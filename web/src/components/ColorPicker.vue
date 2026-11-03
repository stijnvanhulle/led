<script setup lang="ts">
const color = defineModel<string>({ required: true })
const swatches = ['#ff7ad9', '#ffb42e', '#5fcf92', '#6fb6ff', '#ef4b4b', '#ffffff']
</script>

<template>
  <div class="flex flex-wrap items-center gap-2">
    <button
      v-for="c in swatches"
      :key="c"
      type="button"
      class="size-6 rounded-md transition duration-150 ease-out hover:-translate-y-0.5"
      :class="color === c ? 'ring-2 ring-offset-2 ring-offset-default ring-inverted' : 'ring-1 ring-default'"
      :style="{ background: c }"
      :aria-label="`Color ${c}`"
      :aria-pressed="color === c"
      @click="color = c"
    />
    <label
      class="relative size-6 cursor-pointer rounded-md ring-1 ring-default bg-[conic-gradient(red,yellow,lime,cyan,blue,magenta,red)]"
      aria-label="Custom color"
    >
      <input v-model="color" type="color" class="absolute inset-0 opacity-0 cursor-pointer" />
    </label>
  </div>
</template>
