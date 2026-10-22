import type { WakeMood, WakePreset, WakePulseKind } from '../types'
import { fly, stations } from './landscapes/crew'
import { type DayPhase, type Job, type Landscape, type Look, P, SCENE_H, type SceneEvent, type Season } from './landscapes/kit'
import { LANDSCAPES } from './landscapes'
import { type Canvas, canvas, hash, mix, sprite } from './pixels'

// The band's diorama. Every thing in it stands for something real:
//   buildings      turns of this session (taller: more tool calls; wider: more edits)
//   their windows  the turn's tool calls, coloured by kind (a red one failed)
//   the live one   the turn in progress, being built
//   street lamps   plan progress (lit steps done)
//   crew           bridge jobs and subagents, one family per harness, bigger with the model's tier (amber: stale):
//                  Codex drones, airship, boats; agy sparks, comets, constellations; Claude sparrows, gulls, eagles;
//                  OpenCode hot-air balloons, small to striped to banded
//   birds          running subagents (Claude's family)
//   Mochi          the mood: laptop while working, ! when something needs you,
//                  a cloud when a command failed, asleep while you're away
//   the sky        the real sun and moon (phase too) where you are
//   weather        the real weather where you are
//   fireworks      tests passed; a storm: a command failed; a shooting star: a bridge job finished
// The landscape (city, harbor, beach, ...) and the ambient events only set the mood.

const H = SCENE_H
export const SCENE_ROWS = H / 2

export type SceneTurn = { kinds: WakePulseKind[] }
export type SceneEffect = { kind: 'fireworks' | 'storm' | 'shoot'; age: number }
export const EFFECT_FRAMES: Record<SceneEffect['kind'], number> = { fireworks: 40, storm: 48, shoot: 24 }

export type SceneWeather = { cloud: number; rain: 0 | 1 | 2 | 3; snow: 0 | 1 | 2 | 3; fog: boolean; thunder: boolean; wind: number }

/** A running subagent as a bird: its id's seed (who it is: its lane and pace come from it) and its model's tier. */
export type SceneAgent = { seed: number; tier: 1 | 2 | 3 }

export type SceneInput = {
  width: number
  frame: number
  hour: number // local hours
  sun: { rise: number; set: number } // local hours
  moonPhase: number // 0 new .. 0.5 full .. 1 new
  season: Season
  snowy: boolean
  weather: SceneWeather | null
  preset: WakePreset
  seed: number // per place
  turns: SceneTurn[] // finished, oldest first
  live: SceneTurn | null
  mood: WakeMood
  jobs: Job[]
  agents: SceneAgent[] // running subagents
  plan: { done: number; total: number } | null
  effect: SceneEffect | null
  forceEvent?: string // previews: play this event now
}

export const CAT_COLUMNS = 10

// Mochi, 10x7, bottom row on the ground: B body, S shade, E eye, P cheek, N nose, I inner ear, T tail.
const CAT = ['.B.....B..', '.BI...IB..', '.BBBBBBB..', '.BEBBBEB..', '.BPBNBPB..', '..BBBBS..T', '..BSBBSTT.']
const CAT_TAIL_DOWN = ['.B.....B..', '.BI...IB..', '.BBBBBBB..', '.BEBBBEB..', '.BPBNBPB..', '..BBBBS...', '..BSBBSTTT']
const UMBRELLA = ['..ppppp..', '.ppppppp.', 'pp.p.p.pp', '....h....', '....h....']

// ── sky ────────────────────────────────────────────────────────────────────

const NIGHT_TOP = 0x0b0b14
const NIGHT_LOW = 0x171726

