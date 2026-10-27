import { expect, test } from 'claude-code/testing'
import { cells, crewRows, effortMeter, quotaLines, quotaText, STATE_GLYPHS, stateOf } from '../hooks/crew-row'
import type { WakeChip } from '../types'

const base: WakeChip = { name: 'worker', title: 'Inspect 長い👩‍💻 worker title', backend: 'codex', account: '01', model: 'gpt-6.1-terra', effort: 'high', running: true, isStale: false, since: 0, lastEventAt: 10_000, memoryBytes: 512 * 1024 ** 2, memoryCap: '1G' }

test('state glyphs distinguish waits, pause, retry, answer, stall and completion', () => {
  const states = ['running', 'waiting_for_heavy', 'paused', 'retrying', 'blocked_on_question']
  expect(states.map(state => STATE_GLYPHS[state])).toEqual(['●', '⌁', '=', '↻', '?'])
  expect(stateOf({ ...base, isStale: true })).toBe('stalled')
  expect(stateOf({ ...base, running: false, awaitingRoot: true })).toBe('done')
  expect(STATE_GLYPHS.stalled).toBe('!')
  expect(STATE_GLYPHS.done).toBe('✓')
})

test('every width fits terminal cells even with wide text, emoji, links and multiline reasons', () => {
  expect(cells('a長👩‍💻e\u0301')).toBe(6)
  const job = { ...base, isStale: true, reason: 'silence\n長い command', peers: [{ target: 'root/reviewer', count: 12, lastAt: 1, outgoing: true }] }
  for (let width = 0; width <= 180; width++) {
    const row = crewRows([job], 1_000_000, width)[0]!
    const line = row.title + (row.family ? ` ${row.family} ${row.glyph}` : '') + row.detail
    expect(cells(line)).toBeLessThanOrEqual(width)
    expect(line.includes('\n')).toBe(false)
  }
})

test('known memory, freshness, effort and directed weighted peers render without fabricated values', () => {
  const row = crewRows([{ ...base, peers: [{ target: 'owner/reviewer', count: 3, lastAt: 9_000, outgoing: true }, { target: 'owner/other', count: 2, lastAt: 8_000, outgoing: false }] }], 20_000, 120)[0]!
  expect(row.family + ' ' + row.glyph).toBe('◈◑ ●')
  expect(row.detail).toContain('▁▃▄··') // high effort: three of five signal steps lit
  expect(effortMeter('low')).toBe('▁····')
  expect(effortMeter('MAX')).toBe('▁▃▄▆█')
  expect(effortMeter('ultra')).toBe('▁▃▄▆█')
  expect(effortMeter('mystery')).toBeUndefined()
  expect(row.detail).toContain('▰▰▱▱')
  expect(crewRows([{ ...base, memoryBytes: 512, memoryCap: '1024' }], 20_000, 120)[0]!.detail).toContain('▰▰▱▱')
  expect(row.detail).toContain('↗reviewer:3')
  expect(row.detail).toContain('↙other:2')
  expect(crewRows([{ ...base, lastEventAt: undefined, memoryBytes: null }], 20_000, 120)[0]!.detail).toContain('?')
  expect(quotaText({ cli: 'codex', account: '01', plan: '', active: true, parts: [{ label: 'w', pct: 50 }] })).toBe('◈01* w▰▰▱▱')
  expect(quotaText({ cli: 'codex', account: '01', plan: '', active: true, freshness: 'unknown', parts: [{ label: 'w', pct: 50 }] })).toBe('◈01*~ w▰▰▱▱')
})

test('dead accounts fold into one range, and the stale mark only follows numbers', () => {
  const dead = (account: string, status: string) => ({ cli: 'codex' as const, account, plan: '', active: false, parts: [], status })
  const live = { cli: 'codex' as const, account: '01', plan: '', active: true, freshness: 'stale', parts: [{ label: 'w', pct: 50 }] }
  const lines = quotaLines([live, dead('02', 'signed out'), dead('03', 'expired'), dead('04', 'expired'), dead('05', 'expired'), dead('06', 'expired')], 200)
  expect(lines).toEqual(['◈01*~ w▰▰▱▱  ◈02 signed out  ◈03–06 ✕ expired'])
  expect(quotaText(dead('03', 'expired'))).toBe('◈03 expired')
})

test('a wide terminal never truncates a title beside empty space, and a stale peer is not a link', () => {
  const title = 'Pairwise decision-model ranking research'
  const row = crewRows([{ ...base, title, peers: [{ target: 'owner/gone', count: 1, lastAt: 1, outgoing: true }] }], 2_000_000, 190)[0]!
  expect(row.title.trim()).toBe(title)
  expect(row.detail).not.toContain('gone')
  const recent = crewRows([{ ...base, peers: [{ target: 'owner/live', count: 1, lastAt: 1_990_000, outgoing: true }] }], 2_000_000, 190)[0]!
  expect(recent.detail).toContain('↗live')
  expect(recent.detail).not.toContain('↗live:1')
})

test('mixed workers share fixed columns and shrink names first at every width', () => {
  const jobs = [base, { ...base, name: 'research', title: 'Pairwise research', model: 'gpt-6-sol' }, { ...base, name: 'status', title: 'Unified status', backend: 'agy', model: 'claude-fable' }]
  for (const width of [24, 36, 60, 90, 140]) {
    const rows = crewRows(jobs, 20_000, width)
    expect(rows.map(row => row.family)).toEqual(['◈◑', '◈◕', '✦◉'])
    expect(rows.every(row => JSON.stringify(row.columns) === JSON.stringify(rows[0]!.columns))).toBe(true)
    expect(rows.every(row => cells(row.title) === cells(rows[0]!.title))).toBe(true)
    expect(rows.every(row => cells(row.title + ' ' + row.family + ' ' + row.glyph + row.detail) <= width)).toBe(true)
  }
})
