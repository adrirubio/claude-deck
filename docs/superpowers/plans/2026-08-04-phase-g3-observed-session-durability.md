# Phase G3 — Observed Session Durability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `sync_observed_sessions` from destroying the evidence that the dispatch ambiguity gate depends on, so the gate cannot be talked into dispatching a second owner onto an occupied slot.

**Architecture:** Three tasks in one PR, all in the session-registry layer. Task 1 makes the observed-row retention rule pid-aware, so a pane that is demonstrably alive is not deleted merely because one discovery pass failed to see it. Task 2 makes a pane's own tmux environment the authority on which slot it belongs to, so a row that *is* rebuilt comes back slot-bound instead of orphaned. Task 3 removes the `strict=True` flag that PR #310 added, because the failure it guards cannot occur.

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
- Do **not** change the signature of `discover_agent_sessions`. **Roughly fifty test sites patch it as `lambda: []`** (across `test_registry.py`, `test_agent_team_service.py`, `test_github_workspace_service.py`, `test_external_api.py`, and more) and six non-mail callers call it. Making failure explicit *there* is a much larger, separate change. This plan deliberately fixes the consequence instead.
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

  | Command | Baseline |
  |---|---|
  | `python -m pytest tests/agent_teams/test_github_dispatch_service.py tests/agent_mail/test_registry.py tests/test_agent_bridge_discovery.py -q` | **147 passed** |
  | `python -m pytest tests/agent_teams/ tests/agent_mail/ -q` | **444 passed** |
  | `python -m pytest tests/ -q` | **610 passed, 1 failed** |

  The scoped-suite command in the middle column is the one to use per task; it is the tightest set covering all three files this PR touches.
- Known pre-existing failure: `tests/test_multi_provider_smoke.py::test_agent_bridge_session_filter_smoke` (stale monkeypatch, `:54`). **Report it, do not fix it** — an issue is owed separately.
- Every task ends green. If a test fails for a reason your task did not cause, **report it, do not rewrite it.**

**Stop and report** if a step's preconditions do not match what you find. A moved line number is fine to adapt to. A different *shape* — the function doing something other than described — means the reasoning behind the task may not hold, and you should stop.

---

## File Structure

No new files, no schema change. Two backend modules and two test files.

| File | Responsibility here | Tasks |
|---|---|---|
| `backend/app/services/agent_mail_service.py` | Owns the session registry: which observed rows are retained, and which member (hence slot) each pane binds to | 1, 2, 3 |
| `backend/app/services/github_dispatch_service.py` | Drops the now-inert `strict=True` argument | 3 |
| `backend/tests/agent_mail/test_registry.py` | Retention and binding tests — this is where `sync_observed_sessions` is already tested | 1, 2 |
| `backend/tests/agent_teams/test_github_dispatch_service.py` | The end-to-end poll-1-then-poll-2 regression, and the `strict` removal | 1, 3 |

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

`_effective_status` (`:618-641`) already refuses to call an observed row offline when its pid is running — that is Finding 17's rule, and it is why the five live observed rows are 579,148s past `OBSERVED_TTL_SECONDS` and still nudgeable. **Retention did not get the same treatment.** So a row can be simultaneously "too alive to mark offline" and "stale enough to delete." Task 1 closes that gap.

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
```

`pid=None` is the honest way to express "dead" without inventing a pid number that might exist on the machine. `_pid_is_running` returns `False` for a falsy pid (`:608-609`), which is exactly the "no liveness evidence" case.

- [ ] **Step 2: Run the tests to verify the first one fails**

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate
python -m pytest tests/agent_mail/test_registry.py -q -k "pid_is_alive or pid_is_dead"
```

Expected: `test_sync_observed_keeps_row_whose_pid_is_alive` **FAILS** with `assert 0 == 1` — the row was deleted. `test_sync_observed_still_deletes_row_whose_pid_is_dead` **PASSES** already; it is the guard that stops Step 3 from over-correcting into "never delete anything."

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

- [ ] **Step 4: Run the tests to verify both pass**

```bash
python -m pytest tests/agent_mail/test_registry.py -q -k "pid_is_alive or pid_is_dead"
```
Expected: `2 passed`.

- [ ] **Step 5: Add the end-to-end regression that Finding 20 actually described**

The unit tests above prove the retention rule. This one proves the *gate* no longer flips between polls, which is the defect that would have dispatched a second owner. Add to `backend/tests/agent_teams/test_github_dispatch_service.py`, reusing that file's `_team` helper (`:65`) and `_seed_observed_panes` (`:279`) — read both before writing, and do not add a second copy of either.

