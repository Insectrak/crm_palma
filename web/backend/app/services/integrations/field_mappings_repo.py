"""Repository + servicio de Field Mappings (patrón estándar).

Tres responsabilidades distintas — mantenidas en el mismo módulo porque
comparten el mismo modelo de datos y ciclo de vida:

  1. `property_definitions`   — catálogo de propiedades custom tipadas.
  2. `form_field_mappings`    — regla meta_field → target (columna o propiedad).
  3. `lead_properties`        — valores por lead (EAV).

Diseño:
  - SRP: solo CRUD y la función `apply_mappings` que traduce un
    `raw_field_data` de Meta en escrituras concretas. No hace HTTP,
    no autentica, no loggea eventos de integración (eso le toca al caller).
  - Las escrituras sobre `crm.leads` quedan confinadas a una whitelist de
    columnas seguras (ALLOWED_COLUMN_TARGETS). Cualquier `target_key` fuera
    de esa lista se rechaza al guardar el mapeo — no hay camino de inyección
    de identificadores.
  - `apply_mappings` recibe el cursor abierto; el caller hace commit.
    Es idempotente por `(lead_id, property_key)` y por el guard
    "solo sobreescribe la columna si está vacía" (el primer submit gana).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable, Optional

from psycopg2.extras import Json, RealDictCursor

from app.database import get_db

logger = logging.getLogger(__name__)

# Columnas de crm.leads aptas para ser target directo de un mapping.
# Cualquier nombre fuera de aquí se rechaza al guardar (no hay inyección
# porque el valor nunca entra en el SQL como identificador sin validarse).
ALLOWED_COLUMN_TARGETS = frozenset({
    "nombres", "apellidos", "email", "campana", "observaciones",
})

ALLOWED_PROPERTY_TYPES = frozenset({"text", "number", "date", "boolean", "select"})
ALLOWED_TARGET_TYPES = frozenset({"column", "property", "ignore"})

# Campos que ingest_core ya maneja nativamente y que no deberían aparecer
# como "detectados sin mapear" — los filtramos del reporte de unmapped.
_WELL_KNOWN_NATIVE_FIELDS = frozenset({
    "phone_number", "phone", "telephone", "telefono", "teléfono", "celular",
    "mobile", "mobile_phone",
    "email", "correo", "correo_electronico", "correo electrónico",
    "full_name", "name", "nombre_completo", "nombre completo",
    "first_name", "nombre", "nombres",
    "last_name", "apellido", "apellidos",
})

_SLUG_RE = re.compile(r"[^a-z0-9_]+")


class FieldMappingError(Exception):
    """Errores de negocio (no de DB)."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def slugify_key(raw: str) -> str:
    """Convierte 'Proyecto de Interés' → 'proyecto_de_interes' (ASCII-safe)."""
    if not raw:
        return ""
    import unicodedata
    # Quita acentos — NFKD + drop combining marks.
    s = unicodedata.normalize("NFKD", str(raw))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace(" ", "_")
    s = _SLUG_RE.sub("_", s).strip("_")
    return s


def _row_to_property(row: dict) -> dict:
    return {
        "id":            row["id"],
        "property_key":  row["property_key"],
        "display_name":  row["display_name"],
        "property_type": row["property_type"],
        "options":       row.get("options"),
        "description":   row.get("description"),
        "category":      row.get("category"),
        "icon":          row.get("icon"),
        "is_system":     bool(row.get("is_system")),
        "is_active":     bool(row.get("is_active", True)),
        "created_at":    row.get("created_at"),
        "updated_at":    row.get("updated_at"),
    }


