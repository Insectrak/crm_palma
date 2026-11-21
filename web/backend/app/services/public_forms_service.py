"""
Servicio de formularios públicos — reglas de negocio y orquestación.

SRP: esta capa contiene las *reglas* del dominio:
  - Quién puede crear/editar/archivar formularios (admin + supervisor).
  - Cómo se genera un slug único a partir del título.
  - Validación del payload entrante contra el `config` del form.
  - Lógica anti-spam (honeypot, min-time, rate limit por IP).
  - Enforce de `expires_at` y `max_submissions`.
  - Disparar notificación push al creador tras submit exitoso.

NO toca SQL directo (delegado al repository) ni HTTP (delegado al router).
El router depende de este módulo; este módulo depende del repository y de
notification_service, no al revés (DIP).
"""
from __future__ import annotations

import logging
import re
import secrets
import unicodedata
from typing import Any, Optional

from fastapi import HTTPException

from app.auth.schemas import TokenData
from app.config import settings
from app.constants import Role
from app.repositories import public_forms_repository as repo
from app.services.notification_service import notify_new_lead

logger = logging.getLogger(__name__)


# ── Constantes de dominio ─────────────────────────────────────────────────────

# Roles autorizados para crear/editar formularios públicos.
ALLOWED_ROLES_MANAGE = {Role.ADMIN.value, Role.SUPERVISOR.value}

# Campos conocidos del modelo crm.leads que un formulario puede pedir.
# Cualquier otro key en el config se ignora — blindaje contra inyección.
ALLOWED_LEAD_FIELDS = {
    "nombres", "apellidos", "telefono", "email", "dni", "observaciones",
}

# Campos que son obligatorios a nivel de negocio: aunque el creador del form
# los marque como opcionales en la UI, el backend exige al menos uno de
# contacto (telefono o email) para que el lead sea accionable.
MIN_CONTACT_FIELDS = {"telefono", "email"}

# Regex del slug — debe coincidir con el CHECK de la migración V021.
_SLUG_REGEX = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")
_SLUG_MAX_LEN = 80
_SLUG_MIN_LEN = 3
_SLUG_COLLISION_RETRIES = 5

# ── Reglas de validación canónica ────────────────────────────────────────────
#
# Estas reglas existen para que los datos lleguen a la BD YA normalizados:
# ningún consumidor downstream (WhatsApp/Evolution, reportes, dashboards,
# dedup de leads) tiene que transformar — lo que hay en la columna es
# exactamente lo que se muestra y se usa.

# Email: trimmed + lowercase; regex E-mail simple (RFC 5322 es overkill aquí).
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

# Teléfono: después de _normalize_phone() debe venir en formato E.164 estricto:
#   - Empieza con +
#   - Seguido de 8 a 15 dígitos (estándar E.164)
_PHONE_RE = re.compile(r"^\+\d{8,15}$")

# DNI peruano: 8 dígitos exactos.
_DNI_PE_RE = re.compile(r"^\d{8}$")

# Código de país por defecto cuando el lead escribe el teléfono sin prefijo.
# Ahora configurable vía settings.public_form_default_country_code (ver config.py).
# Se lee en cada llamada a _normalize_phone para respetar cambios sin reinicio
# completo del proceso Python (en la práctica el settings no cambia en runtime,
# pero mantener la lectura lazy evita estado global duplicado).
_PHONE_CLEAN_RE = re.compile(r"[\s\-()]")

# Límites de longitud para strings de texto libre (defensivos, alineados con
# los CHECK constraints de crm.leads en la BD).
_FIELD_MAX_LENGTHS = {
    "nombres":       120,
    "apellidos":     120,
    "telefono":      30,
    "email":         120,
    "dni":           20,
    "observaciones": 1000,
}

# Colapsa cualquier whitespace interno múltiple (espacios, tabs, saltos) a 1.
_WS_COLLAPSE_RE = re.compile(r"\s+")

