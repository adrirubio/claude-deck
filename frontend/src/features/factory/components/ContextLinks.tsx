import { Link } from "react-router-dom";
import type { WorkProjection } from "@/types/factory";
import { anchor, destination } from "./styles";

export function ContextLinks({ work: w }: { work: WorkProjection }) {
  const target = w.links.bridge_target;
  const bridge = new URLSearchParams({
    team_id: String(w.team.id),
    ...(w.owner ? { slot_id: String(w.owner.slot_id) } : {}),
    context: "readonly",
  });
  if (target && w.session.state === "bound") {
    bridge.set("team_id", String(target.team_id));
    bridge.set("slot_id", String(target.slot_id));
    bridge.set("member_id", String(target.member_id));
    bridge.set("session_id", String(target.session_id));
  }
  const mail = w.links.mail;
  const launch = w.links.launch_plan;
  const launchName =
    launch?.slot_id === w.owner?.slot_id
      ? (w.owner?.name ?? "owner")
      : launch?.slot_id === w.approver?.slot_id
        ? "Leader"
        : launch
          ? `slot ${launch.slot_id}`
          : "";
  return (
    <nav aria-label="Work context" className="flex flex-wrap items-center gap-2">
      <Link className={anchor} to={`/teams/${w.team.id}`}>
        Team
      </Link>
      <Link className={anchor} to={`/repositories/${w.repository.scope_id}`}>
        Repository scope
      </Link>
      <Link className={destination} to={`/agent-bridge?${bridge}`}>
        {target && w.session.state === "bound"
          ? "Read-only verified session"
          : "Inspect team/slot sessions"}
      </Link>
      {mail && (
        <Link
          className={anchor}
          to={`/agent-mail?team_id=${mail.team_id}&slot_id=${mail.slot_id}&member_id=${mail.member_id}`}
        >
          Mail context
        </Link>
      )}
      {launch && (
        <Link
          className={destination}
          to={`/teams/${launch.team_id}?slot_id=${launch.slot_id}&review_launch=1`}
        >
          Review launch for {launchName}
        </Link>
      )}
      {w.owner?.configured_provider && (
        <Link
          className={destination}
          to={`/harnesses/${w.owner.configured_provider}`}
        >
          Native harness settings
        </Link>
      )}
    </nav>
  );
}
