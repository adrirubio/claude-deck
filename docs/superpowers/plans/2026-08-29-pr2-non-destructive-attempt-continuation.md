# PR2 — Non-Destructive Attempt Continuation Implementation Plan

> **For implementation agents:** Execute after PR1 is reviewed and merged into
> `feature/autonomous-github-dispatch`. Use tests first and stop on code/plan drift.

**Goal:** Let the authenticated current owner propose, receive, acknowledge, execute, and
submit a bounded implementation scope revision without resetting the preserved PR,
workspace, branch, nonce, approval evidence, or retry history.

**Architecture:** PR2 activates the inert scope-revision persistence created by PR1. A
proposal snapshots the server-fetched PR head/tree and exact workspace acquisition. The
designated Leader decides the normalized request. Durable mail delivers the approved
revision, and only owner acknowledgement activates it. Product verification starts only
after authenticated `continuation_completed` proves the changed Git tree is within the
approved exact paths. A dedicated continuation monitor owns PR-bearing `dispatched` items.

**Spec:** `docs/superpowers/specs/2026-08-29-autonomous-attempt-recovery-design.md`,
Revision 7, especially §§4.1–4.5, 5.2–5.4, 6, 7.4, 8.1, 9, 11–13, and 14 PR2.

**Dependency:** Merged PR1 approval authority. Record its integration-branch merge SHA in
the PR description.

**Target:** One PR into `feature/autonomous-github-dispatch`, never `master`.

**Post-PR1 drift corrections (2026-08-29):** Merged PR1 commit `88f06be` made decision
targeting explicit, removed caller-controlled operator cancellation, and serialized
approval mutations against database-current work-item state. The Task 3, Task 4, and Task 6
requirements below supersede any older implementation inference that conflicts with those
contracts.

**Implementation-review corrections (2026-08-29):** The production GitHub tree client
returns path-keyed mappings, not entry lists; completion must consume that exact contract.
Persist the head accepted by `continuation_completed` and require it to remain current until
green promotion, otherwise return the revision to `active` without charging a failed-head
budget. Lease-bearing continuation context requires both the current slot and current member.
An accepted handoff supersedes every nonterminal continuation revision owned by the previous
slot, plus any linked pending approval/mail root, so stale authority cannot block the target.
Only one proposed, approved, active, or submitted revision may exist for an attempt. Leader
decisions and workspace claims re-check database-current slot/member authority in their
conditional writes. Generic mail-list and thread projections redact continuation scope
details; authenticated inbox delivery remains authoritative. Submission time is durable and
anchors the no-check grace window. Terminal PR outcomes close submitted authority, product
failure state commits before best-effort notification, and continuation idle nudges use
deterministic delivery keys so a crash cannot duplicate mail.

## PR Boundary

PR2 implements **implementation-phase continuation only**.

- `attempt_phase = implementation` is accepted.
- Diagnostic proposals return `409 diagnostic_continuation_not_available` until PR3.
- `monitor_recovery` and automatic proposal nudges remain absent until PR3.
- Agent Bridge UI remains unchanged until PR4.
- Every existing and new scope keeps `continuation_enabled = false` during staged rollout.

## Global Safety Constraints

- Use a new isolated worktree based on the PR1 merge tip.
- Do not touch the live Deck checkout, live DB, Tizonia checkout, work item 23, or PR #875.
- Do not enable autonomy or continuation on any live scope.
- Never call `reset_for_retry` from a continuation path.
- Never rotate the dispatch nonce or lease token for continuation.
- Never parse approval or scope authority from mail prose.
- Never use caller-supplied owner, Leader, baseline SHA/tree, workspace id, or current PR
  head as authority.
- `allowed_paths` are exact normalized Git paths; no globs, roots, absolute paths, or `..`.
- Completion/report routes validate session, owner, nonce, revision, and lease before any
  mutation.
- Commit each task independently; stop after opening the PR.

## File Map

