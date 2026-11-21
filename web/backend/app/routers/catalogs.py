"""
Catálogos públicos (requieren auth) para poblar selects del frontend.
- GET    /api/estados       — estados del pipeline
- PATCH  /api/estados/:id   — actualizar estado (admin)
- POST   /api/estados        — crear estado (admin)
- DELETE /api/estados/:id   — eliminar estado (admin)
- GET    /api/fuentes       — fuentes de leads
"""
from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel
from typing import Optional, List
from app.auth.jwt import get_current_user, require_admin
from app.auth.schemas import TokenData
from app.database import get_db
from app.sql_utils import safe_set_clause

router = APIRouter(prefix="/api", tags=["Catálogos"])


# Payload generico para todos los endpoints /reorder (estados, fuentes,
# campanas, calidad, tipos-contacto, ...). Se define al tope del modulo
# para evitar referencias forward-declared.
class ReorderRequest(BaseModel):
    ids: List[int]


@router.get("/estados")
def get_estados(current_user: TokenData = Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, nombre, color_hex, es_final, orden "
                "FROM crm.estados_lead ORDER BY orden"
            )
            return cur.fetchall()


@router.post("/estados/reorder", status_code=200)
def reorder_estados(data: ReorderRequest, admin: TokenData = Depends(require_admin)):
    """Actualiza el orden de los estados segun la lista de IDs recibida.

    crm.estados_lead.orden tiene UNIQUE constraint, asi que un UPDATE
    iterativo violaria la constraint a mitad de camino (dos rows con el
    mismo orden temporal). Solucion clasica: dos pasadas en una sola
    transaccion:
      1. Shift +10000 a todas las filas participantes para liberar los
         slots 1..N. Mantiene unicidad porque los offset son distintos.
      2. Asigna 1..N en el orden recibido sin conflicto.
    """
    if not data.ids:
        return {"message": "Sin cambios"}
    with get_db() as conn:
        with conn.cursor() as cur:
            # Pass 1: librerar los slots 1..N moviendo a +10000
            cur.execute(
                "UPDATE crm.estados_lead SET orden = orden + 10000 WHERE id = ANY(%s)",
                (data.ids,),
            )
            # Pass 2: asignar el orden final
            for i, item_id in enumerate(data.ids):
                cur.execute(
                    "UPDATE crm.estados_lead SET orden = %s WHERE id = %s",
                    (i + 1, item_id),
                )
        conn.commit()
    return {"message": "Orden actualizado"}


class EstadoUpdate(BaseModel):
    nombre:    Optional[str] = None
    color_hex: Optional[str] = None
    es_final:  Optional[bool] = None
    orden:     Optional[int] = None


class EstadoCreate(BaseModel):
    nombre:    str
    color_hex: str = "#6b7280"
    es_final:  bool = False


@router.patch("/estados/{estado_id}")
def update_estado(estado_id: int, data: EstadoUpdate, admin: TokenData = Depends(require_admin)):
    fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="Sin campos a actualizar")

    _ESTADO_COLUMNS = {"nombre", "color_hex", "es_final", "orden"}
    set_clause, set_params = safe_set_clause(fields, _ESTADO_COLUMNS)
    params = set_params + [estado_id]

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"UPDATE crm.estados_lead SET {set_clause} WHERE id = %s RETURNING id, nombre, color_hex, es_final, orden",
                params,
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Estado no encontrado")
        conn.commit()
    return row


