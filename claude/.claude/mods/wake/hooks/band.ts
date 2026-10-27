import type { WakeChip, WakeMood, WakePulse, WakeStep, WakeSurroundings, WakeTally, WakeWeather } from '../types'
import type { Season } from './landscapes/kit'
import { seedOf } from './pixels'
import type { SceneEffect, SceneInput, SceneTurn, SceneWeather } from './scene'
import { modelTier } from './sources/accounts'
import { skyOf } from './sources/weather'

// From the session's state and the surroundings to what the scene draws. Pure.

/** The state the scene reads, gathered by the hooks module (which owns $.state). */
export type BandState = {
  here: WakeSurroundings | null
  tally: WakeTally
  turnStartedAt: number | null
  pulse: WakePulse[]
  plan: WakeStep[]
  mood: WakeMood
  chips: WakeChip[]
  subagents: { id: string; tier: 1 | 2 | 3 | 4 }[] // running subagents: identity and model class
}

const SYNODIC_DAYS = 29.530588853
const NEW_MOON_2000 = Date.UTC(2000, 0, 6, 18, 14)

/** 0 new .. 0.5 full .. 1 new. */
export const moonPhase = (now: number) => ((((now - NEW_MOON_2000) / 86_400_000 / SYNODIC_DAYS) % 1) + 1) % 1

/** Local hours at the place: from the forecast's UTC offset, else the machine's clock. */
export function localHour(now: number, weather: WakeWeather | null): number {
  if (weather) return ((((now / 1000 + weather.utcOffsetSeconds) / 3600) % 24) + 24) % 24
  const d = new Date(now)
  return d.getHours() + d.getMinutes() / 60
}

/** The season at a latitude in a month (0-11); the tropics stay in summer. */
export function seasonAt(lat: number, month: number): Season {
  if (Math.abs(lat) < 23.5) return 'summer'
  const north: Season[] = ['winter', 'winter', 'spring', 'spring', 'spring', 'summer', 'summer', 'summer', 'autumn', 'autumn', 'autumn', 'winter']
  const s = north[month]!
  if (lat >= 0) return s
  return ({ winter: 'summer', summer: 'winter', spring: 'autumn', autumn: 'spring' } as const)[s]
}

export function sceneWeather(w: WakeWeather): SceneWeather {
  const sky = skyOf(w.code, w.isDay)
  return { cloud: Math.max(0, Math.min(1, w.cloud / 100)), rain: sky.rain, snow: sky.snow, fog: sky.fog, thunder: sky.thunder, wind: w.wind }
}

/** Turns as structures: finished ones, and the one in progress while a turn runs. */
function turnsOf(beats: { kind: SceneTurn['kinds'][number]; turn: number }[], current: number, live: boolean) {
  const byTurn = new Map<number, SceneTurn>()
  for (const beat of beats) {
    const turn = byTurn.get(beat.turn) ?? { kinds: [] }
    turn.kinds.push(beat.kind)
    byTurn.set(beat.turn, turn)
  }
  const numbers = [...byTurn.keys()].sort((a, b) => a - b)
  const finished = numbers.filter(n => !(live && n === current)).map(n => byTurn.get(n)!)
  return { turns: finished, live: live ? (byTurn.get(current) ?? { kinds: [] }) : null }
}

export function sceneInput(state: BandState, width: number, frame: number, effect: SceneEffect | null, now: number): SceneInput {
  const here = state.here
  const weather = here?.weather ?? null
  const { turns, live } = turnsOf(state.pulse, state.tally.turns, state.turnStartedAt !== null)
  const done = state.plan.filter(step => step.status === 'completed').length
  const localMs = weather ? now + weather.utcOffsetSeconds * 1000 : now
  const season = seasonAt(here?.place.lat ?? 45, new Date(localMs).getUTCMonth())
  const sky = weather ? skyOf(weather.code, weather.isDay) : undefined
  return {
    width,
    frame,
    hour: localHour(now, weather),
    sun: weather ? { rise: weather.sunrise, set: weather.sunset } : { rise: 6, set: 18 },
    moonPhase: moonPhase(now),
    season,
    snowy: weather ? weather.snowfall > 0 || (sky?.snow ?? 0) > 0 || (season === 'winter' && weather.temp <= 0) : false,
    weather: weather ? sceneWeather(weather) : null,
    preset: here?.preset ?? 'city',
    seed: seedOf(here?.place.key ?? 'wake'),
    turns,
    live,
    mood: state.mood,
    jobs: state.chips.filter(job => job.running).map(job => ({ isStale: job.isStale, seed: seedOf(job.name), tier: modelTier(job.backend ?? 'codex', job.model), kind: (['agy', 'claude', 'opencode'] as const).find(kind => kind === job.backend) ?? ('codex' as const), maker: job.maker })),
    agents: state.subagents.map(agent => ({ seed: seedOf(agent.id), tier: agent.tier })),
    plan: state.plan.length > 0 ? { done, total: state.plan.length } : null,
    effect,
  }
}
