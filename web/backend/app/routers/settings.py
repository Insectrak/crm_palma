"""
Router para configuración general del sistema (SMTP, integraciones, etc.).
Persiste los ajustes en la tabla public.app_settings (key-value JSONB).
"""
import base64
import hashlib
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from typing import Optional
from app.auth.jwt import get_current_user, require_admin, TokenData
from app.config import settings

router = APIRouter(prefix="/api/settings", tags=["Settings"])

# DDL para la tabla de configuración (se crea automáticamente si no existe)
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS public.app_settings (
    key         TEXT PRIMARY KEY,
    value       JSONB NOT NULL,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
"""


def _ensure_table(conn):
    with conn.cursor() as cur:
        cur.execute(_CREATE_TABLE_SQL)
    conn.commit()


class SmtpConfig(BaseModel):
    from_address: Optional[str] = ""
    smtp_server: Optional[str] = ""
    from_domain: Optional[str] = ""
    smtp_port: Optional[int] = 587
    username: Optional[str] = ""
    password: Optional[str] = ""
    use_ssl: Optional[bool] = False
    ignore_tls_errors: Optional[bool] = False
    reject_unauthorized: Optional[bool] = True


@router.get("/smtp")
def get_smtp_config(admin: TokenData = Depends(require_admin)):
    """Retorna la configuración SMTP actual. Solo admin (contiene credenciales)."""
    if settings.demo_mode:
        return SmtpConfig().model_dump()

    from app.database import get_db
    from psycopg2.extras import RealDictCursor

    with get_db() as conn:
        _ensure_table(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT value FROM public.app_settings WHERE key = 'smtp_config'"
            )
            row = cur.fetchone()
            if row:
                return row["value"]
    return SmtpConfig().model_dump()


@router.put("/smtp")
def save_smtp_config(
    config: SmtpConfig,
    admin: TokenData = Depends(require_admin),
):
    """Guarda (upsert) la configuración SMTP. Solo admin."""
    if settings.demo_mode:
        return {"ok": True, "demo": True}

    from app.database import get_db
    import json

    with get_db() as conn:
        _ensure_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.app_settings (key, value, updated_at)
                VALUES ('smtp_config', %s::jsonb, NOW())
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value,
                        updated_at = NOW()
                """,
                (json.dumps(config.model_dump()),),
            )
        conn.commit()
    return {"ok": True}


class SmtpTestRequest(BaseModel):
    to: str


@router.post("/smtp/test")
def test_smtp(
    data: SmtpTestRequest,
    admin: TokenData = Depends(require_admin),
):
    """Envia un email de prueba para verificar la configuracion SMTP. Solo admin."""
    from app.services.email_service import send_email
    from app.services.brand_service import get_company_name

    company = get_company_name()

    result = send_email(
        to=data.to,
        subject=f"Prueba SMTP — {company}",
        html_body=f"""
        <div style="font-family: sans-serif; padding: 20px;">
          <h2>Prueba de correo</h2>
          <p>Si recibes este mensaje, la configuracion SMTP esta funcionando correctamente.</p>
          <p style="color: #64748b; font-size: 12px; margin-top: 20px;">
            {company}
          </p>
        </div>
        """,
    )
    if result["success"]:
        return {"ok": True, "message": f"Email de prueba enviado a {data.to}"}
    else:
        raise HTTPException(status_code=400, detail=f"Error SMTP: {result['error']}")


# ─── Marca / Branding ───────────────────────────────────────────────────────

class BrandConfig(BaseModel):
    # V070.68 (Bundle B): defaults neutros. Cuando el admin del tenant
    # entra por primera vez a Configuracion → Marca, ve "Mi CRM" y debe
    # ponerle el nombre real de su empresa. Antes el default era "CRM
    # Palma Rio" y se filtraba a emails, tabs, exports de cualquier
    # cliente nuevo sin configurar nada.
    company_name:     Optional[str] = "Mi CRM"
    company_subtitle: Optional[str] = "Plataforma de Gestion"
    logo_data_url:    Optional[str] = None     # data:image/png;base64,...
    favicon_data_url: Optional[str] = None     # data:image/x-icon;base64,... (tab del navegador)
    primary_color:    Optional[str] = "#4F46E5"  # indigo-600
    primary_hover:    Optional[str] = "#4338CA"  # indigo-700
    sidebar_bg:       Optional[str] = "#0F172A"  # slate-900
    accent_color:     Optional[str] = "#6366F1"  # indigo-500


BRAND_DEFAULTS = BrandConfig().model_dump()

# Límites de branding — centralizados para facilitar mantenimiento (SRP).
_LOGO_MAX_BYTES = 700_000       # ~500 KB reales tras base64
_FAVICON_MAX_BYTES = 140_000    # ~100 KB reales tras base64
_FAVICON_ALLOWED_MIMES = (
    "image/x-icon",
    "image/vnd.microsoft.icon",
    "image/png",
    "image/svg+xml",
)


def _validate_data_url(
    data_url: Optional[str],
    *,
    field_label: str,
    max_bytes: int,
    allowed_mimes: Optional[tuple[str, ...]] = None,
) -> None:
    """Valida un data URL (tamaño y, opcionalmente, MIME).

    Lanza HTTPException 400 con un mensaje claro si no cumple las reglas.
    Si el valor es falsy (None / "") se considera "sin imagen" y pasa.
    """
    if not data_url:
        return
    if len(data_url) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"{field_label} es demasiado grande",
        )
    if allowed_mimes is not None:
        # Un data URL válido tiene el formato: data:<mime>;base64,<payload>
        if not data_url.startswith("data:"):
            raise HTTPException(
                status_code=400,
                detail=f"{field_label}: formato inválido (se esperaba data URL)",
            )
        header = data_url.split(",", 1)[0]  # "data:image/png;base64"
        mime = header[5:].split(";", 1)[0].lower()
        if mime not in allowed_mimes:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{field_label}: tipo no permitido ({mime}). "
                    f"Formatos válidos: {', '.join(allowed_mimes)}"
                ),
            )


