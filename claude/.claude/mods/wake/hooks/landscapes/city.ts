import { type Canvas, hash, mix, sprite } from '../pixels'
import { byPhase, type Landscape, type Look, P, SCENE_H, editsOf, farTone, foliage, heightFor, lightWindows, wave, jobAccent } from './kit'
import { airJobs } from './crew'

// City: towers (one per turn) over a far skyline, shopfronts at street level, and a busy
// street: cars, taxis, vans, buses and bikes that stop at the lights, pedestrians, trees,
// benches, hydrants, a food cart. Who is out and what is lit changes with look.phase.

const BODIES = [0x313244, 0x2e3041, 0x363a4f, 0x2b2d3d, 0x34364a]
const GROUND = SCENE_H - 5 // the sidewalk; the road's four rows (ROAD..) run below it
const ROAD = GROUND + 1
const AWNINGS: [number, number][] = [[P.red, P.rosewater], [P.green, P.text], [P.blue, P.text], [P.peach, P.yellow], [P.mauve, P.pink]]
const NEON = [P.pink, P.sky, P.green, P.yellow, P.peach]

const dimmed = (look: Look, col: number, t = 0.5) => mix(col, P.ink, look.night * t)
const wrap = (v: number, m: number) => ((Math.round(v) % m) + m) % m
const warmLight = (look: Look) => look.phase === 'dusk' || look.phase === 'dawn'

