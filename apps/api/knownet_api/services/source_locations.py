from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from .ignore_policy import classify_path, forbidden_text_reason


_SOURCE_REF_RE = re.compile(r"^([^#]+?)(?:#L([1-9]\d*)(?:-L([1-9]\d*))?)?$")
_LINE_RANGE_RE = re.compile(r"^\s*([1-9]\d*)(?:\s*-\s*([1-9]\d*))?\s*$")


def _normalize_path(path: str | None) -> str:
    value = str(path or "").strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return value


def safe_source_path(path: str | None) -> tuple[str | None, str | None]:
    value = _normalize_path(path)
    if not value:
        return None, "empty_path"
    if re.search(r"\s", value):
        return None, "unsafe_whitespace"
    if re.match(r"^[A-Za-z]:/", value) or value.startswith("/") or value.startswith("//"):
        return None, "absolute_path"
    normalized = str(PurePosixPath(value))
    if normalized.startswith("../") or "/../" in normalized or normalized == "..":
        return None, "parent_reference"
    classified = classify_path(normalized)
    if classified.get("blocked"):
        return None, str(classified.get("reason") or "blocked_path")
    return str(classified.get("path") or normalized), None


def parse_line_range(value: str | None) -> tuple[int | None, int | None, str | None]:
    if not value:
        return None, None, None
    match = _LINE_RANGE_RE.match(str(value))
    if not match:
        return None, None, "invalid_line_range"
    start = int(match.group(1))
    end = int(match.group(2) or match.group(1))
    if end < start:
        return None, None, "invalid_range"
    return start, end, None


def parse_source_location_ref(ref: str | None) -> dict[str, Any]:
    value = str(ref or "").strip().replace("\\", "/")
    match = _SOURCE_REF_RE.match(value)
    if not match:
        if "#L0" in value or re.search(r"#L-\d+", value):
            return {"status": "rejected", "reason": "invalid_line_range", "raw": value}
        safe_path, reason = safe_source_path(value.split("#", 1)[0])
        return {"status": "rejected", "reason": reason or "invalid_source_ref", "raw": value, "path": safe_path}

    safe_path, reason = safe_source_path(match.group(1))
    if not safe_path:
        return {"status": "rejected", "reason": reason or "unsafe_path", "raw": value}
    start = int(match.group(2)) if match.group(2) else None
    end = int(match.group(3)) if match.group(3) else start
    if start is not None and end is not None and end < start:
        return {"status": "rejected", "reason": "invalid_range", "raw": value}
    return {"status": "accepted", "path": safe_path, "start_line": start, "end_line": end}


def normalize_source_location(
    *,
    path: str | None,
    lines: str | None = None,
    start_line: Any = None,
    end_line: Any = None,
    snippet: str | None = None,
) -> dict[str, Any]:
    if not path:
        return {
            "source_path": None,
            "source_start_line": None,
            "source_end_line": None,
            "source_snippet": None,
            "source_location_status": "omitted",
        }

    parsed = parse_source_location_ref(str(path))
    if parsed.get("status") != "accepted":
        return {
            "source_path": None,
            "source_start_line": None,
            "source_end_line": None,
            "source_snippet": None,
            "source_location_status": f"rejected:{parsed.get('reason') or 'unsafe_path'}",
        }

    parsed_start = parsed.get("start_line")
    parsed_end = parsed.get("end_line")
    if lines:
        line_start, line_end, reason = parse_line_range(lines)
        if reason:
            return {
                "source_path": parsed["path"],
                "source_start_line": None,
                "source_end_line": None,
                "source_snippet": None,
                "source_location_status": f"rejected:{reason}",
            }
        parsed_start, parsed_end = line_start, line_end
    elif start_line is not None:
        try:
            parsed_start = int(start_line)
            parsed_end = int(end_line if end_line is not None else parsed_start)
        except (TypeError, ValueError):
            return {
                "source_path": parsed["path"],
                "source_start_line": None,
                "source_end_line": None,
                "source_snippet": None,
                "source_location_status": "rejected:invalid_line_range",
            }
        if parsed_start < 1 or parsed_end < parsed_start:
            return {
                "source_path": parsed["path"],
                "source_start_line": None,
                "source_end_line": None,
                "source_snippet": None,
                "source_location_status": "rejected:invalid_range",
            }

    clean_snippet = (snippet or "").strip() or None
    if clean_snippet and forbidden_text_reason(clean_snippet):
        return {
            "source_path": parsed["path"],
            "source_start_line": parsed_start,
            "source_end_line": parsed_end,
            "source_snippet": None,
            "source_location_status": "rejected:secret_snippet",
        }

    return {
        "source_path": parsed["path"],
        "source_start_line": parsed_start,
        "source_end_line": parsed_end,
        "source_snippet": clean_snippet,
        "source_location_status": "accepted",
    }
