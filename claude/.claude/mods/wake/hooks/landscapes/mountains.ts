import { type Canvas, hash, mix, sprite } from '../pixels'
import { type Building, sunGlow, type Landscape, type Look, P, SCENE_H, editsOf, farTone, foliage, heightFor, lightWindows, wave, jobAccent } from './kit'
import { airJobs } from './crew'

// Mountains: an alpine village under snowcapped peaks. Each turn is a chalet, an A-frame,
// a chapel or a lodge (by its number); the live one smokes and stands in scaffolding.
// Bridge jobs are hikers' headlamps on the far slope. The day goes: alpenglow on the peaks
// at dawn and dusk, hikers and a cable car by day, a campfire and fireflies at night.

const GROUND = SCENE_H - 4 // the meadow; a path and a two-row stream run below it
const MAXH = GROUND - 4 // tallest turn; the peaks stand above it
const WOODS = [0x7a5a43, 0x6b4f3f, 0x8a6a4c, 0x5f4636, 0x7d6048]
const ROOFS = [0x5a3b3b, 0x3f4a5e, 0x6b4036, 0x4a5240]
const dim = (color: number, look: Look, k = 0.45) => mix(color, P.ink, k * look.night)
const sine = (x: number, f: number, p: number) => 0.5 + 0.5 * Math.sin(x * f + p)
/** A back-and-forth position along `span` columns; `back` when walking left. */
const pingPong = (t: number, span: number) => {
  const m = t % (span * 2)
  return { x: Math.round(m < span ? m : span * 2 - m), back: m >= span }
}

/** The three ridge heights (pixels above the ground row) at column x. */
function ridges(look: Look) {
  const ph = (n: number) => (hash(look.seed + n * 101) % 628) / 100
  const [a, b, c, d, e, f] = [0, 1, 2, 3, 4, 5].map(ph) as [number, number, number, number, number, number]
  const tree = (x: number, k: number) => (hash(x * 5 + look.seed + k) % 5 === 0 ? 1 + (hash(x * 3 + k) % 3 === 0 ? 1 : 0) : 0)
  return {
    far: (x: number) => 4.5 + 0.8 * (5.5 * (1 - Math.abs(Math.sin(x * 0.052 + a))) ** 0.8 + 2.5 * (1 - Math.abs(Math.sin(x * 0.113 + b)))) * (0.7 + 0.3 * sine(x, 0.02, c)),
    mid: (x: number) => 1.6 + 2 * sine(x, 0.07, d) + sine(x, 0.19, e) + tree(x, 1),
    near: (x: number) => 0.8 + 1.2 * sine(x, 0.11, f) + tree(x, 2) * 1.3,
  }
}

/** A pine of `h` tier rows over a trunk, centred on cx, standing on the meadow; snow on each tier's edge. */
function pine(c: Canvas, look: Look, cx: number, h: number, seed: number) {
  const [lt, dk] = foliage(look.season, seed)
  const green = look.season === 'autumn' && hash(seed) % 3 === 0 ? dk : mix(dk, 0x24493c, 0.6) // the odd golden larch
  const maxHalf = h >= 9 ? 3 : h >= 6 ? 2 : 1
  const half = (r: number) => Math.min(maxHalf, (r + 1) >> 1)
  c.set(cx, GROUND - 1, dim(P.woodDark, look))
  for (let r = 0; r < h; r++) {
    for (let dx = -half(r); dx <= half(r); dx++) {
      const exposed = r === 0 || Math.abs(dx) > half(r - 1)
      const leaf = dx < 0 ? mix(green, lt, 0.25) : dx === 0 ? green : mix(green, P.ink, 0.15)
      c.set(cx + dx, GROUND - 1 - h + r, dim(look.snowy && exposed ? (dx < 0 ? P.snow : mix(P.snow, P.overlay0, 0.25)) : leaf, look))
    }
  }
}

