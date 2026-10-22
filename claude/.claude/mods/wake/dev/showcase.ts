// bun dev/showcase.ts [out.bin] [frames] [width]: the eight README scenes, each rendered over `frames` animation
// frames (STEP simulation ticks apart) as raw little-endian uint32 0xRRGGBB, scene-major, `width` x 16 each.
// docs/tools/readme_gifs.py turns them into GIFs.
import { scenePixels, EFFECT_FRAMES, type SceneInput } from '../hooks/scene.ts'

const out = process.argv[2] ?? `${import.meta.dir}/showcase.bin`
const FRAMES = Number(process.argv[3] ?? 48)
const STEP = 3
const W = Number(process.argv[4] ?? 180)
const K = ['read', 'read', 'read', 'search', 'edit', 'run', 'test', 'read', 'edit', 'agent', 'web', 'edit'] as const
const turns = Array.from({ length: 16 }, (_, i) => ({ kinds: K.slice(0, 2 + ((i * 7) % 11)).concat(i % 5 === 2 ? ['fail'] : []) as any }))
const clear = { cloud: 0.2, rain: 0, snow: 0, fog: false, thunder: false, wind: 8 } as const
const base: SceneInput = {
  width: W, frame: 0, hour: 22, sun: { rise: 5.9, set: 17.5 }, moonPhase: 0.3, season: 'summer', snowy: false, weather: clear,
  preset: 'city', seed: 12345, turns, live: { kinds: ['read', 'read', 'edit', 'test', 'edit'] }, mood: 'work',
  jobs: [{ isStale: false, seed: 3 }, { isStale: true, seed: 8 }], agents: [{ seed: 1, tier: 1 }, { seed: 2, tier: 1 }], plan: { done: 2, total: 5 }, effect: null,
}
const calm = { live: null, agents: [], mood: 'idle' as const }
const fx = (kind: 'fireworks' | 'storm' | 'shoot') => ({ kind, age: 0 })

// [label, state]; an effect's age follows the frame so it plays through
export const SCENES: [string, Partial<SceneInput>][] = [
  ['City · working · turns become buildings', {}],
  ['Harbor · needs input · Codex boats and agy crew', { preset: 'harbor', hour: 19.8, mood: 'alert', agents: [], live: null }],
  ['Beach · working · bridge jobs and Claude subagent birds', { preset: 'beach', hour: 13 }],
  ['Mountains · tests passed · fireworks', { ...calm, preset: 'mountains', hour: 20.2, mood: 'happy', effect: fx('fireworks') }],
  ['Countryside · idle · plan lamps show progress', { ...calm, preset: 'countryside', hour: 11, plan: { done: 3, total: 5 } }],
  ['Forest · rain · command failed', { ...calm, preset: 'forest', hour: 15, mood: 'sad', weather: { ...clear, cloud: 0.9, rain: 2, wind: 18 }, effect: fx('storm') }],
  ['Desert · dusk · a finished job leaves a shooting star', { ...calm, preset: 'desert', hour: 18.6, effect: fx('shoot') }],
  ['Tundra · winter night · sleeping', { ...calm, preset: 'tundra', hour: 2, mood: 'sleep', season: 'winter', snowy: true, moonPhase: 0.5, weather: { ...clear, cloud: 0.4, snow: 2, wind: 5 }, jobs: [] }],
]

const data = new Uint32Array(SCENES.length * FRAMES * W * 16)
let at = 0
for (const [, state] of SCENES) {
  for (let i = 0; i < FRAMES; i++) {
    const effect = state.effect ? { ...state.effect, age: (i * STEP) % EFFECT_FRAMES[state.effect.kind] } : null
    data.set(scenePixels({ ...base, ...state, effect, frame: 37 + i * STEP }), at)
    at += W * 16
  }
}
await Bun.write(out, data)
console.log(out, SCENES.length, 'scenes x', FRAMES, 'frames')
