import { Archive, Network, ShieldCheck } from "lucide-react";

type HealthSummary = {
  overall_status: string;
  issues: string[];
  issue_details?: Array<{
    code: string;
    severity: string;
    description: string;
    action: string;
  }>;
  checked_at: string;
};

type SnapshotSummary = {
  name: string;
  path: string;
  size_bytes: number;
};

type OperationsPanelProps = {
  healthSummary: HealthSummary | null;
  snapshots: SnapshotSummary[];
  verifyIssues: number;
  canOperate: boolean;
  busyAction: string | null;
  onCreateSnapshot: () => void;
  onRunVerifyIndex: () => void;
  onRebuildGraph: () => void;
};

export function OperationsPanel({
  healthSummary,
  snapshots,
  verifyIssues,
  canOperate,
  busyAction,
  onCreateSnapshot,
  onRunVerifyIndex,
  onRebuildGraph,
}: OperationsPanelProps) {
  const status = healthSummary?.overall_status || "unknown";
  const description = healthSummary?.issue_details?.[0]?.description || healthSummary?.issues.slice(0, 3).join(", ") || "No issues loaded";

  return (
    <section className="ops-panel">
      <p className="eyebrow">Operations</p>
      <div className={`ops-status ${status}`}>
        <strong>{status}</strong>
        <small>{description}</small>
      </div>
      <div className="ops-grid">
        <button disabled={!canOperate || Boolean(busyAction)} onClick={onCreateSnapshot} type="button">
          <Archive aria-hidden size={15} />
          {busyAction === "snapshot" ? "Working" : "Snapshot"}
        </button>
        <button disabled={!canOperate || Boolean(busyAction)} onClick={onRunVerifyIndex} type="button">
          <ShieldCheck aria-hidden size={15} />
          {busyAction === "verify" ? "Working" : "Verify"}
        </button>
        <button disabled={!canOperate || Boolean(busyAction)} onClick={onRebuildGraph} type="button">
          <Network aria-hidden size={15} />
          {busyAction === "graph" ? "Working" : "Graph"}
        </button>
      </div>
      <small>
        {snapshots[0] ? `Latest: ${snapshots[0].name}` : "No snapshots"} / {verifyIssues} verify issues
        {canOperate ? "" : " / owner or admin required"}
      </small>
    </section>
  );
}
