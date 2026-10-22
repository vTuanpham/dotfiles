import { type Canvas, hash, mix, sprite } from '../pixels'
import { type Building, byPhase, type DayPhase, type Landscape, type Look, P, SCENE_H, type Season, editsOf, foliage, heightFor, lightWindows, wave, jobAccent } from './kit'
import { airJobs } from './crew'

// Countryside: two rolling hills of crop stripes and hedgerows with a far windmill; each
// turn is a farm building (farmhouse, red barn, silo and shed, windmill, greenhouse); the
// live turn is under scaffolding. The day has a life: mist and a rooster at dawn, herds and
// a tractor at noon, golden fields and cows going home at dusk, a sleeping flock and a lit
// farm at night. Bridge jobs are fireflies over the fields.

const GROUND = SCENE_H - 4 // buildings stand on the row above; the meadow runs below
const BOTTOM = SCENE_H - 1
const HILLS: Record<Season, [number, number]> = { spring: [0x86b873, 0x5fa052], summer: [0x4d8350, 0x3a7040], autumn: [0xc2a455, 0x9a8240], winter: [0xd5dcea, 0xe9ecf6] }
const GRASS: Record<Season, number> = { spring: 0x5fb050, summer: 0x3f8040, autumn: 0xa08a3c, winter: 0xe3e7f3 }
const PLASTER = [0xe8d9c0, 0xd6c19c, 0xc7d2dc, 0xe3c4b0]
const SHINGLE = [0xa8503a, 0x7a4a3c, 0x5c6a7a, 0x8a5a3a]
const MIN_W = [7, 7, 7, 7, 8] // farmhouse, barn, silo and shed, windmill, greenhouse
const MIN_H = [6, 7, 7, 8, 6]
const WARM: Record<DayPhase, number> = { dawn: 0.2, morning: 0.04, noon: 0, afternoon: 0.05, dusk: 0.3, night: 0 }
/** Sheep, cows, hens out in the meadow in each part of the day. */
const FLOCK: Record<DayPhase, [number, number, number]> = { dawn: [2, 1, 0], morning: [3, 2, 3], noon: [5, 2, 3], afternoon: [4, 2, 2], dusk: [4, 2, 0], night: [4, 0, 0] }

/** A colour warmed by dawn and dusk light and sunk toward night blue (and a little by rain). */
const dim = (look: Look, color: number) => mix(mix(color, 0xf0a850, byPhase(look, WARM)), 0x10162a, look.night * 0.62 + (look.wet ? 0.1 : 0))
const pal = (look: Look, colors: Record<string, number>) => Object.fromEntries(Object.entries(colors).map(([k, v]) => [k, dim(look, v)]))
const styleOf = (index: number) => [0, 0, 0, 1, 1, 1, 2, 2, 3, 4][hash(index * 7 + 3) % 10]! // mills and greenhouses are rarer
const roofRows = (w: number) => Math.min(3, Math.ceil(w / 2))
const snowOr = (look: Look, color: number) => (look.snowy ? dim(look, P.snow) : color)
const ridge = (look: Look, x: number, layer: number) => Math.sin(x * (0.045 + layer * 0.035) + (look.seed % 97)) * 1.4 + Math.sin(x * 0.13 + (look.seed % 31) + layer * 3) * 0.8
/** A sprite standing with its feet on row `feet`. */
const put = (c: Canvas, look: Look, rows: readonly string[], colors: Record<string, number>, x: number, feet: number, flip = false) => sprite(c, x, feet - rows.length + 1, rows, pal(look, colors), flip)

/** A stepped pitched roof (flat-topped when wide) with its eave at yEave; snow fills it when snowy. */
function gable(c: Canvas, look: Look, x0: number, w: number, yEave: number, color: number) {
  for (let k = 0; k < roofRows(w); k++) {
    for (let x = x0 + k; x <= x0 + w - 1 - k; x++) {
      const inner = x > x0 + k && x < x0 + w - 1 - k
      c.set(x, yEave - k, look.snowy && (inner || k === roofRows(w) - 1) ? dim(look, P.snow) : (x + k) % 2 ? color : mix(color, P.ink, 0.14))
    }
  }
}

