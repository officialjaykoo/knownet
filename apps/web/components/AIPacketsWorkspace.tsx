"use client";

import { Clipboard, FileText } from "lucide-react";

type AIPacketsWorkspaceProps = {
  canOperate: boolean;
  operatorBusyAction: string | null;
  projectSnapshotPacket: any;
  projectSnapshotCopyState: string;
  projectSnapshotTargetAgent: string;
  projectSnapshotProfile: string;
  projectSnapshotOutputMode: string;
  projectSnapshotFocus: string;
  projectSnapshotSincePacketId: string;
  projectSnapshotQualityAcknowledged: boolean;
  onGenerateProjectSnapshotPacket: () => void;
  onCopyProjectSnapshotPacket: () => void;
  onCopyProjectSnapshotMultiAiPrompt: () => void;
  onProjectSnapshotTargetAgentChange: (value: string) => void;
  onProjectSnapshotProfileChange: (value: string) => void;
  onProjectSnapshotOutputModeChange: (value: string) => void;
  onProjectSnapshotFocusChange: (value: string) => void;
  onApplyProjectSnapshotStandardizationPreset: () => void;
  onProjectSnapshotSincePacketIdChange: (value: string) => void;
  onProjectSnapshotQualityAcknowledgedChange: (value: boolean) => void;
};

