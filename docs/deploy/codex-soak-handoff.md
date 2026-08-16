You are taking over execution of the claude-deck soak deployment schedule from the
orchestrator. This is a departure from the usual split (soak execution has been
orchestrator-driven, not impl-agent work), so the guardrails below are hard rules,
not advice.

REPO: /home/juan/work/repos/juanrubio/claude-deck   (origin = adrirubio/claude-deck)
TESTBED: /home/juan/work/repos/tizonia/tizonia-openmax-il  (public repo, real CI)

## Read first, in this order

1. docs/deploy/soak-resume-runbook.md  — YOUR SCHEDULE. Gates G0 through G7, in order.
   Currently UNTRACKED. Read it in full before doing anything else.
2. The specs it cites, as you reach each gate. The runbook owns the ORDERING;
   the specs are normative for DETAIL. Where they disagree, the spec wins on
   detail and you report the discrepancy.

Line-number citations in all these docs have drifted (e.g. G2 §7 cites init_db at
backend/app/database.py:458; it is actually at :521). Re-resolve every citation
against the current file before acting on it. Do not trust a line number.

## First action

Commit the runbook so it is durable and reviewable:
  git add docs/deploy/soak-resume-runbook.md
  git commit -m "docs(deploy): soak resume runbook — gates G0-G7"
Do not modify its content in that commit. If you later find it wrong, fix it in a
separate commit whose message says what was wrong and how you verified the correction.

## Where the checkout stands

HEAD is 832a4de on branch feature/autonomous-github-dispatch, 113 commits behind.
origin/master carries six merged-but-undeployed units: G2-release, G2-delivery, G3,
PR0, PR1, PR2. Last actual deployment was PR A (c92b044) on 2026-08-01.

For G0: check out master and fast-forward to origin/master. The integration branch
has served its purpose (#316 already merged), so master is the tracking branch now.

The rig is fully cold: no backend, no frontend, no tmux server. backend/.env holds
only github_token.

## Hard rules — violating any of these is worse than not finishing

1. NEVER `export` a secret. spawn_session starts tmux with no env=, so the tmux
   server inherits the backend's environment and ANY pane can read it with
   `tmux show-environment -g`. Secrets go in backend/.env at mode 600. Only.
2. NEVER delete, recreate, or reinitialize backend/claude_registry.db. It holds
   irreplaceable soak evidence across every phase. CLAUDE.md lines 67 and 93 are
   WRONG about schema changes needing a db delete — the SQLite compat migration
   ladder in backend/app/database.py handles them. (Correcting those two lines is
   an owed docs commit; do it, separately.)
3. Start the backend from inside backend/. Both the .env path and the sqlite path
   are CWD-relative. Starting it elsewhere silently creates an empty db in that
   directory — this has already happened once in the tizonia checkout.
4. The virtualenv is `venv`, not `.venv`.
5. Do NOT hand-edit database rows to steer a scenario. Drive everything via GitHub
   labels and preset/scope config. The only sanctioned UPDATE in the whole schedule
   is the gated scope reset in G5, and only after its gate passes.
6. Do NOT terminate a dispatched agent session, or report status on its behalf,
   unless you have positively confirmed it dead (process gone, or wake_state=offline).
   Killing a working-but-slow session has happened before and destroyed a gate.
7. NEVER `git clean -fdx` a leased workspace. It deletes the meson build cache.
8. Autonomy is OFF by default and toggled ONLY through
   PATCH /api/v1/agent-teams/presets/{id}. Never by editing a row.
   G3 and G4 REQUIRE autonomy on, because there is no manual dispatch trigger —
   dispatch_pending / poll_scope / process_scope appear nowhere under
   backend/app/api/v1, and the scheduler job is the only caller, gated on
   autonomy_enabled.is_(True). So arm it NARROWLY: point the scope's dispatch_label
   at `agent-ready-e2e` and label EXACTLY ONE issue with it.
   There are currently 10 open tizonia issues carrying `agent-ready`. Enabling
   autonomy while dispatch_label is `agent-ready` fires ten dispatches at once.
   Never do that.

## Not yours to do — stop and hand back to the operator

- Creating the GitHub App, generating/installing its private key, installing it on
  the testbed org (G5 prerequisites).
- Any change to branch protection on tizonia master (G6).
- Enabling autonomy for anything beyond the narrowly-armed G3/G4 windows.
- The G7 soak windows' merge_policy=auto decision.

## The state table is a snapshot, not live state

The "Measured state, 2026-08-15" section is dated and several rows are explicitly
marked UNVERIFIED — read them yourself at G0 before acting. Note the db has a
multi-megabyte uncheckpointed WAL: copying only the .db file reads STALE state.
Copy claude_registry.db, .db-wal and .db-shm together, or checkpoint first.

## One open question to answer before G1's enforcement flip

backend/app/api/v1/deps.py — mail_session compares capability_token_hash with
hmac.compare_digest but performs NO pane-liveness check against the recorded
bound_pane_pid / bound_pane_proc_start. Determine whether a token stolen from a
dead pane still authenticates, and report your finding BEFORE setting
mail_capability_tokens_required=true. Do not treat this as a known bug; it may be
checked elsewhere on the path. Verify, then report.

## Protocol

- Work one gate at a time, in order. Each gate has explicit pass criteria.
- Append evidence to docs/superpowers/specs/2026-07-06-tizonia-roadmap-v1-soak-run-log.md
  as you go: the command you ran, its actual output, and the verdict. Raw output,
  not a summary of it. A claim without pasted evidence does not count as a pass.
- Report to the operator at the end of each gate. Do NOT start the next gate if the
  previous one failed or was inconclusive.
- If a step looks wrong, contradicts what you observe, or cannot be done as written:
  STOP and report. The deviation IS the finding. Do not improvise a way around it,
  do not substitute a different step, do not mark it done. Getting stuck and saying
  so is a correct outcome; inventing a status is not.
