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
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { GraphPanel, GraphData, GraphNode } from "../components/GraphPanel";
import { OperationsPanel } from "../components/OperationsPanel";

type PageSummary = {
  slug: string;
  title: string;
  path: string;
  links_count: number;
  citations_count: number;
};

type Page = {
  slug: string;
  title: string;
  markdown: string;
  links: Array<{ target: string; display?: string | null; status: string }>;
  citations: Array<{ key: string }>;
  citation_sources?: CitationSource[];
  sections: Array<{ heading: string; level: number; section_key: string }>;
};

type CitationSource = {
  key: string;
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
  status: string;
};

type CollaborationReviewDetail = {
  review: CollaborationReviewSummary & { meta?: string };
  findings: CollaborationFinding[];
};

const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "";
const sessionStorageKey = "knownet.session";
const vaultStorageKey = "knownet.vault";

function stripFrontmatter(markdown: string): string {
  if (!markdown.startsWith("---\n")) {
    return markdown;
  }
  const end = markdown.indexOf("\n---\n", 4);
  return end === -1 ? markdown : markdown.slice(end + 5).trimStart();
}

function pageSlug(target: string): string {
  return String(target).trim().toLowerCase().replace(/[^a-z0-9\uac00-\ud7a3_-]+/g, "-").replace(/^-+|-+$/g, "");
}

function pageIdFromSlug(slug: string): string {
  return `page_${slug.replace(/-/g, "_")}`;
}

function domId(value: string): string {
  return value.replace(/[^A-Za-z0-9_-]+/g, "-");
}

function prepareMarkdown(markdown: string, citationSources: CitationSource[] = []): string {
  const indexByKey = new Map(citationSources.map((source, index) => [source.key, String(index + 1)]));
  return stripFrontmatter(markdown)
    .split("\n")
    .filter((line) => !/^\s*\[\^[^\]]+\]:/.test(line))
    .map((line) =>
      line
        .replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_match, target, label) => {
          const text = label || target;
          return `[${text}](page:${encodeURIComponent(pageSlug(target))})`;
        })
        .replace(/\[\^([^\]]+)\]/g, (_match, key) => {
          const cleanKey = String(key).trim();
          const label = indexByKey.get(cleanKey) || cleanKey;
          return `[${label}](#citation-ref-${domId(cleanKey)})`;
        }),
    )
    .join("\n");
}

function citationPreview(source?: CitationSource): string {
  if (!source) {
    return "Citation source not loaded.";
  }
  return source.excerpt || source.definition || source.reason || source.key;
}

function isExternalHref(href: string): boolean {
  return /^https?:\/\//i.test(href);
}