@router.get("/brand")
def get_brand():
    """Configuración de marca — pública (la usa el login)."""
    if settings.demo_mode:
        return BRAND_DEFAULTS

    from app.database import get_db
    from psycopg2.extras import RealDictCursor

    try:
        with get_db() as conn:
            _ensure_table(conn)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT value FROM public.app_settings WHERE key = 'brand_config'")
                row = cur.fetchone()
                if row:
                    return {**BRAND_DEFAULTS, **(row["value"] or {})}
    except Exception:
        pass
    return BRAND_DEFAULTS


# ─── Asset binario del branding (logo / favicon) ────────────────────────────
# correo profesional, Outlook y estilo elegante Mail bloquean `<img src="data:image/...">` por CSP,
# así que el logo del email se sirve vía HTTP público desde estos endpoints.
# La marca es info pública (la misma que el login muestra antes del JWT) → sin
# auth. ETag derivado del hash del data URL evita re-bajar la imagen en cada
# apertura del email.
_DATA_URL_PREFIX = "data:"


def _decode_brand_asset(data_url: Optional[str]) -> Optional[tuple[bytes, str]]:
    """Devuelve (bytes, mime) parseando un data URL del brand_config.
    Devuelve None si está vacío o malformado (sin levantar excepción —
    el caller responde 404 con dignidad).
    """
    if not data_url or not data_url.startswith(_DATA_URL_PREFIX):
        return None
    try:
        header, payload = data_url.split(",", 1)
        mime = header[len(_DATA_URL_PREFIX):].split(";", 1)[0].lower() or "application/octet-stream"
        raw = base64.b64decode(payload, validate=False)
        return raw, mime
    except Exception:
        return None


def _serve_brand_asset(field: str, fallback_mime: str = "image/png") -> Response:
    """Helper compartido por /logo y /favicon. Sin DRY = bugs futuros."""
    brand = get_brand()  # ya tolera DB caída → defaults
    decoded = _decode_brand_asset(brand.get(field))
    if decoded is None:
        # Sin asset configurado: 404 (no inventamos placeholders binarios —
        # el email usa el fallback "inicial sobre color" si falla la imagen).
        raise HTTPException(status_code=404, detail="Asset no configurado")
    image_bytes, mime = decoded
    etag = hashlib.md5(image_bytes).hexdigest()  # noqa: S324 (no es uso crypto)
    return Response(
        content=image_bytes,
        media_type=mime or fallback_mime,
        headers={
            # Cache 1h en el cliente, 24h en proxies (correo profesional rebaja imágenes a su CDN).
            "Cache-Control": "public, max-age=3600, s-maxage=86400",
            "ETag": f'"{etag}"',
        },
    )


@router.get("/brand/logo")
def get_brand_logo_binary():
    """Logo del tenant servido como binario HTTP.

    Usado por templates de email (correo profesional rechaza data URLs en <img>).
    Público — no requiere auth.
    """
    return _serve_brand_asset("logo_data_url", fallback_mime="image/png")


@router.get("/brand/favicon")
def get_brand_favicon_binary():
    """Favicon del tenant servido como binario HTTP."""
    return _serve_brand_asset("favicon_data_url", fallback_mime="image/x-icon")


