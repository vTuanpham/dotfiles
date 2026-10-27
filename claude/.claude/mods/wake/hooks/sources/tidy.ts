import type { EngineInterface } from 'claude-code'
import { bridgeSnapshot } from './bridge'

// Scan-only view of retired bridge jobs past their purge date. Nothing here edits data.

export type TidyItem = {
  kind: 'job' | 'worktree'
  path: string
  owner: string
  name: string
  bytes: number
  ageDays: number
  isDirty?: boolean
}

export type TidyScan = {
  jobs: TidyItem[] // expired retirement, no dirty worktree: eligible for agent-bridge purge
  worktrees: TidyItem[] // clean git worktrees inside those jobs (out/wt)
  dirty: TidyItem[] // dirty worktrees: reported, never counted
  reclaimBytes: number // sum of `jobs` (a job's size includes its worktree)
  scannedAt: number
  olderThanDays?: number
  archivePath: string
}

const LIST_CAP = 40
const REQUEST_CAP = 2_500

export async function scanTidy($: EngineInterface, opts: { olderThanDays?: number } = {}): Promise<TidyScan> {
  const snapshot = await bridgeSnapshot($, true)
  if (!snapshot) throw new Error('Bridge status unavailable; tidy eligibility is unknown')
  const retention = snapshot.retention
  if (!retention.scanned) throw new Error('Bridge did not scan storage')
  const items = retention.items.filter(i => i.age_days >= (opts.olderThanDays ?? 0)).map(i => ({
    kind: i.kind as 'job' | 'worktree', path: i.path, owner: i.owner, name: i.name,
    bytes: i.bytes, ageDays: i.age_days, isDirty: i.is_dirty ?? undefined,
  })).sort((a, b) => b.bytes - a.bytes)
  const jobs = items.filter(i => i.kind === 'job')
  return {
    jobs, worktrees: items.filter(i => i.kind === 'worktree' && !i.isDirty),
    dirty: items.filter(i => i.isDirty), reclaimBytes: jobs.reduce((sum, i) => sum + i.bytes, 0),
    scannedAt: Date.parse(snapshot.generated_at), olderThanDays: opts.olderThanDays ?? 0,
    archivePath: retention.archive_path,
  }
}

function size(bytes: number): string {
  const gb = bytes / 1e9
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${Math.max(1, Math.round(bytes / 1e6))} MB`
}

function names(items: TidyItem[], cap: number): string {
  const label = (i: TidyItem) => (i.owner ? `${i.owner}/${i.name}` : i.name)
  const shown = items.slice(0, cap).map(label).join(', ')
  return items.length > cap ? `${shown}, +${items.length - cap} more` : shown
}

export function tidyRequest(scan: TidyScan): string {
  if (scan.jobs.length === 0 && scan.dirty.length === 0) return 'Tidy bridge jobs: no retired jobs past their purge date.'
  const dirty = scan.dirty.length > 0 ? ` Leave the ${scan.dirty.length} dirty worktrees for my OK: ${names(scan.dirty, 15)}.` : ''
  const head =
    `Tidy bridge jobs: run \`agent-bridge purge <owner>/<name>\` for these ${scan.jobs.length} retired jobs ` +
    `past their purge date (≈${size(scan.reclaimBytes)}); archived reports remain in ${scan.archivePath}: `
  // The job list takes whatever the fixed text leaves of the cap.
  const room = REQUEST_CAP - head.length - dirty.length - 1
  let list = names(scan.jobs, LIST_CAP)
  for (let cap = LIST_CAP; list.length > room && cap > 1; cap--) list = names(scan.jobs, cap - 1)
  return `${head}${list}.${dirty}`.slice(0, REQUEST_CAP)
}
