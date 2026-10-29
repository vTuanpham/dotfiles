import { expect, test } from 'claude-code/testing'

import { LANDSCAPES } from '../hooks/landscapes'
import { P, SCENE_H } from '../hooks/landscapes/kit'
import { canvas, hash, seedOf } from '../hooks/pixels'
import { CAT_COLUMNS, type SceneInput, lookOf, readScenePointer, sceneFrame, sceneHitAt, scenePixels } from '../hooks/scene'
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

test('a real message edge connects visible workers and exposes its preview', () => {
  const input: SceneInput = { ...base, width: 120, turns: [], live: null, plan: null, agents: [], jobs: [
    { isStale: false, seed: 1, hit: { id: 'a', title: 'A', details: [] } },
    { isStale: false, seed: 2, hit: { id: 'b', title: 'B', details: [] } },
  ], peerEdges: [{ source: 'a', target: 'b', strength: 1, preview: 'Review tests' }] }
  const frame = sceneFrame(input)
  const edge = frame.hits.targets.findIndex(item => item.id === 'peer:a:b') + 1
  expect(edge).toBeGreaterThan(0)
  expect(frame.hits.owners).toContain(edge)
  expect(frame.hits.targets[edge - 1]!.details).toEqual(['Review tests'])
  const noMessage = sceneFrame({ ...input, peerEdges: [] })
  expect(noMessage.hits.targets.some(item => item.id.startsWith('peer:'))).toBe(false)
  const graphPixels = scenePixels(input)
  const plainPixels = scenePixels({ ...input, peerEdges: [] })
  for (let cell = 0; cell < noMessage.hits.owners.length; cell++) {
    const owner = noMessage.hits.owners[cell]!
    if (!owner || noMessage.hits.targets[owner - 1]!.id.startsWith('peer:') || noMessage.hits.targets[owner - 1]!.id === 'sky') continue
    const x = cell % input.width, y = Math.floor(cell / input.width) * 2
    expect(graphPixels[y * input.width + x]).toBe(plainPixels[y * input.width + x])
    expect(graphPixels[(y + 1) * input.width + x]).toBe(plainPixels[(y + 1) * input.width + x])
  }
  const missingTarget = sceneFrame({ ...input, jobs: input.jobs.slice(0, 1) })
  expect(missingTarget.hits.targets.some(item => item.id.startsWith('peer:'))).toBe(false)
  const blocked = sceneFrame({ ...input, width: 80 })
  expect(blocked.hits.targets.some(item => item.id.startsWith('peer:'))).toBe(false)
})

