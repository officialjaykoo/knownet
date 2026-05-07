# Phase 30 Tasks: Rust Core Source Structure

Status: completed
Created: 2026-05-07
Updated: 2026-05-07

Implementation status: completed in the codebase.

Implemented surface:

- `storage/phase3.rs` was removed and split into domain modules:
  `storage/access.rs`, `storage/submissions.rs`, and page lifecycle functions in
  `storage/pages.rs`.
- `storage/phase4.rs` was renamed to `storage/citation_audits.rs`.
- `ensure_phase4_schema` was renamed to `ensure_citation_audit_schema`; Python
  startup now calls the new daemon command.
- Legacy access/session/vault/submission/citation/page lifecycle daemon handlers
  now live under `commands/*`.
- `daemon.rs` no longer directly handles those historical phase-era commands.
- Minimal `i64_param` and `opt_i64_param` command helpers were added.
- Existing `graph.rs` and `collaboration.rs` storage files were intentionally
  kept intact for this phase.
- Python API cleanup was added after the Rust pass:
  `routes/collaboration_sarif.py` now owns the SARIF export endpoint,
  `routes/collaboration.py` no longer carries SARIF export filtering/query
  logic, and the unused empty `knownet_api/models` package was removed.
- The Python agent SDK was moved to the standard `src` layout:
  `packages/knownet-agent-py/src/knownet_agent`. SDK packaging, tests, release
  checks, and active docs now point at the new layout.
- The root-level `seeds/` directory was removed. The KnowNet AI state seed now
  lives with its API owner at `apps/api/knownet_api/seeds/knownet-ai-state.yml`,
  and maintenance seed dry-run defaults to that path.
- The MCP app was moved to the standard Python `src` layout:
  `apps/mcp/src/knownet_mcp`. MCP configs, active docs, release checks, and
  smoke-test defaults now point at the new location.
- The root `scripts/` directory was pruned and documented. Obsolete direct DB
  sync and unused Cloudflare quick-tunnel scripts were removed, active docs were
  updated, and `scripts/README.md` now defines what belongs there.

Verification:

- `cd apps/core; $env:CARGO_TARGET_DIR='C:\knownet\.local\cargo-target'; cargo clippy -- -D warnings`
- `cd apps/core; $env:CARGO_TARGET_DIR='C:\knownet\.local\cargo-target'; cargo build`
- `cd apps/core; $env:CARGO_TARGET_DIR='C:\knownet\.local\cargo-target'; cargo test`
- `cd apps/api; python -m pytest tests\test_phase3_auth.py tests\test_phase4_citations.py tests\test_citation_verifier.py tests\test_phase7_collaboration.py tests\test_phase27_sarif.py tests\test_phase28_sarif_location.py -q`
- `cd apps/api; python -m pytest -q`
- Python API structure pass:
  `cd apps/api; python -m pytest tests\test_phase7_collaboration.py tests\test_phase27_sarif.py tests\test_phase28_sarif_location.py -q`
  and `cd apps/api; python -m pytest -q`
- SDK source layout pass:
  `cd packages/knownet-agent-py; python -m pytest -q`
  and
  `$env:PYTHONPATH='C:\knownet\packages\knownet-agent-py\src'; python -m pytest packages\knownet-agent-py\tests -q`
- Seed manifest move:
  `cd apps/api; python -m pytest tests\test_integration.py -q`
- MCP source layout pass:
  `cd apps/mcp; python -m pytest -q`,
  `$env:PYTHONPATH='C:\knownet\apps\mcp\src'; python -m pytest apps\mcp\tests\test_knownet_mcp.py -q`,
  and
  `$env:PYTHONPATH='C:\knownet\apps\mcp\src'; python apps\mcp\scripts\validate_client_profiles.py`
- Scripts cleanup:
  `cd apps/api; python -m pytest tests\test_operator_routes.py -q`,
  `$env:PYTHONPATH='C:\knownet\apps\mcp\src'; python apps\mcp\scripts\validate_client_profiles.py`,
  and
  `$env:PYTHONPATH='C:\knownet\apps\mcp\src'; python -m pytest apps\mcp\tests\test_knownet_mcp.py -q`

Phase 30 is a Rust core source-structure cleanup phase.

It does not change KnowNet behavior. It makes the Rust daemon and storage code
match what the project actually does today.

The trigger is simple: `apps/core/src/storage/phase3.rs` and
`apps/core/src/storage/phase4.rs` are still live production code, but their names
describe historical phase numbers instead of operational domains.

## Current Assessment

Current Rust core source structure score:

```txt
68 / 100
```

Good:

```txt
commands/ and storage/ are separated.
main.rs is tiny.
protocol.rs and error.rs are small.
most storage files are domain-shaped: pages, graph, jobs, messages, suggestions.
```

