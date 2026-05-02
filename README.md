# KnowNet

AI-centered collaboration knowledge base.

KnowNet is designed around durable AI-to-AI project memory: structured findings,
implementation decisions, verification records, context manifests, and safe
context bundles. SQLite/JSON records are the canonical AI collaboration state;
Markdown is a narrative attachment for long reasoning, source review text, and
operator-facing context. See [AI-Centered Design](./docs/AI_CENTERED_DESIGN.md).

## Quick Start

Prerequisites:

- Windows PowerShell
- Python 3.10+
- Node.js 20+
- Rust toolchain with Cargo

Clone and install:

```powershell
git clone https://github.com/officialjaykoo/knownet.git
cd knownet
Copy-Item .env.example .env
```

Start the local development stack:

```powershell
.\scripts\dev.ps1
```

This builds the Rust daemon, creates `apps/api/.venv` when needed, installs API
and web dependencies, then starts:

- API: `http://127.0.0.1:8000`
- Web: `http://127.0.0.1:3000`

The script intentionally sets `LOCAL_EMBEDDING_AUTO_LOAD=false` unless you have
already set it. This keeps first startup fast; semantic embedding search can be
enabled later from `.env`.

Run release checks:

```powershell
.\scripts\release_check.ps1
```

Fast test loop while coding:

```powershell
.\scripts\test_fast.ps1
```

The fast loop runs the default API pytest selection with `--lf -q`, so it skips
slow restore/import flows and smoke tests during normal coding.
`release_check.ps1` still runs fast API tests, slow operational tests, smoke
tests, Rust tests, npm audit, and the web build before a push or release.

If Rust rebuild fails with `access denied`, stop running API/Rust processes and
run the command again. `knownet-core.exe` cannot be replaced while it is running.

Check whether the local dev servers and PID files agree:

```powershell
.\scripts\ops_check.ps1
```

Test external connectivity through Cloudflare Tunnel:

```powershell
.\scripts\dev.ps1 -ProductionWeb -KeepWebCache
.\scripts\cloudflare_quick_tunnel.ps1
```

For actual external use, enable `PUBLIC_MODE=true`, configure a long
`ADMIN_TOKEN`, and protect the tunnel with Cloudflare Access. See
[Cloudflare Tunnel](./docs/CLOUDFLARE_TUNNEL.md).

## Docker

For a repeatable local container setup:

```powershell
docker compose up --build
```

This starts the same API and web ports:

- API: `http://127.0.0.1:8000`
- Web: `http://127.0.0.1:3000`

Docker stores app data in the `knownet-data` volume. See
[Docker docs](./docs/DOCKER.md) before exposing the app outside localhost.

## Agent Tooling

Phase 10 adds agent tooling on top of scoped Phase 9 access:

- MCP server: `apps/mcp/knownet_mcp/server.py`
- Python SDK: `packages/knownet-agent-py/`
- Web Agent Access panel for token management and sanitized activity events

Use `KNOWNET_AGENT_TOKEN` from the environment for MCP and SDK examples. Do not
hard-code agent tokens in source files.

## Project Docs

Implementation task lists:

- [Phase 1 Tasks](./PHASE_1_TASKS.md)
- [Phase 2 Tasks](./PHASE_2_TASKS.md)
- [Phase 3 Tasks](./PHASE_3_TASKS.md)
- [Phase 4 Tasks](./PHASE_4_TASKS.md)
- [Phase 5 Tasks](./PHASE_5_TASKS.md)
- [Phase 6 Tasks](./PHASE_6_TASKS.md)
- [Phase 7 Tasks](./PHASE_7_TASKS.md)
- [Phase 8 Tasks](./PHASE_8_TASKS.md)
- [Phase 9 Tasks](./PHASE_9_TASKS.md)
- [Phase 10 Tasks](./PHASE_10_TASKS.md)

Operational docs:

- [Security Plan](./docs/SECURITY_PLAN.md)
- [Runbook](./docs/RUNBOOK.md)
- [Docker](./docs/DOCKER.md)
- [Cloudflare Tunnel](./docs/CLOUDFLARE_TUNNEL.md)
- [Release Checklist](./docs/RELEASE_CHECKLIST.md)
- [Architecture Hardening Log](./docs/ARCHITECTURE_HARDENING_LOG.md)

Product direction:

- [AI-Centered Design](./docs/AI_CENTERED_DESIGN.md)
- [AI Collaboration Concept](./docs/AI_COLLABORATION_CONCEPT.md)