test('Bridge root messages connect to Mochi in the recorded direction without covering scene objects', () => {
  const job = { isStale: false, seed: 1, hit: { id: 'owner/job', title: 'Worker', details: [] } }
  const rootToWorker: SceneInput = {
    ...base, width: 100, turns: [], live: null, plan: null, agents: [], jobs: [job],
    peerEdges: [{ source: 'mochi', target: 'owner/job', strength: 1, preview: 'Inspect this result', messageState: 'sent' }],
  }
  const workerToRoot: SceneInput = {
    ...rootToWorker,
    peerEdges: [{ source: 'owner/job', target: 'mochi', strength: 1, preview: 'Result is ready', messageState: 'observed' }],
  }
  const incoming = sceneFrame(rootToWorker)
  const outgoing = sceneFrame(workerToRoot)
  const incomingTarget = incoming.hits.targets.find(item => item.id === 'peer:mochi:owner/job')
  const outgoingTarget = outgoing.hits.targets.find(item => item.id === 'peer:owner/job:mochi')
  expect(incomingTarget).toMatchObject({
    title: 'Root → Worker',
    details: ['Bridge sent; worker read status unknown', 'Inspect this result'],
  })
  expect(outgoingTarget).toMatchObject({
    title: 'Worker → root',
    details: ['Worker output observed by Bridge; root read status unknown', 'Result is ready'],
  })
  expect(incoming.hits.owners).toContain(incoming.hits.targets.indexOf(incomingTarget!) + 1)
  expect(outgoing.hits.owners).toContain(outgoing.hits.targets.indexOf(outgoingTarget!) + 1)
  expect(incoming.cells).not.toBe(outgoing.cells) // the bright terminal mark follows the recorded destination
  const both = sceneFrame({ ...rootToWorker, peerEdges: [...rootToWorker.peerEdges!, ...workerToRoot.peerEdges!] })
  expect(both.hits.targets.filter(item => item.id.startsWith('peer:')).map(item => item.id)).toEqual(['peer:mochi:owner/job', 'peer:owner/job:mochi'])

  const background = scenePixels({ ...rootToWorker, peerEdges: [] })
  const linked = scenePixels(rootToWorker)
  const plainHits = sceneFrame({ ...rootToWorker, peerEdges: [] }).hits
  for (let cell = 0; cell < plainHits.owners.length; cell++) {
    const owner = plainHits.owners[cell]!
    if (!owner || plainHits.targets[owner - 1]!.id === 'sky') continue
    const x = cell % rootToWorker.width, y = Math.floor(cell / rootToWorker.width) * 2
    expect(linked[y * rootToWorker.width + x]).toBe(background[y * rootToWorker.width + x])
    expect(linked[(y + 1) * rootToWorker.width + x]).toBe(background[(y + 1) * rootToWorker.width + x])
  }
})

test('crowded workers preserve the pre-existing scene hit pixels', () => {
  const jobs = Array.from({ length: 30 }, (_, i) => ({ isStale: false, seed: hash(i + 100), kind: 'codex' as const }))
  for (const preset of Object.keys(LANDSCAPES) as SceneInput['preset'][]) for (const width of [24, 80]) {
    const input: SceneInput = { ...base, preset, width, jobs, agents: [], weather: null, effect: null }
    const empty = { ...input, jobs: [] }
    const frame = sceneFrame(empty)
    const background = scenePixels(empty)
    const crowded = scenePixels(input)
    for (let cell = 0; cell < frame.hits.owners.length; cell++) {
      if (!frame.hits.owners[cell] || ['sky', 'scenery'].includes(frame.hits.targets[frame.hits.owners[cell]! - 1]!.id)) continue
      const x = cell % width, y = Math.floor(cell / width) * 2
      if (crowded[y * width + x] !== background[y * width + x] || crowded[(y + 1) * width + x] !== background[(y + 1) * width + x]) throw new Error(`${preset} width ${width} cell ${x},${y} owner ${frame.hits.targets[frame.hits.owners[cell]! - 1]!.id}`)
      expect(crowded[y * width + x]).toBe(background[y * width + x])
      expect(crowded[(y + 1) * width + x]).toBe(background[(y + 1) * width + x])
    }
  }
})

