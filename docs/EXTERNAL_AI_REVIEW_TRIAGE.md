# External AI Review Triage

```json
{
  "schema": "knownet.external_ai_review_triage.v1",
  "scope": "Phase 14 external AI review round",
  "source_log": "docs/EXTERNAL_AI_ACCESS_LOG.md",
  "triage_policy": {
    "original_reviews_preserved": true,
    "false_positives_removed_from_action_queue": true,
    "duplicates_merged_into_issue_groups": true,
    "status_meaning": {
      "resolved": "Code or docs were changed during the review round and verified.",
      "intentional": "Reported behavior is correct by design and should not be changed.",
      "deferred": "Real concern, but not required to finish Phase 14.",
      "false_positive": "Reviewer observation contradicted live endpoint verification.",
      "monitor": "Keep visible as release/operations context."
    }
  },
  "reviewer_families": [
    "claude",
    "chatgpt",
    "gemini",
    "manus",
    "deepseek",
    "qwen_3_6_plus",
    "kimi",
    "minimax_agent",
    "glm_5_turbo"
  ],
  "merged_issue_groups": [
    {
      "id": "mcp_get_preview_contract",
      "status": "resolved",
      "severity": "high",
      "areas": ["API", "Docs"],
      "reported_by": ["deepseek", "kimi", "minimax_agent", "glm_5_turbo"],
      "summary": "GET-only clients needed clearer boundaries between discovery, safe resource previews, and JSON-RPC tool calls.",
      "resolution": [
        "GET /mcp remains discovery only.",
        "GET /mcp?resource=agent:onboarding returns onboarding payload.",
        "GET /mcp?resource=agent:state-summary returns state-summary payload.",
        "Discovery now states that search/fetch/dry-run require JSON-RPC POST.",
        "Docs state that dry-run is POST-only so review bodies are not put into URLs or GET logs."
      ],
      "verification": [
        "GET /mcp returned discovery with release_status and GET preview note.",
        "GET /mcp?resource=agent:onboarding returned data.id=agent:onboarding and data.payload.",
        "GET /mcp?resource=agent:state-summary returned data.id=agent:state-summary and data.payload."
      ]
    },
    {
      "id": "state_summary_machine_readability",
      "status": "resolved",
      "severity": "medium",
      "areas": ["API", "Data", "Ops"],
      "reported_by": ["chatgpt", "qwen_3_6_plus", "kimi", "minimax_agent"],
      "summary": "State summary needed stronger first-agent fields, release blockers, graph count consistency, and AI-state drift flags.",
      "resolution": [
        "first_agent_brief includes current_phase, current_focus, current_priorities, implementation_status, verification_status, risk_mitigation_status, and next_best_actions.",
        "phase_status includes release_ready and release_ready_blockers.",
        "graph_node_breakdown.other_nodes now subtracts all explicit node types instead of double-counting.",
        "state-summary includes ai_state_pages_match and drift_suspected."
      ],
      "verification": [
        "Live state-summary showed graph_nodes=625, explicit type sum=625, other_nodes=0.",
        "Live state-summary showed ai_state_pages_match=true and drift_suspected=false."
      ]
    },
    {
      "id": "security_boundary_visibility",
      "status": "resolved",
      "severity": "medium",
      "areas": ["Security", "API"],
      "reported_by": ["claude", "deepseek", "qwen_3_6_plus"],
      "summary": "External agents needed explicit security boundaries in the first readable surfaces.",
      "resolution": [
        "Onboarding and state-summary include security_boundary_policy.",
        "Discovery auth note says scoped tokens are never returned.",
        "knownet_me description says it returns scoped permissions and never raw token values.",
        "GET previews expose only safe onboarding and state-summary context."
      ]
    },
    {
      "id": "finding_parser_and_source_metadata",
      "status": "resolved",
      "severity": "medium",
      "areas": ["API", "Docs"],
      "reported_by": ["manus", "chatgpt"],
      "summary": "Review parser and dry-run metadata needed to preserve titles and source_agent/source_model.",
      "resolution": [
        "Finding parser accepts explicit Title fields and bold labels.",
        "Dry-run honors provided source_agent and source_model.",
        "handoff_format requires Title and includes valid/invalid examples."
      ]
    },
    {
      "id": "local_path_exposure",
      "status": "resolved",
      "severity": "high",
      "areas": ["Security", "Data"],
      "reported_by": ["claude"],
      "summary": "AI-state responses exposed local source paths.",
      "resolution": [
        "Agent AI state strips source_path and nested source.path.",
        "Responses use safe source_ref/content_hash style fields instead of host filesystem paths."
      ]
    },
    {
      "id": "quick_tunnel_not_production",
      "status": "monitor",
      "severity": "critical",
      "areas": ["Security", "Ops"],
      "reported_by": ["qwen_3_6_plus", "minimax_agent", "glm_5_turbo"],
      "summary": "Cloudflare quick tunnel is suitable for tests but not operational external access.",
      "current_state": [
        "Discovery exposes infrastructure_notice.tunnel_type=temporary_quick_tunnel.",
        "Discovery exposes release_status.release_ready=false.",
        "State-summary phase_status includes release_ready_blockers."
      ],
      "next_action_before_real_external_use": "Move to a named tunnel with access controls, short-lived scoped tokens, and operator-managed revocation."
    },
    {
      "id": "tool_resource_semantics",
      "status": "resolved",
      "severity": "medium",
      "areas": ["API", "Docs"],
      "reported_by": ["glm_5_turbo"],
      "summary": "State summary exists as both a tool and a resource, which needed semantic clarification.",
      "resolution": [
        "MCP docs now state that knownet_state_summary and knownet://agent/state-summary expose the same state through different MCP surfaces.",
        "Tool-capable clients should call the tool; resource-oriented clients should read/fetch the resource; GET-only clients use the HTTP preview."
      ]
    }
  ],
  "false_positives": [
    {
      "id": "glm_get_preview_returns_discovery",
      "reported_by": "glm_5_turbo",
      "claim": "All three endpoints returned identical discovery schema.",
      "reason": "Live verification showed /mcp?resource=agent:onboarding and /mcp?resource=agent:state-summary return resource-specific data.payload."
    },
    {
      "id": "minimax_first_agent_brief_missing",
      "reported_by": "minimax_agent",
      "claim": "state-summary does not include first_agent_brief.",
      "reason": "Live verification showed first_agent_brief.current_focus and related fields are present."
    },
    {
      "id": "public_repository_security_findings",
      "reported_by": "deepseek",
      "claim": "Findings based on unrelated public repository search results.",
      "reason": "Reviewer used public search fallback before binding to KnowNet state. These are not KnowNet findings."
    }
  ],
  "intentional_non_changes": [
    {
      "id": "get_dry_run_endpoint",
      "reported_by": ["minimax_agent", "deepseek", "kimi"],
      "decision": "Do not add GET dry-run.",
      "reason": "Review bodies must not be placed in URLs or GET logs. Dry-run remains JSON-RPC POST or scoped API POST."
    },
    {
      "id": "remove_tool_or_resource_state_summary",
      "reported_by": "glm_5_turbo",
      "decision": "Keep both tool and resource.",
      "reason": "MCP clients differ. Tool-capable clients use knownet_state_summary; resource-oriented or connector fallback clients use resource/fetch/GET preview."
    }
  ],
  "deferred_real_issues": [
    {
      "id": "named_tunnel_and_access_controls",
      "severity": "critical",
      "area": "Ops",
      "reason": "Required before operational external use, but quick tunnel is acceptable for this review round."
    },
    {
      "id": "future_direct_write_optimistic_locking",
      "severity": "medium",
      "area": "Data",
      "reason": "Current external agents do not receive raw write_revision tools. If direct page-write APIs are exposed later, require base_revision_id."
    }
  ],
  "phase_14_closeout": {
    "complete": true,
    "remaining_phase_14_blocker": null,
    "next_recommended_work": [
      "Keep quick tunnel testing temporary.",
      "Revoke temporary test tokens after the review window.",
      "Before real external operation, replace quick tunnel with named tunnel and access controls."
    ]
  },
  "phase_15_hardening_status": {
    "status": "triaged_in_db",
    "pending_findings": 0,
    "pending_reviews": 0,
    "note": "Phase 15 applied DB finding decisions from this merged triage. Original reviews and findings remain preserved."
  }
}
```
