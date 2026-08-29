# PR3 — Diagnostic Recovery Orchestration Implementation Plan

> **For implementation agents:** Start only after PR2 is reviewed and merged into
> `feature/autonomous-github-dispatch`. Keep continuation disabled throughout development.

**Goal:** Add bounded diagnostic continuations, isolate expected-red diagnostic CI from
product retry accounting, prove diagnostic tree restoration, and let the scheduler recover
eligible escalated attempts through owner proposal, Leader decision, delivery, and ack
without coordinator intervention.

**Architecture:** Diagnostic work is an `attempt_phase`, not a dispatch status. The existing
verification scheduler observes diagnostic check runs through a separate path that cannot
promote or merge a PR. `diagnostic_completed` proves current Git tree identity equals the
persisted baseline before returning the attempt to an escalated implementation proposal.
`monitor_recovery` repairs every durable authority/mail boundary, applies cooldowns and
expiry, and nudges only authenticated owner/Leader participants. Scope-level hard caps stop
unbounded recovery.

**Spec:** `docs/superpowers/specs/2026-08-29-autonomous-attempt-recovery-design.md`,
Revision 7, especially §§5.2–5.4, 6, 7.1–7.3, 8, 9.1.1–9.2, 11–13, and 14 PR3.

**Dependency:** Merged PR2 implementation continuation. Record its integration merge SHA.

**Target:** One PR into `feature/autonomous-github-dispatch`, never `master`.

## PR Boundary

PR3 completes backend/agentic autonomy recovery but does not add Agent Bridge UI or execute
the live Tizonia replay.

- Continuation remains disabled on live scopes until PR4 and deployment checks finish.
- No frontend files change in PR3.
- No local Tizonia build, tool installation, branch mutation, or dispatch report occurs.
- Human merge remains unchanged.

## Global Safety Constraints

- Use a new isolated worktree based on the PR2 merge tip.
- Never touch the live DB, Tizonia workspace, work item 23, or PR #875.
- Diagnostic tools are installed only by approved hosted CI changes; never on the Deck host.
- Diagnostic check results cannot call `_promote_verified_item`, ready a PR, or merge.
- Diagnostic failures never touch `retry_count` or `last_verified_sha`.
- Product failures never touch diagnostic counters.
- Every scheduler recovery action is persisted/idempotent and respects autonomy-off.
- Human stop reasons and `continuation_budget_exhausted` are never automatically continued.
- Do not kill, impersonate, or report status for a live agent during tests or replay planning.
- Commit each task and stop after opening the PR.

## File Map

| File | Action | Responsibility |
|---|---|---|
| `backend/app/models/schemas.py` | Modify | Diagnostic proposal/report/evidence schemas |
| `backend/app/services/github_approval_service.py` | Modify | Diagnostic policy, fallback, expiry, delivery repair |
| `backend/app/services/github_verification_service.py` | Modify | Diagnostic check observer/accounting/restoration |
| `backend/app/services/github_dispatch_service.py` | Modify | Recovery monitor, nudge state, phase transitions |
| `backend/app/services/github_dispatch_scheduler.py` | Modify | Final monitor ordering |
| `backend/app/api/v1/agent_teams.py` | Modify | Diagnostic completion branch and evidence validation |
| `backend/mcp_shim/agent_mail_server.py` | Modify | Diagnostic proposal/report fields and conflict details |
| `backend/tests/agent_teams/test_github_verification_service.py` | Modify | Diagnostic observer/restoration/budgets |
| `backend/tests/agent_teams/test_github_dispatch_service.py` | Modify | Recovery monitor/delivery/expiry/cooldowns |
| `backend/tests/agent_teams/test_github_dispatch_scheduler.py` | Modify | Full scheduler order and autonomy toggles |
| `backend/tests/agent_teams/test_github_workspace_api.py` | Modify | Diagnostic proposal/report authorization |
| `backend/tests/agent_mail/test_mcp_shim.py` | Modify | Diagnostic MCP and 409 detail propagation |
| `docs/deploy/attempt-recovery-pr3-rollout.md` | Create | Backend recovery rollout with continuation still off |

## Task Index