Weak:

```txt
daemon.rs is too large and handles many command domains directly.
storage/phase3.rs is operational code with a historical name.
storage/phase4.rs is operational code with a historical name.
some daemon command handlers should live in commands/* like newer handlers do.
storage/mod.rs re-exports phase names, which keeps the old mental model alive.
```

Primary cleanup target:

```txt
apps/core/src/storage/phase3.rs
apps/core/src/storage/phase4.rs
apps/core/src/daemon.rs
apps/api/knownet_api/routes/collaboration.py
apps/api/knownet_api/models/
packages/knownet-agent-py/
seeds/
apps/mcp/
scripts/
```

## Fixed Rules

Do not:

- Change API behavior.
- Change DB schema.
- Rename public daemon commands without a deliberate endpoint audit.
- Add compatibility aliases just to preserve old phase wording.
- Split every file merely because it is large.
- Create `utils.rs` dumping grounds.
- Move logic into Python just to avoid Rust cleanup.

Do:

- Rename historical phase modules to domain names.
- Move command dispatch out of `daemon.rs` when a `commands/*` module already
  fits the domain.
- Keep storage functions close to their owning table/domain.
- Prefer small, obvious module names over elaborate architecture.
- Run Rust build/tests and targeted API tests after each cleanup.

## P30-001 Storage Module Rename Plan

Problem:

`phase3.rs` and `phase4.rs` are live storage modules. Their names imply
temporary phase code, not permanent domain ownership.

Current responsibilities:

```txt
phase3.rs:
  users
  sessions
  vaults
  vault_members
  submissions
  tombstone_page
  recover_page

phase4.rs:
  citation_audits
  citation_evidence_snapshots
  citation_audit_events
  citation validation status
  citation audit rebuild
```

Recommended rename:

```txt
storage/phase3.rs -> storage/access.rs
storage/phase4.rs -> storage/citation_audits.rs
```

Safe execution order:

```txt
1. Create the new files.
2. Copy the old contents into the new domain files.
3. Temporarily expose both old and new module names if needed.
4. Change call sites in one small pass.
5. Delete old phase files.
6. Remove temporary aliases.
7. Run cargo build before continuing.
```

Rules:

- File/module names should change.
- Function behavior should not change.
- Public function names can be improved only when all call sites are updated in
  the same change.
- `tombstone_page` and `recover_page` need a domain decision before moving:
  if they are page lifecycle operations with no access/session coupling, they
  belong in `storage/pages.rs`, not `storage/access.rs`.

Done when:

- No `storage::phase3` or `storage::phase4` module names remain.
- `storage/mod.rs` exports domain names.
- Rust build passes.

## P30-002 Citation Schema Naming

Problem:

`ensure_phase4_schema` still exposes phase-era language even though it creates
citation audit tables.

Implementation shape:

Rename:

```txt
ensure_phase4_schema -> ensure_citation_audit_schema
daemon cmd "ensure_phase4_schema" -> "ensure_citation_audit_schema"
```

Rules:

- Because KnowNet is still early, do not preserve the old daemon command unless
  a real caller requires it.
- Search Python call sites before renaming.
- Update any tests or scripts that use the old command.
- Treat daemon command strings as an IPC contract. Python and Rust call sites
  must change in the same commit if the command string changes.

Done when:

- No `ensure_phase4_schema` symbol remains.
- Citation routes/services still rebuild and update audits.
- Rust build and targeted citation tests pass.

## P30-003 Move Legacy Daemon Handlers Into Commands Modules

Problem:

Newer command domains use `commands/*`, but `daemon.rs` still directly handles
older access/vault/submission/citation commands. That makes `daemon.rs` a large
mixed dispatcher.

Implementation shape:

Move these command handlers into domain modules:

```txt
commands/access.rs:
  create_user
  create_session
  revoke_session
  create_vault
  assign_vault_member

commands/submissions.rs or commands/messages.rs:
  create_submission
  update_submission_status

commands/citations.rs:
  ensure_citation_audit_schema
  rebuild_citation_audits_for_page
  update_citation_audit_status
  update_citation_validation_status
```

Move order:

```txt
1. Move citation handlers first, then run Rust build and citation/API tests.
2. Move access/vault/session handlers, then run Rust build and auth/access tests.
3. Move submission handlers, then run Rust build and collaboration/message tests.
```

Keep `daemon.rs` responsible for:

```txt
stdin/stdout loop
JSON request decoding
ping
init_db
calling commands::handle_request
unknown command failure
```

Done when:

- `daemon.rs` is mostly transport and top-level boot commands.
- Domain command parsing lives in `commands/*`.
- No command behavior changes.
- Error response shape is unchanged. Moving handlers must not become an error
  model refactor.

