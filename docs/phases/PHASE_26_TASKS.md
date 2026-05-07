# Phase 26 Tasks: Compact External AI Packet

Status: implemented in the codebase on 2026-05-07
Created: 2026-05-07
Updated: 2026-05-07

Phase 26 exists because `PHASE_25_TASKS.md` is already implemented as
verification, ignore policy, and agent contract work. This phase captures the
next packet/snapshot task requested after the external AI reviews: make the
default AI handoff packet compact, fast to read, and directly useful for
importable findings.

The goal is not to add another enterprise contract layer. The goal is to cut the
current packet down to the small set of fields an external AI needs to:

```txt
1. understand the current KnowNet state,
2. know exactly what context is missing,
3. identify the highest-priority actionable signals,
4. ask short targeted follow-up questions,
5. return findings that KnowNet can import or review.
```

Reference review log:

```txt
docs/reviews/AI_PACKET_STANDARDIZATION_EXTERNAL_REVIEWS.md
```

Implemented surface:

```txt
- Project snapshot packets now emit compact JSON as the copy-ready content.
- Compact packets use contract_ref, contract_hash, packet_integrity, limits,
  compact health, and prioritized signals instead of full inline contract,
  contract_shape, snapshot_self_test, and Markdown/JSON duplication.
- Copy-ready packet content omits full snapshot_quality details; quality remains
  response metadata while packet_integrity carries compact size/budget status.
- required_context lives on the signal that needs it.
- max_findings and max_signals are separate effective limits.
- Empty/null scaffolding is omitted from compact packet content.
- Provider matrix and heavy detail are opt-in by profile.
- /api/schemas/packet/p26.v1 exposes the referenced packet schema.
```

Operator decision after external reviews:

```txt
1. 12,000 chars is the first target/warning line.
2. 8,000 chars is a second optimization target, not a hard requirement.
3. required_context and contract_ref are the fastest practical wins.
4. SARIF belongs in a later findings/tooling phase, not in Phase 26 packets.
5. CloudEvents, JSON-LD, and in-toto are out of scope until real consumers need
   them.
6. required_context should live on the signal that needs it, not as another
   detached top-level section.
```

## Fixed Rules

Do not:

- Add a new provider-specific packet schema.
- Add another full validation framework before the compact shape settles.
- Include full `snapshot_self_test` in compact AI-facing output.
- Expand MCP capabilities, prompts, sampling, logging, or provider surfaces just
  because a standard supports them.
- Put raw secrets, raw database files, backups, sessions, users, local paths,
  tokens, or admin material into any packet.
- Reintroduce Markdown/JSON duplication to make copy-paste output look nicer.
- Keep empty arrays, null fields, or zero-signal scaffolding in compact output.
- Remove the compact health summary entirely; `signals` does not replace all
  health state.
- Make compact packet generation depend on full release checks.

Do:

- Make the compact packet the default external AI handoff shape.
- Keep detailed/provider/debug views opt-in.
- Keep W3C trace context, role boundaries, evidence quality, and import
  guardrails.
- Prefer one canonical machine-readable JSON payload.
- Reference schemas, contracts, and tools instead of inlining their full bodies.
- Use standard names and shapes only where they reduce custom parsing.
- Keep the implementation small enough for a local-first project.

## P26-001 Per-Signal Required Context For Short Follow-Up Questions

Problem:

The current packet tells external AI what not to do, but it does not clearly
tell the AI what missing context would upgrade a weak finding into a stronger
one. This causes long, vague follow-up questions and encourages inference from
thin context.

This is the highest-priority Phase 26 task because it directly supports the
core workflow:

```txt
AI reads packet -> AI asks one short useful question -> operator supplies exact
context -> AI returns a stronger finding.
```

Implementation shape:

Add `required_context` to the specific `signal` that needs more context, not as
another detached top-level section:

```json
{
  "signals": [
    {
      "code": "provider.status_unverified",
      "severity": "medium",
      "action": "verify_provider_status",
      "description": "Provider state cannot be marked direct_access from this packet alone.",
      "required_context": {
        "missing": ["live_provider_status"],
        "ask_operator": "Provide live provider status before marking provider findings as direct_access."
      }
    }
  ]
}
```

Rules:

- Keep the list short and concrete.
- Use names the operator can provide or that KnowNet can expose.
- Pair per-signal `required_context` with `evidence_quality`.
- Do not add a second top-level `required_context` list unless it is a compact
  summary generated from the signal-level requirements.
