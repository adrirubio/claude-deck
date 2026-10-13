import { Link, useNavigate, useParams } from "react-router-dom";
import { RepositorySettings } from "@/features/agent-teams/RepositorySettings";
import type { RepositoryDetailResponse, WorkListResponse } from "@/types/factory";
import { RelativeTime } from "../components/RelativeTime";
import { ReadStatus } from "../components/ReadStatus";
import { anchor } from "../components/styles";
import { repositoryState } from "../filterHelpers";
import { useObservation } from "../reads";
import { useScopeBranch } from "../useScopeBranch";
import { useTeamScope } from "../useTeamScope";

export function RepositoryPage() {
  const { scopeId } = useParams();
  const navigate = useNavigate();
  const id = encodeURIComponent(scopeId ?? "");
  const state = useObservation<RepositoryDetailResponse>(`factory/repositories/${id}`);
  const repository = state.data?.repository ?? null;
  const work = useObservation<WorkListResponse>(
    repository ? `factory/work-items?scope_id=${id}&limit=1` : null,
  );
  const scope = useTeamScope(repository?.team.id ?? null, repository?.scope_id ?? 0);
  const branch = useScopeBranch(repository?.team.id ?? null, repository?.scope_id ?? 0);
  const name = repository ? `${repository.github.owner}/${repository.github.name}` : null;
  const status = repository ? repositoryState(repository) : null;
  const refreshAll = async () => {
    await Promise.all([state.refresh(), scope.refresh()]);
  };
  return (
    <section className="space-y-5">
      <nav aria-label="Breadcrumb" className="flex flex-wrap gap-2 text-sm">
        <Link className={anchor} to="/repositories">
          Repositories
        </Link>
        {name && (
          <>
            <span aria-hidden="true">›</span>
            <span className="font-medium">{name}</span>
          </>
        )}
      </nav>
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-2xl font-semibold">{name ?? "Repository"}</h2>
        {status && (
          <span className="rounded border px-2 text-xs font-medium">{status.label}</span>
        )}
      </div>
      <ReadStatus
        state={state}
        back={{ to: "/repositories", label: "Back to Repositories" }}
        missing="repository"
      />
      {repository && status && (
        <>
          <div className="space-y-1 text-sm">
            <p className="text-muted-foreground">{status.reason}</p>
            <p>
              Team:{" "}
              <Link className={anchor} to={`/teams/${repository.team.id}`}>
                {repository.team.name}
              </Link>
              {branch && <> · Branch: {branch}</>}
              {" · "}Checked: <RelativeTime value={repository.poll.last_polled_at} />
            </p>
            <p>
              {work.data
                ? `${work.data.counts.total} ${work.data.counts.total === 1 ? "item" : "items"} · ${work.data.counts.active} active · `
                : ""}
              <Link className={anchor} to={`/work?scope_id=${id}`}>
                View in Work ›
              </Link>
            </p>
          </div>
          {scope.scope ? (
            <RepositorySettings
              scope={scope.scope}
              autonomyEnabled={repository.team_automation_enabled}
              refresh={refreshAll}
              onRemoved={() => navigate("/repositories")}
            />
          ) : (
            <p role="status" className="text-sm text-muted-foreground">
              {scope.error ? "Settings could not be loaded. Use Refresh to try again." : "Loading settings…"}
            </p>
          )}
        </>
      )}
    </section>
  );
}
