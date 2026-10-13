import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { AuditMetricsPage } from "@/features/factory/AuditMetricsPanel";
import type { AuditEventPage, MetricsWindow } from "@/features/factory/auditApi";
import { clearOperatorToken, getOperatorToken, setOperatorToken } from "@/features/agent-teams/operatorAuth";

// C14: every case renders the real panel with the real browser clients. Only
// the HTTP boundary is replaced: one stub records each request and holds a
// deferred response until the case settles it.
type Call = {
  url: URL;
  headers: Record<string, string>;
  respond: (body: unknown, status?: number) => void;
};

const realFetch = globalThis.fetch;

type KeyList = { teams: unknown[]; repositories: unknown[] };

function stubFetch(keys?: KeyList) {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((resolve) => {
    const url = new URL(String(input), "http://fixture.test");
    // #516: the Team and Repository options answer at once. They are not part of the races under test.
    if (url.pathname.endsWith("/factory/context-keys")) {
      resolve(new Response(JSON.stringify(keys ?? {
        teams: ["a", "b", "c"].map((letter) => ({
          context_key: `team:${letter}`, display_name: `Team ${letter.toUpperCase()}`, retired_at: null, event_count: 1, current: true,
        })),
        repositories: [],
      }), { status: 200, headers: { "Content-Type": "application/json" } }));
      return;
    }
    calls.push({
      url: new URL(String(input), "http://fixture.test"),
      headers: { ...(init?.headers as Record<string, string> | undefined) },
      respond: (body, status = 200) => resolve(new Response(JSON.stringify(body), {
        status, headers: { "Content-Type": "application/json" },
      })),
    });
  })) as unknown as typeof fetch;
  return {
    metrics: () => calls.filter((call) => call.url.pathname.endsWith("/factory/metrics")),
    // The page table reads. The "Needs a look" refusal reads (#520) carry event_kind.
    audit: () => calls.filter((call) => call.url.pathname.endsWith("/factory/audit-events")
      && !call.url.searchParams.has("event_kind")),
    refusals: () => calls.filter((call) => call.url.pathname.endsWith("/factory/audit-events")
      && call.url.searchParams.get("event_kind") === "continuation_request"),
  };
}

type Stub = ReturnType<typeof stubFetch>;

function windowBody(marker: string): MetricsWindow {
  return {
    window_start: "2026-10-01T00:00:00Z",
    window_end: "2026-10-07T00:00:00Z",
    filter_scope: "all",
    counting_unit_note: `note ${marker}`,
    available_interval_start: "2026-10-01T00:00:00Z",
    available_interval_end: "2026-10-07T00:00:00Z",
    missing_intervals: [],
    instrumentation_start: "2026-09-01T00:00:00Z",
    metrics: [
      {
        name: "delivered_in_window", counting_unit: "tracked_attempts", value: 1,
        sample_count: 1, unknown_count: 1, excluded_count: 0,
        unknown_reasons: [`reason ${marker}`],
        source: "factory_audit_events", coverage: "full",
      },
      {
        name: "merged_code_in_window", counting_unit: "code_attempts", value: 3,
        sample_count: 3, unknown_count: 0, excluded_count: 0, unknown_reasons: [],
        source: "factory_audit_events", coverage: "full; sourced merged code pull requests",
      },
      {
        name: "delivered_design_in_window", counting_unit: "design_attempts", value: 4,
        sample_count: 4, unknown_count: 0, excluded_count: 0, unknown_reasons: [],
        source: "factory_audit_events",
        coverage: "full; merged design or exact accepted design version; review is separate",
      },
      {
        name: "terminal_tracking_in_window", counting_unit: "work_items", value: 2,
        sample_count: 2, unknown_count: 0, excluded_count: 0, unknown_reasons: [],
        source: "factory_audit_events", coverage: "full; terminal tracking is not delivery",
      },
      {
        name: "cost", counting_unit: "usage_attribution", value: null,
        sample_count: 0, unknown_count: 1, excluded_count: 0,
        unknown_reasons: ["no measured usage attribution"],
        source: "factory_audit_events", coverage: "unknown",
      },
    ],
  };
}

