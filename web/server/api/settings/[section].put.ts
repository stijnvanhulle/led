import { FEATURES, NPM_PATTERN, NPM_PERIODS } from '../../utils/settings'

// Saves one settings section and, for the ones the panel uses, hands it to the Python service.
export default defineEventHandler(async (event) => {
  const section = getRouterParam(event, 'section')
  const body = await readBody<Record<string, unknown>>(event)
  const bad = (error: string) => createError({ statusCode: 400, data: { error } })

  if (section === 'weather') {
    const { name, lat, lon } = body
    const weather =
      lat === null || lat === undefined ? { name: null, lat: null, lon: null } : { name: String(name ?? '').slice(0, 80), lat: Number(lat), lon: Number(lon) }
    if (weather.lat !== null && !(Math.abs(weather.lat) <= 90 && Math.abs(weather.lon as number) <= 180)) throw bad('lat/lon out of range')
    await pushConfig({ weather })
    await useStorage('settings').setItem('weather', weather)
    return weather
  }
  if (section === 'calendars') {
    // {add: {name, url, type}}, {remove: id}, {select: id} or {type: {id, type}}. Links never go back to the page
    let list = await getCalendars()
    let activeId = (await getActiveCalendar())?.id ?? null
    if (body.add && typeof body.add === 'object') {
      const { name, url, type } = body.add as { name?: unknown; url?: unknown; type?: unknown }
      const link = typeof url === 'string' ? url.trim() : ''
      if (!/^(https?|webcal):\/\//.test(link)) throw bad('calendar link must start with https:// or webcal://')
      const id = `cal-${Date.now().toString(36)}`
      list.push({
        id,
        name:
          String(name ?? '')
            .trim()
            .slice(0, 40) || `Calendar ${list.length + 1}`,
        url: link,
        type: type === 'personal' ? 'personal' : 'work',
      })
      activeId = id
    } else if (typeof body.remove === 'string') {
      list = list.filter((c) => c.id !== body.remove)
    } else if (body.type && typeof body.type === 'object') {
      const { id, type } = body.type as { id?: unknown; type?: unknown }
      const entry = list.find((c) => c.id === id)
      if (!entry || (type !== 'work' && type !== 'personal')) throw bad('send a calendar id and work or personal')
      entry.type = type
    } else if (typeof body.select === 'string') {
      if (!list.some((c) => c.id === body.select)) throw bad('unknown calendar')
      activeId = body.select
    } else throw bad('send add, remove, type or select')
    const active = await saveCalendars(list, activeId)
    return { calendars: list.map((c) => ({ id: c.id, name: c.name, host: calendarHost(c.url), type: calendarType(c) })), active: active?.id ?? null }
  }
  if (section === 'busy') {
    const current = await getBusy()
    const busy = {
      auto: body.auto === undefined ? current.auto : Boolean(body.auto),
      soon: body.soon === undefined ? current.soon : Math.max(1, Math.min(30, Math.round(Number(body.soon)) || 15)),
      force: body.force === undefined ? current.force : Boolean(body.force),
    }
    await useStorage('settings').setItem('busy', busy)
    await pushConfig({ busy: await busyConfig() })
    return busy
  }
  if (section === 'npm') {
    // {add: name}, {remove: name}, {select: name} or {period}
    const npm = await getNpm()
    if (typeof body.add === 'string') {
      const name = body.add.trim().toLowerCase()
      if (!NPM_PATTERN.test(name)) throw bad('package must look like name or @scope/name')
      // a typo would only show "--" on the panel, so check npm knows it
      await $fetch(`https://api.npmjs.org/downloads/point/last-day/${name}`).catch(() => {
        throw bad(`npm has no package called ${name}`)
      })
      if (!npm.packages.includes(name)) npm.packages.push(name)
      npm.package = name
    } else if (typeof body.remove === 'string') {
      npm.packages = npm.packages.filter((p) => p !== body.remove)
      if (npm.package === body.remove) npm.package = npm.packages[0] ?? null
    } else if (typeof body.select === 'string') {
      if (!npm.packages.includes(body.select)) throw bad('unknown package')
      npm.package = body.select
    } else if (NPM_PERIODS.includes(body.period as NpmSettings['period'])) {
      npm.period = body.period as NpmSettings['period']
    } else throw bad(`send add, remove, select or a period: ${NPM_PERIODS.join(', ')}`)
    await pushConfig({ npm: { package: npm.package, period: npm.period } })
    await useStorage('settings').setItem('npm', npm)
    return npm
  }
  if (section === 'night') {
    const night = { enabled: Boolean(body.enabled), off: String(body.off ?? '23:00'), on: String(body.on ?? '07:00') }
    if (!HM_PATTERN.test(night.off) || !HM_PATTERN.test(night.on) || night.off === night.on) throw bad('times must be HH:MM and differ')
    await pushConfig({ night })
    await useStorage('settings').setItem('night', night)
    return night
  }
  if (section === 'presets') {
    if (!Array.isArray(body.items)) throw bad('items must be a list')
    const items = [...new Set(body.items.map((p) => String(p).trim().slice(0, 60)).filter(Boolean))].slice(0, 20)
    await useStorage('settings').setItem('presets', items)
    return { items }
  }
  if (section === 'screen') {
    // the control page saves what it last sent, so a restart puts it back
    const s = body as Partial<ScreenSettings>
    if (!FEATURES.includes(s.feature as ScreenSettings['feature'])) throw bad('unknown screen')
    const color = (c: unknown, fallback: string) => (typeof c === 'string' && /^#[0-9a-fA-F]{6}$/.test(c) ? c : fallback)
    const screen: ScreenSettings = {
      feature: s.feature as ScreenSettings['feature'],
      text: String(s.text ?? '').slice(0, 200),
      color: color(s.color, '#ffffff'),
      animation: Number(s.animation) || 0,
      speed: Math.min(100, Math.max(0, Number(s.speed) || 80)),
      starsColor: color(s.starsColor, '#ffd700'),
      clockColor: color(s.clockColor, '#6fb6ff'),
      h24: s.h24 !== false,
      blink: s.blink !== false,
      weatherColor: color(s.weatherColor, '#ffffff'),
      calendarColor: color(s.calendarColor, '#f0b049'),
      npmColor: color(s.npmColor, '#cb3837'),
    }
    await useStorage('settings').setItem('screen', screen)
    return screen
  }
  throw createError({ statusCode: 404, data: { error: 'unknown settings section' } })
})
