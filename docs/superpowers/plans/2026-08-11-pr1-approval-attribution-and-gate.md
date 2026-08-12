# PR1 — Approval Attribution and Distinct-Approver Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist one complete dispatch-attempt identity, attribute approval to the authenticated designated leader and current approval round, prevent stale or self-authored evidence from satisfying auto-merge, and make handoff continuation and workspace release safe under concurrent ownership changes.

**Architecture:** PR1 builds on PR0's capability-token and pane-binding enforcement. A prepared attempt is a committed five-part record (`owner_slot_id`, `routing_method`, `dispatch_nonce`, `dispatch_head_ref`, `approval_round_count`) created before any brief is delivered. Agent Mail records explicit `approved` or `rejected` decisions, the dispatch service persists auditable approval evidence, and the verification service checks that evidence through a dedicated merge predicate. Handoff moves authority and process-liveness evidence in one transaction. Continuation context returns the persisted attempt and live lease token only to the authenticated current owner. Agent release and contact stamping use conditional SQL writes that bind the row, acquisition, and current owner at the write boundary.

**Tech Stack:** FastAPI, async SQLAlchemy + aiosqlite, Pydantic, pytest + pytest-asyncio + httpx `ASGITransport`, the existing Python MCP shim, SQLite WAL concurrency probes, and the existing Agent Mail and GitHub dispatch services.

**Spec:** `docs/superpowers/specs/2026-08-05-distinct-approver-identity-design.md` — **revision 19**, spec commit `8d7321b`, especially §3.4a, §3.5, §3.5a, and §4.1–§4.8. Implementation baseline is the shipped PR0 tip `5d66d12`. This plan implements **PR1 only**. PR2 remains responsible for repository authentication, credential delivery, `pr_ready`, PR reconciliation, and distinct commit/PR identity.

**PR boundary:** *PR1 owns the record; PR2 owns enforcement that reads the PR/head-specific parts of it.* PR1 stores and exposes `dispatch_head_ref`; it does not implement the PR2 `pr_ready` route or GitHub credential helper.

**Precedence, when documents disagree**

| Situation | What to do |
| --- | --- |
| The plan and the spec disagree, **and the plan marks the difference `Correction (date, review)`** | The plan wins. The correction was verified against source after the spec revision. |
| The plan and the spec disagree, and the plan does **not** mark it | **Stop and report.** Do not choose a convenient interpretation. |
| The plan and the **code** disagree | **Stop and report.** A moved line is fine; a changed function shape, dependency, commit boundary, or caller set is not. |

## Global Constraints

These rules apply to every task.

**Working environment — you are on the SAME machine as the live soak**

- Work only in `/home/juan/work/repos/juanrubio/claude-deck-g1`.
- Never touch `/home/juan/work/repos/juanrubio/claude-deck`. It is the live soak checkout and contains the non-regenerable DB rows behind the design measurements.
- Never touch `/home/juan/work/repos/tizonia/`.
- Do not start, stop, or restart uvicorn, tmux sessions, or agent sessions. If a tmux server appears, it is not yours.
- Autonomy stays **OFF**. Do not dispatch a real issue to test this PR.
- Do not hand-edit any live DB row. Live DB access, if needed at all, is read-only with SQLite URI `mode=ro`.
- The application DB URL is CWD-relative. Never run pytest, migrations, or a server with the live checkout as CWD.

**Git**

- Continue from PR0 tip `5d66d12` in this g1 worktree. PR1 ultimately opens one PR into `feature/autonomous-github-dispatch`.
- This worktree shares `.git` with the live checkout. Forbidden: `git worktree prune`, `git gc`, `git stash`, `git reset --hard`, `git branch -f`, ref deletion, and checking out a branch held by another worktree.
- Never use `git checkout -- <file>` on uncommitted work. Reverse only the exact edit you made.
- Commit locally after every task with the commit message given by that task.
- Do not push, merge, or target `master` while executing this plan unless the user gives a later explicit instruction.

**Forbidden operations**

- **No new `dispatch_status` values.** `routing_method = "operator_resume"` is permitted and must be tested; it is not a dispatch status.
- Do not add `prepared_owner_unavailable` to `_PR_OPENED_RECOVERABLE_ESCALATIONS`.
- Do not rotate `lease_token` during handoff.
- Do not recompute `dispatch_head_ref` after preparation and do not nest it under another `deck/...` ref.
- Do not parse approval prose. The `decision` column is the decision.
- Do not use `request_status == "acknowledged"` as approval evidence.
- Do not weaken the distinct-leader requirement for `leader_fallback`; a leader-owned work item cannot auto-merge.
- Never print a token or PAT plaintext. `backend/.env` stays mode `0600` and gitignored. Never export a secret into tmux's global environment.
- The migration ladder is additive only. No `DROP`, table rebuild, or DB deletion.
- Do not split `agent_mail_service.py` or `github_dispatch_service.py`.

**Code style**

- Use `python3`; the virtual environment is `backend/venv`.
- Keep type hints and async boundaries explicit.
- Reuse existing services and dependencies rather than adding parallel queries or auth paths.
- A preliminary route check is diagnostic; a conditional SQL `UPDATE` predicate is the authorization control.
- Fresh reads must actually query: use `select(...)`, `populate_existing=True`, or `refresh()`. Do not use `db.get(...)` where freshness is required because the identity map may return the stale object.
- Conditional lease writes use ordinary SQL equality: `GithubWorkspace.lease_token == lease_token`. Never use `IS`, `IS NOT DISTINCT FROM`, or a manual null-safe `OR`. This is an explicit code-review check; no reachable test can distinguish the both-NULL case.
- `AsyncSessionLocal` has `autoflush=False`. If a request changes a column used by a following conditional SQL predicate, `await db.flush()` before the statement.
- `attempt_head_ref(item, slot_id)` returns exactly `deck/slot-<numeric-slot-id>/issue-<issue-number>-<full-16-hex-nonce>`. It is called exactly once, by `prepare_attempt`.

**Testing**