function MarkdownView({
  markdown,
  citationSources = [],
  compact = false,
  collapsible = false,
  onOpenPage,
}: {
  markdown: string;
  citationSources?: CitationSource[];
  compact?: boolean;
  collapsible?: boolean;
  onOpenPage?: (slug: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [activeCitationKey, setActiveCitationKey] = useState<string | null>(null);
  const prepared = useMemo(() => prepareMarkdown(markdown, citationSources), [markdown, citationSources]);
  const citationByKey = useMemo(() => new Map(citationSources.map((source) => [source.key, source])), [citationSources]);
  const citationKeyByDomId = useMemo(
    () => new Map(citationSources.map((source) => [`citation-ref-${domId(source.key)}`, source.key])),
    [citationSources],
  );
  const activeCitation = activeCitationKey ? citationByKey.get(activeCitationKey) : undefined;
  const shouldCollapse = collapsible && (prepared.length > 2200 || /\n\|.+\|\n\|[-:|\s]+\|/.test(prepared));

  return (
    <>
      <article className={`${compact ? "markdown compact" : "markdown"} ${shouldCollapse && !expanded ? "is-collapsed" : ""}`}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            a: ({ href, children }) => {
              const target = href || "";
              if (target.startsWith("page:")) {
                const slug = decodeURIComponent(target.slice(5));
                return (
                  <button className="page-inline-link" onClick={() => onOpenPage?.(slug)} type="button">
                    {children}
                  </button>
                );
              }
              if (target.startsWith("#citation-ref-")) {
                const citationDomId = target.slice(1);
                const key = citationKeyByDomId.get(citationDomId) || citationDomId.replace(/^citation-ref-/, "");
                const source = citationByKey.get(key);
                return (
                  <sup className="citation-ref">
                    <button
                      aria-label={`Open citation ${key}`}
                      data-preview={citationPreview(source)}
                      onBlur={() => setActiveCitationKey(null)}
                      onClick={() => document.getElementById(`citation-${domId(key)}`)?.scrollIntoView({ behavior: "smooth", block: "start" })}
                      onFocus={() => setActiveCitationKey(key)}
                      onMouseEnter={() => setActiveCitationKey(key)}
                      onMouseLeave={() => setActiveCitationKey(null)}
                      title={citationPreview(source)}
                      type="button"
                    >
                      {children}
                    </button>
                  </sup>
                );
              }
              return (
                <a href={target} rel={isExternalHref(target) ? "noreferrer" : undefined} target={isExternalHref(target) ? "_blank" : undefined}>
                  {children}
                </a>
              );
            },
          }}
        >
          {prepared}
        </ReactMarkdown>
      </article>
      {shouldCollapse ? (
        <button className="markdown-toggle" onClick={() => setExpanded((value) => !value)} type="button">
          {expanded ? <ChevronsUp aria-hidden size={16} /> : <ChevronsDown aria-hidden size={16} />}
          {expanded ? "Collapse" : "Expand"}
        </button>
      ) : null}
      {activeCitation ? (
        <aside className="citation-hover-card" role="status">
          <strong>{activeCitation.key}</strong>
          <small>{activeCitation.status || "unchecked"}</small>
          <p>{citationPreview(activeCitation)}</p>
          {activeCitation.reason ? <small>{activeCitation.reason}</small> : null}
        </aside>
      ) : null}
      {!compact && citationSources.length ? (
        <section className="citation-references" aria-label="References">
          <p className="eyebrow">References</p>
          {citationSources.map((source, index) => (
            <div className="citation-reference" id={`citation-${domId(source.key)}`} key={source.key}>
              <span>{index + 1}</span>
              <div>
                <strong>{source.key}</strong>
                <small>{source.status || "unchecked"}</small>
                <p>{source.excerpt || source.definition || "No source excerpt available."}</p>
                {source.reason ? <small>{source.reason}</small> : null}
              </div>
            </div>
          ))}
        </section>
      ) : null}
    </>
  );
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
    throw new Error(body.detail?.message ?? body.error?.message ?? "Request failed");
  }
  return body.data as T;
}

