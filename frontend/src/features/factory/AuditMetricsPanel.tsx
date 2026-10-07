import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { ApiHttpError } from "@/lib/api";
import type { AuditEventPage, AuditEventRead, MetricsWindow } from "./auditApi";
import { fetchAuditEvents, fetchMetricsWindow } from "./auditApi";
import { OperatorTokenDialog } from "@/features/agent-teams/AutonomyPanel";
import {
  clearOperatorToken,
  getOperatorToken,
  setOperatorToken,
} from "@/features/agent-teams/operatorAuth";

const labelClass = "block text-sm font-medium";
const PAGE_SIZE = 25;
// C10/C13: the client renders only these named primitive snapshot fields.
// They match the server's typed safe snapshot fields. The response
// snapshot_labels list is only observed keys, never a client allowlist.
const SAFE_SNAPSHOT_FIELDS = [
  "team_display_name",
  "slot_display_name",
  "repo_owner",
  "repo_name",
  "issue_number",
  "pr_number",
  "issue_type",
  "artifact",
  "configured_provider",
  "observed_runtime_provider",
  "github_auth_mode",
  "team_created_at",
  "scope_created_at",
  "scope_updated_at",
  "attempt",
  "launch_attempt",
  "retry_class",
  "fact_source",
] as const;

type AppliedFilters = { teamKey: string; scopeKey: string };
// C13: each retained result keeps the identity of its own successful read.
type MetricsResult = { data: MetricsWindow; filters: AppliedFilters; observedAt: string };
type EventsResult = {
  data: AuditEventPage;
  filters: AppliedFilters;
  page: number;
  observedAt: string;
};
type ReadState = "idle" | "pending" | "failed" | "cancelled";

const NO_FILTERS: AppliedFilters = { teamKey: "", scopeKey: "" };

function sameFilters(left: AppliedFilters, right: AppliedFilters) {
  return left.teamKey === right.teamKey && left.scopeKey === right.scopeKey;
}

function describeFilters(filters: AppliedFilters) {
  return `team ${filters.teamKey || "all"}, scope ${filters.scopeKey || "all"}`;
}

// C15: window bounds are computed at invocation time, never during render.
function windowBounds() {
  const windowEnd = new Date().toISOString();
  const windowStart = new Date(Date.now() - 7 * 24 * 3600 * 1000).toISOString();
  return { windowStart, windowEnd };
}

function retainedReason(state: ReadState, matches: boolean, applied: AppliedFilters) {
  if (state === "pending") return "a newer read is pending";
  if (state === "failed") return "the latest read failed";
  if (state === "cancelled") return "the latest read was cancelled";
  if (!matches) return `it does not match the applied selection (${describeFilters(applied)})`;
  return null;
}

/**
 * P05 audit coverage and delivery metrics view.
 *
 * Keyboard: all controls are native buttons with visible focus rings; the
 * event detail is an inline disclosure with aria-expanded and no focus trap.
 * Status text is announced through role="status". Long names wrap and remain
 * visible.
 */
