/**
 * Tests del helper de telefonos — V070.96 + V070.98.
 *
 * Garantiza paridad con el backend (ingest_core.clean_phone) y el patron
 * patrón estándar de dirty-validation para EDICION de leads existentes.
 */
import { describe, it, expect } from 'vitest';
import { normalizePhonePE, normalizePhonePEEdit } from '@/lib/phone';

describe('normalizePhonePE — validacion estandar', () => {
  it('acepta movil PE de 9 digitos empezando con 9', () => {
    const r = normalizePhonePE('987654321');
    expect(r.valid).toBe(true);
    expect(r.normalized).toBe('+51987654321');
  });

  it('acepta PE con codigo pais', () => {
    const r = normalizePhonePE('+51987654321');
    expect(r.valid).toBe(true);
    expect(r.normalized).toBe('+51987654321');
  });

  it('normaliza con separadores', () => {
    expect(normalizePhonePE('+51 987 654 321').normalized).toBe('+51987654321');
    expect(normalizePhonePE('(987) 654-321').normalized).toBe('+51987654321');
  });

  it('rechaza +51999999999 como junk (anti-junk)', () => {
    const r = normalizePhonePE('+51999999999');
    expect(r.valid).toBe(false);
    expect(r.error).toMatch(/prueba/i);
  });

  it('rechaza 8 digitos como movil PE incompleto', () => {
    const r = normalizePhonePE('97845323');
    expect(r.valid).toBe(false);
  });

  it('rechaza 10 digitos sin codigo pais (ambiguo)', () => {
    const r = normalizePhonePE('9876543210');
    expect(r.valid).toBe(false);
    expect(r.error).toMatch(/codigo de pais/i);
  });

  it('rechaza 9 digitos que no empiezan con 9', () => {
    expect(normalizePhonePE('123456789').valid).toBe(false);
  });

  it('rechaza numeros de prueba conocidos', () => {
    expect(normalizePhonePE('+15555555555').valid).toBe(false);
    expect(normalizePhonePE('+11234567890').valid).toBe(false);
  });
});

describe('normalizePhonePEEdit — patrón estándar dirty validation', () => {
  it('caso unchanged + valido → como normalizePhonePE', () => {
    const r = normalizePhonePEEdit('+51987654321', '+51987654321');
    expect(r.valid).toBe(true);
    expect(r.warning).toBeNull();
  });

  it('caso unchanged + legacy junk → permite guardar con warning amber', () => {
    // Bug reportado: Leonardo Bellido con +51999999999 cargado. Al abrir
    // edit, antes era error rojo bloqueante. Ahora warning suave.
    const r = normalizePhonePEEdit('+51999999999', '+51999999999');
    expect(r.valid).toBe(true);
    expect(r.normalized).toBe('+51999999999');
    expect(r.warning).toMatch(/legacy/i);
    expect(r.error).toBeNull();
  });

  it('caso changed + invalido → bloquea como estricto', () => {
    // Usuario tipea junk nuevo distinto al original cargado.
    const r = normalizePhonePEEdit('+51000000000', '+51987654321');
    expect(r.valid).toBe(false);
    expect(r.error).toBeTruthy();
    expect(r.warning).toBeNull();
  });

  it('caso changed + valido → como normalizePhonePE', () => {
    // Usuario reemplaza junk legacy con un numero valido.
    const r = normalizePhonePEEdit('+51986777920', '+51999999999');
    expect(r.valid).toBe(true);
    expect(r.normalized).toBe('+51986777920');
    expect(r.warning).toBeNull();
  });

  it('caso sin valor inicial (CREATE-like) → no aplica fallback legacy', () => {
    const r = normalizePhonePEEdit('+51999999999', '');
    expect(r.valid).toBe(false);
    expect(r.warning).toBeNull();
  });

  it('caso digitos iguales pero formato distinto cuenta como unchanged', () => {
    // El usuario solo agrega/quita separadores; los digitos no cambian.
    const r = normalizePhonePEEdit('+51 999 999 999', '+51999999999');
    expect(r.valid).toBe(true);
    expect(r.warning).toMatch(/legacy/i);
  });
});