@router.put("/brand")
def save_brand(
    config: BrandConfig,
    current_user: TokenData = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede cambiar la marca")
    if settings.demo_mode:
        return {"ok": True, "demo": True}

    from app.database import get_db
    import json

    payload = config.model_dump()
    _validate_data_url(
        payload.get("logo_data_url"),
        field_label="Logo",
        max_bytes=_LOGO_MAX_BYTES,
    )
    _validate_data_url(
        payload.get("favicon_data_url"),
        field_label="Favicon",
        max_bytes=_FAVICON_MAX_BYTES,
        allowed_mimes=_FAVICON_ALLOWED_MIMES,
    )

    with get_db() as conn:
        _ensure_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.app_settings (key, value, updated_at)
                VALUES ('brand_config', %s::jsonb, NOW())
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value, updated_at = NOW()
                """,
                (json.dumps(payload),),
            )
        conn.commit()
    # V070.68 (Bundle B): invalidar cache del brand_service para que el
    # cambio se refleje en emails / exports / push / clasificador IA
    # de inmediato (sin esperar 60s del TTL).
    from app.services.brand_service import invalidate_cache as _invalidate_brand
    _invalidate_brand()
    return {"ok": True}


# ─── Modo de ingesta (rotacion / pool / fijo) ───────────────────────────────

class IngestModeConfig(BaseModel):
    """Modo de asignacion para leads entrantes via /api/ingest/leads.

    - rotacion: round-robin diario entre supervisores (default).
    - fijo:     siempre se asignan a `fijo_user_id` (debe ser supervisor).
    """
    mode: str = "rotacion"                       # rotacion | fijo
    fijo_user_id: Optional[str] = None           # UUID del supervisor si mode=fijo


INGEST_MODE_DEFAULTS = IngestModeConfig().model_dump()
_VALID_INGEST_MODES = ("rotacion", "fijo")


def load_ingest_mode() -> dict:
    """Helper reutilizable: lee el modo actual (default: rotacion).
    Expuesto como funcion modulo para que ingest.py lo consuma sin
    duplicar logica de persistencia (DRY / SRP)."""
    from app.database import get_db
    from psycopg2.extras import RealDictCursor
    try:
        with get_db() as conn:
            _ensure_table(conn)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT value FROM public.app_settings WHERE key = 'ingest_config'"
                )
                row = cur.fetchone()
                if row:
                    return {**INGEST_MODE_DEFAULTS, **(row["value"] or {})}
    except Exception:
        pass
    return dict(INGEST_MODE_DEFAULTS)


@router.get("/ingest-mode")
def get_ingest_mode(admin: TokenData = Depends(require_admin)):
    """Retorna el modo de ingesta actual. Solo admin."""
    return load_ingest_mode()


@router.put("/ingest-mode")
def save_ingest_mode(
    config: IngestModeConfig,
    admin: TokenData = Depends(require_admin),
):
    """Upsert del modo de ingesta. Solo admin."""
    if config.mode not in _VALID_INGEST_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Modo invalido. Valores validos: {', '.join(_VALID_INGEST_MODES)}",
        )
    if config.mode == "fijo" and not config.fijo_user_id:
        raise HTTPException(400, "Modo 'fijo' requiere fijo_user_id.")

    from app.database import get_db
    from psycopg2.extras import RealDictCursor
    import json

    with get_db() as conn:
        _ensure_table(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Validar que el supervisor exista y sea supervisor (si modo=fijo)
            if config.mode == "fijo":
                cur.execute(
                    "SELECT id FROM auth.users WHERE id = %s::uuid AND role = 'supervisor' AND is_active = TRUE",
                    (config.fijo_user_id,),
                )
                if not cur.fetchone():
                    raise HTTPException(400, "fijo_user_id no corresponde a un supervisor activo.")

            cur.execute(
                """
                INSERT INTO public.app_settings (key, value, updated_at)
                VALUES ('ingest_config', %s::jsonb, NOW())
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value, updated_at = NOW()
                """,
                (json.dumps(config.model_dump()),),
            )
        conn.commit()
    return {"ok": True, **config.model_dump()}


# ─── Permisos de contactos ──────────────────────────────────────────────────

class ContactPermissions(BaseModel):
    asesor_can_edit: bool = False
    asesor_can_delete: bool = False


@router.get("/contact-permissions")
def get_contact_permissions(current_user: TokenData = Depends(get_current_user)):
    from app.database import get_db
    from psycopg2.extras import RealDictCursor

    with get_db() as conn:
        _ensure_table(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT value FROM public.app_settings WHERE key = 'contact_permissions'")
            row = cur.fetchone()
            if row:
                return row["value"]
    return ContactPermissions().model_dump()


@router.put("/contact-permissions")
def save_contact_permissions(
    config: ContactPermissions,
    current_user: TokenData = Depends(get_current_user),
):
    if current_user.role not in ("admin", "supervisor"):
        raise HTTPException(status_code=403, detail="Solo admin y supervisor pueden cambiar permisos")

    from app.database import get_db
    import json

    with get_db() as conn:
        _ensure_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.app_settings (key, value, updated_at)
                VALUES ('contact_permissions', %s::jsonb, NOW())
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value, updated_at = NOW()
                """,
                (json.dumps(config.model_dump()),),
            )
        conn.commit()
    return {"ok": True}


# ─── Sincronizacion movil (call log) ────────────────────────────────────────
#
# Controla cada cuanto la APK hace push del registro de llamadas al CRM.
# Antes era constante hardcoded (30 min) → cambiarlo requeria build de APK
# y redistribuir. Ahora el admin lo ajusta desde la web; la APK lo lee al
# arrancar y al volver a foreground.
#
# Rangos:
#   - min 5: por debajo de 5 min se vuelve agresivo en bateria sin beneficio
#   - max 120: por encima de 2h los reportes del supervisor quedan demasiado
#     atrasados — pierde el caso de uso "casi en vivo".

class MobileSyncConfig(BaseModel):
    auto_sync_minutes: int = 30


MOBILE_SYNC_DEFAULTS = MobileSyncConfig().model_dump()
_MOBILE_SYNC_MIN_MIN = 5
_MOBILE_SYNC_MAX_MIN = 120


@router.get("/mobile-sync")
def get_mobile_sync_config(current_user: TokenData = Depends(get_current_user)):
    """Retorna el intervalo de sync. Cualquier usuario autenticado puede leer
    (la APK lo necesita en el arranque, no solo admins)."""
    from app.database import get_db
    from psycopg2.extras import RealDictCursor

    try:
        with get_db() as conn:
            _ensure_table(conn)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT value FROM public.app_settings WHERE key = 'mobile_sync_config'"
                )
                row = cur.fetchone()
                if row:
                    return {**MOBILE_SYNC_DEFAULTS, **(row["value"] or {})}
    except Exception:
        pass
    return MOBILE_SYNC_DEFAULTS


