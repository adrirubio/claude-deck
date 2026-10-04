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

Coordination requires capability-token enforcement, one enabled repository scope
in the preset, and an exact current, connected, opted-in Leader binding. Existing
shared-slot cross-scope concerns remain tracked separately in #389.

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
