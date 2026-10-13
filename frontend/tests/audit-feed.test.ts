import { describe, expect, it } from "vitest";
import type { AuditEventRead } from "../src/features/factory/auditApi";
import {
  buildFeed,
  changedFields,
  relativeTime,
  rowMatches,
  teamBadgeClass,
  type FeedContext,
} from "../src/features/factory/auditFeed";

const BASE = Date.parse("2026-10-13T12:00:00Z");
const CTX: FeedContext = { teams: { 1: "Release crew" }, members: { 2: "B1 Backend" } };

let nextId = 1;
function event(kind: string, secondsAgo: number, overrides: Partial<AuditEventRead> = {}): AuditEventRead {
  const at = new Date(BASE - secondsAgo * 1000).toISOString();
  return {
    id: nextId++, occurred_at: at, recorded_at: at, event_kind: kind, source: "test", record_kind: "observation",
    actor_kind: "scheduler", actor_reference: "github_dispatch_scheduler",
    team_preset_id: 1, team_context_key: "team-key-1", scope_id: 4, item_id: 7,
    context_snapshot: { team_display_name: "Release crew", repo_owner: "adrirubio", repo_name: "claude-deck", issue_number: 101 },
    action_outcome: "applied", live_links_available: true, ...overrides,
  };
}

describe("buildFeed rows", () => {
  it("names the actor, the action, the subject and the team in plain words", () => {
    const { rows } = buildFeed([
      event("delivery_evidence", 10),
      event("scope_policy_change", 20, {
        actor_kind: "operator", actor_reference: "shared-operator-credential", item_id: null,
        context_snapshot: { team_display_name: "Release crew", repo_owner: "adrirubio", repo_name: "claude-deck" },
        before_values: { enabled: true, merge_policy: "human" }, after_values: { enabled: false, merge_policy: "human" },
      }),
      event("handoff_acceptance", 30, { actor_kind: "member", actor_reference: "member:2" }),
    ], CTX);
    expect(rows.map((row) => [row.actor, row.action, row.subject?.text])).toEqual([
      ["Deck", "delivered", "adrirubio/claude-deck #101"],
      ["Director", "changed the settings of", "repository adrirubio/claude-deck"],
      ["B1 Backend", "accepted a handoff for", "adrirubio/claude-deck #101"],
    ]);
    expect(rows[0].subject?.href).toBe("/work/7");
    expect(rows[1].subject?.href).toBe("/repositories/4");
    expect(rows[1].changes).toEqual(["enabled: on → off"]);
    expect(rows[0].team).toMatchObject({ name: "Release crew", deleted: false, href: "/teams/1" });
  });

  it("falls back for an unknown kind and never shows the kind code", () => {
    const { rows } = buildFeed([event("brand_new_kind", 5)], CTX);
    expect(rows[0].action).toBe("did something that Deck does not describe on");
    expect(JSON.stringify([rows[0].actor, rows[0].action, rows[0].subject, rows[0].reason])).not.toContain("brand_new_kind");
  });

  it("reads \"An agent\" when Agent Mail gives no name, never \"member <id>\"", () => {
    const { rows } = buildFeed([event("handoff_acceptance", 5, { actor_kind: "member", actor_reference: "member:9" })], CTX);
    expect(rows[0].actor).toBe("An agent");
    expect(JSON.stringify(rows)).not.toMatch(/member \d/);
  });

  it("does not credit a slot name from the snapshot to the operator", () => {
    const { rows } = buildFeed([event("scope_policy_change", 5, {
      actor_kind: "operator", actor_reference: "shared-operator-credential",
      context_snapshot: { slot_display_name: "R1 Sonnet 5.5 Leader", repo_name: "claude-deck" },
    })], CTX);
    expect(rows[0].actor).toBe("Director");
    expect(JSON.stringify(rows[0].subject)).not.toContain("Leader");
  });

  it("shows a refused request with its plain reason", () => {
    const { rows } = buildFeed([event("continuation_request", 5, {
      action_outcome: "rejected", sanitized_reason: "allowed_paths_invalid", actor_kind: "member", actor_reference: "member:2",
    })], CTX);
    expect(rows[0]).toMatchObject({ refused: true, action: "asked to continue", reason: "The plan's file paths are not valid." });
    expect(rowMatches(rows[0], "refused")).toBe(true);
    expect(rowMatches(rows[0], "requests")).toBe(true);
  });
});

