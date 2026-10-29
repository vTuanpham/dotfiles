import { type Canvas, hash, mix, sprite } from '../pixels'
import { type Building, byPhase, KIND_COLOR, type Landscape, type Look, P, SCENE_H, editsOf, farTone, foliage, lightWindows, wave, jobAccent } from './kit'
import { airJobs, packBoats, placeBoat, stations } from './crew'

// Harbor: a port town on the water. Turns are waterfront buildings on a pier (warehouse,
// row house, customs tower, fish market, stepped gable); bridge jobs are sailboats; the
// water mirrors the town. Across the bay: hills, a town, container cranes, a lighthouse.
// The day shows in who is out: fishing boats at dawn, a busy quay at noon, a glitter path
// at dusk, the beam and ship lights at night.

const GROUND = SCENE_H - 6 // the pier planks (buildings stand on the row above)
const WATER = GROUND + 2 // water rows, below the pier's fascia
const FAR = GROUND - 3 // last row of the far shore; the bay shows below it
const BASE = SCENE_H - 2 // the row boat hulls end on
const WALLS = [0x7a4a42, 0x44607a, 0x6e6a4a, 0x5c4a68, 0x4a6e68, 0x80604a]
const ROOFS = [0x3a2e3a, 0x5a3a36, 0x2f3b4a, 0x4a3a2a]
const AWNINGS = [P.red, P.blue, P.green, P.peach, P.mauve]
const MIN_H = [4, 6, 7, 5, 5] // warehouse, row house, customs tower, fish market, stepped gable
const BASE_W = [6, 5, 5, 6, 5]
const styleOf = (index: number) => hash(index * 7 + 3) % 5
const lightX = (look: Look) => 10 + (hash(look.seed) % Math.max(1, Math.floor(look.W * 0.3)))
const warm = (look: Look) => byPhase(look, { dawn: 0.12, dusk: 0.12 })
const dim = (color: number, look: Look) => mix(mix(color, P.peach, warm(look)), P.ink, 0.35 * look.night)
const sea = (look: Look, y: number) => mix(mix(mix(0x3a86b4, look.horizon, 0.25 + byPhase(look, { dawn: 0.3, dusk: 0.3 })), 0x1f3f6c, (y - WATER) * 0.2), P.ink, 0.5 * look.night)
const lamp = (look: Look) => (look.night > 0.1 ? P.yellow : P.surface2)
const SAIL_COLORS = [P.text, P.pink, P.sky, P.green, P.mauve]

// Sprites face right: m mast, s sail, j jib, f pennant, c cabin, w window, l lantern, r stripe, h hull.
const SAILBOAT = ['....mf...', '...smjj..', '..ssmjjj.', '.sssmjjjj', 'hhhhhhhhh', '.hhhhhhh.']
const TRAWLER = ['.......l..', '.......m..', '.cccc..m..', '.cwwc..m..', 'rrrrrrrrrr', '.hhhhhhhh.']
const TRUCK = ['bbbbb...', 'bbbbbcw.', 'bbbbbccc', '.o...o.o']
const HULLS = [P.red, P.blue, P.green, P.mauve, P.teal]
const DINGHY = ['...m...', '..smj..', '.ssmjj.', 'sssmjjj', 'hhhhhhh', '.hhhhh.']
const FERRY = ['.....ss.....', '...cwwwwc...', '..cccccccc..', '.cwcwcwcwcc.', 'rrrrrrrrrrrr', '.hhhhhhhhhh.']
const PERSON = ['.h', 'bb', '.b', 'l.']
const GULL_UP = ['g.g', '.g.']
const GULL_DOWN = ['.g.', 'g.g']

