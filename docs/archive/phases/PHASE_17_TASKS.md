# Phase 17 Tasks: Integrated Operator Console And Completion Gate

Phase 17 turns the Phase 1-16 system into a more complete daily-use product.
The goal is not to add another disconnected integration surface. The goal is to
connect the existing pieces into one operator workflow:

```txt
Health -> context quality -> external/model review -> finding triage ->
implementation records -> verification -> release evidence.
```

Phase 17 should make KnowNet feel less like a set of powerful endpoints and
more like an integrated AI collaboration console. The operator should be able to
see what is safe, what is verified, what needs review, what was imported, and
what must happen before a release.

Implementation status: completed in the codebase on 2026-05-04.

Implemented surface as of 2026-05-04:

```txt
Done:
  - /api/operator/ai-state-quality endpoint
  - /api/operator/provider-matrix endpoint
  - /api/operator/release-readiness endpoint
  - provider verification guard that does not treat mocked runs as live_verified
  - Operator Console surface in the main web workspace
  - AI state quality, provider matrix, model runs, and release readiness UI
  - Gemini mock model run start/import workflow from the Operator Console
  - model run token/cost unavailable states in UI
  - release_check AI state quality and provider matrix checks
  - release_check durable docs/RELEASE_EVIDENCE.md output
  - safe restore-plan endpoint for browser-side snapshot/lock/manifest review
  - Operations panel restore-plan inspection for the latest snapshot
  - guarded browser restore execution with typed confirmation
  - Phase 17 API tests for quality, provider guardrails, and release readiness
  - snapshot restore acceptance run through release_check slow operational tests
  - Phase 16/security/runbook/checklist documentation drift cleanup

Partially done:
  - review/finding triage remains available through the existing Review Inbox
  - Gemini real adapter existed from Phase 16 and is now represented in provider
    status, but no paid/free live call was performed in this implementation run

Not done in this step:
  - live Gemini verification against a real API key/quota
```

## Fixed Decisions

```txt
Phase 17 is an integration and completion phase.
It should finish the operational loop created by Phases 7-16.

Do not add:
  A new collaboration data model.
  A second finding/review table family.
  A provider-specific UI for every model.
  Unreviewed AI page writes.
  Shell, raw DB, backup, or filesystem access for external agents.
  A SaaS identity system.
  A broad public deployment model.

Do add or improve:
  A unified operator console.
  Model review run UI.
  Provider verification status.
  Cost/token accounting visibility.
  Release readiness visibility.
  AI-readable state quality checks.
  Review/finding triage ergonomics.
  Snapshot/restore/verify-index confidence.
  Clear live-vs-mocked provider evidence.
  Documentation and checklist drift checks.
```

Phase 17 should preserve the AI-centered design rule:

```txt
SQLite/JSON records are canonical collaboration state.
Markdown is narrative attachment and operator context.
```

The web UI may summarize Markdown, but actions that affect AI-to-AI handoff must
write structured records, audit events, or verification artifacts.

## Completion Target

Phase 17 is complete when a local operator can run this loop from the web UI and
release scripts without manually stitching together undocumented API calls:

```txt
1. Confirm system health and security posture.
2. Confirm AI-readable state quality.
3. Start a mock or live model review run.
4. Inspect the sanitized context summary.
5. Inspect the model response and dry-run findings.
6. Import findings only after explicit operator approval.
7. Triage findings and record implementation decisions.
8. Run verify-index and release checks.
9. Create and test a snapshot/restore path.
10. Produce a release evidence record.
```

## Recommended Implementation Order

Phase 17 should be implemented in dependency order. The Operator Console is the
main product surface, but it should not be built as an empty shell. At least one
machine-readable backend surface must exist before the console becomes useful.

Recommended sequence:

