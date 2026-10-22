import { type Canvas, hash, mix, sprite } from '../pixels'
import { type Building, byPhase, sunGlow, type Landscape, type Look, P, SCENE_H, editsOf, heightFor, lightWindows, wave, jobAccent } from './kit'
import { airJobs } from './crew'

// Tundra: a snowfield and a frozen lake under low icy hills. Turns are igloos, timber huts,
// a research station or a beacon (by number). Bridge jobs are ice-fishing tents on the lake.
// By day a low sun throws long shadows (short at noon); at night the aurora dances.

const GROUND = SCENE_H - 4 // the snowfield; two rows of lake ice run below it
const MAXH = GROUND - 5
const WOODS = [0x6b4f3f, 0x7a4a3a, 0x5f4636, 0x8a5a3a]
const ICE = 0x8fbbdc
const AURORA = [0x5cf2a0, 0x4fe0d0, 0xa56bff]
const SHADOW = { dawn: 1.4, morning: 0.8, noon: 0.25, afternoon: 0.8, dusk: 1.4, night: 0 }
const dim = (color: number, look: Look, k = 0.45) => mix(color, P.ink, k * look.night)
const sine = (x: number, f: number, p: number) => 0.5 + 0.5 * Math.sin(x * f + p)
const pingPong = (t: number, span: number) => {
  const m = t % (span * 2)
  return { x: Math.round(m < span ? m : span * 2 - m), back: m >= span }
}

/** Snow in the light of the hour: peach or pink at the edges of the day, navy at night; `shade` leans to blue shadow. */
function snowOf(look: Look, shade = 0) {
  const glow = sunGlow(look)
  const lit = mix(P.snow, glow.color, 0.3 * glow.amount)
  return mix(mix(lit, 0x6f86c0, shade), 0x1d2440, 0.62 * look.night)
}

/** Aurora curtains: bright green lower edges fading up into purple, rippling with the frame. */
function aurora(c: Canvas, look: Look, strength: number) {
  const t = look.frame
  const p = (look.seed % 628) / 100
  for (let x = 0; x < c.W; x++) {
    for (let band = 0; band < 2; band++) {
      const base = 3.5 + band * 1.6 + 1.8 * Math.sin(x * 0.045 + t * 0.02 + band * 2 + p) + 1.2 * Math.sin(x * 0.11 - t * 0.035 + band)
      const ray = (0.6 + 0.4 * Math.sin(x * 0.55 + t * 0.14 + band * 3)) * Math.min(1, Math.max(0, Math.sin(x * 0.035 - t * 0.012 + band * 1.7 + p) * 1.4))
      if (ray < 0.03) continue
      const len = 6 + 2 * Math.sin(x * 0.09 + t * 0.04)
      for (let k = 0; k < len; k++) c.glow(x, Math.round(base) - k, mix(AURORA[band]!, AURORA[2]!, (k / len) ** 1.2), strength * ray * (1 - k / len) ** 1.3)
    }
  }
}

/** Rising steam or smoke, drifting with the wind. */
function smoke(c: Canvas, look: Look, x: number, y: number, seed: number) {
  for (let k = 0; k < 5; k++) {
    const t = ((look.frame + k * 7 + seed) % 35) / 35
    c.glow(x + Math.round(t * (1.5 + look.wind / 8) + Math.sin(t * 6 + k)), y - Math.round(t * 7), P.white, 0.8 * (1 - t) * (0.6 + 0.4 * (1 - look.night)))
  }
}

/** A spruce, slim and loaded with snow. */
function spruce(c: Canvas, look: Look, cx: number, h: number, seed: number) {
  const green = dim(mix(0x2f4a47, 0x3b5a4a, (seed % 3) / 3), look)
  const half = (r: number) => Math.min(h >= 8 ? 2 : 1, r >> 1)
  c.set(cx, GROUND - 1, dim(P.woodDark, look))
  for (let r = 0; r < h; r++) {
    for (let dx = -half(r); dx <= half(r); dx++) {
      const snowed = r === 0 || Math.abs(dx) > half(r - 1) || (dx >= 0 && r % 2 === 0)
      c.set(cx + dx, GROUND - 1 - h + r, snowed ? snowOf(look, dx > 0 ? 0.15 : 0) : green)
    }
  }
}

function drift(c: Canvas, look: Look, x: number, w: number) {
  for (let k = 0; k < w; k++) c.rect(x + k, GROUND - (k > 0 && k < w - 1 ? 2 : 1), 1, k > 0 && k < w - 1 ? 2 : 1, snowOf(look, k * 2 > w ? 0.15 : 0))
}

