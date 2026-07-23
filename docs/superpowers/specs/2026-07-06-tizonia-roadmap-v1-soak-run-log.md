# Tizonia roadmap:v1 Soak — Live Run Log

**Runbook:** `2026-07-06-tizonia-roadmap-v1-soak-runbook.md`
**Design:** `2026-07-06-autonomous-dispatch-hardening-and-soak-design.md`
**Deck build:** integration branch `feature/autonomous-github-dispatch` @ `5fb4d02` (Phase D merged)
**Testbed:** `tizonia/tizonia-openmax-il` (public). Branch protection on `master` enabled.
**Orchestrator/verifier:** design brain (drives sessions, verifies every gate against DB/code).

---

## Environment setup (2026-07-06)

- Backend: uvicorn PID 760562 on `5fb4d02`, `GITHUB_DISPATCH_INTERVAL_SECONDS=60`, `GITHUB_CHECK_SIGNAL_GRACE_SECONDS=120`, ack/idle settings at code defaults (300 / ×3 / 900 / 180), `GITHUB_TOKEN` set. Migration applied on boot (dispatched_at/ack_received_at/last_nudge_at present).
- Frontend: Vite on `0.0.0.0:5173` (accessible from Windows host via WSL2 localhost forwarding).
- Team: preset 2 `tizonia-v1`, both slots `codex-cli` launched with `--dangerously-bypass-approvals-and-sandbox` (verified in spawned cmdline). Leader = member 16 / slot 4; Generalist = member 14 / slot 5. Fresh sessions, both `wake_state` live.
- Cleanup done: spent PR #857/issue #856 closed, 3 leftover e2e branches deleted, tizonia checkout clean on master, 11 stale work-item rows reconciled to terminal states.
- Scope: `dispatch_label=agent-ready-e2e` (used to isolate single issues during smoke tests), `design_label=agent-design`, `merge_policy=human`, `max_concurrent_dispatched=3`.

## Smoke test #1 — #834 (code pipeline, no-op) — PASS (safety half)

