export type AgentTokenForm = {
  label: string;
  agent_name: string;
  agent_model: string;
  purpose: string;
  role: string;
  scope_preset: string;
  scopes: string;
  expires_at: string;
  max_pages_per_request: string;
  max_chars_per_request: string;
};

export type CreateAgentTokenPayload = {
  label: string;
  agent_name: string;
  agent_model: string | null;
  purpose: string;
  role: string;
  scopes: string[];
  expires_at: string | null;
  max_pages_per_request: number;
  max_chars_per_request: number;
};

export type AgentTokenSummary = {
  id: string;
  label: string;
  agent_name: string;
  agent_model?: string | null;
  purpose?: string | null;
  role: string;
  vault_id?: string | null;
  scopes: string[];
  expires_at?: string | null;
  revoked_at?: string | null;
  last_used_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  max_pages_per_request?: number;
  max_chars_per_request?: number;
};

export type AgentEventSummary = {
  id: number;
  action: string;
  status: string;
  target_type?: string | null;
  target_id?: string | null;
  request_id?: string | null;
  meta?: Record<string, unknown>;
  created_at: string;
};

export type AgentTokenFilters = {
  status: string;
  role: string;
  scope: string;
  search: string;
};

export type AgentEventFilter = "all" | "denied" | "rate_limited" | "errors" | "15m" | "1h" | "1d";

export type DashboardSummary = {
  active: number;
  expiring: number;
  revoked: number;
  denied: number;
  rateLimited: number;
};

const allowedRoles = new Set(["agent_reader", "agent_reviewer", "agent_contributor"]);
const allowedPresets = new Set(["preset:reader", "preset:reviewer", "preset:contributor"]);
const scopePattern = /^[a-z]+:[a-z_]+$/;
const expiringMs = 1000 * 60 * 60 * 24 * 7;
const unusedMs = 1000 * 60 * 60 * 24 * 30;
const unsafeMetaKeys = ["token", "secret", "password", "key", "authorization", "cookie", "session", "content", "body"];

function parseBoundedInt(value: string, min: number, max: number, label: string): number {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < min || parsed > max) {
    throw new Error(`${label} must be between ${min} and ${max}.`);
  }
  return parsed;
}

export function normalizeLocalExpiry(value: string): string | null {
  if (!value.trim()) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    throw new Error("Expiration must be a valid date and time.");
  }
  return date.toISOString().replace(/\.\d{3}Z$/, "Z");
}

export function buildCreateAgentTokenPayload(form: AgentTokenForm): CreateAgentTokenPayload {
  const label = form.label.trim();
  const agentName = form.agent_name.trim();
  const purpose = form.purpose.trim();
  if (!label || !agentName || !purpose) {
    throw new Error("Label, agent name, and purpose are required.");
  }
  if (!allowedRoles.has(form.role)) {
    throw new Error("Invalid agent role.");
  }
  if (!allowedPresets.has(form.scope_preset)) {
    throw new Error("Invalid scope preset.");
  }
  const explicitScopes = form.scopes
    .split(",")
    .map((scope) => scope.trim())
    .filter(Boolean);
  const invalidScope = explicitScopes.find((scope) => !scopePattern.test(scope) || scope.includes("*"));
  if (invalidScope) {
    throw new Error(`Invalid scope: ${invalidScope}`);
  }
  return {
    label,
    agent_name: agentName,
    agent_model: form.agent_model.trim() || null,
    purpose,
    role: form.role,
    scopes: [form.scope_preset, ...explicitScopes],
    expires_at: normalizeLocalExpiry(form.expires_at),
    max_pages_per_request: parseBoundedInt(form.max_pages_per_request, 1, 200, "Max pages"),
    max_chars_per_request: parseBoundedInt(form.max_chars_per_request, 1000, 500000, "Max chars"),
  };
}

export function sanitizeEventMeta(meta: Record<string, unknown> | undefined): Record<string, unknown> {
  const sanitized: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(meta ?? {})) {
    const lowered = key.toLowerCase();
    if (unsafeMetaKeys.some((unsafe) => lowered.includes(unsafe))) {
      continue;
    }
    sanitized[key] = value;
  }
  return sanitized;
}

export function agentDashboardAllowed(role: string | null | undefined): boolean {
  return role === "owner" || role === "admin";
}

export function tokenState(token: AgentTokenSummary, nowMs = Date.now()): "active" | "expiring" | "expired" | "revoked" {
  if (token.revoked_at) return "revoked";
  if (token.expires_at) {
    const expiresMs = Date.parse(token.expires_at);
    if (!Number.isNaN(expiresMs) && expiresMs < nowMs) return "expired";
    if (!Number.isNaN(expiresMs) && expiresMs - nowMs <= expiringMs) return "expiring";
  }
  return "active";
}

