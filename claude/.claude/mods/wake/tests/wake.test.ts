import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'
import { LANDSCAPES } from '../hooks/landscapes'
import { CAT_COLUMNS, sceneCardBounds, sceneFrame, type SceneInput } from '../hooks/scene'
import { crewTiming, isTestCommand } from '../hooks/util'
import ScenePointer from '../hooks/scene-hover'
import type { WakeAgent, WakeChip } from '../types'

type Node = string | { type: string; props?: Record<string, unknown>; children?: Node[] }

const boxes = (node: Node): Exclude<Node, string>[] => typeof node === 'string' ? [] : [node, ...(node.children ?? []).flatMap(boxes)]

/** Every Text's words and Button's label, in order, one Box row per line. */
function flat(node: Node, includeHidden = false): string {
  const text = (n: Node): string =>
    typeof n === 'string' ? n : n.type === 'Button' ? `[${String(n.props?.label ?? '')}]` : (n.children ?? []).map(text).join('')
  const rows = (n: Node): string[] => {
    if (typeof n === 'string' || n.type === 'Text' || n.type === 'Button') return [text(n)]
    if (n.type === 'Image') return [String(n.props?.alt ?? '').slice(0, 2).padEnd(2)]
    if (n.type === 'Raster') return ['<mochi>']
    if (!includeHidden && n.type === 'Box' && n.props?.display === 'none') return []
    const kids = n.children ?? []
    return n.props?.flexDirection === 'column' ? kids.flatMap(rows) : [kids.map(k => rows(k).join('')).join('')]
  }
  return rows(node).join('\n')
}

