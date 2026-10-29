import { expect, test } from 'claude-code/testing'
import type { EngineInterface, ModelCompleteRequest, ModelCompleteResult } from 'claude-code'

import { digestLines, extractCalls, writeRecap, type Digest } from '../hooks/sources/recap'

const usage = { input_tokens: 1, output_tokens: 1, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 }

/**
 * The test engine's `$` has no `model` noun (it is not an engine-raised event), so the module gets a
 * stand-in holding the one method it calls, answering as `ModelCompleteResult` does and recording requests.
 */
function model(first: string | 'error' | 'throw') {
  const seen: { model: string; prompt: string; system?: string }[] = []
  const answer = { reply: first }
  const $ = {
    model: {
      complete: async (request: ModelCompleteRequest): Promise<ModelCompleteResult> => {
        seen.push({ model: request.model, prompt: String(request.prompt), system: request.system === undefined ? undefined : String(request.system) })
        if (answer.reply === 'throw') throw new Error('boom')
        if (answer.reply === 'error') return { isAnswered: false, reason: 'api-error', status: 529, error: 'overloaded', usage }

        return { isAnswered: true, text: answer.reply, usage }
      },
    },
  } as unknown as EngineInterface

  return Object.assign(seen, { answer, $ })
}

const digest: Digest = {
  awaySince: 1,
  prompt: 'fix the lot locking',
  answers: ['Switched the ledger to per-lot locks. Tests pass.'],
  files: [
    { path: 'src/ledger/lots.py', added: 20, removed: 4 },
    { path: 'src/ledger/locks.py', added: 30, removed: 0 },
  ],
  failures: [{ command: 'uv run ty check', code: 1 }],
  tests: [
    { command: 'uv run pytest tests/ledger', ok: true },
    { command: 'uv run pytest tests/risk', ok: true },
  ],
  agents: [{ name: 'reviewer', ok: true }],
  codex: [{ name: 'luna-audit', model: 'gpt-6-luna', urgent: 'needs a decision on retries' }],
  needs: ['Permission to run uv sync'],
}

test('recap uses local evidence and never asks the model', async () => {
  const seen = model('[{"mark":"done","text":"Invented success","evidence":"reviewer"}]')
  expect(await writeRecap(seen.$, digest)).toEqual({ lines: digestLines(digest), source: 'digest' })
  expect(seen).toHaveLength(0)
})

test('a same-head failure remains observed when its order against a test is unknown', () => {
  const d: Digest = { ...digest, answers: ['Blocked: tests still fail'], needs: [], codex: [], files: [], agents: [],
    failures: [{ command: 'pytest', code: 1 }],
    tests: [{ command: 'pytest', ok: false }, { command: 'pytest', ok: true }] }
  const lines = digestLines(d)
  expect(lines[0]).toEqual({ mark: 'fail', text: 'Blocked: tests still fail' })
  expect(lines.some(l => l.text === 'test runs observed: 1 failed, 1 passed')).toBe(true)
  expect(lines.some(l => l.text === '1 command failure observed: pytest')).toBe(true)
})

test('unresolved needs lead and ambiguous answers do not become completed work', () => {
  const d: Digest = { ...digest, answers: ['Waiting for approval.'], needs: [], codex: [] }
  expect(digestLines(d)[0]).toEqual({ mark: 'needs', text: 'Waiting for approval.' })
  for (const answer of ['The fix will be completed later.', 'I fixed nothing.', 'Fixed nothing; the issue remains.']) {
    expect(digestLines({ ...d, answers: [answer] }).some(l => l.text === answer)).toBe(false)
  }
})

test('digestLines: needs first, then failures, tests, files and agents', () => {
  const lines = digestLines(digest)
  expect(lines.map(l => l.mark)).toEqual(['needs', 'needs', 'fail', 'done', 'done', 'agent'])
  expect(lines[0]!.text).toBe('Permission to run uv sync')
  expect(lines[1]!.text).toContain('Codex luna-audit')
  expect(lines.some(l => l.text === 'test runs observed: 2 passed')).toBe(true)
  expect(lines.some(l => l.text.startsWith('edited 2 files in src/ledger'))).toBe(true)
  expect(lines.length).toBeLessThanOrEqual(6)
  expect(lines.every(l => l.text.length <= 70)).toBe(true)
})

test('short explicit choices are extracted locally and unsupported model claims are ignored', async () => {
  const seen = model('["invented choice"]')
  const answer = 'I chose per-lot locks instead of a global lock.'
  const calls = await extractCalls(seen.$, answer, [])
  expect(calls).toHaveLength(1)
  expect(calls[0]!.text).toBe(answer)
  expect(calls[0]!.id).toBe((await extractCalls(seen.$, answer, []))[0]!.id)
  expect(await extractCalls(seen.$, answer, calls)).toEqual([])
  expect(await extractCalls(seen.$, 'All tests passed.', [])).toEqual([])
  expect(await extractCalls(seen.$, 'I chose the option you requested.', [])).toEqual([])
  expect(seen).toHaveLength(0)
})

test('subjectless short decisions are captured only when not attributed to the user', async () => {
  const $ = model('[]').$
  for (const answer of ['Chose SQLite.', 'Selected SQLite.', 'Opted for SQLite.']) {
    expect((await extractCalls($, answer, [])).map(call => call.text)).toEqual([answer])
  }
  for (const answer of ['Selected by the user: SQLite.', 'Selected by you: SQLite.', 'Selected by the customer: SQLite.', 'You asked for SQLite. I chose SQLite.', 'I chose SQLite per your request.', 'I chose SQLite as requested.', 'Use SQLite.', "The user's choice was SQLite. Selected SQLite.", "The customer's choice was SQLite. Selected SQLite.", 'The customer chose SQLite. Selected SQLite.', 'The owner requested SQLite. Selected SQLite.', 'The user’s request was SQLite. Selected SQLite.', 'The user’s selection was SQLite. Selected SQLite.', 'The owner’s decision was SQLite. Selected SQLite.', 'A user decision was to select SQLite. Selected SQLite.', 'The new release notes say, “I chose SQLite.”', '```\nI chose SQLite.\n```']) {
    expect(await extractCalls($, answer, [])).toEqual([])
  }
  expect((await extractCalls($, 'You asked for SQLite. I chose per-lot locks.', [])).map(call => call.text)).toEqual(['I chose per-lot locks.'])
})

test('preserves legacy long calls using their full source without merging distinct choices', async () => {
  const $ = model('[]').$
  const answer = 'I chose SQLite for the synthetic test cases because the fixtures need consistent storage behavior.'
  const old = { id: '12uf0k0', text: 'I chose SQLite for the synthetic test cases because the fix…', answer }
  expect(await extractCalls($, answer, [old])).toEqual([])
  const different = 'I chose SQLite for the synthetic test cases because the fixtures need isolated transactions.'
  const next = await extractCalls($, different, [old])
  expect(next).toHaveLength(1)
  expect(next[0]!.text).toBe(old.text)
  expect(await extractCalls($, different, [...[old], ...next])).toEqual([])
  const ambiguous = { ...old, answer: `${answer}\n${different}` }
  expect(await extractCalls($, answer, [ambiguous])).toHaveLength(1)
})
