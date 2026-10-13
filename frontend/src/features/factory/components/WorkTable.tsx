import { Link } from "react-router-dom";
import type { WorkProjection } from "@/types/factory";
import { stateLabel } from "../filterHelpers";
import { GithubLink } from "./GithubLink";
import { RelativeTime } from "./RelativeTime";
import { anchor } from "./styles";

const STATE_STYLE: Record<WorkProjection["category"], string> = {
  attention: "border-destructive/60 text-destructive",
  review: "border-amber-500/60 text-amber-800 dark:text-amber-300",
  active: "border-primary/60 text-primary",
  queued: "border-border text-muted-foreground",
  finished: "border-border text-muted-foreground",
  unknown: "border-border text-muted-foreground",
};

// "Waiting for" is shown only while the work is not finished and someone is awaited.
function waitingText(work: WorkProjection) {
  if (!work.waiting || work.category === "finished") return null;
  const actor = work.waiting.actor === "leader" ? "Leader" : work.waiting.actor;
  return `Waiting for ${actor}: ${work.waiting.summary}`;
}

export function WorkTable({ rows }: { rows: WorkProjection[] }) {
  return (
    <div data-work-table className="overflow-x-auto rounded-lg border">
      <table className="w-full min-w-[720px] table-fixed text-left text-sm">
        <caption className="sr-only">
          Delivery work across selected teams and watched scopes
        </caption>
        <thead className="bg-muted">
          <tr>
            {[
              ["Issue", "w-[32%]"],
              ["Team", "w-[12%]"],
              ["State", "w-[28%]"],
              ["Owner", "w-[12%]"],
              ["PR", "w-[7%]"],
              ["Updated", "w-[9%]"],
            ].map(([title, width]) => (
              <th key={title} scope="col" className={`px-3 py-2 ${width}`}>
                {title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((work) => {
            const waiting = waitingText(work);
            return (
              <tr key={work.item.id} className="border-t align-top">
                <td className="px-3 py-2">
                  <p
                    className="truncate"
                    title={`#${work.item.issue_number} ${work.item.issue_title} · ${work.repository.display_name}`}
                  >
                    <Link className={anchor} to={`/work/${work.item.id}`}>
                      #{work.item.issue_number} {work.item.issue_title}
                    </Link>{" "}
                    <span className="text-muted-foreground">
                      {work.repository.display_name}
                    </span>
                  </p>
                </td>
                <td className="truncate px-3 py-2" title={work.team.name}>
                  {work.team.name}
                </td>
                <td className="px-3 py-2">
                  <div className="flex min-w-0 items-center gap-2">
                    <span
                      className={`shrink-0 rounded border px-2 text-xs font-medium ${STATE_STYLE[work.category]}`}
                    >
                      {stateLabel(work)}
                    </span>
                    {waiting && (
                      <span
                        className="truncate text-xs text-muted-foreground"
                        title={waiting}
                      >
                        {waiting}
                      </span>
                    )}
                  </div>
                </td>
                <td
                  className="truncate px-3 py-2"
                  title={
                    work.owner
                      ? `${work.owner.name} · ${work.owner.provider_label ?? "harness unknown"}`
                      : undefined
                  }
                >
                  {work.owner?.name ?? "Unassigned"}
                </td>
                <td className="px-3 py-2">
                  {work.item.pr_number ? (
                    <GithubLink
                      identity={work.repository.github}
                      kind="pull"
                      id={work.item.pr_number}
                    >
                      #{work.item.pr_number}
                    </GithubLink>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </td>
                <td className="px-3 py-2">
                  <RelativeTime value={work.item.updated_at} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
