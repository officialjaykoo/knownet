# Phase 26 Tasks: Compact External AI Packet

Status: planned
Created: 2026-05-07

Phase 26 exists because `PHASE_25_TASKS.md` is already implemented as
verification, ignore policy, and agent contract work. This phase captures the
next packet/snapshot task requested after the external AI reviews: make the
default AI handoff packet compact, fast to read, and directly useful for
importable findings.

The goal is not to add another enterprise contract layer. The goal is to cut the
current packet down to the small set of fields an external AI needs to:

```txt
1. understand the current KnowNet state,
2. identify the highest-priority actionable signals,
3. ask short targeted follow-up questions when context is missing,
4. return findings that KnowNet can import or review.
```

Reference review log:

```txt
docs/reviews/AI_PACKET_STANDARDIZATION_EXTERNAL_REVIEWS.md
```

## Fixed Rules

Do not:

- Add a new provider-specific packet schema.
- Add another full validation framework before the compact shape settles.
- Expand MCP capabilities, prompts, sampling, logging, or provider surfaces just
  because a standard supports them.
- Put raw secrets, raw database files, backups, sessions, users, local paths,
  tokens, or admin material into any packet.
- Reintroduce Markdown/JSON duplication to make copy-paste output look nicer.
- Keep empty arrays, null fields, or zero-signal scaffolding in compact output.
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

## P26-001 Compact Overview Budget

Problem:

External AI reviewers repeatedly flagged the default overview packet as too
large:

```txt
observed size: 20,468 chars
current budget: 12,000 chars
recommended compact target: 8,000-12,000 chars
```

Implementation shape:

- Keep `overview` as the default external AI profile.
- Set a compact target budget, preferably `8,000` chars for generated handoff
  text and `12,000` chars as a warning threshold while tuning.
- Move provider, MCP schema, and diagnostic detail into opt-in profiles.
- Emit `oversized_packet` only as a quality warning; do not silently truncate.

Done when:

- The default overview packet is designed to fit under the compact target.
- Oversized packets explain which sections caused the size overrun.
- Provider/detail profiles can still include richer context on request.

## P26-002 Single Canonical Contract

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

- Keep one canonical contract object in compact JSON.
- Replace duplicated contract text with `contract_ref` and/or `contract_hash`.
- Remove `contract_shape` from compact AI-facing output.
- Consolidate `hard_limits`, `profile_hard_limits`, `target_agent_policy`, and
  `target_agent_overrides` into one `limits` object with explicit profile and
  target-agent values.
- Keep `max_findings` as one effective value in the compact packet.

Done when:

- Compact packet output has one effective contract source.
- `max_findings`, char budget, and output mode do not conflict across fields.
- Human-readable contract documentation exists outside the compact packet.

## P26-003 Strip Zero-Signal Scaffolding

Problem:

Reviewers repeatedly called out empty/null fields that cost tokens without
adding context:

```txt
delta: null
since_packet: null
node_cards: []
source_manifest.sources: []
accepted_findings: []
important_changes: {}
do_not_reopen: {}
snapshot_self_test
```

Implementation shape:

- Omit empty arrays, null values, empty objects, and falsey scaffolding from
  compact packet output.
- Move `snapshot_self_test` and quality/self-validation detail to a validation
  endpoint, server log, or stored packet metadata.
- Keep only compact quality warnings that change how the AI should interpret
  the packet.

Done when:

- Compact packet output contains no empty/null scaffolding.
- `snapshot_self_test` is not in AI-facing compact output.
- Internal validation remains available outside the compact packet.

## P26-004 Unified Signals Array

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
top action candidates.

Implementation shape:

Add one compact, sorted `signals` array:

```json
{
  "signals": [
    {
      "code": "health.degraded",
      "severity": "medium",
      "action": "inspect_health_issue",
      "params": {},
      "description": "Health is degraded because embedding is unavailable."
    }
  ]
}
```

Rules:

- Cap `signals` at the effective `max_findings` or another explicit compact
  signal limit.
- Prefer `code`, `severity`, `action`, `params`, and one-line `description`.
- Use RFC 9457 Problem Details shape later only if it reduces custom parsing.
- Keep detailed health and provider data in opt-in profiles.

Done when:

- Compact overview exposes one prioritized action stream.
- Health/provider/action hints no longer need to be read from several sections.
- Signal objects are short enough for AI scanning and stable enough for import
  tooling.

## P26-005 Opt-In Detail Profiles And Schema References

Problem:

Inline schemas and provider matrices make the overview packet heavy. Reviewers
recommended moving detail into schema/resource references and opt-in profiles.

Implementation shape:

- Keep only method/resource names in compact overview for MCP surfaces.
- Move full `inputSchema` and contract definitions to referenced schema
  endpoints or files.
- Prefer resolvable HTTP(S), relative API paths, or MCP-native resource paths
  over custom-only URI schemes when possible.
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

## P26-006 Required Context For Short Follow-Up Questions

Problem:

The current packet tells external AI what not to do, but it does not clearly
tell the AI what missing context would upgrade a weak finding into a stronger
one. This causes long, vague follow-up questions.

Implementation shape:

Add `required_context` to the output contract or compact packet:

```json
{
  "required_context": [
    "node_card_excerpts",
    "live_provider_status",
    "specific finding ids"
  ]
}
```

Rules:

- Keep the list short.
- Use concrete names that the operator can provide or request from KnowNet.
- Pair `required_context` with `evidence_quality` so context-limited reviews do
  not become release blockers without stronger evidence.

Done when:

- External AI can ask for missing context in one short targeted question.
- `context_limited` output includes what would make it stronger.
- Import logic can distinguish finding proposals from context requests.

## P26-007 Standard Alignment Without New Weight

Problem:

External reviews suggested several standards: MCP, W3C Trace Context,
OpenAPI 3.1, JSON Schema, RFC 9457 Problem Details, SARIF, CloudEvents, and
others. Absorbing all of them at once would recreate the overbuilt problem.

Implementation shape:

Use standards only where they replace custom parsing or reduce explanation:

- Keep W3C `traceparent`.
- Keep MCP terminology and resource/tool shapes.
- Prefer OpenAPI/JSON Schema references for tool schemas, not inline bodies.
- Consider RFC 9457 for issue-like `signals` only after the compact shape is
  stable.
- Consider SARIF mapping for importable findings after the compact finding
  shape is proven.
- Do not add JSON-LD, in-toto, CloudEvents, or extended sampling unless a real
  consumer needs them.

Done when:

- The compact packet uses fewer custom concepts than before.
- Any adopted standard makes the packet smaller or easier for AI/Codex to use.
- Standards do not add new mandatory sections to overview.

## Acceptance

```txt
1. Compact overview packet is the default external AI handoff shape.
2. Compact overview is designed for 8,000-12,000 chars, with warnings when over.
3. Packet has one canonical contract and one effective limits object.
4. Empty/null scaffolding and snapshot_self_test are absent from compact output.
5. Actionable state is available through one prioritized signals array.
6. Provider matrix, full schemas, and detailed diagnostics are opt-in.
7. required_context helps external AI ask shorter follow-up questions.
8. Role boundaries, evidence_quality, W3C trace context, and import guardrails
   remain intact.
```

## Suggested Implementation Order

```txt
P26-002 Single Canonical Contract
P26-003 Strip Zero-Signal Scaffolding
P26-001 Compact Overview Budget
P26-004 Unified Signals Array
P26-005 Opt-In Detail Profiles And Schema References
P26-006 Required Context
P26-007 Standard Alignment Without New Weight
```

## Out Of Scope

```txt
- Full MCP server redesign
- Provider runner changes
- SARIF import/export implementation
- OpenAPI client generation
- JSON-LD or in-toto provenance
- UI redesign beyond exposing compact packet generation if needed later
- Full release_check
```
