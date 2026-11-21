"""
lead_history_service.py — Servicio de historial y auditoría de cambios en leads.

Registra detalladamente cada modificación efectuada sobre un lead:
- Quién hizo el cambio (usuario autenticado o sistema).
- Cuándo se realizó el cambio (timestamp).
- Campo modificado con su etiqueta legible (ej: "Teléfono", "Estado", "Fuente", "Asesor").
- Valor anterior y valor nuevo legibles (resolviendo IDs foráneos a nombres).
- Origen del cambio ('edicion_ficha', 'cambio_estado', 'reasignacion', 'ficha_tecnica', 'sistema', etc.).

Fail-safe: los errores al registrar en el historial se loguean pero nunca
deben tumbar la transacción principal de edición del lead.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

FIELD_LABELS: dict[str, str] = {
    "nombres": "Nombres",
    "apellidos": "Apellidos",
    "telefono": "Teléfono",
    "email": "Correo electrónico",
    "ciudad": "Ciudad",
    "trabajo": "Trabajo / Ocupación",
    "dni": "Documento / DNI",
    "tipo_documento": "Tipo de documento",
    "fuente_id": "Fuente",
    "estado_id": "Estado",
    "asesor_id": "Asesor asignado",
    "supervisor_id": "Supervisor asignado",
    "sede_id": "Sede",
    "calidad": "Calidad",
    "campana": "Campaña",
    "observaciones": "Observaciones",
    "referido_por": "Referido por",
    "codigo_convenio": "Código de convenio",
    "fecha_proxima_gestion": "Fecha próxima gestión",
    "accion_proxima_gestion": "Acción próxima gestión",
    "motivo_perdida": "Motivo de pérdida",
    "motivo_perdida_otro": "Detalle motivo de pérdida",
    "tipo_cierre": "Tipo de cierre",
    "segunda_voz": "Segunda voz",
    "gestion_especial_admin": "Gestión especial Administración",
    "activo": "Estado en sistema (Activo / Papelera)",
}

FICHA_TECNICA_KEYS: dict[str, str] = {
    "motivacion": "Ficha técnica: Motivación",
    "beneficiario": "Ficha técnica: Beneficiario",
    "ubicacion": "Ficha técnica: Ubicación",
    "experiencia_previa": "Ficha técnica: Experiencia previa",
    "necesidad_actual": "Ficha técnica: Necesidad actual",
    "inicio": "Ficha técnica: Inicio estimado",
}


def _normalize_str(val: Any) -> Optional[str]:
    """Normaliza un valor a string limpio o None."""
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def _resolve_user_info(cur, user: Any) -> tuple[Optional[str], str, str]:
    """Obtiene (usuario_id, usuario_nombre, usuario_rol) del actor del cambio."""
    if not user:
        return None, "Sistema", "sistema"

    if isinstance(user, (str, UUID)):
        user_id = str(user).strip()
        user_role = "usuario"
        nombre_prop = None
    else:
        user_id = str(getattr(user, "user_id", None) or getattr(user, "id", None) or "").strip()
        user_role = str(getattr(user, "role", None) or "usuario")
        nombre_prop = getattr(user, "nombre_completo", None)

    if not user_id:
        return None, "Sistema", "sistema"

    if nombre_prop and str(nombre_prop).strip():
        return user_id, str(nombre_prop).strip(), user_role

    try:
        cur.execute(
            """
            SELECT
                TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')) AS nombre,
                email,
                role
            FROM auth.users
            WHERE id = %s::uuid
            """,
            (user_id,),
        )
        row = cur.fetchone()
        if row:
            nombre = (row.get("nombre") or "").strip() or row.get("email") or "Usuario"
            rol = row.get("role") or user_role
            return user_id, nombre, rol
    except Exception as exc:  # noqa: BLE001
        logger.debug("[lead_history] no se pudo resolver usuario_id=%s: %s", user_id, exc)

    return user_id, "Usuario", user_role


def _resolve_estado_nombre(cur, estado_id: Any) -> Optional[str]:
    if not estado_id:
        return None
    try:
        cur.execute("SELECT nombre FROM crm.estados_lead WHERE id = %s", (int(estado_id),))
        row = cur.fetchone()
        if row:
            return row.get("nombre") if isinstance(row, dict) else row[0]
    except Exception:
        pass
    return str(estado_id)


def _resolve_fuente_nombre(cur, fuente_id: Any) -> Optional[str]:
    if not fuente_id:
        return None
    try:
        cur.execute("SELECT nombre FROM crm.fuentes WHERE id = %s", (int(fuente_id),))
        row = cur.fetchone()
        if row:
            return row.get("nombre") if isinstance(row, dict) else row[0]
    except Exception:
        pass
    return str(fuente_id)


def _resolve_asesor_nombre(cur, asesor_id: Any) -> Optional[str]:
    if not asesor_id:
        return None
    try:
        cur.execute(
            """
            SELECT TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')) AS nombre, email
            FROM auth.users WHERE id = %s::uuid
            """,
            (str(asesor_id),),
        )
        row = cur.fetchone()
        if row:
            n = (row.get("nombre") if isinstance(row, dict) else row[0]) or ""
            e = (row.get("email") if isinstance(row, dict) else row[1]) or ""
            return n.strip() or e or str(asesor_id)
    except Exception:
        pass
    return str(asesor_id)


def _resolve_sede_nombre(cur, sede_id: Any) -> Optional[str]:
    if not sede_id:
        return None
    try:
        cur.execute("SELECT nombre FROM crm.sedes WHERE id = %s::uuid", (str(sede_id),))
        row = cur.fetchone()
        if row:
            return row.get("nombre") if isinstance(row, dict) else row[0]
    except Exception:
        pass
    return str(sede_id)


def _has_datos_extra_column(cur) -> bool:
    try:
        cur.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'crm'
              AND table_name = 'lead_historial_cambios'
              AND column_name = 'datos_extra'
            """
        )
        return bool(cur.fetchone())
    except Exception:
        return False


