"use client";

import { Activity, Bot, FileText, KeyRound, Link2 } from "lucide-react";

type Workspace = "operator" | "map" | "reviews" | "packets" | "agents";

type WorkspaceTabsProps = {
  activeWorkspace: Workspace;
  canManageAgents: boolean;
  onChange: (workspace: Workspace) => void;
};

export function WorkspaceTabs({ activeWorkspace, canManageAgents, onChange }: WorkspaceTabsProps) {
  return (
    <nav className="workspace-tabs" aria-label="Main workspace sections">
      <button className={activeWorkspace === "operator" ? "active" : ""} onClick={() => onChange("operator")} type="button">
        <Activity aria-hidden size={15} />
        Operator Console
      </button>
      <button className={activeWorkspace === "map" ? "active" : ""} onClick={() => onChange("map")} type="button">
        <Link2 aria-hidden size={15} />
        Knowledge Map
      </button>
      <button className={activeWorkspace === "reviews" ? "active" : ""} onClick={() => onChange("reviews")} type="button">
        <Bot aria-hidden size={15} />
        AI Reviews
      </button>
      <button className={activeWorkspace === "packets" ? "active" : ""} onClick={() => onChange("packets")} type="button">
        <FileText aria-hidden size={15} />
        AI Packets
      </button>
      {canManageAgents ? (
        <button className={activeWorkspace === "agents" ? "active" : ""} onClick={() => onChange("agents")} type="button">
          <KeyRound aria-hidden size={15} />
          Agent Dashboard
        </button>
      ) : null}
    </nav>
  );
}