# Anti-spam
#
# El nombre del campo honeypot se queda HARDCODED a propósito: si fuera
# configurable vía API/settings leído desde el frontend, un atacante podría
# leerlo y excluirlo trivialmente. El resto de thresholds viven en settings
# (config.py) para poder tunearlos por ambiente sin redeploy.
HONEYPOT_FIELD = "website"           # campo oculto en el form, debe venir vacío


# ── Helpers privados ─────────────────────────────────────────────────────────

def _normalize_slug_base(text: str) -> str:
    """Convierte un texto a una base de slug (sin sufijo de colisión).

    - Quita acentos (NFKD)
    - Pasa a minúsculas
    - Reemplaza todo lo que no sea [a-z0-9] por guión
    - Colapsa guiones consecutivos y recorta guiones al borde
    - Trunca a _SLUG_MAX_LEN
    """
    if not text:
        return ""
    # Normalizar y quitar diacríticos
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.lower()
    # Reemplazar chars no válidos por guión
    ascii_text = re.sub(r"[^a-z0-9]+", "-", ascii_text)
    # Colapsar guiones y recortar
    ascii_text = re.sub(r"-+", "-", ascii_text).strip("-")
    return ascii_text[:_SLUG_MAX_LEN]


def _generate_unique_slug(titulo: str) -> str:
    """Genera un slug único a partir del título, con retry si hay colisión.

    Si tras N intentos sigue colisionando, agrega un sufijo aleatorio largo
    para garantizar unicidad práctica. Si el título es muy corto o vacío,
    usa un slug completamente aleatorio.
    """
    base = _normalize_slug_base(titulo)
    if len(base) < _SLUG_MIN_LEN:
        # Título vacío o con solo chars no-ascii → slug random puro
        return f"form-{secrets.token_hex(4)}"

    # Primer intento: slug limpio
    if not repo.slug_exists(base):
        return base

    # Retries con sufijo corto
    for _ in range(_SLUG_COLLISION_RETRIES):
        suffix = secrets.token_hex(2)  # 4 hex chars
        candidate = f"{base[: _SLUG_MAX_LEN - 5]}-{suffix}"
        if not repo.slug_exists(candidate):
            return candidate

    # Último recurso: sufijo largo para forzar unicidad
    suffix = secrets.token_hex(4)
    candidate = f"{base[: _SLUG_MAX_LEN - 9]}-{suffix}"
    return candidate


def _ensure_can_manage(current_user: TokenData) -> None:
    """Gestionar formularios requiere el permiso `formularios.manage` (V093).

    Comportamiento por rol built-in (sin cambios respecto a V092):
      - admin:      bypass (tiene _all en seed V078)
      - supervisor: tiene formularios.manage = true en seed V078
      - asesor:     NO tiene el permiso por default → 403

    El admin puede otorgar el permiso a otros roles (incluyendo asesor)
    desde Configuración → Roles y permisos sin tocar código. Esto reemplaza
    el hardcodeo `ALLOWED_ROLES_MANAGE = {ADMIN, SUPERVISOR}` que existia
    antes de V093, manteniendo el comportamiento default identico pero
    habilitando flexibilidad por cliente (ej: Palma decide darle el permiso
    a un "asesor_senior").
    """
    # Import local para evitar circular import (auth.permissions importa
    # auth.schemas que a su vez importa cosas que terminan aca).
    from app.auth.permissions import has_permission
    if not has_permission(current_user, "formularios.manage"):
        raise HTTPException(
            status_code=403,
            detail="No tienes permiso para gestionar formularios públicos.",
        )


def _ensure_owns_or_admin(current_user: TokenData, form: dict) -> None:
    """El admin puede tocar cualquier form. El supervisor los suyos o asignados a él."""
    if current_user.role == Role.ADMIN.value:
        return
    if (
        str(form.get("created_by")) != current_user.user_id
        and str(form.get("asignado_a")) != current_user.user_id
    ):
        raise HTTPException(
            status_code=403,
            detail="No tienes permiso para modificar este formulario.",
        )


