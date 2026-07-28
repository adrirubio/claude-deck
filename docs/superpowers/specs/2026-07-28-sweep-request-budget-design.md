# Phase G1c design — the closed-issue sweep must not re-fetch what the poll already has

**Status:** design, ready to implement
**Found by:** tizonia soak, 2026-07-28 (see `2026-07-06-tizonia-roadmap-v1-soak-run-log.md`, **Finding 15**)
**Scope:** `backend/app/services/github_watcher_service.py` only
**Depends on:** Phase G1b (merged, `f70b946`). The token half of Finding 15 is already deployed; this is the second half.

## The problem

The G1b closed-issue sweep raised GitHub requests per poll from 1 to 12 and stopped autonomy entirely inside 11 minutes:

```
httpx.HTTPStatusError: Client error '403 rate limit exceeded' for url
'https://api.github.com/repos/tizonia/tizonia-openmax-il/issues?labels=agent-ready&state=open&per_page=100'
```

| | requests per poll | per hour @ 60s | vs anonymous 60/hr |
|---|---|---|---|
| pre-G1b | 1 label-list | 60 | exactly at the ceiling |
| post-G1b | 1 label-list + 11 sweep | 720 | **12× over** |

A read-only PAT is now deployed (5000/hr), so the outage is over. **This task is not about the outage** — it is about the fact that 10 of those 11 requests ask GitHub for data the poll is already holding.

`poll_scope` fetches `labeled` at line 32 — every open issue carrying the dispatch label, in one request. `_reconcile_closed_issues` then issues an individual `GET /issues/{n}` for each of the 11 escalated/failed items: 821–829, 834, 858. **Ten of those numbers are already in `labeled`.**

An item present in `labeled` is open by construction, and the sweep only acts on `state == "closed"`. So for those ten the request is made, the response is parsed, `state` is found to be `"open"`, and the item is skipped — a wasted round trip in every 60-second cycle, forever.

Correct cost is **2 requests per poll**: the label list, plus one lookup for #858, the only sweep-set item absent from it.

## Design principle

**The poll already knows which issues are open; don't ask GitHub twice in the same cycle.** `labeled` is authoritative for open-and-labeled within the poll, and `_reconcile_closed_issues` runs in the same cycle, so no staleness window is introduced that `poll_scope` does not already accept.

## The fix

Thread the labeled issue numbers from `poll_scope` into `_reconcile_closed_issues`, and skip any stalled item whose number is present. Fetch only the remainder.

## The trap — presence proves open, absence proves NOTHING

`list_issues_with_label` filters on **two** dimensions (`github_client.py:29-41`):

```python
params={"labels": label, "state": "open", "per_page": 100}
```

So an issue is absent from `labeled` if it closed **or** if its label was removed while it stayed open. The two are indistinguishable from the list alone.

**Therefore the prefilter may only skip on presence. It must never treat absence as closure.** Absent items must still be fetched individually to learn their real state.

This is not hypothetical. Live item 13 (**#858**, `escalated`/`dispatch_label_removed`, `pr_number=860`) is absent from `labeled` and **OPEN**. A shortcut that inferred "absent ⇒ closed" would flip it to `completed` and fire a bogus `notify_blocker_merged` to the Leader, telling the team a blocker cleared when it hasn't — corrupting the dependency signal the whole cascade runs on.

`get_issues_by_number` already returns `{}` for an empty list without making a request (`github_client.py:53-56`), so the all-present case naturally costs zero.

## Effect on the live soak

Requests per poll 12 → 2. Behaviour is otherwise **bit-identical**: the ten skipped items are open, and the sweep's existing `state != "closed"` check already skips open items. No item changes status as a result of this task. If any does, the prefilter is wrong.

## Explicitly out of scope

- Any change to `_ACTIVE_STATUSES`, `_CLOSED_ISSUE_RECONCILABLE_STATUSES`, or the label-removal branch.
- Any change to `escalate` / `_apply_escalation` / `_complete_and_notify` semantics.
- Prefiltering `_recheck_active_items`. Its statuses (`dispatched`/`verifying`/`awaiting_human_review`) legitimately need per-issue state, and its label-removal branch needs to know about absence. **Leave it alone.**
- Phase G2 (`slot_has_live_owner_session`, `reuse_existing`, the launch path).
- Finding 16 (worktree provisioning / dispatch brief wording).
- New statuses, endpoints, schema/migrations, dependencies.
- `github_client.py` — no change needed at all.

## Test obligations

All in `backend/tests/agent_teams/test_github_watcher_service.py`. `_FakeClient` needs a call counter so request volume is assertable — add a list that `get_issues_by_number` appends its `numbers` argument to. This is an additive change to the fake; do not alter its return semantics.

1. `test_sweep_skips_issues_already_in_labeled_list` — escalated item whose issue IS in `labeled` (open): no per-issue fetch is made for it, item unchanged.
2. `test_sweep_fetches_only_issues_absent_from_labeled_list` — two escalated items, one in `labeled`, one absent and closed: exactly one number is fetched, and only the absent-and-closed one reconciles to `completed`.
3. **`test_sweep_does_not_treat_absent_open_issue_as_closed`** — escalated item absent from `labeled` but **OPEN** when fetched → stays `escalated`, no notification. This is the #858 regression guard; it must fail if someone implements "absent ⇒ closed".
4. `test_sweep_makes_no_request_when_all_stalled_items_are_labeled` — all stalled items present in `labeled` → zero per-issue fetches.
5. All six G1b sweep tests must still pass unmodified.

Baseline to preserve: **290 passing** (`pytest tests/agent_teams tests/agent_mail -q`).
