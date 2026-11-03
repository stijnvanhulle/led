<script setup lang="ts">
import { frame, H, MIN_BRIGHTNESS, SNAKE_FRAMES, SNAKE_MS, snakeFrame, W, type PanelState } from '~/utils/led'

// loading: the snake the panel shows at power-on, while the page connects
const props = defineProps<{ state: PanelState; busy?: boolean; loading?: boolean }>()

const canvas = ref<HTMLCanvasElement>()
const OFF = '#121215' // an unlit LED, just visible like on the real panel

// A left-to-right wipe with a white edge when the feature changes, like the panel does.
let prev: ReturnType<typeof frame> | null = null
let wipeStart = -1
watch(
  () => props.state.feature,
  () => {
    prev = frame({ ...props.state }, performance.now(), true)
    wipeStart = performance.now()
  },
  { flush: 'sync' },
)

let raf = 0
onBeforeUnmount(() => cancelAnimationFrame(raf))

onMounted(() => {
  const c = canvas.value!
  const g = c.getContext('2d')!
  // lit pixels go on their own layer, so it can be drawn blurred underneath as bloom
  const layer = Object.assign(document.createElement('canvas'), { width: c.width, height: c.height })
  const l = layer.getContext('2d')!
  const S = c.width / W
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches
  let last = 0
  let drawnKey = ''
  const pixel = (ctx: CanvasRenderingContext2D, x: number, y: number) => {
    ctx.beginPath()
    ctx.roundRect(x * S + S * 0.15, y * S + S * 0.15, S * 0.7, S * 0.7, S * 0.15)
    ctx.fill()
  }
  // the unlit grid never changes: draw it once and copy it in, so a frame only draws lit LEDs
  const grid = Object.assign(document.createElement('canvas'), { width: c.width, height: c.height })
  const gg = grid.getContext('2d')!
  gg.fillStyle = '#000000'
  gg.fillRect(0, 0, c.width, c.height)
  gg.fillStyle = OFF
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) pixel(gg, x, y)

  const paint = (t: number) => {
    raf = requestAnimationFrame(paint)
    if (t - last < 45) return
    last = t
    const next = props.loading ? snakeFrame(Math.floor(t / SNAKE_MS) % SNAKE_FRAMES) : frame(props.state, t, still)
    const edge = wipeStart < 0 || still ? W : Math.floor(((t - wipeStart) / 320) * W)
    if (edge >= W) wipeStart = -1
    const on = props.state.power || props.loading
    // MIN_BRIGHTNESS is the panel's dimmest look, still clearly lit. Only power off is dark
    const level = (Math.max(MIN_BRIGHTNESS, props.state.brightness) - MIN_BRIGHTNESS) / (100 - MIN_BRIGHTNESS)
    const strength = on ? 0.35 + 0.65 * level : 0

    const lit: Array<string | null> = []
    for (let y = 0; y < H; y++) {
      for (let x = 0; x < W; x++) {
        // the wipe's edge is a full white column, lit or not, like on the panel
        lit.push(on ? (x === edge ? '#ffffff' : ((x < edge || !prev ? next : prev)[y]![x] ?? null)) : null)
      }
    }
    // most screens hold still between ticks: skip a frame that looks like the last one
    const key = `${strength}|${lit.join(',')}`
    if (key === drawnKey) return
    drawnKey = key

    g.globalAlpha = 1
    g.filter = 'none'
    g.drawImage(grid, 0, 0)
    l.clearRect(0, 0, c.width, c.height)
    for (let i = 0; i < lit.length; i++) {
      if (!lit[i]) continue
      l.fillStyle = lit[i]!
      pixel(l, i % W, Math.floor(i / W))
    }

    // bloom, then the crisp pixels, both scaled by brightness
    g.globalAlpha = 0.7 * strength
    g.filter = `blur(${S * 0.7}px)`
    g.drawImage(layer, 0, 0)
    g.filter = 'none'
    g.globalAlpha = strength
    g.drawImage(layer, 0, 0)
  }
  raf = requestAnimationFrame(paint)
})
</script>

<template>
  <div class="screen overflow-hidden rounded-lg bg-black" :class="{ 'is-busy': busy }">
    <canvas ref="canvas" width="640" height="160" class="block h-auto w-full aspect-[4/1]" role="img" :aria-label="`LED panel preview: ${state.feature}`" />
  </div>
</template>
