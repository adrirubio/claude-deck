# PR1 — Approval Request Authority Implementation Plan

> **For implementation agents:** Execute this plan task by task with tests first. Stop when
> a measured code shape contradicts the plan; do not infer a convenient replacement.

**Goal:** Replace mail-row discovery with one normalized, authenticated approval-request
authority while adding crash-safe, idempotent Agent Mail delivery. Create the scope-revision
table as an inert schema prerequisite, but do not activate continuation behavior.

**Architecture:** `GithubApprovalRequest` is the authoritative request/decision record.
`MailMessage` remains transport and evidence. Stable `delivery_key` values make
server-authored mail recoverable after process crashes and concurrent scheduler retries.
Initial plan approval gets an explicit route/tool; generic context questions never create
approval authority. Both normalized tables are created in PR1 because SQLite cannot add the
cross-table foreign keys later without rebuilding tables.

**Spec:** `docs/superpowers/specs/2026-08-29-autonomous-attempt-recovery-design.md`,
Revision 7, especially §§4.3–4.4, 5.1–5.2, 5.5, 6.3, 9.1–9.3, 13.1, and 14 PR1.

**Issue:** `https://github.com/adrirubio/claude-deck/issues/325`

**Target:** One PR into `feature/autonomous-github-dispatch`, never `master`.

**Starting point:** Latest `origin/feature/autonomous-github-dispatch`. Record the exact SHA
in the PR description. PR1 must be merged into the integration branch before PR2 starts.

## Precedence

1. Current source code is the execution baseline.
2. The approved specification defines behavior.
3. This plan defines task order and PR boundaries.
4. If the plan and spec disagree without an explicit **Planning correction**, stop and
   report.

**Planning correction — SQLite FK ordering:** PR1 creates both
`github_approval_requests` and `github_attempt_scope_revisions`, including their nullable
cross-links. The revision table stays empty and has no API/service writer until PR2. This is
the approved §14 boundary and avoids a forbidden SQLite table rebuild.

**Planning correction — explicit initial approval:** Generic `deck_request_context` remains
non-authoritative. PR1 adds `deck_request_work_item_approval` and
`POST /agent-mail/approval-requests`; the dispatch brief uses them.

## Global Safety Constraints

- Work in a new isolated worktree, not the running checkout at
  `/home/juan/work/repos/juanrubio/claude-deck`.
- Do not touch `/home/juan/work/repos/tizonia/`, Tizonia PR #875, or Deck work item 23.
- Do not start or stop Deck, tmux, or agent sessions.
- Keep `tizonia-v1.autonomy_enabled = false`.
- Tests use temporary SQLite databases. Never run tests with the live checkout as CWD.
- Never read, print, export, or log Agent Mail, workspace, operator, GitHub App, or PAT
  tokens.
- Do not change `dispatch_status`, retry semantics, verification behavior, or continuation
  state in PR1.
- The inert scope-revision table must have no route, MCP tool, scheduler writer, or active
  work-item pointer in this PR.
- Commit after each task. Push/open the PR only after final validation.

## Branch and Baseline Setup

- [ ] Fetch without rebasing another worktree:

  ```bash
  git fetch origin feature/autonomous-github-dispatch
  git worktree add -b feature/approval-request-authority \
    /home/juan/work/repos/juanrubio/claude-deck-recovery-pr1 \
    origin/feature/autonomous-github-dispatch
  cd /home/juan/work/repos/juanrubio/claude-deck-recovery-pr1
  ```

- [ ] Confirm the live checkout and Tizonia checkout are not modified.
- [ ] Record baseline collection and results from the isolated worktree:

  ```bash
  cd backend
  ../backend/venv/bin/pytest tests/agent_mail tests/agent_teams \
    tests/test_sqlite_compat_migrations.py --collect-only -q
  ../backend/venv/bin/pytest tests/agent_mail tests/agent_teams \
    tests/test_sqlite_compat_migrations.py -q -p no:warnings
  ```

  If the venv path differs, use the existing repository venv; do not create a second
  dependency lock or modify requirements for this feature.

