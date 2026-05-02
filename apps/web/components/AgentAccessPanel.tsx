"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  Clipboard,
  Copy,
  Filter,
  KeyRound,
  RefreshCw,
  RotateCcw,
  Search,
  Shield,
  X,
} from "lucide-react";
import {
  absoluteTimeTitle,
  agentDashboardAllowed,
  AgentEventFilter,
  AgentEventSummary,
  AgentTokenFilters,
  AgentTokenSummary,
  buildCreateAgentTokenPayload,
  calculateDashboardSummary,
  clearOneTimeRawTokenState,
  createConfirmation,
  createCopyFeedback,
  filterAndSortTokens,
  filterEvents,
  relativeTime,
  sanitizeEventMeta,
  scopeTooltip,
  tokenSignals,
  tokenState,
} from "../lib/agentAccess";

type AgentToken = AgentTokenSummary;

type AgentEvent = AgentEventSummary;

class ApiRequestError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

const presets = [
  { value: "preset:reader", label: "Reader", help: "pages, graph, and citation reads" },
  { value: "preset:reviewer", label: "Reviewer", help: "review and finding reads plus review submission" },
  { value: "preset:contributor", label: "Contributor", help: "review submission plus message creation" },
];
const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "";

async function fetchJson<T>(path: string, init?: RequestInit, token?: string | null, vaultId?: string | null): Promise<T> {
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (vaultId) headers.set("x-knownet-vault", vaultId);
  const response = await fetch(`${apiBase}${path}`, { ...init, headers });
  const body = await response.json().catch(() => ({}));
  if (!response.ok || !body.ok) {
    throw new ApiRequestError(body.detail?.message ?? "Request failed", response.status);
  }
  return body.data as T;
}

function formatTokenId(id: string): string {
  return id.length > 18 ? `${id.slice(0, 12)}...${id.slice(-4)}` : id;
}

function statusIcon(state: string) {
  if (state === "revoked" || state === "expired") return <AlertTriangle aria-hidden size={13} />;
  if (state === "expiring") return <AlertTriangle aria-hidden size={13} />;
  return <Check aria-hidden size={13} />;
}

