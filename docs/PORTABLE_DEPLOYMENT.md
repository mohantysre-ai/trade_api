# SIGQ portable Docker deployment

This procedure moves the complete runtime to another machine:

- Market API, AI News, frontend, and Cloudflare Tunnel containers
- Angel/LLM environment secrets
- Cloudflare named-tunnel credential
- Intraday, swing, Index Options paper books and OI/candle baselines
- Market snapshots, EOD data, alerts and archives

Secrets are never committed to Git or baked into application images.

## Prerequisites on the destination

- Docker Engine 24+ with Compose v2, or current Docker Desktop
- Git
- Access to pull `smohanty010620/iros-market-api`, `iros-frontend`, and `cloudflared`
- Outbound HTTPS/WebSocket connectivity for Angel One and Cloudflare

Only one machine should run the `iros-desk` tunnel and live desk state at a time. Stop the source deployment before activating the destination to prevent competing tunnel connectors and divergent paper books.

## Windows migration

Default flow — `push-docker-hub.bat` / `start-from-hub.bat` — no manual file copy:

On the source machine:

```
push-docker-hub.bat
```

This builds and pushes the app images plus a private runtime image,
`smohanty010620/sigq-runtime-private`, containing `backend/.env`, the Cloudflare
tunnel credential, and a snapshot of the `sigq_iros-*` volumes. That Hub repo must
be created as **Private** on hub.docker.com before the first push — Hub creates a
repo as Public by default on first push otherwise, which would expose the secrets.

On the destination:

```
git clone https://github.com/mohantysre-ai/trade_api.git
cd trade_api
start-from-hub.bat
```

`start-from-hub.bat` detects a missing `backend\.env`, pulls
`sigq-runtime-private`, restores the secrets and volumes from it, then starts the
stack — `docker login` to an account with pull access to that private repo is the
only prerequisite. Run `restore-runtime-private.bat` directly to force a resync
from Hub on a machine that already has `backend\.env`.

Manual, encrypted-file alternative (no Docker Hub involved) — useful for an
air-gapped transfer or if you'd rather not put secrets in any registry:

```powershell
cd D:\trade_api
.\scripts\export-runtime-bundle.ps1
```

The generated ZIP contains live secrets. Transfer it through an encrypted channel
and delete it after import.

On the destination:

```powershell
git clone https://github.com/mohantysre-ai/trade_api.git
cd trade_api
.\scripts\import-runtime-bundle.ps1 C:\secure\sigq-runtime-YYYYMMDD-HHMMSS.zip
.\scripts\deploy-portable.ps1 -Mode Build
```

`deploy-portable.bat` is the one-click equivalent of the final command.

## Linux/macOS migration

For an encrypted bundle on the source:

```bash
cd trade_api
export SIGQ_BUNDLE_PASSWORD='use-a-long-transfer-password'
./scripts/export-runtime-bundle.sh
```

On the destination:

```bash
git clone https://github.com/mohantysre-ai/trade_api.git
cd trade_api
export SIGQ_BUNDLE_PASSWORD='same-password'
./scripts/import-runtime-bundle.sh /secure/sigq-runtime-YYYYMMDD-HHMMSS.tar.gz.enc
./scripts/deploy-portable.sh --build
```

Use `--pull` only after the matching images have been published to Docker Hub.

## Cloudflare behavior

The bundle restores `config/cloudflare/credentials.json` for the existing `iros-desk` named tunnel. Cloudflare hostname/DNS routing remains in the Cloudflare account; it does not need to be recreated on the new host. Compose mounts:

- `config.docker.yml` → `/etc/cloudflared/config.yml`
- `credentials.json` → `/etc/cloudflared/credentials.json`

Ingress routes `sigq.in` to `frontend:3000` on the Compose network. The optional `calendar`, `job`, and `mantra` routes reach host services through `host.docker.internal`, including on Linux via `host-gateway`.

## Persistent volumes

The fixed Compose project name is `sigq`, producing the same volumes on every host:

| Volume | Content |
|---|---|
| `sigq_iros-desk-state` | Live sessions, paper books, Index Options candles/OI, snapshots and alerts |
| `sigq_iros-backend-data` | EOD and backend data |
| `sigq_iros-eod-archive` | Historical EOD archive |

The import scripts restore volumes before starting application writers.

## Verification

```bash
docker compose --profile tunnel ps
docker compose logs --tail=100 market-api ai-news frontend cloudflared
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8001/health
curl -I http://127.0.0.1:3000/
curl -I https://sigq.in/
```

Expected running containers:

- `iros-market-api`
- `iros-ai-news`
- `iros-frontend`
- `iros-cloudflared`

## Rollback

Do not delete the source volumes until the destination is healthy. To revert, stop the destination, then restart the source:

```bash
docker compose --profile tunnel down
# On the source machine:
docker compose --profile tunnel up -d --wait
```