/** The sky's top and horizon colours at `hour`, keyed to the real sunrise and sunset. */
function skyAt(hour: number, rise: number, set: number): [number, number] {
  const r = Math.max(3, Math.min(10, rise))
  const s = Math.max(Math.max(r + 4, 14), Math.min(22.5, set))
  const keys: [number, number, number][] = [
    [0, NIGHT_TOP, NIGHT_LOW],
    [r - 1.5, 0x10101e, 0x24243c],
    [r, 0x3a2d55, 0xb06f7a], // dawn
    [r + 1.5, 0x3d5f93, 0x8fb3dc], // morning
    [(r + s) / 2, 0x3b6db0, 0x9cc4ec], // noon
    [s - 1.2, 0x44558a, 0xd09a7a], // golden hour
    [s, 0x3b2a55, 0xc06a5e], // sunset
    [s + 1.5, 0x161628, 0x2c2c48],
    [24, NIGHT_TOP, NIGHT_LOW],
  ]
  const h = ((hour % 24) + 24) % 24
  const i = Math.max(1, keys.findIndex(([at]) => at > h))
  const [h0, t0, b0] = keys[i - 1]!
  const [h1, t1, b1] = keys[i]!
  const t = h1 === h0 ? 0 : (h - h0) / (h1 - h0)
  return [mix(t0, t1, t), mix(b0, b1, t)]
}

function nightness(hour: number, rise: number, set: number): number {
  const h = ((hour % 24) + 24) % 24
  if (h >= rise + 1 && h <= set - 0.5) return 0
  if (h > rise - 1 && h < rise + 1) return (rise + 1 - h) / 2
  if (h > set - 0.5 && h < set + 1.5) return (h - (set - 0.5)) / 2
  return 1
}

function drawSky(c: Canvas, look: Look, input: SceneInput) {
  const cloud = input.weather?.cloud ?? 0.2
  const grey = Math.min(0.55, Math.max(0, cloud - 0.5) * 1.1 + (input.weather && input.weather.rain + input.weather.snow > 0 ? 0.2 : 0))
  // overcast greys the sky: light by day, dark by night
  const top = mix(look.top, mix(0x8a90a8, P.surface1, look.night), grey)
  const low = mix(look.horizon, mix(0xa6adc8, P.surface0, look.night), grey)
  for (let y = 0; y < H; y++) {
    const row = mix(top, low, (y / (H - 1)) ** 1.4)
    for (let x = 0; x < c.W; x++) c.set(x, y, row)
  }
  const starsVisible = look.night * (1 - Math.min(1, cloud * 1.2))
  if (starsVisible > 0.05) {
    for (let x = 0; x < c.W; x++) {
      for (let y = 0; y < Math.round(H * 0.65); y++) {
        const h = hash(x * 131 + y * 7919 + input.seed)
        if (h % 37 !== 0) continue
        const tw = (h + Math.floor(look.frame / 5)) % 11
        c.glow(x, y, P.text, (tw === 0 ? 0.15 : tw === 1 ? 1 : 0.6) * starsVisible * (1 - y / (H * 0.8)))
      }
    }
  }
  // sun by day, moon (in its real phase) by night, behind thick cloud neither
  if (cloud < 0.85) {
    const { rise, set } = input.sun
    const day = look.isDay
    const len = day ? set - rise : 24 - (set - rise)
    const since = day ? input.hour - rise : (((input.hour - set) % 24) + 24) % 24
    const arc = Math.max(0, Math.min(1, since / len))
    const bx = Math.round(4 + arc * (c.W - 14))
    const by = Math.round(H * 0.55 - H * 0.5 * Math.sin(Math.PI * arc))
    const disc = ['.##.', '####', '####', '.##.']
    const veil = Math.max(0, cloud - 0.5) * 1.5
    if (day) {
      for (let dy = -2; dy < 6; dy++) for (let dx = -2; dx < 6; dx++) c.glow(bx + dx, by + dy, P.yellow, 0.08 * (1 - veil))
      sprite(c, bx, by, disc, { '#': mix(P.yellow, top, veil) })
    } else {
      // lit fraction from the phase: waxing lights the right side first
      const phase = input.moonPhase
      const lit = (dx: number) => {
        const u = (dx + 0.5) / 4 // 0..1 across the disc
        if (phase < 0.5) return u > 1 - phase * 2
        return u < 1 - (phase - 0.5) * 2
      }
      disc.forEach((line, dy) => {
        for (let dx = 0; dx < 4; dx++) {
          if (line[dx] !== '#') continue
          c.set(bx + dx, by + dy, lit(dx) ? mix(P.snow, top, veil) : mix(top, P.surface1, 0.35))
        }
      })
    }
  }
  // clouds: count and greyness from the cloud cover, drifting with the wind
  const n = Math.round((c.W / 30) * (0.2 + cloud * 1.6))
  const speed = 0.03 + (input.weather?.wind ?? 8) * 0.004
  const tone = mix(mix(P.overlay1, P.surface1, grey), top, look.night * 0.65)
  for (let k = 0; k < n; k++) {
    const span = c.W + 30
    const cx = Math.round((((hash(k + input.seed) % span) + look.frame * speed * (1 + (k % 3) * 0.3)) % span) - 15)
    const cy = 1 + (hash(k * 7) % Math.round(H * 0.4))
    const len = 6 + (hash(k * 13) % 10)
    for (let i = 0; i < len; i++) {
      c.glow(cx + i, cy, tone, 0.35 + grey * 0.3)
      if (i > 1 && i < len - 2) c.glow(cx + i, cy - 1, tone, 0.25 + grey * 0.3)
      if (cloud > 0.6 && i > 2 && i < len - 3) c.glow(cx + i, cy + 1, tone, 0.2)
    }
  }
}

