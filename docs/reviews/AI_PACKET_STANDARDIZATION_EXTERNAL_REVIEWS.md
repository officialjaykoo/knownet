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

## 2026-05-07 MiniMax Review

Reviewer: MiniMax  
Focus: packet/snapshot standardization review  
Score: 72/100  
Verdict: sufficient but overbuilt for local-first

### Summary

MiniMax judged the packet as clear and safe, with good MCP integration and W3C
trace context usage. Its criticism is that the packet carries too much overhead
for a local-first project. Like the other reviews, MiniMax focused on the
20,468 character packet exceeding the 12,000 character budget.

### Top 5 Recommended Changes

1. Reduce `hard_limits.char_budget` for the overview profile.

   MiniMax recommends moving the overview profile from `12,000` characters to
   `8,000` characters. Its reasoning is that external AI review works better
   when the default packet forces compact context rather than allowing broad
   detail.

2. Remove or conditionalize unused MCP prompt methods.

   If not actively used, remove these from the default packet:

   ```txt
   prompts/list
   prompts/get
   ```

   Alternatively, include them only in a detailed MCP/profile view.

3. Remove `snapshot_self_test` or replace it with a minimal version.

   MiniMax agrees with Claude, Gemini, DeepSeek, and Kimi that self-test output
   is useful at generation time but too long for AI-facing packet text.

4. Remove `provider_matrix` from the default profile.

   MiniMax argues that the overview packet does not need eight-provider detail
   by default. Provider information should appear only in a provider/detail
   profile.

5. Reduce `output_contract.max_findings` from `5` to `3`.

   MiniMax recommends making default AI output shorter. This differs from some
   previous reviews that wanted `max_findings` unified but did not necessarily
   require reducing it.

### Do Not Change

- Keep the W3C trace context structure.
- Keep `role_and_access_boundaries`; MiniMax considers it clear and safe.
- Keep `import_contract`, including `dry_run` and required fields.
- Keep `node_card_contract`; it is already minimal and clear.
- Keep the security policy narrative and refused/escalation lists.

### Open Source / Standard Patterns To Absorb

MiniMax recommended these patterns:

- OpenTelemetry trace context: keep `traceparent` and consider adding trace
  flags for sampling support.
- JSON Schema `$defs`: separate reusable definitions such as
  `node_card_contract` and `output_contract`.
- MCP `SamplingMessage`-style priority: consider adding sampling or priority
  metadata to evidence quality later.
- RFC 9110 HTTP semantics: make `read_endpoint` explicit with method and path,
  for example `GET /api/...`.

### Importable Finding

```txt
Title: Packet oversized relative to overview char budget
Severity: medium
Area: Data
Evidence: snapshot_quality.details.content_chars is 20468 while
profile_char_budget is 12000, exceeding the budget by about 70%.
Proposed change: Reduce the overview packet size by removing unused fields, or
split into compact overview and detailed variants.
```

### Codex Notes

MiniMax reinforces the strongest consensus item: compact the default packet.
Its most opinionated recommendation is lowering the overview budget to `8,000`
characters and reducing default findings to `3`. That is useful as a speed
target, but should be weighed against Kimi's `required_context` idea so compact
packets do not become too thin to produce importable findings.

## 2026-05-07 Z.ai Review

Reviewer: Z.ai  
Focus: packet/snapshot standardization review  
Score: 62/100  
Verdict: overbuilt for stated scope

### Summary

Z.ai gave one of the harshest reviews. It praised the security boundaries, W3C
trace context, and MCP-aligned shapes, but argued that the packet is enterprise
weight for a small local-first project. Its short recommendation is: stop
building new packet surface, start cutting.

### Score Breakdown

```txt
Security boundaries: +20
Trace context: +15
MCP alignment: +10
Size compliance: -15
Redundancy: -12
Complexity vs local-first: -16
Inconsistencies: -10
```

### Top 5 Recommended Changes

