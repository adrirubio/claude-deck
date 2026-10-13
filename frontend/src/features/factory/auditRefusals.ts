import type { AuditEventRead } from "./auditApi";

// #520: group the refused agent requests of one window for the "Needs a look"
// panel. This is a display of recorded events. It reads and changes nothing else.

/** A refusal that repeats this often usually points to a factory defect. */
export const REFUSAL_REPEAT_THRESHOLD = 3;

export const UNKNOWN_REASON = "The reason is not known to this page.";

// One plain sentence for each code that the controller can record when it
// refuses a continuation request (GithubApprovalError in
// backend/app/services/github_approval_service.py and backend/app/api/v1/agent_teams.py). The page never shows the
// code. The code stays in the event detail.
export const REFUSAL_REASONS: Record<string, string> = {
  allowed_actions_invalid: "Some actions are not allowed in this plan.",
  allowed_paths_invalid: "The plan's file paths are not valid.",
  continuation_failed_head_limit_exceeded: "Too many failed attempts for this plan.",
  continuation_budget_exhausted: "The budget for this plan is used up.",
  continuation_command_limit_exceeded: "The plan lists more commands than the limit allows.",
  continuation_path_limit_exceeded: "The plan lists more file paths than the limit allows.",
  continuation_not_escalated: "Recovery needs a stopped attempt. This attempt is not stopped.",
  continuation_disabled: "Recovery is turned off for this repository.",
  continuation_ack_required: "The owner must first acknowledge the approved plan.",
  continuation_not_approved: "The plan is not approved yet.",
  continuation_phase_invalid: "The phase in the plan is not valid.",
  continuation_pr_not_open: "The pull request is not open.",
  continuation_pr_required: "Recovery needs the saved pull request.",
  continuation_reason_not_allowed: "The reason the attempt stopped does not allow recovery.",
  continuation_request_expired: "The request expired before anyone handled it.",
  continuation_summary_required: "The plan needs a summary.",
  continuation_escalation_changed: "The state of the attempt changed after the request.",
  continuation_delivery_link_mismatch: "The request does not match its stored record.",
  active_continuation: "A recovery plan is already active for this item.",
  active_continuation_cancel_conflict: "The active plan changed, so Deck could not cancel it.",
  active_continuation_diagnostic_head_unrestored: "The diagnostic change is not reverted yet.",
  active_continuation_head_changed: "The branch changed after the plan was made.",
  active_continuation_head_unverifiable: "Deck cannot verify the branch head.",
  active_continuation_not_cancellable: "The active plan cannot be cancelled now.",
  app_installation_id_missing: "The GitHub App is not set up for this repository.",
  approval_decision_delivery_pending: "A decision is still waiting for delivery.",
  approval_request_delivery_pending: "A request is still waiting for delivery.",
  approval_decision_link_mismatch: "The decision does not match its stored record.",
  approval_request_link_mismatch: "The request does not match its stored record.",
  approval_revision_link_mismatch: "The plan revision does not match its stored record.",
  approval_request_receipt_missing: "The stored record of the request is missing.",
  approval_request_already_decided: "The request already has a decision.",
  approval_request_already_pending: "A request is already waiting for a decision.",
  approval_request_not_found: "The request was not found.",
  approval_round_mismatch: "The request belongs to another approval round.",
  approval_round_not_open: "The approval round is not open.",
  approval_summary_required: "The request needs a summary.",
  diagnostic_revert_required: "The diagnostic change must be reverted first.",
  dispatch_nonce_missing: "The request has no current dispatch token.",
  stale_nonce: "The dispatch token in the request is out of date.",
  execution_target_invalid: "The execution target in the plan is not valid.",
  hosted_tool_target_required: "The plan needs a hosted tool target.",
  tool_fallbacks_invalid: "The tool fallbacks in the plan are not valid.",
  item_escalated: "The item is stopped and needs recovery first.",
  leader_not_registered: "The Leader is not registered in Agent Mail.",
  owner_not_registered: "The owner is not registered in Agent Mail.",
  lease_token_mismatch: "The workspace lease does not match.",
  workspace_lease_changed: "The workspace lease changed after the request.",
  workspace_lease_required: "The request needs the current workspace lease.",
  not_item_owner: "Only the owner of the item can send this request.",
  not_designated_leader: "Only the designated Leader can decide this request.",
  not_approval_requester: "Only the agent that sent the request can change it.",
  owner_cannot_approve_own_work: "An owner cannot approve its own work.",
  recovery_checkpoint_context_changed: "The recovery checkpoint changed.",
  recovery_checkpoint_paused: "Recovery is paused at a checkpoint.",
  recovery_checkpoint_stage_invalid: "The recovery checkpoint stage is not valid.",
  recovery_diagnostic_hosted_only: "This diagnostic can run only on a hosted tool.",
  recovery_only_attempt_mismatch: "The attempt does not match the recovery-only state.",
  request_not_pending: "The request is not waiting for a decision.",
  scope_mismatch: "The repository scope does not match the item.",
  scope_not_found: "The repository scope was not found.",
  scope_revision_not_found: "The plan revision was not found.",
  stale_approval_context: "The approval no longer matches the current context.",
  stale_approval_owner: "The approval no longer matches the current owner.",
  stale_approval_recipient: "The approval no longer matches the current recipient.",
  stale_continuation_context: "The plan no longer matches the current context.",
  work_item_not_found: "The work item was not found.",
  implementation_completion_actions_required: "The plan needs the actions that finish the implementation.",
  hosted_diagnostic_local_build_forbidden: "A hosted diagnostic must not run a local build.",
  hosted_tool_fallback_required: "The plan needs a hosted tool fallback.",
  cancellation_reason_required: "A cancellation needs a reason.",
};

