import { type Canvas, hash, mix, sprite } from '../pixels'
import { type Building, byPhase, type DayPhase, type Landscape, type Look, P, SCENE_H, editsOf, foliage, heightFor, lightWindows, wave, jobAccent } from './kit'
import { airJobs } from './crew'

// Forest: a misty ridge, a pine line and dark pines for depth, shafts of light through the
// day, a stream in front. Turns are log cabins, treehouses, fire-lookout towers and mossy
// cottages; the live one is a treehouse going up on a rope hoist. Deer drink at dawn and
// dusk, robins sing by day, a ranger sits at the campfire after dark, bridge jobs are
// fireflies among the trees.

const GROUND = SCENE_H - 4 // buildings stand on the row above; the bank and stream run below
const BANK = GROUND + 1
const BOTTOM = SCENE_H - 1
const MIN_W = [8, 8, 6, 7] // cabin, treehouse, lookout tower, cottage
const MIN_H = [6, 8, 8, 6]
const WARM: Record<DayPhase, number> = { dawn: 0.18, morning: 0.05, noon: 0, afternoon: 0.06, dusk: 0.3, night: 0 }
const FLOOR = { spring: 0x4f9a48, summer: 0x2f6a3a, autumn: 0x8a6a34, winter: 0xdde2f0 }

const dim = (look: Look, color: number) => mix(mix(color, 0xf0a050, byPhase(look, WARM)), 0x0c1424, look.night * 0.65 + (look.wet ? 0.1 : 0))
const pal = (look: Look, colors: Record<string, number>) => Object.fromEntries(Object.entries(colors).map(([k, v]) => [k, dim(look, v)]))
const styleOf = (index: number) => [0, 0, 0, 1, 1, 1, 2, 2, 3, 3][hash(index * 7 + 3) % 10]!
const roofRows = (w: number) => Math.min(3, Math.ceil(w / 2))
const snowOr = (look: Look, color: number) => (look.snowy ? dim(look, P.snow) : color)
const put = (c: Canvas, look: Look, rows: readonly string[], colors: Record<string, number>, x: number, feet: number, flip = false) => sprite(c, x, feet - rows.length + 1, rows, pal(look, colors), flip)
const light = (c: Canvas, look: Look, b: Building, slots: [number, number][], wall: number) => slots.length && lightWindows(c, look, b, slots, wall)

/** A stepped roof over x0..x0+w-1 with its eave at yEave; snow fills it when snowy. */
function gable(c: Canvas, look: Look, x0: number, w: number, yEave: number, color: number, moss = false) {
  for (let k = 0; k < roofRows(w); k++) {
    for (let x = x0 + k; x <= x0 + w - 1 - k; x++) {
      const inner = x > x0 + k && x < x0 + w - 1 - k
      const tone = moss && hash(x * 7 + k) % 3 === 0 ? mix(color, P.green, 0.35) : (x + k) % 2 ? color : mix(color, P.ink, 0.14)
      c.set(x, yEave - k, look.snowy && (inner || k === roofRows(w) - 1) ? dim(look, P.snow) : tone)
    }
  }
}

function smoke(c: Canvas, look: Look, x: number, y: number, seed: number) {
  for (let i = 0; i < 4; i++) {
    const ph = ((look.frame >> 1) + i * 4 + seed) % 16
    c.glow(x + Math.round((ph * look.wind) / 50), Math.round(y - ph * 0.45), P.white, 0.55 * (1 - ph / 16))
  }
}

const windowGrid = (x0: number, w: number, yTop: number, yLow: number) => {
  const slots: [number, number][] = []
  for (let y = yLow; y >= yTop; y -= 2) for (let x = x0 + 1; x < x0 + w - 1; x += 2) slots.push([x, y])
  return slots
}

/** Log walls (rows alternate), dark panes where a window could light. */
function logWalls(c: Canvas, look: Look, x0: number, w: number, y0: number, color: number, slots: [number, number][]) {
  const wall = dim(look, color)
  for (let y = y0; y < GROUND; y++) for (let x = x0; x < x0 + w; x++) c.set(x, y, x === x0 + w - 1 ? mix(wall, P.ink, 0.25) : y % 2 ? wall : mix(wall, P.ink, 0.13))
  for (const [x, y] of slots) c.set(x, y, mix(wall, 0x10182a, 0.65))
  return wall
}

