# KnowNet Scripts

Keep this directory small. A new script should have a stable operator workflow,
be referenced from this file, and avoid direct SQLite mutation unless a phase
explicitly approves it.

## Daily Local Work

| Script | Purpose |
| --- | --- |
| `dev.ps1` | Starts the local API and web development stack. |
| `ops_check.ps1` | Shows local API/web ports, PID files, and health summary. |
| `test_fast.ps1` | Runs the fast API pytest loop with last-failed selection. |
| `clean_generated.ps1` | Removes local caches and generated artifacts. |

## Release And Verification

| Script | Purpose |
| --- | --- |
| `release_check.ps1` | Runs release-level Rust, API, MCP, SDK, slow, smoke, audit, build, health, and evidence checks. |
| `provider_api_smoke.py` | Checks provider API request shape and optional live connectivity without touching KnowNet data. |
| `promote_db_v2.ps1` | Builds a verified v2 SQLite candidate, runs targeted v2 tests, and only replaces `data/knownet.db` when `-Apply` is explicit. |

## External AI And MCP Helpers

| Script | Purpose |
| --- | --- |
| `knownet_mcp_post_client.py` | Small JSON-RPC POST helper for MCP HTTP bridge checks. |
| `knownet_review_pack.py` | Builds copy-paste review packs for external AI providers that cannot directly use MCP. |

## SARIF Helpers

| Script | Purpose |
| --- | --- |
| `export_sarif.ps1` | Exports accepted/operator-verified findings to SARIF. |
| `upload_sarif_to_github.ps1` | Explicitly uploads a SARIF file through GitHub CLI. |

## Shared Helpers

| Script | Purpose |
| --- | --- |
| `local_paths.ps1` | Shared path and Python defaults for PowerShell scripts. |

## Do Not Add

- Provider-specific review pack scripts when `knownet_review_pack.py` can take a profile option.
- Cloudflare/tunnel scripts unless an active deployment path needs them again.
- Direct database mutation scripts for normal operations.
- One-off migration scripts without a phase document and a removal plan.
