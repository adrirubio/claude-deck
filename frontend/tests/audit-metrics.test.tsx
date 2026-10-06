import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AuditMetricsPage } from "@/features/factory/AuditMetricsPanel";
import * as auditApi from "@/features/factory/auditApi";

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
});
