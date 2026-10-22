import type { WakePulseKind } from '../../types'
import { type Canvas, hash, mix, sprite } from '../pixels'
import { type Building, byPhase, type Landscape, type Look, P, SCENE_H, editsOf, heightFor, lightWindows, wave, jobAccent, type Job } from './kit'
import { airJobs } from './crew'

// Desert: far mesas and rippled dunes; one structure per turn (adobe, domed, minaret, tent, stepped
// pueblo); an oasis, cacti and rocks; camels, robed people, a jeep, a roadrunner and tumbleweed in
// front. The day changes who is out: a camp at dawn, a market in the morning, an empty shimmering
// noon, a jeep, a silhouetted caravan at dusk, a fire and string lights at night.

const GROUND = SCENE_H - 4
const FEET = SCENE_H - 2 // the foreground's feet row; its shadow lies on the row below
type Rows = readonly string[]
type Pal = Record<string, number>
type Inner = { span: (y: number) => [number, number]; top: number } // a structure's window area

const HAZE: Record<Look['phase'], [number, number]> = { dawn: [0xe0a8c0, 0.32], morning: [0xffe2b0, 0.08], noon: [0xfff2d8, 0.2], afternoon: [0xffd9a0, 0.12], dusk: [0xff8a40, 0.32], night: [0, 0] }
const SHADOW: Record<Look['phase'], number> = { dawn: 5, morning: 4, noon: 0, afternoon: 3, dusk: 8, night: 0 }
/** A colour as the hour sees it: lavender haze at dawn, bleached at noon, orange at dusk, blue at night. */
const tint = (look: Look, col: number) => {
  // the haze blends with the hour: its strength and its colour weighted by each phase's share
  let a = 0
  let h = 0
  for (const phase of Object.keys(HAZE) as Look['phase'][]) {
    const [color, amount] = HAZE[phase]
    const weight = look.blend[phase] * amount
    if (weight > 0) h = a === 0 ? color : mix(h, color, weight / (a + weight))
    a += weight
  }
  return mix(mix(mix(col, h, a), look.horizon, 0.12 * (1 - look.night)), 0x142c70, 0.72 * look.night)
}
const sand = (look: Look, col: number) => (look.snowy ? mix(tint(look, col), P.snow, 0.4) : tint(look, col))
/** Figures go dark against the dusk glow. */
const fig = (look: Look, col: number) => mix(tint(look, col), 0x2a1830, byPhase(look, { dusk: 0.8, dawn: 0.3 }))
const sunSide = (look: Look) => (look.hour < 12 ? 1 : -1) // the sun climbs from the left: morning shadows fall right

function mesas(c: Canvas, look: Look) {
  const tone = mix(tint(look, 0x92504a), look.horizon, 0.35)
  for (let x = -(hash(look.seed) % 6), seg = 0; x < c.W; seg++) {
    const h = hash(look.seed + seg * 53)
    const w = h % 5 === 0 ? 3 : 7 + ((h >> 4) % 9)
    const ht = w === 3 ? 5 + ((h >> 9) % 2) : 3 + ((h >> 9) % 3)
    const top = GROUND - 2 - ht
    for (let y = top; y < GROUND; y++) {
      const r = y - top
      const ext = Math.min(2, Math.max(0, r - (ht - 3))) // the talus slope at the foot
      const band = r === 0 ? mix(tone, P.white, 0.15) : r % 3 === 2 ? mix(tone, 0x6a3a40, 0.25) : tone
      for (let k = -ext; k < w + ext; k++) if (!(r === 0 && w > 3 && (k === 0 || k === w - 1))) c.set(x + k, y, k >= w + ext - 1 ? mix(band, P.ink, 0.2) : band)
    }
    x += w + 3 + ((h >> 12) % 10)
  }
}

const ridge = (look: Look, x: number, far: boolean) => {
  const s = look.seed % 7
  const wob = 1.7 + 1.5 * Math.sin(x * (far ? 0.045 : 0.06) + s) + 1.1 * Math.sin(x * (far ? 0.12 : 0.17) + s * 2)
  return Math.min(GROUND - 3, GROUND - (far ? 5 : 3) - Math.max(0, Math.round(wob * 0.6)))
}

