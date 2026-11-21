import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { initSentry } from './lib/sentry'

// V070.99 — Inicializar Sentry ANTES de createRoot para capturar errores
// del propio mount. Si VITE_SENTRY_DSN no esta seteada, es no-op.
initSentry()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
