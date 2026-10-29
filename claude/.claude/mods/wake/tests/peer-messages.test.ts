import { expect, test } from 'claude-code/testing'
import { PeerMessageTracker } from '../hooks/peer-messages'

test('message pulse baselines are scoped to owner and job, and reset with the session scope', () => {
  const tracker = new PeerMessageTracker()
  const job = (id: string, owner: string, ...messageIds: string[]) => ({
    id, owner, peers: messageIds.map(messageId => ({ messageId })),
  })

  expect(tracker.observe('session-a:owner-a', [job('a', 'owner-a', 'old')])).toEqual(new Set())
  expect(tracker.observe('session-a:owner-a', [job('a', 'owner-a', 'old')])).toEqual(new Set())
  expect(tracker.observe('session-a:owner-a', [job('a', 'owner-a', 'old', 'new')])).toEqual(new Set([JSON.stringify(['owner-a', 'a', 'new'])]))

  // A different job has its own first-scan baseline even in the same session.
  expect(tracker.observe('session-a:owner-a', [job('a', 'owner-a', 'old', 'new'), job('a', 'owner-b', 'history')])).toEqual(new Set())
  expect(tracker.observe('session-a:owner-a', [job('a', 'owner-a', 'old', 'new', 'next'), job('a', 'owner-b', 'history')])).toEqual(new Set([JSON.stringify(['owner-a', 'a', 'next'])]))

  // Owner handoff/session change resets all historical IDs before the next scan.
  expect(tracker.observe('session-b:owner-a', [job('a', 'owner-a', 'history')])).toEqual(new Set())
  expect(tracker.observe('session-b:owner-a', [job('a', 'owner-a', 'history', 'current')])).toEqual(new Set([JSON.stringify(['owner-a', 'a', 'current'])]))

  // A job that leaves the owned snapshot and returns starts from a clean baseline.
  expect(tracker.observe('session-b:owner-a', [])).toEqual(new Set())
  expect(tracker.observe('session-b:owner-a', [job('a', 'owner-a', 'history', 'replayed')])).toEqual(new Set())

  tracker.reset()
  expect(tracker.observe('session-b:owner-a', [job('a', 'owner-a', 'history', 'after-clear')])).toEqual(new Set())
})

test('history eviction retains currently visible message IDs and each job baseline', () => {
  const tracker = new PeerMessageTracker()
  const a = { id: 'owner/a', owner: 'owner', peers: [{ messageId: 'root-to-worker' }, { messageId: 'worker-to-root' }] }
  const b = (id: string) => ({ id: 'owner/b', owner: 'owner', peers: [{ messageId: id }] })
  tracker.observe('session', [a, b('initial')])
  for (let i = 0; i < 1100; i++) {
    expect(tracker.observe('session', [a, b(String(i))])).toEqual(new Set([JSON.stringify(['owner', 'owner/b', String(i)])]))
  }
  expect(tracker.observe('session', [a, b('1099')])).toEqual(new Set())
  expect(tracker.observe('session', [{ ...a, peers: [...a.peers, { messageId: 'new' }] }, b('1099')])).toEqual(new Set([JSON.stringify(['owner', 'owner/a', 'new'])]))
})
