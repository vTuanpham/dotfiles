import type { EngineInterface } from 'claude-code'
import type { WakeQuota } from '../../types'

// Quota per signed-in account of both bridges, read-only: `codex-auth list` (its own local cache; emails are never
// kept) and agy's per-account cache ~/.agy-accounts/<a>/quota.json (written by `agent-bridge quota --backend agy`).

/** `codex-auth list` rows -> one quota per account; no email survives. Windows depend on the plan: Free has a monthly
 * limit only (m), Plus a five-hour and a weekly (h w), Pro / Pro Lite a weekly only (w). */
export function parseCodexAuth(text: string): WakeQuota[] {
  const out: WakeQuota[] = []
  for (const line of text.split('\n')) {
    const m = /^\s*(\*)?\s*(\d{2})\s+\S+@\S+\s+(.*)$/.exec(line)
    if (!m) continue
    const rest = m[3] ?? ''
    const plan = (/^([A-Za-z][A-Za-z ]*?)\s{2,}/.exec(rest)?.[1] ?? '').trim()
    const pcts = [...rest.matchAll(/(\d+)%/g)].map(p => Number(p[1]))
    const parts = pcts.length === 0 ? []
      : /^free/i.test(plan) ? [{ label: 'm', pct: pcts[0]! }] // codex-auth prints the monthly number in its 5H column
      : /^plus/i.test(plan) ? pcts.map((pct, i) => ({ label: i === 0 ? 'h' : 'w', pct }))
      : [{ label: 'w', pct: pcts[1] ?? pcts[0]! }] // Pro: its 5H column repeats the weekly number
    out.push({ cli: 'codex', account: m[2]!, plan, active: m[1] === '*', parts, status: rest.includes('token_expired') ? 'expired' : undefined })
  }
  return out
}

const GROUP: Record<string, string> = { 'Gemini Models': 'G', 'Claude and GPT models': 'C', 'Gemini 4 Argon': 'A' }

/** One cached `/usage` result -> each bucket's limits (G Gemini, C Claude, A Argon) × window (h five-hour, w weekly). */
export function parseAgyQuota(text: string): WakeQuota | undefined {
  try {
    const v = JSON.parse(text) as { account?: string; rows?: { group: string; limit: string; remaining: number }[] }
    if (!v.account || !Array.isArray(v.rows)) return undefined
    const parts = v.rows
      .map(r => ({ label: (GROUP[r.group] ?? r.group.slice(0, 1)) + (/five hour/i.test(r.limit) ? 'h' : 'w'), pct: r.remaining }))
      .sort((a, b) => a.label[0] === b.label[0] ? a.label.localeCompare(b.label) : 0) // per bucket: h before w
    return { cli: 'agy', account: v.account, plan: 'Pro', active: false, parts }
  } catch {
    return undefined
  }
}

/** One display label for any bridge job: short model family + effort, whichever CLI it runs on. */
export function jobLabel(backend: string, model: string, effort: string): { model: string; effort: string } {
  if (backend === 'codex') return { model: model.replace(/^gpt-[\d.]+-/, ''), effort }
  if (backend === 'opencode') return { model: model.replace(/^.*\//, '').replace(/[:-]free$/, ''), effort } // the model, not its provider path
  const m = /^(.*?)(?:-(low|medium|high))?$/.exec(model)
  const family = ['argon', 'flash', 'opus', 'sonnet'].find(f => model.includes(f)) ?? (m?.[1] ?? model)
  return { model: family, effort: effort || (m?.[2] ?? '') }
}

/** How capable a model is by family name, so new versions need no table: 1 small, 2 mid, 3 frontier; unknown is mid. Trailing effort words never count. */
export type Tier = 1 | 2 | 3
const FAMILY: Record<string, Tier> = { luna: 1, sol: 2, astra: 3, haiku: 1, sonnet: 2, opus: 3, flash: 1, pro: 2, argon: 3 }
const CODEX_FAMILY = ['luna', 'sol', 'astra']
// OpenCode serves any provider's models (ids like opencode/<m>, opencode-go/<m>, openrouter/<org>/<m>:free): read the size
// word first (':free' is no size), then a known family name, else mid
const OPEN_SIZE: Record<string, Tier> = {
  ultra: 3, max: 3, large: 3, pro: 3, '550b': 3, '405b': 3,
  super: 2, medium: 2, plus: 2,
  flash: 1, lightning: 1, mini: 1, nano: 1, lite: 1, small: 1,
}
export function modelTier(backend: string, model: string): Tier {
  if (backend === 'opencode' || /^(opencode(-go)?|openrouter)\//.test(model)) {
    const size = model.toLowerCase().split(/[^a-z0-9]+/).find(n => Object.hasOwn(OPEN_SIZE, n))
    if (size) return OPEN_SIZE[size]!
  }
  const names = model.toLowerCase().split(/[^a-z]+/)
  const family = names.find(n => Object.hasOwn(FAMILY, n) && (backend !== 'codex' || CODEX_FAMILY.includes(n)))
  return family ? FAMILY[family]! : 2
}

/** Whose model a job runs, when that maker has a crew family of its own: a Claude model inside agy wears Claude's pink. */
export const makerOf = (model: string): 'claude' | undefined => (/\b(claude|opus|sonnet|haiku)\b/.test(model.toLowerCase()) ? 'claude' : undefined)

/** Consecutive accounts with the same displayed quota bars fold into one chip. */
export function quotaGroups(quotas: WakeQuota[]): { cli: 'codex' | 'agy'; accounts: string[]; text: string; low: boolean; bad: boolean }[] {
  const out: ReturnType<typeof quotaGroups> = []
  for (const q of quotas) {
    const text = q.status ? '!' : q.parts.map(p => {
      const bar = !Number.isFinite(p.pct) || p.pct < 0 || p.pct > 100 ? '?'
        : p.pct === 0 ? '·' : '▁▂▃▄▅▆▇█'[Math.ceil(p.pct / 12.5) - 1]!
      return p.label + bar
    }).join('') || '?'
    const name = q.account + (q.active ? '*' : '')
    const last = out.at(-1)
    if (last && last.cli === q.cli && last.text === text) last.accounts.push(name)
    else out.push({ cli: q.cli, accounts: [name], text, low: q.parts.some(p => p.pct < 20), bad: q.status !== undefined })
  }
  return out
}

export async function scanQuotas($: EngineInterface, opts: { refreshAgy?: boolean } = {}): Promise<WakeQuota[]> {
  if (opts.refreshAgy) {
    // `/usage` makes no model call; failures leave the previous cache in place
    await $.process.run(['agent-bridge', 'quota', '--backend', 'agy'], { timeoutMs: 180_000 }).catch(() => undefined)
  }
  const home = await $.env.get('HOME')
  if (!home) return []
  const codex = await $.process.run(['codex-auth', 'list']).catch(() => undefined)
  const found = await $.process.run(['find', `${home}/.agy-accounts`, '-maxdepth', '2', '-name', 'quota.json']).catch(() => undefined)
  const agy: WakeQuota[] = []
  for (const path of found?.stdout.split('\n').filter(Boolean) ?? []) {
    const q = parseAgyQuota(await $.fs.read(path).catch(() => ''))
    if (q) agy.push(q)
  }
  return [...(codex?.exitCode === 0 ? parseCodexAuth(codex.stdout) : []), ...agy.sort((a, b) => a.account.localeCompare(b.account))]
}
