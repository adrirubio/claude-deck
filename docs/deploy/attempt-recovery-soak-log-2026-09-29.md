# Tizonia Attempt-Recovery Soak: Final Replay and Cleanup

Status: **evidence draft; independent review FAIL; not master-merge clearance**.
PR #360's GitHub review request was waived at the user's direction after Adri
approved it off-platform; no GitHub review was submitted. The 2026-09-30
independent evidence review found the exceptions and gaps documented below.
Fixes for issues #329 and #359 subsequently merged to the integration branch,
but were not deployed during this soak. Issue #379 tracks a newly identified
failed-head accounting gap. Times below are UTC. This
records the final revision and terminal cleanup from live Deck DB/API, Agent Mail,
GitHub, and the leased checkout. Earlier checkpoints are summarized from durable
authority rows and private operator artifacts where possible. The private
`attempt-recovery-deploy-20260829T205204Z.log` and
`attempt-recovery-soak-20260829T205204Z.md` record the pre-deployment backup
reference/digest and early checkpoint evidence; do not copy the database or its
private backup details into the repository. A private conversation-derived cap
ledger dated 2026-09-30 identifies authorizations, one contextual approval,
and one agent-construed change;
it is not a persisted policy audit trail.

## Identity and safety boundary

| Field | Observed |
|---|---|
| Deck deployment | `d4d7f5dcc08031f4404c071273a04b4ace3cc71c`, integration branch `feature/autonomous-github-dispatch`, not `master` |
| Deck preset / scope | `tizonia-v1` id 2 / `tizonia/tizonia-openmax-il` id 1 |
| Work item / public issue / PR | 23 / #821 / #875 |
| Owner / distinct approver | Specialist member 17, slot 6 / Leader member 16, slot 4 |
| Scope merge policy | `human`; `auto_merged_at` remained NULL |
| Leased workspace | id 2; released during cleanup |
| Final PR head / merge commit | `b6880f541a0b3f0d3e651e2a9592391b5dc4af58` / `d509ad8ea043c787c890dd54626d9c65b955e82c` |

No lease token, capability token, credential, or token hash is recorded here.
Issue #329 remains open. The private early-soak log records a dedicated
`deck-soak` tmux socket, but also a **2026-09-04 cross-project mail delivery**;
the unrelated session was then shut down as mitigation. Final-replay durable
rows show one wake target per soak member and no cross-project mail or wake in
the observed window. They do not establish which tmux socket held the later
sessions. The #329 code fix merged after this soak and was not exercised by it.

## Checkpoint evidence

| Gate | Durable outcome | Evidence / qualification |
|---|---|---|
| 0 — deployment | Backend healthy at integration tip, no integration-to-`master` merge | The original preflight and backup are in private artifacts. A timestamped operator conversation reports deploying `d4d7f5dc` on 2026-09-26 at 19:34 and an owner re-entry/read-only preflight PASS at 19:59. The `pi-cli` provider first entered the integration branch at `d4d7f5dc`; Tizonia slots 4 and 6 registered `pi-cli` sessions at 19:54–19:55, with launch rows 87/88 and a mass retirement of stale sessions/panes at 19:54:22. These rows anchor code identity but not the exact restart moment, preflight content, pre-deploy backup, or uninterrupted process continuity; the current backend is a later restart. |
| 1 — team and scope | Distinct owner and Leader slots/members; one observed pane and one fresh authenticated MCP session for each at final proposal | Private log records Checkpoint 1 PASS on 2026-08-30 with isolated panes. An operator reported repeating DB and tmux checks on 2026-09-28; durable MCP-session and one-pane-per-member wake rows support the final-window identity and wake outcome, not the tmux command or socket claim. |
| 2 — continuation policy | Finite policy, autonomy off at proposal | Private log records initial 6/8/2 cap and Checkpoint 2 PASS on 2026-08-30. Final proposal used 15/11/2. A private, timestamped conversation ledger reconstructs the intermediate changes. The 6→7 approval was contextual; for 7→8, the agent construed a general “yes” given before the numeric question as approval and raised the cap without a further reply. The operator accepted these retrospectively on 2026-09-30; neither was a value-specific contemporaneous approval. Failed-head cap raises and blanket approval also departed from Checkpoint 1.6's finite-cap discipline. The early autonomy-on windows preceded the recovery-only gate. |
| 3 — owner proposal | Revision 15 proposed by member 17 at `decision_hold` | Created 2026-09-28 22:48:23; approval request 15, request mail 1118. Scope: implementation, one allowed path `player/src/decoders/tizflacgraph.cpp`, hosted CI, two failed heads. No coordinator proposal. |
| 4 — decision and ack | Distinct Leader approved; owner acknowledged | Decision mail 1121 at 22:57:53; server delivery mail 1122 at 22:57:53; member 17 acknowledged at 22:58:55. Decision and ack holds were separately released by the operator. |
| 5 — diagnostics and restoration | Earlier diagnostic revisions 3, 6, 8, 9, 12, 13 completed; all diagnostic revisions now terminal | Independent review matched every diagnostic revert commit tree to its persisted baseline tree. Run 33221787425 is a pre-recovery red head reused by revision 3, not a revision-3 run. Revision 6 used run 35969694440; revision 8, 36041701517; revision 9, 36049559994; revision 12, 36352060714; revision 13, 36480800340. No diagnostic authority remains active. |
| 6 — implementation and product CI | Revision 15 completed; item became `ready_for_review` | One-file commit `b6880f54` on preserved PR branch; submitted at 23:39:58, completed at 23:41:49. Hosted run 36498366182: Core Meson build and full Playback smoke both SUCCESS on that head. GitHub attributes the draft→ready flip at 23:41:48 to the human account whose credential Deck used for its GraphQL write; that attribution does not make the action an independent human review. Revision failed-head count 0; product and diagnostic retry counts remained 6 each. **Exception:** revision 14 pushed red head `06c00c42` (run 36490136422), then was cancelled with zero failed heads before Deck counted it. Revision 15 used that head as its baseline. Issue #379 tracks the budget bypass. |
| 7 — human merge and cleanup | PR and item merged; autonomy, continuation and gate disabled; lease cleared | Human squash merge at 2026-09-29 08:46:06; Deck item `merged` at 08:46:47. The owner's normal release returned 409; operator force-release cleared the lease, so runbook step 8 **failed**, not passed. Cleanup details below. Independent evidence clearance remains pending. |

