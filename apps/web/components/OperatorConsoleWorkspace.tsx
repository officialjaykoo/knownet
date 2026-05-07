"use client";

import { Activity, AlertTriangle, Bot, Check, Play, RefreshCw, Upload, ShieldCheck } from "lucide-react";
import { OperationsPanel } from "./OperationsPanel";

type OperatorConsoleWorkspaceProps = {
  healthSummary: any;
  aiStateQuality: any;
  releaseReadiness: any;
  providerMatrix: any;
  modelRuns: any[];
  selectedModelRun: any;
  canOperate: boolean;
  canManageAgents: boolean;
  operatorBusyAction: string | null;
  opsBusyAction: string | null;
  snapshots: any[];
  maintenanceLocks: any[];
  restorePlan: any;
  restoreConfirmValue: string;
  verifyIssues: number;
  onRefresh: () => void;
  onStartGeminiMockRun: () => void;
  onSelectModelRun: (run: any) => void;
  onOpenCollaborationReview: (reviewId: string) => void;
  onImportSelectedModelRun: () => void;
  onCreateSnapshot: () => void;
  onRunVerifyIndex: () => void;
  onRebuildGraph: () => void;
  onInspectRestorePlan: () => void;
  onRestoreConfirmChange: (value: string) => void;
  onRestoreSnapshot: () => void;
};

