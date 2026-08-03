# Phase G2 — Session Lifecycle and Workspace Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace process-liveness with an explicit, attempt-scoped workspace release protocol, then flip dispatch to one-session-per-slot with a delivery guarantee for the brief.

**Architecture:** Two PRs, release protocol first. PR1 makes every workspace lease attempt-scoped via a per-acquisition `lease_token`, adds an agent-reported `workspace_released` status, and replaces `reclaim_stale`'s single liveness gate with a five-condition conjunction whose signals cannot be true-by-design. PR2 flips `reuse_existing=True` and closes the three delivery defects that flip would otherwise expose. Sequencing is mandatory: flipping first creates Finding 19's permanent wedge with no releaser in place.

**Tech Stack:** FastAPI, async SQLAlchemy 2.0 (`Mapped`/`mapped_column`), aiosqlite, pydantic-settings, pytest + pytest-asyncio. Frontend React 19 + TS (one small change in PR1).

**Spec:** `docs/superpowers/specs/2026-08-02-phase-g2-session-lifecycle-design.md` — read §1 and §3 before starting. Every task below cites the spec section it implements.

**Precedence, when documents disagree** — one rule, and the same rule appears in the Codex handoff prompt:

| Disagreement | Rule |
|---|---|
| Plan vs spec, and the plan marks it **"Correction (date, review)"** | **The plan wins.** Implement the plan. There are exactly two: the §2.4 `mailbox_status` rule (Task 7) and the pid-capture ordering (Task 3). In both, the spec text is the version a review rejected. |
| Plan vs spec, **unmarked** | **Stop and report.** Unmarked divergence is drift in a 2000-line document, not a decision, and resolving it silently is how a rejected design gets shipped. |
| Plan (or spec) vs **the code** | **Stop and report.** A moved line number is fine to adapt to; a different *shape* means the reasoning may not hold. |

---

## Global Constraints

These apply to **every** task. They are not negotiable and several are safety rules earned from live incidents.

**Working environment — you are on the SAME machine as the live soak**

This is the single most important section. Everything below is reachable from your shell; none of it is on another host.

- Work **only** in `/home/juan/work/repos/juanrubio/claude-deck-g1`.
- **Never** touch `/home/juan/work/repos/juanrubio/claude-deck`. It holds `backend/claude_registry.db` — 1.1 MB, 28 work items, the evidence that made Findings 17/18/19 provable. It cannot be regenerated.
- **Never** touch `/home/juan/work/repos/tizonia/`. Five tmux sessions (`tizonia-openmax-il-{7845,afde,b19f,fd9c,fe2f}`) hold it as cwd right now, and workspace 1 is that checkout registered as `primary`.
- **`claude-deck-g1` is a git worktree of the live checkout, not a clone.** `cat .git` there reads `gitdir: .../claude-deck/.git/worktrees/claude-deck-g1`. They share one object store, one ref namespace, one stash, one index lock. Consequences you must respect:
  - Do **not** run `git worktree prune`, `git gc`, `git stash`, or any `git checkout`/`switch` of a branch already checked out in the other worktree.
  - Do **not** `git branch -f`, `git reset --hard`, or delete refs the other worktree may be on (`feature/autonomous-github-dispatch` is checked out live).
  - `git worktree list` will show `/tmp/pr303-verify` and `/tmp/pr305-review` as detached-HEAD worktrees. Leave them alone; they are the orchestrator's, pending cleanup.
- A backend process is running (one `uvicorn`). Do not restart, stop, or reload it. Note `database_url` defaults to `sqlite+aiosqlite:///./claude_registry.db` — **relative to the process CWD**, so anything you run from the live checkout's `backend/` directory touches the live DB. Run tests from `claude-deck-g1/backend` only.
- Autonomy is currently **OFF** (`agent_team_presets.autonomy_enabled = 0` for both presets, verified 2026-08-03). Leave it at 0.

**Git**
- Branch from and target `feature/autonomous-github-dispatch`. **One PR per phase** (PR1, then PR2).
- Never merge, self-merge, or push to `master`.
- **Starting state:** `claude-deck-g1` is currently on `feature/autonomous-github-dispatch-workspaces`, which is already merged (PR #305) and 10 commits behind the integration branch. Your first action is:
  ```bash
  cd /home/juan/work/repos/juanrubio/claude-deck-g1
  git fetch origin
  git checkout -b feature/autonomous-github-dispatch-phase-g2-release origin/feature/autonomous-github-dispatch
  ```
  Use `origin/feature/autonomous-github-dispatch` as the base, **not** the local branch of that name — the local one is checked out in the live worktree and a shared-worktree checkout of it would fail. PR2 branches separately, from the integration branch again after PR1 merges.

**Forbidden operations** (all of these have caused incidents)
- Do **not** add any new `dispatch_status` value. This design needs none — see spec §3.1 and §3.1a-bis.
- Do **not** enable or disable autonomy. It stays **OFF** for the whole of both PRs.
- Do **not** spawn or kill agent sessions.
- Do **not** hand-edit DB rows. Schema changes go through the migration ladder (Task 1).
- Do **not** restart the backend.
- Do **not** retry work item 23, or any other escalated item.

**Code style**
- Type hints throughout; `async`/`await` for all DB access.
- New settings go in `app/config.py` as pydantic-settings fields with defaults — no `.env` required.
- Datetimes: `datetime.utcnow()` to match every neighbouring call site. The suite emits deprecation warnings for this already; do **not** "fix" them here, it would be an unrelated cross-cutting change.
- New columns: `Mapped[X | None] = mapped_column(..., nullable=True)`.

**Testing**
- Baseline is **239 passed** in `backend/tests/agent_teams/` — verified 2026-08-03 *inside `claude-deck-g1` itself*, so it is your starting number, not a figure from another checkout. Run with:
  `cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && python -m pytest tests/agent_teams/ -q`
- **Use `venv`, not `.venv`.** Both directories exist in `claude-deck-g1/backend`; `.venv` has no pytest installed and will fail with `No module named pytest`. Do not try to fix `.venv` — just use `venv`.
- Always `cd` to the **g1** backend before running pytest. `database_url` is relative to CWD, so running from the live checkout's `backend/` would point the suite at the live soak DB.
- Every task ends green. If a test fails for a reason your task did not cause, **report it, do not rewrite it.**
- Known pre-existing failure **outside** this directory: `tests/test_multi_provider_smoke.py:54` (stale monkeypatch). Ignore it; an issue is owed separately.

**Stop and report** if a step's preconditions do not match what you find — a wrong line number is fine to adapt to, but a wrong *shape* (the function does something other than described) means the spec's reasoning may not hold.

---

## File Structure

No new files. Both PRs are edits to eight existing backend modules, and the responsibility boundaries already in place are the right ones — the release protocol is workspace-lifecycle logic, so it belongs in the workspace service, and dispatch only calls into it.

| File | Responsibility here | Tasks |
|---|---|---|
| `app/models/database.py` | The eight new nullable columns | 1 |
| `app/database.py` | Migration ladder entries (new `github_workspaces` block) | 1 |
| `app/config.py` | `github_stale_lease_backstop_seconds` | 1 |
| `app/services/github_workspace_service.py` | Owns the lease: token minting, pid liveness, the release conjunction, dirty-tree veto, owner-contact stamping | 2, 3, 4, 6 |
| `app/services/github_dispatch_service.py` | Owns dispatch: pid capture after launch, retry deferral + promotion, release reminders, delivery evidence, ambiguity refusal, the `reuse_existing` flip | 3, 4, 5, 8, 10, 12, 13 |
| `app/api/v1/agent_teams.py` | The `workspace_released` report branch, force-release, response fields | 5, 6, 9 |
| `app/models/schemas.py` | `lease_token` in, lease state and `retry_requested_at` out | 1, 3, 5, 6, 9 |
| `app/services/agent_mail_service.py` | Finding 17's rule; the non-throttled dispatch wake | 7, 11 |
| `app/services/github_watcher_service.py` | Calls the promotion sweep from `poll_scope` | 5 |
| `app/services/github_verification_service.py` | Clears `retry_requested_at` on legitimate recovery | 5 |
| `mcp_shim/agent_mail_server.py` | Forwards `lease_token` from the agent-facing tool | 6 |

`github_dispatch_service.py` is the one file taking most of the change, and it is already large. Do **not** split it as part of these PRs — it is the live soak's hottest file and a reorganisation would make the diff unreviewable against the spec. If it needs splitting, that is its own change on a quiet branch.

---

# PR1 — The release protocol

Nine tasks. After Task 9 the branch is ready for review; autonomy stays off.

Tasks 8 and 9 are §6's mitigations. They are **not optional trimming**: without them a lease held by a live-but-silent session is held *indefinitely*, which §6 states is not an acceptable ceiling. If you are running short, say so and stop — do not ship Tasks 1–7 alone and call PR1 done.

---

### Task 1: Schema — nine nullable columns and two settings

**Files:**
- Modify: `backend/app/models/database.py:285-311` (`GithubWorkspace`), `:240-282` (`GithubWorkItem`)
- Modify: `backend/app/database.py:419-432` (the `github_work_items` migration block), and add a new `github_workspaces` block after `:432`
- Modify: `backend/app/config.py:38-47`
- Test: `backend/tests/agent_teams/test_github_workspace_service.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `GithubWorkspace.lease_token: str | None`, `.leased_owner_pid: int | None`, `.leased_owner_proc_start: str | None`, `.lease_last_owner_contact_at: datetime | None`, `.lease_release_reminded_at: datetime | None`; `GithubWorkItem.retry_requested_at: datetime | None`, `.brief_delivery_nudge_at: datetime | None`, `.brief_delivery_nudge_count: int | None`, `.brief_message_id: int | None`; `settings.github_stale_lease_backstop_seconds: int`, `settings.github_brief_delivery_max_nudges: int`.

Implements spec §3.2 (column inventory), §7 step 1 (migration mechanism).

**Why all nine land in one task:** they are one `ADD COLUMN` sweep against two tables plus two settings lines. Splitting them would produce commits that add a column no code reads, and the migration ladder is the single riskiest step in the deployment (§7) — it deserves one reviewable diff. `brief_delivery_nudge_*` and `brief_message_id` belong to PR2 but the columns are added here so PR2 needs no second migration.

**Two deliberate deltas from the spec.** §3.2 and §7 step 1 both inventory **seven** columns; this task adds two more.

**The ninth, `brief_message_id`, is required by §4.1a test (1)** and the spec does not name it either. §4.1a says delivery is proven by "the receipt's `read_at`" — but *which* receipt? `MailReceipt` is unique on `(message_id, member_id)` only (`database.py:451`), with nothing attempt-scoped, and `_send_dispatch_brief_to_slot` (`github_dispatch_service.py:517-546`) **discards** the `MailMessageResponse` it gets back. So "the owner has an unread receipt" is answerable today only by guessing which of the member's messages was the brief — and a re-dispatched item has more than one. Worse, the guess fails in the unsafe direction: an *older* brief that was read would prove delivery for an attempt whose brief was never delivered. Same defect family as everything else in this design — a signal answering *which member?* when the question is *which dispatch?*

Storing the id makes the lookup exact and single-row. See Task 12 Step 3.

**The eighth, `lease_release_reminded_at`,** is needed by §6 mitigation 1 (release reminders, Task 8) — the spec specifies that mitigation without naming its clock. Do not substitute `last_nudge_at` for it: that field already multiplexes the leader-ack and owner-idle timers, `reset_for_retry` does **not** clear it, and `monitor_dispatched:645` reads `if item.last_nudge_at is None: nudge_leader` **else escalate**. A reminder timestamp surviving into a retried item would therefore escalate `leader_ack_timeout` without the leader ever being nudged. Putting it on the workspace row instead means `release` clears it for free, and it is exactly the field §6 mitigation 2 wants exposed. This is §4.1a's multiplexing lesson recurring one column over.

- [ ] **Step 1: Read the migration ladder before touching it**

Read `backend/app/database.py:290-449` (`_run_sqlite_compat_migrations`). Note the established pattern: `PRAGMA table_info` → a set of column names → `if <table>_columns and "<col>" not in <table>_columns: ALTER TABLE ... ADD COLUMN`. It is idempotent and runs from `init_db` (`:452-458`) on every startup.

**The spec was wrong about this once already** (§7 step 1 records the correction): `CLAUDE.md` claims "No database migration system — schema changes require deleting the db". That is false. Do not delete any database.

- [ ] **Step 2: Write the failing test**

Add to `backend/tests/agent_teams/test_github_workspace_service.py`:

```python
@pytest.mark.asyncio
async def test_lease_columns_default_to_null(db, tmp_path):
    """A lease predating G2 must read as 'no information', never as a false negative.

    Spec §3.2: a NULL pid makes backstop condition 3 unsatisfiable, so any
    lease that predates this migration is retained rather than reclaimed.

    Verified against the live DB 2026-08-03: both workspaces are currently
    UNLEASED (leased_item_id IS NULL), so no real row exercises this on the
    first migration. The test therefore constructs the state, and the guarantee
    still has to hold — the next acquire() after deployment writes a lease whose
    pid capture may fail, landing in exactly this shape.
    """
    scope, _, item = await _context(db, tmp_path / "repo")
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        leased_item_id=item.id,
    )
    db.add(workspace)
    await db.commit()

    assert workspace.lease_token is None
    assert workspace.leased_owner_pid is None
    assert workspace.leased_owner_proc_start is None
    assert workspace.lease_last_owner_contact_at is None
    assert workspace.lease_release_reminded_at is None
    assert item.retry_requested_at is None
    assert item.brief_delivery_nudge_at is None
    assert item.brief_delivery_nudge_count is None
    assert item.brief_message_id is None
```

- [ ] **Step 3: Run it and watch it fail**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/agent_teams/test_github_workspace_service.py::test_lease_columns_default_to_null -v`
Expected: FAIL — `AttributeError: 'GithubWorkspace' object has no attribute 'lease_token'`

- [ ] **Step 4: Add the ORM columns**

In `backend/app/models/database.py`, inside `class GithubWorkspace`, after `released_at` (`:302`):

```python
    lease_token: Mapped[str | None] = mapped_column(String, nullable=True)
    leased_owner_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    leased_owner_proc_start: Mapped[str | None] = mapped_column(String, nullable=True)
    lease_last_owner_contact_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lease_release_reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

`leased_owner_proc_start` is a **String**, not an Integer: it is field 22 of `/proc/<pid>/stat` compared only for equality, and storing it verbatim avoids any int-parse ambiguity.

Inside `class GithubWorkItem`, after `last_nudge_at` (`:273`):

```python
    retry_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    brief_delivery_nudge_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    brief_delivery_nudge_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    brief_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

`brief_delivery_nudge_count` is nullable rather than `default=0, nullable=False`: an `ADD COLUMN` on an existing SQLite table cannot backfill a NOT NULL column without a default, and treating NULL as "never nudged" is exactly right. PR2 reads it as `(item.brief_delivery_nudge_count or 0)`.

`brief_message_id` is a **plain Integer with no `ForeignKey`**, deliberately. SQLite cannot add a column with a foreign-key constraint via `ALTER TABLE ADD COLUMN`, and the reference is advisory: PR2 reads it with `await db.get(MailMessage, ...)` and treats `None` as "no brief recorded", which is the same branch it takes for a pre-migration item. Do not add `ondelete` behaviour or a relationship — nothing in the codebase deletes `mail_messages` rows (verified: no `delete(MailMessage)` anywhere in `app/`), so there is no dangling-id path to defend against.

- [ ] **Step 5: Add the migration entries**

In `backend/app/database.py`, extend the existing `github_work_items` block (after `:432`):

```python
    if work_item_columns and "retry_requested_at" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN retry_requested_at DATETIME"))
    if work_item_columns and "brief_delivery_nudge_at" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN brief_delivery_nudge_at DATETIME"))
    if work_item_columns and "brief_delivery_nudge_count" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN brief_delivery_nudge_count INTEGER"))
    if work_item_columns and "brief_message_id" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN brief_message_id INTEGER"))
```

Then add a **new** block for `github_workspaces`, which has no entries yet:

```python
    workspace_columns = await _sqlite_columns(conn, "github_workspaces")
    if workspace_columns and "lease_token" not in workspace_columns:
        await conn.execute(text("ALTER TABLE github_workspaces ADD COLUMN lease_token VARCHAR"))
    if workspace_columns and "leased_owner_pid" not in workspace_columns:
        await conn.execute(text("ALTER TABLE github_workspaces ADD COLUMN leased_owner_pid INTEGER"))
    if workspace_columns and "leased_owner_proc_start" not in workspace_columns:
        await conn.execute(text("ALTER TABLE github_workspaces ADD COLUMN leased_owner_proc_start VARCHAR"))
    if workspace_columns and "lease_last_owner_contact_at" not in workspace_columns:
        await conn.execute(
            text("ALTER TABLE github_workspaces ADD COLUMN lease_last_owner_contact_at DATETIME")
        )
    if workspace_columns and "lease_release_reminded_at" not in workspace_columns:
        await conn.execute(
            text("ALTER TABLE github_workspaces ADD COLUMN lease_release_reminded_at DATETIME")
        )
```

Place it **before** the final `await conn.commit()` at `:449`. Use `_sqlite_columns` (the helper at `:64`) for the new block rather than an inline `PRAGMA`; both styles exist in the file and the helper is the better one.

All nine are nullable with no default — that is what makes `ADD COLUMN` legal on SQLite and what makes every pre-existing row read as "no information".

- [ ] **Step 6: Add the two settings**

In `backend/app/config.py`, after `github_min_available_memory_mb` (`:47`):

```python
    github_stale_lease_backstop_seconds: int = 21600  # 6h; see G2 design §3.2, §6
    github_brief_delivery_max_nudges: int = 2  # bounded retry; see §4.1a, Task 12
```

Settings fields, not module constants — matching `github_leader_ack_timeout_seconds` and its four neighbours. 6h is explicitly a guess (spec §6) and needs an operator override. Condition 2 and condition 4's contact-ageing share that one number.

`github_brief_delivery_max_nudges = 2` is what makes §4.1a's "bounded retry" a number rather than a phrase: two re-nudges spaced by `github_nudge_grace_seconds` (180s, `config.py:46`) before `brief_unread`. Chosen to sit **inside** `github_owner_idle_timeout_seconds` (900s) so a genuinely undelivered brief escalates as `brief_unread` and not as `owner_idle_timeout` — the same misattribution §4.1a correction (3) exists to prevent, arriving via the other timer. Do not raise it past 4 without also raising the idle timeout.

- [ ] **Step 7: Run the new test and the full suite**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/agent_teams/test_github_workspace_service.py::test_lease_columns_default_to_null -v`
Expected: PASS

Run: `python -m pytest tests/agent_teams/ -q`
Expected: **240 passed** (239 baseline + 1 new)

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/database.py backend/app/database.py backend/app/config.py \
        backend/tests/agent_teams/test_github_workspace_service.py
git commit -m "feat(g2): add lease-identity and retry-deferral columns

Nine nullable columns via the existing compat ladder (database.py:290), so
every checkout migrates itself on restart and no SQL is hand-applied to the
live soak DB. NULL on pre-existing rows means 'no information', which keeps
item 23's lease un-reclaimable — the correct outcome.

brief_message_id is here rather than in PR2 so PR2 needs no second migration.
It exists because MailReceipt is unique on (message_id, member_id) only: with
no recorded id, 'is the brief unread?' has to guess which of the member's
messages was the brief, and a re-dispatched item has several. The guess fails
unsafely — an older, read brief would prove delivery for an attempt whose
brief never arrived.

Adds github_stale_lease_backstop_seconds (6h) and
github_brief_delivery_max_nudges (2) as settings fields, matching the pattern
of every other dispatch threshold."
```

---

### Task 2: `_owner_process_is_alive` — liveness that survives pid reuse

**Files:**
- Modify: `backend/app/services/github_workspace_service.py` (new private method + import)
- Test: `backend/tests/agent_teams/test_github_workspace_service.py`

**Interfaces:**
- Consumes: Task 1's columns.
- Produces: `GithubWorkspaceService._read_proc_start(self, pid: int) -> str | None` and `GithubWorkspaceService._owner_process_is_alive(self, workspace: GithubWorkspace) -> bool`. Task 4's conjunction calls `_owner_process_is_alive`; Task 3's dispatch capture calls `_read_proc_start`.

Implements spec §3.2 (the `/proc` parse, pid-reuse guard, and the unknown→alive rule).

