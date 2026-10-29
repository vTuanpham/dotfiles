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
/** Model class as a circle that fills with size (quarter to full), so a bigger model reads as more. */
export const CLASS_GLYPH = ['◔', '◑', '◕', '◉'] as const
/** Reasoning effort as a five-step signal meter: lit steps rise, unlit steps are dots; full means max or ultra. */
const METER = ['▁', '▃', '▄', '▆', '█']
const EFFORT_STEPS: Record<string, number> = { low: 1, medium: 2, high: 3, xhigh: 4, max: 5, ultra: 5 }
export const effortMeter = (effort: string): string | undefined => {
  const lit = EFFORT_STEPS[effort.toLowerCase()]
  return lit === undefined ? undefined : METER.map((step, i) => (i < lit ? step : '·')).join('')
}

export type CrewColumn = 'effort' | 'elapsed' | 'reason' | 'memory' | 'peers'
const RECENT_PEER_MS = 900_000 // a conversation older than the stall window is history, not a link
const ROOT_GUTTER_WIDTH = cells('↗r ')
export type CrewRow = { title: string; family: string; state: string; glyph: string; detail: string; columns: CrewColumn[]; gutter: { text: string; color: number; dim: boolean; strength: number; description: string[] }[] }
const pad = (s: string, width: number) => s + ' '.repeat(Math.max(0, width - cells(s)))

type Link = { source: number; target: number; count: number; at: number; wait: boolean; preview?: string | null; kind?: string; observedAt?: number }

/** Separate lanes keep simultaneous edges legible; connected lanes share a colour. */
function peerLanes(jobs: WakeChip[], now: number, width: number, reservedGutter = 0): { link: Link; color: number }[] {
  const indices = new Map(jobs.flatMap((job, i) => job.id ? [[job.id, i] as const] : []))
  const links: Link[] = []
  jobs.forEach((job, source) => {
    for (const peer of job.peers ?? []) {
      const target = indices.get(peer.target)
      if (!peer.outgoing || target === undefined || target === source || now < peer.lastAt || now - peer.lastAt > RECENT_PEER_MS) continue
      links.push({ source, target, count: peer.count, at: peer.lastAt, wait: false, preview: peer.preview, kind: peer.kind, observedAt: peer.observedAt })
    }
  })
  const groups: Link[][] = []
  for (const link of links) {
    const touching = groups.filter(group => group.some(edge => [edge.source, edge.target].some(i => i === link.source || i === link.target)))
    const group = [link, ...touching.flat()]
    for (const old of touching) groups.splice(groups.indexOf(old), 1)
    groups.push(group)
  }
  groups.sort((a, b) => Math.min(...a.flatMap(e => [e.source, e.target])) - Math.min(...b.flatMap(e => [e.source, e.target])))
  const minimumTitle = Math.min(24, Math.max(6, Math.floor(width * 0.35)))
  let reserved = 6
  const sizes = [...(jobs.some(job => ['stalled', 'blocked_on_question'].includes(stateOf(job)) && job.reason) ? [width < 60 ? 8 : 16] : []), 5, 5, 5]
  for (const size of sizes) {
    if (width - reserved - size - 1 < minimumTitle) break
    reserved += size + 1
  }
  const capacity = width < 60 ? 0 : Math.max(0, Math.floor((width - reserved - minimumTitle - reservedGutter) / 3))
  const lanes: { link: Link; color: number }[] = []
  for (const [color, group] of groups.entries()) {
    group.sort((a, b) => a.source - b.source || a.target - b.target || Number(a.wait) - Number(b.wait))
    if (lanes.length + group.length <= capacity) lanes.push(...group.map(link => ({ link, color })))
  }
  return lanes
}

export function crewPage(total: number, room: number, requested: number): { page: number; pages: number; start: number; end: number } | null {
  if (total <= room || room < 2) return null
  const pageSize = room - 1
  const pages = Math.ceil(total / pageSize)
  const page = Math.max(0, Math.min(Math.floor(requested), pages - 1))
  return { page, pages, start: page * pageSize, end: Math.min(total, (page + 1) * pageSize) }
}

