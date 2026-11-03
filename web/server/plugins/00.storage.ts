import fsDriver from 'unstorage/drivers/fs'

// Settings from the settings page, as files. On the Pi they live outside the repo
// (LED_DATA_DIR, set by led-web.service), so a fresh clone or reinstall keeps them.
// Anywhere else they're in web/.data/settings (git-ignored). Mounted only here, at runtime.
// The 00. prefix runs this before the plugin that reads the settings on start.
export default defineNitroPlugin(() => {
  useStorage().mount('settings', fsDriver({ base: process.env.LED_DATA_DIR || './.data/settings' }))
})