1. Fix the size crisis immediately.

   Current packet size:

   ```txt
   20,468 characters
   170% of a 12,000 character budget
   ```

   Recommended cuts:

   ```txt
   Remove contract_shape
   Collapse health to overall_status, issue_codes, checked_at
   Delete empty node_cards and source_manifest.sources
   Delete all null fields
   Target overview profile below 8,000 characters
   ```

2. Eliminate triple contract redundancy.

   Z.ai identified three parallel contract representations:

   ```txt
   ## Packet Contract
   contract JSON key
   contract_shape metadata key
   ```

   Recommendation: keep only the structured `contract` JSON as the source of
   truth. Move human-readable contract text to optional docs or appendix.

3. Resolve conflicting limit definitions.

   Z.ai called out competing values:

   ```json
   {
     "hard_limits": {"max_findings": 3},
     "output_contract": {"max_findings": 5},
     "profile_hard_limits": {"max_findings": 3}
   }
   ```

   Recommendation: replace this with one `limits` object and one explicit merge
   strategy for profile overrides.

4. Replace custom `knownet://` URIs with standard URI patterns.

   Z.ai recommends HTTP(S) JSON Schema `$id` or repository-hosted schema URLs:

   ```txt
   https://knownet.dev/schemas/packet/p20.v1
   https://github.com/knownetproject/schemas/blob/main/packet/p20.v1.schema.json
   ```

   The concern is that custom URI schemes break validators, linters, IDEs, and
   generic tooling.

5. Adopt SARIF for findings.

   Z.ai recommends mapping KnowNet findings to SARIF:

   ```txt
   area -> ruleId
   severity -> level
   title -> message.text
   evidence_quality -> properties.evidence_quality
   proposed_change -> properties.knownet.proposed_change
   ```

   Benefit: VS Code, GitHub, and GitLab can already render SARIF-like findings.

### Do Not Change

- Keep W3C Trace Context; the `traceparent` format is correct.
- Keep MCP tool naming, such as `knownet.propose_finding`.
- Keep the role boundary model: `allowed`, `refused`, `escalate_on`.
- Keep the evidence quality taxonomy:
  `direct_access | context_limited | inferred | operator_verified`.
- Keep stale context suppression simple.

### Open Source / Standard Patterns To Absorb

Z.ai recommended:

- OpenAPI 3.1 for tool definitions, with `paths` and `components` instead of
  ad-hoc embedded input schemas.
- RFC 9457 Problem Details for `issues`.
- JSON-LD `@context` for future semantic interoperability.
- in-toto provenance for future reproducible snapshot/build provenance.
- SARIF for portable findings.

### Codex Notes

Z.ai is useful because it names the product risk clearly: KnowNet is carrying
some v0.9 enterprise specification weight before proving the v0.1 external AI
handoff loop. Its standard recommendations are valuable, but not all should be
implemented immediately. The near-term lesson is narrower:

```txt
Trim first, then standardize only the remaining stable shapes.
```

OpenAPI, SARIF, and RFC 9457 are stronger candidates than JSON-LD or in-toto
for the next compact packet iteration because they directly affect tools,
issues, and importable findings.

## Cross-Review Synthesis

Common findings from Claude, Gemini, DeepSeek, Qwen, Kimi, MiniMax, and Z.ai:

1. The packet is too large and overbuilt.
2. Markdown/JSON or contract duplication should be reduced or eliminated.
3. `snapshot_self_test` should not be in AI-facing packet text.
4. Inline action/tool schemas are too heavy for external review.
5. Health should be compact and abnormal-detail-only.
6. Limits and metadata should have one source of truth.
7. Empty/null scaffolding should be omitted.
8. Guardrails should remain explicit.
9. The default profile should be compact; detailed/provider views should be
   opt-in.
10. Custom URI and finding shapes should move toward standard, tool-friendly
    formats once the compact shape is stable.

Likely next implementation direction:

