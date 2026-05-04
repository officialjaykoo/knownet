from __future__ import annotations

import json
from statistics import median
from typing import Any

from .project_snapshot import model_run_summary


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def model_run_observation(row: dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data["request"] = data.get("request") if isinstance(data.get("request"), dict) else _json_loads(data.get("request_json"))
    data["response"] = data.get("response") if isinstance(data.get("response"), dict) else _json_loads(data.get("response_json"))
    summary = model_run_summary(data)
    return {
        "run_id": summary["id"],
        "trace_id": summary.get("trace_id"),
        "packet_trace_id": summary.get("packet_trace_id"),
        "provider": summary.get("provider"),
        "model": summary.get("model"),
        "prompt_profile": summary.get("prompt_profile"),
        "status": summary.get("status"),
        "duration_ms": summary.get("duration_ms"),
        "input_tokens": summary.get("input_tokens"),
        "output_tokens": summary.get("output_tokens"),
        "error_code": summary.get("error_code"),
        "error_message": summary.get("error_message"),
        "evidence_quality": summary.get("evidence_quality"),
        "updated_at": summary.get("updated_at"),
        "detail_url": summary.get("detail_url"),
        "provenance": summary.get("provenance"),
    }


def provider_observation_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    observations = [model_run_observation(row) for row in rows]
    by_provider: dict[str, dict[str, Any]] = {}
    for observation in observations:
        provider = observation.get("provider") or "unknown"
        item = by_provider.setdefault(
            provider,
            {
                "provider": provider,
                "success_count": 0,
                "failure_count": 0,
                "consecutive_failures": 0,
                "durations_ms": [],
                "latest_failure": None,
            },
        )
        if observation.get("status") == "failed":
            item["failure_count"] += 1
            if item["success_count"] == 0:
                item["consecutive_failures"] += 1
            if item["latest_failure"] is None:
                item["latest_failure"] = observation
        else:
            item["success_count"] += 1
        if isinstance(observation.get("duration_ms"), int):
            item["durations_ms"].append(observation["duration_ms"])
    for item in by_provider.values():
        durations = sorted(item.pop("durations_ms"))
        item["p50_duration_ms"] = int(median(durations)) if durations else None
        item["p95_duration_ms"] = durations[min(len(durations) - 1, int(len(durations) * 0.95))] if durations else None
        item["stability_alert"] = item["consecutive_failures"] >= 3
    return {"providers": list(by_provider.values()), "total_runs": len(observations)}

