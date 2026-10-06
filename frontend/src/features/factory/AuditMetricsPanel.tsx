import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  AuditEventRead,
  MetricsWindow,
  fetchAuditEvents,
  fetchMetricsWindow,
} from "./auditApi";

const labelClass = "block text-sm font-medium";

/**
 * P05 audit coverage and delivery metrics view.
 *
 * Keyboard: all controls are native buttons with visible focus rings; the
 * event detail is an inline disclosure with aria-expanded and no focus trap.
 * Status text is announced through role="status". Long names wrap and remain
 * visible. Dialog-free layout keeps dismissal and restoration trivial.
 */
export function AuditMetricsPage() {
  const [metrics, setMetrics] = useState<MetricsWindow | null>(null);
  const [events, setEvents] = useState<AuditEventRead[]>([]);
  const [labels, setLabels] = useState<string[]>([]);
  const [total, setTotal] = useState(0);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [teamKey, setTeamKey] = useState("");
  const [scopeKey, setScopeKey] = useState("");
  const [status, setStatus] = useState("No audit data loaded yet.");
  const [error, setError] = useState("");

  const windowEnd = new Date().toISOString();
  const windowStart = new Date(Date.now() - 7 * 24 * 3600 * 1000).toISOString();

  async function loadAll() {
    setError("");
    setStatus("Loading audit coverage and metrics.");
    try {
      const [windowData, page] = await Promise.all([
        fetchMetricsWindow({ windowStart, windowEnd, filterScope: "all" }),
        fetchAuditEvents({
          page: 1,
          pageSize: 25,
          teamContextKey: teamKey || undefined,
          scopeContextKey: scopeKey || undefined,
        }),
      ]);
      setMetrics(windowData);
      setEvents(page.items);
      setLabels(page.snapshot_labels);
      setTotal(page.total);
      setStatus(`Loaded ${page.items.length} of ${page.total} audit events.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load audit data.");
      setStatus("Audit data could not be loaded.");
    }
  }

  useEffect(() => {
    void loadAll();
    // Mount-only load; filters apply through the explicit button below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <section className="space-y-6 p-4">
      <header>
        <h2 className="text-xl font-semibold">Audit coverage and delivery metrics</h2>
        <p className="text-sm text-muted-foreground">
          These aggregates never fetch fresh external facts and never change any record.
        </p>
      </header>

      <section aria-labelledby="explanations" className="space-y-2 rounded border p-3">
        <h3 id="explanations" className="font-semibold">How to read these numbers</h3>
        <p className="text-sm">
          Terminal tracking is not delivery. A closed item without result evidence counts as unknown.
        </p>
        <p className="text-sm">
          Unknown outcomes are separate from explicit non-delivery. Both are reported with counts and reasons.
        </p>
        <p className="text-sm">
          Historical attribution uses recorded event facts and context snapshots. Imported state is labelled
          as an observed snapshot at import time.
        </p>
        <p className="text-sm">
          Ledger events are retained for the life of the database. Deleted resources keep their snapshot
          labels and show unavailable live links.
        </p>
      </section>

      <section aria-labelledby="coverage" className="space-y-2 rounded border p-3">
        <h3 id="coverage" className="font-semibold">Window and coverage</h3>
        {metrics ? (
          <dl className="grid grid-cols-1 gap-1 text-sm sm:grid-cols-2">
            <div><span className={labelClass}>Requested window</span>{metrics.window_start} to {metrics.window_end}</div>
            <div><span className={labelClass}>Filter scope</span>{metrics.filter_scope}</div>
            <div><span className={labelClass}>Instrumentation start</span>{metrics.instrumentation_start ?? "unavailable"}</div>
            <div><span className={labelClass}>Available interval</span>
              {metrics.available_interval_start ?? "unavailable"} to {metrics.available_interval_end ?? "unavailable"}
            </div>
            <div className="sm:col-span-2">
              <span className={labelClass}>Missing intervals</span>
              {metrics.missing_intervals.length ? metrics.missing_intervals.join(", ") : "none recorded"}
            </div>
            <div className="sm:col-span-2"><span className={labelClass}>Counting unit</span>{metrics.counting_unit_note}</div>
          </dl>
        ) : (
          <p className="text-sm">No window loaded.</p>
        )}
      </section>

      <section aria-labelledby="metrics" className="space-y-2 rounded border p-3">
        <h3 id="metrics" className="font-semibold">Metrics</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left">
                <th className="p-2">Metric</th>
                <th className="p-2">Unit</th>
                <th className="p-2">Value</th>
                <th className="p-2">Samples</th>
                <th className="p-2">Unknown</th>
                <th className="p-2">Excluded</th>
                <th className="p-2">Source</th>
                <th className="p-2">Coverage</th>
              </tr>
            </thead>
            <tbody>
              {(metrics?.metrics ?? []).map((sample) => (
                <tr key={sample.name} className="border-t align-top">
                  <td className="p-2 break-words">{sample.name}</td>
                  <td className="p-2 break-words">{sample.counting_unit}</td>
                  <td className="p-2">{sample.value === null ? "unknown" : sample.value}</td>
                  <td className="p-2">{sample.sample_count}</td>
                  <td className="p-2">
                    {sample.unknown_count}
                    {sample.unknown_reasons.length > 0 && (
                      <div className="text-xs text-muted-foreground">{sample.unknown_reasons.join("; ")}</div>
                    )}
                  </td>
                  <td className="p-2">{sample.excluded_count}</td>
                  <td className="p-2 break-words">{sample.source}</td>
                  <td className="p-2 break-words">{sample.coverage}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section aria-labelledby="filters" className="space-y-2 rounded border p-3">
        <h3 id="filters" className="font-semibold">Historical filters</h3>
        <p className="text-sm">
          Context keys address retained history after deletion. Current-id filters resolve the current
          resource context key.
        </p>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-sm">
            <span className={labelClass}>Team context key</span>
            <input className="mt-1 w-64 rounded-md border bg-background px-3 py-2"
              value={teamKey} onChange={(event) => setTeamKey(event.target.value)} />
          </label>
          <label className="text-sm">
            <span className={labelClass}>Scope context key</span>
            <input className="mt-1 w-64 rounded-md border bg-background px-3 py-2"
              value={scopeKey} onChange={(event) => setScopeKey(event.target.value)} />
          </label>
          <Button onClick={() => void loadAll()}>Apply filters</Button>
        </div>
        {labels.length > 0 && (
          <p className="text-xs text-muted-foreground">Snapshot labels in page: {labels.join(", ")}</p>
        )}
      </section>

      <section aria-labelledby="events" className="space-y-2 rounded border p-3">
        <h3 id="events" className="font-semibold">Audit events</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left">
                <th className="p-2">Occurred</th>
                <th className="p-2">Kind</th>
                <th className="p-2">Actor</th>
                <th className="p-2">Action</th>
                <th className="p-2">Delivery</th>
                <th className="p-2">Live links</th>
                <th className="p-2">Detail</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.id} className="border-t align-top">
                  <td className="p-2">{event.occurred_at}</td>
                  <td className="p-2 break-words">{event.event_kind}</td>
                  <td className="p-2 break-words">{event.actor_kind}</td>
                  <td className="p-2">{event.action_outcome ?? "unknown"}</td>
                  <td className="p-2">{event.delivery_outcome ?? "null"}</td>
                  <td className="p-2">{event.live_links_available ? "available" : "unavailable"}</td>
                  <td className="p-2">
                    <Button variant="outline" aria-expanded={expanded === event.id}
                      onClick={() => setExpanded(expanded === event.id ? null : event.id)}>
                      {expanded === event.id ? "Hide detail" : "Show detail"}
                    </Button>
                  </td>
                  {expanded === event.id && (
                    <tr>
                      <td colSpan={7} className="bg-muted/40 p-3">
                        <dl className="grid grid-cols-1 gap-1 text-xs sm:grid-cols-2">
                          <div><span className={labelClass}>Source</span>{event.source}</div>
                          <div><span className={labelClass}>Record kind</span>{event.record_kind}</div>
                          <div><span className={labelClass}>Fact source</span>{event.fact_source ?? "unavailable"}</div>
                          <div><span className={labelClass}>Fact time</span>{event.fact_time ?? "unavailable"}</div>
                          <div><span className={labelClass}>Reason</span>{event.sanitized_reason ?? "none"}</div>
                          <div><span className={labelClass}>Completion kind</span>{event.completion_kind ?? "null"}</div>
                          <div className="sm:col-span-2">
                            <span className={labelClass}>Context keys</span>
                            team {event.team_context_key ?? "none"}; scope {event.scope_context_key ?? "none"};
                            item {event.item_context_key ?? "none"}
                          </div>
                          <div className="sm:col-span-2">
                            <span className={labelClass}>Before / after (allowlisted)</span>
                            {JSON.stringify(event.before_values ?? {})} → {JSON.stringify(event.after_values ?? {})}
                          </div>
                        </dl>
                      </td>
                    </tr>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <p role="status" className="text-sm">{status}</p>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </section>
  );
}
