// On start, give the Python service what was saved: the stars repo and color,
// brightness and power, weather, the chosen calendar, npm and night mode, then put the last
// screen back. Retry until it works: the Python service restarts with this server on every
// deploy, and after a power cut the network can take minutes to come back (the stars need GitHub).
async function sync() {
  const [stars, panel, weather, calendar, night, screen, npm] = await Promise.all([
    getSavedStars(),
    getSavedPanel(),
    getWeather(),
    getActiveCalendar(),
    getNight(),
    getScreen(),
    getNpm(),
  ])
  // only the sections that were saved, so unset ones keep the Python defaults
  const config: Record<string, unknown> = Object.fromEntries(
    Object.entries({ weather, calendar: calendar && { url: calendar.url }, night, npm: npm.package && { package: npm.package, period: npm.period } }).filter(
      ([, v]) => v,
    ),
  )
  // the busy light always gets its calendars and settings (defaults when never saved)
  config.busy = await busyConfig()
  for (let attempt = 1; ; attempt++) {
    try {
      if (stars) await pushStars(stars)
      if (panel) await pushPanel(panel)
      // after power, so night mode decides last whether the screen should be dark
      if (Object.keys(config).length) await pushConfig(config)
      // the Python service draws nothing until told, so show stars when nothing was saved yet
      await (screen ? restoreScreen(screen) : $fetch(`${useRuntimeConfig().ledApi}/stars`, { method: 'POST', body: {} }))
      return console.log(`synced saved settings, showing ${screen?.feature ?? 'stars'}`)
    } catch (e: unknown) {
      if (attempt === 1 || attempt % 20 === 0) console.error(`could not sync saved settings yet (try ${attempt}): ${(e as Error).message}`)
      // every 2 s at first, then every 30 s
      await new Promise((r) => setTimeout(r, Math.min(30_000, 2000 * attempt)))
    }
  }
}

export default defineNitroPlugin(() => {
  // in the background, so a slow Python start never holds up the page
  void sync()
})
