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
  subagents: { id: string; name?: string; description: string; type: string; model?: string; tier: 1 | 2 | 3 | 4 }[]
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
  const finished = numbers.filter(n => !(live && n === current)).map(turn => ({ ...byTurn.get(turn)!, turn }))
  return { turns: finished, live: live ? { ...(byTurn.get(current) ?? { kinds: [] }), turn: current } : null }
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
    peerEdges: state.chips.filter(job => job.running && job.id).flatMap(job => (job.peers ?? [])
      .filter(peer => (peer.target === 'root' ? peer.messageState !== undefined : peer.outgoing)
        && now >= peer.lastAt && now - peer.lastAt <= 900_000)
      .map(peer => {
        const age = now - peer.lastAt
        const pulse = peer.observedAt !== undefined && now >= peer.observedAt && now - peer.observedAt < 2_000
        const rootMessage = peer.target === 'root'
        return {
          source: rootMessage && !peer.outgoing ? 'mochi' : job.id!,
          target: rootMessage ? peer.outgoing ? 'mochi' : job.id! : peer.target,
          strength: pulse ? 0.65 + 0.35 * (Math.floor((now - peer.observedAt!) / 400) % 2) : Math.max(0.25, 1 - age / 900_000 * 0.75),
          preview: peer.preview ?? null,
          messageState: rootMessage ? peer.messageState : undefined,
        }
      })),
    jobs: state.chips.filter(job => job.running).map(job => {
      const peer = [...(job.peers ?? [])].filter(p => now - p.lastAt <= 900_000 && now >= p.lastAt).sort((a, b) => b.lastAt - a.lastAt)[0]
      return {
      isStale: job.isStale, seed: seedOf(job.name), tier: modelTier(job.backend ?? 'codex', job.model),
      kind: (['agy', 'claude', 'opencode'] as const).find(kind => kind === job.backend) ?? ('codex' as const), maker: job.maker,
      signal: !!peer && peer.observedAt !== undefined && now >= peer.observedAt && now - peer.observedAt < 2_000 && Math.floor((now - peer.observedAt) / 400) % 2 === 1,
      hit: job.id || job.owner ? {
        id: job.id ?? `${job.owner}/${job.name}`, title: job.title ?? job.name,
        details: [
          ...(peer ? [`${peer.outgoing ? 'To' : 'From'}: ${peer.target}`, peer.preview || 'Message preview unavailable'] : []),
          ...(peer?.messageState === 'observed' ? ['Worker output observed; root read status unknown'] : []),
          ...(peer?.messageState === 'sent' ? ['Bridge sent; worker read status unknown'] : []),
          `Harness: ${job.backend ?? 'codex'}`,
          job.model ? `Model ID: ${job.model}` : 'Model ID unavailable',
          ...(job.effort ? [`Effort: ${job.effort}`] : []),
        ],
      } : undefined,
    }}),
    agents: state.subagents.map(agent => ({
      id: agent.id, seed: seedOf(agent.id), tier: agent.tier,
      hit: {
        id: agent.id, title: agent.name ?? agent.description,
        details: [`Claude subagent · ${agent.type}`, agent.model ? `Model ID: ${agent.model}` : 'Model ID unavailable'],
      },
    })),
    plan: state.plan.length > 0 ? { done, total: state.plan.length } : null,
    effect,
  }
}
