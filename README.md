# KnowNet

AI-centered collaboration knowledge base.

KnowNet is designed around durable AI-to-AI project memory: structured findings,
implementation decisions, verification records, context manifests, and safe
context bundles. SQLite/JSON records are the canonical AI collaboration state;
Markdown is a narrative attachment for long reasoning, source review text, and
operator-facing context. See [AI Design](./docs/AI_DESIGN.md).

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

This builds the Rust daemon, checks global Python API dependencies, installs web
dependencies, then starts:

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

Local generated files stay ignored and disposable. Cargo build output is under
`.local/cargo-target`; Next and npm generated folders remain tool-standard
ignored directories. Python API dependencies use the workstation's global
Python interpreter, not a repo-local virtualenv. Generated folders can be removed with
`.\scripts\clean_generated.ps1`. See [Local Environment](./docs/LOCAL_ENVIRONMENT.md).

If Rust rebuild fails with `access denied`, stop running API/Rust processes and
run the command again. `knownet-core.exe` cannot be replaced while it is running.

Check whether the local dev servers and PID files agree:

```powershell
.\scripts\ops_check.ps1
```

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

MCP is the preferred integration path for MCP-capable AI tools. Phase 10 added
agent tooling on top of scoped Phase 9 access, and Phase 11 hardens MCP client
compatibility:

- MCP server: `apps/mcp/src/knownet_mcp/server.py`
- Python SDK: `packages/knownet-agent-py/`
- Web Agent Access panel for token management and sanitized activity events

Use `KNOWNET_AGENT_TOKEN` from the environment for MCP and SDK examples. Do not
hard-code agent tokens in source files.

Client setup examples live in [MCP client docs](./docs/MCP_CLIENTS.md).
Python SDK setup and workflow examples live in [SDK client docs](./docs/SDK_CLIENTS.md).

## Project Docs

Current implementation task lists:

- [Current Phase Index](./docs/phases/README.md)
Current phase docs live in [docs/phases](./docs/phases/). Completed phase
history lives in [docs/archive/phases](./docs/archive/phases/).

Operational docs:

- [Docs Index](./docs/README.md)
- [Security Plan](./docs/SECURITY_PLAN.md)
- [Runbook](./docs/RUNBOOK.md)
- [Docker](./docs/DOCKER.md)
- [Release Checklist](./docs/RELEASE_CHECKLIST.md)

Product direction:

- [AI Design](./docs/AI_DESIGN.md)