function engine(on: On, appended?: (message: unknown) => void) {
  const clock = mock.clock(on, { now: 1_000_000 })
  mock.env(on, { HOME: '/home/u' })
  on('session.cwd', () => ({ value: '/proj' }))
  on('session.append', (_$, e, next) => {
    appended?.(e.message)
    return next(e)
  })
  on('classic.SessionStart', () => ({}))
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

const mount = ($: Engine, component: 'AbovePrompt' | 'Spinner', isWorking = false, columns = 100, maxRows = 16) =>
  $.ui.mount({
    plugin: 'wake',
    surface: 'terminal',
    component,
    props:
      component === 'AbovePrompt'
        ? { hasSurvey: false, isWorking, maxRows, bodyColumns: columns, scroll: { offset: 0, bodyRows: maxRows } }
        : { word: 'Working', message: null, suffix: '', mode: 'tool-use' },
  } as never)

test('idle scene advances over time without input', async ($, on) => {
  const clock = engine(on)
  const frames: string[] = []
  on('ui.blit', async (_$, e, next) => {
    if ('cells' in e) frames.push(e.cells)
    return next(e)
  })
  const bar = await mount($, 'AbovePrompt', false, 100, 16)
  await clock.advance(1_000)
  expect(frames.length).toBeGreaterThan(1)
  expect(new Set(frames).size).toBeGreaterThan(1)
  await bar.unmount()
})

test('a denied blit is retried', async ($, on) => {
  const clock = engine(on)
  let attempts = 0
  on('ui.blit', async (_$, e, next) => {
    attempts++
    return attempts === 1 ? { deny: 'not mounted yet' } : next(e)
  })
  const bar = await mount($, 'AbovePrompt', false, 100, 16)
  await clock.advance(1_000)
  expect(attempts).toBeGreaterThan(1)
  await bar.unmount()
})

test('a denied old-size blit does not disable a newly rendered scene', async ($, on) => {
  const clock = engine(on)
  let release!: () => void
  let started!: () => void
  const blocked = new Promise<void>(resolve => { release = resolve })
  const entered = new Promise<void>(resolve => { started = resolve })
  const widths: number[] = []
  on('ui.blit', async (_$, e, next) => {
    widths.push(e.columns!)
    if (widths.length === 1) { started(); await blocked; return { deny: 'stale size' } }
    return next(e)
  })
  const old = await mount($, 'AbovePrompt', false, 100, 16)
  await clock.advance(50)
  await entered
  const newer = await mount($, 'AbovePrompt', false, 80, 16)
  release()
  await clock.advance(1_000)
  expect(widths).toContain(80)
  await newer.unmount()
  await old.unmount()
})

test('persistent blit denials back off while waiting for a mount', async ($, on) => {
  const clock = engine(on)
  let attempts = 0
  on('ui.blit', async () => { attempts++; return { deny: 'not mounted' } })
  const bar = await mount($, 'AbovePrompt', false, 100, 16)
  await clock.advance(5_000)
  expect(attempts).toBeGreaterThan(1)
  expect(attempts).toBeLessThan(20)
  await bar.unmount()
})

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

test('test command recognition uses executable position and preserves outer status evidence', () => {
  for (const command of [
    'echo pytest tests/test_parse.py',
    'printf "%s" "pytest later"',
    'rg pytest src/',
    'grep -R "cargo test" docs/',
    'echo harmless # pytest is a comment',
    'TEST_COMMAND=pytest echo ready',
    'cat <<\'EOF\'\npytest\nEOF',
    'case "$x" in pytest) echo x;; esac',
    'function pytest() { echo no; }',
    'pytest || echo recovered',
    'pytest | tee output.log',
    'pytest; echo recovered',
    'pytest && echo done',
    'pytest | cat | pytest',
    'echo $(pytest tests/)',
    'cat <(pytest tests/)',
    '! pytest tests/',
    'pytest --version',
    'pytest --help',
    'pytest --collect-only tests/',
    'pytest --co tests/',
    'python3.12 -m pytest --collect-only tests/',
    'pytest --setup-only',
    'pytest --collect-only=true',
    'true || pytest tests/',
    'true || (pytest tests/)',
    'true || (echo x; pytest tests/)',
    '! (pytest tests/)',
    '! (echo x; pytest tests/)',
    'echo x && ! (pytest tests/)',
    '(cd repo && npm run test)',
    'pytest (test params)',
    'go test -list . ./...',
    'go test -list=. ./...',
    'go test -help',
    'go test --help',
    'cargo test --help',
    'cargo test -- --list',
    'bun test --help',
    'vitest list',
    'jest --showConfig',
    'npm test --help',
    'if make setup; then go test ./...; fi',
  ]) expect(isTestCommand(command)).toBe(false)

  for (const command of [
    'pytest tests/',
    'python -m pytest tests/',
    'python3.12 -m pytest tests/',
    'go test ./...',
    'cargo test --workspace',
    'npm test',
    'npm run test -- --watch=false',
    'pnpm test',
    'yarn run test',
    'bun test',
    'rtk test cargo test ./...',
    'cd repo && uv run pytest tests/',
    'echo preparing; cargo test --workspace',
    'printf "%s" "! || (not shell syntax)"; pytest tests/',
    'env CI=1 timeout 30s rtk proxy uv run --frozen pytest tests/',
    'env CI=1 rtk test timeout 30s python3.12 -m pytest tests/',
  ]) expect(isTestCommand(command)).toBe(true)
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

test('bounded crew pages expose every worker, including native subagents', async ($, on) => {
  engine(on)
  const jobs: WakeChip[] = Array.from({ length: 7 }, (_, i) => ({ id: `owner/${i}`, name: `worker-${i}`, title: `Worker ${i}`, backend: 'codex', account: '01', model: 'gpt-6-sol', effort: 'high', running: true, isStale: false, since: 1 }))
  const agents: WakeAgent[] = [{ id: 'agent', type: 'worker', name: 'Native agent', description: 'native', since: 1 }]
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: jobs, version: 1 } }))
  on('state.get', { plugin: 'wake', key: 'subagents' }, () => ({ value: { value: agents, version: 1 } }))
  const bar = await mount($, 'AbovePrompt', false, 40, 7)
  const pages: string[] = []
  for (let i = 0; i < 2; i++) {
    pages.push(flat((await bar.drawn()) as Node))
    await bar.press({ key: 'crew-next' })
  }
  expect(pages.join('\n')).toContain('Native agent')
  for (const job of jobs) expect(pages.join('\n')).toContain(job.title!)
  expect(pages[0]).toContain('crew 1/2')
  expect(pages[1]).toContain('crew 2/2')
  await bar.unmount()
})

test('a one-row crew pager still exposes every worker', async ($, on) => {
  engine(on)
  const jobs: WakeChip[] = Array.from({ length: 3 }, (_, i) => ({ id: `owner/${i}`, name: `worker-${i}`, title: `Worker ${i}`, backend: 'codex', account: '01', model: 'gpt-6-sol', effort: 'high', running: true, isStale: false, since: 1 }))
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: jobs, version: 1 } }))
  const bar = await mount($, 'AbovePrompt', false, 24, 3)
  const pages: string[] = []
  for (let i = 0; i < jobs.length; i++) {
    pages.push(flat((await bar.drawn()) as Node))
    await bar.press({ key: 'crew-next' })
  }
  for (const job of jobs) expect(pages.join('\n')).toContain(job.title!)
  await bar.unmount()
})

