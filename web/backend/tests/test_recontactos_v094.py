"""
V094: tests del re-engagement workflow (patron Salesforce / HubSpot).

Cubre:
- Default sort cambio a 'actividad_reciente' (vs 'fecha_ingreso' anterior).
  Patron clase mundial: leads recontactados burbujean al top sin que
  el asesor tenga que filtrar.
- Filtro `recontacto_sin_atender`: leads con recontacto en ultimas 48h
  pero sin ningun contacto posterior del asesor (URGENTE).
- Filtro `recontacto_recientes_horas`: ventana arbitraria de recontactos
  recientes (atendidos o no), usado por la tab "Recontactos".
- _SORT_FIELDS_MAP whitelist: 'actividad_reciente' es un valor permitido.
"""
import pytest

from app.filters.lead_filters import LeadFilters, apply_lead_filters, lead_filters_query
from app.repositories.leads_repository import _SORT_FIELDS_MAP, _build_order_by


# ── Sort: default = actividad_reciente ──────────────────────────────────────

class TestDefaultSortActividadReciente:
    """V094 — el default cambio de 'v.fecha_ingreso DESC' a
    'GREATEST(...) DESC' para que recontactos burbujeen al top."""

    @pytest.mark.unit
    def test_default_sort_es_actividad_reciente(self):
        """Sin sort explicito, usa actividad_reciente."""
        order_by = _build_order_by(None)
        assert "GREATEST" in order_by
        assert "fecha_ultimo_recontacto" in order_by
        assert "fecha_ultimo_contacto"   in order_by
        assert "fecha_asignacion"        in order_by
        assert "fecha_ingreso"           in order_by

    @pytest.mark.unit
    def test_default_sort_empty_string_tambien_es_actividad(self):
        """Sort vacio = sort None = default actividad."""
        order_by = _build_order_by("")
        assert "GREATEST" in order_by

    @pytest.mark.unit
    def test_default_tiene_tie_breaker_estable(self):
        """V070.6 — siempre se incluye `v.id DESC` al final para
        paginacion determinista. V094 no debe romper esto."""
        order_by = _build_order_by(None)
        assert order_by.rstrip().endswith("v.id DESC")

    @pytest.mark.unit
    def test_sort_explicito_fecha_ingreso_aun_funciona(self):
        """Backward compat: si el user pide fecha_ingreso, le respetamos."""
        order_by = _build_order_by("fecha_ingreso:desc")
        assert "v.fecha_ingreso DESC" in order_by
        # GREATEST NO debe estar — el user pidio explicitamente otra cosa.
        # Tie-breaker v.id DESC al final.
        assert "GREATEST" not in order_by

    @pytest.mark.unit
    def test_sort_actividad_explicito(self):
        """El user puede seleccionar actividad_reciente desde SortMenu."""
        order_by = _build_order_by("actividad_reciente:desc")
        assert "GREATEST" in order_by

    @pytest.mark.unit
    def test_sort_combinado(self):
        """Multiples sorts: actividad + nombre."""
        order_by = _build_order_by("actividad_reciente:desc,nombre_completo:asc")
        assert "GREATEST" in order_by
        assert "v.nombre_completo ASC" in order_by

    @pytest.mark.unit
    def test_actividad_reciente_en_whitelist(self):
        """No debe ser tratado como 'unknown' por el sanitizer."""
        assert "actividad_reciente" in _SORT_FIELDS_MAP


# ── Filtro: recontacto_sin_atender ─────────────────────────────────────────

