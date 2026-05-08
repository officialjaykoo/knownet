"use client";

import type { FormEvent } from "react";
import { Check, CirclePlus, Download, RefreshCw, Save, SquarePen, X } from "lucide-react";

type AIReviewsWorkspaceProps = {
  canWrite: boolean;
  canOperate: boolean;
  reviewMarkdown: string;
  reviewDryRun: any;
  collaborationReviews: any[];
  selectedCollaborationReview: any;
  onReviewMarkdownChange: (value: string) => void;
  onImportReview: (event: FormEvent<HTMLFormElement>) => void;
  onDryRunReview: () => void;
  onRefresh: () => void;
  onExportSarif: () => void;
  onLoadReview: (reviewId: string) => void;
  onDecideFinding: (findingId: string, decision: "accepted" | "rejected" | "deferred" | "needs_more_context") => void;
  onCreateFindingTask: (findingId: string) => void;
};

export function AIReviewsWorkspace({
  canWrite,
  canOperate,
  reviewMarkdown,
  reviewDryRun,
  collaborationReviews,
  selectedCollaborationReview,
  onReviewMarkdownChange,
  onImportReview,
  onDryRunReview,
  onRefresh,
  onExportSarif,
  onLoadReview,
  onDecideFinding,
  onCreateFindingTask,
}: AIReviewsWorkspaceProps) {
  return (
    <section className="ai-reviews-workspace" aria-label="Reviews workspace">
      <div className="workspace-dashboard-head">
        <div>
          <p className="eyebrow">Reviews</p>
          <h2>Review Inbox</h2>
        </div>
        <button onClick={onRefresh} type="button">
          <RefreshCw aria-hidden size={15} />
          Refresh
        </button>
        <button disabled={!canOperate} onClick={onExportSarif} title={canOperate ? "Export trusted findings as SARIF" : "Owner/admin login required"} type="button">
          <Download aria-hidden size={15} />
          Export SARIF
        </button>
      </div>
      <div className="ai-reviews-grid">
        <section className="review-panel collaboration-panel main-review-panel">
          <p className="eyebrow">Step 1: Parse</p>
          <form className="collab-import" onSubmit={onImportReview}>
            <textarea
              aria-label="Agent review Markdown"
              placeholder="Paste an agent_review Markdown document"
              value={reviewMarkdown}
              onChange={(event) => onReviewMarkdownChange(event.target.value)}
            />
            <button disabled={!canWrite || !reviewMarkdown.trim()} onClick={onDryRunReview} type="button">
              <RefreshCw aria-hidden size={15} />
              Dry Run
            </button>
            <button disabled={!canWrite || !reviewMarkdown.trim() || !reviewDryRun || reviewDryRun.parser_errors?.length} title={!reviewDryRun ? "Run parser dry-run first" : reviewDryRun.parser_errors?.length ? "Fix parser errors before import" : "Import review"} type="submit">
              <Save aria-hidden size={15} />
              Import review
            </button>
          </form>
          {reviewDryRun ? (
            <div className="review-dry-run-panel">
              <p className="eyebrow">Step 2: Import Preview</p>
              <strong>{reviewDryRun.finding_count || 0} finding(s)</strong>
              {reviewDryRun.parser_errors?.length ? (
                <div className="parser-error-list">
                  {reviewDryRun.parser_errors.map((error: string) => (
                    <span key={error}>{error}</span>
                  ))}
                </div>
              ) : (
                <small>No parser errors. Import is available.</small>
              )}
              {reviewDryRun.findings?.length ? (
                <div className="review-preview-findings">
                  {reviewDryRun.findings.slice(0, 3).map((finding: any) => (
                    <article key={finding.title}>
                      <span>{finding.severity} / {finding.area}</span>
                      <strong>{finding.title}</strong>
                    </article>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
          <div className="review-list-main">
            {collaborationReviews.map((item) => (
              <button className={selectedCollaborationReview?.review.id === item.id ? "review-open active" : "review-open"} key={item.id} onClick={() => onLoadReview(item.id)} type="button">
                <span>{item.source_agent}</span>
                <strong>{item.title}</strong>
                <small>{item.pending_count}/{item.finding_count} pending</small>
              </button>
            ))}
            {!collaborationReviews.length ? <p className="empty">No pending AI reviews.</p> : null}
          </div>
        </section>
        {selectedCollaborationReview ? (
          <aside className="collaboration-detail">
            <div>
              <p className="eyebrow">Selected Review</p>
              <h2>{selectedCollaborationReview.review.title}</h2>
              <small>{selectedCollaborationReview.review.source_agent} / {selectedCollaborationReview.review.status}</small>
            </div>
            <div className="finding-grid">
              {selectedCollaborationReview.findings.map((finding: any) => (
                <article className={`finding-card ${finding.status}`} key={finding.id}>
                  <div>
                    <span>{finding.severity}</span>
                    <span>{finding.area}</span>
                    <span>{finding.status}</span>
                    {finding.evidence_quality ? <span>{finding.evidence_quality}</span> : null}
                  </div>
                  <h3>{finding.title}</h3>
                  {finding.evidence ? <p>{finding.evidence}</p> : null}
                  {finding.proposed_change ? <p>{finding.proposed_change}</p> : null}
                  <footer>
                    <button onClick={() => onDecideFinding(finding.id, "rejected")} type="button">
                      <X aria-hidden size={14} />
                      Reject
                    </button>
                    <button onClick={() => onDecideFinding(finding.id, "deferred")} type="button">
                      <SquarePen aria-hidden size={14} />
                      Defer
                    </button>
                    <button className="accepted-action" onClick={() => onDecideFinding(finding.id, "accepted")} type="button">
                      <Check aria-hidden size={14} />
                      Accept
                    </button>
                    <button className="task-action" disabled={!canOperate || finding.status !== "accepted"} onClick={() => onCreateFindingTask(finding.id)} type="button">
                      <CirclePlus aria-hidden size={14} />
                      Task
                    </button>
                  </footer>
                </article>
              ))}
            </div>
          </aside>
        ) : (
          <section className="collaboration-detail">
            <p className="empty">Select an AI review to inspect findings.</p>
          </section>
        )}
      </div>
    </section>
  );
}
