import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { AuditMetricsPage } from "@/features/factory/AuditMetricsPanel";
import { clearOperatorToken, setOperatorToken } from "@/features/agent-teams/operatorAuth";

// #676: the member and team names are a separate read. The rows wait for it,
// and a name that cannot be found reads "An agent", never "member <id>".
const realFetch = globalThis.fetch;

type Held = { respond: (body: unknown, status?: number) => void };
let nameRead: Held | null = null;

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const metrics = {
  window_start: "2026-10-01T00:00:00Z", window_end: "2026-10-30T00:00:00Z", filter_scope: "all",
  counting_unit_note: "note", available_interval_start: "2026-10-01T00:00:00Z",
  available_interval_end: "2026-10-30T00:00:00Z", missing_intervals: [], instrumentation_start: "2026-09-01T00:00:00Z", metrics: [],
};
const hourAgo = () => new Date(Date.now() - 3_600_000).toISOString();
const events = () => ({
  items: [{
    id: 1, occurred_at: hourAgo(), recorded_at: hourAgo(), event_kind: "handoff_acceptance",
    source: "agent_teams", record_kind: "observed", actor_kind: "member", actor_reference: "member:3",
    sanitized_reason: "accepted", context_snapshot: { team_display_name: "Release crew", repo_name: "sample-app", issue_number: 102 },
    before_values: null, after_values: null, action_outcome: "applied", delivery_outcome: null, live_links_available: true,
  }],
  total: 1, page: 1, page_size: 25, snapshot_labels: [],
});
const refusals = () => ({
  items: [{
    id: 2, occurred_at: hourAgo(), recorded_at: hourAgo(), event_kind: "continuation_request",
    source: "e2e_seed", record_kind: "observed", actor_kind: "member", actor_reference: "member:3",
    sanitized_reason: "allowed_paths_invalid", context_snapshot: { team_display_name: "Release crew", repo_name: "sample-app", issue_number: 102 },
    before_values: null, after_values: null, action_outcome: "rejected", delivery_outcome: null, live_links_available: true,
    item_context_key: "item-1", item_id: 12,
  }],
  total: 1, page: 1, page_size: 100, snapshot_labels: [],
});

function stub(options: { names: "held" | "fail" }) {
  nameRead = null;
  globalThis.fetch = vi.fn((input: RequestInfo | URL) => new Promise<Response>((resolve) => {
    const url = new URL(String(input), "http://fixture.test");
    const path = url.pathname;
    if (path.endsWith("/agent-mail/team")) {
      if (options.names === "fail") { resolve(json({ detail: "down" }, 500)); return; }
      nameRead = { respond: (body, status = 200) => resolve(json(body, status)) };
      return;
    }
    if (path.endsWith("/agent-teams/presets")) { resolve(json({ presets: [{ id: 1, name: "Release crew" }] })); return; }
    if (path.endsWith("/factory/context-keys")) { resolve(json({ teams: [], repositories: [] })); return; }
    if (path.endsWith("/factory/metrics")) { resolve(json(metrics)); return; }
    if (path.endsWith("/factory/audit-events")) {
      resolve(json(url.searchParams.get("event_kind") === "continuation_request" ? refusals() : events()));
      return;
    }
    resolve(json({ detail: "unexpected" }, 404));
  })) as unknown as typeof fetch;
}

beforeEach(() => setOperatorToken("synthetic-operator"));
afterEach(() => {
  globalThis.fetch = realFetch;
  clearOperatorToken();
  vi.useRealTimers();
});

const noMemberId = () => expect(document.body.textContent ?? "").not.toMatch(/\bmember \d+\b/i);

describe("audit names", () => {
  it("shows no row and no `member <id>` while the name read is pending, then the names", async () => {
    stub({ names: "held" });
    render(<AuditMetricsPage />);
    await waitFor(() => expect(nameRead).not.toBeNull());
    // The events and the refusals have arrived. The rows still wait for the names.
    await waitFor(() => expect(screen.getAllByText("Reading names.").length).toBeGreaterThan(0));
    for (let step = 0; step < 5; step += 1) {
      noMemberId();
      await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    }
    expect(screen.queryByText(/requests? from/)).not.toBeInTheDocument();
    await act(async () => { nameRead!.respond({ members: [{ id: 3, display_name: "B2 Backend" }] }); });
    expect(await screen.findByText(/1 request from B2 Backend was refused/)).toBeInTheDocument();
    expect(await screen.findAllByText(/B2 Backend/)).not.toHaveLength(0);
    noMemberId();
  });

  it("reads \"An agent\" when the name read fails, and shows the rows", async () => {
    stub({ names: "fail" });
    render(<AuditMetricsPage />);
    expect(await screen.findByText(/1 request from an agent was refused/)).toBeInTheDocument();
    expect(await screen.findAllByText(/An agent/)).not.toHaveLength(0);
    noMemberId();
  });

  it("does not wait for a stalled name read for ever", async () => {
    stub({ names: "held" });
    render(<AuditMetricsPage />);
    await waitFor(() => expect(nameRead).not.toBeNull());
    await waitFor(() => expect(screen.getAllByText("Reading names.").length).toBeGreaterThan(0));
    // After the limit the rows show with the fallback.
    expect(await screen.findByText(/1 request from an agent was refused/, {}, { timeout: 7000 })).toBeInTheDocument();
    noMemberId();
    // A late answer still names the rows.
    await act(async () => { nameRead!.respond({ members: [{ id: 3, display_name: "B2 Backend" }] }); });
    expect(await screen.findByText(/1 request from B2 Backend was refused/)).toBeInTheDocument();
  }, 15000);
});
