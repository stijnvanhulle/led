// Frames for the 64×16 panel preview. The pixels come from the Pi (/api/preview),
// which renders with the panel's own font and emoji, so the preview matches it.
export const W = 64
export const H = 16
// below 50 the panel looks no dimmer (checked on the real panel), so 50 is the floor
export const MIN_BRIGHTNESS = 50

export type Feature = 'text' | 'stars' | 'npm' | 'clock' | 'weather' | 'calendar' | 'busy'
export type BusyState = 'free' | 'soon' | 'busy'
export type Pixels = Array<Array<string | null>>

// "1" = lit in the chosen text color, "rrggbb" = a fixed color (emoji, stars frame), "" = off
export interface Grid {
  w: number
  rows: Array<Array<string>>
  // the calendar's second page, the event title, timed as in server.py's two_pages
  title?: { rows: Array<Array<string>>; hold: number; still: number; pause: number; ms: number }
}

export interface PanelState {
  feature: Feature
  text: string
  color: string
  animation: number
  speed: number
  stars: number | null
  clockColor: string
  h24: boolean
  blink: boolean
  starsColor: string
  weatherColor: string
  calendarColor: string
  npmColor: string
  brightness: number
  power: boolean
  busyState: BusyState
}

// API mode name per feature, as /health reports it
export const modeOf: Record<Feature, string> = {
  text: 'send_text',
  stars: 'stars',
  npm: 'npm',
  clock: 'clock',
  weather: 'weather',
  calendar: 'calendar',
  busy: 'busy',
}

const cache = new Map<string, Grid>()
const pending = new Set<string>()

// Returns the grid if loaded, otherwise starts loading it and returns the last one.
let lastGrid: Grid | undefined
function load(key: string, url: string): Grid | undefined {
  const hit = cache.get(key)
  if (hit) return (lastGrid = hit)
  if (!pending.has(key)) {
    pending.add(key)
    $fetch<Grid>(url)
      .then((g) => {
        if (cache.size > 300) cache.clear()
        cache.set(key, g)
      })
      .catch(() => {})
      .finally(() => pending.delete(key))
  }
  return lastGrid
}

const textGrid = (text: string) => load(`t:${text}`, `/api/preview?text=${encodeURIComponent(text)}`)
export const forgetStars = () => [...cache.keys()].filter((k) => k.startsWith('s:')).forEach((k) => cache.delete(k))
// after a settings change (new location, calendar or package), so the preview refetches now
export const forgetScreens = () => [...cache.keys()].filter((k) => /^(weather|calendar|npm):/.test(k)).forEach((k) => cache.delete(k))

// Real pixel width of a text as the panel draws it (emoji are 16px, most glyphs 8px).
export async function measure(text: string) {
  const key = `t:${text}`
  if (!cache.has(key)) cache.set(key, await $fetch<Grid>(`/api/preview?text=${encodeURIComponent(text)}`))
  return cache.get(key)!.w
}

function dim(hex: string, k: number) {
  const n = Number.parseInt(hex.slice(1), 16)
  const f = 0.15 + 0.85 * k
  return `rgb(${(((n >> 16) & 255) * f) | 0},${(((n >> 8) & 255) * f) | 0},${((n & 255) * f) | 0})`
}

