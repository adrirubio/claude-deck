import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchAuditEvents, fetchMetricsWindow } from "@/features/factory/auditApi";

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
    await expect(fetchAuditEvents({ operatorToken: "bad", page: 1, pageSize: 25 }))
      .rejects.toThrow();
  });
});
