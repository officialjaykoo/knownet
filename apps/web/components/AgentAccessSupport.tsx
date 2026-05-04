"use client";

import { FormEvent } from "react";
import { AlertTriangle, Check, Copy, Filter, KeyRound, RefreshCw, Search, Shield, X } from "lucide-react";
import {
  AgentTokenFilters,
  clearOneTimeRawTokenState,
  scopeTooltip,
} from "../lib/agentAccess";

export const agentTokenPresets = [
  { value: "preset:reader", label: "Reader", help: "pages, graph, and citation reads" },
  { value: "preset:reviewer", label: "Reviewer", help: "review and finding reads plus review submission" },
  { value: "preset:contributor", label: "Contributor", help: "review submission plus message creation" },
];

export function formatTokenId(id: string): string {
  return id.length > 18 ? `${id.slice(0, 12)}...${id.slice(-4)}` : id;
}

export function statusIcon(state: string) {
  if (state === "revoked" || state === "expired") return <AlertTriangle aria-hidden size={13} />;
  if (state === "expiring") return <AlertTriangle aria-hidden size={13} />;
  return <Check aria-hidden size={13} />;
}

export function AgentAccessLoading() {
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

export function AgentAccessDenied({ listError }: { listError: string }) {
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

export function AgentAccessSummary({ summary }: { summary: { active: number; expiring: number; revoked: number; denied: number; rateLimited: number } }) {
  return (
    <div className="agent-summary" aria-label="Agent token summary">
      <span><strong>{summary.active}</strong> active</span>
      <span><strong>{summary.expiring}</strong> expiring</span>
      <span><strong>{summary.revoked}</strong> revoked</span>
      <span><strong>{summary.denied}</strong> denied</span>
      <span><strong>{summary.rateLimited}</strong> limited</span>
    </div>
  );
}

export function RawAgentTokenNotice({
  rawToken,
  copyFeedback,
  copyText,
  dismiss,
}: {
  rawToken: { value: string; kind: "created" | "rotated"; tokenId: string };
  copyFeedback: "" | "copied" | "failed";
  copyText: (value: string) => void;
  dismiss: () => void;
}) {
  return (
    <div className="raw-token" role="status">
      <div>
        <strong>Raw token shown once</strong>
        <small>This token cannot be viewed again after dismissal. Store it in the target MCP/SDK environment before closing this panel.</small>
      </div>
      <code>{rawToken.value}</code>
      <div className="raw-token-actions">
        <button aria-label="Copy one-time raw agent token" onClick={() => copyText(rawToken.value)} type="button">
          <Copy aria-hidden size={14} />
          Copy
        </button>
        <button aria-label="Dismiss one-time raw agent token" onClick={dismiss} type="button">
          <X aria-hidden size={14} />
          Dismiss
        </button>
      </div>
      {copyFeedback === "copied" ? <small className="agent-ok">Copied</small> : null}
      {copyFeedback === "failed" ? <small className="agent-error">Copy failed; select the token manually.</small> : null}
      <small>
        New token id: <code>{rawToken.tokenId}</code>. Setup: <a href="/docs/MCP_CLIENTS.md">MCP</a> / <a href="/docs/SDK_CLIENTS.md">SDK</a>
      </small>
    </div>
  );
}

export function AgentTokenCreateForm({
  form,
  setForm,
  onSubmit,
}: {
  form: any;
  setForm: (value: any) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const selectedPreset = agentTokenPresets.find((preset) => preset.value === form.scope_preset);
  return (
    <form className="agent-create" onSubmit={onSubmit}>
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
          {agentTokenPresets.map((preset) => <option key={preset.value} value={preset.value}>{preset.label}</option>)}
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
  );
}

export function AgentTokenFiltersBar({
  filters,
  setFilters,
}: {
  filters: AgentTokenFilters;
  setFilters: (filters: AgentTokenFilters) => void;
}) {
  return (
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
  );
}

export { clearOneTimeRawTokenState, scopeTooltip };
