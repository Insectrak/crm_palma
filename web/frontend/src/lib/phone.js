// Validacion y normalizacion de telefonos — paridad con backend
// app/services/integrations/ingest_core.py::clean_phone (V070.96).
//
// Estandar CRM clase mundial (CRMs profesionales):
//   - Movil PE: 9 digitos empezando con 9 → +51XXXXXXXXX
//   - PE con codigo pais: 11 digitos empezando con 519
//   - Internacional E.164: 11-15 digitos (rechaza 10 digitos por
//     ambiguo: USA local? PE truncado? patrón estándar exige codigo pais)
//   - Anti-junk: rechaza todos digitos iguales (999999999) y numeros
//     de prueba conocidos (5555555555, 1234567890, etc).

const KNOWN_TEST_NUMBERS = new Set([
  '5555555555',
  '555555555',
  '1234567890',
  '0000000000',
  '1111111111',
]);

function isTestOrInvalid(digits) {
  if (!digits || digits.length < 7) return true;
  const candidates = [digits];
  if (digits.length >= 9) candidates.push(digits.slice(-9));
  if (digits.length >= 10) candidates.push(digits.slice(-10));
  for (const c of candidates) {
    if (new Set(c).size === 1) return true;       // todos iguales
    if (KNOWN_TEST_NUMBERS.has(c)) return true;   // numero de prueba
  }
  return false;
}

/**
 * Normaliza y valida un telefono.
 * @param {string} raw entrada del usuario (acepta espacios, parentesis, guiones, +)
 * @returns {{ valid: boolean, normalized: string|null, error: string|null }}
 */
export function normalizePhonePE(raw) {
  if (raw == null) return { valid: false, normalized: null, error: 'Ingresa un numero de celular.' };
  const str = String(raw).trim();
  if (!str) return { valid: false, normalized: null, error: 'Ingresa un numero de celular.' };

  // Extraer solo digitos
  const digits = str.replace(/\D+/g, '');
  if (!digits) return { valid: false, normalized: null, error: 'El numero solo debe contener digitos.' };

  // Movil PE: 9 digitos empezando con 9
  if (digits.length === 9 && digits.startsWith('9')) {
    if (isTestOrInvalid(digits)) {
      return { valid: false, normalized: null, error: 'Numero no valido (parece de prueba).' };
    }
    return { valid: true, normalized: `+51${digits}`, error: null };
  }

  // PE con codigo pais: 11 digitos 519XXXXXXXX
  if (digits.length === 11 && digits.startsWith('519')) {
    const national = digits.slice(2);  // los 9 digitos del movil
    if (isTestOrInvalid(national)) {
      return { valid: false, normalized: null, error: 'Numero no valido (parece de prueba).' };
    }
    return { valid: true, normalized: `+${digits}`, error: null };
  }

  // 9 digitos pero no empieza con 9
  if (digits.length === 9) {
    return { valid: false, normalized: null, error: 'El movil peruano debe empezar con 9.' };
  }

  // 8 digitos: tipico error de tipeo (PE no tiene moviles de 8 digitos)
  if (digits.length === 8) {
    return { valid: false, normalized: null, error: 'Faltan digitos. El movil peruano tiene 9 digitos.' };
  }

  // Menos de 8: claramente incompleto
  if (digits.length < 9) {
    return { valid: false, normalized: null, error: 'Numero demasiado corto.' };
  }

  // 10 digitos sin codigo pais: rechazar (ambiguo)
  if (digits.length === 10) {
    return { valid: false, normalized: null, error: 'Agrega el codigo de pais (ej: +51 para Peru).' };
  }

  // Internacional E.164: 11-15 digitos (NO 10)
  if (digits.length >= 11 && digits.length <= 15) {
    if (isTestOrInvalid(digits)) {
      return { valid: false, normalized: null, error: 'Numero no valido (parece de prueba).' };
    }
    return { valid: true, normalized: `+${digits}`, error: null };
  }

  // Mas de 15 digitos: excede E.164
  return { valid: false, normalized: null, error: 'Numero demasiado largo.' };
}

/**
 * Helper rapido para forms: devuelve solo el string normalizado o null si invalido.
 */
export function toE164PE(raw) {
  return normalizePhonePE(raw).normalized;
}

/**
 * Helper para validacion en onBlur (no muestra error si el campo esta vacio).
 */
export function validatePhoneOnBlur(raw) {
  if (raw == null || String(raw).trim() === '') return null;
  return normalizePhonePE(raw).error;
}

/**
 * Validacion patrón estándar para EDICION: si el valor no cambio desde el
 * valor inicial cargado del lead, permitimos guardar aunque sea junk legacy
 * (no bloqueamos editar otros campos). Si el usuario tipea un valor nuevo
 * y es junk → bloqueamos.
 *
 * @returns {{ valid: boolean, normalized: string|null, error: string|null, warning: string|null }}
 *
 * Caso 1: valor unchanged + valido → como normalizePhonePE normal.
 * Caso 2: valor unchanged + legacy invalido → valid=true, warning="..." (amber, no rojo).
 * Caso 3: valor cambiado → validacion estricta normal.
 */
export function normalizePhonePEEdit(raw, initial) {
  const rawStr = String(raw ?? '').trim();
  const initStr = String(initial ?? '').trim();
  const rawDigits = rawStr.replace(/\D+/g, '');
  const initDigits = initStr.replace(/\D+/g, '');

  // Campo unchanged respecto al inicial cargado.
  const unchanged = initDigits && rawDigits === initDigits;

  const result = normalizePhonePE(rawStr);
  if (result.valid) return { ...result, warning: null };

  if (unchanged) {
    // Legacy invalido — preservar el valor original, mostrar warning suave.
    return {
      valid: true,
      normalized: rawStr,
      error: null,
      warning: `Numero legacy: ${result.error} Editalo cuando puedas.`,
    };
  }

  // Valor cambiado por el usuario y es invalido → bloquear.
  return { ...result, warning: null };
}
