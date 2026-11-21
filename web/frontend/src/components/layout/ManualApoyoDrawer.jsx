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
  Home,
  Building2,
  Video,
  User,
  RotateCcw,
  Link2,
  ExternalLink,
} from 'lucide-react'
import useAuthStore from '@/store/authStore'
import useManualApoyoStore from '@/store/manualApoyoStore'

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
  const [miniPitchSubTab, setMiniPitchSubTab] = useState('interes') // 'interes' | 'motivacion'
  const searchInputRef = useRef(null)
  const contentContainerRef = useRef(null)

  const handleSelectTab = (tabKey) => {
    setActiveTab(tabKey)
    if (contentContainerRef.current) {
      contentContainerRef.current.scrollTo({ top: 0, behavior: 'smooth' })
    }
  }

  // Nombre por defecto del asesor tomado del perfil autenticado
  const defaultAsesor = useMemo(() => {
    if (asesorNombre?.trim()) return asesorNombre.trim()
    const name = [user?.first_name, user?.last_name].filter(Boolean).join(' ')
    return name || 'Brenda González'
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

  // Datos estructurados de los Mini Pitches
  const miniPitchesInteres = useMemo(() => [
    {
      id: 'interes-inmersion-1',
      categoria: 'Metodología de inmersión (Opción 1)',
      titulo: 'Enfoque comunicativo desde la 1ra clase',
      guion: `“¡Justamente esa es nuestra gran diferencia! En Brighton no nos limitamos a la enseñanza tradicional. Trabajamos con una metodología de inmersión, donde recreamos situaciones como si estuvieras en el extranjero, para que tengas la necesidad de comunicarte en inglés desde tu primera clase. ¡Imagínate empezar a hablar inglés desde el primer día!”`,
    },
    {
      id: 'interes-inmersion-2',
      categoria: 'Metodología de inmersión (Opción 2)',
      titulo: 'Superar la gramática tradicional',
      guion: `“Justamente eso es lo que buscamos cambiar en Brighton. No queremos que te quedes solamente aprendiendo reglas gramaticales, sino que vivas el idioma mediante experiencias de inmersión que te impulsen a comunicarte en inglés desde tu primera clase. ¡Imagínate lo diferente que sería aprender de esa manera!”`,
    },
    {
      id: 'interes-talleres',
      categoria: 'Talleres vivenciales',
      titulo: 'Vivir el idioma en situaciones cotidianas',
      guion: `“¡Qué bueno que te llamaron la atención! Nuestros talleres buscan que vivas el inglés, no solamente que lo estudies. Recreamos situaciones cotidianas para que practiques el idioma como si estuvieras en otro país, desarrollando tu comunicación de manera más natural.”`,
    },
    {
      id: 'interes-nativos',
      categoria: 'Profesores nativos',
      titulo: 'Pronunciación real y seguridad auditiva',
      guion: `“¡Excelente! Aprender con profesores nativos te permite familiarizarte con la pronunciación, las expresiones y la manera natural de comunicarse en inglés. Es una oportunidad para desarrollar la parte auditiva y ganar seguridad al hablar.”`,
    },
    {
      id: 'interes-grupos',
      categoria: 'Grupos reducidos',
      titulo: 'Participación activa y atención personalizada',
      guion: `“¡Exactamente! En Brighton buscamos que nuestros alumnos participen activamente. Al trabajar con grupos reducidos, tienes mayores oportunidades de practicar, interactuar y recibir una atención más personalizada.”`,
    },
    {
      id: 'interes-14meses',
      categoria: 'Inglés en 14 meses',
      titulo: 'Programa estructurado con resultados',
      guion: `“¡Claro! Nuestra propuesta contempla un programa de 14 meses. Lo interesante es que durante ese tiempo no solamente estudias contenidos, sino que participas en experiencias diseñadas para desarrollar tu comunicación en inglés desde el inicio.”`,
    },
    {
      id: 'interes-horarios',
      categoria: 'Horarios programables',
      titulo: 'Flexibilidad para estudios y trabajo',
      guion: `“¡Esa es una gran ventaja! Sabemos que muchos alumnos trabajan o estudian, por eso contamos con opciones de programación de clases que permiten organizar mejor el aprendizaje de acuerdo con los horarios disponibles.”`,
    },
    {
      id: 'interes-certificaciones',
      categoria: 'Certificaciones internacionales',
      titulo: 'Acreditación oficial para metas académicas/laborales',
      guion: `“¡Muy buena elección! Hoy acreditar tu nivel de inglés puede ayudarte a acceder a oportunidades académicas y profesionales. Me gustaría explicarte las alternativas de certificación vinculadas a nuestro programa.”`,
    },
  ], [])

  const miniPitchesMotivacion = useMemo(() => [
    {
      id: 'mot-trabajo',
      categoria: 'Trabajo y crecimiento profesional',
      titulo: 'Mejores puestos y desenvolvimiento en entrevistas',
      guion: `“¡Qué bueno que estés pensando en tu crecimiento! Hoy el inglés puede marcar una diferencia importante para acceder a mejores puestos y oportunidades laborales. Imagínate poder desenvolverte con seguridad en una entrevista o reunión de trabajo en inglés.”`,
    },
    {
      id: 'mot-posgrado',
      categoria: 'Maestrías y posgrados',
      titulo: 'Requisito clave y acreditación de posgrado',
      guion: `“¡Excelente! Si estás pensando en una maestría o un posgrado, el inglés puede convertirse en una herramienta fundamental. Muchas oportunidades académicas requieren acreditar el idioma, y prepararte desde ahora puede acercarte a ese objetivo.”`,
    },
    {
      id: 'mot-viaje',
      categoria: 'Viajar al extranjero',
      titulo: 'Autonomía para disfrutar sin traductor',
      guion: `“¡Qué emocionante! Imagínate viajar y poder desenvolverte por tu cuenta, conversar con otras personas, pedir información y disfrutar de la experiencia sin depender constantemente de un traductor.”`,
    },
    {
      id: 'mot-vivir',
      categoria: 'Estudiar o vivir en el extranjero',
      titulo: 'Adaptación fluida a situaciones reales',
      guion: `“¡Qué gran proyecto! Si tienes pensado estudiar o vivir fuera del país, comunicarte en inglés puede facilitar muchísimo tu adaptación. Lo ideal es que empieces a familiarizarte con situaciones reales desde ahora.”`,
    },
    {
      id: 'mot-anterior',
      categoria: 'Experiencia anterior sin resultados',
      titulo: 'Superar la frustración con un método vivencial',
      guion: `“¡Te entiendo! Y justamente lo que necesitas es una experiencia de aprendizaje diferente. En Brighton buscamos que no te quedes solamente con la gramática, sino que puedas practicar el idioma en situaciones reales desde el inicio.”`,
    },
    {
      id: 'mot-hijos',
      categoria: 'Aprendizaje para sus hijos',
      titulo: 'Inversión temprana en su desarrollo y futuro',
      guion: `“¡Qué buena decisión! Aprender inglés desde pequeños puede brindarles herramientas muy valiosas para sus estudios y futuras oportunidades. Es una inversión en su desarrollo.”`,
    },
  ], [])

  // Objeciones frecuentes
  const objeciones = useMemo(() => [
    {
      id: 'obj-tiempo',
      titulo: '“No tengo tiempo para reunirnos”',
      subtitulo: 'Técnica de empatía y compromiso de 30 minutos',
      guion: `“¡${prospecto}, ya somos dos! Te entiendo perfectamente. Hoy todos tenemos las agendas bastante ocupadas, entre el trabajo, la familia y nuestras responsabilidades.
Pero dime algo: ¿crees que valdría la pena dedicar 30 minutos de tu tiempo para conocer una propuesta que podría ayudarte a aprender inglés y abrirte nuevas oportunidades?
Eso es justamente lo que necesito: 30 minutos para mostrarte cómo funciona nuestra metodología de inmersión y qué alternativas tenemos para ti.
Hagamos algo: acomodemos nuestras agendas. Yo reviso la mía y tú la tuya.
¿Te quedaría mejor hoy al finalizar tu jornada o mañana antes de empezar tus actividades?
¡Perfecto! Entonces quedamos para mañana a las 7:30 a. m. Valoro mucho que estés haciendo un espacio en tu agenda y voy a prepararte una asesoría personalizada para que aprovechemos al máximo esos 30 minutos.”`,
    },
    {
      id: 'obj-whatsapp',
      titulo: '“Mándame todo por WhatsApp”',
      subtitulo: 'Evitar saturación de información y posicionar el valor de la asesoría',
      guion: `“¡Claro que sí, ${prospecto}! Con mucho gusto te puedo compartir información por WhatsApp.
Pero te cuento algo: lo que he aprendido atendiendo a personas interesadas en aprender inglés es que enviarles toda la información de golpe no siempre funciona.
Imagínate que te envío nuestra metodología, los talleres de inmersión, las modalidades, los horarios, los programas y los precios. ¡Terminaría enviándote tanta información que, en lugar de ayudarte, podría confundirte!
Y sinceramente creo que mereces una atención mucho más personalizada.
Tú estás buscando invertir en tu educación, ¿verdad? Entonces mereces conocer bien qué estás eligiendo y qué programa se adapta mejor a tus objetivos.
Por eso prefiero dedicarte 30 minutos, explicarte nuestra propuesta académica y económica, resolver todas tus dudas y ayudarte a tomar una decisión bien informada.
Hagamos algo, ${prospecto}: ¿hoy por la tarde a qué hora te quedaría bien que nos reunamos?”`,
    },
    {
      id: 'obj-precio',
      titulo: '“Dime cuánto cuesta”',
      subtitulo: 'Redirección del precio hacia la propuesta de valor integral y presupuesto',
      guion: `“¡Claro que sí, ${prospecto}! Por supuesto que te voy a explicar nuestros precios.
Pero antes, déjame hacerte una pregunta: cuando eliges dónde estudiar inglés, ¿crees que lo único importante es conocer el precio?
¿O también te gustaría saber cómo es la metodología, quiénes son tus profesores, cómo funcionan nuestros talleres de inmersión, qué horarios tenemos y qué resultados de aprendizaje buscamos?
Cuéntame, ${prospecto}, ¿lo que quieres saber principalmente es si nuestro programa está dentro de tu presupuesto?
¡Perfecto! Y para orientarte mejor, ¿tienes pensado un presupuesto mensual para invertir en tus estudios?
[Escuchar respuesta]
¡Excelente! Entonces me gustaría explicarte nuestra propuesta académica y económica, para que conozcas todos los beneficios de nuestro programa y las alternativas de pago disponibles.
La idea es que conozcas no solamente cuánto cuesta estudiar en Brighton, sino también qué incluye el programa y cómo funciona nuestra metodología de inmersión.”`,
    },
  ], [prospecto])

  // Links de interés (Recorridos virtuales, Ubicaciones y Material de Sedes)
  const linksDeInteres = useMemo(() => [
    {
      id: 'link-recorrido-jbyr',
      titulo: 'Recorrido sede JBYR',
      descripcion: 'Recorrido virtual en video de la sede José Luis Bustamante y Rivero',
      url: 'https://drive.google.com/file/d/1jcGZS3HQd3hbWxxvcC5f7koREpIiGaBD/view?usp=sharing',
      categoria: 'Sede Bustamante (JBYR)',
      tipo: 'Recorrido',
    },
    {
      id: 'link-umacollo-madelein',
      titulo: 'Umacollo Madelein',
      descripcion: 'Material y recursos audiovisuales de la sede Umacollo',
      url: 'https://drive.google.com/file/d/1IgzR3zZAgdIflvUbLlUSy60TOf61EmDM/view?usp=sharing',
      categoria: 'Sede Umacollo',
      tipo: 'Material',
    },
    {
      id: 'link-ubicacion-umacollo',
      titulo: 'Ubicacion Brighton Umacollo',
      descripcion: 'Referencia y ubicación de llegada en Calle González Prada 110, Umacollo',
      url: 'https://drive.google.com/file/d/1rLkps_7V2GGLEbb4M7N9xXY433cpfSg0/view?usp=sharing',
      categoria: 'Sede Umacollo',
      tipo: 'Ubicación',
    },
    {
      id: 'link-ubicacion-jbyr',
      titulo: 'Ubicacion Brighton JBYR',
      descripcion: 'Referencia y ubicación de llegada en Calle Danubio 233, Bustamante y Rivero',
      url: 'https://drive.google.com/file/d/1ebBjJcBROwK0Te2SG7ZmDDUqTNzKqMHJ/view?usp=sharing',
      categoria: 'Sede Bustamante (JBYR)',
      tipo: 'Ubicación',
    },
    {
      id: 'link-recorrido-umacollo',
      titulo: 'Recorrido sede Umacollo',
      descripcion: 'Recorrido virtual en video de la sede Umacollo',
      url: 'https://drive.google.com/file/d/10iVWCXRsKgcD0osJdYLPOsgnCgHaS9Y_/view?usp=sharing',
      categoria: 'Sede Umacollo',
      tipo: 'Recorrido',
    },
  ], [])

  // Filtrado reactivo por texto de búsqueda
  const q = searchQuery.toLowerCase().trim()
  const matchText = (text) => (!q ? true : (text || '').toLowerCase().includes(q))

  const showPaso1 = (activeTab === 'todos' || activeTab === 'paso1') &&
    (matchText('apertura presentacion brenda gonzalez brighton ingles nativo redes sociales') || matchText(prospecto))

  const showPaso2 = (activeTab === 'todos' || activeTab === 'paso2') &&
    (matchText('diagnostico preguntas no negociable motivacion beneficiario ubicacion experiencia previa necesidad actual inicio arequipa'))

  const showPaso3 = (activeTab === 'todos' || activeTab === 'paso3') &&
    (miniPitchesInteres.some((p) => matchText(p.categoria) || matchText(p.guion)) ||
     miniPitchesMotivacion.some((p) => matchText(p.categoria) || matchText(p.guion)))

  const showPaso4 = (activeTab === 'todos' || activeTab === 'paso4') &&
    (matchText('cita visita domiciliaria arequipa oficinas brighton umacollo bustamante zoom meet gonzalez prada danubio'))

  const showPaso5 = (activeTab === 'todos' || activeTab === 'paso5') &&
    (matchText('autonomia decision economica academica esposo familia'))

  const showPaso6 = (activeTab === 'todos' || activeTab === 'paso6') &&
    (matchText('confirmacion asentamiento propuesta academica matricula whatsapp'))

  const showObjeciones = (activeTab === 'todos' || activeTab === 'objeciones') &&
    objeciones.some((o) => matchText(o.titulo) || matchText(o.guion))

  const showLinks = (activeTab === 'todos' || activeTab === 'links') &&
    (matchText('links') || matchText('interes') || matchText('enlaces') || matchText('recorrido') || matchText('ubicacion') || matchText('jbyr') || matchText('bustamante') || matchText('umacollo') || matchText('madelein') || linksDeInteres.some((l) => matchText(l.titulo) || matchText(l.descripcion) || matchText(l.categoria)))

  const tabs = [
    { key: 'todos', label: 'Todos' },
    { key: 'paso1', label: '1. Apertura' },
    { key: 'paso2', label: '2. Diagnóstico' },
    { key: 'paso3', label: '3. Mini Pitch' },
    { key: 'paso4', label: '4. Citas' },
    { key: 'paso5', label: '5. Decisión' },
    { key: 'paso6', label: '6. Confirmación' },
    { key: 'objeciones', label: 'Objeciones (3)' },
    { key: 'links', label: 'Links de Interés (5)', icon: Link2 },
  ]

  return (
    <>
      {/* ─────────────────────────────────────────────────────────────
          BOTÓN FLOTANTE EN LA PARTE DERECHA DE LA PLATAFORMA (#df2029)
          Visible en toda la aplicación, fijado en el borde derecho
          ───────────────────────────────────────────────────────────── */}
      <div className="fixed right-0 top-1/2 -translate-y-1/2 z-40 select-none">
        <button
          type="button"
          onClick={toggleManual}
          title="Manual de Apoyo Telefónico (Alt+M)"
          aria-label="Abrir manual de apoyo telefónico"
          style={{ backgroundColor: isOpen ? '#b8151d' : '#df2029' }}
          className={`flex items-center gap-2 pl-2.5 pr-2 py-3.5 rounded-l-2xl border-y border-l shadow-2xl transition-all duration-200 cursor-pointer group text-white border-red-300/40 ${
            isOpen ? 'translate-x-1' : 'hover:-translate-x-1 hover:brightness-110'
          }`}
        >
          <div className="relative flex items-center justify-center">
            <PhoneCall size={18} className="text-white group-hover:scale-110 transition-transform" />
            <span className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full bg-emerald-400 ring-2 ring-[#df2029] animate-pulse" />
          </div>
          <span className="[writing-mode:vertical-rl] rotate-180 text-[11px] font-bold tracking-wider uppercase">
            Manual de Guiones
          </span>
        </button>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          BACKDROP OVERLAY
          ───────────────────────────────────────────────────────────── */}
      {isOpen && (
        <div
          onClick={closeManual}
          className="fixed inset-0 bg-slate-950/60 backdrop-blur-xs z-50 transition-opacity animate-in fade-in duration-200"
          aria-hidden="true"
        />
      )}

      {/* ─────────────────────────────────────────────────────────────
          DRAWER / PANEL DESPLEGABLE DESDE LA DERECHA
          ───────────────────────────────────────────────────────────── */}
      <aside
        className={`fixed inset-y-0 right-0 z-50 flex flex-col w-full sm:w-[580px] md:w-[680px] bg-white dark:bg-[#0f1624] text-slate-900 dark:text-slate-100 shadow-2xl border-l border-slate-200 dark:border-slate-800 transform transition-transform duration-300 ease-out ${
          isOpen ? 'translate-x-0' : 'translate-x-full'
        }`}
        aria-label="Manual de apoyo telefónico"
        role="dialog"
        aria-modal="true"
      >
        {/* HEADER DEL MANUAL */}
        <div className="relative px-5 py-4 border-b border-slate-200 dark:border-slate-800 bg-slate-50/80 dark:bg-[#131d30]/90 backdrop-blur-sm shrink-0">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <div
                style={{ backgroundColor: '#df2029' }}
                className="w-9 h-9 rounded-xl text-white flex items-center justify-center shadow-md shadow-[#df2029]/30 shrink-0"
              >
                <BookOpen size={18} />
              </div>
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <span
                    style={{ color: '#df2029', borderColor: '#df2029' }}
                    className="text-[10px] font-bold tracking-wider uppercase px-2 py-0.5 rounded-full bg-red-50 dark:bg-[#df2029]/20 border border-opacity-30"
                  >
                    Brighton Inglés Nativo
                  </span>
                  <span className="text-[10px] font-medium text-slate-500 dark:text-slate-400">
                    Alt + M
                  </span>
                </div>
                <h2 className="text-base font-bold text-slate-900 dark:text-white leading-tight mt-0.5">
                  Anexo de Guiones · Estructura de Llamada
                </h2>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Gestión Leads TikTok · Instagram · Facebook · Web
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
              <User size={13} style={{ color: '#df2029' }} className="shrink-0" />
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
              placeholder="Buscar en guiones (ej: zoom, precio, umacollo, inmersión, no tengo tiempo)..."
              className="w-full pl-8 pr-8 py-1.5 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-[#0c121d] text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-[#df2029]"
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

          {/* PESTAÑAS DE NAVEGACIÓN RÁPIDA (FONDOS #df2029) */}
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5 pt-0.5">
            {tabs.map((tab) => {
              const active = activeTab === tab.key
              const Icon = tab.icon
              return (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => handleSelectTab(tab.key)}
                  style={active ? { backgroundColor: '#df2029' } : {}}
                  className={`text-xs px-2.5 py-1 rounded-md font-medium whitespace-nowrap transition-all cursor-pointer flex items-center gap-1.5 ${
                    active
                      ? 'text-white shadow-xs font-semibold scale-[1.02]'
                      : 'bg-slate-200/70 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300'
                  }`}
                >
                  {Icon && <Icon size={12} className="shrink-0" />}
                  <span>{tab.label}</span>
                </button>
              )
            })}
          </div>
        </div>

        {/* CONTENIDO CON SCROLL */}
        <div ref={contentContainerRef} className="flex-1 overflow-y-scroll wa-scrollbar p-5 space-y-6">

          {/* ─────────────────────────────────────────────────────────────
              PASO 1 : APERTURA Y PRESENTACION
              ───────────────────────────────────────────────────────────── */}
          {showPaso1 && (
            <section className="space-y-3 rounded-xl p-4 bg-slate-50 dark:bg-[#131d30] border border-slate-200 dark:border-slate-800 shadow-xs">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span
                    style={{ backgroundColor: '#df2029' }}
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
                      `“Hola, ¿${prospecto}?, ¿cómo estas?
Soy ${defaultAsesor} de Brighton Inglés Nativo. Te tenemos registrada en nuestro sistema porque nos dejaste tus datos a través de nuestras redes sociales, interesada en aprender inglés. ¿Correcto?
¡Que bueno!”`
                    )
                  }
                  className="flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-white dark:bg-[#0c121d] border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:text-[#df2029] dark:hover:text-[#ff6b72] transition-colors shadow-xs"
                >
                  {copiedKey === 'p1' ? <Check size={12} className="text-emerald-500" /> : <Copy size={12} />}
                  <span>{copiedKey === 'p1' ? '¡Copiado!' : 'Copiar'}</span>
                </button>
              </div>

              {/* Burbuja de Guión */}
              <div
                style={{ borderLeftColor: '#df2029' }}
                className="relative pl-3 border-l-3 space-y-2 text-sm leading-relaxed text-slate-800 dark:text-slate-200 bg-white dark:bg-[#0c121d] p-3 rounded-r-lg border-y border-r border-slate-200 dark:border-slate-800"
              >
                <p style={{ color: '#df2029' }} className="font-semibold text-xs">
                  Asesor ({defaultAsesor}):
                </p>
                <p>“Hola, ¿<span className="font-bold underline decoration-[#df2029]">{prospecto}</span>?, ¿cómo estas?</p>
                <p>
                  Soy <span className="font-bold">{defaultAsesor}</span> de Brighton Inglés Nativo. Te tenemos registrada en nuestro sistema porque nos dejaste tus datos a través de nuestras redes sociales, interesada en aprender inglés. ¿Correcto?
                </p>
                <p className="font-medium text-emerald-600 dark:text-emerald-400">¡Que bueno!”</p>
              </div>
            </section>
          )}

          {/* ─────────────────────────────────────────────────────────────
              PASO 2 : DIAGNÓSTICO - PREGUNTAS NO NEGOCIABLES
              ───────────────────────────────────────────────────────────── */}
          {showPaso2 && (
            <section className="space-y-3 rounded-xl p-4 bg-slate-50 dark:bg-[#131d30] border border-slate-200 dark:border-slate-800 shadow-xs">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span
                    style={{ backgroundColor: '#df2029' }}
                    className="w-6 h-6 rounded-lg text-white text-xs font-bold flex items-center justify-center shadow-xs"
                  >
                    2
                  </span>
                  <div>
                    <h3 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wide">
                      Paso 2: Diagnóstico - Preguntas No Negociables
                    </h3>
                  </div>
                </div>
                <span className="text-[11px] font-semibold text-amber-700 dark:text-amber-300 bg-amber-100 dark:bg-amber-950/60 px-2 py-0.5 rounded-full border border-amber-200 dark:border-amber-800">
                  Obligatorias
                </span>
              </div>

              <div className="bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-900/60 p-2.5 rounded-lg text-xs text-amber-900 dark:text-amber-200 flex items-start gap-2">
                <Target size={14} className="text-amber-600 shrink-0 mt-0.5" />
                <p>
                  <span className="font-bold">Objetivo:</span> conocer la motivación del prospecto y generar una conversación natural.
                </p>
              </div>

              <div className="grid grid-cols-1 gap-2 pt-1 text-xs">
                {[
                  {
                    cat: 'Motivación',
                    q: '¿Qué fue lo que más te llamó la atención de nuestra publicidad? / ¿Qué te animó a contactarnos?',
                  },
                  {
                    cat: 'Beneficiario',
                    q: '¿El interés por aprender inglés es para ti o para algún miembro de tu familia?',
                  },
                  {
                    cat: 'Ubicación',
                    q: '¿Te encuentras en Arequipa o en otra ciudad? ¿En qué distrito?',
                  },
                  {
                    cat: 'Experiencia previa',
                    q: '¿Anteriormente habías intentado estudiar inglés? ¿Dónde estudiaste? ¿Qué pasó? ¿Por qué crees que no lograste aprender?',
                  },
                  {
                    cat: 'Necesidad actual',
                    q: '¿Por qué es importante para ti aprender inglés hoy? ¿A qué te dedicas actualmente?',
                  },
                  {
                    cat: 'Inicio',
                    q: '¿Para cuándo te gustaría empezar?',
                  },
                ].map((item, idx) => (
                  <div
                    key={idx}
                    className="p-2.5 rounded-lg bg-white dark:bg-[#0c121d] border border-slate-200 dark:border-slate-800 flex items-start justify-between gap-2 hover:border-[#df2029]/50 transition-colors"
                  >
                    <div className="space-y-1">
                      <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">
                        {item.cat}
                      </span>
                      <p className="text-slate-800 dark:text-slate-200 font-medium text-xs leading-snug">
                        {item.q}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => copyText(`p2-${idx}`, item.q)}
                      className="p-1 rounded text-slate-400 hover:text-[#df2029] transition-colors shrink-0"
                      title="Copiar pregunta"
                    >
                      {copiedKey === `p2-${idx}` ? <Check size={12} className="text-emerald-500" /> : <Copy size={12} />}
                    </button>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* ─────────────────────────────────────────────────────────────
              PASO 3 : MINI PITCH
              ───────────────────────────────────────────────────────────── */}
          {showPaso3 && (
            <section className="space-y-3 rounded-xl p-4 bg-slate-50 dark:bg-[#131d30] border border-slate-200 dark:border-slate-800 shadow-xs">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <div className="flex items-center gap-2">
                  <span
                    style={{ backgroundColor: '#df2029' }}
                    className="w-6 h-6 rounded-lg text-white text-xs font-bold flex items-center justify-center shadow-xs"
                  >
                    3
                  </span>
                  <h3 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wide">
                    Paso 3: Mini Pitch
                  </h3>
                </div>

                {/* Sub-tabs selector */}
                <div className="flex items-center p-0.5 rounded-lg bg-slate-200 dark:bg-slate-800 text-xs">
                  <button
                    type="button"
                    onClick={() => setMiniPitchSubTab('interes')}
                    className={`px-2.5 py-1 rounded-md font-medium transition-colors ${
                      miniPitchSubTab === 'interes'
                        ? 'bg-white dark:bg-[#0c121d] text-[#df2029] dark:text-[#ff6b72] shadow-xs'
                        : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
                    }`}
                  >
                    Por Motivo de Interés ({miniPitchesInteres.length})
                  </button>
                  <button
                    type="button"
                    onClick={() => setMiniPitchSubTab('motivacion')}
                    className={`px-2.5 py-1 rounded-md font-medium transition-colors ${
                      miniPitchSubTab === 'motivacion'
                        ? 'bg-white dark:bg-[#0c121d] text-[#df2029] dark:text-[#ff6b72] shadow-xs'
                        : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
                    }`}
                  >
                    Por Motivación del Prospecto ({miniPitchesMotivacion.length})
                  </button>
                </div>
              </div>

              {/* LISTA DE MINI PITCHES SEGÚN SUBTAB */}
              <div className="space-y-2.5 pt-1">
                {(miniPitchSubTab === 'interes' ? miniPitchesInteres : miniPitchesMotivacion)
                  .filter((p) => matchText(p.categoria) || matchText(p.guion) || matchText(p.titulo))
                  .map((pitch) => (
                    <div
                      key={pitch.id}
                      className="p-3 rounded-lg bg-white dark:bg-[#0c121d] border border-slate-200 dark:border-slate-800 space-y-2 hover:border-[#df2029]/40 transition-all"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <span
                            style={{ color: '#df2029' }}
                            className="inline-block px-2 py-0.5 rounded text-[11px] font-bold bg-red-50 dark:bg-[#df2029]/20 border border-red-200 dark:border-[#df2029]/30"
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
                        style={{ borderLeftColor: '#df2029' }}
                        className="text-xs text-slate-700 dark:text-slate-300 leading-relaxed italic border-l-2 pl-2.5"
                      >
                        {pitch.guion}
                      </p>
                    </div>
                  ))}
              </div>
            </section>
          )}

          {/* ─────────────────────────────────────────────────────────────
              PASO 4: GENERACION DE LA CITA
              ───────────────────────────────────────────────────────────── */}
          {showPaso4 && (
            <section className="space-y-3 rounded-xl p-4 bg-slate-50 dark:bg-[#131d30] border border-slate-200 dark:border-slate-800 shadow-xs">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span
                    style={{ backgroundColor: '#df2029' }}
                    className="w-6 h-6 rounded-lg text-white text-xs font-bold flex items-center justify-center shadow-xs"
                  >
                    4
                  </span>
                  <h3 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wide">
                    Paso 4: Generación de la Cita
                  </h3>
                </div>
                <span className="text-[11px] font-semibold text-emerald-700 dark:text-emerald-300 bg-emerald-100 dark:bg-emerald-950/60 px-2 py-0.5 rounded-full border border-emerald-200 dark:border-emerald-800">
                  Cierre de cita
                </span>
              </div>

              <div className="bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-900/60 p-2.5 rounded-lg text-xs text-emerald-900 dark:text-emerald-200 flex items-start gap-2">
                <Target size={14} className="text-emerald-600 shrink-0 mt-0.5" />
                <p>
                  <span className="font-bold">Objetivo:</span> convertir el interés del prospecto en una cita concreta, <strong className="underline">priorizando la visita domiciliaria</strong>.
                </p>
              </div>

              {/* OPCION 1: VISITA DOMICILIARIA (#df2029) */}
              <div
                style={{ borderColor: 'rgba(223, 32, 41, 0.35)' }}
                className="p-3.5 rounded-lg bg-white dark:bg-[#0c121d] border-2 space-y-2"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Home size={16} style={{ color: '#df2029' }} />
                    <span
                      style={{ color: '#df2029' }}
                      className="text-xs font-bold uppercase tracking-wide"
                    >
                      1. Primera opción: Visita domiciliaria (Prioridad 1)
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      copyText(
                        'p4-domicilio',
                        `“${prospecto}, por teléfono sería complicado explicarte todos los detalles de nuestro programa, por eso me gustaría que podamos reunirnos personalmente. De hecho, tenemos la posibilidad de visitarte en tu domicilio para brindarte una asesoría personalizada. Hoy por la tarde, ¿a qué hora te queda bien que nos reunamos?
¡Perfecto! ¿Me indicas, por favor, tu dirección y alguna referencia para poder llegar sin inconvenientes? ¿Manejas algún otro número de celular donde podamos contactarte en caso de algún inconveniente con la señal o batería?
¡Genial! Entonces voy a agendar nuestra visita.”`
                      )
                    }
                    style={{ color: '#df2029' }}
                    className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-red-50 hover:bg-red-100 dark:bg-[#df2029]/15 dark:hover:bg-[#df2029]/25 transition-colors"
                  >
                    {copiedKey === 'p4-domicilio' ? <Check size={11} className="text-emerald-500" /> : <Copy size={11} />}
                    <span>{copiedKey === 'p4-domicilio' ? '¡Copiado!' : 'Copiar'}</span>
                  </button>
                </div>
                <div
                  style={{ borderLeftColor: '#df2029' }}
                  className="text-xs text-slate-700 dark:text-slate-300 leading-relaxed italic border-l-2 pl-2.5 space-y-1.5"
                >
                  <p>
                    “<span className="font-bold">{prospecto}</span>, por teléfono sería complicado explicarte todos los detalles de nuestro programa, por eso me gustaría que podamos reunirnos personalmente. De hecho, tenemos la posibilidad de visitarte en tu domicilio para brindarte una asesoría personalizada. Hoy por la tarde, ¿a qué hora te queda bien que nos reunamos?
                  </p>
                  <p>
                    ¡Perfecto! ¿Me indicas, por favor, tu dirección y alguna referencia para poder llegar sin inconvenientes? ¿Manejas algún otro número de celular donde podamos contactarte en caso de algún inconveniente con la señal o batería?
                  </p>
                  <p className="font-semibold text-emerald-600 dark:text-emerald-400">
                    ¡Genial! Entonces voy a agendar nuestra visita.”
                  </p>
                </div>
              </div>

              {/* OPCION 2: SEDES BRIGHTON */}
              <div className="p-3.5 rounded-lg bg-white dark:bg-[#0c121d] border border-slate-200 dark:border-slate-800 space-y-2.5">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Building2 size={16} className="text-slate-600 dark:text-slate-400" />
                    <span className="text-xs font-bold text-slate-800 dark:text-slate-200 uppercase tracking-wide">
                      2. Segunda opción: Cita en oficinas Brighton
                    </span>
                  </div>
                  <span className="text-[10px] text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-950/40 px-2 py-0.5 rounded border border-amber-200 dark:border-amber-900">
                    Solo si objeta: «Prefiero visitarlos en su oficina»
                  </span>
                </div>

                <div className="text-xs text-slate-700 dark:text-slate-300 leading-relaxed italic border-l-2 border-slate-400 pl-2.5 space-y-1">
                  <p>
                    “¡Claro que sí, <span className="font-bold">{prospecto}</span>! No hay ningún problema. Nosotros contamos con dos oficinas en Arequipa: nuestra sede de Umacollo y nuestra sede de Bustamante. ¿Cuál de las dos te queda mejor?”
                  </p>
                </div>

                {/* TARJETAS DE SEDES CON DIRECCIONES Y COPIADO */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1 text-xs">
                  <div className="p-2.5 rounded-lg bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span style={{ color: '#df2029' }} className="font-bold flex items-center gap-1">
                        <MapPin size={12} /> Sede Umacollo
                      </span>
                      <button
                        type="button"
                        onClick={() => copyText('dir-umacollo', 'Calle González Prada 110, Umacollo, Arequipa')}
                        className="p-1 rounded text-slate-400 hover:text-[#df2029]"
                        title="Copiar dirección"
                      >
                        {copiedKey === 'dir-umacollo' ? <Check size={11} className="text-emerald-500" /> : <Copy size={11} />}
                      </button>
                    </div>
                    <p className="font-mono text-[11px] text-slate-700 dark:text-slate-300">
                      Calle González Prada 110
                    </p>
                    <p className="text-[11px] text-slate-500 italic">
                      “¡Perfecto! Nuestra sede de Umacollo se encuentra en calle González Prada 110. Te voy a compartir la ubicación para que puedas llegar sin inconvenientes. Hoy, ¿a qué hora te quedaría bien acercarte?”
                    </p>
                    <div className="pt-1 flex items-center gap-1.5 flex-wrap border-t border-slate-200/60 dark:border-slate-800 text-[10px]">
                      <button
                        type="button"
                        onClick={() => copyText('sede-link-ub-uma', 'https://drive.google.com/file/d/1rLkps_7V2GGLEbb4M7N9xXY433cpfSg0/view?usp=sharing')}
                        className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:text-[#df2029]"
                        title="Copiar link de ubicación"
                      >
                        {copiedKey === 'sede-link-ub-uma' ? <Check size={10} className="text-emerald-500" /> : <Copy size={10} />}
                        <span>{copiedKey === 'sede-link-ub-uma' ? '¡Copiado!' : 'Link Ubicación'}</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => copyText('sede-link-rec-uma', 'https://drive.google.com/file/d/10iVWCXRsKgcD0osJdYLPOsgnCgHaS9Y_/view?usp=sharing')}
                        className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:text-[#df2029]"
                        title="Copiar link de recorrido virtual"
                      >
                        {copiedKey === 'sede-link-rec-uma' ? <Check size={10} className="text-emerald-500" /> : <Video size={10} />}
                        <span>{copiedKey === 'sede-link-rec-uma' ? '¡Copiado!' : 'Link Recorrido'}</span>
                      </button>
                    </div>
                  </div>

                  <div className="p-2.5 rounded-lg bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span style={{ color: '#df2029' }} className="font-bold flex items-center gap-1">
                        <MapPin size={12} /> Sede Bustamante
                      </span>
                      <button
                        type="button"
                        onClick={() => copyText('dir-bustamante', 'Calle Danubio 233, José Luis Bustamante y Rivero, Arequipa')}
                        className="p-1 rounded text-slate-400 hover:text-[#df2029]"
                        title="Copiar dirección"
                      >
                        {copiedKey === 'dir-bustamante' ? <Check size={11} className="text-emerald-500" /> : <Copy size={11} />}
                      </button>
                    </div>
                    <p className="font-mono text-[11px] text-slate-700 dark:text-slate-300">
                      Calle Danubio 233
                    </p>
                    <p className="text-[11px] text-slate-500 italic">
                      “¡Perfecto! Nuestra sede de Bustamante se encuentra en calle Danubio 233. Te voy a compartir la ubicación para que puedas llegar sin inconvenientes. Hoy, ¿a qué hora te quedaría bien acercarte?”
                    </p>
                    <div className="pt-1 flex items-center gap-1.5 flex-wrap border-t border-slate-200/60 dark:border-slate-800 text-[10px]">
                      <button
                        type="button"
                        onClick={() => copyText('sede-link-ub-jbyr', 'https://drive.google.com/file/d/1ebBjJcBROwK0Te2SG7ZmDDUqTNzKqMHJ/view?usp=sharing')}
                        className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:text-[#df2029]"
                        title="Copiar link de ubicación"
                      >
                        {copiedKey === 'sede-link-ub-jbyr' ? <Check size={10} className="text-emerald-500" /> : <Copy size={10} />}
                        <span>{copiedKey === 'sede-link-ub-jbyr' ? '¡Copiado!' : 'Link Ubicación'}</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => copyText('sede-link-rec-jbyr', 'https://drive.google.com/file/d/1jcGZS3HQd3hbWxxvcC5f7koREpIiGaBD/view?usp=sharing')}
                        className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:text-[#df2029]"
                        title="Copiar link de recorrido virtual"
                      >
                        {copiedKey === 'sede-link-rec-jbyr' ? <Check size={10} className="text-emerald-500" /> : <Video size={10} />}
                        <span>{copiedKey === 'sede-link-rec-jbyr' ? '¡Copiado!' : 'Link Recorrido'}</span>
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              {/* OPCION 3: VIRTUAL ZOOM / MEET */}
              <div className="p-3.5 rounded-lg bg-white dark:bg-[#0c121d] border border-slate-200 dark:border-slate-800 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Video size={16} className="text-sky-600" />
                    <span className="text-xs font-bold text-slate-800 dark:text-slate-200 uppercase tracking-wide">
                      3. Tercera opción: Cita virtual por Zoom o Google Meet
                    </span>
                  </div>
                  <span className="text-[10px] text-sky-700 dark:text-sky-300 bg-sky-50 dark:bg-sky-950/40 px-2 py-0.5 rounded border border-sky-200 dark:border-sky-900">
                    Otras ciudades o si prefieren virtual
                  </span>
                </div>

                <div className="text-xs text-slate-700 dark:text-slate-300 leading-relaxed italic border-l-2 border-sky-400 pl-2.5 space-y-1.5">
                  <p>
                    “¡Perfecto, <span className="font-bold">{prospecto}</span>! Como te encuentras en otra ciudad, podemos reunirnos de manera virtual.
                  </p>
                  <p>
                    Explicarte todos los detalles de nuestro programa por una llamada telefónica sería un poco complicado, por eso me gustaría que tengamos una breve reunión por Zoom o Meet, donde pueda explicarte nuestra metodología, horarios y costos, y resolver todas tus inquietudes.
                  </p>
                  <p>
                    El día de hoy, ¿a qué hora te queda bien que nos reunamos?
                  </p>
                  <p className="font-semibold text-sky-600 dark:text-sky-400">
                    ¡Excelente! Te voy a enviar el enlace de nuestra reunión por WhatsApp.”
                  </p>
                </div>
              </div>

              {/* REGLAS NO NEGOCIABLES DEL PASO 4 */}
              <div className="p-3 rounded-lg bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/60 text-xs space-y-1.5">
                <div className="flex items-center gap-1.5 font-bold text-rose-800 dark:text-rose-300">
                  <ShieldAlert size={14} className="text-rose-600" />
                  <span>Reglas no negociables del Paso 4:</span>
                </div>
                <ul className="list-disc list-inside space-y-1 text-rose-900 dark:text-rose-200 pl-1">
                  <li>Priorizar la visita domiciliaria en Arequipa.</li>
                  <li>Proponer la cita para el mismo día o el siguiente.</li>
                  <li>La cita en sede se da solo si el cliente prefiere acudir a Brighton.</li>
                  <li>Ofrecer Zoom o Meet para prospectos de otras ciudades o cuando corresponda.</li>
                  <li>Confirmar fecha, hora, lugar o enlace y registrar la cita en CRM.</li>
                </ul>
              </div>
            </section>
          )}

          {/* ─────────────────────────────────────────────────────────────
              PASO 5: AUTONOMÍA DE LA DECISIÓN
              ───────────────────────────────────────────────────────────── */}
          {showPaso5 && (
            <section className="space-y-3 rounded-xl p-4 bg-slate-50 dark:bg-[#131d30] border border-slate-200 dark:border-slate-800 shadow-xs">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span
                    style={{ backgroundColor: '#df2029' }}
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
                      `“${prospecto}, una consulta adicional: cuando decides invertir en tus estudios, ¿tanto la decisión académica como la económica las tomas directamente tú o acostumbras conversarlas o consultarlas con alguien de tu familia?”`
                    )
                  }
                  className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-white dark:bg-[#0c121d] border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:text-[#df2029]"
                >
                  {copiedKey === 'p5-pregunta' ? <Check size={11} className="text-emerald-500" /> : <Copy size={11} />}
                  <span>{copiedKey === 'p5-pregunta' ? '¡Copiado!' : 'Copiar'}</span>
                </button>
              </div>

              {/* Pregunta Clave */}
              <div
                style={{ borderLeftColor: '#df2029' }}
                className="p-3 rounded-lg bg-white dark:bg-[#0c121d] border border-slate-200 dark:border-slate-800 text-xs text-slate-800 dark:text-slate-200 italic border-l-2"
              >
                “<span className="font-bold">{prospecto}</span>, una consulta adicional: cuando decides invertir en tus estudios, ¿tanto la decisión académica como la económica las tomas directamente tú o acostumbras conversarlas o consultarlas con alguien de tu familia?”
              </div>

              {/* Escenarios A y B */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                {/* Escenario A */}
                <div className="p-3 rounded-lg bg-emerald-50/60 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-900/60 space-y-2">
                  <div className="flex items-center gap-1.5 font-bold text-emerald-800 dark:text-emerald-300">
                    <CheckCircle2 size={14} className="text-emerald-600" />
                    <span>Escenario A · Autonomía</span>
                  </div>
                  <div className="space-y-1 text-slate-700 dark:text-slate-300">
                    <p className="font-medium text-emerald-700 dark:text-emerald-400">
                      Prospecto: “Sí, yo tomo mis propias decisiones y asumo el pago”.
                    </p>
                    <p className="italic bg-white dark:bg-[#0c121d] p-2 rounded border border-emerald-100 dark:border-emerald-900/40">
                      Asesor: “¡Perfecto, {prospecto}! Entonces vamos a confirmar nuestra reunión para hoy a las seis de la tarde”.
                    </p>
                  </div>
                </div>

                {/* Escenario B */}
                <div className="p-3 rounded-lg bg-amber-50/60 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-900/60 space-y-2">
                  <div className="flex items-center gap-1.5 font-bold text-amber-800 dark:text-amber-300">
                    <Users size={14} className="text-amber-600" />
                    <span>Escenario B · Decisión compartida</span>
                  </div>
                  <div className="space-y-1 text-slate-700 dark:text-slate-300">
                    <p className="font-medium text-amber-700 dark:text-amber-400">
                      Prospecto: “Tengo que conversarlo con mi esposo porque él me apoyaría económicamente”.
                    </p>
                    <p className="italic bg-white dark:bg-[#0c121d] p-2 rounded border border-amber-100 dark:border-amber-900/40">
                      Asesor: “¡Perfecto, {prospecto}! Justamente para que ambos puedan conocer nuestra propuesta, resolver sus dudas y tomar una decisión con toda la información, es importante que tu esposo también esté presente en la reunión. ¿Él podría acompañarnos hoy a las seis o qué horario les quedaría bien a ambos?”
                    </p>
                  </div>
                </div>
              </div>

              {/* Regla comercial no negociable */}
              <div className="p-3 rounded-lg bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/60 text-xs space-y-1 text-rose-900 dark:text-rose-200">
                <p className="font-bold text-rose-800 dark:text-rose-300 flex items-center gap-1.5">
                  <ShieldAlert size={14} className="text-rose-600" />
                  Regla comercial no negociable:
                </p>
                <p>
                  Una cita de cierre calificada debe contar con la participación de todas las personas cuya aprobación académica o económica sea indispensable para concretar la matrícula.
                </p>
                <p className="text-[11px] text-rose-700 dark:text-rose-400">
                  • Si tiene autonomía: se confirma directamente.
                  <br />
                  • Si es compartida: se coordina un horario en el que puedan participar los decisores.
                </p>
              </div>
            </section>
          )}

          {/* ─────────────────────────────────────────────────────────────
              PASO 6: CONFIRMACIÓN Y ASENTAMIENTO
              ───────────────────────────────────────────────────────────── */}
          {showPaso6 && (
            <section className="space-y-3 rounded-xl p-4 bg-slate-50 dark:bg-[#131d30] border border-slate-200 dark:border-slate-800 shadow-xs">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span
                    style={{ backgroundColor: '#df2029' }}
                    className="w-6 h-6 rounded-lg text-white text-xs font-bold flex items-center justify-center shadow-xs"
                  >
                    6
                  </span>
                  <h3 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wide">
                    Paso 6: Confirmación y Asentamiento
                  </h3>
                </div>
                <span
                  style={{ color: '#df2029', borderColor: '#df2029' }}
                  className="text-[11px] font-semibold bg-red-50 dark:bg-[#df2029]/20 px-2 py-0.5 rounded-full border border-opacity-30"
                >
                  Compromiso
                </span>
              </div>

              {/* Confirmación para Visita Domiciliaria */}
              <div className="p-3 rounded-lg bg-white dark:bg-[#0c121d] border border-slate-200 dark:border-slate-800 space-y-2">
                <div className="flex items-center justify-between">
                  <span style={{ color: '#df2029' }} className="text-xs font-bold flex items-center gap-1.5">
                    <Home size={13} /> Para visita domiciliaria
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      copyText(
                        'p6-dom',
                        `“¡Perfecto, ${prospecto}! Entonces quedamos para hoy a las 6:00 p. m. en tu domicilio.
En este momento estoy agendando nuestra reunión y te voy a pedir que tú también la agendes, para evitar cualquier inconveniente.
Durante mi visita te voy a presentar una excelente propuesta académica y económica, explicándote nuestra metodología, horarios y costos.
Si te gusta y se adapta a lo que estás buscando, puedes aprovecharla y matricularte en ese mismo momento. Y si no, no hay ningún problema, te quedará toda la información para que puedas evaluarla con tranquilidad.
Mi nombre es ${defaultAsesor} y en unos minutos te enviaré un WhatsApp confirmando nuestra cita.
¡Nos vemos a las seis, que tengas bonito día!”`
                      )
                    }
                    className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 hover:text-[#df2029]"
                  >
                    {copiedKey === 'p6-dom' ? <Check size={11} className="text-emerald-500" /> : <Copy size={11} />}
                    <span>{copiedKey === 'p6-dom' ? '¡Copiado!' : 'Copiar'}</span>
                  </button>
                </div>
                <div
                  style={{ borderLeftColor: '#df2029' }}
                  className="text-xs text-slate-700 dark:text-slate-300 leading-relaxed italic border-l-2 pl-2.5 space-y-1"
                >
                  <p>“¡Perfecto, <span className="font-bold">{prospecto}</span>! Entonces quedamos para hoy a las 6:00 p. m. en tu domicilio.</p>
                  <p>En este momento estoy agendando nuestra reunión y te voy a pedir que tú también la agendes, para evitar cualquier inconveniente.</p>
                  <p>Durante mi visita te voy a presentar una excelente propuesta académica y económica, explicándote nuestra metodología, horarios y costos.</p>
                  <p>Si te gusta y se adapta a lo que estás buscando, puedes aprovecharla y matricularte en ese mismo momento. Y si no, no hay ningún problema, te quedará toda la información para que puedas evaluarla con tranquilidad.</p>
                  <p style={{ color: '#df2029' }} className="font-semibold">
                    Mi nombre es {defaultAsesor} y en unos minutos te enviaré un WhatsApp confirmando nuestra cita. ¡Nos vemos a las seis, que tengas bonito día!”
                  </p>
                </div>
              </div>

              {/* Confirmación para Visita en Oficina */}
              <div className="p-3 rounded-lg bg-white dark:bg-[#0c121d] border border-slate-200 dark:border-slate-800 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-slate-700 dark:text-slate-300 flex items-center gap-1.5">
                    <Building2 size={13} /> Para visita en oficina
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      copyText(
                        'p6-ofic',
                        `“En este momento estoy agendando nuestra reunión y te voy a pedir que tú también la agendes.
Te comento que normalmente realizo visitas y asesorías fuera de la oficina. Sin embargo, como hemos coordinado reunirnos a esa hora, voy a organizar mi agenda para estar personalmente y atenderte. Durante nuestra reunión te voy a presentar una excelente propuesta académica y económica. Si te gusta y se adapta a lo que estás buscando, puedes aprovecharla y matricularte en ese momento. Y si no, te quedará toda la información.
En unos minutos te enviaré un WhatsApp con la ubicación y la confirmación de nuestra cita. ¡Nos vemos a las seis, que tengas bonito día!”`
                      )
                    }
                    className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 hover:text-[#df2029]"
                  >
                    {copiedKey === 'p6-ofic' ? <Check size={11} className="text-emerald-500" /> : <Copy size={11} />}
                    <span>{copiedKey === 'p6-ofic' ? '¡Copiado!' : 'Copiar'}</span>
                  </button>
                </div>
                <div className="text-xs text-slate-700 dark:text-slate-300 leading-relaxed italic border-l-2 border-slate-400 pl-2.5 space-y-1">
                  <p>“En este momento estoy agendando nuestra reunión y te voy a pedir que tú también la agendes.</p>
                  <p>Te comento que normalmente realizo visitas y asesorías fuera de la oficina. Sin embargo, como hemos coordinado reunirnos a esa hora, voy a organizar mi agenda para estar personalmente y atenderte. Durante nuestra reunión te voy a presentar una excelente propuesta académica y económica. Si te gusta y se adapta a lo que estás buscando, puedes aprovecharla y matricularte en ese momento. Y si no, te quedará toda la información.</p>
                  <p style={{ color: '#df2029' }} className="font-semibold">
                    En unos minutos te enviaré un WhatsApp con la ubicación y la confirmación de nuestra cita. ¡Nos vemos a las seis, que tengas bonito día!”
                  </p>
                </div>
              </div>
            </section>
          )}

          {/* ─────────────────────────────────────────────────────────────
              ANEXO DE GUIONES: OBJECIONES DE LLAMADA TELEFONICA
              ───────────────────────────────────────────────────────────── */}
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

          {/* ─────────────────────────────────────────────────────────────
              LINKS DE INTERÉS: RECORRIDOS, UBICACIONES Y MATERIAL DE SEDES
              ───────────────────────────────────────────────────────────── */}
          {showLinks && (
            <section className="space-y-3 rounded-xl p-4 bg-slate-50 dark:bg-[#131d30] border border-slate-200 dark:border-slate-800 shadow-xs">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <div
                    style={{ backgroundColor: '#df2029' }}
                    className="w-6 h-6 rounded-lg text-white flex items-center justify-center font-bold text-xs shadow-xs"
                  >
                    <Link2 size={13} />
                  </div>
                  <h3 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wide">
                    Links de Interés
                  </h3>
                </div>
                <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-red-50 dark:bg-[#df2029]/20 text-[#df2029] dark:text-[#ff6b72] border border-red-200 dark:border-[#df2029]/30">
                  {linksDeInteres.length} Enlaces
                </span>
              </div>

              <div className="bg-red-50/60 dark:bg-red-950/20 border border-red-100 dark:border-red-900/40 p-2.5 rounded-lg text-xs text-slate-700 dark:text-slate-300 flex items-start gap-2">
                <Target size={14} className="text-[#df2029] shrink-0 mt-0.5" />
                <p>
                  <span className="font-bold text-slate-900 dark:text-white">Herramienta rápida:</span> copia el enlace directo para enviarlo al prospecto por WhatsApp o ábrelo en Google Drive con un solo clic.
                </p>
              </div>

              <div className="space-y-2.5 pt-1">
                {linksDeInteres
                  .filter((l) => matchText(l.titulo) || matchText(l.descripcion) || matchText(l.categoria) || matchText(l.url))
                  .map((link) => {
                    const isCopied = copiedKey === link.id
                    return (
                      <div
                        key={link.id}
                        className="p-3 rounded-lg bg-white dark:bg-[#0c121d] border border-slate-200 dark:border-slate-800 space-y-2 hover:border-[#df2029]/40 transition-all shadow-2xs"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="space-y-1">
                            <div className="flex items-center gap-1.5 flex-wrap">
                              <span
                                style={{ color: '#df2029' }}
                                className="inline-block px-2 py-0.5 rounded text-[10px] font-bold bg-red-50 dark:bg-[#df2029]/20 border border-red-200 dark:border-[#df2029]/30"
                              >
                                {link.categoria}
                              </span>
                              <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
                                {link.tipo}
                              </span>
                            </div>
                            <h4 className="text-xs font-bold text-slate-900 dark:text-slate-100 flex items-center gap-1.5 mt-0.5">
                              {link.tipo === 'Recorrido' ? (
                                <Video size={13} className="text-[#df2029] shrink-0" />
                              ) : link.tipo === 'Ubicación' ? (
                                <MapPin size={13} className="text-[#df2029] shrink-0" />
                              ) : (
                                <Sparkles size={13} className="text-[#df2029] shrink-0" />
                              )}
                              <span>{link.titulo}</span>
                            </h4>
                          </div>

                          <div className="flex items-center gap-1 shrink-0">
                            <button
                              type="button"
                              onClick={() => copyText(link.id, link.url)}
                              className="flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-md bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 hover:text-[#df2029] transition-colors cursor-pointer"
                              title="Copiar link para WhatsApp"
                            >
                              {isCopied ? <Check size={11} className="text-emerald-500" /> : <Copy size={11} />}
                              <span className="font-medium">{isCopied ? '¡Copiado!' : 'Copiar'}</span>
                            </button>
                            <a
                              href={link.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="p-1.5 rounded-md bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 hover:text-[#df2029] transition-colors inline-flex items-center justify-center cursor-pointer"
                              title="Abrir enlace en Google Drive"
                            >
                              <ExternalLink size={13} />
                            </a>
                          </div>
                        </div>

                        <p className="text-[11px] text-slate-600 dark:text-slate-400 leading-snug">
                          {link.descripcion}
                        </p>

                        <div className="pt-1.5 border-t border-slate-100 dark:border-slate-800/80 flex items-center justify-between text-[10px] text-slate-400 font-mono">
                          <span className="truncate max-w-[280px] sm:max-w-[380px]" title={link.url}>
                            {link.url}
                          </span>
                        </div>
                      </div>
                    )
                  })}
              </div>
            </section>
          )}

          {/* MENSAJE CUANDO NINGÚN RESULTADO COINCIDE CON LA BÚSQUEDA */}
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
                style={{ color: '#df2029' }}
                className="text-xs hover:underline"
              >
                Limpiar búsqueda y ver todo
              </button>
            </div>
          )}
        </div>

        {/* FOOTER INFORMATIVO CON ACCESOS RÁPIDOS */}
        <div className="px-5 py-3 border-t border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-[#131d30] flex items-center justify-between text-xs text-slate-500 dark:text-slate-400 shrink-0">
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1">
              <MapPin size={12} style={{ color: '#df2029' }} />
              Umacollo: González Prada 110
            </span>
            <span className="hidden sm:inline">|</span>
            <span className="hidden sm:flex items-center gap-1">
              <MapPin size={12} style={{ color: '#df2029' }} />
              Bustamante: Danubio 233
            </span>
          </div>
          <span className="text-[11px] font-mono">Brighton CRM</span>
        </div>
      </aside>
    </>
  )
}
