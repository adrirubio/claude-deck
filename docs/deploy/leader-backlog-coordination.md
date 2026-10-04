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

The repository card shows active implementations versus the execution limit,
available and leased workspaces, assessment freshness, next actors and gate
reasons. A current empty eligible set says **No eligible implementation work**.
Unknown, stale, failed, capped and previous assessments remain explicit.

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
