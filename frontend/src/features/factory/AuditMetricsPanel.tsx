import { Fragment, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import type { AuditEventRead, MetricsWindow } from "./auditApi";
import { fetchAuditEvents, fetchMetricsWindow } from "./auditApi";
import { OperatorTokenDialog } from "@/features/agent-teams/AutonomyPanel";
import { getOperatorToken } from "@/features/agent-teams/operatorAuth";

const labelClass = "block text-sm font-medium";
const PAGE_SIZE = 25;
// C13: a client-side named safe-field allowlist. The response snapshot_labels
// list is only observed keys, never a client allowlist. Only fields named here
// render their stored values, and primitives only.
const SAFE_SNAPSHOT_FIELDS = [
  "team_display_name",
  "repo_owner",
  "repo_name",
  "issue_number",
  "pr_number",
  "issue_type",
] as const;

type AppliedFilters = { teamKey: string; scopeKey: string };

// C15: window bounds are computed at invocation time, never during render.
function windowBounds() {
  const windowEnd = new Date().toISOString();
  const windowStart = new Date(Date.now() - 7 * 24 * 3600 * 1000).toISOString();
  return { windowStart, windowEnd };
}

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
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [teamKey, setTeamKey] = useState("");
  const [scopeKey, setScopeKey] = useState("");
  const [appliedFilters, setAppliedFilters] = useState<AppliedFilters>({ teamKey: "", scopeKey: "" });
  const [status, setStatus] = useState("No audit data loaded yet.");
  const [error, setError] = useState("");
  const [metricsStale, setMetricsStale] = useState(false);
  const [eventsStale, setEventsStale] = useState(false);
  const [metricsObservedAt, setMetricsObservedAt] = useState<string | null>(null);
  const [eventsObservedAt, setEventsObservedAt] = useState<string | null>(null);
  const [tokenDialogOpen, setTokenDialogOpen] = useState(false);
  const [tokenInput, setTokenInput] = useState("");
  const [tokenError, setTokenError] = useState("");
  const [operatorToken, setOperatorToken] = useState("");
  // C15: a stable ref, not a per-render object.
  const tokenResolverRef = useRef<((value: string | null) => void) | null>(null);
  // C13: per-invocation epochs. A response publishes only when its invocation
  // epoch is still current. Filter equality alone is insufficient: an old A
  // response after an A-to-B-to-A sequence must be rejected by epoch.
  const metricsEpochRef = useRef(0);
  const auditEpochRef = useRef(0);
  // C13: one Apply invocation identity is captured before any await. A newer
  // Apply invalidates older metric and audit publications, including audits
  // still waiting behind an old metrics completion.
  const applyEpochRef = useRef(0);

  function requestOperatorToken(): Promise<string | null> {
    setTokenError("");
    setTokenDialogOpen(true);
    return new Promise((resolve) => {
      tokenResolverRef.current = resolve;
    });
  }

  function settleOperatorToken(value: string | null) {
    if (value) setOperatorToken(value);
    tokenResolverRef.current?.(value);
    tokenResolverRef.current = null;
    setTokenDialogOpen(false);
    setTokenInput("");
    setTokenError("");
  }

  // C01: safe metrics load independently and remain usable when protected
  // audit access is refused.
  async function loadMetrics(filters: AppliedFilters, applyId: number = applyEpochRef.current) {
    const epoch = ++metricsEpochRef.current;
    // Root2976: every read invocation captures the current Apply identity and
    // always compares it. A newer Apply invalidates standalone reads too.
    const current = () => epoch === metricsEpochRef.current && applyId === applyEpochRef.current;
    const { windowStart, windowEnd } = windowBounds();
    try {
      const windowData = await fetchMetricsWindow({
        windowStart,
        windowEnd,
        filterScope: "all",
        teamContextKey: filters.teamKey || undefined,
        scopeContextKey: filters.scopeKey || undefined,
      });
      if (!current()) return;
      setMetrics(windowData);
      setMetricsStale(false);
      setMetricsObservedAt(new Date().toISOString());
      setStatus("Safe metrics loaded.");
    } catch (cause) {
      if (!current()) return;
      // C13: retained data is labelled stale, never presented as a fresh read.
      setMetricsStale(true);
      setError(cause instanceof Error ? cause.message : "Could not load safe metrics.");
    }
  }

  // C01: audit reads use the per-tab operator workflow with the operator
  // credential header. Exact 503 and 401 refusals surface to the operator.
  async function loadAudit(filters: AppliedFilters, requestedPage: number, applyId: number = applyEpochRef.current) {
    const epoch = ++auditEpochRef.current;
    // Root2976: pagination, reload and token flows share the Apply identity
    // gate while keeping their independent read epochs.
    const current = () => epoch === auditEpochRef.current && applyId === applyEpochRef.current;
    const token = getOperatorToken() || operatorToken || await requestOperatorToken();
    if (!current()) return;
    if (!token) {
      setStatus("Audit read cancelled. Safe metrics remain available.");
      return;
    }
    try {
      const result = await fetchAuditEvents({
        page: requestedPage,
        pageSize: PAGE_SIZE,
        teamContextKey: filters.teamKey || undefined,
        scopeContextKey: filters.scopeKey || undefined,
        operatorToken: token,
      });
      if (!current()) return;
      setEvents(result.items);
      setLabels(result.snapshot_labels);
      setTotal(result.total);
      setPage(requestedPage);
      setEventsStale(false);
      setEventsObservedAt(new Date().toISOString());
      setStatus(`Loaded ${result.items.length} of ${result.total} audit events.`);
    } catch (cause) {
      if (!current()) return;
      setEventsStale(true);
      setError(cause instanceof Error ? cause.message : "Audit read refused.");
      setStatus("Audit events could not be loaded. Safe metrics remain available.");
    }
  }

  // One applied identity drives both reads so the filters always match.
  async function applyReads(filters: AppliedFilters, requestedPage: number) {
    const applyId = ++applyEpochRef.current;
    await Promise.resolve();
    if (applyId !== applyEpochRef.current) return;
    setError("");
    setAppliedFilters(filters);
    await loadMetrics(filters, applyId);
    // A delayed old metrics completion must never start an old audit epoch.
    if (applyId !== applyEpochRef.current) return;
    await loadAudit(filters, requestedPage, applyId);
  }

  useEffect(() => {
    void applyReads({ teamKey: "", scopeKey: "" }, 1);
    // Mount-only load; filters apply through the explicit controls below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // C13: unmount invalidation is explicit. Late responses after unmount can
  // never publish state, and a newer Apply supersedes older publications.
  useEffect(() => () => {
    applyEpochRef.current += 1;
    metricsEpochRef.current += 1;
    auditEpochRef.current += 1;
  }, []);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  // C13: only fields named in the client safe-field allowlist render stored
  // values, and only primitive values render. Arbitrary snapshot objects and
  // observed-but-unnamed keys are never rendered.
  function namedSnapshotValues(event: AuditEventRead) {
    const snapshot = event.context_snapshot ?? {};
    return (SAFE_SNAPSHOT_FIELDS as readonly string[])
      .filter((name) => name in snapshot)
      .map((name) => {
        const value = snapshot[name];
        const text = typeof value === "string" || typeof value === "number" || typeof value === "boolean"
          ? String(value)
          : "unavailable";
        return { name, text };
      });
  }

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
        {metricsStale && (
          <p role="status" className="text-sm text-muted-foreground">
            Stale metrics retained from {metricsObservedAt ?? "an earlier read"}. The latest metrics read failed.
          </p>
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
          resource context key. Both reads use the same applied filters.
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
          <Button onClick={() => void applyReads({ teamKey: teamKey.trim(), scopeKey: scopeKey.trim() }, 1)}>Apply filters</Button>
          <Button variant="outline" onClick={() => void loadMetrics(appliedFilters)}>Reload safe metrics</Button>
        </div>
        {labels.length > 0 && (
          <p className="text-xs text-muted-foreground">Snapshot labels in page: {labels.join(", ")}</p>
        )}
      </section>

      <section aria-labelledby="events" className="space-y-2 rounded border p-3">
        <h3 id="events" className="font-semibold">Audit events</h3>
        {eventsStale && (
          <p role="status" className="text-sm text-muted-foreground">
            Stale event list retained from {eventsObservedAt ?? "an earlier read"}. The latest audit read failed.
          </p>
        )}
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
                <Fragment key={event.id}>
                <tr className="border-t align-top">
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
                </tr>
                {expanded === event.id && (
                    <tr key={`${event.id}-detail`}>
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
                            <span className={labelClass}>Stored snapshot labels</span>
                            {namedSnapshotValues(event).length
                              ? namedSnapshotValues(event).map(({ name, text }) => (
                                  <div key={name}>{name}: {text}</div>
                                ))
                              : "none named in this page"}
                          </div>
                          <div className="sm:col-span-2">
                            <span className={labelClass}>Before / after (allowlisted)</span>
                            {JSON.stringify(event.before_values ?? {})} → {JSON.stringify(event.after_values ?? {})}
                          </div>
                        </dl>
                      </td>
                    </tr>
                )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="outline" disabled={page <= 1}
            onClick={() => void loadAudit(appliedFilters, page - 1)}>Previous page</Button>
          <p className="text-sm">Page {page} of {pageCount}</p>
          <Button variant="outline" disabled={page >= pageCount}
            onClick={() => void loadAudit(appliedFilters, page + 1)}>Next page</Button>
        </div>
      </section>

      <p className="text-sm">Total audit events matching filters: {total}</p>
      <OperatorTokenDialog
        open={tokenDialogOpen}
        value={tokenInput}
        error={tokenError}
        onValueChange={setTokenInput}
        onSubmit={() => settleOperatorToken(tokenInput)}
        onCancel={() => settleOperatorToken(null)}
      />
      <p role="status" className="text-sm">{status}</p>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </section>
  );
}
