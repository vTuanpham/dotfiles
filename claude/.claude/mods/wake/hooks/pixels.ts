// A small pixel canvas and colour helpers for the band's diorama. Pure.

export type Canvas = {
  W: number
  H: number
  px: Uint32Array
  hitOwners?: Uint32Array
  set(x: number, y: number, color: number): void
  get(x: number, y: number): number
  /** Moves the pixel toward `color` by `t` (0..1). */
  glow(x: number, y: number, color: number, t: number): void
  rect(x: number, y: number, w: number, h: number, color: number): void
  withHit<T>(owner: number, draw: () => T): T
}

export function canvas(W: number, H: number, collectHits = false): Canvas {
  const px = new Uint32Array(W * H)
  const hitOwners = collectHits ? new Uint32Array(W * H) : undefined
  let currentHit = 0
  // the scene plays half frames (20 a second, motion paced for 10), so a position can land
  // between pixels: it rounds to the nearest, which is what makes the half frame a smoother step
  const at = (x: number, y: number) => {
    const i = Math.round(x)
    const j = Math.round(y)
    return i >= 0 && i < W && j >= 0 && j < H ? j * W + i : -1
  }
  const c: Canvas = {
    W,
    H,
    px,
    hitOwners,
    set: (x, y, color) => {
      const k = at(x, y)
      if (k >= 0) {
        px[k] = color
        if (hitOwners) hitOwners[k] = currentHit
      }
    },
    get: (x, y) => {
      const k = at(x, y)
      return k >= 0 ? px[k]! : 0
    },
    glow: (x, y, color, t) => {
      const k = at(x, y)
      if (k >= 0) {
        px[k] = mix(px[k]!, color, t)
        if (hitOwners) hitOwners[k] = currentHit
      }
    },
    rect: (x, y, w, h, color) => {
      for (let j = y; j < y + h; j++) for (let i = x; i < x + w; i++) c.set(i, j, color)
    },
    withHit: (owner, draw) => {
      const previous = currentHit
      currentHit = owner
      try { return draw() } finally { currentHit = previous }
    },
  }
  return c
}

/** `a` moved toward `b` by `t`, colours as 0xRRGGBB. */
export function mix(a: number, b: number, t: number): number {
  const k = Math.max(0, Math.min(1, t))
  const one = (s: number) => Math.round(((a >> s) & 255) + (((b >> s) & 255) - ((a >> s) & 255)) * k) << s
  return one(16) | one(8) | one(0)
}

/** A well-mixed hash of an integer, non-negative and below 2^31, so `h >> n` and `h % n` never go negative. */
export function hash(n: number): number {
  let h = Math.imul((n | 0) ^ 0x9e3779b9, 0x85ebca6b)
  h = Math.imul(h ^ (h >>> 13), 0xc2b2ae35)
  return (h ^ (h >>> 16)) >>> 1
}

/** A stable seed from text (a place's key). */
export function seedOf(text: string): number {
  let h = 0x811c9dc5
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 0x01000193)
  return h >>> 0
}

/** Draws a sprite: rows of characters, `.` transparent, each other character a colour from `palette`. */
export function sprite(c: Canvas, x: number, y: number, rows: readonly string[], palette: Record<string, number>, flip = false) {
  rows.forEach((line, r) => {
    for (let i = 0; i < line.length; i++) {
      const ch = line[flip ? line.length - 1 - i : i]!
      const color = palette[ch]
      if (ch !== '.' && color !== undefined) c.set(x + i, y + r, color)
    }
  })
}
