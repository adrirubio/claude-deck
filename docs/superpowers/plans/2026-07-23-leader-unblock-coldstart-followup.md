# Leader Unblock — Cold-Start Follow-up (Phase E.1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Close the Phase E cold-start seam (soak Finding 9): the leader knows an escalated dependent is unblocked at start-up but can't act because (a) it has no MCP tool to fetch escalated items' `work_item_id`s, and (b) its protocol only retries on a live `blocker_merged` notification. Add a `deck_list_work_items` read tool and amend the leader bootstrap to act on already-closed blockers at start-up.

**Architecture:** One new read-only MCP tool over the existing activity-feed endpoint, plus an addition to the leader's `_leader_unblock_instructions` text. No schema, no new endpoint, no change to the notification/retry mechanics from Phase E.

**Tech Stack:** Python 3.11+, FastAPI, async SQLAlchemy, FastMCP `@mcp.tool()` + `_dispatch_request`.

## Global Constraints

- **Design spec:** `docs/superpowers/specs/2026-07-23-leader-owned-dependency-unblocking-design.md` — §2b (new tool) and §3 "Cold-start action". Read them first.
- **Branch:** integration branch `feature/autonomous-github-dispatch`. Do NOT merge to master.
- **NO schema, NO migration, NO new endpoint.** Reuse `GET /api/v1/agent-teams/presets/{preset_id}/github-work-items` (exists, ~line 379). If you edit `database.py`, you're off-plan.
- **Reuse Phase E:** do not change `notify_blocker_merged`, `deck_retry_work_item`, or the notification-path retry logic. This only ADDS a read tool + start-up action.
- **Tests:** `cd backend && source venv/bin/activate`; MCP-tool tests in `backend/tests/agent_mail/`, dispatch text tests in `backend/tests/agent_teams/`.
- Conventional commits.

---

## Task 1: `deck_list_work_items` MCP read tool

Give the leader a read tool to fetch work items (default: escalated) with their `work_item_id` ↔ `issue_number` mapping, over the existing activity-feed endpoint. Reviewer gate: the tool returns the scope's escalated items with ids; it filters by status.

**Files:**
- Modify: `backend/mcp_shim/agent_mail_server.py` (new `@mcp.tool()`)
- (Reuse endpoint `GET /presets/{preset_id}/github-work-items` — no endpoint change. It returns items with `work_item_id`/`issue_number`/`dispatch_status`/`escalation_reason`/`status_note`.)
- Test: `backend/tests/agent_mail/test_dispatch_status_tool.py` (or nearest MCP-tool module)

