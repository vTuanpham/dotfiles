import { expect, test } from 'claude-code/testing'

import { LANDSCAPES } from '../hooks/landscapes'
import { SCENE_H } from '../hooks/landscapes/kit'
import { hash } from '../hooks/pixels'
import { type SceneInput, scenePixels } from '../hooks/scene'
import { readable } from '../hooks/util'

const base: SceneInput = {
  width: 120,
  frame: 0,
  hour: 12,
  sun: { rise: 6, set: 18 },
  moonPhase: 0.3,
  season: 'summer',
  snowy: false,
  weather: null,
  preset: 'city',
  seed: 7,
  turns: Array.from({ length: 30 }, (_, i) => ({ kinds: Array.from({ length: (i * 5) % 40 }, (_, k) => (['read', 'edit', 'test', 'fail', 'agent'] as const)[k % 5]!) })),
  live: { kinds: ['read', 'edit'] },
  mood: 'work',
  jobs: [{ isStale: false, seed: 1 }, { isStale: true, seed: 2 }],
  agents: [{ seed: 11, tier: 1 }, { seed: 12, tier: 2 }, { seed: 13, tier: 3 }],
  plan: { done: 1, total: 4 },
  effect: null,
}

const weathers: SceneInput['weather'][] = [
  null,
  { cloud: 1, rain: 3, snow: 0, fog: false, thunder: true, wind: 40 },
  { cloud: 0.6, rain: 0, snow: 3, fog: true, thunder: false, wind: 5 },
]

test('every landscape draws a full frame at any width, hour, weather, season and effect', () => {
  for (const preset of Object.keys(LANDSCAPES) as SceneInput['preset'][]) {
    for (const width of [24, 90, 260]) {
      for (const [i, hour] of [2, 6, 9, 12.5, 15, 17.8, 21].entries()) {
        const input: SceneInput = {
          ...base,
          preset,
          width,
          hour,
          frame: i * 397 + (i % 2) / 2,
          season: (['spring', 'summer', 'autumn', 'winter'] as const)[i % 4]!,
          snowy: i % 4 === 3,
          weather: weathers[i % weathers.length]!,
          mood: (['work', 'idle', 'happy', 'sad', 'sleep', 'alert', 'work'] as const)[i]!,
          live: i % 2 ? null : base.live,
          effect: ([null, { kind: 'fireworks', age: 12.5 }, { kind: 'storm', age: 3.5 }, { kind: 'shoot', age: 9.5 }] as const)[i % 4]!,
        }
        const px = scenePixels(input)
        expect(px.length).toBe(width * SCENE_H)
      }
      for (const event of LANDSCAPES[preset].events) {
        for (const frame of [31, 31.5]) expect(scenePixels({ ...base, preset, width, hour: 22, forceEvent: event.name, frame }).indexOf(0)).toBe(-1)
      }
    }
  }
})

test('hash stays a non-negative int31, so signed shifts and modulo index arrays safely', () => {
  for (let n = -5000; n < 5000; n += 7) {
    const h = hash(n * 2654435761)
    expect(h >= 0 && h < 2 ** 31 && Number.isInteger(h)).toBe(true)
    expect(h >> 8).toBeGreaterThanOrEqual(0)
  }
})

test('words on the scene floor stay readable: text 4.5:1, accents 3:1, light floors or dark', () => {
  const lum = (hex: string) => {
    const [r, g, b] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255).map(c => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
    return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!
  }
  const ratio = (a: string, b: string) => (Math.max(lum(a), lum(b)) + 0.05) / (Math.min(lum(a), lum(b)) + 0.05)
  for (const floor of ['#181825', '#d9c08a', '#e6e9f5', '#585b70', '#1f3a5c']) {
    const ink = readable(floor)
    expect(ratio(ink.text, floor)).toBeGreaterThanOrEqual(4.5)
    expect(ratio(ink.subtext, floor)).toBeGreaterThanOrEqual(4.5)
    for (const key of ['green', 'red', 'peach', 'teal', 'pink', 'blue'] as const) expect(ratio(ink[key], floor)).toBeGreaterThanOrEqual(3)
    expect(ratio(ink.subtle, floor)).toBeGreaterThanOrEqual(3)
  }
})

test('a crew member keeps its place by who it is: the same jobs and birds in another order draw the same frame', () => {
  const kinds = ['codex', 'agy', 'claude', 'opencode'] as const
  const jobs = Array.from({ length: 7 }, (_, i) => ({ isStale: i === 5, seed: hash(i + 40), kind: kinds[i % 4], tier: ((i % 3) + 1) as 1 | 2 | 3, maker: i === 1 ? ('claude' as const) : undefined }))
  const agents = Array.from({ length: 6 }, (_, i) => ({ seed: hash(i + 90), tier: ((i % 3) + 1) as 1 | 2 | 3 }))
  const shuffled = <T,>(list: T[]) => [...list.slice(3), ...list.slice(0, 3)].reverse()
  for (const preset of ['city', 'harbor', 'beach'] as const) {
    for (const frame of [0, 137.5]) {
      const at = { ...base, preset, width: 186, frame, hour: 22 }
      expect(scenePixels({ ...at, jobs: shuffled(jobs), agents: shuffled(agents) })).toEqual(scenePixels({ ...at, jobs, agents }))
    }
  }
})

test('a whole day played in half frames, as the band paints it, draws no black pixel (an undefined colour) in any landscape', () => {
  for (const preset of Object.keys(LANDSCAPES) as SceneInput['preset'][]) {
    for (let t = 0; t < 120; t++) {
      const px = scenePixels({ ...base, preset, width: 186, frame: 5000 + t / 2, hour: (4 + (t / 120) * 24) % 24, weather: weathers[1]! })
      expect(px.indexOf(0)).toBe(-1)
    }
  }
})