test('urgent actions remain visible in two rows with a large crew', async ($, on) => {
  engine(on)
  const jobs: WakeChip[] = Array.from({ length: 8 }, (_, i) => ({ id: `owner/${i}`, name: `worker-${i}`, backend: 'codex', account: '01', model: 'gpt-6-sol', effort: 'high', running: true, isStale: false, since: 1 }))
  jobs[0]!.waitingPeer = { target: 'owner/reviewer', declaredAt: 1 }
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: jobs, version: 1 } }))
  on('state.get', { plugin: 'wake', key: 'subagents' }, () => ({ value: { value: [{ id: 'native', type: 'worker', name: 'Native reviewer', description: 'native', since: 1 }], version: 1 } }))
  on('state.get', { plugin: 'wake', key: 'needs' }, () => ({ value: { value: [{ id: 'n', kind: 'codex-ask', job: 'worker', text: 'Choose a path', at: 1 }], version: 1 } }))
  on('state.get', { plugin: 'wake', key: 'calls' }, () => ({ value: { value: [{ id: 'c', text: 'Use blue?', answer: 'blue' }], version: 1 } }))
  const bar = await mount($, 'AbovePrompt', false, 80, 4)
  const text = flat((await bar.drawn()) as Node)
  expect(text).toContain('Choose a path')
  expect(text).toContain('[reply]')
  expect(text).toContain('Use blue?')
  expect(text).toContain('[inspect]')
  const result = await $.command.run({ command: 'wake', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } } as never)
  expect(result.text).toContain('Native reviewer')
  expect(result.text).toContain('worker-0')
  expect(result.text).toContain('waiting for owner/reviewer')
  await bar.unmount()
})

test('quota details remain reachable through wake when crew is paged', async ($, on) => {
  engine(on)
  const jobs: WakeChip[] = Array.from({ length: 8 }, (_, i) => ({ id: `owner/${i}`, name: `worker-${i}`, backend: 'codex', account: '01', model: 'gpt-6-sol', effort: 'high', running: true, isStale: false, since: 1 }))
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: jobs, version: 1 } }))
  on('state.get', { plugin: 'wake', key: 'quotas' }, () => ({ value: { value: [{ cli: 'codex', account: '01', plan: 'Pro', active: true, parts: [{ label: '5h', pct: 42, resets: 'tomorrow' }] }], version: 1 } }))
  const bar = await mount($, 'AbovePrompt', false, 80, 7)
  expect(flat((await bar.drawn()) as Node)).toContain('quotas: /wake')
  const result = await $.command.run({ command: 'wake', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } } as never)
  expect(result.text).toContain('5h42%')
  expect(result.text).toContain('tomorrow')
  await bar.unmount()
})

test('one crew job at 180 columns keeps its status and model next to the title', async ($, on) => {
  engine(on)
  const job: WakeChip = { name: 'ranking', title: 'Photo ranking feature scan', backend: 'codex', account: '01', model: 'gpt-6-luna', effort: 'high', running: true, isStale: false, since: 1, lastEventAt: 985_000 }
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: [job], version: 1 } }))
  const bar = await mount($, 'AbovePrompt', false, 180)
  const text = flat((await bar.drawn()) as Node)
  expect(text).toContain('Photo ranking feature scan')
  expect(text).toContain('Co◔ ●')
  expect(text).toContain('▁▃▄··') // high effort
  await bar.unmount()
})

test('a fitted row keeps event age, whatever backend runs the job', async ($, on) => {
  engine(on)
  let shown: WakeChip[] = []
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: shown, version: 1 } }))
  for (const [backend, model, mark] of [['codex', 'gpt-6-luna', 'Co◔'], ['agy', 'gemini-3.8-flash-high', 'An◔']] as const) {
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
    { cli: 'codex', account: '01', plan: 'Pro', active: true, parts: [{ label: 'w', pct: 100, resets: null }] },
    { cli: 'codex', account: '02', plan: 'Free', active: false, parts: [] },
    { cli: 'agy', account: 'a1', plan: 'Pro', active: false, parts: [{ label: 'Cw', pct: 0, resets: null }] },
  ]
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: [job], version: 1 } }))
  on('state.get', { plugin: 'wake', key: 'quotas' }, () => ({ value: { value: quotas, version: 1 } }))
  const bar = await mount($, 'AbovePrompt')
  const text = flat((await bar.drawn()) as Node)
  expect(text).toContain('Ana1 Cw0%▱▱▱▱  Co01* w100%▰▰▰▰  Co02 ?')
  await bar.unmount()
})

