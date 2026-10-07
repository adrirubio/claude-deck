import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AuditMetricsPage } from "@/features/factory/AuditMetricsPanel";
import * as auditApi from "@/features/factory/auditApi";
import { setOperatorToken } from "@/features/agent-teams/operatorAuth";

const windowFixture: auditApi.MetricsWindow = {
  window_start: "2026-10-06T00:00:00Z",
  window_end: "2026-10-06T23:59:59Z",
  filter_scope: "all",
  counting_unit_note: "Counts are tracked attempts or events as named per metric. Tracked attempts across separate scopes remain distinct and are never advertised as a unique-PR total.",
  available_interval_start: "2026-10-01T00:00:00Z",
  available_interval_end: "2026-10-06T23:59:59Z",
  missing_intervals: [],
  instrumentation_start: "2026-10-01T00:00:00Z",
  metrics: [
    {
      name: "delivered_in_window", counting_unit: "tracked_attempts", value: 1,
      sample_count: 1, unknown_count: 1, excluded_count: 0,
      unknown_reasons: ["no attributable independent human acceptance"],
      source: "factory_audit_events", coverage: "full",
    },
    {
      name: "cost", counting_unit: "usage_attribution", value: null,
      sample_count: 0, unknown_count: 1, excluded_count: 0,
      unknown_reasons: ["no measured usage attribution"],
      source: "factory_audit_events", coverage: "unknown",
    },
  ],
};

const pageFixture: auditApi.AuditEventPage = {
  items: [
    {
      id: 1, occurred_at: "2026-10-06T10:00:00Z", recorded_at: "2026-10-06T10:00:01Z",
      event_kind: "policy_change", source: "agent_teams.update_github_scope",
      record_kind: "observed", actor_kind: "operator",
      actor_reference: "shared-operator-credential",
      team_context_key: "team:1:x", sanitized_reason: "scope configuration update",
      before_values: { merge_policy: "human" }, after_values: { merge_policy: "auto" },
      action_outcome: "applied", delivery_outcome: null,
      live_links_available: true,
    },
    {
      id: 2, occurred_at: "2026-10-05T09:00:00Z", recorded_at: "2026-10-05T09:00:01Z",
      event_kind: "work_lifecycle", source: "github_dispatch_service.launch",
      record_kind: "observed_snapshot", actor_kind: "scheduler",
      context_snapshot: { team_display_name: "Deleted team" },
      action_outcome: "applied", delivery_outcome: "unknown",
      live_links_available: false,
    },
  ],
  total: 2,
  page: 1,
  page_size: 25,
  snapshot_labels: ["team_display_name"],
};