/** A dune layer: the face toward the sun is lit and rippled, the other shaded. */
function dunes(c: Canvas, look: Look, far: boolean) {
  const tone = far ? mix(sand(look, 0xe6c88e), look.horizon, 0.3) : sand(look, 0xd9a460)
  const shade = mix(tone, sand(look, 0x8a5a48), 0.4)
  for (let x = 0; x < c.W; x++) {
    const top = ridge(look, x, far)
    const lit = (ridge(look, x + 1, far) - ridge(look, x - 1, far)) * sunSide(look) <= 0
    for (let y = top; y < GROUND; y++) {
      const ripple = (y - top) % 3 === 1 && hash(x * 3 + y + (far ? 9 : 0)) % 3 !== 0
      c.set(x, y, y === top ? mix(tone, P.white, 0.3) : lit ? (ripple ? mix(tone, P.white, 0.12) : tone) : ripple ? mix(shade, P.ink, 0.12) : shade)
    }
  }
}

/** Heat shimmer: the rows near the ground wobble at noon and in the afternoon. */
function shimmer(c: Canvas, look: Look) {
  const amp = byPhase(look, { noon: 1, afternoon: 0.7 })
  if (!amp || look.wet) return
  for (let y = GROUND - 4; y < GROUND; y++) {
    const row = c.px.slice(y * c.W, (y + 1) * c.W)
    for (let x = 0; x < c.W; x++) {
      const dx = Math.round(amp * Math.sin(x * 0.35 + look.frame * 0.4 + y * 1.7) * ((y - GROUND + 5) / 4))
      c.set(x, y, row[Math.max(0, Math.min(c.W - 1, x + dx))]!)
    }
  }
}

const styleOf = (index: number) => hash(index * 7 + 3) % 5 // adobe, dome, minaret, tent, pueblo
const WALLS = [0xf0e6d0, 0xc56e50, 0xe8c27a, 0xa8c4cc, 0xb45a4a]

/** A lit, shaded and optionally round-cornered block standing on the ground. */
function box(c: Canvas, look: Look, x0: number, y0: number, w: number, h: number, wall: number, round = true) {
  for (let y = y0; y < y0 + h; y++) {
    for (let x = x0; x < x0 + w; x++) {
      if (round && y === y0 && (x === x0 || x === x0 + w - 1)) continue
      const base = y === y0 ? mix(wall, look.snowy ? P.snow : P.white, look.snowy ? 0.7 : 0.14) : y === GROUND - 1 ? mix(wall, P.ink, 0.12) : wall
      c.set(x, y, x === x0 ? mix(base, P.white, 0.16) : x === x0 + w - 1 ? mix(base, P.ink, 0.28) : base)
    }
  }
}

/** Round roof-beam ends along a roofline, jutting past the sides. */
function vigas(c: Canvas, look: Look, x0: number, y: number, w: number, sides = true) {
  for (let x = x0 + 1; x < x0 + w - 1; x += 2) c.set(x, y + 1, tint(look, 0x5a3b2c))
  if (sides) for (const x of [x0 - 1, x0 + w]) c.set(x, y + 1, tint(look, 0x5a3b2c))
}

const adobe = (c: Canvas, look: Look, b: Building, wall: number): Inner => {
  box(c, look, b.x0, GROUND - b.height, b.width, b.height, wall)
  vigas(c, look, b.x0, GROUND - b.height, b.width)
  return { span: () => [b.x0 + 1, b.x0 + b.width - 2], top: GROUND - b.height + 2 }
}

const dome = (c: Canvas, look: Look, b: Building, wall: number): Inner => {
  const d = Math.max(2, Math.round(b.width / 2))
  const top = GROUND - b.height
  const col = tint(look, [0xf1ead8, 0x3fa7a0, 0xd8b56a, 0x4f7fc0][hash(b.index + 2) % 4]!)
  const cx = b.x0 + (b.width - 1) / 2
  box(c, look, b.x0, top + d, b.width, b.height - d, wall, false)
  for (let x = b.x0; x < b.x0 + b.width; x++) {
    const k = (x - cx) / (b.width / 2)
    for (let y = top + d - Math.round(d * Math.sqrt(Math.max(0, 1 - k * k))); y < top + d; y++) c.set(x, y, k < -0.3 ? mix(col, P.white, 0.22) : k > 0.4 ? mix(col, P.ink, 0.25) : col)
  }
  c.set(Math.floor(cx), top - 1, tint(look, 0xe8c050))
  return { span: () => [b.x0 + 1, b.x0 + b.width - 2], top: top + d }
}