test('crew, model and quota marks carry per-item details and keep the text legend', async ($, on) => {
  engine(on)
  const job: WakeChip = { name: 'review', title: 'Review messages', backend: 'codex', account: '01', model: 'gpt-6.1-terra', effort: 'high', running: true, isStale: false, since: 1, lastEventAt: 995_000 }
  const agent: WakeAgent = { id: 'agent1', type: 'worker', description: 'Review worker', since: 1, model: 'claude-sonnet-5-5' }
  const quotas = [{ cli: 'agy', account: 'a1', plan: 'Pro', active: false, parts: [{ label: 'Cw', pct: 25, resets: 'in 2 hours' }] }]
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: [job], version: 1 } }))
  on('state.get', { plugin: 'wake', key: 'quotas' }, () => ({ value: { value: quotas, version: 1 } }))
  on('state.get', { plugin: 'wake', key: 'subagents' }, () => ({ value: { value: [agent], version: 1 } }))
  const bar = await mount($, 'AbovePrompt', false, 100)
  const tree = (await bar.drawn()) as Node
  const nodes = boxes(tree)
  const keys = nodes.flatMap(node => typeof node.props?.key === 'string' ? [node.props.key] : [])
  const text = flat(tree, true)
  for (const key of ['wake-agent-harness-0', 'wake-agent-model-0', 'wake-crew-harness-0', 'wake-crew-model-0', 'wake-quota-0-0']) expect(keys).toContain(key)
  const modelMark = nodes.find(node => node.type === 'Box' && node.props?.key === 'wake-crew-model-0')
  expect(modelMark?.children?.some(node => typeof node !== 'string' && node.type === 'Box' && node.props?.display === 'none')).toBe(true)
  expect(text).toContain('Model ID: gpt-6.1-terra')
  expect(text).toContain('Model ID: claude-sonnet-5-5')
  expect(text).toContain('reset: in 2 hours')
  await bar.unmount()
  const legend = await $.command.run({ command: 'wake', args: 'legend', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } } as never)
  expect(legend.text).toContain('Hover crew marks')
  expect(legend.text).toContain('source reset text when available')
})

test('harness images and model maker images remain separate', async ($, on) => {
  engine(on)
  const job: WakeChip = { name: 'mixed', backend: 'agy', account: 'a1', model: 'claude-sonnet-5-5', effort: '', running: true, isStale: false, since: 1 }
  let jobs = [job]
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: jobs, version: 1 } }))
  const bar = await mount($, 'AbovePrompt', false, 80)
  let nodes = boxes((await bar.drawn()) as Node)
  const harness = nodes.find(node => node.props?.key === 'wake-crew-harness-0')!
  const model = nodes.find(node => node.props?.key === 'wake-crew-model-0')!
  expect(boxes(harness).find(node => node.type === 'Image')?.props?.alt).toBe('Antigravity')
  expect(boxes(model).find(node => node.type === 'Image')?.props?.alt).toBe('Anthropic')
  const picture = boxes(harness).find(node => node.type === 'Image')!
  expect(picture.props?.columns).toBe(2)
  expect(picture.props?.rows).toBe(1)
  expect((picture.props?.source as { png: string }).png.startsWith('iVBORw0KGgo')).toBe(true)
  await bar.unmount()
  jobs = [{ ...job, model: 'unknown-model' }]
  const second = await mount($, 'AbovePrompt', false, 80)
  nodes = boxes((await second.drawn()) as Node)
  expect(boxes(nodes.find(node => node.props?.key === 'wake-crew-model-0')!).some(node => node.type === 'Image')).toBe(false)
  await second.unmount()
})

test('nonterminal surfaces retain a full text label in the fallback', async ($, on) => {
  engine(on)
  const job: WakeChip = { name: 'worker', backend: 'agy', account: 'a1', model: 'unknown', effort: '', running: true, isStale: false, since: 1 }
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: [job], version: 1 } }))
  const bar = await $.ui.mount({ plugin: 'wake', surface: 'desktop', component: 'AbovePrompt', props: { hasSurvey: false, isWorking: false, maxRows: 16, bodyColumns: 80, scroll: { offset: 0, bodyRows: 16 } } } as never)
  const harness = boxes((await bar.drawn()) as Node).find(node => node.props?.key === 'wake-crew-harness-0')!
  expect(boxes(harness).some(node => node.type === 'Image')).toBe(false)
  expect(boxes(harness).some(node => node.type === 'Box' && node.props?.width === 2)).toBe(true)
  expect(flat(harness)).toContain('Antigravity')
  await bar.unmount()
})

/** Decode the documented Raster triplets, including text drawn by blit. */
function rasterWords(encoded: string): Uint32Array {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
  const bytes = new Uint8Array(encoded.length / 4 * 3)
  for (let i = 0, at = 0; i < encoded.length; i += 4) {
    const value = alphabet.indexOf(encoded[i]!) << 18 | alphabet.indexOf(encoded[i + 1]!) << 12
      | alphabet.indexOf(encoded[i + 2]!) << 6 | alphabet.indexOf(encoded[i + 3]!)
    bytes[at++] = value >>> 16
    bytes[at++] = value >>> 8
    bytes[at++] = value
  }
  return new Uint32Array(bytes.buffer)
}
const rasterText = (encoded: string) => Array.from(rasterWords(encoded)).filter((_, i) => i % 3 === 0).map(cp => String.fromCharCode(cp)).join('')

function observeScene(on: On) {
  let encoded = ''
  on('ui.blit', (_$, e) => {
    if ('cells' in e) encoded = e.cells
    return { value: {} } // The kit does not paint a terminal; supply the successful blit result.
  })
  return () => rasterText(encoded)
}