export function tokenSignals(token: AgentTokenSummary, events: AgentEventSummary[] = [], nowMs = Date.now()): string[] {
  const signals: string[] = [];
  const state = tokenState(token, nowMs);
  if (state === "revoked") signals.push("revoked");
  if (state === "expired") signals.push("expired");
  if (state === "expiring") signals.push("expires soon");
  if (!token.expires_at && !token.revoked_at) signals.push("no expiry");
  if (!token.scopes.length) signals.push("no scopes");
  const lastUsedMs = token.last_used_at ? Date.parse(token.last_used_at) : NaN;
  if (!token.revoked_at && (Number.isNaN(lastUsedMs) || nowMs - lastUsedMs > unusedMs)) signals.push("unused 30d");
  if (events.some((event) => event.status === "denied")) signals.push("recent denied");
  if (events.some((event) => event.status === "rate_limited")) signals.push("recent limited");
  return signals;
}

export function scopeTooltip(scopes: string[]): string {
  return scopes.length ? scopes.join(", ") : "No scopes";
}

export function filterAndSortTokens(tokens: AgentTokenSummary[], filters: AgentTokenFilters, nowMs = Date.now()): AgentTokenSummary[] {
  const query = filters.search.trim().toLowerCase();
  const scopeQuery = filters.scope.trim().toLowerCase();
  const order = { active: 0, expiring: 1, expired: 2, revoked: 3 };
  return tokens
    .filter((token) => filters.status === "all" || tokenState(token, nowMs) === filters.status)
    .filter((token) => filters.role === "all" || token.role === filters.role)
    .filter((token) => !scopeQuery || token.scopes.some((scope) => scope.toLowerCase().includes(scopeQuery)))
    .filter((token) => {
      if (!query) return true;
      return [token.label, token.agent_name, token.agent_model, token.purpose, token.id]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query));
    })
    .sort((left, right) => {
      const stateDelta = order[tokenState(left, nowMs)] - order[tokenState(right, nowMs)];
      if (stateDelta) return stateDelta;
      return (Date.parse(right.last_used_at || right.created_at || "") || 0) - (Date.parse(left.last_used_at || left.created_at || "") || 0);
    });
}

export function filterEvents(events: AgentEventSummary[], filter: AgentEventFilter, nowMs = Date.now()): AgentEventSummary[] {
  if (filter === "all") return events;
  if (filter === "denied") return events.filter((event) => event.status === "denied");
  if (filter === "rate_limited") return events.filter((event) => event.status === "rate_limited");
  if (filter === "errors") return events.filter((event) => event.status === "error" || event.status === "failed" || event.status === "invalid");
  const windowMs = filter === "15m" ? 15 * 60 * 1000 : filter === "1h" ? 60 * 60 * 1000 : 24 * 60 * 60 * 1000;
  return events.filter((event) => {
    const createdMs = Date.parse(event.created_at);
    return !Number.isNaN(createdMs) && nowMs - createdMs <= windowMs;
  });
}

export function calculateDashboardSummary(tokens: AgentTokenSummary[], events: AgentEventSummary[], nowMs = Date.now()): DashboardSummary {
  return {
    active: tokens.filter((token) => tokenState(token, nowMs) === "active").length,
    expiring: tokens.filter((token) => tokenState(token, nowMs) === "expiring").length,
    revoked: tokens.filter((token) => tokenState(token, nowMs) === "revoked").length,
    denied: events.filter((event) => event.status === "denied").length,
    rateLimited: events.filter((event) => event.status === "rate_limited").length,
  };
}

export function relativeTime(value: string | null | undefined, nowMs = Date.now()): string {
  if (!value) return "never";
  const thenMs = Date.parse(value);
  if (Number.isNaN(thenMs)) return "unknown";
  const future = thenMs > nowMs;
  const deltaSeconds = Math.floor(Math.abs(nowMs - thenMs) / 1000);
  const suffix = future ? "" : " ago";
  const prefix = future ? "in " : "";
  if (deltaSeconds < 60) return `${prefix}${deltaSeconds}s${suffix}`;
  const deltaMinutes = Math.floor(deltaSeconds / 60);
  if (deltaMinutes < 60) return `${prefix}${deltaMinutes}m${suffix}`;
  const deltaHours = Math.floor(deltaMinutes / 60);
  if (deltaHours < 24) return `${prefix}${deltaHours}h${suffix}`;
  return `${prefix}${Math.floor(deltaHours / 24)}d${suffix}`;
}

export function absoluteTimeTitle(value: string | null | undefined): string {
  if (!value) return "No timestamp";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${date.toLocaleString()} (${Intl.DateTimeFormat().resolvedOptions().timeZone})`;
}

export function createCopyFeedback(success: boolean): "copied" | "failed" {
  return success ? "copied" : "failed";
}

export function createConfirmation(action: "rotate" | "revoke", token: AgentTokenSummary): string {
  return `${action}:${token.id}`;
}

export function clearOneTimeRawTokenState(): null {
  return null;
}
