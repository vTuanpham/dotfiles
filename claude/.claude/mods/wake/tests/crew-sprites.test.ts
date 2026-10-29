import { expect, test } from 'claude-code/testing'
import { airJobs, boat, fly, placeFly } from '../hooks/landscapes/crew'
import { type Job, type Look, P } from '../hooks/landscapes/kit'
import { canvas } from '../hooks/pixels'

const look = { frame: 0, night: 1 } as Look
const kinds = ['codex', 'agy', 'claude', 'opencode'] as const
const tiers = [1, 2, 3, 4] as const

function render(job: Job, frame: number, water = false) {
  const c = canvas(40, 20)
  if (water) boat(c, { ...look, frame }, 10, 5, job)
  else fly(c, { ...look, frame }, 20, 10, job)
  return Array.from(c.px)
}

function bounds(px: number[]) {
  const points = px.flatMap((color, i) => color ? [[i % 40, Math.floor(i / 40)]] : [])
  const xs = points.map(p => p[0]!)
  const ys = points.map(p => p[1]!)
  return [Math.max(...xs) - Math.min(...xs) + 1, Math.max(...ys) - Math.min(...ys) + 1]
}

test('each crew class has its own size and animated image, including stale amber', () => {
  for (const kind of kinds) for (const isStale of [false, true]) {
    const pictures = tiers.map(tier => render({ kind, tier, seed: 0, isStale }, 0))
    expect(new Set(pictures.map(p => bounds(p).join(','))).size).toBe(4)
    expect(new Set(pictures.map(p => p.join(','))).size).toBe(4)
    for (const [i, tier] of tiers.entries()) {
      const job = { kind, tier, seed: 0, isStale }
      // Compare on the same stale pulse so the sprite animation itself must change.
      expect(render(job, 15)).not.toEqual(pictures[i])
    }
  }
  for (const isStale of [false, true]) {
    const pictures = tiers.map(tier => render({ kind: 'codex', tier, seed: 0, isStale }, 0, true))
    expect(new Set(pictures.map(p => bounds(p).join(','))).size).toBe(4)
    expect(new Set(pictures.map(p => p.join(','))).size).toBe(4)
  }
})

test('flyers choose deterministic clear lanes and reserve space for the next sprite', () => {
  const obstacle = { x: 16, y: 4, w: 8, h: 8 }
  const makeLook = () => ({ ...look, crewZones: [{ ...obstacle }] })
  const job: Job = { kind: 'codex', tier: 1, seed: 0, isStale: false }
  const a = makeLook(), b = makeLook()
  const first = placeFly(canvas(40, 20), a, 20, 8, job, 38)!
  expect(first).toEqual(placeFly(canvas(40, 20), b, 20, 8, job, 38))
  const second = placeFly(canvas(40, 20), a, 20, 8, job, 38)!
  const overlaps = (x: typeof first, y: typeof first) => x.x < y.x + y.w && x.x + x.w > y.x && x.y < y.y + y.h && x.y + x.h > y.y
  expect(overlaps(first, obstacle)).toBe(false)
  expect(overlaps(first, second)).toBe(false)
})

test('small daytime flyers get a contrasting outline selected from their surroundings', () => {
  const job: Job = { kind: 'codex', tier: 1, seed: 0, isStale: false }
  const day = { ...look, night: 0, top: P.blue }
  const light = canvas(40, 20), dark = canvas(40, 20)
  light.rect(0, 0, 40, 20, P.snow)
  dark.rect(0, 0, 40, 20, P.crust)
  fly(light, day, 20, 10, job)
  fly(dark, day, 20, 10, job)
  expect(light.get(20, 8)).not.toBe(P.snow)
  expect(dark.get(20, 8)).not.toBe(P.crust)
  expect(light.get(20, 8)).not.toBe(dark.get(20, 8))
})

test('a crowded sky places twelve mixed flyers without covering reserved decor', () => {
  for (const width of [160, 260]) {
    const c = canvas(width, 16)
    const obstacles = [{ x: 30, y: 2, w: 5, h: 4 }, { x: 85, y: 7, w: 6, h: 5 }]
    const state = { ...look, top: P.blue, crewZones: [...obstacles], crewAnchors: [] as number[], crewSpriteZones: [] as { x: number; y: number; w: number; h: number }[] }
    const jobs = Array.from({ length: 12 }, (_, i): Job => ({ kind: kinds[i % 4]!, tier: (i % 4 + 1) as 1 | 2 | 3 | 4, seed: i + 1, isStale: false }))
    airJobs(c, state, jobs, width - 16)
    expect(state.crewSpriteZones.length).toBe(12)
    expect(new Set(state.crewAnchors).size).toBe(12)
    for (const zone of state.crewSpriteZones) {
      expect(zone.w).toBeGreaterThanOrEqual(3)
      expect(zone.h).toBeGreaterThanOrEqual(2)
      for (const obstacle of obstacles) {
        for (let y = obstacle.y; y < obstacle.y + obstacle.h; y++) for (let x = obstacle.x; x < obstacle.x + obstacle.w; x++) expect(c.get(x, y)).toBe(0)
      }
      let painted = 0
      for (let y = zone.y; y < zone.y + zone.h; y++) for (let x = zone.x; x < zone.x + zone.w; x++) if (c.get(x, y)) painted++
      expect(painted).toBeGreaterThanOrEqual(3)
    }
  }
})

test('failed initial placements leave no invisible hit owners', () => {
  const c = canvas(30, 16, true)
  const state = { ...look, top: P.blue, crewZones: [{ x: 0, y: 0, w: 22, h: 12 }], crewAnchors: [], crewSpriteZones: [], crewGround: 10 }
  const jobs = Array.from({ length: 13 }, (_, i): Job => ({ kind: kinds[i % 4]!, tier: 4, seed: i + 1, isStale: false, hitOwner: i + 1 }))
  airJobs(c, state, jobs, 20)
  expect(c.px.every((color, i) => color !== 0 || c.hitOwners![i] === 0)).toBe(true)
})
