"""Tests para el endpoint /metrics y /api/internal/metrics/backup-success.

V070.72 — Bundle Observability (docs/SLO.md).
"""
import os
import subprocess
import sys
import textwrap

import pytest


class TestPrometheusMetricsEndpoint:
    """`/metrics` debe exponer formato Prometheus text plain."""

    def test_metrics_endpoint_responde_text_plain(self, client):
        # En CI no esta protegido (METRICS_ENDPOINT_PROTECTED no seteada).
        response = client.get("/metrics")
        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        # Prometheus expone text/plain; version=0.0.4
        assert "text/plain" in content_type

    def test_metrics_incluye_metricas_http_auto_instrumentadas(self, client):
        # Pegamos a un endpoint cualquiera para generar al menos 1 hit.
        client.get("/api/health")
        # Y luego pedimos /metrics
        response = client.get("/metrics")
        body = response.text
        # Debe contener al menos:
        # - http_requests_total (counter del instrumentator)
        # - http_request_duration_seconds (histogram)
        # - wa_webhook_processed_total (custom)
        # - crm_backup_last_success_timestamp_seconds (custom gauge)
        assert "http_requests_total" in body or "http_requests_inprogress" in body
        assert "wa_webhook_processed_total" in body
        assert "crm_backup_last_success_timestamp_seconds" in body


class TestBackupReportEndpoint:
    """`/api/internal/metrics/backup-success` recibe pings de n8n."""

    def test_sin_token_devuelve_401_o_503(self, client, monkeypatch):
        """Si no hay token interno o el header esta ausente → rechazo."""
        monkeypatch.setenv("N8N_INTERNAL_KEY", "test-internal-key")
        response = client.post(
            "/api/internal/metrics/backup-success",
            json={"timestamp": 1700000000, "size_bytes": 1024, "tenant_slug": "test"},
        )
        assert response.status_code == 401

    def test_sin_env_var_devuelve_503(self, client, monkeypatch):
        """Si la env var N8N_INTERNAL_KEY no esta configurada → 503."""
        monkeypatch.delenv("N8N_INTERNAL_KEY", raising=False)
        response = client.post(
            "/api/internal/metrics/backup-success",
            headers={"X-Internal-Token": "cualquiera"},
            json={"timestamp": 1700000000, "size_bytes": 1024, "tenant_slug": "test"},
        )
        assert response.status_code == 503

    def test_token_correcto_actualiza_gauge_y_responde_204(self, client, monkeypatch):
        from app.metrics import (
            crm_backup_last_success_timestamp_seconds,
            crm_backup_size_bytes,
        )

        monkeypatch.setenv("N8N_INTERNAL_KEY", "secret-internal-key-xxx")

        ts = 1700000000
        size = 5 * 1024 * 1024  # 5MB

        response = client.post(
            "/api/internal/metrics/backup-success",
            headers={"X-Internal-Token": "secret-internal-key-xxx"},
            json={"timestamp": ts, "size_bytes": size, "tenant_slug": "acme_corp"},
        )
        assert response.status_code == 204

        # Verificar que el gauge se actualizo (Prometheus client expone .get())
        assert crm_backup_last_success_timestamp_seconds._value.get() == ts
        assert crm_backup_size_bytes._value.get() == size

    def test_payload_invalido_devuelve_422(self, client, monkeypatch):
        monkeypatch.setenv("N8N_INTERNAL_KEY", "secret")
        response = client.post(
            "/api/internal/metrics/backup-success",
            headers={"X-Internal-Token": "secret"},
            json={"timestamp": "not-a-number", "size_bytes": -1, "tenant_slug": ""},
        )
        assert response.status_code == 422


