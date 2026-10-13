import { Link, useParams } from "react-router-dom";
import type { WorkDetailResponse } from "@/types/factory";
import { WorkItemPanel } from "@/features/agent-teams/WorkItemPanel";
import { ContextLinks } from "../components/ContextLinks";
import { GithubLink } from "../components/GithubLink";
import { ProtectedRemedies } from "../components/ProtectedRemedies";
import { RequiredCiNotice } from "../components/RequiredCiNotice";
import { ReadStatus } from "../components/ReadStatus";
import { anchor, panel } from "../components/styles";
import { Time } from "../components/Time";
import { stateLabel } from "../filterHelpers";
import { useObservation } from "../reads";
import { waitingActorLabel } from "../waitingActor";

export function WorkDetailPage() {
  const { workItemId } = useParams();
  const state = useObservation<WorkDetailResponse>(
    `factory/work-items/${encodeURIComponent(workItemId ?? "")}`,
  );
  const w = state.data?.work_item;
  const title = w ? `#${w.item.issue_number} ${w.item.issue_title}` : null;
  return (
    <section className="space-y-5">
      <nav aria-label="Breadcrumb" className="flex flex-wrap gap-2 text-sm">
        <Link className={anchor} to="/work">
          Work
        </Link>
        {title && (
          <>
            <span aria-hidden="true">›</span>
            <span className="font-medium">{title}</span>
          </>
        )}
      </nav>
      <h2 className="text-2xl font-semibold">{title ?? "Work item"}</h2>
      <ReadStatus
        state={state}
        back={{ to: "/work", label: "Back to Work" }}
        missing="work item"
      />
      {w && (
        <>
          <article className={panel}>
            <p>
              <strong>{stateLabel(w)}</strong>
              {w.item.pr_number ? ` · PR #${w.item.pr_number}` : ""} ·{" "}
              {w.repository.display_name} · {w.team.name} ·{" "}
              {w.owner
                ? `${w.owner.name} (${w.owner.provider_label ?? "harness unknown"})`
                : "Unassigned"}
            </p>
            {w.waiting && (
              <p>
                Waiting for {waitingActorLabel(w.waiting.actor)}
                : {w.waiting.summary}
              </p>
            )}
            {w.item.dispatch_status === "completed" && (
              <p>
                Tracking finished; delivery and human review are unconfirmed
                without result evidence.
              </p>
            )}
            {w.waiting?.reason_code === "abandoned_by_operator" && (
              <p>
                The Director requested a stop. This remains Needs attention; the agent
                may still run and retry may remain possible. Process termination
                is not guaranteed.
              </p>
            )}
            {w.category === "unknown" && (
              <p>
                Unknown state retained as reported; execution is not inferred.
              </p>
            )}
            <div className="flex flex-wrap gap-4">
              <GithubLink
                identity={w.repository.github}
                kind="issues"
                id={w.item.issue_number}
              >
                Open issue
              </GithubLink>
              {w.item.pr_number && (
                <GithubLink
                  identity={w.repository.github}
                  kind="pull"
                  id={w.item.pr_number}
                >
                  Open PR #{w.item.pr_number}
                </GithubLink>
              )}
            </div>
            <Time value={w.item.updated_at} label="Deck record updated" />
          </article>
          {w.item.required_ci_unreadable && (
            <RequiredCiNotice
              signal={w.item.required_ci_unreadable}
              pullRequest={w.item.pr_number}
            />
          )}
          <ContextLinks work={w} />
          {w.item.dispatch_status === "merged" ? (
            <section className={panel}>
              <h3 className="font-semibold">Outcome</h3>
              <p>
                Merged{w.item.pr_number ? ` PR #${w.item.pr_number}` : ""}. Nothing
                is left to recover on this work.
              </p>
            </section>
          ) : (
            <>
              <ProtectedRemedies
                key={w.item.id}
                work={w}
                refresh={state.refresh}
              />
              <WorkItemPanel
                key={`panel-${w.item.id}`}
                presetId={w.team.id}
                workItemId={w.item.id}
              />
            </>
          )}
          <details className={panel}>
            <summary className="cursor-pointer font-semibold">
              Technical details
            </summary>
            <div className="mt-3 space-y-2">
              <p>
                Status {w.item.dispatch_status} · {w.item.issue_type} · phase{" "}
                {w.item.attempt_phase}
              </p>
              <p>
                Approver slot {w.approver?.slot_id ?? "unknown"} (
                {w.approver?.source ?? "unknown"}) · owner session{" "}
                {w.session.state} · runtime seen{" "}
                {w.session.observed_provider ?? "unknown"}
              </p>
              <p className="break-all">
                PR verification head: {w.item.last_verified_sha ?? "Unconfirmed"}
              </p>
              <p>
                Merge policy: {w.policy.merge_policy} · most verification
                retries {w.policy.max_verification_retries} · most approval
                rounds {w.policy.max_approval_rounds}
              </p>
              <p>
                Implementation retries {w.item.retry_count} · diagnostic failed
                heads {w.item.diagnostic_retry_count} · approval rounds{" "}
                {w.item.approval_round_count}
              </p>
              <p>
                Continuation {w.policy.continuation_enabled ? "on" : "off"}; this
                gives no right to revise by itself. Active revision{" "}
                {w.item.active_scope_revision}:{" "}
                {w.item.active_scope_status ?? "none"}.
              </p>
              <p>
                Workspace{" "}
                {w.workspace
                  ? `${w.workspace.id} (${w.workspace.state})`
                  : "association unknown"}
              </p>
              <Time value={state.data!.generated_at} label="Details updated" />
            </div>
          </details>
        </>
      )}
    </section>
  );
}
