export const REPO_PATTERN = /^[\w.-]+\/[\w.-]+$/
export const COLOR_PATTERN = /^#?[0-9a-fA-F]{6}$/

export interface StarsSettings {
  repo: string
  color?: string
}

export const getSavedStars = () => useStorage('settings').getItem<StarsSettings>('stars')
export const saveStars = (settings: StarsSettings) => useStorage('settings').setItem('stars', settings)

// Tells the Python service which repo to track and in what color. It keeps both only in memory.
export function pushStars(settings: StarsSettings) {
  return $fetch<{ repo: string; color: string; stars: number }>(`${useRuntimeConfig().ledApi}/repo`, { method: 'POST', body: settings })
}
