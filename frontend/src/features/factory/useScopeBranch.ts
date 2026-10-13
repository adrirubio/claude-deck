import { useTeamScope } from "./useTeamScope";

// The branch comes from the team's scope, through the public read of the Teams page.
export function useScopeBranch(teamId: number | null, scopeId: number) {
  const ref = useTeamScope(teamId, scopeId).scope?.base_ref;
  if (!ref) return null;
  return ref === "origin/HEAD" ? "default branch" : ref.replace(/^origin\//, "");
}
