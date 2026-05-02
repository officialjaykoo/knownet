# Phase 15 Tasks: Release Hardening Round 1

Phase 15 raises KnowNet quality after Phases 1-14. It is not a feature
expansion phase. The goal is to make the already-built system safer, cleaner,
faster, and easier to verify before longer real use.

Implementation status: completed in the codebase.

Completed surface:

```txt
scripts/phase15_hardening.py
  Live Phase 15 hardening runner for token cleanup, DB finding triage,
  MCP flow verification, performance baseline collection, snapshot integrity,
  docs/DB cross-check, and release-hardening report generation.

scripts/release_check.ps1
  Release gate covering Rust, API, MCP, SDK, slow operational tests, smoke
  tests, web audit/build, live health, verify-index, and agent-surface exposure
  warnings.

apps/api/tests/test_phase15_integration.py
  Phase 7-14 integration coverage for agent onboarding, ai-state, dry-run
  review, submitted review, finding decision, implementation record, graph
  integration, and verify-index.

apps/api/knownet_api/routes/agent.py
  Agent list metadata now returns offset-aware truncation metadata and
  next_offset for paginated AI-facing responses.

docs/RELEASE_HARDENING_RUN.md
docs/PERFORMANCE_BASELINE.md
docs/EXTERNAL_AI_REVIEW_TRIAGE.md
docs/EXTERNAL_AI_ACCESS_LOG.md
  Phase 15 live run evidence, measured timings, final review/finding triage
  status, and external token cleanup record.
```

## Fixed Decisions

```txt
Phase 15 is quality hardening, not product expansion.

Do not add:
  New collaboration concepts.
  New public write surfaces.
  New dashboard analytics.
  New agent execution features.
  New archive formats.
  New auth systems.

Do improve:
  Temporary token cleanup.
  Review/finding triage hygiene.
  Long-use test data confidence.
  Full verify-index drift checks.
  Real MCP agent flow verification.
  Phase 7-14 integration coverage.
  Revoked-token failure verification.
  Backup snapshot integrity checks.
  MCP bridge restart resilience.
  Documentation/DB state cross-checks.
  Large response guards.
  Local operation without Cloudflare tunnel.
  First-run/runbook command validation.
  Performance visibility.
  Operator UX for existing workflows.
  Release gate automation.

External quick-tunnel tests are considered complete for Phase 14.
Phase 15 should assume external AI review tokens from that round are temporary
and should be revoked unless explicitly marked as active by the operator.
```

## P15-001 Temporary Agent Token Cleanup

Goal:

```txt
Close the external AI test window and prevent stale test tokens from staying
usable.
```

Priority:

```txt
Do this first. Do not wait for the rest of Phase 15.
```

Tasks:

```txt
1. Identify agent_tokens created for Phase 14 external review/testing.
2. Revoke tokens whose purpose/label indicates quick tunnel, external review,
   GET preview, or temporary MCP testing.
3. Do not revoke operator-created tokens that are not clearly test tokens.
4. After revoke, verify at least one revoked token fails against
   GET /api/agent/me or equivalent MCP call with 401.
5. Verify the revoked token also fails through the MCP bridge or MCP tool path.
6. Record the cleanup in audit_events.
7. Update external AI access log with cleanup status.
```

Done when:

```txt
Agent tokens used for Claude/ChatGPT/Gemini/Manus/DeepSeek/Qwen/Kimi/MiniMax/
GLM quick-tunnel testing are revoked or explicitly listed as intentionally kept.
At least one revoked-token access attempt is verified to fail.
At least one revoked-token MCP tool call or bridge call is verified to fail.
GET /api/maintenance/verify-index still passes.
```

## P15-002 Review And Finding Triage Hygiene

Goal:

```txt
Make the collaboration review queue reflect the triage already recorded in
docs/EXTERNAL_AI_REVIEW_TRIAGE.md.
```

Tasks:

```txt
1. Keep original reviews and findings; do not delete review records.
2. Apply decisions to findings:
   - resolved implementation-backed issues -> accepted
   - false positives -> rejected
   - intentional non-changes -> rejected with reason
   - release/ops follow-ups -> deferred
3. Add implementation records where code/docs were changed in Phase 14.
4. Ensure reviews with no pending findings become triaged.
5. Keep docs/EXTERNAL_AI_REVIEW_TRIAGE.md as the readable AI summary.
```

Rules:

```txt
Do not mark a finding accepted just because an AI said it.
Do not hide false positives by deleting them.
Decision notes must be short, explicit, and machine-readable enough for another
AI to understand.
```

Done when:

```txt
GET /api/collaboration/reviews no longer shows the Phase 14 external review
round as a large unresolved pending queue.
State summary and graph counts still make sense after collaboration graph
rebuild.
```

## P15-003 Long-Use Data Exercise

Goal:

```txt
Exercise KnowNet with realistic local data volumes before trusting it for longer
daily use.
```

Scenario:

