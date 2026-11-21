import { create } from 'zustand'
import api from '@/lib/api'

// Default CRM: cualquier install limpio sin TENANT_COMPANY_NAME ni
// logo custom en public.app_settings arranca con la marca por defecto.
// El cliente que sube su logo desde "Configuración → Marca" sobrescribe
// estos defaults dinamicamente en runtime (sin redeploy).
const DEFAULT_BRAND = {
  company_name:     'Palma del Río',
  company_subtitle: 'Plataforma de Gestión de Leads',
  logo_data_url:    '/favicon.svg',
  favicon_data_url: '/favicon.svg',
  primary_color:    '#1E40AF',  // blue-800
  primary_hover:    '#1D4ED8',  // blue-700
  sidebar_bg:       '#0F172A',
  accent_color:     '#38BDF8',  // sky-400
}

// Favicon por defecto del bundle. Se usa cuando el cliente no subió uno custom.
const DEFAULT_FAVICON_HREF = '/favicon.svg'

const BRAND_CACHE_KEY = 'brand_cache_v2'

/**
 * Lee la marca cacheada en localStorage. Si no existe o falla el parse,
 * devuelve el default. Esto evita el flash de marca por defecto en cada
 * reload de la SPA antes de que el fetch a /api/settings/brand responda.
 */
function readCachedBrand() {
  try {
    const raw = localStorage.getItem(BRAND_CACHE_KEY)
    if (!raw) return DEFAULT_BRAND
    return { ...DEFAULT_BRAND, ...JSON.parse(raw) }
  } catch {
    return DEFAULT_BRAND
  }
}

function writeCachedBrand(brand) {
  try {
    localStorage.setItem(BRAND_CACHE_KEY, JSON.stringify(brand))
  } catch {
    /* quota excedida (logos grandes en base64): no es crítico */
  }
}

/**
 * Convierte un color hex a "r, g, b" (para usarlo dentro de rgba(var(--...), 0.X)).
 */
function hexToRgb(hex) {
  if (!hex || typeof hex !== 'string') return '79, 70, 229'
  const clean = hex.replace('#', '')
  const full  = clean.length === 3 ? clean.split('').map(c => c + c).join('') : clean
  const num   = parseInt(full, 16)
  if (Number.isNaN(num)) return '79, 70, 229'
  return `${(num >> 16) & 255}, ${(num >> 8) & 255}, ${num & 255}`
}

/**
 * Inyecta (o reemplaza) el favicon del documento. Si href es falsy usa el default.
 * Reutiliza un único <link rel="icon"> para evitar duplicados entre re-apply.
 */
function applyFavicon(href) {
  if (typeof document === 'undefined') return
  const finalHref = href || DEFAULT_FAVICON_HREF
  let link = document.querySelector("link[rel~='icon']")
  if (!link) {
    link = document.createElement('link')
    link.rel = 'icon'
    document.head.appendChild(link)
  }
  // Si el favicon es un data URL, dejar que el navegador infiera el tipo;
  // si es un archivo estático .svg, fijar el type para evitar revalidaciones.
  if (finalHref.startsWith('data:')) {
    link.removeAttribute('type')
  } else if (finalHref.endsWith('.svg')) {
    link.type = 'image/svg+xml'
  }
  link.href = finalHref
}

/**
 * Aplica los colores, título y favicon de la marca al documento.
 */
function applyBrandToDocument(brand) {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.style.setProperty('--brand-primary',       brand.primary_color)
  root.style.setProperty('--brand-primary-hover', brand.primary_hover)
  root.style.setProperty('--brand-primary-rgb',   hexToRgb(brand.primary_color))
  root.style.setProperty('--brand-sidebar-bg',    brand.sidebar_bg)
  root.style.setProperty('--brand-accent',        brand.accent_color)
  if (brand.company_name) document.title = brand.company_name
  applyFavicon(brand.favicon_data_url)
}

// Hidratación inicial: leer del cache antes del primer render para evitar el
// flash de marca por defecto. Aplicamos las CSS vars al document de inmediato.
const INITIAL_BRAND = readCachedBrand()
applyBrandToDocument(INITIAL_BRAND)

const useBrandStore = create((set, get) => ({
  brand: INITIAL_BRAND,
  loaded: false,

  loadBrand: async () => {
    try {
      const res = await api.get('/api/settings/brand')
      const brand = { ...DEFAULT_BRAND, ...(res.data || {}) }
      applyBrandToDocument(brand)
      writeCachedBrand(brand)
      set({ brand, loaded: true })
    } catch {
      // Si falla el fetch mantenemos lo que ya tenemos en memoria/cache.
      set({ loaded: true })
    }
  },

  setBrandLocal: (partial) => {
    const next = { ...get().brand, ...partial }
    applyBrandToDocument(next)
    set({ brand: next })
  },

  saveBrand: async (partial) => {
    const next = { ...get().brand, ...partial }
    await api.put('/api/settings/brand', next)
    applyBrandToDocument(next)
    writeCachedBrand(next)
    set({ brand: next })
    return next
  },
}))

export default useBrandStore
export { DEFAULT_BRAND }