// ── shared ambient events ──────────────────────────────────────────────────
// (no hot-air balloon among them: balloons are OpenCode's crew, and a crew sprite always stands for a real job)

const SHARED_EVENTS: SceneEvent[] = [
  {
    name: 'plane',
    frames: 160,
    weight: 3,
    draw(c, look, age, seed) {
      const dir = seed % 2 ? 1 : -1
      const t = age / 160
      const x = Math.round(dir > 0 ? t * (c.W + 10) - 5 : (1 - t) * (c.W + 10) - 5)
      const y = 1 + (seed % 3)
      if (look.night > 0.4) {
        c.set(x, y, age % 8 < 4 ? P.red : P.surface2)
        c.set(x + 1, y, P.white)
      } else {
        c.set(x, y, P.overlay2)
        c.set(x + 1, y, P.overlay2)
        for (let k = 2; k < 14; k++) c.glow(x - dir * k, y, P.white, 0.3 * (1 - k / 14)) // contrail
      }
    },
  },
  {
    name: 'shooting stars',
    frames: 50,
    weight: 2,
    when: look => look.night > 0.7,
    draw(c, _look, age, seed) {
      for (let s = 0; s < 3; s++) {
        const a = age - s * 14
        if (a < 0 || a > 12) continue
        const x0 = (hash(seed + s) % Math.max(1, c.W - 20)) + a * 2
        const y0 = (hash(seed * 3 + s) % 3) + Math.floor(a / 3)
        for (let k = 0; k < 5; k++) c.glow(x0 - k * 2, y0 - Math.floor(k / 2), P.white, 1 - k / 5)
      }
    },
  },
  {
    name: 'ufo',
    frames: 120,
    weight: 0.25,
    when: look => look.night > 0.8,
    draw(c, _look, age, seed) {
      const x = Math.round(c.W * 0.2 + (seed % Math.max(1, Math.round(c.W * 0.5))) + Math.sin(age * 0.1) * 6)
      const y = 2 + Math.round(Math.sin(age * 0.07))
      sprite(c, x, y, ['..g..', 'sssss'], { g: P.teal, s: P.overlay2 })
      if (age > 30 && age < 90) for (let yy = y + 2; yy < H - 1; yy++) for (let k = -1; k <= 1; k++) c.glow(x + 2 + k, yy, P.green, 0.18)
    },
  },
  {
    name: 'meteor shower',
    frames: 100,
    weight: 0.5,
    when: look => look.night > 0.8,
    draw(c, _look, age, seed) {
      for (let s = 0; s < 8; s++) {
        const a = (age + s * 13) % 25
        const x0 = hash(seed + s * 17 + Math.floor((age + s * 13) / 25)) % c.W
        for (let k = 0; k < 3; k++) c.glow(x0 + a - k, Math.floor(a / 4) - Math.floor(k / 2), P.yellow, 0.9 - k * 0.3)
      }
    },
  },
  {
    name: 'rainbow',
    frames: 260,
    weight: 4,
    when: look => look.isDay && look.wet,
    draw(c, _look, age) {
      const fade = Math.min(1, age / 30, (260 - age) / 30) * 0.4
      const bands = [P.red, P.peach, P.yellow, P.green, P.blue, P.mauve]
      const cx = c.W * 0.4
      for (let x = 0; x < c.W; x++) {
        bands.forEach((band, i) => {
          const r = c.W * 0.32 - i
          const dx = (x - cx) / r
          if (Math.abs(dx) > 1) return
          c.glow(x, Math.round(H - 2 - Math.sqrt(1 - dx * dx) * (H - 3)), band, fade)
        })
      }
    },
  },
  {
    name: 'flock',
    frames: 140,
    weight: 2,
    when: look => look.isDay && !look.wet,
    draw(c, _look, age, seed) {
      for (let b = 0; b < 7; b++) {
        const x = Math.round((age / 140) * (c.W + 30)) - 20 + Math.abs(b - 3) * 2
        const y = 2 + Math.abs(b - 3) + (seed % 2)
        const up = (age + b) % 6 < 3
        c.set(x, y, P.surface2)
        c.set(x - 1, up ? y - 1 : y, P.surface2)
        c.set(x + 1, up ? y - 1 : y, P.surface2)
      }
    },
  },
]