## File Map

| File | Action | Responsibility |
|---|---|---|
| `backend/app/models/database.py` | Modify | Approval/revision models and mail delivery key |
| `backend/app/database.py` | Modify | Idempotent SQLite compatibility migration/backfill |
| `backend/app/models/schemas.py` | Modify | Approval request/decision responses |
| `backend/app/services/github_approval_service.py` | Create | Normalized authority, fingerprinting, decisions, cancellation |
| `backend/app/services/agent_mail_service.py` | Modify | Idempotent server-authored mail; generic context stays non-authoritative |
| `backend/app/services/github_dispatch_service.py` | Modify | Initial approval request creation and round advancement integration |
| `backend/app/api/v1/agent_mail.py` | Modify | Explicit request and normalized decision routes |
| `backend/app/api/v1/router.py` | Verify/modify only if needed | Route registration consistency |
| `backend/mcp_shim/agent_mail_server.py` | Modify | Explicit initial approval tool and normalized decision handling |
| `backend/tests/test_sqlite_compat_migrations.py` | Modify | Fresh/legacy/idempotent schema tests |
| `backend/tests/agent_mail/test_models.py` | Modify | Constraints and defaults |
| `backend/tests/agent_mail/test_api.py` | Modify | Request/decision/cancellation authorization |
| `backend/tests/agent_mail/test_messaging.py` | Modify | Delivery-key idempotency |
| `backend/tests/agent_mail/test_mcp_shim.py` | Modify | Tool payloads and error propagation |
| `backend/tests/agent_teams/test_github_dispatch_service.py` | Modify | Brief and approval-round integration |
| `docs/deploy/attempt-recovery-pr1-rollout.md` | Create | Inert rollout and restart requirements |

## Task Index

| Task | Deliverable |
|---|---|
| 1 | Normalized schema and constraints |
| 2 | SQLite compatibility and reconciliation |
| 3 | Approval service primitives |
| 4 | Idempotent Agent Mail delivery |
| 5 | Explicit initial approval request |
| 6 | Normalized Leader decision |
| 7 | Cancellation and terminal mail state |
| 8 | MCP and dispatch brief integration |
| 9 | Regression and concurrency sweep |
| 10 | Rollout documentation and PR validation |

---

## Task 1 — Add Normalized Schema and Constraints

**Files:** `backend/app/models/database.py`, `backend/tests/agent_mail/test_models.py`

- [ ] Write failing model tests for:
  - nullable unique `MailMessage.delivery_key`;
  - `GithubApprovalRequest` fields/status defaults;
  - one pending request per work item via partial unique index;
  - `GithubAttemptScopeRevision` complete inert schema;
  - unique `(work_item_id, dispatch_nonce, revision)`;
  - nullable cross-links with `ON DELETE SET NULL` where a lifecycle row may survive its
    evidence message.
- [ ] Add the full models from spec §5.1 and §5.2. Use timezone-naive UTC consistently with
  current models.
- [ ] Use explicit SQLAlchemy `Index(..., unique=True, sqlite_where=...)` for the pending
  request and delivery-key invariants. A preflight query is not sufficient.
- [ ] Keep lifecycle strings as application-validated strings; do not add a database enum
  inconsistent with existing SQLite conventions.
- [ ] Prove NULL delivery keys can repeat while duplicate non-NULL keys fail.
- [ ] Prove the revision table has no writer outside tests.