export const city: Landscape = {
  name: 'city',
  ground: GROUND,

  backdrop(c, look) {
    // far skyline (the deepest layer), then a mid skyline a shade nearer
    for (const [depth, minH, spanH] of [[0, 5, 5], [1, 3, 4]] as const) {
      const tone = farTone(look, depth)
      for (let x = 0, seg = 0; x < c.W; seg++) {
        const h = hash(look.seed + seg * 7 + depth * 1013)
        const w = 2 + (h % 6)
        const bh = minH + ((h >>> 8) % spanH)
        for (let k = 0; k < w; k++) {
          for (let y = GROUND - bh; y < GROUND; y++) c.set(x + k, y, tone)
          if (look.night > 0.3 && hash((x + k) * 17 + seg + depth) % (depth ? 7 : 11) === 0) c.set(x + k, GROUND - 1 - (hash(x + k + depth) % Math.max(1, bh - 1)), mix(tone, P.yellow, 0.3 * look.night))
        }
        if (depth === 0 && h % 9 === 0 && bh > 6) c.set(x + Math.floor(w / 2), GROUND - bh - 1, tone) // a spire
        x += w + ((h >>> 4) % 2)
      }
    }
  },

  floor(c, look) {
    const walk = look.snowy ? mix(P.snow, P.surface1, 0.3) : mix(P.overlay0, P.surface0, 0.25 + look.night * 0.6)
    const road = look.wet ? mix(P.surface1, P.mantle, 0.5) : mix(P.surface1, P.mantle, 0.2 + look.night * 0.55)
    for (let x = 0; x < c.W; x++) {
      c.set(x, GROUND, x % 5 === 0 ? mix(walk, P.ink, 0.2) : walk) // paving joints
      c.set(x, ROAD, look.snowy ? mix(P.snow, P.overlay0, 0.4) : mix(P.overlay0, P.surface0, 0.3 + look.night * 0.4)) // the kerb
      for (let y = ROAD + 1; y < SCENE_H; y++) c.set(x, y, road)
      if (x % 8 < 4) c.set(x, ROAD + 2, mix(P.yellow, road, 0.6)) // lane dashes
    }
    for (const lx of signalXs(c.W)) for (let x = lx + 3; x < lx + 9; x += 2) for (let y = ROAD + 1; y < SCENE_H; y++) c.set(x, y, mix(road, P.text, 0.5)) // zebra crossing
  },

  size(kinds) {
    return { width: 5 + Math.min(3, editsOf(kinds)), height: heightFor(kinds, 4, GROUND - 3, 1.1) }
  },

  gap(index) {
    return index % 7 === 3 ? 6 : hash(index * 31) % 3 // now and then a pocket park
  },

  building(c, look, b) {
    const y0 = GROUND - b.height
    const x1 = b.x0 + b.width - 1
    let style = hash(b.index * 7 + 3) % 11
    if ((style === 7 || style === 8) && b.height < 6) style = 0
    if ((style === 9 || style === 10) && b.height > 7) style = 6
    const body = BODIES[hash(b.index) % BODIES.length]!
    const glass = style === 6
    for (let y = y0; y < GROUND; y++) {
      const [xa, xb] = extent(style, b, y)
      // glass reflects the sky; at golden hour the lit side catches the sun
      const tint = glass ? mix(body, mix(look.top, look.horizon, (y - y0) / b.height), 0.4 * (1 - look.night * 0.7)) : body
      const lit = mix(mix(tint, look.isDay ? P.yellow : P.text, 0.08), P.peach, warmLight(look) ? 0.4 : 0)
      for (let x = xa; x <= xb; x++) {
        if ((style === 2 && y === y0 && (x === b.x0 || x === x1)) || (style === 3 && y - y0 < x - b.x0 - (b.width - 3))) continue
        c.set(x, y, x === xa ? lit : x === xb ? mix(tint, P.ink, 0.25) : tint)
      }
    }
    if (look.snowy) {
      const [xa, xb] = extent(style, b, y0)
      for (let x = xa; x <= xb; x++) if (c.get(x, y0) !== 0 && (style !== 2 || (x !== b.x0 && x !== x1))) c.set(x, y0, P.snow)
    }
    if (style === 5) for (let y = y0 + 1; y < GROUND; y += 3) for (let x = b.x0; x <= x1; x++) c.glow(x, y, P.surface2, 0.25) // banded floors
    if (glass) {
      const t = (look.frame + b.index * 13) % 60
      if (t < b.height) c.glow(b.x0 + 1 + (t % Math.max(1, b.width - 2)), y0 + t, warmLight(look) ? P.peach : P.white, 0.5) // a glint sliding down
    }
    const slots: [number, number][] = []
    for (let y = GROUND - 3; y > y0; y -= 2) {
      const [xa, xb] = extent(style, b, y)
      for (let x = xa + 1; x <= xb - 1; x += 2) slots.push([x, y])
      if (xb - xa < 2) slots.push([xa, y])
    }
    lightWindows(c, look, b, slots, body)
    if (b.isLive) fence(c, look, b)
    else shop(c, look, b.x0, x1, hash(b.index * 17 + 1), body)
    roof(c, look, b, style, body)
    if (b.kinds.includes('fail') && look.frame % 10 < 5) c.set(x1, y0 - 1, P.red)
    if (b.isLive) crane(c, look, b)
  },

  filler(c, look, x0, x1) {
    for (let x = x0; x < x1; ) {
      const h = hash(x * 7 + look.seed)
      const room = x1 - x
      let used = room
      if (room >= 6 && h % 6 === 0) {
        used = Math.min(room, 6 + ((h >>> 4) % 5))
        park(c, look, x, used, h)
      } else if (room >= 4) {
        used = Math.min(room, 4 + ((h >>> 5) % 4))
        lowrise(c, look, x, used, h)
      } else if (room >= 3) tree(c, look, x + 1, false, h)
      x += used
    }
  },

  jobs: airJobs,

  foreground(c, look, right) {
    const flow = flowOf(look.frame)
    furniture(c, look, right)
    cart(c, look, right)
    people(c, look, right)
    steam(c, look, right)
    signals(c, look, flow)
    if (look.wet && !look.snowy) puddles(c, look)
    if (look.snowy) snowbanks(c, look, right)
    traffic(c, look, flow)
  },

  events: [
    {
      name: 'train',
      frames: 90,
      weight: 3,
      draw(c, look, age) {
        // an elevated train crossing on the line above the street
        const x = Math.round((age / 90) * (c.W + 40)) - 35
        for (let k = 0; k < 30; k++) {
          const lit = k % 6 === 1 || k % 6 === 2 || k % 6 === 4
          c.set(x + k, GROUND - 5, k % 6 === 5 ? P.surface0 : P.overlay1)
          c.set(x + k, GROUND - 4, k % 6 === 5 ? P.surface0 : lit && look.night > 0.3 ? P.yellow : lit ? P.sky : P.surface2)
        }
        for (let k = 0; k < c.W; k += 9) c.set(k, GROUND - 3, P.surface1) // viaduct piers
      },
    },
    {
      name: 'blimp',
      frames: 220,
      weight: 1,
      when: look => look.night < 0.7,
      draw(c, _look, age) {
        const x = Math.round((age / 220) * (c.W + 16)) - 10
        sprite(c, x, 2, ['.bbbbb.', 'bbrrrbb', '.bbbbb.', '...g...'], { b: P.overlay2, r: P.red, g: P.surface2 })
        if (age % 10 < 5) c.set(x + 3, 3, P.white)
      },
    },
    {
      name: 'searchlights',
      frames: 120,
      weight: 2,
      when: look => look.night > 0.6,
      draw(c, _look, age) {
        for (const base of [0.3, 0.6]) {
          const angle = Math.sin(age * 0.05 + base * 10) * 0.6
          const x0 = Math.round(c.W * base)
          for (let y = GROUND - 1; y >= 0; y--) c.glow(x0 + Math.round((GROUND - y) * angle), y, P.yellow, 0.18)
        }
      },
    },
    {
      name: 'helicopter',
      frames: 200,
      weight: 2,
      draw(c, look, age, seed) {
        const dir = seed % 2 ? 1 : -1
        const t = age / 200
        const x = Math.round(dir > 0 ? t * (c.W + 30) - 15 : (1 - t) * (c.W + 30) - 15)
        const y = 3 + Math.round(Math.sin(age * 0.1))
        for (const dx of age % 2 ? [-3, -2, -1, 0, 1, 2, 3] : [-1, 0, 1]) c.set(x + dx, y - 1, P.overlay2) // the rotor
        for (const [dx, col] of [[0, P.overlay1], [dir, P.sky], [-dir, P.overlay1], [-2 * dir, P.overlay0], [-3 * dir, P.overlay0]] as const) c.set(x + dx, y, col)
        c.set(x - 4 * dir, y - 1, P.overlay0)
        for (let k = -1; k <= 1; k++) c.set(x + k, y + 1, P.surface2) // skids
        if (age % 10 < 5) c.set(x - 3 * dir, y, P.red)
        if (look.night < 0.4) return
        const tx = x + dir * 6 + Math.round(Math.sin(age * 0.06) * 10) // the spotlight sweeps the street
        for (let i = 0; i <= 12; i++) {
          const bx = x + Math.round(((tx - x) * i) / 12)
          const by = y + 1 + Math.round(((GROUND + 1 - y - 1) * i) / 12)
          for (let w = -(i >> 2); w <= i >> 2; w++) c.glow(bx + w, by, P.white, 0.2 - Math.abs(w) * 0.04)
        }
        for (let dx = -3; dx <= 3; dx++) c.glow(tx + dx, GROUND, P.white, 0.4 - Math.abs(dx) * 0.08)
      },
    },
    {
      name: 'drone show',
      frames: 180,
      weight: 1.5,
      when: look => look.night > 0.7 && !look.wet,
      draw(c, _look, age, seed) {
        const n = 16
        const cx = c.W * 0.3 + (seed % Math.max(1, Math.round(c.W * 0.3)))
        const stage = Math.floor(age / 45)
        const f = Math.min(1, Math.max(0, ((age % 45) - 30) / 15))
        for (let i = 0; i < n; i++) {
          const [ax, ay] = formation(stage % 4, i, n, age)
          const [bx, by] = formation((stage + 1) % 4, i, n, age)
          const x = Math.round(cx + ax + (bx - ax) * f)
          const y = Math.round(4 + ay + (by - ay) * f)
          const col = [P.yellow, P.pink, P.sky, P.green][i % 4]!
          if ((age + i) % 7 === 0) continue
          c.set(x, y, mix(col, P.white, 0.4))
          for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]] as const) c.glow(x + dx, y + dy, col, 0.18)
        }
      },
    },
    {
      name: 'parade',
      frames: 260,
      weight: 2,
      when: look => look.night < 0.5 && !look.wet,
      draw(c, look, age, seed) {
        const dir = seed % 2 ? 1 : -1
        const head = Math.round((age / 260) * (c.W + 70)) - 12
        const at = (back: number) => (dir > 0 ? head - back : c.W - head + back)
        for (const bx of [at(0), at(8)]) {
          c.set(bx, ROAD, P.peach)
          c.set(bx, ROAD + 1, P.surface2)
          c.set(bx, ROAD + 2, P.surface2)
          c.set(bx, ROAD + 3, age % 4 < 2 ? P.surface1 : P.crust)
        }
        for (let k = 1; k < 8; k++) {
          c.set(at(k) + 0, ROAD + 1, [P.red, P.yellow, P.red, P.pink][k % 4]!)
          c.set(at(k), ROAD + 2, k % 2 ? P.yellow : P.red) // the banner
        }
        for (let m = 0; m < 5; m++) {
          const mx = at(14 + m * 4)
          c.set(mx, ROAD - 1, P.red) // plume
          c.set(mx, ROAD, P.peach)
          c.set(mx, ROAD + 1, m % 2 ? P.red : P.text)
          c.set(mx, ROAD + 2, m % 2 ? P.red : P.text)
          c.set(mx + dir, ROAD + 1 + ((age >> 2) + m) % 2, P.yellow) // an instrument
          c.set(mx, ROAD + 3, (age + m) % 4 < 2 ? P.crust : P.surface0)
        }
        for (let k = 0; k < 11; k++) for (let y = ROAD + 1; y < SCENE_H; y++) c.set(at(38 + k), y, y === ROAD + 1 ? P.mauve : k % 3 === 0 ? P.pink : P.peach) // a float
        for (let i = 0; i < 5; i++) {
          const bx = at(40 + i * 2)
          const by = 5 - Math.round(1.5 * Math.sin(age * 0.1 + i))
          c.set(bx, by, [P.red, P.yellow, P.sky, P.green, P.mauve][i]!)
          c.set(bx, by + 1, [P.red, P.yellow, P.sky, P.green, P.mauve][i]!)
          for (let y = by + 2; y < ROAD + 1; y += 2) c.glow(bx, y, P.text, 0.4)
        }
        for (let i = 0; i < 10; i++) c.glow(at(((hash(seed + i) % 40) + age) % 44) , (hash(i * 5 + (age >> 1)) % 8) + 2, [P.pink, P.yellow, P.sky][i % 3]!, 0.7) // confetti
        if (look.night > 0.2) c.glow(at(20), ROAD, P.yellow, 0.2)
      },
    },
  ],
}

