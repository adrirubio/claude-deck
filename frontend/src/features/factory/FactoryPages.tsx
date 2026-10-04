import { useLayoutEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogCancel,
  AlertDialogAction,
} from "@/components/ui/alert-dialog";
import { ApiHttpError } from "@/lib/api";
import {
  fetchGithubScopeRevisions,
  retryGithubWorkItem,
} from "@/features/agent-teams/api";
import {
  clearOperatorToken,
  getOperatorToken,
  setOperatorToken,
} from "@/features/agent-teams/operatorAuth";
import type {
  OverviewResponse,
  RepositoryProjection,
  RepositoryDetailResponse,
  WorkProjection,
  WorkDetailResponse,
  GithubIdentity,
} from "@/types/factory";
import { FactoryFilters } from "./filters";
import { categories, factoryQuery, workLink } from "./filterHelpers";
import {
  markWorkListsDirty,
  useCursorList,
  useObservation,
  type ReadState,
  type ListState,
} from "./reads";

const panel = "space-y-3 rounded-lg border bg-card p-4";
const anchor =
  "text-primary underline underline-offset-4 break-words focus-visible:outline focus-visible:outline-2";
function Time({
  value,
  label = "Observed",
}: {
  value: string | null;
  label?: string;
}) {
  return (
    <span className="text-xs text-muted-foreground">
      {label}:{" "}
      {value ? (
        <time dateTime={value}>{new Date(value).toLocaleString()}</time>
      ) : (
        "Unknown"
      )}
    </span>
  );
}
function ReadStatus<T>({ state }: { state: ReadState<T> }) {
  const error = state.error;
  return (
    <div aria-live="polite" className="text-sm">
      {state.refreshing && (
        <p>{state.data ? "Refreshing observation…" : "Loading…"}</p>
      )}
      {error && (
        <p role="alert" className="rounded border border-destructive p-3">
          {state.data
            ? "Stale data — refresh failed. Last successful observation remains visible. "
            : ""}
          {error instanceof ApiHttpError && error.status === 404
            ? "Not found. "
            : ""}
          {error.message}
          {error instanceof ApiHttpError && (error.code || error.blockCode)
            ? ` (${error.code ?? error.blockCode})`
            : ""}
        </p>
      )}
    </div>
  );
}
function Pagination<T>({
  state,
}: {
  state: ListState<T> & { more: () => void; restart: () => void };
}) {
  return (
    <div className="flex flex-wrap items-center gap-3" aria-live="polite">
      {state.paused && (
        <p className="text-sm">
          Live updates paused while browsing older results
          {state.needsRefresh ? " — detail changed; refresh needed" : ""}.
        </p>
      )}
      {(state.data?.has_more || state.paused) && (
        <Button
          variant="outline"
          aria-disabled={
            !state.data?.has_more || (state.paused && state.refreshing)
          }
          onClick={state.data?.has_more ? state.more : () => undefined}
        >
          {!state.data?.has_more
            ? "No more results"
            : state.paused && state.refreshing
              ? "Loading more…"
              : "Load more"}
        </Button>
      )}
      <Button variant="outline" onClick={state.restart}>
        Refresh from start
      </Button>
      {state.data && (
        <>
          <span className="text-sm">
            {state.data.rows.length} loaded / {state.data.total} matching
          </span>
          <Time value={state.data.generated_at} />
        </>
      )}
    </div>
  );
}
function githubLink(
  identity: GithubIdentity,
  kind: "issues" | "pull",
  id: number,
) {
  if (
    !/^[A-Za-z0-9_.-]+$/.test(identity.owner) ||
    !/^[A-Za-z0-9_.-]+$/.test(identity.name) ||
    !Number.isSafeInteger(id) ||
    id <= 0
  )
    return null;
  return `https://github.com/${identity.owner}/${identity.name}/${kind}/${id}`;
}
function GithubLink({
  identity,
  kind,
  id,
  children,
}: {
  identity: GithubIdentity;
  kind: "issues" | "pull";
  id: number;
  children: React.ReactNode;
}) {
  const href = githubLink(identity, kind, id);
  return href ? (
    <a className={anchor} href={href} target="_blank" rel="noreferrer">
      {children}
    </a>
  ) : (
    <span>Invalid GitHub identity</span>
  );
}
function WorkTable({ rows }: { rows: WorkProjection[] }) {
  return (
    <div data-work-table className="overflow-x-auto rounded-lg border">
      <table className="w-full min-w-[720px] text-left text-sm">
        <caption className="sr-only">
          Delivery work across selected teams and watched scopes
        </caption>
        <thead className="bg-muted">
          <tr>
            {[
              "Issue",
              "Stage",
              "Owner",
              "Waiting",
              "PR",
              "Deck record updated",
              "Actions",
            ].map((title) => (
              <th key={title} scope="col" className="p-3">
                {title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((work) => (
            <tr key={work.item.id} className="border-t align-top">
              <td className="p-3">
                <Link className={anchor} to={`/work/${work.item.id}`}>
                  #{work.item.issue_number} {work.item.issue_title}
                </Link>
                <p>
                  {work.repository.display_name} · {work.team.name} · scope{" "}
                  {work.repository.scope_id}
                </p>
              </td>
              <td className="p-3">
                {categories[work.category]}
                <p>{work.item.dispatch_status}</p>
                <p>
                  {work.item.issue_type} · {work.item.attempt_phase}
                </p>
              </td>
              <td className="p-3">
                {work.owner?.name ?? "Unassigned"}
                <p>
                  {work.owner?.provider_label ?? "Configured harness unknown"}
                </p>
                {work.session.observed_provider && (
                  <p>Observed runtime: {work.session.observed_provider}</p>
                )}
              </td>
              <td className="p-3">
                {work.waiting
                  ? `${work.waiting.actor === "leader" ? "Waiting for Leader" : work.waiting.actor}: ${work.waiting.summary}`
                  : "No waiting actor established"}
              </td>
              <td className="p-3">
                {work.item.pr_number ? (
                  <GithubLink
                    identity={work.repository.github}
                    kind="pull"
                    id={work.item.pr_number}
                  >
                    PR #{work.item.pr_number}
                  </GithubLink>
                ) : (
                  "No PR"
                )}
              </td>
              <td className="p-3">
                <Time value={work.item.updated_at} label="Record observation" />
              </td>
              <td className="p-3">
                <Link className={anchor} to={`/work/${work.item.id}`}>
                  Open details
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function WorkResults({ query = "" }: { query?: string }) {
  const state = useCursorList<WorkProjection>(
    `factory/work-items${query ? `?${query}` : ""}`,
    "items",
    (row) => row.item.id,
  );
  const root = useRef<HTMLDivElement>(null);
  const { getPosition, rememberPosition } = state;
  useLayoutEffect(() => {
    const element = root.current;
    if (!element) return;
    const main = element.closest("main") ?? document.documentElement;
    const table = element.querySelector<HTMLElement>("[data-work-table]");
    const position = getPosition();
    if (position) {
      const link = [
        ...element.querySelectorAll<HTMLAnchorElement>("a[href]"),
      ].find(
        (candidate) =>
          candidate.getAttribute("href") === position.focusHref &&
          candidate.textContent === position.focusText,
      );
      link?.focus({ preventScroll: true });
      main.scrollTop = position.top;
      if (table) table.scrollLeft = position.left;
    }
    return () => {
      const active = document.activeElement;
      rememberPosition({
        top: main.scrollTop,
        left:
          element.querySelector<HTMLElement>("[data-work-table]")?.scrollLeft ??
          0,
        focusHref:
          active instanceof HTMLAnchorElement && element.contains(active)
            ? active.getAttribute("href")
            : null,
        focusText:
          active instanceof HTMLAnchorElement && element.contains(active)
            ? active.textContent
            : null,
      });
    };
  }, [getPosition, rememberPosition]);
  return (
    <div ref={root} className="space-y-4">
      <ReadStatus state={state} />
      {state.data && (
        <>
          {state.data.rows.length ? (
            <WorkTable rows={state.data.rows} />
          ) : (
            <p>
              No work matches these filters. Clear filters to inspect the whole
              factory.
            </p>
          )}
          <Pagination state={state} />
        </>
      )}
    </div>
  );
}
export function WorkPage() {
  const [params] = useSearchParams();
  const query = factoryQuery(params, true);
  return (
    <section className="space-y-5">
      <h2 className="text-2xl font-semibold">Work</h2>
      <p>
        Assigned harness filters describe the current owner slot. Finished means
        tracking ended; delivery and human review require evidence.
      </p>
      <FactoryFilters work />
      <WorkResults key={query} query={query} />
    </section>
  );
}
function RepositoryCard({
  repository: r,
}: {
  repository: RepositoryProjection;
}) {
  return (
    <article className={panel}>
      <h3 className="font-semibold">
        <Link className={anchor} to={`/repositories/${r.scope_id}`}>
          {r.github.owner}/{r.github.name}
        </Link>
      </h3>
      <p>
        <Link className={anchor} to={`/teams/${r.team.id}`}>
          {r.team.name}
        </Link>{" "}
        · scope {r.scope_id}
      </p>
      <p>
        Configured {r.configured_enabled ? "enabled" : "paused"} · team
        automation {r.team_automation_enabled ? "on" : "off"} · scope{" "}
        {r.scope_enabled ? "on" : "off"}
      </p>
      <p>
        Intake {r.intake.state}: {r.intake.summary}
      </p>
      <p>
        Polling {r.poll.freshness.replaceAll("_", " ")} · every{" "}
        {r.poll.interval_seconds}s
      </p>
      <Time value={r.poll.last_polled_at} label="Last repository poll" />
      {r.overlap.state === "warning" && (
        <p role="note" className="rounded border border-amber-500 p-2">
          Same-label overlap: scopes {r.overlap.other_scope_ids.join(", ")} have
          independent dispatch authority. The same issue may dispatch more than
          once.
        </p>
      )}
      {r.overlap.state === "unknown" && <p>Overlap evidence unavailable.</p>}
      <div className="flex flex-wrap gap-3">
        <Link className={anchor} to={`/work?scope_id=${r.scope_id}`}>
          Scope work
        </Link>
        <Link className={anchor} to={`/teams/${r.team.id}?tab=autonomy`}>
          Inspect policy and repository configuration
        </Link>
      </div>
    </article>
  );
}
function RepositoryResults({ query = "" }: { query?: string }) {
  const state = useCursorList<RepositoryProjection>(
    `factory/repositories${query ? `?${query}` : ""}`,
    "repositories",
    (row) => row.scope_id,
  );
  return (
    <div className="space-y-4">
      <ReadStatus state={state} />
      {state.data && (
        <>
          {!state.data.rows.length && (
            <p>
              No watched repository scopes match.{" "}
              <Link className={anchor} to="/teams">
                Configure a repository
              </Link>
            </p>
          )}
          <div className="grid gap-4 lg:grid-cols-2">
            {state.data.rows.map((r) => (
              <RepositoryCard key={r.scope_id} repository={r} />
            ))}
          </div>
          <Pagination state={state} />
        </>
      )}
    </div>
  );
}
export function RepositoriesPage() {
  const [params] = useSearchParams();
  const query = factoryQuery(params);
  return (
    <section className="space-y-5">
      <h2 className="text-2xl font-semibold">Repositories</h2>
      <p>
        Each watched scope keeps its owning team and independent authority. Team
        roster harness filters may differ from Work's assigned owner filter.
      </p>
      <FactoryFilters repository />
      <RepositoryResults key={query} query={query} />
    </section>
  );
}
export function RepositoryPage() {
  const { scopeId } = useParams();
  const state = useObservation<RepositoryDetailResponse>(
    `factory/repositories/${encodeURIComponent(scopeId ?? "")}`,
  );
  return (
    <section className="space-y-5">
      <h2 className="text-2xl font-semibold">Repository scope {scopeId}</h2>
      <ReadStatus state={state} />
      {state.data && (
        <>
          <RepositoryCard repository={state.data.repository} />
          <Time value={state.data.generated_at} />
          <h3 className="text-lg font-semibold">Scope work</h3>
          <WorkResults
            key={scopeId}
            query={`scope_id=${encodeURIComponent(scopeId ?? "")}`}
          />
        </>
      )}
    </section>
  );
}
export function OverviewPage() {
  const [params] = useSearchParams();
  const query = factoryQuery(params);
  const state = useObservation<OverviewResponse>(
    `factory/overview${query ? `?${query}` : ""}`,
  );
  const filtered = Boolean(query);
  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold">Overview</h2>
          <p className="text-muted-foreground">
            Delivery across this backend instance
          </p>
        </div>
        <Button variant="outline" onClick={() => void state.refresh()}>
          Refresh observation
        </Button>
      </div>
      <FactoryFilters />
      <ReadStatus state={state} />
      {state.data && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            {Object.entries(categories)
              .filter(([id]) => id !== "all")
              .map(([id, label]) => (
                <Link
                  key={id}
                  className={`${panel} hover:bg-accent focus-visible:outline focus-visible:outline-2`}
                  to={workLink(params, id)}
                >
                  <span>{label}</span>
                  <strong className="block text-3xl">
                    {state.data!.counts[id as keyof typeof state.data.counts]}
                  </strong>
                </Link>
              ))}
          </div>
          <p>
            {state.data.counts.total} matching work items across the complete
            set.
          </p>
          <Time value={state.data.generated_at} />
          <section className={panel}>
            <h3 className="font-semibold">Automation observation</h3>
            <p>
              Runtime {state.data.automation.runtime.mode.replaceAll("_", " ")}{" "}
              · scheduler {state.data.automation.runtime.scheduler_state}
            </p>
            <Time
              value={state.data.automation.runtime.observed_at}
              label="Runtime observed"
            />
            {state.data.automation.runtime.mode === "recovery_only" && (
              <p>
                Recovery-only mode blocks normal intake for all
                configured-enabled scopes. Protected recovery target details
                remain in operator recovery.
              </p>
            )}
            {state.data.automation.runtime.scheduler_state === "stopped" && (
              <p>Scheduler stopped: normal intake is blocked.</p>
            )}
            {state.data.automation.runtime.mode === "unknown" && (
              <p>
                Runtime evidence is unknown; configuration alone does not
                establish intake health.
              </p>
            )}
            <p>
              {state.data.automation.configured_scopes} configured scopes ·{" "}
              {state.data.automation.enabled_scopes} configured enabled ·{" "}
              {state.data.automation.paused_scopes} configured paused
            </p>
            <p>
              Intake: {state.data.automation.intake_eligible_scopes} eligible ·{" "}
              {state.data.automation.intake_blocked_scopes} blocked ·{" "}
              {state.data.automation.intake_unknown_scopes} unknown
            </p>
            <p>
              Eligible scopes: {state.data.automation.stale_scopes} stale polls
              · {state.data.automation.never_polled_scopes} never polled.
              Eligibility still depends on access, readiness and capacity.
            </p>
          </section>
          {state.data.automation.configured_scopes === 0 && (
            <div className={panel}>
              <h3 className="font-semibold">
                {filtered
                  ? "No scopes match these filters"
                  : "No watched repositories yet"}
              </h3>
              <div className="flex flex-wrap gap-4">
                {filtered ? (
                  <Link className={anchor} to="/">
                    Clear filters
                  </Link>
                ) : (
                  <Link className={anchor} to="/teams?tab=autonomy">
                    Configure a repository
                  </Link>
                )}
                <Link className={anchor} to="/agent-bridge">
                  Open live sessions
                </Link>
                <Link className={anchor} to="/harnesses">
                  Open Harnesses and configuration
                </Link>
              </div>
              <p>
                Native configuration remains available without setting up a
                factory.
              </p>
            </div>
          )}
          {(["attention", "review", "active"] as const).map((category) => (
            <section key={category} className="space-y-3">
              <h3 className="text-lg font-semibold">
                <Link className={anchor} to={workLink(params, category)}>
                  {categories[category]}
                </Link>
              </h3>
              <WorkResults
                query={factoryQuery(
                  new URLSearchParams(workLink(params, category).split("?")[1]),
                  true,
                )}
              />
            </section>
          ))}
          <section className="space-y-3">
            <h3 className="text-lg font-semibold">Repository automation</h3>
            <RepositoryResults query={query} />
          </section>
        </>
      )}
    </section>
  );
}
function ContextLinks({ work: w }: { work: WorkProjection }) {
  const target = w.links.bridge_target;
  const bridge = new URLSearchParams({
    team_id: String(w.team.id),
    ...(w.owner ? { slot_id: String(w.owner.slot_id) } : {}),
    context: "readonly",
  });
  if (target && w.session.state === "bound") {
    bridge.set("team_id", String(target.team_id));
    bridge.set("slot_id", String(target.slot_id));
    bridge.set("member_id", String(target.member_id));
    bridge.set("session_id", String(target.session_id));
  }
  const mail = w.links.mail;
  const launch = w.links.launch_plan;
  const launchName =
    launch?.slot_id === w.owner?.slot_id
      ? (w.owner?.name ?? "owner")
      : launch?.slot_id === w.approver?.slot_id
        ? "Leader"
        : launch
          ? `slot ${launch.slot_id}`
          : "";
  return (
    <nav aria-label="Work context" className="flex flex-wrap gap-4">
      <Link className={anchor} to={`/teams/${w.team.id}`}>
        Team
      </Link>
      <Link className={anchor} to={`/repositories/${w.repository.scope_id}`}>
        Repository scope
      </Link>
      <Link className={anchor} to={`/agent-bridge?${bridge}`}>
        {target && w.session.state === "bound"
          ? "Read-only verified session"
          : "Inspect team/slot sessions"}
      </Link>
      {mail && (
        <Link
          className={anchor}
          to={`/agent-mail?team_id=${mail.team_id}&slot_id=${mail.slot_id}&member_id=${mail.member_id}`}
        >
          Mail context
        </Link>
      )}
      {launch && (
        <Link
          className={anchor}
          to={`/teams/${launch.team_id}?slot_id=${launch.slot_id}&review_launch=1`}
        >
          Review launch for {launchName}
        </Link>
      )}
      {w.owner?.configured_provider && (
        <Link
          className={anchor}
          to={`/harnesses/${w.owner.configured_provider}`}
        >
          Native harness settings
        </Link>
      )}
    </nav>
  );
}
function ProtectedRemedies({
  work,
  refresh,
}: {
  work: WorkProjection;
  refresh: () => Promise<void>;
}) {
  const [operation, setOperation] = useState<"retry" | "history" | null>(null);
  const [confirmRetry, setConfirmRetry] = useState(false);
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<string[] | null>(null);
  const retry = work.actions.find((action) => action.name === "retry");
  const context = useRef({ generation: 0, active: false, work, refresh });
  const retryConfirmed = useRef(false);
  const running = useRef(false);
  useLayoutEffect(() => {
    context.current.work = work;
    context.current.refresh = refresh;
  }, [work, refresh]);
  useLayoutEffect(() => {
    const target = context.current;
    target.active = true;
    return () => {
      target.active = false;
      target.generation += 1;
      retryConfirmed.current = false;
    };
  }, []);

  async function run(action: "retry" | "history", credential: string) {
    const target = context.current;
    if (!target.active || running.current) return;
    if (action === "retry") {
      if (!retryConfirmed.current) return;
      // Each confirmation permits exactly one mutation, including a denied one.
      retryConfirmed.current = false;
      if (
        target.work.actions.find((a) => a.name === "retry")?.state !== "eligible"
      ) {
        setError("Retry eligibility changed. Refresh and review this work item.");
        setOperation(null);
        return;
      }
    }
    const generation = target.generation;
    const workItemId = target.work.item.id;
    const current = () =>
      context.current.active &&
      context.current.generation === generation &&
      context.current.work.item.id === workItemId;
    running.current = true;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      if (action === "retry") {
        const response = await retryGithubWorkItem(workItemId, credential);
        // A sent mutation may affect a paused list even after detail navigation.
        markWorkListsDirty();
        if (!current()) return;
        if (response.id !== workItemId) {
          throw new Error(
            "Retry returned a different work item. Refresh to inspect current state.",
          );
        }
        setResult(
          response.retry_requested_at
          ? `Retry requested; re-dispatch is deferred until the current owner releases the workspace. Dispatch status: ${response.dispatch_status}. ${response.status_note ?? ""}`
          : response.dispatch_status === "pending"
            ? "Retry reset this work item to pending. A new dispatch has not been observed."
            : `Retry response status: ${response.dispatch_status}. A new dispatch has not been observed. ${response.status_note ?? ""}`,
        );
        await context.current.refresh();
      } else {
        const revisions = await fetchGithubScopeRevisions(workItemId, credential);
        if (!current()) return;
        setHistory(revisions.map((r) => `Revision ${r.revision}: ${r.status}`));
      }
      if (!current()) return;
      setOperation(null);
      setToken("");
    } catch (failure) {
      if (action === "retry") markWorkListsDirty();
      if (!current()) return;
      const message =
        failure instanceof Error ? failure.message : "Action failed";
      if (failure instanceof ApiHttpError && failure.status === 401) {
        clearOperatorToken();
        setToken("");
        setOperation(action);
      }
      setError(message);
      if (action === "retry") await context.current.refresh();
    } finally {
      running.current = false;
      if (current()) setBusy(false);
    }
  }
  const begin = (action: "retry" | "history") => {
    if (!context.current.active || running.current) return;
    const credential = getOperatorToken();
    if (credential) void run(action, credential);
    else setOperation(action);
  };
  return (
    <section className={panel}>
      <h3 className="font-semibold">Protected recovery</h3>
      <p>
        Eligibility describes work state; the server rechecks actor and operator
        authorization. Agent decisions and human PR review remain separate.
      </p>
      <div className="flex flex-wrap gap-3">
        <Button
          variant="outline"
          disabled={busy || retry?.state !== "eligible"}
          onClick={() => {
            retryConfirmed.current = false;
            setError(null);
            setConfirmRetry(true);
          }}
        >
          Retry issue
        </Button>
        <Button
          variant="outline"
          disabled={busy}
          onClick={() => begin("history")}
        >
          Inspect protected revision history
        </Button>
        <Link
          className={anchor}
          to={`/teams/${work.team.id}?tab=autonomy&work_item_id=${work.item.id}`}
        >
          Existing attempt recovery and remedies
        </Link>
      </div>
      <p>
        Retry: {retry?.state ?? "unknown"} · required actor{" "}
        {retry?.required_actor ?? "unknown"} ·{" "}
        {retry?.reason ?? "Eligibility unavailable"}. Retrying may reset attempt
        markers.
      </p>
      {work.actions
        .filter((action) => action.name !== "retry")
        .map((action) => (
          <p key={action.name}>
            {action.name.replaceAll("_", " ")}: {action.state} · {action.reason}{" "}
            · required actor {action.required_actor}
          </p>
        ))}
      {error && <p role="alert">{error}</p>}
      {result && <p role="status">{result}</p>}
      {history && (
        <ul>
          {history.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
      <AlertDialog
        open={confirmRetry}
        onOpenChange={(open) => {
          setConfirmRetry(open);
          if (!open) retryConfirmed.current = false;
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Retry issue #{work.item.issue_number}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              Retry can discard prior PR, handoff, and attempt markers. If the
              workspace is still leased, Deck defers re-dispatch until the current
              owner releases it. Review this work item before continuing. The
              server rechecks current eligibility and authorization.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={busy || retry?.state !== "eligible"}
              onClick={(event) => {
                event.preventDefault();
                if (!context.current.active || running.current) return;
                retryConfirmed.current = true;
                setConfirmRetry(false);
                begin("retry");
              }}
            >
              Confirm retry
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <Dialog
        open={operation !== null}
        onOpenChange={(open) => {
          if (!open) {
            setOperation(null);
            setToken("");
            retryConfirmed.current = false;
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Deck operator authorization</DialogTitle>
            <DialogDescription>
              {operation === "retry"
                ? "Retry this issue using current server eligibility. Attempt markers may reset."
                : "Read protected revision history."}{" "}
              Uses the existing per-tab operator credential.
            </DialogDescription>
          </DialogHeader>
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (
                operation && token.trim() && context.current.active &&
                !running.current
              ) {
                setOperatorToken(token);
                if (operation === "retry" && !retryConfirmed.current) {
                  // A 401 consumed the prior confirmation. Review again before retrying.
                  setOperation(null);
                  setToken("");
                  setConfirmRetry(true);
                } else {
                  void run(operation, token.trim());
                }
              }
            }}
          >
            <label className="grid gap-2">
              Operator token
              <input
                autoFocus
                type="password"
                autoComplete="off"
                className="rounded border bg-background p-2"
                value={token}
                onChange={(event) => setToken(event.target.value)}
              />
            </label>
            <Button disabled={busy || !token.trim()}>
              Authorize {operation}
            </Button>
            {error && <p role="alert">{error}</p>}
          </form>
        </DialogContent>
      </Dialog>
    </section>
  );
}
export function WorkDetailPage() {
  const { workItemId } = useParams();
  const state = useObservation<WorkDetailResponse>(
    `factory/work-items/${encodeURIComponent(workItemId ?? "")}`,
  );
  const w = state.data?.work_item;
  return (
    <section className="space-y-5">
      <h2 className="text-2xl font-semibold">Work details</h2>
      <ReadStatus state={state} />
      {w && (
        <>
          <article className={panel}>
            <h3 className="text-xl font-semibold">
              #{w.item.issue_number} {w.item.issue_title}
            </h3>
            <p>
              {categories[w.category]} · raw status {w.item.dispatch_status} ·{" "}
              {w.item.issue_type} · phase {w.item.attempt_phase}
            </p>
            <p>
              {w.team.name} · {w.repository.display_name} · owner{" "}
              {w.owner?.name ?? "Unassigned"} · configured harness{" "}
              {w.owner?.provider_label ?? "unknown"}
            </p>
            <p>
              Approver slot {w.approver?.slot_id ?? "unknown"} (
              {w.approver?.source ?? "unknown"}) · owner session{" "}
              {w.session.state} · observed runtime{" "}
              {w.session.observed_provider ?? "unknown"}
            </p>
            {w.waiting && (
              <p>
                {w.waiting.actor === "leader"
                  ? "Waiting for Leader"
                  : `Waiting for ${w.waiting.actor}`}
                : {w.waiting.summary}
              </p>
            )}
            {w.item.dispatch_status === "completed" && (
              <p>
                Tracking finished; delivery and human review are unconfirmed
                without result evidence.
              </p>
            )}
            {w.waiting?.reason_code === "abandoned_by_operator" && (
              <p>
                Operator requested stop. This remains Needs attention; the agent
                may still run and retry may remain possible. Process termination
                is not guaranteed.
              </p>
            )}
            {w.category === "unknown" && (
              <p>
                Unknown state retained as reported; execution is not inferred.
              </p>
            )}
            <div className="flex flex-wrap gap-4">
              <GithubLink
                identity={w.repository.github}
                kind="issues"
                id={w.item.issue_number}
              >
                Open issue
              </GithubLink>
              {w.item.pr_number && (
                <GithubLink
                  identity={w.repository.github}
                  kind="pull"
                  id={w.item.pr_number}
                >
                  Open PR #{w.item.pr_number}
                </GithubLink>
              )}
            </div>
            <p className="break-all">
              PR verification head: {w.item.last_verified_sha ?? "Unconfirmed"}
            </p>
            <Time value={w.item.updated_at} label="Deck record observation" />
            <Time value={state.data!.generated_at} label="Details observed" />
          </article>
          <ContextLinks work={w} />
          <section className={panel}>
            <h3 className="font-semibold">Finite policy and authority</h3>
            <p>
              Merge policy: {w.policy.merge_policy} · maximum verification
              retries {w.policy.max_verification_retries} · maximum approval
              rounds {w.policy.max_approval_rounds}
            </p>
            <p>
              Implementation retries {w.item.retry_count} · diagnostic failed
              heads {w.item.diagnostic_retry_count} · approval rounds{" "}
              {w.item.approval_round_count}
            </p>
            <p>
              Continuation configured{" "}
              {w.policy.continuation_enabled ? "enabled" : "disabled"}; this
              does not grant revision authority. Active revision{" "}
              {w.item.active_scope_revision}:{" "}
              {w.item.active_scope_status ?? "none"}.
            </p>
            <p>
              Workspace{" "}
              {w.workspace
                ? `${w.workspace.id} (${w.workspace.state})`
                : "association unknown"}
            </p>
          </section>
          <ProtectedRemedies key={w.item.id} work={w} refresh={state.refresh} />
        </>
      )}
    </section>
  );
}
