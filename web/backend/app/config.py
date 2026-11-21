"""
Configuración central de la aplicación.
Lee variables de entorno desde el archivo .env usando pydantic-settings.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import List


class Settings(BaseSettings):
    # Cadena de conexión a PostgreSQL
    database_url: str = "postgresql://user:password@host:5432/dbname"

    # Configuración de pool de conexiones PostgreSQL (V113)
    db_pool_min_conn: int = 4
    db_pool_max_conn: int = 35
    db_pool_timeout: float = 10.0

    # Modo demo: no requiere base de datos real
    demo_mode: bool = False

    # Configuración de JWT
    secret_key: str
    algorithm: str = "HS256"
    # V5.73.7 — TTL subido de 8 a 12 horas. Razón: asesores en jornada
    # completa (8h trabajo + almuerzo + extras) no querían re-login al
    # mediodía o si el OS mataba la app y volvían en la tarde. 12h cubre
    # una jornada laboral con margen. Trade-off: si se pierde el celular,
    # acceso por 12h en lugar de 8h. Sigue siendo estándar industria
    # (Salesforce 2-12h, HubSpot 8-24h).
    access_token_expire_hours: int = 12

    # Orígenes permitidos para CORS (string separado por comas, sin espacios).
    # Default: solo localhost (para desarrollo). Cada cliente/deploy define
    # su lista en su .env propio:
    #   - Palma del Río:   ALLOWED_ORIGINS=https://crm.local,https://panel.crm.local
    #   - Doctor Muelita:  ALLOWED_ORIGINS=https://crm.doctormuelita.com
    #   - n8n self-hosted: agregar la URL del n8n correspondiente
    # Si el cliente usa una URL temporal de EasyPanel (l7weu8.easypanel.host)
    # mientras configura su dominio custom, agregarla tambien.
    # Ver web/backend/.env.example para mas opciones.
    allowed_origins: str = "http://localhost:5173,http://localhost:3000"

    # URL pública canónica del CRM (https://crm.cliente.com). Se usa para
    # construir enlaces absolutos que viajan fuera del CRM: emails,
    # invitaciones, webhooks. Si está vacío, se deriva del primer origin
    # NO-localhost de allowed_origins. correo profesional bloquea data URLs en <img>
    # (CSP) → emails con logo necesitan un URL HTTPS público real.
    public_base_url: str = ""

    # API key para ingesta automatica desde n8n (POST /api/ingest/leads)
    ingest_api_key: str = ""

    # Ollama (mensajes motivacionales)
    ollama_base_url: str = "http://crm_ollama:11434"
    ollama_model: str = "qwen2.5:7b"

    # Emergency reset — permite resetear contraseña admin sin estar logueado.
    # Generar con: python -c "import secrets; print(secrets.token_urlsafe(48))"
    # Dejar vacío para deshabilitar el endpoint.
    emergency_secret: str = ""

    # Firebase Cloud Messaging — push instantaneo
    fcm_enabled: bool = False
    fcm_service_account_b64: str = ""

    # ── WhatsApp Business Cloud API (Meta) ───────────────────────────────────
    # Access token permanente del app de Meta (System User Token recomendado).
    # https://developers.facebook.com/docs/whatsapp/cloud-api/get-started
    meta_wa_access_token: str = ""

    # ID del numero de telefono verificado en Meta Business (NO es el numero en si,
    # es el "Phone number ID" que da Meta en el dashboard).
    meta_wa_phone_number_id: str = ""

    # Token arbitrario que define el dev — Meta lo envia al verificar el webhook.
    # Generar con: python -c "import secrets; print(secrets.token_urlsafe(32))"
    meta_wa_webhook_verify_token: str = ""

    # App Secret del app de Meta — se usa para validar firma HMAC-SHA256 del webhook.
    # En produccion ES OBLIGATORIO. Vacio = modo dev sin verificacion (warning en logs).
    meta_wa_app_secret: str = ""

    # Business Account ID (WABA) — util para llamar Graph API (templates, insights).
    meta_wa_business_account_id: str = ""

    # ── Formularios públicos — anti-spam ─────────────────────────────────────
    # Los defaults aquí son los valores de producción actuales. Externalizados
    # para poder tunearlos por ambiente (dev/staging/prod) o por tenant sin
    # redeploy — editás el .env en EasyPanel y reiniciás el contenedor.
    #
    # HONEYPOT_FIELD NO está aquí a propósito: si el nombre del campo oculto
    # fuera configurable, un atacante podría leerlo y saltarlo. Se queda como
    # constante en el service.

    # Tiempo mínimo (segundos) desde el load del form hasta el submit.
    # Bots automatizados envían en <1s. Valor recomendado: 2–3s.
    public_form_min_submit_seconds: int = 2

    # Cuántas submissions persistidas tolera una misma IP antes de devolver 429.
    public_form_ip_max_submissions: int = 5

    # Ventana de tiempo (minutos) sobre la que se cuenta el límite por IP.
    public_form_ip_window_minutes: int = 10

    # Rate limit de slowapi (formato "N/unit": "10/minute", "100/hour").
    # Capa de memoria que complementa al IP window persistido en BD.
    public_form_rate_limit_submit: str = "10/minute"
    public_form_rate_limit_get:    str = "60/minute"

    # Código de país por defecto cuando el lead escribe el teléfono sin
    # prefijo. Perú = 51, Chile = 56, México = 52, etc. Sin el "+".
    public_form_default_country_code: str = "51"

    # V070.66 — Sentry para error tracking en producción.
    # Si sentry_dsn está vacío, NO se inicializa (no se manda data afuera).
    # Cada cliente define su propia DSN en su .env (proyecto separado en
    # Sentry por tenant → aislamiento de datos).
    # sentry_environment ayuda a distinguir prod / staging / demo en el
    # dashboard de Sentry.
    sentry_dsn: str = ""
    sentry_environment: str = "production"
    sentry_traces_sample_rate: float = 0.0  # 0 = solo errores, no performance traces
    # Nombre del release para correlacionar errores con versión deployada.
    # Ideal: setearlo a la SHA corta del commit en build de Docker.
    app_version: str = "dev"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",   # tolerar variables de entorno no declaradas
    )

    @field_validator("secret_key")
    @classmethod
    def _validate_secret_key(cls, v: str) -> str:
        if not v or len(v) < 32:
            raise ValueError(
                "SECRET_KEY debe tener al menos 32 caracteres "
                "(usa: python -c 'import secrets; print(secrets.token_urlsafe(48))')"
            )
        return v

    def get_allowed_origins(self) -> List[str]:
        """Retorna la lista de orígenes CORS permitidos."""
        return [origin.strip() for origin in self.allowed_origins.split(",")]

    def get_public_base_url(self) -> str:
        """URL pública absoluta del CRM (sin trailing slash).

        Prioridad:
          1. settings.public_base_url si está seteado.
          2. Variable de entorno CRM_BACKEND_URL si existe.
          3. Primer origin de allowed_origins que NO sea localhost/127.x ni *.
          4. Primer origin disponible (fallback dev → http://localhost:5173).
        """
        explicit = (self.public_base_url or "").strip().rstrip("/")
        if explicit:
            return explicit

        import os
        env_backend_url = (os.environ.get("CRM_BACKEND_URL") or "").strip().rstrip("/")
        if env_backend_url:
            return env_backend_url

        for origin in self.get_allowed_origins():
            host = origin.lower()
            if "localhost" in host or "127." in host or "0.0.0.0" in host or host == "*":
                continue
            return origin.rstrip("/")
        origins = self.get_allowed_origins()
        filtered_origins = [o.rstrip("/") for o in origins if o.strip() != "*"]
        return (filtered_origins[0] if filtered_origins else "http://localhost:5173").rstrip("/")


# Instancia global de configuración
settings = Settings()