def _row_to_mapping(row: dict) -> dict:
    return {
        "id":              row["id"],
        "provider":        row["provider"],
        "form_id":         row["form_id"],
        "meta_field_name": row["meta_field_name"],
        "target_type":     row["target_type"],
        "target_key":      row.get("target_key"),
        "created_at":      row.get("created_at"),
        "updated_at":      row.get("updated_at"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# property_definitions — CRUD
# ─────────────────────────────────────────────────────────────────────────────

def list_property_definitions(active_only: bool = True) -> list[dict]:
    where = "WHERE is_active = TRUE" if active_only else ""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT id, property_key, display_name, property_type, options,
                       description, category, icon, is_system, is_active,
                       created_at, updated_at
                  FROM crm.property_definitions
                  {where}
                 ORDER BY COALESCE(category, ''), display_name
                """
            )
            return [_row_to_property(r) for r in cur.fetchall()]


def get_property_definition(property_key: str) -> Optional[dict]:
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, property_key, display_name, property_type, options,
                       description, category, icon, is_system, is_active,
                       created_at, updated_at
                  FROM crm.property_definitions
                 WHERE property_key = %s
                """,
                (property_key,),
            )
            row = cur.fetchone()
            return _row_to_property(row) if row else None


def upsert_property_definition(
    *,
    property_key: str,
    display_name: str,
    property_type: str = "text",
    options: Optional[list] = None,
    description: Optional[str] = None,
    category: Optional[str] = None,
    icon: Optional[str] = None,
    created_by: Optional[str] = None,
) -> dict:
    """Crea o actualiza una propiedad. `property_key` es inmutable."""
    key = slugify_key(property_key)
    if not key:
        raise FieldMappingError(400, "property_key inválido.")
    if property_type not in ALLOWED_PROPERTY_TYPES:
        raise FieldMappingError(400, f"Tipo '{property_type}' no soportado.")
    if property_type == "select" and not options:
        raise FieldMappingError(400, "Para tipo 'select' debes indicar al menos una opción.")
    display_name = (display_name or "").strip()
    if not display_name:
        raise FieldMappingError(400, "display_name es obligatorio.")

    opts_json = Json(options) if options is not None else None

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO crm.property_definitions
                    (property_key, display_name, property_type, options,
                     description, category, icon, created_by, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (property_key) DO UPDATE SET
                    display_name  = EXCLUDED.display_name,
                    property_type = EXCLUDED.property_type,
                    options       = EXCLUDED.options,
                    description   = EXCLUDED.description,
                    category      = EXCLUDED.category,
                    icon          = EXCLUDED.icon,
                    updated_at    = NOW()
                RETURNING id, property_key, display_name, property_type, options,
                          description, category, icon, is_system, is_active,
                          created_at, updated_at
                """,
                (key, display_name, property_type, opts_json,
                 description, category, icon, created_by),
            )
            row = cur.fetchone()
        conn.commit()
    logger.info("field_mappings: upsert property '%s' (type=%s) by %s",
                key, property_type, created_by or "?")
    return _row_to_property(row)


def delete_property_definition(property_key: str) -> bool:
    """Marca is_active=FALSE. No borra fila — preserva valores en lead_properties."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT is_system FROM crm.property_definitions WHERE property_key = %s",
                (property_key,),
            )
            row = cur.fetchone()
            if not row:
                return False
            if row[0]:
                raise FieldMappingError(400, "No se pueden desactivar propiedades del sistema.")
            cur.execute(
                "UPDATE crm.property_definitions SET is_active = FALSE, updated_at = NOW() "
                "WHERE property_key = %s",
                (property_key,),
            )
        conn.commit()
    return True


def delete_property_values(
    property_key: str,
    dry_run: bool = False,
    triggered_by: str = "unknown",
) -> dict:
    """Borra (o cuenta, en dry_run) los valores guardados en crm.lead_properties
    para una propiedad. Operación destructiva e idempotente; admin-only en el router.

    Devuelve {property_key, count, dry_run, deleted}.
      - count    → cuántos valores existían antes de borrar.
      - deleted  → cuántas filas eliminó realmente (0 en dry_run).

    Nota: NO toca property_definitions — borra solo el lado EAV. La definición
    sigue activa (o desactivada por delete_property_definition) según el caller.
    """
    if not property_key or not str(property_key).strip():
        raise FieldMappingError(400, "property_key requerido.")
    key = str(property_key).strip()
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM crm.lead_properties WHERE property_key = %s",
                (key,),
            )
            count_row = cur.fetchone()
            count = int(count_row[0]) if count_row else 0
            deleted = 0
            if not dry_run and count > 0:
                cur.execute(
                    "DELETE FROM crm.lead_properties WHERE property_key = %s",
                    (key,),
                )
                deleted = cur.rowcount or 0
        conn.commit()
    if dry_run:
        logger.info(
            "field_mappings.delete_values.dry_run property_key=%s count=%d triggered_by=%s",
            key, count, triggered_by,
        )
    else:
        logger.warning(
            "field_mappings.delete_values property_key=%s deleted=%d triggered_by=%s",
            key, deleted, triggered_by,
        )
    return {
        "property_key": key,
        "count":        count,
        "dry_run":      dry_run,
        "deleted":      deleted,
    }


