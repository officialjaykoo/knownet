# Phase 20 Tasks: Machine-Enforceable Packet Standardization

Phase 20 turns the Phase 19 packet contract into a stricter implementation
surface:

```txt
One packet shape, all providers. Machine-enforceable boundaries. Explicit stale
context rules. Size budgets. Import tests before model comparison.
```

Phase 19 established profile-specific snapshots, `p19.v1` packet contracts,
quality warnings, delta context, compact parsing, and project snapshot metadata.
Phase 20 should standardize those pieces so Claude, Codex, Gemini, DeepSeek,
and future providers receive the same contract shape and produce comparable
responses.

Implementation status: partially implemented in the codebase on 2026-05-05.

Implemented surface:

```txt
1. Contract version advanced to p20.v1 for project snapshots, experiment
   packets, and provider fast-lane contexts.
2. role_and_access_boundaries is now structured as allowed/refused/escalate_on,
   with a generated narrative of three lines or fewer.
3. stale_context_suppression now uses the explicit active=true/active=false
   schema in generated contracts.
4. Profile char budgets are defined and oversized packets emit
   oversized_packet through snapshot_quality instead of silent truncation.
5. snapshot_self_test validates structured boundaries and explicit stale
   suppression, while treating size budget as advisory quality metadata.
6. target_agent_policy is reflected in contract hard_limits through
   target_agent_overrides.
7. source_agent-based evidence_quality inference was removed from schema
   migration; missing quality remains unspecified unless explicitly provided.
8. import_contract includes auto-task requirements, unsupported section
   behavior, and partial-match behavior.
9. A reusable contract_shape/validate_packet_contract path verifies generated
   packet contracts before outbound project snapshot, experiment, and provider
   fast-lane use.
10. Experiment response dry-runs now report import_ready, rejection_reason, and
    ai_feedback_prompt so unsupported sections are actionable instead of
    silently importable.
11. The same p20.v1 contract shape is tested across project snapshot and
    experiment packet generation, with Claude/Gemini-style compact responses
    using the same parser path.
12. packet_schema_version is exposed as a p20.v1 alias for consumers that expect
    schema naming rather than contract naming.
13. Project snapshot packets include packet_summary with minimal
    finding/task/model_run objects and detail_url links.
14. Project snapshot packets include issues with code, action_template, and
    action_params so external AI can propose executable next steps faster.
15. Project snapshot and provider fast-lane packets include ai_context and
    next_action_hints/read_order guidance for shorter prompts.
16. Experiment packets expose standardized node_cards while keeping inline
    excerpts available for the selected nodes.
17. Read detail endpoints exist for findings and finding tasks so summary
    objects can point to durable detail_url targets.
18. Delta packets expose delta_summary with changed node, finding, task, model
    run, and failed-run counts at the top level and inside the delta payload.
19. Project snapshot packets now include lightweight node_cards for recent or
    delta-changed nodes instead of leaving node context empty.
```

Remaining work:

```txt
1. Add dedicated dry-run fixtures for every output_mode, not only the shared
   top_findings compact path.
2. Surface malformed p20.v1 packet validation errors in operator UI if packet
   controls are touched.
```

## Preflight Gate

Do not start Phase 20 unless these Phase 19 foundations are true:

```txt
1. Project snapshot profiles exist and are tested.
2. Project snapshots, experiment packets, and provider fast-lane contexts carry
   contract_version p19.v1.
3. snapshot_quality exists and is advisory/visible.
4. since_packet_id works and profile mismatch emits a warning.
5. compact JSON review parsing produces importable findings or
   ai_feedback_prompt errors.
6. context_limited findings cannot auto-create tasks or block releases.
```

If any item is false, Phase 20 would standardize on a broken foundation.

## Fixed Rules

```txt
Do not:
  Add raw database, shell, filesystem, token, backup, .env, or secret access to
  any packet.
  Create provider-specific packet schemas.
  Allow context_limited findings to auto-create tasks or block releases.
  Make full release_check a dependency of daily packet generation.
  Let packet size grow unbounded.
  Add new access roles or rewrite Access Tier Definition.
  Touch real patch suggestion diff generation.

Do:
  Use contract_version in every outbound packet.
  Enforce role_and_access_boundaries as three narrative lines or fewer.
  Generate those narrative lines from structured boundaries.
  Require evidence_quality on every importable finding.
  Make compact output the default and verbose output opt-in.
  Reject packets with missing stale_context_suppression.
  Emit oversized_packet when profile budgets are exceeded.
```

## Dependency Order

```txt
P19-004 contract stable
  -> P20-001 structured role_and_access_boundaries
  -> P20-002 packet size budgets per profile
  -> P20-003 explicit stale_context_suppression schema
  -> P20-004 import contract end-to-end tests
  -> P20-005 one packet shape verified across 2+ providers
```

Do not skip this order. Later steps amplify earlier ambiguity.

## P20-001 Structured Role And Access Boundaries

Goal:

```txt
Make packet access boundaries machine-enforceable instead of narrative-only.
```

Authoritative shape:

```json
{
  "role_and_access_boundaries": {
    "allowed": ["read_packet_state", "write_findings_draft", "propose_tasks"],
    "refused": ["admin_token", "raw_db", "shell", "secrets", "snapshot_delete"],
    "escalate_on": ["system_state_assertion", "unverified_live_claim", "role_boundary_ambiguity"]
  }
}
```

Tasks:

