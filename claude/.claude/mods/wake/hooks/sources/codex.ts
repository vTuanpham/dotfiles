import type { EngineInterface } from 'claude-code'
import { bridgePaths, bridgeRunnerAlive } from './bridge'

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
  attention?: 'error' | 'question' // urgent event still pending in bridge's acknowledgement cursor
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

const STALE_MS = 15 * 60_000
const TAIL_BYTES = 64 * 1024
const DEFAULT_RECENT_MS = 6 * 3600_000
const MESSAGE_CHARS = 400
const URGENT_CHARS = 300

type Acknowledgement = { log: string; through: number; completed: number; seen: number }

async function readAcknowledgements($: EngineInterface, path: string): Promise<Record<string, Acknowledgement>> {
  try {
    const data = JSON.parse(await $.fs.read(path)) as { version?: unknown; jobs?: unknown }
    if (data?.version !== 1 || !data.jobs || typeof data.jobs !== 'object' || Array.isArray(data.jobs)) return {}
    const jobs = data.jobs as Record<string, Acknowledgement>
    if (Object.values(jobs).some(c =>
      !c || typeof c !== 'object' || Object.keys(c).sort().join(',') !== 'completed,log,seen,through' ||
      typeof c.log !== 'string' || [c.through, c.completed, c.seen].some(n => !Number.isSafeInteger(n) || n < 0),
    )) return {}
    return jobs
  } catch {
    return {} // missing or invalid acknowledgements leave completions visible
  }
}

type Ev = { at: number; kind: string; level?: string; text?: string; end: number; quietSeconds?: number; attention?: 'error' | 'question' }
type Meta = { lastMessage?: string; finishedAt?: number; completedEnd?: number; startedAt?: number; lastKind?: string; silentSince?: number; identity?: string; attention?: 'error' | 'question'; attentionEnd?: number }

// What the last events said, per live.jsonl. Re-derivable from a 64 KB tail, so a reload only costs one read.
const metaOf = new Map<string, Meta>()

// `$.fs.read` has no offset and rejects past 4 MiB, while live.jsonl runs to hundreds of MB: tail does the seeking.
async function tail($: EngineInterface, path: string, from?: number): Promise<{ text: string; isTruncated: boolean } | undefined> {
  const arg = from === undefined ? String(TAIL_BYTES) : `+${from + 1}`
  const r = await $.process.run(['tail', '-c', arg, path]).catch(() => undefined)
  return r && r.exitCode === 0 ? { text: r.stdout, isTruncated: r.isStdoutTruncated } : undefined
}

function utf8Len(s: string): number {
  let n = 0
  for (const ch of s) {
    const c = ch.codePointAt(0) ?? 0
    n += c < 0x80 ? 1 : c < 0x800 ? 2 : c < 0x10000 ? 3 : 4
  }
  return n
}

function clip(s: string, max: number): string {
  return s.length > max ? `${s.slice(0, max - 1)}…` : s
}

function parseEvents(text: string, offset = 0): Ev[] {
  const out: Ev[] = []
  for (const line of text.slice(0, text.lastIndexOf('\n') + 1).split('\n').slice(0, -1)) {
    offset += utf8Len(line) + 1
    if (!line.startsWith('{')) continue
    try {
      const v = JSON.parse(line) as Record<string, unknown>
      if (typeof v.kind !== 'string') continue
      const at = typeof v.at === 'string' ? Date.parse(v.at) : NaN
      out.push({
        at: Number.isNaN(at) ? 0 : at,
        kind: v.kind,
        end: offset,
        quietSeconds: typeof v.quietSeconds === 'number' && Number.isFinite(v.quietSeconds) && v.quietSeconds >= 0 ? v.quietSeconds : undefined,
        level: typeof v.level === 'string' ? v.level : undefined,
        text: typeof v.text === 'string' ? v.text : undefined,
        attention: ['error', 'permission_denied', 'approval_declined', 'question_timeout'].includes(v.kind) || (v.kind === 'turn_completed' && Boolean(v.error))
          ? 'error' : v.kind === 'question' || (v.kind === 'message' && v.level === 'urgent') ? 'question' : undefined,
      })
    } catch {
      // malformed or half-written line: skip
    }
  }
  return out
}

