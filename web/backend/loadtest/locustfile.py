"""Load testing del CRM con Locust.

V070.74 (Bundle Load Testing — `docs/LOAD_TESTING.md`).

Mide la curva Throughput vs Load y Response Time vs Load del CRM para
caracterizar empiricamente:

  - Throughput maximo sostenido (req/s antes de degradacion).
  - Latencia p50, p95, p99 a distintos niveles de carga.
  - Punto de quiebre del sistema (cuando empiezan 5xx o timeouts).

Esto cumple el principio del workbook (Pogrebinsky §Performance):
"Performance Degradation curves" — saber cuando el sistema empieza a
saturarse antes de que pase en produccion con usuarios reales.

## Como correr

```bash
# 1. Levantar el backend en otra terminal (modo demo OK para baseline).
cd web/backend && uvicorn app.main:app --port 8002

# 2. En esta terminal, correr Locust contra el backend.
cd web/backend && locust -f loadtest/locustfile.py --host http://localhost:8002

# 3. Abrir http://localhost:8089 (Locust UI).
#    - Number of users: 50 (rampea gradual hasta 50 usuarios simultaneos)
#    - Spawn rate: 5 (5 usuarios por segundo)
#    - Run time: 5m (test de 5 minutos)
```

## Headless (CI / scripted)

```bash
locust -f loadtest/locustfile.py --host http://localhost:8002 \
       --headless --users 50 --spawn-rate 5 --run-time 5m \
       --html report.html --csv baseline
```

Genera `report.html` con curvas + CSVs con datos crudos para baseline.

## Scenarios cubiertos

- **AnonUser**: pega a endpoints publicos sin auth (health, version).
- **AuthAsesorUser**: simula un asesor logueado consultando leads,
  contactos, agenda. Es el flujo mas usado en produccion.
- **AdminUser**: simula un admin consultando reportes y dashboard
  (queries mas pesadas).

## Lo que NO testea (deliberado)

- POST/PUT/DELETE que generan side effects. Load test es de READ
  load — los write tests requieren limpieza de DB que complica el
  test. Para writes usar pytest-benchmark en tests dedicados.
- Endpoints externos (Meta, FCM). Esos tienen sus propios SLA del
  proveedor — no son nuestro responsabilidad caracterizar.
- WhatsApp webhook (requiere firma HMAC valida — out of scope para
  load test, se cubre con tests unit/integration).
"""
from __future__ import annotations

import os
import random

from locust import HttpUser, between, task


# ──────────────────────────────────────────────────────────────────────
# Configuracion
# ──────────────────────────────────────────────────────────────────────

# JWT tokens para los users autenticados. Si NO estan seteadas, los
# tests autenticados se skipean y el load test corre solo con AnonUser.
ASESOR_TOKEN = os.environ.get("LOCUST_ASESOR_TOKEN")
ADMIN_TOKEN = os.environ.get("LOCUST_ADMIN_TOKEN")


# ──────────────────────────────────────────────────────────────────────
# AnonUser — sin autenticacion (endpoints publicos)
# ──────────────────────────────────────────────────────────────────────


class AnonUser(HttpUser):
    """Usuario anonimo — pega a health checks y endpoints publicos.

    Pensado para baseline: medir el throughput minimo absoluto del
    stack HTTP sin logica de negocio.
    """

    wait_time = between(0.5, 2)

    @task(10)
    def health(self):
        """Health check v0 — usado por load balancers."""
        self.client.get("/api/health", name="GET /api/health")

    @task(3)
    def health_v1(self):
        """Health check v1 — schema enriquecido para monitoring."""
        self.client.get("/api/v1/health", name="GET /api/v1/health")

    @task(1)
    def brand(self):
        """Brand config — publico (lo usa el login)."""
        self.client.get("/api/settings/brand", name="GET /api/settings/brand")


# ──────────────────────────────────────────────────────────────────────
# AuthAsesorUser — flujo mas usado en produccion
# ──────────────────────────────────────────────────────────────────────


class AuthAsesorUser(HttpUser):
    """Asesor logueado consultando leads y agenda.

    Para correr: setear env var `LOCUST_ASESOR_TOKEN` con un JWT valido
    de un usuario rol 'asesor'. Si NO esta seteada, el usuario se
    desactiva automaticamente.
    """

    wait_time = between(2, 5)
    fixed_count = 1 if ASESOR_TOKEN else 0  # desactivar si no hay token

    def on_start(self):
        if not ASESOR_TOKEN:
            self.environment.runner.quit()
            return
        self.client.headers["Authorization"] = f"Bearer {ASESOR_TOKEN}"

    @task(20)
    def listar_leads(self):
        """Vista por defecto al loguearse — query mas frecuente del CRM."""
        page = random.choice([1, 1, 1, 2])  # 75% pagina 1, 25% pagina 2
        self.client.get(
            f"/api/leads?page={page}&page_size=50",
            name="GET /api/leads",
        )

    @task(8)
    def listar_agenda_hoy(self):
        """Calendario del dia."""
        self.client.get("/api/agenda/today", name="GET /api/agenda/today")

    @task(3)
    def listar_contactos_recientes(self):
        """Historial de actividad reciente del asesor."""
        self.client.get(
            "/api/contactos?limit=20",
            name="GET /api/contactos",
        )

    @task(1)
    def listar_catalogos(self):
        """Catalogos de estado/fuente — cacheable pero validamos cold path."""
        self.client.get("/api/catalogs/estados", name="GET /api/catalogs/estados")


# ──────────────────────────────────────────────────────────────────────
# AdminUser — queries pesadas (reportes, dashboard)
# ──────────────────────────────────────────────────────────────────────


class AdminUser(HttpUser):
    """Admin consultando dashboard y reportes."""

    wait_time = between(5, 15)
    fixed_count = 1 if ADMIN_TOKEN else 0

    def on_start(self):
        if not ADMIN_TOKEN:
            self.environment.runner.quit()
            return
        self.client.headers["Authorization"] = f"Bearer {ADMIN_TOKEN}"

    @task(10)
    def dashboard(self):
        """KPIs del dashboard — agrega varios COUNT() y joins."""
        self.client.get("/api/dashboard", name="GET /api/dashboard")

    @task(3)
    def reporte_conversion(self):
        """Reporte de conversion — query pesada con window functions."""
        self.client.get(
            "/api/reportes/conversion?periodo=30d",
            name="GET /api/reportes/conversion",
        )

    @task(2)
    def reporte_performance_asesores(self):
        """Top asesores por leads asignados/cerrados."""
        self.client.get(
            "/api/reportes/asesores",
            name="GET /api/reportes/asesores",
        )
