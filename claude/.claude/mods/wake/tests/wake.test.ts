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
  const base: WakeChip = { name: 'worker', title: 'Review persisted worker messages', backend: 'codex', account: '01', model: 'gpt-6-sol', effort: 'high', running: true, isStale: false, since: 1, startedAt: 40_000, lastEventAt: 992_000 }
  let shown = [base]
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: shown, version: 1 } }))
  for (const [job, timing] of [
    [base, '8s · turn 16m'],
    [{ ...base, isStale: true, lastEventAt: 100_000 }, 'stalled 15m'],
    [{ ...base, running: false, awaitingRoot: true }, 'done'],
    [{ ...base, awaitingRoot: true, waitingForRoot: true }, 'done'],
  ] as const) {
    shown = [job]
    const bar = await mount($, 'AbovePrompt')
    const tree = (await bar.drawn()) as Node
    const text = flat(tree)
    const row = text.split('\n').find(line => line.includes(base.title!))!
    expect(row).toContain(timing)
    expect(row.indexOf(base.title!) < row.indexOf(timing)).toBe(true)
    expect(text).not.toContain('(worker)')
    expect(JSON.stringify(tree)).toContain('truncate-end')
    await bar.unmount()
  }
})

test('one crew job at 180 columns keeps its status and model next to the title', async ($, on) => {
  engine(on)
  const title = 'Photo ranking feature scan'
  const job: WakeChip = { name: 'ranking', title, backend: 'codex', account: '01', model: 'gpt-6-luna', effort: 'high', running: true, isStale: false, since: 1, lastEventAt: 985_000 }
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: [job], version: 1 } }))
  const bar = await mount($, 'AbovePrompt', false, 180)
  const tree = (await bar.drawn()) as Node
  const slot = boxes(tree).find(node => node.type === 'Box' && typeof node.props?.width === 'number' && node.children?.length === 3 && flat(node).includes(title))!
  expect(flat(slot).replace(/\s+/g, ' ')).toContain(`${title} 15s codex·01 luna high`)
  expect(slot.props!.width).toBe(flat(slot).length - 2) // sized to its words (flat adds a space between its 3 parts)
  const titleBox = slot.children![1] as Exclude<Node, string>
  expect(titleBox.props).toMatchObject({ flexGrow: 0, flexShrink: 1, minWidth: 1 })
  expect(flat(tree).split('codex·01').length - 1).toBe(1)
  await bar.unmount()
})

test('a fitted slot keeps the turn clock, whatever backend runs the job', async ($, on) => {
  engine(on)
  const title = 'Face validation'
  let shown: WakeChip[] = []
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: shown, version: 1 } }))
  for (const [backend, account, model, label] of [['codex', '01', 'gpt-6-luna', 'codex·01 luna high'], ['agy', 'a2', 'gemini-3.8-flash-high', 'agy·a2 flash high']] as const) {
    shown = [{ name: 'v5', title, backend, account, model, effort: 'high', running: true, isStale: false, since: 1, startedAt: 40_000, lastEventAt: 992_000 }]
    const bar = await mount($, 'AbovePrompt', false, 120)
    expect(flat((await bar.drawn()) as Node).replace(/\s+/g, ' ')).toContain(`${title} 8s · turn 16m ${label}`)
    await bar.unmount()
  }
})

test('the quota line leads with the CLI at work and counts unreadable accounts', async ($, on) => {
  engine(on)
  const job: WakeChip = { name: 'takeover', title: 'Face validation', backend: 'agy', account: 'a2', model: 'gemini-3.8-flash-high', effort: '', running: true, isStale: false, since: 1, lastEventAt: 995_000 }
  const quotas = [
    { cli: 'codex', account: '01', plan: 'Pro Lite', active: true, parts: [{ label: 'w', pct: 98 }] },
    { cli: 'codex', account: '02', plan: 'Free', active: false, parts: [] }, // 401
    { cli: 'codex', account: '03', plan: 'Free', active: false, parts: [] }, // timed out
    { cli: 'codex', account: '05', plan: 'Free', active: false, parts: [], status: 'expired' },
    { cli: 'agy', account: 'a1', plan: 'Pro', active: false, parts: [{ label: 'Cw', pct: 0 }, { label: 'Gw', pct: 100 }] },
    { cli: 'agy', account: 'a2', plan: 'Pro', active: false, parts: [{ label: 'Cw', pct: 69 }, { label: 'Gw', pct: 100 }] },
  ]
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: [job], version: 1 } }))
  on('state.get', { plugin: 'wake', key: 'quotas' }, () => ({ value: { value: quotas, version: 1 } }))
  const bar = await mount($, 'AbovePrompt')
  const line = flat((await bar.drawn()) as Node).split('\n').find(row => row.startsWith('quota'))!
  expect(line).toBe('quota agy a1 C w0 · G w100 · a2 C w69 · G w100 │ codex 01* w98 · 3 offline')
  await bar.unmount()
})

test('two crew jobs share the width and identical model details appear once', async ($, on) => {
  engine(on)
  const base: WakeChip = { name: 'review', title: 'Review persisted worker messages', backend: 'codex', account: '01', model: 'gpt-6-sol', effort: 'high', running: true, isStale: false, since: 1, lastEventAt: 989_000 }
  const jobs = [base, { ...base, name: 'provider', title: 'Check provider responses', lastEventAt: 977_000 }]
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: jobs, version: 1 } }))
  for (const width of [60, 100]) {
    const bar = await mount($, 'AbovePrompt', false, width)
    const tree = (await bar.drawn()) as Node
    const text = flat(tree)
    expect(text.indexOf(base.title!) < text.indexOf('11s')).toBe(true)
    expect(text.indexOf('Check provider') < text.indexOf('23s')).toBe(true)
    expect(text).not.toContain('turn ?')
    expect(text).not.toContain('(review)')
    expect(text).not.toContain('(provider)')
    expect(text.split('codex·01').length - 1).toBe(width === 100 ? 1 : 0)
    const slots = boxes(tree).filter(node => node.type === 'Box' && typeof node.props?.width === 'number' && node.props.width < width && node.children?.length === 3)
    expect(slots).toHaveLength(2)
    // each slot is as wide as its words, or as its share when those do not fit
    for (const slot of slots) expect(slot.props!.width as number).toBeLessThanOrEqual(Math.max(flat(slot).length, 1))
    expect(slots.reduce((sum, slot) => sum + (slot.props!.width as number), 0)).toBeLessThanOrEqual(width - 3)
    await bar.unmount()
  }
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