class TestRecontactoSinAtender:
    """V094 — filtro urgente alimenta el banner + la tab + la card."""

    def _make_user(self, role: str = "admin"):
        from app.auth.schemas import TokenData
        return TokenData(
            user_id="00000000-0000-0000-0000-000000000001",
            email=f"{role}@test", role=role, permissions={"_all": True},
        )

    @pytest.mark.unit
    def test_filtro_off_por_default(self):
        """LeadFilters: recontacto_sin_atender default = False."""
        f = LeadFilters()
        assert f.recontacto_sin_atender is False

    @pytest.mark.unit
    def test_filtro_off_no_agrega_clausula(self):
        """Sin filtro activo, no debe agregar ningun WHERE relacionado."""
        f = LeadFilters()
        where, _ = apply_lead_filters(f, self._make_user())
        assert "fecha_ultimo_recontacto" not in where

    @pytest.mark.unit
    def test_filtro_on_agrega_clausula_sin_atender(self):
        """V094.1 — filtro retorna TODOS los leads con recontacto pendiente
        de respuesta, SIN cap de 48h. La escalacion de severidad se hace
        en la UI via /recontactos-summary (amber <48h vs red >=48h)."""
        f = LeadFilters(recontacto_sin_atender=True)
        where, _ = apply_lead_filters(f, self._make_user())
        assert "fecha_ultimo_recontacto IS NOT NULL" in where
        assert "NOT EXISTS" in where
        assert "c.created_at > l.fecha_ultimo_recontacto" in where
        # V094.1 — el cap "INTERVAL '48 hours'" YA NO esta aqui (antes si).
        # Si lo vuelven a meter aca por accidente, recontactos viejos quedan
        # invisibles otra vez y el banner rojo no funcionaria.
        # El cap esta SOLO en el endpoint /recontactos-summary para clasificar
        # amber vs red, no para filtrar.
        # Nota: el FILTRO recontacto_recientes_horas (otro filtro) si usa
        # INTERVAL — por eso buscamos exactamente "INTERVAL '48 hours'".
        assert "INTERVAL '48 hours'" not in where

    @pytest.mark.unit
    def test_filtro_recientes_horas_param(self):
        """recontacto_recientes_horas con valor agrega ventana custom."""
        f = LeadFilters(recontacto_recientes_horas=24)
        where, params = apply_lead_filters(f, self._make_user())
        assert "fecha_ultimo_recontacto IS NOT NULL" in where
        assert "(%s || ' hours')::INTERVAL" in where
        assert "24" in params

    @pytest.mark.unit
    def test_filtro_recientes_horas_none_no_agrega(self):
        """Sin valor explicito, no agrega la clausula."""
        f = LeadFilters(recontacto_recientes_horas=None)
        where, _ = apply_lead_filters(f, self._make_user())
        assert "(%s || ' hours')::INTERVAL" not in where

    @pytest.mark.unit
    def test_filtro_recientes_horas_cero_no_agrega(self):
        """Defensa: 0 horas se trata como None (no tiene sentido logico)."""
        f = LeadFilters(recontacto_recientes_horas=0)
        where, _ = apply_lead_filters(f, self._make_user())
        assert "(%s || ' hours')::INTERVAL" not in where

    @pytest.mark.unit
    def test_lead_filters_query_pasa_los_nuevos_campos(self):
        """La FastAPI dependency mapea los query params nuevos correctamente."""
        f = lead_filters_query(
            recontacto_sin_atender=True,
            recontacto_recientes_horas=48,
        )
        assert f.recontacto_sin_atender is True
        assert f.recontacto_recientes_horas == 48


# ── Smoke: ambos filtros juntos no rompen (caso real del banner+tab) ──────

@pytest.mark.unit
def test_filtros_combinados_smoke():
    """Banner usa sin_atender (V094.1 sin cap), tab usa recientes_horas —
    distintos contextos. Aplicar ambos a la vez no debe romper."""
    from app.auth.schemas import TokenData
    user = TokenData(user_id="x", email="a@a", role="admin", permissions={"_all": True})
    f = LeadFilters(recontacto_sin_atender=True, recontacto_recientes_horas=48)
    where, params = apply_lead_filters(f, user)
    # Ambas clausulas presentes.
    assert "NOT EXISTS" in where
    assert "(%s || ' hours')::INTERVAL" in where
    assert "48" in params


@pytest.mark.unit
def test_v094_1_sin_atender_sin_cap_48h():
    """V094.1 regression — el filtro recontacto_sin_atender NO debe tener
    el cap '48 hours' que tenia en V094. Si vuelve a aparecer ahi, el
    banner rojo no funcionaria (recontactos viejos quedarian fuera del
    NOT EXISTS check)."""
    from app.auth.schemas import TokenData
    user = TokenData(user_id="x", email="a@a", role="admin", permissions={"_all": True})
    f = LeadFilters(recontacto_sin_atender=True)
    where, _ = apply_lead_filters(f, user)
    # Defensa explicita: NO debe estar el cap de 48h en el filtro.
    assert "INTERVAL '48 hours'" not in where
    # Pero la condicion de "no contacto posterior" SI debe estar.
    assert "c.created_at > l.fecha_ultimo_recontacto" in where
