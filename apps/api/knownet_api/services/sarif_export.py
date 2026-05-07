from __future__ import annotations

import json
import hashlib
import re
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

import attr
from jsonschema import Draft202012Validator
from sarif_om import (
    ArtifactContent,
    ArtifactLocation,
    Location,
    Message,
    PhysicalLocation,
    ReportingDescriptor,
    Result,
    Region,
    Run,
    SarifLog,
    Tool,
    ToolComponent,
)

from .source_locations import normalize_source_location, parse_source_location_ref, safe_source_path


SARIF_SCHEMA_URI = "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/sarif-2.1/schema/sarif-schema-2.1.0.json"
SARIF_VERSION = "2.1.0"
KNOWNET_TOOL_NAME = "KnowNet"

SEVERITY_TO_LEVEL = {
    "critical": "error",
    "high": "error",
    "medium": "warning",
    "low": "note",
    "info": "note",
}

TRUSTED_DEFAULT_EVIDENCE = {"direct_access", "operator_verified"}
DEFAULT_EXPORT_STATUSES = {"accepted", "implemented"}
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "sarif-schema-2.1.0.json"


@lru_cache(maxsize=1)
def sarif_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_sarif_log(log: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(sarif_schema())
    return [error.message for error in sorted(validator.iter_errors(log), key=lambda item: list(item.path))[:20]]


def _schema_name(attribute: attr.Attribute) -> str:
    return str(attribute.metadata.get("schema_property_name") or attribute.name)


def sarif_to_dict(value: Any) -> Any:
    """Serialize sarif-om attr classes using SARIF JSON property names."""
    if attr.has(value.__class__):
        result: dict[str, Any] = {}
        for attribute in attr.fields(value.__class__):
            child = getattr(value, attribute.name)
            if child is None:
                continue
            serialized = sarif_to_dict(child)
            if serialized is None:
                continue
            if serialized == [] and attribute.default is None:
                continue
            result[_schema_name(attribute)] = serialized
        return result
    if isinstance(value, list):
        return [sarif_to_dict(item) for item in value if sarif_to_dict(item) is not None]
    if isinstance(value, dict):
        return {key: sarif_to_dict(item) for key, item in value.items() if sarif_to_dict(item) is not None}
    return value


def sarif_level(severity: str | None) -> str:
    return SEVERITY_TO_LEVEL.get(str(severity or "info").lower(), "note")


def rule_id_for_finding(finding: dict[str, Any]) -> str:
    area = re.sub(r"[^a-z0-9]+", "-", str(finding.get("area") or "knownet").lower()).strip("-") or "knownet"
    severity = re.sub(r"[^a-z0-9]+", "-", str(finding.get("severity") or "info").lower()).strip("-") or "info"
    return f"knownet.{area}.{severity}"


def guid_for_finding(finding: dict[str, Any]) -> str:
    source = str(finding.get("id") or finding.get("finding_id") or "")
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"knownet:finding:{source}"))


def safe_sarif_path(path: str | None) -> tuple[str | None, str | None]:
    return safe_source_path(path)


def _append_unique_location(locations: list[dict[str, Any]], location: dict[str, Any]) -> None:
    key = (location.get("path"), location.get("start_line"), location.get("end_line"))
    if key not in {(item.get("path"), item.get("start_line"), item.get("end_line")) for item in locations}:
        locations.append(location)