const minaret = (c: Canvas, look: Look, b: Building, wall: number): Inner => {
  const y0 = GROUND - b.height
  const cap = tint(look, 0x3fa7a0)
  c.set(b.x0 + 1, y0, tint(look, 0xe8c050))
  for (let x = b.x0; x < b.x0 + b.width; x++) c.set(x, y0 + 1, x === b.x0 ? mix(cap, P.white, 0.2) : cap)
  box(c, look, b.x0, y0 + 2, b.width, b.height - 2, wall, false)
  c.rect(b.x0 - 1, y0 + 4, b.width + 2, 1, mix(wall, P.ink, 0.3)) // the muezzin's balcony
  if (look.night > 0.4) c.glow(b.x0 + 1, y0, P.yellow, 0.4)
  return { span: () => [b.x0 + 1, b.x0 + b.width - 2], top: y0 + 4 }
}

const tent = (c: Canvas, look: Look, b: Building): Inner => {
  const y0 = GROUND - b.height
  const cx = b.x0 + (b.width - 1) / 2
  const stripe = tint(look, [0xb94a3e, 0x3e6aa8, 0xc9902e, 0x6a4a8a][hash(b.index) % 4]!)
  for (let y = y0; y < GROUND; y++) {
    for (let x = cx - (y - y0); x <= cx + (y - y0); x++) {
      const col = (x - b.x0) % 4 < 2 ? tint(look, 0xe8dcc0) : stripe
      c.set(x, y, x > cx ? mix(col, P.ink, 0.22) : x === cx - (y - y0) ? mix(col, P.white, 0.15) : col)
    }
  }
  c.set(cx, y0 - 1, tint(look, 0x6b4f3f))
  c.set(cx + 1 + Math.round(wave(look.frame, 12)), y0 - 1, tint(look, 0xc84a3e)) // a pennant in the wind
  return { span: y => [cx - (y - y0) + 1, cx + (y - y0) - 1], top: y0 + 1 }
}

const pueblo = (c: Canvas, look: Look, b: Building, wall: number): Inner => {
  const y0 = GROUND - b.height
  const low = Math.ceil(b.height * 0.55)
  const upW = b.width - 3
  box(c, look, b.x0, GROUND - low, b.width, low, wall)
  box(c, look, b.x0, y0, upW, b.height, wall)
  vigas(c, look, b.x0, y0, upW, false)
  vigas(c, look, b.x0 + upW, GROUND - low, 3)
  return { span: y => [b.x0 + 1, b.x0 + (y > GROUND - low ? b.width : upW) - 2], top: y0 + 2 }
}

const STYLES = [adobe, dome, minaret, tent, pueblo] as const

/** Window slots on every other row above the door, filled bottom-up by the turn's calls. */
function slotsIn(inner: Inner): [number, number][] {
  const out: [number, number][] = []
  for (let y = GROUND - 3; y > inner.top; y -= 2) for (let x = inner.span(y)[0]; x <= inner.span(y)[1]; x += 2) out.push([x, y])
  return out
}

/** The live turn's scaffold: a pole, a ladder, a plank, a mason hammering and a bucket on a rope. */
function scaffold(c: Canvas, look: Look, b: Building) {
  const [wood, plank] = [tint(look, 0x7a4a28), tint(look, 0xf0d9a0)]
  const [top, xr, swing] = [GROUND - b.height - 1, b.x0 + b.width, look.frame % 8 < 4]
  const py = Math.max(top, 4)
  for (let y = py; y < GROUND; y++) {
    c.set(xr, y, wood)
    c.set(b.x0 - 3, y, wood)
    c.set(b.x0 - 2, y, (GROUND - y) % 2 ? plank : wood) // ladder rails and rungs
  }
  for (let x = py === top ? b.x0 - 1 : xr - 3; x <= xr; x++) c.set(x, py, plank)
  sprite(c, xr - 2, py - 3, ['.h.', 'rrr', 'r.r'], { h: 0xd8503a, r: 0xf4eadc })
  c.set(xr - 3, py - 2 + (swing ? 0 : 1), plank) // the hammer
  if (!swing && look.frame % 16 < 8) c.set(xr - 4, py - 1, P.yellow) // a spark
  c.set(xr + 1, py + Math.round(wave(look.frame, 40) * (GROUND - 3 - py)), wood)
  if (look.night > 0.4) c.glow(xr - 3, py - 1, P.yellow, 0.35)
}

