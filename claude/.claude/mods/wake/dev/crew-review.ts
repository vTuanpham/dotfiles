// Synthetic before/after crew sheets at narrow, medium and wide widths.
// The before lines reproduce the previous slot and timing calculation; after uses the live row formatter.
import { crewRows, quotaLines, truncate } from '../hooks/crew-row'
import { crewTiming, fitSlots } from '../hooks/util'
import { jobLabel } from '../hooks/sources/accounts'
import type { WakeChip, WakeQuota } from '../types'

const now = 1_000_000
const cases: [string, string, string, string, Partial<WakeChip>][] = [
  ['Quick scan', 'codex', 'gpt-6-luna', 'running', {}],
  ['Review messages', 'codex', 'gpt-6.1-terra', 'waiting_for_heavy', {}],
  ['Pairwise research', 'codex', 'gpt-6-sol', 'paused', {}],
  ['Unified status', 'codex', 'gpt-6-astra', 'retrying', {}],
  ['Provider answers', 'agy', 'gemini-flash', 'blocked_on_question', { reason: 'Which account?' }],
  ['Long silent command', 'claude', 'fable', 'running', { isStale: true, reason: 'no progress for 16m' }],
  ['Completed review', 'opencode', 'claude-opus', 'waiting_for_root', { awaitingRoot: true, waitingForRoot: true }],
  ['Check response', 'agy', 'sonnet', 'running', {}],
]
const jobs: WakeChip[] = cases.map(([title, backend, model, state, extra], i) => ({
  name: `job${i}`, title, backend, account: '01', model, state, effort: ['low', 'medium', 'high', 'xhigh'][i % 4]!,
  running: true, isStale: false, since: 0, startedAt: 40_000, lastEventAt: now - (i + 1) * 8_000,
  memoryBytes: (i + 1) * 100 * 1024 ** 2, memoryCap: '1G',
  peers: i === 0 ? [{ target: 'demo/job1', outgoing: true, count: 3, lastAt: now - 10_000 }] : [], ...extra,
}))
const quotas: WakeQuota[] = [
  { cli: 'codex', account: '01', active: true, plan: '', freshness: 'unknown', parts: [{ label: 'h', pct: 70 }, { label: 'w', pct: 30 }] },
  { cli: 'agy', account: 'a1', active: false, plan: '', freshness: 'fresh', parts: [{ label: 'Gw', pct: 100 }, { label: 'Cw', pct: 25 }] },
]

// This is the former renderer's shared-slot sizing and metadata selection.
function before(group: WakeChip[], width: number): string {
  const labels = group.map(j => { const v = jobLabel(j.backend, j.model, j.effort); return `${j.backend}·${j.account} ${v.model} ${v.effort}`.trim() })
  const shared = labels.length > 1 && labels.every(l => l === labels[0]) ? labels[0]! : ''
  const sharedWidth = shared && width >= group.length * 36 + shared.length + 3 ? shared.length + 3 : 0
  const room = width - (group.length - 1) * 3 - sharedWidth
  const details = (job: WakeChip, index: number, columns: number) => {
    const timing = crewTiming(job, now, columns)
    const label = shared ? '' : labels[index]!
    const metadata = label && columns >= (job.title || job.name).length + timing.length + label.length + 4 ? label : ''
    return { timing, metadata, length: 2 + (job.title || job.name).length + 1 + timing.length + (metadata ? metadata.length + 1 : 0) }
  }
  const full = group.map((j, i) => details(j, i, Infinity))
  const first = fitSlots(full.map(x => x.length), room)
  const shown = group.map((j, i) => first[i]! >= full[i]!.length ? full[i]! : details(j, i, first[i]!))
  const slots = fitSlots(shown.map(x => x.length), room)
  return group.map((j, i) => {
    const mark = j.isStale ? '!' : j.waitingForRoot ? '✓' : ({ codex: '⣾', agy: '✦', claude: '◆', opencode: '○' } as Record<string, string>)[j.backend]!
    const suffix = ` ${shown[i]!.timing}${shown[i]!.metadata ? ` ${shown[i]!.metadata}` : ''}`
    return `${mark} ${truncate(j.title || j.name, Math.max(1, slots[i]! - 2 - suffix.length))}${suffix}`
  }).join(' │ ') + (sharedWidth ? ` │ ${shared}` : '')
}

const panels = [40, 72, 110].map(width => ({
  width,
  before: [before(jobs.slice(0, 3), width), before(jobs.slice(3, 6), width), before(jobs.slice(6), width), 'codex 01* h70 w30 │ agy a1 Gw100 Cw25'],
  after: [...crewRows(jobs, now, width).map((row, i) => [
    [row.title, '#cdd6f4'],
    [` ${row.family}`, ({ codex: '#94e2d5', agy: '#89b4fa', claude: '#f5c2e7', opencode: '#a6e3a1' } as Record<string, string>)[jobs[i]!.backend]!],
    [` ${row.glyph}`, row.state === 'stalled' ? '#f38ba8' : row.state === 'blocked_on_question' ? '#fab387' : row.state === 'paused' || row.state === 'waiting_for_heavy' ? '#f9e2af' : row.state === 'retrying' ? '#cba6f7' : '#a6e3a1'],
    [row.detail, '#a6adc8'],
  ]), ...quotaLines(quotas, width)],
}))
for (const mode of ['before', 'after'] as const) {
  const out = `${import.meta.dir}/wake-${mode}.png`
  await Bun.write(out + '.json', JSON.stringify({ mode, panels }))
  const result = Bun.spawnSync(['uv', 'run', '-q', '--with', 'pillow', 'python', import.meta.dir + '/crew-review.py', out + '.json', out])
  if (result.exitCode !== 0) throw new Error(result.stderr.toString())
  console.log(out)
}