export function AgentAccessPanel({ sessionToken, vaultId }: { sessionToken: string | null; vaultId: string }) {
  const [tokens, setTokens] = useState<AgentToken[]>([]);
  const [selected, setSelected] = useState<AgentToken | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [rawToken, setRawToken] = useState<{ value: string; kind: "created" | "rotated"; tokenId: string } | null>(null);
  const [copyFeedback, setCopyFeedback] = useState<"" | "copied" | "failed">("");
  const [status, setStatus] = useState("");
  const [listError, setListError] = useState("");
  const [eventError, setEventError] = useState("");
  const [loadingTokens, setLoadingTokens] = useState(true);
  const [loadingEvents, setLoadingEvents] = useState(false);
  const [accessDenied, setAccessDenied] = useState(false);
  const [actorRole, setActorRole] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [filters, setFilters] = useState<AgentTokenFilters>({ status: "all", role: "all", scope: "", search: "" });
  const [eventFilter, setEventFilter] = useState<AgentEventFilter>("all");
  const [form, setForm] = useState({
    label: "",
    agent_name: "",
    agent_model: "",
    purpose: "",
    role: "agent_reader",
    scope_preset: "preset:reader",
    scopes: "",
    expires_at: "",
    max_pages_per_request: "20",
    max_chars_per_request: "60000",
  });

  const visibleTokens = useMemo(() => filterAndSortTokens(tokens, filters), [tokens, filters]);
  const visibleEvents = useMemo(() => filterEvents(events, eventFilter), [events, eventFilter]);
  const summary = useMemo(() => calculateDashboardSummary(tokens, events), [tokens, events]);
  const selectedSignals = useMemo(() => (selected ? tokenSignals(selected, events) : []), [selected, events]);
  const selectedState = selected ? tokenState(selected) : null;
  const selectedPreset = presets.find((preset) => preset.value === form.scope_preset);

  async function loadTokens() {
    setLoadingTokens(true);
    setListError("");
    try {
      const data = await fetchJson<{ tokens: AgentToken[]; actor_role?: string }>("/api/agents/tokens", {}, sessionToken, vaultId);
      setActorRole(data.actor_role ?? null);
      setAccessDenied(!agentDashboardAllowed(data.actor_role));
      setTokens(data.tokens);
      if (selected) {
        setSelected(data.tokens.find((token) => token.id === selected.id) || null);
      } else if (data.tokens.length) {
        setSelected(data.tokens[0]);
      }
    } catch (error) {
      if (error instanceof ApiRequestError && (error.status === 401 || error.status === 403)) {
        setAccessDenied(true);
        setRawToken(clearOneTimeRawTokenState());
      }
      setListError(error instanceof Error ? error.message : "Agent token load failed");
    } finally {
      setLoadingTokens(false);
    }
  }

  async function loadEvents(token: AgentToken | null = selected) {
    if (!token) return;
    setSelected(token);
    setLoadingEvents(true);
    setEventError("");
    try {
      const data = await fetchJson<{ events: AgentEvent[] }>(`/api/agents/tokens/${token.id}/events`, {}, sessionToken, vaultId);
      setEvents(data.events);
    } catch (error) {
      if (error instanceof ApiRequestError && (error.status === 401 || error.status === 403)) {
        setAccessDenied(true);
        setRawToken(clearOneTimeRawTokenState());
      }
      setEventError(error instanceof Error ? error.message : "Agent events load failed");
    } finally {
      setLoadingEvents(false);
    }
  }

  useEffect(() => {
    loadTokens();
  }, [sessionToken, vaultId]);

  useEffect(() => {
    if (selected) loadEvents(selected);
  }, [selected?.id]);

  useEffect(() => {
    if (!copyFeedback) return;
    const timer = window.setTimeout(() => setCopyFeedback(""), 2000);
    return () => window.clearTimeout(timer);
  }, [copyFeedback]);

  async function copyText(value: string) {
    try {
      await navigator.clipboard?.writeText(value);
      setCopyFeedback(createCopyFeedback(true));
    } catch {
      setCopyFeedback(createCopyFeedback(false));
    }
  }

  async function createToken(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("");
    let payload;
    try {
      payload = buildCreateAgentTokenPayload(form);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Invalid agent token form");
      return;
    }
    try {
      const data = await fetchJson<{ token: AgentToken & { raw_token: string } }>(
        "/api/agents/tokens",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
        sessionToken,
        vaultId,
      );
      setRawToken({ value: data.token.raw_token, kind: "created", tokenId: data.token.id });
      setCopyFeedback("");
      setStatus("Agent token created. Copy it before dismissal.");
      setForm({ ...form, label: "", agent_name: "", agent_model: "", purpose: "", scopes: "" });
      await loadTokens();
    } catch (error) {
      setRawToken(clearOneTimeRawTokenState());
      setStatus(error instanceof Error ? error.message : "Agent token create failed");
    }
  }

  async function revokeToken(token: AgentToken) {
    try {
      await fetchJson(`/api/agents/tokens/${token.id}/revoke`, { method: "POST" }, sessionToken, vaultId);
      setConfirming(null);
      setStatus(`Revoked ${token.label}.`);
      await loadTokens();
      if (selected?.id === token.id) await loadEvents(token);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Agent token revoke failed");
    }
  }

  async function rotateToken(token: AgentToken) {
    try {
      const data = await fetchJson<{ token: AgentToken & { raw_token: string } }>(
        `/api/agents/tokens/${token.id}/rotate`,
        { method: "POST" },
        sessionToken,
        vaultId,
      );
      setConfirming(null);
      setRawToken({ value: data.token.raw_token, kind: "rotated", tokenId: data.token.id });
      setCopyFeedback("");
      setStatus("Agent token rotated. The old token is revoked; copy the new one now.");
      await loadTokens();
    } catch (error) {
      setRawToken(clearOneTimeRawTokenState());
      setStatus(error instanceof Error ? error.message : "Agent token rotate failed");
    }
  }

  if (loadingTokens && actorRole === null && !tokens.length && !listError) {
    return (
      <section className="agent-panel">
        <div className="agent-panel-head">
          <div>
            <p className="eyebrow">Agent Access</p>
            <strong>Loading operator dashboard</strong>
          </div>
          <RefreshCw aria-hidden size={18} />
        </div>
        <p className="agent-muted">Checking permissions and token inventory...</p>
      </section>
    );
  }

  if (accessDenied) {
    return (
      <section className="agent-panel">
        <div className="agent-panel-head">
          <div>
            <p className="eyebrow">Agent Access</p>
            <strong>Owner/admin access required</strong>
          </div>
          <Shield aria-hidden size={18} />
        </div>
        <p className="agent-muted">This dashboard manages external agent tokens and is hidden from non-operator roles.</p>
        {listError ? <p className="agent-error">{listError}</p> : null}
      </section>
    );
  }

  return (
    <section className="agent-panel">
      <div className="agent-panel-head">
        <div>
          <p className="eyebrow">Agent Access</p>
          <strong>External AI agent operations</strong>
          <small>{actorRole ? `Signed in as ${actorRole}` : "Owner/admin dashboard"}</small>
        </div>
        <button aria-label="Refresh agent token dashboard" onClick={loadTokens} type="button">
          <RefreshCw aria-hidden size={14} />
          Refresh
        </button>
      </div>

      <div className="agent-summary" aria-label="Agent token summary">
        <span><strong>{summary.active}</strong> active</span>
        <span><strong>{summary.expiring}</strong> expiring</span>
        <span><strong>{summary.revoked}</strong> revoked</span>
        <span><strong>{summary.denied}</strong> denied</span>
        <span><strong>{summary.rateLimited}</strong> limited</span>
      </div>

      {rawToken ? (
        <div className="raw-token" role="status">
          <div>
            <strong>Raw token shown once</strong>
            <small>
              This token cannot be viewed again after dismissal. Store it in the target MCP/SDK environment before closing this panel.
            </small>
          </div>
          <code>{rawToken.value}</code>
          <div className="raw-token-actions">
            <button aria-label="Copy one-time raw agent token" onClick={() => copyText(rawToken.value)} type="button">
              <Copy aria-hidden size={14} />
              Copy
            </button>
            <button aria-label="Dismiss one-time raw agent token" onClick={() => setRawToken(clearOneTimeRawTokenState())} type="button">
              <X aria-hidden size={14} />
              Dismiss
            </button>
          </div>
          {copyFeedback === "copied" ? <small className="agent-ok">Copied</small> : null}
          {copyFeedback === "failed" ? <small className="agent-error">Copy failed; select the token manually.</small> : null}
          <small>
            New token id: <code>{rawToken.tokenId}</code>. Setup: <a href="/docs/MCP_CLIENTS.md">MCP</a> /{" "}
            <a href="/docs/SDK_CLIENTS.md">SDK</a>
          </small>
        </div>
      ) : null}

      <form className="agent-create" onSubmit={createToken}>
        <div className="agent-form-grid">
          <input placeholder="Label" value={form.label} onChange={(event) => setForm({ ...form, label: event.target.value })} required />
          <input placeholder="Agent name" value={form.agent_name} onChange={(event) => setForm({ ...form, agent_name: event.target.value })} required />
          <input placeholder="Model" value={form.agent_model} onChange={(event) => setForm({ ...form, agent_model: event.target.value })} />
          <input placeholder="Purpose" value={form.purpose} onChange={(event) => setForm({ ...form, purpose: event.target.value })} required />
          <select aria-label="Agent role" value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value })}>
            <option value="agent_reader">reader</option>
            <option value="agent_reviewer">reviewer</option>
            <option value="agent_contributor">contributor</option>
          </select>
          <select aria-label="Scope preset" value={form.scope_preset} onChange={(event) => setForm({ ...form, scope_preset: event.target.value })}>
            {presets.map((preset) => <option key={preset.value} value={preset.value}>{preset.label}</option>)}
          </select>
          <input placeholder="Extra scopes, comma separated" value={form.scopes} onChange={(event) => setForm({ ...form, scopes: event.target.value })} />
          <input aria-label="Expiration" type="datetime-local" value={form.expires_at} onChange={(event) => setForm({ ...form, expires_at: event.target.value })} />
          <input aria-label="Maximum pages per request" type="number" value={form.max_pages_per_request} onChange={(event) => setForm({ ...form, max_pages_per_request: event.target.value })} />
          <input aria-label="Maximum characters per request" type="number" value={form.max_chars_per_request} onChange={(event) => setForm({ ...form, max_chars_per_request: event.target.value })} />
        </div>
        <small>{selectedPreset?.label}: {selectedPreset?.help}</small>
        <button type="submit">
          <KeyRound aria-hidden size={14} />
          Create token
        </button>
      </form>

      <div className="agent-filters">
        <label>
          <Filter aria-hidden size={14} />
          <select value={filters.status} onChange={(event) => setFilters({ ...filters, status: event.target.value })}>
            <option value="all">all status</option>
            <option value="active">active</option>
            <option value="expiring">expiring</option>
            <option value="expired">expired</option>
            <option value="revoked">revoked</option>
          </select>
        </label>
        <label>
          <Shield aria-hidden size={14} />
          <select value={filters.role} onChange={(event) => setFilters({ ...filters, role: event.target.value })}>
            <option value="all">all roles</option>
            <option value="agent_reader">reader</option>
            <option value="agent_reviewer">reviewer</option>
            <option value="agent_contributor">contributor</option>
          </select>
        </label>
        <label>
          <Search aria-hidden size={14} />
          <input placeholder="agent, label, id" value={filters.search} onChange={(event) => setFilters({ ...filters, search: event.target.value })} />
        </label>
        <input placeholder="scope filter" value={filters.scope} onChange={(event) => setFilters({ ...filters, scope: event.target.value })} />
      </div>

      {loadingTokens && !tokens.length ? <p className="agent-muted">Loading token list...</p> : null}
      {listError ? <p className="agent-error">{listError} <button onClick={loadTokens} type="button">Retry</button></p> : null}

      <div className="agent-dashboard-grid">
        <div className="agent-token-list" aria-label="Agent token list">
          {!loadingTokens && !tokens.length ? <p className="agent-muted">No agent tokens yet.</p> : null}
          {tokens.length > 0 && !visibleTokens.length ? <p className="agent-muted">No tokens match the current filters.</p> : null}
          {visibleTokens.map((token) => {
            const state = tokenState(token);
            const signals = tokenSignals(token, selected?.id === token.id ? events : []);
            return (
              <button
                className={selected?.id === token.id ? "selected" : ""}
                key={token.id}
                onClick={() => setSelected(token)}
                type="button"
              >
                <span className={`agent-chip ${state}`}>{statusIcon(state)}{state}</span>
                <strong>{token.label}</strong>
                <small>{token.agent_name} / {token.agent_model || "model unset"}</small>
                <small>{token.role} · <span title={scopeTooltip(token.scopes)}>{token.scopes.length} scopes</span></small>
                <small title={absoluteTimeTitle(token.expires_at)}>expires {token.expires_at ? relativeTime(token.expires_at) : "not set"}</small>
                {signals.length ? <small className="agent-signal-line">{signals.slice(0, 3).join(" · ")}</small> : null}
              </button>
            );
          })}
        </div>

        {selected ? (
          <div className="agent-detail">
            <div className="agent-detail-actions">
              <div>
                <strong>{selected.label}</strong>
                <small>Token ID: <code>{formatTokenId(selected.id)}</code></small>
              </div>
              <button aria-label="Copy safe token id" onClick={() => copyText(selected.id)} type="button">
                <Clipboard aria-hidden size={14} />
                Copy ID
              </button>
            </div>

            <div className="agent-detail-grid">
              <small>Agent: <strong>{selected.agent_name}</strong></small>
              <small>Model: <strong>{selected.agent_model || "unset"}</strong></small>
              <small>Role: <strong>{selected.role}</strong></small>
              <small>Vault: <strong>{selected.vault_id || vaultId}</strong></small>
              <small title={absoluteTimeTitle(selected.expires_at)}>Expires: <strong>{selected.expires_at || "not set"}</strong></small>
              <small title={absoluteTimeTitle(selected.last_used_at)}>Last used: <strong>{selected.last_used_at ? relativeTime(selected.last_used_at) : "never"}</strong></small>
              <small title={absoluteTimeTitle(selected.created_at)}>Created: <strong>{selected.created_at || "unknown"}</strong></small>
              <small title={absoluteTimeTitle(selected.updated_at)}>Updated: <strong>{selected.updated_at || "unknown"}</strong></small>
              <small>Limits: <strong>{selected.max_pages_per_request ?? "-"} pages / {selected.max_chars_per_request ?? "-"} chars</strong></small>
              <small>Purpose: <strong>{selected.purpose || "unset"}</strong></small>
            </div>

            <div className="agent-scope-box" title={scopeTooltip(selected.scopes)}>
              {selected.scopes.length ? selected.scopes.map((scope) => <span key={scope}>{scope}</span>) : <span>No scopes</span>}
            </div>

            <div className="agent-warnings">
              <span className={`agent-chip ${selectedState || ""}`}>{selectedState ? statusIcon(selectedState) : null}{selectedState}</span>
              {selectedSignals.map((signal) => <span className="agent-chip warn" key={signal}><AlertTriangle aria-hidden size={13} />{signal}</span>)}
            </div>

            <div className="agent-detail-actions">
              {confirming === createConfirmation("rotate", selected) ? (
                <>
                  <small>Rotate {selected.label} ({formatTokenId(selected.id)})?</small>
                  <button onClick={() => rotateToken(selected)} type="button">Confirm rotate</button>
                  <button onClick={() => setConfirming(null)} type="button">Cancel</button>
                </>
              ) : (
                <button disabled={!!selected.revoked_at} onClick={() => setConfirming(createConfirmation("rotate", selected))} type="button">
                  <RotateCcw aria-hidden size={14} />
                  Rotate
                </button>
              )}
              {confirming === createConfirmation("revoke", selected) ? (
                <>
                  <small>Revoke {selected.label} ({formatTokenId(selected.id)})?</small>
                  <button onClick={() => revokeToken(selected)} type="button">Confirm revoke</button>
                  <button onClick={() => setConfirming(null)} type="button">Cancel</button>
                </>
              ) : (
                <button disabled={!!selected.revoked_at} onClick={() => setConfirming(createConfirmation("revoke", selected))} type="button">
                  <Shield aria-hidden size={14} />
                  Revoke
                </button>
              )}
              <button onClick={() => loadEvents(selected)} type="button">
                <RefreshCw aria-hidden size={14} />
                Events
              </button>
            </div>

            <div className="agent-event-toolbar">
              <select aria-label="Event filter" value={eventFilter} onChange={(event) => setEventFilter(event.target.value as AgentEventFilter)}>
                <option value="all">all events</option>
                <option value="denied">denied</option>
                <option value="rate_limited">rate limited</option>
                <option value="errors">errors</option>
                <option value="15m">last 15m</option>
                <option value="1h">last hour</option>
                <option value="1d">last day</option>
              </select>
            </div>

            {loadingEvents ? <p className="agent-muted">Loading events...</p> : null}
            {eventError ? <p className="agent-error">{eventError}</p> : null}
            <div className="agent-events">
              {!loadingEvents && !visibleEvents.length ? <p className="agent-muted">No events for this token/filter.</p> : null}
              {visibleEvents.slice(0, 12).map((event) => {
                const meta = sanitizeEventMeta(event.meta);
                const warn = event.status === "denied" || event.status === "rate_limited" || event.status === "error" || event.status === "failed";
                return (
                  <div className={warn ? "agent-event warn" : "agent-event"} key={event.id}>
                    <span>{warn ? <AlertTriangle aria-hidden size={13} /> : <Check aria-hidden size={13} />}{event.status}</span>
                    <strong>{event.action}</strong>
                    <small title={absoluteTimeTitle(event.created_at)}>{relativeTime(event.created_at)}</small>
                    {event.request_id ? <small>request: <code>{event.request_id}</code></small> : null}
                    {event.target_type || event.target_id ? <small>{event.target_type || "target"}: {event.target_id || "unknown"}</small> : null}
                    {Object.keys(meta).length ? <code>{JSON.stringify(meta)}</code> : null}
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="agent-detail">
            <p className="agent-muted">Select a token to inspect details, rotate, revoke, or review events.</p>
          </div>
        )}
      </div>

      {status ? <p className={status.toLowerCase().includes("failed") || status.toLowerCase().includes("invalid") ? "agent-error" : "agent-muted"}>{status}</p> : null}
    </section>
  );
}
