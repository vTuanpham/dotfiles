import type { EngineInterface } from 'claude-code'
import type { BridgeSnapshot } from '../hooks/sources/bridge'

export const NOW = '2026-10-27T00:00:00Z'
export const snapshot = (): BridgeSnapshot => ({
  schema_version: 1, generated_at: NOW, jobs: [], events: [], quotas: [],
  retention: { scanned: true, items: [], reclaim_bytes: 0, archive_path: '/state/bridge/archive.jsonl' },
  peers: { nodes: [], edges: [], recent_messages: [] },
})

export const job = (changes: Partial<BridgeSnapshot['jobs'][number]> = {}): BridgeSnapshot['jobs'][number] => ({
  id: 'owner/a', owner: 'owner', name: 'a', title: 'Check bridge', directory: '/state/bridge/jobs/owner/a',
  backend: 'codex', account: '01', model: 'gpt-6-sol', effort: 'high', cwd: '/repo', running: true,
  state: 'running', reason: 'runner alive', stall: { state: 'ok', reason: 'within silence threshold' },
  last_event_at: NOW, started_at: NOW, finished_at: null, awaiting_root: false, last_message: 'ready',
  retired_at: null, log_identity: '1:2', memory_bytes: null, memory_cap: '', ...changes,
})

export const event = (offset: number, changes: Partial<BridgeSnapshot['events'][number]> = {}): BridgeSnapshot['events'][number] => ({
  id: `owner/a:1:2:${offset}`, job: 'owner/a', offset, at: NOW, kind: 'message', text: 'ready', wakes: false, ...changes,
})

export function engine(s: BridgeSnapshot) {
  const calls: string[][] = []
  const $ = { process: { run: async (args: readonly string[]) => {
    calls.push([...args])
    return { stdout: JSON.stringify(s), exitCode: 0, isStdoutTruncated: false }
  } } } as unknown as EngineInterface
  return { $, calls, s }
}