| File | Action | Responsibility |
|---|---|---|
| `backend/app/models/database.py` | Modify | Scope policy/work-item continuation fields |
| `backend/app/database.py` | Modify | Additive compatibility columns/defaults |
| `backend/app/models/schemas.py` | Modify | Policy, revision, request, ack, report, projection schemas |
| `backend/app/services/github_approval_service.py` | Modify | Revision proposals/decisions/delivery/cancel |
| `backend/app/services/github_dispatch_service.py` | Modify | Ack, context, handoff, monitor, preservation |
| `backend/app/services/github_verification_service.py` | Modify | Submission path gate and revision retry budget |
| `backend/app/services/github_watcher_service.py` | Modify | Metadata-only updates for preserved attempts |
| `backend/app/services/github_client.py` | Modify | Commit/tree retrieval and strict response validation |
| `backend/app/api/v1/agent_mail.py` | Modify | Continuation Leader decision route |
| `backend/app/api/v1/agent_teams.py` | Modify | Proposal/list/cancel/ack/context/report routes and projections |
| `backend/app/services/github_dispatch_scheduler.py` | Modify | `monitor_continuation` hook |
| `backend/mcp_shim/agent_mail_server.py` | Modify | Request/decision/ack/list/context/report tools |
| `backend/tests/agent_teams/test_github_scope_models.py` | Modify | Policy validation/defaults |
| `backend/tests/test_sqlite_compat_migrations.py` | Modify | Scope/work-item compatibility migration |
| `backend/tests/agent_teams/test_github_client.py` | Modify | Commit/tree API behavior |
| `backend/tests/agent_mail/test_api.py` | Modify | Continuation decision authority |
| `backend/tests/agent_mail/test_mcp_shim.py` | Modify | Continuation MCP contracts |
| `backend/tests/agent_teams/test_github_workspace_api.py` | Modify | Proposal/ack/list/cancel/context/report auth |
| `backend/tests/agent_teams/test_github_dispatch_service.py` | Modify | Activation/handoff/monitor/preservation |
| `backend/tests/agent_teams/test_github_watcher_service.py` | Modify | Reset guards |
| `backend/tests/agent_teams/test_github_verification_service.py` | Modify | Submission/path/retry gating |
| `backend/tests/agent_teams/test_github_dispatch_scheduler.py` | Modify | Monitor invocation/order |
| `docs/deploy/attempt-recovery-pr2-rollout.md` | Create | Disabled implementation-continuation rollout |

## Task Index

| Task | Deliverable |
|---|---|
| 1 | Scope policy and work-item fields |
| 2 | GitHub commit/tree authority |
| 3 | Proposal validation and revision allocation |
| 4 | Continuation request and Leader decision APIs |
| 5 | Durable delivery and owner acknowledgement |
| 6 | Dynamic context and MCP surface |
| 7 | Watcher and deferred-retry preservation |
| 8 | Authenticated completion and tree path gate |
| 9 | Revision-aware product verification |
| 10 | Handoff and active-continuation monitor |
| 11 | Projections, regression sweep, and rollout |

---

## Task 1 — Add Scope Policy and Work-Item Continuation Fields

**Files:** `backend/app/models/database.py`, `backend/app/database.py`,
`backend/app/models/schemas.py`, `backend/app/api/v1/agent_teams.py`,
`backend/tests/agent_teams/test_github_scope_models.py`,
`backend/tests/agent_teams/test_github_workspace_api.py`,
`backend/tests/test_sqlite_compat_migrations.py`

- [ ] Add the six `TeamGithubScope` policy columns with spec defaults and Pydantic bounds.
- [ ] Add the six `GithubWorkItem` continuation fields with non-NULL defaults where
  specified.
- [ ] Add response fields plus a dedicated continuation-policy update schema. Generic scope
  create/update schemas cannot write these fields. Existing/new scopes use safe defaults.
- [ ] Add operator-only `PATCH /github-scopes/{id}/continuation-policy`; require all six
  finite policy values and return the updated scope.
- [ ] Extend `_run_sqlite_compat_migrations` additively; run twice against a pre-PR2 fixture.
- [ ] Preserve every existing work-item attempt field and normalized approval row.
- [ ] Reject invalid caps (`max_failed_heads_per_revision` above total, non-positive path or
  command limits) at schema and service boundaries.
- [ ] Add application-level accepted phase/status sets without inventing new
  `dispatch_status` values.

**Mutation checks:** default continuation true; generic scope patch enables continuation;
agent session opens policy route; nullable revision/phase; migration overwrites existing
values; missing upper-bound validation.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_scope_models.py \
  tests/agent_teams/test_github_workspace_api.py \
  tests/test_sqlite_compat_migrations.py -q -p no:warnings
