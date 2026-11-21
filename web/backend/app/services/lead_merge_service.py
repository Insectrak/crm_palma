"""
lead_merge_service.py — V067 Fase 3: fusion de leads duplicados.

Patron patrón estándar "Duplicate Management → Merge" / patrón estándar "Merge contacts".

Reglas operativas:
  - Solo admin puede mergear (riesgo: borra historial implícitamente si se
    hace mal). Ya filtrado a nivel de router con require_admin.
  - El SECONDARY queda en DB con merged_into=master_id + activo=FALSE.
    No se borra fisicamente: preserva auditabilidad e historicos.
  - Se migran al master TODOS los registros child del secondary:
      * crm.contactos       (historial de interacciones + citas)
      * crm.llamadas        (registro de calls del Android)
      * crm.lead_tags       (etiquetas/tags si aplica)
      * crm.lead_recontactos (eventos de re-engagement)
      * crm.public_form_submissions (touches por forms publicos)
  - Audit completo en crm.lead_merges con:
      * snapshot del secondary (para deshacer manualmente si hace falta)
      * conteos migrados
      * field_decisions (que conservo del secondary vs master)
      * notes (razon libre del admin)

DESIGN:
  - Una sola transaccion: si algo falla, rollback total. NO queda estado
    inconsistente.
  - field_decisions es un dict opcional {field: 'master' | 'secondary'}.
    Si el admin marco un campo para tomarlo del secondary, lo aplicamos
    al master ANTES de migrar children.
"""
from __future__ import annotations

import json
import logging
from typing import Optional, Any

from fastapi import HTTPException
from psycopg2.extras import RealDictCursor

from app.database import get_db

logger = logging.getLogger(__name__)


# ── Whitelist de campos del master que un admin puede sobreescribir
# desde el secondary durante el merge. Cualquier otro key se ignora
# silenciosamente (blindaje contra inyeccion via JSON).
MERGEABLE_FIELDS = {
    "nombres", "apellidos", "telefono", "email", "dni",
    "tipo_documento", "ciudad", "trabajo", "campana", "observaciones",
    "asesor_id", "supervisor_id", "sede_id", "fuente_id",
}


# ── Tablas con FK a crm.leads(id) que se deben re-apuntar al master
# durante el merge. Las que tienen ON DELETE CASCADE/SET NULL no se
# tocan si igualmente quedan asociadas al secondary (que queda en DB),
# pero queremos consolidar TODO el historial en el master para que el
# admin vea una sola vista coherente.
#
# Formato: (tabla_qualified, col_fk_a_lead, descripcion_para_audit)
CHILD_TABLES = [
    ("crm.contactos",                "lead_id", "contactos_migrated"),
    ("crm.llamadas",                 "lead_id", "llamadas_migrated"),
    ("crm.lead_tags",                "lead_id", "tags_migrated"),
    ("crm.lead_recontactos",         "lead_id", "recontactos_migrated"),
    ("crm.public_form_submissions",  "lead_id", "submissions_migrated"),
    ("crm.asignaciones_log",         "lead_id", "asignaciones_migrated"),
    ("crm.historicos_gestion",       "lead_crm_id", "historicos_migrated"),
    ("crm.lead_historial_cambios",   "lead_id", "historial_migrated"),
]


