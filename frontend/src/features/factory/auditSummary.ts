import { parseServerTime } from "@/lib/serverTime";
import type { MetricSample, MetricsWindow } from "./auditApi";

// #517: the plain-language summary of the Audit page. These functions only
// format what the metrics read returns. They never change a value and never
// turn an unknown value into zero.

export const GUIDE_URL = "https://github.com/adrirubio/claude-deck/blob/master/docs/guide/factory-audit-and-metrics.md";

const DAY_MS = 24 * 3600 * 1000;

export const METRIC_LABELS: Record<string, string> = {
  terminal_tracking_in_window: "Terminal tracking",
  delivered_in_window: "Delivered",
  merged_code_in_window: "Code pull requests merged",
  delivered_design_in_window: "Design delivered",
  closed_without_delivery: "Closed without delivery",
  unknown_outcomes: "Outcome unknown",
  independently_human_reviewed_design: "Design reviewed by an independent human",
  elapsed_attempt_duration: "Median time from dispatch to finish",
  implementation_retries: "Implementation retries charged",
  diagnostic_retries: "Diagnostic retries charged",
  implementation_retry_counters: "Implementation retry budget now",
  diagnostic_retry_counters: "Diagnostic retry budget now",
  recovery_success: "Recoveries that succeeded",
  operator_interventions: "Director interventions",
  harness_failures: "Failed launches",
  current_queue: "Queue now",
  total_tracked_attempts: "Tracked attempts",
  pending_reviews: "Reviews pending now",
  active_revisions: "Active revisions now",
  cost: "Cost",
};

/** A people-facing label for a metric code. An unknown code gets its words. */
export function metricLabel(name: string): string {
  return METRIC_LABELS[name] ?? name.replaceAll("_", " ");
}

function sampleOf(window: MetricsWindow | null, name: string): MetricSample | undefined {
  return window?.metrics.find((sample) => sample.name === name);
}

/** "2 h 50 min", "45 min", "3 d 4 h". Never a raw number of seconds. */
export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "unknown";
  const minutes = Math.round(seconds / 60);
  if (minutes < 1) return "under 1 min";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) {
    const rest = minutes % 60;
    return rest ? `${hours} h ${rest} min` : `${hours} h`;
  }
  const days = Math.floor(hours / 24);
  const restHours = hours % 24;
  return restHours ? `${days} d ${restHours} h` : `${days} d`;
}

function count(sample: MetricSample | undefined): string {
  return sample?.value == null ? "unknown" : String(sample.value);
}