- `cd backend` first, every time.
- Run `venv/bin/pytest ... -q -p no:warnings`.
- Baseline at PR0 tip `5d66d12`:
  - `venv/bin/pytest tests/agent_teams/ tests/agent_mail/ -q -p no:warnings` → **561 passed**.
  - `venv/bin/pytest tests/ -q -p no:warnings` → **732 passed, 1 failed**. The one pre-existing failure is `tests/test_multi_provider_smoke.py::test_agent_bridge_session_filter_smoke` (issue #312). Report it; do not fix it in PR1.
- Expected counts below are collected cases, not test functions. Parameterized cases count separately.

  | After task | New scoped cases (cumulative) | `agent_teams/ + agent_mail/` | Whole `tests/` |
  | --- | ---: | ---: | ---: |
  | baseline | 0 | **561** | **732** + 1 failed |
  | 1 | 3 | 564 | 736 + 1 failed |
  | 2 | 15 | 576 | 748 + 1 failed |
  | 3 | 31 | 592 | 764 + 1 failed |
  | 4 | 41 | 602 | 774 + 1 failed |
  | 5 | 55 | 616 | 788 + 1 failed |
  | 6 | 70 | 631 | 803 + 1 failed |
  | 7 | 77 | 638 | 810 + 1 failed |
  | 8 | 81 | 642 | 814 + 1 failed |
  | 9 | 101 | 662 | 834 + 1 failed |
  | 10 | 118 | **679** | **851** + 1 failed |

  Task 1 adds one migration-ladder case outside the scoped directories, so the full-suite total advances by four while the scoped total advances by three. Tasks 2–10 add only scoped cases. Three existing approval-cap tests are re-authored in Task 2 and do not change collection counts.
- The measurement wins if pytest and the table disagree. Stop and report the mismatch; do not silently adjust a test or this arithmetic.
- Write each task's mutant list **before** its tests. Run each test against the exact mutant it claims to kill. A test that passes both the intended code and its mutant is not coverage.
- Route tests use `app.dependency_overrides[get_db]` and `httpx.ASGITransport`. Its client port is synthetic; never infer a real peer socket from it.
- Assert durable state using raw SQL or a fresh session, not the ORM object just mutated.
- Use a file-backed SQLite DB for WAL races. An in-memory engine cannot reproduce concurrent reader/writer ordering.
- The `db` fixture in `tests/agent_teams/test_github_dispatch_service.py` is a plain in-memory engine, not `StaticPool`. For the deleted-owner FK case, register the foreign-key connect listener before `create_all` and assert `PRAGMA foreign_keys == 1` inside the fixture.
- `github_workspaces.path` is unique; use a unique path for every workspace fixture.
- Quote zsh globs such as `--include="*.py"`.
- Override settings with `monkeypatch.setattr(settings, "<name>", value)`. Do not construct a second `Settings()`.
- Tests of declared defaults inspect `Settings.model_fields["<field>"].default`; never delete or rename `backend/.env` to make a test pass.

**Stop and report**

Stop before editing further if any function has a different shape than this plan, if an existing test asserts the opposite contract, if a dependency returns a different type, if a planned conditional write cannot be expressed without changing a commit boundary, or if a required test is green against its named mutant.

## File Structure

| File | Create / Modify | Responsibility |
| --- | --- | --- |
| `backend/app/database.py` | Modify | Eight additive migration rungs: six work-item columns and two mail-message columns |
| `backend/app/models/database.py` | Modify | Six `GithubWorkItem` columns; `approval_round` and `decision` on `MailMessage` |
| `backend/app/models/schemas.py` | Modify | Decision schemas, resume request, continuation response, six work-item projections |
| `backend/app/services/github_dispatch_service.py` | Modify | Attempt state, dispatch rewiring, recovery, decisions, ack evidence, handoff transfer |
| `backend/app/services/github_workspace_service.py` | Modify | `release_by_owner` and owner/token-conditional contact stamping |
| `backend/app/services/github_verification_service.py` | Modify | Dedicated distinct-approver auto-merge predicate and human fallback |
| `backend/app/services/agent_mail_service.py` | Modify | Decision validation and `send_message(..., commit=True)` |
| `backend/app/api/v1/agent_mail.py` | Modify | Decision endpoint; strict session-derived identity; remove grace authority inputs |
| `backend/app/api/v1/agent_teams.py` | Modify | Strict dispatch-status auth, resume and continuation routes, release sequencing |
| `backend/app/api/v1/deps.py` | Modify | Remove `derive_member_id` after all PR1 callers use authenticated sessions |
| `backend/mcp_shim/agent_mail_server.py` | Modify | Linkage fields, approval tool, continuation tool, narrowed projections and payloads |
| `docs/deploy/pr1-approval-gate-rollout.md` | Create | Required PR0→pane restart→enforcement→PR1 deployment order |
| `backend/tests/test_sqlite_compat_migrations.py` | Modify | Additive migration compatibility for all eight columns |
| `backend/tests/agent_teams/test_github_dispatch_service.py` | Modify | Attempt, routing, retry, recovery, ack, and handoff tests |
| `backend/tests/agent_teams/test_github_dispatch_scheduler.py` | Modify | Scope-level blast-radius regression |
| `backend/tests/agent_teams/test_github_verification_service.py` | Modify | Auto-merge gate and sticky fallback tests |
| `backend/tests/agent_teams/test_github_workspace_service.py` | Modify | Conditional release/contact and WAL interleavings |
| `backend/tests/agent_teams/test_github_workspace_api.py` | Modify | Continuation, resume, release-path, and handoff authorization tests |
| `backend/tests/agent_mail/test_api.py` | Modify | Decision route and strict authenticated mail identity tests |
| `backend/tests/agent_mail/test_capability_tokens.py` | Modify | Re-author PR0 grace-mode and inbox identity tests for PR1 strictness |
| `backend/tests/agent_mail/test_mcp_shim.py` | Modify | Request linkage, approval, continuation, and projection contracts |
| `backend/tests/agent_mail/test_dispatch_status_tool.py` | Modify | Removal of `reporting_slot_id`; replacement wording and statuses |

## Task Index

| Task | Deliverable | Spec |
| --- | --- | --- |
| 1 | Schema and request-context linkage | §4.1, §4.4 |
| 2 | Attempt state and preparation primitives | §4.2, §4.2a |
| 3 | Prepared-first dispatch loop | §4.2b |
| 4 | Unavailable-owner escalation and operator resume | §4.2b.1, §4.2b.2 |
| 5 | Structured decisions and approval rounds | §4.3a, §4.3a.1 |
| 6 | Authenticated ack evidence | §3.4a, §4.3 |
| 7 | Distinct-approver auto-merge gate | §4.5 |
| 8 | Operator and leader projections | §4.6 |
| 9 | Continuation, handoff, and atomic lease ownership | §4.6a, §4.6a.1, §4.6b |
| 10 | Grace closure, compatibility cleanups, wording, rollout | §3.5, §3.5a, §4.7 |

### Normative test ownership

One collected case may satisfy more than one spec id when the assertions are inseparable; the task descriptions below state those combined assertions. No PR1 test id is intentionally omitted.

| Task | Spec §4.8 tests owned |
| --- | --- |
| 1 | 1, plus the eight-column migration compatibility case |
| 2 | 10, 10b, 37b, 37c |
| 3 | 37h, 37i, 37j, 37k, 37l, 37m, 37m-1, 37n, 37n-1, 37n-2, 37p |
| 4 | 37n-3 through 37n-11 |
| 5 | 17–26, 29–31, 31b, 31b-1, 31c, 37, 37d |
| 6 | 2–11, 11b, 11c, 19, 27, 35, 36 |
| 7 | 12–15, 28, 32–34 |
| 8 | 16, 37q |
| 9 | 11f, 11g, 37r through 37r-10, and the PR1 persistence half of 37o |
| 10 | §3.7 tests 7b/7c/7d and §4.8 test 37n-12 |

`46r` and the `pr_ready` route half of `37o` are PR2 tests. PR1 stores and preserves the data those tests consume but must not invent the PR2 route or credential helper merely to make the test executable early.

### PR1 exclusions

- Do not implement `pr_ready`, PR reconciliation, repository auth-mode selection, Git credential delivery, App-created PRs, or commit identity. Those are PR2.
- Do not add a frontend workspace-lease UI.
- Do not change `_owner_process_is_alive` to return `False` for NULL pid.
- Do not add a new approval table, attempt table, routing-method enum, or dispatch status.
- Do not make the continuation claim the first place handoff liveness becomes truthful; `accept_handoff` owns that correctness.

### Implementation branch setup

Before Task 1, verify the current commit is the commit containing this plan and that its PR0 code parent is `5d66d12`. Then create the implementation branch in g1:

```bash
git status --short --branch
git merge-base --is-ancestor 5d66d12 HEAD
git switch -c feature/distinct-approver-identity-pr1
```

If that branch already exists, or if the current commit is no longer a descendant of `5d66d12`, stop and report instead of deleting, forcing, or reusing a ref. The eventual PR targets `feature/autonomous-github-dispatch`, not `master`.

---

### Task 1: Add the schema and request-context linkage first

**Files:**
- Modify: `backend/app/models/database.py`
- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/database.py`
- Modify: `backend/mcp_shim/agent_mail_server.py`
- Modify: `backend/tests/test_sqlite_compat_migrations.py`
- Modify: `backend/tests/agent_mail/test_mcp_shim.py`

**Interfaces:**

```python
# app/models/database.py
class GithubWorkItem(Base):
    ack_approver_member_id: Mapped[int | None]
    ack_evidence_message_id: Mapped[int | None]
    dispatch_nonce: Mapped[str | None]
    ack_enforcement_epoch: Mapped[int | None]
    ack_approval_round: Mapped[int | None]
    dispatch_head_ref: Mapped[str | None]

class MailMessage(Base):
    approval_round: Mapped[int | None]
    decision: Mapped[str | None]

# mcp_shim/agent_mail_server.py
def deck_request_context(
    to_member_id: int,
    topic: str,
    why_needed: str = "",
    files_or_symbols: Optional[list[str]] = None,
    work_item_id: Optional[int] = None,
    dispatch_nonce: Optional[str] = None,
) -> dict: ...
```

- [ ] **Step 1: Write the mutation list before the tests.** Record these exact mutants in the test docstrings or adjacent table: omit one migration rung; make a new column non-nullable; omit either linkage key; include either key with a `None` value and accidentally overwrite an existing payload key.

- [ ] **Step 2: Add a red migration compatibility case.** Starting from the existing compatibility fixture, create legacy `github_work_items` and `mail_messages` tables without the new columns, run `_run_sqlite_compat_migrations`, and assert with `PRAGMA table_info` that all eight columns exist. Run the migration a second time and assert it remains idempotent. This is one collected case outside the scoped suites.

- [ ] **Step 3: Add the ORM columns.** Put all six nullable work-item columns after `brief_message_id` and before `escalation_reason`. Put `approval_round` and `decision` after `sender_actor_id` and before `recipient_member_id`. Do not add DB-level CHECK constraints.

- [ ] **Step 4: Add eight additive migration rungs.** Reuse the existing `work_item_columns` and `message_columns` snapshots. Use `INTEGER` for ids/epoch/round and `VARCHAR` for nonce/head/decision. Do not rebuild either table.

- [ ] **Step 5: Extend the mail schemas now, but not the work-item response yet.** Add:

```python
decision: Optional[Literal["approved", "rejected"]] = None
```

to `MailMessageCreate`, and add `approval_round: Optional[int] = None` plus `decision: Optional[str] = None` to `MailMessageResponse`. Task 8 owns the six work-item response fields so that the projection test arrives with all three projection edits.

- [ ] **Step 6: Write the two-case linkage test.** Parameterize `deck_request_context` over `(work_item_id, dispatch_nonce) == (None, None)` and `(41, "0123456789abcdef")`. Stub `_request`, assert existing callers still work, and for the linked case assert the posted payload equals:

```python
{
    "why_needed": "why",
    "files_or_symbols": ["app/x.py"],
    "work_item_id": 41,
    "dispatch_nonce": "0123456789abcdef",
}
```

Omit optional keys when their values are `None`; do not serialize them as JSON null.

- [ ] **Step 7: Add one schema-contract case.** Assert the six work-item ORM columns and two message ORM columns are nullable, and assert `MailMessageCreate(decision="maybe")` fails validation while `None`, `approved`, and `rejected` validate.

- [ ] **Step 8: Implement the shim linkage.** Merge the two optional values into the existing payload without changing the body, subject, recipient, or ordinary context-request behavior.

- [ ] **Step 9: Run the task tests.** From `backend/`:

```bash
venv/bin/pytest tests/test_sqlite_compat_migrations.py tests/agent_mail/test_mcp_shim.py -q -p no:warnings
venv/bin/pytest tests/agent_teams/ tests/agent_mail/ -q -p no:warnings
```

Expected scoped total: **564 passed**. Whole-suite arithmetic: **736 passed, 1 pre-existing failure**.

- [ ] **Step 10: Commit.**

```bash
git add backend/app/database.py backend/app/models/database.py backend/app/models/schemas.py backend/mcp_shim/agent_mail_server.py backend/tests/test_sqlite_compat_migrations.py backend/tests/agent_mail/test_mcp_shim.py
git commit -m "feat(dispatch): add approval linkage schema"
```

---

### Task 2: Define and persist one complete dispatch attempt

**Files:**
- Modify: `backend/app/services/github_dispatch_service.py`
- Modify: `backend/tests/agent_teams/test_github_dispatch_service.py`

**Interfaces:**

```python
_ATTEMPT_MARKERS = ("dispatch_nonce", "dispatch_head_ref")

class AttemptState(enum.Enum):
    UNPREPARED = "unprepared"
    PREPARED = "prepared"

class PartiallyPreparedAttempt(ValueError):
    def __init__(self, item_id: int, detail: str): ...

@dataclass(frozen=True)
class PreparedAttempt:
    owner_slot_id: int
    routing_method: str
    dispatch_nonce: str
    dispatch_head_ref: str
    approval_round: int

def attempt_head_ref(item: GithubWorkItem, owner_slot_id: int) -> str: ...
def attempt_state(item: GithubWorkItem) -> AttemptState: ...
def prepared_attempt_from_row(item: GithubWorkItem) -> PreparedAttempt: ...

async def prepare_attempt(
    self,
    db: AsyncSession,
    item: GithubWorkItem,
    *,
    owner_slot_id: int,
    routing_method: str,
) -> PreparedAttempt: ...
```

**Required implementation shape:**

```python
def attempt_state(item: GithubWorkItem) -> AttemptState:
    markers = [getattr(item, column) for column in _ATTEMPT_MARKERS]
    if all(marker is None for marker in markers) and item.approval_round_count == 0:
        return AttemptState.UNPREPARED
    markers_complete = (
        all(marker is not None for marker in markers)
        and item.approval_round_count >= 1
    )
    identity_complete = item.owner_slot_id is not None and bool(item.routing_method)
    if markers_complete and identity_complete:
        return AttemptState.PREPARED
    raise PartiallyPreparedAttempt(
        item.id,
        f"nonce={markers[0] is not None} head={markers[1] is not None} "
        f"round={item.approval_round_count} owner={item.owner_slot_id} "
        f"routing={item.routing_method!r}",
    )


def attempt_head_ref(item: GithubWorkItem, owner_slot_id: int) -> str:
    if item.dispatch_nonce is None:
        raise PartiallyPreparedAttempt(item.id, "head requested before nonce mint")
    return (
        f"deck/slot-{owner_slot_id}/issue-{item.issue_number}-"
        f"{item.dispatch_nonce}"
    )


async def prepare_attempt(
    self,
    db: AsyncSession,
    item: GithubWorkItem,
    *,
    owner_slot_id: int,
    routing_method: str,
) -> PreparedAttempt:
    state = attempt_state(item)
    if state is AttemptState.PREPARED:
        return prepared_attempt_from_row(item)
    item.owner_slot_id = owner_slot_id
    item.routing_method = routing_method
    item.dispatch_nonce = secrets.token_hex(8)
    item.dispatch_head_ref = attempt_head_ref(item, owner_slot_id)
    item.approval_round_count = 1
    item.updated_at = datetime.utcnow()
    await db.commit()
    return prepared_attempt_from_row(item)
```

`prepared_attempt_from_row` must validate/cast the nullable ORM fields rather than silence type checking with broad `# type: ignore` comments. Calling `attempt_state` immediately before it is the runtime proof that all five values are present.

- [ ] **Step 1: Write the mutation list.** Include: nonce-only guard; one symmetric `all`/`any` across five fields; head recomposed after handoff; shortened nonce; nested `deck/slot-X/issue-Y/deck/...` ref; no commit; mint on every call; reset clears above the deferred return; reset omits either marker; increment-then-`>` cap leaving a fictional round.

- [ ] **Step 2: Add the seven-case `attempt_state` matrix.** Collected cases:
  1. both markers NULL, round 0, stale owner/routing retained ⇒ `UNPREPARED`;
  2. all markers and identity complete, round 1 ⇒ `PREPARED`;
  3. nonce missing ⇒ `PartiallyPreparedAttempt`;
  4. head missing ⇒ raises;
  5. round 0 with markers ⇒ raises;
  6. owner NULL with complete markers ⇒ raises;
  7. routing NULL with complete markers ⇒ raises.

  Assert the exception type and no replacement nonce; do not pin its prose.

- [ ] **Step 3: Add five more cases.** One each for exact sibling head format/full 16 hex; a second-session read after `prepare_attempt` proving owner/routing/nonce/head/round are committed; idempotent reuse with zero additional `secrets.token_hex` calls; immediate reset clears both markers and the five ack fields below; deferred reset retains both markers until `promote_deferred_retries` runs after release.

- [ ] **Step 4: Implement the attempt types and helper.** The state classifier must test the empty marker/round-0 case first, then require both markers, round ≥1, owner, and routing for `PREPARED`. A torn row raises. `attempt_head_ref` reads the nonce already assigned on `item`; it does not mint.

- [ ] **Step 5: Implement `prepare_attempt`.** On an unprepared row, set owner, routing, `secrets.token_hex(8)`, the one composed head, round `1`, and `updated_at`, then commit before returning. A prepared row returns exactly the persisted values. A partial row raises.

- [ ] **Step 6: Extend `reset_for_retry`.** Below the leased-workspace early return, clear:

```python
for column in _ATTEMPT_MARKERS:
    setattr(item, column, None)
item.ack_received_at = None
item.ack_approver_member_id = None
item.ack_evidence_message_id = None
item.ack_enforcement_epoch = None
item.ack_approval_round = None
```

Keep `owner_slot_id` and `routing_method` for auditability. The existing reset already sets `approval_round_count = 0`; do not duplicate or move it.

- [ ] **Step 7: Re-author the three existing cap-trigger tests.** `test_approval_round_cap_escalates` starts at round 1, permits rounds 2 and 3, escalates on the attempted fourth, and asserts the stored counter remains 3. The two notification/rollback tests set the item at the cap before one call so they continue testing notifications rather than arithmetic. Update `fail_broadcast` to accept keyword-only `owner_may_be_active=False`.

**Correction (2026-08-12, source verification):** Keep the branch green at Task 2 by changing the existing production `record_approval_round` in place to the precondition form: if the current round is already at the cap, escalate without incrementing; otherwise increment. Task 5 replaces and deletes this method after moving the same arithmetic into `advance_approval_round`. Do not add a second temporary helper or leave both methods behind.

- [ ] **Step 8: Run the exact task slice.**

```bash
venv/bin/pytest tests/agent_teams/test_github_dispatch_service.py -q -p no:warnings
venv/bin/pytest tests/agent_teams/ tests/agent_mail/ -q -p no:warnings
```

Expected scoped total: **576 passed**.

- [ ] **Step 9: Commit.**

```bash
git add backend/app/services/github_dispatch_service.py backend/tests/agent_teams/test_github_dispatch_service.py
git commit -m "feat(dispatch): persist complete attempt identity"
```

---

### Task 3: Classify before routing and never re-route a prepared attempt

**Files:**
- Modify: `backend/app/services/github_dispatch_service.py`
- Modify: `backend/tests/agent_teams/test_github_dispatch_service.py`
- Modify: `backend/tests/agent_teams/test_github_dispatch_scheduler.py`

**Interfaces:**

`dispatch_pending(...) -> None` keeps its public signature. Its loop order becomes: scope gates → per-item attempt classification → persisted owner or fresh route → owner-dependent guards → workspace acquisition → prepare/reuse → brief → launch.

- [ ] **Step 1: Write the mutation list.** Include every §4.2b seam: `route_item` still called for prepared rows; override after guards; local owner passed to brief/launcher; classification outside a per-item catch; no owner commit before brief; preparation after brief; launch exception clears identity; delete early-exit writes for unprepared rows; second-poll mint; reset clear only in route; one torn row aborts the batch or scheduler scope.

- [ ] **Step 2: Add sixteen collected cases before implementation.** They are:
  - 37h: real dispatch brief receives a non-NULL nonce/head minted before composition;
  - 37i: a second session opened inside `_send_dispatch_brief_to_slot` can both read context and submit an owner-only report before launcher returns;
  - 37j: launch-outcome-unknown then a same-attempt re-poll reuses the nonce;
  - 37m: label change after a crash keeps owner, method, nonce, head, brief recipient, and launch target;
  - 37m-1, four parameterized early exits: no fresh route, persisted owner busy, fresh candidate ambiguous while persisted owner is not, and no workspace;
  - 37n's real deleted-owner case with the FK pragma asserted on;
  - 37n-1: torn item escalates but the next healthy item dispatches;
  - 37n-2: scheduler pass list still reaches monitor/reminder/verification when one item is torn;
  - 37k: a committed genuine retry mints a different nonce/head;
  - 37p: watcher edit and deferred promotion clear markers through `reset_for_retry`, not a route;
  - unprepared queueing still records the freshly routed owner/method;
  - a partial prepared row escalates `plan_blocked` while retaining its lease and markers;
  - a known/unknown launch failure retains the prepared identity according to the existing launch semantics.

- [ ] **Step 3: Put `slots_by_id` above the item loop.** It must index only the scheduler-provided `preset_slots`; never `db.get` a prepared owner from another preset.

- [ ] **Step 4: Preserve scope gates first.** Repository cap and low-memory checks remain before attempt classification and keep their existing writes and commits.

- [ ] **Step 5: Add a per-item classification catch.** Catch `PartiallyPreparedAttempt` around the classification call itself, call `escalate(..., "plan_blocked", exc.detail)`, commit, keep the lease and markers, then continue to the next item. Do not rely on the later `except ValueError`; it begins below this call.

- [ ] **Step 6: Select the authoritative owner.** For `PREPARED`, use `prepared_attempt_from_row` and never call `route_item`. For `UNPREPARED`, call `route_item` exactly as today and keep existing plan-blocked behavior when it returns no owner.

- [ ] **Step 7: Run owner-dependent guards against that owner.** Busy, ambiguity, and workspace checks keep their current content and order. Their early-exit owner/method writes stay because they are the first durable routing record for an unprepared queued item and harmless no-ops for a prepared one.

- [ ] **Step 8: Prepare before delivery.** Call `prepare_attempt` after workspace acquisition and before `_dispatch_brief`. From that point, pass only `attempt.owner_slot_id`, `attempt.routing_method`, and the persisted item fields. The brief spy and launcher spy must observe the same slot.

- [ ] **Step 9: Delete the redundant success-path owner writes.** Remove the two assignments after launcher returns. Keep `launch_id`, launch status, `dispatched_at`, pane-pid capture, pending reason, and final commit unchanged.

- [ ] **Step 10: Run the mutant checks and scoped suite.** At minimum, temporarily restore a post-guard owner override and prove 37m-1 fails; move preparation below brief and prove 37h fails; remove the per-item catch and prove both 37n-1 and 37n-2 fail.

```bash
venv/bin/pytest tests/agent_teams/test_github_dispatch_service.py tests/agent_teams/test_github_dispatch_scheduler.py -q -p no:warnings
venv/bin/pytest tests/agent_teams/ tests/agent_mail/ -q -p no:warnings
```

Expected scoped total: **592 passed**.

- [ ] **Step 11: Commit.**

```bash
git add backend/app/services/github_dispatch_service.py backend/tests/agent_teams/test_github_dispatch_service.py backend/tests/agent_teams/test_github_dispatch_scheduler.py
git commit -m "fix(dispatch): keep prepared routing authoritative"
```

---
### Task 4: Escalate unavailable prepared owners and resume only by operator action

**Files:**
- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/services/github_dispatch_service.py`
- Modify: `backend/app/api/v1/agent_teams.py`
- Modify: `backend/tests/agent_teams/test_github_dispatch_service.py`
- Modify: `backend/tests/agent_teams/test_github_workspace_api.py`

**Interfaces:**

```python
class GithubWorkItemResumeAttemptRequest(BaseModel):
    resume: Literal[True]
    reassign_to_slot_id: Optional[int] = None

async def _escalate_prepared_owner_unavailable(
    self,
    db: AsyncSession,
    item: GithubWorkItem,
    owner_slot: AgentTeamSlot | None,
) -> None: ...

async def resume_prepared_attempt(
    self,
    db: AsyncSession,
    item: GithubWorkItem,
    scope: TeamGithubScope,
    preset_slots: list[AgentTeamSlot],
    *,
    reassign_to_slot_id: int | None,
) -> None: ...

POST /api/v1/agent-teams/presets/{preset_id}/work-items/{item_id}/resume-attempt
```

- [ ] **Step 1: Write the mutation list.** Cover: disabled owner launched; owner resolved with `db.get` outside the preset; one generic note for disabled/missing; lease released; escalation not committed; re-enable alone resumes; resume calls reset/release/reacquire; cause tests only `enabled`; nonexistent/cross-preset target accepted; agent session token accepted as operator auth; unknown previous-owner liveness accepted for reassignment; `_PR_OPENED_RECOVERABLE_ESCALATIONS` widened.

- [ ] **Step 2: Add ten collected cases.** One each for: disabled-owner escalation; owner-not-in-preset escalation via a real handoff shape; persistence after broadcast failure; reminder count with no resolvable member; note carries explicit do-not-retry and exact head; late PR does not recover this reason; resume preserves nonce/head/round/verified SHA/token and performs zero `reset_workspace`; resume validation matrix; operator-auth matrix including a valid agent session token; previous-owner liveness matrix distinguishing same-owner from reassignment.

- [ ] **Step 3: Implement `_escalate_prepared_owner_unavailable`.** Use separate notes for disabled and not-in-preset. Both notes name owner, head, round, no-retry warning, and the resume route. Call `escalate(..., "prepared_owner_unavailable", note)` then commit because `escalate` does not commit. Do not release the workspace or clear any attempt/approval field.

- [ ] **Step 4: Integrate the owner-availability check in Task 3's prepared branch.** `owner_slot = slots_by_id.get(attempt.owner_slot_id)`. Missing or disabled calls the helper and continues before busy/ambiguity/workspace/brief/launch.

- [ ] **Step 5: Add the request schema and route behind `require_operator`.** Load preset, item, scope, and all preset slots. Require the item's scope to use the route's preset. Refuse anything except `dispatch_status == "escalated"` and `escalation_reason == "prepared_owner_unavailable"` with `409 not_a_resumable_attempt`.

- [ ] **Step 6: Define one `effective_owner`.** It is `reassign_to_slot_id` when supplied, otherwise the stored owner. It must exist, be enabled, and belong to `scope.preset_id`. A supplied invalid target returns `409 invalid_resume_target`; a same-owner unresolved cause returns `409 owner_still_unavailable`.

- [ ] **Step 7: Check previous-owner liveness from evidence, not pid inference.** Resolve the leased workspace's `(leased_owner_pid, leased_owner_proc_start)` through `AgentPaneBinding` to a slot. If it resolves to a different live slot, refuse `409 previous_owner_still_alive`. For reassignment, NULL or unresolvable evidence refuses `409 previous_owner_liveness_unknown`. For same-owner resume, unknown evidence may proceed.

- [ ] **Step 8: Apply only the resume transition.** Set `dispatch_status="pending"`, clear `escalation_reason` and `pending_reason`, and, on reassignment, set owner and `routing_method="operator_resume"`. Commit once. Do not touch the workspace; do not call `reset_for_retry`, `release`, `acquire`, or `reset_workspace`.

- [ ] **Step 9: Prove the existing acquisition is reused.** After resume, call `dispatch_pending` in the test and assert `acquire` takes its existing-lease early return, returns the byte-identical token, does not reset the worktree, and the full issue body reaches the brief. A pre-pass inside `dispatch_pending` must fail this test by using missing prefetched issue details.

- [ ] **Step 10: Run the task slice.**

```bash
venv/bin/pytest tests/agent_teams/test_github_dispatch_service.py tests/agent_teams/test_github_workspace_api.py -q -p no:warnings
venv/bin/pytest tests/agent_teams/ tests/agent_mail/ -q -p no:warnings
```

Expected scoped total: **602 passed**.

- [ ] **Step 11: Commit.**

```bash
git add backend/app/models/schemas.py backend/app/services/github_dispatch_service.py backend/app/api/v1/agent_teams.py backend/tests/agent_teams/test_github_dispatch_service.py backend/tests/agent_teams/test_github_workspace_api.py
git commit -m "feat(dispatch): resume prepared attempts safely"
```

---

### Task 5: Record explicit decisions and advance approval rounds atomically

**Files:**
- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/services/agent_mail_service.py`
- Modify: `backend/app/services/github_dispatch_service.py`
- Modify: `backend/app/api/v1/agent_mail.py`
- Modify: `backend/mcp_shim/agent_mail_server.py`
- Modify: `backend/tests/agent_mail/test_api.py`
- Modify: `backend/tests/agent_mail/test_mcp_shim.py`
- Modify: `backend/tests/agent_teams/test_github_dispatch_service.py`

**Interfaces:**

```python
class MailDecisionRequest(BaseModel):
    work_item_id: int
    dispatch_nonce: str
    decision: Literal["approved", "rejected"]
    reason: str = Field(min_length=1)

async def AgentMailService.send_message(
    self,
    db: AsyncSession,
    request: MailMessageCreate,
    *,
    auto_nudge: bool = True,
    bypass_nudge_cooldown: bool = False,
    sender_actor_id: Optional[int] = None,
    authenticated_sender_member_id: Optional[int] = None,
    commit: bool = True,
) -> MailMessageResponse: ...

async def GithubDispatchService.advance_approval_round(
    self,
    db: AsyncSession,
    item: GithubWorkItem,
    scope: TeamGithubScope,
    *,
    decision_message: MailMessageCreate,
) -> None: ...

POST /api/v1/agent-mail/decisions

def deck_approve_work_item(
    work_item_id: int,
    dispatch_nonce: str,
    decision: str,
    reason: str,
) -> dict: ...
```

- [ ] **Step 1: Write the mutation list.** Start with the exact real-data mutants: any leader answer approves rows 82/92; prose classifier rejects row 40; any authenticated member may set decision; shim-only guard; tokenless decision accepted in grace; server trusts thread id; request match ignores owner/nonce/round; rejection does not advance; branch A clears nonce; branch B calls committing mail write before escalation; branch B clears evidence or increments past cap; notification failure rolls back committed state; already-escalated item advances.

- [ ] **Step 2: Add the three real-prose cases first.** Leader answers with row-82 prose and `decision=None` ⇒ `409 no_decision`; row-92 prose and `decision=None` ⇒ same; row-40 prose with `decision="approved"` ⇒ accepted even though its body contains “no”. These tests must fail against prose parsing and any-answer approval.

- [ ] **Step 3: Add four decision-write guard cases.** Parameterize non-answer decision, non-leader member, tokenless grace-mode caller, and invalid decision. Assert no decision row is written, not only the status. In the non-answer case, post an ordinary `deck_reply` control and assert it still succeeds with `decision IS NULL` and does not advance the round (test 25).

- [ ] **Step 4: Add three thread-resolution cases.** No current-round request ⇒ `404`; duplicate current-owner requests in one round ⇒ `409` naming both ids; requests across two rounds and two owners resolve exactly the current owner's current-round request. The last case performs the full 29/30 flow: rejection opens round 2, the owner sends only a new `deck_request_context`, the server stamps round 2, and the decision resolver ignores round 1 and the previous owner.

- [ ] **Step 5: Add four transition cases.** Below-cap rejection clears all five ack fields plus `last_nudge_at`, increments once, keeps nonce/head, and commits the answer in the same transaction; branch A calls `escalate` zero times; at-cap rejection commits answer plus escalation atomically even when broadcast fails; an already-escalated item returns `409 item_escalated` without writing or incrementing.

- [ ] **Step 6: Validate decisions in `send_message`, not only the route or shim.** A non-NULL decision requires `kind="answer"`, `authenticated_sender_member_id` equal to the server-derived `request.sender_member_id`, a context request linked to a current work item/nonce/round, and the designated leader member. The ordinary `/messages` route passes `session.member_id` only when a capability token resolved; the decisions route passes its required session member; internal callers and grace-mode tokenless callers pass `None`. Keep ordinary `deck_reply` behavior with `decision=None`.

- [ ] **Step 7: Add `commit` to `send_message`.** With `commit=True`, preserve current commit/refresh/nudge behavior byte-for-byte. With `False`, add and flush the message/receipts, update the root, but do not commit, refresh, or auto-nudge. Return or expose the pending `MailMessage` in a shape `advance_approval_round` can commit atomically; do not fake a response that requires a refresh.

**Correction (2026-08-12, type and authority consistency):** The existing signature has no way to distinguish a server-derived member from a caller-supplied member, so `authenticated_sender_member_id` is required in addition to the spec's `commit` flag. If returning `MailMessageResponse` with `commit=False` cannot be done without reading an uncommitted response graph or triggering auto-nudge, introduce a private `_create_message_row(...) -> tuple[MailMessage, set[int]]` used by both `send_message` and `advance_approval_round`. Keep the public return type honest; branch B may call the private row builder. This is preferable to a fabricated response or a split commit.

- [ ] **Step 8: Derive approval rounds server-side for both message shapes.** When an authenticated owner posts a linked `context_request`, load the item from `payload.work_item_id`, require its nonce, current owner member, and open round to match, then stamp `payload["approval_round"] = item.approval_round_count`; reject a conflicting caller-supplied round with `403 approval_round_mismatch` and no row. The same honest value is accepted (test 37d). Round 0 refuses because no round is open (37c). When a decision answer is built, set `MailMessage.approval_round` from that same current item round. No request schema exposes an authoritative round field.

- [ ] **Step 9: Implement the server-side decision route.** Depend on `require_mail_session`, derive the member from the session, load item/scope/current owner/leader, and query context requests by JSON `work_item_id`, `dispatch_nonce`, server-stored current round, owner sender, and leader recipient. Never accept a client-provided thread id or approval round.

- [ ] **Step 10: Implement `advance_approval_round` with two branches.** Refuse already-escalated first. Below cap, clear five ack fields + nudge, increment, and let one mail commit persist decision and item. At cap, keep counter and ack fields, build the answer without commit, call `_apply_escalation`, commit decision+escalation once, then send the escalation notification post-commit in a swallowed/logged best-effort block. Delete `record_approval_round` only after all callers move.

- [ ] **Step 11: Add the MCP tool.** It posts to `/decisions`, does not accept a thread id or round, validates the decision string locally only for helpful error output, and documents that rejection opens the next round with no second call.

- [ ] **Step 12: Run exact mutants.** In particular, temporarily make branch B call ordinary `send_message` then `escalate` without another commit; the fresh-session atomicity test must read `dispatched` and fail. Temporarily accept any answer; rows 82 and 92 must fail.

```bash
venv/bin/pytest tests/agent_mail/test_api.py tests/agent_mail/test_mcp_shim.py tests/agent_teams/test_github_dispatch_service.py -q -p no:warnings
venv/bin/pytest tests/agent_teams/ tests/agent_mail/ -q -p no:warnings
```

Expected scoped total: **616 passed**.

- [ ] **Step 13: Commit.**

```bash
git add backend/app/models/schemas.py backend/app/services/agent_mail_service.py backend/app/services/github_dispatch_service.py backend/app/api/v1/agent_mail.py backend/mcp_shim/agent_mail_server.py backend/tests/agent_mail/test_api.py backend/tests/agent_mail/test_mcp_shim.py backend/tests/agent_teams/test_github_dispatch_service.py
git commit -m "feat(agent-mail): record explicit approval decisions"
```

---

### Task 6: Attribute ack evidence to the designated leader and current round

**Files:**
- Modify: `backend/app/services/github_dispatch_service.py`
- Modify: `backend/app/api/v1/agent_teams.py`
- Modify: `backend/tests/agent_teams/test_github_dispatch_service.py`
- Modify: `backend/tests/agent_teams/test_github_workspace_api.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class AckEvidence:
    ok: bool
    reason: str
    approver_member_id: int | None = None
    evidence_message_id: int | None = None
    approval_round: int | None = None

async def _ack_evidence(
    self,
    db: AsyncSession,
    item: GithubWorkItem,
    preset_slots: list[AgentTeamSlot],
) -> AckEvidence: ...

async def record_ack_received(
    self,
    db: AsyncSession,
    item: GithubWorkItem,
    scope: TeamGithubScope,
) -> AckEvidence: ...
```

- [ ] **Step 1: Write the mutation list.** Include owner-is-leader accepted; any non-owner or slotless member accepted; missing/unregistered leader accepted; request-status evidence; nonce/round ignored; missing payload accepted; rejected/no-decision answer accepted; answer request id stored instead of answer id; grace mode writes evidence; reset/handoff leaves any one of five fields or `last_nudge_at`; `_ack_satisfied` remains true after handoff.

- [ ] **Step 2: Add an eleven-case evidence matrix.** Collected cases: valid approved leader answer; self-ack; non-leader slot member; slotless member; no linkage including NULL/missing payload round; stale nonce; stale round; no enabled/registered leader; no owner member; leader rejection; leader answer with no decision. Assert exact `AckEvidence.reason`, and assert raw-SQL ack columns remain NULL on every refusal. The stale-round and NULL-round assertions are tests 35 and 36, not incidental setup.

- [ ] **Step 3: Add four lifecycle cases.** Grace mode refuses `tokens_not_enforced`, writes nothing, then succeeds after enforcement flips; immediate and deferred retry clear at the correct time; accepted handoff clears all five ack fields and nudge but keeps nonce/head/round/dispatched time; monitor after handoff treats ack as unsatisfied and follows the nudge/timeout path.

- [ ] **Step 4: Implement `_ack_evidence` in the specified order.** First refuse when capability enforcement is off. Resolve enabled leader slot, leader member, and owner member with existing helpers. Refuse self-ack before querying mail. Query context requests by owner→leader plus JSON work-item id, then distinguish no linkage, stale nonce, and stale round in that order. Query leader-authored answers in the matching threads and use `decision`, never `request_status` or prose.

- [ ] **Step 5: Record only accepted evidence.** Set `ack_received_at`, approver member id, answer message id, epoch `1`, approval round, clear nudge, update timestamp, commit. On refusal, commit nothing and return the evidence so the route can return `409` with its reason.

- [ ] **Step 6: Update the `ack_received` branch.** Pass `scope`, convert refused evidence to `HTTPException(409, detail=evidence.reason)`, and preserve the existing successful response shape.

- [ ] **Step 7: Complete lifecycle clears.** `reset_for_retry` already gained them in Task 2. Extend `accept_handoff` for now to clear all five fields + nudge while keeping nonce/head/round/dispatched time. Task 9 adds the liveness transfer without changing this write set.

- [ ] **Step 8: Run the mutant checks.** Delete only `ack_received_at` from the handoff clear and prove the monitor consequence fails. Replace decision with `request_status` and prove self-ack/real-prose cases fail.

```bash
venv/bin/pytest tests/agent_teams/test_github_dispatch_service.py tests/agent_teams/test_github_workspace_api.py -q -p no:warnings
venv/bin/pytest tests/agent_teams/ tests/agent_mail/ -q -p no:warnings
```

Expected scoped total: **631 passed**.

- [ ] **Step 9: Commit.**

```bash
git add backend/app/services/github_dispatch_service.py backend/app/api/v1/agent_teams.py backend/tests/agent_teams/test_github_dispatch_service.py backend/tests/agent_teams/test_github_workspace_api.py
git commit -m "feat(dispatch): attribute leader approval evidence"
```

---

### Task 7: Gate auto-merge on enforced, current-round, distinct approval

**Files:**
- Modify: `backend/app/services/github_verification_service.py`
- Modify: `backend/tests/agent_teams/test_github_verification_service.py`

**Interfaces:**

```python
async def _approval_gate_reason(
    self,
    db: AsyncSession,
    scope: TeamGithubScope,
    item: GithubWorkItem,
) -> str | None: ...
```

`None` means the approval gate passes. A string is an operator-facing refusal reason and must be routed through the existing human-merge fallback with a note beginning `"Auto-merge blocked"`.

- [ ] **Step 1: Write the mutation list.** Include: gate omitted; gate implemented via `_ack_satisfied`; settings check omitted; epoch NULL/0 accepted; stale/missing round accepted; any leader-looking member accepted; owner==leader accepted; approver member no longer bound to enabled leader slot accepted; fallback prefix changed; valid approval refused.

- [ ] **Step 2: Add a five-case refusal matrix.** Parameterize: no approval; capability enforcement off; epoch NULL/0; ack round differs from current round; approver member is owner or is not the current designated leader. Each item has a PR, green current head, auto policy, and no other blocker so the approval predicate is the only reason merge does not run.

- [ ] **Step 3: Add two controls.** A valid current-round approval by the designated leader reaches `merge_pull`; a refusal calls `_fallback_to_human_merge`, produces `ready_for_review`, leaves `escalation_reason=None`, and the note starts with `Auto-merge blocked` so a second poll is sticky and makes zero merge attempts.

- [ ] **Step 4: Implement a dedicated predicate.** It must check, in this order: `mail_capability_tokens_required`; `ack_enforcement_epoch == 1`; `ack_approval_round == approval_round_count`; enabled leader slot and registered member; `ack_approver_member_id == leader_member.id`; owner member exists and differs from approver. Do not query or parse the mail row again.

- [ ] **Step 5: Insert it in `_process_review_item`.** Keep design/human policy and existing sticky human-note return first. Run the approval gate before budget/transient/head/green/merge operations. A refusal calls `_fallback_to_human_merge` with a note beginning `Auto-merge blocked: distinct current-round leader approval is required` plus the specific reason.

- [ ] **Step 6: Prove `_ack_satisfied` is not used.** Temporarily replace the predicate call with `_ack_satisfied(item)`; the no-approval item with a PR must attempt a merge and fail the test.

```bash
venv/bin/pytest tests/agent_teams/test_github_verification_service.py -q -p no:warnings
venv/bin/pytest tests/agent_teams/ tests/agent_mail/ -q -p no:warnings
```

Expected scoped total: **638 passed**.

- [ ] **Step 7: Commit.**

```bash
git add backend/app/services/github_verification_service.py backend/tests/agent_teams/test_github_verification_service.py
git commit -m "feat(dispatch): require distinct leader approval for merge"
```

---

### Task 8: Expose the record through every required projection

**Files:**
- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/api/v1/agent_teams.py`
- Modify: `backend/mcp_shim/agent_mail_server.py`
- Modify: `backend/tests/agent_mail/test_mcp_shim.py`
- Modify: `backend/tests/agent_teams/test_github_workspace_api.py`

**Interfaces:**

`GithubWorkItemResponse` and `_work_item_response` gain all six fields. `deck_list_work_items` gains only `ack_approval_round`, `ack_enforcement_epoch`, and `dispatch_head_ref`. `MailMessageResponse.decision` already reaches `deck_check_inbox` through its splatted response and needs no additional shim projection.

- [ ] **Step 1: Write the mutation list.** Omit each projection in turn; add only five work-item fields; use `extra="allow"`; pass the wrong value through the shim; add all six to the leader projection; change `deck_check_inbox` even though it already splats.

- [ ] **Step 2: Add four collected cases.** Assert: the response schema has all six and no extra-allow config; `_work_item_response` supplies all six explicit values; the real `deck_list_work_items` receives exactly the original five plus the specified three and preserves values; a mail decision reaches `deck_check_inbox` without a new decision-specific shim branch.

- [ ] **Step 3: Add all six fields to `GithubWorkItemResponse`.** Keep them optional for pre-upgrade rows.

- [ ] **Step 4: Add all six explicit keywords to `_work_item_response`.** Do not replace the serializer with `**item.__dict__` or another splat.

- [ ] **Step 5: Extend only the leader projection's three fields.** Keep ids and nonce operator-only. Preserve the exact five existing keys and append the three diagnostic values.

- [ ] **Step 6: Run projection mutants.** Removing any one layer must fail a different assertion. A test that inspects only source text is insufficient; drive the real projection and assert the received value.

```bash
venv/bin/pytest tests/agent_mail/test_mcp_shim.py tests/agent_teams/test_github_workspace_api.py -q -p no:warnings
venv/bin/pytest tests/agent_teams/ tests/agent_mail/ -q -p no:warnings
```

Expected scoped total: **642 passed**.

- [ ] **Step 7: Commit.**

```bash
git add backend/app/models/schemas.py backend/app/api/v1/agent_teams.py backend/mcp_shim/agent_mail_server.py backend/tests/agent_mail/test_mcp_shim.py backend/tests/agent_teams/test_github_workspace_api.py
git commit -m "feat(dispatch): expose approval and attempt evidence"
```

---

### Task 9: Transfer continuation authority and bind lease writes atomically

**Files:**
- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/services/github_dispatch_service.py`
- Modify: `backend/app/services/github_workspace_service.py`
- Modify: `backend/app/api/v1/agent_teams.py`
- Modify: `backend/mcp_shim/agent_mail_server.py`
- Modify: `backend/tests/agent_teams/test_github_dispatch_service.py`
- Modify: `backend/tests/agent_teams/test_github_workspace_service.py`
- Modify: `backend/tests/agent_teams/test_github_workspace_api.py`
- Modify: `backend/tests/agent_mail/test_mcp_shim.py`

**Interfaces:**

```python
class GithubWorkItemContinuationResponse(BaseModel):
    work_item_id: int
    issue_number: int
    issue_title: str
    issue_url: str
    issue_type: str
    repo_owner: str
    repo_name: str
    dispatch_status: str
    approval_round_count: int
    dispatch_nonce: Optional[str] = None
    dispatch_head_ref: Optional[str] = None
    workspace_path: Optional[str] = None
    lease_token: Optional[str] = None
    leader_member_id: Optional[int] = None
    status_note: Optional[str] = None

async def GithubWorkspaceService.release_by_owner(
    self,
    db: AsyncSession,
    item_id: int,
    *,
    lease_token: str,
    workspace_id: int,
    scope_id: int,
    owner_slot_id: int,
) -> bool: ...

async def GithubWorkspaceService.touch_owner_contact(
    self,
    db: AsyncSession,
    item_id: int,
    *,
    lease_token: str | None,
    owner_slot_id: int,
) -> None: ...

async def GithubDispatchService.initiate_handoff(
    self,
    db: AsyncSession,
    item: GithubWorkItem,
    scope: TeamGithubScope,
    *,
    initiating_slot_id: int,
    target_slot_id: int,
) -> None: ...

async def GithubDispatchService.accept_handoff(
    self,
    db: AsyncSession,
    item: GithubWorkItem,
    accepting_slot_id: int,
    *,
    accepting_pane_pid: int,
    accepting_pane_proc_start: str,
) -> None: ...

POST /api/v1/agent-teams/github-work-items/{item_id}/claim-continuation

def deck_get_work_item_context(work_item_id: int) -> dict: ...
```

**Required release-write shape:**

```python
now = datetime.utcnow()
owner_still_current = exists().where(
    GithubWorkItem.id == item_id,
    GithubWorkItem.owner_slot_id == owner_slot_id,
    GithubWorkItem.dispatch_status.in_(_RELEASABLE_STATUSES),
)
result = await db.execute(
    update(GithubWorkspace)
    .where(
        GithubWorkspace.id == workspace_id,
        GithubWorkspace.scope_id == scope_id,
        GithubWorkspace.leased_item_id == item_id,
        GithubWorkspace.lease_token == lease_token,
        owner_still_current,
    )
    .values(
        leased_item_id=None,
        released_at=now,
        lease_token=None,
        leased_owner_pid=None,
        leased_owner_proc_start=None,
        lease_last_owner_contact_at=None,
        lease_release_reminded_at=None,
        updated_at=now,
    )
    .execution_options(synchronize_session=False)
)
if result.rowcount != 1:
    return False
await db.commit()
return True
```

The contact write uses the same ordinary token equality and owner `EXISTS`, but updates only `lease_last_owner_contact_at` and `updated_at`; zero rows is a silent no-op. Do not factor the two writes into a helper that can switch to null-safe equality.

- [ ] **Step 1: Write the mutation list.** Include: claim as GET/query identity; claimed slot authorization; token omitted; token logged; target-column auth; token rotated; handoff owner check missing; target validated by FK only; cross-preset target; liveness transfer deferred to claim; pid/body-derived evidence; two commits; release owner check only before await; conditional write missing row/token/owner/status; write before blocker; flat zero-row 200 or 409; cached diagnosis; path-A interleaving placed at release blocker; contact read-then-write; contact owner-only or token-only; NULL pid reinterpreted.

- [ ] **Step 2: Add the first seven continuation/handoff cases.** Claim succeeds for the authenticated owner and returns persisted head/nonce/round/path/token/leader with `Cache-Control: no-store`, while the token is absent from URL, logs, exceptions, and `status_note` (37r-7); wrong slot refuses; enforcement-off refuses; acceptance alone transfers B's pid/proc-start/contact timestamp in the same transaction as owner and preserves nonce/head/round/dispatched time (11f/37o); claim refreshes the timestamp without being required for correctness and the real tool is B's source of the head (11g); the A-token/B-owner split-authority sequence remains held until B receives the real token; B's delivered-token release is the positive control and A's retained token grants no contact or release authority. The liveness-transfer case first pins `_RECLAIMABLE_STATUSES` by equality and proves dispatched is unselected while an otherwise-identical escalated terminal item is reclaimable (37r-4a). The delivery case also proves the existing reminder is gated off for dispatched work and can report one reminder while sending zero messages (37r-6).

- [ ] **Step 3: Add three parameterized handoff-initiation cases.** Non-owner (including leader) ⇒ `403 not_item_owner`, different-preset target ⇒ `409`, current owner to sibling enabled same-preset target ⇒ accepted. Assert the target column on every result.

- [ ] **Step 4: Add two FK-independent target cases.** Run nonexistent target with foreign keys ON and OFF; both return application-level `409` and leave the target NULL.

- [ ] **Step 5: Add two release-CAS interleavings.** Case (i): A passes owner check, B takes ownership while A is suspended inside `release_blocker`, A's write affects zero and B's lease remains. Case (ii): acquisition changes under the same owner, old token affects zero and replacement remains. Assert branch arrival and that the conditional write ran after the blocker.

- [ ] **Step 6: Add four release-outcome cases.** A1 duplicate with no workspace and same owner ⇒ 200 and no write attempted; A2 handoff interleaved **inside `get_leased_workspace`** so no workspace is captured and fresh owner differs ⇒ 403, proving the lookup branch was reached; C captured workspace then staled/released during blocker ⇒ 409; direct non-owner ⇒ 403 before lookup/write. Branch-arrival and non-arrival assertions are mandatory because the same response code can come from different mechanisms.

- [ ] **Step 7: Add two contact-stamp interleavings.** Handoff between route admission and stamp ⇒ zero rows; acquisition replacement under same owner ⇒ zero rows. Positive owner+token control stamps once. Use a file-backed WAL DB for the fresh-read-then-write mutant and prove that mutant fails.

- [ ] **Step 8: Implement the continuation response and route as POST.** Depend on `mail_session`, require enforcement true, derive slot with `require_session_slot`, and compare it to stored `owner_slot_id`. Return only persisted row/scope/workspace values. Add `Cache-Control: no-store`. The route logs no token and places none in error detail or `status_note`.

- [ ] **Step 9: Refresh liveness in the claim transaction.** When a workspace is leased, require the authenticated session's bound pane pid/proc-start, set those two workspace fields plus `lease_last_owner_contact_at`, and commit before returning. This is an idempotent refresh of evidence `accept_handoff` already made truthful, not the first establishing write. With no leased workspace, return `workspace_path=None` and `lease_token=None` without inventing liveness evidence.

- [ ] **Step 10: Implement the shim tool.** It takes only `work_item_id`, ensures registration, POSTs to the claim route, and returns the context. It sends no `reporting_slot_id`. The 11g test must obtain the head from this tool and compare it to the prepared head; it must not reuse a local fixture variable as the agent's knowledge.

- [ ] **Step 11: Harden handoff initiation.** The current authenticated owner must initiate. Resolve target in application code and require enabled same-preset membership. Do not rely on SQLite FK behavior. Keep `403` for caller authority and `409` for target conflict.

- [ ] **Step 12: Transfer liveness inside `accept_handoff`.** The route supplies `session.bound_pane_pid` and `bound_pane_proc_start`, never body values, and refuses `403 bind_unverifiable` if either is absent. If a workspace is leased, set B's pid, proc start, and contact timestamp in the same transaction as owner/routing/ack clears. If no workspace is leased, update only the item. Commit once. Do not clear pid fields and do not make claim-continuation the establishing write.

- [ ] **Step 13: Centralize `_RELEASABLE_STATUSES` without a circular import.** Move the tuple to `github_workspace_service.py`, import it into `github_dispatch_service.py` and `agent_teams.py`, and keep the exact value `("merged", "completed", "escalated", "failed")`. This gives the route, reminders, and SQL predicate one source.

- [ ] **Step 14: Implement `release_by_owner` as one conditional update.** After `release_blocker`, predicate on workspace PK, scope id, item id, ordinary token equality, and an `EXISTS` over current owner and `_RELEASABLE_STATUSES`. Clear the same seven lease fields as `release` at one timestamp. Use `synchronize_session=False`. Return whether exactly one row changed; do not commit on zero.

- [ ] **Step 15: Implement the three route outcomes.** Path A has no workspace and no write: fresh scalar owner read, 200 if still owner, otherwise 403. Path B is one affected row: 200. Path C is zero rows after a captured workspace: fresh scalar reads owner and current lease; no lease + still owner is idempotent 200, otherwise 409 `lease_changed`. `db.get` and the route's cached item are prohibited for both diagnoses.

- [ ] **Step 16: Replace contact stamping with one conditional update.** Predicate on item id, ordinary token equality, and current-owner `EXISTS`; zero rows is a silent no-op. Do not offer a read-then-write alternative. A shared helper, if used, has no null-safe mode.

- [ ] **Step 17: Preserve preliminary diagnostics.** Keep token-required, legal-status, and obvious owner checks before expensive subprocesses. Treat them as error quality, not authorization proof. The CAS remains the control.

- [ ] **Step 18: Run the exact interleaving slice and mutant checks.** In particular, use the real route for path A2 and suspend inside `get_leased_workspace`; assert the preliminary owner check ran, the lookup was entered, `release_blocker` and `release_by_owner` were not. Run the cached-owner mutant and require A2 to become 200 and fail.

```bash
venv/bin/pytest tests/agent_teams/test_github_workspace_service.py tests/agent_teams/test_github_workspace_api.py tests/agent_teams/test_github_dispatch_service.py tests/agent_mail/test_mcp_shim.py -q -p no:warnings
venv/bin/pytest tests/agent_teams/ tests/agent_mail/ -q -p no:warnings
venv/bin/pytest tests/ -q -p no:warnings
```

Expected scoped total: **662 passed**. Expected full suite: **834 passed, 1 pre-existing failure**.

- [ ] **Step 19: Perform the explicit SQL review.** Confirm both conditional writes use ordinary `=` and contain no `IS`, `IS NOT DISTINCT FROM`, both-NULL `OR`, or null-safe helper option. Record this as a review result; do not invent an unreachable NULL-token test.

- [ ] **Step 20: Commit.**

```bash
git add backend/app/models/schemas.py backend/app/services/github_dispatch_service.py backend/app/services/github_workspace_service.py backend/app/api/v1/agent_teams.py backend/mcp_shim/agent_mail_server.py backend/tests/agent_teams/test_github_dispatch_service.py backend/tests/agent_teams/test_github_workspace_service.py backend/tests/agent_teams/test_github_workspace_api.py backend/tests/agent_mail/test_mcp_shim.py
git commit -m "fix(dispatch): bind handoff and lease actions to owner"
```

---

### Task 10: Close grace-mode authority, retire legacy inputs, and document rollout

**Files:**
- Modify: `backend/app/api/v1/deps.py`
- Modify: `backend/app/api/v1/agent_mail.py`
- Modify: `backend/app/api/v1/agent_teams.py`
- Modify: `backend/app/services/github_dispatch_service.py`
- Modify: `backend/mcp_shim/agent_mail_server.py`
- Create: `docs/deploy/pr1-approval-gate-rollout.md`
- Modify: `backend/tests/agent_mail/test_api.py`
- Modify: `backend/tests/agent_mail/test_capability_tokens.py`
- Modify: `backend/tests/agent_mail/test_dispatch_status_tool.py`
- Modify: `backend/tests/agent_mail/test_mcp_shim.py`
- Modify: `backend/tests/agent_teams/test_github_workspace_api.py`

**Interfaces:**

- `/dispatch-status` keeps `DispatchStatusReport.reporting_slot_id` for wire compatibility, but it is corroboration only and disappears from the shim payload.
- The four Agent Mail agent-write/read routes depend on `require_mail_session`; `derive_member_id` is deleted.
- `revision_requested` remains an accepted input string but always returns `409 use_deck_approve_work_item`.

- [ ] **Step 1: Write the mutation list.** Include: per-status grace allowlist; strict continuation only; `triaging` still writes in grace; `_authorize_dispatch_report` session-None fallthrough; unknown/rule fallthrough; `revision_requested` still advances; shim still sends `reporting_slot_id`; inbox member id remains an authority parameter; one mail route still uses `derive_member_id`; wording still says prose acknowledgment.

- [ ] **Step 2: Add nine parameterized whole-route grace cases.** With `mail_capability_tokens_required=False`, drive `triaging`, `revision_requested`, `handoff_initiated`, `handoff_accepted`, `blocked`, `ack_received`, `pr_opened`, `in_progress`, and `workspace_released`. Every case returns `409 tokens_not_enforced`. Snapshot the entire work-item and workspace rows before/after and assert byte-equivalent field values.

- [ ] **Step 3: Add eight more cases.** One exhaustive 7b/7c/7d rule-table case that loops every branch, asserts the expected authorized role and refusal, and fails if either auth fallthrough remains; one `revision_requested` replacement refusal; four parameterized Agent Mail routes proving no member-identity parameter can override the session; one shim payload assertion proving no `reporting_slot_id` or inbox `member_id`; one wording assertion covering owner brief, leader brief/nudge, and tool docstring.

- [ ] **Step 4: Close grace mode before authorization.** At the top of `/dispatch-status`, after loading the item but before any branch mutation, return `409 tokens_not_enforced` while the flag is false. With enforcement true, a missing/invalid token is already a PR0 `401`; `_authorize_dispatch_report` must not accept `session=None`.

- [ ] **Step 5: Close `_authorize_dispatch_report` fallthroughs.** Unknown status returns the existing named unknown-status refusal; every known matrix entry is authorized before branch mutation, including workspace release. Keep corroboration mismatch `403 slot_claim_mismatch`; fill an absent compatibility field from the derived slot.

- [ ] **Step 6: Retire `revision_requested`.** Keep the branch so old agents receive an actionable response, but make it unconditionally `409 use_deck_approve_work_item`. Delete production calls to `record_approval_round`; delete that method after confirming zero callers.

- [ ] **Step 7: Remove PR0 grace authority from Agent Mail.** Change the four member-scoped routes—send, mark-read, acknowledge, and agent inbox—to `Depends(require_mail_session)` and server-derived `session.member_id`. Remove `member_id` from the inbox signature/URL, remove all four `derive_member_id` callers, then delete `derive_member_id` and its missing-token log cache from `deps.py`. Keep external-actor routes unchanged.

- [ ] **Step 8: Remove authority claims from the shim.** `deck_report_dispatch_status` no longer resolves a member to fill `reporting_slot_id`; `deck_check_inbox` no longer puts `member_id` in its URL. Keep the PR0 session token header path untouched.

- [ ] **Step 9: Update all approval wording.** The owner brief says approval exists only when the designated leader calls `deck_approve_work_item` for this work item/nonce/current round; prose replies are not approval; self-approval is refused. The leader instruction and nudge say the same. Rejection automatically opens the next round, after which the owner revises and calls `deck_request_context` with the same work item and nonce; nobody reports `revision_requested`.

- [ ] **Step 10: Add the rollout document.** It must state this exact order:
  1. set `operator_token` in `backend/.env` mode `0600`;
  2. deploy PR0;
  3. restart every agent pane so it registers and obtains a capability token;
  4. set `mail_capability_tokens_required = True` and restart the backend;
  5. verify authenticated mail and `/dispatch-status` on a non-autonomous test preset;
  6. deploy PR1;
  7. keep autonomy off until PR2 and the E2E gate complete.

  Explicitly prohibit exporting the operator token to tmux and explain that PR1 intentionally refuses all dispatch reports before enforcement.

- [ ] **Step 11: Run focused and full validation.**

```bash
venv/bin/pytest tests/agent_mail/test_api.py tests/agent_mail/test_dispatch_status_tool.py tests/agent_mail/test_mcp_shim.py tests/agent_teams/test_github_workspace_api.py -q -p no:warnings
venv/bin/pytest tests/agent_teams/ tests/agent_mail/ -q -p no:warnings
venv/bin/pytest tests/ -q -p no:warnings
```

Expected scoped total: **679 passed**. Expected full suite: **851 passed, 1 pre-existing failure**.

- [ ] **Step 12: Run static checks used by the repository.** From the repo root:

```bash
cd frontend && npm run typecheck
cd ../backend && venv/bin/python3 -m compileall -q app mcp_shim
```

Do not run or fix the repository-wide frontend lint baseline unless explicitly requested; PR1 changes no frontend source.

- [ ] **Step 13: Run namespace and forbidden-pattern checks.** Review results, do not blindly accept grep counts:

```bash
rg -n 'record_approval_round|derive_member_id' backend/app
rg -n 'reporting_slot_id' backend/mcp_shim/agent_mail_server.py
rg -n 'revision_requested' backend/app backend/mcp_shim
rg -n 'dispatch_status\s*=\s*["\x27]' backend/app --glob='*.py'
rg -n 'lease_token.*(is_|IS NOT DISTINCT|IS NULL)|IS NOT DISTINCT|lease_token.*OR' backend/app/services/github_workspace_service.py
```

Expected: no production `record_approval_round` or `derive_member_id`; no shim authority claim; `revision_requested` appears only in compatibility refusal/docs/tests; no new dispatch-status literal; no null-safe token comparison.

- [ ] **Step 14: Commit.**

```bash
git add backend/app/api/v1/deps.py backend/app/api/v1/agent_mail.py backend/app/api/v1/agent_teams.py backend/app/services/github_dispatch_service.py backend/mcp_shim/agent_mail_server.py docs/deploy/pr1-approval-gate-rollout.md backend/tests/agent_mail/test_api.py backend/tests/agent_mail/test_capability_tokens.py backend/tests/agent_mail/test_dispatch_status_tool.py backend/tests/agent_mail/test_mcp_shim.py backend/tests/agent_teams/test_github_workspace_api.py
git commit -m "feat(dispatch): enforce authenticated approval workflow"
```

---

## Final Review Gate

Do not open or push a PR until all three reviews below are complete and the working tree contains only intended changes.

### 1. Spec coverage review

- [ ] Map every PR1 artifact in §2.1 and §4.1–§4.8 to one task and one test.
- [ ] Verify all six work-item columns and both mail columns exist in ORM and migration ladder.
- [ ] Verify `attempt_head_ref` is called once from `prepare_attempt` and nowhere else.
- [ ] Verify a prepared item is never passed to `route_item`.
- [ ] Verify all five ack fields clear on retry, handoff, and below-cap rejection, and remain on at-cap escalation.
- [ ] Verify approval evidence comes only from the designated leader's explicit current-round `approved` decision under token enforcement.
- [ ] Verify the merge gate is separate from `_ack_satisfied` and uses the sticky human fallback prefix.
- [ ] Verify `accept_handoff` establishes liveness evidence before any continuation claim.
- [ ] Verify release and contact writes each bind current owner and ordinary token equality in SQL.
- [ ] Verify path A2 is interleaved inside `get_leased_workspace` and carries branch-arrival/non-arrival assertions.
- [ ] Verify NULL-token ordinary-equality semantics are recorded as a code-review check, not a fabricated reachable test.
- [ ] Verify no PR2 endpoint, GitHub auth, credential helper, PR reconciliation, or commit identity landed.

### 2. Placeholder and completeness scan

- [ ] Run:

```bash
rg -n 'TODO|TBD|placeholder|implement later|pass\s*$|NotImplemented' docs/superpowers/plans/2026-08-11-pr1-approval-attribution-and-gate.md backend/app backend/mcp_shim --glob='*.py' --glob='*.md'
```

- [ ] Inspect every hit. Existing legitimate `pass` statements are not automatic failures, but no PR1 function, test body, or plan step may be a placeholder.
- [ ] Confirm every task names all files in its `git add` command and no unrelated file is staged.

### 3. Type and transaction consistency review

- [ ] Compare every FastAPI dependency annotation with its actual return type: `mail_session -> MailAgentSession | None`, `require_mail_session -> MailAgentSession`, `require_operator -> None`, `get_db -> AsyncSession`.
- [ ] Confirm every route that accesses `session.member_id`, `team_slot_id`, or bound pane fields has first narrowed away `None`.
- [ ] Confirm `send_message(commit=False)` and any private row builder have honest return types and cannot auto-nudge or refresh before commit.
- [ ] Confirm branch A and branch B of `advance_approval_round` each have exactly one durable commit and notification failure cannot undo it.
- [ ] Confirm `accept_handoff` item and workspace changes share one transaction and one commit.
- [ ] Confirm fresh diagnoses issue a SQL query rather than returning an identity-mapped object.
- [ ] Confirm conditional writes run after `release_blocker` and after any needed explicit flush.
- [ ] Confirm every modified test file is included in the final commit history and the expected collected counts match pytest.

### Handoff after implementation

Report:

1. the ten local commit SHAs;
2. scoped and full pytest results, including the one pre-existing failure;
3. each mutation that was run and the test that killed it;
4. the explicit ordinary-SQL-equality review result;
5. any count mismatch or source drift;
6. confirmation that autonomy remained off, no live checkout/DB/session was touched, and nothing was pushed or merged.

Stop after the report. PR2 still requires its own reviewed implementation plan.