def _has_column(cur, schema: str, table: str, col: str) -> bool:
    """Verifica si una columna existe en la base de datos."""
    try:
        cur.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s AND column_name = %s
            """,
            (schema, table, col),
        )
        return bool(cur.fetchone())
    except Exception:
        return False


def preview_merge(master_id: int, secondary_id: int) -> dict:
    """Devuelve un payload de comparacion lado a lado de los dos leads.

    Lo usa el frontend para mostrar el diff campo por campo antes de
    confirmar el merge. NO hace cambios.
    """
    if master_id == secondary_id:
        raise HTTPException(status_code=400, detail="master_id y secondary_id no pueden ser iguales.")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            master    = _fetch_lead_full(cur, master_id)
            secondary = _fetch_lead_full(cur, secondary_id)

            if not master or not secondary:
                raise HTTPException(status_code=404, detail="Lead(s) no encontrado(s).")
            if master.get("merged_into") is not None:
                raise HTTPException(
                    status_code=409,
                    detail=f"El lead master {master_id} ya esta mergeado en otro lead.",
                )
            if secondary.get("merged_into") is not None:
                raise HTTPException(
                    status_code=409,
                    detail=f"El lead secondary {secondary_id} ya esta mergeado en otro lead.",
                )

            # Conteos de children para preview
            counts = {}
            for table, col, key in CHILD_TABLES:
                sp_name = f"sp_prev_{table.replace('.', '_')}"
                try:
                    cur.execute(f"SAVEPOINT {sp_name}")
                    cur.execute(f"SELECT COUNT(*)::int AS c FROM {table} WHERE {col} = %s", (secondary_id,))
                    counts[key] = cur.fetchone()["c"]
                    cur.execute(f"RELEASE SAVEPOINT {sp_name}")
                except Exception:  # noqa: BLE001
                    cur.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
                    counts[key] = 0

            return {
                "master":           _strip_secrets(master),
                "secondary":        _strip_secrets(secondary),
                "master_owner":     {
                    "id": str(master.get("asesor_id")) if master.get("asesor_id") else None,
                    "nombre": master.get("asesor_nombre") or "Sin asesor asignado",
                },
                "secondary_owner":  {
                    "id": str(secondary.get("asesor_id")) if secondary.get("asesor_id") else None,
                    "nombre": secondary.get("asesor_nombre") or "Sin asesor asignado",
                },
                "secondary_counts": counts,
                "mergeable_fields": sorted(MERGEABLE_FIELDS),
            }


def merge_leads(
    *,
    master_id: int,
    secondary_id: int,
    chosen_owner_id: Optional[str] = None,
    field_decisions: Optional[dict[str, str]] = None,
    notes: Optional[str] = None,
    admin_user_id: str,
    admin_user_name: Optional[str] = None,
    admin_user_role: Optional[str] = "admin",
) -> dict:
    """Ejecuta el merge en una sola transaccion.

    - chosen_owner_id: UUID del asesor que tendrá la autoridad del lead resultante.
    - field_decisions: {field: 'master' | 'secondary'}.
    - Campos vacíos en el master se autocompletan con datos del secondary (unificación inteligente).
    - Los registros hijos (contactos, llamadas, tags, recontactos, notas) se migran al master.
    - El secondary queda inactivo y apuntando con merged_into = master_id.
    - Se registra el evento en crm.lead_merges y crm.lead_historial_cambios.

    Devuelve {master_id, secondary_id, counts: {...}, merge_id}.
    """
    if master_id == secondary_id:
        raise HTTPException(status_code=400, detail="master_id y secondary_id no pueden ser iguales.")

    field_decisions = field_decisions or {}
    field_decisions = {
        k: v for k, v in field_decisions.items()
        if k in MERGEABLE_FIELDS and v in ("master", "secondary")
    }

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            try:
                # ── Lock pesimista: bloqueamos ambos leads para evitar concurrencia
                cur.execute(
                    "SELECT id, activo, merged_into FROM crm.leads "
                    "WHERE id = ANY(%s) FOR UPDATE",
                    ([master_id, secondary_id],),
                )
                rows = cur.fetchall()
                rows_by_id = {r["id"]: r for r in rows}
                if len(rows_by_id) != 2:
                    raise HTTPException(status_code=404, detail="Lead(s) no encontrado(s).")
                if rows_by_id[master_id]["merged_into"] is not None:
                    raise HTTPException(
                        status_code=409,
                        detail=f"El lead master {master_id} ya esta mergeado.",
                    )
                if rows_by_id[secondary_id]["merged_into"] is not None:
                    raise HTTPException(
                        status_code=409,
                        detail=f"El lead secondary {secondary_id} ya esta mergeado.",
                    )

                # ── Snapshots completos de ambos leads ANTES de modificar nada ──
                master = _fetch_lead_full(cur, master_id)
                secondary = _fetch_lead_full(cur, secondary_id)
                if not master or not secondary:
                    raise HTTPException(status_code=404, detail="No se pudieron cargar los leads para fusión.")

                snapshot_master = _serialize_for_json(master)
                snapshot_secondary = _serialize_for_json(secondary)

                # ── Resolución de autoridad y dueño ──
                owner_id: Optional[str] = None
                owner_name: Optional[str] = None
                owner_supervisor_id: Optional[str] = None

                if chosen_owner_id and str(chosen_owner_id).strip():
                    target_id = str(chosen_owner_id).strip()
                    if target_id == str(secondary.get("asesor_id")):
                        owner_id = str(secondary.get("asesor_id"))
                        owner_name = secondary.get("asesor_nombre") or "Asesor del lead secundario"
                        owner_supervisor_id = str(secondary.get("supervisor_id")) if secondary.get("supervisor_id") else None
                    elif target_id == str(master.get("asesor_id")):
                        owner_id = str(master.get("asesor_id"))
                        owner_name = master.get("asesor_nombre") or "Asesor del lead principal"
                        owner_supervisor_id = str(master.get("supervisor_id")) if master.get("supervisor_id") else None
                    else:
                        cur.execute(
                            "SELECT TRIM(COALESCE(first_name,'') || ' ' || COALESCE(last_name,'')) AS nombre FROM auth.users WHERE id = %s::uuid",
                            (target_id,),
                        )
                        u_row = cur.fetchone()
                        owner_id = target_id
                        owner_name = (u_row["nombre"] if u_row else "").strip() or "Usuario asignado"
                        owner_supervisor_id = None
                elif field_decisions.get("asesor_id") == "secondary":
                    owner_id = str(secondary.get("asesor_id")) if secondary.get("asesor_id") else None
                    owner_name = secondary.get("asesor_nombre")
                    owner_supervisor_id = str(secondary.get("supervisor_id")) if secondary.get("supervisor_id") else None
                else:
                    owner_id = str(master.get("asesor_id")) if master.get("asesor_id") else None
                    owner_name = master.get("asesor_nombre")
                    owner_supervisor_id = str(master.get("supervisor_id")) if master.get("supervisor_id") else None

                # ── Unificación inteligente de datos en el master ──
                updates: dict[str, Any] = {}

                # Asignación de dueño con autoridad
                if owner_id:
                    updates["asesor_id"] = owner_id
                    if owner_supervisor_id:
                        updates["supervisor_id"] = owner_supervisor_id

                # Unificación campo por campo de MERGEABLE_FIELDS
                for f in MERGEABLE_FIELDS:
                    if f in ("asesor_id", "supervisor_id"):
                        continue
                    if f == "observaciones":
                        master_obs = (master.get("observaciones") or "").strip()
                        sec_obs = (secondary.get("observaciones") or "").strip()
                        if field_decisions.get("observaciones") == "secondary":
                            updates["observaciones"] = sec_obs
                        elif master_obs and sec_obs and master_obs != sec_obs:
                            updates["observaciones"] = f"{master_obs}\n\n[Observaciones de lead fusionado #{secondary_id}]:\n{sec_obs}"
                        elif not master_obs and sec_obs:
                            updates["observaciones"] = sec_obs
                        continue

                    # Si el usuario explicitó secondary, o si el master está vacío y el secondary tiene valor
                    if field_decisions.get(f) == "secondary":
                        updates[f] = secondary.get(f)
                    elif (master.get(f) is None or str(master.get(f)).strip() == "") and (secondary.get(f) is not None and str(secondary.get(f)).strip() != ""):
                        updates[f] = secondary.get(f)

                # Unificar ficha técnica si aplica
                master_ft = master.get("ficha_tecnica") or {}
                sec_ft = secondary.get("ficha_tecnica") or {}
                if isinstance(master_ft, str):
                    try:
                        master_ft = json.loads(master_ft)
                    except Exception:
                        master_ft = {}
                if isinstance(sec_ft, str):
                    try:
                        sec_ft = json.loads(sec_ft)
                    except Exception:
                        sec_ft = {}

                if isinstance(sec_ft, dict) and sec_ft:
                    merged_ft = dict(sec_ft)
                    if isinstance(master_ft, dict):
                        for k, v in master_ft.items():
                            if v is not None and str(v).strip() != "":
                                merged_ft[k] = v
                    updates["ficha_tecnica"] = json.dumps(merged_ft)

                # Aplicar UPDATE en el master
                if updates:
                    set_parts = []
                    val_params: list[Any] = []
                    for col_name, col_val in updates.items():
                        if col_name == "ficha_tecnica":
                            set_parts.append("ficha_tecnica = %s::jsonb")
                        elif col_name in ("asesor_id", "supervisor_id", "sede_id"):
                            if col_val:
                                set_parts.append(f"{col_name} = %s::uuid")
                            else:
                                set_parts.append(f"{col_name} = NULL")
                                continue
                        else:
                            set_parts.append(f"{col_name} = %s")
                        val_params.append(col_val)
                    val_params.append(master_id)
                    cur.execute(
                        f"UPDATE crm.leads SET {', '.join(set_parts)}, updated_at = NOW() WHERE id = %s",
                        val_params,
                    )

                # ── Migrar children al master con SAVEPOINTS seguros ─────
                counts: dict[str, int] = {}
                for table, col, key in CHILD_TABLES:
                    sp_name = f"sp_merge_{table.replace('.', '_')}"
                    try:
                        cur.execute(f"SAVEPOINT {sp_name}")
                        cur.execute(
                            f"UPDATE {table} SET {col} = %s WHERE {col} = %s",
                            (master_id, secondary_id),
                        )
                        counts[key] = cur.rowcount or 0
                        cur.execute(f"RELEASE SAVEPOINT {sp_name}")
                    except Exception as exc:  # noqa: BLE001
                        cur.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
                        logger.warning("merge: no se pudo migrar %s.%s: %s", table, col, exc)
                        counts[key] = 0

                # ── Marcar secondary como mergeado + inactivo ────────────
                cur.execute(
                    """
                    UPDATE crm.leads
                    SET merged_into = %s,
                        merged_at   = NOW(),
                        activo      = FALSE,
                        updated_at  = NOW()
                    WHERE id = %s
                    """,
                    (master_id, secondary_id),
                )

                # ── Actualizar flags de fusión en el master (V127) ───────
                if _has_column(cur, "crm", "leads", "has_merged_leads"):
                    cur.execute(
                        """
                        UPDATE crm.leads
                        SET has_merged_leads = TRUE,
                            merged_count     = COALESCE(merged_count, 0) + 1
                        WHERE id = %s
                        """,
                        (master_id,),
                    )

                # ── Audit log del merge en crm.lead_merges ────────────────
                has_master_snap = _has_column(cur, "crm", "lead_merges", "master_snapshot")
                if has_master_snap:
                    cur.execute(
                        """
                        INSERT INTO crm.lead_merges (
                            master_id, secondary_id,
                            merged_by, merged_by_name,
                            field_decisions, contactos_migrated,
                            llamadas_migrated, eventos_migrated,
                            master_snapshot, secondary_snapshot,
                            chosen_owner_id, chosen_owner_name,
                            notes
                        ) VALUES (
                            %s, %s, %s::uuid, %s,
                            %s::jsonb, %s, %s, %s,
                            %s::jsonb, %s::jsonb,
                            %s::uuid, %s,
                            %s
                        )
                        RETURNING id
                        """,
                        (
                            master_id, secondary_id,
                            admin_user_id, admin_user_name,
                            json.dumps(field_decisions),
                            counts.get("contactos_migrated", 0),
                            counts.get("llamadas_migrated", 0),
                            (counts.get("tags_migrated", 0)
                             + counts.get("recontactos_migrated", 0)
                             + counts.get("submissions_migrated", 0)),
                            json.dumps(snapshot_master),
                            json.dumps(snapshot_secondary),
                            owner_id if owner_id else None,
                            owner_name or "Sin asignar",
                            notes or None,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO crm.lead_merges (
                            master_id, secondary_id,
                            merged_by, merged_by_name,
                            field_decisions, contactos_migrated,
                            llamadas_migrated, eventos_migrated,
                            secondary_snapshot, notes
                        ) VALUES (
                            %s, %s, %s::uuid, %s,
                            %s::jsonb, %s, %s, %s,
                            %s::jsonb, %s
                        )
                        RETURNING id
                        """,
                        (
                            master_id, secondary_id,
                            admin_user_id, admin_user_name,
                            json.dumps(field_decisions),
                            counts.get("contactos_migrated", 0),
                            counts.get("llamadas_migrated", 0),
                            (counts.get("tags_migrated", 0)
                             + counts.get("recontactos_migrated", 0)
                             + counts.get("submissions_migrated", 0)),
                            json.dumps(snapshot_secondary),
                            notes or None,
                        ),
                    )
                merge_id = cur.fetchone()["id"]

                # ── Registrar en crm.lead_historial_cambios (Auditoría) ──
                master_display_name = (
                    f"{master.get('nombres') or ''} {master.get('apellidos') or ''}".strip()
                    or f"Lead #{master_id}"
                )
                sec_display_name = (
                    f"{secondary.get('nombres') or ''} {secondary.get('apellidos') or ''}".strip()
                    or f"Lead #{secondary_id}"
                )
                master_asesor_label = master.get("asesor_nombre") or "Sin asesor"
                sec_asesor_label = secondary.get("asesor_nombre") or "Sin asesor"
                chosen_owner_label = owner_name or "Sin asignar"

                history_extra = {
                    "master_id": master_id,
                    "secondary_id": secondary_id,
                    "master_lead": {
                        "id": master_id,
                        "nombre": master_display_name,
                        "nombres": master.get("nombres"),
                        "apellidos": master.get("apellidos"),
                        "telefono": master.get("telefono"),
                        "email": master.get("email"),
                        "dni": master.get("dni"),
                        "tipo_documento": master.get("tipo_documento"),
                        "ciudad": master.get("ciudad"),
                        "trabajo": master.get("trabajo"),
                        "asesor_id": str(master.get("asesor_id")) if master.get("asesor_id") else None,
                        "asesor_nombre": master_asesor_label,
                        "estado_id": master.get("estado_id"),
                        "estado_nombre": master.get("estado_nombre") or "—",
                        "fuente_nombre": master.get("fuente_nombre") or "—",
                        "campana": master.get("campana") or "—",
                        "observaciones": master.get("observaciones"),
                        "created_at": master.get("created_at").isoformat() if hasattr(master.get("created_at"), "isoformat") else str(master.get("created_at") or ""),
                    },
                    "secondary_lead": {
                        "id": secondary_id,
                        "nombre": sec_display_name,
                        "nombres": secondary.get("nombres"),
                        "apellidos": secondary.get("apellidos"),
                        "telefono": secondary.get("telefono"),
                        "email": secondary.get("email"),
                        "dni": secondary.get("dni"),
                        "tipo_documento": secondary.get("tipo_documento"),
                        "ciudad": secondary.get("ciudad"),
                        "trabajo": secondary.get("trabajo"),
                        "asesor_id": str(secondary.get("asesor_id")) if secondary.get("asesor_id") else None,
                        "asesor_nombre": sec_asesor_label,
                        "estado_id": secondary.get("estado_id"),
                        "estado_nombre": secondary.get("estado_nombre") or "—",
                        "fuente_nombre": secondary.get("fuente_nombre") or "—",
                        "campana": secondary.get("campana") or "—",
                        "observaciones": secondary.get("observaciones"),
                        "created_at": secondary.get("created_at").isoformat() if hasattr(secondary.get("created_at"), "isoformat") else str(secondary.get("created_at") or ""),
                    },
                    "chosen_owner_id": str(owner_id) if owner_id else None,
                    "chosen_owner_name": chosen_owner_label,
                    "contactos_migrated": counts.get("contactos_migrated", 0),
                    "llamadas_migrated": counts.get("llamadas_migrated", 0),
                    "notes": notes,
                }

                from app.services import lead_history_service
                lead_history_service.record_field_change(
                    cur=cur,
                    lead_id=master_id,
                    user=admin_user_id,
                    campo="fusion_leads",
                    campo_label="Fusión de leads",
                    valor_anterior=f"Lead #{master_id}: {master_display_name} ({master_asesor_label}) + Lead #{secondary_id}: {sec_display_name} ({sec_asesor_label})",
                    valor_nuevo=f"Fusión completada. Autoridad del lead asignada a: {chosen_owner_label}. Se unificaron datos y registros históricos.",
                    origen="fusion",
                    datos_extra=history_extra,
                )

                # ── Registrar nota en crm.contactos ──────────────────────
                try:
                    cur.execute(
                        """
                        INSERT INTO crm.contactos (
                            lead_id, asesor_id, tipo_contacto, resultado, notas, created_at
                        ) VALUES (
                            %s, %s::uuid, 'nota', 'nota', %s, NOW()
                        )
                        """,
                        (
                            master_id,
                            owner_id if owner_id else None,
                            f"Fusión de leads: se unificaron los datos con el Lead #{secondary_id} ({sec_display_name}). Autoridad asignada a: {chosen_owner_label}.",
                        ),
                    )
                except Exception as exc:
                    logger.warning("[merge] no se pudo insertar nota en crm.contactos: %s", exc)

                conn.commit()
                logger.info(
                    "[merge] OK master=%s secondary=%s authority=%s by=%s counts=%s merge_id=%s",
                    master_id, secondary_id, chosen_owner_label, admin_user_id, counts, merge_id,
                )
                return {
                    "master_id":          master_id,
                    "secondary_id":       secondary_id,
                    "merge_id":           str(merge_id),
                    "chosen_owner_id":    owner_id,
                    "chosen_owner_name":  chosen_owner_label,
                    "counts":             counts,
                }
            except HTTPException:
                conn.rollback()
                raise
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                logger.exception("merge fallo master=%s secondary=%s: %s",
                                 master_id, secondary_id, exc)
                raise HTTPException(status_code=500, detail="No se pudo completar la fusion.")


