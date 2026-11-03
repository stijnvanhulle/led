<script setup lang="ts">
import { forgetScreens, forgetStars, measure, type BusyState, MIN_BRIGHTNESS, modeOf, W, type Feature, type PanelState } from '~/utils/led'

interface Health {
  ok: boolean
  mode: string
  repo: string
  stars: number | null
  clock: { color: string; h24: boolean; blink: boolean }
  stars_color: string
  brightness: number
  power: boolean
  weather: { name: string | null; lat: number | null; color: string }
  calendar: { set: boolean; color: string }
  npm: { package: string | null; period: string; color: string }
  busy: { calendars: number; auto: boolean; soon: number; force: boolean; state: BusyState; at: string | null }
}

const toast = useToast()
const state = reactive<PanelState>({
  feature: 'text',
  text: 'hi!',
  color: '#ff7ad9',
  animation: 0,
  speed: 80,
  stars: null,
  clockColor: '#6fb6ff',
  h24: true,
  blink: true,
  starsColor: '#ffd700',
  weatherColor: '#ffffff',
  calendarColor: '#f0b049',
  npmColor: '#cb3837',
  busyState: 'free',
  brightness: 100,
  power: true,
})
const repo = ref('kubb-labs/kubb')
const mode = ref<string | null>(null)
const online = ref<boolean | null>(null)
const busy = ref(false)
const sent = ref(false) // briefly true after a send, to highlight the device frame
const lastError = ref('')

