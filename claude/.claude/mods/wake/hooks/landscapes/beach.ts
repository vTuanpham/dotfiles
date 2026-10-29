import { type Canvas, hash, mix, sprite } from '../pixels'
import { type Building, byPhase, KIND_COLOR, type Landscape, type Look, P, SCENE_H, editsOf, farTone, foliage, lightWindows, wave, jobAccent } from './kit'
import { airJobs, packBoats, placeBoat, stations } from './crew'

// Beach: a tropical shore. Turns are huts on the back of the sand (striped cabana, thatched
// bungalow, lifeguard tower, awning cafe, tiki bar); the sea rolls behind them with a far
// island and a green headland; palms, umbrellas and sandcastles fill the gaps. Bridge jobs
// are sailboats. Who is on the sand changes with the hour: joggers at dawn, swimmers in the
// morning, crowded umbrellas and volleyball at noon, a glowing sunset, bonfires at night.

const GROUND = SCENE_H - 5 // the sand where Mochi sits; huts stand on the row above
const SHORE = GROUND - 2 // the surf line
const HORIZON = 4
const FEET = SCENE_H - 1 // the sand row nearest the viewer
const STRIPES = [P.red, P.blue, P.green, P.mauve, P.pink, P.peach, P.teal]
const THATCH = [0xc9a24a, 0xb8923a, 0xa8832e]
const SKIN = [0xf0c8a0, 0xc68c5e, 0x8d5a3a, 0xf5d5b8]
const SUITS = [P.red, P.blue, P.yellow, P.pink, P.green, P.mauve, P.peach]
const MIN_H = [4, 5, 6, 5, 5] // cabana, bungalow, lifeguard tower, cafe, tiki bar
const BASE_W = [5, 6, 5, 6, 5]
const styleOf = (index: number) => hash(index * 7 + 3) % 5
const dim = (color: number, look: Look) => {
  const tint = mix(mix(color, 0xff8a4a, 0.18 * look.blend.dusk), P.pink, 0.12 * look.blend.dawn)
  return mix(tint, P.ink, 0.38 * look.night)
}
const sunPath = (look: Look) => (look.phase === 'dusk' ? look.W - 14 : look.phase === 'dawn' ? 8 : look.night > 0.6 ? Math.round(look.W * 0.3) : -99)
const isSea = (px: number) => (px & 255) - (px >> 16) > 40 // turquoise or blue: where a swimmer may be drawn

// Sprites face right: h head, s torso, t trunks, l legs; g gull; d dog; c crab.
const PERSON = ['.h.', 'sss', '.s.', '.t.', 'l.l']
const PERSON2 = ['.h.', 'sss', '.s.', '.t.', '.l.']
const SAILBOAT = ['....mf...', '...smjj..', '..ssmjjj.', '.sssmjjjj', 'hhhhhhhhh', '.hhhhhhh.']
const GULL_UP = ['g.g', '.g.']
const GULL_DOWN = ['.g.', 'g.g']
const DOG = ['t...ee', 'dddddd', 'dddddn', 'd.dd.d']
const DOG2 = ['t...ee', 'dddddd', 'dddddn', '.dd.dd']
const CRAB = ['c...c', '.ccc.', 'c.c.c']
const CRAB2 = ['c...c', '.ccc.', '.c.c.']
const SEAPLANE = ['...wwwww...', 'tfffkfffffp', '..o.....o..', '.ooooooooo.']

const person = (c: Canvas, look: Look, x: number, y: number, h: number, step: boolean) => {
  const skin = dim(SKIN[h % SKIN.length]!, look)
  sprite(c, x, y, step ? PERSON : PERSON2, { h: skin, s: (h >>> 3) % 3 ? dim(SUITS[(h >>> 5) % SUITS.length]!, look) : skin, t: dim(SUITS[(h >>> 9) % SUITS.length]!, look), l: skin })
}