def get_candidate_duplicates(cur, lead_id: int) -> dict:
    """Busca otros leads activos que compartan el mismo número de teléfono.

    Tolerante a diferencias de formato (+51, espacios, guiones) evaluando
    los últimos 9 dígitos normalizados (formato celular Perú).
    """
    import re

    cur.execute(
        "SELECT id, telefono FROM crm.leads WHERE id = %s",
        (lead_id,),
    )
    lead_row = cur.fetchone()
    if not lead_row:
        raise HTTPException(status_code=404, detail="Lead no encontrado")

    raw_tel = lead_row.get("telefono") or ""
    tel_clean = re.sub(r"\D", "", str(raw_tel))
    if len(tel_clean) < 7:
        return {"has_duplicate": False, "total": 0, "duplicates": []}

    last9 = tel_clean[-9:]

    cur.execute(
        """
        SELECT
            l.id,
            l.nombres,
            l.apellidos,
            TRIM(COALESCE(l.nombres, '') || ' ' || COALESCE(l.apellidos, '')) AS nombre_completo,
            l.telefono,
            l.email,
            l.dni,
            l.tipo_documento,
            l.ciudad,
            l.trabajo,
            l.campana,
            l.observaciones,
            l.created_at::text AS created_at,
            l.created_at::text AS fecha_ingreso,
            l.estado_id,
            e.nombre AS estado_nombre,
            e.color_hex AS estado_color_hex,
            l.fuente_id,
            f.nombre AS fuente_nombre,
            l.asesor_id::text AS asesor_id,
            TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, '')) AS asesor_nombre,
            u.email AS asesor_email,
            l.supervisor_id::text AS supervisor_id,
            TRIM(COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, '')) AS supervisor_nombre,
            l.ficha_tecnica
        FROM crm.leads l
        LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
        LEFT JOIN crm.fuentes f      ON f.id = l.fuente_id
        LEFT JOIN auth.users u       ON u.id = l.asesor_id
        LEFT JOIN auth.users s       ON s.id = l.supervisor_id
        WHERE l.id <> %s
          AND l.activo = TRUE
          AND l.merged_into IS NULL
          AND l.telefono IS NOT NULL
          AND l.telefono <> ''
          AND (
              (LENGTH(REGEXP_REPLACE(l.telefono, '\\D', '', 'g')) >= 9 AND RIGHT(REGEXP_REPLACE(l.telefono, '\\D', '', 'g'), 9) = %s)
              OR REGEXP_REPLACE(l.telefono, '\\D', '', 'g') = %s
          )
        ORDER BY l.created_at DESC
        LIMIT 20
        """,
        (lead_id, last9, tel_clean),
    )
    rows = cur.fetchall() or []
    duplicates = [dict(r) for r in rows]
    return {
        "has_duplicate": len(duplicates) > 0,
        "total": len(duplicates),
        "duplicates": duplicates,
    }