```

**Commit:** `feat: add attempt continuation policy fields`

---

## Task 2 — Add Authoritative GitHub Commit and Tree Reads

**Files:** `backend/app/services/github_client.py`,
`backend/tests/agent_teams/test_github_client.py`

- [ ] Add explicit-token-aware methods to fetch:
  - a commit by SHA and its root tree SHA;
  - a recursive Git tree by tree SHA.
- [ ] Validate response objects, SHA shape, tree entries, path strings, modes, object types,
  blob/tree SHAs, and `truncated`.
- [ ] Reject non-object entries, duplicate paths with conflicting identities, missing tree
  metadata, cross-repo redirects, unsafe pagination/URLs, and malformed JSON.
- [ ] Return a typed/internal canonical tree map suitable for exact path comparison.
- [ ] Never accept a caller-provided GitHub token from continuation request bodies; use the
  scope's existing auth resolution.
- [ ] Test mode-only changes and files whose blobs have identical content under different
  paths.

**Mutation checks:** ignore `truncated`; drop mode from identity; accept duplicate path;
forward token to unsafe URL; trust pull body tree SHA.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_client.py -q -p no:warnings
```

**Commit:** `feat: add strict github tree snapshots`

---

## Task 3 — Validate Proposals and Allocate Revisions

**Files:** `backend/app/services/github_approval_service.py`,
`backend/app/models/schemas.py`,
`backend/tests/agent_teams/test_github_workspace_api.py`

- [ ] Define proposal input with phase, execution target, summary, paths, actions, commands,
  prohibitions, failed-head budget, tool fallbacks, nonce, and lease token.
- [ ] Require scope continuation enabled, item escalated for an allow-listed reason, open PR,
  owner/member/slot, nonce, and currently leased workspace.
- [ ] In PR2 accept only `implementation`; reject diagnostic explicitly.
- [ ] Validate implementation execution target against the closed target namespace and
  persist it for PR3/UI compatibility.
- [ ] Fetch the current PR head, commit, and baseline tree server-side.
- [ ] Validate exact normalized paths and closed action namespace; canonicalize duplicates
  before fingerprinting.
- [ ] Enforce per-revision and attempt-wide revision/failed-head caps by querying persisted
  rows, not body claims.
- [ ] Hash the lease token with a domain-separated SHA-256 helper and compare with
  `hmac.compare_digest`; never store or return plaintext.
- [ ] Allocate `COALESCE(MAX(revision), 0) + 1` inside the transaction and rely on the unique
  constraint under races.
- [ ] Before inserting revision or approval authority, serialize on a conditional
  `GithubWorkItem` update that requires database-current `dispatch_status == "escalated"`,
  nonce, approval round, owner slot, PR, and originating escalation. Do not reuse PR1's
  initial-plan `dispatch_status != "escalated"` predicate. A concurrent transition out of
  escalation fails closed without creating either row.
- [ ] Resolve the circular links without partial commits: insert/flush the revision, insert/
  flush the approval pointing to it, set `revision.approval_request_id`, then commit once.
- [ ] On conflict, roll back and return the identical winner or
  `409 approval_request_already_pending`.
- [ ] Persist originating escalation, baseline head/tree, expected workspace/acquisition,
  canonical request, and one pending normalized approval.