/** The sea: depth gradient, rolling crests, glitter under the sun or moon; a far island and a green headland. */
function seaAndShore(c: Canvas, look: Look) {
  const glit = sunPath(look)
  for (let y = HORIZON; y < SHORE; y++) {
    const base = dim(mix(mix(0x1d6fa5, 0x3fc1c9, (y - HORIZON) / 4), look.horizon, 0.1 + byPhase(look, { dusk: 0.2, dawn: 0.25 })), look)
    const dy = y - HORIZON
    const glow = mix(mix(base, 0xff8a60, (0.6 - 0.12 * dy) * look.blend.dusk), 0xf8a8b8, (0.45 - 0.09 * dy) * look.blend.dawn)
    for (let x = 0; x < c.W; x++) {
      c.set(x, y, glow)
      if (Math.abs(x - glit) <= 1 + (y - HORIZON) && hash(x * 7 + y * 13 + (look.frame >> 2)) % 3 === 0) c.glow(x, y, look.night > 0.6 ? P.white : P.peach, look.night > 0.6 ? 0.55 : 0.8)
      else if (look.night > 0.5 && hash(x * 5 + y * 3 + (look.frame >> 3)) % 29 === 0) c.glow(x, y, P.white, 0.4) // moonlit glints
    }
  }
  for (let k = 0; k < 3; k++) {
    const y = HORIZON + 1 + Math.floor((look.frame / 9 + k * 2) % 5) // crests roll toward the shore
    for (let x = 0; x < c.W; x++) if ((x + k * 5 + y * 3) % 9 < 4) c.glow(x, y, P.white, 0.18 + 0.05 * (y - HORIZON))
  }
  const isle = 12 + (hash(look.seed) % Math.max(1, c.W - 50))
  const tone = farTone(look, 0)
  for (let k = 0; k < 14; k++) for (let y = HORIZON - Math.round(2.6 * Math.sin((k / 13) * Math.PI)); y < HORIZON; y++) c.set(isle + k, y, tone)
  for (const k of [3, 7, 10]) c.set(isle + k, HORIZON - 4 + (k % 2), mix(tone, foliage(look.season, look.seed)[1], 0.5)) // palm tufts on the island
  const sail = (look.frame * 0.02 + (hash(look.seed + 3) % c.W)) % c.W
  c.set(Math.round(sail), HORIZON - 1, mix(P.text, look.horizon, 0.3 + 0.5 * look.night)) // a far sail
  const green = mix(foliage(look.season, look.seed)[1], farTone(look, 1), 0.4)
  for (let x = 0; x < 26; x++) for (let y = SHORE - 1 - Math.round(7 - x * 0.27); y < SHORE; y++) c.set(x, y, green) // the headland
  for (const px of [3, 9, 15]) {
    const top = SHORE - 1 - Math.round(7 - px * 0.27)
    c.set(px, top - 1, green)
    c.set(px, top - 2, green)
    for (const dx of [-2, -1, 1, 2]) c.set(px + dx, top - 3 + (Math.abs(dx) > 1 ? 1 : 0), green) // silhouette palms
  }
}

/** A palm: a bent trunk, fronds that sway with the wind, coconuts. */
function palm(c: Canvas, look: Look, x: number, tall: number, h: number) {
  const trunk = dim(0x8a6a4a, look)
  const bend = h % 2 ? 1 : -1
  const cx = x + 2 + bend
  const cy = GROUND - 1 - tall
  for (let i = 0; i < tall; i++) c.set(i > tall / 2 ? cx : x + 2, GROUND - 1 - i, i % 2 ? trunk : mix(trunk, P.ink, 0.2))
  const sway = Math.round(Math.sin(look.frame * 0.08 + x) * Math.min(2, look.wind / 14))
  const [light, dark] = foliage(look.season, h)
  for (const [dx, dy] of [[0, -1], [-1, -1], [1, -1], [-2, -1], [2, -1], [-1, 0], [1, 0], [-2, 0], [2, 0], [-3, 0], [3, 0], [-3, 1], [3, 1], [-4, 2], [4, 2]] as const) {
    c.set(cx + dx + (Math.abs(dx) > 1 ? sway : 0), cy + dy, dim(dy < 0 ? light : dark, look))
    if (look.snowy && dy < 0) c.set(cx + dx, cy + dy, P.snow)
  }
  c.set(cx, cy + 1, dim(P.woodDark, look))
  c.set(cx + 1, cy + 1, dim(P.woodDark, look))
}

