# Cloudflare Tunnel

KnowNet can be tested from outside your local network through Cloudflare Tunnel.
The safe default is to expose only the web app on port `3000`; the API on
`8000` should stay bound to localhost and be reached through the web proxy.

## Quick Connectivity Test

This path does not require a Cloudflare account, but it is only a connectivity
test. Do not treat a quick tunnel as real access control.

```powershell
winget install Cloudflare.cloudflared
.\scripts\dev.ps1 -ProductionWeb -KeepWebCache
.\scripts\cloudflare_quick_tunnel.ps1
```

The script runs:

```powershell
cloudflared tunnel --url http://127.0.0.1:3000
```

Open the `trycloudflare.com` URL printed by `cloudflared`.

Use `-ProductionWeb` for tunnel testing. `next dev` is intentionally slower and
will compile routes and assets on demand through the tunnel.

Stop a local quick tunnel:

```powershell
.\scripts\stop_cloudflare_tunnel.ps1
```

## External Use Checklist

Before using KnowNet from outside your machine:

1. Expose the web app only: `http://127.0.0.1:3000`.
2. Keep the API local: `http://127.0.0.1:8000`.
3. Use same-origin API calls:

```env
NEXT_PUBLIC_API_BASE=
KNOWNET_API_INTERNAL=http://127.0.0.1:8000
```

4. Enable public-mode write protection:

```env
PUBLIC_MODE=true
ADMIN_TOKEN=<long-random-token>
ADMIN_TOKEN_MIN_CHARS=32
```

Generate a local random token in PowerShell:

```powershell
[Convert]::ToHexString((1..32 | ForEach-Object { Get-Random -Maximum 256 }))
```

5. Enable the Cloudflare Access origin gate:

```env
CLOUDFLARE_ACCESS_REQUIRED=true
CLOUDFLARE_ACCESS_ALLOWED_EMAILS=you@example.com
CLOUDFLARE_ACCESS_REQUIRE_JWT=true
```

6. Create a Cloudflare Access application and policy for the tunnel hostname.
   A stable Access-protected hostname normally requires a Cloudflare account,
   a named tunnel, and a domain connected to Cloudflare.

## Health Checks

`/health` and `/health/summary` report security warnings when:

- `PUBLIC_MODE=true` but `ADMIN_TOKEN` is missing or too short.
- `PUBLIC_MODE=true` but `CLOUDFLARE_ACCESS_REQUIRED=false`.
- `CLOUDFLARE_ACCESS_REQUIRED=true` but no allowed email list is configured.

## Do Not

- Do not expose port `8000` directly.
- Do not run `PUBLIC_MODE=true` without a long `ADMIN_TOKEN`.
- Do not rely on a quick tunnel alone for real external use.
- Do not put secrets, database files, or backups in a context bundle.
