# Leader-Owned Dependency Unblocking (Design)

**Status:** Approved design — ready for implementation planning.
**Date:** 2026-07-23
**Branch:** `feature/autonomous-github-dispatch` (integration branch; do NOT merge to master until the soak clears).
**Surfaced by:** Finding 7 of the tizonia roadmap:v1 soak (`2026-07-06-tizonia-roadmap-v1-soak-run-log.md`).
**Relation to #280:** joins findings #1 (leader self-ack) and #6 (agent/reviewer identity collision) as the "autonomy needs an orchestration signal a human currently provides" family — but this one is fixed now, not deferred.

## Problem (Finding 7)

The tizonia roadmap is a dependency DAG (issues declare `Blocked by #N` in prose). During Window 1 the agents correctly triaged and escalated `plan_blocked` for every blocked issue with accurate reasons — no fabricated PRs. But when a prerequisite merged (#816), the blocked dependents did **not** auto-recover:

- Deck has **no dependency model** — blocked detection is 100% agent triage (owner reads the issue body).
- The watcher's escalated→pending recovery gate is `github_updated_at > existing.github_updated_at` (spec §4). Merging a *prerequisite* does not bump the *dependent's* `updated_at` (GitHub doesn't cascade reference timestamps), so dependents never recover. Verified: #817 (blocked only by #816, now CLOSED/COMPLETED) stayed escalated with identical DB/GitHub timestamps.
- `_mark_merged` is **silent** — no event exists for anyone to react to when a blocker lands.
- The leader agent has **communication tools only** — no lever to trigger a re-dispatch. `reset_for_retry` / `POST /retry` exist but are human/API-only.

So "merge the root → watch the chain flow" does not happen. Unblocking a dependent currently requires a human `POST /retry` or an issue touch.

## Chosen approach — leader owns the judgment, Deck owns the mechanics

The leader agent supplies the cross-issue intelligence (which dependents are now unblocked); Deck supplies two generic, deterministic primitives (a merge signal and a retry lever). This mirrors the autonomous-factory split: the brain reasons, Deck's services act. Neither primitive is dependency-specific.

### Decisions (from brainstorming)

| Decision | Choice |
|---|---|
| How the leader knows the dep graph | Leader maintains a **running dep map** of the roadmap. |
| Map lifecycle | **Build once on team start**, update incrementally on merge events. |
| How the leader learns a blocker merged | **Deck sends the leader an Agent Mail notification** on merge/close. |
| How the leader triggers re-dispatch | **New MCP tool** the leader calls with the work_item_id. |
| Merge-notify fires for | **Any terminal merge/complete** — human merges too (Window 1 is human-merge). |

---

## §1 — Deck primitive: blocker-merged notification

**File:** `backend/app/services/github_verification_service.py` (`_mark_merged`, ~line 362) + the watcher's closed-issue `completed` path (`backend/app/services/github_watcher_service.py`, ~line 93).

Today `_mark_merged` silently sets `dispatch_status="merged"`. Add a leader-directed Agent Mail notification when an item transitions into a terminal merged/completed state, routed through **one shared helper** both call sites use, so:

- A human-merged code PR (`_verify_item`/`_process_review_item` → `_mark_merged`),
- an auto-merged PR (`_process_review_item` → `_mark_merged` + `auto_merged_at`),
- and the watcher marking an externally-closed issue `completed`,

**all** emit the notification. This matters: Window 1 is human-merge, so the notify must not be auto-merge-only.

**Notification shape:**
- Recipient: the **leader** (scope preset's first-position enabled slot → its Agent Mail member via `_slot_member`, mirroring the Phase D leader-ack resolution). Leader-directed, not a broadcast.
- Subject: e.g. `"Blocker merged: issue #<n>"`.
- Body: names the closed issue number + title, plus a readable list of the currently-escalated items (issue number + short reason) so the leader has full context in one message.
- Payload — self-contained so the leader needs **no follow-up read**:
  ```
  {
    "kind": "github_dispatch_blocker_merged",
    "issue_number": <merged issue #>,
    "work_item_id": <merged item id>,
    "scope_id": <id>,
    "escalated_items": [
      {"work_item_id": <id>, "issue_number": <n>, "escalation_reason": "plan_blocked", "status_note": "<triage note naming its blockers>"},
      ...
    ]
  }
  ```
  The `escalated_items` array is the scope's current `escalated` work items (the candidate dependents). Each carries the `issue_number` ↔ `work_item_id` mapping and the `status_note` (which already records the owner's triaged blockers), so the leader can, in one message: match its dep map against the merged issue, identify newly-fully-unblocked dependents, and call `deck_retry_work_item` with their `work_item_id` directly — no separate activity-feed query.

If the leader member is not registered, the notify is a no-op (do not fail the merge path) — same defensive posture as the existing owner/leader notify helpers.

## §2 — Deck primitive: leader retry lever (new MCP tool)

**Files:** `backend/mcp_shim/agent_mail_server.py` (new tool) + reuse endpoint `POST /api/v1/agent-teams/github-work-items/{id}/retry` (`backend/app/api/v1/agent_teams.py`, ~line 405).

New MCP tool `deck_retry_work_item(work_item_id: int, reason: str = "")`:
- POSTs to the existing retry endpoint, which already runs `reset_for_retry` behind an **escalated-only guard** (409 if `dispatch_status != "escalated"`). No new reset logic.
- Passes the caller's identity (the leader member, via the shim's `_ensure_registered()` pattern used by `deck_report_dispatch_status`) so the retry is auditable as leader-initiated. Include `reason` in the request for the audit trail / `status_note`.
- The escalated-only guard is a safety feature: the leader can revive an escalated item but can never disturb a working (`dispatched`/`verifying`) one.

Docstring names it as: "Leader-only: request re-dispatch of an escalated work item whose blockers are now resolved. Pass the work_item_id and a short reason (e.g. 'prerequisite #816 merged')."

## §3 — Leader-side behavior (operating instructions, not Deck code)

Lives in the **leader's dispatch/charter instructions** (the same brief-construction path Phase D uses for leader-ack). Deck supplies primitives; the leader supplies judgment.

- **Build (team start):** scan the scope's roadmap issues once; parse `Blocked by #N` / "Dependencies" prose from each body; form a dep map `issue → [blocker issues]`; note which blockers are already closed.
- **Maintain (incremental):** on each `github_dispatch_blocker_merged` notification, mark that blocker satisfied; recompute, for each escalated dependent, whether **all** its blockers are now closed.
- **Act:** for each newly-*fully*-unblocked dependent, call `deck_retry_work_item(work_item_id, reason="prerequisite #N merged")`.
- **Guardrails (in the prompt):**
  - Only retry when **all** of a dependent's blockers are satisfied (never premature-retry a multi-blocker issue on one blocker landing).
  - Don't retry the same dependent twice for the same event.
  - If a dependency is ambiguous or the map is uncertain, leave it escalated for a human — conservative, no-fabrication ethos (T-S4 lesson).

**Issue → work_item_id resolution:** no separate read needed. The merge notification payload's `escalated_items` array (§1) already carries every currently-escalated dependent's `issue_number` ↔ `work_item_id` (plus `status_note`). The leader matches its dep map against the merged issue, and for each newly-fully-unblocked dependent reads the `work_item_id` straight from the payload to call `deck_retry_work_item`. The notification is fully self-contained.

## §4 — Testing

- **Deck unit tests:**
  - `_mark_merged` fires the leader notification with the correct `github_dispatch_blocker_merged` payload; the watcher `completed` path fires it too; human-merge (not just auto-merge) triggers it.
  - The payload's `escalated_items` array lists exactly the scope's current `escalated` items with `issue_number` + `work_item_id` + `status_note` (assert against a fixture with a mix of escalated and non-escalated items — only escalated appear).
  - Notification is a no-op when no leader member is registered (merge path still succeeds).
  - `deck_retry_work_item` resets an escalated item to `pending`; returns 409 for a non-escalated item (reuses the existing retry-guard test).
- **Leader behavior:** validated in the **soak** (agent judgment has no unit test). Acceptance criterion = the live Finding-7 case: #816 merged → leader notified → leader retries #817 → #817 dispatches. 

## Scope / YAGNI

- **No Deck dependency schema** — the leader holds the map. Deck never parses `Blocked by #N`.
- **No auto-retry in Deck** — the leader decides; Deck only executes an explicit retry request.
- The merge-notify + retry tool are the **only** new Deck surfaces; everything else is a leader-prompt addition.
- Out of scope: a full dependency subsystem, GitHub native issue-dependencies integration, multi-scope dep graphs. Revisit only if the soak shows the leader-held map is insufficient.

## Rollout

- Phase-E-sized hardening. Handed to the impl agent (same workflow as Phase D): sub-branch off the integration branch → one PR back into it → orchestrator verifies against code+tests → merge to integration branch. Does not merge to master.
- After it lands: resume the soak; **#817 is the live acceptance test** for the whole mechanism.
- Feeds the #280 governance theme alongside findings #1 and #6.

## Success criteria

- Merge/complete of any item notifies the leader (human-merge included), verified in tests.
- `deck_retry_work_item` revives an escalated item and rejects a non-escalated one, verified in tests.
- Leader instructions produce a durable dep map and, on a blocker-merged notification, retry exactly the newly-fully-unblocked dependents.
- Live: merging #816 leads to #817 (and any other now-unblocked dependents) re-dispatching without human intervention.