const cactusPal = (look: Look): Pal => ({
  g: tint(look, 0x5f9a5c), l: tint(look, 0x78b06e), d: tint(look, 0x3f7448), f: look.season === 'spring' ? P.pink : tint(look, 0xe0c050),
  r: tint(look, 0xa08068), s: tint(look, 0x6e5645), b: tint(look, 0x9a7447),
})
const SAGUARO = ['..f..', 'l.g.d', 'l.g.d', 'lgggd', '..g..', '..g..']
const SAGUARO_S = ['.g.', 'lgd', '.g.', '.g.']
const BARREL = ['.f.', 'lgd', 'lgd']
const ROCK = ['..rr.', '.rrrs', 'rrrss']
const ITEMS: Rows[] = [SAGUARO, BARREL, ROCK, SAGUARO_S, ['b.b', 'bbb'], SAGUARO]

function palm(c: Canvas, look: Look, x: number, ht: number, lean: number) {
  const [light, dark] = [tint(look, 0x5aa04a), tint(look, 0x2f6a38)]
  const [tx, ty, droop] = [x + lean, GROUND - ht - 1, wave(look.frame, 30, x * 3) + look.wind * 0.01 > 0.6 ? 1 : 0]
  for (let r = 0; r < ht; r++) c.set(x + Math.floor((r * lean) / ht), GROUND - 1 - r, tint(look, 0x7a5a3a))
  c.set(tx, ty - 1, light)
  for (let dx = -2; dx <= 2; dx++) c.set(tx + dx, ty, dx === 0 ? dark : light)
  for (const s of [-1, 1]) { c.set(tx + 3 * s, ty + 1 + droop, dark); c.set(tx + 2 * s, ty + 1, dark) }
  c.set(tx - 1, ty + 1, tint(look, 0x6b4f3f)) // a coconut
}

function oasis(c: Canvas, look: Look, x: number, w: number) {
  const water = tint(look, 0x4aa8c0)
  for (let k = 1; k < w - 1; k++) {
    const glint = hash(k * 13 + Math.floor(look.frame / 4)) % 9 === 0
    c.set(x + k, GROUND + 1, glint ? mix(water, P.white, 0.5) : water)
    if (k > 2 && k < w - 3) c.set(x + k, GROUND, glint ? mix(water, P.white, 0.5) : mix(water, P.white, 0.15))
  }
  for (const rx of [x, x + w - 1]) c.set(rx, GROUND + 1, tint(look, 0x7a9a4a)) // reeds
  palm(c, look, x + 2, 6, 2)
  palm(c, look, x + w - 5, 5, -1)
}

/** Cacti and rocks laid from the left edge (so they stay put as turns cover them), an oasis first when the place has one. */
function filler(c: Canvas, look: Look, x0: number, x1: number) {
  const span = x1 - x0
  const pal = cactusPal(look)
  const plant = (rows: Rows, x: number) => sprite(c, x, GROUND - rows.length, rows, pal)
  if (span < 3) return
  if (span <= 5) return plant(span === 5 ? SAGUARO : span === 4 ? SAGUARO_S : BARREL, x0)
  for (let k = 0, x = x0 + 1; ; k++) {
    const rows = k === 0 && hash(look.seed) % 3 !== 0 ? undefined : ITEMS[hash(look.seed + k * 17) % ITEMS.length]!
    const w = rows ? rows[0]!.length : 14
    if (x + w > x1 - 1) break
    if (rows) plant(rows, x)
    else oasis(c, look, x, w)
    x += w + 2 + (hash(look.seed + k) % 4)
  }
}

const CAMEL = ['.....hh....ne', '....hhhh.nnnn', 'bbbbbbbbbnn..', 'bBBBBBBBBn...']
const LEGS_A = ['.k.k...k.k...', '.k.k...k.k...', '.k.k...k.k...']
const LEGS_B = ['.k.k...k.k...', '..kk...kk....', '.k..k.k..k...']
const CAMEL_DOWN = ['....hh...ne', '...hhhh.nnn', 'bbbbbbbbnn.', '.kBBBBBBkk.']
const WALKER = ['.t.', '.f.', 'rrr']
const SITTER = ['.t.', 'rrr', 'rrr']
const JEEP = ['.cccccc.w', 'bbbbbbbbl', 'bbbbbbbbb', 'bkkbbbkkb', '.kk...kk.']
const RUNNER = ['....cc', 'tbbbbh', '.bbbb.']
const TUMBLE = [['.t.', 't.t', '.t.'], ['ttt', 't.t', 'ttt']]
const ROBES = [0xd9d0b8, 0x4a6fa5, 0xa8452f, 0x2f2a3a, 0xc9a24a]
const CARGO = [0xb94a3e, 0x3e6aa8, 0xc9902e, 0x6a4a8a]