**Mutation checks:** remove each unique index; change pending predicate to all statuses;
make delivery key non-null; remove one FK.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_mail/test_models.py -q -p no:warnings
```

**Commit:** `feat: add normalized github approval schema`

---

## Task 2 — Add SQLite Compatibility and Historical Reconciliation

**Files:** `backend/app/database.py`, `backend/tests/test_sqlite_compat_migrations.py`

- [ ] Start from a fixture that predates PR1 and contains:
  - one valid current initial-plan context request;
  - two ambiguous current roots for another item;
  - terminal/old-round roots that must not be selected;
  - a PR-bearing item with an unsafe `retry_requested_at` marker.
- [ ] Extend `_run_sqlite_compat_migrations` after `Base.metadata.create_all` to add
  `mail_messages.delivery_key` and its partial unique index to existing tables.
- [ ] Verify both normalized tables and all indexes exist. `create_all` owns fresh table
  creation; the compatibility helper verifies/repairs indexes idempotently.
- [ ] Reconcile historical roots without SQLite JSON1 assumptions: load candidate payload
  bytes, decode in Python, and group by current work-item owner/Leader/nonce/round.
- [ ] Backfill exactly one pending initial approval for a single unambiguous root.
- [ ] For multiple current roots, set each root `request_status = superseded`, create no
  approval row, and write the fresh-request status note.
- [ ] Clear `retry_requested_at` only on rows with a non-NULL PR number. Preserve every
  other attempt field byte-for-byte.
- [ ] Run the migration twice and compare schema, indexes, row counts, statuses, and attempt
  fields.

**Mutation checks:** choose the newest ambiguous root; depend on `json_extract`; clear every
retry marker; omit the partial index; duplicate rows on the second run.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/test_sqlite_compat_migrations.py -q -p no:warnings
```

**Commit:** `feat: reconcile normalized github approval records`

---

## Task 3 — Implement Approval Authority Primitives

**Files:** `backend/app/services/github_approval_service.py`,
`backend/tests/agent_mail/test_api.py`

- [ ] Define one service for canonical payload serialization, SHA-256 fingerprints,
  current pending lookup, creation, decision validation, supersession, and cancellation.
- [ ] Canonicalize sorted JSON with stable separators and UTF-8 bytes. Never fingerprint
  rendered Markdown.
- [ ] Implement initial request creation under one transaction:
  - authenticate current owner member and designated Leader;
  - bind work item, nonce, approval round, owner, and Leader;
  - enforce `request_kind = initial_plan` and `scope_revision_id = NULL`;
  - insert and flush;
  - catch unique conflicts, roll back, and re-read the winner;
  - return the winner only for an identical fingerprint/identity tuple.
- [ ] Implement decision validation by explicit request id or the database-enforced unique
  pending row. Never scan `MailMessage.payload` to rediscover authority.
- [ ] Add typed service errors carrying stable HTTP detail codes.
- [ ] Test owner/Leader changes, stale nonce/round, self-approval, wrong preset, duplicate
  identical request, conflicting request, and concurrent creators.

**Mutation checks:** trust body-supplied member id; ignore nonce; compare rendered prose;
return a conflicting winner; query mail roots.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_mail/test_api.py -q -p no:warnings
```

**Commit:** `feat: add github approval authority service`

---

## Task 4 — Make Server-Authored Agent Mail Idempotent

**Files:** `backend/app/services/agent_mail_service.py`,
`backend/app/models/schemas.py`, `backend/tests/agent_mail/test_messaging.py`

- [ ] Add an internal-only optional `delivery_key` argument to message creation/send helpers.
  Do not expose it on public agent-authored `MailMessageCreate` payloads.
- [ ] On a unique conflict, re-read the existing message and compare kind, sender, recipient,
  thread root, and canonical payload bytes. Return it only on exact agreement.
- [ ] A mismatch raises a stable server-integrity error and creates no receipt or nudge.
- [ ] Ensure concurrent retries create one message and one receipt per recipient.
- [ ] Ensure a crash after mail commit but before authority-row linkage can recover the same
  message by delivery key.
- [ ] Preserve existing commit/nudge semantics for calls without a delivery key.

**Mutation checks:** dedupe by key without payload verification; generate random keys on
retry; create receipts before conflict handling; expose delivery keys in API responses.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_mail/test_messaging.py -q -p no:warnings
```