def get_lead_merges(cur, lead_id: int) -> list[dict]:
    """Obtiene el historial de fusiones en las que este lead fue el master."""
    has_snap = _has_column(cur, "crm", "lead_merges", "master_snapshot")
    has_owner = _has_column(cur, "crm", "lead_merges", "chosen_owner_name")

    master_snap_sql = "COALESCE(m.master_snapshot, '{}'::jsonb) AS master_snapshot," if has_snap else "'{}'::jsonb AS master_snapshot,"
    owner_sql = "m.chosen_owner_id::text AS chosen_owner_id, COALESCE(m.chosen_owner_name, '') AS chosen_owner_name," if has_owner else "NULL AS chosen_owner_id, '' AS chosen_owner_name,"

    try:
        cur.execute(
            f"""
            SELECT
                m.id::text AS id,
                m.master_id,
                m.secondary_id,
                m.merged_by::text AS merged_by,
                COALESCE(NULLIF(m.merged_by_name, ''), 'Sistema') AS merged_by_name,
                m.merged_at::text AS merged_at,
                m.contactos_migrated,
                m.llamadas_migrated,
                m.eventos_migrated,
                m.field_decisions,
                m.notes,
                {master_snap_sql}
                COALESCE(m.secondary_snapshot, '{{}}'::jsonb) AS secondary_snapshot,
                {owner_sql}
                l_sec.nombres AS secondary_nombres,
                l_sec.apellidos AS secondary_apellidos
            FROM crm.lead_merges m
            LEFT JOIN crm.leads l_sec ON l_sec.id = m.secondary_id
            WHERE m.master_id = %s
            ORDER BY m.merged_at DESC
            """,
            (lead_id,),
        )
        rows = cur.fetchall() or []
        res = []
        for r in rows:
            d = dict(r)
            # Asegurar datos legibles en snapshots si estaban vacíos
            if not d.get("master_snapshot") or d.get("master_snapshot") == {}:
                d["master_snapshot"] = {"id": d["master_id"]}
            if not d.get("secondary_snapshot") or d.get("secondary_snapshot") == {}:
                d["secondary_snapshot"] = {
                    "id": d["secondary_id"],
                    "nombre": f"{d.get('secondary_nombres') or ''} {d.get('secondary_apellidos') or ''}".strip(),
                }
            res.append(d)
        return res
    except Exception as exc:
        logger.warning("[lead_merge] error al consultar crm.lead_merges para lead=%s: %s", lead_id, exc)
        return []