```txt
1. P17-006 AI State Quality Gate
2. P17-003 Real Gemini Adapter And Provider Status
3. P17-004 Provider Verification Matrix
4. P17-001 Unified Operator Console
5. P17-002 Model Run Operator UI
6. P17-007 Review And Finding Triage Ergonomics
7. P17-008 Maintenance And Recovery Console
8. P17-012 Midpoint Acceptance Run
9. P17-005 Cost And Token Accounting
10. P17-009 Release Readiness And Evidence Record
11. P17-010 Documentation And Phase Index Cleanup
12. P17-011 Test Coverage completion and final gap closure
13. P17-012 Final Acceptance Run
```

Parallel work is allowed when write scopes are separate, but do not let the UI
invent status that the API cannot provide. Console sections should render real
API data, explicit empty states, or explicit unavailable states.

## Verification Level Guardrails

Provider verification levels must be conservative:

```txt
mocked:
  Automated mocked tests passed.

configured:
  Credentials/config are present, and mocked tests pass, but no real provider
  call has completed.

live_verified:
  A real provider network call completed successfully and produced importable
  dry-run output through the model_review_runs workflow.
```

Mocked tests must never upgrade a provider to `live_verified`. For Gemini and
other paid/API-backed providers, `configured` is the maximum status until the
operator performs a real live call and records the evidence. Release readiness
may warn about missing live verification, but it must not claim live
verification without evidence.

## Acceptance Run Timing

P17-012 must not be saved only for the final release gate.

Required timing:

```txt
Midpoint run:
  Execute after P17-008 Maintenance And Recovery Console is functional.
  The goal is to reveal workflow blockers while there is still time to fix the
  product loop.

Final run:
  Execute after release readiness and documentation are updated.
  The goal is release evidence, not first discovery of integration failures.
```

The midpoint run may use mocked provider paths. The final run may also use
mocked paths unless live credentials are configured, but verification levels
must remain honest.

## P17-001 Unified Operator Console

Goal:

```txt
Make the web app the primary place to operate KnowNet locally.
```

Tasks:

```txt
1. Add or refactor a top-level Operator Console surface in the web app.
2. Keep existing page browsing and graph views available.
3. Organize operational surfaces into stable sections:
     Health
     AI State Quality
     Model Runs
     Review Inbox
     Findings
     Agent Access
     Maintenance
     Release Readiness
4. Use existing API endpoints before adding new endpoints.
5. Add small endpoint gaps only where the UI cannot safely derive state.
6. Keep all mutating actions behind existing admin/write authorization.
7. Show loading, failed, empty, and stale-data states.
8. Never expose raw tokens, token hashes, sessions, raw DB paths, backups, or
   local absolute file paths in ordinary UI.
```

UI rules:

```txt
Operational UI should be dense, scan-friendly, and calm.
Avoid landing-page layout.
Avoid marketing copy.
Avoid decorative cards inside cards.
Use status badges, tables, tabs, segmented controls, dialogs, and icon buttons
where they fit the workflow.
```

Done when:

```txt
An operator can open the web app and understand:
  current health
  pending review/finding work
  active or recent model runs
  agent access status
  maintenance readiness
  release blockers
without reading phase docs first.
```

## P17-002 Model Run Operator UI

Goal:

```txt
Expose Phase 16 model_review_runs as a reviewable operator workflow.
```

Tasks:

```txt
1. List model review runs with provider, model, prompt profile, status, created
   time, imported review id, token estimates, and verification level.
2. Add run detail view with:
     sanitized context summary
     selected review targets
     response status
     normalized findings preview
     import status
     errors without secrets
3. Support starting mock runs from the UI.
4. Support starting configured live provider runs only when credentials and
   provider status allow it.
5. Support cancellation for queued/running runs where the API can cancel safely.
6. Support re-dry-run for completed responses.
7. Support explicit import into collaboration_reviews/collaboration_findings.
8. Make imported runs read-only except for linking to the created review.
9. Show active-run blocking clearly when another run is already running.
```

Safety rules:

```txt
The UI must never let a model run:
  write pages
  apply suggestions
  execute code
  access raw DB files
  access backup archives
  access raw inbox messages
  receive ADMIN_TOKEN
```

Done when:

