# Phase 28 Tasks: SARIF Location Quality

Status: completed
Created: 2026-05-07
Updated: 2026-05-07

Implementation status: completed in the codebase.

Implemented surface:

- Shared source-location parser for repo-relative paths and GitHub-style
  `path#Lx-Ly` refs.
- Optional finding columns: `source_path`, `source_start_line`,
  `source_end_line`, `source_snippet`, `source_location_status`.
- Markdown and compact JSON review parsing for optional source locations.
- SARIF physical locations with `region.startLine`, `region.endLine`, and
  explicitly supplied snippets.
- Stable `knownetContentFingerprint` partial fingerprint alongside
  `knownetFindingId`.
- Per-result `code_scanning_ready` metadata and run-level readiness summary.
- Small UI export status showing `N / total` Code Scanning ready results.

Verification:

- `cd apps/core; $env:CARGO_TARGET_DIR='C:\knownet\.local\cargo-target'; cargo build`
- `cd apps/api; python -m pytest tests\test_phase28_sarif_location.py tests\test_phase27_sarif.py tests\test_collaboration_review_parser.py -q`
- `cd apps/core; $env:CARGO_TARGET_DIR='C:\knownet\.local\cargo-target'; cargo test`
- `cd apps/api; python -m pytest -q`
- `cd apps/web; npm run build`

Phase 27 added SARIF export. Phase 28 improves whether exported SARIF is useful
inside GitHub Code Scanning, IDEs, and code review tools.

The problem is not SARIF syntax anymore. The problem is location quality.

Phase 27 can export findings and file-level locations from
`implementation_records.changed_files`. That is enough to prove the pipeline,
but weak for Code Scanning because GitHub works best when a result has:

```txt
repo-relative file path
start line
end line when relevant
snippet or context when safe
stable fingerprint for deduplication
```

Phase 28 adds those pieces carefully, without turning KnowNet into a static
analysis engine.

## Fixed Rules

Do not:

- Replace Phase 27 SARIF export.
- Add automatic GitHub upload.
- Require every finding to have a source location.
- Fake line numbers for non-code findings.
- Export raw secrets, `.env`, raw DB paths, backups, sessions, generated cache
  paths, or absolute local paths.
- Treat `context_limited` findings as Code Scanning ready by default.
- Add a full CodeQL/static-analysis engine.
- Put line/snippet detail into compact AI packets.

Do:

- Keep Phase 27 `sarif-om` export as the base.
- Add optional source locations to findings/review parsing.
- Prefer direct nullable columns for the first location implementation.
- Parse safe path ranges such as `apps/api/file.py#L12-L18`.
- Emit SARIF `region.startLine` and `region.endLine` only when known.
- Add stable content fingerprints in addition to KnowNet finding IDs.
- Add `code_scanning_ready` metadata instead of rejecting location-less exports.
- Keep non-code findings exportable, but mark them not Code Scanning ready.
- Keep Code Scanning readiness summary inside SARIF `run.properties.knownet`,
  not as custom top-level SARIF fields.

## Why This Phase Exists

External review of the Phase 27 SARIF fixtures found that the fixtures validate
the format but do not represent real actionable Code Scanning alerts. That is
expected for fixtures, but it reveals the next capability gap:

```txt
SARIF without a real file/line target is useful as an archive or exchange
format, but weak as a GitHub PR annotation.
```

KnowNet should therefore distinguish:

```txt
SARIF exportable      -> can be represented as SARIF
Code Scanning ready   -> has trusted evidence and useful safe source location
```

## P28-001 Optional Finding Location Fields

Problem:

KnowNet findings currently capture title, area, severity, evidence, proposed
change, evidence_quality, and status, but not an explicit source location.
Phase 27 can only infer locations from implementation records.

Implementation shape:

Use direct nullable columns first. A separate locations table is too much until
KnowNet needs multiple locations per finding.

Candidate columns on `collaboration_findings`:

```txt
source_path
source_start_line
source_end_line
source_snippet
source_location_status
```

Default decision:

```txt
Use nullable columns now.
Revisit a related table only if one finding needs multiple source locations.
```

Rules:

