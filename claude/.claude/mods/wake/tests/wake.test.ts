import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'
import { COLOR, crewFreshness, crewName, readable } from '../hooks/util'
import type { WakeChip, WakeQuota } from '../types'

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

test('freshness uses shapes instead of clocks; only stalls keep exact minutes', () => {
  const now = 2_000_000
  const job: WakeChip = { name: 'job', backend: 'codex', account: '01', model: 'sol', effort: 'high', running: true, isStale: false, since: 1, startedAt: now - 16 * 60_000, lastEventAt: now - 8_000 }
  expect(crewFreshness(job, now)).toBe('▰▰')
  expect(crewFreshness({ ...job, lastEventAt: now - 30_000 }, now)).toBe('▰▱')
  expect(crewFreshness({ ...job, lastEventAt: now - 120_000 }, now)).toBe('▱▱')
  expect(crewFreshness({ ...job, isStale: true, lastEventAt: now - 15 * 60_000 }, now)).toBe('15m')
  expect(crewFreshness({ ...job, running: false, awaitingRoot: true }, now)).toBe('')
  expect(crewFreshness({ ...job, waitingForRoot: true }, now)).toBe('')
  expect(crewFreshness({ ...job, attention: 'question' }, now)).toBe('')
  expect(crewFreshness({ ...job, lastEventAt: undefined }, now)).toBe('▱▱')
  expect(crewName({ name: 'review', title: 'Review persisted worker messages' }, 20)).toBe('review')
  expect(crewName({ name: 'review', title: 'Review persisted worker messages' }, 100)).toBe('Review persisted worker…')
})

test('one crew job at 180 columns packs its freshness and badge beside its shortened title', async ($, on) => {
  engine(on)
  const title = 'Photo ranking feature scan'
  const job: WakeChip = { name: 'ranking', title, backend: 'codex', account: '01', model: 'gpt-6-luna', effort: 'high', running: true, isStale: false, since: 1, lastEventAt: 985_000 }
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: [job], version: 1 } }))
  const bar = await mount($, 'AbovePrompt', false, 180)
  const tree = (await bar.drawn()) as Node
  const row = boxes(tree).find(node => node.type === 'Text' && node.props?.wrap === 'truncate-end' && flat(node).includes('luna·hi'))!
  expect(flat(row)).toBe('⣾ Photo ranking feature s… ▰▰ luna·hi')
  expect(/ {3,}/.test(flat(row))).toBe(false)
  expect(boxes(row).some(node => node.type === 'Box')).toBe(false)
  await bar.unmount()
})

for (const width of [60, 100, 180]) test(`crew and quotas pack left at ${width} columns with distinct status shapes`, async ($, on) => {
  engine(on)
  const base: WakeChip = { name: 'review', title: 'Review persisted worker messages', backend: 'codex', account: '01', model: 'gpt-6-sol', effort: 'high', running: true, isStale: false, since: 1, lastEventAt: 989_000 }
  let jobs = [base, { ...base, name: 'provider', title: 'Check provider responses', lastEventAt: 977_000 }]
  const quotas: WakeQuota[] = [
    { cli: 'codex', account: '01', active: true, plan: 'Pro', parts: [{ label: 'w', pct: 75 }] },
    { cli: 'codex', account: '02', active: false, plan: 'Pro', parts: [{ label: 'w', pct: 25 }] },
    { cli: 'codex', account: '03', active: false, plan: 'Pro', parts: [], status: 'expired' },
    { cli: 'agy', account: 'a1', active: false, plan: 'Pro', parts: [{ label: 'Gh', pct: 100 }, { label: 'Gw', pct: 50 }] },
  ]
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: jobs, version: 1 } }))
  on('state.get', { plugin: 'wake', key: 'quotas' }, () => ({ value: { value: quotas, version: 1 } }))
  for (const [change, glyph, color] of [
    [{}, '⣾', 'teal'],
    [{ running: false, awaitingRoot: true }, '✓', 'green'],
    [{ isStale: true, lastEventAt: 40_000 }, '◷16m', 'peach'],
    [{ attention: 'question' }, '?', 'red'],
    [{ attention: 'error', running: false }, '!', 'red'],
  ] as const) {
    jobs = [{ ...base, ...change }, jobs[1]!]
    const bar = await mount($, 'AbovePrompt', false, width)
    const tree = (await bar.drawn()) as Node
    const text = flat(tree)
    const row = boxes(tree).find(node => node.type === 'Text' && node.props?.wrap === 'truncate-end' && flat(node).includes('sol·hi'))!
    const quota = boxes(tree).find(node => node.type === 'Text' && flat(node).startsWith('% '))!
    const line = flat(row)
    expect(line.startsWith(`${glyph} `)).toBe(true)
    expect(line.split('sol·hi').length - 1).toBe(1)
    expect(line.length <= width).toBe(true)
    expect(/ {3,}/.test(line)).toBe(false)
    expect(boxes(row).some(node => node.type === 'Box')).toBe(false)
    expect(/\d+s|turn |active |stalled |done/.test(line)).toBe(false)
    expect(flat(quota)).toBe('% c01*:w▆·02:w▂·03:!·a1:Gh█Gw▄')
    expect(/ {3,}/.test(flat(quota))).toBe(false)
    const floor = boxes(tree).find(node => typeof node.props?.backgroundColor === 'string')?.props?.backgroundColor as string | undefined
    const ink = floor ? readable(floor) : COLOR
    expect(boxes(row).find(node => flat(node) === `${glyph} `)?.props?.color).toBe(ink[color])
    if (glyph === '⣾') expect(line).toBe(width === 60
      ? '⣾ review ▰▰ │ ⣾ provider ▰▰ sol·hi'
      : '⣾ Review persisted worker… ▰▰ │ ⣾ Check provider responses ▰▰ sol·hi')
    await bar.unmount()
  }
  jobs = [{ ...base, account: '02' }]
  const bar = await mount($, 'AbovePrompt', false, width)
  const line = flat((await bar.drawn()) as Node)
  expect(line).toContain('sol·hi@02')
  await bar.unmount()
})

test('six mixed jobs at 60 columns keep names and state instead of overflowing with badges', async ($, on) => {
  engine(on)
  const names = ['audit', 'test', 'docs', 'core', 'ui', 'lint']
  const models = ['gpt-6-sol', 'gpt-6-luna', 'gpt-6-astra', 'gemini-3-flash', 'claude-sonnet-5', 'claude-opus-5']
  const backends = ['codex', 'codex', 'codex', 'agy', 'claude', 'agy']
  const jobs: WakeChip[] = names.map((name, i) => ({ name, title: `Long descriptive title for ${name}`, backend: backends[i]!, account: '', model: models[i]!, effort: 'high', running: true, isStale: false, since: 1, lastEventAt: 999_000 }))
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: jobs, version: 1 } }))
  const bar = await mount($, 'AbovePrompt', false, 60)
  const tree = (await bar.drawn()) as Node
  const row = boxes(tree).find(node => node.type === 'Text' && node.props?.wrap === 'truncate-end' && flat(node).includes('audit'))!
  const line = flat(row)
  for (const name of names) expect(line).toContain(name)
  expect(line.length <= 60).toBe(true)
  expect(/ {3,}/.test(line)).toBe(false)
  expect(line).not.toContain('·hi')
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