**Why its own task:** it is a pure function with a nasty parse and a three-way error contract, and it is the one piece of PR1 whose failure mode is silent (a wrong parse yields plausible-but-wrong liveness). It deserves a reviewer's gate before anything depends on it.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/agent_teams/test_github_workspace_service.py`:

```python
def test_read_proc_start_handles_comm_containing_spaces_and_parens():
    """Field 2 of /proc/<pid>/stat is parenthesized and may contain spaces or parens.

    A naive split() puts starttime at the wrong index. Spec §3.2 pins the
    rindex(")") recipe; this fixture is the case that breaks the naive version.
    """
    service = GithubWorkspaceService(runner=FakeGitRunner())
    raw = "12345 (weird (proc) name) S 1 12345 12345 0 -1 4194560 " + " ".join(
        str(n) for n in range(100, 118)
    ) + " 987654321 " + " ".join(str(n) for n in range(200, 210))

    fields = raw[raw.rindex(")") + 2:].split()

    assert fields[19] == "987654321"
    assert service._parse_proc_start(raw) == "987654321"


@pytest.mark.asyncio
async def test_owner_process_alive_is_true_when_pid_is_null(db, tmp_path):
    """Unknown liveness is treated as alive: the safe direction (spec §3.2)."""
    scope, _, item = await _context(db, tmp_path / "repo")
    workspace = GithubWorkspace(
        scope_id=scope.id, path=str(tmp_path / "ws"), leased_item_id=item.id
    )
    db.add(workspace)
    await db.commit()
    service = GithubWorkspaceService(runner=FakeGitRunner())

    assert service._owner_process_is_alive(workspace) is True


@pytest.mark.asyncio
async def test_owner_process_alive_is_false_for_dead_pid(db, tmp_path, monkeypatch):
    """A dead pid must be proven dead, not assumed dead by picking a big number.

    Correction (2026-08-03): an earlier draft used a literal 4194303. pid_max on
    this host is 4194304, so that pid is legal and allocatable — the test would
    invert the day the host assigns it, with no code change. Monkeypatch the
    /proc read to raise instead, which also names WHICH exception maps to dead.
    """
    scope, _, item = await _context(db, tmp_path / "repo")
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        leased_item_id=item.id,
        leased_owner_pid=123456,
        leased_owner_proc_start="123",
    )
    db.add(workspace)
    await db.commit()
    service = GithubWorkspaceService(runner=FakeGitRunner())

    def _dead(pid):
        raise ProcessLookupError()

    monkeypatch.setattr(service, "_read_proc_start", _dead)

    assert service._owner_process_is_alive(workspace) is False


@pytest.mark.asyncio
async def test_owner_process_alive_is_false_when_proc_start_differs(db, tmp_path, monkeypatch):
    """Pid reuse: same pid, different start time, is a DIFFERENT process.

    Spec §3.2 — Finding 18's trap one level down, an identifier whose
    uniqueness is assumed rather than guaranteed.
    """
    scope, _, item = await _context(db, tmp_path / "repo")
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        leased_item_id=item.id,
        leased_owner_pid=os.getpid(),
        leased_owner_proc_start="999999999",
    )
    db.add(workspace)
    await db.commit()
    service = GithubWorkspaceService(runner=FakeGitRunner())

    assert service._owner_process_is_alive(workspace) is False


@pytest.mark.asyncio
async def test_owner_process_alive_is_true_for_this_process(db, tmp_path):
    scope, _, item = await _context(db, tmp_path / "repo")
    service = GithubWorkspaceService(runner=FakeGitRunner())
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        leased_item_id=item.id,
        leased_owner_pid=os.getpid(),
        leased_owner_proc_start=service._read_proc_start(os.getpid()),
    )
    db.add(workspace)
    await db.commit()

    assert service._owner_process_is_alive(workspace) is True


@pytest.mark.asyncio
async def test_owner_process_alive_is_true_when_proc_unreadable(db, tmp_path, monkeypatch):
    """An OSError that is not 'no such process' means UNKNOWN, so: alive, lease retained.

    Deliberately the opposite of _effective_status's fail-closed choice for the
    same error (spec §2.4 records why: the backstop retains a resource, the UI
    reports a status).
    """
    scope, _, item = await _context(db, tmp_path / "repo")
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        leased_item_id=item.id,
        leased_owner_pid=os.getpid(),
        leased_owner_proc_start="123",
    )
    db.add(workspace)
    await db.commit()
    service = GithubWorkspaceService(runner=FakeGitRunner())

    def _boom(_pid):
        raise PermissionError("denied")

    monkeypatch.setattr(service, "_read_proc_start", _boom)

    assert service._owner_process_is_alive(workspace) is True
```

Add `import os` to the test file's imports if absent.

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/agent_teams/test_github_workspace_service.py -k "proc_start or owner_process_alive" -v`
Expected: FAIL — `AttributeError: ... has no attribute '_parse_proc_start'`

- [ ] **Step 3: Implement**

In `backend/app/services/github_workspace_service.py`, add `import pathlib` at the top, then add these three methods to `GithubWorkspaceService` (put them after `_run_git`, before `acquire`):

```python
    def _parse_proc_start(self, raw: str) -> str | None:
        """Field 22 (starttime) of a /proc/<pid>/stat line.

        Field 2 (comm) is parenthesized and may contain spaces or parentheses,
        so the fields after it are located from the LAST ')' — a naive split()
        silently returns the wrong field. Index 19 is field 22 overall,
        counting from state (field 3) at index 0.
        """
        try:
            return raw[raw.rindex(")") + 2:].split()[19]
        except (ValueError, IndexError):
            return None

    def _read_proc_start(self, pid: int) -> str | None:
        """Raises FileNotFoundError/ProcessLookupError if the process is gone.

        Any other OSError propagates: the caller must treat it as UNKNOWN, not
        as death.
        """
        return self._parse_proc_start(
            pathlib.Path(f"/proc/{pid}/stat").read_text()
        )

    def _owner_process_is_alive(self, workspace: GithubWorkspace) -> bool:
        """Is the process that was briefed with this lease still running?

        Unknown counts as alive. A NULL pid (every pre-G2 lease, and any
        dispatch whose pid capture failed) is therefore never reclaimable —
        the safe direction, since guessing 'dead' risks a reset --hard under a
        working agent.
        """
        if workspace.leased_owner_pid is None:
            return True
        try:
            current_start = self._read_proc_start(workspace.leased_owner_pid)
        except (FileNotFoundError, ProcessLookupError):
            return False
        except OSError:
            return True
        if current_start is None or workspace.leased_owner_proc_start is None:
            return True
        return current_start == workspace.leased_owner_proc_start
```

Note `FileNotFoundError` is a subclass of `OSError`, so its `except` clause must come **first**. That ordering is the whole contract.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/agent_teams/test_github_workspace_service.py -k "proc_start or owner_process_alive" -v`
Expected: 6 PASS

Run: `python -m pytest tests/agent_teams/ -q`
Expected: **246 passed**

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/github_workspace_service.py \
        backend/tests/agent_teams/test_github_workspace_service.py
git commit -m "feat(g2): pid liveness that survives reuse and unreadable /proc

Parses field 22 from the last ')' — a naive split() lands on the wrong field
whenever comm contains a space or paren. Pairs pid with proc start time so
'alive' means THIS process, not A process.

Three-way error contract: no-such-process => dead; any other OSError or a NULL
pid => unknown, treated as alive so the lease is retained. Deliberately the
opposite of _effective_status's fail-closed choice for the same error; the
backstop retains a resource, the UI reports a status."
```

---

### Task 3: Mint the lease token and capture the owner pid

**Files:**
- Modify: `backend/app/services/github_workspace_service.py:61-105` (`acquire`)
- Modify: `backend/app/services/github_dispatch_service.py:276-293` (post-launch block)
- Modify: `backend/app/models/schemas.py:2336-2347` (`AgentTeamLaunchResultItem`)
- Modify: `backend/app/services/agent_team_service.py` (populate the new result field)
- Test: `backend/tests/agent_teams/test_github_workspace_service.py`, `backend/tests/agent_teams/test_github_dispatch_service.py`

**Interfaces:**
- Consumes: Task 1's columns, Task 2's `_read_proc_start`.
- Produces: `acquire` now sets `workspace.lease_token` to a fresh `secrets.token_hex(8)` on every real acquisition; `AgentTeamLaunchResultItem.pane_pid: int | None`.

Implements spec §3.1a (token per acquisition), §3.2 (pid captured after launch, not at acquire).

**The ordering correction that makes this task non-obvious:** `acquire` runs at `github_dispatch_service.py:222`, **before** `launcher(...)` at `:251`. On the spawn path the owning pane does not exist yet, so the pid cannot be captured inside `acquire`. It is written in a second step where `dispatched_at` is already set (`:288`).

- [ ] **Step 1: Write the failing tests**

In `test_github_workspace_service.py`:

```python
@pytest.mark.asyncio
async def test_acquire_mints_a_fresh_token_each_acquisition(db, tmp_path):
    """The token names the ACQUISITION, not the item (spec §3.1a).

    Two acquisitions of the SAME item must not share a token, or a stale
    release from attempt 1 can return attempt 2's live lease — Finding 10
    through a new door.
    """
    scope, _, item = await _context(db, tmp_path / "repo")
    service = GithubWorkspaceService(runner=FakeGitRunner())
    workspace = GithubWorkspace(scope_id=scope.id, path=str(tmp_path / "ws"))
    db.add(workspace)
    await db.commit()

    first = await service.acquire(db, scope, item)
    first_token = first.lease_token
    await service.release(db, item.id)
    second = await service.acquire(db, scope, item)

    assert first_token is not None
    assert second.lease_token is not None
    assert second.lease_token != first_token


@pytest.mark.asyncio
async def test_acquire_returning_held_lease_does_not_remint(db, tmp_path):
    """acquire()'s early return hands back the EXISTING lease unchanged.

    This is the step-4 hazard in spec §3.1a-bis: if a token were minted here
    without a reset, the caller would believe it had a fresh workspace. The
    retry deferral (Task 5) is what prevents this path being reached; this
    test pins that acquire itself does not lie about it.
    """
    scope, _, item = await _context(db, tmp_path / "repo")
    service = GithubWorkspaceService(runner=FakeGitRunner())
    workspace = GithubWorkspace(scope_id=scope.id, path=str(tmp_path / "ws"))
    db.add(workspace)
    await db.commit()

    first = await service.acquire(db, scope, item)
    token = first.lease_token
    again = await service.acquire(db, scope, item)

    assert again.id == first.id
    assert again.lease_token == token
```

In `test_github_dispatch_service.py`, find how existing dispatch tests build their fake launcher result (search for `tmux_target`), then add a test asserting that after a successful dispatch the leased workspace has `leased_owner_pid` set from the launch result's `pane_pid`, and that a launch result with `pane_pid=None` leaves it NULL while still reaching `dispatch_status == "dispatched"`.

- [ ] **Step 2: Run and watch them fail**

Run: `python -m pytest tests/agent_teams/test_github_workspace_service.py -k "token" -v`
Expected: FAIL — `assert None is not None`

- [ ] **Step 3: Mint the token in `acquire`**

Add `import secrets` to `github_workspace_service.py`. In `acquire`, in the block that claims a free workspace (`:90-95`), add the token beside the other lease fields:

```python
        now = datetime.utcnow()
        workspace.leased_item_id = item.id
        workspace.leased_at = now
        workspace.released_at = None
        workspace.lease_token = secrets.token_hex(8)
        workspace.leased_owner_pid = None
        workspace.leased_owner_proc_start = None
        workspace.lease_last_owner_contact_at = None
        workspace.lease_release_reminded_at = None
        workspace.updated_at = now
        await db.commit()
```

The four explicit `None` assignments matter: a workspace row is **reused** across leases, so a previous lease's pid and contact timestamp must be cleared or the backstop would evaluate the new lease against the old owner's evidence. Same defect family as everything else in this design.

Leave the `held is not None` early return (`:67-73`) **exactly as it is**. It must not mint a token, because it does not reset the workspace.

- [ ] **Step 4: Clear the same fields in `release`**

In `release` (`:107-119`), alongside `leased_item_id = None`:

```python
        workspace.leased_item_id = None
        workspace.released_at = now
        workspace.lease_token = None
        workspace.leased_owner_pid = None
        workspace.leased_owner_proc_start = None
        workspace.lease_last_owner_contact_at = None
        workspace.lease_release_reminded_at = None
        workspace.updated_at = now
```

`release` clearing the reminder stamp is why it lives on the workspace row rather than the item: a lease that is released and later re-acquired starts its reminder clock fresh with no extra code.

- [ ] **Step 5: Add `pane_pid` to the launch result**

In `backend/app/models/schemas.py`, in `AgentTeamLaunchResultItem` (`:2336-2347`), after `tmux_target`:

```python
    pane_pid: Optional[int] = None