@router.put("/mobile-sync")
def save_mobile_sync_config(
    config: MobileSyncConfig,
    admin: TokenData = Depends(require_admin),
):
    """Upsert del intervalo. Solo admin — afecta a todos los asesores."""
    if not (_MOBILE_SYNC_MIN_MIN <= config.auto_sync_minutes <= _MOBILE_SYNC_MAX_MIN):
        raise HTTPException(
            status_code=400,
            detail=(
                f"auto_sync_minutes fuera de rango "
                f"({_MOBILE_SYNC_MIN_MIN}-{_MOBILE_SYNC_MAX_MIN})."
            ),
        )

    from app.database import get_db
    import json

    with get_db() as conn:
        _ensure_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.app_settings (key, value, updated_at)
                VALUES ('mobile_sync_config', %s::jsonb, NOW())
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value, updated_at = NOW()
                """,
                (json.dumps(config.model_dump()),),
            )
        conn.commit()
    return {"ok": True, **config.model_dump()}


# ─── Configuración de carga masiva ───────────────────────────────────────────
# Flags que gerencia puede activar/desactivar sin tocar código. V028: primer
# flag es `calidad_requerida` — si TRUE, el importador rechaza filas cuya
# calidad no coincida con el catálogo `crm.catalogo_calidad`.

class CargaMasivaConfig(BaseModel):
    calidad_requerida: bool = False


CARGA_MASIVA_DEFAULTS = CargaMasivaConfig().model_dump()


def load_carga_masiva_config() -> dict:
    """Helper reutilizable para que carga_masiva.py lea los flags sin
    duplicar la lógica de persistencia (DRY / SRP)."""
    from app.database import get_db
    from psycopg2.extras import RealDictCursor
    try:
        with get_db() as conn:
            _ensure_table(conn)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT value FROM public.app_settings WHERE key = 'carga_masiva_config'"
                )
                row = cur.fetchone()
                if row:
                    return {**CARGA_MASIVA_DEFAULTS, **(row["value"] or {})}
    except Exception:
        pass
    return dict(CARGA_MASIVA_DEFAULTS)


@router.get("/carga-masiva")
def get_carga_masiva_config(current_user: TokenData = Depends(get_current_user)):
    """Cualquier autenticado lo consulta: el frontend lo necesita para
    decidir si marcar `calidad` como obligatoria en el formulario."""
    return load_carga_masiva_config()


@router.put("/carga-masiva")
def save_carga_masiva_config(
    config: CargaMasivaConfig,
    admin: TokenData = Depends(require_admin),
):
    from app.database import get_db
    import json

    with get_db() as conn:
        _ensure_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.app_settings (key, value, updated_at)
                VALUES ('carga_masiva_config', %s::jsonb, NOW())
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value, updated_at = NOW()
                """,
                (json.dumps(config.model_dump()),),
            )
        conn.commit()
    return {"ok": True, **config.model_dump()}


# ─────────────────────────────────────────────────────────────────────────────
# IA Clasificador — config editable desde /Configuracion
# ─────────────────────────────────────────────────────────────────────────────

class AiClassifierConfig(BaseModel):
    """Config del clasificador IA. Solo se permite editar campos seguros —
    el prompt template y las categorias siguen hardcoded por seguridad.

    V070.68 (Bundle B): defaults sin nombre/industria de cliente especifico.
    El admin del tenant DEBE configurar company_name, company_description y
    relevant_keywords. Si no lo hace, el clasificador se niega a clasificar
    (ver wa_classifier_service.is_configured) en vez de asumir inmobiliaria
    de Palma Rio.
    """
    # Negocio — vacios por default; el clasificador IA exige que esten
    # configurados antes de procesar mensajes (no inventa industria).
    company_name:           Optional[str]   = ""
    company_description:    Optional[str]   = ""
    relevant_keywords:      Optional[str]   = ""
    country:                Optional[str]   = "Peru"
    # Decision thresholds
    auto_assign_threshold:  Optional[float] = 0.80
    auto_archive_threshold: Optional[float] = 0.85
    # Behavior
    history_message_count:  Optional[int]   = 5
    extra_instructions:     Optional[str]   = ""
    # Multi-provider (V039) — cualquier proveedor LLM
    provider:               Optional[str]   = "ollama"   # ollama | openai | anthropic | gemini
    ollama_base_url:        Optional[str]   = ""         # vacio = env
    ollama_model:           Optional[str]   = ""         # vacio = env
    openai_api_key:         Optional[str]   = ""         # plaintext en request, encriptada en DB
    openai_model:           Optional[str]   = "gpt-4o-mini"
    anthropic_api_key:      Optional[str]   = ""
    anthropic_model:        Optional[str]   = "claude-haiku-4-5"
    gemini_api_key:         Optional[str]   = ""
    gemini_model:           Optional[str]   = "gemini-1.5-flash"
    timeout_seconds:        Optional[int]   = 30
    temperature:            Optional[float] = 0.2
    max_tokens:             Optional[int]   = 400

    @classmethod
    def _clamp(cls, v: Optional[float], lo: float, hi: float, default: float) -> float:
        try:
            f = float(v) if v is not None else default
        except (TypeError, ValueError):
            return default
        return max(lo, min(f, hi))


_API_KEY_FIELDS = ("openai_api_key", "anthropic_api_key", "gemini_api_key")


def _mask_api_keys(cfg: dict) -> dict:
    """Reemplaza API keys encriptadas por mask preview "**********abcd".
    Asi el admin sabe que hay una key configurada sin exponerla en GET.
    """
    from app.services.secrets_service import decrypt, mask
    out = dict(cfg)
    for field in _API_KEY_FIELDS:
        enc = (cfg.get(field) or "").strip()
        if not enc:
            out[field] = ""
            continue
        try:
            plain = decrypt(enc)
            out[field] = mask(plain) if plain else "********"
        except Exception:  # noqa: BLE001
            out[field] = "********"
    return out


