"""
Agenda router — citas agendadas por mes + crear contacto (bypass cache).
- GET  /api/agenda/citas?mes=YYYY-MM   — citas del mes (rol-aware)
- POST /api/agenda/contacto/{lead_id}  — crear contacto (workaround deploy cache)
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel
from typing import Optional
from app.auth.jwt import get_current_user
from app.auth.permissions import can_view_all_data
from app.auth.schemas import TokenData
from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agenda", tags=["Agenda"])


# V042 — sin cache. Cada request consulta information_schema (~0.1ms,
# despreciable para un CRM de 15 usuarios). La razon: cualquier cache
# (lru, tri-state, etc) puede quedar en estados stuck post-migracion
# y dificil de invalidar sin restart manual. Para esta escala, un check
# directo es mas robusto y no agrega latencia perceptible.
def _has_cita_estado_column(_cur=None) -> bool:
    """¿Existe crm.contactos.cita_estado_id? Check directo, sin cache."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'crm'
                      AND table_name   = 'contactos'
                      AND column_name  = 'cita_estado_id'
                    LIMIT 1
                    """
                )
                return cur.fetchone() is not None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[cita_estados] schema check failed: %s", exc)
        return False


# ─── Webhook: ingreso automático de leads desde n8n/WhatsApp ───────────

class WebhookLeadIn(BaseModel):
    nombre: str
    telefono: Optional[str] = None
    fuente: str = "whatsapp"
    campana: Optional[str] = None
    email: Optional[str] = None
    ciudad: Optional[str] = None
    observaciones: Optional[str] = None


@router.post("/webhook-lead", status_code=201)
def webhook_lead(data: WebhookLeadIn):
    """
    Endpoint para n8n: crea lead y auto-asigna al supervisor con menos leads hoy.
    No requiere autenticación (llamado internamente desde n8n).
    """
    # Normalizar teléfono si viene
    telefono = None
    if data.telefono:
        telefono = ''.join(c for c in data.telefono if c.isdigit())
        if len(telefono) == 9:
            telefono = '51' + telefono
        elif not telefono:
            telefono = None

    # Normalizar nombre para dedup
    nombre_clean = data.nombre.strip() if data.nombre else ''

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # ── 1. Dedup: por teléfono o por nombre (WhatsApp sin teléfono) ──
            if telefono:
                cur.execute(
                    "SELECT id, asesor_id::text FROM crm.leads WHERE telefono = %s AND activo = TRUE LIMIT 1",
                    (telefono,),
                )
            else:
                cur.execute(
                    "SELECT id, asesor_id::text FROM crm.leads "
                    "WHERE TRIM(COALESCE(nombres,'') || ' ' || COALESCE(apellidos,'')) ILIKE %s "
                    "AND fuente_id = (SELECT id FROM crm.fuentes WHERE nombre = %s LIMIT 1) "
                    "AND activo = TRUE LIMIT 1",
                    (nombre_clean, data.fuente),
                )
            existing = cur.fetchone()
            if existing:
                return {
                    "action": "existing",
                    "lead_id": existing["id"],
                    "asesor_id": existing["asesor_id"],
                    "message": "Lead ya existe",
                }

            # ── 2. Buscar/crear fuente ──
            cur.execute(
                "SELECT id FROM crm.fuentes WHERE nombre = %s",
                (data.fuente,),
            )
            fuente_row = cur.fetchone()
            if fuente_row:
                fuente_id = fuente_row["id"]
            else:
                cur.execute(
                    "INSERT INTO crm.fuentes (nombre) VALUES (%s) RETURNING id",
                    (data.fuente,),
                )
                fuente_id = cur.fetchone()["id"]

            # ── 3. Round-robin diario entre supervisores ──
            # Cuenta leads asignados HOY a cada supervisor.
            # El que tiene menos hoy recibe el siguiente → distribución 1-1 diaria.
            cur.execute(
                """
                WITH sup_list AS (
                    SELECT DISTINCT e.supervisor_id
                    FROM crm.equipos e
                    JOIN auth.users u ON u.id = e.supervisor_id
                    WHERE e.activo = TRUE AND u.is_active = TRUE
                )
                SELECT s.supervisor_id::text,
                       COUNT(l.id) AS leads_hoy
                FROM sup_list s
                LEFT JOIN crm.leads l
                    ON l.asesor_id = s.supervisor_id
                    AND l.activo = TRUE
                    AND l.created_at::date = CURRENT_DATE
                GROUP BY s.supervisor_id
                ORDER BY leads_hoy ASC, s.supervisor_id ASC
                LIMIT 1
                """
            )
            sup_row = cur.fetchone()
            asesor_id = sup_row["supervisor_id"] if sup_row else None

            # ── 4. Crear el lead ──
            # Separar nombre en nombres + apellidos (primer espacio)
            partes = data.nombre.strip().split(' ', 1) if data.nombre else ['']
            nombres = partes[0]
            apellidos = partes[1] if len(partes) > 1 else None

            cur.execute(
                """
                INSERT INTO crm.leads
                    (nombres, apellidos, telefono, email, ciudad,
                     fuente_id, campana, observaciones, asesor_id, estado_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::uuid, 1)
                RETURNING id
                """,
                (
                    nombres, apellidos, telefono, data.email, data.ciudad,
                    fuente_id, data.campana, data.observaciones, asesor_id,
                ),
            )
            lead_id = cur.fetchone()["id"]

        conn.commit()

    return {
        "action": "created",
        "lead_id": lead_id,
        "asesor_id": asesor_id,
        "telefono": telefono,
        "message": "Lead creado y asignado a supervisor",
    }


# ─── Crear contacto (copia exacta de contactos.py POST, aquí porque
#     agenda.py SÍ se actualiza en deploy mientras contactos.py no) ───

class ContactoIn(BaseModel):
    tipo_contacto: str = "llamada"
    resultado: Optional[str] = None
    notas: Optional[str] = None
    proxima_accion: Optional[str] = None
    fecha_proxima_accion: Optional[str] = None
    fecha_cita: Optional[str] = None
    tipo_cita: Optional[str] = None
    url_reunion: Optional[str] = None
    duracion_minutos: Optional[int] = None
    nuevo_estado_id: Optional[int] = None
    # V042: estado de la cita (Pendiente / Completada / Reprogramada / ...)
    # Solo aplica cuando fecha_cita IS NOT NULL. Si no se envia y hay
    # fecha_cita, el INSERT cae al default 'pendiente' del catalogo.
    cita_estado_id: Optional[int] = None


@router.post("/contacto/{lead_id}", status_code=201)
def create_contacto_v2(
    lead_id: int,
    data: ContactoIn,
    current_user: TokenData = Depends(get_current_user),
):
    """Crear contacto — endpoint alternativo que sí se actualiza en deploy."""
    # V070.41 — AUTO-FIX en lugar de rechazo (ver justificacion en
    # contactos.py POST). Default fecha NOW+1h hora Lima si llega null
    # con resultado=cita_agendada. Mejor UX que 400, y el supervisor
    # puede editar la hora despues.
    es_cita = (
        (data.resultado or '').strip().lower() == 'cita_agendada'
        or (data.tipo_contacto or '').strip().lower() == 'cita'
    )
    if es_cita and not (data.fecha_cita and data.fecha_cita.strip()):
        from datetime import datetime, timezone, timedelta
        default_dt = datetime.now(timezone(timedelta(hours=-5))) + timedelta(hours=1)
        default_dt = default_dt.replace(minute=0, second=0, microsecond=0)
        data.fecha_cita = default_dt.strftime("%Y-%m-%dT%H:%M:00")
        logger.warning(
            "AUTO-FIX cita_agendada sin fecha_cita lead=%s user=%s → defaulted to %s",
            lead_id, current_user.user_id, data.fecha_cita
        )

    # Validar que la fecha de la cita no sea pasada. Reportado en UAT v3.1:
    # el frontend dejaba crear citas con fecha pasada, lo que ensuciaba la
    # agenda y mostraba citas "vencidas" como nuevas. Defense in depth: el
    # backend tambien rechaza para que un cliente desactualizado no logre
    # colarse. Tolerancia 5 min para acomodar clock drift entre client y server.
    if data.fecha_cita:
        from datetime import datetime, timezone, timedelta
        try:
            cleaned = data.fecha_cita.strip().replace(' ', 'T')
            if cleaned.endswith('Z'):
                cleaned = cleaned[:-1] + '+00:00'
            cita_dt = datetime.fromisoformat(cleaned)
            if cita_dt.tzinfo is None:
                # Asumir hora Lima si no viene tz (caso historico de la app).
                cita_dt = cita_dt.replace(tzinfo=timezone(timedelta(hours=-5)))
            now = datetime.now(timezone.utc)
            if cita_dt < now - timedelta(minutes=5):
                raise HTTPException(
                    status_code=400,
                    detail="No se puede agendar una cita con fecha pasada. "
                           "Usá una fecha y hora a partir de ahora.",
                )
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Formato de fecha_cita inválido: {data.fecha_cita}",
            ) from exc

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Verificar acceso al lead
            if current_user.role == "admin":
                cur.execute("SELECT id FROM crm.leads WHERE id = %s AND activo = TRUE", (lead_id,))
            elif current_user.role == "supervisor":
                # V035/V041: supervisor también puede actuar sobre leads en su
                # cola (asesor_id IS NULL, supervisor_id = self). V041 anade
                # el AND asesor_id IS NULL para que un lead que ya fue tomado
                # por otro (admin u otro supervisor) deje de ser accesible.
                cur.execute(
                    "SELECT l.id FROM crm.leads l WHERE l.id = %s AND l.activo = TRUE "
                    "AND (l.asesor_id IN (SELECT asesor_id FROM crm.equipos WHERE supervisor_id = %s::uuid AND activo = TRUE) "
                    "OR l.asesor_id = %s::uuid "
                    "OR (l.asesor_id IS NULL AND l.supervisor_id = %s::uuid))",
                    (lead_id, current_user.user_id, current_user.user_id, current_user.user_id),
                )
            else:
                cur.execute(
                    "SELECT id FROM crm.leads WHERE id = %s AND asesor_id = %s::uuid AND activo = TRUE",
                    (lead_id, current_user.user_id),
                )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Lead no encontrado o sin permiso")

            logger.info("CREATE contacto v2 lead=%s fecha_cita=%s", lead_id, data.fecha_cita)

            # V042: si hay fecha_cita y no vino cita_estado_id, default Pendiente.
            cita_estado_id_final = data.cita_estado_id
            if data.fecha_cita and cita_estado_id_final is None and _has_cita_estado_column(cur):
                cur.execute(
                    "SELECT id FROM crm.cita_estados WHERE codigo = 'pendiente' LIMIT 1"
                )
                row_pe = cur.fetchone()
                cita_estado_id_final = row_pe["id"] if row_pe else None

            if _has_cita_estado_column(cur):
                cur.execute(
                    """
                    INSERT INTO crm.contactos
                        (lead_id, asesor_id, tipo_contacto, resultado, notas,
                         proxima_accion, fecha_proxima_accion, fecha_cita, tipo_cita,
                         url_reunion, duracion_minutos, cita_estado_id)
                    VALUES (%s, %s::uuid, %s, %s, %s, %s,
                            %s::timestamptz, %s::timestamptz, %s, %s, %s, %s)
                    RETURNING id, fecha_cita::text
                    """,
                    (
                        lead_id, current_user.user_id,
                        data.tipo_contacto, data.resultado, data.notas,
                        data.proxima_accion, data.fecha_proxima_accion,
                        data.fecha_cita, data.tipo_cita,
                        data.url_reunion.strip() if data.url_reunion else None,
                        data.duracion_minutos,
                        cita_estado_id_final,
                    ),
                )
            else:
                # Fallback pre-V042: no incluimos la columna
                cur.execute(
                    """
                    INSERT INTO crm.contactos
                        (lead_id, asesor_id, tipo_contacto, resultado, notas,
                         proxima_accion, fecha_proxima_accion, fecha_cita, tipo_cita,
                         url_reunion, duracion_minutos)
                    VALUES (%s, %s::uuid, %s, %s, %s, %s,
                            %s::timestamptz, %s::timestamptz, %s, %s, %s)
                    RETURNING id, fecha_cita::text
                    """,
                    (
                        lead_id, current_user.user_id,
                        data.tipo_contacto, data.resultado, data.notas,
                        data.proxima_accion, data.fecha_proxima_accion,
                        data.fecha_cita, data.tipo_cita,
                        data.url_reunion.strip() if data.url_reunion else None,
                        data.duracion_minutos,
                    ),
                )
            row = cur.fetchone()

            if data.nuevo_estado_id:
                cur.execute("SELECT estado_id FROM crm.leads WHERE id = %s", (lead_id,))
                prev_lead = cur.fetchone()
                prev_estado_id = prev_lead["estado_id"] if prev_lead else None

                cur.execute(
                    "UPDATE crm.leads SET estado_id = %s, updated_at = NOW() WHERE id = %s",
                    (data.nuevo_estado_id, lead_id),
                )

                if prev_estado_id != data.nuevo_estado_id and data.tipo_contacto != "cambio_estado":
                    cur.execute("SELECT nombre FROM crm.estados_lead WHERE id = %s", (data.nuevo_estado_id,))
                    ne_row = cur.fetchone()
                    ne_nombre = ne_row["nombre"] if ne_row else str(data.nuevo_estado_id)
                    prox_act = str(data.fecha_proxima_accion).strip() if (data.fecha_proxima_accion and str(data.fecha_proxima_accion).strip()) else None
                    cur.execute(
                        """
                        INSERT INTO crm.contactos (lead_id, asesor_id, tipo_contacto, notas, fecha_proxima_accion)
                        VALUES (%s, %s::uuid, 'cambio_estado', %s, %s::timestamptz)
                        """,
                        (lead_id, current_user.user_id, f"Estado → {ne_nombre} (por Cita)", prox_act),
                    )

            if data.fecha_proxima_accion and str(data.fecha_proxima_accion).strip():
                cur.execute(
                    """
                    UPDATE crm.leads
                    SET fecha_proxima_gestion = %s::timestamptz,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (str(data.fecha_proxima_accion).strip(), lead_id),
                )
            cur.execute(
                "UPDATE crm.leads SET updated_at = NOW() WHERE id = %s",
                (lead_id,),
            )
        conn.commit()

    return {"id": row["id"], "message": "Contacto registrado"}


