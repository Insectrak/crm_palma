"""
Filtros reutilizables para queries sobre `crm.leads`.

Antes esta lógica estaba duplicada en `routers/leads.py::list_leads`,
`routers/leads.py::exportar_leads` y `routers/dashboard.py::leads_por_estado`.
Ahora un único `LeadFilters` + `apply_lead_filters` los serializa todos.
"""
import re
from typing import Optional
from fastapi import Query
from pydantic import BaseModel
from app.auth.schemas import TokenData
from app.constants import Role
from app.auth.permissions import can_view_all_data


class LeadFilters(BaseModel):
    """Conjunto canónico de filtros aceptados por los endpoints de leads."""
    estado_id: Optional[int] = None
    subestado: Optional[str] = None      # Filtro por subestado / motivo / acción / cierre
    fuente_id: Optional[int] = None
    origen: Optional[str] = None         # Filtro por canal/plataforma de origen (TikTok, Facebook, Instagram, WhatsApp, etc.)
    asesor_id: Optional[str] = None
    asesor_historico_id: Optional[str] = None  # Filtro por asesor previo / histórico en historial de asignación
    supervisor_id: Optional[str] = None  # V035: filtro opcional por supervisor
    sin_asesor: bool = False
    en_cola: bool = False                # V035: solo leads en cola (asesor_id NULL)
    search: Optional[str] = None
    fecha_desde: Optional[str] = None  # YYYY-MM-DD inclusive (created_at)
    fecha_hasta: Optional[str] = None  # YYYY-MM-DD inclusive (created_at)
    fecha_asig_desde: Optional[str] = None  # YYYY-MM-DD inclusive (fecha_asignacion)
    fecha_asig_hasta: Optional[str] = None  # YYYY-MM-DD inclusive (fecha_asignacion)
    fecha_actividad_desde: Optional[str] = None  # YYYY-MM-DD inclusive (ultima_actividad)
    fecha_actividad_hasta: Optional[str] = None  # YYYY-MM-DD inclusive (ultima_actividad)
    campana: Optional[str] = None
    con_antecedentes: bool = False  # solo leads con es_recontacto = TRUE
    calidad: Optional[str] = None    # codigo del catalogo (FRIO|TIBIO|CALIENTE) o vacio
    api_client_id: Optional[str] = None  # V061: filtrar por proveedor que entrego el lead
    api_client_legacy_slug: Optional[str] = None  # V062: filtrar por proveedor original (post-unlink)
    sede_id: Optional[str] = None  # V065: filtrar por sede de destino del lead
    # V084: filtros por atribucion del recontacto. Cada uno hace EXISTS sobre
    # crm.lead_recontactos. Permiten preguntas como "leads que volvieron por
    # MI campaña de Meta Promo Verano 2026" — caso reportado por proveedor.
    recontacto_campana: Optional[str] = None
    recontacto_anuncio: Optional[str] = None
    recontacto_conjunto: Optional[str] = None
    recontacto_fuente_id: Optional[int] = None
    recontacto_desde: Optional[str] = None   # YYYY-MM-DD inclusive
    recontacto_hasta: Optional[str] = None   # YYYY-MM-DD inclusive
    recontacto_api_client_id: Optional[str] = None
    # V086: filtro UNIFICADO "tocado por proveedor". Devuelve leads donde
    # el proveedor X fue el ORIGEN del lead (api_client_id directo en
    # crm.leads) O al menos un RECONTACTO viene de ese proveedor (en
    # crm.lead_recontactos.api_client_id). Caso de uso: marketing pregunta
    # "muestrame TODO lo que toco wedo", sin tener que hacer 2 busquedas
    # y unirlas en Excel.
    tocado_por_api_client_id: Optional[str] = None
    # V094: leads con recontacto reciente (<=48h) sin contacto posterior.
    # Patron CRMs profesionales "re-engagement workflow": el lead que
    # volvio a interesarse necesita atencion urgente del asesor.
    # Filtro activo → bubble del lead en multiples surfaces (tab, banner,
    # dashboard card) para que no se pierda en la lista de 5k+ leads.
    recontacto_sin_atender: bool = False
    # V094: cualquier recontacto en las ultimas N horas (usado por la tab
    # "Recontactos" para mostrar los recientes aunque ya hayan sido atendidos).
    recontacto_recientes_horas: Optional[int] = None
    # Filtro por estado en cola / asignación ('estancados', 'pendientes', 'en_cola', 'asignados')
    estado_cola: Optional[str] = None
    # Filtro por alertas operacionales de llamada ('urgentes'/'sin_contacto_48h', 'sla_15m'/'sla_vencido')
    filtro_alerta: Optional[str] = None
    # V124: Filtro por estado de ficha técnica ('pendiente', 'incompleta', 'completa')
    ficha_tecnica_estado: Optional[str] = None
    # Filtro por estado de próxima gestión ('vencidas', 'sin_fecha', 'hoy', 'al_dia')
    filtro_fecha_gestion: Optional[str] = None
    # Subfiltros para citas agendadas: según fecha de cita y atención
    filtro_fecha_cita: Optional[str] = None
    filtro_cita_atendida: Optional[str] = None