```txt
1. Replace manual role boundary arrays in packet_contract.py with structured
   allowed/refused/escalate_on fields.
2. Generate the existing three-line narrative summary from the structured
   source.
3. Keep the narrative summary to three lines or fewer.
4. Add packet_self_test checks for missing/empty allowed/refused/escalate_on.
5. Add tests proving the structured form generates the expected narrative.
```

Done when:

```txt
Every outbound packet has one authoritative structured boundary object and a
generated human-readable summary.
```

## P20-002 Packet Size Budgets Per Profile

Goal:

```txt
Keep profile packets bounded without silent truncation.
```

Starting budgets:

| profile | max tokens | max chars |
| --- | ---: | ---: |
| overview | 3000 | 12000 |
| stability | 2000 | 8000 |
| security | 2000 | 8000 |
| performance | 2000 | 8000 |
| implementation | 2500 | 10000 |
| provider_review | 1500 | 6000 |

Tasks:

```txt
1. Add profile_budget to packet_contract.py or project_snapshot.py.
2. Include budget metadata in snapshot JSON.
3. Estimate packet tokens with the existing model-runner token estimator or a
   shared lightweight estimator.
4. If size exceeds budget, emit oversized_packet with observed and max size.
5. Do not silently truncate. The operator decides whether to send/copy.
6. Add tests for budget warnings per profile.
```

Done when:

```txt
Every project snapshot reports whether it fits the profile budget, and oversized
packets are visible before provider calls or web-chat copy.
```

## P20-003 Explicit Stale Context Suppression

Goal:

```txt
Remove implicit stale suppression defaults from packet contracts.
```

Valid states:

```json
{
  "stale_context_suppression": {
    "active": true,
    "suppressed_before": "2026-05-05T00:00:00Z",
    "reason": "delta packet; prior state excluded"
  }
}
```

or:

```json
{
  "stale_context_suppression": {
    "active": false
  }
}
```

Tasks:

```txt
1. Replace default_applied/custom_rules with explicit active schema.
2. For since/since_packet_id packets, set active=true and suppressed_before to
   the resolved timestamp.
3. For full snapshots, set active=false.
4. Packet self-test rejects missing, empty, or mixed-form suppression fields.
5. Add tests for active=true, active=false, and empty-field rejection.
```

Done when:

```txt
No packet can leave KnowNet with ambiguous stale context semantics.
```

## P20-004 Import Contract End-To-End Tests

Goal:

```txt
Prove the contract can produce importable or actionable parser errors before it
is used for model comparison.
```

Import contract must define:

```txt
accepted finding fields
allowed evidence_quality values
required evidence_quality values for auto task creation
sections that cause dry-run rejection
partial match behavior: warn or reject
ai_feedback_prompt behavior for self-correction
```

Tasks:

```txt
1. Expand import_contract in packet_contract.py with the fields above.
2. Add dry-run fixtures for each output_mode:
   decision_only
   top_findings
   implementation_candidates
   provider_risk_check
3. Verify valid compact outputs pass dry-run.
4. Verify unsupported/noisy sections return actionable parser errors and
   ai_feedback_prompt.
5. Verify context_limited findings do not auto-create tasks.
```

Done when:

```txt
Every supported output_mode has a parser test before provider comparison starts.
```

## P20-005 One Packet Shape Across Providers

Goal:

```txt
Make provider comparisons about model behavior, not packet format differences.
```

Tasks:

```txt
1. Ensure project snapshots, experiment packets, Gemini fast-lane, DeepSeek, and
   OpenAI-compatible provider contexts all include the same eight contract
   sections.
2. Add a contract_shape validator helper.
3. Add tests that at least two provider request contexts deserialize into the
   same contract section set.
4. Do not add provider-specific fields outside provider request metadata.
5. Keep provider quirks in prompts/adapters, not in the packet contract.
```

Done when:

```txt
The same packet contract can be sent to two providers and both responses can be
dry-run parsed without provider-specific parser branches.
```

## Required Tests

Phase 20 must include targeted tests for:

```txt
1. Same packet contract shape across at least two provider contexts.
2. oversized_packet warning when a profile budget is exceeded.
3. context_limited finding does not auto-import or auto-create a task without
   operator_verified/direct_access.
4. stale_context_suppression empty field causes packet self-test failure.
5. Structured role_and_access_boundaries generates the correct three-line
   narrative.
6. contract_version mismatch triggers an escalation instruction in
   output_contract.
7. Dry-run import rejects unsupported sections with ai_feedback_prompt.
8. Delta packet with profile mismatch emits profile_mismatch_delta warning.
```

## What Phase 20 Should Not Do

```txt
Do not expand access roles.
Do not create provider-specific packet schemas.
Do not implement patch suggestion diff generation.
Do not require release_check for daily packet work.
Do not make quality warnings hard blockers except for malformed packet contract
self-tests.
```

## Acceptance Gate

Phase 20 is complete when all of these are true:

```txt
1. role_and_access_boundaries is structured and narrative is generated.
2. Every profile has enforced budget warnings.
3. stale_context_suppression has exactly two valid explicit states.
4. import_contract is detailed enough for dry-run fixtures.
5. At least two provider request contexts share the same contract shape.
6. Packet self-test catches malformed boundaries, stale suppression, missing
   contract_version, and missing output_contract.
7. Targeted API tests pass.
8. Web build passes if UI packet controls are touched.
```

## One-Line Summary

```txt
Phase 20 standardizes the packet contract from P19 into a machine-enforceable,
provider-agnostic, size-budgeted, import-testable shape.
```