def list_duplicate_clusters(*, limit: int = 500) -> dict:
    """Devuelve grupos de leads activos sospechosos de ser duplicados.

    Heuristica: leads con el MISMO telefono (siempre disponible) que no
    estan mergeados todavia. CRMs profesionales usan reglas mas complejas
    (fuzzy name + email), pero el telefono es la senal de match mas
    fuerte en el flujo de Palma (todos los leads tienen telefono
    validado a E.164).

    Devuelve {clusters: [{telefono, total, leads: [...]}], total_clusters,
              total_capped: bool}. `total_capped` indica si llegamos al
    LIMIT (entonces hay mas clusters no devueltos — el admin necesita
    paginacion o subir el limite).

    Ordenamiento: mas recientes primero (MAX(created_at) DESC). Antes
    estaba `total DESC, MAX(created_at) DESC`, lo que tiraba al fondo los
    clusters de 2 leads cuando habia muchos de 3+. Eso hacia que al
    fusionar (cluster pasa de 3 a 2), el cluster cayera mas abajo en la
    lista — confundia al admin que creia que el cluster "desaparecio"
    cuando en realidad estaba mas abajo.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Total de clusters detectados (sin LIMIT) — para indicar al
            # admin si lo que ve esta capado.
            cur.execute(
                """
                SELECT COUNT(*)::int AS c FROM (
                    SELECT 1 FROM crm.leads
                    WHERE activo = TRUE
                      AND merged_into IS NULL
                      AND telefono IS NOT NULL
                      AND telefono <> ''
                    GROUP BY telefono
                    HAVING COUNT(*) > 1
                ) x
                """
            )
            total_clusters_global = cur.fetchone()["c"]

            cur.execute(
                """
                WITH dupes AS (
                    SELECT telefono,
                           COUNT(*)::int AS total,
                           MAX(created_at) AS last_at
                    FROM crm.leads
                    WHERE activo = TRUE
                      AND merged_into IS NULL
                      AND telefono IS NOT NULL
                      AND telefono <> ''
                    GROUP BY telefono
                    HAVING COUNT(*) > 1
                    ORDER BY MAX(created_at) DESC
                    LIMIT %s
                )
                SELECT
                    d.telefono,
                    d.total,
                    d.last_at,
                    l.id, l.nombres, l.apellidos, l.email, l.dni,
                    l.created_at, l.estado_id,
                    e.nombre AS estado_nombre,
                    f.nombre AS fuente_nombre,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS asesor_nombre
                FROM dupes d
                JOIN crm.leads l       ON l.telefono = d.telefono
                LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
                LEFT JOIN crm.fuentes      f ON f.id = l.fuente_id
                LEFT JOIN auth.users       u ON u.id = l.asesor_id
                WHERE l.activo = TRUE AND l.merged_into IS NULL
                ORDER BY d.last_at DESC, d.telefono, l.created_at ASC
                """,
                (limit,),
            )
            rows = cur.fetchall()

    # Agrupar por telefono
    clusters: dict[str, dict] = {}
    for r in rows:
        tel = r["telefono"]
        if tel not in clusters:
            clusters[tel] = {"telefono": tel, "total": r["total"], "leads": []}
        clusters[tel]["leads"].append({
            "id":              r["id"],
            "nombres":         r["nombres"],
            "apellidos":       r["apellidos"],
            "email":           r["email"],
            "dni":             r["dni"],
            "created_at":      r["created_at"].isoformat() if r["created_at"] else None,
            "estado_nombre":   r["estado_nombre"],
            "fuente_nombre":   r["fuente_nombre"],
            "asesor_nombre":   r["asesor_nombre"] or None,
        })
    cluster_list = list(clusters.values())
    return {
        "clusters":              cluster_list,
        "total_clusters_global": total_clusters_global,
        "total_capped":          total_clusters_global > len(cluster_list),
        "limit":                 limit,
    }


# ── Helpers privados ──────────────────────────────────────────────────────

def _fetch_lead_full(cur, lead_id: int) -> Optional[dict]:
    """Trae todos los campos relevantes del lead + nombres resueltos."""
    cur.execute(
        """
        SELECT
            l.*,
            e.nombre AS estado_nombre,
            f.nombre AS fuente_nombre,
            TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS asesor_nombre,
            TRIM(COALESCE(s.first_name,'') || ' ' || COALESCE(s.last_name,'')) AS supervisor_nombre
        FROM crm.leads l
        LEFT JOIN crm.estados_lead e ON e.id = l.estado_id
        LEFT JOIN crm.fuentes      f ON f.id = l.fuente_id
        LEFT JOIN auth.users       u ON u.id = l.asesor_id
        LEFT JOIN auth.users       s ON s.id = l.supervisor_id
        WHERE l.id = %s
        """,
        (lead_id,),
    )
    return cur.fetchone()


def _serialize_for_json(d: dict) -> dict:
    """Convierte datetime/UUID a strings para que jsonb-serializable."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif v is None or isinstance(v, (str, int, float, bool, list, dict)):
            out[k] = v
        else:
            out[k] = str(v)
    return out


def _strip_secrets(d: dict) -> dict:
    """Saca campos no relevantes para el preview UI."""
    out = dict(d)
    for k in ("merged_into", "merged_at", "created_by", "updated_at",
              "duplicate_override_reason", "created_with_duplicate_override"):
        out.pop(k, None)
    # Serializar fechas
    for k, v in list(out.items()):
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif v is not None and not isinstance(v, (str, int, float, bool, list, dict)):
            out[k] = str(v)
    return out
