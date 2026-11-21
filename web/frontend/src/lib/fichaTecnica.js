/**
 * Definición centralizada del cuestionario de la Ficha Técnica para leads.
 */

export const FICHA_TECNICA_FIELDS = [
  {
    key: 'motivacion',
    label: 'Motivación',
    pregunta: '¿Qué fue lo que más te llamó la atención de nuestra publicidad? / ¿Qué te animó a contactarnos?',
    placeholder: 'Ej: Vio publicidad de clases conversacionales en Instagram, busca mejorar su fluidez...',
    rows: 2,
  },
  {
    key: 'beneficiario',
    label: 'Beneficiario',
    pregunta: '¿El interés por aprender inglés es para ti o para algún miembro de tu familia?',
    placeholder: 'Ej: Para sí mismo / Para su hijo de 14 años / Para su cónyuge...',
    rows: 2,
  },
  {
    key: 'ubicacion',
    label: 'Ubicación',
    pregunta: '¿Te encuentras en Arequipa o en otra ciudad? ¿En qué distrito?',
    placeholder: 'Ej: Arequipa - Distrito Cayma / Yanahuara / Otra ciudad...',
    rows: 2,
  },
  {
    key: 'experiencia_previa',
    label: 'Experiencia previa',
    pregunta: '¿Anteriormente habías intentado estudiar inglés? ¿Dónde estudiaste? ¿Qué pasó? ¿Por qué crees que no lograste aprender?',
    placeholder: 'Ej: Estudió básico en instituto hace 2 años, no logró soltarse al hablar por falta de práctica...',
    rows: 3,
  },
  {
    key: 'necesidad_actual',
    label: 'Necesidad actual',
    pregunta: '¿Por qué es importante para ti aprender inglés hoy? ¿A qué te dedicas actualmente?',
    placeholder: 'Ej: Ingeniero de sistemas, necesita inglés para reuniones con clientes internacionales...',
    rows: 3,
  },
  {
    key: 'inicio',
    label: 'Inicio',
    pregunta: '¿Para cuándo te gustaría empezar?',
    placeholder: 'Ej: De inmediato / Primera semana del próximo mes...',
    rows: 2,
  },
]

/**
 * Calcula las estadísticas de llenado de la Ficha Técnica.
 * @param {Object} ficha - Objeto con las respuestas de la ficha técnica.
 * @returns {{ completedCount: number, total: number, isComplete: boolean, percentage: number, pendingKeys: string[], completedKeys: string[] }}
 */
export function getFichaTecnicaStats(ficha) {
  const total = FICHA_TECNICA_FIELDS.length
  if (!ficha || typeof ficha !== 'object') {
    return {
      completedCount: 0,
      total,
      isComplete: false,
      percentage: 0,
      pendingKeys: FICHA_TECNICA_FIELDS.map(f => f.key),
      completedKeys: [],
    }
  }

  const completedKeys = FICHA_TECNICA_FIELDS.filter(f => {
    const val = ficha[f.key]
    return typeof val === 'string' && val.trim().length > 0
  }).map(f => f.key)

  const pendingKeys = FICHA_TECNICA_FIELDS.filter(f => !completedKeys.includes(f.key)).map(f => f.key)
  const completedCount = completedKeys.length

  return {
    completedCount,
    total,
    isComplete: completedCount === total,
    percentage: Math.round((completedCount / total) * 100),
    pendingKeys,
    completedKeys,
  }
}
