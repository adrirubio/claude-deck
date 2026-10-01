# Pi Provider Rollout and Preserved-Team Migration

Issue #357. The implementation PR targets `feature/autonomous-github-dispatch`, not master. This document is a checkpointed operator procedure, not authorization to execute it. Do not resume the soak as part of installing this provider.

## P0 — Prepare and Inspect

Keep preset autonomy OFF, continuation at its existing value, and merge policy human. Verify the reviewed integration SHA before deployment. Back up the live database using SQLite's backup API; use private storage and do not copy it into an implementation worktree. Keep backend `.env` private (0600), never print/export the operator token, and do not inject that token into tmux or Pi.

Requirements: Linux `/proc`, tmux, Pi 0.87.1, Node >=22.19.0, and the deployed backend Python with `mcp`/`httpx`. Install only the repository-local package dependencies:

```sh
cd integrations/pi-agent-mail
npm ci --omit=dev --ignore-scripts
```

Development validation uses full `npm ci`, `npm run typecheck`, `npm test`, and the backend interpreter to run `scripts/generate-pi-mail-manifest.py --check`. The extension is passed explicitly on Deck launches. Do not install it globally or alter Pi's settings, hooks, modes or credential files.

Pi uses its existing OpenRouter authentication. A credential-readiness command, run privately in the intended Pi environment, is:

```sh
pi auth check --provider openrouter --model moonshotai/kimi-k3 --no-refresh
```

Never use credential-printing commands or copy credentials into launch options. Read `/api/v1/agent-mail/install/status` via the actual deployed install-status route and confirm `pi_mail_ready=true`; verify that route in the API schema if deployment routing differs. The backend's readiness probe loads the extension without opt-in, without starting a Pi session or contacting a model/backend. A CLI-installed badge alone is insufficient.

Privately snapshot the preset/slot/member IDs and creation identities, owner slot, workspace ID/path/acquisition/token, item ID/nonce/branch/base/head/PR, revision/failed-head history, pending approvals/holds, budgets and policy. Logs must omit token values/hashes and canonical commands. Record only equality results for sensitive values. Record the previous deployed SHA and slot configuration for rollback.

**STOP:** report preparation/readiness and preserved identity before proceeding.

## P1 — Disposable Client Validation

Use a disposable repository, fixture database/backend and isolated tmux socket. Validate explicit opt-in, server-derived identity, heartbeat, bound wakes, semantic 403/409 results, private close and rapid reload/new/resume. Verify unrelated manually launched Pi panes receive no tools/prompts and cannot be adopted through name/repository matching. Validate shell-backed panes as well as direct Pi panes. Do not run Tizonia builds or write GitHub.

Without `CLAUDE_DECK_MAIL_OPT_IN=1`, the extension registers no tools/listeners or transport. Deck launches supply non-secret opt-in, Python/shim paths and Team metadata. The MCP child receives a bounded runtime environment, not Pi's OpenRouter key or Deck/GitHub credentials. Backend Team binding may commit after Pi starts: registration-only `bind_pending` retry is bounded and authority remains unavailable until authentication succeeds.

Deck pins `--session-dir` to the resolved Pi session directory: `PI_CODING_AGENT_SESSION_DIR`, otherwise merged global/project `sessionDir` settings, otherwise Pi's project-encoded default. Exact resume reads only a bounded session header and refuses a foreign project, even in shared storage. Settings and session contents are never printed.

A separately approved, minimal paid Kimi tool-call probe may follow. Its success does not authorize live replacement or prove the whole soak passed.

**STOP:** report fixture results and request explicit live replacement authorization.

## Lifecycle and Uncertain Outcomes

Normal shutdown stops tools and heartbeat, privately requests `__deck_mail_close_generation`, waits for a backend-committed close ACK, then closes its owned stdio child. This private tool is never model-visible. Closure is terminal; even grace-mode registration cannot reopen the session key. Closed capabilities authenticate only their own idempotent close replay.

An unresolved close leaves a private pane-PID/start-time fence in `$XDG_RUNTIME_DIR/claude-deck-pi/`, or `/tmp/claude-deck-pi-<uid>/claude-deck-pi/`. A new Pi child in the same surviving shell pane cannot bypass it. No secret is stored there. Do not delete a fence to get around an unresolved close. This deliberately favors safety over automatic recovery.

Recovery requires authorization to stop the exact bound pane/process tree (not merely its Pi child), verified pane death/replacement, and operator retirement of only that PID/start-time identity:

```text
POST /api/v1/agent-mail/sessions/retire-dead-pane
X-Deck-Operator-Token: supplied privately by the operator client
{"pane_pid": <snapshotted-positive-PID>, "pane_proc_start": "<snapshotted-start-time>"}
```

The endpoint refuses live or unobservable panes. The durable pane lifecycle gate prevents a delayed old registration from appearing after retirement. Never target another session or reuse a numeric PID without its original start time. Confirm retirement, then explicitly remove only that exact stale local fence. A fresh pane identity can start afterward. Ordinary offline status and local child exit are not terminal closure.

