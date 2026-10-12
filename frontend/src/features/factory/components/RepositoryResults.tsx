import { Link } from "react-router-dom";
import type { RepositoryProjection } from "@/types/factory";
import { useCursorList } from "../reads";
import { Pagination } from "./Pagination";
import { ReadStatus } from "./ReadStatus";
import { RepositoryCard } from "./RepositoryCard";
import { anchor } from "./styles";

export function RepositoryResults({ query = "" }: { query?: string }) {
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