/** Choose one column set for the whole crew; names absorb width changes first. */
export function crewRows(jobs: WakeChip[], now: number, width: number): CrewRow[] {
  width = Math.max(0, Math.floor(width))
  const availableRootDirections = [true, false].filter(outgoing => jobs.some(job =>
    (job.peers ?? []).some(peer => peer.target === 'root' && peer.outgoing === outgoing
      && now >= peer.lastAt && now - peer.lastAt <= RECENT_PEER_MS)))
  // Keep the directed root endpoint only when the fixed worker mark plus at
  // least one title cell can fit beside its three-cell gutter lane.
  const rootDirections = width >= 7 + availableRootDirections.length * ROOT_GUTTER_WIDTH
    ? availableRootDirections
    : []
  const lanes = peerLanes(jobs, now, width, rootDirections.length * ROOT_GUTTER_WIDTH)
  const gutterWidth = lanes.length * 3 + rootDirections.length * ROOT_GUTTER_WIDTH
  const shown = new Set(lanes.filter(lane => !lane.link.wait).map(({ link }) => `${link.source}:${link.target}`))
  const hasHiddenPeers = jobs.some((job, index) => (job.peers ?? []).some(p => {
    if (p.target === 'root') return false // Root has its own directed gutter, not a worker-name column.
    const other = jobs.findIndex(j => j.id === p.target)
    return now >= p.lastAt && now - p.lastAt <= RECENT_PEER_MS && !shown.has(p.outgoing ? `${index}:${other}` : `${other}:${index}`)
  }))
  const hasReason = jobs.some(job => ['stalled', 'blocked_on_question'].includes(stateOf(job)) && job.reason)
  const candidates: [CrewColumn, number][] = [
    ...(hasReason ? [['reason', width < 60 ? 8 : 16] as [CrewColumn, number]] : []),
    ['effort', 5], ['elapsed', 5],
    ['memory', 5],
  ]
  // A two-cell harness image, class and state fit once there are seven cells.
  if (width < 7) return jobs.map(job => ({ title: truncate(job.title || job.name, width), family: '', state: stateOf(job), glyph: '', detail: '', columns: [], gutter: [] }))
  let used = 6 // space + two-cell harness image + class circle + space + state
  const minimumTitle = Math.min(24, Math.max(6, Math.floor(width * 0.35)))
  const selected: [CrewColumn, number][] = []
  // A directed peer mark remains legible at narrow widths before optional metrics.
  const peerWidth = Math.min(width >= 90 ? 24 : 12, width - gutterWidth - used - minimumTitle - 1)
  if (hasHiddenPeers && peerWidth >= 3) {
    selected.push(['peers', peerWidth])
    used += peerWidth + 1
  }
  for (const candidate of candidates) {
    if (width - gutterWidth - used - candidate[1] - 1 < minimumTitle) break
    selected.push(candidate)
    used += candidate[1] + 1
  }
  // Names take what they need (up to 56 cells) so a wide terminal never truncates a title beside empty space.
  const wanted = Math.max(...jobs.map(job => cells(clean(job.title || job.name))), 1)
  const titleWidth = Math.min(wanted, 56, width - gutterWidth - used)
  return jobs.map((job, index) => {
    const state = stateOf(job)
    const effort = effortMeter(job.effort)
    const memory = memoryFraction(job)
    const age = job.lastEventAt === undefined ? undefined : Math.max(0, now - job.lastEventAt)
    const peerMarks = [...(job.peers ?? [])].filter(p => {
      if (p.target === 'root') return false
      const other = jobs.findIndex(j => j.id === p.target)
      return now >= p.lastAt && now - p.lastAt <= RECENT_PEER_MS && !shown.has(p.outgoing ? `${index}:${other}` : `${other}:${index}`)
    }).sort((a, b) => b.lastAt - a.lastAt)
      .map(p => `${p.outgoing ? '↗' : '↙'}${clean(p.target.split('/').at(-1) ?? '')}${p.count > 1 ? ':' + p.count : ''}`)
    const peers = peerMarks.join(',')
    const values: Record<CrewColumn, string> = {
      effort: effort ?? '?',
      elapsed: age === undefined ? '?' : span(age),
      reason: state === 'stalled' || state === 'blocked_on_question' ? job.reason ?? '' : '',
      memory: memory === undefined ? '?' : '▣' + bar(memory),
      peers,
    }
    let detail = selected.map(([name, size]) => ' ' + pad(truncate(values[name], size), size)).join('')
    const peerGutter = lanes.map(({ link, color }) => {
      const top = Math.min(link.source, link.target), bottom = Math.max(link.source, link.target)
      let text = '   '
      if (index >= top && index <= bottom) {
        const branch = index === link.source ? (link.wait ? '┄' : link.count >= 5 ? '═' : link.count >= 2 ? '━' : '─') : index === link.target ? '←' : ' '
        const vertical = index === top ? '┐' : index === bottom ? '┘' : link.wait ? '┆' : link.count >= 5 ? '║' : link.count >= 2 ? '┃' : '│'
        text = branch + vertical + ' '
      }
      const age = Math.max(0, now - link.at)
      const pulseAge = link.observedAt === undefined || now < link.observedAt ? Infinity : now - link.observedAt
      const strength = link.wait ? 1 : pulseAge < 2_000 ? 0.65 + 0.35 * (Math.floor(pulseAge / 400) % 2) : Math.max(0.25, 1 - age / RECENT_PEER_MS * 0.75)
      const description = [
        `${jobs[link.source]!.name} → ${jobs[link.target]!.name}`,
        link.wait ? 'Waiting for peer' : link.preview ? link.preview : 'Message preview unavailable',
      ]
      return { text, color, dim: !link.wait && age > 300_000, strength, description }
    })
    const rootGutter = rootDirections.map(outgoing => {
      const message = [...(job.peers ?? [])]
        .filter(peer => peer.target === 'root' && peer.outgoing === outgoing
          && now >= peer.lastAt && now - peer.lastAt <= RECENT_PEER_MS)
        .sort((a, b) => b.lastAt - a.lastAt)[0]
      if (!message)
        return { text: '   ', color: 3, dim: true, strength: 0.25, description: [] }
      const age = Math.max(0, now - message.lastAt)
      const pulseAge = message.observedAt === undefined || now < message.observedAt
        ? Infinity
        : now - message.observedAt
      const strength = pulseAge < 2_000
        ? 0.65 + 0.35 * (Math.floor(pulseAge / 400) % 2)
        : Math.max(0.25, 1 - age / RECENT_PEER_MS * 0.75)
      return {
        text: pad(outgoing ? '↗r ' : '↙r ', ROOT_GUTTER_WIDTH),
        color: 3,
        dim: age > 300_000,
        strength,
        description: [
          outgoing ? 'Worker → root' : 'Root → worker',
          message.messageState === 'observed'
            ? 'Observed by Bridge; root read state unknown'
            : message.messageState === 'sent'
              ? 'Bridge sent; worker read state unknown'
              : 'Bridge message state unavailable',
          message.preview ?? 'Message preview unavailable',
        ],
      }
    })
    const gutter = [...peerGutter, ...rootGutter]
    return {
      title: pad(truncate(job.title || job.name, titleWidth), titleWidth),
      family: `${MARK[job.backend] ?? '◇'}${CLASS_GLYPH[modelTier(job.backend, job.model) - 1] ?? CLASS_GLYPH[1]}`,
      state, glyph: STATE_GLYPHS[state] ?? '?', detail, columns: selected.map(([name]) => name), gutter,
    }
  })
}