```txt
Use existing APIs, not direct DB/file writes, to create or simulate:
  At least 50 active project pages total.
  At least 20 collaboration reviews total.
  At least 50 findings total.
  At least 20 finding decisions.
  At least 5 implementation records.

Existing Phase 14 review data may count toward these totals.
```

Required flows:

```txt
0. Run verify-index before the exercise to establish baseline drift state.
1. Page reads through normal page API.
2. Agent ai-state reads.
3. Review dry-run.
4. Review import.
5. Finding decision.
6. Implementation record.
7. Graph rebuild or collaboration graph rebuild.
8. Backup snapshot creation.
9. verify-index.
```

Real MCP agent flow:

```txt
At least one real MCP-capable client or local MCP JSON-RPC test must run:
  knownet_start_here
  knownet_me
  knownet_state_summary
  knownet_ai_state
  knownet_review_dry_run
  knownet_submit_review
  finding decision through API/operator path

Use a short-lived local token.
Do not use a broad or permanent token.
Do not expose the raw token in logs or docs.
```

Security checks during exercise:

```txt
ai-state responses must not contain:
  source_path
  source.path
  C:/knownet
  backslash-heavy absolute Windows paths
  token_hash
  raw_token
```

Done when:

```txt
The scenario can be run repeatably without corrupting pages, graph nodes,
reviews, findings, citations, or ai_state rows.
A short run report is written to docs/RELEASE_HARDENING_RUN.md.
The report includes verify-index before/after results and the MCP flow result.
The report confirms ai-state did not expose local filesystem paths or token
material.
```

## P15-004 Performance Visibility

Goal:

```txt
Find slow paths with measurements instead of guessing.
```

Measure at minimum:

```txt
GET /api/pages
GET /api/pages/{slug}
GET /api/agent/ai-state?limit=20
GET /api/agent/state-summary
GET /api/graph
GET /api/citations/audits
GET /mcp
GET /mcp?resource=agent:onboarding
GET /mcp?resource=agent:state-summary
Web initial load on http://127.0.0.1:3000
```

Large response guards:

```txt
Verify truncation/pagination metadata for:
  GET /api/agent/ai-state with a small limit.
  MCP fetch agent:ai-state.
  graph summary/list endpoints when limit is small.

Expected metadata should include truncated/next_offset/warning where relevant.
Responses must not include local filesystem paths.
```

Rules:

```txt
Add timing only where it helps operators or tests.
Do not add heavy analytics.
Do not introduce polling.
Do not optimize before measuring.
```

Done when:

```txt
docs/PERFORMANCE_BASELINE.md records median-ish local timings, obvious slow
paths, and any fixes made.
Endpoints used by external agents have predictable response sizes and no local
filesystem paths in responses.
```

## P15-005 Operator UX Pass

Goal:

```txt
Improve existing operator workflows without adding a larger dashboard product.
```

Review these flows:

```txt
1. Owner bootstrap and login failure feedback.
2. Agent Dashboard open/close in the main pane.
3. Agent token revoke/rotate/create feedback.
4. Review/finding triage navigation.
5. Context bundle naming and explanation.
6. Inbox naming/explanation.
7. Graph node layer color readability.
8. Sidebar sort behavior and selected/pinned clarity.
```

Rules:

```txt
No dashboard analytics.
No new charts.
No nested cards.
No automatic polling.
Prefer clearer labels, disabled states, empty states, and direct workflow links.
```

Done when:

```txt
The operator can tell where to create/revoke tokens, where to triage reviews,
where to read pages, and why quick tunnel access is test-only.
Next build passes.
```

## P15-006 MCP Bridge Restart And Local/External Boundary

Goal:

```txt
Make the MCP bridge reliable after restart and keep local operation independent
from Cloudflare quick-tunnel exposure.
```

Tasks:

```txt
1. Stop and restart the MCP HTTP bridge.
2. Verify after restart:
   - GET /mcp
   - GET /mcp?resource=agent:onboarding
   - GET /mcp?resource=agent:state-summary
   - JSON-RPC initialize
   - JSON-RPC tools/list
3. Stop Cloudflare quick tunnel and verify local API/Web/MCP still work.
4. Restart quick tunnel only if an external test explicitly needs it.
```

Rules:

```txt
Cloudflare tunnel state must not be required for local use.
Do not leave quick-tunnel running as if it were production.
Do not print raw agent tokens in bridge logs.
```

Done when:

```txt
docs/RELEASE_HARDENING_RUN.md records bridge restart results and confirms local
operation works with Cloudflare off.
```

## P15-007 Phase 7-14 Integration Test Coverage

Goal:

```txt
Add one high-value integration test that covers the collaboration path built
across Phases 7-14.
```

Priority:

```txt
Build this before broad manual hardening. It is the regression net for the rest
of Phase 15.
```

Minimum flow:

```txt
1. Create scoped agent token.
2. Agent reads onboarding.
3. Agent reads state-summary.
4. Agent reads ai-state.
5. Agent dry-runs a review.
6. Agent submits the review.
7. Operator decides at least one finding.
8. Implementation record is attached.
9. Collaboration graph rebuild/check does not fail.
10. verify-index compatible state remains valid.
```

