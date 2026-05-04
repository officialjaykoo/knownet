# Phase 19 Tasks: Snapshot And Packet Standardization

Phase 19 turns the lesson from Phase 18 into a product rule:

```txt
The connection path is not the product. The AI-readable snapshot and packet are
the product surface that determines whether external AI advice is useful.
```

Phase 18 made AI handoff executable through next-action, task templates,
provider fast lanes, delta snapshots, and compact evidence. Phase 19 should
raise the quality and consistency of what gets sent to Gemini, DeepSeek,
Claude, Codex, or any other reviewer.

Implementation status: completed in the codebase on 2026-05-05.

Implemented surface as of 2026-05-05:

```txt
Done:
  - project snapshot profile field with overview/stability/performance/security/
    implementation/provider_review profiles
  - profile-specific snapshot sections and invalid profile validation
  - p19.v1 packet contract shared by project snapshots, experiment packets, and
    provider fast-lane model context
  - output modes for decision_only, top_findings, implementation_candidates,
    and provider_risk_check
  - snapshot_quality advisory block with warnings and UI acknowledgement state
  - snapshot_quality details and warning_details for explainable quality loss
  - important_changes section covering high-severity findings, actionable tasks,
    failed model runs, and implementation evidence
  - snapshot_diff_summary for human/AI-readable delta meaning
  - Known Done / Do Not Reopen section for implemented/rejected/deferred items
  - action_route tagging for important findings/tasks
  - profile_hard_limits in packet contract and snapshot JSON
  - snapshot_self_test structural checks for contract/profile/required sections
  - profile-specific default focus prompts
  - do_not_suggest rules in packet content and machine-readable JSON
  - target_agent_policy compaction for smaller/cheaper provider reviewers
  - project_snapshot service module for snapshot policy outside the API route
  - since_packet_id metadata flow through project_snapshot_packets
  - profile mismatch warning for delta packets
  - compact JSON review parser with ai_feedback_prompt on contract errors
  - compact /findings/{finding_id}/evidence endpoint from Phase 18 remains the
    short implementation closure path
  - patch-suggestion stub with machine-readable safety_contract
  - stricter auto task creation: direct_access/operator_verified AND
    high/critical severity
  - AI Packets UI controls for snapshot profile, output mode, since packet, and
    quality acknowledgement
  - targeted API tests and web build coverage
```

## Why Snapshot First

```txt
Snapshot quality comes before packet polish.
```

Reason:

```txt
Packets are delivery envelopes. Snapshots are the source state they carry. If
the snapshot includes stale, duplicated, vague, or low-value state, a clean
packet format only makes bad context easier to send.
```

Phase 19 order:

```txt
1. Improve project snapshot quality and profiles.
2. Standardize packet contracts on top of that snapshot shape.
3. Make provider/API calls use the same contracts as copy-paste packets.
4. Make AI responses shorter and import-safe by default.
```

## Implementation Priority

```txt
Phase 19A:
  P19-001 Snapshot Profiles
  P19-004 Packet Contract Standardization

Phase 19B:
  P19-002 Snapshot Quality Scores
  P19-003 Delta-First Snapshot Flow
  P19-005 Short Output Contracts

Phase 19C:
  P19-006 Snapshot To Task Bridge
  P19-007 Deferred Patch Suggestion API
```

Why:

```txt
Profiles reduce irrelevant context immediately. Packet contracts make Claude,
Codex, Gemini, and DeepSeek comparable because copy-paste packets and API-key
provider packets carry the same shape and rules. Quality scores, delta flow,
short outputs, and automation should build on that stable base.
```

Dependency graph:

```txt
P19-001 Snapshot Profiles
  -> P19-004 Packet Contract Standardization
  -> P19-005 Short Output Contracts
  -> P19-006 Snapshot To Task Bridge

P19-001 Snapshot Profiles
  -> P19-002 Snapshot Quality Scores
  -> P19-003 Delta-First Snapshot Flow

P19-004 Packet Contract Standardization
  -> P19-003 Delta-First Snapshot Flow
  -> P19-007 Deferred Patch Suggestion API
```

Implementation rule:

```txt
Do not implement P19-006 automation before P19-001 and P19-004 are stable and
tested. Automation on unstable packet contracts creates noisy tasks faster.
```

## Fixed Decisions

```txt
Do not add:
  Raw SQLite access for external AI.
  Raw filesystem, shell, token, backup, or .env access.
  A separate model-specific review schema.
  More broad "review everything" prompts.
  Full release_check as a daily packet generation dependency.
  Long node-document rewrites as the main solution.

Do add:
  Snapshot profiles for specific questions.
  Small, stable packet contracts.
  JSON blocks that AI and Codex can parse.
  Delta-first snapshots when a previous packet exists.
  Import-ready finding/action formats.
  Explicit "do not suggest" and stale-context suppression.
  Targeted verification hints attached to implementation tasks.
```

