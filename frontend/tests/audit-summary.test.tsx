import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { AuditSummary } from "../src/features/factory/AuditSummary";
import type { MetricSample, MetricsWindow } from "../src/features/factory/auditApi";
import {
  coverageSentence,
  formatDuration,
  headlines,
  metricLabel,
  tableNotes,
  tableValue,
} from "../src/features/factory/auditSummary";

function sample(name: string, value: number | null, overrides: Partial<MetricSample> = {}): MetricSample {
  return {
    name, counting_unit: "tracked_attempts", value, sample_count: value ?? 0, unknown_count: 0, excluded_count: 0,
    unknown_reasons: [], source: "factory_audit_events", coverage: "full", ...overrides,
  };
}

function metricsWindow(overrides: Partial<MetricsWindow> = {}, samples: MetricSample[] = []): MetricsWindow {
  return {
    window_start: "2026-10-06T08:58:01.957644Z", window_end: "2026-10-13T08:58:01.957644Z", filter_scope: "all",
    counting_unit_note: "note", instrumentation_start: "2026-10-11T09:22:29.365000Z",
    available_interval_start: "2026-10-11T09:22:29.365000Z", available_interval_end: "2026-10-13T08:58:01.957644Z",
    missing_intervals: ["2026-10-06T08:58:01.957644Z/2026-10-11T09:22:29.365000Z: before instrumentation start"],
    metrics: samples, ...overrides,
  };
}

const FULL = [
  sample("delivered_in_window", 2),
  sample("merged_code_in_window", 2),
  sample("delivered_design_in_window", 0),
  sample("closed_without_delivery", 0),
  sample("unknown_outcomes", 0),
  sample("elapsed_attempt_duration", 10181.0607665),
  sample("operator_interventions", 20),
  sample("recovery_success", 1),
  sample("implementation_retries", 0),
  sample("diagnostic_retries", 0),
  sample("cost", null, { coverage: "unknown", unknown_reasons: ["no measured usage attribution"] }),
];

describe("formatDuration", () => {
  it("never shows raw seconds", () => {
    expect(formatDuration(10181.0607665)).toBe("2 h 50 min");
    expect(formatDuration(20)).toBe("under 1 min");
    expect(formatDuration(59 * 60)).toBe("59 min");
    expect(formatDuration(2 * 3600)).toBe("2 h");
    expect(formatDuration(3 * 86400 + 4 * 3600)).toBe("3 d 4 h");
    expect(formatDuration(Number.NaN)).toBe("unknown");
  });
});

describe("coverageSentence", () => {
  it("says when recording started and how many days of the window have no data", () => {
    expect(coverageSentence(metricsWindow())).toMatch(/^Recording started .*2026\. The first 5 days of this window have no data\.$/);
  });

  it("says the whole window has data when recording started before it", () => {
    const early = metricsWindow({ available_interval_start: "2026-10-06T08:58:01.957644Z" });
    expect(coverageSentence(early)).toMatch(/The whole window has data\.$/);
  });

  it("counts hours for a short gap, and handles no marker or no interval", () => {
    const short = metricsWindow({ available_interval_start: "2026-10-06T14:58:01.957644Z" });
    expect(coverageSentence(short)).toMatch(/The first 6 hours of this window have no data\.$/);
    expect(coverageSentence(metricsWindow({ instrumentation_start: null }))).toBe("Recording has not started. This window has no data.");
    expect(coverageSentence(metricsWindow({ available_interval_start: null }))).toMatch(/This window has no data\.$/);
    expect(coverageSentence(null)).toBe("Coverage is not loaded yet.");
  });

  it("shows no ISO time and no interval notation", () => {
    expect(coverageSentence(metricsWindow())).not.toMatch(/\d{4}-\d{2}-\d{2}T|\d{2}:\d{2}:\d{2}/);
  });
});

