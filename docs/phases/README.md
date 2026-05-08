# Current Phase Documents

This folder keeps only phase files that are still active planning or near-term implementation references.
Completed phase records live in `docs/archive/phases/` for traceability without making the active docs folder noisy.

Current operation should start from the top-level README, runbook, security plan, model-run guide, release evidence, and these current phase files.

## Active Planning Set

```txt
PHASE_29_TASKS.md - DB v2 design:
  current schema inventory, entity boundary design, reset/migration strategy,
  migration policy, and next-phase recommendation without rewriting the DB yet.

PHASE_30_TASKS.md - source structure cleanup:
  Rust core storage/command naming, Python API layout, SDK/MCP src layouts,
  seed ownership, scripts pruning, and docs reduction without changing product behavior.

PHASE_31_TASKS.md - DB v2 runtime adoption:
  reconnect API, packet, SARIF, provider-run, agent/operator, and maintenance
  paths to the clean v2 SQLite schema before promoting data/knownet-v2.db.

PHASE_32_TASKS.md - workflow-first operator UI:
  redesign the web UI around Next, Packets, Reviews, Tasks, Sources, and Ops so
  the operator sees the next AI collaboration action instead of backend module
  names.
```

## Archive Rule

Move a phase file to `docs/archive/phases/` when:

```txt
- implementation is complete, and
- its decisions are reflected in code, tests, schemas, README, runbook, or another active phase, and
- it is no longer needed as the next implementation reference.
```

Keep only the next DB/modeling phase and the current cleanup phase here.
