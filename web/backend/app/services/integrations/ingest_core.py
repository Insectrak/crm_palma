"""Núcleo reusable para ingestar un lead — independiente del transport.

Cualquier integración (webhook Meta, poller TikTok, endpoint legacy de
n8n, carga manual desde un formulario público, etc.) termina llamando
a `ingest_lead_core` con un payload normalizado. Aquí viven:

  - dedupe por teléfono contra leads activos
  - resolución de fuente (catálogo)
  - estado inicial 'Nuevo'
  - selección de supervisor (rotación diaria vs fijo)
  - detección de recontacto (histórico legacy + leads inactivos)
  - INSERT del lead y bump del contador de rotación

Clean Code:
  - Recibe un cursor psycopg2 abierto y devuelve el dict con el resultado;
    la transacción la maneja el caller (commit/rollback se coordina arriba).
  - SRP: no hace HTTP, no autentica, no loggea eventos de integración
    (eso le toca al caller con events_repo).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# V053: niveles que el proveedor puede declarar como estado inicial del lead.
# Allowlist estricta — el proveedor NO puede saltar a estados terminales
# (Ganado/Perdido) ni a estados de proceso interno. Si llega algo fuera de
# este set, se ignora y se cae a 'Nuevo'.
PROVIDER_NIVEL_ALLOWLIST = frozenset({"Nuevo", "Contactado"})

# Misma expresión que usaba el router original — Perú por default.
_FECHA_LIMA_EXPR = "(NOW() AT TIME ZONE 'America/Lima')::date"

_CANONICAL_FUENTES = {
    "tiktok": "TikTok",
    "tt": "TikTok",
    "tt mensaje": "TikTok",
    "tiktok ads": "TikTok",
    "tiktok lead gen": "TikTok",
    "tiktok instant form": "TikTok",
    "facebook": "Facebook",
    "fb": "Facebook",
    "fb ads": "Facebook",
    "facebook ads": "Facebook",
    "meta": "Facebook",
    "meta ads": "Facebook",
    "instagram": "Instagram",
    "ig": "Instagram",
    "ig ads": "Instagram",
    "instagram ads": "Instagram",
    "whatsapp": "WhatsApp",
    "wa": "WhatsApp",
    "wa mensaje": "WhatsApp",
    "whatsapp direct": "WhatsApp",
    "web": "Web",
    "web form": "Web",
    "formulario": "Web",
    "landing": "Web",
    "referido": "Referido",
    "referral": "Referido",
    "manual": "Manual",
    "historico": "Historico",
    "histórico": "Historico",
}


@dataclass
class IngestPayload:
    """Payload normalizado que todo driver arma antes de llamar al core."""
    fuente: str
    telefono: str
    nombres: Optional[str] = None
    apellidos: Optional[str] = None
    email: Optional[str] = None
    campana: Optional[str] = None              # campaign_id (text) — el nombre se resuelve via cache
    fuente_externa_id: Optional[str] = None
    # V068.4 — timestamp REAL del evento en el proveedor (no cuando lo
    # ingresamos al CRM). TikTok lo trae como "created_time" en el CSV.
    # Sirve para distinguir backfill (created < lead.created_at -> ignorar)
    # de reactivacion real (created > lead.created_at -> contar).
    external_created_at: Optional[datetime] = None
    observaciones: Optional[str] = None
    fuente_form_id: Optional[str] = None       # form_id — JOIN contra meta_catalog_cache para nombre
    campaign_name: Optional[str] = None        # Hint del nombre — se upserta al cache para mostrar en UI
    form_name: Optional[str] = None            # Hint del nombre del form — idem

    # V053 — campos opcionales para integracion con proveedores IA externos.
    # Se introducen como Optional para no romper compat con drivers existentes
    # (Meta nativo, TikTok, WhatsApp directo) que no los usan.
    nombre_completo: Optional[str] = None      # Fallback si no vienen nombres+apellidos por separado
    apellido: Optional[str] = None             # Schema We Do — apellido singular (a veces vacio)
    dni: Optional[str] = None                  # Documento de identidad
    # V086.1 — Datos demográficos del proveedor para enriquecer leads viejos
    # en recontactos (lead_recapture._fill_empty_fields). Solo rellenan si
    # el lead los tiene vacíos — nunca pisan info ingresada por un humano.
    ciudad: Optional[str] = None
    trabajo: Optional[str] = None
    anuncio: Optional[str] = None              # Nivel Ad de Meta
    conjunto: Optional[str] = None             # Nivel Ad Set de Meta
    nivel: Optional[str] = None                # 'Nuevo' | 'Contactado' (allowlist) — estado inicial declarado
    asesor_telefono: Optional[str] = None      # Pre-asignacion: telefono del asesor que el proveedor sugiere
    resumen_ia: Optional[str] = None           # Transcripcion / resumen de conversacion con IA del proveedor
    extra: Optional[Dict[str, Any]] = None     # Campos custom del proveedor → datos_extra JSONB

    # V085 — Trazabilidad del proveedor en recontactos. El caller (router de
    # ingest) pasa aquí el UUID del api_client autenticado. lead_recapture
    # lo lee para INSERT en crm.lead_recontactos.api_client_id, asi los
    # filtros por proveedor y los webhooks funcionan correctamente.
    # Bug previo: lead_recapture leia getattr(payload, "api_client_id", None)
    # pero el campo no existia → siempre NULL → recontactos sin proveedor.
    api_client_id: Optional[str] = None


class IngestError(Exception):
    """Errores de negocio de la ingesta (payload inválido, sin supervisor, etc.)."""
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# ── Helpers ─────────────────────────────────────────────────────────────────

def _is_test_or_invalid_phone(digits: str) -> bool:
    """Detecta telefonos basura/de prueba que generarian leads no contactables."""
    if not digits or len(digits) < 7:
        return True
    known_test = {
        "5555555555",   # +1 555 555 5555 (Norteamerica testing)
        "555555555",    # 555 555 555
        "1234567890",
        "0000000000",
        "1111111111",
    }
    candidates = [digits]
    if len(digits) >= 9:
        candidates.append(digits[-9:])
    if len(digits) >= 10:
        candidates.append(digits[-10:])
    for c in candidates:
        if len(set(c)) == 1:
            return True
        if c in known_test:
            return True
    return False


def clean_phone(raw: str) -> Optional[str]:
    """Normaliza un teléfono. Devuelve None si no pasa validación básica."""
    if not raw:
        return None
    s = re.sub(r"[\s\-\(\)\.]+", "", str(raw).strip())
    digits = re.sub(r"\D", "", s)
    if not digits or set(digits) == {"0"}:
        return None
    # Móvil peruano: 9 dígitos exactos, debe empezar con 9.
    if len(digits) == 9 and digits.startswith("9"):
        if _is_test_or_invalid_phone(digits):
            return None
        return "+51" + digits
    # Móvil peruano con código país: 519XXXXXXXX.
    if len(digits) == 11 and digits.startswith("519"):
        if _is_test_or_invalid_phone(digits[2:]):
            return None
        return "+" + digits
    # Otros países en formato E.164 (11-15 dígitos).
    if 11 <= len(digits) <= 15:
        if _is_test_or_invalid_phone(digits):
            return None
        return "+" + digits
    return None


def _resolve_fuente_id(cur, fuente_raw: str, payload: Optional[IngestPayload] = None) -> Optional[int]:
    key = (fuente_raw or "").strip().lower()

    # Si la fuente es genérica o vacía, inferir de firmas técnicas del payload
    if key in ("", "general", "lead mkt", "lead", "mkt") and payload:
        ext_id = str(payload.fuente_externa_id or "")
        form_id = str(payload.fuente_form_id or "")
        camp_id = str(payload.campana or "")
        camp_name = str(payload.campaign_name or "").lower()
        form_name = str(payload.form_name or "").lower()
        if (
            re.match(r"^\d{18,20}$", ext_id)
            or form_id.startswith("75")
            or form_id.startswith("18")
            or camp_id.startswith("75")
            or camp_id.startswith("18518")
            or "tiktok" in camp_name
            or "tiktok" in form_name
        ):
            key = "tiktok"
        elif "instagram" in camp_name or "ig" in camp_name:
            key = "instagram"
        elif "facebook" in camp_name or "meta" in camp_name:
            key = "facebook"

    canonical = _CANONICAL_FUENTES.get(key, key.capitalize() if key else "General")

    cur.execute(
        "SELECT id, nombre FROM crm.fuentes WHERE LOWER(nombre) = LOWER(%s) OR LOWER(nombre) = LOWER(%s) ORDER BY id ASC LIMIT 1",
        (canonical, key),
    )
    row = cur.fetchone()
    if row:
        return row["id"] if isinstance(row, dict) else row[0]

    # Auto-creación de la fuente canónica
    try:
        cur.execute(
            "INSERT INTO crm.fuentes (nombre, activo) VALUES (%s, TRUE) ON CONFLICT (nombre) DO UPDATE SET activo = TRUE RETURNING id",
            (canonical,),
        )
        created = cur.fetchone()
        if created:
            return created["id"] if isinstance(created, dict) else created[0]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ingest_core] error auto-creando fuente %s: %s", canonical, exc)

    cur.execute("SELECT id FROM crm.fuentes WHERE activo = TRUE ORDER BY id ASC LIMIT 1")
    fallback_row = cur.fetchone()
    return fallback_row["id"] if fallback_row else None


def _next_supervisor(cur) -> Optional[str]:
    """Round-robin diario con lock + tie-breaker DETERMINISTA (V057).

    Reglas:
      1. Menor contador del dia gana.
      2. Empate -> el que recibio HACE MAS TIEMPO (MIN(MAX(updated_at)))
         gana. Cubre el cambio de dia: el supervisor que cerro ayer NO
         debe recibir el primer lead de hoy.
      3. Empate doble (nadie recibio nunca) -> orden estable por
         created_at del usuario (alfabetico/cronologico).

    Antes esto era random.choice() y causaba que en empates de
    contadores el mismo supervisor pudiera recibir 2 leads seguidos.

    V070.78 (ADR-0010): si el supervisor candidato tiene su equipo en
    estado 'blocked' (>=80% asesores pausados/ausentes/llenos), se
    intenta encontrar otro supervisor con equipo sano. Si TODOS estan
    bloqueados, se cae al primer supervisor del orden estable (fallback
    seguro para no romper la regla "nunca rechazar un lead").
    """
    cur.execute(
        """
        SELECT id::text AS id
        FROM auth.users
        WHERE role = 'supervisor'
          AND is_active = TRUE
          AND COALESCE(login_blocked, FALSE) = FALSE  -- V094.6 — patrón estándar "Freeze"
          AND activo_rotacion = TRUE
        ORDER BY created_at, id
        """
    )
    supervisores = [r["id"] for r in cur.fetchall()]
    if not supervisores:
        return None

    # V070.78 — Circuit breaker: filtrar equipos bloqueados.
    # Si el resultado son TODOS los supervisores, no filtra nada (no
    # afecta el comportamiento normal). Solo afecta cuando hay equipos
    # bloqueados — los excluye del candidato pool.
    try:
        from app.services.team_health_service import get_healthy_supervisor_ids
        healthy_ids = set(get_healthy_supervisor_ids(cur))
        if healthy_ids:
            filtered = [sid for sid in supervisores if sid in healthy_ids]
            if filtered:
                if len(filtered) < len(supervisores):
                    excluded = set(supervisores) - set(filtered)
                    try:
                        from app.metrics import crm_lead_rerouted_total
                        for _ in excluded:
                            crm_lead_rerouted_total.labels(reason="team_blocked").inc()
                    except Exception:  # noqa: BLE001
                        pass
                    logger.info(
                        "[circuit-breaker] excluyendo supervisores con equipos bloqueados: %s",
                        sorted(excluded),
                    )
                supervisores = filtered
            else:
                # TODOS bloqueados → mantener lista original (fallback al
                # comportamiento actual). Metrica de alerta P0.
                try:
                    from app.metrics import crm_lead_rerouted_total
                    crm_lead_rerouted_total.labels(
                        reason="no_healthy_team_fallback_admin"
                    ).inc()
                except Exception:  # noqa: BLE001
                    pass
                logger.warning(
                    "[circuit-breaker] TODOS los equipos bloqueados — "
                    "fallback a rotacion normal entre supervisores. "
                    "REQUIRE ACCION URGENTE: %d supervisores, 0 sanos.",
                    len(supervisores),
                )
        # Si healthy_ids esta vacio Y el modulo lanzo excepcion, supervisores
        # queda intacto — fallback seguro al comportamiento pre-V070.78.
    except Exception as exc:  # noqa: BLE001
        # Defensa en profundidad: si el team_health_service tiene un bug,
        # NO afectamos la asignacion (fail-open).
        logger.warning(
            "[circuit-breaker] error evaluando team health — fallback a rotacion normal: %s",
            exc,
        )

    # Contadores del DIA con lock (atomicidad ante requests concurrentes)
    cur.execute(
        f"""
        SELECT supervisor_id::text AS supervisor_id, contador
        FROM crm.rotacion_diaria
        WHERE fecha = {_FECHA_LIMA_EXPR}
          AND supervisor_id = ANY(%s::uuid[])
        ORDER BY supervisor_id
        FOR UPDATE
        """,
        (supervisores,),
    )
    contadores = {r["supervisor_id"]: r["contador"] for r in cur.fetchall()}

    # Tie-breaker historico: ultimo momento que recibio (cualquier dia).
    # Cubre el caso de cambio de dia: contadores arrancan en 0 pero
    # quien recibio hace mas tiempo debe ir primero.
    cur.execute(
        """
        SELECT supervisor_id::text AS supervisor_id,
               MAX(updated_at) AS last_at
        FROM crm.rotacion_diaria
        WHERE supervisor_id = ANY(%s::uuid[])
        GROUP BY supervisor_id
        """,
        (supervisores,),
    )
    last_at_map = {r["supervisor_id"]: r["last_at"] for r in cur.fetchall()}

    # Sentinel: NULL last_at => "nunca recibio" => debe ir PRIMERO.
    # Usamos un datetime muy antiguo y consciente de timezone para que
    # ordene antes que cualquier valor real de la DB.
    sentinel_old = datetime(1970, 1, 1, tzinfo=timezone.utc)

    def sort_key(sid: str):
        cont = contadores.get(sid, 0)
        last_at = last_at_map.get(sid) or sentinel_old
        # supervisores ya viene ordenado estable por created_at,id
        return (cont, last_at, supervisores.index(sid))

    return min(supervisores, key=sort_key)


def _bump_rotacion(cur, supervisor_id: str, lead_id: int) -> None:
    cur.execute(
        f"""
        INSERT INTO crm.rotacion_diaria (fecha, supervisor_id, contador, ultimo_lead_id)
        VALUES ({_FECHA_LIMA_EXPR}, %s::uuid, 1, %s)
        ON CONFLICT (fecha, supervisor_id) DO UPDATE
        SET contador       = crm.rotacion_diaria.contador + 1,
            ultimo_lead_id = EXCLUDED.ultimo_lead_id,
            updated_at     = NOW()
        """,
        (supervisor_id, lead_id),
    )


# ── V053: helpers para integracion con proveedores IA externos ──────────────

def _parse_nombre(payload: IngestPayload) -> tuple[str, str]:
    """Resuelve (nombres, apellidos) con fallbacks tolerantes a multiples
    formas en que un proveedor puede mandar el nombre del cliente.

    Orden de precedencia:
      1. Combinacion: nombres (plural) + apellidos (plural) o apellido (singular).
         Cubre Meta nativo, TikTok, y We Do (que manda nombre + apellido singular).
      2. nombre_completo single field → split por primer espacio.
      3. Fallback: 'Sin nombre'.
    """
    nombres_in   = (payload.nombres or "").strip()
    # apellidos plural tiene precedencia sobre apellido singular cuando ambos vienen
    apellidos_in = (payload.apellidos or "").strip() or (payload.apellido or "").strip()
    if nombres_in or apellidos_in:
        return nombres_in, apellidos_in

    if (payload.nombre_completo or "").strip():
        partes = payload.nombre_completo.strip().split(maxsplit=1)
        if len(partes) == 2:
            return partes[0], partes[1]
        return partes[0], ""

    return "Sin nombre", ""


def _resolve_estado_inicial(cur, nivel_raw: Optional[str]) -> Optional[int]:
    """Mapea un nivel declarado por el proveedor al estado_id correspondiente.

    Allowlist estricta — el proveedor solo puede declarar 'Nuevo' o
    'Contactado'. Cualquier otro valor (incluido vacio) se ignora y se
    cae a 'Nuevo' como antes. Devuelve estado_id (int) o None si la tabla
    catalogo no tiene los estados (caso invariante de bootstrap).
    """
    nivel = (nivel_raw or "").strip()
    if nivel not in PROVIDER_NIVEL_ALLOWLIST:
        nivel = "Nuevo"
    cur.execute(
        "SELECT id FROM crm.estados_lead WHERE nombre = %s LIMIT 1",
        (nivel,),
    )
    row = cur.fetchone()
    if row:
        return row["id"]
    # Fallback ultimo recurso — siempre debe existir 'Nuevo' por seed
    cur.execute("SELECT id FROM crm.estados_lead WHERE nombre = 'Nuevo' LIMIT 1")
    row = cur.fetchone()
    return row["id"] if row else None


def _resolve_vendedor_phone(cur, telefono_raw: Optional[str]) -> Optional[str]:
    """Lookup de un asesor por telefono. Devuelve user_id::text si encuentra
    un asesor o supervisor activo cuyo telefono termine con los mismos 9
    digitos. Si no hay match → None y el caller cae al routing normal.

    Ejemplo: el proveedor manda '51987291111' → el asesor en auth.users
    puede tener guardado '+51987291111' o '987291111' → matcheamos por
    sufijo de 9 digitos para ser tolerantes al formato.
    """
    if not telefono_raw:
        return None
    digits = re.sub(r"\D", "", str(telefono_raw))
    if len(digits) < 9:
        return None
    suffix = digits[-9:]
    try:
        cur.execute(
            """
            SELECT id::text AS id
            FROM auth.users
            WHERE role IN ('asesor', 'supervisor')
              AND is_active = TRUE
              AND telefono IS NOT NULL
              AND regexp_replace(telefono, '\\D', '', 'g') LIKE %s
            LIMIT 1
            """,
            (f"%{suffix}",),
        )
        row = cur.fetchone()
        return row["id"] if row else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("_resolve_vendedor_phone fallo: %s", exc)
        return None


# ── Núcleo ──────────────────────────────────────────────────────────────────

def ingest_lead_core(cur, payload: IngestPayload) -> dict:
    """Procesa un lead sobre un cursor abierto. El caller hace commit.

    Devuelve:
      {duplicated: True, id: N}              — si ya existía el teléfono
      {duplicated: False, id, asesor_id,
       supervisor_id, mode}                  — lead nuevo creado

    Levanta IngestError(status_code, detail) para errores de negocio.
    """
    telefono = clean_phone(payload.telefono)
    if not telefono:
        # V070.58 — Mensaje accionable: el proveedor sabe exactamente qué arreglar.
        raw_digits = re.sub(r"\D", "", str(payload.telefono or ""))
        if not raw_digits:
            detail = "Teléfono inválido: vacío o sin dígitos."
        elif len(raw_digits) < 9:
            detail = (
                f"Teléfono inválido: '{payload.telefono}' tiene {len(raw_digits)} dígitos. "
                "Los celulares peruanos tienen 9 dígitos (ej: 987654321) o 11 con código país "
                "(ej: 51987654321). Para otros países usa formato E.164 con código de país (10-15 dígitos)."
            )
        elif len(raw_digits) == 9 and not raw_digits.startswith("9"):
            detail = (
                f"Teléfono inválido: '{payload.telefono}' tiene 9 dígitos pero no empieza con 9. "
                "Los móviles peruanos siempre empiezan con 9 (ej: 987654321)."
            )
        elif len(raw_digits) > 15:
            detail = (
                f"Teléfono inválido: '{payload.telefono}' tiene {len(raw_digits)} dígitos. "
                "Máximo permitido por estándar E.164: 15 dígitos."
            )
        else:
            detail = f"Teléfono inválido: '{payload.telefono}'."
        raise IngestError(400, detail)

    # V053: parse_nombre tolera multiples shapes — Meta nativo (nombres+
    # apellidos plural), We Do (apellido singular sin nombre), nombre_completo
    # single field, etc. Si nada llega → 'Sin nombre'.
    nombres, apellidos_parsed = _parse_nombre(payload)
    nombres   = nombres or "Sin nombre"
    apellidos = apellidos_parsed or None
    email     = (payload.email or "").strip().lower() or None
    campana   = (payload.campana or "").strip() or None
    fext      = (payload.fuente_externa_id or "").strip() or None
    obs       = (payload.observaciones or "").strip() or None

    # V053: campos opcionales del proveedor
    dni            = (getattr(payload, "dni", None) or "").strip() or None
    anuncio        = (getattr(payload, "anuncio", None) or "").strip() or None
    conjunto       = (getattr(payload, "conjunto", None) or "").strip() or None
    resumen_ia     = (getattr(payload, "resumen_ia", None) or "").strip() or None
    extra_dict     = getattr(payload, "extra", None) or None

    # ── V068.2: PRIMER CHECK por fext (TikTok/Meta lead_id) ─────────────
    # Replica la logica del flujo n8n viejo (UPSERT por lead_id): si el
    # MISMO fext ya fue procesado antes (como lead nuevo o recontacto),
    # es un re-import del polling — NO un cliente real volviendo. Skip
    # silencioso, no infla recontactos.
    #
    # Distincion clave entre "re-import falso" vs "recontacto verdadero":
    #   - Mismo fext  → mismo registro del proveedor → re-import → SKIP
    #   - Fext nuevo + mismo telefono → cliente llenó OTRO form → REAL
    #   - Fext nuevo + telefono nuevo → cliente nuevo → CREAR
    if fext:
        # V070.96 — Fix patrón estándar "no resucitar leads eliminados".
        # Antes: WHERE l.fuente_externa_id = %s AND l.activo = TRUE
        # → leads soft-deleted (activo=FALSE) NO eran encontrados, el
        #   polling externo (TikTok/Meta) los re-creaba al traer el mismo
        #   fext → cliente Palma reporto que leads borrados volvian.
        # Ahora: buscamos SIN filtro de activo. Si el match es soft-deleted,
        # devolvemos skip con reason='deleted' (patrón estándar de la industria:
        # un lead eliminado solo se restaura por accion explicita del user,
        # nunca por polling externo).
        cur.execute(
            """
            SELECT l.id AS lead_id, l.activo, 'lead' AS source
              FROM crm.leads l
              WHERE l.fuente_externa_id = %s
            UNION ALL
            SELECT r.lead_id, TRUE AS activo, 'recontacto' AS source
              FROM crm.lead_recontactos r
              WHERE r.fuente_externa_id = %s
            LIMIT 1
            """,
            (fext, fext),
        )
        fext_seen = cur.fetchone()
        if fext_seen:
            is_deleted = (fext_seen["source"] == "lead" and not fext_seen["activo"])
            if is_deleted:
                logger.warning(
                    "[ingest] fext=%s pertenece a lead eliminado (id=%s) — "
                    "polling externo intento resucitarlo, skip. Patron CRMs profesionales: "
                    "leads eliminados solo se restauran por accion manual.",
                    fext, fext_seen["lead_id"],
                )
                return {
                    "duplicated": True,
                    "id": fext_seen["lead_id"],
                    "reason": "fext_lead_deleted",
                    "skipped": True,
                }
            logger.info(
                "[ingest] fext=%s ya procesado (source=%s lead=%s) — re-import skip",
                fext, fext_seen["source"], fext_seen["lead_id"],
            )
            return {
                "duplicated": True,
                "id": fext_seen["lead_id"],
                "reason": "fext_already_processed",
                "skipped": True,
            }

    # Dedupe por telefono activo. V048: si el lead ya existe, intentamos
    # re-engagement (Lead Recapture pattern) en lugar de descartar.
    # NOTA V068.2: si llegamos aca con fext, es porque el fext es NUEVO
    # (no estaba en lead.fuente_externa_id ni en lead_recontactos.fuente_externa_id).
    # Eso significa que el cliente lleno OTRO formulario → recontacto REAL.
    #
    # V068.3: Reactivation Window (patron estandar de la industria/Marketo).
    # Adicionalmente traemos l.created_at para distinguir entre:
    #   - Lead creado HOY + nuevo touch → es re-submission del mismo dia,
    #     NO es un re-engagement real. Skip silencioso.
    #   - Lead creado en dia anterior + nuevo touch → es un cliente que
    #     realmente volvio, contamos como recontacto.
    cur.execute(
        """
        SELECT
            l.id, l.asesor_id::text AS asesor_id, l.supervisor_id::text AS supervisor_id,
            l.fuente_id, l.email, l.nombres, l.apellidos,
            -- V086.1 — campos extra para enriquecimiento conservador.
            -- lead_recapture._fill_empty_fields los lee para decidir si
            -- rellenar con los datos que mandó el proveedor en el touch.
            l.dni, l.ciudad, l.trabajo, l.resumen_ia,
            l.created_at,
            (DATE(l.created_at AT TIME ZONE 'America/Lima')
             = DATE(NOW() AT TIME ZONE 'America/Lima')) AS created_today,
            e.nombre AS estado_nombre
        FROM crm.leads l
        LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
        WHERE l.telefono = %s AND l.activo = TRUE
        LIMIT 1
        """,
        (telefono,),
    )
    existing = cur.fetchone()
    if existing:
        # V068.3: Reactivation Window — eventos del mismo dia que la
        # creacion del lead son re-submissions o noise del polling, NO
        # son reactivaciones reales del cliente. CRMs profesionales/Marketo
        # todos requieren un gap minimo (patrón estándar default: 30 dias;
        # nosotros usamos 1 dia por agresividad del poll-cada-minuto).
        if existing.get("created_today"):
            logger.info(
                "[ingest] telefono=%s ya creado hoy (lead=%s) — re-submission "
                "del mismo dia, NO se registra como recontacto.",
                telefono, existing["id"],
            )
            return {
                "duplicated": True,
                "id": existing["id"],
                "reason": "same_day_resubmission",
                "skipped": True,
            }
        # Hand off al handler de re-engagement. Best-effort: si V048 no esta
        # aplicada o algo falla, devolvemos el comportamiento legacy.
        try:
            from app.services import lead_recapture
            recap = lead_recapture.handle_recontacto(
                cur,
                existing=dict(existing),
                payload=payload,
                telefono=telefono,
                email=email,
                nombres=nombres,
                apellidos=apellidos,
                campana=campana,
                fext=fext,
            )
            # V070.59 — Response honesto: el cliente debe saber si el recontacto
            # se persistio realmente (`recontacto_id` != null) o si fue
            # silenciado (`duplicate_event` o `insert_error`). Antes siempre
            # decia `recontacto: true` aunque la fila nunca se insertara.
            return {
                "duplicated": True,
                "id": existing["id"],
                "recontacto": True,
                "estrategia": recap.get("estrategia"),
                "asesor_id": recap.get("asesor_id"),
                "supervisor_id": existing["supervisor_id"],
                "recontacto_id": recap.get("recontacto_id"),
                "duplicate_event": recap.get("duplicate_event", False),
                "backfill_skip": recap.get("backfill_skip", False),
                "insert_error": recap.get("insert_error"),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("[recapture] fallo silencioso lead=%s: %s", existing["id"], exc)
            return {"duplicated": True, "id": existing["id"]}

    # Fuente
    fuente_id = _resolve_fuente_id(cur, payload.fuente, payload)
    if not fuente_id:
        raise IngestError(400, f"Fuente '{payload.fuente}' no encontrada en crm.fuentes.")

    # V053: estado inicial — el proveedor puede declarar 'Nuevo' o
    # 'Contactado' (si su IA ya hablo con el cliente). Allowlist estricta
    # en _resolve_estado_inicial — si llega cualquier otra cosa cae a 'Nuevo'.
    estado_id = _resolve_estado_inicial(cur, getattr(payload, "nivel", None))
    if not estado_id:
        raise IngestError(500, "Estado 'Nuevo' no existe en crm.estados_lead.")

    # V110 + V113 — Asignación exclusiva por campaña publicitaria (Meta / TikTok / General)
    designated_sup_id = None
    camp_dist_mode = "supervisor"
    camp_assigned_asesor = None
    try:
        from app.services.campaign_assignment_service import (
            resolve_campaign_supervisor_assignment,
            assign_to_supervisor_team_round_robin,
        )
        camp_rule = resolve_campaign_supervisor_assignment(
            cur,
            campana=campana,
            campaign_name=getattr(payload, "campaign_name", None),
            provider=payload.fuente,
        )
        if camp_rule:
            designated_sup_id = camp_rule["supervisor_id"]
            camp_dist_mode = camp_rule.get("distribution_mode") or "supervisor"
    except Exception as exc:  # noqa: BLE001
        logger.warning("[campaign-assignment] error resolviendo supervisor para campana=%s: %s", campana, exc)

    if designated_sup_id:
        supervisor_id = designated_sup_id
        mode = "campana_designada"
        if camp_dist_mode in ("equipo", "todos"):
            try:
                camp_assigned_asesor = assign_to_supervisor_team_round_robin(
                    cur,
                    designated_sup_id,
                    distribution_mode=camp_dist_mode,
                    cas_id=camp_rule.get("cas_id"),
                    member_percentages=camp_rule.get("member_percentages"),
                    member_counts=camp_rule.get("member_counts"),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[campaign-assignment] error en reparto de equipo: %s", exc)
                camp_assigned_asesor = None
    else:
        # Modo de asignación (fijo vs rotación)
        from app.routers.settings import load_ingest_mode
        ingest_cfg = load_ingest_mode()
        mode = ingest_cfg.get("mode") or "rotacion"

        if mode == "fijo":
            supervisor_id = ingest_cfg.get("fijo_user_id")
            if not supervisor_id:
                raise IngestError(500, "Modo 'fijo' sin fijo_user_id configurado.")
            cur.execute(
                "SELECT 1 FROM auth.users WHERE id = %s::uuid AND role = 'supervisor' AND is_active = TRUE",
                (supervisor_id,),
            )
            if not cur.fetchone():
                raise IngestError(503, "Supervisor fijo no está activo.")
        else:
            supervisor_id = _next_supervisor(cur)
            if not supervisor_id:
                raise IngestError(503, "No hay supervisores activos para rotación.")

    # Recontacto: histórico legacy + leads inactivos
    tel_digits = re.sub(r"\D", "", telefono)
    tel_norm = tel_digits[-9:] if len(tel_digits) >= 9 else tel_digits
    cur.execute(
        "SELECT 1 FROM crm_legacy.leads_historico WHERE telefono_norm = %s LIMIT 1",
        (tel_norm,),
    )
    es_recontacto = cur.fetchone() is not None
    if not es_recontacto:
        cur.execute(
            "SELECT 1 FROM crm.leads WHERE telefono = %s AND activo = FALSE LIMIT 1",
            (telefono,),
        )
        es_recontacto = cur.fetchone() is not None

    # V035: el lead entrante queda en la cola del supervisor (asesor_id=NULL)
    # para que el panel de Asignación pueda repartirlo al asesor correcto.
    # V053: nuevos campos opcionales (dni, anuncio, conjunto, resumen_ia,
    # datos_extra) — todos NULL si el driver no los entrega.
    fuente_form_id = (payload.fuente_form_id or "").strip() or None
    extra_json = json.dumps(extra_dict) if extra_dict else None

    # V103 — Leads nocturnos (ingresados post 9:00 p.m. / 21:00) pasan con atencion_prioritaria = True
    try:
        from app.services.sla_service import es_hora_nocturna
        es_nocturno = es_hora_nocturna()
    except Exception:
        es_nocturno = False

    cur.execute(
        """
        INSERT INTO crm.leads
            (nombres, apellidos, telefono, email, dni, campana,
             anuncio, conjunto, resumen_ia, datos_extra,
             fuente_id, estado_id, supervisor_id, asesor_id, fuente_externa_id,
             observaciones, es_recontacto, activo, fecha_entrada_cola,
             fuente_form_id, atencion_prioritaria)
        VALUES (%s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s::jsonb,
                %s, %s,
                CASE WHEN %s IS NULL THEN NULL ELSE %s::uuid END,
                NULL,
                %s, %s, %s, TRUE, NOW(),
                %s, %s)
        RETURNING id
        """,
        (
            nombres, apellidos, telefono, email, dni, campana,
            anuncio, conjunto, resumen_ia, extra_json,
            fuente_id, estado_id,
            supervisor_id, supervisor_id,
            fext, obs, es_recontacto,
            fuente_form_id, es_nocturno,
        ),
    )
    new_id = cur.fetchone()["id"]

    # V096.5 — write-through cache via helper centralizado. La leads list y
    # el webhook hacen LEFT JOIN contra meta_catalog_cache para resolver
    # campana_nombre y form_nombre. Sin la hidratacion el usuario ve solo IDs.
    # El helper es best-effort: no rompe el ingest si falla.
    from app.services.integrations.meta_catalog import hydrate_from_provider
    hydrate_from_provider(
        cur, entity_type="campaign",
        entity_id=str(campana).strip() if campana else None,
        name=payload.campaign_name,
    )
    hydrate_from_provider(
        cur, entity_type="form",
        entity_id=fuente_form_id,
        name=payload.form_name,
    )

    asesor_final: Optional[str] = None

    if mode == "campana_designada":
        try:
            c_name = payload.campaign_name or campana or "Campaña"
            if camp_assigned_asesor:
                asesor_final = camp_assigned_asesor["user_id"]
                is_sup = camp_assigned_asesor.get("is_supervisor", False)
                if is_sup:
                    cur.execute(
                        """
                        INSERT INTO crm.asignaciones_log
                            (lead_id, asesor_anterior, asesor_nuevo, asignado_por, motivo)
                        VALUES (%s, NULL, %s::uuid, NULL, 'campana_reparto_todos_supervisor')
                        """,
                        (new_id, designated_sup_id),
                    )
                    cur.execute(
                        """
                        INSERT INTO crm.contactos
                            (lead_id, asesor_id, tipo_contacto, notas, created_at)
                        VALUES (%s, %s::uuid, 'sistema', %s, NOW())
                        """,
                        (
                            new_id,
                            designated_sup_id,
                            f"🌟 Repartido al supervisor {camp_assigned_asesor['nombre']} por campaña ({c_name}) [Modo A Todos]",
                        ),
                    )
                else:
                    cur.execute(
                        "UPDATE crm.leads SET asesor_id = %s::uuid WHERE id = %s",
                        (asesor_final, new_id),
                    )
                    cur.execute(
                        """
                        INSERT INTO crm.asignaciones_log
                            (lead_id, asesor_anterior, asesor_nuevo, asignado_por, motivo)
                        VALUES (%s, NULL, %s::uuid, NULL, 'campana_reparto_equipo')
                        """,
                        (new_id, asesor_final),
                    )
                    nota_asesor = (
                        f"🌟 Repartido al asesor {camp_assigned_asesor['nombre']} por campaña ({c_name}) [Modo A Todos]"
                        if camp_dist_mode == "todos"
                        else f"👥 Repartido al asesor {camp_assigned_asesor['nombre']} por campaña ({c_name})"
                    )
                    cur.execute(
                        """
                        INSERT INTO crm.contactos
                            (lead_id, asesor_id, tipo_contacto, notas, created_at)
                        VALUES (%s, %s::uuid, 'sistema', %s, NOW())
                        """,
                        (
                            new_id,
                            asesor_final,
                            nota_asesor,
                        ),
                    )
            else:
                cur.execute(
                    """
                    INSERT INTO crm.asignaciones_log
                        (lead_id, asesor_anterior, asesor_nuevo, asignado_por, motivo)
                    VALUES (%s, NULL, %s::uuid, NULL, 'campana_supervisor_directo')
                    """,
                    (new_id, designated_sup_id),
                )
                nota_sup = (
                    f"👤 Asignado directo a bandeja de supervisor por regla de Leads Campañas ({c_name})"
                    if camp_dist_mode == "supervisor"
                    else f"🎯 Asignado a supervisor por regla de Leads Campañas ({c_name}) [Equipo sin asesores disponibles]"
                )
                cur.execute(
                    """
                    INSERT INTO crm.contactos
                        (lead_id, asesor_id, tipo_contacto, notas, created_at)
                    VALUES (%s, %s::uuid, 'sistema', %s, NOW())
                    """,
                    (
                        new_id,
                        designated_sup_id,
                        nota_sup,
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[campaign-assignment] log asignacion fallo lead=%s: %s", new_id, exc)
    elif mode == "rotacion":
        _bump_rotacion(cur, supervisor_id, new_id)

    # ── V056: Si el proveedor IA declaro nivel='Contactado', registramos un
    # contacto de tipo 'ia_externa' para trazabilidad y para que la
    # definicion de capacity 'sin_contacto_48h' identifique al lead como
    # ya contactado (no consume slot del cap del asesor por 48h). ──
    nivel_raw = (getattr(payload, "nivel", None) or "").strip()
    if nivel_raw == "Contactado":
        notas_ia = resumen_ia or "Contactado por IA externa del proveedor."
        try:
            cur.execute(
                """
                INSERT INTO crm.contactos
                    (lead_id, asesor_id, tipo_contacto, resultado, notas, created_at)
                VALUES (%s, NULL, 'ia_externa', 'contesto', %s, NOW())
                """,
                (new_id, notas_ia),
            )
        except Exception:  # noqa: BLE001 — best effort, no rompe el ingest
            logger.exception("[ingest] registro ia_externa fallido lead=%s", new_id)

    # ── V053: Pre-asignacion via vendedor del proveedor ──
    # Si el proveedor manda 'asesor_telefono' y matchea un asesor activo,
    # asignamos directo a ese asesor (saltea el round-robin). Si no matchea,
    # cae al flujo normal de auto-asignacion V046 abajo.
    if not asesor_final:
        asesor_pre = _resolve_vendedor_phone(cur, getattr(payload, "asesor_telefono", None))
        if asesor_pre:
            try:
                cur.execute(
                    "UPDATE crm.leads SET asesor_id = %s::uuid WHERE id = %s",
                    (asesor_pre, new_id),
                )
                cur.execute(
                    """
                    INSERT INTO crm.asignaciones_log
                        (lead_id, asesor_anterior, asesor_nuevo, asignado_por, motivo)
                    VALUES (%s, NULL, %s::uuid, NULL, 'inicial')
                    """,
                    (new_id, asesor_pre),
                )
                asesor_final = asesor_pre
                logger.info(
                    "[pre-assign] lead=%s -> asesor=%s via vendedor_telefono=%s",
                    new_id, asesor_pre, getattr(payload, "asesor_telefono", None),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[pre-assign] fallo silencioso lead=%s: %s", new_id, exc)
                asesor_final = None  # cae al flujo normal

    # ── V046: Auto-asignacion al asesor (opt-in via assignment_config) ──
    # Si el motor decide un asesor, actualizamos el lead para que aterrice
    # directamente en su bandeja en vez de la del supervisor. Si el motor
    # devuelve None (config OFF, sin candidatos, fallo interno), el lead
    # queda en el supervisor — comportamiento actual.
    # V053: skip si ya hubo pre-asignacion via vendedor.
    # V113: skip si ya fue atendido por campana_designada (directo o reparto en equipo).
    if asesor_final or mode == "campana_designada":
        return {
            "duplicated":    False,
            "id":            new_id,
            "mode":          mode,
            "asesor_id":     asesor_final,
            "supervisor_id": supervisor_id,
            "nombres":       nombres,
            "apellidos":     apellidos,
            "pre_assigned":  bool(asesor_final),
        }

    try:
        from app.services import lead_routing
        lead_dict = {
            "fuente_id":     fuente_id,
            "campana":       campana,
            "observaciones": obs,
            "fuente_externa_id": fext,
        }
        decision = lead_routing.try_auto_assign(
            cur, lead_id=new_id, lead=lead_dict, supervisor_id=supervisor_id,
        )
        if decision and decision.asignado_a_id and decision.asignado_a_id != supervisor_id:
            cur.execute(
                "UPDATE crm.leads SET asesor_id = %s::uuid WHERE id = %s",
                (decision.asignado_a_id, new_id),
            )
            cur.execute(
                """
                INSERT INTO crm.asignaciones_log
                    (lead_id, asesor_anterior, asesor_nuevo, asignado_por, motivo)
                VALUES (%s, %s::uuid, %s::uuid, NULL, 'auto_asignacion')
                """,
                (new_id, supervisor_id, decision.asignado_a_id),
            )
            cur.execute(
                """
                INSERT INTO crm.contactos
                    (lead_id, asesor_id, tipo_contacto, notas, created_at)
                VALUES (%s, %s::uuid, 'sistema', %s, NOW())
                """,
                (
                    new_id,
                    decision.asignado_a_id,
                    f"⚡ Repartido automáticamente al asesor ({decision.razon or decision.estrategia})",
                ),
            )
            lead_routing.log_decision(
                cur,
                lead_id=new_id,
                supervisor_id=supervisor_id,
                decision=decision,
            )
            asesor_final = decision.asignado_a_id
            logger.info(
                "[auto-assign] lead=%s -> asesor=%s via %s (%dms)",
                new_id, decision.asignado_a_id, decision.estrategia, decision.duracion_ms,
            )
    except Exception as exc:  # noqa: BLE001
        # Fail-safe: nunca bloquear la ingesta por un fallo del motor.
        logger.warning("[auto-assign] fallo silencioso lead=%s: %s", new_id, exc)

    # V070.86 — Push notification: NO se dispara aqui. Es responsabilidad
    # del caller (routers/ingest.py, meta_service.py, tiktok_service.py,
    # whatsapp.py). En V070.85 se habia agregado aqui, pero causaba doble
    # push porque 3 de los 4 callers ya disparaban su propio notify_new_lead
    # despues del ingest_lead_core (router/ingest line 407, tiktok line 1044,
    # whatsapp via _ctwa_lead_push_task). Solo meta_service.py necesita
    # disparar el push porque era el unico que no lo hacia — ese arreglo
    # ahora vive en meta_service.py para no introducir duplicacion.

    return {
        "duplicated":    False,
        "id":            new_id,
        "mode":          mode,
        "asesor_id":     asesor_final,
        "supervisor_id": supervisor_id,
        "nombres":       nombres,
        "apellidos":     apellidos,
    }
