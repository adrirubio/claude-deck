# Soak Defect Triad Hardening (Design)

**Status:** Approved design — ready for implementation.
**Date:** 2026-07-26
**Branch:** `feature/autonomous-github-dispatch` (integration branch; do NOT merge to master).
**Surfaced by:** Findings 10, 11 and a new Finding 12 of the tizonia roadmap:v1 soak (`2026-07-06-tizonia-roadmap-v1-soak-run-log.md`).
**Relation to #280:** these three are the "unattended operation needs physical-state awareness" family. Unlike findings #1/#6 (governance/identity, still deferred), all three here are fixed now — they are the remaining hard blockers to unattended operation.

## The common theme

Deck models **logical work**, not **physical resources**. Each existing guard is correct about its own abstraction and blind to the physical thing that actually breaks:

| Guard | Counts | Blind to | Defect |
|---|---|---|---|
| `max_concurrent_dispatched` | issues in flight | host memory | Finding 11 (OOM) |
| `slot_is_busy` | work items per slot | sessions per slot | Finding 10 (duplicate owner) |
| `_ack_satisfied` | timestamp presence | dispatch generation | Finding 12 (stale ack) |

Unattended operation is exactly the regime where that gap stops being academic. All three fixes narrow it.

---

## §1 — Finding 12 (NEW, correctness): retry silently bypasses the leader-ack gate

### Problem

`reset_for_retry` (`backend/app/services/github_dispatch_service.py:22`) clears `pr_number`, `last_verified_sha`, `retry_count`, `approval_round_count`, `pending_reason`, `handoff_*` — but **not `ack_received_at`**. And the gate is presence-only:

```python
def _ack_satisfied(self, item: GithubWorkItem) -> bool:      # :513
    return item.ack_received_at is not None or item.pr_number is not None
```

So a retried item carries a stale ack from its *previous* dispatch, and `monitor_dispatched` skips the leader-ack check forever after.

**Proven, not inferred.** Reconstructing the #819 case against the real model:

```
after reset_for_retry:
  ack_received_at  = 2026-07-24 17:30:05   <-- survives the reset
re-dispatched (leader has NOT acked):
  _ack_satisfied() = True                  <-- gate SKIPPED
```

Live DB corroboration — an ack 65 minutes **older** than the dispatch it vouches for:

```
#819 id=25 status=dispatched  ack=17:30:05  dispatched=18:35:56  STALE_ACK=True
#818 id=26 status=pending     ack=17:48:06  (survived the clean-slate retry)
```

**Why it matters:** the leader-ack gate is what catches a dispatched owner that never woke up. Every retried item — including both items reset during the 2026-07-24 clean-slate recovery — permanently skips it. Phase D deliberately anchors ack on `dispatched_at` (stable) so a *new* dispatch demands a *new* ack; the missing field defeats that intent.

**Note the asymmetry that hid it:** `record_ack_received` clears `last_nudge_at`, and the retry endpoint clears `last_nudge_at` — the nudge bookkeeping is handled in two places while the ack itself is handled in none.

### Fix — defence in depth (both halves)

1. **Clear the field on reset.** Add `item.ack_received_at = None` to `reset_for_retry`.
2. **Make the gate generation-aware.** An ack only counts if it post-dates the dispatch it vouches for:

```python
def _ack_satisfied(self, item: GithubWorkItem) -> bool:
    if item.pr_number is not None:
        return True
    if item.ack_received_at is None:
        return False
    if item.dispatched_at is not None and item.ack_received_at < item.dispatched_at:
        return False          # stale ack from a previous dispatch generation
    return True
```

Half 2 is the important one: it makes the guard **self-healing** and immune to any *future* transition that forgets to clear the field. A guard derived from a relationship between values is harder to break than one derived from a value's mere presence. Half 1 keeps the data clean.

`pr_number` remains an independent satisfier (an open PR is proof of work regardless of ack) — and `reset_for_retry` already clears it, so no staleness there.

---

## §2 — Finding 10 (serious): Deck can spawn a duplicate owner session

### Problem (root cause confirmed in code)

`dispatch_pending` launches with `reuse_existing=False` (`github_dispatch_service.py:172`), so **every dispatch spawns a NEW session** for a slot that already has a standing session. `slot_is_busy` (`:61`) prevents two *work items* per slot, but nothing prevents two *sessions* per slot.

Consequence, observed twice live: a slot's standing session and its own dispatched-owner session are both live and can race on the same files. On #819 a duplicate process mutated the isolated worktree (diff hash `cffd85ac→b93e145e` in 10s) **even though dispatch used a per-issue worktree** — proving worktree isolation alone is insufficient. Teardown found 6 tmux + 5 codex procs where ~3 were expected.

### Chosen fix — Deck-enforced one owner session per slot

Keep the fresh-context-per-work-item model (`reuse_existing=False`), but make Deck refuse to create a second concurrent owner session for a slot.

**Before spawning**, in `dispatch_pending`, treat "slot already has a live dispatched-owner session" as a *queue* condition, not an error:

```python
if await self.slot_has_live_owner_session(db, owner_slot_id):
    item.owner_slot_id = owner_slot_id
    item.routing_method = method
    item.pending_reason = "queued_owner_session_live"
    item.updated_at = datetime.utcnow()
    await db.commit()
    continue
```