const features: Array<{ id: Feature; label: string }> = [
  { id: 'text', label: 'text' },
  { id: 'stars', label: 'stars' },
  { id: 'npm', label: 'npm' },
  { id: 'clock', label: 'clock' },
  { id: 'weather', label: 'weather' },
  { id: 'calendar', label: 'calendar' },
  { id: 'busy', label: 'busy light' },
]
const weatherName = ref<string | null>(null)
const calendars = ref<Array<{ id: string; name: string; host: string | null }>>([])
const activeCalendar = ref<string | null>(null)
const presets = ref<Array<string>>([])
const npm = ref<NpmSettings>({ packages: [], package: null, period: 'last-week' })
const npmPeriods = [
  { label: 'day', value: 'last-day' },
  { label: 'week', value: 'last-week' },
  { label: 'month', value: 'last-month' },
  { label: 'year', value: 'last-year' },
]
const busyInfo = ref<Health['busy'] | null>(null)
const busyText = computed(() => {
  const b = busyInfo.value
  if (!b) return ''
  const hm = b.at ? new Date(b.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : null
  if (b.force) return 'busy, switched on by hand'
  if (b.state === 'busy') return hm ? `in a work meeting until ${hm}` : 'in a work meeting'
  if (b.state === 'soon') return hm ? `work meeting at ${hm}` : 'work meeting soon'
  return b.calendars ? 'free: no work meeting right now' : 'free: no work calendar yet'
})
// for calls that aren't in the calendar: red until switched off
// The switch flips at once and the preview follows. The Pi gets the last state 400 ms
// after the last click, since redrawing the panel over Bluetooth takes a moment.
const force = ref(false)
let forceTimer: ReturnType<typeof setTimeout> | undefined
let forcePending = false
function setForce(on: boolean) {
  const before = busyInfo.value?.force ?? false
  force.value = on
  if (on) state.busyState = 'busy'
  forcePending = true
  clearTimeout(forceTimer)
  forceTimer = setTimeout(async () => {
    try {
      const b = await $fetch<{ force: boolean }>('/api/settings/busy', { method: 'PUT', body: { force: force.value } })
      if (busyInfo.value) busyInfo.value.force = b.force
      if (mode.value !== 'busy') schedule()
    } catch (e: unknown) {
      force.value = before
      toast.add({ title: "Couldn't change the busy light", description: errorText(e), color: 'error' })
    } finally {
      forcePending = false
      refresh()
    }
  }, 400)
}
// names for the default emoji presets, for hover and screen readers
const PRESET_NAMES: Record<string, string> = {
  '📅': 'in a meeting',
  '📞': 'on a call',
  '🎧': 'focus time',
  '🍕': 'lunch',
  '☕': 'coffee break',
  '🚀': 'deploying',
  '👀': 'code review',
  '🐛': 'fixing a bug',
  '🎉': 'shipped',
  '🏖': 'out today',
}

interface NpmSettings {
  packages: Array<string>
  package: string | null
  period: string
}
interface SavedSettings {
  presets: Array<string>
  npm: NpmSettings
  calendars: Array<{ id: string; name: string; host: string | null }>
  activeCalendar: string | null
  screen: (Partial<PanelState> & { feature: Feature }) | null
}
const effects = [
  { label: 'static', value: 0 },
  { label: 'scroll left', value: 1 },
  { label: 'scroll right', value: 2 },
  { label: 'blink', value: 5 },
  { label: 'fade', value: 6 },
  { label: 'snowflake', value: 7 },
]

// real width from the Pi's renderer, so emoji (16px) and wide glyphs count right
const textW = ref(0)
watch(
  () => state.text,
  async (t) => {
    textW.value = await measure(t || ' ').catch(() => textW.value)
  },
  { immediate: true },
)
const pages = computed(() => Math.max(1, Math.ceil(textW.value / W)))
const tooWide = computed(() => state.feature === 'text' && pages.value > 1 && state.animation === 0)
const fit = computed(() => (state.feature === 'text' ? `${textW.value} of 64 px${tooWide.value ? ` · ${pages.value} pages` : ''}` : '64 × 16'))
const onPanel = (f: Feature) => mode.value === modeOf[f]

const status = computed(() => {
  if (online.value === false) return { text: 'pi not answering', dot: 'bg-red-500' }
  if (!state.power) return { text: 'screen off', dot: 'bg-zinc-600' }
  if (busy.value) return { text: 'sending…', dot: 'bg-amber-400 live-dot' }
  if (lastError.value) return { text: `failed · ${lastError.value}`, dot: 'bg-red-500' }
  return { text: `${onPanel(state.feature) ? 'on panel' : 'preview'} · ${state.feature}`, dot: 'bg-emerald-400' }
})

// FetchError carries the API's {"error": "..."} body in .data
const errorText = (e: unknown) => (e as { data?: { error?: string } })?.data?.error ?? (e as Error)?.message

const post = <T = unknown>(path: string, body: object) => $fetch<T>(`/api/${path}`, { method: 'POST', body })

// Saved on the Pi, so the stars job keeps this repo and color after restarts and deploys.
const savedRepo = ref('')
async function saveRepo() {
  const r = await $fetch<{ repo: string; stars: number }>('/api/repo', { method: 'PUT', body: { repo: repo.value.trim(), color: state.starsColor } })
  savedRepo.value = r.repo
  state.stars = r.stars
  forgetStars()
}

async function send() {
  busy.value = true
  try {
    if (state.feature === 'text') {
      await post('command/send_text', { text: state.text || ' ', color: state.color.slice(1), animation: state.animation, speed: state.speed })
    } else if (state.feature === 'stars') {
      // while stars are on screen, saving the repo or color redraws them by itself
      await saveRepo()
      if (mode.value !== 'stars') state.stars = (await post<{ stars: number }>('stars', {})).stars
    } else if (state.feature === 'clock') {
      await post('clock', { color: state.clockColor.slice(1), h24: state.h24, blink: state.blink })
    } else if (state.feature === 'busy') {
      await post('busy', {})
    } else {
      await post(state.feature, { color: { weather: state.weatherColor, calendar: state.calendarColor, npm: state.npmColor }[state.feature].slice(1) })
    }
    mode.value = modeOf[state.feature]
    lastError.value = ''
    // what's on the panel now, so a restart or redeploy puts it back
    const { feature, text, color, animation, speed, starsColor, clockColor, h24, blink, weatherColor, calendarColor, npmColor } = state
    $fetch('/api/settings/screen', {
      method: 'PUT',
      body: { feature, text, color, animation, speed, starsColor, clockColor, h24, blink, weatherColor, calendarColor, npmColor },
    }).catch(() => {})
    sent.value = true
    setTimeout(() => (sent.value = false), 1200)
  } catch (e: unknown) {
    lastError.value = errorText(e) ?? 'unknown error'
    toast.add({ title: "Couldn't update the panel", description: lastError.value, icon: 'i-iconoir-warning-circle', color: 'error' })
  } finally {
    busy.value = false
  }
}

// Every change goes to the panel by itself, debounced. One send at a time over
// Bluetooth (about 2 s), and a change made meanwhile sends the newest state after it.
const ready = ref(false)
let debounce: ReturnType<typeof setTimeout> | undefined
let inflight = false
let pending = false
function schedule(delay = 400) {
  if (!ready.value || online.value === false) return
  clearTimeout(debounce)
  debounce = setTimeout(flush, delay)
}
async function flush() {
  if (inflight) {
    pending = true
    return
  }
  inflight = true
  await send()
  inflight = false
  if (pending) {
    pending = false
    flush()
  }
}
watch(
  () => [
    state.feature,
    state.color,
    state.animation,
    state.speed,
    state.starsColor,
    state.clockColor,
    state.h24,
    state.blink,
    state.weatherColor,
    state.calendarColor,
    state.npmColor,
  ],
  () => schedule(),
)
watch(
  () => state.text,
  () => schedule(700),
)

let brightTimer: ReturnType<typeof setTimeout> | undefined
watch(
  () => state.brightness,
  (level) => {
    if (!ready.value) return
    clearTimeout(brightTimer)
    brightTimer = setTimeout(() => setting({ brightness: level }), 300)
  },
)

// switching calendars redraws the panel by itself while the calendar is on screen
async function selectCalendar(id: string) {
  if (id === activeCalendar.value) return
  activeCalendar.value = id
  try {
    await $fetch('/api/settings/calendars', { method: 'PUT', body: { select: id } })
    forgetScreens()
    if (mode.value !== 'calendar') schedule()
  } catch (e: unknown) {
    toast.add({ title: "Couldn't switch calendars", description: errorText(e), color: 'error' })
  }
}

// picking a package or period redraws the panel by itself while npm is on screen
async function changeNpm(body: { select?: string; period?: string }) {
  try {
    npm.value = await $fetch<NpmSettings>('/api/settings/npm', { method: 'PUT', body })
    forgetScreens()
    if (mode.value !== 'npm') schedule()
  } catch (e: unknown) {
    toast.add({ title: "Couldn't change the npm screen", description: errorText(e), color: 'error' })
  }
}

function togglePower() {
  state.power = !state.power
  setting({ power: state.power })
}

async function setting(body: { brightness?: number; power?: boolean }) {
  try {
    await $fetch('/api/panel', { method: 'PUT', body })
  } catch (e: unknown) {
    toast.add({ title: "Couldn't change the setting", description: errorText(e), color: 'error' })
  }
}

async function refresh(first = false) {
  try {
    const h = await $fetch<Health>('/api/health')
    online.value = true
    mode.value = h.mode
    busyInfo.value = h.busy
    // while a click is on its way, keep what the switch shows
    if (!forcePending) {
      force.value = h.busy.force
      state.busyState = h.busy.state
    }
    state.stars = h.stars
    weatherName.value = h.weather.lat === null ? null : h.weather.name
    if (first) {
      // the Python service doesn't know the text settings, so they come from the saved screen
      const saved = await $fetch<SavedSettings>('/api/settings').catch(() => null)
      if (saved) {
        presets.value = saved.presets
        npm.value = saved.npm
        calendars.value = saved.calendars
        activeCalendar.value = saved.activeCalendar
        if (saved.screen) {
          const { text, color, animation, speed } = saved.screen
          Object.assign(state, { text: text ?? state.text, color: color ?? state.color, animation: animation ?? state.animation, speed: speed ?? state.speed })
        }
      }
      // start from what the panel shows, so opening the page changes nothing
      Object.assign(state, {
        clockColor: `#${h.clock.color}`,
        h24: h.clock.h24,
        blink: h.clock.blink,
        starsColor: `#${h.stars_color}`,
        weatherColor: `#${h.weather.color}`,
        calendarColor: `#${h.calendar.color}`,
        npmColor: `#${h.npm.color}`,
        brightness: Math.max(MIN_BRIGHTNESS, h.brightness),
        power: h.power,
        feature: features.find((f) => modeOf[f.id] === h.mode)?.id ?? saved?.screen?.feature ?? 'text',
      })
      repo.value = savedRepo.value = h.repo
      await nextTick()
      ready.value = true
    }
  } catch {
    online.value = false
  }
}

let timer: ReturnType<typeof setInterval>
onMounted(() => {
  // settings may have changed since this page was last open
  forgetScreens()
  refresh(true)
  timer = setInterval(refresh, 30_000)
})
onBeforeUnmount(() => {
  clearInterval(timer)
  clearTimeout(debounce)
  clearTimeout(brightTimer)
  clearTimeout(forceTimer)
})
</script>

<template>
  <main class="mx-auto grid max-w-3xl gap-6 px-4 py-8 sm:px-6 sm:py-12">
    <header class="rise flex flex-wrap items-center justify-between gap-3" style="--i: 0">
      <div class="grid gap-0.5">
        <h1 class="text-xl font-bold text-black dark:text-white">pi-led</h1>
        <p class="text-sm text-muted">The LED panel on the Raspberry Pi</p>
      </div>
      <div class="flex items-center gap-1">
        <UButton to="/settings" icon="i-iconoir-settings" color="neutral" variant="ghost" class="rounded-full" aria-label="Settings" />
        <UColorModeButton class="rounded-full" />
      </div>
    </header>

    <section class="rise sticky top-0 z-10 -mx-4 flex gap-3 bg-default/90 px-4 py-2 backdrop-blur sm:mx-0 sm:gap-4 sm:px-0" style="--i: 1">
      <div class="device flex min-w-0 flex-1 flex-col rounded-[18px]" :class="{ 'is-sent': sent }">
        <div class="flex items-center justify-between gap-3 px-4 py-2.5 font-mono text-[11px] text-zinc-400" aria-live="polite">
          <span class="flex min-w-0 items-center gap-2">
            <span class="size-1.5 shrink-0 rounded-full" :class="status.dot" />
            <span class="truncate">{{ status.text }}</span>
          </span>
          <span class="shrink-0 tabular-nums" :class="tooWide ? 'text-amber-400' : ''">{{ fit }} · {{ state.brightness }}%</span>
        </div>
        <LedPanel :state="state" :busy="busy" :loading="online === null" class="mx-2.5" />
        <div class="flex gap-1 px-2.5 pb-2.5 pt-2 font-mono text-xs" role="group" aria-label="What the panel shows">
          <button
            v-for="f in features"
            :key="f.id"
            type="button"
            class="rounded-md px-2.5 py-1.5 transition duration-150 ease-out"
            :class="state.feature === f.id ? 'bg-zinc-800 text-white' : 'text-zinc-400 hover:text-zinc-200'"
            :aria-pressed="state.feature === f.id"
            @click="state.feature = f.id"
          >
            {{ f.label }}
          </button>
        </div>
      </div>

      <div class="device flex flex-col items-center justify-between gap-3 rounded-[18px] px-2.5 py-3">
        <button
          type="button"
          class="grid size-9 place-items-center rounded-full transition duration-150 ease-out"
          :class="state.power ? 'bg-white text-zinc-950' : 'bg-zinc-800 text-zinc-400'"
          :aria-pressed="state.power"
          :aria-label="state.power ? 'Turn the screen off' : 'Turn the screen on'"
          @click="togglePower"
        >
          <UIcon :name="state.power ? 'i-iconoir-light-bulb-on' : 'i-iconoir-light-bulb-off'" class="size-4" />
        </button>
        <div class="flex flex-1 flex-col items-center gap-2 text-zinc-400">
          <USlider
            v-model="state.brightness"
            orientation="vertical"
            :min="MIN_BRIGHTNESS"
            :max="100"
            size="sm"
            class="min-h-20 flex-1"
            :ui="{ track: 'bg-zinc-700', range: 'bg-zinc-200', thumb: 'bg-zinc-950 ring-zinc-200' }"
            aria-label="Brightness"
          />
          <UIcon name="i-iconoir-brightness" class="size-4" aria-hidden="true" />
        </div>
      </div>
    </section>

    <section class="card rise font-mono text-xs" style="--i: 2">
      <div class="flex items-center justify-between gap-3 border-b border-default px-4 py-3 text-[11px] uppercase tracking-wider text-muted">
        <span>{{ state.feature }}</span>
        <span class="normal-case tracking-normal">changes go to the panel automatically</span>
      </div>

      <Transition
        mode="out-in"
        enter-active-class="transition duration-200 ease-out"
        enter-from-class="opacity-0 translate-y-2"
        leave-active-class="transition duration-150 ease-in"
        leave-to-class="opacity-0"
      >
        <div v-if="state.feature === 'text'" key="text" class="grid gap-x-6 gap-y-4 p-4 sm:grid-cols-2">
          <UFormField label="text" class="sm:col-span-2">
            <UInput v-model="state.text" size="lg" maxlength="200" class="w-full" :ui="{ base: 'font-mono' }" />
          </UFormField>
          <div v-if="presets.length" class="flex flex-wrap gap-1.5 sm:col-span-2" role="group" aria-label="Text presets">
            <button
              v-for="p in presets"
              :key="p"
              type="button"
              class="grid min-w-10 place-items-center rounded-full px-2.5 py-1 text-lg leading-none ring-1 ring-default transition duration-150 ease-out hover:-translate-y-0.5"
              :class="state.text === p ? 'bg-inverted text-inverted ring-inverted' : 'text-toned hover:text-highlighted'"
              :aria-pressed="state.text === p"
              :aria-label="PRESET_NAMES[p] ?? p"
              :title="PRESET_NAMES[p] ?? p"
              @click="state.text = p"
            >
              {{ p }}
            </button>
          </div>
          <UFormField label="color">
            <ColorPicker v-model="state.color" />
          </UFormField>
          <UFormField label="effect">
            <USelect v-model="state.animation" :items="effects" class="w-full" :ui="{ base: 'font-mono' }" />
          </UFormField>
          <UFormField :label="`speed ${state.speed}`" class="sm:col-span-2">
            <USlider v-model="state.speed" :min="10" :max="100" size="sm" class="pt-2" />
          </UFormField>
        </div>

        <div v-else-if="state.feature === 'stars'" key="stars" class="grid gap-x-6 gap-y-4 p-4 sm:grid-cols-2">
          <UFormField label="repository" class="sm:col-span-2" help="checked every 10 minutes and redrawn when the count changes">
            <NuxtLink to="/settings#github" class="flex items-center gap-2 text-highlighted underline-offset-2 hover:underline">
              <UIcon name="i-iconoir-github" class="size-4 text-muted" />{{ repo }}<span class="text-muted">· change in settings</span>
            </NuxtLink>
          </UFormField>
          <UFormField label="color">
            <ColorPicker v-model="state.starsColor" />
          </UFormField>
        </div>

        <div v-else-if="state.feature === 'npm'" key="npm" class="grid gap-x-6 gap-y-4 p-4 sm:grid-cols-2">
          <UFormField v-if="npm.packages.length" label="package" class="sm:col-span-2" help="downloads from npm, checked every hour">
            <div class="flex flex-wrap items-center gap-3">
              <USelect
                :model-value="npm.package ?? undefined"
                :items="npm.packages"
                icon="i-iconoir-npm"
                class="min-w-48"
                :ui="{ base: 'font-mono' }"
                @update:model-value="(p) => changeNpm({ select: String(p) })"
              />
              <NuxtLink to="/settings#npm" class="text-muted underline-offset-2 hover:underline">add or remove in settings</NuxtLink>
            </div>
          </UFormField>
          <UFormField v-else label="package" class="sm:col-span-2">
            <NuxtLink to="/settings#npm" class="flex items-center gap-2 text-highlighted underline-offset-2 hover:underline">
              <UIcon name="i-iconoir-npm" class="size-4 text-muted" />no package yet<span class="text-muted">· add one in settings</span>
            </NuxtLink>
          </UFormField>
          <UFormField label="downloads in the last">
            <USelect
              :model-value="npm.period"
              :items="npmPeriods"
              class="w-full"
              :ui="{ base: 'font-mono' }"
              @update:model-value="(p) => changeNpm({ period: String(p) })"
            />
          </UFormField>
          <UFormField label="color">
            <ColorPicker v-model="state.npmColor" />
          </UFormField>
        </div>

        <div v-else-if="state.feature === 'weather'" key="weather" class="grid gap-x-6 gap-y-4 p-4 sm:grid-cols-2">
          <UFormField label="location" class="sm:col-span-2" help="temperature and an icon from Open-Meteo, updated every 10 minutes">
            <NuxtLink to="/settings#weather" class="flex items-center gap-2 text-highlighted underline-offset-2 hover:underline">
              <UIcon name="i-iconoir-map-pin" class="size-4 text-muted" />{{ weatherName ?? 'no location set'
              }}<span class="text-muted">· change in settings</span>
            </NuxtLink>
          </UFormField>
          <UFormField label="color">
            <ColorPicker v-model="state.weatherColor" />
          </UFormField>
        </div>

        <div v-else-if="state.feature === 'calendar'" key="calendar" class="grid gap-x-6 gap-y-4 p-4 sm:grid-cols-2">
          <UFormField
            v-if="calendars.length"
            label="calendar"
            class="sm:col-span-2"
            help="your next event, updated every minute: “in 12m”, a time later today, “tmrw” or “free”"
          >
            <div class="flex flex-wrap items-center gap-3">
              <USelect
                :model-value="activeCalendar ?? undefined"
                :items="calendars.map((c) => ({ label: c.name, value: c.id }))"
                icon="i-iconoir-calendar"
                class="min-w-48"
                :ui="{ base: 'font-mono' }"
                @update:model-value="(id) => selectCalendar(String(id))"
              />
              <NuxtLink to="/settings#calendar" class="text-muted underline-offset-2 hover:underline">add or remove in settings</NuxtLink>
            </div>
          </UFormField>
          <UFormField v-else label="calendar" class="sm:col-span-2">
            <NuxtLink to="/settings#calendar" class="flex items-center gap-2 text-highlighted underline-offset-2 hover:underline">
              <UIcon name="i-iconoir-calendar" class="size-4 text-muted" />no calendar yet<span class="text-muted">· add one in settings</span>
            </NuxtLink>
          </UFormField>
          <UFormField label="color">
            <ColorPicker v-model="state.calendarColor" />
          </UFormField>
        </div>

        <div v-else-if="state.feature === 'busy'" key="busy" class="grid gap-x-6 gap-y-4 p-4 sm:grid-cols-2">
          <UFormField label="now" class="sm:col-span-2">
            <span class="flex items-center gap-2 text-highlighted">
              <span
                class="size-2 rounded-full"
                :class="state.busyState === 'busy' ? 'bg-red-500' : state.busyState === 'soon' ? 'bg-orange-500' : 'bg-emerald-400'"
              />{{ busyText }}
            </span>
          </UFormField>
          <USwitch :model-value="force" label="busy now (not in the calendar)" @update:model-value="setForce" />
          <NuxtLink to="/settings#busy" class="text-muted underline-offset-2 hover:underline sm:text-right">
            {{ busyInfo?.auto ? `switches on by itself ${busyInfo.soon} min before work meetings` : 'automatic switching is off' }} · settings
          </NuxtLink>
        </div>

        <div v-else key="clock" class="grid gap-x-6 gap-y-4 p-4 sm:grid-cols-2">
          <UFormField label="color" class="sm:col-span-2" help="drawn by the Pi in the panel's font, every minute">
            <ColorPicker v-model="state.clockColor" />
          </UFormField>
          <USwitch v-model="state.h24" label="24-hour" />
          <USwitch v-model="state.blink" label="blinking colon" />
        </div>
      </Transition>
    </section>
  </main>
</template>
