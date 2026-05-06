from __future__ import annotations

import fnmatch
import re
from pathlib import PurePosixPath
from typing import Any


FORBIDDEN_PATH_PATTERNS = (
    ".env",
    ".env.*",
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    "*.pem",
    "*.key",
    "*.p12",
    "id_rsa",
    "id_ed25519",
    ".git",
    ".git/*",
    ".local",
    ".local/*",
    "node_modules",
    "node_modules/*",
    "data/knownet.db",
    "data/*.db",
    "data/backups",
    "data/backups/*",
    "data/sessions",
    "data/sessions/*",
    "target",
    "target/*",
    "dist",
    "dist/*",
    ".next",
    ".next/*",
    "__pycache__",
    "__pycache__/*",
)

SECRET_KEY_RE = re.compile(r"(?i)(secret|password|token|api[_-]?key|private[_-]?key|credential)")
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?im)^\s*(ADMIN_TOKEN|OPENAI_API_KEY|GEMINI_API_KEY|DEEPSEEK_API_KEY|MINIMAX_API_KEY|KIMI_API_KEY|MOONSHOT_API_KEY|GLM_API_KEY|ZAI_API_KEY|Z_AI_API_KEY|QWEN_API_KEY|API_KEY|SECRET|PASSWORD)\s*="
)
LOCAL_PATH_RE = re.compile(r"(?i)\b[A-Z]:[\\/][^\s\"']+")
FORBIDDEN_MARKER_RE = re.compile(r"(?i)(raw_token|token_hash|\.env|knownet\.db|\.db\b|backups[\\/]|sessions?[\\/]|users?[\\/])")


def _normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.strip("/")


def classify_path(path: str | None) -> dict[str, Any]:
    if not path:
        return {"blocked": False, "reason": None}
    normalized = _normalize_path(str(path))
    name = PurePosixPath(normalized).name
    parts = [part.lower() for part in PurePosixPath(normalized).parts]
    for pattern in FORBIDDEN_PATH_PATTERNS:
        pattern_lower = pattern.lower()
        pattern_name = pattern_lower.rstrip("/*")
        if (
            fnmatch.fnmatch(normalized.lower(), pattern_lower)
            or fnmatch.fnmatch(name.lower(), pattern_lower)
            or ("/" not in pattern_name and pattern_name in parts)
        ):
            return {"blocked": True, "reason": "forbidden_path_pattern", "pattern": pattern, "path": normalized}
    return {"blocked": False, "reason": None, "path": normalized}


def is_forbidden_path(path: str | None) -> bool:
    return bool(classify_path(path).get("blocked"))


def forbidden_text_reason(text: str) -> dict[str, Any] | None:
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if SECRET_ASSIGNMENT_RE.search(line):
            return {"reason": "secret_assignment", "line": line_number}
    if LOCAL_PATH_RE.search(text):
        return {"reason": "local_path"}
    marker = FORBIDDEN_MARKER_RE.search(text)
    if marker:
        return {"reason": "forbidden_marker", "marker": marker.group(0)}
    return None


def assert_safe_text(text: str, *, code: str, message: str, label: str) -> None:
    reason = forbidden_text_reason(text)
    if reason:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail={"code": code, "message": message, "details": {"label": label, **reason}})


def assert_safe_json_keys(value: Any, *, code: str, message: str, label: str) -> None:
    from fastapi import HTTPException

    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            if SECRET_KEY_RE.search(key_text):
                raise HTTPException(status_code=422, detail={"code": code, "message": message, "details": {"label": f"{label}.{key}"}})
            assert_safe_json_keys(child, code=code, message=message, label=f"{label}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_safe_json_keys(child, code=code, message=message, label=f"{label}[{index}]")
    elif isinstance(value, str):
        assert_safe_text(value, code=code, message=message, label=label)