@router.get("/ai-classifier")
def get_ai_classifier_config(admin: TokenData = Depends(require_admin)):
    """Devuelve la config actual con defaults. API keys vienen enmascaradas
    (nunca en plaintext) — el frontend muestra el preview pero al editar
    debe enviar la key completa o dejar el campo vacio para no tocarla."""
    if settings.demo_mode:
        return AiClassifierConfig().model_dump()

    from app.services.wa_classifier_service import load_ai_config
    return _mask_api_keys(load_ai_config())


@router.put("/ai-classifier")
def save_ai_classifier_config(
    config: AiClassifierConfig,
    admin: TokenData = Depends(require_admin),
):
    """Persiste la config y INVALIDA el cache del classifier service —
    el proximo classify usa los valores nuevos sin reiniciar el server."""
    if settings.demo_mode:
        return {"ok": True, "demo": True, **config.model_dump()}

    from app.database import get_db
    from app.services.secrets_service import encrypt
    from app.services.wa_classifier_service import (
        invalidate_ai_config_cache,
        load_ai_config,
    )
    import json

    # Clamping defensivo de thresholds (UI tambien valida pero defense in depth)
    payload = config.model_dump()
    payload["auto_assign_threshold"]  = AiClassifierConfig._clamp(
        payload.get("auto_assign_threshold"), 0.50, 0.99, 0.80,
    )
    payload["auto_archive_threshold"] = AiClassifierConfig._clamp(
        payload.get("auto_archive_threshold"), 0.50, 0.99, 0.85,
    )
    # history_message_count clamp [1, 20]
    try:
        hc = int(payload.get("history_message_count") or 5)
    except (TypeError, ValueError):
        hc = 5
    payload["history_message_count"] = max(1, min(hc, 20))

    # provider whitelist
    if payload.get("provider") not in ("ollama", "openai", "anthropic", "gemini"):
        payload["provider"] = "ollama"

    # Encriptacion de API keys: si el frontend manda la key en plaintext,
    # la encriptamos. Si el campo viene vacio o con el mask preview ("****..."),
    # PRESERVAMOS la encriptada existente — asi el admin puede editar otros
    # campos sin re-tipear la key cada vez.
    existing = load_ai_config()
    for field in _API_KEY_FIELDS:
        new_val = (payload.get(field) or "").strip()
        if not new_val or new_val.startswith("*"):
            # Preserve existing encrypted value
            payload[field] = existing.get(field) or ""
        else:
            # Encriptar plaintext nuevo
            payload[field] = encrypt(new_val)

    with get_db() as conn:
        _ensure_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.app_settings (key, value, updated_at)
                VALUES ('ai_classifier_config', %s::jsonb, NOW())
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value, updated_at = NOW()
                """,
                (json.dumps(payload),),
            )
        conn.commit()

    invalidate_ai_config_cache()
    # Respondemos con keys enmascaradas (nunca en plaintext)
    return {"ok": True, **_mask_api_keys(payload)}


@router.get("/ai-classifier/health")
async def ai_classifier_health(admin: TokenData = Depends(require_admin)):
    """Ping al proveedor IA configurado. Devuelve latencia, modelos
    disponibles y status. Util antes de guardar para validar la config."""
    if settings.demo_mode:
        return {"ok": True, "demo": True, "model": "demo-model", "latency_ms": 0}

    from app.services.llm_providers import LLMProviderError, get_provider
    from app.services.wa_classifier_service import (
        _build_provider_runtime_config,
        load_ai_config,
    )
    runtime_cfg = _build_provider_runtime_config(load_ai_config())
    try:
        provider = get_provider(runtime_cfg)
    except LLMProviderError as exc:
        raise HTTPException(400, str(exc)) from exc

    return await provider.health_check()


class AiClassifierTestRequest(BaseModel):
    message: str
    contact_name: Optional[str] = None
    ad_headline: Optional[str] = None


@router.post("/ai-classifier/test")
async def test_ai_classifier(
    data: AiClassifierTestRequest,
    admin: TokenData = Depends(require_admin),
):
    """Corre el clasificador con un mensaje de prueba sin tocar la DB.
    Util para iterar el prompt rapido desde la UI antes de aprobarlo."""
    if settings.demo_mode:
        return {
            "ok":            True,
            "demo":          True,
            "categoria":     "cliente_potencial",
            "confianza":     0.92,
            "interes":       "compra",
            "urgencia":      "media",
            "resumen":       "[demo] Pregunta precio del lote 8",
        }

    from app.services.wa_classifier_service import _build_prompt, _call_ollama

    if not data.message or not data.message.strip():
        raise HTTPException(400, "message vacio")

    ctx = {
        "contact_name":      data.contact_name or "Test User",
        "wa_phone":          "51999999999",
        "campaign_headline": data.ad_headline,
        "campaign_body":     None,
        "campaign_name":     None,
        "messages":          [],
        "referral":          None,
    }
    prompt = _build_prompt(ctx, data.message.strip())
    raw = await _call_ollama(prompt)
    if raw is None:
        raise HTTPException(503, "Ollama no respondio o devolvio JSON invalido")

    return {
        "ok":         True,
        "raw_result": raw,
        "prompt":     prompt,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Notificaciones Push — templates editables por evento (V040)
# ─────────────────────────────────────────────────────────────────────────────

class NotificationTemplate(BaseModel):
    enabled: bool = True
    title:   str  = ""
    body:    str  = ""


class QuietHoursConfig(BaseModel):
    """Rango horario donde no se envia push (excepto eventos urgentes)."""
    enabled: bool = True
    start: str = "21:00"
    end:   str = "08:00"


class NotificationsConfig(BaseModel):
    """Templates por evento + quiet hours global. Frontend manda dict completo,
    server preserva el shape y solo permite eventos conocidos (whitelist)."""
    events: dict = {}
    quiet_hours: Optional[QuietHoursConfig] = None


@router.get("/notifications")
def get_notifications_config(admin: TokenData = Depends(require_admin)):
    """Devuelve los templates actuales + lista de variables disponibles
    por evento + config de quiet hours. El frontend usa las variables para
    mostrar tags clickeables en el editor (autocompletado tipo mensajería profesional)."""
    if settings.demo_mode:
        from app.services.notification_service import (
            _TEMPLATE_DEFAULTS,
            _QUIET_HOURS_DEFAULT,
            URGENT_EVENTS,
            get_available_variables,
        )
        return {
            "events":              {k: dict(v) for k, v in _TEMPLATE_DEFAULTS.items()},
            "available_variables": get_available_variables(),
            "quiet_hours":         dict(_QUIET_HOURS_DEFAULT),
            "urgent_events":       sorted(URGENT_EVENTS),
        }

    from app.services.notification_service import (
        URGENT_EVENTS,
        get_available_variables,
        load_quiet_hours,
        load_templates,
    )
    return {
        "events":              load_templates(),
        "available_variables": get_available_variables(),
        "quiet_hours":         load_quiet_hours(),
        "urgent_events":       sorted(URGENT_EVENTS),
    }


@router.put("/notifications")
def save_notifications_config(
    config: NotificationsConfig,
    admin: TokenData = Depends(require_admin),
):
    """Persiste templates + quiet hours. Solo guarda eventos del whitelist.
    Invalida cache."""
    from app.services.notification_service import (
        _TEMPLATE_DEFAULTS,
        _QUIET_HOURS_DEFAULT,
        invalidate_templates_cache,
    )

    # Whitelist + sanitizado: solo eventos conocidos, defaults para campos faltantes
    sanitized_events: dict = {}
    for event_type, default_tpl in _TEMPLATE_DEFAULTS.items():
        incoming = (config.events or {}).get(event_type) or {}
        sanitized_events[event_type] = {
            "enabled": bool(incoming.get("enabled", default_tpl.get("enabled", True))),
            "title":   str(incoming.get("title", default_tpl.get("title", "")))[:200],
            "body":    str(incoming.get("body",  default_tpl.get("body",  "")))[:500],
        }

    # V070.52 — Sanitizar quiet_hours. Formato HH:MM, default si invalido.
    import re
    _hhmm = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

    def _valid_hhmm(s, fallback):
        return s if isinstance(s, str) and _hhmm.match(s) else fallback

    qh_in = config.quiet_hours.dict() if config.quiet_hours else {}
    sanitized_quiet = {
        "enabled": bool(qh_in.get("enabled", _QUIET_HOURS_DEFAULT["enabled"])),
        "start":   _valid_hhmm(qh_in.get("start"), _QUIET_HOURS_DEFAULT["start"]),
        "end":     _valid_hhmm(qh_in.get("end"),   _QUIET_HOURS_DEFAULT["end"]),
    }

    if settings.demo_mode:
        return {"ok": True, "demo": True, "events": sanitized_events, "quiet_hours": sanitized_quiet}

    from app.database import get_db
    import json

    with get_db() as conn:
        _ensure_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.app_settings (key, value, updated_at)
                VALUES ('notifications_config', %s::jsonb, NOW())
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value, updated_at = NOW()
                """,
                (json.dumps({"events": sanitized_events, "quiet_hours": sanitized_quiet}),),
            )
        conn.commit()

    invalidate_templates_cache()
    return {"ok": True, "events": sanitized_events, "quiet_hours": sanitized_quiet}


