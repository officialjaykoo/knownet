from __future__ import annotations

import json
from pathlib import Path


REQUIRED_PROFILE_FIELDS = {
    "id",
    "display_name",
    "github_references",
    "best_paid_path",
    "realistic_free_path",
    "implemented_surface",
    "test_status",
    "requires_paid_or_external_setup",
    "connection_modes",
    "do_not_add",
}

EXPECTED_PROFILES = {"chatgpt", "claude", "gemini", "manus", "deepseek", "qwen", "kimi", "minimax", "glm"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    root = _repo_root()
    profile_dir = root / "apps" / "mcp" / "client_profiles"
    config_dir = root / "apps" / "mcp" / "configs"
    errors: list[str] = []

    profiles = {}
    for path in sorted(profile_dir.glob("*.json")):
        try:
            payload = _load_json(path)
        except json.JSONDecodeError as error:
            errors.append(f"{path}: invalid JSON: {error}")
            continue
        profile_id = payload.get("id")
        profiles[profile_id] = payload
        missing = sorted(REQUIRED_PROFILE_FIELDS - set(payload))
        if missing:
            errors.append(f"{path}: missing fields {missing}")
        if path.stem != profile_id:
            errors.append(f"{path}: filename must match id={profile_id}")
        if not isinstance(payload.get("github_references"), list) or not payload["github_references"]:
            errors.append(f"{path}: github_references must be non-empty")
        if not isinstance(payload.get("connection_modes"), list) or not payload["connection_modes"]:
            errors.append(f"{path}: connection_modes must be non-empty")
        for index, mode in enumerate(payload.get("connection_modes") or []):
            if not isinstance(mode, dict) or not mode.get("mode"):
                errors.append(f"{path}: connection_modes[{index}] must include mode")
            template = mode.get("config_template")
            if template and not (root / template).exists():
                errors.append(f"{path}: config_template does not exist: {template}")
        surface = payload.get("implemented_surface")
        if surface and surface.startswith("apps/mcp/configs/"):
            if not (root / surface).exists():
                errors.append(f"{path}: implemented_surface does not exist: {surface}")

    missing_profiles = sorted(EXPECTED_PROFILES - set(profiles))
    extra_profiles = sorted(set(profiles) - EXPECTED_PROFILES)
    if missing_profiles:
        errors.append(f"missing profiles: {missing_profiles}")
    if extra_profiles:
        errors.append(f"extra profiles: {extra_profiles}")

    for path in sorted(config_dir.glob("*.json")):
        try:
            _load_json(path)
        except json.JSONDecodeError as error:
            errors.append(f"{path}: invalid JSON: {error}")

    report = {
        "ok": not errors,
        "profile_count": len(profiles),
        "config_json_count": len(list(config_dir.glob("*.json"))),
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
