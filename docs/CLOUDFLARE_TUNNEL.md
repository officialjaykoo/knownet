# Cloudflare Tunnel

KnowNet's recommended external access shape is API-only:

```txt
Local operator:
  Web UI: http://127.0.0.1:3000

External AI agents:
  Cloudflare Tunnel -> http://127.0.0.1:8000
```

The web UI stays local. External agents use scoped agent tokens through the API.

## Quick Connectivity Test

This path is for connectivity testing. It does not replace a Cloudflare Access
policy for real use.

```powershell
winget install Cloudflare.cloudflared
.\scripts\dev.ps1 -ProductionWeb -KeepWebCache
.\scripts\cloudflare_quick_tunnel.ps1
```

The script runs:

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
```

Give external agents the printed `trycloudflare.com` URL as
`KNOWNET_BASE_URL`. Keep using the local web UI on `http://127.0.0.1:3000` to
create, rotate, revoke, and inspect agent tokens.

Stop a local quick tunnel:

```powershell
.\scripts\stop_cloudflare_tunnel.ps1
```

## Environment

For API-only tunnel testing, use:

```env
PUBLIC_MODE=true
ADMIN_TOKEN=<long-random-token>
ADMIN_TOKEN_MIN_CHARS=32

NEXT_PUBLIC_API_BASE=
KNOWNET_API_INTERNAL=http://127.0.0.1:8000
```

Generate a local random token in PowerShell:

```powershell
[Convert]::ToHexString((1..32 | ForEach-Object { Get-Random -Maximum 256 }))
```

`CLOUDFLARE_ACCESS_REQUIRED` should stay `false` for local direct testing. Turn
it on only after a stable Cloudflare Access application and allowed email list
are configured for the tunnel hostname:

```env
CLOUDFLARE_ACCESS_REQUIRED=true
CLOUDFLARE_ACCESS_ALLOWED_EMAILS=you@example.com
CLOUDFLARE_ACCESS_REQUIRE_JWT=true
```

When Access enforcement is enabled, requests that do not include Cloudflare
Access headers are rejected. That is correct for a protected external hostname,
but it can also block direct localhost calls if enabled too early.

## Agent Setup

Use the dashboard to create an agent token with the minimum scopes needed.

For MCP:

```env
KNOWNET_BASE_URL=https://<your-tunnel-hostname>
KNOWNET_AGENT_TOKEN=<agent-token-shown-once>
```

For the Python SDK:

```env
KNOWNET_BASE_URL=https://<your-tunnel-hostname>
KNOWNET_AGENT_TOKEN=<agent-token-shown-once>
```

Run a small `ping` or `me` check from the external client before giving it a
larger review task.

## Health Checks

`/health` and `/health/summary` report security warnings when:

- `PUBLIC_MODE=true` but `ADMIN_TOKEN` is missing or too short.
- `PUBLIC_MODE=true` but `CLOUDFLARE_ACCESS_REQUIRED=false`.
- `CLOUDFLARE_ACCESS_REQUIRED=true` but no allowed email list is configured.

The second warning is expected during a quick connectivity test. It should be
resolved before treating the tunnel as real external access.

## Do Not

- Do not expose the web UI through the tunnel for normal agent access.
- Do not run `PUBLIC_MODE=true` without a long `ADMIN_TOKEN`.
- Do not treat a quick tunnel URL as durable infrastructure.
- Do not give external agents admin tokens.
- Do not put secrets, database files, or backups in a context bundle.
