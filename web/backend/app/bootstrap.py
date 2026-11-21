"""
bootstrap.py — Arranque y migraciones idempotentes del esquema.

Algunas migraciones del proyecto viven en `database/migrations/*.sql` y se
aplican manualmente contra la DB de producción. Esto funciona para
cambios operados por DBAs, pero cualquier feature que se autosirva desde
el backend necesita que su schema exista al primer request — si no, el
endpoint devuelve 500 hasta que alguien corra el SQL a mano.

Este módulo ejecuta los DDL idempotentes necesarios al levantar la app.
Todas las sentencias usan `IF NOT EXISTS` y son seguras de re-ejecutar
cada arranque. Los errores se capturan y se loguean pero NO tumban la
app — preferimos servir el resto del CRM con el feature caído antes que
dejar todo sin arrancar.

Nota: la fuente de verdad canónica sigue siendo
`database/migrations/V021_public_forms.sql`. Este DDL es una copia
sincronizada — cualquier cambio ahí debe replicarse aquí (o viceversa).
"""
from __future__ import annotations

import logging

from app.database import get_db

logger = logging.getLogger(__name__)


# ── V021: crm.public_forms ───────────────────────────────────────────────────
# Copia fiel de database/migrations/V021_public_forms.sql.
# Todo IF NOT EXISTS + ALTER TABLE ADD COLUMN IF NOT EXISTS → idempotente.
_V021_PUBLIC_FORMS_DDL = """
CREATE TABLE IF NOT EXISTS crm.public_forms (
    id               UUID         PRIMARY KEY DEFAULT uuid_generate_v1(),
    slug             VARCHAR(80)  NOT NULL,
    titulo           VARCHAR(120) NOT NULL,
    descripcion      TEXT,
    nombre_evento    VARCHAR(200),
    empresa          VARCHAR(200),
    fuente_id        INTEGER
                     REFERENCES crm.fuentes(id)
                     ON DELETE SET NULL,
    campana          VARCHAR(200),
    asignado_a       UUID         NOT NULL
                     REFERENCES auth.users(id)
                     ON DELETE RESTRICT,
    created_by       UUID         NOT NULL
                     REFERENCES auth.users(id)
                     ON DELETE RESTRICT,
    config           JSONB        NOT NULL DEFAULT '{}'::jsonb,
    activo           BOOLEAN      NOT NULL DEFAULT TRUE,
    expires_at       TIMESTAMPTZ,
    max_submissions  INTEGER,
    submission_count INTEGER      NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT public_forms_slug_unico             UNIQUE (slug),
    CONSTRAINT public_forms_slug_formato           CHECK (slug ~ '^[a-z0-9][a-z0-9-]{2,79}$'),
    CONSTRAINT public_forms_max_subs_positivo      CHECK (max_submissions IS NULL OR max_submissions > 0),
    CONSTRAINT public_forms_submission_count_positivo CHECK (submission_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_public_forms_created_by_activo
    ON crm.public_forms (created_by, created_at DESC)
    WHERE activo = TRUE;

CREATE INDEX IF NOT EXISTS idx_public_forms_asignado_a_activo
    ON crm.public_forms (asignado_a, created_at DESC)
    WHERE activo = TRUE;

DROP TRIGGER IF EXISTS trg_public_forms_updated_at ON crm.public_forms;
CREATE TRIGGER trg_public_forms_updated_at
    BEFORE UPDATE ON crm.public_forms
    FOR EACH ROW
    EXECUTE FUNCTION crm.fn_set_updated_at();

CREATE TABLE IF NOT EXISTS crm.public_form_submissions (
    id          BIGSERIAL    PRIMARY KEY,
    form_id     UUID         NOT NULL
                REFERENCES crm.public_forms(id)
                ON DELETE CASCADE,
    lead_id     INTEGER
                REFERENCES crm.leads(id)
                ON DELETE SET NULL,
    ip_address  INET,
    user_agent  TEXT,
    payload     JSONB,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_form_submissions_form_id
    ON crm.public_form_submissions (form_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_form_submissions_ip_time
    ON crm.public_form_submissions (ip_address, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_form_submissions_lead_id
    ON crm.public_form_submissions (lead_id)
    WHERE lead_id IS NOT NULL;

ALTER TABLE crm.leads
    ADD COLUMN IF NOT EXISTS origen_form_id UUID
        REFERENCES crm.public_forms(id)
        ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_leads_origen_form_id
    ON crm.leads (origen_form_id)
    WHERE origen_form_id IS NOT NULL;
"""


def _public_forms_schema_exists() -> bool:
    """True si crm.public_forms ya existe. Barato — single query a pg_catalog."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'crm'
                      AND table_name   = 'public_forms'
                    LIMIT 1
                    """
                )
                return cur.fetchone() is not None
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo verificar existencia de crm.public_forms: %s", exc)
        return False


def ensure_public_forms_schema() -> None:
    """Aplica el DDL de V021 si aún no está presente.

    Idempotente: todas las sentencias son `IF NOT EXISTS`. Si la DB ya está
    al día el trabajo es trivial (una query a pg_catalog) y no se vuelve
    a ejecutar el DDL. Si falla, loguea y continúa — no bloquea la app.
    """
    try:
        if _public_forms_schema_exists():
            logger.info("bootstrap: crm.public_forms ya existe, saltando V021")
            return
        logger.info("bootstrap: aplicando V021_public_forms (idempotente)")
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(_V021_PUBLIC_FORMS_DDL)
            conn.commit()
        logger.info("bootstrap: V021_public_forms aplicado correctamente")
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.error(
            "bootstrap: fallo aplicando V021_public_forms: %s. "
            "La feature de formularios públicos no funcionará hasta que "
            "el DDL se aplique manualmente.",
            exc,
        )


# ── V023: WhatsApp Business Cloud API ────────────────────────────────────────
# Copia fiel de database/migrations/V023_whatsapp_business.sql.
_V023_WHATSAPP_DDL = """
CREATE TABLE IF NOT EXISTS crm.wa_campaigns (
    id            SERIAL       PRIMARY KEY,
    name          VARCHAR(200) NOT NULL,
    platform      VARCHAR(40)  NOT NULL DEFAULT 'facebook',
    ad_id         VARCHAR(80),
    campaign_code VARCHAR(40),
    start_date    DATE,
    end_date      DATE,
    budget        NUMERIC(12,2),
    active        BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT wa_campaigns_code_unico UNIQUE (campaign_code)
);

CREATE INDEX IF NOT EXISTS idx_wa_campaigns_ad_id
    ON crm.wa_campaigns (ad_id)
    WHERE ad_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_wa_campaigns_active
    ON crm.wa_campaigns (active, created_at DESC);

CREATE TABLE IF NOT EXISTS crm.wa_conversations (
    id                   BIGSERIAL    PRIMARY KEY,
    wa_phone             VARCHAR(30)  NOT NULL,
    lead_id              INTEGER
                         REFERENCES crm.leads(id)
                         ON DELETE SET NULL,
    asesor_id            UUID
                         REFERENCES auth.users(id)
                         ON DELETE SET NULL,
    contact_name         VARCHAR(200),
    last_message_at      TIMESTAMPTZ,
    last_message_preview TEXT,
    unread_count         INTEGER      NOT NULL DEFAULT 0,
    window_expires_at    TIMESTAMPTZ,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT wa_conversations_phone_unico UNIQUE (wa_phone)
);

CREATE INDEX IF NOT EXISTS idx_wa_conversations_lead_id
    ON crm.wa_conversations (lead_id)
    WHERE lead_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_wa_conversations_asesor_id
    ON crm.wa_conversations (asesor_id, last_message_at DESC);

CREATE INDEX IF NOT EXISTS idx_wa_conversations_last_message
    ON crm.wa_conversations (last_message_at DESC NULLS LAST);

CREATE TABLE IF NOT EXISTS crm.wa_messages (
    id              BIGSERIAL    PRIMARY KEY,
    conversation_id BIGINT       NOT NULL
                    REFERENCES crm.wa_conversations(id)
                    ON DELETE CASCADE,
    wa_message_id   VARCHAR(120),
    direction       VARCHAR(10)  NOT NULL,
    msg_type        VARCHAR(30)  NOT NULL DEFAULT 'text',
    content         TEXT,
    payload         JSONB,
    status          VARCHAR(20)  NOT NULL DEFAULT 'received',
    error_code      VARCHAR(40),
    error_detail    TEXT,
    sent_by_user_id UUID
                    REFERENCES auth.users(id)
                    ON DELETE SET NULL,
    timestamp       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT wa_messages_direction_chk CHECK (direction IN ('inbound','outbound')),
    CONSTRAINT wa_messages_wamid_unico   UNIQUE (wa_message_id)
);

CREATE INDEX IF NOT EXISTS idx_wa_messages_conversation
    ON crm.wa_messages (conversation_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_wa_messages_status
    ON crm.wa_messages (status)
    WHERE status IN ('queued','sent','failed');

ALTER TABLE crm.leads
    ADD COLUMN IF NOT EXISTS wa_campaign_id     INTEGER
        REFERENCES crm.wa_campaigns(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS wa_campaign_ad_id  TEXT,
    ADD COLUMN IF NOT EXISTS wa_campaign_headline TEXT,
    ADD COLUMN IF NOT EXISTS wa_ctwa_clid       TEXT,
    ADD COLUMN IF NOT EXISTS wa_referral_payload JSONB;

CREATE INDEX IF NOT EXISTS idx_leads_wa_campaign
    ON crm.leads (wa_campaign_id)
    WHERE wa_campaign_id IS NOT NULL;

DROP TRIGGER IF EXISTS trg_wa_conversations_updated_at ON crm.wa_conversations;
CREATE TRIGGER trg_wa_conversations_updated_at
    BEFORE UPDATE ON crm.wa_conversations
    FOR EACH ROW
    EXECUTE FUNCTION crm.fn_set_updated_at();

DROP TRIGGER IF EXISTS trg_wa_campaigns_updated_at ON crm.wa_campaigns;
CREATE TRIGGER trg_wa_campaigns_updated_at
    BEFORE UPDATE ON crm.wa_campaigns
    FOR EACH ROW
    EXECUTE FUNCTION crm.fn_set_updated_at();
"""


def _whatsapp_schema_exists() -> bool:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'crm'
                      AND table_name   = 'wa_conversations'
                    LIMIT 1
                    """
                )
                return cur.fetchone() is not None
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo verificar existencia de crm.wa_conversations: %s", exc)
        return False


def ensure_whatsapp_schema() -> None:
    """Aplica el DDL de V023 (WhatsApp) si aun no esta presente. Idempotente."""
    try:
        if _whatsapp_schema_exists():
            logger.info("bootstrap: crm.wa_conversations ya existe, saltando V023")
            return
        logger.info("bootstrap: aplicando V023_whatsapp_business (idempotente)")
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(_V023_WHATSAPP_DDL)
            conn.commit()
        logger.info("bootstrap: V023_whatsapp_business aplicado correctamente")
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "bootstrap: fallo aplicando V023_whatsapp_business: %s. "
            "La feature de WhatsApp no funcionara hasta que el DDL se aplique manualmente.",
            exc,
        )


# ── V024: WhatsApp Classification (IA pipeline) ──────────────────────────────
# Agrega columnas a crm.wa_conversations para persistir la clasificacion
# que hace Ollama sobre el primer mensaje entrante.
_V024_WHATSAPP_CLASSIFICATION_DDL = """
ALTER TABLE crm.wa_conversations
    ADD COLUMN IF NOT EXISTS classification_status     VARCHAR(20) NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS classification_category   VARCHAR(30),
    ADD COLUMN IF NOT EXISTS classification_confidence NUMERIC(3,2),
    ADD COLUMN IF NOT EXISTS classification_interest   VARCHAR(30),
    ADD COLUMN IF NOT EXISTS classification_urgency    VARCHAR(10),
    ADD COLUMN IF NOT EXISTS classification_summary    TEXT,
    ADD COLUMN IF NOT EXISTS classification_raw        JSONB,
    ADD COLUMN IF NOT EXISTS classification_attempts   INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS classified_at             TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS classified_by_model       VARCHAR(50);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'wa_conversations_class_status_chk'
    ) THEN
        ALTER TABLE crm.wa_conversations
            ADD CONSTRAINT wa_conversations_class_status_chk
            CHECK (classification_status IN (
                'pending','queued','classified','manual_review','archived','failed','skipped'
            ));
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'wa_conversations_class_conf_chk'
    ) THEN
        ALTER TABLE crm.wa_conversations
            ADD CONSTRAINT wa_conversations_class_conf_chk
            CHECK (classification_confidence IS NULL
                   OR (classification_confidence >= 0 AND classification_confidence <= 1));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_wa_conv_class_status
    ON crm.wa_conversations (classification_status, last_message_at DESC);

CREATE INDEX IF NOT EXISTS idx_wa_conv_class_category
    ON crm.wa_conversations (classification_category)
    WHERE classification_category IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_wa_conv_class_retry
    ON crm.wa_conversations (classified_at NULLS FIRST)
    WHERE classification_status = 'failed' AND classification_attempts < 3;
"""


def _whatsapp_classification_schema_exists() -> bool:
    """True si la columna classification_status ya existe en wa_conversations."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'crm'
                      AND table_name   = 'wa_conversations'
                      AND column_name  = 'classification_status'
                    LIMIT 1
                    """
                )
                return cur.fetchone() is not None
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "No se pudo verificar existencia de classification_status: %s", exc,
        )
        return False


def ensure_whatsapp_classification_schema() -> None:
    """Aplica V024 (columnas de clasificacion IA) si aun no esta presente."""
    try:
        if _whatsapp_classification_schema_exists():
            logger.info(
                "bootstrap: crm.wa_conversations.classification_status ya existe, saltando V024"
            )
            return
        logger.info("bootstrap: aplicando V024_whatsapp_classification (idempotente)")
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(_V024_WHATSAPP_CLASSIFICATION_DDL)
            conn.commit()
        logger.info("bootstrap: V024_whatsapp_classification aplicado correctamente")
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "bootstrap: fallo aplicando V024_whatsapp_classification: %s. "
            "La clasificacion IA de WhatsApp no funcionara hasta que el DDL "
            "se aplique manualmente.",
            exc,
        )


# ── V025: WhatsApp Multiple Cases (un cliente, varios lotes) ────────────────
# Copia fiel de database/migrations/V025_whatsapp_multiple_cases.sql.
_V025_WHATSAPP_MULTIPLE_CASES_DDL = """
CREATE TABLE IF NOT EXISTS crm.wa_conversation_leads (
    id              BIGSERIAL    PRIMARY KEY,
    conversation_id BIGINT       NOT NULL
                    REFERENCES crm.wa_conversations(id)
                    ON DELETE CASCADE,
    lead_id         INTEGER      NOT NULL
                    REFERENCES crm.leads(id)
                    ON DELETE CASCADE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    closed_at       TIMESTAMPTZ,
    created_by      VARCHAR(20)  NOT NULL DEFAULT 'auto_classifier',
    created_by_user UUID         REFERENCES auth.users(id) ON DELETE SET NULL,
    reason          TEXT,
    CONSTRAINT wa_conv_leads_unico       UNIQUE (conversation_id, lead_id),
    CONSTRAINT wa_conv_leads_origen_chk  CHECK (
        created_by IN ('auto_classifier', 'auto_terminal', 'manual_user')
    )
);

