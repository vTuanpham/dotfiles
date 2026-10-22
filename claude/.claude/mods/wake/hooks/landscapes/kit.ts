import type { WakePreset, WakePulseKind } from '../../types'
import { type Canvas, hash, mix } from '../pixels'

// The contract every landscape implements, and the shared kit they draw with.
//
// The scene is `W` pixels wide and SCENE_H (16) tall (8 terminal rows of half blocks; a
// pixel is about square). Size things from SCENE_H, never a literal height. The core draws, in order:
//   1. the sky (gradient by the real sun), stars, sun or moon, clouds
//   2. landscape.backdrop: distant scenery (far and mid layers)
//   3. landscape.floor: the ground at and below `ground`
//   4. buildings right to left from Mochi: landscape.building for each turn (the live
//      one first), landscape.filler in the gaps, until the left edge
//   5. street lamps (lit by plan progress) on the ground row
//   6. landscape.jobs (running bridge jobs), landscape.foreground (critters, vehicles,
//      reflections)
//   7. an ambient event, if one is playing (landscape.events plus shared ones)
//   8. weather overlay (rain, snow, fog, lightning), session effects (fireworks, storm,
//      shooting star), then Mochi and her props at the right edge
//
// Every function is pure: draw only through the canvas, derive all motion from
// `look.frame` (10 frames a second) and all variety from hashes of `look.seed`,
// the building's `index` and positions. Never Math.random: a frame must be
// reproducible.

export const SCENE_H = 16

export type Season = 'spring' | 'summer' | 'autumn' | 'winter'

/**
 * The part of the day, from the real sunrise and sunset where the person is. Every
 * landscape should look different across them, not just darker: who is out, what is
 * lit, what moves (commuters and joggers in the morning, busy noon, lit-up evening,
 * a quiet night with a few lit windows and night-shift life).
 */
export type DayPhase = 'dawn' | 'morning' | 'noon' | 'afternoon' | 'dusk' | 'night'

export type Look = {
  W: number
  H: number
  frame: number // 10 a second
  hour: number // local hours, 0..24
  night: number // 1 deep night .. 0 day
  isDay: boolean // between sunrise and sunset
  phase: DayPhase // for what is there (who is out, what is lit); blend colours by `blend` instead
  /** Each phase's weight now, summing to 1, cross-fading over ~50 min at each boundary. */
  blend: Record<DayPhase, number>
  top: number // the sky's colour at the top now
  horizon: number // the sky's colour at the horizon now
  season: Season
  snowy: boolean // snow lies on the ground
  wet: boolean // it is raining or snowing now
  wind: number // km/h
  seed: number // per place: vary layouts by it
  working: boolean // Claude is mid-turn
}

/** One turn as a structure: its tool calls in order, where it stands, how big. */
export type Building = {
  kinds: WakePulseKind[]
  index: number // the turn's number in the session: a stable seed
  x0: number // left column
  width: number
  height: number // pixels above the ground row
  isLive: boolean // the turn in progress (show it being built / busy)
}

/** A crew member: the seed is who it is (its place, lane and motion come from it, never from its place in the list); the harness picks
 *  the family (kind), the model the tier, and a maker with its own family (Claude inside agy) lends one mark its colour. */
export type Job = { isStale: boolean; seed: number; kind?: 'codex' | 'agy' | 'claude' | 'opencode'; tier?: 1 | 2 | 3; maker?: 'claude' }

/** Each backend keeps a distinct accent; agy's mauve reads on day and night skies, unlike blue; OpenCode's green, unlike the sky's own blues. */
export const jobAccent = (job: Job, codex: number): number => (job.kind === 'agy' ? P.mauve : job.kind === 'claude' ? P.pink : job.kind === 'opencode' ? P.green : codex)

/** A happening that plays now and then for `frames` frames. */
export type SceneEvent = {
  name: string
  frames: number
  weight: number // relative chance among the events that may play now
  when?: (look: Look) => boolean
  draw: (c: Canvas, look: Look, age: number, seed: number) => void
}

export type Landscape = {
  name: WakePreset
  ground: number // y of the row Mochi sits on and buildings stand on
  backdrop(c: Canvas, look: Look): void
  floor(c: Canvas, look: Look): void
  /** Size of a turn's structure: grows with calls (kinds.length) and edits. Height <= ground - 1. */
  size(kinds: WakePulseKind[], index: number, look: Look): { width: number; height: number }
  /** Empty columns to leave left of building `index` (filler is drawn there). */
  gap(index: number, look: Look): number
  building(c: Canvas, look: Look, b: Building): void
  filler(c: Canvas, look: Look, x0: number, x1: number): void
  jobs(c: Canvas, look: Look, jobs: Job[], right: number): void
  foreground(c: Canvas, look: Look, right: number): void
  events: SceneEvent[]
}

/** The colour of each kind of tool call: windows show what the turn did. */
export const KIND_COLOR: Record<WakePulseKind, number> = {
  read: 0x89b4fa,
  search: 0x89dceb,
  web: 0xfab387,
  plan: 0xf9e2af,
  run: 0xb4befe,
  edit: 0xa6e3a1,
  test: 0x94e2d5,
  agent: 0xcba6f7,
  fail: 0xf38ba8,
}

