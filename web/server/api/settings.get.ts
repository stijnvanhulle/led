// Everything the settings and control pages show. Calendar links are private, so only their hosts are returned.
export default defineEventHandler(async () => {
  const [stars, weather, calendars, active, night, presets, screen, busy, npm] = await Promise.all([
    getSavedStars(),
    getWeather(),
    getCalendars(),
    getActiveCalendar(),
    getNight(),
    getPresets(),
    getScreen(),
    getBusy(),
    getNpm(),
  ])
  return {
    repo: stars?.repo ?? null,
    weather: weather ?? { name: null, lat: null, lon: null },
    calendars: calendars.map((c) => ({ id: c.id, name: c.name, host: calendarHost(c.url), type: calendarType(c) })),
    activeCalendar: active?.id ?? null,
    night: night ?? { enabled: false, off: '23:00', on: '07:00' },
    presets,
    screen,
    busy,
    npm,
  }
})
