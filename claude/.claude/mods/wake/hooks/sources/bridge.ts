import type { EngineInterface } from 'claude-code'

type Event = { id: string; job: string; offset: number; kind: string; at: string | null; text: string; wakes: boolean }
type Job = {
  id: string; owner: string; name: string; title: string; directory: string
  backend: string | null; account: string | null; model: string | null; effort: string | null; cwd: string | null
  running: boolean; state: string; reason: string; stall: { state: string; reason: string }
  last_event_at: string | null; started_at: string | null; finished_at: string | null
  awaiting_root: boolean; last_message: string | null; retired_at: string | null; log_identity: string
}
type Quota = {
  backend: string; account: string; plan: string | null; active: boolean; status: string | null
  freshness: string; windows: { label: string; remaining_percent: number }[]
}
type TidyItem = { kind: string; path: string; owner: string; name: string; bytes: number; age_days: number; is_dirty: boolean | null }
export type BridgeSnapshot = {
  schema_version: 1; generated_at: string; jobs: Job[]; events: Event[]; quotas: Quota[]
  retention: { scanned: boolean; items: TidyItem[]; reclaim_bytes: number | null; archive_path: string }
  peers: {
    nodes: string[]
    edges: { id: string; source: string; target: string; count: number; last_at: string; last_kind: string }[]
    recent_messages: { id: string; source: string; target: string; at: string; kind: string; size: number; preview: string | null }[]
  }
}

const object = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v)
const str = (v: unknown): v is string => typeof v === 'string'
const nullable = (v: unknown) => v === null || str(v)
const number = (v: unknown) => typeof v === 'number' && Number.isFinite(v) && v >= 0
const date = (v: unknown) => str(v) && /(Z|[+-]\d\d:\d\d)$/.test(v) && Number.isFinite(Date.parse(v))
const maybeDate = (v: unknown) => v === null || date(v)

/** Validate consumed fields, tolerate additive fields. Unknown major versions fail closed. */
export function readSnapshot(text: string): BridgeSnapshot | undefined {
  try {
    const s: unknown = JSON.parse(text)
    if (!object(s) || s.schema_version !== 1 || !date(s.generated_at)
      || !Array.isArray(s.jobs) || !Array.isArray(s.events) || !Array.isArray(s.quotas)
      || !object(s.retention) || !Array.isArray(s.retention.items) || !str(s.retention.archive_path)
      || typeof s.retention.scanned !== 'boolean' || !(s.retention.reclaim_bytes === null || number(s.retention.reclaim_bytes))
      || !object(s.peers) || !Array.isArray(s.peers.nodes) || !Array.isArray(s.peers.edges) || !Array.isArray(s.peers.recent_messages)) return undefined
    if (s.jobs.some(j => !object(j)
      || !['id', 'owner', 'name', 'title', 'directory', 'state', 'reason', 'log_identity'].every(k => str(j[k]))
      || !['backend', 'account', 'model', 'effort', 'cwd', 'last_message'].every(k => nullable(j[k]))
      || !['last_event_at', 'started_at', 'finished_at', 'retired_at'].every(k => maybeDate(j[k]))
      || typeof j.running !== 'boolean' || typeof j.awaiting_root !== 'boolean'
      || !object(j.stall) || !str(j.stall.state) || !str(j.stall.reason))) return undefined
    if (s.events.some(e => !object(e) || !['id', 'job', 'kind', 'text'].every(k => str(e[k]))
      || !Number.isSafeInteger(e.offset) || !number(e.offset) || !maybeDate(e.at) || typeof e.wakes !== 'boolean')) return undefined
    if (s.quotas.some(q => !object(q) || !str(q.backend) || !str(q.account) || !nullable(q.plan)
      || !nullable(q.status) || !str(q.freshness) || typeof q.active !== 'boolean' || !Array.isArray(q.windows)
      || q.windows.some(w => !object(w) || !str(w.label) || !Number.isSafeInteger(w.remaining_percent)
        || !number(w.remaining_percent) || (w.remaining_percent as number) > 100))) return undefined
    if (s.retention.items.some(i => !object(i) || !['kind', 'path', 'owner', 'name'].every(k => str(i[k]))
      || !Number.isSafeInteger(i.bytes) || !number(i.bytes) || !Number.isSafeInteger(i.age_days)
      || !number(i.age_days) || !(i.is_dirty === null || typeof i.is_dirty === 'boolean'))) return undefined
    if (s.peers.nodes.some(n => !str(n)) || s.peers.edges.some(e => !object(e)
      || !['id', 'source', 'target', 'last_kind'].every(k => str(e[k])) || !date(e.last_at)
      || !Number.isSafeInteger(e.count) || !number(e.count) || (e.count as number) < 1)) return undefined
    if (s.peers.recent_messages.length > 100 || s.peers.recent_messages.some(m => !object(m)
      || !['id', 'source', 'target', 'kind'].every(k => str(m[k])) || !date(m.at)
      || !Number.isSafeInteger(m.size) || !number(m.size) || !nullable(m.preview)
      || typeof m.preview === 'string' && m.preview.length > 160)) return undefined
    return s as unknown as BridgeSnapshot
  } catch { return undefined }
}

export async function bridgeSnapshot($: EngineInterface, storage = false): Promise<BridgeSnapshot | undefined> {
  const r = await $.process.run(['agent-bridge', 'status', '--json', ...(storage ? ['--storage'] : [])],
    { timeoutMs: storage ? 120_000 : 30_000 }).catch(() => undefined)
  if (!r || r.exitCode !== 0 || r.isStdoutTruncated) return undefined
  return readSnapshot(r.stdout)
}