**Mutation checks:** baseline from body; wildcard path accepted; revision cap checked after
insert; owner slot without member; hash omitted; race allocates two revisions; proposal
guard accepts a database-current non-escalated item.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_workspace_api.py -q -p no:warnings
```

**Commit:** `feat: validate bounded continuation proposals`

---

## Task 4 — Add Continuation Request and Leader Decision APIs

**Files:** `backend/app/api/v1/agent_teams.py`,
`backend/app/api/v1/agent_mail.py`, `backend/app/models/schemas.py`,
`backend/app/services/github_approval_service.py`,
`backend/tests/agent_mail/test_api.py`,
`backend/tests/agent_teams/test_github_workspace_api.py`

- [ ] Add owner-authenticated `POST /github-work-items/{id}/continuation-requests`.
- [ ] Commit revision/approval authority before sending the request mail; recover/link one
  mail root by stable delivery key.
- [ ] Add Leader-authenticated `POST /agent-mail/continuation-decisions` taking approval id,
  decision, and reason—not a thread id.
- [ ] Require an explicit `approval_request_id` and resolve only
  `request_kind == "continuation"`. Parameterize PR1's resolver with an expected kind or add
  a dedicated continuation resolver; never route continuation decisions through the
  initial-plan-only resolver and never infer whichever request is pending.
- [ ] Validate distinct current Leader, request owner, nonce, round, revision, pending status,
  and expiry.
- [ ] Serialize the decision mutation on a conditional `GithubWorkItem` update requiring
  database-current `dispatch_status == "escalated"`, nonce, approval round, owner slot, PR,
  and originating escalation. A concurrent transition out of escalation leaves the
  approval and revision pending and returns a stable conflict.
- [ ] Commit decision authority before decision mail; link decision evidence idempotently.
- [ ] On approval, leave the item escalated and revision approved.
- [ ] On rejection, mark request/revision terminal and leave the item escalated.
- [ ] Add cancellation with two authenticated pathways and no caller-controlled privilege
  flag: an authenticated requester session calls
  `github_approval_service.cancel(..., requester_member_id=session.member_id)`; an operator
  route protected by `require_operator` calls the neutral private authorized transition.
  Neither pathway may manufacture a `MailAgentSession` or member id.
- [ ] Add audited revision-list route; never return lease hash or secrets.

**Mutation checks:** choose mail thread; omit or change `approval_request_id`; resolve an
`initial_plan` request as continuation; approval changes item status; decision guard accepts
a database-current non-escalated item; operator approves; unprotected operator cancellation;
cancel updates one row; decision replay reverses terminal decision.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_mail/test_api.py \
  tests/agent_teams/test_github_workspace_api.py -q -p no:warnings
```

**Commit:** `feat: add continuation approval endpoints`

---

## Task 5 — Deliver and Acknowledge Approved Scope

**Files:** `backend/app/services/github_approval_service.py`,
`backend/app/services/github_dispatch_service.py`,
`backend/app/api/v1/agent_teams.py`,
`backend/tests/agent_teams/test_github_dispatch_service.py`,
`backend/tests/agent_teams/test_github_workspace_api.py`

- [ ] After decision evidence is linked, send/recover the canonical approved revision to the
  current owner with `github-scope:{revision_id}:delivery`.
- [ ] Store delivery message/timestamp in a separate commit; retry safely after every crash
  boundary.
- [ ] Add owner-authenticated ack route requiring revision, nonce, and plaintext lease token.
- [ ] Re-fetch item, owner, PR head, workspace id, and lease acquisition before activation.
- [ ] Require PR head still equals `baseline_head_sha` and workspace hash still matches.
- [ ] Activate in one transaction: revision active, work-item active revision/phase,
  `dispatch_status = dispatched`, fresh continuation clock, cleared pending/escalation state,
  and originating escalation retained on the revision.
- [ ] Conditionally stamp owner contact under item/owner/workspace/token predicates.
- [ ] Preserve PR, refs, nonce, owner, lease/token, retry counters, approval evidence, and
  verification SHAs byte-for-byte.
- [ ] Make duplicate same-owner/same-revision ack idempotent; reject all stale actors and
  acquisitions.

**Mutation checks:** activate on approval before delivery; compare workspace id only; rotate
token; reset retry count; use old dispatch clock; accept changed PR head.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_dispatch_service.py \
  tests/agent_teams/test_github_workspace_api.py -q -p no:warnings
```

**Commit:** `feat: activate delivered continuation scopes`

---

## Task 6 — Add Dynamic Context and MCP Surface

**Files:** `backend/app/api/v1/agent_teams.py`,
`backend/app/models/schemas.py`, `backend/mcp_shim/agent_mail_server.py`,
`backend/tests/agent_mail/test_mcp_shim.py`,
`backend/tests/agent_teams/test_github_workspace_api.py`

- [ ] Extend owner continuation context with active revision, pending approval, phase,
  exact scope, block code, and budgets.
- [ ] Keep lease token visible only through the existing authenticated owner continuation
  context; list/audit endpoints omit it.
- [ ] Require the claim caller to match both the database-current owner slot and member;
  a stale session from a previous member in the same slot receives no lease context.
- [ ] Add MCP tools:
  - `deck_request_continuation`;
  - `deck_decide_continuation(approval_request_id: int, work_item_id: int,
    dispatch_nonce: str, decision: str, reason: str)` with every argument required and no
    pending-request fallback;
  - `deck_ack_continuation`;
  - `deck_list_scope_revisions`.
- [ ] Extend `deck_list_work_items` with safe continuation fields.
- [ ] Extend `deck_report_dispatch_status` signature/docstring for
  `continuation_completed`, revision, nonce, current head, summary, evidence, and lease.
- [ ] Preserve backend conflict code/message and redact token/header values.
- [ ] Test restart: a new authenticated owner session reads the exact same active revision.

**Mutation checks:** return lease in list route; accept body member id; omit revision from
report; genericize 409 detail; depend on terminal scrollback.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_mail/test_mcp_shim.py \
  tests/agent_teams/test_github_workspace_api.py -q -p no:warnings
```