/** Smoke curling up from (x, y), drifting with the wind. */
function smoke(c: Canvas, look: Look, x: number, y: number, seed: number) {
  for (let i = 0; i < 4; i++) {
    const ph = ((look.frame >> 1) + i * 4 + seed) % 16
    c.glow(x + Math.round((ph * look.wind) / 50), Math.round(y - ph * 0.45), P.white, 0.6 * (1 - ph / 16))
  }
}

/** Walls with a shaded right edge, and dark panes where a window could light. */
function walls(c: Canvas, look: Look, x0: number, w: number, y0: number, color: number, slots: [number, number][]) {
  const wall = dim(look, color)
  c.rect(x0, y0, w, GROUND - y0, wall)
  for (let y = y0; y < GROUND; y++) c.set(x0 + w - 1, y, mix(wall, P.ink, 0.2))
  for (const [x, y] of slots) c.set(x, y, mix(wall, 0x1a2540, 0.6))
  return wall
}

/** lightWindows, but safe for a structure with no slots. */
const light = (c: Canvas, look: Look, b: Building, slots: [number, number][], wall: number) => slots.length && lightWindows(c, look, b, slots, wall)

const windowGrid = (x0: number, w: number, yTop: number, yLow: number) => {
  const slots: [number, number][] = []
  for (let y = yLow; y >= yTop; y -= 2) for (let x = x0 + 1; x < x0 + w - 1; x += 2) slots.push([x, y])
  return slots
}

function farmhouse(c: Canvas, look: Look, b: Building) {
  const { x0, width: w } = b
  const r = roofRows(w)
  const wallTop = GROUND - b.height + r
  const slots = windowGrid(x0, w, wallTop, GROUND - 3)
  const door = x0 + (w >> 1)
  const wall = walls(c, look, x0, w, wallTop, PLASTER[hash(b.index) % 4]!, slots)
  gable(c, look, x0, w, wallTop - 1, dim(look, SHINGLE[hash(b.index >> 1) % 4]!))
  const lit = look.night > 0.4 || look.phase === 'dawn'
  for (const y of [GROUND - 2, GROUND - 1]) c.set(door, y, lit ? P.peach : dim(look, P.wood))
  if (lit) c.glow(door, GROUND, P.yellow, 0.4)
  for (const dx of [-1, 1]) c.set(door + dx, GROUND - 1, dim(look, mix(wall, P.green, 0.25))) // shrubs
  const chim = x0 + w - 3
  for (const dy of [4, 5]) c.set(chim, wallTop - dy, dim(look, 0x8a4a3c))
  if (b.index % 2 === 0 || b.isLive || lit) smoke(c, look, chim, wallTop - 6, b.index)
  slots.push([x0 + ((w - 1) >> 1), wallTop - 2]) // the attic window
  light(c, look, b, slots, wall)
}

function barn(c: Canvas, look: Look, b: Building) {
  const { x0, width: w } = b
  const wallTop = GROUND - b.height + roofRows(w)
  const slots = windowGrid(x0, w, wallTop, GROUND - 4)
  const wall = walls(c, look, x0, w, wallTop, 0xa8404a, slots)
  gable(c, look, x0, w, wallTop - 1, dim(look, 0x55506a))
  const dw = w >= 9 ? 4 : 3
  const dx = x0 + ((w - dw) >> 1)
  for (let i = 0; i < dw; i++) for (let j = 0; j < 3; j++) c.set(dx + i, GROUND - 3 + j, dim(look, i === 0 || i === dw - 1 || j === 0 || i === j ? P.rosewater : mix(wall, P.ink, 0.45))) // white-trimmed X door
  if (look.night > 0.4) c.glow(dx + (dw >> 1), GROUND, P.yellow, 0.35)
  light(c, look, b, slots, wall)
}

