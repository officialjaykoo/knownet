# Release Hardening Run

```json
{
  "schema": "knownet.phase15_hardening_run.v1",
  "started_at": "2026-05-02T17:43:32.814716Z",
  "api_base": "http://127.0.0.1:8000",
  "verify_index_before": {
    "status": 200,
    "ok": true,
    "issues": []
  },
  "token_cleanup": {
    "revoked_test_tokens": [],
    "kept_token_ids": [
      "agent_55b5a5bf6896"
    ],
    "revoked_api_status": 401,
    "revoked_mcp_ok": false,
    "revoked_mcp_error": "auth_failed"
  },
  "finding_triage": {
    "decisions": {},
    "implementation_records_added": 0
  },
  "mcp_flow": {
    "calls": {
      "knownet_start_here": true,
      "knownet_me": true,
      "knownet_state_summary": true,
      "knownet_ai_state": true,
      "knownet_review_dry_run": true,
      "knownet_submit_review": true
    },
    "finding_id": "finding_f06003742915",
    "ai_state_security": {
      "status": 200,
      "forbidden_hits": [],
      "truncated": true
    },
    "token_revoked": "agent_0543bf791525"
  },
  "performance": {
    "timings": {
      "api_pages": {
        "status": 200,
        "median_ms": 41.29,
        "bytes": 18004
      },
      "api_first_page": {
        "status": 200,
        "median_ms": 55.9,
        "bytes": 1775
      },
      "agent_ai_state": {
        "status": 200,
        "median_ms": 78.79,
        "bytes": 61304
      },
      "agent_state_summary": {
        "status": 200,
        "median_ms": 119.31,
        "bytes": 4760
      },
      "api_graph": {
        "status": 200,
        "median_ms": 50.09,
        "bytes": 66684
      },
      "citation_audits": {
        "status": 200,
        "median_ms": 20.12,
        "bytes": 37468
      },
      "mcp_discovery": {
        "status": 200,
        "median_ms": 3.79,
        "bytes": 7774
      },
      "mcp_onboarding_preview": {
        "status": 200,
        "median_ms": 64.13,
        "bytes": 16725
      },
      "mcp_state_summary_preview": {
        "status": 200,
        "median_ms": 103.71,
        "bytes": 9620
      },
      "web_initial_load": {
        "status": 200,
        "median_ms": 5.65,
        "bytes": 12847
      }
    },
    "large_response_guard": {
      "status": 200,
      "truncated": true,
      "next_offset": 1,
      "forbidden_hits": []
    }
  },
  "snapshot": {
    "name": "knownet-snapshot-20260502T174337-0deb7267.tar.gz",
    "format": "tar.gz",
    "manifest_present": true,
    "size_bytes": 446174
  },
  "docs_db_cross_check": {
    "triage_doc_exists": true,
    "triage_mentions_phase15": true,
    "pending_findings": 0,
    "pending_reviews": 0
  },
  "verify_index_after": {
    "status": 200,
    "ok": true,
    "issues": []
  },
  "completed_at": "2026-05-02T17:43:38.096844Z",
  "counts_after": {
    "tables": {
      "pages": 64,
      "collaboration_reviews": 13,
      "collaboration_findings": 59,
      "implementation_records": 12,
      "graph_nodes": 630,
      "ai_state_pages": 64
    },
    "finding_statuses": {
      "accepted": 5,
      "deferred": 4,
      "implemented": 12,
      "rejected": 38
    }
  }
}
```
