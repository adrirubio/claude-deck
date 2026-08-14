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

> **⚠ REVISED 2026-07-27 — read this before implementing.** The first version of this task said "accept from `escalated`" unconditionally. **That was wrong** and the impl agent correctly refused it: unconditional acceptance repeals the **T-S6 human stop-signal** guarantee (`../specs/2026-07-05-tizonia-e2e-testbed-plan.md`, T-S6), enforced by `tests/agent_mail/test_dispatch_status_tool.py::test_pr_opened_rejected_after_item_escalated`. **That existing test is correct and must keep passing UNMODIFIED.** Not all escalations are equal — see the revised design's decision table. Implement the allow-list below.

**Step 1 (test first).** In `backend/tests/agent_teams/test_github_verification_service.py`, add:

- `test_pr_opened_accepted_from_recoverable_escalation` — `dispatch_status="escalated"`, `escalation_reason="plan_blocked"`, `issue_type="code"`. After `report_pr_opened(..., pr_number=865)`: `dispatch_status == "verifying"`, `pr_number == 865`, `escalation_reason is None`.
- `test_pr_opened_accepted_from_recoverable_escalation_design_item` — same but `issue_type="design"` → `awaiting_human_review`.
- `test_pr_opened_rejected_after_label_removed` — `escalation_reason="dispatch_label_removed"` → **raises `ValueError`**. This is the T-S6 guarantee; it is the most important test in this task.
- `test_pr_opened_rejected_after_retry_budget_exhausted` — `escalation_reason="retry_count_exhausted"` → raises.
- `test_pr_opened_rejected_from_unattributed_escalation` — `escalation_reason=None` → raises (default-deny).
- `test_pr_opened_still_rejected_from_merged` — `dispatch_status="merged"` → raises.

Run them. Only the first two may fail at this point; the four rejection tests should pass immediately against the *current* code (it rejects everything non-`dispatched`). If a rejection test fails now, STOP and report — your fixture is wrong.

**Step 2 (implement).** At module level in `github_verification_service.py`:

```python
# Escalations a late PR legitimately resolves: the agent said it was stuck, or Deck
# *inferred* it from a timer. A real PR is evidence that inference was wrong.
# Anything NOT listed here — including an unattributed escalation (reason=None) —
# stays rejected: default-deny. `dispatch_label_removed` is a human stop signal
# (T-S6) and `*_exhausted` are deliberate budget stops; both outrank a late PR.
_PR_OPENED_RECOVERABLE_ESCALATIONS = frozenset({
    "plan_blocked",
    "owner_idle_timeout",
    "owner_offline",
    "leader_offline",
    "leader_ack_timeout",
})
```

Then replace the guard in `report_pr_opened`:

```python
        recoverable = (
            item.dispatch_status == "escalated"
            and item.escalation_reason in _PR_OPENED_RECOVERABLE_ESCALATIONS
        )
        if item.dispatch_status != "dispatched" and not recoverable:
            raise ValueError(
                f"pr_opened is only valid for dispatched work items, or escalated "
                f"items with a recoverable reason; current status is "
                f"{item.dispatch_status} ({item.escalation_reason})"
            )
        if recoverable:
            item.escalation_reason = None
```

Everything after the existing `item.pr_number = pr_number` line is unchanged. **Do NOT** touch the `issue_type == "design"` branch or the notification bodies.

**Step 3 (verify you didn't break T-S6).** Run the pre-existing guard explicitly and confirm it still passes without edits:

```bash
pytest tests/agent_mail/test_dispatch_status_tool.py::test_pr_opened_rejected_after_item_escalated -q
```

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