- Do not let `context_limited` findings become release blockers unless the
  required context is later provided or operator-verified.

Done when:

- External AI can ask for missing context in one short targeted question.
- `context_limited` output includes what would make it stronger per signal.
- Import logic can distinguish finding proposals from context requests.

## P26-002 Contract Ref And Single Canonical Contract

Problem:

External reviews identified repeated contract definitions:

```txt
1. human-readable Packet Contract text
2. structured contract JSON
3. contract_shape metadata
```

This creates size bloat and version drift. Some packets also expose conflicting
limits, such as `max_findings` being `5` in one place and `3` in another.

Implementation shape:

- Keep one canonical contract object or referenced contract for compact JSON.
- Replace duplicated contract text with `contract_ref` and/or `contract_hash`.
- Remove `contract_shape` from compact AI-facing output.
- Remove full `snapshot_self_test` from compact AI-facing output.
- Replace it, only if needed, with a tiny `packet_integrity` summary.
- Keep human-readable contract documentation outside the compact packet.

Candidate compact shape:

```json
{
  "contract_ref": "/api/schemas/packet/p26.v1",
  "contract_hash": "sha256:...",
  "packet_integrity": {
    "status": "pass",
    "checks_passed": 10,
    "checked_at": "2026-05-07T00:00:00Z"
  }
}
```

Done when:

- Compact packet output has one effective contract source.
- Duplicated contract text is absent from compact output.
- Full `snapshot_self_test` is absent from compact output.
- `packet_integrity`, if present, is a short summary only.
- Human-readable contract documentation exists outside the compact packet.

## P26-003 Compact Health And Unified Signals

Problem:

Actionable context is currently scattered across multiple sections:

```txt
health
issues
next_action_hints
provider_matrix
release_summary
```

External AIs should not need to cross-reference several sections to find the
top action candidates. However, the entire `health` block should not disappear:
basic operational status remains useful outside `signals`.

Implementation shape:

Keep compact health as state:

```json
{
  "health": {
    "overall_status": "degraded",
    "degraded": true,
    "checked_at": "2026-05-07T00:00:00Z",
    "issue_codes": ["embedding.unavailable"]
  }
}
```

Add one compact, sorted priority queue named `signals` for actions:

```json
{
  "signals": [
    {
      "code": "embedding.unavailable",
      "severity": "expected_degraded",
      "action": null,
      "description": "Embedding is unavailable; keyword and FTS fallback should still work."
    },
    {
      "code": "health.degraded",
      "severity": "medium",
      "action": "inspect_health_issue",
      "params": {},
      "required_context": {
        "missing": ["health_issue_details"],
        "ask_operator": "Provide health issue details if this signal should become a finding."
      }
    }
  ]
}
```

Rules:

- `severity` and `action` must be top-level fields on each signal.
- Sort `signals` by severity and actionability:
  `critical`, `high`, `medium`, `low`, `expected_degraded`.
- Cap `signals` with an explicit `max_signals`; do not reuse `max_findings`
  unless the effective values are intentionally equal.
- Prefer `code`, `severity`, `action`, `params`, and one-line `description`.
- Allow per-signal `required_context` where the next AI question should be
  short and targeted.
- Use RFC 9457 Problem Details shape later only if it reduces custom parsing.
- Keep detailed health and provider data in opt-in profiles.

Done when:

- Compact overview exposes one prioritized signal queue.
- Health/provider/action hints no longer need to be read from several sections.
- Compact health remains available for state, while `signals` carries action.
- Signal objects are short enough for AI scanning and stable enough for import
  tooling.

## P26-004 Single Effective Limits

Problem:

Current packets can expose multiple limit sources:

```txt
hard_limits
profile_hard_limits
target_agent_overrides
target_agent_policy
output_contract.max_findings
```

If these conflict, external AI cannot know which value to obey.

Implementation shape:

Expose one effective `limits` object in compact output:

```json
{
  "limits": {
    "max_findings": 3,
    "max_signals": 5,
    "max_important_changes": 8,
    "char_budget": 12000,
    "optimization_target_chars": 8000
  }
}
```

Rules:

- Internal profile or target-agent overrides may still exist.
- Compact output should show only the final effective values.
- `max_findings` and `max_signals` are separate unless intentionally equal:
  findings are import candidates, signals are attention/action candidates.
- If override precedence matters, document it outside the packet or expose a
  one-line `limits_source` field.

