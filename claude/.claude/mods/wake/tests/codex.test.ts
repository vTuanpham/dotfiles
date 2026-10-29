import { expect, test } from 'claude-code/testing'
import type { EngineInterface } from 'claude-code'
import { read, update } from 'claude-code'
import { codexTick } from '../hooks/register'
import { ownedBy, ownersIn, scanCodex, withoutDetachedOwners } from '../hooks/sources/codex'
import { readSnapshot } from '../hooks/sources/bridge'
import { engine, event, job, NOW, snapshot } from './status-world'

test('Bridge state is mapped without filesystem access or reclassifying waits', async () => {
  const s = snapshot()
  s.jobs = ['waiting_for_heavy', 'paused', 'retrying', 'blocked_on_question', 'waiting_for_root'].map((state, i) =>
    job({ id: `owner/j${i}`, name: `j${i}`, state, stall: { state: 'known', reason: state },
      last_event_at: '2026-10-26T00:00:00Z' }))
  const w = engine(s)
  const result = await scanCodex(w.$, {})
  expect(result.jobs.every(j => !j.isStale)).toBe(true)
  expect(result.jobs.at(-1)?.waitingForRoot).toBe(true)
  expect(w.calls).toEqual([['agent-bridge', 'status', '--json']])
})

test('first sight is not news; later urgent and completion events are new-only', async () => {
  const s = snapshot()
  s.jobs = [job()]
  s.events = [event(10)]
  const w = engine(s)
  const first = await scanCodex(w.$, {})
  expect(first.jobs[0]).toMatchObject({ completedNow: false, urgent: [], lastMessage: 'ready' })
  s.events.push(event(20, { wakes: true, text: 'URGENT: review' }), event(30, { kind: 'turn_completed', wakes: true }))
  const next = await scanCodex(w.$, first.cursor)
  expect(next.jobs[0]).toMatchObject({ completedNow: true, urgent: [{ at: Date.parse(NOW), text: 'URGENT: review' }] })
  expect((await scanCodex(w.$, next.cursor)).jobs[0]).toMatchObject({ completedNow: false, urgent: [] })
})

test('owner scope bounds the Bridge request and leaves unowned namespaces out of the cursor', async () => {
  const s = snapshot()
  s.jobs = [job(), job({ id: 'owner/child/b', owner: 'owner/child', name: 'b' }), job({ id: 'other/a', owner: 'other' })]
  const w = engine(s)
  const scoped = await scanCodex(w.$, {}, { owners: ['owner'] })
  expect(scoped.jobs.map(one => one.id)).toEqual(['owner/a', 'owner/child/b'])
  expect(Object.keys(scoped.cursor).sort()).toEqual(['owner/a:1:2', 'owner/child/b:1:2'])
  expect(w.calls).toEqual([['agent-bridge', 'status', '--json', 'owner']])

  const empty = await scanCodex(w.$, scoped.cursor, { owners: [] })
  expect(empty).toEqual({ jobs: [], cursor: {}, detachedOwners: [] })
  expect(w.calls).toHaveLength(1)
})

test('a first scoped scan surfaces only Bridge-unacknowledged wake events', async () => {
  const s = snapshot()
  s.jobs = [job()]
  s.events = [event(10, { wakes: true, text: 'question: old but unanswered' }), event(20, { text: 'ordinary history' })]
  s.wake_events = [event(10, { wakes: true, text: 'question: old but unanswered' })]
  const result = await scanCodex(engine(s).$, {}, { owners: ['owner'] })
  expect(result.jobs[0]?.urgent).toEqual([{ at: Date.parse(NOW), text: 'question: old but unanswered' }])
})

test('retirement, pending completion, age and stall are supplied by Bridge', async () => {
  const s = snapshot()
  const old = '2026-10-20T00:00:00Z'
  s.jobs = [
    job({ name: 'retired', retired_at: old }),
    job({ name: 'done', running: false, awaiting_root: true, last_event_at: old }),
    job({ name: 'acknowledged', running: false, last_event_at: old }),
    job({ name: 'stalled', stall: { state: 'stalled', reason: 'silence' } }),
  ]
  const result = await scanCodex(engine(s).$, {})
  expect(result.jobs.map(j => j.name)).toEqual(['stalled', 'done'])
  expect(result.jobs[0]?.isStale).toBe(true)
})

