import { expect, test } from 'claude-code/testing'
import { ownedBy, ownersIn, scanCodex } from '../hooks/sources/codex'
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

test('additive fields are accepted; malformed fields and unknown versions are rejected', () => {
  const s = snapshot()
  s.jobs = [job()]
  expect(readSnapshot(JSON.stringify({ ...s, future: true }))).toBeDefined()
  expect(readSnapshot(JSON.stringify({ ...s, schema_version: 2 }))).toBeUndefined()
  expect(readSnapshot(JSON.stringify({ ...s, generated_at: '2026-10-27T00:00:00' }))).toBeUndefined()
  expect(readSnapshot(JSON.stringify({ ...s, jobs: [{ ...job(), running: 'true' }] }))).toBeUndefined()
  expect(readSnapshot(JSON.stringify({ ...s, quotas: [{ backend: 'codex', account: '01', plan: null, active: true, status: null, freshness: 'future', windows: [] }] }))).toBeUndefined()
  expect(readSnapshot('null')).toBeUndefined()
  expect(readSnapshot('{broken')).toBeUndefined()
})

test('snapshot memory, reason and peer edges reach each job', async () => {
  const s = snapshot()
  s.jobs = [job({ memory_bytes: 1024, memory_cap: '1G', state: 'blocked_on_question', reason: 'answer needed' })]
  s.peers = { nodes: ['owner/a', 'owner/b'], edges: [{ id: 'owner/a->owner/b', source: 'owner/a', target: 'owner/b', count: 3, last_at: NOW, last_kind: 'steer' }], recent_messages: [] }
  const result = await scanCodex(engine(s).$, {})
  expect(result.jobs[0]).toMatchObject({ state: 'blocked_on_question', reason: 'answer needed', memoryBytes: 1024, memoryCap: '1G', peers: [{ target: 'owner/b', count: 3, outgoing: true, lastAt: Date.parse(NOW) }] })
  expect(readSnapshot(JSON.stringify({ ...s, jobs: [{ ...s.jobs[0], memory_bytes: -1 }] }))).toBeUndefined()
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
