# Autonomous Attempt Recovery — Design

**Date:** 2026-08-29
**Revision:** 7 — implementation-plan semantic corrections applied
**Status:** Approved for implementation planning
**Issue:** [#325 — Resume active escalated attempts with leader-authorized scope extensions](https://github.com/adrirubio/claude-deck/issues/325)
**Target branch:** `feature/autonomous-github-dispatch`
**Evidence:** Tizonia work item 23, issue #821, draft PR #875

---

## 1. Executive summary

Deck can stop unsafe work, but it cannot autonomously resume a stopped attempt when the
next action needs a small, legitimate scope extension. The Tizonia soak demonstrated the
failure mode:

1. CI failures exhausted the verification budget.
2. Deck escalated the item while its owner, PR, branch, and workspace were still valid.
3. Retry was correctly refused because it would discard attempt identity and PR state.
4. The Leader could approve each proposed correction, but Deck had no non-destructive
   continuation transition and no way to update the active owner's authorization.
5. A coordinator manually relayed approvals, committed on the owner's branch, and watched
   CI. No human judgment was required, yet autonomy stalled.

This design adds an **attempt continuation protocol**. A current owner proposes one bounded
scope extension, the designated Leader decides it, Deck delivers the approved revision to
the same authenticated owner, and the owner acknowledges it before Deck resumes the
preserved attempt. Diagnostic work is tracked separately from product verification so an
expected-red diagnostic run cannot consume the product retry budget.

The design does **not** make retry more permissive. Retry remains the operation that starts
a new attempt. Continuation is a new operation that preserves the current one.

---

## 2. Incident and measured gaps

### 2.1 The Tizonia sequence

The preserved soak state is:

- Deck work item: `23`
- Tizonia issue: `#821`
- Tizonia PR: `#875`, draft
- Escalation: `retry_count_exhausted`
- Owner slot: Specialist
- Workspace: still leased to the item
- PR branch: still present and clean
- Merge policy: human

The remote pipeline repeatedly passed dependency installation, Meson configuration, and
compilation, then failed during the focused playback smoke test. The owner and Leader were
both available. The work needed progressively narrower diagnostics and fixes, but each new
action required a manually relayed authorization.

Autonomy for preset `tizonia-v1` was disabled through the Deck API on 2026-08-29. Item 23,
its lease, and PR #875 are intentionally preserved as this design's end-to-end replay.

### 2.2 Existing safety work is necessary but insufficient

Phase G1 (`2026-07-27-escalation-inflight-safety-design.md`) correctly prevents retry from
orphaning a PR. It also deliberately keeps `retry_count_exhausted` outside the set of
escalations that a late PR can silently resolve. That is the correct safety decision.

The missing operation is not a broader retry. It is an explicit, approved continuation of
the same attempt.

### 2.3 Current code seams

The following current behavior is load-bearing:

- `github_dispatch_service.reset_for_retry` clears the attempt markers, PR number,
  approval evidence, verification SHA, retry count, and approval-round count once the
  workspace is released.
- `POST /github-work-items/{id}/retry` refuses an item that already has a PR.
- `POST /presets/{preset_id}/work-items/{id}/resume-attempt` only handles
  `prepared_owner_unavailable`, before ordinary in-flight recovery. It is operator-only and
  moves a prepared item back to `pending`.
- `POST /agent-mail/decisions` discovers the current approval request by scanning
  `mail_messages` payloads. More than one matching row returns
  `409 ambiguous_current_approval_request`.
- The dispatch brief is durable mail, but its authorization text is immutable. Later Leader
  messages do not update a server-side scope object.
- Verification counts failed PR heads in `GithubWorkItem.retry_count`. There is no
  distinction between an expected-red diagnostic head and a failed product-fix head.
- Work-item reports are correctly bound to an authenticated Agent Mail session, current
  owner slot, dispatch nonce, and—where destructive—workspace lease token.
- `github_watcher_service._upsert_item` currently calls `reset_for_retry` for any newer
  GitHub update on an `escalated` or `failed` item. A PR-bearing escalated item can therefore
  acquire `retry_requested_at` while its lease is held and lose its PR/attempt markers after
  release.
- `github_verification_service.process_scope` currently verifies every PR-bearing
  `dispatched` item. A continued attempt would therefore be polled before its owner reports
  completion unless the selector is changed.

The continuation design must reuse the last property and must not weaken it.

---

## 3. Goals and non-goals

### 3.1 Goals

1. Resume an eligible escalated attempt without resetting it.
2. Preserve the PR, branch, workspace lease, owner, dispatch nonce, retry history, and
   verification history.
3. Let the current owner request a bounded extension while remaining unable to approve its
   own request.
4. Let the designated Leader approve or reject the extension without a human operator.
5. Deliver a versioned authorization to the current owner and require an authenticated
   acknowledgement before work resumes.
6. Separate diagnostic failures from product verification failures.
7. Recover automatically after process or Deck restarts.
8. Expose the state through REST, Agent Mail/MCP, and Agent Bridge.
9. Preserve human merge policy and human stop signals.

### 3.2 Non-goals

- Automatically overriding `dispatch_label_removed`, `abandoned_by_operator`, or any future
  human stop signal.
- Letting a Leader approve its own proposal.
- Turning Agent Mail prose into authorization.
- Enforcing shell-level file access before a command runs. Deck verifies the resulting Git
  and GitHub changes; it does not sandbox the agent process in this phase.
- Auto-merging a PR that uses human merge policy.
- Replacing the existing workspace lease or handoff protocols.
- Installing debugging tools on the Deck host. Diagnostic tooling in the Tizonia case is
  required on the hosted GitHub Actions runner.

---

## 4. Design principles

### 4.1 Retry and continuation are different operations

| Operation | Identity | PR/workspace | Counters | Intended use |
|---|---|---|---|---|
| Retry | New attempt | Must be absent/released | Reset | Re-dispatch from the issue |
| Continuation | Same attempt | Preserved | Preserved; bounded extension budget added | Recover an in-flight attempt |

An operator may request Retry while a PR-less escalated item still holds its workspace, but
Deck only starts the new attempt after release; until then the existing deferred-retry marker
preserves the old attempt. Continuation is the only path that performs more work while that
acquisition remains held.

No implementation helper may serve both operations unless its caller must explicitly
select one semantic and tests prove the destructive fields are preserved for continuation.

#### 4.1.1 GitHub issue updates cannot imply retry

The watcher may request an automatic retry for a recoverable legacy item only when all of
these are true:

- `pr_number IS NULL`;
- `active_scope_revision == 0`;
- no pending normalized approval request exists;
- `retry_requested_at IS NULL` before this update.

If any guard fails, `_upsert_item` updates only non-attempt GitHub metadata
(`github_updated_at`, `issue_title`, and `updated_at`). `issue_type` remains immutable once
an attempt is no longer `pending`; changing a design/code label cannot rewrite the type of
an active attempt. The watcher must not call `reset_for_retry`, set `retry_requested_at`, or
alter continuation/approval rows.

`promote_deferred_retries` applies the same guards before honoring an existing marker. The
migration clears `retry_requested_at` on PR-bearing rows because the public retry route
already rejects a preserved PR; on the pre-feature schema such a marker can only have been
created by this unsafe watcher path.

### 4.2 Attempt phase is orthogonal to dispatch status

`dispatch_status` answers where the work item is in the dispatch pipeline. It does not
answer whether the current work is product implementation or temporary diagnosis.

This design adds `attempt_phase` with two values:

- `implementation`
- `diagnostic`

It does **not** add `diagnosing` to `dispatch_status`.

### 4.3 An approval is a row, not a mail search

Mail remains the transport and human-readable thread. A normalized approval-request row is
the authority. The decision route resolves that row by primary key or by the database-
enforced unique pending row rather than rediscovering authority from JSON payloads.
The implementation may resolve an explicitly supplied request id or the one database-
enforced pending row for the item; it must not add an unsynchronized second "current"
pointer.

### 4.4 Approval does not resume work; acknowledgement does

The item remains safely escalated after the Leader approves. Deck first delivers the
approved scope revision. Only the authenticated current owner can acknowledge that exact
revision, and the acknowledgement transaction activates the revision and resumes the item.

This ordering makes a mail-delivery failure safe.

### 4.5 Preserve history; grant a new bounded budget

Continuation never resets `retry_count`. An approved scope revision carries its own head
budget. Product retry history remains an audit fact while the new revision gets a small,
explicit opportunity to prove itself.

---

## 5. Data model

### 5.1 `github_approval_requests`

A new table represents the one approval request Deck currently treats as an inferred set of
mail rows.

| Column | Type | Meaning |
|---|---|---|
| `id` | integer PK | Stable request identity |
| `work_item_id` | FK, indexed | Owning work item |
| `request_kind` | string | `initial_plan` or `continuation` |
| `dispatch_nonce` | string | Attempt identity at creation |
| `approval_round` | integer | Approval round at creation |
| `owner_member_id` | FK | Authenticated requester |
| `leader_member_id` | FK | Designated approver |
| `request_message_id` | nullable FK | Agent Mail context-request root; linked after durable send |
| `decision_message_id` | nullable FK | Structured decision answer |
| `scope_revision_id` | nullable FK | Proposed continuation scope |
| `request_fingerprint` | string | SHA-256 of the canonical request payload |
| `status` | string | `pending`, `approved`, `rejected`, `superseded`, `expired` |
| `reason` | nullable text | Structured decision reason |
| `created_at` | datetime | Creation time |
| `decided_at` | nullable datetime | Decision time |
| `superseded_at` | nullable datetime | Supersession time |

A partial unique index enforces **one `pending` approval request per work item**. This is a
database invariant, not a preflight `SELECT`.

Creating a request is idempotent when all of these match the existing pending row:

- work item
- request kind
- dispatch nonce
- approval round
- owner member
- request fingerprint

The route returns the existing row in that case. A different request while one is pending
returns `409 approval_request_already_pending`; it does not create a second row.

When owner, nonce, or round changes, Deck supersedes the old pending row in the same
transaction before creating the new one.

Concurrent creators may both pass a read preflight. The partial unique index is the final
authority: the losing transaction catches the uniqueness failure, rolls back, re-reads the
winner, and returns it only when the fingerprint and identity tuple match. Otherwise it
returns `409 approval_request_already_pending`.

### 5.1.1 Idempotent Agent Mail transport

Database rows and Agent Mail delivery cannot be treated as one atomic operation because
mail helpers commit independently. Add nullable `delivery_key` to `mail_messages` with a
partial unique index over non-NULL values. Server-authored approval traffic uses stable
keys:

- `github-approval:{approval_request_id}:request`
- `github-approval:{approval_request_id}:decision`
- `github-scope:{scope_revision_id}:delivery`
- `github-scope:{scope_revision_id}:ack-nudge:{sequence}`

The Agent Mail send helper accepts an optional server-only `delivery_key`. A conflicting
insert returns the existing message after verifying kind, sender, recipient, and canonical
payload bytes. A mismatch is a server integrity error; it never reuses the row.

This makes every post-commit mail retry idempotent across task retries, concurrent
schedulers, and process crashes. A route must not claim idempotent delivery merely because
it stored a message id after sending.

### 5.2 `github_attempt_scope_revisions`

Scope revisions are immutable after proposal except for lifecycle timestamps and counters.

| Column | Type | Meaning |
|---|---|---|
| `id` | integer PK | Stable revision identity |
| `work_item_id` | FK, indexed | Owning work item |
| `dispatch_nonce` | string | Attempt identity |
| `revision` | integer | Monotonic within the attempt |
| `owner_slot_id` | FK | Slot authorized by the revision |
| `owner_member_id` | FK | Member authorized by the revision |
| `phase` | string | `implementation` or `diagnostic` |
| `execution_target` | string | `workspace`, `hosted_ci`, or `workspace_and_hosted_ci` |
| `summary` | text | Bounded objective |
| `allowed_paths` | JSON array | Paths the revision may add/change/delete |
| `allowed_actions` | JSON array | Named operations, not free-form authority |
| `allowed_commands` | JSON array | Exact commands or command prefixes approved |
| `prohibited_actions` | JSON array | Explicit exclusions |
| `tool_fallbacks` | JSON object | Pre-authorized missing-tool behavior |
| `baseline_head_sha` | string | Server-fetched PR head when proposed |
| `baseline_tree_sha` | string | Git tree identity of that PR head |
| `originating_escalation_reason` | string | Stop reason this revision is recovering from |
| `expected_workspace_id` | FK | Workspace acquisition present at proposal time |
| `expected_lease_token_hash` | string | Hash binding the proposal to that acquisition |
| `max_failed_heads` | integer | Revision-specific failure budget |
| `failed_head_count` | integer | Distinct failed heads consumed |
| `last_failed_head_sha` | nullable string | Duplicate-poll suppression |
| `status` | string | `proposed`, `approved`, `active`, `submitted`, `completed`, `exhausted`, `rejected`, `superseded`, `expired` |
| `approval_request_id` | nullable FK | Decision that authorizes it |
| `delivery_message_id` | nullable FK | Mail carrying the approved revision |
| `approved_at` | nullable datetime | Leader decision time |
| `delivered_at` | nullable datetime | Successful durable-mail commit time |
| `acknowledged_at` | nullable datetime | Owner activation time |
| `last_delivery_attempt_at` | nullable datetime | Delivery retry clock |
| `delivery_attempt_count` | integer | Delivery retry count |
| `last_ack_nudge_at` | nullable datetime | Owner acknowledgement nudge clock |
| `result_summary` | nullable text | Diagnostic or implementation outcome |
| `evidence` | nullable JSON | Hosted run ids and evidence URLs |
| `completed_at` | nullable datetime | End time |
| `expires_at` | nullable datetime | Approval expiry |
| `created_at` | datetime | Proposal time |

Unique constraint: `(work_item_id, dispatch_nonce, revision)`.

The next revision is allocated inside the proposal transaction as
`COALESCE(MAX(revision), 0) + 1` for the exact `(work_item_id, dispatch_nonce)` tuple. The
unique constraint is authoritative under concurrency. On conflict, the losing transaction
rolls back and re-reads the pending approval: it returns the winner only for the same
fingerprint, otherwise it returns `409 approval_request_already_pending` rather than
silently allocating another revision.

`allowed_actions` is a closed application-level namespace. Initial values:

- `edit_production`
- `edit_tests`
- `edit_ci_workflow`
- `install_hosted_ci_tool`
- `push_pr_head`
- `collect_hosted_logs`
- `revert_diagnostic_changes`
- `request_verification`

Unknown actions fail closed. The list is API-visible so providers do not infer meaning from
prose.

### 5.3 `github_work_items` additions

| Column | Type/default | Meaning |
|---|---|---|
| `active_scope_revision` | integer, `0` | Active revision number; `0` means launch scope only |
| `attempt_phase` | string, `implementation` | Orthogonal phase |
| `diagnostic_retry_count` | integer, `0` | Total distinct failed diagnostic heads |
| `diagnostic_last_verified_sha` | nullable string | Diagnostic duplicate-poll suppression |
| `continuation_nudged_at` | nullable datetime | Recovery-proposal nudge cooldown |
| `continuation_activated_at` | nullable datetime | Fresh liveness anchor for the active revision |

The active revision is resolved by `(item.id, item.dispatch_nonce,
item.active_scope_revision)`. Avoiding a circular FK keeps migration and deletion behavior
simple; the unique constraint on the revision table makes the tuple single-valued.

The existing fields remain unchanged:

- `retry_count` remains total product-verification failures.
- `last_verified_sha` remains product-verification duplicate suppression.
- `escalation_reason` remains the reason the attempt stopped.
- `dispatch_nonce` does not rotate during continuation.
- Workspace `lease_token` does not rotate merely because scope changed.

The lease-token hash is an acquisition discriminator, not a replacement capability. The
plaintext token remains only on the workspace row and in the current owner's existing
capability context. It is required on proposal, acknowledgement, and completion, compared
server-side, and never returned by continuation APIs.

### 5.4 Scope-level continuation policy

Continuation is disabled by default for existing GitHub scopes. `team_github_scopes` gains:

| Column | Default | Meaning |
|---|---:|---|
| `continuation_enabled` | `false` | Permit autonomous continuation on this scope |
| `max_continuation_revisions` | `6` | Total proposed revisions in one dispatch nonce |
| `max_continuation_failed_heads` | `8` | Total failed diagnostic/product heads across those revisions |
| `max_failed_heads_per_revision` | `2` | Upper bound a proposal may request |
| `max_scope_paths` | `32` | Maximum exact repo-relative paths per revision |
| `max_scope_commands` | `16` | Maximum command entries per revision |

The proposal route enforces all caps before creating a row. `max_failed_heads` must be at
least one and no greater than the scope limit. Paths are exact, normalized, case-sensitive
Git paths: no absolute paths, `..`, empty entries, root-wide sentinels, or globs. Repeated
paths and commands are canonicalized before fingerprinting.

When either attempt-wide cap is exhausted, Deck escalates with
`continuation_budget_exhausted`. That reason is not automatically continuable. Raising a
scope cap is an operator configuration change, not a Leader decision. This prevents an
owner/Leader pair from converting individually bounded approvals into an unbounded loop.

The existing generic GitHub-scope create/update routes do not gain these write fields.
New scopes receive the defaults above. A dedicated
`PATCH /github-scopes/{id}/continuation-policy` route updates all six fields and requires
`require_operator`; there is no session-token or external-actor fallback.

### 5.5 Migration and historical ambiguity

The migration must not guess among duplicate current requests.

It first adds `mail_messages.delivery_key` and its partial unique index. Existing messages
receive NULL, so no historical message is retroactively treated as idempotent transport.

Deck uses `Base.metadata.create_all` for new tables and
`backend/app/database.py::_run_sqlite_compat_migrations` for an existing SQLite database.
The compatibility migration must be idempotent and perform these explicit steps:

1. Add nullable `mail_messages.delivery_key` and create
   `ix_mail_messages_delivery_key` as a unique partial index where the key is non-NULL.
2. Add the six continuation-policy columns from §5.4 to `team_github_scopes`, backfilling
   `continuation_enabled = false` and the documented finite defaults.
3. Add the six continuation columns from §5.3 to `github_work_items`, with non-NULL
   defaults for revision, phase, and diagnostic retry count.
4. Create the new approval and scope-revision tables, their foreign-key indexes, the
   `(work_item_id, dispatch_nonce, revision)` unique constraint, and the partial unique
   pending-approval index.
5. Backfill/reconcile approval rows only after all schema objects exist.
6. Clear `retry_requested_at` on PR-bearing work items without changing any other attempt
   field.

Migration tests start from a pre-feature SQLite fixture and run the helper twice. Both runs
must leave the same columns, defaults, indexes, backfilled rows, and preserved attempt data.

For each current work item:

1. Find linked pending context-request roots for the current owner, designated Leader,
   dispatch nonce, and approval round.
2. Zero matches: create no approval row.
3. One match: backfill one `pending` approval row.
4. More than one match: mark every matching mail root `superseded`, create no pending
   approval row, and set a status note requiring the owner to submit one fresh request.

This converts the live `ambiguous_current_approval_request` failure into a deterministic
fresh-request path without choosing which historical prose was intended.

Pre-upgrade items receive `active_scope_revision = 0` and
`attempt_phase = implementation`. No synthetic scope authorization is invented.
Mail readers must treat `superseded` as a terminal request status, never as pending or
answerable.

---

## 6. Continuation protocol

### 6.1 Eligible escalations

Automatic continuation is allow-listed:

- `retry_count_exhausted`
- `plan_blocked`
- `owner_idle_timeout`
- `owner_offline` when the same owner later proves live
- `leader_offline` when the designated Leader later proves live
- `leader_ack_timeout` when the round has not been explicitly rejected

Every allow-listed reason is still subject to the attempt-preservation preconditions: the
item has a PR, current owner, dispatch nonce, and currently leased workspace. PR-less or
released items remain on existing retry, handoff, or operator recovery paths. This first
phase deliberately does not invent a trustworthy baseline for unpushed local work.

Automatic continuation is refused for:

- `dispatch_label_removed`
- `abandoned_by_operator`
- `pr_closed_unmerged`
- `approval_rounds_exhausted`
- `continuation_budget_exhausted`
- unknown or NULL reasons

`prepared_owner_unavailable` remains owned by the existing operator-only
`resume-attempt` route. This design does not merge the two protocols.

### 6.2 Proposal

New MCP tool and REST route:

```text
deck_request_continuation(...)
POST /github-work-items/{work_item_id}/continuation-requests
```

Required request fields:

- `dispatch_nonce`
- `phase`
- `execution_target`
- `summary`
- `allowed_paths`
- `allowed_actions`
- `allowed_commands`
- `prohibited_actions`
- `max_failed_heads`
- `tool_fallbacks`
- `lease_token`

`tool_fallbacks` is a map from a required tool to the already-requested fallback. Example:

```json
{
  "gdb": {
    "target": "hosted_ci",
    "if_missing": "install_temporarily",
    "package": "gdb",
    "revert_required": true
  }
}
```

This closes the exact Tizonia stall: the proposal requests both use of `gdb` and permission
to install it temporarily if the runner lacks it. Missing-tool recovery is no longer an
unanticipated scope change.

The caller must be the authenticated current owner. The item must still have the supplied
nonce. The owner may propose while the item is escalated, but no work is authorized by the
proposal itself.

The server, not the caller, fetches the current PR head and stores it as
`baseline_head_sha`, then fetches that commit's Git tree and stores `baseline_tree_sha`. It
also snapshots the current workspace id and a one-way hash of its lease token. If the PR is
absent, its head/tree cannot be fetched, the lease token disagrees, or the lease changes
before the proposal transaction commits, the request fails closed. Caller-supplied baseline
or workspace identity is never authoritative.

The route:

1. validates eligibility and ownership;
2. records a `proposed` scope revision and its canonical fingerprint;
3. creates the single pending approval row;
4. commits those authoritative rows;
5. sends one idempotent context request to the designated Leader;
6. stores the resulting mail root on the approval row in a second commit;
7. nudges the Leader only after the request root is linked.

A failure before the first commit creates nothing. A failure after it leaves a visible
pending request whose stable delivery key lets the scheduler create or recover exactly one
mail root. A nudge failure likewise leaves the pending request intact.

### 6.3 Leader decision

New MCP tool and REST route:

```text
deck_decide_continuation(...)
POST /agent-mail/continuation-decisions
```

The caller supplies the approval-request id, decision, and reason. It does not choose a
mail thread.

The server requires:

- authenticated Agent Mail session;
- caller is the current designated Leader;
- request status is `pending`;
- item, nonce, round, owner, and proposed revision still match;
- requester and approver are distinct members and distinct slots;
- revision has not expired.

Rejection commits the request/revision rejection and leaves the item escalated. Its
structured decision message is then written or recovered by delivery key and linked in a
second commit. A crash cannot roll back the decision merely because its explanatory mail
was delayed.

Repeating the same decision by the same Leader is idempotent and returns the existing
decision. An opposite decision or a decision by a different member after the request is
terminal returns `409 approval_request_already_decided`.

Approval transactionally:

1. marks the approval row approved;
2. marks the revision approved;
3. stores approver and decision evidence;
4. commits;
5. writes or recovers the idempotent structured decision message;
6. links the decision message in a second commit;
7. sends or recovers the approved revision delivery to the current owner;
8. stores `delivery_message_id` and `delivered_at` in a final commit.

The item remains escalated. If any transport/link step after the authority commit fails,
the scheduler repairs it idempotently. For either decision, the scheduler first repairs a
missing decision-message link. An approved revision is not delivered to the owner until
that link exists.

### 6.4 Owner acknowledgement and activation

New MCP tool and REST route:

```text
deck_ack_continuation(...)
POST /github-work-items/{work_item_id}/scope-revisions/{revision}/ack
```

The server requires:

- authenticated current owner session;
- matching slot, member, work item, nonce, and revision;
- matching plaintext lease token when the revision captured a workspace;
- revision status `approved`;
- non-NULL delivered message id;
- revision not expired;
- item still in the escalation from which the proposal was made;
- current workspace id and lease-token hash still match the acquisition captured at
  proposal time.

Activation is one transaction:

- revision `approved → active`;
- `item.active_scope_revision = revision`;
- `item.attempt_phase = revision.phase`;
- `item.dispatch_status = dispatched`;
- `item.continuation_activated_at = now`;
- `item.pending_reason = NULL`;
- `item.status_note` names the active revision and bounded objective;
- `item.updated_at` changes;
- `item.escalation_reason` is copied into the immutable revision audit fields before being
  cleared on the item.

The acknowledgement also conditionally refreshes the workspace owner-contact timestamp
under the same item, owner, workspace, and token predicates. Old `dispatched_at`,
`last_nudge_at`, and lease-contact values are not reused as continuation grace anchors.

The transaction does **not** change:

- `pr_number`
- `dispatch_nonce`
- `dispatch_head_ref`
- `dispatch_base_ref`
- `owner_slot_id`
- workspace lease or lease token
- `retry_count`
- `last_verified_sha`
- approval history from prior rounds

### 6.5 Dynamic instructions

The delivery message must contain both prose and a canonical JSON payload. The owner is told
to call `deck_ack_continuation` before making changes.

`allowed_commands` and `allowed_actions` are authorization instructions and audit inputs;
Deck does not claim to observe every shell command. Enforcement occurs at authenticated
reports, GitHub comparisons, and merge gates.

`deck_get_work_item_context` gains:

- `attempt_phase`
- `active_scope_revision`
- active revision body
- pending approval summary
- continuation block reason

This lets a restarted owner recover the same authorization without minting a new attempt or
depending on terminal scrollback.

### 6.6 Handoff interaction

An active revision authorizes one owner member and slot. Handoff therefore:

1. marks the active revision `superseded`;
2. returns the item to `escalated` with the prior escalation reason restored from the
   revision audit;
3. completes the existing lease/PID transfer protocol;
4. requires the target owner to submit a fresh continuation proposal.

The target may read the previous revision as context but cannot acknowledge or act under it.
The previous owner's retained lease token is useless because every continuation mutation
also checks current owner identity. The target receives the existing token only through the
already-authenticated handoff/lease protocol; continuation APIs never disclose it.

---

## 7. Diagnostic phase

### 7.1 Entering diagnostic phase

A diagnostic revision must include:

- baseline PR head SHA;
- exact diagnostic paths/actions;
- remote versus local execution target;
- tool fallback policy;
- maximum distinct failed heads;
- mandatory revert action;
- evidence to collect.

`baseline_head_sha` and `baseline_tree_sha` are fetched from the PR by Deck during proposal.
The PR head must still equal the stored head when the revision is acknowledged. GitHub
lookup failures, missing commit/tree metadata, or a changed head fail closed and require a
fresh proposal.

Local build commands are rejected when the team scope or proposal says hosted-only. For the
Tizonia replay, all compilation remains on GitHub Actions.

### 7.2 Verification accounting

`github_verification_service.process_scope` must distinguish three selectors before it
calls the existing product verifier:

| Item state | Action |
|---|---|
| `active_scope_revision == 0` and status `dispatched`/`verifying` | Existing behavior |
| active implementation revision and status `dispatched` | Skip; owner has not submitted the revision |
| active implementation revision and status `verifying` | Run product verification |
| active diagnostic revision and status `dispatched` | Observe checks through a diagnostic-only path |
| active diagnostic revision in any review status | Refuse/escalate invalid state; never promote |

The diagnostic observer may record check evidence and distinct failed diagnostic heads. It
must never call `_promote_verified_item`, write a ready/review status, invoke merge logic, or
consume product counters. Green diagnostic checks remain diagnostic evidence until the
owner restores the tree and reports `diagnostic_completed`.

When `attempt_phase == diagnostic`:

- failed PR heads update `diagnostic_last_verified_sha` and
  `diagnostic_retry_count`;
- the active revision's `failed_head_count` increments once per distinct head;
- `retry_count` and `last_verified_sha` do not change;
- expected-red conclusions generate a diagnostic result message rather than ordinary
  product-failure escalation;
- exceeding `max_failed_heads` returns the item to escalated and closes the revision as
  exhausted.

The verifier must branch on the persisted phase before calling the current
`_record_failed_verification_attempt`. It must not increment a normal counter and later
subtract it.

### 7.3 Reporting diagnostic completion

New report status:

```text
diagnostic_completed
```

It is a report status, not a `dispatch_status` value.

Required fields:

- work item id
- dispatch nonce
- active scope revision
- lease token
- diagnostic result summary
- evidence URLs/run ids
- restored PR head SHA

Before accepting completion, Deck fetches the PR and requires its current head to equal the
reported restored SHA. It fetches that commit's Git tree from GitHub and requires its tree
SHA to equal the persisted `baseline_tree_sha`. A revert commit has a different commit SHA
but the same tree SHA, which is the exact no-net-diff property this gate needs.

The GitHub Compare API's two-dot/three-dot and merge-base semantics are not authoritative
for diagnostic restoration. Missing commit/tree objects, a mismatched tree SHA,
cross-repository metadata, or inconclusive GitHub data fails closed.

If the net diff is non-empty, return `409 diagnostic_tree_not_restored`; keep the revision
active and do not resume product verification.

On success:

1. mark the diagnostic revision completed;
2. set `attempt_phase = implementation`;
3. set `dispatch_status = escalated`;
4. restore the originating escalation reason;
5. store the diagnostic summary and evidence on the revision;
6. notify the owner to propose the smallest implementation continuation informed by the
   evidence.

The item does not automatically enter verification after a diagnostic. Diagnosis grants
knowledge, not permission to edit production code.

### 7.4 Completing an implementation continuation

New report status:

```text
continuation_completed
```

Deck fetches the current PR head and both baseline/current recursive Git trees from GitHub,
then computes the changed path set from tree entry paths and blob/mode identities:

- every changed path is in `allowed_paths`;
- the revision includes `push_pr_head` and `request_verification`;
- the current owner and lease still match;
- the active revision and nonce match.

If either recursive tree response is truncated or incomplete, the path set is not proven
and the report returns `409 continuation_diff_inconclusive`. Compare-API pagination alone
is not sufficient because omitted files could hide an out-of-scope change.

On success, the revision becomes `submitted` and the item enters `verifying` with its
existing PR. A failed implementation head increments both the global product audit counter
and the revision counter, but escalation eligibility uses the active revision's
`max_failed_heads`; the already-exhausted preset-level counter must not immediately
re-escalate the continuation. A same-head poll increments neither counter.

If the revision budget remains, a failed head returns the revision to `active`, the item to
`dispatched`, and refreshes the continuation liveness anchor so the owner can correct the
same bounded scope. If the revision budget is exceeded, the revision becomes `exhausted`
and the item returns to `escalated` with the originating reason and new failure evidence.
On green, the revision becomes `completed` and the normal ready-for-review/human-merge path
runs unchanged.

---

## 8. Automatic recovery orchestration

### 8.1 Recovery monitor

Add `github_dispatch_service.monitor_recovery(db, scope, slots)`. It scans escalated items
only when their preset has autonomy enabled and the scope has continuation enabled.

For each item:

1. refuse reasons outside the continuation allow-list;
2. refuse when the PR, workspace, owner, or nonce to preserve is absent;
3. check the current owner has a nudgeable authenticated session;
4. if no pending continuation request exists, send one recovery instruction to the owner;
5. if a request exists but the Leader has not read it, nudge the Leader using the existing
   mail-delivery policy;
6. if an approved revision is undelivered, retry delivery idempotently;
7. if delivered but unacknowledged, nudge the owner;
8. enforce cooldowns and expiry without creating duplicate requests.

Add a separate `github_dispatch_service.monitor_continuation(db, scope, slots)` for
`dispatched` items with an active continuation and an existing PR. Today's ordinary
dispatched monitor intentionally excludes PR-bearing items, so merely setting
`dispatch_status = dispatched` would otherwise create an unmonitored state. The
continuation monitor:

- anchors grace at `continuation_activated_at`, then at authenticated owner contact or
  accepted progress reports;
- nudges the current owner once after the configured idle interval;
- returns the same attempt to `escalated` after the nudge grace expires;
- preserves PR, workspace, nonce, revision history, and counters;
- never treats an old initial `dispatched_at` or `last_nudge_at` as the new grace clock.

Recovery proposal nudges use `continuation_nudged_at`. Delivery and acknowledgement nudges
use the revision's dedicated clocks and counters. Reusing the initial-dispatch nudge fields
is forbidden because their pre-escalation timestamps can cause immediate timeout after
activation.

Both continuation monitors emit structured debug events for every acted-on row. Events
include monitor name, work item id, active revision, current phase/status, grace anchor,
elapsed grace seconds, selected action, and refusal/block code. They omit message bodies,
scope commands, tokens, and credentials. This telemetry is diagnostic only and never serves
as state or authorization evidence.

The three monitor query domains are disjoint:

```text
monitor_dispatched:
  dispatch_status = dispatched AND pr_number IS NULL AND active_scope_revision = 0

monitor_continuation:
  dispatch_status = dispatched AND pr_number IS NOT NULL AND active_scope_revision > 0

monitor_recovery:
  dispatch_status = escalated AND scope.continuation_enabled = true
```

`github_dispatch_scheduler.run_repo_once` invokes the stages in this order after watcher and
pending dispatch:

1. `monitor_dispatched`
2. `monitor_continuation`
3. `verification.process_scope`
4. `monitor_recovery`
5. `remind_held_leases`

Each stage re-queries its own rows and commits before the next stage. This lets verification
escalations become recovery candidates on the same scheduler pass while preventing an item
escalated by the continuation monitor from also being verified using a stale in-memory
list.

The recovery instruction includes failure evidence and tells the owner to perform read-only
diagnosis, then call `deck_request_continuation` with the smallest bounded proposal.

### 8.2 When the owner is unavailable

Continuation is owner-driven. If the owner is offline beyond the configured recovery
window, Deck does not let the Leader self-propose and self-approve.

The Leader may initiate the existing handoff protocol. The target then becomes owner and
submits a fresh proposal. If safe handoff cannot complete, the item remains escalated for an
operator.

### 8.3 Autonomy-off behavior

Disabling autonomy stops recovery nudges and automatic transitions. It does not delete
pending requests, active revisions, leases, or audit rows. Manual read APIs remain
available. Re-enabling autonomy resumes from persisted state idempotently.

---

## 9. API and Agent Mail/MCP surface

### 9.1 New REST routes

| Method and route | Caller | Purpose |
|---|---|---|
| `POST /github-work-items/{id}/continuation-requests` | current owner session | Propose bounded revision |
| `POST /agent-mail/continuation-decisions` | designated Leader session | Decide pending request |
| `POST /github-work-items/{id}/scope-revisions/{revision}/ack` | current owner session | Activate delivered revision |
| `GET /github-work-items/{id}/scope-revisions` | team member/operator | Audit history |
| `POST /github-work-items/{id}/continuation-requests/{request_id}/cancel` | requester or operator | Cancel pending request |
| `PATCH /github-scopes/{id}/continuation-policy` | operator | Enable/disable continuation and set finite caps |

Owner/Leader mutating routes require existing Agent Mail capability authentication.
The continuation-policy route requires `require_operator`. Cancellation accepts either the
authenticated current requester or an operator principal; the operator branch requires
`require_operator`. No route treats an external actor credential as either authority.

Cancellation is a synchronized terminal transition, not deletion:

1. require the request is the item's current `pending` request;
2. require the authenticated current requester or an operator principal;
3. set the approval request to `superseded` and stamp `superseded_at`;
4. set its linked proposed revision to `superseded`;
5. set the linked request root's `request_status = superseded`;
6. commit all three changes in one transaction and return the superseded request.

A repeated cancel is idempotent for the same caller/request. A subsequent Leader decision
returns `409 request_not_pending`. Agent Mail readers treat the root as terminal and do not
offer an answer action.

### 9.1.1 Dispatch-status report contract

Both completion reports continue through
`POST /api/v1/agent-teams/dispatch-status`. Add these exact authorization rules:

`backend/app/api/v1/agent_teams.py::_DISPATCH_STATUS_RULES` gains:

```text
diagnostic_completed:
  role = owner
  refusal = not_item_owner
  lease_token_required = true

continuation_completed:
  role = owner
  refusal = not_item_owner
  lease_token_required = true
```

`DispatchStatusReport` gains optional transport fields:

```text
active_scope_revision: Optional[int]
dispatch_nonce: Optional[str]
result_summary: Optional[str]
current_head_sha: Optional[str]
evidence: Optional[Dict[str, Any]]
```

They are optional at Pydantic parsing time for backward compatibility but required by the
corresponding status branch. `diagnostic_completed` requires all five fields.
`continuation_completed` requires revision, nonce, result summary, and current head SHA;
evidence may be empty. Validation happens after session/owner/lease authorization and before
any item or revision mutation. Unknown status behavior remains unchanged.

### 9.2 New MCP tools

- `deck_request_work_item_approval` (PR1; normalized initial-plan request)
- `deck_request_continuation`
- `deck_decide_continuation`
- `deck_ack_continuation`
- `deck_list_scope_revisions`

`deck_report_dispatch_status` adds `continuation_completed` and
`diagnostic_completed`, plus revision and evidence arguments.

The MCP shim preserves structured backend conflicts. For continuation tools, an HTTP 409
response surfaces the backend `detail` code and explanatory text in `error.message` rather
than replacing it with a generic request failure. This includes
`approval_request_already_pending`, stale owner/nonce/revision/workspace conflicts,
`diagnostic_tree_not_restored`, and `continuation_diff_inconclusive`. Tokens and response
headers remain excluded.

`deck_approve_work_item` remains the initial plan decision tool. It no longer searches mail
rows; it resolves the normalized current `initial_plan` approval request.

Generic `deck_request_context` calls never create approval authority, even when they carry a
work item id and nonce. PR1 adds
`POST /agent-mail/approval-requests` and `deck_request_work_item_approval`; the dispatch
brief uses that explicit operation for the initial plan. This prevents an ordinary
Leader question from becoming the current approval merely because it was sent first.

### 9.3 Existing response extensions

`GithubWorkItemResponse`, `deck_list_work_items`, and continuation context expose:

- `attempt_phase`
- `active_scope_revision`
- `active_scope_summary`
- `active_scope_status`
- `pending_approval_request_id`
- `pending_approval_kind`
- `diagnostic_retry_count`
- revision-specific failed-head count and budget
- continuation block code
- `retry_allowed` and `retry_block_code`, computed by the same backend predicate used by
  the retry route

Each hand-written projection gets its own test. Adding only ORM and Pydantic fields is not
sufficient.

`backend/app/api/v1/agent_teams.py::_work_item_response` cannot discover the normalized
rows synchronously. Its signature gains explicit preloaded values:

```text
active_revision: GithubAttemptScopeRevision | None = None
pending_approval: GithubApprovalRequest | None = None
```

List endpoints preload the active revision and unique pending approval with outer
joins/subqueries in bulk; they must not issue one query per work item or trigger async ORM
lazy loading from the synchronous serializer. Mutation endpoints that return a work item
reload those two rows before calling the helper.

`frontend/src/types/agentTeams.ts` gains the same contract:

- `TeamGithubScope` includes all six continuation-policy fields, while generic scope
  create/update types omit them and a dedicated operator-only policy-update type carries
  all six values;
- `GithubWorkItem` includes attempt phase, active revision number/summary/status, pending
  approval id/kind, diagnostic retry count, revision failed-head count/budget, and
  continuation block code;
- dedicated approval-request and scope-revision response interfaces model their lifecycle
  statuses and timestamps.

Frontend type-checking is part of every PR that changes this response surface.

---

## 10. Agent Bridge UI

The existing work-item dialog offers `Retry` for every escalated item even when retry is
known to be destructive. Replace the unconditional action with state-aware controls.

### 10.1 Work-item list

Show:

- dispatch status;
- attempt phase badge;
- active scope revision;
- pending continuation/approval indicator;
- product retry count;
- diagnostic failed-head count;
- explicit `Retry unavailable: PR #N is preserved` text when applicable.

### 10.2 Work-item dialog

Add an **Attempt recovery** section with:

- originating escalation;
- preserved PR, owner, workspace, and branch;
- current/pending scope revision;
- exact allowed paths/actions/commands;
- requester, Leader, decision, and timestamps;
- delivery/ack state;
- diagnostic evidence links;
- why automatic continuation is blocked.

The operator can cancel a pending request but cannot approve as a Leader or impersonate an
agent member. This preserves the distinct-approver design.

Agent Bridge asks the operator to enter the configured operator token before policy changes,
opening protected exact revision detail, or operator cancellation. It stores that token in
per-tab `sessionStorage`, never localStorage, never returns it from the backend, and sends it
only in `X-Deck-Operator-Token` to protected operator-capable routes. Clearing the tab
credential is an explicit UI action.

### 10.3 Retry button

Display Retry only when the existing retry endpoint can succeed safely. A held workspace on
an otherwise eligible PR-less escalation remains Retry-eligible: the backend records a
deferred retry and waits for safe release. When a preserved PR, active revision, or pending
approval blocks destructive retry, show `Continue attempt` status instead of inviting a
guaranteed 409.

---

## 11. Failure and restart behavior

| Failure point | Required result |
|---|---|
| Proposal validation fails | No approval/revision/mail row |
| Authority commit succeeds before request mail | Scheduler creates exactly one request root by delivery key |
| DB commit succeeds, Leader nudge fails | One pending request; scheduler re-nudges |
| Leader decision commit fails | No decision and no approved revision |
| Approval succeeds, owner delivery fails | Item remains escalated; delivery retries |
| Delivery succeeds, owner crashes before ack | Item remains escalated; restarted owner reads and acks |
| Owner acks twice | Second ack is idempotent when same owner/revision |
| Owner changes before ack | `409 stale_continuation_owner`; revision superseded |
| Nonce changes before ack | `409 stale_nonce`; revision superseded |
| GitHub issue changes while PR/continuation is preserved | Metadata refresh only; no retry marker/reset |
| Deck restarts during diagnostic | Phase, baseline, budget, and last head restore from DB |
| Diagnostic tree not reverted | Item stays diagnostic; product verification cannot start |
| Implementation continuation has not reported completion | Product verifier skips it |
| Diagnostic CI is green | Evidence only; never ready-for-review or merge |
| Leader disappears | Request remains pending until expiry, then item remains escalated |
| Autonomy is disabled | No nudges/transitions; state preserved |
| Active continuation owner goes idle | Same attempt returns to escalated; no reset |
| Pending request is cancelled | Request, revision, and mail root become superseded atomically |

No recovery branch may call `reset_for_retry`.

---

## 12. Security and authorization

1. Requester identity comes from `MailAgentSession`, never a body-supplied member id.
2. Current owner slot and member are checked server-side.
3. Leader identity is resolved from the current preset and checked server-side.
4. Requester and approver must be distinct slots and members.
5. Every mutation binds work item, dispatch nonce, approval round, owner, and revision.
6. Lease-token checks remain mandatory for Git/PR-affecting reports.
7. Allowed paths are verified against GitHub compare results before verification resumes.
8. Unknown actions, phases, statuses, and escalation reasons fail closed.
9. Approval and scope data are never inferred from message prose.
10. API responses and logs omit lease tokens, mail capability tokens, GitHub credentials,
    and operator tokens.

The system still cannot prevent an already-authorized shell process from editing an
unapproved file before it pushes. The control is detection before verification/merge, plus
an explicit instruction and audit trail. OS-level sandboxing is a separate project.

---

## 13. Test obligations

### 13.1 Approval invariant

1. First current request creates one approval row and one mail root.
2. Byte-identical repeat returns the same request id and creates no rows.
3. Different repeat returns `409 approval_request_already_pending`.
4. Owner/nonce/round change supersedes the old row before creating the new one.
5. Concurrent creates produce one pending row under the partial unique index.
6. Historical duplicate migration supersedes all duplicates and chooses none.
7. Decision resolves by approval id or the unique pending row, never a JSON scan.
8. Wrong Leader, self-approval, stale owner, stale nonce, and stale round fail.
9. Crash and concurrent-retry tests produce one request, decision, and delivery message per
    stable delivery key.
10. Disabled continuation, oversized budgets, excess revision count, excess total failed
    heads, invalid paths, and unknown actions fail before creating any row or mail.

### 13.2 Continuation preservation

11. Approving does not move an escalated item.
12. Delivery failure leaves it escalated and retryable by the delivery scheduler.
13. Correct owner ack activates the revision and moves to `dispatched`.
14. Ack preserves PR number, refs, nonce, owner, lease token, retry count, and both
    verification SHAs.
15. Ack by old owner, target slot, Leader, external actor, or operator fails.
16. Duplicate ack is idempotent only for the same active revision.
17. No continuation path calls `reset_for_retry`.
18. Workspace release/reacquisition between proposal and ack is rejected even when item,
    owner, and nonce are unchanged.
19. Ack refreshes continuation and owner-contact clocks without treating old dispatch/nudge
    timestamps as current.

### 13.3 Diagnostic accounting

20. Distinct failed diagnostic head increments diagnostic counters only.
21. Re-polling the same diagnostic head increments nothing.
22. Distinct failed implementation head increments product and revision counters.
23. Diagnostic budget exhaustion escalates without clearing attempt state.
24. Product budget history remains unchanged when a revision grants a new bounded budget.
25. Diagnostic completion rejects a current tree SHA different from the persisted baseline
    tree.
26. Diagnostic completion accepts a revert head with a different commit SHA and identical
    tree SHA.
27. Product verification cannot start while diagnostic restoration is unproven.
28. Reported restored head must equal the server-fetched current PR head.
29. Missing or inconclusive commit/tree metadata and truncated recursive trees fail closed.
30. An already-exhausted global retry count does not immediately exhaust a newly active
    revision; its own distinct-head budget controls the transition.
31. `continuation_completed` leaves the revision submitted until green, then completes it.

### 13.4 Delivery, restart, and handoff

32. Approved revision survives backend restart before delivery.
33. Delivered revision survives owner restart before ack.
34. `deck_get_work_item_context` returns the same revision after restart.
35. Handoff supersedes the active revision and target cannot use it.
36. Target can submit and receive approval for a new revision.
37. Autonomy off preserves rows and suppresses recovery nudges.
38. Re-enable resumes exactly one pending recovery action.
39. A PR-bearing dispatched continuation is monitored for owner progress and safely
    re-escalates on idle without resetting the attempt.

### 13.5 API/MCP/UI projections

40. Every new work-item and scope-policy field appears in REST and agentic projections.
41. MCP tools derive caller identity from the session and omit secrets.
42. Agent Bridge shows continuation state and hides unsafe Retry.
43. Operator UI cannot write a Leader decision.

### 13.6 Regression guards

44. `dispatch_label_removed` remains non-continuable.
45. `continuation_budget_exhausted` remains non-continuable.
46. Human merge remains human.
47. Existing prepared-attempt resume behavior remains operator-only.
48. Existing workspace release and handoff race tests remain unchanged.
49. Initial approval still requires a structured Leader decision.
50. Existing retry still resets only when its current preconditions are satisfied.
51. Mail readers treat migrated `superseded` roots as terminal.

### 13.7 External-review regression gates

52. A newer GitHub issue update on an escalated PR-bearing item updates metadata without
    calling `reset_for_retry`, setting `retry_requested_at`, or changing continuation state.
53. `promote_deferred_retries` refuses a PR, active revision, or pending approval even when
    a stale retry marker exists.
54. Product verification skips a `dispatched` implementation continuation until the
    authenticated completion report moves it to `verifying`.
55. Green diagnostic checks record evidence without calling `_promote_verified_item` or
    changing review/merge state.
56. One scheduler pass exercises disjoint initial-dispatch, active-continuation, and
    escalated-recovery fixtures through the three explicit monitors with no clock crosstalk.
57. Both completion statuses accept the valid owner/token/revision/nonce shape and reject
    missing fields, wrong owner, stale nonce/revision, and wrong lease token before mutation.
58. Requester and operator cancellation atomically supersede approval, revision, and mail
    root; a later Leader decision is rejected.
59. Work-item list and mutation responses project preloaded normalized rows without lazy
    loading or N+1 queries.
60. The SQLite compatibility migration is idempotent over a pre-feature fixture and
    preserves PR-bearing attempt state while clearing only its unsafe retry marker.
61. Frontend TypeScript compilation covers all scope policy, work-item, approval, and
    revision response fields.
62. Sequential rejected/proposed revisions allocate `1, 2, 3`; concurrent proposals leave
    one pending request and no duplicate revision number.
63. Tree-based path validation detects mode-only changes and out-of-scope paths and refuses
    truncated recursive tree responses.
64. Continuation/recovery monitor tests capture structured debug events with item, revision,
    elapsed grace, action, and block code while proving no token or command payload is
    logged.
65. MCP continuation tools preserve backend 409 detail codes/messages and still redact
    tokens and headers.
66. Generic work-item context requests create no approval row; only the authenticated
    initial-approval route/tool can create `request_kind = initial_plan`.
67. Diagnostic proposals persist `execution_target`; hosted-only scopes reject local build
    commands and local-only diagnostics cannot request hosted tool installation.
68. REST and Agent Bridge use the same server-side Retry eligibility predicate; a PR-bearing
    or active-continuation item cannot render an actionable Retry control.
69. Generic scope create/update cannot enable or alter continuation policy; the dedicated
    policy route and Agent Bridge's protected revision-detail/cancellation calls require a
    valid operator token and reject external-actor credentials.

---

## 14. Delivery plan

Implementation is staged and every PR targets `feature/autonomous-github-dispatch`.
Nothing targets `master` until the resumed soak passes.

### PR1 — Approval request authority

- Create both normalized tables and their foreign keys so SQLite never needs a later table
  rebuild. `github_attempt_scope_revisions` remains empty/inert in PR1; PR2 owns every
  writer and continuation transition.
- Add `github_approval_requests`, idempotent compatibility migration, and backfill.
- Add idempotent server-authored Agent Mail delivery keys.
- Enforce one pending request.
- Move initial-plan decision resolution off mail JSON scans.
- Add the explicit initial-plan approval request route/tool and update the dispatch brief;
  generic context requests remain non-authoritative.
- Add synchronized request cancellation and terminal mail-root behavior.
- Add REST/MCP projections and regression tests.

PR1 changes no continuation state and should be deployable with autonomy off.

### PR2 — Scope revisions and non-destructive continuation

- Activate the already-created scope revision model and add work-item fields.
- Add scope-level continuation policy and hard attempt caps.
- Add proposal, decision, delivery, acknowledgement, cancellation, and context APIs.
- Guard watcher refresh/deferred retry against preserved attempts.
- Add completion-report authorization/schema and implementation path validation.
- Gate product verification until authenticated continuation submission.
- Add `monitor_continuation` and its scheduler hook.
- Add MCP tools.
- Add preservation, restart, and handoff tests.

Continuation remains disabled on every scope during staged deployment. PR2 contains a
complete implementation-continuation state machine but does not yet classify diagnostic CI
or initiate recovery automatically.

### PR3 — Diagnostic accounting and recovery monitor

- Add phase-aware verification accounting.
- Add diagnostic/product completion reports and GitHub tree/path enforcement.
- Add diagnostic-only check observation.
- Add `monitor_recovery` and complete the explicit scheduler ordering.
- Add automatic recovery nudges, cooldowns, and expiry.
- Add structured continuation/recovery monitor telemetry.
- Add hosted-tool fallback policy.

### PR4 — Agent Bridge visibility and replay tooling

- Add work-item continuation UI.
- Add bulk normalized-row projections and frontend response types.
- Preserve structured continuation conflict details through the MCP shim.
- Replace unsafe unconditional Retry affordances.
- Add end-to-end observability and replay checklist.

Each PR is reviewed and merged into the integration branch before the next begins.

---

## 15. Deployment and Tizonia replay

1. Keep `tizonia-v1.autonomy_enabled = false` during implementation and deployment.
2. Back up the Deck database.
3. Deploy PR1–PR4 from the integration branch.
4. Enable continuation for the Tizonia scope with reviewed finite caps; leave every other
   migrated scope disabled.
5. Verify migration reconciliation does not mutate item 23's PR, owner, lease, counters, or
   nonce.
6. Ensure Specialist and Leader each have exactly one live, authenticated session.
7. Re-enable autonomy for `tizonia-v1`.
8. Confirm Deck nudges the Specialist to propose continuation for item 23.
9. Specialist proposes a diagnostic revision that permits:
   - `tests/playback_smoke.py.in` diagnostic instrumentation;
   - temporary `gdb` installation in the hosted playback job if absent;
   - hosted CI execution and log collection;
   - mandatory revert of diagnostic changes.
10. Leader approves through `deck_decide_continuation` without human involvement.
11. Specialist acknowledges and executes the revision.
12. Deck records diagnostic failure/evidence without changing `retry_count`.
13. Specialist reverts the diagnostic tree and reports `diagnostic_completed`.
14. Deck proves the net diff is empty and requests the next bounded implementation proposal.
15. Continue until product CI is green or the finite continuation budget stops the attempt.
16. Keep PR #875 draft until the normal ready-for-review transition.
17. A human performs the merge.

The replay fails if a coordinator must commit, push, approve, report status, repair DB rows,
or relay a token on the owner's behalf.

---

## 16. Success criteria

The design is successful when all of the following are true:

1. A recoverable escalated attempt progresses through Leader-only approval with no human.
2. No retry/reset occurs and no attempt identity is lost.
3. At most one pending approval request exists at every point.
4. The owner receives and acknowledges a persisted, versioned scope.
5. Diagnostic and product verification budgets remain distinct.
6. Diagnostic changes cannot leak into final verification unnoticed.
7. Restart and handoff preserve safety and liveness.
8. Human stop and merge policies remain stronger than autonomous continuation.
9. REST, MCP, and Agent Bridge show the same state.
10. Preserved Tizonia item 23 / PR #875 completes the replay without coordinator
    intervention.

External review cleared revision 2 with no blockers or important corrections. Revision 3
incorporated its two non-blocking observability suggestions. Revisions 4–7 add the persisted
execution target, server-derived Retry eligibility, dedicated operator-only policy surface,
and explicit protected-detail UI credential path required to implement the already-approved
diagnostic and UI contracts; they do not change the reviewed authority or state machine.
The specification is ready for implementation planning.