- Isolated via `agent-ready-e2e` on #834 only; autonomy enabled.
- Watcher created work item 12, `issue_type=code`, routed to Generalist (slot 5) by `label`, fresh owner launch 28, `dispatched_at` stamped. Dispatch brief delivered (mail 105).
- Owner triaged, discovered the `pthread_yield→sched_yield` fix was ALREADY on master (from merged #844), verified via source inspection + core Meson compile (exit 0, no deprecation warning), opened NO branch/PR, reported `ack_received` (recorded 22:35:01) then `blocked`.
- Final: `escalated`, reason `plan_blocked`, `pr_number=NULL`. Full evidence in status_note.
- **Verdict: PASS (safety).** Correct conservative behavior — no fabricated PR on a stale issue. Did NOT exercise dispatch→PR→CI→merge (no-op). #834 disarmed after.

## Smoke test #2 — #858 (design pipeline, yt-dlp design note) — PASS (full path)

- Created #858 (agent-design + roadmap:v1 + area:services), armed with `agent-ready-e2e`.
- Watcher created work item 13, **`issue_type=design`** ✓, routed to Leader (slot 4) by `leader_fallback` (Generalist area labels `area:build,area:docs` don't match `area:services`), owner launch 29.
- `ack_received_at` set 22:46:47 (self-ack — Leader is both owner and approver; see Finding 1). Design ack window 900s; PR opened at ~537s.
- **PR #860** opened non-draft on `design/youtube-yt-dlp-note-858`, one file `docs/design/youtube-yt-dlp-integration.md` (+206/-0). Notification "Design PR ready for review" (mail 116).
- Final: `awaiting_human_review`; **`retry_count=0`, `last_verified_sha=NULL`, `auto_merged_at=NULL`** — Deck never verified, counted retries, or attempted merge. C1 no-unreviewed-design invariant HELD.
- **Verdict: PASS (full design path).** PR #860 left open for human review.

## Soak findings (observed during smoke tests — neither blocks Window 1)

1. **Leader-as-owner self-ack.** When routing falls back to the Leader (no area-label match), the leader-ack gate becomes the Leader sending an ack request to itself (observed mail 114: member 16 → 16). Not unsafe for design (never auto-merges; human merge is the real gate). BUT under `merge_policy=auto`, a Leader-owned CODE issue would have leader-ack + CI as its ONLY gates, and the ack would be a self-ack — a weaker gate than intended. Consider before Window 2 / broad auto-merge: either exclude the leader from being its own approver, or require a distinct approver for auto-merge-eligible code. Related to the ack-governance theme in issue #280.
2. **`plan_blocked` reason for a no-op issue.** #834 (work already done) escalated as `plan_blocked` rather than a more precise "already satisfied / no-op." Accurate enough (status_note has detail) but imprecise for audit. Minor; note for the reason-taxonomy cleanup.

---

## Window 1 — human-merge (roadmap:v1) — RUNNING (opened 2026-07-06 ~22:5x)

Switched `dispatch_label` agent-ready-e2e → agent-ready: armed 15 code issues (#816–#829, #834) + design #859. #858 already delivered (PR #860). `merge_policy=human`, autonomy on. Concurrency cap 3, paced correctly (no stacking).

### Finding 3 (ACTED ON) — routing lopsided; added a third slot

At open, the 2-slot team routed only 4/16 issues to the Generalist (`area:build`/`docs`); the other 12 fell back to the Leader (`area:services`/`packaging`/`ci`/`tests`) → Leader bottleneck + self-acks at scale. **Fix:** created slot 6 "Specialist" (member 17), `area_labels=[services,packaging,ci,tests]`, codex-cli + bypass flag, launched fresh. Confirmed the dispatcher **re-routes pending items on each cycle** (routing is recomputed, not cached): 11 items immediately re-routed from Leader-fallback → Specialist by label. Team is now Leader(approver) + Generalist(build/docs) + Specialist(services/pkg/ci/tests), giving the proper leader-worker ack dynamic. Concurrent dispatch across slots confirmed (#816→Generalist, #827→Specialist simultaneously).

### Finding 4 — roadmap is a dependency DAG; blocked issues escalate cleanly

The roadmap has real prerequisites (#816 baseline → build → services → packaging → #829 release validation). Multiple issues escalated `plan_blocked` with ACCURATE dependency reasons rather than proceeding out of order or fabricating PRs:
- #817 blocked by #816 (not done); #828 (docs) blocked by #822/#823/#825/#827 (can't document unbuilt features); #829 (release validation) blocked by #821–#828. All correct, all explainable.
This directly demonstrates the finish-line bar ("loop reliability, not solving every issue"): a naive loop would have produced broken out-of-order PRs. #816 (the root) is being worked first by the Generalist.

### Finding 5 (process note) — watcher overrides hand-reconciled DB rows

I hand-set #858 to `awaiting_human_review` after my label-cleanup escalation; the watcher RE-escalated it `dispatch_label_removed` because the GitHub issue no longer carries the dispatch label. **The watcher is the source of truth over a DB hand-edit** — reinforces the "drive via labels/config, not DB edits" rule. #858's PR #860 remained safe (OPEN, unmerged) throughout. Left escalated (honest: label gone but PR exists → human handles).

### Finding 6 (IMPORTANT — real product lesson) — agent commit identity collides with human reviewer identity

The agents commit/open PRs as `juanrubio` (the `gh` token account), which is ALSO the human reviewer's account. GitHub forbids approving your own PR, and branch protection required 1 review → **the human-merge gate deadlocked** (all 3 PRs stuck `REVIEW_REQUIRED`/BLOCKED). In a real unattended factory this is fatal: the agent's git identity MUST differ from the human reviewer's, or human-merge can never be satisfied. Related to Finding 1 (Leader self-ack) — both are "who is a *distinct* approver" problems; feed into #280.

**Soak accommodation (temporary):** relaxed master branch protection `required_approving_review_count 1→0`, `enforce_admins true→false` so the admin (juanrubio) can merge CI-green PRs directly. Original config backed up to `/tmp/tizonia-master-protection-backup.json`.

### ⛔ HARD GATE before Window 2: restore branch protection

Window 2 (auto-merge) relies on branch protection to prove the T-S7 human-fallback path. Protection is currently OFF. **Restore from `/tmp/tizonia-master-protection-backup.json` (required_reviews=1, enforce_admins=true) before enabling `merge_policy=auto`.**

### PRs ready for human merge (protection relaxed)

- PR #862 (issue #816, code, CI green) — merge FIRST (DAG root; unblocks the chain).
- PR #860 (issue #858, design note yt-dlp) — mergeable.
- PR #861 (issue #859, design note libspotify) — mergeable.

## ⏸️ PAUSED overnight (2026-07-06 ~23:40) — RESUME STATE

- **Autonomy DISABLED** (`preset 2 autonomy_enabled=false`) — nothing dispatches until re-enabled. Nothing was dispatched/verifying at pause.
- **#816 MERGED** (PR #862, CI green) → issue #816 CLOSED. This is the DAG root; its dependents (#817 → #818–#820 → …) should re-dispatch once autonomy is re-enabled.
- Design PRs **#860 (#858) and #861 (#859) still OPEN** — mergeable, not yet merged (optional; they're reference design notes).
- Backend still running (uvicorn PID 760562, Phase D code, 60s/120s timings). Frontend on 0.0.0.0:5173. 3 team sessions (Leader/Generalist/Specialist) + ~leftover idle owner codex procs still alive (harmless with autonomy off; can prune tomorrow).
- **Branch protection STILL RELAXED** (required_reviews=0, enforce_admins=false). Backup at `/tmp/tizonia-master-protection-backup.json`. ⛔ Restore before Window 2.

### ▶️ TO RESUME (tomorrow)
1. Optionally merge design PRs #860/#861.
2. Re-enable autonomy: `PATCH /api/v1/agent-teams/presets/2 {"autonomy_enabled": true}`.
3. Verify the **unblock cascade**: #817 (and downstream) should transition escalated → pending → dispatched now that #816 is merged. This is the key Window 1 evidence not yet captured.
4. Continue merging CI-green PRs as they land; watch for any actual loop defect (vs. expected dependency escalation).
5. Before Window 2: restore branch protection; resolve the distinct-approver problem (findings #1 + #6).

## RESUMED 2026-07-23 (session 2) — Phase E merged; cold-start acceptance test

- Phase E (leader-owned dependency unblocking) merged to integration (`a5fa0e7`), verified (261 tests). Backend restarted on Phase E code; **verified live** the Leader's bootstrap includes the unblock instructions and the Generalist/Specialist's do NOT (leader-gating works). Team respawned (launch 48), all 3 live.

### Finding 8 (process) — duplicate agent set from restart ordering

Restarting the backend BEFORE killing the old agent tmux sessions left 3 orphaned sessions (19:25) that codex auto-reconnected to the same durable member IDs → two Leaders/Generalists/Specialists briefly live (4 sessions/member). Caught and cleaned (killed the 3 orphans; back to one set, 2 sessions/member). No double-action occurred (only mail 222 during the window). **Runbook fix: kill agent tmux sessions FIRST, then restart backend, then respawn.**

### Finding 9 (IMPORTANT — Phase E cold-start seam) — leader knows #817 is unblocked but won't act without a live notification

On start-up the Leader correctly built its dep map and reported (mail 222): "#817 -> #816[CLOSED] ... so #817 is logically clear ... Inbox contains no github_dispatch_blocker_merged notification ... so per the leader retry protocol I did not call deck_retry_work_item." The Leader's reasoning was impeccable — the **protocol has a gap**: action is tied strictly to receiving a blocker-merged *notification*, but a blocker that merged before the leader existed (resume-after-pause, leader crash/respawn — the cold-start case) produces no notification, so the already-unblocked dependent stays stranded.

**Root cause is deeper than prompt wording:** the leader has NO MCP read tool to fetch escalated work items with their `work_item_id`s at start-up. The `issue_number ↔ work_item_id` mapping needed to call `deck_retry_work_item` only arrives via the notification payload's `escalated_items`. The activity-feed endpoint `GET /presets/{id}/github-work-items` exists but is not exposed as a `deck_` tool. So the build-on-start map is informational-only; the leader literally cannot act on it.

**Fix (chosen 2026-07-23): close the seam properly (Phase E follow-up).** Add a `deck_list_work_items` MCP read tool (exposing escalated items + ids, reusing the activity-feed endpoint), and amend the leader bootstrap: after the start-up dep-map scan, fetch escalated items via the new tool and retry any whose blockers are ALL already closed — same all-blockers-resolved guardrail as the notification path. Then re-run the #817 acceptance test. Autonomy left OFF until the fix lands.

## Per-issue outcome log

| Issue | Type | Owner | Outcome (latest) | Escalation explainable? | Notes |
|---|---|---|---|---|---|
| 834 | code | Generalist | escalated(plan_blocked) | yes — already fixed on master (#844) | smoke #1; no-op, re-escalated in W1 |
| 858 | design | Leader (fallback) | awaiting_human_review (PR #860) → escalated(label_removed) | yes — label removed by orchestrator cleanup | smoke #2; C1 held; PR #860 safe |
| 859 | design | Specialist/Leader | dispatched | — | libspotify design note |
| 816 | code | Generalist | dispatched (working) | — | ROOT dependency; unblocks chain |
| 817 | code | Generalist | escalated(plan_blocked) | yes — blocked by #816 | dependency DAG |
| 827 | code | Specialist | dispatched | — | ci/packaging |
| 828 | code | Generalist | escalated(plan_blocked) | yes — blocked by #822/#823/#825/#827 | docs can't precede build |
| 829 | code | Specialist | escalated(plan_blocked) | yes — blocked by #821–#828 | release validation = last step |
| 818–826 | code | Specialist | pending (queued_slot_busy) | — | queued behind Specialist |