| Task | Deliverable |
|---|---|
| 1 | Diagnostic proposal policy and execution targets |
| 2 | Diagnostic verification observer |
| 3 | Diagnostic completion and tree restoration |
| 4 | Recovery eligibility and owner proposal nudges |
| 5 | Leader decision/delivery/ack crash repair |
| 6 | Expiry, cooldowns, and budget stops |
| 7 | Scheduler integration and telemetry |
| 8 | Restart/autonomy/race regression sweep |
| 9 | Rollout documentation and PR validation |

---

## Task 1 — Activate Diagnostic Proposal Policy

**Files:** `backend/app/models/schemas.py`,
`backend/app/services/github_approval_service.py`,
`backend/tests/agent_teams/test_github_workspace_api.py`

- [ ] Accept `phase = diagnostic` only when the scope has continuation enabled and the
  requested execution target/policy is valid.
- [ ] Require diagnostic proposals to include:
  - `execution_target`;
  - exact paths/actions/commands;
  - evidence objective;
  - finite failed-head budget;
  - `revert_diagnostic_changes`;
  - hosted tool fallbacks for every named required hosted tool.
- [ ] Reject local build/compile commands when scope/build policy or proposal is hosted-only.
- [ ] Reject `install_hosted_ci_tool` unless target includes `hosted_ci`, a package/tool is
  named, installation is temporary, and revert is mandatory.
- [ ] Normalize tool-fallback payloads into a closed schema. Unknown keys/actions fail.
- [ ] Derive baseline head/tree/workspace exactly as implementation proposals do.
- [ ] Count diagnostic proposals against attempt-wide revision caps.
- [ ] Keep the item escalated until Leader approval, delivery, and owner ack.

**Mutation checks:** allow diagnostic before PR3 flag; accept local gdb install; omit revert;
infer target from command prose; permit unlimited failed heads.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_workspace_api.py -q -p no:warnings
```

**Commit:** `feat: validate diagnostic continuation policy`

---

## Task 2 — Add Diagnostic-Only Check Observation

**Files:** `backend/app/services/github_verification_service.py`,
`backend/tests/agent_teams/test_github_verification_service.py`

- [ ] Add a diagnostic observer selected only for active diagnostic revision plus
  `dispatch_status = dispatched`.
- [ ] Fetch/validate current PR identity using existing protections.
- [ ] Record pending/green/red check evidence on the revision without moving review status.
- [ ] On a distinct failed diagnostic head:
  - update `diagnostic_last_verified_sha`;
  - increment `diagnostic_retry_count` and revision failed-head count;
  - store evidence/message once;
  - leave product counters untouched.
- [ ] Same-head polls change no counter/message.
- [ ] Green diagnostic checks remain evidence only; never call `_promote_verified_item`,
  merge, mark ready, or complete the revision.
- [ ] If the revision budget is exceeded, mark it exhausted and return the item to escalated
  without clearing attempt state. Apply attempt-wide hard caps.
- [ ] Keep legacy and implementation selector behavior from PR2 unchanged.

**Mutation checks:** reuse `_record_failed_verification_attempt`; promote on green; increment
product counter then subtract; count same head; run diagnostic observer in review status.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_verification_service.py -q -p no:warnings
```

**Commit:** `feat: observe diagnostic checks separately`

---

## Task 3 — Prove Diagnostic Restoration Before Completion

**Files:** `backend/app/models/schemas.py`,
`backend/app/api/v1/agent_teams.py`,
`backend/app/services/github_verification_service.py`,
`backend/mcp_shim/agent_mail_server.py`,
`backend/tests/agent_teams/test_github_workspace_api.py`,
`backend/tests/agent_teams/test_github_verification_service.py`,
`backend/tests/agent_mail/test_dispatch_status_tool.py`

- [ ] Add `diagnostic_completed` to `_DISPATCH_STATUS_RULES` as owner-only and lease-token
  required.
- [ ] Require revision, nonce, result summary, evidence, current/restored head, and lease
  fields after auth but before mutation.
- [ ] Re-fetch current owner, nonce, active diagnostic revision, PR, workspace id, and lease.
- [ ] Require reported head equals current PR head.
- [ ] Fetch the current commit's root tree and require exact equality with
  `baseline_tree_sha`. Different commit SHA is allowed; different tree is not.