- All fields are optional.
- Path must be repo-relative and pass ignore/secret path policy.
- Line numbers must be positive integers.
- `source_end_line` must be greater than or equal to `source_start_line`.
- `source_snippet` must pass secret text checks.
- `source_location_status` should record `accepted`, `omitted`, or
  `rejected:<reason>`.
- Existing findings do not need migration beyond nullable fields/table.

Done when:

- A finding can carry a safe source path and optional line range.
- Existing findings without locations continue to work.
- Unsafe paths/snippets are rejected or dropped with an explicit reason.
- API responses expose `source_location_status` so the operator can see why a
  location is absent.

## P28-002 Review Parser Location Contract

Problem:

External AI/code reviewers need a simple way to submit locations without
learning a custom nested schema.

Implementation shape:

Allow optional fields in Finding blocks:

```txt
Source path: apps/api/knownet_api/services/sarif_export.py
Source lines: 42-57
Source snippet:
...
```

Also allow compact JSON:

```json
{
  "title": "...",
  "severity": "medium",
  "area": "API",
  "evidence_quality": "direct_access",
  "source_location": {
    "path": "apps/api/knownet_api/services/sarif_export.py",
    "start_line": 42,
    "end_line": 57,
    "snippet": "..."
  }
}
```

Rules:

- Missing source location is valid.
- Invalid source location should not make the whole review fail unless it
  contains forbidden content.
- Parser should report `source_location_omitted` or similar metadata when a
  provided location is unsafe.
- Store `source_location_status` on the finding so the rejection reason is not
  lost after import.
- Do not infer lines from prose.
- Markdown `Source lines: 42-57` must be supported separately from
  GitHub-style `#L42-L57`.

Done when:

- Markdown and compact JSON reviews can carry optional source locations.
- Parser tests cover valid path/range, missing location, and unsafe path.
- Location data reaches the stored finding record or related location table.
- Location parser errors do not prevent valid finding import unless the value
  contains forbidden secret text.

## P28-003 `path#Lx-Ly` Range Parsing

Problem:

AI and humans often refer to code locations as GitHub-style fragments:

```txt
apps/api/routes.py#L45
apps/api/routes.py#L45-L52
```

Implementation shape:

Add a small parser:

```python
parse_source_location_ref("apps/api/routes.py#L45-L52")
```

Expected output:

```json
{
  "path": "apps/api/routes.py",
  "start_line": 45,
  "end_line": 52
}
```

Rules:

- Accept `#L45` and `#L45-L52`.
- Accept plain path without line numbers.
- Reject absolute paths, parent traversal, generated/secret paths.
- Reject line `0` and negative line numbers.
- Reject ranges where end line is lower than start line.
- Normalize Windows backslashes to `/` before validation.
- Reject paths with unsafe whitespace unless a later concrete need appears.
- Keep parsing deterministic; no fuzzy matching.
- Reuse the existing ignore/secret path policy instead of adding a parallel
  denylist.

Done when:

- Unit tests cover path-only, single-line, range, invalid path, and invalid
  range.
- SARIF exporter can consume parsed ranges.
- Security tests cover `.env`, DB paths, generated paths, absolute paths, and
  parent traversal.

## P28-004 SARIF Region And Snippet Output

Problem:

Phase 27 outputs SARIF `artifactLocation.uri` but not line regions.

Implementation shape:

When a safe source location exists, emit:

```json
{
  "physicalLocation": {
    "artifactLocation": {"uri": "apps/api/routes.py"},
    "region": {
      "startLine": 45,
      "endLine": 52,
      "snippet": {"text": "..."}
    }
  }
}
```

Rules:

- Emit `region` only when line data exists.
- Emit `snippet` only when provided and safe.
- Keep file-level locations valid for implementation_records.changed_files.
- Do not open source files to guess snippets in this phase.
- Do not add SARIF `suppressions` for implemented findings yet; keep
  `properties.knownet.status = implemented` until GitHub rendering behavior is
  verified.

Done when:

- SARIF results include region data for findings that provide line ranges.
- Findings without line ranges still export safely.
- Schema validation still passes.

## P28-005 Stable Content Fingerprints

Problem:

Phase 27 includes `partialFingerprints.knownetFindingId`, but database IDs are
not stable across imports or environments.

Implementation shape:

Add an additional content fingerprint:

```txt
knownetContentFingerprint = sha256(title + area + evidence + path + line range)
```