/** The far shore: hills, a town, container cranes, a moored ship, the bay, a lighthouse. */
function farShore(c: Canvas, look: Look) {
  const tint = mix(farTone(look, 0), foliage(look.season, look.seed)[1], 0.3 * (1 - look.night))
  for (let x = 0; x < c.W; x++) {
    const h = Math.max(2, Math.min(5, 3 + Math.round(1.6 * Math.sin(x * 0.07 + (look.seed % 7)) + 1.2 * Math.sin(x * 0.19 + (look.seed % 5)))))
    for (let y = FAR - h + 1; y <= FAR; y++) c.set(x, y, tint)
    if (look.snowy && h > 3) c.set(x, FAR - h + 1, mix(P.snow, tint, 0.3))
  }
  const town = farTone(look, 1)
  const working = look.phase !== 'night' && look.phase !== 'dawn'
  for (let x = 0, seg = 0; x < c.W; seg++) {
    const h = hash(look.seed + seg * 7 + 1013)
    const w = 3 + (h % 3)
    const kind = (h >>> 4) % 6
    const bh = 2 + ((h >>> 8) % 3)
    if (kind === 5) {
      // a container crane: two legs, a jib over the water, a trolley that works by day
      for (let y = FAR - 5; y <= FAR; y++) c.set(x + 1, y, town)
      for (let k = -1; k < 5; k++) c.set(x + k, FAR - 5, town)
      const tx = x + 1 + (working ? Math.round(2 * wave(look.frame, 40, h % 40)) : 0)
      c.set(tx, FAR - 4, town)
      if (working) c.set(tx, FAR - 3, mix(town, [P.red, P.blue, P.peach][h % 3]!, 0.6))
      if (look.night > 0.3 && look.frame % 20 < 10) c.set(x + 1, FAR - 6, P.red)
    } else {
      for (let k = 0; k < w && kind >= 2; k++) {
        for (let y = FAR - bh + 1; y <= FAR; y++) c.set(x + k, y, town)
        if (look.night > 0.3 && hash((x + k) * 17 + seg) % 4 === 0) c.set(x + k, FAR - 1 - (hash(x + k) % 2), mix(town, P.yellow, 0.5 * look.night))
      }
      if (kind === 3) c.set(x + 1, FAR - bh, town) // a spire
    }
    x += w + 1 + ((h >>> 11) % 3)
  }
  const bay = mix(sea(look, WATER), look.horizon, 0.3)
  for (let y = FAR + 1; y < GROUND; y++) {
    for (let x = 0; x < c.W; x++) {
      c.set(x, y, bay)
      if (Math.sin(x * 0.6 + look.frame * 0.12 + y * 3) > 0.9) c.glow(x, y, P.white, 0.12)
    }
  }
  for (let x = 0; x < c.W; x++) c.glow(x, FAR + 1, c.get(x, FAR), 0.35) // the shore mirrored
  const sx = 24 + (hash(look.seed + 5) % Math.max(1, c.W - 60)) // a ship at anchor, lit once it is dim
  sprite(c, sx, FAR, ['...s......', '..cwcwc...', 'hhhhhhhhhh'], { s: P.red, c: mix(P.rosewater, bay, 0.4), w: look.night > 0.2 ? P.yellow : P.sky, h: mix(P.ink, bay, 0.3) })
  for (let k = 0; k < 2; k++) {
    const x = Math.round((look.frame * 0.03 + (hash(look.seed + k) % c.W)) % c.W) // far sails
    c.set(x, FAR + 1, mix(P.text, bay, 0.2 + 0.5 * look.night))
    c.set(x, FAR + 2, mix(P.ink, bay, 0.3))
  }
  const lx = lightX(look)
  sprite(c, lx, FAR - 7, ['.rr.', '.ll.', '.ww.', '.rr.', '.ww.', '.rr.', '.ww.', 'bbbb'], { r: dim(P.red, look), l: look.night > 0.3 ? P.yellow : P.overlay2, w: dim(P.rosewater, look), b: mix(P.surface1, bay, 0.3) })
}

/** A rotating beam from the lighthouse: it sweeps one way, thins, flashes, sweeps back. */
function beam(c: Canvas, look: Look) {
  if (look.night < 0.35) return
  const cx = lightX(look) + 1
  const cs = Math.cos(look.frame * 0.06)
  const len = Math.abs(cs) * 38
  const dir = cs > 0 ? 1 : -1
  for (let d = 1; d < len; d++) {
    const a = 0.8 * look.night * (1 - d / len)
    const x = cx + dir * d - (dir > 0 ? 0 : 1)
    c.glow(x, FAR - 6 + Math.floor(d * 0.12), P.yellow, a)
    c.glow(x, FAR - 5 + Math.floor(d * 0.12), P.yellow, a * 0.5)
    c.glow(x, FAR - 7 + Math.floor(d * 0.12), P.yellow, a * 0.3)
  }
  if (Math.abs(cs) < 0.3) for (const [dx, dy] of [[-1, 0], [1, 0], [0, -1], [0, 1], [0, 0]] as const) c.glow(cx + dx, FAR - 6 + dy, P.yellow, 0.6)
}