/** A drone formation: a circle, a heart, a star, a wave. */
function formation(shape: number, i: number, n: number, age: number): [number, number] {
  const t = (i / n) * Math.PI * 2
  if (shape === 0) return [Math.cos(t) * 6, Math.sin(t) * 3.5]
  if (shape === 1) return [Math.sin(t) ** 3 * 5.5, (-(13 * Math.cos(t) - 5 * Math.cos(2 * t) - 2 * Math.cos(3 * t) - Math.cos(4 * t)) / 13) * 3.8]
  if (shape === 2) return [Math.cos(t) * (i % 2 ? 2.5 : 6.5), Math.sin(t) * (i % 2 ? 1.5 : 4)]
  return [(i / (n - 1) - 0.5) * 18, Math.sin(i * 0.8 + age * 0.2) * 2]
}

// ── towers ─────────────────────────────────────────────────────────────────

/** The columns a tower covers at row `y`: setbacks for art deco, a slim shaft and deck for the needle. */
function extent(style: number, b: { x0: number; width: number; height: number }, y: number): [number, number] {
  const x1 = b.x0 + b.width - 1
  const mid = b.x0 + (b.width >> 1)
  const top = y - (GROUND - b.height)
  if (style === 7) return top < Math.ceil(b.height * 0.3) ? [b.x0 + 2, x1 - 2] : top < Math.ceil(b.height * 0.6) ? [b.x0 + 1, x1 - 1] : [b.x0, x1]
  if (style === 8 && y < GROUND - 2) return top === 0 ? [mid, mid] : top === 1 ? [mid - 2, mid + 2] : top < Math.ceil(b.height * 0.55) ? [mid - 1, mid + 1] : [b.x0, x1]
  return [b.x0, x1]
}

