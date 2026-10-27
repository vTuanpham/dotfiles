import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'
import { crewTiming } from '../hooks/util'
import type { WakeChip } from '../types'

type Node = string | { type: string; props?: Record<string, unknown>; children?: Node[] }

const boxes = (node: Node): Exclude<Node, string>[] => typeof node === 'string' ? [] : [node, ...(node.children ?? []).flatMap(boxes)]

/** Every Text's words and Button's label, in order, one Box row per line. */
function flat(node: Node): string {
  const text = (n: Node): string =>
    typeof n === 'string' ? n : n.type === 'Button' ? `[${String(n.props?.label ?? '')}]` : (n.children ?? []).map(text).join('')
  const rows = (n: Node): string[] => {
    if (typeof n === 'string' || n.type === 'Text' || n.type === 'Button') return [text(n)]
    if (n.type === 'Raster') return ['<mochi>']
    const kids = n.children ?? []
    return n.props?.flexDirection === 'column' ? kids.flatMap(rows) : [kids.map(k => rows(k).join(' ')).join(' ')]
  }
  return rows(node).join('\n')
}

function engine(on: On) {
  const clock = mock.clock(on, { now: 1_000_000 })
  mock.env(on, { HOME: '/home/u' })
  on('session.cwd', () => ({ value: '/proj' }))
  on('session.append', () => ({ uuid: 'x' }) as never)
  on('prompt.submit', (_$, e) => e as never)
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['engine'] }) as never) // the engine's own drawing
  on('turn.start', (_$, e) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))
  on('tool.call', async (_$, e) => {
    if (e.tool === 'Bash' && e.command.includes('fail')) return { isError: true as const, result: 'Exit code 1' as never, text: 'Exit code 1' }
    return { result: {} as never, text: 'ok' }
  })
  return clock
}

type Engine = Parameters<Extract<Parameters<typeof test>[1], (...args: never[]) => unknown>>[0]

const mount = ($: Engine, component: 'AbovePrompt' | 'Spinner', isWorking = false, columns = 100) =>
  $.ui.mount({
    plugin: 'wake',
    surface: 'terminal',
    component,
    props:
      component === 'AbovePrompt'
        ? { hasSurvey: false, isWorking, maxRows: 16, bodyColumns: columns, scroll: { offset: 0, bodyRows: 16 } }
        : { word: 'Working', message: null, suffix: '', mode: 'tool-use' },
  } as never)

test('crew timing distinguishes turn age, recent events, stalled jobs and unacknowledged completion', () => {
  const now = 2_000_000
  const job: WakeChip = { name: 'job', backend: 'codex', account: '01', model: 'sol', effort: 'high', running: true, isStale: false, since: 1, startedAt: now - 16 * 60_000, lastEventAt: now - 8_000 }
  expect(crewTiming(job, now)).toBe('8s · turn 16m')
  expect(crewTiming(job, now, 38)).toBe('8s')
  expect(crewTiming({ ...job, startedAt: undefined }, now)).toBe('8s')
  expect(crewTiming({ ...job, startedAt: now - 20_000 }, now)).toBe('8s')
  expect(crewTiming({ ...job, isStale: true, lastEventAt: now - 15 * 60_000 }, now)).toBe('stalled 15m')
  expect(crewTiming({ ...job, lastEventAt: now - 12 * 60_000, startedAt: now - 14 * 60_000 }, now)).toBe('12m · turn 14m') // a long command
  expect(crewTiming({ ...job, running: false, awaitingRoot: true }, now)).toBe('done')
  expect(crewTiming({ ...job, awaitingRoot: true, waitingForRoot: true }, now)).toBe('done')
  expect(crewTiming({ ...job, startedAt: undefined, lastEventAt: undefined }, now)).toBe('starting')
})