export function AIPacketsWorkspace({
  canOperate,
  operatorBusyAction,
  projectSnapshotPacket,
  projectSnapshotCopyState,
  projectSnapshotTargetAgent,
  projectSnapshotProfile,
  projectSnapshotOutputMode,
  projectSnapshotFocus,
  projectSnapshotSincePacketId,
  projectSnapshotQualityAcknowledged,
  onGenerateProjectSnapshotPacket,
  onCopyProjectSnapshotPacket,
  onCopyProjectSnapshotMultiAiPrompt,
  onProjectSnapshotTargetAgentChange,
  onProjectSnapshotProfileChange,
  onProjectSnapshotOutputModeChange,
  onProjectSnapshotFocusChange,
  onApplyProjectSnapshotStandardizationPreset,
  onProjectSnapshotSincePacketIdChange,
  onProjectSnapshotQualityAcknowledgedChange,
}: AIPacketsWorkspaceProps) {
  const projectPacketDisabledReason = !canOperate
    ? "Owner/admin login required"
    : operatorBusyAction === "project-snapshot"
      ? "Project packet generation is already running"
      : "";
  const packetIntegrity = projectSnapshotPacket?.packet_integrity ?? {};
  const packetChars = packetIntegrity.content_chars ?? projectSnapshotPacket?.content?.length;
  const packetBudget = packetIntegrity.char_budget ?? projectSnapshotPacket?.limits?.char_budget ?? 12000;
  const packetTarget = packetIntegrity.optimization_target_chars ?? projectSnapshotPacket?.limits?.optimization_target_chars ?? 8000;
  const packetSizeLabel = packetChars
    ? `${packetChars.toLocaleString()} chars / ${packetBudget.toLocaleString()} budget / ${packetTarget.toLocaleString()} target`
    : "size pending";
  const packetSizeState = packetChars && packetChars > packetBudget ? "over budget" : packetChars && packetChars <= packetTarget ? "under target" : "within budget";

  return (
    <section className="ai-packets-workspace" aria-label="Packets workspace">
      <div className="workspace-dashboard-head">
        <div>
          <p className="eyebrow">Packets</p>
          <h2>Compact AI Handoff</h2>
        </div>
        <div className="operator-actions">
          <button
            disabled={Boolean(projectPacketDisabledReason)}
            onClick={onGenerateProjectSnapshotPacket}
            title={projectPacketDisabledReason || "Generate a compact Phase 26 project packet"}
            type="button"
          >
            <FileText aria-hidden size={15} />
            {operatorBusyAction === "project-snapshot" ? "Generating" : "Compact packet"}
          </button>
        </div>
      </div>
      {projectPacketDisabledReason && operatorBusyAction !== "project-snapshot" ? (
        <div className="model-run-stats warning-stats">
          <span>{projectPacketDisabledReason}</span>
        </div>
      ) : null}
      {projectSnapshotPacket ? (
        <section className="experiment-packet-panel">
          <div className="operator-panel-head">
            <div>
              <h3>Compact Project Packet</h3>
              <small>{projectSnapshotPacket.id} / {packetSizeLabel}</small>
            </div>
            <div className="operator-actions">
              <button onClick={onCopyProjectSnapshotPacket} type="button">
                <Clipboard aria-hidden size={15} />
                {projectSnapshotCopyState === "packet" ? "Copied" : "Copy packet"}
              </button>
              <button onClick={onCopyProjectSnapshotMultiAiPrompt} type="button">
                <Clipboard aria-hidden size={15} />
                {projectSnapshotCopyState === "prompt" ? "Copied" : "Copy multi-AI prompt"}
              </button>
            </div>
          </div>
          <div className="experiment-packet-preview">
            <div className="model-run-stats">
              <span>{projectSnapshotPacket.profile ?? "overview"}</span>
              <span>{projectSnapshotPacket.output_mode ?? "top_findings"}</span>
              <span>{projectSnapshotPacket.contract_version ?? "p26.v1"}</span>
              <span>{packetSizeState}</span>
              {projectSnapshotPacket.contract_ref ? <span>{projectSnapshotPacket.contract_ref}</span> : null}
              <span>{projectSnapshotPacket.links.storage?.href ?? "no storage link"}</span>
              <span>{projectSnapshotPacket.links.self.href}</span>
            </div>
            {projectSnapshotPacket.signals?.length ? (
              <div className="model-run-findings">
                {projectSnapshotPacket.signals.slice(0, 5).map((signal: any) => (
                  <article key={signal.code}>
                    <span>{signal.severity} / {signal.action ?? "observe"}</span>
                    <strong>{signal.code}</strong>
                    {signal.required_context?.ask_operator ? <small>{signal.required_context.ask_operator}</small> : null}
                  </article>
                ))}
              </div>
            ) : null}
            {projectSnapshotPacket.warnings?.length ? (
              <div className="model-run-stats warning-stats">
                {projectSnapshotPacket.warnings.map((warning: string) => (
                  <span key={warning}>{warning}</span>
                ))}
              </div>
            ) : null}
            <textarea readOnly rows={8} value={projectSnapshotPacket.content} />
          </div>
        </section>
      ) : null}
      <section className="experiment-packet-panel">
        <div className="operator-panel-head">
          <div>
            <h3>Compact Packet Builder</h3>
            <small>Generate the Phase 26 copy-ready JSON packet for external AI review</small>
          </div>
        </div>
        <div className="experiment-packet-form">
          <label>
            <span>Reviewer Target</span>
            <select onChange={(event) => onProjectSnapshotTargetAgentChange(event.target.value)} value={projectSnapshotTargetAgent}>
              <option value="all">all</option>
              <option value="deepseek">deepseek</option>
              <option value="qwen">qwen</option>
              <option value="kimi">kimi</option>
              <option value="minimax">minimax</option>
              <option value="glm">glm</option>
              <option value="claude">claude</option>
              <option value="codex">codex</option>
            </select>
          </label>
          <label>
            <span>Packet Profile</span>
            <select onChange={(event) => onProjectSnapshotProfileChange(event.target.value)} value={projectSnapshotProfile}>
              <option value="overview">overview</option>
              <option value="stability">stability</option>
              <option value="performance">performance</option>
              <option value="security">security</option>
              <option value="implementation">implementation</option>
              <option value="provider_review">provider_review</option>
            </select>
          </label>
          <label>
            <span>Output Contract</span>
            <select onChange={(event) => onProjectSnapshotOutputModeChange(event.target.value)} value={projectSnapshotOutputMode}>
              <option value="top_findings">top_findings</option>
              <option value="decision_only">decision_only</option>
              <option value="implementation_candidates">implementation_candidates</option>
              <option value="provider_risk_check">provider_risk_check</option>
            </select>
          </label>
          <label>
            <span>Question</span>
            <textarea
              onChange={(event) => onProjectSnapshotFocusChange(event.target.value)}
              placeholder="Optional. Leave empty to use the profile default."
              rows={2}
              value={projectSnapshotFocus}
            />
          </label>
          <button onClick={onApplyProjectSnapshotStandardizationPreset} type="button">
            Phase 26 review focus
          </button>
          <label>
            <span>Previous Packet ID</span>
            <input onChange={(event) => onProjectSnapshotSincePacketIdChange(event.target.value)} placeholder="snapshot_..." value={projectSnapshotSincePacketId} />
          </label>
          {projectSnapshotQualityAcknowledged ? (
            <label className="inline-toggle">
              <input checked={projectSnapshotQualityAcknowledged} onChange={(event) => onProjectSnapshotQualityAcknowledgedChange(event.target.checked)} type="checkbox" />
              <span>Quality warnings acknowledged</span>
            </label>
          ) : null}
        </div>
      </section>
    </section>
  );
}
