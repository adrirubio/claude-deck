# Open Design Finding — leader-ack gate strands work when the leader is briefly unresponsive

**Status:** Open DESIGN question — NON-BLOCKING for the integration→master gate. Surfaced during the tizonia e2e run (T-S8 attempt, 2026-07-06). To be tackled **post-merge** as its own brainstorm→spec→plan cycle. See also the sibling deferred finding [`2026-07-05-dispatch-open-finding-stale-ready-state.md`](./2026-07-05-dispatch-open-finding-stale-ready-state.md) and the deferred §6 reachable-but-idle monitor work (below) — these three are one theme.

## What happened
T-S8 (CI grace-window scenario) never reached the behavior under test because the item escalated at the leader-ack step first. DB/mail evidence for work item 10 / issue #854:
- Owner (Generalist, member 14) dispatched correctly, received its brief, and sent the leader (member 16) two `deck_request_context` approval requests (mail 88 @ 22:58:43, mail 89 @ 22:58:54).
- The **leader session was not attentive during that window** — its heartbeat had a gap (prior `last_seen_at` 19:59, next 23:04). The leader answered (mail 92/93) at **23:04**, ~3 minutes *after* the owner had already given up.
- The owner waited ~1.5 min, then self-reported `blocked` → item escalated `plan_blocked` (via the status report; the reason string is a separate, minor inconsistency — see Note).

**Nothing here was a product bug.** The owner behaved reasonably; escalating rather than hanging forever is the safe behavior; §6 anticipates a slow/absent leader as a known failure mode. But it exposed a real design brittleness.

## The design question
A hard "leader must ack before work starts" gate strands work whenever the leader is briefly unresponsive. Is that the right design for real unattended operation, where leaders won't be instantly attentive at all hours?

### Key nuance — the brittleness is asymmetric by pipeline (do NOT soften uniformly)
- **Code issues:** the ack is a *catch-a-bad-plan-early* optimization. The PR is still human-reviewed before merge (human-merge-only), so an owner proceeding without ack is low-risk — the human merge gate still catches problems. Escalating on no-ack is arguably over-strict here.
- **Design issues:** the ack **is** the approval gate — the substitute for the brainstorming skill's human-approval requirement (the entire C1 fix). If the owner proceeds without ack, it writes a design doc with NO review — exactly what C1 forbids unattended. Here, stranding-on-no-ack is the gate **working as designed**.

So any redesign must be **tiered by pipeline**, not a uniform "soften the gate" — a uniform softening would quietly reopen C1.

### The deeper insight — wait-logic is in the wrong place
The proximate cause is that the **owner's prompt** decides how long to wait and when to give up (~1.5 min, improvised, inconsistent across runs). Better architecture: move "how long to wait for ack, nudge before giving up, then escalate" out of the owner prompt and into **the brain's §6 monitor**, which already has configurable timeouts, the generous design-issue multiplier, and (per its deferred stub) a nudge-before-escalate step. This is the **same work as the deferred §6 reachable-but-idle owner/leader idle path** — they should be designed together.

## Candidate directions (for the post-merge cycle — not decided here)
- **Central ack-timeout governance in §6:** the brain owns the ack wait/nudge/escalate lifecycle with configurable, pipeline-tiered timeouts, instead of the owner prompt.
- **Leader-nudge before escalate:** on an unanswered ack past a threshold, the brain nudges the leader (wake/ping) before escalating — closes the "leader was just briefly away" case.
- **Tiered proceed-vs-escalate:** code pipeline may proceed-after-timeout (PR still human-gated) while design pipeline strictly escalates (preserves C1). Explicitly a per-pipeline policy.
- **Leader liveness as a precondition:** don't dispatch (or warn) if no leader is attentive, rather than dispatching then stranding.

## Why non-blocking for the master merge
- The failure mode is a **visible, recoverable escalation** (escalated→pending recovery + Retry exist), not a silent loss or a bad merge.
- Under human-merge-only operation a human is watching and can Retry.
- It did not indicate a defect in the loop's correctness — the loop did the safe thing.
- The master merge gates on "the loop works correctly and safely," which the e2e run established. This is "works, but fragile under real-world leader latency" hardening — a next piece of work.

## Required before real UNATTENDED production operation (not before merge)
This should be resolved before Claude Deck runs genuinely unattended against a live roadmap at scale, since leader latency will be common there. Tackle as a brainstorm→spec→plan cycle, jointly with the deferred §6 reachable-but-idle monitor work.

## Note (minor, separate)
The escalation reason surfaced as `plan_blocked` (the owner's `status="blocked"` report reason) rather than a leader-ack-specific reason. Low priority; if the ack lifecycle moves into §6, it should get its own reason (e.g. `leader_ack_timeout`) for a truthful audit trail.
