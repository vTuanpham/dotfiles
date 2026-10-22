import type { EngineInterface } from 'claude-code'

import type { WakeHour, WakePlace, WakePreset, WakeWeather } from '../../types'

// Where the person is and what the sky is doing there. Keyless public APIs only:
// GeoJS then ipwho.is for the IP's place, Open-Meteo for geocoding a named place
// and for the forecast. Every response is decoded once, strictly, here.

const GEO_IP = 'https://get.geojs.io/v1/ip/geo.json'
const GEO_IP_FALLBACK = 'https://ipwho.is/'
const GEOCODE = 'https://geocoding-api.open-meteo.com/v1/search'
const FORECAST = 'https://api.open-meteo.com/v1/forecast'

export const PRESETS: readonly WakePreset[] = ['city', 'harbor', 'beach', 'mountains', 'countryside', 'forest', 'desert', 'tundra']

/** A finite number from a JSON number, or from a numeric string (GeoJS sends coordinates as strings). */
function num(value: unknown, field: string): number {
  const n = typeof value === 'string' && value.trim() !== '' ? Number(value) : value
  if (typeof n !== 'number' || !Number.isFinite(n)) throw new Error(`${field} is not a finite number`)
  return n
}

function text(value: unknown, field: string): string {
  if (typeof value !== 'string' || value.trim() === '') throw new Error(`${field} is missing`)
  return value.trim()
}

function record(value: unknown, field: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new Error(`${field} is not an object`)
  return value as Record<string, unknown>
}

async function getJson($: EngineInterface, url: string): Promise<unknown> {
  const response = await $.http.fetch(url, { headers: { accept: 'application/json' } })
  if (!response.ok) throw new Error(`${new URL(url).host} answered ${response.status}`)
  return JSON.parse(response.text)
}

function placeOf(name: string, country: string, lat: number, lon: number, source: WakePlace['source']): WakePlace {
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) throw new Error(`coordinates out of range: ${lat},${lon}`)
  return { key: `${name}|${country}`.toLowerCase(), name, country, lat, lon, source }
}

/** The machine's place by its public IP: GeoJS, then ipwho.is. */
export async function locateByIp($: EngineInterface): Promise<WakePlace & { countryCode?: string }> {
  try {
    const d = record(await getJson($, GEO_IP), 'geojs')
    const place = placeOf(text(d.city, 'geojs city'), text(d.country, 'geojs country'), num(d.latitude, 'geojs latitude'), num(d.longitude, 'geojs longitude'), 'ip')
    return typeof d.country_code === 'string' ? { ...place, countryCode: d.country_code } : place
  } catch {
    const d = record(await getJson($, GEO_IP_FALLBACK), 'ipwho.is')
    if (d.success !== true) throw new Error(`ipwho.is: ${typeof d.message === 'string' ? d.message : 'no answer'}`)
    const place = placeOf(text(d.city, 'ipwho.is city'), text(d.country, 'ipwho.is country'), num(d.latitude, 'ipwho.is latitude'), num(d.longitude, 'ipwho.is longitude'), 'ip')
    return typeof d.country_code === 'string' ? { ...place, countryCode: d.country_code } : place
  }
}

/** A named place (or the IP's city, to learn its size and height), by Open-Meteo's geocoder; undefined when nothing matches. */
export async function geocode($: EngineInterface, name: string, countryCode?: string): Promise<WakePlace | undefined> {
  const query = new URLSearchParams({ name, count: '1', language: 'en', format: 'json' })
  if (countryCode) query.set('countryCode', countryCode)
  const d = record(await getJson($, `${GEOCODE}?${query}`), 'geocoder')
  if (d.results === undefined) return undefined // no match: the answer carries no results list
  if (!Array.isArray(d.results)) throw new Error('geocoder results is not a list')
  if (d.results.length === 0) return undefined
  const hit = record(d.results[0], 'geocoder result')
  const place = placeOf(text(hit.name, 'geocoder name'), typeof hit.country === 'string' ? hit.country : '', num(hit.latitude, 'geocoder latitude'), num(hit.longitude, 'geocoder longitude'), 'named')
  return {
    ...place,
    ...(hit.elevation !== undefined ? { elevation: num(hit.elevation, 'geocoder elevation') } : {}),
    ...(hit.population !== undefined ? { population: num(hit.population, 'geocoder population') } : {}),
  }
}

/** A landscape for a place nobody pinned one to: the far north or south is tundra, high ground mountains, a big town a city, a small one countryside. */
export function guessPreset(place: Pick<WakePlace, 'lat' | 'elevation' | 'population'>): WakePreset {
  if (Math.abs(place.lat) >= 60) return 'tundra'
  if ((place.elevation ?? 0) >= 700) return 'mountains'
  if (place.population !== undefined && place.population < 150_000) return 'countryside'
  return 'city'
}

/** "2026-10-15T05:52" -> 5.8667 (local hours; Open-Meteo gives local times under timezone=auto). */
function localHours(stamp: unknown, field: string): number {
  const m = /T(\d{2}):(\d{2})/.exec(text(stamp, field))
  if (!m) throw new Error(`${field} has no time`)
  return Number(m[1]) + Number(m[2]) / 60
}

