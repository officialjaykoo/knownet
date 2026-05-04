"use client";

import { AgentAccessPanel } from "./AgentAccessPanel";

type AgentDashboardWorkspaceProps = {
  sessionToken: string | null;
  vaultId: string;
};

export function AgentDashboardWorkspace({ sessionToken, vaultId }: AgentDashboardWorkspaceProps) {
  return (
    <aside className="workspace-dashboard">
      <div className="workspace-dashboard-head">
        <div>
          <p className="eyebrow">Agent Dashboard</p>
          <h2>External Agent Access</h2>
        </div>
      </div>
      <AgentAccessPanel sessionToken={sessionToken} vaultId={vaultId} />
    </aside>
  );
}
