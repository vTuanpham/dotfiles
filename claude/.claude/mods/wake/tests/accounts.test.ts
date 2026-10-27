import { expect, test } from 'claude-code/testing'
import { jobLabel, makerOf, modelTier, quotaGroups, scanQuotas } from '../hooks/sources/accounts'
import { engine, snapshot } from './status-world'

test('every job reads cli-agnostic: short model family + effort', () => {
  expect(jobLabel('agy', 'gemini-3.8-flash-high', '')).toEqual({ model: 'flash', effort: 'high' })
  expect(jobLabel('agy', 'claude-opus-5-5-medium', '')).toEqual({ model: 'opus', effort: 'medium' })
  expect(jobLabel('codex', 'gpt-6-luna', 'xhigh')).toEqual({ model: 'luna', effort: 'xhigh' })
  expect(jobLabel('claude', 'claude-sonnet-5-5', '')).toEqual({ model: 'sonnet', effort: '' })
  expect(jobLabel('claude', 'sonnet', 'high')).toEqual({ model: 'sonnet', effort: 'high' })
})

test('consecutive accounts with the same numbers fold into one group', () => {
  const base = { cli: 'codex' as const, plan: 'Plus', active: false, parts: [{ label: 'w', pct: 39 }] }
  const g = quotaGroups([{ ...base, account: '01' }, { ...base, account: '02', active: true }])
  expect(g.map(x => [x.accounts.join(' '), x.text])).toEqual([['01 02*', 'w39']])
})

test('quota numbers come only from the snapshot; refresh does not parse its text', async () => {
  const s = snapshot()
  s.quotas = [{ backend: 'agy', account: 'a1', plan: 'Pro', active: false, status: null,
    freshness: 'stale', windows: [{ label: 'Gh', remaining_percent: 42 }] }]
  const w = engine(s)
  const result = await scanQuotas(w.$, { refreshAgy: true })
  expect(result[0]).toMatchObject({ cli: 'agy', account: 'a1', parts: [{ label: 'Gh', pct: 42 }] })
  expect(w.calls).toEqual([['agent-bridge', 'quota', '--backend', 'agy'], ['agent-bridge', 'status', '--json']])
})

test('modelTier reads the family, not the version or the effort', () => {
  expect(['gpt-6-luna', 'gpt-7-sol', 'gpt-6-astra', 'gpt-6-mini'].map(m => modelTier('codex', m))).toEqual([1, 2, 3, 2])
  expect(['claude-haiku-5', 'claude-sonnet-5-5-high', 'opus', 'gemini-3-flash', 'gemini-3-pro-low', 'argon-high', '', 'mystery'].map(m => modelTier('agy', m))).toEqual([1, 2, 3, 1, 2, 3, 2, 2])
  expect(['claude-opus-5-5-medium', 'claude-sonnet-5', 'gemini-4-argon', 'gemini-3-flash'].map(makerOf)).toEqual(['claude', 'claude', undefined, undefined]) // Claude inside agy wears its pink
})

test('modelTier reads an OpenCode model by its size word; free never counts, unknown is mid', () => {
  const ids = ['opencode/nemotron-3-ultra-free', 'opencode/glm-5.3-flash-free', 'openrouter/google/gemma-4-31b-it:free', 'openrouter/meta-llama/llama-4-405b-instruct', 'opencode-go/qwen4-coder-plus', 'opencode/mistral-small-4', 'opencode/claude-opus-5', 'opencode-go/minimax-m3']
  expect(ids.map(m => modelTier('opencode', m))).toEqual([3, 1, 2, 3, 2, 1, 3, 2])
  expect(['opencode/nemotron-3-super', 'opencode/nemotron-3-super-free', 'openrouter/x/nemotron-3-super:free'].map(m => modelTier('opencode', m))).toEqual([2, 2, 2])
  expect(modelTier('agy', 'openrouter/x/kimi-k3-pro')).toBe(3) // the id alone marks it, whichever backend
  expect(jobLabel('opencode', 'openrouter/google/gemma-4-31b-it:free', '')).toEqual({ model: 'gemma-4-31b-it', effort: '' })
})
