import { createI18n } from 'vue-i18n'
import ru from './locales/ru.json'
import ky from './locales/ky.json'

const STORAGE_KEY = 'akmsoft_locale'
const SUPPORTED_LOCALES = ['ru', 'ky']

function getInitialLocale() {
  const saved = localStorage.getItem(STORAGE_KEY)
  return SUPPORTED_LOCALES.includes(saved) ? saved : 'ru'
}

const i18n = createI18n({
  legacy: false,
  locale: getInitialLocale(),
  fallbackLocale: 'ru',
  messages: { ru, ky },
})

export function setLocale(locale) {
  if (!SUPPORTED_LOCALES.includes(locale)) return
  i18n.global.locale.value = locale
  localStorage.setItem(STORAGE_KEY, locale)
  document.documentElement.setAttribute('lang', locale)
}

export default i18n
