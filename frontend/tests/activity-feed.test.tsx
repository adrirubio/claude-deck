import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { ActivityFeed } from "../src/features/factory/ActivityFeed";
import { buildFeed } from "../src/features/factory/auditFeed";
import type { AuditEventRead } from "../src/features/factory/auditApi";

const NOW = Date.parse("2026-10-13T12:00:00Z");
const CTX = { teams: { 1: "Release crew" }, members: { 2: "B1 Backend" } };

let nextId = 100;
function event(kind: string, secondsAgo: number, overrides: Partial<AuditEventRead> = {}): AuditEventRead {
  const at = new Date(NOW - secondsAgo * 1000).toISOString();
  return {
    id: nextId++, occurred_at: at, recorded_at: at, event_kind: kind, source: "services.internal_source", record_kind: "observation",
    actor_kind: "scheduler", actor_reference: "github_dispatch_scheduler", team_preset_id: 1, team_context_key: "team-key-1",
    scope_id: 4, item_id: 7, sanitized_reason: "some_internal_reason",
    context_snapshot: { team_display_name: "Release crew", repo_owner: "adrirubio", repo_name: "claude-deck", issue_number: 101 },
    action_outcome: "applied", delivery_outcome: null, completion_kind: null, live_links_available: true, ...overrides,
  };
}

const EVENTS = [
  event("delivery_evidence", 60, { delivery_outcome: "delivered" }),
  event("continuation_request", 3600, {
    actor_kind: "member", actor_reference: "member:2", action_outcome: "rejected", sanitized_reason: "allowed_paths_invalid",
  }),
  event("continuation_request_notification", 3599),
  event("scope_policy_change", 3 * 86400, {
    actor_kind: "operator", actor_reference: "shared-operator-credential", item_id: null,
    context_snapshot: { team_display_name: "Release crew", repo_owner: "adrirubio", repo_name: "claude-deck" },
    before_values: { enabled: true }, after_values: { enabled: false },
  }),
  event("team_delete", 4 * 86400, {
    actor_kind: "operator", actor_reference: "shared-operator-credential", team_preset_id: null, team_context_key: "gone-key",
    scope_id: null, item_id: null, context_snapshot: { team_display_name: "Retired crew" },
  }),
];

function renderFeed(events = EVENTS) {
  return render(
    <MemoryRouter>
      <ActivityFeed feed={buildFeed(events, CTX)} now={NOW} snapshotLabels={() => []} />
    </MemoryRouter>,
  );
}

/** The text of a row without its "Technical detail" disclosure. */
function plainText(row: HTMLElement): string {
  const clone = row.cloneNode(true) as HTMLElement;
  clone.querySelectorAll("details").forEach((details) => details.remove());
  return (clone.textContent ?? "").replace(/\s+/g, " ");
}

describe("ActivityFeed", () => {
  it("shows one plain line per action with team, actor and subject", () => {
    renderFeed();
    const rows = screen.getAllByTestId("audit-feed-row");
    expect(rows).toHaveLength(4);
    expect(plainText(rows[0])).toMatch(/Release crew.*Deck delivered adrirubio\/claude-deck #101/);
    expect(plainText(rows[1])).toMatch(/Request refused:.*B1 Backend asked to continue adrirubio\/claude-deck #101/);
    expect(plainText(rows[1])).toContain("The plan's file paths are not valid.");
    expect(plainText(rows[1])).toContain("Leader notified");
    expect(plainText(rows[2])).toMatch(/Director changed the settings of repository adrirubio\/claude-deck/);
    expect(plainText(rows[2])).toContain("enabled: on → off");
  });

  it("shows no null, code name or ISO time outside the technical detail", () => {
    renderFeed();
    for (const row of screen.getAllByTestId("audit-feed-row")) {
      const text = plainText(row);
      expect(text).not.toMatch(/\bnull\b/);
      expect(text).not.toMatch(/[a-z]+_[a-z_]+/);
      expect(text).not.toMatch(/\d{4}-\d{2}-\d{2}T/);
    }
  });

  it("labels a deleted team and does not link it", () => {
    renderFeed();
    const row = screen.getAllByTestId("audit-feed-row")[3];
    expect(plainText(row)).toContain("Retired crew");
    expect(plainText(row)).toContain("(deleted)");
    expect(within(row).queryAllByRole("link")).toHaveLength(0);
  });

  it("shows the local time with a zone, and a relative time for recent events", () => {
    renderFeed();
    const rows = screen.getAllByTestId("audit-feed-row");
    expect(within(rows[0]).getByText(/1 min ago/)).toBeInTheDocument();
    expect(within(rows[1]).getByText(/1 h ago/)).toBeInTheDocument();
    expect(within(rows[3]).queryByText(/ago/)).not.toBeInTheDocument();
    for (const row of rows) {
      const time = row.querySelector("time")!;
      expect(time.textContent).toMatch(/\d{1,2}\/\d{1,2}\/\d{4}, .*(AM|PM) (GMT|UTC|[A-Z]{3,4})/);
      expect(time.textContent).not.toMatch(/\d{4}-\d{2}-\d{2}T/);
    }
  });

  it("opens the detail under its own row, with the technical detail closed", () => {
    renderFeed();
    const row = screen.getAllByTestId("audit-feed-row")[1];
    const toggle = within(row).getByRole("button", { name: "Show detail" });
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const detail = row.querySelector(`#${toggle.getAttribute("aria-controls")}`);
    expect(detail).not.toBeNull();
    expect(within(detail as HTMLElement).getByText("Refused")).toBeInTheDocument();
    const technical = (detail as HTMLElement).querySelector("details")!;
    expect(technical.open).toBe(false);
    expect(technical.textContent).toContain("allowed_paths_invalid");
    expect(plainText(detail as HTMLElement)).not.toContain("allowed_paths_invalid");
    fireEvent.click(within(row).getByRole("button", { name: "Hide detail" }));
    expect(row.querySelector("details")).toBeNull();
  });

  it("filters the loaded page with the chips and counts each one", () => {
    renderFeed();
    expect(screen.getByRole("button", { name: "All (4)" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Refused (1)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Director actions (2)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Deliveries (1)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Agent requests (1)" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refused (1)" }));
    expect(screen.getAllByTestId("audit-feed-row")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Director actions (2)" }));
    expect(screen.getAllByTestId("audit-feed-row")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "All (4)" }));
    expect(screen.getAllByTestId("audit-feed-row")).toHaveLength(4);
  });

  it("says when no row matches the filter and when notifications had no parent", () => {
    renderFeed([event("approval_decision_notification", 5), event("delivery_evidence", 4000)]);
    expect(screen.getByText(/1 notification record is folded into actions on other pages/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refused (0)" }));
    expect(screen.getByText("No activity on this page matches this filter.")).toBeInTheDocument();
  });
});