function localDate(iso: string): string {
  return parseServerTime(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/** One sentence: when recording started and how much of the window has no data. */
export function coverageSentence(window: MetricsWindow | null): string {
  if (!window) return "Coverage is not loaded yet.";
  if (!window.instrumentation_start) return "Recording has not started. This window has no data.";
  const started = `Recording started ${localDate(window.instrumentation_start)}.`;
  if (!window.available_interval_start) return `${started} This window has no data.`;
  const gap = Date.parse(window.available_interval_start) - Date.parse(window.window_start);
  if (!Number.isFinite(gap) || gap < 3600 * 1000) return `${started} The whole window has data.`;
  const days = Math.round(gap / DAY_MS);
  if (days >= 1) return `${started} The first ${days} ${days === 1 ? "day" : "days"} of this window have no data.`;
  const hours = Math.max(1, Math.round(gap / 3600_000));
  return `${started} The first ${hours} ${hours === 1 ? "hour" : "hours"} of this window have no data.`;
}

export interface Headline {
  id: string;
  label: string;
  value: string;
  detail: string | null;
  help: string;
}

/** The headline results, in plain words. A null value reads "unknown", never 0. */
export function headlines(window: MetricsWindow | null): Headline[] {
  if (!window) return [];
  const delivered = sampleOf(window, "delivered_in_window");
  const retries = [sampleOf(window, "implementation_retries"), sampleOf(window, "diagnostic_retries")];
  const retriesKnown = retries.every((sample) => sample?.value != null);
  const duration = sampleOf(window, "elapsed_attempt_duration");
  const cost = sampleOf(window, "cost");
  return [
    {
      id: "delivered",
      label: "Delivered",
      value: count(delivered),
      detail: `${count(sampleOf(window, "merged_code_in_window"))} code PRs merged, ${count(sampleOf(window, "delivered_design_in_window"))} design`,
      help: "Attempts whose current result is delivered: a merged pull request, or a trusted acceptance of an exact design version.",
    },
    {
      id: "closed",
      label: "Closed without delivery",
      value: count(sampleOf(window, "closed_without_delivery")),
      detail: null,
      help: "Attempts with sourced proof that they ended without delivery. For example, GitHub closed the issue as not planned, with no pull request.",
    },
    {
      id: "unknown",
      label: "Outcome unknown",
      value: count(sampleOf(window, "unknown_outcomes")),
      detail: null,
      help: "Attempts that ended but have no result evidence. For example, an ordinary issue closure with no merge evidence. Later evidence can resolve them.",
    },
    {
      id: "duration",
      label: "Median time from dispatch to finish",
      value: duration?.value == null ? "unknown" : formatDuration(duration.value),
      detail: null,
      help: "The median time from dispatch to the first finishing fact of the same attempt. It is not execution time or hands-on time.",
    },
    {
      id: "interventions",
      label: "Director interventions",
      value: count(sampleOf(window, "operator_interventions")),
      detail: null,
      help: "Distinct applied actions of the Director, one for each action and resource. Notifications and refused actions are not counted.",
    },
    {
      id: "recoveries",
      label: "Recoveries that succeeded",
      value: count(sampleOf(window, "recovery_success")),
      detail: null,
      help: "Revisions whose preserved result completed, one for each revision. A cancel or resume request is not a success.",
    },
    {
      id: "retries",
      label: "Retries charged",
      value: retriesKnown ? String(retries.reduce((sum, sample) => sum + (sample?.value ?? 0), 0)) : "unknown",
      detail: retriesKnown
        ? `${retries[0]?.value} implementation, ${retries[1]?.value} diagnostic`
        : null,
      help: "Recorded retry charges. The remaining retry budget is a different number and is in the technical table.",
    },
    {
      id: "cost",
      label: "Cost",
      value: cost?.value == null ? "not measured" : String(cost.value),
      detail: null,
      help: "Deck has no measured usage attribution, so it reports no cost.",
    },
  ];
}

/** The value of one metric for the technical table. Values stay unchanged. */
export function tableValue(sample: MetricSample): string {
  if (sample.name === "cost") return sample.value == null ? "not measured" : String(sample.value);
  if (sample.value == null) return "unknown";
  if (sample.name === "elapsed_attempt_duration") return formatDuration(sample.value);
  return String(sample.value);
}

export interface TableNotes {
  /** Each distinct note once, in first-seen order. */
  footnotes: string[];
  /** The footnote numbers (1-based) for each metric name. */
  refs: Record<string, number[]>;
  /** The short coverage word of each metric, for example "full". */
  coverage: Record<string, string>;
}

/** Split each coverage text into its first word and a note, and number the distinct notes. */
export function tableNotes(samples: MetricSample[]): TableNotes {
  const footnotes: string[] = [];
  const refs: Record<string, number[]> = {};
  const coverage: Record<string, string> = {};
  const noteNumber = (text: string) => {
    const found = footnotes.indexOf(text);
    if (found >= 0) return found + 1;
    footnotes.push(text);
    return footnotes.length;
  };
  for (const sample of samples) {
    const match = /^\s*([a-z]+)\s*(?:[;:,]\s*(.*))?$/i.exec(sample.coverage);
    const word = match?.[1] ?? sample.coverage;
    const rest = match?.[2]?.trim() ?? "";
    coverage[sample.name] = word;
    const notes = [...(rest ? [rest] : []), ...sample.unknown_reasons];
    refs[sample.name] = [...new Set(notes.map(noteNumber))];
  }
  return { footnotes, refs, coverage };
}
