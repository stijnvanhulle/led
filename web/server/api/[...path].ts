// /api/<path> → the Python service, which talks to the panel over Bluetooth
export default defineEventHandler((event) => {
  const path = getRouterParam(event, 'path') ?? ''
  // the router param has no query string, so carry it over (e.g. /preview?text=…)
  return proxyRequest(event, `${useRuntimeConfig(event).ledApi}/${path}${getRequestURL(event).search}`)
})