const SLOT = 400 // frames: a chance of one event every 40 seconds

function playingEvent(look: Look, events: SceneEvent[], force?: string): { event: SceneEvent; age: number; seed: number } | null {
  if (force) {
    const event = events.find(e => e.name === force)
    return event ? { event, age: look.frame % event.frames, seed: look.seed } : null
  }
  const slot = Math.floor(look.frame / SLOT)
  const h = hash(look.seed ^ Math.imul(slot, 7919))
  if (h % 100 >= 55) return null
  const pool = events.filter(e => !e.when || e.when(look))
  const total = pool.reduce((sum, e) => sum + e.weight, 0)
  if (total === 0) return null
  let pick = ((h >>> 8) % 10_000) / 10_000 * total
  const event = pool.find(e => (pick -= e.weight) < 0) ?? pool[0]!
  const delay = event.frames < SLOT ? (h >>> 4) % (SLOT - event.frames) : 0
  const age = (look.frame % SLOT) - delay
  return age >= 0 && age < event.frames ? { event, age, seed: h } : null
}

// ── weather and session effects ────────────────────────────────────────────

function drawWeather(c: Canvas, look: Look, w: SceneWeather, ground: number) {
  const slant = w.wind > 30 ? 2 : w.wind > 15 ? 1 : 0
  if (w.rain > 0) {
    const every = [0, 31, 19, 12][w.rain]!
    for (let x = -10; x < c.W; x++) {
      for (let y = 0; y < ground + 1; y++) {
        const fall = (((y - look.frame * 2) % 48) + 48) % 48
        if (hash(x * 31 + fall * 17) % every !== 0) continue
        c.glow(x + Math.floor((y * slant) / 3), y, P.blue, 0.45)
        if (y + 1 <= ground) c.glow(x + Math.floor(((y + 1) * slant) / 3), y + 1, P.blue, 0.25)
      }
    }
    if (w.rain >= 2) for (let x = 0; x < c.W; x++) if (hash(x + look.frame * 3) % 19 === 0) c.glow(x, ground, P.sky, 0.5) // splashes
  }
  if (w.snow > 0) {
    const every = [0, 29, 17, 9][w.snow]!
    for (let x = 0; x < c.W; x++) {
      for (let y = 0; y < ground + 1; y++) {
        const fall = (((y - Math.floor(look.frame / 3)) % 36) + 36) % 36
        if (hash(x * 53 + fall * 29) % every !== 0) continue
        c.glow(x + Math.round(Math.sin((look.frame + x * 7) * 0.08) + (slant * y) / 6), y, P.white, 0.85)
      }
    }
  }
  if (w.fog) {
    for (let y = 0; y < H; y++) {
      const base = 0.15 + (y / H) * 0.45
      for (let x = 0; x < c.W; x++) c.glow(x, y, P.overlay2, base * (0.75 + 0.25 * Math.sin((x + look.frame * 0.3) * 0.12 + y)))
    }
  }
  if (w.thunder) {
    const cycle = look.frame % 170
    if (cycle === 3 || cycle === 4 || cycle === 9) {
      for (let y = 0; y < H; y++) for (let x = 0; x < c.W; x++) c.glow(x, y, P.white, 0.15)
      let x = hash(Math.floor(look.frame / 170) + look.seed) % c.W
      for (let y = 0; y < ground; y++) {
        c.set(x, y, P.yellow)
        x += hash(y + look.frame) % 3 === 0 ? -1 : 1
      }
    }
  }
}

