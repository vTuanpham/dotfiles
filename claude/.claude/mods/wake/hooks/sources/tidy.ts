import type { EngineInterface } from 'claude-code'
import { bridgePaths, bridgeRunnerAlive } from './bridge'

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

const DAY_MS = 86_400_000
const LIST_CAP = 40
const REQUEST_CAP = 2_500

type Dir = { newest: number; hasState: boolean; wt?: string }

const EMPTY = (now: number, days: number, archivePath = '~/.local/state/agent-bridge/archive.jsonl'): TidyScan => ({ jobs: [], worktrees: [], dirty: [], reclaimBytes: 0, scannedAt: now, olderThanDays: days, archivePath })

// Prints "clean <wt>" or "dirty <wt>" per path that is a git worktree; a failing `git status` counts as dirty.
const GIT_SCRIPT =
  'for w; do git -C "$w" rev-parse --git-common-dir >/dev/null 2>&1 || continue; ' +
  's=$(git -C "$w" status --porcelain 2>&1) || { echo "dirty $w"; continue; }; ' +
  'if [ -n "$s" ]; then echo "dirty $w"; else echo "clean $w"; fi; done'

function ident(root: string, dir: string): { owner: string; name: string } {
  const parts = dir.slice(root.length + 1).split('/')
  return { owner: parts.slice(0, -1).join('/'), name: parts.at(-1) ?? '' }
}

export async function scanTidy($: EngineInterface, opts: { olderThanDays?: number } = {}): Promise<TidyScan> {
  const days = opts.olderThanDays ?? 0
  const paths = await bridgePaths($)
  const now = await $.clock.now()
  if (!paths) return EMPTY(now, days)
  const { jobs: root, archive: archivePath } = paths

  // One find: every job's marker files (for its newest mtime) and its out/wt.
  const found = await $.process
    .run([
      'find', root, '-maxdepth', '4',
      '(', '-name', 'state.json', '-o', '-name', 'live.jsonl', '-o', '-name', 'runner.log',
      '-o', '(', '-type', 'd', '-name', 'wt', '-path', '*/out/wt', ')', ')',
      '-printf', '%y %T@ %p\\n',
    ])
    .catch(() => undefined)
  if (!found) return EMPTY(now, days, archivePath)

  const dirs = new Map<string, Dir>()
  const get = (d: string) => dirs.get(d) ?? dirs.set(d, { newest: 0, hasState: false }).get(d)!
  for (const line of found.stdout.split('\n')) {
    const m = /^(\w) (\d+)(?:\.\d+)? (.+)$/.exec(line)
    if (!m) continue
    const [, type, sec, path = ''] = m
    const depth = path.slice(root.length + 1).split('/').length
    if (type === 'd') {
      if (depth >= 3 && depth <= 4) get(path.slice(0, -'/out/wt'.length)).wt = path
      continue
    }
    if (depth < 2 || depth > 3) continue // a marker deeper than owner/job belongs to something else
    const dir = path.slice(0, path.lastIndexOf('/'))
    const d = get(dir)
    d.newest = Math.max(d.newest, Number(sec) * 1000)
    if (path.endsWith('/state.json')) d.hasState = true
  }

  const candidates = [...dirs].filter(([dir, d]) => d.hasState && !dir.endsWith('/out') && now - d.newest > days * DAY_MS)
  const old = [] as typeof candidates
  for (const item of candidates) {
    try {
      const state = JSON.parse(await $.fs.read(`${item[0]}/state.json`)) as Record<string, unknown>
      const retired = typeof state.retiredAt === 'string' ? Date.parse(state.retiredAt) : NaN
      const after = typeof state.purgeAfter === 'string' ? Date.parse(state.purgeAfter) : NaN
      // Bridge writes UTC timestamps; reject missing, local or normalized malformed dates.
      const valid = (value: unknown, parsed: number) => typeof value === 'string' && Number.isFinite(parsed)
        && new Date(parsed).toISOString().replace('.000Z', 'Z') === value.replace('+00:00', 'Z').replace('.000Z', 'Z')
      if (valid(state.retiredAt, retired) && valid(state.purgeAfter, after) && after >= retired && after <= now
        && !(await bridgeRunnerAlive($, state.runnerPid))) old.push(item)
    } catch { /* missing or malformed state: never claim its data is reclaimable */ }
  }
  if (old.length === 0) return EMPTY(now, days, archivePath)

  const wts = old.flatMap(([, d]) => (d.wt ? [d.wt] : []))
  const gitState = new Map<string, boolean>() // worktree path -> isDirty (absent: not a git worktree)
  if (wts.length > 0) {
    const g = await $.process.run(['sh', '-c', GIT_SCRIPT, 'sh', ...wts], { timeoutMs: 120_000 }).catch(() => undefined)
    for (const line of g?.stdout.split('\n') ?? []) {
      const m = /^(clean|dirty) (.+)$/.exec(line)
      if (m) gitState.set(m[2] ?? '', m[1] === 'dirty')
    }
  }

  // Worktrees first: du counts a file once, so a job's own size then excludes its worktree.
  const jobPaths = old.filter(([, d]) => !(d.wt && gitState.get(d.wt))).map(([dir]) => dir)
  const sized = [...gitState.keys(), ...jobPaths]
  const bytesOf = new Map<string, number>()
  const du = await $.process.run(['du', '-sb', ...sized], { timeoutMs: 120_000 }).catch(() => undefined)
  for (const line of du?.stdout.split('\n') ?? []) {
    const m = /^(\d+)\s+(.+)$/.exec(line)
    if (m) bytesOf.set(m[2] ?? '', Number(m[1]))
  }

  const age = (d: Dir) => Math.floor((now - d.newest) / DAY_MS)
  const scan = EMPTY(now, days, archivePath)
  for (const [dir, d] of old) {
    const id = ident(root, dir)
    const wtBytes = d.wt ? (bytesOf.get(d.wt) ?? 0) : 0
    const isDirty = d.wt ? gitState.get(d.wt) : undefined
    if (d.wt && isDirty !== undefined) {
      const item: TidyItem = { kind: 'worktree', path: d.wt, ...id, bytes: wtBytes, ageDays: age(d), isDirty }
      ;(isDirty ? scan.dirty : scan.worktrees).push(item)
    }
    if (isDirty) continue // keep the job with its dirty worktree
    const bytes = (bytesOf.get(dir) ?? 0) + (isDirty === false ? wtBytes : 0)
    scan.jobs.push({ kind: 'job', path: dir, ...id, bytes, ageDays: age(d) })
    scan.reclaimBytes += bytes
  }
  scan.jobs.sort((a, b) => b.bytes - a.bytes)
  scan.worktrees.sort((a, b) => b.bytes - a.bytes)
  scan.dirty.sort((a, b) => b.bytes - a.bytes)
  return scan
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