**Commit:** `feat: make server agent mail delivery idempotent`

---

## Task 5 — Add Explicit Initial Approval Requests

**Files:** `backend/app/api/v1/agent_mail.py`,
`backend/app/models/schemas.py`, `backend/app/services/github_dispatch_service.py`,
`backend/app/services/agent_mail_service.py`, `backend/tests/agent_mail/test_api.py`,
`backend/tests/agent_teams/test_github_dispatch_service.py`

- [ ] Add request/response schemas and
  `POST /api/v1/agent-mail/approval-requests`.
- [ ] Require `MailAgentSession`; derive owner member server-side; require work item, nonce,
  plan summary, and optional structured plan metadata.
- [ ] Call the authority service first and commit the normalized row before mail transport.
- [ ] Send/recover exactly one context-request root with
  `github-approval:{request_id}:request`, then link it in a second commit.
- [ ] If linking fails after mail commit, a repeated request repairs the same link.
- [ ] Change linked generic context requests so they remain authenticated context but never
  create approval rows.
- [ ] Update `_dispatch_brief` to instruct the owner to use the explicit approval tool and
  wait for its structured decision before implementation.
- [ ] Keep work items stopped if the authority row exists but the mail root is not linked.

**Mutation checks:** send mail before authority commit; infer approval from generic context;
trust sender id; omit the wait instruction; create a second mail root after link failure.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_mail/test_api.py \
  tests/agent_teams/test_github_dispatch_service.py -q -p no:warnings
```

**Commit:** `feat: add explicit work item approval requests`

---

## Task 6 — Rewire Leader Decisions to Normalized Authority

**Files:** `backend/app/api/v1/agent_mail.py`,
`backend/app/services/github_approval_service.py`,
`backend/app/services/github_dispatch_service.py`,
`backend/tests/agent_mail/test_api.py`

- [ ] Remove the context-root scan from `decide_work_item`.
- [ ] Resolve the explicit request id when supplied, otherwise the one pending
  `initial_plan` request for work item/nonce.
- [ ] Validate authenticated designated Leader, distinct owner/Leader member and slot,
  current nonce/round/owner, and pending status.
- [ ] Commit the authoritative approved/rejected state before sending the decision mail.
- [ ] Create/recover the decision answer with
  `github-approval:{request_id}:decision`, link it, then invoke existing approval-round/ack
  integration without parsing prose.
- [ ] Preserve current rejection-round semantics, but supersede the old normalized request
  before opening the next round.
- [ ] Replace `github_dispatch_service._ack_evidence` mail-root/answer scans with the
  normalized approved initial-plan request, then validate its linked authenticated decision
  message. No ack or merge gate may rediscover approval from arbitrary mail rows.
- [ ] Make identical decisions idempotent and opposite terminal decisions return
  `409 approval_request_already_decided`.
- [ ] Ensure auto-merge/ack evidence still points to the authenticated decision message.

**Mutation checks:** use first matching mail root; keep `_ack_evidence` scanning answers;
approve from owner; commit mail before authority; accept opposite replay; treat ordinary
answer as approval.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_mail/test_api.py \
  tests/agent_teams/test_github_verification_service.py -q -p no:warnings
```

**Commit:** `refactor: resolve work item decisions from approval records`

---

## Task 7 — Synchronize Cancellation and Terminal Mail State

**Files:** `backend/app/services/github_approval_service.py`,
`backend/tests/agent_mail/test_api.py`, `backend/tests/agent_mail/test_messaging.py`

- [ ] Implement the service-level cancellation transition now; PR2 adds the continuation
  route that calls it.
- [ ] Require pending status and authenticated requester or operator principal.
- [ ] In one transaction set approval request, linked inert/proposed revision, and linked
  mail root to `superseded`; stamp `superseded_at`.