## P30-004 Command Parameter Helpers

Problem:

Command handlers repeat parameter extraction:

```rust
request.params.get("sqlite_path").and_then(|value| value.as_str()).unwrap_or(...)
```

Existing helpers cover strings, bool, f64. Phase 28 added ad hoc `as_i64`.

Implementation shape:

Add only the helpers actually needed:

```rust
i64_param
opt_i64_param
json_string_param if repeated enough
```

Rules:

- Do not add a macro framework.
- Do not introduce a command schema system yet.
- Do not rewrite all handlers if a small helper is enough.
- Helper error types must match the existing command response flow. Do not make
  helpers return a new incompatible error model.

Done when:

- New command code avoids repeated manual `as_i64`.
- Existing handlers remain readable.

## P30-005 Storage Boundary Review

Problem:

Some storage files are domain-shaped, but `graph.rs` and `collaboration.rs` are
large. They may or may not need splitting.

Implementation shape:

Document a lightweight decision:

```txt
storage/graph.rs:
  keep for now / split layout cache / split rebuild logic

storage/collaboration.rs:
  keep for now / split findings / split packets / split tasks
```

Expected Phase 30 default:

```txt
storage/graph.rs: keep for now unless a tiny, obvious extraction appears.
storage/collaboration.rs: keep for now unless a tiny, obvious extraction appears.
```

Phase 30 decision:

```txt
storage/graph.rs: kept intact.
  Reason: graph rebuild, audit edges, layout cache, and cleanup still share
  transaction-heavy helper paths. Splitting now would be a behavior-risking
  refactor, not a naming cleanup.

storage/collaboration.rs: kept intact.
  Reason: finding creation, implementation evidence, context bundle records, and
  task status updates still share review/finding lifecycle assumptions. Split
  after DB v2 clarifies collaboration entity boundaries.
```

Rules:

- Do not split `graph.rs` or `collaboration.rs` in Phase 30 unless a narrow
  boundary is obvious.
- Prefer a later phase if splitting would require deep behavior tests.
- Record the decision in this phase document so the same split/no-split debate
  does not restart in the next phase.

Done when:

- Phase 30 records whether each large storage file stays or becomes a later
  cleanup candidate.

## P30-006 Verification

Run:

```powershell
cd apps\core
$env:CARGO_TARGET_DIR='C:\knownet\.local\cargo-target'
cargo clippy
cargo build
cargo test

cd ..\api
python -m pytest tests\test_phase7_collaboration.py tests\test_phase27_sarif.py tests\test_phase28_sarif_location.py -q
```

If command movement touches citations, also run citation-focused tests.

Done when:

- Each moved domain is verified before moving the next domain.
- Rust build passes.
- Rust tests pass.
- Targeted API tests pass.
- No old phase module names remain unless documented as intentionally deferred.

## P30-007 Python API Source Structure Pass

Problem:

The Rust core source names are now domain-shaped, but Python still has two
small source-structure issues that belong in the same cleanup phase:

```txt
routes/collaboration.py is too broad and contains SARIF export code.
knownet_api/models/ is an empty package with no live purpose.
```

Implementation shape:

```txt
routes/collaboration_sarif.py:
  findings.sarif export endpoint
  SARIF export filter parsing

routes/collaboration.py:
  collaboration reviews, findings, packets, tasks, and context bundle flows

knownet_api/models/:
  remove if no imports exist
```

Rules:

- Do not split the whole collaboration router in this phase.
- Do not change endpoint paths, query parameters, auth dependencies, or response
  shape.
- Register static SARIF routes before dynamic finding routes so
  `/findings.sarif` is not captured as `/findings/{finding_id}`.
- Do not introduce a Python model layer until DB v2 defines real model
  boundaries.
- Keep Next/web source restructuring out of Phase 30; web should follow DB/API
  contract changes later.

Done when:

- `/api/collaboration/findings.sarif` still works through the same path.
- `collaboration.py` no longer imports SARIF export services directly.
- No imports reference `knownet_api.models`.
- The empty models package is removed.
- Targeted SARIF and collaboration tests pass.

## Acceptance

```txt
1. Historical storage module names are replaced with domain names.
2. Citation schema command/function no longer uses phase-era naming.
3. daemon.rs is reduced toward transport/boot responsibilities.
4. Domain command handlers live under commands/*.
5. No DB schema or API behavior changes are introduced.
6. Large storage files are reviewed without reflexively splitting them.
7. Tests confirm behavior is preserved.
```

## Suggested Work Order

```txt
P30-001 Storage Module Rename Plan
P30-002 Citation Schema Naming
P30-003 Move Legacy Daemon Handlers Into Commands Modules
P30-004 Command Parameter Helpers
P30-005 Storage Boundary Review
P30-006 Verification
P30-007 Python API Source Structure Pass
```