const mark = (quota: WakeQuota) => (quota.cli === 'agy' ? '✦' : '◈')

export function quotaText(quota: WakeQuota): string {
  // The stale-cache '~' only means something beside numbers; a dead account has none to be stale.
  const stale = !quota.status && quota.freshness && quota.freshness !== 'fresh' ? '~' : ''
  return `${mark(quota)}${quota.account}${quota.active ? '*' : ''}${stale} ${quota.status ?? (quota.parts.length ? quota.parts.map(p => `${p.label}${Math.round(p.pct)}%${bar(p.pct / 100)}`).join(' ') : '?')}`
}

/** Neighbouring accounts of one CLI in the same dead state read once: '◈03–06 ✕ expired', not four times. */
export type QuotaChunk = { text: string; quotas: WakeQuota[] }

function foldDead(quotas: WakeQuota[]): QuotaChunk[] {
  const parts: QuotaChunk[] = []
  for (let i = 0; i < quotas.length; i++) {
    const quota = quotas[i]!
    let j = i
    while (quota.status && quotas[j + 1]?.cli === quota.cli && quotas[j + 1]?.status === quota.status) j++
    if (j === i) { parts.push({ text: quotaText(quota), quotas: [quota] }); continue }
    const group = quotas.slice(i, j + 1)
    const names = group.map(q => q.account)
    parts.push({ text: `${mark(quota)}${names[0]}–${names.at(-1)} ✕ ${quota.status}`, quotas: group })
    i = j
  }
  return parts
}

/** Keep each account together where possible, wrapping at the available terminal width. */
export function quotaRows(quotas: WakeQuota[], width: number): QuotaChunk[][] {
  const lines: QuotaChunk[][] = []
  for (const chunk of foldDead(quotas)) {
    const part = { ...chunk, text: truncate(chunk.text, width - 1) }
    const last = lines.at(-1)
    if (last && cells(last.map(p => p.text).join('  ')) + last.length + 3 + cells(part.text) <= width) last.push(part)
    else if (part.text) lines.push([part])
  }
  return lines
}

export function quotaLines(quotas: WakeQuota[], width: number): string[] {
  return quotaRows(quotas, width).map(line => line.map(chunk => chunk.text).join('  '))
}
