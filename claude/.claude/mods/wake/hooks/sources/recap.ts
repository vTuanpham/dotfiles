import type { EngineInterface } from 'claude-code'

export type Digest = {
  awaySince: number
  prompt?: string
  answers: string[]
  files: { path: string; added: number; removed: number }[]
  failures: { command: string; code?: number }[]
  tests: { command: string; ok: boolean }[]
  agents: { name: string; model?: string; ok: boolean; summary?: string }[]
  codex: { name: string; model: string; summary?: string; urgent?: string }[]
  needs: string[]
}
export type RecapMark = 'done' | 'decision' | 'needs' | 'agent' | 'fail'
export type RecapLine = { mark: RecapMark; text: string; evidence?: string }
export type Call = { id: string; text: string; answer?: string }

const LINE_MAX = 70
const CALL_MAX = 60

const clamp = (text: string, max: number) => {
  const flat = text.replace(/\s+/g, ' ').trim()
  return flat.length <= max ? flat : `${flat.slice(0, max - 1).trimEnd()}…`
}

export async function writeRecap(_$: EngineInterface, digest: Digest): Promise<{ lines: RecapLine[]; source: 'model' | 'digest' }> {
  return { lines: digestLines(digest), source: 'digest' }
}

// ---------------------------------------------------------------- deterministic fallback

