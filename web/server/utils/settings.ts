// Settings from the settings page, brightness and power, and the last screen, saved on
// the Pi. The ones the panel uses are also handed to the Python service, which keeps
// them only in memory.

export interface PanelSettings {
  brightness?: number
  power?: boolean
}
export interface WeatherSettings {
  name: string | null
  lat: number | null
  lon: number | null
}
export interface CalendarEntry {
  id: string
  name: string
  url: string
  // work calendars drive the busy light, and personal ones only show on the calendar tab
  type?: 'work' | 'personal'
}
export interface BusySettings {
  auto: boolean
  soon: number
  force: boolean
}
export const DEFAULT_BUSY: BusySettings = { auto: true, soon: 15, force: false }
export interface NightSettings {
  enabled: boolean
  off: string
  on: string
}
// npm's download count periods; the package names it allows
export const NPM_PERIODS = ['last-day', 'last-week', 'last-month', 'last-year'] as const
export const NPM_PATTERN = /^(@[a-z0-9][a-z0-9._~-]*\/)?[a-z0-9][a-z0-9._~-]*$/
// the packages to pick from, and the one and period on screen
export interface NpmSettings {
  packages: Array<string>
  package: string | null
  period: (typeof NPM_PERIODS)[number]
}
export const DEFAULT_NPM: NpmSettings = { packages: [], package: null, period: 'last-week' }
export const FEATURES = ['text', 'stars', 'npm', 'clock', 'weather', 'calendar', 'busy'] as const
// what the control page last put on the panel, with every screen's settings
export interface ScreenSettings {
  feature: (typeof FEATURES)[number]
  text: string
  color: string
  animation: number
  speed: number
  starsColor: string
  clockColor: string
  h24: boolean
  blink: boolean
  weatherColor: string
  calendarColor: string
  npmColor: string
}

// one emoji fills the 16px panel height, so these read at a glance on the desk
export const DEFAULT_PRESETS = ['📅', '📞', '🎧', '🍕', '☕', '🚀', '👀', '🐛', '🎉', '🏖']
export const HM_PATTERN = /^([01]\d|2[0-3]):[0-5]\d$/

const store = () => useStorage('settings')
export const getSavedPanel = () => store().getItem<PanelSettings>('panel')
export const getWeather = () => store().getItem<WeatherSettings>('weather')
export const getNight = () => store().getItem<NightSettings>('night')
export const getPresets = async () => (await store().getItem<Array<string>>('presets')) ?? DEFAULT_PRESETS
export const getScreen = () => store().getItem<ScreenSettings>('screen')
export const getBusy = async () => ({ ...DEFAULT_BUSY, ...(await store().getItem<BusySettings>('busy')) })
export const getNpm = async () => ({ ...DEFAULT_NPM, ...(await store().getItem<NpmSettings>('npm')) })
// a calendar saved before types existed: work when its name says so
export const calendarType = (c: CalendarEntry) => c.type ?? (/work/i.test(c.name) ? 'work' : 'personal')

const workUrls = (list: Array<CalendarEntry>) => list.filter((c) => calendarType(c) === 'work').map((c) => c.url)

// what the Python service needs for the busy light: the work calendars' links and the settings
export async function busyConfig() {
  const [list, busy] = await Promise.all([getCalendars(), getBusy()])
  return { ...busy, urls: workUrls(list) }
}

export const getCalendars = async () => (await store().getItem<Array<CalendarEntry>>('calendars')) ?? []
export async function getActiveCalendar() {
  const [list, id] = await Promise.all([getCalendars(), store().getItem<string>('calendar-active')])
  return list.find((c) => c.id === id) ?? list[0] ?? null
}
// saves the list and choice, and gives the Python service the chosen link
export async function saveCalendars(list: Array<CalendarEntry>, activeId: string | null) {
  const active = list.find((c) => c.id === activeId) ?? list[0] ?? null
  await pushConfig({ calendar: { url: active?.url ?? null }, busy: { ...(await getBusy()), urls: workUrls(list) } })
  await store().setItem('calendars', list)
  await store().setItem('calendar-active', active?.id ?? null)
  return active
}

export function pushConfig(config: {
  weather?: WeatherSettings
  calendar?: { url: string | null }
  night?: NightSettings
  busy?: BusySettings & { urls: Array<string> }
  npm?: { package: string | null; period: string }
}) {
  return $fetch(`${useRuntimeConfig().ledApi}/config`, { method: 'POST', body: config })
}

export async function pushPanel({ brightness, power }: PanelSettings) {
  const api = useRuntimeConfig().ledApi
  if (brightness !== undefined) await $fetch(`${api}/command/set_brightness`, { method: 'POST', body: { level: brightness } })
  if (power !== undefined) await $fetch(`${api}/command/set_power`, { method: 'POST', body: { on: power } })
}

// puts a saved screen back on the panel, the way the control page would send it
export function restoreScreen(s: ScreenSettings) {
  const api = useRuntimeConfig().ledApi
  const post = (path: string, body: object) => $fetch(`${api}/${path}`, { method: 'POST', body })
  const hex = (c: string) => c.replace('#', '')
  if (s.feature === 'text') return post('command/send_text', { text: s.text || ' ', color: hex(s.color), animation: s.animation, speed: s.speed })
  if (s.feature === 'clock') return post('clock', { color: hex(s.clockColor), h24: s.h24, blink: s.blink })
  if (s.feature === 'weather') return post('weather', { color: hex(s.weatherColor) })
  if (s.feature === 'calendar') return post('calendar', { color: hex(s.calendarColor) })
  if (s.feature === 'busy') return post('busy', {})
  if (s.feature === 'npm') return post('npm', { color: hex(s.npmColor) })
  return post('stars', { color: hex(s.starsColor) })
}

export function calendarHost(url: string) {
  try {
    return new URL(url.replace(/^webcal:/, 'https:')).host
  } catch {
    return null
  }
}
