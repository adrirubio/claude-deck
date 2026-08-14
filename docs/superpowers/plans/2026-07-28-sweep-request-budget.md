# Phase G1c implementation plan — prefilter the closed-issue sweep (Finding 15)

Design: `../specs/2026-07-28-sweep-request-budget-design.md`

Work TDD: write the failing test, run it, see it fail for the *expected reason*, then implement.

**New sub-branch off `feature/autonomous-github-dispatch`: `feature/autonomous-github-dispatch-phase-g1c`.** One PR back into `feature/autonomous-github-dispatch`. Do not merge it yourself.

Baseline before you start:

```bash
cd backend && source venv/bin/activate && pytest tests/agent_teams tests/agent_mail -q
# expect: 290 passed
```

Only one file changes in production: `backend/app/services/github_watcher_service.py`.

---

## Task 1 — make request volume assertable

**File:** `backend/tests/agent_teams/test_github_watcher_service.py`

`_FakeClient` (line 112) currently records nothing, so no test can prove a request was avoided. Add a counter — additive only, return semantics unchanged:

```python
class _FakeClient:
    def __init__(self, labeled=None, by_number=None):
        self._labeled = labeled or []
        self._by_number = by_number or {}
        self.by_number_calls = []          # NEW: each call's `numbers` argument

    async def get_issues_by_number(self, owner, repo, numbers):
        self.by_number_calls.append(list(numbers))   # NEW
        return {number: self._by_number[number] for number in numbers if number in self._by_number}
```

Run the suite. Still **290** — this changes no behaviour. If anything fails, you altered the fake's semantics; stop and report.

---

## Task 2 — the prefilter

**Step 1 (test first).** Add the four tests from the design's "Test obligations" (1–4). Follow the file's existing idioms: `_make_scope(db)`, `_issue(n, [labels])`, `issue["state"] = "closed"`, and drive via `_FakeClient(labeled=[...], by_number={...})`.

Note test 1 and 4 require the item's issue to appear in the `labeled` argument **with the dispatch label**, since that is what `poll_scope` passes through. Assert on `client.by_number_calls` — flatten it and check membership, since `_recheck_active_items` may also call through in some fixtures.

Names:

- `test_sweep_skips_issues_already_in_labeled_list`
- `test_sweep_fetches_only_issues_absent_from_labeled_list`
- `test_sweep_does_not_treat_absent_open_issue_as_closed`
- `test_sweep_makes_no_request_when_all_stalled_items_are_labeled`

Run them. 1, 2 and 4 should fail (no prefilter exists). **Test 3 should PASS immediately** — it is a regression guard for a shortcut you must not take. If test 3 fails now, stop and report: the sweep is already mis-inferring closure and the diagnosis needs revisiting.

**Step 2 (implement).** Give `_reconcile_closed_issues` a new keyword-only parameter and prefilter with it:

```python
    async def _reconcile_closed_issues(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        client: GithubClient,
        *,
        open_labeled_numbers: frozenset[int] = frozenset(),
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
        # Presence in the poll's open-labeled list proves the issue is open, so it
        # cannot be closed and needs no per-issue request. Absence proves NOTHING —
        # the issue may have closed, or merely had its label removed while staying
        # open — so absent items must still be fetched to learn their real state.
        stalled = [
            item for item in stalled if item.issue_number not in open_labeled_numbers
        ]
        if not stalled:
            return
        current = await client.get_issues_by_number(
            scope.repo_owner,
            scope.repo_name,
            [item.issue_number for item in stalled],
        )
        ...  # rest of the loop UNCHANGED
```

Then pass it from `poll_scope`, deriving the set from the `labeled` response it already has:

```python
        labeled = await client.list_issues_with_label(
            scope.repo_owner, scope.repo_name, scope.dispatch_label
        )
        for issue in labeled:
            await self._upsert_item(db, scope, issue)
        await self._recheck_active_items(db, scope, client)
        await self._reconcile_closed_issues(
            db,
            scope,
            client,
            open_labeled_numbers=frozenset(
                issue["number"] for issue in labeled
            ),
        )
```

Keep the parameter defaulted to `frozenset()` so any direct caller (tests included) that omits it gets the old, safe, fetch-everything behaviour.

**Do NOT** prefilter `_recheck_active_items` — its label-removal branch needs to see absence. **Do NOT** infer closure from absence anywhere. **Do NOT** touch `_complete_and_notify`, `escalate`, `_apply_escalation`, or any status constant.

---

## Task 3 — verify and open the PR

```bash
cd backend && source venv/bin/activate && pytest tests/agent_teams tests/agent_mail -q
git diff --stat app/models/database.py app/database.py requirements.txt app/services/github_client.py   # must be EMPTY
```

Expected: **294 passed** (290 + 4). Report the actual number.

Open ONE PR into `feature/autonomous-github-dispatch` describing:

- requests per poll 12 → 2, and that behaviour is otherwise bit-identical (the skipped items are open; the sweep already skipped open items);
- why the prefilter skips only on presence, naming the #858 absent-but-open case;
- the `_FakeClient` counter as the mechanism that makes the saving assertable;
- the final test count;
- confirmation the schema/client diff is empty.

Then STOP and report. Do not merge.