/** One building's roof rows and body: the five styles share the walls, differ on top. */
function shell(c: Canvas, look: Look, b: Building, style: number, y0: number, rr: number) {
  const { x0, width: w } = b
  const wall = dim(WALLS[hash(b.index) % WALLS.length]!, look)
  const roof = dim(ROOFS[hash(b.index * 5) % ROOFS.length]!, look)
  const roofAt = (r: number) => (look.snowy ? mix(P.snow, roof, 0.1 + 0.15 * r) : r === 0 ? mix(roof, P.text, 0.12) : roof)
  for (let r = 0; r < rr; r++) {
    const inset = style === 0 || style === 3 ? -1 : style === 2 ? 2 - r : rr - 1 - r // flat roofs overhang, gables and caps taper
    for (let x = x0 + inset; x < x0 + w - inset; x++) c.set(x, y0 + r, roofAt(r))
  }
  const lit = mix(wall, P.text, 0.1)
  const shade = mix(wall, P.ink, 0.25)
  const step = (y: number) => (style === 4 ? Math.max(0, 2 - (y - y0)) : 0) // stepped gable top
  for (let y = y0 + rr; y < GROUND; y++) {
    for (let x = x0; x < x0 + w; x++) {
      if (x < x0 + step(y) || x >= x0 + w - step(y)) continue
      const topmost = style === 4 && step(y - 1) > Math.min(x - x0, x0 + w - 1 - x)
      c.set(x, y, look.snowy && topmost ? P.snow : x === x0 ? lit : x === x0 + w - 1 ? shade : wall)
    }
  }
  return wall
}

/** The live turn: scaffold, a worker on the planks, a dock crane carrying the newest call's crate. */
function scaffold(c: Canvas, look: Look, b: Building, y0: number) {
  const { x0, width: w } = b
  const wood = dim(P.wood, look)
  for (let y = Math.max(0, y0 - 1); y < GROUND; y++) c.set(x0 - 1, y, wood)
  const py = GROUND - 3
  for (let x = x0 - 1; x <= x0 + w; x++) c.set(x, py, mix(wood, P.text, 0.15))
  const wx = x0 + ((look.frame >> 2) % w)
  c.set(wx, py - 1, P.peach)
  c.set(wx, py - 2, P.yellow)
  for (let y = y0; y < GROUND; y++) for (let x = x0; x < x0 + w; x++) if ((x + y) % 3 === 0) c.glow(x, y, P.yellow, 0.15)
  const mast = x0 + w
  const jib = Math.max(0, y0 - 3)
  for (let y = jib; y < GROUND; y++) c.set(mast, y, mix(P.yellow, P.ink, 0.45))
  for (let x = x0 - 2; x <= mast; x++) c.set(x, jib, mix(P.yellow, P.ink, 0.35))
  const hook = x0 + 1 + Math.round(2 * wave(look.frame, 36))
  c.set(hook, jib + 1, P.surface2)
  c.set(hook, jib + 2, P.surface2)
  c.rect(hook, jib + 3, 2, 2, KIND_COLOR[b.kinds[b.kinds.length - 1] ?? 'run'])
  if (look.frame % 8 < 4) c.set(mast, jib, P.red)
}

/** A bit of quay clutter, stable for its absolute column. */
function decor(c: Canvas, look: Look, kind: number, x: number, h: number) {
  const wood = dim(P.wood, look)
  const base = GROUND - 1
  const snow = (xx: number, y: number) => look.snowy && c.set(xx, y, P.snow)
  const iron = mix(P.overlay0, P.ink, 0.3 + 0.3 * look.night)
  if (kind === 0) {
    c.rect(x, base - 1, 3, 2, wood)
    c.rect(x, base - 1, 3, 1, mix(wood, P.text, 0.15))
    c.set(x + 1, base, dim(P.woodDark, look))
    if (h & 0x10000) c.rect(x, base - 2, 2, 1, dim(P.woodDark, look))
    snow(x, base - ((h & 0x10000) ? 2 : 1))
  } else if (kind === 1) {
    for (let k = 0; k < 2; k++) {
      c.rect(x + k, base - 2, 1, 3, dim(mix(P.woodDark, P.maroon, 0.25 * k), look))
      c.set(x + k, base - 1, iron)
    }
  } else if (kind === 2) {
    c.rect(x, base - 1, 1, 2, iron) // a bollard with its coiled rope
    c.set(x + 1, base, dim(P.sand, look))
  } else if (kind === 3) {
    const [light, dark] = foliage(look.season, h)
    c.rect(x + 1, base - 1, 1, 2, wood)
    c.rect(x, base - 4, 3, 3, dim(dark, look))
    c.set(x + 1, base - 5, dim(light, look))
    c.set(x, base - 4, dim(light, look))
    c.set(x + 2, base - 3, dim(light, look))
    snow(x + 1, base - 5)
  } else if (kind === 4) {
    c.set(x, base - 2, dim(P.peach, look)) // an angler on the pier edge, rod and line over the water
    c.rect(x, base - 1, 1, 2, dim(P.blue, look))
    c.set(x + 1, base - 1, wood)
    c.set(x + 2, base - 2, wood)
    c.set(x + 3, base - 3, wood)
    for (let y = base - 2; y < WATER + 1; y++) c.glow(x + 3, y, P.text, 0.35)
    if ((look.frame >> 2) % 5 !== 0) c.set(x + 3, WATER + 1, P.red)
  } else if (kind === 5) {
    for (const px of [x, x + 2]) c.rect(px, base - 3, 1, 4, wood)
    c.rect(x, base - 3, 3, 1, wood)
    for (let y = base - 2; y <= base; y++) c.set(x + 1, y, mix(P.overlay1, P.sky, 0.3 - 0.2 * look.night))
  } else {
    c.rect(x, base - 2, 2, 3, dim(mix(P.teal, P.ink, 0.55), look))
    c.rect(x, base - 2, 2, 1, dim(mix(P.teal, P.ink, 0.3), look))
  }
}

