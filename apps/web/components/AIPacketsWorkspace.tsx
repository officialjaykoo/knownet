"use client";

import { Clipboard, FileText, Play, Upload } from "lucide-react";

type AIPacketsWorkspaceProps = {
  canOperate: boolean;
  operatorBusyAction: string | null;
  projectSnapshotPacket: any;
  projectSnapshotTargetAgent: string;
  projectSnapshotProfile: string;
  projectSnapshotOutputMode: string;
  projectSnapshotFocus: string;
  projectSnapshotSincePacketId: string;
  projectSnapshotQualityAcknowledged: boolean;
  experimentPacket: any;
  experimentName: string;
  experimentTask: string;
  experimentScenarios: string;
  experimentResponseMarkdown: string;
  experimentResponseDryRun: any;
  experimentImportedReviewId: string | null;
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
  onGenerateExperimentPacket: () => void;
  onCopyExperimentPacket: () => void;
  onExperimentNameChange: (value: string) => void;
  onExperimentTaskChange: (value: string) => void;
  onExperimentScenariosChange: (value: string) => void;
  onExperimentResponseMarkdownChange: (value: string) => void;
  onDryRunExperimentResponse: () => void;
  onImportExperimentResponse: () => void;
};

export function AIPacketsWorkspace({
  canOperate,
  operatorBusyAction,
  projectSnapshotPacket,
  projectSnapshotTargetAgent,
  projectSnapshotProfile,
  projectSnapshotOutputMode,
  projectSnapshotFocus,
  projectSnapshotSincePacketId,
  projectSnapshotQualityAcknowledged,
  experimentPacket,
  experimentName,
  experimentTask,
  experimentScenarios,
  experimentResponseMarkdown,
  experimentResponseDryRun,
  experimentImportedReviewId,
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
  onGenerateExperimentPacket,
  onCopyExperimentPacket,
  onExperimentNameChange,
  onExperimentTaskChange,
  onExperimentScenariosChange,
  onExperimentResponseMarkdownChange,
  onDryRunExperimentResponse,
  onImportExperimentResponse,
}: AIPacketsWorkspaceProps) {
  return (
    <section className="ai-packets-workspace" aria-label="AI Packets">
      <div className="workspace-dashboard-head">
        <div>
          <p className="eyebrow">AI Packets</p>
          <h2>External AI Handoff</h2>
        </div>
        <div className="operator-actions">
          <button disabled={!canOperate || operatorBusyAction === "project-snapshot"} onClick={onGenerateProjectSnapshotPacket} type="button">
            <FileText aria-hidden size={15} />
            {operatorBusyAction === "project-snapshot" ? "Snapshotting" : "Project packet"}
          </button>
        </div>
      </div>
      {projectSnapshotPacket ? (
        <section className="experiment-packet-panel">
          <div className="operator-panel-head">
            <div>
              <h3>Project Snapshot Packet</h3>
              <small>{projectSnapshotPacket.id} / {projectSnapshotPacket.warnings.length} warning(s)</small>
            </div>
            <div className="operator-actions">
              <button onClick={onCopyProjectSnapshotPacket} type="button">
                <Clipboard aria-hidden size={15} />
                Copy
              </button>
              <button onClick={onCopyProjectSnapshotMultiAiPrompt} type="button">
                <Clipboard aria-hidden size={15} />
                Copy multi-AI prompt
              </button>
            </div>
          </div>
          <div className="experiment-packet-preview">
            <div className="model-run-stats">
              <span>{projectSnapshotPacket.profile ?? "overview"}</span>
              <span>{projectSnapshotPacket.output_mode ?? "top_findings"}</span>
              <span>{projectSnapshotPacket.contract_version ?? "p20.v1"}</span>
              {projectSnapshotPacket.snapshot_quality ? <span>quality {projectSnapshotPacket.snapshot_quality.score}</span> : null}
              <span>{projectSnapshotPacket.links.storage?.href ?? "no storage link"}</span>
              <span>{projectSnapshotPacket.links.self.href}</span>
            </div>
            {projectSnapshotPacket.snapshot_quality?.warnings?.length ? (
              <div className="model-run-stats warning-stats">
                {projectSnapshotPacket.snapshot_quality.warnings.map((warning: string) => (
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
            <h3>Snapshot Packet Builder</h3>
            <small>Choose how the standard AI packet is shaped before copying it to external models</small>
          </div>
        </div>
        <div className="experiment-packet-form">
          <label>
            <span>AI Target</span>
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
            <span>Snapshot Profile</span>
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
            <span>Response Format</span>
            <select onChange={(event) => onProjectSnapshotOutputModeChange(event.target.value)} value={projectSnapshotOutputMode}>
              <option value="top_findings">top_findings</option>
              <option value="decision_only">decision_only</option>
              <option value="implementation_candidates">implementation_candidates</option>
              <option value="provider_risk_check">provider_risk_check</option>
            </select>
          </label>
          <label>
            <span>Review Question</span>
            <textarea
              onChange={(event) => onProjectSnapshotFocusChange(event.target.value)}
              placeholder="Optional. Leave empty to use the profile default."
              rows={2}
              value={projectSnapshotFocus}
            />
          </label>
          <button onClick={onApplyProjectSnapshotStandardizationPreset} type="button">
            Standardization focus
          </button>
          <label>
            <span>Delta From Packet</span>
            <input onChange={(event) => onProjectSnapshotSincePacketIdChange(event.target.value)} placeholder="snapshot_..." value={projectSnapshotSincePacketId} />
          </label>
          <label className="inline-toggle">
            <input checked={projectSnapshotQualityAcknowledged} onChange={(event) => onProjectSnapshotQualityAcknowledgedChange(event.target.checked)} type="checkbox" />
            <span>Acknowledge quality warnings</span>
          </label>
        </div>
      </section>
      <section className="experiment-packet-panel">
        <div className="operator-panel-head">
          <div>
            <h3>External AI Packet</h3>
            <small>{experimentPacket ? `${experimentPacket.included_nodes.length} node(s) / ${experimentPacket.id}` : "Generate a copy-ready Claude/Codex packet"}</small>
          </div>
          <div className="operator-actions">
            <button disabled={!canOperate || operatorBusyAction === "experiment-packet"} onClick={onGenerateExperimentPacket} type="button">
              <FileText aria-hidden size={15} />
              {operatorBusyAction === "experiment-packet" ? "Generating" : "Generate"}
            </button>
            <button disabled={!experimentPacket} onClick={onCopyExperimentPacket} type="button">
              <Clipboard aria-hidden size={15} />
              Copy
            </button>
          </div>
        </div>
        <div className="experiment-packet-form">
          <label>
            <span>Experiment</span>
            <input onChange={(event) => onExperimentNameChange(event.target.value)} value={experimentName} />
          </label>
          <label>
            <span>Task</span>
            <textarea onChange={(event) => onExperimentTaskChange(event.target.value)} rows={2} value={experimentTask} />
          </label>
          <label>
            <span>Scenarios</span>
            <textarea onChange={(event) => onExperimentScenariosChange(event.target.value)} rows={3} value={experimentScenarios} />
          </label>
        </div>
        {experimentPacket ? (
          <div className="experiment-packet-preview">
            <div className="model-run-stats">
              <span>{experimentPacket.preflight.pages} pages</span>
              <span>{experimentPacket.preflight.ai_state_pages} ai_state</span>
              <span>{experimentPacket.preflight.unresolved_nodes} unresolved</span>
              <span>{experimentPacket.preflight.pending_findings} pending findings</span>
              <span>{experimentPacket.links.self.href}</span>
            </div>
            <textarea readOnly rows={10} value={experimentPacket.content} />
          </div>
        ) : null}
        <div className="experiment-response-panel">
          <div className="operator-panel-head">
            <h4>Response Dry Run</h4>
            <button disabled={!experimentPacket || !experimentResponseMarkdown.trim() || operatorBusyAction === "experiment-response"} onClick={onDryRunExperimentResponse} type="button">
              <Play aria-hidden size={15} />
              {operatorBusyAction === "experiment-response" ? "Parsing" : "Dry-run parse"}
            </button>
            <button disabled={!experimentResponseDryRun || Boolean(experimentImportedReviewId) || operatorBusyAction === "experiment-import"} onClick={onImportExperimentResponse} type="button">
              <Upload aria-hidden size={15} />
              {operatorBusyAction === "experiment-import" ? "Importing" : "Import to inbox"}
            </button>
          </div>
          <textarea onChange={(event) => onExperimentResponseMarkdownChange(event.target.value)} placeholder="Paste Claude or Codex response here" rows={6} value={experimentResponseMarkdown} />
          {experimentResponseDryRun ? (
            <div className="experiment-dry-run-result">
              <strong>{experimentResponseDryRun.finding_count} finding(s)</strong>
              {experimentImportedReviewId ? <small>Imported as {experimentImportedReviewId}</small> : experimentResponseDryRun.parser_errors.length ? <small>{experimentResponseDryRun.parser_errors.join(", ")}</small> : <small>No parser errors</small>}
              <div className="model-run-findings">
                {experimentResponseDryRun.findings.slice(0, 3).map((finding: any) => (
                  <article key={finding.title}>
                    <span>{finding.severity} / {finding.area}</span>
                    <strong>{finding.title}</strong>
                  </article>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </section>
    </section>
  );
}
