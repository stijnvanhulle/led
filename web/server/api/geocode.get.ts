// Place search for the weather location (Open-Meteo, free, no key).
interface Place {
  name: string
  country?: string
  admin1?: string
  latitude: number
  longitude: number
}

export default defineEventHandler(async (event) => {
  const q = String(getQuery(event).q ?? '').trim()
  if (q.length < 2) return []
  const res = await $fetch<{ results?: Array<Place> }>('https://geocoding-api.open-meteo.com/v1/search', { query: { name: q, count: 6, language: 'en' } })
  return (res.results ?? []).map((p) => ({
    name: [p.name, p.admin1, p.country].filter(Boolean).join(', '),
    lat: p.latitude,
    lon: p.longitude,
  }))
})
