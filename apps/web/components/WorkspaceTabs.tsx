"use client";

import { Activity, Bot, Check, FileText, Link2, Settings } from "lucide-react";

export type Workspace = "next" | "packets" | "reviews" | "tasks" | "sources" | "ops";

type WorkspaceTabsProps = {
  activeWorkspace: Workspace;
  onChange: (workspace: Workspace) => void;
};

const workspaceItems: Array<{ key: Workspace; label: string; icon: typeof Activity }> = [
  { key: "next", label: "Next", icon: Activity },
  { key: "packets", label: "Packets", icon: FileText },
  { key: "reviews", label: "Reviews", icon: Bot },
  { key: "tasks", label: "Tasks", icon: Check },
  { key: "sources", label: "Sources", icon: Link2 },
  { key: "ops", label: "Ops", icon: Settings },
];

export function WorkspaceTabs({ activeWorkspace, onChange }: WorkspaceTabsProps) {
  return (
    <nav className="workspace-tabs" aria-label="Main workspace sections">
      {workspaceItems.map((item) => {
        const Icon = item.icon;
        return (
          <button
            aria-current={activeWorkspace === item.key ? "page" : undefined}
            className={activeWorkspace === item.key ? "active" : ""}
            data-label={item.label}
            key={item.key}
            onClick={() => onChange(item.key)}
            type="button"
          >
            <Icon aria-hidden size={15} />
            {item.label}
          </button>
        );
      })}
    </nav>
  );
}