@router.post("/estados", status_code=201)
def create_estado(data: EstadoCreate, admin: TokenData = Depends(require_admin)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT COALESCE(MAX(orden), 0) + 1 AS next_orden FROM crm.estados_lead")
            next_orden = cur.fetchone()["next_orden"]
            cur.execute(
                "INSERT INTO crm.estados_lead (nombre, color_hex, es_final, orden) "
                "VALUES (%s, %s, %s, %s) RETURNING id, nombre, color_hex, es_final, orden",
                (data.nombre, data.color_hex, data.es_final, next_orden),
            )
            row = cur.fetchone()
        conn.commit()
    return row


@router.delete("/estados/{estado_id}", status_code=200)
def delete_estado(estado_id: int, admin: TokenData = Depends(require_admin)):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM crm.leads WHERE estado_id = %s", (estado_id,))
            count = cur.fetchone()[0]
            if count > 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"No se puede eliminar: {count} leads usan este estado"
                )
            cur.execute("DELETE FROM crm.estados_lead WHERE id = %s RETURNING id", (estado_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Estado no encontrado")
        conn.commit()
    return {"message": "Estado eliminado"}


# ╔═══════════════════════════════════════════════════════════════════════╗
# ║ V042 — Estados de cita (Pendiente, Completada, Reprogramada, ...)    ║
# ║ Catalogo configurable. Mismo patron que estados_lead.                ║
# ╚═══════════════════════════════════════════════════════════════════════╝

@router.get("/cita-estados")
def get_cita_estados(current_user: TokenData = Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, codigo, nombre, color_hex, es_final, orden "
                "FROM crm.cita_estados WHERE activo = TRUE ORDER BY orden"
            )
            return cur.fetchall()


@router.post("/cita-estados/reorder", status_code=200)
def reorder_cita_estados(data: ReorderRequest, admin: TokenData = Depends(require_admin)):
    """Reordenar con two-pass para no violar UNIQUE(orden). Mismo patron
    que /estados/reorder."""
    if not data.ids:
        return {"message": "Sin cambios"}
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE crm.cita_estados SET orden = orden + 10000 WHERE id = ANY(%s)",
                (data.ids,),
            )
            for i, item_id in enumerate(data.ids):
                cur.execute(
                    "UPDATE crm.cita_estados SET orden = %s WHERE id = %s",
                    (i + 1, item_id),
                )
        conn.commit()
    return {"message": "Orden actualizado"}


class CitaEstadoCreate(BaseModel):
    nombre:    str
    color_hex: str = "#6B7280"
    es_final:  bool = False


class CitaEstadoUpdate(BaseModel):
    nombre:    Optional[str] = None
    color_hex: Optional[str] = None
    es_final:  Optional[bool] = None


def _slugify(s: str) -> str:
    """codigo estable para inserts: lowercase + sin acentos + _ por espacio."""
    import unicodedata
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')
    return ''.join(c if c.isalnum() else '_' for c in s.lower()).strip('_') or 'estado'


@router.post("/cita-estados", status_code=201)
def create_cita_estado(data: CitaEstadoCreate, admin: TokenData = Depends(require_admin)):
    codigo = _slugify(data.nombre)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT COALESCE(MAX(orden), 0) + 1 AS next_orden FROM crm.cita_estados")
            next_orden = cur.fetchone()["next_orden"]
            cur.execute(
                "INSERT INTO crm.cita_estados (codigo, nombre, color_hex, es_final, orden) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (codigo) DO UPDATE SET activo = TRUE "
                "RETURNING id, codigo, nombre, color_hex, es_final, orden",
                (codigo, data.nombre.strip(), data.color_hex, data.es_final, next_orden),
            )
            row = cur.fetchone()
        conn.commit()
    return row


@router.patch("/cita-estados/{estado_id}")
def update_cita_estado(estado_id: int, data: CitaEstadoUpdate, admin: TokenData = Depends(require_admin)):
    fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="Sin campos a actualizar")
    set_clause, params = safe_set_clause(
        fields, {"nombre", "color_hex", "es_final"}
    )
    params = params + [estado_id]
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"UPDATE crm.cita_estados SET {set_clause} WHERE id = %s "
                "RETURNING id, codigo, nombre, color_hex, es_final, orden",
                params,
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Estado no encontrado")
        conn.commit()
    return row


@router.delete("/cita-estados/{estado_id}", status_code=200)
def delete_cita_estado(estado_id: int, admin: TokenData = Depends(require_admin)):
    """Soft-delete: marca activo=FALSE en lugar de borrar (preserva historial
    de citas que apuntan a este estado)."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE crm.cita_estados SET activo = FALSE WHERE id = %s RETURNING id",
                (estado_id,),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Estado no encontrado")
        conn.commit()
    return {"message": "Estado desactivado"}


_CREATE_CONTACTO_CATALOGS_SQL = """
CREATE TABLE IF NOT EXISTS crm.tipos_contacto (
    id      SERIAL PRIMARY KEY,
    nombre  TEXT NOT NULL UNIQUE,
    icono   TEXT DEFAULT '📋',
    activo  BOOLEAN DEFAULT TRUE,
    orden   INT DEFAULT 0
);
INSERT INTO crm.tipos_contacto (nombre, icono, orden) VALUES
    ('Llamada',    '📞', 1),
    ('WhatsApp',   '💬', 2),
    ('Email',      '✉️', 3),
    ('Presencial', '👥', 4),
    ('Nota',       '📝', 5)
ON CONFLICT (nombre) DO NOTHING;

CREATE TABLE IF NOT EXISTS crm.tipos_cita (
    id      SERIAL PRIMARY KEY,
    nombre  TEXT NOT NULL UNIQUE,
    icono   TEXT DEFAULT '📋',
    activo  BOOLEAN DEFAULT TRUE,
    orden   INT DEFAULT 0
);
INSERT INTO crm.tipos_cita (nombre, icono, orden) VALUES
    ('Cita oficina Bustamante', '🏢', 1),
    ('Cita oficina Umacollo',   '🏢', 2),
    ('Cita Exteriores',         '🚗', 3),
    ('Cita Virtual',            '💻', 4)