/** Rooftop furniture: antenna, water tower, a flickering neon sign, a billboard. */
function roof(c: Canvas, look: Look, b: { x0: number; width: number; height: number; index: number }, style: number, body: number) {
  const y0 = GROUND - b.height
  const x1 = b.x0 + b.width - 1
  const mid = b.x0 + (b.width >> 1)
  if (style === 1 && y0 > 2) {
    c.set(mid, y0 - 1, P.surface1)
    c.set(mid, y0 - 2, P.surface1)
    if (look.frame % 16 < 8) c.set(mid, y0 - 3, P.red)
  } else if (style === 4 && y0 > 2) {
    c.set(b.x0 + 1, y0 - 1, P.surface1)
    c.set(b.x0 + 1, y0 - 2, mix(body, P.text, 0.12))
    c.set(b.x0 + 2, y0 - 2, mix(body, P.text, 0.12)) // a water tower
  } else if (style === 9) {
    const neon = NEON[hash(b.index) % NEON.length]!
    const on = look.night > 0.3 && (look.frame + b.index * 7) % 41 > 3 && (look.frame + b.index) % 17 !== 0 // it flickers
    c.set(b.x0 + 1, y0 - 1, P.surface1)
    c.set(x1 - 1, y0 - 1, P.surface1)
    for (let x = b.x0; x <= x1; x++) for (let dy = 0; dy < 2; dy++) {
      c.set(x, y0 - 3 + dy, P.crust)
      if (hash(x * 13 + dy * 7 + b.index) % 3 !== 0) c.set(x, y0 - 3 + dy, on ? neon : mix(neon, P.crust, 0.6))
    }
    if (on) for (let x = b.x0 - 1; x <= x1 + 1; x++) c.glow(x, y0 - 2, neon, 0.18)
  } else if (style === 10) {
    const ad = [P.red, P.blue, P.green, P.mauve, P.peach][hash(b.index * 3) % 5]!
    c.set(b.x0 + 1, y0 - 1, P.surface1)
    c.set(x1 - 1, y0 - 1, P.surface1)
    for (let x = b.x0; x <= x1; x++) for (let dy = 0; dy < 3; dy++) c.set(x, y0 - 4 + dy, dy === 1 && x % 2 ? P.white : dimmed(look, ad, 0.3))
    if (look.night > 0.3) for (let x = b.x0; x <= x1; x++) c.glow(x, y0 - 4, P.yellow, 0.35) // lit from above
  }
}

/** The tower under construction hides behind a striped fence (no shop yet). */
function fence(c: Canvas, look: Look, b: { x0: number; width: number }) {
  for (let x = b.x0; x < b.x0 + b.width; x++) {
    c.set(x, GROUND - 1, x % 2 ? dimmed(look, P.peach, 0.3) : P.white)
    c.set(x, GROUND - 2, P.surface2)
  }
  c.set(b.x0 + b.width, GROUND - 1, P.peach) // a cone
}

function crane(c: Canvas, look: Look, b: { x0: number; width: number; height: number }) {
  const y0 = GROUND - b.height
  for (let y = y0; y < GROUND; y++) for (let x = b.x0; x < b.x0 + b.width; x++) if ((x + y) % 3 === 0) c.glow(x, y, P.yellow, 0.18)
  const mast = b.x0 + b.width
  const jib = Math.max(0, y0 - 3)
  for (let y = jib; y < GROUND - 1; y++) c.set(mast, y, mix(P.yellow, P.ink, 0.45))
  for (let x = b.x0 - 3; x <= mast + 1; x++) c.set(x, jib, mix(P.yellow, P.ink, 0.35))
  const hook = b.x0 - 2 + Math.round(3 * wave(look.frame, 30))
  c.set(hook, jib + 1, P.surface1)
  c.set(hook, jib + 2, mix(P.yellow, P.ink, 0.2))
  if (look.frame % 8 < 4) c.set(mast, jib - 1, P.red)
}

/** A ground-floor shop: an awning, glass that reflects the sky by day and glows at night, a door. */
function shop(c: Canvas, look: Look, x0: number, x1: number, hs: number, body: number) {
  const [a1, a2] = AWNINGS[hs % AWNINGS.length]!
  const dusky = look.night > 0.3 || look.phase === 'dusk'
  const shut = look.phase === 'dawn' // shops open from the morning
  const open = !shut && (hs % 3 !== 0 || look.phase !== 'night')
  const glow = [P.yellow, P.peach, P.pink, P.sky, P.teal][(hs >>> 8) % 5]!
  const glass = dusky ? (open ? mix(glow, body, 0.15) : mix(body, P.ink, 0.3)) : mix(P.sky, body, 0.5)
  const door = x0 + 1 + ((hs >>> 4) % Math.max(1, x1 - x0 - 1))
  for (let x = x0; x <= x1; x++) {
    c.set(x, GROUND - 2, shut ? P.surface1 : dimmed(look, mix((x - x0) % 2 ? a1 : a2, body, 0.45), 0.4)) // the awning (rolled up and shuttered at dawn)
    c.set(x, GROUND - 1, x === door ? P.woodDark : glass)
    if (dusky && open && x !== door) c.glow(x, GROUND, glow, 0.25) // light spilling on the pavement
  }
  if (dusky && open && look.frame % 20 < 14) c.set(x1, GROUND - 1, P.pink) // an OPEN sign
}