**Commit:** `feat: expose attempt continuation agent tools`

---

## Task 7 — Guard Watcher and Deferred Retry Preservation

**Files:** `backend/app/services/github_watcher_service.py`,
`backend/app/services/github_dispatch_service.py`,
`backend/tests/agent_teams/test_github_watcher_service.py`,
`backend/tests/agent_teams/test_github_dispatch_service.py`

- [ ] Restrict watcher auto-retry to PR-less, revision-zero items with no pending approval
  and no existing deferred marker.
- [ ] For guarded items, update only title/GitHub timestamp/updated timestamp; keep
  `issue_type` immutable outside pending.
- [ ] Apply the same guards in `promote_deferred_retries`.
- [ ] Prove issue comments, title edits, label edits, and newer `updated_at` cannot queue or
  complete a retry for a preserved PR/continuation.
- [ ] Prove legitimate legacy PR-less recovery still works.
- [ ] Add the stale-marker case: preserved PR plus released workspace still cannot reset.

**Mutation checks:** guard only active revision but not PR; guard watcher but not promoter;
change issue type; clear approval rows; call reset after metadata update.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_watcher_service.py \
  tests/agent_teams/test_github_dispatch_service.py -q -p no:warnings
```

**Commit:** `fix: preserve continued attempts on issue updates`

---

## Task 8 — Authenticate Completion and Enforce Tree Paths

**Files:** `backend/app/models/schemas.py`,
`backend/app/api/v1/agent_teams.py`,
`backend/app/services/github_verification_service.py`,
`backend/tests/agent_mail/test_dispatch_status_tool.py`,
`backend/tests/agent_teams/test_github_workspace_api.py`,
`backend/tests/agent_teams/test_github_verification_service.py`

- [ ] Add `continuation_completed` to `_DISPATCH_STATUS_RULES` as owner-only and lease-token
  required.
- [ ] Add optional report transport fields, then require revision, nonce, summary, current
  head, and lease in this branch before mutation.
- [ ] Fetch current PR head and require it equals the report.
- [ ] Fetch baseline/current recursive trees; refuse truncated/incomplete responses.
- [ ] Consume the path-keyed mapping returned by the production recursive-tree client;
  list-shaped test doubles are not an acceptable substitute for this interface.
- [ ] Compute changed paths including mode/type changes and require every path is exactly
  allowed.
- [ ] Require `push_pr_head` and `request_verification` actions.
- [ ] Revalidate owner, nonce, revision active status, workspace id/token hash, and PR.
- [ ] Set revision `submitted` and item `verifying`; do not mark completed yet.
- [ ] Persist the submitted head SHA. Re-check it before reading CI and immediately before
  green promotion; a changed head returns the revision to `active` for a new authenticated
  completion report without incrementing either failure counter.
- [ ] Return stable conflict codes for stale head, inconclusive diff, out-of-scope paths, and
  missing actions.

**Mutation checks:** verify caller path list; ignore mode changes; accept truncated tree;
mark revision completed immediately; skip lease re-read; accept `dispatched` verifier entry.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_mail/test_dispatch_status_tool.py \
  tests/agent_teams/test_github_workspace_api.py \
  tests/agent_teams/test_github_verification_service.py -q -p no:warnings
```

**Commit:** `feat: gate continuation verification by github tree`

---

## Task 9 — Make Product Verification Revision-Aware

**Files:** `backend/app/services/github_verification_service.py`,
`backend/tests/agent_teams/test_github_verification_service.py`

- [ ] Partition `process_scope`:
  - legacy revision-zero dispatched/verifying keeps current behavior;
  - active implementation dispatched is skipped;
  - active implementation verifying is processed.
- [ ] On a distinct failed implementation head, increment global product audit count and
  revision failed-head count once.