function eventsBody(marker: string, count = 1, total = count, firstId = 1): AuditEventPage {
  return {
    items: Array.from({ length: count }, (_, index) => ({
      id: firstId + index,
      // One minute apart, so the feed never groups the rows of one page.
      occurred_at: `2026-10-06T10:${String(index).padStart(2, "0")}:00Z`, recorded_at: "2026-10-06T10:59:01Z",
      event_kind: "policy_change", source: "agent_teams.update_github_scope",
      record_kind: "observed", actor_kind: "operator",
      actor_reference: "shared-operator-credential",
      sanitized_reason: `reason for ${marker}`,
      context_snapshot: {
        team_display_name: "Deleted team", repo_name: marker, configured_provider: "codex-cli",
        raw_blob: { nested: "private-detail" },
      },
      before_values: { merge_policy: "human" }, after_values: { merge_policy: "auto" },
      action_outcome: "applied", delivery_outcome: null,
      live_links_available: index !== 0,
    })),
    total, page: 1, page_size: 25, snapshot_labels: ["team_display_name"],
  };
}

async function flushLate() {
  // Real clients read the Response body after the fetch settles; one timer
  // tick is not enough. A positive sentinel always follows this wait.
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 25)); });
}

async function mountWith(stub: Stub, events: AuditEventPage = eventsBody("mount-event")) {
  render(<AuditMetricsPage />);
  await waitFor(() => expect(stub.metrics()).toHaveLength(1));
  stub.metrics()[0].respond(windowBody("mount"));
  await waitFor(() => expect(stub.audit()).toHaveLength(1));
  stub.audit()[0].respond(events);
  await waitFor(() => expect(screen.getByText(/^Loaded \d+ of \d+ audit events\.$/)).toBeInTheDocument());
}

// #516: choose a team in the Team select. A selection applies at once.
async function apply(team: string) {
  const name = `Team ${team.slice(-1).toUpperCase()}`;
  await screen.findByRole("option", { name }, { timeout: 3000 });
  fireEvent.change(screen.getByLabelText("Team"), { target: { value: team } });
}

afterEach(() => {
  globalThis.fetch = realFetch;
  vi.restoreAllMocks();
});

