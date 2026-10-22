// bun dev/dock.ts [out.bin] [frames] [width]: the README's beach dock scene over `frames` animation frames (raw
// uint32 0xRRGGBB, width x 16 each) plus out.json: per frame, where each thing the legend names is (its bounding box in cells).
// A thing is found by rendering the scene without it and diffing, so nothing here copies the renderer's layout maths.
import { scenePixels, type SceneInput } from '../hooks/scene.ts'

const out = process.argv[2] ?? `${import.meta.dir}/dock.bin`
const FRAMES = Number(process.argv[3] ?? 48)
const STEP = 3
const W = Number(process.argv[4] ?? 117) // x12 = 1404 px, the width of the 156-column status line at 9 px a cell
const H = 16
const K = ['read', 'read', 'read', 'search', 'edit', 'run', 'test', 'read', 'edit', 'agent', 'web', 'edit'] as const
const turns = Array.from({ length: 16 }, (_, i) => ({ kinds: K.slice(0, 2 + ((i * 7) % 11)).concat(i % 5 === 2 ? ['fail'] : []) as any }))
const state: SceneInput = {
  width: W, frame: 0, hour: 18.3, sun: { rise: 5.9, set: 17.5 }, moonPhase: 0.3, season: 'summer', snowy: false,
  weather: { cloud: 0.2, rain: 0, snow: 0, fog: false, thunder: false, wind: 8 },
  preset: 'beach', seed: 12345, turns, live: { kinds: ['read', 'read', 'edit', 'test', 'edit'] }, mood: 'work',
  jobs: [{ isStale: false, seed: 3, tier: 2, kind: 'codex' }, { isStale: false, seed: 8, tier: 3, kind: 'agy' }],
  agents: [{ seed: 1, tier: 2 }], plan: { done: 3, total: 5 }, effect: null,
}
// name -> the same scene without that thing
const without: Record<string, Partial<SceneInput>> = {
  claude: { agents: [] },
  codex: { jobs: state.jobs.filter(job => job.kind !== 'codex') },
  agy: { jobs: state.jobs.filter(job => job.kind !== 'agy') },
  live: { live: null },
  lamps: { plan: null }, // lit lamps are the steps done; without a plan they only light at night
  mochi: { mood: 'sleep' },
}

// removing the live turn shifts the whole street, so only the columns beside Mochi (where it stands) count
const LIVE_FROM = W - 24
const LIVE_TO = W - 15

function box(a: Uint32Array, b: Uint32Array, from = 0, to = W) {
  let x0 = W, y0 = H, x1 = -1, y1 = -1
  for (let i = 0; i < a.length; i++) {
    if (a[i] === b[i]) continue
    const x = i % W, y = (i / W) | 0
    if (x < from || x >= to) continue
    x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y)
  }
  return x1 < 0 ? null : { x: x0, y: y0, w: x1 - x0 + 1, h: y1 - y0 + 1 }
}

// one box per lit lamp: changed pixels grouped wherever their columns lie within 2 of each other
function clusters(a: Uint32Array, b: Uint32Array) {
  const hit: [number, number][] = []
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) hit.push([i % W, (i / W) | 0])
  hit.sort((p, q) => p[0] - q[0])
  const groups: [number, number][][] = []
  for (const point of hit) {
    const last = groups[groups.length - 1]
    if (last && point[0] - last[last.length - 1]![0] <= 2) last.push(point)
    else groups.push([point])
  }
  return groups.map(g => {
    const xs = g.map(p => p[0]), ys = g.map(p => p[1])
    const x = Math.min(...xs), y = Math.min(...ys)
    return { x, y, w: Math.max(...xs) - x + 1, h: Math.max(...ys) - y + 1 }
  })
}

// start where the subagent's bird stays on screen for the whole loop, so its callout never blinks out
const seen = (frame: number) => box(scenePixels({ ...state, frame }), scenePixels({ ...state, frame, ...without.claude })) !== null
let start = 0
while (start < 600 && !Array.from({ length: FRAMES }, (_, i) => start + i * STEP).every(seen)) start++

const pixels = new Uint32Array(FRAMES * W * H)
const anchors: Record<string, ReturnType<typeof box> | ReturnType<typeof clusters>>[] = []
for (let i = 0; i < FRAMES; i++) {
  const at = { ...state, frame: start + i * STEP }
  const full = scenePixels(at)
  pixels.set(full, i * W * H)
  anchors.push(
    Object.fromEntries(
      Object.entries(without).map(([name, change]) => [
        name,
        name === 'live'
          ? box(full, scenePixels({ ...at, ...change }), LIVE_FROM, LIVE_TO)
          : name === 'lamps'
            ? clusters(full, scenePixels({ ...at, ...change }))
            : box(full, scenePixels({ ...at, ...change })),
      ]),
    ),
  )
}
await Bun.write(out, pixels)
await Bun.write(out.replace(/\.bin$/, '.json'), JSON.stringify({ w: W, h: H, frames: FRAMES, anchors }))
console.log(out, FRAMES, 'frames', W, 'x', H)
