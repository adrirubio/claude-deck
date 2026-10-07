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

function stubFetch() {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((resolve) => {
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
    audit: () => calls.filter((call) => call.url.pathname.endsWith("/factory/audit-events")),
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
      occurred_at: "2026-10-06T10:00:00Z", recorded_at: "2026-10-06T10:00:01Z",
      event_kind: marker, source: "agent_teams.update_github_scope",
      record_kind: "observed", actor_kind: "operator",
      actor_reference: "shared-operator-credential",
      sanitized_reason: `reason for ${marker}`,
      context_snapshot: {
        team_display_name: "Deleted team", configured_provider: "codex-cli",
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

function apply(team: string) {
  // A text query also finds the control while a modal dialog hides the page
  // from role queries.
  fireEvent.change(screen.getByLabelText("Team context key"), { target: { value: team } });
  fireEvent.click(screen.getByText("Apply filters"));
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

    expect(screen.getByText(/Terminal tracking is not delivery/)).toBeInTheDocument();
    expect(screen.getByText("note mount")).toBeInTheDocument();
    expect(screen.getByText("reason mount")).toBeInTheDocument();
    expect(screen.getByText("terminal_tracking_in_window")).toBeInTheDocument();
    expect(screen.getByText(/Showing metrics for team all, scope all/)).toBeInTheDocument();
    expect(screen.getByText("unavailable")).toBeInTheDocument();
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

      apply("team:a");
      await waitFor(() => expect(stub.metrics()).toHaveLength(2));
      apply("team:b");
      await waitFor(() => expect(stub.metrics()).toHaveLength(3));
      apply("team:a");
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
      await waitFor(() => expect(screen.getByText("A2-event")).toBeInTheDocument());
      await flushLate();

      expect(screen.getByText("note A2")).toBeInTheDocument();
      expect(screen.queryByText("note A1")).not.toBeInTheDocument();
      expect(screen.queryByText(/synthetic metrics failure/)).not.toBeInTheDocument();
      expect(screen.queryByText(/Retained metrics/)).not.toBeInTheDocument();
      expect(screen.getByText(/Showing metrics for team team:a, scope all/)).toBeInTheDocument();
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
        expect(screen.getByText("mount-event")).toBeInTheDocument();
        expect(screen.getByText("Total audit events matching filters: 1")).toBeInTheDocument();
        expect(screen.getByText("Retained events: a newer read is pending.")).toBeInTheDocument();
        a2.respond(eventsBody("A2-event", 1, 43));
        await waitFor(() => expect(screen.getByText("A2-event")).toBeInTheDocument());
      } else {
        a2.respond(eventsBody("A2-event", 1, 43));
        await waitFor(() => expect(screen.getByText("A2-event")).toBeInTheDocument());
        a1.respond(eventsBody("A1-event", 1, 41));
        b.respond(eventsBody("B-event", 1, 42));
        await flushLate();
      }
      expect(screen.queryByText("A1-event")).not.toBeInTheDocument();
      expect(screen.queryByText("B-event")).not.toBeInTheDocument();
      expect(screen.getByText("Total audit events matching filters: 43")).toBeInTheDocument();
      expect(screen.getByText(/Showing events for team team:a, scope all, page 1/)).toBeInTheDocument();
    },
  );

  it("pages the identity on screen and clears an old page error after success", async () => {
    const stub = stubFetch();
    setOperatorToken("synthetic-operator");
    await mountWith(stub, eventsBody("page-one", 25, 27));
    expect(screen.getAllByText("page-one")).toHaveLength(25);
    expect(screen.getByText("Page 1 of 2")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(stub.audit()).toHaveLength(2));
    expect(stub.audit()[1].url.searchParams.get("page")).toBe("2");
    expect(stub.audit()[1].url.searchParams.has("team_context_key")).toBe(false);
    stub.audit()[1].respond({ ...eventsBody("page-two", 2, 27, 100), page: 2 });
    await waitFor(() => expect(screen.getAllByText("page-two")).toHaveLength(2));
    expect(screen.getByText("Page 2 of 2")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
    await waitFor(() => expect(stub.audit()).toHaveLength(3));
    expect(stub.audit()[2].url.searchParams.get("page")).toBe("1");
    stub.audit()[2].respond(eventsBody("page-one", 25, 27));
    await waitFor(() => expect(screen.getByText("Page 1 of 2")).toBeInTheDocument());

    // While Apply-B is pending, the A rows stay on screen and paging waits:
    // it never requests B page 2 under A rows.
    apply("team:b");
    await waitFor(() => expect(stub.metrics()).toHaveLength(2));
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await flushLate();
    expect(stub.audit()).toHaveLength(3);
    stub.metrics()[1].respond(windowBody("B"));
    await waitFor(() => expect(stub.audit()).toHaveLength(4));
    stub.audit()[3].respond(eventsBody("b-page-one", 25, 27, 200));
    await waitFor(() => expect(screen.getAllByText("b-page-one")).toHaveLength(25));

    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(stub.audit()).toHaveLength(5));
    expect(stub.audit()[4].url.searchParams.get("team_context_key")).toBe("team:b");
    stub.audit()[4].respond({ detail: "synthetic page failure" }, 500);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("synthetic page failure"));
    expect(screen.getByText("Retained events: the latest read failed.")).toBeInTheDocument();
    expect(screen.getByText(/Showing events for team team:b, scope all, page 1/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(stub.audit()).toHaveLength(6));
    stub.audit()[5].respond({ ...eventsBody("b-page-two", 2, 27, 300), page: 2 });
    await waitFor(() => expect(screen.getAllByText("b-page-two")).toHaveLength(2));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText(/Retained events/)).not.toBeInTheDocument();
  });

  it("waits for one submitted token and never sends the superseded mount audit read", async () => {
    const stub = stubFetch();
    render(<AuditMetricsPage />);
    await waitFor(() => expect(stub.metrics()).toHaveLength(1));
    stub.metrics()[0].respond(windowBody("mount"));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    expect(screen.getByText("note mount")).toBeInTheDocument();
    expect(stub.audit()).toHaveLength(0);

    apply("team:b");
    await waitFor(() => expect(stub.metrics()).toHaveLength(2));
    fireEvent.change(screen.getByPlaceholderText("Enter secret value"),
      { target: { value: "synthetic-submitted" } });
    fireEvent.click(screen.getByRole("button", { name: "Use token" }));
    await flushLate();
    expect(stub.audit()).toHaveLength(0);
    expect(getOperatorToken()).toBe("synthetic-submitted");

    stub.metrics()[1].respond(windowBody("B"));
    await waitFor(() => expect(stub.audit()).toHaveLength(1));
    expect(stub.audit()[0].headers["X-Deck-Operator-Token"]).toBe("synthetic-submitted");
    expect(stub.audit()[0].url.searchParams.get("team_context_key")).toBe("team:b");
    stub.audit()[0].respond(eventsBody("B-event"));
    await waitFor(() => expect(screen.getByText("B-event")).toBeInTheDocument());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(stub.audit()).toHaveLength(1);
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
      "The Deck operator token was rejected. Clear it and enter a valid token."));
    expect(screen.getByText("note mount")).toBeInTheDocument();
    expect(getOperatorToken()).toBeNull();

    apply("team:a");
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
      "The Deck operator token is not configured on the backend."));
    expect(screen.getByText("note mount")).toBeInTheDocument();
    expect(screen.getByText(/Audit events could not be loaded/)).toBeInTheDocument();
  });

  it("shows expanded detail outside the scrolled table and bounds the filters (R10)", async () => {
    const stub = stubFetch();
    setOperatorToken("synthetic-operator");
    await mountWith(stub);

    const toggle = screen.getByRole("button", { name: "Show detail" });
    expect(toggle).toHaveAttribute("aria-controls", "audit-event-detail");
    fireEvent.click(toggle);
    const region = screen.getByRole("region", { name: "Event detail" });
    expect(region).toHaveAttribute("id", "audit-event-detail");
    expect(within(region).getByText("team_display_name: Deleted team")).toBeInTheDocument();
    for (const element of screen.getAllByRole("table")) {
      expect(element.contains(region)).toBe(false);
    }
    for (const label of ["Team context key", "Scope context key"]) {
      expect(screen.getByLabelText(label).className).toContain("w-full");
    }
  });

  it.each(["Escape", "Cancel"])("restores focus to Apply filters after %s closes the token dialog (R11)",
    async (dismissal) => {
      const stub = stubFetch();
      render(<AuditMetricsPage />);
      await waitFor(() => expect(stub.metrics()).toHaveLength(1));
      stub.metrics()[0].respond(windowBody("mount"));
      // The mount read opens the dialog; nothing invoked it, so focus falls back to Apply.
      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
      if (dismissal === "Escape") {
        fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
      } else {
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
      }
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
      await waitFor(() => expect(document.activeElement).toBe(screen.getByText("Apply filters")));

      // Opened from Apply filters: focus returns to that invoking control.
      const apply = screen.getByText("Apply filters");
      apply.focus();
      fireEvent.click(apply);
      await waitFor(() => expect(stub.metrics()).toHaveLength(2));
      stub.metrics()[1].respond(windowBody("B"));
      await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
      fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
      await waitFor(() => expect(document.activeElement).toBe(apply));
    });

  it("labels each retained result with its own identity after cancellation or failure", async () => {
    const stub = stubFetch();
    setOperatorToken("synthetic-operator");
    await mountWith(stub);

    // Cancellation: the token prompt for Apply-B is cancelled.
    clearOperatorToken();
    apply("team:b");
    await waitFor(() => expect(stub.metrics()).toHaveLength(2));
    stub.metrics()[1].respond(windowBody("B"));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.getByText(
      "Audit read cancelled. Safe metrics remain available.")).toBeInTheDocument());
    expect(screen.getByText("mount-event")).toBeInTheDocument();
    expect(screen.getByText(/Showing events for team all, scope all, page 1/)).toBeInTheDocument();
    expect(screen.getByText("Retained events: the latest read was cancelled.")).toBeInTheDocument();
    expect(stub.audit()).toHaveLength(1);

    // Failure at both reads of Apply-C: each section names its own last
    // successful identity, never C.
    setOperatorToken("synthetic-operator");
    apply("team:c");
    await waitFor(() => expect(stub.metrics()).toHaveLength(3));
    stub.metrics()[2].respond({ detail: "synthetic metrics failure" }, 500);
    await waitFor(() => expect(stub.audit()).toHaveLength(2));
    stub.audit()[1].respond({ detail: "synthetic audit failure" }, 500);
    await waitFor(() => expect(screen.getByText("Retained events: the latest read failed.")).toBeInTheDocument());
    expect(screen.getByText("Retained metrics: the latest read failed.")).toBeInTheDocument();
    expect(screen.getByText(/Showing metrics for team team:b, scope all/)).toBeInTheDocument();
    expect(screen.getByText(/Showing events for team all, scope all, page 1/)).toBeInTheDocument();
    expect(screen.queryByText(/Showing .* team team:c/)).not.toBeInTheDocument();
    expect(screen.getAllByRole("alert").map((node) => node.textContent)).toEqual([
      "synthetic metrics failure", "synthetic audit failure"]);
  });
});
