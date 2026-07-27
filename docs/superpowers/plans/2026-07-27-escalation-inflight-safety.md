# Phase G1 implementation plan — escalation in-flight safety

Design: `../specs/2026-07-27-escalation-inflight-safety-design.md`

Work TDD: write the failing test, run it, see it fail for the *expected reason*, then implement.

Branch: `feature/autonomous-github-dispatch-phase-g1` off `feature/autonomous-github-dispatch`.
One PR back into `feature/autonomous-github-dispatch`. Do not merge to master. Do not self-merge.

Baseline before you start — record the number, it must not regress:

```bash
cd backend && source venv/bin/activate && pytest tests/agent_teams tests/agent_mail -q
# expect: 274 passed
```

---

## Task 1 — `pr_opened` accepted from `escalated`

**File:** `backend/app/services/github_verification_service.py` (~line 39)

Current:

```python
if item.dispatch_status != "dispatched":
    raise ValueError(
        f"pr_opened is only valid for dispatched work items; current status is "
        f"{item.dispatch_status}"
    )
```

**Step 1 (test first).** In `backend/tests/agent_teams/test_github_verification_service.py`, add:

- `test_pr_opened_accepted_from_escalated` — item `dispatch_status="escalated"`, `escalation_reason="plan_blocked"`, `issue_type="code"`. After `report_pr_opened(..., pr_number=865)`: `dispatch_status == "verifying"`, `pr_number == 865`, `escalation_reason is None`.
- `test_pr_opened_accepted_from_escalated_design_item` — same but `issue_type="design"` → `dispatch_status == "awaiting_human_review"`.
- `test_pr_opened_still_rejected_from_merged` — `dispatch_status="merged"` → still raises `ValueError`. This is the regression guard; do not skip it.

Run them. The first two must fail with the current `ValueError`. If they fail for any *other* reason, STOP and report — your fixture is wrong, not the code.

**Step 2 (implement).** Allow the two valid entry states and clear the escalation when accepting from it:

```python
if item.dispatch_status not in ("dispatched", "escalated"):
    raise ValueError(
        f"pr_opened is only valid for dispatched or escalated work items; current "
        f"status is {item.dispatch_status}"
    )
if item.dispatch_status == "escalated":
    item.escalation_reason = None
```

Place this before the existing `item.pr_number = pr_number` line. Everything after it is unchanged.

**Do NOT** touch the `issue_type == "design"` branch or the notification bodies.

---

## Task 2 — retry refuses to orphan an open PR

**File:** `backend/app/api/v1/agent_teams.py`, `retry_github_work_item` (~line 409)

**Step 1 (test first).** The retry endpoint is tested in `backend/tests/agent_teams/test_agent_team_api.py`. Add there — do not create a new module:

- `test_retry_rejected_when_pr_open` — escalated item with `pr_number=865` → **409**, and the response detail mentions `865`. Then re-read the item from the DB and assert it is **unchanged**: `pr_number == 865`, `dispatch_status == "escalated"`.
- `test_retry_allowed_when_no_pr` — escalated item with `pr_number=None` → 200, `dispatch_status == "pending"`.

### ⚠ Known collision — read before you run anything

`test_github_work_item_feed_and_retry_guard` (same file, ~line 269) builds its `escalated` fixture with **`pr_number=12`** and then asserts the retry returns **200**. Change 2 makes that a 409, so **this pre-existing test will fail. That failure is expected and correct.**

This is the one case in this plan where you SHOULD edit an existing test, because the fixture — not the assertion — is what is wrong: the test's purpose is to prove the *status* guard (dispatched → 409, escalated → 200), and `pr_number=12` is incidental scaffolding that now contradicts a new, deliberate rule.

**Do exactly this and nothing more:** change that fixture's `pr_number=12` to `pr_number=None`. Leave every assertion in that test untouched. Then state in the PR that you changed it, quoting this paragraph as your authorisation.

If any *other* pre-existing test fails, that is NOT covered by this authorisation — report it, do not rewrite it.

**Step 2 (implement).** Add the guard *after* the existing `escalated` check and *before* `reset_for_retry`:

```python
    if item.pr_number is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Work item has PR #{item.pr_number} already open; retry would orphan "
                "it. Resolve or close the PR first."
            ),
        )
```

**Do NOT** add this guard inside `reset_for_retry` — the watcher calls that function on its own recovery path and must keep its current behaviour.

---

## Task 3 — escalation broadcast flags a possibly-live owner

**File:** `backend/app/services/github_dispatch_service.py`, `_send_escalation_broadcast` (~line 726)

**Step 1 (test first).** In `backend/tests/agent_teams/test_github_dispatch_service.py`:

- `test_escalation_broadcast_flags_active_owner` — escalate an item that is `dispatched` with an `owner_slot_id` set; assert the broadcast message's `payload["owner_may_be_active"] is True` and that its `body_markdown` warns against retrying.
- `test_escalation_broadcast_no_active_owner_for_pending_item` — escalate a `pending` item with no owner; assert `payload["owner_may_be_active"] is False`.

Read how the existing tests in that file capture broadcasts (there are already assertions on escalation broadcast payloads) and follow the same approach.

**Step 2 (implement).** `_apply_escalation` runs *before* the broadcast and overwrites `dispatch_status`, so capture the pre-escalation state in `escalate()` and pass it down. In `escalate()`:

```python
    async def escalate(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        reason: str,
        note: str | None = None,
    ) -> None:
        owner_may_be_active = (
            item.dispatch_status == "dispatched" and item.owner_slot_id is not None
        )
        applied = self._apply_escalation(item, reason, note)
        if not applied:
            return
        try:
            await self._send_escalation_broadcast(
                db, item, reason, note, owner_may_be_active=owner_may_be_active
            )
```

Then give `_send_escalation_broadcast` a keyword-only `owner_may_be_active: bool = False`, add `"owner_may_be_active": owner_may_be_active` to the payload dict it builds, and when true append a line to `lines`:

```
- NOTE: this item's owner session may still be working. Do NOT retry it — retrying
  clears any PR it has opened. Confirm with the coordinator first.
```

Keep the existing payload keys exactly as they are.

---

## Task 4 — verify and report

```bash
cd backend && source venv/bin/activate && pytest tests/agent_teams tests/agent_mail -q
git diff --stat app/models/database.py app/database.py requirements.txt   # must be EMPTY
```

Open the PR into `feature/autonomous-github-dispatch` stating:

- the three changes, one line each;
- the exact final test count (baseline was 274 — report the new number);
- confirmation the schema diff is empty;
- any pre-existing test that failed, **reported not rewritten**.

Then STOP. The orchestrator reviews before merge.
