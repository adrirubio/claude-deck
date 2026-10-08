# Leader backlog coordination

Issue #434 adds an opt-in reconciliation cycle for explicitly assigned GitHub
issues, including issues that do not yet have the scope's dispatch-ready label.
The Leader assesses dependencies and remaining scope. Existing dispatch handles
implementation after the Leader's normal authorized admission workflow.

## Configure

In **Agent Teams → Autonomy**, each watched repository has **Configure backlog**.
Select up to 32 assigned issue numbers, a fallback interval (5–1440 minutes), and
a finite daily notification limit (1–48, default 12). Include prerequisites and
evidence issues needed for the reviewed packet. Configuration can be staged or
disabled while autonomy is off. It does not enable autonomy, add dispatch labels,
approve a plan, satisfy milestone gates, release a workspace or merge a PR.

The equivalent operator-protected route is
`PUT /api/v1/agent-teams/github-scopes/{scope_id}/coordination-policy`:

```json
{
  "expected_version": 0,
  "enabled": true,
  "issue_numbers": [7, 8, 11, 12, 13, 14],
  "fallback_seconds": 1800,
  "max_daily_requests": 12
}
```

Read the latest version from `GET .../github-scopes/{scope_id}/coordination`.
Concurrent configuration changes return a conflict; review before retrying.
Changing configuration does not reset the persisted daily quota or request
sequence. Disabling, re-enabling and restarting do not create a fresh allowance.

Coordination requires capability-token enforcement and an exact current,
connected Leader binding with Mail enabled. A team can coordinate more than one
repository. Configure each repository scope separately.

## Coordinate multiple repositories

The designated Leader reads and submits one assessment for each scope. Each
assessment has its own policy, assigned issues, token, sequence and notification
limit. An issue number belongs to its repository. For example, `owner/code#7`
and `owner/site#7` are separate issues.

Repository limits and workspace counts apply to that repository. The
`shared_slot_capacity` field lists occupied and available slot IDs across the
whole team. Active work, prepared starts, retained uncertain launch leases and
pending handoffs reserve their owners. A pending handoff also reserves its
target. A disabled scope can retain a reservation. Human review or merge wait
does not reserve an implementation slot.

Dispatch reserves the owner and repository capacity in a short database
transaction before it resets a workspace or sends a brief. `dispatched` includes
this durable start intent. It does not prove that the harness launched or that
the Leader approved work. A stale call cannot repeat the start. A crash after
the reservation requires the existing monitored recovery procedure. Known
workspace or authentication refusals return to the pending queue. A retained
uncertain launch stays occupied until its lease is released through the existing
authorized procedure. A busy handoff target is refused before notice delivery.

Sibling scope changes, new starts and handoffs invalidate stale assessments.
Scope, slot and participant authority checks remain in force. Reads have finite
context bounds. Overflow refuses coordination instead of hiding relevant work.

Cross-repository dependencies still require explicit full GitHub links in the
release plan. The Leader must confirm those prerequisites before admission.
Deck does not provide a cross-repository dependency graph or an atomic merge of
several repositories. Keep release publication under the configured review gate.

## Leader protocol

The scheduler observes the assigned issues by number, independently of the
dispatch label. It sends bounded Agent Mail requests on meaningful issue,
work-state, resource, routing and policy changes, after resume/restart, and on a
capped fallback. Poll timestamps, heartbeat timestamps and assessment writes do
not themselves change the snapshot. At most three requests are sent for an
unchanged snapshot, subject to the daily limit. Mail, request linkage and quota
are committed together before waking the exact bound Leader.

On receipt, the Leader calls `deck_get_backlog_coordination(scope_id)`, reconciles
the assigned GitHub issues against the reviewed packet and existing acceptance
evidence, then submits one disposition per assigned issue with
`deck_report_backlog_assessment`. Use the returned generation and request sequence.
Each disposition includes its issue number, controlled reason, required actor and
at least one evidence issue number within the configured assigned set.

For example, an unchanged-head PR awaiting human merge is
`human_decision_blocked` / `human_merge` / `operator`. A package held for the pilot
is `human_decision_blocked` / `pilot_decision` / `operator`. Standing validation
can use `standing` / `standing` / `reviewer`. A remaining follow-up whose scope
is ambiguous stays `needs_scope_clarification`; absence of a label is not proof
of completion. Eligible work uses `eligible` / `admission` / `leader`.

The receipt is advisory. It grants no implementation, label, approval, retry,
merge or milestone authority. The Leader uses its existing authorized workflow
to admit independent work only after verifying every reviewed gate, owner,
exclusive file assignment and resource constraint. Validation and documentation
can proceed within their existing standing assignments without dummy dispatches.

Assessment writes require the exact current authenticated Leader and current
request/snapshot after a fresh bounded GitHub read. Stale requests, changed
bindings, duplicate or missing issue dispositions and out-of-scope evidence are
refused. An identical replay changes neither freshness nor counters.

## Visibility and limits

### Follow up after an owner turn

