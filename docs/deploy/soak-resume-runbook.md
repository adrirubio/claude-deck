# Soak resume runbook — deployment and verification schedule

**Status: G0, G1, and G2 passed on 2026-08-16; proceed with G3.**

**Audience:** the implementing agent taking over the deployment schedule.
**Written:** 2026-08-15, against `origin/master` at `96954a6`.

## What this document is

Six units of merged code are queued behind a deployment that has not happened, and
the schedule for deploying them existed only as fragments across six documents. This
document supplies the **ordering** between those fragments and the current state of
the live rig. It does not restate them.

Each gate below names its normative source. **Where this document and the source
disagree, the source wins** — with one exception, recorded because it already bit: line
number citations in the older specs have drifted. G2 §7 cites `init_db` at
`database.py:458`; on `origin/master` it is `:521`, calling
`_run_sqlite_compat_migrations` (`:290`) at `:527`. Re-resolve every citation before
acting on it.

| Fragment | Owns |
|---|---|
| `specs/2026-07-06-tizonia-roadmap-v1-soak-runbook.md` | Windows 1/2, the finish line, the safety invariants. Its pre-flight predates G2 — read it last, not first |
| `specs/2026-07-29-dispatch-workspace-provisioning-design.md` §7 | PR A steps 0–5 and the ⛔ status block explaining why step 5 stopped |
| `specs/2026-08-02-phase-g2-session-lifecycle-design.md` §7, §9 | G2 re-arm order, the owed sixth step, carried-forward obligations |
| `deploy/pr0-capability-tokens-rollout.md` | the four-step credential rollout |
| `deploy/pr1-approval-gate-rollout.md` | the deploy ordering PR1's guarantees depend on |
| `deploy/pr2-github-app-rollout.md` | App permissions, scope-reset gate, staged rollout, rollback |
| `specs/2026-08-05-distinct-approver-identity-design.md` §5.9, §8 | scope reset detail, 34 acceptance criteria |
| `specs/2026-07-06-tizonia-roadmap-v1-soak-run-log.md` | **the evidence artifact.** Last entry 2026-08-16 |

## What we are verifying against — the tizonia testbed

Deck's autonomous dispatch loop is not verified against fixtures. It is verified by pointing
it at a **real, public, third-party repository** and watching what it does:

**Testbed:** `tizonia/tizonia-openmax-il` — a C/C++ multimedia player built with meson. It is
public, so **every write Deck makes there is public**. Branch protection on its `master`
stays enabled throughout (Gate 6 restores the part that was relaxed).

