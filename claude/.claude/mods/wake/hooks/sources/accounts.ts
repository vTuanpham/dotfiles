import type { EngineInterface } from 'claude-code'
import type { WakeQuota } from '../../types'

import { bridgeSnapshot } from './bridge'

/** One display label for any bridge job: short model family + effort, whichever CLI it runs on. */
export function jobLabel(backend: string, model: string, effort: string): { model: string; effort: string } {
  if (backend === 'codex') return { model: model.replace(/^gpt-[\d.]+-/, ''), effort }
  if (backend === 'opencode') return { model: model.replace(/^.*\//, '').replace(/[:-]free$/, ''), effort } // the model, not its provider path
  const m = /^(.*?)(?:-(low|medium|high))?$/.exec(model)
  const family = ['argon', 'flash', 'opus', 'sonnet'].find(f => model.includes(f)) ?? (m?.[1] ?? model)
  return { model: family, effort: effort || (m?.[2] ?? '') }
}

/** Model class by family; unknown is mid. Trailing effort words never count. */
export type Tier = 1 | 2 | 3 | 4
const FAMILY: Record<string, Tier> = { luna: 1, terra: 2, sol: 3, astra: 4, haiku: 1, sonnet: 2, opus: 3, fable: 4, flash: 1, pro: 2, argon: 3 }
const CODEX_FAMILY = ['luna', 'terra', 'sol', 'astra']
// OpenCode serves any provider's models (ids like opencode/<m>, opencode-go/<m>, openrouter/<org>/<m>:free): read the size
// word first (':free' is no size), then a known family name, else mid
const OPEN_SIZE: Record<string, Tier> = {
  ultra: 3, max: 3, large: 3, pro: 3, '550b': 3, '405b': 3,
  super: 2, medium: 2, plus: 2,
  flash: 1, lightning: 1, mini: 1, nano: 1, lite: 1, small: 1,
}
export function modelTier(backend: string, model: string): Tier {
  if (backend === 'opencode' || /^(opencode(-go)?|openrouter)\//.test(model)) {
    const family = model.toLowerCase().split(/[^a-z]+/).find(n => ['luna', 'terra', 'sol', 'astra', 'haiku', 'sonnet', 'opus', 'fable'].includes(n))
    if (family) return FAMILY[family]!
    const size = model.toLowerCase().split(/[^a-z0-9]+/).find(n => Object.hasOwn(OPEN_SIZE, n))
    if (size) return OPEN_SIZE[size]!
  }
  const names = model.toLowerCase().split(/[^a-z]+/)
  const family = names.find(n => Object.hasOwn(FAMILY, n) && (backend !== 'codex' || CODEX_FAMILY.includes(n)))
  return family ? FAMILY[family]! : 2
}

/** Whose model a job runs, when that maker has a crew family of its own: a Claude model inside agy wears Claude's pink. */
export const makerOf = (model: string): 'claude' | undefined => (/\b(claude|fable|opus|sonnet|haiku)\b/.test(model.toLowerCase()) ? 'claude' : undefined)

/** Consecutive accounts of one CLI with the same numbers fold into one group, so four idle free accounts read once. */
export function quotaGroups(quotas: WakeQuota[]): { cli: 'codex' | 'agy'; accounts: string[]; text: string; low: boolean; bad: boolean }[] {
  const out: ReturnType<typeof quotaGroups> = []
  for (const q of quotas) {
    // agy parts are bucket+window ('Gh', 'Gw'): print each bucket once, then its windows, like codex's 'h39 w39'
    const text = q.status ?? (q.cli === 'agy'
      ? [...new Set(q.parts.map(p => p.label[0]))].map(b => `${b} ${q.parts.filter(p => p.label[0] === b).map(p => `${p.label.slice(1)}${p.pct}`).join(' ')}`).join(' · ')
      : q.parts.map(p => `${p.label}${p.pct}`).join(' '))
    const name = q.account + (q.active ? '*' : '')
    const last = out.at(-1)
    if (last && last.cli === q.cli && last.text === text) last.accounts.push(name)
    else out.push({ cli: q.cli, accounts: [name], text, low: q.parts.some(p => p.pct < 20), bad: q.status !== undefined })
  }
  return out
}

export async function scanQuotas($: EngineInterface, opts: { refreshAgy?: boolean } = {}): Promise<WakeQuota[]> {
  if (opts.refreshAgy) {
    // Preserve the existing refresh schedule; consume numbers only from the status contract.
    await $.process.run(['agent-bridge', 'quota', '--backend', 'agy'], { timeoutMs: 180_000 }).catch(() => undefined)
  }
  const snapshot = await bridgeSnapshot($)
  if (!snapshot) throw new Error('Bridge quota status unavailable')
  return snapshot.quotas.filter(q => q.backend === 'codex' || q.backend === 'agy').map(q => ({
    cli: q.backend as 'codex' | 'agy', account: q.account, plan: q.plan ?? '', active: q.active,
    parts: q.windows.map(w => ({ label: w.label, pct: w.remaining_percent })), status: q.status ?? undefined, freshness: q.freshness,
  }))
}
