# Phase G3 — Observed Session Durability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `sync_observed_sessions` from destroying the evidence that the dispatch ambiguity gate depends on, so the gate cannot be talked into dispatching a second owner onto an occupied slot.

**Architecture:** Three tasks in one PR, all in the session-registry layer. Task 1 makes the observed-row retention rule pid-aware, so a pane that is demonstrably alive is not deleted merely because one discovery pass failed to see it. Task 2 makes a pane's own tmux environment the authority on which slot it belongs to, so a row that *is* rebuilt comes back slot-bound instead of orphaned. Task 3 keeps the `strict=True` flag that PR #310 added — the failure it guards is reachable — and closes the one escape route that is a parsing bug rather than a genuine inability to observe.

**Tech Stack:** FastAPI, async SQLAlchemy 2.0 (`Mapped`/`mapped_column`), aiosqlite, pytest + pytest-asyncio. No frontend change. No schema change, no migration.

**Prior plan:** `docs/superpowers/plans/2026-08-02-phase-g2-session-lifecycle.md`. This is the follow-up to that plan's **Task 13**, which shipped in PR #310. Read Task 13 before starting — this plan repairs the gate it introduced, and reuses its `nudgeable_sessions_for_slot` unchanged.

---

## Why this PR exists

PR #310's Task 13 added a fail-closed guard to `_session_ambiguity_note`:

```python
        if not candidates and known_before:
            return (f"Discovery found no sessions for this slot, but {known_before} "
                    "was expected. Treating zero as unverified rather than empty.")
```

The intent is right: zero sessions where one was expected means the evidence is untrustworthy, so hold rather than dispatch. The defect is that the guard is load-bearing on state **its own call deletes**. Three lines earlier it calls `sync_observed_sessions`, which calls `_remove_stale_observed_sessions`, which deletes every observed row the current discovery pass did not return. So:

- **Poll 1** — `known_before = 1`, `candidates = 0`. The guard fires. Correct. But the row is already gone.
- **Poll 2** — `known_before = 0`, `candidates = 0`. `not candidates and known_before` is `False`. The gate returns `None`. Dispatch proceeds onto a slot that still has a live agent on it.

Measured, at PR #310's tip (`806ec3b`):

```
initial nudgeable: 1
--- poll 1 ---
note: Discovery found no sessions for this slot, but 1 was expected...
nudgeable rows left after sync: 0
--- poll 2 (same dead tmux) ---
note: NONE -> WOULD DISPATCH
```

This is the same defect family as Findings 17–20: **a signal that answers a question it is no longer being asked.** The gate asks "is a session on this slot?" and reads a DB row. But that row is a *cache of a tmux observation*, rebuilt from scratch every poll. Its lifetime is the last successful discovery pass; the question's lifetime is the whole dispatch.

**The fix is not in the gate.** Two smaller fixes upstream remove the condition the gate is trying to defend against, and then the guard is simply never reached by this path.

### Why not "have the gate consult pid liveness" (the shape this PR started as)

The original shape was to have `_session_ambiguity_note` check pid liveness instead of row existence. Research killed it, and the reason matters:

**pid liveness proves a pane is alive; it cannot prove the pane belongs to *this slot*.** The delete takes `team_slot_id` and `team_preset_id` with it. Measured — same pane, before/after a discovery blip and a recovery:

```
1. seeded, slot-bound, pid alive
   key=tmux:%1 slot=2 pid=3440094 cwd=/tmp/r preset=1     nudgeable_for_slot: 1
2. after blip (row deleted -> binding gone with it)
   (none)                                                 nudgeable_for_slot: 0
3. after recovery
   key=tmux:%1 slot=None pid=3440094 cwd=/tmp/r preset=None   nudgeable_for_slot: 0
```

The pid survives. The slot does not. A gate holding only a pid has nothing to compare it against — and in the live DB two slots of the same preset routinely share a `repo_path`, so cwd cannot disambiguate either. Keeping the *intent* (trust durable process evidence over a rebuilt row) while moving it to where the binding still exists is what Tasks 1 and 2 do.

### Why the loss is frequent, not exotic

`discover_agent_sessions` returns `[]` — not an exception — for tmux missing, non-zero exit, and `TimeoutExpired` (`agent_bridge/discovery.py:98-116`). `[]` is indistinguishable from "no panes", so the deletion runs.

Worse, a pane is only recognised as an agent if `provider.is_process_match(command, pid)` returns `True`, and all five live tizonia panes report `pane_current_command = node`, not `codex`:

```
tizonia-openmax-il-7845:0.0|159009|node
tizonia-openmax-il-afde:0.0|149168|node
tizonia-openmax-il-b19f:0.0|149179|node
tizonia-openmax-il-fd9c:0.0|379552|node
tizonia-openmax-il-fe2f:0.0|149190|node
```

