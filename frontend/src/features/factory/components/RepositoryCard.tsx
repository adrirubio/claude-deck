import { Link } from "react-router-dom";
import type { RepositoryProjection } from "@/types/factory";
import { anchor, panel } from "./styles";
import { Time } from "./Time";

export function RepositoryCard({
  repository: r,
}: {
  repository: RepositoryProjection;
}) {
  return (
    <article className={panel}>
      <h3 className="font-semibold">
        <Link className={anchor} to={`/repositories/${r.scope_id}`}>
          {r.github.owner}/{r.github.name}
        </Link>
      </h3>
      <p>
        <Link className={anchor} to={`/teams/${r.team.id}`}>
          {r.team.name}
        </Link>{" "}
        · scope {r.scope_id}
      </p>
      <p>
        Configured {r.configured_enabled ? "enabled" : "paused"} · team
        automation {r.team_automation_enabled ? "on" : "off"} · scope{" "}
        {r.scope_enabled ? "on" : "off"}
      </p>
      <p>
        Intake {r.intake.state}: {r.intake.summary}
      </p>
      <p>
        Polling {r.poll.freshness.replaceAll("_", " ")} · every{" "}
        {r.poll.interval_seconds}s
      </p>
      <Time value={r.poll.last_polled_at} label="Last repository poll" />
      {r.overlap.state === "warning" && (
        <p role="note" className="rounded border border-amber-500 p-2">
          Same-label overlap: scopes {r.overlap.other_scope_ids.join(", ")} have
          independent dispatch authority. The same issue may dispatch more than
          once.
        </p>
      )}
      {r.overlap.state === "unknown" && <p>Overlap evidence unavailable.</p>}
      <div className="flex flex-wrap gap-3">
        <Link className={anchor} to={`/work?scope_id=${r.scope_id}`}>
          Scope work
        </Link>
        <Link className={anchor} to={`/teams/${r.team.id}?tab=autonomy`}>
          Inspect policy and repository configuration
        </Link>
      </div>
    </article>
  );
}
