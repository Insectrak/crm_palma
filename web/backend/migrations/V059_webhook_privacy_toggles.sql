-- ╔════════════════════════════════════════════════════════════════════════╗
-- ║ V059 — Toggles de privacidad para outbound webhooks                   ║
-- ║                                                                        ║
-- ║ V058 envia el payload completo del lead + asesor + supervisor con     ║
-- ║ todos sus datos (nombre, email, telefono). Para el caso Wedo (IA      ║
-- ║ que entrega lead a vendedor humano) eso es deseable. Pero algunos     ║
-- ║ proveedores solo necesitan saber QUIEN es el vendedor (id+nombre)     ║
-- ║ sin acceder a su contacto privado.                                    ║
-- ║                                                                        ║
-- ║ Tres toggles para control granular por api_client:                    ║
-- ║   1. webhook_include_asesor_contact      (DEFAULT TRUE)               ║
-- ║      - TRUE  : payload.asesor incluye email + telefono                ║
-- ║      - FALSE : payload.asesor solo incluye id + nombre               ║
-- ║                                                                        ║
-- ║   2. webhook_include_supervisor          (DEFAULT TRUE)               ║
-- ║      - TRUE  : payload incluye objeto supervisor                      ║
-- ║      - FALSE : payload omite supervisor por completo                  ║
-- ║                                                                        ║
-- ║   3. webhook_include_supervisor_contact  (DEFAULT FALSE)              ║
-- ║      - TRUE  : payload.supervisor incluye email + telefono            ║
-- ║      - FALSE : payload.supervisor solo incluye id + nombre            ║
-- ║                                                                        ║
-- ║ Defaults conservadores: el asesor se manda completo (lo necesita el   ║
-- ║ proveedor IA), el supervisor solo nombre (no es el target del         ║
-- ║ proveedor, no necesita acceso directo).                               ║
-- ╚════════════════════════════════════════════════════════════════════════╝

BEGIN;

ALTER TABLE crm.api_clients
    ADD COLUMN IF NOT EXISTS webhook_include_asesor_contact     BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS webhook_include_supervisor         BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS webhook_include_supervisor_contact BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN crm.api_clients.webhook_include_asesor_contact IS
    'V059: Si TRUE, el payload de webhook incluye email + telefono del asesor. Si FALSE, solo id + nombre.';
COMMENT ON COLUMN crm.api_clients.webhook_include_supervisor IS
    'V059: Si TRUE, el payload incluye objeto supervisor. Si FALSE, omitido.';
COMMENT ON COLUMN crm.api_clients.webhook_include_supervisor_contact IS
    'V059: Si TRUE, payload.supervisor incluye email + telefono. Solo aplica si webhook_include_supervisor=TRUE.';

COMMIT;
