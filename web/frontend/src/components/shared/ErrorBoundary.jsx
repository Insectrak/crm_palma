import React from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'

/**
 * ErrorBoundary — atrapa errores durante render y previene que el árbol
 * completo se desmonte (pantalla en blanco). Muestra un fallback amigable
 * y permite reintentar sin recargar el navegador.
 *
 * Uso:
 *   <ErrorBoundary>
 *     <Layout />
 *   </ErrorBoundary>
 *
 * Con fallback custom:
 *   <ErrorBoundary fallback={(err, reset) => <MiFallback ... />}>
 *     ...
 *   </ErrorBoundary>
 */
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null, info: null }
    this.reset = this.reset.bind(this)
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    this.setState({ info })
    // Log para diagnóstico — visible en DevTools incluso en producción
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary] Componente crasheó:', error)
    if (info?.componentStack) {
      // eslint-disable-next-line no-console
      console.error('[ErrorBoundary] Stack:', info.componentStack)
    }
  }

  reset() {
    this.setState({ error: null, info: null })
  }

  render() {
    const { error } = this.state
    const { children, fallback } = this.props

    if (!error) return children

    if (typeof fallback === 'function') {
      return fallback(error, this.reset)
    }

    return (
      <div className="p-6">
        <div className="max-w-2xl mx-auto rounded-lg border border-red-200 bg-red-50 p-6">
          <div className="flex items-start gap-3">
            <AlertTriangle className="h-6 w-6 text-red-600 flex-shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <h2 className="text-lg font-semibold text-red-900">
                Algo salió mal en esta sección
              </h2>
              <p className="mt-1 text-sm text-red-800">
                Se produjo un error al renderizar esta parte de la aplicación.
                El resto del CRM sigue funcionando — puedes reintentar aquí o
                navegar a otra página desde el menú lateral.
              </p>
              {error?.message && (
                <pre className="mt-3 text-xs bg-white border border-red-200 rounded p-2 text-red-900 overflow-x-auto whitespace-pre-wrap break-words">
                  {error.message}
                </pre>
              )}
              <div className="mt-4 flex gap-2">
                <button
                  type="button"
                  onClick={this.reset}
                  className="inline-flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-md bg-red-600 text-white hover:bg-red-700 transition"
                >
                  <RefreshCw className="h-4 w-4" />
                  Reintentar
                </button>
                <button
                  type="button"
                  onClick={() => window.location.reload()}
                  className="inline-flex items-center gap-2 px-3 py-1.5 text-sm font-medium rounded-md border border-red-300 text-red-800 hover:bg-red-100 transition"
                >
                  Recargar página
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    )
  }
}