export function frame(s: PanelState, t: number, still = false): Pixels {
  const px: Pixels = Array.from({ length: H }, () => Array<string | null>(W).fill(null))
  const stamp = (g: Grid | undefined, x0: number, color: string) =>
    g?.rows.forEach((r, y) =>
      r.forEach((c, x) => {
        const xx = x0 + x
        if (c && xx >= 0 && xx < W && y < H) px[y]![xx] = c === '1' ? color : `#${c}`
      }),
    )
  const center = (w: number) => Math.floor((W - w) / 2)

  if (s.feature === 'text') {
    const g = textGrid(s.text || ' ')
    if (!g) return px
    const pages = Math.ceil(g.w / W)
    const a = still ? 0 : s.animation
    if (a === 0) {
      const page = pages > 1 && !still ? Math.floor(t / 1500) % pages : 0
      stamp(g, pages > 1 ? -page * W : center(g.w), s.color)
    } else if (a === 1 || a === 2) {
      const p = Math.floor(t / ((110 - s.speed) * 0.9)) % (g.w + W)
      stamp(g, a === 1 ? W - p : p - g.w, s.color)
    } else {
      if (a === 5 && Math.floor(t / 400) % 2) return px
      stamp(g, pages > 1 ? 0 : center(g.w), a === 6 ? dim(s.color, (Math.sin(t / 500) + 1) / 2) : s.color)
      if (a === 7) for (let i = 0; i < 9; i++) px[Math.floor(t / 120 + i * 7) % H]![(i * 23 + 5) % W] = '#ffffff'
    }
  } else if (s.feature === 'stars') {
    stamp(load(`s:${s.stars}`, '/api/preview/stars'), 0, s.starsColor)
  } else if (s.feature === 'busy') {
    return glowFrame(s.busyState, still ? 0 : t)
  } else if (s.feature === 'weather' || s.feature === 'calendar' || s.feature === 'npm') {
    // drawn by the Pi from live data, so fetched again each minute
    const minute = Math.floor(Date.now() / 60_000)
    const color = { weather: s.weatherColor, calendar: s.calendarColor, npm: s.npmColor }[s.feature]
    const g = load(`${s.feature}:${minute}`, `/api/preview/${s.feature}`)
    const title = g?.title
    if (!title || still) {
      stamp(g, 0, color)
      return px
    }
    // the loop the panel plays: the countdown, then the title, still and centered when it
    // fits, else left-aligned with a pause, a slow scroll until its end shows, and a pause
    const tw = title.rows[0]?.length ?? 0
    const overflow = tw - W
    const cycle = title.hold + (overflow <= 0 ? title.still : 2 * title.pause + (overflow - 1) * title.ms)
    const p = t % cycle
    const q = p - title.hold
    if (q < 0) stamp(g, 0, color)
    else if (overflow <= 0) stamp({ w: tw, rows: title.rows }, Math.floor((W - tw) / 2), color)
    else {
      const scrolled = q < title.pause ? 0 : Math.min(overflow, 1 + Math.floor((q - title.pause) / title.ms))
      stamp({ w: tw, rows: title.rows }, -scrolled, color)
    }
  } else {
    const d = new Date()
    const h = s.h24 ? d.getHours() : d.getHours() % 12 || 12
    // same text as the Pi's clock frame: a space when the colon blinks off (500ms)
    const colon = still || !s.blink || Math.floor(t / 500) % 2 === 0 ? ':' : ' '
    const g = textGrid(`${String(h).padStart(2, '0')}${colon}${String(d.getMinutes()).padStart(2, '0')}`)
    if (g) stamp(g, center(g.w), s.clockColor)
  }
  return px
}

// The loading snake: the panel's power-on animation (boot_screen.py) and the
// preview while the page connects. Keep both in step: 40 frames of 45 ms.
export const SNAKE_FRAMES = 40
export const SNAKE_MS = 45
const SNAKE_TRACK = [
  ...Array.from({ length: 18 }, (_, i) => [23 + i, 3]),
  ...Array.from({ length: 8 }, (_, i) => [41, 4 + i]),
  ...Array.from({ length: 18 }, (_, i) => [40 - i, 12]),
  ...Array.from({ length: 8 }, (_, i) => [22, 11 - i]),
] as Array<[number, number]>

export function snakeFrame(i: number, tint = [228, 228, 231]): Pixels {
  const px: Pixels = Array.from({ length: H }, () => Array<string | null>(W).fill(null))
  const n = SNAKE_TRACK.length
  const head = Math.round((i / SNAKE_FRAMES) * n) % n
  const shade = (v: number) => `rgb(${tint.map((c) => Math.round(c * v)).join(',')})`
  for (const [x, y] of SNAKE_TRACK) px[y]![x] = shade(0.07)
  for (let k = 0; k < 10; k++) {
    const [x, y] = SNAKE_TRACK[(head - k + n) % n]!
    px[y]![x] = shade(1 - k / 11)
  }
  return px
}

// The busy light: the whole panel glows green (free), orange (a work meeting soon) or red
// (in one), breathing on a sine, one step every 333 ms (the panel's smooth limit), even as
// seen. Same formula as server.py's glow_seen. The Pi sends the panel these values
// gamma-corrected, since LEDs dim linearly and a screen doesn't, so both look alike.
const GLOW: Record<BusyState, [number, number, number, number, number]> = {
  free: [0x00, 0xff, 0x30, 10, 0.8],
  soon: [0xff, 0x7a, 0x00, 6, 0.6],
  busy: [0xff, 0x00, 0x00, 8, 0.6],
}
const GLOW_MS = 333
export function glowFrame(state: BusyState, t: number): Pixels {
  const [r, g, b, steps, low] = GLOW[state]
  const step = Math.floor(t / GLOW_MS) % steps
  const v = low + (1 - low) * (0.5 + 0.5 * Math.cos((step / steps) * Math.PI * 2))
  return Array.from({ length: H }, (_, y) =>
    Array.from({ length: W }, (_, x) => {
      // a soft glow from the middle, down to 35% at the edges, as seen, in the Pi's 64 shades.
      // The Pi gamma-corrects it for the LEDs
      const k = (v * Math.round(Math.max(0.3, 1 - Math.hypot((x - 31.5) / 32, (y - 7.5) / 8) * 0.65) * 64)) / 64
      return `rgb(${Math.round(r * k)},${Math.round(g * k)},${Math.round(b * k)})`
    }),
  )
}