test('rendered crew puts names first and includes done jobs awaiting root', async ($, on) => {
  engine(on)
  const base: WakeChip = { name: 'worker', title: 'Review messages', backend: 'codex', account: '01', model: 'gpt-6-sol', effort: 'high', running: true, isStale: false, since: 1, lastEventAt: 992_000 }
  let shown = [base]
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: shown, version: 1 } }))
  for (const [job, mark] of [[base, '●'], [{ ...base, isStale: true, reason: 'silence' }, '!'], [{ ...base, running: false, awaitingRoot: true }, '✓']] as const) {
    shown = [job]
    const bar = await mount($, 'AbovePrompt')
    const text = flat((await bar.drawn()) as Node)
    const row = text.split('\n').find(line => line.includes(base.title!))!
    expect(row.indexOf(base.title!) < row.indexOf(mark)).toBe(true)
    expect(row).toContain(mark)
    await bar.unmount()
  }
})

test('one crew job at 180 columns keeps its status and model next to the title', async ($, on) => {
  engine(on)
  const job: WakeChip = { name: 'ranking', title: 'Photo ranking feature scan', backend: 'codex', account: '01', model: 'gpt-6-luna', effort: 'high', running: true, isStale: false, since: 1, lastEventAt: 985_000 }
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: [job], version: 1 } }))
  const bar = await mount($, 'AbovePrompt', false, 180)
  const text = flat((await bar.drawn()) as Node)
  expect(text).toContain('Photo ranking feature scan')
  expect(text).toContain('◈◔ ●')
  expect(text).toContain('▁▃▄··') // high effort
  await bar.unmount()
})

test('a fitted row keeps event age, whatever backend runs the job', async ($, on) => {
  engine(on)
  let shown: WakeChip[] = []
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: shown, version: 1 } }))
  for (const [backend, model, mark] of [['codex', 'gpt-6-luna', '◈◔'], ['agy', 'gemini-3.8-flash-high', '✦◔']] as const) {
    shown = [{ name: 'v5', title: 'Face validation', backend, account: '01', model, effort: 'high', running: true, isStale: false, since: 1, lastEventAt: 992_000 }]
    const bar = await mount($, 'AbovePrompt', false, 120)
    const text = flat((await bar.drawn()) as Node)
    expect(text).toContain(mark)
    expect(text).toContain('8s')
    await bar.unmount()
  }
})

test('the quota line leads with the CLI at work and shows unknown accounts', async ($, on) => {
  engine(on)
  const job: WakeChip = { name: 'takeover', title: 'Face validation', backend: 'agy', account: 'a2', model: 'gemini-3-flash', effort: '', running: true, isStale: false, since: 1, lastEventAt: 995_000 }
  const quotas = [
    { cli: 'codex', account: '01', plan: 'Pro', active: true, parts: [{ label: 'w', pct: 100 }] },
    { cli: 'codex', account: '02', plan: 'Free', active: false, parts: [] },
    { cli: 'agy', account: 'a1', plan: 'Pro', active: false, parts: [{ label: 'Cw', pct: 0 }] },
  ]
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: [job], version: 1 } }))
  on('state.get', { plugin: 'wake', key: 'quotas' }, () => ({ value: { value: quotas, version: 1 } }))
  const bar = await mount($, 'AbovePrompt')
  const text = flat((await bar.drawn()) as Node)
  expect(text).toContain('✦a1 Cw0%▱▱▱▱  ◈01* w100%▰▰▰▰  ◈02 ?')
  await bar.unmount()
})

test('two crew jobs get separate compact rows', async ($, on) => {
  engine(on)
  const base: WakeChip = { name: 'review', title: 'Review messages', backend: 'codex', account: '01', model: 'gpt-6-sol', effort: 'high', running: true, isStale: false, since: 1, lastEventAt: 989_000 }
  const jobs = [base, { ...base, name: 'provider', title: 'Check responses', lastEventAt: 977_000 }]
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: jobs, version: 1 } }))
  for (const width of [60, 100]) {
    const bar = await mount($, 'AbovePrompt', false, width)
    const text = flat((await bar.drawn()) as Node)
    const lines = text.split('\n')
    expect(lines.find(line => line.includes('Review messages'))).toContain('11s')
    expect(lines.find(line => line.includes('Check responses'))).toContain('23s')
    expect(lines.find(line => line.includes('Review messages'))).not.toContain('Check responses')
    await bar.unmount()
  }
})

