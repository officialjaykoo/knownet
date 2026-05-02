import assert from "node:assert/strict";
import test from "node:test";

import {
  absoluteTimeTitle,
  agentDashboardAllowed,
  buildCreateAgentTokenPayload,
  calculateDashboardSummary,
  clearOneTimeRawTokenState,
  createConfirmation,
  createCopyFeedback,
  filterAndSortTokens,
  filterEvents,
  normalizeLocalExpiry,
  relativeTime,
  sanitizeEventMeta,
  scopeTooltip,
  tokenSignals,
  tokenState,
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
  assert.deepEqual(
    sanitizeEventMeta({
      token: "x",
      API_KEY: "y",
      authorization: "bearer",
      cookie: "session",
      request_body: "raw",
      reason: "scope",
    }),
    { reason: "scope" },
  );
});

const now = Date.parse("2026-05-02T00:00:00Z");
const tokens = [
  {
    id: "agent_a",
    label: "Active reviewer",
    agent_name: "Claude",
    agent_model: "review-model",
    purpose: "phase review",
    role: "agent_reviewer",
    scopes: ["reviews:read", "reviews:create"],
    expires_at: "2026-06-01T00:00:00Z",
    last_used_at: "2026-05-01T00:00:00Z",
    created_at: "2026-04-01T00:00:00Z",
  },
  {
    id: "agent_b",
    label: "Expiring reader",
    agent_name: "Gemini",
    role: "agent_reader",
    scopes: ["pages:read"],
    expires_at: "2026-05-04T00:00:00Z",
    last_used_at: null,
    created_at: "2026-04-02T00:00:00Z",
  },
  {
    id: "agent_c",
    label: "Revoked contributor",
    agent_name: "Codex",
    role: "agent_contributor",
    scopes: ["messages:create"],
    expires_at: null,
    revoked_at: "2026-04-20T00:00:00Z",
    created_at: "2026-04-03T00:00:00Z",
  },
];

const events = [
  { id: 1, action: "pages.read", status: "allowed", created_at: "2026-05-01T23:59:30Z" },
  { id: 2, action: "reviews.read", status: "denied", created_at: "2026-05-01T23:50:00Z" },
  { id: 3, action: "pages.read", status: "rate_limited", created_at: "2026-05-01T22:00:00Z" },
];

test("agentDashboardAllowed gates operator roles", () => {
  assert.equal(agentDashboardAllowed("owner"), true);
  assert.equal(agentDashboardAllowed("admin"), true);
  assert.equal(agentDashboardAllowed("editor"), false);
  assert.equal(agentDashboardAllowed(null), false);
});

test("tokenState and tokenSignals expose expiry and health", () => {
  assert.equal(tokenState(tokens[0], now), "active");
  assert.equal(tokenState(tokens[1], now), "expiring");
  assert.equal(tokenState(tokens[2], now), "revoked");
  assert.deepEqual(tokenSignals({ ...tokens[1], scopes: [] }, events, now), [
    "expires soon",
    "no scopes",
    "unused 30d",
    "recent denied",
    "recent limited",
  ]);
});

test("filterAndSortTokens filters status, role, scopes, and search", () => {
  assert.deepEqual(filterAndSortTokens(tokens, { status: "expiring", role: "all", scope: "", search: "" }, now).map((token) => token.id), ["agent_b"]);
  assert.deepEqual(filterAndSortTokens(tokens, { status: "all", role: "agent_reviewer", scope: "", search: "" }, now).map((token) => token.id), ["agent_a"]);
  assert.deepEqual(filterAndSortTokens(tokens, { status: "all", role: "all", scope: "messages", search: "" }, now).map((token) => token.id), ["agent_c"]);
  assert.deepEqual(filterAndSortTokens(tokens, { status: "all", role: "all", scope: "", search: "gemini" }, now).map((token) => token.id), ["agent_b"]);
});

test("filterEvents supports failure and time windows", () => {
  assert.deepEqual(filterEvents(events, "denied", now).map((event) => event.id), [2]);
  assert.deepEqual(filterEvents(events, "rate_limited", now).map((event) => event.id), [3]);
  assert.deepEqual(filterEvents(events, "15m", now).map((event) => event.id), [1, 2]);
});

test("calculateDashboardSummary counts token and event health", () => {
  assert.deepEqual(calculateDashboardSummary(tokens, events, now), {
    active: 1,
    expiring: 1,
    revoked: 1,
    denied: 1,
    rateLimited: 1,
  });
});

test("time and scope helpers produce operator-safe strings", () => {
  assert.equal(relativeTime("2026-05-01T23:59:30Z", now), "30s ago");
  assert.match(absoluteTimeTitle("2026-05-01T23:59:30Z"), /2026|5|May/);
  assert.equal(scopeTooltip(["pages:read", "graph:read"]), "pages:read, graph:read");
});

test("raw token state and UI helpers avoid persistence assumptions", () => {
  globalThis.localStorage?.setItem?.("safe", "value");
  assert.equal(clearOneTimeRawTokenState(), null);
  assert.equal(globalThis.localStorage?.getItem?.("rawToken") ?? null, null);
  assert.equal(createCopyFeedback(true), "copied");
  assert.equal(createCopyFeedback(false), "failed");
  assert.equal(createConfirmation("rotate", tokens[0]), "rotate:agent_a");
});
