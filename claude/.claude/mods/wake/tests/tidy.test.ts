import { expect, test } from 'claude-code/testing'
import { scanTidy, tidyRequest, type TidyItem, type TidyScan } from '../hooks/sources/tidy'
import { engine, NOW as AT, snapshot } from './status-world'

const HOME = '/state'
const ROOT = '/state/bridge/jobs'
const NOW = Date.parse(AT)
function world() {
  const s = snapshot()
  s.retention.items = [
    { kind: 'job', owner: 'pb', name: 'old1', path: `${ROOT}/pb/old1`, bytes: 1000, age_days: 5, is_dirty: null },
    { kind: 'job', owner: 'pb', name: 'old2', path: `${ROOT}/pb/old2`, bytes: 2000, age_days: 10, is_dirty: null },
    { kind: 'job', owner: 'pb', name: 'notgit', path: `${ROOT}/pb/notgit`, bytes: 30, age_days: 9, is_dirty: null },
    { kind: 'worktree', owner: 'pb', name: 'old1', path: `${ROOT}/pb/old1/out/wt`, bytes: 900, age_days: 5, is_dirty: false },
    { kind: 'worktree', owner: 'pb', name: 'dirty1', path: `${ROOT}/pb/dirty1/out/wt`, bytes: 777, age_days: 6, is_dirty: true },
  ]
  return engine(s)
}

test('tidy consumes Bridge eligibility, dirty exclusions and sizes through one command', async () => {
  const w = world()
  const scan = await scanTidy(w.$)
  expect(w.calls).toEqual([['agent-bridge', 'status', '--json', '--storage']])
  expect(scan.jobs.map(j => j.name)).toEqual(['old2', 'old1', 'notgit'])
  expect(scan.reclaimBytes).toBe(3030)
  expect(scan.worktrees[0]?.bytes).toBe(900)
  expect(scan.dirty[0]?.name).toBe('dirty1')
  expect((await scanTidy(w.$, { olderThanDays: 8 })).jobs.map(j => j.name)).toEqual(['old2', 'notgit'])
})

const item = (i: number, kind: TidyItem['kind'] = 'job'): TidyItem => ({
  kind,
  path: `${ROOT}/pb/job-${i}`,
  owner: 'pb',
  name: `job-${i}`,
  bytes: 1e9,
  ageDays: 5,
})

test('tidyRequest names the plan, sizes, jobs and the dirty ones left for approval', async () => {
  const scan = await scanTidy(world().$)
  const text = tidyRequest(scan)

  expect(text).toContain('`agent-bridge purge <owner>/<name>`')
  expect(text).toContain(`${HOME}/bridge/archive.jsonl`)
  expect(text).toContain('Tidy bridge jobs:')
  expect(text).toContain('these 3 retired jobs past their purge date')
  expect(text).toContain('pb/old1')
  expect(text).not.toContain('pb/retained')
  expect(text).toContain('Leave the 1 dirty worktrees for my OK: pb/dirty1')
  expect(text).toMatch(/\(≈\d+ MB\)/)
})

test('tidyRequest caps the list at 40 and stays under 2,500 characters', () => {
  const jobs = Array.from({ length: 300 }, (_, i) => item(i))
  const dirty = Array.from({ length: 30 }, (_, i) => ({ ...item(i, 'worktree'), isDirty: true }))
  const scan: TidyScan = { jobs, worktrees: [], dirty, reclaimBytes: 41.8e9, scannedAt: NOW, archivePath: `${HOME}/.local/state/agent-bridge/archive.jsonl` }
  const text = tidyRequest(scan)

  expect(text.length).toBeLessThanOrEqual(2_500)
  expect(text).toContain('≈41.8 GB')
  expect(text).toContain('+260 more')
  expect(text).toContain('+15 more')
  expect(text).not.toContain('job-40,')
})

test('tidyRequest has nothing to say when nothing qualifies', () => {
  const empty: TidyScan = { jobs: [], worktrees: [], dirty: [], reclaimBytes: 0, scannedAt: NOW, archivePath: `${HOME}/.local/state/agent-bridge/archive.jsonl` }

  expect(tidyRequest(empty)).toContain('no retired jobs past their purge date')
})