test('unchanged sky and scenery have source-grounded hover targets', () => {
  const input: SceneInput = { ...base, width: 100, preset: 'city', jobs: [], agents: [], turns: [], live: null, weather: null, effect: null }
  const frame = sceneFrame(input)
  const ids = new Set(frame.hits.owners.filter(Boolean).map(owner => frame.hits.targets[owner - 1]!.id))
  expect(ids.has('sky')).toBe(true)
  expect(ids.has('scenery')).toBe(true)
  expect(frame.hits.owners.some((owner, cell) => Math.floor(cell / input.width) * 2 >= LANDSCAPES.city.ground && frame.hits.targets[owner - 1]?.id === 'scenery')).toBe(true)
  expect(ids.has('sun')).toBe(true)
  expect(frame.hits.targets.find(target => target.id === 'sky')!.details).toContain('Weather unavailable')
  const wet = sceneFrame({ ...input, weather: { cloud: 1, rain: 3, snow: 0, fog: false, thunder: true, wind: 40 } })
  expect(wet.hits.targets.find(target => target.id === 'weather')!.details).toContain('Thunderstorm')
  const night = sceneFrame({ ...input, hour: 22 })
  expect(night.hits.targets.some(target => target.id === 'moon')).toBe(true)
  const cloudy = { ...input, weather: { cloud: 0.7, rain: 0 as const, snow: 0 as const, fog: false, thunder: false, wind: 40 }, seed: 7 }
  const visibleSun = sceneFrame({ ...cloudy, frame: 0 }).hits
  const obscuredSun = sceneFrame({ ...cloudy, frame: 110 }).hits
  const countSun = (map: typeof visibleSun) => map.owners.filter(owner => map.targets[owner - 1]?.id === 'sun').length
  expect(countSun(visibleSun)).toBeGreaterThan(0)
  expect(countSun(obscuredSun)).toBe(0)
  const foreground = canvas(input.width, SCENE_H)
  LANDSCAPES.city.foreground(foreground, lookOf(input), input.width - CAT_COLUMNS - 6)
  expect(frame.hits.owners.some((owner, cell) => {
    const x = cell % input.width, y = Math.floor(cell / input.width) * 2
    return frame.hits.targets[owner - 1]?.id === 'foreground' && (foreground.get(x, y) !== 0 || foreground.get(x, y + 1) !== 0)
  })).toBe(true)
})

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
    expect(ratio(ink.green, floor)).toBeGreaterThanOrEqual(3)
    expect(ratio(ink.subtle, floor)).toBeGreaterThanOrEqual(3)
  }
})

test('a crew member keeps its place by who it is: the same jobs and birds in another order draw the same frame', () => {
  const kinds = ['codex', 'agy', 'claude', 'opencode'] as const
  const jobs = Array.from({ length: 8 }, (_, i) => ({ isStale: i === 5, seed: hash(i + 40), kind: kinds[i % 4], tier: ((i % 4) + 1) as 1 | 2 | 3 | 4, maker: i === 1 ? ('claude' as const) : undefined }))
  const agents = Array.from({ length: 6 }, (_, i) => ({ seed: hash(i + 90), tier: ((i % 4) + 1) as 1 | 2 | 3 | 4 }))
  const shuffled = <T,>(list: T[]) => [...list.slice(3), ...list.slice(0, 3)].reverse()
  for (const preset of ['city', 'harbor', 'beach'] as const) {
    for (const frame of [0, 137.5]) {
      const at = { ...base, preset, width: 186, frame, hour: 22 }
      expect(scenePixels({ ...at, jobs: shuffled(jobs), agents: shuffled(agents) })).toEqual(scenePixels({ ...at, jobs, agents }))
    }
  }
})

test('one to twelve flyers retain visible, distinct anchors in every landscape', { timeoutMs: 60_000 }, () => {
  for (const preset of Object.keys(LANDSCAPES) as SceneInput['preset'][]) {
    for (const kind of ['codex', 'agy', 'claude', 'opencode'] as const) for (const hour of [13, 22]) for (let count = 1; count <= 12; count++) {
      if (kind === 'codex' && (preset === 'harbor' || preset === 'beach')) continue // these jobs use boats
      const jobs = Array.from({ length: count }, (_, i) => ({ isStale: i === 3, seed: hash(i + 41), kind, tier: (i % 4 + 1) as 1 | 2 | 3 | 4 }))
      const input = { ...base, preset, width: 260, hour, frame: 40, jobs, agents: [], weather: null, effect: null }
      const anchors: number[] = []
      const pixels = scenePixels(input, anchors)
      const background = scenePixels({ ...input, jobs: [] })
      expect(anchors.length).toBe(count)
      expect(new Set(anchors).size).toBe(count)
      for (const anchor of anchors) {
        const x = anchor % input.width, y = Math.floor(anchor / input.width)
        let visible = false
        for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) {
          const px = x + dx, py = y + dy
          if (px >= 0 && px < input.width && py >= 0 && py < SCENE_H && pixels[py * input.width + px] !== background[py * input.width + px]) visible = true
        }
        expect(visible).toBe(true)
      }
    }
  }
})