function drawEffect(c: Canvas, look: Look, fx: SceneEffect, ground: number, right: number) {
  if (fx.kind === 'fireworks') {
    const sparks = [P.yellow, P.pink, P.mauve, P.green, P.sky, P.peach]
    for (let b = 0; b < 4; b++) {
      const age = fx.age - b * 7
      if (age < 0 || age > 20) continue
      const seed = hash(b * 101 + 7)
      const cx = Math.round(right * (0.15 + 0.23 * b) + (seed % 9))
      const cy = 2 + (seed % 3)
      const color = sparks[(seed + b) % sparks.length]!
      if (age < 5) {
        c.set(cx, ground - 1 - age * 2, P.white)
        c.glow(cx, ground - age * 2, P.yellow, 0.5)
        continue
      }
      const r = Math.min(5, age - 4)
      const fade = age > 13 ? (age - 13) / 8 : 0
      for (let a = 0; a < 12; a++) {
        const ang = (a / 12) * Math.PI * 2
        c.glow(cx + Math.round(Math.cos(ang) * r * 1.4), cy + Math.round(Math.sin(ang) * r * 0.8) + (age > 10 ? Math.floor((age - 10) / 3) : 0), a % 2 ? color : P.white, 1 - fade)
      }
      if (age < 8) c.glow(cx, cy, P.white, 0.9)
    }
  } else if (fx.kind === 'storm') {
    drawWeather(c, look, { cloud: 1, rain: 3, snow: 0, fog: false, thunder: false, wind: 25 }, ground)
    if ([3, 4, 14, 30].includes(fx.age)) {
      for (let y = 0; y < H; y++) for (let x = 0; x < c.W; x++) c.glow(x, y, P.white, 0.18)
      let x = Math.round(right * (0.3 + 0.3 * ((fx.age % 5) / 5)))
      for (let y = 0; y < ground; y++) {
        c.set(x, y, P.yellow)
        c.glow(x - 1, y, P.yellow, 0.3)
        x += hash(y + fx.age) % 3 === 0 ? -1 : 1
      }
    }
  } else {
    const t = fx.age / EFFECT_FRAMES.shoot
    const x = Math.round(t * (c.W + 20)) - 10
    const y = Math.floor(t * 5)
    for (let k = 0; k < 7; k++) c.glow(x - k * 2, y - Math.floor(k / 3), P.white, 1 - k / 7)
  }
}

// ── Mochi ──────────────────────────────────────────────────────────────────

function drawMochi(c: Canvas, look: Look, input: SceneInput, ground: number, catX: number) {
  const fx = input.effect
  const jump = fx?.kind === 'fireworks' && fx.age < 28 && look.frame % 6 < 3 ? 1 : 0
  const blink = input.mood !== 'sleep' && look.frame % 61 < 2
  const rows = input.mood === 'work' || look.frame % 24 < 12 ? CAT : CAT_TAIL_DOWN
  const top = ground - CAT.length - jump
  const eye = input.mood === 'sleep' || blink ? P.overlay0 : P.crust
  sprite(c, catX, top, rows, { B: P.lavender, T: P.lavender, S: 0x9399d6, E: eye, P: P.pink, I: P.pink, N: P.maroon })
  if (look.snowy && input.weather && input.weather.snow > 0) c.set(catX + 3, top + 2, P.white) // a snowflake on her head
  if (input.mood === 'work') {
    const lx = catX - 4
    for (let k = 0; k < 4; k++) c.set(lx + k, ground, P.overlay0)
    for (let y = ground - 3; y < ground; y++) c.set(lx, y, P.overlay0)
    for (let k = 1; k < 4; k++) c.glow(lx + k, ground - 1, P.teal, look.frame % 6 < 3 ? 0.35 : 0.2)
    c.glow(catX + 1, top + 4, P.teal, 0.25)
  }
  const raining = (input.weather?.rain ?? 0) > 0 || fx?.kind === 'storm'
  if (raining && input.mood !== 'sleep') sprite(c, catX, top - 3, UMBRELLA, { p: P.pink, h: P.overlay1 })
  if (input.mood === 'sleep') {
    for (let k = 0; k < 2; k++) {
      const z = (Math.floor(look.frame / 4) + k * 5) % 10
      c.glow(catX + 8 + Math.floor(z / 4), top - 1 - Math.floor(z / 2), P.white, 0.9 - z / 10)
    }
  }
  if (input.mood === 'alert' && look.frame % 8 < 5) {
    c.set(catX + 4, top - 4, P.yellow)
    c.set(catX + 4, top - 3, P.yellow)
    c.set(catX + 4, top - 1, P.yellow)
  }
  if (input.mood === 'sad' && !raining) {
    for (let x = catX; x < catX + 8; x++) {
      c.set(x, top - 3, P.overlay0)
      if (x > catX && x < catX + 7) c.set(x, top - 4, P.overlay0)
    }
    for (let k = 0; k < 4; k++) c.glow(catX + 1 + k * 2, top - 2 + ((look.frame + k) % 2), P.blue, 0.9)
  }
  if (input.mood === 'happy' && !jump) {
    const sparks = [P.yellow, P.pink, P.mauve]
    for (let k = 0; k < 3; k++) if ((look.frame + k * 3) % 9 < 3) c.glow(catX - 1 + k * 5, top - 1 - (k % 2), sparks[k]!, 0.9)
  }
}