The independent reviewer compared these diagnostic revert commit trees with the
baseline tree persisted for each revision; the full identifiers are in the
GitHub PR and durable revision rows:

| Revision | Diagnostic head | Restoration head | Hosted run | Baseline tree prefix restored |
|---|---|---|---|---|
| 3 | No new mutation; reused pre-existing red head `c1c7ef1a` | Not applicable | 33221787425, before revision 3 | No diagnostic tree to restore |
| 6 | `93184083` | `dc52a085` | 35969694440 | `477ec137` |
| 8 | `6354e3f3` | `9310b69a` | 36041701517 | `5b084e1f` |
| 9 | `3951cfbc` | `b2e9c0ba` | 36049559994 | `5b084e1f` |
| 12 | `d81b5b8c` | `9963255a` | 36352060714 | `5a9cc1e6` |
| 13 | `c07eae0f` | `3dab62aa` | 36480800340 | `5a9cc1e6` |

The cap-change trail was reconstructed from timestamped operator conversation,
not a persisted policy-change log. These are report times, not asserted API
write times:

| Change | Reported applied (UTC) | Authorization quality |
|---|---|---|
| Revisions 6→7 | 2026-09-24 05:48 | Contextual “good, continue” after a stated 6→7 recommendation; gate-owner disposition needed |
| Revisions 7→8 | 2026-09-24 09:28 | Agent construed a general “yes” preceding the numeric question as approval; no value-specific reply before the raise; Checkpoint 1.6 deviation |
| Revisions 8→9 | 2026-09-24 18:56 | Explicit yes to the bounded 8→9 sequence |
| Revisions 9→10 | 2026-09-26 11:19 | Explicit yes and operator-reported guarded-script verification |
| Revisions 10→11 | 2026-09-26 15:32 | Explicit confirmation of 10→11 |
| Revisions 11→13; failed heads 8→9 | 2026-09-26 21:09 | Explicit approval of both limits; failed-head raise departed from Checkpoint 1.6's keep-at-8 instruction |
| Revisions 13→14; failed heads 9→11 | 2026-09-28 08:47 | Prospective blanket approval after the exact 14/11 proposal; failed-head raise departed from Checkpoint 1.6 |
| Revisions 14→15 | 2026-09-28 22:27 | Prospective blanket approval only; departed from Checkpoint 1.6's separate-decision instruction |

On 2026-09-30 the operator retrospectively accepted the cap increases, including
contextual 6→7, agent-construed 7→8, and blanket coverage of 14→15. This does
not create contemporaneous value-specific approvals or erase the runbook
deviations.

Revisions 1–15 are all terminal. The private early-soak log records Checkpoint 3
and 4 blockers/retries and the first diagnostic-restoration PASS; it does not
cover every later revision. Its deployment log also records an **unsanctioned
local Tizonia build attempt on 2026-08-29 before Checkpoint 0 PASS**, with all build processes
stopped and no source edits. Do not describe the entire soak as having had no
local build. The final implementation path was reviewed
before push: Leader's corrected actual-diff PASS followed the coordinator's
`nSampleRate` → `nSamplingRate` compile-blocker correction. Leader's full PR
net-diff review reported no blocker across 16 files. The public PR contains
historical diagnostic/revert pairs, but no diagnostic instrumentation survives
in its net diff. The exact baseline-tree comparisons, not the final net diff
alone, support the restoration claim.