ON CONFLICT (nombre) DO NOTHING;

CREATE TABLE IF NOT EXISTS crm.resultados_contacto (
    id      SERIAL PRIMARY KEY,
    nombre  TEXT NOT NULL UNIQUE,
    activo  BOOLEAN DEFAULT TRUE,
    orden   INT DEFAULT 0
);
INSERT INTO crm.resultados_contacto (nombre, orden) VALUES
    ('contesto',1),('no_contesto',2),('buzon',3),
    ('cita_agendada',4),('no_interesado',5),('volver_llamar',6)
ON CONFLICT (nombre) DO NOTHING;
"""


@router.get("/tipos-contacto")
def get_tipos_contacto(current_user: TokenData = Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(_CREATE_CONTACTO_CATALOGS_SQL)
            cur.execute("SELECT id, nombre, icono FROM crm.tipos_contacto WHERE activo=TRUE ORDER BY orden")
            return cur.fetchall()


@router.get("/tipos-cita")
def get_tipos_cita(current_user: TokenData = Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(_CREATE_CONTACTO_CATALOGS_SQL)
            cur.execute("SELECT id, nombre, icono FROM crm.tipos_cita WHERE activo=TRUE ORDER BY orden")
            return cur.fetchall()


@router.get("/resultados-contacto")
def get_resultados_contacto(current_user: TokenData = Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(_CREATE_CONTACTO_CATALOGS_SQL)
            cur.execute("SELECT id, nombre FROM crm.resultados_contacto WHERE activo=TRUE ORDER BY orden")
            return cur.fetchall()


class CatalogoItem(BaseModel):
    nombre: str
    icono: Optional[str] = '📋'


class CatalogoUpdate(BaseModel):
    nombre: Optional[str] = None
    icono: Optional[str] = None


@router.post("/tipos-contacto/reorder", status_code=200)
def reorder_tipos_contacto(data: ReorderRequest, admin: TokenData = Depends(require_admin)):
    """Actualiza el orden de los tipos de contacto según la lista de IDs recibida."""
    with get_db() as conn:
        with conn.cursor() as cur:
            for i, item_id in enumerate(data.ids):
                cur.execute(
                    "UPDATE crm.tipos_contacto SET orden = %s WHERE id = %s",
                    (i + 1, item_id),
                )
        conn.commit()
    return {"message": "Orden actualizado"}


@router.post("/tipos-cita/reorder", status_code=200)
def reorder_tipos_cita(data: ReorderRequest, admin: TokenData = Depends(require_admin)):
    """Actualiza el orden de los tipos de cita según la lista de IDs recibida."""
    with get_db() as conn:
        with conn.cursor() as cur:
            for i, item_id in enumerate(data.ids):
                cur.execute(
                    "UPDATE crm.tipos_cita SET orden = %s WHERE id = %s",
                    (i + 1, item_id),
                )
        conn.commit()
    return {"message": "Orden actualizado"}


@router.post("/resultados-contacto/reorder", status_code=200)
def reorder_resultados_contacto(data: ReorderRequest, admin: TokenData = Depends(require_admin)):
    """Actualiza el orden de los resultados de contacto según la lista de IDs recibida."""
    with get_db() as conn:
        with conn.cursor() as cur:
            for i, item_id in enumerate(data.ids):
                cur.execute(
                    "UPDATE crm.resultados_contacto SET orden = %s WHERE id = %s",
                    (i + 1, item_id),
                )
        conn.commit()
    return {"message": "Orden actualizado"}


@router.post("/tipos-contacto", status_code=201)
def create_tipo_contacto(data: CatalogoItem, admin: TokenData = Depends(require_admin)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT COALESCE(MAX(orden),0)+1 AS next_orden FROM crm.tipos_contacto")
            orden = cur.fetchone()["next_orden"]
            cur.execute(
                "INSERT INTO crm.tipos_contacto (nombre, icono, orden) VALUES (%s,%s,%s) "
                "ON CONFLICT (nombre) DO UPDATE SET activo=TRUE, icono=EXCLUDED.icono RETURNING id, nombre, icono",
                (data.nombre, data.icono or '📋', orden),
            )
            row = cur.fetchone()
        conn.commit()
    return row


@router.patch("/tipos-contacto/{item_id}", status_code=200)
def update_tipo_contacto(item_id: int, data: CatalogoUpdate, admin: TokenData = Depends(require_admin)):
    fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="Sin campos a actualizar")
    _TIPO_COLUMNS = {"nombre", "icono"}
    set_clause, set_params = safe_set_clause(fields, _TIPO_COLUMNS)
    params = set_params + [item_id]
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"UPDATE crm.tipos_contacto SET {set_clause} WHERE id = %s AND activo = TRUE RETURNING id, nombre, icono",
                params,
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Tipo no encontrado")
        conn.commit()
    return row


@router.delete("/tipos-contacto/{item_id}", status_code=200)
def delete_tipo_contacto(item_id: int, admin: TokenData = Depends(require_admin)):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE crm.tipos_contacto SET activo=FALSE WHERE id=%s RETURNING id", (item_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Tipo no encontrado")
        conn.commit()
    return {"message": "Tipo desactivado"}


@router.post("/tipos-cita", status_code=201)
def create_tipo_cita(data: CatalogoItem, admin: TokenData = Depends(require_admin)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT COALESCE(MAX(orden),0)+1 AS next_orden FROM crm.tipos_cita")
            orden = cur.fetchone()["next_orden"]
            cur.execute(
                "INSERT INTO crm.tipos_cita (nombre, icono, orden) VALUES (%s,%s,%s) "
                "ON CONFLICT (nombre) DO UPDATE SET activo=TRUE, icono=EXCLUDED.icono RETURNING id, nombre, icono",
                (data.nombre, data.icono or '📋', orden),
            )
            row = cur.fetchone()
        conn.commit()
    return row


@router.patch("/tipos-cita/{item_id}", status_code=200)
def update_tipo_cita(item_id: int, data: CatalogoUpdate, admin: TokenData = Depends(require_admin)):
    fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="Sin campos a actualizar")
    _TIPO_COLUMNS = {"nombre", "icono"}
    set_clause, set_params = safe_set_clause(fields, _TIPO_COLUMNS)
    params = set_params + [item_id]
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"UPDATE crm.tipos_cita SET {set_clause} WHERE id = %s AND activo = TRUE RETURNING id, nombre, icono",
                params,
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Tipo no encontrado")
        conn.commit()
    return row


@router.delete("/tipos-cita/{item_id}", status_code=200)
def delete_tipo_cita(item_id: int, admin: TokenData = Depends(require_admin)):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE crm.tipos_cita SET activo=FALSE WHERE id=%s RETURNING id", (item_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Tipo no encontrado")
        conn.commit()
    return {"message": "Tipo desactivado"}


@router.post("/resultados-contacto", status_code=201)
def create_resultado_contacto(data: CatalogoItem, admin: TokenData = Depends(require_admin)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT COALESCE(MAX(orden),0)+1 AS next_orden FROM crm.resultados_contacto")
            orden = cur.fetchone()["next_orden"]
            cur.execute(
                "INSERT INTO crm.resultados_contacto (nombre, orden) VALUES (%s,%s) "
                "ON CONFLICT (nombre) DO UPDATE SET activo=TRUE RETURNING id, nombre",
                (data.nombre, orden),
            )
            row = cur.fetchone()
        conn.commit()
    return row


@router.patch("/resultados-contacto/{item_id}", status_code=200)
def update_resultado_contacto(item_id: int, data: CatalogoUpdate, admin: TokenData = Depends(require_admin)):
    fields = {k: v for k, v in data.model_dump().items() if v is not None and k != 'icono'}
    if not fields:
        raise HTTPException(status_code=400, detail="Sin campos a actualizar")
    _RESULTADO_COLUMNS = {"nombre"}
    set_clause, set_params = safe_set_clause(fields, _RESULTADO_COLUMNS)
    params = set_params + [item_id]
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"UPDATE crm.resultados_contacto SET {set_clause} WHERE id = %s AND activo = TRUE RETURNING id, nombre",
                params,
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Resultado no encontrado")
        conn.commit()
    return row


@router.delete("/resultados-contacto/{item_id}", status_code=200)
def delete_resultado_contacto(item_id: int, admin: TokenData = Depends(require_admin)):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE crm.resultados_contacto SET activo=FALSE WHERE id=%s RETURNING id", (item_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Resultado no encontrado")
        conn.commit()
    return {"message": "Resultado desactivado"}


# ── Calidad (temperatura del lead) ──────────────────────────────────────────
# V028: catálogo configurable. Antes era un CHECK constraint hardcoded en DB.
# El `codigo` es UPPER y se persiste directamente en `crm.leads.calidad`.

import re
import unicodedata

_CALIDAD_CODIGO_RE = re.compile(r"^[A-Z0-9_]{1,40}$")


def _slugify_codigo(raw: str) -> str:
    """Normaliza un string a formato de código interno: sin tildes, UPPER,
    símbolos y espacios → _, truncado a 40 chars. Mismo algoritmo que la UI."""
    if not raw:
        return ""
    s = unicodedata.normalize("NFD", raw)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.upper()
    s = re.sub(r"[^A-Z0-9]+", "_", s)
    s = s.strip("_")
    return s[:40]


def _validate_codigo(raw: str) -> str:
    """Devuelve el código normalizado o levanta 400. Blinda la API contra
    callers que no pasan por la UI (curl, webhooks, scripts)."""
    codigo = _slugify_codigo((raw or "").strip())
    if not codigo or not _CALIDAD_CODIGO_RE.match(codigo):
        raise HTTPException(
            status_code=400,
            detail=(
                "El código solo admite letras, números y guiones bajos "
                "(1 a 40 caracteres). Ej: MUY_CALIENTE"
            ),
        )
    return codigo


def _load_calidad_codigos_activos(cur) -> set[str]:
    """Helper compartido: devuelve el set de códigos activos (UPPER)
    para validar lead.calidad desde leads.py y carga_masiva.py sin duplicar SQL."""
    cur.execute("SELECT codigo FROM crm.catalogo_calidad WHERE activo = TRUE")
    return {r[0] for r in cur.fetchall()}


@router.get("/calidad")
def get_calidad(current_user: TokenData = Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, codigo, nombre, color_hex, orden, activo "
                "FROM crm.catalogo_calidad "
                "WHERE activo = TRUE "
                "ORDER BY orden, nombre"
            )
            return cur.fetchall()


class CalidadCreate(BaseModel):
    codigo:    str
    nombre:    str
    color_hex: str = "#64748b"


class CalidadUpdate(BaseModel):
    # `codigo` es inmutable por diseño (estilo CRMs profesionales picklist API name):
    # garantiza integridad de histórico y evita orfanatos en crm.leads.calidad.
    # Para "renombrar" un valor: crear uno nuevo y desactivar el viejo.
    nombre:    Optional[str] = None
    color_hex: Optional[str] = None
    orden:     Optional[int] = None
    activo:    Optional[bool] = None


@router.post("/calidad", status_code=201)
def create_calidad(data: CalidadCreate, admin: TokenData = Depends(require_admin)):
    codigo = _validate_codigo(data.codigo)
    nombre = (data.nombre or "").strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre visible es obligatorio")
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT COALESCE(MAX(orden), 0) + 1 AS next_orden FROM crm.catalogo_calidad")
            next_orden = cur.fetchone()["next_orden"]
            cur.execute(
                "INSERT INTO crm.catalogo_calidad (codigo, nombre, color_hex, orden) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (codigo) DO UPDATE "
                "    SET nombre = EXCLUDED.nombre, color_hex = EXCLUDED.color_hex, activo = TRUE "
                "RETURNING id, codigo, nombre, color_hex, orden, activo",
                (codigo, nombre, data.color_hex, next_orden),
            )
            row = cur.fetchone()
        conn.commit()
    return row


@router.patch("/calidad/{calidad_id}", status_code=200)
def update_calidad(calidad_id: int, data: CalidadUpdate, admin: TokenData = Depends(require_admin)):
    fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="Sin campos a actualizar")

    # codigo intencionalmente excluido: es inmutable tras la creación.
    _CALIDAD_COLUMNS = {"nombre", "color_hex", "orden", "activo"}
    set_clause, set_params = safe_set_clause(fields, _CALIDAD_COLUMNS)
    params = set_params + [calidad_id]

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"UPDATE crm.catalogo_calidad SET {set_clause}, updated_at = NOW() "
                f"WHERE id = %s RETURNING id, codigo, nombre, color_hex, orden, activo",
                params,
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Calidad no encontrada")
        conn.commit()
    return row


@router.post("/calidad/reorder", status_code=200)
def reorder_calidad(data: ReorderRequest, admin: TokenData = Depends(require_admin)):
    with get_db() as conn:
        with conn.cursor() as cur:
            for i, item_id in enumerate(data.ids):
                cur.execute(
                    "UPDATE crm.catalogo_calidad SET orden = %s, updated_at = NOW() WHERE id = %s",
                    (i + 1, item_id),
                )
        conn.commit()
    return {"message": "Orden actualizado"}


@router.delete("/calidad/{calidad_id}", status_code=200)
def delete_calidad(calidad_id: int, admin: TokenData = Depends(require_admin)):
    """Soft delete: marca como inactivo. Si hay leads usando el código
    avisamos al admin para que decida (reasignar primero, o dejar datos
    históricos con un código que ya no aparece en selects).

    El conteo de leads afectados es informativo: si la consulta falla
    (p.ej. la columna `calidad` aún no existe en este deploy) seguimos
    adelante con el soft-delete y devolvemos `leads_afectados=null`.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "UPDATE crm.catalogo_calidad SET activo = FALSE, updated_at = NOW() "
                "WHERE id = %s RETURNING codigo",
                (calidad_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Calidad no encontrada")
            codigo = row["codigo"]
        conn.commit()

        usados: Optional[int] = None
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT COUNT(*) AS n FROM crm.leads WHERE calidad = %s AND activo = TRUE",
                    (codigo,),
                )
                usados = cur.fetchone()["n"]
        except Exception:
            conn.rollback()  # libera la transacción abortada del cursor anterior

    return {"message": "Calidad desactivada", "leads_afectados": usados}