An open harness does not schedule the next turn. A progress message can reach the
Leader before the owner stops. Issue #455 adds a durable watch for this race.
Before ending a turn with unfinished initial implementation, the current Leader
must record the remaining task and its next trigger.

Call `deck_get_backlog_coordination(scope_id)`. Select the item's
`owner_followups` entry. Use its private `followup_token` and `event_sequence`:

```text
deck_report_owner_followup(
    scope_id=1, work_item_id=10,
    action="watch", reason="unfinished_authorized_work",
    expected_sequence=0, followup_token="PRIVATE_FRESH_READ"
)
```

The watch covers a current approved initial implementation, including corrections
to a tracked PR. It requires the current approval decision, stored owner ACK,
workspace acquisition, distinct owner and Leader, and authenticated native
bindings. It does not cover scoped recovery, terminal work, handoffs, or escalated
attempts. Missing authority or unknown native evidence refuses registration.

The read records the native event baseline. A fresh completed turn that occurs
during registration becomes pending. An already completed fresh turn can also
be registered explicitly. A resumed file, stale record, live PID, heartbeat,
interrupted turn, or UI input prompt cannot prove settlement. Pi must use the
current extension that records explicit `agent_settled` provenance.

While idle, the owning Pi extension checks SDK idle state every 15 seconds. It
also checks its current Mail fence, active-run state, and pending input. This
attestation has a separate time and expires after 30 seconds. It preserves the
actual settlement ID and time. It can prove that an already recorded event
remains current during a longer Leader turn. It cannot create new settlement
debt from an old event. A cached marker or a Mail heartbeat cannot renew this
proof. A provider without fresh proof retains pending debt and suppresses wake.

After a five-second debounce, the scheduler sends one notice to the exact current
Leader when the Leader is idle. A busy Leader leaves the event pending. The notice
asks the Leader to inspect evidence and choose the next permitted action. It
never wakes the owner automatically.

A valid native identity can remain current when activity evidence expires. Deck
can record a fresh owner completion while the Leader activity is unknown. It
must wait for valid Leader idle evidence before it sends or delivers a notice.
A missing or changed native identity does not permit event capture.

Read again, then call the same tool with `action="assess"`. Use the fresh token
and event sequence. Use `reason="next_action_arranged"`, `"blocked"`, or
`"complete"`. This resolves only the coordination event. It does not complete
the issue. A Mail read receipt or an earlier backlog assessment cannot resolve a
newer event. If work remains, arrange the next authorized chunk, read again, and
register a new watch before ending the turn.
If the latest owner completion is the event just assessed, the new watch waits
for a different event. It creates no new debt and spends no shared quota.

Each new notice spends the existing daily and unchanged-snapshot notification
budget. An unread current request can cover another event without new Mail or
quota. Rearming and assessment spend no quota and reset no counter. A read but
unassessed notice has a finite fallback. Each watch registration permits at most
three new notices and three physical wake attempts, with the existing cooldown.
The shared limits can stop it earlier. An active authenticated Leader can still
read and assess a capped event.

The safe `owner_followups` projection shows waiting, pending, delivered,
assessed, invalidated, paused, capped, and uncertain delivery states. A cap or
unknown observation does not create a human decision gate. Current assigned
issues bound this projection; historical records do not enlarge the active set.
An uncertain partial terminal injection is retained and is not retried
automatically. The Leader must reconcile it from an active authenticated turn.

The team page shows owner follow-ups separately from backlog eligibility. A
current backlog assessment does not resolve a later owner completion. The
server checks the captured attempt, authority and native binding before it
marks a recorded obligation current. It rechecks the watch and authority after
the asynchronous reads. Missing, changed or paused evidence makes the record
historical. The public read changes no record and mints no authority token.

A current capped record identifies its issue, event and completion time. Its
next actor is the Leader. A supervisor can contact the Leader through the
existing channel. This notice is not a human approval request. Shared daily,
unchanged snapshot and local delivery limits remain separate. The display
does not reset a limit, infer idle activity, wake an agent or admit work.
Failed refresh, expiry, scope changes and OFF/HOLD remove current action
guidance. The existing UI request and poll supply this section.

OFF/HOLD suppresses delivery. Changed policy, native binding, attempt, approval,
ACK or workspace acquisition invalidates the old watch. Resume requires a fresh
watch. Watch state and stable Mail keys survive controller restart. The safety
supervisor retains its separate HOLD function.

The team page shows **Human actions and decision gates** above both the Roster
and Autonomy tabs. It includes dispatched review/recovery attention and explicit
Leader requests attached to backlog dispositions, including standing work that
has no dispatch item. A request provides its assigned issue, controlled action,
readiness (`requested` or `waiting_for_prerequisites`) and assigned prerequisite
issue references. PR review/merge requests also provide `pull_request_number`
and the full lowercase `expected_head_sha`. At most four requests per disposition,
16 per assessment and eight distinct PRs are accepted. For example:

```json
"human_actions": [{
  "kind": "review_pr",
  "readiness": "requested",
  "pull_request_number": 38,
  "expected_head_sha": "a2b94a1971bd19eeae16ea4436beaf00e6381c10",
  "prerequisite_issue_numbers": []
}]
```

