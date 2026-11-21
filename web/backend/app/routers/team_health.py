"""Endpoint /api/v1/team-health — estado operacional de los equipos.

V070.78 (ADR-0010 — Team Circuit Breaker).

Devuelve el estado de cada equipo (active/at_risk/blocked) + metricas
de carga. Usado por:
  - Frontend admin: badges en Configuracion → Equipos.
  - Frontend supervisor: banner cuando su equipo esta bloqueado.
  - Dashboards externos (Grafana via Prometheus tambien lo expone).

Auth:
  - admin: ve TODOS los equipos.
  - supervisor: ve SOLO su equipo (filtro por supervisor_id = current_user.user_id).
  - asesor: 403 (no es para ellos).
"""
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.auth.jwt import get_current_user
from app.auth.schemas import TokenData
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/team-health", tags=["Team Health (v1)"])


@router.get("/")
def get_team_health(current_user: TokenData = Depends(get_current_user)):
    """Devuelve el estado de los equipos.

    Schema de respuesta:
    ```json
    {
      "teams": [
        {
          "supervisor_id":     "uuid",
          "supervisor_nombre": "Paola Cuadros",
          "supervisor_email":  "paola@...",
          "status":            "blocked" | "at_risk" | "active",
          "previous_status":   "blocked" | "at_risk" | "active" | null,
          "total_asesores":     4,
          "asesores_pausados":  4,
          "pct_pausados":       1.0
        },
        ...
      ],
      "summary": {
        "active":  1,
        "at_risk": 0,
        "blocked": 1
      }
    }
    ```
    """
    if current_user.role not in ("admin", "supervisor"):
        raise HTTPException(403, "Solo admin y supervisores pueden ver team-health")

    if settings.demo_mode:
        return {
            "teams":   [],
            "summary": {"active": 0, "at_risk": 0, "blocked": 0},
            "demo":    True,
        }

    from app.database import get_db
    from psycopg2.extras import RealDictCursor
    from app.services.team_health_service import get_team_health_summary

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            teams = get_team_health_summary(cur)

    # Filtro por rol: supervisor solo ve su propio equipo
    if current_user.role == "supervisor":
        teams = [t for t in teams if t["supervisor_id"] == current_user.user_id]

    summary = {"active": 0, "at_risk": 0, "blocked": 0}
    for t in teams:
        summary[t["status"]] = summary.get(t["status"], 0) + 1

    return {"teams": teams, "summary": summary}
