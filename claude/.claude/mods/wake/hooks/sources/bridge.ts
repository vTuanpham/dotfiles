import type { EngineInterface } from 'claude-code'
import { validQuota, type Quota } from './account-observations'
import { rfc3339 } from './wire'

type Event = { id: string; job: string; offset: number; kind: string; at: string | null; text: string; wakes: boolean }
type Job = {
  id: string; owner: string; name: string; title: string; directory: string
  backend: string | null; account: string | null; model: string | null; effort: string | null; cwd: string | null
  running: boolean; state: string; reason: string; stall: { state: string; reason: string }
  last_event_at: string | null; started_at: string | null; finished_at: string | null
  awaiting_root: boolean; last_message: string | null; retired_at: string | null; log_identity: string
  memory_bytes: number | null; memory_cap: string
  waiting?: { kind: string; peer: string | null; declared_at: string } | null
}
type TidyItem = { kind: string; path: string; owner: string; name: string; bytes: number; age_days: number; is_dirty: boolean | null }
type Owner = { id: string; root_backend?: string | null; root_session_id?: string | null }
export type DirectMessage = {
  id: string; source: string; target: string; direction: 'root_to_worker' | 'worker_to_root'
  at: string; recorded_at?: string | null; kind: 'message' | 'question' | 'prompt' | 'steer'; size: number | null; preview: string | null
}
export type BridgeSnapshot = {
  schema_version: 1; generated_at: string; jobs: Job[]; events: Event[]; wake_events?: Event[]; quotas: Quota[]
  owners?: Owner[]
  retention: { scanned: boolean; items: TidyItem[]; reclaim_bytes: number | null; archive_path: string }
  peers: {
    nodes: string[]
    edges: { id: string; source: string; target: string; count: number; last_at: string; last_kind: string }[]
    recent_messages: { id: string; source: string; target: string; at: string; kind: string; size: number; preview: string | null }[]
  }
  /** Absent on schema_minor < 3; present values are already bounded and locally scrubbed. */
  direct_messages?: DirectMessage[]
}

const object = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v)
const str = (v: unknown): v is string => typeof v === 'string'
const nullable = (v: unknown) => v === null || str(v)
const number = (v: unknown) => typeof v === 'number' && Number.isFinite(v) && v >= 0
const maybeDate = (v: unknown) => v === null || rfc3339(v)
const boundedPreview = (v: unknown) => nullable(v) && (typeof v !== 'string' || Array.from(v).length <= 160)

/** Validate consumed fields, tolerate additive fields. Unknown major versions fail closed. */
export function readSnapshot(text: string): BridgeSnapshot | undefined {
  try {
    const s: unknown = JSON.parse(text)
    if (!object(s) || s.schema_version !== 1 || !rfc3339(s.generated_at)
      || !Array.isArray(s.jobs) || !Array.isArray(s.events) || !Array.isArray(s.quotas)
      || !(s.wake_events === undefined || Array.isArray(s.wake_events))
      || !object(s.retention) || !Array.isArray(s.retention.items) || !str(s.retention.archive_path)
      || typeof s.retention.scanned !== 'boolean' || !(s.retention.reclaim_bytes === null || number(s.retention.reclaim_bytes))
      || !(s.owners === undefined || Array.isArray(s.owners))
      || !object(s.peers) || !Array.isArray(s.peers.nodes) || !Array.isArray(s.peers.edges) || !Array.isArray(s.peers.recent_messages)
      || !(s.direct_messages === undefined || Array.isArray(s.direct_messages) && s.direct_messages.length <= 100)) return undefined
    if (s.owners?.some(o => !object(o) || !str(o.id)
      || !(o.root_backend === undefined || nullable(o.root_backend))
      || !(o.root_session_id === undefined || nullable(o.root_session_id)))) return undefined
    if (s.jobs.some(j => !object(j)
      || !['id', 'owner', 'name', 'title', 'directory', 'state', 'reason', 'log_identity', 'memory_cap'].every(k => str(j[k]))
      || !(j.memory_bytes === null || Number.isSafeInteger(j.memory_bytes) && number(j.memory_bytes))
      || !['backend', 'account', 'model', 'effort', 'cwd', 'last_message'].every(k => nullable(j[k]))
      || !['last_event_at', 'started_at', 'finished_at', 'retired_at'].every(k => maybeDate(j[k]))
      || typeof j.running !== 'boolean' || typeof j.awaiting_root !== 'boolean'
      || !(j.waiting === undefined || j.waiting === null || object(j.waiting) && ['command', 'peer', 'root', 'external', 'dependency'].includes(j.waiting.kind as string) && nullable(j.waiting.peer) && rfc3339(j.waiting.declared_at))
      || !object(j.stall) || !str(j.stall.state) || !str(j.stall.reason))) return undefined
    const validEvent = (e: unknown) => object(e) && ['id', 'job', 'kind', 'text'].every(k => str(e[k]))
      && Number.isSafeInteger(e.offset) && number(e.offset) && maybeDate(e.at) && typeof e.wakes === 'boolean'
    if (s.events.some(e => !validEvent(e)) || s.wake_events?.some(e => !validEvent(e))) return undefined
    if (s.quotas.some(q => !validQuota(q))) return undefined
    if (s.retention.items.some(i => !object(i) || !['kind', 'path', 'owner', 'name'].every(k => str(i[k]))
      || !Number.isSafeInteger(i.bytes) || !number(i.bytes) || !Number.isSafeInteger(i.age_days)
      || !number(i.age_days) || !(i.is_dirty === null || typeof i.is_dirty === 'boolean'))) return undefined
    if (s.peers.nodes.some(n => !str(n)) || s.peers.edges.some(e => !object(e)
      || !['id', 'source', 'target', 'last_kind'].every(k => str(e[k])) || !rfc3339(e.last_at)
      || !Number.isSafeInteger(e.count) || !number(e.count) || (e.count as number) < 1)) return undefined
    if (s.peers.recent_messages.length > 100 || s.peers.recent_messages.some(m => !object(m)
      || !['id', 'source', 'target', 'kind'].every(k => str(m[k])) || !rfc3339(m.at)
      || !Number.isSafeInteger(m.size) || !number(m.size) || !boundedPreview(m.preview))) return undefined
    if (s.direct_messages?.some(m => !object(m)
      || !['id', 'source', 'target'].every(k => str(m[k]))
      || !['root_to_worker', 'worker_to_root'].includes(m.direction as string)
      || !['message', 'question', 'prompt', 'steer'].includes(m.kind as string)
      || m.direction === 'root_to_worker' && !['prompt', 'steer'].includes(m.kind as string)
      || m.direction === 'worker_to_root' && !['message', 'question'].includes(m.kind as string)
      || !rfc3339(m.at) || !(m.recorded_at === undefined || maybeDate(m.recorded_at))
      || !(m.size === null || Number.isSafeInteger(m.size) && number(m.size))
      || !boundedPreview(m.preview))) return undefined
    return s as unknown as BridgeSnapshot
  } catch { return undefined }
}

export async function bridgeSnapshot(
  $: EngineInterface,
  storage = false,
  ownerScopes?: readonly string[],
): Promise<BridgeSnapshot | undefined> {
  if (ownerScopes && ownerScopes.length === 0) return undefined
  const args = ['agent-bridge', 'status', '--json', ...(storage ? ['--storage'] : [])]
  args.push(...ownerScopes ?? [])
  const r = await $.process.run(args,
    { timeoutMs: storage ? 120_000 : 30_000 }).catch(() => undefined)
  if (!r || r.exitCode !== 0 || r.isStdoutTruncated) return undefined
  return readSnapshot(r.stdout)
}