```

Then populate it in `agent_team_service.py` wherever `tmux_target` is set on a result item — for both the spawn and reuse branches. Search for `tmux_target=` in that file.

**Correction (2026-08-03, impl-agent review + orchestrator verification): the spawn path has no pid to pass through, so there must be a resolution step.** The earlier draft said to prefer a value "the launch path already has in hand" and, failing that, to leave `pane_pid=None`. Verified: `spawn_session` (`agent_bridge/spawn.py:101-106`) returns exactly `{provider, provider_display_name, tmux_target, session_name}` — **no pid at all**. So on the spawn path there is no value in hand, the fallback would always be taken, `leased_owner_pid` would be NULL on every newly spawned lease, and backstop condition 3 would be unsatisfiable for all of them. The backstop would release nothing — Finding 19 restored through a different door. A NULL pid is only an acceptable *exception*; it cannot be the standard outcome.

Resolve `tmux_target` → pid instead. Add to `github_dispatch_service.py`:

```python
    def _resolve_pane_pid(self, tmux_target: str | None) -> int | None:
        """Resolve a tmux target to its pane pid. Best-effort by contract.

        Verified on this host 2026-08-03:
          $ tmux display-message -p -t <live target> '#{pane_pid}'  -> "149190", exit 0
          $ tmux display-message -p -t <bogus target> '#{pane_pid}' -> "",       exit 0

        A bogus target exits ZERO with empty stdout, so the return code is not a
        validity signal — the output must be parsed and empty output treated as
        failure. Checking only `returncode == 0` would store None while looking
        like it succeeded.
        """
        if not tmux_target:
            return None
        try:
            result = subprocess.run(
                ["tmux", "display-message", "-p", "-t", tmux_target, "#{pane_pid}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            logger.warning("could not resolve pane pid for %s", tmux_target)
            return None
        if result.returncode != 0:
            return None
        raw = result.stdout.strip()
        if not raw.isdigit():
            logger.warning(
                "tmux returned no pane pid for %s (stdout=%r) — the lease will "
                "not be auto-reclaimable",
                tmux_target,
                raw,
            )
            return None
        return int(raw)
```

Add `import subprocess` and use the module's existing `logger`. Prefer `launch_item.pane_pid` when the launch result carries one (the reuse branch may), and fall back to this resolver:

```python
pane_pid = getattr(launch_item, "pane_pid", None) or self._resolve_pane_pid(tmux_target)
```

Why a second tmux round-trip is acceptable here, reversing the draft's reasoning: the race the draft feared is against the pane's *startup*, but `display-message -p '#{pane_pid}'` asks tmux for the pane's own pid, which exists the moment the pane does — it does not depend on the agent process inside having finished initialising. `discover_agent_sessions()` would be the racy choice, because it filters panes by *recognized provider command* (`discovery.py:124-125`), and a pane whose provider has not yet exec'd is skipped. So use `display-message`, **not** `discover_agent_sessions`.

**Write a test that the fallback is actually exercised on the spawn path**, monkeypatching `_resolve_pane_pid` to return a known pid and asserting `workspace.leased_owner_pid` equals it. Without that test, this whole correction can silently regress to NULL — which is the failure mode that reads as working.

The logged warning is required, not decorative: a NULL pid means an operator is now the only thing that can clear that lease, and Task 9's staleness view is the only other place that becomes visible.

- [ ] **Step 6: Capture the pid after launch**

In `github_dispatch_service.py`, in the `else` branch where dispatch succeeds (`:286-290`):

```python
            else:
                item.dispatch_status = "dispatched"
                item.dispatched_at = datetime.utcnow()
                pane_pid = getattr(launch_item, "pane_pid", None) or self._resolve_pane_pid(
                    tmux_target
                )
                if pane_pid is not None:
                    try:
                        proc_start = github_workspace_service._read_proc_start(pane_pid)
                    except OSError:
                        proc_start = None
                    # Store the pair or NEITHER. A pid without its start time
                    # cannot be checked for reuse: _owner_process_is_alive
                    # returns True whenever proc_start is None (Task 2), so a
                    # half-written pair silently makes the lease permanent.
                    if proc_start is not None:
                        workspace.leased_owner_pid = pane_pid
                        workspace.leased_owner_proc_start = proc_start
                        workspace.updated_at = datetime.utcnow()
                    else:
                        logger.warning(
                            "captured pane pid %s for item %s but could not read "
                            "its start time; lease will not be auto-reclaimable",
                            pane_pid,
                            item.id,
                        )
                slots_dispatched_this_batch.add(owner_slot_id)
                scope_dispatched_this_batch += 1
```

A failed pid capture must **never** fail a dispatch that otherwise succeeded (spec §3.2) — hence the caught `OSError` and the absence of any re-raise.

Note the all-or-nothing pairing, which the draft got wrong: it wrote `leased_owner_pid` first and then set `leased_owner_proc_start = None` on failure. Task 2's `_owner_process_is_alive` returns **True** when `leased_owner_proc_start is None` (it cannot rule out pid reuse), so that combination is indistinguishable from a live owner and holds the lease forever. Both columns are written together or neither is. Test this explicitly: monkeypatch `_read_proc_start` to raise `OSError` and assert `leased_owner_pid is None` afterwards.

- [ ] **Step 7: Run the tests**

Run: `python -m pytest tests/agent_teams/ -q`
Expected: all pass, count = 246 + the tests you added.

- [ ] **Step 8: Commit**

```bash
git add -A backend/app backend/tests
git commit -m "feat(g2): mint a per-acquisition lease token, capture the owner pid

acquire() mints secrets.token_hex(8) per real acquisition and clears the
previous lease's pid/contact fields — a workspace row outlives its leases, so
stale owner evidence would otherwise be evaluated against a new lease.

The early-return path (held is not None) deliberately does NOT mint: it
performs no reset, so a fresh token there would be a lie. Task 5's retry
deferral is what keeps that path from being reached.

Pid is captured after launch, not in acquire: acquire runs before launcher(),
so on the spawn path the pane does not exist yet. spawn_session returns no pid
(spawn.py:101-106), so tmux_target is resolved via display-message; a bogus
target exits ZERO with empty stdout, so the output is parsed rather than the
return code trusted. pid and proc_start are stored as a pair or not at all: a
pid without a start time reads as ALIVE and would hold the lease forever. A
failed capture never fails the dispatch."
```

---

### Task 4: The backstop conjunction

**Files:**
- Modify: `backend/app/services/github_workspace_service.py:121-146` (`reclaim_stale`)
- Modify: `backend/app/services/github_dispatch_service.py:114-...` (delete `slot_has_live_owner_session`), `:215-221` (delete its dispatch gate)
- Test: `backend/tests/agent_teams/test_github_workspace_service.py:210-260` (rewrite two tests), `test_github_dispatch_service.py:1299` (delete one)

**Interfaces:**
- Consumes: Task 1's columns, Task 2's `_owner_process_is_alive`, Task 3's token.
- Produces: `reclaim_stale` returns the count of leases released under the five-condition conjunction.

Implements spec §3.2 (the conjunction), §3.2a (owner-contact recency), §2.2 (deleting the predicate).

**Read spec §1.2 before starting this task.** The predicate being deleted is not merely wrong — it is *permanently true* under one-session-per-slot, which is why `reclaim_stale` released 0 forever. Do not replace it with anything that asks "is the slot's session alive?"; that is the trap §3.2a documents.

**Correction (2026-08-03, orchestrator verification): condition 5 is two checks, not one.** The spec (§3.2 condition 5, §3.2a residual risk) defines the quiescence veto as `git status --porcelain` being empty. That is **insufficient**, and this was verified experimentally rather than reasoned about:

```
$ git commit -qm "agent: implement feature"   # agent commits, does not push
$ git status --porcelain                       # -> EMPTY
```

An agent that has committed its work locally and not yet pushed produces a **clean** porcelain output. So the veto passes, the lease is released, and the next `acquire` runs `reset --hard <base_ref>` + `clean -fd` (`github_workspace_service.py:155-159`) — which removes those commits from the tree. Recovery is reflog-only, in an object store shared with the live checkout. Committed-but-unpushed work is *exactly* what a dispatched agent holds between starting and opening a PR, so this is the common state, not an exotic one.

Spec §3.2a's residual-risk paragraph (`:581-585`) frames the danger as "a clean tree at the sampling moment", implying the tree must merely *happen* to be quiescent. The sharper statement: the tree can be clean **because** the agent committed. Condition 5 therefore requires both halves:

1. `git status --porcelain` is empty (no uncommitted or untracked changes), **and**
2. `git rev-list --count <base_ref>..HEAD` is `0` (no unpushed commits).

Either check failing, **or erroring**, retains the lease. This preserves the veto's one-directional contract: it can only prevent a release.

- [ ] **Step 1: Rewrite the two tests that monkeypatch the deleted predicate**

First extend `FakeGitRunner` (`:38-59`). Two gaps block the tests below:

```python
class FakeGitRunner:
    def __init__(self):
        self.calls: list[list[str]] = []
        self.identities: dict[str, tuple[str, str, str] | None] = {}
        self.statuses: dict[str, str] = {}
        self.rev_counts: dict[str, str] = {}     # NEW: path -> unpushed commit count
        self.failures: dict[str, str] = {}

    async def __call__(self, args: list[str]) -> tuple[int, str]:
        self.calls.append(args)
        path = args[1] if len(args) > 1 and args[0] == "-C" else ""
        command = args[2] if len(args) > 2 else ""
        # NEW: check failures FIRST so a test can make status/rev-list exit nonzero.
        # Previously the status branch returned before failures was consulted, so
        # the fail-closed paths were untestable.
        failure = self.failures.get(command)
        if failure is not None:
            return 1, failure
        if command == "rev-parse":
            identity = self.identities.get(path)
            if identity is None:
                return 128, "fatal: not a git repository"
            return 0, "\n".join(identity) + "\n"
        if command == "status":
            return 0, self.statuses.get(path, "")
        if command == "rev-list":                # NEW
            return 0, self.rev_counts.get(path, "0") + "\n"
        return 0, ""
```

`rev_counts` **must default to `"0"`**, not to the `return 0, ""` fall-through. An empty string is not `"0"`, so a bare fall-through would read as "unpushed work present" and every release test below would retain instead of release — a fixture that silently inverts the whole task. Run the existing suite after this change alone and confirm it is still green before writing new tests; moving the `failures` check first is a behaviour change to a shared fixture.

`test_reclaim_releases_non_working_item_without_live_owner` (`:211`) and `test_reclaim_retains_non_working_item_with_live_owner` (`:236`) both `monkeypatch.setattr(github_dispatch_service, "slot_has_live_owner_session", ...)`. That attribute will not exist. Rewrite them as the five cases of the conjunction:

```python
@pytest.fixture
def dead_owner(monkeypatch):
    """Make the recorded owner pid provably dead for the whole test.

    Correction (2026-08-03): an earlier draft encoded 'dead' as the literal pid
    4194303. pid_max here is 4194304, so that pid is legal and allocatable — on
    the day the host assigns it, every release test below would flip to 'retain'
    and the suite would report the backstop as working while it released
    nothing. Patch the class so any service instance in the test is covered.
    """
    def _dead(self, pid):
        raise ProcessLookupError()

    monkeypatch.setattr(GithubWorkspaceService, "_read_proc_start", _dead)


def _stale_lease(scope, tmp_path, item, **overrides):
    """A lease that satisfies every RELEASE condition unless overridden."""
    fields = dict(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        leased_item_id=item.id,
        leased_at=datetime.utcnow() - timedelta(seconds=25000),  # > 6h
        lease_token="t1",
        leased_owner_pid=123456,           # dead via the dead_owner fixture
        leased_owner_proc_start="123",
        lease_last_owner_contact_at=None,  # never spoke
    )
    fields.update(overrides)
    return GithubWorkspace(**fields)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["escalated", "failed", "merged", "completed"])
async def test_reclaim_releases_dead_silent_clean_lease(db, tmp_path, dead_owner, status):
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = status
    db.add(_stale_lease(scope, tmp_path, item))
    await db.commit()

    count = await GithubWorkspaceService(runner=FakeGitRunner()).reclaim_stale(db, scope)

    assert count == 1


@pytest.mark.asyncio
async def test_reclaim_retains_lease_with_live_owner_process(db, tmp_path):
    """Deliberately does NOT request the dead_owner fixture — it needs the real
    /proc read against a genuinely live process (this one). Do not add
    dead_owner here 'for consistency'; it would invert the test."""
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = "escalated"
    service = GithubWorkspaceService(runner=FakeGitRunner())
    db.add(_stale_lease(
        scope, tmp_path, item,
        leased_owner_pid=os.getpid(),
        leased_owner_proc_start=service._read_proc_start(os.getpid()),
    ))
    await db.commit()

    assert await service.reclaim_stale(db, scope) == 0


@pytest.mark.asyncio
async def test_reclaim_retains_lease_within_threshold(db, tmp_path, dead_owner):
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = "escalated"
    db.add(_stale_lease(
        scope, tmp_path, item, leased_at=datetime.utcnow() - timedelta(seconds=60)
    ))
    await db.commit()

    assert await GithubWorkspaceService(runner=FakeGitRunner()).reclaim_stale(db, scope) == 0


@pytest.mark.asyncio
async def test_reclaim_retains_lease_with_dirty_tree(db, tmp_path, dead_owner):
    """Git-quiescence is a VETO, never a cause (spec §3.2).

    Deck must not discard uncommitted work its own sweep can see.
    """
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = "escalated"
    runner = FakeGitRunner()
    runner.statuses[str(tmp_path / "ws")] = " M src/foo.c\n"
    db.add(_stale_lease(scope, tmp_path, item))
    await db.commit()

    assert await GithubWorkspaceService(runner=runner).reclaim_stale(db, scope) == 0


@pytest.mark.asyncio
async def test_reclaim_retains_lease_with_unpushed_commits(db, tmp_path, dead_owner):
    """A CLEAN tree can still hold the agent's whole deliverable.

    Verified 2026-08-03: an agent that commits locally without pushing leaves
    `git status --porcelain` EMPTY. The next acquire runs reset --hard + clean
    -fd, so releasing here discards committed work with reflog-only recovery.
    Committed-but-unpushed is the normal state between starting an item and
    opening its PR, so this is the common case, not an edge one.
    """
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = "escalated"
    runner = FakeGitRunner()
    runner.statuses[str(tmp_path / "ws")] = ""        # clean, deliberately
    runner.rev_counts[str(tmp_path / "ws")] = "3"     # three unpushed commits
    db.add(_stale_lease(scope, tmp_path, item))
    await db.commit()

    assert await GithubWorkspaceService(runner=runner).reclaim_stale(db, scope) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_command", ["status", "rev-list"])
async def test_reclaim_retains_lease_when_quiescence_cannot_be_determined(
    db, tmp_path, dead_owner, failing_command
):
    """The veto fails CLOSED. An unreadable worktree counts as occupied.

    Same safe direction as an unknown pid in Task 2, and it matches the
    established contract at github_workspace_service.py:271-274, where a
    nonzero `status` exit raises rather than being read as clean.
    """
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = "escalated"
    runner = FakeGitRunner()
    runner.failures[failing_command] = "fatal: not a git repository"
    db.add(_stale_lease(scope, tmp_path, item))
    await db.commit()

    assert await GithubWorkspaceService(runner=runner).reclaim_stale(db, scope) == 0


@pytest.mark.asyncio
async def test_reclaim_checks_unpushed_commits_against_the_scope_base_ref(db, tmp_path, dead_owner):
    """The comparison point is the scope's base_ref, not a hardcoded branch.

    base_ref is per-scope and defaults to origin/HEAD (database.py:225).
    Diffing against the wrong ref would count every commit on the base branch
    as 'unpushed' and wedge the backstop permanently — Finding 19's shape.
    """
    scope, _, item = await _context(db, tmp_path / "repo")
    scope.base_ref = "origin/feature/integration"
    item.dispatch_status = "escalated"
    runner = FakeGitRunner()
    db.add(_stale_lease(scope, tmp_path, item))
    await db.commit()

    await GithubWorkspaceService(runner=runner).reclaim_stale(db, scope)

    rev_list = [c for c in runner.calls if len(c) > 2 and c[2] == "rev-list"]
    assert rev_list, "the conjunction never checked for unpushed commits"
    assert "origin/feature/integration..HEAD" in rev_list[0]


@pytest.mark.asyncio
async def test_reclaim_retains_lease_with_recent_owner_contact(db, tmp_path, dead_owner):
    """A REPLACEMENT owner must not be mistaken for a dead one (spec §3.2a).

    The recorded pid is dead because the session restarted; the agent resumed
    the item under a new process and is still reporting. Releasing here would
    reset --hard under a live agent — the backstop as the weapon.
    """
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = "escalated"
    db.add(_stale_lease(
        scope, tmp_path, item,
        lease_last_owner_contact_at=datetime.utcnow() - timedelta(seconds=60),
    ))
    await db.commit()

    assert await GithubWorkspaceService(runner=FakeGitRunner()).reclaim_stale(db, scope) == 0


@pytest.mark.asyncio
async def test_reclaim_releases_when_owner_contact_has_aged_out(db, tmp_path, dead_owner):
    """The complement of the test above: contact older than the threshold ages out."""
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = "escalated"
    db.add(_stale_lease(
        scope, tmp_path, item,
        lease_last_owner_contact_at=datetime.utcnow() - timedelta(seconds=25000),
    ))
    await db.commit()

    assert await GithubWorkspaceService(runner=FakeGitRunner()).reclaim_stale(db, scope) == 1


@pytest.mark.asyncio
async def test_reclaim_never_touches_a_leased_primary_workspace(db, tmp_path, dead_owner):
    """The conjunction is defined for WORKTREE workspaces (spec §3.2).

    A primary checkout is a human's working tree; git status there says nothing
    about Deck's leases.
    """
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = "escalated"
    db.add(_stale_lease(scope, tmp_path, item, kind="primary"))
    await db.commit()

    assert await GithubWorkspaceService(runner=FakeGitRunner()).reclaim_stale(db, scope) == 0


@pytest.mark.asyncio
async def test_ready_for_review_is_not_reclaimable(db, tmp_path, dead_owner):
    """M12's guard, owed from PR A §6.

    ready_for_review is a real dispatch_status (github_verification_service.py:102)
    and is correctly absent from _RECLAIMABLE_STATUSES. This test pins that
    omission as a decision rather than an accident — exclusion lists are
    systematically under-tested.
    """
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = "ready_for_review"
    db.add(_stale_lease(scope, tmp_path, item))
    await db.commit()

    assert await GithubWorkspaceService(runner=FakeGitRunner()).reclaim_stale(db, scope) == 0
```

Add `from datetime import datetime, timedelta` and `import os` to the test imports as needed.

- [ ] **Step 2: Delete the obsolete dispatch test**

Delete `test_queued_owner_session_dispatches_after_session_goes_offline` (`test_github_dispatch_service.py:1299`). It tests the `queued_owner_session_live` queue state, which ceases to exist in Step 4.

- [ ] **Step 3: Run and watch them fail**

Run: `python -m pytest tests/agent_teams/test_github_workspace_service.py -k reclaim -v`
Expected: FAIL — the parametrized release test finds `count == 1` only by accident of the old gate; the retain tests fail because no conjunction exists yet.

- [ ] **Step 4: Implement the conjunction**

Replace `reclaim_stale` (`:121-146`) with:

```python
    async def reclaim_stale(self, db: AsyncSession, scope: TeamGithubScope) -> int:
        """Release leases whose owner is provably gone.

        Five conditions, ALL required. They fail in opposite directions — a
        stale pid resolving to an unrelated live process says 'alive' and costs
        throughput; a clean tree says 'idle' and could cost a working agent's
        checkout. Requiring all five means any disagreement retains the lease,
        so the safe error dominates.

        This replaces PR A's single slot_has_live_owner_session gate, which
        Finding 19 showed is permanently TRUE under one-session-per-slot — the
        sweep released 0 forever. See design §1.2 and §3.2.
        """
        threshold = datetime.utcnow() - timedelta(
            seconds=settings.github_stale_lease_backstop_seconds
        )
        leased = (
            await db.execute(
                select(GithubWorkspace, GithubWorkItem)
                .join(GithubWorkItem, GithubWorkspace.leased_item_id == GithubWorkItem.id)
                .where(
                    GithubWorkspace.scope_id == scope.id,
                    GithubWorkItem.dispatch_status.in_(_RECLAIMABLE_STATUSES),
                )
                .order_by(GithubWorkspace.id)
            )
        ).all()
        released = 0
        for workspace, item in leased:
            # A leased primary is a human's working tree; git status there says
            # nothing about Deck's leases. Retain unconditionally.
            if workspace.kind == "primary":
                continue
            if workspace.leased_at is None or workspace.leased_at > threshold:
                continue
            if self._owner_process_is_alive(workspace):
                continue
            # A replacement owner reports; a crashed one goes quiet and ages out.
            if (
                workspace.lease_last_owner_contact_at is not None
                and workspace.lease_last_owner_contact_at > threshold
            ):
                continue
            if not await self._worktree_is_quiescent(scope, workspace):
                continue
            await self.release(db, workspace.leased_item_id)
            released += 1
        return released

    async def _worktree_is_quiescent(
        self, scope: TeamGithubScope, workspace: GithubWorkspace
    ) -> bool:
        """A veto, never a cause: it can only prevent a release.

        TWO checks, because a clean tree is not an empty one. An agent that
        committed its work and has not pushed leaves `status --porcelain` empty
        (verified 2026-08-03), and the next acquire would reset --hard it away.
        So unpushed commits veto the release too.

        Every failure path returns False. An unreadable worktree counts as
        occupied — the same safe direction as an unknown pid in
        _owner_process_is_alive, and the same contract as the adoption check at
        :271-274, which raises on a nonzero `status` exit rather than reading
        the empty output as clean.
        """
        return_code, output = await self._runner(
            ["-C", workspace.path, "status", "--porcelain"]
        )
        if return_code != 0:
            return False
        if output.strip():
            return False

        return_code, output = await self._runner(
            ["-C", workspace.path, "rev-list", "--count", f"{scope.base_ref}..HEAD"]
        )
        if return_code != 0:
            return False
        return output.strip() == "0"
```

Add `from datetime import datetime, timedelta` and `from app.config import settings` to the module imports.

Note condition 4 as implemented is "no contact, **or** contact older than the threshold" — expressed as "skip if contact is *recent*". That matches spec §3.2a exactly.

Note also that `_worktree_is_quiescent` takes `scope`, not just `workspace`: `base_ref` lives on the scope (`database.py:225`, default `origin/HEAD`) and is per-scope, so it cannot be a module constant. `reclaim_stale` already has `scope` in hand.

The `return output.strip() == "0"` on the last line is deliberately a positive test rather than `!= "0"` being falsy-tolerant: if `rev-list` ever succeeds with empty output, `"" == "0"` is False, so the lease is retained. Unparseable output must not read as "no work".

- [ ] **Step 5: Delete the predicate and its dispatch gate**

In `github_dispatch_service.py`:
- Delete the `slot_has_live_owner_session` method (starts `:114`).
- Delete its gate in `dispatch_pending` (`:215-221`) — the whole `if await self.slot_has_live_owner_session(...)` block including the `queued_owner_session_live` assignment.

Keep `slot_is_busy` untouched. It is the logical one-item-per-slot guard and it was always correct (spec §2.2).

Grep for both names across `backend/` afterwards to catch any remaining reference:
`grep -rn "slot_has_live_owner_session\|queued_owner_session_live" backend/app backend/tests backend/mcp_shim frontend/src`

Frontend may reference the pending reason string for display; if so, remove that branch too.

- [ ] **Step 6: Run everything**

Run: `python -m pytest tests/agent_teams/ -q`
Expected: green. Count changes — you deleted 1 test and the parametrized rewrite adds cases.

- [ ] **Step 7: Commit**

```bash
git add -A backend frontend
git commit -m "feat(g2)!: replace the liveness gate with a five-condition conjunction

Deletes slot_has_live_owner_session. Finding 19: under one-session-per-slot the
slot's session is alive permanently BY DESIGN, so the predicate PR A made the
only releaser was permanently true and reclaim_stale released 0 forever. The
first terminal item wedged the pool.

Release now requires all of: reclaimable status, lease older than the backstop
threshold, recorded owner process dead, no recent owner contact on this lease,
clean worktree. The signals fail in opposite directions, so requiring all five
makes the safe error (retain) dominate.

Condition 4 (owner contact) is what distinguishes a REPLACEMENT owner from a
dead one without asking 'is the slot alive?' — which would rebuild Finding 19
inside its own fix.

Also adds M12's owed guard test: ready_for_review is not reclaimable."
```

---

### Task 5: The deferred retry — `retry_requested_at`

**Files:**
- Modify: `backend/app/services/github_dispatch_service.py:38-49` (`reset_for_retry`), plus a new `promote_deferred_retries`
- Modify: `backend/app/services/github_watcher_service.py:28-45` (`poll_scope`)
- Modify: `backend/app/services/github_verification_service.py:60-61` (`report_pr_opened`'s recoverable branch)
- Modify: `backend/app/models/schemas.py:2255-2281` (`GithubWorkItemResponse`)
- Modify: `backend/app/api/v1/agent_teams.py:645-671` (retry endpoint), and `_work_item_response`
- Test: `backend/tests/agent_teams/test_github_dispatch_service.py:377`, plus new tests

**Interfaces:**
- Consumes: Task 1's `retry_requested_at`, Task 3's token.
- Produces: `github_dispatch_service.promote_deferred_retries(db, scope) -> int`, called from `poll_scope`.

Implements spec §3.1a-bis in full. **Read that section before starting — all of it.** It documents a trap that the obvious implementation walks into.

- [ ] **Step 1: Rewrite the test that asserts the old behaviour**

`test_reset_for_retry_does_not_release_workspace` (`test_github_dispatch_service.py:377`) currently asserts `item.dispatch_status == "pending"` **with the lease still held** — the exact state this task makes unreachable. Its name and its lease assertion stay true; only the status assertion inverts:

```python
@pytest.mark.asyncio
async def test_reset_for_retry_defers_while_a_lease_is_held(db):
    """Retry must not overtake release (spec §3.1a-bis).

    Flipping straight to 'pending' both locks the legitimate releaser out (a
    non-terminal item cannot release, §3.1c) and lets the next acquire() return
    the EXISTING lease via its early return — so no token is minted and
    reset_workspace never runs. The new owner silently inherits a dirty tree.
    That silent reset skip, not the wedge, is the real harm.
    """
    _, _, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=909,
        issue_title="retry",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="escalated",
        escalation_reason="plan_blocked",
    )
    db.add(item)
    await db.flush()
    workspace = (
        await db.execute(
            select(GithubWorkspace)
            .where(GithubWorkspace.scope_id == scope.id)
            .order_by(GithubWorkspace.id)
        )
    ).scalars().first()
    workspace.leased_item_id = item.id
    await db.commit()

    github_dispatch_service.reset_for_retry(item)
    await db.commit()

    assert item.dispatch_status == "escalated"
    assert item.retry_requested_at is not None
    assert workspace.leased_item_id == item.id
    # escalation_reason is load-bearing while the item stays escalated
    assert item.escalation_reason == "plan_blocked"
```

- [ ] **Step 2: Write the new tests**

```python
@pytest.mark.asyncio
async def test_reset_for_retry_without_a_lease_is_unchanged(db):
    """The common path must not change (spec §3.1a-bis)."""
    _, _, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=910,
        issue_title="retry",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="escalated",
        escalation_reason="plan_blocked",
        ack_received_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()

    github_dispatch_service.reset_for_retry(item)

    assert item.dispatch_status == "pending"
    assert item.retry_requested_at is None
    assert item.escalation_reason is None
    assert item.ack_received_at is None