// ── the whole scene ────────────────────────────────────────────────────────

/** The part of the day from the real sunrise and sunset. */
export function phaseOf(hour: number, rise: number, set: number): DayPhase {
  const h = ((hour % 24) + 24) % 24
  if (h >= rise - 0.75 && h < rise + 0.75) return 'dawn'
  if (h >= rise + 0.75 && h < 11) return 'morning'
  if (h >= 11 && h < 14) return 'noon'
  if (h >= 14 && h < set - 1) return 'afternoon'
  if (h >= set - 1 && h < set + 0.75) return 'dusk'
  return 'night'
}

/** Each phase's share of a ~50 min window around the hour: a cross-fade at every boundary. */
function phaseBlend(hour: number, rise: number, set: number): Record<DayPhase, number> {
  const blend: Record<DayPhase, number> = { dawn: 0, morning: 0, noon: 0, afternoon: 0, dusk: 0, night: 0 }
  const samples = 9
  for (let i = 0; i < samples; i++) blend[phaseOf(hour + ((i / (samples - 1)) - 0.5) * 0.85, rise, set)] += 1 / samples
  return blend
}

export function lookOf(input: SceneInput): Look {
  const [top, horizon] = skyAt(input.hour, input.sun.rise, input.sun.set)
  const w = input.weather
  return {
    W: input.width,
    H,
    frame: input.frame,
    hour: input.hour,
    night: nightness(input.hour, input.sun.rise, input.sun.set),
    isDay: input.hour >= input.sun.rise && input.hour < input.sun.set,
    phase: phaseOf(input.hour, input.sun.rise, input.sun.set),
    blend: phaseBlend(input.hour, input.sun.rise, input.sun.set),
    top,
    horizon,
    season: input.season,
    snowy: input.snowy,
    wet: (w?.rain ?? 0) + (w?.snow ?? 0) > 0,
    wind: w?.wind ?? 8,
    seed: input.seed,
    working: input.mood === 'work',
  }
}

