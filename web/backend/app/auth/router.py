"""
Auth router CRM.
- POST /auth/login  — login con email + password
- GET  /auth/me     — perfil del usuario actual
- GET  /auth/users  — listar usuarios (admin)
- PATCH /auth/users/{user_id}/role — cambiar rol (admin)
"""
import bcrypt
import logging
import secrets
from typing import Optional
from fastapi import APIRouter, HTTPException, status, Depends, Request, Query
from psycopg2.extras import RealDictCursor
from app.auth.schemas import LoginRequest, PermissionsRefreshResponse, TokenResponse, TokenData, UserResponse
from app.auth.jwt import create_access_token, get_current_user
from app.auth.permissions import check_permission
from app.auth.rate_limit import limiter
from app.config import settings
from app.database import get_db
from app.sql_utils import safe_set_clause

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Autenticación"])


def _verify_password(plain: str, hashed: str) -> bool:
    """Verifica password contra hash bcrypt (compatible con pgcrypto crypt())."""
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


from app.utils.url_helpers import resolve_public_base_url as _resolve_public_base_url  # noqa: E402


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
def login(request: Request, data: LoginRequest):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # ADR-0011 — LEFT JOIN auth.roles para traer permissions del rol
            # custom si el usuario tiene role_id. Si NULL, los campos quedan
            # en sus defaults (sin permisos custom, comportamiento legacy).
            cur.execute(
                """
                SELECT u.id::text, u.email, u.password_hash, u.role,
                       u.first_name, u.last_name, u.is_active,
                       COALESCE(u.login_blocked, FALSE) AS login_blocked,
                       u.default_wa_number_id,
                       u.role_id, u.api_client_id::text AS api_client_id,
                       r.permissions AS role_permissions,
                       r.is_external AS role_is_external
                FROM auth.users u
                LEFT JOIN auth.roles r ON r.id = u.role_id
                WHERE u.email = %s
                """,
                (data.email.lower().strip(),),
            )
            user = cur.fetchone()

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Credenciales incorrectas")

    if not user["is_active"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Usuario desactivado. Contacta al administrador.")

    # V094 — bloqueo de login independiente de is_active. El usuario sigue
    # visible en listas operacionales (rotacion, asignacion, equipos) pero
    # no puede entrar al CRM. Util para freeze rapido tipo "vacaciones" o
    # "investigacion en curso" sin romper el workflow del equipo.
    if user.get("login_blocked"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tu inicio de sesion esta bloqueado. Contacta al administrador.",
        )

    if not _verify_password(data.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Credenciales incorrectas")

    # ADR-0011 — snapshot del permissions del rol al momento del login.
    # Si el admin cambia permisos del rol después, los users logueados
    # ven el cambio recién al re-login (TTL del JWT controla la frescura).
    permissions = user.get("role_permissions") or {}
    role_is_external = bool(user.get("role_is_external"))
    role_id = user.get("role_id")
    api_client_id = user.get("api_client_id")

    # Validación: rol externo (proveedor) SIN api_client_id es inconsistente.
    if role_is_external and not api_client_id:
        logger.warning(
            "login bloqueado: user=%s tiene rol externo sin api_client_id",
            user["id"],
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Configuración inconsistente: rol externo requiere api_client_id. Contacta al administrador.",
        )

    # V088 — Bloqueo de cuenta sin acceso efectivo.
    # Si el admin asignó un rol custom con permissions={} a un usuario
    # NO admin (ej. rol "Sin Acceso"), la cuenta queda funcionalmente nula:
    # la UI no muestra módulos, las APIs devuelven 403, pero el usuario
    # podía entrar y ver una sesión vacía confusa. Cortamos en el login.
    #
    # Bypass: admin legacy (su rol siempre permite todo via Role.ADMIN).
    if (
        user["role"] != "admin"
        and role_id is not None
        and not permissions.get("_all")
        and not any(v is True for v in permissions.values())
    ):
        logger.warning(
            "login bloqueado: user=%s tiene role_id=%s sin permisos efectivos",
            user["id"], role_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Tu cuenta no tiene acceso al CRM. "
                "Contacta al administrador para que te asigne un rol con permisos."
            ),
        )

    nombre = f"{user['first_name'] or ''} {user['last_name'] or ''}".strip()
    token_payload = {
        "sub": user["id"],
        "email": user["email"],
        "role": user["role"],
        "permissions": permissions,
        "role_id": role_id,
        "role_is_external": role_is_external,
        "api_client_id": api_client_id,
    }
    token = create_access_token(token_payload)
    return TokenResponse(
        access_token=token,
        role=user["role"],
        user_id=user["id"],
        email=user["email"],
        nombre_completo=nombre or None,
        default_wa_number_id=user.get("default_wa_number_id"),
        permissions=permissions,
        role_id=role_id,
        role_is_external=role_is_external,
        api_client_id=api_client_id,
    )


@router.get("/me", response_model=UserResponse)
def me(current_user: TokenData = Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT u.id::text, u.email, u.first_name, u.last_name,
                       u.role, u.is_active,
                       COALESCE(u.login_blocked, FALSE) AS login_blocked,
                       u.telefono,
                       u.created_at::text AS created_at,
                       u.default_wa_number_id,
                       wn.display_name AS default_wa_number_name,
                       u.role_id, r.name AS role_name
                FROM auth.users u
                LEFT JOIN crm.wa_numbers wn ON wn.id = u.default_wa_number_id
                LEFT JOIN auth.roles r ON r.id = u.role_id
                WHERE u.id = %s::uuid
                """,
                (current_user.user_id,),
            )
            user = cur.fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return user


@router.get("/me/permissions", response_model=PermissionsRefreshResponse)
def me_permissions(current_user: TokenData = Depends(get_current_user)):
    """Live Permission Refresh (ADR-0011).

    Devuelve el snapshot actual de permisos del usuario leyendo directo
    de DB Y un access_token nuevo con esos permisos embebidos. El frontend
    DEBE reemplazar su token despues de llamar este endpoint.

    Por que reemplazar el token? Los chequeos de permisos del backend
    (check_permission, mask_record FLS) leen `permissions` del JWT decoded,
    no de DB en cada request (decision de performance). Si solo refrescamos
    el snapshot del cliente sin renovar el token, el backend sigue viendo
    permisos viejos hasta el proximo login. Esto causaba el bug donde
    Live Refresh actualizaba la UI pero las llamadas API seguian
    enmascarando con la config vieja.

    Si el usuario fue desactivado o eliminado entre el login y este
    refresh, devolvemos 401 para forzar logout en el cliente.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # V5.73.4 — Fallback al rol built-in cuando u.role_id IS NULL.
            # Sin esto, los usuarios legacy (creados antes del backfill de V078
            # o creados despues sin asignar role_id) heredaban permissions={}
            # vacio y los cambios del admin en el rol built-in 'asesor' (o
            # 'supervisor') NO se aplicaban al usuario. Bug reportado por el
            # user: 'quito reportes.view del rol asesor desde la web pero los
            # asesores siguen viendo Reportes en la app/web'.
            #
            # La segunda LEFT JOIN busca el rol built-in cuyo name coincida
            # con u.role (string legacy). COALESCE prioriza el rol custom
            # (role_id) si existe; solo cae al built-in si role_id IS NULL.
            cur.execute(
                """
                SELECT u.email, u.role, u.is_active,
                       COALESCE(u.login_blocked, FALSE) AS login_blocked,
                       u.api_client_id::text AS api_client_id,
                       u.role_id,
                       COALESCE(r.name,        builtin.name)        AS role_name,
                       COALESCE(r.permissions, builtin.permissions) AS role_permissions,
                       COALESCE(r.is_external, builtin.is_external, FALSE) AS role_is_external
                FROM auth.users u
                LEFT JOIN auth.roles r ON r.id = u.role_id
                LEFT JOIN auth.roles builtin
                    ON builtin.is_builtin = TRUE
                   AND builtin.name = u.role
                WHERE u.id = %s::uuid
                """,
                (current_user.user_id,),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado. Vuelve a iniciar sesion.",
        )
    if not row["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario desactivado. Contacta al administrador.",
        )
    # V094 — si el admin bloqueo el login del usuario mientras tenia sesion
    # activa, este refresh es la oportunidad para echarlo del cliente.
    if row.get("login_blocked"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tu inicio de sesion fue bloqueado. Contacta al administrador.",
        )

    permissions = row.get("role_permissions") or {}
    role_id = row.get("role_id")
    role_is_external = bool(row.get("role_is_external"))
    api_client_id = row.get("api_client_id")

    # Emitir JWT nuevo con los permisos frescos. Misma estructura que el
    # token de /auth/login para que el backend no distinga origen.
    new_token = create_access_token({
        "sub": current_user.user_id,
        "email": row.get("email") or current_user.email,
        "role": row["role"],
        "permissions": permissions,
        "role_id": role_id,
        "role_is_external": role_is_external,
        "api_client_id": api_client_id,
    })

    return PermissionsRefreshResponse(
        access_token=new_token,
        permissions=permissions,
        role=row["role"],
        role_id=role_id,
        role_name=row.get("role_name"),
        role_is_external=role_is_external,
        api_client_id=api_client_id,
    )


@router.get("/users", response_model=list[UserResponse])
def list_users(
    role: Optional[str] = Query(None),
    current_user: TokenData = Depends(check_permission("usuarios.manage", "supervisor", "asignacion.manage")),
):
    """
    Lista usuarios con scoping por rol y alcance de permisos:
    - admin / usuarios.manage / asignacion global → ve todos.
    - supervisor (equipo)                        → ve sus asesores (crm.equipos) + sí mismo + otros supervisores activos.
    - asignacion personalizado                   → ve usuarios en allowed_users + sí mismo.
    - asesor con asignacion de equipo             → ve el supervisor de su equipo + compañeros del equipo + sí mismo.
    - asesor sin permisos                         → 403 (via dependency).
    Filtro opcional ?role=asesor|supervisor|admin.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            where = ["1=1"]
            params: list = []

            perms = current_user.permissions or {}
            is_admin = current_user.role == "admin" or perms.get("_all") is True
            can_assign = perms.get("asignacion.manage") is True or current_user.role == "supervisor"
            scope = perms.get("asignacion.scope") or "equipo"
            allowed_users = perms.get("asignacion.allowed_users") or []

            if is_admin or perms.get("usuarios.manage") is True or (can_assign and scope == "global"):
                # Visibilidad total
                pass
            elif can_assign and scope == "personalizado" and allowed_users:
                where.append("(u.id = ANY(%s::uuid[]) OR u.id = %s::uuid)")
                params.extend([allowed_users, current_user.user_id])
            elif current_user.role == "supervisor":
                # Asesores del propio equipo + asesores de supervisores subordinados + self + otros supervisores activos
                where.append(
                    """(
                        u.id IN (
                            SELECT eq.asesor_id FROM crm.equipos eq
                            WHERE (
                                eq.supervisor_id = %s::uuid
                                OR eq.supervisor_id IN (
                                    SELECT s.id FROM auth.users s
                                    WHERE s.supervisor_jefe_id = %s::uuid AND s.is_active = TRUE AND s.role = 'supervisor'
                                )
                            ) AND eq.activo = TRUE
                        )
                        OR u.id = %s::uuid
                        OR (u.role = 'supervisor' AND u.is_active = TRUE)
                    )"""
                )
                params.extend([current_user.user_id, current_user.user_id, current_user.user_id])
            else:
                # Asesor o rol encapsulado a su equipo:
                # Miembros de su equipo: su supervisor ("sea supervisor o no") + compañeros + self
                where.append(
                    """(
                        u.id = %s::uuid
                        OR u.id IN (
                            SELECT eq.supervisor_id FROM crm.equipos eq
                            WHERE eq.asesor_id = %s::uuid AND eq.activo = TRUE
                        )
                        OR u.id IN (
                            SELECT eq2.asesor_id FROM crm.equipos eq1
                            JOIN crm.equipos eq2 ON eq1.supervisor_id = eq2.supervisor_id
                            WHERE eq1.asesor_id = %s::uuid AND eq1.activo = TRUE AND eq2.activo = TRUE
                        )
                    )"""
                )
                params.extend([current_user.user_id, current_user.user_id, current_user.user_id])

            if role:
                where.append("u.role = %s")
                params.append(role)

            cur.execute(
                f"""
                SELECT u.id::text, u.email, u.first_name, u.last_name,
                       u.role, u.is_active,
                       COALESCE(u.login_blocked, FALSE) AS login_blocked,
                       u.telefono,
                       u.created_at::text AS created_at,
                       u.default_wa_number_id,
                       wn.display_name AS default_wa_number_name,
                       -- ADR-0011 — rol custom (NULL si solo legacy)
                       u.role_id, r.name AS role_name,
                       u.supervisor_jefe_id::text AS supervisor_jefe_id,
                       TRIM(COALESCE(sj.first_name,'') || ' ' || COALESCE(sj.last_name,'')) AS supervisor_jefe_nombre
                FROM auth.users u
                LEFT JOIN crm.wa_numbers wn ON wn.id = u.default_wa_number_id
                LEFT JOIN auth.roles r ON r.id = u.role_id
                LEFT JOIN auth.users sj ON sj.id = u.supervisor_jefe_id
                WHERE {' AND '.join(where)}
                ORDER BY u.role, u.first_name
                """,
                params,
            )
            return cur.fetchall()


from pydantic import BaseModel

class RoleUpdateRequest(BaseModel):
    role: str


class UserCreate(BaseModel):
    email: str
    password: str
    first_name: str = ""
    last_name: str = ""
    role: str = "asesor"
    role_id: Optional[int] = None  # ADR-0011 — rol custom (auth.roles.id)
    telefono: str = ""


@router.post("/users", status_code=201)
def create_user(data: UserCreate, admin: TokenData = Depends(check_permission("usuarios.manage"))):
    if data.role not in ("admin", "supervisor", "asesor"):
        raise HTTPException(status_code=400, detail="Rol inválido")
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="Contraseña mínimo 6 caracteres")

    # ADR-0011 — validar role_id si vino, evitar usuario inconsistente
    if data.role_id is not None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, name, is_external FROM auth.roles WHERE id = %s",
                    (data.role_id,),
                )
                role_row = cur.fetchone()
                if not role_row:
                    raise HTTPException(status_code=400, detail="role_id no existe en auth.roles")
                if role_row["is_external"]:
                    # Rol externo requiere api_client_id en una segunda llamada o
                    # asignación previa. En este endpoint no aceptamos crear externos
                    # directamente porque no hay UI para mapear el api_client_id aún.
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "Los roles externos requieren vincular el usuario a un "
                            "proveedor (api_client_id). Crea el usuario con un rol "
                            "interno y luego asignale el proveedor desde la pantalla "
                            "del proveedor."
                        ),
                    )

    password_hash = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode()

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM auth.users WHERE email = %s", (data.email.lower(),))
            if cur.fetchone():
                raise HTTPException(status_code=409, detail="El email ya está registrado")
            cur.execute(
                """
                INSERT INTO auth.users
                    (id, email, password_hash, first_name, last_name, role, role_id,
                     is_active, telefono, created_at, updated_at)
                VALUES (uuid_generate_v1(), %s, %s, %s, %s, %s, %s, TRUE, %s, NOW(), NOW())
                RETURNING id::text
                """,
                (data.email.lower(), password_hash, data.first_name, data.last_name,
                 data.role, data.role_id, data.telefono or None),
            )
            new_id = cur.fetchone()["id"]
        conn.commit()
    return {"id": new_id, "message": "Usuario creado"}


class UserActiveUpdate(BaseModel):
    is_active: bool


class UserLoginBlockedUpdate(BaseModel):
    login_blocked: bool


@router.get("/users/{user_id}/active-leads-count", status_code=200)
def get_user_active_leads_count(
    user_id: str,
    admin: TokenData = Depends(check_permission("usuarios.manage")),
):
    """V090 — Devuelve cuántos leads activos tiene asignados el usuario.

    Pre-check para el flujo de deshabilitar: si > 0, el admin tiene que
    decidir qué hacer con esos leads antes de cortar el acceso (patrón
    estándar de la industria — sin esto los leads quedan huérfanos).

    Solo cuenta leads con `activo=TRUE` (no soft-deleted) y asignados
    directamente al user via `asesor_id`. Los leads que el user solo
    "contactó" pero no posee no se cuentan.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM crm.leads
                WHERE asesor_id = %s::uuid AND activo = TRUE
                """,
                (user_id,),
            )
            row = cur.fetchone()
    return {"count": int(row["n"] if isinstance(row, dict) else row[0])}


class ReassignLeadsRequest(BaseModel):
    # Modo de reasignacion:
    #   - "supervisor": al supervisor del equipo del user (asesor_id=NULL, supervisor_id=equipo.supervisor)
    #   - "asesor":     a un asesor especifico (asesor_id=target_user_id)
    #   - "unassign":   leads quedan sin asesor ni supervisor
    #   - "keep":       no toca nada (advertir al admin que quedan huérfanos)
    mode: str
    target_user_id: Optional[str] = None  # solo para mode="asesor"


@router.post("/users/{user_id}/reassign-leads", status_code=200)
def reassign_user_leads(
    user_id: str,
    data: ReassignLeadsRequest,
    request: Request,
    admin: TokenData = Depends(check_permission("usuarios.manage")),
):
    """V090 — Reasigna los leads activos del usuario en bulk.

    Patrón estándar de la industria: cuando un usuario se va de la empresa
    (lo deshabilitamos), sus leads no pueden quedar huérfanos. Este
    endpoint es atómico: o reasigna TODO o no toca nada.

    Modos:
      - supervisor: leads vuelven a la cola del supervisor del equipo del
        user (asesor_id=NULL, supervisor_id=equipo.supervisor). El
        supervisor decide después qué hacer.
      - asesor: transfer directo a otro asesor especifico (target_user_id).
      - unassign: asesor_id=NULL, supervisor_id=NULL → quedan en "Sin asignar".
      - keep: no-op (devuelve count=0). El admin acepta que queden huérfanos.

    Devuelve {reassigned: int, mode: str, target_name?: str}.
    """
    if data.mode not in ("supervisor", "asesor", "unassign", "keep"):
        raise HTTPException(status_code=400, detail="mode inválido")

    if data.mode == "keep":
        return {"reassigned": 0, "mode": "keep", "target_name": None}

    if data.mode == "asesor" and not data.target_user_id:
        raise HTTPException(
            status_code=400,
            detail="Modo 'asesor' requiere target_user_id",
        )

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Verificar que el user origen existe.
            cur.execute(
                """
                SELECT id::text AS id, email,
                       TRIM(COALESCE(first_name,'') || ' ' || COALESCE(last_name,'')) AS nombre
                FROM auth.users WHERE id = %s::uuid
                """,
                (user_id,),
            )
            origin = cur.fetchone()
            if not origin:
                raise HTTPException(status_code=404, detail="Usuario origen no encontrado")

            target_name: Optional[str] = None
            new_asesor_id: Optional[str] = None
            new_supervisor_id: Optional[str] = None

            if data.mode == "asesor":
                # Verificar target activo y rol válido.
                cur.execute(
                    """
                    SELECT id::text AS id, role, is_active,
                           TRIM(COALESCE(first_name,'') || ' ' || COALESCE(last_name,'')) AS nombre
                    FROM auth.users WHERE id = %s::uuid
                    """,
                    (data.target_user_id,),
                )
                target = cur.fetchone()
                if not target:
                    raise HTTPException(status_code=400, detail="Target user no encontrado")
                if not target["is_active"]:
                    raise HTTPException(status_code=400, detail="El usuario destino está deshabilitado")
                if target["role"] not in ("asesor", "supervisor", "admin"):
                    raise HTTPException(status_code=400, detail="El usuario destino no puede recibir leads")
                new_asesor_id = target["id"]
                # supervisor_id derivado del equipo del nuevo asesor (si tiene).
                cur.execute(
                    """
                    SELECT supervisor_id::text AS supervisor_id
                    FROM crm.equipos
                    WHERE asesor_id = %s::uuid AND activo = TRUE
                    LIMIT 1
                    """,
                    (new_asesor_id,),
                )
                eq = cur.fetchone()
                new_supervisor_id = eq["supervisor_id"] if eq else None
                target_name = target["nombre"] or "(sin nombre)"

            elif data.mode == "supervisor":
                # Buscar el supervisor del equipo del user origen.
                cur.execute(
                    """
                    SELECT s.id::text AS id,
                           TRIM(COALESCE(s.first_name,'') || ' ' || COALESCE(s.last_name,'')) AS nombre
                    FROM crm.equipos eq
                    JOIN auth.users s ON s.id = eq.supervisor_id
                    WHERE eq.asesor_id = %s::uuid
                      AND eq.activo = TRUE
                      AND s.is_active = TRUE
                    LIMIT 1
                    """,
                    (user_id,),
                )
                sup = cur.fetchone()
                if not sup:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "El usuario no tiene supervisor de equipo asignado. "
                            "Elige otro modo de reasignación."
                        ),
                    )
                new_asesor_id = None
                new_supervisor_id = sup["id"]
                target_name = sup["nombre"] or "(sin nombre)"

            # mode == "unassign" → ambos en NULL.

            # V091 — Tracking de herencia: dejamos constancia en cada lead de
            # quién era el dueño antes y cuándo se reasignó. Permite mostrar
            # el badge "Heredado de Fernando · hace 3 días" en la card del
            # lead durante 30 días, sin tener que consultar el audit log.
            cur.execute(
                """
                UPDATE crm.leads
                   SET asesor_id          = %s::uuid,
                       supervisor_id      = CASE WHEN %s = 'unassign' THEN NULL ELSE COALESCE(%s::uuid, supervisor_id) END,
                       previous_asesor_id = %s::uuid,
                       reassigned_at      = NOW(),
                       updated_at         = NOW()
                 WHERE asesor_id = %s::uuid
                   AND activo = TRUE
                RETURNING id
                """,
                (new_asesor_id, data.mode, new_supervisor_id, user_id, user_id),
            )
            updated = cur.fetchall()
            reassigned = len(updated)
        conn.commit()

    # Audit fail-safe.
    from app.services import permission_audit_service as _audit
    try:
        _audit._insert(
            actor=admin,
            action="user.reassign_leads",
            target_kind="user",
            target_id=user_id,
            target_label=origin.get("email"),
            before={"asesor_id": user_id},
            after={
                "mode": data.mode,
                "new_asesor_id": new_asesor_id,
                "new_supervisor_id": new_supervisor_id,
                "reassigned": reassigned,
            },
            request=request,
        )
    except Exception:  # noqa: BLE001
        logger.warning("audit fallo en reassign_user_leads", exc_info=True)

    return {
        "reassigned": reassigned,
        "mode": data.mode,
        "target_name": target_name,
    }


@router.patch("/users/{user_id}/active", status_code=200)
def update_user_active(
    user_id: str,
    data: UserActiveUpdate,
    request: Request,
    admin: TokenData = Depends(check_permission("usuarios.manage")),
):
    """V088 — Soft-disable de un usuario (is_active=false) o re-habilitarlo.

    Patrón estándar de la industria: en lugar del DELETE destructivo (que
    pierde historial), el admin marca al usuario como inactivo. Efectos:

      - El usuario no puede iniciar sesión (login devuelve 403 con
        "Usuario desactivado. Contacta al administrador.")
      - Desaparece de TODOS los listados de supervisores / asesores que
        filtran por `is_active = TRUE` (rotación, dropdowns de asignación,
        equipos, dashboards, etc.)
      - Sus leads asignados quedan donde estaban — el admin decide qué
        hacer con ellos por separado.
      - El historial (contactos, eventos, audits) se preserva intacto.

    Re-activación: misma operación con `is_active=true`. El usuario puede
    volver a entrar sin perder nada.

    Audit: registrado en auth.permission_audit_log con la acción
    `user.deactivate` / `user.activate`.
    """
    if user_id == admin.user_id:
        raise HTTPException(
            status_code=400,
            detail="No puedes deshabilitar tu propio usuario. Pídele a otro admin que lo haga.",
        )

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id::text AS id, email, is_active FROM auth.users WHERE id = %s::uuid",
                (user_id,),
            )
            prev = cur.fetchone()
            if not prev:
                raise HTTPException(status_code=404, detail="Usuario no encontrado")

            new_active = bool(data.is_active)
            if bool(prev["is_active"]) == new_active:
                # No-op: ya está en el estado solicitado. Devolvemos 200 igual
                # para que el cliente no tenga que diferenciar — idempotente.
                return {
                    "message": (
                        "El usuario ya estaba habilitado."
                        if new_active
                        else "El usuario ya estaba deshabilitado."
                    ),
                    "is_active": new_active,
                }

            cur.execute(
                "UPDATE auth.users SET is_active = %s, updated_at = NOW() WHERE id = %s::uuid",
                (new_active, user_id),
            )

            # Si lo deshabilitamos, invalidamos todas las sesiones activas
            # para que no pueda seguir operando con su JWT actual.
            if not new_active:
                try:
                    cur.execute(
                        "DELETE FROM auth.user_sessions WHERE user_id = %s::uuid",
                        (user_id,),
                    )
                except Exception:  # noqa: BLE001
                    # auth.user_sessions puede no existir en tenants legacy —
                    # no rompemos el deshabilitar por eso.
                    conn.rollback()
                    cur.execute(
                        "UPDATE auth.users SET is_active = %s, updated_at = NOW() WHERE id = %s::uuid",
                        (new_active, user_id),
                    )
        conn.commit()

    # Audit fail-safe (record_user_active_change ya silencia internamente).
    from app.services import permission_audit_service as _audit
    _audit.record_user_active_change(
        actor=admin,
        target_user_id=user_id,
        target_user_email=prev.get("email"),
        before_active=bool(prev["is_active"]),
        after_active=new_active,
        request=request,
    )

    return {
        "message": (
            "Usuario habilitado. Ya puede iniciar sesión."
            if new_active
            else "Usuario deshabilitado. No podrá iniciar sesión ni aparecer en listas."
        ),
        "is_active": new_active,
    }


@router.patch("/users/{user_id}/login-blocked", status_code=200)
def update_user_login_blocked(
    user_id: str,
    data: UserLoginBlockedUpdate,
    request: Request,
    admin: TokenData = Depends(check_permission("usuarios.manage")),
):
    """V094 — Bloqueo / desbloqueo del login independiente de is_active.

    A diferencia de `update_user_active`, esta accion NO saca al usuario
    de las listas operacionales (rotacion, asignacion, equipos, dropdowns).
    Solo le impide iniciar sesion en el CRM. Util para:

      - Freeze rapido tipo "vacaciones" sin afectar la operacion del equipo.
      - Cortar acceso mientras se investiga algo, sin reasignar leads.
      - Supervisores que deben seguir visibles para sus asesores pero no
        deben entrar al CRM por un periodo.

    Efectos al bloquear:
      - El login devuelve 403 con "Tu inicio de sesion esta bloqueado".
      - Las sesiones activas se invalidan (DELETE en auth.user_sessions).
      - El JWT actual del usuario sigue valido HASTA su proximo refresh
        (entonces /auth/me/permissions tambien rechaza). Tiempo maximo
        de exposicion = TTL del access_token.
      - El usuario sigue apareciendo en TODOS los listados, equipos,
        rotacion, dashboards, etc.

    Desbloqueo: misma operacion con `login_blocked=false`.

    Audit: registrado en auth.permission_audit_log con accion
    `user.login_block` / `user.login_unblock`.
    """
    if user_id == admin.user_id:
        raise HTTPException(
            status_code=400,
            detail="No puedes bloquear tu propio inicio de sesion. Pidele a otro admin que lo haga.",
        )

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id::text AS id, email,
                       COALESCE(login_blocked, FALSE) AS login_blocked
                FROM auth.users
                WHERE id = %s::uuid
                """,
                (user_id,),
            )
            prev = cur.fetchone()
            if not prev:
                raise HTTPException(status_code=404, detail="Usuario no encontrado")

            new_blocked = bool(data.login_blocked)
            if bool(prev["login_blocked"]) == new_blocked:
                # Idempotente: ya esta en el estado pedido.
                return {
                    "message": (
                        "El inicio de sesion ya estaba bloqueado."
                        if new_blocked
                        else "El inicio de sesion ya estaba desbloqueado."
                    ),
                    "login_blocked": new_blocked,
                }

            cur.execute(
                "UPDATE auth.users SET login_blocked = %s, updated_at = NOW() WHERE id = %s::uuid",
                (new_blocked, user_id),
            )

            # Al bloquear, cerramos sesiones activas para echar al usuario
            # del cliente de inmediato. Igual patron que update_user_active.
            if new_blocked:
                try:
                    cur.execute(
                        "DELETE FROM auth.user_sessions WHERE user_id = %s::uuid",
                        (user_id,),
                    )
                except Exception:  # noqa: BLE001
                    # auth.user_sessions puede no existir en tenants legacy.
                    conn.rollback()
                    cur.execute(
                        "UPDATE auth.users SET login_blocked = %s, updated_at = NOW() WHERE id = %s::uuid",
                        (new_blocked, user_id),
                    )
        conn.commit()

    # Audit fail-safe.
    from app.services import permission_audit_service as _audit
    _audit.record_user_login_blocked_change(
        actor=admin,
        target_user_id=user_id,
        target_user_email=prev.get("email"),
        before_blocked=bool(prev["login_blocked"]),
        after_blocked=new_blocked,
        request=request,
    )

    return {
        "message": (
            "Inicio de sesion bloqueado. El usuario sigue visible en las listas pero no podra entrar."
            if new_blocked
            else "Inicio de sesion desbloqueado. El usuario ya puede entrar de nuevo."
        ),
        "login_blocked": new_blocked,
    }


@router.delete("/users/{user_id}", status_code=200)
def delete_user(user_id: str, admin: TokenData = Depends(check_permission("usuarios.manage"))):
    if user_id == admin.user_id:
        raise HTTPException(status_code=400, detail="No puedes eliminar tu propio usuario")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM auth.users WHERE id = %s::uuid RETURNING id", (user_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Usuario no encontrado")
        conn.commit()
    return {"message": "Usuario eliminado"}


