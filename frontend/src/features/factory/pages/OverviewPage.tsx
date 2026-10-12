import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { TeamSummaries } from "@/features/agent-teams/TeamSummaryCard";
import type { OverviewResponse } from "@/types/factory";
import { ReadStatus } from "../components/ReadStatus";
import { RepositoryResults } from "../components/RepositoryResults";
import { anchor, destination, panel } from "../components/styles";
import { Time } from "../components/Time";
import { WorkResults } from "../components/WorkResults";
import { categories, factoryQuery, workLink } from "../filterHelpers";
import { FactoryFilters } from "../filters";
import { useFactoryFilters } from "../filterOptions";
import { useObservation } from "../reads";

export function OverviewPage() {
  const { params, ready } = useFactoryFilters();
  const query = factoryQuery(params);
  const state = useObservation<OverviewResponse>(
    ready ? `factory/overview${query ? `?${query}` : ""}` : null,
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
          <TeamSummaries teamId={params.get("team_id")} />
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
                  <Link className={destination} to="/teams?tab=autonomy">
                    Configure a repository
                  </Link>
                )}
                <Link className={destination} to="/agent-bridge">
                  Open live sessions
                </Link>
                <Link className={destination} to="/harnesses">
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
              <div className="flex flex-wrap items-baseline justify-between gap-3">
                <h3 className="text-lg font-semibold">{categories[category]}</h3>
                <Link
                  className={anchor}
                  aria-label={`View all ${categories[category]}`}
                  to={workLink(params, category)}
                >
                  View all
                </Link>
              </div>
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