```txt
Create a compact external-AI packet mode:
- one primary readable format
- no empty structures
- no snapshot_self_test
- no inline action_input_schema
- no duplicated provider_matrix
- provider_matrix only in provider/detail profiles
- compact health summary only
- one signals array for prioritized actionable items
- required_context for targeted follow-up questions
- unified max_findings
- unified metadata and limits object
- schema/tool references instead of schema bodies
- HTTP(S) or resolvable schema references over custom-only URI schemes
- SARIF/OpenAPI/RFC 9457 alignment where it reduces custom parsing
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

Fifth open question:

```txt
Should the compact overview target remain 12,000 characters, or should KnowNet
adopt an 8,000 character target and move more detail into opt-in profiles?
```

Sixth open question:

```txt
Should KnowNet findings remain a compact custom import shape for now, or should
the next stable import format map directly to SARIF fields?
```

## 2026-05-07 DeepSeek Review After Phase 26 Compact Packet

Reviewer: DeepSeek  
Focus: Phase 26 compact external AI packet  
Packet: `snapshot_20f26adeab6e`  
Score: 80/100  
Verdict: enough for now

### Summary

DeepSeek's post-Phase 26 review is the first review to rate the compact packet
as good enough for current use. The score moved from earlier overbuilt ratings
into an 80/100 range after the packet dropped below the 8,000-character
optimization target. DeepSeek still sees small redundant fields, but no longer
recommends broad redesign.

### Top Concrete Changes

1. Remove standalone `ai_state_quality` and `preflight` objects.

   DeepSeek says the current `signals` already carries the useful summary. The
   remaining top-level objects duplicate context and can be removed from the
   AI-facing packet body to save characters.

2. Replace `health.issue_codes` with terse reasons.

   Recommended shape:

   ```json
   {
     "reasons": [
       {
         "code": "security.public_without_cloudflare_access",
         "text": "Public mode without Cloudflare Access origin gate"
       }
     ]
   }
   ```

   This keeps health compact while making the issue understandable without a
   separate operator lookup.

3. Drop top-level `links`.

   DeepSeek argues external copy-paste reviewers consume the payload directly
   and rarely resolve API hrefs from the snapshot. Removing `links` would reduce
   noise and save roughly 200 characters.

### Do Not Change

DeepSeek specifically says to keep:

- `signals` with embedded `required_context`
- precise `ask_operator` prompts
- `role_boundaries`
- `contract_ref` and `schema_ref`
- W3C `trace`
- `limits` with character budget tracking

### Standard Pattern

DeepSeek recommends adopting CloudEvents envelope attributes:

```txt
id
source
type
time
```

The recommendation is to use CloudEvents as a light header layer over the
existing W3C `traceparent`, not to add a heavy event subsystem.

### Codex Notes

This review changes the implementation posture: Phase 26 is now good enough for
active external AI use. Remaining work should be small trimming, not another
contract redesign. The highest-signal follow-up candidates are:

```txt
1. Fold preflight/ai_state_quality into signals or packet_summary.
2. Make compact health self-explanatory with short reason text.
3. Consider whether links belong only in stored API responses, not copy-ready
   content.
