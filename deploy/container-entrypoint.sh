#!/bin/bash
# Austen container entrypoint.
#
#   1. REQUIRE Azure Blob creds — abort if any is missing (fail-fast: the app
#      must not run with a non-replicated, silently-degraded workspace).
#   2. Pull the durable workspace from Azure Blob into /apps/storage.
#   3. Seed the public web root from image-baked defaults (missing entries only).
#   4. Background push loop (delta sync) + a final push on SIGTERM.
#   5. Launch feedback_server.py (which itself exits if SMTP creds are absent).
#
# Bash is PID 1 so the SIGTERM trap fires on `podman stop`.
set -euo pipefail

: "${AUSTEN_WEB_ROOT:=/apps/storage/public}"
: "${AUSTEN_DATA_DIR:=/apps/storage/data}"
: "${AUSTEN_AZ_SYNC_INTERVAL:=60}"
export AUSTEN_WEB_ROOT AUSTEN_DATA_DIR

mkdir -p /apps/storage "$AUSTEN_WEB_ROOT" "$AUSTEN_DATA_DIR"

# --- Azure Blob (REQUIRED) -------------------------------------------------
if [[ -z "${AZ_STORAGE_ACCOUNT:-}" || -z "${AZ_STORAGE_KEY:-}" || -z "${AZ_STORAGE_CONTAINER:-}" ]]; then
    echo "[entrypoint] FATAL: AZ_STORAGE_ACCOUNT / AZ_STORAGE_KEY / AZ_STORAGE_CONTAINER must all be set." >&2
    echo "[entrypoint]        Add austen_az_storage_{account,key,container} to" >&2
    echo "[entrypoint]        ai-guild-infra deployment/secrets.enc.yaml (production tier)." >&2
    exit 1
fi

mkdir -p /root/.config/rclone
cat > /root/.config/rclone/rclone.conf <<EOF
[az]
type = azureblob
account = ${AZ_STORAGE_ACCOUNT}
key = ${AZ_STORAGE_KEY}
EOF
chmod 600 /root/.config/rclone/rclone.conf

echo "[entrypoint] pulling workspace from az:${AZ_STORAGE_CONTAINER} -> /apps/storage ..."
if ! rclone copy "az:${AZ_STORAGE_CONTAINER}" /apps/storage --create-empty-src-dirs --quiet; then
    echo "[entrypoint] FATAL: Azure Blob pull failed — bad creds, the container does not" >&2
    echo "[entrypoint]        exist, or egress isn't allowing storage_azure. Aborting." >&2
    exit 1
fi
echo "[entrypoint] pull complete"

# Image-baked seed fills only entries the bucket didn't supply (no-clobber):
# the bucket is authoritative once the app is live.
if [[ -d /apps/_seed ]]; then
    echo "[entrypoint] seeding /apps/storage from /apps/_seed (missing entries only)"
    cp -an /apps/_seed/. /apps/storage/ 2>/dev/null || true
fi
mkdir -p "$AUSTEN_WEB_ROOT" "$AUSTEN_DATA_DIR"

# --- background sync -------------------------------------------------------
# `rclone sync` is one-way local->remote and deletes remote-only blobs, so
# on-disk deletions replicate. Recover deletions via the storage account's
# blob soft-delete + versioning (enable at account creation).
AZ_SYNC_PID=
(
    while true; do
        sleep "${AUSTEN_AZ_SYNC_INTERVAL}"
        rclone sync /apps/storage "az:${AZ_STORAGE_CONTAINER}" --quiet \
            || echo "[entrypoint] WARN Azure sync push failed (will retry)" >&2
    done
) &
AZ_SYNC_PID=$!
echo "[entrypoint] Azure background sync every ${AUSTEN_AZ_SYNC_INTERVAL}s (pid=${AZ_SYNC_PID})"

SERVER_PID=
shutdown() {
    echo "[entrypoint] SIGTERM — stopping sync, final Azure push, then stopping server" >&2
    [[ -n "$AZ_SYNC_PID" ]] && kill "$AZ_SYNC_PID" 2>/dev/null || true
    rclone sync /apps/storage "az:${AZ_STORAGE_CONTAINER}" --quiet \
        || echo "[entrypoint] WARN final Azure push failed" >&2
    [[ -n "$SERVER_PID" ]] && kill -TERM "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
    exit 0
}
trap shutdown TERM INT

echo "[entrypoint] starting feedback_server.py on ${HOST:-0.0.0.0}:${PORT:-4097}"
python3 /app/feedback_server.py &
SERVER_PID=$!
# `wait` returns when the server exits OR when a trapped signal interrupts it.
wait "$SERVER_PID"
