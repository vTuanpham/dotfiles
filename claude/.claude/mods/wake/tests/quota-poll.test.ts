import { expect, mock, test } from 'claude-code/testing'
import type { EngineInterface } from 'claude-code'
import { quotaTick } from '../hooks/register'
import type { WakeChip, WakeQuota } from '../types'
import { job, snapshot } from './status-world'

const chip = (owner?: string, running = true): WakeChip => ({
  owner, name: 'worker', backend: 'codex', account: '01', model: 'gpt-6-sol', effort: 'high',
  running, isStale: false, since: 1,
})

function quotaEngine() {
  const calls: string[][] = []
  const writes: string[] = []
  const values = new Map<string, unknown>([['owners', ['owner']], ['chips', []], ['quotas', []]])
  const s = snapshot()
  s.jobs = [job()]
  s.quotas = ['01', '02'].map(account => ({ backend: 'codex', account, plan: null, active: false,
    status: null, freshness: 'stale', windows: [{ label: 'w', remaining_percent: 42, resets: null }] }))
  let version = 1
  const $ = {
    state: {
      get: async (ref: { key: string }) => ({ value: values.get(ref.key), version }),
      set: async (ref: { key: string }, value: unknown) => {
        writes.push(ref.key)
        values.set(ref.key, value)
        return { isSet: true, version: ++version }
      },
    },
    process: { run: async (args: readonly string[]) => {
      calls.push([...args])
      const value = { ...s, jobs: [{}], peers: null, errors: [] }
      return { stdout: JSON.stringify(value), exitCode: 0, isStdoutTruncated: false }
    } },
  } as unknown as EngineInterface
  return { $, calls, values, s, writes }
}

test('periodic quotas skip empty, finished, foreign and unattributed crew', async () => {
  const w = quotaEngine()
  for (const [owners, chips] of [
    [[], [chip('owner')]],
    [['owner'], []],
    [['owner'], [{ ...chip('owner', false), awaitingRoot: true }, chip('other'), chip()]],
  ]) {
    w.values.set('owners', owners)
    w.values.set('chips', chips)
    await quotaTick(w.$)
  }
  expect(w.calls).toEqual([])
})

test('periodic quotas use account observations only while this session owns active work', async () => {
  const w = quotaEngine()
  w.values.set('chips', [chip('owner'), chip('owner'), chip('other'), chip('owner', false)])
  await quotaTick(w.$)
  expect(w.calls.filter(args => args[1] === 'snapshot')).toEqual([['agent-accounts', 'snapshot']])
  expect((w.values.get('quotas') as WakeQuota[]).map(quota => [quota.account, quota.freshness])).toEqual([
    ['01', 'stale'], ['02', 'stale'],
  ])
})

test('periodic quota refresh preserves previous numbers when an account returns no reading', async () => {
  const w = quotaEngine()
  const previous: WakeQuota = { cli: 'codex', account: '01', plan: '', active: false,
    freshness: 'stale', parts: [{ label: 'w', pct: 17, resets: null }] }
  w.values.set('chips', [chip('owner')])
  w.values.set('quotas', [previous])
  w.s.quotas[0]!.windows = []
  await quotaTick(w.$)
  expect((w.values.get('quotas') as WakeQuota[])[0]).toMatchObject(previous)
})

test('unchanged quotas avoid writes while a changed freshness reading still publishes', async () => {
  const w = quotaEngine()
  w.values.set('chips', [chip('owner')])
  await quotaTick(w.$)
  expect(w.writes).toEqual(['quotas'])
  w.writes.length = 0
  await quotaTick(w.$)
  expect(w.writes).toEqual([])
  w.s.quotas[0]!.freshness = 'unknown'
  await quotaTick(w.$)
  expect(w.writes).toEqual(['quotas'])
})

test('an empty quota reading retains numbers while adopting current account and freshness metadata', async () => {
  const w = quotaEngine()
  const previous: WakeQuota = { cli: 'codex', account: '01', plan: 'old', active: false,
    freshness: 'fresh', parts: [{ label: 'w', pct: 17, resets: null }] }
  w.values.set('chips', [chip('owner')])
  w.values.set('quotas', [previous])
  Object.assign(w.s.quotas[0]!, { windows: [], freshness: 'unknown', active: true, plan: 'current' })
  await quotaTick(w.$)
  expect(w.writes).toEqual(['quotas'])
  expect((w.values.get('quotas') as WakeQuota[])[0]).toMatchObject({
    ...previous, freshness: 'unknown', active: true, plan: 'current',
  })
  w.writes.length = 0
  await quotaTick(w.$)
  expect(w.writes).toEqual([])
})

test('quota rows follow active work while finished crew and cached summary remain available', async ($, on) => {
  mock.clock(on, { now: 1_000_000 })
  mock.env(on, { HOME: '/home/u' })
  on('http.fetch', () => ({ deny: 'offline test' }))
  on('session.cwd', () => ({ value: '/repo' }))
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['engine'] }) as never)
  let active = true
  on('state.get', { plugin: 'wake', key: 'chips' }, () => ({ value: { value: [
    { ...chip('owner', active), title: 'Quota crew', awaitingRoot: !active },
  ], version: 1 } }))
  on('state.get', { plugin: 'wake', key: 'quotas' }, () => ({ value: { value: [
    { cli: 'codex', account: '99', plan: '', active: false, freshness: 'fresh', parts: [{ label: 'w', pct: 17, resets: null }] },
  ], version: 1 } }))
  type Node = string | { children?: Node[] }
  const text = (node: Node): string => typeof node === 'string' ? node : (node.children ?? []).map(text).join('')
  for (const running of [true, false]) {
    active = running
    const bar = await $.ui.mount({ plugin: 'wake', surface: 'terminal', component: 'AbovePrompt',
      props: { hasSurvey: false, isWorking: false, maxRows: 16, bodyColumns: 100, scroll: { offset: 0, bodyRows: 16 } },
    } as never)
    const rendered = text((await bar.drawn()) as Node)
    expect(rendered).toContain('Quota crew')
    expect(rendered.includes('w17%')).toBe(running)
    await bar.unmount()
  }
  const summary = await $.command.run({ command: 'wake', args: '', origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 100 } } as never)
  expect(summary.text).toContain('w17%')
})