The file has an autouse fixture (added by PR #310, `no_discovered_panes`) that patches `app.services.agent_mail_service.discover_agent_sessions` to `lambda: []`. This test needs to drive that patch itself, so override it locally with `monkeypatch` inside the test — `monkeypatch` applied in the test body wins over the autouse fixture's earlier `setattr`.

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
Expected: `1 passed`.

- [ ] **Step 7: Run the scoped suites**

```bash
python -m pytest tests/agent_teams/test_github_dispatch_service.py tests/agent_mail/test_registry.py tests/test_agent_bridge_discovery.py -q
```
Expected: **150 passed** — the measured 147 baseline plus this task's 3 new tests (2 in `test_registry.py`, 1 in `test_github_dispatch_service.py`).

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
```

`_slot` builds the slot with `provider="codex-cli"` and `repo_id` derived from the cwd you pass, which is why the panes above use `codex-cli` and the matching cwd. Check `_slot`'s body before relying on that — it is at `:44` and it returns `(preset, slot)`.

- [ ] **Step 2: Run the tests to verify the first fails**

```bash
python -m pytest tests/agent_mail/test_registry.py -q -k "tmux_environment or another_repo or no_longer_exists"
```

Expected: `test_sync_observed_binds_slot_from_tmux_environment` **FAILS** with `assert None == 1`. The other two **PASS** already — they are the guards that stop Step 3 from trusting the env unconditionally.

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
python -m pytest tests/agent_mail/test_registry.py -q -k "tmux_environment or another_repo or no_longer_exists"
```
Expected: `3 passed`.

- [ ] **Step 5: Run the scoped suites**

```bash
python -m pytest tests/agent_teams/test_github_dispatch_service.py tests/agent_mail/test_registry.py tests/test_agent_bridge_discovery.py -q
```
Expected: **153 passed** — 150 after Task 1, plus this task's 3.

Pay attention to `test_registry.py`'s existing observed-sync tests. Several seed a slot and a registered row and assert the observed row binds to the **slot** member (`:376-400` and the group from `:440` to `:600`). Those pass because their fake panes carry no `team_slot_id` key, so `_member_for_advertised_slot` returns `None` at its first guard and the existing pid path still runs. If any of them fails, **stop and report** — it means the ordering above is wrong, not that the test is.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agent_mail_service.py backend/tests/agent_mail/test_registry.py
git commit -m "fix(g3): observed rows recover their slot from the tmux environment"
```

---

### Task 3: Remove `strict=True`, which guards a failure that cannot happen

**Files:**
- Modify: `backend/app/services/agent_mail_service.py:350-360` (drop the `strict` parameter and its branch)
- Modify: `backend/app/services/github_dispatch_service.py:634-660` (`_session_ambiguity_note` — drop the `try`/`except` and the strict call)
- Test: `backend/tests/agent_teams/test_github_dispatch_service.py:1716` (one stub signature)

**Interfaces:**
- Consumes: nothing new.
- Produces: `sync_observed_sessions(db) -> None` — back to its pre-PR-#310 signature. `_session_ambiguity_note(db, owner_slot_id) -> str | None` keeps its signature; only its body shrinks.

PR #310 added `strict=True` so the gate could tell "discovery worked and found nothing" from "discovery blew up." The flag works exactly as written. The problem is that the underlying call does not raise for any realistic failure, so the distinction it draws is one the data cannot express.

`discover_agent_sessions` (`agent_bridge/discovery.py:98-116`):

```python
        if result.returncode != 0:
            logger.debug("tmux list-panes failed: %s", result.stderr.strip())
            return []
    except FileNotFoundError:
        logger.debug("tmux not found")
        return []
    except subprocess.TimeoutExpired:
        logger.warning("tmux list-panes timed out")
        return []
```

tmux missing, tmux erroring, tmux hanging — all three return `[]`. Those are the realistic failures. `strict=True` only fires if discovery raises something else entirely, and `[]` flows through as *data* indistinguishable from an empty slot. Verified against the real function, not a mock.

That is why Tasks 1 and 2 fix the consequence instead. The honest options for `strict` are to make it real — which means changing `discover_agent_sessions`'s contract, and the Global Constraints explain why that is a separate, much larger change — or to remove it. Leaving it is the one option to reject: a flag whose name promises a guarantee it does not provide will be trusted by the next reader.

**Removing it is safe only because Tasks 1 and 2 landed first.** Do not reorder. With the strict branch gone and retention still pid-blind, a discovery failure would silently delete the row and the gate would have neither the exception nor the evidence.

- [ ] **Step 1: Find everything that mentions `strict`**

```bash
grep -rn "strict" tests/agent_teams/test_github_dispatch_service.py app/services/agent_mail_service.py app/services/github_dispatch_service.py
```

Expected: exactly one test-side hit, and it is **not** a test of the strict path. It is a stub whose signature has to tolerate the keyword (`:1716`, inside `test_dispatch_proceeds_with_only_standing_session` which begins at `:1715`):

```python
    async def keep_synthetic_session(_db, *, strict=False):
        return None
```

**No test asserts the strict behaviour, which is itself the finding.** The flag was added with a fail-closed message and no test proving the message can be produced — because with the real `discover_agent_sessions` it cannot be. So this task deletes **no** tests; it updates that one stub to:

```python
    async def keep_synthetic_session(_db):
        return None
```

If you find a test that genuinely asserts the gate holds when discovery raises, **stop and report** — that contradicts the measurement this task rests on, and the task should not proceed on a stale premise.

- [ ] **Step 2: Simplify the gate**

In `github_dispatch_service.py`, replace the guarded call:

```python
        try:
            await agent_mail_service.sync_observed_sessions(db, strict=True)
        except Exception:
            logger.exception(
                "session discovery failed while checking slot %s", owner_slot_id
            )
            return (
                "Session discovery failed, so the owning pane could not be "
                "confirmed. Holding rather than briefing an unknown session."
            )
```

with the plain call:

```python
        # No strict mode: discover_agent_sessions returns [] for tmux-missing,
        # non-zero exit and timeout, so a failure cannot be distinguished here.
        # Retention is pid-aware instead (_remove_stale_observed_sessions), so a
        # failed pass no longer deletes the evidence this gate reads.
        await agent_mail_service.sync_observed_sessions(db)
```

The `except` block spans four lines and its `return (` is followed by a bracketed multi-line string. **Delete the whole `try`/`except` as one unit** — dedenting the call while leaving the `return (...)` behind produces an `IndentationError` that fails collection for a dozen unrelated test files with no mention of this file. If you see `IndentationError: unexpected indent` after this step, that is what happened.

Leave the rest of `_session_ambiguity_note` alone — the `len(candidates) > 1` branch and the `not candidates and known_before` branch both stay. The second is now unreachable via a discovery blip, but it still fires if a row is deleted for a reason this PR does not cover, and fail-closed is the right default there. Do **not** "simplify" it away.

- [ ] **Step 3: Drop the parameter**

In `agent_mail_service.py`:

```python
    async def sync_observed_sessions(self, db: AsyncSession) -> None:
        """Upsert Agent Bridge tmux discoveries as observed sessions."""
        try:
            discovered = discover_agent_sessions()
        except Exception as exc:
            logger.warning("agent bridge discovery failed: %s", exc)
            return
```

Then confirm no caller still passes it:

```bash
grep -rn "sync_observed_sessions" app/ tests/ | grep strict
```
Expected: no output.

- [ ] **Step 4: Run the scoped suites**

```bash
python -m pytest tests/agent_teams/test_github_dispatch_service.py tests/agent_mail/test_registry.py tests/test_agent_bridge_discovery.py -q
```

Expected: **153 passed** — unchanged from Task 2. This task removes no tests and adds none; it deletes a parameter and a dead branch. If the number moves at all, something else changed and you should find out what before continuing.

- [ ] **Step 5: Run the full backend suite**

```bash
python -m pytest tests/ -q
```

Expected: **616 passed, 1 failed.** That is the 610 baseline plus this PR's 6 new tests, and it is a **measured** figure — the full plan (both production edits and all six tests exactly as written above) was run before this plan was handed over. The one failure must be `tests/test_multi_provider_smoke.py::test_agent_bridge_session_filter_smoke` and nothing else. Any other failure: **stop and report.**

Each production edit was also measured alone, with no test changes, at **610 passed, 1 failed** — so neither introduces a regression by itself. If your number differs, the difference is yours to explain before opening the PR.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/agent_mail_service.py backend/app/services/github_dispatch_service.py backend/tests/agent_teams/test_github_dispatch_service.py
git commit -m "refactor(g3): drop strict discovery mode, which guarded an unreachable failure"
```

- [ ] **Step 7: Open the PR**

```bash
git push -u origin feature/autonomous-github-dispatch-phase-g3
gh pr create --base feature/autonomous-github-dispatch \
  --title "fix(g3): observed session durability — Finding 20" \
  --body "..."
```

In the body, report: the measured scoped count and full-suite count, the number of tests added and removed, and the pre-existing failure. Leave the PR open and unmerged.

---

## Self-review notes

**Spec coverage.** There is no spec document for this PR; the requirement is Finding 20 as recorded in the PR #310 review, plus the two adjacent defects the investigation surfaced. All three are covered: the poll-2 dispatch (Task 1), the orphaned rebind (Task 2), the inert flag (Task 3).

**What this PR does not fix, deliberately.**

1. **`discover_agent_sessions` still cannot report failure.** Fifty-odd test sites and six callers depend on the current contract. It is the right fix eventually and it is its own change.
2. **`_member_for_existing_observed_session`'s dependence on `team_slot_id` is unchanged.** Task 2 routes around it rather than relaxing it, because its strictness is load-bearing for the non-deleted case.
3. **The multiple-sessions-per-slot condition still exists.** Live slot 6 carries three observed rows. The gate correctly refuses to dispatch there; nothing here reduces three to one. That is a team-hygiene matter, not a dispatch-correctness one.
4. **`is_process_match`'s load sensitivity is unchanged.** Task 1 makes the *consequence* of a false negative survivable. A `pgrep` that times out under load still reports the pane as a non-agent for that pass, which still means the pane is absent from `nudgeable_sessions_for_slot`'s input for that pass — the row simply is not destroyed. Worth its own investigation.

**Type consistency.** `_member_for_advertised_slot` returns `MailTeamMember | None`, matching `_member_for_existing_observed_session`, and is called in the same `if member is None:` chain style. `_pid_is_running` takes `Optional[int]` and `MailAgentSession.pid` is `Mapped[int | None]`, so the Task 1 call site needs no guard.