/** A quiet mid-rise between the turns' towers: city depth, not information, so it stays muted. */
function lowrise(c: Canvas, look: Look, x: number, w: number, h: number) {
  const ht = 4 + ((h >>> 9) % 4)
  const body = mix(mix(BODIES[h % BODIES.length]!, look.horizon, 0.25), P.ink, look.night * 0.3)
  for (let yy = GROUND - ht; yy < GROUND; yy++) for (let xx = x; xx < x + w; xx++) c.set(xx, yy, xx === x ? mix(body, P.white, 0.05) : body)
  for (let yy = GROUND - 2; yy > GROUND - ht; yy -= 2) {
    for (let xx = x + 1; xx < x + w - 1; xx += 2) {
      const on = look.night > 0.3 && hash(xx * 5 + yy + look.seed) % 3 === 0
      c.set(xx, yy, on ? mix(P.yellow, body, 0.45) : mix(look.horizon, body, 0.7)) // dim panes, a few lit at night
    }
  }
}

// ── street life ────────────────────────────────────────────────────────────

function tree(c: Canvas, look: Look, x: number, tall: boolean, seed: number) {
  const [leaf, dark] = foliage(look.season, seed)
  const trunk = dimmed(look, P.wood, 0.4)
  const th = tall ? 3 : 2
  c.set(x - 1, GROUND - 1, P.surface1) // planter
  c.set(x, GROUND - 1, P.surface1)
  c.set(x + 1, GROUND - 1, P.surface1)
  for (let k = 0; k < th; k++) c.set(x, GROUND - 2 - k, trunk)
  const top = GROUND - 2 - th
  if (look.season === 'winter') {
    for (const [dx, dy] of [[-1, 0], [1, 0], [0, -1], [-1, -1], [1, -1]] as const) c.set(x + dx, top + dy, dimmed(look, 0x5a4a40, 0.3))
    if (look.snowy) c.set(x, top - 1, P.snow)
    return
  }
  const rows = tall ? 3 : 2
  for (let r = 0; r < rows; r++) for (let dx = -(tall && r === 1 ? 2 : 1); dx <= (tall && r === 1 ? 2 : 1); dx++) c.set(x + dx, top - r, dimmed(look, (dx + r) % 2 ? dark : leaf, 0.4))
  if (look.snowy) c.set(x, top - rows + 1, P.snow)
}

function bench(c: Canvas, look: Look, x: number) {
  const wood = dimmed(look, P.wood, 0.4)
  for (let k = 0; k < 4; k++) c.set(x + k, GROUND - 2, wood)
  for (let k = 0; k < 3; k++) c.set(x + k, GROUND - 3, mix(wood, P.ink, 0.2)) // the back
  c.set(x, GROUND - 1, P.surface1)
  c.set(x + 3, GROUND - 1, P.surface1)
}

function busStop(c: Canvas, look: Look, x: number) {
  for (let k = 0; k < 7; k++) c.set(x + k, GROUND - 4, P.surface1) // roof
  for (const px of [x, x + 6]) for (let y = GROUND - 3; y < GROUND; y++) c.set(px, y, P.overlay0)
  for (let k = 1; k < 6; k++) for (let y = GROUND - 3; y < GROUND - 1; y++) c.glow(k + x, y, look.night > 0.3 ? P.yellow : P.sky, look.night > 0.3 ? 0.4 : 0.2) // glass and a lit timetable
  for (let k = 1; k < 6; k++) c.set(x + k, GROUND - 1, dimmed(look, P.wood, 0.4)) // the bench
  if (look.phase === 'morning' || look.phase === 'dusk') for (const px of [x + 2, x + 4]) {
    c.set(px, GROUND - 4 + 1, P.peach)
    c.set(px, GROUND - 2, [P.blue, P.red, P.green][px % 3]!) // commuters waiting
  }
}

/** Fixed street furniture along the pavement: trees in planters, benches, hydrants, signs, bus stops. */
function furniture(c: Canvas, look: Look, right: number) {
  for (let x = 7 + (look.seed % 5); x < right - 8; x += 19) {
    const h = hash(x * 31 + look.seed)
    switch (h % 8) {
      case 0:
      case 1:
        tree(c, look, x + 1, h % 5 === 0, h)
        break
      case 2:
      case 7:
        if (look.phase === 'noon' || look.phase === 'afternoon') parasol(c, look, x, h) // cafe terraces at lunch
        else if (h % 2) bench(c, look, x)
        break
      case 3:
        bench(c, look, x)
        break
      case 4:
        c.set(x, GROUND - 1, P.red)
        c.set(x, GROUND - 2, P.red)
        c.set(x, GROUND - 3, mix(P.red, P.white, 0.3))
        break
      case 5:
        for (let y = GROUND - 4; y < GROUND; y++) c.set(x, y, P.overlay0)
        c.set(x + 1, GROUND - 4, P.green)
        c.set(x - 1, GROUND - 4, P.green)
        c.set(x + 1, GROUND - 5, P.text) // a street sign
        break
      case 6:
        if (x > 24) busStop(c, look, x)
        break
    }
  }
}