function rock(c: Canvas, look: Look, x: number, seed: number) {
  const stone = dim(mix(P.overlay0, P.surface1, (seed % 3) / 3), look)
  c.rect(x, GROUND - 1, 3, 1, stone)
  c.set(x + 1, GROUND - 2, look.snowy ? dim(P.snow, look) : mix(stone, P.overlay2, 0.3))
}

/** Rising chimney smoke: puffs drift with the wind and fade. */
function smoke(c: Canvas, look: Look, x: number, y: number, seed: number) {
  for (let k = 0; k < 5; k++) {
    const t = ((look.frame + k * 7 + seed) % 35) / 35
    const px = x + Math.round(t * (1.5 + look.wind / 8) + Math.sin(t * 6 + k))
    const py = y - Math.round(t * 7)
    c.glow(px, py, P.white, 0.8 * (1 - t) * (0.6 + 0.4 * (1 - look.night)))
    if (t > 0.35) c.glow(px + 1, py, P.overlay2, 0.4 * (1 - t))
  }
}

/** Plank walls (alternate rows a shade darker, the left column lit). */
function wall(c: Canvas, look: Look, x0: number, w: number, y0: number, y1: number, color: number) {
  for (let y = y0; y <= y1; y++) for (let x = x0; x < x0 + w; x++) c.set(x, y, dim(x === x0 ? mix(color, P.white, 0.1) : (y - y0) % 2 ? mix(color, P.ink, 0.14) : color, look))
}

/** A stepped gable roof with a 1px eave and snow on every exposed edge. Returns the roof's top y at a column. */
function gable(c: Canvas, look: Look, x0: number, w: number, eaveY: number, color: number) {
  const rows = Math.ceil((w + 2) / 4)
  const mid = x0 + (w - 1) / 2
  const xl = (r: number) => x0 - 1 + r * 2
  const xr = (r: number) => x0 + w - r * 2
  for (let r = 0; r < rows; r++) {
    for (let x = xl(r); x <= xr(r); x++) {
      const exposed = r === rows - 1 || x < xl(r + 1) || x > xr(r + 1)
      const base = r === 0 ? mix(color, P.ink, 0.22) : x <= mid ? color : mix(color, P.ink, 0.14)
      c.set(x, eaveY - 1 - r, dim(look.snowy && exposed ? (x <= mid ? P.snow : mix(P.snow, P.overlay0, 0.2)) : base, look))
    }
  }
  return (x: number) => eaveY - 1 - Math.min(Math.floor((x - xl(0)) / 2), Math.floor((xr(0) - x) / 2))
}

function door(c: Canvas, look: Look, x: number, tall = 2) {
  for (let k = 1; k <= tall; k++) c.set(x, GROUND - k, dim(P.woodDark, look, 0.2))
  if (look.night > 0.4) c.glow(x, GROUND - 1, P.yellow, 0.55 * look.night)
}

type Parts = { eave: number; smoke: [number, number] }

/** Window slots up the wall, bottom to top, every other column from `from` to `to`. */
function wallSlots(x0: number, from: number, to: number, eave: number): [number, number][] {
  const slots: [number, number][] = []
  for (let y = GROUND - 2; y >= eave; y -= 2) for (let x = x0 + from; x <= x0 + to; x += 2) slots.push([x, y])
  return slots
}

