---
name: deck-factory-supervisor
description: Prepare, supervise, maintain and finish a Deck team working on a GitHub backlog when the operator delegates factory execution. Use for team startup, supervised goals, stalled work, maintenance handoffs and completion; ordinary application coding does not need this skill.
---

# Deck factory supervisor

Use this skill for the outer supervising agent. Keep the team's authenticated Leader responsible for its plans and backlog assessments.

## Load the operating reference

Link the saved team to its parent issue with `parent_issue_url`.
Use `description` for the outcome. Keep completion conditions in the parent issue.
Use `deck_get_team_summary` to read existing attention, human actions, HOLD, pauses, effort totals, and next actors.
Read its optional `required_ci_unreadable` array for unreadable CI after the 15-minute grace period.
Work item responses supply the same signal and `checks_unavailable_since`.
Use the safe reason and fixed next steps to check GitHub access and configured workflows.
This replaces manual comparison of repeated status notes.
Unreadable checks consume no retry or diagnostic budget.
A later successful read clears the signal, including pending or failed checks.
Check expiry and coverage. Incomplete, stale, unknown, or changed-context reports keep the whole estimate Unknown.
The read limits observations to eight seconds and 64 unfinished items. Its effort total excludes waiting time.
The summary grants no approval, owner contact, resume, retry, lease, merge, or milestone authority.
Read optional `supervisor_observation` for supervisor health and the bound actor address.
The original `supervisor` literal remains `none` for older clients.
The Director binds the optional external actor. One actor can supervise several teams.
Binding grants no new permission.

After a successful check, call `deck_supervisor_checkin(preset_id, next_check_at, note)`.
Promise a future ISO 8601 check time within 24 hours.
The tool uses the bound external actor credential. It accepts no credential argument.
Deck records the check time and derives `healthy`, `late`, or `absent` from its clock.
This replaces manual tick reporting. `none` means supervision is optional and unbound.
Late and absent states expose “Supervisor check-in overdue”.
The default grace is the larger of 30 minutes and twice the last promised interval.
Only the Director changes the grace period.
Check-ins grant no approval, retry, lease, merge, or milestone authority.

Members use the `supervisor_address` from `deck_whoami` or their dispatch brief.
They send messages with `deck_send_message(to_supervisor_actor_id=..., body=...)`.
The actor reads `GET /api/v1/external/agent-mail/supervisor-inbox`.
Foreign actors and unbound teams get a refusal.
Keep Leader, Supervisor, and retained operator decisions in their existing escalation order.

Locate the Deck source checkout supplied by the operator or recorded campaign. Read `docs/guide/supervised-factory-playbook.md` there. When this skill is used directly from its repository, that file is at `../../docs/guide/supervised-factory-playbook.md` relative to this directory.

Read the campaign brief, current parent issue and protected installation record. Check their source versions. If the playbook is absent, obtain the matching Deck source or a path from the operator. Continue independent read-only discovery where useful; do not invent the maintenance procedure from an old session.

The playbook is the process reference. Load the relevant linked API or maintenance contract for the operation in progress. Keep installation credentials, private launch settings and account details out of messages, GitHub artifacts and documentation.

## Select the work

- **Prepare:** Reconcile existing issues. Record completion conditions, branches, dependencies, permissions and limits. Provision the smallest useful roster and isolated writing workspaces. Check actual native startup, authenticated Mail, database and durable supervision before authorized activation. Confirm Deck's Claude team prompt block and launch trust results. Check first-turn Claude identity and the Codex restart condition. Give each member a supervisor channel and an escalation order before activation.
- **Supervise:** Read the outer goal, current GitHub heads, checks, owner authority, leases, native evidence and Leader assessments. Follow the campaign's real monitoring mechanism. Publish useful checkpoints and short remaining-work summaries. Let independent eligible work continue. At each check, scan the panes for screens that wait for input, and verify an incident claim before you act on it.
- **Recover:** Classify the blocker from evidence. Resolve routine defects within delegation. Preserve work, authority and counters. Use supported observation recovery or a bounded approved continuation. A live process is not proof of progress or permission.
- **Maintain:** Use the playbook's safe handoff and reviewed operation. Disabling intake does not stop active owners. Bind review and proof to the deployed source. Check retained database, private configuration, sessions and leases before releasing operation-specific holds and resuming.
- **Finish:** Complete the accepted outcome and any retained publication gate. Record exact sources, artifacts, checks and rollback. Reconcile requests and assessments. Disable completed dispatch. State what remains running, then complete the goal.

Use the [shared agent status](../../docs/api/agent-teams.md#shared-agent-status) instead of comparing separate screen status rules.
Keep online, activity, and wake facts separate.
Use the native idle event time for idle duration.
Unknown or expired status grants no approval, contact renewal, delivery, or recovery authority.

## Apply the campaign's authority

Use existing explicit authorization. Do not ask again for an action already delegated. Finish authorized preparation so a retained decision is concrete and reviewable.

Loading this skill grants no permissions. Create a goal only when requested. Use the installed goal tool's status and budget rules. A factory pause can leave the goal active for repair. Claim periodic supervision only while a real continuation mechanism is running.

If no goal tool exists, report that limitation and use the durable campaign record. Do not fabricate a goal or scheduled monitoring.

Do not change models, limits, merge policy or retained decisions beyond delegation. A genuine security HOLD stops affected autonomy and needs operator instructions. Do not retry, rephrase, switch models or clear that HOLD on your own.

Use the operator API with the authorized operator identity. Do not borrow an owner or Leader credential, edit live authority rows, forge an ACK or rewrite a session binding to bypass a refusal.

## Keep review and reporting efficient

Use the team's independent verifier for completed source. Add a focused external review for a material operational change or a process retrospective at a useful decision point. Reviewer advice does not grant authority.

Bind findings and evidence to full source SHAs. Review changed contracts and carry forward valid unaffected evidence. Follow the configured current-head CI gate. Do not duplicate broad suites at each handoff or turn every checkpoint into final review.

Keep one current summary publisher and one finding register. Keep human instructions in the main issue body. State the exact action, reason, source, required actor and completion condition. Clear or supersede the request when it ends.

Use the saved controlled-language setting. Remaining work needs three short fields: remaining tasks, active effort estimate or Unknown, and the next actor/action. Keep detailed evidence in linked records.