class NotificationsTestRequest(BaseModel):
    event_type: str  # uno del whitelist


@router.post("/notifications/test")
def test_notification(
    data: NotificationsTestRequest,
    current_user: TokenData = Depends(get_current_user),
):
    """Envia un push de prueba al usuario actual con el template del evento.
    Usa contexto dummy (Lead Demo, etc.) para que el render se vea real.
    Permite a CUALQUIER usuario probar sus propias notificaciones (no solo admin),
    asi cada asesor verifica que su dispositivo recibe correctamente."""
    from app.services.notification_service import (
        _TEMPLATE_DEFAULTS,
        notify,
    )

    if data.event_type not in _TEMPLATE_DEFAULTS:
        raise HTTPException(400, f"Evento desconocido: {data.event_type}")

    # Contexto dummy con todas las variables posibles para previewing
    dummy_context = {
        "lead_name":       "Juan Pérez (DEMO)",
        "fuente":          "WhatsApp",
        "contact_name":    "María González (DEMO)",
        "message_preview": "Hola, quería más información",
        "wa_phone":        "+51999000000",
    }

    if settings.demo_mode:
        from app.services.notification_service import _safe_format
        templates = {k: dict(v) for k, v in _TEMPLATE_DEFAULTS.items()}
        tpl = templates[data.event_type]
        return {
            "ok":         True,
            "demo":       True,
            "title":      _safe_format(tpl["title"], dummy_context),
            "body":       _safe_format(tpl["body"], dummy_context),
        }

    sent = notify(data.event_type, current_user.user_id, dummy_context)
    return {
        "ok":   True,
        "sent": sent,
        "info": (
            "Push enviado a tu dispositivo. Si no llega: confirma que tienes "
            "FCM_ENABLED=true y un token registrado (la app movil debe estar instalada)."
            if sent else
            "No se envio: revisa FCM_ENABLED, FCM_SERVICE_ACCOUNT_B64 y que el "
            "evento este habilitado."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# V070.53 — Preferencias personales de notificaciones (fase 3).
# Cada usuario (cualquier rol) puede ajustar sus propias prefs:
#   - Kill switch general (push on/off)
#   - Quiet hours personal (override del global)
#   - Opt-out por tipo de evento
# Paridad patrón estándar preferencias de notificación per-user.

class UserNotificationPrefs(BaseModel):
    push_enabled: bool = True
    # None = heredar del global. true/false = override personal.
    quiet_hours_enabled: Optional[bool] = None
    quiet_hours_start:   Optional[str]  = None  # HH:MM
    quiet_hours_end:     Optional[str]  = None
    # Lista de event_types donde el usuario eligio NO recibir push.
    events_disabled: list = []
    # V073 — Lista de event_types URGENT donde el usuario eligio que SI
    # respeten su quiet_hours (override del bypass global). patrón estándar.
    # Whitelist server-side: solo eventos que esten en URGENT_EVENTS.
    urgent_events_disabled: list = []


@router.get("/me/notification-prefs")
def get_my_notification_prefs(current_user: TokenData = Depends(get_current_user)):
    """Devuelve las preferencias del usuario actual + defaults globales
    para que el cliente sepa que valores se aplican cuando hereda."""
    from app.services.notification_service import (
        _TEMPLATE_DEFAULTS,
        URGENT_EVENTS,
        load_quiet_hours,
        load_user_prefs,
    )
    # V070.67 — Eliminado 'effective_quiet_hours' del response: era dead data,
    # ningun cliente lo consumia (ambos lo recalculan en cliente-side a partir
    # de prefs + global_quiet_hours). Mantener el campo confundia: cuando
    # cambien las reglas, hay 3 fuentes de verdad y el cliente puede mostrar
    # algo distinto al servidor. Si en el futuro necesitamos logica compleja
    # server-side (feriados, excepciones), agregamos un endpoint dedicado
    # GET /api/settings/me/quiet-hours/effective.
    prefs = load_user_prefs(current_user.user_id)
    global_qh = load_quiet_hours()
    return {
        "prefs":              prefs,
        "global_quiet_hours": global_qh,
        "available_events":   list(_TEMPLATE_DEFAULTS.keys()),
        "urgent_events":      sorted(URGENT_EVENTS),
    }


@router.put("/me/notification-prefs")
def save_my_notification_prefs(
    data: UserNotificationPrefs,
    current_user: TokenData = Depends(get_current_user),
):
    """Persiste prefs del usuario actual. Sanitiza HH:MM y events_disabled.

    V089 — Defense in depth: el admin puede revocar el permiso
    `notificaciones.manage_own` a un rol para que sus usuarios NO puedan
    apagar su kill switch ni cambiar el horario silencioso (caso de uso:
    asegurar que los asesores siempre reciban push de leads). Admin legacy
    bypasea siempre.
    """
    if current_user.role != "admin":
        perms = current_user.permissions or {}
        if perms.get("_all") is not True and perms.get("notificaciones.manage_own") is not True:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Tu administrador gestiona estas preferencias. "
                    "Si necesitas pausar tus notificaciones, coordínalo con tu supervisor."
                ),
            )

    from app.services.notification_service import save_user_prefs
    saved = save_user_prefs(current_user.user_id, data.dict())
    return {"ok": True, "prefs": saved}