/** A chalet, or the wider lodge with a stone base and a flag on the ridge. */
function timber(c: Canvas, look: Look, b: Building, lodge: boolean): Parts {
  const { x0, width: w } = b
  const wood = WOODS[hash(b.index) % WOODS.length]!
  const eave = GROUND - (b.height - Math.ceil((w + 2) / 4))
  wall(c, look, x0, w, eave, GROUND - (lodge ? 2 : 1), wood)
  const top = gable(c, look, x0, w, eave, ROOFS[hash(b.index + 5) % ROOFS.length]!)
  const cx = lodge ? x0 + w - 3 : x0 + 2
  c.rect(cx, top(cx) - 2, 1, 2, dim(P.surface2, look))
  const slots = wallSlots(x0, 1, w - (lodge ? 2 : 3), eave)
  if (lodge) {
    for (let x = x0; x < x0 + w; x++) c.set(x, GROUND - 1, dim(mix(P.surface2, P.surface1, hash(x * 3 + b.index) % 2), look))
    door(c, look, x0 + (w >> 1), 1)
    const fx = x0 + ((w - 1) >> 1)
    c.rect(fx, top(fx) - 2, 1, 2, dim(P.overlay1, look))
    c.set(fx + 1, top(fx) - 2 + Math.round(wave(look.frame, 14)), dim(P.red, look, 0.2)) // flag
  } else {
    door(c, look, x0 + w - 2)
    slots.push([x0 + (w >> 1), eave - 1]) // an attic window
  }
  lightWindows(c, look, b, slots, wood)
  return { eave, smoke: [cx, top(cx) - 3] }
}

function aframe(c: Canvas, look: Look, b: Building): Parts {
  const { x0, width: w, height: h } = b
  const roof = ROOFS[hash(b.index + 9) % ROOFS.length]!
  const face = WOODS[hash(b.index) % WOODS.length]!
  const mid = x0 + (w >> 1)
  const spanAt = (y: number) => Math.max(1, Math.round((w * (y - (GROUND - h) + 1)) / h))
  for (let y = GROUND - h; y < GROUND; y++) {
    const span = spanAt(y)
    const left = x0 + ((w - span) >> 1)
    for (let x = left; x < left + span; x++) {
      const edge = x === left || x === left + span - 1
      const snow = look.snowy && edge && (y - GROUND + h) % 2 === 0
      c.set(x, y, dim(snow ? (x === left ? P.snow : mix(P.snow, P.overlay0, 0.2)) : edge ? roof : mix(face, P.white, 0.05), look))
    }
  }
  door(c, look, mid)
  const slots: [number, number][] = []
  for (let y = GROUND - 2; y > GROUND - h; y -= 2) {
    if (spanAt(y) >= 5) slots.push([mid - 1, y], [mid + 1, y])
    else if (spanAt(y) >= 3) slots.push([mid, y])
  }
  lightWindows(c, look, b, slots, face)
  c.set(mid, GROUND - h - 1, dim(P.surface2, look))
  return { eave: GROUND - h + 1, smoke: [mid, GROUND - h - 2] }
}

/** A chapel: a tower with a spire and cross beside a low nave. */
function chapel(c: Canvas, look: Look, b: Building): Parts {
  const { x0, width: w } = b
  const plaster = mix(0xd9d0c4, P.surface2, 0.15)
  const slate = ROOFS[(hash(b.index + 2) % 2) + 1]!
  const bodyH = b.height - 3
  const left = hash(b.index) % 2 === 0
  const tx = left ? x0 : x0 + w - 3
  const nx = left ? x0 + 3 : x0
  const nw = w - 3
  const naveWall = Math.max(2, bodyH - 2)
  wall(c, look, tx, 3, GROUND - bodyH, GROUND - 1, plaster)
  wall(c, look, nx, nw, GROUND - naveWall, GROUND - 1, plaster)
  gable(c, look, nx, nw, GROUND - naveWall, slate)
  const sy = GROUND - bodyH
  for (let dx = 0; dx < 3; dx++) c.set(tx + dx, sy - 1, dim(look.snowy ? mix(P.snow, slate, 0.2) : slate, look))
  c.set(tx + 1, sy - 2, dim(look.snowy ? P.snow : slate, look))
  c.set(tx + 1, sy - 3, dim(P.yellow, look, 0.2)) // the cross
  door(c, look, tx + 1)
  const slots: [number, number][] = []
  for (let x = nx + 1; x <= nx + nw - 2; x += 2) slots.push([x, GROUND - 2])
  for (let y = GROUND - 4; y > sy; y -= 2) slots.push([tx + 1, y])
  slots.push([tx + 1, sy + 1])
  lightWindows(c, look, b, slots, plaster)
  return { eave: GROUND - naveWall, smoke: [nx + (nw >> 1), GROUND - naveWall - 3] }
}

