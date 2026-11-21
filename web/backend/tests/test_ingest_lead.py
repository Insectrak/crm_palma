"""Tests del flujo POST /api/ingest/leads.

Antes del 2026-05-15 este path tuvo 5 bugs encadenados que se descubrieron
en producción manualmente (KeyError silencioso, regex colisión, fuente
ignorada, etc). Esta suite cubre los casos críticos para que cualquier
regresión salte en CI antes de llegar a producción.

Estrategia (V070.67):
  - Tests unitarios de funciones puras (clean_phone) — sin mocks.
  - Tests del endpoint con DEMO_MODE=true + mocks de get_db/ingest_lead_core
    para validar autenticación, validación de payload y resolución de fuente
    sin depender de Postgres real.

Casos cubiertos:
  1. Teléfono válido peruano de 9 dígitos → +51XXXXXXXXX
  2. Teléfono inválido de 8 dígitos → rechazado
  3. Teléfono internacional E.164 → aceptado
  4. Teléfono con separadores → normalizado
  5. Payload sin teléfono → 422 Pydantic validation
  6. Payload sin fuente y sin auth multi-tenant → 400
  7. API key ausente → 401
  8. API key inválida → 401
"""
import pytest


# ════════════════════════════════════════════════════════════════════════════
# TESTS UNITARIOS — clean_phone
# ════════════════════════════════════════════════════════════════════════════

class TestCleanPhone:
    """V070.58 — validación E.164 estricta para móvil peruano + internacional."""

    def test_movil_peruano_9_digitos(self):
        from app.services.integrations.ingest_core import clean_phone
        assert clean_phone("987654321") == "+51987654321"

    def test_movil_peruano_con_codigo_pais(self):
        from app.services.integrations.ingest_core import clean_phone
        assert clean_phone("51987654321") == "+51987654321"

    def test_movil_peruano_con_separadores(self):
        from app.services.integrations.ingest_core import clean_phone
        assert clean_phone("+51 987 654 321") == "+51987654321"
        assert clean_phone("(987) 654-321") == "+51987654321"

    def test_rechaza_telefono_8_digitos(self):
        """Bug histórico: '97845323' (8 dígitos) se aceptaba como '97845323'.

        En PE los celulares siempre son 9 dígitos empezando con 9.
        8 dígitos = casi seguro un error de tipeo o fijo sin código de área.
        """
        from app.services.integrations.ingest_core import clean_phone
        assert clean_phone("97845323") is None

    def test_rechaza_telefono_7_digitos(self):
        from app.services.integrations.ingest_core import clean_phone
        assert clean_phone("1234567") is None

    def test_rechaza_telefono_vacio(self):
        from app.services.integrations.ingest_core import clean_phone
        assert clean_phone("") is None
        assert clean_phone(None) is None
        assert clean_phone("000000000") is None  # solo ceros

    def test_acepta_internacional_e164(self):
        """Otro país en formato E.164 (10-15 dígitos)."""
        from app.services.integrations.ingest_core import clean_phone
        # Argentina (13 dígitos con código)
        assert clean_phone("+5491150000000") == "+5491150000000"
        # USA (11 dígitos con código país)
        assert clean_phone("+12025550100") == "+12025550100"

    def test_rechaza_mas_de_15_digitos(self):
        from app.services.integrations.ingest_core import clean_phone
        assert clean_phone("1234567890123456") is None  # 16 dígitos

    def test_rechaza_9_digitos_que_no_empieza_con_9(self):
        """Móvil peruano debe empezar con 9."""
        from app.services.integrations.ingest_core import clean_phone
        assert clean_phone("123456789") is None

    # ── V070.96 — Anti-junk: patrones obvios de número falso ────────────

    def test_v070_96_rechaza_todos_los_digitos_iguales_pe(self):
        """Bug reportado en prod: referido con +51999999999 (todos 9s)
        pasaba validacion porque cumplia formato E.164 (519 + 9 digitos).
        Ahora se rechaza por patron junk."""
        from app.services.integrations.ingest_core import clean_phone
        assert clean_phone("+51999999999") is None
        assert clean_phone("+51111111111") is None
        assert clean_phone("999999999") is None
        assert clean_phone("111111111") is None

    def test_v070_96_acepta_numero_real_pe_normal(self):
        """Sanity: numeros reales validos no deben caer en anti-junk."""
        from app.services.integrations.ingest_core import clean_phone
        assert clean_phone("987654321") == "+51987654321"
        assert clean_phone("+51 986 777 920") == "+51986777920"
        assert clean_phone("951234567") == "+51951234567"

    def test_v070_96_rechaza_10_digitos_sin_codigo_pais(self):
        """Bug observado: numeros de 10 digitos sin codigo pais entraban
        como E.164 'internacional' pero son ambiguos (USA local? PE
        truncado?). Salesforce/HubSpot exigen codigo pais explicito."""
        from app.services.integrations.ingest_core import clean_phone
        assert clean_phone("9876543210") is None
        assert clean_phone("2025550100") is None

    def test_v070_96_rechaza_hardcoded_test_numbers(self):
        """Numeros conocidos de pruebas que aparecen en seeds, demos
        y documentacion son junk en produccion."""
        from app.services.integrations.ingest_core import clean_phone
        assert clean_phone("+15555555555") is None  # +1 555 555 5555
        assert clean_phone("+11234567890") is None
        assert clean_phone("+10000000000") is None