## Out Of Scope

```txt
- DB v2 implementation
- Schema migrations
- Broad API router restructuring beyond the SARIF export extraction
- New product features
- GitHub upload automation
- Full release_check
- Next/web source restructuring
```

## P30-008 Python SDK Source Layout

Problem:

`packages/knownet-agent-py` is a standalone SDK package, which is correct.
However, the import package previously lived directly under the package root:

```txt
packages/knownet-agent-py/knownet_agent/
```

That works, but the standard Python package layout is:

```txt
packages/knownet-agent-py/
  src/
    knownet_agent/
```

Implementation shape:

```txt
Move knownet_agent/ to src/knownet_agent/.
Configure pyproject.toml for setuptools src discovery.
Configure pytest pythonpath for src.
Update release_check.ps1 to test against packages/knownet-agent-py/src.
Update generated-file cleanup paths.
Update active SDK docs; leave archived phase docs unchanged.
```

Rules:

- Keep the package name `knownet-agent`.
- Keep the import name `knownet_agent`.
- Do not move the SDK into `apps/api`; it is intentionally an external client
  package.
- Do not introduce a local virtual environment.

Done when:

- `from knownet_agent import KnowNetClient` works with
  `PYTHONPATH=packages/knownet-agent-py/src`.
- SDK tests pass from inside the package directory.
- SDK tests pass from the repository root with the explicit `src` PYTHONPATH.

## P30-009 API-Owned Seed Manifest Location

Problem:

The root-level `seeds/` directory contained a single API-owned manifest:

```txt
seeds/knownet-ai-state.yml
```

The only live runtime consumer is the API maintenance dry-run endpoint. That
made `seeds/` look like a repository-wide seed system even though ownership
belongs to the API/system pages area.

Implementation shape:

```txt
Move:
  seeds/knownet-ai-state.yml

To:
  apps/api/knownet_api/seeds/knownet-ai-state.yml

Update:
  maintenance seed dry-run default path
```

Rules:

- Keep the seed file as data, not Python code.
- Keep the maintenance endpoint path parameter so operators can still test
  alternate seed manifests inside the repository.
- Do not create a broad seed framework in Phase 30.

Done when:

- No root `seeds/` directory remains.
- `/api/maintenance/seed/dry-run` defaults to the API-owned seed path.
- Existing repository-bound seed path validation remains in place.

## P30-010 MCP Python Source Layout

Problem:

`apps/mcp` is a standalone MCP app, which is correct. Its import package
previously lived directly under the app root:

```txt
apps/mcp/knownet_mcp/
```

That worked, but the standard Python layout is:

```txt
apps/mcp/
  pyproject.toml
  src/
    knownet_mcp/
  tests/
  scripts/
  configs/
  client_profiles/
```

Implementation shape:

```txt
Move knownet_mcp/ to src/knownet_mcp/.
Add apps/mcp/pyproject.toml.
Configure pytest pythonpath for src.
Update MCP config examples and client profiles.
Update release_check.ps1 and security/path scan paths.
Update active MCP docs; leave archived phase docs unchanged.
```

Rules:

- Keep `apps/mcp` as a standalone MCP app.
- Keep the import name `knownet_mcp`.
- Do not split `server.py` during this layout pass.
- Do not create a local virtual environment.

Done when:

- `from knownet_mcp.server import KnowNetMcpServer` works with
  `PYTHONPATH=apps/mcp/src`.
- MCP tests pass from inside the MCP app directory.
- MCP tests pass from the repository root with explicit `src` PYTHONPATH.
- Client profile validation passes.

## P30-011 Scripts Directory Pruning

Problem:

Root `scripts/` was becoming a mixed toolbox. That is useful early on, but it
can turn into permanent one-off automation unless every script has a clear
owner and active workflow.

Implementation shape:

```txt
Remove obsolete scripts:
  sync_ai_state.py
  cloudflare_quick_tunnel.ps1
  stop_cloudflare_tunnel.ps1

Remove obsolete docs:
  docs/CLOUDFLARE_TUNNEL.md

Add:
  scripts/README.md
```

Rules:

- Keep daily local work scripts.
- Keep release and verification scripts.
- Keep MCP/external AI helpers that are referenced by active docs.
- Keep SARIF helpers because Phase 27/28 use them.
- Do not keep direct SQLite mutation scripts as normal operator tools.
- Do not keep Cloudflare quick-tunnel scripts unless an active deployment path
  needs them again.

Done when:

- Active docs no longer point to deleted scripts.
- Operator AI-state guidance no longer recommends the removed direct DB sync
  script.
- `scripts/README.md` documents the allowed script categories and "do not add"
  rules.
- Targeted operator and MCP tests still pass.