/** Soft mist bands drifting over the water. */
function mist(c: Canvas, look: Look, age: number, strength: number) {
  for (let y = GROUND - 3; y < WATER + 3; y++) {
    for (let x = 0; x < c.W; x++) {
      const n = Math.sin(x * 0.09 + y * 1.7 + age * 0.04 * (y % 2 ? 1 : -1))
      if (n > 0.1) c.glow(x, y, mix(P.text, look.horizon, 0.3), (n - 0.1) * 0.35 * strength)
    }
  }
}

/** The water mirrors the pier, rippling; at dawn and dusk the sun lays a glitter path on it. */
function reflect(c: Canvas, look: Look) {
  const sun = look.phase === 'dusk' ? look.W - 11 : look.phase === 'dawn' ? 8 : -99
  for (let y = WATER; y < c.H; y++) {
    const src = GROUND - 1 - (y - WATER)
    const d = y - WATER
    for (let x = 0; x < c.W; x++) {
      c.glow(x, y, c.get(x + Math.round(1.2 * Math.sin(x * 0.4 + look.frame * 0.2 + y * 2)), src), 0.5 - d * 0.1)
      if (Math.abs(x - sun) <= 2 + d * 2 && hash(x * 7 + y * 13 + (look.frame >> 2)) % 3 === 0) c.glow(x, y, P.peach, 0.9 - 0.12 * d)
    }
  }
}

/** Boats and ships under way, by the hour: trawlers out at dawn and home at dusk, dinghies by day. */
function smallBoats(c: Canvas, look: Look) {
  const n = Math.round(byPhase(look, { dawn: 3, morning: 2, noon: 3, afternoon: 3, dusk: 3, night: 1 }))
  const trawl = look.phase === 'dawn' || look.phase === 'dusk' || look.phase === 'night' || look.phase === 'morning'
  for (let k = 0; k < n; k++) {
    const h = hash(look.seed + k * 53)
    const dir = look.phase === 'dusk' ? -1 : trawl ? 1 : k % 2 ? 1 : -1
    const span = look.W + 24
    const pos = ((h % span) + look.frame * (trawl ? 0.09 : 0.05)) % span
    const x = Math.round(dir > 0 ? pos - 12 : look.W + 12 - pos)
    const y = BASE - (trawl ? 5 : 5) - (Math.sin(look.frame * 0.12 + k * 2) > 0.5 ? 1 : 0)
    if (trawl) sprite(c, x, y, TRAWLER, { l: lamp(look), m: P.overlay1, c: dim(P.rosewater, look), w: look.night > 0.1 ? P.yellow : P.sky, r: dim(HULLS[h % HULLS.length]!, look), h: dim(P.woodDark, look) }, dir < 0)
    else sprite(c, x, y, DINGHY, { m: P.overlay1, s: dim(SAIL_COLORS[h % SAIL_COLORS.length]!, look), j: dim(SAIL_COLORS[(h >>> 4) % SAIL_COLORS.length]!, look), h: dim(P.wood, look) }, dir < 0)
    if (look.night > 0.1 && trawl) c.glow(x + (dir > 0 ? 7 : 2), y - 1, P.yellow, 0.5)
    for (let w = 1; w <= 3; w++) c.glow(x + (dir > 0 ? -w : 8 + w), BASE, P.white, 0.5 - w * 0.12) // wake
  }
}