# ════════════════════════════════════════════════════════════════════════════
# TESTS DEL ENDPOINT — POST /api/ingest/leads
# ════════════════════════════════════════════════════════════════════════════

class TestIngestEndpointAuth:
    """Auth dual: multi-tenant (cli_*) y legacy (INGEST_API_KEY).

    Estos tests usan dependency_overrides de FastAPI para evitar tocar la
    DB real (que en DEMO_MODE no existe). Solo verifican el contrato HTTP
    del endpoint, no la lógica interna de autenticación contra Postgres.
    """

    def test_sin_api_key_devuelve_401(self, client):
        """Header X-Api-Key ausente → 401 'API key ausente.'

        Único caso que NO requiere mock: la guard `if not x_api_key` se
        evalúa antes de cualquier llamada a DB, así que en DEMO_MODE
        responde 401 sin crashear.
        """
        response = client.post(
            "/api/ingest/leads",
            json={"fuente": "web", "telefono": "+51987654321"},
        )
        assert response.status_code == 401
        assert "API key" in response.json()["detail"]

    def test_api_key_invalida_devuelve_401(self, app_instance, client):
        """Key con formato cli_ pero inválida → 401.

        Mockeamos authenticate_ingest para simular el camino 'auth falla
        en lookup' sin necesidad de DB real.
        """
        from fastapi import HTTPException
        from app.routers.ingest import authenticate_ingest

        def fake_auth_invalid():
            raise HTTPException(401, "API key inválida.")

        app_instance.dependency_overrides[authenticate_ingest] = fake_auth_invalid
        try:
            response = client.post(
                "/api/ingest/leads",
                headers={"X-Api-Key": "cli_inexistente_xxx"},
                json={"fuente": "web", "telefono": "+51987654321"},
            )
            assert response.status_code == 401
            assert "API key" in response.json()["detail"]
        finally:
            app_instance.dependency_overrides.pop(authenticate_ingest, None)