function silo(c: Canvas, look: Look, b: Building) {
  const { x0, width: w } = b
  const sx = x0 + w - 4
  const top = GROUND - b.height
  const shed = w - 4
  const slots: [number, number][] = [[x0 + 1, GROUND - 3]]
  for (let y = GROUND - 3; y > top + 2; y -= 2) slots.push([sx + (y % 4 === 1 ? 1 : 2), y])
  const metal = dim(look, 0xaab6c6)
  for (let y = top + 1; y < GROUND; y++) {
    for (let i = 0; i < 4; i++) c.set(sx + i, y, i === 0 ? mix(metal, P.white, 0.2) : i === 3 ? mix(metal, P.ink, 0.3) : metal)
    if ((GROUND - y) % 3 === 0) for (let x = sx; x < sx + 4; x++) c.glow(x, y, P.ink, 0.18) // hoops
  }
  for (let i = 1; i < 3; i++) c.set(sx + i, top, snowOr(look, dim(look, 0x7a8494)))
  c.rect(x0, GROUND - 4, shed, 4, dim(look, 0x9a6a4a))
  for (let x = x0; x < x0 + shed; x++) c.set(x, GROUND - 5, snowOr(look, dim(look, 0x5c4a44))) // lean-to roof
  for (const y of [GROUND - 2, GROUND - 1]) c.set(x0 + shed - 2, y, dim(look, P.woodDark)) // door
  for (const [x, y] of slots) c.set(x, y, dim(look, mix(0x9a6a4a, 0x1a2540, 0.6)))
  light(c, look, b, slots, metal)
}

function mill(c: Canvas, look: Look, b: Building) {
  const half = (b.width - 1) >> 1
  const cx = b.x0 + half
  const top = GROUND - b.height
  const wall = dim(look, 0xe2d8c4)
  for (let y = top + 2; y < GROUND; y++) {
    const h = Math.min(half, 1 + ((y - top - 2) >> 1))
    for (let x = cx - h; x <= cx + h; x++) c.set(x, y, x === cx + h ? mix(wall, P.ink, 0.22) : (x + y) % 5 === 0 ? mix(wall, P.ink, 0.07) : wall)
  }
  const cap = snowOr(look, dim(look, 0xa0483a))
  c.rect(cx - 1, top + 1, 3, 1, cap)
  c.set(cx, top, cap)
  for (const y of [GROUND - 2, GROUND - 1]) c.set(cx, y, dim(look, P.woodDark))
  const slots: [number, number][] = []
  for (let y = GROUND - 4; y > top + 4; y -= 2) slots.push([cx, y])
  for (const [x, y] of slots) c.set(x, y, mix(wall, 0x1a2540, 0.6))
  light(c, look, b, slots, wall)
  // sails: fast while this turn is being worked on, otherwise turning with the wind
  const angle = b.index + look.frame * (b.isLive && look.working ? 0.3 : 0.02 + look.wind * 0.004)
  const hubY = top + 4
  for (let k = 0; k < 4; k++) {
    const a = angle + (k * Math.PI) / 2
    for (let r = 1; r <= 4; r++) {
      const x = cx + Math.round(Math.cos(a) * r)
      const y = hubY + Math.round(Math.sin(a) * r)
      if (y < GROUND - 1) c.set(x, y, dim(look, P.woodDark))
      if (r >= 2 && y < GROUND - 1) c.set(x + Math.round(-Math.sin(a)), y + Math.round(Math.cos(a)), dim(look, mix(P.rosewater, P.wood, 0.35))) // sail cloth
    }
  }
  c.set(cx, hubY, dim(look, P.wood))
}

function greenhouse(c: Canvas, look: Look, b: Building) {
  const { x0, width: w } = b
  const top = GROUND - b.height
  const glass = dim(look, mix(0x7fb8d8, look.horizon, 0.25))
  const frame = dim(look, mix(P.rosewater, P.overlay2, 0.4))
  for (let y = top + 2; y < GROUND; y++) for (let x = x0; x < x0 + w; x++) c.set(x, y, x === x0 || x === x0 + w - 1 || (x - x0) % 3 === 0 ? frame : (x + y) % 5 === 0 ? mix(glass, P.white, 0.25) : glass)
  for (let k = 0; k < 2; k++) for (let x = x0 + k; x < x0 + w - k; x++) c.set(x, top + 1 - k, snowOr(look, k ? frame : mix(frame, glass, 0.3)))
  for (let x = x0 + 1; x < x0 + w - 1; x++) {
    const h = hash(x + b.index * 31)
    c.set(x, GROUND - 1, dim(look, h % 3 ? 0x4a9a4a : P.red)) // tomatoes
    if (h % 2) c.set(x, GROUND - 2, dim(look, h % 5 ? 0x5ab05a : P.pink))
  }
  if (look.night > 0.3) for (let y = top + 2; y < GROUND; y++) for (let x = x0 + 1; x < x0 + w - 1; x++) c.glow(x, y, P.mauve, 0.22 * look.night) // grow lights
  const slots: [number, number][] = []
  for (let y = GROUND - 3; y >= top + 2; y -= 2) for (let x = x0 + 1; x < x0 + w - 1; x++) if ((x - x0) % 3) slots.push([x, y])
  light(c, look, b, slots, glass)
}