/** People on the pier: anglers and few at dawn, dock workers by day, strollers at dusk, a watchman at night. */
function people(c: Canvas, look: Look, right: number) {
  const n = Math.min(Math.round(byPhase(look, { dawn: 3, morning: 6, noon: 8, afternoon: 6, dusk: 5, night: 1 })), Math.floor(right / 14))
  const shirts = look.phase === 'dusk' ? [P.pink, P.mauve, P.red, P.blue] : look.phase === 'night' ? [P.overlay1] : [P.peach, P.yellow, P.blue, P.green, P.red]
  for (let k = 0; k < n; k++) {
    const h = hash(look.seed * 7 + k * 977)
    const walks = k % 3 !== 0
    const x = Math.round((((h % right) + (walks ? (k % 2 ? 1 : -1) * look.frame * 0.12 : 0)) % right + right) % right)
    const step = (look.frame + k * 2) % 6 < 3
    const shirt = dim(shirts[h % shirts.length]!, look)
    sprite(c, x, GROUND - 4, PERSON, { h: dim([P.peach, P.rosewater, P.flamingo][h % 3]!, look), b: shirt, l: dim(P.surface1, look) })
    if (step && walks) c.set(x + 1, GROUND - 1, dim(P.surface1, look))
    if (look.phase !== 'night' && look.phase !== 'dusk' && h % 2) c.set(x, GROUND - 5, P.yellow) // a hard hat
    if (look.phase === 'night') {
      c.set(x + 2, GROUND - 2, P.yellow) // the watchman's lantern
      for (const [dx, dy] of [[1, 0], [3, 0], [2, -1], [2, 1]] as const) c.glow(x + 2 + dx - 2, GROUND - 2 + dy, P.yellow, 0.3)
    }
  }
}

/** A pier truck hauling crates, busy hours only. */
function trucks(c: Canvas, look: Look, right: number) {
  const n = Math.round(byPhase(look, { morning: 1, noon: 2, afternoon: 1 }))
  for (let k = 0; k < n; k++) {
    const h = hash(look.seed + k * 211)
    const dir = k % 2 ? 1 : -1
    const span = right + 16
    const x = Math.round(((((h % span) + dir * look.frame * 0.22) % span) + span) % span) - 8
    const crate = dim(mix([P.peach, P.blue, P.red, P.teal][h % 4]!, P.ink, 0.3), look)
    sprite(c, x, GROUND - 3, TRUCK, { b: crate, c: dim(P.rosewater, look), w: P.sapphire, o: P.crust }, dir > 0)
  }
}

