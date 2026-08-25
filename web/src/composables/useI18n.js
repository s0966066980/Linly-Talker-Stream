// 語言管理 Composable
import { ref, computed } from 'vue'
import zhTW from '../locales/zh-TW.js'
import enUS from '../locales/en-US.js'

const languages = {
  'zh-TW': zhTW,
  'zh-CN': zhTW, // 舊的簡體設定改走繁中
  'en-US': enUS
}

const DEFAULT_LOCALE = 'zh-TW'

const normalizeLocale = (locale) => {
  if (!locale) return DEFAULT_LOCALE
  if (locale === 'zh-CN' || locale === 'zh') return 'zh-TW'
  return languages[locale] ? locale : DEFAULT_LOCALE
}

const currentLocale = ref(DEFAULT_LOCALE)

export function useI18n() {
  const t = (key) => {
    const keys = key.split('.')
    let value = languages[currentLocale.value]
    
    for (const k of keys) {
      if (value && typeof value === 'object') {
        value = value[k]
      } else {
        return key
      }
    }
    
    return value || key
  }
  
  const setLocale = (locale) => {
    const next = normalizeLocale(locale)
    currentLocale.value = next
    localStorage.setItem('linly-talker-stream-language', next)
  }
  
  const loadLocale = () => {
    const savedLocale = localStorage.getItem('linly-talker-stream-language')
    currentLocale.value = normalizeLocale(savedLocale)
    if (savedLocale && savedLocale !== currentLocale.value) {
      localStorage.setItem('linly-talker-stream-language', currentLocale.value)
    }
  }
  
  // 獲取當前語言
  const locale = computed(() => currentLocale.value)
  
  return {
    t,
    locale,
    setLocale,
    loadLocale
  }
}