```

## 2026-05-07 Claude Review After Phase 26 Compact Packet

Reviewer: Claude  
Focus: Phase 26 compact external AI packet  
Packet: `snapshot_20f26adeab6e`  
Score: 81/100  
Verdict: enough for now

### Summary

Claude also rates the current Phase 26 packet as sufficient for active use. Its
review is slightly higher than DeepSeek's and recommends only small trimming.
Claude's strongest overlap with DeepSeek is the removal of redundant
`ai_state_quality`.

### Top Concrete Changes

1. Remove top-level `ai_state_quality`.

   Claude says the same information already exists inside `signals[].params`
   and that the standalone block is pure duplication. Estimated saving: about
   300 characters.

2. Collapse `trace` to one `traceparent` field.

   Claude keeps the W3C standard but recommends dropping `trace_id`, `span_id`,
   and `attributes` from the copy-ready packet because external AIs do not read
   them. Suggested compact shape:

   ```json
   {
     "traceparent": "00-a7b832d0752da0916ca8e6dfe8e3530b-c4608ab51eba21f1-01"
   }
   ```

3. Remove `role_boundaries.narrative`.

   Claude says `allowed`, `refused`, and `escalate_on` are already clear enough.
   The narrative repeats the same meaning in sentence form and can be removed
   from the compact body.

### Do Not Change

Claude specifically says to keep:

- `signals[].required_context`
- single `limits` block
- `contract_ref`
- `packet_integrity`

### Standard Pattern

Claude does not recommend adding another standard immediately. It says the
packet is already standard enough for now, and RFC 9457 can be revisited later
if real findings accumulate and `signals` need a more formal problem-details
shape.

### Codex Notes

Claude and DeepSeek now agree that Phase 26 is sufficient. Their common
implementation candidate is:

```txt
Remove top-level ai_state_quality from copy-ready content.
```

The remaining suggestions differ:

```txt
DeepSeek: improve compact health reasons and maybe remove links.
Claude: collapse trace and remove role_boundaries.narrative.
```

Because the packet is already below the 8,000-character target, these should be
treated as small polish work, not a new phase-sized redesign.

## 2026-05-07 Qwen Review After Phase 26 Compact Packet

Reviewer: Qwen  
Focus: Phase 26 compact external AI packet  
Packet: `snapshot_20f26adeab6e`  
Score: 88/100  
Verdict: enough for now

### Summary

Qwen gives the strongest post-Phase 26 score so far. It explicitly says the
packet is compact, signal-focused, and import-ready at 5,906 characters. Qwen
also calls out `signals[].required_context` with `missing` and `ask_operator` as
the right pattern for actionable findings without over-fetching.

### Top Concrete Changes

1. Remove `role_boundaries.narrative`.

   This matches Claude's recommendation. Qwen says the prose duplicates the
   structured `allowed`, `refused`, and `escalate_on` arrays. External AI can
   infer or generate narrative from the arrays when needed.

2. Compress zero-value summaries.

   Qwen points to repeated summaries such as:

   ```json
   {
     "pages": 0,
     "ai_state_pages": 0
   }
   ```

   It recommends omitting all-zero summaries or replacing them with a compact
   sentinel such as `"summary": "empty"`.

3. Make `required_context.ask_operator` schema-referenced.

   For overview packets, Qwen suggests keeping only `missing` in the packet and
   referencing a standard question template from a schema such as:

   ```txt
   knownet://schemas/signals/v1#context_questions
   ```

   This would preserve actionability while trimming repeated prompt text.

### Do Not Change

Qwen specifically says to keep:

- W3C traceparent format and trace attribute structure
- `role_boundaries` core arrays
- `signals[].code`, `severity`, and `action`
- `packet_integrity.char_budget` fields
- `do_not_suggest`
- `ai_context.read_order`

### Standard Patterns

Qwen recommends these standards for future alignment:

- RFC 7807 Problem Details for `signals`
- IETF JSON Hyper-Schema style `links`
- CloudEvents envelope alignment

### Codex Notes

Qwen further strengthens the current consensus:

```txt
Phase 26 is enough for now.
```

The strongest shared trim candidate after Claude and Qwen is:

```txt
Remove role_boundaries.narrative from copy-ready content.
```

The zero-summary compression idea is new and practical. The schema-referenced
`ask_operator` idea saves little but risks weakening the best Phase 26 usability
feature, so it should wait unless repeated signals make the text expensive.

## 2026-05-07 Kimi Review After Phase 26 Compact Packet

Reviewer: Kimi  
Focus: Phase 26 compact external AI packet  
Packet: `snapshot_20f26adeab6e`  
Score: 84/100  
Verdict: enough for now

### Summary

Kimi agrees that the packet is now short enough for daily handoffs. It cites the
under-6K size, single contract reference, unified signals,
per-signal `required_context`, and clean role boundaries as the reasons the
packet is import-ready.

### Top Concrete Changes

1. Remove `ai_state_quality` and `preflight` duplication.

   Kimi says these top-level fields repeat the same zero-value state already
   embedded in the first signal's `params.summary`. Removing both saves roughly
   400 characters and removes a cross-reference burden.

2. Flatten `links`.

   Kimi says `links.self`, `links.content`, and `links.storage` are identical or
   derivable enough for external reviewers. A single `packet_url` string would
   be sufficient if a link is still needed.

3. Remove `role_boundaries.narrative`.

   This matches Claude and Qwen. The structured arrays are enough for AI
   consumers, and the narrative text is redundant.

### Do Not Change

Kimi specifically says:

- Do not add another JSON Schema validation layer.
- Do not expand `signals` beyond the current overview cap.
- Do not replace W3C `traceparent`.
- Do not inline MCP resource/tool schemas.
- Do not add SARIF, CloudEvents, or JSON-LD to the packet.

### Standard Pattern

Kimi recommends RFC 9457 Problem Details for API error responses, not for the
compact packet itself. Suggested future use cases:

```txt
/api/schemas/packet/p26.v1 errors
propose_finding error responses
```

### Codex Notes

Kimi's review creates a strong three-review overlap around removing
`role_boundaries.narrative`, and a strong DeepSeek/Kimi overlap around removing
or folding `preflight` and `ai_state_quality`.

The current practical trim list is:

```txt
1. Remove top-level ai_state_quality from copy-ready content.
2. Remove top-level preflight from copy-ready content.
3. Remove role_boundaries.narrative from copy-ready content.
4. Flatten or move links out of copy-ready content.
```

These are small enough to implement as Phase 26 polish rather than a new phase.

## 2026-05-07 MiniMax Review After Phase 26 Compact Packet

Reviewer: MiniMax  
Focus: Phase 26 compact external AI packet  
Packet: `snapshot_20f26adeab6e`  
Score: 85/100  
Verdict: enough

### Summary

MiniMax rates the p26 packet as sufficient and emphasizes the improvement from
the older p20 packet:

```txt
p20.v1: 20,468 chars
p26.v1: 5,906 chars
reduction: about 71%
```

MiniMax says the packet is now below both the 12,000-character warning line and
the 8,000-character optimization target.

### Top Concrete Changes

1. Remove or profile-gate `links`.

   MiniMax says `self`, `content`, and `storage` links may not be used by
   external AI copy-paste reviewers. If unused, removing them could save a few
   hundred characters.

2. Remove `role_boundaries.narrative`.

   This matches Claude, Qwen, and Kimi. The structured arrays are enough.

3. Replace empty `snapshot_diff_summary` with a boolean.

   MiniMax recommends using a compact flag such as:

   ```json
   {
     "delta_detected": false
   }
   ```

   This is more relevant if the field is empty. The current packet normally
   omits empty arrays through `omit_empty`, but the idea is useful for future
   delta packet shape review.

### Do Not Change

MiniMax specifically says to keep:

- `packet_integrity`
- `signals[].required_context`
- `limits`
- `contract_hash`

### Standard Patterns

MiniMax suggests possible future alignment with:

- ETag/cache-validation patterns around `content_hash` or `contract_hash`
- OpenTelemetry span status terminology
- IETF health check response shape
- JSON Schema `$id`

### Finding

```txt
Title: p26.v1 packet size is excellent; next optimization is signal depth
Severity: low
Area: Data
Evidence: packet_integrity.content_chars is 5906, below the 8K optimization
target. Signals contain two items with required_context asking for operator
input.
Proposed change: Omit signals when there are none. When preflight.pages = 0,
add fresh_install: true so reviewers know whether empty context is intentional.
```

### Codex Notes

MiniMax further confirms that the compact packet is usable now. The most common
post-Phase 26 trim candidates across reviews are now:

```txt
1. Remove role_boundaries.narrative.
2. Remove or shrink links in copy-ready content.
3. Remove ai_state_quality/preflight duplication.
```

The `fresh_install` idea is useful because multiple AI reviews have reacted to
the empty project state as a potential quality problem. A small explicit flag
could reduce mistaken findings without adding much weight.
