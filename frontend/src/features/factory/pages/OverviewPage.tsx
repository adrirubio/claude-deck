import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { TeamSummaries } from "@/features/agent-teams/TeamSummaryCard";
import type { AgentTeamPresetListResponse, AgentTeamSummary } from "@/types/agentTeams";
import type { OverviewResponse } from "@/types/factory";
import { ActiveWork } from "../components/overview/ActiveWork";
import { CampaignProgress } from "../components/overview/CampaignProgress";
import { NeedsYou } from "../components/overview/NeedsYou";
import { needsYouRows } from "../components/overview/needsYou";
import { StatusLine } from "../components/overview/StatusLine";
import { StatusTiles } from "../components/overview/StatusTiles";
import { ReadStatus } from "../components/ReadStatus";
import { RelativeTime } from "../components/RelativeTime";
import { anchor, destination, panel } from "../components/styles";
import { Time } from "../components/Time";
import { factoryQuery, workLink } from "../filterHelpers";
import { FactoryFilters } from "../filters";
import { useFactoryFilters } from "../filterOptions";
import { useObservation, useObservations } from "../reads";

export function OverviewPage() {
  const { params, ready } = useFactoryFilters();
  const query = factoryQuery(params);
  const state = useObservation<OverviewResponse>(
    ready ? `factory/overview${query ? `?${query}` : ""}` : null,
  );
  const filtered = Boolean(query);
  // The same reads as the team cards below, so they add no request.
  const teamId = params.get("team_id");
  const presetList = useObservation<AgentTeamPresetListResponse>("agent-teams/presets");
  const presets = (presetList.data?.presets ?? []).filter(
    (preset) => !teamId || String(preset.id) === teamId,
  );
  const { states, refresh: refreshSummaries } = useObservations<AgentTeamSummary>(
    presets.map((preset) => `agent-teams/presets/${preset.id}/summary`),
  );
  const summaries = states.map((item) => item.data);
  const rows = needsYouRows(presets, summaries);
  const summariesLoading =
    presetList.data === null || states.some((item) => item.data === null && item.error === null);
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-baseline gap-3">
          <h2 className="text-2xl font-semibold">Overview</h2>
          {state.data && (
            <span className="text-sm text-muted-foreground">
              Updated <RelativeTime value={state.data.generated_at} />
            </span>
          )}
        </div>
        <Button
          variant="outline"
          onClick={() => void Promise.all([state.refresh(), presetList.refresh(), refreshSummaries()])}
        >
          Refresh observation
        </Button>
      </div>
      <FactoryFilters />
      <ReadStatus state={state} />
      {state.data && (
        <>
          <StatusLine data={state.data} teams={presetList.data ? presets.length : null} />
          <NeedsYou rows={rows} loading={summariesLoading} />
          <CampaignProgress presets={presets} summaries={summaries} />
          <StatusTiles counts={state.data.counts} params={params} />
          <TeamSummaries teamId={teamId} onOverview />
          <ActiveWork query={query} viewAll={workLink(params, "open")} />
          <details className={`${panel} space-y-2 py-3`}>
            <summary className="cursor-pointer font-semibold">Automation details</summary>
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
          </details>
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
                  <Link className={destination} to="/repositories/new">
                    Add a repository
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
          <section className="flex flex-wrap items-baseline justify-between gap-3">
            <h3 className="text-lg font-semibold">Repositories</h3>
            <p>
              {state.data.automation.configured_scopes} watched ·{" "}
              {state.data.automation.enabled_scopes} on ·{" "}
              {state.data.automation.intake_blocked_scopes} need attention
            </p>
            <Link className={anchor} to="/repositories">
              View all ›
            </Link>
          </section>
        </>
      )}
    </section>
  );
}