def _validate_assignee(current_user: TokenData, asignado_a: Optional[str]) -> str:
    """Valida que asignado_a sea un usuario válido y con permisos según el rol del creador.

    Si asignado_a es None o vacío, se asigna por defecto al creador (current_user.user_id).
    """
    if not asignado_a or not str(asignado_a).strip():
        return current_user.user_id

    assignee_id = str(asignado_a).strip()
    try:
        import uuid
        uuid.UUID(assignee_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail="asignado_a debe ser un UUID válido.")

    assignee = repo.get_user_by_id(assignee_id)
    if not assignee or not assignee.get("is_active"):
        raise HTTPException(status_code=422, detail="El usuario asignado no existe o está inactivo.")

    if current_user.role == Role.ADMIN.value:
        return assignee_id

    if current_user.user_id == assignee_id:
        return assignee_id

    eligible = repo.list_eligible_assignees(current_user)
    eligible_ids = {u["id"] for u in eligible}
    if assignee_id not in eligible_ids:
        raise HTTPException(
            status_code=403,
            detail="No tienes permiso para asignar este formulario a un usuario fuera de tu equipo.",
        )
    return assignee_id


def _validate_config(config: dict) -> dict:
    """Valida y normaliza el `config` de un form.

    Shape canónico devuelto:
    {
      "campos": [
        {"key": "nombres", "label": "Nombre", "required": True, "type": "text"}
      ],
      "mensaje_exito": "...",
      "redirect_url": None
    }

    - Ignora campos desconocidos (no en ALLOWED_LEAD_FIELDS).
    - Exige al menos un campo de contacto (telefono o email) requerido.
    - Normaliza flags y trunca strings para evitar payloads gigantes.
    """
    if not isinstance(config, dict):
        raise HTTPException(status_code=422, detail="config debe ser un objeto.")

    raw_campos = config.get("campos") or []
    if not isinstance(raw_campos, list) or not raw_campos:
        raise HTTPException(
            status_code=422,
            detail="El formulario debe incluir al menos un campo en config.campos.",
        )

    normalized: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    contact_required = False

    for idx, campo in enumerate(raw_campos):
        if not isinstance(campo, dict):
            raise HTTPException(
                status_code=422,
                detail=f"config.campos[{idx}] debe ser un objeto.",
            )
        key = str(campo.get("key", "")).strip().lower()
        if key not in ALLOWED_LEAD_FIELDS:
            # Silenciosamente ignoramos campos no soportados — es más amigable
            # que rechazar y permite evolución futura sin romper forms viejos.
            continue
        if key in seen_keys:
            raise HTTPException(
                status_code=422,
                detail=f"El campo '{key}' está duplicado en config.campos.",
            )
        seen_keys.add(key)
        label = str(campo.get("label") or key.capitalize()).strip()[:120]
        required = bool(campo.get("required", False))
        tipo = str(campo.get("type") or "text").strip().lower()[:20]
        if required and key in MIN_CONTACT_FIELDS:
            contact_required = True
        normalized.append({
            "key": key,
            "label": label,
            "required": required,
            "type": tipo,
        })

    if not normalized:
        raise HTTPException(
            status_code=422,
            detail="Ningún campo válido en config.campos (solo se aceptan: "
                   f"{sorted(ALLOWED_LEAD_FIELDS)}).",
        )
    if not contact_required:
        raise HTTPException(
            status_code=422,
            detail="Al menos un campo de contacto (telefono o email) debe ser requerido.",
        )

    mensaje_exito = str(
        config.get("mensaje_exito") or "¡Gracias! Pronto te contactaremos."
    ).strip()[:500]
    redirect_url = config.get("redirect_url")
    if redirect_url is not None:
        redirect_url = str(redirect_url).strip()[:500]
        if redirect_url and not (
            redirect_url.startswith("http://") or redirect_url.startswith("https://")
        ):
            raise HTTPException(
                status_code=422,
                detail="redirect_url debe comenzar con http:// o https://",
            )

    return {
        "campos": normalized,
        "mensaje_exito": mensaje_exito,
        "redirect_url": redirect_url or None,
    }