```txt
A model review run can be created, inspected, dry-run reviewed, imported, and
linked to review/finding triage from the web UI.
```

## P17-003 Real Gemini Adapter And Provider Status

Goal:

```txt
Finish the highest-priority real network adapter from Phase 16 while keeping
mocked and unverified states explicit.
```

Tasks:

```txt
1. Implement the real Gemini API adapter behind the shared provider contract.
2. Read API credentials only from server-side environment/config.
3. Add request timeouts and response size limits.
4. Normalize Gemini output into the existing structured model output schema.
5. Reject non-JSON or schema-invalid responses with a safe failed status.
6. Store sanitized request/response metadata only.
7. Log token usage when provided by the provider.
8. Add tests with mocked network responses:
     success
     timeout
     malformed JSON
     safety refusal or blocked response
     oversized response
     missing credentials
9. Do not require paid/API access for automated tests.
```

Provider status model:

```txt
unavailable:
  No config, missing credentials, or disabled provider.

mocked:
  Local mock adapter works and is test-covered.

configured:
  Credentials/config are present, but live call has not been verified.

live_verified:
  A live provider call succeeded and produced importable dry-run output.

failed:
  Last live attempt failed. Error is sanitized and operator-visible.
```

Done when:

```txt
Gemini can be used through the same model_review_runs workflow as mock runs,
and the operator can distinguish mocked, configured, live_verified, and failed
states.
```

## P17-004 Provider Verification Matrix

Goal:

```txt
Make external integration confidence visible and machine-readable.
```

Tasks:

```txt
1. Add a provider verification matrix in API data or generated JSON.
2. Include each Phase 16 provider/path:
     mock
     Gemini API
     DeepSeek API
     Qwen API
     Qwen-Agent MCP
     Kimi API
     Kimi Code MCP
     MiniMax API
     Mini-Agent HTTP/MCP
     GLM/Z.AI API
     GLM coding-tool MCP
     Manus Custom MCP/API
     Claude Desktop MCP
     ChatGPT/Cursor MCP where applicable
3. Track for each provider/path:
     route type
     implemented surface
     verification level
     last verified at
     required credential/config
     local test command
     live test command or manual runbook step
     safe scopes
     known limitations
4. Expose matrix in the Operator Console.
5. Keep docs synchronized with the matrix.
```

Rules:

```txt
Do not imply web chat products can perform API/MCP actions unless they were
actually verified.
Do not mark a provider live_verified from mocked tests.
Do not block local release on paid/API live verification for providers the
operator has not configured.
Do block provider-specific claims that say live verification happened when it
did not.
```

Done when:

```txt
The operator and the next AI agent can tell which provider paths are only
designed, which are mocked, which are configured, and which have live evidence.
```

## P17-005 Cost And Token Accounting

Goal:

```txt
Make model review runs accountable before they become routine.
```

Tasks:

```txt
1. Implement empty and unavailable UI states first.
2. Store input_tokens and output_tokens when a provider returns usage.
3. Store estimated tokens when exact usage is unavailable.
4. Store provider/model pricing metadata as optional config, not hard-coded
   truth.
5. Calculate estimated cost only when pricing metadata is available.
6. Show token/cost values in model run list and detail UI.
7. Add per-run context size preview before starting a run.
8. Warn when selected context exceeds configured budget.
9. Keep costs out of release pass/fail unless an explicit budget is configured.
```

Data rules:

```txt
Cost accounting is operator guidance, not billing authority.
Do not store API keys in pricing/config snapshots.
Do not assume token estimates are exact.
```

Done when:

```txt
Each model_review_run has visible token usage, token estimates, or an explicit
unavailable state. Live runs can show estimated cost when provider usage and
operator pricing metadata are both available.
```

## P17-006 AI State Quality Gate

Goal:

```txt
Check whether KnowNet's canonical AI-readable state is actually useful for the
next agent.
```

Quality checks:

```txt
1. Current state exists.
2. Boundaries and non-goals exist.
3. Known issues are current.
4. Review targets are explicit.
5. Verification notes are present.
6. Open/deferred high-severity findings are visible.
7. Recent implementation records link to findings or decisions.
8. Context bundles do not include forbidden secret/path patterns.
9. Large AI-facing responses have truncation metadata.
10. Graph/index counts are consistent enough for handoff.
```

Tasks:

```txt
1. Add an AI State Quality endpoint or extend existing health/agent summaries.
2. Return machine-readable checks with pass/warn/fail status.
3. Show quality gate results in the Operator Console.
4. Add a release-check warning or failure for severe quality drift.
5. Add tests for missing current state, stale findings, forbidden context hits,
   and truncation metadata.
```

Severity:

```txt
fail:
  Secret/path leak, missing canonical state, broken verify-index, or a severe
  graph/index drift that makes AI handoff misleading.

warn:
  Stale implementation records, missing review targets, missing verification
  notes, or unresolved deferred issues.

pass:
  State is current enough for a follow-on AI review.
```

Done when:

```txt
KnowNet can tell the operator whether the next AI agent is likely to receive
useful, safe, current context.
```

## P17-007 Review And Finding Triage Ergonomics

Goal:

```txt
Make review/finding decisions fast enough that the queue stays healthy.
```

Tasks:

```txt
1. Add review inbox filters:
     pending_review
     triaged
     imported from model run
     has pending findings
     has high severity findings
2. Add finding filters:
     pending
     accepted
     rejected
     deferred
     needs_more_context
     implemented
     severity
     provider/source
3. Add decision controls for each finding.
4. Require a short decision note for reject/defer/needs_more_context.
5. Link accepted findings to implementation records where possible.
6. Show finding provenance:
     original review
     provider/model
     imported run id
     created_at
     decision_at
7. Add stale queue warnings when pending findings remain too long.
```

Rules:

```txt
Do not delete reviews or findings to make the queue clean.
Do not mark AI suggestions accepted without operator decision.
Do not bury deferred high-severity findings.
```

Done when:

```txt
The operator can triage a review round from the web UI and the state summary no
longer needs manual DB/API inspection to understand queue health.
```

## P17-008 Maintenance And Recovery Console

Goal:

```txt
Expose existing operational safety workflows without making destructive actions
casual.
```

Tasks:

```txt
1. Show health summary and attention_required causes.
2. Show maintenance locks and active operations.
3. Show snapshot list with format, size, created time, and manifest status.
4. Support creating a snapshot from the UI.
5. Support verify-index from the UI.
6. Show verify-index issues with actionable grouping.
7. Keep restore as a guarded workflow:
     explicit snapshot selection
     lock check
     pre-restore snapshot warning
     dry-run or isolated restore check where available
     final confirmation
8. Do not expose raw backup contents in the browser.
9. Add audit events for UI-triggered maintenance actions.
```

Done when:

```txt
The operator can see whether maintenance is safe to run and can create
evidence-backed snapshots/verify-index results without using undocumented
commands.
```

## P17-009 Release Readiness And Evidence Record

Goal:

```txt
Turn release_check output into a durable, readable release evidence artifact.
```

Tasks:

```txt
1. Extend scripts/release_check.ps1 or add a wrapper to emit a structured JSON
   release evidence record.
2. Include:
     git status
     Rust test result
     API pytest result
     MCP test result
     SDK test result
     smoke test result
     npm audit result
     web build result
     health summary
     verify-index result
     snapshot created
     restore test result
     AI state quality result
     provider verification matrix summary
3. Write the latest result to docs/RELEASE_EVIDENCE.md.
4. Keep secrets and local absolute paths out of evidence records.
5. Show latest release readiness in the Operator Console.
6. Release check should fail when:
     tests fail
     build fails
     health is attention_required
     verify-index fails
     snapshot/restore test fails for a release run
     AI state quality has fail status
7. Release check may warn, not fail, when:
     optional provider live verification is missing
     costs are unavailable
     paid/API credentials are absent
     non-release docs have minor drift
```