Done when:

- `max_findings`, char budget, and output mode do not conflict across fields.
- `max_signals` is present and does not conflict with `max_findings`.
- Compact output contains one effective `limits` object.
- Override precedence is documented and tested, not guessed by the AI.

## P26-005 Compact Overview Budget

Problem:

External AI reviewers repeatedly flagged the default overview packet as too
large:

```txt
observed size: 20,468 chars
first target / warning line: 12,000 chars
second optimization target: 8,000 chars
```

Implementation shape:

- Keep `overview` as the default external AI profile.
- Treat `12,000` chars as the first practical target and warning threshold.
- Treat `8,000` chars as an optimization target after `required_context`,
  `contract_ref`, `packet_integrity`, `signals`, and `limits` are in place.
- Move provider, MCP schema, and diagnostic detail into opt-in profiles.
- Emit `oversized_packet` only as a quality warning; do not silently truncate.

Done when:

- The default overview packet is designed to fit under 12,000 chars.
- The packet reports whether it is near the 8,000 char optimization target.
- Oversized packets explain which sections caused the size overrun.
- Provider/detail profiles can still include richer context on request.

## P26-006 Opt-In Detail Profiles And Schema References

Problem:

Inline schemas and provider matrices make the overview packet heavy. Reviewers
recommended moving detail into schema/resource references and opt-in profiles.

Implementation shape:

- Keep only method/resource names in compact overview for MCP surfaces.
- Move full `inputSchema` and contract definitions to referenced schema
  endpoints or files.
- Prefer resolvable relative API paths or MCP-native resource paths over
  custom-only URI schemes when possible.
- Keep provider details in `provider_review` or detail profiles, not overview.

Candidate references:

```txt
/api/schemas/packet/p26.v1
/api/schemas/actions/v1
/api/mcp/resources
/api/mcp/tools
```

Done when:

- Compact overview does not inline full tool/action schemas.
- Detailed schema content remains discoverable through explicit references.
- Provider matrix is absent from overview unless the operator asks for provider
  review.

## P26-007 Standard Alignment Without New Weight

Problem:

External reviews suggested several standards: MCP, W3C Trace Context,
OpenAPI 3.1, JSON Schema, RFC 9457 Problem Details, SARIF, CloudEvents,
JSON-LD, in-toto, and others. Absorbing all of them at once would recreate the
overbuilt problem.

Implementation shape:

Use standards only where they replace custom parsing or reduce explanation:

- Keep W3C `traceparent`.
- Keep MCP terminology and resource/tool shapes.
- Prefer OpenAPI/JSON Schema references for tool schemas, not inline bodies.
- Use compact `signals` in overview; consider RFC 9457 only in detail/API
  paths if it stays compact.
- Keep SARIF for a later findings/tooling phase, likely export-first.
- Do not add JSON-LD, in-toto, CloudEvents, or extended sampling unless a real
  consumer needs them.

Done when:

- The compact packet uses fewer custom concepts than before.
- Any adopted standard makes the packet smaller or easier for AI/Codex to use.
- Standards do not add new mandatory sections to overview.

## Acceptance

```txt
1. Per-signal required_context helps external AI ask shorter follow-up
   questions.
2. Compact overview packet is the default external AI handoff shape.
3. Compact overview is designed for 12,000 chars first, with 8,000 chars as an
   optimization target.
4. Packet has one canonical contract reference and one effective limits object.
5. Empty/null scaffolding and full snapshot_self_test are absent from compact
   output; packet_integrity is short if present.
6. Health remains compact state, while actionable items use one prioritized
   signals queue with separate max_signals.
7. Provider matrix, full schemas, and detailed diagnostics are opt-in.
8. Role boundaries, evidence_quality, W3C trace context, and import guardrails
   remain intact.
```

## Suggested Implementation Order

```txt
P26-001 Per-Signal Required Context
P26-002 Contract Ref And Single Canonical Contract
P26-003 Compact Health And Unified Signals
P26-004 Single Effective Limits
P26-005 Compact Overview Budget
P26-006 Opt-In Detail Profiles And Schema References
P26-007 Standard Alignment Without New Weight
```

## Out Of Scope

```txt
- Full MCP server redesign
- Provider runner changes
- SARIF import/export implementation
- OpenAPI client generation
- JSON-LD, CloudEvents, or in-toto provenance
- UI redesign beyond exposing compact packet generation if needed later
- Full release_check
```