/** Current conditions, today's sunrise and sunset, and the next 12 hours. */
export async function forecast($: EngineInterface, place: Pick<WakePlace, 'lat' | 'lon'>, now: number): Promise<WakeWeather> {
  const query = new URLSearchParams({
    latitude: place.lat.toFixed(3),
    longitude: place.lon.toFixed(3),
    current: 'temperature_2m,weather_code,is_day,cloud_cover,precipitation,snowfall,wind_speed_10m',
    hourly: 'temperature_2m,precipitation_probability,weather_code',
    daily: 'sunrise,sunset',
    timezone: 'auto',
    forecast_days: '1',
    forecast_hours: '12',
  })
  const d = record(await getJson($, `${FORECAST}?${query}`), 'forecast')
  if (d.error === true) throw new Error(`open-meteo: ${String(d.reason)}`)
  const cur = record(d.current, 'current')
  const hourly = record(d.hourly, 'hourly')
  const daily = record(d.daily, 'daily')
  const times = hourly.time
  const temps = hourly.temperature_2m
  const pops = hourly.precipitation_probability
  const codes = hourly.weather_code
  if (![times, temps, pops, codes].every(Array.isArray)) throw new Error('hourly series are not lists')
  const n = (times as unknown[]).length
  if ([temps, pops, codes].some(series => (series as unknown[]).length !== n)) throw new Error('hourly series differ in length')
  const hours: WakeHour[] = (times as unknown[]).map((time, i) => ({
    time: text(time, 'hourly time'),
    temp: num((temps as unknown[])[i], 'hourly temperature'),
    pop: (pops as unknown[])[i] === null ? 0 : num((pops as unknown[])[i], 'hourly precipitation probability'), // null where a model has no probability
    code: num((codes as unknown[])[i], 'hourly weather code'),
  }))
  const sunrise = (daily.sunrise as unknown[] | undefined)?.[0]
  const sunset = (daily.sunset as unknown[] | undefined)?.[0]
  return {
    fetchedAt: now,
    utcOffsetSeconds: num(d.utc_offset_seconds, 'utc_offset_seconds'),
    temp: num(cur.temperature_2m, 'temperature_2m'),
    code: num(cur.weather_code, 'weather_code'),
    isDay: num(cur.is_day, 'is_day') === 1,
    cloud: num(cur.cloud_cover, 'cloud_cover'),
    precipitation: num(cur.precipitation, 'precipitation'),
    snowfall: num(cur.snowfall, 'snowfall'),
    wind: num(cur.wind_speed_10m, 'wind_speed_10m'),
    sunrise: localHours(sunrise, 'sunrise'),
    sunset: localHours(sunset, 'sunset'),
    hours,
  }
}

/** What a WMO weather code looks like in the scene. */
export type Sky = { label: string; icon: number; rain: 0 | 1 | 2 | 3; snow: 0 | 1 | 2 | 3; fog: boolean; thunder: boolean }

export function skyOf(code: number, isDay: boolean): Sky {
  const clear = { rain: 0, snow: 0, fog: false, thunder: false } as const
  if (code === 0) return { ...clear, label: 'clear', icon: isDay ? 0xe30d : 0xe32b }
  if (code === 1) return { ...clear, label: 'mainly clear', icon: isDay ? 0xe30c : 0xe37b }
  if (code === 2) return { ...clear, label: 'partly cloudy', icon: isDay ? 0xe302 : 0xe37e }
  if (code === 3) return { ...clear, label: 'overcast', icon: 0xe312 }
  if (code === 45 || code === 48) return { ...clear, fog: true, label: 'fog', icon: 0xe313 }
  if (code >= 51 && code <= 57) return { ...clear, rain: 1, label: 'drizzle', icon: 0xe319 }
  if (code === 61 || code === 80 || code === 66) return { ...clear, rain: 1, label: 'light rain', icon: 0xe319 }
  if (code === 63 || code === 81) return { ...clear, rain: 2, label: 'rain', icon: 0xe318 }
  if (code === 65 || code === 82 || code === 67) return { ...clear, rain: 3, label: 'heavy rain', icon: 0xe318 }
  if (code === 71 || code === 85 || code === 77) return { ...clear, snow: 1, label: 'light snow', icon: 0xe31a }
  if (code === 73) return { ...clear, snow: 2, label: 'snow', icon: 0xe31a }
  if (code === 75 || code === 86) return { ...clear, snow: 3, label: 'heavy snow', icon: 0xe31a }
  if (code >= 95) return { ...clear, rain: 3, thunder: true, label: 'thunderstorm', icon: 0xe31d }
  return { ...clear, label: `code ${code}`, icon: 0xe312 }
}

/** The next hour worth mentioning: the first where rain or snow is likely (40%+), else none; a wet code at a low chance is noise. */
export function nextRain(hours: WakeHour[]): WakeHour | undefined {
  return hours.find(hour => hour.pop >= 40)
}