CREATE INDEX IF NOT EXISTS idx_wa_conv_leads_conv
    ON crm.wa_conversation_leads (conversation_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_wa_conv_leads_lead
    ON crm.wa_conversation_leads (lead_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_wa_conv_leads_active_unique
    ON crm.wa_conversation_leads (conversation_id)
    WHERE closed_at IS NULL;

INSERT INTO crm.wa_conversation_leads (conversation_id, lead_id, created_by)
SELECT id, lead_id, 'auto_classifier'
FROM crm.wa_conversations
WHERE lead_id IS NOT NULL
ON CONFLICT (conversation_id, lead_id) DO NOTHING;
"""


def _whatsapp_multiple_cases_schema_exists() -> bool:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'crm'
                      AND table_name   = 'wa_conversation_leads'
                    LIMIT 1
                    """
                )
                return cur.fetchone() is not None
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "No se pudo verificar existencia de wa_conversation_leads: %s", exc,
        )
        return False


def ensure_whatsapp_multiple_cases_schema() -> None:
    """Aplica V025 (historico de casos por chat) si aun no esta presente."""
    try:
        if _whatsapp_multiple_cases_schema_exists():
            logger.info(
                "bootstrap: crm.wa_conversation_leads ya existe, saltando V025"
            )
            return
        logger.info("bootstrap: aplicando V025_whatsapp_multiple_cases (idempotente)")
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(_V025_WHATSAPP_MULTIPLE_CASES_DDL)
            conn.commit()
        logger.info("bootstrap: V025_whatsapp_multiple_cases aplicado correctamente")
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "bootstrap: fallo aplicando V025_whatsapp_multiple_cases: %s. "
            "El historial de casos por chat no funcionara hasta que el DDL "
            "se aplique manualmente.",
            exc,
        )


_V026_LEAD_TAGS_DDL = """
CREATE TABLE IF NOT EXISTS crm.tags (
    id          SERIAL       PRIMARY KEY,
    nombre      VARCHAR(64)  NOT NULL,
    color_hex   VARCHAR(9)   NOT NULL DEFAULT '#6366f1',
    descripcion TEXT,
    activo      BOOLEAN      NOT NULL DEFAULT TRUE,
    orden       INTEGER      NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT tags_nombre_unique UNIQUE (nombre)
);

CREATE INDEX IF NOT EXISTS idx_tags_activo_orden
    ON crm.tags (activo, orden, nombre);

CREATE TABLE IF NOT EXISTS crm.lead_tags (
    lead_id         INTEGER      NOT NULL
                    REFERENCES crm.leads(id) ON DELETE CASCADE,
    tag_id          INTEGER      NOT NULL
                    REFERENCES crm.tags(id)  ON DELETE CASCADE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_by_user UUID         REFERENCES auth.users(id) ON DELETE SET NULL,
    PRIMARY KEY (lead_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_lead_tags_tag  ON crm.lead_tags (tag_id);
CREATE INDEX IF NOT EXISTS idx_lead_tags_lead ON crm.lead_tags (lead_id);

-- Seed de etiquetas: solo marcadores operativos. NO incluir
-- Caliente/Tibio/Frio aqui — esos viven en crm.catalogo_calidad (un
-- campo 1:1 por lead) y duplicarlos como tags confunde al usuario
-- (el catalogo de Etiquetas y de Calidad apareceria con los mismos
-- nombres). Las etiquetas son N:M y complementan al estado del lead.
INSERT INTO crm.tags (nombre, color_hex, descripcion, orden) VALUES
    ('Requiere visita',  '#8b5cf6', 'Pidio ver lote en persona',           40),
    ('Pendiente info',   '#14b8a6', 'Esperando que enviemos precio/plano', 50),
    ('Agendado',         '#22c55e', 'Cita confirmada',                     60)
ON CONFLICT (nombre) DO NOTHING;
"""


def _lead_tags_schema_exists() -> bool:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'crm'
                      AND table_name   = 'tags'
                    LIMIT 1
                    """
                )
                return cur.fetchone() is not None
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo verificar existencia de crm.tags: %s", exc)
        return False


def ensure_lead_tags_schema() -> None:
    """Aplica V026 (etiquetas para leads) si aun no esta presente."""
    try:
        if _lead_tags_schema_exists():
            logger.info("bootstrap: crm.tags ya existe, saltando V026")
            return
        logger.info("bootstrap: aplicando V026_lead_tags (idempotente)")
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(_V026_LEAD_TAGS_DDL)
            conn.commit()
        logger.info("bootstrap: V026_lead_tags aplicado correctamente")
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "bootstrap: fallo aplicando V026_lead_tags: %s. Las etiquetas "
            "no funcionaran hasta que el DDL se aplique manualmente.",
            exc,
        )


# ── V038: Conversation tags + trigger de herencia conv → lead ──────────────
# Permite etiquetar conversaciones que no tienen lead todavia (spam, soporte,
# pregunta tecnica, postventa). Cuando la conv "se promueve" a lead via
# "Tomar este chat", el trigger fn_inherit_conv_tags_to_lead copia las tags
# automaticamente al lead. Idempotente. Espera que crm.tags y crm.lead_tags
# existan (V026) y crm.wa_conversations tambien (V023).
_V038_WA_CONVERSATION_TAGS_DDL = """
CREATE TABLE IF NOT EXISTS crm.wa_conversation_tags (
    conversation_id INTEGER     NOT NULL
                    REFERENCES crm.wa_conversations(id) ON DELETE CASCADE,
    tag_id          INTEGER     NOT NULL
                    REFERENCES crm.tags(id)             ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by_user UUID        REFERENCES auth.users(id) ON DELETE SET NULL,
    PRIMARY KEY (conversation_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_wa_conversation_tags_tag
    ON crm.wa_conversation_tags (tag_id);

CREATE INDEX IF NOT EXISTS idx_wa_conversation_tags_conv
    ON crm.wa_conversation_tags (conversation_id);

CREATE OR REPLACE FUNCTION crm.fn_inherit_conv_tags_to_lead()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.lead_id IS NOT NULL AND NEW.lead_id IS DISTINCT FROM OLD.lead_id THEN
        INSERT INTO crm.lead_tags (lead_id, tag_id, created_at, created_by_user)
        SELECT NEW.lead_id, ct.tag_id, ct.created_at, ct.created_by_user
        FROM crm.wa_conversation_tags ct
        WHERE ct.conversation_id = NEW.id
        ON CONFLICT (lead_id, tag_id) DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_inherit_conv_tags_to_lead ON crm.wa_conversations;
CREATE TRIGGER trg_inherit_conv_tags_to_lead
AFTER UPDATE OF lead_id ON crm.wa_conversations
FOR EACH ROW
EXECUTE FUNCTION crm.fn_inherit_conv_tags_to_lead();
"""


def _wa_conversation_tags_exists() -> bool:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'crm'
                      AND table_name   = 'wa_conversation_tags'
                    LIMIT 1
                    """
                )
                return cur.fetchone() is not None
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo verificar existencia de crm.wa_conversation_tags: %s", exc)
        return False


def ensure_wa_conversation_tags_schema() -> None:
    """Aplica V038 (tags a nivel conversacion + trigger de herencia)."""
    try:
        if _wa_conversation_tags_exists():
            logger.info(
                "bootstrap: crm.wa_conversation_tags ya existe, saltando V038"
            )
            return
        logger.info("bootstrap: aplicando V038_wa_conversation_tags (idempotente)")
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(_V038_WA_CONVERSATION_TAGS_DDL)
            conn.commit()
        logger.info("bootstrap: V038_wa_conversation_tags aplicado correctamente")
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "bootstrap: fallo aplicando V038_wa_conversation_tags: %s. "
            "Las etiquetas a nivel conversacion no funcionaran hasta que "
            "el DDL se aplique manualmente.",
            exc,
        )


# ── V027: WhatsApp UI labels (chips editables sin tocar codigo) ─────────────
# Define labels, colores e iconos para los chips que se muestran en Chat.
# 'kind' indica el grupo:
#   - category: clasificacion IA (Potencial, Cliente, Consulta, Spam, ...)
#   - urgency:  nivel de urgencia (Urgente, ...)
#   - inbox:    bandejas del sidebar (Potenciales, Revision, Archivados, ...)
# La columna 'key' es contrato interno y NO se edita desde UI — mapea con
# los valores que emite el clasificador IA y con los filtros del backend.
_V027_WA_UI_LABELS_DDL = """
CREATE TABLE IF NOT EXISTS crm.wa_ui_labels (
    id          SERIAL       PRIMARY KEY,
    kind        VARCHAR(20)  NOT NULL,
    key         VARCHAR(50)  NOT NULL,
    label       VARCHAR(60)  NOT NULL,
    color_hex   VARCHAR(9)   NOT NULL DEFAULT '#6b7280',
    icon_name   VARCHAR(30)  NOT NULL DEFAULT 'Tag',
    sort_order  INTEGER      NOT NULL DEFAULT 100,
    activo      BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT wa_ui_labels_kind_chk CHECK (kind IN ('category','urgency','inbox')),
    CONSTRAINT wa_ui_labels_kind_key_unico UNIQUE (kind, key)
);

CREATE INDEX IF NOT EXISTS idx_wa_ui_labels_kind_sort
    ON crm.wa_ui_labels (kind, sort_order, id)
    WHERE activo = TRUE;

DROP TRIGGER IF EXISTS trg_wa_ui_labels_updated_at ON crm.wa_ui_labels;
CREATE TRIGGER trg_wa_ui_labels_updated_at
    BEFORE UPDATE ON crm.wa_ui_labels
    FOR EACH ROW
    EXECUTE FUNCTION crm.fn_set_updated_at();

INSERT INTO crm.wa_ui_labels (kind, key, label, color_hex, icon_name, sort_order) VALUES
    -- category (output del clasificador IA)
    ('category', 'cliente_potencial', 'Potencial',      '#16a34a', 'Sparkles',     10),
    ('category', 'cliente_existente', 'Cliente',        '#6366f1', 'UserCheck',    20),
    ('category', 'consulta_general',  'Consulta',       '#0ea5e9', 'MessageCircle',30),
    ('category', 'spam',              'Spam',           '#6b7280', 'Archive',      40),
    ('category', 'no_relacionado',    'No relacionado', '#6b7280', 'Archive',      50),
    ('category', 'manual_review',     'Revisar',        '#f59e0b', 'AlertCircle',  60),
    ('category', 'pending',           'Clasificando',   '#64748b', 'Clock',        70),
    ('category', 'archived',          'Archivado',      '#6b7280', 'Archive',      80),
    ('category', 'skipped',           'Cliente',        '#6366f1', 'Sparkles',     90),
    -- urgency
    ('urgency',  'alta',              'Urgente',        '#dc2626', 'Flame',        10),
    -- inbox (bandejas del sidebar)
    ('inbox',    'potenciales',       'Clientes potenciales',    '#16a34a', 'Sparkles',    10),
    ('inbox',    'revisar',           'Requieren revision',      '#f59e0b', 'AlertCircle', 20),
    ('inbox',    'sin_clasificar',    'Sin clasificar',          '#64748b', 'Clock',       30),
    ('inbox',    'delegar',           'Pendientes de delegar',   '#8b5cf6', 'UserCheck',   40),
    ('inbox',    'archivados',        'Archivados',              '#6b7280', 'Archive',     50)
ON CONFLICT (kind, key) DO NOTHING;
"""


def _wa_ui_labels_schema_exists() -> bool:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'crm'
                      AND table_name   = 'wa_ui_labels'
                    LIMIT 1
                    """
                )
                return cur.fetchone() is not None
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo verificar existencia de crm.wa_ui_labels: %s", exc)
        return False


def ensure_wa_ui_labels_schema() -> None:
    """Aplica V027 (wa_ui_labels) si aun no esta presente. Idempotente."""
    try:
        if _wa_ui_labels_schema_exists():
            logger.info("bootstrap: crm.wa_ui_labels ya existe, saltando V027")
            return
        logger.info("bootstrap: aplicando V027_wa_ui_labels (idempotente)")
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(_V027_WA_UI_LABELS_DDL)
            conn.commit()
        logger.info("bootstrap: V027_wa_ui_labels aplicado correctamente")
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "bootstrap: fallo aplicando V027_wa_ui_labels: %s. Los chips "
            "del chat usaran valores por defecto hasta que el DDL se aplique.",
            exc,
        )


# ── V028: Catálogo de campañas ──────────────────────────────────────────────

_V028_CAMPANAS_DDL = """
CREATE TABLE IF NOT EXISTS crm.campanas (
    id         SERIAL       PRIMARY KEY,
    nombre     TEXT         NOT NULL,
    activo     BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    orden      INTEGER      NOT NULL DEFAULT 0,
    CONSTRAINT campanas_nombre_unico UNIQUE (nombre)
);

