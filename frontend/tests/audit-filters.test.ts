import { describe, expect, it } from "vitest";
import type { ContextKeyEntry } from "../src/features/factory/auditApi";
import { filterOptions, isNoEventKey, noEventKey, windowBounds } from "../src/features/factory/auditFilters";

function entry(name: string, overrides: Partial<ContextKeyEntry> = {}): ContextKeyEntry {
  return { context_key: `key-${name}`, display_name: name, retired_at: null, event_count: 1, current: true, ...overrides };
}

describe("windowBounds", () => {
  const now = Date.parse("2026-10-13T12:00:00Z");
  const days = (bounds: { windowStart: string; windowEnd: string }) =>
    (Date.parse(bounds.windowEnd) - Date.parse(bounds.windowStart)) / 86_400_000;

  it("gives 7 and 30 days ending now", () => {
    expect(days(windowBounds("last7", null, now))).toBe(7);
    expect(days(windowBounds("last30", null, now))).toBe(30);
    expect(windowBounds("last7", null, now).windowEnd).toBe("2026-10-13T12:00:00.000Z");
  });

  it("starts 'Since recording started' at the instrumentation start", () => {
    expect(windowBounds("since", "2026-10-01T00:00:00Z", now).windowStart).toBe("2026-10-01T00:00:00.000Z");
  });

  it("falls back to 30 days when the start is unknown or in the future", () => {
    expect(days(windowBounds("since", null, now))).toBe(30);
    expect(days(windowBounds("since", "2027-01-01T00:00:00Z", now))).toBe(30);
    expect(days(windowBounds("since", "not a date", now))).toBe(30);
  });
});

describe("filterOptions", () => {
  it("lists current entries first by name, then deleted ones, newest deletion first", () => {
    const options = filterOptions("team", [
      entry("zeta", { current: false, retired_at: "2026-10-01T10:00:00Z" }),
      entry("beta"),
      entry("alpha"),
      entry("gamma", { current: false, retired_at: "2026-10-12T10:00:00Z" }),
    ]);
    expect(options.map((option) => option.label.split(" (")[0])).toEqual(["alpha", "beta", "gamma", "zeta"]);
  });

  it("marks a deleted entry with its date and never shows the key", () => {
    const [option] = filterOptions("team", [entry("major-release-v3", { current: false, retired_at: "2026-10-12T09:00:00Z" })]);
    expect(option.label).toMatch(/^major-release-v3 \(deleted .+\)$/);
    expect(option.label).not.toContain("key-");
    expect(option.value).toBe("key-major-release-v3");
  });

  it("keeps two entries of one name distinct", () => {
    const options = filterOptions("team", [
      entry("Retired crew", { context_key: "new", event_count: 0 }),
      entry("Retired crew", { context_key: "old", event_count: 5, current: false, retired_at: "2026-10-12T09:00:00Z" }),
    ]);
    expect(options).toHaveLength(2);
    expect(new Set(options.map((option) => option.label)).size).toBe(2);
    expect(new Set(options.map((option) => option.value)).size).toBe(2);
  });

  it("separates two current entries that share a name by their event counts", () => {
    const options = filterOptions("scope", [
      entry("api", { context_key: "a", event_count: 1 }),
      entry("api", { context_key: "b", event_count: 4 }),
    ]);
    expect(options.map((option) => option.label).sort()).toEqual(["api · 1 event", "api · 4 events"]);
  });

  it("gives an entry with no key a choice that matches no event", () => {
    const [option] = filterOptions("team", [entry("Fresh crew", { context_key: null, event_count: 0 })]);
    expect(isNoEventKey(option.value)).toBe(true);
    expect(isNoEventKey(noEventKey("scope", "x"))).toBe(true);
    expect(isNoEventKey("team-key-1")).toBe(false);
    expect(option.label).toBe("Fresh crew");
  });
});