/** A bit of beach clutter, stable for its column: palms, umbrellas, sandcastles, boards, chairs. */
function decor(c: Canvas, look: Look, kind: number, x: number, h: number) {
  const base = GROUND - 1
  const day = look.phase === 'morning' || look.phase === 'noon' || look.phase === 'afternoon'
  const open = day && !look.wet && (look.phase !== 'morning' || h % 2 === 0)
  const col = STRIPES[h % STRIPES.length]!
  if (kind === 0 || kind === 3) palm(c, look, x, 5 + (h >>> 4) % 3, h)
  else if (kind === 1) {
    for (let y = base - 3; y <= base; y++) c.set(x + 2, y, dim(P.rosewater, look)) // pole
    if (open) {
      for (let k = 0; k < 5; k++) c.set(x + k, base - 4, dim(k % 2 ? P.rosewater : col, look))
      for (let k = 1; k < 4; k++) c.set(x + k, base - 3, dim(k % 2 ? col : P.rosewater, look))
      c.rect(x, base, 4, 1, dim(STRIPES[(h >>> 3) % STRIPES.length]!, look)) // a towel and someone on it
      c.set(x + 3, base, dim(SKIN[h % 4]!, look))
      c.set(x + 1, base, dim(SUITS[(h >>> 6) % SUITS.length]!, look))
    } else c.set(x + 2, base - 4, dim(col, look)) // furled
  } else if (kind === 2) {
    const sand = dim(mix(0xe6cc8f, P.ink, 0.15), look)
    sprite(c, x, base - 2, ['.f..', 'c.c.', 'cccc'], { f: P.red, c: sand })
    c.set(x + 1, base, mix(sand, P.white, 0.15))
    if (look.snowy) c.set(x, base - 1, P.snow)
  } else if (kind === 4) {
    for (let i = 0; i < 3; i++) c.rect(x + i, base - 3 - (i % 2), 1, 4 + (i % 2), dim(STRIPES[(h >>> (i * 3)) % STRIPES.length]!, look)) // surfboards
    c.rect(x, base - 1, 3, 1, dim(P.wood, look))
  } else if (kind === 5) {
    c.rect(x, base, 3, 1, dim(col, look))
    c.set(x + 2, base - 1, dim(P.rosewater, look))
    if (open) c.set(x, base - 1, dim(SKIN[h % 4]!, look))
  } else {
    const [light, dark] = foliage(look.season, h)
    c.rect(x, base - 1, 2, 2, dim(P.overlay1, look))
    c.rect(x + 2, base - 2, 2, 3, dim(dark, look))
    c.set(x + 3, base - 2, dim(light, look))
    if (look.season !== 'winter') c.set(x + 2, base - 1, dim(P.red, look)) // a hibiscus
  }
}

/** Roof rows, walls and the style's details; returns the wall colour for the windows. */
function hut(c: Canvas, look: Look, b: Building, style: number, y0: number) {
  const { x0, width: w } = b
  const base = GROUND - 1
  const col = STRIPES[hash(b.index * 3) % STRIPES.length]!
  const white = dim(P.rosewater, look)
  const thatch = THATCH[hash(b.index) % THATCH.length]!
  const roofCol = style === 1 || style === 4 ? thatch : col
  const rr = style === 0 ? 2 : style === 1 ? 3 : style === 4 ? 3 : 1
  const wallAt = (x: number, y: number) =>
    style === 0 ? ((x - x0) % 2 ? dim(mix(P.rosewater, col, 0.4), look) : dim(col, look))
    : style === 1 ? dim(mix(P.wood, P.sand, y % 2 ? 0.2 : 0.45), look)
    : style === 4 ? dim(mix(0xc9a24a, 0x7a5a2a, (x - x0) % 2 ? 0.2 : 0.55), look)
    : style === 3 ? dim(mix(P.rosewater, col, 0.45), look)
    : y === y0 + 3 ? dim(P.red, look) : dim(0x8fd0d4, look)
  for (let r = 0; r < rr; r++) {
    const inset = style === 1 ? 1 - r : style === 4 ? 2 - r : style === 0 ? 1 - r : -1
    for (let x = x0 + inset; x < x0 + w - inset; x++) {
      const fringe = style === 1 && r === 2 && (x - x0) % 3 === 0
      if (!fringe) c.set(x, y0 + r, look.snowy ? mix(P.snow, roofCol, 0.15 * r) : dim(r % 2 && style !== 0 ? mix(roofCol, P.ink, 0.2) : roofCol, look))
    }
  }
  const top = style === 2 ? y0 + 1 : y0 + rr
  const legs = style === 2 ? y0 + 5 : base + 1
  for (let y = top; y < Math.min(legs, base + 1); y++) for (let x = x0; x < x0 + w; x++) c.set(x, y, wallAt(x, y))
  if (style === 2) {
    for (const lx of [x0 + 1, x0 + w - 2]) for (let y = legs; y <= base; y++) c.set(lx, y, dim(P.wood, look))
    if (base - legs >= 1) for (let k = 0; k <= base - legs; k++) c.set(x0 + 2 + (k % 2), legs + k, dim(P.woodDark, look)) // cross brace
    c.rect(x0 + w - 1, y0 + 1, 1, base - y0, dim(P.woodDark, look)) // ladder
    c.rect(x0, y0 - 2, 1, 2, dim(P.overlay1, look))
    c.set(x0 + 1, y0 - 2 + Math.round(wave(look.frame, 10, x0)), dim(look.wind > 20 ? P.red : P.yellow, look)) // flag
    c.rect(x0 + w, y0 + 2, 1, 2, dim(P.red, look)) // rescue buoy
  } else if (style === 3) {
    for (let x = x0; x < x0 + w; x++) {
      c.set(x, y0 + 1, dim(x % 2 ? col : P.rosewater, look))
      if ((x - x0) % 2 === 0) c.set(x, y0 + 2, dim(col, look))
      else if (look.night > 0.2) c.set(x, y0 + 2, (look.frame + x * 3) % 12 < 8 ? P.yellow : P.pink) // string lights
    }
    c.rect(x0, base, 2, 1, dim(P.surface0, look)) // a chalkboard
    c.set(x0 + 1, base, dim(P.text, look))
  } else if (style === 4) {
    c.rect(x0 - 1, base - 2, 1, 3, dim(P.woodDark, look)) // a torch, lit toward evening
    if (look.night > 0.1) {
      c.set(x0 - 1, base - 3, (look.frame >> 1) % 3 ? P.peach : P.yellow)
      c.glow(x0 - 2, base - 3, P.peach, 0.3)
      c.glow(x0, base - 3, P.peach, 0.3)
    }
    c.rect(x0, base, w, 1, dim(P.woodDark, look)) // the bar
  } else if (style === 0) {
    c.rect(x0 + 2, base - 1, 1, 2, dim(P.woodDark, look)) // door
  } else {
    c.rect(x0, base - 1, 1, 2, dim(P.woodDark, look)) // veranda post and door
    c.rect(x0 + w - 2, base - 1, 1, 2, dim(P.woodDark, look))
  }
  const slots: [number, number][] = []
  const rows = style === 2 ? [y0 + 4, y0 + 2] : [GROUND - 2, GROUND - 4, GROUND - 6]
  for (const y of rows) if (y >= top + (style === 3 ? 2 : 0)) for (let x = x0 + 1; x <= x0 + w - 2; x += 2) slots.push([x, y])
  if (!slots.length) slots.push([x0 + 1, base - 1])
  if (b.kinds.includes('fail') && look.frame % 10 < 5) c.set(x0 + w - 1, y0 - 1, P.red)
  return { slots, wall: wallAt(x0 + 1, y0 + 2) }
}