class InviteRequest(BaseModel):
    email: str
    role: str = "asesor"
    role_id: Optional[int] = None  # ADR-0011 — rol custom (auth.roles.id)


@router.post("/invite", status_code=201)
def create_invitation(request: Request, data: InviteRequest, admin: TokenData = Depends(check_permission("usuarios.manage"))):
    """Crea o regenera una invitación para el email dado. Devuelve la URL de invitación."""
    import psycopg2 as _psycopg2
    if data.role not in ("admin", "supervisor", "asesor"):
        raise HTTPException(status_code=400, detail="Rol inválido")
    if "@" not in data.email:
        raise HTTPException(status_code=400, detail="Email inválido")

    # ADR-0011 — validar role_id si vino
    if data.role_id is not None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, name, is_external FROM auth.roles WHERE id = %s",
                    (data.role_id,),
                )
                role_row = cur.fetchone()
                if not role_row:
                    raise HTTPException(status_code=400, detail="role_id no existe en auth.roles")
                if role_row["is_external"]:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "Los roles externos requieren vincular el usuario a un "
                            "proveedor (api_client_id). No se pueden enviar por invitación "
                            "directamente — créalo manualmente desde la pantalla del proveedor."
                        ),
                    )

    token = secrets.token_urlsafe(32)
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Crear tabla si no existe (idempotente). Sin CHECK constraint
                # estricto en `role` text — validación viaja a código para
                # soportar coexistencia legacy + custom (ADR-0011).
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS auth.invitations (
                        id          SERIAL      PRIMARY KEY,
                        email       TEXT        NOT NULL,
                        role        TEXT        NOT NULL DEFAULT 'asesor',
                        role_id     INTEGER     NULL REFERENCES auth.roles(id) ON DELETE SET NULL,
                        token       TEXT        NOT NULL UNIQUE,
                        invited_by  UUID        NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
                        expires_at  TIMESTAMPTZ NOT NULL,
                        accepted_at TIMESTAMPTZ,
                        created_at  TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                # V080: backward-compat — si la tabla ya existía sin role_id,
                # lo agregamos (idempotente).
                cur.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_schema = 'auth' AND table_name = 'invitations' AND column_name = 'role_id'
                        ) THEN
                            ALTER TABLE auth.invitations
                                ADD COLUMN role_id INTEGER NULL REFERENCES auth.roles(id) ON DELETE SET NULL;
                        END IF;
                    END $$;
                """)
                # Eliminar invitaciones anteriores no aceptadas para este email
                cur.execute(
                    "DELETE FROM auth.invitations WHERE email = %s AND accepted_at IS NULL",
                    (data.email.lower(),),
                )
                cur.execute(
                    """
                    INSERT INTO auth.invitations (email, role, role_id, token, invited_by, expires_at)
                    VALUES (%s, %s, %s, %s, %s::uuid, NOW() + INTERVAL '7 days')
                    """,
                    (data.email.lower(), data.role, data.role_id, token, admin.user_id),
                )
    except _psycopg2.Error as e:
        logger.error("Error DB en create_invitation: %s", e)
        raise HTTPException(status_code=500, detail=f"Error de base de datos: {e.pgcode or str(e)}")

    # Construir URL absoluta. Orden de precedencia:
    #   1) settings.public_base_url (mas confiable - configurado por el admin
    #      del CRM con el dominio canonico https://crm.<cliente>.com).
    #   2) X-Forwarded-Host + X-Forwarded-Proto (proxies tipo traefik/nginx
    #      que pasan estos headers — EasyPanel deberia pero no siempre).
    #   3) Fallback a request.base_url (puede devolver el host INTERNO del
    #      container de Docker, ej. http://brighton_crm-brighton:8002/ —
    #      INUTIL para emails de invitacion que el cliente abre en su navegador).
    base_url = _resolve_public_base_url(request)
    invite_url = f"{base_url}/invite?token={token}"

    # Obtener nombre del admin para el email
    admin_name = admin.email
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT first_name, last_name FROM auth.users WHERE id = %s::uuid",
                (admin.user_id,),
            )
            row = cur.fetchone()
            if row:
                name_parts = [row["first_name"] or "", row["last_name"] or ""]
                admin_name = " ".join(p for p in name_parts if p).strip() or admin.email

    # Enviar email de invitación
    from app.services.email_service import send_invitation_email
    email_sent = send_invitation_email(
        to=data.email.lower(),
        invite_url=invite_url,
        role=data.role,
        invited_by=admin_name,
    )

    return {
        "email_sent": email_sent,
        "invite_url": invite_url,
        "invite_email": data.email.lower(),
        "message": f"Invitación enviada a {data.email}" if email_sent else f"Invitación creada para {data.email} (sin email)",
    }


@router.get("/invitations")
def list_invitations(admin: TokenData = Depends(check_permission("usuarios.manage"))):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT i.id, i.email, i.role, i.token,
                       i.expires_at::text, i.accepted_at::text, i.created_at::text,
                       TRIM(COALESCE(u.first_name,'') || ' ' || COALESCE(u.last_name,'')) AS invited_by
                FROM auth.invitations i
                JOIN auth.users u ON u.id = i.invited_by
                ORDER BY i.created_at DESC
                """
            )
            return cur.fetchall()


