# Current Phase Documents

This folder keeps only the current standardization and integration phase
documents. Older completed phase records live in `docs/archive/phases/` for
traceability without making the active docs folder noisy.

Current operation should start from the top-level README, runbook, security
plan, model-run guide, release evidence, and these current phase files.

Current active planning set:

```txt
PHASE_19_TASKS.md - snapshot profiles and packet foundation
PHASE_20_TASKS.md - packet standardization
PHASE_21_TASKS.md - trace and schema validation
PHASE_22_TASKS.md - standard absorption
PHASE_23_TASKS.md - Standard MCP baseline:
  standard KnowNet MCP resource URIs, proposal-only tools, prompt names, and
  tests that keep raw/admin surfaces out.
PHASE_24_TASKS.md - lightweight SQLite FTS5 page search:
  page-level `pages_fts`, rebuild endpoint, FTS-first keyword search, and
  compact health/packet search status without adding a search server.
PHASE_25_TASKS.md - verification, ignore policy, and agent contract:
  verify FTS, centralize forbidden path/secret policy, expose
  `knownet.agent.v1`, align packet source manifests, and add snapshot integrity
  smoke checks without redesigning the DB.
PHASE_26_TASKS.md - compact external AI packet:
  default compact overview handoff, one canonical contract, no empty/null
  scaffolding, prioritized signals, opt-in detail profiles, and required context
  prompts for shorter external AI follow-up.
```
