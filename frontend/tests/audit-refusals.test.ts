import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { AuditEventRead } from "../src/features/factory/auditApi";
import {
  REFUSAL_REASONS,
  REFUSAL_REPEAT_THRESHOLD,
  UNKNOWN_REASON,
  groupRefusals,
  plainReason,
} from "../src/features/factory/auditRefusals";

const NOW = Date.parse("2026-10-13T12:00:00Z");
const WINDOW_START = NOW - 7 * 24 * 3600 * 1000;

function refusal(id: number, code: string, hoursAgo: number, overrides: Partial<AuditEventRead> = {}): AuditEventRead {
  return {
    id,
    occurred_at: new Date(NOW - hoursAgo * 3600 * 1000).toISOString(),
    recorded_at: new Date(NOW - hoursAgo * 3600 * 1000).toISOString(),
    event_kind: "continuation_request",
    source: "test",
    record_kind: "observation",
    actor_kind: "member",
    actor_reference: "member:2",
    item_id: 7,
    item_context_key: "item-7",
    context_snapshot: { repo_name: "claude-deck-website", issue_number: 2 },
    sanitized_reason: code,
    action_outcome: "rejected",
    live_links_available: true,
    ...overrides,
  };
}

describe("plain reasons for refused requests", () => {
  it("has one short sentence for each code that the controller can record", () => {
    const source = ["../backend/app/services/github_approval_service.py", "../backend/app/api/v1/agent_teams.py"]
      .map((file) => readFileSync(file, "utf8")).join("\n");
    const codes = new Set([...source.matchAll(/GithubApprovalError\(\s*"([a-z0-9_]+)"/g)].map((match) => match[1]));
    expect(codes.size).toBeGreaterThan(30);
    const missing = [...codes].filter((code) => !REFUSAL_REASONS[code]);
    expect(missing).toEqual([]);
    for (const [code, sentence] of Object.entries(REFUSAL_REASONS)) {
      expect(sentence.split(/\s+/).length, code).toBeLessThanOrEqual(20);
      expect(sentence, code).not.toMatch(/[a-z]+_[a-z_]+/);
    }
  });

  it("uses the issue wording for the codes of the observed refusals", () => {
    expect(plainReason("allowed_paths_invalid")).toBe("The plan's file paths are not valid.");
    expect(plainReason("continuation_failed_head_limit_exceeded")).toBe("Too many failed attempts for this plan.");
  });

  it("falls back for an unknown, empty or missing code", () => {
    expect(plainReason("e2e_unknown_reason_code")).toBe(UNKNOWN_REASON);
    expect(plainReason("")).toBe(UNKNOWN_REASON);
    expect(plainReason(null)).toBe(UNKNOWN_REASON);
  });
});

describe("groupRefusals", () => {
  it("groups by member and item, then by reason, with counts and the last time", () => {
    const groups = groupRefusals([
      refusal(1, "allowed_paths_invalid", 30),
      refusal(2, "allowed_paths_invalid", 20),
      refusal(3, "allowed_paths_invalid", 10),
      refusal(4, "continuation_failed_head_limit_exceeded", 25),
      refusal(5, "continuation_not_escalated", 5, { actor_reference: "member:3", item_id: 9, item_context_key: "item-9",
        context_snapshot: { repo_name: "claude-deck", issue_number: 492 } }),
    ], WINDOW_START);
    expect(groups).toHaveLength(2);
    const [newest, older] = groups;
    expect(newest.itemLabel).toBe("claude-deck #492");
    expect(newest.memberId).toBe(3);
    expect(older.itemLabel).toBe("claude-deck-website #2");
    expect(older.total).toBe(4);
    expect(older.reasons.map((reason) => [reason.sentence, reason.count])).toEqual([
      ["The plan's file paths are not valid.", 3],
      ["Too many failed attempts for this plan.", 1],
    ]);
    expect(older.lastAt).toBe(new Date(NOW - 10 * 3600 * 1000).toISOString());
  });

  it("marks a repeated refusal at the threshold and not below it", () => {
    const events = (count: number) => Array.from({ length: count }, (_, index) => refusal(index + 1, "allowed_paths_invalid", index + 1));
    expect(groupRefusals(events(REFUSAL_REPEAT_THRESHOLD), WINDOW_START)[0].repeated).toBe(true);
    expect(groupRefusals(events(REFUSAL_REPEAT_THRESHOLD - 1), WINDOW_START)[0].repeated).toBe(false);
  });

  it("merges different unknown codes into one fallback reason and never keeps the raw code", () => {
    const [group] = groupRefusals([refusal(1, "new_code_a", 2), refusal(2, "new_code_b", 1)], WINDOW_START);
    expect(group.reasons).toHaveLength(1);
    expect(group.reasons[0]).toMatchObject({ sentence: UNKNOWN_REASON, count: 2 });
    expect(JSON.stringify(group)).not.toContain("new_code");
  });

  it("skips events that are not refused requests or are outside the window", () => {
    const groups = groupRefusals([
      refusal(1, "allowed_paths_invalid", 8 * 24),
      refusal(2, "allowed_paths_invalid", 2, { action_outcome: "applied" }),
      refusal(3, "allowed_paths_invalid", 2, { event_kind: "work_lifecycle" }),
    ], WINDOW_START);
    expect(groups).toEqual([]);
  });

  it("labels an item without a snapshot by its id", () => {
    const [group] = groupRefusals([refusal(1, "allowed_paths_invalid", 1, { context_snapshot: null })], WINDOW_START);
    expect(group.itemLabel).toBe("item 7");
  });
});
