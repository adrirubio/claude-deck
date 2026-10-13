import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { formatServerTime } from "@/lib/serverTime";
import { ApiHttpError } from "@/lib/api";
import type { AuditEventPage, AuditEventRead, MetricsWindow } from "./auditApi";
import type { ContextKeyList } from "./auditApi";
import { fetchAuditEvents, fetchContextKeys, fetchMetricsWindow } from "./auditApi";
import { WINDOW_OPTIONS, filterOptions, isNoEventKey, windowBounds, type WindowId } from "./auditFilters";
import { groupRefusals, type RefusalGroup } from "./auditRefusals";
import { NeedsALookPanel, type RefusalReadState } from "./NeedsALookPanel";
import { fetchAgentMailTeam } from "@/features/agent-mail/api";
import { fetchAgentTeamPresets } from "@/features/agent-teams/api";
import { ActivityFeed } from "./ActivityFeed";
import { AuditSummary } from "./AuditSummary";
import { metricLabel, tableNotes, tableValue } from "./auditSummary";
import { buildFeed } from "./auditFeed";
import { OperatorTokenDialog } from "@/features/agent-teams/AutonomyPanel";
import {
  clearOperatorToken,
  getOperatorToken,
  setOperatorToken,
} from "@/features/agent-teams/operatorAuth";

const labelClass = "block text-sm font-medium";
const PAGE_SIZE = 25;
// #520: the refusal read takes at most this many pages of REFUSAL_PAGE_SIZE
// request events, newest first. The panel says so when the cap stops it.
const REFUSAL_PAGE_SIZE = 100;
const REFUSAL_MAX_PAGES = 5;
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
  // A20/A32/T05: native runtime evidence, exact versions, source times and
  // original typed identities.
  "runtime_provider_evidence",
  "claimed_runtime_provider",
  "artifact_version",
  "pull_closed_at",
  "issue_closed_at",
  "original_team_id",
  "original_scope_id",
  "original_item_id",
  "original_slot_id",
  "item_created_at",
  "slot_created_at",
] as const;

type AppliedFilters = { teamKey: string; scopeKey: string; windowId: WindowId };
// C13: each retained result keeps the identity of its own successful read.
type MetricsResult = { data: MetricsWindow; filters: AppliedFilters; observedAt: string };
type EventsResult = {
  data: AuditEventPage;
  filters: AppliedFilters;
  page: number;
  observedAt: string;
};
type ReadState = "idle" | "pending" | "failed" | "cancelled" | "locked";
type RefusalResult = { groups: RefusalGroup[]; truncated: boolean };
// #520: "Show events" narrows the events table to the refused requests of one item.
type EventFocus = { itemContextKey: string; label: string };

const NO_FILTERS: AppliedFilters = { teamKey: "", scopeKey: "", windowId: "last7" };

function sameFilters(left: AppliedFilters, right: AppliedFilters) {
  return left.teamKey === right.teamKey && left.scopeKey === right.scopeKey && left.windowId === right.windowId;
}

type FilterNames = { team: (key: string) => string; scope: (key: string) => string };

// #516: the page names the choice. It never shows a context key.
function describeFilters(filters: AppliedFilters, names: FilterNames) {
  const team = filters.teamKey ? names.team(filters.teamKey) : "all";
  const scope = filters.scopeKey ? names.scope(filters.scopeKey) : "all";
  const window = WINDOW_OPTIONS.find((option) => option.id === filters.windowId)?.label ?? "";
  return `team ${team}, scope ${scope}${filters.windowId === "last7" ? "" : `, ${window.toLowerCase()}`}`;
}