/** A sprite standing on the feet row (facing right unless `dir` < 0) with its shadow. */
function put(c: Canvas, look: Look, x: number, rows: Rows, pal: Pal, dir = 1) {
  const w = rows[0]!.length
  const len = look.night > 0.5 ? -w : Math.round(byPhase(look, SHADOW))
  sprite(c, x, FEET - rows.length + 1, rows, pal, dir < 0)
  for (let i = sunSide(look) > 0 ? x : x - len; i < (sunSide(look) > 0 ? x + w + len : x + w); i++) c.glow(i, SCENE_H - 1, 0x4a2f48, 0.3)
}

const camelPal = (look: Look, load?: number): Pal => ({ b: fig(look, 0xc79a5e), B: fig(look, 0xa07040), h: fig(look, load ?? 0xd2a868), n: fig(look, 0xb88850), e: P.ink, k: fig(look, 0x6e4c30) })
const robePal = (look: Look, i: number): Pal => ({ t: fig(look, [0xe8e0d0, 0xb94a3e, 0x2f4a8a][i % 3]!), f: fig(look, 0xd9a07a), r: fig(look, ROBES[i % ROBES.length]!) })

/** A position that wanders across the scene and wraps. */
const wander = (look: Look, right: number, k: number, speed: number, dir: number) => {
  const span = right + 24
  return Math.round(((((hash(look.seed + k * 131) % span) + dir * look.frame * speed) % span) + span) % span) - 12
}

function camelWalk(c: Canvas, look: Look, x: number, dir: number, load?: number, rider?: number) {
  put(c, look, x, [...CAMEL, ...(Math.floor(look.frame / 3) % 2 ? LEGS_B : LEGS_A)], camelPal(look, load), dir)
  if (rider !== undefined) sprite(c, x + (dir > 0 ? 4 : 5), FEET - 8, WALKER, robePal(look, rider))
}

function walker(c: Canvas, look: Look, right: number, k: number) {
  const dir = k % 2 ? 1 : -1
  const hem = Math.floor((look.frame + k) / 3) % 2 ? 'r.r' : '.r.'
  put(c, look, wander(look, right, 40 + k, 0.2, dir), [...WALKER, hem], robePal(look, k + (hash(look.seed + k) % 5)), dir)
}

function fire(c: Canvas, look: Look, x: number) {
  const f = hash(Math.floor(look.frame / 2) + x) % 3
  if (look.phase === 'dusk' || look.phase === 'dawn' || look.night > 0.3) {
    for (let dx = -5; dx <= 5; dx++) for (let y = GROUND + 1; y < SCENE_H; y++) c.glow(x + 1 + dx, y, 0xff9a40, 0.3 * (1 - Math.abs(dx) / 6))
  }
  sprite(c, x, FEET - 2, [f ? '.y.' : '.o.', 'ooo', 'kkk'], { y: 0xffe070, o: 0xf08a30, k: 0x5a3b2c })
  if (look.frame % 7 < 2) c.set(x + f, FEET - 4, 0xffd070) // a spark
}

/** A market stall: a striped awning, hanging goods, a counter with fruit. */
function stall(c: Canvas, look: Look, x: number, k: number) {
  const [a, cream, wood] = [fig(look, CARGO[hash(look.seed + k) % 4]!), fig(look, 0xe8dcc0), fig(look, 0x6b4f3f)]
  for (let i = 0; i < 7; i++) {
    c.set(x + i, FEET - 4, i % 2 ? a : cream)
    c.set(x + i, FEET - 3, mix(i % 2 ? a : cream, P.ink, 0.2))
    c.set(x + i, FEET, wood)
    if (i % 2) c.set(x + i, FEET - 1, fig(look, [0xe05a3a, 0xe8c050, 0x7aa84a, 0x8a5aa8][(i + k) % 4]!)) // goods on the counter
    if (i % 6 === 0) for (let y = FEET - 2; y < FEET; y++) c.set(x + i, y, wood)
  }
  c.set(x + 2, FEET - 2, fig(look, 0xc9902e))
  c.set(x + 4, FEET - 2 + Math.round(wave(look.frame, 24, k * 3)), fig(look, 0xb94a3e))
}

