import { create } from 'zustand'
import api from '@/lib/api'

/**
 * Store central para el módulo CRM.
 * Maneja catálogos (estados, fuentes) que se usan en múltiples páginas.
 */
const useCrmStore = create((set, get) => ({
  // Catálogos cargados una sola vez al iniciar
  estados: [],
  fuentes: [],
  calidades: [],
  catalogsLoaded: false,
  isLoadingCatalogs: false,

  /**
   * Carga estados, fuentes y calidades desde la API.
   * Idempotente: si ya están cargados, no hace nada.
   */
  loadCatalogs: async () => {
    if (get().catalogsLoaded || get().isLoadingCatalogs) return
    set({ isLoadingCatalogs: true })
    try {
      const [estadosRes, fuentesRes, calidadesRes] = await Promise.all([
        api.get('/api/estados'),
        api.get('/api/fuentes'),
        api.get('/api/calidad').catch(() => ({ data: [] })),
      ])
      set({
        estados: estadosRes.data,
        fuentes: fuentesRes.data,
        calidades: calidadesRes.data || [],
        catalogsLoaded: true,
        isLoadingCatalogs: false,
      })
    } catch {
      set({ isLoadingCatalogs: false })
    }
  },

  /**
   * Limpia los catálogos (útil al hacer logout).
   */
  clearCatalogs: () => set({ estados: [], fuentes: [], calidades: [], catalogsLoaded: false }),
}))

export default useCrmStore