# ─────────────────────────────────────────────────────────────────────────────
# form_field_mappings — CRUD
# ─────────────────────────────────────────────────────────────────────────────

def list_form_field_mappings(
    provider: Optional[str] = None,
    form_id: Optional[str] = None,
) -> list[dict]:
    clauses = []
    params: list[Any] = []
    if provider:
        clauses.append("provider = %s")
        params.append(provider)
    if form_id:
        clauses.append("form_id = %s")
        params.append(form_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT id, provider, form_id, meta_field_name, target_type, target_key,
                       created_at, updated_at
                  FROM crm.form_field_mappings
                  {where}
                 ORDER BY form_id, meta_field_name
                """,
                tuple(params),
            )
            return [_row_to_mapping(r) for r in cur.fetchall()]


def _validate_mapping(
    *,
    target_type: str,
    target_key: Optional[str],
) -> Optional[str]:
    """Valida target_type y target_key. Normaliza target_key o devuelve None."""
    if target_type not in ALLOWED_TARGET_TYPES:
        raise FieldMappingError(400, f"target_type '{target_type}' inválido.")
    if target_type == "ignore":
        return None
    key = (target_key or "").strip()
    if not key:
        raise FieldMappingError(400, "target_key es obligatorio para este target_type.")
    if target_type == "column":
        if key not in ALLOWED_COLUMN_TARGETS:
            raise FieldMappingError(
                400,
                f"Columna '{key}' no permitida como target. "
                f"Permitidas: {sorted(ALLOWED_COLUMN_TARGETS)}",
            )
        return key
    if target_type == "property":
        # Validamos que exista la propiedad (podría autocrearse desde otra API).
        existing = get_property_definition(key)
        if not existing or not existing.get("is_active"):
            raise FieldMappingError(
                400,
                f"La propiedad '{key}' no existe o está desactivada.",
            )
        return key
    return key


def upsert_form_field_mapping(
    *,
    provider: str = "meta",
    form_id: str,
    meta_field_name: str,
    target_type: str,
    target_key: Optional[str] = None,
    created_by: Optional[str] = None,
) -> dict:
    form_id = (form_id or "").strip() or "_any_"
    name = (meta_field_name or "").strip().lower()
    if not name:
        raise FieldMappingError(400, "meta_field_name es obligatorio.")
    target_key_clean = _validate_mapping(target_type=target_type, target_key=target_key)

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO crm.form_field_mappings
                    (provider, form_id, meta_field_name, target_type, target_key,
                     created_by, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (provider, form_id, meta_field_name) DO UPDATE SET
                    target_type = EXCLUDED.target_type,
                    target_key  = EXCLUDED.target_key,
                    updated_at  = NOW()
                RETURNING id, provider, form_id, meta_field_name, target_type, target_key,
                          created_at, updated_at
                """,
                (provider, form_id, name, target_type, target_key_clean, created_by),
            )
            row = cur.fetchone()
        conn.commit()
    logger.info("field_mappings: upsert mapping %s/%s/%s → %s:%s by %s",
                provider, form_id, name, target_type, target_key_clean or "-",
                created_by or "?")
    return _row_to_mapping(row)