Publish this inside the existing authenticated, fresh-read assessment. PR identity
and head are read again before acceptance. Display reads verify PR state/head with
a bounded observation cache. Merged/closed PRs resolve the displayed request;
changed heads and unavailable reads require confirmation. Missing, expired and
previous assessments stay explicit. Legacy operator dispositions appear as gates,
without invented PR identity or a claim that a decision is ready. Closing a
prerequisite issue does not record acceptance or promote a future gate. The read-only
route is `GET /api/v1/agent-teams/presets/{preset_id}/human-actions`.

This report extension uses the existing assessment JSON and optional fields inside
the MCP tool's existing `entries` argument. No dispatch item, quota reset or MCP
function-signature change is required. Requests grant no review acceptance, merge,
implementation, approval, lease or milestone authority.

The repository card shows active implementations versus the execution limit,
available and leased workspaces, assessment freshness, next actors and gate
reasons. A current empty eligible set says **No eligible implementation work**.
Unknown, stale, failed, capped and previous assessments remain explicit.
The UI expires retained eligibility at the server's observation deadline, even
if a refresh stalls or the browser tab was suspended. Each refresh has a
10-second deadline; a failed refresh remains historical and polling continues.

The authority snapshot includes assigned issues and current active implementations,
plus their current-attempt approvals, registered workspaces and roster. Unrelated
historical issues do not enlarge the write guard. Each context collection is
limited to 64 rows. An oversized active context reports
`coordination_context_limit`, grants no eligibility and sends no request; the
operator must review the assignment/resources. Coordination never archives or
rewrites authority rows to satisfy this limit.
Current authenticated participant bindings and derived availability are included
in the snapshot. Owner reconnects, disconnects and binding changes trigger a new
assessment within the debounce and daily quota. Routine heartbeat timestamps do
not create a new generation or reset limits.

Issue #436 separates notification limits from assessment publication. While an
unanswered request is within its fallback interval and still belongs to the
current Leader, snapshot changes advance that request's generation. They retain
its Mail ID, sequence, counters and actual notification time. Churn cannot extend
the fallback indefinitely. Once the fallback expires, a bounded retry can send
another notification within the existing quotas.

An active authenticated Leader can also publish without another notification.
Immediately before publication, call `deck_get_backlog_coordination(scope_id)`
and pass its private `snapshot_token`, generation and request sequence to
`deck_report_backlog_assessment`. The sequence can be zero before the first
notification. The token expires after five minutes and binds the current Leader,
policy, assessment revision and freshly observed snapshot. Keep it within the
authenticated tool exchange; do not copy it into Mail, logs or review receipts.
Publication performs another bounded GitHub read and checks current authority.
Changes to the snapshot, policy, session or notification sequence require a new
read. Restart invalidates outstanding tokens. An exact accepted replay does not
refresh the timestamp; a correction requires a fresh token. Omitting the token
retains the legacy request-bound protocol. An invalid supplied token never falls
back to that protocol.

Notification caps do not stop dispatch, team Mail or signed publication. OFF,
HOLD, scoped recovery and all existing authority checks still stop publication.
The card shows the cap reason, remaining daily budget and UTC reset time beside
assessment age. Latest observed GitHub and tracking states appear separately from
historical Leader dispositions. A current assessment remains current when the
notification allowance is exhausted, until its normal freshness or authority
checks invalidate it.

Only `dispatched` and `verifying` count against execution concurrency. Review
readiness can still retain a workspace lease; spare execution capacity and spare
workspaces are different observations. Coordination never changes the native
Working/Idle signal or creates a synthetic Working pulse.

Coordination errors are isolated after the ordinary scheduler's verification,
recovery and lease-reminder stages. Existing workflows keep their authority and
finite retry/revision policy.

## HOLD and rollout

For deployments with an external safety supervisor, set
`GITHUB_COORDINATION_HOLD_PATHS` to a JSON list of that supervisor's existing
absolute HOLD marker paths **before enabling coordination**. Any marker,
including a dangling symlink, pauses coordination. Unreadable or invalid paths
fail closed. The configured paths are never included in public/agent responses.
Autonomy OFF and scoped recovery-only operation also prevent coordination and
Leader assessment writes. The external supervisor remains responsible for
stopping existing execution; coordination does not override its HOLD.

Deployment follows the existing guarded maintenance procedure: independent
exact-head review and hosted CI, upstream master merge, fork integration
backport, maintenance pause, backup, reviewed runtime pin and explicit scope
configuration, then normal resume. Product milestone and human merge decisions
remain separate. The new table is created by the existing database initialization
mechanism; existing dispatch/approval/lease rows are not migrated or rewritten.
Install the reviewed MCP shim and refresh the harness MCP connection during the
maintenance pause so the Leader has the two new coordination tools before
enabling the scope policy.
For #436, refresh the Leader connection again so its assessment tool exposes the
optional `snapshot_token` argument. The compatibility migration adds policy and
assessment revisions plus an accepted-token digest. It preserves existing Mail
linkage, counters, assessments and all dispatch authority.