@router.get("/fuentes")
def get_fuentes(current_user: TokenData = Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, nombre FROM crm.fuentes WHERE activo = TRUE ORDER BY orden, nombre"
            )
            return cur.fetchall()


@router.post("/fuentes/reorder", status_code=200)
def reorder_fuentes(data: ReorderRequest, admin: TokenData = Depends(require_admin)):
    """Actualiza el orden de las fuentes según la lista de IDs recibida."""
    with get_db() as conn:
        with conn.cursor() as cur:
            for i, item_id in enumerate(data.ids):
                cur.execute(
                    "UPDATE crm.fuentes SET orden = %s WHERE id = %s",
                    (i + 1, item_id),
                )
        conn.commit()
    return {"message": "Orden actualizado"}


class FuenteCreate(BaseModel):
    nombre: str


class FuenteUpdate(BaseModel):
    nombre: Optional[str] = None


@router.post("/fuentes", status_code=201)
def create_fuente(data: FuenteCreate, admin: TokenData = Depends(require_admin)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO crm.fuentes (nombre) VALUES (%s) "
                "ON CONFLICT (nombre) DO UPDATE SET activo = TRUE RETURNING id, nombre",
                (data.nombre.strip(),),
            )
            row = cur.fetchone()
        conn.commit()
    return row