function absorb(meta: Meta, events: Ev[]): void {
  for (const e of events) {
    meta.lastKind = e.kind
    if (e.attention) {
      meta.attention = e.attention
      meta.attentionEnd = e.end
    }
    meta.silentSince = e.kind === 'stalled' && e.quietSeconds !== undefined ? e.at - e.quietSeconds * 1000 : undefined
    if (e.kind === 'turn_started') meta.startedAt = e.at || undefined
    if (e.kind === 'message' && e.text) meta.lastMessage = clip(e.text, MESSAGE_CHARS)
    if (e.kind === 'turn_completed') {
      meta.finishedAt = e.at
      meta.completedEnd = e.end
    }
  }
}

async function activeTurn($: EngineInterface, dir: string): Promise<{ active: boolean; retired: boolean; runnerAlive: boolean; backend: string; account: string; model: string; effort: string; cwd: string; title: string }> {
  try {
    const s = JSON.parse(await $.fs.read(`${dir}/state.json`)) as Record<string, unknown>
    const str = (k: string) => (typeof s[k] === 'string' ? (s[k] as string) : '')
    return { active: s.activeTurnId != null, retired: Boolean(s.retiredAt), runnerAlive: await bridgeRunnerAlive($, s.runnerPid), backend: str('backend') || 'codex', account: str('account'), model: str('model'), effort: str('effort'), cwd: str('cwd'), title: str('title') }
  } catch {
    return { active: false, retired: false, runnerAlive: false, backend: 'codex', account: '', model: '', effort: '', cwd: '', title: '' }
  }
}