function cabin(c: Canvas, look: Look, b: Building) {
  const { x0, width: w } = b
  const wallTop = GROUND - b.height + roofRows(w)
  const slots = windowGrid(x0, w, wallTop, GROUND - 3)
  const wall = logWalls(c, look, x0, w, wallTop, 0x8a5a3a, slots)
  gable(c, look, x0, w, wallTop - 1, dim(look, 0x4a4a3a), true)
  const door = x0 + (w >> 1)
  const lit = look.night > 0.4
  for (const y of [GROUND - 2, GROUND - 1]) c.set(door, y, lit ? P.peach : dim(look, P.woodDark))
  if (lit) c.glow(door, BANK, P.yellow, 0.4)
  for (let x = door - 2; x <= door + 2; x += 4) c.set(x, GROUND - 1, dim(look, P.woodDark)) // porch posts
  c.set(door - 1, GROUND - 3, dim(look, P.woodDark)) // porch roof
  c.set(door + 1, GROUND - 3, dim(look, P.woodDark))
  const chim = x0 + w - 3
  for (const dy of [4, 5]) c.set(chim, wallTop - dy, dim(look, 0x7a7a82))
  smoke(c, look, chim, wallTop - 6, b.index)
  slots.push([x0 + ((w - 1) >> 1), wallTop - 2])
  light(c, look, b, slots, wall)
}

function treehouse(c: Canvas, look: Look, b: Building) {
  const { x0, width: w } = b
  const top = GROUND - b.height
  const cx = x0 + (w >> 1)
  const [l, d] = foliage(look.season, b.index)
  const boxTop = top + 3
  const px0 = x0 + 1
  const pw = w - 2
  for (let dy = -3; dy <= 4; dy++) for (let dx = -(w >> 1) - 1; dx <= (w >> 1) + 1; dx++) {
    if ((dx * dx) / ((w / 2 + 1) ** 2) + (dy * dy) / 20 > 1 || top + 3 + dy < 0) continue
    const t = hash(cx + dx + (top + dy) * 31) % 5
    c.set(cx + dx, top + 3 + dy, dim(look, snowOr(look, t === 0 ? mix(l, P.white, 0.15) : dy > 1 || t === 1 ? d : l))) // canopy
  }
  const trunk = dim(look, 0x5a4034)
  for (let y = boxTop + 3; y < GROUND; y++) { c.set(cx, y, trunk); c.set(cx + 1, y, mix(trunk, P.ink, 0.25)); if (y > GROUND - 3) c.set(cx - 1, y, trunk) }
  c.set(cx + 2, GROUND - 1, mix(trunk, P.ink, 0.25))
  const wood = dim(look, 0x9a6a44)
  c.rect(px0, boxTop, pw, 3, wood)
  for (let x = px0 - 1; x <= px0 + pw; x++) c.set(x, boxTop + 3, dim(look, P.woodDark)) // the deck
  gable(c, look, px0 - 1, pw + 2, boxTop - 1, dim(look, 0x5a4a3a), true)
  for (let y = boxTop + 4; y < GROUND; y += 1) if (y % 2) c.set(px0 - 1, y, dim(look, P.sand)) // rope ladder
  c.set(px0 + pw, boxTop - 3, dim(look, P.red)) // a pennant
  const slots: [number, number][] = []
  for (let x = px0 + 1; x < px0 + pw - 1; x += 2) slots.push([x, boxTop + 1])
  slots.push([px0, boxTop + 3], [px0 + pw - 1, boxTop + 3], [cx, boxTop - 2]) // deck lanterns and the loft
  for (const [x, y] of slots.slice(0, -3)) c.set(x, y, mix(wood, 0x10182a, 0.65))
  light(c, look, b, slots, wood)
}