/** Plank walls, alternate rows a shade darker. */
function wall(c: Canvas, look: Look, x0: number, w: number, y0: number, y1: number, color: number) {
  for (let y = y0; y <= y1; y++) for (let x = x0; x < x0 + w; x++) c.set(x, y, dim(x === x0 ? mix(color, P.white, 0.1) : (y - y0) % 2 ? mix(color, P.ink, 0.14) : color, look))
}

const door = (c: Canvas, look: Look, x: number) => {
  c.rect(x, GROUND - 2, 1, 2, dim(P.woodDark, look, 0.2))
  if (look.night > 0.4) c.glow(x, GROUND - 1, P.yellow, 0.55 * look.night)
}

type Parts = { eave: number; smoke: [number, number] }

/** Window slots up a wall, bottom to top, every other column from `from` to `to`. */
function wallSlots(x0: number, from: number, to: number, top: number): [number, number][] {
  const slots: [number, number][] = []
  for (let y = GROUND - 2; y >= top; y -= 2) for (let x = x0 + from; x <= x0 + to; x += 2) slots.push([x, y])
  return slots
}

/** A dome of snow blocks with a low tunnel entrance, a lit doorway and ice windows. */
function igloo(c: Canvas, look: Look, b: Building): Parts {
  const { x0, width: w, height: h } = b
  const side = (x: number) => ((x + 0.5 - x0) / w) * 2 - 1
  const colH = (x: number) => Math.round(h * Math.sqrt(Math.max(0, 1 - side(x) ** 2)))
  for (let x = x0; x < x0 + w; x++) {
    for (let y = GROUND - colH(x); y < GROUND; y++) {
      const r = GROUND - 1 - y
      const tone = snowOf(look, (x + r * 2) % 4 === 0 ? 0.3 : r % 2 ? 0.14 : 0)
      c.set(x, y, mix(mix(tone, 0x6f86c0, Math.max(0, side(x)) * 0.45), P.white, y === GROUND - colH(x) ? 0.25 * (1 - look.night) : 0))
    }
  }
  for (let dx = -1; dx <= 1; dx++) c.rect(x0 + dx, GROUND - (dx === 0 ? 3 : 2), 1, dx === 0 ? 3 : 2, snowOf(look, 0.12)) // tunnel
  c.set(x0, GROUND - 1, dim(0x232a40, look))
  const slots: [number, number][] = [[x0, GROUND - 1]]
  for (let y = GROUND - 3; y > GROUND - h; y -= 2) for (let x = x0 + 2; x <= x0 + w - 3; x += 2) if (colH(x) > GROUND - y) slots.push([x, y])
  lightWindows(c, look, b, slots, snowOf(look, 0.2))
  return { eave: GROUND - h, smoke: [x0 + (w >> 1), GROUND - h - 1] }
}

/** A timber hut under a thick drape of snow, icicles along the eave. */
function hut(c: Canvas, look: Look, b: Building): Parts {
  const { x0, width: w } = b
  const wood = WOODS[hash(b.index) % WOODS.length]!
  const top = GROUND - (b.height - 3)
  wall(c, look, x0, w, top, GROUND - 1, wood)
  for (let x = x0; x < x0 + w; x++) c.set(x, top, dim(mix(wood, P.ink, 0.45), look)) // shadow under the eave
  for (let r = 0; r < 3; r++) for (let x = x0 - 1 + r; x <= x0 + w - r; x++) c.set(x, top - 1 - r, snowOf(look, x > x0 + w / 2 ? 0.12 : 0))
  for (let x = x0 - 1; x <= x0 + w; x++) if (hash(x * 7 + b.index) % 3 === 0) c.set(x, top + 1, dim(ICE, look)) // icicles
  const cx = x0 + w - 3
  c.rect(cx, top - 5, 1, 2, dim(P.surface2, look))
  door(c, look, x0 + w - 2)
  lightWindows(c, look, b, wallSlots(x0, 1, w - 3, top), wood)
  return { eave: top - 3, smoke: [cx, top - 6] }
}

