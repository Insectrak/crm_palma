import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'
import { fileURLToPath } from 'url'
import { execSync } from 'child_process'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// Captura el commit hash y la fecha de build para mostrar en
// Configuración → General. Permite verificar qué build esta corriendo en
// cada ambiente (prod vs lab) cuando algo no anda como esperaba.
//
// Estrategia 3-niveles (mas robusta vs distintos build environments):
//   1. Env var VITE_BUILD_COMMIT (build arg de Docker/CI). Para EasyPanel
//      en el futuro: setear como Variable de Entorno del app frontend.
//   2. git rev-parse en el cwd. Funciona en `npm run build` local.
//   3. Vacio. La UI esconde el prefijo "<hash> ·" cuando no hay hash —
//      evita mostrar "unknown" feo al usuario.
function gitCommit() {
  if (process.env.VITE_BUILD_COMMIT) {
    return process.env.VITE_BUILD_COMMIT.trim()
  }
  try {
    return execSync('git rev-parse --short HEAD', { encoding: 'utf-8' }).trim()
  } catch {
    return ''
  }
}

// Configuración de Vite con Tailwind v4 y alias @ para imports
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  define: {
    __BUILD_COMMIT__: JSON.stringify(gitCommit()),
    __BUILD_TIME__:   JSON.stringify(new Date().toISOString()),
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
  },
})