test('pointer selection and the animated scene share one Raster; leave and reset preserve detail semantics', async ($, on) => {
  const clock = engine(on)
  const drawn = observeScene(on)
  let preset: 'city' | 'harbor' = 'city'
  on('state.get', { plugin: 'wake', key: 'surroundings' }, () => ({ value: { value: { place: { key: 'fixture', name: 'Fixture', country: '', lat: 0, lon: 0, source: 'named' }, preset, presetSource: 'pinned', weather: null }, version: 1 } }))
  const bar = await mount($, 'AbovePrompt', false, 100)
  const pointer = bar as unknown as { pointer: (event: { type: 'move' | 'leave'; x: number; y: number }) => Promise<void> }
  await pointer.pointer({ type: 'move', x: 0, y: 0 })
  await clock.advance(100)
  expect(drawn()).toContain('Sky')
  await pointer.pointer({ type: 'move', x: 100 - CAT_COLUMNS, y: 4 })
  await clock.advance(100)
  expect(drawn()).toContain('Mochi')
  expect(drawn()).toContain('Session mood:')
  expect(flat((await bar.drawn({ in: 'scene-pointer' })) as Node)).toBe('')
  preset = 'harbor'
  await clock.advance(2_000)
  expect(drawn()).toContain('Session mood:')
  await pointer.pointer({ type: 'move', x: 100 - CAT_COLUMNS, y: 4 })
  await clock.advance(100)
  expect(drawn()).toContain('Session mood:')
  await pointer.pointer({ type: 'leave', x: 100 - CAT_COLUMNS, y: 4 })
  await clock.advance(100)
  expect(drawn()).not.toContain('/wake detail')
  const detail = await $.command.run({ command: 'wake', args: 'detail', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } } as never)
  expect(detail.text).toContain('Mochi')
  await $.classic.SessionStart({ source: 'clear' })
  const cleared = await $.command.run({ command: 'wake', args: 'detail', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } } as never)
  expect(cleared.text).toBe('No scene object has been selected.')
  await bar.unmount()
})

test('Raster cards stay inside the scene and leave status and crew unchanged at every band size', async ($, on) => {
  const clock = engine(on)
  const drawn = observeScene(on)
  const job: WakeChip = { id: 'owner/a', name: 'worker', title: 'Review work', backend: 'codex', account: '01', model: 'gpt-6-sol', effort: 'high', running: true, isStale: false, since: 1 }
  let jobs: WakeChip[] = []
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: jobs, version: 1 } }))
  on('state.get', { plugin: 'wake', key: 'surroundings' }, () => ({ value: { value: { place: { key: 'fixture', name: 'Fixture', country: '', lat: 0, lon: 0, source: 'named' }, preset: 'city', presetSource: 'pinned', weather: { fetchedAt: 1_000_000, utcOffsetSeconds: 0, temp: 24, code: 3, isDay: true, cloud: 0.8, precipitation: 0, snowfall: 0, wind: 4, sunrise: 6, sunset: 18, hours: [] } }, version: 1 } }))
  for (const width of [40, 100, 180]) for (const maxRows of [10, 12, 16]) {
    jobs = maxRows === 10 ? [] : [job, { ...job, id: 'owner/b', name: 'second' }, { ...job, id: 'owner/c', name: 'third' }]
    const bar = await mount($, 'AbovePrompt', false, width, maxRows)
    const before = (await bar.drawn()) as Node
    const headline = flat(boxes(before).find(node => node.props?.key === 'wake-headline')!)
    expect(headline).toContain('Fixture')
    expect(headline).toContain('24°')
    expect(headline).toContain('0 turns')
    const pointer = bar as unknown as { pointer: (event: { type: 'move' | 'leave'; x: number; y: number }) => Promise<void> }
    const x = width - CAT_COLUMNS, y = Math.floor((LANDSCAPES.city.ground - 5) / 2)
    await pointer.pointer({ type: 'move', x, y })
    await clock.advance(100)
    expect(drawn()).toContain('Session mood:')
    const tree = (await bar.drawn()) as Node
    expect(flat(boxes(tree).find(node => node.props?.key === 'wake-headline')!)).toBe(headline)
    expect(boxes(tree).some(node => node.props?.key === 'scene-card-slot')).toBe(false)
    expect(boxes(tree).filter(node => node.type === 'Raster')).toHaveLength(1)
    if (jobs.length) expect(flat(tree)).toContain('Review work')
    const bounds = sceneCardBounds(width, 8, { x, y, details: ['Session mood: idle'] })!
    expect(bounds.left + bounds.width <= width && bounds.top + bounds.height <= 8).toBe(true)
    await pointer.pointer({ type: 'move', x: bounds.left + 1, y: bounds.top })
    await clock.advance(100)
    expect(drawn()).toContain('Session mood:')
    await pointer.pointer({ type: 'leave', x: 0, y: 0 })
    await bar.unmount()
  }
})

