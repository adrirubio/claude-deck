import type { TeamGithubScope, TeamGithubScopeListResponse } from "@/types/agentTeams";
import { useObservation } from "./reads";

// The full scope settings come from the public read of the Teams page.
export function useTeamScope(teamId: number | null, scopeId: number) {
  const read = useObservation<TeamGithubScopeListResponse>(
    teamId === null ? null : `agent-teams/presets/${teamId}/github-scopes`,
  );
  const scope: TeamGithubScope | null =
    read.data?.scopes?.find((candidate) => candidate.id === scopeId) ?? null;
  return { scope, error: read.error, refresh: read.refresh };
}
