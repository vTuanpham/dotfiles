import type { EngineInterface } from 'claude-code'

import type { WakePlace, WakePreset, WakeSurroundings, WakeWeather } from '../types'
import { PRESETS, forecast, geocode, guessPreset, locateByIp } from './sources/weather'

// Where the band's scene is: the place (by IP, or one the person named), the
// landscape (pinned per place, else guessed), and the weather there. Kept in the
// mod's store so every session on the machine shares one lookup.
//
// Store keys:
//   place    WakePlace | null   a place the person named (/wake place <name>)
//   geo      { at, place }      the IP's place, looked up at most every GEO_TTL
//   pins     { [placeKey]: WakePreset }
//   weather  { [placeKey]: WakeWeather }

const GEO_TTL = 3 * 3600_000
const WEATHER_TTL = 20 * 60_000

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const isFiniteNumber = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

/** A stored place, or undefined when the store holds something else (an older shape, a hand edit). */
function storedPlace(v: unknown): WakePlace | undefined {
  if (!isObject(v)) return undefined
  const ok = typeof v.key === 'string' && typeof v.name === 'string' && typeof v.country === 'string' && isFiniteNumber(v.lat) && isFiniteNumber(v.lon) && (v.source === 'ip' || v.source === 'named')
  return ok ? (v as WakePlace) : undefined
}

function storedWeather(v: unknown): WakeWeather | undefined {
  if (!isObject(v)) return undefined
  const numbers = ['fetchedAt', 'utcOffsetSeconds', 'temp', 'code', 'cloud', 'precipitation', 'snowfall', 'wind', 'sunrise', 'sunset']
  return numbers.every(k => isFiniteNumber(v[k])) && typeof v.isDay === 'boolean' && Array.isArray(v.hours) ? (v as WakeWeather) : undefined
}

const isPreset = (v: unknown): v is WakePreset => typeof v === 'string' && (PRESETS as readonly string[]).includes(v)

async function storedMap($: EngineInterface, key: string): Promise<Record<string, unknown>> {
  const v = await $.store.get(key)
  return isObject(v) ? v : {}
}

/** Fills in a place's height and size from the geocoder, so a landscape can be guessed. */
async function described($: EngineInterface, place: WakePlace & { countryCode?: string }): Promise<WakePlace> {
  if (place.elevation !== undefined || place.population !== undefined) return place
  const hit = await geocode($, place.name, place.countryCode).catch(() => undefined)
  const { countryCode: _, ...rest } = place
  return { ...rest, ...(hit?.elevation !== undefined ? { elevation: hit.elevation } : {}), ...(hit?.population !== undefined ? { population: hit.population } : {}) }
}

async function currentPlace($: EngineInterface, now: number, force: boolean): Promise<WakePlace | undefined> {
  const named = storedPlace(await $.store.get('place'))
  if (named) return named
  const geo = await $.store.get('geo')
  const cached = isObject(geo) && isFiniteNumber(geo.at) ? storedPlace(geo.place) : undefined
  if (cached && !force && now - (geo as { at: number }).at < GEO_TTL) return cached
  try {
    const place = await described($, await locateByIp($))
    await $.store.set('geo', { at: now, place })
    return place
  } catch {
    return cached // offline or refused: keep the last known place
  }
}

/** Where the scene is now (place, pin, weather), looking up only what went stale; null while the place is unknown. */
export async function lookAround($: EngineInterface, force = false): Promise<WakeSurroundings | null> {
  const now = await $.clock.now()
  const place = await currentPlace($, now, force)
  if (!place) return null
  const pins = await storedMap($, 'pins')
  const pinned = pins[place.key]
  const cache = await storedMap($, 'weather')
  let weather = storedWeather(cache[place.key]) ?? null
  if (force || !weather || now - weather.fetchedAt >= WEATHER_TTL) {
    try {
      weather = await forecast($, place, now)
      await $.store.set('weather', { ...cache, [place.key]: weather })
    } catch {
      // keep the stale forecast; the scene falls back to the machine clock without one
    }
  }
  return {
    place,
    preset: isPreset(pinned) ? pinned : guessPreset(place),
    presetSource: isPreset(pinned) ? 'pinned' : 'guessed',
    weather,
  }
}

/** `/wake scene <preset|auto>`: pins a landscape to the current place; the answer for the person. */
export async function pinPreset($: EngineInterface, here: WakeSurroundings | null, choice: string): Promise<string> {
  if (!here) return 'Wake does not know where you are yet; try /wake place <city>.'
  const pins = await storedMap($, 'pins')
  if (choice === 'auto') {
    const { [here.place.key]: _, ...rest } = pins
    await $.store.set('pins', rest)
    return `${here.place.name}: ${guessPreset(here.place)} (guessed).`
  }
  if (!isPreset(choice)) return `Scenes: ${PRESETS.join(', ')}, or auto.`
  await $.store.set('pins', { ...pins, [here.place.key]: choice })
  return `${here.place.name}: ${choice} (pinned).`
}

/** `/wake place <name|auto>`: names where you are, or goes back to the IP's place; the answer for the person. */
export async function namePlace($: EngineInterface, name: string): Promise<string> {
  if (name === 'auto') {
    await $.store.delete('place')
    return 'Following your IP again.'
  }
  const hit = await geocode($, name).catch(() => undefined)
  if (!hit) return `No place called "${name}".`
  await $.store.set('place', hit)
  return `Now at ${hit.name}${hit.country ? `, ${hit.country}` : ''}.`
}