**Why a real external repo:** the subject under test is the *loop*, not the C++. From the
soak runbook's finish line — "loop reliability across every `roadmap:v1` issue Deck picks up,
NOT solving every issue. Easy issues merge; hard/blocked ones escalate cleanly and
recoverably. A capability failure (agent can't do a hard issue) is acceptable; a *loop*
failure (silent stranding, bad write, wrong-reason escalation, guard not firing) is not."
A fixture cannot fail that way. This testbed already produced 19 numbered findings, of which
the ones that mattered most — 10, 13, 17, 18, 19 — were all invisible to a green test suite.

**How Deck decides what to work on** (labels, which is also the only sanctioned way to steer
a scenario — rule 6):

| Label | Role |
|---|---|
| `roadmap:v1` | the scope of the soak |
| `agent-ready` | broad arming — Window 1/2 work |
| `agent-ready-e2e` | **isolation** — arm exactly one issue for a controlled single dispatch (G3/G4) |
| `agent-design` | design-tier: `awaiting_human_review`, no CI, never auto-merged |
| `area:*` | routes the item to a slot by matching the slot's `area_labels` |

**Testbed state, measured 2026-08-15:** 11 open `roadmap:v1` issues — **10 `agent-ready`**
(#821–#829, #834) and **1 `agent-design`** (#858, the yt-dlp design note). `agent-ready-e2e`:
**0**. #816–#820 were worked and closed during the soak. Meaning: `agent-ready` is loaded and
would fire ten dispatches the moment autonomy came on against that label — hence rule 1.

**Local checkouts** (the worktree pool PR A provisions):

| Path | State 2026-08-15 |
|---|---|
| `…/tizonia/tizonia-openmax-il` | **primary** — registered `disabled_for_dispatch`, `dispatchable=false` by kind. On branch `codex/issue-819-remove-libspotify`, **not** `master`; 1 untracked file |
| `…/tizonia/tizonia-openmax-il-issue-818` | the **adopted, dispatchable** pool member (PR A step 2 registered it `available`). On `codex/issue-818-remove-gmusic-v2`; `build/` = 34 MB |

Two consequences to handle, not to tidy away:

- **The soak runbook's pre-flight "local tizonia checkout clean on `master`" is currently
  UNMET.** The primary sits on the #819 branch, whose PR #865 the run log records as
  "survived, but conflicted and orphaned". Reconcile before Gate 7; report rather than
  force-clean, and never `git clean -fdx` (PR A prohibits it — that is what would delete the
  build cache).
- **That untracked file is a 0-byte `claude_registry.db` dated 27 Jul.** Trap 4 in the traps
  table has already fired once here: a backend was started with the tizonia checkout as CWD.
  It is empty, so nothing was lost — treat it as evidence the trap is real, not theoretical.

**Scope config**, verified live at PR A step 3: `base_ref=origin/master` (resolves),
`builds_out_of_tree=true`, `build_dir_template=build`,
`meson compile -C {build_dir} -j{parallelism}`, `max_build_parallelism=4`. The parallelism cap
exists because Finding 11 was concurrent C++ builds OOM-ing the box and killing the team
overnight — it is a resource guard, not a tuning knob.

**Team shape** (preset 2 `tizonia-v1`, all slots codex-cli). Last known ids; the G1 respawn
changes sessions, not slots:

| Slot | Role | Routes on |
|---|---|---|
| 4 | **Leader** — the approver | `leader_fallback` when no area matches |
| 5 | Generalist | `area:build`, `area:docs` |
| 6 | Specialist | `area:services`, `area:packaging`, `area:ci`, `area:tests` |

Slot 6 exists because a 2-slot team routed 12 of 16 issues to the Leader, producing a
bottleneck and self-acks at scale — which is Finding 1, the defect PR1's distinct-approver
gate now closes.

**Timing:** `GITHUB_DISPATCH_INTERVAL_SECONDS=60`, `GITHUB_CHECK_SIGNAL_GRACE_SECONDS=120`,
ack/idle/nudge at code defaults (300 / ×3 / 900 / 180). Record any change you make.

## How work moves through this repo

**Remote:** `origin` is `github.com/adrirubio/claude-deck` — the working repo where PRs and
issues live. Issue numbers in this document are that repo's.

**Branching:** a phase gets `feature/<feature>-phase-<x>` off the long-lived integration
branch (`feature/autonomous-github-dispatch`); each phase PRs **into the integration branch,
not master**; phase issues stay open and close together when integration merges to master.
Note the drift: PR #316 already merged integration → master on 2026-08-14 while #272/#275/
#277/#280 stayed open. The operator resolved this on 2026-08-16 by restoring
`feature/autonomous-github-dispatch` as the soak delivery line. From G0 onward, defect
PRs target that branch and are held there until the remaining gates pass. This does not
undo the earlier #316 merge; it prevents further soak fixes from reaching `master`
prematurely.

**Roles** (established during phases A–D and unchanged):

- **The assistant** is design brain + orchestrator + reviewer: brainstorm → plan → write the
  spec and implementation plan, then hand implementation off. It does not write the feature
  code.
- **The impl agent (Codex CLI)** executes the plan task by task, reports at a PR checkpoint,
  and **does not self-merge**.
- **Handoff** is a GitHub issue linking the committed spec + plan by blob URL, plus
  prescriptive handoff files. The spec/plan must be pushed first so the links resolve.

**Review discipline, non-negotiable:** every impl-agent claim is re-verified independently
against the source and the live DB. "Tests pass" and "PASS" are not evidence; a number
someone else measured is not a measurement. This verify-don't-trust loop caught 8 bugs during
the tizonia e2e gate that unit tests missed, and 2 of 12 mutations survived PR A's review by
being *understood* rather than waved through.

**Per-change gates** before any commit: `/code-review` → `/simplify` → `/verify` → manual
verification of the feature, then conventional commits (`feat`/`fix`/`chore`/`docs`/
`refactor`). Backend venv is `venv`, not `.venv`; the suite for this work is
`pytest tests/agent_teams tests/agent_mail -q`.

**The precedent this handoff departs from, stated so the boundary is explicit.** The recorded
split is that **soak execution is orchestrator-driven** — the impl agent writes code and
runbooks; enabling autonomy and driving live agent sessions against tizonia has been the
orchestrator's job. The reason is on the record: the impl agent has previously invented
statuses, inverted test scenarios, and killed working-but-slow sessions. This handoff crosses
that line deliberately, so the guardrails that made the split safe are restated here as hard
rules rather than left implicit: rules 1, 5, 6 and 9, the *Not yours to do* list, and —

**STOP and report.** If a step's precondition does not match what you measure, stop and
report the measurement. Do not adapt the step, do not substitute a similar subject, do not
"fix" the state to match the plan. Every one of the 19 findings came from a step that did not
match its precondition; the deviation **is** the finding, and adapting past it is how one gets
lost. Recent precedent, from PR A step 3: values were set from memory, were wrong, and were
caught only on re-reading the step. Read each step immediately before executing it.

## Standing rules

These hold across every gate. They are not advice.

1. **Autonomy is off by default, and G3/G4 are the two deliberate exceptions.** Toggle it
   only through `PATCH /api/v1/agent-teams/presets/{id}`, never by editing a row.

   The exception is not a relaxation, it is forced: **there is no manual dispatch trigger.**
   Verified on `origin/master` — `dispatch_pending`, `poll_scope` and `process_scope` appear
   **nowhere** in `backend/app/api/v1`, and the only caller is the scheduler job, gated on
   `autonomy_enabled.is_(True)` (`github_dispatch_scheduler.py:64`, `:118`). `retry` sets an
   item to `pending`; nothing then consumes it. This is exactly the blocker that stopped PR A
   step 5 on 2026-08-01, and it is still true today.

   So G3 and G4 run with autonomy **on and narrowly armed**: point the scope's
   `dispatch_label` at `agent-ready-e2e`, label **exactly one** issue with it, let the
   dispatch happen, then set autonomy back off. That is the isolation mechanism the soak
   already used for smoke tests (run log, 2026-07-06), and it satisfies rule 6 — you are
   driving with a label, not a row edit. `agent-ready-e2e` currently has **0** open issues,
   so nothing is armed by accident.

   **Never enable autonomy while `dispatch_label` is `agent-ready`.** Ten issues are armed
   with that label right now (see the testbed section); a broad enable is Gate 7, and Gate 7
   is the operator's call.
2. **Never recreate the database.** `backend/claude_registry.db` holds the 28 work items
   that made Findings 17, 18 and 19 provable. `CLAUDE.md` lines 67 and 93 still say
   "no database migration system — schema changes require deleting the db". That line is
   **wrong** and following it destroys the evidence; the idempotent ladder at
   `database.py:290` is the migration system. Correcting `CLAUDE.md` is an owed `docs:`
   commit (G2 §9).
3. **Never `export` a secret.** `spawn_session` runs tmux with no `env=`, so the tmux
   server inherits the backend's environment and any pane reads it with
   `tmux show-environment -g`. Secrets go in `backend/.env` at mode `600`.
4. **Start the backend from `backend/`.** `config.py:9` sets `env_file=".env"` and the DB
   path is CWD-relative. Started from the repo root, the backend loads no `.env` *and*
   creates a virgin database — which presents as "the token didn't deploy" while orphaning
   the soak evidence.
5. **Never terminate a dispatched session, or report on its behalf**, unless positively
   confirmed dead (process gone / `wake_state=offline`).
6. **Do not hand-edit DB rows to steer a scenario.** Drive through labels and config. The
   one sanctioned `UPDATE` is Gate 5's scope reset, and it has its own gate.
7. **Kill panes before restarting the backend**, not after: codex reconnects to durable
   member IDs and recreates duplicates otherwise.
8. **One uvicorn worker.** The installation-token cache, revocation locks and PR-creation
   lock are all process-local.
9. **Record measurements, not conclusions.** Every gate's evidence goes in the run log as
   the observed value. "Verified" without a number is not an entry.

## Not yours to do

Escalate to the operator rather than performing these:

- Creating or installing the GitHub App; provisioning its private key.
- Any branch-protection change (Gate 6 included).
- Enabling autonomy (Gate 7), or any production enablement.
- Deleting or recreating the database, or any DB write outside Gate 5's scope reset.
- Killing a pane whose session has unfinished work.

## Measured state, 2026-08-15

Re-measure before acting. This is a snapshot, and rule 9 applies to it too.

| Fact | Value | How measured |
|---|---|---|
| `origin/master` | `96954a6` (Aug 14) — G2-release, G2-delivery, G3, PR0, PR1, PR2 all merged | `git log -1 origin/master`; `git merge-base --is-ancestor` per branch |
| Live checkout `/home/juan/work/repos/juanrubio/claude-deck` | `832a4de` (Aug 4), branch `feature/autonomous-github-dispatch`, **113 commits behind** `origin/master`; G2/G3 code absent, only their docs | `git rev-list --count HEAD..origin/master`; `merge-base --is-ancestor` for each phase branch |
| Last deployed code | PR A `c92b044` (2026-08-01) | run log, PR A §7 status block |
| Backend / frontend | **down** — nothing listening on `:8000` or `:5173` | `ss -ltnp` |
| tmux server | **absent** — `/tmp/tmux-1000/default` does not exist; zero agent panes | `tmux list-panes -a` |
| `backend/.env` | mode `600`, contains **`github_token` only** — no `operator_token`, no `mail_capability_tokens_required`, no `GITHUB_APP_*` | `grep -oE '^[A-Za-z_]+' backend/.env` |
| DB | `claude_registry.db` 1.1 MB (Aug 9 19:56) + **`-wal` 5.0 MB, uncheckpointed** (Aug 9 20:21) + `-shm` (Aug 11 21:42) | `ls -la backend/claude_registry.db*` |
| Worktrees | primary; `claude-deck-g1` on `fix/codeql-integration` @ `25622d5`; three prunable `/tmp` review worktrees | `git worktree list` |
| `autonomy_enabled`, work-item counts, workspace rows | **UNVERIFIED — read them yourself at G0.** Last known (2026-08-01): autonomy off both presets, 11 escalated / 11 completed / 6 merged, 2 workspaces (1 dispatchable) | not measured on 2026-08-15 |

**The WAL is the headline.** A 5 MB uncheckpointed WAL against a 1.1 MB main file means
most recent state lives in the WAL, not the `.db`. Two consequences: any inspection copy
must copy `.db`, `-wal` **and** `-shm` together or it silently reads stale data, and the
G0 backup must include all three. A `.db`-only backup is not a backup.

## The gates

### G0 — cold-start the rig on the merged code

**Goal:** the live checkout runs `origin/master`, the ladder has migrated, and no evidence
was lost. **Source:** G2 §7 step 1.

1. Back up all three DB files to a timestamped path outside the repo. Verify the copy's
   sizes match the originals before proceeding.
2. Confirm nothing is listening on `:8000` and no tmux server exists (else stop: rule 7).
3. Fast-forward the live checkout to `origin/master`. Decide the branch question in
   *Open decisions* first.
4. Start the backend **from `backend/`**, one worker. The ladder runs from `init_db`
   (`database.py:521` → `:527`) and is idempotent.
5. **Verify by reading the schema out of the live DB, not the ORM:**
   - `github_workspaces` has `lease_token`, `push_token_expires_at`, `leased_owner_pid`,
     `leased_owner_proc_start`, `lease_last_owner_contact_at`, `lease_release_reminded_at`
     (`database.py:476-497`).
   - `github_work_items` has `retry_requested_at`, `brief_delivery_nudge_at`,
     `brief_delivery_nudge_count`, `ack_approver_member_id`, `ack_evidence_message_id`,
     `dispatch_nonce`, `ack_enforcement_epoch`, `ack_approval_round`, `dispatch_head_ref`,
     `dispatch_base_ref` (`:439-475`).
   - `team_github_scopes` has `github_auth_mode` (default `'unknown'`, NOT NULL) and
     `github_app_installation_id` (`:430-437`).
   - Work-item counts by status **unchanged** from the pre-restart reading you took in
     step 1. Take that reading before the restart, not after.
   - `autonomy_enabled` still `0` on both presets.
6. Run `pytest tests/agent_teams tests/agent_mail -q` in the deployed checkout and record
   the counts. One known-stale failure is expected at
   `test_multi_provider_smoke.py:54`; anything else is a stop.

**Fail:** any column missing means the ladder did not run — check the CWD (rule 4) before
touching SQL. Counts changed means you are looking at a different database.

### G1 — PR0 credential rollout

**Goal:** the operator credential works and every agent pane holds a capability token.
**Source:** `deploy/pr0-capability-tokens-rollout.md`, four steps, in order. Step 4 before
step 3 locks every agent out of mail.

Verified against source, so you do not have to re-derive it:

- Settings names are `operator_token` and `mail_capability_tokens_required`
  (`config.py:56-57`, `case_sensitive=False` — either case works in `.env`).
- Headers are `x-deck-operator-token` and `x-deck-session-token` (`deps.py:44`, `:80`;
  HTTP header names are case-insensitive, so the rollout doc's `X-Deck-Operator-Token`
  is the same header).
- `require_operator` refuses in this order: **503** `operator_token_unconfigured` (setting
  empty) → **401** `operator_token_required` (no header) → **401** `operator_token_invalid`
  (mismatch) — `deps.py:79-110`. So a `503` after step 2 means the restart missed the
  file; a `401 invalid` means a trailing newline or quotes in the value.
- The capability token is **a column, not a table**:
  `mail_agent_sessions.capability_token_hash` (`models/database.py:412-440`). Pane
  bindings live in `agent_pane_bindings` (`:344-358`). Verification query is
  `SELECT count(*) FROM mail_agent_sessions WHERE capability_token_hash IS NOT NULL`.

**Step 3 is a full team respawn, not a restart.** There is no tmux server, so there are no
panes to restart. Before spawning: clear orphaned session rows (rule 7's hygiene), then
launch, then confirm each member registers and mints a token.

**Report before flipping the flag in step 4** — a question, not a finding, and I did not
trace it: `mail_session` (`deps.py:44-61`) resolves a caller by comparing
`capability_token_hash` and performs **no liveness check on the bound pane**. The live DB
carried ~150 `source="mcp"` session rows as of 2026-08-05. Determine whether registration
deletes or replaces prior rows for the same pane, and whether a stale row's token hash
therefore remains a valid credential for a pane that no longer exists. Record the answer
in the run log either way.

**Pass:** `401` on force-release with no header, `200`/`404` with it; no new
`capability_token_missing` log lines for respawned members; after step 4, a tokenless mail
write is `401 session_token_required` and a bad token is `401 session_token_invalid`
(never treated as absent).

**Rollback:** `mail_capability_tokens_required=false`, restart. The operator half took
effect at step 2 and is not covered by the flag.

### G2 — PR1 verification, autonomy still off

**Goal:** authenticated mail and `/dispatch-status` work end to end on a **non-autonomous
test preset**. **Source:** `deploy/pr1-approval-gate-rollout.md` step 5.

Expect `409 tokens_not_enforced` on **every** `/dispatch-status` branch until G1 step 4 is
done — that refusal is PR1 protecting its own guarantees, not a defect. Route is
`POST /api/v1/agent-teams/dispatch-status` (`agent_teams.py:627`).

### G3 — G2 re-arm steps 2–6 (never run)

**Goal:** one real dispatch through each delivery path. **Source:** G2 §7 steps 2–5 plus
the owed sixth step in §9.

Step 2 as written ("converge slot 6 to one session") is **moot**: the sessions it names are
gone with the tmux server. What survives is its intent — one session per slot — which G1's
respawn satisfies by construction. Clear stale rows, do not chase the named sessions.

**Arming, before either dispatch below.** Per rule 1 this gate needs autonomy on, and it must
be armed to exactly one issue: `PATCH` the scope so `dispatch_label=agent-ready-e2e`, confirm
`agent-ready-e2e` has **0** open issues on the testbed, label **one** issue with it, then
enable autonomy on preset 2. Turn autonomy back off before leaving the gate, and remove the
`agent-ready-e2e` label from the issue you used. Prefer an issue whose work is small — the
subject under test is the delivery and release mechanics, not the C++.

- **Spawn path:** dispatch one fresh item to a slot with **no** standing session. Verify
  the brief lands in the owner's inbox and is read; the agent works inside the *leased
  worktree*; `workspace_released` with the correct `lease_token` returns the lease; a
  **repeat** of that token is `200`; a **stale** token is `409` with the lease retained
  (`agent_teams.py:393`, `:427`, `:747`).
- **Reuse path (the owed sixth step):** dispatch a second item to a slot that **does**
  carry a standing session. Verify the brief arrives by mail and that **no second pane
  appears**.
- Do **not** retry item 23. It stays escalated (PR A §7's ⛔ block explains why it is the
  wrong subject).

### G4 — PR A §7 step 5, the deferred dispatch half

**Goal:** close the risk PR A deferred on 2026-08-01. **Source:** PR A §7 step 5 and its
⛔ status block. Both original blockers are removed by G2/G3 (a trigger now exists; the
liveness predicate is trustworthy) — confirm that yourself rather than assuming it.

Specifically unverified since PR A merged, all of it on real git:

- `acquire` under a real dispatch.
- `reset_workspace`'s four commands on a real worktree.
- That `clean -fd` **preserves the meson build cache** in practice. **Do not use PR A's
  "1.1 GB" as the assertion — it is stale.** Measured 2026-08-15: the `issue-818` worktree's
  `build/` is **34 MB** and the primary's is 5.5 MB. Take the baseline `du -sh` on the leased
  worktree immediately before the dispatch and assert *that* number survives; a hardcoded
  figure that no longer matches anything on disk makes the check unfalsifiable.
- That the brief names the worktree path (if it dispatches with `scope.repo_path` as cwd,
  the change did not take).
- Release on launch failure.

Recovery actions, neither needing DB surgery:
`POST /github-scopes/{scope_id}/workspaces/{workspace_id}/reprobe` (`:1173`) if a reset
failure disabled the worktree, and `POST /github-work-items/{item_id}/abandon` (`:1395`)
if an item wedges in a review status. Using either is itself a first — record it.

### G5 — PR2 GitHub App staged rollout

**Goal:** bot-authored commits and PRs on one sandbox repo. **Source:**
`deploy/pr2-github-app-rollout.md`; scope-reset detail in the design's §5.9.

App creation, installation and key provisioning are operator actions (see *Not yours to
do*). Permissions are Contents RW + Pull requests RW + Metadata RO only — **no**
Administration, Workflows, or protection bypass. Settings are `github_app_id`,
`github_app_private_key_path`, `github_app_bot_login` (`config.py:40-42`), in
`backend/.env`, key at `0600`.

**The scope-reset gate is the step that must not be improvised.** In order: autonomy off
for every affected preset → confirm every affected `github_workspaces.leased_item_id` is
`NULL` → in **one** transaction set `github_auth_mode='unknown'` **and**
`github_app_installation_id=NULL` → read both columns back. Never reset a live scope: a
leased worktree's credential helper reads the persisted installation id
(`agent_teams.py:437` `POST /git-credential`).

Skipping the reset is the trap the design calls out by name: a scope that resolved
`ambient` before the App existed keeps using the human's credential forever, and the
resulting human-authored PR reads as a misconfigured App. `unknown` is the only value
meaning "ask again".

Then one sandbox dispatch verifying worktree commit identity, authenticated push,
Deck-created PR, and managed-config cleanup after release. Expand to further repos only
after that full lifecycle completes. Diagnostics to expect are listed in the rollout doc
(`app_not_installed`, `app_auth_unconfigured`, `app_mode_bot_login_unset`,
`queued_auth_mode_unresolved`, `pane_unresolved`, and `501` meaning a stale mixed-version
deployment).

### G6 — restore branch protection (operator)

`required_reviews=1, enforce_admins=true` on the testbed's `master`. It was relaxed as a
soak accommodation because agents could not approve their own PRs; PR2's bot authorship is
what makes restoration possible (criterion 7). Operator action.

### G7 — resume the soak runbook

**Source:** `specs/2026-07-06-tizonia-roadmap-v1-soak-runbook.md`. Treat its pre-flight as
superseded by G0–G6 above; its windows and invariants stand.

- **Window 1** (`merge_policy=human`, autonomy on): every touched issue ends `merged`,
  `escalated` with an explainable reason, or `still-working`. Zero silent stranding, zero
  unintended public write. Record a row per issue in the outcome table.
- **Window 2** (`merge_policy=auto`, only after Window 1 is clean): the finding-#3 head
  re-confirm guard must fire **at least once** on a moved or red head — inject a controlled
  red-commit-after-promotion if the roadmap will not produce one. `max_auto_merges_per_day`
  holds; per-slot concurrency queues under real load.

## Traps

Each of these has already cost a session or was measured as a live defect.

| Trap | Consequence |
|---|---|
| `.db`-only DB copy | reads state from Aug 9 minus the 5 MB WAL — silently stale |
| Backend started from repo root | no `.env` loaded **and** a virgin DB created; evidence orphaned |
| `export`ing any secret | every pane reads it via `tmux show-environment -g` |
| Following `CLAUDE.md` on migrations | destroys the soak evidence |
| Restarting the backend before killing panes | codex reconnects, duplicate members |
| Resetting a live (leased) scope | the credential helper reads the id you just cleared |
| Enforcement flag before pane respawn | every agent locked out of mail |
| Trusting a spec's line numbers | they have already drifted (`init_db` `:458` → `:521`) |
| Reading a runbook step from memory | happened at PR A step 3; wrong values were set and only caught on re-reading |

## Carried-forward obligations

Open, and not owned by any gate above:

- `CLAUDE.md` lines 67 and 93 contradict `database.py:290`. Owed as its own `docs:` commit
  (G2 §9) — it misleads every future reader, not just this schedule.
- `_validate_adoption_is_available`'s blind spot (PR A §2.3): recorded, not fixed, and it
  will mislead a future reader.
- Issue #312: `agent_bridge` session-filter smoke test broken since `1840c05` (route became
  async, the test never awaits).
- Trackers still open: #306 (G2), #304 (PR A / Finding 16), #302, #300, #298, #296, #294,
  #281, #280, #277, #275, #272.

## Open decisions for the operator

1. **Resolved 2026-08-16 — which branch the live checkout tracks.** G0 historically ran
   from `origin/master` because PR #316 had already merged. For G1 onward, track
   `origin/feature/autonomous-github-dispatch`. The branch was fast-forwarded through
   #316 and given the durable runbook; Finding 20 PR #320 was retargeted there. Hold all
   subsequent soak fixes on that integration branch until the remaining gates pass.
2. **Restart granularity in G0/G1.** The PR0 doc separates the code restart from the
   token restart. Recommended: keep them separate — one variable per restart gives a free
   bisect on a 113-commit jump against an irreplaceable database, and a restart costs
   seconds.

## Evidence protocol

The run log (`specs/2026-07-06-tizonia-roadmap-v1-soak-run-log.md`) is the artifact, not
this document. Append a dated section per gate containing: the commands run, the observed
values (rule 9), anything that deviated from the plan, and any new finding numbered in
sequence — the last one used is **Finding 19**. A gate with no run-log entry has not been
completed, however green it looked at the terminal.