@router.patch("/fuentes/{fuente_id}", status_code=200)
def update_fuente(fuente_id: int, data: FuenteUpdate, admin: TokenData = Depends(require_admin)):
    if not data.nombre or not data.nombre.strip():
        raise HTTPException(status_code=400, detail="El nombre es obligatorio")
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "UPDATE crm.fuentes SET nombre = %s WHERE id = %s AND activo = TRUE RETURNING id, nombre",
                (data.nombre.strip(), fuente_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Fuente no encontrada")
        conn.commit()
    return row


@router.delete("/fuentes/{fuente_id}", status_code=200)
def delete_fuente(fuente_id: int, admin: TokenData = Depends(require_admin)):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE crm.fuentes SET activo = FALSE WHERE id = %s RETURNING id",
                (fuente_id,),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Fuente no encontrada")
        conn.commit()
    return {"message": "Fuente desactivada"}


# ── Campañas ────────────────────────────────────────────────────────────────

@router.get("/campanas")
def get_campanas(current_user: TokenData = Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, nombre FROM crm.campanas WHERE activo = TRUE ORDER BY orden, nombre"
            )
            return cur.fetchall()


@router.post("/campanas/reorder", status_code=200)
def reorder_campanas(data: ReorderRequest, admin: TokenData = Depends(require_admin)):
    with get_db() as conn:
        with conn.cursor() as cur:
            for i, item_id in enumerate(data.ids):
                cur.execute(
                    "UPDATE crm.campanas SET orden = %s WHERE id = %s",
                    (i + 1, item_id),
                )
        conn.commit()
    return {"message": "Orden actualizado"}


class CampanaCreate(BaseModel):
    nombre: str


class CampanaUpdate(BaseModel):
    nombre: Optional[str] = None


@router.post("/campanas", status_code=201)
def create_campana(data: CampanaCreate, admin: TokenData = Depends(require_admin)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO crm.campanas (nombre) VALUES (%s) "
                "ON CONFLICT (nombre) DO UPDATE SET activo = TRUE RETURNING id, nombre",
                (data.nombre.strip(),),
            )
            row = cur.fetchone()
        conn.commit()
    return row


@router.patch("/campanas/{campana_id}", status_code=200)
def update_campana(campana_id: int, data: CampanaUpdate, admin: TokenData = Depends(require_admin)):
    if not data.nombre or not data.nombre.strip():
        raise HTTPException(status_code=400, detail="El nombre es obligatorio")
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "UPDATE crm.campanas SET nombre = %s WHERE id = %s AND activo = TRUE RETURNING id, nombre",
                (data.nombre.strip(), campana_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Campaña no encontrada")
        conn.commit()
    return row


@router.delete("/campanas/{campana_id}", status_code=200)
def delete_campana(campana_id: int, admin: TokenData = Depends(require_admin)):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE crm.campanas SET activo = FALSE WHERE id = %s RETURNING id",
                (campana_id,),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Campaña no encontrada")
        conn.commit()
    return {"message": "Campaña desactivada"}


@router.get("/equipos")
def get_equipos(current_user: TokenData = Depends(get_current_user)):
    """Relación asesor → supervisor.
    - admin: ve todos los equipos.
    - supervisor: ve solo los asesores de su propio equipo.
    - asesor: ve solo su propia relación (si existe).
    """
    where = ["eq.activo = TRUE", "a.is_active = TRUE"]
    params: list = []
    if current_user.role == "supervisor":
        where.append(
            """(
                eq.supervisor_id = %s::uuid
                OR eq.supervisor_id IN (
                    SELECT s.id FROM auth.users s
                    WHERE s.supervisor_jefe_id = %s::uuid AND s.is_active = TRUE AND s.role = 'supervisor'
                )
            )"""
        )
        params.extend([current_user.user_id, current_user.user_id])
    elif current_user.role == "asesor":
        perms = current_user.permissions or {}
        scope = perms.get("asignacion.scope")
        if perms.get("asignacion.manage") and scope == "global":
            pass  # Asignación global ve todos los equipos
        elif perms.get("asignacion.manage") or perms.get("asignacion.scope"):
            # Asesor con asignación de equipo o personalizada ve el equipo al que pertenece
            where.append(
                """(
                    eq.asesor_id = %s::uuid
                    OR eq.supervisor_id IN (
                        SELECT eq_sub.supervisor_id FROM crm.equipos eq_sub
                        WHERE eq_sub.asesor_id = %s::uuid AND eq_sub.activo = TRUE
                    )
                )"""
            )
            params.extend([current_user.user_id, current_user.user_id])
        else:
            where.append("eq.asesor_id = %s::uuid")
            params.append(current_user.user_id)
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                    a.id::text          AS asesor_id,
                    TRIM(COALESCE(a.first_name,'') || ' ' || COALESCE(a.last_name,'')) AS asesor_nombre,
                    s.id::text          AS supervisor_id,
                    TRIM(COALESCE(s.first_name,'') || ' ' || COALESCE(s.last_name,'')) AS supervisor_nombre
                FROM crm.equipos eq
                JOIN auth.users a ON a.id = eq.asesor_id
                JOIN auth.users s ON s.id = eq.supervisor_id
                WHERE {' AND '.join(where)}
                ORDER BY supervisor_nombre, asesor_nombre
                """,
                params,
            )
            return cur.fetchall()


class EquipoCreate(BaseModel):
    supervisor_id: str
    asesor_id: str


@router.post("/equipos", status_code=201)
def add_to_equipo(data: EquipoCreate, admin: TokenData = Depends(require_admin)):
    """Asigna un asesor a un supervisor. Si ya tenía supervisor, lo cambia."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # V088 — Verificar que el asesor existe y está activo.
            cur.execute(
                "SELECT id FROM auth.users WHERE id = %s::uuid AND role IN ('asesor', 'supervisor') AND is_active = TRUE",
                (data.asesor_id,),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=400, detail="El asesor no existe o está deshabilitado")
            # V088 — Verificar que el supervisor existe y está activo.
            cur.execute(
                "SELECT id FROM auth.users WHERE id = %s::uuid AND role IN ('supervisor', 'admin', 'supervisor_jefe', 'subadmin') AND is_active = TRUE",
                (data.supervisor_id,),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=400, detail="El supervisor no existe o está deshabilitado")
            # Issue #57 — Calcular el proximo orden libre del supervisor.
            # Sin esto los asesores entran en orden=0 y el round-robin
            # secuencial cae a sort por user_id (UUID random), no por el
            # orden que el admin ve en la UI.
            cur.execute(
                """
                SELECT COALESCE(MAX(orden), 0) + 1 AS next_orden
                FROM crm.equipos
                WHERE supervisor_id = %s::uuid AND activo = TRUE
                """,
                (data.supervisor_id,),
            )
            next_orden = cur.fetchone()["next_orden"]

            # Upsert: si ya existe la relación la actualiza, si no la crea.
            # En el UPDATE solo recalculamos orden si el asesor cambia de
            # supervisor — si solo se reactiva en el mismo, preservamos el
            # orden que ya tenia (no perdemos su posicion en la jerarquia).
            cur.execute(
                """
                INSERT INTO crm.equipos (supervisor_id, asesor_id, orden)
                VALUES (%s::uuid, %s::uuid, %s)
                ON CONFLICT (asesor_id) DO UPDATE
                    SET supervisor_id = EXCLUDED.supervisor_id,
                        orden         = CASE
                            WHEN crm.equipos.supervisor_id = EXCLUDED.supervisor_id
                                THEN crm.equipos.orden
                            ELSE EXCLUDED.orden
                        END,
                        updated_at    = NOW()
                RETURNING id
                """,
                (data.supervisor_id, data.asesor_id, next_orden),
            )
            row = cur.fetchone()
        conn.commit()
    return {"id": row["id"], "message": "Asesor asignado al equipo"}


@router.delete("/equipos/{asesor_id}", status_code=200)
def remove_from_equipo(asesor_id: str, admin: TokenData = Depends(require_admin)):
    """Quita a un asesor de su equipo (deja sin supervisor).

    Tras borrar la fila, renumera el `orden` de los asesores restantes
    del mismo equipo para que la jerarquia de rotacion quede consecutiva
    (1, 2, 3, ...) sin huecos. Antes del fix: si el asesor borrado tenia
    orden=1, los restantes quedaban como 2, 3 — sin nadie en posicion 1.
    Reportado en producción 2026-06-17: tras quitar a Ana Montes (orden=1),
    Solanch (orden=2) y la siguiente (orden=3) seguian con esos numeros,
    confundiendo a los supervisores que esperaban ver 1 y 2.

    La renumeracion usa ROW_NUMBER() preservando el orden previo (orden
    actual, luego id como tiebreaker) y solo actualiza filas que cambian.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # 1) Borrar la fila y capturar el supervisor_id afectado.
            cur.execute(
                """
                DELETE FROM crm.equipos
                WHERE asesor_id = %s::uuid
                RETURNING id, supervisor_id::text
                """,
                (asesor_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(
                    status_code=404,
                    detail="El asesor no pertenece a ningún equipo",
                )
            supervisor_id = row[1]

            # 2) Renumerar orden consecutivo de los asesores restantes
            #    del mismo equipo. ROW_NUMBER() preserva el orden previo.
            #    El filtro `orden IS DISTINCT FROM new_orden` evita UPDATEs
            #    redundantes y mantiene `updated_at` solo donde aplica.
            cur.execute(
                """
                WITH renumbered AS (
                    SELECT id,
                           ROW_NUMBER() OVER (ORDER BY orden, id) AS new_orden
                    FROM crm.equipos
                    WHERE supervisor_id = %s::uuid
                )
                UPDATE crm.equipos eq
                SET orden = renumbered.new_orden,
                    updated_at = NOW()
                FROM renumbered
                WHERE eq.id = renumbered.id
                  AND eq.orden IS DISTINCT FROM renumbered.new_orden
                """,
                (supervisor_id,),
            )
        conn.commit()
    return {"message": "Asesor removido del equipo"}


class SupervisorJefeAssign(BaseModel):
    supervisor_id: str
    supervisor_jefe_id: Optional[str] = None


@router.post("/equipos/supervisor-jefe", status_code=200)
def assign_supervisor_jefe(data: SupervisorJefeAssign, admin: TokenData = Depends(require_admin)):
    """Asigna o remueve un Supervisor Jefe a un supervisor de equipo."""
    if data.supervisor_jefe_id and str(data.supervisor_id) == str(data.supervisor_jefe_id):
        raise HTTPException(status_code=400, detail="Un supervisor no puede ser su propio Supervisor Jefe")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Validar que supervisor_id exista y sea supervisor o admin
            cur.execute(
                "SELECT id FROM auth.users WHERE id = %s::uuid AND role IN ('supervisor', 'admin') AND is_active = TRUE",
                (data.supervisor_id,),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=400, detail="El supervisor no existe o está deshabilitado")

            if data.supervisor_jefe_id:
                # Validar supervisor_jefe_id exista y sea supervisor o admin
                cur.execute(
                    "SELECT id FROM auth.users WHERE id = %s::uuid AND role IN ('supervisor', 'admin') AND is_active = TRUE",
                    (data.supervisor_jefe_id,),
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=400, detail="El Supervisor Jefe no existe o no está activo")

            cur.execute(
                """
                UPDATE auth.users
                SET supervisor_jefe_id = %s::uuid
                WHERE id = %s::uuid
                """,
                (data.supervisor_jefe_id if data.supervisor_jefe_id else None, data.supervisor_id),
            )
        conn.commit()
    return {"ok": True, "message": "Jerarquía de supervisor actualizada correctamente"}

