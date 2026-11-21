import { create } from 'zustand'

const THEME_STORAGE_KEY = 'crm_theme_mode'

/**
 * Obtiene el tema inicial desde localStorage o preferencia del sistema.
 */
function getInitialTheme() {
  if (typeof window === 'undefined') return 'light'
  try {
    const saved = localStorage.getItem(THEME_STORAGE_KEY)
    if (saved === 'dark' || saved === 'light') return saved
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
      return 'dark'
    }
  } catch {
    /* error de acceso a storage ignorado */
  }
  return 'light'
}

/**
 * Aplica o remueve la clase 'dark' en el elemento raíz del DOM (<html>).
 */
function applyThemeToDocument(theme) {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  if (theme === 'dark') {
    root.classList.add('dark')
    root.style.colorScheme = 'dark'
  } else {
    root.classList.remove('dark')
    root.style.colorScheme = 'light'
  }
}

// Inicialización inmediata al importar para evitar parpadeos visuales (FOUC)
const initialTheme = getInitialTheme()
applyThemeToDocument(initialTheme)

const useThemeStore = create((set, get) => ({
  theme: initialTheme,
  isDark: initialTheme === 'dark',

  toggleTheme: () => {
    const next = get().theme === 'dark' ? 'light' : 'dark'
    applyThemeToDocument(next)
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next)
    } catch {
      /* quota o storage bloqueado */
    }
    set({ theme: next, isDark: next === 'dark' })
  },

  setTheme: (next) => {
    if (next !== 'dark' && next !== 'light') return
    applyThemeToDocument(next)
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next)
    } catch {
      /* quota o storage bloqueado */
    }
    set({ theme: next, isDark: next === 'dark' })
  },
}))

export default useThemeStore