function tower(c: Canvas, look: Look, b: Building) {
  const { x0, width: w } = b
  const top = GROUND - b.height
  const wood = dim(look, 0x7a5a40)
  const roof = dim(look, 0x8a3a30)
  const cabTop = top + 2
  for (let y = cabTop + 3; y < GROUND; y++) {
    const inset = y < (GROUND + cabTop) / 2 ? 1 : 0 // legs lean in toward the top
    for (const x of [x0 + inset, x0 + w - 1 - inset]) c.set(x, y, wood)
    if (y % 3 === 0) for (let x = x0 + inset; x <= x0 + w - 1 - inset; x++) c.set(x, y, mix(wood, P.ink, 0.15)) // landings
    else if ((y + b.index) % 2) c.set(x0 + 1 + (y % 4), y, mix(wood, P.ink, 0.3)) // cross brace
  }
  c.rect(x0 + 1, cabTop, w - 2, 3, dim(look, 0x6a4a34))
  for (let x = x0 + 2; x < x0 + w - 2; x++) c.set(x, cabTop + 1, mix(dim(look, P.sky), look.horizon, 0.3))
  const slots: [number, number][] = []
  for (let x = x0 + 2; x < x0 + w - 2; x++) slots.push([x, cabTop + 1])
  for (let y = cabTop + 6; y < GROUND - 1; y += 3) slots.push([x0 + (w >> 1), y]) // landing lamps
  for (let x = x0; x < x0 + w; x++) c.set(x, cabTop - 1, snowOr(look, roof))
  for (let x = x0 + 1; x < x0 + w - 1; x++) c.set(x, cabTop - 2, snowOr(look, mix(roof, P.ink, 0.15)))
  const mid = x0 + (w >> 1)
  c.set(mid, cabTop - 3, dim(look, P.surface1))
  if (look.frame % 14 < 7) c.set(mid, cabTop - 4, look.night > 0.3 ? P.red : dim(look, P.peach))
  c.set(x0 + w - 1, GROUND - 1, dim(look, P.woodDark))
  light(c, look, b, slots, dim(look, 0x6a4a34))
}

function cottage(c: Canvas, look: Look, b: Building) {
  const { x0, width: w } = b
  const wallTop = GROUND - b.height + roofRows(w)
  const slots = windowGrid(x0, w, wallTop, GROUND - 3)
  const wall = dim(look, 0x9a948a)
  for (let y = wallTop; y < GROUND; y++) for (let x = x0; x < x0 + w; x++) c.set(x, y, (x * 3 + y * 5) % 4 === 0 ? mix(wall, P.ink, 0.15) : x === x0 + w - 1 ? mix(wall, P.ink, 0.22) : wall)
  for (const [x, y] of slots) {
    c.set(x, y, mix(wall, 0x10182a, 0.65))
    if (y === GROUND - 3) c.set(x, y + 1, dim(look, hash(x * 3 + b.index) % 2 ? P.pink : P.yellow)) // a flower box
  }
  gable(c, look, x0, w, wallTop - 1, dim(look, 0x4f8a3f), true)
  const door = x0 + (w >> 1)
  for (const y of [GROUND - 2, GROUND - 1]) c.set(door, y, look.night > 0.4 ? P.peach : dim(look, 0x7a4a30))
  if (look.night > 0.4) c.glow(door, BANK, P.yellow, 0.4)
  if (!look.snowy) c.set(x0 + 2 + (b.index % 2), wallTop - 3, dim(look, hash(b.index) % 2 ? P.red : P.pink)) // a roof mushroom
  const chim = x0 + w - 3
  for (const dy of [4, 5]) c.set(chim, wallTop - dy, dim(look, 0x7a7a82))
  if (b.index % 2 === 0 || b.isLive) smoke(c, look, chim, wallTop - 6, b.index)
  slots.push([x0 + ((w - 1) >> 1), wallTop - 2])
  light(c, look, b, slots, wall)
}

const STYLES = [cabin, treehouse, tower, cottage]

/** The treehouse going up: a branch with a rope hoist lifting a plank, a builder, sawdust. */
function hoist(c: Canvas, look: Look, b: Building) {
  const top = GROUND - b.height
  const px = b.x0 + b.width
  const rope = dim(look, P.sand)
  const jib = Math.max(0, top - 1)
  for (let x = px - 5; x <= px; x++) c.set(x, jib, dim(look, P.woodDark))
  for (let y = jib; y < GROUND; y++) c.set(px, y, dim(look, mix(P.wood, P.yellow, 0.3)))
  const lift = wave(look.frame, 60)
  const load = top + 2 + Math.round(lift * Math.max(1, b.height - 5))
  const tx = px - 3
  for (let y = jib + 1; y < load; y++) c.set(tx, y, rope)
  const sway = Math.round(Math.sin(look.frame * 0.2))
  for (let k = -1; k <= 1; k++) c.set(tx + k + sway, load, dim(look, 0xb88a5a)) // the plank
  for (let y = top; y < GROUND; y++) for (let x = b.x0; x < b.x0 + b.width; x++) if ((x + y) % 4 === 0) c.glow(x, y, P.yellow, 0.1)
  for (let i = 0; i < 3; i++) c.glow(b.x0 + 2 + ((look.frame + i * 5) % 6), top + 4 + ((look.frame >> 1) + i) % 4, P.sand, 0.5) // sawdust
  if (look.frame % 8 < 4) c.set(px, jib - 1, P.red)
}

