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

## 2026-05-07 DeepSeek Review

Reviewer: DeepSeek  
Focus: packet/snapshot standardization review  
Score: 65/100  
Verdict: overbuilt

### Summary

DeepSeek also rated the packet as overbuilt. Its recommendations overlap
strongly with Claude and Gemini: remove duplicated human/machine-readable
content, move validation out of the packet, simplify health, and reference
schemas instead of embedding them.

### Top 5 Recommended Changes

1. Collapse human-readable/machine-readable duplication.

   DeepSeek recommends a single compact JSON payload and removing top-level text
   blocks. Its position is stronger than Claude's: instead of keeping Markdown
   plus references, DeepSeek prefers one compact machine-readable packet format.

2. Unify `max_findings`.

   Use a single value, for example `5`, across:

   ```txt
   output_contract
   hard_limits
   profile_hard_limits
   ```

   This avoids conflicting limits inside the same packet contract.

3. Strip `health` to minimal fields.

   Keep only:

   ```txt
   overall_status
   short reasons array
   degraded flag
   ```

   Remove per-service details from the AI-facing snapshot packet.

4. Reference MCP tool input schemas.

   Move MCP tool input schemas to referenced JSON Schema URIs instead of
   inlining full definitions. Keep only required fields and short descriptions
   inline.

5. Move self-test/quality blocks out of the packet.

   Replace embedded `snapshot_self_test` and quality blocks with a separate
   validation endpoint or pre-generation check.

### Do Not Change

- Keep W3C trace context integration.
- Keep MCP alignment.
- Keep output/import contracts.
- Keep `node_card_contract`.
- Keep role boundaries.

DeepSeek agrees with Claude that trace context is valuable, which conflicts
with Gemini's recommendation to remove telemetry from AI-facing packets.

### Open Source / Standard Patterns To Absorb

Use a single JSON Schema document as the sole source of truth for packet
structure and validation:

```txt
knownet://schemas/packet/p20.v1
```

Do not put schema checks inside every packet. For tool input shapes, reference
standard JSON Schema definitions that external AI and Codex can consume without
parsing the whole packet.

### Codex Notes

DeepSeek creates a stronger consensus around JSON Schema references. After
three reviews, schema bodies and validation diagnostics inside the packet look
clearly too heavy. The remaining design question is not whether to compact the
packet, but what the copy-paste handoff format should be:

- compact JSON only
- compact Markdown with JSON references
- MCP resources/tools as the primary path, with copy-paste as fallback

## 2026-05-07 Qwen Review

Reviewer: Qwen  
Focus: packet/snapshot standardization review  
Score: 72/100  
Verdict: enough for now, but trim for speed

### Summary

Qwen gave the most positive review so far. It judged the packet's structural
bones as sound for AI consumption, especially contracts, boundaries, and trace
context. Its criticism is still about speed: 20 KB packet size against a 12 KB
budget, nested duplication, and optional schema details that should be stripped
from a compact profile.

### Top 5 Recommended Changes

1. Deduplicate metadata.

   Keep packet identity fields in one top-level location only:

   ```txt
   contract_version
   protocol_version
   schema_ref
   ```

   Remove repeated copies inside `contract.packet_metadata` and
   `contract_shape`.

2. Consolidate limits.

   Merge these objects into one `limits` object keyed by `profile` and
   `target_agent`:

   ```txt
   hard_limits
   profile_hard_limits
   target_agent_overrides
   target_agent_policy
   ```

3. Make MCP schemas profile-conditional.

   For the `overview` profile, include only MCP method names. Move full
   resource/tool/prompt `inputSchema` definitions to a separate `/schemas`
   endpoint referenced by URI.

4. Remove dual-format duplication.

   When `output_mode=top_findings`, drop the human-readable Markdown header and
   keep only machine-readable JSON, or reduce the header to a 3-line summary
   that references the JSON payload.

5. Simplify `issues` for overview.

   Keep only:

   ```txt
   code
   severity
   one-line description
   ```

   Move `action_input_schema` to a referenced schema document such as:

   ```txt
   knownet://schemas/actions/v1
   ```

### Do Not Change

- Keep W3C trace context structure: `traceparent`, `trace_id`, `span_id`.
- Keep role boundaries: `allowed`, `refused`, `escalate_on`, and narrative.
- Keep output contract `max_findings` and `forbidden_sections` guardrails.
- Keep `Do Not Suggest` content and placement.
- Keep `evidence_quality` enum values and `auto_import_requires` logic.
- Keep node card `read_rules`: short summary first, scoped `detail_url`, and
  optional excerpt.

### Open Source / Standard Patterns To Absorb

Qwen recommended several standards:

- CloudEvents: align packet envelope fields such as `id`, `type`, `source`,
  `time`, and `datacontenttype`.
- RFC 7807 Problem Details: use `type`, `title`, `status`, `detail`, and
  `instance` for issue/problem shapes.
- OpenAPI 3.1 Schema Object with `$defs`: reference shared schema definitions
  for tool `inputSchema`.
- JSON Merge Patch (RFC 7396): use a standard diff format for
  `snapshot_diff_summary`.
- MCP Schema Registry pattern: register `knownet://schemas/*` with the MCP
  schema catalog rather than maintaining an isolated custom URI convention.

### Codex Notes

Qwen shifts the score upward, but not the direction. Its message is: the packet
is structurally good enough, but the default external handoff should be compact.
It also gives the clearest envelope recommendation so far: CloudEvents for
packet identity and event-style interoperability.