function parasol(c: Canvas, look: Look, x: number, h: number) {
  const col = mix([P.red, P.blue, P.yellow, P.pink, P.teal][h % 5]!, P.surface0, 0.3)
  for (let k = -1; k <= 1; k++) c.set(x + 1 + k, GROUND - 4, k === 0 ? mix(col, P.white, 0.3) : col)
  c.set(x + 1, GROUND - 3, P.overlay0)
  c.set(x + 1, GROUND - 2, P.overlay0)
  c.set(x, GROUND - 1, P.surface1)
  c.set(x + 2, GROUND - 1, P.surface1)
  c.set(x, GROUND - 2, P.rosewater) // a diner
  if (look.frame % 40 < 4) c.set(x + 2, GROUND - 2, P.white)
}

function cart(c: Canvas, look: Look, right: number) {
  if (look.phase !== 'noon' && look.phase !== 'afternoon') return
  const x = 14 + (look.seed % 23) * 3 % Math.max(1, right - 30)
  for (let k = 0; k < 5; k++) c.set(x + k, GROUND - 4, k % 2 ? P.red : P.white) // umbrella
  c.set(x + 2, GROUND - 3, P.overlay0)
  for (let k = 0; k < 5; k++) c.set(x + k, GROUND - 2, P.surface1)
  c.set(x + 1, GROUND - 1, P.crust)
  c.set(x + 4, GROUND - 1, P.crust)
  for (let i = 0; i < 3; i++) c.glow(x + 2 + Math.round(Math.sin((look.frame + i * 5) * 0.3)), GROUND - 5 - i, P.white, 0.5 - i * 0.12) // steam
  for (const px of [x - 3, x - 5]) person(c, look, px, hash(px + look.seed), 0, false)
}

function person(c: Canvas, look: Look, x: number, h: number, dir: number, jog: boolean) {
  const skin = [P.peach, P.rosewater, P.flamingo, 0xc8956e][h % 4]!
  const coat = dimmed(look, mix(jog ? [P.red, P.green, P.yellow][h % 3]! : [P.blue, P.red, P.green, P.mauve, P.surface2, P.yellow, P.teal][(h >>> 3) % 7]!, P.surface0, 0.35), 0.3)
  const legs = mix(P.surface2, P.crust, 0.4 + look.night * 0.3)
  c.set(x, GROUND - 4, skin)
  c.set(x, GROUND - 3, coat)
  c.set(x, GROUND - 2, coat)
  c.set(x, GROUND - 1, legs)
  if (dir !== 0 && (Math.floor(look.frame / (jog ? 1 : 3)) + h) % 2 === 0) c.set(x + dir, GROUND - 1, legs) // a stride
  if (dir !== 0 && (look.phase === 'morning' || look.phase === 'dawn') && h % 3 === 0 && !jog) c.set(x + dir, GROUND - 2, P.woodDark) // a briefcase
  if (look.wet && dir !== 0) {
    const brolly = dimmed(look, mix([P.red, P.blue, P.mauve, P.yellow, P.teal][h % 5]!, P.surface0, 0.35), 0.3)
    for (let k = -1; k <= 1; k++) c.set(x + k, GROUND - 5, brolly)
    c.set(x, GROUND - 6, brolly)
  }
}

/** Walkers: commuters and joggers in the morning, crowds at noon and dusk, a few at night. */
function people(c: Canvas, look: Look, right: number) {
  const base = byPhase(look, { dawn: 2, morning: 5, noon: 5, afternoon: 4, dusk: 5, night: 1 })
  const n = Math.max(1, Math.round((base * right) / 150))
  for (let k = 0; k < n; k++) {
    const h = hash(look.seed * 7 + k * 977)
    const dir = k % 2 ? 1 : -1
    const jog = (look.phase === 'dawn' || look.phase === 'morning') && k % 4 === 0
    person(c, look, wrap((h % right) + dir * look.frame * (jog ? 0.45 : 0.1 + (h % 5) * 0.03), right), h, dir, jog)
  }
}

/** Steam from the street grates in winter. */
function steam(c: Canvas, look: Look, right: number) {
  if (look.season !== 'winter' && !look.snowy) return
  for (let v = 0; v < 3; v++) {
    const vx = 10 + hash(look.seed + v * 53) % Math.max(1, right - 20)
    c.set(vx, GROUND, P.crust)
    c.set(vx + 1, GROUND, P.crust)
    for (let i = 0; i < 6; i++) c.glow(vx + Math.round(Math.sin(look.frame * 0.2 + i * 0.9 + v)) + (look.wind > 15 ? i >> 1 : 0), GROUND - 1 - i, P.white, 0.5 * (1 - i / 6) * (0.7 + 0.3 * Math.sin(look.frame * 0.3 + i)))
  }
}

// ── traffic ────────────────────────────────────────────────────────────────

const CYCLE = 200 // frames of a signal cycle: green, amber, red
const signalXs = (W: number) => {
  const xs: number[] = []
  for (let x = 30; x < W - 24; x += 48) xs.push(x)
  return xs
}

const RED_AT = 130 // green, then amber from 110, then red from here to the end of the cycle

/** Where the signals stand in the cycle at a frame. */
function flowOf(frame: number): { red: boolean; amber: boolean } {
  const t = frame % CYCLE
  return { red: t >= RED_AT, amber: t >= 110 && t < RED_AT }
}

/** One vehicle on a lane: it starts at `origin`, drives at `speed` px a frame toward `dir`, and is `w` wide. */
type Driver = { key: string; origin: number; dir: number; speed: number; w: number; span: number; lines: number[] }

