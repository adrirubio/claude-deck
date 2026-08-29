# PR4 — Agent Bridge Visibility and Soak Replay Implementation Plan

> **For implementation agents:** Start only after PR3 is reviewed and merged into
> `feature/autonomous-github-dispatch`. Complete UI/backend validation before touching live
> soak state. The live replay uses explicit checkpoints.

**Goal:** Make attempt continuation discoverable and operable in Agent Bridge, expose scope
policy safely, preserve actionable backend conflict details in agent tools, and replay the
preserved Tizonia attempt end to end without coordinator impersonation.

**Architecture:** Backend responses preload normalized approval/revision state and compute
Retry eligibility from the same predicate used by the retry route. Agent Bridge renders
phase, revision, budgets, approval/delivery/ack state, exact scope, and block reasons. The
operator may configure finite continuation policy or cancel a pending request, but cannot
approve as Leader. A read-only preflight script plus checkpointed runbook gates the live
Tizonia replay after PR4 is merged to the integration branch.

**Spec:** `docs/superpowers/specs/2026-08-29-autonomous-attempt-recovery-design.md`,
Revision 7, especially §§8.3, 9.3, 10, 13.5–13.7, 14 PR4, 15, and 16.

**Dependency:** Merged PR3 diagnostic recovery. Record its integration merge SHA.

**Target:** One PR into `feature/autonomous-github-dispatch`, never `master`.

## PR Boundary

- PR4 includes UI/types/API clients, final MCP conflict propagation, read-only preflight,
  deployment/replay documentation, and the replay log template.
- Code is reviewed and merged to the integration branch before live replay.
- The integration branch is not merged to `master` until the replay gate passes.
- Human merge remains required for Tizonia PR #875.

## Global Safety Constraints

- Use an isolated worktree based on the PR3 merge tip for code and tests.
- Do not use the live Deck database while implementing or testing UI.
- Do not enable Tizonia continuation/autonomy until the runbook's configuration checkpoint.
- Never retry or release work item 23 during replay.
- Never touch historical item 26/#818.
- Never run a Tizonia build locally; all compilation/diagnostics run in hosted CI under an
  approved scope revision.
- Do not commit, push, report, approve, or cancel on behalf of a live owner/Leader agent.
- Operator UI must not expose a Leader approval action.
- Never render or log lease tokens, capability tokens, GitHub tokens, operator tokens, or
  lease-token hashes.
- Stop at each replay checkpoint and obtain the user's confirmation before continuing.

## File Map

| File | Action | Responsibility |
|---|---|---|
| `backend/app/models/schemas.py` | Verify/modify | Final projection and eligibility fields |
| `backend/app/api/v1/agent_teams.py` | Modify | Bulk preload, Retry predicate, audit/cancel responses |
| `backend/mcp_shim/agent_mail_server.py` | Modify | Preserve structured 409 details |
| `frontend/src/types/agentTeams.ts` | Modify | Scope/work-item/approval/revision types |
| `frontend/src/features/agent-teams/api.ts` | Modify | Revision audit/cancel and policy clients |
| `frontend/src/features/agent-teams/operatorAuth.ts` | Create | Per-tab operator credential |
| `frontend/src/features/agent-teams/AutonomyPanel.tsx` | Modify | Policy controls and recovery visibility |
| `frontend/src/features/agent-teams/AgentTeamsPage.tsx` | Modify | Fetch/refresh/cancel integration |
| `backend/tests/agent_teams/test_github_workspace_api.py` | Modify | Projection/query/Retry/cancel behavior |
| `backend/tests/agent_mail/test_mcp_shim.py` | Modify | Conflict detail and redaction |
| `scripts/attempt-recovery-preflight.sh` | Create | Read-only live-state checks |
| `docs/deploy/attempt-recovery-rollout.md` | Create | PR1–PR4 deployment and rollback |
| `docs/deploy/attempt-recovery-soak-runbook.md` | Create | Checkpointed Tizonia replay |
| `docs/deploy/attempt-recovery-soak-log-template.md` | Create | Fill-as-you-go evidence artifact |

## Task Index

| Task | Deliverable |
|---|---|
| 1 | Final backend projections and Retry predicate |
| 2 | Frontend continuation types and API clients |
| 3 | Scope continuation policy controls |
| 4 | Work-item continuation list visibility |
| 5 | Recovery detail dialog and cancellation |
| 6 | MCP conflict detail propagation |
| 7 | UI/accessibility/build validation |
| 8 | Read-only deployment preflight tooling |
| 9 | Rollout and replay runbooks |
| 10 | PR validation and integration merge gate |
| 11 | Post-merge checkpointed Tizonia replay |

---

## Task 1 — Finalize Backend Projections and Retry Eligibility

**Files:** `backend/app/models/schemas.py`,
`backend/app/api/v1/agent_teams.py`,
`backend/tests/agent_teams/test_github_workspace_api.py`