@pytest.mark.asyncio
async def test_promote_deferred_retry_after_release(db):
    """Once the lease is gone the deferred reset applies in full."""
    _, _, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=911,
        issue_title="retry",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="escalated",
        escalation_reason="plan_blocked",
        retry_requested_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()

    promoted = await github_dispatch_service.promote_deferred_retries(db, scope)

    assert promoted == 1
    assert item.dispatch_status == "pending"
    assert item.retry_requested_at is None
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_promote_deferred_retry_waits_for_the_lease(db):
    _, _, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=912,
        issue_title="retry",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="escalated",
        retry_requested_at=datetime.utcnow(),
    )
    db.add(item)
    await db.flush()
    workspace = (
        await db.execute(
            select(GithubWorkspace)
            .where(GithubWorkspace.scope_id == scope.id)
            .order_by(GithubWorkspace.id)
        )
    ).scalars().first()
    workspace.leased_item_id = item.id
    await db.commit()

    assert await github_dispatch_service.promote_deferred_retries(db, scope) == 0
    assert item.dispatch_status == "escalated"
```

Also write, in `test_github_verification_service.py` (or wherever `report_pr_opened` is tested), a test that a recoverable escalated item with `retry_requested_at` set has it **cleared** by `report_pr_opened` — otherwise a stamp left behind re-pends the item the next time it escalates, weeks later, as a re-dispatch nobody requested.

- [ ] **Step 2b: The five full-flow tests from spec §5.2 — do not skip these**

**Correction (2026-08-03, impl-agent review): the unit tests above are necessary but not sufficient.** They each poke one function. Spec §5.2 (`:817-847`) specifies five *flow* tests, and it names the first one "the highest-value test in this PR" — because the defect this task fixes is not visible in any single function. `reset_for_retry` looks correct in isolation; the harm emerges from the composition (re-pend → non-terminal → release refused → `acquire` early-return → **`reset_workspace` never runs** → new owner inherits a dirty tree). A suite that only unit-tests the parts would stay green through a regression that restores the whole defect.

Write all five. The first, in full, because its assertions are the specification:

```python
@pytest.mark.asyncio
async def test_retry_does_not_overtake_release_end_to_end(db, monkeypatch):
    """Spec §5.2: the highest-value test in this PR.

    The load-bearing assertion is that reset_workspace NEVER RAN. Everything
    else here can be right while isolation is silently lost: acquire()'s early
    return hands back the existing lease, so a new owner starts on the previous
    attempt's tree with no error anywhere.
    """
    _, _, scope = await _team(db)
    resets: list[str] = []

    async def _spy_reset(db_, scope_, workspace_):
        resets.append(workspace_.path)

    monkeypatch.setattr(github_workspace_service, "reset_workspace", _spy_reset)

    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=913,
        issue_title="retry flow",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    workspace = await github_workspace_service.acquire(db, scope, item)
    first_token = workspace.lease_token
    assert first_token is not None
    assert resets == [workspace.path]          # a real acquisition DOES reset

    item.dispatch_status = "escalated"
    item.escalation_reason = "plan_blocked"
    await db.commit()

    # Re-pend the way production does it: via the watcher, no human involved.
    github_dispatch_service.reset_for_retry(item)
    await db.commit()

    assert item.dispatch_status == "escalated"          # still not dispatchable
    assert item.retry_requested_at is not None
    assert workspace.leased_item_id == item.id          # lease STILL HELD
    assert workspace.lease_token == first_token         # and on the SAME token
    assert await github_dispatch_service.promote_deferred_retries(db, scope) == 0
    assert resets == [workspace.path]                   # <-- NO second reset

    # Now the legitimate owner releases, and only then does the retry proceed.
    await github_workspace_service.release_by_token(
        db, item.id, lease_token=first_token
    )
    assert await github_dispatch_service.promote_deferred_retries(db, scope) == 1
    assert item.dispatch_status == "pending"
    assert item.retry_requested_at is None

    reacquired = await github_workspace_service.acquire(db, scope, item)
    assert reacquired.lease_token != first_token        # a NEW attempt
    assert len(resets) == 2                             # and it DID reset
```

`_team` provisions the scope's workspace; check the existing fixture's shape and adapt the `acquire` call if it needs a `FakeGitRunner`-backed service instance rather than the module singleton — `acquire` calls `reset_workspace`, which shells out to git, so the spy above is what keeps this a unit test.

Then the remaining four from spec §5.2 (`:825-847`), one test each:

1. **Via the watcher, not the operator.** Same flow, but trigger the re-pend through watcher reconcile with an advanced `github_updated_at` (`github_watcher_service.py:74-78`) instead of calling `reset_for_retry`. The point of the finding is that no human is involved, so a test that calls the function directly cannot see it. Companion case: the manual `POST .../retry` endpoint reaches the same deferred state.
2. **`escalation_reason` survives, and recovery still works.** Escalate `plan_blocked`, lease held, request retry → assert `escalation_reason` is **unchanged**, then assert `report_pr_opened` still succeeds through `_PR_OPENED_RECOVERABLE_ESCALATIONS` (`github_verification_service.py:50-59`). Companion: a re-escalation while the stamp is set still no-ops and leaves `status_note` intact (`_apply_escalation`'s guard, `github_dispatch_service.py:774-779`). This pair pins the trap a status-only deferral walks into — which is *why* the whole reset defers rather than just the status.
3. **Recovery clears the stamp.** Stamp set, lease held, owner reports `pr_opened` → `retry_requested_at` is NULL afterwards. Without this, a stamp left behind re-pends the item at its next unrelated escalation.
4. **The sweep is not inside `dispatch_pending` — scheduler level.** Promote via `poll_scope`, run a **full scheduler pass**, and assert the retried item's `routing_method` is `"label"` (not `"leader_fallback"`) for an issue carrying a slot's `area_labels`. Only a scheduler-level test can see this; the unit tests above would pass with the sweep in the wrong place. This is the regression Step 6's placement exists to avoid.

If any of these five cannot be written because a fixture does not reach that far, **stop and report which one** rather than substituting a unit test for it. A missing flow test here is how the defect returns.

- [ ] **Step 3: Run and watch them fail**

Run: `python -m pytest tests/agent_teams/test_github_dispatch_service.py -k retry -v`
Expected: FAIL

- [ ] **Step 4: Make `reset_for_retry` conditional**

It is currently synchronous and takes only the item. It now needs to know whether a lease is held, so it becomes async and takes the session:

```python
    async def reset_for_retry(self, db: AsyncSession, item: GithubWorkItem) -> None:
        """Request re-dispatch. Defers if the item still holds a workspace lease.

        While a lease is held this mutates NOTHING but retry_requested_at,
        status_note and updated_at. Clearing escalation_reason here would break
        two things, because that field is load-bearing while the item stays
        'escalated':

          1. report_pr_opened treats an escalated item as recoverable only when
             escalation_reason is in _PR_OPENED_RECOVERABLE_ESCALATIONS. A
             cleared reason makes the owner's pr_opened report raise instead of
             recovering — the retry request would destroy the very recovery
             path the owner was about to use.
          2. _apply_escalation's idempotence guard is
             `dispatch_status == "escalated" and escalation_reason`. A cleared
             reason turns a no-op re-escalation into one that overwrites
             status_note, discarding the operator's original context.

        See design §3.1a-bis.
        """
        held = (
            await db.execute(
                select(GithubWorkspace).where(GithubWorkspace.leased_item_id == item.id)
            )
        ).scalar_one_or_none()
        now = datetime.utcnow()
        if held is not None:
            item.retry_requested_at = now
            item.status_note = (
                "Re-dispatch requested; waiting for the current owner to release "
                f"workspace {held.path}."
            )
            item.updated_at = now
            return
        item.dispatch_status = "pending"
        item.escalation_reason = None
        item.pending_reason = None
        item.handoff_state = None
        item.handoff_target_slot_id = None
        item.pr_number = None
        item.ack_received_at = None
        item.last_verified_sha = None
        item.retry_count = 0
        item.approval_round_count = 0
        item.retry_requested_at = None
        item.updated_at = now
```

Update both callers to `await`:
- `github_watcher_service.py:78` → `await github_dispatch_service.reset_for_retry(db, existing)`
- `agent_teams.py:666` → `await github_dispatch_service.reset_for_retry(db, item)`

- [ ] **Step 5: Add the promotion sweep**

Add to `GithubDispatchService`:

```python
    async def promote_deferred_retries(self, db: AsyncSession, scope: TeamGithubScope) -> int:
        """Complete deferred retries whose lease has since been released."""
        candidates = (
            await db.execute(
                select(GithubWorkItem)
                .outerjoin(GithubWorkspace, GithubWorkspace.leased_item_id == GithubWorkItem.id)
                .where(
                    GithubWorkItem.scope_id == scope.id,
                    GithubWorkItem.dispatch_status.in_(("escalated", "failed")),
                    GithubWorkItem.retry_requested_at.is_not(None),
                    GithubWorkspace.id.is_(None),
                )
                .order_by(GithubWorkItem.id)
            )
        ).scalars().all()
        for item in candidates:
            await self.reset_for_retry(db, item)
        if candidates:
            await db.commit()
        return len(candidates)
```

Calling `reset_for_retry` here is deliberate: the lease is gone, so it takes the immediate branch and applies the full reset — one definition of "what a retry does", not two.

- [ ] **Step 6: Call the sweep from `poll_scope`, not from `dispatch_pending`**

In `github_watcher_service.py`, in `poll_scope`, before `scope.last_polled_at = ...` (`:44`):

```python
        await github_dispatch_service.promote_deferred_retries(db, scope)
```

**Not in `dispatch_pending`, and this matters.** `github_dispatch_scheduler.py:132` fetches issue labels and details for `pending` items **before** calling `dispatch_pending` at `:137`. An item promoted inside `dispatch_pending` would be routed with an empty label set — falling through `route_item`'s label branch to `leader_fallback` (`:64-76`) — and briefed with `issue_details=None`. A retried item would silently route worse than a fresh one. `poll_scope` runs at `:124`, before the label fetch.

Cost: a lease released by the *backstop* (which runs inside `dispatch_pending`, after the sweep) is promoted on the following poll. One interval of latency on a path that already waited 6h.

- [ ] **Step 7: Clear the stamp on legitimate recovery**

In `github_verification_service.py`, in `report_pr_opened`'s recoverable branch (`:60-61`):

```python
        if recoverable:
            item.escalation_reason = None
            item.retry_requested_at = None
```

- [ ] **Step 8: Surface it on the API**

Add `retry_requested_at: Optional[datetime] = None` to `GithubWorkItemResponse` (`schemas.py:2255-2281`) and populate it in `_work_item_response` in `agent_teams.py`. Without this, `POST .../retry` returns an item still reading `escalated` and looks like it did nothing.

- [ ] **Step 9: Run everything**

Run: `python -m pytest tests/agent_teams/ -q`
Expected: green.

- [ ] **Step 10: Commit**

```bash
git add -A backend
git commit -m "feat(g2): defer retry until the workspace lease is released

reset_for_retry no longer flips straight to 'pending' when a lease is held.
Composed with terminal-only release, that deadlocked: the watcher re-pends an
escalated item on any issue comment, the item leaves terminal status, the
legitimate owner's release is refused, and acquire()'s early return hands back
the EXISTING lease — so no token is minted and reset_workspace never runs. The
new owner inherits the previous attempt's dirty tree. The silent reset skip,
not the wedge, is the harm.

Uses a nullable retry_requested_at rather than a new dispatch_status: escalated
is already terminal-for-release, already reclaimable, and already
non-dispatchable, so all three needed properties come free and no state-machine
or UI change is required.

While a lease is held the reset defers ENTIRELY — clearing escalation_reason
would break report_pr_opened's recovery path and _apply_escalation's
idempotence guard, both of which read that field while the item stays
escalated.

The promotion sweep runs in poll_scope, not dispatch_pending: the scheduler
fetches issue labels for pending items before calling dispatch_pending, so an
item promoted there would route by leader_fallback instead of by label."
```

---

### Task 6: The `workspace_released` report

**Files:**
- Modify: `backend/app/models/schemas.py:2327-2333` (`DispatchStatusReport`)
- Modify: `backend/app/api/v1/agent_teams.py:267-323` (`report_dispatch_status`)
- Modify: `backend/app/services/github_workspace_service.py` (new `release_by_token`)
- Modify: `backend/app/services/github_dispatch_service.py` (`_dispatch_brief`)
- Modify: `backend/mcp_shim/agent_mail_server.py` (the `deck_report_dispatch_status` docstring/params)
- Test: `backend/tests/agent_teams/` (API-level tests — find the file that exercises `/dispatch-status`)

**Interfaces:**
- Consumes: Task 3's token, Task 5's deferral.
- Produces: `github_workspace_service.release_by_token(db, item_id, *, lease_token) -> None`, raising `ValueError` on mismatch; report status `workspace_released`.

Implements spec §3.1 (the report), §3.1a (token matching), §3.1c (when release is legal), §3.2a (stamping owner contact).

- [ ] **Step 1: Write the failing tests**

Cover all six behaviours. Find the existing `/dispatch-status` test file first (`grep -rln "dispatch-status" backend/tests/`) and follow its client fixture pattern:

1. Owner slot releases a `merged` item with the correct token → 200, `leased_item_id` is None.
2. **Non-owner** slot reports `workspace_released` → 409, lease retained.
3. Wrong token → 409, lease retained, response names the mismatch.
4. Repeat of the same token after release → 200 (idempotent), no error.
5. Release while `dispatch_status == "dispatched"` → 409 naming the current status, lease retained. Repeat for `verifying` and `ready_for_review`.
6. Release with a **dirty** tree (`FakeGitRunner().statuses[...] = " M src/foo.c\n"`) on an `escalated` item → 409, lease retained, response names the dirty paths. Pair with the clean-tree case → 200.
7. A `failed` item **with a live pane** can release → 200. Dispatch retains the lease on a failed launch when `tmux_target` is not None (`github_dispatch_service.py:282-285`) precisely because something may be running in it, so that state must have a release path.
8. Any **other** report status (`triaging`) **carrying the current token** stamps `lease_last_owner_contact_at` on the workspace row.
9. A `triaging` report carrying a **stale** token leaves `lease_last_owner_contact_at` unchanged **and still applies its own status change** (assert `status_note` was written). Stale evidence must not extend a lease, and refusing the evidence must not fail the report.
10. Release with a clean tree but **unpushed commits** (`runner.rev_counts[...] = "2"`) on a `merged` item → 409, lease retained, message names the base ref. This is the same veto as Task 4's backstop, reached through the agent instead of the sweep; both paths must refuse.
11. Release when `git status` **errors** (`runner.failures["status"] = "fatal: ..."`) → 409, lease retained. The veto fails closed here exactly as it does in the backstop.

- [ ] **Step 2: Run and watch them fail**

Expected: FAIL — `400 unknown status workspace_released`

- [ ] **Step 3: Add `lease_token` to the report schema**

```python
class DispatchStatusReport(BaseModel):
    work_item_id: int
    status: str
    pr_number: Optional[int] = None
    reassign_to_slot_id: Optional[int] = None
    note: Optional[str] = None
    reporting_slot_id: Optional[int] = None
    lease_token: Optional[str] = None
```

It stays `Optional` at the schema level even though release requires it, because the same model serves every report status and pre-G2 callers omit it. The **endpoint** enforces presence for `workspace_released` (Step 5); the contact stamp treats absence as "no evidence to record" rather than an error (Step 6). Two different contracts on one optional field, deliberately — an acting operation must reject an unproven claim, a recording one may only decline to record.

- [ ] **Step 4: Implement `release_by_token`**

In `github_workspace_service.py`:

```python
    async def release_by_token(
        self, db: AsyncSession, item_id: int, *, lease_token: str
    ) -> None:
        """Release only the acquisition the token names.

        release() keys on leased_item_id alone, so it cannot tell one dispatch
        attempt of an item from the next — a stale report from attempt 1 would
        return attempt 2's live lease, and the next acquire would reset --hard
        under a working agent (design §3.1a).

        Idempotent when nothing is leased: a duplicated report is harmless.
        """
        workspace = (
            await db.execute(
                select(GithubWorkspace).where(GithubWorkspace.leased_item_id == item_id)
            )
        ).scalar_one_or_none()
        if workspace is None:
            return
        if workspace.lease_token != lease_token:
            raise GithubWorkspaceLeaseTokenMismatch(
                f"lease_token does not match the current lease for item {item_id}"
            )
        await self.release(db, item_id)
```

Add the exception beside the existing ones at the top of the module:

```python
class GithubWorkspaceLeaseTokenMismatch(GithubWorkspaceError):
    def __init__(self, message: str):
        super().__init__(message, "lease_token_mismatch")
```

- [ ] **Step 5: Add the endpoint branch**

In `agent_teams.py`, in `report_dispatch_status`, before the final `else`:

```python
    elif report.status == "workspace_released":
        if report.reporting_slot_id != item.owner_slot_id:
            raise HTTPException(
                status_code=409,
                detail="only the owner slot may release its workspace",
            )
        if report.lease_token is None:
            raise HTTPException(status_code=400, detail="lease_token required")
        # Release is GATED BY dispatch_status but never MOVES it. A non-terminal
        # item can still be sent back for more work (a failed check reopens a
        # verified SHA, an approval round asks for changes), and an owner that
        # released early would need a workspace it no longer holds. §3.1c
        if item.dispatch_status not in _RELEASABLE_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"workspace cannot be released while the item is "
                    f"{item.dispatch_status}; release is legal only from "
                    f"{', '.join(_RELEASABLE_STATUSES)}"
                ),
            )
        workspace = await github_workspace_service.get_leased_workspace(db, item.id)
        if workspace is not None:
            blocker = await github_workspace_service.release_blocker(scope, workspace)
            if blocker is not None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"workspace will not be released: {blocker}. Commit and "
                        "push, or report the situation in status_note and leave "
                        "the lease held."
                    ),
                )
        try:
            await github_workspace_service.release_by_token(
                db, item.id, lease_token=report.lease_token
            )
        except GithubWorkspaceLeaseTokenMismatch as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
```

Define at module scope in **`github_dispatch_service.py`**, beside `_BUSY_STATUSES` (`:25`), and import it into `agent_teams.py`:

```python
# Release is legal only from a state that is terminal FOR THE OWNER. `failed`
# is included deliberately: dispatch retains the lease on a failed launch when
# a pane was created (github_dispatch_service.py:282-285), and the agent in
# that pane is the one entity that knows whether it is doing anything.
_RELEASABLE_STATUSES = ("merged", "completed", "escalated", "failed")
```

It goes in the service, not the endpoint, because Task 8 also needs it and the API layer already imports from the service — defining it in `agent_teams.py` would force the reverse import.

Add two helpers to `github_workspace_service.py`. `get_leased_workspace(db, item_id)` returns the row or None. `release_blocker(scope, workspace)` is the **human-readable** side of the same veto Task 4 uses, so the two cannot drift apart:

```python
    async def release_blocker(
        self, scope: TeamGithubScope, workspace: GithubWorkspace
    ) -> str | None:
        """Why this workspace must not be released, or None if it may be.

        The same two-part veto as _worktree_is_quiescent (Task 4), but it names
        the blocker so the agent's 409 can say what to fix. Both must stay in
        agreement: protecting work from Deck's own sweep while letting an agent
        discard it by reporting has no justification.

        Fails CLOSED — an unreadable worktree blocks the release.
        """
        if workspace.kind == "primary":
            return None      # never leased; must not inspect a human's tree

        return_code, output = await self._runner(
            ["-C", workspace.path, "status", "--porcelain"]
        )
        if return_code != 0:
            return output.strip() or "workspace status could not be determined"
        if output.strip():
            return f"uncommitted or untracked changes:\n{output.strip()}"

        return_code, output = await self._runner(
            ["-C", workspace.path, "rev-list", "--count", f"{scope.base_ref}..HEAD"]
        )
        if return_code != 0:
            return output.strip() or "unpushed commits could not be determined"
        if output.strip() != "0":
            return (
                f"{output.strip()} commit(s) not pushed to {scope.base_ref}; "
                "the next dispatch would reset --hard them away"
            )
        return None
```

Note the reviewer's point applied here deliberately: the earlier draft returned a *string* of dirty paths and the endpoint tested its truthiness, so a nonzero `git` exit returned `""` → falsy → **release allowed on an unreadable worktree**. Returning `str | None` with an explicit message on every failure path removes that reading entirely. Write the test for it: `runner.failures["status"] = "fatal: ..."` on a `workspace_released` report must produce **409**, not a release.

- [ ] **Step 6: Stamp owner contact on every report**

Still in `report_dispatch_status`, after the branch chain and before `await db.refresh(item)`:

```python
    # "Has the thing holding THIS LEASE spoken recently?" — the question the
    # backstop actually needs (§3.2a). A replacement owner that resumed the item
    # reports; a crashed one goes quiet and ages out. Independent of tmux,
    # session discovery and last_seen_at, so Finding 17's staleness cannot
    # corrupt it.
    if report.status != "workspace_released" and report.reporting_slot_id == item.owner_slot_id:
        await github_workspace_service.touch_owner_contact(
            db, item.id, lease_token=report.lease_token
        )