-- Seed inicial: importa valores unicos del campo texto crm.leads.campana
-- para que el catalogo arranque con datos reales. ON CONFLICT evita
-- duplicados si se ejecuta mas de una vez.
INSERT INTO crm.campanas (nombre)
SELECT DISTINCT campana FROM crm.leads
WHERE campana IS NOT NULL AND campana != ''
ON CONFLICT (nombre) DO NOTHING;
"""


def _campanas_schema_exists() -> bool:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'crm' AND table_name = 'campanas'"
                )
                return cur.fetchone() is not None
    except Exception:
        return False


def ensure_campanas_schema() -> None:
    """Aplica V028 (campanas) si aun no esta presente + sincroniza el
    catalogo en CADA arranque (V094.2).

    Cambio V094.2 — auto-sync del catalogo:
    Antes el seed solo corria cuando la tabla se creaba por primera vez.
    Bug: en Palma prod la tabla se creo cuando crm.leads tenia pocos
    valores en `campana`, asi que el catalogo arrancaba practicamente
    vacio y nunca se actualizaba a pesar de que ingest de Meta/TikTok/
    formularios iba metiendo 50+ valores distintos. Resultado: admin
    veia "Sin elementos" en Configuracion → Campañas.

    Ahora el INSERT (idempotente via ON CONFLICT DO NOTHING) corre en
    cada deploy/arranque, sumando al catalogo los valores nuevos que
    aparecieron desde la ultima vez. Si el admin desactivo manualmente
    una campaña (activo=FALSE), no la reactivamos — respetamos la
    decision humana via ON CONFLICT DO NOTHING (no UPDATE).
    """
    schema_existed_before = _campanas_schema_exists()
    try:
        if not schema_existed_before:
            logger.info("bootstrap: aplicando V028_campanas DDL inicial")
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute(_V028_CAMPANAS_DDL)
                conn.commit()
            logger.info("bootstrap: V028_campanas DDL aplicado correctamente")
    except Exception as exc:
        logger.warning(
            "bootstrap: fallo aplicando V028_campanas DDL: %s", exc,
        )
        return

    # V094.2 — sync recurrente del catalogo desde crm.leads.campana.
    # Idempotente: ON CONFLICT DO NOTHING evita re-insertar y NO toca
    # el flag `activo` (respeta desactivaciones manuales del admin).
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO crm.campanas (nombre)
                    SELECT DISTINCT TRIM(campana)
                    FROM crm.leads
                    WHERE campana IS NOT NULL AND TRIM(campana) != ''
                    ON CONFLICT (nombre) DO NOTHING
                    """
                )
                inserted = cur.rowcount
            conn.commit()
        if inserted > 0:
            logger.info(
                "bootstrap: V094.2 catalogo campanas sincronizado — %d nuevos valores agregados",
                inserted,
            )
        else:
            logger.info("bootstrap: V094.2 catalogo campanas ya al dia (0 nuevos)")
    except Exception as exc:
        logger.warning(
            "bootstrap: V094.2 sync campanas fallo (no critico, reintentar al proximo arranque): %s",
            exc,
        )


# ── V029: Actualizar vw_leads_dashboard para incluir llamadas en fechas ──────
# Las fechas de primer/ultimo contacto solo miraban crm.contactos.
# Ahora incluyen tambien crm.llamadas (sync desde app movil).
# Solo contactos + llamadas — WhatsApp es canal aparte (Chat).

_V029_VIEW_UPDATE = """
CREATE OR REPLACE VIEW crm.vw_leads_dashboard AS
WITH todas_interacciones AS (
    -- Contactos manuales registrados por asesores (sin cambios de estado)
    SELECT lead_id, asesor_id, tipo_contacto, resultado, notas,
           fecha_proxima_accion, fecha_cita, created_at
    FROM crm.contactos
    WHERE tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
    UNION ALL
    -- Llamadas sincronizadas desde app movil
    SELECT lead_id, asesor_id,
           CASE tipo WHEN 'entrante' THEN 'llamada_entrante'
                     WHEN 'saliente' THEN 'llamada_saliente'
                     ELSE 'llamada' END AS tipo_contacto,
           CASE WHEN duracion_segundos > 0 THEN 'contesto' ELSE 'no_contesto' END AS resultado,
           NULL AS notas,
           NULL AS fecha_proxima_accion,
           NULL AS fecha_cita,
           fecha_llamada AS created_at
    FROM crm.llamadas
),
ultimo_contacto AS (
    SELECT DISTINCT ON (lead_id)
        lead_id,
        tipo_contacto        AS ultimo_tipo_contacto,
        resultado            AS ultimo_resultado,
        notas                AS ultimas_notas,
        fecha_proxima_accion,
        fecha_cita           AS proxima_cita,
        created_at           AS fecha_ultimo_contacto
    FROM todas_interacciones
    ORDER BY lead_id, created_at DESC
),
interacciones_count AS (
    SELECT lead_id, COUNT(*)::int AS total
    FROM todas_interacciones
    GROUP BY lead_id
),
primer_contacto AS (
    SELECT lead_id, MIN(created_at) AS fecha_primer_contacto
    FROM todas_interacciones
    GROUP BY lead_id
),
primera_asignacion AS (
    SELECT DISTINCT ON (lead_id)
        lead_id, created_at AS fecha_asignacion
    FROM crm.asignaciones_log
    ORDER BY lead_id, created_at ASC
)
SELECT
    l.id,
    l.nombres,
    l.apellidos,
    TRIM(COALESCE(l.nombres, '') || ' ' || COALESCE(l.apellidos, '')) AS nombre_completo,
    l.telefono,
    l.email,
    l.ciudad,
    l.trabajo,
    l.es_recontacto,
    COALESCE(ic.total, 0)   AS intentos_contacto,
    l.observaciones,
    l.datos_extra,
    l.hash_dedup,
    l.activo,
    l.created_at            AS fecha_ingreso,
    l.updated_at,

    l.estado_id,
    e.nombre                AS estado_nombre,
    e.color_hex             AS estado_color,
    e.es_final              AS estado_es_final,

    l.fuente_id,
    f.nombre                AS fuente_nombre,
    l.fuente_externa_id,
    l.campana,

    l.asesor_id,
    TRIM(COALESCE(a.first_name, '') || ' ' || COALESCE(a.last_name, '')) AS asesor_nombre,
    a.email                 AS asesor_email,

    eq.supervisor_id,
    TRIM(COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, '')) AS supervisor_nombre,

    uc.ultimo_tipo_contacto,
    uc.ultimo_resultado,
    uc.ultimas_notas,
    uc.fecha_ultimo_contacto,
    uc.fecha_proxima_accion,
    uc.proxima_cita,

    CASE
        WHEN uc.fecha_ultimo_contacto IS NULL THEN TRUE
        WHEN uc.fecha_ultimo_contacto < NOW() - INTERVAL '24 hours' THEN TRUE
        ELSE FALSE
    END                     AS sin_contacto_reciente,

    EXTRACT(EPOCH FROM (NOW() - l.created_at)) / 3600 AS horas_desde_ingreso,

    pa.fecha_asignacion,
    pc.fecha_primer_contacto

FROM crm.leads l
LEFT JOIN crm.estados_lead     e  ON e.id  = l.estado_id
LEFT JOIN crm.fuentes          f  ON f.id  = l.fuente_id
LEFT JOIN auth.users           a  ON a.id  = l.asesor_id
LEFT JOIN crm.equipos          eq ON eq.asesor_id = l.asesor_id AND eq.activo = TRUE
LEFT JOIN auth.users           s  ON s.id  = eq.supervisor_id
LEFT JOIN ultimo_contacto      uc ON uc.lead_id = l.id
LEFT JOIN interacciones_count  ic ON ic.lead_id = l.id
LEFT JOIN primer_contacto      pc ON pc.lead_id = l.id
LEFT JOIN primera_asignacion   pa ON pa.lead_id = l.id
WHERE l.activo = TRUE;
"""


def ensure_view_v029() -> None:
    """Obsoleto: la vista crm.vw_leads_dashboard se gestiona via migraciones versionadas (V093/V101/V102)."""
    pass


# ── V030: Backfill es_recontacto cruzando con historico y leads inactivos ─────

def ensure_lead_recontactos_external_created_at() -> None:
    """V070.60 — Safety net: garantiza que crm.lead_recontactos tiene
    la columna external_created_at (V068.4).

    El auto-migrator V<num> tenía un bug de regex (V068, V068_3, V068_4
    se trataban como la misma version) que dejó V068_4 sin aplicar.
    Aunque ya arreglamos el regex, este safety net asegura que la
    columna existe incluso si el migrator falla por otro motivo.

    Idempotente: ADD COLUMN IF NOT EXISTS no rompe si ya existe.
    """
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "ALTER TABLE crm.lead_recontactos "
                    "ADD COLUMN IF NOT EXISTS external_created_at TIMESTAMPTZ"
                )
        logger.info("[bootstrap] lead_recontactos.external_created_at: OK (asegurada)")
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[bootstrap] no se pudo asegurar lead_recontactos.external_created_at: %s",
            exc, exc_info=True,
        )


def ensure_lead_recontacto_webhook_event() -> None:
    """V084 — Safety net: garantiza que `lead.recontacto` esta en el array
    `webhook_events` de todos los api_clients con webhook habilitado.

    Caso reportado en el entorno de pruebas 2026-06-16: el admin tildaba 'Lead
    recontacto' en el panel, pero el guardado fallaba silenciosamente
    porque el binario backend deployado era pre-V084 (ALL_EVENTS no
    incluia ese evento todavia). Cuando este binario nuevo arranca:
      - V084 ya esta en ALL_EVENTS
      - Reabrir el panel + Guardar de nuevo resolveria
      - Pero queremos evitar ese paso manual → backfilleamos aqui.

    Idempotente: solo agrega el string si NO esta ya. Solo afecta a
    proveedores con webhook_enabled=true (intencion clara de recibir
    eventos). El admin puede destildarlo despues si no lo quiere.

    Si el caller no quiere este backfill, lo controla via env var
    SKIP_RECONTACTO_BACKFILL=1.
    """
    import os
    if os.environ.get("SKIP_RECONTACTO_BACKFILL") == "1":
        logger.info("[bootstrap] lead.recontacto backfill SKIPPED (env)")
        return
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                # V085.1 — webhook_events es text[] (no jsonb). Operadores:
                #   ANY(arr)             contiene
                #   array_append(arr, x) agrega un elemento
                # Antes usabamos `?` y `||` (jsonb) y la query fallaba.
                cur.execute(
                    """
                    UPDATE crm.api_clients
                    SET webhook_events = array_append(webhook_events, 'lead.recontacto')
                    WHERE webhook_enabled = TRUE
                      AND activo = TRUE
                      AND revoked_at IS NULL
                      AND NOT ('lead.recontacto' = ANY(webhook_events))
                    RETURNING id, nombre
                    """
                )
                rows = cur.fetchall()
                if rows:
                    logger.info(
                        "[bootstrap] lead.recontacto auto-suscripto en %d api_clients: %s",
                        len(rows), [r[1] for r in rows],
                    )
                else:
                    logger.info(
                        "[bootstrap] lead.recontacto: todos los api_clients ya suscriptos (no-op)"
                    )
    except Exception as exc:  # noqa: BLE001
        # Best-effort — no rompemos el startup si la tabla aun no existe o
        # la columna jsonb tiene un formato inesperado.
        logger.warning(
            "[bootstrap] backfill lead.recontacto fallo (no critico): %s",
            exc, exc_info=True,
        )


def ensure_recontacto_backfill() -> None:
    """Mantiene `es_recontacto` coherente con sus fuentes de forma idempotente."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE SCHEMA IF NOT EXISTS crm;
                    CREATE TABLE IF NOT EXISTS crm.bootstrap_flags (
                        key TEXT PRIMARY KEY,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                """)
                cur.execute("SELECT 1 FROM crm.bootstrap_flags WHERE key = 'recontacto_backfill_done'")
                if cur.fetchone():
                    return

                # Cruzar con crm_legacy.leads_historico por telefono normalizado
                cur.execute("""
                    UPDATE crm.leads l
                    SET es_recontacto = TRUE
                    WHERE l.activo = TRUE
                      AND l.es_recontacto = FALSE
                      AND EXISTS (
                          SELECT 1 FROM crm_legacy.leads_historico h
                          WHERE h.telefono_norm = RIGHT(REGEXP_REPLACE(l.telefono, '\\D', '', 'g'), 9)
                      )
                """)
                legacy_count = cur.rowcount

                cur.execute("""
                    UPDATE crm.leads l
                    SET es_recontacto = TRUE
                    WHERE l.activo = TRUE
                      AND l.es_recontacto = FALSE
                      AND EXISTS (
                          SELECT 1 FROM crm.leads l2
                          WHERE l2.id <> l.id
                            AND RIGHT(REGEXP_REPLACE(l2.telefono, '\\D', '', 'g'), 9)
                              = RIGHT(REGEXP_REPLACE(l.telefono,  '\\D', '', 'g'), 9)
                      )
                """)
                inactive_count = cur.rowcount

                cur.execute("""
                    INSERT INTO crm.bootstrap_flags (key)
                    VALUES ('recontacto_backfill_done')
                    ON CONFLICT (key) DO NOTHING;
                """)
            conn.commit()
        if legacy_count or inactive_count:
            logger.info("bootstrap: es_recontacto — set %d (legacy) + %d (crm)", legacy_count, inactive_count)
    except Exception as exc:
        logger.warning("bootstrap: fallo backfill es_recontacto: %s", exc)