/** A research station: ribbed orange module, radar dome, a mast with a blinking light. */
function station(c: Canvas, look: Look, b: Building): Parts {
  const { x0, width: w } = b
  const paint = [0xe0743a, 0xd9553f, 0x3f9aa8][hash(b.index) % 3]!
  const top = GROUND - (b.height - 3)
  for (let y = top; y < GROUND; y++) for (let x = x0; x < x0 + w; x++) c.set(x, y, dim(y === GROUND - 1 ? mix(paint, P.ink, 0.45) : (x - x0) % 4 === 3 ? mix(paint, P.ink, 0.2) : paint, look))
  for (let x = x0; x < x0 + w; x++) if (hash(x + b.index * 3) % 3) c.set(x, top - 1, snowOf(look)) // snow on the roof
  sprite(c, x0 + w - 5, top - 2, ['.ww.', 'wwww'], { w: dim(P.snow, look, 0.3) }) // radar dome
  for (let y = top - 4; y < top; y++) c.set(x0 + 1, y, dim(P.overlay1, look))
  c.rect(x0, top - 3, 3, 1, dim(P.overlay1, look))
  if (look.frame % (b.isLive ? 6 : 16) < 3) c.set(x0 + 1, top - 5, P.red)
  door(c, look, x0 + (w >> 1))
  lightWindows(c, look, b, wallSlots(x0, 1, w - 2, top).filter(([x, y]) => x !== x0 + (w >> 1) || y !== GROUND - 2), paint)
  return { eave: top - 5, smoke: [x0 + w - 1, top - 3] }
}

/** A striped beacon tower; at night its lamp sweeps a beam each way. */
function beacon(c: Canvas, look: Look, b: Building): Parts {
  const { x0, width: w } = b
  const cx = x0 + (w >> 1)
  const bodyH = b.height - 4
  const top = GROUND - bodyH
  for (let r = 0; r < bodyH; r++) {
    const half = (w - 2 * Math.floor((r * ((w - 3) / 2)) / bodyH + 0.5)) >> 1
    for (let x = cx - half; x <= cx + half; x++) c.set(x, GROUND - 1 - r, dim(mix((r >> 1) % 2 ? 0xd9453f : P.snow, P.ink, x === cx + half ? 0.2 : 0), look))
  }
  c.rect(cx - 2, top - 1, 5, 1, dim(P.surface2, look)) // gallery
  const lamp = look.night > 0.3 ? mix(P.yellow, P.white, 0.3) : 0xe8e0b8
  c.rect(cx - 1, top - 3, 3, 2, lamp)
  c.set(cx, top - 4, dim(0xd9453f, look))
  if (look.night > 0.3) {
    const dir = look.frame % 60 < 30 ? 1 : -1
    for (let k = 2; k < 18; k++) for (let dy = -1; dy <= 0; dy++) c.glow(cx + dir * k, top - 3 + dy + (k >> 3), P.yellow, 0.35 * (1 - k / 18))
    c.glow(cx, top - 3, P.yellow, 0.4)
  }
  const slots: [number, number][] = []
  for (let y = GROUND - 3; y > top; y -= 2) slots.push([cx, y])
  lightWindows(c, look, b, slots, P.snow)
  return { eave: top - 4, smoke: [cx + 2, top - 3] }
}

/** Scaffolding round the turn being built, a worker in a parka on the top plank. */
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
  const py = planks[planks.length - 1] ?? GROUND - 3
  const wx = b.x0 + Math.round((b.width - 1) * wave(look.frame, 50, b.index))
  c.set(wx, py - 1, dim(P.peach, look))
  c.set(wx, py - 2, dim(P.snow, look))
  if (look.frame % 8 < 2) c.set(wx + 1, py - 2, P.white) // a hammer blow
}

/** The sun is low: shadows stretch away from it, longest at the edges of the day. */
function shadow(c: Canvas, look: Look, b: Building) {
  const len = Math.round(b.height * byPhase(look, SHADOW))
  for (let k = 0; k < b.width + len; k++) {
    const x = look.hour < 12 ? b.x0 + k : b.x0 + b.width - 1 - k
    c.glow(x, GROUND, 0x3a52a0, 0.5 * (1 - k / (b.width + len + 2)))
    if (k < b.width + len * 0.6) c.glow(x, GROUND + 1, 0x3a52a0, 0.35)
  }
}

const STYLES = [igloo, hut, station, beacon]
const styleOf = (index: number) => hash(index * 7 + 3) % STYLES.length

// ── life on the snow: feet on the row below the snowfield ──────────────────

const FOX = ['.....e.e', '.t..fffn', 'tttfffff']
const REINDEER = ['...a.a.', '....bbn', '.....b.', '.bbbbb.', '.bwwbw.']
const DOG = ['d..e.', 'ddddn', 'ddddd']
const SLED = ['.hh......', '.jj.bb...', '.jjbbbbb.', 'rrrrrrrrr']
const BEAR = ['..www.....', '.wwwwww.w.', 'wwwwwwwwew', 'sssssssssn', 'ww.ww.ww.w', 'ww.ww.ww.w']

