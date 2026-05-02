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

const allowedRoles = new Set(["agent_reader", "agent_reviewer", "agent_contributor"]);
const allowedPresets = new Set(["preset:reader", "preset:reviewer", "preset:contributor"]);
const scopePattern = /^[a-z]+:[a-z_]+$/;

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
    if (lowered.includes("token") || lowered.includes("secret") || lowered.includes("password") || lowered.includes("key")) {
      continue;
    }
    sanitized[key] = value;
  }
  return sanitized;
}
