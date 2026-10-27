import { type Canvas, hash, mix } from '../pixels'
import { type Job, jobAccent, type Look, P } from './kit'

// The crew's look: one family per harness, four classes that grow in size and detail.
//   codex     mechanical  drone -> big drone -> airship (a skiff -> tug -> steamship on the water)
//   agy       celestial   spark -> comet -> constellation
//   claude    living      sparrow -> gull -> eagle (also the subagents' birds)
//   opencode  festival    hot-air balloons, free to drift: hopper -> striped balloon -> big balloon with a bunting band
// Sprite keys: a body, W highlight, l light stripe, d shade or rope, s lamp, beak or flame, p bunting, k smoke, h hull or basket,
// m / M the maker's mark (a body / highlight pixel that takes the maker's colour when another family made the model).
// Where each one flies comes from who it is (its seed), never from its place in the list: see stations.

type Kind = NonNullable<Job['kind']>
type Frames = readonly (readonly string[])[]

const AIR: Record<Kind, Record<1 | 2 | 3 | 4, Frames>> = {
  codex: {
    1: [['a...a', '.aWa.'], ['.a.a.', '.aWa.']],
    2: [['aa...aa', '.aaaaa.', '..aWa..', '..s.s..'], ['.a...a.', '.aaaaa.', '..aWa..', '..s.s..']],
    3: [
      ['d..aaaaaaa...', '.aaaaaaaaaaa.', 'aaWaWaWaWaWaa', '.aaaaaaaaaaa.', '...aaaaaaa...', '.....dsd.....'],
      ['d..aaaaaaa...', '.aaaaaaaaaaa.', 'aWaWaWaWaWaWa', '.aaaaaaaaaaa.', '...aaaaaaa...', '.....dWd.....'],
    ],
    4: [['d...aaaaaaaaa....', '..aaaaaaaaaaaaa..', 'aaWaWaWaWaWaWaWaa', '..aaaaaaaaaaaaa..', '....aaaaaaaaa....', '.......dsd.......']],
  },
  agy: {
    1: [['.W.', 'WmW', '.W.'], ['W.W', '.m.', 'W.W']],
    2: [['.......mm.', 'd.dd.ddmWm', '.......mm.'], ['.......mm.', '.d.dd.dmWm', '.......mm.']],
    3: [
      ['.........M...', '...W....d.d..', '....d..d...d.', '.....dW.....W'],
      ['.........m...', '...a....d.d..', '....d..d...d.', '.....dW.....a'],
    ],
    4: [['..W.......M......', '...d....d.d..W...', '....d..d...dd....', '.....dW.....W....', '....d........d...']],
  },
  claude: {
    1: [['a.a', '.a.'], ['.a.', 'a.a']],
    2: [['a.....a', '.aa.aa.', '...d...'], ['...a...', 'aaadaaa', '.a...a.']],
    3: [
      ['aaa.......aaa', '.aaaaa.aaaaa.', '...aaaaaaWWs.', '.dd..aaa.....'],
      ['.............', '.aaa.....aaa.', 'aaaaaaaaaWWs.', '.dd..aaa.....'],
    ],
    4: [['aaaa.........aaaa', '.aaaaaa.aaaaaa...', '...aaaaaaaaaWWs..', '..dd...aaaa......'], ['.................', '.aaaa.......aaaa.', 'aaaaaaaaaaaaWWs..', '..dd...aaaa......']],
  },
  opencode: {
    1: [['ala', 'ala', '.a.', '.s.', '.h.'], ['ala', 'ala', '.a.', '.W.', '.h.']],
    2: [['.lal.', 'alala', 'alala', '.lal.', '..a..', '.dsd.', '.hhh.'], ['.lal.', 'alala', 'alala', '.lal.', '..a..', '.dWd.', '.hhh.']],
    3: [
      ['..alala..', '.lalalal.', 'alalalala', 'ppppppppp', '.lalalal.', '..alala..', '...lal...', '...dsd...', '...hhh...'],
      ['..alala..', '.lalalal.', 'alalalala', 'ppppppppp', '.lalalal.', '..alala..', '...lal...', '...dWd...', '...hhh...'],
    ],
    4: [['...alalala...', '.alalalalala.', 'alalalalalala', 'ppppppppppppp', 'alalalalalala', '.alalalalala.', '...alalala...', '....dsdsd....', '....hhhhh....']],
  },
}

const BOATS: Record<1 | 2 | 3 | 4, readonly string[]> = {
  1: ['.......', '...s...', '..aaa..', '.aWaaa.', 'hhhhhhh', '.hhhhh.'],
  2: ['.....k....', '.....k.s..', '..aaaaaa..', '..aWaWaa..', 'hhhhhhhhhh', '.hhhhhhhh.'],
  3: ['...k..k....s..', '...k..k.....a..', '.aaaaaaaaaaaa.', '.aWaWaWaWaWaa.', 'hhhhhhhhhhhhhh', '.hhhhhhhhhhhh.'],
  4: ['...k..k.....s....', '...k..k......a...', '.aaaaaaaaaaaaaaa.', '.aWaWaWaWaWaWaaa.', 'hhhhhhhhhhhhhhhhh', '.hhhhhhhhhhhhhhh.'],
}

/** OpenCode's festival: a handful of existing inks no other family owns (Codex teal, agy mauve, Claude pink, stale
 *  peach all stay out), each bright enough to read on a day or night sky. A balloon keeps the colours it drew here. */
const BALLOON_INKS = [P.green, P.yellow, P.red, P.blue, P.lavender] as const

/** A balloon's envelope colour from its stable identity: one of the palette, never another family's accent. */
export const balloonInk = (seed: number) => BALLOON_INKS[hash(seed ^ 0x5bf03635) % BALLOON_INKS.length]!

