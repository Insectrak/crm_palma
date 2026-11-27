import { useState, useMemo, useEffect, useRef } from 'react'
import {
  PhoneCall,
  X,
  Copy,
  Check,
  Search,
  BookOpen,
  Sparkles,
  MapPin,
  ShieldAlert,
  HelpCircle,
  Users,
  Target,
  CheckCircle2,
  Building2,
  Video,
  User,
  RotateCcw,
  ExternalLink,
  Link2,
  Globe,
  Map,
} from 'lucide-react'
import useAuthStore from '@/store/authStore'
import useBrandStore from '@/store/brandStore'
import useManualApoyoStore from '@/store/manualApoyoStore'
import { FICHA_TECNICA_FIELDS } from '@/lib/fichaTecnica'

// Helper para copiar texto al portapapeles con feedback visual
function useCopy() {
  const [copiedKey, setCopiedKey] = useState(null)
  const copyText = (key, text) => {
    if (navigator?.clipboard?.writeText) {
      navigator.clipboard.writeText(text)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = text
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
    }
    setCopiedKey(key)
    setTimeout(() => {
      setCopiedKey((curr) => (curr === key ? null : curr))
    }, 2000)
  }
  return { copiedKey, copyText }
}

export default function ManualApoyoDrawer() {
  const { user } = useAuthStore()
  const brand = useBrandStore((s) => s.brand)
  const {
    isOpen,
    activeTab,
    prospectoNombre,
    asesorNombre,
    searchQuery,
    closeManual,
    toggleManual,
    setActiveTab,
    setProspectoNombre,
    setAsesorNombre,
    setSearchQuery,
  } = useManualApoyoStore()

  const { copiedKey, copyText } = useCopy()
  const [miniPitchSubTab, setMiniPitchSubTab] = useState('lote') // 'lote' | 'objetivo'
  const searchInputRef = useRef(null)
  const contentContainerRef = useRef(null)

  const handleSelectTab = (tabKey) => {
    setActiveTab(tabKey)
    if (contentContainerRef.current) {
      contentContainerRef.current.scrollTo({ top: 0, behavior: 'smooth' })
    }
  }

  const brandName = brand?.company_name || 'Palma del Río'
  const brandLegalName = brand?.legal_name || 'Palma del Río Inmobiliaria'

  // Nombre por defecto del asesor tomado del perfil autenticado
  const defaultAsesor = useMemo(() => {
    if (asesorNombre?.trim()) return asesorNombre.trim()
    const name = [user?.first_name, user?.last_name].filter(Boolean).join(' ')
    return name || 'Asesor Comercial'
  }, [asesorNombre, user])

  const prospecto = prospectoNombre?.trim() || 'Andrea'

  // Listener para atajo de teclado: Alt + M para abrir/cerrar, Esc para cerrar
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.altKey && (e.key === 'm' || e.key === 'M')) {
        e.preventDefault()
        toggleManual()
      } else if (e.key === 'Escape' && isOpen) {
        closeManual()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, toggleManual, closeManual])

  // Mini Pitches por tipo de lote / atributo del proyecto
  const miniPitchesLote = useMemo(() => [
    {
      id: 'lote-residencial',
      categoria: 'Lote residencial / vivienda',
      titulo: 'Construir tu hogar en zona tranquila y planificada',
      guion: `“¡Excelente elección, ${prospecto}! Nuestros lotes residenciales están pensados para familias que buscan tranquilidad, áreas verdes y espacios bien distribuidos para construir su casa a su gusto. En la visita te muestro las ubicaciones disponibles en plano y cuál se adapta mejor a lo que imaginas.”`,
    },
    {
      id: 'lote-inversion',
      categoria: 'Lote de inversión / plusvalía',
      titulo: 'Valorización progresiva y respaldo patrimonial',
      guion: `“¡Muy buena visión! Invertir en tierra es una de las decisiones más seguras porque tu capital queda respaldado por un bien tangible que gana plusvalía conforme avanza el desarrollo y consolidación de la zona. Podemos revisar qué lotes estratégicos tienen mayor proyección de valorización.”`,
    },
    {
      id: 'lote-comercial',
      categoria: 'Lote en esquina / avenida o comercial',
      titulo: 'Alta visibilidad para negocio o renta futura',
      guion: `“¡Claro que sí! Contamos con ubicaciones estratégicas frente a vías principales o en esquina, ideales si estás pensando en combinar vivienda con negocio o generar ingresos por alquiler más adelante. Revisemos qué opciones siguen libres en esta etapa.”`,
    },
    {
      id: 'lote-financiamiento',
      categoria: 'Financiamiento directo y cuotas',
      titulo: 'Facilidades accesibles sin trabas bancarias',
      guion: `“Justamente buscamos que adquirir tu lote sea alcanzable. Manejamos facilidades con financiamiento directo y cuotas cómodas para que puedas separar tu lote hoy mismo con una inicial accesible y sin trámites bancarios engorrosos.”`,
    },
    {
      id: 'lote-seguridad',
      categoria: 'Documentación y respaldo legal',
      titulo: 'Transparencia jurídica desde el primer día',
      guion: `“Entiendo totalmente tu prioridad por la seguridad legal. En ${brandLegalName} te mostramos toda la documentación del proyecto con total transparencia para que tomes tu decisión con la tranquilidad de que tu inversión está protegida.”`,
    },
  ], [prospecto, brandLegalName])

  // Mini Pitches por objetivo o situación del prospecto
  const miniPitchesObjetivo = useMemo(() => [
    {
      id: 'obj-familia',
      categoria: 'Casa propia / familia',
      titulo: 'Patrimonio seguro y calidad de vida para los tuyos',
      guion: `“¡Qué gran paso para ti y tu familia! Tener un terreno propio significa dejar de depender de alquileres y construir un patrimonio que quedará para tus hijos. Queremos acompañarte a elegir el lote ideal según el tamaño que necesitan.”`,
    },
    {
      id: 'obj-inversionista',
      categoria: 'Compra como inversión',
      titulo: 'Aprovechar precios de etapa actual antes de revalorización',
      guion: `“Cuando uno compra para invertir, el momento de entrada hace toda la diferencia. Asegurar un lote hoy te permite aprovechar los precios y campañas vigentes antes de los siguientes incrementos por avance del proyecto.”`,
    },
    {
      id: 'obj-fuera-arequipa',
      categoria: 'Cliente de otra ciudad / extranjero',
      titulo: 'Asesoría virtual con planos, ubicación GPS y video',
      guion: `“¡No hay ningún problema si estás fuera de Arequipa! Atendemos a muchos clientes de otros departamentos y del extranjero mediante videollamada por Zoom o Meet, mostrándote el plano en vivo, la ubicación exacta, fotos y videos del proyecto.”`,
    },
    {
      id: 'obj-cotizando',
      categoria: 'Está cotizando otros proyectos',
      titulo: 'Comparar ubicación, metraje real y facilidades con criterio',
      guion: `“¡Qué bueno que estés comparando opciones! Así tomas una decisión bien informada. Lo ideal es que conozcas nuestro proyecto en persona o en una reunión breve para comparar metraje real, proyección de la zona, documentación y facilidad de cuotas.”`,
    },
    {
      id: 'obj-plazo',
      categoria: 'Quiere comprar pronto o evaluar campaña',
      titulo: 'Asegurar ubicación disponible antes que se separe',
      guion: `“Como los lotes con mejor ubicación frente a parque o esquina suelen separarse primero, lo más recomendable es revisar hoy mismo la disponibilidad actualizada para que no pierdas la opción que más te conviene.”`,
    },
  ], [])

  // Objeciones frecuentes en ventas inmobiliarias
  const objeciones = useMemo(() => [
    {
      id: 'obj-tiempo',
      titulo: '“No tengo tiempo para ir al proyecto o reunirme”',
      subtitulo: 'Técnica de empatía y propuesta flexible (visita corta o reunión virtual de 20 min)',
      guion: `“¡${prospecto}, te entiendo perfectamente! Hoy todos andamos con el tiempo justo entre el trabajo y la familia.
Precisamente por eso quiero ahorrarte vueltas: en una reunión breve de 20 minutos —ya sea en videollamada o coordinando una visita rápida al proyecto— te muestro directo los lotes disponibles según el tipo y presupuesto que buscas.
Hagamos algo práctico: ¿te queda mejor hoy al final de tu jornada o este fin de semana en la mañana para hacer la visita o videollamada?
¡Perfecto! Dejemos separado ese espacio y te envío los detalles para aprovechar al máximo tu tiempo.”`,
    },
    {
      id: 'obj-whatsapp',
      titulo: '“Mándame toda la información y precios por WhatsApp”',
      subtitulo: 'Evitar enviar precios aislados sin explicar ubicación, metraje y facilidades',
      guion: `“¡Claro que sí, ${prospecto}! Con gusto te comparto la ubicación y el resumen por WhatsApp.
Pero te soy sincero: enviarte solo una lista de precios sin explicarte el plano puede confundir más de lo que ayuda, porque el valor cambia según el metraje, si da a parque, avenida o esquina, y según la modalidad de pago o inicial que prefieras.
Por eso prefiero dedicarte 15 a 20 minutos —en visita al proyecto o por videollamada— para mostrarte en plano qué lotes calzan exactamente con lo que buscas y las facilidades de cuotas vigentes.
¿A qué hora de hoy te queda cómodo conversar o coordinar tu visita?”`,
    },
    {
      id: 'obj-precio',
      titulo: '“Dime de frente cuánto cuesta el lote”',
      subtitulo: 'Enmarcar el precio según metraje, ubicación y capacidad de inicial/cuota',
      guion: `“¡Por supuesto, ${prospecto}! Justamente el precio depende del tipo de lote, el metraje y la ubicación dentro del proyecto.
Para darte una cifra exacta y no un aproximado genérico, cuéntame:
1. ¿Qué metraje o tipo de lote estás buscando (vivienda o inversión)?
2. ¿Estás evaluando comprarlo al contado o con financiamiento directo en cuotas?
[Escuchar respuesta]
¡Excelente! Con eso claro, te muestro en nuestra visita guiada —o en reunión por Zoom— las manzanas disponibles que se ajustan a tu presupuesto, la inicial desde la que puedes separar y cómo quedan las cuotas.”`,
    },
  ], [prospecto])

  // Filtrado reactivo por texto de búsqueda
  const q = searchQuery.toLowerCase().trim()
  const matchText = (text) => (!q ? true : (text || '').toLowerCase().includes(q))

  const showPaso1 = (activeTab === 'todos' || activeTab === 'paso1') &&
    (matchText(`apertura presentacion ${brandName} ${brandLegalName} lotes proyecto inmobiliario redes sociales`) || matchText(prospecto))

  const showPaso2 = (activeTab === 'todos' || activeTab === 'paso2') &&
    (matchText('diagnostico perfilamiento preguntas no negociable arequipa distrito lote inversion cotizando proyectos') ||
      FICHA_TECNICA_FIELDS.some((f) => matchText(f.label) || matchText(f.pregunta) || matchText(f.placeholder)))

  const showPaso3 = (activeTab === 'todos' || activeTab === 'paso3') &&
    (miniPitchesLote.some((p) => matchText(p.categoria) || matchText(p.titulo) || matchText(p.guion)) ||
      miniPitchesObjetivo.some((p) => matchText(p.categoria) || matchText(p.titulo) || matchText(p.guion)))

  const showPaso4 = (activeTab === 'todos' || activeTab === 'paso4') &&
    (matchText('cita visita proyecto arequipa oficina planos zoom meet videollamada terreno lotes'))

  const showPaso5 = (activeTab === 'todos' || activeTab === 'paso5') &&
    (matchText('autonomia decision economica familiar conyuge pareja socio separacion lote'))

  const showPaso6 = (activeTab === 'todos' || activeTab === 'paso6') &&
    (matchText('confirmacion asentamiento visita proyecto oficina separacion reserva plano whatsapp'))

  const showObjeciones = (activeTab === 'todos' || activeTab === 'objeciones') &&
    objeciones.some((o) => matchText(o.titulo) || matchText(o.subtitulo) || matchText(o.guion))

  const linksInteresGrupos = useMemo(() => [
    {
      id: 'planos',
      titulo: 'Planos de los Lotes',
      badge: 'Planos',
      items: [
        { id: 'lnk-palmeras', nombre: 'Puerto Palmeras', url: 'https://palmadelrioinmobiliaria.com/app_puertopalmeras/' },
        { id: 'lnk-illary', nombre: 'Illary', url: 'https://palmadelrioinmobiliaria.com/app_illary/' },
        { id: 'lnk-ensenada', nombre: 'La Ensenada', url: 'https://palmadelrioinmobiliaria.com/pr_laensenadaa/' },
        { id: 'lnk-paracas', nombre: 'Paracas', url: 'https://palmadelrioinmobiliaria.com/pr_paracas/' },
        { id: 'lnk-vallarta', nombre: 'Puerto Vallarta', url: 'https://palmadelrioinmobiliaria.com/pto.vallarta/' },
        { id: 'lnk-hacienda', nombre: 'Hacienda del Mar', url: 'https://palmadelrioinmobiliaria.com/pr_haciendadelmar/' },
        { id: 'lnk-comercial', nombre: 'Proyecto Comercial', url: 'https://palmadelrioinmobiliaria.com/pr_comercial/' },
      ],
    },
    {
      id: 'tours',
      titulo: 'Tours Virtuales de Proyectos',
      badge: 'Tour 360°',
      items: [
        { id: 'lnk-tour-madero', nombre: 'Tour Puerto Madero', url: 'https://palmadelrioinmobiliaria.com/tourpuertomadero/index.html' },
        { id: 'lnk-tour-illary', nombre: 'Tour Illary', url: 'https://palmadelrioinmobiliaria.com/tourillary/index.htm' },
      ],
    },
    {
      id: 'web',
      titulo: 'Página Principal',
      badge: 'Web Oficial',
      items: [
        { id: 'lnk-web', nombre: 'Palma del Río Inmobiliaria', url: 'https://palmadelrioinmobiliaria.com/' },
      ],
    },
    {
      id: 'redes',
      titulo: 'Redes Sociales Oficiales',
      badge: 'Redes Sociales',
      items: [
        { id: 'lnk-tiktok', nombre: 'TikTok', url: 'https://www.tiktok.com/@palmadelrioinmobiliaria' },
        { id: 'lnk-facebook', nombre: 'Facebook', url: 'https://www.facebook.com/PalmaDelRioInmobiliaria' },
        { id: 'lnk-instagram', nombre: 'Instagram', url: 'https://www.instagram.com/palmadelrio.inmobiliaria/' },
      ],
    },
  ], [])

  const filteredLinksGrupos = useMemo(() => (
    linksInteresGrupos
      .map((g) => ({
        ...g,
        items: g.items.filter(
          (it) => matchText(g.titulo) || matchText(g.badge) || matchText(it.nombre) || matchText(it.url),
        ),
      }))
      .filter((g) => g.items.length > 0)
  ), [linksInteresGrupos, q])

  const showLinks = (activeTab === 'todos' || activeTab === 'links') && filteredLinksGrupos.length > 0

  const tabs = [
    { key: 'todos', label: 'Todos' },
    { key: 'paso1', label: '1. Apertura' },
    { key: 'paso2', label: '2. Perfilamiento' },
    { key: 'paso3', label: '3. Mini Pitch' },
    { key: 'paso4', label: '4. Visitas y Citas' },
    { key: 'paso5', label: '5. Decisión' },
    { key: 'paso6', label: '6. Confirmación' },
    { key: 'objeciones', label: 'Objeciones (3)' },
    { key: 'links', label: 'Links de interés (13)' },
  ]

  return (
    <>
      {/* ─────────────────────────────────────────────────────────────
          BOTÓN FLOTANTE EN LA PARTE DERECHA DE LA PLATAFORMA (#1F1D5C)
          ───────────────────────────────────────────────────────────── */}
      <div className="fixed right-0 top-1/2 -translate-y-1/2 z-40 select-none">
        <button
          type="button"
          onClick={toggleManual}
          title="Manual de Guiones Comerciales (Alt+M)"
          aria-label="Abrir manual de guiones comerciales"
          style={{ backgroundColor: isOpen ? '#161445' : '#1F1D5C' }}
          className={`flex items-center gap-2 pl-2.5 pr-2 py-3.5 rounded-l-2xl border-y border-l shadow-2xl transition-all duration-200 cursor-pointer group text-white border-indigo-300/40 ${
            isOpen ? 'translate-x-1' : 'hover:-translate-x-1 hover:brightness-110'
          }`}
        >
          <div className="relative flex items-center justify-center">
            <PhoneCall size={18} className="text-white group-hover:scale-110 transition-transform" />
            <span className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full bg-emerald-400 ring-2 ring-[#1F1D5C] animate-pulse" />
          </div>
          <span className="[writing-mode:vertical-rl] rotate-180 text-[11px] font-bold tracking-wider uppercase">
            Manual de Guiones
          </span>
        </button>
      </div>

      {/* BACKDROP OVERLAY */}
      {isOpen && (
        <div
          onClick={closeManual}
          className="fixed inset-0 bg-slate-950/60 backdrop-blur-xs z-50 transition-opacity animate-in fade-in duration-200"
          aria-hidden="true"
        />
      )}

      {/* DRAWER / PANEL DESPLEGABLE DESDE LA DERECHA */}
      <aside
        className={`fixed inset-y-0 right-0 z-50 flex flex-col w-full sm:w-[580px] md:w-[680px] bg-white dark:bg-[#0f1624] text-slate-900 dark:text-slate-100 shadow-2xl border-l border-slate-200 dark:border-slate-800 transform transition-transform duration-300 ease-out ${
          isOpen ? 'translate-x-0' : 'translate-x-full'
        }`}
        aria-label="Manual de guiones comerciales inmobiliarios"
        role="dialog"
        aria-modal="true"
      >
        {/* HEADER DEL MANUAL */}
        <div className="relative px-5 py-4 border-b border-slate-200 dark:border-slate-800 bg-slate-50/80 dark:bg-[#131d30]/90 backdrop-blur-sm shrink-0">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <div
                style={{ backgroundColor: '#1F1D5C' }}
                className="w-9 h-9 rounded-xl text-white flex items-center justify-center shadow-md shadow-[#1F1D5C]/30 shrink-0"
              >
                <BookOpen size={18} />
              </div>
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <span
                    className="text-[10px] font-bold tracking-wider uppercase px-2 py-0.5 rounded-full text-[#1F1D5C] dark:text-indigo-300 bg-[#1F1D5C]/10 dark:bg-[#1F1D5C]/40 border border-[#1F1D5C]/30 dark:border-indigo-400/30"
                  >
                    {brandLegalName}
                  </span>
                  <span className="text-[10px] font-medium text-slate-500 dark:text-slate-400">
                    Alt + M
                  </span>
                </div>
                <h2 className="text-base font-bold text-slate-900 dark:text-white leading-tight mt-0.5">
                  Anexo de Guiones · Llamada Inmobiliaria
                </h2>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Gestión Leads TikTok · Instagram · Facebook · Web · Referidos
                </p>
              </div>
            </div>

            <button
              type="button"
              onClick={closeManual}
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-200/60 dark:hover:bg-slate-800 transition-colors cursor-pointer"
              title="Cerrar (Esc)"
            >
              <X size={20} />
            </button>
          </div>

          {/* BARRA DE PERSONALIZACIÓN DINÁMICA (PROSPECTO Y ASESOR) */}
          <div className="mt-3.5 pt-3 border-t border-slate-200/80 dark:border-slate-800/80 grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
            <div className="flex items-center gap-2 bg-white dark:bg-[#0c121d] px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-800">
              <User size={13} style={{ color: '#1F1D5C' }} className="shrink-0" />
              <span className="text-slate-500 font-medium shrink-0">Prospecto:</span>
              <input
                type="text"
                value={prospectoNombre}
                onChange={(e) => setProspectoNombre(e.target.value)}
                placeholder="Andrea (ej. Carlos, María)"
                className="w-full bg-transparent border-0 p-0 text-slate-800 dark:text-slate-100 focus:outline-none focus:ring-0 text-xs font-semibold"
              />
              {prospectoNombre && (
                <button
                  type="button"
                  onClick={() => setProspectoNombre('')}
                  className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                  title="Restablecer"
                >
                  <RotateCcw size={11} />
                </button>
              )}
            </div>

            <div className="flex items-center gap-2 bg-white dark:bg-[#0c121d] px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-800">
              <Sparkles size={13} className="text-amber-500 shrink-0" />
              <span className="text-slate-500 font-medium shrink-0">Asesor:</span>
              <input
                type="text"
                value={asesorNombre}
                onChange={(e) => setAsesorNombre(e.target.value)}
                placeholder={defaultAsesor}
                className="w-full bg-transparent border-0 p-0 text-slate-800 dark:text-slate-100 focus:outline-none focus:ring-0 text-xs font-semibold"
              />
            </div>
          </div>

          {/* BARRA DE BÚSQUEDA */}
          <div className="mt-2.5 relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              ref={searchInputRef}
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Buscar en guiones (ej: lote, visita, precio, inversión, separación, zoom)..."
              className="w-full pl-8 pr-8 py-1.5 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-[#0c121d] text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-[#1F1D5C]"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
              >
                <X size={12} />
              </button>
            )}
          </div>

          {/* PESTAÑAS DE NAVEGACIÓN RÁPIDA */}
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5 pt-0.5">
            {tabs.map((tab) => {
              const active = activeTab === tab.key
              return (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => handleSelectTab(tab.key)}
                  style={active ? { backgroundColor: '#1F1D5C' } : {}}
                  className={`text-xs px-2.5 py-1 rounded-md font-medium whitespace-nowrap transition-all cursor-pointer flex items-center gap-1.5 ${
                    active
                      ? 'text-white shadow-xs font-semibold scale-[1.02]'
                      : 'bg-slate-200/70 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300'
                  }`}
                >
                  <span>{tab.label}</span>
                </button>
              )
            })}
          </div>
        </div>

        {/* CONTENIDO CON SCROLL */}
        <div ref={contentContainerRef} className="flex-1 overflow-y-scroll wa-scrollbar p-5 space-y-6">

          {/* PASO 1: APERTURA Y PRESENTACIÓN */}
          {showPaso1 && (
            <section className="space-y-3 rounded-xl p-4 bg-slate-50 dark:bg-[#131d30] border border-slate-200 dark:border-slate-800 shadow-xs">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span
                    style={{ backgroundColor: '#1F1D5C' }}
                    className="w-6 h-6 rounded-lg text-white text-xs font-bold flex items-center justify-center shadow-xs"
                  >
                    1
                  </span>
                  <h3 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wide">
                    Paso 1: Apertura y Presentación
                  </h3>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    copyText(
                      'p1',
                      `“Hola, ¿${prospecto}?, ¿cómo estás?\nSoy ${defaultAsesor} de ${brandLegalName}. Te tenemos registrado en nuestro sistema porque nos dejaste tus datos a través de nuestras redes sociales interesado en nuestros lotes y proyectos inmobiliarios, ¿correcto?\n¡Qué bueno!”`
                    )
                  }
                  className="flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-white dark:bg-[#0c121d] border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:text-[#1F1D5C] dark:hover:text-indigo-300 transition-colors shadow-xs"
                >
                  {copiedKey === 'p1' ? <Check size={12} className="text-emerald-500" /> : <Copy size={12} />}
                  <span>{copiedKey === 'p1' ? '¡Copiado!' : 'Copiar'}</span>
                </button>
              </div>

              <div
                style={{ borderLeftColor: '#1F1D5C' }}
                className="relative pl-3 border-l-3 space-y-2 text-sm leading-relaxed text-slate-800 dark:text-slate-200 bg-white dark:bg-[#0c121d] p-3 rounded-r-lg border-y border-r border-slate-200 dark:border-slate-800"
              >
                <p style={{ color: '#1F1D5C' }} className="font-semibold text-xs">
                  Asesor ({defaultAsesor}):
                </p>
                <p>“Hola, ¿<span className="font-bold underline decoration-[#1F1D5C]">{prospecto}</span>?, ¿cómo estás?</p>
                <p>
                  Soy <span className="font-bold">{defaultAsesor}</span> de {brandLegalName}. Te tenemos registrado en nuestro sistema porque nos dejaste tus datos a través de nuestras redes sociales interesado en nuestros lotes y proyectos inmobiliarios, ¿correcto?
                </p>
                <p className="font-medium text-emerald-600 dark:text-emerald-400">¡Qué bueno!”</p>
              </div>
            </section>
          )}

          {/* PASO 2: PERFILAMIENTO - PREGUNTAS CLAVE DE LA FICHA TÉCNICA */}
          {showPaso2 && (
            <section className="space-y-3 rounded-xl p-4 bg-slate-50 dark:bg-[#131d30] border border-slate-200 dark:border-slate-800 shadow-xs">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span
                    style={{ backgroundColor: '#1F1D5C' }}
                    className="w-6 h-6 rounded-lg text-white text-xs font-bold flex items-center justify-center shadow-xs"
                  >
                    2
                  </span>
                  <h3 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wide">
                    Paso 2: Perfilamiento - Ficha Técnica ({FICHA_TECNICA_FIELDS.length} Preguntas)
                  </h3>
                </div>
                <span className="text-[11px] font-semibold text-amber-700 dark:text-amber-300 bg-amber-100 dark:bg-amber-950/60 px-2 py-0.5 rounded-full border border-amber-200 dark:border-amber-800">
                  Obligatorias
                </span>
              </div>

              <div className="bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-900/60 p-2.5 rounded-lg text-xs text-amber-900 dark:text-amber-200 flex items-start gap-2">
                <Target size={14} className="text-amber-600 shrink-0 mt-0.5" />
                <p>
                  <span className="font-bold">Objetivo:</span> identificar qué tipo de lote busca el cliente, su ubicación, si compara proyectos y en qué plazo planea adquirirlo (sincronizado con la Ficha Técnica del lead).
                </p>
              </div>

              <div className="grid grid-cols-1 gap-2 pt-1 text-xs">
                {FICHA_TECNICA_FIELDS.map((item, idx) => (
                  <div
                    key={item.key}
                    className="p-2.5 rounded-lg bg-white dark:bg-[#0c121d] border border-slate-200 dark:border-slate-800 flex items-start justify-between gap-2 hover:border-[#1F1D5C]/50 transition-colors"
                  >
                    <div className="space-y-1">
                      <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">
                        {idx + 1}. {item.label}
                      </span>
                      <p className="text-slate-800 dark:text-slate-200 font-medium text-xs leading-snug">
                        {item.pregunta}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => copyText(`p2-${item.key}`, item.pregunta)}
                      className="p-1 rounded text-slate-400 hover:text-[#1F1D5C] transition-colors shrink-0"
                      title="Copiar pregunta"
                    >
                      {copiedKey === `p2-${item.key}` ? <Check size={12} className="text-emerald-500" /> : <Copy size={12} />}
                    </button>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* PASO 3: MINI PITCH INMOBILIARIO */}
          {showPaso3 && (
            <section className="space-y-3 rounded-xl p-4 bg-slate-50 dark:bg-[#131d30] border border-slate-200 dark:border-slate-800 shadow-xs">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <div className="flex items-center gap-2">
                  <span
                    style={{ backgroundColor: '#1F1D5C' }}
                    className="w-6 h-6 rounded-lg text-white text-xs font-bold flex items-center justify-center shadow-xs"
                  >
                    3
                  </span>
                  <h3 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wide">
                    Paso 3: Mini Pitch de Valor
                  </h3>
                </div>

                <div className="flex items-center p-0.5 rounded-lg bg-slate-200 dark:bg-slate-800 text-xs">
                  <button
                    type="button"
                    onClick={() => setMiniPitchSubTab('lote')}
                    className={`px-2.5 py-1 rounded-md font-medium transition-colors ${
                      miniPitchSubTab === 'lote'
                        ? 'bg-white dark:bg-[#0c121d] text-[#1F1D5C] dark:text-indigo-300 shadow-xs'
                        : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
                    }`}
                  >
                    Por Tipo / Beneficio ({miniPitchesLote.length})
                  </button>
                  <button
                    type="button"
                    onClick={() => setMiniPitchSubTab('objetivo')}
                    className={`px-2.5 py-1 rounded-md font-medium transition-colors ${
                      miniPitchSubTab === 'objetivo'
                        ? 'bg-white dark:bg-[#0c121d] text-[#1F1D5C] dark:text-indigo-300 shadow-xs'
                        : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
                    }`}
                  >
                    Por Objetivo del Cliente ({miniPitchesObjetivo.length})
                  </button>
                </div>
              </div>

              <div className="space-y-2.5 pt-1">
                {(miniPitchSubTab === 'lote' ? miniPitchesLote : miniPitchesObjetivo)
                  .filter((p) => matchText(p.categoria) || matchText(p.guion) || matchText(p.titulo))
                  .map((pitch) => (
                    <div
                      key={pitch.id}
                      className="p-3 rounded-lg bg-white dark:bg-[#0c121d] border border-slate-200 dark:border-slate-800 space-y-2 hover:border-[#1F1D5C]/40 transition-all"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <span
                            style={{ color: '#1F1D5C' }}
                            className="inline-block px-2 py-0.5 rounded text-[11px] font-bold bg-[#1F1D5C]/10 dark:bg-[#1F1D5C]/30 border border-[#1F1D5C]/25 dark:border-indigo-400/30"
                          >
                            {pitch.categoria}
                          </span>
                          <h4 className="text-xs font-semibold text-slate-700 dark:text-slate-300 mt-1">
                            {pitch.titulo}
                          </h4>
                        </div>
                        <button
                          type="button"
                          onClick={() => copyText(pitch.id, pitch.guion)}
                          className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 transition-colors shrink-0"
                          title="Copiar guion"
                        >
                          {copiedKey === pitch.id ? <Check size={11} className="text-emerald-500" /> : <Copy size={11} />}
                          <span>{copiedKey === pitch.id ? '¡Copiado!' : 'Copiar'}</span>
                        </button>
                      </div>

                      <p
                        style={{ borderLeftColor: '#1F1D5C' }}
                        className="text-xs text-slate-700 dark:text-slate-300 leading-relaxed italic border-l-2 pl-2.5"
                      >
                        {pitch.guion}
                      </p>
                    </div>
                  ))}
              </div>
            </section>
          )}

          {/* PASO 4: GENERACIÓN DE VISITA AL PROYECTO / CITA */}
          {showPaso4 && (
            <section className="space-y-3 rounded-xl p-4 bg-slate-50 dark:bg-[#131d30] border border-slate-200 dark:border-slate-800 shadow-xs">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span
                    style={{ backgroundColor: '#1F1D5C' }}
                    className="w-6 h-6 rounded-lg text-white text-xs font-bold flex items-center justify-center shadow-xs"
                  >
                    4
                  </span>
                  <h3 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wide">
                    Paso 4: Agendamiento de Visita o Cita
                  </h3>
                </div>
                <span className="text-[11px] font-semibold text-emerald-700 dark:text-emerald-300 bg-emerald-100 dark:bg-emerald-950/60 px-2 py-0.5 rounded-full border border-emerald-200 dark:border-emerald-800">
                  Cierre de visita / cita
                </span>
              </div>

              <div className="bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-900/60 p-2.5 rounded-lg text-xs text-emerald-900 dark:text-emerald-200 flex items-start gap-2">
                <Target size={14} className="text-emerald-600 shrink-0 mt-0.5" />
                <p>
                  <span className="font-bold">Objetivo:</span> convertir el interés en una <strong className="underline">visita guiada al proyecto</strong> (prioridad para clientes en Arequipa) o en una cita en oficina / virtual.
                </p>
              </div>

              {/* OPCIÓN 1: VISITA AL PROYECTO */}
              <div
                style={{ borderColor: 'rgba(31, 29, 92, 0.35)' }}
                className="p-3.5 rounded-lg bg-white dark:bg-[#0c121d] border-2 space-y-2"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <MapPin size={16} style={{ color: '#1F1D5C' }} />
                    <span
                      style={{ color: '#1F1D5C' }}
                      className="text-xs font-bold uppercase tracking-wide"
                    >
                      1. Primera opción: Visita guiada al proyecto (Prioridad 1)
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      copyText(
                        'p4-visita',
                        `“${prospecto}, por teléfono es difícil que aprecies la ubicación exacta, las vistas y los lotes disponibles. Por eso lo mejor es coordinar una visita guiada al proyecto para que veas el terreno en persona, recorras las manzanas libres y revisemos juntos precios y facilidades de pago.\n¿Te queda mejor visitarnos hoy por la tarde o mañana en la mañana? ¿Irás por tu cuenta o coordinamos punto de encuentro?”`
                      )
                    }
                    style={{ color: '#1F1D5C' }}
                    className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-[#1F1D5C]/10 hover:bg-[#1F1D5C]/20 dark:bg-[#1F1D5C]/30 dark:hover:bg-[#1F1D5C]/45 transition-colors"
                  >
                    {copiedKey === 'p4-visita' ? <Check size={11} className="text-emerald-500" /> : <Copy size={11} />}
                    <span>{copiedKey === 'p4-visita' ? '¡Copiado!' : 'Copiar'}</span>
                  </button>
                </div>
                <div
                  style={{ borderLeftColor: '#1F1D5C' }}
                  className="text-xs text-slate-700 dark:text-slate-300 leading-relaxed italic border-l-2 pl-2.5 space-y-1.5"
                >
                  <p>
                    “<span className="font-bold">{prospecto}</span>, por teléfono es difícil que aprecies la ubicación exacta, las vistas y los lotes disponibles. Por eso lo mejor es coordinar una visita guiada al proyecto para que veas el terreno en persona, recorras las manzanas libres y revisemos juntos precios y facilidades de pago.”
                  </p>
                  <p className="font-semibold text-emerald-600 dark:text-emerald-400">
                    “¿Te queda mejor visitarnos hoy por la tarde o mañana en la mañana? ¿Irás por tu cuenta o coordinamos punto de encuentro?”
                  </p>
                </div>
              </div>

              {/* OPCIÓN 2: CITA EN OFICINA */}
              <div className="p-3.5 rounded-lg bg-white dark:bg-[#0c121d] border border-slate-200 dark:border-slate-800 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Building2 size={16} className="text-slate-600 dark:text-slate-400" />
                    <span className="text-xs font-bold text-slate-800 dark:text-slate-200 uppercase tracking-wide">
                      2. Segunda opción: Cita presencial en oficina
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      copyText(
                        'p4-oficina',
                        `“¡Perfecto, ${prospecto}! Si prefieres primero revisar planos, disponibilidad y simulación de cuotas con calma en oficina antes de subir al proyecto, podemos reunirnos personalmente en nuestra oficina de ${brandName}. Hoy o mañana, ¿a qué hora te queda mejor acercarte?”`
                      )
                    }
                    className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 hover:text-[#1F1D5C]"
                  >
                    {copiedKey === 'p4-oficina' ? <Check size={11} className="text-emerald-500" /> : <Copy size={11} />}
                    <span>{copiedKey === 'p4-oficina' ? '¡Copiado!' : 'Copiar'}</span>
                  </button>
                </div>

                <div className="text-xs text-slate-700 dark:text-slate-300 leading-relaxed italic border-l-2 border-slate-400 pl-2.5">
                  <p>
                    “¡Perfecto, <span className="font-bold">{prospecto}</span>! Si prefieres primero revisar planos, disponibilidad y simulación de cuotas con calma en oficina antes de ir al proyecto, podemos reunirnos personalmente en nuestra oficina de {brandName}. Hoy o mañana, ¿a qué hora te queda mejor acercarte?”
                  </p>
                </div>
              </div>

              {/* OPCIÓN 3: VIRTUAL ZOOM / MEET */}
              <div className="p-3.5 rounded-lg bg-white dark:bg-[#0c121d] border border-slate-200 dark:border-slate-800 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Video size={16} className="text-sky-600" />
                    <span className="text-xs font-bold text-slate-800 dark:text-slate-200 uppercase tracking-wide">
                      3. Tercera opción: Cita virtual por Zoom o Google Meet
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      copyText(
                        'p4-virtual',
                        `“¡Excelente, ${prospecto}! Como te encuentras en otra ciudad (o con horario ajustado), hagamos una videollamada corta de 20 minutos por Zoom o Meet. Te comparto pantalla con el plano interactivo, lotes disponibles, ubicación GPS, fotos/videos del proyecto y cotización detallada.\n¿Qué horario de hoy te queda cómodo para enviarte el enlace por WhatsApp?”`
                      )
                    }
                    className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-sky-50 hover:bg-sky-100 dark:bg-sky-950/50 text-sky-700 dark:text-sky-300"
                  >
                    {copiedKey === 'p4-virtual' ? <Check size={11} className="text-emerald-500" /> : <Copy size={11} />}
                    <span>{copiedKey === 'p4-virtual' ? '¡Copiado!' : 'Copiar'}</span>
                  </button>
                </div>

                <div className="text-xs text-slate-700 dark:text-slate-300 leading-relaxed italic border-l-2 border-sky-400 pl-2.5 space-y-1.5">
                  <p>
                    “¡Excelente, <span className="font-bold">{prospecto}</span>! Como te encuentras en otra ciudad o con horario ajustado, hagamos una videollamada corta de 20 minutos por Zoom o Meet. Te comparto pantalla con el plano, lotes disponibles, ubicación exacta, fotos/videos del proyecto y cotización detallada.”
                  </p>
                  <p className="font-semibold text-sky-600 dark:text-sky-400">
                    “¿Qué horario de hoy te queda cómodo para enviarte el enlace por WhatsApp?”
                  </p>
                </div>
              </div>

              {/* REGLAS NO NEGOCIABLES */}
              <div className="p-3 rounded-lg bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/60 text-xs space-y-1.5">
                <div className="flex items-center gap-1.5 font-bold text-rose-800 dark:text-rose-300">
                  <ShieldAlert size={14} className="text-rose-600" />
                  <span>Reglas no negociables del Paso 4:</span>
                </div>
                <ul className="list-disc list-inside space-y-1 text-rose-900 dark:text-rose-200 pl-1">
                  <li>Si está en Arequipa, priorizar siempre la visita guiada al proyecto.</li>
                  <li>Si está en otra ciudad/departamento o no puede desplazarse aún, agendar videollamada con plano en vivo.</li>
                  <li>Proponer fecha y hora concreta (idealmente hoy, mañana o fin de semana próximo).</li>
                  <li>Si reprograma o no puede asistir, actualizar el estado de la cita a <strong>Reprogramada</strong> o <strong>No asistió</strong> en el CRM y reagendar.</li>
                </ul>
              </div>
            </section>
          )}

          {/* PASO 5: AUTONOMÍA DE LA DECISIÓN */}
          {showPaso5 && (
            <section className="space-y-3 rounded-xl p-4 bg-slate-50 dark:bg-[#131d30] border border-slate-200 dark:border-slate-800 shadow-xs">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span
                    style={{ backgroundColor: '#1F1D5C' }}
                    className="w-6 h-6 rounded-lg text-white text-xs font-bold flex items-center justify-center shadow-xs"
                  >
                    5
                  </span>
                  <h3 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wide">
                    Paso 5: Autonomía de la Decisión
                  </h3>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    copyText(
                      'p5-pregunta',
                      `“${prospecto}, una consulta adicional: cuando evalúas adquirir o invertir en un lote, ¿la decisión la tomas directamente tú o la conversas también con tu pareja, algún familiar o socio?”`
                    )
                  }
                  className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-white dark:bg-[#0c121d] border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:text-[#1F1D5C]"
                >
                  {copiedKey === 'p5-pregunta' ? <Check size={11} className="text-emerald-500" /> : <Copy size={11} />}
                  <span>{copiedKey === 'p5-pregunta' ? '¡Copiado!' : 'Copiar'}</span>
                </button>
              </div>

              <div
                style={{ borderLeftColor: '#1F1D5C' }}
                className="p-3 rounded-lg bg-white dark:bg-[#0c121d] border border-slate-200 dark:border-slate-800 text-xs text-slate-800 dark:text-slate-200 italic border-l-2"
              >
                “<span className="font-bold">{prospecto}</span>, una consulta adicional: cuando evalúas adquirir o invertir en un lote, ¿la decisión la tomas directamente tú o la conversas también con tu pareja, algún familiar o socio?”
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                <div className="p-3 rounded-lg bg-emerald-50/60 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-900/60 space-y-2">
                  <div className="flex items-center gap-1.5 font-bold text-emerald-800 dark:text-emerald-300">
                    <CheckCircle2 size={14} className="text-emerald-600" />
                    <span>Escenario A · Decisor directo</span>
                  </div>
                  <div className="space-y-1 text-slate-700 dark:text-slate-300">
                    <p className="font-medium text-emerald-700 dark:text-emerald-400">
                      Prospecto: “Sí, la decisión e inversión dependen directamente de mí”.
                    </p>
                    <p className="italic bg-white dark:bg-[#0c121d] p-2 rounded border border-emerald-100 dark:border-emerald-900/40">
                      Asesor: “¡Perfecto, {prospecto}! Entonces confirmamos nuestra visita/cita y te llevo las opciones exactas de lotes y financiamiento”.
                    </p>
                  </div>
                </div>

                <div className="p-3 rounded-lg bg-amber-50/60 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-900/60 space-y-2">
                  <div className="flex items-center gap-1.5 font-bold text-amber-800 dark:text-amber-300">
                    <Users size={14} className="text-amber-600" />
                    <span>Escenario B · Decisión compartida</span>
                  </div>
                  <div className="space-y-1 text-slate-700 dark:text-slate-300">
                    <p className="font-medium text-amber-700 dark:text-amber-400">
                      Prospecto: “Lo veo con mi esposo / esposa / familia porque compramos juntos”.
                    </p>
                    <p className="italic bg-white dark:bg-[#0c121d] p-2 rounded border border-amber-100 dark:border-amber-900/40">
                      Asesor: “¡Qué importante que ambos conozcan el terreno y los números! ¿Podría acompañarnos a la visita o conectarse también a la videollamada para que resuelvan todas sus dudas juntos?”
                    </p>
                  </div>
                </div>
              </div>

              <div className="p-3 rounded-lg bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/60 text-xs space-y-1 text-rose-900 dark:text-rose-200">
                <p className="font-bold text-rose-800 dark:text-rose-300 flex items-center gap-1.5">
                  <ShieldAlert size={14} className="text-rose-600" />
                  Regla comercial no negociable:
                </p>
                <p>
                  En compras inmobiliarias, asegurar la presencia de los codecisores (cónyuge, familia o socio) aumenta drásticamente la probabilidad de separación en visita y evita postergaciones largas.
                </p>
              </div>
            </section>
          )}

          {/* PASO 6: CONFIRMACIÓN Y ASENTAMIENTO */}
          {showPaso6 && (
            <section className="space-y-3 rounded-xl p-4 bg-slate-50 dark:bg-[#131d30] border border-slate-200 dark:border-slate-800 shadow-xs">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span
                    style={{ backgroundColor: '#1F1D5C' }}
                    className="w-6 h-6 rounded-lg text-white text-xs font-bold flex items-center justify-center shadow-xs"
                  >
                    6
                  </span>
                  <h3 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wide">
                    Paso 6: Confirmación y Asentamiento
                  </h3>
                </div>
                <span
                  style={{ color: '#1F1D5C', borderColor: '#1F1D5C' }}
                  className="text-[11px] font-semibold bg-[#1F1D5C]/10 dark:bg-[#1F1D5C]/30 px-2 py-0.5 rounded-full border border-[#1F1D5C]/30 dark:border-indigo-400/30"
                >
                  Compromiso
                </span>
              </div>

              {/* Confirmación Visita al Proyecto */}
              <div className="p-3 rounded-lg bg-white dark:bg-[#0c121d] border border-slate-200 dark:border-slate-800 space-y-2">
                <div className="flex items-center justify-between">
                  <span style={{ color: '#1F1D5C' }} className="text-xs font-bold flex items-center gap-1.5">
                    <MapPin size={13} /> Para visita guiada al proyecto
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      copyText(
                        'p6-visita',
                        `“¡Perfecto, ${prospecto}! Quedamos confirmados para el [día] a las [hora] para tu visita al proyecto.\nEn este momento dejo registrada nuestra cita en agenda; te recomiendo también anotarla para no cruzarnos.\nDurante el recorrido te mostraré los lotes disponibles según lo que buscas, la documentación y las facilidades de cuotas. Si encuentras el lote ideal, ese mismo día puedes separarlo para asegurar tu ubicación.\nSoy ${defaultAsesor} de ${brandName}; en unos minutos te envío por WhatsApp la ubicación exacta y confirmación. ¡Nos vemos!”`
                      )
                    }
                    className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 hover:text-[#1F1D5C]"
                  >
                    {copiedKey === 'p6-visita' ? <Check size={11} className="text-emerald-500" /> : <Copy size={11} />}
                    <span>{copiedKey === 'p6-visita' ? '¡Copiado!' : 'Copiar'}</span>
                  </button>
                </div>
                <div
                  style={{ borderLeftColor: '#1F1D5C' }}
                  className="text-xs text-slate-700 dark:text-slate-300 leading-relaxed italic border-l-2 pl-2.5 space-y-1"
                >
                  <p>“¡Perfecto, <span className="font-bold">{prospecto}</span>! Quedamos confirmados para el [día] a las [hora] para tu visita al proyecto.</p>
                  <p>Durante el recorrido te mostraré los lotes disponibles según lo que buscas, la documentación y las facilidades de cuotas. Si encuentras el lote ideal, ese mismo día puedes separarlo para asegurar tu ubicación.</p>
                  <p style={{ color: '#1F1D5C' }} className="font-semibold">
                    Soy {defaultAsesor} de {brandName}; en unos minutos te envío por WhatsApp la ubicación exacta y confirmación. ¡Nos vemos!”
                  </p>
                </div>
              </div>

              {/* Confirmación Oficina / Virtual */}
              <div className="p-3 rounded-lg bg-white dark:bg-[#0c121d] border border-slate-200 dark:border-slate-800 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-slate-700 dark:text-slate-300 flex items-center gap-1.5">
                    <Building2 size={13} /> Para cita en oficina o virtual
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      copyText(
                        'p6-ofic',
                        `“¡Excelente, ${prospecto}! Estoy agendando nuestra reunión para el [día] a las [hora].\nTendré listos el plano actualizado, la disponibilidad de lotes según el metraje que buscas y la simulación de cuotas para evaluarlo con total claridad. Si alguna ubicación te convence, te explico ahí mismo el proceso de separación.\nEn unos minutos te envío por WhatsApp la confirmación y [la dirección / el enlace de reunión]. ¡Que tengas excelente día!”`
                      )
                    }
                    className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 hover:text-[#1F1D5C]"
                  >
                    {copiedKey === 'p6-ofic' ? <Check size={11} className="text-emerald-500" /> : <Copy size={11} />}
                    <span>{copiedKey === 'p6-ofic' ? '¡Copiado!' : 'Copiar'}</span>
                  </button>
                </div>
                <div className="text-xs text-slate-700 dark:text-slate-300 leading-relaxed italic border-l-2 border-slate-400 pl-2.5 space-y-1">
                  <p>“¡Excelente, <span className="font-bold">{prospecto}</span>! Estoy agendando nuestra reunión para el [día] a las [hora].</p>
                  <p>Tendré listos el plano actualizado, la disponibilidad de lotes según el metraje que buscas y la simulación de cuotas para evaluarlo con total claridad. Si alguna ubicación te convence, te explico ahí mismo el proceso de separación.</p>
                  <p style={{ color: '#1F1D5C' }} className="font-semibold">
                    En unos minutos te envío por WhatsApp la confirmación y [la dirección / el enlace de reunión]. ¡Que tengas excelente día!”
                  </p>
                </div>
              </div>
            </section>
          )}

          {/* OBJECIONES TELEFÓNICAS */}
          {showObjeciones && (
            <section className="space-y-3 rounded-xl p-4 bg-amber-50/50 dark:bg-[#181a24] border border-amber-200 dark:border-amber-900/60 shadow-xs">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <div className="w-6 h-6 rounded-lg bg-amber-600 text-white flex items-center justify-center font-bold text-xs">
                    !
                  </div>
                  <h3 className="text-sm font-bold text-amber-950 dark:text-amber-200 uppercase tracking-wide">
                    Anexo de Guiones · Objeciones Telefónicas
                  </h3>
                </div>
                <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-amber-100 dark:bg-amber-950 text-amber-800 dark:text-amber-300 border border-amber-300 dark:border-amber-800">
                  3 Casos Clave
                </span>
              </div>

              <div className="space-y-3 pt-1">
                {objeciones
                  .filter((o) => matchText(o.titulo) || matchText(o.guion) || matchText(o.subtitulo))
                  .map((obj) => (
                    <div
                      key={obj.id}
                      className="p-3.5 rounded-lg bg-white dark:bg-[#0c121d] border border-amber-200 dark:border-slate-800 space-y-2 hover:border-amber-400 dark:hover:border-amber-700 transition-colors"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <h4 className="text-xs font-bold text-slate-900 dark:text-white flex items-center gap-1.5">
                            <HelpCircle size={14} className="text-amber-500 shrink-0" />
                            {obj.titulo}
                          </h4>
                          <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
                            {obj.subtitulo}
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() => copyText(obj.id, obj.guion)}
                          className="flex items-center gap-1 text-[11px] px-2 py-1 rounded bg-amber-50 hover:bg-amber-100 dark:bg-amber-950/60 dark:hover:bg-amber-900 text-amber-800 dark:text-amber-300 transition-colors shrink-0"
                          title="Copiar respuesta"
                        >
                          {copiedKey === obj.id ? <Check size={11} className="text-emerald-500" /> : <Copy size={11} />}
                          <span>{copiedKey === obj.id ? '¡Copiado!' : 'Copiar'}</span>
                        </button>
                      </div>

                      <div className="text-xs text-slate-700 dark:text-slate-300 leading-relaxed italic border-l-2 border-amber-400 pl-2.5 whitespace-pre-line">
                        {obj.guion}
                      </div>
                    </div>
                  ))}
              </div>
            </section>
          )}

          {/* SECCIÓN: LINKS DE INTERÉS (PLANOS, TOURS Y WEB) */}
          {showLinks && (
            <section className="space-y-4 rounded-xl p-4 bg-slate-50 dark:bg-[#131d30] border border-slate-200 dark:border-slate-800 shadow-xs">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span
                    style={{ backgroundColor: '#1F1D5C' }}
                    className="w-6 h-6 rounded-lg text-white flex items-center justify-center shadow-xs"
                  >
                    <Link2 size={14} />
                  </span>
                  <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                    Links de Interés para Consultar
                  </h3>
                </div>
                <span className="text-[11px] font-semibold text-[#1F1D5C] dark:text-indigo-300 bg-[#1F1D5C]/10 dark:bg-[#1F1D5C]/30 px-2 py-0.5 rounded-full border border-[#1F1D5C]/30 dark:border-indigo-400/30">
                  Planos · Tours · Web · Redes
                </span>
              </div>

              <div className="space-y-4">
                {filteredLinksGrupos.map((grupo) => (
                  <div key={grupo.id} className="space-y-2">
                    <div className="flex items-center gap-1.5 text-xs font-bold text-[#1F1D5C] dark:text-indigo-300">
                      {grupo.id === 'planos' ? (
                        <Map size={13} />
                      ) : grupo.id === 'tours' ? (
                        <Video size={13} />
                      ) : grupo.id === 'redes' ? (
                        <Users size={13} />
                      ) : (
                        <Globe size={13} />
                      )}
                      <span>{grupo.titulo}</span>
                    </div>

                    <div className="grid grid-cols-1 gap-2">
                      {grupo.items.map((item) => (
                        <div
                          key={item.id}
                          className="p-2.5 rounded-lg bg-white dark:bg-[#0c121d] border border-slate-200 dark:border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-2 hover:border-[#1F1D5C]/50 transition-colors"
                        >
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-1.5 flex-wrap">
                              <span className="text-xs font-bold text-slate-900 dark:text-white">
                                {item.nombre}
                              </span>
                              <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
                                {grupo.badge}
                              </span>
                            </div>
                            <a
                              href={item.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="block text-[11px] font-mono text-indigo-600 dark:text-indigo-400 hover:underline truncate mt-0.5"
                              title={item.url}
                            >
                              {item.url}
                            </a>
                          </div>

                          <div className="flex items-center gap-1.5 shrink-0">
                            <button
                              type="button"
                              onClick={() => copyText(item.id, item.url)}
                              className="inline-flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-md bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 transition-colors cursor-pointer"
                              title="Copiar enlace"
                            >
                              {copiedKey === item.id ? (
                                <Check size={12} className="text-emerald-500" />
                              ) : (
                                <Copy size={12} />
                              )}
                              <span>{copiedKey === item.id ? '¡Copiado!' : 'Copiar'}</span>
                            </button>

                            <a
                              href={item.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              style={{ backgroundColor: '#1F1D5C' }}
                              className="inline-flex items-center gap-1 text-[11px] font-semibold px-2.5 py-1 rounded-md text-white hover:brightness-110 transition-all"
                              title={`Abrir ${item.nombre}`}
                            >
                              <span>Abrir</span>
                              <ExternalLink size={11} />
                            </a>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* MENSAJE CUANDO NINGÚN RESULTADO COINCIDE */}
          {!showPaso1 && !showPaso2 && !showPaso3 && !showPaso4 && !showPaso5 && !showPaso6 && !showObjeciones && !showLinks && (
            <div className="text-center py-12 space-y-2 text-slate-400">
              <Search size={32} className="mx-auto text-slate-300 dark:text-slate-600" />
              <p className="text-sm font-medium">No se encontraron resultados para “{searchQuery}”</p>
              <button
                type="button"
                onClick={() => {
                  setSearchQuery('')
                  setActiveTab('todos')
                }}
                style={{ color: '#1F1D5C' }}
                className="text-xs hover:underline"
              >
                Limpiar búsqueda y ver todo
              </button>
            </div>
          )}
        </div>

        {/* FOOTER INFORMATIVO */}
        <div className="px-5 py-3 border-t border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-[#131d30] flex items-center justify-between text-xs text-slate-500 dark:text-slate-400 shrink-0">
          <div className="flex items-center gap-2">
            <MapPin size={12} style={{ color: '#1F1D5C' }} />
            <span>{brandLegalName} · Guiones de calificación, visita y cierre</span>
          </div>
          <span className="text-[11px] font-mono">{brandName} CRM</span>
        </div>
      </aside>
    </>
  )
}
