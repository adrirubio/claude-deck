# Soak Defect Triad Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Fix the three confirmed soak defects blocking unattended operation: (12) retry bypasses the leader-ack gate, (10) Deck can spawn a duplicate owner session, (11) no resource awareness before dispatch.

**Architecture:** All three are guard changes inside `github_dispatch_service.py` plus one new config setting. No schema change, no new endpoint, no new dependency.

**Tech Stack:** Python 3.11+, FastAPI, async SQLAlchemy, pytest-asyncio.

## Global Constraints

- **Design spec:** `docs/superpowers/specs/2026-07-26-soak-defect-triad-hardening-design.md` — read §1/§2/§3 first. It records *why* each fix is shaped as it is.
- **Branch:** sub-branch off integration branch `feature/autonomous-github-dispatch`. Do NOT merge to master. Open ONE PR back into the integration branch and STOP.
- **NO schema change, NO migration, NO new endpoint, NO new dependency** (specifically: do NOT add `psutil` — parse `/proc/meminfo`). If you edit `backend/app/models/database.py`, you're off-plan — except for §2's documented fallback, and only after reporting why.
- **Tests:** `cd backend && source venv/bin/activate`; dispatch tests in `backend/tests/agent_teams/test_github_dispatch_service.py`. Baseline is **262 passing** — it must not regress.
- **Do NOT touch the live soak state.** Autonomy is deliberately OFF (`preset.autonomy_enabled=false`) and a team may be running for an unrelated rebase task. Do not enable autonomy, do not spawn/kill agent sessions, do not hand-edit DB rows, do not touch the tizonia repo.
- Conventional commits. TDD throughout: failing test → implement → pass.

---

## Task 1: Fix the stale-ack gate bypass (Finding 12)

Both halves of the defence: clear the field on reset, AND make the gate generation-aware so it self-heals if any future transition forgets. Reviewer gate: a retried item with a stale `ack_received_at` no longer satisfies the ack gate.

**Files:**
- Modify: `backend/app/services/github_dispatch_service.py` (`reset_for_retry` ~line 22, `_ack_satisfied` ~line 513)
- Test: `backend/tests/agent_teams/test_github_dispatch_service.py`

**Interfaces:**
- `reset_for_retry(item) -> None` — additionally sets `item.ack_received_at = None`.
- `_ack_satisfied(item) -> bool` — returns False for an ack older than `dispatched_at`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/agent_teams/test_github_dispatch_service.py` (follow the module's existing construction style for `GithubWorkItem`):

```python
def test_reset_for_retry_clears_ack_received_at():
    item = GithubWorkItem(
        scope_id=1, issue_number=819, issue_type="code",
        dispatch_status="escalated", escalation_reason="plan_blocked",
        ack_received_at=datetime(2026, 7, 24, 17, 30, 5),
        dispatched_at=datetime(2026, 7, 24, 17, 12, 0),
    )
    github_dispatch_service.reset_for_retry(item)
    assert item.ack_received_at is None


def test_ack_not_satisfied_by_ack_older_than_current_dispatch():
    # stale ack from a PREVIOUS dispatch generation must not satisfy the gate
    item = GithubWorkItem(
        scope_id=1, issue_number=819, issue_type="code",
        dispatch_status="dispatched",
        ack_received_at=datetime(2026, 7, 24, 17, 30, 5),
        dispatched_at=datetime(2026, 7, 24, 18, 35, 56),
    )
    assert github_dispatch_service._ack_satisfied(item) is False


def test_ack_satisfied_when_ack_follows_dispatch():
    item = GithubWorkItem(
        scope_id=1, issue_number=819, issue_type="code",
        dispatch_status="dispatched",
        dispatched_at=datetime(2026, 7, 24, 18, 35, 56),
        ack_received_at=datetime(2026, 7, 24, 18, 40, 0),
    )
    assert github_dispatch_service._ack_satisfied(item) is True


