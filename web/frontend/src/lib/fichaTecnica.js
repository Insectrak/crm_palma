/**
 * Definición centralizada del cuestionario de la Ficha Técnica para leads.
 */

export const FICHA_TECNICA_FIELDS = [
  {
    key: 'tipo_lote',
    label: 'Tipo de lote',
    pregunta: '¿Qué tipo de lote estás buscando? (Residencial, campestre, comercial, metraje aprox.)',
    placeholder: 'Ej: Lote residencial de 120 m² a 160 m², cerca a parque o en esquina...',
    rows: 2,
  },
  {
    key: 'uso_lote',
    label: 'Uso / Objetivo',
    pregunta: '¿Este lote es para ti, para tu familia o por inversión?',
    placeholder: 'Ej: Para vivienda propia / Para su familia / Para inversión y plusvalía...',
    rows: 2,
  },
  {
    key: 'ubicacion',
    label: 'Ubicación actual',
    pregunta: '¿En Arequipa o en qué departamento del Perú te encuentras? Especificar distrito.',
    placeholder: 'Ej: Arequipa - Distrito Cayma / Yanahuara / Lima - Surco...',
    rows: 2,
  },
  {
    key: 'otros_proyectos',
    label: 'Otros proyectos',
    pregunta: '¿Estás cotizando otros proyectos inmobiliarios?',
    placeholder: 'Ej: Sí, evaluando 2 opciones en la zona / No, es la primera opción que consulta...',
    rows: 2,
  },
  {
    key: 'plazo_compra',
    label: 'Plazo de compra',
    pregunta: '¿Para cuándo quisieras adquirir tu lote?',
    placeholder: 'Ej: Este mes / En 1 a 3 meses / Evaluando inicial o financiamiento...',
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
