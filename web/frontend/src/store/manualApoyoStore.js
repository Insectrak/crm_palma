import { create } from 'zustand'

export const useManualApoyoStore = create((set) => ({
  isOpen: false,
  activeTab: 'todos', // 'todos' | 'paso1' | 'paso2' | 'paso3' | 'paso4' | 'paso5' | 'paso6' | 'objeciones'
  prospectoNombre: '',
  asesorNombre: '',
  searchQuery: '',

  openManual: (tab = null) =>
    set({
      isOpen: true,
      ...(tab ? { activeTab: tab } : {}),
    }),

  closeManual: () => set({ isOpen: false }),

  toggleManual: () => set((state) => ({ isOpen: !state.isOpen })),

  setActiveTab: (tab) => set({ activeTab: tab }),

  setProspectoNombre: (name) => set({ prospectoNombre: name }),

  setAsesorNombre: (name) => set({ asesorNombre: name }),

  setSearchQuery: (query) => set({ searchQuery: query }),
}))

export default useManualApoyoStore
