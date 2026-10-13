import { useScopeBranch } from "../useScopeBranch";

export function RepositoryBranch({ teamId, scopeId }: { teamId: number; scopeId: number }) {
  const branch = useScopeBranch(teamId, scopeId);
  return branch ? <span className="text-muted-foreground">{branch}</span> : null;
}