describe("headlines", () => {
  it("states the results in plain words", () => {
    const results = Object.fromEntries(headlines(metricsWindow({}, FULL)).map((entry) => [entry.id, entry]));
    expect(results.delivered).toMatchObject({ value: "2", detail: "2 code PRs merged, 0 design" });
    expect(results.duration.value).toBe("2 h 50 min");
    expect(results.interventions.value).toBe("20");
    expect(results.recoveries.value).toBe("1");
    expect(results.retries).toMatchObject({ value: "0", detail: "0 implementation, 0 diagnostic" });
    expect(results.cost.value).toBe("not measured");
  });

  it("reads unknown, never 0, for a null or a missing value", () => {
    const results = Object.fromEntries(headlines(metricsWindow({}, [
      sample("delivered_in_window", null), sample("implementation_retries", 1), sample("diagnostic_retries", null),
    ])).map((entry) => [entry.id, entry]));
    expect(results.delivered.value).toBe("unknown");
    expect(results.delivered.detail).toBe("unknown code PRs merged, unknown design");
    expect(results.closed.value).toBe("unknown");
    expect(results.duration.value).toBe("unknown");
    expect(results.retries.value).toBe("unknown");
    expect(headlines(null)).toEqual([]);
  });

  it("gives every headline a definition", () => {
    for (const entry of headlines(metricsWindow({}, FULL))) expect(entry.help.length, entry.id).toBeGreaterThan(20);
  });
});

describe("technical table helpers", () => {
  it("keeps the values and formats only the duration and the missing ones", () => {
    expect(tableValue(sample("delivered_in_window", 3))).toBe("3");
    expect(tableValue(sample("delivered_in_window", 0))).toBe("0");
    expect(tableValue(sample("delivered_in_window", null))).toBe("unknown");
    expect(tableValue(sample("elapsed_attempt_duration", 10181.0607665))).toBe("2 h 50 min");
    expect(tableValue(sample("cost", null))).toBe("not measured");
  });

  it("writes each distinct note once", () => {
    const note = "part of the requested window precedes instrumentation start";
    const notes = tableNotes([
      sample("a", 1, { coverage: `partial; ${note}` }),
      sample("b", 2, { coverage: `partial; ${note}` }),
      sample("c", 3, { coverage: "full", unknown_reasons: ["no result evidence"] }),
    ]);
    expect(notes.footnotes).toEqual([note, "no result evidence"]);
    expect(notes.refs).toEqual({ a: [1], b: [1], c: [2] });
    expect(notes.coverage).toEqual({ a: "partial", b: "partial", c: "full" });
  });

  it("labels a metric in plain words and falls back for an unknown code", () => {
    expect(metricLabel("operator_interventions")).toBe("Director interventions");
    expect(metricLabel("brand_new_metric")).toBe("brand new metric");
  });
});

describe("AuditSummary", () => {
  it("shows the coverage sentence first, then every headline", () => {
    render(<AuditSummary metrics={metricsWindow({}, FULL)} />);
    const region = screen.getByRole("region", { name: "Delivery in this window" });
    expect(within(region).getByText(/The first 5 days of this window have no data\./)).toBeInTheDocument();
    for (const label of ["Delivered", "Closed without delivery", "Outcome unknown", "Median time from dispatch to finish",
      "Director interventions", "Recoveries that succeeded", "Retries charged", "Cost"]) {
      expect(within(region).getByText(label)).toBeInTheDocument();
    }
    expect(within(region).getByText("2 h 50 min")).toBeInTheDocument();
    expect(within(region).getByText("not measured")).toBeInTheDocument();
    expect(region.textContent).not.toMatch(/\d{4}-\d{2}-\d{2}T|\bnull\b|[a-z]+_[a-z_]+/);
  });

  it("opens and closes a definition with its button", () => {
    render(<AuditSummary metrics={metricsWindow({}, FULL)} />);
    const button = screen.getByRole("button", { name: "About: Cost" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/no measured usage attribution, so it reports no cost/)).toBeInTheDocument();
    fireEvent.click(button);
    expect(screen.queryByText(/no measured usage attribution, so it reports no cost/)).not.toBeInTheDocument();
  });

  it("says that nothing is loaded yet", () => {
    render(<AuditSummary metrics={null} />);
    expect(screen.getByText("No results loaded yet.")).toBeInTheDocument();
    expect(screen.getByText("Coverage:").parentElement?.textContent).toContain("Coverage is not loaded yet.");
  });
});