- [ ] Make repeated cancellation idempotent for the same authority.
- [ ] Ensure inbox/pending queries and answer creation treat `superseded` as terminal.
- [ ] A Leader decision after cancellation returns `409 request_not_pending`.

**Mutation checks:** update only the approval row; leave mail pending; permit answer after
cancel; delete rows; let an unrelated team member cancel.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_mail/test_api.py \
  tests/agent_mail/test_messaging.py -q -p no:warnings
```

**Commit:** `feat: synchronize approval request cancellation`

---

## Task 8 — Add MCP Tools and Brief Compatibility

**Files:** `backend/mcp_shim/agent_mail_server.py`,
`backend/tests/agent_mail/test_mcp_shim.py`,
`backend/tests/agent_mail/test_dispatch_status_tool.py`

- [ ] Add `deck_request_work_item_approval(work_item_id, dispatch_nonce, summary, ...)`.
- [ ] Keep `deck_request_context` unchanged and non-authoritative.
- [ ] Extend `deck_approve_work_item` with optional `approval_request_id`; preserve the
  work-item/nonce fallback to the unique pending request.
- [ ] Return stable request id, mail root id when linked, status, and approval round.
- [ ] Preserve backend detail code/message for 409 responses and redact headers/tokens.
- [ ] Update docstrings and generated tool schemas so agents do not use generic context for
  initial approval.
- [ ] Test exact API prefixes and payloads.

**Mutation checks:** route request to agent-teams prefix; omit session token; map all 409s to
generic failure; keep old brief/tool wording.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_mail/test_mcp_shim.py \
  tests/agent_mail/test_dispatch_status_tool.py -q -p no:warnings
```

**Commit:** `feat: expose normalized work item approval tools`

---

## Task 9 — Run Concurrency and Regression Sweep

**Files:** tests only unless a defect is found in PR1-owned behavior.

- [ ] Add a file-backed SQLite WAL race for two identical request creators.
- [ ] Add a conflicting-payload race proving one pending row and no orphan revision/mail.
- [ ] Simulate crashes at authority commit, request-mail commit, request-link commit,
  decision commit, decision-mail commit, and decision-link commit.
- [ ] Re-run existing approval, ack, auto-merge, inbox, receipt, and migration suites.
- [ ] Verify generic context answers still work but cannot satisfy approval.
- [ ] Verify no continuation route/tool/work-item fields are activated.
- [ ] Run every named mutation from Tasks 1–8 against its claimed test.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_mail tests/agent_teams \
  tests/test_sqlite_compat_migrations.py -q -p no:warnings
```

**Commit:** `test: harden normalized approval authority`

---

## Task 10 — Document Inert Rollout and Validate PR

**Files:** `docs/deploy/attempt-recovery-pr1-rollout.md`

- [ ] Document migration backup, backend restart, pane/MCP restart requirement for the new
  explicit tool, and rollback behavior.
- [ ] State that autonomy and continuation remain off; no live Tizonia replay occurs.
- [ ] Document the ambiguous-root reconciliation and how an owner creates one fresh request.
- [ ] Record exact test counts measured after implementation; do not predict them here.
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

- [ ] Report unrelated baseline failures without fixing them.
- [ ] Confirm the diff has no scope policy, continuation transitions, diagnostic counters,
  monitor hooks, or UI changes.
- [ ] Open one PR targeting `feature/autonomous-github-dispatch` and stop. Do not merge.

**Commit:** `docs: add approval authority rollout guide`

## PR1 Exit Gate

PR1 is complete only when:

- one pending normalized request is database-enforced;
- initial approval creation is explicit and authenticated;
- decisions no longer scan mail payloads;
- server mail retries are idempotent under crashes/concurrency;
- cancellation synchronizes authority/revision/mail state;
- historical ambiguity chooses no winner;
- scope revision persistence is inert;
- autonomy remains disabled;
- the PR targets only `feature/autonomous-github-dispatch`.
