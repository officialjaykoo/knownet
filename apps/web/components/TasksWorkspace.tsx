"use client";

import { Check, CirclePlus, RefreshCw, Save } from "lucide-react";

type TasksWorkspaceProps = {
  canOperate: boolean;
  tasks: any[];
  acceptedFindings: any[];
  selectedTask: any | null;
  evidenceCommit: string;
  evidenceChangedFiles: string;
  evidenceVerification: string;
  evidenceNotes: string;
  busyAction: string | null;
  onRefresh: () => void;
  onSelectTask: (task: any) => void;
  onCreateTask: (findingId: string) => void;
  onEvidenceCommitChange: (value: string) => void;
  onEvidenceChangedFilesChange: (value: string) => void;
  onEvidenceVerificationChange: (value: string) => void;
  onEvidenceNotesChange: (value: string) => void;
  onSubmitEvidence: () => void;
};

const taskStatuses = ["open", "in_progress", "blocked", "done"];

export function TasksWorkspace({
  canOperate,
  tasks,
  acceptedFindings,
  selectedTask,
  evidenceCommit,
  evidenceChangedFiles,
  evidenceVerification,
  evidenceNotes,
  busyAction,
  onRefresh,
  onSelectTask,
  onCreateTask,
  onEvidenceCommitChange,
  onEvidenceChangedFilesChange,
  onEvidenceVerificationChange,
  onEvidenceNotesChange,
  onSubmitEvidence,
}: TasksWorkspaceProps) {
  const groupedTasks = taskStatuses.map((status) => ({
    status,
    tasks: tasks.filter((task) => task.status === status),
  }));
  const evidenceDisabled = !canOperate || !selectedTask || !evidenceVerification.trim() || busyAction === "task-evidence";

  return (
    <section className="tasks-workspace" aria-label="Tasks workspace">
      <div className="workspace-dashboard-head">
        <div>
          <p className="eyebrow">Tasks</p>
          <h2>Implementation Work Queue</h2>
        </div>
        <button onClick={onRefresh} type="button">
          <RefreshCw aria-hidden size={15} />
          Refresh
        </button>
      </div>

      {acceptedFindings.length ? (
        <section className="task-attention-panel ui-panel">
          <div>
            <p className="eyebrow">Accepted Without Task</p>
            <h3>{acceptedFindings.length} finding(s) need task creation</h3>
          </div>
          <div className="accepted-finding-list">
            {acceptedFindings.slice(0, 6).map((finding) => (
              <article key={finding.id}>
                <div>
                  <span>{finding.severity} / {finding.area}</span>
                  <strong>{finding.title}</strong>
                  <small>{finding.evidence_quality || "unspecified"}</small>
                </div>
                <button disabled={!canOperate || Boolean(finding.has_task)} onClick={() => onCreateTask(finding.id)} type="button">
                  <CirclePlus aria-hidden size={14} />
                  {finding.has_task ? "Task exists" : "Create task"}
                </button>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      <div className="tasks-grid">
        <section className="task-list-panel ui-panel">
          <p className="eyebrow">Task Status</p>
          {groupedTasks.map((group) => (
            <div className="task-status-group" key={group.status}>
              <h3>{group.status.replace("_", " ")}</h3>
              {group.tasks.length ? (
                group.tasks.map((task) => (
                  <button className={selectedTask?.id === task.id ? "active" : ""} key={task.id} onClick={() => onSelectTask(task)} type="button">
                    <span>{task.priority || "normal"} / {task.owner || "unassigned"}</span>
                    <strong>{task.title || task.id}</strong>
                    <small>{task.finding_id}</small>
                  </button>
                ))
              ) : (
                <p className="empty">No {group.status.replace("_", " ")} task.</p>
              )}
            </div>
          ))}
        </section>

        <section className="task-detail-panel ui-panel">
          {selectedTask ? (
            <>
              <div>
                <p className="eyebrow">Selected Task</p>
                <h3>{selectedTask.title || selectedTask.id}</h3>
                <small>{selectedTask.status} / {selectedTask.priority || "normal"} / {selectedTask.owner || "unassigned"}</small>
              </div>
              {selectedTask.task_prompt ? <p>{selectedTask.task_prompt}</p> : null}
              {selectedTask.expected_verification ? <p>{selectedTask.expected_verification}</p> : null}
              {selectedTask.status === "blocked" && selectedTask.blocking_reason ? <p className="operator-error">{selectedTask.blocking_reason}</p> : null}
              <div className="task-evidence-form">
                <label>
                  <span>Commit</span>
                  <input onChange={(event) => onEvidenceCommitChange(event.target.value)} placeholder="optional commit hash" value={evidenceCommit} />
                </label>
                <label>
                  <span>Changed files</span>
                  <input onChange={(event) => onEvidenceChangedFilesChange(event.target.value)} placeholder="apps/api/file.py, apps/web/file.tsx" value={evidenceChangedFiles} />
                </label>
                <label>
                  <span>Verification note</span>
                  <textarea onChange={(event) => onEvidenceVerificationChange(event.target.value)} rows={3} value={evidenceVerification} />
                </label>
                <label>
                  <span>Memo</span>
                  <textarea onChange={(event) => onEvidenceNotesChange(event.target.value)} rows={2} value={evidenceNotes} />
                </label>
                <button disabled={evidenceDisabled} onClick={onSubmitEvidence} title={evidenceDisabled ? "Select a task and add a verification note" : "Submit implementation evidence"} type="button">
                  {busyAction === "task-evidence" ? <RefreshCw aria-hidden size={15} /> : <Save aria-hidden size={15} />}
                  {busyAction === "task-evidence" ? "Submitting" : "Submit evidence"}
                </button>
              </div>
            </>
          ) : (
            <div className="task-empty-detail">
              <Check aria-hidden size={22} />
              <strong>Select a task</strong>
              <small>Implementation evidence closes the loop from finding to task to verification.</small>
            </div>
          )}
        </section>
      </div>
    </section>
  );
}
