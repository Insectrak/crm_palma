"""
public_forms.py — Router de formularios públicos.

Dos áreas:
  1. Endpoints privados (`/api/public-forms/*`)
     - CRUD + QR + conteo de leads
     - Protegidos por JWT + rol admin/supervisor (enforced en service).

  2. Endpoints públicos (`/api/f/*`)
     - GET  /api/f/:slug        → metadata para renderizar el form
     - POST /api/f/:slug/submit → enviar el form (crea lead)
     - Sin auth, con rate limit agresivo por IP (slowapi) y anti-spam en service.

Todas las reglas viven en `services.public_forms_service`. Este router es
solo HTTP/serialización — SRP + DIP respetados.
"""
from __future__ import annotations

import io
import logging
from typing import Any, Optional

import qrcode
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth.jwt import get_current_user
from app.auth.rate_limit import limiter
from app.auth.schemas import TokenData
from app.config import settings
from app.services import public_forms_service

logger = logging.getLogger(__name__)


# ── Schemas Pydantic ─────────────────────────────────────────────────────────

class FormCampoIn(BaseModel):
    key: str = Field(..., min_length=1, max_length=30)
    label: Optional[str] = None
    required: bool = False
    type: str = "text"


class FormConfigIn(BaseModel):
    campos: list[FormCampoIn] = Field(..., min_length=1)
    mensaje_exito: Optional[str] = None
    redirect_url: Optional[str] = None


class CreateFormIn(BaseModel):
    titulo: str = Field(..., min_length=3, max_length=120)
    descripcion: Optional[str] = Field(None, max_length=2000)
    nombre_evento: Optional[str] = Field(None, max_length=200)
    empresa: Optional[str] = Field(None, max_length=200)
    fuente_id: Optional[int] = None
    campana: Optional[str] = Field(None, max_length=200)
    config: FormConfigIn
    expires_at: Optional[str] = None        # ISO-8601 o None
    max_submissions: Optional[int] = Field(None, ge=1)
    sede_id_default: Optional[str] = None   # V065: sede asignada a leads de este form
    asignado_a: Optional[str] = None        # Asesor o supervisor al que le llegarán los leads


class UpdateFormIn(BaseModel):
    titulo: Optional[str] = Field(None, min_length=3, max_length=120)
    descripcion: Optional[str] = Field(None, max_length=2000)
    nombre_evento: Optional[str] = Field(None, max_length=200)
    empresa: Optional[str] = Field(None, max_length=200)
    fuente_id: Optional[int] = None
    campana: Optional[str] = Field(None, max_length=200)
    config: Optional[FormConfigIn] = None
    activo: Optional[bool] = None
    expires_at: Optional[str] = None
    max_submissions: Optional[int] = Field(None, ge=1)
    sede_id_default: Optional[str] = None   # V065
    asignado_a: Optional[str] = None


class SubmitFormIn(BaseModel):
    """Submission pública.

    - `data` contiene los campos del lead (nombres, telefono, email, etc.).
    - `website` es honeypot: debe venir vacío siempre (bots lo llenarán).
    - `_elapsed` es el tiempo desde el load del form; rechazamos <2s.
    """
    data: dict[str, Any] = Field(default_factory=dict)
    website: Optional[str] = None   # honeypot
    elapsed: Optional[float] = Field(None, alias="_elapsed")

    class Config:
        populate_by_name = True


# ── Helpers ─────────────────────────────────────────────────────────────────

def _serialize_form(form: dict) -> dict:
    """Normaliza UUID/datetime a strings para JSON."""
    out = dict(form)
    for key in ("id", "fuente_id", "asignado_a", "created_by", "origen_form_id",
                "sede_id_default"):  # V065
        if key in out and out[key] is not None:
            out[key] = str(out[key])
    for key in ("created_at", "updated_at", "expires_at"):
        if out.get(key) is not None:
            out[key] = out[key].isoformat()
    return out