/** The live turn: bamboo scaffold, a builder, string lights, a wooden crane carrying the newest call's crate. */
function scaffold(c: Canvas, look: Look, b: Building, y0: number) {
  const { x0, width: w } = b
  const bamboo = dim(0xb89a4a, look)
  for (let y = Math.max(0, y0 - 1); y < GROUND; y++) c.set(x0 - 1, y, bamboo)
  const py = GROUND - 4
  for (let x = x0 - 1; x <= x0 + w; x++) {
    c.set(x, py, mix(bamboo, P.ink, 0.15))
    if ((look.frame + x * 2) % 8 < 4) c.set(x, py + 1, (x + b.index) % 2 ? P.yellow : P.pink) // bunting lights
  }
  const wx = x0 + ((look.frame >> 2) % w)
  c.set(wx, py - 1, dim(P.peach, look))
  c.set(wx, py - 2, P.yellow)
  if (look.frame % 8 < 4) c.set(wx + 1, py - 1, P.overlay2) // the hammer
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

/** A campfire: logs, flames that lick up, sparks, a warm glow on the sand, two people sitting by it. */
function bonfire(c: Canvas, look: Look, x: number) {
  const y = FEET - 1
  c.rect(x - 2, y, 5, 1, dim(P.woodDark, look))
  for (let dx = -1; dx <= 1; dx++) {
    const h = 2 + (hash((look.frame >> 1) + dx * 7 + x) % 3) - (dx ? 1 : 0)
    for (let r = 0; r < h; r++) c.set(x + dx, y - 1 - r, r === 0 ? 0xffd25a : r === 1 ? 0xff8a1a : r < h - 1 ? 0xe5461a : 0xa8281a)
  }
  for (let k = 0; k < 2; k++) {
    const t = (look.frame * 0.5 + k * 5) % 9
    c.set(x - 1 + k * 2 + Math.round(Math.sin(t + k)), y - 4 - Math.round(t / 2), t < 7 ? P.yellow : P.peach)
  }
  for (let dy = -5; dy <= 1; dy++) for (let dx = -7; dx <= 7; dx++) {
    const d = Math.hypot(dx, dy * 1.6)
    if (d < 7.5) c.glow(x + dx, y + dy, 0xff8a2a, 0.3 * (1 - d / 7.5) * Math.max(0.4, look.night))
  }
  for (const side of [-1, 1]) {
    const px = x + side * 6
    const h = hash(x + side)
    sprite(c, px, y - 2, ['.h', 'bb', 'bb'], { h: mix(dim(SKIN[h % 4]!, look), 0xff8a2a, 0.5), b: mix(dim(SUITS[h % SUITS.length]!, look), 0xff8a2a, 0.15) })
  }
}

/** Umbrellas on the sand with towels and sunbathers: open and crowded at noon, furled at dusk. */
function umbrellas(c: Canvas, look: Look, right: number) {
  const n = look.wet ? 0 : Math.min(Math.round(byPhase(look, { morning: 2, noon: 7, afternoon: 5, dusk: 2 })), Math.floor(right / 14))
  for (let k = 0; k < n; k++) {
    const h = hash(look.seed * 3 + k * 577)
    const x = 5 + (h % Math.max(1, right - 12))
    const base = 13 + ((h >>> 6) % 2)
    const col = dim(STRIPES[(h >>> 9) % STRIPES.length]!, look)
    c.rect(x - 2, base + 1, 5, 1, dim(STRIPES[(h >>> 12) % STRIPES.length]!, look)) // towel
    c.rect(x, base - 3, 1, 4, dim(P.rosewater, look)) // pole
    if (look.phase === 'dusk') {
      c.set(x, base - 4, col)
      continue
    }
    for (let i = -3; i <= 3; i++) c.set(x + i, base - 4, dim(i % 2 ? P.rosewater : col, look))
    for (let i = -1; i <= 1; i++) c.set(x + i, base - 5, col)
    c.set(x - 1, base, dim(SKIN[h % 4]!, look)) // someone lies in the shade
    c.rect(x, base, 2, 1, dim(SUITS[(h >>> 15) % SUITS.length]!, look))
    c.set(x + 2, base, dim(SKIN[h % 4]!, look))
  }
}

/** Kites on the wind, held by someone on the sand. */
function kites(c: Canvas, look: Look, right: number) {
  if (look.phase !== 'morning' && look.phase !== 'noon' && look.phase !== 'afternoon') return
  for (let k = 0; k < (right > 100 ? 2 : 1); k++) {
    const h = hash(look.seed + k * 997)
    const holder = 14 + (h % Math.max(1, right - 40))
    const kx = holder + 9 + Math.round(5 * Math.sin(look.frame * 0.03 + k))
    const ky = 2 + k + Math.round(Math.sin(look.frame * 0.06 + k * 3))
    const col = STRIPES[h % STRIPES.length]!
    for (let t = 0; t < 14; t++) c.glow(Math.round(kx + (holder - kx) * (t / 14)), Math.round(ky + 2 + (FEET - 4 - ky - 2) * (t / 14)), P.white, 0.4) // the string
    for (const [dx, dy] of [[0, -1], [-1, 0], [0, 0], [1, 0], [0, 1]] as const) c.set(kx + dx, ky + dy, dx === 0 && dy === 0 ? P.white : col)
    for (let t = 0; t < 3; t++) c.set(kx - 1 + (t % 2) * 2 - 1, ky + 2 + t, col) // the tail
    person(c, look, holder, FEET - 4, h, look.frame % 12 < 6)
  }
}

/** Walkers and joggers on the sand, swimmers in the visible sea, a volleyball game, campfires: all by the hour. */
function beachLife(c: Canvas, look: Look, right: number) {
  const calm = look.wet ? 0.4 : 1
  const people = Math.min(Math.round(byPhase(look, { dawn: 3, morning: 4, noon: 7, afternoon: 6, dusk: 4 }) * calm), Math.floor(right / 15))
  for (let k = 0; k < people; k++) {
    const pair = look.phase === 'dusk' ? k >> 1 : k // couples stroll side by side at dusk
    const h = hash(look.seed * 7 + pair * 977)
    const jog = (look.phase === 'dawn' || look.phase === 'morning') && k % 2 === 0
    const dir = pair % 2 ? 1 : -1
    const x = Math.round((((h % right) + dir * look.frame * (jog ? 0.36 : 0.12)) % right + right) % right) + (look.phase === 'dusk' ? (k % 2) * 3 : 0)
    person(c, look, x, FEET - 4 - (pair % 3), hash(look.seed + k * 31), (look.frame >> (jog ? 1 : 2)) % 2 === 0)
    if (k === 0 && look.phase !== 'noon' && look.phase !== 'afternoon') {
      sprite(c, x + dir * 7, FEET - 3, (look.frame >> 1) % 2 ? DOG : DOG2, { d: dim(0xc08a50, look), t: dim(0xc08a50, look), e: dim(0x8a5a30, look), n: P.ink }, dir < 0) // a dog runs ahead
    }
  }
  const swimmers = Math.round(byPhase(look, { morning: 3, noon: 8, afternoon: 6, dusk: 1 }) * calm)
  for (let k = 0; k < swimmers; k++) {
    const h = hash(look.seed + k * 41)
    const x = Math.round(((h % right) + Math.sin(look.frame * 0.03 + k) * 5 + right) % right)
    const y = HORIZON + 2 + (h >>> 5) % 4
    if (!isSea(c.get(x, y))) continue
    const stroke = (look.frame + k * 3) % 8 < 4
    c.set(x, y, dim(SKIN[h % 4]!, look)) // head
    c.set(x, y - 1, dim(SUITS[(h >>> 9) % SUITS.length]!, look)) // swim cap
    c.set(x + (stroke ? 1 : -1), y, P.white) // the arm's splash
    c.set(x + (stroke ? 2 : -2), y + 1, mix(c.get(x, y + 1), P.white, 0.5))
  }
  if ((look.phase === 'noon' || look.phase === 'afternoon') && right > 60 && !look.wet) {
    const v = 14 + (hash(look.seed) % Math.max(1, right - 34))
    for (const px of [v, v + 9]) c.rect(px, FEET - 4, 1, 5, dim(P.woodDark, look))
    for (let x = v + 1; x < v + 9; x++) for (let y = FEET - 4; y <= FEET - 2; y++) if ((x + y) % 2) c.set(x, y, dim(P.rosewater, look))
    const t = (look.frame % 48) / 48
    const tri = t < 0.5 ? t * 2 : 2 - t * 2
    for (const [px, near] of [[v + 2, tri < 0.18], [v + 6, tri > 0.82]] as const) person(c, look, px, FEET - 4 - (near ? 2 : 0), px, look.frame % 6 < 3)
    const bx = v + 3 + Math.round(4 * tri)
    c.rect(bx, FEET - 7 - Math.round(3 * Math.sin(Math.PI * ((t * 2) % 1))), 2, 2, P.white)
    c.set(bx, FEET - 7 - Math.round(3 * Math.sin(Math.PI * ((t * 2) % 1))), P.red)
  }
  if (look.phase === 'night' || look.phase === 'dusk') {
    bonfire(c, look, 18 + (hash(look.seed + 1) % Math.max(1, right - 40)))
    if (look.night > 0.6 && right > 110) bonfire(c, look, Math.round(right * 0.8))
  }
  umbrellas(c, look, right)
  kites(c, look, right)
  const flock = look.night > 0.75 ? 0 : Math.round(byPhase(look, { dawn: 4, morning: 4, noon: 5, afternoon: 5, dusk: 3 }))
  for (let k = 0; k < flock; k++) {
    const x = Math.round((look.frame * (0.3 + k * 0.07) + (hash(look.seed + k) % look.W)) % (look.W + 10)) - 5
    sprite(c, x, 1 + (k % 3) + Math.round(1.2 * Math.sin(look.frame * 0.1 + k * 2)), (look.frame + k * 2) % 8 < 4 ? GULL_UP : GULL_DOWN, { g: mix(P.rosewater, P.surface2, look.night) })
  }
}

export const beach: Landscape = {
  name: 'beach',
  ground: GROUND,

  backdrop: seaAndShore,

  floor(c, look) {
    for (let y = SHORE; y < c.H; y++) {
      for (let x = 0; x < c.W; x++) {
        const h = hash(x * 13 + y * 7 + look.seed)
        let sand = mix(0xe6cc8f, 0xc9a66b, (y - SHORE) / 7)
        if (y === SHORE + 1 || (y === SHORE + 2 && look.wet)) sand = mix(sand, P.surface1, 0.2) // wet sand
        if (h % 11 === 0) sand = mix(sand, h % 2 ? P.white : P.sand, 0.18)
        if (y > GROUND + 1 && hash(x * 3 + look.seed) % 17 === 0 && (y === FEET - 1 || y === FEET - 2)) sand = mix(sand, P.woodDark, 0.18) // footprints
        c.set(x, y, dim(look.snowy ? mix(P.snow, sand, 0.2 + 0.15 * (h % 3)) : sand, look))
      }
    }
    const surge = wave(look.frame, 50) // the surf line breathes in and out
    for (let x = 0; x < c.W; x++) {
      const foam = Math.sin(x * 0.7 + look.frame * 0.1) > -0.35
      c.set(x, SHORE, dim(foam ? mix(P.white, 0x8fe3e6, 0.2) : 0x6fd2d8, look))
      if (surge > 0.55 && Math.sin(x * 0.5 - look.frame * 0.1) > 0.2) c.glow(x, SHORE + 1, P.white, look.isDay ? 0.45 : 0.25)
    }
  },

  size(kinds, index) {
    const style = styleOf(index)
    return { width: BASE_W[style]! + Math.min(3, editsOf(kinds)), height: Math.min(GROUND - 3, MIN_H[style]! + Math.round(Math.log2(kinds.length + 1) * 0.8)) }
  },

  gap(index) {
    return 2 + (hash(index * 31) % 4)
  },

  building(c, look, b) {
    const style = styleOf(b.index)
    const y0 = GROUND - b.height
    const { slots, wall } = hut(c, look, b, style, y0)
    if (b.isLive) scaffold(c, look, b, y0)
    lightWindows(c, look, b, slots, wall)
  },

  filler(c, look, x0, x1) {
    const fromLeft = x0 <= 0 // the open span at the left edge keeps its decor as turns arrive
    let x = fromLeft ? x0 : x1
    for (let n = 0; n < 24; n++) {
      const h = hash(look.seed + n * 131 + (fromLeft ? 0 : (x1 - x0) * 7))
      const kind = h % 8
      const w = [5, 5, 4, 5, 3, 3, 4, 2][kind]!
      const lo = fromLeft ? x : x - w
      if (kind === 7 || (fromLeft ? lo + w > x1 : lo < x0)) continue
      decor(c, look, kind, lo, h)
      x = fromLeft ? lo + w + 1 + ((h >>> 8) % 2) : lo - 1 - ((h >>> 8) % 2)
    }
  },

  jobs(c, look, jobs, right) {
    const count = Math.max(1, Math.floor((right - 14) / 20)) // each boat keeps its own stretch of sea by who it is
    const lane = (right - 14) / count
    const boats = stations(jobs.filter(job => (job.kind ?? 'codex') === 'codex'), count).map(([job, slot]) => {
      const t = job.seed * 97
      const x = Math.round(4 + ((slot % count) + (Math.floor(slot / count) % 2) * 0.5) * lane + (job.seed % 5) + 3 * Math.sin(t * 0.04 + job.seed))
      const y = HORIZON - (Math.sin(t * 0.12 + job.seed) > 0.3 ? 1 : 0)
      return { job, x, y }
    })
    const crowded = jobs.length * 9 > right * Math.max(1, GROUND - 3)
    const overflow = crowded ? boats.splice(3).map(({ job }) => job) : []
    const packed = crowded ? packBoats(c, look, boats) : undefined
    for (const [i, { job, x, y }] of boats.entries()) {
      const placed = packed ? packed[i] : placeBoat(c, look, x, y, job, crowded)
      if (placed) for (let k = 1; k < 4; k++) {
        const x = placed.x - k, wakeY = y + 6
        if (!(look.crewZones ?? []).some(z => x >= z.x && x < z.x + z.w && wakeY >= z.y && wakeY < z.y + z.h)) c.glow(x, wakeY, P.white, 0.5 - k * 0.12)
      }
      else overflow.push(job)
    }
    airJobs(c, look, [...jobs.filter(job => (job.kind ?? 'codex') !== 'codex'), ...overflow], right)
  },

  foreground(c, look, right) {
    beachLife(c, look, right)
    if (look.wet) for (let k = 0; k < look.W / 10; k++) c.glow(hash(look.frame * 7 + k) % look.W, HORIZON + (hash(look.frame + k) % 5), P.white, 0.3)
  },

  events: [
    {
      name: 'dolphin pod',
      frames: 130,
      weight: 3,
      when: look => look.night < 0.6,
      draw(c, look, age, seed) {
        // three dolphins leap in turn: blue-grey backs, pale bellies, a splash where each re-enters
        for (let k = 0; k < 3; k++) {
          const u = (age - k * 20) / 55
          const x0 = 20 + (seed % Math.max(1, c.W - 70)) + k * 11
          const at = (v: number) => [x0 + Math.round(v * 18), SHORE - Math.round(8 * Math.sin(Math.PI * v))] as const
          if (u > 0 && u < 1) {
            for (let s = 0; s < 7; s++) {
              const [x, y] = at(Math.max(0, u - s * 0.025))
              c.set(x, y, s === 0 ? 0x6c819f : 0x9fb3cc)
              c.set(x, y + 1, P.white)
              if (s === 3) c.set(x, y - 1, 0x4d5f80) // dorsal fin
            }
          }
          for (const [edge, v] of [[0, 0], [1, 1]] as const) {
            const d = Math.abs(u - edge) * 55
            const [sx] = at(v)
            if (d < 7) for (let q = 0; q < 3; q++) c.glow(sx + (q - 1) * (1 + Math.round(d / 3)), SHORE - 1 - ((d / 2) | 0) + q % 2, P.white, 0.8 - d * 0.1)
          }
        }
      },
    },
    {
      name: 'seaplane',
      frames: 220,
      weight: 2,
      when: look => look.night < 0.7,
      draw(c, look, age, seed) {
        // a seaplane glides in, skims the water leaving a wake, and takes off again
        const p = age / 220
        const dir = seed % 2 ? 1 : -1
        const x = Math.round(dir > 0 ? -12 + p * (c.W + 24) : c.W + 12 - p * (c.W + 24))
        const y = 2 + Math.round(5 * Math.max(0, 1 - Math.abs(p - 0.5) * 3.6))
        sprite(c, x, y, SEAPLANE, { w: dim(P.white, look), t: dim(P.red, look), f: dim(P.red, look), k: P.sky, p: (age >> 1) % 2 ? P.overlay1 : P.white, o: dim(0x2f3f66, look) }, dir < 0)
        if (y >= 6) for (let k = 1; k < 9; k++) c.glow(x + (dir > 0 ? -k : 11 + k), SHORE, P.white, 0.8 - k * 0.08)
        if (look.night > 0.3 && age % 10 < 5) c.set(x + (dir > 0 ? 5 : 5), y - 1, P.red)
      },
    },
    {
      name: 'beach ball',
      frames: 170,
      weight: 2,
      when: look => look.night < 0.7,
      draw(c, look, age, seed) {
        // a ball bounces along the sand with a child running after it
        const dir = seed % 2 ? 1 : -1
        const x = Math.round(dir > 0 ? -8 + (age / 170) * (c.W + 24) : c.W + 8 - (age / 170) * (c.W + 24))
        const y = FEET - 3 - Math.round(5 * Math.abs(Math.sin(age * 0.22)))
        const spin = (age >> 2) % 4
        for (let i = 0; i < 4; i++) c.set(x + (i & 1), y + (i >> 1), [P.red, P.white, P.blue, P.yellow][(i + spin) % 4]!)
        person(c, look, x - dir * 8, FEET - 4, seed + 5, age % 4 < 2)
        c.glow(x, FEET, P.ink, 0.25)
      },
    },
    {
      name: 'crab walk',
      frames: 190,
      weight: 2,
      draw(c, look, age) {
        // three crabs scuttle sideways across the sand, claws up
        for (let k = 0; k < 3; k++) {
          const x = Math.round(-6 + (age / 190) * (c.W + 12) * (0.8 + k * 0.2) - k * 14)
          sprite(c, x, FEET - 2 - (k % 2), age % 4 < 2 ? CRAB : CRAB2, { c: mix(0xe0603a, P.ink, 0.15 * look.night) })
          if (age % 8 < 4) c.set(x, FEET - 3 - (k % 2), mix(0xe0603a, P.ink, 0.15 * look.night)) // a claw raised
        }
      },
    },
    {
      name: 'turtles hatching',
      frames: 240,
      weight: 2,
      when: look => look.night > 0.5,
      draw(c, look, age, seed) {
        // hatchlings dig out of a nest and crawl to the moonlit sea, glinting
        const nx = 16 + ((seed * 7) % Math.max(1, c.W - 60))
        c.rect(nx - 2, FEET - 1, 5, 1, mix(0xc9a66b, P.ink, 0.35))
        c.set(nx - 1, FEET - 1, P.white)
        c.set(nx + 1, FEET - 1, P.white)
        for (let k = 0; k < 6; k++) {
          const t = (age - k * 22) / 90
          if (t < 0 || t > 1) continue
          const x = nx - 4 + k * 2 + Math.round(2 * Math.sin(t * 5 + k))
          const y = FEET - 1 - Math.round(t * 6)
          sprite(c, x, y, age % 6 < 3 ? ['.t.', 'ttt'] : ['.t.', 'tt.'], { t: 0x4f8f5f })
          for (const [dx, dy] of [[-1, 0], [3, 0], [1, -1]] as const) c.glow(x + dx, y + dy, P.white, 0.25)
        }
      },
    },
  ],
}