test('owner handoff hides another root while preserving legacy and current bindings', async () => {
  const s = snapshot()
  s.jobs = [job()]
  s.owners = [{ id: 'owner', root_backend: 'codex', root_session_id: 'new-root' }]
  const old = await scanCodex(engine(s).$, {}, { root: { backend: 'claude', session_id: 'old-root' } })
  expect(old.jobs).toEqual([])
  expect(old.detachedOwners).toEqual(['owner'])
  expect(old.cursor['owner/a:1:2']).toBe(0)
  const current = await scanCodex(engine(s).$, {}, { root: { backend: 'codex', session_id: 'new-root' } })
  expect(current.jobs.map(one => one.id)).toEqual(['owner/a'])
  const legacy = await scanCodex(engine({ ...s, owners: undefined }).$, {}, { root: { backend: 'claude', session_id: 'old-root' } })
  expect(legacy.jobs.map(one => one.id)).toEqual(['owner/a'])
  expect(legacy.detachedOwners).toEqual([])
})

test('handoff clears tagged Wake notices without deleting untagged legacy state', () => {
  expect(withoutDetachedOwners([
    { id: 'old', owner: 'owner' }, { id: 'other', owner: 'other' }, { id: 'legacy' },
  ], ['owner'])).toEqual([{ id: 'other', owner: 'other' }, { id: 'legacy' }])
})

test('the old session clears transferred crew state and emits no new notification', async () => {
  let s = snapshot()
  s.owners = [{ id: 'owner', root_backend: 'claude', root_session_id: 'old-root' }]
  s.jobs = [job()]
  s.events = [event(10)]
  const notifications: string[] = []
  const writes: string[] = []
  const values = new Map<string, unknown>()
  const versions = new Map<string, number>()
  const reference = (value: { plugin: string; key: string }) => `${value.plugin}.${value.key}`
  const engine = {
    state: {
      get: async (ref: { plugin: string; key: string }) => ({
        value: values.get(reference(ref)), version: versions.get(reference(ref)) ?? 0,
      }),
      set: async (ref: { plugin: string; key: string }, value: unknown, options?: { ifVersion?: number }) => {
        const key = reference(ref)
        const version = versions.get(key) ?? 0
        if (options?.ifVersion !== undefined && options.ifVersion !== version) {
          return { isSet: false, version }
        }
        writes.push(ref.key)
        values.set(key, value)
        versions.set(key, version + 1)
        return { isSet: true, version: version + 1 }
      },
    },
    session: { id: async () => 'old-root', append: async () => ({ uuid: 'fixture' }) },
    clock: { now: async () => 1_000_000 },
    process: { run: async () => ({
      stdout: JSON.stringify(s), stderr: '', exitCode: 0,
      isStdoutTruncated: false, isStderrTruncated: false,
    }) },
    ui: { notify: async (text: string) => {
      notifications.push(text)
      return { isSent: false, reason: 'no-surface' }
    } },
  } as unknown as EngineInterface

  await update(engine, { plugin: 'wake', key: 'owners' }, () => ['owner'])
  await update(engine, { plugin: 'wake', key: 'lastActivity' }, () => 0)
  await update(engine, { plugin: 'wake', key: 'needs' }, () => [
    { id: 'old', kind: 'codex-done' as const, owner: 'owner', job: 'a', text: 'old', at: 1 },
    { id: 'other', kind: 'codex-done' as const, owner: 'other', job: 'a', text: 'keep', at: 1 },
    { id: 'legacy', kind: 'codex-done' as const, job: 'old-format', text: 'keep', at: 1 },
  ])
  await update(engine, { plugin: 'wake', key: 'digest' }, () => ({
    awaySince: 0, answers: [], files: [], failures: [], tests: [], agents: [],
    codex: [{ owner: 'owner', name: 'old', model: 'sol' }, { owner: 'other', name: 'keep', model: 'sol' }], needs: [],
  }))
  await codexTick(engine)
  expect((await read(engine, { plugin: 'wake', key: 'chips' }))?.map(chip => chip.id)).toEqual(['owner/a'])

  s = { ...s, owners: [{ id: 'owner', root_backend: 'codex', root_session_id: 'new-root' }] }
  s.events = [...s.events, event(20, { kind: 'question', wakes: true, text: 'answer needed' })]
  await update(engine, { plugin: 'wake', key: 'turnStartedAt' }, () => 999)
  await codexTick(engine)

  expect((await read(engine, { plugin: 'wake', key: 'chips' }))).toEqual([])
  expect((await read(engine, { plugin: 'wake', key: 'needs' }))?.map(item => item.id)).toEqual(['other', 'legacy'])
  expect((await read(engine, { plugin: 'wake', key: 'digest' }))?.codex.map(item => item.owner)).toEqual(['other'])
  expect(notifications).toEqual([])
  expect(await read(engine, { plugin: 'wake', key: 'recap' })).toBeUndefined()
  await update(engine, { plugin: 'wake', key: 'turnStartedAt' }, () => null)
  writes.length = 0
  await codexTick(engine)
  expect(writes).toEqual(['recap'])
  expect((await read(engine, { plugin: 'wake', key: 'recap' }))?.lines.length).toBeGreaterThan(0)
  writes.length = 0
  await codexTick(engine)
  expect(writes).toEqual([])
})