# ─────────────────────────────────────────────────────────────────────────────
# Firebase Cloud Messaging (FCM) — credenciales editables (V040.1)
#
# Antes solo via env vars (FCM_ENABLED, FCM_SERVICE_ACCOUNT_B64). Ahora via
# UI con encryption Fernet. Override pattern: si DB tiene credencial, se usa;
# si no, fallback al env. Hot reload — al guardar, el app de Firebase se
# rehinicia con la credencial nueva sin restart del contenedor.
# ─────────────────────────────────────────────────────────────────────────────

class FcmConfig(BaseModel):
    enabled: bool = False
    # Service account JSON RAW (no base64) — el server lo encodea a base64
    # antes de encriptar. UX: el admin pega el JSON tal cual lo descarga
    # de Firebase Console, sin tener que correr un comando para encodear.
    # Si viene vacio o con asterisks (mask preview del GET), preserva la
    # credencial existente (mismo patron que API keys de OpenAI/Anthropic).
    service_account_json: Optional[str] = ""


@router.get("/fcm")
def get_fcm_config(admin: TokenData = Depends(require_admin)):
    """Devuelve estado actual de FCM. La credencial NUNCA se devuelve en
    plaintext — solo un preview enmascarado y metadata (source, status)."""
    if settings.demo_mode:
        return {
            "enabled":           True,
            "has_credentials":   True,
            "credential_source": "demo",
            "credential_preview": "********demo",
            "initialized":       True,
            "last_error":        None,
        }

    from app.services.fcm_service import get_init_status, load_fcm_config
    from app.services.secrets_service import mask
    cfg = load_fcm_config()
    status = get_init_status()
    sa_b64 = cfg.get("service_account_b64") or ""
    return {
        "enabled":            cfg["enabled"],
        "has_credentials":    bool(sa_b64),
        "credential_source":  cfg.get("source", "env"),
        "credential_preview": mask(sa_b64) if sa_b64 else "",
        "initialized":        status["initialized"],
        "last_error":         status["last_error"],
    }


