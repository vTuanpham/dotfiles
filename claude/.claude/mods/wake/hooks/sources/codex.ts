import type { EngineInterface } from 'claude-code'
import { bridgeSnapshot, type DirectMessage } from './bridge'

// Read-only view of agent-bridge jobs (<root>/jobs/<owner>/<job>/). Nothing here writes.

export type CodexJob = {
  id: string
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
  state: string
  reason: string
  eventKnown: boolean
  memoryBytes: number | null
  memoryCap: string
  peers: { target: string; count: number; lastAt: number; outgoing: boolean; preview?: string | null; kind?: string; messageId?: string; messageState?: 'observed' | 'sent' }[]
  waitingPeer?: { target: string; declaredAt: number }
}

function directRootPeers(job: Pick<CodexJob, 'id' | 'owner'>, messages: DirectMessage[]): CodexJob['peers'] {
  const root = `root/${job.owner}`
  const directions = new Map<boolean, DirectMessage[]>()
  for (const message of messages) {
    const outgoing = message.direction === 'worker_to_root'
    const matches = outgoing
      ? message.source === job.id && message.target === root
      : message.source === root && message.target === job.id
    if (!matches) continue
    const items = directions.get(outgoing) ?? []
    items.push(message)
    directions.set(outgoing, items)
  }
  return [...directions].map(([outgoing, items]) => {
    const recordedAt = (message: DirectMessage) => Date.parse(message.recorded_at ?? message.at)
    // Stable timestamp sorting retains Bridge's append order for simultaneous
    // events; IDs are opaque strings, not sortable sequence numbers. Older
    // status snapshots have no recorded_at and use the source timestamp.
    const ordered = [...items].sort((a, b) => recordedAt(a) - recordedAt(b))
    const latest = ordered.at(-1)!
    return {
      target: 'root',
      count: ordered.length,
      lastAt: recordedAt(latest),
      outgoing,
      preview: latest.preview,
      kind: latest.kind,
      messageId: latest.id,
      messageState: outgoing ? 'observed' : 'sent',
    }
  })
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

/** Remove only explicitly tagged rows; older session state has no owner and remains readable. */
export function withoutDetachedOwners<T extends { owner?: string }>(rows: readonly T[], owners: readonly string[]): T[] {
  const detached = new Set(owners)
  return rows.filter(row => !row.owner || !detached.has(row.owner))
}

/** Bridge owns job state, stalls and acknowledgements. Wake only maps presentation fields. */
export async function scanCodex(
  $: EngineInterface,
  cursor: CodexCursor,
  opts: { recentMs?: number; root?: { backend: string; session_id: string }; owners?: readonly string[] } = {},
): Promise<{ jobs: CodexJob[]; cursor: CodexCursor; detachedOwners: string[] }> {
  if (opts.owners && opts.owners.length === 0) return { jobs: [], cursor: {}, detachedOwners: [] }
  const snapshot = await bridgeSnapshot($, false, opts.owners)
  if (!snapshot) throw new Error('Bridge status unavailable')
  const now = Date.parse(snapshot.generated_at)
  const next: CodexCursor = {}
  const jobs: CodexJob[] = []
  const detachedOwners = (snapshot.owners ?? []).filter(owner =>
    opts.root && owner.root_backend && owner.root_session_id
    && (owner.root_backend !== opts.root.backend || owner.root_session_id !== opts.root.session_id))
    .filter(owner => !opts.owners || ownedBy({ owner: owner.id }, opts.owners))
    .map(owner => owner.id)
  const detached = new Set(detachedOwners)
  for (const job of snapshot.jobs) {
    if (opts.owners && !ownedBy(job, opts.owners)) continue
    const key = `${job.id}:${job.log_identity}`
    const events = snapshot.events.filter(e => e.job === job.id)
    const end = Math.max(0, ...events.map(e => e.offset))
    const previous = cursor[key]
    next[key] = end
    if (job.retired_at || detached.has(job.owner)) continue
    const fresh = previous === undefined
      ? (snapshot.wake_events ?? []).filter(e => e.job === job.id && e.wakes)
      : events.filter(e => e.offset > previous)
    const lastEventAt = job.last_event_at ? Date.parse(job.last_event_at) : now
    if (!job.running && !job.awaiting_root && now - lastEventAt > (opts.recentMs ?? 6 * 3600_000)) continue
    jobs.push({
      id: job.id, owner: job.owner, name: job.name, title: job.title || job.name,
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
      state: job.state, reason: job.stall.state === 'stalled' ? job.stall.reason : job.reason,
      eventKnown: job.last_event_at !== null, memoryBytes: job.memory_bytes, memoryCap: job.memory_cap,
      waitingPeer: job.waiting?.peer && ['peer', 'dependency'].includes(job.waiting.kind) ? { target: job.waiting.peer, declaredAt: Date.parse(job.waiting.declared_at) } : undefined,
      peers: [
        ...snapshot.peers.edges.filter(e => (e.source === job.id || e.target === job.id)
          && e.source.startsWith(`${job.owner}/`) && e.target.startsWith(`${job.owner}/`)).map(e => {
          const message = snapshot.peers.recent_messages.filter(m => m.source === e.source && m.target === e.target && Date.parse(m.at) === Date.parse(e.last_at) && m.kind === e.last_kind).at(-1)
          return { target: e.source === job.id ? e.target : e.source, count: e.count, lastAt: Date.parse(e.last_at), outgoing: e.source === job.id,
            preview: message?.preview ?? null, kind: message?.kind, messageId: message?.id }
        }),
        ...directRootPeers(job, snapshot.direct_messages ?? []),
      ],
    })
  }
  jobs.sort((a, b) => Number(b.running) - Number(a.running) || b.lastEventAt - a.lastEventAt)
  return { jobs, cursor: next, detachedOwners }
}