The pre-gate broad watcher polled scope 1 on 2026-09-05 at 18:28:02–03 and
rewrote metadata timestamps on historical items 15–22 and 26. It did not change
their dispatch statuses or dispatch work, but the hard rule against touching
item 26 was violated. The operator accepted this and revision 14's uncounted
red head as historical exceptions on 2026-09-30. Neither is counted as a passed
invariant; issue #379 remains a master blocker.

## Merge and terminal cleanup

1. GitHub records PR #875 `MERGED` into `master` at 08:46:06 and issue #821
   `CLOSED` at 08:46:07. Deck's work item reached `merged` at 08:46:47;
   `auto_merged_at` is NULL. The user reported temporarily disabling repository
   rules to perform the human merge. A post-merge GitHub read confirmed master
   protection again requires one approving review and enforces administrators.
   An admin read of the branch-protection API on 2026-09-30 at 14:17 returned
   `required_approving_review_count=1` and `enforce_admins=true` (no required
   status-check contexts); this confirms the present configuration, not the
   length or exact settings of the bypass window.
   The bypass window and `reviewDecision=REVIEW_REQUIRED` must be visible to the
   independent reviewer; do not describe the merge as a protected approval.
2. Preset 2 autonomy was reported disabled at 08:50:16. The exact-attempt
   scheduler job was reported unscheduled. No broad Tizonia dispatch was enabled
   during cleanup.
3. The owner's normal `workspace_released` report returned HTTP 409 because
   `release_blocker` counted 23 branch commits not ancestral to `origin/master`
   after the squash merge. The checkout was clean and the branch head remained
   pushed remotely. All 16 PR file blob SHAs match the merged master tree; two
   files were already identical on master before the squash commit. The operator
   then used the acquisition-bound force-release route with a reason supplied
   to the route; no durable record of that reason survives.
   Workspace 2 released at 08:59:47; the lease token and item pointer are NULL.
   This was a runbook-step failure, even though the operator cleanup was safe.
   Follow-up: [Deck issue #359](https://github.com/adrirubio/claude-deck/issues/359).
4. The recovery-only selector was removed from the ignored, mode-0600
   `backend/.env` at 09:00:13; an operator-facing report at 09:00:49 said Deck
   restarted and `/health` passed. The operator-only recovery-gate endpoint
   returned `active=false` in a later check.
5. Scope 1 continuation was reported disabled by 09:09 with numerical limits
   preserved for audit (15 revisions, 11 total failed heads, 2 per revision).
   The surviving access log places a continuation-policy PATCH after a 16:00
   backend restart. At least one policy write therefore occurred after that
   restart and is unexplained by the cleanup narrative; the exact first write
   time is unproven. At the cleanup
   audit, preset autonomy was false and no scope-1 lease, pending approval,
   nonterminal revision, open approval request root, or missing
   approved-request/delivery linkage remained.

The branch's local checkout was not reset, rebased, built, or deleted. Its clean
head is still `b6880f54`, matching the remote PR branch. No local Tizonia build
was run during the final revision or cleanup, and no auto-merge was attempted.
These are cleanup-time observations, not a claim about the current live team:
the Tizonia roster was edited and sessions were relaunched around 21:36 on
2026-09-29.

## Review gates before integration-to-master

- Independent review on 2026-09-30 verified the original backup digest and
  diagnostic baseline-tree restoration. It found an uncounted red head,
  a pre-gate broad watcher metadata write, and the normal-release failure.
  The gate owner retrospectively accepted the two historical deviations on
  2026-09-30. They remain failed checks. Issue #379 holds the product-level
  budget-bypass fix required before master.
- The private cap ledger reconstructs the changes from timestamped operator
  conversation, but 6→7 is contextual and 7→8 lacks an unambiguous
  value-specific approval. The gate owner retrospectively accepted the cap
  increases on 2026-09-30; do not invent a contemporaneous approval.
- The `d4d7f5dc` deployment has a timestamped conversation report and read-only
  preflight report, but no surviving process log proving uninterrupted service
  through the final replay. The later `deck-soak` socket claim is also not
  independently established. An independent reviewer must decide whether the
  remaining evidence suffices or requires a targeted check.
- Current `master` protection was confirmed by an admin API read, but the
  temporary review-rule bypass on PR #875 remains a documented exception.
  The merge was not a protected or independently approved merge.
- The #329 and #359 fixes were reviewed and merged to integration after the
  soak; neither ran in the observed replay. A targeted isolated normal-release
  replay against the #359 fix passed through the owner report route
  (`test_owner_release_after_real_squash_merge_uses_normal_route`, 2026-09-30).
  This is code-path validation, **not** a live Tizonia terminal-release observation.
  Do not claim the historical runbook step passed.
- Have the independent reviewer re-assess the amended evidence before a
  `master` PR. PR #360 recorded a draft only; green product CI and current
  protection settings do not themselves clear the soak gate.
