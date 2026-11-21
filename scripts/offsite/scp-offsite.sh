#!/bin/bash
# V070.84 — Off-site backup multi-tenant via Tailscale + SSH.
#
# Corre en el HOST de Hetzner (NO en el container n8n) via cron, 30 min
# despues del workflow n8n. Encuentra el .sql.gz mas reciente generado
# por el workflow y lo copia al server del cliente.
#
# El container n8n no puede tener Tailscale (Alpine + EasyPanel no expone
# CAP_NET_ADMIN ni /dev/net/tun). Por eso el off-site va en el host.
#
# Uso:
#   1. Copiar este script al server del cliente:
#      /opt/backups/scripts/scp-offsite.sh
#   2. Copiar el ejemplo de config:
#      cp scripts/offsite/scp-offsite.conf.example /opt/backups/scp-offsite.conf
#   3. Editar /opt/backups/scp-offsite.conf con los datos del cliente.
#   4. chmod +x /opt/backups/scripts/scp-offsite.sh
#   5. Programar cron diario:
#      30 8 * * * /opt/backups/scripts/scp-offsite.sh >> /opt/backups/logs/cron.log 2>&1
#
# Exit codes:
#   0 — OK off-site enviado
#   1 — error de configuracion (config file ausente o invalido)
#   2 — no hay backup en el volumen (n8n no genero nada)
#   3 — backup demasiado chico (posible pg_dump fallido silenciosamente)
#   4 — fallo el SCP (red, auth, permisos en destino)

set -e

# ── Carga de configuracion ───────────────────────────────────────────────
CONFIG="${SCP_OFFSITE_CONFIG:-/opt/backups/scp-offsite.conf}"

if [ ! -f "$CONFIG" ]; then
  echo "[ERROR] No existe config file: $CONFIG" >&2
  echo "  Copia scripts/offsite/scp-offsite.conf.example y edita los valores." >&2
  exit 1
fi

# shellcheck source=/dev/null
. "$CONFIG"

# ── Validacion de variables obligatorias ─────────────────────────────────
REQUIRED_VARS=(TENANT_SLUG VOLUME DEST_USER DEST_HOST DEST_PATH KEY_PATH)
for var in "${REQUIRED_VARS[@]}"; do
  if [ -z "${!var}" ]; then
    echo "[ERROR] Variable obligatoria sin valor: $var (revisa $CONFIG)" >&2
    exit 1
  fi
done

# Defaults opcionales
LOG_DIR="${LOG_DIR:-/opt/backups/logs}"
MIN_SIZE_BYTES="${MIN_SIZE_BYTES:-100000}"
LOG_RETENTION_DAYS="${LOG_RETENTION_DAYS:-30}"
SSH_TIMEOUT="${SSH_TIMEOUT:-30}"

# ── Logging ──────────────────────────────────────────────────────────────
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/scp_${TENANT_SLUG}_$(date +%Y-%m-%d).log"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

log "=== Iniciando off-site SCP (tenant=$TENANT_SLUG) ==="

# ── 1. Encontrar el .sql.gz mas reciente ─────────────────────────────────
LATEST=$(ls -t "$VOLUME"/*.sql.gz 2>/dev/null | head -1 || true)

if [ -z "$LATEST" ]; then
  log "ERROR: no hay .sql.gz en $VOLUME"
  log "  Verifica que el workflow n8n haya corrido y el volumen este montado."
  exit 2
fi

SIZE=$(stat -c%s "$LATEST")
log "Backup mas reciente: $LATEST ($SIZE bytes)"

# ── 2. Validacion de tamaño minimo (anti pg_dump fallido silencioso) ─────
if [ "$SIZE" -lt "$MIN_SIZE_BYTES" ]; then
  log "ERROR: backup demasiado chico ($SIZE bytes < $MIN_SIZE_BYTES)."
  log "  Posible pg_dump fallido. Revisa logs del workflow n8n."
  exit 3
fi

# ── 3. SCP via Tailscale ─────────────────────────────────────────────────
log "Enviando a ${DEST_USER}@${DEST_HOST}:${DEST_PATH}"

if scp -i "$KEY_PATH" \
       -o StrictHostKeyChecking=no \
       -o ConnectTimeout="$SSH_TIMEOUT" \
       "$LATEST" "${DEST_USER}@${DEST_HOST}:${DEST_PATH}" >> "$LOG" 2>&1; then
  log "OK off-site enviado: $(basename "$LATEST")"
else
  rc=$?
  log "FAIL off-site SCP (exit $rc)"
  log "  Diagnostico: verifica tailscale status, ping al destino, permisos de la key."
  exit 4
fi

# ── 4. Rotar logs viejos ─────────────────────────────────────────────────
find "$LOG_DIR" -name "scp_${TENANT_SLUG}_*.log" \
     -mtime +"$LOG_RETENTION_DAYS" -delete 2>/dev/null || true

log "=== Off-site SCP terminado OK ==="
exit 0
