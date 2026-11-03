export default defineNuxtConfig({
  srcDir: 'src/',
  compatibilityDate: '2026-10-01',
  sourcemap: { server: false, client: false },
  modules: ['@nuxt/ui'],
  css: ['~/assets/css/main.css'],
  devtools: { enabled: false },
  runtimeConfig: {
    // the Python service that owns the Bluetooth connection, overridden by NUXT_LED_API
    ledApi: 'http://127.0.0.1:8080',
  },
  app: {
    head: {
      title: 'pi-led',
      htmlAttrs: { lang: 'en' },
    },
  },
})
