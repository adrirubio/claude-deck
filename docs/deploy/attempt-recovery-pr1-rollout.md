# Autonomous Attempt Recovery PR1 Rollout

This rollout installs normalized initial-plan approval authority only. It does not
enable continuation, diagnostics, retry policy changes, monitor transitions, or new UI.
Keep every affected preset's `autonomy_enabled` value false throughout deployment and
verification. Do not use a live Tizonia work item as a smoke test.

## 1. Back Up the Registry

Resolve `database_url` from the backend configuration before copying anything. The default
URL is relative to the backend process working directory:
`sqlite+aiosqlite:///./claude_registry.db`.

For the default layout, stop the backend and create a SQLite-consistent backup:

```bash
cd backend
sqlite3 claude_registry.db ".backup 'claude_registry.pre-attempt-recovery-pr1.db'"
chmod 600 claude_registry.pre-attempt-recovery-pr1.db
```

Keep the backup until PR2 has passed its rollout gate. A file copy while the backend is
writing is not an equivalent backup.

Confirm autonomy is off before restart:

```bash
sqlite3 claude_registry.db \
  "SELECT id, name, autonomy_enabled FROM agent_team_presets ORDER BY id;"
```

Every row used by autonomous GitHub dispatch must report `0`.

## 2. Deploy and Restart the Backend

Deploy PR1 after PR0 capability-token enforcement. Restart the backend once. Startup adds:

- `mail_messages.delivery_key` and its partial unique index;
- `github_approval_requests` and its one-pending-request partial unique index;
- the inert `github_attempt_scope_revisions` table.

The scope-revision table is persistence only in PR1. No route, scheduler, or monitor can
activate a revision.

Verify the migration:

```bash
sqlite3 claude_registry.db <<'SQL'
.schema github_approval_requests
.schema github_attempt_scope_revisions
PRAGMA index_list('github_approval_requests');
PRAGMA index_list('mail_messages');
SQL
```

The output must include `uix_github_approval_requests_pending_work_item` and
`ix_mail_messages_delivery_key`.

## 3. Reconcile Historical Approval Roots

Startup reconciles only pending context roots that match the current work item, dispatch
nonce, approval round, owner, and designated Leader:

- No matching root creates no normalized authority.
- Exactly one matching root creates one pending `initial_plan` approval row linked to it.
- More than one matching root supersedes every matching mail root, creates no approval
  row, and adds a work-item note requiring one fresh request.

This intentionally chooses no winner when history is ambiguous. Inspect affected items:

```bash
sqlite3 -header -column claude_registry.db <<'SQL'
SELECT id, issue_number, status_note
FROM github_work_items
WHERE status_note LIKE 'Multiple current approval requests were found%';
SQL
```

For each listed item, the current owner must submit one fresh request from its authenticated
pane:

```text
deck_request_work_item_approval(
  work_item_id=<id>,
  dispatch_nonce="<current nonce>",
  summary="<current bounded plan>"
)
```

Do not recreate approval with `deck_request_context`. Generic context mail remains useful
for questions, but it creates no approval authority and cannot satisfy the ack/merge gate.

## 4. Restart Agent Panes

Restart every participating agent pane after the backend is healthy. The MCP shim must
reload before agents can see `deck_request_work_item_approval` or pass an
`approval_request_id` to `deck_approve_work_item`.

PR0 capability-token rules still apply: the owner creates the request with its own session
token, and only the authenticated designated Leader can decide it. A prose reply is not an
approval decision.

Verify on a non-autonomous test preset only:

1. The owner creates one explicit approval request.
2. Repeating the same request returns the same request id and mail-root id.
3. The Leader decides that request by id.
4. Repeating the same decision returns the same decision message.
5. An opposite replay returns `409 approval_request_already_decided`.
6. A generic context request and answer do not create a `github_approval_requests` row.

## 5. Rollback

Keep autonomy off and stop the backend. Restoring the pre-deploy backup is the only complete
rollback because startup can supersede ambiguous mail roots and clear deferred retry
markers on PR-bearing work items. Reverting application code alone does not undo those data
changes.

```bash
cd backend
sqlite3 claude_registry.pre-attempt-recovery-pr1.db \
  ".backup 'claude_registry.db'"
```

Then deploy the previous integration-branch code and restart the backend and agent panes.
Any Agent Mail or approval records created after the backup are intentionally lost by this
rollback, so preserve an incident copy first if they are needed for diagnosis.

## Validation Record

Measured on the isolated PR1 worktree on 2026-08-29:

- Approval/Agent Mail/agent-team/migration scope: `833 passed in 89.08s`.
- Whole backend suite: `1002 passed, 1 failed in 96.43s`; the only failure is the
  documented pre-existing `tests/test_multi_provider_smoke.py::test_agent_bridge_session_filter_smoke`
  tracked as issue #312.
- Frontend production build: passed (`tsc -b && vite build`); Vite reported only the
  existing large-chunk advisory.
- `git diff --check`: passed.

No live Deck database was migrated, no autonomy flag was enabled, and no Tizonia dispatch or
build was started during PR1 validation.