def source_locations_from_row(row: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    locations: list[dict[str, Any]] = []
    omitted: list[dict[str, str]] = []
    explicit = normalize_source_location(
        path=row.get("source_path"),
        start_line=row.get("source_start_line"),
        end_line=row.get("source_end_line"),
        snippet=row.get("source_snippet"),
    )
    if explicit.get("source_location_status") == "accepted" and explicit.get("source_path"):
        _append_unique_location(
            locations,
            {
                "path": explicit["source_path"],
                "start_line": explicit.get("source_start_line"),
                "end_line": explicit.get("source_end_line"),
                "snippet": explicit.get("source_snippet"),
                "source": "finding",
            },
        )
    elif row.get("source_path"):
        omitted.append({"path": str(row.get("source_path")), "reason": explicit.get("source_location_status") or "unsafe_source_location"})

    raw_values: list[Any] = []
    if row.get("changed_files_values"):
        raw_values.extend(row.get("changed_files_values") or [])
    elif row.get("changed_files_json"):
        raw_values.extend(str(row.get("changed_files_json")).split("||"))
    elif row.get("changed_files"):
        raw_values.append(row.get("changed_files"))
    paths: list[str] = []
    omitted: list[dict[str, str]] = []
    for raw in raw_values:
        if not raw:
            continue
        candidates: list[Any]
        if isinstance(raw, list):
            candidates = raw
        else:
            try:
                parsed = json.loads(str(raw))
                candidates = parsed if isinstance(parsed, list) else [raw]
            except Exception:
                candidates = [raw]
        for candidate in candidates:
            parsed = parse_source_location_ref(str(candidate))
            if parsed.get("status") == "accepted" and parsed.get("path"):
                _append_unique_location(
                    locations,
                    {
                        "path": parsed["path"],
                        "start_line": parsed.get("start_line"),
                        "end_line": parsed.get("end_line"),
                        "snippet": None,
                        "source": "implementation",
                    },
                )
            else:
                omitted.append({"path": str(candidate), "reason": str(parsed.get("reason") or "unsafe_path")})
    return locations, omitted


def changed_files_from_row(row: dict[str, Any]) -> tuple[list[str], list[dict[str, str]]]:
    locations, omitted = source_locations_from_row(row)
    paths: list[str] = []
    for location in locations:
        path = str(location.get("path") or "")
        if path and path not in paths:
            paths.append(path)
    return paths, omitted


def _locations_for_source_locations(locations: list[dict[str, Any]]) -> list[Location]:
    result: list[Location] = []
    for location in locations:
        region = None
        if location.get("start_line"):
            region = Region(
                start_line=int(location["start_line"]),
                end_line=int(location.get("end_line") or location["start_line"]),
                snippet=ArtifactContent(text=str(location["snippet"])) if location.get("snippet") else None,
            )
        result.append(
            Location(
                physical_location=PhysicalLocation(
                    artifact_location=ArtifactLocation(uri=str(location["path"])),
                    region=region,
                )
            )
        )
    return result


def _stable_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def content_fingerprint(finding: dict[str, Any], locations: list[dict[str, Any]] | None = None) -> str:
    first_location = (locations or [{}])[0] if locations else {}
    components = [
        _stable_text(finding.get("title")),
        _stable_text(finding.get("area")),
        _stable_text(finding.get("evidence")),
        _stable_text(first_location.get("path") or finding.get("source_path")),
        _stable_text(first_location.get("start_line") or finding.get("source_start_line")),
        _stable_text(first_location.get("end_line") or finding.get("source_end_line")),
    ]
    return "sha256:" + hashlib.sha256("|".join(components).encode("utf-8")).hexdigest()


def code_scanning_readiness(finding: dict[str, Any], locations: list[dict[str, Any]]) -> dict[str, Any]:
    reasons_pass: list[str] = []
    reasons_fail: list[str] = []
    if str(finding.get("evidence_quality") or "unspecified") in TRUSTED_DEFAULT_EVIDENCE:
        reasons_pass.append("trusted_evidence")
    else:
        reasons_fail.append("untrusted_evidence_quality")
    if locations:
        reasons_pass.append("safe_location")
    else:
        reasons_fail.append("missing_source_path")
    if any(location.get("start_line") for location in locations):
        reasons_pass.append("line_range_present")
    else:
        reasons_fail.append("missing_line_range")
    return {
        "code_scanning_ready": not reasons_fail,
        "code_scanning_ready_reasons": reasons_pass if not reasons_fail else reasons_fail,
    }


def _knownet_properties(
    finding: dict[str, Any],
    *,
    omitted_locations: list[dict[str, str]],
    readiness: dict[str, Any],
) -> dict[str, Any]:
    implementation = {}
    if finding.get("commit_sha"):
        implementation["commit"] = finding.get("commit_sha")
    if finding.get("commit_shas"):
        implementation["commits"] = [value for value in str(finding["commit_shas"]).split("|") if value]
    props = {
        "knownet": {
            "finding_id": finding.get("id") or finding.get("finding_id"),
            "review_id": finding.get("review_id"),
            "severity": finding.get("severity"),
            "area": finding.get("area"),
            "status": finding.get("status") or finding.get("finding_status"),
            "evidence_quality": finding.get("evidence_quality") or "unspecified",
            "evidence": finding.get("evidence"),
            "proposed_change": finding.get("proposed_change"),
            "source": {
                "agent": finding.get("source_agent"),
                "model": finding.get("source_model"),
            },
            "source_location": {
                "path": finding.get("source_path"),
                "start_line": finding.get("source_start_line"),
                "end_line": finding.get("source_end_line"),
                "status": finding.get("source_location_status") or "omitted",
            },
            "code_scanning_ready": readiness["code_scanning_ready"],
            "code_scanning_ready_reasons": readiness["code_scanning_ready_reasons"],
            "implementation": implementation or None,
            "omitted_locations": omitted_locations or None,
        }
    }
    return _drop_empty(props)


def _drop_empty(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            cleaned = _drop_empty(item)
            if cleaned in (None, [], {}):
                continue
            result[key] = cleaned
        return result
    if isinstance(value, list):
        return [item for item in (_drop_empty(item) for item in value) if item not in (None, [], {})]
    return value


def build_sarif_log(findings: list[dict[str, Any]], *, run_id: str, generated_at: str) -> dict[str, Any]:
    rules_by_id: dict[str, ReportingDescriptor] = {}
    results: list[Result] = []
    omitted_location_count = 0
    code_scanning_ready_count = 0
    not_ready_reasons: dict[str, int] = {}
    for finding in findings:
        rule_id = rule_id_for_finding(finding)
        if rule_id not in rules_by_id:
            rules_by_id[rule_id] = ReportingDescriptor(
                id=rule_id,
                name=str(finding.get("area") or "KnowNet finding"),
                properties={
                    "knownet": {
                        "area": finding.get("area"),
                        "severity": finding.get("severity"),
                    }
                },
            )
        locations, omitted_locations = source_locations_from_row(finding)
        readiness = code_scanning_readiness(finding, locations)
        if readiness["code_scanning_ready"]:
            code_scanning_ready_count += 1
        else:
            for reason in readiness["code_scanning_ready_reasons"]:
                not_ready_reasons[reason] = not_ready_reasons.get(reason, 0) + 1
        omitted_location_count += len(omitted_locations)
        result = Result(
            guid=guid_for_finding(finding),
            rule_id=rule_id,
            level=sarif_level(str(finding.get("severity") or "info")),
            message=Message(text=str(finding.get("title") or "KnowNet finding")),
            locations=_locations_for_source_locations(locations) or None,
            partial_fingerprints={
                "knownetFindingId": str(finding.get("id") or finding.get("finding_id") or ""),
                "knownetContentFingerprint": content_fingerprint(finding, locations),
            },
            properties=_knownet_properties(finding, omitted_locations=omitted_locations, readiness=readiness),
        )
        results.append(result)
    log = SarifLog(
        version=SARIF_VERSION,
        schema_uri=SARIF_SCHEMA_URI,
        runs=[
            Run(
                tool=Tool(
                    driver=ToolComponent(
                        name=KNOWNET_TOOL_NAME,
                        information_uri="https://github.com/officialjaykoo/knownet",
                        rules=list(rules_by_id.values()),
                    )
                ),
                results=results,
                properties={
                    "knownet": {
                        "run_id": run_id,
                        "generated_at": generated_at,
                        "finding_count": len(results),
                        "omitted_location_count": omitted_location_count,
                        "code_scanning_ready_summary": {
                            "total_results": len(results),
                            "ready": code_scanning_ready_count,
                            "not_ready_reasons": not_ready_reasons,
                        },
                    }
                },
            )
        ],
    )
    return sarif_to_dict(log)