const STYLES = [farmhouse, barn, silo, mill, greenhouse]

/** A mast with planks, a jib hoisting a bucket, and a builder with a hammer: this turn is still going up. */
function scaffold(c: Canvas, look: Look, b: Building) {
  const top = GROUND - b.height
  const pole = dim(look, mix(P.wood, P.yellow, 0.35))
  const px = b.x0 + b.width
  const jib = Math.max(0, top - 2)
  for (let y = jib; y < GROUND; y++) c.set(px, y, pole)
  for (let x = px - 5; x < px; x++) c.set(x, jib, pole)
  const plank = GROUND - 4 * Math.max(1, Math.floor(b.height / 4))
  for (let y = GROUND - 4; y > top; y -= 4) for (let x = px - 3; x < px; x++) c.set(x, y, mix(pole, P.ink, 0.15))
  for (let y = top; y < GROUND; y++) for (let x = b.x0; x < b.x0 + b.width; x++) if ((x + y) % 3 === 0) c.glow(x, y, P.yellow, 0.12)
  c.set(px - 1, plank - 1, dim(look, P.blue)) // the builder
  c.set(px - 1, plank - 2, dim(look, P.peach))
  c.set(px - (look.frame % 6 < 3 ? 2 : 3), plank - 2 + (look.frame % 6 < 3 ? 0 : 1), dim(look, P.surface2)) // swinging hammer
  const tx = px - 2 - Math.round(wave(look.frame, 70) * 2)
  const bucket = top + 1 + Math.round(wave(look.frame, 36) * Math.max(0, b.height - 4))
  for (let y = jib + 1; y < bucket; y++) c.set(tx, y, dim(look, P.surface2))
  c.set(tx, bucket, dim(look, P.peach))
  c.set(tx - 1, bucket, dim(look, P.surface1))
  if (look.frame % 8 < 4) c.set(px, jib - 1, P.red)
}

const SHEEP = ['.wwww..', 'wwwwwkk', 'wwwwwk.', '.k..k..']
const SHEEP_GRAZE = ['.wwww..', 'wwwwww.', 'wwwwwkk', '.k..k..']
const SHEEP_LYING = ['.wwww.', 'wwwwwk']
const COW = ['kwwwwk..', 'wwkwwwhh', 'wwwwwkhn', 'l.l..l..', 'l.l..l..']
const COW_GRAZE = ['kwwwwk..', 'wwkwww..', 'wwwwwwhh', 'l.l..lhn', 'l.l..l..']
const HEN = ['...r', '.bbh', 'bbbb', '.y.y']
const HEN_PECK = ['....', '..bb', 'bbbr', '.y.y']
const FARMER = ['hhh', '.f.', 'bbb', '.bp', 'k.k']
const ROOSTER = ['.....r', '....oy', 'ttoooo', '.tooo.', '..y.y.']
const SCARECROW = ['.hhh.', '..f..', 'ssbss', '..b..', '..w..']
const TRACTOR = ['..rrrr.e..', '..gggr.e..', '.kkkrrrrr.', 'kkukkrrrkk', 'kuuukrrkuk', 'kkukk..kkk', '.kkk......']
const COLORS = { w: 0xf0ece4, k: 0x4a3a36, l: 0x3a3438, h: 0x7a5a48, n: 0xeba0ac, y: 0xe0b040, b: 0xb87b4f, r: 0xc83a3a, f: P.peach, s: 0xd8b84a, o: 0xc0602a, t: 0x2a6a5a, e: 0x3a3438, g: 0x8ab8c8, p: 0x8ab8c8 }