```

**Correction (2026-08-03, impl-agent review): the stamp must be attempt-scoped, exactly like the release.** The draft stamped contact on any owner-slot report for the item. But `lease_last_owner_contact_at` is backstop **condition 4** — evidence that keeps a lease held. Item-scoped evidence on an attempt-scoped lease is Finding 18 again, and the direction is unsafe: a stale report from a *previous* attempt refreshes the *current* attempt's contact clock, so a genuinely dead owner's lease is held indefinitely and the backstop never fires. It is the same defect as `release()` keying on `leased_item_id`, arriving through the evidence rather than the action. Note the family: the token answers *which acquisition?*, and every signal feeding a lease decision has to answer that question rather than *which item?*

```python
    async def touch_owner_contact(
        self, db: AsyncSession, item_id: int, *, lease_token: str | None = None
    ) -> None:
        """Stamp owner contact on the lease, if the reporter holds it.

        No-op when nothing is leased. Also a no-op on a token mismatch, and
        DELIBERATELY not an error: this is a side effect of a report whose own
        branch already succeeded, so raising here would fail a legitimate
        status update. Release is the operation that must reject a stale token
        (release_by_token); recording evidence just declines to record.
        """
        workspace = await self.get_leased_workspace(db, item_id)
        if workspace is None:
            return
        if workspace.lease_token is not None and lease_token != workspace.lease_token:
            logger.info(
                "ignoring owner contact for item %s: token mismatch (lease is "
                "on a different attempt)",
                item_id,
            )
            return
        workspace.lease_last_owner_contact_at = datetime.utcnow()
        workspace.updated_at = workspace.lease_last_owner_contact_at
        await db.commit()
```

`github_workspace_service.py` has **no module logger** — verified 2026-08-03, unlike `github_dispatch_service.py:34`. Add the standard two lines at the top of the module:

```python
import logging

logger = logging.getLogger(__name__)
```

The `workspace.lease_token is not None` guard is what keeps pre-migration leases working: their token is NULL, they cannot be matched, and they are already unreclaimable by design (spec §3.2, `:526-528`), so refusing to stamp them changes nothing.

This makes `lease_token` **required for the contact stamp to work at all**, so the brief must carry it for every report, not only for release — which Step 7 already requires. Two tests:

- an owner report carrying the current token stamps `lease_last_owner_contact_at`;
- an owner report carrying a **stale** token leaves it unchanged, and the report's own branch still succeeds (assert the status change it was supposed to make actually happened).

The second test is the load-bearing one. Without it, a token mismatch that raised would look like correct strictness while breaking every legitimate report on a re-acquired workspace.

- [ ] **Step 7: Teach the brief to name the token**

In `_dispatch_brief` (`github_dispatch_service.py:295`), add a `workspace_released` instruction alongside the existing `triaging` / `pr_opened` / `blocked` ones. It **must** include `workspace.lease_token` verbatim — the agent cannot derive it. State that release is required once the item reaches a terminal state, that the tree must be committed and pushed first, and give the exact `deck_report_dispatch_status` call.

Update `deck_report_dispatch_status` in `backend/mcp_shim/agent_mail_server.py` to accept and forward `lease_token`.

- [ ] **Step 8: Run everything**

Run: `python -m pytest tests/agent_teams/ -q`
Expected: green.

- [ ] **Step 9: Commit**

```bash
git add -A backend
git commit -m "feat(g2): agent-reported workspace release, scoped to the attempt

Adds report status workspace_released. No new dispatch_status value — the
endpoint's triaging/ack_received/in_progress branches already set the precedent
for reports that do not move status.

Release names the TOKEN, not the item: release() keys on leased_item_id alone
and cannot tell one dispatch attempt from the next, so a stale report from a
previous attempt would return a live lease and the next acquire would reset
--hard under a working agent.

Gated by dispatch_status but never moves it. Legal only from merged, completed,
escalated or failed; 'failed' included because dispatch deliberately retains
the lease when a pane was created, and that agent is the only entity that knows
whether it is still working. Refused on a dirty tree — the same veto §3.2
applies to the backstop, since protecting uncommitted work from Deck's own
sweep while letting an agent discard it has no justification.

Every other owner report stamps lease_last_owner_contact_at, which is backstop
condition 4."
```

---

### Task 7: Finding 17 — observed rows resolve on their pid

**Files:**
- Modify: `backend/app/services/agent_mail_service.py:628-631`
- Test: `backend/tests/agent_mail/` (find the `_effective_status` tests)

**Interfaces:**
- Consumes: nothing from earlier tasks (independent; it is in PR1 because the skew test is owed from PR A §6).
- Produces: nothing consumed later.

Implements spec §2.4 — read it, including the two implementation notes at the end.

**Scope warning:** this is a display-accuracy fix. Nothing destructive hangs off the predicate any more (Task 4 removed that). Do not expand it.

- [ ] **Step 1: Write the failing tests — one per row of the table**

The load-bearing one is the **skew**: a live pid with an expired TTL. Fixtures hide this class of defect by construction, because every test supplies its own timestamps — so it must be built deliberately, not as a plainly-live or plainly-offline object.

**Correction (2026-08-03, impl-agent review): two fixture bugs in the draft, both of which would have produced a green-looking test that proves nothing.**

1. `provider="claude"` is **not** a wake provider. `TMUX_WAKE_PROVIDERS = {"claude-code", "codex-cli", "copilot-cli", "opencode-cli"}` (`agent_mail_service.py:44`) and `_session_can_nudge` requires `session.provider in TMUX_WAKE_PROVIDERS` (`:598`). With `"claude"` the assertion fails on the provider check, so the test would fail for a reason unrelated to the status literal it exists to pin — and "fix" by weakening the assertion. Use `provider="claude-code"`.
2. Liveness must be **monkeypatched**, not inferred from a chosen pid number. The draft used `pid=4194303` elsewhere as "dead" and `os.getpid()` as "alive". `os.getpid()` is genuinely fine, but a hardcoded dead pid is not: it is only dead until the host allocates it (`pid_max` is 4194304 here, so 4194303 is a legal, allocatable pid), and the test would then invert with no code change. Monkeypatch `_pid_is_running` for the dead cases.

```python
def test_observed_session_past_ttl_with_live_pid_reads_observed():
    """Finding 17: five live agents displayed as offline.

    last_seen_at is refreshed only by sync_observed_sessions, whose callers are
    all interactive — so the column reflects when a human last opened the Agent
    Mail page, not whether the agent is alive. Spec §2.4 row 2.
    """
    service = agent_mail_service
    now = datetime.utcnow()
    session = MailAgentSession(
        member_id=1,
        source="observed",
        mailbox_status="observed",
        pid=os.getpid(),          # genuinely alive: this test process
        last_seen_at=now - timedelta(seconds=OBSERVED_TTL_SECONDS + 60),
    )

    assert service._effective_status(session, now) == "observed"


def test_revived_observed_session_is_still_nudgeable():
    """The revived status must be the one _session_can_nudge accepts.

    _session_can_nudge requires _effective_status == "observed" EXACTLY
    (agent_mail_service.py:600). Reviving these rows as "connected" would make
    every one of them un-nudgeable — turning a display fix into a delivery
    outage, and silently defeating Task 13's ambiguity check.

    provider MUST be a member of TMUX_WAKE_PROVIDERS (:44) or this test fails
    on the provider check instead of on the status literal it exists to pin.
    """
    service = agent_mail_service
    now = datetime.utcnow()
    session = MailAgentSession(
        member_id=1,
        source="observed",
        provider="claude-code",       # in TMUX_WAKE_PROVIDERS; "claude" is NOT
        tmux_target="tizonia:1.0",
        mailbox_status="observed",
        pid=os.getpid(),
        last_seen_at=now - timedelta(seconds=OBSERVED_TTL_SECONDS + 60),
    )

    assert service._session_can_nudge(session, now) is True


def test_observed_session_past_ttl_with_dead_pid_reads_offline(monkeypatch):
    """Fails closed. Monkeypatched rather than using a 'probably unused' pid:
    any specific number is allocatable, and this test would silently invert
    the day the host assigns it."""
    service = agent_mail_service
    monkeypatch.setattr(service, "_pid_is_running", lambda pid: False)
    now = datetime.utcnow()
    session = MailAgentSession(
        member_id=1,
        source="observed",
        mailbox_status="observed",
        pid=123456,
        last_seen_at=now - timedelta(seconds=OBSERVED_TTL_SECONDS + 60),
    )

    assert service._effective_status(session, now) == "offline"
```

Then, following that same shape, one test each for:

- expired + **NULL** pid → `offline`. No monkeypatch needed: `_pid_is_running` returns `False` for a falsy pid (`:604-605`).
- expired + `mailbox_status == "offline"` + observed source with a **live** pid → `offline`. An explicit disconnect wins; this row never reaches the TTL branch because `:619-620` returns first.
- **within** TTL → the row's `mailbox_status` returned unchanged.
- `source == "mcp"` + expired + live pid → still `"connected"`. This pins the branch you must **not** touch; if you edit the mcp path instead, this is what fails.

The within-TTL case and the mcp case are the traps: they are what fail if you edit the wrong branch, and neither is about Finding 17 at all.

**On error behaviour, note what `_pid_is_running` actually does** (`:603-612`) — it is `os.kill(pid, 0)`, **not** a `/proc` read, and it is a different implementation from Task 2's `_owner_process_is_alive` on purpose:

| Condition | `_pid_is_running` | Why |
|---|---|---|
| falsy pid | `False` | no evidence → offline |
| `ProcessLookupError` | `False` | dead |
| `PermissionError` | **`True`** | the process exists, owned by another user |
| other `OSError` | `False` | fail closed |

`PermissionError → True` is verified (`os.kill(1, 0)` raises it on this host). Do **not** "simplify" the two liveness helpers into one: this one fails **closed** (an honest UI), and Task 2's fails **open** (retain a resource). Same question, deliberately opposite error contracts, as spec §3.2 states.

**A correction to the spec you must apply here.** §2.4's table says the revived value is `connected`, borrowing the word from the mcp branch. For an **observed** row that is wrong. Observed sessions are written with `mailbox_status = "observed"` (`:317`, `:393`), and `_session_can_nudge` tests `_effective_status(...) == "observed"` exactly, so returning `connected` would make every revived row fail that test and stop being nudgeable. Return the row's own `mailbox_status` instead — which is what the within-TTL path already does (`:632`). The table's *intent* (row 2: not `offline`) is preserved; only the literal is corrected. Verify with `grep -n "_effective_status" app/ -r` that no other caller distinguishes the two values: at the time of writing all seven either compare against `"offline"` or accept `{"connected", "observed"}` together.

- [ ] **Step 2: Run and watch the skew test fail**

Expected: FAIL — `assert 'offline' == 'connected'`

- [ ] **Step 3: Make the one-line change**

In `_effective_status`, in the TTL-expiry branch (`:628-631`) **only**:

```python
        if session.last_seen_at < now - timedelta(seconds=ttl):
            # An observed row carries a pid too. Resolving on it is what the mcp
            # branch already does; the asymmetry is why five live agents read as
            # offline (Finding 17). Fails closed on a NULL pid or an os.kill
            # error — _pid_is_running returns False for both — because here the
            # cost of guessing "alive" is a UI that lies, and possibly a nudge
            # into a dead pane.
            #
            # Returns the row's own mailbox_status, not the literal "connected":
            # observed rows carry "observed", and _session_can_nudge tests for
            # that exact value, so reviving them as "connected" would make every
            # one of them un-nudgeable.
            if session.pid and self._pid_is_running(session.pid):
                return session.mailbox_status
            return "offline"
```

An explicit `mailbox_status == "offline"` never reaches this branch — it returned at `:620` — so returning the row's own status here cannot resurrect a disconnected session.

**Do not touch the first block (`:615-619`).** It gives mcp rows a pre-emptive live-pid check that overrides an explicit `mailbox_status == "offline"`. Extending it to observed rows would satisfy the table's rows 2–4 while silently inverting row 5. The only edit is inside the TTL-expiry branch.

`_pid_is_running` is unchanged and stays the single implementation for both sources; it already returns `False` for a falsy pid (`:603-605`) and for an `OSError` from `os.kill` (`:611-612`), so rows 3 and 4 need no new guard. It is `os.kill(pid, 0)` rather than a `/proc` read — which is why it needs no pid-reuse guard of its own here, and also why it cannot be shared with Task 2's helper, which does read `/proc` in order to compare start times.

- [ ] **Step 4: Run the mail suite and the full backend suite**

Run: `python -m pytest tests/agent_mail/ -q && python -m pytest tests/agent_teams/ -q`
Expected: both green. If a mail test asserted the old offline behaviour, read it before changing it — and report it rather than rewriting if its intent looks deliberate.

- [ ] **Step 5: Commit**

```bash
git add -A backend
git commit -m "fix(g2): observed sessions past TTL resolve on their pid

_effective_status consulted _pid_is_running for source='mcp' rows but not for
source='observed' rows, though observed rows carry pids too. On the live host
five agents with running pids all read 'offline' because last_seen_at is
refreshed only by sync_observed_sessions, whose callers are all interactive —
the column recorded when a human last opened the Agent Mail page.

Only the TTL-expiry branch changes. The earlier mcp block overrides an explicit
disconnect, and extending that to observed rows would invert the rule that an
explicit disconnect wins.

Fails closed on a NULL or unreadable pid: the cost of guessing 'alive' here is
a UI that lies. That is deliberately the opposite of the backstop's treatment
of the same error, which retains a resource instead."
```

---

### Task 8: Release reminders — bound the forgot-to-report hold

**Files:**
- Modify: `backend/app/services/github_dispatch_service.py` (new `remind_held_leases`, called from `monitor_dispatched`)
- Test: `backend/tests/agent_teams/test_github_dispatch_service.py`

**Interfaces:**
- Consumes: Task 1's `lease_release_reminded_at`, Task 3's token, Task 5's `retry_requested_at`, Task 6's `_RELEASABLE_STATUSES`.
- Produces: `github_dispatch_service.remind_held_leases(db, scope) -> int`.

Implements spec §6 mitigation 1. **This is PR1 scope, not a nice-to-have.** §6 is explicit that the exposure is *unbounded*, not 6h: the backstop is a conjunction requiring the owner process to be **dead**, and under one-session-per-slot a standing session that simply never reports stays **alive** — so condition 3 never holds and the lease is held indefinitely. 6h bounds only the crash case. Nothing bounds the forgot-to-report case except this reminder and the Task 9 force-release.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_terminal_item_holding_a_lease_is_reminded(db):
    """The only bound on a forgot-to-report hold (spec §6 mitigation 1).

    The backstop cannot help: it requires a DEAD owner process, and the whole
    point of one-session-per-slot is that the session stays alive.
    """
    _, _, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=920,
        issue_title="merged but not released",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="merged",
    )
    db.add(item)
    await db.flush()
    workspace = (
        await db.execute(
            select(GithubWorkspace)
            .where(GithubWorkspace.scope_id == scope.id)
            .order_by(GithubWorkspace.id)
        )
    ).scalars().first()
    workspace.leased_item_id = item.id
    workspace.lease_token = "tok-abc"
    await db.commit()

    reminded = await github_dispatch_service.remind_held_leases(db, scope)

    assert reminded == 1
    assert workspace.lease_release_reminded_at is not None
```

Then, following that same fixture shape, one test each for:

2. **The reminder quotes the token.** Assert the sent message body contains `"tok-abc"`. The agent cannot derive it, and a reminder it cannot act on is not a mitigation.
3. **Throttled by `github_nudge_grace_seconds`.** A workspace with `lease_release_reminded_at = utcnow()` is not reminded again; one stamped `grace + 60` seconds ago is. Two assertions, two workspaces, one test.
4. **A pending retry changes the wording.** With `item.retry_requested_at` set, the body says the re-dispatch is queued behind this release. Assert on a distinctive substring. §6: under a column rather than a new status **nothing about the item's visible status changes**, so this reminder is the *only* notification the previous owner ever gets that its item was re-pended.
5. **A non-terminal item is not reminded.** `dispatch_status = "dispatched"` holding a lease → 0. Release is illegal there (§3.1c), so a reminder would ask for something the endpoint refuses.
6. **An unleased terminal item is not reminded.** → 0.
7. **The reminder never escalates.** After enough passes to exceed any grace window, `dispatch_status` is still `merged` and `escalation_reason` is still None. This is the trap: `monitor_dispatched`'s two existing timers both escalate on their second pass (`:647`, `:660`), and copying that shape here would escalate items whose work is *finished and merged*.

- [ ] **Step 2: Run and watch them fail**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/agent_teams/test_github_dispatch_service.py -k remind -v`
Expected: FAIL — `AttributeError: ... has no attribute 'remind_held_leases'`

- [ ] **Step 3: Implement**

```python
    async def remind_held_leases(self, db: AsyncSession, scope: TeamGithubScope) -> int:
        """Re-notify owners of terminal items that still hold a workspace lease.

        Never escalates, unlike the two timers in monitor_dispatched. The item's
        work is done — merged, completed, escalated or failed — and escalating
        finished work would be noise. This only asks for the release.

        Clock is lease_release_reminded_at on the WORKSPACE row, not
        item.last_nudge_at: that field already multiplexes the ack and idle
        timers, reset_for_retry does not clear it, and monitor_dispatched reads
        `last_nudge_at is None` to mean 'not yet nudged' before escalating. A
        reminder stamp surviving a retry would escalate leader_ack_timeout
        without the leader ever being nudged. On the workspace row, release()
        clears it for free.
        """
        grace = timedelta(seconds=settings.github_nudge_grace_seconds)
        now = datetime.utcnow()
        held = (
            await db.execute(
                select(GithubWorkspace, GithubWorkItem)
                .join(GithubWorkItem, GithubWorkspace.leased_item_id == GithubWorkItem.id)
                .where(
                    GithubWorkspace.scope_id == scope.id,
                    GithubWorkItem.dispatch_status.in_(_RELEASABLE_STATUSES),
                )
                .order_by(GithubWorkspace.id)
            )
        ).all()
        reminded = 0
        for workspace, item in held:
            if (
                workspace.lease_release_reminded_at is not None
                and now - workspace.lease_release_reminded_at < grace
            ):
                continue
            if item.retry_requested_at is not None:
                urgency = (
                    "\n\n**A re-dispatch of this issue is queued behind this "
                    "release.** It cannot start until you release the workspace."
                )
            else:
                urgency = ""
            await self.notify_owner(
                db,
                item,
                subject=f"Release needed: issue #{item.issue_number}",
                body_markdown=(
                    f"Issue #{item.issue_number} ({item.issue_title}) is "
                    f"`{item.dispatch_status}` but still holds workspace "
                    f"`{workspace.path}`. Commit and push anything you want to "
                    "keep, then release it:\n\n"
                    "```\n"
                    "deck_report_dispatch_status(\n"
                    f"    work_item_id={item.id},\n"
                    '    status="workspace_released",\n'
                    f'    lease_token="{workspace.lease_token}",\n'
                    ")\n"
                    "```"
                    f"{urgency}"
                ),
                payload={
                    "kind": "github_lease_release_reminder",
                    "work_item_id": item.id,
                    "issue_number": item.issue_number,
                    "workspace_path": workspace.path,
                },
            )
            workspace.lease_release_reminded_at = now
            workspace.updated_at = now
            reminded += 1
        if reminded:
            await db.commit()
        return reminded
```

`_RELEASABLE_STATUSES` is already at module scope in this file from Task 6.

- [ ] **Step 4: Call it from the scheduler, NOT from inside `monitor_dispatched`**

**Correction (2026-08-03, impl-agent review): placing this inside `monitor_dispatched` makes it unreachable in the exact case it exists for.** `monitor_dispatched` opens with an early return:

```python
enabled = sorted([slot for slot in preset_slots if slot.enabled], key=...)
if not enabled:
    return                      # github_dispatch_service.py:598-599