/** The plain sentence for a recorded reason code, or the fallback. */
export function plainReason(code: string | null | undefined): string {
  return (code && REFUSAL_REASONS[code]) || UNKNOWN_REASON;
}

export interface RefusalReason {
  sentence: string;
  count: number;
  lastAt: string;
}

export interface RefusalGroup {
  key: string;
  /** "member:3", or null when the event names no member. */
  actorReference: string | null;
  memberId: number | null;
  itemId: number | null;
  itemContextKey: string | null;
  itemLabel: string;
  linkAvailable: boolean;
  total: number;
  lastAt: string;
  reasons: RefusalReason[];
  /** The same refusal came back often enough to suggest a factory defect. */
  repeated: boolean;
}

function itemLabelOf(event: AuditEventRead): string {
  const snapshot = event.context_snapshot ?? {};
  const issue = snapshot["issue_number"];
  const repo = snapshot["repo_name"];
  if (typeof issue === "number" || typeof issue === "string") {
    return typeof repo === "string" && repo ? `${repo} #${issue}` : `#${issue}`;
  }
  return event.item_id != null ? `item ${event.item_id}` : "an item";
}

function memberIdOf(event: AuditEventRead): number | null {
  const match = /^member:(\d+)$/.exec(event.actor_reference ?? "");
  return match ? Number(match[1]) : null;
}

function isRefusal(event: AuditEventRead): boolean {
  return event.event_kind === "continuation_request" && event.action_outcome === "rejected";
}

/**
 * Refused continuation requests since `windowStartMs`, grouped by member and
 * item, then by plain reason. The newest group comes first.
 */
export function groupRefusals(events: AuditEventRead[], windowStartMs: number): RefusalGroup[] {
  const groups = new Map<string, RefusalGroup>();
  for (const event of events) {
    if (!isRefusal(event)) continue;
    if (!(Date.parse(event.occurred_at) >= windowStartMs)) continue;
    const key = `${event.actor_reference ?? "unknown"}|${event.item_context_key ?? event.item_id ?? "none"}`;
    let group = groups.get(key);
    if (!group) {
      group = {
        key,
        actorReference: event.actor_reference ?? null,
        memberId: memberIdOf(event),
        itemId: event.item_id ?? null,
        itemContextKey: event.item_context_key ?? null,
        itemLabel: itemLabelOf(event),
        linkAvailable: event.live_links_available && event.item_id != null,
        total: 0,
        lastAt: event.occurred_at,
        reasons: [],
        repeated: false,
      };
      groups.set(key, group);
    }
    group.total += 1;
    if (Date.parse(event.occurred_at) > Date.parse(group.lastAt)) group.lastAt = event.occurred_at;
    const sentence = plainReason(event.sanitized_reason);
    let reason = group.reasons.find((entry) => entry.sentence === sentence);
    if (!reason) {
      reason = { sentence, count: 0, lastAt: event.occurred_at };
      group.reasons.push(reason);
    }
    reason.count += 1;
    if (Date.parse(event.occurred_at) > Date.parse(reason.lastAt)) reason.lastAt = event.occurred_at;
  }
  const result = [...groups.values()];
  for (const group of result) {
    group.reasons.sort((a, b) => b.count - a.count || Date.parse(b.lastAt) - Date.parse(a.lastAt));
    group.repeated = group.reasons.some((reason) => reason.count >= REFUSAL_REPEAT_THRESHOLD);
  }
  return result.sort((a, b) => Date.parse(b.lastAt) - Date.parse(a.lastAt));
}