- [ ] Do not use Compare API files as restoration authority.
- [ ] On mismatch/inconclusive GitHub data return stable conflict and leave diagnostic active.
- [ ] On success atomically:
  - complete the diagnostic revision;
  - persist summary/evidence;
  - set phase back to implementation;
  - set item escalated;
  - restore originating escalation reason;
  - clear only continuation-active clocks/state;
  - retain PR, workspace, nonce, counters, and audit rows.
- [ ] Notify the owner to propose the smallest informed implementation revision; do not
  authorize production edits automatically.

**Mutation checks:** compare commit SHA equality; trust reported tree; accept missing
evidence; enter verifying; clear diagnostic counters; alter product retry history.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_workspace_api.py \
  tests/agent_teams/test_github_verification_service.py \
  tests/agent_mail/test_dispatch_status_tool.py -q -p no:warnings
```

**Commit:** `feat: require diagnostic tree restoration`

---

## Task 4 — Implement Recovery Eligibility and Owner Nudges

**Files:** `backend/app/services/github_dispatch_service.py`,
`backend/tests/agent_teams/test_github_dispatch_service.py`

- [ ] Add `monitor_recovery(db, scope, slots)` selecting only escalated items under enabled
  autonomy plus enabled continuation.
- [ ] Require allow-listed escalation reason, PR, owner, nonce, leased workspace, and
  nudgeable authenticated owner session.
- [ ] Refuse dispatch-label removal, operator abandonment, closed-unmerged PR,
  approval-round exhaustion, continuation-budget exhaustion, unknown/NULL reasons, and
  missing preserved state.
- [ ] When no pending request exists, send one idempotent recovery instruction to the owner
  and stamp `continuation_nudged_at`.
- [ ] Include failure evidence and require read-only diagnosis followed by the explicit
  request tool; Deck does not fabricate the owner's proposal.
- [ ] Cool down repeated nudges and preserve state while autonomy is off.
- [ ] When owner is offline, remain escalated; do not let Leader self-propose/approve.

**Mutation checks:** scan while autonomy off; continue human stop; create proposal as Deck;
nudge offline owner forever; omit PR/workspace precondition.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_dispatch_service.py -q -p no:warnings
```

**Commit:** `feat: nudge recoverable escalated owners`

---

## Task 5 — Repair Decision, Delivery, and Ack Boundaries

**Files:** `backend/app/services/github_approval_service.py`,
`backend/app/services/github_dispatch_service.py`,
`backend/tests/agent_teams/test_github_dispatch_service.py`,
`backend/tests/agent_mail/test_api.py`

- [ ] For pending authority without request mail/link, create/recover/link one request root.
- [ ] For pending request with unread root, nudge designated Leader under cooldown.
- [ ] For terminal decision missing decision mail/link, create/recover/link it first.
- [ ] For approved revision missing owner delivery/link, create/recover/link one delivery.
- [ ] For delivered/unacknowledged revision, nudge only the current owner.
- [ ] Require decision evidence link before owner delivery.
- [ ] Use stable delivery keys from the spec at every boundary.
- [ ] Re-read owner/Leader/nonce/round/revision before each repair; stale rows become
  superseded rather than delivered.
- [ ] Test crashes after every authority/mail/link commit and concurrent scheduler workers.

**Mutation checks:** random delivery key; deliver before decision link; use stale owner;
duplicate mail/receipts; broadcast ack nudge.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_dispatch_service.py \
  tests/agent_mail/test_api.py -q -p no:warnings
```

**Commit:** `feat: repair continuation delivery after crashes`

---

## Task 6 — Enforce Expiry, Cooldowns, and Hard Stops

**Files:** `backend/app/services/github_approval_service.py`,
`backend/app/services/github_dispatch_service.py`,
`backend/tests/agent_teams/test_github_dispatch_service.py`

- [ ] Define settings/defaults for proposal expiry, Leader nudge cooldown, owner ack cooldown,
  and recovery nudge grace using existing settings patterns.
- [ ] Expire pending request plus proposed revision and mark linked mail root terminal in one
  transaction.
- [ ] Expire approved-but-unacknowledged revisions safely; item remains escalated.
- [ ] Never expire an active revision through the pending-request timer.
- [ ] Count all proposed revisions and distinct failed heads against scope hard caps.
- [ ] Escalate `continuation_budget_exhausted` when caps are exhausted and suppress further
  automatic recovery.
- [ ] Re-enable after autonomy-off continues from persisted timestamps without creating
  duplicates; do not pretend disabled wall time was owner activity.

**Mutation checks:** expire one table only; approve after expiry; reset cap counters;
auto-continue budget stop; create new nudge each tick.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_dispatch_service.py -q -p no:warnings
```