leader = enabled[0]
```

A reminder placed at the end of that function never runs when **no slot is enabled** — and "the operator disabled the slots while a terminal item still holds a lease" is precisely a forgot-to-report hold that nothing else bounds. Worse, the function's whole body assumes a leader exists, so the reminder would inherit a precondition it does not need: reminding an owner that its lease is held has nothing to do with leader presence.

Call it from the scheduler instead, as its own step beside `monitor_dispatched` (`github_dispatch_scheduler.py:147`):

```python
            await self.dispatch.monitor_dispatched(db, scope, slots)
            await self.dispatch.remind_held_leases(db, scope)
            await self.verification.process_scope(db, scope, client=client)
```

`remind_held_leases` therefore takes `(db, scope)` only — no `preset_slots` — which is what the Interfaces block above already specifies. It commits its own work rather than relying on `monitor_dispatched`'s final commit.

Two consequences worth stating, because both are the point rather than side effects:

- It runs on every scheduler pass regardless of slot state. Its own `lease_release_reminded_at` throttle is what bounds message volume; nothing else gates it.
- It is a separate pass over a **disjoint** set. `monitor_dispatched` selects `dispatch_status == "dispatched"` items only (`:614-621`), so its loop can never see a terminal item. This is not a branch inside that loop and must not be refactored into one.

Add a test that the reminder fires **with no enabled slots** — `preset_slots` empty or all disabled — since that is the regression this correction prevents and it would otherwise pass silently through any test that happens to have a leader.

- [ ] **Step 5: Run everything**

Run: `python -m pytest tests/agent_teams/ -q`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add -A backend
git commit -m "feat(g2): remind owners holding a lease on terminal work

The backstop bounds only the CRASH case: its conjunction requires the owner
process to be dead, and under one-session-per-slot a standing session that
simply never reports stays alive forever. Nothing bounded the
forgot-to-report hold. This does.

Quotes the lease_token, which the agent cannot derive. When a retry is pending
it says so — under a retry_requested_at column nothing about the item's visible
status changes, so this reminder is the only notification the previous owner
gets that its item was re-pended.

Never escalates, unlike the two timers it sits beside: the work is already
merged or completed. Clocked on the workspace row rather than
item.last_nudge_at, which is already multiplexed and survives reset_for_retry —
a stamp leaking into a retried item would escalate leader_ack_timeout without
the leader ever being nudged."
```

---

### Task 9: Operator visibility and force-release

**Files:**
- Modify: `backend/app/models/schemas.py:2235-2249` (`GithubWorkspaceResponse`)
- Modify: `backend/app/api/v1/agent_teams.py:160-175` (`_workspace_response`), plus a new force-release endpoint
- Test: `backend/tests/agent_teams/` (the workspace API tests)

**Interfaces:**
- Consumes: Tasks 1, 3, 6, 8.
- Produces: `POST /github-scopes/{scope_id}/workspaces/{workspace_id}/force-release`.

Implements spec §6 mitigations 2 and 3, and §9's owed UI surface.

- [ ] **Step 1: Write the failing tests**

Find the existing workspace-endpoint tests (`grep -rln "workspaces" backend/tests/agent_teams/`) and follow their client fixture. Cover:

1. `GET .../workspaces` exposes `lease_token`, `lease_last_owner_contact_at`, `lease_release_reminded_at` and a computed `lease_age_seconds` for a leased workspace, and nulls for an unleased one.
2. Force-release with the **matching** token → 200, lease returned.
3. Force-release with a **stale** token → 409 whose detail shows **both** tokens.
4. Force-release with a **dirty** tree → 200 and the lease still released, with `discarded_paths` naming the dirty files. This is the deliberate difference from agent-reported release: the operator endpoint exists precisely for the case where the normal path refuses, so a dirty-tree veto here would make it useless.
5. Force-release on an **unleased** workspace → 409, not a 500.
6. Force-release with **unpushed commits** → 200, released, and `discarded_paths` mentions the unpushed commits. Same asymmetry as test 4: the backstop and the agent path veto, the operator path reports and proceeds.
7. Force-release **omitting** `expected_lease_token` → 422 from pydantic. Pins the field as required; an optional token would compare `None` against a pre-migration lease's NULL token and match.
8. Force-release **omitting** `reason` → 422.

- [ ] **Step 2: Run and watch them fail**

- [ ] **Step 3: Extend the response schema**

Add to `GithubWorkspaceResponse` (`schemas.py:2235-2249`):

```python
    lease_token: Optional[str] = None
    lease_last_owner_contact_at: Optional[datetime] = None
    lease_release_reminded_at: Optional[datetime] = None
    lease_age_seconds: Optional[int] = None
```

and populate them in `_workspace_response` (`agent_teams.py:160-175`), computing `lease_age_seconds` from `leased_at` when a lease is held and leaving it None otherwise. §6 mitigation 2: a forgotten lease should be *visible*, not inferred from a stalled queue — the Finding 14 lesson.

`lease_token` is exposed deliberately. §6 mitigation 3 needs the operator to have it in hand to pass it back as the compare-and-swap guard. Note this widens who can read a token: §3.1b already records that `/dispatch-status` has no authentication, so a token read here could be replayed there. That is the same pre-existing gap, not a new one, and it is listed below as owed.

- [ ] **Step 4: Add the force-release endpoint**

Model it on `reprobe_github_workspace` (`agent_teams.py:569-607`) — same 404 checks, same `_conflict` helper.

**Correction (2026-08-03, impl-agent review): the draft used `body.expected_lease_token` and a `_workspace_response` return without defining either contract.** Neither can be left to the implementer: the request model determines what the CAS guard compares, and `_workspace_response` has no field able to carry the discarded paths that the commit message and test 4 both promise. Define both explicitly.

Request and response models, in `schemas.py` beside `GithubWorkspaceResponse` (`:2235-2253`):

```python
class GithubWorkspaceForceReleaseRequest(BaseModel):
    expected_lease_token: str          # REQUIRED — the CAS guard is the point
    reason: str                        # REQUIRED — why a human overrode the protocol
    requested_by: Optional[str] = None # operator identity, when the caller knows it


class GithubWorkspaceForceReleaseResponse(BaseModel):
    workspace: GithubWorkspaceResponse
    released_item_id: int
    discarded_paths: Optional[str] = None   # git status --porcelain at force time
    unpushed_commits: Optional[int] = None  # commits ahead of base_ref at force time
```

`expected_lease_token` is `str`, not `Optional[str]`: an absent token would make the CAS guard vacuous, and `None == workspace.lease_token` is *true* for a pre-migration lease — so an omitted field would silently force exactly the leases whose owner is least knowable. `reason` is required because this endpoint discards another party's work; an unexplained force is the thing the audit log exists to prevent.

On identity: there is **no authentication on this router** (§3.1b records the same gap for `/dispatch-status`), so `requested_by` is a self-asserted label, not a verified principal. Log it as such and do not build any authorization on it. Do not invent a header-based or session-based identity to fill the gap — endpoint-wide auth is listed as owed below and is a larger change than this task.

```python
    if workspace.leased_item_id is None:
        raise _conflict(
            "Workspace is not leased",
            block_code="workspace_not_leased",
        )
    if workspace.lease_token != request.expected_lease_token:
        raise _conflict(
            f"Lease token mismatch: expected {request.expected_lease_token}, "
            f"current {workspace.lease_token}. Refresh and re-check before forcing.",
            block_code="lease_token_mismatch",
        )
    # Capture what is about to be discarded BEFORE releasing — after release the
    # next acquire may reset the tree, and then nothing can report what was lost.
    scope = await db.get(TeamGithubScope, workspace.scope_id)
    blocker = await github_workspace_service.release_blocker(scope, workspace)
    released_item_id = workspace.leased_item_id
    logger.warning(
        "force-release workspace %s (item %s) by %s: %s; discarding: %s",
        workspace.id,
        released_item_id,
        request.requested_by or "unknown",
        request.reason,
        blocker or "nothing (tree was quiescent)",
    )
    await github_workspace_service.release(db, released_item_id)
```

The compare-and-swap is the point (§6 mitigation 3). An operator clicks from a page rendered some time ago; between render and click the lease may have been released and re-acquired by a **new** owner. A workspace-id-only force-release would then destroy a live lease — the same stale-identity failure as §3.1a, arriving through the operator instead of the agent.

Note the ordering above is load-bearing: `release_blocker` is called *before* `release`, and the `blocker` string is what populates `discarded_paths`. Reversing those two lines yields a response that always reports nothing discarded — a report that reads as reassuring precisely when it is least true.

Do **not** call `reset_workspace` here — release only. The next `acquire` resets, and doing it twice would discard the operator's chance to inspect the tree first.

- [ ] **Step 5: Run the suite**

Run: `python -m pytest tests/agent_teams/ -q`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add -A backend
git commit -m "feat(g2): expose lease staleness, add force-release with a CAS guard

Mitigation 2: GET .../workspaces reports the token, owner-contact and
reminder timestamps, and lease age, so a forgotten lease is visible rather than
inferred from a stalled queue.

Mitigation 3: force-release takes the EXPECTED token, not just the workspace
id. An operator acts from a page rendered some time ago; between render and
click the lease may have been released and re-acquired by a new owner, and an
id-only force-release would destroy a live lease — §3.1a's stale-identity
failure arriving through the operator instead of the agent. Mismatch returns
409 showing both tokens.

Unlike agent-reported release this does NOT veto on a dirty tree: the endpoint
exists for the case where the normal path refuses, so vetoing would make it
useless. It names the discarded paths and logs the force."
```

---

### PR1 gate

- [ ] Run `python -m pytest tests/agent_teams/ tests/agent_mail/ -q` — green.
- [ ] `grep -rn "slot_has_live_owner_session\|queued_owner_session_live" backend/ frontend/src` returns nothing.
- [ ] `grep -rn "retry_requested\"" backend/` returns nothing — no new `dispatch_status` value was added.
- [ ] Open **one** PR into `feature/autonomous-github-dispatch`. Do not merge it.
- [ ] In the PR body, list anything you had to adapt (line numbers that moved, a helper that already existed) and anything you could not do as specified.

---

# PR2 — The delivery guarantee

Open only after PR1 is merged. Autonomy stays off throughout.

Read spec §4 in full first. The ordering is not cosmetic: flipping `reuse_existing=True` before PR1's releaser exists creates Finding 19's permanent wedge, measured at `reclaim_stale released: 0`.

---

### Task 10: Keep `slot_prompt_overrides`, flip `reuse_existing`

**Files:**
- Modify: `backend/app/services/github_dispatch_service.py:251-261`
- Test: `backend/tests/agent_teams/test_github_dispatch_service.py:1256`

Implements spec §4.0 and §2.2.

**The correction that makes this task subtle:** `reuse_existing=True` does not mean "a session will be reused" — it means "reuse one **if a match exists**". With no wakeable session, `plan_launch` still yields `action=spawn`, and `_execute_plan_item` computes `bootstrap_prompt = prompt_override or await self._bootstrap_prompt(...)` (`agent_team_service.py:606-608`). Dropping the override would start a spawned agent with the generic team prompt: no issue number, no worktree path, no reporting instructions, no lease token. All six live slots have `bootstrap_prompt = NULL`, so this is the live behaviour, not a hypothetical.

- [ ] **Step 1: Rewrite the test that encodes Finding 13**

`test_dispatch_proceeds_with_only_standing_session` (`:1256`) asserts a second session **is spawned** when a standing one exists — it encodes the bug as the requirement. Rewrite it to assert the brief *reached* the standing session: a `MailReceipt` exists for the owner member, the launch request carried `reuse_existing=True`, and exactly one session exists for the slot afterwards.

- [ ] **Step 2: Add the spawn-fallback test**

Dispatch to a slot with **no** wakeable session must still spawn with `slot_prompt_overrides` containing the issue number and the leased worktree path. This is the regression §4.0 caught in review, and §7 step 4 walks straight into the path it guards.

- [ ] **Step 3: Run and watch them fail**

- [ ] **Step 4: Flip the flag, keep the override**

```python
                    AgentTeamLaunchRequest(
                        slot_ids=[owner_slot_id],
                        reuse_existing=True,
                        skip_plan_confirmation=True,
                        repo_path_override=workspace.path,
                        slot_prompt_overrides={owner_slot_id: brief},
                    ),
```

One word changes. The override stays: it is *ignored* on the reuse branch (which is Finding 13, and why the mail path exists) and *load-bearing* on the spawn branch. Complementary, not redundant.

- [ ] **Step 5: Run the suite, then commit**

```bash
git add -A backend
git commit -m "feat(g2): dispatch reuses the slot's standing session

reuse_existing=True. The brief already arrives as mail before launcher() is
called — verified on live data, all 14 recent briefs carry a read_at — so the
reuse path does not need prompt delivery.

slot_prompt_overrides is KEPT. reuse_existing=True means 'reuse if a match
exists'; with no wakeable session plan_launch still yields action=spawn, and
that branch uses prompt_override or falls back to the generic three-line team
prompt. All six live slots have bootstrap_prompt=NULL, so dropping the override
would have shipped a spawned agent with no issue number, no worktree path and
no lease token.

Rewrites the canary that asserted a second session is spawned — it encoded
Finding 13 as the requirement."
```

---

### Task 11: A non-throttled wake for dispatch briefs

**Files:**
- Modify: `backend/app/services/agent_mail_service.py:42, 1127-1146`
- Test: `backend/tests/agent_mail/`

Implements spec §4.1.

`AUTO_NUDGE_COOLDOWN_SECONDS = 30` over an in-memory `_last_auto_nudge_at` dict. Under per-item spawn the nudge was decorative — the prompt was passed at spawn. Under one-session-per-slot it is the **only** thing that makes the agent read the brief, so any unrelated message to that member within the prior 30s (an escalation broadcast, a blocker-merged notification) silently drops the brief's wake.

**Interfaces:**
- Produces: `auto_nudge_members(db, member_ids, *, bypass_cooldown: bool = False)`; `send_message(..., bypass_nudge_cooldown: bool = False)`; `send_direct_message(..., bypass_nudge_cooldown: bool = False)`.

- [ ] **Step 1: Write the failing test**

Model the fixture on `test_send_message_auto_nudge_is_throttled` (`tests/agent_mail/test_registry.py:698-740`) — it already fakes `discover_agent_sessions`, `subprocess.run` and `time.sleep`, which is everything a nudge needs. Note two things about that fixture and copy them exactly:

- The recipient is the **observed** member that `sync_observed_sessions` creates, obtained with `(await svc.list_team(db))[0]` (`:726`). Do **not** reach for `get_or_create_slot_member` — no slot exists in this fixture.
- `calls.clear()` runs after the sync, so the count starts at zero. **One nudge is two tmux calls** (`send-keys -l <prompt>`, then `send-keys Enter`), which is why the original asserts `len(tmux_calls) == 2` for two sends: the first nudged, the second was throttled.

```python
@pytest.mark.asyncio
async def test_dispatch_brief_nudge_bypasses_the_cooldown(db, svc, tmp_path, monkeypatch):
    """Spec §4.1. Under one-session-per-slot the nudge is the ONLY thing that
    makes the agent read the brief, so an unrelated message moments earlier
    must not silently consume the brief's wake.

    Under per-item spawn this was decorative — the brief was the spawn prompt.
    That is why the existing throttle test treats the cooldown purely as a
    feature: it was written when suppressing a nudge cost nothing.
    """
    cwd = tmp_path / "obs"
    cwd.mkdir()
    fake = [
        {
            "provider": "codex-cli",
            "provider_display_name": "Codex",
            "tmux_target": "w:0.1",
            "session_name": "w",
            "window_name": "main",
            "pane_id": "%7",
            "cwd": str(cwd),
            "pid": "4242",
            "status": "active",
        }
    ]
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(
            stdout="", stderr="", returncode=0 if command[0] == "tmux" else 1
        )

    monkeypatch.setattr(
        "app.services.agent_mail_service.discover_agent_sessions", lambda: fake
    )
    monkeypatch.setattr("app.services.agent_mail_service.subprocess.run", fake_run)
    monkeypatch.setattr("app.services.agent_mail_service.time.sleep", lambda _: None)
    await svc.sync_observed_sessions(db)
    recipient = (await svc.list_team(db))[0]
    calls.clear()

    # An unrelated message — an escalation broadcast, a blocker-merged note.
    # This arms the 30s cooldown for this member.
    await svc.send_direct_message(
        db,
        recipient_member_id=recipient.id,
        subject="blocker merged",
        body_markdown="fyi",
    )
    assert len([c for c, _ in calls if c[0] == "tmux"]) == 2  # one nudge

    # The dispatch brief, moments later, MUST still wake the pane.
    await svc.send_direct_message(
        db,
        recipient_member_id=recipient.id,
        subject="Autonomous dispatch: issue #900",
        body_markdown="brief",
        bypass_nudge_cooldown=True,
    )

    assert len([c for c, _ in calls if c[0] == "tmux"]) == 4  # two nudges
```

Also add the negative, in the same file, so the bypass cannot silently become the default — an *ordinary* second send within the cooldown must still be suppressed:

```python
@pytest.mark.asyncio
async def test_ordinary_send_still_throttled_after_a_bypassed_brief(
    db, svc, tmp_path, monkeypatch
):
    """The bypass is per-call, not a mode. Sending a brief must not leave the
    member permanently un-throttled — the brief still ARMS the window.
    """
    # ... identical fixture to the test above ...
    await svc.send_direct_message(
        db, recipient_member_id=recipient.id, subject="brief",
        body_markdown="b", bypass_nudge_cooldown=True,
    )
    assert len([c for c, _ in calls if c[0] == "tmux"]) == 2

    await svc.send_direct_message(
        db, recipient_member_id=recipient.id, subject="chatter", body_markdown="c",
    )
    assert len([c for c, _ in calls if c[0] == "tmux"]) == 2  # unchanged
```

That second test is what pins the "records but does not read" semantics in Step 3. Without it, an implementation that skips the `self._last_auto_nudge_at[member_id] = now` write on the bypass path would pass the first test and silently disable the throttle for whatever the brief is followed by.

- [ ] **Step 2: Run and watch it fail**

Run: `python -m pytest tests/agent_mail/test_registry.py -k bypass -v`
Expected: FAIL — `TypeError: send_direct_message() got an unexpected keyword argument 'bypass_nudge_cooldown'`.

- [ ] **Step 3: Thread the bypass through the three layers**

`AUTO_NUDGE_COOLDOWN_SECONDS = 30` (`:42`) stays exactly as it is. Add a parameter, do not weaken the constant — it exists to stop nudge storms and every other caller still wants it.

In `auto_nudge_members` (`:1127`):

```python
    async def auto_nudge_members(
        self,
        db: AsyncSession,
        member_ids: set[int],
        *,
        bypass_cooldown: bool = False,
    ) -> list[dict[str, str | int]]:
        ...
        for member_id in sorted(member_ids):
            last_nudge_at = self._last_auto_nudge_at.get(member_id)
            if (
                not bypass_cooldown
                and last_nudge_at is not None
                and last_nudge_at > cooldown_cutoff
            ):
                continue
```

The bypass still **records** `self._last_auto_nudge_at[member_id] = now` at `:1146` — it skips reading the cooldown, not writing it. Otherwise a brief would leave the next ordinary message un-throttled.

Then pass it through `send_message` (the call at `:862`) and `send_direct_message` (`:887-909`), defaulting to `False` in both signatures. Finally, in `github_dispatch_service._send_dispatch_brief_to_slot` (`:531-545`), set `bypass_nudge_cooldown=True` on the brief's send — that call site is the only one that should use it in PR2.

- [ ] **Step 4: Run both tests, then the full suite**

Run: `python -m pytest tests/agent_mail/ -q && python -m pytest tests/agent_teams/ -q`
Expected: green, including the original `test_send_message_auto_nudge_is_throttled` **unchanged**. If you had to modify that test, stop and report — it means the bypass leaked into the default path.

- [ ] **Step 5: Commit**

```bash
git add -A backend
git commit -m "feat(g2): dispatch briefs bypass the auto-nudge cooldown

AUTO_NUDGE_COOLDOWN_SECONDS is unchanged and still applies to every other
sender. Under per-item spawn the nudge was decorative — the brief WAS the spawn
prompt — so a suppressed nudge cost nothing and the existing test treats the
throttle purely as a feature. Under one-session-per-slot the nudge is the only
thing that makes the agent read the brief, so any unrelated message within 30s
(an escalation broadcast, a blocker-merged note) silently dropped the dispatch.

