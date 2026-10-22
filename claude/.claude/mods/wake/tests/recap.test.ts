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

test('good JSON becomes model lines, clamped, capped and evidence-checked', async () => {
  const seen = model(
    JSON.stringify([
      { mark: 'done', text: 'Switched the ledger to per-lot locks', evidence: 'src/ledger/lots.py' },
      { mark: 'fail', text: 'x'.repeat(200), evidence: 'uv run ty check' },
      { mark: 'needs', text: 'Waiting on permission for uv sync' },
      { mark: 'bogus', text: 'bad mark', evidence: 'reviewer' },
      { mark: 'done', text: 'Edited config.toml', evidence: 'config.toml' }, // not in the digest
      ...Array.from({ length: 8 }, (_, i) => ({ mark: 'agent', text: `agent ${i}`, evidence: 'reviewer' })),
    ]),
  )
  const { lines, source } = await writeRecap(seen.$, digest)

  expect(source).toBe('model')
  expect(lines).toHaveLength(6)
  expect(lines.map(l => l.text)).not.toContain('Edited config.toml')
  expect(lines.map(l => l.text)).not.toContain('bad mark')
  expect(lines[0]).toEqual({ mark: 'done', text: 'Switched the ledger to per-lot locks', evidence: 'src/ledger/lots.py' })
  expect(lines[1]!.text.length).toBe(70)
  expect(lines[2]).toEqual({ mark: 'needs', text: 'Waiting on permission for uv sync' })
  expect(seen).toHaveLength(1)
  expect(seen[0]!.model).toBe('haiku')
  expect(seen[0]!.prompt).toContain('src/ledger/lots.py')
})

test('a fenced JSON reply is accepted', async () => {
  const seen = model('```json\n[{"mark":"done","text":"Per-lot locks","evidence":"reviewer"}]\n```')
  expect((await writeRecap(seen.$, digest)).source).toBe('model')
})

test('garbage, wrong shape, all-invalid, model error and a throw fall back to the digest', async () => {
  const expected = digestLines(digest)
  const seen = model('')
  for (const reply of ['sorry, here is a recap', '{"lines":[]}', '[]', '[{"mark":"done","text":"x","evidence":"nowhere.ts"}]', 'error', 'throw']) {
    seen.answer.reply = reply
    expect(await writeRecap(seen.$, digest)).toEqual({ lines: expected, source: 'digest' })
  }
  expect(seen).toHaveLength(6)
})

test('an empty digest asks nothing', async () => {
  const seen = model('[]')
  const empty: Digest = { awaySince: 1, answers: [], files: [], failures: [], tests: [], agents: [], codex: [], needs: [] }
  expect(await writeRecap(seen.$, empty)).toEqual({ lines: [], source: 'digest' })
  expect(seen).toHaveLength(0)
})

test('the prompt stays small and keeps the newest answers', async () => {
  const seen = model('[]')
  const big: Digest = { ...digest, answers: Array.from({ length: 30 }, (_, i) => `answer-${i} ${'w'.repeat(2400)}`) }
  await writeRecap(seen.$, big)
  const prompt = seen[0]!.prompt
  expect(prompt.length).toBeLessThan(13_000)
  expect(prompt).toContain('answer-29')
  expect(prompt).not.toContain('answer-0 ')
})

test('digestLines: needs first, then failures, tests, files, agents, last answer', () => {
  const lines = digestLines(digest)
  expect(lines.map(l => l.mark)).toEqual(['needs', 'needs', 'fail', 'done', 'done', 'done'])
  expect(lines[0]!.text).toBe('Permission to run uv sync')
  expect(lines[1]!.text).toContain('Codex luna-audit')
  expect(lines.some(l => l.text === '2 test runs passed')).toBe(true)
  expect(lines.some(l => l.text.startsWith('edited 2 files in src/ledger'))).toBe(true)
  expect(lines.at(-1)).toEqual({ mark: 'done', text: 'Switched the ledger to per-lot locks.' })
  expect(lines.length).toBeLessThanOrEqual(6)
  expect(lines.every(l => l.text.length <= 70)).toBe(true)
})

const ANSWER = `I went with per-lot locks instead of one global lock, because settlement touches lots independently. ${'Details follow. '.repeat(10)}`

test('extractCalls skips the model for short answers and answers with no decision verb', async () => {
  const seen = model('["x"]')
  expect(await extractCalls(seen.$, 'I chose a lock.', [])).toEqual([])
  expect(await extractCalls(seen.$, `All good and finished. ${'Everything is done. '.repeat(20)}`, [])).toEqual([])
  expect(seen).toHaveLength(0)
})

test('extractCalls returns stable ids, drops known and duplicate calls, clamps and caps', async () => {
  const seen = model(JSON.stringify(['per-lot locks, not a global lock', 'Per-lot locks, NOT a global lock!', 'skipped the retry path', 'y'.repeat(100), 'assumed UTC everywhere', 'fourth call', 42]))
  const known = [{ id: 'k', text: 'skipped the retry path' }]
  const calls = await extractCalls(seen.$, ANSWER, known)

  expect(calls.map(c => c.text)).toEqual(['per-lot locks, not a global lock', 'y'.repeat(59) + '…', 'assumed UTC everywhere'])
  expect(calls[0]!.id).toMatch(/^[0-9a-z]+$/)
  expect(calls[0]!.id).toBe((await extractCalls(seen.$, ANSWER, []))[0]!.id)
  expect(seen[0]!.prompt).toContain('- skipped the retry path')
  expect(seen[0]!.model).toBe('haiku')
})

test('extractCalls returns [] on garbage, error and throw', async () => {
  const seen = model('')
  for (const reply of ['nothing to report', '{"a":1}', 'error', 'throw']) {
    seen.answer.reply = reply
    expect(await extractCalls(seen.$, ANSWER, [])).toEqual([])
  }
})
