# Phase 18 Tasks: AI Handoff Acceleration

Phase 18 reduces the slowest gap in the KnowNet external-AI loop:

```txt
AI reads KnowNet -> AI gives advice -> operator/Codex turns advice into work ->
implementation evidence returns to KnowNet.
```

Phase 17 made the operator console coherent. Phase 18 should make the next AI
agent faster by giving it structured handoff packets, actionable queues, and
implementation evidence without asking a human to re-read the same context.

Implementation status: completed in the codebase on 2026-05-04.

Implemented surface as of 2026-05-04:

```txt
Done:
  - project snapshot packet endpoint
  - project snapshot packet read endpoint
  - project snapshot packet UI generate/copy surface
  - next-action endpoint for agent-friendly one-call task discovery
  - Gemini fast-lane review endpoint for direct server-side API review
  - fast-lane slim context defaults for lower latency provider calls
  - stale/duplicate finding suppression in model-run context and parser output
  - duplicate finding group endpoint for review queue compression
  - duplicate candidate reporting during review dry-run
  - backlog-aware next-action routing before new Gemini reviews
  - next-action task_template payloads for immediate Codex/API execution
  - automatic accepted-finding task creation for high-confidence/high-severity work
  - project snapshot delta packets through since timestamps
  - simplified implementation evidence endpoint for commit/note closure
  - shared protocol header across Gemini and OpenAI-compatible provider prompts
  - next-action provider-first recommendation when Gemini is configured
  - accepted finding queue endpoint for AI/Codex handoff
  - finding task table for accepted finding -> implementation task conversion
  - finding task creation endpoint with generated task prompt and verification hint
  - finding task list endpoint for Codex-readable work discovery
  - Review Inbox Task button for accepted findings
  - implementation evidence dry-run endpoint
  - implementation evidence commit endpoint with task linkage
  - task done update after implementation evidence is recorded
  - restore revision optimistic lock through expected_current_revision_id
  - changed-file path validation for implementation evidence
  - verify-index orphan check for finding_tasks
  - API tests for project snapshot, accepted finding task conversion, and
    implementation evidence recording
  - RUNBOOK fast AI handoff documentation
```

## Fixed Decisions

```txt
Do not add:
  External AI write access to pages.
  Raw SQLite, backup, shell, token, or filesystem access.
  A second review/finding model.
  Release blockers from context_limited findings without operator verification.
  A slow release_check dependency in daily AI experiments.

Do add:
  Copy-ready and API-readable handoff packets.
  A small accepted-finding work queue.
  Task prompts that Codex can consume without re-reading long reviews.
  Evidence records that connect code changes back to accepted findings.
  A one-call next action endpoint for Codex and other local agents.
  A paid/API provider fast lane before packet fallback when credentials exist.
  Targeted verification over broad release checks for daily work.
```

## P18-001 Project Snapshot Packet

Goal:

```txt
Give Claude, Codex, or another reviewer a compact, current project packet that
explains what KnowNet is, where the operator loop stands, and what to inspect.
```

Tasks:

```txt
1. Add a project snapshot packet endpoint. Done.
2. Include current health summary without secrets or local absolute paths. Done.
3. Include AI state quality, provider matrix summary, pending review/finding
   counts, recent model runs, recent accepted tasks, and release readiness.
   Done.
4. Include a concise operator question or focus area. Done.
5. Keep the packet copy-ready for web chat and readable through API JSON. Done.
6. Add preflight warnings when health is degraded, pending findings are high,
   or AI state quality is fail. Done.
7. Add tests for secret/path redaction and packet shape. Done.
```

Done when:

```txt
An external AI can understand the current KnowNet project state from one packet
without reading the whole docs folder or guessing from node names.
```

## P18-002 Accepted Finding Queue

Goal:

```txt
Turn accepted external-AI advice into implementation work that Codex can read
directly.
```

Implemented:

```txt
1. Added finding_tasks structured table.
2. Added GET /api/collaboration/finding-queue.
3. Added GET /api/collaboration/finding-tasks.
4. Added POST /api/collaboration/findings/{finding_id}/task.
5. Generated deterministic task prompts from accepted findings.
6. Generated expected verification hints by finding area.
7. Added Review Inbox Task button for accepted findings.
8. Added verify-index orphan check for finding_tasks.
9. Added targeted API tests.
```

