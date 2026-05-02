from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def profiles_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "client_profiles"


def load_client_profiles() -> dict[str, Any]:
    root = profiles_dir()
    profiles: dict[str, Any] = {}
    if not root.exists():
        return profiles
    for path in sorted(root.glob("*.json")):
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        key = str(payload.get("id") or path.stem)
        profiles[key] = payload
    return profiles
