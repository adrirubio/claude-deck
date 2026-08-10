# PR0 — Agent Mail Capability Tokens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every Agent Mail writer a cryptographic identity — a per-session capability token bound to the tmux pane the session actually runs in — and harden the operator-only routes behind a shared secret, so that PR1's release protocol can trust who is talking to it.

**Architecture:** Registration mints a `secrets.token_urlsafe(32)` capability token, stores only its SHA-256 hash on `mail_agent_sessions`, and returns the plaintext exactly once. The route that registers also derives the caller's tmux pane from the kernel (`/proc/net/tcp` + `/proc/net/tcp6` → peer pid → ppid walk → `agent_pane_bindings`), so a session's claimed slot is checked against where it physically runs. Mail writes and `/dispatch-status` then resolve their actor from the token instead of from a body field. A new `mail_capability_tokens_required` flag keeps the whole enforcement path backward-compatible while it is `False`; the operator-route hardening and the force-release API migration take effect immediately.

**Tech Stack:** FastAPI, async SQLAlchemy + aiosqlite, pydantic-settings, pytest + pytest-asyncio + httpx `ASGITransport`, React 19 + TypeScript (two write call sites), Python `stdlib` only for the resolver (`socket.inet_pton`, `/proc`, `subprocess` for `tmux list-panes`).

**Spec:** `docs/superpowers/specs/2026-08-05-distinct-approver-identity-design.md` — revision 17, HEAD `4810c1b`. This plan implements **PR0 only**: spec §3.1–§3.8 plus §4.6a requirements 1–4. PR1 (release protocol) and PR2 follow in their own plans.

**Precedence, when documents disagree** — one rule, and the same rule appears in the Codex handoff prompt:

| Situation | What to do |
| --- | --- |
| The plan and the spec disagree, **and the plan marks the difference "Correction (date, review)"** | The plan wins. The correction was verified against source; the spec text was not updated. |
| The plan and the spec disagree, and the plan does **not** mark it | **Stop and report.** An unmarked divergence means one of us is wrong, and neither of us knows which. |
| The plan and the **code** disagree | **Stop and report.** A moved line number is fine to adapt to; a different *shape* means the reasoning may not hold. |

## Global Constraints

These apply to **every** task. They are not negotiable and several are safety rules earned from live incidents.

**Working environment — you are on the SAME machine as the live soak**

- Work only in `/home/juan/work/repos/juanrubio/claude-deck-g1`.
- **Never** touch `/home/juan/work/repos/juanrubio/claude-deck`. It is the live soak checkout and holds the live DB with the 28 work items that made Findings 17–20 provable. Those rows are not regenerable and the same file serves the running backend.
- **Never** touch `/home/juan/work/repos/tizonia/`. Five live sessions hold it as their cwd. Do not `tmux send-keys`, do not kill panes, do not restart sessions. `tmux list-panes` / `list-sessions` / `show-environment` are read-only and allowed; run environment probes on a throwaway socket (`tmux -L <name>`, killed afterwards).
- Do **not** restart, stop, or reload the running uvicorn (PID 2206652, port 8000).
- Autonomy stays **OFF** (`autonomy_enabled = 0` on both presets). Do not enable it "to test".
- Do not spawn or kill agent sessions. Do not hand-edit DB rows. Do not retry work item 23 or any other escalated item.
- Live DB reads are read-only: `sqlite3.connect("file:/home/juan/work/repos/juanrubio/claude-deck/backend/claude_registry.db?mode=ro", uri=True)`.
- `rm` is denied by the permission layer. Move files to `/tmp` with `mv`, or write to a fresh filename.

**Git**

- Branch from `origin/feature/autonomous-github-dispatch`, never from the local ref — the live worktree holds it.
- g1 shares `.git` with the live checkout. Forbidden: `git worktree prune`, `git gc`, `git stash`, `git reset --hard`, `git branch -f`, any ref deletion, and checking out a branch the live worktree has.
- **Never** `git checkout -- <file>` on uncommitted work. Reverse an edit by replacing the exact string you inserted.
- Commit locally at the end of every task. **Do not push.** Never merge or push to `master`.

**Forbidden operations** (all of these have caused incidents)

- **No new `dispatch_status` values.** The vocabulary is closed.
- Never print the PAT value or any token plaintext into logs, test output, or commit messages. `backend/.env` stays mode `0600` and gitignored.
- Never `export` a secret into tmux's global environment — `tmux show-environment -g` is readable from every pane.
- The migration ladder is **additive only**. No `DROP`, no table rebuild, no "delete the db and let `create_all` redo it".
- Do not rewrite a test that was already failing before you started. Report it.

**Code style**

- `python3`, not `python` — `python` is not on PATH.
- The virtualenv is `backend/venv`, not `.venv`.
- Type hints throughout, async/await, pydantic models for validation.
- Conditional updates use **ordinary SQL `=`**, never a null-safe operator. This is normative (spec revision 17) and deliberately untestable: `acquire` can never produce a row with a NULL `lease_token`, so the difference is invisible to every test that can exist. A shared conditional-update helper must not offer a null-safe mode. **This is an explicit code-review check, not a test.**

**Testing**

- `cd backend` **first**, every time. The DB path is CWD-relative.
- Always `pytest -p no:warnings`.
- **Baseline, measured on this machine at the start of PR0.** Two figures, because the tasks below quote the first and the risky tasks need the second:
  - `pytest tests/agent_teams/ tests/agent_mail/ -q -p no:warnings` → **`454 passed in 31.61s`**. Every "Expected: N passed" in this plan counts up from this number.
  - `pytest tests/ -q -p no:warnings` → **`622 passed, 1 failed`**. The one failure is **pre-existing on a clean tree at `4810c1b`** and unrelated to this spec: `tests/test_multi_provider_smoke.py::test_agent_bridge_session_filter_smoke` calls `agent_bridge_api.list_sessions` without awaiting it (`RuntimeWarning: coroutine 'list_sessions' was never awaited`), so its `calls` list is empty and `assert calls == [None, "codex-cli"]` fails. **Do not fix it in this PR** — report it, per the standing rule on pre-existing failures. Run the full suite at Tasks 8 and 9, which are the ones that touch `agent_teams.py`, and expect exactly this one failure and no other.
- Any task that ends with fewer passing tests than it started with, minus the tests it deliberately re-authored, is a regression — stop and report.
- **The expected counts, all of them, in one place.** Each task's own step repeats its number; this table is the cross-check. Every figure is *collected cases*, not test functions — six tests in this plan are parameterized, so the two differ.

  | After task | `test_capability_tokens.py` | `test_peer_process.py` | new cases (cumulative) | `agent_teams/ + agent_mail/` | whole `tests/` |
  | --- | --- | --- | --- | --- | --- |
  | baseline | — | — | 0 | **454** | **622** + 1 failed |
  | 1 | 4 | — | 5 | 458 | 627 |
  | 2 | 4 | 13 | 18 | 471 | 640 |
  | 3 | 13 | 13 | 27 | 480 | 649 |
  | 4 | 25 | 15 | 46 | 497 | 668 |
  | 5 | 33 | 15 | 54 | 505 | 676 |
  | 6 | 33 | 15 | 58 | 509 | 680 |
  | 7 | 33 | 15 | 75 | 526 | 697 |
  | 8 | 33 | 15 | 87 | 538 | 709 |
  | 9 | 33 | 15 | 96 | 547 | 718 |
  | 10 | 35 | 15 | 106 | 557 | 728 |

  `test_capability_tokens.py` is the file to watch, because five different tasks append to it and one of them (Task 3) puts both service-level and route-level tests there — Step 7 says "append to `test_capability_tokens.py`" while naming `test_api.py` only as the place to *copy the `client` fixture from*. Read that instruction carefully; creating a second file there breaks every later per-file figure in this column while leaving the suite totals correct, which is the confusing way to be wrong.

  Four tasks write fewer functions than they collect cases: Tasks 7, 8 and 9 write 11, 8 and 8 functions that collect as 17, 12 and 9, because `test_non_owner_is_refused_and_changes_nothing` (7 rows), `test_unconfigured_install_refuses_with_503_whatever_the_header` (3), `test_near_miss_tokens_are_invalid` (3), `test_force_must_be_true_and_the_lease_is_untouched` (2) and `test_force_release_requires_reason_and_acquisition` (2) are parameterized. The whole-`tests/` column runs ahead of the suite column by 3 from Task 4 onward, from Task 1's one migration-ladder case in `tests/test_sqlite_compat_migrations.py` and Task 4's two in `tests/test_agent_bridge_spawn.py` — both outside these two directories.

  Two mid-task figures sit *below* the table on purpose and are not errors: Task 4 Step 14's `494` (Steps 17-24 add five more cases afterwards) and Task 9's per-file `32` for the two workspace files.

  Where a task's own step and this table disagree, **the measurement wins over both**. Report the number pytest actually prints; a mismatch means either a test was collected twice or one of these arithmetic chains is off, and both are worth a sentence in the handoff rather than a silent adjustment.
- Route probes use `app.dependency_overrides[get_db]` plus `httpx.ASGITransport`.
- **`httpx.ASGITransport` fakes the client port** — `scope["client"]` is `("127.0.0.1", 123)`. Every binding test must inject or override the peer resolver; none of them can rely on a real socket.
- Assert on rows **read back with raw SQL**, not on the ORM objects you just wrote.
- `github_workspaces.path` is UNIQUE — parameterize the path in every fixture that makes more than one.
- A WAL race needs a **file-backed** DB; the in-memory engine in `tests/agent_mail/conftest.py` cannot show it.
- zsh eats unquoted globs. Quote every `--include="*.py"`.
- Override a setting in a test with `monkeypatch.setattr(settings, "<name>", value)` — the in-repo idiom. Do not construct a second `Settings()`.

**Stop and report**

If a step's preconditions do not hold — a function has a different shape, a test asserts the opposite of what the plan says, a line number points somewhere unrecognizable — stop and report before writing code. Do not "adapt" your way past a contradiction.

## File Structure

Nine new files — two in `app/`, four test files, two in `frontend/src/`, one under `docs/deploy/`; everything else is an edit to an existing one. **Do not split `agent_mail_service.py` or `github_dispatch_service.py`** — they are large, but the codebase keeps service logic in one file per domain and a split here would collide with PR1.

| File | Create / Modify | Responsibility |
| --- | --- | --- |
| `backend/app/config.py` (between `:49` and `:51`) | Modify | Two settings: `mail_capability_tokens_required: bool = False`, `operator_token: str = ""` |
| `backend/app/database.py` (after `:359`) | Modify | Three additive ladder rungs on `mail_agent_sessions` |
| `backend/app/models/database.py` | Modify | Three new `MailAgentSession` columns; new `AgentPaneBinding` table |
| `backend/app/models/schemas.py` | Modify | `capability_token` on `MailAgentRegisterResponse`; force-release request rewrite; drop the `lease_token` projection |
| `backend/app/utils/peer_process.py` | **Create** | Kernel-derived resolver: peer socket → pid → tmux pane pid + proc start |
| `backend/app/api/v1/deps.py` | **Create** | `mail_session`, `require_mail_session`, `require_session_slot`, `derive_member_id`, `require_operator`, `OperatorPrincipal` |
| `backend/app/services/agent_mail_service.py` | Modify | `hash_capability_token`, `ensure_capability_token`, `peek_session_by_key` — three new methods **beside** `register_session`, not inside it (Task 3 says why) |
| `backend/app/services/agent_team_service.py` | Modify | Write and commit the `agent_pane_bindings` row on both launch paths (`:569` reuse, `:637` spawn) — without this every Deck-launched pane gets `409 bind_pending` forever |
| `backend/app/services/agent_bridge/spawn.py` | Modify | Return the pane pid from `new-session -P -F '#{pane_pid}'` so the binding writer has something to key on |
| `backend/app/api/v1/agent_mail.py` | Modify | Binding policy at the `register_agent` route; token dependency on the four write routes |
| `backend/app/api/v1/agent_teams.py` | Modify | `/dispatch-status` authorization resolver; `require_operator` on operator routes; force-release migration |
| `backend/app/services/github_workspace_service.py` | Modify | `release_by_token` predicate + the seven-column clear at one `now` |
| `backend/mcp_shim/agent_mail_server.py` | Modify | Capture the minted token; send `X-Deck-Session-Token` on every bridge call |
| `frontend/src/lib/operatorToken.ts` | **Create** | Per-tab operator-token store, cached; `sessionStorage` so the secret dies with the tab |
| `frontend/src/lib/api.ts` | Modify | `X-Deck-Operator-Token` injection into `apiClient` (`:99-131`) |
| `frontend/src/features/agent-mail/api.ts` | Modify | The three write helpers gain an actionable `401` message |
| `frontend/src/features/config/OperatorTokenCard.tsx` | **Create** | Where the operator pastes the token; never renders it back |
| `README.md` (after `:114`) | Modify | Linux prerequisite bullet, scoped to pane binding rather than to the app |
| `docs/deploy/pr0-capability-tokens-rollout.md` | **Create** | The four ordered steps; two restarts for two credentials |
| `backend/tests/agent_mail/test_capability_tokens.py` | **Create** | Spec §3.7 tests 1–22 |
| `backend/tests/agent_mail/test_peer_process.py` | **Create** | Resolver unit tests (parsers, both address families) |
| `backend/tests/agent_mail/test_api.py` | Modify | Four existing tests gain a token |
| `backend/tests/agent_mail/test_external_api.py` | Modify | The tokenless-legacy-post test (`:118-137`) |
| `backend/tests/agent_mail/test_mcp_shim.py` | Modify | The exact five-key payload equality (`:13-47`) |
| `backend/tests/agent_mail/test_dispatch_status_tool.py` | Modify | 18 call sites; 12 carry `reporting_slot_id`, 5 do not |
| `backend/tests/test_agent_bridge_spawn.py` | Modify | Three of its 13 tests re-authored for the added `-P -F` argv pair (Task 4 names them) |
| `backend/tests/agent_teams/test_agent_team_service.py` | Modify | Binding-writer tests on both launch paths; 41 tests today |
| `backend/tests/agent_teams/test_operator_auth.py` | **Create** | Spec §3.7 test 20 — the eight-case matrix, for each of the two operator routes |
| `backend/tests/agent_mail/test_operator_mail_writes.py` | **Create** | Task 10 — the operator credential on the UI's three writes; §3.6 has no test today, which is why its two false claims survived |
| `backend/tests/agent_teams/test_github_workspace_api.py` | Modify | 8 call sites gain the operator header (Task 8); then the force-release migration — six tests, incl. inverting the disclosure assertion (Task 9) |

## Task Index

| Task | Deliverable | Spec |
| --- | --- | --- |
| 1 | Settings, ladder rungs, `AgentPaneBinding` | §3.1, §3.2, §3.3 |
| 2 | `app/utils/peer_process.py` — the kernel resolver | §3.3 |
| 3 | Mint-once in `register_session`; `capability_token` on the response | §3.4 |
| 4 | Registration policy + pane binding at the `register_agent` route; the launcher writes the binding row | §3.3, §3.3a, §3.8 |
| 5 | `mail_session` / `require_session_slot`; the four write routes; grace mode | §3.5 |
| 6 | Shim: capture the token, send the header | §3.4, §3.8 |
| 7 | `/dispatch-status` authorization resolver | §3.5a |
| 8 | `require_operator` and the operator routes | §3.6a |
| 9 | Force-release API migration | §4.6a req. 1–4 |
| 10 | The operator credential reaches the UI (no new route; §3.6's actor mechanism refuted) | §3.6, §3.6a |
| 11 | README Linux prerequisite; the four-step rollout note | §3.8 |

### Spec sections this plan deliberately does **not** implement

The PR boundary rule is §2.1's: *each artifact ships in the earliest PR that has a consumer for it, and every artifact's tests ship with the artifact.* Three sections in §3 fail that test and belong to PR1. They are named here so a reviewer comparing spec to plan sees a decision rather than a gap.

| Spec section | Why it is PR1, not PR0 |
| --- | --- |
| **§3.4a** — `record_ack_received` refuses `tokens_not_enforced` in grace mode; `ack_enforcement_epoch` stamps the regime | Both are guards over columns that **do not exist in PR0**. Verified: `grep -rn "ack_approver_member_id\|ack_evidence_message_id\|ack_enforcement_epoch" backend/app/` returns **nothing**, and the spec creates all three in §4.1 — PR1's schema ladder. Today's `record_ack_received` (`github_dispatch_service.py:681-688`) writes only `ack_received_at`, `last_nudge_at`, `updated_at`; there is no approver evidence in PR0 for a grace-mode refusal to protect. Adding the refusal here would guard nothing and would break the ack path that PR0 must leave working. Its test is spec test 27, which asserts on `ack_approver_member_id` — unwritable in PR0. |
| **§3.5's removal of `member_id` from `agent_inbox`** | Removing it breaks the pre-upgrade shim that grace mode exists to protect (Task 5's Correction says why). The parameter stays in PR0 and is *derived-over*; **PR1 deletes it** after the panes have restarted. |
| **§3.5a's `revision_requested` → `409 use_deck_approve_work_item`** | The replacement tool `deck_approve_work_item` is §4.3a, a PR1 artifact. Refusing the status before its replacement exists would leave an agent with neither. Task 7 implements §3.5a's *authorization* rows only and says so. |

**§3.4a's mutation-table row is therefore PR1's to satisfy, not PR0's.** Task 5's commit message must not cite §3.4a — it implements §3.5 alone.

---

### Task 1: Schema — two settings, three session columns, one new table

**Files:**
- Modify: `backend/app/config.py:49-51`
- Modify: `backend/app/models/database.py:388-396` (three columns after `team_slot_id`)
- Modify: `backend/app/models/database.py` (new `AgentPaneBinding` class, after `GithubWorkspace` ends at `:320`)
- Modify: `backend/app/database.py:359` (three ladder rungs, inserted **after** the `team_slot_id` rung)
- Test: `backend/tests/agent_mail/test_capability_tokens.py` (create)

**Interfaces:**
- Consumes: nothing. This is the first task.
- Produces:
  - `settings.mail_capability_tokens_required: bool` (default `False`) and `settings.operator_token: str` (default `""`).
  - `MailAgentSession.capability_token_hash: str | None`, `.bound_pane_pid: int | None`, `.bound_pane_proc_start: str | None`.
  - `AgentPaneBinding` with `id`, `pane_pid: int`, `pane_proc_start: str`, `slot_id: int | None`, `preset_id: int | None`, `tmux_target: str | None`, `created_at: datetime`, and `UniqueConstraint("pane_pid", "pane_proc_start", name="uix_pane_binding")`.

**Why all of this lands in one task:** a reviewer cannot usefully accept the settings while rejecting the columns — nothing reads either one yet, and every later task consumes both. The independently testable deliverable is "the schema exists and the ladder is idempotent."

**Two deliberate deltas from the spec:**

1. **The spec's `AgentPaneBinding` sketch types `slot_id` and `preset_id` as `Mapped[int]`** (§3.3). The plan makes both **nullable**, because `slot_id`'s FK is `ondelete="SET NULL"` — a non-nullable column with a SET NULL cascade is a contradiction SQLite will hit the moment a slot is deleted. `preset_id` follows `MailAgentSession.team_preset_id`, which is nullable for the same reason.
2. **`agent_pane_bindings` is created by `create_all`, not by a ladder rung.** It is a brand-new table, so `create_all` makes it on every existing database. Only the three `mail_agent_sessions` columns need rungs, because that table already exists in the live DB.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/agent_mail/test_capability_tokens.py`:

```python
"""Spec §3.7 — capability token tests for PR0."""
import pytest
from sqlalchemy import text

from app.config import settings
from app.models.database import AgentPaneBinding, MailAgentSession


def test_capability_token_settings_default_to_grace_mode():
    """PR0 ships enforcement off, so an unconfigured deploy behaves exactly as before."""
    assert settings.mail_capability_tokens_required is False
    assert settings.operator_token == ""


def test_session_model_carries_the_three_binding_columns():
    columns = MailAgentSession.__table__.columns
    assert columns["capability_token_hash"].nullable is True
    assert columns["bound_pane_pid"].nullable is True
    assert columns["bound_pane_proc_start"].nullable is True


def test_pane_binding_table_is_unique_on_pid_and_proc_start():
    names = {c.name for c in AgentPaneBinding.__table__.columns}
    assert names == {
        "id",
        "pane_pid",
        "pane_proc_start",
        "slot_id",
        "preset_id",
        "tmux_target",
        "created_at",
    }
    unique = {
        tuple(sorted(c.name for c in constraint.columns))
        for constraint in AgentPaneBinding.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("pane_pid", "pane_proc_start") in unique


@pytest.mark.asyncio
async def test_pane_binding_round_trips(db):
    """create_all makes the table; a row survives a raw-SQL read-back."""
    db.add(
        AgentPaneBinding(
            pane_pid=4242,
            pane_proc_start="123456",
            slot_id=None,
            preset_id=None,
            tmux_target="deck-team:0.1",
        )
    )
    await db.commit()

    row = (
        await db.execute(
            text(
                "SELECT pane_pid, pane_proc_start, tmux_target "
                "FROM agent_pane_bindings WHERE pane_pid = 4242"
            )
        )
    ).first()
    assert row == (4242, "123456", "deck-team:0.1")
```

`db` is the existing fixture in `backend/tests/agent_mail/conftest.py`. Note its shape: it yields an **`AsyncSession`**, not a sessionmaker, from an in-memory engine with `create_all` already run and `expire_on_commit=False`. Do not add a second fixture.

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_mail/test_capability_tokens.py -q -p no:warnings
```

Expected: collection error — `ImportError: cannot import name 'AgentPaneBinding' from 'app.models.database'`.

- [ ] **Step 3: Add the two settings**

In `backend/app/config.py`, between `github_brief_delivery_max_nudges: int = 2` (`:49`) and the blank line before `# Server settings` (`:51`):

```python
    github_brief_delivery_max_nudges: int = 2

    # Agent Mail identity settings
    mail_capability_tokens_required: bool = False
    operator_token: str = ""

    # Server settings
```

`operator_token` is read from `backend/.env` in deployment. Never commit a value and never `export` it — the setting default stays `""` in source.

- [ ] **Step 4: Add the three session columns**

In `backend/app/models/database.py`, immediately after the `team_slot_id` column (`:388-390`) and before `mailbox_status`:

```python
    team_slot_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agent_team_slots.id", ondelete="SET NULL"), nullable=True
    )
    capability_token_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    bound_pane_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bound_pane_proc_start: Mapped[str | None] = mapped_column(String, nullable=True)
    mailbox_status: Mapped[str] = mapped_column(String, default="connected", nullable=False)
```

- [ ] **Step 5: Add the `AgentPaneBinding` table**

In `backend/app/models/database.py`, after `GithubWorkspace`'s `__table_args__` block ends (`:320`) and before `class BridgeSessionAttachment`:

```python
class AgentPaneBinding(Base):
    """Which tmux pane a launched slot physically occupies.

    Written by the launcher at launch time and committed on its own, ahead of
    the slot loop's single commit, because the pane it describes can register
    with Agent Mail before that loop finishes. A binding that is not visible
    yet is indistinguishable from a pane that was never launched.
    """

    __tablename__ = "agent_pane_bindings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pane_pid: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    pane_proc_start: Mapped[str] = mapped_column(String, nullable=False)
    slot_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agent_team_slots.id", ondelete="SET NULL"), nullable=True
    )
    preset_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agent_team_presets.id", ondelete="SET NULL"), nullable=True
    )
    tmux_target: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("pane_pid", "pane_proc_start", name="uix_pane_binding"),
    )
```

`String`, `Integer`, `DateTime`, `ForeignKey`, `UniqueConstraint`, `Mapped`, `mapped_column` and `datetime` are all already imported at `models/database.py:1-6`. Add nothing to the import line.

- [ ] **Step 6: Add the three ladder rungs**

In `backend/app/database.py`, immediately after the `team_slot_id` rung (`:358-359`) and before the blank line that precedes `PRAGMA table_info(agent_team_slots)`:

```python
    if session_columns and "team_slot_id" not in session_columns:
        await conn.execute(text("ALTER TABLE mail_agent_sessions ADD COLUMN team_slot_id INTEGER"))
    if session_columns and "capability_token_hash" not in session_columns:
        await conn.execute(
            text("ALTER TABLE mail_agent_sessions ADD COLUMN capability_token_hash TEXT")
        )
    if session_columns and "bound_pane_pid" not in session_columns:
        await conn.execute(
            text("ALTER TABLE mail_agent_sessions ADD COLUMN bound_pane_pid INTEGER")
        )
    if session_columns and "bound_pane_proc_start" not in session_columns:
        await conn.execute(
            text("ALTER TABLE mail_agent_sessions ADD COLUMN bound_pane_proc_start TEXT")
        )
```

The `session_columns and` guard is not decorative: on a fresh database `create_all` has already made the table with all its columns, and `PRAGMA table_info` on a table that does not exist returns an empty set. Copy the guard exactly as the two rungs above it use it.

- [ ] **Step 7: Run the new tests to verify they pass**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_mail/test_capability_tokens.py -q -p no:warnings
```

Expected: `4 passed`.

- [ ] **Step 8: Run the full baseline suite**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_teams/ tests/agent_mail/ -q -p no:warnings
```

Expected: `458 passed` (the 454 baseline plus this task's 4). Nothing in the baseline reads the new columns yet, so any failure here is a real regression — stop and report.

- [ ] **Step 9: Write the ladder regression test**

The in-memory conftest engine runs `create_all`, which makes the columns directly and never exercises the ladder. The ladder needs its own test, in the file that already exists for exactly this purpose — `backend/tests/test_sqlite_compat_migrations.py`, which imports `app.database`'s private helpers by name. Append:

```python
@pytest.mark.asyncio
async def test_compat_migrations_add_capability_columns_idempotently():
    """A pre-PR0 mail_agent_sessions table gains the three columns, twice over."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    """
                    CREATE TABLE mail_agent_sessions (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        member_id INTEGER NOT NULL,
                        provider VARCHAR NOT NULL,
                        source VARCHAR NOT NULL,
                        session_key VARCHAR NOT NULL,
                        mailbox_status VARCHAR NOT NULL,
                        last_seen_at DATETIME NOT NULL,
                        created_at DATETIME NOT NULL
                    )
                    """
                )
            )
            expected = {"capability_token_hash", "bound_pane_pid", "bound_pane_proc_start"}
            for _ in range(2):
                await _run_sqlite_compat_migrations(conn)
                columns = await _sqlite_columns(conn, "mail_agent_sessions")
                assert expected <= columns
    finally:
        await engine.dispose()
```

Add `_run_sqlite_compat_migrations` to the existing `from app.database import (...)` block at the top of that file. The second loop iteration is the whole point: without the `not in session_columns` guard, SQLite raises `duplicate column name` and the test fails.

- [ ] **Step 10: Run the ladder test**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/test_sqlite_compat_migrations.py -q -p no:warnings
```

Expected: all pre-existing tests in that file plus the new one pass.

- [ ] **Step 11: Commit**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1 && git add backend/app/config.py backend/app/database.py backend/app/models/database.py backend/tests/agent_mail/test_capability_tokens.py backend/tests/test_sqlite_compat_migrations.py && git commit -m "feat(mail): add capability-token schema and grace-mode settings

Three nullable columns on mail_agent_sessions (capability_token_hash,
bound_pane_pid, bound_pane_proc_start) with additive ladder rungs, plus the
agent_pane_bindings table created by create_all. Two settings ship enforcement
off: mail_capability_tokens_required=False and operator_token=\"\".

Spec: 2026-08-05-distinct-approver-identity-design.md sections 3.1-3.3"
```

---

### Task 2: The kernel resolver — from a TCP peer to a tmux pane

**Files:**
- Create: `backend/app/utils/peer_process.py`
- Test: `backend/tests/agent_mail/test_peer_process.py` (create)

**Interfaces:**
- Consumes: nothing from Task 1. This task is pure `stdlib` and can be built in parallel with Task 1.
- Produces, all in `app.utils.peer_process`:
  - `format_endpoint(host: str, port: int) -> str | None` — a `/proc/net`-style hex endpoint, or `None` if `host` is not an IP literal.
  - `find_socket_inode(host: str, port: int, local_port: int | None = None) -> int | None`
  - `find_pid_for_inode(inode: int) -> int | None`
  - `read_proc_stat(pid: int) -> tuple[int, str] | None` — `(ppid, starttime)`.
  - `list_tmux_pane_pids() -> dict[int, str]` — `{pane_pid: tmux_target}`.
  - `resolve_peer_pane(host: str, port: int, local_port: int | None = None) -> PeerPane | None` where `PeerPane` is a frozen dataclass with `pane_pid: int`, `pane_proc_start: str`, `tmux_target: str | None`, `peer_pid: int`.

**Why this is its own file and its own task:** every function here is a thin wrapper over a kernel interface, all of them are pure, and none of them touch the database or FastAPI. That makes them the only part of PR0 that can be tested without a request, and a reviewer can accept or reject the resolver on its own merits. `app/utils/` currently holds only `path_utils` and `file_utils`; this is the third module, not an addition to either.

**PR0 requires Linux.** Everything here reads `/proc`. Task 11 documents the prerequisite. Every function degrades to `None` or `{}` rather than raising, so a non-Linux host running with `mail_capability_tokens_required = False` still serves requests — it simply never binds a pane.

**Measured facts this task depends on** (re-measured on this machine, 2026-08-09 — do not re-derive them, and stop and report if any turns out false):

| Fact | Measured value |
| --- | --- |
| Hex endpoint, IPv4 `127.0.0.1:8000` | `0100007F:1F40` |
| Hex endpoint, IPv6 `::1:8000` | `00000000000000000000000001000000:1F40` |
| One formatter serves both families | Yes — `inet_pton` then reverse each 4-byte word |
| Inode column in `/proc/net/tcp` and `/proc/net/tcp6` | `line.split()[9]`, identical in both files |
| A loopback connection appears **twice** | Two rows, mirror images. For peer `127.0.0.1:34265` → backend `127.0.0.1:34280`, `/proc/net/tcp` held `local=…:85D9 rem=…:85E8` (the caller's socket, inode 39993300) **and** `local=…:85E8 rem=…:85D9` (the backend's accepted socket, inode 39993301) |
| Therefore the caller's row is matched on **`local_address`** | `parts[1] == format_endpoint(peer_host, peer_port)`, not `parts[2]` |
| `/proc/<pid>/stat` — one parse, two fields | `fields = raw[raw.rindex(")") + 2:].split()`; `int(fields[1])` = ppid (verified against `os.getppid()`), `fields[19]` = starttime; 50 fields total |
| Worst-case **full** `/proc` fd scan (inode absent) | **2.0–6.3 ms** across 140 pids |
| `tmux list-panes -a -F "#{pane_id} #{pane_pid}"` | Works; one line per pane |

The 2–6 ms figure is why the resolver runs **synchronously inside the request handler**. It must: resolving after the response has been sent finds the socket in `TIME_WAIT` with inode `0` and no owning pid. That is a correctness requirement, not a latency preference.

- [ ] **Step 1: Write the failing test for the endpoint formatter**

Create `backend/tests/agent_mail/test_peer_process.py`:

```python
"""Kernel-derived peer resolution (spec section 3.3)."""
import pytest

from app.utils import peer_process


def test_format_endpoint_ipv4():
    assert peer_process.format_endpoint("127.0.0.1", 8000) == "0100007F:1F40"


def test_format_endpoint_ipv6():
    assert peer_process.format_endpoint("::1", 8000) == (
        "00000000000000000000000001000000:1F40"
    )


def test_format_endpoint_rejects_a_hostname():
    """A non-literal host has no /proc/net representation, and must not be guessed at."""
    assert peer_process.format_endpoint("testclient", 123) is None
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_mail/test_peer_process.py -q -p no:warnings
```

Expected: `ModuleNotFoundError: No module named 'app.utils.peer_process'`.

- [ ] **Step 3: Write the formatter**

Create `backend/app/utils/peer_process.py`:

```python
"""Resolve a TCP peer to the tmux pane its process runs in.

Everything here reads Linux kernel interfaces (/proc/net/tcp, /proc/net/tcp6,
/proc/<pid>/stat) and shells out to tmux. On a host without /proc, every
function returns None or an empty mapping rather than raising, so a deployment
with mail_capability_tokens_required = False still serves requests.

The caller MUST invoke resolve_peer_pane synchronously, inside the request
handler. Once the response is sent the peer socket enters TIME_WAIT, its
/proc/net inode reads 0, and no process owns it any more.
"""
import logging
import os
import socket
import subprocess
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

_PROC_NET_TABLES = (
    ("/proc/net/tcp", socket.AF_INET),
    ("/proc/net/tcp6", socket.AF_INET6),
)

# /proc/net/tcp columns: sl local_address rem_address st tx_queue:rx_queue
# tr:tm->when retrnsmt uid timeout inode ...
_LOCAL_ADDRESS_COLUMN = 1
_REMOTE_ADDRESS_COLUMN = 2
_STATE_COLUMN = 3
_INODE_COLUMN = 9

# Kernel TCP state codes, as printed in /proc/net/tcp column 4.
_TCP_ESTABLISHED = "01"

# How far up the process tree to walk before giving up on finding a pane.
_MAX_PARENT_WALK = 32


def format_endpoint(host: str, port: int) -> Optional[str]:
    """Render host:port the way /proc/net/tcp does, or None if host is not an IP.

    The kernel prints each 4-byte word of the address in host byte order, so a
    single formatter serves IPv4 and IPv6 alike: pack, then reverse per word.
    """
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            packed = socket.inet_pton(family, host)
        except (OSError, ValueError):
            continue
        words = [packed[i : i + 4][::-1] for i in range(0, len(packed), 4)]
        return f"{b''.join(words).hex().upper()}:{port:04X}"
    return None
```

- [ ] **Step 4: Run the formatter tests to verify they pass**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_mail/test_peer_process.py -q -p no:warnings
```

Expected: `3 passed`.

- [ ] **Step 5: Commit the formatter**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1 && git add backend/app/utils/peer_process.py backend/tests/agent_mail/test_peer_process.py && git commit -m "feat(mail): add /proc/net hex endpoint formatter

One formatter serves IPv4 and IPv6: inet_pton, then reverse each 4-byte word,
matching how the kernel prints addresses in /proc/net/tcp and /proc/net/tcp6.

Spec: 2026-08-05-distinct-approver-identity-design.md section 3.3"
```

- [ ] **Step 6: Write the failing test for the inode lookup and the stat parse**

Append to `backend/tests/agent_mail/test_peer_process.py`:

```python
_HEADER = (
    "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when"
    " retrnsmt   uid  timeout inode\n"
)
_TAIL = "00000000:00000000 00:00000000 00000000  1000        0"

# The two mirror-image rows a single loopback connection produces, plus the
# backend's listening socket. 85D9 = 34265 (the caller), 85E8 = 34280 (us).
_TCP_TABLE = (
    _HEADER
    + f"   0: 0100007F:85E8 00000000:0000 0A {_TAIL} 39993299 1 0 20 0 0 10 0\n"
    + f"   1: 0100007F:85D9 0100007F:85E8 01 {_TAIL} 39993300 1 0 20 0 0 10 -1\n"
    + f"   2: 0100007F:85E8 0100007F:85D9 01 {_TAIL} 39993301 1 0 20 0 0 10 -1\n"
)

_STAT = (
    "1234 (claude with spaces) S 1200 1234 1234 0 -1 4194304 900 0 0 0 5 2 0 0"
    " 20 0 12 0 120913170 " + " ".join(["0"] * 30) + "\n"
)


@pytest.fixture
def tcp_table(tmp_path, monkeypatch):
    table = tmp_path / "tcp"
    table.write_text(_TCP_TABLE)
    monkeypatch.setattr(peer_process, "_PROC_NET_TABLES", ((str(table), None),))
    return table


def test_find_socket_inode_matches_the_local_address_column(tcp_table):
    """The caller's own socket has the caller's address in local_address.

    Matching rem_address instead would return 39993301 -- the backend's own
    accepted socket -- and resolve every caller to the backend's pid, binding
    every session to whatever pane the backend happens to run in.
    """
    assert peer_process.find_socket_inode("127.0.0.1", 34265) == 39993300


def test_find_socket_inode_ignores_a_listening_socket(tcp_table):
    """Row 0 has our port in local_address but is state 0A (LISTEN)."""
    assert peer_process.find_socket_inode("127.0.0.1", 34280, local_port=34265) == 39993301
    assert peer_process.find_socket_inode("127.0.0.1", 9999) is None


def test_find_socket_inode_disambiguates_on_the_local_port(tcp_table):
    """A wrong backend port must not match, even with the right caller port."""
    assert peer_process.find_socket_inode("127.0.0.1", 34265, local_port=34280) == 39993300
    assert peer_process.find_socket_inode("127.0.0.1", 34265, local_port=9999) is None


def test_read_proc_stat_survives_a_command_name_containing_spaces(tmp_path, monkeypatch):
    """The comm field is parenthesised and may contain spaces and parens.

    Splitting the whole line would misalign every field after it, so the parse
    starts after the LAST close-paren. One parse yields both fields we need.
    """
    proc = tmp_path / "1234"
    proc.mkdir()
    (proc / "stat").write_text(_STAT)
    monkeypatch.setattr(peer_process, "_PROC_ROOT", str(tmp_path))
    assert peer_process.read_proc_stat(1234) == (1200, "120913170")


def test_read_proc_stat_returns_none_for_a_dead_pid(tmp_path, monkeypatch):
    monkeypatch.setattr(peer_process, "_PROC_ROOT", str(tmp_path))
    assert peer_process.read_proc_stat(999999) is None
```

The space-and-paren command name is the case that matters. `raw.split()[3]` would be `"spaces)"` for this input; `raw[raw.rindex(")") + 2:].split()[1]` is `"1200"`. Assert the ppid so a regression to naive splitting fails loudly.

- [ ] **Step 7: Run it to verify it fails**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_mail/test_peer_process.py -q -p no:warnings
```

Expected: `AttributeError: module 'app.utils.peer_process' has no attribute 'find_socket_inode'`.

- [ ] **Step 8: Implement the inode lookup, the pid scan, and the stat parse**

Append to `backend/app/utils/peer_process.py`:

```python
_PROC_ROOT = "/proc"


def find_socket_inode(
    host: str, port: int, local_port: Optional[int] = None
) -> Optional[int]:
    """Find the inode of the CALLER's socket, whose local end is host:port.

    A loopback connection appears twice in /proc/net/tcp, as mirror-image rows:
    one owned by the caller and one owned by this backend. We want the caller's,
    so we match host:port against LOCAL_address -- matching rem_address would
    find our own accepted socket and resolve every caller to the backend's pid.

    Pass local_port (this backend's port for the connection) to disambiguate
    when the caller reuses a source port across restarts; the pair is unique.
    Both address families are searched: a connection to ::1 lands in
    /proc/net/tcp6 while 127.0.0.1 lands in /proc/net/tcp.
    """
    wanted = format_endpoint(host, port)
    if wanted is None:
        return None
    for path, _family in _PROC_NET_TABLES:
        try:
            with open(path) as handle:
                next(handle, None)  # header
                for line in handle:
                    parts = line.split()
                    if len(parts) <= _INODE_COLUMN:
                        continue
                    if parts[_LOCAL_ADDRESS_COLUMN].upper() != wanted:
                        continue
                    if parts[_STATE_COLUMN] != _TCP_ESTABLISHED:
                        continue
                    if local_port is not None:
                        remote = parts[_REMOTE_ADDRESS_COLUMN].upper()
                        if not remote.endswith(f":{local_port:04X}"):
                            continue
                    try:
                        inode = int(parts[_INODE_COLUMN])
                    except ValueError:
                        continue
                    if inode:
                        return inode
        except OSError:
            continue
    return None


def find_pid_for_inode(inode: int) -> Optional[int]:
    """Find the process holding the socket with this inode.

    A full scan of every /proc/<pid>/fd measured 2.0-6.3 ms across 140 pids on
    the deployment host, which is why this is safe to call inline in a request.
    """
    target = f"socket:[{inode}]"
    try:
        entries = os.listdir(_PROC_ROOT)
    except OSError:
        return None
    for entry in entries:
        if not entry.isdigit():
            continue
        fd_dir = f"{_PROC_ROOT}/{entry}/fd"
        try:
            descriptors = os.listdir(fd_dir)
        except OSError:
            continue  # the process exited, or is not ours to read
        for descriptor in descriptors:
            try:
                if os.readlink(f"{fd_dir}/{descriptor}") == target:
                    return int(entry)
            except OSError:
                continue
    return None


def read_proc_stat(pid: int) -> Optional[tuple[int, str]]:
    """Return (ppid, starttime) for pid, or None if it is gone.

    Field 2 (comm) is parenthesised and may itself contain spaces and
    parentheses, so the parse begins after the last close-paren. From there
    fields[1] is ppid and fields[19] is starttime -- one read, both values.
    """
    try:
        with open(f"{_PROC_ROOT}/{pid}/stat") as handle:
            raw = handle.read()
    except OSError:
        return None
    try:
        fields = raw[raw.rindex(")") + 2 :].split()
        return int(fields[1]), fields[19]
    except (ValueError, IndexError):
        return None
```

- [ ] **Step 9: Run the tests to verify they pass**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_mail/test_peer_process.py -q -p no:warnings
```

Expected: `8 passed`.

Then **mutate to prove the local-address test has teeth**: temporarily change `_LOCAL_ADDRESS_COLUMN = 1` to `= 2` and re-run. `test_find_socket_inode_matches_the_local_address_column` must fail. Restore the `1` by replacing the exact string — do not `git checkout`. If the test still passes with the mutant, the fixture is wrong and the whole binding design rests on nothing; stop and report.

- [ ] **Step 10: Commit**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1 && git add backend/app/utils/peer_process.py backend/tests/agent_mail/test_peer_process.py && git commit -m "feat(mail): resolve a TCP peer to its pid and read its proc stat

find_socket_inode matches the caller's own row on local_address -- a loopback
connection appears twice, and the rem_address row is the backend's own accepted
socket, which would bind every session to the backend's pane;
find_pid_for_inode scans /proc/<pid>/fd (measured 2-6ms for a full scan);
read_proc_stat parses after the last close-paren so a command name containing
spaces cannot misalign ppid and starttime.

Spec: 2026-08-05-distinct-approver-identity-design.md section 3.3"
```

- [ ] **Step 11: Write the failing test for the pane walk**

Append to `backend/tests/agent_mail/test_peer_process.py`:

```python
def test_list_tmux_pane_pids_parses_the_format_string(monkeypatch):
    output = "%3 159009 team:0.0\n%0 149168 team:0.1\n\n"
    monkeypatch.setattr(
        peer_process, "_run_tmux", lambda *args, **kwargs: output
    )
    assert peer_process.list_tmux_pane_pids() == {159009: "team:0.0", 149168: "team:0.1"}


def test_list_tmux_pane_pids_is_empty_when_tmux_is_absent(monkeypatch):
    monkeypatch.setattr(peer_process, "_run_tmux", lambda *args, **kwargs: None)
    assert peer_process.list_tmux_pane_pids() == {}


def test_resolve_peer_pane_walks_ppids_up_to_a_pane(monkeypatch):
    """The MCP shim is a grandchild of the pane, not the pane itself."""
    tree = {5000: (4000, "aaa"), 4000: (3000, "bbb"), 3000: (1, "ccc")}
    monkeypatch.setattr(peer_process, "find_socket_inode", lambda h, p, local_port=None: 77)
    monkeypatch.setattr(peer_process, "find_pid_for_inode", lambda inode: 5000)
    monkeypatch.setattr(peer_process, "read_proc_stat", lambda pid: tree.get(pid))
    monkeypatch.setattr(peer_process, "list_tmux_pane_pids", lambda: {3000: "team:0.2"})

    pane = peer_process.resolve_peer_pane("127.0.0.1", 36253)
    assert pane is not None
    assert (pane.pane_pid, pane.pane_proc_start, pane.tmux_target, pane.peer_pid) == (
        3000,
        "ccc",
        "team:0.2",
        5000,
    )


def test_resolve_peer_pane_is_none_when_no_ancestor_is_a_pane(monkeypatch):
    tree = {5000: (1, "aaa")}
    monkeypatch.setattr(peer_process, "find_socket_inode", lambda h, p, local_port=None: 77)
    monkeypatch.setattr(peer_process, "find_pid_for_inode", lambda inode: 5000)
    monkeypatch.setattr(peer_process, "read_proc_stat", lambda pid: tree.get(pid))
    monkeypatch.setattr(peer_process, "list_tmux_pane_pids", lambda: {3000: "team:0.2"})
    assert peer_process.resolve_peer_pane("127.0.0.1", 36253) is None


def test_resolve_peer_pane_is_none_when_the_socket_is_gone(monkeypatch):
    """The TIME_WAIT case: no inode, therefore no pane. Never guess."""
    monkeypatch.setattr(peer_process, "find_socket_inode", lambda h, p, local_port=None: None)
    assert peer_process.resolve_peer_pane("127.0.0.1", 36253) is None
```

The three stubs take `local_port=None` because `resolve_peer_pane` forwards it as a keyword. A stub with the wrong signature fails with `TypeError`, not a wrong answer — but fix the stub, never the call.

Note the third test's shape: the pane pid is the caller's **grandparent**, and `pane_proc_start` comes from the pane's own stat line (`"ccc"`), not the caller's. Getting that backwards is the defect this test exists to catch — a rebind check comparing the wrong process's start time would accept any restarted shim.

- [ ] **Step 12: Run it to verify it fails**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_mail/test_peer_process.py -q -p no:warnings
```

Expected: `AttributeError: ... has no attribute '_run_tmux'`.

- [ ] **Step 13: Implement the pane walk**

Append to `backend/app/utils/peer_process.py`:

```python
@dataclass(frozen=True)
class PeerPane:
    """The tmux pane a caller's process tree belongs to."""

    pane_pid: int
    pane_proc_start: str
    tmux_target: Optional[str]
    peer_pid: int


def _run_tmux(*args: str) -> Optional[str]:
    """Run a read-only tmux command, or return None if tmux is unavailable."""
    try:
        completed = subprocess.run(
            ["tmux", *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def list_tmux_pane_pids() -> dict[int, str]:
    """Map every live pane's pid to its tmux target."""
    output = _run_tmux(
        "list-panes",
        "-a",
        "-F",
        "#{pane_id} #{pane_pid} #{session_name}:#{window_index}.#{pane_index}",
    )
    if not output:
        return {}
    panes: dict[int, str] = {}
    for line in output.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        try:
            panes[int(parts[1])] = parts[2]
        except ValueError:
            continue
    return panes


def resolve_peer_pane(
    host: str, port: int, local_port: Optional[int] = None
) -> Optional[PeerPane]:
    """Resolve a TCP peer to the tmux pane it runs under, or None.

    MUST be called synchronously inside the request handler -- see the module
    docstring. Returns None rather than guessing whenever any link in the chain
    is missing: an unresolvable caller is not a caller in some other pane.
    """
    inode = find_socket_inode(host, port, local_port=local_port)
    if inode is None:
        return None
    peer_pid = find_pid_for_inode(inode)
    if peer_pid is None:
        return None

    panes = list_tmux_pane_pids()
    if not panes:
        return None

    pid = peer_pid
    for _ in range(_MAX_PARENT_WALK):
        stat = read_proc_stat(pid)
        if stat is None:
            return None
        ppid, proc_start = stat
        if pid in panes:
            return PeerPane(
                pane_pid=pid,
                pane_proc_start=proc_start,
                tmux_target=panes[pid],
                peer_pid=peer_pid,
            )
        if ppid <= 1:
            return None
        pid = ppid
    return None
```

The walk checks `pid in panes` **after** reading that pid's own stat, so `pane_proc_start` always describes the pane process. The `_MAX_PARENT_WALK` bound is a guard against a pid cycle, which should be impossible but costs nothing to rule out.

- [ ] **Step 14: Run the tests to verify they pass**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_mail/test_peer_process.py -q -p no:warnings
```

Expected: `13 passed`.

- [ ] **Step 15: Verify the resolver against a real socket, end to end**

The unit tests all stub `/proc`. Prove the real chain works once, by hand, against a live loopback connection:

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && python3 - <<'PY'
import socket
from app.utils import peer_process

srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
cli = socket.socket(); cli.connect(srv.getsockname())
conn, peer = srv.accept()
local_port = conn.getsockname()[1]
inode = peer_process.find_socket_inode(*peer, local_port=local_port)
pid = peer_process.find_pid_for_inode(inode) if inode else None
print("peer:", peer, "| our port:", local_port, "| inode:", inode, "| pid:", pid)
print("this process:", __import__("os").getpid())
print("pane:", peer_process.resolve_peer_pane(*peer, local_port=local_port))
cli.close(); conn.close(); srv.close()
PY
```

Expected: a non-zero `inode`, a `pid` **equal to `this process`** (client and server are the same process here, so that is the correct answer), and a `PeerPane` **if and only if** you run this inside tmux. Outside tmux, `pane: None` is correct, not a failure. Record which you saw.

- [ ] **Step 16: Run the full baseline suite**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_teams/ tests/agent_mail/ -q -p no:warnings
```

Expected: `471 passed` (454 baseline + 4 from Task 1 + 13 here). Nothing outside these two new files has changed, so any other failure is a regression — stop and report.

- [ ] **Step 17: Commit**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1 && git add backend/app/utils/peer_process.py backend/tests/agent_mail/test_peer_process.py && git commit -m "feat(mail): walk a peer pid up to its tmux pane

resolve_peer_pane chains inode -> pid -> ppid walk -> pane, and returns the
PANE's proc start rather than the caller's, so a restarted shim under the same
pane is still recognised as that pane. Returns None at every missing link:
an unresolvable caller is never treated as a caller somewhere else.

Spec: 2026-08-05-distinct-approver-identity-design.md section 3.3"
```

---

### Task 3: Mint the capability token — once per session, never rotated

**Files:**
- Modify: `backend/app/services/agent_mail_service.py:155-218` (add a method; **do not** change `register_session`'s signature)
- Modify: `backend/app/models/schemas.py:1994-1996` (`MailAgentRegisterResponse`)
- Modify: `backend/app/api/v1/agent_mail.py:119-130` (the `register_agent` route)
- Test: `backend/tests/agent_mail/test_capability_tokens.py`

**Interfaces:**
- Consumes: `MailAgentSession.capability_token_hash` (Task 1).
- Produces:
  - `agent_mail_service.hash_capability_token(token: str) -> str` — SHA-256 hex.
  - `agent_mail_service.ensure_capability_token(db, session) -> str | None` — returns the plaintext **only** on the call that mints it; `None` on every later call for the same session. **Mints only when `capability_token_hash` is NULL *and* the row was just created** — the caller decides that; see `peek_session_by_key`.
  - `agent_mail_service.peek_session_by_key(db, session_key: str) -> MailAgentSession | None` — a read-only lookup by key, **no writes**. Exists because the rebind check must run *before* `register_session`, which rewrites the row in place.
  - `MailAgentRegisterResponse.capability_token: Optional[str] = None`.

**Correction (2026-08-09, source verification) — the spec says mint inside `register_session` before its `await db.commit()` at `:215`. The plan mints in a separate method that the route calls afterwards.** Two measured reasons:

1. **`register_session` returns a 2-tuple and 42 call sites unpack it** — 28 in `tests/agent_mail/test_registry.py`, 14 in `tests/agent_teams/test_agent_team_service.py`. Threading a third value out of it means editing all 42 for no behavioural gain. The plaintext has to reach the route by another channel regardless; a separate method *is* that channel.
2. **`register_session` has two callers, and the second must not mint.** `_register_from_hook` (`agent_mail.py:184-200`) is called from `hook_session_start` and `hook_user_prompt_submit`, both of which end `except Exception as exc: logger.warning(...); return {}`. A hook has nowhere to put a token — it returns `{}` — so minting there would burn the one-time plaintext into a swallowed exception path and leave a row whose hash nobody holds.

**The token is minted once and never rotated.** This is the decisive constraint and it is not optional: the MCP shim's `_guard` re-registers before **every** tool call, so `register_agent` is hit continuously for the same `session_key`. Rotating on each registration would invalidate the token the shim is holding, on every call. So:

| Registration | `capability_token_hash` | Response `capability_token` |
| --- | --- | --- |
| New `session_key`, row created | minted | the plaintext, once |
| Same `session_key`, hash already set (the `_guard` re-register) | untouched | `None` |
| Same `session_key`, hash is `NULL`, **enforcement on** | untouched (still `NULL`) | `409 token_required_for_rebind` — see below |
| Same `session_key`, hash is `NULL`, **grace mode** | untouched (still `NULL`) | `200`, `capability_token: None` — mint nothing, refuse nothing |
| Via `_register_from_hook` | untouched | n/a — hooks return `{}` |

The two hashless rows are the same row shape with two answers, and the flag is the only thing that separates them. Both **decline to mint**; only the enforced one refuses the request. Neither backfills. The section below is why — including why an earlier draft of this task got each of the three possible answers wrong in turn.

A dead shim's row keeps its hash forever. Do not null it on disconnect: a restarted shim gets a **new** `session_key` (`f"mcp:{uuid.uuid4().hex[:12]}"`, evaluated once at module import, `mcp_shim/agent_mail_server.py:26`) and therefore a new row and a new token, so no shim can ever be locked out by a hash it no longer holds.

#### The row that must refuse, and why an earlier draft of this task got it wrong

**Revision note (2026-08-10, self-review — two passes, and the first fix was also wrong).** This table's hashless row went through three versions. Version 1 said *"hash is `NULL` (a row from before PR0) ⇒ minted"* — a leader-impersonation hole, and it silently dropped §3.4's row 4. Version 2 refused it `409 token_required_for_rebind` **unconditionally** — which fixes the hole and creates a deploy-day outage. Version 3, above, is the one to implement: **mint nothing in either mode; refuse only under enforcement.**

Both wrong versions are recorded because each is the one that looks obviously right from where it was written. Backfilling reads as a courtesy to existing sessions. An unconditional refusal reads as the properly paranoid correction to it. The measurements below say the courtesy is a hole and the paranoia is an outage, and that the third answer — decline to mint, decline to refuse — is neither.

`register_session` does **not** create a new row for a known `session_key`. It looks the row up by key (`agent_mail_service.py:175-178`) and then *rewrites it in place* — `member_id`, `provider`, `cwd`, `pid`, `team_preset_id`, `team_slot_id` (`:206-213`). So "same `session_key`" is not a new session presenting a familiar name; it is **the same row, repointed**.

Measured, with `register_session` called twice for one key from two different cwds:

```
victim   member_id=1 name='alpha'    session_id=1 pid=1111 cwd='/repo/alpha'
attacker member_id=2 name='attacker' session_id=1 pid=2222 cwd='/repo/attacker'
same session row? True
session rows total: 1
  row id=1 key='mcp:victimkey01' member=2 pid=2222 cwd='/repo/attacker'
```

That alone is only a nuisance — the replaying caller lands on its own member. The escalation is the branch at `:179-189`, which **keeps the existing member** when the request claims no team context, the stored row is slot-bound, and `_session_team_context_matches_registration` passes. That predicate compares `provider` and `derive_repo_identity(cwd)["repo_id"]` (`:264-274`) — both attacker-supplied, and both readable from the **unauthenticated** `GET /agent-mail/team`, which projects `session_key` on every session (`MailSessionResponse.session_key`, `schemas.py:1817`, reached via `MailMemberResponse.sessions` at `:1854`). Measured end to end:

```
LEADER   session=1 key='mcp:leaderkey99' member=1 name='Leader' kind=team_slot slot=1

readable from GET /agent-mail/team (no credential):
  member='Leader' repo_path='/repo/tizonia' session_key='mcp:leaderkey99' cwd='/repo/tizonia'

ATTACKER session=1 member=1 name='Leader' kind=team_slot slot=1 pid=2222
  same session row as leader? True
  resolved member IS the leader's? True
  slot still the leader's?        True
```

So the replaying caller's registration resolves to the **leader's** member on the **leader's** slot. Under the deleted row, that registration *mints* — and Task 5's `derive_member_id` reads `session.member_id` at write time, so the minted token writes mail as the leader. PR1 §4.3 rule 4 accepts an approval from an `answer` whose `sender_member_id == leader_member.id`. That is the whole gate, handed over by a backfill.

**And it is permanent, not a race.** The tempting dismissal is that the leader's next `_guard` re-register (before every tool call) re-mints and closes the window. It does not, because **no path deletes an `mcp` session row** — `_remove_stale_observed_sessions` selects `source == "observed"` (`:565-568`), which is why the live DB holds 150 `mcp` rows with 7 connected. Every one of the other 143 has a NULL hash, keeps its `session_key` in the unauthenticated roster, and never re-registers because its shim is gone. Measured with the leader's row aged 30 days past `MCP_HEARTBEAT_TTL_SECONDS` (`3600`, `agent_mail_service.py:39`):

```
dead leader session: id=1 key='mcp:deadleader01' member=1 slot=1 last_seen=2026-07-11
GET /agent-mail/team projects:
  member='Leader' status='offline' session_key='mcp:deadleader01' mailbox_status='offline'
dead leader session_key readable with no credential? True
replay -> session=1 member=1 name='Leader' kind=team_slot slot=1
resolved to the leader's member? True
```

143 permanently-open doors, each one addressed by a string the roster hands out for free. **This is why the no-mint half of the rule below is unconditional: "backfill a pre-PR0 row" is a mutation that stays exploitable for the life of the row, so no flag may switch it back on.** Note that this case is *not* §3.4's row 4 — that row is "no token presented but a hash exists," a row that HAS a hash. The hashless row is a shape §3.4 does not tabulate, which is exactly why this task has to reason it out rather than copy an answer. What §3.4 does supply is the retention rule the argument rests on, and the withdrawn rescue rule at the end of this section. The dead-row population makes the hashless case worse than §3.4's live-key reasoning argues, not better.

**What replaces the backfill.** Nothing is minted. A pre-PR0 row is never rescued — but under grace mode it is not refused either, and that asymmetry is the whole correction.

- **Never mint for a hashless existing row, in either mode.** This is the non-negotiable half. A token minted in grace mode does not expire when the operator flips the flag: it is a row in `mail_agent_sessions` whose hash outlives the window, and Task 5's `derive_member_id` will resolve it to `session.member_id` — the leader's — for as long as the row exists, which by the retention rule above is forever. Backfilling "just during grace" therefore manufactures exactly the durable credential enforcement exists to prevent, and hands it out during the window nobody is watching.
- **Under enforcement, refuse `409 token_required_for_rebind`.** Not `403`: the honest remedy is available to the legitimate caller and the code should say so. The remedy is a **shim restart**, which yields a new `session_key` (per-process UUID) and therefore row 1 — a fresh row, a fresh mint, no rebind. That is exactly the "restart the agent panes" step §3.8's rollout already requires and Task 11 documents, and it is a step the operator performs *before* flipping the flag. So by the time the refusal is live, no legitimate caller can reach it.
- **Under grace mode, return `200` with `capability_token: None`.** The registration otherwise proceeds exactly as it does today. This is the row an earlier draft got wrong in the paranoid direction, and it is wrong for two measured reasons.

**Measurement 1 — an unconditional refusal is a deploy-day outage, in the mode that exists to prevent one.** A live pre-upgrade shim's process survives the deploy. Its `session_key` was fixed at module import (`mcp_shim/agent_mail_server.py:23-28`) and its row's hash is `NULL`, because nothing ever minted one. So its very next `_guard` — which re-registers before **every** tool call (`:201-203`) — presents a known `session_key` against a hashless row: precisely the shape being refused. And a failed registration is not a warning the agent can work around, because `_guard` returns the error instead of `None`:

```
session_key is fixed at import: mcp:aaf3e35bca3a
_ensure_registered ok?  False
_guard returns:         an ERROR (tool blocked)
error surfaced:         {'code': 'deck_http_error', 'status_code': 409, 'message': 'token_required_for_rebind'}
```

Every mail tool, on every live session, fails from the moment PR0 deploys until the operator restarts that pane. The rollout does restart the panes — but grace mode's contract is that *nothing breaks on deploy* and the restart happens at the operator's convenience (§3.4, "Deployment"). An unconditional refusal converts that into a hard ordering requirement with a live outage in between, for the 7 connected sessions.

**Measurement 2 — in grace mode the refusal defends nothing, because the attack needs no token.** Task 5's grace-mode fallback returns the *claimed* `sender_member_id` unverified (`derive_member_id`, `session is None` branch). So the impersonation the mint would enable is already available to any caller, with no credential at all:

```
leader member_id=1 attacker member_id=2
   (1, 2, 'context_request', 'approve?')
   (2, 1, 'answer',          'approved')

attacker's 'answer' sender_member_id = 1 | is the leader's? True
```

The attacker wrote an `answer` as the leader without registering, without a `session_key`, and without a token. Refusing their *registration* leaves that path untouched. Grace mode is a knowingly-unauthenticated window — that is its cost, stated in §3.4 — and adding a refusal inside it buys no security while costing the outage in measurement 1.

**So the flag does gate the refusal, and does not gate the mint.** Put the other way: the thing that must never happen (a minted token for a row the caller cannot prove it owns) is unconditional; the thing that would break running agents (refusing them) waits until the operator has restarted the panes and flipped the flag. The 143 dead rows stay unmintable throughout, which is what closes the hole — the refusal was never what closed it.

**Do not "fix" this by comparing the pane binding instead.** Task 4's binding is derived from the caller's own connection, so a co-resident pane in the same repo satisfies `_session_team_context_matches_registration` and, on this host, can be a genuine sibling pane of the same repo — §3.3's residual-risk note says pane binding defeats *claiming* another slot, not co-residency. §3.4 already withdrew precisely this rescue rule for the same reason. Refuse on the hash's absence, which is a fact about the row, not about the caller.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/agent_mail/test_capability_tokens.py`:

```python
import hashlib

from app.models.schemas import MailAgentRegisterRequest
from app.services.agent_mail_service import agent_mail_service


def _register(cwd: str, session_key: str = "mcp:abc123") -> MailAgentRegisterRequest:
    return MailAgentRegisterRequest(
        source="mcp",
        provider="claude",
        cwd=cwd,
        session_key=session_key,
    )


@pytest.mark.asyncio
async def test_ensure_capability_token_mints_once(db, tmp_path):
    _member, session = await agent_mail_service.register_session(db, _register(str(tmp_path)))
    assert session.capability_token_hash is None

    token = await agent_mail_service.ensure_capability_token(db, session)
    assert token is not None
    assert len(token) >= 32

    stored = (
        await db.execute(
            text("SELECT capability_token_hash FROM mail_agent_sessions WHERE id = :i"),
            {"i": session.id},
        )
    ).scalar_one()
    assert stored == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert stored != token, "the plaintext must never be stored"


@pytest.mark.asyncio
async def test_ensure_capability_token_does_not_rotate(db, tmp_path):
    """The shim re-registers before every tool call. Rotating would break it."""
    _member, session = await agent_mail_service.register_session(db, _register(str(tmp_path)))
    first = await agent_mail_service.ensure_capability_token(db, session)

    # Same session_key -> same row, as the shim's _guard does on every tool.
    _member, again = await agent_mail_service.register_session(db, _register(str(tmp_path)))
    assert again.id == session.id
    second = await agent_mail_service.ensure_capability_token(db, again)

    assert second is None, "a re-registration must not hand out a second plaintext"
    stored = (
        await db.execute(
            text("SELECT capability_token_hash FROM mail_agent_sessions WHERE id = :i"),
            {"i": session.id},
        )
    ).scalar_one()
    assert stored == hashlib.sha256(first.encode("utf-8")).hexdigest()


@pytest.mark.asyncio
async def test_peek_session_by_key_reads_without_writing(db, tmp_path):
    """The rebind check runs BEFORE register_session, so its lookup must not write.

    register_session rewrites member_id/cwd/pid on a known key (:206-213). If the
    check reused it, the row would already be repointed by the time we refused.
    """
    _member, session = await agent_mail_service.register_session(
        db, _register(str(tmp_path), session_key="mcp:peek1")
    )
    before = (
        await db.execute(
            text("SELECT member_id, cwd, pid, last_seen_at FROM mail_agent_sessions WHERE id = :i"),
            {"i": session.id},
        )
    ).one()

    found = await agent_mail_service.peek_session_by_key(db, "mcp:peek1")
    assert found is not None and found.id == session.id
    assert await agent_mail_service.peek_session_by_key(db, "mcp:nosuchkey") is None

    after = (
        await db.execute(
            text("SELECT member_id, cwd, pid, last_seen_at FROM mail_agent_sessions WHERE id = :i"),
            {"i": session.id},
        )
    ).one()
    assert tuple(after) == tuple(before), "peek must not touch the row"


@pytest.mark.asyncio
async def test_two_sessions_get_different_tokens(db, tmp_path):
    _m, first = await agent_mail_service.register_session(
        db, _register(str(tmp_path), session_key="mcp:one")
    )
    _m, second = await agent_mail_service.register_session(
        db, _register(str(tmp_path), session_key="mcp:two")
    )
    a = await agent_mail_service.ensure_capability_token(db, first)
    b = await agent_mail_service.ensure_capability_token(db, second)
    assert a != b
```

The singleton is `agent_mail_service = AgentMailService()`, the last line of `app/services/agent_mail_service.py` — verified, import it exactly as written above.

- [ ] **Step 2: Run to verify failure**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_mail/test_capability_tokens.py -q -p no:warnings
```

Expected: `AttributeError: 'AgentMailService' object has no attribute 'ensure_capability_token'`.

- [ ] **Step 3: Add the hashing helper and the mint**

`agent_mail_service.py` imports `logging, os, subprocess, time` at `:2-5`. Add `hashlib` and `secrets` to that block, keeping it alphabetical:

```python
import hashlib
import logging
import os
import secrets
import subprocess
import time
```

Then add both methods to the service class, immediately after `register_session` ends at `:218`:

```python
    @staticmethod
    def hash_capability_token(token: str) -> str:
        """Hash a capability token for storage.

        Same construction as external_agent_mail_service._hash_token, so the
        two credential families are verified identically.
        """
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    async def ensure_capability_token(
        self, db: AsyncSession, session: MailAgentSession
    ) -> Optional[str]:
        """Mint this session's capability token, or None if it already has one.

        Called by the register_agent route, never by the hook registration path
        (a hook returns {} and has nowhere to put the plaintext).

        The token is minted once and NEVER rotated: the MCP shim re-registers
        before every tool call, so rotating here would invalidate the token the
        shim is holding on every single call. A row therefore keeps its hash for
        life -- including after the shim dies -- which locks nobody out, because
        a restarted shim generates a fresh session_key and so gets a fresh row.
        """
        if session.capability_token_hash is not None:
            return None
        token = secrets.token_urlsafe(32)
        session.capability_token_hash = self.hash_capability_token(token)
        await db.commit()
        await db.refresh(session)
        return token

    async def peek_session_by_key(
        self, db: AsyncSession, session_key: str
    ) -> Optional[MailAgentSession]:
        """Look up a session by key WITHOUT writing anything.

        The register route's rebind check needs to know whether a row already
        exists, and with what hash, BEFORE register_session runs -- because
        register_session rewrites member_id, cwd and pid in place on a known key
        (:206-213). Refusing after that call would refuse a row already
        repointed at the caller.
        """
        result = await db.execute(
            select(MailAgentSession).where(MailAgentSession.session_key == session_key)
        )
        return result.scalar_one_or_none()
```

`Optional` is already imported (`:7`), as are `MailAgentSession` (`:16`), `AsyncSession` (`:11`) and `select` (`:9` — confirm the exact line; `register_session` already uses it at `:175`).

- [ ] **Step 4: Run to verify the tests pass**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_mail/test_capability_tokens.py -q -p no:warnings
```

Expected: `8 passed` (4 from Task 1 + 4 here).

- [ ] **Step 5: Mutation-check the no-rotate guarantee**

The rotate test is the one that matters most, so prove it has teeth. Temporarily delete the two guard lines:

```python
        if session.capability_token_hash is not None:
            return None
```

Re-run. `test_ensure_capability_token_does_not_rotate` **must** fail. `test_peek_session_by_key_reads_without_writing` must still pass — it does not touch the guard, and that is expected rather than a gap. Restore the two lines by retyping them exactly. If the rotate test passes without the guard, it is not testing what it claims; stop and report.

- [ ] **Step 6: Add `capability_token` to the response schema**

In `backend/app/models/schemas.py`, replace `MailAgentRegisterResponse` (`:1994-1996`):

```python
class MailAgentRegisterResponse(BaseModel):
    member: MailMemberResponse
    session: MailSessionResponse
    capability_token: Optional[str] = None
```

`Optional` is already imported at the top of the file. The field defaults to `None` so that every existing construction of this model — and the hook path, which does not build one at all — stays valid.

- [ ] **Step 7: Write the failing route test**

Append to `backend/tests/agent_mail/test_capability_tokens.py`. The `client` fixture is **not** in `conftest.py` — it is defined locally in `tests/agent_mail/test_api.py:13-22`, so copy it verbatim into the new file:

```python
import httpx
import pytest_asyncio

from app.database import get_db
from app.main import app


@pytest_asyncio.fixture
async def client(db):
    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
```

Note `base_url="http://test"` — that hostname is why `_is_loopback_request` (`external_agent_mail.py:39-41`) accepts these requests, which Task 10's test 20 depends on. Do not change it.

```python
@pytest.mark.asyncio
async def test_register_route_returns_the_token_once(client, tmp_path):
    body = {
        "source": "mcp",
        "provider": "claude",
        "cwd": str(tmp_path),
        "session_key": "mcp:route1",
    }
    first = await client.post("/api/v1/agent-mail/agent/register", json=body)
    assert first.status_code == 200
    token = first.json()["capability_token"]
    assert token

    second = await client.post("/api/v1/agent-mail/agent/register", json=body)
    assert second.status_code == 200
    assert second.json()["capability_token"] is None


@pytest.mark.asyncio
async def test_a_hashless_existing_row_refuses_rather_than_minting(
    client, db, tmp_path, monkeypatch
):
    """Under enforcement: refuse, and mint nothing.

    The mutation this kills is 'backfill a pre-PR0 row'. Measured:
    register_session rewrites a known key's row in place, and the branch at
    agent_mail_service.py:179-189 can KEEP the stored member when the request
    claims no team context and provider+repo_id match -- both of which the
    unauthenticated GET /agent-mail/team hands out. So minting here issues a
    token that writes mail as the row's existing member.
    """
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    body = {
        "source": "mcp",
        "provider": "claude",
        "cwd": str(tmp_path),
        "session_key": "mcp:pre-pr0",
    }
    first = await client.post("/api/v1/agent-mail/agent/register", json=body)
    assert first.status_code == 200
    assert first.json()["capability_token"]

    # Age the row into the pre-PR0 shape: a live session_key, no hash. This is
    # the shape all 150 live mcp rows have on the morning of the deploy.
    await db.execute(
        text("UPDATE mail_agent_sessions SET capability_token_hash = NULL WHERE session_key = :k"),
        {"k": "mcp:pre-pr0"},
    )
    await db.commit()

    replay = await client.post("/api/v1/agent-mail/agent/register", json=body)
    assert replay.status_code == 409
    assert replay.json()["detail"] == "token_required_for_rebind"
    assert "capability_token" not in replay.text

    still_null = (
        await db.execute(
            text("SELECT capability_token_hash FROM mail_agent_sessions WHERE session_key = :k"),
            {"k": "mcp:pre-pr0"},
        )
    ).scalar_one()
    assert still_null is None, "the refusal must not mint as a side effect"


@pytest.mark.asyncio
async def test_the_refusal_does_not_repoint_the_row(client, db, tmp_path, monkeypatch):
    """The refusal must precede register_session, not follow it.

    A check placed after register_session returns 409 on a row whose member_id,
    cwd and pid have ALREADY been rewritten to the replaying caller's -- the
    request is refused and the takeover still happened. Assert the row is
    untouched, not merely that the status is 409.
    """
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    body = {
        "source": "mcp",
        "provider": "claude",
        "cwd": str(tmp_path),
        "session_key": "mcp:norepoint",
        "pid": 1111,
    }
    assert (await client.post("/api/v1/agent-mail/agent/register", json=body)).status_code == 200
    await db.execute(
        text("UPDATE mail_agent_sessions SET capability_token_hash = NULL WHERE session_key = :k"),
        {"k": "mcp:norepoint"},
    )
    await db.commit()
    before = (
        await db.execute(
            text("SELECT member_id, cwd, pid FROM mail_agent_sessions WHERE session_key = :k"),
            {"k": "mcp:norepoint"},
        )
    ).one()

    other = dict(body, cwd=str(tmp_path / "elsewhere"), pid=2222)
    (tmp_path / "elsewhere").mkdir()
    replay = await client.post("/api/v1/agent-mail/agent/register", json=other)
    assert replay.status_code == 409

    after = (
        await db.execute(
            text("SELECT member_id, cwd, pid FROM mail_agent_sessions WHERE session_key = :k"),
            {"k": "mcp:norepoint"},
        )
    ).one()
    assert tuple(after) == tuple(before), "a refused registration must change nothing"


@pytest.mark.asyncio
async def test_a_hashless_row_in_grace_mode_neither_mints_nor_refuses(client, db, tmp_path):
    """The same row shape, enforcement off: 200 with no token, hash still NULL.

    Two mutants die here. (a) 'refuse unconditionally' -> 409, which is the
    deploy-day outage: a live pre-upgrade shim's _guard re-registers before every
    tool call and returns the error instead of None, so every mail tool fails.
    (b) 'mint during grace, enforce later' -> a non-null hash, which is a durable
    credential resolving to this row's member for as long as the row exists --
    and no path deletes an mcp session row.
    """
    assert settings.mail_capability_tokens_required is False
    body = {
        "source": "mcp",
        "provider": "claude",
        "cwd": str(tmp_path),
        "session_key": "mcp:grace1",
    }
    assert (await client.post("/api/v1/agent-mail/agent/register", json=body)).status_code == 200
    await db.execute(
        text("UPDATE mail_agent_sessions SET capability_token_hash = NULL WHERE session_key = :k"),
        {"k": "mcp:grace1"},
    )
    await db.commit()

    replay = await client.post("/api/v1/agent-mail/agent/register", json=body)
    assert replay.status_code == 200, "grace mode must not break a running shim"
    payload = replay.json()
    assert payload["capability_token"] is None
    # A normal, complete response -- not a stripped-down or warning-shaped one.
    assert payload["member"]["id"] and payload["session"]["session_key"] == "mcp:grace1"

    still_null = (
        await db.execute(
            text("SELECT capability_token_hash FROM mail_agent_sessions WHERE session_key = :k"),
            {"k": "mcp:grace1"},
        )
    ).scalar_one()
    assert still_null is None, "grace mode must not backfill a hash either"


@pytest.mark.asyncio
async def test_a_fresh_session_key_from_the_same_pane_still_mints(client, tmp_path):
    """§3.7 test 14c, and the reason the refusal costs the rollout nothing.

    A restarted shim generates a new per-process session_key
    (agent_mail_server.py:26), so it is a FIRST registration -- row 1, which
    mints. Restarting the panes is already §3.8's rollout step.
    """
    base = {"source": "mcp", "provider": "claude", "cwd": str(tmp_path)}
    first = await client.post(
        "/api/v1/agent-mail/agent/register", json=dict(base, session_key="mcp:aaa")
    )
    assert first.status_code == 200 and first.json()["capability_token"]

    restarted = await client.post(
        "/api/v1/agent-mail/agent/register", json=dict(base, session_key="mcp:bbb")
    )
    assert restarted.status_code == 200
    assert restarted.json()["capability_token"], "a restarted shim must not be locked out"
    assert restarted.json()["capability_token"] != first.json()["capability_token"]
```

The route is `@router.post("/agent/register", response_model=MailAgentRegisterResponse)` at `agent_mail.py:119`; confirm the `/api/v1/agent-mail` prefix in `app/api/v1/router.py` — `tests/agent_mail/test_api.py` already posts to paths under it, so copy the prefix from a working call there.

**These five tests need both `client` and `db`**, and the `client` fixture already depends on `db`, so they share one session — that is why the raw-SQL `UPDATE` is visible to the route.

**The three hashless tests are one experiment run twice, plus its escape hatch.** `test_a_hashless_existing_row_refuses_rather_than_minting` and `test_a_hashless_row_in_grace_mode_neither_mints_nor_refuses` build the *identical* row shape and differ only in `mail_capability_tokens_required`, which is exactly the discrimination the route makes; both assert the hash is still `NULL`, because the no-mint half is what the flag must **not** change. `test_a_fresh_session_key_from_the_same_pane_still_mints` is the remedy, and it needs no flag setting — a first registration mints in either mode.

Do not collapse the pair into one parametrized test with a status list. `assert replay.status_code in (200, 409)` passes against every mutant here, including the two the pair exists to kill.

- [ ] **Step 8: Run to verify it fails**

Expected: `assert token` fails in the first test, because the route still returns `capability_token: None` on the first call. The three new tests fail too — the first two because the route returns `200`, the third because no token is minted at all yet.

- [ ] **Step 9: Wire the route**

In `backend/app/api/v1/agent_mail.py`, replace the body of `register_agent` (`:119-130`). Note the mint goes **after** `register_session` but **before** `list_team`, because `ensure_capability_token` commits and `list_team` reads:

```python
@router.post("/agent/register", response_model=MailAgentRegisterResponse)
async def register_agent(
    request: MailAgentRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    # The rebind check runs FIRST, before register_session, because
    # register_session rewrites a known key's row in place (member_id, cwd, pid
    # at agent_mail_service.py:206-213). Checking afterwards would refuse a
    # request whose takeover had already been committed.
    #
    # A row exists for this key but holds no hash. Either it pre-dates PR0 or
    # some caller is replaying a session_key read from the unauthenticated
    # GET /agent-mail/team. We cannot tell the two apart, and minting for the
    # second hands out a token that writes mail as the row's stored member --
    # the leader's, when the row is slot-bound. So never mint here, in either
    # mode: a token minted "just during grace" outlives the grace window.
    #
    # Refusing, though, IS flag-gated. A live pre-upgrade shim re-registers on
    # this exact shape before every tool call, and _guard turns a 409 into a
    # tool failure -- so refusing in grace mode is an outage in the mode that
    # exists to prevent one. It also buys nothing: grace mode already accepts an
    # unverified sender_member_id, so the impersonation needs no token at all.
    existing = await agent_mail_service.peek_session_by_key(db, request.session_key)
    hashless_rebind = existing is not None and existing.capability_token_hash is None
    if hashless_rebind and settings.mail_capability_tokens_required:
        # The remedy is a shim restart: a new per-process session_key, hence a
        # fresh row that mints cleanly. That restart is already the rollout step
        # the operator performs BEFORE flipping this flag, so no legitimate
        # caller can reach this refusal once it is live.
        raise HTTPException(status_code=409, detail="token_required_for_rebind")

    member, session = await agent_mail_service.register_session(db, request)
    capability_token = (
        None if hashless_rebind else await agent_mail_service.ensure_capability_token(db, session)
    )
    members = await agent_mail_service.list_team(db)
    member_resp = next(candidate for candidate in members if candidate.id == member.id)
    session_resp = next(
        candidate for candidate in member_resp.sessions if candidate.session_key == session.session_key
    )
    return MailAgentRegisterResponse(
        member=member_resp,
        session=session_resp,
        capability_token=capability_token,
    )
```

Leave both `next(...)` lookups exactly as they are. **Do not touch `_register_from_hook` (`:184-200`)** — the hook path must not mint. Task 4 renames this handler's `request` parameter; do not do that yet.

`HTTPException` must be imported in `agent_mail.py`; check the `from fastapi import ...` line and add it if absent (Task 4 needs it too). `settings` must be imported too — `from app.config import settings`; Task 4 adds the same import, so if it is already there, leave it.

**Note the two conditions are deliberately different.** `hashless_rebind` gates the **mint** and is flag-independent. `hashless_rebind and settings.mail_capability_tokens_required` gates the **refusal**. Collapsing them into one condition gets one of the two wrong whichever way you collapse it: refuse always ⇒ deploy-day outage; mint when not enforcing ⇒ a durable leader-resolving credential handed out during the unwatched window. Step 7's tests pin both halves.

**Four things this branch deliberately does not do.**

1. **It does not read a presented token.** §3.4's row 4 is *"no token presented but a hash exists."* Its rows 2 and 3 — re-registration *with* a token — are about a row that **has** a hash, which `ensure_capability_token`'s existing guard already handles by returning `None`. So the only case needing a new branch is the hashless one, and for that case a presented token cannot help: there is no stored hash to verify it against. Accepting one would be authentication theatre. **Do not add an `X-Deck-Session-Token` header check to this route** — Task 5 adds the header to the *write* routes, and adding it here would suggest the token gates registration, which it cannot.
2. **It does not distinguish `mcp` from `hook` or `observed` rows.** The hook path never reaches this route (`_register_from_hook` is called from the hook handlers), and hook keys live in a different namespace anyway (`cc:`/`codex:`/`copilot:`/`opencode:`, `agent_mail.py:156-171`), as do observed rows (`tmux:`, `:368`). A collision would need a caller to guess a key in another namespace and would be handled for the same reason. Keep the check namespace-agnostic; it is a fact about the row, not about the source.
3. **In grace mode it does not fail the registration in any way.** The response is a normal `200` with `capability_token: None`. Do not add a warning status, do not omit fields, do not raise anything the shim's `raise_for_status` would catch — `_deck_request` turns any 4xx into `{"ok": False}` and `_guard` turns that into a tool failure. The *only* difference from today's behaviour is that no token is minted.
4. **It does not null or otherwise "tidy" the existing row's hash.** There is no hash to null here (it is already `NULL`), and the general rule from §3.4 stands: a row that *has* a hash keeps it forever. See the retention discussion above — nulling a hash on disconnect is what would turn a dead row back into a mintable row 1.

- [ ] **Step 10: Run the route test and the full suite**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_mail/test_capability_tokens.py -q -p no:warnings && pytest tests/agent_teams/ tests/agent_mail/ -q -p no:warnings
```

Expected: `13 passed` in `test_capability_tokens.py` — the 4 from Task 1 plus this task's 9, since Step 1's four service tests and Step 7's five route tests both **append to the same file** — then `480 passed` (471 after Task 2 + this task's 9). No existing test asserts the exact key set of the register response, so nothing should break — if something does, report it before adapting.

- [ ] **Step 11: Commit**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1 && git add backend/app/services/agent_mail_service.py backend/app/models/schemas.py backend/app/api/v1/agent_mail.py backend/tests/agent_mail/test_capability_tokens.py && git commit -m "feat(mail): mint a per-session capability token on registration

ensure_capability_token stores only a SHA-256 hash and returns the plaintext
exactly once. It never rotates: the MCP shim re-registers before every tool
call, so rotating would invalidate the token the shim holds on every call.

Minted from the register_agent route, not inside register_session, because
register_session returns a 2-tuple that 42 call sites unpack, and because its
second caller (_register_from_hook) runs under handlers that swallow
exceptions and return {} -- nowhere to deliver a one-time secret.

A registration for a session_key whose row already exists with a NULL hash is
never backfilled, in either mode. Backfilling is a leader impersonation:
register_session rewrites a known key's row in place and can keep the stored
member when provider and repo_id agree, both of which the unauthenticated GET
/agent-mail/team publishes alongside the session_key. No path deletes an mcp
session row, so a hash minted "just during grace" resolves to that member for
as long as the row exists -- which is forever, across 150 live rows.

Under enforcement the same registration is refused 409
token_required_for_rebind; in grace mode it returns 200 with no token. The
refusal is flag-gated and the no-mint rule is not, because the shim's _guard
re-registers before every tool call and surfaces a failed registration as a
failed tool -- refusing in grace mode would take every running agent's mail
offline on deploy, which is the one thing grace mode exists to prevent. It
would also defend nothing there: grace mode already accepts an unverified
sender_member_id, so the impersonation needs no token at all. The legitimate
remedy is a shim restart, which yields a new per-process session_key and a
clean first registration -- already the rollout's pane-restart step, performed
before the flag is flipped.

Spec: 2026-08-05-distinct-approver-identity-design.md section 3.4"
```

---

### Task 4: Bind the registration to the pane it came from — and write the row it reads

**Files:**
- Modify: `backend/app/api/v1/agent_mail.py:119-130` (the `register_agent` route)
- Modify: `backend/app/utils/peer_process.py` (add `pane_is_alive`)
- Modify: `backend/app/services/agent_mail_service.py` (add `resolve_pane_binding`)
- Modify: `backend/app/services/agent_bridge/spawn.py:75-87` (return the pane pid from `new-session`)
- Modify: `backend/app/services/agent_team_service.py:569` and `:637` (write the binding row on both launch paths)
- Test: `backend/tests/agent_mail/test_capability_tokens.py`
- Modify: `backend/tests/test_agent_bridge_spawn.py` (three named tests; Steps 17–19)
- Modify: `backend/tests/agent_teams/test_agent_team_service.py` (the binding-writer tests; Steps 20–24)

**Interfaces:**
- Consumes: `peer_process.resolve_peer_pane` and `read_proc_stat` (Task 2); `AgentPaneBinding`, `MailAgentSession.bound_pane_pid`, `.bound_pane_proc_start` (Task 1); `ensure_capability_token` (Task 3).
- Produces:
  - `peer_process.pane_is_alive(pane_pid: int, pane_proc_start: str) -> bool | None` — `True` alive, `False` gone, `None` unobservable.
  - `agent_mail_service.resolve_pane_binding(db, pane) -> AgentPaneBinding | None` — the live row for a pane, pruning stale ones.
  - A module-level override seam on the route: `agent_mail.resolve_request_pane(request) -> PeerPane | None`.
  - `spawn_session`'s return dict gains **`"pane_pid": int | None`**.
  - `agent_team_service._write_pane_binding(db, *, pane_pid, slot, preset, tmux_target) -> None` — select-then-update on `(pane_pid, pane_proc_start)`, then `await db.commit()`.

**Why the writer is in this task and not its own.** The reader and the writer are one policy. Steps 1–16 build the reader — a route that refuses `409 bind_pending` when a pane claims team context and has no binding row. Nothing in this repository writes that row. Shipping the reader alone is not a partial feature; it is an outage, and the section below measures it. A reviewer cannot usefully accept one half.

**The binding check lives at the route, not in `register_session`.** `register_session` has a second caller — `_register_from_hook` (`agent_mail.py:184-200`), reached from `hook_session_start` and `hook_user_prompt_submit`, both of which swallow every exception and return `{}`. A `409 bind_pending` raised inside `register_session` would be swallowed there and reported as success. The hook path must keep working exactly as it does today, unbound.

**`register_agent`'s body parameter is already named `request`.** The ASGI `Request` therefore needs a different name. Use `http_request` and put it **first** in the signature.

**The four-row policy, verbatim from §3.3a.** The body's `team_slot_id` / `team_preset_id` claim is used **only** to choose between two refusal policies, never for identity:

| Binding row | Body claims team context | Result |
| --- | --- | --- |
| exists, `slot_id` set | either way | bound to that slot (derived; a disagreeing body claim is `403`) |
| exists, `slot_id` NULL | either way | unbound token |
| none | **no** | unbound token — an ordinary repo member |
| none | **yes** | `409 bind_pending`, retryable |

Why the asymmetry is safe: claiming team context you do not have yields `bind_pending`, i.e. **no token at all** — strictly worse for the liar than the unbound token they would otherwise get. There is no version of this lie that gains a slot binding.

Two more rungs from §3.3:

- **Peer pid underivable** ⇒ under enforcement, refuse with `bind_unverifiable`; in grace mode (`mail_capability_tokens_required = False`), mint unbound. Refusing in grace mode would break every non-Linux and every pre-upgrade caller on deploy, which is the one thing grace mode exists to prevent.
- **No ancestor is a tmux pane** ⇒ mint unbound. Not every caller is tmux-hosted.

**`bind_pending` is `409`, not `403`.** Deck may simply not have committed the binding yet. A `403` would permanently strand a correctly-launched agent that registered early. Worst case for an **idle** agent is 300s (`HEARTBEAT_UNAVAILABLE_INTERVAL_SECONDS`, `agent_mail_server.py:19`) — the shim's failing heartbeat path backs off to 300s, not 60s. An agent that calls any mail tool retries immediately, because `_guard` (`:201-203`) re-registers first. **PR0 changes neither heartbeat constant.**

#### The writer half: nothing in this repository writes an `agent_pane_bindings` row

**Added 2026-08-10 (self-review, Finding B).** Steps 1–16 implement the reader. Spec §3.8 (`:970`) assigns the writer to `agent_team_service.py` on both paths (`:569`, `:637`); an earlier draft of this plan named that file **nowhere**, in neither the File Structure table nor the Task Index. That omission is not a missing nicety. It reintroduces the exact defect §3.3a exists to prevent, and here is the chain, each link measured:

1. `grep -rn AgentPaneBinding backend/app/` returns **only** Task 1's model and Task 4's reader. No `db.add(AgentPaneBinding(...))` anywhere.
2. Deck-launched panes **do** claim team context. The shim sends `team_preset_id` / `team_slot_id` iff `CLAUDE_DECK_TEAM_PRESET_ID` / `_SLOT_ID` are in the pane environment (`agent_mail_server.py:148-153`), and the only writer of those variables is `_execute_plan_item`'s spawn env (`agent_team_service.py:619-626`).
3. So every Deck-launched pane lands on **row 4** of the policy table above: no binding row, claims team context ⇒ `409 bind_pending`.
4. `_guard` (`agent_mail_server.py:201-203`) re-registers before **every** tool call. A refusal at registration is therefore a refusal of every mail tool, for the life of the pane, with no retry that can ever succeed.

Revision 4 of the spec shipped this failure for hand-started panes and §3.3a fixed it by *narrowing the refusal*. Omitting the writer re-creates it for exactly the population §3.3a left inside the refusal. **Ship the reader without the writer and Deck-launched teams lose mail entirely.**

**Four measurements decide how the writer is built.** Do not re-derive them; stop and report if any turns out false.

**1. The row cannot be written on a second connection — it must commit on the caller's session.** `launch` does `db.add(launch)` + `await db.flush()` (`agent_team_service.py:508-509`) **before** the slot loop, so by the time `_execute_plan_item` runs, the request's connection already holds SQLite's write lock. Measured on a file-backed WAL database with session A in exactly that state: a second session's `INSERT` into `agent_pane_bindings` **failed after 1.506 s** with `OperationalError: (sqlite3.OperationalError) database is locked` (`busy_timeout` is 5000 ms, `database.py:16-58`); the same insert on A's own session committed fine. So §3.3's phrase *"committed on its own"* means **its own commit**, not its own connection. Writing that clearly matters because "commit it independently so the launch can still roll back" is the natural reading and it does not run.

**2. That mid-loop commit IS visible to the registering shim, and it carries the launch row with it.** Measured, same setup: after A commits the binding mid-loop, a **fresh** connection B reads `bindings=[(4242, 1)]` and `launches=[(1, 'running')]`, while `launch_items=[]` — still uncommitted, since `_record_launch_item` only calls `db.add`. B's reads took 0.0015 s, no lock wait; WAL lets the reader through. This is the claim the whole task rests on: the shim registers on a different connection, so a commit is the only thing that can make the row visible to it.

**What else that commit carries — read [[commit-ordering-decides-what-survives-rollback]] before writing this step.** The commit is on the caller's session, so it persists every mutation pending there. Traced on the autonomous-dispatch path (`github_dispatch_service.dispatch_pending`), which reaches `launch` through `launcher` (`:306`):

| Pending mutation at the moment `_write_pane_binding` commits | Consequence of committing it early |
| --- | --- |
| The `AgentTeamLaunch` row, `status='running'` (flushed at `:509`) | **Harmless.** `AgentTeamLaunch` is read in only two places, both `agent_team_service` preset-deletion queries (`:147`, `:153`), and nothing in the codebase reads `status == 'running'`. `launch.status` is overwritten at `:527-528` and committed at `:530` on every non-raising path. |
| `item.brief_message_id` / `brief_delivery_nudge_at` / `_count`, set by `_send_dispatch_brief_to_slot` (`:628-630`) | **Already committed before we get here.** `send_direct_message` → `send_message` commits at `agent_mail_service.py:899`. Not our commit's doing. |
| `workspace` lease columns from `github_workspace_service.acquire` (`:277`) | **Already committed** — `acquire` commits at `github_workspace_service.py:136`/`:145`. |
| `item.owner_slot_id` / `routing_method` / `dispatch_status` | **Not yet set.** They are assigned *after* `launcher` returns (`:332-334`). Nothing of the item's dispatch state is pending during the loop. |
| The `except ValueError` path: `escalate` + `release` + `commit` (`:317-324`) | **Unaffected.** Those run after `launch` has already returned or raised; a binding row committed for a pane that then failed to launch is pruned by `resolve_pane_binding`'s liveness check (Step 8), because the pane is not alive. |

So the early commit is safe **on the paths that exist today**, and the reason is that everything upstream of `launch` already committed itself. Record that reasoning in the code comment, not just here: the safety is a property of the current callers, not of the design, and a future caller that holds an uncommitted mutation across `launch` breaks it.

**3. The write is select-then-update, never a bare insert.** The reuse path re-binds the **same** pane on every dispatch to that slot, so `UNIQUE(pane_pid, pane_proc_start)` is hit repeatedly. Measured: the second insert raises `IntegrityError: UNIQUE constraint failed: agent_pane_bindings.pane_pid, agent_pane_bindings.pane_proc_start`, and the session is then **poisoned** — the very next statement raises `PendingRollbackError`, which inside `launch`'s loop means every remaining slot fails too. Select-then-update reslots the same row cleanly (measured slot 1 → 2 → 2, same row id throughout, no new rows).

**4. The reuse path's pid is a string, and pydantic already coerces it.** Discovery types it `pid: str` (`agent_bridge/discovery.py:80`), carried into `plan_item.matching_session` by `_matching_session_payload` (`:994-1006`). Two consequences, measured separately:
- `AgentTeamLaunchResultItem(pane_pid="4242")` yields `pane_pid=4242` as an `int` — pydantic coerces, and `pane_pid="%1"` raises `ValidationError` rather than storing garbage. So `result.pane_pid` is already a safe `int | None`. **Read the pid off the result object, not off `matching_session`.**
- Do **not** hand a raw string to the ORM instead. Storing `pane_pid="4242"` gives SQLite `typeof='integer'`, but within the *same* session the in-memory attribute stays `'4242'` (a `str`) and `'4242' == 4242` is `False`; only a fresh session read yields `4242`. The writer and `resolve_pane_binding` can share a session, so a str would compare unequal to the reader's int. Taking the pid from the validated result object avoids this entirely — which is why that is the specified source.

**Where the spawn path's pid comes from — a measured trade-off, and the plan picks one.** `spawn_session` returns no pid at all (`{provider, provider_display_name, tmux_target, session_name}`, `spawn.py:101-106`), so **`spawned.get("pid")` at `:637` is always `None` today** — the field the result object already has has never been populated on this path. Two ways to fix it, both measured:

| Option | Test fallout | Race |
| --- | --- | --- |
| **`-P -F '#{pane_pid}'` inside `new-session`** (chosen) | Breaks exactly **3 of 13** tests in `tests/test_agent_bridge_spawn.py`, named in Steps 17–19. Placement before or after the `-e` flags makes no difference to which three. | **None.** Returns `rc=0 49769` even for a command that exits immediately. |
| Post-hoc `tmux list-panes -t <name> -F '#{pane_pid}'` | Breaks **0** tests (13 passed). | **Racy.** For a session whose command exits at once, the tmux server is already gone: measured `rc=1 no server running`, so the pid is silently `None` and the pane never binds. |

`-P -F` is chosen: three re-authored assertions are a bounded, visible cost paid once, and the race has no bound. Do not put `-P -F` **after** the shell command — measured `rc=0` with **empty stdout**; that escape from the argv assertions does not exist.

**One correction to carry into the comment.** `spawn.py` hardcodes `tmux_target = f"{name}:0.0"` (`:104`). That is **correct** for the single-window session `new-session` creates, even under `base-index 1`: measured, `display-message -p -t 'alpha:0.0'` returned `48778 alpha:1.1`, matching `list-panes -a` ground truth, and stayed correct with a second session present. The `:0.0` form only misreports for a **multi-window** session, where it resolves to the *current* window's pane and returns `rc=0` even for a bogus index. So do not "fix" `tmux_target` in this task — but do not build the pid on `display-message -t <target>` either, because that form's correctness depends on a property (`one window`) that nothing enforces. `-P -F` reads the pane tmux just created, with no target string in the middle.

**`agent_team_service.py` has no logger and no `subprocess` import** (checked: `:1-51`). The writer needs neither — the pid arrives on the result object and `pane_proc_start` comes from `peer_process.read_proc_stat`, which Task 2 already built and which `agent_team_service` can import without a cycle (`app.utils.peer_process` imports nothing from `app.services`).

**And one consumer to be aware of.** `spawn_session`'s dict is returned straight to an HTTP client at `agent_bridge/router.py:323`, under `@router.post("/sessions")` with **no `response_model`** — so the new `pane_pid` key reaches the wire unfiltered. That is acceptable: a pane pid is not a secret, it is already exposed by `GET /agent-bridge/sessions` (discovery projects `pid` at `discovery.py:92`), and adding a `response_model` now would be an unrelated behaviour change to a route this spec does not touch. Recorded so a reviewer sees a decision.

- [ ] **Step 1: Write the failing test for `pane_is_alive`**

Append to `backend/tests/agent_mail/test_peer_process.py`:

```python
def test_pane_is_alive_distinguishes_gone_from_unobservable(tmp_path, monkeypatch):
    """Three-valued on purpose: gone means prune, unobservable means keep."""
    proc = tmp_path / "1234"
    proc.mkdir()
    (proc / "stat").write_text(_STAT)
    monkeypatch.setattr(peer_process, "_PROC_ROOT", str(tmp_path))

    assert peer_process.pane_is_alive(1234, "120913170") is True
    assert peer_process.pane_is_alive(1234, "99999999") is False  # pid reused
    assert peer_process.pane_is_alive(4321, "120913170") is False  # process gone


def test_pane_is_alive_is_none_when_proc_cannot_be_read(monkeypatch):
    def _boom(pid):
        raise PermissionError("no")

    monkeypatch.setattr(peer_process, "read_proc_stat", _boom)
    assert peer_process.pane_is_alive(1234, "120913170") is None
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_mail/test_peer_process.py -q -p no:warnings
```

Expected: `AttributeError: ... has no attribute 'pane_is_alive'`.

- [ ] **Step 3: Implement `pane_is_alive`**

Append to `backend/app/utils/peer_process.py`:

```python
def pane_is_alive(pane_pid: int, pane_proc_start: str) -> Optional[bool]:
    """Is the process at pane_pid still the one that started at pane_proc_start?

    Three-valued, mirroring _owner_process_is_alive in github_workspace_service:
      True  -- alive and the same process
      False -- gone, or the pid was reused by a different process (prune)
      None  -- cannot observe (keep the row; fail closed, never prune on doubt)

    A start time mismatch is not "maybe" -- it is proof the original process
    exited and something else took its number.
    """
    try:
        stat = read_proc_stat(pane_pid)
    except OSError:
        return None
    if stat is None:
        return False
    _ppid, current_start = stat
    return current_start == pane_proc_start
```

`read_proc_stat` already swallows `OSError` and returns `None`, so the `try` here catches only a monkeypatched raiser or a future change in that function. Keep it: the three-valued contract must not silently collapse to two if `read_proc_stat` ever starts propagating.

- [ ] **Step 4: Run to verify the tests pass**

Expected: `15 passed` in `test_peer_process.py`.

- [ ] **Step 5: Commit**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1 && git add backend/app/utils/peer_process.py backend/tests/agent_mail/test_peer_process.py && git commit -m "feat(mail): add three-valued pane liveness

pane_is_alive returns True/False/None so a pane that cannot be observed is
kept rather than pruned, matching _owner_process_is_alive's existing
distinction between process-gone and cannot-observe.

Spec: 2026-08-05-distinct-approver-identity-design.md section 3.3"
```

- [ ] **Step 6: Write the failing test for `resolve_pane_binding`**

Append to `backend/tests/agent_mail/test_capability_tokens.py`:

```python
from app.utils.peer_process import PeerPane


def _pane(pid: int = 3000, start: str = "111", target: str | None = "team:0.1") -> PeerPane:
    return PeerPane(pane_pid=pid, pane_proc_start=start, tmux_target=target, peer_pid=pid + 1)


@pytest.mark.asyncio
async def test_resolve_pane_binding_matches_on_pid_and_proc_start(db):
    db.add(AgentPaneBinding(pane_pid=3000, pane_proc_start="111", slot_id=None, preset_id=None))
    await db.commit()

    found = await agent_mail_service.resolve_pane_binding(db, _pane())
    assert found is not None and found.pane_pid == 3000


@pytest.mark.asyncio
async def test_resolve_pane_binding_ignores_a_row_with_a_stale_proc_start(db):
    """Pid reuse: the number matches, the process does not."""
    db.add(AgentPaneBinding(pane_pid=3000, pane_proc_start="OLD", slot_id=None, preset_id=None))
    await db.commit()

    assert await agent_mail_service.resolve_pane_binding(db, _pane(start="111")) is None


@pytest.mark.asyncio
async def test_resolve_pane_binding_prunes_rows_for_dead_panes(db, monkeypatch):
    """A row whose pane is gone is deleted, as session rows already are."""
    from app.utils import peer_process

    db.add(AgentPaneBinding(pane_pid=7777, pane_proc_start="OLD", slot_id=None, preset_id=None))
    db.add(AgentPaneBinding(pane_pid=3000, pane_proc_start="111", slot_id=None, preset_id=None))
    await db.commit()

    monkeypatch.setattr(
        peer_process, "pane_is_alive", lambda pid, start: pid == 3000
    )
    await agent_mail_service.resolve_pane_binding(db, _pane())

    remaining = (
        await db.execute(text("SELECT pane_pid FROM agent_pane_bindings ORDER BY pane_pid"))
    ).scalars().all()
    assert remaining == [3000]


@pytest.mark.asyncio
async def test_resolve_pane_binding_keeps_a_row_it_cannot_observe(db, monkeypatch):
    """None means 'cannot observe'. Never prune on doubt."""
    from app.utils import peer_process

    db.add(AgentPaneBinding(pane_pid=7777, pane_proc_start="OLD", slot_id=None, preset_id=None))
    await db.commit()

    monkeypatch.setattr(peer_process, "pane_is_alive", lambda pid, start: None)
    await agent_mail_service.resolve_pane_binding(db, _pane())

    remaining = (
        await db.execute(text("SELECT pane_pid FROM agent_pane_bindings"))
    ).scalars().all()
    assert remaining == [7777]
```

Import `AgentPaneBinding` from `app.models.database` at the top of the test file — Task 1 already did.

- [ ] **Step 7: Run to verify it fails**

Expected: `AttributeError: ... has no attribute 'resolve_pane_binding'`.

- [ ] **Step 8: Implement `resolve_pane_binding`**

Add to `agent_mail_service.py`, after `ensure_capability_token`. Add `from app.models.database import AgentPaneBinding` to the existing `from app.models.database import (...)` block (`:13-20`, keep it alphabetical — `AgentPaneBinding` sorts before `AgentTeamPreset`), and `from app.utils import peer_process` to the imports.

```python
    async def resolve_pane_binding(
        self, db: AsyncSession, pane: "peer_process.PeerPane"
    ) -> Optional[AgentPaneBinding]:
        """Find the live binding row for this pane, pruning dead ones.

        Rows are keyed (pane_pid, pane_proc_start): the pair is the identity,
        because a pid alone is reusable. A row whose pane is provably gone is
        deleted here -- the same "prune on the next registration sweep" policy
        session rows already follow. A row we merely cannot observe is kept.
        """
        rows = (await db.execute(select(AgentPaneBinding))).scalars().all()
        match: Optional[AgentPaneBinding] = None
        pruned = False
        for row in rows:
            if row.pane_pid == pane.pane_pid and row.pane_proc_start == pane.pane_proc_start:
                match = row
                continue
            if peer_process.pane_is_alive(row.pane_pid, row.pane_proc_start) is False:
                await db.delete(row)
                pruned = True
        if pruned:
            await db.commit()
        return match
```

The select is deliberately unfiltered: the prune is a whole-table sweep, which is what makes it "pruned on the next registration sweep" rather than "pruned only for panes that happen to re-register." The matching row is skipped by the `continue` before the liveness check — it is alive by construction, since its pane just made this request.

- [ ] **Step 9: Run to verify the tests pass**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_mail/test_capability_tokens.py -q -p no:warnings
```

Expected: `13 passed`.

- [ ] **Step 10: Commit**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1 && git add backend/app/services/agent_mail_service.py backend/tests/agent_mail/test_capability_tokens.py && git commit -m "feat(mail): resolve a pane to its slot binding, pruning dead rows

Keyed on (pane_pid, pane_proc_start) because a pid alone is reusable. Prunes
rows whose pane is provably gone; keeps rows it cannot observe.

Spec: 2026-08-05-distinct-approver-identity-design.md section 3.3"
```

- [ ] **Step 11: Write the failing route tests — all four policy rows**

Append to `backend/tests/agent_mail/test_capability_tokens.py`. **Every one of these must inject the resolver**: `httpx.ASGITransport` sets `scope["client"]` to `("127.0.0.1", 123)`, a port no real socket owns, so the kernel resolver can never succeed under test.

```python
import app.api.v1.agent_mail as agent_mail_routes


@pytest.fixture
def pane_resolver(monkeypatch):
    """Override the route's pane resolution. ASGITransport fakes the peer port."""

    def _set(pane):
        monkeypatch.setattr(
            agent_mail_routes, "resolve_request_pane", lambda http_request: pane
        )

    return _set


def _body(cwd, session_key="mcp:bind", **extra):
    body = {
        "source": "mcp",
        "provider": "claude",
        "cwd": str(cwd),
        "session_key": session_key,
    }
    body.update(extra)
    return body


@pytest.mark.asyncio
async def test_row_with_a_slot_binds_the_session(client, db, tmp_path, pane_resolver, slot):
    db.add(
        AgentPaneBinding(
            pane_pid=3000, pane_proc_start="111", slot_id=slot.id, preset_id=slot.preset_id
        )
    )
    await db.commit()
    pane_resolver(_pane())

    response = await client.post("/api/v1/agent-mail/agent/register", json=_body(tmp_path))
    assert response.status_code == 200
    assert response.json()["capability_token"]

    row = (
        await db.execute(
            text(
                "SELECT team_slot_id, bound_pane_pid, bound_pane_proc_start "
                "FROM mail_agent_sessions WHERE session_key = 'mcp:bind'"
            )
        )
    ).first()
    assert row == (slot.id, 3000, "111")


@pytest.mark.asyncio
async def test_row_with_a_null_slot_mints_unbound(client, db, tmp_path, pane_resolver):
    db.add(AgentPaneBinding(pane_pid=3000, pane_proc_start="111", slot_id=None, preset_id=None))
    await db.commit()
    pane_resolver(_pane())

    response = await client.post("/api/v1/agent-mail/agent/register", json=_body(tmp_path))
    assert response.status_code == 200
    assert response.json()["capability_token"]
    slot_id = (
        await db.execute(
            text("SELECT team_slot_id FROM mail_agent_sessions WHERE session_key = 'mcp:bind'")
        )
    ).scalar_one()
    assert slot_id is None


@pytest.mark.asyncio
async def test_no_row_and_no_claim_mints_unbound(client, tmp_path, pane_resolver):
    """A hand-started pane Deck never launched is an ordinary repo member."""
    pane_resolver(_pane())
    response = await client.post("/api/v1/agent-mail/agent/register", json=_body(tmp_path))
    assert response.status_code == 200
    assert response.json()["capability_token"]


@pytest.mark.asyncio
async def test_no_row_but_a_team_claim_is_bind_pending(client, tmp_path, pane_resolver, slot):
    """Retryable: Deck may not have committed the binding yet."""
    pane_resolver(_pane())
    response = await client.post(
        "/api/v1/agent-mail/agent/register",
        json=_body(tmp_path, team_slot_id=slot.id, team_preset_id=slot.preset_id),
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "bind_pending"


@pytest.mark.asyncio
async def test_a_disagreeing_slot_claim_is_403(client, db, tmp_path, pane_resolver, slot, other_slot):
    """Derive, do not compare -- and never silently overwrite."""
    db.add(
        AgentPaneBinding(
            pane_pid=3000, pane_proc_start="111", slot_id=slot.id, preset_id=slot.preset_id
        )
    )
    await db.commit()
    pane_resolver(_pane())

    response = await client.post(
        "/api/v1/agent-mail/agent/register",
        json=_body(tmp_path, team_slot_id=other_slot.id, team_preset_id=other_slot.preset_id),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_no_pane_ancestor_mints_unbound(client, tmp_path, pane_resolver):
    """resolve_peer_pane returned None because no ancestor is a tmux pane."""
    pane_resolver(None)
    response = await client.post("/api/v1/agent-mail/agent/register", json=_body(tmp_path))
    assert response.status_code == 200
    assert response.json()["capability_token"]


@pytest.mark.asyncio
async def test_unresolvable_peer_refuses_under_enforcement(
    client, tmp_path, pane_resolver, monkeypatch
):
    """Grace mode mints unbound; enforcement refuses bind_unverifiable."""
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    pane_resolver(None)
    response = await client.post(
        "/api/v1/agent-mail/agent/register",
        json=_body(tmp_path, team_slot_id=1, team_preset_id=1),
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "bind_unverifiable"


@pytest.mark.asyncio
async def test_unresolvable_peer_mints_unbound_in_grace_mode(client, tmp_path, pane_resolver):
    """The same request, enforcement off: mint rather than strand the caller."""
    assert settings.mail_capability_tokens_required is False
    pane_resolver(None)
    response = await client.post(
        "/api/v1/agent-mail/agent/register",
        json=_body(tmp_path, team_slot_id=1, team_preset_id=1),
    )
    assert response.status_code == 200
    assert response.json()["capability_token"]
```

You need `slot` and `other_slot` fixtures making two `AgentTeamSlot` rows on one preset. **Do not invent them** — `tests/agent_teams/test_agent_team_service.py` and `tests/agent_mail/test_registry.py` both already build slots; copy the shape from whichever helper is closest, and note in your report which you copied. Every required column must be set, or the insert fails with a constraint error that reads like a logic bug.

**Note what the last two tests pin down.** `pane_resolver(None)` cannot distinguish "no pane ancestor" from "no peer pid" — the route sees `None` either way, so the *only* thing that separates minting unbound from refusing `bind_unverifiable` is the enforcement flag. These two tests are the same request differing only in that flag, which is exactly the discrimination the route makes. Do not merge them into one loose assertion: a test that accepts either refusal proves nothing about which branch ran.

`test_no_pane_ancestor_mints_unbound` and `test_unresolvable_peer_mints_unbound_in_grace_mode` overlap by design — the first has no team claim, the second has one. Together they show the claim alone does not trigger a refusal in grace mode.

- [ ] **Step 12: Run to verify they fail**

Expected: the first assertion to fail is `AttributeError: module 'app.api.v1.agent_mail' has no attribute 'resolve_request_pane'`.

- [ ] **Step 13: Implement the route**

In `backend/app/api/v1/agent_mail.py`, add to the imports at `:7`:

```python
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
```

and add, near the top of the module:

```python
from app.config import settings
from app.utils import peer_process


def resolve_request_pane(http_request: Request) -> Optional[peer_process.PeerPane]:
    """Resolve the calling pane from the live connection.

    A module-level function so tests can override it: httpx.ASGITransport
    reports a synthetic client port that no real socket owns.

    MUST be called inside the handler, never after the response -- see
    app/utils/peer_process. Once the response is sent the socket is in
    TIME_WAIT, its inode reads 0, and no process owns it.
    """
    client = http_request.client
    if client is None:
        return None
    local_port = http_request.scope.get("server", (None, None))[1]
    return peer_process.resolve_peer_pane(client.host, client.port, local_port=local_port)
```

Then replace `register_agent`:

```python
@router.post("/agent/register", response_model=MailAgentRegisterResponse)
async def register_agent(
    http_request: Request,
    request: MailAgentRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    # Task 3's hashless-rebind rule stays FIRST and unchanged: mint never,
    # refuse only under enforcement. It precedes the binding policy on purpose --
    # a hashless existing row must be settled before anything else looks at the
    # caller, because register_session would repoint the row.
    existing = await agent_mail_service.peek_session_by_key(db, request.session_key)
    hashless_rebind = existing is not None and existing.capability_token_hash is None
    if hashless_rebind and settings.mail_capability_tokens_required:
        raise HTTPException(status_code=409, detail="token_required_for_rebind")

    claims_team_context = request.team_preset_id is not None or request.team_slot_id is not None
    pane = resolve_request_pane(http_request)

    binding = None
    if pane is not None:
        binding = await agent_mail_service.resolve_pane_binding(db, pane)
    elif claims_team_context and settings.mail_capability_tokens_required:
        # Cannot verify where this caller runs, and it claims a slot. Refuse --
        # retryable, because the cause may be a binding that is not committed
        # yet. In grace mode we mint unbound instead: refusing here would break
        # every pre-upgrade and non-Linux caller the moment PR0 deploys.
        raise HTTPException(status_code=409, detail="bind_unverifiable")

    derived_slot_id = binding.slot_id if binding is not None else None
    if binding is None and claims_team_context:
        raise HTTPException(status_code=409, detail="bind_pending")
    if (
        request.team_slot_id is not None
        and derived_slot_id is not None
        and request.team_slot_id != derived_slot_id
    ):
        # Derive, do not compare -- and never silently overwrite: a silent
        # overwrite would report a misconfigured shim as success.
        raise HTTPException(status_code=403, detail="slot_claim_mismatch")

    request = request.model_copy(
        update={
            "team_slot_id": derived_slot_id,
            "team_preset_id": binding.preset_id if binding is not None else None,
        }
    )
    member, session = await agent_mail_service.register_session(db, request)
    if pane is not None:
        session.bound_pane_pid = pane.pane_pid
        session.bound_pane_proc_start = pane.pane_proc_start
        await db.commit()
    capability_token = (
        None if hashless_rebind else await agent_mail_service.ensure_capability_token(db, session)
    )
    members = await agent_mail_service.list_team(db)
    member_resp = next(candidate for candidate in members if candidate.id == member.id)
    session_resp = next(
        candidate for candidate in member_resp.sessions if candidate.session_key == session.session_key
    )
    return MailAgentRegisterResponse(
        member=member_resp,
        session=session_resp,
        capability_token=capability_token,
    )
```

Three things to be careful about:

0. **`hashless_rebind` is computed once and used twice, and the two uses have different conditions.** The refusal is `hashless_rebind and settings.mail_capability_tokens_required`; the mint suppression is `hashless_rebind` alone. Task 3 argues that at length; do not simplify it here. Note also that in grace mode the flow *continues* past the refusal — so a hashless rebind still gets its pane rebound and its row rewritten, and still returns `200`. Only the mint is withheld. Task 3's `test_a_hashless_row_in_grace_mode_neither_mints_nor_refuses` covers the route as this task leaves it, so it must still pass after this step.
1. **The `model_copy` that overwrites `team_slot_id` also overwrites `team_preset_id` with `None` when there is no binding.** That is deliberate — an unbound session has neither. But `register_session` *infers* team context from the process when the body carries none (`_infer_team_context_from_process`, `:158`), so clearing both keeps that inference path live rather than short-circuiting it. Verify with the existing `tests/agent_mail/test_registry.py` inference tests: they must all still pass. If any breaks, **stop and report** — it means inference and derivation disagree, which is a design question, not an implementation detail.
2. **`Optional` must be imported** in `agent_mail.py` for `resolve_request_pane`'s annotation. Check the existing imports; add `from typing import Optional` if absent.

- [ ] **Step 14: Run the new tests and the full suite**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_mail/test_capability_tokens.py -q -p no:warnings && pytest tests/agent_teams/ tests/agent_mail/ -q -p no:warnings
```

Expected: `25 passed` in `test_capability_tokens.py` (4 from Task 1 + 9 from Task 3 + 4 from this task's Step 6 + 8 from Step 11) and `494 passed` for the two suites. That suite figure is *mid-task* and deliberately below the table's 497: Steps 17-24 add three more `test_agent_team_service.py` cases after this point, plus two in `test_agent_bridge_spawn.py` that fall outside these two directories entirely. For the full suite, expect the `test_registry.py` inference tests to be the risk area — read constraint 1 above before touching anything.

- [ ] **Step 15: Verify the hook path is untouched**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_mail/test_hooks_api.py -q -p no:warnings
```

Expected: unchanged from baseline. The hook routes call `_register_from_hook`, which must never see the binding policy — if these fail, the check leaked out of the route.

- [ ] **Step 16: Commit**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1 && git add backend/app/api/v1/agent_mail.py backend/tests/agent_mail/test_capability_tokens.py && git commit -m "feat(mail): bind registration to the caller's tmux pane

The slot is derived from the kernel, never from the body: a disagreeing
team_slot_id claim is 403, not a silent overwrite. A pane with no binding row
mints unbound if it claims no team context (an ordinary repo member) and gets
a retryable 409 bind_pending if it does.

The policy lives at the route because register_session's other caller,
_register_from_hook, runs under handlers that swallow exceptions and return {}
-- a refusal raised there would be reported as success.

Spec: 2026-08-05-distinct-approver-identity-design.md sections 3.3, 3.3a"
```

The reader is now complete and the writer is not. **Until Step 24 commits, a Deck-launched team pane gets `409 bind_pending` on every mail tool.** Do not stop the task here, and do not deploy this commit alone.

- [ ] **Step 17: Re-author the three spawn tests for the added argv pair**

`spawn_session` is about to insert `-P -F '#{pane_pid}'` after `-c <directory>`, so the shell command moves from index 7 to index 9 and the plain-launch argv grows from 8 entries to 10. Exactly three of the 13 tests in `backend/tests/test_agent_bridge_spawn.py` assert on those positions. Measured — these three and no others.

Re-index the argv prefix, and switch the command assertion to `[-1]`. In `test_claude_worktree_uses_generated_session_name_when_blank` (`:27-28`), replace:

```python
    assert calls[0][:7] == ["tmux", "new-session", "-d", "-s", "repo-abcd", "-c", str(tmp_path)]
    assert "--worktree repo-abcd" in calls[0][7]
```

with:

```python
    assert calls[0][:10] == [
        "tmux", "new-session", "-d", "-s", "repo-abcd", "-c", str(tmp_path),
        "-P", "-F", "#{pane_pid}",
    ]
    assert "--worktree repo-abcd" in calls[0][-1]
```

The `[-1]` is the change that matters: the shell command is always last, so the assertion stops depending on how many flags precede it. Four sites in this file already use `calls[0][-1]` / `argv[-1]` (`:141`, `:171`, `:228`, `:268`), so this is the file's own idiom, not a new one.

In `test_claude_resume_resolves_directory_from_transcript_cwd` (`:68-69`), the same shape:

```python
    assert calls[0][:10] == [
        "tmux", "new-session", "-d", "-s", "claude-deck-abcd", "-c", str(project_dir),
        "-P", "-F", "#{pane_pid}",
    ]
    assert "--resume session-123" in calls[0][-1]
```

In `test_anthropic_platform_adds_no_env_flags` (`:324-325`):

```python
    assert argv[:10] == [
        "tmux", "new-session", "-d", "-s", "repo-abcd", "-c", str(tmp_path),
        "-P", "-F", "#{pane_pid}",
    ]
    assert len(argv) == 11
```

`assert "-e" not in argv` (`:323`) stays exactly as it is — that is the assertion this test exists for, and `-P`/`-F` do not disturb it. Keep the length assertion rather than deleting it: it is what proves no *other* flag crept in. **8 becomes 11**, because this platform contributes no `-e` pairs and the argv is exactly `["tmux", "new-session", "-d", "-s", name, "-c", dir, "-P", "-F", "#{pane_pid}", shell_command]` — ten flags plus the command. If the run reports a different number, stop: something other than these two flags was added.

The other four tests that touch argv positions — `:99`, `:135`, `:141`, and the three `shlex.split(calls[0][-1])` sites — are expected to keep passing: `:99` and `:135` assert only `argv[:7]`, which is unchanged, and every `-1` site still finds the command last. Measured: 3 failures, not 7. If a fourth test fails, stop and report; it means the flags went somewhere other than after `-c <directory>`.

Also add a new test to the same file, asserting the pid actually comes back:

```python
def test_spawn_session_returns_the_pane_pid(monkeypatch, tmp_path):
    """The binding writer keys on this; a None pid means the pane never binds."""
    from app.services.agent_bridge import spawn
    from app.services.providers.base import SpawnCommandOptions

    def fake_run(args, capture_output=True, text=True, timeout=10):
        return SimpleNamespace(returncode=0, stdout="49769\n", stderr="")

    monkeypatch.setattr(spawn, "_session_name_for", lambda directory: "repo-abcd")
    monkeypatch.setattr(spawn.subprocess, "run", fake_run)
    spawn.get_spawned_sessions().clear()

    result = spawn.spawn_session(
        "claude-code",
        SpawnCommandOptions(directory=str(tmp_path), mode="plain"),
    )
    assert result["pane_pid"] == 49769


def test_spawn_session_pane_pid_is_none_when_tmux_prints_nothing(monkeypatch, tmp_path):
    """Every other test in this file stubs stdout='' -- that must not raise."""
    from app.services.agent_bridge import spawn
    from app.services.providers.base import SpawnCommandOptions

    def fake_run(args, capture_output=True, text=True, timeout=10):
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(spawn, "_session_name_for", lambda directory: "repo-abcd")
    monkeypatch.setattr(spawn.subprocess, "run", fake_run)
    spawn.get_spawned_sessions().clear()

    result = spawn.spawn_session(
        "claude-code",
        SpawnCommandOptions(directory=str(tmp_path), mode="plain"),
    )
    assert result["pane_pid"] is None
```

The second test is not padding. **Every existing test in this file stubs `stdout=""`** (`SimpleNamespace(returncode=0, stdout="", stderr="")`, at all 13 sites), so a parser that raises on empty output would fail all 13 rather than 3. That test pins the tolerance the other 12 silently depend on.

- [ ] **Step 18: Run to verify the three fail and the two new ones fail**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/test_agent_bridge_spawn.py -q -p no:warnings
```

Expected: **5 failed, 10 passed.** The three re-authored tests fail on the missing `-P`/`-F` (`AssertionError` on the list compare); the two new ones fail with `KeyError: 'pane_pid'`. If a *sixth* test fails, stop and report.

- [ ] **Step 19: Return the pane pid from `spawn_session`**

In `backend/app/services/agent_bridge/spawn.py`, change the `subprocess.run` argv (`:76`) to insert the two flags after `-c directory`:

```python
        result = subprocess.run(
            [
                "tmux", "new-session", "-d", "-s", name, "-c", directory,
                "-P", "-F", "#{pane_pid}",
                *env_flags,
                shell_command,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
```

Then parse it, immediately after the existing `returncode` check (`:82-83`) and before the `except FileNotFoundError`:

```python
        pane_pid = _parse_pane_pid(result.stdout)
```

and add the parser at module level, beside `_env_flags`:

```python
def _parse_pane_pid(stdout: str) -> int | None:
    """Read the pane pid tmux printed for -F '#{pane_pid}'.

    Returns None rather than raising: a pane with no pid simply never gets an
    agent_pane_bindings row, which the registration route already handles as
    "no binding" (spec 3.3a). Raising here would turn an unparseable line into
    a failed launch.
    """
    line = (stdout or "").strip().splitlines()
    if not line:
        return None
    try:
        return int(line[0].strip())
    except ValueError:
        return None
```

Finally add the key to the return dict (`:101-106`):

```python
    return {
        "provider": provider.id,
        "provider_display_name": provider.display_name,
        "tmux_target": f"{name}:0.0",
        "session_name": name,
        "pane_pid": pane_pid,
    }
```

`pane_pid` must be assigned on every path that reaches the return. It is set inside the `try`, and both `except` branches raise, so it is always bound — verify that when you edit, because a `NameError` here would surface as a failed launch.

**Do not change `tmux_target`.** The `:0.0` form is correct for the single-window session this call creates, even under `base-index 1` — see the correction above.

Run the spawn tests again:

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/test_agent_bridge_spawn.py -q -p no:warnings
```

Expected: **15 passed** (13 original + 2 new). If `test_anthropic_platform_adds_no_env_flags` still fails on `len(argv)`, read the actual length off the failure and write that number — that is the step where the count is established by measurement, not by arithmetic in this plan.

Then the wider suite, because `spawn_session` has three callers:

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/ -q -p no:warnings
```

Expected: the one pre-existing failure (`test_multi_provider_smoke.py::test_agent_bridge_session_filter_smoke`) and nothing else. The third caller is `agent_bridge/router.py:323`, which returns the dict straight to the HTTP client with no `response_model` — so the new key reaches the wire, deliberately.

- [ ] **Step 20: Write the failing test for the binding writer, spawn path**

Append to `backend/tests/agent_teams/test_agent_team_service.py`. Read `test_launch_spawns_and_records_items` first (`:1108-1126`) — this test copies its `fake_spawn` shape and adds the pid.

```python
@pytest.mark.asyncio
async def test_launch_writes_a_pane_binding_on_the_spawn_path(db, tmp_path, monkeypatch):
    """Without this row every Deck-launched pane gets 409 bind_pending forever."""
    from sqlalchemy import text

    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Binding team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Dev agent",
                    provider="codex-cli",
                    repo_path=str(repo),
                )
            ],
        ),
    )
    plan = await agent_team_service.plan_launch(db, preset.id)
    assert plan.items[0].action == "spawn"

    def fake_spawn(provider_id, options, *, extra_env=None):
        return {
            "session_name": "repo-abcd",
            "tmux_target": "repo-abcd:0.0",
            "pane_pid": 4242,
        }

    monkeypatch.setattr("app.services.agent_team_service.spawn_session", fake_spawn)
    monkeypatch.setattr(
        "app.services.agent_team_service.read_proc_stat", lambda pid: (1, "120913170")
    )

    result = await agent_team_service.launch(
        db,
        preset.id,
        AgentTeamLaunchRequest(confirm_plan_hash=plan.plan_hash),
    )
    assert result.items[0].pane_pid == 4242

    rows = (
        await db.execute(
            text(
                "SELECT pane_pid, pane_proc_start, slot_id, preset_id, tmux_target "
                "FROM agent_pane_bindings"
            )
        )
    ).all()
    assert rows == [(4242, "120913170", preset.slots[0].id, preset.id, "repo-abcd:0.0")]


@pytest.mark.asyncio
async def test_pane_binding_is_written_before_the_slot_loop_ends(db, tmp_path, monkeypatch):
    """The row must exist while the loop is still running, not after it.

    A shim spawned for slot 1 can register while slots 2-6 are still spawning
    (spec 3.3: "the window is the whole launch"). This asserts the row is
    queryable from inside the loop, using a second slot's spawn as the probe
    point. It does NOT prove the write was committed -- see the caution below.
    """
    from sqlalchemy import text

    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Ordering team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Agent one", provider="codex-cli", repo_path=str(repo)
                ),
                AgentTeamSlotCreate(
                    display_name="Agent two", provider="codex-cli", repo_path=str(repo)
                ),
            ],
        ),
    )
    plan = await agent_team_service.plan_launch(db, preset.id)
    assert [item.action for item in plan.items] == ["spawn", "spawn"]

    spawn_calls: list[int] = []
    observed: list[list] = []

    def fake_spawn(provider_id, options, *, extra_env=None):
        spawn_calls.append(len(spawn_calls))
        return {
            "session_name": f"repo-abc{len(spawn_calls)}",
            "tmux_target": f"repo-abc{len(spawn_calls)}:0.0",
            "pane_pid": 4240 + len(spawn_calls),
        }

    real_bootstrap = agent_team_service._bootstrap_prompt

    async def spy_bootstrap(db_arg, preset_arg, slot_arg):
        # Runs at the TOP of each spawn, so on slot 2 it sees slot 1's write.
        observed.append(
            (await db_arg.execute(text("SELECT pane_pid FROM agent_pane_bindings"))).all()
        )
        return await real_bootstrap(db_arg, preset_arg, slot_arg)

    monkeypatch.setattr("app.services.agent_team_service.spawn_session", fake_spawn)
    monkeypatch.setattr(
        "app.services.agent_team_service.read_proc_stat", lambda pid: (1, "120913170")
    )
    monkeypatch.setattr(agent_team_service, "_bootstrap_prompt", spy_bootstrap)

    await agent_team_service.launch(
        db, preset.id, AgentTeamLaunchRequest(confirm_plan_hash=plan.plan_hash)
    )

    assert observed[0] == [], "no binding exists before the first slot spawns"
    assert observed[1] == [(4241,)], "slot 1's binding is visible during slot 2's spawn"
    final = (await db.execute(text("SELECT pane_pid FROM agent_pane_bindings"))).all()
    assert sorted(final) == [(4241,), (4242,)]
```

**A caution on the second test, and it is the important one in this pair.** It proves *ordering* — the row lands inside the loop rather than after it — and that is genuinely worth pinning, because writing the binding after the loop is the natural refactor and it reopens the whole race. It does **not** prove the write was *committed*. The `db` fixture in `tests/agent_teams/conftest.py` is a single **in-memory** session, and a second connection to `:memory:` is a different database, so no test in this suite can distinguish a commit from a flush. Both pass either way.

**The cross-connection claim was verified by direct measurement outside the suite** — a file-backed WAL database with a reader on a fresh connection, seeing `bindings=[(4242, 1)]` while `launch_items=[]` — and that measurement is recorded in this task's design section above. Do not write a test that *claims* to prove it against the in-memory fixture: it would pass whether or not the commit is there, which is exactly the [[requirement-with-no-failing-case]] trap. If you want it under test it needs a file-backed engine, and that is a fixture this plan does not add.

So the *real* guard on the commit is a **code-review check**, restated in Step 24's commit message: `_write_pane_binding` ends in `await db.commit()`, and deleting that line must be caught by a reviewer, not by a green suite.

**The second test's three preconditions were measured, not assumed** — the same fixture was run as a real test in `tests/agent_teams/` before this plan was finalised, so the implementer inherits facts rather than a homework assignment:

| Precondition | Measured result |
| --- | --- |
| Two slots on one `repo_path` both classify as `spawn` | `slot=1 action='spawn'`, `slot=2 action='spawn'`, `can_launch: True`, each with `reasons=['No matching running session found']` |
| The `_bootstrap_prompt` spy fires once per slot with `(db, preset, slot)` | fired **2 times**; `slot_arg.display_name` was `'Agent one'` then `'Agent two'` |
| The spy's observation point precedes that slot's own spawn | `_bootstrap_prompt` is awaited at `:608`, `spawn_session` at `:616` — so on slot 2 the spy runs **after** slot 1's writer commit and **before** slot 2's spawn |

That third row is what makes `observed[0] == []` and `observed[1] == [(4241,)]` the right assertions rather than an off-by-one. If a future refactor moves the bootstrap call below the spawn, this test starts asserting the wrong iteration's state — so if it fails, re-read `:608`/`:616` before touching the expected values.

The same run also confirmed the `:637` key bug from the other direction: `fake_spawn` returned `"pane_pid": 4241` and `4242`, and **both result items came back `pane_pid=None`**, because `_execute_plan_item` reads `spawned.get("pid")`. Step 23 fixes that; this is what the un-fixed code looks like.

- [ ] **Step 21: Write the failing test for the reuse path**

Read `_matching_session_payload` (`:994-1006`) first — the reuse path's pid is a **string**, because `discovery.py:80` types it `pid: str`.

```python
@pytest.mark.asyncio
async def test_launch_writes_a_pane_binding_on_the_reuse_path(db, tmp_path, monkeypatch):
    """The reuse pid arrives as a str from discovery; it must land as an int.

    And re-dispatching to the same pane must UPDATE the row, not insert a
    second one -- a duplicate insert raises IntegrityError on the UNIQUE
    (pane_pid, pane_proc_start) constraint and then poisons the session with
    PendingRollbackError, failing every remaining slot in the loop.
    """
    from sqlalchemy import text

    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Reuse team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Dev agent",
                    provider="codex-cli",
                    repo_path=str(repo),
                )
            ],
        ),
    )
    monkeypatch.setattr(
        "app.services.agent_team_service.discover_agent_sessions",
        lambda: [
            {
                "session_name": "repo-abcd",
                "tmux_target": "repo-abcd:0.0",
                "pid": "4242",            # a str, exactly as discovery returns it
                "provider": "codex-cli",
                "cwd": str(repo),
                "wakeable": True,
            }
        ],
    )
    monkeypatch.setattr(
        "app.services.agent_team_service.read_proc_stat", lambda pid: (1, "120913170")
    )

    plan = await agent_team_service.plan_launch(db, preset.id)
    assert plan.items[0].action == "reuse", plan.items[0].reasons

    await agent_team_service.launch(
        db, preset.id, AgentTeamLaunchRequest(confirm_plan_hash=plan.plan_hash)
    )
    rows = (
        await db.execute(
            text("SELECT id, pane_pid, typeof(pane_pid), slot_id FROM agent_pane_bindings")
        )
    ).all()
    assert len(rows) == 1
    first_id = rows[0][0]
    assert rows[0][1] == 4242
    assert rows[0][2] == "integer"

    # Dispatch to the same pane again: same row, no IntegrityError.
    plan2 = await agent_team_service.plan_launch(db, preset.id)
    await agent_team_service.launch(
        db, preset.id, AgentTeamLaunchRequest(confirm_plan_hash=plan2.plan_hash)
    )
    rows2 = (
        await db.execute(text("SELECT id, pane_pid FROM agent_pane_bindings"))
    ).all()
    assert rows2 == [(first_id, 4242)], "re-dispatch must update, not insert"
```

**The `plan_launch` stub shape is a precondition, and this one was measured.** The test only exercises the reuse path if `plan_launch` classifies the stubbed session as reusable, so the exact dict above was run as a real test in `tests/agent_teams/` first. Results:

- `action='reuse'`, `block=None`, `reasons=['A matching running session is already available']`.
- `_matching_session_payload` projected it to `{'source': 'bridge', 'provider': 'codex-cli', 'session_key': None, 'session_name': 'repo-abcd', 'tmux_target': 'repo-abcd:0.0', 'pane_id': None, 'cwd': <repo>, 'pid': '4242'}` — note `session_key=None`, because the stub has neither `session_key` nor `pane_id`. That is fine: nothing on the reuse binding path reads it.
- The launch returned `action=reuse status=reused pane_pid=4242 type=int` — **pydantic already coerced the string**, which is why Step 23's writer reads `result.pane_pid` off the validated model rather than calling `int(...)` on the raw dict.
- The **second** `plan_launch` also returned `action='reuse'` with the same reason, so the re-dispatch half of this test genuinely re-enters the reuse branch. Without that, the `rows2 == [(first_id, 4242)]` assertion would be vacuous.

The reuse classification only needs `provider` and `cwd`: `_discovered_session_matches_slot` (`:965-973`) compares `session["provider"]` to `slot.provider` and `derive_repo_identity(cwd)["repo_id"]` to `slot.repo_id`, and nothing else. `wakeable` and `session_name` are carried for realism, not for the match. Note also that `plan_launch` reads discovery through `self._discover_sessions()` (`:428`), which calls the module-level `discover_agent_sessions()` inside a bare `except Exception: return []` (`:1137-1141`) — so the `monkeypatch.setattr` target above is right, but a stub that *raises* would be silently swallowed into "no sessions found" rather than failing the test.

- [ ] **Step 22: Run to verify both fail**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_teams/test_agent_team_service.py -q -p no:warnings
```

Expected: **3 failed, 41 passed** — the three new tests fail because `agent_pane_bindings` is empty (`assert [] == [(4242, ...)]`) and because `read_proc_stat` is not an attribute of `agent_team_service` yet (`AttributeError` on the `monkeypatch.setattr`). The 41 is this file's measured count today; any other number means the file changed under you.

- [ ] **Step 23: Implement the writer**

In `backend/app/services/agent_team_service.py`, add the import beside the existing ones (`:1-51`):

```python
from app.utils.peer_process import read_proc_stat
```

Import the *name*, not the module — the tests above monkeypatch `app.services.agent_team_service.read_proc_stat`, which only works for a name bound in this module. `app.utils.peer_process` imports nothing from `app.services`, so there is no cycle. Verified separately: `github_workspace_service` has an equivalent `_read_proc_start` (`:79-81`), and reusing *that* would work too — but it is a private method on a service object, and importing one service into another for a `/proc` read is a dependency this file does not otherwise have.

Then add the writer as a method on the service:

```python
    async def _write_pane_binding(
        self,
        db: AsyncSession,
        *,
        pane_pid: int | None,
        slot: AgentTeamSlot,
        preset: AgentTeamPreset,
        tmux_target: str | None,
    ) -> None:
        """Record which slot owns a pane, so registration can derive it.

        Committed here, mid-loop, on the CALLER's session -- and both halves of
        that are deliberate:

        * Committed, because the agent's MCP shim registers over a different
          connection and cannot see an uncommitted row. Without a visible row
          it claims team context with no binding and gets 409 bind_pending on
          every mail tool for the life of the pane (spec 3.3a).
        * On the caller's session, because launch() already flushed the
          AgentTeamLaunch row before this loop, so this request's connection
          holds SQLite's write lock. A second session's INSERT here was
          measured failing after 1.5s with "database is locked".

        The commit therefore also persists the AgentTeamLaunch row in its
        interim status='running'. That is safe TODAY because nothing reads that
        status and every caller upstream of launch() has already committed its
        own mutations (send_message commits; workspace acquire commits). A
        future caller that holds an uncommitted mutation across launch() would
        have it committed here -- check before adding one.
        """
        if pane_pid is None:
            return
        stat = read_proc_stat(pane_pid)
        if stat is None:
            return
        _ppid, proc_start = stat

        existing = (
            await db.execute(
                select(AgentPaneBinding).where(
                    AgentPaneBinding.pane_pid == pane_pid,
                    AgentPaneBinding.pane_proc_start == proc_start,
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            # Select-then-update, never a bare insert: the reuse path re-binds
            # the same pane on every dispatch, and a duplicate insert raises
            # IntegrityError on UNIQUE(pane_pid, pane_proc_start) and then
            # poisons the session with PendingRollbackError, failing every
            # remaining slot in this loop.
            db.add(
                AgentPaneBinding(
                    pane_pid=pane_pid,
                    pane_proc_start=proc_start,
                    slot_id=slot.id,
                    preset_id=preset.id,
                    tmux_target=tmux_target,
                )
            )
        else:
            existing.slot_id = slot.id
            existing.preset_id = preset.id
            existing.tmux_target = tmux_target
        await db.commit()
```

Add `AgentPaneBinding` to the model import block, and `select` is already imported (`:147` uses it).

Now call it on both paths. **Read the pid off the result object, not off the payload** — `AgentTeamLaunchResultItem` types `pane_pid: Optional[int]`, and measured, pydantic coerces `"4242"` to `4242` and raises `ValidationError` on `"%1"`. That is where the reuse path's `str` becomes an `int`.

On the **reuse** path, after the `result = AgentTeamLaunchResultItem(...)` block and before `self._record_launch_item(...)` (`:575`):

```python
            await self._write_pane_binding(
                db,
                pane_pid=result.pane_pid,
                slot=slot,
                preset=preset,
                tmux_target=result.tmux_target,
            )
```

On the **spawn** path, the same call goes inside the `try`, immediately after its `result = AgentTeamLaunchResultItem(...)` block (which ends at `:640`) — **not** after the `except`, and **not** after `_record_launch_item` at `:652`, which both paths share. Putting it after the shared `_record_launch_item` would run it on the `except Exception` path too, where `result` has no `tmux_target` and no pid, and on the `skip`/`blocked`/`reuse` paths that return earlier. Inside the `try` it runs only where a pane was actually created:

```python
            await self._write_pane_binding(
                db,
                pane_pid=result.pane_pid,
                slot=slot,
                preset=preset,
                tmux_target=result.tmux_target,
            )
```

**`spawned.get("pid")` at `:637` is wrong and stays wrong until Step 19.** `spawn_session` never returned a `pid` key, so that line has always evaluated to `None`. Step 19 adds `pane_pid`, so change `:637` to read it:

```python
                pane_pid=spawned.get("pane_pid"),
```

Leaving `"pid"` there would make the whole spawn-path binding silently dead — the row would never be written, the tests in Step 20 would fail, and the failure would look like a missing commit rather than a wrong key. This is the single most likely way to get this task wrong.

- [ ] **Step 24: Run the tests and commit the writer**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_teams/test_agent_team_service.py tests/test_agent_bridge_spawn.py -q -p no:warnings && pytest tests/ -q -p no:warnings
```

Expected: **44 passed** in `test_agent_team_service.py` (41 + 3) and **15 passed** in `test_agent_bridge_spawn.py` (13 + 2). Full suite: **`668 passed, 1 failed`** — the 622 baseline plus Tasks 1-4's 46 new cases, and the one failure is the pre-existing smoke test. Report the actual numbers.

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1 && git add backend/app/services/agent_bridge/spawn.py backend/app/services/agent_team_service.py backend/tests/test_agent_bridge_spawn.py backend/tests/agent_teams/test_agent_team_service.py && git commit -m "feat(teams): write the pane binding the registration route reads

Spec 3.8 assigns this to agent_team_service on both launch paths, and without
it every Deck-launched pane claims team context with no binding row -- 409
bind_pending on every mail tool, for the life of the pane, since _guard
re-registers before each one. That is the revision-4 defect 3.3a exists to
prevent.

spawn_session now returns the pane pid from new-session -P -F '#{pane_pid}',
which is race-free where a post-hoc list-panes is not: for a command that exits
immediately the tmux server is already gone and list-panes returns nothing. The
cost is three re-authored argv assertions, which now key on argv[-1] for the
shell command rather than on a fixed index.

The row is committed mid-loop on the caller's own session. Not on a second
connection: launch() flushes its AgentTeamLaunch row before the slot loop, so
the request already holds SQLite's write lock and a second session's INSERT was
measured failing after 1.5s with 'database is locked'. Committed rather than
flushed because the shim registers over a different connection.

Select-then-update, not insert: the reuse path re-binds the same pane on every
dispatch, and a duplicate hits UNIQUE(pane_pid, pane_proc_start), raising
IntegrityError and then poisoning the session for every remaining slot.

CODE REVIEW CHECK, not covered by a test: _write_pane_binding must end in
await db.commit(). The agent_teams db fixture is a single in-memory session, so
no test in this suite can distinguish a commit from a flush -- the
cross-connection visibility was verified by direct measurement on a file-backed
WAL database instead.

Spec: 2026-08-05-distinct-approver-identity-design.md sections 3.3, 3.3a, 3.8"
```

---

### Task 5: The enforcement dependency and the four write routes

**Four, not five.** §3.5's endpoint table lists five token-carrying routes; the fifth is `POST /agent-teams/dispatch-status`, which lives in `agent_teams.py` and has its own authorization resolver. That one is **Task 7**. This task's Files block is the authority for which four: `send_message`, `mark_read`, `ack_message`, `agent_inbox`.

**Files:**
- Create: `backend/app/api/v1/deps.py`
- Modify: `backend/app/api/v1/agent_mail.py` (`send_message` `:65-70`, `mark_read` `:90-97`, `ack_message` `:100-107`, `agent_inbox` `:133-148`)
- Test: `backend/tests/agent_mail/test_capability_tokens.py`
- Modify: `backend/tests/agent_mail/test_api.py` (four tests)

**Interfaces:**
- Consumes: `agent_mail_service.hash_capability_token` (Task 3); `settings.mail_capability_tokens_required` (Task 1).
- Produces, in `app.api.v1.deps`:
  - `mail_session(x_deck_session_token, db) -> MailAgentSession | None` — the resolved session, or `None` in grace mode with no token. Raises `401 session_token_invalid` for a token that does not match. **Task 10 widens this return to `MailAgentSession | OperatorPrincipal | None`**; write the two-member version here and let Task 10 add the third, since nothing in PR0 before Task 10 can produce an `OperatorPrincipal`.
  - `require_mail_session(...) -> MailAgentSession` — the same, but `401 session_token_required` rather than `None`. The return stays `MailAgentSession` through Task 10: its whole job there is to *refuse* the widened union, so the narrowing is the point and the annotation does not move.
  - `require_session_slot(session) -> int` — the session's `team_slot_id`, or `403 session_not_slot_bound`. **Task 10 adds an `isinstance` guard** to this function, because `/dispatch-status` reaches it with whatever `mail_session` returned and Task 10 widens that union.
  - `derive_member_id(session, claimed: int | None, *, detail: str = "sender_not_token_holder") -> Optional[int]` — derive, do not compare. The keyword-only `detail` is what the refusal says when `claimed` disagrees with the token holder: the three `sender_member_id` routes take the default, and the inbox route passes `detail="member_not_token_holder"` (Step 6), because on that route the caller is naming *whose inbox to read*, not whose name to sign. Two codes rather than one, because an operator debugging a `403` needs to know which of the two claims was rejected.

    The return is `Optional[int]`, not `int`, and it is `Optional` from Task 5 onward — **not** something Task 10 widens. Task 10 adds a third caller shape (`OperatorPrincipal`) that returns `None` on the anonymous-compose path, but the annotation already admits it. Write `Optional[int]` here in Task 5 and Task 10 changes only the `session` parameter's type. A Task 5 that writes `-> int` produces a real type error the moment Task 10's branch lands, and `mypy` is not in this repo's CI to catch it.

**`app/api/v1/` has no `deps.py`** — this is a new file. Put it there rather than in `agent_mail.py` because Task 7 imports `require_session_slot` from `agent_teams.py`, and a cross-import between two route modules is a cycle waiting to happen.

**The grace-mode fallback is the whole of PR0's mail-write change.** With `mail_capability_tokens_required = False`:

| Request | Behaviour |
| --- | --- |
| No token | Falls back to today's caller-supplied `member_id`; log `capability_token_missing` once per session key |
| Token that matches a session | Member **derived** from the token. A caller-supplied `member_id` that agrees is accepted; one that disagrees is `403` |
| Token that does not match any session | `401 session_token_invalid` — a wrong token is never treated as no token |

That last row is the one to get right. "Invalid falls back to unauthenticated" would make the enforcement flag meaningless: an attacker sends garbage and gets the legacy path.

**Correction (2026-08-09, source verification) — §3.5 says `member_id` "is removed from the agent route, not merely validated." PR0 cannot remove it.** Grace mode's entire purpose is that a pre-upgrade shim, whose loaded code has no idea the header exists, keeps working across the deploy. That shim sends `member_id` as a query parameter and no token (`agent_mail_server.py:191` and `:264`). Removing the parameter in PR0 breaks exactly the callers grace mode exists to protect. So in PR0 the parameter stays and is *derived-over* when a token is present; **removing it belongs in PR1**, after the operator has restarted the panes and flipped the flag. Under enforcement the parameter is ignored entirely, so it is inert rather than a trap — but it is still a parameter that outlived its purpose, and PR1's plan must delete it.

**Derive, do not compare.** The server sets the member from the token. A caller-supplied value that *agrees* is accepted (which keeps the shim's current payload valid); one that *disagrees* is `403`, never a silent overwrite. A silent overwrite would report a misconfigured shim as success.

- [ ] **Step 1: Write the failing tests for the dependency**

Append to `backend/tests/agent_mail/test_capability_tokens.py`:

```python
@pytest.mark.asyncio
async def test_write_with_a_valid_token_derives_the_sender(client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    register = await client.post(
        "/api/v1/agent-mail/agent/register", json=_body(tmp_path, session_key="mcp:send")
    )
    token = register.json()["capability_token"]
    sender_id = register.json()["member"]["id"]
    recipient = await _member(db, "other-repo", "other")

    response = await client.post(
        "/api/v1/agent-mail/messages",
        json={
            "kind": "message",
            "recipient_member_id": recipient.id,
            "subject": "hello",
            "body_markdown": "hi",
        },
        headers={"X-Deck-Session-Token": token},
    )
    assert response.status_code == 200
    assert response.json()["sender_member_id"] == sender_id


@pytest.mark.asyncio
async def test_write_with_no_token_is_401_under_enforcement(client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    recipient = await _member(db, "other-repo", "other")
    response = await client.post(
        "/api/v1/agent-mail/messages",
        json={
            "kind": "message",
            "sender_member_id": recipient.id,
            "recipient_member_id": recipient.id,
            "subject": "s",
            "body_markdown": "b",
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "session_token_required"


@pytest.mark.asyncio
async def test_an_invalid_token_never_falls_back(client, db, tmp_path, monkeypatch):
    """Grace mode must not turn a wrong token into an unauthenticated write."""
    assert settings.mail_capability_tokens_required is False
    recipient = await _member(db, "other-repo", "other")
    response = await client.post(
        "/api/v1/agent-mail/messages",
        json={
            "kind": "message",
            "sender_member_id": recipient.id,
            "recipient_member_id": recipient.id,
            "subject": "s",
            "body_markdown": "b",
        },
        headers={"X-Deck-Session-Token": "not-a-real-token"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "session_token_invalid"


@pytest.mark.asyncio
async def test_grace_mode_accepts_a_tokenless_write(client, db, tmp_path):
    """Test 15: the whole point of PR0's mail-write path staying compatible."""
    assert settings.mail_capability_tokens_required is False
    sender = await _member(db, "sender-repo", "sender")
    recipient = await _member(db, "other-repo", "other")
    response = await client.post(
        "/api/v1/agent-mail/messages",
        json={
            "kind": "message",
            "sender_member_id": sender.id,
            "recipient_member_id": recipient.id,
            "subject": "s",
            "body_markdown": "b",
        },
    )
    assert response.status_code == 200
    assert response.json()["sender_member_id"] == sender.id


@pytest.mark.asyncio
async def test_a_disagreeing_sender_is_403(client, db, tmp_path, monkeypatch):
    """Test 5: the forgery. The token mismatch must refuse before send_message
    gets a chance to reject the payload for its own reasons."""
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    register = await client.post(
        "/api/v1/agent-mail/agent/register", json=_body(tmp_path, session_key="mcp:forge")
    )
    token = register.json()["capability_token"]
    victim = await _member(db, "victim-repo", "victim")
    recipient = await _member(db, "other-repo", "other")

    response = await client.post(
        "/api/v1/agent-mail/messages",
        json={
            "kind": "message",
            "sender_member_id": victim.id,
            "recipient_member_id": recipient.id,
            "subject": "s",
            "body_markdown": "b",
        },
        headers={"X-Deck-Session-Token": token},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "sender_not_token_holder"


@pytest.mark.asyncio
async def test_inbox_without_a_token_is_401(client, db, tmp_path, monkeypatch):
    """Test 17. The inbox is in this task because it WRITES (see Step 6)."""
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    member = await _member(db, "inbox-repo", "inbox")
    response = await client.get(f"/api/v1/agent-mail/agent/inbox?member_id={member.id}")
    assert response.status_code == 401
    assert response.json()["detail"] == "session_token_required"


@pytest.mark.asyncio
async def test_the_forged_liveness_attack_writes_nothing(client, db, tmp_path, monkeypatch):
    """Test 18. The refusal must happen BEFORE the writes, not after.

    Asserting the 401 alone would pass a route that heartbeats first and
    refuses second -- the caller would still have forged the leader's liveness
    and silenced the escalation, and the test would be green. So this asserts
    on the four rows, and the seeded values are chosen so that every one of
    them MOVES if the refusal comes too late.
    """
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    register = await client.post(
        "/api/v1/agent-mail/agent/register",
        json=_body(tmp_path, session_key="mcp:victim"),
    )
    leader_id = register.json()["member"]["id"]

    # Age the session past the heartbeat TTL and mark it offline, so a
    # heartbeat would be visible as a change rather than a no-op.
    stale = datetime.utcnow() - timedelta(days=30)
    session_row = (
        await db.execute(
            select(MailAgentSession).where(MailAgentSession.member_id == leader_id)
        )
    ).scalar_one()
    session_row.last_seen_at = stale
    session_row.mailbox_status = "offline"

    # An unread brief addressed to the leader: receipt.read_at is what
    # _brief_delivered reads, so clearing it is what silences an escalation.
    sender = await _member(db, "sender-repo", "sender")
    message = MailMessage(
        kind="message",
        sender_member_id=sender.id,
        recipient_member_id=leader_id,
        subject="dispatch brief",
        body_markdown="do the thing",
    )
    db.add(message)
    await db.flush()
    receipt = MailReceipt(message_id=message.id, member_id=leader_id)
    db.add(receipt)
    leader = await db.get(MailTeamMember, leader_id)
    leader.last_inbox_checked_at = None
    await db.commit()

    response = await client.get(
        f"/api/v1/agent-mail/agent/inbox?member_id={leader_id}&mark_read=true"
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "session_token_required"

    # Now the part that matters: nothing moved.
    message_id = message.id  # read BEFORE expire_all, or it lazy-loads
    db.expire_all()
    session_row = (
        await db.execute(
            select(MailAgentSession).where(MailAgentSession.member_id == leader_id)
        )
    ).scalar_one()
    assert session_row.last_seen_at == stale, "liveness was forged before the refusal"
    assert session_row.mailbox_status == "offline"
    receipt = (
        await db.execute(select(MailReceipt).where(MailReceipt.message_id == message_id))
    ).scalar_one()
    assert receipt.read_at is None, "the brief was marked read before the refusal"
    leader = await db.get(MailTeamMember, leader_id)
    assert leader.last_inbox_checked_at is None


@pytest.mark.asyncio
async def test_inbox_with_a_token_ignores_a_disagreeing_member_id(
    client, db, tmp_path, monkeypatch
):
    """Test 19. Assert on the member returned, not on the status code.

    A route that authenticates and then still honours the query parameter
    returns 200 either way. The status code cannot distinguish the two, so it
    is not the assertion.
    """
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    register = await client.post(
        "/api/v1/agent-mail/agent/register",
        json=_body(tmp_path, session_key="mcp:holder"),
    )
    token = register.json()["capability_token"]
    holder_id = register.json()["member"]["id"]
    victim = await _member(db, "victim-repo", "victim")

    # No member_id at all: the token alone must resolve it.
    response = await client.get(
        "/api/v1/agent-mail/agent/inbox",
        headers={"X-Deck-Session-Token": token},
    )
    assert response.status_code == 200
    assert response.json()["member_id"] == holder_id

    # A member_id that AGREES is accepted (this keeps the pre-upgrade shim's
    # payload valid once it starts sending the token).
    response = await client.get(
        f"/api/v1/agent-mail/agent/inbox?member_id={holder_id}",
        headers={"X-Deck-Session-Token": token},
    )
    assert response.status_code == 200
    assert response.json()["member_id"] == holder_id

    # One that DISAGREES is refused, never silently derived over.
    response = await client.get(
        f"/api/v1/agent-mail/agent/inbox?member_id={victim.id}",
        headers={"X-Deck-Session-Token": token},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "member_not_token_holder"
```

Copy `_member` from `tests/agent_mail/test_api.py:25-35` — note it takes **`(db, repo_id, name)`**, three arguments, because `identity_key` and `repo_id` are distinct from the display name. Test 18 needs these imports at the top of the file: `from datetime import datetime, timedelta`, `from sqlalchemy import select`, and `from app.models.database import MailAgentSession, MailMessage, MailReceipt, MailTeamMember`.

**The receipt class is `MailReceipt`, not `MailMessageReceipt`.** Verified against `app/models/database.py:442` — `__tablename__ = "mail_receipts"`, with `message_id`, `member_id`, `read_at`, `acked_at`, `created_at`, and `UniqueConstraint("message_id", "member_id")`. `member.last_inbox_checked_at` is at `:364` and `session.mailbox_status`/`last_seen_at` are on `MailAgentSession` (`:369`+). Every column test 18 touches was checked against source; the plausible-sounding `MailMessageReceipt` does not exist and would fail at import.

**Test 5's ordering matters:** `send_message` already raises `ValueError → 400` for a payload carrying both sender fields, and for an `answer` whose sender is not the root's recipient. Use `kind="message"` with only `sender_member_id` set, so the **403 from the token check fires first**. If you see a 400, the dependency is running after the service instead of before it.

**Test 18's seeded values are load-bearing, and each was measured to move.** This exact fixture was run as a real test against the current code — no dependency in place, so the call returns `200` and every write lands. All four fields moved:

| Field | Seeded | Measured after the unauthenticated call | Written by |
| --- | --- | --- | --- |
| `session.last_seen_at` | `2026-07-11 08:19:56` (30 days stale) | `2026-08-10 08:19:56` | `heartbeat_member_mcp_session` (`:346`), reached from `get_inbox:1082` |
| `session.mailbox_status` | `'offline'` | `'connected'` | same, `:347` — forced, not conditional |
| `receipt.read_at` | `None` | `2026-08-10 08:19:56` | `get_inbox:1101` |
| `member.last_inbox_checked_at` | `None` | `2026-08-10 08:19:56` | `get_inbox:1098` |

That is what makes this a real test rather than a restatement of the 401. Seed it any other way — a fresh session, an already-read receipt — and the assertions hold whether or not the refusal precedes the writes, which is the [[requirement-with-no-failing-case]] trap.

Two mechanical details the probe run exposed, both of which will bite:

1. **`source` must be `"mcp"`.** `heartbeat_member_mcp_session` filters on `MailAgentSession.source == "mcp"` (`:338`) and returns silently for anything else. `_body`'s `"source": "mcp"` is why the first two rows move; a `"bridge"` registration would leave them untouched and make those two assertions vacuous.
2. **Read `message.id` into a local *before* `db.expire_all()`.** Doing it after raises `sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called` — the expired attribute triggers a lazy refresh outside the async greenlet, and the test fails with a SQLAlchemy internals traceback that looks nothing like the bug it is. The `expire_all()` itself is not optional: the `client` fixture shares the request's session, so without it the re-reads return the identity map rather than the rows.

- [ ] **Step 2: Run to verify they fail**

Expected: the enforcement tests return `200`, because nothing checks a token yet.

- [ ] **Step 3: Write `deps.py`**

Create `backend/app/api/v1/deps.py`:

```python
"""Shared route dependencies for capability-token enforcement."""
import hmac
import logging
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.database import MailAgentSession
from app.services.agent_mail_service import agent_mail_service

logger = logging.getLogger(__name__)

# Members we have already logged a missing token for, so grace mode does not
# emit one line per request for the lifetime of a pre-upgrade shim. The key is
# the CLAIMED member: a tokenless caller has no session for us to key on, which
# is the whole reason it needs logging.
_missing_token_logged: set[int] = set()


async def mail_session(
    x_deck_session_token: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> Optional[MailAgentSession]:
    """Resolve the calling session from its capability token.

    Returns None only in grace mode with NO token at all. A token that is
    present but matches nothing is always a 401: treating an invalid token as
    an absent one would make the enforcement flag meaningless, because any
    caller could send garbage and get the legacy unauthenticated path.
    """
    if not x_deck_session_token:
        if settings.mail_capability_tokens_required:
            raise HTTPException(status_code=401, detail="session_token_required")
        return None

    hashed = agent_mail_service.hash_capability_token(x_deck_session_token)
    result = await db.execute(
        select(MailAgentSession).where(MailAgentSession.capability_token_hash.is_not(None))
    )
    for session in result.scalars().all():
        if hmac.compare_digest(session.capability_token_hash, hashed):
            return session
    raise HTTPException(status_code=401, detail="session_token_invalid")


async def require_mail_session(
    session: Optional[MailAgentSession] = Depends(mail_session),
) -> MailAgentSession:
    """Like mail_session, but never None."""
    if session is None:
        raise HTTPException(status_code=401, detail="session_token_required")
    return session


def require_session_slot(session: MailAgentSession) -> int:
    """The slot this session is bound to, or 403.

    An unbound session can send mail as a repo member. It can never speak for a
    slot, which is what every dispatch-status report claims to do.
    """
    if session.team_slot_id is None:
        raise HTTPException(status_code=403, detail="session_not_slot_bound")
    return session.team_slot_id


def derive_member_id(
    session: Optional[MailAgentSession],
    claimed: Optional[int],
    *,
    detail: str = "sender_not_token_holder",
) -> Optional[int]:
    """Derive the acting member from the token; refuse a disagreeing claim.

    A claim that AGREES is accepted, which keeps the existing shim payload
    valid. A claim that DISAGREES is 403, never a silent overwrite: overwriting
    would report a misconfigured shim as success.
    """
    if session is None:
        if claimed is None:
            raise HTTPException(status_code=400, detail="member_id_required")
        if claimed not in _missing_token_logged:
            _missing_token_logged.add(claimed)
            logger.warning(
                "capability_token_missing: unauthenticated write as member %s "
                "accepted because mail_capability_tokens_required is False",
                claimed,
            )
        return claimed
    if claimed is not None and claimed != session.member_id:
        raise HTTPException(status_code=403, detail=detail)
    return session.member_id
```

The log line lives inside `derive_member_id` rather than in `mail_session` because that is the only place a tokenless caller's identity is known — `mail_session` returns `None` and has nothing to name. It fires once per claimed member, so a pre-upgrade shim polling its inbox every 60 s produces one line, not one per poll. Grace mode is meant to be visible in the log without drowning it.

`hmac.compare_digest` on two hex digests of equal length is the right comparison here. Note it is reached **only** after `if not x_deck_session_token`, which is what keeps `compare_digest("", "") is True` from mattering — the same ordering trap Task 8 handles for the operator token.

- [ ] **Step 4: Apply the dependency to `send_message`**

In `agent_mail.py`, add `from app.api.v1.deps import derive_member_id, mail_session, require_mail_session` and replace `send_message` (`:65-70`):

```python
@router.post("/messages", response_model=MailMessageResponse)
async def send_message(
    request: MailMessageCreate,
    session: Optional[MailAgentSession] = Depends(mail_session),
    db: AsyncSession = Depends(get_db),
):
    if session is not None:
        request = request.model_copy(
            update={"sender_member_id": derive_member_id(session, request.sender_member_id)}
        )
    try:
        return await agent_mail_service.send_message(db, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

`MailAgentSession` needs importing into `agent_mail.py` for the annotation. Leave the `except ValueError` mapping exactly as it is — `send_message`'s own validation order (invalid kind, both sender fields, `answer` without a root, and so on) is unchanged and still correct.

- [ ] **Step 5: Apply it to `mark_read` and `ack_message`**

```python
@router.post("/messages/{message_id}/read")
async def mark_read(
    message_id: int,
    body: dict[str, Any] = Body(default_factory=dict),
    session: Optional[MailAgentSession] = Depends(mail_session),
    db: AsyncSession = Depends(get_db),
):
    member_id = derive_member_id(
        session, body.get("member_id"), detail="member_not_token_holder"
    )
    await agent_mail_service.mark_read(db, message_id, int(member_id))
    return {"ok": True}


@router.post("/messages/{message_id}/ack")
async def ack_message(
    message_id: int,
    body: dict[str, Any] = Body(default_factory=dict),
    session: Optional[MailAgentSession] = Depends(mail_session),
    db: AsyncSession = Depends(get_db),
):
    member_id = derive_member_id(
        session, body.get("member_id"), detail="member_not_token_holder"
    )
    await agent_mail_service.ack_message(db, message_id, int(member_id))
    return {"ok": True}
```

Two changes to notice. `Body(...)` becomes `Body(default_factory=dict)`, because a tokened caller no longer needs to send a body at all. And `int(body["member_id"])` becomes `body.get("member_id")` passed through `derive_member_id`, which raises `400 member_id_required` instead of the bare `KeyError` today's code would raise.

**Why these two routes matter as much as `send_message`:** `ack_message` writes `receipt.read_at` (`agent_mail_service.py:1294`), and `_brief_delivered` (`github_dispatch_service.py:806-824`) reads exactly that field on the `(brief_message_id, owner_member_id)` receipt to decide whether the `brief_unread` escalation fires. An unauthenticated ack on an arbitrary member therefore silences a dispatch escalation. That is not a hypothetical — it is why test 18 exists.

- [ ] **Step 6: Apply it to `agent_inbox`**

```python
@router.get("/agent/inbox", response_model=MailInboxResponse)
async def agent_inbox(
    member_id: Optional[int] = None,
    unread_only: bool = False,
    mark_read: bool = False,
    limit: int = 50,
    session: Optional[MailAgentSession] = Depends(mail_session),
    db: AsyncSession = Depends(get_db),
):
    # member_id survives PR0 only for grace mode: a pre-upgrade shim sends it
    # and no token. Under enforcement it is ignored -- derive_member_id refuses
    # a disagreeing value and returns the token's member otherwise. PR1 deletes
    # the parameter once the panes have restarted.
    resolved = derive_member_id(session, member_id, detail="member_not_token_holder")
    return await agent_mail_service.get_inbox(
        db,
        int(resolved),
        unread_only=unread_only,
        mark_read=mark_read,
        limit=limit,
        refresh_mcp_session=True,
    )
```

`member_id` changes from a required to an optional query parameter. That is the only signature change, and it is backward-compatible: every existing caller still passes it.

**Why the inbox is a write endpoint.** `refresh_mcp_session=True` is hardcoded at the route, and it calls `heartbeat_member_mcp_session`, which writes `last_seen_at` and forces `mailbox_status = "connected"`. With `mark_read=true` it also writes `receipt.read_at` and `member.last_inbox_checked_at`. `_effective_status` reads the first pair, `_brief_delivered` reads the second. So an unauthenticated `GET` forges a dead agent's liveness *and* silences an escalation.

- [ ] **Step 7: Run the new tests**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_mail/test_capability_tokens.py -q -p no:warnings
```

Expected: `33 passed` in `test_capability_tokens.py` (25 after Task 4 + this task's 8).

- [ ] **Step 8: Run the full suite and expect four named failures**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_teams/ tests/agent_mail/ -q -p no:warnings
```

Grace mode is on by default, so **most** existing tests keep passing untouched. Any that do fail should be from this list, which was measured: `test_api.py`'s `test_inbox_read_ack_endpoints`, `test_agent_inbox_refreshes_stale_mcp_session`, `test_send_and_thread_roundtrip`, `test_invalid_kind_is_400`. **If a test outside that list fails, stop and report** — it means the dependency changed behaviour in grace mode, which it must not.

- [ ] **Step 9: Fix only the tests that actually broke**

For each failure, the fix is one of exactly two things, and nothing else:

- The test relied on `Body(...)` rejecting an empty body ⇒ it now gets `400 member_id_required` instead of `422`. Assert the new code.
- The test relied on `member_id` being a required query parameter ⇒ same, `400` not `422`.

Do **not** add tokens to these tests. They are the grace-mode regression suite: their value is precisely that they pass unauthenticated. If a test needs a token to pass, the grace-mode fallback is broken.

- [ ] **Step 10: Run the full suite again**

Expected: `505 passed` (497 after Task 4 + this task's 8), no failures. Report the actual number.

- [ ] **Step 11: Commit**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1 && git add backend/app/api/v1/deps.py backend/app/api/v1/agent_mail.py backend/tests/agent_mail/test_capability_tokens.py backend/tests/agent_mail/test_api.py && git commit -m "feat(mail): derive the acting member from the capability token

Four routes (messages, read, ack, agent/inbox) now resolve their member from
the X-Deck-Session-Token header. A claim that agrees is accepted; one that
disagrees is 403, never a silent overwrite.

An absent token falls back to the legacy path only while
mail_capability_tokens_required is False. An INVALID token is always 401 --
falling back there would let any caller reach the legacy path with garbage.

agent/inbox is included because it is a write endpoint: refresh_mcp_session is
hardcoded at the route, so an unauthenticated GET forges last_seen_at and, with
mark_read, receipt.read_at -- the two fields _effective_status and
_brief_delivered read to make safety decisions.

Spec: 2026-08-05-distinct-approver-identity-design.md section 3.5"
```

---

### Task 6: The shim captures the token and sends it on every call

**Files:**
- Modify: `backend/mcp_shim/agent_mail_server.py` (`_state` `:24-29`, `_deck_request` `:79-98`, `_ensure_registered` `:139-161`)
- Test: `backend/tests/agent_mail/test_mcp_shim.py`

**Interfaces:**
- Consumes: `capability_token` on the register response (Task 3); the `X-Deck-Session-Token` header (Task 5).
- Produces: `_state["capability_token"]`, sent as `X-Deck-Session-Token` on every Deck request the shim makes.

**Spec sections:** §3.4 (the token is stored once and never replaced) and §3.8's shim bullet (`:969`), which names the file and the two edit sites. **Not §3.6a** — that section is the *operator* credential, which the shim never holds; Task 8 implements it.

**The header goes in `_deck_request`, the single chokepoint.** Every shim call funnels through it — `_request` (`:101`), `_team_request` (`:105`), `_bridge_request` (`:109`), `_dispatch_request` (`:113`) are all one-line wrappers, and `_bridge_request_with_token` (`:117`) layers a second header on top of `_bridge_request`. Putting the token anywhere else means auditing five call paths instead of one and getting it wrong on the sixth someone adds.

**Merge, never replace, the caller's headers.** `_bridge_request_with_token` already does `headers = dict(kwargs.pop("headers", {}) or {})` and sets `X-Claude-Deck-Terminal-Token`. If `_deck_request` assigns `kwargs["headers"] = {...}` it destroys that one. Copy the same pop-and-merge idiom.

**Capture on first registration only.** `ensure_capability_token` returns the plaintext exactly once, so every later `_ensure_registered` — and `_guard` calls it before every tool — sees `capability_token: None`. Overwriting `_state["capability_token"]` unconditionally would null it on the second call and 401 every subsequent request.

- [ ] **Step 1: Write the failing test**

`tests/agent_mail/test_mcp_shim.py:13-47` already asserts an exact five-key payload for registration. Read it, then append:

```python
def test_registration_captures_the_capability_token(monkeypatch):
    """The plaintext arrives once; the shim must keep it."""
    from mcp_shim import agent_mail_server as shim

    responses = [
        {"ok": True, "data": {"member": {"id": 4}, "session": {"id": 9},
                              "capability_token": "tok-abc"}},
        {"ok": True, "data": {"member": {"id": 4}, "session": {"id": 9},
                              "capability_token": None}},
    ]
    monkeypatch.setattr(shim, "_request", lambda *a, **k: responses.pop(0))
    shim._state["capability_token"] = None
    shim._state["member_id"] = None

    shim._ensure_registered()
    assert shim._state["capability_token"] == "tok-abc"

    # The re-registration _guard performs before every tool returns None.
    shim._ensure_registered()
    assert shim._state["capability_token"] == "tok-abc", "must not be nulled"


def test_deck_request_sends_the_session_token(monkeypatch):
    from mcp_shim import agent_mail_server as shim

    captured = {}

    def _fake_request(method, url, **kwargs):
        captured["headers"] = kwargs.get("headers")

        class _Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {}

        return _Response()

    monkeypatch.setattr(shim.httpx, "request", _fake_request)
    shim._state["capability_token"] = "tok-abc"
    shim._state["offline_until"] = 0.0

    shim._deck_request("GET", "agent-mail", "/team")
    assert captured["headers"]["X-Deck-Session-Token"] == "tok-abc"


def test_deck_request_preserves_a_callers_headers(monkeypatch):
    """_bridge_request_with_token sets its own header; do not clobber it."""
    from mcp_shim import agent_mail_server as shim

    captured = {}

    def _fake_request(method, url, **kwargs):
        captured["headers"] = kwargs.get("headers")

        class _Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {}

        return _Response()

    monkeypatch.setattr(shim.httpx, "request", _fake_request)
    shim._state["capability_token"] = "tok-abc"
    shim._state["offline_until"] = 0.0

    shim._deck_request(
        "GET", "agent-bridge", "/x", headers={"X-Claude-Deck-Terminal-Token": "term"}
    )
    assert captured["headers"]["X-Claude-Deck-Terminal-Token"] == "term"
    assert captured["headers"]["X-Deck-Session-Token"] == "tok-abc"


def test_deck_request_sends_no_header_without_a_token(monkeypatch):
    """A shim that never got a token must not send an empty one -- an empty
    header is a token that matches nothing, which is 401, not grace mode."""
    from mcp_shim import agent_mail_server as shim

    captured = {}

    def _fake_request(method, url, **kwargs):
        captured["headers"] = kwargs.get("headers")

        class _Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {}

        return _Response()

    monkeypatch.setattr(shim.httpx, "request", _fake_request)
    shim._state["capability_token"] = None
    shim._state["offline_until"] = 0.0

    shim._deck_request("GET", "agent-mail", "/team")
    assert "X-Deck-Session-Token" not in (captured["headers"] or {})
```

The last test is the one that pairs with Task 5's `test_an_invalid_token_never_falls_back`. An empty-string header is **not** the same as no header: `deps.mail_session` treats `""` as absent via `if not x_deck_session_token`, so it would work — but relying on that couples the shim to a truthiness check three modules away. Send no header at all.

These tests mutate module-level `_state`, so they leak between tests. Add a fixture that saves and restores it, or set every key each test reads. Check whether `test_mcp_shim.py` already has such a fixture before adding one.

- [ ] **Step 2: Run to verify it fails**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_mail/test_mcp_shim.py -q -p no:warnings
```

Expected: `KeyError: 'capability_token'` on `_state`.

- [ ] **Step 3: Add the state slot**

In `mcp_shim/agent_mail_server.py`, add to the `_state` dict (`:24-29`):

```python
    "capability_token": None,
```

- [ ] **Step 4: Capture the token in `_ensure_registered`**

Inside `_ensure_registered`, after the `_request("POST", ...)` result is confirmed `ok` and alongside where `_state["member_id"]` is set, add:

```python
        minted = result["data"].get("capability_token")
        if minted:
            # Returned exactly once, on the registration that mints it. Every
            # later call -- and _guard re-registers before every tool -- returns
            # None, so an unconditional assignment would null this and 401 the
            # rest of the session.
            _state["capability_token"] = minted
```

Read the existing block first: the two `_state` writes are inside `_ensure_registered` (`:139-161`) and the surrounding code already guards on `result["ok"]`. Put this next to them, under the same guard, and do not add a second `ok` check.

- [ ] **Step 5: Send the header in `_deck_request`**

In `_deck_request` (`:79-98`), between the `url = ...` line (`:84`) and the `try:` (`:85`):

```python
    session_token = _state.get("capability_token")
    if session_token:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["X-Deck-Session-Token"] = session_token
        kwargs["headers"] = headers
```

The pop-and-merge is the same idiom `_bridge_request_with_token` uses at `:132`. It matters: `_bridge_request_with_token` sets `X-Claude-Deck-Terminal-Token` and then calls through here, so a plain assignment would drop the terminal token and break every bridge call.

- [ ] **Step 6: Run the shim tests**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_mail/test_mcp_shim.py -q -p no:warnings
```

Expected: `25 passed` — the file's measured 21 today plus this task's 4. **`test_mcp_shim.py:13-47`'s exact five-key payload assertion is expected to still pass** — the registration *payload* is unchanged; only the *response* handling and the *headers* changed. If that test fails, you modified the payload; revert that part.

- [ ] **Step 7: Run the full suite**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_teams/ tests/agent_mail/ -q -p no:warnings
```

Expected: `509 passed` (505 after Task 5 + this task's 4). Report the actual number.

- [ ] **Step 8: Commit**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1 && git add backend/mcp_shim/agent_mail_server.py backend/tests/agent_mail/test_mcp_shim.py && git commit -m "feat(shim): capture the capability token and send it on every call

The header is added in _deck_request, the single chokepoint all five request
wrappers funnel through, using the same pop-and-merge idiom as
_bridge_request_with_token so a caller's own headers survive.

The token is captured only when the response actually carries one: it is minted
once, so an unconditional assignment would null it on the re-registration
_guard performs before every tool call.

Spec: 2026-08-05-distinct-approver-identity-design.md sections 3.4, 3.8"
```

---

### Task 7: `/dispatch-status` — an authorization rule for every branch

**Files:**
- Modify: `backend/app/api/v1/agent_teams.py:1-58` (imports), `:286-385` (`report_dispatch_status`)
- Test: `backend/tests/agent_mail/test_dispatch_status_tool.py`

**Interfaces:**
- Consumes: `app.api.v1.deps.mail_session` and `require_session_slot` (Task 5); `github_dispatch_service._leader_slot` (existing, `:533-539`).
- Produces, in `app.api.v1.agent_teams`:
  - `_DISPATCH_STATUS_RULES: dict[str, _StatusRule]` — one entry per accepted status. The module-level table test 7c enumerates.
  - `_StatusRule` — a `NamedTuple` with `role: str` (`"owner"` or `"target"`), `refusal: str`, and `lease_token_required: bool`.
  - `async def _authorize_dispatch_report(db, item, report, session) -> None` — raises, or returns having filled `report.reporting_slot_id` from the derivation.

**The gap, measured.** Of the nine branches the route accepts, exactly **one** compares the reporter to the item — `workspace_released` at `:334`. Every other branch reads `report.work_item_id` and acts. Task 5's token narrows the caller population from "any process with curl" to "any registered agent," and on this route that narrowing buys almost nothing: the population that matters is the other slots on the same team, and they are all registered. Today a Specialist can mark another slot's item `blocked`, accept a handoff aimed elsewhere, or plant a `pr_number` on an item it has never touched.

**The rules table, from §3.5a's matrix.** Roles: **owner** = `item.owner_slot_id`; **target** = `item.handoff_target_slot_id`.

| Status | Who may report it | Lease token | Refusal |
| --- | --- | --- | --- |
| `triaging` | owner | not required | `403 not_item_owner` |
| `in_progress` | owner | not required | `403 not_item_owner` |
| `blocked` | owner | not required | `403 not_item_owner` |
| `ack_received` | owner | not required | `403 not_item_owner` |
| `handoff_initiated` | owner | not required | `403 not_item_owner` |
| `handoff_accepted` | **target** | not required | `403 not_handoff_target` — *in addition to* `accept_handoff`'s existing `409` |
| `revision_requested` | owner | not required | `403 not_item_owner` — **see the Correction below** |
| `pr_opened` | owner | **required** | `403 not_item_owner`; `409` on token mismatch |
| `workspace_released` | owner | **required** | unchanged — the branch already enforces both |
| unknown status | — | — | `400 unknown status <s>` (unchanged) |

**Correction (2026-08-09, source verification) — three of §3.5a's rows are not PR0's, and one of them inverts.**

1. **`revision_requested` stays owner-authorized here; its retirement is PR1's.** §3.5a's matrix gives this row to *nobody*, refusing `409 use_deck_approve_work_item`. That refusal is the visible half of §4.3a.1's `advance_approval_round` — "the rejection *is* the transition" — and §4.3a.1 is squarely inside the PR1 chapter (spec `:985` opens it; §4.3a.1 is at `:1760`). By §2.1's rule, *"each artifact ships in the earliest PR that has a consumer for it"*, the refusal ships with the function that replaces it. Today the branch calls `record_approval_round` (`agent_teams.py:302`) and `test_revision_requested_increments_and_caps` (`test_dispatch_status_tool.py:165-176`) asserts `200` plus `escalated` / `approval_rounds_exhausted`. **Give this row the ordinary owner rule and leave the branch body alone.** Consequences to carry forward: spec test **7d is PR1's**, and 7b's stated exception ("a test hardcoding `403` fails on the one branch whose refusal is stronger") **does not apply in PR0** — in PR0 every authorization refusal on this route is a `403`, so 7b's table may carry one code. PR1's plan must add the per-branch expected status back when it adds the `409`.
2. **`pr_ready` has no row, because the branch does not exist.** Grep-verified in `app/`, and §2.1 assigns `pr_ready` and its head check to **PR2**. So the table has **nine** statuses, not ten, and spec tests **7h and 7i are PR2's**. Test 7c's exhaustiveness assertion is written against whatever the route accepts, so it needs no edit when PR2 adds the tenth — which is the entire reason it is mechanical rather than a hardcoded list.
3. **The whole-route `409 tokens_not_enforced` is PR1's**, per §2.1's grace-mode row. PR0 must not add it. In PR0 this route keeps the same grace-mode fallback the mail routes got in Task 5: **no token ⇒ legacy caller-supplied `reporting_slot_id`, unchanged behaviour; a token that resolves ⇒ derived slot and the table enforced; an invalid token ⇒ `401 session_token_invalid`.** That is what keeps the 22 existing tests in `test_dispatch_status_tool.py` green and what keeps a pre-upgrade shim working across the deploy.

**What PR0's authorization is therefore worth, stated honestly.** With enforcement off, a caller who simply omits the header gets today's behaviour, so PR0's matrix is **not** a live control on the day it deploys — it is the control that becomes live when the operator flips `mail_capability_tokens_required`, which is §3.8's rollout step and Task 11's note. Two things make writing it now correct rather than theatre: the shim ships the header in the same PR (Task 6), so every *real* caller is authorized from the moment the panes restart; and PR1's `409` closes the tokenless hole in the PR that needs it closed. Do not "improve" this by refusing tokenless calls in PR0 — that breaks the shipped shim on deploy, which is the one thing grace mode exists to prevent.

**Where the check lives: in the route, once, before the branch chain.** Not inside the service functions. `initiate_handoff`, `accept_handoff`, `record_approval_round`, `escalate`, and `report_pr_opened` are all also called from the monitor loop and from operator paths that have no reporting slot; pushing agent authorization down into them would either block those callers or grow an `if caller_is_agent` parameter through five signatures. The endpoint is the trust boundary.

**Ordering: authorize before the first mutation, not after.** This is what tests 7b and 7f actually assert — a route that mutates and *then* refuses returns the same status code as one that refuses first, so only the row can tell them apart. The resolver goes immediately after `scope` is loaded at `:294` and before `if report.status == "triaging"` at `:296`.

**`workspace_released` keeps its own checks and gains nothing.** Its `409` at `:334` and its `400 lease_token required` at `:339` both stay exactly as they are, and four existing tests assert those codes (`test_non_owner_cannot_release_workspace` expects `409`, `test_workspace_release_requires_token` expects `400 lease_token required`). The resolver's table lists the row for test 7c's benefit, and the resolver must **not** pre-empt the branch: converting that `409` to a `403` is PR1's `release_by_owner` work (§4.6a requirement 5), not PR0's. Concretely — the resolver skips its own refusal for `workspace_released` and lets the branch speak.

**`handoff_accepted` keeps both refusals.** The resolver's `403 not_handoff_target` says *"you are not the target"*; `accept_handoff`'s `ValueError → 409` (`:309-313`) says *"there is no handoff to accept."* Collapsing them loses a distinction the agent needs in order to act — retry versus give up. Note the ordering consequence: with a `handoff_target_slot_id` set, the `403` fires first and the `409` becomes unreachable *for a non-target*; the `409` remains reachable for the target of a handoff that was since cleared.

**`touch_owner_contact` needs no change.** Its gate in the tail (`report.status != "workspace_released" and report.reporting_slot_id == item.owner_slot_id`, `:371-377`) becomes honest once `reporting_slot_id` is derived, and because the resolver runs first, a refused report never reaches it. It stamps nudge-timing evidence only, never a merge input — a stale token is already a logged no-op (`github_workspace_service.py:255-259`).

- [ ] **Step 1: Add the token plumbing to the existing test file**

The tests need a session row whose `team_slot_id` is a slot the item knows about. **Do not register through `/agent-mail/agent/register` to get one.** Measured: `register_session` only honours a `team_slot_id` when `_slot_matches_registration` passes, which requires `request.provider == slot.provider` **and** `derive_repo_identity(request.cwd)["repo_id"] == slot.repo_id` (`agent_mail_service.py:295-305`). `_seed_leased_item` builds its slots with `provider="codex-cli"` and `repo_id="r"`, and a `tmp_path` hashes to a 16-hex `repo_id` that is never `"r"` — so a registration against those slots silently yields `session.team_slot_id = None` and every authorization test would refuse with `session_not_slot_bound` instead of testing the matrix. Verified by running all three shapes: only matching provider **and** `repo_id` binds.

So seed the session directly. Add to `backend/tests/agent_mail/test_dispatch_status_tool.py`:

```python
import hashlib

from app.models.database import MailAgentSession, MailTeamMember
from app.services.agent_mail_service import agent_mail_service


async def _token_for_slot(maker, slot_id: int | None, *, key: str = "mcp:auth") -> str:
    """Mint a session bound to slot_id and return its plaintext token.

    Seeded directly rather than through /agent/register: that route derives the
    slot via _slot_matches_registration, which compares provider AND repo_id
    against the slot row -- and _seed_leased_item's slots use provider
    "codex-cli" with repo_id "r", which no tmp_path can hash to. Registering
    would hand back a session with team_slot_id = None and every test below
    would refuse with session_not_slot_bound instead of exercising the matrix.
    """
    token = f"tok-{key}-{slot_id}"
    async with maker() as db:
        member = MailTeamMember(
            identity_key=f"slot:{key}:{slot_id}",
            repo_id="r",
            repo_path="/tmp/r",
            repo_name="r",
            display_name="Reporter",
            participant_kind="team_slot",
            team_slot_id=slot_id,
        )
        db.add(member)
        await db.flush()
        db.add(
            MailAgentSession(
                member_id=member.id,
                source="mcp",
                session_key=key,
                team_slot_id=slot_id,
                capability_token_hash=agent_mail_service.hash_capability_token(token),
            )
        )
        await db.commit()
    return token


def _auth(token: str) -> dict[str, str]:
    return {"X-Deck-Session-Token": token}
```

`hash_capability_token` is Task 3's; `capability_token_hash` is Task 1's column. `MailTeamMember` requires `identity_key`, `repo_id`, `repo_path`, `repo_name`, `display_name`; `MailAgentSession` requires `member_id`, `source`, `session_key` — measured, so an insert missing one fails with a constraint error that reads like a logic bug.

- [ ] **Step 2: Write the failing authorization tests (7b, 7e, 7f, 7g)**

Append to the same file:

```python
_OWNER_ONLY_STATUSES = [
    ("triaging", {"note": "n"}),
    ("in_progress", {}),
    ("blocked", {"note": "n"}),
    ("ack_received", {}),
    ("revision_requested", {}),
    ("handoff_initiated", {"reassign_to_slot_id": 1}),
    ("pr_opened", {"pr_number": 7}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,extra", _OWNER_ONLY_STATUSES)
async def test_non_owner_is_refused_and_changes_nothing(client_and_db, status, extra):
    """Test 7b. The columns are the assertion: a route that mutates and THEN
    refuses returns the same 403 as one that refuses first."""
    ac, maker = client_and_db
    item_id, owner_id, other_id, _, _ = await _seed_leased_item(
        maker, dispatch_status="dispatched"
    )
    token = await _token_for_slot(maker, other_id, key=f"mcp:{status}")
    async with maker() as db:
        before = await db.get(GithubWorkItem, item_id)
        snapshot = {
            column.name: getattr(before, column.name)
            for column in GithubWorkItem.__table__.columns
        }

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={"work_item_id": item_id, "status": status, **extra},
        headers=_auth(token),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "not_item_owner"
    async with maker() as db:
        after = await db.get(GithubWorkItem, item_id)
        assert {
            column.name: getattr(after, column.name)
            for column in GithubWorkItem.__table__.columns
        } == snapshot


@pytest.mark.asyncio
async def test_handoff_accepted_belongs_to_the_target(client_and_db):
    """Test 7e. Both calls run against an item whose handoff_target_slot_id is
    SET, so the refusal comes from the resolver and not from accept_handoff's
    own 409 -- which is a different sentence to the agent."""
    ac, maker = client_and_db
    item_id, owner_id, other_id, _, _ = await _seed_leased_item(
        maker, dispatch_status="dispatched"
    )
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        item.handoff_target_slot_id = other_id
        item.handoff_state = "pending"
        await db.commit()

    owner_token = await _token_for_slot(maker, owner_id, key="mcp:ha-owner")
    refused = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={"work_item_id": item_id, "status": "handoff_accepted"},
        headers=_auth(owner_token),
    )
    assert refused.status_code == 403
    assert refused.json()["detail"] == "not_handoff_target"
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        assert item.owner_slot_id == owner_id
        assert item.handoff_state == "pending"

    target_token = await _token_for_slot(maker, other_id, key="mcp:ha-target")
    accepted = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={"work_item_id": item_id, "status": "handoff_accepted"},
        headers=_auth(target_token),
    )
    assert accepted.status_code == 200
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        assert item.owner_slot_id == other_id
        assert item.handoff_state == "accepted"


@pytest.mark.asyncio
async def test_pr_opened_with_a_stale_token_leaves_pr_number_null(client_and_db):
    """Test 7f. The NULL assertion is the point: pr_number is what admits the
    item to process_scope's query, so setting it before the token check makes
    the refusal cosmetic -- the merge path has already been entered."""
    ac, maker = client_and_db
    item_id, owner_id, _, _, _ = await _seed_leased_item(maker, dispatch_status="dispatched")
    token = await _token_for_slot(maker, owner_id, key="mcp:pr")

    stale = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "pr_opened",
            "pr_number": 7,
            "lease_token": "lease-stale",
        },
        headers=_auth(token),
    )
    assert stale.status_code == 409
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        assert item.pr_number is None
        assert item.dispatch_status == "dispatched"

    current = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "pr_opened",
            "pr_number": 7,
            "lease_token": "lease-current",
        },
        headers=_auth(token),
    )
    assert current.status_code == 200
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        assert item.pr_number == 7


@pytest.mark.asyncio
async def test_pr_opened_with_no_token_at_all_is_refused(client_and_db):
    """The sibling 7f needs: absent is not the same as wrong, and neither is OK
    on the one branch that opens the merge path."""
    ac, maker = client_and_db
    item_id, owner_id, _, _, _ = await _seed_leased_item(maker, dispatch_status="dispatched")
    token = await _token_for_slot(maker, owner_id, key="mcp:pr-none")

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={"work_item_id": item_id, "status": "pr_opened", "pr_number": 7},
        headers=_auth(token),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "lease_token required"
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        assert item.pr_number is None


@pytest.mark.asyncio
async def test_blocked_needs_no_lease_token(client_and_db):
    """Test 7g. Written to fail against an implementation that requires the
    token everywhere 'for consistency'. A gate that can refuse an escalation
    because a lease rotated is a gate that hides failures."""
    ac, maker = client_and_db
    item_id, owner_id, _, _, _ = await _seed_leased_item(maker, dispatch_status="dispatched")
    token = await _token_for_slot(maker, owner_id, key="mcp:blocked")

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={"work_item_id": item_id, "status": "blocked", "note": "stuck"},
        headers=_auth(token),
    )

    assert response.status_code == 200
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        assert item.dispatch_status == "escalated"
        assert item.escalation_reason == "plan_blocked"
        assert item.status_note == "stuck"


@pytest.mark.asyncio
async def test_a_disagreeing_slot_claim_is_refused(client_and_db):
    """Spec test 7: the body is corroboration, never authority. Agreeing is
    accepted, disagreeing is 403 -- never a silent overwrite, which would
    report a misconfigured shim as success."""
    ac, maker = client_and_db
    item_id, owner_id, other_id, _, _ = await _seed_leased_item(
        maker, dispatch_status="dispatched"
    )
    token = await _token_for_slot(maker, owner_id, key="mcp:claim")

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "triaging",
            "reporting_slot_id": other_id,
            "note": "n",
        },
        headers=_auth(token),
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "slot_claim_mismatch"

    agreeing = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "triaging",
            "reporting_slot_id": owner_id,
            "note": "n",
        },
        headers=_auth(token),
    )
    assert agreeing.status_code == 200


@pytest.mark.asyncio
async def test_an_unbound_session_cannot_speak_for_a_slot(client_and_db):
    """A session with team_slot_id NULL can send mail as a repo member. It can
    never report dispatch status, which is a claim about a slot."""
    ac, maker = client_and_db
    item_id, _, _, _, _ = await _seed_leased_item(maker, dispatch_status="dispatched")
    token = await _token_for_slot(maker, None, key="mcp:unbound")

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={"work_item_id": item_id, "status": "triaging", "note": "n"},
        headers=_auth(token),
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "session_not_slot_bound"


@pytest.mark.asyncio
async def test_an_invalid_token_never_falls_back_to_the_legacy_path(client_and_db):
    """Grace mode must not turn a wrong token into an unauthenticated report."""
    ac, maker = client_and_db
    item_id, owner_id, _, _, _ = await _seed_leased_item(maker, dispatch_status="dispatched")

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={
            "work_item_id": item_id,
            "status": "triaging",
            "reporting_slot_id": owner_id,
            "note": "n",
        },
        headers=_auth("not-a-real-token"),
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "session_token_invalid"
```

Three things to note about these tests.

1. **`_seed_leased_item` is the right fixture even for the non-release branches.** It is the only helper in the file that creates *two* slots and sets `owner_slot_id`, which is what an owner/non-owner test needs. `_seed_item` sets no owner at all, so every authorization test built on it would compare against `None`.
2. **`_OWNER_ONLY_STATUSES` omits `workspace_released`** deliberately — that branch's non-owner refusal is `409` and is already covered by `test_non_owner_cannot_release_workspace`. Adding it to this parameterization would assert `403` and fail. It also omits `handoff_accepted`, whose refusal is `not_handoff_target`.
3. **The `handoff_initiated` row passes `reassign_to_slot_id: 1`** only so the request is well-formed; the resolver refuses before the branch reads it, which the snapshot proves.

- [ ] **Step 3: Run to verify they fail**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_mail/test_dispatch_status_tool.py -q -p no:warnings
```

Expected: the 22 existing tests pass, and the new ones fail — the `403` tests return `200` (nothing authorizes), `test_an_unbound_session_cannot_speak_for_a_slot` returns `200`, and the invalid-token test returns `200` because no dependency reads the header yet.

- [ ] **Step 4: Write test 7c — the matrix is exhaustive**

This is the blocker-1 test in general form: revision 5's `pr_ready` hole was one missing row, and a per-row test would have to be rewritten for every future branch to catch the next one. Append:

```python
import ast
import inspect
import textwrap

import app.api.v1.agent_teams as agent_teams_routes


def _statuses_the_route_accepts() -> set[str]:
    """Extract the accepted statuses from the branch chain itself.

    Reads `report.status == "<const>"` comparisons out of the route's own AST
    rather than trusting a hand-maintained list, so a branch added without a
    matrix row fails this test instead of silently defaulting to allowed.
    """
    source = textwrap.dedent(inspect.getsource(agent_teams_routes.report_dispatch_status))
    return {
        node.comparators[0].value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Compare)
        and len(node.ops) == 1
        and isinstance(node.ops[0], ast.Eq)
        and isinstance(node.left, ast.Attribute)
        and node.left.attr == "status"
        and isinstance(node.comparators[0], ast.Constant)
        and isinstance(node.comparators[0].value, str)
    }


def test_every_accepted_status_has_an_authorization_rule():
    """Test 7c. A status absent from the table is unauthorized by omission."""
    accepted = _statuses_the_route_accepts()
    assert len(accepted) == 9, f"branch count changed: {sorted(accepted)}"
    missing = accepted - set(agent_teams_routes._DISPATCH_STATUS_RULES)
    assert not missing, f"statuses with no authorization rule: {sorted(missing)}"


def test_the_rules_table_has_no_rule_for_a_status_the_route_rejects():
    """The other direction: a rule for a branch that does not exist is a rule
    nothing enforces, and reads as coverage during review."""
    stale = set(agent_teams_routes._DISPATCH_STATUS_RULES) - _statuses_the_route_accepts()
    assert not stale, f"rules for non-existent statuses: {sorted(stale)}"


@pytest.mark.asyncio
async def test_an_unknown_status_refuses_rather_than_falling_through(client_and_db):
    """The fall-through must refuse, not proceed. Written to fail against a
    resolver whose default is 'no rule => allowed'."""
    ac, maker = client_and_db
    item_id, owner_id, _, _, _ = await _seed_leased_item(maker, dispatch_status="dispatched")
    token = await _token_for_slot(maker, owner_id, key="mcp:unknown")

    response = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        json={"work_item_id": item_id, "status": "not_a_real_status"},
        headers=_auth(token),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "unknown status not_a_real_status"
```

**Why the `len(accepted) == 9` assertion is there and why it is not brittle.** It is a tripwire, not a spec: if a later PR adds `pr_ready` (PR2's), this line fails loudly and the implementer updates it to `10` *and* checks that the new branch has a rule. Without it, an AST helper that silently stops matching — because someone rewrote the chain as a `match` statement, say — would return an empty set and both exhaustiveness tests would pass vacuously. Measured against today's route, the helper returns exactly `{ack_received, blocked, handoff_accepted, handoff_initiated, in_progress, pr_opened, revision_requested, triaging, workspace_released}`.

**The unknown-status test asserts `400`, not `403`.** The resolver has no rule for `not_a_real_status`, so it must not authorize it — but it must also not invent a new refusal. Letting an unknown status fall through the resolver *without a mutation* and reach the existing `else` at `:369` gives the caller the same `400 unknown status ...` it gets today, which is the right message. The rule is "no rule ⇒ no mutation," and `400` is how that surfaces.

- [ ] **Step 5: Run to verify 7c fails**

Expected: `AttributeError: module 'app.api.v1.agent_teams' has no attribute '_DISPATCH_STATUS_RULES'` on both table tests. The unknown-status test already passes — it is a regression guard on the `else` branch, and it must stay passing through the implementation step.

- [ ] **Step 6: Add the rules table and the resolver**

In `backend/app/api/v1/agent_teams.py`, extend the import at `:8` and add two imports:

```python
from typing import NamedTuple

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.api.v1.deps import mail_session, require_session_slot
from app.models.database import AgentTeamSlot, MailAgentSession
```

`AgentTeamSlot` and `MailAgentSession` are **not** currently imported here — `:15` imports only `GithubWorkItem`, `GithubWorkspace`, `TeamGithubScope`. `typing` is not imported at all today; the file uses `from __future__ import annotations` and `X | None` annotations, so **write new annotations in that style** and use `typing` only for `NamedTuple`. Verified: a `session: MailAgentSession | None = Depends(...)` parameter resolves correctly under `from __future__ import annotations` — FastAPI evaluates the string annotation, so the PEP 604 form is safe here.

Then add above the route:

```python
class _StatusRule(NamedTuple):
    """Who may report a status, and whether the current lease token is needed.

    role is "owner" (item.owner_slot_id) or "target"
    (item.handoff_target_slot_id). enforced_in_branch marks the one status whose
    own branch already does both checks, with its own codes and its own tests.
    """

    role: str
    refusal: str
    lease_token_required: bool = False
    enforced_in_branch: bool = False


_OWNER = _StatusRule("owner", "not_item_owner")

# One entry per status the branch chain accepts. A status missing from this
# table is unauthorized by omission -- the resolver refuses to mutate rather
# than defaulting to allowed. Tests 7b/7c pin both halves of that rule.
_DISPATCH_STATUS_RULES: dict[str, _StatusRule] = {
    "triaging": _OWNER,
    "in_progress": _OWNER,
    "blocked": _OWNER,
    "ack_received": _OWNER,
    "handoff_initiated": _OWNER,
    "revision_requested": _OWNER,
    "handoff_accepted": _StatusRule("target", "not_handoff_target"),
    "pr_opened": _StatusRule("owner", "not_item_owner", lease_token_required=True),
    "workspace_released": _StatusRule(
        "owner", "not_item_owner", lease_token_required=True, enforced_in_branch=True
    ),
}


async def _authorize_dispatch_report(
    db: AsyncSession,
    item: GithubWorkItem,
    report: DispatchStatusReport,
    session: MailAgentSession | None,
) -> None:
    """Authorize a dispatch-status report, before the branch chain mutates.

    Grace mode: with no token this returns immediately and the caller's own
    reporting_slot_id is used, exactly as before PR0. An INVALID token never
    reaches here -- mail_session raises 401 for that, so garbage cannot buy the
    legacy path. PR1 closes the tokenless hole for the whole route.
    """
    if session is None:
        return

    slot_id = require_session_slot(session)
    if report.reporting_slot_id is not None and report.reporting_slot_id != slot_id:
        # The body is corroboration, never authority. Agreeing is accepted so
        # the shipped shim's payload stays valid; disagreeing is a refusal
        # rather than a silent overwrite, which would report a misconfigured
        # shim as success.
        raise HTTPException(status_code=403, detail="slot_claim_mismatch")
    report.reporting_slot_id = slot_id

    rule = _DISPATCH_STATUS_RULES.get(report.status)
    if rule is None:
        # No rule => no mutation. Fall through to the branch chain, which ends
        # in `400 unknown status ...`. Never default to allowed.
        return
    if rule.enforced_in_branch:
        return

    authorized = item.owner_slot_id if rule.role == "owner" else item.handoff_target_slot_id
    if authorized is None or slot_id != authorized:
        raise HTTPException(status_code=403, detail=rule.refusal)

    if rule.lease_token_required:
        if report.lease_token is None:
            raise HTTPException(status_code=400, detail="lease_token required")
        workspace = await github_workspace_service.get_leased_workspace(db, item.id)
        if workspace is None or workspace.lease_token != report.lease_token:
            raise HTTPException(
                status_code=409,
                detail=f"lease_token does not match the current lease for item {item.id}",
            )
```

Then wire it into the route — two lines, immediately after `scope` is loaded:

```python
@router.post("/dispatch-status")
async def report_dispatch_status(
    report: DispatchStatusReport,
    session: MailAgentSession | None = Depends(mail_session),
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(GithubWorkItem, report.work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="work item not found")
    scope = await db.get(TeamGithubScope, item.scope_id)
    await _authorize_dispatch_report(db, item, report, session)

    if report.status == "triaging":
        ...
```

Five points the implementer must not get wrong:

1. **`authorized is None` refuses.** An item with `owner_slot_id = NULL` has no owner, so no slot can be its owner and every owner-only report on it must be refused. Written as an explicit clause rather than relying on `slot_id != None`, because the two happen to agree here and only one of them says what is meant — and the column *is* nullable (`models/database.py:259`), so this is a reachable state, not a hypothetical. Live: all 28 work items currently have a non-NULL owner, which is exactly why a bug here would not show up in the soak.
2. **`report.reporting_slot_id = slot_id` mutates the Pydantic model in place.** `DispatchStatusReport` is a plain `BaseModel` with no `model_config`, so assignment is permitted and no validation runs on it. This is what makes the rest of the route — including `workspace_released`'s own owner check and the `touch_owner_contact` gate in the tail — read the *derived* slot without any further edits. Task 5's mail routes used `model_copy(update=...)` instead because they pass the request object into a service; here the route reads the fields itself.
3. **The lease check is the resolver's own, and it deliberately duplicates `release_by_token`'s message.** `pr_opened` never touched a lease before, so there is nothing to reuse: `release_by_token` (`github_workspace_service.py:178-194`) both checks *and releases*, which is not what `pr_opened` wants. Matching its `409` detail string keeps one sentence for one failure across the route. Do **not** refactor `release_by_token` to share this code in PR0 — that function is rewritten as `release_by_owner` in PR1 (§4.6a requirement 2), and a shared helper introduced now would have to be unpicked.
4. **`get_leased_workspace` filters on `leased_item_id` only** — no scope predicate — so it returns *this item's* lease or nothing. That is what makes the check "does this token lease **this** item" rather than "is this token current for some workspace." The distinction is the whole content of spec test 7h (PR2's): an implementation that queries by token instead of by item passes a naive test and fails that one. Keep the query keyed on `item.id`.
5. **No `Header` import is needed in this file — not in this task and not in Task 8 either.** The header is read by `mail_session` inside `deps.py`, which already imports `Header` (Task 5, Step 3). Task 8's `require_operator` lives in that same module for the same reason, so `agent_teams.py` never grows a `Header` import in PR0: it imports the two *dependencies*, not the primitive they are built from. If you find yourself adding `Header` to `:8`, a dependency has leaked into the route module — stop and re-read Task 8's Step 3.

- [ ] **Step 7: Run the file**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_mail/test_dispatch_status_tool.py -q -p no:warnings
```

Expected: all pass — the 22 pre-existing tests **unchanged and untokenized**, plus the new ones. If any of the original 22 now fails, the resolver is refusing in grace mode, which it must not: those 22 tests send no header, and 5 of them (`:153`, `:169`, `:184`, `:200`, `:217`) send no `reporting_slot_id` either. Their continuing to pass *is* the backward-compatibility assertion, so **do not add tokens to them**.

- [ ] **Step 8: Mutate to prove the ordering assertion has teeth**

Test 7b's value is entirely in the column snapshot, and a snapshot assertion that would pass against a mutate-then-refuse implementation is worth nothing. Prove it bites: move the `await _authorize_dispatch_report(...)` call from before the branch chain to **immediately after it**, just above the `touch_owner_contact` block at `:371`, and re-run.

Expected: `test_non_owner_is_refused_and_changes_nothing` fails on the **snapshot**, not the status code, for the parameterizations that write (`triaging` writes `status_note`; `revision_requested` increments `approval_round_count`; `handoff_initiated` writes `handoff_target_slot_id`). Then restore the call to its correct position **by replacing the exact string** — do not `git checkout`, there is uncommitted work in this file.

If every parameterization still passes with the mutant, the snapshot is being taken or compared wrongly and 7b is decorative — **stop and report**.

- [ ] **Step 9: Run the full suite**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && pytest tests/agent_teams/ tests/agent_mail/ -q -p no:warnings
```

Expected: `526 passed` (509 after Task 6 + this task's 17 **collected cases** — 10 plain tests plus `test_non_owner_is_refused_and_changes_nothing`'s 7 parameterizations), no new failures. The risk area is `tests/agent_teams/test_github_dispatch_service.py` — it calls `initiate_handoff` and `accept_handoff` **at the service level** (`:2439-2448`), which the resolver does not touch by design. If a *service* test fails, authorization leaked out of the route and into a service; that is the one outcome this task's design exists to prevent, so **stop and report**.

**Cases, not functions, from here on.** Tasks 7, 8 and 9 each add parametrized tests, so their `def` count and their `passed` count differ. This task writes **11 test functions** but adds **17 collected cases**, because `test_non_owner_is_refused_and_changes_nothing` is parameterized over `_OWNER_ONLY_STATUSES`' seven rows. `test_dispatch_status_tool.py` measures **22 today** and ends this task at **39**.

- [ ] **Step 10: Commit**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1 && git add backend/app/api/v1/agent_teams.py backend/tests/agent_mail/test_dispatch_status_tool.py && git commit -m "feat(teams): authorize every /dispatch-status branch, not just one

Of the nine branches this route accepts, exactly one compared the reporter to
the item. A resolver now runs once before the branch chain: owner-only for
seven statuses, target-only for handoff_accepted, and the current lease token
on pr_opened, which is the branch that admits an item to the merge path by
setting pr_number.

The rules live in a module-level table so an added branch with no rule is
caught by a test that reads the route's own AST rather than a hand-maintained
list. A status with no rule refuses to mutate and falls through to the existing
400, never to allowed.

The body's reporting_slot_id becomes corroboration: agreeing is accepted so the
shipped shim keeps working, disagreeing is 403, absent is filled from the
token. Tokenless calls keep today's behaviour while
mail_capability_tokens_required is False -- PR1 closes that with a whole-route
409 tokens_not_enforced, in the PR whose guarantees need it.

workspace_released keeps its own two checks and its own codes; converting its
409 to a 403 is PR1's release_by_owner work.

Spec: 2026-08-05-distinct-approver-identity-design.md section 3.5a"
```

---

### Task 8: `require_operator` and the two operator routes

**Files:**
- Modify: `backend/app/api/v1/deps.py` (append `require_operator`; no new imports — `hmac`, `Header`, `HTTPException` and `settings` are all already there from Task 5)
- Modify: `backend/app/api/v1/agent_teams.py:14` (import), `:554-557` (the listing signature), `:676-681` (the force-release signature)
- Test: `backend/tests/agent_teams/test_operator_auth.py` (create)
- Test: `backend/tests/agent_teams/test_github_workspace_api.py` (modify — 8 call sites need the header)

**Interfaces:**
- Consumes: `settings.operator_token` (Task 1); the `deps.py` module (Task 5).
- Produces: `require_operator() -> None` — a value-less dependency. Raises `503 operator_token_unconfigured`, `401 operator_token_required`, or `401 operator_token_invalid`. PR1's `resume-attempt` (§4.2b.2) is its third consumer.

**What this task fixes is live on `master` right now, which is why it is in PR0 rather than PR1.** Force-release is reachable by any local process with no credential at all, and its mismatch branch interpolates the *live* lease token into the response (`agent_teams.py:693-698` → `_conflict` at `:84-88` → `detail.message`, serialised verbatim). Two unauthenticated calls — guess, read the real token out of the refusal, replay it — force-release any agent's workspace. The disclosure itself is deleted in Task 9 along with the field that makes it possible; this task shuts the door.

**`agent_teams.py` has no authentication at all today, so this is the file's first non-`get_db` dependency.** Measured: all 27 `Depends(...)` in the file are `Depends(get_db)`. There was no operator surface for a route to sit "on" — the spec's earlier phrase "the unauthenticated-but-human surface" named an absence, not a surface.

**Why the external-actor token cannot be this credential**, since §3.6 uses it for the UI and it is the obvious candidate. Measured end to end through the real app, with no credential presented:

```
POST /api/v1/external/agent-mail/actors (no credential) -> 200, keys ['actor', 'token']
  token length 43
  GET /actors/me with it -> 200, kind='supervisor'
```

An agent pane *is* a loopback caller, so it mints its own "supervisor" actor in one call. An authentication scheme is only as strong as the cheapest way to obtain a credential. This is why test 20 has a row that **mints a real actor token** rather than fabricating a string.

**What this credential is worth, stated honestly.** The backend and every pane run as the same uid (`juan`), `hidepid` is absent, and `backend/.env` is mode `600` owned by that same uid — so a determined pane can read the token. It is a boundary against an *opportunistic* adversary, not a co-resident one: it moves the attack from *knowing a URL*, which every agent does because this spec publishes them, to *deliberately reading a `600` file*. Do not describe it in code comments or the commit message as authenticating a human. §8's criterion is "not reachable by an agent following its brief," not "not reachable by an agent."

**And the deployment prohibition that follows: the token goes in `backend/.env` and is never exported.** This is a requirement with a measurement attached, not a style preference. `spawn_session` runs `tmux new-session` with **no `env=`** (`agent_bridge/spawn.py:78-83`), so the tmux *server* inherits the backend's whole environment as its **global** environment, and any pane reads it back with `tmux show-environment -g` — one documented command, in a shell every agent has. The `-e` allowlist protects the pane's own `environ` and nothing else. Had the token been exported, the bound above would collapse from *opportunistic adversary* to *none*. Task 11 carries the runbook line.

#### The four measurements that decide this task's code

**1. The empty case must be checked before the comparison, and the mutant is subtler than "wrong status".** `hmac.compare_digest("", "")` returns `True` (measured). Driving the mutant — `503` branch omitted, empty setting left to the comparison — against an unconfigured install:

```
MUTANT on an UNCONFIGURED install:
  no header        -> 200 {'workspaces': ['/tmp/ws-1', '/tmp/ws-2']}
  empty header     -> 200 {'workspaces': ['/tmp/ws-1', '/tmp/ws-2']}
  garbage header   -> 401 {'detail': 'operator_token_invalid'}
```

Read the third line. The mutant **does** refuse a wrong token, so a suite that only ever sends non-empty wrong headers passes an install that serves the whole workspace topology to any caller sending nothing. That is why the spec gives "empty header on an empty setting" its own row and why every unconfigured assertion checks the **code** `503`, not merely "a 4xx or 5xx".

**2. `hmac.compare_digest` raises `TypeError` on non-ASCII `str`, and a header can carry one.** Measured: comparing two `str` values containing `é` raises `TypeError: comparing strings with non-ASCII characters is not supported`, and driven through a real route, a `latin-1`-encoded header produced **HTTP 500** — an unhandled exception, not a refusal. So the comparison operates on **bytes**: `x_deck_operator_token.encode("utf-8")` against `expected.encode("utf-8")`. With that one change the same input returns `401 operator_token_invalid`. **No spec row covers this**; it is a plan-level addition, and Step 1's test includes the case so it cannot regress.

**3. Read `settings.operator_token` at call time, never at import time.** `settings` is constructed at import (`config.py:57`), so a module-level `EXPECTED = settings.operator_token` in `deps.py` would freeze the empty default before any test could configure it — every operator test would then see `503` and the positive control could not be written at all. Reading the attribute inside the function is also what makes `monkeypatch.setattr(settings, "operator_token", ...)` work; measured, `Settings` has neither `frozen` nor `validate_assignment`, so plain assignment is permitted, and `app.config.settings` is the same object through every import.

**4. The dependency runs before body validation and before the route body.** Measured, in both the decorator and the parameter form:

| Request | Status |
|---|---|
| no header, nonexistent scope | **401** (not 404) |
| no header, invalid body | **401** (not 422) |
| valid header, invalid body | 422 |
| valid header, nonexistent scope | 404 |
| valid header, valid request | 200 |

This is the correct posture — an unauthenticated caller must not learn whether a scope exists — and it has a consequence this task owns: **the existing `422` and `404` assertions in `test_github_workspace_api.py` start returning `401` the moment the dependency lands.** Fixing them belongs here, in the task that breaks them, not in Task 9. Eight call sites need the header: the listing at `:151` and `:171`, and force-release at `:182`, `:207`, `:235`, `:257`, `:281`, `:309`.

**Use the parameter form, `_operator: None = Depends(require_operator)`, not `dependencies=[...]` in the decorator.** Both were measured to enforce identically and both advertise the header in OpenAPI. The parameter form is the file's own idiom — measured, `dependencies=[` appears **zero** times in `app/`, while every one of the 27 existing dependencies is a parameter. The `_`-prefixed name says the value is unused; `external_agent_mail.py:95` already uses the sibling idiom `_ = actor`.

- [ ] **Step 1: Write the failing test — the eight-case matrix, for both routes**

Create `backend/tests/agent_teams/test_operator_auth.py`:

```python
"""Spec §3.7 test 20 — require_operator refuses every credential an agent can obtain."""
from datetime import datetime
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.database import (
    AgentTeamPreset,
    GithubWorkItem,
    GithubWorkspace,
    MailAgentSession,
    MailTeamMember,
    TeamGithubScope,
)
from app.services.agent_mail_service import agent_mail_service

OPERATOR_TOKEN = "0f3c9a71b25e4d8fa6c1e07b9d24misalign"  # >= 32 bytes of nothing in particular


@pytest_asyncio.fixture
async def client_and_db(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http, maker
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.fixture
def operator_token_configured(monkeypatch):
    """Configure the operator token for the duration of one test.

    monkeypatch.setattr on the settings OBJECT, not on a module-level constant:
    require_operator reads settings.operator_token at call time precisely so
    this works. If a future refactor hoists the read to import time, every test
    below starts returning 503 and this fixture is where to look.
    """
    monkeypatch.setattr(settings, "operator_token", OPERATOR_TOKEN)
    return OPERATOR_TOKEN


@pytest.fixture
def operator_token_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "operator_token", "")


async def _leased_scope_and_workspace(maker, tmp_path: Path):
    """A scope with one leased workspace, so force-release reaches its own logic."""
    async with maker() as db:
        preset = AgentTeamPreset(name=f"Operator {tmp_path.name}", description="", created_by="test")
        db.add(preset)
        await db.flush()
        repo_path = tmp_path / "repo"
        repo_path.mkdir(exist_ok=True)
        scope = TeamGithubScope(
            preset_id=preset.id,
            repo_owner="o",
            repo_name=f"r-{preset.id}",
            repo_path=str(repo_path),
        )
        db.add(scope)
        await db.flush()
        item = GithubWorkItem(
            scope_id=scope.id,
            issue_number=1,
            issue_title="x",
            issue_url="u",
            github_updated_at=datetime.utcnow(),
            dispatch_status="merged",
        )
        db.add(item)
        await db.flush()
        workspace = GithubWorkspace(
            scope_id=scope.id,
            path=str(tmp_path / "ws"),
            kind="worktree",
            leased_item_id=item.id,
            leased_at=datetime.utcnow(),
            lease_token="lease-current",
        )
        db.add(workspace)
        await db.commit()
        return scope.id, workspace.id, item.id


async def _agent_session_token(maker) -> str:
    """A REAL agent capability token -- the credential an agent legitimately holds.

    Real rather than fabricated for the same reason the actor token is minted:
    a made-up string would be refused by anything, so the test would pass
    against a require_operator that happened to accept genuine session tokens.
    This one resolves through deps.mail_session on the routes that take it.

    No team_slot_id: this test is about the credential, not about slot binding,
    and an unbound session is the weaker case -- if even a slot-bound token were
    accepted the failure would be worse, but this shape is enough to show that
    the two schemes do not cross.
    """
    token = "agent-session-token-for-operator-test"
    async with maker() as db:
        member = MailTeamMember(
            identity_key="slot:operator-test",
            repo_id="r",
            repo_path="/tmp/r",
            repo_name="r",
            display_name="Agent",
        )
        db.add(member)
        await db.flush()
        db.add(
            MailAgentSession(
                member_id=member.id,
                source="mcp",
                session_key="operator-test",
                capability_token_hash=agent_mail_service.hash_capability_token(token),
            )
        )
        await db.commit()
    return token


async def _external_actor_token(client: httpx.AsyncClient) -> str:
    """Mint a real external-actor token, per the spec's instruction not to fabricate one.

    If this route ever gains a credential, this call starts failing -- which is
    the signal that §3.6a's "cheapest escalation on the host" argument needs
    re-measuring, and is exactly why the spec says mint rather than fake.
    """
    response = await client.post(
        "/api/v1/external/agent-mail/actors",
        json={
            "actor_key": "operator-auth-test",
            "display_name": "Operator Auth Test",
            "kind": "supervisor",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["token"]


# --- The two routes under test, as (label, callable) so one matrix covers both ---


def _routes(scope_id: int, workspace_id: int):
    listing = (
        "listing",
        "get",
        f"/api/v1/agent-teams/github-scopes/{scope_id}/workspaces",
        None,
    )
    force_release = (
        "force-release",
        "post",
        f"/api/v1/agent-teams/github-scopes/{scope_id}/workspaces/{workspace_id}/force-release",
        {"force": True, "reason": "owner is unavailable"},
    )
    return [listing, force_release]


async def _call(client, method, url, body, headers):
    if method == "get":
        return await client.get(url, headers=headers)
    return await client.post(url, json=body, headers=headers)


@pytest.mark.asyncio
@pytest.mark.parametrize("header", [None, "", "anything-at-all"])
async def test_unconfigured_install_refuses_with_503_whatever_the_header(
    client_and_db, tmp_path, operator_token_unconfigured, header
):
    """Row 1 and row 2 of test 20's table.

    The empty-header case is NOT redundant with the no-header case. Measured
    against the mutant that omits the 503 branch: no header -> 200 and empty
    header -> 200, while "anything-at-all" -> 401. So a suite that only sends
    non-empty wrong tokens passes an unconfigured install that serves the whole
    workspace topology to any caller. Assert the CODE, never merely a 4xx/5xx.
    """
    client, maker = client_and_db
    scope_id, workspace_id, _ = await _leased_scope_and_workspace(maker, tmp_path)
    headers = {} if header is None else {"X-Deck-Operator-Token": header}

    for label, method, url, body in _routes(scope_id, workspace_id):
        response = await _call(client, method, url, body, headers)
        assert response.status_code == 503, f"{label}: {response.status_code} {response.text}"
        assert response.json()["detail"] == "operator_token_unconfigured", label


@pytest.mark.asyncio
async def test_no_header_is_required_and_a_wrong_one_is_invalid(
    client_and_db, tmp_path, operator_token_configured
):
    """Rows 3 and 4: the two 401s must be distinguishable from each other."""
    client, maker = client_and_db
    scope_id, workspace_id, _ = await _leased_scope_and_workspace(maker, tmp_path)

    for label, method, url, body in _routes(scope_id, workspace_id):
        absent = await _call(client, method, url, body, {})
        assert absent.status_code == 401, label
        assert absent.json()["detail"] == "operator_token_required", label

        wrong = await _call(client, method, url, body, {"X-Deck-Operator-Token": "wrong"})
        assert wrong.status_code == 401, label
        assert wrong.json()["detail"] == "operator_token_invalid", label


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token,why",
    [
        (OPERATOR_TOKEN[:-1], "a prefix of the real token"),
        (OPERATOR_TOKEN + "X", "the real token plus a trailing byte"),
        (OPERATOR_TOKEN.upper(), "the real token in the wrong case"),
    ],
)
async def test_near_miss_tokens_are_invalid(
    client_and_db, tmp_path, operator_token_configured, token, why
):
    """Row 5: the rows a startswith, `in`, or truncating comparison fails."""
    client, maker = client_and_db
    scope_id, workspace_id, _ = await _leased_scope_and_workspace(maker, tmp_path)

    for label, method, url, body in _routes(scope_id, workspace_id):
        response = await _call(client, method, url, body, {"X-Deck-Operator-Token": token})
        assert response.status_code == 401, f"{label}: {why} was accepted"
        assert response.json()["detail"] == "operator_token_invalid", label


@pytest.mark.asyncio
async def test_a_non_ascii_header_is_refused_rather_than_crashing(
    client_and_db, tmp_path, operator_token_configured
):
    """Not a spec row -- a plan-level addition, measured.

    hmac.compare_digest raises TypeError on str values holding non-ASCII
    characters, and driven through a real route that reached the client as
    HTTP 500, an unhandled exception rather than a refusal. Comparing bytes
    turns the same input into a clean 401. Without this test, a str-comparing
    implementation passes every other row here.
    """
    client, maker = client_and_db
    scope_id, workspace_id, _ = await _leased_scope_and_workspace(maker, tmp_path)
    headers = {"X-Deck-Operator-Token": "café-not-a-token".encode("latin-1")}

    for label, method, url, body in _routes(scope_id, workspace_id):
        response = await _call(client, method, url, body, headers)
        assert response.status_code == 401, f"{label}: {response.status_code}"
        assert response.json()["detail"] == "operator_token_invalid", label


@pytest.mark.asyncio
async def test_an_agent_session_token_does_not_admit_an_operator_route(
    client_and_db, tmp_path, operator_token_configured
):
    """Row 6: an agent's own credential must not open an operator route.

    This is the assertion that fails if someone "unifies" the two dependencies
    on the grounds that both authenticate somebody. The token here is real --
    it resolves through deps.mail_session on the routes that accept it.
    """
    client, maker = client_and_db
    scope_id, workspace_id, _ = await _leased_scope_and_workspace(maker, tmp_path)
    session_token = await _agent_session_token(maker)
    headers = {"X-Deck-Session-Token": session_token}

    for label, method, url, body in _routes(scope_id, workspace_id):
        response = await _call(client, method, url, body, headers)
        assert response.status_code == 401, label
        assert response.json()["detail"] == "operator_token_required", label


@pytest.mark.asyncio
async def test_a_self_minted_external_actor_token_does_not_admit_either_route(
    client_and_db, tmp_path, operator_token_configured
):
    """Row 7: the cheapest escalation on the host.

    Minted for real, not fabricated. Presented both as a bearer token (the way
    external routes take it) and in the operator header (the way an implementer
    who confused the two schemes would wire it).
    """
    client, maker = client_and_db
    scope_id, workspace_id, _ = await _leased_scope_and_workspace(maker, tmp_path)
    actor_token = await _external_actor_token(client)

    for label, method, url, body in _routes(scope_id, workspace_id):
        as_bearer = await _call(
            client, method, url, body, {"Authorization": f"Bearer {actor_token}"}
        )
        assert as_bearer.status_code == 401, f"{label}: bearer actor token admitted"
        assert as_bearer.json()["detail"] == "operator_token_required", label

        as_operator = await _call(
            client, method, url, body, {"X-Deck-Operator-Token": actor_token}
        )
        assert as_operator.status_code == 401, f"{label}: actor token admitted as operator"
        assert as_operator.json()["detail"] == "operator_token_invalid", label


@pytest.mark.asyncio
async def test_the_configured_operator_token_is_accepted(
    client_and_db, tmp_path, operator_token_configured, monkeypatch
):
    """Row 8, the positive control.

    Without this row, a dependency that refuses everything passes every
    assertion above. The listing is the cheaper control (no git), so it carries
    the 200; force-release only has to get PAST the credential, which is what
    "not 401 and not 503" asserts -- its own success path is Task 9's business.
    """
    from app.services import github_workspace_service as ws_module

    client, maker = client_and_db
    scope_id, workspace_id, _ = await _leased_scope_and_workspace(maker, tmp_path)
    headers = {"X-Deck-Operator-Token": operator_token_configured}

    async def _fake_runner(args):
        return 0, ""

    monkeypatch.setattr(ws_module.github_workspace_service, "_runner", _fake_runner)

    listing = await client.get(
        f"/api/v1/agent-teams/github-scopes/{scope_id}/workspaces", headers=headers
    )
    assert listing.status_code == 200, listing.text
    assert len(listing.json()["workspaces"]) == 1

    forced = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope_id}/workspaces/"
        f"{workspace_id}/force-release",
        json={"force": True, "reason": "owner is unavailable"},
        headers=headers,
    )
    assert forced.status_code not in (401, 503), forced.text


@pytest.mark.asyncio
async def test_the_credential_is_checked_before_the_scope_is_looked_up(
    client_and_db, tmp_path, operator_token_configured
):
    """An unauthenticated caller must not learn whether a scope exists.

    Measured: the dependency runs before body validation and before the route
    body, so a missing header yields 401 where a valid one would yield 404 or
    422. Asserted rather than assumed, because it is the property that makes
    this dependency an authorization boundary and not a decoration -- and
    because it is why this task fixes the eight existing call sites in Step 6.
    """
    client, _ = client_and_db
    missing_scope = "/api/v1/agent-teams/github-scopes/999999/workspaces"

    assert (await client.get(missing_scope)).status_code == 401
    assert (
        await client.get(
            missing_scope, headers={"X-Deck-Operator-Token": operator_token_configured}
        )
    ).status_code == 404
```

- [ ] **Step 2: Run it to confirm every case fails for the right reason**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && python3 -m pytest tests/agent_teams/test_operator_auth.py -q -p no:warnings
```

Expected: failures throughout, because both routes still admit everyone. Read the failure lines before continuing — the unconfigured cases should report `200 != 503` and the wrong-token cases `200 != 401`. A **collection** error instead means `settings.operator_token` is missing (Task 1) or `force`/`reason` do not match the request schema yet (Task 9) — the second is expected and Step 7 addresses it.

- [ ] **Step 3: Append `require_operator` to `deps.py`**

At the end of `backend/app/api/v1/deps.py`:

```python
async def require_operator(
    x_deck_operator_token: str | None = Header(default=None),
) -> None:
    """Authenticate the operator by a secret no agent is given.

    A sibling of require_session_slot, not a variant: that one authenticates an
    agent by what the kernel says about it, this one authenticates the operator
    by a shared secret. Do not merge them -- an agent's own session token must
    never open an operator route.

    Three distinguishable refusals, in this order:

      settings.operator_token empty  -> 503 operator_token_unconfigured
      no header (or an empty one)    -> 401 operator_token_required
      a header that does not match   -> 401 operator_token_invalid

    The empty check comes FIRST and that ordering is load-bearing. hmac.
    compare_digest("", "") returns True, so an implementation that leaves the
    empty setting to the comparison authorizes every caller who sends no header
    -- measured: 200 with the full workspace listing -- while its source still
    reads fail-closed. It refuses a *garbage* header, so a suite that never
    sends an empty one would not notice.

    The comparison is over BYTES because compare_digest raises TypeError on str
    values holding non-ASCII characters, and an unhandled TypeError here is an
    HTTP 500 rather than a refusal (measured).

    settings.operator_token is read at CALL time, not captured at import: the
    settings object is built when config.py is imported, so a module-level
    constant would freeze the empty default and make the 503 unconditional.

    What this credential is worth: the backend and every agent pane share a
    uid, so a determined pane can read backend/.env. This is a boundary against
    an opportunistic adversary, not a co-resident one -- it moves the attack
    from knowing a URL to deliberately reading a 600 file. Do not describe it
    as authenticating a human.
    """
    expected = settings.operator_token
    if not expected:
        raise HTTPException(status_code=503, detail="operator_token_unconfigured")
    if not x_deck_operator_token:
        raise HTTPException(status_code=401, detail="operator_token_required")
    if not hmac.compare_digest(
        x_deck_operator_token.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="operator_token_invalid")
```

**No new imports.** `hmac`, `Header`, `HTTPException` and `settings` all arrived in Step 3 of Task 5. If your editor wants to add one, the file you are editing is not the one Task 5 created.

- [ ] **Step 4: Apply it to the workspace listing**

In `agent_teams.py`, extend the import at `:14`:

```python
from app.api.v1.deps import mail_session, require_operator, require_session_slot
```

That line already exists from Task 7 with two names; add the third. Then the listing at `:554-557`:

```python
async def list_github_workspaces(
    scope_id: int,
    _operator: None = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
```

**Why the listing is gated at all, since Task 9 deletes the `lease_token` it used to project.** Not for the token — after Task 9 no projection carries it, so a rule phrased "any projection carrying `lease_token`" would guard nothing. The listing is gated because it enumerates every workspace's path, lease holder and dispatchability, which is the reconnaissance step for choosing a force-release target, and **no agent workflow in this spec reads it** — agents learn their own workspace from the brief. Gating it costs nothing and removes the survey step. The two routes are gated for *different* reasons: force-release because it mutates and used to leak, the listing because it discloses topology.

- [ ] **Step 5: Apply it to force-release**

At `:676-681`:

```python
async def force_release_github_workspace(
    scope_id: int,
    workspace_id: int,
    request: GithubWorkspaceForceReleaseRequest,
    _operator: None = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
```

Put `_operator` **before** `db` in both signatures, matching Task 7's ordering for `session`. Parameter order does not affect resolution — FastAPI resolves the whole dependency graph before calling the route — but keeping credentials above `db` makes the trust boundary visible at a glance in a file where every other route's first dependency is the database.

- [ ] **Step 6: Add the header to the eight existing call sites**

`tests/agent_teams/test_github_workspace_api.py` now sends the operator header on both guarded routes. Add near the imports:

```python
OPERATOR_TOKEN = "test-operator-token-for-workspace-api"


@pytest.fixture(autouse=True)
def operator_token(monkeypatch):
    """Every guarded call in this file authenticates as the operator.

    autouse because the alternative -- threading a fixture through 19 test
    functions of which 6 need it -- is the kind of edit that silently misses
    one. A test
    that wants to assert a REFUSAL belongs in test_operator_auth.py, which
    owns the matrix; this file is about workspace behaviour, not credentials.
    """
    monkeypatch.setattr(settings, "operator_token", OPERATOR_TOKEN)


OPERATOR_HEADERS = {"X-Deck-Operator-Token": OPERATOR_TOKEN}
```

and `from app.config import settings` to the import block.

Then add `headers=OPERATOR_HEADERS` to exactly these eight calls — the two listing `GET`s and the six force-release `POST`s:

| Line | Call | Note |
|---|---|---|
| `:151` | `client.get(.../workspaces)` | in `test_list_workspaces_derives_all_lease_states` |
| `:171` | `client.get(.../github-scopes/999999/workspaces)` | the 404 assertion in the same test — **this is the one that silently becomes a 401 and still passes nothing**, because the test only asserts `== 404`; without the header it fails, which is the correct signal |
| `:182` | `test_force_release_with_matching_token` | Task 9 renames this test |
| `:207` | `test_force_release_rejects_stale_token` | Task 9 **inverts** this test |
| `:235` | `test_force_release_reports_dirty_paths_and_proceeds` | |
| `:257` | `test_force_release_rejects_unleased_workspace` | |
| `:281` | `test_force_release_reports_clean_unpushed_commits` | |
| `:309` | `test_force_release_requires_token_and_reason` | the parameterized `422` — **without the header this returns `401` and the test fails**, because the dependency runs before body validation. Measured. Task 9 re-authors its parameter list; this task only makes it reach `422` again |

Do **not** add the header to the other eleven `client.post` calls in the file (`:328`, `:357`, `:379`, `:392`, `:409`, `:458`, `:489`, `:517`, `:555`, `:591`, `:620`) or the `GET` at `:657`. Those are workspace *creation*, *reprobe*, *abandon* and the work-item feed — routes this PR does not gate. Adding a header they ignore is harmless but it would misrepresent which routes carry a credential, and a later reader would have no way to tell the deliberate eight from the incidental twelve.

- [ ] **Step 7: Run both test files**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && python3 -m pytest tests/agent_teams/test_operator_auth.py tests/agent_teams/test_github_workspace_api.py -q -p no:warnings
```

Expected: **`test_operator_auth.py` fully passing except the cases that send `{"force": True, ...}`**, which `GithubWorkspaceForceReleaseRequest` does not accept until Task 9 — those return `422` after passing the credential, so the unconfigured (`503`) and refusal (`401`) rows all pass now, and only `test_the_configured_operator_token_is_accepted`'s `assert forced.status_code not in (401, 503)` is affected — and it passes, because `422` is neither.

`test_github_workspace_api.py` should be **fully green at 23 passed** — 19 test functions, 23 collected cases, because two of them are parameterized. Measured at baseline: `23 passed in 1.89s`. If `:171` or `:309` still fails, the header did not land on that call.

**This is the ordering trap in this task**: the credential and the request-body migration are separate tasks, so between them the body of a force-release request is the *old* shape while `test_operator_auth.py` sends the *new* one. That is deliberate — writing the matrix against the old body would mean re-authoring it in Task 9 — and it is why the positive control asserts `not in (401, 503)` rather than `== 200`. **Do not "fix" this by changing the schema here.** That is Task 9, and it ships with its own tests.

- [ ] **Step 8: Prove the ordering claim by mutation**

Reverse the empty check and the comparison in `deps.require_operator` — delete the `if not expected:` block and change the comparison to compare against `expected` unconditionally:

```python
    if not x_deck_operator_token:
        raise HTTPException(status_code=401, detail="operator_token_required")
    if not hmac.compare_digest(
        x_deck_operator_token.encode("utf-8"), settings.operator_token.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="operator_token_invalid")
```

Run `test_unconfigured_install_refuses_with_503_whatever_the_header`. Expected: it **fails on all three parameters** — `401 != 503` for the header cases and for no-header, because this variant still refuses rather than admitting. Now delete the `if not x_deck_operator_token:` block too, so an absent header becomes `""` and reaches the comparison:

```python
    if not hmac.compare_digest(
        (x_deck_operator_token or "").encode("utf-8"),
        settings.operator_token.encode("utf-8"),
    ):
        raise HTTPException(status_code=401, detail="operator_token_invalid")
```

Expected now: the `None` and `""` parameters fail with **`200 != 503`** — an unconfigured install serving the workspace listing to a caller with no credential — while `"anything-at-all"` fails with `401 != 503`. That contrast is the whole point of the two-row split: **the mutant is not a refusal with the wrong status, it is an admission wearing a refusal's shape.**

Restore both blocks by exact string replacement — retype them from Step 3. **Do not `git checkout` the file**: `deps.py` holds Tasks 5 and 7's uncommitted work at this point, and a checkout discards all of it. Re-run the test file and confirm green before moving on.

- [ ] **Step 9: Run the full suite**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && python3 -m pytest tests/ -q -p no:warnings
```

Expected: **`709 passed, 1 failed`** — the 622 baseline plus Tasks 1-8's 87 new collected cases, and the one failure is the pre-existing `test_multi_provider_smoke.py::test_agent_bridge_session_filter_smoke` and **nothing else**.

`test_operator_auth.py` collects **12 cases from 8 test functions**: `test_unconfigured_install_refuses_with_503_whatever_the_header` is parameterized over three headers and `test_near_miss_tokens_are_invalid` over three near misses, so `-q` prints 12 where the file has 8 `def`s. Do not read that gap as duplicated collection.

This is the first task in the plan that gates an existing route, so the full suite matters more here than anywhere before it: any test anywhere that calls the listing or force-release without a credential now gets `401`. Measured, there are exactly eight such call sites and all eight are in `test_github_workspace_api.py` — no other test file references either route. If a third file fails, a route was gated that this task did not intend to gate; **stop and report** rather than adding headers until it goes green.

- [ ] **Step 10: Commit**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1 && git add backend/app/api/v1/deps.py backend/app/api/v1/agent_teams.py backend/tests/agent_teams/test_operator_auth.py backend/tests/agent_teams/test_github_workspace_api.py && git commit -m "feat(teams): require an operator credential on force-release and the listing

agent_teams.py had no authentication at all -- all 27 dependencies were
Depends(get_db) -- so force-release was reachable by any local process, and its
mismatch branch interpolated the live lease token into the response body. Guess,
read the real token out of the refusal, replay it.

require_operator reads X-Deck-Operator-Token and compares it with
hmac.compare_digest against settings.operator_token. Three distinguishable
refusals: 503 operator_token_unconfigured, 401 operator_token_required, 401
operator_token_invalid.

The empty setting is checked BEFORE the comparison, and that ordering is the
whole fix rather than a detail. compare_digest(\"\", \"\") is True, so leaving the
empty case to the comparison makes an unconfigured install serve the full
workspace listing to any caller sending no header, while the source still reads
fail-closed. Measured, that mutant refuses a garbage header, so only the
empty-header case reveals it -- hence a test row for it.

The comparison is over bytes: compare_digest raises TypeError on non-ASCII str,
which reaches the client as a 500 rather than a refusal.

The listing is gated for a different reason than force-release -- it enumerates
every workspace path and lease holder, which is the reconnaissance step for
choosing a force-release target, and no agent workflow reads it.

The credential is a boundary against an opportunistic adversary, not a
co-resident one: the backend and every pane share a uid, so a pane that goes
looking can read backend/.env. It therefore lives in backend/.env and is never
exported -- tmux inherits the backend's environment as its global environment,
which every pane can read back with one command.

Spec: 2026-08-05-distinct-approver-identity-design.md section 3.6a"
```

---

### Task 9: Force-release names an acquisition, not a token

**Files:**
- Modify: `backend/app/models/schemas.py:2255-2258` (`GithubWorkspaceForceReleaseRequest` — replace `expected_lease_token` with `force` + `expected_leased_at`), `:2245` (delete `GithubWorkspaceResponse.lease_token`)
- Modify: `backend/app/services/github_workspace_service.py` (add `force_release_acquisition` immediately after `release`, `:148-165`)
- Modify: `backend/app/api/v1/agent_teams.py:185` (drop the projection), `:676-724` (the force-release route body)
- Test: `backend/tests/agent_teams/test_github_workspace_api.py` (re-author six force-release tests; fix two assertions in the listing test)
- Test: `backend/tests/agent_teams/test_force_release_concurrency.py` (create — the five interleaving cases plus the positive path, the disclosure assertion, and the `force` validation pair)

**Interfaces:**
- Consumes: `require_operator` on the route (Task 8, already in the signature); `OPERATOR_HEADERS` in `test_github_workspace_api.py` (Task 8, Step 6).
- Produces: `github_workspace_service.force_release_acquisition(db, *, workspace_id: int, scope_id: int, item_id: int, expected_leased_at: datetime, lease_token: str | None) -> bool` — `True` when exactly one row was cleared and committed, `False` when zero rows matched and nothing was written. PR1's §4.6a.1 `release_by_owner` is built in this shape and is its sibling, not its caller.
- Produces: `GithubWorkspaceForceReleaseRequest{force: Literal[True], expected_leased_at: datetime, reason: str, requested_by: Optional[str]}`.

**Task 8 shut the door; this task removes the key from under the mat.** Task 8's dependency stops an unauthenticated caller reaching force-release. It does not stop the route *requiring* the operator to replay the agent's live bearer credential, which is why the listing has to project `lease_token` at all, and why the `409` interpolates the current one. Authenticating the operator and then handing them the agent's secret is a password on a door that is still propped open — spec test 21 exists precisely to fail an implementation that does only Task 8.

**And the replacement is not a rename.** `expected_lease_token` → `expected_leased_at` swaps *which value* is compared and leaves the real defect untouched: the comparison happens at the top of the route, the write happens at the bottom, and between them sit two `git` subprocesses. Measured against today's code, with the replacement acquisition landing at the route's own await:

```
   route status (TODAY'S code): 200
   runner calls: ['status', 'rev-list']
   row after: (None, None) *** REPLACEMENT DESTROYED ***
```

The `logger.warning` printed *before* that destruction, so the audit trail records a force-release of `ACQ-1-aaa` while the row that died held `ACQ-2-bbb`. A confidently wrong log is worse than no log.

**So the comparison must *be* the write.** One conditional `UPDATE`, issued after the awaited inspection, whose `WHERE` names every part of what the operator confirmed: the workspace row, its scope, the item, the timestamp the operator sent, and the token the server captured. Zero rows means the world moved and nothing happened.

#### The eight measurements that decide this task's code

**1. The predicate must name the workspace row, because `release()` does not.** `release()` selects `WHERE leased_item_id == item_id` with no workspace and no scope predicate (`github_workspace_service.py:148-152`). The narrow-looking fix — keep `release(db, item_id)` and bolt a `leased_at` check onto it — destroys a lease on a workspace the operator never inspected. Measured, with the item's lease legitimately moving from X to Y during the suspension:

```
1. lease moved: X free, Y holds ON-Y-bbb
2. correct predicate (names X) -> rowcount 0 | Y: (1, 'ON-Y-bbb') SURVIVED
3. MUTANT (item id only)       -> rowcount 1 | Y: (None, None) *** DESTROYED ***
```

Note *how* the test has to set this up: the lease **moves**, it does not duplicate. `UNIQUE(leased_item_id)` (`database.py:319`) refuses a second acquisition outright — measured, `IntegrityError` — so a test that tries to lease the same item on two workspaces at once tests nothing but the constraint. X must release first.

**2. The captured `lease_token` is mandatory, not "a further discriminator".** `leased_at` is a timestamp, not an acquisition identity: measured on this platform, `datetime.utcnow()` returned equal values for back-to-back calls **59 612 times in 200 000 pairs**, and the column has neither a UNIQUE constraint nor any monotonicity guarantee. Driven end to end — a replacement acquisition given the *identical* `leased_at` and a fresh token:

```
4. interleaved replacement, SAME leased_at, new token
  status=409 block_code=lease_changed
  X after: item=1 token=ACQ-2-bbb pid=4242
```

And the mutant that omits the token from the predicate, against the same row: `rowcount 1`, replacement destroyed. This is the one mutant that survives every other case in spec test 22, because the plain interleaving gives the replacement a *later* `leased_at` and a timestamp-only predicate refuses that one correctly.

**3. `synchronize_session` must be `False`, and the default is actively wrong here.** This is the measurement that changed the code rather than confirming it. An ORM-enabled `update()` defaults to `synchronize_session="auto"`, which evaluates the `WHERE` **in memory** against the session's own attributes — and the session's attributes are the *stale* ones the operator inspected. So on the zero-row path the in-memory object is updated as though the release succeeded:

```
synchronize_session=None       rowcount=0  in-memory workspace now reads item=None token=None pid=None
synchronize_session='auto'     rowcount=0  in-memory workspace now reads item=None token=None pid=None
synchronize_session='evaluate' rowcount=0  in-memory workspace now reads item=None token=None pid=None
synchronize_session='fetch'    rowcount=0  in-memory workspace now reads item=1 token='ACQ-1-aaa' pid=4242
synchronize_session=False      rowcount=0  in-memory workspace now reads item=1 token='ACQ-1-aaa' pid=4242
```

Read the first three lines: `rowcount=0` and the object says released. Nothing is written back — measured, the row survives a subsequent `commit()` on all five settings — but any code reading `workspace` after the failed write sees a release that did not happen, and that includes `_workspace_response(workspace)`. `False` is correct because the row is re-read from the database afterwards anyway; `"fetch"` would also be safe and costs an extra `SELECT`.

**4. The route must `refresh` before it responds, and there is a measurement that proves it.** With `synchronize_session=False` the ORM object is deliberately *not* updated by the write, so building the response from it reports the pre-release state. Measured, the same route with and without the refresh:

| | positive-path response body |
|---|---|
| with `await db.refresh(workspace)` | `leased_item_id: None`, `lease_state: available` |
| without | `leased_item_id: 1`, `lease_state: leased` |

The second row is a `200` that tells the operator the workspace is still leased while the database says otherwise. This is the trade the previous measurement makes: turning synchronization off buys correctness on the `409` path and obliges an explicit re-read on the `200` path.

**5. Do not call `db.rollback()` on the `409` path — and this one is about the tests, not the route.** The conditional `UPDATE` wrote nothing, so there is nothing to roll back; `get_db` rolls back on the raised exception anyway (`database.py:52-53`). Adding an explicit rollback expires the session's identity map, and every subsequent ORM attribute read from the *test* then raises:

```
A. explicit rollback:    ORM attr read after 409 RAISED: MissingGreenlet
B. no explicit rollback: ORM attr read after 409: 1 fdcb0d7fd39d388b
```

Both leave the row untouched — the row is what matters and both are correct on that. But under `httpx.ASGITransport` the test session *is* the request session, so an explicit rollback turns `assert workspace.leased_item_id == item.id` into a `MissingGreenlet` crash rather than a passing assertion. The tests below read rows back with raw SQL for the reasons spec test 22 gives, so they survive either choice; the route omits the rollback because it is unnecessary, and this note exists so nobody adds it back "for safety" and breaks the neighbouring suite.

**6. `expected_leased_at` round-trips through the wire exactly, including microseconds.** The operator's only source for the value is the listing, so the two have to agree to the microsecond. Measured, `2026-08-08 12:00:00.123456` stored → `'2026-08-08T12:00:00.123456'` on the wire → parsed by Pydantic back to `datetime(2026, 8, 8, 12, 0, 0, 123456)`, equal to the stored value. No timezone suffix is emitted, and a client that adds one still matches: SQLAlchemy's SQLite bind processor formats an aware datetime by dropping the tzinfo, so `...123456Z` and `...123456+05:00` both bind as `'2026-08-08 12:00:00.123456'`. That last part is a wart worth knowing about rather than a feature to rely on — the `+05:00` case matches a lease it arguably should not — and it is out of scope here because the only client is the listing, which emits naive values. Do not "fix" it by making the column timezone-aware; that is a migration this PR does not have.

**7. `Literal[True]` refuses both `false` and omission, at validation.** Measured on the real model: `{"force": false, ...}` → `ValidationError`, `force` absent → `ValidationError`. Driven through a route, both are `422` with the lease unchanged. No route code reads the field, which is the point — a `force: bool` that the implementation ignores passes every other test in this task.

**8. The `409` names both timestamps, and on one of its two paths there is no second timestamp to name.** §4.6a requires the refusal to name both — "which are not secrets" — so the message needs a *fresh* read of `leased_at`, and `synchronize_session=False` means the ORM object still holds the stale one. A `refresh` on the refusal path supplies it. But `release()` **never clears `leased_at`** (its eight assignments are `leased_item_id`, `released_at`, `lease_token`, the four liveness columns, and `updated_at` — verified by reading `:155-165`), so a workspace released during the inspection still reports the timestamp the operator confirmed. Naming it there would tell the operator their value *matched* while refusing them. Measured, all three shapes, through a route:

```
--- REACQUIRED:     409  "You confirmed leased_at 2026-08-09T17:15:58.687395, but it now
                          reports leased_at 2026-08-09T17:17:28.718209."
                    row after: (1, 'ACQ-2-bbb')     token leaked: False
--- PLAIN RELEASE:  409  "You confirmed leased_at 2026-08-09T17:15:58.749400, but the
                          workspace is no longer leased."
                    row after: (None, None)         token leaked: False
--- POSITIVE:       200  released_item_id=3, leased_item_id=null
                    row after: (None, None)         token leaked: False
```

So the message branches on `leased_item_id is None` after the refresh, not on `leased_at`. And the refresh is what makes measurement 5's finding narrowly true rather than accidental: a `refresh` before the raise leaves the session usable — measured, the neighbouring ORM read returns `1` and `None` on the two refusal paths — whereas a `rollback` before the raise does not.

#### What is deliberately *not* touched

`lease_token` appears in eleven other places and all of them stay:

- `DispatchStatusReport.lease_token` (`schemas.py:2352`) and the three shim sites (`mcp_shim/agent_mail_server.py:608`, `:616`, `:627`) are the **agent's** dispatch-status token — a different field, on a different route, serving `release_by_token` and `touch_owner_contact`. Confirmed by reading the owning model: `:2352` belongs to `DispatchStatusReport`, not to any workspace schema.
- `agent_teams.py:339`, `:364`, `:376` are that same agent path (`/dispatch-status`). §4.6a.1 rewrites `:376`'s `release_by_token` in **PR1**, and it needs the token to keep flowing.
- `github_dispatch_service.py:448-456` and `:878` interpolate the token into the agent's brief. That is how the owner learns its own credential; deleting it would break dispatch.
- `test_github_workspace_service.py:121, 289-311, 413`, `test_github_watcher_service.py:270`, `test_agent_team_api.py:469` set or read the column directly rather than through the deleted projection. Verified: none of them asserts on a response body's `lease_token`.

The frontend reads it nowhere — measured, zero matches for `lease_token` or `leaseToken` under `frontend/src/`. There is no UI to update in this task.

- [ ] **Step 1: Write the failing concurrency test — the four interleavings**

Create `backend/tests/agent_teams/test_force_release_concurrency.py`. This file is separate from `test_github_workspace_api.py` because its fixtures are different in kind: it injects a mutation at the route's own suspension point, and mixing that machinery into the HTTP-contract file makes both harder to read.

```python
"""Spec §3.7 test 22 — the force-release concurrency contract.

Every case here drives a mutation at the route's real suspension point: the
two `git` subprocesses `pending_work` awaits between the operator's inspection
and the release. A test that seeds the replacement *before* the request passes
against a route that compares at the top and writes at the bottom, which is
the exact defect this file exists to catch.
"""
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.config import settings
from app.database import get_db
from app.main import app
from app.models.database import (
    AgentTeamPreset,
    GithubWorkItem,
    GithubWorkspace,
    TeamGithubScope,
)
from app.services.github_workspace_service import github_workspace_service

OPERATOR_TOKEN = "test-operator-token-for-force-release"
OPERATOR_HEADERS = {"X-Deck-Operator-Token": OPERATOR_TOKEN}

# The seven columns release() clears, plus the two timestamps that must agree.
RELEASE_STATE_COLUMNS = (
    "leased_item_id, lease_token, leased_owner_pid, leased_owner_proc_start,"
    " lease_last_owner_contact_at, lease_release_reminded_at, released_at, updated_at"
)


@pytest.fixture(autouse=True)
def operator_token(monkeypatch):
    monkeypatch.setattr(settings, "operator_token", OPERATOR_TOKEN)


@pytest_asyncio.fixture
async def client(db):
    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


class InterleavingRunner:
    """A git runner that runs `hook` at the route's first await.

    `pending_work` awaits self._runner twice for a worktree -- `status
    --porcelain` then `rev-list --count`. Firing on the first call puts the
    mutation strictly between the operator's inspection and the release, which
    is where a real replacement acquisition lands.
    """

    def __init__(self, repo_path: Path, hook=None):
        self.repo_path = repo_path
        self.hook = hook
        self.calls: list[list[str]] = []
        self.status_output = ""
        self.rev_count = "0"

    async def __call__(self, args: list[str]):
        first = not self.calls
        self.calls.append(args)
        if first and self.hook is not None:
            await self.hook()
        path = Path(args[1])
        command = args[2]
        common = self.repo_path / ".git"
        if command == "rev-parse":
            linked = path != self.repo_path
            git_dir = common / "worktrees" / path.name if linked else common
            return 0, f"{git_dir}\n{common}\n{path}\n"
        if command == "status":
            return 0, self.status_output
        if command == "rev-list":
            return 0, f"{self.rev_count}\n"
        return 0, ""


async def _scope(db, repo_path: Path):
    repo_path.mkdir(parents=True, exist_ok=True)
    preset = AgentTeamPreset(name=f"FR {repo_path.name}", description="", created_by="test")
    db.add(preset)
    await db.flush()
    scope = TeamGithubScope(
        preset_id=preset.id,
        repo_owner="owner",
        repo_name=repo_path.name,
        repo_path=str(repo_path),
    )
    db.add(scope)
    await db.commit()
    return scope


async def _leased(db, scope, path: Path):
    """A worktree workspace with every liveness column populated.

    kind="worktree" is load-bearing: pending_work returns (None, None)
    immediately for kind == "primary" with no git call at all, so a primary
    workspace has no suspension point and none of these tests can interleave.
    """
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=1,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="merged",
    )
    db.add(item)
    await db.flush()
    inspected_at = datetime.utcnow() - timedelta(seconds=90)
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(path),
        kind="worktree",
        leased_item_id=item.id,
        leased_at=inspected_at,
        lease_token="ACQ-1-aaa",
        leased_owner_pid=4242,
        leased_owner_proc_start="991122",
        lease_last_owner_contact_at=datetime.utcnow(),
        lease_release_reminded_at=datetime.utcnow(),
    )
    db.add(workspace)
    await db.commit()
    # Capture ids as plain ints. After the request, ORM attribute access on
    # these objects may hit the database from outside a greenlet context.
    return item.id, workspace.id, inspected_at


def _url(scope_id: int, workspace_id: int) -> str:
    return (
        f"/api/v1/agent-teams/github-scopes/{scope_id}/workspaces/"
        f"{workspace_id}/force-release"
    )


async def _row(db, workspace_id: int, columns: str = "leased_item_id, lease_token"):
    """Read the row back with raw SQL.

    Never assert on the ORM object: with expire_on_commit=False the identity
    map can report values the database does not hold, in both directions.
    """
    result = await db.execute(
        text(f"SELECT {columns} FROM github_workspaces WHERE id = :id"),
        {"id": workspace_id},
    )
    return result.one()


@pytest.mark.asyncio
async def test_matching_acquisition_is_released_and_state_fully_cleared(
    client, db, tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    scope = await _scope(db, repo)
    item_id, workspace_id, inspected_at = await _leased(db, scope, tmp_path / "ws")
    monkeypatch.setattr(github_workspace_service, "_runner", InterleavingRunner(repo))

    response = await client.post(
        _url(scope.id, workspace_id),
        json={
            "force": True,
            "expected_leased_at": inspected_at.isoformat(),
            "reason": "owner is unavailable",
            "requested_by": "operator",
        },
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["released_item_id"] == item_id
    # The response must reflect the post-release row, not the object the
    # request inspected.
    assert body["workspace"]["leased_item_id"] is None
    assert body["workspace"]["lease_state"] == "available"

    row = await _row(db, workspace_id, RELEASE_STATE_COLUMNS)
    (
        leased_item_id,
        lease_token,
        owner_pid,
        owner_proc_start,
        owner_contact_at,
        reminded_at,
        released_at,
        updated_at,
    ) = row
    # All seven columns release() clears, enumerated. The ones an implementer
    # drops are the liveness ones, and a NULL leased_item_id beside a stale
    # leased_owner_pid is the row shape §4.6b exists to prevent.
    assert leased_item_id is None
    assert lease_token is None
    assert owner_pid is None
    assert owner_proc_start is None
    assert owner_contact_at is None
    assert reminded_at is None
    assert released_at is not None
    assert released_at == updated_at


@pytest.mark.asyncio
async def test_stale_expected_leased_at_refuses_without_touching_the_lease(
    client, db, tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    scope = await _scope(db, repo)
    item_id, workspace_id, _ = await _leased(db, scope, tmp_path / "ws")
    monkeypatch.setattr(github_workspace_service, "_runner", InterleavingRunner(repo))

    response = await client.post(
        _url(scope.id, workspace_id),
        json={
            "force": True,
            "expected_leased_at": "2020-01-01T00:00:00",
            "reason": "stale value",
        },
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["block_code"] == "lease_changed"
    assert await _row(db, workspace_id) == (item_id, "ACQ-1-aaa")


@pytest.mark.asyncio
async def test_a_replacement_acquired_during_the_inspection_survives(
    client, db, tmp_path, monkeypatch, caplog
):
    """The ABA case. Measured against the pre-Task-9 route: 200, replacement destroyed."""
    repo = tmp_path / "repo"
    scope = await _scope(db, repo)
    item_id, workspace_id, inspected_at = await _leased(db, scope, tmp_path / "ws")

    # Written explicitly rather than taken from utcnow() inside the hook: the
    # assertion below compares against this value's isoformat(), and a
    # microsecond of exactly 0 would make SQLite's stored '.000000' and
    # Python's suffix-less isoformat() disagree.
    replacement_leased_at = inspected_at + timedelta(seconds=30)

    async def replace():
        # The owner released and the item was dispatched again while the
        # operator's request sat in `git status`.
        await db.execute(
            text(
                "UPDATE github_workspaces SET leased_at = :now,"
                " lease_token = 'ACQ-2-bbb' WHERE id = :id"
            ),
            {"now": replacement_leased_at, "id": workspace_id},
        )
        await db.commit()

    monkeypatch.setattr(
        github_workspace_service, "_runner", InterleavingRunner(repo, replace)
    )

    with caplog.at_level("WARNING", logger="app.api.v1.agent_teams"):
        response = await client.post(
            _url(scope.id, workspace_id),
            json={
                "force": True,
                "expected_leased_at": inspected_at.isoformat(),
                "reason": "owner is unavailable",
            },
            headers=OPERATOR_HEADERS,
        )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["block_code"] == "lease_changed"
    # §4.6a: the refusal names both timestamps. The second one has to be the
    # REPLACEMENT's, read fresh -- a message built from the stale ORM object
    # names the operator's own value twice and reads as "your value matched".
    assert inspected_at.isoformat() in detail["message"]
    assert replacement_leased_at.isoformat() in detail["message"]
    # The replacement acquisition is intact -- both the pointer and the token.
    assert await _row(db, workspace_id) == (item_id, "ACQ-2-bbb")
    # And nothing was logged as released. The success line must sit AFTER the
    # write; before it, a force-release that did not happen is recorded as one.
    assert "force-release workspace" not in caplog.text


@pytest.mark.asyncio
async def test_a_replacement_sharing_the_leased_at_still_survives(
    client, db, tmp_path, monkeypatch
):
    """The same-timestamp case: the only one that fails a token-less predicate.

    utcnow() self-collides -- measured 59 612 times in 200 000 back-to-back
    pairs -- and leased_at has neither a UNIQUE constraint nor any
    monotonicity guarantee, so two acquisitions sharing one is not contrived.
    The timestamp is written explicitly rather than waited for.
    """
    repo = tmp_path / "repo"
    scope = await _scope(db, repo)
    item_id, workspace_id, inspected_at = await _leased(db, scope, tmp_path / "ws")

    async def replace_with_same_timestamp():
        await db.execute(
            text(
                "UPDATE github_workspaces SET leased_at = :same,"
                " lease_token = 'ACQ-2-bbb' WHERE id = :id"
            ),
            {"same": inspected_at, "id": workspace_id},
        )
        await db.commit()

    monkeypatch.setattr(
        github_workspace_service,
        "_runner",
        InterleavingRunner(repo, replace_with_same_timestamp),
    )

    response = await client.post(
        _url(scope.id, workspace_id),
        json={
            "force": True,
            "expected_leased_at": inspected_at.isoformat(),
            "reason": "owner is unavailable",
        },
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["block_code"] == "lease_changed"
    assert await _row(db, workspace_id) == (item_id, "ACQ-2-bbb")
    # Microseconds survive the round trip, so the refusal above is the token
    # doing the work rather than a truncated comparison failing for its own
    # unrelated reason.
    (stored_leased_at,) = await _row(db, workspace_id, "leased_at")
    assert stored_leased_at.endswith(f"{inspected_at.microsecond:06d}")


@pytest.mark.asyncio
async def test_an_owner_release_during_the_inspection_refuses_honestly(
    client, db, tmp_path, monkeypatch
):
    """The other refusal branch: the owner released it before the operator's write.

    release() does not clear leased_at, so the row still reports the exact
    timestamp the operator confirmed. A message that names it says "your value
    did not match" while showing a value that did. This asserts the branch.
    """
    repo = tmp_path / "repo"
    scope = await _scope(db, repo)
    _, workspace_id, inspected_at = await _leased(db, scope, tmp_path / "ws")

    async def owner_releases():
        await db.execute(
            text(
                "UPDATE github_workspaces SET leased_item_id = NULL,"
                " lease_token = NULL WHERE id = :id"
            ),
            {"id": workspace_id},
        )
        await db.commit()

    monkeypatch.setattr(
        github_workspace_service, "_runner", InterleavingRunner(repo, owner_releases)
    )

    response = await client.post(
        _url(scope.id, workspace_id),
        json={
            "force": True,
            "expected_leased_at": inspected_at.isoformat(),
            "reason": "owner is unavailable",
        },
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 409
    message = response.json()["detail"]["message"]
    assert response.json()["detail"]["block_code"] == "lease_changed"
    assert "no longer leased" in message
    # leased_at survives release(), so the honest message must NOT present it
    # as the current state.
    assert f"now reports leased_at {inspected_at.isoformat()}" not in message
    (stored_leased_at,) = await _row(db, workspace_id, "leased_at")
    assert stored_leased_at is not None  # the trap this assertion guards


@pytest.mark.asyncio
async def test_a_lease_that_moved_to_another_workspace_survives(
    client, db, tmp_path, monkeypatch
):
    """The cross-workspace case: release()'s selector names no workspace.

    The lease has to MOVE rather than duplicate -- UNIQUE(leased_item_id)
    refuses a second acquisition of the same item outright (measured,
    IntegrityError), so X releases before Y acquires.
    """
    repo = tmp_path / "repo"
    scope = await _scope(db, repo)
    item_id, x_id, inspected_at = await _leased(db, scope, tmp_path / "ws-x")
    y = GithubWorkspace(scope_id=scope.id, path=str(tmp_path / "ws-y"), kind="worktree")
    db.add(y)
    await db.commit()
    y_id = y.id

    async def move_lease_to_y():
        await db.execute(
            text(
                "UPDATE github_workspaces SET leased_item_id = NULL,"
                " lease_token = NULL WHERE id = :id"
            ),
            {"id": x_id},
        )
        await db.execute(
            text(
                "UPDATE github_workspaces SET leased_item_id = :item,"
                " leased_at = :now, lease_token = 'ON-Y-bbb' WHERE id = :id"
            ),
            {"item": item_id, "now": datetime.utcnow(), "id": y_id},
        )
        await db.commit()

    monkeypatch.setattr(
        github_workspace_service, "_runner", InterleavingRunner(repo, move_lease_to_y)
    )

    response = await client.post(
        _url(scope.id, x_id),
        json={
            "force": True,
            "expected_leased_at": inspected_at.isoformat(),
            "reason": "owner is unavailable",
        },
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["block_code"] == "lease_changed"
    # The operator inspected X and confirmed X. Y is a lease they never saw.
    assert await _row(db, y_id) == (item_id, "ON-Y-bbb")


@pytest.mark.asyncio
async def test_the_conflict_body_discloses_no_token(client, db, tmp_path, monkeypatch):
    """Spec test 22's disclosure assertion, over the whole serialised body.

    The live disclosure reaches the wire through _conflict's detail.message
    nesting, so an assertion that reads only a top-level "message" misses it.
    Both the stored token and the value the caller supplied are asserted: an
    attacker's own guess echoed back confirms nothing, but an operator's
    mistyped paste of a real token is still a secret in a log.
    """
    repo = tmp_path / "repo"
    scope = await _scope(db, repo)
    _, workspace_id, _ = await _leased(db, scope, tmp_path / "ws")
    monkeypatch.setattr(github_workspace_service, "_runner", InterleavingRunner(repo))

    response = await client.post(
        _url(scope.id, workspace_id),
        json={
            "force": True,
            "expected_leased_at": "2020-01-01T00:00:00",
            "reason": "ACQ-3-ccc",  # a token-shaped value in a field that is echoed
        },
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 409
    assert "ACQ-1-aaa" not in response.text
    assert "ACQ-3-ccc" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "force_field",
    [{"force": False}, {}],
    ids=["force_false", "force_omitted"],
)
async def test_force_must_be_true_and_the_lease_is_untouched(
    client, db, tmp_path, force_field
):
    """Literal[True] pins the schema, so a route that ignores `force` still fails."""
    scope = await _scope(db, tmp_path / "repo")
    item_id, workspace_id, inspected_at = await _leased(db, scope, tmp_path / "ws")

    response = await client.post(
        _url(scope.id, workspace_id),
        json={
            **force_field,
            "expected_leased_at": inspected_at.isoformat(),
            "reason": "unconfirmed",
        },
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 422
    assert await _row(db, workspace_id) == (item_id, "ACQ-1-aaa")
```

- [ ] **Step 2: Run it and read the failures carefully**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && venv/bin/python3 -m pytest tests/agent_teams/test_force_release_concurrency.py -q -p no:warnings
```

Expected: **9 failed** (8 test functions, 9 cases). The failures are *not* all the same, and the difference matters:

- The six cases sending `force: true` fail with **`422`**, because today's schema requires `expected_lease_token` and rejects the unknown field's absence. `422` here means "the schema has not been migrated yet" — it is not the refusal Step 1's assertions are about.
- `test_force_must_be_true_and_the_lease_is_untouched` **passes for the wrong reason** — today's schema also returns `422`, for the missing `expected_lease_token`. Treat it as red until Step 4, then confirm it still passes.

Do not chase the `422`s individually. They all resolve in Step 3.

- [ ] **Step 3: Migrate the request schema and delete the projection**

In `backend/app/models/schemas.py`, replace `GithubWorkspaceForceReleaseRequest` (`:2255-2258`):

```python
class GithubWorkspaceForceReleaseRequest(BaseModel):
    # Literal[True] rather than bool: an omitted or false `force` must be a
    # validation error, not a branch the route can forget to read.
    force: Literal[True]
    # The acquisition the operator inspected, as shown by the workspace
    # listing. Compared inside the release write, not before it.
    expected_leased_at: datetime
    reason: str
    requested_by: Optional[str] = None
```

`Literal` is already imported (`schemas.py:3`); no import change.

And delete one line from `GithubWorkspaceResponse` (`:2245`):

```python
    lease_token: Optional[str] = None
```

**Delete only that one.** Two other `lease_token: Optional[str] = None` lines exist in this file: `:2256` is the field being replaced above, and `:2352` belongs to `DispatchStatusReport` — the *agent's* dispatch-status token, a different credential on a different route, which PR1 still needs. Verified by reading the owning class.

- [ ] **Step 4: Delete the projection's other half**

In `backend/app/api/v1/agent_teams.py`, remove line `:185` from `_workspace_response`:

```python
        lease_token=workspace.lease_token,
```

The surrounding call keeps every other field. Nothing else in the function changes.

Run the new file again:

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && venv/bin/python3 -m pytest tests/agent_teams/test_force_release_concurrency.py -q -p no:warnings
```

Expected: **2 passed, 7 failed**. The two `force` cases now pass for the right reason (`Literal[True]` refusing at validation), and the seven `force: true` cases fail with `AttributeError: 'GithubWorkspaceForceReleaseRequest' object has no attribute 'expected_lease_token'` — measured, `httpx.ASGITransport` re-raises that rather than turning it into a `500`, so it surfaces as an error rather than an assertion failure. That is the schema and the route disagreeing, which Step 6 fixes.

- [ ] **Step 5: Add the conditional release to the service**

In `backend/app/services/github_workspace_service.py`, add `force_release_acquisition` immediately after `release` (which ends at `:165`) — beside it deliberately, so the two column lists can be read against each other. Add `update` to the existing SQLAlchemy import at `:11`:

```python
from sqlalchemy import select, update
```

```python
    async def force_release_acquisition(
        self,
        db: AsyncSession,
        *,
        workspace_id: int,
        scope_id: int,
        item_id: int,
        expected_leased_at: datetime,
        lease_token: str | None,
    ) -> bool:
        """Clear exactly the acquisition described, or nothing at all.

        `release` selects on `leased_item_id` alone, so a caller that inspects
        a workspace, awaits, and then calls it can clear a lease on a
        different row -- the item's lease may have moved in between. Here the
        comparison IS the write: every part of what the caller inspected is in
        the WHERE clause, so a lease that changed under them cannot be
        destroyed by a confirmation of the one that is gone.

        Returns True when one row was cleared and committed, False when the
        acquisition no longer exists. Exactly-one is a guarantee rather than a
        hope because `id` is the primary key.
        """
        now = datetime.utcnow()
        result = await db.execute(
            update(GithubWorkspace)
            .where(
                GithubWorkspace.id == workspace_id,
                GithubWorkspace.scope_id == scope_id,
                GithubWorkspace.leased_item_id == item_id,
                GithubWorkspace.leased_at == expected_leased_at,
                GithubWorkspace.lease_token == lease_token,
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
            # synchronize_session's default evaluates this WHERE in memory
            # against the session's own -- stale -- attributes, which on the
            # zero-row path marks the in-memory workspace released while the
            # row is still leased. Callers re-read the row instead.
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            return False
        await db.commit()
        return True
```

**Two review points, neither of which has a test.**

1. `GithubWorkspace.lease_token == lease_token` with `lease_token=None` compiles to **`IS NULL`**, not `= NULL` — measured, SQLAlchemy rewrites the operator when the right-hand side is `None` at compile time, so it *matches* a row whose stored token is NULL. That is harmless here (`acquire` always sets a token at `:130`, so the row shape is unreachable through the normal path) but it is the opposite of what a reader who knows SQL's `NULL = NULL` will assume, and it would be a real hole for any caller that could be induced to capture `None`. Do **not** switch to `is_(None)` or a null-safe operator: leave the `==` and leave this note. §4.6a.1's `release_by_owner` in PR1 inherits the same consideration.
2. The `where()` takes five positional criteria, which SQLAlchemy `AND`s together. Do not "simplify" any of the five away. Each has a measured mutant: dropping `id`/`scope_id` destroys another workspace's lease, dropping `leased_at` defeats the whole point, dropping `lease_token` fails only the same-timestamp case, and dropping `leased_item_id` releases an already-free row as though it had been leased.

- [ ] **Step 6: Rewrite the route body**

Replace the body of `force_release_github_workspace` in `backend/app/api/v1/agent_teams.py` (`:682-724`, everything after the signature Task 8 already updated). The signature itself is unchanged:

```python
async def force_release_github_workspace(
    scope_id: int,
    workspace_id: int,
    request: GithubWorkspaceForceReleaseRequest,
    _operator: None = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    scope = await db.get(TeamGithubScope, scope_id)
    if scope is None:
        raise HTTPException(status_code=404, detail="GitHub scope not found")
    workspace = await db.get(GithubWorkspace, workspace_id)
    if workspace is None or workspace.scope_id != scope_id:
        raise HTTPException(status_code=404, detail="GitHub workspace not found")
    if workspace.leased_item_id is None:
        raise _conflict(
            "Workspace is not leased",
            block_code="workspace_not_leased",
        )

    # Capture the acquisition being confirmed BEFORE the await. The token is
    # captured server-side and never returned to the operator -- requiring
    # them to replay it is what made the projection necessary in the first
    # place.
    released_item_id = workspace.leased_item_id
    inspected_lease_token = workspace.lease_token

    # Both risk signals. The operator override reports potential loss but
    # deliberately does not gate on it, and after this await everything read
    # above may be stale -- which is why the release re-checks it in its own
    # WHERE clause rather than trusting what was read here.
    discarded_paths, unpushed_commits = await github_workspace_service.pending_work(
        scope, workspace
    )

    released = await github_workspace_service.force_release_acquisition(
        db,
        workspace_id=workspace_id,
        scope_id=scope_id,
        item_id=released_item_id,
        expected_leased_at=request.expected_leased_at,
        lease_token=inspected_lease_token,
    )
    if not released:
        # A fresh read, because the conditional write deliberately does not
        # update the identity map -- and §4.6a requires the refusal to name
        # both timestamps, which are not secrets.
        await db.refresh(workspace)
        if workspace.leased_item_id is None:
            current = "the workspace is no longer leased"
        else:
            # release() does not clear leased_at, so this branch is the only
            # one where a stored timestamp means what the operator will read
            # it to mean.
            current = f"it now reports leased_at {workspace.leased_at.isoformat()}"
        raise _conflict(
            "The workspace lease changed between inspection and release, so "
            f"nothing was released. You confirmed leased_at "
            f"{request.expected_leased_at.isoformat()}, but {current}. "
            "Refresh the workspace and confirm again.",
            block_code="lease_changed",
        )

    # After the write, never before it: a log line emitted ahead of the
    # release records a force-release that may not have happened.
    logger.warning(
        "force-release workspace %s (item %s) by %s: %s; discarding: %s dirty "
        "path(s), %s unpushed commit(s)",
        workspace_id,
        released_item_id,
        request.requested_by or "unknown",
        request.reason,
        len((discarded_paths or "").splitlines()),
        unpushed_commits if unpushed_commits is not None else "unknown",
    )
    # The conditional write does not update the identity map, so the response
    # must be built from a re-read row rather than the object inspected above.
    await db.refresh(workspace)
    return GithubWorkspaceForceReleaseResponse(
        workspace=_workspace_response(workspace),
        released_item_id=released_item_id,
        discarded_paths=discarded_paths,
        unpushed_commits=unpushed_commits,
    )
```

Five things to get right, each with a measurement behind it:

1. **No `await db.rollback()` on the `409` path** — a `refresh`, not a `rollback`. Nothing was written, and `get_db` rolls back on the raised exception anyway (`database.py:52-53`). An explicit rollback expires the identity map, and because the test session *is* the request session under `ASGITransport`, every later ORM attribute read in the neighbouring suite raises `MissingGreenlet`. Measured: with the `refresh` and no `rollback`, the neighbouring read returns cleanly on both refusal paths.
2. **Both `refresh` calls are mandatory, for different reasons.** The `200`-path one: without it the body reports `leased_item_id: 1` / `lease_state: "leased"` — a success response claiming the workspace is still held. The `409`-path one: without it the message names the operator's own value twice, since the stale ORM `leased_at` *is* `expected_leased_at`.
3. **The refusal branches on `leased_item_id`, not on `leased_at`.** `release()` leaves `leased_at` populated, so the "released during the inspection" case has no honest second timestamp to name.
4. **`workspace_id` and `scope_id` are the path parameters**, not `workspace.id` / `workspace.scope_id`. Same values, but reading them off a possibly-stale ORM object in the predicate that exists to defeat staleness reads as a mistake even where it isn't.
5. **The refusal names no token.** Two timestamps and nothing else; `request.reason` is not echoed either.

- [ ] **Step 7: Run the concurrency file — expect green**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && venv/bin/python3 -m pytest tests/agent_teams/test_force_release_concurrency.py -q -p no:warnings
```

Expected: **9 passed**.

- [ ] **Step 8: Re-author the six force-release tests in the existing file**

`backend/tests/agent_teams/test_github_workspace_api.py` still sends `expected_lease_token`. Six call sites migrate. Task 8 already added `headers=OPERATOR_HEADERS` to each of them; keep it.

Replace each body's `"expected_lease_token": "lease-current"` with `"force": True, "expected_leased_at": <the workspace's leased_at>`. The helper `_leased_workspace` (`:87-107`) sets `leased_at=datetime.utcnow() - timedelta(seconds=90)` but does not return it, so **change the helper to return it** rather than recomputing an approximation in six places — a recomputed `utcnow() - 90s` will not match to the microsecond and every test would fail with `409 lease_changed`:

```python
async def _leased_workspace(db, scope, path: Path, *, token="lease-current"):
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=1,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="merged",
    )
    db.add(item)
    await db.flush()
    leased_at = datetime.utcnow() - timedelta(seconds=90)
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(path),
        leased_item_id=item.id,
        leased_at=leased_at,
        lease_token=token,
    )
    db.add(workspace)
    await db.commit()
    return item, workspace, leased_at
```

Every caller of `_leased_workspace` in the file now unpacks three values. There are five call sites — `:179`, `:204`, `:230`, `:276`, `:307` — and the three that do not need the item use `_, workspace, leased_at = ...`. **Grep for them rather than trusting this list**; a missed one fails with `ValueError: too many values to unpack`, which is loud but costs a test run each:

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && grep -n "_leased_workspace(" tests/agent_teams/test_github_workspace_api.py
```

Then the six bodies. Five are a mechanical swap, e.g. `test_force_release_with_matching_token` (`:176`, and rename it — it no longer names a token):

```python
@pytest.mark.asyncio
async def test_force_release_with_matching_acquisition(client, db, tmp_path, monkeypatch):
    repo_path = tmp_path / "repo"
    _, scope = await _scope(db, repo_path)
    item, workspace, leased_at = await _leased_workspace(db, scope, tmp_path / "ws")
    monkeypatch.setattr(github_workspace_service, "_runner", ApiGitRunner(repo_path))

    response = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/workspaces/"
        f"{workspace.id}/force-release",
        json={
            "force": True,
            "expected_leased_at": leased_at.isoformat(),
            "reason": "owner is unavailable",
            "requested_by": "operator",
        },
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["released_item_id"] == item.id
    assert body["workspace"]["leased_item_id"] is None
    assert "lease_token" not in body["workspace"]
    await db.refresh(workspace)
    assert workspace.leased_item_id is None
```

The `assert "lease_token" not in body["workspace"]` line is spec test 21's schema assertion; add it here and in the listing test at Step 9.

**One of the five needs more than a swap.** `test_force_release_rejects_unleased_workspace` (`:251`) creates its workspace inline rather than through the helper, so it has no `leased_at` to send — and `expected_leased_at` is now required, so a body without it returns `422` and the test stops proving anything about `workspace_not_leased`. Send an arbitrary timestamp; the route refuses on the unleased check before the predicate is ever built:

```python
        json={
            "force": True,
            "expected_leased_at": "2026-08-08T12:00:00",
            "reason": "nothing owns it",
        },
```

This test also asserts the *ordering* of the two refusals — `workspace_not_leased` wins over `lease_changed` — which matters because both are `409` and only the block code distinguishes them.

**The sixth is inverted, not swapped.** `test_force_release_rejects_stale_token` (`:201`) asserts that the refusal *contains* both tokens — it is the test that pins the disclosure this task deletes. Replace it wholesale:

```python
@pytest.mark.asyncio
async def test_force_release_refusal_names_no_lease_token(
    client, db, tmp_path, monkeypatch
):
    """The old version asserted the 409 echoed both tokens; that WAS the leak."""
    repo_path = tmp_path / "repo"
    _, scope = await _scope(db, repo_path)
    item, workspace, _ = await _leased_workspace(db, scope, tmp_path / "ws")
    monkeypatch.setattr(github_workspace_service, "_runner", ApiGitRunner(repo_path))

    response = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/workspaces/"
        f"{workspace.id}/force-release",
        json={
            "force": True,
            "expected_leased_at": "2020-01-01T00:00:00",
            "reason": "owner is unavailable",
        },
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["block_code"] == "lease_changed"
    assert "lease-current" not in response.text
    await db.refresh(workspace)
    assert workspace.leased_item_id == item.id
```

Finally, the parameterized `test_force_release_requires_token_and_reason` (`:305`) parameterizes over the old field. Its cases become "missing `reason`" and "missing `expected_leased_at`", and its name changes:

```python
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"force": True, "expected_leased_at": "2026-08-08T12:00:00"},
        {"force": True, "reason": "missing the acquisition"},
    ],
    ids=["no_reason", "no_expected_leased_at"],
)
async def test_force_release_requires_reason_and_acquisition(
    client, db, tmp_path, body
):
    _, scope = await _scope(db, tmp_path / "repo")
    _, workspace, _ = await _leased_workspace(db, scope, tmp_path / "ws")

    response = await client.post(
        f"/api/v1/agent-teams/github-scopes/{scope.id}/workspaces/"
        f"{workspace.id}/force-release",
        json=body,
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 422
```

The `headers=OPERATOR_HEADERS` is what lets this reach `422` at all — Task 8 measured that the dependency runs *before* body validation, so without the header both cases return `401`.

- [ ] **Step 9: Fix the listing test's two `lease_token` assertions**

Same file, `test_list_workspaces_derives_all_lease_states` (`:111-172`). Two assertions read the deleted key. Line `:163`:

```python
    assert rows[0]["lease_token"] is None
```

and line `:167`:

```python
    assert rows[1]["lease_token"] == "lease-visible"
```

Replace **both** with one assertion that the key is gone from every row — which is the property spec test 21 actually states, and is stronger than either:

```python
    assert all("lease_token" not in row for row in rows)
```

Put it immediately after the `lease_state` list assertion (`:159-165` region), and delete the two original lines. Keep every other assertion in the test, including the `lease_last_owner_contact_at` and `lease_age_seconds` ones on the same rows — those columns stay projected.

- [ ] **Step 10: Run the workspace API file, then both files together**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && venv/bin/python3 -m pytest tests/agent_teams/test_github_workspace_api.py tests/agent_teams/test_force_release_concurrency.py -q -p no:warnings
```

Expected: **32 passed** — 23 in the migrated file (19 test functions, 23 collected cases; this task re-authors tests without changing either count, since the parameterization stays at two cases) and 9 in the new one (8 test functions, 9 cases — `test_force_must_be_true_and_the_lease_is_untouched` is parameterized over two).

- [ ] **Step 11: Mutate the predicate and the route eight ways, and watch the right test fail**

This is the step that proves the tests have discriminating power rather than merely passing. Apply each mutation to `force_release_acquisition`'s `where()`, run the concurrency file, restore, and move on. **Restore by exact string replacement — never `git checkout`**, because `github_workspace_service.py` may hold uncommitted work from earlier tasks.

| Mutation | Must fail |
|---|---|
| delete `GithubWorkspace.lease_token == lease_token` | `test_a_replacement_sharing_the_leased_at_still_survives` **only** — measured, the later-timestamp interleaving still refuses correctly, so this is the single row with power over it |
| delete `GithubWorkspace.leased_at == expected_leased_at` | `test_stale_expected_leased_at_refuses_without_touching_the_lease` and the two interleavings |
| delete both `GithubWorkspace.id ==` and `GithubWorkspace.scope_id ==` | `test_a_lease_that_moved_to_another_workspace_survives` |
| replace the whole call with `await github_workspace_service.release(db, released_item_id); released = True` | all four concurrency tests |
| move the `logger.warning` back above the release call | `test_a_replacement_acquired_during_the_inspection_survives` (its `caplog` assertion) |
| delete the `await db.refresh(workspace)` on the **409** path | `test_a_replacement_acquired_during_the_inspection_survives` — the message then names `expected_leased_at` twice, so its `replacement_leased_at.isoformat() in message` assertion fails |
| delete the `await db.refresh(workspace)` on the **200** path | `test_matching_acquisition_is_released_and_state_fully_cleared` (`leased_item_id is None` / `lease_state == "available"` in the body) |
| always take the `f"it now reports leased_at …"` branch, dropping the `leased_item_id is None` check | `test_an_owner_release_during_the_inspection_refuses_honestly` — and this is the mutant a reviewer reading the branch will not see, because the value it names is present and plausible |

If any mutation leaves the file green, the test is not testing what its name says. Stop and fix the test before continuing.

Then the two schema mutations, which are the ones a reviewer cannot see by reading:

| Mutation | Must fail |
|---|---|
| `force: bool` instead of `force: Literal[True]` | both `test_force_must_be_true_and_the_lease_is_untouched` cases |
| restore `lease_token` to `GithubWorkspaceResponse` and `_workspace_response` | the listing test's `all("lease_token" not in row ...)` and the two `not in body["workspace"]` assertions |

- [ ] **Step 12: Run the full agent-team and mail suites, then the whole suite**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && venv/bin/python3 -m pytest tests/agent_teams/ tests/agent_mail/ -q -p no:warnings
```

Expected: `547 passed` (538 after Task 8 + this task's 9). Nothing should have *dropped* — this task re-authors six tests in `test_github_workspace_api.py` and adds none there, so that file stays at 23.

Then the whole suite, because this task changes a response schema that other files may read:

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && venv/bin/python3 -m pytest tests/ -q -p no:warnings
```

Measured baseline on a clean tree at `4810c1b`: **622 passed, 1 failed**. The one failure is `tests/test_multi_provider_smoke.py::test_agent_bridge_session_filter_smoke` (`assert [] == [None, 'codex-cli']`) — pre-existing and unrelated to this spec. Tasks 1-9 add 96 collected cases on top of that baseline, so expect **718 passed, 1 failed** here, and treat any *second* failure as this task's, most likely a test reading `lease_token` off a workspace response body that the enumeration above missed. Report it and fix it here; do not "fix" the smoke test.

- [ ] **Step 13: Commit**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1 && git add backend/app/models/schemas.py backend/app/services/github_workspace_service.py backend/app/api/v1/agent_teams.py backend/tests/agent_teams/test_github_workspace_api.py backend/tests/agent_teams/test_force_release_concurrency.py && git commit -m "feat(teams): force-release names an acquisition, and the comparison is the write

Task 8 authenticated the operator. The route still required them to replay the
agent's live lease token, which is why the workspace listing projected it and
why the 409 interpolated the current one. A password on a door that is still
propped open: expected_lease_token is deleted, and with it the projection on
GithubWorkspaceResponse and _workspace_response.

Its replacement is not a rename. The old route compared at the top, awaited two
git subprocesses, then called release(db, item_id) -- so everything the check
established was stale by the time the write happened, and release() selects on
leased_item_id alone with no workspace or scope predicate. Measured: a
replacement acquisition taken during the inspection was destroyed, and the
success log line printed before the destruction, recording a force-release of a
lease that was already gone.

So the comparison IS the write. force_release_acquisition issues one
conditional UPDATE after the awaited inspection, predicated on workspace id,
scope id, the captured leased_item_id, the operator's expected_leased_at, and
the server-captured lease_token. Zero rows means the world moved: 409
lease_changed, the lease untouched, no success log. Exactly one row is a
guarantee because id is the primary key.

The captured token is mandatory rather than a further discriminator. leased_at
is a timestamp, not an acquisition identity -- utcnow() self-collided 59 612
times in 200 000 back-to-back pairs, and the column has neither a UNIQUE
constraint nor any monotonicity guarantee. A predicate without the token
refuses a later-timestamped replacement correctly and destroys a
same-timestamped one, which is why that case is its own test.

synchronize_session is False deliberately. The default evaluates the WHERE in
memory against the session's own stale attributes, which on the zero-row path
marks the in-memory workspace released while the row is still leased -- so the
route re-reads the row on both paths before it answers.

The refusal names both timestamps and no token, and it branches on
leased_item_id rather than on leased_at, because release() does not clear
leased_at: a workspace freed during the inspection still reports the exact
value the operator confirmed, so naming it would say "your value did not
match" while showing a value that did.

force is Literal[True]: omitted or false is a validation error rather than a
branch the route can forget to read.

Spec: 2026-08-05-distinct-approver-identity-design.md section 4.6a"
```

---

### Task 10: The operator credential reaches the UI, because the actor token cannot

**Files:**
- Modify: `backend/app/api/v1/deps.py` (`mail_session`, `require_mail_session`, `require_session_slot`, `derive_member_id` — all four from Task 5)
- Modify: `backend/app/api/v1/agent_mail.py` (`mark_read`, `ack_message`, `agent_inbox` — a `None`-member guard each, per Step 6)
- Modify: `backend/tests/agent_mail/test_dispatch_status_tool.py` (one case, per Step 9 — the widened union reaches this route through `mail_session`)
- Create: `frontend/src/lib/operatorToken.ts`
- Modify: `frontend/src/lib/api.ts` (`apiClient`, `:99-131`)
- Modify: `frontend/src/features/agent-mail/api.ts` (`sendAgentMailMessage` `:28-33`, `ackAgentMailMessage` `:73-78`, `markAgentMailRead` `:57-62`)
- Create: `frontend/src/features/config/OperatorTokenCard.tsx`
- Modify: `frontend/src/features/config/ConfigViewerPage.tsx` (mount the card beside the three Codex cards)
- Test: `backend/tests/agent_mail/test_operator_mail_writes.py` (**create**)
- Modify: `backend/tests/agent_mail/test_capability_tokens.py` (Task 5's file — two added cases)

**Interfaces:**
- Consumes: `mail_session` and `derive_member_id` from Task 5; `settings.operator_token` from Task 1; the `X-Deck-Operator-Token` header name and the three refusal codes from Task 8's `require_operator`.
- Produces:
  - `OperatorPrincipal` — a module-level sentinel class in `deps.py`, exported so Task 5's callers can type the union. `mail_session` now returns `MailAgentSession | OperatorPrincipal | None`.
  - `operatorToken(): string | null` and `setOperatorToken(value: string | null): void` in `frontend/src/lib/operatorToken.ts`.
  - No new routes and no new response fields. PR1's `POST /agent-mail/decisions` (§4.3a) consumes the same `mail_session` union.

**The spec is internally contradictory here, and the measured half wins.** §3.6 says the UI should authenticate as an **external actor** and that "the ack path uses the actor ack endpoint that already exists, so no new route is needed." §3.6a, written later and against measurements, says "**the external-actor token cannot be the operator credential**" because `POST /external/agent-mail/actors` gates only on `_is_loopback_request` and an agent pane is a loopback caller. Both cannot hold. §3.6a is the section with measurements behind it, and four more measurements below show §3.6's mechanism does not even reach the UI's writes. So this task implements §3.6's *requirement* — the UI writes without a session token — using §3.6a's *credential*, the operator token Task 8 already ships.

**Why the external routes cannot serve this UI, in three refutations.** Each was driven through the real ASGI app; none is an inference from reading.

*First, the ack route refuses.* `POST /external/agent-mail/requests/{id}/ack` reaches `acknowledge_external_request`, which opens with `if root.sender_actor_id != actor.id: raise ValueError("External actors can only acknowledge requests they created")` (`external_agent_mail_service.py:339-340`). The UI acks messages **agents** created, whose `sender_actor_id` is NULL. Measured: `400`. Spec §3.6's closing bullet is refuted by its own cited line number.

*Second, the reply route refuses for the same reason.* `reply_in_thread` (`:255-256`) carries the identical check with "reply in threads they created." The UI replies in agent-created threads. Measured: `400`.

*Third — and this is the one that decides the design — the UI's reply is not expressible as an actor write at all.* `ThreadDialog.tsx:152-156` chooses `kind` by comparing the operator-selected sender against the thread root: `root.recipient_member_id === senderId ? 'answer' : 'message'`. And `send_message` requires exactly that agreement — `if root.recipient_member_id != request.sender_member_id: raise ValueError("only the context request recipient can answer it")` (`agent_mail_service.py:859-860`). Measured, an `answer` posted with no `sender_member_id` returns **`400 "only the context request recipient can answer it"`**, and the root stays `pending`. An actor write lands in `sender_actor_id` and leaves `sender_member_id` NULL **by construction**, so no actor token — per-tab or otherwise — can post the UI's answer. The reply path needs a **member sender**, which is the one thing the external routes are built never to accept.

**And a member-sender route gated on an actor token would be a hole, not a fix.** This is the trap to see before writing any code. Measured end to end:

```
POST /api/v1/external/agent-mail/actors (NO credential) -> 200
  token minted: len 43
  GET /actors/me with it -> 200, kind='supervisor'
```

Any pane mints a "supervisor" actor in one unauthenticated call. Today that token is harmless *because* the external schemas have no `sender_member_id` — measured, passing one is silently ignored and the row still stores `(sender_member_id=None, sender_actor_id=1)`. A new route that accepted a member sender on an actor token would convert a bounded credential into an unbounded one, and PR1 is precisely where that matters: §4.3 rule 4 accepts an approval only from an `answer` whose `sender_member_id == leader_member.id`. Gating a member-sender write on a token every agent can mint hands every agent the leader's signature. **The operator token is the only credential in this system that an agent cannot obtain**, which is the entire reason §3.6a introduced it.

**So the change is one union in one dependency, not a route.** `mail_session` learns a second credential; `derive_member_id` learns a third caller shape. The four write routes Task 5 already touched need no edit — they call these two functions and nothing else.

#### The five measurements that decide this task's code

**1. One dependency serves all three UI writes, under enforcement, with no new route.** A faithful stand-in for Task 5's `mail_session` — extended exactly as Step 1 extends it — driven against the three writes `ThreadDialog` and `AgentMailPage` actually perform:

```
=== ENFORCED, WITH the operator header
  compose  (no sender at all)   -> 200 sender=(None, None)
  reply kind=answer as bravo    -> 200 sender_member=2
     root request_status -> answered
  ack the answer as alpha       -> 200
     root status after ack -> acknowledged
     answer receipt read_at -> [(1, 1)]
  ack the handoff as bravo      -> 200
     handoff status / receipt -> [('acknowledged', 1, 1)]

=== ENFORCED, WITHOUT the header
  answer as bravo, no header              -> 401 session_token_required
  ack handoff bravo, no header            -> 401 session_token_required
  answer as bravo, wrong operator token   -> 401 operator_token_invalid
  ack handoff bravo, wrong operator token -> 401 operator_token_invalid
```

Both ack shapes the UI can reach are covered, and they are genuinely different rows: `answerAckMember` acks the **answer** (`ThreadDialog.tsx:132`), `handoffAckMember` acks the **root** (`:126-128`). Both flip `request_status` to `acknowledged` and both write `read_at` **and** `acked_at` on the acking member's receipt — the field `_brief_delivered` reads. That is what Task 5's own note says an unauthenticated ack must not be able to do, and it is why the operator path has to be authenticated rather than merely left open.

**2. Compose stores `(NULL, NULL)` today, so the operator path is strictly more attribution — but only if the UI keeps sending no sender.** Measured against the member route with exactly the body `ComposeDialog.tsx:150-157` builds, which contains no `sender_member_id` key at all:

```
message          -> 200  row(sender_member,sender_actor)=(None, None)
broadcast        -> 200  row(sender_member,sender_actor)=(None, None)
context_request  -> 200  row(sender_member,sender_actor)=(None, None)
handoff          -> 200  row(sender_member,sender_actor)=(None, None)
```

So today every operator-composed message is anonymous. Keep it that way: `ComposeDialog` must **not** gain a sender field in this task. §3.6's consequence that "an operator-authored message has `sender_member_id = NULL`, so it can never be mistaken for the leader's approval" already holds for compose, and PR1's §4.3 depends on it. The reply path is different and deliberately so — there the operator *chooses* a member, and that is a pre-existing capability this task authenticates rather than creates.

**3. `settings.operator_token` must be read at call time here too, for Task 8's measured reason.** `settings` is constructed at import (`config.py:57`), so a module-level capture in `deps.py` would freeze the empty default and make every operator mail write a `503`. The same `monkeypatch.setattr(settings, "operator_token", ...)` Task 8's fixtures use is what makes this task's tests possible.

**4. The empty-setting hole needs two mutations, not one, so one test cannot catch it.** `hmac.compare_digest("", "")` is `True`, and Task 8 closes that trap for `require_operator`. Here the trap has a different shape, and measuring it changed both this task's comment and its test. Driven through a real route in `mail_session`'s exact form, with `operator_token = ""` and enforcement on:

| | no header | empty header | wrong header |
|---|---|---|---|
| correct: truthy guard + `503` check | `401 session_token_required` | `401 session_token_required` | `503 operator_token_unconfigured` |
| **A:** the `503` check deleted | `401 session_token_required` | `401 session_token_required` | `401 operator_token_invalid` |
| **B:** guard widened to `is not None` | `401 session_token_required` | `503 operator_token_unconfigured` | `503 operator_token_unconfigured` |
| **A + B** | `401 session_token_required` | **`200` — authorized** | `401 operator_token_invalid` |

So it is the **truthy guard**, not the `503` check, that keeps an empty header out of the comparison: `if x_deck_operator_token:` is falsy on `""`, so an empty header falls through to the enforcement refusal. Deleting the `503` check *alone opens nothing* — it only degrades the diagnosis from `operator_token_unconfigured` to `operator_token_invalid`. The hole needs both mutations together.

This is the reason the first draft of this task's test was worthless. An assertion of the form `status_code in (401, 503)` passes against A, against B, and against correct code — it tests that *something* refused, and all three refuse. **The codes are what differ, so the codes are what the test must name.** Two cases pin the two mutations: a *wrong* header against an empty setting must be `503` (kills A), and an *empty* header against an empty setting must be `401 session_token_required` (kills B, and A+B with it).

**5. The comparison is over bytes.** Re-measured here rather than inherited: Task 8 established that `hmac.compare_digest` raises `TypeError` on `str` values holding non-ASCII characters, and that driven through a real route this is **HTTP 500**, not a refusal. A header can carry a `latin-1` byte. `.encode("utf-8")` on both sides is not defensive styling; it is the difference between `401` and an unhandled exception.

#### What is deliberately *not* touched

- **No new backend route.** §3.6 predicted "no new route is needed" for the wrong reason and reached the right conclusion. The UI's three writes are three of the four routes Task 5 already guards.
- **`ComposeDialog.tsx` gains nothing.** See measurement 2.
- **`fetchAgentMailThread` and the other read paths stay open.** Task 5 gates writes, not reads; `mail_session` is not applied to `GET /messages/{id}/thread`, so the UI's thread view keeps working with no credential. Gating reads is not in this spec.
- **`markAgentMailRead` and `fetchAgentMailInbox` have zero callers** — grepped across `src/`. They still get the header, because leaving one write helper without it is how a future caller acquires a silent `401`.
- **Per-tab actor keys, `sessionStorage`, `crypto.randomUUID`, the `401` re-provision, the actor-row accumulation note.** All of §3.6's provisioning machinery is dropped: it exists to obtain a credential this task does not use. Recorded here so a reviewer comparing plan to spec sees a decision rather than an omission.
- **The `deck-ui-*` actor pruning note (§3.6's "one consequence to accept")** becomes moot for the same reason. No `deck-ui-*` actors are ever created.

- [ ] **Step 1: Write the failing test — the operator credential on the three UI writes**

Create `backend/tests/agent_mail/test_operator_mail_writes.py`. This file exists because §3.6's write paths have **no** test today, which is exactly why its two false claims survived twelve revisions of review.

```python
"""Task 10 -- the operator credential on the UI's mail writes.

Spec 3.6 requires the UI to write without a session token; spec 3.6a requires
the credential to be one an agent cannot mint. This file pins both halves: the
operator header works, and everything an agent can present does not.
"""
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models.database import MailTeamMember

OPERATOR_TOKEN = "0f3c9a71b25e4d8fa6c1e07b9d24aa5b1c3d5e7f9a1b3c5d7e9f1a3b5c7d9e1f"
OP = {"X-Deck-Operator-Token": OPERATOR_TOKEN}


@pytest_asyncio.fixture
async def client_and_db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db:
        async def override():
            yield db

        app.dependency_overrides[get_db] = override
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, db
        app.dependency_overrides.clear()
    await engine.dispose()


@pytest.fixture
def enforced(monkeypatch):
    """Both settings on: this is the state PR0's rollout ends in."""
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    monkeypatch.setattr(settings, "operator_token", OPERATOR_TOKEN)
    return OPERATOR_TOKEN


async def _member(db, name):
    """No member-creation route exists; the ORM is the only way in."""
    member = MailTeamMember(
        identity_key=f"repo:{name}",
        repo_id=name,
        repo_path=f"/tmp/{name}",
        repo_name=name,
        display_name=name,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


@pytest.mark.asyncio
async def test_operator_composes_anonymously(client_and_db, enforced):
    """Compose is exactly ComposeDialog's body: no sender key at all.

    The stored row must keep sender_member_id NULL. PR1's section 4.3 relies on
    an operator-composed message being unable to look like a leader approval,
    and that property comes from this absence, not from a check.
    """
    client, db = client_and_db
    recipient = await _member(db, "bravo")

    response = await client.post(
        "/api/v1/agent-mail/messages",
        headers=OP,
        json={
            "kind": "message",
            "recipient_member_id": recipient.id,
            "subject": "from the UI",
            "body_markdown": "hello",
            "payload": None,
        },
    )

    assert response.status_code == 200, response.text
    row = (
        await db.execute(
            text(
                "SELECT sender_member_id, sender_actor_id FROM mail_messages "
                "WHERE id = :i"
            ),
            {"i": response.json()["id"]},
        )
    ).one()
    assert row == (None, None)


@pytest.mark.asyncio
async def test_operator_answers_as_the_designated_recipient(client_and_db, enforced):
    """The reply path, which no actor token can express.

    kind='answer' is accepted only when sender_member_id equals the root's
    recipient_member_id, so the operator must be able to name a member. This is
    the measurement that ruled out the external routes.
    """
    client, db = client_and_db
    asker = await _member(db, "alpha")
    answerer = await _member(db, "bravo")

    root = await client.post(
        "/api/v1/agent-mail/messages",
        headers=OP,
        json={
            "kind": "context_request",
            "sender_member_id": asker.id,
            "recipient_member_id": answerer.id,
            "subject": "need input",
            "body_markdown": "which branch?",
        },
    )
    assert root.status_code == 200, root.text
    root_id = root.json()["id"]

    answer = await client.post(
        "/api/v1/agent-mail/messages",
        headers=OP,
        json={
            "kind": "answer",
            "sender_member_id": answerer.id,
            "thread_root_id": root_id,
            "body_markdown": "the feature branch",
        },
    )

    assert answer.status_code == 200, answer.text
    assert answer.json()["sender_member_id"] == answerer.id
    assert (
        await db.execute(
            text("SELECT request_status FROM mail_messages WHERE id = :i"),
            {"i": root_id},
        )
    ).one() == ("answered",)


@pytest.mark.asyncio
async def test_operator_acks_and_the_receipt_records_it(client_and_db, enforced):
    """The ack path, and the field that makes it security-relevant.

    ack_message writes read_at and acked_at on the acking member's receipt.
    _brief_delivered reads read_at to decide the brief_unread escalation, so an
    unauthenticated ack silences a dispatch escalation -- which is why this
    route needs a credential rather than an open door.
    """
    client, db = client_and_db
    sender = await _member(db, "alpha")
    recipient = await _member(db, "bravo")

    handoff = await client.post(
        "/api/v1/agent-mail/messages",
        headers=OP,
        json={
            "kind": "handoff",
            "sender_member_id": sender.id,
            "recipient_member_id": recipient.id,
            "subject": "take it",
            "body_markdown": "yours now",
        },
    )
    assert handoff.status_code == 200, handoff.text
    handoff_id = handoff.json()["id"]

    ack = await client.post(
        f"/api/v1/agent-mail/messages/{handoff_id}/ack",
        headers=OP,
        json={"member_id": recipient.id},
    )

    assert ack.status_code == 200, ack.text
    assert (
        await db.execute(
            text(
                "SELECT m.request_status, r.read_at IS NOT NULL, r.acked_at IS NOT NULL "
                "FROM mail_messages m JOIN mail_receipts r ON r.message_id = m.id "
                "WHERE m.id = :i AND r.member_id = :m"
            ),
            {"i": handoff_id, "m": recipient.id},
        )
    ).one() == ("acknowledged", 1, 1)


@pytest.mark.asyncio
async def test_a_wrong_operator_token_is_refused_not_downgraded(client_and_db, enforced):
    """A bad operator token must never fall through to the tokenless path.

    This is the sibling of Task 5's 'invalid is not absent' rule. If a wrong
    operator token were treated as no credential, enforcement would be advisory:
    send garbage, get the legacy path.
    """
    client, db = client_and_db
    recipient = await _member(db, "bravo")
    body = {
        "kind": "message",
        "recipient_member_id": recipient.id,
        "body_markdown": "x",
    }

    for header, expected in [
        ({"X-Deck-Operator-Token": "i-am-guessing"}, "operator_token_invalid"),
        ({"X-Deck-Operator-Token": OPERATOR_TOKEN[:-1]}, "operator_token_invalid"),
        ({"X-Deck-Operator-Token": OPERATOR_TOKEN + "X"}, "operator_token_invalid"),
        ({"X-Deck-Operator-Token": OPERATOR_TOKEN.upper()}, "operator_token_invalid"),
        ({}, "session_token_required"),
    ]:
        response = await client.post(
            "/api/v1/agent-mail/messages", headers=header, json=body
        )
        label = f"header={header!r}"
        assert response.status_code == 401, f"{label}: {response.text}"
        assert response.json()["detail"] == expected, label


@pytest.mark.asyncio
async def test_an_unconfigured_operator_token_refuses_with_the_right_code(
    client_and_db, monkeypatch
):
    """The compare_digest("", "") trap, pinned by CODE and not merely by refusal.

    Measured, this hole needs TWO mutations: deleting the 503 check and widening
    the presence guard from truthy to `is not None`. Either one alone still
    refuses, so `assert status in (401, 503)` passes against both and proves
    nothing. The exact codes are the only thing that differs between the correct
    implementation and each mutant, so the exact codes are what this asserts.
    """
    client, db = client_and_db
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    monkeypatch.setattr(settings, "operator_token", "")
    recipient = await _member(db, "bravo")

    for header, status, detail, kills in [
        (
            {"X-Deck-Operator-Token": "anything"},
            503,
            "operator_token_unconfigured",
            "a deleted 503 check, which answers operator_token_invalid instead "
            "and tells an operator who forgot the setting that their token is wrong",
        ),
        (
            {"X-Deck-Operator-Token": ""},
            401,
            "session_token_required",
            "an `is not None` guard, which lets an empty header reach the "
            "comparison -- and with the 503 check also gone, compare_digest("
            '"", "") authorizes it',
        ),
    ]:
        response = await client.post(
            "/api/v1/agent-mail/messages",
            headers=header,
            json={
                "kind": "message",
                "recipient_member_id": recipient.id,
                "body_markdown": "x",
            },
        )
        assert response.status_code == status, f"kills {kills}: {response.text}"
        assert response.json()["detail"] == detail, f"kills {kills}"

    assert (
        await db.execute(text("SELECT COUNT(*) FROM mail_messages"))
    ).one() == (0,), "an unconfigured install wrote a message"


@pytest.mark.asyncio
async def test_a_non_ascii_operator_header_is_a_refusal_not_a_500(
    client_and_db, enforced
):
    """compare_digest raises TypeError on non-ASCII str; a header can carry one.

    Sent as raw bytes because httpx will not encode a non-latin-1 str header.
    """
    client, db = client_and_db
    recipient = await _member(db, "bravo")

    response = await client.post(
        "/api/v1/agent-mail/messages",
        headers={"X-Deck-Operator-Token": "café".encode("latin-1")},
        json={
            "kind": "message",
            "recipient_member_id": recipient.id,
            "body_markdown": "x",
        },
    )

    assert response.status_code == 401, response.text
    assert response.json()["detail"] == "operator_token_invalid"


@pytest.mark.asyncio
async def test_an_actor_token_does_not_open_a_member_sender_write(
    client_and_db, enforced
):
    """The credential-provenance rule, as a test.

    An agent pane mints an actor with no credential at all -- measured, 200 and
    a 43-character token. If that token opened a member-sender write, PR1's
    approval gate (section 4.3 rule 4 matches sender_member_id == leader) would
    be forgeable by every agent on the host. The actor token authenticates a
    caller; it does not authorize speaking as a member.
    """
    client, db = client_and_db
    leader = await _member(db, "leader")

    minted = await client.post(
        "/api/v1/external/agent-mail/actors",
        json={
            "actor_key": "totally-not-an-agent",
            "display_name": "Deck UI",
            "kind": "supervisor",
        },
    )
    assert minted.status_code == 200, minted.text
    actor_token = minted.json()["token"]

    response = await client.post(
        "/api/v1/agent-mail/messages",
        headers={"Authorization": f"Bearer {actor_token}"},
        json={
            "kind": "message",
            "sender_member_id": leader.id,
            "recipient_member_id": leader.id,
            "body_markdown": "signed, the leader",
        },
    )

    assert response.status_code == 401, response.text
    assert response.json()["detail"] == "session_token_required"
    assert (
        await db.execute(text("SELECT COUNT(*) FROM mail_messages"))
    ).one() == (0,)
```

- [ ] **Step 2: Run it and read the failures**

```bash
cd backend && source venv/bin/activate
pytest tests/agent_mail/test_operator_mail_writes.py -v -p no:warnings
```

Expected: **7 failed**. The four positive tests fail with `401 session_token_required` — under enforcement `mail_session` refuses every credential it does not yet recognise, and the operator token is one of those. `test_a_wrong_operator_token_is_refused_not_downgraded` fails only on its four operator-header rows, which currently return `session_token_required` rather than `operator_token_invalid`; its `{}` row already passes. The empty-setting and non-ASCII tests fail the same way. `test_an_actor_token_does_not_open_a_member_sender_write` **passes already** — an actor token is not an operator token and never was — and it stays in the file as a regression guard, because the mutation in Step 8 is what makes it earn its place.

Read the failure of `test_operator_answers_as_the_designated_recipient` carefully. Without the extension there is **no** way to post that row under enforcement: not the external routes (measured `400`), not an actor token, not a session token the UI does not have. That absence is the requirement.

- [ ] **Step 3: Add the operator principal to `deps.py`**

At the top of `deps.py`, beside `_missing_token_logged`:

```python
class OperatorPrincipal:
    """The human operator, authenticated by settings.operator_token.

    A sentinel rather than a row: the operator has no MailAgentSession, no
    member, and no slot. It exists so mail_session can return "authenticated,
    but not as an agent" without overloading None -- None means grace mode, and
    conflating the two would make an unconfigured install indistinguishable from
    an authenticated operator.

    Deliberately NOT a MailAgentSession subclass. require_session_slot must
    refuse it, and it does so by the attribute access failing loudly rather
    than by a check someone can forget to write: an operator cannot report
    dispatch status on a slot's behalf.
    """


OPERATOR = OperatorPrincipal()
```

`OPERATOR` is a module-level singleton because nothing distinguishes two operator principals, and an identity check reads better at the call sites than an `isinstance`.

**Widen the `typing` import in the same edit.** Task 5 wrote `from typing import Optional`; Steps 4, 5 and 6 all annotate with `Union`, so change that line to `from typing import Optional, Union`. Missing it is a `NameError` at **import** time, which surfaces as every test in the file erroring during collection rather than as one failing assertion — a confusing failure for a one-word omission.

- [ ] **Step 4: Teach `mail_session` the second credential**

Replace `mail_session` (added in Task 5) with the version below. Only the middle block is new; the session-token half is unchanged.

```python
async def mail_session(
    x_deck_session_token: Optional[str] = Header(default=None),
    x_deck_operator_token: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> Union[MailAgentSession, OperatorPrincipal, None]:
    """Resolve the caller: an agent session, the operator, or grace mode.

    The two credentials are checked in order and never blended. A session token
    is tried first because it is the common case and the more specific claim; an
    operator token is only consulted when no session token was presented, so a
    pane that holds both cannot escalate by adding a header.

    Returns None only in grace mode with NO credential at all. A credential that
    is present but does not match is always a refusal: treating an invalid token
    as an absent one would make the enforcement flag meaningless, because any
    caller could send garbage and get the legacy unauthenticated path.
    """
    if x_deck_session_token:
        hashed = agent_mail_service.hash_capability_token(x_deck_session_token)
        result = await db.execute(
            select(MailAgentSession).where(MailAgentSession.capability_token_hash.is_not(None))
        )
        for session in result.scalars().all():
            if hmac.compare_digest(session.capability_token_hash, hashed):
                return session
        raise HTTPException(status_code=401, detail="session_token_invalid")

    if x_deck_operator_token:
        expected = settings.operator_token
        # The empty check precedes the comparison, and that order is load-bearing:
        # compare_digest("", "") is True, so leaving the empty setting to the
        # comparison would let any caller sending an empty header write mail as
        # any member on an unconfigured install. Same trap as require_operator,
        # separate comparison, so it must be closed separately.
        if not expected:
            raise HTTPException(status_code=503, detail="operator_token_unconfigured")
        # Bytes, because compare_digest raises TypeError on a non-ASCII str and
        # an unhandled TypeError here is a 500 rather than a refusal.
        if not hmac.compare_digest(
            x_deck_operator_token.encode("utf-8"), expected.encode("utf-8")
        ):
            raise HTTPException(status_code=401, detail="operator_token_invalid")
        return OPERATOR

    if settings.mail_capability_tokens_required:
        raise HTTPException(status_code=401, detail="session_token_required")
    return None
```

Add `Union` to the `typing` import. Note what moved: Task 5's version returned early on `if not x_deck_session_token`, which cannot accommodate a second credential; this version inverts that into `if x_deck_session_token:` and lets the enforcement check fall to the end, where it now guards "no credential of either kind."

**Do not reuse `require_operator` as a sub-dependency here.** It raises `401 operator_token_required` when the header is absent, which is the wrong refusal for a route that also accepts a session token — a pane calling with no headers at all would be told to present an operator token. The comparison is four lines; the refusal vocabulary is what differs.

- [ ] **Step 5: Teach `derive_member_id` the operator shape**

In `derive_member_id`, insert one branch **before** the `session is None` branch:

```python
    if session is OPERATOR:
        # The operator names the member it acts as, and that is the point rather
        # than a weakness: ThreadDialog's answer path is only valid when
        # sender_member_id equals the thread root's recipient_member_id, so a
        # server-derived value is impossible here -- there is no session to
        # derive from. What makes this safe is the credential, not the claim:
        # the operator token is the one secret no agent is given.
        #
        # A missing claim is NOT an error. Compose sends no sender at all and
        # must keep storing NULL, which is what stops an operator-composed
        # message from ever resembling a leader approval (PR1 section 4.3).
        return claimed
```

Then widen the signature and return type:

```python
def derive_member_id(
    session: Union[MailAgentSession, OperatorPrincipal, None],
    claimed: Optional[int],
    *,
    detail: str = "sender_not_token_holder",
) -> Optional[int]:
```

**Only the `session` parameter's annotation changes here.** The return is already `Optional[int]` — Task 5 wrote it that way, because its own grace-mode branch can return a `None` claim. So this step widens the input union and adds one branch; it does not touch the return annotation. If you find `-> int` there, Task 5 was implemented against the older Interfaces line and the operator-compose path will not type-check — fix it here and say so in the handoff.

The `None` return *reaches a new caller* now, though: the operator-compose path returns `None` deliberately, where before `None` only came back from a grace-mode path that had already raised on a missing claim. That has one consequence at the call sites Task 5 wrote, and Step 6 handles it.

**`require_session_slot` needs one guard, and this is the step that must not skip it.** Its `session.team_slot_id` raises `AttributeError` on an `OperatorPrincipal`, and that path is **reachable**: `/dispatch-status` (Task 7, `agent_teams.py`) declares `session: MailAgentSession | None = Depends(mail_session)` — `mail_session`, *not* `require_mail_session` — and `_authorize_dispatch_report` calls `require_session_slot(session)` after only an `if session is None: return`. An `OperatorPrincipal` is not `None`, so it falls straight through to the attribute access and the operator gets a `500` instead of a refusal.

Add the type check rather than relying on the attribute failing:

```python
def require_session_slot(session: Union[MailAgentSession, "OperatorPrincipal"]) -> int:
    """The slot this session is bound to, or 403.

    The operator is refused for the same reason an unbound agent is: it has no
    slot, and every dispatch-status report claims to speak for one. Checked
    explicitly rather than left to AttributeError, because the difference
    between the two is a 403 and a 500.
    """
    if not isinstance(session, MailAgentSession):
        raise HTTPException(status_code=403, detail="session_not_slot_bound")
    if session.team_slot_id is None:
        raise HTTPException(status_code=403, detail="session_not_slot_bound")
    return session.team_slot_id
```

Both branches return the same code deliberately: from the reporter's side "you are not bound to a slot" is the same fact either way, and inventing a second code would be a new refusal string PR0's spec does not define.

This is the one place in Task 10 where a route *outside* `agent_mail.py` sees the widened union, which is why it is easy to miss — Step 8's fifth mutation row exists to catch it.

- [ ] **Step 6: Fix the two call sites the widened return type breaks**

`require_mail_session` must refuse the operator, or `/dispatch-status` would accept an operator token as an agent's slot claim:

```python
async def require_mail_session(
    session: Union[MailAgentSession, OperatorPrincipal, None] = Depends(mail_session),
) -> MailAgentSession:
    """Like mail_session, but always a real agent session.

    The operator is refused here rather than at each caller: a route that needs
    a SLOT needs an agent, and the operator has none. session_token_required is
    the right refusal -- the caller did authenticate, just not as the kind of
    principal this route serves.
    """
    if not isinstance(session, MailAgentSession):
        raise HTTPException(status_code=401, detail="session_token_required")
    return session
```

And in `agent_mail.py`, the two routes that pass the derived value into `int(...)` — `mark_read` and `ack_message` — need the `None` case, which is now reachable for an operator who omits `member_id`:

```python
    member_id = derive_member_id(
        session, body.get("member_id"), detail="member_not_token_holder"
    )
    if member_id is None:
        # Reachable only for an operator who named no member. Compose may store
        # a NULL sender; a receipt cannot have a NULL member, so this is a 400
        # rather than a silent no-op -- ack_message returns quietly when no
        # receipt matches, and that quiet is what would hide the mistake.
        raise HTTPException(status_code=400, detail="member_id_required")
    await agent_mail_service.mark_read(db, message_id, int(member_id))
```

Apply the same three lines to `ack_message`. `send_message` needs no such guard: it passes the value into `model_copy`, and a `None` sender is exactly what compose stores.

`agent_inbox` also calls `int(resolved)`. Add the same guard there, with the same reasoning — an operator hitting the agent inbox with no `member_id` has named no inbox to read.

- [ ] **Step 7: Run the file — expect green**

```bash
cd backend && source venv/bin/activate
pytest tests/agent_mail/test_operator_mail_writes.py -v -p no:warnings
```

Expected: **7 passed**.

- [ ] **Step 8: Mutate the dependency eight ways**

Each mutation must turn at least one test red. If any is silent, the test that should have caught it is wrong — fix the test, not the mutation.

| Mutation | Test that must fail | Why it is the trap |
| --- | --- | --- |
| Check `x_deck_operator_token` **before** `x_deck_session_token` | none in this file — **add the case** | A pane holding a real session token plus a guessed operator token would be resolved as the operator. Add a case to `test_capability_tokens.py`: a valid session token *and* a wrong operator header must still resolve as the session, not `401` |
| Delete the `if not expected: raise 503` line | `test_an_unconfigured_operator_token_refuses_with_the_right_code`, first case | Measured, this alone opens **nothing** — an empty header is falsy and never reaches the comparison. What it destroys is the *diagnosis*: an operator who forgot the setting is told their token is invalid. Only a code-exact assertion catches it |
| Widen the guard to `if x_deck_operator_token is not None:` | the same test, second case | Now an empty header does reach the comparison. Together with the row above, `compare_digest("", "")` returns `True` and an unconfigured install **authorizes every caller** — measured `200` |
| Compare `str` instead of bytes | `test_a_non_ascii_operator_header_is_a_refusal_not_a_500` | `TypeError` → `500`. A suite that only sends ASCII garbage sees nothing wrong |
| Return `None` instead of `OPERATOR` on a valid operator token | the three positive tests, but **not** with a useful message | Under enforcement `None` means grace mode, so the write would *succeed* while logging `capability_token_missing`. Green tests, silently wrong audit trail — check the log assertion in Step 9 |
| Delete the `isinstance` guard from `require_session_slot` (Step 6) | none in this file — **add the case** | This is the reachable `500`. `/dispatch-status` takes `Depends(mail_session)`, not `require_mail_session`, so an operator token arrives as an `OperatorPrincipal`, survives `if session is None: return`, and hits `session.team_slot_id`. Add the case to `test_operator_mail_writes.py` — see Step 9's third test |
| Make `require_mail_session` accept `OperatorPrincipal` | **nothing today — and that is the finding** | It reads like the dangerous mutation and is currently inert, because no PR0 route depends on `require_mail_session`: `/dispatch-status` uses `mail_session` directly and the four mail routes use `derive_member_id`. Leave the narrowing in place anyway — PR1 adds routes that do depend on it — but do not record this row as "caught by Task 7's suite," because it is not |
| In `derive_member_id`, raise on `claimed is None` for the operator instead of returning it | `test_operator_composes_anonymously` | Compose would `400`. This is the mutation that looks like tightening and is actually a regression |

- [ ] **Step 9: Add the two cases to `test_capability_tokens.py`**

The first is the credential-precedence case Step 8's first row demands. The second pins the log line, which Step 8's fourth row shows is the only observable difference between a correct operator write and a grace-mode one.

```python
@pytest.mark.asyncio
async def test_a_session_token_wins_over_an_operator_header(
    client, db, tmp_path, monkeypatch
):
    """A pane that adds a guessed operator header must not become the operator.

    Precedence is the whole of this test: the session token is checked first, so
    the bogus operator header is never consulted. Reverse the order in deps.py
    and this returns 401 operator_token_invalid instead of 200.
    """
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    monkeypatch.setattr(settings, "operator_token", "the-real-operator-token")
    register = await client.post(
        "/api/v1/agent-mail/agent/register",
        json=_body(tmp_path, session_key="mcp:precedence"),
    )
    token = register.json()["capability_token"]
    sender_id = register.json()["member"]["id"]
    recipient = await _member(db, "other-repo", "other")

    response = await client.post(
        "/api/v1/agent-mail/messages",
        headers={
            "X-Deck-Session-Token": token,
            "X-Deck-Operator-Token": "i-guessed-this",
        },
        json={
            "kind": "message",
            "recipient_member_id": recipient.id,
            "body_markdown": "hi",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["sender_member_id"] == sender_id


@pytest.mark.asyncio
async def test_an_operator_write_does_not_log_a_missing_token(
    client, db, tmp_path, monkeypatch, caplog
):
    """An authenticated operator is not a tokenless caller.

    derive_member_id logs capability_token_missing for the grace-mode path. If
    mail_session returned None for a valid operator token instead of OPERATOR,
    every UI write would still succeed and would be recorded as unauthenticated
    -- green tests, false audit trail. This assertion is the difference.
    """
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    monkeypatch.setattr(settings, "operator_token", "the-real-operator-token")
    recipient = await _member(db, "other-repo", "other")

    with caplog.at_level(logging.WARNING, logger="app.api.v1.deps"):
        response = await client.post(
            "/api/v1/agent-mail/messages",
            headers={"X-Deck-Operator-Token": "the-real-operator-token"},
            json={
                "kind": "message",
                "sender_member_id": recipient.id,
                "recipient_member_id": recipient.id,
                "body_markdown": "hi",
            },
        )

    assert response.status_code == 200, response.text
    assert "capability_token_missing" not in caplog.text
```

Add `import logging` to the file if Task 5 did not.

**The third case goes in a different file, because the route it exercises is not a mail route.** Step 8's `require_session_slot` row describes a reachable `500` on `/dispatch-status`, and that route lives in `agent_teams.py` with its own fixtures. Append to `backend/tests/agent_mail/test_dispatch_status_tool.py`, which Task 7 already extended and which owns `client_and_db` and `_seed_item`:

```python
@pytest.mark.asyncio
async def test_an_operator_token_is_refused_not_a_500(client_and_db, monkeypatch):
    """The operator has no slot, so it cannot report on one -- 403, not 500.

    /dispatch-status takes Depends(mail_session), NOT require_mail_session, so
    Task 10's widened union arrives here directly. The route's only None check
    is `if session is None: return`, and an OperatorPrincipal is not None -- so
    without the isinstance guard in require_session_slot this reaches
    `session.team_slot_id` on a class that has no such attribute and the client
    sees an unhandled AttributeError. Delete that guard and this test is the
    only thing in the suite that notices.
    """
    monkeypatch.setattr(settings, "operator_token", "the-real-operator-token")
    ac, maker = client_and_db
    item_id = await _seed_item(maker, approval_round_count=1)

    resp = await ac.post(
        "/api/v1/agent-teams/dispatch-status",
        headers={"X-Deck-Operator-Token": "the-real-operator-token"},
        json={"work_item_id": item_id, "status": "triaging"},
    )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "session_not_slot_bound"
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        assert item.dispatch_status == "dispatched", "a refused report must change nothing"
```

This test needs `from app.config import settings` in that file — check whether Task 7 already added it; the pre-existing file does not import it. It does **not** need `mail_capability_tokens_required` set: the operator branch in `mail_session` is reached on the strength of the operator header alone, in either mode, which is itself worth knowing.

That makes **three** Step 9 cases, not two: two in `test_capability_tokens.py` and one in `test_dispatch_status_tool.py`, taking that file to **40** and this task's total to **10** new cases.

**`_missing_token_logged` is module-level state and `caplog` only sees the first log for a given member.** If a preceding test in the same process already logged for this member id, the assertion passes for the wrong reason. It cannot fire falsely *negative*, which is the direction that matters here, but note it: a positive control for the log line belongs with Task 5's grace-mode tests, where the set is empty.

- [ ] **Step 10: Run both backend files, then the whole mail suite**

```bash
cd backend && source venv/bin/activate
pytest tests/agent_mail/test_operator_mail_writes.py tests/agent_mail/test_capability_tokens.py -v -p no:warnings
pytest tests/agent_mail/ tests/agent_teams/ -q -p no:warnings
```

Expected: `7 passed` in `test_operator_mail_writes.py` and `35 passed` in `test_capability_tokens.py` (33 after Task 5 + this task's Step 9 pair), then **`557 passed`** for the two suites (547 after Task 9 + this task's 10 — Step 1's 7 plus Step 9's 3). `test_dispatch_status_tool.py` goes to **40**. Any *other* failure is a real regression from the widened return type — most likely a call site passing the derived value into `int()` that Step 6 missed. Grep for `derive_member_id` and check each caller handles `None`.

- [ ] **Step 11: Commit the backend half**

```bash
git add backend/app/api/v1/deps.py backend/app/api/v1/agent_mail.py \
        backend/tests/agent_mail/test_operator_mail_writes.py \
        backend/tests/agent_mail/test_capability_tokens.py
git commit -m "feat(mail): accept the operator credential on the UI's mail writes

The Agent Mail UI holds no session token and its reply path requires a MEMBER
sender: kind='answer' is valid only when sender_member_id equals the thread
root's recipient_member_id. An external-actor write lands in sender_actor_id and
leaves sender_member_id NULL by construction, so no actor token can post it --
measured 400 'only the context request recipient can answer it'. The two
external routes spec 3.6 named also refuse outright, both with 'External actors
can only ... they created', because the UI acts in threads agents created.

mail_session therefore accepts a second credential: the operator token from
spec 3.6a, which is the only secret in this system an agent cannot mint. A
member-sender route gated on an actor token would be a hole, not a fix -- POST
/external/agent-mail/actors needs no credential at all, so every pane could
then write as the leader whose answer PR1's approval gate reads.

Session token is checked first, so a pane holding one cannot escalate by adding
an operator header. The empty-setting check precedes the comparison because
compare_digest('', '') is True. The comparison is over bytes because
compare_digest raises TypeError on a non-ASCII str, which is a 500 not a
refusal.

Spec: 2026-08-05-distinct-approver-identity-design.md section 3.6, resolved
against section 3.6a"
```

- [ ] **Step 12: Add the token store to the frontend**

Create `frontend/src/lib/operatorToken.ts`:

```ts
const STORAGE_KEY = 'deck.operatorToken'

// Cached because apiClient reads it on every request and sessionStorage access
// is a synchronous cross-boundary call. The cache is invalidated only through
// setOperatorToken, which is the sole writer.
let cached: string | null | undefined

export function operatorToken(): string | null {
  if (cached === undefined) {
    try {
      cached = sessionStorage.getItem(STORAGE_KEY)
    } catch {
      // Private-mode or a hardened browser: treat as absent rather than throw.
      cached = null
    }
  }
  return cached
}

export function setOperatorToken(value: string | null): void {
  cached = value
  try {
    if (value) {
      sessionStorage.setItem(STORAGE_KEY, value)
    } else {
      sessionStorage.removeItem(STORAGE_KEY)
    }
  } catch {
    // The in-memory cache still holds it for this tab's lifetime.
  }
}
```

**`sessionStorage`, not `localStorage`, and this is the one part of §3.6's provisioning advice that survives.** The token dies with the tab, so a shared machine does not leave an operator credential in a profile that outlives the session. It also means the operator pastes it once per tab, which is the cost of not storing a secret durably in the browser.

- [ ] **Step 13: Send the header from `apiClient`**

In `frontend/src/lib/api.ts`, import the store and add one header. The spread order matters: `...options?.headers` stays **last** so a call site can still override.

```ts
import { operatorToken } from '@/lib/operatorToken'
```

```ts
export async function apiClient<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`
  const token = operatorToken()

  try {
    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { 'X-Deck-Operator-Token': token } : {}),
        ...options?.headers,
      },
    })
```

Sending it on **every** request rather than only on mail writes is deliberate: the backend ignores the header on routes with no dependency reading it, and a per-call opt-in is how a future write acquires a silent `401`. It also means Task 8's operator-gated workspace routes become reachable from the UI for free, which is what makes the deferred workspace-lease UI (§7) possible without another auth change.

- [ ] **Step 14: Add the settings field so the operator can supply the token**

Create `frontend/src/features/config/OperatorTokenCard.tsx`.

**Measured before writing: there is no `features/settings/` directory.** `ConfigViewerPage.tsx` composes sibling `*Card.tsx` files from `features/config/` directly (`CodexDiagnosticsCard`, `CodexInventoryCard`, `CodexProfileResolverCard` — imported at `:8-10`, rendered at `:297`). There *is* a `features/config/settings/` subtree, but it belongs to `SettingsEditor` and edits Claude's own settings files, not Deck's. Follow the sibling-card pattern.

```tsx
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { operatorToken, setOperatorToken } from '@/lib/operatorToken'

export function OperatorTokenCard() {
  const [value, setValue] = useState('')
  const [stored, setStored] = useState(() => operatorToken() !== null)

  const save = () => {
    const next = value.trim() || null
    setOperatorToken(next)
    setStored(next !== null)
    setValue('')
    toast.success(next ? 'Operator token stored for this tab' : 'Operator token cleared')
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Operator token</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">
          Required to send Agent Mail and to manage workspace leases once capability
          tokens are enforced. Must match <code>operator_token</code> in{' '}
          <code>backend/.env</code>. Stored for this tab only — a new tab will ask
          again.
        </p>
        <div className="space-y-2">
          <Label htmlFor="operator-token">Token</Label>
          <div className="flex gap-2">
            <Input
              id="operator-token"
              type="password"
              autoComplete="off"
              placeholder={stored ? '•••••••• (stored for this tab)' : 'paste the token'}
              value={value}
              onChange={(event) => setValue(event.target.value)}
            />
            <Button onClick={save} disabled={!value.trim() && !stored}>
              {value.trim() ? 'Save' : 'Clear'}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
```

`type="password"` and `autoComplete="off"` because this is a secret on a screen that gets shared and screenshotted. The card **never renders the stored value back** — only whether one exists — which is the same posture `CodexDiagnosticsCard` already takes with its `SENSITIVE_KEY_PATTERN` redaction (`:15`). `stored` is `useState` rather than a bare `operatorToken()` call so the placeholder updates after a save without a reload.

Mount it in `ConfigViewerPage.tsx` beside the existing cards: add `import { OperatorTokenCard } from "./OperatorTokenCard";` next to the three Codex imports, and render `<OperatorTokenCard />` in the same section. **Do not add a route** — `App.tsx`'s 17 routes are enumerated in `CLAUDE.md`, and one field does not warrant an 18th.

- [ ] **Step 15: Improve the `401` message on the three mail writes**

A bare `401 session_token_required` in a toast tells an operator nothing actionable. In `frontend/src/features/agent-mail/api.ts`, wrap the three writes:

```ts
import { apiClient, buildEndpoint } from '@/lib/api'
import { operatorToken } from '@/lib/operatorToken'
```

```ts
async function operatorWrite<T>(endpoint: string, body: unknown): Promise<T> {
  try {
    return await apiClient<T>(endpoint, {
      method: 'POST',
      body: JSON.stringify(body),
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : ''
    if (message.includes('session_token_required') || message.includes('operator_token')) {
      throw new Error(
        operatorToken()
          ? 'The stored operator token was rejected. Re-enter it in Config.'
          : 'Agent Mail writes need an operator token. Add it in Config.'
      )
    }
    throw error
  }
}

export function sendAgentMailMessage(message: MailMessageCreate): Promise<MailMessageResponse> {
  return operatorWrite<MailMessageResponse>('agent-mail/messages', message)
}

export function markAgentMailRead(messageId: number, memberId: number): Promise<{ ok: boolean }> {
  return operatorWrite<{ ok: boolean }>(`agent-mail/messages/${messageId}/read`, {
    member_id: memberId,
  })
}

export function ackAgentMailMessage(messageId: number, memberId: number): Promise<{ ok: boolean }> {
  return operatorWrite<{ ok: boolean }>(`agent-mail/messages/${messageId}/ack`, {
    member_id: memberId,
  })
}
```

The two branches are distinguishable on purpose: "no token stored" and "the stored token is wrong" send the operator to different actions, and `apiClient` surfaces FastAPI's `detail` through `apiErrorMessage`, so the string match has something to match on.

`markAgentMailRead` has zero callers today and still gets this treatment — see "What is deliberately not touched."

- [ ] **Step 16: Verify the frontend builds and lints**

```bash
cd frontend
npm run lint
npx tsc --noEmit
npm run build
```

Expected: clean. `noUnusedLocals` is on, so an unused import from Step 13 or 15 is an error, not a warning.

- [ ] **Step 17: Manually verify the three writes, both ways**

The backend tests prove the routes; this proves the browser actually sends the header. With the backend running and `operator_token` set in `backend/.env`:

1. With **no** token in Config, open Agent Mail and send a message. Expect the toast: *"Agent Mail writes need an operator token. Add it in Config."*
2. Paste a **wrong** token in Config, retry. Expect: *"The stored operator token was rejected. Re-enter it in Config."*
3. Paste the **real** token, retry. Expect the message to send.
4. Open a thread on a `context_request` addressed to a member, select that member as sender, and reply. Expect *"Answer sent"* and the root's status to become `answered`.
5. Ack a pending handoff. Expect *"Acknowledged"*.
6. Open a **new tab**. Expect step 1's toast again — `sessionStorage` is per-tab, and confirming that is confirming the secret is not persisted.

Steps 4 and 5 are the ones no automated frontend test covers (this project has none) and the ones the spec got wrong, so do not skip them.

- [ ] **Step 18: Commit the frontend half**

```bash
git add frontend/src/lib/operatorToken.ts frontend/src/lib/api.ts \
        frontend/src/features/agent-mail/api.ts \
        frontend/src/features/config/OperatorTokenCard.tsx \
        frontend/src/features/config/ConfigViewerPage.tsx
git commit -m "feat(ui): send the operator token with every request

apiClient adds X-Deck-Operator-Token when one is stored, so the three Agent Mail
writes keep working once capability tokens are enforced -- and Task 8's
operator-gated workspace routes become reachable without a second auth change.

sessionStorage rather than localStorage: the token dies with the tab, so a
shared machine does not leave an operator credential in a browser profile. The
cost is re-entry per tab, which is the right trade for a secret.

Spec 3.6 proposed a per-tab external ACTOR token instead. Dropped: that
credential needs no secret to mint (POST /external/agent-mail/actors is
loopback-gated only), and the UI's reply path needs a member sender, which the
external schemas have no field for.

Spec: 2026-08-05-distinct-approver-identity-design.md section 3.6"
```

---

### Task 11: The two things an operator must know before deploying this

**Files:**
- Modify: `README.md` (`:110-114`, the `**Prerequisites**:` list)
- Create: `docs/deploy/pr0-capability-tokens-rollout.md`

**Interfaces:**
- Consumes: nothing. This task writes prose only and depends on no earlier task's code.
- Produces: nothing any task imports. It is last because it *describes* Tasks 1–10, and it is not optional: two of PR0's three deployment steps are invisible in the code, and an operator who performs them in the wrong order locks themselves out of the routes Task 8 gates.

**Why documentation is a task with a reviewer's gate rather than a step inside another task.** Two facts about PR0 cannot be discovered by reading the diff. First, **PR0 requires Linux** — every function in `peer_process.py` (Task 2) reads `/proc/net/tcp`, `/proc/net/tcp6`, and `/proc/<pid>/stat`, and the README's own prerequisite list currently promises only "Python 3.11+, Node.js 18+, at least one agent CLI." Second, the rollout is a **four-step ordered sequence involving two different restarts for two different credentials**, and §3.6a says in as many words that "an operator who reads 'restart the panes' and stops has provisioned nothing." Neither belongs in Task 2's or Task 8's commit, because both describe the *assembled* PR.

#### The four measurements that decide this task's content

**1. `backend/.env` is already gitignored, so the plan must not tell an operator to add it.** Measured:

```
$ git check-ignore -v backend/.env
.gitignore:27:.env	backend/.env
```

`.gitignore:27` is a bare `.env`, which git matches at any depth. §3.6a's requirement that the file be "gitignored" is therefore already satisfied, and a rollout note instructing an operator to edit `.gitignore` would produce a redundant line and a confusing diff. What is *not* automatic is the mode: `600` has to be set explicitly.

**2. The README's prerequisite list is lines 112–114 and mentions no platform at all.** Verified by reading:

```
110: **Prerequisites**:
112: - Python 3.11+
113: - Node.js 18+
114: - At least one supported local agent CLI installed on the same host: ...
```

So the bullet is an addition, not an edit, and it goes after `:114` — a platform requirement is a stronger constraint than a CLI requirement and belongs adjacent to it, not above the language runtimes.

**3. The README already says Deck must run on the host where the agents live, which is the sentence the new bullet must not contradict.** `README.md:108` reads: *"Claude Deck must run in the same environment where your agent CLIs and credentials are installed. Use the native install path below; Docker is not supported because containers cannot see host-installed CLIs, tmux sessions, native agent credentials, or your real repository environment."* And `:150`: *"Remote use should still be native."* The Linux bullet is consistent with both and should be phrased as sharpening them rather than as a new restriction.

**4. Non-Linux does not crash — it silently never binds a pane, and that is the fact a prerequisite bullet must convey without overclaiming.** Task 2's design is that every resolver function returns `None` or `{}` rather than raising, so on macOS a Deck with `mail_capability_tokens_required = False` serves every request and simply mints unbound sessions. Under enforcement the same host refuses registration with `bind_unverifiable` (Task 4). So the honest statement is not "Deck requires Linux" but "**pane binding** requires Linux, and enforcement requires pane binding." Writing the stronger claim would be wrong in the direction that costs a macOS user the whole app.

#### What is deliberately *not* documented

- **No `.env.example`.** `CLAUDE.md` states "No `.env` file needed — all config has defaults in `backend/app/config.py`," and that stays true: both new settings have defaults. Shipping an example file would invert the project's stated posture for two optional settings.
- **No README section on capability tokens.** The README is a user-facing feature tour; the enforcement flag is an operator concern with one audience of one. It goes in `docs/deploy/`.
- **No rollback procedure.** Flipping `mail_capability_tokens_required` back to `False` and restarting is the rollback, and it is stated inline in the note. A separate section would imply a process that does not exist.
- **`CLAUDE.md`'s "no migration system" line is left alone.** Task 1 adds additive ladder rungs, which makes that line imprecise, but fixing it is a separate `docs:` commit outside this spec — it describes the whole project, not PR0.

- [ ] **Step 1: Add the prerequisite bullet**

In `README.md`, after the CLI bullet at `:114`:

```markdown
- **Linux** for agent-team pane binding. Deck reads `/proc/net/tcp` and `/proc/<pid>/stat` to derive which tmux pane a registering agent is running in. On macOS or Windows every other feature works, but agents register unbound, and the Agent Mail capability-token enforcement described in `docs/deploy/pr0-capability-tokens-rollout.md` cannot be turned on
```

Match the list's existing style: no terminal period, sentence case, `**bold**` for the lead term as the CLI bullet does not — but the other three bullets are bare, so bold only the word `Linux` and leave the rest plain.

- [ ] **Step 2: Verify the README renders and says what you meant**

```bash
sed -n '108,120p' README.md
```

Read it back as an operator on a Mac would: the paragraph above says Docker is unsupported because containers cannot see the host, and this bullet now says one feature needs Linux. Those are consistent. If the bullet reads as "Deck is Linux-only," rewrite it — measurement 4 says that is false.

- [ ] **Step 3: Write the rollout note**

Create `docs/deploy/pr0-capability-tokens-rollout.md`:

````markdown
# PR0 rollout — Agent Mail capability tokens

Four ordered steps. **Steps 1 and 2 provision the operator credential; steps 3
and 4 provision the agents'.** They are different credentials with different
lifetimes, and each needs its own restart — the backend loads the operator token
at import, while agents obtain session tokens by registering. Doing 4 before 3
locks every agent out of mail.

Autonomy stays **off** for the whole sequence. Nothing here needs a dispatch to
verify, and a dispatch mid-rollout would register against a half-configured
backend.

## Step 1 — write the operator token

```bash
openssl rand -hex 32                     # 32 bytes is a floor, not a suggestion
```

Put it in `backend/.env` as `operator_token`:

```
operator_token=<the value>
```

Then:

```bash
chmod 600 backend/.env
```

`backend/.env` is already gitignored (`.gitignore:27` is a bare `.env`, which git
matches at any depth) — do not add another rule. The `chmod` is the part that is
not automatic.

**Never `export` this value.** `spawn_session` runs `subprocess.run(["tmux",
"new-session", ...])` with **no `env=` argument** (`app/services/agent_bridge/spawn.py:79-84`),
so the tmux server inherits the backend process's environment, and any pane can
read it with `tmux show-environment -g`.
A secret exported into the shell that launched the backend is a secret every
agent can read, which defeats the entire point of a credential agents are not
given.

`hmac.compare_digest` protects the comparison against timing attacks. Nothing
protects a short secret from being guessed at loopback speed, which is why the
floor is 32 bytes.

## Step 2 — restart the backend

```bash
# whatever you use to run it; the point is a NEW process
```

`settings = Settings()` runs at import (`backend/app/config.py:57`), so the value
is read once per process. Until this restart, every operator-gated route answers
`503 operator_token_unconfigured` — which is the intended fail-closed posture,
not a bug.

**Verify before continuing:**

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST http://127.0.0.1:8000/api/v1/agent-teams/github-scopes/1/workspaces/1/force-release \
  -H 'Content-Type: application/json' -d '{}'
# expect 401 -- the route exists and demands a credential

curl -s -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:8000/api/v1/agent-teams/github-scopes/1/workspaces \
  -H "X-Deck-Operator-Token: $(grep '^operator_token=' backend/.env | cut -d= -f2-)"
# expect 200 or 404 -- authenticated; 404 only means scope 1 does not exist
```

A `503` on the second call means the restart did not pick up the file. A `401`
means the value does not match — check for a trailing newline or a quoted value.

**Do not put the token in shell history.** The `grep | cut` form above reads it
from the file rather than typing it. If you type it once, clear the line.

## Step 3 — restart the agent panes

Each agent registers on its next MCP call and receives a capability token, once,
in the registration response. The shim stores it and sends it as
`X-Deck-Session-Token` from then on (Task 6).

Until a pane restarts it holds no token. That is exactly why step 4 comes last:
with `mail_capability_tokens_required = False`, tokenless writes still work and
log `capability_token_missing` once per member — so this step's progress is
observable in the backend log.

**Verify before continuing:** the log should show no new
`capability_token_missing` lines for members whose panes you restarted. A member
that still logs it has a pane running pre-upgrade shim code.

## Step 4 — enforce

Add to `backend/.env`:

```
mail_capability_tokens_required=true
```

Restart the backend again. From this point:

- A mail write with no credential is `401 session_token_required`.
- A write with a token matching no session is `401 session_token_invalid` — an
  invalid token is never treated as an absent one.
- Agent registration on a host where the pane cannot be derived from the kernel
  refuses with `bind_unverifiable`. On Linux this means the peer process is
  gone; on macOS it means always, which is why the README lists Linux as a
  prerequisite for this feature.
- The Agent Mail **UI** needs the operator token pasted into Config → Operator
  token, per tab. Without it, sending mail from the UI answers
  `401 session_token_required` and the UI says so.

**Rollback** is this step in reverse: set `mail_capability_tokens_required=false`,
restart the backend. Grace mode returns and tokenless writes work again. The
operator token stays configured and the operator routes stay gated — that half
took effect at step 2 and is not covered by the flag.

## What changes immediately at step 2, before enforcement

Two behaviours do not wait for the flag, and both are intentional:

- **Force-release and the workspace listing require the operator token.** An
  unconfigured install has no working operator route at all. A destructive route
  with no credential should be closed rather than open.
- **The force-release mismatch message no longer contains a lease token.**
  It previously interpolated the live token into an HTTP 409 body, making two
  unauthenticated calls enough to force-release any agent's workspace: guess,
  read the real token from the refusal, replay. The message now names the item,
  never either value.

## Rotating the operator token

Replace it in `backend/.env` and restart the backend. There is no overlap
window: the old value dies with the old process. Acceptable here because the
population holding it is one human, not 150 panes — every open browser tab needs
the new value pasted, and `sessionStorage` means a tab that is closed and
reopened asks anyway.
````

- [ ] **Step 4: Check the note against the code it describes**

Not a proofread — a verification. Each of these is a claim the note makes that the reader cannot check:

```bash
cd backend
grep -n 'settings = Settings()' app/config.py          # the import-time claim
grep -n '^\.env$' ../.gitignore                        # the bare-.env claim
git check-ignore -v .env                               # and the consequence
grep -n 'new-session' app/services/agent_bridge/spawn.py   # note: no env= is passed
```

If `settings = Settings()` is not at `config.py:57` after Task 1's edit, fix the line number in the note. Task 1 inserts two settings between `:49` and `:51`, so **it will have moved** — this is the one number in this task guaranteed to be stale by the time you write it. Read it, do not copy it.

- [ ] **Step 5: Confirm the curl commands actually work**

Run both verification commands from step 2 against the running backend, with a real `operator_token` configured. A rollout note whose verification step does not run is worse than none: it teaches the operator to skip verification.

The paths were verified against source while writing this plan: force-release is
`/github-scopes/{scope_id}/workspaces/{workspace_id}/force-release` (`agent_teams.py:673`) under the
`/api/v1/agent-teams` prefix (`router.py:62`), and the listing is `/github-scopes/{scope_id}/workspaces` (`:550-551`).
Task 9 rewrote force-release's body, not its path. If a command 404s on a path
rather than on a missing scope, fix the note rather than the route.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/deploy/pr0-capability-tokens-rollout.md
git commit -m "docs: Linux prerequisite and the PR0 rollout sequence

Two facts about PR0 are invisible in its diff.

Pane binding reads /proc/net/tcp and /proc/<pid>/stat, so it needs Linux. The
README's prerequisite list named only Python, Node, and an agent CLI. The bullet
is scoped to the feature rather than the app: on macOS everything else works and
agents simply register unbound, so claiming 'Deck requires Linux' would be wrong
in the direction that costs a user the whole app.

The rollout is four ordered steps with two restarts for two credentials. The
backend restarts to LOAD the operator token, because settings is constructed at
import; panes restart to OBTAIN session tokens. Flipping the enforcement flag
before the panes restart locks every agent out of mail. Spec 3.6a's warning is
that an operator who reads 'restart the panes' and stops has provisioned
nothing, so the note states which restart does what, in order, with a
verification command between each pair.

backend/.env needed no gitignore instruction -- .gitignore:27 is a bare .env,
which git matches at any depth (verified with git check-ignore). The chmod 600
is the part that is not automatic, and the note says not to export the value:
spawn_session starts tmux with no env=, so an exported secret is readable by
every pane with tmux show-environment -g.

Spec: 2026-08-05-distinct-approver-identity-design.md section 3.8"
```

---
