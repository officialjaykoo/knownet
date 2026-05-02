import assert from "node:assert/strict";
import test from "node:test";

import {
  buildCreateAgentTokenPayload,
  normalizeLocalExpiry,
  sanitizeEventMeta,
} from "../lib/agentAccess.ts";

const baseForm = {
  label: " External reviewer ",
  agent_name: " claude ",
  agent_model: " test-model ",
  purpose: " phase review ",
  role: "agent_reviewer",
  scope_preset: "preset:reviewer",
  scopes: "pages:read, graph:read",
  expires_at: "",
  max_pages_per_request: "20",
  max_chars_per_request: "60000",
};

test("buildCreateAgentTokenPayload trims values and validates scopes", () => {
  const payload = buildCreateAgentTokenPayload(baseForm);
  assert.equal(payload.label, "External reviewer");
  assert.equal(payload.agent_name, "claude");
  assert.deepEqual(payload.scopes, ["preset:reviewer", "pages:read", "graph:read"]);
  assert.equal(payload.expires_at, null);
});

test("buildCreateAgentTokenPayload rejects unsafe scopes and invalid limits", () => {
  assert.throws(() => buildCreateAgentTokenPayload({ ...baseForm, scopes: "pages:*" }), /Invalid scope/);
  assert.throws(() => buildCreateAgentTokenPayload({ ...baseForm, max_pages_per_request: "999" }), /Max pages/);
});

test("normalizeLocalExpiry returns API-safe ISO UTC strings", () => {
  assert.match(normalizeLocalExpiry("2099-01-01T09:30") ?? "", /^2099-01-01T\d\d:30:00Z$/);
});

test("sanitizeEventMeta removes secret-looking keys", () => {
  assert.deepEqual(sanitizeEventMeta({ token: "x", API_KEY: "y", reason: "scope" }), { reason: "scope" });
});
