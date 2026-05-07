# AI Packet Standardization External Reviews

This document records external AI feedback on KnowNet packet and snapshot
standardization. It is a review log only. Do not treat entries here as
implementation decisions until an operator accepts them into a phase or task.

## 2026-05-06 Claude Review

Reviewer: Claude  
Focus: packet/snapshot standardization review  
Score: 62/100  
Verdict: overbuilt

### Summary

Claude judged the current packet direction as useful but too large for fast
external AI review. The strongest criticism is that packet bodies include too
much internal contract and diagnostic detail inline, increasing token cost and
making the useful review context harder to find.

### Top 5 Recommended Changes

1. Shrink packet size immediately.

   The `overview` profile budget is 12,000 characters, while the observed
   packet was 20,468 characters. Claude identified the inline `contract`
   section as the largest avoidable duplicate. Recommended replacement:

   ```json
   {
     "contract_ref": "knownet://schemas/packet/p20.v1"
   }
   ```

2. Remove `snapshot_self_test` from AI-facing packet bodies.

   Claude considers this internal verification output. It should live in server
   logs or health/maintenance endpoints rather than in the packet an external AI
   reads.

3. Simplify `issues`.

   Current issue entries include inline `action_input_schema` JSON Schema.
   Claude recommends a compact shape:

   ```json
   {
     "code": "health.degraded",
     "severity": "medium",
     "action": "inspect_health_issue"
   }
   ```

4. Remove duplicated `provider_matrix`.

   Claude observed the same provider data in `release_summary.provider_matrix`
   and top-level `provider_matrix`. Keep one representation only.

5. Shrink the `health` block.

   Blocks like `health.api_detail`, `health.rust_daemon_detail`, and
   `health.sqlite_detail` only contain `{"status": "ok"}` when healthy. Claude
   recommends omitting normal details and including detail blocks only when
   abnormal.

### Do Not Change

- Keep W3C `traceparent`; it is standard and useful.
- Keep the 4-level `evidence_quality` distinction.
- Keep `do_not_suggest`; it helps steer model behavior.
- Keep `read_order`; it is low-cost and useful.
- Keep `search_index_status`; it is compact and clear.

### Open Source / Standard Patterns To Absorb

| Current Pattern | Suggested Pattern |
| --- | --- |
| Inline custom contract schema | JSON Schema `$ref` with external URI |
| Custom issue shape | RFC 9457 Problem Details |
| W3C `traceparent` | Keep |
| Custom `evidence_quality` enum | Keep, no clear standard alternative |

Problem Details example:

```json
{
  "type": "knownet://problems/health-degraded",
  "title": "Health Degraded",
  "status": 503,
  "detail": "embedding.unavailable"
}
```

### Codex Notes

This feedback is credible because it targets token cost, duplicated packet
fields, and AI-readable signal density. It should not be applied immediately
without comparing with other model reviews, because removing inline contract
content may reduce copy-paste portability unless `contract_ref` content is
also available in the handoff prompt or MCP resource set.

Potential follow-up task after more reviews:

```txt
Create a compact packet profile that replaces inline contract and schema-heavy
issue details with references while preserving enough context for copy-paste
external AI review.
```

## 2026-05-07 Gemini Review

Reviewer: Gemini  
Focus: packet/snapshot standardization review  
Score: 65/100  
Verdict: overbuilt

### Summary

Gemini agreed with Claude that the packet is overbuilt. Its main criticism is
that KnowNet is still sending a large monolithic hybrid packet instead of using
separate standard context and action surfaces. Gemini was more direct than
Claude about preferring strict MCP resources/tools over a custom packet wrapper.

### Top 5 Recommended Changes

1. Eliminate Markdown/JSON duplication.

   Gemini observed that the packet duplicates most important content between
   narrative Markdown sections and the `## Machine Readable JSON` block. This is
   a direct cause of the `oversized_packet` warning:

   ```txt
   20,468 > 12,000 chars
   ```

   Recommendation: pick one primary format for AI review instead of shipping the
   same capability, contract, and summary data twice.

2. Drop empty structures.

   Omit empty arrays and empty/null blocks entirely. Examples:

   ```json
   {
     "node_cards": [],
     "accepted_findings": [],
     "source_manifest": {
       "sources": []
     }
   }
   ```

   These fields preserve schema shape but add no context for the reviewing AI.

3. Remove internal telemetry.

   Gemini recommends stripping OpenTelemetry/W3C trace context from AI-facing
   packets:

   ```txt
   trace_id
   span_id
   span_kind
   attributes
   ```

   Gemini's view differs from Claude here. Claude recommended keeping W3C
   `traceparent`; Gemini says external LLMs do not need APM routing data.

4. Remove meta-diagnostics.

   Delete `snapshot_self_test` from the payload. Gemini agrees with Claude that
   external AIs do not need internal packet unit-test results such as checks for
   section headers.

5. Deduplicate action schemas.

   `issues[*].action_input_schema` duplicates schemas that belong in tool
   definitions. Gemini recommends referencing only the action/tool name, for
   example:

   ```txt
   triage_ai_state_failures
   ```

   The AI should rely on the primary tool definition or MCP tool schema instead.

### Do Not Change

- Keep `Role And Access Boundaries`.
- Keep explicit `Output Contract` rules.

Gemini called these guardrails excellent and deterministic because they reduce
hallucinated access requests and unauthorized system assumptions.

### Open Source / Standard Patterns To Absorb

Gemini recommends absorbing the official Model Context Protocol strictly:

- Use MCP `resources` for state and node context.
- Use MCP `tools` for actions.
- Stop relying on a custom monolithic `knownet://schemas/packet/p20.v1` hybrid
  wrapper as the primary external AI interface.

### Codex Notes

Gemini reinforces the same core signal as Claude: packet size and duplication
are the immediate problem. The strongest shared recommendation is to remove
duplicated narrative/JSON payload content, `snapshot_self_test`, and inline
action schemas.

The main disagreement is telemetry:

- Claude: keep W3C `traceparent`.
- Gemini: remove trace telemetry from AI-facing packets.

Codex recommendation after two reviews: keep trace identifiers in stored packet
metadata, but consider removing or greatly shortening them in copy-paste
external AI packet text. This preserves auditability without spending external
AI context budget on telemetry.

## Cross-Review Synthesis

Common findings from Claude and Gemini:

1. The packet is too large and overbuilt.
2. Markdown/JSON or contract duplication should be reduced.
3. `snapshot_self_test` should not be in AI-facing packet text.
4. Inline action schemas are too heavy for external review.
5. Guardrails should remain explicit.

Likely next implementation direction:

```txt
Create a compact external-AI packet mode:
- one primary readable format
- no empty structures
- no snapshot_self_test
- no inline action_input_schema
- no duplicated provider_matrix
- schema/tool references instead of schema bodies
- role/access/output guardrails preserved
```

Open question:

```txt
Should copy-paste packets keep a small trace reference, or should trace data
exist only in stored packet metadata and MCP/API responses?
```