Done when:

```txt
A release candidate has one durable evidence record that another AI agent can
read to understand what was verified and what remains unverified.
```

## P17-010 Documentation And Phase Index Cleanup

Goal:

```txt
Make the documentation match the real product surface.
```

Tasks:

```txt
1. Keep README phase links current early.
2. Defer broad RUNBOOK, RELEASE_CHECKLIST, and provider doc rewrites until the
   corresponding implementation surfaces are stable.
3. Update RUNBOOK with the Operator Console workflow.
4. Update RELEASE_CHECKLIST with AI state quality and provider verification.
5. Update provider docs with verification levels and last-live-test status.
6. Add a short "Daily Operator Loop" section:
     start dev stack
     check health
     inspect pending reviews/findings
     run model review if needed
     triage findings
     verify-index
     snapshot before risky operations
7. Add a short "Release Operator Loop" section:
     clean git status
     release_check
     snapshot
     isolated restore test
     evidence record
     tag only after restore is verified
```

Done when:

```txt
A new operator can use README and RUNBOOK to perform daily and release workflows
without reading all phase task files.
```

## P17-011 Test Coverage

Goal:

```txt
Cover the integration points that make Phase 17 trustworthy.
```

Required tests:

```txt
API:
  provider status matrix
  Gemini adapter mocked success/failure paths
  model run usage/cost fields
  AI state quality pass/warn/fail
  release evidence serialization
  forbidden context leakage regression

Web:
  model run list/detail rendering
  provider verification matrix rendering
  review/finding filtering
  health/maintenance empty/error states
  release readiness rendering

MCP/agent:
  AI state summary still has truncation metadata
  provider matrix or quality summary is safe for AI-readable handoff

Ops:
  release_check includes AI state quality
  verify-index remains part of release gate
  snapshot/restore evidence is recorded for release runs
```

Done when:

```txt
Phase 17 can be developed without relying on manual browser inspection for the
most important safety and workflow guarantees.
```

## P17-012 Acceptance Run

Goal:

```txt
Prove Phase 17 closes the integrated operator loop.
```

Runbook:

```txt
1. Start from a clean git status.
2. Start the local dev stack.
3. Open the Operator Console.
4. Confirm health is healthy or degraded without attention_required.
5. Confirm maintenance locks are clear.
6. Run AI State Quality and record pass/warn/fail.
7. Start a mock model review run.
8. Inspect sanitized context summary.
9. Re-dry-run output if needed.
10. Import findings into collaboration review/finding tables.
11. Triage at least one finding.
12. Add or link one implementation record if the finding is accepted.
13. Run verify-index.
14. Create a snapshot.
15. Run release_check in release mode.
16. Confirm release evidence records:
      tests/build
      health
      verify-index
      snapshot/restore
      AI state quality
      provider verification summary
17. Update docs with the acceptance run.
```

Done when:

```txt
The acceptance run completes, release evidence is written, pending/failed items
are explicitly documented, and no secret/path leaks are present in AI-readable
state or evidence records.
```

## Final Phase 17 Gate

Phase 17 is done only when all of these are true:

```txt
1. Operator Console shows health, AI state quality, model runs, review/finding
   triage, agent access, maintenance, and release readiness.
2. Model review runs can be created, inspected, dry-run reviewed, imported, and
   linked to findings.
3. Gemini has a real adapter with mocked network tests and clear credential
   handling.
4. Provider paths have explicit verification levels.
5. Token/cost usage is visible for model runs where data is available.
6. AI state quality gate exists and is included in release readiness.
7. Review/finding triage can be performed from the web UI.
8. Maintenance workflows expose snapshots, locks, and verify-index safely.
9. Release evidence is durable and safe for AI handoff.
10. README, RUNBOOK, RELEASE_CHECKLIST, and provider docs match the product.
11. release_check passes for local release mode.
12. A snapshot restore test has been performed before any release tag.
```

Do not mark Phase 17 complete if restore has not been tested.
