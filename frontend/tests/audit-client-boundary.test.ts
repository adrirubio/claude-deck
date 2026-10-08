import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchAuditEvents, fetchMetricsWindow } from "@/features/factory/auditApi";
import { ApiHttpError } from "@/lib/api";

const realFetch = globalThis.fetch;

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("audit browser clients at the HTTP boundary", () => {
  afterEach(() => {
    globalThis.fetch = realFetch;
    vi.restoreAllMocks();
  });

  it("requests the exact factory URLs with the operator header only on audit reads", async () => {
    const calls: Array<{ url: string; headers: HeadersInit | undefined }> = [];
    globalThis.fetch = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(url), headers: init?.headers });
      if (String(url).includes("audit-events")) {
        return jsonResponse({ items: [], total: 0, page: 1, page_size: 25, snapshot_labels: [] });
      }
      return jsonResponse({
        window_start: "s", window_end: "e", filter_scope: "all",
        counting_unit_note: "n", missing_intervals: [], metrics: [],
      });
    }) as unknown as typeof fetch;

    await fetchMetricsWindow({ windowStart: "s", windowEnd: "e" });
    await fetchAuditEvents({ operatorToken: "synthetic-operator", page: 1, pageSize: 25 });

    expect(calls[0].url).toContain("/factory/metrics?");
    expect(calls[0].url).not.toContain("/api/v1//");
    expect(calls[0].url).toContain("/api/v1/factory/metrics?");
    const metricHeaders = calls[0].headers as Record<string, string>;
    expect(metricHeaders["X-Deck-Operator-Token"]).toBeUndefined();

    expect(calls[1].url).toContain("/factory/audit-events?");
    expect(calls[1].url).not.toContain("/api/v1//");
    const auditHeaders = calls[1].headers as Record<string, string>;
    expect(auditHeaders["X-Deck-Operator-Token"]).toBe("synthetic-operator");
  });

  it("keeps safe metrics usable after a refused audit read", async () => {
    globalThis.fetch = vi.fn(async (url: RequestInfo | URL) => {
      if (String(url).includes("audit-events")) {
        return jsonResponse({ detail: "operator_token_invalid" }, 401);
      }
      return jsonResponse({
        window_start: "s", window_end: "e", filter_scope: "all",
        counting_unit_note: "n", missing_intervals: [],
        metrics: [{ name: "cost", counting_unit: "usage_attribution", value: null,
                    sample_count: 0, unknown_count: 1, excluded_count: 0,
                    unknown_reasons: ["no measured usage attribution"],
                    source: "factory_audit_events", coverage: "unknown" }],
      });
    }) as unknown as typeof fetch;

    const metrics = await fetchMetricsWindow({ windowStart: "s", windowEnd: "e" });
    expect(metrics.metrics[0].value).toBeNull();
    // C14: the exact refusal status and operator message reach the caller.
    const refusal = await fetchAuditEvents({ operatorToken: "bad", page: 1, pageSize: 25 })
      .then(() => null, (error: unknown) => error);
    expect(refusal).toBeInstanceOf(ApiHttpError);
    expect((refusal as ApiHttpError).status).toBe(401);
    expect((refusal as ApiHttpError).message).toBe(
      "The Deck operator token was rejected. Clear it and enter a valid token.");
  });

  it("surfaces the exact unconfigured-operator 503 refusal", async () => {
    globalThis.fetch = vi.fn(async () => jsonResponse(
      { detail: "operator_token_unconfigured" }, 503)) as unknown as typeof fetch;

    const refusal = await fetchAuditEvents({ operatorToken: "synthetic-operator" })
      .then(() => null, (error: unknown) => error);
    expect((refusal as ApiHttpError).status).toBe(503);
    expect((refusal as ApiHttpError).message).toBe(
      "The Deck operator token is not configured on the backend.");
  });

  // C13: both reads carry the same supported history filters.
  it("sends matching team and scope context filters on both reads", async () => {
    const calls: string[] = [];
    globalThis.fetch = vi.fn(async (url: RequestInfo | URL) => {
      calls.push(String(url));
      if (String(url).includes("audit-events")) {
        return jsonResponse({ items: [], total: 0, page: 1, page_size: 25, snapshot_labels: [] });
      }
      return jsonResponse({
        window_start: "s", window_end: "e", filter_scope: "all",
        counting_unit_note: "n", missing_intervals: [], metrics: [],
      });
    }) as unknown as typeof fetch;

    await fetchMetricsWindow({
      windowStart: "s", windowEnd: "e",
      teamContextKey: "team:9:z", scopeContextKey: "scope:7:y",
    });
    await fetchAuditEvents({
      operatorToken: "synthetic-operator", page: 1, pageSize: 25,
      teamContextKey: "team:9:z", scopeContextKey: "scope:7:y",
    });

    expect(calls[0]).toContain("team_context_key=team%3A9%3Az");
    expect(calls[0]).toContain("scope_context_key=scope%3A7%3Ay");
    expect(calls[1]).toContain("team_context_key=team%3A9%3Az");
    expect(calls[1]).toContain("scope_context_key=scope%3A7%3Ay");
  });

  // C13: audit reads carry pagination parameters.
  it("sends pagination parameters on audit reads", async () => {
    const calls: string[] = [];
    globalThis.fetch = vi.fn(async (url: RequestInfo | URL) => {
      calls.push(String(url));
      return jsonResponse({ items: [], total: 30, page: 2, page_size: 25, snapshot_labels: [] });
    }) as unknown as typeof fetch;

    await fetchAuditEvents({ operatorToken: "synthetic-operator", page: 2, pageSize: 25 });
    expect(calls[0]).toContain("page=2");
    expect(calls[0]).toContain("page_size=25");
  });
});