test('narrow-scene flyers retain visible anchors without displacing scenery', () => {
  const jobs = Array.from({ length: 12 }, (_, i) => ({ isStale: false, seed: hash(i + 41), kind: 'opencode' as const, tier: (i % 4 + 1) as 1 | 2 | 3 | 4 }))
  for (const preset of Object.keys(LANDSCAPES) as SceneInput['preset'][]) {
    const input = { ...base, preset, width: 24, hour: 13, frame: 40, jobs, agents: [], weather: null, effect: null }
    const anchors: number[] = []
    const pixels = scenePixels(input, anchors)
    expect(anchors.length).toBeLessThanOrEqual(jobs.length)
    for (const anchor of anchors) if (pixels[anchor] !== P.wood) throw new Error(`${preset} anchor ${anchor} became ${pixels[anchor]?.toString(16)}`)
  }
})

test('narrow Codex anchors remain distinct through crowded water and night skies', () => {
  for (const preset of Object.keys(LANDSCAPES) as SceneInput['preset'][]) for (const hour of [13, 17.8, 22]) for (const sample of [2, 3, 7]) {
    const jobs = Array.from({ length: 12 }, (_, i) => ({ isStale: i === 3, seed: hash(i + sample * 41 + 41), kind: 'codex' as const, tier: ((i + sample) % 4 + 1) as 1 | 2 | 3 | 4 }))
    const anchors: number[] = []
    scenePixels({ ...base, preset, width: 24, hour, frame: sample * 31, jobs, agents: [], weather: null, effect: null }, anchors)
    expect(anchors.length).toBeLessThanOrEqual(jobs.length)
    expect(new Set(anchors).size).toBe(anchors.length)
  }
})

test('crew does not jump between distant lanes as the scene animates', { timeoutMs: 60_000 }, () => {
  const kinds = ['codex', 'agy', 'claude', 'opencode'] as const
  const jobs = kinds.map((kind, i) => ({ kind, tier: (i + 1) as 1 | 2 | 3 | 4, seed: seedOf(`j${i}`), isStale: false }))
  for (const preset of Object.keys(LANDSCAPES) as SceneInput['preset'][]) for (const turns of [[], base.turns.slice(0, 8)]) {
    let previous: number[] = []
    for (let frame = 0; frame < 180; frame++) {
      const anchors: number[] = []
      scenePixels({ ...base, preset, frame, turns, live: null, mood: 'idle', jobs, agents: [], plan: null }, anchors)
      expect(anchors).toHaveLength(jobs.length)
      if (previous.length) for (const [i, anchor] of anchors.entries()) {
        const old = previous[i]!
        const distance = Math.abs(anchor % base.width - old % base.width) + Math.abs(Math.floor(anchor / base.width) - Math.floor(old / base.width))
        if (distance > 6) throw new Error(`${preset} frame ${frame}: worker moved ${distance} pixels`)
      }
      previous = anchors
    }
  }
})

test('crowded beach packing keeps distinct anchors', () => {
  const jobs = Array.from({ length: 20 }, (_, i) => ({ kind: 'codex' as const, tier: (i % 4 + 1) as 1 | 2 | 3 | 4, seed: seedOf(`j${i}`), isStale: false }))
  const anchors: number[] = []
  scenePixels({ ...base, width: 30, preset: 'beach', frame: 40, hour: 13, sun: { rise: 5.9, set: 17.5 }, seed: 12345, turns: [], live: null, mood: 'idle', jobs, agents: [], plan: null }, anchors)
  expect(anchors.length).toBeLessThanOrEqual(jobs.length)
  expect(new Set(anchors).size).toBe(anchors.length)
})

