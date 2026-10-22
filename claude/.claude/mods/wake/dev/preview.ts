// bun dev/preview.ts <preset> [out.png] [width]: a sheet of states (phases, weather, effects, events) for one landscape.
import { lookOf, scenePixels, type SceneInput } from '../hooks/scene.ts'
import { LANDSCAPES } from '../hooks/landscapes/index.ts'
const preset = (process.argv[2] ?? 'city') as SceneInput['preset']
const out = process.argv[3] ?? `${import.meta.dir}/${preset}.png`
const W = Number(process.argv[4] ?? 160)
const K = ['read', 'read', 'read', 'search', 'edit', 'run', 'test', 'read', 'edit', 'agent', 'web', 'edit'] as const
const turns = Array.from({ length: 16 }, (_, i) => ({ kinds: K.slice(0, 2 + ((i * 7) % 11)).concat(i % 5 === 2 ? ['fail'] : []) as any }))
const base: SceneInput = {
  width: W, frame: 37, hour: 22, sun: { rise: 5.9, set: 17.5 }, moonPhase: 0.3, season: 'summer', snowy: false, weather: { cloud: 0.2, rain: 0, snow: 0, fog: false, thunder: false, wind: 8 },
  preset, seed: 12345, turns, live: { kinds: ['read', 'read', 'edit', 'test', 'edit'] }, mood: 'work',
  jobs: [{ isStale: false, seed: 3 }, { isStale: true, seed: 8 }], agents: [{ seed: 1, tier: 1 }, { seed: 2, tier: 1 }], plan: { done: 2, total: 5 }, effect: null,
}
const calm = { live: null, agents: [], mood: 'idle' as const }
const states: [string, Partial<SceneInput>][] = [
  ['night · working (crane, laptop, fireflies, birds)', {}],
  ['morning · idle · few turns', { ...calm, hour: 8, turns: turns.slice(0, 3) }],
  ['noon · partly cloudy · empty session', { ...calm, hour: 12.5, turns: [], weather: { cloud: 0.5, rain: 0, snow: 0, fog: false, thunder: false, wind: 20 } }],
  ['dusk · tests passed (fireworks)', { ...calm, hour: 17.8, mood: 'happy', effect: { kind: 'fireworks', age: 14 } }],
  ['day · rain + rainbow', { ...calm, hour: 14, weather: { cloud: 0.8, rain: 2, snow: 0, fog: false, thunder: false, wind: 18 }, forceEvent: 'rainbow' }],
  ['night · thunderstorm · failed', { ...calm, hour: 21, mood: 'sad', frame: 173, weather: { cloud: 1, rain: 3, snow: 0, fog: false, thunder: true, wind: 35 } }],
  ['winter night · snowing · asleep', { ...calm, hour: 2, mood: 'sleep', season: 'winter', snowy: true, moonPhase: 0.5, weather: { cloud: 0.4, rain: 0, snow: 2, fog: false, thunder: false, wind: 5 }, jobs: [] }],
  ['autumn morning · fog', { ...calm, hour: 7, season: 'autumn', weather: { cloud: 0.6, rain: 0, snow: 0, fog: true, thunder: false, wind: 3 } }],
  ['spring day · alert', { ...calm, hour: 10, season: 'spring', mood: 'alert' }],
  ...LANDSCAPES[preset].events.map(e => [`event: ${e.name}`, { ...calm, hour: [22, 12, 17.8, 6.2].find(hour => !e.when || e.when(lookOf({ ...base, ...calm, hour, season: 'autumn' }))) ?? 22, season: 'autumn', forceEvent: e.name, frame: Math.floor(e.frames * 0.45) }] as [string, Partial<SceneInput>]),
]
const rows = states.map(([name, s]) => ({ name, px: Array.from(scenePixels({ ...base, ...s })) }))
await Bun.write(out + '.json', JSON.stringify({ w: W, h: 16, rows }))
const r = Bun.spawnSync(['uv', 'run', '-q', '--with', 'pillow', 'python', import.meta.dir + '/sheet.py', out + '.json', out])
if (r.exitCode !== 0) console.error(r.stderr.toString())
else console.log(out)