Rules:

```txt
Only accepted findings can become implementation tasks.
Finding tasks do not execute code.
Finding tasks do not mark findings implemented.
Implementation still needs verification and an implementation record.
```

Done when:

```txt
Codex can ask KnowNet for accepted work, receive a scoped task prompt, implement
it, and then record evidence against the same finding.
```

## P18-002A Agent Next Action

Goal:

```txt
Let Codex ask KnowNet "what should I do next?" without using the UI or reading
the full review queue manually.
```

Implemented:

```txt
1. Added GET /api/collaboration/next-action.
2. Prefer open/in_progress finding_tasks by task priority and finding severity.
3. Fall back to accepted findings that still need task creation.
4. Fall back to review/finding triage when nothing is accepted yet.
5. Fall back to project snapshot generation when no actionable work exists.
6. Include the implementation-evidence endpoint to call after coding.
7. Added targeted API tests for task, accepted-finding, triage, and empty states.
```

Done when:

```txt
A coding agent can call one endpoint, receive the next action plus the exact
follow-up API endpoint, and proceed without opening the browser.
```

## P18-002B Provider Fast Lane

Goal:

```txt
When Gemini is configured, use the server-side API directly instead of making
the operator copy packets through an external web chat.
```

Implemented:

```txt
1. Added POST /api/model-runs/review-now.
2. Selects Gemini live mode when GEMINI_RUNNER_ENABLED and GEMINI_API_KEY exist.
3. Supports allow_mock_fallback for offline/local drills.
4. Supports auto_import for one-call mock or provider review import.
5. Keeps dry-run/import state in the existing model_review_runs table.
6. Keeps operator import optional and explicit through auto_import.
7. next-action now recommends review-now before project snapshot fallback when
   Gemini is configured.
8. Defaults to slim context with bounded pages/findings for daily fast-lane use.
9. Includes access fallback, boundary enforcement, evidence-quality, and stale
   suppression rules in the provider request packet.
10. Deduplicates repeated finding titles before Markdown/import parsing.
11. Added targeted tests for live adapter selection, mock fallback, required
   live mode, and next-action recommendation.
```

Done when:

```txt
An operator or Codex can call one endpoint and have KnowNet run a Gemini review
through the API key path, falling back to packet workflows only when configured
provider access is unavailable or explicitly declined.
```

## P18-003 Implementation Evidence Auto-Recording

Goal:

```txt
Reduce the gap between "Codex fixed it" and "KnowNet knows what changed".
```

Tasks:

```txt
1. Add an implementation evidence draft endpoint that accepts finding_id,
   changed files, verification output, and optional commit SHA. Done.
2. Support a dry-run mode that validates evidence without marking implemented.
   Done.
3. Auto-fill changed files from git status when invoked locally by operator
   tooling, but never expose raw local paths to external AI.
   Done through include_git_status.
4. Link evidence to finding_tasks when a task exists. Done.
5. Mark the task done only after implementation record creation succeeds. Done.
6. Keep the existing collaboration_findings status transition to implemented.
   Done.
7. Add targeted tests for dry-run, invalid commit SHA/path protection, orphan
   task protection, and task status updates. Done.
```

Done when:

```txt
After implementing a task, Codex can submit one evidence payload and KnowNet
records the implementation, updates the task, and keeps verify-index clean.
```

## P18 Acceptance Gate

Phase 18 is complete when all of these are true:

```txt
1. A project snapshot packet gives external AI enough safe context to advise.
2. Accepted findings can be listed as actionable tasks.
3. Accepted findings can be converted into tasks from API and UI.
4. Implementation evidence can be recorded with task linkage.
5. verify-index covers the new task/evidence state.
6. Targeted tests pass without depending on the full release_check script.
7. RUNBOOK documents the fast daily AI handoff loop.
8. GET /api/collaboration/next-action returns a useful next API action for
   task work, accepted findings, triage, or snapshot generation.
9. POST /api/model-runs/review-now starts a Gemini fast-lane review when the
  server has provider credentials, with mock fallback only when allowed.
```

## P18-004 Fast Provider Loop Hardening

Goal:

```txt
Make server-side AI review faster and less noisy than copy/paste packet review,
while keeping the same safety boundaries.
```

Implemented:

```txt
1. Review-now defaults to max_pages=10, max_findings=15, and slim_context=true.
2. Provider routes accept max_findings and slim_context controls.
3. Safe context includes protocol headers for access fallback, boundary
   enforcement, evidence quality, stale suppression, and daily verification.
4. Safe context deduplicates existing open findings by normalized title.
5. Model output normalization drops duplicate finding titles before Markdown
   generation.
6. OpenAI-compatible providers receive the same protocol header as Gemini.
7. next-action recommends Gemini review-now earlier when credentials exist,
   while still prioritizing open/in-progress implementation tasks.
8. Targeted tests cover context slimming, duplicate suppression, protocol
   prompt injection, and fast-lane request defaults.
```

Done when:

```txt
Gemini or another configured provider can inspect KnowNet through a compact,
protocol-bearing packet and return fewer duplicate findings without relying on
the slow full release checklist.
```

## P18-005 Restore Optimistic Lock

Goal:

```txt
Prevent stale AI/operator actions from restoring an old page revision over a
newer current revision without noticing the race.
```

Implemented:

```txt
1. POST /api/pages/{slug}/revisions/{revision_id}/restore accepts
   expected_current_revision_id.
2. Restore returns 409 page_revision_conflict when the current page revision no
   longer matches the expected revision.
3. Audit metadata records the expected current revision when supplied.
4. Existing no-body restore calls remain supported for manual/operator flows.
5. Integration test covers stale expected revision rejection and successful
   expected revision restore.
```

Done when:

```txt
AI-assisted restore workflows can pass the revision they inspected and fail
fast if the page changed before the write.
```

## P18-006 Review Queue Compression

Goal:

```txt
Treat fast/cheaper providers such as Gemini Flash as narrow reviewers, not as
the primary reasoning authority. Keep their context small and prevent them from
adding noise while unresolved review backlog exists.
```

Implemented:

```txt
1. Added GET /api/collaboration/finding-duplicates.
2. Groups open findings by normalized title across pending, needs_more_context,
   accepted, and deferred statuses.
3. Reports canonical finding id, duplicate count, involved statuses, and source
   review metadata for each duplicate group.
4. Review import dry-run now reports duplicate_candidates when incoming finding
   titles already exist in the open finding set.
5. next-action now prefers accepted finding task creation before Gemini when
   accepted work is already waiting.
6. next-action now recommends compress_review_queue when pending review/finding
   backlog or duplicate groups would make another Gemini review noisy.
7. Experiment packet requests accept minimum_inline_context so operator-supplied
   critical context is always carried alongside selected node excerpts.
8. Targeted tests cover duplicate grouping, dry-run duplicate candidates,
   backlog-aware next-action, and minimum inline context packets.
```

Done when:

```txt
KnowNet can reduce review queue noise before asking a fast provider for more
advice, and external AI packet quality does not depend on the model guessing
from node names.
```

## P18-007 Advice To Implementation Compression

Goal:

```txt
Reduce the handoff gap after an external AI gives useful advice. Codex should
receive the next executable API payload instead of rereading the review queue or
inventing request bodies.
```

Implemented:

```txt
1. GET /api/collaboration/next-action now includes task_template payloads for
   implementation tasks, accepted finding task creation, review queue triage,
   provider fast-lane review, and project snapshot generation.
2. Implement-finding actions also include a simple_evidence_template pointing at
   POST /api/collaboration/findings/{finding_id}/evidence.
3. Accepting a critical/high finding, or a direct_access/operator_verified
   finding, auto-creates an open Codex-owned finding task.
4. POST /api/collaboration/findings/{finding_id}/evidence accepts the compact
   implemented/commit/note shape and records normal implementation evidence.
5. Project snapshot packets accept since to include changed pages, findings,
   finding tasks, and model runs since a timestamp.
6. Targeted collaboration tests cover automatic task creation, task_template
   payloads, snapshot delta packets, and simplified evidence recording.
```

Done when:

```txt
An external AI can return a narrow finding, the operator can accept it, and
Codex can call next-action, implement, then close the loop with a small evidence
payload without opening the UI or running release_check.
```

Deferred:

```txt
Patch suggestion diff generation remains a future phase item. It needs code
context analysis and should stay optional because external AI providers do not
receive raw filesystem or shell access.
```