/** The family's palette; a stale job goes amber, and its body dims on the off beat so the silhouette stays. */
function paint(job: Job, look: Look) {
  const base = job.isStale ? P.peach : job.kind === 'opencode' ? balloonInk(job.seed) : jobAccent(job, P.teal)
  const off = job.isStale && look.frame % 10 >= 6
  const mark = job.maker && job.maker !== job.kind && !job.isStale ? jobAccent({ ...job, kind: job.maker }, P.teal) : undefined
  const a = off ? mix(base, P.ink, 0.5) : base
  const W = job.isStale ? P.yellow : mix(base, P.white, 0.7)
  return {
    a,
    W,
    m: mark ?? a,
    M: mark === undefined ? W : mix(mark, P.white, 0.45),
    l: mix(base, P.white, 0.5),
    d: mix(base, P.ink, 0.45),
    s: P.yellow,
    p: job.isStale ? P.woodDark : P.yellow,
    k: P.surface2,
    h: job.isStale ? mix(P.peach, P.woodDark, 0.5) : P.wood,
  } as Record<string, number>
}

function draw(c: Canvas, look: Look, x0: number, y0: number, art: readonly string[], pal: Record<string, number>, glow: boolean) {
  art.forEach((row, r) => {
    for (let i = 0; i < row.length; i++) {
      const ch = row[i]!
      if (ch === '.') continue
      c.set(x0 + i, y0 + r, pal[ch]!)
      if (glow && (ch === 'W' || ch === 'M' || ch === 's')) for (const [dx, dy] of [[-1, 0], [1, 0], [0, -1], [0, 1]] as const) c.glow(x0 + i + dx, y0 + r + dy, pal.a!, 0.25 * (0.4 + look.night))
    }
  })
}

/** A flyer centred on (cx, cy): its family and class decide the sprite and which frame this beat shows. */
export function fly(c: Canvas, look: Look, cx: number, cy: number, job: Job, kind: Kind = job.kind ?? 'codex') {
  const frames = AIR[kind][job.tier ?? 1]
  const art = frames[(Math.floor(look.frame / (kind === 'claude' ? 3 : kind === 'opencode' ? 5 : 4)) + job.seed) % frames.length]!
  draw(c, look, cx - (art[0]!.length >> 1), cy - (art.length >> 1), art, paint({ ...job, kind }, look), true)
}

/** Who comes first when two want the same place: the lower seed, then kind and class, so a tie never falls to list order. */
const byIdentity = (a: Job, b: Job) => a.seed - b.seed || (a.kind ?? '').localeCompare(b.kind ?? '') || (a.tier ?? 1) - (b.tier ?? 1)

/**
 * Each crew member's slot of `count`, in identity order (also the draw order, so overlaps don't hang on the list's order):
 * its own hashed pick, or the next free one when a lower seed holds that. So adding, removing or reordering the others
 * moves only one that collides with them. Past `count` slots stack: slot `count + n` is slot n again, half a slot over.
 */
export function stations<T extends Job>(crew: readonly T[], count: number): [T, number][] {
  const taken = new Set<number>()
  return [...crew].sort(byIdentity).map(job => {
    const want = hash(job.seed) % count
    let slot = want
    for (let k = 1; taken.has(slot); k++) slot = Math.floor(k / count) * count + ((want + k) % count)
    taken.add(slot)
    return [job, slot]
  })
}

/** Slots of sky across `right` columns: each flyer keeps a stretch wide enough for an airship and its sway. */
export const airSlots = (right: number) => Math.max(1, Math.floor((right - 16) / 22))

/** Where a hovering job sits in the sky, in its slot of `count`: small ones flit about the lower sky, big ones glide high and slow. */
export function hover(c: Canvas, look: Look, job: Job, slot: number, count: number, right: number): [number, number] {
  const t = look.frame + job.seed * 97
  const tier = job.tier ?? 1
  const width = Math.max(8, right - 16) / count
  const speed = [0, 0.07, 0.045, 0.025, 0.02][tier]!
  const at = (slot % count) + 0.5 + (Math.floor(slot / count) % 2) * 0.5 // a stacked slot sits half a slot over
  const x = Math.round(8 + at * width + Math.min(width * 0.3, tier >= 3 ? 6 : 4) * Math.sin(t * speed + job.seed))
  const y = [0, 7, 6, 4, 4][tier]! + (slot % 2) * (tier >= 3 ? 0 : 1) + Math.round([0, 1.5, 1, 0.5, 0.5][tier]! * Math.sin(t * 0.09 + job.seed * 2))
  return [x, y]
}

/** Every landscape that keeps its crew in the air. */
export function airJobs(c: Canvas, look: Look, jobs: Job[], right: number) {
  const count = airSlots(right)
  for (const [job, slot] of stations(jobs, count)) {
    const [x, y] = hover(c, look, job, slot, count, right)
    fly(c, look, x, y, job)
  }
}

/** A Codex boat of its class standing on `y` (its top row) at `x`; returns its width for reflections and slots. */
export function boat(c: Canvas, look: Look, x: number, y: number, job: Job): number {
  const art = BOATS[job.tier ?? 1]
  const pal = paint(job, look)
  draw(c, look, x, y, art, pal, false)
  const lamp = art[0]!.indexOf('s') >= 0 ? [art[0]!.indexOf('s'), 0] : [art[1]!.indexOf('s'), 1]
  if (look.night > 0.2) c.glow(x + lamp[0]!, y + lamp[1]!, job.isStale ? P.peach : P.yellow, 0.8)
  if ((job.tier ?? 1) > 1 && !job.isStale && look.frame % 8 < 5) c.glow(x + art[0]!.indexOf('k') + (look.frame % 2), y - 1, P.white, 0.35) // funnel smoke
  return art[0]!.length
}

