# Standard Absorption Map

KnowNet packet work follows existing public standards where they fit. The goal is not to invent packet language when proven protocol, schema, trace, and evaluation language already exists.

## Source Standards

| Standard/project | Absorbed concept | KnowNet field or module |
| --- | --- | --- |
| Model Context Protocol | protocol version, capabilities, resource/tool boundaries, structured refusal | `protocol_version`, `role_and_access_boundaries`, `output_contract` |
| OpenAPI / JSON Schema | schema reference, reusable component thinking, validation errors | `schema_ref`, `validate_packet_schema_core`, `contract_shape` |
| OpenTelemetry / OpenInference | trace identity, span kind, model/provider run semantics | `trace`, `model_review_runs.trace_id`, `model_review_runs.packet_trace_id` |
| Promptfoo | provider-agnostic prompt fixtures and assertion-style output checks | `apps/api/tests/fixtures/provider_comparison/` |
| Langfuse / Agenta | run, observation, evaluation, prompt/result lifecycle | `model_review_runs`, `collaboration_reviews`, `implementation_records` |

## Packet Header

Every outbound packet or provider context should carry:

```json
{
  "contract_version": "p20.v1",
  "packet_schema_version": "p20.v1",
  "protocol_version": "2026-05-05",
  "schema_ref": "knownet://schemas/packet/p20.v1",
  "trace": {
    "trace_id": "snapshot_...",
    "span_id": "...",
    "traceparent": "00-<trace_id>-<span_id>-01",
    "name": "knownet.project_snapshot_packet",
    "span_kind": "INTERNAL"
  }
}
```

The concrete schema lives at `docs/schemas/packet.p20.v1.schema.json` and uses
`$id: knownet://schemas/packet/p20.v1`.

## Mapping Rules

- Use `protocol_version` for protocol-level versioning and parser behavior.
- Use `schema_ref` for contract/schema identity.
- Use `trace` for packet/run lineage and later model-run evidence correlation.
- Store `model_review_runs.trace_id` for the run and
  `model_review_runs.packet_trace_id` for the originating packet/context.
- Use 32-hex trace IDs and 16-hex span IDs.
- Use W3C Trace Context `traceparent` format: `00-{trace_id}-{span_id}-01`.
- Use OpenTelemetry-style `span_kind` values: `INTERNAL`, `CLIENT`, `SERVER`,
  `PRODUCER`, `CONSUMER`.
- Use MCP standard method names (`resources/list`, `resources/read`,
  `tools/list`, `tools/call`, `prompts/list`, `prompts/get`) and namespaced
  `knownet://` resource URIs / `knownet.*` tool names in packet capabilities.
- Use `role_and_access_boundaries` as the packet-level capability boundary.
- Use `issues[].code` and `issues[].action_template` as machine-actionable diagnostics.
- Use `packet_summary` for compact reading and `detail_url` for expansion.
- Use `node_cards` as resource cards, not page-body dumps.
- Keep provider comparison fixtures as JSON files so each provider/output mode
  is tested through the same parser assertions.

## Names KnowNet Keeps

KnowNet keeps its domain names where they describe the product loop:

- `collaboration_findings`
- `finding_tasks`
- `implementation_records`
- `project_snapshot_packets`
- `experiment_packets`

These are mapped to standard concepts but not renamed away from the domain.

## Rejected Reinvention

- No provider-specific packet schema.
- No raw database, shell, filesystem, token, secret, backup, session, or user dump in packets.
- No unbounded snapshot packet.
- No release-blocking decision from `context_limited` evidence.
- No vague narrative-only contract where structured schema can be used.
