from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPO_ROOT / "apps" / "api" / "tests" / "fixtures"


def load_json_fixture(relative_path: str) -> dict[str, Any]:
    path = FIXTURE_ROOT / relative_path
    return json.loads(path.read_text(encoding="utf-8"))


def load_json_fixture_dir(relative_path: str) -> list[dict[str, Any]]:
    path = FIXTURE_ROOT / relative_path
    return [json.loads(item.read_text(encoding="utf-8")) for item in sorted(path.glob("*.json"))]
