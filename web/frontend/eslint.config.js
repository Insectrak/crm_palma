import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  // Config files (vite.config.js, etc.) corren en Node, no en browser.
  // Sin esto, process/require/__dirname disparan no-undef.
  {
    files: ['vite.config.js', 'eslint.config.js', '*.config.js'],
    languageOptions: {
      globals: { ...globals.node },
    },
  },
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: {
        ...globals.browser,
        // Vite inyecta estas constantes via `define` en vite.config.js
        // para mostrar el build commit + fecha en Configuración → General.
        __BUILD_COMMIT__: 'readonly',
        __BUILD_TIME__:   'readonly',
      },
      parserOptions: {
        ecmaVersion: 'latest',
        ecmaFeatures: { jsx: true },
        sourceType: 'module',
      },
    },
    rules: {
      // Ignora vars/args/destructurados que empiezan con mayúscula o _ (componentes + placeholders)
      'no-unused-vars': ['error', {
        varsIgnorePattern: '^[A-Z_]',
        argsIgnorePattern: '^[A-Z_]',
        destructuredArrayIgnorePattern: '^[A-Z_]',
        ignoreRestSiblings: true,
      }],
      // Permitir re-exportar constantes junto a componentes (cva variants)
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      // Warnings de exhaustive-deps son informativos, no deben bloquear el CI
      'react-hooks/exhaustive-deps': 'warn',
      // Reglas estrictas nuevas de react-hooks (v6/v7): degradadas a warning para no
      // bloquear el CI en patrones legacy válidos (setState diferido en fetches,
      // reseteos al cambiar props, Date.now() en paneles de diagnostico, etc.).
      // Se pueden endurecer gradualmente.
      'react-hooks/set-state-in-effect': 'warn',
      'react-hooks/immutability': 'warn',
      'react-hooks/purity': 'warn',
      'react-hooks/refs': 'warn',
      'react-hooks/static-components': 'warn',
      'react-hooks/preserve-manual-memoization': 'warn',
    },
  },
])
