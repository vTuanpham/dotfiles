import { expect, mock, test } from 'claude-code/testing'
import type { EngineInterface } from 'claude-code'
import { codexTick } from '../hooks/register'
import { job, NOW, snapshot } from './status-world'

test('unchanged idle crew polling performs no state writes or process calls', async () => {
  const writes: string[] = [], calls: string[] = []
  const $ = {
    state: {
      get: async () => ({ value: undefined, version: 0 }),
      set: async (ref: { key: string }) => { writes.push(ref.key); return { isSet: true, version: 1 } },
    },
    session: { id: async () => 'idle-root' },
    clock: { now: async () => 0 },
    process: { run: async () => { calls.push('status'); throw new Error('unexpected idle process') } },
  } as unknown as EngineInterface
  await codexTick($)
  await codexTick($)
  expect(writes).toEqual([])
  expect(calls).toEqual([])
})

test('unchanged owned crew is quiet while a new observed message still updates the projection', async () => {
  const s = snapshot()
  s.jobs = [job()]
  const values = new Map<string, unknown>([['owners', ['owner']], ['lastActivity', Date.parse(NOW)]])
  const writes: string[] = []
  let version = 1
  let now = Date.parse(NOW)
  const $ = {
    state: {
      get: async (ref: { key: string }) => ({ value: values.get(ref.key), version }),
      set: async (ref: { key: string }, value: unknown) => {
        writes.push(ref.key)
        values.set(ref.key, value)
        return { isSet: true, version: ++version }
      },
    },
    session: { id: async () => 'root' },
    clock: { now: async () => now },
    process: { run: async () => ({ stdout: JSON.stringify(s), exitCode: 0, isStdoutTruncated: false }) },
  } as unknown as EngineInterface
  await codexTick($)
  expect(writes.filter(key => key !== 'tick')).toEqual(['chips'])
  writes.length = 0
  await codexTick($)
  expect(writes).toEqual([])
  now += 15_000
  s.direct_messages = [{ id: 'new', source: 'root/owner', target: 'owner/a', direction: 'root_to_worker',
    at: NOW, kind: 'steer', size: 4, preview: 'work' }]
  await codexTick($)
  expect(writes.filter(key => key !== 'tick')).toEqual(['chips'])
  expect((values.get('chips') as { peers: { observedAt: number }[] }[])[0]?.peers[0]?.observedAt).toBe(now)
})

test('re-reading the same cached surroundings avoids a redundant projection write', async ($, on) => {
  mock.clock(on, { now: 1_000_000 })
  on('classic.SessionStart', () => ({}))
  on('http.fetch', () => ({ deny: 'offline test' }))
  const stored: Record<string, unknown> = {
    place: { key: 'fixture', name: 'Fixture', country: '', lat: 0, lon: 0, source: 'named' },
    pins: { fixture: 'city' },
    weather: { fixture: { fetchedAt: 1_000_000, utcOffsetSeconds: 0, temp: 20, code: 0, cloud: 0,
      precipitation: 0, snowfall: 0, wind: 0, sunrise: 6, sunset: 18, isDay: true, hours: [] } },
  }
  on('store.get', (_$, e) => ({ value: stored[e.key] }))
  const writes: string[] = []
  on('state.set', { plugin: 'wake', key: 'surroundings' }, (_$, e, next) => { writes.push(e.key); return next(e) })
  await $.classic.SessionStart({ source: 'resume' })
  expect(writes).toEqual(['surroundings'])
  writes.length = 0
  await $.classic.SessionStart({ source: 'resume' })
  expect(writes).toEqual([])
})

test('elapsed labels advance once per coarse bucket without rewriting crew metadata', async () => {
  let now = Date.parse('2026-10-28T12:00:00Z')
  const values = new Map<string, unknown>([['owners', []], ['lastActivity', now], ['tally', { turns: 1 }]])
  const writes: string[] = []
  const $ = {
    state: {
      get: async (ref: { key: string }) => ({ value: values.get(ref.key), version: 1 }),
      set: async (ref: { key: string }, value: unknown) => {
        writes.push(ref.key)
        values.set(ref.key, value)
        return { isSet: true, version: 2 }
      },
    },
    session: { id: async () => 'clock-root' },
    clock: { now: async () => now },
    process: { run: async () => { throw new Error('unowned clock must not query Bridge') } },
  } as unknown as EngineInterface
  await codexTick($)
  expect(writes).toEqual(['tick'])
  writes.length = 0
  await codexTick($)
  expect(writes).toEqual([])
  now += 15_000
  await codexTick($)
  expect(writes).toEqual(['tick'])

  values.set('tally', { turns: 0 })
  for (const [key, value] of [
    ['subagents', [{ id: 'native-worker' }]],
    ['recap', { lines: [{ mark: 'done', text: 'Done' }], awaySince: now, source: 'digest' }],
  ] as const) {
    writes.length = 0
    now += 15_000
    values.set(key, value)
    await codexTick($)
    expect(writes).toEqual(['tick'])
    values.delete(key)
  }
  writes.length = 0
  now += 15_000
  await codexTick($)
  expect(writes).toEqual([])
})

test('the coarse clock does not add redraws while the turn animation is running', async ($, on) => {
  const clock = mock.clock(on, { now: 1_000_000 })
  on('turn.start', (_$, e) => ({ turnId: e.turnId }))
  on('http.fetch', () => ({ deny: 'offline test' }))
  on('session.cwd', () => ({ value: '/repo' }))
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['engine'] }) as never)
  const writes: string[] = []
  on('state.set', { plugin: 'wake', key: 'tick' }, (_$, e, next) => { writes.push(e.key); return next(e) })
  await $.turn.start({ text: 'work', turnId: 't1' })
  expect(writes).toEqual([])
  const bar = await $.ui.mount({ plugin: 'wake', surface: 'terminal', component: 'AbovePrompt',
    props: { hasSurvey: false, isWorking: true, maxRows: 4, bodyColumns: 40, scroll: { offset: 0, bodyRows: 4 } },
  } as never)
  await bar.drawn()
  await clock.advance(15_200)
  expect(writes.length).toBe(38)
  await bar.unmount()
})
