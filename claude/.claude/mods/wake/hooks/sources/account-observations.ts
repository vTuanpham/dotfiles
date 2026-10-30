/** Decode the independent account reader's wire contract once. */
import { rfc3339 } from './wire'
export type Quota = {
  backend: string; account: string; plan: string | null; active: boolean; status: string | null
  freshness: 'fresh' | 'stale' | 'unknown'; windows: { label: string; remaining_percent: number; resets: string | null }[]
}

const object = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v)
const text = (v: unknown) => typeof v === 'string' && v.length <= 4096 && !/[\x00-\x1f\x7f]/.test(v)
const nullable = (v: unknown) => v === null || text(v)

export function validQuota(q: unknown): q is Quota {
  return object(q) && text(q.backend) && text(q.account) && nullable(q.plan) && nullable(q.status)
    && ['fresh', 'stale', 'unknown'].includes(q.freshness as string) && typeof q.active === 'boolean'
    && Array.isArray(q.windows) && q.windows.every(w => object(w) && text(w.label)
      && Number.isSafeInteger(w.remaining_percent) && (w.remaining_percent as number) >= 0
      && (w.remaining_percent as number) <= 100 && nullable(w.resets))
}

export function readAccountSnapshot(source: string): Quota[] | undefined {
  try {
    const value: unknown = JSON.parse(source)
    if (!object(value) || value.schema_version !== 1 || !Array.isArray(value.quotas)
      || !value.quotas.every(validQuota) || !Array.isArray(value.errors) || !value.errors.every(text)
      || !rfc3339(value.generated_at)) return undefined
    return value.quotas
  } catch { return undefined }
}