export default function HomePage() {
  const [pages, setPages] = useState<PageSummary[]>([]);
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
  const [verifyIssues, setVerifyIssues] = useState(0);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [reviewMarkdown, setReviewMarkdown] = useState("");
  const [collaborationReviews, setCollaborationReviews] = useState<CollaborationReviewSummary[]>([]);
  const [selectedCollaborationReview, setSelectedCollaborationReview] = useState<CollaborationReviewDetail | null>(null);
  const [bundleStatus, setBundleStatus] = useState("");
  const [bundlePageIds, setBundlePageIds] = useState<string[]>([]);

  async function loadPages() {
    const data = await fetchJson<{ pages: PageSummary[] }>("/api/pages");
    setPages(data.pages);
    setBundlePageIds((current) => current.filter((pageId) => data.pages.some((item) => pageIdFromSlug(item.slug) === pageId)));
    if (!data.pages.some((item) => item.slug === selectedSlug) && data.pages[0]) {
      setSelectedSlug(data.pages[0].slug);
    }
  }

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
      return;
    }
    try {
      const snapshotData = await fetchJson<{ snapshots: SnapshotSummary[] }>("/api/maintenance/snapshots", {}, sessionToken, vaultId);
      setSnapshots(snapshotData.snapshots);
    } catch {
      setSnapshots([]);
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

  async function rebuildGraph() {
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
    }
  }

  async function createSnapshot() {
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
    }
  }

  async function runVerifyIndex() {
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
        <nav className="page-list" aria-label="Pages">
          {pages.map((item) => (
            <button
              className={item.slug === selectedSlug ? "page-link active" : "page-link"}
              key={item.slug}
              onClick={() => setSelectedSlug(item.slug)}
              type="button"
            >
              <span>
                <FileText aria-hidden size={15} />
                {item.title}
              </span>
              <small>
                {item.links_count} links / {item.citations_count} refs
              </small>
            </button>
          ))}
        </nav>
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
                placeholder="Password"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
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
        {citationAudits.length ? (
          <section className="review-panel citation-panel">
            <p className="eyebrow">Citations</p>
            {citationAudits.slice(0, 5).map((item) => (
              <div className="review-item" key={item.id}>
                <small>{item.status} / {item.verifier_type}</small>
                <strong>{item.citation_key}</strong>
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
        <section className="review-panel collaboration-panel">
          <p className="eyebrow">AI Reviews</p>
          <form className="collab-import" onSubmit={importCollaborationReview}>
            <textarea
              aria-label="Agent review Markdown"
              placeholder="Paste an agent_review Markdown document"
              value={reviewMarkdown}
              onChange={(event) => setReviewMarkdown(event.target.value)}
            />
            <button disabled={!canWrite || !reviewMarkdown.trim()} type="submit">
              <Save aria-hidden size={15} />
              Import review
            </button>
          </form>
          {collaborationReviews.slice(0, 5).map((item) => (
            <button className="review-open" key={item.id} onClick={() => loadCollaborationReview(item.id)} type="button">
              <span>{item.source_agent}</span>
              <strong>{item.title}</strong>
              <small>
                {item.pending_count}/{item.finding_count} pending
              </small>
            </button>
          ))}
          <div className="bundle-picker" aria-label="Context bundle pages">
            {pages.slice(0, 8).map((item) => {
              const pageId = pageIdFromSlug(item.slug);
              return (
                <label key={item.slug}>
                  <input checked={bundlePageIds.includes(pageId)} onChange={() => toggleBundlePage(item.slug)} type="checkbox" />
                  <span>{item.title}</span>
                </label>
              );
            })}
          </div>
          <button className="bundle-button" disabled={!(actor && ["owner", "admin"].includes(actor.role)) || (!selectedSlug && !bundlePageIds.length)} onClick={createContextBundleForCurrentPage} type="button">
            <FileText aria-hidden size={15} />
            {bundlePageIds.length ? `Bundle ${bundlePageIds.length} pages` : "Bundle current page"}
          </button>
          {bundleStatus ? <small>Last bundle: {bundleStatus}</small> : null}
        </section>
        {actor && ["owner", "admin"].includes(actor.role) ? (
          <OperationsPanel
            healthSummary={healthSummary}
            snapshots={snapshots}
            verifyIssues={verifyIssues}
            onCreateSnapshot={createSnapshot}
            onRunVerifyIndex={runVerifyIndex}
            onRebuildGraph={rebuildGraph}
          />
        ) : null}
      </aside>
      <section className="workspace">
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
        {selectedCollaborationReview ? (
          <aside className="collaboration-detail">
            <div>
              <p className="eyebrow">Review Inbox</p>
              <h2>{selectedCollaborationReview.review.title}</h2>
              <small>
                {selectedCollaborationReview.review.source_agent} / {selectedCollaborationReview.review.status}
              </small>
            </div>
            <div className="finding-grid">
              {selectedCollaborationReview.findings.map((finding) => (
                <article className={`finding-card ${finding.status}`} key={finding.id}>
                  <div>
                    <span>{finding.severity}</span>
                    <span>{finding.area}</span>
                    <span>{finding.status}</span>
                  </div>
                  <h3>{finding.title}</h3>
                  {finding.evidence ? <p>{finding.evidence}</p> : null}
                  {finding.proposed_change ? <p>{finding.proposed_change}</p> : null}
                  <footer>
                    <button onClick={() => decideCollaborationFinding(finding.id, "rejected")} type="button">
                      <X aria-hidden size={14} />
                      Reject
                    </button>
                    <button onClick={() => decideCollaborationFinding(finding.id, "deferred")} type="button">
                      <SquarePen aria-hidden size={14} />
                      Defer
                    </button>
                    <button onClick={() => decideCollaborationFinding(finding.id, "accepted")} type="button">
                      <Check aria-hidden size={14} />
                      Accept
                    </button>
                  </footer>
                </article>
              ))}
            </div>
          </aside>
        ) : null}
        {page ? (
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
        )}
      </section>
    </main>
  );
}