/** Gap from the vehicle's front to the next stop line ahead of it (lines in screen columns). */
function gapAhead(d: Driver, dist: number): number {
  const x = wrap(d.origin + d.dir * dist, d.span) - 16
  const front = d.dir > 0 ? x + d.w : x
  let gap = Infinity
  for (const line of d.lines) gap = Math.min(gap, d.dir > 0 ? wrap(line - 1 - front, d.span) : wrap(front - (line + 2), d.span))
  return gap
}

// ponytail: a per-vehicle cache of the last cycle stepped to keeps a frame O(1); it resets on reload
const stepped = new Map<string, { cycle: number; dist: number }>()

/**
 * How far a vehicle has driven by `frame`, and whether it is waiting at a red: it drives freely
 * through green and amber; at red it keeps going until its front reaches the next stop line,
 * and waits there only if it gets there before green. Cars between lights never stop.
 */
function driven(d: Driver, frame: number): { dist: number; held: boolean } {
  const cycle = Math.floor(frame / CYCLE)
  let at = stepped.get(d.key)
  if (!at || at.cycle > cycle) at = { cycle: 0, dist: 0 }
  let dist = at.dist
  for (let k = at.cycle; k < cycle; k++) {
    dist += d.speed * RED_AT
    dist += Math.min(d.speed * (CYCLE - RED_AT), gapAhead(d, dist))
  }
  stepped.set(d.key, { cycle, dist })
  const t = frame % CYCLE
  if (t < RED_AT) return { dist: dist + d.speed * t, held: false }
  dist += d.speed * RED_AT
  const gap = gapAhead(d, dist)
  const go = d.speed * (t - RED_AT)
  return { dist: dist + Math.min(go, gap), held: go >= gap }
}

function signals(c: Canvas, look: Look, flow: { red: boolean; amber: boolean }) {
  for (const x of signalXs(c.W)) {
    c.set(x, GROUND - 1, P.surface1)
    c.set(x, GROUND - 2, P.surface1)
    const lamps: [number, number][] = [[P.red, flow.red ? 1 : 0.2], [P.yellow, flow.amber ? 1 : 0.2], [P.green, !flow.red && !flow.amber ? 1 : 0.2]]
    lamps.forEach(([col, k], i) => {
      c.set(x, GROUND - 5 + i, mix(P.crust, col, k))
      if (k === 1) c.glow(x + 1, GROUND - 5 + i, col, 0.3)
    })
  }
}

function puddles(c: Canvas, look: Look) {
  for (let x = 0; x < c.W; x++) {
    if (hash((x >> 2) + look.seed * 3) % 5 > 1) continue
    c.glow(x, ROAD + 1, c.get(x, GROUND - 1), 0.45) // the street front reflected
    c.glow(x, ROAD + 2, c.get(x, GROUND - 3), 0.25)
    if ((x * 3 + (look.frame >> 1)) % 7 === 0) c.glow(x, ROAD + 1, P.white, 0.4)
  }
}

function snowbanks(c: Canvas, look: Look, right: number) {
  for (let x = 0; x < right; x++) {
    if (hash(x * 5 + look.seed) % 11 > 2) continue
    c.set(x, ROAD, P.snow)
    c.set(x + 1, ROAD, P.snow)
    c.set(x, GROUND, P.snow)
    if (hash(x) % 2) c.set(x, GROUND - 1, mix(P.snow, P.overlay1, 0.2))
  }
}

// Vehicles face right: r roof, b body, g glass, H glass highlight, k wheel, t tail light, l headlight,
// c cab, s stripe, S taxi sign. Each is 4 rows (the far lane's cars 3), roof contour on top.
const CAR = ['..rrrr....', '.rgHggr...', 'tbbbbbbbbl', '.kkbbbbkk.']
const TAXI = ['..rSSr....', '.rgHggr...', 'tbbbbbbbbl', '.kkbbbbkk.']
const VAN = ['bbbbbbb...', 'bsssssbcgg', 'tbbbbbbbbl', '.kkbbbbkk.']
const BUS = ['rrrrrrrrrrrrrrrr', 'bgggHgggggggggbg', 'tbbbbbbbbbbbbbbl', '..kkbbbbbbbbkk..']
const FAR_CAR = ['.rgHgr..', 'tbbbbbbl', '.kk..kk.']
const BIKE = ['....h..', '...bb..', '.o.b.o.', 'ooo.ooo']
const CAR_COLORS = [P.red, P.blue, P.text, P.green, P.mauve, P.peach, P.overlay2, P.teal]
/** Cars in the far and near lane at each part of the day (per 180 px). */
const RUSH: Record<Look['phase'], [number, number]> = { dawn: [1, 2], morning: [4, 5], noon: [4, 4], afternoon: [4, 4], dusk: [5, 6], night: [1, 2] }

