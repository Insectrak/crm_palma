import { describe, it, expect } from 'vitest'
import { formatDate, formatDateTime, getStatusColor } from '@/lib/utils'


describe('formatDate', () => {
  it('convierte ISO YYYY-MM-DD a DD/MM/YYYY', () => {
    expect(formatDate('2026-04-12')).toBe('12/04/2026')
  })

  it('retorna null para string vacio', () => {
    expect(formatDate('')).toBeNull()
  })

  it('retorna null para null', () => {
    expect(formatDate(null)).toBeNull()
  })

  it('preserva DD/MM/YYYY ya formateado', () => {
    expect(formatDate('12/04/2026')).toBe('12/04/2026')
  })

  it('maneja fechas con hora (solo extrae fecha)', () => {
    expect(formatDate('2026-04-12T14:30:00')).toBe('12/04/2026')
  })
})


describe('formatDateTime', () => {
  it('convierte ISO con hora a DD/MM/YYYY HH:MM', () => {
    expect(formatDateTime('2026-04-12T14:30')).toBe('12/04/2026 14:30')
  })

  it('acepta espacio como separador de fecha y hora', () => {
    expect(formatDateTime('2026-04-12 09:15')).toBe('12/04/2026 09:15')
  })

  it('delega a formatDate si no hay hora', () => {
    expect(formatDateTime('2026-04-12')).toBe('12/04/2026')
  })

  it('retorna null para null', () => {
    expect(formatDateTime(null)).toBeNull()
  })
})


describe('getStatusColor', () => {
  it('retorna verde para procesado', () => {
    expect(getStatusColor('procesado')).toContain('green')
  })

  it('retorna amarillo para pendiente', () => {
    expect(getStatusColor('pendiente')).toContain('yellow')
  })

  it('retorna rojo para error', () => {
    expect(getStatusColor('error')).toContain('red')
  })

  it('retorna gris para estado desconocido', () => {
    expect(getStatusColor('otro')).toContain('gray')
  })

  it('es case-insensitive', () => {
    expect(getStatusColor('PROCESADO')).toContain('green')
  })

  it('maneja null sin error', () => {
    expect(getStatusColor(null)).toContain('gray')
  })
})
