"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  Check,
  ChevronsDown,
  ChevronsUp,
  CirclePlus,
  FileText,
  KeyRound,
  Link2,
  LogIn,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
  Save,
  ShieldCheck,
  SquarePen,
  X,
} from "lucide-react";
import { GraphPanel, GraphData, GraphNode } from "../components/GraphPanel";
import { AgentDashboardWorkspace } from "../components/AgentDashboardWorkspace";
import { AIReviewsWorkspace } from "../components/AIReviewsWorkspace";
import { AIPacketsWorkspace } from "../components/AIPacketsWorkspace";
import { MarkdownView } from "../components/MarkdownView";
import { OperatorConsoleWorkspace } from "../components/OperatorConsoleWorkspace";
import { WorkspaceTabs } from "../components/WorkspaceTabs";

type PageSummary = {
  slug: string;
  title: string;
  path: string;
  updated_at?: string | null;
  links_count: number;
  citations_count: number;
  system_kind?: string | null;
  system_tier?: number | null;
  system_locked?: boolean;
};

type Page = {
  slug: string;
  title: string;
  markdown: string;
  links: Array<{ target: string; display?: string | null; status: string }>;
  citations: Array<{ key: string; display_title?: string | null }>;
  citation_sources?: CitationSource[];
  sections: Array<{ heading: string; level: number; section_key: string }>;
};

type CitationSource = {
  key: string;
  display_title?: string | null;
  definition?: string | null;
  excerpt?: string | null;
  status?: string | null;
  reason?: string | null;
};

type LinkSummary = {
  links: Array<{ target: string; display?: string | null; status: string }>;
  unresolved: Array<{ target: string; display?: string | null; status: string }>;
};

type BacklinkSummary = {
  backlinks: Array<{ source_slug: string; source_title: string; raw: string }>;
};

type Suggestion = {
  id: string;
  job_id: string;
  title: string;
  status: string;
  markdown: string;
};

type SuggestionDiff = {
  suggestion_id: string;
  slug: string;
  status: string;
  mode: string;
  changes: Array<{ type: "added" | "removed"; text: string }>;
};

type ActorState = {
  actor_type: string;
  actor_id: string;
  session_id: string | null;
  role: string;
  vault_id: string;
};

type Submission = {
  id: string;
  message_id: string;
  actor_type: string;
  status: string;
  created_at: string;
  message_path: string;
};

type Vault = {
  id: string;
  name: string;
  role: string;
};

type CitationAudit = {
  id: string;
  page_id: string;
  citation_key: string;
  display_title?: string | null;
  claim_text: string;
  status: string;
  reason: string | null;
  verifier_type: string;
};

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

type CollaborationReviewSummary = {
  id: string;
  title: string;
  source_agent: string;
  status: string;
  finding_count: number;
  pending_count: number;
};

type CollaborationFinding = {
  id: string;
  severity: string;
  area: string;
  title: string;
  evidence?: string | null;
  proposed_change?: string | null;
  evidence_quality?: string | null;
  status: string;
};

type FindingTask = {
  id: string;
  finding_id: string;
  status: string;
  priority: string;
  owner?: string | null;
  task_prompt: string;
  expected_verification?: string | null;
};

type CollaborationReviewDetail = {
  review: CollaborationReviewSummary & { meta?: string };
  findings: CollaborationFinding[];
};

type QualityCheck = {
  code: string;
  status: "pass" | "warn" | "fail";
  title: string;
  detail: string;
  action?: string | null;
};

type AiStateQuality = {
  overall_status: "pass" | "warn" | "fail";
  checks: QualityCheck[];
  summary?: Record<string, number>;
  checked_at: string;
};

type ProviderMatrix = {
  providers: Array<{
    provider_id: string;
    label: string;
    route_type: string;
    implemented_surface: string;
    verification_level: string;
    last_verified_at?: string | null;
    required_config_present: boolean;
    model?: string | null;
    known_limitations: string[];
    run_counts: { mock_successful: number; live_successful: number; failed: number };
  }>;
  summary: Record<string, number>;
  checked_at: string;
};

type ModelRun = {
  id: string;
  provider: string;
  model: string;
  prompt_profile: string;
  status: string;
  review_id?: string | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  estimated_cost_usd?: number | null;
  error_code?: string | null;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
  context_summary?: {
    page_count?: number;
    open_finding_count?: number;
    estimated_input_tokens?: number;
    chars?: number;
    context_hash?: string;
  };
  request?: { mock?: boolean; review_focus?: string | null };
  response?: {
    mock?: boolean;
    dry_run?: { finding_count?: number; findings?: CollaborationFinding[]; parser_errors?: string[] };
    import?: { review_id?: string; finding_count?: number };
  };
};

type ReleaseReadiness = {
  release_ready: boolean;
  blockers: string[];
  warnings: string[];
  ai_state_quality: { overall_status: string; summary?: Record<string, number> };
  provider_matrix: Record<string, number>;
  latest_model_run?: { id: string; provider: string; status: string; updated_at: string } | null;
  checked_at: string;
};

type ExperimentPacket = {
  id: string;
  type: string;
  content: string;
  content_hash: string;
  links: { self: { href: string }; content?: { href: string }; storage?: { href: string } };
  included_nodes: Array<{ page_id: string; slug: string; title: string }>;
  preflight: { pages: number; ai_state_pages: number; unresolved_nodes: number; pending_findings: number };
  copy_ready: boolean;
};

type ProjectSnapshotPacket = {
  id: string;
  type: string;
  content: string;
  content_hash: string;
  links: { self: { href: string }; content?: { href: string }; storage?: { href: string } };
  warnings: string[];
  profile?: string;
  output_mode?: string;
  contract_version?: string;
  snapshot_quality?: { score: number; warnings: string[]; advisory_only: boolean; acknowledgement_required_for_ui_send: boolean; acknowledged: boolean };
  copy_ready: boolean;
};

type ExperimentResponseDryRun = {
  response_id: string;
  packet: { id: string; type: string };
  finding_count: number;
  findings: CollaborationFinding[];
  parser_errors: string[];
  truncated_findings: boolean;
};

const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "";
const sessionStorageKey = "knownet.session";
const vaultStorageKey = "knownet.vault";

function pageIdFromSlug(slug: string): string {
  return `page_${slug.replace(/-/g, "_")}`;
}

