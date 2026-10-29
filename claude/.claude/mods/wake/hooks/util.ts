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

/** Widths for side-by-side slots: each gets what it needs, capped at an even share of what is left. */
export function fitSlots(natural: number[], columns: number): number[] {
  const out = natural.map(() => 1)
  let left = Math.max(natural.length, columns)
  const order = natural.map((_, i) => i).sort((a, b) => natural[a]! - natural[b]!)
  order.forEach((i, rank) => {
    out[i] = Math.max(1, Math.min(natural[i]!, Math.floor(left / (order.length - rank))))
    left -= out[i]!
  })
  return out
}

/** Separate the turn clock from event freshness, including chips saved before these fields existed. */
export function crewTiming(job: WakeChip, now: number, columns = Infinity): string {
  if (!job.running || job.waitingForRoot) return 'done'
  if (!job.lastEventAt) return 'starting'
  const quiet = now - job.lastEventAt
  if (job.isStale) return columns < 24 ? 'stalled' : `stalled ${span(quiet)}`
  const turn = job.startedAt ? now - job.startedAt : 0
  // the turn clock says something the silence does not once the turn ran a minute before it went quiet
  return span(quiet) + (columns >= 60 && turn - quiet >= 60_000 ? ` · turn ${span(turn)}` : '')
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

type TestCommand = { words: string[]; next: 'end' | 'and' | 'or' | 'pipe' | 'sequence' }

function testCommands(source: string): TestCommand[] {
  // Unknown shell structures can change whether a runner executes or what its status means.
  if (/<<<?|<\(|>\(|\$\(|`/.test(source) || /\b(case|function)\b/.test(source)) return []
  const commands: TestCommand[] = []
  let words: string[] = []
  let word = ''
  let quote = ''
  let escaped = false
  let comment = false
  let hasConditionalOr = false
  let hasNegation = false
  let hasGroup = false
  const endWord = () => {
    if (word) words.push(word)
    word = ''
  }
  const endCommand = (next: TestCommand['next'] = 'sequence') => {
    endWord()
    if (words.length) commands.push({ words, next })
    words = []
  }

  for (let i = 0; i < source.length; i++) {
    const char = source[i]!
    const following = source[i + 1]
    if (comment) {
      if (char === '\n') { comment = false; endCommand('sequence') }
      continue
    }
    if (escaped) { word += char; escaped = false; continue }
    if (quote) {
      if (char === '\\' && quote === '"') { escaped = true; continue }
      if (char === quote) quote = ''
      else word += char
      continue
    }
    if (char === '\\') { escaped = true; continue }
    if (char === "'" || char === '"') { quote = char; continue }
    if (char === '#' && word === '') { comment = true; continue }
    if (char === '!' && word === '' && (following === undefined || /[\s(;|&)]/.test(following))) hasNegation = true
    if (char === '(' || char === ')' || char === '{' || char === '}') {
      hasGroup = true
      endCommand(char === ')' || char === '}' ? 'end' : 'sequence')
      continue
    }
    if (char === ';') {
      endCommand('sequence')
      while (source[i + 1] === ';') i++
      continue
    }
    if (char === '&') {
      const and = following === '&'
      endCommand(and ? 'and' : 'sequence')
      if (and) i++
      continue
    }
    if (char === '|') {
      if (following === '|') {
        hasConditionalOr = true
        endCommand('or')
        i++
      } else endCommand('pipe')
      continue
    }
    if (char === '\n') { endCommand('sequence'); continue }
    if (/\s/.test(char)) {
      if (['then', 'do', 'else', 'elif'].includes(word)) {
        word = ''
        endCommand('sequence')
      } else endWord()
      continue
    }
    word += char
  }
  endCommand('end')
  return hasConditionalOr || hasNegation || hasGroup ? [] : commands
}

const assignment = (value: string) => /^[A-Za-z_][A-Za-z0-9_]*=/.test(value)
const executableName = (value: string) => value.split('/').at(-1) ?? value
const testRunners = new Set(['pytest', 'vitest', 'jest', 'mocha', 'unittest'])
const informationFlags: Record<string, Set<string>> = {
  pytest: new Set(['--help', '-h', '--version', '-V', '--collect-only', '--collectonly', '--co', '--fixtures', '--fixtures-per-test', '--markers', '--trace-config', '--setup-plan', '--setup-only']),
  vitest: new Set(['--help', '-h', '--version']),
  jest: new Set(['--help', '-h', '--version', '--listTests', '--showConfig']),
  mocha: new Set(['--help', '-h', '--version', '--dry-run']),
  unittest: new Set(['--help', '-h']),
}

function runnerExecutesTests(runner: string, args: string[]): boolean {
  if (runner === 'vitest' && args[0] === 'list') return false
  return !args.some(argument => {
    const flag = argument.split('=', 1)[0]!
    return informationFlags[runner]?.has(argument) || informationFlags[runner]?.has(flag)
  })
}

function cargoExecutesTests(args: string[]): boolean {
  if (args.some(argument => ['--help', '-h'].includes(argument))) return false
  const separator = args.indexOf('--')
  return separator < 0 || !args.slice(separator + 1).includes('--list')
}

function goExecutesTests(args: string[]): boolean {
  return !args.some(argument => ['-h', '-help', '--help'].includes(argument)
    || argument === '-list' || argument.startsWith('-list='))
}

function packageScriptExecutesTests(args: string[]): boolean {
  return !args.some(argument => ['--help', '-h'].includes(argument))
}

function argvRunsTests(argv: string[], depth = 0): boolean {
  if (depth > 5 || argv.length === 0) return false
  let index = 0
  while (assignment(argv[index] ?? '')) index++
  if (argv[index] === '!') return false
  const executable = executableName(argv[index] ?? '')
  if (testRunners.has(executable)) return runnerExecutesTests(executable, argv.slice(index + 1))
  if (/^python(?:3(?:\.\d+)?)?$/.test(executable) || executable === 'py') {
    if (argv[index + 1] !== '-m' || !['pytest', 'unittest'].includes(argv[index + 2] ?? '')) return false
    return runnerExecutesTests(argv[index + 2]!, argv.slice(index + 3))
  }
  if (executable === 'go' && argv[index + 1] === 'test') return goExecutesTests(argv.slice(index + 2))
  if (executable === 'cargo' && argv[index + 1] === 'test') return cargoExecutesTests(argv.slice(index + 2))
  if (['npm', 'pnpm', 'yarn', 'bun'].includes(executable)) {
    const scriptIndex = argv[index + 1] === 'run' ? index + 2 : index + 1
    if (argv[scriptIndex] !== 'test') return false
    return packageScriptExecutesTests(argv.slice(scriptIndex + 1))
  }
  if (executable === 'rtk') {
    const subcommand = argv[index + 1]
    const skip = subcommand === 'proxy' ? 2 : subcommand === 'test' ? 2 : 1
    return argvRunsTests(argv.slice(index + skip), depth + 1)
  }
  if (executable === 'env') {
    index++
    while (index < argv.length) {
      const item = argv[index] ?? ''
      if (assignment(item)) { index++; continue }
      if (['-u', '--unset', '-C', '--chdir'].includes(item)) { index += 2; continue }
      if (/^(--unset|--chdir)=/.test(item) || item.startsWith('-')) { index++; continue }
      break
    }
    return argvRunsTests(argv.slice(index), depth + 1)
  }
  if (executable === 'timeout') {
    index++
    while (index < argv.length && (argv[index] ?? '').startsWith('-')) {
      if (['-k', '--kill-after', '-s', '--signal'].includes(argv[index] ?? '')) index++
      index++
    }
    if (argv[index] && !/^\d/.test(argv[index]!)) return false
    return argvRunsTests(argv.slice(index + 1), depth + 1)
  }
  if (['time', 'nice', 'command', 'sudo'].includes(executable)) {
    index++
    while ((argv[index] ?? '').startsWith('-')) index++
    return argvRunsTests(argv.slice(index), depth + 1)
  }
  if (executable === 'uv' && argv[index + 1] === 'run') {
    index += 2
    const takesValue = new Set(['--project', '--directory', '--with', '--with-requirements', '--env-file', '--python'])
    while (index < argv.length && (argv[index] ?? '').startsWith('-')) {
      if (takesValue.has(argv[index] ?? '')) index++
      index++
    }
    return argvRunsTests(argv.slice(index), depth + 1)
  }
  return false
}

/** Test runners are recognized only in executable position, never in prose or search arguments. */
export function isTestCommand(source: string): boolean {
  const commands = testCommands(source)
  if (!commands.length) return false
  const runners = commands.flatMap((command, index) => argvRunsTests(command.words) ? [index] : [])
  if (runners.length !== 1) return false
  const index = runners[0]!
  if (index !== commands.length - 1 || commands.at(-1)?.next !== 'end') return false
  let chainStart = 0
  for (let i = 0; i < index; i++) if (commands[i]?.next === 'sequence') chainStart = i + 1
  return !commands.slice(chainStart, index).some(command => command.next === 'or')
}

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