Qwen strongly supports keeping trace context and guardrails, aligning with
Claude and DeepSeek against Gemini on telemetry removal.

## 2026-05-07 Kimi Review

Reviewer: Kimi  
Focus: packet/snapshot standardization review  
Score: 72/100  
Verdict: insufficient

### Summary

Kimi judged the packet as structurally coherent but still insufficient for the
core goal: helping external AI read faster, ask shorter questions, and produce
importable findings. Its review is stricter than Qwen's despite the same score.
The main complaint is that actionable signals are buried under duplicated
contracts, stale scaffolding, and metadata noise.

### Top 5 Recommended Changes

1. Collapse dual contracts into one canonical JSON shape.

   The `## Packet Contract` text block and the `contract` JSON object repeat
   the same rules with slight drift. Kimi specifically called out a mismatch
   where `max_findings` is `5` in text but `3` in `profile_hard_limits`.

   Recommendation: prefer the machine-readable JSON as the source of truth and
   replace the text block with a compact `contract_hash` or `contract_ref`.

2. Strip null and empty scaffolding.

   Remove fields that carry no signal:

   ```txt
   delta: null
   since_packet: null
   node_cards: []
   sources: []
   important_changes
   do_not_reopen
   ```

   If a section has no content, omit the key entirely.

3. Replace `knownet://` URIs with MCP-native or resolvable resource paths.

   Kimi argued that custom `knownet://` URIs are not directly resolvable by
   standard clients. Recommended alternatives:

   ```txt
   mcp://...
   /api/...
   HTTPS paths when available
   ```

   For local-first use, relative API paths may be more practical than a custom
   faux-protocol.

4. Merge `issues`, `next_action_hints`, and `health` into `signals`.

   Actionable items are currently scattered across multiple sections with
   inconsistent shapes. Kimi recommends a single sorted array:

   ```json
   {
     "code": "health.degraded",
     "severity": "medium",
     "action": "inspect_health_issue",
     "params": {}
   }
   ```

   The array should be capped at the packet's `max_findings` limit.

5. Add `required_context` to the output contract.

   The packet says what an AI must not do, but not what missing context would
   upgrade a finding from `context_limited`. Kimi recommends making the missing
   context explicit:

   ```json
   {
     "required_context": ["node_card_excerpts", "live_provider_status"]
   }
   ```

   This should help external agents ask shorter, more targeted follow-up
   questions.

### Do Not Change

- Do not add a JSON Schema validation layer yet; Kimi considers it premature
  while the packet is still evolving.
- Keep W3C `traceparent`; do not replace it with a custom trace format.
- Keep `role_and_access_boundaries`; only remove duplication around it.
- Do not expand MCP `capabilities` until a concrete consumer needs more tools,
  prompts, logging, or sampling.

### Open Source / Standard Patterns To Absorb

Kimi recommended the following standards and conventions:

- MCP terminology and shapes: align with `resources/list` and `tools/call` as
  the primary interaction flow.
- W3C Trace Context: keep `traceparent` and propagate `trace_id` into
  `propose_finding` calls for cross-agent traceability.
- JSON Schema for `inputSchema`: use it consistently and ensure `required`
  arrays have matching property definitions.
- OpenAPI-style parameter objects: replace ad-hoc `action_params` with
  `{name, in, schema, required}` where typed client generation matters.
- SARIF-style finding severity: map KnowNet severity to SARIF `level` and,
  later, optional `rank` for CI/code-scanning portability.

### Codex Notes

Kimi adds two useful concepts that earlier reviews did not emphasize as
strongly:

- `signals` as a single high-priority action stream.
- `required_context` as the mechanism for shorter follow-up questions.

It disagrees with DeepSeek on JSON Schema timing. DeepSeek wanted schema
references as a stronger source of truth; Kimi says formal validation is
premature. A balanced interpretation is to reference schemas for stable tool
and packet shapes, while delaying strict runtime rejection until compact packet
shape settles.

## Cross-Review Synthesis

Common findings from Claude, Gemini, DeepSeek, Qwen, and Kimi:

1. The packet is too large and overbuilt.
2. Markdown/JSON or contract duplication should be reduced or eliminated.
3. `snapshot_self_test` should not be in AI-facing packet text.
4. Inline action/tool schemas are too heavy for external review.
5. Health should be compact and abnormal-detail-only.
6. Limits and metadata should have one source of truth.
7. Empty/null scaffolding should be omitted.
8. Guardrails should remain explicit.

Likely next implementation direction:

```txt
Create a compact external-AI packet mode:
- one primary readable format
- no empty structures
- no snapshot_self_test
- no inline action_input_schema
- no duplicated provider_matrix
- compact health summary only
- one signals array for prioritized actionable items
- required_context for targeted follow-up questions
- unified max_findings
- unified metadata and limits object
- schema/tool references instead of schema bodies
- role/access/output guardrails preserved
```

Open question:

```txt
Should copy-paste packets keep a small trace reference, or should trace data
exist only in stored packet metadata and MCP/API responses?
```

Second open question:

```txt
Should the external handoff format be compact JSON only, or compact Markdown
with JSON references for human copy-paste ergonomics?
```

Third open question:

```txt
Should the packet envelope adopt CloudEvents fields (`id`, `type`, `source`,
`time`, `datacontenttype`) while keeping existing KnowNet trace metadata in
stored packet records?
```

Fourth open question:

```txt
Should KnowNet replace custom `knownet://` packet/schema URIs with MCP-native,
relative API, or HTTPS resource paths for external AI handoff?
```
