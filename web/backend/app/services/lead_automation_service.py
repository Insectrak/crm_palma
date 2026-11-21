"""
lead_automation_service.py — Automatizaciones periódicas y por eventos de estados y flujo de leads.

Configurable dinámicamente desde el Panel de Administración (Configuración -> Automatización de estados).
Soporta:
1. Interruptor global (enabled: True/False) — Deshabilitado por defecto a solicitud del administrador.
2. Reglas por intentos de contacto (llamadas y WhatsApp):
   - Mínimo de intentos telefónicos / marcaciones.
   - Mínimo de mensajes salientes de WhatsApp.
   - Estado de destino seleccionado libremente del catálogo crm.estados_lead.
   - Orden y jerarquía para evitar retrocesos de estado.
3. Reglas de transición por tiempo en estado (ej. pase a bolsa o reciclaje tras X horas):
   - Estado de origen.
   - Horas transcurridas en dicho estado.
   - Estado de destino.
   - Opción para desasignar asesor (asesor_id = NULL) y registrar motivo en crm.asignaciones_log.
4. Exclusiones y protecciones:
   - Excluir leads con contacto efectivo registrado (llamadas contestadas, citas agendadas, etc.).
   - Respetar gestión especial por administración (gestion_especial_admin = TRUE).
   - Proteger estados finales o cerrados.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Optional
from psycopg2.extras import RealDictCursor
from app.database import get_db

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "enabled": False,  # Deshabilitado por defecto a petición de administración
    "reglas_intentos": [],
    "reglas_tiempo": [],
    "excluir_contacto_efectivo": True,
    "respetar_gestion_admin": True,
}


@lru_cache(maxsize=1)
def _has_gestion_especial_admin_column() -> bool:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'crm'
                      AND table_name   = 'leads'
                      AND column_name  = 'gestion_especial_admin'
                    LIMIT 1
                    """
                )
                return cur.fetchone() is not None
    except Exception:
        return False


