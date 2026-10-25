import type { WakeChip } from '../types'

// Catppuccin Mocha, as in the status line.
export const COLOR = {
  mauve: '#cba6f7',
  lavender: '#b4befe',
  pink: '#f5c2e7',
  blue: '#89b4fa',
  sky: '#89dceb',
  teal: '#94e2d5',
  green: '#a6e3a1',
  yellow: '#f9e2af',
  peach: '#fab387',
  red: '#f38ba8',
  text: '#cdd6f4',
  subtext: '#a6adc8',
  subtle: '#6c7086',
  surface: '#45475a',
} as const

const channels = (hex: string) => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16))
const luminance = (hex: string) => {
  const [r, g, b] = channels(hex).map(c => (c / 255 <= 0.03928 ? c / 255 / 12.92 : ((c / 255 + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!
}
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi! + 0.05) / (lo! + 0.05)
}
const blend = (a: string, b: string, t: number) => {
  const [x, y] = [channels(a), channels(b)]
  return '#' + x.map((c, i) => Math.round(c + (y[i]! - c) * t).toString(16).padStart(2, '0')).join('')
}

/** COLOR moved, each just enough, toward black on a light background or white on a dark one, so text reads on `bg`. */
export function readable(bg: string): Record<keyof typeof COLOR, string> {
  const toward = luminance(bg) > 0.18 ? '#11111b' : '#ffffff'
  const need = (key: keyof typeof COLOR) => (key === 'text' || key === 'subtext' ? 4.5 : key === 'surface' ? 1.8 : 3)
  const out = {} as Record<keyof typeof COLOR, string>
  for (const key of Object.keys(COLOR) as (keyof typeof COLOR)[]) {
    let color: string = COLOR[key]
    for (let t = 0.1; contrast(color, bg) < need(key) && t <= 1.001; t += 0.1) color = blend(COLOR[key], toward, t)
    out[key] = color
  }
  return out
}

const pad = (n: number) => String(n).padStart(2, '0')

/** m:ss for clocks that tick. */
export function clock(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000))
  return `${Math.floor(s / 60)}:${pad(s % 60)}`
}

/** 45s, 12m, 1h04m: for spans. */
export function span(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000))
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m`
  return `${Math.floor(s / 3600)}h${pad(Math.floor((s % 3600) / 60))}m`
}

/** Separate the turn clock from event freshness, including chips saved before these fields existed. */
export function crewTiming(job: WakeChip, now: number, columns = Infinity): string {
  if (!job.running || job.waitingForRoot) return 'done'
  if (!job.lastEventAt) return 'starting'
  const quiet = now - job.lastEventAt
  if (job.isStale) return columns < 24 ? 'stalled' : `stalled ${span(quiet)}`
  const turn = job.startedAt ? now - job.startedAt : 0
  return span(quiet) + (columns >= 60 && turn >= 60_000 && turn >= quiet * 2 ? ` · turn ${span(turn)}` : '')
}

/** Lines in a block of text; "" is none, a trailing newline adds no line. */
export function lines(text: unknown): number {
  if (typeof text !== 'string' || text === '') return 0
  return text.replace(/\n$/, '').split('\n').length
}

/** +/- lines of a tool result's structuredPatch, when it has one. */
export function patchCounts(result: unknown): { added: number; removed: number } | undefined {
  const hunks = (result as { structuredPatch?: { lines?: string[] }[] } | null)?.structuredPatch
  if (!Array.isArray(hunks) || hunks.length === 0) return undefined
  const all = hunks.flatMap(hunk => hunk.lines ?? [])
  return { added: all.filter(l => l.startsWith('+')).length, removed: all.filter(l => l.startsWith('-')).length }
}

/** Project-relative when inside the root, else ~-relative or absolute. */
export function shortPath(file: string, root: string | undefined, home: string | undefined): string {
  for (const [dir, prefix] of [[root, ''], [home, '~/']] as const) {
    const base = dir?.replace(/\/$/, '')
    if (base && file.startsWith(base + '/')) return prefix + file.slice(base.length + 1)
  }
  return file
}

/** The command a person would name: env assignments, `cd … &&`, timeout and wrappers dropped. */
export function commandHead(command: string): string {
  let head = command.trim().split('\n')[0]!
  for (;;) {
    const next = head
      .replace(/^cd\s+\S+\s*&&\s*/, '')
      .replace(/^[A-Za-z_][A-Za-z0-9_]*=("[^"]*"|'[^']*'|\S*)\s+/, '')
      .replace(/^env(\s+-u\s+\S+)+\s+/, '')
      .replace(/^(timeout\s+\S+|rtk(\s+proxy)?|time|nice|command)\s+/, '')
    if (next === head) return head.length > 80 ? head.slice(0, 79) + '…' : head
    head = next
  }
}

export const isTestCommand = (command: string) =>
  /\b(pytest|vitest|jest|mocha|go test|cargo test|npm (run )?test|pnpm test|yarn test|bun test|plugin test|unittest)\b/.test(command)

/** A short stable id (FNV-1a, base 36). */
export function hash(text: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 0x01000193)
  return (h >>> 0).toString(36)
}

/** Whether an assistant message shows (the end of) the answer a turn completed with. */
export const isAnswerText = (message: string, answer: string) => {
  const a = answer.trim()
  const m = message.trim()
  return m.length > 0 && (a === m || a.endsWith(m))
}