export async function scanCodex(
  $: EngineInterface,
  cursor: CodexCursor,
  opts: { recentMs?: number } = {},
): Promise<{ jobs: CodexJob[]; cursor: CodexCursor }> {
  const recentMs = opts.recentMs ?? DEFAULT_RECENT_MS
  const paths = await bridgePaths($)
  const next: CodexCursor = {}
  if (!paths) return { jobs: [], cursor: next }
  const root = paths.jobs
  const now = await $.clock.now()

  // Include old logs: a finished job stays visible until its completion is acknowledged.
  const found = await $.process
    .run(['find', root, '-maxdepth', '3', '(', '-name', 'live.jsonl', '-o', '-name', 'state.json', ')', '-printf', '%T@ %s %D:%i %p\\n'])
    .catch(() => undefined)
  const jobs: CodexJob[] = []
  const candidates = new Map<string, { lastEventAt: number; size: number; identity: string }>()
  const acknowledgements = new Map<string, Record<string, Acknowledgement>>()

  for (const line of found?.stdout.split('\n') ?? []) {
    const m = /^(\d+)(?:\.\d+)? (\d+) (\d+:\d+) (.+)\/(live\.jsonl|state\.json)$/.exec(line)
    if (!m) continue
    const mtime = Number(m[1]) * 1000
    const size = Number(m[2])
    const dir = m[4] ?? ''
    const previous = candidates.get(dir) ?? { lastEventAt: mtime, size: 0, identity: '' }
    candidates.set(dir, m[5] === 'live.jsonl' ? { lastEventAt: mtime, size, identity: m[3]! } : previous)
  }

  for (const [dir, { lastEventAt: mtime, size, identity }] of candidates) {
    const path = `${dir}/live.jsonl`
    const parts = dir.slice(root.length + 1).split('/')
    const owner = parts.slice(0, -1).join('/')
    const name = parts.at(-1) ?? ''
    if (!acknowledgements.has(owner)) {
      acknowledgements.set(owner, await readAcknowledgements($, `${root}/${owner}/ack.json`))
    }
    const ack = acknowledgements.get(owner)?.[name]
    const validAck = ack?.log === identity && Math.max(ack.through, ack.completed, ack.seen) <= size ? ack : undefined
    const acknowledged = validAck ? Math.max(validAck.through, validAck.completed) : 0
    const cached = metaOf.get(path)
    const prev = cached?.identity && cached.identity !== identity ? undefined : cursor[path]
    next[path] = prev ?? size

    let fresh: Ev[] = []
    let meta = prev === undefined ? undefined : cached
    let tailed = false

    if (size === 0) {
      next[path] = prev ?? 0
    } else if (prev === undefined) {
      // First sight: old history is not news. Read the tail for the last message, start at the last whole line.
      const t = await tail($, path)
      if (t) {
        const body = size > TAIL_BYTES ? t.text.slice(t.text.indexOf('\n') + 1) : t.text
        meta = {}
        absorb(meta, parseEvents(body, size - utf8Len(body)))
        next[path] = Math.max(0, size - utf8Len(t.text.slice(t.text.lastIndexOf('\n') + 1)))
        tailed = true
      }
    } else if (size !== prev) {
      const from = size < prev ? 0 : prev // truncated or rotated: start over
      const t = await tail($, path, from)
      if (t) {
        const cut = t.text.lastIndexOf('\n') + 1 // keep a half-written line for the next scan
        if (size < prev) meta = {}
        fresh = parseEvents(t.text.slice(0, cut), from)
        // ponytail: a single line over 4 MiB cannot be read; skip past it rather than stall
        next[path] = cut === 0 && t.isTruncated ? size : from + utf8Len(t.text.slice(0, cut))
      } else {
        next[path] = prev
      }
    }

    if (size > 0 && !meta && !tailed) {
      const t = await tail($, path)
      meta = {}
      if (t) {
        const body = size > TAIL_BYTES ? t.text.slice(t.text.indexOf('\n') + 1) : t.text
        absorb(meta, parseEvents(body, size - utf8Len(body)))
      }
    }
    meta ??= {}
    absorb(meta, fresh)
    meta.identity = identity
    metaOf.set(path, meta)

    const st = await activeTurn($, dir)
    if (st.retired) continue
    const running = st.runnerAlive
    const lastEventAt = meta.silentSince ?? mtime
    const awaitingRoot = (meta.completedEnd ?? 0) > acknowledged
    const attention = (meta.attentionEnd ?? 0) > (validAck?.through ?? 0) ? meta.attention : undefined
    const waitingForRoot = running && !st.active && (awaitingRoot || meta.lastKind === 'root_wait')
    if (!running && !awaitingRoot && !attention && now - lastEventAt > recentMs) continue

    jobs.push({
      owner: parts.length > 1 ? parts.slice(0, -1).join('/') : '',
      name: parts.at(-1) ?? '',
      title: st.title || parts.at(-1) || '',
      dir,
      backend: st.backend,
      account: st.account,
      model: st.model,
      effort: st.effort,
      cwd: st.cwd,
      running,
      isStale: running && !waitingForRoot && meta.lastKind !== 'root_wait' && now - lastEventAt >= STALE_MS,
      lastEventAt,
      startedAt: meta.startedAt,
      awaitingRoot,
      waitingForRoot,
      attention,
      lastMessage: meta.lastMessage,
      finishedAt: meta.finishedAt,
      urgent: fresh
        .filter(e => e.level === 'urgent' && e.kind !== 'turn_completed')
        .map(e => ({ at: e.at, text: clip(e.text ?? e.kind, URGENT_CHARS) })),
      completedNow: fresh.some(e => e.kind === 'turn_completed'),
    })
  }

  jobs.sort((a, b) => Number(b.running) - Number(a.running) || b.lastEventAt - a.lastEventAt)
  return { jobs, cursor: next }
}