function firstSentence(answer: string): string {
  const text = answer
    .split('\n')
    .map(l => l.replace(/^[\s#>*\-`|]+/, '').replace(/[*`_]/g, '').trim())
    .find(l => l.length > 0)
  if (!text) return ''
  const end = /[.!?](\s|$)/.exec(text)
  return clamp(end ? text.slice(0, end.index + 1) : text, LINE_MAX)
}

/** The longest directory prefix all paths share ('' when none). */
function commonDir(paths: string[]): string {
  const dirs = paths.map(p => p.split('/').slice(0, -1))
  let shared = dirs[0] ?? []
  for (const d of dirs) {
    let i = 0
    while (i < shared.length && i < d.length && shared[i] === d[i]) i++
    shared = shared.slice(0, i)
  }
  return shared.join('/')
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

export function digestLines(digest: Digest): RecapLine[] {
  const out: RecapLine[] = []
  for (const need of digest.needs.slice(0, 2)) out.push({ mark: 'needs', text: clamp(need, LINE_MAX) })
  for (const c of digest.codex.filter(c => c.urgent).slice(0, 1)) {
    out.push({ mark: 'needs', text: clamp(`Codex ${c.name}: ${c.urgent}`, LINE_MAX), evidence: c.name })
  }
  const tests = digest.tests
  const failed = digest.failures
  if (failed.length) {
    out.push({ mark: 'fail', text: clamp(`${plural(failed.length, 'command failure')} observed: ${failed[failed.length - 1]!.command}`, LINE_MAX), evidence: clamp(failed[failed.length - 1]!.command, 120) })
  }
  if (tests.length) {
    const bad = tests.filter(t => !t.ok).length
    const good = tests.length - bad
    const text = bad ? `test runs observed: ${bad} failed${good ? `, ${good} passed` : ''}` : `test runs observed: ${good} passed`
    out.push({ mark: bad ? 'fail' : 'done', text, evidence: clamp(tests.find(t => !t.ok)?.command ?? tests[tests.length - 1]!.command, 120) })
  }
  if (digest.files.length) {
    const paths = digest.files.map(f => f.path)
    const dir = commonDir(paths)
    const added = digest.files.reduce((n, f) => n + f.added, 0)
    const removed = digest.files.reduce((n, f) => n + f.removed, 0)
    const where = digest.files.length === 1 ? paths[0]! : dir ? `${plural(digest.files.length, 'file')} in ${dir}` : plural(digest.files.length, 'file')
    out.push({ mark: 'done', text: clamp(`edited ${where} (+${added} -${removed})`, LINE_MAX), evidence: paths[0] })
  }
  if (digest.agents.length) {
    const bad = digest.agents.filter(a => !a.ok).length
    out.push({ mark: bad ? 'fail' : 'agent', text: clamp(`${plural(digest.agents.length, 'agent')} finished${bad ? `, ${bad} failed` : ''}`, LINE_MAX), evidence: digest.agents[0]!.name })
  }
  const codex = digest.codex.filter(c => !c.urgent)
  if (codex.length) {
    out.push({ mark: 'agent', text: clamp(`Bridge jobs finished: ${codex.map(c => c.name).join(', ')}`, LINE_MAX), evidence: codex[0]!.name })
  }
  const said = firstSentence(digest.answers[digest.answers.length - 1] ?? '')
  // shortcut: only explicit status words are recognized; use structured outcomes when available.
  const mark = /^(?:blocked|failed|unable|cannot|could not|not fixed)\b/i.test(said) ? 'fail'
    : /^(?:needs?|waiting|requires?)\b/i.test(said) ? 'needs' : undefined
  if (said && mark === 'needs') out.unshift({ mark, text: said })
  if (said && mark === 'fail') {
    const firstNonNeed = out.findIndex(l => l.mark !== 'needs')
    out.splice(firstNonNeed < 0 ? out.length : firstNonNeed, 0, { mark, text: said })
  }
  return out.slice(0, 6)
}

// ---------------------------------------------------------------- judgment calls

const normalize = (text: string) => text.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()

/** FNV-1a over the normalized text, base 36: short and stable across runs. */
function hash(text: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < text.length; i++) {
    h = Math.imul(h ^ text.charCodeAt(i), 0x01000193) >>> 0
  }
  return h.toString(36)
}

export async function extractCalls(_$: EngineInterface, answer: string, known: Call[]): Promise<Call[]> {
  const seen = new Set(known.map(k => k.id))
  const calls: Call[] = []
  // Subjectless choices are ambiguous in context. Only accept one as the whole
  // answer; elsewhere require an unquoted first-person assertion. Attribution
  // remains heuristic because the answer alone cannot establish the prompt.
  const sentences = answer.replace(/```[\s\S]*?```/g, '').split(/(?<=[.!?])\s+|\n+/).filter(sentence => sentence.trim())
  const userChoice = /\b(?:you|your|user|customer|client|owner|person|as requested|per request)\b/i
  const attributionWords = (s: string) => normalize(s).split(' ').filter(word => word.length > 2 && !/^(?:you|your|user|customer|client|owner|person|asked|requested|specified|chose|selected|decided|wanted|said|choice|preference|decision|selection|the|and|for|with|per|request|instruction|direction)$/.test(word))
  for (const [index, sentence] of sentences.entries()) {
    const selfChoice = /^\s*(?:[-*]\s+)?(?:for\s+[^,\n]{1,40},\s*)?(?:I|we)\s+(?:chose|picked|selected|went with|opted for|decided on|assumed|skipped|deferred)\s+\S/i.test(sentence)
    const shortChoice = sentences.length === 1 && /^\s*(?:[-*]\s+)?(?:chose|picked|selected|went with|opted for|decided on|assumed|skipped|deferred)\s+(?!by\b)\S/i.test(sentence)
    if (!selfChoice && !shortChoice) continue
    if (userChoice.test(sentence)) continue
    const previous = sentences[index - 1] ?? ''
    if (userChoice.test(previous) && (!selfChoice || attributionWords(sentence).some(word => attributionWords(previous).includes(word)))) continue
    const text = clamp(sentence, CALL_MAX)
    const key = normalize(sentence)
    const id = hash(key)
    if (!key || seen.has(id)) continue
    // Old calls used the truncated display text as their ID. Recover the full
    // sentence only when the saved answer identifies exactly one matching line.
    const legacyMatch = known.some(call => {
      if (!call.answer || !call.text.endsWith('…') || call.id !== hash(normalize(call.text)) || normalize(call.text) !== normalize(text)) return false
      const matches = call.answer.split(/(?<=[.!?])\s+|\n+/).filter(item => normalize(clamp(item, CALL_MAX)) === normalize(call.text))
      return matches.length === 1 && normalize(matches[0]!) === key
    })
    if (legacyMatch) continue
    seen.add(id)
    calls.push({ id, text })
    if (calls.length === 3) break
  }
  return calls
}