function vehicle(c: Canvas, look: Look, x: number, y: number, rows: readonly string[], body: number, dir: number, braking: boolean, far: boolean) {
  const night = look.night > 0.3 || look.phase === 'dusk'
  const base = mix(body, P.ink, 0.1 + look.night * 0.35 + (far ? 0.12 : 0))
  const glass = rows === BUS && night ? mix(P.yellow, base, 0.45) : mix(mix(0x2f5080, P.sky, 0.2), P.ink, look.night * 0.5)
  const pal = {
    r: mix(base, P.white, 0.2), b: base, g: glass, H: mix(glass, P.white, 0.45), k: P.crust, c: mix(base, P.white, 0.1),
    s: mix(CAR_COLORS[(((x + 5) % CAR_COLORS.length) + CAR_COLORS.length) % CAR_COLORS.length]!, P.ink, look.night * 0.3), S: night ? P.yellow : P.peach,
    t: braking ? mix(P.red, P.white, 0.3) : night ? P.red : mix(P.red, base, 0.4), l: night ? P.white : mix(P.yellow, base, 0.5),
  }
  sprite(c, x, y, rows, pal, dir < 0)
  if (rows === VAN) for (let k = 1; k < 6; k++) c.set(dir < 0 ? x + 9 - k : x + k, y, mix(P.text, P.ink, 0.1 + look.night * 0.4)) // the box is white
  const w = rows[0]!.length
  const ly = y + rows.length - 2 - (far ? 0 : 0)
  const back = dir > 0 ? x - 1 : x + w
  if (braking || night) c.glow(back, ly, P.red, braking ? 0.7 : 0.3)
  if (night) {
    const front = dir > 0 ? x + w : x - 1
    for (let k = 0; k < 4; k++) {
      c.glow(front + dir * k, ly, P.yellow, 0.4 - k * 0.09) // headlight beams
      c.glow(front + dir * k, ly + 1, P.yellow, 0.2 - k * 0.04)
    }
  }
}

function traffic(c: Canvas, look: Look, flow: { red: boolean; amber: boolean }) {
  const span = c.W + 28
  const [farN, nearN] = [0, 1].map(i => byPhase(look, { dawn: RUSH.dawn[i]!, morning: RUSH.morning[i]!, noon: RUSH.noon[i]!, afternoon: RUSH.afternoon[i]!, dusk: RUSH.dusk[i]!, night: RUSH.night[i]! })) as [number, number]
  const scale = span / 184
  const lines = signalXs(c.W)
  // a cyclist or two in the morning and afternoon, hugging the kerb
  if (look.phase === 'morning' || look.phase === 'afternoon' || look.phase === 'dawn') {
    for (let k = 0; k < Math.max(1, Math.round(scale)); k++) {
      const ride = driven({ key: `bike${k}|${look.seed}|${span}`, origin: k * (span / 2) + look.seed, dir: 1, speed: 0.5, w: 7, span, lines }, look.frame)
      const x = wrap(k * (span / 2) + look.seed + ride.dist, span) - 16
      sprite(c, x, ROAD, BIKE, { h: P.peach, b: [P.red, P.green, P.blue][(k + look.seed) % 3]!, o: P.crust })
      if ((look.frame >> 1) % 2) c.set(x + 3, ROAD + 2, P.surface2)
    }
  }
  for (const far of [true, false]) {
    const n = Math.max(1, Math.round((far ? farN : nearN) * scale))
    const dir = far ? 1 : -1
    const speed = far ? 0.7 : 0.95
    const slot = span / n
    for (let k = 0; k < n; k++) {
      const h = hash(look.seed + k * 131 + (far ? 977 : 0))
      const bus = !far && h % 8 === 0
      const van = !far && !bus && h % 5 === 0 && (look.phase === 'morning' || look.phase === 'dawn' || h % 10 === 0)
      const taxi = !bus && !van && (look.phase === 'night' || look.phase === 'noon') && h % 3 === 0
      const sweeper = !far && k === 0 && look.phase === 'dawn' // the street sweeper, beacon flashing
      const rows = far ? FAR_CAR : bus ? BUS : van || sweeper ? VAN : taxi ? TAXI : CAR
      const color = sweeper ? P.peach : bus ? P.peach : van ? P.text : taxi ? P.yellow : CAR_COLORS[h % CAR_COLORS.length]!
      const origin = k * slot + (h % Math.max(1, Math.floor(slot / 3)))
      const drive = driven({ key: `${far ? 'f' : 'n'}${k}|${look.seed}|${span}|${rows[0]!.length}`, origin, dir, speed, w: rows[0]!.length, span, lines }, look.frame)
      const x = Math.round(wrap(origin + dir * drive.dist, span) - 16)
      vehicle(c, look, x, ROAD, rows, color, dir, drive.held || (flow.amber && !far), far)
      if (sweeper && look.frame % 6 < 3) c.set(x + 3, ROAD - 1, P.yellow)
    }
  }
}

// ── parks ──────────────────────────────────────────────────────────────────

/** A pocket park: grass over the pavement, hedges, trees, a bench and a small fountain. */
function park(c: Canvas, look: Look, x: number, w: number, h: number) {
  const grass = look.snowy ? mix(P.snow, P.surface1, 0.2) : dimmed(look, 0x4a7a46, 0.5)
  for (let k = 0; k < w; k++) {
    c.set(x + k, GROUND, grass)
    c.set(x + k, GROUND - 1, look.snowy ? P.snow : dimmed(look, mix(0x2f5f34, P.leaf, k % 2 * 0.4), 0.4)) // a low hedge
  }
  tree(c, look, x + 1, true, h)
  if (w >= 7) tree(c, look, x + w - 2, true, h >>> 3)
  if (w >= 8) {
    const m = x + (w >> 1)
    for (const dx of [-1, 0, 1]) c.set(m + dx, GROUND - 1, P.sapphire)
    for (let k = 0; k < 3; k++) c.glow(m, GROUND - 2 - k, P.sky, 0.7 - 0.2 * (((look.frame >> 1) + k) % 3)) // the fountain
  } else bench(c, look, x + (w >> 1) - 1)
}