describe("AuditMetricsPage", () => {
  beforeEach(() => {
    vi.spyOn(auditApi, "fetchMetricsWindow").mockResolvedValue(windowFixture);
    vi.spyOn(auditApi, "fetchAuditEvents").mockResolvedValue(pageFixture);
    setOperatorToken("synthetic-operator");
  });

  it("renders metrics with explicit unknown counts, coverage and explanations", async () => {
    render(<AuditMetricsPage />);
    await waitFor(() => expect(screen.getByText(/Loaded 2 of 2 audit events/)).toBeInTheDocument());
    expect(screen.getByText(/Terminal tracking is not delivery/)).toBeInTheDocument();
    expect(screen.getAllByText(/never advertised as a unique-PR total/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("unknown").length).toBeGreaterThan(0);
    expect(screen.getByText(/no attributable independent human acceptance/)).toBeInTheDocument();
  });

  it("exposes event detail through a keyboard-accessible disclosure", async () => {
    render(<AuditMetricsPage />);
    const toggles = await screen.findAllByRole("button", { name: "Show detail" });
    expect(toggles[0]).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggles[0]);
    expect(screen.getByText(/scope configuration update/)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Hide detail" })[0]).toHaveAttribute("aria-expanded", "true");
  });

  it("labels unavailable live links while keeping snapshot labels visible", async () => {
    render(<AuditMetricsPage />);
    await waitFor(() => expect(screen.getByText("unavailable")).toBeInTheDocument());
    expect(screen.getAllByText(/Snapshot labels in page: team_display_name/).length).toBeGreaterThan(0);
  });
  // C13: per-invocation epochs reject old responses after A-to-B-to-A.
  it("rejects old responses after an A-to-B-to-A filter sequence", async () => {
    type Deferred = { resolve: (value: auditApi.AuditEventPage) => void };
    const pending: Deferred[] = [];
    const eventsFor = (marker: string): auditApi.AuditEventPage => ({
      items: [{
        id: marker === "A3 newest" ? 31 : marker === "B late" ? 21 : 11,
        occurred_at: "2026-10-06T10:00:00Z", recorded_at: "2026-10-06T10:00:01Z",
        event_kind: marker, source: "synthetic", record_kind: "observed", actor_kind: "operator",
        action_outcome: "applied", delivery_outcome: null, live_links_available: true,
      }],
      total: 1, page: 1, page_size: 25, snapshot_labels: [],
    });
    vi.spyOn(auditApi, "fetchAuditEvents").mockImplementation(() => new Promise((resolve) => {
      pending.push({ resolve });
    }));
    render(<AuditMetricsPage />);
    // The mount request must start before the first Apply. applyReads waits one
    // microtask, so an immediate first Apply could cancel the mount request.
    await waitFor(() => expect(pending.length).toBe(1));
    // Three applies: A, B, A. The responses resolve out of order.
    fireEvent.change(screen.getByLabelText("Team context key"), { target: { value: "team:a" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(pending.length).toBe(2));
    fireEvent.change(screen.getByLabelText("Team context key"), { target: { value: "team:b" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(pending.length).toBe(3));
    fireEvent.change(screen.getByLabelText("Team context key"), { target: { value: "team:a" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(pending.length).toBe(4));

    pending[3].resolve(eventsFor("A3 newest"));
    await waitFor(() => expect(screen.getByText("A3 newest")).toBeInTheDocument());
    pending[2].resolve(eventsFor("B late"));
    pending[1].resolve(eventsFor("A1 oldest"));
    pending[0].resolve(eventsFor("A1 oldest"));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByText("A3 newest")).toBeInTheDocument();
    expect(screen.queryByText("B late")).not.toBeInTheDocument();
    expect(screen.queryByText("A1 oldest")).not.toBeInTheDocument();
  });

  // C13: a refused audit read keeps retained rows and labels them stale.
  it("labels the retained event list stale after a refused audit read", async () => {
    render(<AuditMetricsPage />);
    await waitFor(() => expect(screen.getByText(/Loaded 2 of 2 audit events/)).toBeInTheDocument());
    vi.spyOn(auditApi, "fetchAuditEvents").mockRejectedValue(new Error("Audit read refused."));
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(screen.getByText(/Stale event list retained from/)).toBeInTheDocument());
    expect(screen.getAllByText(/policy_change/).length).toBeGreaterThan(0);
  });

  // C13: pagination beyond 25 events keeps the applied identity.
  it("paginates audit events with the applied filters preserved", async () => {
    const paged: auditApi.AuditEventPage = {
      items: [{
        id: 3, occurred_at: "2026-10-06T11:00:00Z", recorded_at: "2026-10-06T11:00:01Z",
        event_kind: "work_lifecycle", source: "synthetic", record_kind: "observed", actor_kind: "scheduler",
        action_outcome: "applied", delivery_outcome: null, live_links_available: true,
      }],
      total: 30, page: 2, page_size: 25, snapshot_labels: [],
    };
    const auditSpy = vi.spyOn(auditApi, "fetchAuditEvents").mockResolvedValue({ ...pageFixture, total: 30 });
    render(<AuditMetricsPage />);
    await waitFor(() => expect(screen.getByText(/Loaded 2 of 30 audit events/)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Team context key"), { target: { value: "team:page" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(screen.getByText(/Loaded 2 of 30 audit events/)).toBeInTheDocument());
    auditSpy.mockResolvedValue(paged);
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(screen.getByText("work_lifecycle")).toBeInTheDocument());
    expect(screen.getByText(/Page 2 of 2/)).toBeInTheDocument();
    expect(auditSpy).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, teamContextKey: "team:page" }));
  });

  // C13: only named snapshot labels render their stored values.
  it("renders stored values for named snapshot labels only", async () => {
    const named: auditApi.AuditEventPage = {
      items: [{
        id: 2, occurred_at: "2026-10-05T09:00:00Z", recorded_at: "2026-10-05T09:00:01Z",
        event_kind: "work_lifecycle", source: "github_dispatch_service.launch",
        record_kind: "observed_snapshot", actor_kind: "scheduler",
        context_snapshot: { team_display_name: "Deleted team", raw_blob: { nested: "private-detail" } },
        action_outcome: "applied", delivery_outcome: "unknown", live_links_available: false,
      }],
      total: 1, page: 1, page_size: 25, snapshot_labels: ["team_display_name"],
    };
    vi.spyOn(auditApi, "fetchAuditEvents").mockResolvedValue(named);
    render(<AuditMetricsPage />);
    const toggles = await screen.findAllByRole("button", { name: "Show detail" });
    fireEvent.click(toggles[0]);
    expect(screen.getByText(/team_display_name: Deleted team/)).toBeInTheDocument();
    expect(screen.queryByText(/private-detail/)).not.toBeInTheDocument();
  });

  // C13: both reads receive the same applied filters.
  it("passes matching team and scope filters to both reads", async () => {
    const metricsSpy = vi.spyOn(auditApi, "fetchMetricsWindow").mockResolvedValue(windowFixture);
    const auditSpy = vi.spyOn(auditApi, "fetchAuditEvents").mockResolvedValue(pageFixture);
    render(<AuditMetricsPage />);
    await waitFor(() => expect(screen.getByText(/Loaded 2 of 2 audit events/)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Team context key"), { target: { value: "team:9:z" } });
    fireEvent.change(screen.getByLabelText("Scope context key"), { target: { value: "scope:7:y" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(auditSpy).toHaveBeenCalledTimes(2));
    expect(metricsSpy).toHaveBeenLastCalledWith(expect.objectContaining({
      teamContextKey: "team:9:z", scopeContextKey: "scope:7:y",
    }));
    expect(auditSpy).toHaveBeenLastCalledWith(expect.objectContaining({
      teamContextKey: "team:9:z", scopeContextKey: "scope:7:y",
    }));
  });
  // C13 Root2956: a delayed old metrics completion, including a rejection,
  // must never start an old audit epoch or invalidate newer A2 events.
  it("does not start a stale audit after delayed metrics in an A1-B-A2 sequence", async () => {
    type MetricsDeferred = {
      resolve: (value: auditApi.MetricsWindow) => void;
      reject: (reason: Error) => void;
    };
    const pendingMetrics: MetricsDeferred[] = [];
    vi.spyOn(auditApi, "fetchMetricsWindow").mockImplementation(() => new Promise((resolve, reject) => {
      pendingMetrics.push({ resolve, reject });
    }));
    const auditSpy = vi.spyOn(auditApi, "fetchAuditEvents").mockResolvedValue({
      items: [{
        id: 41, occurred_at: "2026-10-06T12:00:00Z", recorded_at: "2026-10-06T12:00:01Z",
        event_kind: "A2 newest", source: "synthetic", record_kind: "observed", actor_kind: "operator",
        action_outcome: "applied", delivery_outcome: null, live_links_available: true,
      }],
      total: 1, page: 1, page_size: 25, snapshot_labels: [],
    });
    render(<AuditMetricsPage />);
    // The mount request must start before the first Apply. applyReads waits one
    // microtask, so an immediate first Apply could cancel the mount request.
    await waitFor(() => expect(pendingMetrics.length).toBe(1));

    fireEvent.change(screen.getByLabelText("Team context key"), { target: { value: "team:a" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(pendingMetrics.length).toBe(2));
    fireEvent.change(screen.getByLabelText("Team context key"), { target: { value: "team:b" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(pendingMetrics.length).toBe(3));
    fireEvent.change(screen.getByLabelText("Team context key"), { target: { value: "team:a" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(pendingMetrics.length).toBe(4));

    // A2 completes first and publishes its audit.
    pendingMetrics[3].resolve(windowFixture);
    await waitFor(() => expect(screen.getByText("A2 newest")).toBeInTheDocument());
    const auditCallsAfterA2 = auditSpy.mock.calls.length;
    expect(auditCallsAfterA2).toBe(1);

    // B resolves late: its apply identity is old, so no B audit may start.
    pendingMetrics[2].resolve(windowFixture);
    // A1 rejects late: its apply identity is old, so no A1 audit may start.
    pendingMetrics[1].reject(new Error("delayed metrics failure"));
    // The mount invocation is old too.
    pendingMetrics[0].resolve(windowFixture);
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(screen.getByText("A2 newest")).toBeInTheDocument();
    expect(auditSpy).toHaveBeenCalledTimes(1);
    expect(auditSpy).toHaveBeenCalledWith(expect.objectContaining({ teamContextKey: "team:a" }));
    expect(auditCallsAfterA2).toBe(1);
  });
  // Root2976: a pending standalone page read is invalidated when a newer
  // Apply starts, even if it settles before the new audit read begins.
  it("invalidates a pending page read when a newer Apply starts", async () => {
    type Deferred<T> = { resolve: (value: T) => void };
    const pendingAudit: Deferred<auditApi.AuditEventPage>[] = [];
    const pendingMetrics: Deferred<auditApi.MetricsWindow>[] = [];
    const eventsFor = (marker: string): auditApi.AuditEventPage => ({
      items: [{
        id: marker === "B fresh" ? 51 : 61,
        occurred_at: "2026-10-06T13:00:00Z", recorded_at: "2026-10-06T13:00:01Z",
        event_kind: marker, source: "synthetic", record_kind: "observed", actor_kind: "operator",
        action_outcome: "applied", delivery_outcome: null, live_links_available: true,
      }],
      total: 30, page: 1, page_size: 25, snapshot_labels: [],
    });
    const metricsSpy = vi.spyOn(auditApi, "fetchMetricsWindow").mockImplementation(
      () => new Promise((resolve) => { pendingMetrics.push({ resolve }); }));
    const auditSpy = vi.spyOn(auditApi, "fetchAuditEvents").mockResolvedValue({ ...pageFixture, total: 30 });
    render(<AuditMetricsPage />);
    // Complete the mount reads first: metrics then audit.
    await waitFor(() => expect(pendingMetrics.length).toBe(1));
    pendingMetrics[0].resolve(windowFixture);
    await waitFor(() => expect(screen.getByText(/Loaded 2 of 30 audit events/)).toBeInTheDocument());

    // The page-A audit read stays pending.
    auditSpy.mockImplementation(() => new Promise((resolve) => { pendingAudit.push({ resolve }); }));
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(pendingAudit.length).toBe(1));

    // Apply-B starts and its metrics read is deferred explicitly.
    fireEvent.change(screen.getByLabelText("Team context key"), { target: { value: "team:b" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(pendingMetrics.length).toBe(2));

    // The old page read settles while B metrics remain pending.
    pendingAudit[0].resolve(eventsFor("page-A stale"));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByText("page-A stale")).not.toBeInTheDocument();

    // B completes and publishes its events.
    pendingMetrics[1].resolve(windowFixture);
    await waitFor(() => expect(pendingAudit.length).toBe(2));
    pendingAudit[1].resolve(eventsFor("B fresh"));
    await waitFor(() => expect(screen.getByText("B fresh")).toBeInTheDocument());
    expect(screen.queryByText("page-A stale")).not.toBeInTheDocument();
    expect(auditSpy).toHaveBeenLastCalledWith(expect.objectContaining({ teamContextKey: "team:b" }));
  });
});