test('mixed model rows keep their own marks in the same columns at each width', async ($, on) => {
  engine(on)
  const base: WakeChip = { name: 'a', title: 'Review messages', backend: 'codex', account: '01', model: 'gpt-6.1-terra', effort: 'high', running: true, isStale: false, since: 1, lastEventAt: 989_000 }
  const jobs = [base, { ...base, name: 'b', title: 'Pairwise research', model: 'gpt-6-sol' }, { ...base, name: 'c', title: 'Unified status', backend: 'agy', model: 'fable' }]
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: jobs, version: 1 } }))
  for (const width of [32, 60, 100]) {
    const bar = await mount($, 'AbovePrompt', false, width)
    const lines = flat((await bar.drawn()) as Node).split('\n')
    const marks = ['◈◑', '◈◕', '✦◉']
    const rows = marks.map(mark => lines.find(line => line.includes(mark))!)
    expect(rows.every(Boolean)).toBe(true)
    expect(rows.map((line, i) => line.indexOf(marks[i]!))).toEqual([rows[0]!.indexOf('◈◑'), rows[0]!.indexOf('◈◑'), rows[0]!.indexOf('◈◑')])
    expect(rows.every(line => line.includes('●'))).toBe(true)
    await bar.unmount()
  }
})

test('the crew legend is available on demand', async ($, on) => {
  engine(on)
  const result = await $.command.run({ command: 'wake', args: 'legend', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } } as never)
  expect(result.text).toContain('⌁ heavy queue')
  expect(result.text).toContain('▣▰▱ is memory against the job cap')
  expect(result.text).toContain('↗/↙')
})

test('a larger crew gets the available rows when the scene would hide workers', async ($, on) => {
  engine(on)
  const jobs: WakeChip[] = Array.from({ length: 8 }, (_, i) => ({ name: `job${i}`, title: `Worker ${i}`, backend: 'codex', account: '01', model: 'sol', effort: 'high', running: true, isStale: false, since: 1, lastEventAt: 995_000 }))
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: jobs, version: 1 } }))
  const bar = await mount($, 'AbovePrompt', false, 80)
  const text = flat((await bar.drawn()) as Node)
  for (const job of jobs) expect(text).toContain(job.title!)
  expect(text).not.toContain('<mochi>')
  await bar.unmount()
})

test('the plan rides in the spinner; the dock says what is happening now', async ($, on) => {
  engine(on)
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.call({
    tool: 'TodoWrite',
    todos: [
      { content: 'Read the code', status: 'completed', activeForm: 'Reading the code' },
      { content: 'Migrate callers', status: 'in_progress', activeForm: 'Migrating callers' },
      { content: 'Run tests', status: 'pending', activeForm: 'Running tests' },
    ],
  } as never)
  const spinner = await mount($, 'Spinner')
  const line = flat((await spinner.drawn()) as Node)
  expect(line).toContain('Migrating callers')
  expect(line).toContain('2/3')
  await spinner.unmount()

  const dock = await mount($, 'AbovePrompt', true)
  const drawn = (await dock.drawn()) as Node
  const text = flat(drawn)
  expect(text).toContain('Planning') // what the main agent is doing now
  expect(text).toContain('turn 1')
  expect(text).toContain('plan')
  expect(text).not.toContain('away')
  await dock.unmount()
})

test('after ten idle minutes a recap waits above the prompt, from the log when no model answers', async ($, on) => {
  const clock = engine(on)
  await $.prompt.submit({ text: 'fix the parser' } as never)
  await $.turn.start({ text: 'fix the parser', turnId: 't1' })
  await $.tool.call({ tool: 'Edit', file_path: '/proj/src/parse.ts', old_string: 'a', new_string: 'a\nb' } as never)
  await $.tool.call({ tool: 'Bash', command: 'uv run pytest tests/test_parse.py' } as never)
  await $.turn.complete({ answer: 'Fixed the parser. All parse tests pass.', durationMs: 60_000, isAborted: false, turnId: 't1', reason: 'answer' } as never)
  await clock.advance(10 * 60_000 + 1)

  const bar = await mount($, 'AbovePrompt')
  const tree = (await bar.drawn()) as Node
  const drawn = flat(tree)
  expect(drawn).toContain('+2') // the session's diff tally
  expect(drawn).toContain('−1')
  expect(drawn).toContain('while you were away')
  expect(drawn).toContain('from the log')
  expect(drawn).toContain('<mochi>')
  await bar.unmount()
})
