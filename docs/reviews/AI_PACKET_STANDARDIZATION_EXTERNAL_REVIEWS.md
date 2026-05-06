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