function retainedReason(state: ReadState, matches: boolean, applied: AppliedFilters, names: FilterNames) {
  if (state === "pending") return "a newer read is pending";
  if (state === "failed") return "the latest read failed";
  if (!matches) return `it does not match the applied selection (${describeFilters(applied, names)})`;
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
  // #515: true after the API refused the Director key. The page then offers Unlock events again.
  const [eventsRefused, setEventsRefused] = useState(false);
  // #515: true from the Unlock click until that read ends. The locked box stays, so focus keeps its button.
  const [unlocking, setUnlocking] = useState(false);
  const [metricsError, setMetricsError] = useState("");
  const [eventsError, setEventsError] = useState("");
  const [refusalResult, setRefusalResult] = useState<RefusalResult | null>(null);
  const [refusalState, setRefusalState] = useState<RefusalReadState>("loading");
  const [memberNames, setMemberNames] = useState<Record<number, string>>({});
  const [teamNames, setTeamNames] = useState<Record<number, string>>({});
  const [focus, setFocus] = useState<EventFocus | null>(null);
  const [contextKeys, setContextKeys] = useState<ContextKeyList | null>(null);
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
  const refusalEpochRef = useRef(0);
  const focusRef = useRef<EventFocus | null>(null);
  const applyEpochRef = useRef(0);

  // R11: focus returns to the invoking control, or to Apply filters, after
  // the token dialog closes by Escape, Cancel or submission.
  const focusReturnRef = useRef<HTMLElement | null>(null);
  const teamSelectRef = useRef<HTMLSelectElement | null>(null);
  const instrumentationRef = useRef<string | null>(null);
  const optionsLoadedRef = useRef(false);
  const dialogWasOpenRef = useRef(false);

  const requestToken = useCallback((message: string | null = null): Promise<string | null> => {
    const stored = getOperatorToken();
    if (stored) return Promise.resolve(stored);
    if (tokenPromiseRef.current) return tokenPromiseRef.current;
    const active = document.activeElement;
    focusReturnRef.current = active instanceof HTMLElement && active !== document.body ? active : null;
    const pending = new Promise<string | null>((resolve) => {
      tokenResolverRef.current = resolve;
    });
    tokenPromiseRef.current = pending;
    setTokenError(message);
    setTokenDialogOpen(true);
    return pending;
  }, []);

  useEffect(() => {
    if (tokenDialogOpen) {
      dialogWasOpenRef.current = true;
      return;
    }
    if (!dialogWasOpenRef.current) return;
    dialogWasOpenRef.current = false;
    // Runs after the dialog's own unmount focus handling.
    const timer = window.setTimeout(() => {
      const preferred = focusReturnRef.current;
      const target = preferred && preferred.isConnected ? preferred : teamSelectRef.current;
      focusReturnRef.current = null;
      target?.focus();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [tokenDialogOpen]);

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
    const { windowStart, windowEnd } = windowBounds(filters.windowId, instrumentationRef.current, Date.now());
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
      instrumentationRef.current = data.instrumentation_start ?? null;
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
    ask = false,
  ): Promise<string | null> {
    const epoch = ++auditEpochRef.current;
    const current = () => epoch === auditEpochRef.current && applyId === applyEpochRef.current;
    // #515: the key dialog opens only when the Director chooses Unlock events.
    if (!ask && !getOperatorToken()) {
      setUnlocking(false);
      // #659: no key, so no protected rows, labels or counts stay on the page.
      setEventsResult(null);
      setEventsState("locked");
      setEventsError("");
      setStatus("Audit events are locked. Safe metrics remain available.");
      return null;
    }
    setEventsState("pending");
    const token = await requestToken();
    if (!current()) return null;
    if (!token) {
      setUnlocking(false);
      setEventsResult(null);
      setEventsState("cancelled");
      setStatus("Audit read cancelled. Safe metrics remain available.");
      return null;
    }
    try {
      const data = await fetchAuditEvents({
        page: requestedPage,
        pageSize: PAGE_SIZE,
        occurredAfter: windowBounds(filters.windowId, instrumentationRef.current, Date.now()).windowStart,
        eventKind: focusRef.current ? "continuation_request" : undefined,
        itemContextKey: focusRef.current?.itemContextKey,
        teamContextKey: filters.teamKey || undefined,
        scopeContextKey: filters.scopeKey || undefined,
        operatorToken: token,
      });
      if (!current()) return token;
      setEventsResult({ data, filters, page: requestedPage, observedAt: new Date().toISOString() });
      setEventsState("idle");
      setUnlocking(false);
      setEventsRefused(false);
      setEventsError("");
      setStatus(`Loaded ${data.items.length} of ${data.total} audit events.`);
      return token;
    } catch (cause) {
      // C13: a refused token is never sent again; the next read asks for a
      // replacement. A newer stored token is kept.
      const refused = cause instanceof ApiHttpError && cause.status === 401;
      if (refused && getOperatorToken() === token) {
        clearOperatorToken();
      }
      if (!current()) return null;
      setEventsRefused(refused);
      setUnlocking(false);
      // #659: a refused key shows nothing protected. A 5xx or a network error keeps the earlier data.
      if (refused) setEventsResult(null);
      setEventsState("failed");
      setEventsError(cause instanceof Error ? cause.message : "Audit read refused.");
      setStatus("Audit events could not be loaded. Safe metrics remain available.");
      return refused ? null : token;
    }
  }

  // #520: the refused agent requests of the 7-day window. The read uses the
  // Director key that the events read already holds. It never asks again.
  async function loadRefusals(filters: AppliedFilters, token: string, applyId: number) {
    const epoch = ++refusalEpochRef.current;
    const current = () => epoch === refusalEpochRef.current && applyId === applyEpochRef.current;
    const windowStartMs = Date.parse(windowBounds(filters.windowId, instrumentationRef.current, Date.now()).windowStart);
    setRefusalState("loading");
    try {
      const collected: AuditEventRead[] = [];
      let truncated = false;
      for (let pageNumber = 1; pageNumber <= REFUSAL_MAX_PAGES; pageNumber += 1) {
        const data = await fetchAuditEvents({
          page: pageNumber,
          pageSize: REFUSAL_PAGE_SIZE,
          eventKind: "continuation_request",
          teamContextKey: filters.teamKey || undefined,
          scopeContextKey: filters.scopeKey || undefined,
          operatorToken: token,
        });
        if (!current()) return;
        collected.push(...data.items);
        const oldest = data.items[data.items.length - 1];
        const done = data.items.length === 0 || pageNumber * REFUSAL_PAGE_SIZE >= data.total;
        if (done || (oldest && Date.parse(oldest.occurred_at) < windowStartMs)) break;
        if (pageNumber === REFUSAL_MAX_PAGES) truncated = true;
      }
      const groups = groupRefusals(collected, windowStartMs);
      setRefusalResult({ groups, truncated });
      setRefusalState("ready");
    } catch (cause) {
      if (!current()) return;
      if (cause instanceof ApiHttpError && cause.status === 401) {
        if (getOperatorToken() === token) clearOperatorToken();
        setRefusalState("locked");
      } else {
        setRefusalState("failed");
      }
    }
  }

  // Names are a courtesy. Without them the feed shows "member N" and the
  // stored team name. The two reads are public and need no key.
  async function loadFeedContext(current: () => boolean) {
    const [team, presets] = await Promise.allSettled([fetchAgentMailTeam(false), fetchAgentTeamPresets()]);
    if (!current()) return;
    if (team.status === "fulfilled") {
      setMemberNames(Object.fromEntries(team.value.members.map((member) => [member.id, member.display_name])));
    }
    if (presets.status === "fulfilled") {
      setTeamNames(Object.fromEntries(presets.value.presets.map((preset) => [preset.id, preset.name])));
    }
  }

  // The Team and Repository choices. The route needs the Director key. While
  // the page is locked the selects offer only "All".
  async function loadFilterOptions(token: string, current: () => boolean) {
    if (optionsLoadedRef.current) return;
    try {
      const list = await fetchContextKeys(token);
      if (!current()) return;
      optionsLoadedRef.current = true;
      setContextKeys(list);
    } catch {
      // keep the minimal selects
    }
  }

  // #515: the one way to ask for the Director key.
  function unlockEvents() {
    setUnlocking(true);
    void applyReads(applied, 1, true);
  }

  function showRefusalEvents(group: RefusalGroup) {
    if (!group.itemContextKey) return;
    const next = { itemContextKey: group.itemContextKey, label: group.itemLabel };
    focusRef.current = next;
    setFocus(next);
    void loadAudit(applied, 1);
    document.getElementById("events")?.scrollIntoView?.({ block: "start" });
  }

  function clearEventFocus() {
    focusRef.current = null;
    setFocus(null);
    void loadAudit(applied, 1);
  }

  // One applied identity drives both reads so the filters always match.
  async function applyReads(filters: AppliedFilters, requestedPage: number, ask = false) {
    const applyId = ++applyEpochRef.current;
    await Promise.resolve();
    if (applyId !== applyEpochRef.current) return;
    setApplied(filters);
    focusRef.current = null;
    setFocus(null);
    await loadMetrics(filters, applyId);
    // A delayed old metrics completion must never start an old audit epoch.
    if (applyId !== applyEpochRef.current) return;
    const token = await loadAudit(filters, requestedPage, applyId, ask);
    if (applyId !== applyEpochRef.current) return;
    if (token) {
      void loadFeedContext(() => applyId === applyEpochRef.current);
      void loadFilterOptions(token, () => applyId === applyEpochRef.current);
      await loadRefusals(filters, token, applyId);
    } else {
      setRefusalState("locked");
    }
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
    refusalEpochRef.current += 1;
    tokenResolverRef.current?.(null);
    tokenResolverRef.current = null;
    tokenPromiseRef.current = null;
  }, []);

  const metrics = metricsResult?.data ?? null;
  const notes = tableNotes(metrics?.metrics ?? []);
  const events = eventsResult?.data.items ?? [];
  const feed = buildFeed(events, { teams: teamNames, members: memberNames });
  const labels = eventsResult?.data.snapshot_labels ?? [];
  const total = eventsResult?.data.total ?? 0;
  const page = eventsResult?.page ?? 1;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const teamOptions = filterOptions("team", contextKeys?.teams ?? []);
  const scopeOptions = filterOptions("scope", contextKeys?.repositories ?? []);
  const filterNames: FilterNames = {
    team: (key) => teamOptions.find((option) => option.value === key)?.label ?? "selected",
    scope: (key) => scopeOptions.find((option) => option.value === key)?.label ?? "selected",
  };
  const metricsRetained = metricsResult
    ? retainedReason(metricsState, sameFilters(metricsResult.filters, applied), applied, filterNames)
    : null;
  const eventsRetained = eventsResult
    ? retainedReason(eventsState, sameFilters(eventsResult.filters, applied), applied, filterNames)
    : null;
  // C13: paging uses the identity of the rows on screen. It waits while those
  // rows belong to another selection or a read is pending.
  // #515: no count and no feed while the events are locked, cancelled or refused.
  // The box stays from the Unlock click until that read ends, so focus returns to the same button.
  const eventsBlocked = !eventsResult
    && (["locked", "cancelled", "failed"].includes(eventsState) || (eventsState === "pending" && unlocking));
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
          How delivery is going, and what needs a look.
        </p>
      </header>

      <section aria-label="Filters" className="flex flex-wrap items-end gap-3 rounded border p-3">
        {/* R10: selects stay inside the card at narrow widths. */}
        <div className="w-full min-w-0 text-sm sm:w-auto">
          <label htmlFor="audit-filter-team" className={labelClass}>Team</label>
          <select id="audit-filter-team" ref={teamSelectRef} value={applied.teamKey}
            onChange={(event) => void applyReads({ ...applied, teamKey: event.target.value }, 1)}
            className="mt-1 w-full rounded-md border bg-background px-3 py-2 sm:w-64">
            <option value="">All teams</option>
            {teamOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </div>
        <div className="w-full min-w-0 text-sm sm:w-auto">
          <label htmlFor="audit-filter-scope" className={labelClass}>Repository</label>
          <select id="audit-filter-scope" value={applied.scopeKey}
            onChange={(event) => void applyReads({ ...applied, scopeKey: event.target.value }, 1)}
            className="mt-1 w-full rounded-md border bg-background px-3 py-2 sm:w-64">
            <option value="">All repositories</option>
            {scopeOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </div>
        <div className="w-full min-w-0 text-sm sm:w-auto">
          <label htmlFor="audit-filter-window" className={labelClass}>Window</label>
          <select id="audit-filter-window" value={applied.windowId}
            onChange={(event) => void applyReads({ ...applied, windowId: event.target.value as WindowId }, 1)}
            className="mt-1 w-full rounded-md border bg-background px-3 py-2 sm:w-64">
            {WINDOW_OPTIONS.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
          </select>
        </div>
      </section>

      <AuditSummary metrics={metrics} />

      <div className="space-y-1">
        {metricsResult && (
          <p className="text-xs text-muted-foreground">
            Showing metrics for {describeFilters(metricsResult.filters, filterNames)}, observed at {formatServerTime(metricsResult.observedAt)}.
          </p>
        )}
        {metricsRetained && (
          <p role="status" className="text-sm text-muted-foreground">
            Retained metrics: {metricsRetained}.
          </p>
        )}
        {metricsError && <p role="alert" className="text-sm text-destructive">{metricsError}</p>}
      </div>

      <NeedsALookPanel
        state={refusalState}
        groups={refusalResult?.groups ?? []}
        names={memberNames}
        truncated={refusalResult?.truncated ?? false}
        onShowEvents={showRefusalEvents}
        onUnlock={unlockEvents}
      />

      <section aria-labelledby="events" className="space-y-2 rounded border p-3">
        <h3 id="events" className="font-semibold">Audit events</h3>
        {labels.length > 0 && (
          <p className="text-xs text-muted-foreground">Snapshot labels in page: {labels.join(", ")}</p>
        )}
        {focus && (
          <p className="flex flex-wrap items-center gap-2 text-sm">
            Showing refused requests for {focus.label} only.
            <Button variant="outline" size="sm" onClick={clearEventFocus}>Show all events</Button>
          </p>
        )}
        {eventsResult && (
          <p className="text-sm text-muted-foreground">
            Showing events for {describeFilters(eventsResult.filters, filterNames)}, page {eventsResult.page}, observed
            at {formatServerTime(eventsResult.observedAt)}.
          </p>
        )}
        {eventsRetained && (
          <p role="status" className="text-sm text-muted-foreground">
            Retained events: {eventsRetained}.
          </p>
        )}
        {eventsError && <p role="alert" className="text-sm text-destructive">{eventsError}</p>}
        {eventsBlocked && (
          <div data-testid="events-locked" className="space-y-2 rounded border border-dashed p-3 text-sm">
            <p>
              <span className="font-medium">Locked.</span> Audit events are protected. They can include changed
              settings and reasons, and agents cannot read them.
            </p>
            {eventsState === "cancelled" && (
              <p>Events are not shown. The Director key request was cancelled.</p>
            )}
            {eventsState === "failed" && <p>Events are not shown. The read was refused or failed.</p>}
            {(eventsState !== "failed" || eventsRefused) && (
              <Button onClick={unlockEvents} disabled={eventsState === "pending"}>Unlock events</Button>
            )}
          </div>
        )}
        {!eventsResult && eventsState === "pending" && !unlocking && (
          <p className="text-sm text-muted-foreground">Reading events.</p>
        )}
        {eventsResult && (isNoEventKey(applied.teamKey) || isNoEventKey(applied.scopeKey)) && (
          <p className="text-sm">
            No recorded events for this {isNoEventKey(applied.teamKey) ? "team" : "repository"} yet.
          </p>
        )}
        {eventsResult && (
          <ActivityFeed
            feed={feed}
            now={Date.parse(eventsResult.observedAt)}
            snapshotLabels={namedSnapshotValues}
          />
        )}
        {eventsResult && (
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="outline" disabled={pagingBlocked || page <= 1}
              onClick={() => void loadAudit(eventsResult.filters, eventsResult.page - 1)}>
              Previous page
            </Button>
            <p className="text-sm">Page {page} of {pageCount}</p>
            <Button variant="outline" disabled={pagingBlocked || page >= pageCount}
              onClick={() => void loadAudit(eventsResult.filters, eventsResult.page + 1)}>
              Next page
            </Button>
          </div>
        )}
      </section>

      {eventsResult && <p className="text-sm">Total audit events matching filters: {total}</p>}

      <details className="rounded border p-3">
        <summary className="cursor-pointer font-semibold">All metrics (technical)</summary>
        <div className="mt-3 space-y-4">
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
          <div>
            <table className="w-full table-fixed text-sm">
              <thead>
                <tr className="text-left">
                  <th className="w-2/5 p-2">Metric</th>
                  <th className="p-2">Value</th>
                  <th className="p-2">Samples</th>
                  <th className="p-2">Unknown</th>
                  <th className="p-2">Excluded</th>
                  <th className="p-2">Coverage</th>
                  <th className="p-2">Notes</th>
                </tr>
              </thead>
              <tbody>
                {(metrics?.metrics ?? []).map((sample) => (
                  <tr key={sample.name} className="border-t align-top">
                    <td className="p-2 break-words">
                      <span className="block font-medium">{metricLabel(sample.name)}</span>
                      <span className="block text-xs text-muted-foreground">{sample.name}</span>
                      <span className="block text-xs text-muted-foreground">{sample.counting_unit}</span>
                      <span className="block text-xs text-muted-foreground">{sample.source}</span>
                    </td>
                    <td className="p-2">{tableValue(sample)}</td>
                    <td className="p-2">{sample.sample_count}</td>
                    <td className="p-2">{sample.unknown_count}</td>
                    <td className="p-2">{sample.excluded_count}</td>
                    <td className="p-2 break-words">{notes.coverage[sample.name]}</td>
                    <td className="p-2">
                      {(notes.refs[sample.name] ?? []).map((ref) => (
                        <a key={ref} href={`#metric-note-${ref}`} className="mr-1 text-primary underline">{ref}</a>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {notes.footnotes.length > 0 && (
              <ol className="mt-2 space-y-1 text-xs text-muted-foreground">
                {notes.footnotes.map((note, index) => (
                  <li key={note} id={`metric-note-${index + 1}`}>{index + 1}. {note}</li>
                ))}
              </ol>
            )}
          </div>
        </div>
      </details>

      <OperatorTokenDialog
        open={tokenDialogOpen}
        value={tokenInput}
        error={tokenError}
        reason="to read audit events"
        onValueChange={setTokenInput}
        onSubmit={submitToken}
        onCancel={() => settleToken(null)}
      />
      <p role="status" className="text-sm">{status}</p>
    </section>
  );
}