function tumbleweed(c: Canvas, look: Look, right: number) {
  const x = wander(look, right, 90, 0.04 + look.wind * 0.012, 1) // rolls downwind
  sprite(c, x, FEET - 2 - Math.round(Math.abs(Math.sin(look.frame * 0.35)) * 2), TUMBLE[Math.floor(look.frame / 2) % 2]!, { t: fig(look, 0x9a7447) })
}

function runner(c: Canvas, look: Look, right: number) {
  const [cycle, t] = [Math.floor(look.frame / 100), Math.min(35, look.frame % 100)] // dashes for 3.5 s, then stands
  const dir = cycle % 2 ? 1 : -1
  const x = ((((hash(look.seed + cycle) % right) + dir * t * 0.9) % right) + right) % right
  const legs = t < 35 && Math.floor(look.frame / 2) % 2 ? '.l..l.' : '..l.l.'
  put(c, look, Math.round(x), [...RUNNER, legs], { c: fig(look, 0x2f4a8a), t: fig(look, 0x6e5a48), b: fig(look, 0x8a7458), h: P.yellow, l: fig(look, 0xd0a040) }, dir)
}

function lightsString(c: Canvas, look: Look, x0: number, x1: number) {
  const wood = fig(look, 0x6b4f3f)
  for (const x of [x0, x1]) for (let y = FEET - 5; y <= FEET; y++) c.set(x, y, wood)
  for (let x = x0 + 1; x < x1; x++) {
    const y = FEET - 5 + Math.round(1.5 * Math.sin(((x - x0) / (x1 - x0)) * Math.PI))
    c.set(x, y, mix(wood, P.ink, 0.2))
    if ((x - x0) % 3 === 1 && hash(x + Math.floor(look.frame / 6)) % 5 !== 0) {
      const bulb = [0xffd36a, 0xff8a6a, 0x9ad8ff, 0xffd36a][(x - x0) % 4]!
      c.set(x, y + 1, bulb)
      c.glow(x, y + 2, bulb, 0.25)
    }
  }
}

/** A lantern: a bright pixel with a halo. */
function lantern(c: Canvas, x: number, y: number, color: number) {
  c.set(x, y, color)
  for (const [dx, dy] of [[-1, 0], [1, 0], [0, -1], [0, 1]] as const) c.glow(x + dx, y + dy, color, 0.3)
}

function foreground(c: Canvas, look: Look, right: number) {
  const at = (f: number) => Math.round(right * f)
  tumbleweed(c, look, right)
  switch (look.phase) {
    case 'dawn':
      fire(c, look, at(0.55))
      put(c, look, at(0.55) - 4, SITTER, robePal(look, 1))
      put(c, look, at(0.3), CAMEL_DOWN, camelPal(look, CARGO[0]))
      walker(c, look, right, 1)
      break
    case 'morning':
      for (let k = 0; k < 3; k++) stall(c, look, at(0.12 + k * 0.28), k)
      for (let k = 0; k < 3; k++) walker(c, look, right, k)
      camelWalk(c, look, wander(look, right, 1, 0.12, 1), 1, CARGO[1])
      break
    case 'noon':
      put(c, look, at(0.4), ROCK, { r: fig(look, 0xa08068), s: fig(look, 0x6e5645) })
      sprite(c, at(0.4) + 1, FEET - 4 + (look.frame % 30 < 4 ? 0 : 1), ['gg', 'gg'], { g: fig(look, 0x7a9a4a) }) // a lizard on the rock
      runner(c, look, right)
      break
    case 'afternoon': {
      const dir = look.seed % 2 ? 1 : -1
      const x = wander(look, right, 5, 0.7, dir)
      put(c, look, x, JEEP, { c: fig(look, 0xe0d0a0), b: fig(look, 0xb8452f), w: fig(look, 0x9ad8ff), l: P.yellow, k: P.crust }, dir)
      for (let k = 1; k < 7; k++) c.glow(x + (dir > 0 ? -k : 9 + k), FEET - (hash(Math.floor(look.frame / 2) + k) % 3), 0xf0d8a8, 0.5 - k * 0.07) // dust
      stall(c, look, at(0.18), 5)
      walker(c, look, right, 0)
      camelWalk(c, look, wander(look, right, 2, 0.12, -1), -1, CARGO[2])
      break
    }
    case 'dusk':
      for (let k = 0; k < 3; k++) camelWalk(c, look, wander(look, right, 0, 0.1, -1) + k * 13, -1, k % 2 ? CARGO[k] : undefined, k === 0 ? 0 : undefined)
      fire(c, look, at(0.62))
      put(c, look, at(0.62) + 4, SITTER, robePal(look, 2))
      walker(c, look, right, 3)
      break
    default:
      lightsString(c, look, at(0.4), at(0.4) + 14)
      fire(c, look, at(0.4) + 7)
      put(c, look, at(0.4) + 3, SITTER, robePal(look, 3))
      put(c, look, at(0.4) + 11, SITTER, robePal(look, 0), -1)
      put(c, look, at(0.78), CAMEL_DOWN, camelPal(look, CARGO[3]), -1)
      lantern(c, at(0.78) + 1, FEET - 1, P.yellow) // the resting camel's lantern
  }
}