/** Scaffolding round the turn being built, a worker on the top plank. */
function scaffold(c: Canvas, look: Look, b: Building, eave: number) {
  const wood = dim(mix(P.sand, P.wood, 0.4), look)
  const xl = b.x0 - 1
  const xr = b.x0 + b.width
  const top = Math.max(1, eave)
  for (let y = top; y < GROUND; y++) {
    c.set(xl, y, wood)
    c.set(xr, y, wood)
  }
  const planks: number[] = []
  for (let y = GROUND - 3; y >= top; y -= 3) planks.push(y)
  for (const y of planks) for (let x = xl; x <= xr; x++) c.set(x, y, wood)
  for (let k = 0; k < 3; k++) c.set(xl + 1 + k, GROUND - 1 - k, dim(mix(wood, P.ink, 0.2), look)) // a brace
  const py = planks[planks.length - 1] ?? GROUND - 3
  const wx = b.x0 + Math.round((b.width - 1) * wave(look.frame, 50, b.index))
  c.set(wx, py - 1, dim(P.maroon, look))
  c.set(wx, py - 2, dim(P.yellow, look, 0.2))
  if (look.frame % 8 < 2) c.set(wx + 1, py - 2, P.white) // a hammer blow
}

const STYLES = [(c: Canvas, l: Look, b: Building) => timber(c, l, b, false), aframe, chapel, (c: Canvas, l: Look, b: Building) => timber(c, l, b, true)]
const styleOf = (index: number) => hash(index * 7 + 3) % STYLES.length

// ── foreground life, walking the path (feet on the row below the meadow) ──

const DEER = ['...a.a.', '....bbn', '.....b.', '.bbbbb.', '.bbbbs.']
const GRAZING = ['.......', '.......', '.......', '.bbbbbb', '.bbbbsn']
const HIKER = ['.hh.', '.ss.', 'pjj.', 'pjjs']

/** Deer wander the bank at dawn and dusk, stopping to graze. */
function deer(c: Canvas, look: Look, right: number) {
  const moving = look.frame % 120 < 70
  const span = Math.max(8, right - 20)
  const t = Math.floor(look.frame / 120) * 8.4 + Math.min(look.frame % 120, 70) * 0.12 + (look.seed % span)
  const coat = look.snowy ? 0xd8cbb0 : 0x9a6b45
  const legs = !moving || look.frame % 6 < 3 ? '.bb.bb.' : '.b.b.b.'
  const palette = { b: dim(coat, look), s: dim(mix(coat, P.white, 0.35), look), n: dim(mix(coat, P.white, 0.55), look), a: dim(P.sand, look) }
  const { x, back } = pingPong(t, span)
  sprite(c, 4 + x, GROUND - 5, [...(moving ? DEER : GRAZING), legs, legs], palette, back)
}

/** Two hikers with packs pace the path by day. */
function hikers(c: Canvas, look: Look, right: number) {
  for (let k = 0; k < 2; k++) {
    const h = hash(look.seed + k * 77)
    const span = Math.max(8, right - 14)
    const jacket = [P.red, P.blue, P.peach, P.green][h % 4]!
    const legs = look.frame % 8 < 4 ? '.l.l' : '.ll.'
    const palette = { h: dim(mix(jacket, P.white, 0.3), look), s: dim(0xe0b898, look), j: dim(jacket, look), p: dim(P.wood, look), l: dim(P.surface1, look) }
    const { x, back } = pingPong(look.frame * (0.1 + k * 0.03) + (h % span), span)
    sprite(c, 4 + x, GROUND - 4, [...HIKER, legs, legs], palette, back)
  }
}

