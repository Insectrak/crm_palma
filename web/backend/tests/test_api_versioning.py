"""Tests para el middleware de API versioning y el endpoint /api/v1/health.

V070.73 — Bundle API Versioning (ADR-0009).
"""


class TestApiVersionHeader:
    """`X-Api-Version` debe aparecer en todas las respuestas de /api/* y /auth/*."""

    def test_api_v0_devuelve_v0_stable(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.headers.get("X-Api-Version") == "v0-stable"

    def test_api_v1_devuelve_v1(self, client):
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.headers.get("X-Api-Version") == "v1"

    def test_endpoint_root_no_lleva_header(self, client):
        # Solo /api/* y /auth/* llevan el header. La raiz no es API publico.
        response = client.get("/")
        # No importa el status (puede ser 404 o 200 segun config); el header
        # NO debe estar.
        assert response.headers.get("X-Api-Version") is None

    def test_metrics_endpoint_no_lleva_header(self, client):
        response = client.get("/metrics")
        assert response.headers.get("X-Api-Version") is None

    def test_header_se_inyecta_aun_en_404(self, client):
        """Hasta los 404 de un path /api/* deben llevar el header
        para que el consumer detecte que llego al backend correcto."""
        response = client.get("/api/no-existe-este-endpoint-xxx")
        assert response.status_code == 404
        assert response.headers.get("X-Api-Version") == "v0-stable"

    def test_header_se_inyecta_en_v2_hipotetico(self, client):
        """Si en el futuro se monta /api/v2/*, el regex matchea automaticamente."""
        # Como no hay v2 hoy, el 404 igual lleva el header v2.
        response = client.get("/api/v2/cualquier-cosa")
        assert response.status_code == 404
        assert response.headers.get("X-Api-Version") == "v2"


class TestHealthV1Schema:
    """`/api/v1/health` devuelve schema enriquecido."""

    def test_schema_v1_contiene_status_components_version_api_version(self, client):
        response = client.get("/api/v1/health")
        body = response.json()
        # v1 schema NUEVO (no estaba en v0)
        assert "status" in body
        assert "components" in body
        assert "version" in body
        assert "api_version" in body
        assert body["api_version"] == "v1"

    def test_status_es_ok_en_demo_mode(self, client):
        response = client.get("/api/v1/health")
        body = response.json()
        assert body["status"] == "ok"
        assert body["components"]["database"] in ("demo_mode", "connected", "disconnected")

    def test_v0_y_v1_no_rompen_uno_al_otro(self, client):
        """Llamar a v0 y luego v1 NO debe afectar el response del otro."""
        v0 = client.get("/api/health").json()
        v1 = client.get("/api/v1/health").json()
        # v0 mantiene el schema flat
        assert "components" not in v0  # v0 NO tiene components
        # v1 tiene el schema enriquecido
        assert "components" in v1