/** Where the scarecrow stands: foreground, shared with the crows event. */
const scarecrowX = (seed: number, W: number) => 12 + (hash(seed + 5) % Math.max(1, W - 50))

function foreground(c: Canvas, look: Look, right: number) {
  const span = Math.max(12, right - 12)
  const sx = scarecrowX(look.seed, c.W)
  put(c, look, SCARECROW, { ...COLORS, h: 0x6a5238, w: P.wood, b: 0x5a6a8a }, sx, BOTTOM - 2)
  // a short fence with the rooster on it at dawn and in the morning
  const fx = 6 + (hash(look.seed + 9) % span)
  for (let k = 0; k < 9; k++) {
    c.set(fx + k, BOTTOM - 2, snowOr(look, dim(look, 0x9a7a5a)))
    if (k % 3 === 0) for (const y of [BOTTOM - 1, BOTTOM - 2]) c.set(fx + k, y, snowOr(look, dim(look, P.wood)))
  }
  if (look.phase === 'dawn' || look.phase === 'morning') {
    const crow = look.frame % 40 < 14
    put(c, look, ROOSTER, COLORS, fx + 2, BOTTOM - 3)
    if (crow) for (let i = 0; i < 3; i++) c.glow(fx + 9 + i * 2, BOTTOM - 10 - ((look.frame >> 1) + i) % 3, i % 2 ? P.white : P.yellow, 0.8 - i * 0.15) // cock-a-doodle-doo
  }
  const [sheep, cows, hens] = [0, 1, 2].map(i => Math.round(byPhase(look, { dawn: FLOCK.dawn[i]!, morning: FLOCK.morning[i]!, noon: FLOCK.noon[i]!, afternoon: FLOCK.afternoon[i]!, dusk: FLOCK.dusk[i]!, night: FLOCK.night[i]! }))) as [number, number, number]
  const n = sheep + cows + hens
  for (const feet of [BOTTOM - 1, BOTTOM]) {
    for (let k = 0; k < n; k++) {
      const h = hash(look.seed + k * 53)
      const type = k < sheep ? 0 : k < sheep + cows ? 1 : 2
      if ((type === 2 || (h >> 9) & 1 ? BOTTOM : BOTTOM - 1) !== feet) continue
      const ph = look.frame * 0.012 + k * 2.1
      const home = look.phase === 'dusk' // the herd drifts home to the right
      const x = home ? Math.round((3 + (h % span) + look.frame * 0.05) % span) : 3 + (h % span) + Math.round(type === 2 ? 2 * Math.sin(ph * 3) : 4 * Math.sin(ph))
      const face = home || Math.cos(ph) >= 0
      const graze = !home && (look.frame + h) % 70 < 45
      if (look.phase === 'night' && type === 0) put(c, look, SHEEP_LYING, COLORS, x, feet, !face)
      else if (type === 0) put(c, look, graze ? SHEEP_GRAZE : SHEEP, COLORS, x, feet, !face)
      else if (type === 1) put(c, look, graze ? COW_GRAZE : COW, COLORS, x, feet, !face)
      else put(c, look, (look.frame + k * 7) % 14 < 4 ? HEN_PECK : HEN, COLORS, x, BOTTOM, !face)
    }
    if (feet === BOTTOM - 1 && look.phase === 'night') for (let k = 0; k < 2; k++) c.glow(8 + k * 50 + ((look.frame >> 2) % 6), BOTTOM - 4 - ((look.frame >> 2) % 3), P.white, 0.6) // sleeping z
  }
  if (look.phase === 'dawn' || look.phase === 'morning' || look.phase === 'dusk') {
    const x = Math.round((((hash(look.seed + 3) % span) + look.frame * 0.1) % span + span) % span)
    put(c, look, (look.frame >> 2) % 2 ? FARMER : FARMER.map((r, i) => (i === 4 ? '.k.' : r)), COLORS, x, BOTTOM, false)
  }
  if ((look.working || look.phase === 'noon' || look.phase === 'afternoon') && right > 60) {
    const t = look.frame * (look.working ? 0.02 : 0.012)
    const x = Math.round(right - 40 + 24 * Math.sin(t))
    const flip = Math.cos(t) < 0
    put(c, look, TRACTOR, { ...COLORS, r: 0xc83a3a, k: 0x26242a, u: 0xc8a040 }, x, BOTTOM - 1, flip)
    c.glow(x + (flip ? 7 : 2), BOTTOM - 8 - ((look.frame >> 1) % 3), P.white, 0.5)
    for (let i = 1; i < 6; i++) c.glow(x + (flip ? 10 + i : -i), BOTTOM - 1 - (i & 1), P.sand, 0.5 / i) // dust
  }
}

