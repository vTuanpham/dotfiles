import type { EngineInterface } from 'claude-code'
import { bridgeSnapshot } from './bridge'

// Read-only view of agent-bridge jobs (<root>/jobs/<owner>/<job>/). Nothing here writes.

export type CodexJob = {
  owner: string
  name: string
  title: string
  dir: string
  backend: string // 'codex' | 'agy' | 'claude' | 'opencode'
  account: string // codex-auth number or agy login dir; '' for Claude jobs
  model: string
  effort: string
  cwd: string
  running: boolean // runnerPid points to a live agent-bridge process
  isStale: boolean // live runner silent for bridge's default 15 min; root_wait is exempt
  lastEventAt: number
  startedAt?: number
  awaitingRoot: boolean // latest completion has not been acknowledged by bridge
  waitingForRoot: boolean // runner is alive but the completed turn is idle
  lastMessage?: string // <= 400 chars
  finishedAt?: number
  urgent: { at: number; text: string }[] // urgent events new since the cursor (turn_completed excluded), text <= 300
  completedNow: boolean // a turn_completed arrived since the cursor
}

export type CodexCursor = Record<string, number> // live.jsonl path -> byte offset seen

/**
 * The job owners a shell command touches: `.../agent-bridge/jobs/<owner>/...` paths, an `agent-bridge <cmd> <owner>/<job>`
 * call, and `agent-bridge watch <owner>...`. Other sessions share the root, so a session shows only the owners its own
 * commands named.
 */
export function ownersIn(command: string): string[] {
  const found = new Set<string>()
  const clean = (s: string) => s.replace(/^['"]|['"]$/g, '')
  for (const m of command.matchAll(/agent-bridge\/jobs\/([^/\s'"]+)\//g)) found.add(m[1]!)
  const valueOptions = new Set(['--backend', '--cwd', '--sandbox', '--model', '--effort', '--writable-root', '--config', '--account', '--allow', '--deny', '--prompt-file', '--stall-min', '--timeout', '-c'])
  for (const m of command.matchAll(/agent-bridge\s+(start|resume|steer|interrupt|stop|compact|archive|watch|result|ack)\b([^;|&]*)/g)) {
    const args = (m[2] ?? '').trim().split(/\s+/).filter(Boolean).map(clean)
    const positional = []
    for (let i = 0; i < args.length; i++) {
      const arg = args[i]!
      if (arg.startsWith('-')) {
        if (valueOptions.has(arg)) i++
      } else positional.push(arg)
    }
    const jobs = m[1] === 'watch' || m[1] === 'ack' ? positional : positional.slice(0, 1)
    for (const job of jobs) {
      const parts = job.split('/')
      const owner = m[1] === 'watch' || m[1] === 'ack' ? parts[0]! : parts.length === 2 ? parts[0]! : ''
      if (owner && !owner.startsWith('.') && !owner.startsWith('$') && !owner.startsWith('<') && !owner.startsWith('~')) found.add(owner)
    }
  }
  return [...found].filter(o => o && !o.startsWith('.') && !o.startsWith('$') && !o.startsWith('<'))
}

/** Whether a job belongs to one of the owners (an owner may be nested: `pb/brain` under `pb`). */
export const ownedBy = (job: { owner: string }, owners: readonly string[]) =>
  owners.some(o => job.owner === o || job.owner.startsWith(o + '/'))

/** Bridge owns job state, stalls and acknowledgements. Wake only maps presentation fields. */
export async function scanCodex(
  $: EngineInterface,
  cursor: CodexCursor,
  opts: { recentMs?: number } = {},
): Promise<{ jobs: CodexJob[]; cursor: CodexCursor }> {
  const snapshot = await bridgeSnapshot($)
  if (!snapshot) throw new Error('Bridge status unavailable')
  const now = Date.parse(snapshot.generated_at)
  const next: CodexCursor = {}
  const jobs: CodexJob[] = []
  for (const job of snapshot.jobs) {
    if (job.retired_at) continue
    const key = `${job.id}:${job.log_identity}`
    const events = snapshot.events.filter(e => e.job === job.id)
    const end = Math.max(0, ...events.map(e => e.offset))
    const previous = cursor[key]
    next[key] = end
    const fresh = previous === undefined ? [] : events.filter(e => e.offset > previous)
    const lastEventAt = job.last_event_at ? Date.parse(job.last_event_at) : now
    if (!job.running && !job.awaiting_root && now - lastEventAt > (opts.recentMs ?? 6 * 3600_000)) continue
    jobs.push({
      owner: job.owner, name: job.name, title: job.title || job.name,
      dir: job.directory, backend: job.backend ?? 'unknown', account: job.account ?? '',
      model: job.model ?? '', effort: job.effort ?? '', cwd: job.cwd ?? '',
      running: job.running, isStale: job.stall.state === 'stalled', lastEventAt,
      startedAt: job.started_at ? Date.parse(job.started_at) : undefined,
      awaitingRoot: job.awaiting_root, waitingForRoot: job.state === 'waiting_for_root',
      lastMessage: job.last_message?.slice(0, 400),
      finishedAt: job.finished_at ? Date.parse(job.finished_at) : undefined,
      urgent: fresh.filter(e => e.wakes && e.kind !== 'turn_completed')
        .map(e => ({ at: e.at ? Date.parse(e.at) : now, text: (e.text || e.kind).slice(0, 300) })),
      completedNow: fresh.some(e => e.kind === 'turn_completed'),
    })
  }
  jobs.sort((a, b) => Number(b.running) - Number(a.running) || b.lastEventAt - a.lastEventAt)
  return { jobs, cursor: next }
}