/** An arctic fox by day and night, a reindeer at the edges of the day, pausing now and then. */
function walker(c: Canvas, look: Look, right: number) {
  const moving = look.frame % 120 < 70
  const span = Math.max(8, right - 20)
  const t = Math.floor(look.frame / 120) * 8.4 + Math.min(look.frame % 120, 70) * 0.12 + (look.seed % span)
  const { x, back } = pingPong(t, span)
  const step = !moving || look.frame % 6 < 3
  if (look.phase === 'dawn' || look.phase === 'dusk') {
    const legs = step ? '.bb.bb.' : '.b.b.b.'
    const palette = { b: dim(0x8a7a68, look), w: dim(0xe3dccf, look), n: dim(0xd0c4b0, look), a: dim(P.sand, look) }
    sprite(c, 4 + x, GROUND - 5, [...REINDEER, legs, legs], palette, back)
  } else {
    const fur = mix(snowOf(look), 0x7a86a8, 0.65)
    sprite(c, 4 + x, GROUND - 2, [...FOX, step ? '..f.f.f.' : '..ff.ff.'], { f: fur, t: mix(fur, P.white, 0.25), e: dim(0x4a4a5a, look), n: P.ink }, back)
  }
}

export const tundra: Landscape = {
  name: 'tundra',
  ground: GROUND,

  backdrop(c, look) {
    if (look.night > 0.5) aurora(c, look, 0.42 * (look.wet ? 0.3 : 1))
    const ph = (n: number) => (hash(look.seed + n * 101) % 628) / 100
    const [a, b, d, e] = [ph(0), ph(1), ph(2), ph(3)] as [number, number, number, number]
    // far ice ridge with a toothed edge, then nearer rolling hills
    for (let x = 0; x < c.W; x++) {
      const far = 2.5 + 2.2 * sine(x, 0.035, a) + 1.2 * sine(x, 0.09, b) + (hash(x * 3 + look.seed) % 7 === 0 ? 1 : 0)
      const mid = 1.4 + 1.8 * sine(x, 0.06, d) + sine(x, 0.17, e)
      for (let y = Math.round(GROUND - far); y < GROUND; y++) c.set(x, y, mix(mix(snowOf(look, 0.55), look.horizon, 0.45), snowOf(look, 0.7), (y - GROUND + far) / far))
      for (let y = Math.round(GROUND - mid); y < GROUND; y++) c.set(x, y, mix(snowOf(look, y === Math.round(GROUND - mid) ? 0 : 0.18), 0x8aa4cf, 0.25 * ((y - GROUND + mid) / mid)))
    }
  },

  floor(c, look) {
    const ice = mix(mix(ICE, look.horizon, 0.25), 0x141a30, 0.65 * look.night)
    for (let x = 0; x < c.W; x++) {
      const h = hash(x * 7 + look.seed)
      c.set(x, GROUND, snowOf(look, h % 3 ? 0.04 : 0))
      c.set(x, GROUND + 1, snowOf(look, 0.1 + 0.05 * (h % 3)))
      for (let y = GROUND + 2; y < SCENE_H; y++) {
        let tone = mix(ice, P.ink, 0.1 * (y - GROUND - 2))
        if (hash(x * 3 + y + look.seed) % 13 === 0) tone = mix(tone, 0x4a62a8, 0.45) // cracks
        else if ((x + y * 5) % 11 === 0) tone = mix(tone, P.white, 0.3 * (1 - look.night)) // sheen
        if (look.night > 0.5) tone = mix(tone, AURORA[hash(x) % 2]!, 0.12 + 0.08 * Math.sin(x * 0.2 + look.frame * 0.05)) // the aurora, reflected
        c.set(x, y, tone)
      }
      for (const y of [GROUND, GROUND + 2]) if (hash(x * 5 + y * 11 + Math.floor(look.frame / 4)) % 53 === 0) c.glow(x, y, P.white, 0.8 * (1 - look.night * 0.5)) // diamond dust
    }
  },

  size(kinds, index) {
    const e = Math.min(3, editsOf(kinds))
    switch (styleOf(index)) {
      case 0: return { width: 9 + e, height: heightFor(kinds, 4, 7) }
      case 1: return { width: 6 + e, height: heightFor(kinds, 5, MAXH) }
      case 2: return { width: 8 + e, height: heightFor(kinds, 6, MAXH) }
      default: return { width: 5 + 2 * Math.min(1, e >> 1), height: heightFor(kinds, 7, MAXH + 1) }
    }
  },

  gap(index) {
    return 2 + (hash(index * 31) % 3)
  },

  building(c, look, b) {
    const parts = STYLES[styleOf(b.index)]!(c, look, b)
    shadow(c, look, b)
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
      if (room >= 5 && h % 10 < 4) {
        const ph = 5 + ((h >>> 4) % 5)
        spruce(c, look, x + 2, ph, h >>> 8)
        x += 5 + 1 + ((h >>> 9) % 6)
      } else {
        const w = Math.min(room, 3 + ((h >>> 6) % 3))
        drift(c, look, x, w)
        x += w + 1
      }
    }
  },

  jobs: airJobs,

  foreground(c, look, right) {
    walker(c, look, right)
  },

  events: [
    {
      name: 'aurora',
      frames: 240,
      weight: 6,
      when: look => look.night > 0.6,
      draw(c, look, age) {
        aurora(c, look, 0.8 * Math.min(1, age / 30, (240 - age) / 30))
      },
    },
    {
      name: 'corona',
      frames: 140,
      weight: 2,
      when: look => look.night > 0.6,
      draw(c, look, age, seed) {
        // rays fan down from one point overhead
        const cx = Math.round(c.W * 0.3 + (seed % Math.max(1, Math.round(c.W * 0.3))))
        const fade = Math.min(1, age / 20, (140 - age) / 20)
        for (let i = -8; i <= 8; i++) {
          const ang = i * 0.17 + Math.sin(look.frame * 0.03 + i) * 0.05
          for (let k = 1; k < 12; k++) c.glow(Math.round(cx + Math.sin(ang) * k * 1.6), Math.round(Math.cos(ang) * k * 0.7), mix(AURORA[0]!, P.white, 0.3 * (1 - k / 12)), fade * 0.55 * (1 - k / 12))
        }
        for (let dx = -2; dx <= 2; dx++) c.glow(cx + dx, 0, P.white, fade * 0.5 * (1 - Math.abs(dx) / 3))
      },
    },
    {
      name: 'polar bear',
      frames: 320,
      weight: 3,
      when: look => look.night < 0.8,
      draw(c, look, age, seed) {
        // a bear lumbers across the snowfield
        const dir = seed % 2 ? 1 : -1
        const x = Math.round((dir > 0 ? age / 320 : 1 - age / 320) * (c.W + 20)) - 10
        const legs = age % 12 < 6 ? 'ww.ww.ww.w' : '.ww.ww.ww.'
        const fur = mix(snowOf(look), 0xe0cfa8, 0.55)
        sprite(c, x, GROUND - 4, [...BEAR.slice(0, 4), legs, legs], { w: fur, s: mix(fur, 0x8a8ca8, 0.4), e: P.ink, n: P.ink }, dir < 0)
      },
    },
    {
      name: 'sled team',
      frames: 260,
      weight: 3,
      when: look => look.night < 0.8,
      draw(c, look, age, seed) {
        // four dogs in a line pull a sled and its musher
        const dir = seed % 2 ? 1 : -1
        const lead = Math.round((dir > 0 ? age / 260 : 1 - age / 260) * (c.W + 70)) - 35
        const step = age % 6 < 3
        for (let k = 0; k < 4; k++) {
          const coat = [0x8a8aa0, 0xb8a58a, 0xd0d4e4, 0x6a5a50][(seed + k) % 4]!
          const x = lead + dir * (9 + k * 6)
          sprite(c, x, GROUND - 2, [...DOG, step ? '.d.d.' : 'd..d.'], { d: dim(coat, look), e: dim(coat, look), n: P.ink }, dir < 0)
          c.glow(x + 2 - dir * 4, GROUND, P.overlay2, 0.4) // the line back to the sled
        }
        sprite(c, lead - (dir > 0 ? 0 : 8), GROUND - 2, SLED, { h: dim(P.red, look, 0.2), j: dim(P.peach, look), b: dim(P.wood, look), r: dim(P.surface2, look) }, dir < 0)
      },
    },
    {
      name: 'snowy owl',
      frames: 200,
      weight: 2,
      when: look => look.night > 0.4,
      draw(c, look, age, seed) {
        // a pale owl glides silent over the snow
        const x = Math.round((seed % 2 ? age / 200 : 1 - age / 200) * (c.W + 12)) - 6
        const y = 5 + Math.round(1.5 * Math.sin(age * 0.06))
        const wings = age % 14 < 7 ? ['w.....w', 'ww.e.ww', '.wwwww.'] : ['.......', '.wwewww.', 'ww.w.ww']
        sprite(c, x, y, wings, { w: mix(P.snow, look.top, 0.15 * look.night), e: P.yellow })
      },
    },
  ],
}
