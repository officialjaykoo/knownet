"use client";

import { AlertTriangle, ArrowRight, RefreshCw } from "lucide-react";
import type { Workspace } from "./WorkspaceTabs";

export type NextAction = {
  action_type?: string;
  priority?: "urgent" | "high" | "normal" | "low" | string;
  title?: string;
  detail?: string;
  next_endpoint?: string;
  method?: string;
  task_template?: Record<string, unknown> | null;
  empty_state?: boolean | { active?: boolean; reason?: string; message?: string; operator_question?: string };
  suggested_params?: Record<string, unknown>;
};

type NextWorkspaceProps = {
  action: NextAction | null;
  error: string | null;
  loading: boolean;
  onRefresh: () => void;
  onOpenWorkspace: (workspace: Workspace) => void;
};

function workspaceForAction(action: NextAction | null): Workspace {
  const actionType = (action?.action_type || "").toLowerCase();
  if (actionType.includes("packet") || actionType.includes("snapshot")) {
    return "packets";
  }
  if (actionType.includes("review") || actionType.includes("finding")) {
    return "reviews";
  }
  if (actionType.includes("task") || actionType.includes("implement")) {
    return "tasks";
  }
  if (actionType.includes("provider") || actionType.includes("model") || actionType.includes("run_ai")) {
    return "ops";
  }
  return "packets";
}

function fallbackWorkspace(primary: Workspace): Workspace {
  if (primary === "packets") return "reviews";
  if (primary === "reviews") return "tasks";
  if (primary === "tasks") return "packets";
  return "ops";
}

function emptyStateText(emptyState: NextAction["empty_state"]): string | null {
  if (!emptyState) {
    return null;
  }
  if (emptyState === true) {
    return "No sources or findings are loaded yet. Confirm whether this is a fresh install or a data-load issue.";
  }
  return emptyState.operator_question || emptyState.message || emptyState.reason || null;
}

export function NextWorkspace({ action, error, loading, onRefresh, onOpenWorkspace }: NextWorkspaceProps) {
  const primaryWorkspace = workspaceForAction(action);
  const secondaryWorkspace = fallbackWorkspace(primaryWorkspace);
  const emptyState = emptyStateText(action?.empty_state);

  return (
    <section className="next-workspace" aria-label="Next workspace">
      <div className="workspace-dashboard-head">
        <div>
          <p className="eyebrow">Next</p>
          <h2>What needs attention now</h2>
        </div>
        <button className="ui-button ui-button-secondary" onClick={onRefresh} type="button">
          <RefreshCw aria-hidden size={15} />
          Refresh
        </button>
      </div>

      <section className="next-action-card ui-panel">
        {loading ? (
          <div className="next-action-skeleton">
            <span />
            <strong>Loading next action</strong>
            <small>Checking packets, reviews, tasks, and system state.</small>
          </div>
        ) : error ? (
          <div className="next-action-error">
            <AlertTriangle aria-hidden size={18} />
            <div>
              <strong>Next action is unavailable</strong>
              <small>{error}</small>
            </div>
          </div>
        ) : (
          <>
            <div className="next-action-meta">
              <span className={`ui-status priority-${action?.priority || "normal"}`}>{action?.priority || "normal"}</span>
              <span>{action?.action_type || "generate_project_snapshot"}</span>
              {action?.method && action?.next_endpoint ? <span>{action.method} {action.next_endpoint}</span> : null}
            </div>
            <h3>{action?.title || "Generate a compact packet for external review"}</h3>
            <p>{action?.detail || "Start with a copy-ready packet, then bring the external AI response back into Reviews."}</p>
            {emptyState ? (
              <div className="next-empty-state">
                <AlertTriangle aria-hidden size={16} />
                <span>{emptyState}</span>
              </div>
            ) : null}
            {action?.task_template ? (
              <pre className="task-template-preview">{JSON.stringify(action.task_template, null, 2)}</pre>
            ) : null}
            <div className="next-action-buttons">
              <button className="ui-button ui-button-primary" onClick={() => onOpenWorkspace(primaryWorkspace)} type="button">
                Open {primaryWorkspace}
                <ArrowRight aria-hidden size={15} />
              </button>
              <button className="ui-button ui-button-secondary" onClick={() => onOpenWorkspace(secondaryWorkspace)} type="button">
                Open {secondaryWorkspace}
              </button>
            </div>
          </>
        )}
      </section>
    </section>
  );
}