The bypass skips READING the cooldown, not writing it: the brief still arms the
window for whatever follows it."
```

---

### Task 12: Delivery evidence and the `brief_unread` escalation

**Files:**
- Modify: `backend/app/services/github_dispatch_service.py:517-546` (`_send_dispatch_brief_to_slot`), `:624-663` (`monitor_dispatched`'s timer block), plus two new helpers
- Modify: `backend/app/services/github_verification_service.py:29-37` (`_PR_OPENED_RECOVERABLE_ESCALATIONS`)
- Test: `backend/tests/agent_teams/test_github_dispatch_service.py`

Implements spec §4.1a — all three corrections. Uses Task 1's `brief_delivery_nudge_at`, `brief_delivery_nudge_count`, `brief_message_id`, and `settings.github_brief_delivery_max_nudges`.

**Interfaces:**
- Consumes: Task 1's four fields; Task 6's `lease_last_owner_contact_at` stamp; Task 11's `bypass_nudge_cooldown`.
- Produces: `GithubDispatchService._brief_delivered(self, db, item) -> bool`; `_nudge_owner_for_brief(self, db, item) -> None`; the escalation reason string `"brief_unread"`.

Three rules, each with a test:

1. **Delivery is proven by the receipt's `read_at` OR any owner status report.** A spawned owner gets the brief as its *prompt* (§4.0) and may work correctly while never opening its mailbox, so `read_at` alone yields a false `brief_unread`. A report is *stronger* evidence than a read receipt — it proves comprehension, not retrieval.
2. **Delivery gets its own columns.** `last_nudge_at` already multiplexes the leader-ack and owner-idle timers (`:645-663`), with the ack branch `continue`-ing before the idle branch. A third tenant would make them interfere: whichever fires first resets the shared clock, and `escalate` then reports whichever branch it happened to be in.
3. **Delivery is evaluated BEFORE ack.** `leader_ack_timeout` currently masks `brief_unread` permanently — the ack branch escalates first and `escalate` is terminal, so an undelivered brief is misdiagnosed as *the leader failing to ack*. That is the Finding 14 misattribution cost, exactly.

The ack clock keeps its `dispatched_at` anchor. Gating it on delivery evidence was **declined twice**: it converts a loud, already-implemented failure into silence.

- [ ] **Step 1: Record which message was the brief**

This comes first because every test below needs it. `_send_dispatch_brief_to_slot` (`:517-546`) currently **discards** the `MailMessageResponse` and swallows every exception with `logger.exception`. Capture the id, and take Task 11's bypass at the same time:

```python
    async def _send_dispatch_brief_to_slot(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        *,
        preset_slots: list[AgentTeamSlot],
        owner_slot_id: int,
        brief: str,
    ) -> None:
        owner_slot = next((slot for slot in preset_slots if slot.id == owner_slot_id), None)
        if owner_slot is None:
            return
        try:
            from app.services.agent_mail_service import agent_mail_service

            member = await agent_mail_service.get_or_create_slot_member(db, owner_slot)
            message = await agent_mail_service.send_direct_message(
                db,
                recipient_member_id=member.id,
                subject=f"Autonomous dispatch: issue #{item.issue_number}",
                body_markdown=brief,
                bypass_nudge_cooldown=True,   # Task 11
                payload={
                    "kind": "github_dispatch_assignment",
                    "work_item_id": item.id,
                    "issue_number": item.issue_number,
                    "scope_id": item.scope_id,
                },
            )
            # Which message was THIS attempt's brief. MailReceipt is unique on
            # (message_id, member_id) only, so without the id the delivery check
            # has to guess among the member's messages — and a re-dispatched item
            # has several. The guess fails unsafely: an older brief that WAS read
            # proves delivery for an attempt whose brief never arrived.
            item.brief_message_id = message.id
            item.brief_delivery_nudge_at = None
            item.brief_delivery_nudge_count = None
        except Exception:
            logger.exception("Failed to send autonomous dispatch brief for item %s", item.id)
```

Two things about that block:

- **Clearing the two counters here is the "counter clearing on fresh dispatch" requirement.** A retried item that escalated `brief_unread` last time starts at count 0, or the second attempt escalates on its first monitor pass with no nudge sent. This is the same class of bug Task 1 avoids by keeping the reminder stamp off `last_nudge_at` — a counter surviving into a new attempt. Note it must clear on the **success** path only; the `except` branch leaves `brief_message_id` NULL, which Step 3 reads as "no brief recorded" and treats as undelivered.
- **Do not add `await db.commit()`.** `dispatch_pending` commits at the end of the item's loop iteration (`:288-290`), and on the failure paths it rolls back or escalates. Committing here would persist a `brief_message_id` for a dispatch that then failed to launch.

- [ ] **Step 2: Write the failing tests**

Four tests, from spec §5.2. Build them on the `_team(db)` + `GithubWorkItem(...)` + `wake_state_by_slot=` fixture shape used by every existing monitor test — `test_monitor_escalates_when_leader_offline` (`test_github_dispatch_service.py:1710-1737`) is the shortest example. Every one needs `updated_at` set past `github_owner_registration_grace_seconds` (120s) or `_within_registration_grace` (`:666`) makes the whole loop a no-op.

Two facts about this file that save you a detour: `_team(db)` (`:54-98`) already creates **five unleased `GithubWorkspace` rows** for the scope, so a lease fixture just claims one; and `agent_mail_service` is **not** in its import block (`:12-26`) — add it.

Add a local helper next to `_team`, since three of the four tests need a lease:

```python
async def _lease_for(db, scope, item, **overrides):
    """Claim one of _team's workspaces for this item. Mirrors acquire()."""
    workspace = (
        await db.execute(
            select(GithubWorkspace).where(
                GithubWorkspace.scope_id == scope.id,
                GithubWorkspace.leased_item_id.is_(None),
            ).limit(1)
        )
    ).scalar_one()
    workspace.leased_item_id = item.id
    workspace.leased_at = datetime.utcnow()
    workspace.lease_token = "t1"
    for key, value in overrides.items():
        setattr(workspace, key, value)
    await db.commit()
    return workspace
```

```python
@pytest.mark.asyncio
async def test_delivery_proven_by_report_not_only_receipt(db):
    """Spec §4.1a(1). A SPAWNED owner gets the brief as its prompt and may never
    open its mailbox. read_at NULL + a recorded report must NOT be brief_unread.
    """
    preset, slots, scope = await _team(db)
    stale = datetime.utcnow() - timedelta(
        seconds=settings.github_owner_registration_grace_seconds + 1
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=90,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=slots[1].id,
        dispatched_at=stale,
        updated_at=stale,
        brief_delivery_nudge_count=settings.github_brief_delivery_max_nudges,
        brief_delivery_nudge_at=stale,  # retries exhausted, so only evidence saves it
    )
    db.add(item)
    await db.commit()

    # An unread brief: a MailMessage plus a MailReceipt whose read_at is NULL.
    # send_direct_message creates the receipt (agent_mail_service.py:852).
    member = await agent_mail_service.get_or_create_slot_member(db, slots[1])
    message = await agent_mail_service.send_direct_message(
        db,
        recipient_member_id=member.id,
        subject="brief",
        body_markdown="b",
        auto_nudge=False,
    )
    item.brief_message_id = message.id
    # ...but the owner reported. That is stronger evidence than a read receipt.
    await _lease_for(db, scope, item, lease_last_owner_contact_at=datetime.utcnow())

    await github_dispatch_service.monitor_dispatched(
        db, scope, preset_slots=slots,
        wake_state_by_slot={slots[0].id: "wakeable", slots[1].id: "wakeable"},
    )
    await db.refresh(item)
    assert item.escalation_reason != "brief_unread"
    assert item.dispatch_status == "dispatched"
```

Use `auto_nudge=False` on every fixture send. Without it `auto_nudge_members` runs `sync_observed_sessions` → `discover_agent_sessions` → a real `tmux list-panes` against **this machine**, so the test would depend on whichever panes happen to be open. It would not fail loudly either: `discover_agent_sessions` returns `[]` on a nonzero exit or a missing binary rather than raising (`agent_bridge/discovery.py:100-116`), so the test would just quietly stop testing what it claims to.

Then, following that same fixture shape, one test each for:

- **No receipt, no report, retries exhausted → `brief_unread`.** The complement of the above: `lease_last_owner_contact_at` NULL, `read_at` NULL, `brief_delivery_nudge_count == github_brief_delivery_max_nudges`, `brief_delivery_nudge_at` older than `github_nudge_grace_seconds`. Assert `dispatch_status == "escalated"` **and** `escalation_reason == "brief_unread"`.
- **`brief_unread` is not masked by `leader_ack_timeout`.** Same fixture, but *also* make the ack overdue: `ack_received_at=None` and `last_nudge_at` older than `github_nudge_grace_seconds` (which is the state that escalates `leader_ack_timeout` today, `:647-650`). Both are overdue; the reason must be `brief_unread`. **This is the load-bearing test of the task** — it is the only one that fails if the delivery check is placed after the ack branch instead of before it, and misattribution is what Finding 14 cost two review rounds.
- **The counters are independent, in both directions.** (a) An item whose brief is *undelivered but retries not yet exhausted* gets a delivery nudge: assert `brief_delivery_nudge_count == 1` and `last_nudge_at` is **still None**. (b) An item whose brief *is* delivered but whose leader is silent gets an ack nudge: assert `last_nudge_at` is set and `brief_delivery_nudge_at` is **still None**. Without (b) an implementation that writes both fields from one helper passes (a).
- **A brief read on the first nudge does not escalate** (spec §5.2, last bullet). Same fixture with `receipt.read_at = datetime.utcnow()` → `dispatch_status` stays `dispatched`.

- [ ] **Step 3: Run and watch them fail**

Run: `python -m pytest tests/agent_teams/test_github_dispatch_service.py -k "delivery or brief_unread" -v`
Expected: FAIL. The masking test fails with `assert 'leader_ack_timeout' == 'brief_unread'` — which is the defect stated as an assertion. The others fail with `escalation_reason is None`.

- [ ] **Step 4: Add the delivery-evidence helper**

In `github_dispatch_service.py`. It needs `MailReceipt` added to the `app.models.database` import block (`:11-19`) — `MailAgentSession` and `MailTeamMember` are already there, `MailReceipt` is not.

```python
    async def _brief_delivered(self, db: AsyncSession, item: GithubWorkItem) -> bool:
        """Has this attempt's brief reached the owner? (Spec §4.1a(1).)

        Either signal suffices, and the report is the stronger of the two: it
        proves comprehension, not just retrieval. The receipt alone would raise
        brief_unread against a spawned owner that got the brief as its PROMPT
        and never opened its mailbox (§4.0) — a false escalation against an
        agent that is working.

        Owner contact is read from the LEASE, not the item, because the
        question is 'has the thing holding this acquisition spoken?' — see
        Task 6. A NULL brief_message_id means no brief was recorded (the send
        raised, or the item predates this migration), which is undelivered.
        """
        workspace = await github_workspace_service.get_leased_workspace(db, item.id)
        if workspace is not None and workspace.lease_last_owner_contact_at is not None:
            return True
        if item.brief_message_id is None:
            return False
        member = await self._owner_member(db, item)
        if member is None:
            return False
        receipt = (
            await db.execute(
                select(MailReceipt).where(
                    MailReceipt.message_id == item.brief_message_id,
                    MailReceipt.member_id == member.id,
                )
            )
        ).scalar_one_or_none()
        return receipt is not None and receipt.read_at is not None
```

Note the deliberate asymmetry with `_owner_process_is_alive` (Task 2). That one fails **open** — unknown means alive, retain the lease. This one fails **closed** — unknown means undelivered, escalate. Both are correct because the unsafe outcomes point opposite ways: wrongly reclaiming a live agent's worktree destroys work, while wrongly escalating an unread brief only summons a human. Do not "make them consistent".

And the delivery nudge, which writes **only** its own fields:

```python
    async def _nudge_owner_for_brief(self, db: AsyncSession, item: GithubWorkItem) -> None:
        """Re-wake the owner about an unread brief. Touches brief_delivery_* ONLY.

        Not last_nudge_at: that column already multiplexes the leader-ack and
        owner-idle timers (§4.1a(2)) and a third tenant makes all three
        interfere — whichever fires first resets the shared clock and escalate
        reports whichever branch it happened to be in.
        """
        item.brief_delivery_nudge_at = datetime.utcnow()
        item.brief_delivery_nudge_count = (item.brief_delivery_nudge_count or 0) + 1
        await self.notify_owner(
            db,
            item,
            subject=f"Unread dispatch brief: issue #{item.issue_number}",
            body_markdown=(
                f"You were assigned issue #{item.issue_number} ({item.issue_title}) "
                "but the brief is still unread. Call `deck_check_inbox` now and "
                "report your status."
            ),
            payload={
                "kind": "github_dispatch_brief_nudge",
                "work_item_id": item.id,
                "issue_number": item.issue_number,
            },
        )
        await db.commit()
```

`(item.brief_delivery_nudge_count or 0) + 1` is the NULL-as-zero reading Task 1 specifies. `notify_owner` (`:787`) already resolves the owner member and no-ops when there is none, so no extra guard is needed.

- [ ] **Step 5: Insert the delivery branch BEFORE the ack branch**

In `monitor_dispatched`, between the `owner_wake == "offline"` check (`:634-637`) and `if not self._ack_satisfied(item):` (`:638`):

```python
            if not await self._brief_delivered(db, item):
                anchor = item.brief_delivery_nudge_at
                if anchor is None:
                    await self._nudge_owner_for_brief(db, item)
                    continue
                if datetime.utcnow() - anchor <= timedelta(
                    seconds=settings.github_nudge_grace_seconds
                ):
                    continue
                if (item.brief_delivery_nudge_count or 0) < settings.github_brief_delivery_max_nudges:
                    await self._nudge_owner_for_brief(db, item)
                    continue
                await self.escalate(db, item, "brief_unread")
                continue
```

**Placement is the whole point of §4.1a(3), so do not move it.** Before the ack branch, an undelivered brief reports as `brief_unread`. After it, `_ack_satisfied` is False (the owner never got the brief, so the leader never acked), the ack branch escalates `leader_ack_timeout`, and `escalate` is terminal — the delivery branch is then unreachable *forever* for that item. That is a wrong diagnosis pointing at the wrong actor.

It goes **after** the two `wake == "offline"` checks deliberately: an offline owner is a better diagnosis than an unread brief, and it is the older, already-tested one.

Every branch `continue`s. An item whose brief is undelivered must not also be evaluated for ack or idle on the same pass — that is the multiplexing this task exists to prevent, and the existing branches use the same discipline (`:637`, `:651`).

- [ ] **Step 6: Make `brief_unread` recoverable by a late PR**

In `github_verification_service.py`, add `"brief_unread"` to `_PR_OPENED_RECOVERABLE_ESCALATIONS` (`:29-37`):

```python
_PR_OPENED_RECOVERABLE_ESCALATIONS = frozenset(
    {
        "plan_blocked",
        "owner_idle_timeout",
        "owner_offline",
        "leader_offline",
        "leader_ack_timeout",
        "brief_unread",
    }
)
```

Its own comment states the rule this satisfies: "Escalations a late PR legitimately resolves: the agent said it was stuck, or Deck inferred it from a timer." `brief_unread` is inferred from a timer, and an owner that opens a PR has self-evidently read the brief. Omitting it would make `report_pr_opened` **raise** for exactly the item that just proved the escalation wrong.

Add the test with it: `brief_unread` + a `pr_opened` report → 200, `escalation_reason` cleared, `pr_number` set.

- [ ] **Step 7: Run the suite**

Run: `python -m pytest tests/agent_teams/ tests/agent_mail/ -q`
Expected: green. Watch for pre-existing monitor tests that now take the delivery branch first: any `dispatched` fixture with no receipt, no report and no `brief_message_id` is *undelivered* by the new rule, so its first monitor pass now sends a delivery nudge instead of what it asserted. If one breaks, check which behaviour it was pinning before changing it — a test asserting `leader_ack_timeout` on an item that never received a brief was asserting the misattribution, and rewriting it is correct. A test that set up genuine delivery and broke anyway is a real regression. Report either way; do not rewrite silently.

- [ ] **Step 8: Commit**

```bash
git add -A backend
git commit -m "feat(g2): delivery evidence and the brief_unread escalation

Records which message was the brief (brief_message_id) because MailReceipt is
unique on (message_id, member_id) only — without it, 'is the brief unread?'
has to guess among the member's messages, and the guess fails unsafely: an
older brief that WAS read would prove delivery for an attempt whose brief
never arrived.

Delivery is proven by the receipt's read_at OR any owner status report. The
receipt alone would escalate against a spawned owner that received the brief
as its PROMPT and never opened its mailbox — a false alarm against an agent
that is working. The report is the stronger signal: comprehension, not
retrieval.

Dedicated columns, not last_nudge_at, which already multiplexes leader-ack and
owner-idle. A third tenant makes all three interfere — whichever fires first
resets the shared clock and escalate reports whichever branch it was in.

Evaluated BEFORE ack, and that ordering is the fix. After it, _ack_satisfied
is False precisely BECAUSE the brief never arrived, the ack branch escalates
leader_ack_timeout, and escalate is terminal — so an undelivered brief was
permanently misdiagnosed as the leader failing to ack. Finding 14's cost was
two review rounds spent on exactly that misattribution.

brief_unread joins _PR_OPENED_RECOVERABLE_ESCALATIONS: it is timer-inferred,
and an owner that opens a PR has self-evidently read the brief."
```

---

### Task 13: Refuse an ambiguous slot before acquiring

**Files:**
- Modify: `backend/app/services/agent_mail_service.py:350-398` (`sync_observed_sessions` gains `strict`), plus a new `nudgeable_sessions_for_slot`
- Modify: `backend/app/services/github_dispatch_service.py:215-221` (the gate Task 4 emptied, before `acquire` at `:222`)
- Modify: `frontend/src/features/agent-teams/AutonomyPanel.tsx:85-96` (`pendingReasonLabel`)
- Test: `backend/tests/agent_teams/test_github_dispatch_service.py`

Implements spec §4.2.

**Interfaces:**
- Consumes: `_session_can_nudge` (`agent_mail_service.py:595`).
- Produces: `agent_mail_service.sync_observed_sessions(db, *, strict: bool = False) -> None`; `agent_mail_service.nudgeable_sessions_for_slot(db, slot_id) -> list[MailAgentSession]`; the `pending_reason` string `"queued_ambiguous_sessions"`.

`_nudge_session_for_member` orders by `last_seen_at desc` and takes the first nudgeable session (`:1067-1086`). Slot 6 currently carries three sessions under one `member_id`, all stamped within microseconds by `sync_observed_sessions` one line earlier — so which pane receives the prompt is a coin flip today.

**This gate replaces the one Task 4 deleted, at the same place in `dispatch_pending`.** That is a convenience, not a coincidence: both answer "is this slot fit to be dispatched to?" immediately before `acquire`. But they are opposite predicates and must not be confused — Task 4 removed `slot_has_live_owner_session` because *a live session is now the normal state*; this one blocks on **two or more** live sessions. If you find yourself writing `if any(...)`, stop: that is Finding 19 restored.

- [ ] **Step 1: Give `sync_observed_sessions` a strict mode**

The existing signature swallows discovery failures with an early return (`:352-356`), so a caller cannot tell "discovery worked and found nothing" from "discovery blew up". Add the distinction without changing any existing caller's behaviour:

```python
    async def sync_observed_sessions(
        self, db: AsyncSession, *, strict: bool = False
    ) -> None:
        """Upsert Agent Bridge tmux discoveries as observed sessions.

        strict=True re-raises a discovery failure instead of returning. Callers
        that gate a decision on the result need to know the difference between
        'no sessions' and 'could not look'; the default stays lenient because
        every other caller is a best-effort refresh (auto_nudge_members:1131,
        the Agent Mail page) where a warning is the right outcome.
        """
        try:
            discovered = discover_agent_sessions()
        except Exception as exc:
            logger.warning("agent bridge discovery failed: %s", exc)
            if strict:
                raise
            return