def _normalize_phone(raw: str) -> str:
    """Normaliza un teléfono a formato E.164 peruano (+51XXXXXXXXX).

    Casos soportados:
      - "941468455"        → "+51941468455"  (9 dígitos, móvil peruano)
      - "51941468455"      → "+51941468455"  (con código país sin +)
      - "+51 941-468-455"  → "+51941468455"  (con formato)
      - "+51941468455"     → "+51941468455"  (idempotente)
      - "+1234567890"      → "+1234567890"   (extranjero — se respeta)

    Si no puede normalizar (muy corto, muy largo, no dígitos), devuelve
    el valor original limpio para que la validación de formato lo rechace.
    """
    if not raw:
        return raw
    cleaned = _PHONE_CLEAN_RE.sub("", raw.strip())
    if not cleaned:
        return cleaned

    # Ya viene con +: respetamos tal cual (puede ser número extranjero)
    if cleaned.startswith("+"):
        return cleaned

    # Solo dígitos a partir de aquí
    if not cleaned.isdigit():
        return cleaned

    # Código de país por defecto (configurable vía settings, default "51" PE).
    default_cc = settings.public_form_default_country_code

    # Código país sin "+": "51XXXXXXXXX" (total = len(cc) + 9 para móvil PE)
    if cleaned.startswith(default_cc) and len(cleaned) == len(default_cc) + 9:
        return f"+{cleaned}"

    # Móvil peruano de 9 dígitos empezando por 9
    if len(cleaned) == 9 and cleaned.startswith("9"):
        return f"+{default_cc}{cleaned}"

    # Otros largos: asumimos nacional y prependemos el código de país default
    # (ej: fijo Lima 7 dígitos, fijo regional 8 dígitos).
    if 6 <= len(cleaned) <= 11:
        return f"+{default_cc}{cleaned}"

    # No identificable — devolvemos tal cual (fallará el regex check).
    return cleaned


def _canonicalize_name(value: str) -> str:
    """Nombres/apellidos: trim, colapsa whitespace interno, title-case.

    Convierte entradas como "  juan  PEDRO " → "Juan Pedro". Preserva
    caracteres unicode (acentos, ñ) porque `str.title()` ya los respeta.
    """
    collapsed = _WS_COLLAPSE_RE.sub(" ", value.strip())
    return collapsed.title() if collapsed else ""


def _canonicalize_observaciones(value: str) -> str:
    """Observaciones: trim extremos, colapsa saltos de línea múltiples a uno.

    No tocamos el contenido interno más allá de eso — es texto libre.
    """
    # Strip bordes, colapsa 3+ newlines a 2 (párrafos), deja 1-2 tal cual
    trimmed = value.strip()
    return re.sub(r"\n{3,}", "\n\n", trimmed)


