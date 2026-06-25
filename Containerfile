# Austen feedback/analytics server image.
#
# The deployed service is feedback_server.py (Python stdlib only — no pip
# deps). rclone is installed for the /apps/storage <-> Azure Blob sync the
# entrypoint runs; ca-certificates so HTTPS (Azure Blob, SMTP STARTTLS)
# validates. austen.py (the human-run weekly digest generator) is copied in
# too so the image is a complete Austen runtime, but it is NOT started here.
#
# Built + pushed to ghcr.io/ironbridge-ai/austen by
# .github/workflows/build-and-push.yml on every merge to main.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends rclone ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Service + generator code and the generator's committed state.
COPY feedback_server.py austen.py personality.md ./
COPY knowledge_log.json stories_log.json ./

# Entrypoint + image-baked seed for the public web root (first-deploy only).
COPY deploy/container-entrypoint.sh /usr/local/bin/austen-entrypoint
COPY deploy/seed/ /apps/_seed/
RUN chmod +x /usr/local/bin/austen-entrypoint

# Defaults; the Quadlet overrides PORT/HOST/paths explicitly in production.
# PYTHONUNBUFFERED so stdout/stderr stream to podman -> Loki without buffering.
ENV PYTHONUNBUFFERED=1 \
    PORT=4097 \
    HOST=0.0.0.0 \
    AUSTEN_WEB_ROOT=/apps/storage/public \
    AUSTEN_DATA_DIR=/apps/storage/data

EXPOSE 4097

# Bash entrypoint is PID 1 so its SIGTERM trap (final Azure push + graceful
# server stop) runs on `podman stop`.
ENTRYPOINT ["/usr/local/bin/austen-entrypoint"]