describe("teams", () => {
  it("labels an event with no team as Factory-wide", () => {
    const { rows } = buildFeed([event("work_lifecycle", 5, {
      team_preset_id: null, team_context_key: null, scope_id: null, item_id: null, context_snapshot: {},
    })], CTX);
    expect(rows[0].team).toMatchObject({ name: "Factory-wide", factoryWide: true, href: null });
  });

  it("marks a deleted team and does not link it", () => {
    const { rows } = buildFeed([event("team_delete", 5, {
      team_preset_id: null, team_context_key: "gone", actor_kind: "operator", actor_reference: "shared-operator-credential",
      context_snapshot: { team_display_name: "Retired crew" },
    })], CTX);
    expect(rows[0].team).toMatchObject({ name: "Retired crew", deleted: true, href: null });
    expect(rows[0].subject).toEqual({ text: "team Retired crew", href: null });
  });

  it("shows the current name and the stored name when they differ", () => {
    const { rows } = buildFeed([event("delivery_evidence", 5, { context_snapshot: { team_display_name: "Old name", repo_name: "x", issue_number: 1 } })], CTX);
    expect(rows[0].team).toMatchObject({ name: "Release crew", formerly: "Old name" });
  });

  it("gives one team one stable badge class", () => {
    expect(teamBadgeClass("team-key-1")).toBe(teamBadgeClass("team-key-1"));
    expect(teamBadgeClass(null)).toContain("bg-muted");
  });
});

describe("folding and grouping", () => {
  it("folds a notification into its parent action", () => {
    const feed = buildFeed([
      event("continuation_request_notification", 4),
      event("continuation_request", 5, { actor_kind: "member", actor_reference: "member:2" }),
    ], CTX);
    expect(feed.rows).toHaveLength(1);
    expect(feed.rows[0].notified).toEqual(["Leader notified"]);
    expect(feed.hiddenNotifications).toBe(0);
  });

  it("hides a notification with no parent and counts it", () => {
    const feed = buildFeed([event("approval_decision_notification", 4), event("delivery_evidence", 1000)], CTX);
    expect(feed.rows).toHaveLength(1);
    expect(feed.hiddenNotifications).toBe(1);
  });

  it("does not fold a notification of another item", () => {
    const feed = buildFeed([
      event("continuation_request_notification", 4, { item_id: 8 }),
      event("continuation_request", 5, { item_id: 7 }),
    ], CTX);
    expect(feed.hiddenNotifications).toBe(1);
    expect(feed.rows[0].notified).toEqual([]);
  });

  it("groups the same action recorded within one second", () => {
    const feed = buildFeed([event("delivery_evidence", 10), event("delivery_evidence", 10.5), event("delivery_evidence", 30)], CTX);
    expect(feed.rows.map((row) => row.count)).toEqual([2, 1]);
  });

  it("does not group a different reason or a different change", () => {
    const refused = (reason: string, secondsAgo: number) =>
      event("continuation_request", secondsAgo, { action_outcome: "rejected", sanitized_reason: reason });
    expect(buildFeed([refused("allowed_paths_invalid", 10), refused("allowed_actions_invalid", 10)], CTX).rows).toHaveLength(2);
    const change = (value: boolean, secondsAgo: number) =>
      event("scope_policy_change", secondsAgo, { before_values: { enabled: !value }, after_values: { enabled: value } });
    expect(buildFeed([change(true, 10), change(false, 10)], CTX).rows).toHaveLength(2);
  });

  it("shows the setup import as one row with its count", () => {
    const imports = Array.from({ length: 11 }, (_, index) => event("work_state_import", 500 + index, { actor_kind: "system", actor_reference: null }));
    const feed = buildFeed([event("delivery_evidence", 10), ...imports], CTX);
    expect(feed.rows).toHaveLength(2);
    expect(feed.rows[1].action).toBe("recorded the start of the history; existing state imported (11 records)");
    expect(feed.rows[1].team.factoryWide).toBe(true);
    expect(feed.rows[1].count).toBe(11);
  });
});

describe("helpers", () => {
  it("lists only the changed settings and treats a missing value as not set", () => {
    expect(changedFields({ a: 1, b: true, c: "x" }, { a: 1, b: false, c: "y", d: null })).toEqual([
      "b: on → off",
      "c: x → y",
    ]);
    expect(changedFields({}, { max_open: 3 })).toEqual(["max open: not set → 3"]);
  });

  it("formats relative time inside one day only", () => {
    expect(relativeTime(new Date(BASE - 20_000).toISOString(), BASE)).toBe("just now");
    expect(relativeTime(new Date(BASE - 12 * 60_000).toISOString(), BASE)).toBe("12 min ago");
    expect(relativeTime(new Date(BASE - 3 * 3600_000).toISOString(), BASE)).toBe("3 h ago");
    expect(relativeTime(new Date(BASE - 30 * 3600_000).toISOString(), BASE)).toBeNull();
  });
});
