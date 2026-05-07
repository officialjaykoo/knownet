from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import Any

import attr
from sarif_om import (
    ArtifactLocation,
    Location,
    Message,
    PhysicalLocation,
    ReportingDescriptor,
    Result,
    Run,
    SarifLog,
    Tool,
    ToolComponent,
)

from .ignore_policy import classify_path


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


def safe_sarif_path(path: str | None) -> tuple[str | None, str | None]:
    if not path:
        return None, None
    raw = str(path).strip().replace("\\", "/")
    if not raw or re.match(r"^[A-Za-z]:/", raw) or raw.startswith("/"):
        return None, "absolute_path"
    normalized = str(PurePosixPath(raw))
    if normalized.startswith("../") or "/../" in normalized or normalized == "..":
        return None, "parent_reference"
    classified = classify_path(normalized)
    if classified.get("blocked"):
        return None, str(classified.get("reason") or "blocked_path")
    return str(classified.get("path") or normalized), None


def changed_files_from_row(row: dict[str, Any]) -> tuple[list[str], list[dict[str, str]]]:
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
            safe_path, reason = safe_sarif_path(str(candidate))
            if safe_path:
                if safe_path not in paths:
                    paths.append(safe_path)
            else:
                omitted.append({"path": str(candidate), "reason": reason or "unsafe_path"})
    return paths, omitted


def _locations_for_paths(paths: list[str]) -> list[Location]:
    return [
        Location(
            physical_location=PhysicalLocation(
                artifact_location=ArtifactLocation(uri=path),
            )
        )
        for path in paths
    ]


def _knownet_properties(finding: dict[str, Any], *, omitted_locations: list[dict[str, str]]) -> dict[str, Any]:
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
        paths, omitted_locations = changed_files_from_row(finding)
        omitted_location_count += len(omitted_locations)
        result = Result(
            guid=str(finding.get("id") or finding.get("finding_id") or ""),
            rule_id=rule_id,
            level=sarif_level(str(finding.get("severity") or "info")),
            message=Message(text=str(finding.get("title") or "KnowNet finding")),
            locations=_locations_for_paths(paths) or None,
            partial_fingerprints={"knownetFindingId": str(finding.get("id") or finding.get("finding_id") or "")},
            properties=_knownet_properties(finding, omitted_locations=omitted_locations),
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
                    }
                },
            )
        ],
    )
    return sarif_to_dict(log)