Already-running old shims do not gain cleanup code when the backend is deployed. Coordinate their pause, stop only the authorized exact panes, verify death, and use the retirement endpoint; never extract old capabilities.

Tool cancellation or transport loss does not undo a committed backend mutation. `mutation_outcome_unknown` requires read-only reconciliation or operator handling, not blind repeat. Even `deck_get_work_item_context` and inbox checks have side effects. Do not ask an unrelated agent to perform the uncertain operation on the owner's behalf.

## P2 — Replace the Two Live Team Slots

Autonomy stays OFF. Obtain permission to replace each exact old pane after coordinating a pause and checking work state. Slowness is not permission to kill an owner. Stop/verify/retire old registrations as above before provider edits.

Update existing slots through the slot-update API, preserving IDs, charters, labels and creation identity. For the current Tizonia team, the intended IDs are Leader 4 and Specialist 6, preset 2; verify these from current read-only state rather than treating this historical example as fresh evidence.

```text
PATCH /api/v1/agent-teams/slots/4
PATCH /api/v1/agent-teams/slots/6
{"provider":"pi-cli","launch_mode":"plain","launch_options":{"platform":"openrouter","model":"moonshotai/kimi-k3","reasoning_effort":"high"}}
```

Provider edits detach old session rows to repo membership; the durable slot-member identity must remain unchanged. Verify old tokens are retired without retrieving/printing them. Do not create a new team or reassign/handoff the work item.

Plan and launch each slot separately. `repo_path_override` applies to the whole request: never give the Leader the owner's leased worktree. Resolve both paths from the verified snapshot, review each fresh plan and use its exact returned `plan_hash`:

```text
POST /api/v1/agent-teams/presets/2/plan-launch
{"slot_ids":[4],"reuse_existing":false,"repo_path_override":"<verified-Leader-normal-checkout>"}

POST /api/v1/agent-teams/presets/2/launch
{"slot_ids":[4],"reuse_existing":false,"repo_path_override":"<same-Leader-path>","confirm_plan_hash":"<Leader-plan-hash>"}

POST /api/v1/agent-teams/presets/2/plan-launch
{"slot_ids":[6],"reuse_existing":false,"repo_path_override":"<verified-preserved-leased-worktree>"}

POST /api/v1/agent-teams/presets/2/launch
{"slot_ids":[6],"reuse_existing":false,"repo_path_override":"<same-owner-path>","confirm_plan_hash":"<owner-plan-hash>"}
```

Replace placeholders from read-only state before operator confirmation; do not run these examples verbatim. No `retry`, redispatch, release/reacquire or workspace reset is allowed as a launch shortcut. Keep the unrelated Pi investigation pane untouched.

**STOP:** report IDs, paths, exact one physical pane/fresh bound registration per slot, and equality of all preserved attempt/lease fields.

## P2a — Owner Re-entry (A Separate Write)

Only the new authenticated Specialist calls `deck_get_work_item_context` for the preserved item. This is an owner claim-continuation write, not read-only preflight or automatic extension startup. Verify only leased-owner PID/start-time, last-contact and updated-at evidence changed. Acquisition/token, owner identity, nonce/refs/head/PR, revision/history/budgets and holds must remain equal. Do not copy an old token or have the coordinator claim context.

**STOP:** report field-equality results and the permitted liveness changes; stop on any other change.

## P3 — Read-only Re-entry Gate

Verify exactly one live observed pane and a fresh authenticated bound MCP registration/wake target per slot, distinct owner/Leader members, the recovery-only selector matching the preserved identity, stable lease/attempt fields, no pending proposal, human merge and autonomy OFF. Continuation is already ON in this preserved attempt: do not toggle it to satisfy a fresh-rollout script's continuation-OFF assumption. Use equivalent read-only re-entry checks and report the complete identity matrix.

**STOP:** obtain the existing soak checkpoint confirmation before any proposal, hold release or autonomy change.

## P4 — Resume Existing Soak Protocol

Follow `attempt-recovery-soak-runbook.md`; stop at every existing checkpoint. The owner independently proposes an implementation continuation for Tizonia fix commit `1e384079799775189565fb888bb13e89664738bf`, limited to `libtizonia/src/tizscheduler.c` and `libtizonia/test_component/tiztcproc.c`. Reverify commit content and current preserved state before proposing.

Historical preparation recorded ten persisted revisions, revision cap 11 and six failed heads of eight; re-read current counts. Do not silently raise caps. Distinct Leader review/decision and separate operator decision/ack hold releases remain mandatory. No coordinator cherry-pick, synthetic approval/status report or local Tizonia build. Hosted product CI must pass before human merge of PR #875. Provider migration alone is not a soak pass.

## Rollback

Keep autonomy OFF. Under explicit authorization, stop only the new Pi panes, terminally close/retire their registrations, restore old slot/deployment configuration and launch fresh authenticated old-provider sessions through Deck. Never reuse capabilities, reset/release the preserved workspace, change budgets/history or claim rollback authorizes another proposal. If a live revision/pending approval exists, stop for its separate disposition. Preserve the unrelated investigation session.