def _validate_submission_payload(form: dict, payload: dict) -> dict:
    """Valida y canonicaliza el payload entrante contra el config del form.

    Devuelve un dict `lead_data` listo para pasar al repository, con TODOS
    los campos en formato canónico. Cualquier consumidor downstream puede
    confiar en que los datos no requieren más transformación:

      - nombres/apellidos → Title Case, whitespace colapsado
      - email             → lowercase, trimmed, formato E-mail válido
      - telefono          → E.164 estricto (+<código><número>)
      - dni               → 8 dígitos exactos (DNI peruano)
      - observaciones     → texto limpio, truncado

    Lanza HTTPException 422 si algún campo requerido falta o es inválido.
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="payload inválido")

    config = form.get("config") or {}
    campos = config.get("campos") or []
    if not campos:
        raise HTTPException(
            status_code=500,
            detail="El formulario no tiene campos configurados. Contacta al administrador.",
        )

    lead_data: dict[str, Any] = {k: None for k in ALLOWED_LEAD_FIELDS}

    # ── Paso 1: extraer valores + chequear required ────────────────────────
    for campo in campos:
        key = campo.get("key")
        if key not in ALLOWED_LEAD_FIELDS:
            continue
        raw = payload.get(key)
        if isinstance(raw, str):
            raw = raw.strip()
            if raw == "":
                raw = None
        if campo.get("required") and raw is None:
            raise HTTPException(
                status_code=422,
                detail=f"El campo '{campo.get('label') or key}' es obligatorio.",
            )
        lead_data[key] = raw

    # ── Paso 2: canonicalizar + validar formato campo por campo ────────────

    # nombres / apellidos → Title Case, whitespace colapsado
    for name_field in ("nombres", "apellidos"):
        val = lead_data.get(name_field)
        if isinstance(val, str):
            canonical = _canonicalize_name(val)
            if not canonical:
                lead_data[name_field] = None
            elif len(canonical) < 2:
                raise HTTPException(
                    status_code=422,
                    detail=f"El campo '{name_field}' debe tener al menos 2 caracteres.",
                )
            else:
                lead_data[name_field] = canonical

    # email → lowercase + formato válido
    email = lead_data.get("email")
    if email:
        email = email.lower()
        if not _EMAIL_RE.match(email):
            raise HTTPException(
                status_code=422,
                detail="El email no tiene un formato válido.",
            )
        lead_data["email"] = email

    # telefono → E.164 (+51XXXXXXXXX para móviles PE) + validación estricta
    telefono = lead_data.get("telefono")
    if telefono:
        telefono = _normalize_phone(telefono)
        if not _PHONE_RE.match(telefono):
            raise HTTPException(
                status_code=422,
                detail=(
                    "El teléfono no tiene un formato válido. "
                    "Debe tener entre 8 y 15 dígitos."
                ),
            )
        lead_data["telefono"] = telefono

    # dni → 8 dígitos exactos (DNI peruano)
    dni = lead_data.get("dni")
    if dni:
        dni_clean = re.sub(r"\D", "", dni)
        if not _DNI_PE_RE.match(dni_clean):
            raise HTTPException(
                status_code=422,
                detail="El DNI debe tener exactamente 8 dígitos.",
            )
        lead_data["dni"] = dni_clean

    # observaciones → texto limpio
    obs = lead_data.get("observaciones")
    if obs:
        lead_data["observaciones"] = _canonicalize_observaciones(obs)

    # ── Paso 3: regla de negocio — al menos un canal de contacto ──────────
    if not (lead_data.get("telefono") or lead_data.get("email")):
        raise HTTPException(
            status_code=422,
            detail="Debes proporcionar al menos un teléfono o un email.",
        )

    # ── Paso 4: truncar defensivamente (alineado con CHECK de la BD) ──────
    for field, maxlen in _FIELD_MAX_LENGTHS.items():
        val = lead_data.get(field)
        if isinstance(val, str) and len(val) > maxlen:
            lead_data[field] = val[:maxlen]

    return lead_data


def _check_antispam(
    form: dict,
    payload: dict,
    elapsed_seconds: Optional[float],
    ip_address: Optional[str],
) -> None:
    """Bloquea submissions sospechosas sin revelar al atacante el motivo.

    - honeypot: campo oculto que debe venir vacío
    - min-time: los bots envían en menos de 2s
    - rate limit por IP: N submissions en ventana de M minutos
    """
    # Honeypot: un humano no ve este campo, si viene relleno es bot.
    if payload.get(HONEYPOT_FIELD):
        logger.info("honeypot triggered on form %s from ip=%s", form.get("id"), ip_address)
        raise HTTPException(status_code=400, detail="Envío rechazado.")

    # Min time: frontend envía `_elapsed` en segundos desde que se cargó la página.
    min_seconds = settings.public_form_min_submit_seconds
    if elapsed_seconds is not None and elapsed_seconds < min_seconds:
        logger.info(
            "min-time triggered on form %s: %.2fs (<%ds) from ip=%s",
            form.get("id"), elapsed_seconds, min_seconds, ip_address,
        )
        raise HTTPException(status_code=400, detail="Envío rechazado.")

    # Rate limit por IP (defensa en profundidad además del slowapi global).
    if ip_address:
        window_minutes = settings.public_form_ip_window_minutes
        max_subs_per_ip = settings.public_form_ip_max_submissions
        recent = repo.count_recent_submissions_by_ip(
            ip_address=ip_address,
            minutes=window_minutes,
        )
        if recent >= max_subs_per_ip:
            logger.warning(
                "ip rate limit: %s has %d recent submissions (max=%d in %dmin)",
                ip_address, recent, max_subs_per_ip, window_minutes,
            )
            raise HTTPException(
                status_code=429,
                detail="Demasiados envíos desde tu red. Intenta de nuevo más tarde.",
            )


def _check_form_availability(form: dict) -> None:
    """Form debe estar activo, no expirado y bajo su cap de submissions."""
    if not form.get("activo"):
        raise HTTPException(status_code=410, detail="Este formulario ya no está activo.")

    expires_at = form.get("expires_at")
    if expires_at is not None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        # psycopg2 devuelve datetime con tz; si viene naive lo tratamos como UTC.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if now >= expires_at:
            raise HTTPException(status_code=410, detail="Este formulario ha expirado.")

    max_subs = form.get("max_submissions")
    if max_subs is not None and form.get("submission_count", 0) >= max_subs:
        raise HTTPException(
            status_code=410,
            detail="Este formulario ha alcanzado el límite de envíos.",
        )


# ── API pública del servicio ─────────────────────────────────────────────────

def list_eligible_assignees(current_user: TokenData) -> list[dict]:
    """Lista los asesores y supervisores a los que el usuario actual puede asignar un formulario."""
    _ensure_can_manage(current_user)
    return repo.list_eligible_assignees(current_user)


def create_form(
    *,
    current_user: TokenData,
    titulo: str,
    descripcion: Optional[str],
    nombre_evento: Optional[str],
    empresa: Optional[str],
    fuente_id: Optional[int],
    campana: Optional[str],
    config: dict,
    expires_at: Optional[str] = None,
    max_submissions: Optional[int] = None,
    sede_id_default: Optional[str] = None,  # V065
    asignado_a: Optional[str] = None,       # Asesor o supervisor opcional
) -> dict:
    """Crea un nuevo form. Genera slug único y asigna al usuario especificado (o creador por defecto)."""
    _ensure_can_manage(current_user)

    titulo = (titulo or "").strip()
    if len(titulo) < 3:
        raise HTTPException(status_code=422, detail="El título debe tener al menos 3 caracteres.")
    if len(titulo) > 120:
        raise HTTPException(status_code=422, detail="El título no puede superar 120 caracteres.")

    normalized_config = _validate_config(config)
    slug = _generate_unique_slug(titulo)
    target_asignado_a = _validate_assignee(current_user, asignado_a)

    return repo.create_form(
        slug=slug,
        titulo=titulo,
        descripcion=(descripcion or None),
        nombre_evento=(nombre_evento or None),
        empresa=(empresa or None),
        fuente_id=fuente_id,
        campana=(campana or None),
        asignado_a=target_asignado_a,
        created_by=current_user.user_id,
        config=normalized_config,
        expires_at=expires_at,
        max_submissions=max_submissions,
        sede_id_default=sede_id_default,
    )


def list_forms(current_user: TokenData, include_archived: bool = False) -> list[dict]:
    """Admin ve todos; supervisor los suyos o asignados a él."""
    _ensure_can_manage(current_user)
    if current_user.role == Role.ADMIN.value:
        return repo.list_all_forms(include_archived=include_archived)
    return repo.list_forms_by_creator(
        created_by=current_user.user_id,
        include_archived=include_archived,
    )


def get_form_private(form_id: str, current_user: TokenData) -> dict:
    """Vista privada (con metadata completa). Admin o dueño."""
    _ensure_can_manage(current_user)
    form = repo.get_form_by_id(form_id)
    if not form:
        raise HTTPException(status_code=404, detail="Formulario no encontrado.")
    _ensure_owns_or_admin(current_user, form)
    return form


def get_form_public(slug: str) -> dict:
    """Vista pública por slug — solo datos necesarios para renderizar.

    No revela created_by, asignado_a, ni metadata administrativa.
    """
    form = repo.get_form_by_slug(slug)
    if not form or not form.get("activo"):
        raise HTTPException(status_code=404, detail="Formulario no encontrado.")
    # Chequear expiración / cap — si no aplica, devuelve normal; si aplica, 410.
    _check_form_availability(form)

    # Recuperar píxeles globales configurados en el panel de Integraciones
    from app.services.integrations import credentials_repo
    from app.services.integrations.credentials_repo import GLOBAL_ACCOUNT

    meta_pixel_id = credentials_repo.get_plaintext("meta", "pixel_id", GLOBAL_ACCOUNT)
    tiktok_pixel_id = credentials_repo.get_plaintext("tiktok", "pixel_id", GLOBAL_ACCOUNT)

    return {
        "id":            str(form["id"]),
        "slug":          form["slug"],
        "titulo":        form["titulo"],
        "descripcion":   form.get("descripcion"),
        "nombre_evento": form.get("nombre_evento"),
        "empresa":       form.get("empresa"),
        "config":        form.get("config") or {},
        "meta_pixel_id":   meta_pixel_id,
        "tiktok_pixel_id": tiktok_pixel_id,
    }


def update_form(
    form_id: str,
    fields: dict,
    current_user: TokenData,
) -> dict:
    """Actualiza un form. Solo admin o el creador."""
    _ensure_can_manage(current_user)
    form = repo.get_form_by_id(form_id)
    if not form:
        raise HTTPException(status_code=404, detail="Formulario no encontrado.")
    _ensure_owns_or_admin(current_user, form)

    # Si cambia config, validar de nuevo
    if "config" in fields and fields["config"] is not None:
        fields["config"] = _validate_config(fields["config"])

    # Si cambia asignado_a, validar usuario elegible
    if "asignado_a" in fields:
        fields["asignado_a"] = _validate_assignee(current_user, fields["asignado_a"])

    # Título no se puede vaciar
    if "titulo" in fields:
        titulo = (fields["titulo"] or "").strip()
        if len(titulo) < 3 or len(titulo) > 120:
            raise HTTPException(
                status_code=422,
                detail="El título debe tener entre 3 y 120 caracteres.",
            )
        fields["titulo"] = titulo

    updated = repo.update_form(form_id, fields)
    if not updated:
        raise HTTPException(status_code=404, detail="Formulario no encontrado.")
    return updated


def archive_form(form_id: str, current_user: TokenData) -> None:
    """Soft delete — marca `activo = FALSE`."""
    _ensure_can_manage(current_user)
    form = repo.get_form_by_id(form_id)
    if not form:
        raise HTTPException(status_code=404, detail="Formulario no encontrado.")
    _ensure_owns_or_admin(current_user, form)
    if not repo.archive_form(form_id):
        raise HTTPException(status_code=404, detail="Formulario no encontrado.")


def delete_form_permanent(form_id: str, current_user: TokenData) -> None:
    """Hard delete — borrado físico irreversible del form.

    Reglas de seguridad:
      1. Solo admin puede hacerlo (supervisor no, aunque sea dueño).
      2. El form debe estar ya archivado (activo=FALSE). Esto obliga a un
         paso previo consciente y evita dedazos sobre forms en producción.
      3. Los leads capturados NO se borran (FK ON DELETE SET NULL), pero
         pierden la referencia al form de origen.
      4. Las submissions SI se borran en cascada (log histórico del form).
    """
    _ensure_can_manage(current_user)
    if current_user.role != Role.ADMIN.value:
        raise HTTPException(
            status_code=403,
            detail="Solo un administrador puede borrar formularios permanentemente.",
        )

    form = repo.get_form_by_id(form_id)
    if not form:
        raise HTTPException(status_code=404, detail="Formulario no encontrado.")

    if form.get("activo"):
        raise HTTPException(
            status_code=409,
            detail=(
                "Debes archivar el formulario antes de borrarlo permanentemente. "
                "Esto es una salvaguarda para evitar pérdidas accidentales."
            ),
        )

    if not repo.delete_form_permanent(form_id):
        raise HTTPException(status_code=404, detail="Formulario no encontrado.")
    logger.info(
        "Form %s borrado permanentemente por admin %s",
        form_id, current_user.user_id,
    )


def submit_public_form(
    *,
    slug: str,
    payload: dict,
    ip_address: Optional[str],
    user_agent: Optional[str],
    elapsed_seconds: Optional[float],
    background_tasks: Optional[Any] = None,
) -> dict:
    """Caso de uso completo de submit público.

    1. Busca form por slug
    2. Valida disponibilidad (activo, no expirado, no tope)
    3. Anti-spam (honeypot, min-time, rate limit IP)
    4. Valida payload contra config
    5. Crea lead + submission + incrementa contador (atómico en repo)
    6. Dispara notificación push (best-effort)
    7. Devuelve mensaje de éxito del form
    """
    form = repo.get_form_by_slug(slug)
    if not form or not form.get("activo"):
        # No revelamos si existía inactivo o si nunca existió.
        raise HTTPException(status_code=404, detail="Formulario no encontrado.")

    _check_form_availability(form)
    _check_antispam(form, payload, elapsed_seconds, ip_address)

    lead_data = _validate_submission_payload(form, payload)

    # V067: la repo ahora retorna {lead_id, recaptured, estrategia}.
    # Si recaptured=True el lead ya existia y handle_recontacto se encargo
    # del push de re-engagement al asesor original — NO mandamos el push de
    # "lead nuevo" para evitar duplicar notificaciones al asesor.
    result = repo.record_submission_and_create_lead(
        form=form,
        lead_data=lead_data,
        ip_address=ip_address,
        user_agent=user_agent,
        payload=payload,
    )
    lead_id    = result["lead_id"]
    recaptured = result.get("recaptured", False)

    if not recaptured:
        # Notificación push — siempre fuera de la tx. Si el caller paso
        # `background_tasks` (FastAPI), la enviamos despues de la response HTTP
        # asi el cliente del formulario no espera por FCM. Si no, fallback
        # sincrono (igual best-effort: errores no revierten el lead).
        asesor_id = str(form.get("asignado_a") or "")
        full_name = " ".join(
            filter(None, [lead_data.get("nombres"), lead_data.get("apellidos")])
        ).strip() or "Nuevo contacto"
        fuente_label = form.get("nombre_evento") or form.get("titulo") or ""

        def _send_push():
            try:
                # V070.91 — lead_id para deep-link al tap en mobile.
                notify_new_lead(asesor_id, full_name, fuente=fuente_label, lead_id=lead_id)
            except Exception as exc:  # noqa: BLE001 — el push es best-effort
                logger.warning("push fallido tras submit público %s: %s", slug, exc)

        if background_tasks is not None:
            background_tasks.add_task(_send_push)
        else:
            _send_push()
    else:
        logger.info(
            "[public_forms/recapture] form=%s lead=%s estrategia=%s — push de recontacto delegado a lead_recapture",
            slug, lead_id, result.get("estrategia"),
        )

    config = form.get("config") or {}
    return {
        "lead_id":       lead_id,
        "mensaje_exito": config.get("mensaje_exito") or "¡Gracias! Pronto te contactaremos.",
        "redirect_url":  config.get("redirect_url"),
    }


def count_leads_for_form(form_id: str, current_user: TokenData) -> int:
    """Total de leads NUEVOS vivos de un form — solo para admin/dueño.

    Compat con UI pre-V093: para el desglose completo (submissions /
    nuevos / recontactos) usar count_breakdown_for_form.
    """
    _ensure_can_manage(current_user)
    form = repo.get_form_by_id(form_id)
    if not form:
        raise HTTPException(status_code=404, detail="Formulario no encontrado.")
    _ensure_owns_or_admin(current_user, form)
    return repo.count_leads_by_form(form_id)


def count_breakdown_for_form(form_id: str, current_user: TokenData) -> dict:
    """Desglose de captacion del form (V093 — fix bug "3 vs 0").

    Devuelve `{total_submissions, leads_nuevos, recontactos}`. La UI lo
    usa para mostrar los 3 numeros en el modal de detalle del formulario,
    eliminando la confusion del label "LEADS CAPTURADOS" que mostraba
    valores distintos en card vs modal.
    """
    _ensure_can_manage(current_user)
    form = repo.get_form_by_id(form_id)
    if not form:
        raise HTTPException(status_code=404, detail="Formulario no encontrado.")
    _ensure_owns_or_admin(current_user, form)
    return repo.count_breakdown_by_form(form_id)