```

The rest of the method is unchanged. Note what `strict` does **not** buy you: `discover_agent_sessions` itself returns `[]` for a missing tmux binary, a nonzero `list-panes` exit, or a timeout (`agent_bridge/discovery.py:100-116`) — it does not raise. So an empty result is still ambiguous by construction, and Step 3 has to handle it separately. `strict` closes the narrower hole of an unexpected exception mid-sync.

- [ ] **Step 2: Add the counting helper**

Also in `agent_mail_service.py`, beside `_nudge_session_for_member` (`:1067`). It exists so the check and the live nudge share one definition of "nudgeable":

```python
    async def nudgeable_sessions_for_slot(
        self, db: AsyncSession, slot_id: int
    ) -> list[MailAgentSession]:
        """Every session that _nudge_session_for_member would be willing to pick.

        Deliberately the same filter and predicate as _nudge_session_for_member
        (:1073-1086) — that method takes the FIRST of these, so anything it
        would choose among is what 'ambiguous' has to mean. Two definitions
        would let the check pass while the nudge still coin-flips.
        """
        now = datetime.utcnow()
        sessions = (
            await db.execute(
                select(MailAgentSession).where(
                    MailAgentSession.team_slot_id == slot_id,
                    MailAgentSession.source == "observed",
                    MailAgentSession.provider.in_(sorted(TMUX_WAKE_PROVIDERS)),
                    MailAgentSession.tmux_target.is_not(None),
                )
            )
        ).scalars().all()
        return [s for s in sessions if self._session_can_nudge(s, now)]
```

**Keyed on `team_slot_id`, deliberately, and this is not the same set of rows `_nudge_session_for_member` sees.** That method keys on `member_id` (`:1074`). The two agree only while a slot has exactly one member — and nothing enforces that: `MailTeamMember.team_slot_id` has **no unique constraint** (`database.py:350-352`), and the soak log records duplicate members on one slot as a recurring, confirmed defect (Finding 10, `2026-07-06-tizonia-roadmap-v1-soak-run-log.md:166-169`).

So there are in fact **two** coin flips on the delivery path, not one:

1. `_slot_member` (`github_dispatch_service.py:970-978`) picks the slot's member by `ORDER BY updated_at DESC LIMIT 1` — an arbitrary choice among duplicates.
2. `_nudge_session_for_member` then picks that member's first nudgeable session — the flip §4.2 names.

`team_slot_id` is the superset that spans both: it counts every nudgeable pane on the slot regardless of which member owns it. Keying on `member_id` instead would let a slot with two members holding one pane each read as **unambiguous twice over**, dispatch, and then coin-flip at step 1 — the precise failure §4.2 exists to prevent, reintroduced by a narrower key. Fail-closed requires the superset.

`sync_observed_sessions` sets `session.team_slot_id` from the resolved member on every sync (`:391`), so the column is as fresh as the sync Step 5 forces. Do not "align" this helper with `_nudge_session_for_member` for symmetry; the asymmetry is the point. (Converging a slot to one member is out of scope for G2 — it needs a migration plus a uniqueness constraint. This gate makes the duplicate *visible* rather than silent, which is what §4.2 asks for.)

- [ ] **Step 3: Write the failing tests**

Before the tests themselves, one fixture is **mandatory**, not optional — read this even if you skim the rest.

**Step 5 makes every `dispatch_pending` call in this file shell out to the real `tmux`.** Two consequences, both of which will otherwise produce failures that look unrelated to G2:

1. **The suite becomes host-dependent.** `discover_agent_sessions` runs `tmux list-panes -a` (`discovery.py:102-107`). On a developer laptop with no tmux it returns `[]`; on *this* machine there are live agent panes right now, so it returns real rows and `_member_for_observed_session` inserts real repo members into the in-memory test DB. Same code, different results, depending on who runs it.
2. **The sync deletes seeded sessions.** `_remove_stale_observed_sessions` (`:530-548`) selects **every** row with `source == "observed"` — not scoped to the slot, the preset, or the scope — and deletes any whose `session_key` is absent from *this* discovery pass. So any test that seeds an observed session and then calls `dispatch_pending` has that session deleted mid-test unless discovery happens to return the same `pane_id`.

Add an autouse fixture so discovery is explicit in every test rather than inherited from the host:

```python
@pytest.fixture(autouse=True)
def no_discovered_panes(monkeypatch):
    """Dispatch now syncs tmux discovery (Task 13 Step 5), so without this the
    suite reads the developer's real tmux server: [] on a laptop with no tmux,
    live agent panes on the orchestration host. Tests that want panes override
    this with their own monkeypatch.setattr on the same target.
    """
    monkeypatch.setattr(
        "app.services.agent_mail_service.discover_agent_sessions", lambda: []
    )
```

With discovery pinned to `[]`, a test that seeds sessions and expects them to *survive* a dispatch must also return them from discovery — which is exactly what `_seed_observed_panes` plus a matching `_pane` list does below. That coupling is real behaviour, not a test artifact: a pane tmux cannot see is, correctly, not a pane you can nudge.

Now the tests. Both from spec §5.2, plus the load-bearing negative. Three fixture facts, all verified, that will otherwise cost you an afternoon:

**(a) Patch discovery at `app.services.agent_mail_service.discover_agent_sessions`.** The name is imported *into* that module (`:33`), so patching the definition site (`agent_bridge.discovery`) would not take. Every existing test does it this way (`tests/agent_mail/test_registry.py:721`).

**(b) A discovered pane only binds to a *slot* member if a matching observed session already exists.** `sync_observed_sessions` looks up by `session_key = f"tmux:{pane_id}"` (`:365`) and only reuses the slot binding when `_member_for_existing_observed_session` (`:474-508`) accepts the row — which requires the stored session to have `source == "observed"`, a non-NULL `team_slot_id`, the same `provider`, the same `pane_id` and `tmux_target`, a `cwd` with the same `repo_id`, a slot whose `provider` matches, and a member whose `team_slot_id` is that slot. Fail any one and `_member_for_observed_session` falls through to `_get_or_create_repo_member`, producing a **repo** member with `team_slot_id = NULL` — and `nudgeable_sessions_for_slot` then counts zero, so the test silently asserts nothing.

**(c) The member must not have the same row id as the slot.** The test asserts a count for `owner.id`, so if the seeded member happened to get that same integer, an implementation that wrongly keyed on `member_id` would pass anyway and the test would prove nothing about the key — which is the whole point of Step 2. `_create_registered_slot_member` (`:122-152`) already solves this: it inserts two throwaway "offset" members first and ends with `assert member.id != slot.id`. Reuse it; do **not** substitute `agent_mail_service.get_or_create_slot_member` (used at `:244`) here, which offers no such guarantee.

So seed first, then discover the same panes. Note `_create_live_slot_launch_session` (`:155-195`) is *nearly* the helper you want but sets `session_key=f"tmux:{target}"` and leaves `pane_id` NULL, so sync would not match it. Add a purpose-built one that takes **all** the slot's panes at once — one member, N sessions, because `_create_registered_slot_member` builds `identity_key=f"slot:test:{slot.id}"` and calling it twice for one slot would violate that column's unique constraint (`database.py:341`):

```python
async def _seed_observed_panes(db, preset, slot, panes):
    """One slot member with N observed sessions, each shaped so a later
    sync_observed_sessions() with the same pane RE-BINDS it to this member
    rather than creating a repo member (_member_for_existing_observed_session).

    panes: list of (pane_id, tmux_target).
    """
    member = await _create_registered_slot_member(db, slot)   # guarantees member.id != slot.id
    for pane_id, target in panes:
        db.add(
            MailAgentSession(
                member_id=member.id,
                provider=slot.provider,          # must equal the discovered provider
                source="observed",
                session_key=f"tmux:{pane_id}",   # sync keys on pane_id, not target
                pane_id=pane_id,
                cwd=slot.repo_path,
                tmux_target=target,
                team_preset_id=preset.id,
                team_slot_id=slot.id,
                mailbox_status="observed",
                last_seen_at=datetime.utcnow(),
            )
        )
    await db.commit()
    return member


def _pane(*, pane_id, target, cwd):
    """The discovery dict shape. Keys copied from tests/agent_mail/test_registry.py:702-713."""
    return {
        "provider": "codex-cli",   # _team's slots use this, and it is in TMUX_WAKE_PROVIDERS
        "provider_display_name": "Codex",
        "tmux_target": target,
        "session_name": target.split(":")[0],
        "window_name": "main",
        "pane_id": pane_id,
        "cwd": cwd,
        "pid": "4242",
        "status": "active",
    }


async def _launcher_that_must_not_run(*_args, **_kwargs):
    raise AssertionError("dispatch launched despite an ambiguous slot")
```

```python
@pytest.mark.asyncio
async def test_ambiguous_slot_blocks_and_leases_nothing(db, monkeypatch):
    """Spec §4.2. Two nudgeable panes on the owner slot → held, and CRUCIALLY
    no workspace leased: an ambiguous slot must never hold a lease it cannot be
    briefed about.
    """
    preset, slots, scope = await _team(db)
    owner = next(slot for slot in slots if slot.display_name == "Backend SME")
    await _seed_observed_panes(db, preset, owner, [("%1", "w:0.1"), ("%2", "w:0.2")])
    monkeypatch.setattr(
        "app.services.agent_mail_service.discover_agent_sessions",
        lambda: [
            _pane(pane_id="%1", target="w:0.1", cwd=owner.repo_path),
            _pane(pane_id="%2", target="w:0.2", cwd=owner.repo_path),
        ],
    )
    assert len(await agent_mail_service.nudgeable_sessions_for_slot(db, owner.id)) == 2

    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=91,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=_launcher_that_must_not_run,
        issue_labels_by_number={91: ["area:backend"]},
    )

    await db.refresh(item)
    assert item.dispatch_status == "pending"
    assert item.owner_slot_id == owner.id
    assert item.pending_reason == "queued_ambiguous_sessions"
    assert "w:0.1" in item.status_note and "w:0.2" in item.status_note
    leased = (
        await db.execute(
            select(GithubWorkspace).where(GithubWorkspace.leased_item_id == item.id)
        )
    ).scalars().all()
    assert leased == []        # the load-bearing half
```

The `assert ... == 2` before dispatching is not redundant: it separates "the gate works" from "the fixture built what I think it built". Given (b) above, a fixture that silently produced repo members would otherwise make the *whole* test vacuous while still passing for the wrong reason — the item would be held, but by `queued_no_workspace` or nothing at all.

`_launcher_that_must_not_run` raising is the other half. Asserting the absence of a launch from the item's fields alone would pass against an implementation that launched and then reset them.

Note `_item` (`:108-119`) looks like the right fixture helper and is **not** — it returns a `(item, labels)` tuple and has no call sites anywhere in the suite. Do not use it; build the item inline as `test_dispatch_pending_launches_and_marks_dispatched` (`:651-689`) does.

Then, following the same shape, one test each for:

- **The check re-synced rather than trusting stale rows.** Seed the DB with **one** session for the owner slot, then have discovery return **two**. Dispatch must still block. This is the Finding 17 case: an implementation that counts DB rows without syncing first sees one, proceeds, and hands the brief to `auto_nudge_members`, which *does* sync (`:1131`) and then coin-flips between the two panes it finds. Nothing detects it.
- **Discovery returning nothing for a populated slot holds.** Seed one session, then have discovery return `[]`. Assert `pending_reason == "queued_ambiguous_sessions"` and no lease. This is the fail-closed half; see Step 4 for why the pre-sync count has to be captured before the sync runs.
- **One nudgeable pane dispatches normally.** The regression guard. Without it, an off-by-one (`> 0` instead of `> 1`) blocks *every* dispatch and every other test in the file that expects a successful dispatch starts failing for a reason that looks unrelated.
- **An empty slot with no prior sessions still dispatches** — discovery `[]`, DB `[]`. This is Task 10 Step 2's spawn-fallback path, and it must not be caught by the fail-closed rule. It is the case that makes "populated" in the bullet above load-bearing rather than decorative.

- [ ] **Step 4: Run and watch them fail**

Run: `python -m pytest tests/agent_teams/test_github_dispatch_service.py -k ambiguous -v`
Expected: FAIL — the item reaches `dispatched` and `_launcher_that_must_not_run` raises `AssertionError`.

- [ ] **Step 5: Implement the gate**

In `dispatch_pending`, in the slot Task 4 emptied — after the `slot_is_busy` block (ending `:214`) and **before** `acquire` (`:222`):

```python
            ambiguity_note = await self._session_ambiguity_note(db, owner_slot_id)
            if ambiguity_note is not None:
                item.owner_slot_id = owner_slot_id
                item.routing_method = method
                item.pending_reason = "queued_ambiguous_sessions"
                item.status_note = ambiguity_note
                item.updated_at = datetime.utcnow()
                await db.commit()
                continue
```

And the helper, on `GithubDispatchService`:

```python
    async def _session_ambiguity_note(
        self, db: AsyncSession, owner_slot_id: int
    ) -> str | None:
        """Why this slot cannot be safely briefed, or None if it can.

        Counts what _nudge_session_for_member would choose among. Two or more
        candidates means the brief goes to an arbitrary pane (§4.2) — silently,
        which is why blocking is strictly more visible even though it stalls the
        queue.

        Runs BEFORE acquire so an ambiguous slot never holds a lease it cannot
        be briefed about, and re-syncs first: dispatch_pending never calls
        sync_observed_sessions, so counting stored rows would count whatever a
        human's last visit to the Agent Mail page left behind, while the live
        nudge syncs and then picks from the fresh set. That skew IS Finding 17.
        """
        member = await self._slot_member(db, owner_slot_id)
        if member is None:
            # No mail identity yet: nothing to be ambiguous between, and the
            # spawn path will create one. Not a fail-closed case.
            return None

        # Captured BEFORE the sync, which deletes rows discovery no longer sees
        # (_remove_stale_observed_sessions, :530-548). After it, a discovery
        # failure and a genuinely emptied slot look identical.
        known_before = len(
            await agent_mail_service.nudgeable_sessions_for_slot(db, owner_slot_id)
        )
        try:
            await agent_mail_service.sync_observed_sessions(db, strict=True)
        except Exception:
            logger.exception(
                "session discovery failed while checking slot %s for ambiguity",
                owner_slot_id,
            )
            return (
                "Session discovery failed, so the owning pane could not be "
                "confirmed. Holding rather than briefing an unknown session."
            )

        candidates = await agent_mail_service.nudgeable_sessions_for_slot(
            db, owner_slot_id
        )
        if len(candidates) > 1:
            targets = ", ".join(sorted(str(s.tmux_target) for s in candidates))
            return (
                f"{len(candidates)} nudgeable sessions on this slot ({targets}). "
                "The dispatch brief would reach an arbitrary one. Converge the "
                "slot to a single session, then this item dispatches itself."
            )
        if not candidates and known_before:
            return (
                f"Discovery found no sessions for this slot, but {known_before} "
                "was expected. Treating zero as unverified rather than empty."
            )
        return None
```

Three things not to change:

- **`len(candidates) > 1`, not `>= 1`.** One live session is the *normal* state under one-session-per-slot; that is the entire premise of G2. `>= 1` blocks every dispatch forever.
- **`known_before` is captured before the sync.** `sync_observed_sessions` deletes observed rows discovery no longer returns (`_remove_stale_observed_sessions`, `:530-548`), so reading the count afterwards makes a discovery failure indistinguishable from a slot whose panes genuinely closed. Ordering is the whole mechanism of the fail-closed rule.
- **`not candidates and not known_before` returns None.** An empty slot dispatches and spawns (Task 10 Step 2). Fail-closed applies to *lost* evidence, not absent evidence — otherwise a fresh team could never be dispatched to at all.

`agent_mail_service` is already imported at module scope (`github_dispatch_service.py:21`), so no local import is needed; `slot_has_live_owner_session` reached into `agent_mail_service._effective_status` the same way before Task 4 deleted it.

- [ ] **Step 6: Label the new pending reason in the UI**

`pendingReasonLabel` (`AutonomyPanel.tsx:85-96`) returns `null` for an unrecognised reason, and `null` renders nothing — so without this the operator sees an item stuck at `pending` with no reason at all, which is precisely the visibility the §4.2 decision was chosen for. Add beside the other branches:

```tsx
  if (item.pending_reason === 'queued_ambiguous_sessions') {
    return `queued · ${ownerName ?? 'owner'} has multiple sessions`
  }
```

The competing targets are already visible: `status_note` renders at `:357-358`. Note this is the *only* frontend change in either PR — the workspace-lease UI stays out of scope (see "Owed alongside").

- [ ] **Step 7: Run the suite**

Run: `python -m pytest tests/agent_teams/ tests/agent_mail/ -q`
Expected: green. Three things to watch:

- **The `no_discovered_panes` autouse fixture from Step 3 must be in place first.** Without it, every `dispatch_pending` test in the file reads the host's real tmux server and the results differ between machines. If you skipped it because the suite happened to pass, it passed by luck about which panes were open.
- **A test that seeds an observed session and then dispatches will lose that session** to `_remove_stale_observed_sessions` unless discovery returns the same `pane_id`. Task 4 already rewrites or deletes the three tests in this file that seed one (`:1205`, `:1256`, `:1300` via `_create_live_slot_launch_session`), so if you have done PR1 there should be none left — but check `tests/agent_teams/test_agent_team_service.py:849-940`, which seeds four observed sessions. Those tests do not call `dispatch_pending`, so they should be unaffected; confirm that rather than assuming it.
- `tests/agent_mail/` must stay green with `strict` defaulting to `False`. If any existing test changed behaviour, the default leaked.

If a test fails for a reason this list does not explain, that is a signal about the gate, not a chore. Report it.

- [ ] **Step 8: Commit**

```bash
git add -A backend frontend
git commit -m "feat(g2): refuse to dispatch to a slot with ambiguous sessions

_nudge_session_for_member takes the FIRST nudgeable session ordered by
last_seen_at desc, and sync_observed_sessions stamps every pane within
microseconds — so with more than one session on a slot, which pane gets the
brief is a coin flip. Slot 6 carries three today.

Dispatch now counts nudgeable sessions before acquire and holds the item with
pending_reason=queued_ambiguous_sessions, naming the competing targets. Chosen
over persisting the briefed session on the lease, which would re-introduce the
per-item session identity Finding 18 withdrew. Refusing to guess stalls a
queue; guessing delivers a brief to the wrong pane undetectably.

The check syncs discovery ITSELF, immediately before counting. dispatch_pending
never called sync_observed_sessions, so a stored count reflects whenever a
human last opened the Agent Mail page — while the live nudge syncs first and
picks from the fresh set. The stale check would pass and the delivery would
still coin-flip: Finding 17 rebuilt inside its own fix.

And it fails closed on lost evidence, not on absent evidence. The pre-sync
count is captured BEFORE the sync, because the sync deletes rows discovery no
longer sees — after it, a discovery failure and a genuinely emptied slot are
indistinguishable. A slot that never had sessions still dispatches and spawns.

sync_observed_sessions gains strict=True for callers that gate a decision on
the result; every existing caller is a best-effort refresh and keeps the
lenient default."
```

---

### PR2 gate

- [ ] Full suite green: `python -m pytest tests/agent_teams/ tests/agent_mail/ -q`
- [ ] One PR into `feature/autonomous-github-dispatch`. Do not merge.
- [ ] Report anything adapted or omitted.

---

## Owed alongside, not inside, these PRs

These are recorded in spec §9 and must **not** be folded into PR1 or PR2:

- **`CLAUDE.md` is wrong about migrations.** It says "No database migration system — schema changes require deleting the db"; the ladder has existed at `app/database.py:290` for some time. Separate `docs:` commit — it misleads every reader of the repo, not just this design.
- **PR A's §2.9/§2.10b** describe a force-release endpoint as "deliberately not built" and the liveness gate as "the single arbiter of release". G2 §6 reverses both. Already amended in the spec docs; no code owed.
- **`/dispatch-status` has no authentication** (§3.1b). Owner-only release is *cooperative* validation — the MCP shim derives `reporting_slot_id` from the caller's registration, but a direct HTTP caller can pass any slot id. Endpoint-wide auth is owed **before autonomy runs against anything but a trusted local team**, and is out of scope here because fixing one branch would imply the other eight are protected.
- **§6's three mitigations are Tasks 8 and 9 — they are in PR1, not owed.** What remains owed is the *frontend* surface: nothing in `frontend/src` currently reads `lease_state`, `leased_at` or the reprobe endpoint (verified by grep), so the whole workspace-lease UI is unbuilt. Task 9 makes the API expose lease age, reminder state and the token; the React page that shows them is a separate frontend change and is out of scope for both PRs.
- **A pre-existing failure** at `tests/test_multi_provider_smoke.py:54` (stale monkeypatch on `agent_bridge_api.discover_agent_sessions`) needs its own issue.

## Deployment (operator, not implementer)

Spec §7 owns this. The implementer does **not** deploy, restart the backend, converge slot 6, or re-enable autonomy. Item 23 stays escalated and must not be retried.