def lead_filters_query(
    estado_id: Optional[int] = None,
    subestado: Optional[str] = None,
    fuente_id: Optional[int] = None,
    origen: Optional[str] = None,
    asesor_id: Optional[str] = None,
    asesor_historico_id: Optional[str] = None,
    supervisor_id: Optional[str] = None,
    sin_asesor: bool = False,
    en_cola: bool = False,
    search: Optional[str] = None,
    fecha_desde: Optional[str] = None,
    fecha_hasta: Optional[str] = None,
    fecha_asig_desde: Optional[str] = None,
    fecha_asig_hasta: Optional[str] = None,
    fecha_actividad_desde: Optional[str] = None,
    fecha_actividad_hasta: Optional[str] = None,
    campana: Optional[str] = None,
    con_antecedentes: bool = False,
    calidad: Optional[str] = None,
    api_client_id: Optional[str] = None,  # V061
    api_client_legacy_slug: Optional[str] = None,  # V062
    sede_id: Optional[str] = None,  # V065
    # V084: filtros por atribucion del recontacto
    recontacto_campana: Optional[str] = None,
    recontacto_anuncio: Optional[str] = None,
    recontacto_conjunto: Optional[str] = None,
    recontacto_fuente_id: Optional[int] = None,
    recontacto_desde: Optional[str] = None,
    recontacto_hasta: Optional[str] = None,
    recontacto_api_client_id: Optional[str] = None,
    tocado_por_api_client_id: Optional[str] = None,
    # V094 — re-engagement workflow
    recontacto_sin_atender: bool = False,
    recontacto_recientes_horas: Optional[int] = None,
    estado_cola: Optional[str] = None,
    filtro_alerta: Optional[str] = None,
    ficha_tecnica_estado: Optional[str] = None,
    filtro_fecha_gestion: Optional[str] = None,
    filtro_fecha_cita: Optional[str] = None,
    filtro_cita_atendida: Optional[str] = None,
) -> LeadFilters:
    """Dependency de FastAPI que arma `LeadFilters` desde query params."""
    return LeadFilters(
        estado_id=estado_id,
        subestado=subestado,
        fuente_id=fuente_id,
        origen=origen,
        asesor_id=asesor_id,
        asesor_historico_id=asesor_historico_id,
        supervisor_id=supervisor_id,
        sin_asesor=sin_asesor,
        en_cola=en_cola,
        search=search,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        fecha_asig_desde=fecha_asig_desde,
        fecha_asig_hasta=fecha_asig_hasta,
        fecha_actividad_desde=fecha_actividad_desde,
        fecha_actividad_hasta=fecha_actividad_hasta,
        campana=campana,
        con_antecedentes=con_antecedentes,
        calidad=calidad,
        api_client_id=api_client_id,
        api_client_legacy_slug=api_client_legacy_slug,
        sede_id=sede_id,
        recontacto_campana=recontacto_campana,
        recontacto_anuncio=recontacto_anuncio,
        recontacto_conjunto=recontacto_conjunto,
        recontacto_fuente_id=recontacto_fuente_id,
        recontacto_desde=recontacto_desde,
        recontacto_hasta=recontacto_hasta,
        recontacto_api_client_id=recontacto_api_client_id,
        tocado_por_api_client_id=tocado_por_api_client_id,
        recontacto_sin_atender=recontacto_sin_atender,
        recontacto_recientes_horas=recontacto_recientes_horas,
        estado_cola=estado_cola,
        filtro_alerta=filtro_alerta,
        ficha_tecnica_estado=ficha_tecnica_estado,
        filtro_fecha_gestion=filtro_fecha_gestion,
        filtro_fecha_cita=filtro_fecha_cita,
        filtro_cita_atendida=filtro_cita_atendida,
    )


