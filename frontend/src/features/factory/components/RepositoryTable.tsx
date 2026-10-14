import { Link } from "react-router-dom";
import type { RepositoryProjection } from "@/types/factory";
import { repositoryState } from "../filterHelpers";
import { RelativeTime } from "./RelativeTime";
import { RepositoryBranch } from "./RepositoryBranch";
import { anchor } from "./styles";

const STATE_STYLE = {
  On: "border-primary/60 text-primary",
  Off: "border-border text-muted-foreground",
  "Needs attention": "border-amber-500/60 text-amber-800 dark:text-amber-300",
} as const;

export function RepositoryTable({ rows }: { rows: RepositoryProjection[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full min-w-[720px] table-fixed text-left text-sm">
        <caption className="sr-only">Repositories that Deck watches</caption>
        <thead className="bg-muted">
          <tr>
            {[
              ["Repository", "w-[30%]"],
              ["Team", "w-[16%]"],
              ["State", "w-[30%]"],
              ["Checked", "w-[12%]"],
              ["", "w-[12%]"],
            ].map(([title, width]) => (
              <th key={title || "open"} scope="col" className={`px-3 py-2 ${width}`}>
                {title || <span className="sr-only">Open</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const state = repositoryState(r);
            return (
              <tr key={r.scope_id} className="border-t align-top">
                <td className="px-3 py-2">
                  <p className="truncate font-medium" title={`${r.github.owner}/${r.github.name}`}>
                    {r.github.owner}/{r.github.name}
                  </p>
                  <p className="truncate text-xs">
                    <RepositoryBranch teamId={r.team.id} scopeId={r.scope_id} />
                  </p>
                </td>
                <td className="truncate px-3 py-2" title={r.team.name}>{r.team.name}</td>
                <td className="px-3 py-2">
                  <span className={`rounded border px-2 text-xs font-medium ${STATE_STYLE[state.label]}`}>
                    {state.label}
                  </span>
                  <p className="mt-1 text-xs text-muted-foreground">{state.reason}</p>
                </td>
                <td className="px-3 py-2">
                  <RelativeTime value={r.poll.last_polled_at} />
                </td>
                <td className="px-3 py-2">
                  <Link
                    className={anchor}
                    to={`/repositories/${r.scope_id}`}
                    aria-label={`Open ${r.github.owner}/${r.github.name}`}
                  >
                    Open ›
                  </Link>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