describe("AuditMetricsPage at the HTTP boundary", () => {
  it("renders metrics, coverage, explanations and named safe snapshot values", async () => {
    const stub = stubFetch();
    setOperatorToken("synthetic-operator");
    await mountWith(stub);

    const metricsUrl = stub.metrics()[0].url;
    expect(metricsUrl.pathname).toBe("/api/v1/factory/metrics");
    expect(metricsUrl.searchParams.get("filter_scope")).toBe("all");
    expect(metricsUrl.searchParams.has("page")).toBe(false);
    expect(stub.metrics()[0].headers["X-Deck-Operator-Token"]).toBeUndefined();
    const auditUrl = stub.audit()[0].url;
    expect(auditUrl.pathname).toBe("/api/v1/factory/audit-events");
    expect(auditUrl.searchParams.get("page")).toBe("1");
    expect(auditUrl.searchParams.get("page_size")).toBe("25");
    expect(stub.audit()[0].headers["X-Deck-Operator-Token"]).toBe("synthetic-operator");

    // #517: the plain summary comes first. The definitions sit behind the "?" buttons.
    const summary = screen.getByRole("region", { name: "Delivery in this window" });
    expect(within(summary).getByText(/Recording started .*2026\. The whole window has data\./)).toBeInTheDocument();
    expect(within(summary).getByText("3 code PRs merged, 4 design")).toBeInTheDocument();
    expect(within(summary).getByText("not measured")).toBeInTheDocument();
    expect(screen.queryByText(/Terminal tracking is not delivery/)).not.toBeInTheDocument();
    fireEvent.click(within(summary).getByRole("button", { name: "About: Delivered" }));
    expect(within(summary).getByText(/a merged pull request, or a trusted acceptance/)).toBeInTheDocument();
    expect(within(summary).getByRole("link", { name: "audit and metrics guide" }))
      .toHaveAttribute("href", expect.stringContaining("docs/guide/factory-audit-and-metrics.md"));

    expect(screen.getByText("note mount")).toBeInTheDocument();
    expect(screen.getByText(/reason mount/)).toBeInTheDocument();
    expect(screen.getByText("terminal_tracking_in_window")).toBeInTheDocument();
    // T09: separate code and design delivery rows, apart from total delivery.
    const codeRow = screen.getByText("merged_code_in_window").closest("tr")!;
    expect(within(codeRow).getByText("Code pull requests merged")).toBeInTheDocument();
    expect(within(codeRow).getByText("code_attempts")).toBeInTheDocument();
    expect(within(codeRow).getAllByText("3", { selector: "td" })).toHaveLength(2);
    // The notes sit once below the table, not in each row.
    expect(screen.getByText(/merged design or exact accepted design version; review is separate/)).toBeInTheDocument();
    expect(screen.getByText(/Showing metrics for team all, scope all/)).toBeInTheDocument();
    // The first event has no team link left, so its team shows "(deleted)" (#519).
    expect(screen.getByText("(deleted)")).toBeInTheDocument();
    expect(screen.getByText(/Snapshot labels in page: team_display_name/)).toBeInTheDocument();

    const toggle = screen.getByRole("button", { name: "Show detail" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Hide detail" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("team_display_name: Deleted team")).toBeInTheDocument();
    expect(screen.getByText("configured_provider: codex-cli")).toBeInTheDocument();
    expect(screen.queryByText(/private-detail/)).not.toBeInTheDocument();
  });

  it.each(["old-first", "new-first"])(
    "rejects delayed metrics after A1-B-A2 (%s) and starts one audit read",
    async (order) => {
      const stub = stubFetch();
      setOperatorToken("synthetic-operator");
      await mountWith(stub);

      await apply("team:a");
      await waitFor(() => expect(stub.metrics()).toHaveLength(2));
      await apply("team:b");
      await waitFor(() => expect(stub.metrics()).toHaveLength(3));
      await apply("team:a");
      await waitFor(() => expect(stub.metrics()).toHaveLength(4));
      const [, a1, b, a2] = stub.metrics();
      for (const call of [a1, a2]) {
        expect(call.url.searchParams.get("team_context_key")).toBe("team:a");
        expect(call.url.searchParams.get("filter_scope")).toBe("scoped");
        expect(call.url.searchParams.has("page")).toBe(false);
      }
      expect(b.url.searchParams.get("team_context_key")).toBe("team:b");
      // The mount result stays visible under its own identity while A2 is pending.
      expect(screen.getByText(/Showing metrics for team all, scope all/)).toBeInTheDocument();
      expect(screen.getByText("Retained metrics: a newer read is pending.")).toBeInTheDocument();

      if (order === "old-first") {
        a1.respond(windowBody("A1"));
        b.respond({ detail: "synthetic metrics failure" }, 500);
        await flushLate();
        expect(screen.queryByText("note A1")).not.toBeInTheDocument();
        expect(stub.audit()).toHaveLength(1);
        a2.respond(windowBody("A2"));
      } else {
        a2.respond(windowBody("A2"));
        await waitFor(() => expect(screen.getByText("note A2")).toBeInTheDocument());
        b.respond({ detail: "synthetic metrics failure" }, 500);
        a1.respond(windowBody("A1"));
      }
      await waitFor(() => expect(stub.audit()).toHaveLength(2));
      expect(stub.audit()[1].url.searchParams.get("team_context_key")).toBe("team:a");
      stub.audit()[1].respond(eventsBody("A2-event"));
      await waitFor(() => expect(screen.getByText(/A2-event/)).toBeInTheDocument());
      await flushLate();

      expect(screen.getByText("note A2")).toBeInTheDocument();
      expect(screen.queryByText("note A1")).not.toBeInTheDocument();
      expect(screen.queryByText(/synthetic metrics failure/)).not.toBeInTheDocument();
      expect(screen.queryByText(/Retained metrics/)).not.toBeInTheDocument();
      expect(screen.getByText(/Showing metrics for team Team A, scope all/)).toBeInTheDocument();
      expect(stub.audit()).toHaveLength(2);
    },
  );

  it.each(["old-first", "new-first"])(
    "rejects delayed audit pages after A1-B-A2 (%s)",
    async (order) => {
      const stub = stubFetch();
      setOperatorToken("synthetic-operator");
      await mountWith(stub);

      for (const [index, team] of [[2, "team:a"], [3, "team:b"], [4, "team:a"]] as const) {
        apply(team);
        await waitFor(() => expect(stub.metrics()).toHaveLength(index));
        stub.metrics()[index - 1].respond(windowBody(`metrics ${index}`));
        await waitFor(() => expect(stub.audit()).toHaveLength(index));
      }
      const [, a1, b, a2] = stub.audit();
      for (const [call, team] of [[a1, "team:a"], [b, "team:b"], [a2, "team:a"]] as const) {
        expect(call.headers["X-Deck-Operator-Token"]).toBe("synthetic-operator");
        expect(call.url.searchParams.get("page")).toBe("1");
        expect(call.url.searchParams.get("page_size")).toBe("25");
        expect(call.url.searchParams.get("team_context_key")).toBe(team);
      }

      if (order === "old-first") {
        a1.respond(eventsBody("A1-event", 1, 41));
        b.respond(eventsBody("B-event", 1, 42));
        await flushLate();
        expect(screen.getByText(/mount-event/)).toBeInTheDocument();
        expect(screen.getByText("Total audit events matching filters: 1")).toBeInTheDocument();
        expect(screen.getByText("Retained events: a newer read is pending.")).toBeInTheDocument();
        a2.respond(eventsBody("A2-event", 1, 43));
        await waitFor(() => expect(screen.getByText(/A2-event/)).toBeInTheDocument());
      } else {
        a2.respond(eventsBody("A2-event", 1, 43));
        await waitFor(() => expect(screen.getByText(/A2-event/)).toBeInTheDocument());
        a1.respond(eventsBody("A1-event", 1, 41));
        b.respond(eventsBody("B-event", 1, 42));
        await flushLate();
      }
      expect(screen.queryByText("A1-event")).not.toBeInTheDocument();
      expect(screen.queryByText("B-event")).not.toBeInTheDocument();
      expect(screen.getByText("Total audit events matching filters: 43")).toBeInTheDocument();
      expect(screen.getByText(/Showing events for team Team A, scope all, page 1/)).toBeInTheDocument();
    },
  );

  it("pages the identity on screen and clears an old page error after success", async () => {
    const stub = stubFetch();
    setOperatorToken("synthetic-operator");
    await mountWith(stub, eventsBody("page-one", 25, 27));
    expect(screen.getAllByText(/page-one/)).toHaveLength(25);
    expect(screen.getByText("Page 1 of 2")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(stub.audit()).toHaveLength(2));
    expect(stub.audit()[1].url.searchParams.get("page")).toBe("2");
    expect(stub.audit()[1].url.searchParams.has("team_context_key")).toBe(false);
    stub.audit()[1].respond({ ...eventsBody("page-two", 2, 27, 100), page: 2 });
    await waitFor(() => expect(screen.getAllByText(/page-two/)).toHaveLength(2));
    expect(screen.getByText("Page 2 of 2")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
    await waitFor(() => expect(stub.audit()).toHaveLength(3));
    expect(stub.audit()[2].url.searchParams.get("page")).toBe("1");
    stub.audit()[2].respond(eventsBody("page-one", 25, 27));
    await waitFor(() => expect(screen.getByText("Page 1 of 2")).toBeInTheDocument());

    // While Apply-B is pending, the A rows stay on screen and paging waits:
    // it never requests B page 2 under A rows.
    await apply("team:b");
    await waitFor(() => expect(stub.metrics()).toHaveLength(2));
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await flushLate();
    expect(stub.audit()).toHaveLength(3);
    stub.metrics()[1].respond(windowBody("B"));
    await waitFor(() => expect(stub.audit()).toHaveLength(4));
    stub.audit()[3].respond(eventsBody("b-page-one", 25, 27, 200));
    await waitFor(() => expect(screen.getAllByText(/b-page-one/)).toHaveLength(25));

    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(stub.audit()).toHaveLength(5));
    expect(stub.audit()[4].url.searchParams.get("team_context_key")).toBe("team:b");
    stub.audit()[4].respond({ detail: "synthetic page failure" }, 500);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("synthetic page failure"));
    expect(screen.getByText("Retained events: the latest read failed.")).toBeInTheDocument();
    expect(screen.getByText(/Showing events for team Team B, scope all, page 1/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(stub.audit()).toHaveLength(6));
    stub.audit()[5].respond({ ...eventsBody("b-page-two", 2, 27, 300), page: 2 });
    await waitFor(() => expect(screen.getAllByText(/b-page-two/)).toHaveLength(2));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText(/Retained events/)).not.toBeInTheDocument();
  });

  it("asks for the Director key only through Unlock events and sends one audit read (#515)", async () => {
    const stub = stubFetch();
    render(<AuditMetricsPage />);
    await waitFor(() => expect(stub.metrics()).toHaveLength(1));
    stub.metrics()[0].respond(windowBody("mount"));
    // No stored key: the page opens with no dialog, no audit read and no count.
    await screen.findByRole("button", { name: "Unlock events" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText("note mount")).toBeInTheDocument();
    expect(stub.audit()).toHaveLength(0);
    expect(screen.getByText(/Audit events are protected\./)).toBeInTheDocument();
    expect(screen.queryByText(/Total audit events/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Page \d+ of \d+/)).not.toBeInTheDocument();

    // While locked the Team select offers only "All teams" (#516), and a choice does not ask for the key.
    expect(screen.getAllByText("All teams")).toHaveLength(1);
    fireEvent.change(screen.getByLabelText("Window"), { target: { value: "last30" } });
    await waitFor(() => expect(stub.metrics()).toHaveLength(2));
    stub.metrics()[1].respond(windowBody("30"));
    await flushLate();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(stub.audit()).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "Unlock events" }));
    await waitFor(() => expect(stub.metrics()).toHaveLength(3));
    stub.metrics()[2].respond(windowBody("B"));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    expect(stub.audit()).toHaveLength(0);
    fireEvent.change(screen.getByPlaceholderText("Enter secret value"),
      { target: { value: "synthetic-submitted" } });
    fireEvent.click(screen.getByRole("button", { name: "Use key" }));
    await waitFor(() => expect(stub.audit()).toHaveLength(1));
    expect(getOperatorToken()).toBe("synthetic-submitted");
    expect(stub.audit()[0].headers["X-Deck-Operator-Token"]).toBe("synthetic-submitted");
    expect(stub.audit()[0].url.searchParams.has("team_context_key")).toBe(false);
    const after = Date.parse(stub.audit()[0].url.searchParams.get("occurred_after") ?? "");
    expect(Date.now() - after).toBeGreaterThan(29 * 24 * 3600 * 1000);
    stub.audit()[0].respond(eventsBody("B-event"));
    await waitFor(() => expect(screen.getByText(/B-event/)).toBeInTheDocument());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByText(/Audit events are protected\./)).not.toBeInTheDocument();
    expect(screen.getByText(/Total audit events matching filters: 1/)).toBeInTheDocument();
    expect(stub.audit()).toHaveLength(1);
  });

  it("shows no count after a cancelled key request, and says why", async () => {
    const stub = stubFetch();
    render(<AuditMetricsPage />);
    await waitFor(() => expect(stub.metrics()).toHaveLength(1));
    stub.metrics()[0].respond(windowBody("mount"));
    fireEvent.click(await screen.findByRole("button", { name: "Unlock events" }));
    await waitFor(() => expect(stub.metrics()).toHaveLength(2));
    stub.metrics()[1].respond(windowBody("again"));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(await screen.findByText(/Events are not shown\. The Director key request was cancelled\./)).toBeInTheDocument();
    expect(screen.queryByText(/Total audit events/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\b\d+ events?\b/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Page \d+ of \d+/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unlock events" })).toBeInTheDocument();
    expect(stub.audit()).toHaveLength(0);
  });

  it("opens with a stored key and loads the events with no dialog (#515)", async () => {
    const stub = stubFetch();
    setOperatorToken("synthetic-operator");
    await mountWith(stub);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Unlock events" })).not.toBeInTheDocument();
    expect(screen.getByText(/Total audit events matching filters: 1/)).toBeInTheDocument();
  });

  it("shows the exact 401 refusal, clears the refused token and asks for a replacement", async () => {
    const stub = stubFetch();
    setOperatorToken("synthetic-refused");
    render(<AuditMetricsPage />);
    await waitFor(() => expect(stub.metrics()).toHaveLength(1));
    stub.metrics()[0].respond(windowBody("mount"));
    await waitFor(() => expect(stub.audit()).toHaveLength(1));
    stub.audit()[0].respond({ detail: "operator_token_invalid" }, 401);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(
      "The Director key was rejected. Clear it and enter a valid key."));
    expect(screen.getByText("note mount")).toBeInTheDocument();
    expect(getOperatorToken()).toBeNull();

    // The refusal shows no count and offers Unlock events. Only Unlock asks for the replacement.
    expect(screen.queryByText(/Total audit events/)).not.toBeInTheDocument();
    expect(screen.getByText(/Events are not shown\./)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Unlock events" }));
    await waitFor(() => expect(stub.metrics()).toHaveLength(2));
    stub.metrics()[1].respond(windowBody("A"));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    expect(screen.getByText("note A")).toBeInTheDocument();
    expect(stub.audit()).toHaveLength(1);
  });

  it("shows the exact unconfigured-operator 503 refusal with safe metrics kept", async () => {
    const stub = stubFetch();
    setOperatorToken("synthetic-operator");
    render(<AuditMetricsPage />);
    await waitFor(() => expect(stub.metrics()).toHaveLength(1));
    stub.metrics()[0].respond(windowBody("mount"));
    await waitFor(() => expect(stub.audit()).toHaveLength(1));
    stub.audit()[0].respond({ detail: "operator_token_unconfigured" }, 503);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(
      "The Director key is not configured on the backend."));
    expect(screen.getByText("note mount")).toBeInTheDocument();
    expect(screen.getByText(/Audit events could not be loaded/)).toBeInTheDocument();
  });

  it("opens the detail under its own row and bounds the filters (R10)", async () => {
    const stub = stubFetch();
    setOperatorToken("synthetic-operator");
    await mountWith(stub);

    const toggle = screen.getByRole("button", { name: "Show detail" });
    expect(toggle).toHaveAttribute("aria-controls", "feed-detail-event-1");
    fireEvent.click(toggle);
    const row = toggle.closest("article")!;
    const detail = row.querySelector("#feed-detail-event-1") as HTMLElement;
    expect(detail).not.toBeNull();
    expect(within(detail).getByText("team_display_name: Deleted team")).toBeInTheDocument();
    expect(row.querySelector("table")).toBeNull();
    for (const label of ["Team", "Repository", "Window"]) {
      expect(screen.getByLabelText(label).className).toContain("w-full");
    }
  });

  it("filters with Team, Repository and Window selects, not typed keys (#516)", async () => {
    const stub = stubFetch();
    setOperatorToken("synthetic-operator");
    await mountWith(stub);
    expect(screen.queryByLabelText(/context key/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Apply filters")).not.toBeInTheDocument();
    expect(screen.queryByText("Reload safe metrics")).not.toBeInTheDocument();
    for (const name of ["Team", "Repository", "Window"]) {
      expect(screen.getByRole("combobox", { name })).toBeInTheDocument();
    }
    const windowOptions = within(screen.getByRole("combobox", { name: "Window" })).getAllByRole("option");
    expect(windowOptions.map((option) => option.textContent)).toEqual(["Last 7 days", "Last 30 days", "Since recording started"]);
  });

  it("applies a Window choice at once to the metrics, the events and the refusal read", async () => {
    const stub = stubFetch();
    setOperatorToken("synthetic-operator");
    await mountWith(stub);
    const sevenDays = (call: Call) => Date.now() - Date.parse(call.url.searchParams.get("occurred_after") ?? "");
    expect(sevenDays(stub.audit()[0])).toBeLessThan(8 * 24 * 3600 * 1000);

    fireEvent.change(screen.getByLabelText("Window"), { target: { value: "last30" } });
    await waitFor(() => expect(stub.metrics()).toHaveLength(2));
    const start = Date.parse(stub.metrics()[1].url.searchParams.get("window_start") ?? "");
    expect(Date.now() - start).toBeGreaterThan(29 * 24 * 3600 * 1000);
    stub.metrics()[1].respond(windowBody("30"));
    await waitFor(() => expect(stub.audit()).toHaveLength(2));
    expect(sevenDays(stub.audit()[1])).toBeGreaterThan(29 * 24 * 3600 * 1000);
    expect(screen.getByLabelText("Window")).toHaveValue("last30");
  });

  it("lists deleted teams with their date and keeps two teams of one name apart", async () => {
    const stub = stubFetch({
      teams: [
        { context_key: "team:new", display_name: "Retired crew", retired_at: null, event_count: 0, current: true },
        { context_key: "team:old", display_name: "Retired crew", retired_at: "2026-10-12T09:00:00Z", event_count: 5, current: false },
      ],
      repositories: [
        { context_key: "scope:old", display_name: "example-org/retired-site", retired_at: "2026-10-12T09:00:00Z", event_count: 2, current: false },
      ],
    });
    setOperatorToken("synthetic-operator");
    await mountWith(stub);
    await screen.findByRole("option", { name: /Retired crew \(deleted/ });
    const labels = within(screen.getByRole("combobox", { name: "Team" })).getAllByRole("option").map((option) => option.textContent);
    expect(labels[0]).toBe("All teams");
    expect(labels.filter((label) => label?.startsWith("Retired crew"))).toHaveLength(2);
    expect(new Set(labels).size).toBe(labels.length);
    expect(labels.some((label) => /^Retired crew \(deleted .+\)$/.test(label ?? ""))).toBe(true);
    expect(screen.getByRole("option", { name: /example-org\/retired-site \(deleted/ })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Team"), { target: { value: "team:old" } });
    await waitFor(() => expect(stub.metrics()).toHaveLength(2));
    expect(stub.metrics()[1].url.searchParams.get("team_context_key")).toBe("team:old");
    expect(screen.queryByText(/team:old/)).not.toBeInTheDocument();
  });

  it("shows a plain empty state for a team that has no recorded event", async () => {
    const stub = stubFetch({
      teams: [{ context_key: null, display_name: "Fresh crew", retired_at: null, event_count: 0, current: true }],
      repositories: [],
    });
    setOperatorToken("synthetic-operator");
    await mountWith(stub);
    await screen.findByRole("option", { name: "Fresh crew" });
    const value = (screen.getByRole("option", { name: "Fresh crew" }) as HTMLOptionElement).value;
    fireEvent.change(screen.getByLabelText("Team"), { target: { value } });
    await waitFor(() => expect(stub.metrics()).toHaveLength(2));
    // The request carries a choice that matches no event, never an empty filter that matches every team.
    expect(stub.metrics()[1].url.searchParams.get("team_context_key")).toMatch(/^no-events:/);
    expect(await screen.findByText("No recorded events for this team yet.")).toBeInTheDocument();
  });

  it.each(["Escape", "Cancel"])("restores focus to the Unlock events button after %s closes the token dialog (R11)",
    async (dismissal) => {
      const stub = stubFetch();
      render(<AuditMetricsPage />);
      await waitFor(() => expect(stub.metrics()).toHaveLength(1));
      stub.metrics()[0].respond(windowBody("mount"));
      // The page opens with no dialog (#515). Only Unlock events opens it.
      const unlock = await screen.findByRole("button", { name: "Unlock events" });
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      unlock.focus();
      fireEvent.click(unlock);
      await waitFor(() => expect(stub.metrics()).toHaveLength(2));
      stub.metrics()[1].respond(windowBody("B"));
      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
      if (dismissal === "Escape") {
        fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
      } else {
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
      }
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
      await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Unlock events" })));
    });

  it("labels each retained result with its own identity after a transient failure", async () => {
    const stub = stubFetch();
    setOperatorToken("synthetic-operator");
    await mountWith(stub);

    // Apply-B succeeds at both reads, so B is the last successful identity.
    await apply("team:b");
    await waitFor(() => expect(stub.metrics()).toHaveLength(2));
    stub.metrics()[1].respond(windowBody("B"));
    await waitFor(() => expect(stub.audit()).toHaveLength(2));
    stub.audit()[1].respond(eventsBody("b-event"));
    await waitFor(() => expect(screen.getByText(/b-event/)).toBeInTheDocument());

    // Failure at both reads of Apply-C: each section names its own last
    // successful identity, never C. A 5xx keeps the earlier data (#659).
    await apply("team:c");
    await waitFor(() => expect(stub.metrics()).toHaveLength(3));
    stub.metrics()[2].respond({ detail: "synthetic metrics failure" }, 500);
    await waitFor(() => expect(stub.audit()).toHaveLength(3));
    stub.audit()[2].respond({ detail: "synthetic audit failure" }, 500);
    await waitFor(() => expect(screen.getByText("Retained events: the latest read failed.")).toBeInTheDocument());
    expect(screen.getByText("Retained metrics: the latest read failed.")).toBeInTheDocument();
    expect(screen.getByText(/Showing metrics for team Team B, scope all/)).toBeInTheDocument();
    expect(screen.getByText(/Showing events for team Team B, scope all, page 1/)).toBeInTheDocument();
    expect(screen.getByText(/b-event/)).toBeInTheDocument();
    expect(screen.queryByText(/Showing .* team Team C/)).not.toBeInTheDocument();
    expect(screen.getAllByRole("alert").map((node) => node.textContent)).toEqual([
      "synthetic metrics failure", "synthetic audit failure"]);
  });

  describe("protected results after a cancelled or refused key (#659)", () => {
    const hidden = () => {
      expect(screen.queryByText(/mount-event/)).not.toBeInTheDocument();
      expect(screen.queryByText(/Total audit events/)).not.toBeInTheDocument();
      expect(screen.queryByText(/Page \d+ of \d+/)).not.toBeInTheDocument();
      expect(screen.queryByText(/Showing events for/)).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Next page" })).not.toBeInTheDocument();
      expect(screen.queryByTestId("audit-feed-row")).not.toBeInTheDocument();
      expect(screen.getByTestId("events-locked")).toBeInTheDocument();
    };

    it("hides the loaded events when the key is gone and the Director cancels the new key request", async () => {
      const stub = stubFetch();
      setOperatorToken("synthetic-operator");
      await mountWith(stub);
      expect(screen.getByText(/mount-event/)).toBeInTheDocument();

      // The key is cleared and a filter changes: no key, so nothing protected stays on the page.
      clearOperatorToken();
      fireEvent.change(screen.getByLabelText("Window"), { target: { value: "last30" } });
      await waitFor(() => expect(stub.metrics()).toHaveLength(2));
      stub.metrics()[1].respond(windowBody("30"));
      await screen.findByTestId("events-locked");
      hidden();

      // Unlock and Cancel keep the page locked.
      fireEvent.click(screen.getByRole("button", { name: "Unlock events" }));
      await waitFor(() => expect(stub.metrics()).toHaveLength(3));
      stub.metrics()[2].respond(windowBody("again"));
      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
      fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
      expect(await screen.findByText(/Events are not shown\. The Director key request was cancelled\./)).toBeInTheDocument();
      hidden();
      expect(stub.audit()).toHaveLength(1);
    });

    it("hides the loaded events when a later read is refused with 401, and clears the key", async () => {
      const stub = stubFetch();
      setOperatorToken("synthetic-operator");
      await mountWith(stub);
      expect(screen.getByText(/mount-event/)).toBeInTheDocument();

      fireEvent.change(screen.getByLabelText("Window"), { target: { value: "last30" } });
      await waitFor(() => expect(stub.metrics()).toHaveLength(2));
      stub.metrics()[1].respond(windowBody("30"));
      await waitFor(() => expect(stub.audit()).toHaveLength(2));
      stub.audit()[1].respond({ detail: "operator_token_invalid" }, 401);

      await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(
        "The Director key was rejected. Clear it and enter a valid key."));
      await screen.findByTestId("events-locked");
      hidden();
      expect(screen.getByRole("button", { name: "Unlock events" })).toBeInTheDocument();
      expect(getOperatorToken()).toBeNull();
    });

    it("hides the loaded events at once when a filter changes and no key is stored", async () => {
      const stub = stubFetch();
      setOperatorToken("synthetic-operator");
      await mountWith(stub);
      clearOperatorToken();
      fireEvent.change(screen.getByLabelText("Window"), { target: { value: "last30" } });
      await waitFor(() => expect(stub.metrics()).toHaveLength(2));
      stub.metrics()[1].respond(windowBody("30"));
      await screen.findByTestId("events-locked");
      hidden();
      expect(screen.queryByText(/Retained events/)).not.toBeInTheDocument();
    });

    it("keeps the earlier events after a transient 5xx, as before", async () => {
      const stub = stubFetch();
      setOperatorToken("synthetic-operator");
      await mountWith(stub);
      fireEvent.change(screen.getByLabelText("Window"), { target: { value: "last30" } });
      await waitFor(() => expect(stub.metrics()).toHaveLength(2));
      stub.metrics()[1].respond(windowBody("30"));
      await waitFor(() => expect(stub.audit()).toHaveLength(2));
      stub.audit()[1].respond({ detail: "synthetic server failure" }, 500);
      await waitFor(() => expect(screen.getByText("Retained events: the latest read failed.")).toBeInTheDocument());
      expect(screen.getByText(/mount-event/)).toBeInTheDocument();
      expect(screen.queryByTestId("events-locked")).not.toBeInTheDocument();
      expect(getOperatorToken()).toBe("synthetic-operator");
    });
  });
});