def role_filter(user: TokenData) -> tuple[str, list]:
    """Cláusula WHERE y params para limitar leads visibles por rol.

    - admin:      todos
    - supervisor: leads de su equipo (crm.equipos), asignados a él,
                  o en su cola (supervisor_id = él, asesor_id NULL). V041
    - asesor:     solo sus propios leads

    V041 — el OR de supervisor_id ahora exige asesor_id IS NULL. Antes
    permitia ver leads que un admin (u otro supervisor) habia tomado pero
    cuyo supervisor_id seguia historicamente apuntando al supervisor
    original — Paola seguia viendo leads asignados a Admin CRM. La cola
    es por definicion "lead sin asesor": si alguien lo tomo, sale.

    Sprint 4 (ADR-0012) — Sharing Rules: si el usuario tiene `role_id`
    custom y hay reglas activas para ese rol, se extiende el WHERE con
    los leads que matchean esas reglas. Patron CRMs profesionales —
    el admin define vistas compartidas declarativas y los usuarios con
    rol custom las ven ademas de los leads propios.
    """
    if can_view_all_data(user, "leads"):
        return "TRUE", []
    if user.role == Role.SUPERVISOR or user.role == "supervisor":
        base = (
            "("
            "l.asesor_id = %s::uuid "
            "OR (l.supervisor_id = %s::uuid AND ("
                "l.asesor_id IS NULL "
                "OR l.estado_id IN (SELECT id FROM crm.estados_lead WHERE nombre ILIKE '%%matr%%' OR nombre ILIKE '%%ganad%%' OR nombre ILIKE '%%cierr%%' OR nombre ILIKE '%%reserv%%' OR nombre ILIKE '%%separac%%' OR nombre ILIKE '%%venta concretad%%') "
                "OR l.tipo_cierre IS NOT NULL"
            ")) "
            "OR l.asesor_id IN ("
                "SELECT id FROM auth.users WHERE supervisor_jefe_id = %s::uuid AND is_active = TRUE AND role = 'supervisor'"
            ") "
            "OR (l.supervisor_id IN ("
                "SELECT id FROM auth.users WHERE supervisor_jefe_id = %s::uuid AND is_active = TRUE AND role = 'supervisor'"
            ") AND ("
                "l.asesor_id IS NULL "
                "OR l.estado_id IN (SELECT id FROM crm.estados_lead WHERE nombre ILIKE '%%matr%%' OR nombre ILIKE '%%ganad%%' OR nombre ILIKE '%%cierr%%' OR nombre ILIKE '%%reserv%%' OR nombre ILIKE '%%separac%%' OR nombre ILIKE '%%venta concretad%%') "
                "OR l.tipo_cierre IS NOT NULL"
            ")) "
            "OR l.asesor_id IN ("
                "SELECT eq.asesor_id FROM crm.equipos eq "
                "WHERE (eq.supervisor_id = %s::uuid OR eq.supervisor_id IN ("
                    "SELECT id FROM auth.users WHERE supervisor_jefe_id = %s::uuid AND is_active = TRUE AND role = 'supervisor'"
                ")) AND eq.activo = TRUE"
            ")"
            ")"
        )
        return base, [
            user.user_id,
            user.user_id,
            user.user_id,
            user.user_id,
            user.user_id,
            user.user_id,
        ]

    # asesor base — `l.asesor_id = user.id`. Sumar sharing rules si aplica.
    base_where = "l.asesor_id = %s::uuid"
    base_params: list = [user.user_id]
    shared_where, shared_params = _shared_rules_for_user(user)
    if shared_where:
        return f"({base_where} OR {shared_where})", base_params + shared_params
    return base_where, base_params


def _shared_rules_for_user(user: TokenData) -> tuple[Optional[str], list]:
    """Devuelve (where, params) con las sharing rules activas del role_id
    del usuario. Si no tiene role_id custom o no hay reglas activas, (None, []).

    Fail-safe: si la tabla `crm.lead_sharing_rules` no existe todavia
    (deploy pre-V082) o cualquier otro error, devuelve (None, []) sin
    bloquear el listado de leads.
    """
    role_id = getattr(user, "role_id", None)
    if not role_id:
        return None, []
    try:
        from app.database import get_db
        from app.services import lead_sharing_service
        from psycopg2.extras import RealDictCursor
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                return lead_sharing_service.build_shared_where_for_role(cur, int(role_id))
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).debug(
            "sharing rules lookup fallido para role_id=%s: %s", role_id, exc,
        )
        return None, []