def _client_ip(request: Request) -> Optional[str]:
    """Devuelve la IP del cliente respetando X-Forwarded-For si el proxy lo setea.

    Nota: en producción detrás de EasyPanel/Traefik el header viene poblado.
    En dev local viene None → no se aplica rate limit por IP en repo.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    client = request.client
    return client.host if client else None


# ── Routers ──────────────────────────────────────────────────────────────────

# Privado: /api/public-forms/* (requiere JWT + rol)
private_router = APIRouter(prefix="/api/public-forms", tags=["Formularios públicos"])

# Público: /api/f/* (sin auth, con rate limit)
public_router = APIRouter(prefix="/api/f", tags=["Formularios públicos (público)"])

# Rate limits configurables vía settings. Se leen a module-load porque los
# decoradores de slowapi capturan la expresión literal en tiempo de import —
# cambiar el .env requiere reiniciar el contenedor, cosa coherente con el
# resto de settings (12-factor: config en el ambiente).
_RATE_LIMIT_GET_PUBLIC    = settings.public_form_rate_limit_get
_RATE_LIMIT_SUBMIT_PUBLIC = settings.public_form_rate_limit_submit


# ── Privado: CRUD ───────────────────────────────────────────────────────────

@private_router.get("")
def list_forms(
    include_archived: bool = False,
    current_user: TokenData = Depends(get_current_user),
):
    """Lista forms visibles para el usuario.

    - admin: todos los forms
    - supervisor: sus propios forms
    - asesor: 403 (enforced en service)
    """
    try:
        forms = public_forms_service.list_forms(
            current_user, include_archived=include_archived,
        )
        return {"items": [_serialize_form(f) for f in forms]}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        # Log con stack completo para diagnóstico. Respuesta genérica al cliente.
        logger.exception("Error listando formularios públicos: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="No se pudieron cargar los formularios. Revisa logs del servidor.",
        )


@private_router.get("/assignees")
def list_assignees(
    current_user: TokenData = Depends(get_current_user),
):
    """Lista asesores y supervisores a los que se puede asignar un formulario."""
    items = public_forms_service.list_eligible_assignees(current_user)
    return {"items": items}


@private_router.post("", status_code=status.HTTP_201_CREATED)
def create_form(
    body: CreateFormIn,
    current_user: TokenData = Depends(get_current_user),
):
    try:
        form = public_forms_service.create_form(
            current_user=current_user,
            titulo=body.titulo,
            descripcion=body.descripcion,
            nombre_evento=body.nombre_evento,
            empresa=body.empresa,
            fuente_id=body.fuente_id,
            campana=body.campana,
            config=body.config.model_dump(),
            expires_at=body.expires_at,
            max_submissions=body.max_submissions,
            sede_id_default=body.sede_id_default,
            asignado_a=body.asignado_a,
        )
        return _serialize_form(form)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error creando formulario público: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="No se pudo crear el formulario. Revisa logs del servidor.",
        )


@private_router.get("/{form_id}")
def get_form_detail(
    form_id: str,
    current_user: TokenData = Depends(get_current_user),
):
    form = public_forms_service.get_form_private(form_id, current_user)
    # V093 — desglose total/nuevos/recontactos. `leads_count` se mantiene
    # como compat con la UI legacy (apunta a leads_nuevos del breakdown).
    breakdown = public_forms_service.count_breakdown_for_form(form_id, current_user)
    return {
        **_serialize_form(form),
        "leads_count":      breakdown["leads_nuevos"],  # compat legacy
        "captures_breakdown": breakdown,
    }


@private_router.patch("/{form_id}")
def update_form(
    form_id: str,
    body: UpdateFormIn,
    current_user: TokenData = Depends(get_current_user),
):
    # Solo enviar al service los campos explícitamente presentes en el body
    fields = body.model_dump(exclude_unset=True)
    if "config" in fields and fields["config"] is not None:
        # FormConfigIn → dict plano
        fields["config"] = body.config.model_dump()  # type: ignore[union-attr]
    updated = public_forms_service.update_form(form_id, fields, current_user)
    return _serialize_form(updated)


@private_router.delete("/{form_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_form(
    form_id: str,
    current_user: TokenData = Depends(get_current_user),
):
    """Soft delete: `activo = FALSE`. No borra filas para preservar auditoría."""
    public_forms_service.archive_form(form_id, current_user)
    return None


@private_router.delete("/{form_id}/permanent", status_code=status.HTTP_204_NO_CONTENT)
def delete_form_permanent(
    form_id: str,
    current_user: TokenData = Depends(get_current_user),
):
    """Hard delete — borrado físico. Solo admin, solo si ya está archivado.

    Cascadas:
      - public_form_submissions → eliminadas
      - leads.origen_form_id    → SET NULL (los leads se conservan)
    """
    public_forms_service.delete_form_permanent(form_id, current_user)
    return None


@private_router.get("/{form_id}/qr")
def get_form_qr(
    form_id: str,
    request: Request,
    current_user: TokenData = Depends(get_current_user),
):
    """Devuelve el QR del form como PNG. Solo admin o dueño.

    La URL embebida se construye a partir del request actual (host real donde
    el admin está accediendo) — esto garantiza que el QR siempre apunte al
    dominio correcto sin importar lo que haya en ALLOWED_ORIGINS. Respeta
    X-Forwarded-Proto / X-Forwarded-Host (Traefik/EasyPanel los setean).
    Fallback a ALLOWED_ORIGINS[0] si por alguna razón no hay host en el
    request (ej. tests).
    """
    form = public_forms_service.get_form_private(form_id, current_user)

    forwarded_host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
    )
    if forwarded_host:
        scheme = (
            request.headers.get("x-forwarded-proto")
            or request.url.scheme
            or "https"
        )
        base = f"{scheme}://{forwarded_host}"
    else:
        origins = settings.get_allowed_origins()
        base = origins[0] if origins else "http://localhost:5173"

    public_url = f"{base.rstrip('/')}/f/{form['slug']}"

    img = qrcode.make(public_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="image/png",
        headers={
            "Content-Disposition": f'inline; filename="form-{form["slug"]}.png"',
            # URL embebida como header para debug/logging
            "X-Form-Url": public_url,
        },
    )


# ── Público: vista + submit ─────────────────────────────────────────────────

@public_router.get("/{slug}")
@limiter.limit(_RATE_LIMIT_GET_PUBLIC)
def get_public_form(slug: str, request: Request):
    """Metadata pública del form — lo que el frontend necesita para renderizar.

    No devuelve info interna (created_by, asignado_a, stats).
    """
    return public_forms_service.get_form_public(slug)


@public_router.post("/{slug}/submit")
@limiter.limit(_RATE_LIMIT_SUBMIT_PUBLIC)
def submit_public_form(
    slug: str,
    body: SubmitFormIn,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Recibe una submission pública y crea el lead.

    Capas de defensa contra spam:
      - slowapi rate limit por IP (10/min globalmente)
      - honeypot field `website`
      - min-time `_elapsed` < 2s
      - rate limit per-form por IP en ventana de 10min (en service)

    `background_tasks` se inyecta para que el push notification al asesor
    se ejecute DESPUES de devolver la respuesta HTTP — el cliente que
    submitea el form no espera por FCM (que puede tomar cientos de ms).
    """
    try:
        return public_forms_service.submit_public_form(
            slug=slug,
            payload=body.data or {},
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            elapsed_seconds=body.elapsed,
            background_tasks=background_tasks,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — log y respuesta genérica
        logger.exception("Error procesando submit público slug=%s: %s", slug, exc)
        raise HTTPException(status_code=500, detail="Error procesando el envío.")