test('animated foreground and weather leave crew visible', { timeoutMs: 60_000 }, () => {
  const kinds = ['codex', 'agy', 'claude', 'opencode'] as const
  const jobs = kinds.map((kind, i) => ({ kind, tier: (i + 1) as 1 | 2 | 3 | 4, seed: seedOf(`j${i}`), isStale: false }))
  for (const preset of Object.keys(LANDSCAPES) as SceneInput['preset'][]) for (const weather of weathers) for (let frame = 0; frame < 120; frame += 15) {
    const input = { ...base, preset, weather, frame, turns: [], live: null, mood: 'idle' as const, jobs, agents: [], plan: null }
    const anchors: number[] = []
    const pixels = scenePixels(input, anchors)
    const background = scenePixels({ ...input, jobs: [] })
    expect(anchors).toHaveLength(jobs.length)
    for (const anchor of anchors) {
      const x = anchor % input.width, y = Math.floor(anchor / input.width)
      let visible = false
      for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) {
        const px = x + dx, py = y + dy
        if (px >= 0 && px < input.width && py >= 0 && py < SCENE_H && pixels[py * input.width + px] !== background[py * input.width + px]) visible = true
      }
      if (!visible) throw new Error(`${preset} frame ${frame} hid worker at ${anchor}`)
    }
  }
})

test('water scenes keep intermediate-width workers through rain and night', { timeoutMs: 60_000 }, () => {
  const kinds = ['codex', 'agy', 'claude', 'opencode'] as const
  for (const preset of ['beach', 'harbor'] as const) for (const width of [40, 60, 80, 120]) for (const count of [4, 6, 12]) for (const mixed of [false, true]) for (const weather of weathers) {
    const jobs = Array.from({ length: count }, (_, i) => ({ kind: mixed ? kinds[i % 4]! : 'codex' as const, tier: (i % 4 + 1) as 1 | 2 | 3 | 4, seed: seedOf(`j${i}`), isStale: false }))
    const anchors: number[] = []
    scenePixels({ ...base, preset, width, hour: weather ? 22 : 13, frame: 40, turns: base.turns.slice(0, 8), live: null, mood: 'idle', jobs, agents: [], weather, effect: null }, anchors)
    expect(anchors.length).toBeLessThanOrEqual(count)
    expect(new Set(anchors).size).toBe(anchors.length)
    expect(anchors.every(anchor => anchor >= 0 && anchor < width * SCENE_H)).toBe(true)
  }
})

// Omitted workers are covered by the bounded pager tests in wake.test.ts and
// crew-row.test.ts; the scene must preserve scenery instead of drawing a badge.

test('twelve mixed crew have visible positions in every landscape', () => {
  const kinds = ['codex', 'agy', 'claude', 'opencode'] as const
  const jobs = Array.from({ length: 12 }, (_, i) => ({ isStale: i === 3, seed: hash(i + 41), kind: kinds[i % 4]!, tier: (Math.floor(i / 4) + 2) as 2 | 3 | 4 }))
  for (const preset of Object.keys(LANDSCAPES) as SceneInput['preset'][]) for (const width of [24, 260]) {
    const input = { ...base, preset, width, hour: 13, frame: 40, jobs, agents: [], weather: null, effect: null }
    const anchors: number[] = []
    const pixels = scenePixels(input, anchors)
    const background = scenePixels({ ...input, jobs: [] })
    if (width === 260) expect(anchors).toHaveLength(12)
    else expect(anchors.length).toBeLessThanOrEqual(12)
    expect(new Set(anchors).size).toBe(anchors.length)
    for (const anchor of anchors) {
      const x = anchor % input.width, y = Math.floor(anchor / input.width)
      let visible = false
      for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) {
        const px = x + dx, py = y + dy
        if (px >= 0 && px < input.width && py >= 0 && py < SCENE_H && pixels[py * input.width + px] !== background[py * input.width + px]) visible = true
      }
      expect(visible).toBe(true)
    }
  }
})