## P19-001 Snapshot Profiles

Goal:

```txt
Stop producing one generic project snapshot for every AI question.
```

Tasks:

```txt
1. Add a snapshot profile field to project snapshot packet requests.
2. Support at least these profiles:
   - overview
   - stability
   - performance
   - security
   - implementation
   - provider_review
3. Each profile chooses a bounded set of fields and sections.
4. Keep overview as the backward-compatible default.
5. Add profile metadata to the Markdown and machine-readable JSON block.
6. Add targeted tests proving profiles include/exclude the intended sections.
```

Profile field contract:

```txt
profile default: overview
unknown profile: 422 project_snapshot_invalid_profile
profile is written to packet_metadata and machine-readable JSON
```

Profile include/exclude table:

| profile | Must include | Must exclude |
| --- | --- | --- |
| overview | health, AI state quality, provider summary, warnings, accepted findings, recent tasks, recent model runs | raw page bodies, raw DB paths, secrets, backup contents |
| stability | health issues, provider failures, failed/slow model runs, pending high-severity findings, backup age, embedding status | broad UI state, long docs history, low-severity implemented findings |
| performance | provider duration/failure summary, search fallback state, model-run durations, graph/index freshness, recent slow warnings | security narrative, unrelated accepted findings, full review bodies |
| security | public mode/access guard state, auth warnings, evidence quality mix, boundary rules, high severity security findings | provider benchmarking detail, performance-only findings, raw tokens |
| implementation | open finding tasks, accepted high-confidence findings, task_template, expected verification, recent implementation evidence | pending low-confidence advice, broad provider matrix detail, release speculation |
| provider_review | provider matrix, configured/live/mock status, latest failures, request-shape warnings, model-run history | unrelated page narrative, implementation task details, backup restore detail |

Backward compatibility test:

```txt
An old project snapshot request without profile must produce the same core
overview fields that Phase 18 exposed: health, ai_state_quality, release
summary, provider_matrix, preflight, warnings, accepted_findings,
finding_tasks, and model_runs.
```

Done when:

```txt
Codex can request an implementation snapshot, DeepSeek can request a stability
snapshot, and neither one has to read irrelevant project history.
```

## P19-002 Snapshot Quality Scores

Goal:

```txt
Make packet quality visible before sending it to a provider or web chat.
```

Tasks:

```txt
1. Add a snapshot_quality block to project snapshot packet responses.
2. Score freshness, duplication, pending backlog, evidence quality mix, and
   context size.
3. Report warnings such as stale_delta, too_many_pending_findings,
   mostly_context_limited, duplicate_noise, and oversized_packet.
4. Keep this advisory only; do not block packet generation.
5. Surface the quality block in the AI Packets UI.
6. Add tests for warning generation.
```

Required warning behavior:

```txt
1. Warnings are advisory and do not block API packet generation.
2. The UI should support an acknowledged flag before sending a warned packet to
   a provider or before copying it for web chat.
3. mostly_context_limited must be reflected in the packet output contract:
   results from this packet may create review flags, but must not become release
   blockers without operator verification.
```

Done when:

```txt
The operator can see whether a packet is likely to produce useful advice before
asking an external AI.
```

## P19-003 Delta-First Snapshot Flow

Goal:

```txt
Make "what changed since the last AI saw KnowNet" the normal flow.
```

Tasks:

```txt
1. Persist project snapshot packet metadata in SQLite, not only as Markdown
   files.
2. Track target_agent, profile, focus, generated_at, content_hash, and warnings.
3. Let project snapshot requests use since_packet_id instead of manually
   supplying an ISO timestamp.
4. Resolve since_packet_id to generated_at and include the delta.
5. Return fallback warnings when the old packet is missing.
6. Add tests for since_packet_id success and missing/invalid packet IDs.
```

Delta rules:

```txt
1. since_packet_id resolves to generated_at and the old packet profile.
2. If the old packet profile differs from the requested profile, return
   profile_mismatch_delta warning and still generate the packet.
3. Snapshot metadata must include profile and tests must prove the profile is
   used during delta comparison.
4. Missing since_packet_id returns a warning and falls back to a full snapshot
   only when the caller explicitly allows fallback.
```

Done when:

```txt
The operator can ask another AI pass without making the model reread old state.
```

## P19-004 Packet Contract Standardization

Goal:

```txt
Make every outbound AI packet look familiar regardless of provider or delivery
path.
```

Contract sections:

```txt
1. packet_metadata
2. role_and_access_boundaries
3. operator_question
4. relevant_state
5. stale_context_suppression
6. output_contract
7. import_contract
8. task_template_contract
```