export const desert: Landscape = {
  name: 'desert',
  ground: GROUND,

  backdrop(c, look) {
    mesas(c, look)
    dunes(c, look, true)
    dunes(c, look, false)
    const haze = byPhase(look, { dawn: 0.28, morning: 0.1 })
    if (haze) for (let y = GROUND - 5; y < GROUND; y++) for (let x = 0; x < c.W; x++) c.glow(x, y, 0xe8c0d8, haze * ((y - GROUND + 6) / 5))
    shimmer(c, look)
  },

  floor(c, look) {
    for (let y = GROUND; y < SCENE_H; y++) {
      for (let x = 0; x < c.W; x++) {
        let col = sand(look, mix(0xeed19a, 0xcfa468, (y - GROUND) / 3))
        const h = hash(x * 7 + y * 131 + look.seed)
        if (y === GROUND) col = mix(col, P.white, 0.12)
        if ((x + y * 5 + (hash(y + look.seed) % 9)) % 9 < 2) col = mix(col, sand(look, 0x8a5a48), 0.2) // ripples
        if (h % 43 === 0) col = mix(col, P.ink, 0.25)
        else if (h % 57 === 0) col = mix(col, P.white, 0.2)
        c.set(x, y, look.wet ? mix(col, P.surface1, 0.22) : col)
      }
    }
  },

  size(kinds: WakePulseKind[], index) {
    const e = editsOf(kinds)
    switch (styleOf(index)) {
      case 0: return { width: 5 + Math.min(3, e), height: heightFor(kinds, 4, 9) }
      case 1: return { width: 5 + Math.min(2, e), height: heightFor(kinds, 6, 10) }
      case 2: return { width: 3 + (e >= 2 ? 1 : 0), height: heightFor(kinds, 7, GROUND - 1, 2) }
      case 3: return { width: 2 * heightFor(kinds, 4, 7) - 1, height: heightFor(kinds, 4, 7) }
      default: return { width: 6 + Math.min(4, e), height: heightFor(kinds, 5, 10) }
    }
  },

  gap: index => 3 + (hash(index * 31) % 3),

  building(c, look, b) {
    const wall = tint(look, WALLS[hash(b.index) % WALLS.length]!)
    const inner = STYLES[styleOf(b.index)]!(c, look, b, wall)
    const cx = b.x0 + Math.floor(b.width / 2)
    const door = b.index % 3 === 0 ? tint(look, 0x3a86a0) : tint(look, 0x4a3328)
    for (const y of [GROUND - 1, GROUND - 2]) c.set(cx, y, mix(door, P.yellow, 0.5 * look.night))
    lightWindows(c, look, b, slotsIn(inner), wall)
    if (b.kinds.includes('fail') && look.frame % 10 < 6) c.glow(cx + 1, GROUND - 3, P.red, 0.9) // a red lantern by the door
    if (b.isLive) scaffold(c, look, b)
  },

  filler,
  jobs: airJobs,
  foreground,

  events: [
    {
      name: 'sandstorm', frames: 150, weight: 2, when: look => !look.wet && look.night < 0.9,
      draw(c, look, age, seed) {
        const [k, dust] = [Math.sin((age / 150) * Math.PI), tint(look, 0xd8b078)]
        for (let y = 0; y < SCENE_H; y++) for (let x = 0; x < c.W; x++) c.glow(x, y, dust, 0.6 * k)
        for (let s = 0; s < c.W / 5; s++) {
          const x = ((hash(s * 3 + seed) % (c.W + 20)) + age * (4 + (s % 3))) % (c.W + 20) - 10
          for (let l = 0; l < 6; l++) c.glow(x - l, hash(seed + s) % SCENE_H, mix(dust, P.white, 0.4), 0.55 * k * (1 - l / 6)) // streaks
        }
      },
    },
    {
      name: 'caravan', frames: 260, weight: 3,
      draw(c, look, age) {
        const lead = Math.round((age / 260) * (c.W + 80)) - 20
        for (let k = 0; k < 4; k++) {
          const x = lead - k * 15
          const y = FEET - 7
          if (x < -12 || x > c.W + 2) continue
          sprite(c, x, y, [...CAMEL, ...(Math.floor(age / 3) % 2 ? LEGS_B : LEGS_A)], camelPal(look, CARGO[k]))
          if (k === 0) sprite(c, x + 4, y - 2, WALKER, robePal(look, 1))
          if (k < 3) for (let i = 1; i < 4; i++) c.set(x - 1 - i, y + 3, fig(look, 0x6b4f3f)) // the rope
          if (look.night > 0.4) lantern(c, x + 8, y + 4, P.yellow)
        }
      },
    },
    {
      name: 'mirage', frames: 160, weight: 2, when: look => look.phase === 'noon' || look.phase === 'afternoon',
      draw(c, _look, age) {
        const [k, x0, w] = [Math.sin((age / 160) * Math.PI), Math.floor(c.W * 0.28), Math.floor(c.W * 0.3)]
        for (let x = 0; x < w; x++) {
          const wob = Math.round(Math.sin(x * 0.5 + age * 0.4) * 0.8)
          c.glow(x0 + x, GROUND - 3 + wob, 0x9fd8f0, 0.6 * k)
          c.glow(x0 + x, GROUND - 2 + wob, hash(x + age) % 4 ? 0x8fd0ec : P.white, 0.5 * k)
        }
        for (const px of [x0 + Math.floor(w / 3), x0 + Math.floor(w / 2)]) {
          for (let r = 0; r < 3; r++) c.glow(px + Math.round(Math.sin(age * 0.3 + r)), GROUND - 1 + r, 0x2f6a38, 0.5 * k) // palms in the water, upside down
          for (const dx of [-1, 1]) c.glow(px + dx, GROUND + 2, 0x2f6a38, 0.4 * k)
        }
      },
    },
    {
      name: 'coyote', frames: 140, weight: 2, when: look => look.night > 0.6,
      draw(c, look, age, seed) {
        const x = Math.floor(c.W * 0.1) + (seed % Math.max(1, Math.floor(c.W * 0.35)))
        const y = ridge(look, x, false) - 5
        const ring = Math.floor(age / 7) % 5 // the howl rolls out in arcs
        sprite(c, x, y, ['....nn', '...nn.', '..nn..', '.nnn..', 'nnnnn.', 'nnnnn.'], { n: mix(tint(look, 0x7a6a6a), P.lavender, 0.3) })
        if (ring > 0 && ring < 4) for (const dy of [-1, 0, 1]) c.glow(x + 5 + ring * 2 + (dy ? 0 : 1), y + dy - ring, P.white, 0.55 - ring * 0.12)
      },
    },
    {
      name: 'milky way', frames: 200, weight: 2, when: look => look.night > 0.8,
      draw(c, _look, age, seed) {
        const k = Math.sin((age / 200) * Math.PI)
        for (let i = 0; i < c.W * 2; i++) {
          const t = (hash(seed + i) % 1000) / 1000
          const x = Math.round(c.W * (0.1 + 0.8 * t))
          const y = Math.round(SCENE_H * 0.55 - t * SCENE_H * 0.5 + ((hash(seed * 3 + i) % 5) - 2) * 0.8 * (1 - Math.abs(t - 0.5)))
          const px = c.get(x, y)
          if (y < GROUND - 3 && (px & 255) >= ((px >> 16) & 255)) c.glow(x, y, hash(i + age) % 5 ? P.lavender : P.white, 0.28 * k) // only over sky
        }
      },
    },
  ],
}