def delete_form_field_mapping(mapping_id: int) -> bool:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM crm.form_field_mappings WHERE id = %s",
                (mapping_id,),
            )
            deleted = cur.rowcount > 0
        conn.commit()
    return deleted


# ─────────────────────────────────────────────────────────────────────────────
# Detección de campos sin mapear
# ─────────────────────────────────────────────────────────────────────────────

def detect_unmapped_fields(
    provider: str = "meta",
    days_back: int = 90,
    limit: int = 200,
) -> list[dict]:
    """Lista campos de `lead_interacciones_meta.raw_field_data` que:

      - No son campos nativos (phone/email/name…).
      - No tienen mapping en `form_field_mappings` (ni exacto ni wildcard).

    Devuelve [{form_id, form_nombre, meta_field_name, sample_value,
               submit_count, last_seen}], ordenado por submit_count DESC.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                WITH
                field_items AS (
                    SELECT
                        i.form_id,
                        LOWER(item->>'name') AS meta_field_name,
                        (item->'values'->>0) AS sample_value,
                        i.fecha_interaccion
                      FROM crm.lead_interacciones_meta i
                      CROSS JOIN LATERAL jsonb_array_elements(
                          COALESCE(i.raw_field_data, '[]'::jsonb)
                      ) AS item
                     WHERE i.fecha_interaccion >= NOW() - (%s || ' days')::interval
                       AND i.form_id IS NOT NULL
                       AND item ? 'name'
                ),
                mapped AS (
                    SELECT provider, form_id, meta_field_name
                      FROM crm.form_field_mappings
                     WHERE provider = %s
                )
                SELECT
                    f.form_id,
                    mc.name AS form_nombre,
                    f.meta_field_name,
                    MAX(f.sample_value) AS sample_value,
                    COUNT(*) AS submit_count,
                    MAX(f.fecha_interaccion) AS last_seen
                  FROM field_items f
                  LEFT JOIN crm.meta_catalog_cache mc
                    ON mc.entity_type = 'form'
                   AND mc.entity_id   = f.form_id
                   AND mc.fetch_status = 'ok'
                 WHERE f.meta_field_name NOT IN %s
                   AND NOT EXISTS (
                       SELECT 1 FROM mapped m
                        WHERE m.provider = %s
                          AND (m.form_id = f.form_id OR m.form_id = '_any_')
                          AND m.meta_field_name = f.meta_field_name
                   )
                 GROUP BY f.form_id, mc.name, f.meta_field_name
                 ORDER BY submit_count DESC, last_seen DESC
                 LIMIT %s
                """,
                (
                    str(days_back),
                    provider,
                    tuple(_WELL_KNOWN_NATIVE_FIELDS),
                    provider,
                    limit,
                ),
            )
            return [dict(r) for r in cur.fetchall()]


# ─────────────────────────────────────────────────────────────────────────────
# Aplicación: raw_field_data + form_id + lead_id → escrituras
# ─────────────────────────────────────────────────────────────────────────────

def _load_mappings_for_form(
    cur,
    provider: str,
    form_id: Optional[str],
) -> dict[str, dict]:
    """Devuelve {meta_field_name_lc: {target_type, target_key}} para ese form.

    Incluye wildcards `form_id = '_any_'`. Si un campo tiene regla específica
    y una wildcard, gana la específica.
    """
    form_ids: list[str] = ["_any_"]
    if form_id:
        form_ids.insert(0, form_id)
    cur.execute(
        """
        SELECT form_id, meta_field_name, target_type, target_key
          FROM crm.form_field_mappings
         WHERE provider = %s
           AND form_id = ANY(%s)
        """,
        (provider, form_ids),
    )
    rows = cur.fetchall()

    # form_id específico gana sobre '_any_'.
    by_key: dict[str, dict] = {}
    for r in rows:
        name = r["meta_field_name"]
        if name not in by_key or (form_id and r["form_id"] == form_id):
            by_key[name] = {
                "target_type": r["target_type"],
                "target_key":  r.get("target_key"),
            }
    return by_key


