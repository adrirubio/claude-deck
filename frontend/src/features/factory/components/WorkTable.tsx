import { Link } from "react-router-dom";
import type { WorkProjection } from "@/types/factory";
import { categories } from "../filterHelpers";
import { GithubLink } from "./GithubLink";
import { anchor, destination } from "./styles";
import { Time } from "./Time";

export function WorkTable({ rows }: { rows: WorkProjection[] }) {
  return (
    <div data-work-table className="overflow-x-auto rounded-lg border">
      <table className="w-full min-w-[720px] text-left text-sm">
        <caption className="sr-only">
          Delivery work across selected teams and watched scopes
        </caption>
        <thead className="bg-muted">
          <tr>
            {[
              "Issue",
              "Stage",
              "Owner",
              "Waiting",
              "PR",
              "Deck record updated",
              "Actions",
            ].map((title) => (
              <th key={title} scope="col" className="p-3">
                {title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((work) => (
            <tr key={work.item.id} className="border-t align-top">
              <td className="p-3">
                <Link className={anchor} to={`/work/${work.item.id}`}>
                  #{work.item.issue_number} {work.item.issue_title}
                </Link>
                <p>
                  {work.repository.display_name} · {work.team.name} · scope{" "}
                  {work.repository.scope_id}
                </p>
              </td>
              <td className="p-3">
                {categories[work.category]}
                <p>{work.item.dispatch_status}</p>
                <p>
                  {work.item.issue_type} · {work.item.attempt_phase}
                </p>
              </td>
              <td className="p-3">
                {work.owner?.name ?? "Unassigned"}
                <p>
                  {work.owner?.provider_label ?? "Configured harness unknown"}
                </p>
                {work.session.observed_provider && (
                  <p>Observed runtime: {work.session.observed_provider}</p>
                )}
              </td>
              <td className="p-3">
                {work.waiting
                  ? `${work.waiting.actor === "leader" ? "Waiting for Leader" : work.waiting.actor}: ${work.waiting.summary}`
                  : "No waiting actor established"}
              </td>
              <td className="p-3">
                {work.item.pr_number ? (
                  <GithubLink
                    identity={work.repository.github}
                    kind="pull"
                    id={work.item.pr_number}
                  >
                    PR #{work.item.pr_number}
                  </GithubLink>
                ) : (
                  "No PR"
                )}
              </td>
              <td className="p-3">
                <Time value={work.item.updated_at} label="Record observation" />
              </td>
              <td className="p-3">
                <Link className={destination} to={`/work/${work.item.id}`}>
                  Open details
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
