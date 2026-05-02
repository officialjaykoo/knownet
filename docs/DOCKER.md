# Docker

KnowNet supports a local Docker Compose setup for easier install and repeatable
testing. This is a local/self-hosted convenience path, not a hardened public
cloud deployment.

## Requirements

```txt
Docker Desktop or Docker Engine
Docker Compose v2
```

## Start

```powershell
docker compose up --build
```

Open:

```txt
Web: http://127.0.0.1:3000
API: internal container localhost only
```

Data is stored in the named Docker volume:

```txt
knownet-data:/data
```

The container sets:

```txt
DATA_DIR=/data
SQLITE_PATH=/data/knownet.db
RUST_CORE_PATH=/app/bin/knownet-core
LOCAL_EMBEDDING_AUTO_LOAD=false
LOCAL_EMBEDDING_LOCAL_FILES_ONLY=true
```

Embeddings are intentionally disabled by default so the first container startup
does not try to download or load a large local model.

## Logs

Inside the data volume:

```txt
/data/logs/api.log
/data/logs/web.log
```

From the host:

```powershell
docker compose logs -f
```

## Stop

```powershell
docker compose down
```

To delete the local Docker volume as well:

```powershell
docker compose down -v
```

Only use `-v` when you intentionally want to remove the local KnowNet data.

## Security Notes

The default compose file is for local use:

```txt
PUBLIC_MODE=false
Only the web port is bound through Docker to the host.
No HTTPS or reverse proxy is configured.
No admin token is configured by default.
```

For external access or team use, set at minimum:

```yaml
environment:
  PUBLIC_MODE: "true"
  ADMIN_TOKEN: "a-long-random-token-at-least-32-characters"
  CLOUDFLARE_ACCESS_REQUIRED: "true"
  CLOUDFLARE_ACCESS_ALLOWED_EMAILS: "you@example.com"
  NEXT_PUBLIC_API_BASE: ""
  KNOWNET_API_INTERNAL: "http://127.0.0.1:8000"
```

Also put KnowNet behind a reverse proxy or Cloudflare Tunnel with HTTPS and
restrict network access. Do not expose the API port directly.

## Backup

Use the built-in snapshot endpoint/UI before upgrades:

```txt
POST /api/maintenance/snapshots
```

Snapshots are written under `/data/backups` inside the volume.
