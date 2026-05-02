# Architecture Hardening Log

This log tracks quality work that improves the current implementation without adding new product features.

## Why This Exists

KnowNet should become more complete by reducing ambiguity, hidden coupling, and maintenance cost. Records like this help future implementation work continue from the same judgment instead of rediscovering why a boundary exists.

## Active Architecture Debts

| Area | Current state | Desired direction | Status |
|---|---|---|---|
| FastAPI direct writes | Maintenance orchestration still writes operational lock/run/snapshot state directly, but page creation, suggestion rejection, and citation verification status now delegate canonical mutations to Rust. | Keep remaining FastAPI writes scoped to orchestration and audit-style operational state. | Accepted |
| Web page size | `apps/web/app/page.tsx` still owns workflow state, but Operations and Graph panels are now components. | Extract stable panels/components gradually without changing behavior. | Improved |
| Rust daemon handler size | `apps/core/src/daemon.rs` still contains a large command handler, but page, suggestion, citation, and graph commands now route through `apps/core/src/commands/`. | Move only high-risk repeated command groups when touched; avoid splitting tiny one-off commands just to create files. | Improved |
| Operations docs | Runbook exists but should keep matching actual health, restore, import, and release behavior. | Update docs alongside each hardening change. | Ongoing |

## Completed In This Pass

1. Extracted the Operations panel from `apps/web/app/page.tsx` into `apps/web/components/OperationsPanel.tsx`.
2. Kept the UI behavior unchanged while reducing the main page component size.
3. Moved suggestion rejection status mutation from FastAPI direct SQLite write to Rust daemon command `reject_suggestion`.
4. Moved page creation from FastAPI direct Markdown/SQLite writes to Rust daemon command `create_page`.
5. Extracted the Graph panel into `apps/web/components/GraphPanel.tsx`.
6. Added Rust command domain modules under `apps/core/src/commands/` for new page and suggestion commands.
7. Verified that API tests need the rebuilt Rust binary; if `knownet-core.exe` is running, stop it before `cargo build`.
8. Removed third-party note-app import/export compatibility so KnowNet keeps a single native page and snapshot model.
9. Moved citation validation status updates to Rust daemon command `update_citation_validation_status`.
10. Moved graph rebuild/layout cache command routing out of the large daemon match arm and added shared command response/parameter helpers.

## Near-Term Work Queue

1. Continue moving only large repeated Rust daemon command groups into `commands/` domain modules when those commands are touched.
2. Keep direct-write inventory updates in this log or the active phase task file.