class TestIngestEndpointValidation:
    """Validación de payload — Pydantic + reglas de negocio.

    FastAPI resuelve dependencies ANTES de validar el body Pydantic,
    así que necesitamos mockear authenticate_ingest para evitar que
    se intente acceder a la DB durante los tests de validation.
    """

    @pytest.fixture(autouse=True)
    def _override_auth(self, app_instance):
        from app.routers.ingest import authenticate_ingest, IngestAuth

        def fake_auth_ok():
            client_row = {
                "id":                    "00000000-0000-0000-0000-000000000099",
                "api_key_prefix":        "test_xxx",
                "fuente_id":             None,
                "sede_id_default":       None,
                "rate_limit_per_minute": 1000,
                "nombre":                "Test Client",
            }
            return IngestAuth(client=client_row, key_prefix="test_xxx")

        app_instance.dependency_overrides[authenticate_ingest] = fake_auth_ok
        yield
        app_instance.dependency_overrides.pop(authenticate_ingest, None)

    def test_sin_telefono_devuelve_422(self, client):
        """Pydantic rechaza payload sin campo obligatorio 'telefono'."""
        response = client.post(
            "/api/ingest/leads",
            headers={"X-Api-Key": "cli_test_xxx"},
            json={"fuente": "web"},  # falta telefono
        )
        assert response.status_code == 422
        body = response.json()
        assert any(
            "telefono" in str(e.get("loc", []))
            for e in body.get("detail", [])
        )

    def test_sin_fuente_devuelve_422(self, client):
        """Sin fuente en body → 422 (Pydantic require el campo).

        Nota: en IngestLead actual, `fuente: str` es required, así que
        Pydantic rechaza con 422 antes de llegar a la lógica del fallback
        al default del client. Si en el futuro se relaja a Optional[str],
        este test debería cambiar a esperar 400 (mensaje del endpoint).
        """
        response = client.post(
            "/api/ingest/leads",
            headers={"X-Api-Key": "cli_no_fuente"},
            json={"telefono": "+51987654321"},  # sin fuente
        )
        assert response.status_code == 422
        body = response.json()
        assert any(
            "fuente" in str(e.get("loc", []))
            for e in body.get("detail", [])
        )


class TestIngestEndpointSchema:
    """Verifica que el shape del payload soportado no se rompa."""

    def test_payload_minimo_pasa_validation_pydantic(self):
        """IngestLead acepta los campos mínimos sin error."""
        from app.routers.ingest import IngestLead
        lead = IngestLead(fuente="web", telefono="+51987654321")
        assert lead.fuente == "web"
        assert lead.telefono == "+51987654321"

    def test_payload_completo_acepta_todos_los_campos_ia(self):
        """V053 — proveedor IA puede mandar nivel, resumen_ia, extra, etc."""
        from app.routers.ingest import IngestLead
        lead = IngestLead(
            fuente="instagram",
            telefono="+51987654321",
            nombres="María",
            apellidos="García",
            email="maria@test.com",
            dni="40123456",
            campana="Promo Mayo 2026",
            conjunto="Geolocalizado 25-45",
            anuncio="LEAD AD - FACHADA",
            fuente_externa_id="META-leadgen-123",
            external_created_at="2026-05-15T14:32:18Z",
            form_name="Formulario informativo",
            nivel="Contactado",
            asesor_telefono="51987000000",
            resumen_ia="Cliente interesado en 2 dormitorios.",
            extra={"presupuesto_max": "220000", "habitaciones": "2"},
            observaciones="Test full payload",
        )
        assert lead.fuente == "instagram"
        assert lead.nivel == "Contactado"
        assert lead.extra["habitaciones"] == "2"
        assert lead.resumen_ia.startswith("Cliente interesado")

    def test_external_created_at_acepta_z_y_offset(self):
        """ISO 8601 con Z (UTC) o con offset explícito (-05:00)."""
        from app.routers.ingest import IngestLead
        lead1 = IngestLead(
            fuente="web", telefono="+51987654321",
            external_created_at="2026-05-15T14:32:18Z",
        )
        lead2 = IngestLead(
            fuente="web", telefono="+51987654321",
            external_created_at="2026-05-15T09:32:18-05:00",
        )
        assert lead1.external_created_at.endswith("Z")
        assert lead2.external_created_at.endswith("-05:00")