def _upsert_lead_property(cur, lead_id: int, property_key: str, value: str) -> None:
    cur.execute(
        """
        INSERT INTO crm.lead_properties (lead_id, property_key, property_value, updated_at)
        VALUES (%s, %s, %s, NOW())
        ON CONFLICT (lead_id, property_key) DO UPDATE SET
            property_value = EXCLUDED.property_value,
            updated_at     = NOW()
        """,
        (lead_id, property_key, value),
    )


def _update_lead_column_if_empty(cur, lead_id: int, column: str, value: str) -> None:
    # La whitelist ya validó el nombre. Aun así, defensa en profundidad: solo
    # aceptamos identificadores simples.
    if column not in ALLOWED_COLUMN_TARGETS:
        return
    # Para `observaciones`, concatenamos si ya tiene contenido — el primer
    # submit escribe, los siguientes añaden "clave: valor" separado por " | ".
    if column == "observaciones":
        cur.execute(
            """
            UPDATE crm.leads
               SET observaciones = CASE
                        WHEN observaciones IS NULL OR observaciones = ''
                             THEN %s
                        WHEN position(%s IN observaciones) > 0
                             THEN observaciones
                        ELSE observaciones || ' | ' || %s
                   END
             WHERE id = %s
            """,
            (value, value, value, lead_id),
        )
        return
    cur.execute(
        f"""
        UPDATE crm.leads
           SET {column} = %s
         WHERE id = %s
           AND ({column} IS NULL OR {column} = '')
        """,
        (value, lead_id),
    )