def test_pr_number_satisfies_ack_regardless_of_stale_ack():
    item = GithubWorkItem(
        scope_id=1, issue_number=819, issue_type="code",
        dispatch_status="dispatched", pr_number=865,
        ack_received_at=datetime(2026, 7, 24, 17, 30, 5),
        dispatched_at=datetime(2026, 7, 24, 18, 35, 56),
    )
    assert github_dispatch_service._ack_satisfied(item) is True
```

Also add the **regression test that motivated this** — a retried, re-dispatched item with a stale ack must still be nudged/escalated on leader silence. Mirror the existing `monitor_dispatched` ack-timeout tests in this module (they already build a scope + slots + wake-state map; reuse that harness rather than inventing one):

```python
@pytest.mark.asyncio
async def test_retried_item_still_nudged_when_leader_never_acks_again(...):
    # item was acked in a previous generation, retried, re-dispatched just now.
    # Expect: ack gate NOT satisfied -> leader nudge (then escalation after grace),
    # exactly as for a first-time dispatch.
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py -k "ack" -v`
Expected: the new stale-ack tests FAIL (gate currently returns True).

- [ ] **Step 3: Implement**

In `reset_for_retry`, add alongside the other cleared fields:

```python
item.ack_received_at = None
```

Replace `_ack_satisfied` with the generation-aware version:

```python
def _ack_satisfied(self, item: GithubWorkItem) -> bool:
    if item.pr_number is not None:
        return True
    if item.ack_received_at is None:
        return False
    if item.dispatched_at is not None and item.ack_received_at < item.dispatched_at:
        return False
    return True
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py -k "ack" -v`
Expected: PASS, including the pre-existing ack tests (they seed `ack_received_at` at/after dispatch, so they must remain green — if one now fails, read it carefully: it may have been relying on the buggy behaviour, in which case report it rather than silently rewriting the assertion).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/github_dispatch_service.py backend/tests/agent_teams/test_github_dispatch_service.py
git commit -m "fix(dispatch): require a fresh leader ack after retry"
```

---

## Task 2: One owner session per slot (Finding 10)

Reviewer gate: with a live dispatched-owner session for a slot, dispatch does not spawn a second; with only the slot's standing session, dispatch proceeds normally.

**Files:**
- Modify: `backend/app/services/github_dispatch_service.py` (new predicate + check in `dispatch_pending` before the launch, ~line 138–177)
- Test: `backend/tests/agent_teams/test_github_dispatch_service.py`

**Interfaces:**
- New: `slot_has_live_owner_session(db, slot_id) -> bool` on `GithubDispatchService`.
- `dispatch_pending` — queues the item with `pending_reason="queued_owner_session_live"` instead of launching.

- [ ] **Step 1: Confirm the discriminator FIRST (do not skip)**

This is the one genuinely uncertain part of the plan, and getting it wrong produces a guard that blocks **all** dispatch (every slot normally has a live standing session). Before writing code, determine how a dispatched-owner session is distinguishable from a standing session:

```bash
cd backend
grep -n "source" app/models/database.py | sed -n '/MailAgentSession/,$p'
grep -n "source=" app/services/agent_mail_service.py | head -20
grep -n "session_name\|tmux_target" app/services/agent_team_service.py | head -20
```

**The orchestrator already ran this investigation against the live soak DB. Findings — treat as verified, but re-confirm before relying on them:**

1. ❌ **`MailAgentSession.source` is NOT a viable discriminator.** Its only values are `mcp`, `hook`, `observed`, and *both* standing and dispatched-owner sessions produce those. Do not use it.
2. ✅ **`tmux_target` correlation WORKS and is the recommended discriminator.** `agent_team_launch_items.tmux_target` joins exactly to `mail_agent_sessions.tmux_target`, and a launch is a *dispatch* launch iff its id appears in `github_work_items.launch_id`. Verified live:

```
launch_item(launch 58, slot 6) tmux_target = tizonia-openmax-il-a1c9:0.0   <- standing (launch 58 NOT on any work item)
launch_item(launch 59, slot 6) tmux_target = tizonia-openmax-il-8403:0.0   <- dispatched owner (launch 59 IS on work item 25)

mail_session(member 17, slot 6) tmux_target = tizonia-openmax-il-a1c9:0.0
mail_session(member 17, slot 6) tmux_target = tizonia-openmax-il-8403:0.0
```

   Note that this pair **is Finding 10 captured in data**: slot 6 with two live tmux-bound sessions, one standing and one dispatched owner. Your queueing test can be seeded from exactly this shape.

3. **Fallback** (only if 2 doesn't hold up): record the spawned owner session identity on the work item at dispatch time and key the check off that. This needs a column — if you reach here, STOP and report before adding it.

**Report which discriminator you chose and the evidence** in the PR description. If none is reliable, STOP and report rather than shipping a guard that might block all dispatch.

- [ ] **Step 2: Write the failing tests**

Both directions matter — the second test is what protects against over-blocking:

```python
@pytest.mark.asyncio
async def test_dispatch_queues_when_slot_has_live_owner_session(...):
    # seed: a live dispatched-owner session for the routed slot
    # expect: launcher NOT called; item stays pending
    #         with pending_reason == "queued_owner_session_live"


@pytest.mark.asyncio
async def test_dispatch_proceeds_with_only_standing_session(...):
    # seed: only the slot's STANDING session is live (the normal case)
    # expect: launcher IS called; item becomes dispatched
```

Reuse the module's existing `dispatch_pending` harness (fake launcher + seeded scope/slots).

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py -k "owner_session" -v`
Expected: the queueing test FAILS (dispatch currently spawns unconditionally).

- [ ] **Step 4: Implement**

Add the predicate, reusing the **existing** liveness logic in `agent_mail_service` (`_session_is_live` / `_effective_status`) — do NOT hand-roll a staleness threshold:

```python
async def slot_has_live_owner_session(self, db: AsyncSession, slot_id: int) -> bool:
    ...
```

Then in `dispatch_pending`, before the `launcher(...)` call (alongside the existing `slot_is_busy` queue branch):

```python
if await self.slot_has_live_owner_session(db, owner_slot_id):
    item.owner_slot_id = owner_slot_id
    item.routing_method = method
    item.pending_reason = "queued_owner_session_live"
    item.updated_at = datetime.utcnow()
    await db.commit()
    continue
```

- [ ] **Step 5: Run to verify pass**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py -k "owner_session or dispatch_pending" -v`
Expected: PASS, and all pre-existing `dispatch_pending` tests still green (this is the over-blocking canary — if many suddenly queue instead of dispatching, the discriminator from Step 1 is wrong).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/github_dispatch_service.py backend/tests/agent_teams/test_github_dispatch_service.py
git commit -m "fix(dispatch): never spawn a duplicate owner session for a slot"
```

---

## Task 3: Memory preflight gate (Finding 11)

Reviewer gate: below the configured memory floor, dispatch is refused and the item queues; above it, dispatch proceeds; unreadable memory fails open.

**Files:**
- Modify: `backend/app/config.py` (new setting)
- Modify: `backend/app/services/github_dispatch_service.py` (helper + check in `dispatch_pending`)
- Test: `backend/tests/agent_teams/test_github_dispatch_service.py`

**Interfaces:**
- New setting: `github_min_available_memory_mb: int = 3000`.
- New helper: available-memory reader parsing `MemAvailable` from `/proc/meminfo`, returning `int | None` (None = unknown). Must be monkeypatchable.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_dispatch_queues_when_available_memory_below_floor(monkeypatch, ...):
    monkeypatch.setattr(github_dispatch_service, "_available_memory_mb", lambda: 500)
    # expect: launcher NOT called; pending_reason == "queued_low_memory"


@pytest.mark.asyncio
async def test_dispatch_proceeds_when_memory_above_floor(monkeypatch, ...):
    monkeypatch.setattr(github_dispatch_service, "_available_memory_mb", lambda: 16000)
    # expect: launcher called; item dispatched


@pytest.mark.asyncio
async def test_dispatch_fails_open_when_memory_unknown(monkeypatch, ...):
    monkeypatch.setattr(github_dispatch_service, "_available_memory_mb", lambda: None)
    # expect: launcher called (never block on an unreadable metric)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py -k "memory" -v`
Expected: FAIL — helper/gate not defined.

- [ ] **Step 3: Implement**

Add to `backend/app/config.py`:

```python
github_min_available_memory_mb: int = 3000
```

Add the helper to `GithubDispatchService` (parse `MemAvailable`, which unlike `MemFree` accounts for reclaimable cache; return None on any failure), and gate in `dispatch_pending` near the `max_concurrent_dispatched` check:

```python
available_mb = self._available_memory_mb()
if available_mb is not None and available_mb < settings.github_min_available_memory_mb:
    item.pending_reason = "queued_low_memory"
    item.updated_at = datetime.utcnow()
    await db.commit()
    continue
```

Note the `is not None` — unknown memory must NOT block dispatch.

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py -k "memory" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/app/services/github_dispatch_service.py backend/tests/agent_teams/test_github_dispatch_service.py
git commit -m "feat(dispatch): refuse dispatch when host memory is below the floor"
```

---

## Task 4: Full-suite verification

- [ ] **Step 1: Run the full suite**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams tests/agent_mail -q`
Expected: all green, **≥262 passing** (baseline 262 + your new tests). Report the exact count.

- [ ] **Step 2: Confirm no schema/dependency change**

Run:
```bash
cd backend && git diff --stat app/models/database.py app/database.py requirements.txt
```
Expected: empty. (Guards + one config setting only.)

- [ ] **Step 3: Open ONE PR into the integration branch and STOP**

PR into `feature/autonomous-github-dispatch` (NOT master). In the description include:
- the three defects fixed, one line each;
- **the §2 discriminator you chose and the evidence** (the orchestrator will verify this specifically);
- the exact test count;
- confirmation that no schema/dependency changed.

Do NOT self-merge. Do NOT enable autonomy. Do NOT touch agent sessions or the tizonia repo.

---

## Self-Review

**1. Spec coverage:** §1 both halves (clear field + generation-aware gate) → Task 1 ✓; §2 predicate + queue branch + over-blocking canary → Task 2 ✓; §3 setting + `/proc/meminfo` helper + fail-open → Task 3 ✓.

**2. Placeholder scan:** No TBD. Task 2 Step 1 is deliberately an investigation step with explicit `grep`s and a STOP condition, because the standing-vs-owner discriminator is the one thing that cannot be assumed — guessing it wrong yields a guard that blocks all dispatch. Task 1 Step 4 flags that a pre-existing test failure may indicate reliance on the buggy behaviour and must be reported, not silently rewritten.

**3. Type consistency:** `reset_for_retry(item) -> None`, `_ack_satisfied(item) -> bool`, `slot_has_live_owner_session(db, slot_id) -> bool`, `_available_memory_mb() -> int | None`; `pending_reason` string vocabulary (`queued_owner_session_live`, `queued_low_memory`) consistent between plan, spec, and tests.

## Notes for the implementer

- All three fixes share one posture: **queue, don't escalate**. A live standing session and a temporarily busy host are normal conditions, not faults; items stay `pending` and retry next tick, so the gates are self-clearing.
- Task 1's generation-aware gate is the most valuable line in this plan: it converts a presence check into a relationship check, so the guard survives future transitions that forget to clear the field.
- Live acceptance tests (orchestrator-run, not yours): retried #818/#819 demand a fresh ack; two dispatches never yield two owner sessions; dispatch holds when memory is low.