async function fetchJson<T>(path: string, init?: RequestInit, token?: string | null, vaultId?: string | null): Promise<T> {
  const headers = new Headers(init?.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (vaultId) {
    headers.set("x-knownet-vault", vaultId);
  }
  const response = await fetch(`${apiBase}${path}`, { ...init, headers });
  const body = await response.json();
  if (!response.ok || !body.ok) {
    const validationMessage = Array.isArray(body.detail) ? body.detail.map((item: { msg?: string }) => item.msg).filter(Boolean).join("; ") : "";
    throw new Error(body.detail?.message ?? validationMessage ?? body.error?.message ?? "Request failed");
  }
  return body.data as T;
}

export default function HomePage() {
  const [pages, setPages] = useState<PageSummary[]>([]);
  const [pageSort, setPageSort] = useState<"recent" | "links" | "class">("recent");
  const [pageSortDir, setPageSortDir] = useState<"asc" | "desc">("desc");
  const [selectedSlug, setSelectedSlug] = useState("");
  const [page, setPage] = useState<Page | null>(null);
  const [linkSummary, setLinkSummary] = useState<LinkSummary | null>(null);
  const [backlinkSummary, setBacklinkSummary] = useState<BacklinkSummary | null>(null);
  const [message, setMessage] = useState("");
  const [status, setStatus] = useState("Waiting for API");
  const [submitting, setSubmitting] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [suggestion, setSuggestion] = useState<Suggestion | null>(null);
  const [suggestionDiff, setSuggestionDiff] = useState<SuggestionDiff | null>(null);
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [actor, setActor] = useState<ActorState | null>(null);
  const [authMode, setAuthMode] = useState<"login" | "bootstrap">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [vaults, setVaults] = useState<Vault[]>([]);
  const [vaultId, setVaultId] = useState("local-default");
  const [newVaultName, setNewVaultName] = useState("");
  const [citationAudits, setCitationAudits] = useState<CitationAudit[]>([]);
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [graphMode, setGraphMode] = useState<"map" | "list">("map");
  const [graphNodeType, setGraphNodeType] = useState("page");
  const [graphStatus, setGraphStatus] = useState("");
  const [selectedGraphNode, setSelectedGraphNode] = useState<GraphNode | null>(null);
  const [graphError, setGraphError] = useState<string | null>(null);
  const [healthSummary, setHealthSummary] = useState<HealthSummary | null>(null);
  const [snapshots, setSnapshots] = useState<SnapshotSummary[]>([]);
  const [maintenanceLocks, setMaintenanceLocks] = useState<MaintenanceLock[]>([]);
  const [restorePlan, setRestorePlan] = useState<RestorePlan | null>(null);
  const [restoreConfirmValue, setRestoreConfirmValue] = useState("");
  const [verifyIssues, setVerifyIssues] = useState(0);
  const [opsBusyAction, setOpsBusyAction] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [activeWorkspace, setActiveWorkspace] = useState<"operator" | "map" | "reviews" | "packets" | "agents">("operator");
  const [reviewMarkdown, setReviewMarkdown] = useState("");
  const [collaborationReviews, setCollaborationReviews] = useState<CollaborationReviewSummary[]>([]);
  const [selectedCollaborationReview, setSelectedCollaborationReview] = useState<CollaborationReviewDetail | null>(null);
  const [bundleStatus, setBundleStatus] = useState("");
  const [bundlePageIds, setBundlePageIds] = useState<string[]>([]);
  const [aiStateQuality, setAiStateQuality] = useState<AiStateQuality | null>(null);
  const [providerMatrix, setProviderMatrix] = useState<ProviderMatrix | null>(null);
  const [modelRuns, setModelRuns] = useState<ModelRun[]>([]);
  const [selectedModelRun, setSelectedModelRun] = useState<ModelRun | null>(null);
  const [releaseReadiness, setReleaseReadiness] = useState<ReleaseReadiness | null>(null);
  const [operatorBusyAction, setOperatorBusyAction] = useState<string | null>(null);
  const [projectSnapshotPacket, setProjectSnapshotPacket] = useState<ProjectSnapshotPacket | null>(null);
  const [projectSnapshotTargetAgent, setProjectSnapshotTargetAgent] = useState("all");
  const [projectSnapshotProfile, setProjectSnapshotProfile] = useState("overview");
  const [projectSnapshotOutputMode, setProjectSnapshotOutputMode] = useState("top_findings");
  const [projectSnapshotFocus, setProjectSnapshotFocus] = useState("");
  const [projectSnapshotSincePacketId, setProjectSnapshotSincePacketId] = useState("");
  const [projectSnapshotQualityAcknowledged, setProjectSnapshotQualityAcknowledged] = useState(false);
  const [experimentPacket, setExperimentPacket] = useState<ExperimentPacket | null>(null);
  const [experimentName, setExperimentName] = useState("Boundary Interpretation Divergence Test");
  const [experimentTask, setExperimentTask] = useState("Decide scenarios only. Return parser-ready findings only for items that should be imported.");
  const [experimentScenarios, setExperimentScenarios] = useState("Can a context_limited finding be a release blocker?\nCan a model infer whole-system health from /api/agent/ping?");
  const [experimentResponseMarkdown, setExperimentResponseMarkdown] = useState("");
  const [experimentResponseDryRun, setExperimentResponseDryRun] = useState<ExperimentResponseDryRun | null>(null);
  const [experimentImportedReviewId, setExperimentImportedReviewId] = useState<string | null>(null);

  async function loadPages() {
    const data = await fetchJson<{ pages: PageSummary[] }>("/api/pages");
    setPages(data.pages);
    setBundlePageIds((current) => current.filter((pageId) => data.pages.some((item) => pageIdFromSlug(item.slug) === pageId)));
    if (!data.pages.some((item) => item.slug === selectedSlug) && data.pages[0]) {
      setSelectedSlug(data.pages[0].slug);
    }
  }

  const sortedPages = useMemo(() => {
    const classRank = (page: PageSummary) => Number(page.system_tier || 3);
    const sorted = [...pages].sort((left, right) => {
      let value = 0;
      if (pageSort === "recent") {
        value = new Date(left.updated_at || 0).getTime() - new Date(right.updated_at || 0).getTime();
      } else if (pageSort === "links") {
        value = (Number(left.links_count || 0) + Number(left.citations_count || 0)) - (Number(right.links_count || 0) + Number(right.citations_count || 0));
      } else {
        value = classRank(left) - classRank(right);
      }
      if (value === 0) {
        value = left.title.localeCompare(right.title);
      }
      return pageSortDir === "asc" ? value : -value;
    });
    return sorted;
  }, [pageSort, pageSortDir, pages]);

  const pageIconClass = (page: PageSummary) => {
    if (page.system_tier === 1) {
      return "page-icon system";
    }
    if (page.system_tier === 2) {
      return "page-icon managed";
    }
    return "page-icon";
  };

  useEffect(() => {
    const stored = window.localStorage.getItem(sessionStorageKey);
    const storedVault = window.localStorage.getItem(vaultStorageKey);
    if (stored) {
      setSessionToken(stored);
    }
    if (storedVault) {
      setVaultId(storedVault);
    }
    loadPages()
      .then(() => setStatus("Ready"))
      .catch((error: Error) => setStatus(error.message));
  }, []);

  useEffect(() => {
    fetchJson<ActorState>("/api/auth/me", {}, sessionToken, vaultId)
      .then(setActor)
      .catch(() => setActor(null));
  }, [sessionToken, vaultId]);

  async function loadVaults(token = sessionToken) {
    if (!token && actor?.actor_type !== "local") {
      setVaults([{ id: "local-default", name: "Local", role: "viewer" }]);
      return;
    }
    try {
      const data = await fetchJson<{ vaults: Vault[]; current_vault_id: string }>("/api/vaults", {}, token, vaultId);
      setVaults(data.vaults);
    } catch {
      setVaults([{ id: "local-default", name: "Local", role: "owner" }]);
    }
  }

  useEffect(() => {
    loadVaults();
  }, [sessionToken, actor?.actor_type, vaultId]);

  async function loadSubmissions(token = sessionToken) {
    if (!token) {
      setSubmissions([]);
      return;
    }
    try {
      const data = await fetchJson<{ submissions: Submission[] }>("/api/submissions", {}, token, vaultId);
      setSubmissions(data.submissions);
    } catch {
      setSubmissions([]);
    }
  }

  useEffect(() => {
    loadSubmissions();
  }, [sessionToken, actor?.role, vaultId]);

  async function loadCitationAudits(token = sessionToken) {
    if (!token && actor?.actor_type !== "local") {
      setCitationAudits([]);
      return;
    }
    try {
      const data = await fetchJson<{ audits: CitationAudit[] }>(
        `/api/citations/audits?vault_id=${encodeURIComponent(vaultId)}&status=unsupported,contradicted,stale,needs_review&limit=20`,
        {},
        token,
        vaultId,
      );
      setCitationAudits(data.audits);
    } catch {
      setCitationAudits([]);
    }
  }

  useEffect(() => {
    loadCitationAudits();
  }, [sessionToken, actor?.role, vaultId]);

  async function loadCollaborationReviews(token = sessionToken) {
    if (!token && actor?.actor_type !== "local") {
      setCollaborationReviews([]);
      return;
    }
    try {
      const data = await fetchJson<{ reviews: CollaborationReviewSummary[] }>(
        `/api/collaboration/reviews?vault_id=${encodeURIComponent(vaultId)}&status=pending_review`,
        {},
        token,
        vaultId,
      );
      setCollaborationReviews(data.reviews);
    } catch {
      setCollaborationReviews([]);
    }
  }

  useEffect(() => {
    loadCollaborationReviews();
  }, [sessionToken, actor?.role, vaultId]);

  async function loadOperatorConsole() {
    if (!sessionToken && actor?.actor_type !== "local") {
      setAiStateQuality(null);
      setProviderMatrix(null);
      setModelRuns([]);
      setReleaseReadiness(null);
      return;
    }
    try {
      const [quality, matrix, runs, readiness] = await Promise.all([
        fetchJson<AiStateQuality>(`/api/operator/ai-state-quality?vault_id=${encodeURIComponent(vaultId)}`, {}, sessionToken, vaultId),
        fetchJson<ProviderMatrix>("/api/operator/provider-matrix", {}, sessionToken, vaultId),
        fetchJson<{ runs: ModelRun[] }>("/api/model-runs?limit=12", {}, sessionToken, vaultId),
        fetchJson<ReleaseReadiness>(`/api/operator/release-readiness?vault_id=${encodeURIComponent(vaultId)}`, {}, sessionToken, vaultId),
      ]);
      setAiStateQuality(quality);
      setProviderMatrix(matrix);
      setModelRuns(runs.runs);
      setReleaseReadiness(readiness);
      if (selectedModelRun) {
        const refreshed = runs.runs.find((run) => run.id === selectedModelRun.id);
        if (refreshed) {
          setSelectedModelRun(refreshed);
        }
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Operator console load failed");
    }
  }

  useEffect(() => {
    loadOperatorConsole();
  }, [sessionToken, actor?.actor_type, vaultId]);

  async function loadGraph() {
    try {
      const params = new URLSearchParams({
        vault_id: vaultId,
        node_type: graphNodeType,
        limit: "500",
      });
      if (graphStatus) {
        params.set("status", graphStatus);
      }
      const data = await fetchJson<GraphData>(`/api/graph?${params.toString()}`, {}, sessionToken, vaultId);
      setGraph(data);
      setGraphError(null);
      if (data.nodes.length > 1000) {
        setGraphMode("list");
      }
    } catch (error) {
      setGraph(null);
      setGraphError(error instanceof Error ? error.message : "Graph load failed");
      setGraphMode("list");
    }
  }

  useEffect(() => {
    loadGraph();
  }, [sessionToken, vaultId, graphNodeType, graphStatus]);

  async function loadOperations() {
    try {
      const health = await fetchJson<HealthSummary>("/health/summary", {}, sessionToken, vaultId);
      setHealthSummary(health);
    } catch {
      setHealthSummary(null);
    }
    if (!sessionToken && actor?.actor_type !== "local") {
      setSnapshots([]);
      setMaintenanceLocks([]);
      return;
    }
    try {
      const [snapshotData, lockData] = await Promise.all([
        fetchJson<{ snapshots: SnapshotSummary[] }>("/api/maintenance/snapshots", {}, sessionToken, vaultId),
        fetchJson<{ locks: MaintenanceLock[] }>("/api/maintenance/locks", {}, sessionToken, vaultId),
      ]);
      setSnapshots(snapshotData.snapshots);
      setMaintenanceLocks(lockData.locks);
    } catch {
      setSnapshots([]);
      setMaintenanceLocks([]);
    }
  }

  useEffect(() => {
    loadOperations();
    const interval = window.setInterval(loadOperations, healthSummary?.overall_status === "attention_required" ? 30000 : 60000);
    return () => window.clearInterval(interval);
  }, [sessionToken, actor?.actor_type, vaultId, healthSummary?.overall_status]);

  useEffect(() => {
    if (!selectedSlug) {
      return;
    }
    fetchJson<Page>(`/api/pages/${encodeURIComponent(selectedSlug)}`)
      .then(setPage)
      .catch((error: Error) => setStatus(error.message));
    fetchJson<LinkSummary>(`/api/pages/${encodeURIComponent(selectedSlug)}/links`)
      .then(setLinkSummary)
      .catch(() => setLinkSummary(null));
    fetchJson<BacklinkSummary>(`/api/pages/${encodeURIComponent(selectedSlug)}/backlinks`)
      .then(setBacklinkSummary)
      .catch(() => setBacklinkSummary(null));
  }, [selectedSlug]);

  async function submitMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!message.trim()) {
      return;
    }
    setSubmitting(true);
    try {
      const data = await fetchJson<{ message_id: string; job_id: string; status: string }>("/api/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: message.trim() }),
      }, sessionToken, vaultId);
      setMessage("");
      setSuggestion(null);
      setSuggestionDiff(null);
      setActiveJobId(data.job_id);
      setStatus(`Saved: ${data.message_id}`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Save failed");
    } finally {
      setSubmitting(false);
    }
  }

  async function applySuggestion() {
    if (!suggestion) {
      return;
    }
    try {
      const result = await fetchJson<{ slug: string; status: string; citation_warnings?: Array<{ status: string }> }>(`/api/suggestions/${suggestion.id}/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      }, sessionToken, vaultId);
      setStatus(result.citation_warnings?.length ? `Applied with ${result.citation_warnings.length} citation warning(s)` : "Applied to page");
      setSelectedSlug(result.slug);
      setSuggestion({ ...suggestion, status: result.status });
      setSuggestionDiff(suggestionDiff ? { ...suggestionDiff, status: result.status } : null);
      await loadPages();
      await loadCitationAudits();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Apply failed");
    }
  }

  async function rejectSuggestion() {
    if (!suggestion) {
      return;
    }
    try {
      const result = await fetchJson<{ suggestion_id: string; status: string }>(`/api/suggestions/${suggestion.id}/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "Rejected from review panel" }),
      }, sessionToken, vaultId);
      setStatus("Rejected suggestion");
      setSuggestion({ ...suggestion, status: result.status });
      setSuggestionDiff(suggestionDiff ? { ...suggestionDiff, status: result.status } : null);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Reject failed");
    }
  }

  async function createPageFromLink(target: string) {
    try {
      const result = await fetchJson<{ slug: string }>("/api/pages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug: target }),
      }, sessionToken, vaultId);
      setStatus("Created page");
      await loadPages();
      setSelectedSlug(result.slug);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Create page failed");
    }
  }

  useEffect(() => {
    if (!activeJobId) {
      return;
    }
    const source = new EventSource(`${apiBase}/api/events/jobs/${activeJobId}`);

    source.addEventListener("job.queued", () => {
      setStatus("Queued");
    });
    source.addEventListener("job.running", () => {
      setStatus("Processing");
    });
    source.addEventListener("job.failed", (event) => {
      const payload = JSON.parse((event as MessageEvent).data);
      setStatus(`Failed: ${payload.error_code ?? "unknown"}`);
      source.close();
    });
    source.addEventListener("job.completed", async (event) => {
      const payload = JSON.parse((event as MessageEvent).data);
      setStatus("Draft ready");
      source.close();
      if (payload.suggestion_id) {
        const data = await fetchJson<Suggestion>(`/api/suggestions/${payload.suggestion_id}`);
        setSuggestion(data);
        const diff = await fetchJson<SuggestionDiff>(`/api/suggestions/${payload.suggestion_id}/diff`);
        setSuggestionDiff(diff);
      }
    });
    source.onerror = () => {
      setStatus("Reconnecting status stream");
    };

    return () => source.close();
  }, [activeJobId]);

  const canWrite = !actor || ["owner", "admin", "editor"].includes(actor.role);
  const canOperate = !actor || ["owner", "admin"].includes(actor.role);
  const canManageAgents = !actor || ["owner", "admin"].includes(actor.role);

  async function rebuildGraph() {
    if (!canOperate) {
      setStatus("Owner or admin login required");
      return;
    }
    setOpsBusyAction("graph");
    setStatus("Rebuilding graph");
    try {
      const result = await fetchJson<{ created: number; failed: number }>(
        "/api/graph/rebuild",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ scope: "vault" }),
        },
        sessionToken,
        vaultId,
      );
      setStatus(`Graph rebuilt: ${result.created} changes`);
      await loadGraph();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Graph rebuild failed");
    } finally {
      setOpsBusyAction(null);
    }
  }

  async function createSnapshot() {
    if (!canOperate) {
      setStatus("Owner or admin login required");
      return;
    }
    setOpsBusyAction("snapshot");
    setStatus("Creating snapshot");
    try {
      const result = await fetchJson<{ name: string }>(
        "/api/maintenance/snapshots",
        { method: "POST" },
        sessionToken,
        vaultId,
      );
      setStatus(`Snapshot created: ${result.name}`);
      await loadOperations();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Snapshot failed");
    } finally {
      setOpsBusyAction(null);
    }
  }

  async function runVerifyIndex() {
    if (!canOperate) {
      setStatus("Owner or admin login required");
      return;
    }
    setOpsBusyAction("verify");
    setStatus("Running verify");
    try {
      const result = await fetchJson<{ issues: Array<{ code: string }> }>(
        "/api/maintenance/verify-index",
        {},
        sessionToken,
        vaultId,
      );
      setVerifyIssues(result.issues.length);
      setStatus(result.issues.length ? `Verify found ${result.issues.length} issue(s)` : "Verify passed");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Verify failed");
    } finally {
      setOpsBusyAction(null);
    }
  }

  async function inspectRestorePlan() {
    if (!canOperate || !snapshots[0]) {
      return;
    }
    setOpsBusyAction("restore-plan");
    setStatus("Inspecting restore plan");
    try {
      const plan = await fetchJson<RestorePlan>(
        `/api/maintenance/restore-plan?snapshot_name=${encodeURIComponent(snapshots[0].name)}`,
        {},
        sessionToken,
        vaultId,
      );
      setRestorePlan(plan);
      setRestoreConfirmValue("");
      setStatus(plan.can_restore_now ? "Restore plan ready" : "Restore blocked by maintenance lock");
      await loadOperations();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Restore plan failed");
    } finally {
      setOpsBusyAction(null);
    }
  }

  async function restoreSnapshotFromPlan() {
    if (!canOperate || !restorePlan || restoreConfirmValue !== restorePlan.snapshot) {
      return;
    }
    setOpsBusyAction("restore");
    setStatus("Restoring snapshot");
    try {
      await fetchJson<{ snapshot: string; pre_restore?: { name?: string } }>(
        "/api/maintenance/restore",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ snapshot_name: restorePlan.snapshot }),
        },
        sessionToken,
        vaultId,
      );
      setStatus("Snapshot restored; running verify-index is required");
      setRestoreConfirmValue("");
      setRestorePlan(null);
      await loadOperations();
      await loadPages();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Restore failed");
    } finally {
      setOpsBusyAction(null);
    }
  }

  async function startGeminiMockRun() {
    if (!canOperate) {
      setStatus("Owner or admin login required");
      return;
    }
    setOperatorBusyAction("mock-run");
    setStatus("Starting Gemini mock review");
    try {
      const result = await fetchJson<{ run: ModelRun }>(
        "/api/model-runs/gemini/reviews",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mock: true, review_focus: "Phase 17 operator console acceptance run", max_pages: 20 }),
        },
        sessionToken,
        vaultId,
      );
      setSelectedModelRun(result.run);
      setStatus(`Model run ready: ${result.run.id}`);
      await loadOperatorConsole();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Model run failed");
    } finally {
      setOperatorBusyAction(null);
    }
  }

  async function importSelectedModelRun() {
    if (!selectedModelRun) {
      return;
    }
    setOperatorBusyAction("import-run");
    setStatus("Importing model review");
    try {
      const result = await fetchJson<{ run: ModelRun; findings: CollaborationFinding[] }>(
        `/api/model-runs/${selectedModelRun.id}/import`,
        { method: "POST" },
        sessionToken,
        vaultId,
      );
      setSelectedModelRun(result.run);
      setStatus(`Imported ${result.findings.length} finding(s)`);
      await loadOperatorConsole();
      await loadCollaborationReviews();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Model import failed");
    } finally {
      setOperatorBusyAction(null);
    }
  }

  async function generateProjectSnapshotPacket() {
    setOperatorBusyAction("project-snapshot");
    setStatus("Generating project snapshot packet");
    try {
      const data = await fetchJson<ProjectSnapshotPacket>(
        "/api/collaboration/project-snapshot-packets",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            vault_id: vaultId,
            target_agent: projectSnapshotTargetAgent === "all" ? "multi_ai" : projectSnapshotTargetAgent,
            profile: projectSnapshotProfile,
            output_mode: projectSnapshotOutputMode,
            since_packet_id: projectSnapshotSincePacketId.trim() || undefined,
            allow_since_packet_fallback: false,
            quality_acknowledged: projectSnapshotQualityAcknowledged,
            focus: projectSnapshotFocus.trim() || "Read this KnowNet project state, identify the highest-leverage next action, and avoid release_check unless release verification is explicitly requested.",
          }),
        },
        sessionToken,
        vaultId,
      );
      setProjectSnapshotPacket(data);
      setStatus(`Project snapshot ready: ${data.id}`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Project snapshot failed");
    } finally {
      setOperatorBusyAction(null);
    }
  }

  function applyProjectSnapshotStandardizationPreset() {
    setProjectSnapshotTargetAgent("all");
    setProjectSnapshotProfile("overview");
    setProjectSnapshotOutputMode("top_findings");
    setProjectSnapshotSincePacketId("");
    setProjectSnapshotFocus("Review packet/snapshot standardization. Score sufficiency, list only top 5 concrete changes, and avoid overbuilt platform work.");
    setStatus("Project packet preset applied");
  }

  async function copyProjectSnapshotPacket() {
    if (!projectSnapshotPacket) {
      return;
    }
    try {
      await navigator.clipboard.writeText(projectSnapshotPacket.content);
      setStatus(`Copied project snapshot: ${projectSnapshotPacket.id}`);
    } catch {
      setStatus("Clipboard unavailable");
    }
  }

  async function copyProjectSnapshotMultiAiPrompt() {
    if (!projectSnapshotPacket) {
      return;
    }
    const targetLabel = projectSnapshotTargetAgent === "all" ? "DeepSeek, Qwen, Kimi, MiniMax, GLM, Claude, or Codex" : projectSnapshotTargetAgent;
    const targetRule =
      projectSnapshotTargetAgent === "all"
        ? "This prompt is intended to be pasted unchanged into multiple AI systems. Do not adapt the packet per model."
        : `This prompt is intended for ${projectSnapshotTargetAgent}. Keep the answer tailored to that model's strengths but do not change the requested output shape.`;
    const prompt = [
      "You are reviewing KnowNet packet and snapshot standardization.",
      `Target: ${targetLabel}.`,
      targetRule,
      "",
      "Use the same packet below. Evaluate only from the supplied packet. Do not ask for raw DB, filesystem, shell, secrets, backups, sessions, users, or tokens.",
      "",
      "Return exactly:",
      "1. Score out of 100",
      "2. Is it enough for now, insufficient, or overbuilt?",
      "3. Top 5 concrete changes only",
      "4. What should NOT be changed next",
      "5. Any standard/open-source pattern we should absorb instead of inventing",
      "",
      "Rules:",
      "- Prefer lightweight standard shapes: JSON Schema, OpenAPI-style params, MCP terminology, W3C trace context.",
      "- Focus on making external AI read faster, ask shorter questions, produce importable findings/tasks, and help Codex implement faster.",
      "- Remove anything overbuilt for a small local-first project.",
      "",
      "KnowNet packet:",
      "```text",
      projectSnapshotPacket.content,
      "```",
    ].join("\n");
    try {
      await navigator.clipboard.writeText(prompt);
      setStatus("Copied multi-AI prompt");
    } catch {
      setStatus("Copy failed");
    }
  }

  async function generateExperimentPacket() {
    if (!canOperate) {
      setStatus("Owner or admin login required");
      return;
    }
    setOperatorBusyAction("experiment-packet");
    setStatus("Generating experiment packet");
    try {
      const scenarios = experimentScenarios
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);
      const result = await fetchJson<ExperimentPacket>(
        "/api/collaboration/experiment-packets",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            vault_id: vaultId,
            experiment_name: experimentName.trim() || "External AI experiment",
            task: experimentTask.trim() || "Perform the requested experiment step only.",
            target_agent: "claude",
            scenarios,
            output_schema: "Return Access Status and Scenario Decision Table first. Include parser-ready Finding blocks only when an item should be imported.",
            max_node_chars: 1200,
          }),
        },
        sessionToken,
        vaultId,
      );
      setExperimentPacket(result);
      setExperimentResponseDryRun(null);
      setExperimentImportedReviewId(null);
      setStatus(`Experiment packet ready: ${result.content_hash.slice(0, 12)}`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Experiment packet failed");
    } finally {
      setOperatorBusyAction(null);
    }
  }

  async function copyExperimentPacket() {
    if (!experimentPacket) {
      return;
    }
    try {
      await navigator.clipboard.writeText(experimentPacket.content);
      setStatus("Experiment packet copied");
    } catch {
      setStatus("Clipboard copy failed");
    }
  }

  async function dryRunExperimentResponse() {
    if (!experimentPacket || !experimentResponseMarkdown.trim()) {
      return;
    }
    setOperatorBusyAction("experiment-response");
    setStatus("Parsing experiment response");
    try {
      const result = await fetchJson<ExperimentResponseDryRun>(
        `/api/collaboration/experiment-packets/${experimentPacket.id}/responses/dry-run`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source_agent: "external_ai", response_markdown: experimentResponseMarkdown }),
        },
        sessionToken,
        vaultId,
      );
      setExperimentResponseDryRun(result);
      setExperimentImportedReviewId(null);
      setStatus(`Response parsed: ${result.finding_count} finding(s)`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Response parse failed");
    } finally {
      setOperatorBusyAction(null);
    }
  }

  async function importExperimentResponse() {
    if (!experimentPacket || !experimentResponseDryRun) {
      return;
    }
    setOperatorBusyAction("experiment-import");
    setStatus("Importing experiment response");
    try {
      const result = await fetchJson<{ review: CollaborationReviewSummary; findings: CollaborationFinding[] }>(
        `/api/collaboration/experiment-packets/${experimentPacket.id}/responses/${experimentResponseDryRun.response_id}/import`,
        { method: "POST" },
        sessionToken,
        vaultId,
      );
      setExperimentImportedReviewId(result.review.id);
      setStatus(`Imported response: ${result.findings.length} finding(s)`);
      await loadCollaborationReviews();
      await loadCollaborationReview(result.review.id);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Response import failed");
    } finally {
      setOperatorBusyAction(null);
    }
  }

  async function openGraphNode(node: GraphNode) {
    setSelectedGraphNode(node);
    if (node.node_type === "page" && typeof node.meta.slug === "string") {
      setSelectedSlug(node.meta.slug);
    }
    if (node.node_type === "review" && typeof node.target_id === "string") {
      await loadCollaborationReview(node.target_id);
    }
  }

  function toggleBundlePage(slug: string) {
    const pageId = pageIdFromSlug(slug);
    setBundlePageIds((current) => (current.includes(pageId) ? current.filter((item) => item !== pageId) : [...current, pageId]));
  }

  async function toggleGraphNodePin(node: GraphNode, pinned: boolean) {
    try {
      await fetchJson<{ status: string; node_id: string; pinned: boolean }>(
        "/api/graph/pins/nodes",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ node_id: node.id, pinned }),
        },
        sessionToken,
        vaultId,
      );
      setStatus(pinned ? "Pinned core node" : "Unpinned core node");
      await loadGraph();
      setSelectedGraphNode((current) =>
        current?.id === node.id
          ? {
              ...current,
              meta: {
                ...current.meta,
                user_pinned: pinned,
                core: pinned || current.meta.auto_core,
              },
            }
          : current,
      );
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Pin failed");
    }
  }

  async function submitAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const path = authMode === "bootstrap" ? "/api/auth/bootstrap" : "/api/auth/login";
    try {
      const data = await fetchJson<{ session_id: string; role: string; username: string }>(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      window.localStorage.setItem(sessionStorageKey, data.session_id);
      setSessionToken(data.session_id);
      setPassword("");
      setStatus(`${data.username} signed in`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Sign in failed");
    }
  }

  async function logout() {
    try {
      await fetchJson<{ status: string }>("/api/auth/logout", { method: "POST" }, sessionToken, vaultId);
    } catch {
      // Local-only mode may not have an active session; clearing the client token is still correct.
    }
    window.localStorage.removeItem(sessionStorageKey);
    setSessionToken(null);
    setActor(null);
    setStatus("Signed out");
  }

  async function reviewSubmission(submissionId: string, action: "approve" | "reject") {
    try {
      const data = await fetchJson<{ status: string; job_id?: string }>(
        `/api/submissions/${submissionId}/${action}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ note: action === "approve" ? "Approved from web review queue" : "Rejected from web review queue" }),
        },
        sessionToken,
        vaultId,
      );
      setStatus(action === "approve" ? `Queued: ${data.job_id}` : "Submission rejected");
      await loadSubmissions();
      if (data.job_id) {
        setActiveJobId(data.job_id);
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Review failed");
    }
  }

  async function importCollaborationReview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!reviewMarkdown.trim()) {
      return;
    }
    try {
      const data = await fetchJson<{ review: CollaborationReviewSummary; findings: CollaborationFinding[] }>(
        "/api/collaboration/reviews",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ vault_id: vaultId, markdown: reviewMarkdown.trim(), source_agent: "external-ai" }),
        },
        sessionToken,
        vaultId,
      );
      setReviewMarkdown("");
      setStatus(`Imported review: ${data.findings.length} finding(s)`);
      await loadCollaborationReviews();
      await loadCollaborationReview(data.review.id);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Review import failed");
    }
  }

  async function loadCollaborationReview(reviewId: string) {
    try {
      const data = await fetchJson<CollaborationReviewDetail>(`/api/collaboration/reviews/${reviewId}`, {}, sessionToken, vaultId);
      setSelectedCollaborationReview(data);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Review load failed");
    }
  }

  async function decideCollaborationFinding(findingId: string, decision: "accepted" | "rejected" | "deferred" | "needs_more_context") {
    try {
      await fetchJson<{ finding_id: string; status: string }>(
        `/api/collaboration/findings/${findingId}/decision`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: decision, decision_note: `Marked ${decision} from Review Inbox` }),
        },
        sessionToken,
        vaultId,
      );
      setStatus(`Finding ${decision}`);
      if (selectedCollaborationReview) {
        await loadCollaborationReview(selectedCollaborationReview.review.id);
      }
      await loadCollaborationReviews();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Decision failed");
    }
  }

  async function createFindingTask(findingId: string) {
    try {
      const data = await fetchJson<{ task: FindingTask }>(
        `/api/collaboration/findings/${findingId}/task`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ priority: "normal", owner: "codex", notes: "Created from Review Inbox" }),
        },
        sessionToken,
        vaultId,
      );
      setStatus(`Task ready: ${data.task.id}`);
      if (selectedCollaborationReview) {
        await loadCollaborationReview(selectedCollaborationReview.review.id);
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Task creation failed");
    }
  }

  async function createContextBundleForCurrentPage() {
    const selectedPageIds = bundlePageIds.length ? bundlePageIds : selectedSlug ? [pageIdFromSlug(selectedSlug)] : [];
    if (!selectedPageIds.length) {
      return;
    }
    try {
      const data = await fetchJson<{ manifest: { filename: string } }>(
        "/api/collaboration/context-bundles",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ vault_id: vaultId, page_ids: selectedPageIds, include_graph_summary: true }),
        },
        sessionToken,
        vaultId,
      );
      setBundleStatus(data.manifest.filename);
      setStatus(`Context bundle created: ${data.manifest.filename}`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Context bundle failed");
    }
  }

  async function markCitationNeedsReview(auditId: string) {
    try {
      await fetchJson<{ audit_id: string; status: string }>(
        `/api/citations/audits/${auditId}/needs-review`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reason: "Marked from web citation queue" }),
        },
        sessionToken,
        vaultId,
      );
      setStatus("Citation marked for review");
      await loadCitationAudits();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Citation review failed");
    }
  }

  async function createVault(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!newVaultName.trim()) {
      return;
    }
    try {
      const data = await fetchJson<{ vault_id: string; name: string }>(
        "/api/vaults",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: newVaultName.trim() }),
        },
        sessionToken,
        vaultId,
      );
      setVaultId(data.vault_id);
      window.localStorage.setItem(vaultStorageKey, data.vault_id);
      setNewVaultName("");
      setStatus(`Vault created: ${data.name}`);
      await loadVaults();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Vault create failed");
    }
  }

  return (
    <main className={sidebarOpen ? "shell" : "shell sidebar-closed"}>
      <button
        aria-label={sidebarOpen ? "Hide sidebar" : "Show sidebar"}
        className="sidebar-toggle"
        onClick={() => setSidebarOpen((value) => !value)}
        type="button"
      >
        {sidebarOpen ? <PanelLeftClose aria-hidden size={16} /> : <PanelLeftOpen aria-hidden size={16} />}
        {sidebarOpen ? "Hide menu" : "Menu"}
      </button>
      <aside className="sidebar" aria-hidden={!sidebarOpen}>
        <div className="sidebar-head">
          <div>
            <img alt="KnowNet" className="brand-logo" src="/knownet-logo.png" />
            <p className="eyebrow">KnowNet</p>
            <h1>AI Collaboration Knowledge Base</h1>
          </div>
          <button onClick={() => setSidebarOpen(false)} type="button">
            <PanelLeftClose aria-hidden size={16} />
            Hide
          </button>
        </div>
        {activeWorkspace === "map" ? (
          <>
            <div className="page-list-tools" aria-label="Page sorting">
              <select aria-label="Sort pages" value={pageSort} onChange={(event) => setPageSort(event.target.value as "recent" | "links" | "class")}>
                <option value="recent">Recent</option>
                <option value="links">Connected</option>
                <option value="class">Class</option>
              </select>
              <button aria-label="Toggle page sort direction" onClick={() => setPageSortDir((current) => (current === "asc" ? "desc" : "asc"))} type="button">
                {pageSortDir === "asc" ? <ChevronsUp aria-hidden size={15} /> : <ChevronsDown aria-hidden size={15} />}
                {pageSortDir === "asc" ? "Asc" : "Desc"}
              </button>
            </div>
            <nav className="page-list" aria-label="Pages">
              {sortedPages.map((item) => (
                <button
                  className={item.slug === selectedSlug ? "page-link active" : "page-link"}
                  key={item.slug}
                  onClick={() => setSelectedSlug(item.slug)}
                  type="button"
                >
                  <span>
                    <FileText aria-hidden className={pageIconClass(item)} size={15} />
                    {item.title}
                  </span>
                  <small>
                    {item.links_count} links / {item.citations_count} refs
                    {item.system_kind ? ` / ${item.system_kind}` : ""}
                  </small>
                </button>
              ))}
            </nav>
          </>
        ) : null}
        <section className="auth-panel">
          <div className="actor-row">
            <div>
              <p className="eyebrow">Actor</p>
              <strong>{actor ? actor.actor_type : "local"}</strong>
              <small>{actor ? `${actor.role} / ${actor.vault_id}` : "owner / local-default"}</small>
            </div>
            {sessionToken ? (
              <button onClick={logout} type="button">
                <LogOut aria-hidden size={15} />
                Logout
              </button>
            ) : null}
          </div>
          {!sessionToken ? (
            <form className="auth-form" onSubmit={submitAuth}>
              <div className="auth-tabs">
                <button className={authMode === "login" ? "active" : ""} onClick={() => setAuthMode("login")} type="button">
                  <LogIn aria-hidden size={15} />
                  Login
                </button>
                <button className={authMode === "bootstrap" ? "active" : ""} onClick={() => setAuthMode("bootstrap")} type="button">
                  <KeyRound aria-hidden size={15} />
                  Bootstrap
                </button>
              </div>
              <input aria-label="Username" placeholder="Username" value={username} onChange={(event) => setUsername(event.target.value)} />
              <input
                aria-label="Password"
                minLength={authMode === "bootstrap" ? 8 : 1}
                placeholder="Password"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
              {authMode === "bootstrap" ? <small>Owner password must be at least 8 characters.</small> : null}
              <button type="submit">
                {authMode === "bootstrap" ? <ShieldCheck aria-hidden size={15} /> : <LogIn aria-hidden size={15} />}
                {authMode === "bootstrap" ? "Create owner" : "Login"}
              </button>
            </form>
          ) : null}
          <div className="vault-select">
            <label htmlFor="vault">Vault</label>
            <select
              id="vault"
              value={vaultId}
              onChange={(event) => {
                setVaultId(event.target.value);
                window.localStorage.setItem(vaultStorageKey, event.target.value);
              }}
            >
              {(vaults.length ? vaults : [{ id: "local-default", name: "Local", role: "owner" }]).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} ({item.role})
                </option>
              ))}
            </select>
            {actor && ["owner", "admin"].includes(actor.role) ? (
              <form onSubmit={createVault}>
                <input
                  aria-label="New vault name"
                  placeholder="New vault"
                  value={newVaultName}
                  onChange={(event) => setNewVaultName(event.target.value)}
                />
                <button type="submit">
                  <CirclePlus aria-hidden size={15} />
                  Create
                </button>
              </form>
            ) : null}
          </div>
        </section>
        {activeWorkspace === "operator" ? (
          <>
            <form className="inbox" onSubmit={submitMessage}>
              <label htmlFor="message">Inbox</label>
              <textarea
                id="message"
                placeholder="Drop a note, question, or experiment log"
                value={message}
                onChange={(event) => setMessage(event.target.value)}
              />
              <button disabled={submitting || !canWrite} type="submit">
                <Save aria-hidden size={15} />
                {submitting ? "Saving" : "Save"}
              </button>
              <p>{status}</p>
            </form>
            {submissions.length ? (
              <section className="review-panel">
                <p className="eyebrow">Review</p>
                {submissions.slice(0, 5).map((item) => (
                  <div className="review-item" key={item.id}>
                    <small>{item.actor_type}</small>
                    <strong>{item.message_id}</strong>
                    <div>
                      <button onClick={() => reviewSubmission(item.id, "reject")} type="button">
                        <X aria-hidden size={15} />
                        Reject
                      </button>
                      <button onClick={() => reviewSubmission(item.id, "approve")} type="button">
                        <Check aria-hidden size={15} />
                        Approve
                      </button>
                    </div>
                  </div>
                ))}
              </section>
            ) : null}
          </>
        ) : null}
        {activeWorkspace === "map" && citationAudits.length ? (
          <section className="review-panel citation-panel">
            <p className="eyebrow">Citations</p>
            {citationAudits.slice(0, 5).map((item) => (
              <div className="review-item" key={item.id}>
                <small>{item.status} / {item.verifier_type}</small>
                <strong>{item.display_title || item.citation_key}</strong>
                {item.display_title && item.display_title !== item.citation_key ? <small>{item.citation_key}</small> : null}
                <p>{item.reason || item.claim_text}</p>
                <div>
                  <button onClick={() => markCitationNeedsReview(item.id)} type="button">
                    <SquarePen aria-hidden size={15} />
                    Needs review
                  </button>
                </div>
              </div>
            ))}
          </section>
        ) : null}
      </aside>
      <section className="workspace">
        <WorkspaceTabs activeWorkspace={activeWorkspace} canManageAgents={canManageAgents} onChange={setActiveWorkspace} />
        {activeWorkspace === "agents" && canManageAgents ? (
          <AgentDashboardWorkspace sessionToken={sessionToken} vaultId={vaultId} />
        ) : (
          <>
        {activeWorkspace === "operator" ? (
          <OperatorConsoleWorkspace
            healthSummary={healthSummary}
            aiStateQuality={aiStateQuality}
            releaseReadiness={releaseReadiness}
            providerMatrix={providerMatrix}
            modelRuns={modelRuns}
            selectedModelRun={selectedModelRun}
            canOperate={canOperate}
            canManageAgents={canManageAgents}
            operatorBusyAction={operatorBusyAction}
            opsBusyAction={opsBusyAction}
            snapshots={snapshots}
            maintenanceLocks={maintenanceLocks}
            restorePlan={restorePlan}
            restoreConfirmValue={restoreConfirmValue}
            verifyIssues={verifyIssues}
            onRefresh={loadOperatorConsole}
            onStartGeminiMockRun={startGeminiMockRun}
            onSelectModelRun={setSelectedModelRun}
            onOpenCollaborationReview={loadCollaborationReview}
            onImportSelectedModelRun={importSelectedModelRun}
            onCreateSnapshot={createSnapshot}
            onRunVerifyIndex={runVerifyIndex}
            onRebuildGraph={rebuildGraph}
            onInspectRestorePlan={inspectRestorePlan}
            onRestoreConfirmChange={setRestoreConfirmValue}
            onRestoreSnapshot={restoreSnapshotFromPlan}
          />
        ) : null}
        {activeWorkspace === "packets" ? (
          <AIPacketsWorkspace
            canOperate={canOperate}
            operatorBusyAction={operatorBusyAction}
            projectSnapshotPacket={projectSnapshotPacket}
            projectSnapshotTargetAgent={projectSnapshotTargetAgent}
            projectSnapshotProfile={projectSnapshotProfile}
            projectSnapshotOutputMode={projectSnapshotOutputMode}
            projectSnapshotFocus={projectSnapshotFocus}
            projectSnapshotSincePacketId={projectSnapshotSincePacketId}
            projectSnapshotQualityAcknowledged={projectSnapshotQualityAcknowledged}
            experimentPacket={experimentPacket}
            experimentName={experimentName}
            experimentTask={experimentTask}
            experimentScenarios={experimentScenarios}
            experimentResponseMarkdown={experimentResponseMarkdown}
            experimentResponseDryRun={experimentResponseDryRun}
            experimentImportedReviewId={experimentImportedReviewId}
            onGenerateProjectSnapshotPacket={generateProjectSnapshotPacket}
            onCopyProjectSnapshotPacket={copyProjectSnapshotPacket}
            onCopyProjectSnapshotMultiAiPrompt={copyProjectSnapshotMultiAiPrompt}
            onProjectSnapshotTargetAgentChange={setProjectSnapshotTargetAgent}
            onProjectSnapshotProfileChange={setProjectSnapshotProfile}
            onProjectSnapshotOutputModeChange={setProjectSnapshotOutputMode}
            onProjectSnapshotFocusChange={setProjectSnapshotFocus}
            onApplyProjectSnapshotStandardizationPreset={applyProjectSnapshotStandardizationPreset}
            onProjectSnapshotSincePacketIdChange={setProjectSnapshotSincePacketId}
            onProjectSnapshotQualityAcknowledgedChange={setProjectSnapshotQualityAcknowledged}
            onGenerateExperimentPacket={generateExperimentPacket}
            onCopyExperimentPacket={copyExperimentPacket}
            onExperimentNameChange={setExperimentName}
            onExperimentTaskChange={setExperimentTask}
            onExperimentScenariosChange={setExperimentScenarios}
            onExperimentResponseMarkdownChange={setExperimentResponseMarkdown}
            onDryRunExperimentResponse={dryRunExperimentResponse}
            onImportExperimentResponse={importExperimentResponse}
          />
        ) : null}
        {activeWorkspace === "reviews" ? (
          <AIReviewsWorkspace
            canWrite={canWrite}
            canOperate={canOperate}
            reviewMarkdown={reviewMarkdown}
            collaborationReviews={collaborationReviews}
            selectedCollaborationReview={selectedCollaborationReview}
            onReviewMarkdownChange={setReviewMarkdown}
            onImportReview={importCollaborationReview}
            onRefresh={loadCollaborationReviews}
            onLoadReview={loadCollaborationReview}
            onDecideFinding={decideCollaborationFinding}
            onCreateFindingTask={createFindingTask}
          />
        ) : null}
        {activeWorkspace === "map" ? (
          <>
        {suggestion ? (
          <aside className="suggestion">
            <div className="suggestion-head">
              <div>
                <p className="eyebrow">Suggestion</p>
                <h3>{suggestion.title}</h3>
                <small className="suggestion-status">{suggestion.status}</small>
              </div>
              <div className="suggestion-actions">
                <button disabled={suggestion.status !== "pending" || !canWrite} onClick={rejectSuggestion} type="button">
                  <X aria-hidden size={15} />
                  Reject
                </button>
                <button disabled={suggestion.status !== "pending" || !canWrite} onClick={applySuggestion} type="button">
                  <Check aria-hidden size={15} />
                  {suggestion.status === "applied" ? "Applied" : "Apply"}
                </button>
              </div>
            </div>
            {suggestionDiff ? (
              <div className="diff-panel">
                <div className="diff-meta">
                  <span>{suggestionDiff.mode}</span>
                  <span>/{suggestionDiff.slug}</span>
                </div>
                <div className="diff-lines">
                  {suggestionDiff.changes.length ? (
                    suggestionDiff.changes.slice(0, 80).map((change, index) => (
                      <p className={change.type === "added" ? "diff-added" : "diff-removed"} key={`${change.type}-${index}`}>
                        <span>{change.type === "added" ? "+" : "-"}</span>
                        {change.text || " "}
                      </p>
                    ))
                  ) : (
                    <p className="diff-empty">No line changes.</p>
                  )}
                </div>
              </div>
            ) : null}
            <MarkdownView compact markdown={suggestion.markdown} onOpenPage={setSelectedSlug} />
          </aside>
        ) : null}
        <GraphPanel
          graph={graph}
          graphMode={graphMode}
          graphNodeType={graphNodeType}
          graphStatus={graphStatus}
          graphError={graphError}
          selectedGraphNode={selectedGraphNode}
          canWrite={canWrite}
          onGraphModeChange={setGraphMode}
          onGraphNodeTypeChange={setGraphNodeType}
          onGraphStatusChange={setGraphStatus}
          onRebuildGraph={rebuildGraph}
          onOpenGraphNode={openGraphNode}
          onToggleGraphNodePin={toggleGraphNodePin}
        />
          </>
        ) : null}
        {activeWorkspace === "map" ? (
          page ? (
            <>
              <header className="page-header">
                <div>
                  <p className="eyebrow">/{page.slug}</p>
                  <h2>{page.title}</h2>
                </div>
                <div className="stats">
                  <span>{page.sections.length} sections</span>
                  <span>{page.links.length} links</span>
                  <span>{page.citations.length} refs</span>
                </div>
              </header>
              <section className="link-panel">
                <div>
                  <p className="eyebrow">Backlinks</p>
                  {backlinkSummary?.backlinks.length ? (
                    <div className="link-chips">
                      {backlinkSummary.backlinks.slice(0, 8).map((link, index) => (
                        <button key={`${link.source_slug}-${link.raw}-${index}`} onClick={() => setSelectedSlug(link.source_slug)} type="button">
                          <Link2 aria-hidden size={14} />
                          {link.source_title || link.source_slug}
                        </button>
                      ))}
                    </div>
                  ) : (
                    <p>No backlinks.</p>
                  )}
                </div>
                <div>
                  <p className="eyebrow">Unresolved</p>
                  {linkSummary?.unresolved.length ? (
                    <div className="link-chips unresolved">
                      {linkSummary.unresolved.slice(0, 8).map((link, index) => (
                        <button disabled={!canWrite} key={`${link.target}-${index}`} onClick={() => createPageFromLink(link.target)} type="button">
                          <CirclePlus aria-hidden size={14} />
                          {link.display || link.target}
                        </button>
                      ))}
                    </div>
                  ) : (
                    <p>No unresolved links.</p>
                  )}
                </div>
              </section>
              <MarkdownView citationSources={page.citation_sources || []} collapsible markdown={page.markdown} onOpenPage={setSelectedSlug} />
            </>
          ) : (
            <p className="empty">Loading page.</p>
          )
        ) : null}
          </>
        )}
      </section>
    </main>
  );
}
