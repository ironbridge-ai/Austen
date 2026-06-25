# Deploying Austen

Austen ships two things; **only the feedback server is deployed here.**

| Component             | What it is                                                            | Where it runs |
|-----------------------|------------------------------------------------------------------------|---------------|
| `austen.py`           | Weekly digest **generator** — fetches AI news, calls Claude, writes the HTML editions, publishes them to **GitHub Pages** (`ironbridge-ai.github.io/Austen`). | Run by a human, on demand. Needs `ANTHROPIC_API_KEY`. Not containerised. |
| `feedback_server.py`  | The **service** — feedback/search/trending API + a daily feedback-summary email. Embedded widget in the published editions POSTs here. | Deployed to `https://ramsac-austen.ironbridge.tech` via ai-guild-infra. |

This deploy follows the [ai-guild-infra app contract](https://github.com/ironbridge-ai/ai-guild-infra/blob/main/ops/app-repo.md):
`Containerfile` + `deploy/austen.container` (Quadlet) + `deploy/ironbridge.yaml`
(manifest) + the two CI workflows. The repo must be listed in
`ai-guild-infra/deployment/config/repos.yaml`.

## Fail-fast by design

The service **refuses to start** if its required secrets are absent — it does
not silently degrade:

- `feedback_server.py` exits non-zero if `smtp_user` / `smtp_password` aren't set.
- `container-entrypoint.sh` exits non-zero if `AZ_STORAGE_*` aren't set, or if
  the initial Azure Blob pull fails.

A failed start fails the deploy health gate and pings Slack — the intended
signal. **Provision all secrets before/with the first deploy.**

## Secrets (add to ai-guild-infra `deployment/secrets.enc.yaml`, `production` tier)

```yaml
austen_smtp_user:           { tier: production, value: <m365-sender@ironbridgesg.com> }
austen_smtp_password:       { tier: production, value: <m365 app password> }
austen_az_storage_account:  { tier: production, value: <storage account name> }
austen_az_storage_key:      { tier: production, value: <storage account key1> }
austen_az_storage_container:{ tier: production, value: data }
```

`smtp_*` mount as files at `/run/secrets/`; `az_storage_*` mount as env vars
(rclone reads them). All are `austen_*`-namespaced per the validator.

## Non-secret config

Lives in the Quadlet (`Environment=`): `PORT=4097`, `HOST=0.0.0.0`,
`AUSTEN_WEB_ROOT=/apps/storage/public`, `AUSTEN_DATA_DIR=/apps/storage/data`,
`SMTP_SERVER=smtp.office365.com`, `DIGEST_SEND_TIME=17:00`,
`AUSTEN_FEEDBACK_RECIPIENT=renato.velasquez@ironbridgesg.com`.

## Persistence

`feedback_log.json` + `search_log.json` live on `/apps/storage` (bind-mounted
`%h/storage/austen`), synced to Azure Blob by the entrypoint: pull on boot,
delta push every 60s, final push on SIGTERM. Provision the bucket + seed it
once with `deploy/seed-azure.sh <account>` before the first deploy.

## Egress caveat (daily email)

Outbound is default-deny via tinyproxy. `storage_azure` (rclone HTTPS) is
allowed and works. `office365_smtp` is declared, but SMTP/:587 is STARTTLS,
not HTTP — tinyproxy may not tunnel it. If the daily email can't connect,
either add a direct VM firewall allowance for `smtp.office365.com:587` or move
email to Microsoft Graph over HTTPS. Feedback collection is unaffected.

## Local dev

```bash
cp deploy/.env.example .env && set -a && . ./.env && set +a
python3 feedback_server.py          # serves the repo dir, logs to the repo dir
```