/** A campfire with a sitting camper, sparks rising, fireflies about in the warm months. */
function camp(c: Canvas, look: Look, right: number) {
  const x = 12 + (hash(look.seed) % Math.max(1, right - 30))
  const y = GROUND + 1
  const flick = look.frame % 6 < 3
  for (let dx = -5; dx <= 8; dx++) for (let dy = -4; dy <= 1; dy++) c.glow(x + dx, y + dy, P.peach, Math.max(0, 0.22 * (1 - Math.hypot(dx - 1, dy + 1) / 6)) * (flick ? 1 : 0.8))
  c.rect(x, y, 3, 1, P.woodDark)
  sprite(c, x, y - 3, flick ? ['.y.', 'yoy', 'orr'] : ['y..', 'yoy', 'rro'], { y: P.yellow, o: P.peach, r: P.red })
  for (let k = 0; k < 2; k++) c.glow(x + 1 + k, y - 4 - ((look.frame + k * 5) % 8), P.yellow, 0.9 - ((look.frame + k * 5) % 8) / 9)
  sprite(c, x + 5, y - 3, ['.s.', 'jjw', 'jjw', 'jjj'], { s: 0xd9b090, j: P.surface2, w: mix(P.surface2, P.peach, 0.5) })
  if (look.season !== 'spring' && look.season !== 'summer') return
  for (let k = 0; k < 8; k++) {
    if ((look.frame + k * 7) % 22 > 13) continue
    const fx = 6 + ((hash(k + look.seed) % Math.max(1, right - 8)) + Math.round(3 * Math.sin(look.frame * 0.03 + k)))
    const fy = GROUND - 2 + Math.round(2 * Math.sin(look.frame * 0.05 + k * 2))
    c.glow(fx, fy, 0xd7f070, 0.9)
    c.glow(fx + 1, fy, 0xd7f070, 0.2)
  }
}