# ─── Recordatorios de citas (para n8n) ────────────────────────────────────

@router.get("/citas-proximas")
def citas_proximas():
    """
    Devuelve citas en los proximos 35 minutos que NO tienen recordatorio enviado.
    Endpoint sin auth (llamado por n8n internamente).

    V5.73.3 — Filtra citas en estado final (cancelada / completada /
    no_asistio). Antes el endpoint las devolvia igual y el workflow n8n
    enviaba WhatsApp recordatorio para citas ya canceladas. Filas legacy
    sin cita_estado_id (NULL) se tratan como 'pendiente' y se incluyen.

    V096.8 — Filtra citas cuyo asesor no tiene telefono. Antes el endpoint
    las devolvia igual, y el workflow n8n las "marcaba como enviadas" con
    flag enviado_a='sin_telefono' en la rama "Marcar sin tel (skip)". Eso
    contaminaba crm.recordatorios_enviados: si despues se asignaba un
    asesor con telefono, el recordatorio nunca salia porque el flag ya
    existia. Ahora el SQL las excluye en origen — no se contamina nada y
    el flow natural las vuelve a procesar cuando hay asesor con tel.

    Tambien excluye citas sin asesor asignado (INNER JOIN auth.users):
    es funcionalmente identico al filtro de telefono — no se puede
    notificar a un asesor que no existe.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    c.id AS contacto_id,
                    c.fecha_cita::text,
                    c.tipo_cita,
                    c.url_reunion,
                    c.tipo_contacto,
                    TRIM(COALESCE(l.nombres,'') || ' ' || COALESCE(l.apellidos,'')) AS lead_nombre,
                    l.telefono AS lead_telefono,
                    TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS asesor_nombre,
                    u.telefono AS asesor_telefono,
                    u.email AS asesor_email,
                    TO_CHAR(c.fecha_cita AT TIME ZONE 'America/Lima', 'HH24:MI') AS hora_cita
                FROM crm.contactos c
                JOIN crm.leads l ON l.id = c.lead_id AND l.activo = TRUE
                JOIN auth.users u ON u.id = c.asesor_id
                LEFT JOIN crm.cita_estados ce ON ce.id = c.cita_estado_id
                WHERE c.fecha_cita IS NOT NULL
                  AND c.fecha_cita > NOW()
                  AND c.fecha_cita <= NOW() + INTERVAL '35 minutes'
                  -- V5.73.3 — excluir citas en estados terminales.
                  AND COALESCE(ce.codigo, 'pendiente') NOT IN ('cancelada', 'completada', 'no_asistio')
                  -- V096.8 — solo asesores con telefono valido para WhatsApp.
                  AND u.telefono IS NOT NULL
                  AND TRIM(u.telefono) <> ''
                  AND NOT EXISTS (
                      SELECT 1 FROM crm.recordatorios_enviados r
                      WHERE r.contacto_id = c.id AND r.tipo = 'whatsapp_cita'
                  )
                ORDER BY c.fecha_cita ASC
            """)
            rows = cur.fetchall()
    return {"total": len(rows), "citas": [dict(r) for r in rows]}


