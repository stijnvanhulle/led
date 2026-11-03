// Brightness and screen power: set on the panel and saved, so they come back after
// a restart and the preview keeps matching the panel.
export default defineEventHandler(async (event) => {
  const body = await readBody<{ brightness?: unknown; power?: unknown }>(event)
  const saved = (await getSavedPanel()) ?? {}
  if (body.brightness !== undefined) {
    const level = Number(body.brightness)
    // below 50 the panel looks no dimmer, so the page never sends less
    if (!Number.isInteger(level) || level < 50 || level > 100) throw createError({ statusCode: 400, data: { error: 'brightness must be 50–100' } })
    await pushPanel({ brightness: level })
    saved.brightness = level
  }
  if (body.power !== undefined) {
    await pushPanel({ power: Boolean(body.power) })
    saved.power = Boolean(body.power)
  }
  await useStorage('settings').setItem('panel', saved)
  return saved
})