test('the pointer Client accepts retained props and never draws or schedules local updates', () => {
  const posts: unknown[] = []
  let listener!: (event: { type: string; x: number; y: number }) => void
  for (const props of [null, { epoch: 'old', columns: 100, rows: 8 }]) {
    const tree = ScenePointer(props, {
      columns: 100, rows: 8,
      elements: { Box: (props: unknown) => ({ type: 'Box', props }) },
      setState: () => { throw new Error('pointer capture must not invalidate the Client') },
      onPointer: (fn: typeof listener) => { listener = fn; return () => {} },
      post: (data: unknown) => posts.push(data),
    } as never) as Node
    expect(boxes(tree)).toHaveLength(1)
    listener({ type: 'move', x: 3, y: 1 })
  }
  expect(posts).toEqual([{ type: 'move', x: 3, y: 1 }, { type: 'move', x: 3, y: 1 }])
})

test('mouse movement writes no reactive state or band drawing; unrelated redraw and resize retain the card', async ($, on) => {
  const clock = engine(on)
  const drawn = observeScene(on)
  let bandReads = 0, writes = 0
  on('state.get', { plugin: 'wake', key: 'tally' }, (_$, e, next) => { bandReads++; return next(e) })
  on('state.set', (_$, e, next) => { writes++; return next(e) })
  const bar = await mount($, 'AbovePrompt', false, 100, 10)
  const pointer = bar as unknown as { pointer: (event: { type: 'move' | 'leave'; x: number; y: number }) => Promise<void> }
  const beforeReads = bandReads, beforeWrites = writes
  for (const x of [0, 1, 2, 3]) await pointer.pointer({ type: 'move', x, y: 0 })
  expect(bandReads).toBe(beforeReads)
  expect(writes).toBe(beforeWrites)
  await clock.advance(100)
  expect(drawn()).toContain('Sky')
  await bar.redraw()
  expect(rasterText(String(boxes((await bar.drawn()) as Node).find(node => node.type === 'Raster')!.props!.cells))).toContain('Sky')
  await bar.redraw({ hasSurvey: false, isWorking: false, maxRows: 10, bodyColumns: 40, scroll: { offset: 0, bodyRows: 10 } } as never)
  const resized = boxes((await bar.drawn()) as Node).find(node => node.type === 'Raster')!
  expect(resized.props?.columns).toBe(40)
  expect(rasterText(String(resized.props!.cells))).toContain('Sky')
  await $.classic.SessionStart({ source: 'clear' })
  await clock.advance(100)
  expect(drawn()).not.toContain('/wake detail')
  await pointer.pointer({ type: 'move', x: 0, y: 0 })
  await pointer.pointer({ type: 'leave', x: 0, y: 0 })
  await clock.advance(100)
  expect(drawn()).not.toContain('/wake detail')
  await bar.unmount()
})

test('hiding the scene keeps rendering pure and retains the last selected details', async ($, on) => {
  engine(on)
  let forbidWrites = false
  on('state.set', (_$, e, next) => {
    if (forbidWrites) throw new Error('state writes are forbidden during render')
    return next(e)
  })
  const first = await mount($, 'AbovePrompt', false, 100, 16)
  const pointer = first as unknown as { pointer: (event: { type: 'move'; x: number; y: number }) => Promise<void> }
  await pointer.pointer({ type: 'move', x: 100 - CAT_COLUMNS, y: 4 })
  forbidWrites = true
  const short = await mount($, 'AbovePrompt', false, 100, 3)
  expect(flat((await short.drawn()) as Node)).toContain('ready when you are')
  expect(boxes((await short.drawn()) as Node).some(node => node.type === 'Raster')).toBe(false)
  forbidWrites = false
  const detail = await $.command.run({ command: 'wake', args: 'detail', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } } as never)
  expect(detail.text).toContain('Mochi')
  await short.unmount()
  await first.unmount()
})

