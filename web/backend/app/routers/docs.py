"""
Endpoint para servir documentacion del proyecto a la UI.

Hoy en dia: solo expone /api/docs/integracion-proveedores que devuelve el
markdown de docs/INTEGRACION_PROVEEDORES.md tal cual.

Por que esta como endpoint y no como link a servicio externo:
  - El admin del CRM puede no tener acceso al repo
  - El doc evoluciona con el codigo (V053 agrego campos) — siempre devuelve
    la version desplegada, no la del repo publico
  - Permite agregar nuevos docs en el futuro (DPA template, FAQ, etc)
    sin tocar el frontend

Auth: requiere admin/supervisor (igual que /api/admin/api-clients/*).
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from app.auth.jwt import require_supervisor_or_admin
from app.auth.schemas import TokenData

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/docs", tags=["Docs"])

# Ubicacion de los docs servibles desde el backend. Tienen que vivir
# DENTRO de web/backend para que el Dockerfile (cuyo build context es
# ./backend) los incluya en la imagen. La copia canonica vive en
# <repo>/docs/, esta carpeta es una copia desplegable.
#
# REGLA: cuando edites <repo>/docs/INTEGRACION_PROVEEDORES.md, copia
# tambien a <repo>/web/backend/docs_static/ para que el deploy quede
# sincronizado. (Si en algun momento esto da problema, agregar un check
# en CI que compare los archivos byte a byte).
_BACKEND_ROOT = Path(__file__).resolve().parents[2]      # → web/backend
_DOCS_DIR = _BACKEND_ROOT / "docs_static"

# Whitelist de docs que se exponen via API. Agregar aqui si se quiere
# servir uno nuevo — no permitimos servir cualquier archivo del repo.
_ALLOWED_DOCS = {
    "integracion-proveedores": "INTEGRACION_PROVEEDORES.md",
}


def _resolve_crm_base_url(request: Request) -> str:
    """Resuelve el dominio base del CRM que esta sirviendo este doc.

    Delega al helper centralizado en utils/url_helpers.py — mismo orden de
    precedencia que usan los emails de invitacion (settings.public_base_url
    -> X-Forwarded-* -> CORS heuristic -> request.base_url).
    """
    from app.utils.url_helpers import resolve_public_base_url
    return resolve_public_base_url(request)


def _strip_internal_footer(content: str) -> str:
    """Quita la seccion de version/changelog del doc antes de servirlo.

    Esa seccion es util en el archivo fuente (git, tracking de cambios,
    revision interna) pero satura el modal del cliente. Buscamos el
    marker '**Versión del documento:**' y cortamos desde el separador
    '---' previo hasta el final del archivo.
    """
    marker = "**Versión del documento:**"
    idx = content.find(marker)
    if idx == -1:
        return content
    head = content[:idx].rstrip()
    # Si hay un '---' como separador antes del footer, removemoslo tambien
    # para no dejar un separador huerfano al final.
    if head.endswith("---"):
        head = head[:-3].rstrip()
    return head + "\n"


@router.get("/{slug}")
def get_doc(
    slug: str,
    request: Request,
    _admin: TokenData = Depends(require_supervisor_or_admin),
):
    """Devuelve el contenido markdown del doc indicado.

    Slug whitelisted — si no esta en _ALLOWED_DOCS responde 404 sin
    revelar que paths existen en el repo.

    Substituye placeholders en el doc:
      - {{CRM_BASE_URL}} → dominio real desde el cual se esta sirviendo
        el doc. Asi el admin ve los curls listos para copiar/pegar sin
        tener que cambiar manualmente la URL.
    """
    filename = _ALLOWED_DOCS.get(slug)
    if not filename:
        raise HTTPException(404, "Doc no encontrado")

    path = _DOCS_DIR / filename
    if not path.is_file():
        logger.error("Doc whitelisted pero archivo no existe: %s", path)
        raise HTTPException(500, "Doc no disponible — contacta al equipo tecnico")

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.exception("Error leyendo doc %s: %s", path, exc)
        raise HTTPException(500, "Error leyendo el doc")

    # Substitucion de placeholders. Si en el futuro hay mas, se puede
    # generalizar a un dict — por ahora hay uno solo.
    content = content.replace("{{CRM_BASE_URL}}", _resolve_crm_base_url(request))

    # Quita el changelog/footer interno antes de servir al admin del CRM.
    content = _strip_internal_footer(content)

    return Response(content=content, media_type="text/markdown; charset=utf-8")
