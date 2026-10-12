import { useParams } from "react-router-dom";
import type { WorkDetailResponse } from "@/types/factory";
import { ContextLinks } from "../components/ContextLinks";
import { GithubLink } from "../components/GithubLink";
import { ProtectedRemedies } from "../components/ProtectedRemedies";
import { ReadStatus } from "../components/ReadStatus";
import { panel } from "../components/styles";
import { Time } from "../components/Time";
import { categories } from "../filterHelpers";
import { useObservation } from "../reads";

export function WorkDetailPage() {
  const { workItemId } = useParams();
  const state = useObservation<WorkDetailResponse>(
    `factory/work-items/${encodeURIComponent(workItemId ?? "")}`,
  );
  const w = state.data?.work_item;
  return (
    <section className="space-y-5">
      <h2 className="text-2xl font-semibold">Work details</h2>
      <ReadStatus state={state} />
      {w && (
        <>
          <article className={panel}>
            <h3 className="text-xl font-semibold">
              #{w.item.issue_number} {w.item.issue_title}
            </h3>
            <p>
              {categories[w.category]} · raw status {w.item.dispatch_status} ·{" "}
              {w.item.issue_type} · phase {w.item.attempt_phase}
            </p>
            <p>
              {w.team.name} · {w.repository.display_name} · owner{" "}
              {w.owner?.name ?? "Unassigned"} · configured harness{" "}
              {w.owner?.provider_label ?? "unknown"}
            </p>
            <p>
              Approver slot {w.approver?.slot_id ?? "unknown"} (
              {w.approver?.source ?? "unknown"}) · owner session{" "}
              {w.session.state} · observed runtime{" "}
              {w.session.observed_provider ?? "unknown"}
            </p>
            {w.waiting && (
              <p>
                {w.waiting.actor === "leader"
                  ? "Waiting for Leader"
                  : `Waiting for ${w.waiting.actor}`}
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
                Operator requested stop. This remains Needs attention; the agent
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
            <p className="break-all">
              PR verification head: {w.item.last_verified_sha ?? "Unconfirmed"}
            </p>
            <Time value={w.item.updated_at} label="Deck record observation" />
            <Time value={state.data!.generated_at} label="Details observed" />
          </article>
          <ContextLinks work={w} />
          <section className={panel}>
            <h3 className="font-semibold">Finite policy and authority</h3>
            <p>
              Merge policy: {w.policy.merge_policy} · maximum verification
              retries {w.policy.max_verification_retries} · maximum approval
              rounds {w.policy.max_approval_rounds}
            </p>
            <p>
              Implementation retries {w.item.retry_count} · diagnostic failed
              heads {w.item.diagnostic_retry_count} · approval rounds{" "}
              {w.item.approval_round_count}
            </p>
            <p>
              Continuation configured{" "}
              {w.policy.continuation_enabled ? "enabled" : "disabled"}; this
              does not grant revision authority. Active revision{" "}
              {w.item.active_scope_revision}:{" "}
              {w.item.active_scope_status ?? "none"}.
            </p>
            <p>
              Workspace{" "}
              {w.workspace
                ? `${w.workspace.id} (${w.workspace.state})`
                : "association unknown"}
            </p>
          </section>
          <ProtectedRemedies key={w.item.id} work={w} refresh={state.refresh} />
        </>
      )}
    </section>
  );
}
