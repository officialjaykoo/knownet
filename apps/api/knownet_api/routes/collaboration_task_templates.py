from __future__ import annotations


def task_prompt_from_finding(row: dict) -> str:
    parts = [
        f"Implement accepted KnowNet finding: {row['title']}",
        f"Finding id: {row['id']}",
        f"Severity: {row['severity']}",
        f"Area: {row['area']}",
        f"Evidence quality: {row.get('evidence_quality') or 'unspecified'}",
    ]
    if row.get("evidence"):
        parts.append(f"Evidence: {row['evidence']}")
    if row.get("proposed_change"):
        parts.append(f"Requested change: {row['proposed_change']}")
    parts.append("Keep the change scoped. Record implementation evidence after verification.")
    return "\n\n".join(parts)


def verification_from_finding(row: dict) -> str:
    area = str(row.get("area") or "").lower()
    if area == "docs":
        return "Run targeted docs/schema checks or explain why no executable check applies."
    if area in {"api", "security", "ops", "data"}:
        return "Run targeted API tests for the changed route/service and verify-index when collaboration state changes."
    if area == "ui":
        return "Run the web build and any targeted UI checks for the changed surface."
    if area == "rust":
        return "Run the targeted Rust test or cargo test for the affected crate."
    return "Run the smallest targeted verification that proves the finding is handled."


def priority_from_finding(row: dict) -> str:
    return "high" if row.get("severity") in {"critical", "high"} else "normal"


def should_auto_create_task(row: dict) -> bool:
    return row.get("severity") in {"critical", "high"} and row.get("evidence_quality") in {"direct_access", "operator_verified"}


def implementation_task_template(row: dict) -> dict:
    finding_id = row["finding_id"] if row.get("finding_id") else row["id"]
    return {
        "endpoint": f"/api/collaboration/findings/{finding_id}/implementation-evidence",
        "method": "POST",
        "body": {
            "dry_run": True,
            "changed_files": [],
            "verification": row.get("expected_verification") or verification_from_finding(row),
            "notes": "Targeted implementation evidence.",
        },
    }


def simple_evidence_template(finding_id: str) -> dict:
    return {
        "endpoint": f"/api/collaboration/findings/{finding_id}/evidence",
        "method": "POST",
        "body": {"implemented": True, "commit": None, "note": "Implemented and verified with targeted checks."},
    }


def task_creation_template(row: dict) -> dict:
    return {
        "endpoint": f"/api/collaboration/findings/{row['id']}/task",
        "method": "POST",
        "body": {
            "priority": priority_from_finding(row),
            "owner": "codex",
            "task_prompt": task_prompt_from_finding(row),
            "expected_verification": verification_from_finding(row),
        },
    }