// ── foreground sprites ─────────────────────────────────────────────────────

const DEER = ['.......a.a', '.......hhh', '........hn', '.......bb.', '.bbbbbbbb.', 'wbbbbbsbb.', '.l.l..l.l.', '.l.l..l.l.']
const DEER_WALK = ['.......a.a', '.......hhh', '........hn', '.......bb.', '.bbbbbbbb.', 'wbbbbbsbb.', 'l.l..l.l..', '.l.l..l.l.']
const DEER_DRINK = ['.bbbbbbb..', 'wbbbbsbbbb', '.l.l..lbbh', '.l.l..l.hh', '.l.l..l.hn', '.l.l..l.l.']
const RABBIT = ['...ee', '...hn', 'wbbbb', '.l.l.']
const RANGER = ['.hhh', '.ff.', 'bbbb', 'bbbk']
const COLORS = { a: 0xd8c8a0, h: 0xb98450, b: 0xa8703c, s: 0xd8b080, l: 0x6a4a30, w: P.white, n: 0x2a2428, e: 0xb08a68, f: P.peach, k: 0x3a4a6a, o: 0xc86a3a }
const PHASE_DEER: DayPhase[] = ['dawn', 'morning', 'dusk']

const plantX = (look: Look, k: number, right: number) => 4 + (hash(look.seed + k * 41) % Math.max(10, right - 8))

function foreground(c: Canvas, look: Look, right: number) {
  const night = look.night > 0.4
  // ferns and mushrooms along the bank
  for (let k = 0; k < Math.floor(right / 14); k++) {
    const x = plantX(look, k, right)
    const [l, d] = foliage(look.season === 'winter' ? 'summer' : look.season, k)
    if (k % 3 === 2) {
      const cap = night ? mix(P.teal, 0x10182a, 0.2 + 0.2 * wave(look.frame, 40, k * 9)) : dim(look, P.red)
      sprite(c, x, BANK - 1, ['rwr', '.s.'], { r: cap, w: night ? P.white : dim(look, P.white), s: dim(look, P.rosewater) })
      if (night) for (const [dx, dy] of [[-1, 0], [3, 0], [1, -1]] as const) c.glow(x + dx, BANK - 1 + dy, P.teal, 0.3)
    } else put(c, look, ['l.l.l', '.ldl.', '..d..'], { l, d }, x, BANK)
  }
  // the deer drinks at dawn, in the morning and at dusk
  if (PHASE_DEER.includes(look.phase) && right > 40) {
    const x = 10 + (hash(look.seed + 17) % Math.max(10, right - 36))
    put(c, look, DEER_DRINK, COLORS, x, BANK, (look.seed & 1) === 1)
    if (look.frame % 30 < 4) c.glow(x + 9, BOTTOM - 1, P.white, 0.5) // a ripple
  }
  // rabbits: hop now and then
  for (let k = 0; k < 2 + (look.seed % 2); k++) {
    if (look.phase === 'night' && k > 0) continue
    const slot = Math.floor(look.frame / 36) + k * 7
    const from = hash(look.seed + k * 11 + slot - 1) % 9
    const to = hash(look.seed + k * 11 + slot) % 9
    const t = Math.min(1, (look.frame % 36) / 6)
    const x = 6 + ((hash(look.seed + k * 61) % Math.max(10, right - 24)) + Math.round(from + (to - from) * t) - 4)
    const hop = t < 1 && from !== to ? Math.round(Math.sin(t * Math.PI) * 2) : 0
    put(c, look, RABBIT, COLORS, x, BANK - hop, to < from)
  }
  // songbirds on twigs by day, with a few notes at dawn and in the morning
  if (look.night < 0.3) for (let k = 0; k < 2; k++) {
    const x = 8 + (hash(look.seed + 77 + k) % Math.max(10, right - 20))
    const y = 5 + (k % 2) * 2
    for (let i = 0; i < 4; i++) c.set(x - 1 + i, y + 1, dim(look, P.woodDark))
    c.set(x, y, dim(look, P.red)); c.set(x + 1, y, dim(look, 0x7a5a3a)); c.set(x + 2, y - ((look.frame + k * 9) % 40 < 4 ? 1 : 0), dim(look, 0x7a5a3a))
    if ((look.phase === 'dawn' || look.phase === 'morning') && (look.frame + k * 13) % 20 < 12) c.glow(x - 1 + ((look.frame >> 2) % 3), y - 2 - ((look.frame >> 3) % 2), P.yellow, 0.85) // a note
  }
  if (look.phase === 'noon' || look.phase === 'afternoon') for (let k = 0; k < 2; k++) {
    const t = look.frame * 0.04 + k * 3
    const x = Math.round(30 + k * 70 + 14 * Math.sin(t * 0.7)) % Math.max(10, right)
    const y = 10 + Math.round(2 * Math.sin(t * 1.3))
    const wing = look.frame % 4 < 2
    c.set(x, y, [P.yellow, P.pink][k]!)
    c.set(x + 1, wing ? y - 1 : y, [P.peach, P.mauve][k]!)
  }
  if (look.phase === 'dusk') for (let k = 0; k < 2; k++) {
    const x = Math.round(((look.frame * (0.7 + k * 0.2) + k * 60) % (c.W + 10)) - 5)
    const y = 4 + k * 2 + Math.round(1.5 * Math.sin(look.frame * 0.3 + k))
    const up = look.frame % 4 < 2
    c.set(x, y, 0x1a1a24); c.set(x - 1, up ? y - 1 : y + 1, 0x1a1a24); c.set(x + 1, up ? y - 1 : y + 1, 0x1a1a24) // bats
  }
  // the campfire, with the ranger after dark
  const fx = Math.max(6, right - 14 - (look.seed % 9))
  const lit = look.night > 0.3 || look.working || look.phase === 'dawn' || look.phase === 'dusk'
  for (let k = 0; k < 5; k++) c.set(fx + k, BANK, dim(look, k === 2 ? P.woodDark : P.wood))
  c.set(fx - 1, BANK, dim(look, P.overlay0)); c.set(fx + 5, BANK, dim(look, P.overlay0))
  if (lit) {
    const f = hash(look.frame * 7 + fx) % 3
    sprite(c, fx + 1, BANK - 3, f ? ['.y.', 'yoy', 'ooo'] : ['y..', 'yoy', 'ooo'], { y: P.yellow, o: 0xe8803a })
    c.set(fx + 2, BANK - 1, P.white)
    for (let dx = -5; dx <= 7; dx++) for (let dy = 0; dy < 4; dy++) c.glow(fx + 2 + dx, BANK - dy, P.peach, 0.3 * look.night * (1 - Math.abs(dx) / 7) * (1 - dy / 4))
    c.glow(fx + 2 + ((look.frame >> 2) % 3) - 1, BANK - 5 - ((look.frame >> 1) % 3), P.peach, 0.8) // a spark
    if (look.night > 0.3) put(c, look, RANGER, { ...COLORS, h: 0x4a8a4a, b: 0xc86a3a }, fx + 7, BANK)
  } else smoke(c, look, fx + 2, BANK - 2, 3)
}