@router.put("/fcm")
def save_fcm_config(
    config: FcmConfig,
    admin: TokenData = Depends(require_admin),
):
    """Guarda credencial encriptada + invalida cache + tear down de Firebase
    Admin para que el proximo push use la credencial nueva."""
    if settings.demo_mode:
        return {"ok": True, "demo": True, "enabled": config.enabled}

    from app.database import get_db
    from app.services.fcm_service import (
        invalidate_fcm_config_cache,
        load_fcm_config,
    )
    from app.services.secrets_service import encrypt
    import base64
    import json as _json

    incoming_json = (config.service_account_json or "").strip()
    encrypted_b64: Optional[str] = None

    if incoming_json and not incoming_json.startswith("*"):
        # Validacion sintactica: debe ser JSON parseable con campos basicos
        try:
            parsed = _json.loads(incoming_json)
        except Exception as exc:
            raise HTTPException(400, f"JSON invalido: {exc}") from exc
        if parsed.get("type") != "service_account":
            raise HTTPException(
                400,
                "El JSON no parece de un service account de Firebase. "
                "Debe tener 'type': 'service_account'.",
            )
        if not parsed.get("project_id") or not parsed.get("private_key"):
            raise HTTPException(
                400,
                "El JSON no tiene campos requeridos (project_id, private_key).",
            )
        # Encodear a base64 (formato que espera _init_firebase) y encriptar
        sa_b64 = base64.b64encode(incoming_json.encode("utf-8")).decode("ascii")
        encrypted_b64 = encrypt(sa_b64)
    else:
        # Preserva credencial existente (admin solo edito el toggle)
        existing = load_fcm_config()
        if existing.get("service_account_b64"):
            encrypted_b64 = encrypt(existing["service_account_b64"])

    payload = {
        "enabled": bool(config.enabled),
        "service_account_b64_encrypted": encrypted_b64 or "",
    }

    with get_db() as conn:
        _ensure_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.app_settings (key, value, updated_at)
                VALUES ('fcm_credentials', %s::jsonb, NOW())
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value, updated_at = NOW()
                """,
                (_json.dumps(payload),),
            )
        conn.commit()

    invalidate_fcm_config_cache()
    return {"ok": True, "enabled": payload["enabled"]}


@router.post("/fcm/test")
def test_fcm_init(admin: TokenData = Depends(require_admin)):
    """Fuerza re-init de Firebase Admin con la credencial actual y devuelve
    el resultado. Util para validar que un service account nuevo funciona
    antes de mandar pushes a usuarios reales."""
    if settings.demo_mode:
        return {
            "ok":         True,
            "demo":       True,
            "initialized": True,
            "message":    "Demo mode — no se inicializa Firebase real.",
        }

    from app.services.fcm_service import (
        _init_firebase,
        get_init_status,
        invalidate_fcm_config_cache,
    )
    # Forzamos re-init aunque ya este inicializado, para reflejar cambios recientes
    invalidate_fcm_config_cache()
    initialized = _init_firebase()
    status = get_init_status()
    return {
        "ok":          initialized,
        "initialized": initialized,
        "message":     status["last_error"] or "Firebase Admin SDK inicializado correctamente.",
        "source":      status["credential_source"],
    }


# ─── Configuración de Automatización Dinámica de Estados de Leads ──────────

class LeadAutomationReglaIntento(BaseModel):
    id: str
    nombre: Optional[str] = "Regla de intento"
    estado_destino_id: int
    min_llamadas: int = 1
    min_whatsapp: int = 0
    orden: int = 1
    activo: bool = True


class LeadAutomationReglaTiempo(BaseModel):
    id: str
    nombre: Optional[str] = "Regla de tiempo"
    estado_origen_id: int
    horas_espera: int = 12
    estado_destino_id: int
    desasignar_asesor: bool = False
    activo: bool = True


class LeadAutomationConfigPayload(BaseModel):
    enabled: bool = False
    reglas_intentos: list[LeadAutomationReglaIntento] = []
    reglas_tiempo: list[LeadAutomationReglaTiempo] = []
    excluir_contacto_efectivo: bool = True
    respetar_gestion_admin: bool = True


@router.get("/lead-automation")
def get_lead_automation_settings(admin: TokenData = Depends(require_admin)):
    """Retorna la configuración de automatizaciones de estados y el catálogo de estados disponibles."""
    from app.services.lead_automation_service import get_lead_automation_config
    from app.database import get_db
    from psycopg2.extras import RealDictCursor

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            config = get_lead_automation_config(cur)
            cur.execute("SELECT id, nombre, color_hex, es_final, orden FROM crm.estados_lead ORDER BY orden ASC, id ASC")
            estados = cur.fetchall() or []

    return {
        "config": config,
        "estados": estados,
    }


@router.put("/lead-automation")
def save_lead_automation_settings(
    payload: LeadAutomationConfigPayload,
    admin: TokenData = Depends(require_admin),
):
    """Guarda la configuración de automatización de estados. Solo admin."""
    from app.services.lead_automation_service import save_lead_automation_config

    saved = save_lead_automation_config(payload.model_dump())
    return {"ok": True, "config": saved}


@router.post("/lead-automation/run-now")
def run_lead_automation_now(admin: TokenData = Depends(require_admin)):
    """Ejecuta inmediatamente un ciclo de automatización de estados con las reglas configuradas."""
    from app.services.lead_automation_service import procesar_automatizaciones_estados_no_contesta
    result = procesar_automatizaciones_estados_no_contesta()
    return result