export const countryside: Landscape = {
  name: 'countryside',
  ground: GROUND,

  backdrop(c, look) {
    const [farHill, nearHill] = HILLS[look.season]
    const gold = look.season === 'winter' ? 0 : byPhase(look, { dusk: 0.25, afternoon: 0.08 })
    const patch = [0, 0x6a5a3a, 0xd8b84a, 0x9ac060] // plain, plowed, rapeseed, young crop
    const tops: number[] = []
    for (let x = 0; x < c.W; x++) {
      const top = 7 + Math.round(ridge(look, x, 0))
      tops.push(top)
      const ph = hash(Math.floor((x + (look.seed % 7)) / 9) + look.seed)
      const tint = look.season === 'winter' ? 0 : patch[ph % 4]!
      for (let y = top; y < GROUND; y++) {
        const stripe = ph & 8 ? y % 2 : (x + y) % 2
        const col = mix(mix(tint ? mix(farHill, tint, 0.3) : farHill, 0xe8b040, gold), P.white, y === top ? 0.14 : stripe ? 0.07 : 0)
        c.set(x, y, dim(look, mix(col, look.horizon, 0.22)))
      }
    }
    const far = dim(look, mix(farHill, P.ink, 0.45))
    const wx = 10 + (hash(look.seed + 2) % Math.max(1, c.W - 30))
    const wy = tops[wx]!
    for (let y = wy - 3; y < wy; y++) c.set(wx, y, far)
    for (let k = 0; k < 4; k++) c.set(wx + Math.round(Math.cos(look.frame * 0.08 + k * 1.57) * 2), wy - 3 + Math.round(Math.sin(look.frame * 0.08 + k * 1.57) * 2), far) // a far windmill
    const bx = 14 + (hash(look.seed + 4) % Math.max(1, c.W - 40))
    c.rect(bx, tops[bx]! - 1, 3, 2, far)
    c.set(bx + 1, tops[bx]! - 2, far)
    c.rect(bx + 3, tops[bx]! - 3, 1, 3, far) // a far barn and silo
    if (look.night > 0.3) c.set(bx + 1, tops[bx]!, P.yellow)
    for (let x = 0; x < c.W; x++) {
      const top = 9 + Math.round(ridge(look, x, 1) * 0.5)
      const hedge = hash(Math.floor((x + look.seed) / 5)) % 3 === 0
      for (let y = top; y < GROUND; y++) {
        const hedgeRow = hedge && y === top
        const col = hedgeRow ? foliage(look.season === 'winter' ? 'summer' : look.season, 1)[1] : (x * 3 + y) % 5 === 0 ? mix(nearHill, P.ink, 0.12) : nearHill
        c.set(x, y, dim(look, mix(hedgeRow && look.snowy ? mix(col, P.snow, 0.5) : col, 0xe8b040, gold)))
      }
    }
    const mist = look.wet ? 0 : byPhase(look, { dawn: 0.34, morning: 0.16 })
    if (mist) for (let y = 6; y < GROUND; y++) for (let x = 0; x < c.W; x++) c.glow(x, y, mix(look.horizon, P.white, 0.6), mist * wave(x * 4 + look.frame, 110, y * 9) * ((y - 5) / 6))
  },

  floor(c, look) {
    const grass = mix(GRASS[look.season], 0xe0b040, look.season !== 'winter' ? byPhase(look, { dusk: 0.15 }) : 0)
    const flower = look.season === 'spring' ? [P.pink, P.yellow, P.white] : look.season === 'summer' ? [P.yellow, P.white] : look.season === 'autumn' ? [0xd08a3a] : []
    for (let x = 0; x < c.W; x++) {
      const h = hash(x * 11 + look.seed)
      for (let y = GROUND; y < SCENE_H; y++) {
        const tuft = hash(h + y) % 6 === 0
        c.set(x, y, dim(look, mix(grass, y === GROUND ? P.white : P.ink, y === GROUND ? 0.1 : 0.07 * (y - GROUND) + (tuft ? 0.1 : 0))))
        if (hash(h + y * 3) % 31 === 0 && flower.length) c.set(x, y, dim(look, flower[(h >> 4) % flower.length]!))
      }
    }
  },

  size(kinds, index) {
    const style = styleOf(index)
    const width = MIN_W[style]! + Math.min(4, editsOf(kinds)) | (style === 3 ? 1 : 0)
    return { width, height: Math.min(GROUND - 2, Math.max(MIN_H[style]!, heightFor(kinds, 5, 10))) }
  },

  gap(index) {
    return hash(index * 31) % 3
  },

  building(c, look, b) {
    STYLES[styleOf(b.index)]!(c, look, b)
    if (b.kinds.includes('fail') && look.frame % 10 < 5) c.set(b.x0, GROUND - b.height - 1, P.red)
    if (b.isLive) scaffold(c, look, b)
  },

  filler(c, look, x0, x1) {
    const snow = dim(look, P.snow)
    for (let cx = Math.floor(x0 / 8) * 8; cx < x1; cx += 8) {
      const h = hash(cx * 5 + look.seed)
      const x = cx + ((h >> 8) % 2)
      const [l, d] = foliage(look.season, h >> 3)
      const colors = { l, d, t: P.woodDark, y: 0xd9b24a, z: 0xa88a30 }
      const fits = (w: number) => x >= x0 && x + w <= x1
      const draw = (rows: string[]) => {
        if (!fits(rows[0]!.length)) return
        put(c, look, rows, colors, x, GROUND - 1)
        if (look.snowy) c.set(x + (rows[0]!.length >> 1), GROUND - rows.length, snow)
      }
      const kind = h % 9
      if (kind < 3) draw(['..lll..', '.lllld.', 'lllllld', 'llllddd', '.lddddd', '..ddd..', '...t...', '...t...'])
      else if (kind === 3) draw(['.lll.', 'lllld', 'llddd', '.ddd.', '..t..', '..t..'])
      else if (kind === 4) draw(['.l.', 'lld', 'lld', 'lld', 'ldd', 'ldd', '.d.', '.t.']) // a poplar
      else if (kind === 5 && fits(8)) {
        for (let k = 0; k < 8; k++) {
          c.set(x + k, GROUND - 3, look.snowy ? snow : dim(look, 0x9a7a5a))
          if (k % 3 === 0) for (const y of [GROUND - 2, GROUND - 1]) c.set(x + k, y, look.snowy && y === GROUND - 2 ? snow : dim(look, P.wood))
        }
      } else if (kind === 6) draw(look.season === 'autumn' || look.season === 'summer' ? ['..y..', '.yyy.', 'yyzyy'] : ['.l.', 'lld'])
      else if (kind === 7) draw(look.season === 'autumn' ? ['.yy', 'yzy', 'yyy'] : ['.ll', 'lld'])
    }
  },

  jobs: airJobs,

  foreground,

  events: [
    {
      name: 'train',
      frames: 110,
      weight: 3,
      draw(c, look, age, seed) {
        const dir = seed % 2 ? 1 : -1
        const x = Math.round((dir > 0 ? age / 110 : 1 - age / 110) * (c.W + 40)) - 22
        const colors = [0x4a4a5a, P.peach, P.blue, P.peach, P.mauve]
        for (let k = 0; k < 19; k++) {
          const px = dir > 0 ? x + 18 - k : x + k // the engine leads
          if (k % 4 === 3) continue
          const car = colors[Math.floor(k / 4)]!
          c.set(px, 8, k < 3 ? dim(look, car) : look.night > 0.4 ? P.yellow : dim(look, car))
          c.set(px, 9, dim(look, k < 3 ? car : mix(car, P.ink, 0.35)))
        }
        const head = dir > 0 ? x + 18 : x
        for (let k = 0; k < 4; k++) c.glow(head - dir * (k * 2 + 2), 6 - (k >> 1), P.white, 0.6 - k * 0.13)
      },
    },
    {
      name: 'combine',
      frames: 300,
      weight: 2,
      when: look => look.night < 0.6 && (look.season === 'summer' || look.season === 'autumn'),
      draw(c, look, age, seed) {
        const dir = seed % 2 ? 1 : -1
        const x = Math.round((dir > 0 ? age / 300 : 1 - age / 300) * (c.W + 30)) - 15
        const rows = ['..cccc.......', '..gggg.....y.', '..ggggbbbbbyy', 'bbbbbbbbbbbyy', 'bbbbbbbbbbbbb', '.kkk....kkk..']
        put(c, look, rows, { c: 0xa83a2a, g: 0x8ab8c8, b: 0xd8902a, k: 0x26242a, y: 0xe8d070 }, x, BOTTOM - 1, dir < 0)
        for (let r = 1; r < 5; r++) c.set(x + (dir > 0 ? 11 + ((r + look.frame) % 2) : 1 - ((r + look.frame) % 2)), BOTTOM - 6 + r, dim(look, (r + (look.frame >> 1)) % 2 ? 0xe0b040 : 0xa08030)) // the reel turns
        for (let i = 1; i < 7; i++) c.glow(x + (dir > 0 ? -i : 12 + i), BOTTOM - 2 - ((look.frame + i * 2) % 4), 0xd8b84a, 0.8 / i) // chaff
      },
    },
    {
      name: 'fox',
      frames: 130,
      weight: 2,
      when: look => look.night > 0.15,
      draw(c, look, age, seed) {
        const t = age / 130
        const p = t < 0.4 ? (t / 0.4) * 0.45 : t < 0.6 ? 0.45 : 0.45 + ((t - 0.6) / 0.4) * 0.55
        const dir = seed % 2 ? 1 : -1
        const x = Math.round((dir > 0 ? p : 1 - p) * (c.W - 40)) + 6
        const walking = t < 0.4 || t >= 0.6
        const gait = walking && look.frame % 4 < 2
        const rows = ['......o.o.', 'wooooooooon', '.oooooooo..', gait ? 'k.k....k.k.' : '.k.k..k.k.']
        sprite(c, x, BOTTOM - 3, rows, { o: mix(0xe0803a, 0x10162a, look.night * 0.3), w: P.white, n: 0x2a2428, k: 0x2a2428 }, dir < 0) // bright enough to spot at night
        if (look.night > 0.5) c.set(x + (dir > 0 ? 8 : 2), BOTTOM - 3, P.yellow) // eyeshine
      },
    },
    {
      name: 'crows',
      frames: 150,
      weight: 2,
      when: look => look.night < 0.35,
      draw(c, look, age, seed) {
        const sx = scarecrowX(look.seed, c.W)
        for (let k = 0; k < 4; k++) {
          const perch = [[sx - 3, BOTTOM - 7], [sx + 5, BOTTOM - 7], [sx - 6, BOTTOM - 2], [sx + 8, BOTTOM - 2]][k] as [number, number]
          const from = [(hash(seed + k) % 30) - 15 + sx, -3] as const
          const t = Math.min(1, age / 40) // fly in
          const out = Math.max(0, (age - 105) / 40) // scatter
          const x = Math.round(from[0] + (perch[0] - from[0]) * t + out * (k % 2 ? 40 : -40))
          const y = Math.round(from[1] + (perch[1] - from[1]) * t - out * 18 + (t < 1 || out > 0 ? 0 : (age + k * 5) % 24 < 3 ? 1 : 0))
          const flap = (t < 1 || out > 0) && look.frame % 4 < 2
          c.set(x, y, 0x1a1a24)
          c.set(x + 1, y, 0x1a1a24)
          c.set(x + (k % 2 ? 2 : -1), flap ? y - 1 : y, 0x2a2a36)
          c.set(x + 1, y + 1, 0x2a2a36)
        }
      },
    },
  ],
}
