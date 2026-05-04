import { Archive, LockKeyhole, Network, ShieldCheck } from "lucide-react";

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

type MaintenanceLock = {
  id: string;
  operation: string;
  status: string;
  created_at: string;
};

type RestorePlan = {
  snapshot: string;
  can_restore_now: boolean;
  pre_restore_snapshot_required: boolean;
  manifest: {
    created_at?: string | null;
    included_files?: number | null;
    hash_count?: number | null;
  };
  active_lock?: MaintenanceLock | null;
  warnings: string[];
};

type OperationsPanelProps = {
  healthSummary: HealthSummary | null;
  snapshots: SnapshotSummary[];
  locks: MaintenanceLock[];
  restorePlan: RestorePlan | null;
  restoreConfirmValue: string;
  verifyIssues: number;
  canOperate: boolean;
  busyAction: string | null;
  onCreateSnapshot: () => void;
  onRunVerifyIndex: () => void;
  onRebuildGraph: () => void;
  onInspectRestorePlan: () => void;
  onRestoreConfirmChange: (value: string) => void;
  onRestoreSnapshot: () => void;
};

export function OperationsPanel({
  healthSummary,
  snapshots,
  locks,
  restorePlan,
  restoreConfirmValue,
  verifyIssues,
  canOperate,
  busyAction,
  onCreateSnapshot,
  onRunVerifyIndex,
  onRebuildGraph,
  onInspectRestorePlan,
  onRestoreConfirmChange,
  onRestoreSnapshot,
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
        <button disabled={!canOperate || Boolean(busyAction) || !snapshots[0]} onClick={onInspectRestorePlan} type="button">
          <LockKeyhole aria-hidden size={15} />
          {busyAction === "restore-plan" ? "Working" : "Restore plan"}
        </button>
      </div>
      <small>
        {snapshots[0] ? `Latest: ${snapshots[0].name}` : "No snapshots"} / {verifyIssues} verify issues
        {locks.length ? ` / ${locks.length} active lock(s)` : " / no active locks"}
        {canOperate ? "" : " / owner or admin required"}
      </small>
      {restorePlan ? (
        <div className={`ops-restore-plan ${restorePlan.can_restore_now ? "ready" : "blocked"}`}>
          <strong>{restorePlan.snapshot}</strong>
          <small>
            {restorePlan.can_restore_now ? "restore available after confirmation" : "restore blocked by active lock"} / {restorePlan.manifest.included_files || 0} file(s)
            {restorePlan.pre_restore_snapshot_required ? " / pre-restore snapshot required" : ""}
          </small>
          {restorePlan.can_restore_now ? (
            <div className="ops-restore-confirm">
              <input
                aria-label="Restore confirmation snapshot name"
                placeholder={restorePlan.snapshot}
                value={restoreConfirmValue}
                onChange={(event) => onRestoreConfirmChange(event.target.value)}
              />
              <button
                disabled={!canOperate || Boolean(busyAction) || restoreConfirmValue !== restorePlan.snapshot}
                onClick={onRestoreSnapshot}
                type="button"
              >
                <LockKeyhole aria-hidden size={15} />
                {busyAction === "restore" ? "Restoring" : "Restore"}
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
