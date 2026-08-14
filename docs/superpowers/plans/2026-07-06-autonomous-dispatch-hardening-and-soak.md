# Autonomous Dispatch Hardening & Soak Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the three deferred dispatch findings (leader-ack brittleness, reachable-but-idle monitor, stale-ready pre-auto-merge head re-confirm) so the loop is safe under unattended auto-merge, then produce the soak runbook that gathers real-world evidence against tizonia's `roadmap:v1` issues.

**Architecture:** Move wait-authority out of the owner's prompt and into the brain's `monitor_dispatched` (§6). One unified nudge-then-escalate lifecycle serves both leader-ack (finding #1) and owner-idle (finding #2), differing only in timeout anchor and duration. Finding #3 is a separate re-confirm guard at the auto-merge boundary in the verification service. All code changes are backend Python (FastAPI + async SQLAlchemy + aiosqlite); no frontend changes.

**Tech Stack:** Python 3.11+, FastAPI, async SQLAlchemy 2.0, aiosqlite, pytest + pytest-asyncio. MCP tool shim in `backend/mcp_shim/`.

## Global Constraints

- **Design spec:** `docs/superpowers/specs/2026-07-06-autonomous-dispatch-hardening-and-soak-design.md` — this plan implements it exactly. Read it before starting.
- **Branch:** work on `feature/autonomous-github-dispatch`. Do NOT merge to master until the soak clears.
- **SQLite has no migration system:** every new column on an existing table MUST get an `ALTER TABLE ADD COLUMN` guard in `_run_sqlite_compat_migrations` (`backend/app/database.py`), matching the existing pattern (check `PRAGMA table_info`, add if absent). The ORM `create_all` only creates *new* tables, never alters existing ones.
- **Nudge is a question, never a kill:** the monitor must never terminate a session. It sends one Agent Mail message, waits a grace window, then escalates (recoverable). An alive-but-slow owner that shows activity resets its idle clock (the T-S4 lesson).
- **No "code proceeds without ack" branch:** on ack timeout both pipelines escalate (recoverable). Auto-proceeding would let an unreviewed plan auto-merge, reopening the C1 design-review gate.
- **Tests:** run from `backend/` with the venv active: `cd backend && source venv/bin/activate`. Existing dispatch/verify tests live in `backend/tests/agent_teams/`.
- **Commit style:** conventional commits (`feat:`/`fix:`/`test:`/`docs:`).

---

## File Structure

- `backend/app/config.py` — 4 new settings (ack timeout, design multiplier, idle timeout, nudge grace).
- `backend/app/models/database.py` — 3 new nullable columns on `GithubWorkItem`: `dispatched_at`, `ack_received_at`, `last_nudge_at`.
- `backend/app/database.py` — 3 `ADD COLUMN` guards in the `github_work_items` block of `_run_sqlite_compat_migrations`.
- `backend/app/services/github_dispatch_service.py` — set `dispatched_at` at dispatch; add ack + idle lifecycle to `monitor_dispatched`; add `_nudge_leader_for_ack` / `_nudge_owner_for_progress` helpers; add `_ack_satisfied` / `_ack_deadline_seconds` helpers; simplify `_leader_ack_instruction` to remove owner-side timeout language and add the `ack_received` reporting instruction.
- `backend/app/api/v1/agent_teams.py` — handle a new `ack_received` status in `report_dispatch_status`.
- `backend/mcp_shim/agent_mail_server.py` — add `ack_received` to the `deck_report_dispatch_status` docstring's valid-status list.
- `backend/app/services/github_verification_service.py` — pre-auto-merge head re-confirm guard in `_process_review_item`.
- `backend/tests/agent_teams/test_github_dispatch_service.py` — ack/idle lifecycle tests, ack_received signal test, prompt-simplification test.
- `backend/tests/agent_teams/test_github_verification_service.py` — merge-boundary guard tests.
- `docs/superpowers/specs/2026-07-06-tizonia-roadmap-v1-soak-runbook.md` — soak runbook + run-log template (new).

---

## Task 1: Schema + settings foundation

Adds the persistence and config the monitor lifecycle depends on. Reviewer gate: columns exist, migration applies cleanly on a pre-existing DB, settings load.

**Files:**
- Modify: `backend/app/config.py:38-42` (GitHub integration block)
- Modify: `backend/app/models/database.py` (GithubWorkItem class, after `last_verified_sha` mapped_column)
- Modify: `backend/app/database.py:399-406` (github_work_items migration block)
- Test: `backend/tests/agent_teams/test_github_dispatch_service.py`

**Interfaces:**
- Produces: `GithubWorkItem.dispatched_at: Mapped[datetime | None]`, `GithubWorkItem.ack_received_at: Mapped[datetime | None]`, `GithubWorkItem.last_nudge_at: Mapped[datetime | None]`
- Produces settings: `settings.github_leader_ack_timeout_seconds: int`, `settings.github_design_ack_multiplier: int`, `settings.github_owner_idle_timeout_seconds: int`, `settings.github_nudge_grace_seconds: int`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/agent_teams/test_github_dispatch_service.py`:

```python
@pytest.mark.asyncio
async def test_work_item_has_lifecycle_columns(db):
    preset, slots, scope = await _team(db)
    now = datetime.utcnow()
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=900,
        issue_title="x",
        issue_url="u",
        github_updated_at=now,
        dispatch_status="dispatched",
        dispatched_at=now,
        ack_received_at=now,
        last_nudge_at=now,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    assert item.dispatched_at is not None
    assert item.ack_received_at is not None
    assert item.last_nudge_at is not None


def test_ack_lifecycle_settings_present():
    assert settings.github_leader_ack_timeout_seconds > 0
    assert settings.github_design_ack_multiplier >= 1
    assert settings.github_owner_idle_timeout_seconds > 0
    assert settings.github_nudge_grace_seconds > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py::test_work_item_has_lifecycle_columns tests/agent_teams/test_github_dispatch_service.py::test_ack_lifecycle_settings_present -v`
Expected: FAIL — `TypeError: 'dispatched_at' is an invalid keyword argument` and `AttributeError: ... github_leader_ack_timeout_seconds`.

- [ ] **Step 3: Add the settings**

In `backend/app/config.py`, extend the GitHub integration block (after line 42, `github_owner_registration_grace_seconds`):

```python
    github_owner_registration_grace_seconds: int = 120
    github_leader_ack_timeout_seconds: int = 300
    github_design_ack_multiplier: int = 3
    github_owner_idle_timeout_seconds: int = 900
    github_nudge_grace_seconds: int = 180
```

- [ ] **Step 4: Add the ORM columns**

In `backend/app/models/database.py`, in the `GithubWorkItem` class immediately after the `last_verified_sha` mapped_column:

```python
    last_verified_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ack_received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_nudge_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

- [ ] **Step 5: Add the migration guards**

In `backend/app/database.py`, in the `github_work_items` block (after the `last_verified_sha` guard at line 406):

```python
    if work_item_columns and "last_verified_sha" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN last_verified_sha VARCHAR"))
    if work_item_columns and "dispatched_at" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN dispatched_at DATETIME"))
    if work_item_columns and "ack_received_at" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN ack_received_at DATETIME"))
    if work_item_columns and "last_nudge_at" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN last_nudge_at DATETIME"))
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py::test_work_item_has_lifecycle_columns tests/agent_teams/test_github_dispatch_service.py::test_ack_lifecycle_settings_present -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Commit**

```bash
git add backend/app/config.py backend/app/models/database.py backend/app/database.py backend/tests/agent_teams/test_github_dispatch_service.py
git commit -m "feat(dispatch): add ack/idle lifecycle columns and timeout settings"
```

---

## Task 2: The `ack_received` signal (dispatch stamp + endpoint + prompt + MCP doc)

One coherent deliverable: the owner reports `ack_received` after the leader acks; the brain records it and stamps `dispatched_at` at dispatch time so the monitor has a stable ack anchor. Reviewer gate: reporting `ack_received` sets `ack_received_at` and clears `last_nudge_at`; dispatch stamps `dispatched_at`; the owner prompt tells the owner to report it and no longer improvises a timeout.

**Files:**
- Modify: `backend/app/services/github_dispatch_service.py:198` (set `dispatched_at` when marking dispatched)
- Modify: `backend/app/services/github_dispatch_service.py:300-324` (`_leader_ack_instruction`)
- Modify: `backend/app/api/v1/agent_teams.py:187` (add `ack_received` branch before `pr_opened`)
- Modify: `backend/mcp_shim/agent_mail_server.py:609-616` (docstring valid-status list)
- Test: `backend/tests/agent_teams/test_github_dispatch_service.py`

**Interfaces:**
- Consumes: `GithubWorkItem.dispatched_at`, `ack_received_at`, `last_nudge_at` (Task 1)
- Produces: `report_dispatch_status` accepts `status="ack_received"` → sets `item.ack_received_at = utcnow()`, `item.last_nudge_at = None`, commits. `dispatch_pending` sets `item.dispatched_at = utcnow()` on the same line it sets `dispatch_status = "dispatched"`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/agent_teams/test_github_dispatch_service.py`:

```python
@pytest.mark.asyncio
async def test_dispatch_pending_stamps_dispatched_at(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=910,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    class _Result:
        launch_id = 910
        items = []

    async def fake_launcher(db_, preset_id, request):
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={910: ["area:backend"]},
        issue_details_by_number={910: {"body": "do the thing"}},
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.dispatched_at is not None


@pytest.mark.asyncio
async def test_ack_prompt_has_no_owner_side_timeout(db):
    preset, slots, scope = await _team(db)
    architect = next(slot for slot in slots if slot.display_name == "Architect")
    backend = next(slot for slot in slots if slot.display_name == "Backend SME")
    # register the leader member so the instruction uses member_id form
    from app.services.agent_mail_service import agent_mail_service
    leader_member = await agent_mail_service.get_or_create_slot_member(db, architect)
    await db.commit()
    instruction = github_dispatch_service._leader_ack_instruction(
        architect, leader_member, before="editing files"
    )
    assert "report `ack_received`" in instruction or "ack_received" in instruction
    # owner no longer decides how long to wait
    assert "minute" not in instruction.lower()
    assert "give up" not in instruction.lower()
```

- [ ] **Step 2: Add the endpoint test**

Add to `backend/tests/agent_teams/test_github_dispatch_service.py`:

```python
@pytest.mark.asyncio
async def test_report_ack_received_records_timestamp_and_clears_nudge(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=911,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=slots[1].id,
        dispatched_at=datetime.utcnow(),
        last_nudge_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.record_ack_received(db, item)

    await db.refresh(item)
    assert item.ack_received_at is not None
    assert item.last_nudge_at is None
    assert item.dispatch_status == "dispatched"  # unchanged; owner keeps working
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py::test_dispatch_pending_stamps_dispatched_at tests/agent_teams/test_github_dispatch_service.py::test_ack_prompt_has_no_owner_side_timeout tests/agent_teams/test_github_dispatch_service.py::test_report_ack_received_records_timestamp_and_clears_nudge -v`
Expected: FAIL — `dispatched_at is None`; prompt still contains timeout wording; `record_ack_received` not defined.

- [ ] **Step 4: Stamp `dispatched_at` at dispatch**

In `backend/app/services/github_dispatch_service.py`, in `dispatch_pending`, the `else` branch that sets `dispatched` (currently line 197-200):

```python
            else:
                item.dispatch_status = "dispatched"
                item.dispatched_at = datetime.utcnow()
                slots_dispatched_this_batch.add(owner_slot_id)
                scope_dispatched_this_batch += 1
```

- [ ] **Step 5: Add `record_ack_received` to the service**

In `backend/app/services/github_dispatch_service.py`, add a method (place it near `record_approval_round`, ~line 357):

```python
    async def record_ack_received(
        self, db: AsyncSession, item: GithubWorkItem
    ) -> None:
        item.ack_received_at = datetime.utcnow()
        item.last_nudge_at = None
        item.updated_at = datetime.utcnow()
        await db.commit()
```

- [ ] **Step 6: Simplify the owner ack instruction**

Replace `_leader_ack_instruction` (`backend/app/services/github_dispatch_service.py:300-324`). Keep the three-way member/slot/none branching but drop owner-side timing and add the `ack_received` report:

```python
    def _leader_ack_instruction(
        self,
        leader: AgentTeamSlot | None,
        leader_member: MailTeamMember | None,
        *,
        before: str,
    ) -> str:
        report = (
            " Once the leader acknowledges, call "
            "`deck_report_dispatch_status(status=\"ack_received\")` before "
            f"{before}. Do not set your own deadline for the acknowledgment; "
            "the brain manages timeouts and will nudge or escalate if needed."
        )
        if leader_member is not None:
            return (
                "- Send the team leader a short plan via Agent Mail using "
                f"`deck_request_context(to_member_id={leader_member.id}, ...)` "
                "or "
                f"`deck_send_message(to_member_id={leader_member.id}, ...)`, "
                f"then wait for acknowledgment before {before}." + report
            )
        if leader is not None:
            return (
                "- Send the team leader a short plan via Agent Mail and wait for "
                f"acknowledgment before {before}; first call `deck_list_team` to "
                f"resolve the Agent Mail member id for `{leader.display_name}`." + report
            )
        return (
            "- Send the team leader a short plan via Agent Mail and wait for "
            f"acknowledgment before {before}; if no leader is registered, report blocked."
            + report
        )
```

- [ ] **Step 7: Handle `ack_received` in the endpoint**

In `backend/app/api/v1/agent_teams.py`, add a branch in `report_dispatch_status` immediately before the `elif report.status == "pr_opened":` branch (line 187):

```python
    elif report.status == "ack_received":
        await github_dispatch_service.record_ack_received(db, item)
```

- [ ] **Step 8: Update the MCP tool docstring**

In `backend/mcp_shim/agent_mail_server.py`, in the `deck_report_dispatch_status` docstring (line ~610), add `ack_received` to the valid-status list:

```python
    """Report progress on a Claude-Deck-dispatched GitHub issue back to the brain.

    status is one of: triaging, ack_received, revision_requested, in_progress,
    pr_opened, handoff_initiated (with reassign_to_slot_id), handoff_accepted,
    blocked. Report ack_received right after the team leader acknowledges your
    plan. Called by the owner slot the brain dispatched the issue to. Include
    work_item_id from your bootstrap prompt.
    """
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py -k "dispatched_at or ack_prompt or ack_received" -v`
Expected: PASS (3 passed). Also run the existing brief tests to confirm no regression: `pytest tests/agent_teams/test_github_dispatch_service.py -k "brief or discovery" -v` → PASS.

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/github_dispatch_service.py backend/app/api/v1/agent_teams.py backend/mcp_shim/agent_mail_server.py backend/tests/agent_teams/test_github_dispatch_service.py
git commit -m "feat(dispatch): add ack_received signal and brain-owned ack timing"
```

---

## Task 3: Leader-ack timeout lifecycle in the monitor (finding #1)

Add the nudge-then-escalate lifecycle for a leader who hasn't acked. Ack anchors on `dispatched_at` (stable — owner status reports can't reset it). Design issues get the generous multiplier. Reviewer gate: past ack timeout → nudge (not escalate); still no ack past nudge grace → escalate `leader_ack_timeout`; ack received → nothing.

