// bun dev/crew.ts [family]: sheets of the crew for one family (default opencode), saved as dev/<family>-grid.png and dev/<family>-busy.png.
//   grid  the family's four classes beside a mid-class sprite of each other family, then agy running Opus, Sonnet and Argon
//         (Claude's pink mark inside agy), over a few landscapes by day and night; seeds picked so the lineup reads left to right
//   busy  a crowded sky of mixed families, classes, a stale job and subagent birds, seeded from job names as the band does
//   opencode also saves dev/balloons.png: six balloons of mixed classes (their palette colours and one stale row) by day and night
import { type SceneInput, scenePixels } from '../hooks/scene.ts'
import { airSlots, balloonInk } from '../hooks/landscapes/crew.ts'
import { type Job, P } from '../hooks/landscapes/kit.ts'
import { hash, seedOf } from '../hooks/pixels.ts'
type Kind = NonNullable<Job['kind']>
const family = (process.argv[2] ?? 'opencode') as Kind
const W = 260
const right = W - 10 - 1 - 5 // as scene.ts: left of Mochi's laptop
const count = airSlots(right)
/** The first seed at `slot` whose balloon ink is `want` (when given), so the sheet lines up in order with a chosen colour. */
const at = (slot: number, kind: Kind, tier: 1 | 2 | 3 | 4, maker?: 'claude', want?: number): Job => {
  let seed = slot * 1000
  while (hash(seed) % count !== slot || (want !== undefined && balloonInk(seed) !== want)) seed++
  return { kind, tier, seed, isStale: false, maker }
}
const others = (['codex', 'agy', 'claude', 'opencode'] as const).filter(k => k !== family)
const grid = [at(0, family, 1), at(1, family, 2), at(2, family, 3), at(3, family, 4), ...others.map((k, i) => at(4 + i, k, 2)), at(7, 'agy', 3, 'claude'), at(8, 'agy', 2, 'claude'), at(9, 'agy', 3)]
const named = (name: string, kind: Kind, tier: 1 | 2 | 3 | 4, isStale = false, maker?: 'claude'): Job => ({ kind, tier, seed: seedOf(name), isStale, maker })
const busy = [
  named('wake-opencode', 'opencode', 3), named('fix-tests', 'codex', 3), named('docs-pass', 'agy', 2), named('free-review', 'opencode', 1),
  named('triage', 'claude', 1), named('lint', 'codex', 1), named('ollama-try', 'opencode', 2, true), named('opus-plan', 'agy', 3, false, 'claude'),
]
const dense = Array.from({ length: 12 }, (_, i) => named(`dense-${i}`, family, (i % 4 + 1) as 1 | 2 | 3 | 4))
const mixed = Array.from({ length: 12 }, (_, i) => named(`mixed-${i}`, (['codex', 'agy', 'claude', 'opencode'] as const)[i % 4]!, (Math.floor(i / 4) + 2) as 2 | 3 | 4))
const birds = [{ seed: seedOf('agent-a1'), tier: 2 as const }, { seed: seedOf('agent-b2'), tier: 3 as const }]
const base: SceneInput = {
  width: W, frame: 40, hour: 22, sun: { rise: 5.9, set: 17.5 }, moonPhase: 0.3, season: 'summer', snowy: false, weather: { cloud: 0.2, rain: 0, snow: 0, fog: false, thunder: false, wind: 8 },
  preset: 'city', seed: 12345, turns: Array.from({ length: 8 }, () => ({ kinds: ['read', 'edit', 'run', 'test'] })), live: null, mood: 'idle', jobs: [], agents: [], plan: null, effect: null,
}
const lineup = `${family} 1 2 3 4 · ${others.join(' ')} · agy opus, sonnet, argon`
const places: [string, Partial<SceneInput>][] = (['city', 'harbor', 'beach', 'mountains', 'countryside', 'forest', 'desert', 'tundra'] as const).flatMap(preset =>
  ([['day', 13], ['dusk', 17.8], ['night', 22]] as const).map(([time, hour]): [string, Partial<SceneInput>] => [`${preset} ${time}`, { preset, hour }]),
)
const sheets: [string, [string, Partial<SceneInput>][]][] = [
  [`${family}-grid`, [...places.map(([name, s]): [string, Partial<SceneInput>] => [`${name} · ${lineup}`, { ...s, jobs: grid }]), ['city night · all stale (amber, dims on the off beat)', { jobs: grid.map(j => ({ ...j, isStale: true })), frame: 46 }]]],
  [`${family}-busy`, [
    ['tundra night · 8 jobs + 2 subagents', { preset: 'tundra', hour: 1, jobs: busy, agents: birds }],
    ['beach day · 8 jobs + 2 subagents', { preset: 'beach', hour: 11, jobs: busy, agents: birds }],
    ['beach day · next beat, one job gone (the rest stay put)', { preset: 'beach', hour: 11, jobs: busy.filter((_, i) => i !== 2), agents: birds, frame: 45 }],
    ['city day · twelve jobs', { preset: 'city', hour: 13, jobs: dense }],
    ['harbor rain · twelve jobs', { preset: 'harbor', hour: 13, jobs: dense, weather: { cloud: 0.8, rain: 2, snow: 0, fog: false, thunder: false, wind: 18 } }],
    ['tundra snow · twelve jobs', { preset: 'tundra', hour: 22, jobs: dense, snowy: true, weather: { cloud: 0.4, rain: 0, snow: 2, fog: false, thunder: false, wind: 5 } }],
  ]],
  [`${family}-mixed`, (['city', 'harbor', 'beach', 'mountains', 'countryside', 'forest', 'desert', 'tundra'] as const).map(preset => [preset, { preset, hour: 13, jobs: mixed }] as [string, Partial<SceneInput>])],
]
// the balloon festival: six OpenCode jobs of mixed classes, their envelope colours spanning the palette, then all stale
if (family === 'opencode') {
  const flight = [
    at(0, family, 1, undefined, P.red), at(1, family, 2, undefined, P.green), at(2, family, 3, undefined, P.blue),
    at(3, family, 1, undefined, P.yellow), at(4, family, 2, undefined, P.lavender), at(5, family, 3, undefined, P.green),
  ]
  sheets.push(['balloons', [
    ...places.map(([name, s]): [string, Partial<SceneInput>] => [`${name} · six balloons, classes 1-3 twice`, { ...s, jobs: flight }]),
    ['city night · all stale (amber, dims on the off beat)', { ...places[0]![1], jobs: flight.map(j => ({ ...j, isStale: true })), frame: 46 }],
  ]])
}
for (const [sheet, states] of sheets) {
  const out = `${import.meta.dir}/${sheet}.png`
  const rows = states.map(([name, s]) => ({ name, px: Array.from(scenePixels({ ...base, ...s })) }))
  await Bun.write(out + '.json', JSON.stringify({ w: W, h: 16, rows }))
  const r = Bun.spawnSync(['uv', 'run', '-q', '--with', 'pillow', 'python', import.meta.dir + '/sheet.py', out + '.json', out])
  if (r.exitCode !== 0) console.error(r.stderr.toString())
  else console.log(out)
}