Rules:

```txt
Use isolated test DB/data directory.
Do not depend on network or Cloudflare.
Do not assert fragile exact counts from the developer's live data.
```

Done when:

```txt
The integration test passes in normal API pytest and catches broken onboarding,
review import, finding decision, or implementation record wiring.
```

## P15-008 Backup Snapshot Integrity Check

Goal:

```txt
Verify the backup safety net without doing risky restore operations by default.
```

Tasks:

```txt
1. Create a snapshot through the maintenance API or release check.
2. Confirm the archive uses .tar.gz.
3. Confirm the archive contains a manifest.
4. Confirm forbidden local secrets are not printed in logs or report.
5. Do not restore over the live data directory unless explicitly requested.
```

Done when:

```txt
docs/RELEASE_HARDENING_RUN.md records snapshot path, archive format, manifest
presence, and any skipped restore rationale.
```

## P15-009 Documentation/DB State Cross-Check

Goal:

```txt
Prevent docs from saying external review findings are resolved while the DB
still shows a large stale pending queue.
```

Tasks:

```txt
1. Compare docs/EXTERNAL_AI_REVIEW_TRIAGE.md issue groups against
   collaboration_findings statuses.
2. Add a lightweight script or release-check step if practical.
3. Record mismatches as release warnings.
4. Do not delete original reviews/findings.
```

Done when:

```txt
The release hardening report states whether docs and DB triage agree.
Any intentional mismatch is explicitly listed.
```

## P15-010 First-Run And Runbook Validation

Goal:

```txt
Check that the documented local startup and verification commands still match
the real repo.
```

Validate:

```txt
README or runbook startup command.
scripts/dev.ps1 behavior.
scripts/ops_check.ps1 behavior.
scripts/release_check.ps1 behavior after P15-011.
MCP bridge startup command.
```

Rules:

```txt
Do not rewrite all docs.
Fix only commands or instructions that are wrong or confusing.
```

Done when:

```txt
docs/RELEASE_HARDENING_RUN.md includes a runbook validation result and any doc
edits made.
```

## P15-011 Release Gate Automation

Goal:

```txt
Make release readiness one command instead of a memory exercise.
```

Priority:

```txt
Build this early, then use it after each Phase 15 work cluster.
```

Required command:

```txt
scripts/release_check.ps1
```

It should run or clearly report:

```txt
cargo test
API pytest
MCP pytest
SDK pytest
npm audit
npm run build
GET /health/summary
GET /api/maintenance/verify-index
External review docs/DB cross-check
MCP bridge restart smoke check
Security/path exposure grep checks
Optional smoke tests when the local environment supports them
```

Output rules:

```txt
Do not print ADMIN_TOKEN or agent tokens.
Print pass/fail summary.
Print degraded health issues separately from hard failures.
Treat embedding.unavailable as acceptable local degraded state.
Treat security.public_without_cloudflare_access as acceptable only when quick
tunnel/testing mode is explicitly active; otherwise warn loudly.
Fail or warn loudly if exposed agent surfaces contain source_path, token_hash,
raw_token, or local absolute paths such as C:/knownet.
```

Done when:

```txt
Running scripts/release_check.ps1 gives a single high-signal release readiness
summary and exits non-zero on hard failures.
```

## P15-012 Phase 15 Closeout

Goal:

```txt
Leave Phase 15 in a state another AI can safely continue from.
```

Closeout tasks:

```txt
1. Update this document's implementation status.
2. Update docs/RELEASE_HARDENING_RUN.md.
3. Ensure docs/EXTERNAL_AI_REVIEW_TRIAGE.md reflects final finding states.
4. Run scripts/release_check.ps1.
5. Commit and push.
```

Completion definition:

```txt
Phase 15 is complete when:
  1. Temporary external AI test tokens are revoked or explicitly accounted for.
  2. Phase 14 external review findings are triaged in DB and docs.
  3. Long-use data exercise has a written run report.
  4. Performance baseline exists with measured timings.
  5. Operator UX pass is complete without feature expansion.
  6. Revoked-token failure, backup snapshot integrity, MCP bridge restart, and
     local-without-Cloudflare checks are recorded.
  7. Phase 7-14 integration test exists and passes.
  8. Release gate automation runs successfully.
  9. verify-index passes.
  10. Working tree is clean after commit/push.
```

## Suggested Implementation Order

```txt
Immediate:
  P15-001 Temporary Agent Token Cleanup

First work cluster:
  P15-007 Phase 7-14 Integration Test Coverage
  P15-011 Release Gate Automation

Second work cluster:
  P15-002 Review And Finding Triage Hygiene
  P15-003 Long-Use Data Exercise
  P15-006 MCP Bridge Restart And Local/External Boundary

Third work cluster:
  P15-004 Performance Visibility
  P15-005 Operator UX Pass
  P15-008 Backup Snapshot Integrity Check
  P15-009 Documentation/DB State Cross-Check
  P15-010 First-Run And Runbook Validation

Final:
  P15-012 Phase 15 Closeout
```