So every live pane matches only via `has_binary_descendant` (`providers/base.py:66-110`), which shells out to `pgrep -a -P` **per process-tree level** with `timeout=5`, and returns `False` on any `SubprocessError` — timeout included. Under the load Finding 11 documented (concurrent C++ builds that OOM'd the host), a slow `pgrep` degrades to "this pane is not an agent" → "no sessions on this slot" → row deleted. Evidence loss is coupled to host load, i.e. precisely when dispatch decisions matter most.

There are **eight** callers of `sync_observed_sessions` (`api/v1/agent_mail.py:37`, three inside the service, `external_agent_mail_service.py:138`, `agent_team_service.py:205` and `:427`, and the dispatch gate). Seven are lenient best-effort refreshes. Any one of them, including a background UI poll, can erase the dispatch gate's evidence. That is why the fix belongs in the shared retention rule and not at one call site.

### And `[]` is not the only failure mode — some failures raise

This matters enough to state separately, because an earlier draft of this plan got it wrong and told you to delete `strict=True` on the strength of the three `return []` paths above.

**The `try` in `discover_agent_sessions` closes at `:116`.** `get_providers()` (`:100`) is above it, and the whole per-pane match loop (`:118-141`) is below it. So the three `return []` paths describe what happens to `subprocess.run` for `list-panes` — and nothing else. Measured by injecting each exception at that call:

```
  CAUGHT  -> returns []    FileNotFoundError (tmux absent)
  CAUGHT  -> returns []    TimeoutExpired
  ESCAPES -> OSError: [Errno 12] Cannot allocate memory
  ESCAPES -> PermissionError: [Errno 13] Permission denied
  ESCAPES -> SubprocessError: boom
```

`OSError(ENOMEM)` is what a failed `fork` raises — **the same memory pressure that makes evidence loss frequent in the first place.** So the two failure modes are not alternatives; they are two faces of one cause, and a host under load can produce either. There is a second, unrelated escape as well: `argv0_name(" ")` raises `IndexError`, because `if not command` rejects `""` but not `" "`, and that call sits inside the loop below the `try`.

`strict=True` therefore guards a **reachable** failure, and Task 3 hardens it rather than removing it.

---

## Global Constraints

These apply to **every** task. Several are safety rules earned from live incidents. They are carried forward verbatim in intent from the G2 plan because the environment has not changed.

**Working environment — you are on the SAME machine as the live soak**

- Work **only** in `/home/juan/work/repos/juanrubio/claude-deck-g1`.
- **Never** touch `/home/juan/work/repos/juanrubio/claude-deck`. It holds `backend/claude_registry.db` — 28 work items, the evidence that made Findings 17/18/19 provable. It cannot be regenerated, and it also serves the running backend.
- **Never** touch `/home/juan/work/repos/tizonia/`. Five tmux sessions hold it as cwd right now. Note this plan quotes their tmux environment; that was read with `tmux show-environment`, which is read-only. **Do not `tmux send-keys`, kill, or otherwise disturb those panes.** A test can reach a real pid without touching the directory — see Task 1 Step 1 on why the tests use `os.getpid()`.
- **`claude-deck-g1` is a git worktree of the live checkout, not a clone.** They share one object store, one ref namespace, one stash, one index lock. Therefore: no `git worktree prune`, `git gc`, `git stash`, `git reset --hard`, `git branch -f`, ref deletion, or checkout of a branch the live worktree holds.
- A backend `uvicorn` is running. Do not restart, stop, or reload it. `database_url` defaults to `sqlite+aiosqlite:///./claude_registry.db` — **relative to process CWD** — so anything run from the live checkout's `backend/` touches the live DB. Run tests from `claude-deck-g1/backend` only.
- Autonomy is **OFF** (`agent_team_presets.autonomy_enabled = 0`, both presets). Leave it at 0. Do not enable it "to test".

**Git**
- Branch from and target `feature/autonomous-github-dispatch`.
- **PR #310 is merged.** It landed as merge commit `2801556` on 2026-08-04, so this prerequisite is already satisfied — you do not need to wait for anything. This plan's line numbers and baselines were all measured at PR #310's tip (`806ec3b`), and `git diff 806ec3b 2801556 -- backend/ frontend/` is **empty**: the merge changed no code, only added this plan document. So every line number and every count below still holds exactly as written at the branch tip you will branch from. Start with:
  ```bash
  cd /home/juan/work/repos/juanrubio/claude-deck-g1
  git fetch origin
  git checkout -b feature/autonomous-github-dispatch-phase-g3 origin/feature/autonomous-github-dispatch
  ```
  Use `origin/feature/autonomous-github-dispatch`, **not** the local branch of that name — the local one is checked out in the live worktree.
- Never merge, self-merge, or push to `master`.
- Never `git checkout -- <file>` on uncommitted work. Reverse an edit by exact string.

**Forbidden operations**
- Do **not** add any new `dispatch_status` value. This plan needs none.
- Do **not** change the signature of `discover_agent_sessions`. Measured: **27 patch/`setattr` statements across 10 test files** (`test_registry.py`, `test_agent_team_service.py`, `test_github_workspace_service.py`, `test_github_workspace_api.py`, `test_agent_team_api.py`, `test_external_api.py`, `test_github_dispatch_service.py`, `test_agent_bridge_discovery.py`, `test_agent_bridge_attachments.py`, `test_multi_provider_smoke.py`), and **6 call sites in `app/`** — `api/v1/agent_bridge/router.py:123`, `github_workspace_service.py:457`, `agent_mail_service.py:355`, `agent_team_service.py:1139`, `cc_bridge/discovery.py:35`, `agent_bridge/attachments.py:170`. Only the third is the mail path. Making failure explicit *there* is a much larger, separate change. This plan deliberately fixes the consequence instead.
- Do **not** add keys to the dict `discover_agent_sessions` returns. `tests/test_agent_bridge_discovery.py:76-94` asserts the returned dict by **exact equality**; a new key fails it. Task 2 consumes a key that already exists.
- Do **not** spawn or kill agent sessions. Do not hand-edit DB rows. Do not restart the backend. Do not retry work item 23 or any other escalated item.

**Code style**
- Type hints throughout; `async`/`await` for all DB access.
- Datetimes: `datetime.utcnow()`, matching every neighbouring call site. The suite already emits deprecation warnings for this; do **not** "fix" them here.
- Follow the existing predicate style in `agent_mail_service.py`: small private methods, early `return None` / `return False`, one reason per guard.

**Testing**
- **Use `venv`, not `.venv`.** Both exist in `claude-deck-g1/backend`; `.venv` has no pytest. Do not try to fix `.venv`.
- Always `cd` to the **g1** backend before pytest — `database_url` is CWD-relative.
- **Measured baselines at PR #310's tip.** These are measurements, not predictions:

  | Command | Baseline | After the whole PR |
  |---|---|---|
  | `python -m pytest tests/agent_teams/test_github_dispatch_service.py tests/agent_mail/test_registry.py tests/test_agent_bridge_discovery.py -q` | **147 passed** | **157 passed** |
  | `python -m pytest tests/test_providers.py -q` | **9 passed** | **11 passed** |
  | `python -m pytest tests/agent_teams/ tests/agent_mail/ -q` | **444 passed** | **454 passed** |
  | `python -m pytest tests/ -q` | **610 passed, 1 failed** | **622 passed, 1 failed** |

  Both columns are measurements. The right-hand one was produced by applying this plan's own code — all three production edits and all twelve tests, exactly as written below — and running each command. It is not arithmetic on the left-hand column.

  The scoped-suite command in the first row is the one to use per task; it is the tightest set covering the three files Tasks 1 and 2 touch. Task 3 also touches `tests/test_providers.py`, which that set does **not** include, so Task 3 runs both.
- Known pre-existing failure: `tests/test_multi_provider_smoke.py::test_agent_bridge_session_filter_smoke` (stale monkeypatch, `:54`). **Report it, do not fix it** — an issue is owed separately.
- Every task ends green. If a test fails for a reason your task did not cause, **report it, do not rewrite it.**

**Stop and report** if a step's preconditions do not match what you find. A moved line number is fine to adapt to. A different *shape* — the function doing something other than described — means the reasoning behind the task may not hold, and you should stop.

---

## File Structure

No new files, no schema change. Two backend modules and three test files.

| File | Responsibility here | Tasks |
|---|---|---|
| `backend/app/services/agent_mail_service.py` | Owns the session registry: which observed rows are retained, and which member (hence slot) each pane binds to | 1, 2 |
| `backend/app/services/providers/base.py` | Names the binary behind a pane command; must not raise on a blank one | 3 |
| `backend/tests/agent_mail/test_registry.py` | Retention and binding tests — this is where `sync_observed_sessions` is already tested | 1, 2 |
| `backend/tests/agent_teams/test_github_dispatch_service.py` | The end-to-end poll-1-then-poll-2 regression, and the strict-path hold | 1, 3 |
| `backend/tests/test_providers.py` | `argv0_name` and blank-pane discovery coverage — this file already tests `is_process_match` | 3 |

`backend/app/services/github_dispatch_service.py` appears in **no** task's edit list. Task 3 touches it only to prove a test bites, and reverts. If it shows up in `git status` when you commit, something went wrong.

`agent_mail_service.py` is large and this PR adds one method and two guards to it. Do **not** split it — it is the live soak's session registry and a reorganisation would make the diff unreviewable.

---

### Task 1: A live pane is not a stale row

**Files:**
- Modify: `backend/app/services/agent_mail_service.py:534-556` (`_remove_stale_observed_sessions`)
- Test: `backend/tests/agent_mail/test_registry.py`
- Test: `backend/tests/agent_teams/test_github_dispatch_service.py`

**Interfaces:**
- Consumes: `_pid_is_running(pid: Optional[int]) -> bool` (`agent_mail_service.py:607`) — already exists, already used by `_effective_status`. Do **not** write a second liveness helper.
- Produces: no new public API. `_remove_stale_observed_sessions` keeps its signature `(db, active_observed_keys: set[str]) -> None`; only its deletion predicate changes.

This is the whole fix for Finding 20. Everything else in this PR is repair of the surrounding blast radius.

The current rule deletes on a single signal — "discovery did not return this key this pass":

```python
        for session in result.scalars().all():
            if session.session_key in active_observed_keys:
                continue
            affected_member_ids.add(session.member_id)
            await db.delete(session)
```

`_effective_status` (`:618-641`) already refuses to call an observed row offline when its pid is running — that is Finding 17's rule, and it is why the five live observed rows are **over a week** past `OBSERVED_TTL_SECONDS` (300s) and still nudgeable. (Measured at 616,682s on 2026-08-04; the figure grows with wall-clock, so do not treat it as a fixture value — the point is the ratio, roughly 2000× the TTL.) **Retention did not get the same treatment.** So a row can be simultaneously "too alive to mark offline" and "stale enough to delete." Task 1 closes that gap.

Note the asymmetry this deliberately creates, and do not "make it consistent": a row whose pid is dead is still deleted immediately, as today. Retention becomes *pid-aware*, not *pid-only*.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/agent_mail/test_registry.py`. Reuse the file's existing `db` fixture (from `tests/agent_mail/conftest.py`), its `svc` fixture (`:30`), and its `_slot` helper (`:44`) — do not write new ones.

The test needs a pid that is genuinely running, because `_pid_is_running` calls `os.kill(pid, 0)` for real. Use `os.getpid()`: the pytest process is alive by definition, needs no fixture, and reaches no agent pane. `os` is already imported at `:2`.

```python
@pytest.mark.asyncio
async def test_sync_observed_keeps_row_whose_pid_is_alive(db, svc, tmp_path):
    """A single failed discovery pass must not delete a live pane's row.

    discover_agent_sessions() returns [] for tmux-missing, non-zero exit, and
    timeout, so [] cannot be read as "no panes exist".
    """
    cwd = tmp_path / "obs"
    cwd.mkdir()
    preset, slot = await _slot(db, str(cwd), "Owner")
    member = await svc.get_or_create_slot_member(db, slot)
    db.add(
        MailAgentSession(
            member_id=member.id,
            team_preset_id=slot.preset_id,
            team_slot_id=slot.id,
            source="observed",
            provider="codex-cli",
            session_key="tmux:%1",
            pane_id="%1",
            tmux_target="obs:0.0",
            cwd=str(cwd),
            pid=os.getpid(),
            mailbox_status="observed",
            last_seen_at=datetime.utcnow(),
        )
    )
    await db.commit()

    assert len(await svc.nudgeable_sessions_for_slot(db, slot.id)) == 1

    with patch("app.services.agent_mail_service.discover_agent_sessions", return_value=[]):
        await svc.sync_observed_sessions(db)

    kept = await svc.nudgeable_sessions_for_slot(db, slot.id)
    assert len(kept) == 1
    assert kept[0].team_slot_id == slot.id


@pytest.mark.asyncio
async def test_sync_observed_still_deletes_row_whose_pid_is_dead(db, svc, tmp_path):
    """Retention becomes pid-aware, not pid-only. A dead pane still goes."""
    cwd = tmp_path / "obs"
    cwd.mkdir()
    preset, slot = await _slot(db, str(cwd), "Owner")
    member = await svc.get_or_create_slot_member(db, slot)
    db.add(
        MailAgentSession(
            member_id=member.id,
            team_preset_id=slot.preset_id,
            team_slot_id=slot.id,
            source="observed",
            provider="codex-cli",
            session_key="tmux:%2",
            pane_id="%2",
            tmux_target="obs:0.1",
            cwd=str(cwd),
            pid=None,
            mailbox_status="observed",
            last_seen_at=datetime.utcnow(),
        )
    )
    await db.commit()

    with patch("app.services.agent_mail_service.discover_agent_sessions", return_value=[]):
        await svc.sync_observed_sessions(db)

    assert await svc.nudgeable_sessions_for_slot(db, slot.id) == []


@pytest.mark.asyncio
async def test_sync_observed_deletes_row_whose_pid_is_gone(db, svc, tmp_path):
    """A NON-NULL pid that is not running must still be deleted.

    This is the test that pins the rule to _pid_is_running rather than to
    "has a pid at all". See the note below on why the pid=None test alone is
    not sufficient.
    """
    cwd = tmp_path / "obs"
    cwd.mkdir()
    preset, slot = await _slot(db, str(cwd), "Owner")
    member = await svc.get_or_create_slot_member(db, slot)
    db.add(
        MailAgentSession(
            member_id=member.id,
            team_preset_id=slot.preset_id,
            team_slot_id=slot.id,
            source="observed",
            provider="codex-cli",
            session_key="tmux:%3",
            pane_id="%3",
            tmux_target="obs:0.2",
            cwd=str(cwd),
            pid=999999,
            mailbox_status="observed",
            last_seen_at=datetime.utcnow(),
        )
    )
    await db.commit()

    with patch(
        "app.services.agent_mail_service.discover_agent_sessions", return_value=[]
    ), patch.object(type(svc), "_pid_is_running", return_value=False):
        await svc.sync_observed_sessions(db)

    assert await svc.nudgeable_sessions_for_slot(db, slot.id) == []
```

**Why three tests and not two.** `pid=None` expresses "dead" without inventing a pid that might exist on the machine, and `_pid_is_running` does return `False` for a falsy pid (`:608-609`). But the alive/`None` pair is **not sufficient to pin the rule**, and this was caught in review rather than by me:

An implementation that never calls `_pid_is_running` at all —

```python
            if session.pid is not None:      # WRONG: retains dead pids too
                continue
```

— passes both of them. The alive row has a non-null pid so it is kept; the `None` row has no pid so it is deleted. **Measured, not argued:** that mutant was applied to the real service and both tests passed (`2 passed`). The third test kills it (`1 failed` against the mutant, `3 passed` against the correct implementation), because it supplies a non-null pid *and* forces `_pid_is_running` to `False`, so only an implementation that actually consults liveness can satisfy it.

`patch.object(type(svc), ...)` patches the class, not the instance, because `svc` is a shared service object and the call is `self._pid_is_running(...)`. Do not patch the module-level name — there isn't one; it is a method.

Do **not** use a real dead pid instead of mocking. Any number you pick might be alive on this host, and 999999 exceeds the default `pid_max` on many systems but not all — the mock is what makes this deterministic.

- [ ] **Step 2: Run the tests to verify the first one fails**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate
python -m pytest tests/agent_mail/test_registry.py -q -k "pid_is_alive or pid_is_dead or pid_is_gone"
```

Expected, measured: **`1 failed, 2 passed`**. The failure is `test_sync_observed_keeps_row_whose_pid_is_alive` with `assert 0 == 1` — the row was deleted. The other two **PASS** already: they are the guards that stop Step 3 from over-correcting into "never delete anything," and both must still pass afterwards.

- [ ] **Step 3: Make retention pid-aware**

In `_remove_stale_observed_sessions`, add one guard:

```python
    async def _remove_stale_observed_sessions(
        self, db: AsyncSession, active_observed_keys: set[str]
    ) -> None:
        """Drop Agent Bridge-only sessions that are no longer discoverable."""
        result = await db.execute(
            select(MailAgentSession).where(MailAgentSession.source == "observed")
        )
        affected_member_ids: set[int] = set()
        for session in result.scalars().all():
            if session.session_key in active_observed_keys:
                continue
            # Absence from one discovery pass is not evidence of death.
            # discover_agent_sessions() returns [] for tmux-missing, non-zero
            # exit and timeout, and a pane only registers as an agent if
            # is_process_match succeeds -- which for every live pane here means
            # a pgrep tree walk that returns False on timeout. Deleting on that
            # signal alone destroys the binding the dispatch ambiguity gate
            # reads, and the gate cannot detect a loss whose evidence is gone.
            # Mirrors _effective_status, which already refuses to call a
            # pid-alive observed row offline.
            if self._pid_is_running(session.pid):
                continue
            affected_member_ids.add(session.member_id)
            await db.delete(session)

        if not affected_member_ids:
            return

        await db.flush()
        for member_id in affected_member_ids:
            await self._remove_empty_observed_member(db, member_id)
```

- [ ] **Step 4: Run the tests to verify all three pass**

```bash
python -m pytest tests/agent_mail/test_registry.py -q -k "pid_is_alive or pid_is_dead or pid_is_gone"
```
Expected: `3 passed`.

- [ ] **Step 5: Add the end-to-end regression that Finding 20 actually described**

The unit tests above prove the retention rule. This one proves the *gate* no longer flips between polls, which is the defect that would have dispatched a second owner. Add to `backend/tests/agent_teams/test_github_dispatch_service.py`, reusing that file's `_team` helper (`:65`) and `_seed_observed_panes` (`:279`) — read both before writing, and do not add a second copy of either.

The file has an autouse fixture (added by PR #310, `no_discovered_panes`) that patches `app.services.agent_mail_service.discover_agent_sessions` to `lambda: []`. This test needs to drive that patch itself, so override it locally with `monkeypatch` inside the test — `monkeypatch` applied in the test body wins over the autouse fixture's earlier `setattr`.

**Add `import os` to the top of this file first.** Unlike `test_registry.py`, `test_github_dispatch_service.py` does **not** import `os`; its imports start at `:2` with `from datetime import datetime, timedelta`. Without it this test fails with `NameError: name 'os' is not defined` at the `pid=os.getpid()` line — measured, so do not skip it. Put `import os` above the `from datetime` line, keeping stdlib imports alphabetical as the file already does.

```python
@pytest.mark.asyncio
async def test_ambiguity_gate_is_stable_when_discovery_blips(db, monkeypatch):
    """Two consecutive failed discoveries must not become permission to dispatch.

    Finding 20: the fail-closed guard read state that sync_observed_sessions
    deleted, so poll 1 held and poll 2 saw an empty slot and dispatched.
    """
    preset, slots, scope = await _team(db)
    slot = slots[0]
    member = await agent_mail_service.get_or_create_slot_member(db, slot)
    db.add(
        MailAgentSession(
            member_id=member.id,
            team_preset_id=slot.preset_id,
            team_slot_id=slot.id,
            source="observed",
            provider=slot.provider,
            session_key="tmux:%1",
            pane_id="%1",
            tmux_target="live:0.0",
            cwd=slot.repo_path,
            pid=os.getpid(),
            mailbox_status="observed",
            last_seen_at=datetime.utcnow(),
        )
    )
    await db.commit()

    monkeypatch.setattr(
        "app.services.agent_mail_service.discover_agent_sessions", lambda: []
    )

    first = await github_dispatch_service._session_ambiguity_note(db, slot.id)
    second = await github_dispatch_service._session_ambiguity_note(db, slot.id)

    # The row survives, so the gate reads true state rather than a hole it made.
    assert len(await agent_mail_service.nudgeable_sessions_for_slot(db, slot.id)) == 1
    assert first is None
    assert second == first
```

`_team` returns `(preset, [architect, backend], scope)` — verified at `:109`, note the slot list is the **middle** element. It creates the preset, both slots with `provider="codex-cli"` and `repo_path="/tmp/r"`, the scope, and five `GithubWorkspace` rows. If its shape differs from this when you read it, **adapt the test, do not change `_team`** — a dozen other tests depend on it.

`MailAgentSession` and `datetime` are already imported in this file (`:20`, `:2`). **`os` is not** — add `import os` to the stdlib import block at the top. `agent_mail_service` and `github_dispatch_service` are imported at `:26-27`.

Note what the assertion says and does not say. It does **not** assert the gate holds; it asserts the gate is **stable and truthful**. With the row retained there is exactly one nudgeable session, which is the unambiguous case, so `None` is the correct answer both times. The bug was never "poll 1 said the wrong thing" — poll 1 was right. The bug was that poll 1 and poll 2 disagreed because the first call destroyed the evidence.

- [ ] **Step 6: Run it**

```bash
python -m pytest tests/agent_teams/test_github_dispatch_service.py -q -k "discovery_blips"
```
Expected: `1 passed`. Before Step 3's guard exists this same test fails with `assert 0 == 1` — measured — so if it passes on a tree where you have not yet made retention pid-aware, the test is not exercising what it claims.

- [ ] **Step 7: Run the scoped suites**

```bash
python -m pytest tests/agent_teams/test_github_dispatch_service.py tests/agent_mail/test_registry.py tests/test_agent_bridge_discovery.py -q
```
Expected: **151 passed** — the measured 147 baseline plus this task's 4 new tests (3 in `test_registry.py`, 1 in `test_github_dispatch_service.py`).

Count the test *functions you added* and check the arithmetic yourself. Do not infer the total from a `-k` selection: `-k` matches substrings and will happily include pre-existing tests, which is how an earlier task in this series reported 7 new tests when it had written 6.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/agent_mail_service.py backend/tests/agent_mail/test_registry.py backend/tests/agent_teams/test_github_dispatch_service.py
git commit -m "fix(g3): a pid-alive pane is not a stale observed row"
```

---

### Task 2: A pane's tmux environment is the authority on its slot

**Files:**
- Modify: `backend/app/services/agent_mail_service.py:374-376` (the member-resolution chain in `sync_observed_sessions`), plus a new `_member_for_advertised_slot` inserted immediately above `_member_for_observed_session` at `:404`
- Test: `backend/tests/agent_mail/test_registry.py`

**Interfaces:**
- Consumes: `get_or_create_slot_member(db, slot) -> MailTeamMember` (`:148`); `derive_repo_identity(cwd) -> dict` from `app.utils.repo_utils`, already imported. `AgentTeamSlot` is already imported.
- Produces: `_member_for_advertised_slot(db, info: dict) -> MailTeamMember | None` — returns the slot member the pane's own tmux env names, or `None` when the env says nothing or the claim does not validate.

Task 1 stops the row being deleted, which is the fix. Task 2 repairs the case where a row legitimately *does* get rebuilt — after a genuine agent restart, or a pid that really did die — and comes back **orphaned**.

Measured. Same pane, discovery blip then recovery, with a registered MCP row 600s old:

```
CASE B: registered mcp row is 600s old
   before blip : slot=1 preset=1 pid=3443099 member=1
   after blip  : (no observed rows)
   after recov : slot=None preset=None pid=3443099 member=2   nudgeable_for_slot=0
```

The pane is alive and nudgeable in general, but invisible to `nudgeable_sessions_for_slot`, permanently. The path is: `_member_for_existing_observed_session` (`:478`) requires an existing row with a non-NULL `team_slot_id` on its very first line, so once deleted it returns `None`; the fallback `_member_for_observed_session` (`:404`) mints a **repo** member; and `sync_observed_sessions:395-396` then writes `session.team_slot_id = member.team_slot_id`, i.e. `NULL`.

The recovery in the fallback is not reliable, and the reason is another freshness coupling. It only rebinds by finding a non-observed row with a related pid — and `_registered_session_matches_observed` (`:515-532`) requires that row's `last_seen_at >= now - HEARTBEAT_TTL_SECONDS` (**180 seconds**). With the MCP row 10s old the slot recovers; at 600s it does not:

```
CASE A: registered mcp row is 10s old
   after recov : slot=1 preset=1 pid=3443094 member=1   nudgeable_for_slot=1
```

So slot identity currently depends on an MCP heartbeat having landed in the last three minutes. That is a cache, not an identity.

**There is a durable authority already in the system, and it is not in the DB.** `spawn_session` exports the slot id into the tmux session environment (`agent_team_service.py:618-626`), `discover_agent_sessions` reads it back via `_TEAM_ENV_KEYS` into `info["team_slot_id"]` (`agent_bridge/discovery.py:24-31`), and it matches the DB exactly on all five live sessions:

```
tizonia-openmax-il-afde  CLAUDE_DECK_TEAM_SLOT_ID=4   (DB: observed 301 -> slot 4)
tizonia-openmax-il-b19f  CLAUDE_DECK_TEAM_SLOT_ID=5   (DB: observed 302 -> slot 5)
tizonia-openmax-il-fe2f  CLAUDE_DECK_TEAM_SLOT_ID=6   (DB: observed 303 -> slot 6)
tizonia-openmax-il-7845  CLAUDE_DECK_TEAM_SLOT_ID=6   (DB: observed 308 -> slot 6)
tizonia-openmax-il-fd9c  CLAUDE_DECK_TEAM_SLOT_ID=6   (DB: observed 312 -> slot 6)
```

It survives row deletion, DB restarts, and heartbeat gaps, because it lives in the tmux server. `api/v1/agent_bridge/router.py:74-80` already trusts it for exactly this purpose (`_enrich_team_sessions`). The mail sync path is the one place that reads it and throws it away. Measured, with the env present and the fallback exhausted:

```
   discovered info carries: team_slot_id=1 team_preset_id=1
   after recov: slot=None preset=None member=2(repo)   nudgeable=0
```

Validate the claim rather than trusting it blindly — the env is set by our own launcher, but a stale `tmux show-environment` could name a deleted slot, and a pane could have been re-`cd`'d elsewhere.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/agent_mail/test_registry.py`. Reuse `db`, `svc`, `_slot`.

```python
@pytest.mark.asyncio
async def test_sync_observed_binds_slot_from_tmux_environment(db, svc, tmp_path):
    """A rebuilt row recovers its slot from the pane's own tmux env.

    The env is exported by spawn_session and read back by
    discover_agent_sessions, so it outlives both the row and any heartbeat.
    """
    cwd = tmp_path / "obs"
    cwd.mkdir()
    preset, slot = await _slot(db, str(cwd), "Owner")
    fake = [
        {
            "provider": "codex-cli",
            "provider_display_name": "Codex",
            "tmux_target": "obs:0.0",
            "session_name": "obs",
            "window_name": "main",
            "pane_id": "%1",
            "cwd": str(cwd),
            "pid": "4242",
            "status": "active",
            "team_preset_id": preset.id,
            "team_slot_id": slot.id,
        }
    ]
    with patch("app.services.agent_mail_service.discover_agent_sessions", return_value=fake):
        await svc.sync_observed_sessions(db)

    session = (
        await db.execute(
            select(MailAgentSession).where(MailAgentSession.session_key == "tmux:%1")
        )
    ).scalar_one()
    assert session.team_slot_id == slot.id
    assert session.team_preset_id == preset.id
    member = await db.get(MailTeamMember, session.member_id)
    assert member.participant_kind == "team_slot"


@pytest.mark.asyncio
async def test_sync_observed_ignores_env_slot_from_another_repo(db, svc, tmp_path):
    """An advertised slot whose repo does not match the pane's cwd is rejected."""
    slot_cwd = tmp_path / "slotrepo"
    slot_cwd.mkdir()
    pane_cwd = tmp_path / "elsewhere"
    pane_cwd.mkdir()
    preset, slot = await _slot(db, str(slot_cwd), "Owner")
    fake = [
        {
            "provider": "codex-cli",
            "provider_display_name": "Codex",
            "tmux_target": "obs:0.0",
            "session_name": "obs",
            "window_name": "main",
            "pane_id": "%1",
            "cwd": str(pane_cwd),
            "pid": "4242",
            "status": "active",
            "team_preset_id": preset.id,
            "team_slot_id": slot.id,
        }
    ]
    with patch("app.services.agent_mail_service.discover_agent_sessions", return_value=fake):
        await svc.sync_observed_sessions(db)

    session = (
        await db.execute(
            select(MailAgentSession).where(MailAgentSession.session_key == "tmux:%1")
        )
    ).scalar_one()
    assert session.team_slot_id is None
    member = await db.get(MailTeamMember, session.member_id)
    assert member.participant_kind == "repo"


@pytest.mark.asyncio
async def test_sync_observed_ignores_env_slot_that_no_longer_exists(db, svc, tmp_path):
    """A stale tmux env naming a deleted slot falls back, it does not crash."""
    cwd = tmp_path / "obs"
    cwd.mkdir()
    fake = [
        {
            "provider": "codex-cli",
            "provider_display_name": "Codex",
            "tmux_target": "obs:0.0",
            "session_name": "obs",
            "window_name": "main",
            "pane_id": "%1",
            "cwd": str(cwd),
            "pid": "4242",
            "status": "active",
            "team_preset_id": 999,
            "team_slot_id": 999,
        }
    ]
    with patch("app.services.agent_mail_service.discover_agent_sessions", return_value=fake):
        await svc.sync_observed_sessions(db)

    session = (
        await db.execute(
            select(MailAgentSession).where(MailAgentSession.session_key == "tmux:%1")
        )
    ).scalar_one()
    assert session.team_slot_id is None


@pytest.mark.asyncio
async def test_sync_observed_ignores_env_slot_with_a_different_provider(db, svc, tmp_path):
    """A pane advertising a slot whose provider disagrees is rejected."""
    cwd = tmp_path / "obs"
    cwd.mkdir()
    preset, slot = await _slot(db, str(cwd), "Owner")
    assert slot.provider == "codex-cli"
    fake = [
        {
            "provider": "claude-code",
            "provider_display_name": "Claude Code",
            "tmux_target": "obs:0.0",
            "session_name": "obs",
            "window_name": "main",
            "pane_id": "%1",
            "cwd": str(cwd),
            "pid": "4242",
            "status": "active",
            "team_preset_id": preset.id,
            "team_slot_id": slot.id,
        }
    ]
    with patch("app.services.agent_mail_service.discover_agent_sessions", return_value=fake):
        await svc.sync_observed_sessions(db)

    session = (
        await db.execute(
            select(MailAgentSession).where(MailAgentSession.session_key == "tmux:%1")
        )
    ).scalar_one()
    assert session.team_slot_id is None


@pytest.mark.asyncio
async def test_sync_observed_ignores_env_slot_whose_preset_disagrees(db, svc, tmp_path):
    """A reused slot id with a contradictory preset id must not bind.

    agent_team_slots.id is a rowid alias (no AUTOINCREMENT), so SQLite reuses
    freed ids. A pane whose env names a deleted slot can otherwise bind to
    whatever replacement slot inherited that id.
    """
    cwd = tmp_path / "obs"
    cwd.mkdir()
    preset, slot = await _slot(db, str(cwd), "Owner")
    fake = [
        {
            "provider": "codex-cli",
            "provider_display_name": "Codex",
            "tmux_target": "obs:0.0",
            "session_name": "obs",
            "window_name": "main",
            "pane_id": "%1",
            "cwd": str(cwd),
            "pid": "4242",
            "status": "active",
            "team_preset_id": preset.id + 500,
            "team_slot_id": slot.id,
        }
    ]
    with patch("app.services.agent_mail_service.discover_agent_sessions", return_value=fake):
        await svc.sync_observed_sessions(db)

    session = (
        await db.execute(
            select(MailAgentSession).where(MailAgentSession.session_key == "tmux:%1")
        )
    ).scalar_one()
    assert session.team_slot_id is None
```

`_slot` builds the slot with `provider="codex-cli"` and `repo_id` derived from the cwd you pass, which is why the panes above use `codex-cli` and the matching cwd. Check `_slot`'s body before relying on that — it is at `:44` and it returns `(preset, slot)`.

The provider test asserts `slot.provider == "codex-cli"` before doing anything else. That is deliberate: if `_slot`'s default provider ever changes, the test would otherwise still "pass" while no longer exercising a mismatch — the same silent-no-op trap PR2's Task 13 note warned about.

The preset test uses `preset.id + 500` rather than a literal, so it stays a genuine mismatch regardless of what ids the fixtures allocate.

- [ ] **Step 2: Run the tests to verify the first fails**

```bash
python -m pytest tests/agent_mail/test_registry.py -q -k "tmux_environment or another_repo or no_longer_exists or different_provider or preset_disagrees"
```

Expected, measured: **`1 failed, 4 passed`**. The one failure is `test_sync_observed_binds_slot_from_tmux_environment` with `assert None == 1`. The other four **PASS** already — they are the guards that stop Step 3 from trusting the env unconditionally, and each one must keep passing afterwards.

That four-pass-before is worth pausing on, because it is the fixture trap in this task. Those tests pass now for the *right* reason — with no resolver, nothing binds the slot, so a rejection is indistinguishable from "the feature does not exist yet." They only become meaningful once Step 3 lands. If any of the four turns red after Step 3, the resolver is trusting the env where it should not.

- [ ] **Step 3: Add the resolver and put it in the chain**

Insert this method immediately **above** `async def _member_for_observed_session` (`:404`):

```python
    async def _member_for_advertised_slot(
        self,
        db: AsyncSession,
        info: dict,
    ) -> MailTeamMember | None:
        """Bind a pane to the slot its own tmux environment advertises.

        spawn_session exports CLAUDE_DECK_TEAM_SLOT_ID into the tmux session
        environment and discover_agent_sessions reads it back, so this binding
        outlives the observed row, a DB restart, and any heartbeat gap. It is
        the only slot evidence that does not expire. The claim is still
        validated: a stale env can name a deleted slot, and a pane can be
        re-cd'd out of the slot's repo.
        """
        slot_id = info.get("team_slot_id")
        if not isinstance(slot_id, int):
            return None
        slot = await db.get(AgentTeamSlot, slot_id)
        if slot is None or slot.provider != str(info.get("provider") or "unknown"):
            return None
        preset_id = info.get("team_preset_id")
        if isinstance(preset_id, int) and preset_id != slot.preset_id:
            return None
        cwd = str(info.get("cwd") or "")
        if not cwd:
            return None
        try:
            if derive_repo_identity(cwd)["repo_id"] != slot.repo_id:
                return None
        except Exception:
            return None
        return await self.get_or_create_slot_member(db, slot)
```

`isinstance(slot_id, int)` rather than a truthiness check: `_clean_int` (`discovery.py:34-40`) returns `None` for unparseable values, and `router.py:76-78` guards the same field the same way. `bool` is an `int` subclass in Python but no code path can put a bool there.

**The preset check exists because SQLite reuses primary keys, and it closes a real misbinding.** This was raised in review and I confirmed it by measurement rather than accepting or dismissing it:

`agent_team_slots` is declared `id INTEGER NOT NULL, PRIMARY KEY (id)` with **no `AUTOINCREMENT`**, which makes `id` a rowid alias. SQLite then reuses the largest freed rowid. Measured: create slots 1 and 2, delete slot 2, create a new slot → it gets **id 2**.

So a pane whose tmux environment still advertises a deleted slot's id can bind to whatever *replacement* slot inherited that id. Provider and repo do not catch it, because a replacement slot in the same repo with the same provider is the normal case — that is precisely what "replacement" means. Probed end to end: pane advertises `slot=2, preset=1`; slot 2 is now a different slot in preset 2; without this check the row binds to it (`MISBOUND to the replacement slot`), and with it the pane falls back correctly.

`isinstance(preset_id, int) and ...` — not a bare inequality. A pane launched before `CLAUDE_DECK_TEAM_PRESET_ID` was exported, or whose env only carries the slot id, has `team_preset_id` absent or `None`; that must stay bindable on the slot id alone. Only a *present and contradictory* preset id is disqualifying. Do not tighten this into `preset_id != slot.preset_id`, which would reject every pane that advertises no preset.

This does not make env binding safe against **all** id reuse — a replacement slot in the *same* preset still shares both ids and remains indistinguishable. That residual case is out of scope and recorded in the Deferred section; the durable fix is `AUTOINCREMENT` (or a spawn-time UUID), which is a schema change and belongs in its own PR.

Then insert it into the resolution chain in `sync_observed_sessions` (`:374-376`):

```python
            member = await self._member_for_existing_observed_session(db, session, info)
            if member is None:
                member = await self._member_for_advertised_slot(db, info)
            if member is None:
                member = await self._member_for_observed_session(db, info)
```

Order matters, in both directions. It goes **after** `_member_for_existing_observed_session` so an intact row keeps deciding for itself — that path already validates pane id, target, pid, provider and repo, and changing which wins would be a behaviour change beyond this PR's scope. It goes **before** `_member_for_observed_session` because that one never returns `None`: it ends in `return await self._get_or_create_repo_member(db, cwd)`, so anything placed after it is dead code.

- [ ] **Step 4: Run the tests to verify all three pass**

```bash
python -m pytest tests/agent_mail/test_registry.py -q -k "tmux_environment or another_repo or no_longer_exists or different_provider or preset_disagrees"
```
Expected: `5 passed`.

- [ ] **Step 5: Run the scoped suites**

```bash
python -m pytest tests/agent_teams/test_github_dispatch_service.py tests/agent_mail/test_registry.py tests/test_agent_bridge_discovery.py -q
```
Expected: **156 passed** — 151 after Task 1, plus this task's 5.

Pay attention to `test_registry.py`'s existing observed-sync tests. Several seed a slot and a registered row and assert the observed row binds to the **slot** member (`:376-400` and the group from `:440` to `:600`). Those pass because their fake panes carry no `team_slot_id` key, so `_member_for_advertised_slot` returns `None` at its first guard and the existing pid path still runs. If any of them fails, **stop and report** — it means the ordering above is wrong, not that the test is.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agent_mail_service.py backend/tests/agent_mail/test_registry.py
git commit -m "fix(g3): observed rows recover their slot from the tmux environment"
```

---

### Task 3: Keep `strict=True`, close the escape it cannot survive, and finally test it

**Files:**
- Modify: `backend/app/services/providers/base.py:59-63` (`argv0_name` — three lines)
- Test: `backend/tests/test_providers.py` (two new tests)
- Test: `backend/tests/agent_teams/test_github_dispatch_service.py` (one new test, near `:1960`)

**Interfaces:**
- Consumes: `sync_observed_sessions(db, *, strict: bool = False) -> None` — **unchanged**, both the parameter and the gate's `strict=True` call site stay exactly as PR #310 shipped them.
- Produces: `argv0_name(command: str) -> str` — same signature, same return type. It stops raising `IndexError` on whitespace-only input and returns `""`, which every caller already handles because `""` was already a possible return.

**Read this before you start: an earlier draft of this task was wrong, and the correction is the task.**

The draft told you to delete `strict=True` on the grounds that `discover_agent_sessions` "cannot raise for any realistic failure." That claim came from reading the three `return []` paths at `:108-116` and generalising. It is false, and the review that caught it was right.

The `try` closes at `:116`. `get_providers()` at `:100` sits above it; the entire per-pane match loop at `:118-141` sits below it. Measured by injecting exceptions at the `subprocess.run` call:

```
  CAUGHT  -> returns []    FileNotFoundError (tmux absent)
  CAUGHT  -> returns []    TimeoutExpired
  ESCAPES -> OSError: [Errno 12] Cannot allocate memory
  ESCAPES -> PermissionError: [Errno 13] Permission denied
  ESCAPES -> SubprocessError: boom
```

`OSError(ENOMEM)` is what a failed `fork` raises. That is **the same host memory pressure that makes evidence loss frequent** — the two failure modes share one cause. And `strict=True` demonstrably does the right thing with it. Measured end to end against the real gate:

```
  seeded nudgeable = 1
  strict=True  -> HOLD: Session discovery failed, so the owning pane could not be co…
  rows after   = 1
  strict REMOVED, cold start -> NONE -> DISPATCHES on unknown state
```

Two things to read off that. First, `strict=True` produces its fail-closed note and the row survives — because the exception aborts the pass before `_remove_stale_observed_sessions` runs at all. Second, the cold-start case is why removal is not merely redundant but harmful: with no observed row, `known_before` is `0`, so the `not candidates and known_before` guard cannot fire, and there is nothing else left to hold on. Tasks 1 and 2 do **not** cover this. Task 1 protects a row that exists; here there is no row.

So this task does the opposite of the draft:

1. **Keep** `strict=True` and the `try`/`except` in `_session_ambiguity_note`. Change neither.
2. **Fix** the one escape that is a plain bug rather than a signal: `argv0_name(" ")` raises `IndexError`.
3. **Add** the regression test for the strict path whose absence was already flagged as a finding in this plan.

**Why fix `argv0_name` but keep `strict`?** They are different kinds of failure and deserve different treatment. `ENOMEM` is real information — the host genuinely cannot look right now, and holding is correct. A whitespace-only pane command is not information; it is a parsing gap, and letting it fail the whole discovery pass means one idle pane can block dispatch for every slot on the host. Fail closed on *inability to observe*; do not fail closed on *a pane you merely cannot name*.

- [ ] **Step 1: Confirm the bug before fixing it**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend
python -c "from app.services.providers.base import argv0_name; print(repr(argv0_name(' ')))"
```

Expected: `IndexError: list index out of range`. If it prints `''` instead, the function has already been fixed upstream — **stop and report**, because then this task's premise has moved and Step 4's test would pass without proving anything.

- [ ] **Step 2: Write the failing tests**

Add to `backend/tests/test_providers.py`, immediately above `test_opencode_home_respects_xdg_config_home`. That file already tests `is_process_match` and already patches `app.services.providers.base.subprocess.run` (`:98`, `:111`, `:124`), so it is the right home. It imports `SimpleNamespace` and `patch` at module level (`:2-3`); the second test re-imports them locally anyway, matching the file's own per-test import idiom.

```python
def test_argv0_name_tolerates_blank_commands():
    from app.services.providers.base import argv0_name

    # A whitespace-only pane command used to raise IndexError out of
    # discover_agent_sessions, which runs the match loop outside its try.
    assert argv0_name(" ") == ""
    assert argv0_name("\t") == ""
    assert argv0_name("") == ""
    assert argv0_name("  codex  ") == "codex"


def test_discovery_survives_a_blank_pane_command():
    from types import SimpleNamespace
    from unittest.mock import patch

    from app.services.agent_bridge.discovery import discover_agent_sessions

    tmux_output = "\n".join([
        "blank:0.0|blank|main|%1|/repo/a|111| ",
        "codexproj:0.0|codexproj|main|%2|/repo/b|222|codex",
    ])

    def fake_run(args, **_kwargs):
        if args[:2] == ["tmux", "list-panes"]:
            return SimpleNamespace(returncode=0, stdout=tmux_output, stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    with patch("app.services.agent_bridge.discovery.subprocess.run", side_effect=fake_run):
        sessions = discover_agent_sessions()

    assert [session["pane_id"] for session in sessions] == ["%2"]
```

**The blank command must not be on the last row.** `discover_agent_sessions` does `result.stdout.strip().splitlines()`, so a trailing `" "` on the final row gets stripped away and the row never reaches `argv0_name` — the test then passes against the unfixed code and proves nothing. I hit exactly that while measuring. The `codex` row must come second.

The `fake_run` fallback returns `returncode=1` rather than raising, because a matched pane triggers a `tmux show-environment` call; a non-zero return makes `_team_context_for_session` yield `{}` without an exception.

- [ ] **Step 3: Run them and watch them fail**

```bash
python -m pytest tests/test_providers.py -q -k "argv0 or blank_pane"
```

Expected: **2 failed**, both with `IndexError: list index out of range` at `app/services/providers/base.py:63`. If either fails with an assertion mismatch instead of `IndexError`, the test is not reaching the code path — fix the test before touching the implementation.

- [ ] **Step 4: Fix `argv0_name`**

In `backend/app/services/providers/base.py`, replace:

```python
def argv0_name(command: str) -> str:
    """Return the executable basename from a command or argv0 string."""
    if not command:
        return ""
    return Path(command.strip().split()[0]).name.lower()
```

with:

```python
def argv0_name(command: str) -> str:
    """Return the executable basename from a command or argv0 string."""
    parts = command.split() if command else []
    if not parts:
        return ""
    return Path(parts[0]).name.lower()
```

`str.split()` with no argument already discards leading and trailing whitespace, so the explicit `.strip()` was redundant even before it was unsafe. Guarding on `parts` rather than on `command` covers `""`, `" "`, `"\t"` and `"\n"` with one predicate.

Then re-run Step 3's command. Expected: **2 passed**.

- [ ] **Step 5: Write the strict-path regression test**

This is the test whose absence this plan already called a finding: `strict=True` shipped with a fail-closed message and **no test proving the message can be produced.**

Add to `backend/tests/agent_teams/test_github_dispatch_service.py`, immediately above `test_ambiguous_check_allows_one_nudgeable_pane` (`:1960`). It joins the three existing `test_ambiguous_check_*` tests and reuses their fixtures and helpers exactly — `_team`, `_seed_observed_panes`, `_launcher_that_must_not_run`, and the autouse `no_discovered_panes` fixture at `:57-62`.

```python
@pytest.mark.asyncio
async def test_ambiguous_check_holds_when_discovery_raises(db, monkeypatch):
    """strict=True must convert a discovery exception into a hold, not a dispatch.

    discover_agent_sessions() swallows tmux-missing, non-zero exit and timeout,
    but get_providers() and the process-match loop run OUTSIDE its try, so an
    OSError from a failed fork under memory pressure escapes. This is the only
    test that proves the fail-closed message can actually be produced.
    """
    preset, slots, scope = await _team(db)
    owner = next(slot for slot in slots if slot.display_name == "Backend SME")
    await _seed_observed_panes(db, preset, owner, [("%1", "w:0.1")])

    def raises_like_a_failed_fork():
        raise OSError(12, "Cannot allocate memory")

    monkeypatch.setattr(
        "app.services.agent_mail_service.discover_agent_sessions",
        raises_like_a_failed_fork,
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=954,
        issue_title="discovery exploded",
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
        issue_labels_by_number={954: ["area:backend"]},
    )

    await db.refresh(item)
    assert item.pending_reason == "queued_ambiguous_sessions"
    # The row must survive: retention is pid-aware, and the exception means the
    # pass never reached _remove_stale_observed_sessions at all.
    assert len(await agent_mail_service.nudgeable_sessions_for_slot(db, owner.id)) == 1
```

Three details that are load-bearing:

**Patch the name the service resolves, not the source module.** `agent_mail_service.py` does `from ... import discover_agent_sessions`, so it holds its own reference. `monkeypatch.setattr("app.services.agent_bridge.discovery.subprocess.run", ...)` does **not** work here — the autouse `no_discovered_panes` fixture has already replaced the whole function on the service, so your patch at the subprocess layer never runs. I made this mistake while measuring and got a green test that was actually re-proving Finding 20's poll-1 hold instead. The three existing `test_ambiguous_check_*` tests all patch `app.services.agent_mail_service.discover_agent_sessions`; follow them.

**The replacement takes no arguments.** `sync_observed_sessions` calls `discover_agent_sessions()` bare. A `lambda: ...` cannot raise, hence the named `def`.

**Assert the row survived, not just the hold.** Without the second assertion the test would still pass if a future change deleted the row and held for some unrelated reason. `nudgeable_sessions_for_slot` is the same predicate the gate itself counts.

- [ ] **Step 6: Verify the test detects `strict` being removed**

A regression test that passes with and without the thing it guards is decoration. Prove this one bites, by temporarily replacing the guarded call in `_session_ambiguity_note` (`github_dispatch_service.py:644-654`) with the plain call:

```python
        await agent_mail_service.sync_observed_sessions(db)
```

```bash
python -m pytest tests/agent_teams/test_github_dispatch_service.py -q -k discovery_raises
```

Expected: **1 failed**, with `agent bridge discovery failed: [Errno 12] Cannot allocate memory` logged at `agent_mail_service.py:357` — the lenient path swallowing the exception, exactly as it should when `strict` is absent.

Then **restore the `try`/`except` verbatim** and re-run. Expected: **1 passed**, and `git diff app/services/github_dispatch_service.py` must be **empty** — this task changes that file not at all. Reverse the edit by exact string; do not `git checkout --` it.

- [ ] **Step 7: Run the scoped suites**

The scoped set does not include `test_providers.py`, so run both:

```bash
python -m pytest tests/agent_teams/test_github_dispatch_service.py tests/agent_mail/test_registry.py tests/test_agent_bridge_discovery.py -q
python -m pytest tests/test_providers.py -q
```

Expected: **157 passed** for the first (156 after Task 2, plus this task's one dispatch test) and **11 passed** for the second (the file's 9, plus this task's 2).

- [ ] **Step 8: Run the full backend suite**

```bash
python -m pytest tests/ -q
```

Expected: **622 passed, 1 failed.** That is the 610 baseline plus this PR's 12 new tests, and it is a **measured** figure — the whole plan, all three production edits and all twelve tests exactly as written, was applied and run before this plan was handed over. The one failure must be `tests/test_multi_provider_smoke.py::test_agent_bridge_session_filter_smoke` and nothing else. Any other failure: **stop and report.**

The three production edits were also measured **together with no test changes at all**: `610 passed, 1 failed` — identical to the baseline. So none of them breaks an existing test on its own, and any full-suite failure you see beyond the known one comes from a test, not from the production code.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/providers/base.py backend/tests/test_providers.py backend/tests/agent_teams/test_github_dispatch_service.py
git commit -m "fix(g3): a blank pane command must not abort session discovery"
```

Note what is **not** in that `git add`: `github_dispatch_service.py` and `agent_mail_service.py`. If either shows up in `git status` at this point, Step 6's revert was incomplete.

- [ ] **Step 10: Open the PR**

```bash
git push -u origin feature/autonomous-github-dispatch-phase-g3
gh pr create --base feature/autonomous-github-dispatch \
  --title "fix(g3): observed session durability — Finding 20" \
  --body "..."
```

In the body, report: the measured scoped counts and full-suite count, the number of tests added, that `strict=True` was **retained** and why, and the pre-existing failure. Leave the PR open and unmerged.

---

## Self-review notes

**Spec coverage.** There is no spec document for this PR; the requirement is Finding 20 as recorded in the PR #310 review, plus the adjacent defects the investigation surfaced. All are covered: the poll-2 dispatch (Task 1), the orphaned rebind (Task 2), the untested and escapable fail-closed guard (Task 3).

**Revision history of this plan, because one task reversed.** Task 3 originally said "remove `strict=True`, which guards a failure that cannot happen." An implementation review rejected the plan on that basis and was correct. `OSError(ENOMEM)` from a failed `fork` escapes `discover_agent_sessions` — `get_providers()` and the match loop are outside its `try` — and with `strict` removed, the cold-start case dispatches onto unknown state with nothing left to hold on. Task 3 now retains the flag. The same review also found Task 1's dead-pid test used `pid=None` (a mutant retaining every non-null pid passed both planned tests) and Task 2's advertised-slot validation untested for provider and unvalidated for preset. All three were reproduced by measurement before being accepted; all three are fixed above.

**What this PR does not fix, deliberately.**

1. **`discover_agent_sessions` still cannot report failure explicitly.** It still mixes `return []` for three failures with propagation for the rest. 27 patch statements and six callers depend on the current contract, so replacing it with an explicit success/failure result is a much larger change of its own. Task 3 makes the mixed contract *safe* at the one call site where it decides a dispatch; it does not make it *clean*.
2. **Slot-id reuse within the same preset.** `agent_team_slots.id` is a bare `INTEGER PRIMARY KEY` — a rowid alias with no `AUTOINCREMENT` — and SQLite reuses freed ids. Measured: delete slot id 2, insert, and the new slot gets id 2. Task 2's provider, repo and preset guards catch a stale tmux env pointing at a replacement in a *different* preset or repo, but a replacement slot in the **same** preset shares both advertised ids and stays indistinguishable. The durable fix is `AUTOINCREMENT` on that table, or a spawn-time UUID exported alongside the ids — a schema change, hence its own PR.
3. **`_member_for_existing_observed_session`'s dependence on `team_slot_id` is unchanged.** Task 2 routes around it rather than relaxing it, because its strictness is load-bearing for the non-deleted case.
4. **The multiple-sessions-per-slot condition still exists.** Live slot 6 carries three observed rows. The gate correctly refuses to dispatch there; nothing here reduces three to one. That is a team-hygiene matter, not a dispatch-correctness one.
5. **`is_process_match`'s load sensitivity is unchanged.** Task 1 makes the *consequence* of a false negative survivable. A `pgrep` that times out under load still reports the pane as a non-agent for that pass, which still means the pane is absent from `nudgeable_sessions_for_slot`'s input for that pass — the row simply is not destroyed. Worth its own investigation.

**Type consistency.** `_member_for_advertised_slot` returns `MailTeamMember | None`, matching `_member_for_existing_observed_session`, and is called in the same `if member is None:` chain style. `_pid_is_running` takes `Optional[int]` and `MailAgentSession.pid` is `Mapped[int | None]`, so the Task 1 call site needs no guard.