export const mountains: Landscape = {
  name: 'mountains',
  ground: GROUND,

  backdrop(c, look) {
    const r = ridges(look)
    const far = mix(farTone(look, 0), 0x46598a, 0.7 * (1 - look.night))
    const glow = sunGlow(look) // alpenglow on the peaks, fading in and out with the hour
    const snowLine = look.snowy ? 4.5 : look.season === 'winter' ? 5 : look.season === 'summer' ? 7 : 6
    const snow = mix(mix(P.snow, far, 0.3 + 0.55 * look.night), glow.color, 0.7 * glow.amount)
    const snowShade = mix(snow, mix(far, P.mauve, glow.amount), 0.5 - 0.05 * glow.amount)
    for (let x = 0; x < c.W; x++) {
      const h = r.far(x)
      const top = Math.round(GROUND - h)
      const lit = r.far(x - 1) < h
      const capRows = h > snowLine ? Math.min(6, Math.floor((h - snowLine) * 1.4) + 1 - (hash(x + look.seed) % 5 === 0 ? 1 : 0)) : 0
      for (let y = top; y < GROUND; y++) {
        const d = y - top
        if (d < capRows) c.set(x, y, lit ? snow : snowShade)
        else c.set(x, y, mix(mix(mix(far, look.horizon, 0.25 * (d / h)), glow.color, lit ? 0.22 * glow.amount : 0), P.ink, lit ? 0 : 0.14))
      }
    }
    // forested ridges: nearer, greener, with pine tips along the top
    for (const [depth, fn, green] of [[1, r.mid, 0.35], [2, r.near, 0.55]] as const) {
      const base = mix(farTone(look, depth), foliage(look.season, look.seed)[1], green)
      for (let x = 0; x < c.W; x++) {
        const top = Math.round(GROUND - fn(x))
        for (let y = top; y < GROUND; y++) c.set(x, y, mix(base, P.ink, 0.08 * (y - top)))
        if (look.snowy) c.glow(x, top, P.snow, 0.5 + 0.3 * (1 - look.night))
        if (depth === 1 && look.night > 0.4 && hash(x * 17 + look.seed) % 29 === 0) c.set(x, top + 1, mix(base, P.yellow, 0.7 * look.night)) // a far cabin light
      }
    }
  },

  floor(c, look) {
    const meadow = look.snowy ? mix(P.snow, P.surface1, 0.12) : mix(foliage(look.season, look.seed)[0], P.mantle, 0.4)
    const path = look.snowy ? mix(P.snow, P.overlay0, 0.3) : mix(P.sand, P.wood, 0.45)
    const water = look.snowy ? mix(0xb9d4ec, look.horizon, 0.3) : mix(look.horizon, P.sapphire, 0.4)
    for (let x = 0; x < c.W; x++) {
      const h = hash(x * 7 + look.seed)
      c.set(x, GROUND, dim(h % 9 === 0 && !look.snowy ? foliage(look.season, h)[0] : mix(meadow, P.ink, 0.1 * (h % 3)), look)) // a tuft now and then
      c.set(x, GROUND + 1, dim(mix(path, P.ink, 0.08 * (h % 4)), look))
      for (let y = GROUND + 2; y < SCENE_H; y++) {
        const f = (((x - Math.floor(look.frame / (y === GROUND + 2 ? 2 : 3)) + y * 3) % 9) + 9) % 9
        let tone = mix(water, P.ink, 0.12 * (y - GROUND - 2))
        if (look.snowy) tone = hash(x * 3 + y + look.seed) % 11 === 0 ? mix(water, P.surface1, 0.4) : tone // ice with cracks
        else if (f === 0 || (f === 4 && x % 3 === 0)) tone = mix(tone, mix(P.white, sunGlow(look).color, sunGlow(look).amount), 0.4) // glints drift along
        c.set(x, y, dim(tone, look))
      }
    }
  },

  size(kinds, index) {
    const e = Math.min(3, editsOf(kinds))
    switch (styleOf(index)) {
      case 0: return { width: 7 + e, height: heightFor(kinds, 6, MAXH) }
      case 1: return { width: 6 + e, height: heightFor(kinds, 6, MAXH) }
      case 2: return { width: 7 + Math.min(2, e), height: heightFor(kinds, 8, MAXH) }
      default: return { width: 9 + e, height: heightFor(kinds, 7, MAXH) }
    }
  },

  gap(index) {
    return 2 + (hash(index * 31) % 3)
  },

  building(c, look, b) {
    const parts = STYLES[styleOf(b.index)]!(c, look, b)
    if (b.kinds.includes('fail') && look.frame % 10 < 5) c.set(b.x0 + b.width, GROUND - 2, P.red) // a warning lantern by the wall
    if (b.isLive) {
      scaffold(c, look, b, parts.eave)
      smoke(c, look, parts.smoke[0], parts.smoke[1], b.index)
    }
  },

  filler(c, look, x0, x1) {
    for (let x = x0; x < x1; ) {
      const h = hash(x * 13 + look.seed)
      const room = x1 - x
      if (room >= 3 && h % 10 < 6) {
        const ph = room < 5 ? 4 + ((h >>> 4) % 2) : 4 + ((h >>> 4) % 4) + ((h >>> 9) % 6 === 0 ? 3 : 0)
        const w = ph >= 9 ? 7 : ph >= 6 ? 5 : 3
        if (w <= room) {
          pine(c, look, x + (w >> 1), ph, h >>> 8)
          x += w + 1 + ((h >>> 9) % 4)
          continue
        }
      }
      if (room >= 3 && h % 10 < 8) rock(c, look, x, h >>> 6)
      else if (!look.snowy && (look.season === 'spring' || look.season === 'summer')) c.set(x, GROUND - 1, dim([P.pink, P.yellow, P.white, P.mauve][(h >>> 5) % 4]!, look)) // a wildflower
      else c.set(x, GROUND - 1, look.snowy ? dim(P.snow, look) : dim(foliage(look.season, h)[1], look))
      x += 2
    }
  },

  jobs: airJobs,

  foreground(c, look, right) {
    if (look.phase === 'night') camp(c, look, right)
    else if (look.phase === 'dawn' || look.phase === 'dusk') deer(c, look, right)
    else hikers(c, look, right)
  },

  events: [
    {
      name: 'cable car',
      frames: 220,
      weight: 4,
      when: look => look.night < 0.6,
      draw(c, look, age, seed) {
        // a gondola on a cable strung high across the valley
        const cableY = (x: number) => 1 + Math.round((x / c.W) * 3)
        for (let x = 0; x < c.W; x++) c.glow(x, cableY(x), P.ink, 0.5)
        const x = Math.round((seed % 2 ? age / 220 : 1 - age / 220) * (c.W + 8)) - 4
        const y = cableY(x)
        c.set(x + 1, y + 1, P.surface2)
        c.set(x + 2, y + 1, P.surface2)
        sprite(c, x, y + 2, ['rrrr', 'rwwr', 'rrrr'], { r: dim(P.red, look, 0.2), w: look.night > 0.4 ? P.yellow : mix(P.red, P.sky, 0.5) })
      },
    },
    {
      name: 'eagle',
      frames: 200,
      weight: 3,
      when: look => look.night < 0.6 && !look.wet,
      draw(c, look, age, seed) {
        // circling on a thermal over the peaks
        const a = age * 0.09
        const x = Math.round(c.W * 0.3 + (seed % Math.max(1, Math.round(c.W * 0.3))) + 14 * Math.cos(a))
        const y = 1 + Math.round(1.3 * Math.sin(a))
        const color = dim(0x3a2f2a, look)
        sprite(c, x - 3, y, age % 40 > 34 ? ['#.....#', '.#####.', '...#...'] : ['##...##', '..###..', '...#...'], { '#': color })
        c.set(x + (Math.sin(a) > 0 ? -1 : 1), y + 2, mix(color, P.white, 0.5)) // pale head
      },
    },
    {
      name: 'avalanche',
      frames: 90,
      weight: 2,
      when: look => look.night < 0.9,
      draw(c, look, age) {
        // a plume of powder pours down the right shoulder of the tallest peak
        const r = ridges(look)
        let px = 0
        for (let x = 0; x < c.W - 20; x++) if (r.far(x) > r.far(px)) px = x
        const fade = Math.min(1, (90 - age) / 30)
        const reach = Math.min(12, Math.floor(age / 4))
        for (let k = 1; k <= reach * 2; k++) {
          const x = px + 1 + Math.floor(k / 2)
          const y = Math.round(GROUND - r.far(x)) - (hash(k * 7 + Math.floor(age / 3)) % 3) + 1
          c.glow(x, y, P.white, 0.8 * fade * (1 - k / (reach * 2 + 3)))
          c.glow(x + 1, y + 1, P.snow, 0.5 * fade)
        }
        if (age < 20) c.glow(px, Math.round(GROUND - r.far(px)) - 1, P.white, 0.7 * (1 - age / 20))
      },
    },
    {
      name: 'paragliders',
      frames: 240,
      weight: 2,
      when: look => look.night < 0.4 && !look.wet && look.wind < 28,
      draw(c, look, age, seed) {
        // two canopies riding down the valley
        const colors = [P.red, P.peach, P.mauve, P.sky, P.yellow]
        for (let g = 0; g < 2; g++) {
          const t = (age + g * 40) / 280
          const x = Math.round(c.W * (0.95 - 0.8 * t) + (seed % 9)) - g * 11
          const y = Math.round(1 + t * 4 + 0.8 * Math.sin(age * 0.07 + g))
          sprite(c, x, y, ['.ccccc.', 'c.....c'], { c: dim(colors[(seed + g * 2) % colors.length]!, look, 0.2) })
          c.glow(x + 2, y + 2, P.ink, 0.35)
          c.glow(x + 4, y + 2, P.ink, 0.35)
          sprite(c, x + 3, y + 3, ['j', 'j'], { j: dim(P.maroon, look) })
        }
      },
    },
  ],
}