test('Raster card composition changes only its rectangle and emits legal cells for Unicode labels', () => {
  const input = { width: 40, frame: 0, hour: 12, sun: { rise: 6, set: 18 }, moonPhase: 0.3,
    season: 'summer', snowy: false, weather: null, preset: 'city', seed: 7, turns: [], live: null,
    mood: 'idle', jobs: [], agents: [], plan: null, effect: null } satisfies SceneInput
  const target = { id: 'worker', title: 'Cafe\u0301 李 😀', details: ['Line\u0000 control \u202e \ud800 \u0378', 'More details'] }
  const selected = { target, x: 39, y: 4 }
  const plain = sceneFrame(input), card = sceneFrame(input, selected)
  expect(card.hits).toEqual(plain.hits)
  expect(card.floor).toBe(plain.floor)
  const before = rasterWords(plain.cells), after = rasterWords(card.cells)
  const bounds = sceneCardBounds(40, 8, { ...selected, details: target.details })!
  for (let i = 0; i < 40 * 8; i++) {
    const x = i % 40, y = Math.floor(i / 40)
    if (x < bounds.left || x >= bounds.left + bounds.width || y < bounds.top || y >= bounds.top + bounds.height) {
      expect(Array.from(after.slice(i * 3, i * 3 + 3))).toEqual(Array.from(before.slice(i * 3, i * 3 + 3)))
    }
    const cp = after[i * 3]!
    expect(cp >= 32 && cp <= 0xffff && !(cp >= 0x7f && cp <= 0x9f)).toBe(true)
    expect(/[\p{Cc}\p{Cf}\p{Cs}\p{Cn}\p{Zl}\p{Zp}]/u.test(String.fromCharCode(cp))).toBe(false)
  }
  expect(rasterText(card.cells)).toContain('Café')
  expect(rasterText(card.cells)).toContain('/wake detail')
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
    const marks = ['Co◑', 'Co◕', 'An◉']
    const rows = marks.map(mark => lines.find(line => line.includes(mark))!)
    expect(rows.every(Boolean)).toBe(true)
    expect(rows.map((line, i) => line.indexOf(marks[i]!))).toEqual([rows[0]!.indexOf('Co◑'), rows[0]!.indexOf('Co◑'), rows[0]!.indexOf('Co◑')])
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

test('a larger crew is reachable by pages while the scene remains visible', async ($, on) => {
  engine(on)
  const jobs: WakeChip[] = Array.from({ length: 8 }, (_, i) => ({ name: `job${i}`, title: `Worker ${i}`, backend: 'codex', account: '01', model: 'sol', effort: 'high', running: true, isStale: false, since: 1, lastEventAt: 995_000 }))
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: jobs, version: 1 } }))
  const bar = await mount($, 'AbovePrompt', false, 80)
  const first = flat((await bar.drawn()) as Node)
  expect(first).toContain('<mochi>')
  await bar.press({ key: 'crew-next' })
  const second = flat((await bar.drawn()) as Node)
  await bar.press({ key: 'crew-next' })
  const third = flat((await bar.drawn()) as Node)
  for (const job of jobs) expect(first + second + third).toContain(job.title!)
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
  expect(drawn).toContain('since last activity')
  expect(drawn).toContain('from the log')
  expect(drawn).not.toContain('<mochi>')
  await bar.unmount()
})

test('turn completion does not recreate a legacy truncated call with a full source answer', async ($, on) => {
  const answer = 'I chose SQLite for the synthetic test cases because the fixtures need consistent storage behavior.'
  const legacy = { id: '12uf0k0', text: 'I chose SQLite for the synthetic test cases because the fix…', answer }
  engine(on)
  let stored = [legacy]
  let version = 1
  on('state.get', { plugin: 'wake', key: 'calls' }, () => ({ value: { value: stored, version } }))
  on('state.set', { plugin: 'wake', key: 'calls' }, (_$, e) => {
    stored = e.value as typeof stored
    return { value: { isSet: true as const, version: ++version } }
  })
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.turn.complete({ answer, durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' } as never)
  const summary = await $.command.run({ command: 'wake', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } } as never)
  expect(summary.text!.match(/◆ /g)).toHaveLength(1)
})

test('calls survive later answers and resolve individually without replacing the draft', async ($, on) => {
  engine(on)
  let draft = 'Existing draft'
  on('prompt.fill', (_$, e) => {
    draft = e.mode === 'append' ? draft + e.text : e.text
    return { isFilled: true, text: draft, cursor: draft.length } as never
  })
  for (const [turnId, answer] of [['t1', 'I chose blue instead of red.'], ['t2', 'I skipped the retry path.'], ['t3', 'I chose blue instead of red.']] as const) {
    await $.turn.start({ text: 'go', turnId })
    await $.turn.complete({ answer, durationMs: 1, isAborted: false, turnId, reason: 'answer' } as never)
  }
  const summary = await $.command.run({ command: 'wake', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } } as never)
  expect(summary.text).toContain('I chose blue instead of red.')
  expect(summary.text).toContain('I skipped the retry path.')
  const id = /◆ (\w+) I chose blue/.exec(summary.text!)![1]!
  const detail = await $.command.run({ command: 'wake', args: `call ${id}`, origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } } as never)
  expect(detail.text).toContain('Source answer:')
  expect(detail.text).toContain('I chose blue instead of red.')
  const narrow = await mount($, 'AbovePrompt', false, 32)
  const narrowLines = flat((await narrow.drawn()) as Node).split('\n')
  expect(narrowLines.some(line => line.includes('I chose blue instead of red.') && !line.includes('[push back]'))).toBe(true)
  expect(narrowLines.some(line => line.includes('[push back]') && line.includes('[inspect]') && line.includes('[fine]'))).toBe(true)
  await narrow.unmount()
  const bar = await mount($, 'AbovePrompt', false, 100)
  await bar.press({ key: `call-push-${id}` })
  expect(draft).toContain('Existing draft')
  expect(draft).toContain('Revisit your call')
  await bar.press({ key: `call-fine-${id}` })
  const after = await $.command.run({ command: 'wake', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } } as never)
  expect(after.text).not.toContain('I chose blue')
  expect(after.text).toContain('I skipped the retry path.')
  await bar.unmount()
})