test('a whole day played in half frames, as the band paints it, draws no black pixel (an undefined colour) in any landscape', { timeoutMs: 15_000 }, () => {
  for (const preset of Object.keys(LANDSCAPES) as SceneInput['preset'][]) {
    for (let t = 0; t < 120; t++) {
      const px = scenePixels({ ...base, preset, width: 186, frame: 5000 + t / 2, hour: (4 + (t / 120) * 24) % 24, weather: weathers[1]! })
      expect(px.indexOf(0)).toBe(-1)
    }
  }
})

test('scene pointer cells resolve only one painted identity and reject malformed input', () => {
  const target = { id: 'turn:7', title: 'Turn 7', details: ['read · edit'] }
  const map = { columns: 2, rows: 1, owners: [1, 0], targets: [target] }
  expect(sceneHitAt(map, 0, 0)).toEqual(target)
  expect(sceneHitAt(map, 1, 0)).toBeUndefined()
  expect(sceneHitAt({ ...map, owners: [2, 0] }, 0, 0)).toBeUndefined()
  expect(sceneHitAt({ ...map, owners: [1, 1] }, 2, 0)).toBeUndefined()
  expect(readScenePointer({ type: 'move', x: 1, y: 0 })).toEqual({ type: 'move', x: 1, y: 0 })
  expect(readScenePointer({ type: 'move', x: 1.5, y: 0 })).toBeUndefined()
  expect(readScenePointer({ type: 'click', x: 1, y: 0 })).toBeUndefined()
})

test('scene hit identity follows jobs through reorder and overflow', () => {
  const jobs = [
    { isStale: false, seed: 91, kind: 'codex' as const, tier: 2 as const, hit: { id: 'owner/alpha', title: 'Alpha', details: ['Model ID: gpt-6.1-terra'] } },
    { isStale: false, seed: 17, kind: 'agy' as const, tier: 3 as const, hit: { id: 'owner/beta', title: 'Beta', details: ['Model ID: gemini-pro'] } },
  ]
  const input: SceneInput = {
    ...base, width: 120, preset: 'city', hour: 13, frame: 40, turns: [
      { turn: 41, kinds: ['read', 'edit'] }, { turn: 42, kinds: ['test'] },
    ], live: { turn: 43, kinds: ['run'] }, mood: 'idle', jobs,
    agents: [{ id: 'agent-a', seed: 13, tier: 2, hit: { id: 'agent-a', title: 'Reviewer', details: ['Claude subagent · model unavailable'] } }],
    weather: null, effect: null,
  }
  const before = sceneFrame(input).hits
  const after = sceneFrame({ ...input, jobs: [...jobs].reverse() }).hits
  const locate = (map: typeof before, id: string) => {
    const at = map.owners.findIndex(owner => map.targets[owner - 1]?.id === id)
    return at < 0 ? undefined : { x: at % map.columns, y: Math.floor(at / map.columns) }
  }
  for (const id of ['owner/alpha', 'owner/beta', 'agent-a', 'turn:41', 'turn:42', 'turn:43']) {
    const point = locate(before, id)
    expect(point).toBeDefined()
    expect(sceneHitAt(before, point!.x, point!.y)?.id).toBe(id)
    expect(locate(after, id)).toEqual(point)
  }

  const crowded = Array.from({ length: 120 }, (_, i) => ({
    isStale: false, seed: hash(i + 41), kind: 'opencode' as const, tier: 1 as const,
    hit: { id: `owner/job${i}`, title: `Job ${i}`, details: ['OpenCode worker'] },
  }))
  const overflow = sceneFrame({ ...input, width: 24, turns: [], live: null, jobs: crowded, agents: [], effect: null }).hits
  expect(overflow.targets.some(target => target.id === 'crew-overflow')).toBe(false)
  const jobIds = new Set(crowded.map(job => job.hit.id))
  const visible = new Set(overflow.owners.filter(owner => owner > 0).map(owner => overflow.targets[owner - 1]!.id).filter(id => jobIds.has(id)))
  expect(visible.size).toBeLessThan(crowded.length)
  for (const owner of overflow.owners) if (owner > 0) expect(overflow.targets[owner - 1]).toBeDefined()
})