def _ensure_settings_table(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS public.app_settings (
            key         TEXT PRIMARY KEY,
            value       JSONB NOT NULL,
            updated_at  TIMESTAMPTZ DEFAULT NOW()
        );
        """
    )


def _generar_config_inicial_desde_db(cur) -> dict:
    """
    Construye una plantilla inicial de configuración inspeccionando los estados
    actualmente existentes en crm.estados_lead.
    Mantiene 'enabled': False por defecto para que no actúe hasta que el admin la active.
    """
    cur.execute("SELECT id, nombre, color_hex, orden FROM crm.estados_lead ORDER BY orden ASC, id ASC")
    estados = cur.fetchall() or []

    d1_id = None
    d2_id = None
    d3_id = None
    bolsa_id = None

    for r in estados:
        nom = (r.get("nombre") or "").lower().strip()
        if ("no contesta" in nom and ("1" in nom or "día 1" in nom or "dia 1" in nom)) and "bolsa" not in nom:
            d1_id = r["id"]
        elif ("no contesta" in nom and ("2" in nom or "día 2" in nom or "dia 2" in nom)) and "bolsa" not in nom:
            d2_id = r["id"]
        elif ("no contesta" in nom and ("3" in nom or "día 3" in nom or "dia 3" in nom)) and "bolsa" not in nom:
            d3_id = r["id"]
        elif "bolsa" in nom and ("reciclaje" in nom or "tmk" in nom or "no contesta" in nom):
            bolsa_id = r["id"]

    reglas_intentos = []
    if d1_id:
        reglas_intentos.append({
            "id": "regla_intento_1",
            "nombre": "Primer escalamiento (Día 1)",
            "estado_destino_id": d1_id,
            "min_llamadas": 3,
            "min_whatsapp": 1,
            "orden": 1,
            "activo": True,
        })
    if d2_id:
        reglas_intentos.append({
            "id": "regla_intento_2",
            "nombre": "Segundo escalamiento (Día 2)",
            "estado_destino_id": d2_id,
            "min_llamadas": 5,
            "min_whatsapp": 2,
            "orden": 2,
            "activo": True,
        })
    if d3_id:
        reglas_intentos.append({
            "id": "regla_intento_3",
            "nombre": "Tercer escalamiento (Día 3)",
            "estado_destino_id": d3_id,
            "min_llamadas": 6,
            "min_whatsapp": 3,
            "orden": 3,
            "activo": True,
        })

    reglas_tiempo = []
    if d3_id and bolsa_id:
        reglas_tiempo.append({
            "id": "regla_tiempo_1",
            "nombre": "Pase a Bolsa de reciclaje tras 12h",
            "estado_origen_id": d3_id,
            "horas_espera": 12,
            "estado_destino_id": bolsa_id,
            "desasignar_asesor": True,
            "activo": True,
        })

    return {
        "enabled": False,  # Inicialmente apagado
        "reglas_intentos": reglas_intentos,
        "reglas_tiempo": reglas_tiempo,
        "excluir_contacto_efectivo": True,
        "respetar_gestion_admin": True,
    }


def get_lead_automation_config(cur=None) -> dict:
    """
    Obtiene la configuración actual de automatizaciones desde public.app_settings.
    Si no existe, retorna una plantilla con 'enabled': False.
    """
    def _fetch(c) -> dict:
        _ensure_settings_table(c)
        c.execute("SELECT value FROM public.app_settings WHERE key = 'lead_automation_config'")
        row = c.fetchone()
        if row and row.get("value"):
            cfg = dict(row["value"])
            # Asegurar claves mínimas
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
        return _generar_config_inicial_desde_db(c)

    if cur is not None:
        return _fetch(cur)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as c:
            return _fetch(c)


def save_lead_automation_config(config_dict: dict, cur=None) -> dict:
    """Guarda (upsert) la configuración en public.app_settings."""
    payload = {
        "enabled": bool(config_dict.get("enabled", False)),
        "reglas_intentos": list(config_dict.get("reglas_intentos", [])),
        "reglas_tiempo": list(config_dict.get("reglas_tiempo", [])),
        "excluir_contacto_efectivo": bool(config_dict.get("excluir_contacto_efectivo", True)),
        "respetar_gestion_admin": bool(config_dict.get("respetar_gestion_admin", True)),
    }

    def _save(c):
        _ensure_settings_table(c)
        c.execute(
            """
            INSERT INTO public.app_settings (key, value, updated_at)
            VALUES ('lead_automation_config', %s::jsonb, NOW())
            ON CONFLICT (key) DO UPDATE
                SET value = EXCLUDED.value,
                    updated_at = NOW()
            """,
            (json.dumps(payload),),
        )

    if cur is not None:
        _save(cur)
    else:
        with get_db() as conn:
            with conn.cursor() as c:
                _save(c)
            conn.commit()

    logger.info("[Auto-Estado Config] Configuración guardada. Enabled=%s", payload["enabled"])
    return payload


# ─── MÉTODOS DE RETROCOMPATIBILIDAD ──────────────────────────────────────────

def _calcular_meta_estado(llamadas: int, whatsapp: int, estados_map: dict) -> Optional[dict]:
    """Retrocompatibilidad para tests existentes."""
    if llamadas >= 6 and whatsapp >= 3:
        return estados_map.get("dia_3")
    elif llamadas >= 5 and whatsapp >= 2:
        return estados_map.get("dia_2")
    elif llamadas >= 3 and whatsapp >= 1:
        return estados_map.get("dia_1")
    return None


def _nivel_jerarquia_no_contesta(estado_id: int, estados_map: dict) -> int:
    """Retrocompatibilidad para tests existentes."""
    if estado_id == estados_map.get("dia_1", {}).get("id"):
        return 1
    if estado_id == estados_map.get("dia_2", {}).get("id"):
        return 2
    if estado_id == estados_map.get("dia_3", {}).get("id"):
        return 3
    if estado_id == estados_map.get("bolsa", {}).get("id"):
        return 4
    return 0


def _asegurar_estados_no_contesta(cur) -> dict[str, dict]:
    """Retrocompatibilidad: inspecciona o resuelve estados canónicos."""
    cur.execute("SELECT id, nombre, orden FROM crm.estados_lead ORDER BY orden ASC, id ASC")
    rows = cur.fetchall() or []
    estados_map = {}
    for r in rows:
        nom = (r.get("nombre") or "").lower()
        if ("no contesta" in nom and ("1" in nom or "día 1" in nom or "dia 1" in nom)) and "bolsa" not in nom:
            if "dia_1" not in estados_map:
                estados_map["dia_1"] = {"id": r["id"], "nombre": r["nombre"]}
        elif ("no contesta" in nom and ("2" in nom or "día 2" in nom or "dia 2" in nom)) and "bolsa" not in nom:
            if "dia_2" not in estados_map:
                estados_map["dia_2"] = {"id": r["id"], "nombre": r["nombre"]}
        elif ("no contesta" in nom and ("3" in nom or "día 3" in nom or "dia 3" in nom)) and "bolsa" not in nom:
            if "dia_3" not in estados_map:
                estados_map["dia_3"] = {"id": r["id"], "nombre": r["nombre"]}
        elif "bolsa" in nom and ("reciclaje" in nom or "tmk" in nom or "no contesta" in nom):
            if "bolsa" not in estados_map:
                estados_map["bolsa"] = {"id": r["id"], "nombre": r["nombre"]}
    return estados_map


def lead_cumple_reglas_no_contesta(cur, lead_id: int, estado_nombre: Optional[str] = None) -> bool:
    """
    Verifica si un lead cumple con las condiciones de las reglas de automatización.
    Si la automatización global está deshabilitada (enabled: False), retorna False
    (a menos que ya tenga la bandera gestion_especial_admin = True).
    """
    try:
        config = get_lead_automation_config(cur)
    except Exception:
        config = DEFAULT_CONFIG

    # Si está deshabilitado globalmente, no forzar cumplimiento de reglas
    if not config.get("enabled", False):
        if _has_gestion_especial_admin_column():
            cur.execute("SELECT gestion_especial_admin FROM crm.leads WHERE id = %s", (lead_id,))
            row = cur.fetchone()
            if row and row.get("gestion_especial_admin"):
                return True
        return False

    nom = (estado_nombre or "").lower()
    reglas_intentos = [r for r in config.get("reglas_intentos", []) if r.get("activo", True)]
    reglas_tiempo = [r for r in config.get("reglas_tiempo", []) if r.get("activo", True)]

    # Chequear si su estado actual coincide con algún destino de las reglas activas
    cur.execute("SELECT id, nombre FROM crm.estados_lead")
    all_estados = {r["id"]: r["nombre"].lower() for r in (cur.fetchall() or [])}

    target_ids = {r.get("estado_destino_id") for r in reglas_intentos if r.get("estado_destino_id")}
    target_ids.update({r.get("estado_destino_id") for r in reglas_tiempo if r.get("estado_destino_id")})

    for tid in target_ids:
        if tid in all_estados and all_estados[tid] in nom:
            return True

    # Chequear umbrales mínimos de llamadas / WA de la regla con menor exigencia
    min_llamadas = min((r.get("min_llamadas", 3) for r in reglas_intentos), default=3)
    min_wa = min((r.get("min_whatsapp", 1) for r in reglas_intentos), default=1)

    cur.execute(
        """
        SELECT
            (
                COALESCE((
                    SELECT COUNT(*) FROM crm.contactos c
                    WHERE c.lead_id = %s
                      AND LOWER(c.tipo_contacto) IN ('llamada', 'llamada_saliente', 'llamada_entrante', 'telefonica')
                      AND c.tipo_contacto != 'cambio_estado'
                ), 0)
                +
                COALESCE((
                    SELECT COUNT(*) FROM crm.llamadas ll
                    WHERE ll.lead_id = %s
                ), 0)
            ) AS total_llamadas,
            (
                COALESCE((
                    SELECT COUNT(*) FROM crm.contactos c
                    WHERE c.lead_id = %s
                      AND c.tipo_contacto ILIKE '%%whatsapp%%'
                ), 0)
                +
                COALESCE((
                    SELECT COUNT(*) FROM crm.wa_messages wm
                    JOIN crm.wa_conversations wc ON wc.id = wm.conversation_id
                    WHERE wc.lead_id = %s AND wm.direction = 'outbound'
                ), 0)
            ) AS total_wa
        """,
        (lead_id, lead_id, lead_id, lead_id),
    )
    row = cur.fetchone()
    if not row:
        return False

    llamadas = row.get("total_llamadas") or 0
    wa = row.get("total_wa") or 0
    return llamadas >= min_llamadas and wa >= min_wa


# ─── MOTOR DINÁMICO DE EVALUACIÓN ───────────────────────────────────────────

def evaluar_lead_individual_no_contesta(lead_id: int) -> dict:
    """
    Evalúa inmediatamente un lead específico tras una gestión (contacto o llamada).
    Lee la configuración dinámica de public.app_settings. Si la automatización
    está desactivada (enabled: False), se omite de inmediato.
    """
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                config = get_lead_automation_config(cur)

                # Si está desactivada globalmente, no realizar ninguna acción
                if not config.get("enabled", False):
                    return {
                        "ok": True,
                        "actualizado": False,
                        "motivo": "Automatización de estados deshabilitada en la configuración",
                    }

                reglas_intentos = [
                    r for r in config.get("reglas_intentos", [])
                    if r.get("activo", True) and r.get("estado_destino_id")
                ]
                if not reglas_intentos:
                    return {
                        "ok": True,
                        "actualizado": False,
                        "motivo": "No hay reglas de intentos configuradas o activas",
                    }

                # Ordenar reglas por orden de menor a mayor exigencia
                reglas_intentos.sort(key=lambda r: (r.get("orden", 1), r.get("min_llamadas", 0)))

                has_ga = _has_gestion_especial_admin_column()
                ga_select = "COALESCE(l.gestion_especial_admin, FALSE) AS gestion_especial_admin," if has_ga else "FALSE AS gestion_especial_admin,"

                cur.execute(
                    f"""
                    SELECT
                        l.id,
                        l.asesor_id,
                        l.estado_id,
                        {ga_select}
                        e.nombre AS estado_nombre,
                        e.es_final,
                        (
                            COALESCE((
                                SELECT COUNT(*) FROM crm.contactos c
                                WHERE c.lead_id = l.id
                                  AND LOWER(c.tipo_contacto) IN ('llamada', 'llamada_saliente', 'llamada_entrante', 'telefonica')
                                  AND c.tipo_contacto != 'cambio_estado'
                            ), 0)
                            +
                            COALESCE((
                                SELECT COUNT(*) FROM crm.llamadas ll
                                WHERE ll.lead_id = l.id
                            ), 0)
                        ) AS total_llamadas,
                        (
                            COALESCE((
                                SELECT COUNT(*) FROM crm.contactos c
                                WHERE c.lead_id = l.id
                                  AND c.tipo_contacto ILIKE '%%whatsapp%%'
                            ), 0)
                            +
                            COALESCE((
                                SELECT COUNT(*) FROM crm.wa_messages wm
                                JOIN crm.wa_conversations wc ON wc.id = wm.conversation_id
                                WHERE wc.lead_id = l.id AND wm.direction = 'outbound'
                            ), 0)
                        ) AS total_wa,
                        (
                            EXISTS (
                                SELECT 1 FROM crm.contactos c
                                WHERE c.lead_id = l.id
                                  AND (
                                      c.resultado IN ('contesto', 'cita_agendada', 'interesado', 'calificado', 'matricula')
                                      OR c.fecha_cita IS NOT NULL
                                      OR COALESCE(c.duracion_minutos, 0) > 0
                                  )
                            ) OR EXISTS (
                                SELECT 1 FROM crm.llamadas ll
                                WHERE ll.lead_id = l.id AND ll.duracion_segundos > 0
                            )
                        ) AS tiene_contacto_efectivo
                    FROM crm.leads l
                    JOIN crm.estados_lead e ON e.id = l.estado_id
                    WHERE l.id = %s AND l.activo = TRUE
                    """,
                    (lead_id,),
                )
                lead = cur.fetchone()
                if not lead:
                    return {"ok": True, "actualizado": False, "motivo": "Lead no encontrado o inactivo"}

                if config.get("respetar_gestion_admin", True) and lead.get("gestion_especial_admin"):
                    logger.info("[Auto-Estado Lead %s] Omitido: lead bajo gestión especial de administración.", lead_id)
                    return {"ok": True, "actualizado": False, "motivo": "Lead en gestión especial por Administración"}

                if config.get("excluir_contacto_efectivo", True) and lead["tiene_contacto_efectivo"]:
                    return {"ok": True, "actualizado": False, "motivo": "Lead tiene contacto efectivo registrado"}

                # Verificar si está en un estado protegido/final
                e_nom = lead["estado_nombre"] or ""
                if lead["es_final"] or any(term in e_nom.lower() for term in ["matr", "ganad", "perdid", "no inter", "calific", "negociac"]):
                    return {"ok": True, "actualizado": False, "motivo": f"Estado '{e_nom}' está protegido de automatización"}

                llamadas = lead["total_llamadas"] or 0
                wa = lead["total_wa"] or 0

                # Determinar la regla más alta que cumple el lead
                qualifying_rule = None
                for r in reversed(reglas_intentos):
                    if llamadas >= r.get("min_llamadas", 0) and wa >= r.get("min_whatsapp", 0):
                        qualifying_rule = r
                        break

                if not qualifying_rule:
                    return {"ok": True, "actualizado": False, "motivo": "No alcanza umbral de llamadas/whatsapp"}

                target_id = qualifying_rule["estado_destino_id"]
                curr_id = lead["estado_id"]

                if curr_id == target_id:
                    return {"ok": True, "actualizado": False, "motivo": "Lead ya se encuentra en este estado"}

                # Determinar jerarquía actual vs jerarquía meta
                curr_orden = 0
                for r in reglas_intentos:
                    if r.get("estado_destino_id") == curr_id:
                        curr_orden = r.get("orden", 0)
                        break

                target_orden = qualifying_rule.get("orden", 0)
                if target_orden <= curr_orden:
                    return {"ok": True, "actualizado": False, "motivo": "Lead ya se encuentra en nivel igual o superior"}

                # Obtener nombre del estado destino
                cur.execute("SELECT nombre FROM crm.estados_lead WHERE id = %s", (target_id,))
                target_row = cur.fetchone()
                target_nombre = target_row["nombre"] if target_row else f"Estado {target_id}"

                # Actualizar estado del lead
                cur.execute(
                    """
                    UPDATE crm.leads
                    SET estado_id = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (target_id, lead_id),
                )

                rule_title = qualifying_rule.get("nombre") or "Regla automática"
                nota_sistema = (
                    f"Estado → {target_nombre} "
                    f"(Cambio automático: {llamadas} intentos telefónicos y {wa} WhatsApp · {rule_title})"
                )
                cur.execute(
                    """
                    INSERT INTO crm.contactos (
                        lead_id,
                        asesor_id,
                        tipo_contacto,
                        notas
                    ) VALUES (%s, %s, 'cambio_estado', %s)
                    """,
                    (lead_id, lead["asesor_id"], nota_sistema),
                )

                conn.commit()
                logger.info(
                    "[Auto-Estado Lead %s] Movido a '%s' por regla '%s' (%d llamadas, %d WA).",
                    lead_id,
                    target_nombre,
                    rule_title,
                    llamadas,
                    wa,
                )
                return {
                    "ok": True,
                    "actualizado": True,
                    "lead_id": lead_id,
                    "nuevo_estado": target_nombre,
                    "llamadas": llamadas,
                    "whatsapp": wa,
                    "regla": rule_title,
                }
    except Exception as exc:
        logger.exception("[Auto-Estado Lead %s] Error evaluando lead individual: %s", lead_id, exc)
        return {"ok": False, "error": str(exc), "actualizado": False}