Contract field rules:

```txt
contract_version:
  Start with p19.v1. If a packet consumer sees an unsupported version, it must
  escalate instead of guessing.

role_and_access_boundaries:
  Summarize packet-local permissions in three lines or fewer:
  can read supplied packet state, can propose findings/tasks, cannot request or
  infer raw DB/filesystem/secrets/shell access.

stale_context_suppression:
  Default suppression is applied when the field is omitted. Empty arrays mean no
  additional custom suppression rules, not "disable defaults".

output_contract:
  Must include the requested output_mode, max findings, forbidden sections, and
  version-mismatch escalation rule.
```

Tasks:

```txt
1. Create a shared packet contract builder used by project snapshots,
   experiment packets, and provider fast-lane requests.
2. Keep Markdown copy-ready output and JSON machine-readable output in sync.
3. Ensure web/manual packets and API-key provider packets share the same
   boundaries and output contract.
4. Add contract_version to packet metadata.
5. Add tests that Gemini/DeepSeek/OpenAI-compatible provider requests include
   the same contract fields.
```

Done when:

```txt
Switching from Claude web copy-paste to Gemini or DeepSeek API does not change
the safety rules, output shape, or import expectations.
```

## P19-005 Short Output Contracts

Goal:

```txt
Make external AI answers shorter, narrower, and easier to import.
```

Tasks:

```txt
1. Add output modes:
   - decision_only
   - top_findings
   - implementation_candidates
   - provider_risk_check
2. Each mode defines max findings, required fields, and forbidden sections.
3. Prefer structured compact findings over long narrative reviews.
4. Add parser support for the compact output format.
5. Dry-run import should reject unsupported sections with actionable parser
   errors.
6. Add tests for compact parser success and noisy-response rejection.
```

Output mode rules:

```txt
decision_only:
  max_findings: 0
  output: allow/refuse/escalate with reason

top_findings:
  max_findings: 3
  output: import-ready Finding blocks only

implementation_candidates:
  max_findings: 1
  output: one candidate with expected files, verification hint, and confidence

provider_risk_check:
  max_findings: 3
  output: provider stability/speed/security risks only
```

Parser feedback rule:

```txt
Unsupported sections must be returned both to the operator and as
ai_feedback_prompt text that can be pasted or sent back to the provider for a
self-correction loop.
```

Done when:

```txt
DeepSeek/Gemini/Claude can answer a narrow question in a short format that
KnowNet can dry-run and import without manual cleanup.
```

## P19-006 Snapshot To Task Bridge

Goal:

```txt
Ask AI for implementation candidates, not just advice.
```

Tasks:

```txt
1. Add an implementation_candidates packet profile.
2. Include accepted findings, open finding tasks, recent implementation
   evidence, changed files from recent records, and target verification hints.
3. Ask the model for "one next implementation candidate" by default.
4. If the response imports as an accepted high-confidence finding, auto-create
   the Codex task using the existing task_template flow.
5. Keep auto task creation limited to direct_access/operator_verified AND high
   or critical severity findings.
6. Add tests proving context_limited findings do not become release blockers.
7. Add tests proving context_limited findings do not auto-create tasks.
```

Done when:

```txt
External AI output can naturally become the next Codex task without a second
human translation step.
```

## P19-007 Deferred Patch Suggestion API

Goal:

```txt
Prepare, but do not rush, a code-patch suggestion path.
```

Tasks:

```txt
1. Define the API contract for GET /api/collaboration/patch-suggestion.
2. Require finding_id and return unsupported_until_implemented for now.
3. Return a machine-readable safety_contract field:
   - requires_local_code_context: true
   - external_ai_raw_code_access: false
   - exposes_secrets: false
   - returns_unified_diff_only_after_operator_request: true
4. Leave real diff generation to a later phase after snapshot and packet
   contracts are stable.
```

Done when:

```txt
The future diff-generation idea is captured without pretending it is safe or
ready today.
```

## Acceptance Gate

Phase 19 is complete when all of these are true:

```txt
1. Project snapshots support profile-specific state selection.
2. Snapshot responses include quality warnings.
3. Delta snapshots can use since_packet_id.
4. Project snapshots, experiment packets, and provider fast-lane requests share
   one packet contract version.
5. External AI output can be constrained to short import-friendly modes.
6. The implementation_candidates profile can feed the existing next-action and
   task_template loop.
7. Targeted tests cover the packet contract, snapshot profiles, delta flow, and
   compact parser.
8. No full release_check is required for daily AI packet work.
```

## Working Theory

```txt
Markdown nodes remain useful as narrative source material, but KnowNet's
AI-collaboration value comes from converting that material into high-quality
structured snapshots and standardized packets.
```
