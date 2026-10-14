import type { ContextKeyEntry } from "./auditApi";

// #516: the Team, Repository and Window choices of the Audit page. The page
// maps each choice to the context key that the API needs. A Director never
// sees a key.

export type WindowId = "last7" | "last30" | "since";

export const WINDOW_OPTIONS: Array<{ id: WindowId; label: string }> = [
  { id: "last7", label: "Last 7 days" },
  { id: "last30", label: "Last 30 days" },
  { id: "since", label: "Since recording started" },
];

const DAY_MS = 24 * 3600 * 1000;

/**
 * The window bounds at one moment. "Since recording started" begins at the
 * instrumentation start of the last metrics read. Before that read it falls
 * back to 30 days.
 */
export function windowBounds(
  id: WindowId,
  instrumentationStart: string | null,
  nowMs: number,
): { windowStart: string; windowEnd: string } {
  const since = instrumentationStart ? Date.parse(instrumentationStart) : Number.NaN;
  const startMs = id === "last30"
    ? nowMs - 30 * DAY_MS
    : id === "since"
      ? (Number.isFinite(since) && since < nowMs ? since : nowMs - 30 * DAY_MS)
      : nowMs - 7 * DAY_MS;
  return { windowStart: new Date(startMs).toISOString(), windowEnd: new Date(nowMs).toISOString() };
}

/** A choice that no event can match: a live team with no recorded event yet. */
export function noEventKey(kind: "team" | "scope", label: string): string {
  return `no-events:${kind}:${label}`;
}

/** True for the choice of a live team or repository that has no recorded event. */
export function isNoEventKey(key: string): boolean {
  return key.startsWith("no-events:");
}

export interface FilterOption {
  value: string;
  label: string;
}

function deletedOn(iso: string): string {
  const stamp = /Z|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`;
  return new Date(stamp).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/**
 * The options of one select. Current entries come first, by name. A deleted
 * entry reads "name (deleted 12 Oct)". Two entries with one label get their
 * event counts, so they stay distinct. A renamed team is one entry because
 * the API lists each key once.
 */
export function filterOptions(kind: "team" | "scope", entries: ContextKeyEntry[]): FilterOption[] {
  const sorted = [...entries].sort((a, b) => {
    if (a.current !== b.current) return a.current ? -1 : 1;
    if (!a.current) return Date.parse(b.retired_at ?? "") - Date.parse(a.retired_at ?? "");
    return a.display_name.localeCompare(b.display_name);
  });
  const labels = sorted.map((entry) =>
    entry.retired_at ? `${entry.display_name} (deleted ${deletedOn(entry.retired_at)})` : entry.display_name);
  return sorted.map((entry, index) => {
    const twins = labels.filter((label) => label === labels[index]).length;
    const label = twins > 1
      ? `${labels[index]} · ${entry.event_count} ${entry.event_count === 1 ? "event" : "events"}`
      : labels[index];
    return { value: entry.context_key ?? noEventKey(kind, `${index}:${entry.display_name}`), label };
  });
}
