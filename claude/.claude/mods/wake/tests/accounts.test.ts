import { expect, test } from 'claude-code/testing'

import { jobLabel, makerOf, modelTier, parseAgyQuota, parseCodexAuth, quotaGroups } from '../hooks/sources/accounts'

const LIST = `     ACCOUNT                    PLAN      CREDITS            RESET CREDITS      5H                      WEEKLY                 LAST ACTIVITY
--------------------------------------------------------------------------------------------------------------------------------------------
  01 alice@example.com  Pro Lite  0                  0                  39% (09:10 on 25 Oct)   39% (09:10 on 25 Oct)  Now
  02 bob@example.com  Free      401 token_expired  401 token_expired  401 token_expired       401 token_expired      17d ago
* 03 carol@example.com    Free      -                  0                  100% (12:58 on 18 Nov)  -                      Now
`

test('a Plus account shows both its five-hour and weekly windows', () => {
  const q = parseCodexAuth('  07 erin@example.com  Plus      0                  0                  62% (14:00 on 19 Oct)   81% (09:10 on 25 Oct)  Now\n')
  expect(q[0]).toMatchObject({ plan: 'Plus', parts: [{ label: 'h', pct: 62 }, { label: 'w', pct: 81 }] })
})

test('codex-auth rows keep number, plan and percents, never the email', () => {
  const q = parseCodexAuth(LIST)
  expect(q.map(x => x.account)).toEqual(['01', '02', '03'])
  expect(q[0]).toMatchObject({ plan: 'Pro Lite', active: false, parts: [{ label: 'w', pct: 39 }] }) // Pro: weekly only
  expect(q[1]).toMatchObject({ status: 'expired', parts: [] })
  expect(q[2]).toMatchObject({ plan: 'Free', active: true, parts: [{ label: 'm', pct: 100 }] }) // Free: monthly only
  expect(JSON.stringify(q)).not.toContain('@')
})

test('agy /usage cache keeps both windows per bucket', () => {
  const q = parseAgyQuota(JSON.stringify({
    account: 'a1',
    rows: [
      { group: 'Gemini Models', limit: 'Weekly Limit Remaining', remaining: 99 },
      { group: 'Gemini Models', limit: 'Five Hour Limit Remaining', remaining: 42 },
      { group: 'Claude and GPT models', limit: 'Weekly Limit Remaining', remaining: 100 },
      { group: 'Gemini 4 Argon', limit: 'Gemini 4 Argon Weekly Limit', remaining: 98 },
    ],
  }))
  expect(q).toMatchObject({ cli: 'agy', account: 'a1', parts: [{ label: 'Gh', pct: 42 }, { label: 'Gw', pct: 99 }, { label: 'Cw', pct: 100 }, { label: 'Aw', pct: 98 }] })
  expect(quotaGroups([q!])[0]!.text).toBe('Gh▄Gw█Cw█Aw█')
  expect(parseAgyQuota('not json')).toBeUndefined()
})

test('every job reads cli-agnostic: short model family + effort', () => {
  expect(jobLabel('agy', 'gemini-3.8-flash-high', '')).toEqual({ model: 'flash', effort: 'high' })
  expect(jobLabel('agy', 'claude-opus-5-5-medium', '')).toEqual({ model: 'opus', effort: 'medium' })
  expect(jobLabel('codex', 'gpt-6-luna', 'xhigh')).toEqual({ model: 'luna', effort: 'xhigh' })
  expect(jobLabel('claude', 'claude-sonnet-5-5', '')).toEqual({ model: 'sonnet', effort: '' })
  expect(jobLabel('claude', 'sonnet', 'high')).toEqual({ model: 'sonnet', effort: 'high' })
})

test('consecutive accounts with the same numbers fold into one group', () => {
  const g = quotaGroups(parseCodexAuth(LIST + '  04 dan@example.com    Free      -                  0                  100% (12:58 on 18 Nov)  -                      Now\n'))
  expect(g.map(x => [x.accounts.join(' '), x.text])).toEqual([['01', 'w▄'], ['02', '!'], ['03* 04', 'm█']])
})

test('quota bars distinguish empty, low, full and unknown values without relying on color', () => {
  const groups = quotaGroups([0, 1, 100, NaN, -1, 101].map((pct, i) => ({ cli: 'codex', account: String(i), active: false, plan: 'Pro', parts: [{ label: 'w', pct }] })))
  expect(groups.map(group => group.text)).toEqual(['w·', 'w▁', 'w█', 'w?'])
  expect(groups.at(-1)!.accounts).toEqual(['3', '4', '5'])
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