**Interfaces:**
- Consumes: `_ensure_registered()` (resolves the caller's member, which carries `team_preset_id`); `_dispatch_request(method, path, **kwargs)`; existing endpoint `GET /presets/{preset_id}/github-work-items?limit=`.
- Produces: `deck_list_work_items(status: str = "escalated", limit: int = 100) -> dict` returning `{"ok": True, "items": [{"work_item_id", "issue_number", "dispatch_status", "escalation_reason", "status_note"}, ...]}` filtered to `status` (or all if `status=""`).

Note on preset resolution: the endpoint is keyed by `preset_id`. The registered member carries its `team_preset_id` (set at registration via `CLAUDE_DECK_TEAM_PRESET_ID`). Resolve it from the `_ensure_registered()` result / the shim's known member context the same way other tools obtain member identity. If the shim already stores `team_preset_id`, use it; otherwise read it from the `deck_whoami`/register response. Confirm via: `grep -n "team_preset_id\|CLAUDE_DECK_TEAM_PRESET_ID\|_state\[" backend/mcp_shim/agent_mail_server.py`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/agent_mail/test_dispatch_status_tool.py` (mirror the existing tool→ASGI test pattern in that module — it exercises the shim against the app). The test seeds a preset with escalated + non-escalated work items, registers a member for that preset, calls the tool, and asserts only escalated come back with ids:

```python
@pytest.mark.asyncio
async def test_deck_list_work_items_returns_escalated_with_ids(client_and_db, monkeypatch):
    ac, maker = client_and_db
    # seed: escalated #817 + dispatched #816 under the same preset/scope (use the module's seed helpers)
    esc_id = await _seed_item(maker, issue_number=817, dispatch_status="escalated",
                              status_note="Blocked by #816")
    await _seed_item(maker, issue_number=816, dispatch_status="dispatched")
    # register the caller as a member of that preset (module has a helper/pattern for this)
    # ... then invoke the shim tool wired to the ASGI client ...
    result = await _call_tool_list_work_items(ac, status="escalated")
    assert result["ok"] is True
    issues = {it["issue_number"] for it in result["items"]}
    assert 817 in issues and 816 not in issues
    row = next(it for it in result["items"] if it["issue_number"] == 817)
    assert row["work_item_id"] == esc_id
    assert "Blocked by #816" in (row["status_note"] or "")
```

Follow the exact seeding + tool-invocation conventions already in this test module (adapt `_seed_item`/`_call_*` to match). If the module's tools are tested by calling the shim function directly with a patched `_deck_request`, mirror that instead.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_mail/test_dispatch_status_tool.py -k "list_work_items" -v`
Expected: FAIL — tool not defined.

- [ ] **Step 3: Implement the tool**

In `backend/mcp_shim/agent_mail_server.py`, near `deck_retry_work_item`:

```python
@mcp.tool()
def deck_list_work_items(status: str = "escalated", limit: int = 100) -> dict:
    """Leader-only: list this team's GitHub dispatch work items with their
    work_item_id and issue_number. Defaults to escalated items (pass status=""
    for all). Use at team start to resolve which escalated dependents are now
    unblocked (per your dependency map) so you can call deck_retry_work_item
    with the correct work_item_id.
    """
    registered = _ensure_registered()
    if not registered["ok"]:
        return registered
    preset_id = registered["data"]["member"].get("team_preset_id")
    if preset_id is None:
        return {"ok": False, "error": {"code": "no_team_preset",
                "message": "Caller is not a member of a team preset."}}
    result = _dispatch_request(
        "GET", f"/presets/{preset_id}/github-work-items", params={"limit": limit}
    )
    if not result["ok"]:
        return result
    items = result["data"].get("items", [])
    if status:
        items = [it for it in items if it.get("dispatch_status") == status]
    slim = [
        {
            "work_item_id": it.get("work_item_id") or it.get("id"),
            "issue_number": it.get("issue_number"),
            "dispatch_status": it.get("dispatch_status"),
            "escalation_reason": it.get("escalation_reason"),
            "status_note": it.get("status_note"),
        }
        for it in items
    ]
    return {"ok": True, "items": slim}
```

Adjust the `work_item_id`/`id` field access to match the endpoint's actual response schema (`GithubWorkItemResponse` — confirm the field name via `grep -n "class GithubWorkItemResponse" -A 20 backend/app/models/schemas.py`; use whichever of `id`/`work_item_id` it exposes).

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_mail/test_dispatch_status_tool.py -k "list_work_items" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/mcp_shim/agent_mail_server.py backend/tests/agent_mail/test_dispatch_status_tool.py
git commit -m "feat(dispatch): add deck_list_work_items MCP read tool"
```

---

## Task 2: Leader bootstrap — act on already-closed blockers at start-up

Amend `_leader_unblock_instructions` so the start-up scan is actionable. Reviewer gate: the instruction text tells the leader to fetch escalated items via `deck_list_work_items` at start-up and retry those with all blockers already closed, with the same all-blockers-resolved guardrail.

**Files:**
- Modify: `backend/app/services/github_dispatch_service.py` (`_leader_unblock_instructions`)
- Test: `backend/tests/agent_teams/test_github_dispatch_service.py`

**Interfaces:**
- Consumes: nothing new (pure text).
- Produces: updated `_leader_unblock_instructions()` string that references `deck_list_work_items` and the start-up retry action, in addition to the existing notification-path text.

- [ ] **Step 1: Update the failing test**

In `backend/tests/agent_teams/test_github_dispatch_service.py`, extend `test_leader_unblock_instructions_text` (from Phase E):

```python
def test_leader_unblock_instructions_text():
    text = github_dispatch_service._leader_unblock_instructions()
    # notification path (existing)
    assert "github_dispatch_blocker_merged" in text
    assert "deck_retry_work_item" in text
    assert "all" in text.lower()
    # cold-start path (new)
    assert "deck_list_work_items" in text
    assert "start" in text.lower()  # act at team start on already-closed blockers
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py -k "leader_unblock_instructions_text" -v`
Expected: FAIL — `deck_list_work_items` not in the text yet.

- [ ] **Step 3: Amend the instruction text**

In `backend/app/services/github_dispatch_service.py`, update `_leader_unblock_instructions` to add the start-up action (keep the existing notification-path lines):

```python
    def _leader_unblock_instructions(self) -> str:
        return (
            "DEPENDENCY UNBLOCKING (leader duty):\n"
            "- On team start, scan the roadmap issues and build a dependency map "
            "(parse 'Blocked by #N' / 'Dependencies' from each issue body): "
            "issue -> [blocker issues]. Note which blockers are already closed.\n"
            "- ALSO at team start (cold-start recovery): call `deck_list_work_items"
            "(status=\"escalated\")` to get the current escalated items with their "
            "work_item_ids. For each escalated dependent whose blockers are ALL already "
            "closed (per your map), call `deck_retry_work_item(work_item_id=<id>, "
            "reason=\"prerequisite #<n> already merged\")`. This handles blockers that "
            "merged before you started (resume/respawn), where no notification arrives.\n"
            "- When you receive a `github_dispatch_blocker_merged` notification, mark "
            "that blocker satisfied in your map. For each ESCALATED dependent in the "
            "notification's `escalated_items`, check whether ALL of its blockers are now "
            "resolved.\n"
            "- For each dependent whose blockers are ALL resolved, call "
            "`deck_retry_work_item(work_item_id=<id>, "
            "reason=\"prerequisite #<n> merged\")` to re-dispatch it.\n"
            "- Only retry when ALL blockers are resolved (never on a single blocker for a "
            "multi-blocker issue). Do not retry the same dependent twice. If a dependency "
            "is ambiguous, leave it escalated for a human."
        )
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py -k "leader_unblock_instructions_text or bootstrap_prompt_appends" -v`
Expected: PASS (the bootstrap-delivery tests still pass — text still contains `deck_retry_work_item`).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/github_dispatch_service.py backend/tests/agent_teams/test_github_dispatch_service.py
git commit -m "feat(dispatch): leader acts on already-closed blockers at start-up (cold-start)"
```

---

## Task 3: Full-suite verification

- [ ] **Step 1: Run the full suite**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams tests/agent_mail -q`
Expected: PASS (all green).

- [ ] **Step 2: Confirm no schema/endpoint change**

Run: `cd backend && git diff --stat backend/app/models/database.py backend/app/database.py`
Expected: empty. (New MCP tool + prompt text + one reused GET endpoint only.)

---

## Self-Review

**1. Spec coverage:** §2b (deck_list_work_items over existing endpoint) → Task 1 ✓; §3 cold-start action (fetch at start, retry all-blockers-closed) → Task 2 ✓; all-blockers-resolved guardrail applies to both paths → Task 2 text ✓.

**2. Placeholder scan:** No TBD. Task 1 flags the two things the implementer must confirm against the real code (member `team_preset_id` access in the shim; the endpoint response's id field name) with exact `grep`s — because the shim's identity plumbing and the response schema must match, not be guessed.

**3. Type consistency:** `deck_list_work_items(status, limit)`, `_leader_unblock_instructions()`, field names `work_item_id`/`issue_number`/`dispatch_status`/`escalation_reason`/`status_note` consistent across tool, tests, and instruction text.

## Notes for the implementer

- This is a Phase E follow-up (call it Phase E.1). Sub-branch off the integration branch → one PR back → orchestrator verifies → merge. Do NOT touch the merged Phase E notification/retry code except to READ it.
- The `deck_list_work_items` tool is read-only; the actual retry still goes through the Phase E `deck_retry_work_item` (escalated-only guard). No new write path.
- Live acceptance test (orchestrator-run, not yours): after this lands, respawn the team; the leader's start-up scan should call `deck_list_work_items`, see #817 escalated with #816 closed, and `deck_retry_work_item(#817)` — #817 re-dispatches with NO notification needed.