def apply_mappings(
    cur,
    *,
    lead_id: int,
    provider: str,
    form_id: Optional[str],
    raw_field_data: Iterable[dict],
) -> dict:
    """Aplica todos los mappings resolubles a `raw_field_data` sobre el lead.

    Devuelve {applied: N, ignored: N, unmapped: N, errors: N}. Nunca levanta
    — cualquier error se loggea y se cuenta en `errors`.
    """
    stats = {"applied": 0, "ignored": 0, "unmapped": 0, "errors": 0}
    if not lead_id or not raw_field_data:
        return stats

    try:
        mappings = _load_mappings_for_form(cur, provider, form_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("field_mappings: no se pudieron cargar reglas para %s/%s: %s",
                       provider, form_id, exc)
        return stats

    for entry in raw_field_data:
        if not isinstance(entry, dict):
            continue
        raw_name = entry.get("name")
        if not raw_name:
            continue
        name = str(raw_name).strip().lower()
        values = entry.get("values") or []
        value = str(values[0]).strip() if values and values[0] is not None else ""
        if not value:
            continue

        rule = mappings.get(name)
        if not rule:
            # No hay regla — sigue cayendo en `observaciones` vía el flujo
            # normal de normalize_field_data. Solo llevamos el contador.
            stats["unmapped"] += 1
            continue

        tt = rule["target_type"]
        tk = rule.get("target_key")
        try:
            if tt == "ignore":
                stats["ignored"] += 1
            elif tt == "column":
                _update_lead_column_if_empty(cur, lead_id, tk, value)
                stats["applied"] += 1
            elif tt == "property":
                _upsert_lead_property(cur, lead_id, tk, value)
                stats["applied"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "field_mappings: fallo aplicando regla %s/%s=%s → %s:%s (lead=%s): %s",
                provider, form_id, name, tt, tk, lead_id, exc,
            )
            stats["errors"] += 1

    return stats


# ─────────────────────────────────────────────────────────────────────────────
# Lectura de propiedades por lead (para UI de detalle)
# ─────────────────────────────────────────────────────────────────────────────

# Advisory lock key para serializar backfills entre workers. Estable.
_BACKFILL_ADVISORY_LOCK_KEY = 0x4246494C4C4D4150  # "BFILLMAP"

# Cuántas interacciones procesamos entre commits — balance entre:
#   - mantener tx cortas (no bloquear lead_properties/leads mucho tiempo)
#   - amortizar costo de round-trips.
_BACKFILL_BATCH_SIZE = 200


def acquire_backfill_lock(cur) -> bool:
    """Intenta adquirir el advisory lock de backfill sin bloquear.

    Devuelve True si lo tomó, False si otro worker ya está corriendo uno.
    El lock se libera al commit/rollback (scope transaccional).
    """
    cur.execute("SELECT pg_try_advisory_xact_lock(%s)",
                (_BACKFILL_ADVISORY_LOCK_KEY,))
    row = cur.fetchone()
    if row is None:
        return False
    # RealDictCursor devuelve dict; cursor normal tupla.
    return bool(list(row.values())[0] if isinstance(row, dict) else row[0])


def backfill_mappings(
    *,
    provider: str = "meta",
    days_back: int = 180,
    limit: int = 5000,
    batch_size: int = _BACKFILL_BATCH_SIZE,
    progress_cb=None,
) -> dict:
    """Reprocesa interacciones existentes para poblar lead_properties y
    columnas bajo las reglas actuales. Idempotente.

    Usa commits por lotes para no mantener una transacción larga que
    bloquee ingestas concurrentes. `progress_cb(totals)` se invoca tras
    cada batch para reportar avance.

    Procesa en orden cronológico ascendente — el primer submit gana si el
    mismo lead tiene múltiples (mismo criterio que la ingesta).
    """
    totals = {
        "interactions_seen": 0,
        "leads_touched": 0,
        "applied": 0,
        "ignored": 0,
        "unmapped": 0,
        "errors": 0,
    }
    touched_leads: set[int] = set()

    with get_db() as conn:
        # 1) Leer ids de interacciones a procesar en una tx breve.
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, lead_id, form_id, raw_field_data
                  FROM crm.lead_interacciones_meta
                 WHERE fecha_interaccion >= NOW() - (%s || ' days')::interval
                   AND lead_id IS NOT NULL
                   AND raw_field_data IS NOT NULL
                 ORDER BY fecha_interaccion ASC
                 LIMIT %s
                """,
                (str(days_back), limit),
            )
            rows = cur.fetchall()
        conn.commit()  # cierra la tx de lectura

        # 2) Procesar en batches, commit cada batch.
        for offset in range(0, len(rows), batch_size):
            batch = rows[offset:offset + batch_size]
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    for row in batch:
                        totals["interactions_seen"] += 1
                        lead_id = row["lead_id"]
                        form_id = row.get("form_id")
                        raw = row.get("raw_field_data") or []
                        if not isinstance(raw, list):
                            continue
                        stats = apply_mappings(
                            cur,
                            lead_id=lead_id,
                            provider=provider,
                            form_id=form_id,
                            raw_field_data=raw,
                        )
                        totals["applied"]  += stats["applied"]
                        totals["ignored"]  += stats["ignored"]
                        totals["unmapped"] += stats["unmapped"]
                        totals["errors"]   += stats["errors"]
                        if stats["applied"] or stats["ignored"]:
                            touched_leads.add(lead_id)
                conn.commit()
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                logger.warning(
                    "backfill: fallo en batch offset=%d size=%d: %s",
                    offset, len(batch), exc,
                )
                totals["errors"] += len(batch)

            totals["leads_touched"] = len(touched_leads)
            if progress_cb is not None:
                try:
                    progress_cb(totals)
                except Exception:  # noqa: BLE001
                    pass

    totals["leads_touched"] = len(touched_leads)
    return totals


# ─────────────────────────────────────────────────────────────────────────────
# Jobs de backfill — persistencia en crm.field_mappings_backfill_jobs
# ─────────────────────────────────────────────────────────────────────────────

def create_backfill_job(triggered_by: str, params: dict) -> str:
    """Crea una fila de job en status='pending'. Devuelve job_id (uuid str)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO crm.field_mappings_backfill_jobs
                    (triggered_by, status, params)
                VALUES (%s, 'pending', %s)
                RETURNING job_id
                """,
                (triggered_by, Json(params)),
            )
            job_id = str(cur.fetchone()[0])
        conn.commit()
    return job_id


def update_backfill_job(
    job_id: str,
    *,
    status: Optional[str] = None,
    totals: Optional[dict] = None,
    error: Optional[str] = None,
    started: bool = False,
    completed: bool = False,
) -> None:
    sets = []
    params: list = []
    if status is not None:
        sets.append("status = %s")
        params.append(status)
    if totals is not None:
        sets.append("totals = %s")
        params.append(Json(totals))
    if error is not None:
        sets.append("error = %s")
        params.append(error)
    if started:
        sets.append("started_at = COALESCE(started_at, NOW())")
    if completed:
        sets.append("completed_at = NOW()")
    if not sets:
        return
    params.append(job_id)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE crm.field_mappings_backfill_jobs "
                f"SET {', '.join(sets)} WHERE job_id = %s::uuid",
                params,
            )
        conn.commit()


def list_recent_backfill_jobs(limit: int = 10) -> list[dict]:
    """Lista los N jobs más recientes (audit trail ligero)."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT job_id::text, triggered_by, status, params, totals,
                       error, created_at, started_at, completed_at
                  FROM crm.field_mappings_backfill_jobs
                 ORDER BY created_at DESC
                 LIMIT %s
                """,
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]


def get_backfill_job(job_id: str) -> Optional[dict]:
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT job_id::text, triggered_by, status, params, totals,
                       error, created_at, started_at, completed_at
                  FROM crm.field_mappings_backfill_jobs
                 WHERE job_id = %s::uuid
                """,
                (job_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def run_backfill_job(job_id: str, params: dict) -> None:
    """Ejecuta un job ya creado: adquiere advisory lock, corre backfill,
    actualiza estado final. Nunca levanta (se loggea en job.error).
    """
    update_backfill_job(job_id, status="running", started=True)
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                if not acquire_backfill_lock(cur):
                    conn.commit()
                    update_backfill_job(
                        job_id,
                        status="rejected",
                        error="Otro backfill ya está corriendo.",
                        completed=True,
                    )
                    return
            # lock se libera al salir del with (transaction-scoped)

        def _on_progress(t: dict) -> None:
            update_backfill_job(job_id, totals=dict(t))

        totals = backfill_mappings(
            provider=params.get("provider", "meta"),
            days_back=int(params.get("days_back", 180)),
            limit=int(params.get("limit", 5000)),
            progress_cb=_on_progress,
        )
        update_backfill_job(
            job_id, status="completed", totals=totals, completed=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("backfill_job %s: error no capturado", job_id)
        update_backfill_job(
            job_id, status="failed", error=str(exc)[:2000], completed=True,
        )


def get_properties_for_lead(lead_id: int) -> list[dict]:
    """Lista propiedades custom de un lead con su definición (display_name, type)."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT lp.property_key,
                       lp.property_value,
                       lp.updated_at,
                       pd.display_name,
                       pd.property_type,
                       pd.category,
                       pd.icon
                  FROM crm.lead_properties lp
                  LEFT JOIN crm.property_definitions pd
                    ON pd.property_key = lp.property_key
                 WHERE lp.lead_id = %s
                   AND COALESCE(pd.is_active, TRUE) = TRUE
                 ORDER BY COALESCE(pd.category, ''), pd.display_name, lp.property_key
                """,
                (lead_id,),
            )
            return [dict(r) for r in cur.fetchall()]