test('additive fields are accepted; malformed fields and unknown versions are rejected', () => {
  const s = snapshot()
  s.jobs = [job()]
  expect(readSnapshot(JSON.stringify({ ...s, future: true }))).toBeDefined()
  expect(readSnapshot(JSON.stringify({ ...s, schema_version: 2 }))).toBeUndefined()
  expect(readSnapshot(JSON.stringify({ ...s, generated_at: '2026-10-27T00:00:00' }))).toBeUndefined()
  expect(readSnapshot(JSON.stringify({ ...s, jobs: [{ ...job(), running: 'true' }] }))).toBeUndefined()
  expect(readSnapshot(JSON.stringify({ ...s, owners: [{ id: 'owner', root_backend: 5, root_session_id: 'x' }] }))).toBeUndefined()
  expect(readSnapshot(JSON.stringify({ ...s, quotas: [{ backend: 'codex', account: '01', plan: null, active: true, status: null, freshness: 'future', windows: [{ label: '5h', remaining_percent: 50, resets: null }] }] }))).toBeUndefined()
  expect(readSnapshot('null')).toBeUndefined()
  expect(readSnapshot('{broken')).toBeUndefined()
})

test('direct message fields remain optional for older snapshots and validate bounded previews', () => {
  const s = snapshot()
  s.jobs = [job()]
  const { direct_messages: _directMessages, ...legacy } = s
  expect(readSnapshot(JSON.stringify(legacy))).toBeDefined()
  const message = {
    id: 'dm-1', source: 'root/owner', target: 'owner/a', direction: 'root_to_worker',
    at: NOW, kind: 'prompt', size: 5, preview: 'hello',
  }
  expect(readSnapshot(JSON.stringify({ ...s, direct_messages: [message] }))).toBeDefined()
  expect(readSnapshot(JSON.stringify({ ...s, direct_messages: [{ ...message, recorded_at: NOW }] }))).toBeDefined()
  expect(readSnapshot(JSON.stringify({ ...s, direct_messages: [{ ...message, recorded_at: 'bad' }] }))).toBeUndefined()
  expect(readSnapshot(JSON.stringify({ ...s, direct_messages: [{ ...message, recorded_at: null }] }))).toBeDefined()
  for (const recorded_at of ['2026-02-30T00:00:00Z', '2026-02-29T00:00:00Z', '0000-01-01T00:00:00Z', '2026-10-27T24:00:00Z', '2026-10-27 00:00:00Z', '2026-10-27T00:00:00+24:00']) {
    expect(readSnapshot(JSON.stringify({ ...s, direct_messages: [{ ...message, recorded_at }] }))).toBeUndefined()
  }
  expect(readSnapshot(JSON.stringify({ ...s, direct_messages: [{ ...message, recorded_at: '2024-02-29T00:00:00Z' }] }))).toBeDefined()
  for (const changes of [
    { direction: 'unknown' }, { kind: 'turn' }, { direction: 'root_to_worker', kind: 'message' },
    { direction: 'worker_to_root', kind: 'steer' }, { size: -1 },
    { at: '2026-10-27T00:00:00' }, { preview: 'x'.repeat(161) },
  ]) {
    expect(readSnapshot(JSON.stringify({ ...s, direct_messages: [{ ...message, ...changes }] }))).toBeUndefined()
  }
  expect(readSnapshot(JSON.stringify({ ...s, direct_messages: [{ ...message, preview: '🙂'.repeat(160) }] }))).toBeDefined()
  expect(readSnapshot(JSON.stringify({ ...s, direct_messages: [{ ...message, preview: '🙂'.repeat(161) }] }))).toBeUndefined()
  const recent = { id: 'peer', source: 'owner/a', target: 'owner/b', at: NOW, kind: 'message', size: 1, preview: '🙂'.repeat(160) }
  expect(readSnapshot(JSON.stringify({ ...s, peers: { ...s.peers, recent_messages: [recent] } }))).toBeDefined()
  expect(readSnapshot(JSON.stringify({ ...s, peers: { ...s.peers, recent_messages: [{ ...recent, preview: '🙂'.repeat(161) }] } }))).toBeUndefined()
  expect(readSnapshot(JSON.stringify({ ...s, direct_messages: Array(101).fill(message) }))).toBeUndefined()
})