class RecordatorioIn(BaseModel):
    contacto_id: int
    enviado_a: Optional[str] = None


@router.post("/recordatorio-enviado", status_code=201)
def marcar_recordatorio(data: RecordatorioIn):
    """
    Marca un recordatorio como enviado para evitar duplicados.
    Endpoint sin auth (llamado por n8n internamente).
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO crm.recordatorios_enviados (contacto_id, tipo, enviado_a)
                VALUES (%s, 'whatsapp_cita', %s)
                ON CONFLICT (contacto_id, tipo) DO NOTHING
                RETURNING id
            """, (data.contacto_id, data.enviado_a))
            row = cur.fetchone()
        conn.commit()
    return {"ok": True, "id": row["id"] if row else None}


def _role_filter_contactos(user: TokenData) -> tuple[str, list]:
    """Devuelve cláusula WHERE y params según rol del usuario para filtrar citas de la agenda."""
    if can_view_all_data(user, "agenda"):
        return "", []
    elif user.role == "supervisor":
        return (
            """
            AND (
                c.asesor_id = %s::uuid
                OR c.asesor_id IN (
                    SELECT id FROM auth.users WHERE supervisor_jefe_id = %s::uuid AND is_active = TRUE AND role = 'supervisor'
                )
                OR c.asesor_id IN (
                    SELECT eq.asesor_id FROM crm.equipos eq
                    JOIN auth.users u ON u.id = eq.asesor_id
                    WHERE (
                        eq.supervisor_id = %s::uuid
                        OR eq.supervisor_id IN (
                            SELECT id FROM auth.users WHERE supervisor_jefe_id = %s::uuid AND is_active = TRUE AND role = 'supervisor'
                        )
                    )
                    AND eq.activo = TRUE
                    AND u.is_active = TRUE
                )
                OR (
                    c.asesor_id IS NULL AND (
                        l.asesor_id = %s::uuid
                        OR l.asesor_id IN (
                            SELECT id FROM auth.users WHERE supervisor_jefe_id = %s::uuid AND is_active = TRUE AND role = 'supervisor'
                        )
                        OR l.asesor_id IN (
                            SELECT eq.asesor_id FROM crm.equipos eq
                            JOIN auth.users u ON u.id = eq.asesor_id
                            WHERE (
                                eq.supervisor_id = %s::uuid
                                OR eq.supervisor_id IN (
                                    SELECT id FROM auth.users WHERE supervisor_jefe_id = %s::uuid AND is_active = TRUE AND role = 'supervisor'
                                )
                            )
                            AND eq.activo = TRUE
                            AND u.is_active = TRUE
                        )
                    )
                )
            )
            """,
            [
                user.user_id,
                user.user_id,
                user.user_id,
                user.user_id,
                user.user_id,
                user.user_id,
                user.user_id,
                user.user_id,
            ],
        )
    else:
        return (
            """
            AND (
                c.asesor_id = %s::uuid
                OR (c.asesor_id IS NULL AND l.asesor_id = %s::uuid)
            )
            """,
            [user.user_id, user.user_id],
        )