export function OperatorConsoleWorkspace({
  healthSummary,
  aiStateQuality,
  releaseReadiness,
  providerMatrix,
  modelRuns,
  selectedModelRun,
  canOperate,
  canManageAgents,
  operatorBusyAction,
  opsBusyAction,
  snapshots,
  maintenanceLocks,
  restorePlan,
  restoreConfirmValue,
  verifyIssues,
  onRefresh,
  onStartGeminiMockRun,
  onSelectModelRun,
  onOpenCollaborationReview,
  onImportSelectedModelRun,
  onCreateSnapshot,
  onRunVerifyIndex,
  onRebuildGraph,
  onInspectRestorePlan,
  onRestoreConfirmChange,
  onRestoreSnapshot,
}: OperatorConsoleWorkspaceProps) {
  return (
    <section className="operator-console" aria-label="Operator Console">
      <div className="operator-head">
        <div>
          <p className="eyebrow">Operator Console</p>
          <h2>Phase 17 Readiness</h2>
        </div>
        <div className="operator-actions">
          <button onClick={onRefresh} type="button">
            <RefreshCw aria-hidden size={15} />
            Refresh
          </button>
          <button disabled={!canOperate || operatorBusyAction === "mock-run"} onClick={onStartGeminiMockRun} type="button">
            <Play aria-hidden size={15} />
            {operatorBusyAction === "mock-run" ? "Running" : "Gemini mock"}
          </button>
        </div>
      </div>
      <div className="operator-grid">
        <article className={`operator-tile ${healthSummary?.overall_status || "unknown"}`}>
          <span><Activity aria-hidden size={16} /> Health</span>
          <strong>{healthSummary?.overall_status || "unknown"}</strong>
          <small>{healthSummary?.issues.length ? `${healthSummary.issues.length} issue(s)` : "No blocking health issue loaded"}</small>
        </article>
        <article className={`operator-tile ${aiStateQuality?.overall_status || "unknown"}`}>
          <span><ShieldCheck aria-hidden size={16} /> AI State</span>
          <strong>{aiStateQuality?.overall_status || "unknown"}</strong>
          <small>{aiStateQuality?.summary ? `${aiStateQuality.summary.structured_state_pages || 0}/${aiStateQuality.summary.pages || 0} structured state pages` : "Quality not loaded"}</small>
        </article>
        <article className={`operator-tile ${releaseReadiness?.release_ready ? "pass" : "warn"}`}>
          <span><Check aria-hidden size={16} /> Release</span>
          <strong>{releaseReadiness?.release_ready ? "ready" : "blocked/warn"}</strong>
          <small>{releaseReadiness ? `${releaseReadiness.blockers.length} blocker(s), ${releaseReadiness.warnings.length} warning(s)` : "Readiness not loaded"}</small>
        </article>
        <article className="operator-tile">
          <span><Bot aria-hidden size={16} /> Providers</span>
          <strong>{providerMatrix?.summary.live_verified || 0} live</strong>
          <small>{providerMatrix ? `${providerMatrix.summary.configured || 0} configured / ${providerMatrix.summary.mocked || 0} mocked` : "Matrix not loaded"}</small>
        </article>
      </div>
      <div className="operator-split">
        <section className="operator-panel">
          <div className="operator-panel-head">
            <h3>Quality Checks</h3>
            <small>{aiStateQuality?.checked_at || "not checked"}</small>
          </div>
          <div className="quality-list">
            {(aiStateQuality?.checks || []).slice(0, 8).map((check: any) => (
              <div className={`quality-row ${check.status}`} key={check.code}>
                <span>{check.status === "fail" ? <AlertTriangle aria-hidden size={14} /> : <Check aria-hidden size={14} />}</span>
                <div>
                  <strong>{check.title}</strong>
                  <small>{check.detail}</small>
                </div>
              </div>
            ))}
            {!aiStateQuality ? <p className="empty">AI state quality has not loaded.</p> : null}
          </div>
        </section>
        <section className="operator-panel">
          <div className="operator-panel-head">
            <h3>Model Runs</h3>
            <small>{modelRuns.length} recent</small>
          </div>
          <div className="model-run-list">
            {modelRuns.slice(0, 8).map((run) => (
              <button className={selectedModelRun?.id === run.id ? "active" : ""} key={run.id} onClick={() => onSelectModelRun(run)} type="button">
                <span>{run.provider} / {run.status}</span>
                <strong>{run.id}</strong>
                <small>{run.request?.mock === false ? "live/configured" : "mock"} / {run.input_tokens || run.context_summary?.estimated_input_tokens || "?"} in tokens</small>
              </button>
            ))}
            {!modelRuns.length ? <p className="empty">No model runs yet.</p> : null}
          </div>
        </section>
      </div>
      {selectedModelRun ? (
        <section className="model-run-detail">
          <div>
            <p className="eyebrow">Model Run</p>
            <h3>{selectedModelRun.provider} / {selectedModelRun.status}</h3>
            <small>{selectedModelRun.model} / {selectedModelRun.prompt_profile}</small>
          </div>
          <div className="model-run-stats">
            <span>{selectedModelRun.context_summary?.page_count || 0} pages</span>
            <span>{selectedModelRun.context_summary?.open_finding_count || 0} open findings</span>
            <span>{selectedModelRun.input_tokens || selectedModelRun.context_summary?.estimated_input_tokens || "?"} input tokens</span>
            <span>{selectedModelRun.output_tokens || "?"} output tokens</span>
            <span>{selectedModelRun.estimated_cost_usd == null ? "cost unavailable" : `$${selectedModelRun.estimated_cost_usd.toFixed(4)}`}</span>
          </div>
          {selectedModelRun.error_message ? <p className="operator-error">{selectedModelRun.error_message}</p> : null}
          {selectedModelRun.response?.dry_run?.findings?.length ? (
            <div className="model-run-findings">
              {selectedModelRun.response.dry_run.findings.slice(0, 3).map((finding: any, index: number) => (
                <article key={`${selectedModelRun.id}-${index}`}>
                  <span>{finding.severity} / {finding.area}</span>
                  <strong>{finding.title}</strong>
                </article>
              ))}
            </div>
          ) : null}
          <footer>
            {selectedModelRun.review_id ? <button onClick={() => onOpenCollaborationReview(selectedModelRun.review_id)} type="button">Open review</button> : null}
            <button disabled={!canOperate || selectedModelRun.status !== "dry_run_ready" || operatorBusyAction === "import-run"} onClick={onImportSelectedModelRun} type="button">
              <Upload aria-hidden size={15} />
              {operatorBusyAction === "import-run" ? "Importing" : "Import findings"}
            </button>
          </footer>
        </section>
      ) : null}
      <section className="provider-matrix">
        {(providerMatrix?.providers || []).slice(0, 8).map((provider: any) => (
          <article className={`provider-row ${provider.verification_level}`} key={provider.provider_id}>
            <strong>{provider.label}</strong>
            <span>{provider.verification_level}</span>
            <small>{provider.route_type} / {provider.model || provider.implemented_surface}</small>
          </article>
        ))}
      </section>
      {canManageAgents ? (
        <OperationsPanel
          healthSummary={healthSummary}
          snapshots={snapshots}
          locks={maintenanceLocks}
          restorePlan={restorePlan}
          restoreConfirmValue={restoreConfirmValue}
          verifyIssues={verifyIssues}
          canOperate={canOperate}
          busyAction={opsBusyAction}
          onCreateSnapshot={onCreateSnapshot}
          onRunVerifyIndex={onRunVerifyIndex}
          onRebuildGraph={onRebuildGraph}
          onInspectRestorePlan={onInspectRestorePlan}
          onRestoreConfirmChange={onRestoreConfirmChange}
          onRestoreSnapshot={onRestoreSnapshot}
        />
      ) : null}
    </section>
  );
}