def record_field_change(
    cur,
    lead_id: int,
    user: Any,
    campo: str,
    campo_label: str,
    valor_anterior: Any,
    valor_nuevo: Any,
    origen: str = "edicion_ficha",
    datos_extra: Optional[dict] = None,
) -> None:
    """Registra un único cambio de campo en `crm.lead_historial_cambios`.

    Idempotente ante no-ops: si `valor_anterior == valor_nuevo` (normalizados),
    se ignora para no ensuciar el historial.
    """
    v_old = _normalize_str(valor_anterior)
    v_new = _normalize_str(valor_nuevo)

    if v_old == v_new and not datos_extra:
        return

    try:
        user_id, user_nombre, user_rol = _resolve_user_info(cur, user)
        has_extra = _has_datos_extra_column(cur)
        if has_extra and datos_extra:
            cur.execute(
                """
                INSERT INTO crm.lead_historial_cambios (
                    lead_id, usuario_id, usuario_nombre, usuario_rol,
                    campo, campo_label, valor_anterior, valor_nuevo, origen, datos_extra, created_at
                )
                VALUES (%s, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, NOW())
                """,
                (
                    lead_id,
                    user_id,
                    user_nombre,
                    user_rol,
                    campo,
                    campo_label,
                    v_old or "—",
                    v_new or "—",
                    origen,
                    json.dumps(datos_extra),
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO crm.lead_historial_cambios (
                    lead_id, usuario_id, usuario_nombre, usuario_rol,
                    campo, campo_label, valor_anterior, valor_nuevo, origen, created_at
                )
                VALUES (%s, %s::uuid, %s, %s, %s, %s, %s, %s, %s, NOW())
                """,
                (
                    lead_id,
                    user_id,
                    user_nombre,
                    user_rol,
                    campo,
                    campo_label,
                    v_old or "—",
                    v_new or "—",
                    origen,
                ),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[lead_history] error al registrar cambio de campo=%s lead=%s: %s", campo, lead_id, exc)


def record_lead_updates(
    cur,
    lead_id: int,
    user: Any,
    old_lead: dict,
    new_fields: dict,
    origin: str = "edicion_ficha",
) -> None:
    """Compara el estado previo del lead contra los nuevos campos enviados y registra
    todas las diferencias encontradas en `crm.lead_historial_cambios`.
    """
    if not old_lead or not new_fields:
        return

    try:
        for campo, new_raw in new_fields.items():
            if campo == "ficha_tecnica":
                # Ficha técnica: registrar cada pregunta individual que cambió
                old_ft = old_lead.get("ficha_tecnica") or {}
                if isinstance(old_ft, str):
                    try:
                        old_ft = json.loads(old_ft)
                    except Exception:
                        old_ft = {}
                elif not isinstance(old_ft, dict):
                    old_ft = {}

                new_ft = new_raw if isinstance(new_raw, dict) else {}
                for fkey, flabel in FICHA_TECNICA_KEYS.items():
                    old_ans = old_ft.get(fkey)
                    new_ans = new_ft.get(fkey)
                    if _normalize_str(old_ans) != _normalize_str(new_ans):
                        record_field_change(
                            cur,
                            lead_id=lead_id,
                            user=user,
                            campo=f"ficha_tecnica.{fkey}",
                            campo_label=flabel,
                            valor_anterior=old_ans,
                            valor_nuevo=new_ans,
                            origen="ficha_tecnica",
                        )
                continue

            if campo not in FIELD_LABELS:
                continue

            label = FIELD_LABELS[campo]
            old_raw = old_lead.get(campo)

            # Resoluciones foráneas para que el usuario vea nombres en vez de IDs
            if campo == "estado_id":
                old_display = _resolve_estado_nombre(cur, old_raw)
                new_display = _resolve_estado_nombre(cur, new_raw)
            elif campo == "fuente_id":
                old_display = _resolve_fuente_nombre(cur, old_raw)
                new_display = _resolve_fuente_nombre(cur, new_raw)
            elif campo == "asesor_id":
                old_display = _resolve_asesor_nombre(cur, old_raw)
                new_display = _resolve_asesor_nombre(cur, new_raw)
            elif campo == "sede_id":
                old_display = _resolve_sede_nombre(cur, old_raw)
                new_display = _resolve_sede_nombre(cur, new_raw)
            elif campo == "gestion_especial_admin":
                old_display = "Activado" if bool(old_raw) else "Desactivado"
                new_display = "Activado" if bool(new_raw) else "Desactivado"
            elif campo == "activo":
                old_display = "Activo" if bool(old_raw) else "En papelera"
                new_display = "Activo" if bool(new_raw) else "En papelera"
            else:
                old_display = old_raw
                new_display = new_raw

            record_field_change(
                cur,
                lead_id=lead_id,
                user=user,
                campo=campo,
                campo_label=label,
                valor_anterior=old_display,
                valor_nuevo=new_display,
                origen=origin,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[lead_history] error al procesar record_lead_updates lead=%s: %s", lead_id, exc)


def record_status_change(
    cur,
    lead_id: int,
    user: Any,
    old_estado_id: Optional[int],
    new_estado_id: int,
    extra_details: Optional[str] = None,
    origen: str = "cambio_estado",
) -> None:
    """Registra una transición de estado de un lead."""
    if old_estado_id == new_estado_id and not extra_details:
        return

    old_nombre = _resolve_estado_nombre(cur, old_estado_id) or "Sin estado"
    new_nombre = _resolve_estado_nombre(cur, new_estado_id) or str(new_estado_id)

    valor_nuevo = new_nombre
    if extra_details and str(extra_details).strip():
        valor_nuevo += f" · {str(extra_details).strip()}"

    record_field_change(
        cur,
        lead_id=lead_id,
        user=user,
        campo="estado_id",
        campo_label="Estado",
        valor_anterior=old_nombre,
        valor_nuevo=valor_nuevo,
        origen=origen,
    )


def record_reassignment(
    cur,
    lead_id: int,
    user: Any,
    old_asesor_id: Optional[str],
    new_asesor_id: Optional[str],
    motivo: str = "manual",
) -> None:
    """Registra la reasignación de un lead."""
    old_name = _resolve_asesor_nombre(cur, old_asesor_id) or "Sin asignar"
    new_name = _resolve_asesor_nombre(cur, new_asesor_id) or "Liberado (Sin asesor)"

    motivo_label = {
        "inicial": "Asignación inicial",
        "round_robin": "Round-robin",
        "campana_exclusiva": "Leads Campañas",
        "auto_asignacion": "Reparto automático",
        "manual_supervisor": "Reasignación",
        "manual_admin": "Reasignación (admin)",
        "derivacion_supervisor": "Derivación supervisor",
        "derivacion_antecedente": "Devuelto por antecedentes",
        "liberacion": "Liberación",
    }.get(motivo, motivo or "Reasignación")

    record_field_change(
        cur,
        lead_id=lead_id,
        user=user,
        campo="asesor_id",
        campo_label="Asesor asignado",
        valor_anterior=old_name,
        valor_nuevo=f"{new_name} ({motivo_label})",
        origen="reasignacion",
    )


def get_lead_history(cur, lead_id: int, limit: int = 150, offset: int = 0) -> dict:
    """Retorna el historial completo de cambios de un lead ordenado cronológicamente (DESC)."""
    cur.execute(
        """
        SELECT COUNT(*) FROM crm.lead_historial_cambios
        WHERE lead_id = %s
        """,
        (lead_id,),
    )
    total_row = cur.fetchone()
    total = total_row["count"] if isinstance(total_row, dict) else (total_row[0] if total_row else 0)

    has_extra = _has_datos_extra_column(cur)
    extra_field = "COALESCE(h.datos_extra, '{}'::jsonb) AS datos_extra," if has_extra else "'{}'::jsonb AS datos_extra,"

    cur.execute(
        f"""
        SELECT
            h.id,
            h.lead_id,
            h.usuario_id::text AS usuario_id,
            COALESCE(NULLIF(h.usuario_nombre, ''), 'Sistema') AS usuario_nombre,
            COALESCE(NULLIF(h.usuario_rol, ''), 'sistema') AS usuario_rol,
            h.campo,
            h.campo_label,
            h.valor_anterior,
            h.valor_nuevo,
            h.origen,
            {extra_field}
            h.created_at::text AS created_at
        FROM crm.lead_historial_cambios h
        WHERE h.lead_id = %s
        ORDER BY h.created_at DESC, h.id DESC
        LIMIT %s OFFSET %s
        """,
        (lead_id, limit, offset),
    )
    rows = cur.fetchall() or []
    return {
        "items": rows,
        "total": total,
    }
