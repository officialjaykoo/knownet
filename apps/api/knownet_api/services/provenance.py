from __future__ import annotations

import re
from typing import Any


FORBIDDEN_PROVENANCE_RE = re.compile(
    r"(?i)([A-Z]:[\\/]|\.env|\.db|backups[\\/]|sessions?[\\/]|users?[\\/]|token|secret|password|api[_-]?key)"
)


def compact_provenance(
    *,
    source_type: str,
    source_id: str | None = None,
    source_packet_id: str | None = None,
    source_packet_trace_id: str | None = None,
    source_model_run_id: str | None = None,
    source_model_run_trace_id: str | None = None,
    source_finding_id: str | None = None,
    evidence_quality: str | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    provenance = {
        "source_type": source_type,
        "source_id": source_id,
        "source_packet_id": source_packet_id,
        "source_packet_trace_id": source_packet_trace_id,
        "source_model_run_id": source_model_run_id,
        "source_model_run_trace_id": source_model_run_trace_id,
        "source_finding_id": source_finding_id,
        "evidence_quality": evidence_quality,
        "updated_at": updated_at,
    }
    return {key: value for key, value in provenance.items() if value not in {None, ""}}


def validate_provenance_safe(provenance: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key, value in provenance.items():
        if isinstance(value, str) and FORBIDDEN_PROVENANCE_RE.search(value):
            errors.append(f"provenance_forbidden_value:{key}")
    return errors