test('snapshot memory, reason and peer edges reach each job', async () => {
  const s = snapshot()
  s.jobs = [job({ memory_bytes: 1024, memory_cap: '1G', state: 'blocked_on_question', reason: 'answer needed', waiting: { kind: 'dependency', peer: 'owner/b', declared_at: NOW } })]
  s.peers = { nodes: ['owner/a', 'owner/b'], edges: [{ id: 'owner/a->owner/b', source: 'owner/a', target: 'owner/b', count: 3, last_at: NOW, last_kind: 'steer' }], recent_messages: [] }
  const result = await scanCodex(engine(s).$, {})
  expect(result.jobs[0]).toMatchObject({ id: 'owner/a', waitingPeer: { target: 'owner/b', declaredAt: Date.parse(NOW) }, state: 'blocked_on_question', reason: 'answer needed', memoryBytes: 1024, memoryCap: '1G', peers: [{ target: 'owner/b', count: 3, outgoing: true, lastAt: Date.parse(NOW) }] })
  s.peers.recent_messages = [{ id: 'message', source: 'owner/a', target: 'owner/b', at: NOW, kind: 'steer', size: 12, preview: 'Review tests' }]
  expect((await scanCodex(engine(s).$, {})).jobs[0]!.peers[0]!.preview).toBe('Review tests')
  s.peers.recent_messages[0]!.at = '2026-10-25T00:00:00Z'
  expect((await scanCodex(engine(s).$, {})).jobs[0]!.peers[0]!.preview).toBeNull()
  expect(readSnapshot(JSON.stringify({ ...s, jobs: [{ ...s.jobs[0], memory_bytes: -1 }] }))).toBeUndefined()
  expect(readSnapshot(JSON.stringify({ ...s, jobs: [{ ...s.jobs[0], waiting: { kind: 'peer', peer: 'owner/b', declared_at: 'bad' } }] }))).toBeUndefined()
  expect(readSnapshot(JSON.stringify({ ...s, jobs: [{ ...s.jobs[0], waiting: { kind: 'unknown', peer: 'owner/b', declared_at: NOW } }] }))).toBeUndefined()
})

