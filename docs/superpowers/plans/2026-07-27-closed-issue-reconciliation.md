# Phase G1b implementation plan — closed-issue reconciliation (Finding 14)

Design: `../specs/2026-07-27-closed-issue-reconciliation-design.md`

Work TDD: write the failing test, run it, see it fail for the *expected reason*, then implement.

**Branch: continue on `feature/autonomous-github-dispatch-phase-g1`** and push to the **existing PR #301**. Do not open a second PR. Do not merge. Do not self-merge.

Baseline before you start — this is the post-G1 number, not 274:

```bash
cd backend && source venv/bin/activate && pytest tests/agent_teams tests/agent_mail -q
# expect: 284 passed
```

Only one file changes in production: `backend/app/services/github_watcher_service.py`.

---

## Task 1 — extract the reconciliation body (pure refactor, no behaviour change)

**File:** `backend/app/services/github_watcher_service.py`

`_recheck_active_items` currently inlines the completion + notification logic at lines 96–119. Two passes will need it, and they must not drift.

Extract it verbatim into a helper on the class:

```python
    async def _complete_and_notify(
        self, db: AsyncSession, scope: TeamGithubScope, item: GithubWorkItem
    ) -> None:
        item.dispatch_status = "completed"
        item.escalation_reason = None
        item.updated_at = datetime.utcnow()
        await db.commit()
        try:
            slots = (
                await db.execute(
                    select(AgentTeamSlot)
                    .where(AgentTeamSlot.preset_id == scope.preset_id)
                    .order_by(AgentTeamSlot.position, AgentTeamSlot.id)
                )
            ).scalars().all()
            await github_dispatch_service.notify_blocker_merged(db, scope, item, slots)
            await db.commit()
        except Exception:
            logger.exception(
                "Failed to send blocker-merged notification for work item %s", item.id
            )
            await db.rollback()
```

Then in `_recheck_active_items`, replace lines 97–118 with `await self._complete_and_notify(db, scope, item)`, keeping the `continue`.

**Run the suite now.** It must still be **284 passed** — this task changes no behaviour. If anything fails, you have altered semantics; stop and report.

---

## Task 2 — the closed-issue sweep

**Step 1 (test first).** In `backend/tests/agent_teams/test_github_watcher_service.py`, add the six tests from the design's "Test obligations". Follow the existing file's idioms: build scope via `_make_scope(db)`, build issues via `_issue(n, [labels])` then `issue["state"] = "closed"`, and drive with `_FakeClient(labeled=[], by_number={...})`. For the notification test, create the Leader `AgentTeamSlot` + `MailTeamMember` exactly as `test_watcher_completed_fires_blocker_merged_notification` does (that slot must be `position=0` to be found by `_leader_slot`).

Name them:

- `test_closed_issue_reconciles_escalated_item`
- `test_closed_issue_reconciliation_fires_blocker_merged_notification`
- `test_closed_issue_reconciles_failed_item`
- `test_closed_issue_skips_item_with_open_pr`
- `test_failed_item_with_label_removed_is_not_laundered_into_escalated`
- `test_escalated_item_with_open_labeled_issue_is_untouched`

Run them. The first three and the fourth should fail (no sweep exists yet); the fifth and sixth should **pass immediately** against current code — they are regression guards. If the fifth fails now, stop and report: it means the laundering bug already exists on some other path and the diagnosis needs revisiting.

**Step 2 (implement).** Add the constant next to the existing two at the top of the module:

```python
# A closed issue is ground truth from GitHub and outranks Deck's stale inference
# that an item is stuck. Kept separate from _ACTIVE_STATUSES on purpose: that
# tuple also drives the label-removal branch, which would flip `failed` items to
# `escalated` (and thus make them retryable) behind the operator's back.
_CLOSED_ISSUE_RECONCILABLE_STATUSES = ("escalated", "failed")
```

Add the second pass as its own method:

```python
    async def _reconcile_closed_issues(
        self, db: AsyncSession, scope: TeamGithubScope, client: GithubClient
    ) -> None:
        stalled = (
            await db.execute(
                select(GithubWorkItem).where(
                    GithubWorkItem.scope_id == scope.id,
                    GithubWorkItem.dispatch_status.in_(
                        _CLOSED_ISSUE_RECONCILABLE_STATUSES
                    ),
                )
            )
        ).scalars().all()
        if not stalled:
            return
        current = await client.get_issues_by_number(
            scope.repo_owner,
            scope.repo_name,
            [item.issue_number for item in stalled],
        )
        for item in stalled:
            issue = current.get(item.issue_number)
            if issue is None or issue.get("state") != "closed":
                continue
            if item.pr_number is not None:
                logger.info(
                    "Work item %s (issue #%s) has a closed issue but an unresolved "
                    "PR #%s; leaving it for the verification path",
                    item.id,
                    item.issue_number,
                    item.pr_number,
                )
                continue
            await self._complete_and_notify(db, scope, item)
```

Call it from `poll_scope`, **after** `_recheck_active_items` (so an item that legitimately transitions during the active pass is not examined twice in one poll):

```python
        await self._recheck_active_items(db, scope, client)
        await self._reconcile_closed_issues(db, scope, client)
```

**Do NOT** add `escalated` or `failed` to `_ACTIVE_STATUSES`. **Do NOT** touch the `still_labeled` / label-removal branch. **Do NOT** modify `escalate` or `_apply_escalation`.

---

## Task 3 — verify and update the PR

```bash
cd backend && source venv/bin/activate && pytest tests/agent_teams tests/agent_mail -q
git diff --stat app/models/database.py app/database.py requirements.txt   # must be EMPTY
```

Expected: **290 passed** (284 + 6). Report the actual number.

Push to the existing branch and **update PR #301's description** with a new section covering this change:

- the extracted `_complete_and_notify` helper (pure refactor, verified at 284 before the sweep was added);
- the new closed-issue sweep and why it is a separate query rather than a widened `_ACTIVE_STATUSES` (name the `failed` → `escalated` laundering trap);
- the `pr_number is not None` skip;
- the final test count;
- confirmation the schema diff is empty.

Then STOP and report. The orchestrator reviews before merge, and merging this restarts the live soak cascade — that is the orchestrator's call, not yours.
