import { expect, test } from 'claude-code/testing'
import type { EngineInterface } from 'claude-code'

import { scanTidy, tidyRequest, type TidyItem, type TidyScan } from '../hooks/sources/tidy'

const HOME = '/home/u'
const ROOT = `${HOME}/.local/state/agent-bridge/jobs`
const DAY = 86_400_000
const NOW = 100 * DAY

// job dir (relative to the root) -> age in days of its newest file, and whether it has an out/wt
const JOBS: Record<string, { age: number; wt?: 'clean' | 'dirty' | 'plain' }> = {
  'pb/old1': { age: 5, wt: 'clean' },
  'pb/old2': { age: 10 },
  'pb/dirty1': { age: 6, wt: 'dirty' },
  'pb/fresh': { age: 1 },
  'pb/running': { age: 8 },
  'pb/agyrun': { age: 7 },
  leg: { age: 4 },
  'pb/notgit': { age: 9, wt: 'plain' },
}
const DU: Record<string, number> = {
  [`${ROOT}/pb/old1/out/wt`]: 900,
  [`${ROOT}/pb/dirty1/out/wt`]: 777,
  [`${ROOT}/pb/old1`]: 100,
  [`${ROOT}/pb/old2`]: 2_000,
  [`${ROOT}/leg`]: 50,
  [`${ROOT}/pb/notgit`]: 30,
}

/**
 * The test engine's `$` has no env, clock or process nouns, so the module gets a stand-in with the calls it
 * makes, answering as the host's find, procfs, git script and du would.
 */
function world(opts: { bridgeHome?: string; wrongCmdline?: boolean } = {}) {
  const calls: string[][] = []
  const $ = {
    env: { get: async (key: string) => key === 'AGENT_BRIDGE_HOME' ? opts.bridgeHome : HOME },
    clock: { now: async () => NOW },
    process: {
      run: async (argv: readonly string[]) => {
        calls.push([...argv])
        const out = (stdout: string, exitCode = 0) => ({ exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false })
        switch (argv[0]) {
          case 'find':
            const root = opts.bridgeHome ? `${opts.bridgeHome}/jobs` : ROOT
            return out(
              Object.entries(JOBS)
                .flatMap(([dir, j]) => {
                  const t = ((NOW - j.age * DAY) / 1000).toFixed(3)
                  return [
                    `f ${t} ${root}/${dir}/state.json\n`,
                    ...(j.wt ? [`d ${t} ${root}/${dir}/out/wt\n`] : []),
                  ]
                })
                .join('') + `f ${(NOW / 1000).toFixed(3)} ${root}/pb/old2/out/state.json\n`, // deeper marker: not a job
            )
          case 'sh':
            return out(
              argv
                .slice(4)
                .flatMap(w => (w.includes('/notgit/') ? [] : [`${w.includes('/dirty1/') ? 'dirty' : 'clean'} ${w}\n`]))
                .join(''),
            )
          default: // du
            return out(argv.slice(2).map(p => `${DU[p] ?? 1}\t${p}\n`).join(''))
        }
      },
    },
    fs: {
      read: async (path: string) => {
        if (path.startsWith('/proc/')) return opts.wrongCmdline ? 'other-process' : 'agent-bridge run'
        const root = opts.bridgeHome ? `${opts.bridgeHome}/jobs` : ROOT
        const dir = path.slice(root.length + 1, -'/state.json'.length)
        const pid = dir === 'pb/running' ? 123 : dir === 'pb/agyrun' ? 125 : undefined
        return JSON.stringify({ runnerPid: pid })
      },
    },
  } as unknown as EngineInterface
  return { $, calls }
}

test('running, too-new and non-job dirs are excluded; dirty is reported apart and not counted', async () => {
  const { $, calls } = world()
  const scan = await scanTidy($)

  expect(scan.jobs.map(j => j.name).sort()).toEqual(['leg', 'notgit', 'old1', 'old2'])
  expect(scan.worktrees.map(w => w.name)).toEqual(['old1'])
  expect(scan.dirty).toEqual([
    { kind: 'worktree', path: `${ROOT}/pb/dirty1/out/wt`, owner: 'pb', name: 'dirty1', bytes: 777, ageDays: 6, isDirty: true },
  ])
  expect(scan.jobs.find(j => j.name === 'dirty1')).toBeUndefined()
  expect(scan.jobs.find(j => j.name === 'leg')).toMatchObject({ owner: '', path: `${ROOT}/leg`, ageDays: 4 })
  expect(scan.scannedAt).toBe(NOW)
  expect(calls.map(c => c[0])).toEqual(['find', 'sh', 'du']) // one listing call, whatever the job count
})

test('du output is parsed: a job counts its worktree once; reclaim excludes dirty', async () => {
  const scan = await scanTidy(world().$)

  const old1 = scan.jobs.find(j => j.name === 'old1')!
  expect(old1.bytes).toBe(1_000)
  expect(scan.worktrees[0]!.bytes).toBe(900)
  expect(scan.reclaimBytes).toBe(1_000 + 2_000 + 50 + 30)
  expect(scan.jobs[0]!.name).toBe('old2') // biggest first
})

test('worktrees are listed before jobs in du, and nothing running or new is sized', async () => {
  const { $, calls } = world()
  await scanTidy($)
  const du = calls.find(c => c[0] === 'du')!.slice(2)

  expect(du.indexOf(`${ROOT}/pb/old1/out/wt`)).toBeLessThan(du.indexOf(`${ROOT}/pb/old1`))
  expect(du.some(p => p.includes('/running') || p.includes('/fresh'))).toBe(false)
})

test('olderThanDays narrows the scan', async () => {
  const scan = await scanTidy(world().$, { olderThanDays: 8 })

  expect(scan.jobs.map(j => j.name).sort()).toEqual(['notgit', 'old2'])
  expect(scan.olderThanDays).toBe(8)
})

test('AGENT_BRIDGE_HOME selects the job root and archive path', async () => {
  const root = '/state/bridge'
  const { $, calls } = world({ bridgeHome: root })
  const scan = await scanTidy($)
  expect(calls[0]![1]).toBe(`${root}/jobs`)
  expect(scan.archivePath).toBe(`${root}/archive.jsonl`)
})

test('runner pid is live only when its proc cmdline contains agent-bridge', async () => {
  const live = await scanTidy(world().$)
  const other = await scanTidy(world({ wrongCmdline: true }).$)
  expect(live.jobs.some(job => job.name === 'running' || job.name === 'agyrun')).toBe(false)
  expect(other.jobs.some(job => job.name === 'running' || job.name === 'agyrun')).toBe(true)
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

  expect(text).toContain('remove 1 clean worktrees with `git worktree remove` (no --force)')
  expect(text).toContain(`${HOME}/.local/state/agent-bridge/archive.jsonl`)
  expect(text).toContain('Tidy bridge jobs:')
  expect(text).toContain('delete these 4 finished job dirs older than 3 days')
  expect(text).toContain('pb/old1')
  expect(text).toContain('leg')
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

  expect(tidyRequest(empty)).toContain('nothing')
})
