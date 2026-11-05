<script setup lang="ts">
interface Settings {
  repo: string | null
  weather: { name: string | null; lat: number | null; lon: number | null }
  calendars: Array<CalendarItem>
  activeCalendar: string | null
  night: { enabled: boolean; off: string; on: string }
  presets: Array<string>
  busy: { auto: boolean; soon: number; force: boolean }
  npm: { packages: Array<string>; package: string | null; period: string }
}
interface CalendarItem {
  id: string
  name: string
  host: string | null
  type: 'work' | 'personal'
}
interface Place {
  name: string
  lat: number
  lon: number
}
type Section = 'github' | 'npm' | 'weather' | 'calendar' | 'busy' | 'night' | 'presets'

const toast = useToast()
const loaded = ref(false)
const repo = ref('')
const weather = ref<Settings['weather']>({ name: null, lat: null, lon: null })
const calendars = ref<Array<CalendarItem>>([])
const activeCalendar = ref<string | null>(null)
const calendarName = ref('')
const calendarUrl = ref('')
const night = reactive({ enabled: false, off: '23:00', on: '07:00' })
const presets = ref<Array<string>>([])
const newPreset = ref('')
const npmPackages = ref<Array<string>>([])
const newPackage = ref('')
const saved = reactive<Record<Section, boolean>>({ github: false, npm: false, weather: false, calendar: false, busy: false, night: false, presets: false })
const calendarType = ref<'work' | 'personal'>('work')
const busy = reactive({ auto: false, soon: 15 })

// FetchError carries the API's {"error": "..."} body in .data
const errorText = (e: unknown) => (e as { data?: { error?: string } })?.data?.error ?? (e as Error)?.message

async function save(section: Section, request: () => Promise<unknown>) {
  try {
    await request()
    saved[section] = true
    setTimeout(() => (saved[section] = false), 1500)
  } catch (e: unknown) {
    toast.add({ title: "Couldn't save the setting", description: errorText(e), icon: 'i-iconoir-warning-circle', color: 'error' })
  }
}
const put = (section: string, body: object) => $fetch<unknown>(`/api/settings/${section}`, { method: 'PUT', body })

function saveRepo() {
  if (!/^[\w.-]+\/[\w.-]+$/.test(repo.value.trim())) return toast.add({ title: 'Use the form owner/name', color: 'error' })
  save('github', () => $fetch<unknown>('/api/repo', { method: 'PUT', body: { repo: repo.value.trim() } }))
}

// the server checks npm knows the package and answers with the list
function changeNpm(body: object) {
  save('npm', async () => {
    npmPackages.value = ((await put('npm', body)) as Settings['npm']).packages
  })
}
function addPackage() {
  if (!newPackage.value.trim()) return
  changeNpm({ add: newPackage.value.trim() })
  newPackage.value = ''
}

// place search, debounced while typing
const query = ref('')
const places = ref<Array<Place>>([])
const searching = ref(false)
let searchTimer: ReturnType<typeof setTimeout> | undefined
watch(query, (q) => {
  clearTimeout(searchTimer)
  if (q.trim().length < 2) return (places.value = [])
  searchTimer = setTimeout(async () => {
    searching.value = true
    places.value = await $fetch<Array<Place>>('/api/geocode', { query: { q } }).catch(() => [])
    searching.value = false
  }, 350)
})
function pickPlace(p: Place) {
  weather.value = p
  query.value = ''
  places.value = []
  save('weather', () => put('weather', p))
}
function clearPlace() {
  weather.value = { name: null, lat: null, lon: null }
  save('weather', () => put('weather', { lat: null }))
}

// add, remove, select or type. The server answers with the list (names and hosts only)
function changeCalendars(body: object) {
  save('calendar', async () => {
    const r = (await put('calendars', body)) as { calendars: Array<CalendarItem>; active: string | null }
    calendars.value = r.calendars
    activeCalendar.value = r.active
  })
}
function addCalendar() {
  if (!calendarUrl.value.trim()) return
  changeCalendars({ add: { name: calendarName.value.trim(), url: calendarUrl.value.trim(), type: calendarType.value } })
  calendarName.value = calendarUrl.value = ''
}

function saveBusy() {
  save('busy', () => put('busy', { auto: busy.auto, soon: busy.soon }))
}

function saveNight() {
  save('night', () => put('night', { ...night }))
}