- [ ] Extract one pure/service Retry eligibility predicate returning
  `(allowed, block_code, message)`.
- [ ] Make the retry endpoint and work-item response use that same result.
- [ ] Match the current endpoint plus the new continuation guards: require escalated status;
  refuse a preserved PR, active revision, or pending approval. Do not invent a separate
  human-stop-reason block. An otherwise eligible PR-less item with a held workspace remains
  allowed and enters the existing deferred-retry path.
- [ ] Project:
  - attempt phase/revision/summary/status;
  - pending approval id/kind/status;
  - product/diagnostic/revision counters and budgets;
  - continuation block code;
  - retry allowed/block code;
  - delivery/ack timestamps safe for UI.
- [ ] Bulk preload active revision and pending approval with joins/subqueries for list
  endpoints. Assert bounded query count as item count grows.
- [ ] Reload normalized rows for mutation responses; never async-lazy-load in the sync helper.
- [ ] Omit commands/tool fallbacks from list summaries; expose exact scope only from the
  dedicated revision audit endpoint to authorized team/operator callers.

**Mutation checks:** UI predicate differs from route; N+1 query; return lease hash; Retry true
with PR; stale pending row projected as current.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_workspace_api.py -q -p no:warnings
```

**Commit:** `feat: expose attempt recovery projections`

---

## Task 2 — Add Frontend Types and API Clients

**Files:** `frontend/src/types/agentTeams.ts`,
`frontend/src/features/agent-teams/api.ts`,
`frontend/src/features/agent-teams/operatorAuth.ts`

- [ ] Add all six scope-policy fields to scope response and dedicated policy-update
  interfaces; generic scope input/update cannot write them.
- [ ] Add work-item continuation, diagnostic, approval, budget, block, and Retry fields.
- [ ] Add typed approval-request/scope-revision list responses and lifecycle unions.
- [ ] Create a per-tab operator credential helper backed only by `sessionStorage`, with
  explicit get/set/clear operations and no logging or response persistence.
- [ ] Add API clients for revision audit history and cancellation. The backend retains its
  requester-or-operator contract; Agent Bridge uses only the operator branch. Protected
  browser calls accept an explicit operator token and send only
  `X-Deck-Operator-Token`; the API module does not read browser storage itself.
- [ ] Add the operator-only continuation-policy client with
  the same explicit operator-token argument.
- [ ] Keep Leader decision absent from browser/operator clients.
- [ ] Preserve backend detail codes/messages in thrown API errors where the current client
  supports them.
- [ ] Compile before component changes to catch contract drift early.

**Verify:**

```bash
cd frontend
npm run build
```

**Commit:** `feat: type attempt recovery api responses`

---

## Task 3 — Add Scope Continuation Policy Controls

**Files:** `frontend/src/features/agent-teams/AutonomyPanel.tsx`,
`frontend/src/features/agent-teams/operatorAuth.ts`, `frontend/src/types/agentTeams.ts`

- [ ] Add a continuation-policy editor separate from generic scope editing and autonomy.
- [ ] Prompt for the operator token on first protected action; store it only in per-tab
  `sessionStorage` through the Task 2 helper, provide an explicit clear action, and never
  echo it.
- [ ] Add numeric controls for revision cap, total failed-head cap, per-revision cap, path
  cap, and command cap.
- [ ] Populate the dedicated policy editor from backend values and submit all six policy
  fields atomically; generic scope create/edit forms remain unable to write them.
- [ ] Explain that continuation requires both preset autonomy and scope continuation, and
  that finite caps stop recovery.
- [ ] New scopes remain continuation off through backend defaults; the generic create form
  has no enable field.
- [ ] Warn before enabling continuation when autonomy is already on; do not silently enable
  autonomy.
- [ ] Validate min/max relationships client-side while treating backend validation as final.
- [ ] Keep controls keyboard accessible and labels/errors associated.

**Manual mutation checks:** put policy fields on generic scope update; store token in
localStorage; echo token; enable by default; couple policy and autonomy; allow per-revision
cap above total.

**Verify:**

```bash
cd frontend
npm run build
```

**Commit:** `feat: configure bounded attempt recovery`

---

## Task 4 — Show Continuation State in the Work-Item List

**Files:** `frontend/src/features/agent-teams/AutonomyPanel.tsx`

- [ ] Add phase badge, active revision, pending approval indicator, product retry count,
  diagnostic failed-head count, and revision budget.
- [ ] Show preserved PR link/number and owner/workspace preservation status.
- [ ] For escalated PR-bearing items, show `Continue attempt` state and block reason.
- [ ] Render Retry only when `retry_allowed` is true; do not reimplement backend eligibility.
- [ ] When Retry is blocked by preserved PR, show explicit text rather than a disabled button
  with no reason.
- [ ] Preserve compact layout and light/dark theme contrast.
- [ ] Ensure status is conveyed in text, not color alone.

**Manual mutation checks:** render Retry from status only; hide reason; color-only phase;
truncate PR link or revision budget.

**Verify:**

```bash
cd frontend
npm run build
```

**Commit:** `feat: show attempt recovery status`

---

## Task 5 — Add Recovery Detail and Safe Cancellation

**Files:** `frontend/src/features/agent-teams/AutonomyPanel.tsx`,
`frontend/src/features/agent-teams/AgentTeamsPage.tsx`,
`frontend/src/features/agent-teams/api.ts`

- [ ] Fetch revision history when the work-item dialog opens; show loading/error/empty states.
- [ ] Require the per-tab operator credential before the browser fetches protected exact
  revision detail, and pass it explicitly to the API client.
- [ ] Add an Attempt recovery section containing:
  - originating escalation;
  - preserved PR/owner/workspace/branch;
  - active/pending revision and exact paths/actions/commands;
  - requester/Leader/decision/timestamps;
  - delivery/ack state;
  - diagnostic evidence links;
  - automatic continuation block reason.
- [ ] Render external evidence URLs safely with `rel="noreferrer"` and no raw HTML.
- [ ] Show Cancel only for a pending request and only through the operator-capable endpoint;
  pass the same explicit per-tab operator credential.
- [ ] Require confirmation naming the request/revision; refresh list/detail after success.
- [ ] Do not add approve/reject controls or sender/member impersonation.
- [ ] Display backend 409 detail on stale cancellation instead of generic failure.

**Manual mutation checks:** operator approval button; cancel active revision; stale cached
state after cancel; unsafe evidence URL; render secret fields.

**Verify:**

```bash
cd frontend
npm run build
```

**Commit:** `feat: add attempt recovery details`

---

## Task 6 — Preserve MCP Conflict Details

**Files:** `backend/mcp_shim/agent_mail_server.py`,
`backend/tests/agent_mail/test_mcp_shim.py`

- [ ] Audit `_request`, `_dispatch_request`, and continuation tool wrappers.
- [ ] Preserve backend 409 `detail` code/text in `error.code`/`error.message` for pending,
  stale owner/nonce/revision/workspace, tree-not-restored, and diff-inconclusive conflicts.
- [ ] Handle string and structured FastAPI detail safely.
- [ ] Keep authorization headers, capability tokens, lease tokens, and response headers out
  of returned/logged errors.
- [ ] Keep non-continuation error behavior stable.

**Mutation checks:** genericize 409; stringify full response/headers; lose structured code;
echo request JSON containing lease token.

**Verify:**

```bash
cd backend
venv/bin/pytest tests/agent_mail/test_mcp_shim.py -q -p no:warnings
```

**Commit:** `fix: preserve attempt recovery conflict details`

---

## Task 7 — Validate UI, Accessibility, and Theme Behavior

**Files:** frontend files only if a defect is found.

- [ ] Run TypeScript/Vite build.
- [ ] Run ESLint and separate pre-existing findings from changed-file findings.
- [ ] Exercise keyboard navigation for scope controls, work-item rows, dialog, links, and
  cancellation confirmation.
- [ ] Check screen-reader labels and focus return after dialog/cancel.
- [ ] Check narrow width plus Deck light and dark themes.
- [ ] Verify long paths/commands/reasons wrap without hiding controls.
- [ ] Verify no browser console error during list/detail refresh.
- [ ] Do not introduce a new frontend test framework solely for this PR.

**Verify:**

```bash
cd frontend
npm run build
npm run lint
```

If lint has existing unrelated failures, record them and require zero new failures in changed
files.

**Commit (only if fixes were needed):** `fix: polish attempt recovery interface`

---

## Task 8 — Add Read-Only Preflight Tooling

**Files:** `scripts/attempt-recovery-preflight.sh`

- [ ] Create a strict-mode (`set -euo pipefail`) read-only script requiring explicit Deck
  base URL, preset id, scope id, and work item id.
- [ ] Query API state and print only:
  - Deck health/version;
  - autonomy/continuation booleans;
  - configured finite caps;
  - work-item status/phase/revision/PR/owner/workspace presence;
  - pending approval summary/block codes;
  - connected-session counts per required slot.
- [ ] Fail if autonomy or continuation is unexpectedly enabled during preflight, item/PR
  identity differs, lease/workspace is absent, duplicate live slot sessions exist, or
  required owner/Leader session is missing.
- [ ] Never print environment values, request headers, tokens, workspace lease token/hash,
  message bodies, commands, or DB paths.
- [ ] Make the script incapable of PATCH/POST/DELETE. Live mutations remain explicit runbook
  steps after checkpoint approval.
- [ ] Do not inspect or classify `*.db-wal`/`*.db-shm` files. Their presence is normal for an
  active SQLite WAL database and cannot prove a stale lock or hung process; preflight stays
  on supported read-only health/state APIs.
- [ ] Add shell syntax/static checks available in the repo environment.

**Mutation checks:** allow POST; dump curl verbose headers; accept duplicate sessions; ignore
wrong PR; pass while autonomy on.

**Verify:**

```bash
bash -n scripts/attempt-recovery-preflight.sh
```

**Commit:** `feat: add attempt recovery preflight`

---

## Task 9 — Write Rollout, Replay, and Evidence Artifacts

**Files:** `docs/deploy/attempt-recovery-rollout.md`,
`docs/deploy/attempt-recovery-soak-runbook.md`,
`docs/deploy/attempt-recovery-soak-log-template.md`

- [ ] Rollout guide covers DB backup, PR1→PR4 order, backend and pane/MCP restarts, migration
  checks, continuation default-off, rollback, logs, and master-merge hold.
- [ ] Document post-merge cleanup of each clean, fully pushed phase worktree with
  `git worktree remove`; never use forced cleanup as part of rollout.
- [ ] Replay runbook uses the preserved identities:
  - preset `tizonia-v1` / preset id 2;
  - Deck work item 23;
  - Tizonia issue #821;
  - Tizonia PR #875;
  - Specialist owner and designated Leader;
  - human merge policy.
- [ ] Require fresh API/DB verification rather than trusting those ids blindly.
- [ ] Include checkpoints:
  0. deployed Deck healthy, autonomy/continuation off;
  1. exact team/scope/caps and one session per required slot;
  2. continuation enabled but autonomy still off;
  3. autonomy on and owner proposal received;
  4. autonomous Leader decision/delivery/ack;
  5. hosted diagnostic/fallback/revert/tree-restoration pass;
  6. implementation continuation and product CI green;
  7. ready-for-review, human merge, item merged, cleanup.
- [ ] Hard rules: no local Tizonia build, no coordinator agent impersonation, no work-item
  retry/release, no writes beyond PR #875, no auto-merge, and stop on any unsanctioned write.
- [ ] Log template captures state transitions, revisions, mail ids, CI run ids, tree SHAs,
  counters, telemetry, approvals, checkpoint confirmations, and cleanup.

**Commit:** `docs: add attempt recovery soak runbook`

---

## Task 10 — Validate PR4 and Merge Only to Integration

- [ ] Run backend scoped/full tests and frontend checks:

  ```bash
  cd backend
  venv/bin/pytest tests/agent_mail tests/agent_teams \
    tests/test_sqlite_compat_migrations.py -q -p no:warnings
  venv/bin/pytest tests -q -p no:warnings
  cd ../frontend
  npm run build
  npm run lint
  cd ..
  bash -n scripts/attempt-recovery-preflight.sh
  git diff --check
  git status --short
  ```

- [ ] Record measured test counts and unrelated failures.
- [ ] Confirm no live API/DB/Tizonia mutation occurred during implementation.
- [ ] Open one PR targeting `feature/autonomous-github-dispatch`; obtain code review and fix
  findings.
- [ ] Merge PR4 only to the integration branch.
- [ ] Do not merge the integration branch to `master`.

## Task 11 — Execute the Post-Merge Tizonia Replay

This task is operational and begins only after PR4 is merged to the integration branch and
the user explicitly authorizes deployment.

- [ ] Deploy the integration branch using the rollout guide.
- [ ] Run the read-only preflight and stop at Checkpoint 0.
- [ ] Follow every runbook checkpoint; do not batch confirmations.
- [ ] Enable continuation with reviewed finite caps before enabling autonomy.
- [ ] Observe agents perform proposal, Leader decision, delivery, ack, diagnostic, hosted
  tool fallback, revert, restoration proof, implementation correction, and product
  verification.
- [ ] Do not perform any owner/Leader action on their behalf.
- [ ] A human merges PR #875 only after Deck marks it ready under human policy.
- [ ] Disable autonomy after the replay; retain or disable continuation according to the
  final checkpoint decision.
- [ ] Fill and commit the soak log artifact to the integration branch.
- [ ] Only after an independent reviewer clears the log may the integration branch be
  proposed for merge to `master`.

## PR4 Exit Gate

Code exit:

- UI and MCP expose the same safe continuation state as REST;
- Retry visibility comes from one backend predicate;
- operator can configure/cancel but never approve;
- frontend passes build with no new changed-file lint errors;
- preflight is provably read-only;
- PR4 is merged only to the integration branch.

Program exit:

- Tizonia replay completes without coordinator commits, approvals, reports, DB repair, or
  token relay;
- diagnostic changes are reverted and tree identity is proven;
- product CI is green;
- PR #875 is human-merged;
- work item 23 reaches merged;
- the evidence log is independently approved before any master merge.