Rules:

- Keep `knownetFindingId` for local traceability.
- Add stable hash for GitHub deduplication.
- Do not include volatile fields such as updated_at, status, or review_id.
- Normalize whitespace before hashing.
- Normalize title, area, evidence, source path, and line range in a fixed order.
- Use `sha256:` prefix.

Done when:

- SARIF results include both local finding ID and stable content fingerprint.
- Tests show the fingerprint stays stable when status changes.
- Tests show fingerprint changes when path/line/evidence changes.
- Tests show whitespace-only title changes do not change the fingerprint.

## P28-006 `code_scanning_ready` Metadata

Problem:

Rejecting SARIF export when locations are missing is too strict. Some findings
are useful as SARIF records but not as GitHub Code Scanning alerts.

Implementation shape:

Add metadata under SARIF properties:

```json
{
  "properties": {
    "knownet": {
      "code_scanning_ready": true,
      "code_scanning_ready_reasons": ["trusted_evidence", "safe_location", "line_range_present"]
    }
  }
}
```

If not ready:

```json
{
  "code_scanning_ready": false,
  "code_scanning_ready_reasons": ["missing_line_range"]
}
```

Rules:

- Compute readiness through one function, not scattered inline logic.
- Do not block export solely because `code_scanning_ready` is false.
- Default ready criteria:
  - evidence_quality is `direct_access` or `operator_verified`
  - safe repo-relative source path exists
  - line range exists
- `implemented` findings may still be exported but should remain clear as
  implemented/closed in properties.
- `context_limited` is not ready by default, even if it has a path.
- Readiness summary belongs in `run.properties.knownet`, for example:

```json
{
  "code_scanning_ready_summary": {
    "total_results": 12,
    "ready": 4,
    "not_ready_reasons": {
      "missing_line_range": 6,
      "untrusted_evidence_quality": 2
    }
  }
}
```

Done when:

- SARIF output marks each result as ready/not ready for Code Scanning.
- Tests cover ready, file-only, no-location, and context_limited cases.
- SARIF run properties include a readiness summary without adding non-standard
  top-level fields.

## P28-007 UI And Operator Guidance

Problem:

Operators need to understand why an exported SARIF file may not produce useful
GitHub annotations.

Implementation shape:

Keep UI small:

```txt
Export SARIF
Code Scanning ready: N / total
```

or expose readiness in endpoint metadata if UI display is deferred.

If exposed through SARIF, read the count from:

```txt
runs[0].properties.knownet.code_scanning_ready_summary
```

Rules:

- No SARIF dashboard.
- No automatic upload.
- Do not make source-location entry mandatory in the UI.

Done when:

- Operator can see whether the SARIF export is Code Scanning ready enough to
  upload.
- Non-ready results explain missing reasons.

## Acceptance

```txt
1. Findings can optionally carry safe source path, line range, and snippet.
2. Review parser accepts optional source location in Markdown and compact JSON.
3. GitHub-style path#Lx-Ly references are parsed deterministically.
4. SARIF results include region/snippet when provided.
5. SARIF results include stable content fingerprints.
6. Each SARIF result reports code_scanning_ready true/false with reasons.
7. Missing locations do not block SARIF export.
8. context_limited findings are not Code Scanning ready by default.
9. Compact AI packets remain unchanged.
10. `source_location_status` explains accepted/omitted/rejected locations.
11. SARIF readiness summary lives under `run.properties.knownet`.
12. Implemented findings are not represented with SARIF suppressions until
    GitHub rendering behavior is verified.
```

## Suggested Implementation Order

```txt
P28-003 path#Lx-Ly Range Parsing
P28-001 Optional Finding Location Fields
P28-002 Review Parser Location Contract
P28-004 SARIF Region And Snippet Output
P28-005 Stable Content Fingerprints
P28-006 code_scanning_ready Metadata
P28-007 UI And Operator Guidance
```

## Out Of Scope

```txt
- Automatic GitHub upload
- GitHub Actions workflow template
- CodeQL/static analyzer integration
- Fuzzy source location inference
- Opening files to guess snippets
- Replacing KnowNet packets or findings
- Requiring source locations for all findings
- SARIF suppressions for implemented findings
- Custom top-level SARIF metadata
- Full release_check
```
