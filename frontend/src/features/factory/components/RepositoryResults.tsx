import { Link } from "react-router-dom";
import type { RepositoryProjection } from "@/types/factory";
import { useCursorList } from "../reads";
import { Pagination } from "./Pagination";
import { ReadStatus } from "./ReadStatus";
import { RepositoryTable } from "./RepositoryTable";
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
              No watched repositories match.{" "}
              <Link className={anchor} to="/repositories/new">
                Add a repository
              </Link>
            </p>
          )}
          {state.data.rows.length > 0 && <RepositoryTable rows={state.data.rows} />}
          <Pagination state={state} />
        </>
      )}
    </div>
  );
}