def procesar_automatizaciones_estados_no_contesta() -> dict:
    """
    Motor global de automatización de estados.
    Evalúa en lote las reglas activas de intentos y reglas de tiempo según la
    configuración de la plataforma. Si está deshabilitada (enabled: False), sale inmediatamente.
    """
    total_movidos = 0
    detalles_reglas = {}

    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                config = get_lead_automation_config(cur)

                if not config.get("enabled", False):
                    return {
                        "ok": True,
                        "enabled": False,
                        "total_movidos": 0,
                        "motivo": "Automatización deshabilitada en la configuración",
                    }

                reglas_intentos = [
                    r for r in config.get("reglas_intentos", [])
                    if r.get("activo", True) and r.get("estado_destino_id")
                ]
                reglas_tiempo = [
                    r for r in config.get("reglas_tiempo", [])
                    if r.get("activo", True) and r.get("estado_origen_id") and r.get("estado_destino_id")
                ]

                has_ga = _has_gestion_especial_admin_column()
                ga_filter = "AND COALESCE(l.gestion_especial_admin, FALSE) = FALSE" if (has_ga and config.get("respetar_gestion_admin", True)) else ""

                # Obtener catálogo de estados para nombres
                cur.execute("SELECT id, nombre FROM crm.estados_lead")
                estados_nombres = {r["id"]: r["nombre"] for r in (cur.fetchall() or [])}

                # ── PASO 1: Evaluar reglas por intentos ────────────────────────
                if reglas_intentos:
                    reglas_intentos.sort(key=lambda r: (r.get("orden", 1), r.get("min_llamadas", 0)))
                    min_llamadas = min((r.get("min_llamadas", 1) for r in reglas_intentos), default=1)
                    min_wa = min((r.get("min_whatsapp", 0) for r in reglas_intentos), default=0)

                    cur.execute(
                        f"""
                        WITH metricas AS (
                            SELECT
                                l.id,
                                l.asesor_id,
                                l.estado_id,
                                e.nombre AS estado_nombre,
                                e.es_final,
                                (
                                    COALESCE((
                                        SELECT COUNT(*) FROM crm.contactos c
                                        WHERE c.lead_id = l.id
                                          AND LOWER(c.tipo_contacto) IN ('llamada', 'llamada_saliente', 'llamada_entrante', 'telefonica')
                                          AND c.tipo_contacto != 'cambio_estado'
                                    ), 0)
                                    +
                                    COALESCE((
                                        SELECT COUNT(*) FROM crm.llamadas ll
                                        WHERE ll.lead_id = l.id
                                    ), 0)
                                ) AS total_llamadas,
                                (
                                    COALESCE((
                                        SELECT COUNT(*) FROM crm.contactos c
                                        WHERE c.lead_id = l.id
                                          AND c.tipo_contacto ILIKE '%%whatsapp%%'
                                    ), 0)
                                    +
                                    COALESCE((
                                        SELECT COUNT(*) FROM crm.wa_messages wm
                                        JOIN crm.wa_conversations wc ON wc.id = wm.conversation_id
                                        WHERE wc.lead_id = l.id AND wm.direction = 'outbound'
                                    ), 0)
                                ) AS total_wa,
                                (
                                    EXISTS (
                                        SELECT 1 FROM crm.contactos c
                                        WHERE c.lead_id = l.id
                                          AND (
                                              c.resultado IN ('contesto', 'cita_agendada', 'interesado', 'calificado', 'matricula')
                                              OR c.fecha_cita IS NOT NULL
                                              OR COALESCE(c.duracion_minutos, 0) > 0
                                          )
                                    ) OR EXISTS (
                                        SELECT 1 FROM crm.llamadas ll
                                        WHERE ll.lead_id = l.id AND ll.duracion_segundos > 0
                                    )
                                ) AS tiene_contacto_efectivo
                            FROM crm.leads l
                            JOIN crm.estados_lead e ON e.id = l.estado_id
                            WHERE l.activo = TRUE
                              {ga_filter}
                              AND e.es_final = FALSE
                              AND e.nombre NOT ILIKE '%%Matr%%'
                              AND e.nombre NOT ILIKE '%%Ganad%%'
                              AND e.nombre NOT ILIKE '%%Perdid%%'
                              AND e.nombre NOT ILIKE '%%No inter%%'
                              AND e.nombre NOT ILIKE '%%Calific%%'
                              AND e.nombre NOT ILIKE '%%En negociac%%'
                              AND e.nombre NOT ILIKE '%%Bolsa%%'
                        )
                        SELECT * FROM metricas
                        WHERE (NOT {config.get("excluir_contacto_efectivo", True)} OR NOT tiene_contacto_efectivo)
                          AND total_llamadas >= %s
                          AND total_wa >= %s
                        ORDER BY id ASC
                        LIMIT 500
                        """,
                        (min_llamadas, min_wa),
                    )
                    candidatos = cur.fetchall() or []

                    for row in candidatos:
                        lead_id = row["id"]
                        asesor_id = row["asesor_id"]
                        curr_estado_id = row["estado_id"]
                        llamadas = row["total_llamadas"]
                        wa = row["total_wa"]

                        # Determinar mejor regla que califica
                        target_rule = None
                        for r in reversed(reglas_intentos):
                            if llamadas >= r.get("min_llamadas", 0) and wa >= r.get("min_whatsapp", 0):
                                target_rule = r
                                break

                        if not target_rule:
                            continue

                        target_id = target_rule["estado_destino_id"]
                        if curr_estado_id == target_id:
                            continue

                        curr_orden = 0
                        for r in reglas_intentos:
                            if r.get("estado_destino_id") == curr_estado_id:
                                curr_orden = r.get("orden", 0)
                                break

                        if target_rule.get("orden", 0) > curr_orden:
                            cur.execute(
                                """
                                UPDATE crm.leads
                                SET estado_id = %s, updated_at = NOW()
                                WHERE id = %s
                                """,
                                (target_id, lead_id),
                            )

                            target_name = estados_nombres.get(target_id, f"Estado {target_id}")
                            rule_name = target_rule.get("nombre") or "Regla automática"
                            nota = (
                                f"Estado → {target_name} "
                                f"(Cambio automático: {llamadas} intentos telefónicos y {wa} WhatsApp · {rule_name})"
                            )
                            cur.execute(
                                """
                                INSERT INTO crm.contactos (lead_id, asesor_id, tipo_contacto, notas)
                                VALUES (%s, %s, 'cambio_estado', %s)
                                """,
                                (lead_id, asesor_id, nota),
                            )

                            total_movidos += 1
                            detalles_reglas[rule_name] = detalles_reglas.get(rule_name, 0) + 1

                # ── PASO 2: Evaluar reglas por tiempo ──────────────────────────
                for rt in reglas_tiempo:
                    src_id = rt["estado_origen_id"]
                    dst_id = rt["estado_destino_id"]
                    horas = max(1, rt.get("horas_espera", 12))
                    desasignar = rt.get("desasignar_asesor", False)
                    rt_nombre = rt.get("nombre") or f"Transición {horas}h"

                    cur.execute(
                        f"""
                        SELECT
                            l.id,
                            l.asesor_id,
                            e.nombre AS source_estado_nombre
                        FROM crm.leads l
                        JOIN crm.estados_lead e ON e.id = l.estado_id
                        WHERE l.activo = TRUE
                          {ga_filter}
                          AND l.estado_id = %s
                          AND COALESCE(
                                (SELECT MAX(c.created_at) FROM crm.contactos c
                                 WHERE c.lead_id = l.id AND c.tipo_contacto = 'cambio_estado'),
                                l.updated_at,
                                l.created_at
                              ) <= NOW() - (%s || ' hours')::interval
                        LIMIT 200
                        """,
                        (src_id, str(horas)),
                    )
                    leads_tiempo = cur.fetchall() or []

                    dst_name = estados_nombres.get(dst_id, f"Estado {dst_id}")

                    for row in leads_tiempo:
                        lid = row["id"]
                        aid = row["asesor_id"]
                        src_name = row["source_estado_nombre"]

                        if desasignar:
                            cur.execute(
                                """
                                UPDATE crm.leads
                                SET estado_id = %s,
                                    previous_asesor_id = COALESCE(previous_asesor_id, %s::uuid),
                                    asesor_id = NULL,
                                    updated_at = NOW()
                                WHERE id = %s
                                """,
                                (dst_id, aid, lid),
                            )
                            if aid:
                                cur.execute(
                                    """
                                    INSERT INTO crm.asignaciones_log (
                                        lead_id, asesor_anterior, asesor_nuevo, asignado_por, motivo
                                    ) VALUES (%s, %s::uuid, NULL, NULL, %s)
                                    """,
                                    (lid, aid, f"pase_automatico_{rt.get('id', 'tiempo')}"),
                                )
                                cur.execute(
                                    """
                                    UPDATE crm.wa_conversations
                                       SET asesor_id = NULL
                                     WHERE lead_id = %s
                                    """,
                                    (lid,),
                                )
                            nota = (
                                f"Estado → {dst_name} "
                                f"(Cambio automático tras {horas} horas en {src_name} - Asesor desasignado · {rt_nombre})"
                            )
                        else:
                            cur.execute(
                                """
                                UPDATE crm.leads
                                SET estado_id = %s, updated_at = NOW()
                                WHERE id = %s
                                """,
                                (dst_id, lid),
                            )
                            nota = (
                                f"Estado → {dst_name} "
                                f"(Cambio automático tras {horas} horas en {src_name} · {rt_nombre})"
                            )

                        cur.execute(
                            """
                            INSERT INTO crm.contactos (lead_id, asesor_id, tipo_contacto, notas)
                            VALUES (%s, %s, 'cambio_estado', %s)
                            """,
                            (lid, aid, nota),
                        )
                        total_movidos += 1
                        detalles_reglas[rt_nombre] = detalles_reglas.get(rt_nombre, 0) + 1

                conn.commit()

        return {
            "ok": True,
            "enabled": True,
            "total_movidos": total_movidos,
            "detalles": detalles_reglas,
            "dia_1": detalles_reglas.get("Primer escalamiento (Día 1)", 0),
            "dia_2": detalles_reglas.get("Segundo escalamiento (Día 2)", 0),
            "dia_3": detalles_reglas.get("Tercer escalamiento (Día 3)", 0),
            "bolsa_reciclaje": sum(v for k, v in detalles_reglas.items() if "bolsa" in k.lower() or "tiempo" in k.lower()),
        }
    except Exception as exc:
        logger.exception("[Automatización de Estados] Error en ejecución: %s", exc)
        return {
            "ok": False,
            "error": str(exc),
            "total_movidos": 0,
        }


def procesar_automatizacion_no_contesta_dia_3() -> dict:
    """Retrocompatibilidad."""
    res = procesar_automatizaciones_estados_no_contesta()
    return {
        "ok": res.get("ok", False),
        "movidos": res.get("total_movidos", 0),
        "destino": "Configuración dinámica",
        "detalles": res,
    }
