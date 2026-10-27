import type { WakeChip, WakeQuota } from '../types'
import { modelTier } from './sources/accounts'
import { span } from './util'

const clean = (s: string) => s.replace(/[\x00-\x1f\x7f-\x9f]/g, ' ').replace(/\s+/g, ' ').trim()
const segments = new Intl.Segmenter(undefined, { granularity: 'grapheme' })
/** Terminal cells for graphemes: combining marks are zero-width; emoji and East Asian wide characters take two. */
export function cells(s: string): number {
  let n = 0
  for (const { segment } of segments.segment(s)) {
    if (/^[\p{Mark}\u200b-\u200f\u2060\ufe00-\ufe0f]+$/u.test(segment)) continue
    const cp = segment.codePointAt(0)!
    n += /\p{Extended_Pictographic}|\p{Regional_Indicator}|\ufe0f|\u20e3/u.test(segment)
      || cp >= 0x1100 && (cp <= 0x115f || cp === 0x2329 || cp === 0x232a || cp >= 0x2e80 && cp <= 0xa4cf && cp !== 0x303f || cp >= 0xac00 && cp <= 0xd7a3 || cp >= 0xf900 && cp <= 0xfaff || cp >= 0xfe10 && cp <= 0xfe19 || cp >= 0xfe30 && cp <= 0xfe6f || cp >= 0xff00 && cp <= 0xff60 || cp >= 0xffe0 && cp <= 0xffe6 || cp >= 0x20000 && cp <= 0x3fffd) ? 2 : 1
  }
  return n
}
export function truncate(text: string, width: number): string {
  const s = clean(text)
  if (width <= 0) return ''
  if (cells(s) <= width) return s
  let out = ''
  for (const { segment } of segments.segment(s)) {
    if (cells(out + segment) > width - 1) break
    out += segment
  }
  return out + '…'
}

export const STATE_GLYPHS: Record<string, string> = {
  running: '●', waiting_for_heavy: '⌁', paused: '=', retrying: '↻', blocked_on_question: '?',
  waiting_for_root: '✓', idle: '○', retired: '○', stalled: '!', done: '✓',
}
export function stateOf(job: WakeChip): string {
  if (job.isStale) return 'stalled'
  if (job.state === 'blocked_on_question') return job.state
  if (job.awaitingRoot && (!job.running || job.waitingForRoot)) return 'done'
  return job.state ?? (job.running ? 'running' : 'idle')
}
const bar = (fraction: number) => {
  const n = Math.round(Math.max(0, Math.min(1, fraction)) * 4)
  return '▰'.repeat(n) + '▱'.repeat(4 - n)
}
function memoryFraction(job: WakeChip): number | undefined {
  const match = /^([0-9]+(?:\.[0-9]+)?)([KMGT]?)$/.exec(job.memoryCap ?? '')
  if (!match || job.memoryBytes == null) return undefined
  const cap = Number(match[1]) * 1024 ** (match[2] ? 'KMGT'.indexOf(match[2]) + 1 : 0)
  return cap > 0 ? job.memoryBytes / cap : undefined
}
const MARK: Record<string, string> = { codex: '◈', agy: '✦', claude: '◆', opencode: '○' }
const EFFORT = ['low', 'medium', 'high', 'xhigh', 'max', 'ultra']

export type CrewColumn = 'effort' | 'freshness' | 'elapsed' | 'reason' | 'memory' | 'peers'
export type CrewRow = { title: string; family: string; state: string; glyph: string; detail: string; columns: CrewColumn[] }
const pad = (s: string, width: number) => s + ' '.repeat(Math.max(0, width - cells(s)))

/** Choose one column set for the whole crew; names absorb width changes first. */
export function crewRows(jobs: WakeChip[], now: number, width: number): CrewRow[] {
  width = Math.max(0, Math.floor(width))
  const hasReason = jobs.some(job => ['stalled', 'blocked_on_question'].includes(stateOf(job)) && job.reason)
  const candidates: [CrewColumn, number][] = [
    ...(hasReason ? [['reason', width < 60 ? 8 : 16] as [CrewColumn, number]] : []),
    ['effort', 6], ['freshness', 4], ['elapsed', 5],
    ['memory', 4], ['peers', width >= 90 ? 24 : 12],
  ]
  // Family and state always fit once there are six cells. On narrower terminals, only the name can fit.
  if (width < 6) return jobs.map(job => ({ title: truncate(job.title || job.name, width), family: '', state: stateOf(job), glyph: '', detail: '', columns: [] }))
  let used = 5 // space + two-cell family/class + space + state
  const minimumTitle = Math.min(24, Math.max(6, Math.floor(width * 0.35)))
  const selected: [CrewColumn, number][] = []
  for (const candidate of candidates) {
    if (width - used - candidate[1] - 1 < minimumTitle) break
    selected.push(candidate)
    used += candidate[1] + 1
  }
  const titleWidth = Math.min(32, width - used)
  return jobs.map(job => {
    const state = stateOf(job)
    const effort = EFFORT.indexOf(job.effort.toLowerCase())
    const memory = memoryFraction(job)
    const age = job.lastEventAt === undefined ? undefined : Math.max(0, now - job.lastEventAt)
    const peers = [...(job.peers ?? [])].sort((a, b) => b.lastAt - a.lastAt)
      .map(p => `${p.outgoing ? '↗' : '↙'}${clean(p.target.split('/').at(-1) ?? '')}:${p.count}${now - p.lastAt > 900_000 ? '·' : ''}`).join(',')
    const values: Record<CrewColumn, string> = {
      effort: effort < 0 ? '?' : '•'.repeat(effort + 1) + '·'.repeat(5 - effort),
      freshness: age === undefined ? '?' : bar(1 - age / 900_000),
      elapsed: age === undefined ? '?' : span(age),
      reason: state === 'stalled' || state === 'blocked_on_question' ? job.reason ?? '' : '',
      memory: memory === undefined ? '?' : bar(memory),
      peers,
    }
    const detail = selected.map(([name, size]) => ' ' + pad(truncate(values[name], size), size)).join('')
    return {
      title: pad(truncate(job.title || job.name, titleWidth), titleWidth),
      family: `${MARK[job.backend] ?? '◇'}${modelTier(job.backend, job.model)}`,
      state, glyph: STATE_GLYPHS[state] ?? '?', detail, columns: selected.map(([name]) => name),
    }
  })
}

export function quotaText(quota: WakeQuota): string {
  return `${quota.cli === 'agy' ? '✦' : '◈'}${quota.account}${quota.active ? '*' : ''}${quota.freshness && quota.freshness !== 'fresh' ? '~' : ''} ${quota.status ?? (quota.parts.length ? quota.parts.map(p => `${p.label}${bar(p.pct / 100)}`).join(' ') : '?')}`
}

/** Keep each account together where possible, wrapping at the available terminal width. */
export function quotaLines(quotas: WakeQuota[], width: number): string[] {
  const lines: string[] = []
  for (const quota of quotas) {
    const part = truncate(quotaText(quota), width)
    const last = lines.at(-1)
    if (last && cells(last) + 2 + cells(part) <= width) lines[lines.length - 1] = last + '  ' + part
    else if (part) lines.push(part)
  }
  return lines
}
