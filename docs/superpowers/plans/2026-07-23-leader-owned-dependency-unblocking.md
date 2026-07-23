# Leader-Owned Dependency Unblocking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a blocker issue merges/closes, notify the leader agent with the current escalated-dependents list, and give the leader an MCP tool to re-dispatch a now-unblocked escalated work item — closing Finding 7 (blocked dependents never auto-recover when their prerequisite lands).

**Architecture:** Two generic Deck primitives + a leader-prompt addition. (1) A shared async notify helper on `github_dispatch_service` fires a leader-directed Agent Mail message on any transition into `merged`/`completed`, with a self-contained `escalated_items` payload. (2) A new `deck_retry_work_item` MCP tool posts to the existing escalated-only retry endpoint. (3) The leader's dispatch brief gains dep-map + unblock instructions. Deck owns mechanics; the leader owns judgment.

**Tech Stack:** Python 3.11+, FastAPI, async SQLAlchemy 2.0, aiosqlite, pytest + pytest-asyncio. MCP shim in `backend/mcp_shim/` (FastMCP `@mcp.tool()` + `_dispatch_request`).

## Global Constraints

- **Design spec:** `docs/superpowers/specs/2026-07-23-leader-owned-dependency-unblocking-design.md` — implement it exactly. Read it first.
- **Branch:** work on the integration branch `feature/autonomous-github-dispatch`. Do NOT merge to master.
- **No Deck dependency schema, no auto-retry in Deck** — the leader holds the dep map and decides; Deck only notifies and executes an explicit retry. The only new Deck surfaces are the merge-notify helper and the retry MCP tool.
- **Merge-notify fires for human merges too** (not just auto-merge) — Window 1 is human-merge. Route both `_mark_merged` and the watcher `completed` path through the same helper.
- **Notify is best-effort** — if no leader member is registered, it is a no-op and must NOT fail the merge/watcher path (mirror `notify_owner`'s `if member is None: return`).
- **Tests:** run from `backend/` with the venv active: `cd backend && source venv/bin/activate`. Dispatch/verify tests live in `backend/tests/agent_teams/`; MCP-tool tests in `backend/tests/agent_mail/`.
- **Commit style:** conventional commits.

---

## File Structure

- `backend/app/services/github_dispatch_service.py` — new async helper `notify_blocker_merged(db, scope, item, preset_slots)` + private `_escalated_items_payload(db, scope)`; reuses `_leader_slot`, `_slot_member`, `send_direct_message`.
- `backend/app/services/github_verification_service.py` — call the helper after `_mark_merged` at its three sites (the two `if pull.get("merged")` paths + the auto-merge success path); these already have `db`, `scope`, `item`. `_process_scope`/`_verify_item`/`_process_review_item` must pass `preset_slots` (or the helper resolves the leader from the scope's preset — see Task 1).
- `backend/app/services/github_watcher_service.py` — call the same helper in `_recheck_active_items` when an issue transitions to `completed` (~line 93-96).
- `backend/mcp_shim/agent_mail_server.py` — new `@mcp.tool() deck_retry_work_item(work_item_id, reason)`.
- `backend/app/api/v1/agent_teams.py` — the retry endpoint (~line 405) already exists with the escalated-only guard; extend only to accept/record an optional `reason` (via a tiny request body) for the audit trail.
- Tests: `backend/tests/agent_teams/test_github_dispatch_service.py`, `.../test_github_verification_service.py`, `backend/tests/agent_mail/test_dispatch_status_tool.py` (or the nearest MCP-tool test module).

---

## Task 1: `notify_blocker_merged` helper + escalated-items payload

The core primitive: a leader-directed notification carrying the self-contained escalated-dependents list. Reviewer gate: given a merged item and a scope with a registered leader + some escalated items, the helper sends one direct message to the leader with the correct payload; with no leader registered it is a silent no-op.

**Files:**
- Modify: `backend/app/services/github_dispatch_service.py` (add two methods near `notify_owner`/`_send_escalation_broadcast`, ~line 588-680)
- Test: `backend/tests/agent_teams/test_github_dispatch_service.py`

**Interfaces:**
- Consumes (existing): `self._leader_slot(preset_slots) -> AgentTeamSlot | None` (line 294); `self._slot_member(db, slot_id) -> MailTeamMember | None` (line 687); `agent_mail_service.send_direct_message(db, *, recipient_member_id, subject, body_markdown, payload)`; `AgentTeamSlot`, `GithubWorkItem`, `TeamGithubScope`, `MailTeamMember` models.
- Produces:
  - `async _escalated_items_payload(db, scope) -> list[dict]` — returns `[{"work_item_id", "issue_number", "escalation_reason", "status_note"}, ...]` for the scope's `escalated` items.
  - `async notify_blocker_merged(db, scope, item, preset_slots) -> None` — resolves the leader slot→member; if none, returns (no-op); else sends a direct message with subject `f"Blocker merged: issue #{item.issue_number}"` and payload `{"kind": "github_dispatch_blocker_merged", "issue_number", "work_item_id", "scope_id", "escalated_items": [...]}`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/agent_teams/test_github_dispatch_service.py` (follow the existing `_team` fixture + `MailMessage` assertion style used by the monitor tests):

```python
@pytest.mark.asyncio
async def test_notify_blocker_merged_sends_leader_message_with_escalated_items(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]  # architect = leader (position 0)
    # register the leader member so the notify has a recipient
    from app.services.agent_mail_service import agent_mail_service
    leader_member = await agent_mail_service.get_or_create_slot_member(db, architect)
    await db.commit()
    # a merged item + two escalated dependents + one non-escalated (must be excluded)
    merged = GithubWorkItem(scope_id=scope.id, issue_number=816, issue_title="baseline",
        issue_url="u", github_updated_at=datetime.utcnow(), dispatch_status="merged")
    dep1 = GithubWorkItem(scope_id=scope.id, issue_number=817, issue_title="build",
        issue_url="u", github_updated_at=datetime.utcnow(), dispatch_status="escalated",
        escalation_reason="plan_blocked", status_note="Blocked by #816")
    dep2 = GithubWorkItem(scope_id=scope.id, issue_number=818, issue_title="gmusic",
        issue_url="u", github_updated_at=datetime.utcnow(), dispatch_status="escalated",
        escalation_reason="plan_blocked", status_note="Blocked by #817")
    other = GithubWorkItem(scope_id=scope.id, issue_number=828, issue_title="docs",
        issue_url="u", github_updated_at=datetime.utcnow(), dispatch_status="dispatched")
    db.add_all([merged, dep1, dep2, other])
    await db.commit()

    await github_dispatch_service.notify_blocker_merged(db, scope, merged, slots)

    messages = (await db.execute(select(MailMessage))).scalars().all()
    hit = [m for m in messages if (m.payload or {}).get("kind") == "github_dispatch_blocker_merged"]
    assert len(hit) == 1
    msg = hit[0]
    assert msg.recipient_member_id == leader_member.id
    assert "816" in (msg.subject or "")
    esc = {e["issue_number"] for e in msg.payload["escalated_items"]}
    assert esc == {817, 818}          # only escalated, not #828 (dispatched)
    ids = {e["work_item_id"] for e in msg.payload["escalated_items"]}
    assert dep1.id in ids and dep2.id in ids
    assert msg.payload["issue_number"] == 816


@pytest.mark.asyncio
async def test_notify_blocker_merged_noop_when_no_leader_registered(db):
    preset, slots, scope = await _team(db)
    # do NOT register any leader member
    merged = GithubWorkItem(scope_id=scope.id, issue_number=816, issue_title="x",
        issue_url="u", github_updated_at=datetime.utcnow(), dispatch_status="merged")
    db.add(merged)
    await db.commit()

    # must not raise, must send nothing
    await github_dispatch_service.notify_blocker_merged(db, scope, merged, slots)
    messages = (await db.execute(select(MailMessage))).scalars().all()
    assert not [m for m in messages if (m.payload or {}).get("kind") == "github_dispatch_blocker_merged"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py -k "notify_blocker_merged" -v`
Expected: FAIL — `AttributeError: 'GithubDispatchService' object has no attribute 'notify_blocker_merged'`.

- [ ] **Step 3: Implement the two methods**

In `backend/app/services/github_dispatch_service.py`, add near `notify_owner` (after `_send_label_removed_owner_message`, ~line 680):

```python
    async def _escalated_items_payload(
        self, db: AsyncSession, scope: TeamGithubScope
    ) -> list[dict]:
        rows = (
            await db.execute(
                select(GithubWorkItem).where(
                    GithubWorkItem.scope_id == scope.id,
                    GithubWorkItem.dispatch_status == "escalated",
                )
            )
        ).scalars().all()
        return [
            {
                "work_item_id": row.id,
                "issue_number": row.issue_number,
                "escalation_reason": row.escalation_reason,
                "status_note": row.status_note,
            }
            for row in rows
        ]

    async def notify_blocker_merged(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        item: GithubWorkItem,
        preset_slots: list[AgentTeamSlot],
    ) -> None:
        leader = self._leader_slot(preset_slots)
        if leader is None:
            return
        member = await self._slot_member(db, leader.id)
        if member is None:
            return
        escalated = await self._escalated_items_payload(db, scope)
        lines = [
            f"Blocker merged: issue #{item.issue_number} ({item.issue_title}).",
            "",
            "Currently escalated items (candidate dependents):",
        ]
        if escalated:
            for e in escalated:
                lines.append(
                    f"- #{e['issue_number']} (work_item {e['work_item_id']}): "
                    f"{e['status_note'] or e['escalation_reason']}"
                )
        else:
            lines.append("- (none)")
        lines += [
            "",
            "If any of these were blocked ONLY by the merged issue (and all their "
            "other blockers are resolved), call "
            "`deck_retry_work_item(work_item_id=<id>, reason=\"prerequisite #"
            f"{item.issue_number} merged\")` to re-dispatch them.",
        ]
        from app.services.agent_mail_service import agent_mail_service

        await agent_mail_service.send_direct_message(
            db,
            recipient_member_id=member.id,
            subject=f"Blocker merged: issue #{item.issue_number}",
            body_markdown="\n".join(lines),
            payload={
                "kind": "github_dispatch_blocker_merged",
                "issue_number": item.issue_number,
                "work_item_id": item.id,
                "scope_id": item.scope_id,
                "escalated_items": escalated,
            },
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py -k "notify_blocker_merged" -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/github_dispatch_service.py backend/tests/agent_teams/test_github_dispatch_service.py
git commit -m "feat(dispatch): add notify_blocker_merged leader notification with escalated-items payload"
```

---

## Task 2: Fire the notification from the merge + watcher paths

Wire the Task 1 helper into every terminal-merge/complete transition. Reviewer gate: a human-merged code item, an auto-merged item, and a watcher-completed (externally closed) item each fire exactly one `github_dispatch_blocker_merged` notification.

**Files:**
- Modify: `backend/app/services/github_verification_service.py` (`_verify_item` ~line 114-116, `_process_review_item` ~line 177-179, auto-merge success ~line 233-234)
- Modify: `backend/app/services/github_watcher_service.py` (`_recheck_active_items` ~line 93-96)
- Test: `backend/tests/agent_teams/test_github_verification_service.py`

**Interfaces:**
- Consumes: `github_dispatch_service.notify_blocker_merged(db, scope, item, preset_slots)` (Task 1). All call sites must obtain `preset_slots`. `_verify_item`/`_process_review_item` receive `scope` but not slots today — load the preset's slots inside the call (query `AgentTeamSlot` by `scope.preset_id`, ordered by position) via a small helper `self._preset_slots(db, scope)` in the verification service, OR pass slots down from `process_scope`. Use the query helper (simplest, no signature churn).
- Produces: no new public signatures; behavior change only.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/agent_teams/test_github_verification_service.py` (reuse the file's stub-client + fixture conventions; mirror an existing merge test):

```python
@pytest.mark.asyncio
async def test_human_merge_fires_blocker_merged_notification(db):
    # scope with merge_policy=human, a registered leader, an item whose PR is now merged
    scope, item, client = await _merged_pull_item(db, merge_policy="human")
    # (helper: builds preset+leader slot+registered leader member, a ready_for_review item,
    #  and a stub client whose get_pull returns {"merged": True})
    await github_verification_service._process_review_item(db, scope, item, client)
    await db.refresh(item)
    assert item.dispatch_status == "merged"
    from app.models.database import MailMessage
    msgs = (await db.execute(select(MailMessage))).scalars().all()
    assert any((m.payload or {}).get("kind") == "github_dispatch_blocker_merged" for m in msgs)
```

Build `_merged_pull_item` at the top of the test module following the file's existing scope/item/stub-client helpers (register a leader member via `agent_mail_service.get_or_create_slot_member` so the notify has a recipient).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_verification_service.py -k "fires_blocker_merged" -v`
Expected: FAIL — no `github_dispatch_blocker_merged` message (notification not wired yet).

- [ ] **Step 3: Add the preset-slots helper + wire the three verification call sites**

In `backend/app/services/github_verification_service.py`, add a helper:

```python
    async def _preset_slots(self, db: AsyncSession, scope: TeamGithubScope) -> list:
        from app.models.database import AgentTeamSlot
        return (
            await db.execute(
                select(AgentTeamSlot)
                .where(AgentTeamSlot.preset_id == scope.preset_id)
                .order_by(AgentTeamSlot.position, AgentTeamSlot.id)
            )
        ).scalars().all()
```

Then after each `self._mark_merged(item)` that represents a terminal merge, add the notify. For `_verify_item` (line 114-116):

```python
        if pull.get("merged"):
            self._mark_merged(item)
            await db.commit()
            slots = await self._preset_slots(db, scope)
            await github_dispatch_service.notify_blocker_merged(db, scope, item, slots)
            await db.commit()
            return
```

Apply the identical pattern after the `_mark_merged(item)` in `_process_review_item` (line 177-179) and after the auto-merge success `_mark_merged(item)` + `auto_merged_at` (line 233-234). (Import `github_dispatch_service` is already present in this module.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_verification_service.py -k "fires_blocker_merged" -v`
Expected: PASS.

- [ ] **Step 5: Wire the watcher completed path + test**

Add to `backend/tests/agent_teams/test_github_dispatch_service.py` (watcher test file may differ — put it wherever `github_watcher_service` is tested; if none, add to the watcher's test module):

```python
@pytest.mark.asyncio
async def test_watcher_completed_fires_blocker_merged_notification(db):
    # an ACTIVE item (awaiting_human_review) whose GitHub issue is now closed → completed
    preset, slots, scope = await _team(db)
    from app.services.agent_mail_service import agent_mail_service
    await agent_mail_service.get_or_create_slot_member(db, slots[0])  # leader
    item = GithubWorkItem(scope_id=scope.id, issue_number=858, issue_title="design",
        issue_url="u", github_updated_at=datetime.utcnow(),
        dispatch_status="awaiting_human_review")
    db.add(item); await db.commit()

    class _Client:
        async def get_issues_by_number(self, owner, repo, numbers):
            return {858: {"state": "closed", "title": "design", "labels": []}}

    from app.services.github_watcher_service import github_watcher_service
    await github_watcher_service._recheck_active_items(db, scope, _Client())
    await db.refresh(item)
    assert item.dispatch_status == "completed"
    msgs = (await db.execute(select(MailMessage))).scalars().all()
    assert any((m.payload or {}).get("kind") == "github_dispatch_blocker_merged" for m in msgs)
```

In `backend/app/services/github_watcher_service.py`, in `_recheck_active_items`, after setting `completed` (line 93-96):

```python
            if issue is not None and issue.get("state") == "closed":
                item.dispatch_status = "completed"
                item.escalation_reason = None
                item.updated_at = datetime.utcnow()
                slots = (
                    await db.execute(
                        select(AgentTeamSlot)
                        .where(AgentTeamSlot.preset_id == scope.preset_id)
                        .order_by(AgentTeamSlot.position, AgentTeamSlot.id)
                    )
                ).scalars().all()
                await github_dispatch_service.notify_blocker_merged(db, scope, item, slots)
                continue
```

Add `from app.models.database import AgentTeamSlot` to the watcher imports if absent.

- [ ] **Step 6: Run the watcher test + full verify/dispatch suites**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams -k "blocker_merged or completed" -v && pytest tests/agent_teams -q`
Expected: PASS; no regressions.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/github_verification_service.py backend/app/services/github_watcher_service.py backend/tests/agent_teams/
git commit -m "feat(dispatch): fire blocker-merged notification on merge and watcher-completed"
```

---

## Task 3: `deck_retry_work_item` MCP tool + endpoint reason

The leader's lever. Reviewer gate: the tool posts to the retry endpoint and returns its result; the endpoint records the leader's reason; the escalated-only guard still returns 409 for a non-escalated item.

**Files:**
- Modify: `backend/app/api/v1/agent_teams.py` (retry endpoint ~line 405-419) — accept an optional `reason`
- Modify: `backend/app/models/schemas.py` — tiny `GithubWorkItemRetryRequest` body (optional)
- Modify: `backend/mcp_shim/agent_mail_server.py` — new `@mcp.tool() deck_retry_work_item`
- Test: `backend/tests/agent_teams/test_github_work_items_api.py` (or the module where the retry endpoint is tested) + `backend/tests/agent_mail/` for the tool

**Interfaces:**
- Consumes: existing `POST /api/v1/agent-teams/github-work-items/{id}/retry` (escalated-only guard, 409 otherwise); `reset_for_retry`; MCP shim `_dispatch_request(method, path, **kwargs)`.
- Produces: endpoint accepts optional JSON body `{"reason": str}` → written to `item.status_note` before reset (audit); MCP tool `deck_retry_work_item(work_item_id: int, reason: str = "") -> dict`.

- [ ] **Step 1: Write the failing endpoint test**

Add to the retry endpoint's test module (find it: `grep -rl "github-work-items/.*/retry\|retry_github_work_item" backend/tests`). Test that a reason is recorded and the escalated-only guard holds:

```python
@pytest.mark.asyncio
async def test_retry_endpoint_records_reason(client, db):
    # seed an escalated work item (helper per the test module's conventions) -> id
    resp = await client.post(f"/api/v1/agent-teams/github-work-items/{item_id}/retry",
                             json={"reason": "prerequisite #816 merged"})
    assert resp.status_code == 200
    # after reset it is pending; the reason was recorded on the way through
    body = resp.json()
    assert body["dispatch_status"] == "pending"


@pytest.mark.asyncio
async def test_retry_endpoint_rejects_non_escalated(client, db):
    # seed a DISPATCHED item -> id
    resp = await client.post(f"/api/v1/agent-teams/github-work-items/{item_id}/retry",
                             json={"reason": "x"})
    assert resp.status_code == 409
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams -k "retry_endpoint" -v`
Expected: the reason test fails (endpoint takes no body today); the 409 test already passes (guard exists).

- [ ] **Step 3: Add the optional reason to the endpoint**

In `backend/app/models/schemas.py`, add:

```python
class GithubWorkItemRetryRequest(BaseModel):
    reason: Optional[str] = None
```

In `backend/app/api/v1/agent_teams.py`, extend the retry endpoint (line 408) to accept the body and record the reason BEFORE reset (so it survives as provenance in `status_note`; `reset_for_retry` sets status to pending but the note documents why):

```python
async def retry_github_work_item(
    work_item_id: int,
    request: GithubWorkItemRetryRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(GithubWorkItem, work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="GitHub work item not found")
    scope = await db.get(TeamGithubScope, item.scope_id)
    if scope is None:
        raise HTTPException(status_code=404, detail="GitHub scope not found")
    if item.dispatch_status != "escalated":
        raise HTTPException(status_code=409, detail="Only escalated work items can be retried")
    if request is not None and request.reason:
        item.pending_reason = f"retry requested: {request.reason}"
    github_dispatch_service.reset_for_retry(item)
    await db.commit()
    await db.refresh(item)
    return _work_item_response(item, scope)
```

Note: confirm `reset_for_retry` does not clear `pending_reason`, or set the reason after it — check the function; if it clears `pending_reason`, move the assignment to after `reset_for_retry(item)`. Import `GithubWorkItemRetryRequest`.

- [ ] **Step 4: Run endpoint tests**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams -k "retry_endpoint" -v`
Expected: PASS (both).

- [ ] **Step 5: Add the MCP tool**

In `backend/mcp_shim/agent_mail_server.py`, add near `deck_report_dispatch_status`:

```python
@mcp.tool()
def deck_retry_work_item(work_item_id: int, reason: str = "") -> dict:
    """Leader-only: request re-dispatch of an ESCALATED GitHub work item whose
    blockers are now resolved. Pass the work_item_id (from the blocker-merged
    notification's escalated_items) and a short reason, e.g.
    'prerequisite #816 merged'. Rejected (409) if the item is not escalated.
    """
    _ensure_registered()
    return _dispatch_request(
        "POST",
        f"/github-work-items/{work_item_id}/retry",
        json={"reason": reason},
    )
```

- [ ] **Step 6: Test the MCP tool**

Add a shim-level test mirroring the existing dispatch-status tool tests (they exercise the tool→endpoint path against the ASGI app). Assert that calling `deck_retry_work_item` on an escalated item returns `dispatch_status == "pending"`, and on a non-escalated item returns the 409 error shape. Run:
`cd backend && source venv/bin/activate && pytest tests/agent_mail -k "retry_work_item" -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/v1/agent_teams.py backend/app/models/schemas.py backend/mcp_shim/agent_mail_server.py backend/tests/
git commit -m "feat(dispatch): add deck_retry_work_item MCP tool + retry reason"
```

---

## Task 4: Leader dispatch-brief instructions (dep map + unblock behavior)

Teach the leader to build/maintain the dep map and act on blocker-merged notifications. Reviewer gate: the leader's brief text contains the dep-map + unblock instructions and references the real tool/payload names.

**Files:**
- Modify: `backend/app/services/github_dispatch_service.py` (`_leader_ack_instruction` / the brief-construction path that builds the leader's operating text — the same path Phase D used; find where the leader slot's brief/charter is assembled)
- Test: `backend/tests/agent_teams/test_github_dispatch_service.py`

**Interfaces:**
- Consumes: the existing brief-construction for a leader-owned or leader slot. If the leader only receives instructions when it is dispatched as an owner, the dep-map instructions must live in the leader's standing charter/bootstrap text instead — locate where the leader slot's persistent instructions are set (slot `charter`/`bootstrap_prompt`, or the team-launch prompt). Add the instructions there so the leader has them regardless of being dispatched.
- Produces: brief/charter text including the dep-map lifecycle + `deck_retry_work_item` usage.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/agent_teams/test_github_dispatch_service.py`:

```python
def test_leader_brief_includes_dep_map_and_unblock_instructions():
    # the function that builds the leader's operating instructions
    text = github_dispatch_service._leader_unblock_instructions()
    assert "dependency map" in text.lower()
    assert "deck_retry_work_item" in text
    assert "github_dispatch_blocker_merged" in text
    assert "all" in text.lower()  # only retry when ALL blockers resolved
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py -k "leader_brief_includes_dep_map" -v`
Expected: FAIL — `_leader_unblock_instructions` not defined.

- [ ] **Step 3: Add the instruction text + include it in the leader's brief**

In `backend/app/services/github_dispatch_service.py`, add:

```python
    def _leader_unblock_instructions(self) -> str:
        return (
            "DEPENDENCY UNBLOCKING (leader duty):\n"
            "- On team start, scan the roadmap issues and build a dependency map "
            "(parse 'Blocked by #N' / 'Dependencies' from each issue body): "
            "issue -> [blocker issues]. Note which blockers are already closed.\n"
            "- When you receive a `github_dispatch_blocker_merged` notification, mark "
            "that blocker satisfied in your map. For each ESCALATED dependent in the "
            "notification's `escalated_items`, check whether ALL of its blockers are now "
            "resolved.\n"
            "- For each dependent whose blockers are ALL resolved, call "
            "`deck_retry_work_item(work_item_id=<id from escalated_items>, "
            "reason=\"prerequisite #<n> merged\")` to re-dispatch it.\n"
            "- Only retry when ALL blockers are resolved (never on a single blocker for a "
            "multi-blocker issue). Do not retry the same dependent twice for one event. If "
            "a dependency is ambiguous, leave it escalated for a human."
        )
```

Then include `self._leader_unblock_instructions()` in the leader slot's operating text at the brief/charter assembly point (the same construction path Phase D's `_leader_ack_instruction` is used in). If the leader receives a brief only when dispatched, ALSO ensure these instructions reach the leader as standing guidance (append to the leader slot's launch/bootstrap prompt in the launch path). Locate via: `grep -n "_leader_ack_instruction\|charter\|bootstrap_prompt\|slot_prompt_overrides" backend/app/services/github_dispatch_service.py backend/app/services/agent_team_service.py`.

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py -k "leader_brief_includes_dep_map" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/github_dispatch_service.py backend/tests/agent_teams/test_github_dispatch_service.py
git commit -m "feat(dispatch): add leader dependency-map + unblock instructions"
```

---

## Task 5: Full-suite verification

Confirm the whole dispatch/verify/mail suite is green and the migration/DB are unaffected (no schema change here, but confirm nothing regressed). Reviewer gate: full suite green.

- [ ] **Step 1: Run the full suite**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams tests/agent_mail -q`
Expected: PASS (all green — prior tests plus the ~7 added here).

- [ ] **Step 2: Confirm no accidental schema/migration change**

Run: `cd backend && git diff --stat backend/app/models/database.py backend/app/database.py`
Expected: empty (this feature adds no columns; if `database.py` shows changes, that's an error — revert them).

- [ ] **Step 3: Commit (if any test-only fixups were needed)**

```bash
git add -A backend/tests
git commit -m "test(dispatch): full-suite green for leader-owned unblocking" --allow-empty
```

---

## Self-Review

**1. Spec coverage:**
- §1 merge notification (human + auto + watcher-completed), leader-directed, self-contained `escalated_items` payload, no-op without leader → Task 1 (helper) + Task 2 (wiring, all 3 verify sites + watcher) ✓
- §2 retry MCP tool reusing escalated-only endpoint, leader identity/reason → Task 3 ✓
- §3 leader dep-map + incremental-update + retry + guardrails instructions → Task 4 ✓
- §4 tests: notify payload correctness (escalated-only), human-merge fires, retry resets/409, watcher-completed fires → Tasks 1-3 tests + Task 5 ✓
- Scope/YAGNI: no dependency schema, no auto-retry, only the two primitives + prompt → honored (Task 5 Step 2 explicitly guards against a schema change) ✓

**2. Placeholder scan:** No TBD/TODO. Task 2/3/4 name a `grep` to locate an exact anchor (test module, brief-assembly point) rather than guessing a path — because those must match the repo's real layout; every code block is complete. Task 3 Step 3 flags the one thing the implementer must verify (`reset_for_retry` vs `pending_reason`) with the exact remedy.

**3. Type consistency:** `notify_blocker_merged(db, scope, item, preset_slots)`, `_escalated_items_payload(db, scope)`, `_preset_slots(db, scope)`, `_leader_unblock_instructions()`, `deck_retry_work_item(work_item_id, reason)`, payload `kind="github_dispatch_blocker_merged"` with `escalated_items[].work_item_id/issue_number/escalation_reason/status_note` — all names identical across defining task, wiring task, tests, and the leader-instruction text.

## Notes for the implementer

- The notify helper lives on `github_dispatch_service` (not the verification service) so both the verification service AND the watcher can call it without a circular import — both already import `github_dispatch_service`.
- Fire the notification AFTER the merge/complete state is committed, so the item's own terminal state is consistent and the `escalated_items` query reflects the post-merge world. (The merged item itself is `merged`/`completed`, so it won't appear in `escalated_items`.)
- Best-effort: wrap the notify in the merge path so a notify failure never rolls back a completed merge (mirror how `escalate()` guards its broadcast). If you add a try/except, log and continue.
- This adds NO schema and NO migration. If you find yourself editing `database.py`, stop — you've gone off-plan.