def _role_filter_leads_agenda(user: TokenData) -> tuple[str, list]:
    """Cláusula WHERE y params según rol para seguimientos y oportunidad futura en crm.leads."""
    if can_view_all_data(user, "agenda"):
        return "", []
    if user.role == "supervisor":
        return (
            """
            AND (
                l.asesor_id = %s::uuid
                OR l.supervisor_id = %s::uuid
                OR l.asesor_id IN (
                    SELECT id FROM auth.users WHERE supervisor_jefe_id = %s::uuid AND is_active = TRUE AND role = 'supervisor'
                )
                OR l.asesor_id IN (
                    SELECT eq.asesor_id FROM crm.equipos eq
                    JOIN auth.users u ON u.id = eq.asesor_id
                    WHERE (
                        eq.supervisor_id = %s::uuid
                        OR eq.supervisor_id IN (
                            SELECT id FROM auth.users WHERE supervisor_jefe_id = %s::uuid AND is_active = TRUE AND role = 'supervisor'
                        )
                    )
                    AND eq.activo = TRUE
                    AND u.is_active = TRUE
                )
            )
            """,
            [user.user_id] * 5,
        )
    return " AND l.asesor_id = %s::uuid ", [user.user_id]


@router.get("/citas")
def get_citas(
    mes: str = None,           # YYYY-MM, default = mes actual
    supervisor_id: Optional[str] = None,
    current_user: TokenData = Depends(get_current_user),
):
    """
    Devuelve citas agendadas, seguimientos y oportunidades futuras del mes indicado.
    - Citas: contactos en crm.contactos con resultado ILIKE '%cita%' o fecha_cita IS NOT NULL.
    - Seguimientos / Oportunidad futura: leads activos en crm.leads con fecha_proxima_gestion en el mes.
    Soporta filtrado opcional por supervisor_id.
    """
    from datetime import date, timedelta
    import calendar as cal_mod

    if not mes:
        today = date.today()
        mes = today.strftime("%Y-%m")

    try:
        year, month = int(mes[:4]), int(mes[5:7])
    except Exception:
        year, month = date.today().year, date.today().month

    last_day = cal_mod.monthrange(year, month)[1]
    fecha_desde = f"{year:04d}-{month:02d}-01"
    fecha_hasta  = f"{year:04d}-{month:02d}-{last_day:02d}"

    role_clause, role_params = _role_filter_contactos(current_user)
    leads_role_clause, leads_role_params = _role_filter_leads_agenda(current_user)

    supervisor_filter_clause = ""
    supervisor_filter_params = []
    if supervisor_id and supervisor_id.strip():
        supervisor_filter_clause = " AND (l.supervisor_id = %s::uuid OR eq_sup.supervisor_id = %s::uuid) "
        supervisor_filter_params = [supervisor_id.strip(), supervisor_id.strip()]

    # V042: incluimos cita_estado info via JOIN. Columna defensiva con NULL
    # como fallback para entornos donde la migracion aun no se aplico.
    cita_estado_select = (
        ", c.cita_estado_id, ce.codigo AS cita_estado_codigo, "
        "ce.nombre AS cita_estado_nombre, ce.color_hex AS cita_estado_color"
        if _has_cita_estado_column() else
        ", NULL::int AS cita_estado_id, NULL AS cita_estado_codigo, "
        "NULL AS cita_estado_nombre, NULL AS cita_estado_color"
    )
    cita_estado_join = (
        "LEFT JOIN crm.cita_estados ce ON ce.id = c.cita_estado_id"
        if _has_cita_estado_column() else ""
    )

    sql = f"""
        SELECT * FROM (
            SELECT
                c.id,
                'cita'::text AS item_kind,
                c.lead_id,
                COALESCE(NULLIF(c.tipo_cita, ''), c.tipo_contacto) AS tipo_contacto,
                c.resultado,
                c.tipo_cita,
                c.url_reunion,
                c.notas,
                c.proxima_accion,
                TO_CHAR(COALESCE(c.fecha_cita, c.fecha_proxima_accion, c.created_at)
                    AT TIME ZONE 'America/Lima', 'YYYY-MM-DD"T"HH24:MI:SS') AS fecha_evento,
                (COALESCE(c.fecha_cita, c.fecha_proxima_accion, c.created_at)
                    AT TIME ZONE 'America/Lima')::date::text AS fecha_dia,
                c.asesor_id::text,
                TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS asesor_nombre,
                COALESCE(l.supervisor_id, eq_sup.supervisor_id)::text AS supervisor_id,
                TRIM(COALESCE(sup.first_name,'') || ' ' || COALESCE(sup.last_name,'')) AS supervisor_nombre,
                TRIM(COALESCE(l.nombres,'')    || ' ' || COALESCE(l.apellidos,'')) AS lead_nombre,
                l.telefono AS lead_telefono,
                l.estado_id AS lead_estado_id,
                el.nombre   AS lead_estado_nombre,
                el.color_hex AS lead_estado_color
                {cita_estado_select}
            FROM crm.contactos c
            LEFT JOIN crm.leads l ON l.id = c.lead_id
            LEFT JOIN auth.users u ON u.id = c.asesor_id
            LEFT JOIN LATERAL (
                SELECT eq.supervisor_id
                FROM crm.equipos eq
                WHERE eq.asesor_id = COALESCE(c.asesor_id, l.asesor_id)
                  AND eq.activo = TRUE
                LIMIT 1
            ) eq_sup ON TRUE
            LEFT JOIN auth.users sup ON sup.id = COALESCE(l.supervisor_id, eq_sup.supervisor_id)
            LEFT JOIN crm.estados_lead el ON el.id = l.estado_id
            {cita_estado_join}
            WHERE (
                c.resultado ILIKE '%%cita%%'
                OR c.fecha_cita IS NOT NULL
            )
            -- V070.47 — Excluir citas de leads soft-deleted (activo=FALSE).
            AND l.activo = TRUE
            AND (COALESCE(c.fecha_cita, c.fecha_proxima_accion, c.created_at)
                    AT TIME ZONE 'America/Lima')::date
                BETWEEN %s::date AND %s::date
            {role_clause}
            {supervisor_filter_clause}

            UNION ALL

            SELECT
                (-l.id) AS id,
                CASE
                    WHEN LOWER(COALESCE(el.nombre, '')) ~ '(oportunidad|futur)' THEN 'oportunidad_futura'
                    ELSE 'seguimiento'
                END AS item_kind,
                l.id AS lead_id,
                CASE
                    WHEN LOWER(COALESCE(el.nombre, '')) ~ '(oportunidad|futur)' THEN 'oportunidad_futura'
                    ELSE 'seguimiento'
                END AS tipo_contacto,
                NULL::text AS resultado,
                CASE
                    WHEN LOWER(COALESCE(el.nombre, '')) ~ '(oportunidad|futur)' THEN 'Oportunidad futura'
                    ELSE 'Seguimiento'
                END AS tipo_cita,
                NULL::text AS url_reunion,
                COALESCE(NULLIF(TRIM(l.accion_proxima_gestion), ''), l.observaciones) AS notas,
                l.accion_proxima_gestion AS proxima_accion,
                TO_CHAR(l.fecha_proxima_gestion AT TIME ZONE 'America/Lima', 'YYYY-MM-DD"T"HH24:MI:SS') AS fecha_evento,
                (l.fecha_proxima_gestion AT TIME ZONE 'America/Lima')::date::text AS fecha_dia,
                l.asesor_id::text AS asesor_id,
                TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS asesor_nombre,
                COALESCE(l.supervisor_id, eq_sup.supervisor_id)::text AS supervisor_id,
                TRIM(COALESCE(sup.first_name,'') || ' ' || COALESCE(sup.last_name,'')) AS supervisor_nombre,
                TRIM(COALESCE(l.nombres,'')    || ' ' || COALESCE(l.apellidos,'')) AS lead_nombre,
                l.telefono AS lead_telefono,
                l.estado_id AS lead_estado_id,
                el.nombre   AS lead_estado_nombre,
                el.color_hex AS lead_estado_color,
                NULL::int   AS cita_estado_id,
                NULL::text  AS cita_estado_codigo,
                NULL::text  AS cita_estado_nombre,
                NULL::text  AS cita_estado_color
            FROM crm.leads l
            JOIN crm.estados_lead el ON el.id = l.estado_id
            LEFT JOIN auth.users u ON u.id = l.asesor_id
            LEFT JOIN LATERAL (
                SELECT eq.supervisor_id
                FROM crm.equipos eq
                WHERE eq.asesor_id = l.asesor_id
                  AND eq.activo = TRUE
                LIMIT 1
            ) eq_sup ON TRUE
            LEFT JOIN auth.users sup ON sup.id = COALESCE(l.supervisor_id, eq_sup.supervisor_id)
            WHERE l.activo = TRUE
              AND l.fecha_proxima_gestion IS NOT NULL
              AND COALESCE(el.es_final, FALSE) = FALSE
              AND (
                  LOWER(COALESCE(el.nombre, '')) LIKE '%%seguimiento%%'
                  OR LOWER(COALESCE(el.nombre, '')) LIKE '%%oportunidad%%'
                  OR LOWER(COALESCE(el.nombre, '')) LIKE '%%futur%%'
              )
              AND (l.fecha_proxima_gestion AT TIME ZONE 'America/Lima')::date
                  BETWEEN %s::date AND %s::date
              {leads_role_clause}
              {supervisor_filter_clause}
        ) agenda_items
        ORDER BY fecha_evento ASC
    """

    params = (
        [fecha_desde, fecha_hasta]
        + role_params
        + supervisor_filter_params
        + [fecha_desde, fecha_hasta]
        + leads_role_params
        + supervisor_filter_params
    )

    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return {"mes": mes, "total": len(rows), "citas": [dict(r) for r in rows]}
    except Exception as e:
        import traceback
        return {"mes": mes, "total": 0, "citas": [], "error": str(e), "trace": traceback.format_exc()}