export const harbor: Landscape = {
  name: 'harbor',
  ground: GROUND,

  backdrop: farShore,

  floor(c, look) {
    for (let x = 0; x < c.W; x++) {
      const plank = look.snowy ? (x % 4 === 0 ? P.wood : mix(P.snow, P.woodDark, 0.15)) : look.wet ? P.woodDark : x % 3 === 0 ? P.woodDark : P.wood
      c.set(x, GROUND, dim(plank, look))
      c.set(x, GROUND + 1, dim(P.woodDark, look)) // the pier's fascia
      if (x % 6 === 2) c.rect(x, WATER, 1, 2, dim(P.woodDark, look)) // pilings
    }
    for (let y = WATER; y < c.H; y++) {
      for (let x = 0; x < c.W; x++) {
        c.set(x, y, sea(look, y))
        if (Math.sin(x * 0.45 + look.frame * 0.18 + y * 1.7 + (look.seed % 7)) > 0.85) c.glow(x, y, mix(look.horizon, P.white, 0.4), 0.25 * (1 - look.night * 0.6))
      }
    }
  },

  size(kinds, index) {
    const style = styleOf(index)
    const cap = style === 2 ? GROUND - 1 : GROUND - 2
    return { width: BASE_W[style]! + Math.min(3, editsOf(kinds)), height: Math.min(cap, MIN_H[style]! + Math.round(Math.log2(kinds.length + 1) * 0.8)) }
  },

  gap(index) {
    return hash(index * 31) % 3
  },

  building(c, look, b) {
    const { x0, width: w } = b
    const style = styleOf(b.index)
    const y0 = GROUND - b.height
    const rr = style === 1 ? Math.min(3, Math.ceil(w / 2)) : style === 2 ? 2 : style === 4 ? 0 : 1
    const wall = shell(c, look, b, style, y0, rr)
    const mid = x0 + (w >> 1)
    const wood = dim(P.woodDark, look)
    const roof = dim(ROOFS[hash(b.index * 5) % ROOFS.length]!, look)
    if (style === 0) {
      c.rect(mid - 1, GROUND - 3, 2, 3, wood) // a loading door and a hoist beam
      c.set(mid, GROUND - 2, dim(P.wood, look))
      c.rect(x0 - 2, y0, 2, 1, dim(P.wood, look))
      c.set(x0 - 2, y0 + 1, P.overlay1)
      c.set(x0 - 2, y0 + 2, P.overlay1)
    } else if (style === 1) {
      c.rect(x0 + w - 2, GROUND - 2, 1, 2, wood)
      const cx = x0 + 1
      c.set(cx, y0, mix(WALLS[0]!, P.ink, 0.3 + 0.3 * look.night))
      for (let k = 0; k < 3; k++) {
        const t = (look.frame + k * 7 + b.index * 3) % 21
        c.glow(cx + Math.round((t * look.wind) / 160), y0 - 1 - Math.floor(t / 5), P.text, 0.45 - t * 0.02) // smoke
      }
    } else if (style === 2) {
      c.rect(mid, GROUND - 2, 1, 2, wood)
      c.set(mid, y0 + rr, look.night > 0.4 ? P.yellow : P.rosewater) // the clock
      c.rect(mid, y0 - 2, 1, 2, P.overlay1)
      const flag = hash(b.index) % 2 ? P.red : P.blue
      for (let k = 1; k <= (look.wind > 20 ? 3 : 2); k++) c.set(mid + k, y0 - 2 + Math.round(wave(look.frame, 10, k * 2 + x0)), flag)
    } else if (style === 3) {
      const awning = AWNINGS[hash(b.index * 3) % AWNINGS.length]!
      for (let x = x0; x < x0 + w; x++) {
        c.set(x, y0 + 1, dim(x % 2 ? awning : P.rosewater, look))
        if ((x - x0) % 2 === 0) c.set(x, y0 + 2, dim(awning, look))
      }
      c.rect(x0 + w - 2, GROUND - 2, 1, 2, wood)
      c.rect(x0, GROUND - 2, 2, 2, dim(P.peach, look)) // a crate of fish
    } else {
      c.set(mid + (((look.frame >> 4) + b.index) % 2), y0 - 1, roof) // a weathervane
      c.rect(mid, y0 - 2, 1, 2, P.overlay1)
    }
    if (b.isLive) scaffold(c, look, b, y0)
    const slots: [number, number][] = []
    const first = y0 + (style === 3 || style === 4 ? 2 : rr)
    for (let y = GROUND - 2; y >= first; y -= 2) {
      for (let x = x0 + 1; x <= x0 + w - 2; x += 2) if (!(style === 0 && y >= GROUND - 3 && x >= mid - 1 && x <= mid)) slots.push([x, y])
    }
    lightWindows(c, look, b, slots, wall)
    if (b.kinds.includes('fail') && look.frame % 10 < 5) c.set(x0 + w - 1, y0 - 1, P.red)
  },

  filler(c, look, x0, x1) {
    for (let cell = Math.floor(x0 / 6); cell * 6 < x1; cell++) {
      const h = hash(cell * 31 + look.seed)
      const x = cell * 6 + ((h >>> 8) % 2)
      const kind = h % 8
      const w = [3, 2, 2, 3, 4, 3, 2, 2][kind]!
      if (x >= x0 && x + w <= x1 && kind !== 7) decor(c, look, kind, x, h)
    }
  },

  jobs(c, look, jobs, right) {
    reflect(c, look) // the mirror comes first so boats and their wakes sit on top of it
    smallBoats(c, look)
    const count = Math.max(1, Math.floor((right - 14) / 20)) // berths: each boat keeps its own by who it is
    const berth = (right - 14) / count
    const boats = stations(jobs.filter(job => (job.kind ?? 'codex') === 'codex'), count).map(([job, slot]) => {
      const t = job.seed * 97
      const x = Math.round(4 + ((slot % count) + (Math.floor(slot / count) % 2) * 0.5) * berth + (job.seed % 5) + 3 * Math.sin(t * 0.04 + job.seed))
      const bob = Math.sin(t * 0.12 + job.seed) > 0.3 ? 1 : 0
      const y = GROUND - 1 + bob
      return { job, x, y, bob }
    })
    const crowded = jobs.length * 9 > right * Math.max(1, GROUND - 3)
    const overflow = crowded ? boats.splice(3).map(({ job }) => job) : []
    const packed = crowded ? packBoats(c, look, boats) : undefined
    for (const [i, { job, x, y, bob }] of boats.entries()) {
      const placed = packed ? packed[i] : placeBoat(c, look, x, y, job, crowded)
      if (placed && !bob) for (let k = 1; k < placed.w; k++) {
        const x = placed.x + k, y = SCENE_H - 1
        if (!(look.crewZones ?? []).some(z => x >= z.x && x < z.x + z.w && y >= z.y && y < z.y + z.h)) c.glow(x, y, jobAccent(job, P.teal), 0.2)
      }
      if (!placed) overflow.push(job)
    }
    airJobs(c, look, [...jobs.filter(job => (job.kind ?? 'codex') !== 'codex'), ...overflow], right)
  },

  foreground(c, look, right) {
    beam(c, look)
    if (look.phase === 'dawn') mist(c, look, look.frame, 0.7)
    people(c, look, right)
    trucks(c, look, right)
    for (let k = 0; k < 3; k++) {
      const x = 6 + (hash(look.seed + k * 17) % Math.max(1, right - 12))
      const y = WATER + 1 + (Math.sin(look.frame * 0.1 + k * 2) > 0 ? 1 : 0)
      c.rect(x, y, 2, 1, P.red)
      c.rect(x, y + 1, 2, 1, P.text)
      c.set(x, y + 2, P.red)
      if (k === 0 && look.night < 0.6) sprite(c, x, y - 2, ['gg.', '.gb'], { g: P.rosewater, b: P.peach }) // a gull rests on the first buoy
      if (look.night > 0.4 && (look.frame + k * 5) % 14 < 4) for (const [dx, dy, t] of [[0, -1, 0.8], [-1, 0, 0.3], [2, 0, 0.3]] as const) c.glow(x + dx, y + dy, P.yellow, t)
    }
    // the ferry shuttles across, alternating direction each lap
    const lap = look.W + 36
    const t = look.frame * 0.18 + (look.seed % 211)
    const pos = t % lap
    const dir = hash(look.seed + Math.floor(t / lap)) % 2 ? 1 : -1
    const fx = Math.round(dir > 0 ? pos - 18 : look.W + 18 - pos)
    sprite(c, fx, GROUND - 1, FERRY, { s: P.red, c: dim(P.rosewater, look), w: look.night > 0.3 ? P.yellow : P.sapphire, r: P.blue, h: P.surface1 }, dir < 0)
    for (let k = 1; k <= 5; k++) c.glow(fx + (dir > 0 ? -k : 11 + k), BASE, P.white, 0.55 - k * 0.1)
    if (look.night < 0.75) {
      const flock = Math.round(byPhase(look, { dawn: 5, morning: 5, noon: 6, afternoon: 5, dusk: 3 }))
      for (let k = 0; k < flock; k++) {
        const x = Math.round((look.frame * (0.3 + k * 0.07) + (hash(look.seed + k) % look.W)) % (look.W + 10)) - 5
        const gy = 1 + (k % 4) + Math.round(1.2 * Math.sin(look.frame * 0.1 + k * 2))
        sprite(c, x, gy, (look.frame + k * 2) % 8 < 4 ? GULL_UP : GULL_DOWN, { g: mix(P.rosewater, P.surface2, look.night) })
      }
    }
    if (look.wet) for (let k = 0; k < look.W / 10; k++) c.glow(hash(look.frame * 7 + k) % look.W, WATER + (hash(look.frame + k) % 4), P.white, 0.3)
  },

  events: [
    {
      name: 'cargo ship',
      frames: 260,
      weight: 3,
      draw(c, look, age, seed) {
        // a container ship crosses, bridge lit when dim, smoke trailing from the funnel
        const L = 32
        const dir = seed % 2 ? 1 : -1
        const x = Math.round(dir > 0 ? -L + (age / 260) * (c.W + L) : c.W - (age / 260) * (c.W + L))
        const at = (u: number) => (dir > 0 ? x + u : x + L - 1 - u)
        const dk = (color: number) => dim(color, look)
        for (let u = 0; u < L; u++) {
          c.set(at(u), BASE - 1, dk(0x2a2e3f))
          if (u > 0 && u < L - 3) c.set(at(u), BASE, dk(0x4a2a30))
          if (u >= 3 && u < 20) {
            const h = hash(seed + (u >> 1) * 5)
            for (let r = 0; r < 3; r++) if (r === 0 || (u >= 5 && u < 17 && (h >>> r) % 3)) c.set(at(u), BASE - 2 - r, dk([P.red, P.blue, P.peach, P.green, P.mauve, P.teal][(h >>> (r * 3)) % 6]!))
          }
          if (u >= 21 && u < 27) for (let y = BASE - 7; y < BASE - 1; y++) c.set(at(u), y, y % 2 && u % 2 ? (look.night > 0.3 ? P.yellow : P.sapphire) : dk(P.rosewater))
          if (u >= 27) c.set(at(u), BASE - 2, dk(P.surface1))
        }
        c.rect(at(23), BASE - 10, 2, 3, dk(P.red))
        for (let k = 0; k < 5; k++) c.glow(at(23) - dir * (k + 1), BASE - 11 - (k >> 1), P.text, 0.4 - k * 0.07)
        for (let k = 1; k < 6; k++) c.glow(at(-k), BASE, P.white, 0.55 - k * 0.1)
        if (look.night > 0.3) for (let u = 3; u < 27; u += 6) c.glow(at(u), SCENE_H - 1, P.yellow, 0.18) // lights on the water
      },
    },
    {
      name: 'whale',
      frames: 90,
      weight: 2,
      when: look => look.night < 0.6,
      draw(c, look, age, seed) {
        // a whale breaches in an arc, spray and rings where it leaves and re-enters
        const x0 = 12 + (seed % Math.max(1, c.W - 60))
        const p = age / 90
        const arc = (u: number) => [x0 + Math.round(u * 22), BASE - Math.round(11 * Math.sin(Math.PI * u))] as const
        if (p > 0.15 && p < 0.85) {
          const u = (p - 0.15) / 0.7
          for (let s = 0; s < 12; s++) {
            const [x, y] = arc(Math.max(0, u - s * 0.022))
            const fat = s < 2 ? 2 : s > 9 ? 0 : 1 // blunt head, tapering tail
            for (let dy = -fat; dy <= fat; dy++) if (y + dy < WATER) c.set(x, y + dy, dy < 0 ? 0x2f3f66 : dy > 0 ? P.white : 0x7d90bd)
          }
          const [tx, ty] = arc(Math.max(0, u - 0.28)) // tail flukes
          if (ty < WATER) for (const dx of [-2, -1, 1, 2]) c.set(tx + dx, ty - 1 - (Math.abs(dx) > 1 ? 1 : 0), 0x2f3f66)
        }
        for (const [at, pos] of [[0.15, 0], [0.85, 1]] as const) {
          const r = Math.round(Math.abs(p - at) * 18)
          const [sx] = arc(pos)
          if (r < 6) for (const dx of [-r, r]) c.glow(sx + dx, WATER, P.white, 0.7 - r * 0.1)
          if (Math.abs(p - at) < 0.1) for (let h = 1; h < 4; h++) c.glow(sx + (h % 2 ? 1 : -1), WATER - h - Math.round(Math.abs(p - at) * 8), P.white, 0.8)
        }
      },
    },
    {
      name: 'fishing fleet',
      frames: 260,
      weight: 2,
      when: look => look.night > 0.3,
      draw(c, look, age) {
        // trawlers come home with lanterns lit, bobbing, a lantern trail on the water
        for (let k = 0; k < 3; k++) {
          const x = Math.round(c.W + 4 - (age / 260) * (c.W + 16) + k * 14)
          const y = BASE - 5 - Math.round(0.5 + 0.5 * Math.sin(age * 0.12 + k * 2))
          sprite(c, x, y, TRAWLER, { l: P.yellow, m: P.overlay1, c: dim(P.rosewater, look), w: P.yellow, r: dim(HULLS[k % HULLS.length]!, look), h: dim(P.woodDark, look) }, true)
          const flick = (age + k * 3) % 7 < 5 ? 0.9 : 0.5
          for (const [dx, dy, t] of [[2, 0, 1], [1, 0, 0.3], [3, 0, 0.3], [2, -1, 0.3]] as const) c.glow(x + dx, y + dy, P.yellow, t * flick)
          c.glow(x + 2, SCENE_H - 1, P.yellow, 0.4 * flick)
          for (let w = 1; w <= 3; w++) c.glow(x + 10 + w, BASE, P.white, 0.5 - w * 0.12)
        }
      },
    },
    {
      name: 'regatta',
      frames: 240,
      weight: 2,
      when: look => look.night < 0.5,
      draw(c, look, age, seed) {
        // dinghies race across in a line, heeling a little, wakes behind them
        for (let k = 0; k < 4; k++) {
          const x = Math.round(-8 + (age / 240) * (c.W + 24) - k * 11)
          const y = BASE - 5 - (Math.sin(age * 0.2 + k * 2) > 0.6 ? 1 : 0)
          sprite(c, x, y, DINGHY, { m: P.overlay1, s: dim(SAIL_COLORS[(seed + k) % SAIL_COLORS.length]!, look), j: dim(SAIL_COLORS[(seed + k * 3 + 1) % SAIL_COLORS.length]!, look), h: dim(P.wood, look) })
          for (let w = 1; w <= 3; w++) c.glow(x - w, BASE, P.white, 0.55 - w * 0.12)
        }
      },
    },
    {
      name: 'fog horn',
      frames: 150,
      weight: 1,
      draw(c, look, age) {
        // mist drifts across the bay while the lighthouse sounds its horn in rings
        mist(c, look, age, Math.sin((age / 150) * Math.PI))
        const cx = lightX(look) + 1
        for (let k = 0; k < 3; k++) {
          const r = age * 0.35 - k * 5
          if (r < 0) continue
          const rr = r % 18
          for (let a = 0; a < 6.28; a += 0.3) c.glow(cx + Math.round(Math.cos(a) * rr * 1.3), FAR - 6 + Math.round(Math.sin(a) * rr * 0.8), P.white, 0.5 * (1 - rr / 18))
        }
      },
    },
  ],
}