# ── V031: Cache local de media de WhatsApp ──────────────────────────────────
# Los URLs que Meta Graph API devuelve para descargar media expiran a los ~5
# minutos. Para que el frontend pueda mostrar imágenes/audio/video del chat
# sin fricción, cacheamos el binario la primera vez que se solicita y lo
# servimos desde PG en siguientes requests.
_V031_WA_MEDIA_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS crm.wa_media_cache (
    media_id    TEXT PRIMARY KEY,
    mime_type   TEXT NOT NULL,
    size_bytes  BIGINT,
    data        BYTEA NOT NULL,
    cached_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wa_media_cache_cached_at
    ON crm.wa_media_cache (cached_at DESC);
"""


def _wa_media_cache_exists() -> bool:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'crm' AND table_name = 'wa_media_cache'"
                )
                return cur.fetchone() is not None
    except Exception:
        return False


def ensure_wa_media_cache_schema() -> None:
    """Aplica V031 (wa_media_cache) si aun no esta presente. Idempotente."""
    try:
        if _wa_media_cache_exists():
            logger.info("bootstrap: crm.wa_media_cache ya existe, saltando V031")
            return
        logger.info("bootstrap: aplicando V031_wa_media_cache (idempotente)")
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(_V031_WA_MEDIA_CACHE_DDL)
            conn.commit()
        logger.info("bootstrap: V031_wa_media_cache aplicado correctamente")
    except Exception as exc:
        logger.warning(
            "bootstrap: fallo aplicando V031_wa_media_cache: %s. La descarga "
            "de media de WhatsApp no funcionara hasta que se cree la tabla.",
            exc,
        )


# ── V032: Deteccion de phishing en mensajes WhatsApp ────────────────────────
# Agrega columna risk_flags JSONB a wa_messages para almacenar el resultado
# del analisis anti-phishing (reglas + LLM local). Estructura esperada:
#   {"score": 0-100, "level": "low|medium|high", "reasons": [...],
#    "urls": [...], "analyzed_at": iso, "engine": "rules+ollama"}
_V032_RISK_FLAGS_DDL = """
ALTER TABLE crm.wa_messages
    ADD COLUMN IF NOT EXISTS risk_flags JSONB;

CREATE INDEX IF NOT EXISTS idx_wa_messages_risk_level
    ON crm.wa_messages ((risk_flags->>'level'))
    WHERE risk_flags IS NOT NULL;
"""


def _risk_flags_column_exists() -> bool:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = 'crm' "
                    "  AND table_name = 'wa_messages' "
                    "  AND column_name = 'risk_flags'"
                )
                return cur.fetchone() is not None
    except Exception:
        return False


def ensure_wa_messages_risk_flags_schema() -> None:
    """Aplica V032 (risk_flags en wa_messages) si aun no esta. Idempotente."""
    try:
        if _risk_flags_column_exists():
            logger.info("bootstrap: crm.wa_messages.risk_flags ya existe, saltando V032")
            return
        logger.info("bootstrap: aplicando V032_wa_messages_risk_flags (idempotente)")
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(_V032_RISK_FLAGS_DDL)
            conn.commit()
        logger.info("bootstrap: V032_wa_messages_risk_flags aplicado correctamente")
    except Exception as exc:
        logger.warning(
            "bootstrap: fallo aplicando V032_wa_messages_risk_flags: %s. La "
            "deteccion de phishing no persistira hasta que la columna exista.",
            exc,
        )


# ── V033: Multi-numero de WhatsApp ──────────────────────────────────────────
# Soporte para que Palma del Rio opere N numeros de WhatsApp Business en
# paralelo (Ventas, Post-venta, nuevo producto, etc.) todos bajo el mismo
# WABA. Cada conversacion y cada mensaje queda linkado al numero propio
# que lo recibio/envio.
_V033_WA_NUMBERS_DDL = """
CREATE TABLE IF NOT EXISTS crm.wa_numbers (
    id               BIGSERIAL PRIMARY KEY,
    phone_number_id  TEXT       NOT NULL UNIQUE,     -- ID de Meta
    display_phone    TEXT,                            -- +51 941 352 492
    display_name     TEXT       NOT NULL,             -- 'Ventas', 'Post-venta'
    waba_id          TEXT,                            -- WhatsApp Business Account
    is_default       BOOLEAN    NOT NULL DEFAULT FALSE,
    activo           BOOLEAN    NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Solo UN numero puede ser default
CREATE UNIQUE INDEX IF NOT EXISTS ux_wa_numbers_default
    ON crm.wa_numbers (is_default) WHERE is_default = TRUE;

ALTER TABLE crm.wa_conversations
    ADD COLUMN IF NOT EXISTS wa_number_id BIGINT
    REFERENCES crm.wa_numbers(id) ON DELETE SET NULL;

ALTER TABLE crm.wa_messages
    ADD COLUMN IF NOT EXISTS wa_number_id BIGINT
    REFERENCES crm.wa_numbers(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_wa_conversations_wa_number_id
    ON crm.wa_conversations (wa_number_id)
    WHERE wa_number_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_wa_messages_wa_number_id
    ON crm.wa_messages (wa_number_id)
    WHERE wa_number_id IS NOT NULL;
"""


def _wa_numbers_table_exists() -> bool:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'crm' AND table_name = 'wa_numbers'"
                )
                return cur.fetchone() is not None
    except Exception:
        return False


def _seed_default_wa_number() -> None:
    """Si hay META_WA_PHONE_NUMBER_ID en env y la tabla esta vacia, inserta
    el numero actual como default. Luego backfillea conversations/messages.
    """
    from app.config import settings

    default_phone_id = (settings.meta_wa_phone_number_id or "").strip()
    if not default_phone_id:
        logger.info(
            "bootstrap: META_WA_PHONE_NUMBER_ID vacio, no se sembrara numero default. "
            "El primer webhook registrara el numero automaticamente."
        )
        return

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM crm.wa_numbers")
            count = cur.fetchone()[0]
            if count > 0:
                # Tabla ya tiene numeros — no tocamos nada
                return

            cur.execute(
                """
                INSERT INTO crm.wa_numbers
                    (phone_number_id, display_name, waba_id, is_default, activo)
                VALUES (%s, %s, %s, TRUE, TRUE)
                ON CONFLICT (phone_number_id) DO NOTHING
                RETURNING id
                """,
                (
                    default_phone_id,
                    "Linea principal",
                    (settings.meta_wa_business_account_id or None),
                ),
            )
            row = cur.fetchone()
            default_num_id = row[0] if row else None
            if not default_num_id:
                cur.execute(
                    "SELECT id FROM crm.wa_numbers WHERE phone_number_id = %s",
                    (default_phone_id,),
                )
                default_num_id = cur.fetchone()[0]

            # Backfill conversaciones y mensajes sin numero
            cur.execute(
                "UPDATE crm.wa_conversations SET wa_number_id = %s WHERE wa_number_id IS NULL",
                (default_num_id,),
            )
            conv_updated = cur.rowcount
            cur.execute(
                "UPDATE crm.wa_messages SET wa_number_id = %s WHERE wa_number_id IS NULL",
                (default_num_id,),
            )
            msg_updated = cur.rowcount
            logger.info(
                "bootstrap: V033 seed default number id=%s (convs=%s, msgs=%s backfilled)",
                default_num_id, conv_updated, msg_updated,
            )
        conn.commit()


def ensure_wa_numbers_schema() -> None:
    """Aplica V033 (multi-numero WA). Idempotente."""
    try:
        existed = _wa_numbers_table_exists()
        if not existed:
            logger.info("bootstrap: aplicando V033_wa_numbers (idempotente)")
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(_V033_WA_NUMBERS_DDL)
            conn.commit()
        _seed_default_wa_number()
        logger.info("bootstrap: V033_wa_numbers aplicado correctamente")
    except Exception as exc:
        logger.warning(
            "bootstrap: fallo aplicando V033_wa_numbers: %s. El multi-numero "
            "no funcionara hasta que la tabla exista.",
            exc,
        )


# ── V034: Multi-WABA (WhatsApp Business Account) ───────────────────────────
# Soporte para N WhatsApp Business Accounts en paralelo — casos como
# empresas distintas (Palma del Rio + Doctor Muelita), Meta Apps separados,
# o ambientes de staging. Cada WABA tiene su propio access_token, app_secret
# y webhook verify_token, todos gestionados desde la UI y cifrados en DB.
#
# Diseño:
#   - Tabla crm.wa_babas guarda credenciales por WABA (tokens cifrados con
#     secrets_service — Fernet derivada de SECRET_KEY).
#   - wa_numbers.waba_id_ref (FK a wa_babas.id) — cada numero propio
#     pertenece a una WABA. Mantenemos tambien la columna textual waba_id
#     (ID de Meta) para que el webhook la use sin JOIN.
#   - Seed automatico: si hay env vars META_WA_* al arrancar, se crea una
#     WABA inicial con esas credenciales y se linkea al numero default.
#     Zero-config migration — el sistema sigue funcionando sin tocar env.
_V034_WA_BABAS_DDL = """
CREATE TABLE IF NOT EXISTS crm.wa_babas (
    id                        BIGSERIAL PRIMARY KEY,
    waba_id                   TEXT        NOT NULL UNIQUE,   -- ID de Meta
    display_name              TEXT        NOT NULL,          -- 'Palma del Rio', 'Doctor Muelita'
    access_token_encrypted    TEXT        NOT NULL,          -- Fernet ciphertext
    app_secret_encrypted      TEXT        NOT NULL DEFAULT '',
    webhook_verify_token_encrypted TEXT   NOT NULL DEFAULT '',
    is_default                BOOLEAN     NOT NULL DEFAULT FALSE,
    activo                    BOOLEAN     NOT NULL DEFAULT TRUE,
    notes                     TEXT,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Solo UNA WABA default
CREATE UNIQUE INDEX IF NOT EXISTS ux_wa_babas_default
    ON crm.wa_babas (is_default) WHERE is_default = TRUE;

-- Cada numero (phone) pertenece a una WABA. ON DELETE RESTRICT para evitar
-- borrar accidentalmente una WABA que tenga numeros registrados — el admin
-- debe primero reasignar o borrar los numeros.
ALTER TABLE crm.wa_numbers
    ADD COLUMN IF NOT EXISTS waba_id_ref BIGINT
    REFERENCES crm.wa_babas(id) ON DELETE RESTRICT;

CREATE INDEX IF NOT EXISTS idx_wa_numbers_waba_id_ref
    ON crm.wa_numbers (waba_id_ref)
    WHERE waba_id_ref IS NOT NULL;
"""


def _wa_babas_table_exists() -> bool:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'crm' AND table_name = 'wa_babas'"
                )
                return cur.fetchone() is not None
    except Exception:
        return False


def _seed_default_wa_baba() -> None:
    """Si la tabla esta vacia y hay credenciales en env, crea la WABA
    inicial y linkea todos los numeros existentes a ella.

    Zero-downtime: mantiene 100% el comportamiento previo sin que el admin
    tenga que tocar nada. Despues del primer arranque, las credenciales ya
    viven en DB y los env vars pueden quedar como fallback o removerse.
    """
    from app.config import settings
    from app.services.secrets_service import encrypt

    access_token = (settings.meta_wa_access_token or "").strip()
    waba_id_env  = (settings.meta_wa_business_account_id or "").strip()

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM crm.wa_babas")
            count = cur.fetchone()[0]
            if count > 0:
                return  # ya hay WABAs — no tocamos

            if not access_token:
                logger.info(
                    "bootstrap: V034 — no hay META_WA_ACCESS_TOKEN en env, "
                    "no se sembrara WABA default. Admin debe crearla desde UI."
                )
                return

            # Si no hay waba_id en env, usamos un placeholder — el admin lo
            # corrige desde la UI.
            effective_waba_id = waba_id_env or f"legacy-{access_token[-8:]}"
            display_name = "WABA principal"

            cur.execute(
                """
                INSERT INTO crm.wa_babas
                    (waba_id, display_name, access_token_encrypted,
                     app_secret_encrypted, webhook_verify_token_encrypted,
                     is_default, activo, notes)
                VALUES (%s, %s, %s, %s, %s, TRUE, TRUE, %s)
                ON CONFLICT (waba_id) DO NOTHING
                RETURNING id
                """,
                (
                    effective_waba_id,
                    display_name,
                    encrypt(access_token),
                    encrypt(settings.meta_wa_app_secret or ""),
                    encrypt(settings.meta_wa_webhook_verify_token or ""),
                    "Sembrada automaticamente desde variables de entorno en V034.",
                ),
            )
            row = cur.fetchone()
            baba_id = row[0] if row else None
            if not baba_id:
                cur.execute(
                    "SELECT id FROM crm.wa_babas WHERE waba_id = %s",
                    (effective_waba_id,),
                )
                baba_id = cur.fetchone()[0]

            # Linkea TODOS los numeros existentes a esta WABA default
            cur.execute(
                "UPDATE crm.wa_numbers SET waba_id_ref = %s "
                "WHERE waba_id_ref IS NULL",
                (baba_id,),
            )
            numbers_linked = cur.rowcount
            logger.info(
                "bootstrap: V034 seed default WABA id=%s, %s numeros linkeados",
                baba_id, numbers_linked,
            )
        conn.commit()


def ensure_wa_babas_schema() -> None:
    """Aplica V034 (multi-WABA) idempotente."""
    try:
        existed = _wa_babas_table_exists()
        if not existed:
            logger.info("bootstrap: aplicando V034_wa_babas (idempotente)")
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(_V034_WA_BABAS_DDL)
            conn.commit()
        _seed_default_wa_baba()
        logger.info("bootstrap: V034_wa_babas aplicado correctamente")
    except Exception as exc:
        logger.warning(
            "bootstrap: fallo aplicando V034_wa_babas: %s. Multi-WABA "
            "no funcionara hasta que la tabla exista.",
            exc,
        )


# ── V035: Línea WhatsApp por defecto por asesor ───────────────────────────
# Cada asesor tiene una línea WhatsApp asignada (Ventas / Marketing / Soporte)
# para que sus mensajes salientes usen esa línea sin tener que seleccionarla
# cada vez. La asignación es manual — la hace el admin desde "Usuarios".
# El supervisor sigue controlando la asignación de leads (no hay auto-ruteo).
_V035_USER_DEFAULT_WA_NUMBER_DDL = """
ALTER TABLE auth.users
    ADD COLUMN IF NOT EXISTS default_wa_number_id BIGINT
    REFERENCES crm.wa_numbers(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_users_default_wa_number_id
    ON auth.users (default_wa_number_id)
    WHERE default_wa_number_id IS NOT NULL;
"""


def ensure_user_default_wa_number_schema() -> None:
    """Aplica V035 (default_wa_number_id en auth.users) idempotente."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(_V035_USER_DEFAULT_WA_NUMBER_DDL)
            conn.commit()
        logger.info("bootstrap: V035_user_default_wa_number aplicado correctamente")
    except Exception as exc:
        logger.warning(
            "bootstrap: fallo aplicando V035_user_default_wa_number: %s. "
            "La asignacion de linea por asesor no funcionara hasta que la "
            "columna exista.",
            exc,
        )


# ── V027 (file): Campos de carga masiva en crm.leads ────────────────────────
# database/migrations/V027_leads_carga_masiva_fields.sql nunca se incluyó en
# bootstrap. Como producción (EasyPanel) NO ejecuta los .sql, las columnas
# `proyecto`, `estrategia` y `calidad` faltaban y cualquier query contra
# `leads.calidad` (incl. el catálogo) explotaba con UndefinedColumn → 500.
# Idempotente: ALTER TABLE ADD COLUMN IF NOT EXISTS no falla si ya existe.

_V027_LEADS_CARGA_MASIVA_DDL = """
ALTER TABLE crm.leads ADD COLUMN IF NOT EXISTS proyecto        TEXT;
ALTER TABLE crm.leads ADD COLUMN IF NOT EXISTS estrategia      TEXT;
ALTER TABLE crm.leads ADD COLUMN IF NOT EXISTS calidad         TEXT;
ALTER TABLE crm.leads ADD COLUMN IF NOT EXISTS codigo_convenio TEXT;

CREATE INDEX IF NOT EXISTS idx_leads_calidad
    ON crm.leads (calidad)  WHERE activo = TRUE;
CREATE INDEX IF NOT EXISTS idx_leads_proyecto
    ON crm.leads (proyecto) WHERE activo = TRUE;
CREATE INDEX IF NOT EXISTS idx_leads_codigo_convenio
    ON crm.leads (codigo_convenio) WHERE activo = TRUE AND codigo_convenio IS NOT NULL;
"""


def _leads_has_column(column: str) -> bool:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema='crm' AND table_name='leads' AND column_name=%s",
                    (column,),
                )
                return cur.fetchone() is not None
    except Exception:
        return False


def ensure_leads_carga_masiva_fields() -> None:
    """Asegura que crm.leads tenga proyecto/estrategia/calidad/codigo_convenio. Idempotente."""
    try:
        if (
            _leads_has_column("calidad")
            and _leads_has_column("proyecto")
            and _leads_has_column("estrategia")
            and _leads_has_column("codigo_convenio")
        ):
            return
        logger.info("bootstrap: aplicando campos de carga masiva y convenios en crm.leads (idempotente)")
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(_V027_LEADS_CARGA_MASIVA_DDL)
            conn.commit()
        logger.info("bootstrap: campos de carga masiva y convenios aplicados correctamente")
    except Exception as exc:
        logger.warning(
            "bootstrap: fallo aplicando V027_leads_carga_masiva_fields: %s.",
            exc,
        )


# ── V028 (file): Catálogo de calidad (temperatura del lead) ─────────────────
# El número interno colisiona con la etiqueta local de campañas; lo dejamos
# explícito con sufijo _calidad. Copia fiel del contenido de
# database/migrations/V028_catalogo_calidad.sql.

_V028_CATALOGO_CALIDAD_DDL = """
CREATE TABLE IF NOT EXISTS crm.catalogo_calidad (
    id          SERIAL PRIMARY KEY,
    codigo      TEXT NOT NULL UNIQUE,
    nombre      TEXT NOT NULL,
    color_hex   TEXT NOT NULL DEFAULT '#64748b',
    orden       INT  NOT NULL DEFAULT 0,
    activo      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO crm.catalogo_calidad (codigo, nombre, color_hex, orden) VALUES
    ('FRIO',     'Frío',     '#38bdf8', 1),
    ('TIBIO',    'Tibio',    '#f59e0b', 2),
    ('CALIENTE', 'Caliente', '#ef4444', 3)
ON CONFLICT (codigo) DO NOTHING;

ALTER TABLE crm.leads DROP CONSTRAINT IF EXISTS leads_calidad_chk;
"""


def _catalogo_calidad_exists() -> bool:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema='crm' AND table_name='catalogo_calidad'"
                )
                return cur.fetchone() is not None
    except Exception:
        return False


def ensure_catalogo_calidad_schema() -> None:
    """Aplica V028_catalogo_calidad si aun no esta presente. Idempotente."""
    try:
        if _catalogo_calidad_exists():
            logger.info("bootstrap: crm.catalogo_calidad ya existe, saltando V028_calidad")
            return
        logger.info("bootstrap: aplicando V028_catalogo_calidad (idempotente)")
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(_V028_CATALOGO_CALIDAD_DDL)
            conn.commit()
        logger.info("bootstrap: V028_catalogo_calidad aplicado correctamente")
    except Exception as exc:
        logger.warning(
            "bootstrap: fallo aplicando V028_catalogo_calidad: %s. "
            "El catalogo de calidad quedara vacio hasta que el DDL se aplique.",
            exc,
        )


# ── Integraciones (Meta/TikTok/...) — fundación ─────────────────────────────
# Tres tablas para soportar integraciones externas de forma segura y escalable:
#   * crm.integrations_credentials  — KV cifrado por (provider, account_id, key).
#       provider   = 'meta' | 'tiktok' | 'whatsapp' | futuros.
#       account_id = '_global' para secretos a nivel de app (app_secret,
#                    verify_token) o el page_id / advertiser_id para tokens
#                    que son por-cuenta (multi-page, multi-advertiser).
#       key        = nombre del secreto/config ('app_secret', 'access_token',
#                    'polling_interval_minutes', ...).
#       is_secret  = TRUE → value_encrypted (Fernet) y nunca se devuelve en GET.
#                    FALSE → value_plain (config no sensible; se devuelve tal cual).
#       updated_by = UUID del admin que tocó el valor (trazabilidad).
#   * crm.integrations_events       — log de observabilidad (webhooks,
#       polls, ingestas, errores). Alimenta la UI de "Historial" y facilita
#       diagnosticar incidentes sin revisar logs del servidor.
#   * crm.integrations_checkpoint   — cursor de polling por (provider,
#       account_id). Usado por el poller de TikTok (futuro PR).

_INTEGRATIONS_FOUNDATION_DDL = """
CREATE TABLE IF NOT EXISTS crm.integrations_credentials (
    id              BIGSERIAL PRIMARY KEY,
    provider        TEXT NOT NULL,
    account_id      TEXT NOT NULL DEFAULT '_global',
    key             TEXT NOT NULL,
    value_encrypted TEXT,                              -- Fernet ciphertext (is_secret=TRUE)
    value_plain     TEXT,                              -- solo si is_secret=FALSE
    is_secret       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by      UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    UNIQUE (provider, account_id, key)
);

CREATE INDEX IF NOT EXISTS idx_integ_cred_provider
    ON crm.integrations_credentials (provider, account_id);

CREATE TABLE IF NOT EXISTS crm.integrations_events (
    id            BIGSERIAL PRIMARY KEY,
    provider      TEXT NOT NULL,
    account_id    TEXT,
    event_type    TEXT NOT NULL,   -- 'webhook_received' | 'poll_success' | 'lead_created' | 'lead_duplicated' | 'error' | ...
    status        TEXT NOT NULL,   -- 'ok' | 'error' | 'skipped'
    external_id   TEXT,            -- leadgen_id (Meta), lead_id (TikTok), etc.
    lead_id       INTEGER REFERENCES crm.leads(id) ON DELETE SET NULL,
    latency_ms    INTEGER,
    error_message TEXT,
    raw_payload   JSONB,           -- payload normalizado (secretos redactados antes de guardar)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Consulta principal: eventos por provider ordenados por fecha desc (UI historial)
CREATE INDEX IF NOT EXISTS idx_integ_events_provider_time
    ON crm.integrations_events (provider, created_at DESC);

-- Dedupe / tracking por lead externo
CREATE INDEX IF NOT EXISTS idx_integ_events_external_id
    ON crm.integrations_events (provider, external_id)
    WHERE external_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS crm.integrations_checkpoint (
    provider            TEXT NOT NULL,
    account_id          TEXT NOT NULL,
    last_run_at         TIMESTAMPTZ,
    last_success_at     TIMESTAMPTZ,
    last_error          TEXT,
    consecutive_errors  INT  NOT NULL DEFAULT 0,
    items_last_run      INT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (provider, account_id)
);
"""


# ── V029 — Atribución multi-campaña de Meta Lead Ads ──────────────────────
# Tabla append-only que registra CADA submit de Meta por lead. Cuando un
# mismo prospecto completa varios formularios (distintas campañas), el
# dedupe de `ingest_lead_core` reutiliza el lead pero la data de atribución
# nueva se pierde — esta tabla la preserva para timeline y reportes.
_LEAD_INTERACCIONES_META_DDL = """
CREATE TABLE IF NOT EXISTS crm.lead_interacciones_meta (
    id                 BIGSERIAL PRIMARY KEY,
    lead_id            INTEGER NOT NULL REFERENCES crm.leads(id) ON DELETE CASCADE,
    leadgen_id         TEXT NOT NULL,
    page_id            TEXT NOT NULL,
    form_id            TEXT,
    ad_id              TEXT,
    adset_id           TEXT,
    campaign_id        TEXT,
    es_duplicado       BOOLEAN NOT NULL,
    fecha_interaccion  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_field_data     JSONB,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_lead_interacciones_meta_leadgen UNIQUE (leadgen_id)
);

CREATE INDEX IF NOT EXISTS idx_interacciones_meta_lead_fecha
    ON crm.lead_interacciones_meta (lead_id, fecha_interaccion DESC);

CREATE INDEX IF NOT EXISTS idx_interacciones_meta_campaign
    ON crm.lead_interacciones_meta (campaign_id)
    WHERE campaign_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_interacciones_meta_form
    ON crm.lead_interacciones_meta (form_id)
    WHERE form_id IS NOT NULL;
"""


def _lead_interacciones_meta_exists() -> bool:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema='crm' AND table_name='lead_interacciones_meta'"
                )
                return cur.fetchone() is not None
    except Exception:
        return False


def ensure_lead_interacciones_meta_schema() -> None:
    """Aplica V029 si aún no existe. Idempotente."""
    try:
        if _lead_interacciones_meta_exists():
            logger.info("bootstrap: crm.lead_interacciones_meta ya existe, saltando V029")
            return
        logger.info("bootstrap: aplicando V029 lead_interacciones_meta (idempotente)")
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(_LEAD_INTERACCIONES_META_DDL)
            conn.commit()
        logger.info("bootstrap: V029 aplicada correctamente")
    except Exception as exc:
        logger.warning(
            "bootstrap: fallo aplicando V029 lead_interacciones_meta: %s. "
            "Las re-interacciones de Meta no se registrarán hasta que la "
            "tabla exista.",
            exc,
        )


# ─────────────────────────────────────────────────────────────────────────────
# V030 — cache de nombres del catálogo Meta (campañas, formularios, ads).
# Resuelve IDs crudos (ej. "741668672274795") a nombres legibles para la UI
# de Leads y el reporte de integraciones. Append-update, refresh perezoso.
# ─────────────────────────────────────────────────────────────────────────────
_META_CATALOG_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS crm.meta_catalog_cache (
    id            BIGSERIAL PRIMARY KEY,
    entity_type   TEXT NOT NULL CHECK (entity_type IN ('campaign', 'form', 'ad', 'adset')),
    entity_id     TEXT NOT NULL,
    name          TEXT,
    page_id       TEXT,
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    fetch_status  TEXT NOT NULL DEFAULT 'ok'
                  CHECK (fetch_status IN ('ok', 'error', 'not_found')),
    error_message TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_meta_catalog_entity UNIQUE (entity_type, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_meta_catalog_cache_fetched
    ON crm.meta_catalog_cache (fetched_at);
"""


def _meta_catalog_cache_exists() -> bool:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema='crm' AND table_name='meta_catalog_cache'"
                )
                return cur.fetchone() is not None
    except Exception:
        return False


def ensure_meta_catalog_cache_schema() -> None:
    """Aplica V030 si aún no existe. Idempotente."""
    try:
        if _meta_catalog_cache_exists():
            logger.info("bootstrap: crm.meta_catalog_cache ya existe, saltando V030")
            return
        logger.info("bootstrap: aplicando V030 meta_catalog_cache (idempotente)")
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(_META_CATALOG_CACHE_DDL)
            conn.commit()
        logger.info("bootstrap: V030 aplicada correctamente")
    except Exception as exc:
        logger.warning(
            "bootstrap: fallo aplicando V030 meta_catalog_cache: %s. "
            "La UI seguirá mostrando IDs crudos hasta que la tabla exista.",
            exc,
        )


# ─────────────────────────────────────────────────────────────────────────────
# V031 — Field Mappings & Custom Properties (patrón estándar).
# 3 tablas: property_definitions (catálogo), form_field_mappings (reglas),
# lead_properties (storage EAV).
# ─────────────────────────────────────────────────────────────────────────────
_FIELD_MAPPINGS_DDL = """
CREATE TABLE IF NOT EXISTS crm.property_definitions (
    id              BIGSERIAL PRIMARY KEY,
    property_key    TEXT        NOT NULL UNIQUE,
    display_name    TEXT        NOT NULL,
    property_type   TEXT        NOT NULL DEFAULT 'text'
                     CHECK (property_type IN ('text', 'number', 'date', 'boolean', 'select')),
    options         JSONB,
    description     TEXT,
    category        TEXT,
    icon            TEXT,
    is_system       BOOLEAN     NOT NULL DEFAULT FALSE,
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    created_by      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_property_definitions_category
    ON crm.property_definitions (category) WHERE is_active = TRUE;

CREATE TABLE IF NOT EXISTS crm.form_field_mappings (
    id                BIGSERIAL PRIMARY KEY,
    provider          TEXT    NOT NULL DEFAULT 'meta',
    form_id           TEXT    NOT NULL,
    meta_field_name   TEXT    NOT NULL,
    target_type       TEXT    NOT NULL CHECK (target_type IN ('column', 'property', 'ignore')),
    target_key        TEXT,
    created_by        TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_form_field_mapping UNIQUE (provider, form_id, meta_field_name),
    CONSTRAINT ck_form_field_mapping_target
        CHECK (
            (target_type = 'ignore'  AND target_key IS NULL) OR
            (target_type <> 'ignore' AND target_key IS NOT NULL AND length(btrim(target_key)) > 0)
        )
);

CREATE INDEX IF NOT EXISTS idx_form_field_mappings_lookup
    ON crm.form_field_mappings (provider, form_id, meta_field_name);

CREATE TABLE IF NOT EXISTS crm.lead_properties (
    id              BIGSERIAL PRIMARY KEY,
    lead_id         BIGINT      NOT NULL REFERENCES crm.leads(id) ON DELETE CASCADE,
    property_key    TEXT        NOT NULL,
    property_value  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_lead_property UNIQUE (lead_id, property_key)
);

CREATE INDEX IF NOT EXISTS idx_lead_properties_key_value
    ON crm.lead_properties (property_key, property_value);
CREATE INDEX IF NOT EXISTS idx_lead_properties_lead
    ON crm.lead_properties (lead_id);

-- Jobs de backfill: persisten estado entre workers y permiten polling
-- desde el panel sin depender de memoria in-process.
CREATE TABLE IF NOT EXISTS crm.field_mappings_backfill_jobs (
    job_id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    triggered_by   TEXT        NOT NULL,
    status         TEXT        NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending','running','completed','failed','rejected')),
    params         JSONB,
    totals         JSONB,
    error          TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at     TIMESTAMPTZ,
    completed_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_fm_backfill_jobs_created
    ON crm.field_mappings_backfill_jobs (created_at DESC);
"""


def _field_mappings_exists(cur) -> bool:
    # Chequeamos la tabla mas reciente del conjunto para que, al sumar
    # tablas nuevas al DDL, las instalaciones existentes re-apliquen
    # (los CREATE IF NOT EXISTS previos son no-op).
    cur.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='crm' AND table_name='field_mappings_backfill_jobs'"
    )
    return cur.fetchone() is not None


# Clave arbitraria pero estable para el advisory lock que serializa la
# aplicación del DDL entre workers (evita carrera en pg_type cuando varios
# procesos ejecutan CREATE TABLE IF NOT EXISTS concurrentemente).
_FIELD_MAPPINGS_LOCK_KEY = 0x6649454C444D4150  # "fFIELDMAP"


def ensure_field_mappings_schema() -> None:
    """Aplica V031 field_mappings si aún no existe. Idempotente y seguro
    frente a múltiples workers arrancando en paralelo.
    """
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                # Chequeo rápido SIN lock: caso común tras el primer arranque.
                if _field_mappings_exists(cur):
                    logger.info(
                        "bootstrap: field_mappings (todas las tablas) ya existe, saltando V031"
                    )
                    return
                # Serializa el DDL entre workers para evitar la carrera en
                # pg_type (duplicate key en pg_type_typname_nsp_index).
                cur.execute(
                    "SELECT pg_advisory_xact_lock(%s)",
                    (_FIELD_MAPPINGS_LOCK_KEY,),
                )
                # Re-chequeo bajo lock: si otro worker ya lo aplicó, salimos.
                if _field_mappings_exists(cur):
                    logger.info(
                        "bootstrap: V031 aplicada por otro worker, saltando"
                    )
                    return
                logger.info(
                    "bootstrap: aplicando V031 field_mappings (idempotente)"
                )
                cur.execute(_FIELD_MAPPINGS_DDL)
            conn.commit()
        logger.info("bootstrap: V031 aplicada correctamente")
    except Exception as exc:
        logger.warning(
            "bootstrap: fallo aplicando V031 field_mappings: %s. "
            "El mapeo de campos custom no estará disponible hasta que las tablas existan.",
            exc,
        )


def _integrations_foundation_exists() -> bool:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema='crm' AND table_name='integrations_credentials'"
                )
                return cur.fetchone() is not None
    except Exception:
        return False


# ── V032: Enriquecimiento de jerarquia Meta en crm.wa_campaigns ─────────────
# Columnas para cachear nombres reales (ad / adset / campaign) resueltos
# via Graph API a partir del source_id (= ad_id) que llega en el referral CTWA.
_V032_WA_CAMPAIGNS_ENRICHMENT_DDL = """
ALTER TABLE crm.wa_campaigns
    ADD COLUMN IF NOT EXISTS ad_name            TEXT,
    ADD COLUMN IF NOT EXISTS adset_id           VARCHAR(80),
    ADD COLUMN IF NOT EXISTS adset_name         TEXT,
    ADD COLUMN IF NOT EXISTS meta_campaign_id   VARCHAR(80),
    ADD COLUMN IF NOT EXISTS meta_campaign_name TEXT,
    ADD COLUMN IF NOT EXISTS enriched_at        TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS enrich_error       TEXT;

CREATE INDEX IF NOT EXISTS idx_wa_campaigns_needs_enrichment
    ON crm.wa_campaigns (ad_id)
    WHERE enriched_at IS NULL AND ad_id IS NOT NULL;
"""


def _wa_campaigns_enrichment_cols_exist() -> bool:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = 'crm' "
                    "  AND table_name = 'wa_campaigns' "
                    "  AND column_name = 'enriched_at'"
                )
                return cur.fetchone() is not None
    except Exception:
        return False


def ensure_wa_campaigns_enrichment_schema() -> None:
    """Aplica V032 (columnas de enrichment en wa_campaigns) si aun no esta. Idempotente."""
    try:
        if _wa_campaigns_enrichment_cols_exist():
            logger.info(
                "bootstrap: crm.wa_campaigns.enriched_at ya existe, saltando V032"
            )
            return
        logger.info("bootstrap: aplicando V032_wa_campaigns_enrichment (idempotente)")
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(_V032_WA_CAMPAIGNS_ENRICHMENT_DDL)
            conn.commit()
        logger.info("bootstrap: V032_wa_campaigns_enrichment aplicado correctamente")
    except Exception as exc:
        logger.warning(
            "bootstrap: fallo aplicando V032_wa_campaigns_enrichment: %s. "
            "El enrichment de jerarquia Meta en CTWA no podra persistir nombres.",
            exc,
        )


# ── V034: Diferenciar ad.name vs ad.creative.body en wa_campaigns ──────────
# El ad CTWA tiene dos textos distintos: el nombre interno operativo (ad.name)
# y el copy publicitario que vio el cliente (ad.creative.body). Antes los
# confundiamos en `ad_name`. Estas columnas separan el copy del nombre.
_V034_WA_CAMPAIGNS_CREATIVE_DDL = """
ALTER TABLE crm.wa_campaigns
    ADD COLUMN IF NOT EXISTS creative_body  TEXT,
    ADD COLUMN IF NOT EXISTS creative_title TEXT;
"""


def _wa_campaigns_creative_cols_exist() -> bool:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = 'crm' "
                    "  AND table_name = 'wa_campaigns' "
                    "  AND column_name = 'creative_body'"
                )
                return cur.fetchone() is not None
    except Exception:
        return False


def ensure_wa_campaigns_creative_schema() -> None:
    """Aplica V034 (creative_body/creative_title en wa_campaigns). Idempotente."""
    try:
        if _wa_campaigns_creative_cols_exist():
            logger.info(
                "bootstrap: crm.wa_campaigns.creative_body ya existe, saltando V034"
            )
            return
        logger.info("bootstrap: aplicando V034_wa_campaigns_creative (idempotente)")
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(_V034_WA_CAMPAIGNS_CREATIVE_DDL)
            conn.commit()
        logger.info("bootstrap: V034_wa_campaigns_creative aplicado correctamente")
    except Exception as exc:
        logger.warning(
            "bootstrap: fallo aplicando V034_wa_campaigns_creative: %s. "
            "El banner CTWA no podra mostrar el copy del anuncio separado del ad_name.",
            exc,
        )


# ── V037: Creative media (thumbnail/image/video) del ad en wa_campaigns ────
# El panel "Info del contacto" muestra un preview visual del creative que
# vio el cliente antes de iniciar el chat. Lo descargamos una vez desde el
# CDN de Meta (fbcdn.net, URLs firmadas y volatiles) y lo cacheamos como
# BYTEA en crm.meta_creative_cache para servirlo desde nuestro backend sin
# depender del CDN externo ni filtrar URLs con token.
_V037_WA_CAMPAIGNS_CREATIVE_MEDIA_DDL = """
ALTER TABLE crm.wa_campaigns
    ADD COLUMN IF NOT EXISTS creative_media_type       VARCHAR(20),
    ADD COLUMN IF NOT EXISTS creative_thumbnail_url    TEXT,
    ADD COLUMN IF NOT EXISTS creative_image_url        TEXT,
    ADD COLUMN IF NOT EXISTS creative_video_id         VARCHAR(80),
    ADD COLUMN IF NOT EXISTS creative_object_story_id  VARCHAR(120),
    ADD COLUMN IF NOT EXISTS creative_media_cached_at  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS creative_media_error      TEXT;

CREATE TABLE IF NOT EXISTS crm.meta_creative_cache (
    wa_campaign_id  BIGINT PRIMARY KEY
        REFERENCES crm.wa_campaigns(id) ON DELETE CASCADE,
    media_kind      VARCHAR(20) NOT NULL,
    mime_type       TEXT        NOT NULL,
    size_bytes      BIGINT,
    data            BYTEA       NOT NULL,
    source_url      TEXT,
    cached_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_meta_creative_cache_cached_at
    ON crm.meta_creative_cache (cached_at DESC);
"""


def _wa_campaigns_creative_media_cols_exist() -> bool:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = 'crm' "
                    "  AND table_name = 'wa_campaigns' "
                    "  AND column_name = 'creative_thumbnail_url'"
                )
                return cur.fetchone() is not None
    except Exception:
        return False


def ensure_wa_campaigns_creative_media_schema() -> None:
    """Aplica V037 (creative media + meta_creative_cache). Idempotente."""
    try:
        if _wa_campaigns_creative_media_cols_exist():
            logger.info(
                "bootstrap: crm.wa_campaigns.creative_thumbnail_url ya existe, saltando V037"
            )
            return
        logger.info("bootstrap: aplicando V037_wa_campaigns_creative_media (idempotente)")
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(_V037_WA_CAMPAIGNS_CREATIVE_MEDIA_DDL)
            conn.commit()
        logger.info("bootstrap: V037_wa_campaigns_creative_media aplicado correctamente")
    except Exception as exc:
        logger.warning(
            "bootstrap: fallo aplicando V037_wa_campaigns_creative_media: %s. "
            "El panel Info del contacto no podra mostrar preview visual del ad.",
            exc,
        )

def ensure_wa_ctwa_clid_schema() -> None:
    """V125 / V070.73 - Safety net: garantiza que wa_ctwa_clid y campos CTWA sean TEXT."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_schema = 'crm' AND table_name = 'leads' AND column_name = 'wa_ctwa_clid'
                              AND data_type <> 'text'
                        ) THEN
                            ALTER TABLE crm.leads ALTER COLUMN wa_ctwa_clid TYPE TEXT;
                        END IF;

                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_schema = 'crm' AND table_name = 'leads' AND column_name = 'wa_campaign_ad_id'
                              AND data_type <> 'text'
                        ) THEN
                            ALTER TABLE crm.leads ALTER COLUMN wa_campaign_ad_id TYPE TEXT;
                        END IF;

                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_schema = 'crm' AND table_name = 'wa_campaigns' AND column_name = 'name'
                              AND data_type <> 'text'
                        ) THEN
                            ALTER TABLE crm.wa_campaigns ALTER COLUMN name TYPE TEXT;
                        END IF;

                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_schema = 'crm' AND table_name = 'wa_campaigns' AND column_name = 'ad_id'
                              AND data_type <> 'text'
                        ) THEN
                            ALTER TABLE crm.wa_campaigns ALTER COLUMN ad_id TYPE TEXT;
                        END IF;
                    END $$;
                    """
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("ensure_wa_ctwa_clid_schema no-op: %s", exc)


def ensure_wa_webhook_events_schema() -> None:
    """V128: Garantiza que la tabla de auditoría continua crm.wa_webhook_events exista."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS crm.wa_webhook_events (
                        id BIGSERIAL PRIMARY KEY,
                        received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        event_type VARCHAR(50) NOT NULL,
                        wa_phone VARCHAR(50),
                        wamid VARCHAR(255),
                        phone_number_id VARCHAR(50),
                        display_phone_number VARCHAR(50),
                        contact_name VARCHAR(255),
                        has_referral BOOLEAN NOT NULL DEFAULT FALSE,
                        referral_ad_id VARCHAR(100),
                        referral_headline VARCHAR(255),
                        referral_source_type VARCHAR(50),
                        lead_id INT REFERENCES crm.leads(id) ON DELETE SET NULL,
                        conversation_id INT REFERENCES crm.wa_conversations(id) ON DELETE SET NULL,
                        outcome VARCHAR(50) NOT NULL,
                        error_detail TEXT,
                        metadata JSONB DEFAULT '{}'::jsonb,
                        payload JSONB
                    );
                    CREATE INDEX IF NOT EXISTS idx_wa_webhook_events_received ON crm.wa_webhook_events(received_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_wa_webhook_events_phone ON crm.wa_webhook_events(wa_phone);
                    CREATE INDEX IF NOT EXISTS idx_wa_webhook_events_wamid ON crm.wa_webhook_events(wamid);
                    CREATE INDEX IF NOT EXISTS idx_wa_webhook_events_ad_id ON crm.wa_webhook_events(referral_ad_id) WHERE referral_ad_id IS NOT NULL;
                    CREATE INDEX IF NOT EXISTS idx_wa_webhook_events_outcome ON crm.wa_webhook_events(outcome);
                    CREATE INDEX IF NOT EXISTS idx_wa_webhook_events_has_referral ON crm.wa_webhook_events(has_referral) WHERE has_referral = TRUE;
                    CREATE INDEX IF NOT EXISTS idx_wa_webhook_events_lead_id ON crm.wa_webhook_events(lead_id) WHERE lead_id IS NOT NULL;
                    """
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("ensure_wa_webhook_events_schema error: %s", exc)



_V035_SUPERVISOR_ID_DDL = """
ALTER TABLE crm.leads
    ADD COLUMN IF NOT EXISTS supervisor_id UUID
        REFERENCES auth.users(id)
        ON DELETE SET NULL;

ALTER TABLE crm.leads
    ADD COLUMN IF NOT EXISTS fecha_entrada_cola TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_leads_supervisor_id
    ON crm.leads (supervisor_id)
    WHERE activo = TRUE;

CREATE INDEX IF NOT EXISTS idx_leads_cola_estancada
    ON crm.leads (fecha_entrada_cola)
    WHERE activo = TRUE AND asesor_id IS NULL;

UPDATE crm.leads l
SET supervisor_id      = l.asesor_id,
    asesor_id          = NULL,
    fecha_entrada_cola = COALESCE(l.updated_at, l.created_at)
FROM auth.users u
WHERE u.id = l.asesor_id
  AND u.role = 'supervisor'
  AND l.supervisor_id IS NULL;

UPDATE crm.leads l
SET supervisor_id = eq.supervisor_id
FROM crm.equipos eq
WHERE eq.asesor_id = l.asesor_id
  AND eq.activo = TRUE
  AND l.supervisor_id IS NULL
  AND l.asesor_id IS NOT NULL;
"""


_V035_VIEW_DDL = """
CREATE OR REPLACE VIEW crm.vw_leads_dashboard AS
WITH todas_interacciones AS (
    SELECT
        id,
        lead_id,
        asesor_id,
        tipo_contacto,
        resultado,
        notas,
        fecha_proxima_accion,
        fecha_cita,
        created_at
    FROM crm.contactos
    WHERE tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
    UNION ALL
    SELECT
        id,
        lead_id,
        asesor_id,
        CASE tipo
            WHEN 'entrante' THEN 'llamada_entrante'
            WHEN 'saliente' THEN 'llamada_saliente'
            ELSE 'llamada'
        END AS tipo_contacto,
        CASE
            WHEN duracion_segundos > 0 THEN 'contesto'
            ELSE 'no_contesto'
        END AS resultado,
        NULL::text AS notas,
        NULL::timestamp without time zone AS fecha_proxima_accion,
        NULL::timestamp without time zone AS fecha_cita,
        fecha_llamada AS created_at
    FROM crm.llamadas
    WHERE lead_id IS NOT NULL
),
ultimo_contacto AS (
    SELECT DISTINCT ON (lead_id)
        lead_id,
        id                   AS contacto_id,
        tipo_contacto        AS ultimo_tipo_contacto,
        resultado            AS ultimo_resultado,
        notas                AS ultimas_notas,
        fecha_proxima_accion,
        fecha_cita           AS proxima_cita,
        created_at           AS fecha_ultimo_contacto
    FROM todas_interacciones
    ORDER BY lead_id, created_at DESC
),
contactos_count AS (
    SELECT lead_id, COUNT(*)::int AS total
    FROM todas_interacciones
    GROUP BY lead_id
),
primer_contacto AS (
    SELECT lead_id, MIN(created_at) AS fecha_primer_contacto
    FROM todas_interacciones
    GROUP BY lead_id
),
primera_asignacion AS (
    SELECT lead_id, MIN(ts) AS fecha_asignacion
    FROM (
        SELECT lead_id, created_at AS ts
        FROM crm.asignaciones_log
        UNION ALL
        SELECT lead_id, fecha AS ts
        FROM crm.assignment_log
        UNION ALL
        SELECT id AS lead_id, created_at AS ts
        FROM crm.leads
        WHERE asesor_id IS NOT NULL
    ) _all
    GROUP BY lead_id
)
SELECT
    l.id,
    l.nombres,
    l.apellidos,
    TRIM(COALESCE(l.nombres, '') || ' ' || COALESCE(l.apellidos, '')) AS nombre_completo,
    l.telefono,
    l.email,
    l.ciudad,
    l.trabajo,
    l.es_recontacto,
    COALESCE(cc.total, 0)   AS intentos_contacto,
    l.observaciones,
    l.datos_extra,
    l.hash_dedup,
    l.activo,
    l.created_at            AS fecha_ingreso,
    l.updated_at,
    l.estado_id,
    e.nombre                AS estado_nombre,
    e.color_hex             AS estado_color,
    e.es_final              AS estado_es_final,
    l.fuente_id,
    f.nombre                AS fuente_nombre,
    l.fuente_externa_id,
    l.campana,
    l.asesor_id,
    TRIM(COALESCE(a.first_name, '') || ' ' || COALESCE(a.last_name, '')) AS asesor_nombre,
    a.email                 AS asesor_email,
    COALESCE(l.supervisor_id, eq.supervisor_id)                       AS supervisor_id,
    TRIM(COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, '')) AS supervisor_nombre,
    uc.contacto_id,
    uc.ultimo_tipo_contacto,
    uc.ultimo_resultado,
    uc.ultimas_notas,
    uc.fecha_ultimo_contacto,
    uc.fecha_proxima_accion,
    uc.proxima_cita,
    CASE
        WHEN uc.fecha_ultimo_contacto IS NULL THEN TRUE
        WHEN uc.fecha_ultimo_contacto < NOW() - INTERVAL '24 hours' THEN TRUE
        ELSE FALSE
    END                     AS sin_contacto_reciente,
    EXTRACT(EPOCH FROM (NOW() - l.created_at)) / 3600 AS horas_desde_ingreso,
    pa.fecha_asignacion,
    pc.fecha_primer_contacto,
    l.proyecto,
    l.estrategia,
    l.calidad,
    l.fecha_entrada_cola,
    CASE
        WHEN l.asesor_id IS NULL
         AND l.fecha_entrada_cola IS NOT NULL
         AND l.fecha_entrada_cola < NOW() - INTERVAL '24 hours'
        THEN TRUE
        ELSE FALSE
    END                     AS cola_estancada,
    l.dni,
    l.tipo_documento,
    l.fecha_ultimo_recontacto
FROM crm.leads l
LEFT JOIN crm.estados_lead   e  ON e.id  = l.estado_id
LEFT JOIN crm.fuentes        f  ON f.id  = l.fuente_id
LEFT JOIN auth.users         a  ON a.id  = l.asesor_id
LEFT JOIN crm.equipos        eq ON eq.asesor_id = l.asesor_id AND eq.activo = TRUE
LEFT JOIN auth.users         s  ON s.id  = COALESCE(l.supervisor_id, eq.supervisor_id)
LEFT JOIN ultimo_contacto    uc ON uc.lead_id = l.id
LEFT JOIN contactos_count    cc ON cc.lead_id = l.id
LEFT JOIN primer_contacto    pc ON pc.lead_id = l.id
LEFT JOIN primera_asignacion pa ON pa.lead_id = l.id
WHERE l.activo = TRUE;

CREATE OR REPLACE VIEW crm.vw_kpis_por_supervisor AS
WITH leads_del_supervisor AS (
    SELECT l.id, l.estado_id, l.created_at, l.activo, eq.supervisor_id
    FROM crm.leads l
    JOIN crm.equipos eq
      ON eq.asesor_id = l.asesor_id AND eq.activo = TRUE
    WHERE l.activo = TRUE
    UNION
    SELECT l.id, l.estado_id, l.created_at, l.activo, l.supervisor_id
    FROM crm.leads l
    WHERE l.activo = TRUE
      AND l.asesor_id IS NULL
      AND l.supervisor_id IS NOT NULL
)
SELECT
    s.id                    AS supervisor_id,
    TRIM(COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, '')) AS supervisor_nombre,
    s.email                 AS supervisor_email,
    COUNT(DISTINCT eq.asesor_id)    AS total_asesores,
    COUNT(lds.id)           AS total_leads,
    COUNT(lds.id) FILTER (WHERE e.nombre = 'Nuevo')          AS leads_nuevo,
    COUNT(lds.id) FILTER (WHERE e.nombre = 'Contactado')     AS leads_contactado,
    COUNT(lds.id) FILTER (WHERE e.nombre = 'Calificado')     AS leads_calificado,
    COUNT(lds.id) FILTER (WHERE e.nombre = 'En negociación') AS leads_en_negociacion,
    COUNT(lds.id) FILTER (
        WHERE e.nombre ILIKE '%%matr%%'
           OR e.nombre ILIKE '%%ganad%%'
           OR e.nombre ILIKE '%%cierr%%'
    )                                                      AS leads_ganado,
    COUNT(lds.id) FILTER (WHERE e.nombre = 'Perdido')        AS leads_perdido,
    COUNT(lds.id) FILTER (WHERE e.nombre = 'No interesado')  AS leads_no_interesado,
    CASE
        WHEN COUNT(lds.id) = 0 THEN 0
        ELSE ROUND(
            100.0 * COUNT(lds.id) FILTER (
                WHERE e.nombre ILIKE '%%matr%%'
                   OR e.nombre ILIKE '%%ganad%%'
                   OR e.nombre ILIKE '%%cierr%%'
            ) / COUNT(lds.id),
            2
        )
    END                     AS tasa_conversion_pct,
    COUNT(lds.id) FILTER (
        WHERE lds.created_at >= CURRENT_DATE::TIMESTAMPTZ
    )                       AS leads_hoy,
    COUNT(lds.id) FILTER (
        WHERE lds.created_at >= NOW() - INTERVAL '7 days'
    )                       AS leads_ultimos_7dias,
    COUNT(lds.id) FILTER (
        WHERE lds.created_at >= NOW() - INTERVAL '30 days'
    )                       AS leads_ultimos_30dias,
    COUNT(lds.id) FILTER (
        WHERE lds.id IN (
            SELECT id FROM crm.leads
            WHERE supervisor_id = s.id AND asesor_id IS NULL AND activo = TRUE
        )
    )                       AS leads_en_cola
FROM auth.users s
LEFT JOIN crm.equipos eq
    ON eq.supervisor_id = s.id AND eq.activo = TRUE
LEFT JOIN leads_del_supervisor lds
    ON lds.supervisor_id = s.id
LEFT JOIN crm.estados_lead e
    ON e.id = lds.estado_id
WHERE s.role = 'supervisor'
  AND s.is_active = TRUE
GROUP BY s.id, s.first_name, s.last_name, s.email;
"""


def _leads_supervisor_id_col_exists() -> bool:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = 'crm' "
                    "  AND table_name = 'leads' "
                    "  AND column_name = 'supervisor_id'"
                )
                return cur.fetchone() is not None
    except Exception:
        return False


def ensure_supervisor_id_schema() -> None:
    """Aplica V035 (supervisor_id + fecha_entrada_cola en crm.leads). Idempotente.

    Separa el supervisor del asesor para que los leads entrantes de FB/IG/WA
    no queden atrapados como "ya asignados" cuando en realidad deben entrar
    a la cola de asignación del supervisor.
    """
    try:
        already_migrated = _leads_supervisor_id_col_exists()
        with get_db() as conn:
            with conn.cursor() as cur:
                if not already_migrated:
                    logger.info("bootstrap: aplicando V035_supervisor_id_en_leads (idempotente)")
                    cur.execute(_V035_SUPERVISOR_ID_DDL)
            conn.commit()
        if already_migrated:
            logger.info(
                "bootstrap: crm.leads.supervisor_id ya existe (OK)"
            )
        else:
            logger.info("bootstrap: V035_supervisor_id_en_leads aplicado correctamente")
    except Exception as exc:
        logger.warning(
            "bootstrap: fallo aplicando V035_supervisor_id_en_leads: %s. "
            "El panel de asignación no podrá separar supervisor de asesor hasta que se aplique.",
            exc,
        )


def ensure_integrations_foundation_schema() -> None:
    """Aplica la fundación de integraciones si aún no existe. Idempotente."""
    try:
        if _integrations_foundation_exists():
            logger.info("bootstrap: crm.integrations_credentials ya existe, saltando integrations_foundation")
            return
        logger.info("bootstrap: aplicando integrations_foundation (idempotente)")
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(_INTEGRATIONS_FOUNDATION_DDL)
            conn.commit()
        logger.info("bootstrap: integrations_foundation aplicado correctamente")
    except Exception as exc:
        logger.warning(
            "bootstrap: fallo aplicando integrations_foundation: %s. "
            "Las integraciones externas no podrán guardar credenciales ni registrar eventos "
            "hasta que las tablas existan.",
            exc,
        )


def ensure_new_features_schema() -> None:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS supervisor_jefe_id UUID REFERENCES auth.users(id) ON DELETE SET NULL")
                cur.execute("ALTER TABLE crm.lead_assignment_rules ADD COLUMN IF NOT EXISTS campana_exclude_pattern VARCHAR(200)")
                cur.execute("ALTER TABLE crm.lead_assignment_rules ALTER COLUMN asignar_a_tipo TYPE VARCHAR(50)")
                cur.execute("ALTER TABLE crm.assignment_config ADD COLUMN IF NOT EXISTS incluir_supervisor_en_rotacion BOOLEAN NOT NULL DEFAULT FALSE")
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("bootstrap: ensure_new_features_schema error: %s", exc)


def ensure_kpis_view_fix() -> None:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DROP VIEW IF EXISTS crm.vw_kpis_por_asesor CASCADE;
                    CREATE OR REPLACE VIEW crm.vw_kpis_por_asesor AS
                    SELECT
                        a.id                                                   AS asesor_id,
                        TRIM(COALESCE(a.first_name, '') || ' ' || COALESCE(a.last_name, '')) AS asesor_nombre,
                        a.email                                                AS asesor_email,
                        COALESCE(eq.supervisor_id, l.supervisor_id)           AS supervisor_id,
                        TRIM(COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, '')) AS supervisor_nombre,
                        COUNT(l.id)                                            AS total_leads,
                        COUNT(l.id) FILTER (WHERE e.nombre = 'Nuevo')          AS leads_nuevo,
                        COUNT(l.id) FILTER (WHERE e.nombre = 'Contactado')     AS leads_contactado,
                        COUNT(l.id) FILTER (WHERE e.nombre = 'Calificado')     AS leads_calificado,
                        COUNT(l.id) FILTER (WHERE e.nombre = 'En negociación') AS leads_en_negociacion,
                        COUNT(l.id) FILTER (
                            WHERE e.nombre ILIKE '%%matr%%'
                               OR e.nombre ILIKE '%%ganad%%'
                               OR e.nombre ILIKE '%%cierr%%'
                               OR l.tipo_cierre IS NOT NULL
                        )                                                      AS leads_ganado,
                        COUNT(l.id) FILTER (WHERE e.nombre = 'Perdido')        AS leads_perdido,
                        COUNT(l.id) FILTER (WHERE e.nombre = 'No interesado')  AS leads_no_interesado,
                        COUNT(l.id) FILTER (
                            WHERE NOT EXISTS (
                                SELECT 1 FROM crm.contactos c
                                WHERE c.lead_id = l.id
                                  AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                            )
                        )                                                      AS leads_sin_contacto,
                        COUNT(DISTINCT co_vencido.lead_id)                     AS leads_accion_vencida,
                        CASE
                            WHEN COUNT(l.id) = 0 THEN 0
                            ELSE ROUND(
                                100.0 * COUNT(l.id) FILTER (
                                    WHERE e.nombre ILIKE '%%matr%%'
                                       OR e.nombre ILIKE '%%ganad%%'
                                       OR e.nombre ILIKE '%%cierr%%'
                                       OR l.tipo_cierre IS NOT NULL
                                ) / COUNT(l.id),
                                2
                            )
                        END                                                    AS tasa_conversion_pct
                    FROM auth.users a
                    LEFT JOIN crm.equipos eq
                        ON eq.asesor_id = a.id AND eq.activo = TRUE
                    LEFT JOIN crm.leads l
                        ON l.asesor_id = a.id AND l.activo = TRUE
                    LEFT JOIN auth.users s
                        ON s.id = COALESCE(eq.supervisor_id, l.supervisor_id)
                    LEFT JOIN crm.estados_lead e
                        ON e.id = l.estado_id
                    LEFT JOIN LATERAL (
                        SELECT c.lead_id
                        FROM crm.contactos c
                        WHERE c.lead_id = l.id
                          AND c.tipo_contacto NOT IN ('cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion')
                          AND c.fecha_proxima_accion < NOW()
                        ORDER BY c.created_at DESC
                        LIMIT 1
                    ) co_vencido ON co_vencido.lead_id = l.id
                    WHERE a.role IN ('asesor', 'supervisor')
                      AND (a.is_active = TRUE OR l.id IS NOT NULL)
                    GROUP BY a.id, a.first_name, a.last_name, a.email, COALESCE(eq.supervisor_id, l.supervisor_id), s.first_name, s.last_name;
                    """
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("bootstrap: ensure_kpis_view_fix error: %s", exc)


def ensure_canonical_fuentes() -> None:
    """Asegura la presencia de fuentes estándar en crm.fuentes sin modificar leads existentes."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO crm.fuentes (nombre, activo) VALUES
                        ('TikTok',    TRUE),
                        ('Facebook',  TRUE),
                        ('Instagram', TRUE),
                        ('WhatsApp',  TRUE),
                        ('Web',       TRUE),
                        ('Referido',  TRUE),
                        ('Manual',    TRUE)
                    ON CONFLICT (nombre) DO NOTHING;
                    """
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("bootstrap: ensure_canonical_fuentes error: %s", exc)


def ensure_campaign_supervisor_assignments_schema() -> None:
    """V110 + V113 — Tabla de mapeo de campañas Meta/TikTok a supervisores y modo de reparto."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS crm.campaign_supervisor_assignments (
                        id                BIGSERIAL PRIMARY KEY,
                        provider          VARCHAR(30) NOT NULL CHECK (provider IN ('meta', 'tiktok', 'general')),
                        campaign_id       VARCHAR(255) NOT NULL,
                        campaign_name     VARCHAR(255),
                        account_id        VARCHAR(255),
                        status            VARCHAR(50) NOT NULL DEFAULT 'ACTIVE',
                        objective         VARCHAR(100),
                        supervisor_id     UUID REFERENCES auth.users(id) ON DELETE SET NULL,
                        distribution_mode VARCHAR(30) NOT NULL DEFAULT 'supervisor' CHECK (distribution_mode IN ('supervisor', 'equipo', 'todos')),
                        is_active         BOOLEAN NOT NULL DEFAULT TRUE,
                        last_sync_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        created_by        UUID REFERENCES auth.users(id) ON DELETE SET NULL,
                        updated_by        UUID REFERENCES auth.users(id) ON DELETE SET NULL,
                        CONSTRAINT uq_campaign_provider_id UNIQUE (provider, campaign_id)
                    );

                    ALTER TABLE crm.campaign_supervisor_assignments
                        ADD COLUMN IF NOT EXISTS distribution_mode VARCHAR(30) NOT NULL DEFAULT 'supervisor';

                    ALTER TABLE crm.campaign_supervisor_assignments
                        DROP CONSTRAINT IF EXISTS campaign_supervisor_assignments_distribution_mode_check,
                        DROP CONSTRAINT IF EXISTS chk_campaign_distribution_mode;

                    ALTER TABLE crm.campaign_supervisor_assignments
                        ADD CONSTRAINT chk_campaign_distribution_mode
                        CHECK (distribution_mode IN ('supervisor', 'equipo', 'todos'));

                    CREATE INDEX IF NOT EXISTS idx_camp_assignments_sup
                        ON crm.campaign_supervisor_assignments (supervisor_id)
                        WHERE supervisor_id IS NOT NULL;

                    CREATE INDEX IF NOT EXISTS idx_camp_assignments_prov_stat
                        ON crm.campaign_supervisor_assignments (provider, status);

                    CREATE INDEX IF NOT EXISTS idx_camp_assignments_name
                        ON crm.campaign_supervisor_assignments (LOWER(campaign_name));

                    -- V114: Multi-supervisor y rotación equitativa
                    CREATE TABLE IF NOT EXISTS crm.campaign_assigned_supervisors (
                        id                  BIGSERIAL PRIMARY KEY,
                        assignment_id       BIGINT NOT NULL REFERENCES crm.campaign_supervisor_assignments(id) ON DELETE CASCADE,
                        supervisor_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
                        last_assigned_at    TIMESTAMPTZ DEFAULT NULL,
                        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        CONSTRAINT uq_campaign_assigned_supervisor UNIQUE (assignment_id, supervisor_id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_camp_assigned_sups_assign
                        ON crm.campaign_assigned_supervisors (assignment_id);

                    CREATE INDEX IF NOT EXISTS idx_camp_assigned_sups_sup
                        ON crm.campaign_assigned_supervisors (supervisor_id);

                    CREATE INDEX IF NOT EXISTS idx_camp_assigned_sups_rot
                        ON crm.campaign_assigned_supervisors (assignment_id, last_assigned_at NULLS FIRST);

                    INSERT INTO crm.campaign_assigned_supervisors (assignment_id, supervisor_id, created_at)
                    SELECT c.id, c.supervisor_id, NOW()
                    FROM crm.campaign_supervisor_assignments c
                    JOIN auth.users u ON u.id = c.supervisor_id
                    WHERE c.supervisor_id IS NOT NULL
                    ON CONFLICT (assignment_id, supervisor_id) DO NOTHING;

                    -- V121: Reparto personalizado por porcentajes
                    ALTER TABLE crm.campaign_assigned_supervisors
                        ADD COLUMN IF NOT EXISTS porcentaje INT DEFAULT NULL,
                        ADD COLUMN IF NOT EXISTS assigned_count INT NOT NULL DEFAULT 0;

                    -- V122: Reparto personalizado por equipo y modo 'todos'
                    ALTER TABLE crm.campaign_assigned_supervisors
                        ADD COLUMN IF NOT EXISTS distribution_mode VARCHAR(30) DEFAULT NULL,
                        ADD COLUMN IF NOT EXISTS member_percentages JSONB DEFAULT NULL,
                        ADD COLUMN IF NOT EXISTS member_counts JSONB DEFAULT NULL,
                        ADD COLUMN IF NOT EXISTS member_last_assigned JSONB DEFAULT NULL;

                    -- V115: Deduplicar y fusionar campañas TikTok erróneamente registradas como Meta
                    UPDATE crm.campaign_supervisor_assignments t
                    SET campaign_name = m.campaign_name,
                        supervisor_id = COALESCE(t.supervisor_id, m.supervisor_id),
                        distribution_mode = CASE WHEN t.supervisor_id IS NULL AND m.supervisor_id IS NOT NULL THEN m.distribution_mode ELSE t.distribution_mode END,
                        updated_at = NOW()
                    FROM crm.campaign_supervisor_assignments m
                    WHERE m.campaign_id = t.campaign_id
                      AND m.provider = 'meta'
                      AND t.provider = 'tiktok'
                      AND m.campaign_name IS NOT NULL
                      AND m.campaign_name !~ '^\\d+$';

                    INSERT INTO crm.campaign_assigned_supervisors (assignment_id, supervisor_id, last_assigned_at, created_at)
                    SELECT t.id, cas.supervisor_id, cas.last_assigned_at, cas.created_at
                    FROM crm.campaign_supervisor_assignments m
                    JOIN crm.campaign_supervisor_assignments t
                      ON t.campaign_id = m.campaign_id AND t.provider = 'tiktok'
                    JOIN crm.campaign_assigned_supervisors cas
                      ON cas.assignment_id = m.id
                    WHERE m.provider = 'meta'
                    ON CONFLICT (assignment_id, supervisor_id) DO NOTHING;

                    DELETE FROM crm.campaign_supervisor_assignments m
                    USING crm.campaign_supervisor_assignments t
                    WHERE m.campaign_id = t.campaign_id
                      AND m.provider = 'meta'
                      AND t.provider = 'tiktok';

                    UPDATE crm.campaign_supervisor_assignments m
                    SET provider = 'tiktok',
                        updated_at = NOW()
                    WHERE m.provider = 'meta'
                      AND EXISTS (
                          SELECT 1
                          FROM crm.leads l
                          JOIN crm.fuentes f ON f.id = l.fuente_id
                          WHERE (l.campana = m.campaign_id OR l.campana = m.campaign_name)
                            AND LOWER(f.nombre) LIKE '%tiktok%'
                      )
                      AND NOT EXISTS (
                          SELECT 1
                          FROM crm.leads l2
                          JOIN crm.fuentes f2 ON f2.id = l2.fuente_id
                          WHERE (l2.campana = m.campaign_id OR l2.campana = m.campaign_name)
                            AND (LOWER(f2.nombre) LIKE '%facebook%' OR LOWER(f2.nombre) LIKE '%instagram%' OR LOWER(f2.nombre) LIKE '%meta%')
                      )
                      AND NOT EXISTS (
                          SELECT 1
                          FROM crm.campaign_supervisor_assignments t2
                          WHERE t2.provider = 'tiktok' AND t2.campaign_id = m.campaign_id
                      );
                    """
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("bootstrap: ensure_campaign_supervisor_assignments_schema error: %s", exc)



def ensure_oportunidad_futura_schema() -> None:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("ALTER TABLE crm.leads ADD COLUMN IF NOT EXISTS accion_proxima_gestion TEXT;")
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("bootstrap: ensure_oportunidad_futura_schema error: %s", exc)


def ensure_proxima_gestion_notificada_schema() -> None:
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "ALTER TABLE crm.leads ADD COLUMN IF NOT EXISTS proxima_gestion_notificada_at TIMESTAMPTZ DEFAULT NULL;"
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("bootstrap: ensure_proxima_gestion_notificada_schema error: %s", exc)


def ensure_lead_historial_schema() -> None:
    """Asegura la existencia de la tabla crm.lead_historial_cambios y sus indices."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS crm.lead_historial_cambios (
                        id                  BIGSERIAL PRIMARY KEY,
                        lead_id             INTEGER NOT NULL REFERENCES crm.leads(id) ON DELETE CASCADE,
                        usuario_id          UUID REFERENCES auth.users(id) ON DELETE SET NULL,
                        usuario_nombre      TEXT,
                        usuario_rol         TEXT,
                        campo               TEXT NOT NULL,
                        campo_label         TEXT NOT NULL,
                        valor_anterior      TEXT,
                        valor_nuevo         TEXT,
                        origen              TEXT NOT NULL DEFAULT 'edicion_ficha',
                        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );

                    CREATE INDEX IF NOT EXISTS idx_lead_historial_cambios_lead_created
                        ON crm.lead_historial_cambios (lead_id, created_at DESC);

                    CREATE INDEX IF NOT EXISTS idx_lead_historial_cambios_usuario
                        ON crm.lead_historial_cambios (usuario_id)
                        WHERE usuario_id IS NOT NULL;

                    CREATE INDEX IF NOT EXISTS idx_lead_historial_cambios_campo
                        ON crm.lead_historial_cambios (campo);
                    """
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("bootstrap: ensure_lead_historial_schema error: %s", exc)


STARTUP_BOOTSTRAP_LOCK_ID = 849204821


def run_startup_bootstrap() -> None:
    """Punto único de entrada — llámese desde el lifespan de FastAPI.

    Garantiza con advisory lock que solo un worker ejecute el bootstrap a la vez.
    """
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s)", (STARTUP_BOOTSTRAP_LOCK_ID,))
                acquired = cur.fetchone()[0]
            if not acquired:
                logger.info("[bootstrap] Otro worker ya está ejecutando el startup bootstrap — skip.")
                return

            try:
                # FASE 0 — auto-bootstrap del schema base para fresh installs.
                try:
                    from app.schema_bootstrap import ensure_base_schema
                    ensure_base_schema()
                except Exception as exc:  # noqa: BLE001
                    logger.error("[bootstrap] schema_bootstrap crashed: %s", exc)

                ensure_new_features_schema()
                ensure_kpis_view_fix()
                ensure_canonical_fuentes()
                ensure_public_forms_schema()
                ensure_whatsapp_schema()
                ensure_whatsapp_classification_schema()
                ensure_whatsapp_multiple_cases_schema()
                ensure_lead_tags_schema()
                ensure_wa_conversation_tags_schema()
                ensure_wa_ui_labels_schema()
                ensure_campanas_schema()
                ensure_leads_carga_masiva_fields()
                ensure_catalogo_calidad_schema()
                ensure_integrations_foundation_schema()
                ensure_lead_interacciones_meta_schema()
                ensure_meta_catalog_cache_schema()
                ensure_field_mappings_schema()
                ensure_view_v029()
                ensure_wa_media_cache_schema()
                ensure_wa_messages_risk_flags_schema()
                ensure_wa_numbers_schema()
                ensure_wa_babas_schema()
                ensure_user_default_wa_number_schema()
                ensure_wa_campaigns_enrichment_schema()
                ensure_wa_campaigns_creative_schema()
                ensure_wa_campaigns_creative_media_schema()
                ensure_wa_ctwa_clid_schema()
                ensure_wa_webhook_events_schema()
                ensure_supervisor_id_schema()
                ensure_lead_recontactos_external_created_at()
                ensure_recontacto_backfill()

                # ── Auto-migrador SQL (V040+) ─────────────────────────────────────
                try:
                    from app.db_migrator import run_pending_migrations
                    run_pending_migrations()
                except Exception as exc:  # noqa: BLE001
                    logger.error("[bootstrap] auto-migrator crashed: %s", exc)

                ensure_lead_recontacto_webhook_event()
                ensure_campaign_supervisor_assignments_schema()
                ensure_oportunidad_futura_schema()
                ensure_proxima_gestion_notificada_schema()
                ensure_lead_historial_schema()
            finally:
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT pg_advisory_unlock(%s)", (STARTUP_BOOTSTRAP_LOCK_ID,))
                        cur.fetchone()
                    conn.commit()
                except Exception:
                    pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("[bootstrap] run_startup_bootstrap error: %s", exc)