test('recap refreshes on later tool results and labels its source in the command', async ($, on) => {
  const notices: string[] = []
  const clock = engine(on, message => notices.push(JSON.stringify(message)))
  await $.prompt.submit({ text: 'go' } as never)
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.call({ tool: 'Edit', file_path: '/proj/a.ts', old_string: 'a', new_string: 'b' } as never)
  await $.turn.complete({ answer: 'Done.', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' } as never)
  await clock.advance(10 * 60_000 + 1)
  await $.tool.call({ tool: 'Bash', command: 'pytest later' } as never)
  const result = await $.command.run({ command: 'wake', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } } as never)
  expect(result.text).toContain('from the log')
  expect(result.text).toContain('test runs observed: 1 passed')
  await $.prompt.submit({ text: 'I am back' } as never)
  expect(notices.some(text => text.includes('since last activity') && text.includes('from the log'))).toBe(true)
})

test('needs-only recap and row-limited renders retain a path to details', async ($, on) => {
  const clock = engine(on)
  on('state.get', { plugin: 'wake', key: 'needs' }, () => ({ value: { value: [{ id: 'n', kind: 'codex-ask', job: 'worker', text: 'Choose a path', at: 1 }], version: 1 } }))
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' } as never)
  await clock.advance(10 * 60_000 + 1)
  for (const [width, rows] of [[32, 4], [100, 16]]) {
    const bar = await mount($, 'AbovePrompt', false, width, rows)
    const text = flat((await bar.drawn()) as Node)
    expect(text).toContain('Choose a path')
    if (rows === 4) expect(text).toContain('/wake')
    else expect(text).toContain('from the log')
    await bar.unmount()
  }
})

test('a return while a recap is being assembled cannot leave a stale recap', async ($, on) => {
  const clock = engine(on)
  let release!: () => void
  let entered!: () => void
  let returning!: () => void
  const blocked = new Promise<void>(resolve => { release = resolve })
  const started = new Promise<void>(resolve => { entered = resolve })
  const returnStarted = new Promise<void>(resolve => { returning = resolve })
  let delay = false
  on('state.get', { plugin: 'wake', key: 'digest' }, async (_$, e, next) => {
    if (delay) { entered(); await blocked }
    return next(e)
  })
  on('state.get', { plugin: 'wake', key: 'recap' }, (_$, e, next) => {
    if (delay) returning()
    return next(e)
  })
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.tool.call({ tool: 'Edit', file_path: '/proj/a.ts', old_string: 'a', new_string: 'b' } as never)
  await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' } as never)
  delay = true
  const advanced = clock.advance(10 * 60_000 + 1)
  await started
  const returned = $.prompt.submit({ text: 'I am back' } as never)
  await returnStarted
  delay = false
  release()
  await returned
  await advanced
  const bar = await mount($, 'AbovePrompt')
  expect(flat((await bar.drawn()) as Node)).not.toContain('since last activity')
  await bar.unmount()
})

test('resolving a call during a later extraction does not resurrect it', async ($, on) => {
  engine(on)
  let release!: () => void
  let entered!: () => void
  const blocked = new Promise<void>(resolve => { release = resolve })
  const started = new Promise<void>(resolve => { entered = resolve })
  let delay = false
  on('state.get', { plugin: 'wake', key: 'calls' }, async (_$, e, next) => {
    if (delay) { delay = false; entered(); await blocked }
    return next(e)
  })
  const answer = 'I chose blue instead of red.'
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.turn.complete({ answer, durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' } as never)
  const summary = await $.command.run({ command: 'wake', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } } as never)
  const id = /◆ (\w+) I chose blue/.exec(summary.text!)![1]!
  const bar = await mount($, 'AbovePrompt')
  await $.turn.start({ text: 'go', turnId: 't2' })
  delay = true
  const completed = $.turn.complete({ answer, durationMs: 1, isAborted: false, turnId: 't2', reason: 'answer' } as never)
  await started
  await bar.press({ key: `call-fine-${id}` })
  release()
  await completed
  const after = await $.command.run({ command: 'wake', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } } as never)
  expect(after.text).not.toContain(answer)
  await bar.unmount()
})