function savePresets(items: Array<string>) {
  presets.value = items
  save('presets', () => put('presets', { items }))
}
function addPreset() {
  const p = newPreset.value.trim()
  if (p && !presets.value.includes(p)) savePresets([...presets.value, p])
  newPreset.value = ''
}

onMounted(async () => {
  try {
    const s = await $fetch<Settings>('/api/settings')
    repo.value = s.repo ?? 'kubb-labs/kubb'
    weather.value = s.weather
    calendars.value = s.calendars
    activeCalendar.value = s.activeCalendar
    Object.assign(night, s.night)
    Object.assign(busy, { auto: s.busy.auto, soon: s.busy.soon })
    presets.value = s.presets
    npmPackages.value = s.npm.packages
  } finally {
    loaded.value = true
  }
})
onBeforeUnmount(() => clearTimeout(searchTimer))
</script>

<template>
  <main class="mx-auto grid max-w-3xl gap-6 px-4 py-8 sm:px-6 sm:py-12">
    <header class="rise flex flex-wrap items-center justify-between gap-3" style="--i: 0">
      <div class="flex items-center gap-2">
        <UButton to="/" icon="i-iconoir-nav-arrow-left" color="neutral" variant="ghost" class="rounded-full" aria-label="Back to the panel" />
        <div class="grid gap-0.5">
          <h1 class="text-xl font-bold text-black dark:text-white">Settings</h1>
          <p class="text-sm text-muted">Saved on the Pi as you change them</p>
        </div>
      </div>
      <UColorModeButton class="rounded-full" />
    </header>

    <div v-if="loaded" class="grid gap-4 font-mono text-xs">
      <section id="github" class="card rise scroll-mt-6" style="--i: 1">
        <div class="flex items-center justify-between border-b border-default px-4 py-3 text-[11px] uppercase tracking-wider text-muted">
          <span>github</span><span v-if="saved.github" class="normal-case tracking-normal text-emerald-500">saved</span>
        </div>
        <div class="grid gap-4 p-4">
          <UFormField label="repository" help="the stars screen shows its star count. Saved when you leave the field or press Enter">
            <UInput
              v-model="repo"
              icon="i-iconoir-github"
              size="lg"
              class="w-full"
              spellcheck="false"
              placeholder="owner/name"
              :ui="{ base: 'font-mono' }"
              @change="saveRepo"
            />
          </UFormField>
        </div>
      </section>

      <section id="npm" class="card rise scroll-mt-6" style="--i: 2">
        <div class="flex items-center justify-between border-b border-default px-4 py-3 text-[11px] uppercase tracking-wider text-muted">
          <span>npm</span><span v-if="saved.npm" class="normal-case tracking-normal text-emerald-500">saved</span>
        </div>
        <div class="grid gap-4 p-4">
          <p v-if="!npmPackages.length" class="flex items-center gap-2 text-highlighted">
            <UIcon name="i-iconoir-npm" class="size-4 text-muted" />no packages yet
          </p>
          <ul v-else class="flex flex-wrap gap-1.5" aria-label="npm packages">
            <li v-for="p in npmPackages" :key="p" class="flex items-center gap-1 rounded-full py-1 pl-2.5 pr-1 ring-1 ring-default text-highlighted">
              {{ p }}
              <button
                type="button"
                class="grid size-5 place-items-center rounded-full text-muted hover:bg-elevated hover:text-highlighted"
                :aria-label="`Remove ${p}`"
                @click="changeNpm({ remove: p })"
              >
                <UIcon name="i-iconoir-xmark" class="size-3" />
              </button>
            </li>
          </ul>
          <form class="flex gap-2" @submit.prevent="addPackage">
            <UInput
              v-model="newPackage"
              icon="i-iconoir-npm"
              size="lg"
              class="flex-1"
              spellcheck="false"
              placeholder="add a package, e.g. @scope/name"
              :ui="{ base: 'font-mono' }"
            />
            <UButton type="submit" icon="i-iconoir-plus" color="neutral" variant="soft" size="lg" aria-label="Add package" :disabled="!newPackage.trim()" />
          </form>
          <p class="text-muted">The npm tab shows the downloads of the one you pick there, for the last day, week, month or year.</p>
        </div>
      </section>

      <section id="weather" class="card rise scroll-mt-6" style="--i: 3">
        <div class="flex items-center justify-between border-b border-default px-4 py-3 text-[11px] uppercase tracking-wider text-muted">
          <span>weather</span><span v-if="saved.weather" class="normal-case tracking-normal text-emerald-500">saved</span>
        </div>
        <div class="grid gap-4 p-4">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <span class="flex items-center gap-2 text-highlighted">
              <UIcon name="i-iconoir-map-pin" class="size-4 text-muted" />{{ weather.lat === null ? 'no location set' : weather.name }}
            </span>
            <UButton v-if="weather.lat !== null" color="neutral" variant="ghost" size="xs" icon="i-iconoir-xmark" @click="clearPlace">clear</UButton>
          </div>
          <UFormField label="search a place" help="temperature and an icon from Open-Meteo, every 10 minutes">
            <UInput v-model="query" icon="i-iconoir-search" size="lg" class="w-full" placeholder="Brussels" :loading="searching" :ui="{ base: 'font-mono' }" />
          </UFormField>
          <ul v-if="places.length" class="grid gap-1" aria-label="Places">
            <li v-for="p in places" :key="`${p.lat},${p.lon}`">
              <button
                type="button"
                class="flex w-full items-center justify-between gap-3 rounded-md px-3 py-2 text-left ring-1 ring-default transition duration-150 ease-out hover:bg-elevated"
                @click="pickPlace(p)"
              >
                <span class="truncate text-highlighted">{{ p.name }}</span>
                <span class="shrink-0 text-muted">{{ p.lat.toFixed(2) }}, {{ p.lon.toFixed(2) }}</span>
              </button>
            </li>
          </ul>
        </div>
      </section>

      <section id="calendar" class="card rise scroll-mt-6" style="--i: 4">
        <div class="flex items-center justify-between border-b border-default px-4 py-3 text-[11px] uppercase tracking-wider text-muted">
          <span>calendar</span><span v-if="saved.calendar" class="normal-case tracking-normal text-emerald-500">saved</span>
        </div>
        <div class="grid gap-4 p-4">
          <p v-if="!calendars.length" class="flex items-center gap-2 text-highlighted">
            <UIcon name="i-iconoir-calendar" class="size-4 text-muted" />no calendars yet
          </p>
          <ul v-else class="grid gap-1.5" aria-label="Calendars">
            <li v-for="c in calendars" :key="c.id" class="flex items-center gap-3 rounded-md px-3 py-2 ring-1 ring-default">
              <button
                type="button"
                role="radio"
                class="flex min-w-0 flex-1 items-center gap-3 text-left"
                :aria-checked="c.id === activeCalendar"
                @click="c.id !== activeCalendar && changeCalendars({ select: c.id })"
              >
                <span class="grid size-4 shrink-0 place-items-center rounded-full ring-1 ring-accented">
                  <span v-if="c.id === activeCalendar" class="size-2 rounded-full bg-inverted" />
                </span>
                <span class="truncate text-highlighted">{{ c.name }}</span>
                <span class="truncate text-muted">{{ c.host }}</span>
              </button>
              <div class="flex shrink-0 rounded-full p-0.5 ring-1 ring-default" role="radiogroup" :aria-label="`${c.name} type`">
                <button
                  v-for="t in ['work', 'personal'] as const"
                  :key="t"
                  type="button"
                  role="radio"
                  class="rounded-full px-2 py-0.5 transition duration-150 ease-out"
                  :class="c.type === t ? 'bg-inverted text-inverted' : 'text-muted hover:text-highlighted'"
                  :aria-checked="c.type === t"
                  @click="c.type !== t && changeCalendars({ type: { id: c.id, type: t } })"
                >
                  {{ t }}
                </button>
              </div>
              <UButton
                color="neutral"
                variant="ghost"
                size="xs"
                icon="i-iconoir-trash"
                :aria-label="`Remove ${c.name}`"
                @click="changeCalendars({ remove: c.id })"
              />
            </li>
          </ul>
          <form class="grid gap-3 sm:grid-cols-[10rem_minmax(0,1fr)_7rem_auto] sm:items-end" @submit.prevent="addCalendar">
            <UFormField label="name">
              <UInput v-model="calendarName" size="lg" class="w-full" maxlength="40" placeholder="Work" :ui="{ base: 'font-mono' }" />
            </UFormField>
            <UFormField label="private iCal link">
              <UInput
                v-model="calendarUrl"
                type="url"
                size="lg"
                class="w-full"
                placeholder="https://… or webcal://…"
                autocomplete="off"
                :ui="{ base: 'font-mono' }"
              />
            </UFormField>
            <UFormField label="type">
              <USelect v-model="calendarType" :items="['work', 'personal']" size="lg" class="w-full" :ui="{ base: 'font-mono' }" />
            </UFormField>
            <UButton type="submit" icon="i-iconoir-plus" color="neutral" variant="soft" size="lg" :disabled="!calendarUrl.trim()">add</UButton>
          </form>
          <p class="text-muted">
            The selected one shows on the calendar tab. Work calendars also drive the busy light. Google: Settings → your calendar → “Secret address in iCal
            format”. Outlook: Settings → Shared calendars → Publish → ICS. Links stay on the Pi.
          </p>
        </div>
      </section>

      <section id="busy" class="card rise scroll-mt-6" style="--i: 5">
        <div class="flex items-center justify-between border-b border-default px-4 py-3 text-[11px] uppercase tracking-wider text-muted">
          <span>busy light</span><span v-if="saved.busy" class="normal-case tracking-normal text-emerald-500">saved</span>
        </div>
        <div class="grid gap-4 p-4 sm:grid-cols-[minmax(0,1fr)_10rem] sm:items-end">
          <div class="grid gap-2">
            <USwitch v-model="busy.auto" label="switch to the busy light by itself" @update:model-value="saveBusy" />
            <p class="text-muted">
              The panel glows green when you're free, orange before a work meeting and red during one, then goes back to what was on screen. Only work calendars
              count.
            </p>
          </div>
          <UFormField label="orange from (minutes)">
            <UInput
              v-model.number="busy.soon"
              type="number"
              min="1"
              max="30"
              size="lg"
              class="w-full"
              :disabled="!busy.auto"
              :ui="{ base: 'font-mono' }"
              @change="saveBusy"
            />
          </UFormField>
        </div>
      </section>

      <section id="night" class="card rise scroll-mt-6" style="--i: 6">
        <div class="flex items-center justify-between border-b border-default px-4 py-3 text-[11px] uppercase tracking-wider text-muted">
          <span>night mode</span><span v-if="saved.night" class="normal-case tracking-normal text-emerald-500">saved</span>
        </div>
        <div class="grid gap-4 p-4 sm:grid-cols-3 sm:items-end">
          <USwitch v-model="night.enabled" label="turn the screen off at night" class="sm:col-span-3" @update:model-value="saveNight" />
          <UFormField label="off at">
            <UInput v-model="night.off" type="time" size="lg" class="w-full" :disabled="!night.enabled" :ui="{ base: 'font-mono' }" @change="saveNight" />
          </UFormField>
          <UFormField label="on at">
            <UInput v-model="night.on" type="time" size="lg" class="w-full" :disabled="!night.enabled" :ui="{ base: 'font-mono' }" @change="saveNight" />
          </UFormField>
          <p class="text-muted sm:pb-2.5">the Pi switches the screen, and you can still turn it on yourself</p>
        </div>
      </section>

      <section id="presets" class="card rise scroll-mt-6" style="--i: 7">
        <div class="flex items-center justify-between border-b border-default px-4 py-3 text-[11px] uppercase tracking-wider text-muted">
          <span>text presets</span><span v-if="saved.presets" class="normal-case tracking-normal text-emerald-500">saved</span>
        </div>
        <div class="grid gap-4 p-4">
          <ul class="flex flex-wrap gap-1.5" aria-label="Presets">
            <li v-for="p in presets" :key="p" class="flex items-center gap-1 rounded-full py-1 pl-2.5 pr-1 ring-1 ring-default text-highlighted">
              {{ p }}
              <button
                type="button"
                class="grid size-5 place-items-center rounded-full text-muted hover:bg-elevated hover:text-highlighted"
                :aria-label="`Remove ${p}`"
                @click="savePresets(presets.filter((x) => x !== p))"
              >
                <UIcon name="i-iconoir-xmark" class="size-3" />
              </button>
            </li>
          </ul>
          <form class="flex gap-2" @submit.prevent="addPreset">
            <UInput v-model="newPreset" size="lg" class="flex-1" maxlength="60" placeholder="add a preset, e.g. standup" :ui="{ base: 'font-mono' }" />
            <UButton type="submit" icon="i-iconoir-plus" color="neutral" variant="soft" size="lg" aria-label="Add preset" :disabled="!newPreset.trim()" />
          </form>
        </div>
      </section>
    </div>
  </main>
</template>