/** The scene's pixels, row-major, `width` x 12, as 0xRRGGBB. */
export function scenePixels(input: SceneInput): Uint32Array {
  const c = canvas(input.width, H)
  const look = lookOf(input)
  const land: Landscape = LANDSCAPES[input.preset]
  const ground = land.ground
  const catX = c.W - CAT_COLUMNS - 1
  const right = catX - 5 // left of the laptop

  drawSky(c, look, input)
  land.backdrop(c, look)
  land.floor(c, look)

  // birds: running subagents, over the backdrop; each keeps a lane and pace by who it is (the five first by identity fly)
  for (const [bird, j] of stations(input.agents.map(agent => ({ isStale: false, seed: agent.seed, tier: agent.tier, kind: 'claude' as const })), 5)) {
    if (j >= 5) continue
    const tier = bird.tier // the Claude family's birds: sparrow, gull, eagle (the eagle glides slower)
    const x = Math.round((input.frame * (0.5 + j * 0.08) * (tier === 3 ? 0.7 : 1) + j * 29) % (c.W + 20)) - 10
    const y = 3 + (j % 3) + Math.round(Math.sin((input.frame + j * 9) * (tier === 3 ? 0.07 : 0.15)))
    fly(c, look, x, y, bird)
  }

  // structures, newest at the right
  let edge = right
  const place = (kinds: WakePulseKind[], index: number, isLive: boolean) => {
    const { width, height } = land.size(kinds, index, look)
    const x0 = edge - width
    if (x0 + width < 0) return false
    land.building(c, look, { kinds, index, x0, width, height, isLive })
    const gap = land.gap(index, look)
    if (gap > 0) land.filler(c, look, x0 - gap, x0)
    edge = x0 - gap
    return true
  }
  if (input.live) place(input.live.kinds, input.turns.length, true)
  for (let i = input.turns.length - 1; i >= 0; i--) if (!place(input.turns[i]!.kinds, i, false)) break
  if (edge > 0) land.filler(c, look, 0, edge)

  // lamps: plan progress
  const lamps = Math.max(0, Math.floor((right - 4) / 9))
  for (let i = 0; i < lamps; i++) {
    const x = 4 + i * 9
    const on = input.plan ? i < Math.round((lamps * input.plan.done) / input.plan.total) : look.night > 0.5
    const color = input.plan ? P.yellow : mix(P.yellow, P.mantle, 0.35)
    c.set(x, ground - 1, P.surface1)
    c.set(x, ground - 2, on ? color : P.surface2)
    if (on) for (const [dx, t] of [[-1, 0.25], [0, 0.4], [1, 0.25]] as const) c.glow(x + dx, ground, color, t)
  }

  land.jobs(c, look, input.jobs, right)
  land.foreground(c, look, right)
  const playing = playingEvent(look, [...land.events, ...SHARED_EVENTS], input.forceEvent)
  if (playing) playing.event.draw(c, look, playing.age, playing.seed)
  if (input.weather) drawWeather(c, look, input.weather, ground)
  if (input.effect) drawEffect(c, look, input.effect, ground, right)
  drawMochi(c, look, input, ground, catX)
  return c.px
}

/** What is playing now, for the legend. */
export function eventName(input: SceneInput): string | undefined {
  const look = lookOf(input)
  return playingEvent(look, [...LANDSCAPES[input.preset].events, ...SHARED_EVENTS], input.forceEvent)?.event.name
}

/** The scene as a Raster's cells (one half block per cell, top pixel fg, bottom bg) and its
 * floor: the bottom row's most common colour, so a passing car doesn't change it. */
export function sceneFrame(input: SceneInput): { cells: string; floor: number } {
  const px = scenePixels(input)
  const W = input.width
  const words = new Uint32Array(W * SCENE_ROWS * 3)
  for (let r = 0; r < SCENE_ROWS; r++) {
    for (let x = 0; x < W; x++) {
      const at = (r * W + x) * 3
      words[at] = 0x2580 // ▀
      words[at + 1] = px[2 * r * W + x]!
      words[at + 2] = px[(2 * r + 1) * W + x]!
    }
  }
  const counts = new Map<number, number>()
  let floor = px[(H - 1) * W]!
  for (let x = 0; x < W; x++) {
    const color = px[(H - 1) * W + x]!
    const n = (counts.get(color) ?? 0) + 1
    counts.set(color, n)
    if (n > (counts.get(floor) ?? 0)) floor = color
  }
  return { cells: bytesToBase64(new Uint8Array(words.buffer)), floor }
}

export const sceneCells = (input: SceneInput) => sceneFrame(input).cells

const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
const B64_PAIRS = Array.from({ length: 4096 }, (_, n) => B64[n >> 6]! + B64[n & 63]!) // 12 bits -> 2 chars

/** Base64 of a frame: 12 bytes a cell, so always whole 3-byte groups and no padding. */
function bytesToBase64(bytes: Uint8Array): string {
  const parts: string[] = []
  for (let i = 0; i < bytes.length; i += 3) {
    const n = (bytes[i]! << 16) | (bytes[i + 1]! << 8) | bytes[i + 2]!
    parts.push(B64_PAIRS[n >> 12]!, B64_PAIRS[n & 4095]!)
  }
  return parts.join('')
}
