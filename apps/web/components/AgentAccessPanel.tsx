"use client";

import { FormEvent, useEffect, useState } from "react";
import { Copy, KeyRound, RefreshCw, RotateCcw, Shield, X } from "lucide-react";
import { buildCreateAgentTokenPayload, sanitizeEventMeta } from "../lib/agentAccess";

type AgentToken = {
  id: string;
  label: string;
  agent_name: string;
  agent_model?: string | null;
  purpose: string;
  role: string;
  scopes: string[];
  expires_at?: string | null;
  revoked_at?: string | null;
  last_used_at?: string | null;
  max_pages_per_request: number;
  max_chars_per_request: number;
};

type AgentEvent = {
  id: number;
  action: string;
  status: string;
  target_type?: string | null;
  target_id?: string | null;
  meta?: Record<string, unknown>;
  created_at: string;
};

const presets = ["preset:reader", "preset:reviewer", "preset:contributor"];
const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "";

function tokenState(token: AgentToken): string {
  if (token.revoked_at) return "revoked";
  if (token.expires_at && new Date(token.expires_at).getTime() < Date.now()) return "expired";
  if (token.expires_at && new Date(token.expires_at).getTime() - Date.now() < 1000 * 60 * 60 * 24 * 3) return "expiring";
  return "active";
}

async function fetchJson<T>(path: string, init?: RequestInit, token?: string | null, vaultId?: string | null): Promise<T> {
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (vaultId) headers.set("x-knownet-vault", vaultId);
  const response = await fetch(`${apiBase}${path}`, { ...init, headers });
  const body = await response.json();
  if (!response.ok || !body.ok) throw new Error(body.detail?.message ?? "Request failed");
  return body.data as T;
}

export function AgentAccessPanel({ sessionToken, vaultId }: { sessionToken: string | null; vaultId: string }) {
  const [tokens, setTokens] = useState<AgentToken[]>([]);
  const [selected, setSelected] = useState<AgentToken | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [rawToken, setRawToken] = useState<string | null>(null);
  const [status, setStatus] = useState("");
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

  async function loadTokens() {
    try {
      const data = await fetchJson<{ tokens: AgentToken[] }>("/api/agents/tokens", {}, sessionToken, vaultId);
      setTokens(data.tokens);
      if (selected) setSelected(data.tokens.find((token) => token.id === selected.id) || null);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Agent token load failed");
    }
  }

  async function loadEvents(token: AgentToken) {
    setSelected(token);
    try {
      const data = await fetchJson<{ events: AgentEvent[] }>(`/api/agents/tokens/${token.id}/events`, {}, sessionToken, vaultId);
      setEvents(data.events);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Agent events load failed");
    }
  }

  useEffect(() => {
    loadTokens();
  }, [sessionToken, vaultId]);

  async function createToken(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
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
      setRawToken(data.token.raw_token);
      setStatus("Agent token created. Copy it now; it will not be shown again.");
      setForm({ ...form, label: "", agent_name: "", agent_model: "", purpose: "", scopes: "" });
      await loadTokens();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Agent token create failed");
    }
  }

  async function revokeToken(token: AgentToken) {
    await fetchJson(`/api/agents/tokens/${token.id}/revoke`, { method: "POST" }, sessionToken, vaultId);
    await loadTokens();
    if (selected?.id === token.id) await loadEvents(token);
  }

  async function rotateToken(token: AgentToken) {
    const data = await fetchJson<{ token: AgentToken & { raw_token: string } }>(`/api/agents/tokens/${token.id}/rotate`, { method: "POST" }, sessionToken, vaultId);
    setRawToken(data.token.raw_token);
    setStatus("Agent token rotated. Copy the new token now.");
    await loadTokens();
  }

  return (
    <section className="agent-panel">
      <div className="agent-panel-head">
        <div>
          <p className="eyebrow">Agent Access</p>
          <strong>Scoped AI agents</strong>
        </div>
        <button onClick={loadTokens} type="button">
          <RefreshCw aria-hidden size={14} />
          Refresh
        </button>
      </div>
      {rawToken ? (
        <div className="raw-token">
          <small>Shown once</small>
          <code>{rawToken}</code>
          <button onClick={() => navigator.clipboard?.writeText(rawToken)} type="button">
            <Copy aria-hidden size={14} />
            Copy
          </button>
          <button onClick={() => setRawToken(null)} type="button">
            <X aria-hidden size={14} />
            Dismiss
          </button>
        </div>
      ) : null}
      <form className="agent-create" onSubmit={createToken}>
        <input placeholder="Label" value={form.label} onChange={(event) => setForm({ ...form, label: event.target.value })} required />
        <input placeholder="Agent name" value={form.agent_name} onChange={(event) => setForm({ ...form, agent_name: event.target.value })} required />
        <input placeholder="Model" value={form.agent_model} onChange={(event) => setForm({ ...form, agent_model: event.target.value })} />
        <input placeholder="Purpose" value={form.purpose} onChange={(event) => setForm({ ...form, purpose: event.target.value })} required />
        <select value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value })}>
          <option value="agent_reader">reader</option>
          <option value="agent_reviewer">reviewer</option>
          <option value="agent_contributor">contributor</option>
        </select>
        <select value={form.scope_preset} onChange={(event) => setForm({ ...form, scope_preset: event.target.value })}>
          {presets.map((preset) => <option key={preset}>{preset}</option>)}
        </select>
        <input placeholder="Extra scopes, comma separated" value={form.scopes} onChange={(event) => setForm({ ...form, scopes: event.target.value })} />
        <input type="datetime-local" value={form.expires_at} onChange={(event) => setForm({ ...form, expires_at: event.target.value })} />
        <input type="number" value={form.max_pages_per_request} onChange={(event) => setForm({ ...form, max_pages_per_request: event.target.value })} />
        <input type="number" value={form.max_chars_per_request} onChange={(event) => setForm({ ...form, max_chars_per_request: event.target.value })} />
        <button type="submit">
          <KeyRound aria-hidden size={14} />
          Create
        </button>
      </form>
      <div className="agent-token-list">
        {tokens.map((token) => (
          <button className={selected?.id === token.id ? "selected" : ""} key={token.id} onClick={() => loadEvents(token)} type="button">
            <span className={`agent-chip ${tokenState(token)}`}>{tokenState(token)}</span>
            <strong>{token.label}</strong>
            <small>{token.agent_name} / {token.role}</small>
          </button>
        ))}
      </div>
      {selected ? (
        <div className="agent-detail">
          <div className="agent-detail-actions">
            <strong>{selected.label}</strong>
            <button onClick={() => revokeToken(selected)} type="button">
              <Shield aria-hidden size={14} />
              Revoke
            </button>
            <button onClick={() => rotateToken(selected)} type="button">
              <RotateCcw aria-hidden size={14} />
              Rotate
            </button>
          </div>
          <small>{selected.scopes.join(", ")}</small>
          <small>{selected.max_pages_per_request} pages / {selected.max_chars_per_request} chars</small>
          <div className="agent-events">
            {events.slice(0, 8).map((event) => (
              <div className={event.status === "denied" || event.status === "rate_limited" ? "agent-event warn" : "agent-event"} key={event.id}>
                <span>{event.status}</span>
                <strong>{event.action}</strong>
                <small>{event.created_at}</small>
                {Object.keys(sanitizeEventMeta(event.meta)).length ? <code>{JSON.stringify(sanitizeEventMeta(event.meta))}</code> : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}
      {status ? <small>{status}</small> : null}
    </section>
  );
}