def apply_lead_filters(
    filters: LeadFilters,
    user: TokenData,
    *,
    include_estado: bool = True,
) -> tuple[str, list]:
    """Construye la cláusula WHERE completa y la lista de params.

    Devuelve `(where_sql, params)` listos para inyectar en una query
    sobre `crm.leads l` (alias `l` obligatorio).

    `include_estado=False` permite reusar el mismo filtro en endpoints
    que agrupan por estado (donde forzar `estado_id` rompería la lógica).
    """
    role_clause, params = role_filter(user)

    parts = [f"({role_clause})"]

    if include_estado and filters.estado_id:
        parts.append("l.estado_id = %s")
        params.append(filters.estado_id)
    if filters.subestado and filters.subestado.strip():
        sub_val = filters.subestado.strip()
        parts.append(
            "("
            "l.motivo_perdida ILIKE %s OR "
            "l.motivo_perdida_otro ILIKE %s OR "
            "l.tipo_cierre ILIKE %s OR "
            "l.segunda_voz ILIKE %s OR "
            "l.accion_proxima_gestion ILIKE %s"
            ")"
        )
        p = f"%{sub_val}%"
        params.extend([p, p, p, p, p])
    if filters.fuente_id:
        parts.append("l.fuente_id = %s")
        params.append(filters.fuente_id)
    if filters.sin_asesor or filters.en_cola:
        parts.append("l.asesor_id IS NULL")
    elif filters.asesor_id and (user.role in (Role.ADMIN, Role.SUPERVISOR) or getattr(user, "role_id", None) is not None):
        parts.append("l.asesor_id = %s::uuid")
        params.append(filters.asesor_id)
    if filters.estado_cola:
        ec = filters.estado_cola.strip().lower()
        if ec in ("estancados", "estancado", "stale"):
            parts.append(
                "("
                "(l.asesor_id IS NULL OR l.asesor_id IN (SELECT u_sup.id FROM auth.users u_sup WHERE u_sup.role = 'supervisor')) "
                "AND ("
                "  (l.fecha_entrada_cola IS NOT NULL AND l.fecha_entrada_cola < NOW() - INTERVAL '24 hours') "
                "  OR (l.fecha_entrada_cola IS NULL AND l.created_at < NOW() - INTERVAL '24 hours')"
                ")"
                ")"
            )
        elif ec in ("pendientes", "pendiente", "pending"):
            parts.append(
                "("
                "(l.asesor_id IS NULL OR l.asesor_id IN (SELECT u_sup.id FROM auth.users u_sup WHERE u_sup.role = 'supervisor')) "
                "AND ("
                "  (l.fecha_entrada_cola IS NOT NULL AND l.fecha_entrada_cola >= NOW() - INTERVAL '24 hours') "
                "  OR (l.fecha_entrada_cola IS NULL AND l.created_at >= NOW() - INTERVAL '24 hours')"
                ")"
                ")"
            )
        elif ec in ("en_cola", "cola", "sin_asignar"):
            parts.append(
                "(l.asesor_id IS NULL OR l.asesor_id IN (SELECT u_sup.id FROM auth.users u_sup WHERE u_sup.role = 'supervisor'))"
            )
        elif ec in ("asignados", "asignado"):
            parts.append(
                "(l.asesor_id IS NOT NULL AND l.asesor_id NOT IN (SELECT u_sup.id FROM auth.users u_sup WHERE u_sup.role = 'supervisor'))"
            )
    if filters.asesor_historico_id:
        parts.append(
            "("
            "EXISTS ("
                "SELECT 1 FROM crm.asignaciones_log al "
                "WHERE al.lead_id = l.id "
                "AND (al.asesor_anterior = %s::uuid OR al.asesor_nuevo = %s::uuid)"
            ") "
            "OR l.previous_asesor_id = %s::uuid"
            ")"
            " AND (l.asesor_id IS DISTINCT FROM %s::uuid)"
        )
        params.extend([
            filters.asesor_historico_id,
            filters.asesor_historico_id,
            filters.asesor_historico_id,
            filters.asesor_historico_id,
        ])
    if filters.supervisor_id and (user.role in (Role.ADMIN, Role.SUPERVISOR) or getattr(user, "role_id", None) is not None):
        parts.append(
            "("
            "(l.asesor_id IS NULL AND l.supervisor_id = %s::uuid) "
            "OR l.asesor_id = %s::uuid "
            "OR l.asesor_id IN ("
                "SELECT eq.asesor_id FROM crm.equipos eq "
                "WHERE eq.supervisor_id = %s::uuid AND eq.activo = TRUE"
            ")"
            ")"
        )
        params.extend([filters.supervisor_id, filters.supervisor_id, filters.supervisor_id])
    if filters.origen:
        origen_val = filters.origen.strip().lower()
        if origen_val in ("tiktok", "tt"):
            parts.append(
                "("
                "l.campana ILIKE %s "
                "OR l.campana ILIKE %s "
                "OR l.campana ILIKE %s "
                "OR l.anuncio ILIKE %s "
                "OR l.fuente_form_id ILIKE %s "
                "OR l.campana ILIKE %s "
                "OR l.campana ILIKE %s "
                "OR l.campana ILIKE %s "
                "OR l.campana ILIKE %s "
                "OR l.api_client_legacy_slug = 'tiktok' "
                "OR EXISTS (SELECT 1 FROM crm.fuentes f WHERE f.id = l.fuente_id AND (f.nombre ILIKE %s OR f.nombre ILIKE %s))"
                ")"
            )
            params.extend([
                "1870%", "1851%", "75%", "75%", "75%",
                "%presencial campaña sur%", "%virtual 3%", "%tiktok%", "%tt%",
                "%tiktok%", "%tt%",
            ])
        elif origen_val in ("facebook", "fb", "meta"):
            parts.append(
                "("
                "l.campana ILIKE %s "
                "OR l.campana ILIKE %s "
                "OR l.anuncio ILIKE %s "
                "OR l.fuente_externa_id ILIKE %s "
                "OR l.leadgen_id IS NOT NULL "
                "OR l.campana ILIKE %s "
                "OR l.campana ILIKE %s "
                "OR l.campana ILIKE %s "
                "OR (l.campana ILIKE %s AND l.campana NOT ILIKE %s) "
                "OR l.api_client_legacy_slug IN ('meta', 'facebook', 'fb') "
                "OR EXISTS (SELECT 1 FROM crm.fuentes f WHERE f.id = l.fuente_id AND (f.nombre ILIKE %s OR f.nombre ILIKE %s OR f.nombre ILIKE %s))"
                ")"
            )
            params.extend([
                "1202%", "12%", "1202%", "1202%",
                "%perfilado%", "%virtual ii%", "%agosto 1%",
                "%campaña presencial%", "%sur%",
                "%facebook%", "%fb%", "%meta%",
            ])
        elif origen_val in ("instagram", "ig"):
            parts.append(
                "("
                "l.api_client_legacy_slug = 'instagram' "
                "OR EXISTS (SELECT 1 FROM crm.fuentes f WHERE f.id = l.fuente_id AND (f.nombre ILIKE %s OR f.nombre ILIKE %s))"
                ")"
            )
            params.extend(["%instagram%", "%ig%"])
        elif origen_val in ("whatsapp", "wa"):
            parts.append(
                "("
                "l.api_client_legacy_slug = 'whatsapp' "
                "OR EXISTS (SELECT 1 FROM crm.wa_conversations wc WHERE wc.lead_id = l.id AND wc.wa_number_id IS NOT NULL) "
                "OR EXISTS (SELECT 1 FROM crm.fuentes f WHERE f.id = l.fuente_id AND (f.nombre ILIKE %s OR f.nombre ILIKE %s))"
                ")"
            )
            params.extend(["%whatsapp%", "%wa%"])
        else:
            parts.append(
                "EXISTS (SELECT 1 FROM crm.fuentes f WHERE f.id = l.fuente_id AND LOWER(f.nombre) = %s)"
            )
            params.append(origen_val)
    # V069 — Busqueda inteligente world-class (paridad con CRMs profesionales).
    #
    # Bug previo: la busqueda concatenaba ILIKE en cada columna por separado.
    # Si nombres="Flor" y apellidos="Olazabal mamani", buscar
    # "Flor Olazabal mamani" no matcheaba porque ninguna columna sola
    # contenia la frase completa.
    #
    # Fix de 2 capas:
    #   1) Single-token: ILIKE en cada campo + el full_name concatenado
    #      (cubre busquedas simples como "Flor", "mamani", o por telefono).
    #   2) Multi-token: cada palabra debe matchear EN ALGUN campo
    #      (nombres OR apellidos OR full_name concat). AND entre tokens.
    #      Permite reordering ("mamani Flor") y particiones ("Flor mamani"
    #      saltando el medio).
    #   Plus: la frase completa se busca tambien en telefono+email para
    #   no perder esos canales con multi-token.
    # V069 / V106 — Búsqueda inteligente:
    # Soporta búsqueda por teléfono con dígitos separados (ej: "9 5 1 2 3 4 5 6 7", "951 234 567", "+51 951 234 567"),
    # con el mismo comportamiento que en la vista de Históricos, normalizando dígitos (REGEXP_REPLACE)
    # y respetando DNI, nombres y email.
    if filters.search and filters.search.strip():
        s = filters.search.strip()
        digits = re.sub(r'\D', '', s)
        full_name_expr = "TRIM(COALESCE(l.nombres,'') || ' ' || COALESCE(l.apellidos,''))"
        has_letters = bool(re.search(r'[a-zA-ZáéíóúÁÉÍÓÚñÑ]', s))

        if digits and len(digits) >= 4 and not has_letters:
            # Búsqueda numérica / teléfono con dígitos separados (paridad con Históricos).
            # Soporta: "9 5 1 2 3 4 5 6 7", "951 234 567", "+51 951 234 567", "951234567",
            # números con guiones/paréntesis, o DNI.
            phone_pattern = f"%{digits[-9:]}%"
            parts.append(
                "("
                "REGEXP_REPLACE(COALESCE(l.telefono, ''), '\\D', '', 'g') LIKE %s "
                "OR l.telefono ILIKE %s "
                "OR l.dni ILIKE %s"
                ")"
            )
            params.extend([phone_pattern, phone_pattern, f"%{digits}%"])
        elif digits and len(digits) >= 4 and has_letters:
            # Búsqueda mixta: contiene letras y 4+ dígitos (ej: "juan1234@gmail.com" o "Flor 951 234 567")
            phone_pattern = f"%{digits[-9:]}%"
            tokens = [t for t in s.split() if t]
            token_clauses = []
            for tok in tokens:
                token_clauses.append(
                    f"(l.nombres ILIKE %s OR l.apellidos ILIKE %s OR {full_name_expr} ILIKE %s)"
                )
                tterm = f"%{tok}%"
                params += [tterm, tterm, tterm]
            parts.append(
                "("
                "(" + " AND ".join(token_clauses) + ") "
                "OR REGEXP_REPLACE(COALESCE(l.telefono, ''), '\\D', '', 'g') LIKE %s "
                "OR l.telefono ILIKE %s "
                "OR l.dni ILIKE %s "
                "OR l.email ILIKE %s"
                ")"
            )
            params.extend([phone_pattern, phone_pattern, f"%{digits}%", f"%{s}%"])
        else:
            # Búsqueda por texto (nombres, apellidos, email, etc.)
            tokens = [t for t in s.split() if t]
            if len(tokens) <= 1:
                parts.append(
                    f"(l.nombres ILIKE %s OR l.apellidos ILIKE %s "
                    f"OR {full_name_expr} ILIKE %s "
                    f"OR l.telefono ILIKE %s OR l.dni ILIKE %s OR l.email ILIKE %s)"
                )
                term = f"%{s}%"
                params += [term, term, term, term, term, term]
            else:
                token_clauses = []
                for tok in tokens:
                    token_clauses.append(
                        f"(l.nombres ILIKE %s OR l.apellidos ILIKE %s "
                        f"OR {full_name_expr} ILIKE %s)"
                    )
                    tterm = f"%{tok}%"
                    params += [tterm, tterm, tterm]
                parts.append(
                    "((" + " AND ".join(token_clauses) + ") "
                    "OR l.telefono ILIKE %s OR l.dni ILIKE %s OR l.email ILIKE %s)"
                )
                full_term = f"%{s}%"
                params += [full_term, full_term, full_term]
    if filters.fecha_desde:
        parts.append("l.created_at >= %s::date")
        params.append(filters.fecha_desde)
    if filters.fecha_hasta:
        parts.append("l.created_at < (%s::date + INTERVAL '1 day')")
        params.append(filters.fecha_hasta)
    if filters.fecha_asig_desde:
        parts.append("l.fecha_asignacion >= %s::date")
        params.append(filters.fecha_asig_desde)
    if filters.fecha_asig_hasta:
        parts.append("l.fecha_asignacion < (%s::date + INTERVAL '1 day')")
        params.append(filters.fecha_asig_hasta)
    if filters.fecha_actividad_desde:
        parts.append(
            "(SELECT MAX(ts) FROM ("
            "  SELECT created_at AS ts FROM crm.contactos WHERE lead_id = l.id "
            "  UNION ALL SELECT fecha_llamada AS ts FROM crm.llamadas WHERE lead_id = l.id "
            "  UNION ALL SELECT created_at AS ts FROM crm.asignaciones_log WHERE lead_id = l.id "
            "  UNION ALL SELECT created_at AS ts FROM crm.lead_recontactos WHERE lead_id = l.id "
            "  UNION ALL SELECT COALESCE(l.updated_at, l.created_at) AS ts"
            ") _all_act) >= %s::date"
        )
        params.append(filters.fecha_actividad_desde)
    if filters.fecha_actividad_hasta:
        parts.append(
            "(SELECT MAX(ts) FROM ("
            "  SELECT created_at AS ts FROM crm.contactos WHERE lead_id = l.id "
            "  UNION ALL SELECT fecha_llamada AS ts FROM crm.llamadas WHERE lead_id = l.id "
            "  UNION ALL SELECT created_at AS ts FROM crm.asignaciones_log WHERE lead_id = l.id "
            "  UNION ALL SELECT created_at AS ts FROM crm.lead_recontactos WHERE lead_id = l.id "
            "  UNION ALL SELECT COALESCE(l.updated_at, l.created_at) AS ts"
            ") _all_act) < (%s::date + INTERVAL '1 day')"
        )
        params.append(filters.fecha_actividad_hasta)
    if filters.campana:
        parts.append("l.campana ILIKE %s")
        params.append(f"%{filters.campana}%")
    if filters.con_antecedentes:
        # El badge "↻ N" del frontend cuenta filas en crm.lead_recontactos (V048).
        # Antes el filtro usaba `l.es_recontacto = TRUE` que es OTRA cosa: indica
        # que el lead ES un recontacto, no que TIENE recontactos. Reportado por
        # usuario 2026-06-16: filtro daba 0 leads aunque varios mostraban el
        # badge.
        parts.append(
            "EXISTS (SELECT 1 FROM crm.lead_recontactos WHERE lead_id = l.id)"
        )
    if filters.recontacto_sin_atender:
        # V094.1 — re-engagement workflow con ESCALACION DE SEVERIDAD
        # patron CRMs profesionales: el filtro retorna TODOS los leads
        # con recontacto pendiente de respuesta, sin cap de tiempo.
        # La visualizacion (banner + KpiCard) usa el breakdown
        # amber (<48h) / red (>=48h) para escalar urgencia visual.
        #
        # Cambio vs V094: removido el cap "ultimas 48h". Antes los
        # recontactos sin atender por >48h desaparecian silenciosamente del
        # filtro → punto ciego de UX. Ahora se mantienen visibles y se
        # vuelven mas urgentes con el tiempo (banner rojo).
        parts.append(
            "l.fecha_ultimo_recontacto IS NOT NULL "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM ("
            "    SELECT lead_id, created_at FROM crm.contactos WHERE tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion') "
            "    UNION ALL "
            "    SELECT lead_id, fecha_llamada AS created_at FROM crm.llamadas WHERE lead_id IS NOT NULL"
            "  ) c "
            "  WHERE c.lead_id = l.id "
            "    AND c.created_at > l.fecha_ultimo_recontacto"
            ")"
        )
    if filters.recontacto_recientes_horas is not None and filters.recontacto_recientes_horas > 0:
        # V094 — todos los recontactos de las ultimas N horas (atendidos o no).
        # Sirve para la tab "Recontactos" que muestra la actividad reciente
        # completa, no solo lo urgente.
        parts.append(
            "l.fecha_ultimo_recontacto IS NOT NULL "
            "AND l.fecha_ultimo_recontacto > NOW() - (%s || ' hours')::INTERVAL"
        )
        params.append(str(filters.recontacto_recientes_horas))
    if filters.calidad:
        # codigo del catalogo (FRIO/TIBIO/CALIENTE...). Comparacion case-insensitive.
        parts.append("UPPER(l.calidad) = UPPER(%s)")
        params.append(filters.calidad)
    if filters.api_client_id:
        # V061: filtra leads que vinieron por una API key especifica
        # (proveedores externos: Wedo, agencias, etc.).
        parts.append("l.api_client_id = %s::uuid")
        params.append(filters.api_client_id)
    if filters.api_client_legacy_slug:
        # V062: filtra por proveedor original (slug snapshoteado al unlink).
        # Sirve para "leads que vinieron de Wedo" aunque ya se desvincularon.
        parts.append("l.api_client_legacy_slug = %s")
        params.append(filters.api_client_legacy_slug)
    if filters.sede_id:
        # V065: filtra leads por sede de destino. Atributo, no permiso —
        # el role_filter sigue siendo invariante por encima.
        parts.append("l.sede_id = %s::uuid")
        params.append(filters.sede_id)

    # V084 — filtros por atribucion del recontacto. Se construye UNA sola
    # cláusula EXISTS combinando todos los criterios, así un mismo row de
    # crm.lead_recontactos debe matchear TODO lo pedido (no leads cuyos
    # recontactos por separado cubran los filtros).
    recontacto_clauses = []
    recontacto_params: list = []
    if filters.recontacto_campana:
        recontacto_clauses.append("r.campana ILIKE %s")
        recontacto_params.append(f"%{filters.recontacto_campana}%")
    if filters.recontacto_anuncio:
        recontacto_clauses.append("r.anuncio ILIKE %s")
        recontacto_params.append(f"%{filters.recontacto_anuncio}%")
    if filters.recontacto_conjunto:
        recontacto_clauses.append("r.conjunto ILIKE %s")
        recontacto_params.append(f"%{filters.recontacto_conjunto}%")
    if filters.recontacto_fuente_id is not None:
        recontacto_clauses.append("r.fuente_id = %s")
        recontacto_params.append(filters.recontacto_fuente_id)
    if filters.recontacto_desde:
        recontacto_clauses.append("r.created_at >= %s::date")
        recontacto_params.append(filters.recontacto_desde)
    if filters.recontacto_hasta:
        recontacto_clauses.append("r.created_at < (%s::date + INTERVAL '1 day')")
        recontacto_params.append(filters.recontacto_hasta)
    if filters.recontacto_api_client_id:
        recontacto_clauses.append("r.api_client_id = %s::uuid")
        recontacto_params.append(filters.recontacto_api_client_id)
    if recontacto_clauses:
        parts.append(
            "EXISTS (SELECT 1 FROM crm.lead_recontactos r "
            "WHERE r.lead_id = l.id AND "
            + " AND ".join(recontacto_clauses) + ")"
        )
        params.extend(recontacto_params)

    # V086 — Filtro unificado "tocado por proveedor". OR entre dos
    # condiciones: el proveedor X aparece como origen del lead (api_client_id
    # en crm.leads) o como autor de algun recontacto (api_client_id en
    # crm.lead_recontactos). Cubre el caso de uso "muestrame TODO lo que
    # toco wedo" sin que el marketing tenga que hacer 2 busquedas y unirlas.
    # Reemplaza la combinacion api_client_id + recontacto_api_client_id
    # cuando lo que el user quiere es la UNION, no la INTERSECCION.
    if filters.tocado_por_api_client_id:
        parts.append(
            "(l.api_client_id = %s::uuid "
            "OR EXISTS (SELECT 1 FROM crm.lead_recontactos r2 "
            "WHERE r2.lead_id = l.id AND r2.api_client_id = %s::uuid))"
        )
        params.append(filters.tocado_por_api_client_id)
        params.append(filters.tocado_por_api_client_id)

    # Filtro por alertas operacionales de llamadas pendientes
    if filters.filtro_alerta:
        fa = filters.filtro_alerta.strip().lower()
        if fa in ("urgentes", "sin_contacto_48h", "urgente"):
            parts.append(
                "("
                "l.created_at < NOW() - INTERVAL '48 hours' "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM crm.contactos c WHERE c.lead_id = l.id AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion') "
                "  UNION ALL "
                "  SELECT 1 FROM crm.llamadas ll WHERE ll.lead_id = l.id"
                ")"
                ")"
            )
        elif fa in ("sla_15m", "sla_vencido", "sla"):
            parts.append(
                "("
                "((l.sla_15m_cumplido = FALSE OR l.sla_15m_notificado_at IS NOT NULL) "
                " OR (l.created_at < NOW() - INTERVAL '15 minutes' AND l.created_at > NOW() - INTERVAL '48 hours')) "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM crm.contactos c WHERE c.lead_id = l.id AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion') "
                "  UNION ALL "
                "  SELECT 1 FROM crm.llamadas ll WHERE ll.lead_id = l.id"
                ")"
                ")"
            )
        elif fa in ("pendientes", "pendientes_seguimiento", "mi_dia", "pendientes_mi_dia"):
            parts.append(
                "("
                "l.estado_id NOT IN ("
                "  SELECT id FROM crm.estados_lead "
                "  WHERE es_final = TRUE OR nombre IN ('Ganado', 'Perdido', 'No interesado', 'Histórico', 'Historico')"
                ") "
                "AND ("
                "  ("
                "    UPPER(COALESCE(l.calidad, '')) = 'CALIENTE' "
                "    AND COALESCE(("
                "      SELECT MAX(ts) FROM ("
                "        SELECT created_at AS ts FROM crm.contactos WHERE lead_id = l.id AND tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion') "
                "        UNION ALL "
                "        SELECT fecha_llamada FROM crm.llamadas WHERE lead_id = l.id"
                "      ) _all"
                "    ), l.created_at) < NOW() - INTERVAL '24 hours'"
                "  ) "
                "  OR ("
                "    COALESCE(("
                "      SELECT MAX(ts) FROM ("
                "        SELECT created_at AS ts FROM crm.contactos WHERE lead_id = l.id AND tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion') "
                "        UNION ALL "
                "        SELECT fecha_llamada FROM crm.llamadas WHERE lead_id = l.id"
                "      ) _all"
                "    ), l.created_at) < NOW() - INTERVAL '48 hours'"
                "  )"
                ")"
                ")"
            )

    # V124: Filtro por estado de Ficha Técnica
    if filters.ficha_tecnica_estado:
        fte = filters.ficha_tecnica_estado.lower().strip()
        if fte in ("pendiente", "incompleta"):
            parts.append("COALESCE(l.ficha_tecnica_completada, FALSE) = FALSE")
        elif fte == "completa":
            parts.append("COALESCE(l.ficha_tecnica_completada, FALSE) = TRUE")

    # Filtro por estado de próxima gestión ('vencidas', 'sin_fecha', 'hoy', 'al_dia' / 'futuras')
    if filters.filtro_fecha_gestion:
        ffg = filters.filtro_fecha_gestion.strip().lower()
        if ffg in ("vencidas", "vencido", "overdue"):
            parts.append("(l.fecha_proxima_gestion IS NOT NULL AND l.fecha_proxima_gestion < NOW())")
        elif ffg in ("sin_fecha", "sin_asignar", "sin_programar", "none"):
            parts.append("l.fecha_proxima_gestion IS NULL")
        elif ffg in ("hoy", "today"):
            parts.append("((l.fecha_proxima_gestion AT TIME ZONE 'America/Lima')::date = (NOW() AT TIME ZONE 'America/Lima')::date)")
        elif ffg in ("al_dia", "futuras", "futuro", "upcoming"):
            parts.append("(l.fecha_proxima_gestion IS NOT NULL AND l.fecha_proxima_gestion >= NOW())")

    # Subfiltros para Citas Agendadas: según fecha de cita
    if filters.filtro_fecha_cita:
        ffc = filters.filtro_fecha_cita.strip().lower()
        cita_fecha_expr = """COALESCE(
            (
                SELECT c.fecha_cita
                FROM crm.contactos c
                WHERE c.lead_id = l.id AND c.fecha_cita IS NOT NULL
                ORDER BY c.created_at DESC, c.id DESC
                LIMIT 1
            ),
            l.fecha_proxima_gestion
        )"""
        if ffc in ("vencidas", "vencido", "overdue"):
            parts.append(f"({cita_fecha_expr} IS NOT NULL AND {cita_fecha_expr} < NOW())")
        elif ffc in ("sin_fecha", "sin_asignar", "sin_programar", "none"):
            parts.append(f"({cita_fecha_expr} IS NULL)")
        elif ffc in ("hoy", "today"):
            parts.append(f"(({cita_fecha_expr} AT TIME ZONE 'America/Lima')::date = (NOW() AT TIME ZONE 'America/Lima')::date)")
        elif ffc in ("al_dia", "futuras", "futuro", "upcoming", "proximas"):
            parts.append(f"({cita_fecha_expr} IS NOT NULL AND {cita_fecha_expr} >= NOW())")

    # Subfiltros para Citas Agendadas: según si fue atendida o no
    if filters.filtro_cita_atendida:
        fca = filters.filtro_cita_atendida.strip().lower()
        cita_estado_expr = """(
            SELECT COALESCE(ce.codigo, 'pendiente')
            FROM crm.contactos c
            LEFT JOIN crm.cita_estados ce ON ce.id = c.cita_estado_id
            WHERE c.lead_id = l.id AND c.fecha_cita IS NOT NULL
            ORDER BY c.created_at DESC, c.id DESC
            LIMIT 1
        )"""
        if fca in ("atendidas", "atendida", "completada", "completadas", "si", "true"):
            parts.append(f"({cita_estado_expr} IN ('completada', 'asistio', 'realizada', 'atendida'))")
        elif fca in ("no_atendidas", "no_atendida", "pendientes", "pendiente", "no", "false"):
            parts.append(
                f"({cita_estado_expr} IS NULL OR {cita_estado_expr} IN ('pendiente', 'reprogramada') "
                f"OR {cita_estado_expr} NOT IN ('completada', 'asistio', 'realizada', 'atendida', 'no_asistio', 'cancelada'))"
            )
        elif fca in ("no_asistio", "no_asistieron"):
            parts.append(f"({cita_estado_expr} = 'no_asistio')")
        elif fca in ("cancelada", "canceladas"):
            parts.append(f"({cita_estado_expr} = 'cancelada')")

    return " AND ".join(parts), params
