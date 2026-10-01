# Autonomous Attempt Recovery PR2 Rollout

PR2 installs authenticated implementation-continuation infrastructure. It does not enable
continuation on any GitHub scope. Diagnostic continuation, automatic recovery proposals,
and Agent Bridge continuation controls remain unavailable until later phases.

## Deployment Gate

Before deployment:

1. Keep every affected preset's `autonomy_enabled` value false.
2. Confirm every existing scope has `continuation_enabled = 0`.
3. Back up the registry with SQLite's `.backup` command while the backend is stopped.
4. Record all work items with a preserved PR, active workspace lease, or pending approval.

Do not use a live Tizonia issue, work item, branch, PR, or workspace as a smoke test.

## Schema and Restart

Restart the backend once after deployment. Startup adds continuation policy columns,
work-item phase and revision fields, and compatibility defaults. Existing and new scopes
remain continuation-disabled unless an authenticated operator later changes the dedicated
continuation policy endpoint.

Verify the disabled state after restart:

```bash
cd backend
sqlite3 -header -column claude_registry.db <<'SQL'
SELECT id, preset_id, repo_owner, repo_name, continuation_enabled
FROM team_github_scopes
ORDER BY id;
SQL
```

Every row must report `0`. A generic scope create or update request cannot change this
field. Do not call the dedicated continuation-policy endpoint during PR2 deployment.

## Installed but Disabled Behavior

PR2 adds these dormant capabilities:

- the authenticated owner can propose a bounded implementation revision;
- only the designated Leader can decide its normalized approval request;
- approval alone does not resume work;
- the same authenticated owner must acknowledge delivered authority with the current
  dispatch nonce and workspace lease token;
- completion validates the current GitHub tree against exact approved paths before product
  verification resumes;
- product failures consume the active revision's budget without resetting the preserved
  PR, workspace, branch, nonce, or retry history;
- a dedicated monitor handles an already-active, PR-bearing continuation.

These paths refuse while `continuation_enabled = 0`. Retry also refuses when a preserved
PR, active scope revision, or pending approval would make reset destructive. A PR-less
escalated item with a held workspace remains eligible for the existing deferred retry.

## Agent and Operator Surfaces

Restart participating agent panes only in a non-autonomous test preset when the new MCP
tools must be inspected. Safe list projections expose revision status and retry eligibility,
but omit workspace lease tokens, lease-token hashes, and canonical commands for callers
that do not own the revision. Only authenticated owner continuation context can return the
live lease token.

PR2 does not add Agent Bridge continuation UI. Do not interpret absent controls as a failed
deployment. The UI phase follows separately.

Diagnostic proposals return `409 diagnostic_continuation_not_available`. PR2 does not add
diagnostic observers, diagnostic execution, or automatic recovery-nudge loops.

## Validation Without Enablement

Use an isolated database and a non-autonomous test preset. Verify:

1. Existing scopes read `continuation_enabled = false`.
2. A diagnostic proposal is refused with the documented code.
3. A retry projection reports the same eligibility and block code enforced by the retry
   route.
4. Non-owner revision history omits canonical commands and all lease secrets.
5. No live scope, preset, work item, workspace, or PR changes during validation.

Do not run an end-to-end continuation until a separate rollout decision explicitly enables
one sandbox scope.

## Rollback

Keep autonomy and continuation disabled, stop the backend, and restore the pre-deployment
SQLite backup. Reverting application code alone does not remove additive schema or authority
history. Restart the previous integration-branch build, then confirm the recorded live work
items, PRs, and workspace leases still match the pre-deployment inventory.

## Validation Record

Measured on the isolated PR2 worktree on 2026-08-29:

- Agent Mail, agent-team, and compatibility-migration scope: `912 passed`.
- Whole backend suite: `1081 passed, 1 failed`; the only failure is the documented
  pre-existing `tests/test_multi_provider_smoke.py::test_agent_bridge_session_filter_smoke`
  tracked as issue #312.
- Frontend production build: passed (`tsc -b && vite build`); Vite reported only the
  existing large-chunk advisory.
- `git diff --check`: passed.

No live Deck database was migrated, no autonomy or continuation flag was enabled, and no
Tizonia dispatch or build was started during PR2 validation.

Implementation-review hardening also binds a submitted continuation to the exact PR head
that passed path validation. If the head changes before green promotion, Deck returns the
same revision to the owner for a new completion report and does not spend its failed-head
budget. Handoffs invalidate all nonterminal authority held by the previous owner, including
pending approval roots, and lease-bearing continuation context requires the database-current
owner member as well as the slot.

The final implementation review also enforces one nonterminal revision per attempt, binds
Leader decisions and lease claims to database-current membership at the write boundary, and
redacts continuation scope details from generic mail-list/thread projections. A durable
submission timestamp prevents check-signal grace from sliding across polls. Merged and
closed PRs terminate submitted authority, failure counters and lifecycle state persist before
notification, and idle-progress nudges use deterministic delivery keys for crash-safe replay.