/** Catppuccin Mocha and a few scene colours. */
export const P = {
  ink: 0x0b0b14,
  crust: 0x11111b,
  mantle: 0x181825,
  base: 0x1e1e2e,
  surface0: 0x313244,
  surface1: 0x45475a,
  surface2: 0x585b70,
  overlay0: 0x6c7086,
  overlay1: 0x7f849c,
  overlay2: 0x9399b2,
  subtext: 0xa6adc8,
  text: 0xcdd6f4,
  lavender: 0xb4befe,
  blue: 0x89b4fa,
  sapphire: 0x74c7ec,
  sky: 0x89dceb,
  teal: 0x94e2d5,
  green: 0xa6e3a1,
  yellow: 0xf9e2af,
  peach: 0xfab387,
  maroon: 0xeba0ac,
  red: 0xf38ba8,
  mauve: 0xcba6f7,
  pink: 0xf5c2e7,
  flamingo: 0xf2cdcd,
  rosewater: 0xf5e0dc,
  white: 0xffffff,
  snow: 0xe6e9f5,
  wood: 0x6b4f3f,
  woodDark: 0x4a3830,
  leaf: 0x40734a,
  leafDark: 0x2d5238,
  sand: 0xc9a66b,
  sea: 0x1f3a5c,
}

/** Foliage by season (a light and a dark shade). */
export function foliage(season: Season, seed: number): [number, number] {
  const autumn: [number, number][] = [[0xd08a3a, 0x9c5a2a], [0xc0603a, 0x8a3f28], [0xd9b24a, 0xa07a30]]
  switch (season) {
    case 'spring':
      return hash(seed) % 4 === 0 ? [P.pink, 0xb78aa8] : [0x6fbf5f, 0x4a8a42]
    case 'summer':
      return [0x4f8f4a, 0x2f5f34]
    case 'autumn':
      return autumn[hash(seed) % autumn.length]!
    case 'winter':
      return [0x5a6b5f, 0x3c4a42]
  }
}

/** A lit window: the kind's colour, dim by day, bright at night; a fail is always red. */
export function windowColor(kind: WakePulseKind, wall: number, look: Look): number {
  return kind === 'fail' ? KIND_COLOR.fail : mix(KIND_COLOR[kind], wall, 0.55 - 0.4 * look.night)
}

/**
 * Lights the given window slots with the turn's calls, the newest last, so the
 * structure reads as what the turn did. A few windows go dark now and then.
 */
export function lightWindows(c: Canvas, look: Look, b: Building, slots: [number, number][], wall: number) {
  if (slots.length === 0) return // slice(-0) would be every call
  const kinds = b.kinds.slice(-slots.length)
  kinds.forEach((kind, i) => {
    const [x, y] = slots[i]!
    if (kind !== 'fail' && (hash(b.index * 977 + i) + Math.floor(look.frame / 30)) % 31 === 0) return
    c.set(x, y, windowColor(kind, wall, look))
    if (look.night > 0.5 && kind !== 'fail') c.glow(x, y + 1, KIND_COLOR[kind], 0.12)
  })
}

/**
 * A number weighted by the phases' blend, e.g. `byPhase(look, { dusk: 0.3, dawn: 0.2 })`, so a
 * tint fades in and out with the hour instead of switching on one frame. Unnamed phases count 0.
 */
export function byPhase(look: Look, values: Partial<Record<DayPhase, number>>): number {
  let sum = 0
  for (const phase of Object.keys(values) as DayPhase[]) sum += look.blend[phase] * values[phase]!
  return sum
}

/** The low-sun glow: pink at dawn, peach at dusk, and how strong it is now (0..1, fading with the hour). */
export function sunGlow(look: Look): { color: number; amount: number } {
  const amount = look.blend.dawn + look.blend.dusk
  return { color: amount > 0 ? mix(P.pink, P.peach, look.blend.dusk / amount) : P.peach, amount }
}

/** Calls in a turn that edited files. */
export const editsOf = (kinds: WakePulseKind[]) => kinds.filter(kind => kind === 'edit').length

/** A height that grows with the log of the calls, between `min` and `max`. */
export function heightFor(kinds: WakePulseKind[], min: number, max: number, scale = 1.6): number {
  return Math.max(min, Math.min(max, min + Math.round(Math.log2(kinds.length + 1) * scale)))
}

/** 0..1 sine wave over frames. */
export const wave = (frame: number, period: number, phase = 0) => 0.5 + 0.5 * Math.sin(((frame + phase) / period) * Math.PI * 2)

/** The far colour for silhouettes: darker than the horizon by day, a touch lighter at night so they still read. */
export const farTone = (look: Look, depth: number) => mix(mix(look.horizon, P.ink, 0.25 + depth * 0.3), mix(look.horizon, P.surface0, 0.5 + depth * 0.2), look.night)