**Commit:** `feat: bound autonomous recovery attempts`

---

## Task 7 — Complete Scheduler Ordering and Telemetry

**Files:** `backend/app/services/github_dispatch_scheduler.py`,
`backend/app/services/github_dispatch_service.py`,
`backend/tests/agent_teams/test_github_dispatch_scheduler.py`

- [ ] Invoke after watcher/pending dispatch:
  1. `monitor_dispatched`;
  2. `monitor_continuation`;
  3. verification processing;
  4. `monitor_recovery`;
  5. held-lease reminders.
- [ ] Ensure each stage re-queries and commits before the next.
- [ ] Add one scheduler fixture containing an initial dispatch, active continuation,
  diagnostic continuation, verification escalation, and recoverable escalated item.
- [ ] Verify each item is touched only by its intended stage and newly escalated verification
  can be recovery-nudged in the same pass.
- [ ] Emit structured redacted monitor events with monitor, item, revision, phase/status,
  grace anchor/delta, action, and block code.
- [ ] Test log records do not contain lease token, commands, message bodies, credentials, or
  tool fallback secrets.

**Mutation checks:** recovery before verification; reuse stale list; omit commit; invoke two
monitors for one row; log full revision payload.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_dispatch_scheduler.py -q -p no:warnings
```

**Commit:** `feat: schedule autonomous attempt recovery`

---

## Task 8 — Run Restart, Autonomy, and Race Regressions

**Files:** tests only unless a PR3-owned defect is found.

- [ ] Restart after proposal authority, request mail, decision authority, decision mail,
  delivery mail, ack, diagnostic red, revert push, and diagnostic completion.
- [ ] Toggle autonomy off at every durable state; verify no nudge/transition and no row loss.
- [ ] Re-enable and prove exactly one next action.
- [ ] Race owner handoff against proposal, decision, delivery, ack, observer, and completion.
- [ ] Race PR head movement against diagnostic ack/completion.
- [ ] Prove a green diagnostic never changes ready/merge state.
- [ ] Prove expected-red diagnostic heads never alter product counters.
- [ ] Prove hard budget stop stays stopped.
- [ ] Run every named mutant from Tasks 1–7.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_mail tests/agent_teams \
  tests/test_sqlite_compat_migrations.py -q -p no:warnings
```

**Commit:** `test: harden autonomous diagnostic recovery`

---

## Task 9 — Document Disabled Rollout and Validate PR

**Files:** `docs/deploy/attempt-recovery-pr3-rollout.md`

- [ ] Document backend deployment, migration backup, process/pane restart, log fields,
  rollback, and hard-stop interpretation.
- [ ] Keep every live scope continuation-disabled. PR4 owns UI/config enablement and replay.
- [ ] Document hosted-only tool fallback and prohibition on Deck-host installation.
- [ ] Record measured test counts and any pre-existing failures.
- [ ] Run final validation:

  ```bash
  cd backend
  venv/bin/pytest tests/agent_mail tests/agent_teams \
    tests/test_sqlite_compat_migrations.py -q -p no:warnings
  venv/bin/pytest tests -q -p no:warnings
  cd ../frontend
  npm run build
  cd ..
  git diff --check
  git status --short
  ```

- [ ] Confirm no frontend changes and no live replay artifact/state mutation.
- [ ] Open one PR targeting `feature/autonomous-github-dispatch` and stop.

**Commit:** `docs: add diagnostic recovery rollout guide`

## PR3 Exit Gate

PR3 is complete only when:

- diagnostic red/green checks cannot affect product review/merge state;
- exact tree restoration is required before leaving diagnosis;
- owner and Leader can complete the recovery protocol without a coordinator;
- crashes/restarts resume exactly one durable next action;
- autonomy-off freezes transitions;
- finite caps stop loops honestly;
- logs are useful and secret-free;
- continuation remains disabled on live scopes;
- the PR targets only the integration branch.