**New predicate** `slot_has_live_owner_session(db, slot_id) -> bool` on `GithubDispatchService`:
- Query `MailAgentSession` rows with `team_slot_id == slot_id`.
- Count only **live** sessions, reusing the existing liveness predicate (`agent_mail_service._session_is_live` / `_effective_status`, `agent_mail_service.py:528`/`:652`) — do NOT hand-roll a new staleness threshold.
- Return True when a live session exists for that slot.

**Design notes:**
- `pending_reason="queued_owner_session_live"` mirrors the existing `queued_repo_cap`/`queued_slot_busy` vocabulary — the item stays `pending` and is retried next scheduler tick. Queue, don't escalate: a live standing session is the *normal* state, not a fault.
- **Interaction with the standing session (important):** every slot normally has a live standing session, so a naive check would block *all* dispatch. The predicate must distinguish a **dispatched-owner** session from the slot's **standing** session. Discriminator to confirm against the data (the implementer must verify, not guess): `MailAgentSession.source`, and/or correlating `session_key`/`tmux_target` with `agent_team_launch_items.session_name` for launches tied to a work item. If no reliable discriminator exists, the fallback is to record the spawned owner session's identity on the work item at dispatch time and key the check off that.
- No new schema unless the fallback above is needed.

**Out of scope:** quiescing the standing session while its owner is active (agent-level protocol, and the Leader already demonstrated a voluntary freeze works). This fix targets the Deck-side spawn guarantee only.

---

## §3 — Finding 11 (critical): no resource awareness

### Problem

`max_concurrent_dispatched` is a *dispatch* guardrail, not a *resource* guardrail. When the work is compilation, concurrency implicitly sets peak memory but nothing links them. On the 15Gi host, 3 concurrent C++ builds exhausted memory and killed the user session manager, which killed the agents' heartbeats → mass `leader_offline` escalations. Confirmed independently from `journalctl -b -2` (28 OOM lines, `npm run dev` and `snapd` invoking the oom-killer, `cc1plus` ~1GB RSS).

`max_concurrent_dispatched=1` is already applied and is the correct immediate fix, but it is config: the same OOM returns the moment concurrency is raised, and it says nothing about memory already consumed by other processes.

### Chosen fix — memory preflight gate

Admission control on available host memory, checked **before** dispatching each item:

```python
if self._available_memory_mb() < settings.github_min_available_memory_mb:
    item.pending_reason = "queued_low_memory"
    item.updated_at = datetime.utcnow()
    await db.commit()
    continue
```

- **New setting** `github_min_available_memory_mb: int = 3000` in `backend/app/config.py`.
- **Reading available memory:** parse `MemAvailable` from `/proc/meminfo` (Linux, no new dependency — do NOT add `psutil`). `MemAvailable` is the right field: it accounts for reclaimable cache, unlike `MemFree`. Must be **injectable** for tests (a helper method or a module-level function the test can monkeypatch), and must **fail open** — if the value can't be read (non-Linux, unreadable), do not block dispatch.
- Same queue-don't-escalate posture and `pending_reason` vocabulary as §2. The item retries next tick, so the gate is self-clearing once memory frees up.

**Why a floor rather than per-item cost modelling:** Deck cannot know a given issue's build cost without executing it. A floor is generic, requires no per-repo calibration, and prevents the *class* of failure. Per-work-item resource cost modelling stays deferred (run-log deferred decision A, offloading builds to a bigger host, is the real long-term answer).

---

## §4 — Testing

- **§1 stale ack:** `reset_for_retry` clears `ack_received_at`; `_ack_satisfied` returns False when `ack_received_at < dispatched_at`, True when it post-dates, True when `pr_number` is set regardless; a retried-then-redispatched item still gets nudged/escalated on leader silence (the regression that motivated this).
- **§2 duplicate owner:** with a live dispatched-owner session for the slot, dispatch does NOT spawn and the item is `pending` with `pending_reason="queued_owner_session_live"`; with only the standing session, dispatch DOES proceed (guards against the naive over-blocking failure mode); the item dispatches normally on a later tick once the owner session is gone.
- **§3 memory gate:** below the floor → not dispatched, `pending_reason="queued_low_memory"`, no launcher call; above the floor → dispatches; unreadable memory → fails open and dispatches.
- Full suite green (`pytest tests/agent_teams tests/agent_mail -q`), currently 262 passing.

## Scope / YAGNI

- No new schema (unless §2's fallback discriminator proves necessary).
- No auto-respawn of vanished members (run-log deferred decision B — still deferred).
- No per-work-item resource cost model; no cgroup/systemd memory limits; no remote build offload (deferred decision A).
- Findings #1 (leader self-ack) and #6 (agent/reviewer identity collision) remain **deferred** and remain Window 2 gates.

## Success criteria

- A retried work item demands a **fresh** leader ack; a stale ack cannot satisfy the gate (both halves verified by test).
- Deck never creates a second concurrent dispatched-owner session for a slot; excess work queues with a clear reason.
- Dispatch is refused when available memory is below the configured floor, and resumes automatically when it recovers.
- Full suite green; no schema change; autonomy remains OFF until the orchestrator re-arms it.

## Rollout

Handed to the impl agent (same workflow as Phases D/E): sub-branch off the integration branch → one PR back into it → orchestrator verifies against code+tests → merge to integration. Does NOT merge to master. Soak stays PAUSED (`preset.autonomy_enabled=false`) until these land and the orchestrator re-arms.
