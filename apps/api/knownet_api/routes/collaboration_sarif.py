from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from ..db.sqlite import fetch_all
from ..security import Actor, require_review_access, utc_now
from ..services.sarif_export import (
    DEFAULT_EXPORT_STATUSES,
    TRUSTED_DEFAULT_EVIDENCE,
    build_sarif_log,
    validate_sarif_log,
)

router = APIRouter(prefix="/api/collaboration", tags=["collaboration"])


def _csv_filter(value: str | None, *, allowed: set[str], default: set[str]) -> set[str]:
    if not value:
        return set(default)
    if value.strip().lower() == "all":
        return set(allowed)
    parsed = {item.strip().lower() for item in value.split(",") if item.strip()}
    invalid = parsed - allowed
    if invalid:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "sarif_export_invalid_filter",
                "message": "Invalid SARIF export filter",
                "details": {"invalid": sorted(invalid), "allowed": sorted(allowed)},
            },
        )
    return parsed or set(default)


@router.get("/findings.sarif")
async def export_findings_sarif(
    request: Request,
    vault_id: str = "local-default",
    status: str | None = None,
    severity: str | None = None,
    evidence_quality: str | None = None,
    limit: int = 100,
    actor: Actor = Depends(require_review_access),
):
    _ = actor
    statuses = _csv_filter(
        status,
        allowed={"pending", "needs_more_context", "accepted", "deferred", "implemented", "rejected"},
        default=DEFAULT_EXPORT_STATUSES,
    )
    severities = _csv_filter(
        severity,
        allowed={"critical", "high", "medium", "low", "info"},
        default={"critical", "high", "medium", "low", "info"},
    )
    qualities = _csv_filter(
        evidence_quality,
        allowed={"direct_access", "operator_verified", "context_limited", "inferred", "unspecified"},
        default=TRUSTED_DEFAULT_EVIDENCE,
    )
    limit = max(1, min(limit, 500))
    status_placeholders = ",".join("?" for _ in statuses)
    severity_placeholders = ",".join("?" for _ in severities)
    quality_placeholders = ",".join("?" for _ in qualities)
    rows = await fetch_all(
        request.app.state.settings.sqlite_path,
        "SELECT f.*, r.vault_id, r.source_agent, r.source_model, "
        "fe.evidence, fe.proposed_change, COALESCE(fe.evidence_quality, 'unspecified') AS evidence_quality, "
        "fl.source_path, fl.source_start_line, fl.source_end_line, fl.source_snippet, "
        "COALESCE(fl.source_location_status, 'omitted') AS source_location_status, "
        "GROUP_CONCAT(i.commit_sha, '|') AS commit_shas, GROUP_CONCAT(i.changed_files, '||') AS changed_files_json "
        "FROM findings f "
        "JOIN reviews r ON r.id = f.review_id "
        "LEFT JOIN finding_evidence fe ON fe.finding_id = f.id "
        "LEFT JOIN finding_locations fl ON fl.finding_id = f.id "
        "LEFT JOIN implementation_records i ON i.finding_id = f.id "
        f"WHERE r.vault_id = ? AND f.status IN ({status_placeholders}) AND f.severity IN ({severity_placeholders}) "
        f"AND COALESCE(fe.evidence_quality, 'unspecified') IN ({quality_placeholders}) "
        "GROUP BY f.id "
        "ORDER BY CASE f.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END, f.updated_at DESC "
        "LIMIT ?",
        (vault_id, *sorted(statuses), *sorted(severities), *sorted(qualities), limit),
    )
    generated_at = utc_now()
    sarif = build_sarif_log(rows, run_id=f"knownet-sarif-{generated_at}", generated_at=generated_at)
    validation_errors = validate_sarif_log(sarif)
    if validation_errors:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "sarif_export_invalid",
                "message": "Generated SARIF failed schema validation",
                "details": {"errors": validation_errors},
            },
        )
    return JSONResponse(content=sarif, media_type="application/sarif+json")
