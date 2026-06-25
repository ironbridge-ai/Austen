#!/usr/bin/env bash
# One-time bootstrap: push Austen's image-baked seed (the public landing page)
# into its Azure Blob container so the first deploy starts from known-good
# state. Run from a workstation with the Azure CLI logged in (`az login`),
# BEFORE the first reconcile.
#
# After the app is live the container's entrypoint sync is authoritative —
# re-running this would clobber feedback collected since. So: run once.
#
# Usage:
#   deploy/seed-azure.sh <storage-account> [container]
#
# `container` defaults to `data` (matches the austen_az_storage_container
# secret convention). The account + key must match austen_az_storage_account
# / austen_az_storage_key in ai-guild-infra deployment/secrets.enc.yaml.
set -euo pipefail

ACCOUNT="${1:?usage: seed-azure.sh <storage-account> [container]}"
CONTAINER="${2:-data}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEED_DIR="$HERE/seed"

if ! command -v az >/dev/null 2>&1; then
    echo "error: az CLI not found. Install the Azure CLI and 'az login' first." >&2
    exit 1
fi
if [[ ! -d "$SEED_DIR" ]]; then
    echo "error: seed dir not found at $SEED_DIR" >&2
    exit 1
fi

echo "Ensuring container '$CONTAINER' exists in account '$ACCOUNT'…"
az storage container create \
    --account-name "$ACCOUNT" \
    --name "$CONTAINER" \
    --auth-mode login >/dev/null

echo "Uploading $SEED_DIR -> az://$ACCOUNT/$CONTAINER (no overwrite)…"
az storage blob upload-batch \
    --account-name "$ACCOUNT" \
    --destination "$CONTAINER" \
    --source "$SEED_DIR" \
    --auth-mode login \
    --overwrite false

echo "Done. The container now mirrors deploy/seed/ (public/index.html)."
echo "The running app will pull this on next boot and own it from then on."
