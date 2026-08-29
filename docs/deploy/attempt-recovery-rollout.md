# Attempt Recovery Rollout

## Purpose

Deploy the four-PR autonomous attempt recovery series to the integration environment while
keeping continuation and autonomy disabled. This procedure does not authorize the Tizonia
replay or a merge to `master`.

## Release Order

Deploy one integration tip containing, in order:

1. PR1 — normalized approval authority;
2. PR2 — non-destructive attempt continuation;
3. PR3 — diagnostic recovery orchestration;
4. PR4 — Agent Bridge visibility, operator controls, preflight, and replay artifacts.

PR3 merged to `feature/autonomous-github-dispatch` as
`b4d444c7b469dafb52de0e2a2bb895a7fa43a851`. Record the reviewed PR4 merge SHA in the soak
log before deployment.

## Hard Gates

- The integration branch, not `master`, is the deployment source.
- The reviewed PR4 head is merged and the integration worktree is clean.
- Tizonia preset autonomy is off.
- Tizonia scope continuation is off.
- Tizonia PR #875 remains under human merge policy.
- No local Tizonia compilation or diagnostic tool installation occurs.
- Issue #329, cross-project Agent Mail prompt injection, is resolved or the replay runtime is
  isolated so unrelated sessions cannot receive Deck prompts.

## Backup

1. Record the running Deck commit, process IDs, tmux targets, and configured database path
   without printing environment values.
2. Disable autonomy before stopping any process.
3. Stop the backend cleanly so SQLite checkpoints its WAL.
4. Use SQLite's backup API or copy the closed database to a timestamped file outside the
   repository.
5. Record the backup path and SHA-256 digest in the private operator log. Do not commit the
   database or its WAL/SHM files.

## Deploy

1. Fast-forward the deployment worktree to the reviewed integration merge SHA.
2. Confirm `git status --short` is empty.
3. Start the backend from its own `backend` directory so the relative database setting
   resolves to the intended registry.
4. Wait for `/health` and `/api/v1/health` to report healthy.
5. Restart the Agent Mail MCP shims and team panes so they load the merged tool contracts.
6. Do not enable continuation or autonomy.

## Migration Checks

Use read-only API responses and a read-only SQLite connection to verify:

- normalized approval and scope-revision tables exist;
- the single-pending approval constraint exists;
- continuation columns exist on work items and scopes;
- every scope still has `continuation_enabled = false` unless a separately reviewed rollout
  explicitly says otherwise;
- preset `tizonia-v1` has `autonomy_enabled = false`;
- work item 23 still references issue #821, PR #875, the preserved owner, nonce, branch, and
  workspace lease;
- no migration created a new approval request or revision for item 23.

Never print lease tokens, token hashes, capability tokens, GitHub credentials, operator
tokens, commands, or message bodies.

## Validation

Run the read-only preflight only after all processes are healthy:

```bash
scripts/attempt-recovery-preflight.sh \
  http://127.0.0.1:8000 \
  2 \
  1 \
  23
```

The command must report autonomy and continuation off, the expected item/PR identity, a
preserved workspace, finite caps, at least one fresh authenticated MCP registration for the
owner and Leader, and exactly one observed tmux pane for each slot. Codex reports one physical
session through separate MCP and hook rows; those rows must not be counted as separate agents.

## Rollback

Rollback is required if startup, migration, API projection, session registration, or
preflight fails.

1. Keep autonomy and continuation off.
2. Stop the backend and MCP shims.
3. Restore the recorded pre-deployment Git commit.
4. Restore the database backup only if the migration itself changed data incorrectly. Never
   restore a database while a backend process is running.
5. Restart Deck and repeat read-only health checks.
6. Record the failure and stop. Do not attempt the Tizonia replay.

## Cleanup

After each phase PR is merged and its branch is clean and fully pushed, remove its isolated
worktree with `git worktree remove <path>`. Never force-remove a dirty or unmerged worktree.

The integration branch remains held from `master` until the completed soak log receives an
independent review approval.