export const forest: Landscape = {
  name: 'forest',
  ground: GROUND,

  backdrop(c, look) {
    const ridge = (x: number, f: number) => Math.sin(x * f + (look.seed % 97)) * 1.6 + Math.sin(x * f * 2.7 + (look.seed % 31)) * 0.8
    const far = dim(look, mix(look.horizon, 0x3e6e6c, 0.5))
    const mid = dim(look, mix(0x2c5a44, look.horizon, 0.2))
    const dusk = byPhase(look, { dusk: 0.28, dawn: 0.2 })
    const speck = (x: number, y: number, base: number, seedPlus: number) => {
      const h = hash(x * 13 + y * 7 + seedPlus)
      if (look.season === 'winter') return h % 5 === 0 ? mix(base, P.snow, 0.5) : base
      if (look.season === 'summer' || h % 6) return base
      return mix(base, foliage(look.season, h >> 3)[0], 0.55)
    }
    for (let x = 0; x < c.W; x++) {
      const cell = Math.floor((x + 2) / 5)
      const top = 3 + Math.round(ridge(x, 0.04)) + hash(cell + look.seed) % 2 + Math.round(Math.abs(((x + 2) % 5) - 2) * 0.7)
      for (let y = top; y < GROUND; y++) c.set(x, y, mix(mix(far, look.horizon, 0.15 + 0.35 * ((y - top) / 8)), P.peach, dusk * (y === top ? 1 : 0.5)))
    }
    for (let x = 0; x < c.W; x++) {
      const cell = Math.floor(x / 6)
      const top = 6 + Math.round(ridge(x, 0.07) * 0.6) + (hash(cell * 3 + look.seed) % 3) + Math.round(Math.abs((x % 6) - 3) * 0.8)
      for (let y = top; y < GROUND; y++) c.set(x, y, y >= GROUND - 2 && (x % 6 === 3) ? dim(look, 0x3a2e2c) : speck(x, y, y > GROUND - 3 ? mix(mid, P.ink, 0.3) : mid, 1)) // trunks in the shade
      if (look.snowy) c.set(x, top, dim(look, mix(P.snow, mid, 0.3)))
    }
    for (let cx = 5 + (look.seed % 7); cx < c.W; cx += 13 + (hash(cx + look.seed) % 5)) { // dark pines, nearer
      const base = dim(look, mix(0x1c3a30, look.horizon, 0.08))
      for (let r = 0; r < 12; r++) {
        const half = Math.min(4, r >> 1)
        for (let x = cx - half; x <= cx + half; x++) c.set(x, GROUND - 12 + r, r % 2 && Math.abs(x - cx) === half ? mix(base, P.ink, 0.25) : base)
      }
    }
    // morning light in shafts, mist at dawn
    const beams = byPhase(look, { morning: 0.16, dawn: 0.1, afternoon: 0.1, noon: 0.06 })
    if (beams && !look.wet) for (let k = 0; k < 4; k++) {
      const bx = (hash(look.seed + k * 5) % c.W) + 0
      const pulse = 0.7 + 0.3 * wave(look.frame, 90, k * 23)
      for (let y = 0; y < GROUND; y++) for (let w = 0; w < 3; w++) c.glow(bx + Math.round(y * 0.6) + w, y, look.phase === 'noon' ? P.white : P.yellow, beams * pulse * (1 - y / 14))
    }
    if (look.night > 0.5) for (let k = 0; k < 2; k++) for (let y = 0; y < 9; y++) c.glow(Math.round(c.W * (0.3 + k * 0.4)) + Math.round(y * 0.4), y, P.blue, 0.06 * look.night) // moonlight
    const mist = look.wet ? 0 : byPhase(look, { dawn: 0.3, morning: 0.14 })
    if (mist) for (let y = 7; y < GROUND; y++) for (let x = 0; x < c.W; x++) c.glow(x, y, mix(look.horizon, P.white, 0.6), mist * wave(x * 5 + look.frame, 120, y * 7))
  },

  floor(c, look) {
    const moss = FLOOR[look.season]
    const water = mix(0x3a78a8, look.horizon, 0.15)
    for (let x = 0; x < c.W; x++) {
      const h = hash(x * 11 + look.seed)
      c.set(x, GROUND, dim(look, mix(moss, P.white, 0.08)))
      c.set(x, BANK, dim(look, mix(moss, P.ink, 0.15 + (h % 4 === 0 ? 0.1 : 0))))
      if (look.season === 'autumn' && h % 4 === 0) c.set(x, GROUND, dim(look, foliage('autumn', h >> 5)[0]))
      if (look.season === 'spring' && h % 19 === 0) c.set(x, GROUND, dim(look, P.pink))
      if (look.phase !== 'dawn' && look.night < 0.5 && !look.wet && hash(x * 7 + (look.frame >> 5)) % 9 === 0) c.glow(x, GROUND, P.yellow, 0.2) // dappled light
      for (const y of [BANK + 1, BOTTOM]) {
        const streak = !look.snowy && (x - (look.frame >> 1) * (y === BOTTOM ? 1 : 2) + y * 5 + (look.seed % 11)) % 11 < 3 // ripples run downstream
        c.set(x, y, dim(look, look.snowy ? mix(0xbdd3e6, P.white, 0.2 * (h % 3)) : mix(mix(water, look.horizon, y === BOTTOM ? 0 : 0.3), P.white, streak ? 0.3 : 0)))
      }
      if (!look.snowy && h % 29 === 0) c.set(x, BANK + 1, dim(look, P.overlay1)) // a stone
    }
  },

  size(kinds, index) {
    const style = styleOf(index)
    return { width: MIN_W[style]! + Math.min(3, editsOf(kinds)), height: Math.min(GROUND - 2, Math.max(MIN_H[style]!, heightFor(kinds, 5, 10))) }
  },

  gap(index) {
    return 3 + (hash(index * 31) % 3) // room for a tree between neighbours
  },

  building(c, look, b) {
    STYLES[styleOf(b.index)]!(c, look, b)
    if (b.kinds.includes('fail') && look.frame % 10 < 5) c.set(b.x0, GROUND - b.height - 1, P.red)
    if (b.isLive) hoist(c, look, b)
  },

  filler(c, look, x0, x1) {
    const cells: [number, number][] = []
    if (x1 - x0 < 8) cells.push([x0, x1 - x0])
    else for (let cx = Math.floor(x0 / 8) * 8; cx < x1; cx += 8) if (cx >= x0 && cx + 8 <= x1) cells.push([cx + (hash(cx + look.seed) % 2), 7])
    for (const [x, w] of cells) {
      const h = hash(x * 5 + look.seed)
      const [l, d] = foliage(look.season === 'winter' ? 'summer' : look.season, h >> 3)
      const night = look.night > 0.5
      const kind = w < 5 ? h % 3 : h % 8
      if (kind < 3 || (kind === 7 && w < 5)) {
        const half = Math.min(3, (w - 1) >> 1)
        const mid = x + half
        const rows = 6 + half
        for (let r = 0; r < rows; r++) {
          const hw = Math.min(half, r >> 1)
          for (let px = mid - hw; px <= mid + hw; px++) {
            const snow = look.snowy && r % 2 === 0 && px !== mid
            c.set(px, GROUND - rows - 1 + r, dim(look, snow ? P.snow : px < mid ? l : r % 2 && px === mid + hw ? mix(d, P.ink, 0.25) : d))
          }
        }
        for (const y of [GROUND - 1, GROUND - 2]) c.set(mid, y, dim(look, P.woodDark))
        if (look.snowy) c.set(mid, GROUND - rows - 1, dim(look, P.snow))
      } else if (kind === 3) {
        const mid = x + 2
        for (let y = GROUND - 8; y < GROUND; y++) c.set(mid, y, dim(look, hash(y + x) % 3 === 0 ? P.surface0 : P.rosewater)) // birch
        const [bl, bd] = foliage(look.season, h)
        sprite(c, x, GROUND - 11, ['.lll.', 'lllld', '.ddd.'], pal(look, { l: bl, d: bd }))
        if (look.season === 'winter') c.set(mid, GROUND - 11, dim(look, P.snow))
      } else if (kind === 4) put(c, look, ['l.l.l', '.ldl.', '..d..'], { l, d }, x, GROUND - 1)
      else if (kind === 5) {
        sprite(c, x, GROUND - 2, ['rwr', '.s.'], { r: dim(look, night ? P.teal : P.red), w: dim(look, P.white), s: dim(look, P.rosewater) })
        if (night) c.glow(x + 1, GROUND - 2, P.teal, 0.3)
      } else if (kind === 6) put(c, look, ['.bbbb.', 'ebbbbe'], { b: 0x6a4a34, e: 0xb08a68 }, x, GROUND - 1)
      else put(c, look, ['.rr', 'rrr'], { r: 0x7a7a82 }, x, GROUND - 1)
    }
  },

  jobs: airJobs,

  foreground,

  events: [
    {
      name: 'owl',
      frames: 200,
      weight: 3,
      when: look => look.night > 0.5,
      draw(c, look, age, seed) {
        const ox = 10 + (hash(seed) % Math.max(1, c.W - 30))
        for (let k = -4; k <= 4; k++) c.set(ox + k, 7, mix(0x5a4a3a, 0x10182a, look.night * 0.3)) // the branch
        const blink = age % 50 < 4
        const shown = age >= 12 && age <= 188 // the eyes open first, in the dark
        if (shown) sprite(c, ox, 3, ['e.e', 'bbb', 'bwb', 'bbb', '.k.'], { e: 0xa89a88, b: 0xa08e78, w: 0xe8dcc0, k: 0x6a5a4a })
        for (const dx of [0, 2]) {
          c.set(ox + dx, 4, blink ? 0x5a4a38 : P.yellow)
          if (!blink) for (const [gx, gy] of [[-1, 0], [1, 0], [0, -1], [0, 1]] as const) c.glow(ox + dx + gx, 4 + gy, P.yellow, 0.25)
        }
        if (!blink && shown) c.set(ox + 1 + Math.round(Math.sin(age * 0.06)), 4, 0x2a2018) // turning its head
      },
    },
    {
      name: 'deer',
      frames: 190,
      weight: 3,
      when: look => look.night < 0.8,
      draw(c, look, age, seed) {
        const t = age / 190
        const p = t < 0.4 ? (t / 0.4) * 0.45 : t < 0.6 ? 0.45 : 0.45 + ((t - 0.6) / 0.4) * 0.55
        const dir = seed % 2 ? 1 : -1
        const x = Math.round((dir > 0 ? p : 1 - p) * (c.W - 30)) + 6
        const walking = t < 0.4 || t >= 0.6
        put(c, look, walking ? (look.frame % 6 < 3 ? DEER : DEER_WALK) : DEER, COLORS, x, BANK, dir < 0)
        if (!walking && look.frame % 12 < 2) c.set(x + (dir > 0 ? 0 : 9), BANK - 3, dim(look, P.white)) // the white tail flicks
      },
    },
    {
      name: 'woodpecker',
      frames: 110,
      weight: 2,
      when: look => look.night < 0.4,
      draw(c, look, age, seed) {
        const tx = 14 + (hash(seed) % Math.max(1, c.W - 40))
        const fade = Math.min(1, age / 10, (110 - age) / 10)
        for (let y = 1; y < GROUND; y++) for (let k = 0; k < 2; k++) c.glow(tx + k, y, dim(look, k ? 0x4a3a2e : 0x6a5442), fade)
        const peck = age >= 22 && age < 88
        const t = age < 22 ? age / 22 : age >= 88 ? 1 + (age - 88) / 22 : 1
        const bx = Math.round(tx + 8 - 7 * Math.min(1, t) + Math.max(0, t - 1) * 30)
        const by = Math.round(4 - Math.sin(Math.min(1, t) * Math.PI) * 3 - Math.max(0, t - 1) * 8)
        const nod = peck && look.frame % 4 < 2 ? 1 : 0
        const bird = (x: number, y: number) => { c.set(x, y, 0x2a2a34); c.set(x + 1, y, 0x2a2a34) }
        if (!peck) { bird(bx, by); c.set(bx + 2, by - (look.frame % 4 < 2 ? 1 : 0), P.white); c.set(bx - 1, by, 0x2a2a34); return }
        c.set(tx + 2 - nod, 3, P.red) // the red cap
        c.set(tx + 3, 3, 0x2a2a34); c.set(tx + 3, 4, P.white); c.set(tx + 3, 5, 0x2a2a34); c.set(tx + 4, 6, 0x2a2a34); c.set(tx + 3, 6, P.white)
        if (nod) c.glow(tx - 1 - (look.frame % 3), 3 + (look.frame % 2), 0xc8a070, 0.8) // chips fly
      },
    },
    {
      name: 'glowing mushrooms',
      frames: 220,
      weight: 3,
      when: look => look.night > 0.6,
      draw(c, look, age, seed) {
        const mx = 8 + (hash(seed) % Math.max(1, c.W - 34))
        const pulse = 0.6 + 0.4 * wave(age, 40)
        for (let k = 0; k < 5; k++) {
          const x = mx + k * 5 + (hash(seed + k) % 2)
          const hgt = 2 + (hash(seed + k * 3) % 4)
          const cap = [P.teal, P.sky, P.mauve][k % 3]!
          const glowing = mix(0x10182a, cap, pulse)
          for (let y = 1; y < hgt; y++) c.set(x, BANK - y, mix(0x10182a, P.rosewater, 0.5))
          for (const dx of [-1, 0, 1]) c.set(x + dx, BANK - hgt, dx ? glowing : mix(cap, P.white, 0.4 * pulse))
          for (let dx = -3; dx <= 3; dx++) for (let dy = -2; dy <= 2; dy++) if (Math.abs(dx) + Math.abs(dy) < 4) c.glow(x + dx, BANK - hgt + dy, cap, 0.12 * pulse) // halo
          const rise = (age + k * 9) % 16
          c.glow(x + Math.round(Math.sin((age + k * 17) * 0.1) * 2), BANK - hgt - 1 - rise * 0.5, cap, 0.8 * (1 - rise / 16)) // drifting spores
        }
      },
    },
    {
      name: 'falling leaves',
      frames: 220,
      weight: 3,
      when: look => look.season === 'autumn',
      draw(c, look, age, seed) {
        for (let k = 0; k < 18; k++) {
          const h = hash(seed + k * 29)
          const y = Math.round(-2 + ((age * (0.07 + (h % 5) * 0.02) + (h >> 8) % 12) % 16))
          const x = Math.round((h >> 4) % c.W + Math.sin((age + k * 11) * 0.12) * 3 + age * look.wind * 0.003)
          c.set(x % c.W, y, foliage('autumn', h >> 3)[h % 2]!)
          if ((age + k) % 6 < 3) c.glow(x % c.W + 1, y, foliage('autumn', h >> 3)[0], 0.5)
        }
      },
    },
  ],
}