@router.delete("/invitations/{invitation_id}", status_code=200)
def cancel_invitation(invitation_id: int, admin: TokenData = Depends(check_permission("usuarios.manage"))):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM auth.invitations WHERE id = %s RETURNING id", (invitation_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Invitación no encontrada")
        conn.commit()
    return {"message": "Invitación cancelada"}


@router.get("/invite/{token}", status_code=200)
@limiter.limit("20/minute")
def verify_invite_token(request: Request, token: str):
    """Verifica que un token de invitación sea válido y devuelve email + rol."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT email, role FROM auth.invitations
                WHERE token = %s AND accepted_at IS NULL AND expires_at > NOW()
                """,
                (token,),
            )
            inv = cur.fetchone()
    if not inv:
        raise HTTPException(status_code=404, detail="Invitación no válida o expirada")
    return {"email": inv["email"], "role": inv["role"]}


class AcceptInviteRequest(BaseModel):
    token: str
    password: str
    username: str = ""        # email (se ignora, se usa el del token)
    nombre_completo: str = ""


@router.post("/accept-invite", status_code=201)
@limiter.limit("5/minute")
def accept_invite(request: Request, data: AcceptInviteRequest):
    """Crea la cuenta del usuario invitado y marca la invitación como aceptada."""
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="Contraseña mínimo 6 caracteres")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Validar token. ADR-0011 — leemos role_id (NULL si invitación pre-V080
            # o si admin invitó con rol legacy). Tolerante a deploys donde
            # auth.invitations todavía no tiene la columna (queremos que el
            # ACCEPT no rompa por eso).
            try:
                cur.execute(
                    """
                    SELECT id, email, role, role_id FROM auth.invitations
                    WHERE token = %s AND accepted_at IS NULL AND expires_at > NOW()
                    """,
                    (data.token,),
                )
            except Exception:
                # Fallback: sin columna role_id (deploy mixto)
                conn.rollback()
                cur.execute(
                    """
                    SELECT id, email, role, NULL::integer AS role_id FROM auth.invitations
                    WHERE token = %s AND accepted_at IS NULL AND expires_at > NOW()
                    """,
                    (data.token,),
                )
            inv = cur.fetchone()
            if not inv:
                raise HTTPException(status_code=400, detail="Invitación no válida o expirada")

            # Verificar que el email no tenga ya una cuenta
            cur.execute("SELECT id FROM auth.users WHERE email = %s", (inv["email"],))
            if cur.fetchone():
                raise HTTPException(status_code=409, detail="Ya existe una cuenta con este email")

            # Parsear nombre completo
            parts = (data.nombre_completo or "").split(" ", 1)
            first_name = parts[0] if parts else ""
            last_name = parts[1] if len(parts) > 1 else ""

            # Crear usuario — ADR-0011: vincula role_id de la invitación si vino.
            password_hash = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode()
            cur.execute(
                """
                INSERT INTO auth.users
                    (id, email, password_hash, first_name, last_name, role, role_id,
                     is_active, created_at, updated_at)
                VALUES (uuid_generate_v1(), %s, %s, %s, %s, %s, %s, TRUE, NOW(), NOW())
                """,
                (inv["email"], password_hash, first_name, last_name, inv["role"], inv.get("role_id")),
            )

            # Marcar invitación como aceptada
            cur.execute(
                "UPDATE auth.invitations SET accepted_at = NOW() WHERE id = %s",
                (inv["id"],),
            )
    return {"message": "Cuenta creada exitosamente", "email": inv["email"]}


class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    telefono: Optional[str] = None
    # V035: admin puede asignar la linea WhatsApp por defecto al asesor.
    # 0 o null = sin linea asignada (usa default global al enviar).
    default_wa_number_id: Optional[int] = None


@router.patch("/users/{user_id}", status_code=200)
def update_user(user_id: str, data: UserUpdate, admin: TokenData = Depends(check_permission("usuarios.manage"))):
    import psycopg2 as _psycopg2

    # default_wa_number_id tiene semantica especial: 0/null = desasignar
    # (explicit), por eso no lo filtramos como los strings vacios.
    raw = data.model_dump(exclude_unset=True)
    fields: dict = {}
    for k, v in raw.items():
        if k == "default_wa_number_id":
            fields[k] = v if v else None   # 0 → NULL (desasignar)
        elif v is not None and v != "":
            fields[k] = v
    if not fields:
        raise HTTPException(status_code=400, detail="Sin campos a actualizar")

    # V087 — si el admin esta cambiando el email, normalizamos a lowercase
    # (matchea la conveccion del resto del sistema y evita colisiones por
    # mayusculas/minusculas en UNIQUE constraint).
    if "email" in fields:
        fields["email"] = fields["email"].strip().lower()

    _USER_COLUMNS = {"first_name", "last_name", "email", "telefono", "default_wa_number_id"}
    set_clause, set_params = safe_set_clause(fields, _USER_COLUMNS)
    params = set_params + [user_id]

    # V087 — pre-check de colision de email ANTES del UPDATE. Devuelve mensaje
    # claro con el nombre del usuario que ya tiene ese email, en vez de un
    # IntegrityError opaco. Reusa la misma logica del endpoint check-email.
    if "email" in fields:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id::text AS id,
                           TRIM(COALESCE(first_name,'') || ' ' || COALESCE(last_name,'')) AS nombre,
                           email
                    FROM auth.users
                    WHERE LOWER(email) = %s AND id <> %s::uuid
                    LIMIT 1
                    """,
                    (fields["email"], user_id),
                )
                conflict = cur.fetchone()
                if conflict:
                    nombre = (conflict.get("nombre") or "").strip() or conflict["email"]
                    raise HTTPException(
                        status_code=409,
                        detail=f"Ese correo ya está usado por otro usuario ({nombre}). Elige uno distinto.",
                    )

    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE auth.users SET {set_clause}, updated_at = NOW() WHERE id = %s::uuid RETURNING id",
                    params,
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Usuario no encontrado")
            conn.commit()
    except _psycopg2.errors.UniqueViolation:
        # Defense in depth: si por race condition (admin concurrente) el
        # pre-check paso pero el UPDATE colisiona, devolvemos 409 igual
        # en vez del 500 que devuelve FastAPI por default.
        raise HTTPException(
            status_code=409,
            detail="Ese correo ya está usado por otro usuario. Elige uno distinto.",
        )
    return {"message": "Usuario actualizado"}


@router.get("/users/check-email", status_code=200)
def check_email_availability(
    email: str = Query(..., min_length=3, max_length=120),
    exclude_user_id: Optional[str] = Query(None),
    admin: TokenData = Depends(check_permission("usuarios.manage")),
):
    """V087 — Verifica si un email esta disponible para usarse en un nuevo
    usuario o en una edicion.

    Args:
        email: el email a consultar (case-insensitive).
        exclude_user_id: UUID del usuario que se esta editando — su propio
            email no se considera "ocupado". Si es null, busca match exacto.

    Respuesta:
        {"available": bool, "owner_name": str|None, "owner_email": str|None}

    El owner_name solo viaja si available=False, para que el frontend pueda
    mostrar "Ese correo ya pertenece a Carlos Ramirez" inline mientras el
    admin tipea (UX de pre-check antes de submit).
    """
    normalized = email.strip().lower()
    if "@" not in normalized or "." not in normalized.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Email inválido")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if exclude_user_id:
                cur.execute(
                    """
                    SELECT id::text AS id,
                           TRIM(COALESCE(first_name,'') || ' ' || COALESCE(last_name,'')) AS nombre,
                           email
                    FROM auth.users
                    WHERE LOWER(email) = %s AND id <> %s::uuid
                    LIMIT 1
                    """,
                    (normalized, exclude_user_id),
                )
            else:
                cur.execute(
                    """
                    SELECT id::text AS id,
                           TRIM(COALESCE(first_name,'') || ' ' || COALESCE(last_name,'')) AS nombre,
                           email
                    FROM auth.users
                    WHERE LOWER(email) = %s
                    LIMIT 1
                    """,
                    (normalized,),
                )
            row = cur.fetchone()

    if not row:
        return {"available": True, "owner_name": None, "owner_email": None}

    nombre = (row.get("nombre") or "").strip()
    return {
        "available": False,
        "owner_name": nombre or None,
        "owner_email": row["email"],
    }


@router.post("/users/{user_id}/reset-link", status_code=200)
def generate_reset_link(user_id: str, admin: TokenData = Depends(check_permission("usuarios.manage"))):
    """Genera un token de reseteo de contraseña válido por 24 horas."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM auth.users WHERE id = %s::uuid", (user_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Usuario no encontrado")
            token = secrets.token_urlsafe(32)
            cur.execute(
                """
                INSERT INTO auth.password_resets (user_id, token, expires_at)
                VALUES (%s::uuid, %s, NOW() + INTERVAL '24 hours')
                """,
                (user_id, token),
            )
        conn.commit()
    return {"token": token}


@router.post("/users/{user_id}/send-reset-email", status_code=200)
@limiter.limit("10/hour")
def send_reset_email_to_user(
    user_id: str,
    request: Request,
    admin: TokenData = Depends(check_permission("usuarios.manage")),
):
    """V087 — Genera un token de reseteo y lo envia por correo al usuario.

    Reemplaza el patron previo de "Reenviar invitacion" para usuarios activos,
    que estaba roto: creaba una invitacion nueva, el usuario seguia link,
    poneia password y el backend tiraba 409 porque ya existia cuenta con
    ese email. La accion correcta para un usuario activo que olvido la
    pass es enviarle un correo de reset, no una invitacion.

    Audit log: cada llamada queda registrada en auth.audit_password_resets
    con actor, target, IP, user-agent, resultado SMTP y motivo del fallo si
    aplica. Cumplimiento Ley 29733 PE.

    Rate limit: 10/hora por IP del admin para evitar abuso. El rate limit
    por target user lo hace el SMTP del cliente (correo profesional/Outlook tiran 421
    si se repite el envio rapido).
    """
    from app.services.email_service import send_password_reset_email
    from app.services import password_reset_audit_service as _audit

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id::text AS id, email, first_name, last_name
                FROM auth.users
                WHERE id = %s::uuid
                """,
                (user_id,),
            )
            target = cur.fetchone()
            if not target:
                raise HTTPException(status_code=404, detail="Usuario no encontrado")

            token = secrets.token_urlsafe(32)
            cur.execute(
                """
                INSERT INTO auth.password_resets (user_id, token, expires_at)
                VALUES (%s::uuid, %s, NOW() + INTERVAL '24 hours')
                """,
                (user_id, token),
            )
        conn.commit()

    # Armar URL canonica del reset. Misma logica que la del invite (resuelve
    # public_base_url > X-Forwarded-Host > request.base_url).
    base_url = _resolve_public_base_url(request)
    reset_url = f"{base_url}/reset-password?token={token}"

    recipient_name = " ".join(
        p for p in [target.get("first_name") or "", target.get("last_name") or ""] if p
    ).strip()

    # Envio efectivo + registro del resultado en audit.
    result = send_password_reset_email(
        to=target["email"],
        reset_url=reset_url,
        recipient_name=recipient_name,
    )
    email_sent = bool(result.get("success"))
    smtp_error = result.get("error") if not email_sent else None

    _audit.record_send_reset_email(
        actor=admin,
        target_user_id=user_id,
        target_user_email=target["email"],
        email_sent=email_sent,
        smtp_error=smtp_error,
        request=request,
    )

    if not email_sent:
        # 502 Bad Gateway: el backend hizo su parte (token generado, audit
        # registrado) pero el SMTP del cliente fallo. El admin necesita
        # saber por que para arreglar la config — no devolvemos 500 generico.
        raise HTTPException(
            status_code=502,
            detail=(
                f"No se pudo enviar el correo: {smtp_error or 'error desconocido'}. "
                f"Verifica la configuración SMTP. Como alternativa, puedes copiar "
                f"manualmente el enlace de restablecimiento."
            ),
        )

    return {
        "email_sent": True,
        "message": f"Correo de restablecimiento enviado a {target['email']}",
        "target_email": target["email"],
    }


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password", status_code=200)
@limiter.limit("10/minute")
def change_password(request: Request, data: ChangePasswordRequest, current_user: TokenData = Depends(get_current_user)):
    """Cambiar contraseña del usuario autenticado."""
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="La nueva contraseña debe tener al menos 6 caracteres")
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT password_hash FROM auth.users WHERE id = %s::uuid",
                (current_user.user_id,),
            )
            user = cur.fetchone()
            if not user:
                raise HTTPException(status_code=404, detail="Usuario no encontrado")
            if not _verify_password(data.current_password, user["password_hash"]):
                raise HTTPException(status_code=400, detail="Contraseña actual incorrecta")
            password_hash = bcrypt.hashpw(data.new_password.encode(), bcrypt.gensalt()).decode()
            cur.execute(
                "UPDATE auth.users SET password_hash = %s, updated_at = NOW() WHERE id = %s::uuid",
                (password_hash, current_user.user_id),
            )
        conn.commit()
    return {"message": "Contraseña actualizada exitosamente"}


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/reset-password", status_code=200)
@limiter.limit("5/minute")
def reset_password(request: Request, data: ResetPasswordRequest):
    """Endpoint público: valida token y actualiza contraseña."""
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="Contraseña mínimo 6 caracteres")
    password_hash = bcrypt.hashpw(data.new_password.encode(), bcrypt.gensalt()).decode()
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT user_id FROM auth.password_resets WHERE token = %s AND used = FALSE AND expires_at > NOW()",
                (data.token,),
            )
            reset = cur.fetchone()
            if not reset:
                raise HTTPException(status_code=400, detail="Token inválido o expirado")
            cur.execute(
                "UPDATE auth.users SET password_hash = %s, updated_at = NOW() WHERE id = %s",
                (password_hash, reset["user_id"]),
            )
            cur.execute("UPDATE auth.password_resets SET used = TRUE WHERE token = %s", (data.token,))
        conn.commit()
    return {"message": "Contraseña actualizada exitosamente"}


@router.patch("/users/{user_id}/role", status_code=200)
def update_role(
    user_id: str,
    data: RoleUpdateRequest,
    request: Request,
    admin: TokenData = Depends(check_permission("usuarios.manage")),
):
    if data.role not in ("admin", "supervisor", "asesor"):
        raise HTTPException(status_code=400, detail="Rol inválido")
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Snapshot previo para el audit log.
            cur.execute(
                "SELECT email, role FROM auth.users WHERE id = %s::uuid",
                (user_id,),
            )
            prev = cur.fetchone()
            if not prev:
                raise HTTPException(status_code=404, detail="Usuario no encontrado")
            cur.execute(
                "UPDATE auth.users SET role = %s WHERE id = %s::uuid",
                (data.role, user_id),
            )
        conn.commit()
    # Audit del cambio de rol legacy (admin/supervisor/asesor). Para cambios
    # de role_id custom ver routers/roles.py::assign_to_user.
    if prev and prev["role"] != data.role:
        from app.services import permission_audit_service as _audit
        _audit.record_user_role_change(
            actor=admin,
            target_user_id=user_id,
            target_user_email=prev.get("email"),
            before_role_id=None,
            before_role_name=prev.get("role"),
            after_role_id=None,
            after_role_name=data.role,
            request=request,
        )
    return {"message": f"Rol actualizado a {data.role}"}


# ── Emergency reset ─────────────────────────────────────────────────────────

class EmergencyResetRequest(BaseModel):
    secret: str
    email: str
    new_password: str


@router.post("/emergency-reset", status_code=200)
@limiter.limit("3/hour")
def emergency_reset(request: Request, data: EmergencyResetRequest):
    """Reset de contraseña de emergencia — no requiere login.

    Protegido por:
      1. EMERGENCY_SECRET en .env (si está vacío, el endpoint devuelve 404)
      2. Rate limit estricto: 3 intentos por hora
      3. Comparación en tiempo constante contra timing attacks
    """
    if not settings.emergency_secret:
        raise HTTPException(status_code=404, detail="Not found")

    if not secrets.compare_digest(data.secret, settings.emergency_secret):
        logger.warning("Intento de emergency-reset fallido para %s", data.email)
        raise HTTPException(status_code=403, detail="Secret inválido")

    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="Contraseña mínimo 6 caracteres")

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, role FROM auth.users WHERE email = %s",
                (data.email.lower().strip(),),
            )
            user = cur.fetchone()
            if not user:
                raise HTTPException(status_code=404, detail="Usuario no encontrado")

            password_hash = bcrypt.hashpw(
                data.new_password.encode(), bcrypt.gensalt()
            ).decode()
            cur.execute(
                "UPDATE auth.users SET password_hash = %s, updated_at = NOW() "
                "WHERE id = %s",
                (password_hash, user["id"]),
            )
        conn.commit()

    # V061: no logueamos el email para no filtrar PII en logs centralizados.
    # El user_id + role son suficientes para auditoria forense.
    logger.info("Emergency reset ejecutado para user_id=%s (role=%s)", user["id"], user["role"])
    return {"message": f"Contraseña reseteada para {data.email}"}