**Files:**
- Modify: `backend/app/services/github_dispatch_service.py` (`monitor_dispatched` loop ~425-438; add helpers `_ack_satisfied`, `_ack_deadline_seconds`, `_nudge_leader_for_ack`)
- Test: `backend/tests/agent_teams/test_github_dispatch_service.py`

**Interfaces:**
- Consumes: `dispatched_at`, `ack_received_at`, `last_nudge_at`, ack settings (Task 1); `escalate` (existing); `notify_team`/`_slot_member` (existing).
- Produces: `_ack_satisfied(item) -> bool` (True if `ack_received_at` or `pr_number` set); `_ack_deadline_seconds(item) -> int` (base × multiplier for design); `_nudge_leader_for_ack(db, item, leader)` (sends one Agent Mail to the leader slot member, sets `item.last_nudge_at`). New escalation reason string `"leader_ack_timeout"`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/agent_teams/test_github_dispatch_service.py`:

```python
@pytest.mark.asyncio
async def test_monitor_nudges_leader_on_ack_timeout(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    # dispatched long enough ago to pass registration grace AND ack timeout
    old = datetime.utcnow() - timedelta(
        seconds=settings.github_leader_ack_timeout_seconds
        + settings.github_owner_registration_grace_seconds
        + 10
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=920,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        dispatched_at=old,
        updated_at=old,
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.monitor_dispatched(
        db, scope, preset_slots=slots,
        wake_state_by_slot={architect.id: "wakeable", backend.id: "wakeable"},
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"       # nudged, not escalated
    assert item.last_nudge_at is not None
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_monitor_escalates_leader_ack_after_nudge_grace(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    old = datetime.utcnow() - timedelta(
        seconds=settings.github_leader_ack_timeout_seconds
        + settings.github_owner_registration_grace_seconds
        + 10
    )
    nudged = datetime.utcnow() - timedelta(seconds=settings.github_nudge_grace_seconds + 5)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=921,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        dispatched_at=old,
        updated_at=old,
        last_nudge_at=nudged,
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.monitor_dispatched(
        db, scope, preset_slots=slots,
        wake_state_by_slot={architect.id: "wakeable", backend.id: "wakeable"},
    )
    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "leader_ack_timeout"


@pytest.mark.asyncio
async def test_monitor_design_item_uses_ack_multiplier(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    # aged past the CODE ack timeout but within the DESIGN (× multiplier) timeout
    age = settings.github_leader_ack_timeout_seconds + \
        settings.github_owner_registration_grace_seconds + 10
    assert age < settings.github_leader_ack_timeout_seconds * settings.github_design_ack_multiplier
    old = datetime.utcnow() - timedelta(seconds=age)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=922,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        issue_type="design",
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        dispatched_at=old,
        updated_at=old,
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.monitor_dispatched(
        db, scope, preset_slots=slots,
        wake_state_by_slot={architect.id: "wakeable", backend.id: "wakeable"},
    )
    await db.refresh(item)
    # design item is NOT yet past its (longer) ack timeout → no nudge
    assert item.dispatch_status == "dispatched"
    assert item.last_nudge_at is None


@pytest.mark.asyncio
async def test_monitor_no_ack_action_when_ack_received(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    old = datetime.utcnow() - timedelta(
        seconds=settings.github_leader_ack_timeout_seconds
        + settings.github_owner_registration_grace_seconds
        + 10
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=923,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        dispatched_at=old,
        updated_at=datetime.utcnow(),
        ack_received_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.monitor_dispatched(
        db, scope, preset_slots=slots,
        wake_state_by_slot={architect.id: "wakeable", backend.id: "wakeable"},
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.last_nudge_at is None
    assert item.escalation_reason is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py -k "ack_timeout or ack_after_nudge or ack_multiplier or no_ack_action" -v`
Expected: FAIL — the monitor takes no ack action today, so `last_nudge_at` stays None and the escalate case stays `dispatched`.

- [ ] **Step 3: Add the ack helpers**

In `backend/app/services/github_dispatch_service.py`, add near `_within_registration_grace` (~line 440):

```python
    def _ack_satisfied(self, item: GithubWorkItem) -> bool:
        return item.ack_received_at is not None or item.pr_number is not None

    def _ack_deadline_seconds(self, item: GithubWorkItem) -> int:
        base = settings.github_leader_ack_timeout_seconds
        if item.issue_type == "design":
            return base * settings.github_design_ack_multiplier
        return base

    async def _nudge_leader_for_ack(
        self, db: AsyncSession, item: GithubWorkItem, leader: AgentTeamSlot
    ) -> None:
        member = await self._slot_member(db, leader.id)
        item.last_nudge_at = datetime.utcnow()
        if member is not None:
            from app.services.agent_mail_service import agent_mail_service

            await agent_mail_service.send_direct_message(
                db,
                recipient_member_id=member.id,
                subject=f"Ack needed: issue #{item.issue_number}",
                body_markdown=(
                    f"The owner is waiting on your acknowledgment for issue "
                    f"#{item.issue_number} ({item.issue_title}). Please review their "
                    "plan and acknowledge so work can proceed."
                ),
                payload={
                    "kind": "github_dispatch_ack_nudge",
                    "work_item_id": item.id,
                    "issue_number": item.issue_number,
                },
            )
        await db.commit()
```

- [ ] **Step 4: Add the ack lifecycle to the monitor loop**

In `monitor_dispatched`, extend the per-item loop. After the existing `owner_offline` escalation block (line 436-437), add the ack lifecycle. The full loop body becomes:

```python
        for item in dispatched:
            if self._within_registration_grace(item):
                continue
            if leader_wake == "offline":
                await self.escalate(db, item, "leader_offline")
                continue
            owner_wake = (
                wake_state_by_slot.get(item.owner_slot_id)
                if item.owner_slot_id is not None
                else None
            )
            if owner_wake == "offline":
                await self.escalate(db, item, "owner_offline")
                continue
            if not self._ack_satisfied(item):
                anchor = item.dispatched_at or item.updated_at or item.created_at
                overdue = datetime.utcnow() - anchor > timedelta(
                    seconds=self._ack_deadline_seconds(item)
                )
                if not overdue:
                    continue
                if item.last_nudge_at is None:
                    await self._nudge_leader_for_ack(db, item, leader)
                elif datetime.utcnow() - item.last_nudge_at > timedelta(
                    seconds=settings.github_nudge_grace_seconds
                ):
                    await self.escalate(db, item, "leader_ack_timeout")
                continue
        await db.commit()
```

Note: the `continue` after the ack block leaves room for Task 4's idle branch to slot in as the `else` of `if not self._ack_satisfied(item)`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py -k "ack_timeout or ack_after_nudge or ack_multiplier or no_ack_action" -v`
Expected: PASS (4 passed). Regression: `pytest tests/agent_teams/test_github_dispatch_service.py -k "monitor" -v` → all existing monitor tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/github_dispatch_service.py backend/tests/agent_teams/test_github_dispatch_service.py
git commit -m "feat(dispatch): brain-owned leader-ack nudge-then-escalate lifecycle"
```

---

## Task 4: Owner-idle timeout lifecycle in the monitor (finding #2)

Same nudge-then-escalate shape for an alive owner who has acked but produced no PR. Idle anchors on `updated_at` (activity anchor — owner status reports reset it, encoding "still working, don't escalate"). Reviewer gate: idle past timeout → nudge owner; owner activity since nudge → re-nudge, not escalate; silent past nudge grace → escalate `owner_idle_timeout`.

**Files:**
- Modify: `backend/app/services/github_dispatch_service.py` (`monitor_dispatched` loop — add the `else` branch after Task 3's ack block; add `_nudge_owner_for_progress` helper)
- Test: `backend/tests/agent_teams/test_github_dispatch_service.py`

**Interfaces:**
- Consumes: `updated_at`, `last_nudge_at`, `github_owner_idle_timeout_seconds`, `github_nudge_grace_seconds`; `notify_owner` (existing, `backend/app/services/github_dispatch_service.py:489`); `escalate`.
- Produces: `_nudge_owner_for_progress(db, item)` (sends one Agent Mail to the owner via `notify_owner`, sets `item.last_nudge_at`). New escalation reason string `"owner_idle_timeout"`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/agent_teams/test_github_dispatch_service.py`:

```python
@pytest.mark.asyncio
async def test_monitor_nudges_idle_owner_after_ack(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    old = datetime.utcnow() - timedelta(
        seconds=settings.github_owner_idle_timeout_seconds + 30
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=930,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        dispatched_at=old,
        updated_at=old,          # no activity since dispatch → idle anchor is old
        ack_received_at=old,     # ack satisfied → idle phase applies
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.monitor_dispatched(
        db, scope, preset_slots=slots,
        wake_state_by_slot={architect.id: "wakeable", backend.id: "wakeable"},
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"     # nudged, not escalated
    assert item.last_nudge_at is not None
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_monitor_idle_owner_activity_resets_clock(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    old = datetime.utcnow() - timedelta(
        seconds=settings.github_owner_idle_timeout_seconds + 30
    )
    nudged = old + timedelta(seconds=1)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=931,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        dispatched_at=old,
        ack_received_at=old,
        last_nudge_at=nudged,          # was nudged earlier...
        updated_at=datetime.utcnow(),  # ...but owner has since shown activity
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.monitor_dispatched(
        db, scope, preset_slots=slots,
        wake_state_by_slot={architect.id: "wakeable", backend.id: "wakeable"},
    )
    await db.refresh(item)
    # recent activity → not overdue → left alone, not escalated
    assert item.dispatch_status == "dispatched"
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_monitor_escalates_idle_owner_after_nudge_grace(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    old = datetime.utcnow() - timedelta(
        seconds=settings.github_owner_idle_timeout_seconds + 60
    )
    nudged = datetime.utcnow() - timedelta(seconds=settings.github_nudge_grace_seconds + 5)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=932,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        dispatched_at=old,
        ack_received_at=old,
        updated_at=old,        # no activity since before the nudge
        last_nudge_at=nudged,
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.monitor_dispatched(
        db, scope, preset_slots=slots,
        wake_state_by_slot={architect.id: "wakeable", backend.id: "wakeable"},
    )
    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "owner_idle_timeout"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py -k "idle_owner" -v`
Expected: FAIL — no idle branch yet, so items stay `dispatched` with `last_nudge_at` untouched (nudge test) and never escalate (grace test).

- [ ] **Step 3: Add the idle nudge helper**

In `backend/app/services/github_dispatch_service.py`, near `_nudge_leader_for_ack`:

```python
    async def _nudge_owner_for_progress(
        self, db: AsyncSession, item: GithubWorkItem
    ) -> None:
        item.last_nudge_at = datetime.utcnow()
        await self.notify_owner(
            db,
            item,
            subject=f"Progress check: issue #{item.issue_number}",
            body_markdown=(
                f"No PR yet for issue #{item.issue_number} ({item.issue_title}). "
                "Are you still making progress? Reply or report your status. If you "
                "are blocked, report `blocked` so a human can help."
            ),
            payload={
                "kind": "github_dispatch_idle_nudge",
                "work_item_id": item.id,
                "issue_number": item.issue_number,
            },
        )
        await db.commit()
```

Note: `notify_owner` (line 489) commits nothing itself; the explicit `await db.commit()` here persists `last_nudge_at`.

- [ ] **Step 4: Add the idle branch to the monitor loop**

In `monitor_dispatched`, replace Task 3's `if not self._ack_satisfied(item): ... continue` block's trailing `continue` with an `else` idle branch. The ack+idle section becomes:

```python
            if not self._ack_satisfied(item):
                anchor = item.dispatched_at or item.updated_at or item.created_at
                overdue = datetime.utcnow() - anchor > timedelta(
                    seconds=self._ack_deadline_seconds(item)
                )
                if not overdue:
                    continue
                if item.last_nudge_at is None:
                    await self._nudge_leader_for_ack(db, item, leader)
                elif datetime.utcnow() - item.last_nudge_at > timedelta(
                    seconds=settings.github_nudge_grace_seconds
                ):
                    await self.escalate(db, item, "leader_ack_timeout")
                continue
            # ack satisfied, owner alive, still no PR → idle lifecycle
            idle_anchor = item.updated_at or item.created_at
            idle_overdue = datetime.utcnow() - idle_anchor > timedelta(
                seconds=settings.github_owner_idle_timeout_seconds
            )
            if not idle_overdue:
                continue
            if item.last_nudge_at is None or item.last_nudge_at < idle_anchor:
                await self._nudge_owner_for_progress(db, item)
            elif datetime.utcnow() - item.last_nudge_at > timedelta(
                seconds=settings.github_nudge_grace_seconds
            ):
                await self.escalate(db, item, "owner_idle_timeout")
```

The `item.last_nudge_at < idle_anchor` clause is the "activity resets the clock" rule: if the owner's last activity (`updated_at`) is newer than the last nudge, treat it as fresh progress and nudge again rather than escalate.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py -k "idle_owner" -v`
Expected: PASS (3 passed). Regression: `pytest tests/agent_teams/test_github_dispatch_service.py -k "monitor or ack" -v` → all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/github_dispatch_service.py backend/tests/agent_teams/test_github_dispatch_service.py
git commit -m "feat(dispatch): brain-owned owner-idle nudge-then-escalate lifecycle"
```

---

## Task 5: Pre-auto-merge head re-confirm guard (finding #3)

Before an auto-merge, re-confirm the current head is the one we verified and still green. On any mismatch, demote to `verifying` and let the existing §7a loop re-check. Gated behind `merge_policy=="auto"` so human-merge is untouched. Reviewer gate: moved head → not merged, demoted; head unchanged but red → not merged, demoted; head unchanged and green → merged as today.

**Files:**
- Modify: `backend/app/services/github_verification_service.py:181-223` (`_process_review_item`, insert guard before `client.merge_pull`); add helper `_head_is_green`
- Test: `backend/tests/agent_teams/test_github_verification_service.py`

**Interfaces:**
- Consumes: `item.last_verified_sha` (set at promotion), `client.get_pull`, `client.list_check_runs_for_ref`, `self._head_sha` (line 446), `_SUCCESS_CONCLUSIONS` (line 16).
- Produces: `_head_is_green(scope, client, head_sha) -> bool` (True iff there are completed check-runs and all conclusions are in `_SUCCESS_CONCLUSIONS`). On guard failure: `item.dispatch_status = "verifying"`, `item.status_note` explains, commit, return (no merge).

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/agent_teams/test_github_verification_service.py` (follow the existing fake-client pattern in that file — inspect a nearby test for the exact `scope`/`item` fixture helpers and a stub client shape, then mirror them):

```python
@pytest.mark.asyncio
async def test_auto_merge_demotes_when_head_moved(db):
    scope, item, client = await _auto_ready_item(
        db,
        last_verified_sha="aaa111",
        current_head="bbb222",          # head moved since promotion
        head_checks=[{"status": "completed", "conclusion": "success"}],
    )
    await github_verification_service._process_review_item(db, scope, item, client)
    await db.refresh(item)
    assert item.dispatch_status == "verifying"
    assert client.merged is False


@pytest.mark.asyncio
async def test_auto_merge_demotes_when_head_red(db):
    scope, item, client = await _auto_ready_item(
        db,
        last_verified_sha="aaa111",
        current_head="aaa111",          # same head...
        head_checks=[{"status": "completed", "conclusion": "failure"}],  # ...but now red
    )
    await github_verification_service._process_review_item(db, scope, item, client)
    await db.refresh(item)
    assert item.dispatch_status == "verifying"
    assert client.merged is False


@pytest.mark.asyncio
async def test_auto_merge_proceeds_when_head_unchanged_and_green(db):
    scope, item, client = await _auto_ready_item(
        db,
        last_verified_sha="aaa111",
        current_head="aaa111",
        head_checks=[{"status": "completed", "conclusion": "success"}],
    )
    await github_verification_service._process_review_item(db, scope, item, client)
    await db.refresh(item)
    assert item.dispatch_status == "merged"
    assert client.merged is True
```

Add the `_auto_ready_item` helper at the top of the test module (build a `TeamGithubScope` with `merge_policy="auto"`, a `GithubWorkItem` with `dispatch_status="ready_for_review"`, `issue_type="code"`, `pr_number=1`, the given `last_verified_sha`; and a stub client whose `get_pull` returns `{"merged": False, "mergeable_state": "clean", "head": {"sha": current_head}}`, `list_check_runs_for_ref` returns `head_checks`, and `merge_pull` sets `self.merged = True`). Mirror the exact stub-client conventions already used in this test file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_verification_service.py -k "auto_merge_demotes or head_unchanged" -v`
Expected: FAIL — today `_process_review_item` merges without re-confirming, so both demote tests wrongly reach `merged`/`client.merged is True`.

- [ ] **Step 3: Add the `_head_is_green` helper**

In `backend/app/services/github_verification_service.py`, add near `_head_sha` (~line 446):

```python
    async def _head_is_green(
        self, scope: TeamGithubScope, client: GithubClient, head_sha: str | None
    ) -> bool:
        if not head_sha:
            return False
        checks = await client.list_check_runs_for_ref(
            scope.repo_owner, scope.repo_name, head_sha
        )
        if not checks:
            return False
        if any(
            check.get("status") != "completed" or check.get("conclusion") is None
            for check in checks
        ):
            return False
        return all(
            check.get("conclusion") in _SUCCESS_CONCLUSIONS for check in checks
        )
```

- [ ] **Step 4: Insert the guard before `client.merge_pull`**

In `_process_review_item`, immediately before the `try:` block that calls `client.merge_pull` (currently line 201). After the transient-state check (line 192-200) and before `try:`:

```python
        merge_state = pull.get("mergeable_state")
        if merge_state in _TRANSIENT_MERGE_STATES:
            await self._record_transient_merge_failure(
                db, scope, item, f"mergeable_state={merge_state}",
            )
            return
        # Finding #3: re-confirm the CURRENT head is the verified one and still green
        # before an irreversible auto-merge. A commit pushed after promotion could
        # have moved or reddened the head; demote to verifying and let §7a re-check.
        current_head = self._head_sha(pull)
        if current_head != item.last_verified_sha or not await self._head_is_green(
            scope, client, current_head
        ):
            item.dispatch_status = "verifying"
            item.status_note = (
                "Head changed or is no longer green since promotion; re-verifying "
                "before auto-merge."
            )
            item.updated_at = datetime.utcnow()
            await db.commit()
            return
        try:
            await client.merge_pull(scope.repo_owner, scope.repo_name, int(item.pr_number))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_verification_service.py -k "auto_merge_demotes or head_unchanged" -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Run the full verification suite for regressions**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_verification_service.py -v`
Expected: PASS — existing auto-merge/human-fallback/design tests unaffected (the guard only adds a pre-merge check on the `auto` path; human/design return early at line 181-182 before reaching it).

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/github_verification_service.py backend/tests/agent_teams/test_github_verification_service.py
git commit -m "fix(verify): re-confirm head green before auto-merge (stale-ready guard)"
```

---

## Task 6: Full-suite verification + soak runbook

Confirm the whole dispatch/verify suite is green, then write the soak runbook and run-log template — the evidence artifact for the master-merge decision. Reviewer gate: full suite green; runbook covers cleanup, seeded design issues, both windows, and the per-issue outcome table.

**Files:**
- Create: `docs/superpowers/specs/2026-07-06-tizonia-roadmap-v1-soak-runbook.md`
- Test: (full existing suite — no new code)

- [ ] **Step 1: Run the full dispatch + verify + mail suite**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams tests/agent_mail -q`
Expected: PASS (all green — the prior 235+ tests plus the ~13 added here). If anything fails, fix before proceeding.

- [ ] **Step 2: Confirm the migration applies on a real pre-existing DB**

The DB at `backend/claude_registry.db` predates the new columns. Confirm the compat migration adds them cleanly on startup:

Run: `cd backend && source venv/bin/activate && python -c "import asyncio; from app.database import init_db; asyncio.run(init_db())" && python -c "import sqlite3; c=sqlite3.connect('claude_registry.db'); cols=[r[1] for r in c.execute('PRAGMA table_info(github_work_items)')]; print('dispatched_at' in cols, 'ack_received_at' in cols, 'last_nudge_at' in cols)"`
Expected: `True True True` (adjust the init entrypoint name if `init_db` differs — check `app/database.py` for the actual startup hook used by `main.py` lifespan).

- [ ] **Step 3: Write the soak runbook**

Create `docs/superpowers/specs/2026-07-06-tizonia-roadmap-v1-soak-runbook.md` with this content:

````markdown
# Tizonia roadmap:v1 Unattended Soak — Runbook

**Design:** `docs/superpowers/specs/2026-07-06-autonomous-dispatch-hardening-and-soak-design.md`
**Testbed:** `tizonia/tizonia-openmax-il` (public). Branch protection on `master` stays enabled.
**Finish line:** loop reliability across every `roadmap:v1` issue Deck picks up — NOT solving every issue. Easy issues merge; hard/blocked ones escalate cleanly and recoverably. A capability failure (agent can't do a hard issue) is acceptable; a *loop* failure (silent stranding, bad write, wrong-reason escalation, guard not firing) is not.

## Pre-flight

- [ ] Backend on `feature/autonomous-github-dispatch` at the post-hardening commit; `pytest tests/agent_teams tests/agent_mail -q` green.
- [ ] `GITHUB_TOKEN` exported with `repo`+`workflow` scope (`gh auth token`).
- [ ] Real default timing: `GITHUB_DISPATCH_INTERVAL_SECONDS=60`, `GITHUB_CHECK_SIGNAL_GRACE_SECONDS=120`. Leave the new ack/idle/nudge settings at code defaults (300 / ×3 / 900 / 180) unless a run shows they need tuning — record any change here.
- [ ] Team preset `tizonia-v1` (Leader + Generalist), both slots have fresh, actively-heartbeating sessions before enabling autonomy.
- [ ] Local tizonia checkout clean on `master`.

## Cleanup (spent e2e artifacts — do first, not soak work)

- [ ] Close leftover PR #857 and issue #856 (`agent-ready-e2e`, "CI signal grace-window validation rerun").
- [ ] Reconcile the local work-item state for #834 from prior runs.
- [ ] Confirm no `agent-ready-e2e` issues remain open: `gh issue list --repo tizonia/tizonia-openmax-il --label agent-ready-e2e --state open` → empty.

## Seed design issues (design-pipeline coverage — prerequisites for the hardest work)

Create 1–2 `agent-design` + `roadmap:v1` issues that genuinely de-risk implementation issues:

- [ ] Design note: yt-dlp backend integration approach (prerequisite for #822).
- [ ] Design note: libspotify removal blast-radius / v1 packaging strategy (prerequisite for #819 / #824 / #825).

These flow through the design pipeline (`awaiting_human_review`, no CI, never auto-merged) and exercise the design-tier ack timeout (× multiplier).

## Window 1 — human-merge

- [ ] Set scope `merge_policy=human`; `autonomy_enabled=true`. Leave running unattended, monitoring backend logs.
- [ ] Deck watches `agent-ready` + `roadmap:v1` (and the seeded `agent-design`) issues, works them, a human merges after review.
- [ ] For each issue Deck touches, record a row in the outcome table below.
- **Pass:** every touched issue ends `merged` OR `escalated(explainable reason)` OR `still-working`; ZERO silent stranding; ZERO unintended public write. At least one leader-ack lifecycle and (if it arises naturally) one idle lifecycle observed behaving correctly.
- [ ] On completion: `autonomy_enabled=false`, revert to a clean baseline.

## Window 2 — auto-merge (only after Window 1 is clean)

- [ ] Set scope `merge_policy=auto`; `autonomy_enabled=true`. Monitor logs.
- **Must observe:** the finding-#3 head re-confirm guard fires at least once on a moved/red head. If the roadmap doesn't produce one naturally, inject a controlled "red commit after promotion" on one scoped issue's PR to force it (like the original T-S3 inversion), and record it.
- **Also observe:** `max_auto_merges_per_day` cap enforced; per-slot concurrency queueing under real load.
- **Pass:** guard demonstrably blocked ≥1 stale/red head; cap + concurrency held; ZERO bad auto-merge.
- [ ] On completion: `autonomy_enabled=false`, `merge_policy` reverted.

## Safety invariants (both windows)

- No hand-editing DB rows to steer scenarios — drive via labels/config only.
- Do not terminate a dispatched session or report on its behalf unless positively confirmed dead (process gone / `wake_state=offline`).
- Branch protection on `master` stays enabled throughout.

## Per-issue outcome log

| Issue | Type | Owner | Outcome (merged / escalated(reason) / still-working) | Escalation explainable? | Notes |
|---|---|---|---|---|---|
| | | | | | |

## Verdict

- Window 1 clean (no silent stranding / bad write): <yes/no>
- Window 2: #3 guard fired ≥1×; cap + concurrency held; no bad auto-merge: <yes/no>
- **Cleared for integration→master merge (closes #272 / #275 / #277 / #280):** <yes/no>
````

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-07-06-tizonia-roadmap-v1-soak-runbook.md
git commit -m "docs: add tizonia roadmap:v1 unattended soak runbook"
```

---

## Self-Review

**1. Spec coverage:**
- §2 leader-ack lifecycle → Task 3 ✓
- §2 owner-idle lifecycle → Task 4 ✓
- §2 "ack received" detection (explicit `ack_received` + fast-path via pr_number) → Task 2 (`record_ack_received`) + `_ack_satisfied` in Task 3 ✓
- §2 wait-authority out of owner prompt → Task 2 (`_leader_ack_instruction` simplified) ✓
- §2 new settings + persistence + migration guards → Task 1 ✓
- §2 truthful reasons (`leader_ack_timeout`, `owner_idle_timeout`) → Tasks 3, 4 ✓
- §3 pre-auto-merge head re-confirm (Option B), human-merge untouched → Task 5 ✓
- §4 soak protocol (cleanup, seeded design issues, two windows, outcome table, safety) → Task 6 runbook ✓

**2. Placeholder scan:** No TBD/TODO. Task 5's `_auto_ready_item` helper is described precisely (fields + stub shape) but instructs mirroring the existing file's stub-client conventions rather than reprinting them — because that file's exact fixture style must be matched, not guessed; the implementer reads one nearby test. Every code step shows complete code.

**3. Type consistency:** `_ack_satisfied`, `_ack_deadline_seconds`, `_nudge_leader_for_ack`, `_nudge_owner_for_progress`, `record_ack_received`, `_head_is_green` — names identical across their defining task and consuming loop. Columns `dispatched_at` / `ack_received_at` / `last_nudge_at` consistent from Task 1 through Tasks 2–4. Settings names consistent Task 1 → Tasks 3–4. Escalation reason strings `leader_ack_timeout` / `owner_idle_timeout` consistent between service and tests.

## Notes for the implementer

- The scheduler (`github_dispatch_scheduler.run_repo_once:147`) already calls `monitor_dispatched(db, scope, slots)` and the monitor resolves `wake_state_by_slot` internally via `agent_mail_service.list_team`. No scheduler change is needed.
- Ack anchors on `dispatched_at` (stable) so a stalled owner spamming `triaging` cannot reset the ack clock; idle anchors on `updated_at` (activity) so a genuinely-working owner is never escalated. This split is intentional — do not "simplify" both onto one timestamp.
- `last_nudge_at` is reused across both wait phases; it is cleared when `ack_received` is reported (Task 2), so the idle phase starts with a clean nudge slate.