class TestCustomMetricsImports:
    """Verifica que todos los simbolos publicos de metrics.py importan limpios."""

    def test_imports_no_levantan(self):
        from app.metrics import (  # noqa: F401
            auth_login_attempts,
            crm_backup_last_success_timestamp_seconds,
            crm_backup_size_bytes,
            db_pool_connections_active,
            db_pool_connections_max,
            fcm_push_sent,
            ingest_leads,
            setup_metrics,
            wa_messages_processed,
            wa_webhook_processed,
        )

    def test_counters_aceptan_labels_definidos(self):
        from app.metrics import (
            fcm_push_sent,
            ingest_leads,
            wa_webhook_processed,
        )
        # No deberian levantar — todos los labels coinciden con la definicion.
        wa_webhook_processed.labels(status="ok").inc()
        wa_webhook_processed.labels(status="invalid_signature").inc()
        fcm_push_sent.labels(result="success").inc()
        ingest_leads.labels(api_client_prefix="acme", fuente="facebook", result="created").inc()

    def test_counter_con_label_invalido_levanta(self):
        from app.metrics import wa_webhook_processed
        with pytest.raises(ValueError):
            # Label desconocido para este counter
            wa_webhook_processed.labels(otro_label="x")


class TestMetricsProtectedMode:
    """Regresion para el bug V070.74:

    En PROD se reporto que /metrics con METRICS_ENDPOINT_PROTECTED=true
    devolvia 422 'Field required: query.request' en vez de 401.

    Causa: `from __future__ import annotations` + import de Request
    DENTRO de setup_metrics() = FastAPI no resuelve el type hint y trata
    `request` como query param.

    Fix: Request importado a nivel de modulo en metrics.py.

    Este test se ejecuta como subprocess porque setup_metrics solo
    corre una vez por proceso (cache), y necesitamos re-importar todo
    con las env vars de protected mode.
    """

    @pytest.mark.regression
    def test_protected_mode_sin_token_devuelve_401_no_422(self):
        """Bug ID: V070.74 — /metrics protected debia ser 401 pero era 422.

        Tambien valida V070.75: soporte de Authorization: Bearer ademas
        de X-Metrics-Token (Prometheus solo emite el primero nativamente).
        """
        script = textwrap.dedent("""
            import os
            os.environ['SECRET_KEY'] = 'ci-secret-key-32-chars-long-xx-yy'
            os.environ['DEMO_MODE'] = 'true'
            os.environ['DATABASE_URL'] = 'postgresql://fake:fake@localhost:5432/fake'
            os.environ['ALLOWED_ORIGINS'] = 'http://localhost:5173'
            os.environ['METRICS_ENABLED'] = 'true'
            os.environ['METRICS_ENDPOINT_PROTECTED'] = 'true'
            os.environ['METRICS_TOKEN'] = 'secret-test-token-32-chars-long-zz'

            from fastapi.testclient import TestClient
            from app.main import app

            TOKEN = 'secret-test-token-32-chars-long-zz'

            with TestClient(app) as c:
                # Sin token: DEBE ser 401, NO 422.
                r1 = c.get('/metrics')
                assert r1.status_code == 401, (
                    f"Esperaba 401, obtuve {r1.status_code}: {r1.text[:200]}"
                )

                # Con token incorrecto (X-Metrics-Token): tambien 401.
                r2 = c.get('/metrics', headers={'X-Metrics-Token': 'wrong'})
                assert r2.status_code == 401

                # Con token correcto via X-Metrics-Token: 200.
                r3 = c.get('/metrics', headers={'X-Metrics-Token': TOKEN})
                assert r3.status_code == 200
                assert 'text/plain' in r3.headers.get('content-type', '')
                assert 'http_requests_total' in r3.text or 'process_' in r3.text

                # V070.75: con token correcto via Authorization: Bearer: 200.
                r4 = c.get('/metrics', headers={'Authorization': f'Bearer {TOKEN}'})
                assert r4.status_code == 200, (
                    f"Bearer auth fallo, esperaba 200, obtuve {r4.status_code}"
                )

                # Authorization Bearer con token incorrecto: 401.
                r5 = c.get('/metrics', headers={'Authorization': 'Bearer wrong'})
                assert r5.status_code == 401

                # Header Authorization sin prefijo Bearer (formato invalido): 401.
                r6 = c.get('/metrics', headers={'Authorization': TOKEN})
                assert r6.status_code == 401

            print("OK")
        """)
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            timeout=60,
        )
        assert result.returncode == 0, (
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )
        assert "OK" in result.stdout