test('root peers require exact owner, job and direction records from Bridge', async () => {
  const s = snapshot()
  s.jobs = [job(), job({ id: 'owner/b', name: 'b' }), job({ id: 'other/a', owner: 'other' })]
  s.direct_messages = [
    { id: 'prompt-1', source: 'root/owner', target: 'owner/a', direction: 'root_to_worker', at: NOW, kind: 'prompt', size: 5, preview: 'first' },
    { id: 'steer-2', source: 'root/owner', target: 'owner/a', direction: 'root_to_worker', at: '2026-10-27T00:01:00Z', kind: 'steer', size: 4, preview: 'latest' },
    { id: 'event:9', source: 'root/owner', target: 'owner/a', direction: 'root_to_worker', at: '2026-10-27T00:01:00Z', kind: 'steer', size: 4, preview: 'sequence nine' },
    { id: 'event:10', source: 'root/owner', target: 'owner/a', direction: 'root_to_worker', at: '2026-10-27T00:01:00Z', kind: 'steer', size: 5, preview: 'sequence ten' },
    { id: 'answer-1', source: 'owner/a', target: 'root/owner', direction: 'worker_to_root', at: NOW, kind: 'question', size: 3, preview: null },
    // These records have one correct endpoint each but do not belong to this exact root/job pair.
    { id: 'wrong-job', source: 'root/owner', target: 'owner/b', direction: 'root_to_worker', at: NOW, kind: 'prompt', size: 1, preview: 'other job' },
    { id: 'wrong-owner', source: 'root/other', target: 'owner/a', direction: 'root_to_worker', at: NOW, kind: 'prompt', size: 1, preview: 'other root' },
    { id: 'wrong-source', source: 'owner/a', target: 'root/other', direction: 'worker_to_root', at: NOW, kind: 'message', size: 1, preview: 'other root' },
    { id: 'missing-job', source: 'root/owner', target: 'owner/missing', direction: 'root_to_worker', at: NOW, kind: 'prompt', size: 1, preview: 'no job' },
  ]
  const result = await scanCodex(engine(s).$, {})
  expect(result.jobs.find(one => one.id === 'owner/a')?.peers).toEqual([
    { target: 'root', count: 4, lastAt: Date.parse('2026-10-27T00:01:00Z'), outgoing: false, preview: 'sequence ten', kind: 'steer', messageId: 'event:10', messageState: 'sent' },
    { target: 'root', count: 1, lastAt: Date.parse(NOW), outgoing: true, preview: null, kind: 'question', messageId: 'answer-1', messageState: 'observed' },
  ])
  expect(result.jobs.find(one => one.id === 'owner/b')?.peers).toEqual([
    { target: 'root', count: 1, lastAt: Date.parse(NOW), outgoing: false, preview: 'other job', kind: 'prompt', messageId: 'wrong-job', messageState: 'sent' },
  ])
  expect(result.jobs.find(one => one.id === 'other/a')?.peers).toEqual([])
  s.direct_messages.push({
    id: 'late-confirmation', source: 'root/owner', target: 'owner/a', direction: 'root_to_worker',
    at: '2026-10-25T00:00:00Z', recorded_at: '2026-10-27T00:01:30Z', kind: 'prompt', size: 1, preview: 'confirmed later',
  })
  const delayed = await scanCodex(engine(s).$, {})
  expect(delayed.jobs.find(one => one.id === 'owner/a')?.peers[0]).toMatchObject({
    count: 5, lastAt: Date.parse('2026-10-27T00:01:30Z'), messageId: 'late-confirmation', preview: 'confirmed later',
  })
})

test('ownersIn reads only the job owners a command names', () => {
  expect(ownersIn('agent-bridge watch pb --until-event --timeout 1800')).toEqual(['pb'])
  expect(ownersIn('agent-bridge result pb/job; agent-bridge ack pb other')).toEqual(['pb', 'other'])
  expect(ownersIn('agent-bridge start pb-brain/luna-a --backend codex --cwd /r --detach')).toEqual(['pb-brain'])
  expect(ownersIn('mkdir -p ~/.local/state/agent-bridge/jobs/pb/a && agent-bridge steer pb/a "hi"')).toEqual(['pb'])
  expect(ownersIn('timeout 1500 agent-bridge watch poly-audit pb --until-event')).toEqual(['poly-audit', 'pb'])
  expect(ownersIn('rm -rf ~/.local/state/agent-bridge/jobs/.trash/x; tail ~/.local/state/agent-bridge/archive.jsonl')).toEqual([])
  expect(ownersIn('agent-bridge start <owner>/<name> --model x; agent-bridge start ~/abs/job; ls /tmp')).toEqual([])
  expect(ownersIn('agent-bridge start --backend codex --cwd /r pb/worker')).toEqual(['pb'])
  expect(ownersIn('agent-bridge watch --until-event --stall-min 15 pb poly')).toEqual(['pb', 'poly'])
  expect(ownedBy({ owner: 'pb/brain' }, ['pb'])).toBe(true)
  expect(ownedBy({ owner: 'pbx' }, ['pb'])).toBe(false)
})