export function AuditMetricsPage() {
  const [metricsResult, setMetricsResult] = useState<MetricsResult | null>(null);
  const [eventsResult, setEventsResult] = useState<EventsResult | null>(null);
  const [metricsState, setMetricsState] = useState<ReadState>("idle");
  const [eventsState, setEventsState] = useState<ReadState>("idle");
  const [metricsError, setMetricsError] = useState("");
  const [eventsError, setEventsError] = useState("");
  const [expanded, setExpanded] = useState<number | null>(null);
  const [teamKey, setTeamKey] = useState("");
  const [scopeKey, setScopeKey] = useState("");
  const [applied, setApplied] = useState<AppliedFilters>(NO_FILTERS);
  const [status, setStatus] = useState("No audit data loaded yet.");
  const [tokenDialogOpen, setTokenDialogOpen] = useState(false);
  const [tokenInput, setTokenInput] = useState("");
  const [tokenError, setTokenError] = useState<string | null>(null);
  // C13: one coalesced per-tab token request, as in AutonomyPanel.
  const tokenResolverRef = useRef<((value: string | null) => void) | null>(null);
  const tokenPromiseRef = useRef<Promise<string | null> | null>(null);
  // C13: per-invocation epochs. A response publishes only when its invocation
  // epoch and its Apply identity are still current. Filter equality alone is
  // insufficient after an A-to-B-to-A sequence.
  const metricsEpochRef = useRef(0);
  const auditEpochRef = useRef(0);
  const applyEpochRef = useRef(0);

  const requestToken = useCallback((message: string | null = null): Promise<string | null> => {
    const stored = getOperatorToken();
    if (stored) return Promise.resolve(stored);
    if (tokenPromiseRef.current) return tokenPromiseRef.current;
    const pending = new Promise<string | null>((resolve) => {
      tokenResolverRef.current = resolve;
    });
    tokenPromiseRef.current = pending;
    setTokenError(message);
    setTokenDialogOpen(true);
    return pending;
  }, []);

  function settleToken(token: string | null) {
    tokenResolverRef.current?.(token);
    tokenResolverRef.current = null;
    tokenPromiseRef.current = null;
    setTokenDialogOpen(false);
    setTokenInput("");
    setTokenError(null);
  }

  function submitToken() {
    const token = tokenInput.trim();
    if (!token) return;
    setOperatorToken(token);
    settleToken(token);
  }

  // C01: safe metrics load independently and remain usable when protected
  // audit access is refused.
  async function loadMetrics(filters: AppliedFilters, applyId: number = applyEpochRef.current) {
    const epoch = ++metricsEpochRef.current;
    const current = () => epoch === metricsEpochRef.current && applyId === applyEpochRef.current;
    const { windowStart, windowEnd } = windowBounds();
    setMetricsState("pending");
    try {
      const data = await fetchMetricsWindow({
        windowStart,
        windowEnd,
        filterScope: filters.teamKey || filters.scopeKey ? "scoped" : "all",
        teamContextKey: filters.teamKey || undefined,
        scopeContextKey: filters.scopeKey || undefined,
      });
      if (!current()) return;
      setMetricsResult({ data, filters, observedAt: new Date().toISOString() });
      setMetricsState("idle");
      setMetricsError("");
      setStatus("Safe metrics loaded.");
    } catch (cause) {
      if (!current()) return;
      setMetricsState("failed");
      setMetricsError(cause instanceof Error ? cause.message : "Could not load safe metrics.");
    }
  }

  // C01: audit reads use the per-tab operator workflow with the operator
  // credential header. Exact 503 and 401 refusals surface to the operator.
  async function loadAudit(
    filters: AppliedFilters,
    requestedPage: number,
    applyId: number = applyEpochRef.current,
  ) {
    const epoch = ++auditEpochRef.current;
    const current = () => epoch === auditEpochRef.current && applyId === applyEpochRef.current;
    setEventsState("pending");
    const token = await requestToken();
    if (!current()) return;
    if (!token) {
      setEventsState("cancelled");
      setStatus("Audit read cancelled. Safe metrics remain available.");
      return;
    }
    try {
      const data = await fetchAuditEvents({
        page: requestedPage,
        pageSize: PAGE_SIZE,
        teamContextKey: filters.teamKey || undefined,
        scopeContextKey: filters.scopeKey || undefined,
        operatorToken: token,
      });
      if (!current()) return;
      setEventsResult({ data, filters, page: requestedPage, observedAt: new Date().toISOString() });
      setEventsState("idle");
      setEventsError("");
      setStatus(`Loaded ${data.items.length} of ${data.total} audit events.`);
    } catch (cause) {
      // C13: a refused token is never sent again; the next read asks for a
      // replacement. A newer stored token is kept.
      if (cause instanceof ApiHttpError && cause.status === 401 && getOperatorToken() === token) {
        clearOperatorToken();
      }
      if (!current()) return;
      setEventsState("failed");
      setEventsError(cause instanceof Error ? cause.message : "Audit read refused.");
      setStatus("Audit events could not be loaded. Safe metrics remain available.");
    }
  }

  // One applied identity drives both reads so the filters always match.
  async function applyReads(filters: AppliedFilters, requestedPage: number) {
    const applyId = ++applyEpochRef.current;
    await Promise.resolve();
    if (applyId !== applyEpochRef.current) return;
    setApplied(filters);
    await loadMetrics(filters, applyId);
    // A delayed old metrics completion must never start an old audit epoch.
    if (applyId !== applyEpochRef.current) return;
    await loadAudit(filters, requestedPage, applyId);
  }

  useEffect(() => {
    void applyReads(NO_FILTERS, 1);
    // Mount-only load; filters apply through the explicit controls below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // C13: unmount invalidation is explicit. Late responses after unmount can
  // never publish state, and a pending token request settles.
  useEffect(() => () => {
    applyEpochRef.current += 1;
    metricsEpochRef.current += 1;
    auditEpochRef.current += 1;
    tokenResolverRef.current?.(null);
    tokenResolverRef.current = null;
    tokenPromiseRef.current = null;
  }, []);

  const metrics = metricsResult?.data ?? null;
  const events = eventsResult?.data.items ?? [];
  const labels = eventsResult?.data.snapshot_labels ?? [];
  const total = eventsResult?.data.total ?? 0;
  const page = eventsResult?.page ?? 1;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const metricsRetained = metricsResult
    ? retainedReason(metricsState, sameFilters(metricsResult.filters, applied), applied)
    : null;
  const eventsRetained = eventsResult
    ? retainedReason(eventsState, sameFilters(eventsResult.filters, applied), applied)
    : null;
  // C13: paging uses the identity of the rows on screen. It waits while those
  // rows belong to another selection or a read is pending.
  const pagingBlocked = !eventsResult || !sameFilters(eventsResult.filters, applied)
    || eventsState === "pending";

  // C13: only fields named in the client safe-field allowlist render stored
  // values, and only primitive values render.
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
          Terminal tracking, delivery and independent human review are separate metrics.
        </p>
        <p className="text-sm">
          Unknown outcomes are separate from explicit non-delivery. Both are reported with counts and reasons.
        </p>
        <p className="text-sm">
          Coverage starts at the installed instrumentation marker. Earlier intervals stay missing; they are
          never reconstructed. Imported state is labelled as an observed snapshot at the marker time.
        </p>
        <p className="text-sm">
          Ledger events are retained for the life of the database. Deleted resources keep their snapshot
          labels and show unavailable live links.
        </p>
      </section>

      <section aria-labelledby="coverage" className="space-y-2 rounded border p-3">
        <h3 id="coverage" className="font-semibold">Window and coverage</h3>
        {metricsResult && (
          <p className="text-sm text-muted-foreground">
            Showing metrics for {describeFilters(metricsResult.filters)}, observed at {metricsResult.observedAt}.
          </p>
        )}
        {metricsRetained && (
          <p role="status" className="text-sm text-muted-foreground">
            Retained metrics: {metricsRetained}.
          </p>
        )}
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
        {metricsError && <p role="alert" className="text-sm text-destructive">{metricsError}</p>}
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
          Context keys address retained history after deletion. A key without a current resource has no
          present-state population. Both reads use the same applied filters.
        </p>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-sm">
            <span className={labelClass}>Team context key</span>
            <input className="mt-1 w-64 max-w-full rounded-md border bg-background px-3 py-2"
              value={teamKey} onChange={(event) => setTeamKey(event.target.value)} />
          </label>
          <label className="text-sm">
            <span className={labelClass}>Scope context key</span>
            <input className="mt-1 w-64 max-w-full rounded-md border bg-background px-3 py-2"
              value={scopeKey} onChange={(event) => setScopeKey(event.target.value)} />
          </label>
          <Button onClick={() => void applyReads({ teamKey: teamKey.trim(), scopeKey: scopeKey.trim() }, 1)}>
            Apply filters
          </Button>
          <Button variant="outline" onClick={() => void loadMetrics(applied)}>Reload safe metrics</Button>
        </div>
        <p className="text-xs text-muted-foreground">Applied selection: {describeFilters(applied)}.</p>
        {labels.length > 0 && (
          <p className="text-xs text-muted-foreground">Snapshot labels in page: {labels.join(", ")}</p>
        )}
      </section>

      <section aria-labelledby="events" className="space-y-2 rounded border p-3">
        <h3 id="events" className="font-semibold">Audit events</h3>
        {eventsResult && (
          <p className="text-sm text-muted-foreground">
            Showing events for {describeFilters(eventsResult.filters)}, page {eventsResult.page}, observed
            at {eventsResult.observedAt}.
          </p>
        )}
        {eventsRetained && (
          <p role="status" className="text-sm text-muted-foreground">
            Retained events: {eventsRetained}.
          </p>
        )}
        {eventsError && <p role="alert" className="text-sm text-destructive">{eventsError}</p>}
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
                    <tr>
                      <td colSpan={7} className="bg-muted/40 p-3">
                        <dl className="grid grid-cols-1 gap-1 text-xs sm:grid-cols-2">
                          <div><span className={labelClass}>Source</span>{event.source}</div>
                          <div><span className={labelClass}>Record kind</span>{event.record_kind}</div>
                          <div><span className={labelClass}>Fact source</span>{event.fact_source ?? "unavailable"}</div>
                          <div><span className={labelClass}>Fact time</span>{event.fact_time ?? "unavailable"}</div>
                          <div><span className={labelClass}>Actor reference</span>{event.actor_reference ?? "none"}</div>
                          <div><span className={labelClass}>Reason</span>{event.sanitized_reason ?? "none"}</div>
                          <div><span className={labelClass}>Completion kind</span>{event.completion_kind ?? "null"}</div>
                          <div><span className={labelClass}>Revision</span>{event.revision_id ?? "none"}</div>
                          <div className="sm:col-span-2">
                            <span className={labelClass}>Context keys</span>
                            team {event.team_context_key ?? "none"}; scope {event.scope_context_key ?? "none"};
                            item {event.item_context_key ?? "none"}
                          </div>
                          <div className="sm:col-span-2">
                            <span className={labelClass}>Stored snapshot labels</span>
                            {namedSnapshotValues(event).length
                              ? namedSnapshotValues(event).map(({ name, text }) => (
                                  <div key={name} className="break-words">{name}: {text}</div>
                                ))
                              : "none named in this event"}
                          </div>
                          <div className="sm:col-span-2 break-words">
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
          <Button variant="outline" disabled={pagingBlocked || page <= 1}
            onClick={() => eventsResult && void loadAudit(eventsResult.filters, eventsResult.page - 1)}>
            Previous page
          </Button>
          <p className="text-sm">Page {page} of {pageCount}</p>
          <Button variant="outline" disabled={pagingBlocked || page >= pageCount}
            onClick={() => eventsResult && void loadAudit(eventsResult.filters, eventsResult.page + 1)}>
            Next page
          </Button>
        </div>
      </section>

      <p className="text-sm">Total audit events matching filters: {total}</p>
      <OperatorTokenDialog
        open={tokenDialogOpen}
        value={tokenInput}
        error={tokenError}
        onValueChange={setTokenInput}
        onSubmit={submitToken}
        onCancel={() => settleToken(null)}
      />
      <p role="status" className="text-sm">{status}</p>
    </section>
  );
}