- [ ] While a revision is active/submitted, use its finite budget for escalation eligibility;
  do not immediately re-escalate because the global count was already exhausted.
- [ ] Within budget, set revision active, item dispatched, and refresh continuation clock.
- [ ] On revision/attempt cap exhaustion, mark revision exhausted and escalate
  `continuation_budget_exhausted` without resetting attempt state.
- [ ] On green, mark revision completed and execute the unchanged ready-for-review/human
  merge behavior.
- [ ] Prove same-head polls change no counter or notification.

**Mutation checks:** verify implementation while dispatched; use global threshold; increment
same head; complete revision before green; call reset on exhaustion.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_verification_service.py -q -p no:warnings
```

**Commit:** `feat: account product failures by continuation revision`

---

## Task 10 — Integrate Handoff and Active-Continuation Monitoring

**Files:** `backend/app/services/github_dispatch_service.py`,
`backend/app/services/github_dispatch_scheduler.py`,
`backend/tests/agent_teams/test_github_dispatch_service.py`,
`backend/tests/agent_teams/test_github_dispatch_scheduler.py`

- [ ] On accepted handoff, supersede every previous-owner nonterminal revision, restore an
  active revision's originating escalation, supersede linked pending approval/mail roots,
  and require the target to propose a fresh revision.
- [ ] Keep existing atomic owner/PID/lease-token handoff guarantees unchanged.
- [ ] Add `monitor_continuation` query:
  `dispatched AND pr_number IS NOT NULL AND active_scope_revision > 0`.
- [ ] Anchor grace at activation, then authenticated owner contact/progress—not initial
  dispatch/nudge timestamps.
- [ ] Nudge once, then re-escalate the same attempt on idle without reset.
- [ ] Emit redacted structured debug telemetry for item, revision, phase/status, grace
  anchor/delta, action, and block code.
- [ ] Make `monitor_dispatched` explicitly revision zero.
- [ ] Invoke monitor order: initial dispatch monitor, continuation monitor, verification,
  then held-lease reminder. PR3 later inserts recovery monitor after verification.
- [ ] Use fresh queries/commits between stages.

**Mutation checks:** target uses old revision; rotate lease token; reuse dispatched_at;
monitor PR-bearing item twice; omit scheduler call; log command/token payload.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_dispatch_service.py \
  tests/agent_teams/test_github_dispatch_scheduler.py -q -p no:warnings
```

**Commit:** `feat: monitor active attempt continuations`

---

## Task 11 — Complete Projections, Regressions, and Disabled Rollout

**Files:** `backend/app/api/v1/agent_teams.py`,
`backend/app/models/schemas.py`, tests, `docs/deploy/attempt-recovery-pr2-rollout.md`

- [ ] Extend `_work_item_response` with explicitly preloaded active revision and pending
  approval values.
- [ ] Extract one backend Retry eligibility predicate and project `retry_allowed` plus
  `retry_block_code`; make the retry route call the same predicate.
- [ ] Preserve current deferred retry behavior: an otherwise eligible PR-less escalated item
  with a held workspace remains allowed and records `retry_requested_at`. Add only the
  active-revision and pending-approval blocks needed to prevent authority loss; do not add
  a new escalation-reason allow-list.
- [ ] Bulk-load normalized rows for list endpoints; assert bounded query count and no async
  lazy loading.
- [ ] Reload normalized rows before mutation responses.
- [ ] Test API/MCP omission of lease hashes/tokens and canonical commands where the caller is
  not the owner.
- [ ] Run every named mutant from Tasks 1–10.
- [ ] Document that continuation remains disabled and diagnostic requests are unavailable.
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

- [ ] Confirm no diagnostic observer/counters, recovery nudge loop, continuation UI, or live
  scope enablement is present.
- [ ] Open one PR targeting `feature/autonomous-github-dispatch` and stop.

**Commit:** `docs: add implementation continuation rollout guide`

## PR2 Exit Gate

PR2 is complete only when:

- implementation continuation is fully authenticated and restart-safe;
- approval alone never resumes work;
- owner ack preserves every attempt identity field;
- product verification cannot run before tree/path submission;
- watcher updates cannot queue a destructive retry;
- handoff invalidates owner-bound scope without rotating the lease;
- PR-bearing dispatched continuations are monitored;
- all scopes remain continuation-disabled;
- the PR targets only the integration branch.
