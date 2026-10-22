// bun dev/tourcheck.ts: plays /wake tour frame by frame per landscape; reports black pixels, dropped fractional draws (needs the __frac probe in pixels.ts) and frames whose change spikes over their neighbours.
import { scenePixels, type SceneInput } from '../hooks/scene.ts'
const PRESETS = ['city', 'harbor', 'beach', 'mountains', 'countryside', 'forest', 'desert', 'tundra'] as const
let frac = 0
;(globalThis as any).__frac = () => { frac++ }
const K = ['read', 'read', 'edit', 'run', 'test', 'read', 'edit', 'agent'] as const
const turns = Array.from({ length: 9 }, (_, i) => ({ kinds: K.slice(0, 3 + (i * 5) % 6) as any }))
const W = 186, TOUR = 120
const base: SceneInput = { width: W, frame: 0, hour: 0, sun: { rise: 5.7, set: 17.6 }, moonPhase: 0.4, season: 'summer', snowy: false, weather: { cloud: 0.6, rain: 1, snow: 0, fog: false, thunder: false, wind: 10 }, preset: 'city', seed: 3911, turns, live: null, mood: 'idle', jobs: [{ isStale: false, seed: 4 }], agents: [{ seed: 1, tier: 1 }], plan: null, effect: null }
const report: any[] = []
for (const [pi, preset] of PRESETS.entries()) {
  let prev: Uint32Array | null = null
  const deltas: number[] = []
  const stats = { preset, black: 0, blackFrames: [] as number[], frac: 0, fracFrames: [] as number[], jumps: [] as [number, number][] }
  for (let t = 0; t < TOUR; t++) {
    const frame = 5000 + pi * TOUR + t
    const hour = (4 + (t / TOUR) * 24) % 24
    frac = 0
    const px = scenePixels({ ...base, preset, frame, hour })
    let black = 0
    for (const v of px) if (v === 0) black++
    if (black) { stats.black += black; if (stats.blackFrames.length < 5) stats.blackFrames.push(t) }
    if (frac) { stats.frac += frac; if (stats.fracFrames.length < 8) stats.fracFrames.push(t) }
    if (prev) {
      let sum = 0
      for (let i = 0; i < px.length; i++) {
        const a = px[i]!, b = prev[i]!
        sum += Math.abs(((a >> 16) & 255) - ((b >> 16) & 255)) + Math.abs(((a >> 8) & 255) - ((b >> 8) & 255)) + Math.abs((a & 255) - (b & 255))
      }
      deltas.push(sum / px.length / 3)
    }
    prev = px
  }
  // a glitch: a frame whose change spikes over its neighbours' (median of the 6 around it)
  deltas.forEach((d, i) => {
    const around = deltas.slice(Math.max(0, i - 3), i).concat(deltas.slice(i + 1, i + 4)).sort((a, b) => a - b)
    const med = around[Math.floor(around.length / 2)] ?? 0
    if (d > 4 && d > med * 3) stats.jumps.push([i + 1, Math.round(d * 10) / 10])
  })
  stats.mean = Math.round((deltas.reduce((a, b) => a + b, 0) / deltas.length) * 10) / 10
  report.push(stats)
}
for (const r of report) console.log(r.preset.padEnd(12), 'black', r.black, r.blackFrames.join(','), '| frac draws', r.frac, r.fracFrames.join(','), '| mean Δ', r.mean, '| spikes', r.jumps.slice(0, 10).map(([t, s]: any) => `${t}:${s}`).join(' '))
