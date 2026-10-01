# Autonomous Attempt Recovery PR3 Rollout

PR3 installs diagnostic continuation and automatic recovery orchestration. It does not
enable either feature on an existing GitHub scope. PR4 owns operator UI, policy enablement,
and live replay. Keep every affected preset's `autonomy_enabled` value false and every
scope's `continuation_enabled` value false throughout this rollout.

Do not use Tizonia work item 23, PR #875, or any other live dispatch as a smoke test.

## Deployment Gate

Before deployment:

1. Stop the backend.
2. Confirm no autonomous GitHub dispatch job is running.
3. Record all scopes, preserved PRs, active revisions, and held workspace leases.
4. Create a SQLite-consistent backup with `.backup`, not a file copy.
5. Confirm every preset used by GitHub dispatch has autonomy disabled and every scope has
   continuation disabled.

For the default backend layout:

```bash
cd backend
sqlite3 claude_registry.db ".backup 'claude_registry.pre-attempt-recovery-pr3.db'"
chmod 600 claude_registry.pre-attempt-recovery-pr3.db
sqlite3 -header -column claude_registry.db <<'SQL'
SELECT id, name, autonomy_enabled
FROM agent_team_presets
ORDER BY id;

SELECT id, preset_id, repo_owner, repo_name, enabled, continuation_enabled
FROM team_github_scopes
ORDER BY id;

SELECT id, scope_id, issue_number, dispatch_status, pr_number,
       active_scope_revision, attempt_phase, escalation_reason
FROM github_work_items
WHERE pr_number IS NOT NULL OR active_scope_revision > 0
ORDER BY id;

SELECT id, scope_id, leased_item_id, leased_at
FROM github_workspaces
WHERE leased_item_id IS NOT NULL
ORDER BY id;
SQL
```

All affected autonomy and continuation values must report `0`. Stop if they do not.

## Deploy and Restart

Deploy PR3 only after PR1 and PR2. Restart the backend from `backend/` so the relative
`.env` and SQLite paths resolve to the intended files. PR3 does not add a new database
table or column; startup still runs the existing compatibility migration ladder and must
complete before any pane restarts.

PR3 adds these backend settings, with safe positive defaults:

```dotenv
GITHUB_CONTINUATION_PROPOSAL_EXPIRY_SECONDS=3600
GITHUB_CONTINUATION_LEADER_NUDGE_COOLDOWN_SECONDS=180
GITHUB_CONTINUATION_OWNER_ACK_NUDGE_COOLDOWN_SECONDS=180
GITHUB_RECOVERY_NUDGE_COOLDOWN_SECONDS=180
```

Do not tune these values during deployment. A short expiry or cooldown can convert a
deployment check into an authority or notification race.

After the backend is healthy, restart participating agent panes so their MCP shims load the
diagnostic completion and continuation transport behavior. Restarting panes does not enable
continuation. Do not export backend or operator credentials into tmux; secrets remain only in
`backend/.env` with mode `0600`.

## Installed but Disabled Behavior

With continuation disabled, PR3 creates no automatic recovery proposal, approval request,
diagnostic revision, or recovery nudge. The scheduler still processes legacy work, but its
fresh autonomy gates stop later stages if an operator disables autonomy between durable
stages.

When a later PR4 rollout enables one sandbox scope, PR3 can:

- ask the current authenticated owner for one bounded recovery proposal;
- repair request, decision, and owner-delivery mail after backend crashes without creating
  duplicate authority or notifications;
- require a distinct current Leader decision and owner acknowledgement;
- observe hosted diagnostic checks as evidence only, never as product-ready or merge state;
- count diagnostic failed heads separately from product verification history;
- require the final reported PR head to match GitHub and restore the exact baseline tree;
- return the preserved attempt to `escalated` for a bounded implementation proposal;
- stop permanently with `continuation_budget_exhausted` when the attempt-wide revision or
  diagnostic failed-head cap is consumed.

Hosted-only diagnostics may declare a temporary tool fallback such as installing `gdb` in
hosted CI when the approved policy includes `install_hosted_ci_tool` and requires reversion.
Do not install hosted-only diagnostic tools on the Deck host. A missing hosted tool is not
permission to compile locally, broaden paths, retain workflow edits, or mutate the Deck
machine.

## Observability

Run the backend at debug level only when diagnostic recovery needs investigation. Recovery
and continuation monitor records include:

- `monitor_name`;
- `work_item_id`;
- `active_scope_revision` and `scope_revision`;
- `attempt_phase`, `dispatch_status`, `revision_phase`, and `revision_status`;
- `grace_anchor` and `elapsed_grace_seconds`;
- `monitor_action` and `block_code`.

These records intentionally omit message bodies, allowed command payloads, lease tokens,
token hashes, and credentials. Treat any such secret in a monitor record as a rollout stop.

Important actions and blocks include `nudge_leader`, `nudge_owner_ack`,
`expired_pending`, `expired_approved`, `superseded_stale`,
`continuation_reason_not_allowed`, `owner_session_unavailable`, and
`continuation_budget_exhausted`.

`continuation_budget_exhausted` is a hard stop, not a retry request. Deck preserves the PR,
branch, workspace lease, nonce, revision history, product counters, and diagnostic evidence;
it sends one escalation broadcast and suppresses further automatic recovery. An operator
must inspect the history and decide whether a later, explicit policy change is safe. Do not
clear the reason or reset the item to make the monitor run again.

## Disabled Verification

Use an isolated database and non-live repository fixtures only:

1. Confirm restart preserves proposal, request-mail, decision, delivery, acknowledgement,
   diagnostic observation, and diagnostic completion rows.
2. Confirm autonomy off causes no transport repair, nudge, observation, transition, or row
   loss.
3. Re-enable only the fixture preset and confirm one idempotent next action.
4. Confirm a changed owner or PR head is rejected before diagnostic activation or
   completion mutates state.
5. Confirm green diagnostic checks do not call ready-for-review or merge behavior.
6. Confirm red diagnostic checks do not change product retry counters.
7. Confirm an exhausted continuation budget remains stopped across repeated scheduler
   passes.

Do not call the dedicated continuation-policy endpoint for a live scope during PR3 rollout.
Absent Agent Bridge controls are expected; PR4 owns those controls and the first live replay.

## Rollback

Keep autonomy and continuation disabled, stop the backend, deploy the previous integration
branch build, and restart the backend and panes. Because PR3 adds no schema, application
rollback is sufficient when no continuation scope was enabled and no PR3 authority rows
were created.

If any PR3 path ran despite the gate, preserve an incident copy and restore the pre-deploy
SQLite backup instead:

```bash
cd backend
sqlite3 claude_registry.pre-attempt-recovery-pr3.db \
  ".backup 'claude_registry.db'"
```

Restoring the backup intentionally discards Agent Mail and authority history created after
the backup. Re-read the recorded PRs and workspace leases before restarting any pane.

## Validation Record

Measured on the isolated PR3 worktree on 2026-08-29:

- Agent Mail, agent-team, and compatibility-migration scope: `973 passed in 110.77s`.
- Whole backend suite: `1142 passed, 1 failed in 113.20s`; the only failure is the
  documented pre-existing
  `tests/test_multi_provider_smoke.py::test_agent_bridge_session_filter_smoke` tracked as
  issue #312.
- Frontend production build: passed (`tsc -b && vite build`); Vite reported only the
  existing large-chunk advisory.
- `git diff --check`: passed.

No live Deck database was migrated, no autonomy or continuation flag was enabled, and no
Tizonia dispatch, build, work item, branch, or PR was touched during PR3 implementation.
