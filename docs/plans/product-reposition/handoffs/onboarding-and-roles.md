# Repository onboarding and roles implementation handoff

**Execution baseline, 2026-10-02:** G00 passed through upstream PR #399 / `ac9252242fcf436c3ea9997add5d32416cad2cd1`. Product work starts first in the fork `juanrubio/claude-deck`, from and targeting `feature/software-delivery-product-reposition`. Follow the agent deployment plan and startup gates. Earlier release snapshots and M0 readiness tables are historical evidence; this decision supersedes their pending-G00 or master-target instructions.

Implement **P04 in M2**, after M1b: make Leader authority explicit and guide an operator through repository, team, routing, access/label checks, and policy configuration.

Read the [architecture contracts](../architecture-contracts.md) and [experience specification](../experience-spec.md). The explicit-role change affects actual authority, so its backend, SQL guards, and UI must agree.

## Start conditions

Start only after the autonomy feature has been merged into `master` ([G00](../implementation-plan.md#autonomy-merge-gate)). Branch from updated `feature/software-delivery-product-reposition` and record the autonomy merge evidence and base SHA.

M1b must be accepted and its contracts stable, with the earlier pilot disposition recorded. The team-deletion guard must be integrated. Preserve the audited operator/agent authorization distinctions, and complete this package's creation/import/duplication guards before exposing wizard writes.

Rebase after P01's projection extraction and P03's readiness extraction. This package owns the next edits to team services and authority records.

## Source files

- `backend/app/models/database.py`, `models/schemas.py`, and `database.py`.
- `backend/app/services/agent_team_service.py`.
- `backend/app/services/github_dispatch_service.py`: `_leader_slot`, routing fallback, briefs, acknowledgement evidence, and monitoring.
- `backend/app/services/agent_mail_service.py`: `_dispatch_participants` and approval participant derivation.
- `backend/app/services/github_approval_service.py`: SQL designated-Leader guards.
- `backend/app/api/v1/agent_teams.py`: protected routes and server-derived authority.
- `frontend/src/features/agent-teams/leaderSlot.ts`, `AgentTeamsPage.tsx`, `api.ts`, and team types.
- `backend/tests/test_sqlite_compat_migrations.py` and existing team/approval tests.
- The earlier conversational setup spec in `docs/superpowers/specs/2026-07-04-conversational-team-and-autonomy-setup-design.md`.

The earlier conversation spec informs the setup stages. This package implements a deterministic reviewable flow, without introducing an LLM interview service.

## Write scope

Own new `backend/app/services/team_authority_service.py`, the explicit assignment model/schema/migration, affected authority consumers, creation-route guards/clients, the bounded setup-preflight endpoint, role/setup tests, and new `frontend/src/features/repository-setup/`.

Coordinate team types and route registration after M1b. P05 follows this package in shared database and mutation files. Reuse the shared per-tab credential helper; cookie/session login is not part of this package.

## Explicit authority steps

1. Inventory every current first-enabled-slot selection and caller ordering, including SQL guards and cold-start monitoring. `_leader_slot` sorts by position while audited callers supply `(position, id)` order; do not assume a demonstrated production mismatch.
2. Add nullable `leader_slot_id` to presets and a shared resolver.
3. Add a one-time compatibility migration using the existing SQLite migration mechanism. Prove the same Leader is selected for tied positions, disabled slots, and pending authority, and that no-enabled-slot presets remain unassigned. Repeated startup must not overwrite later explicit assignments.
4. Preserve pending and approved request identities, owner/approver separation, active revision/lease identities, and existing member bindings. If a legacy authority conflict cannot be reconciled safely, report it rather than rewriting approval evidence.
5. Add an operator-protected assignment route with expected previous assignment, expected update timestamp, and reason.
6. Apply the paused/quiescent precondition and same-team/enabled-slot validation. Enforce state checks transactionally so a concurrent owner action cannot bypass them.
7. Update dispatch fallback, participant derivation, prompts, initial and continuation decisions, SQL checks, and monitoring to resolve the explicit field.
8. Reject disabling/deleting the designated Leader without a valid replacement. Preserve assignment when roster order changes.
9. Update duplication/import/creation so copied slots use their new IDs and activation requires a deliberate assignment.
10. Replace frontend inference with the server-projected Leader. Display descriptive roles separately.

An authority-preserving schema upgrade and an operator changing authority are different operations. Migration tests must cover existing pending/active records; the update route refuses changes while those records are in use.

Manual single-agent teams remain valid. Automatic work retains the existing distinct-owner/approver requirement.

No slot-position uniqueness constraint is required. The explicit assignment removes authority's dependence on order. Supply the [paused rollback procedure](../architecture-contracts.md#explicit-leader-assignment): stop relevant writers after quiescence, back up, compare explicit assignments with legacy resolution, and validate representable downgrades on a restored copy. Refuse downgrade for divergent/unrepresentable assignments instead of silently transferring authority. Restoring an old production database is a separate release decision.

Before wizard writes, protect POST team creation, creation from Mail/Bridge, and duplication with operator authority. Update all browser callers and compatibility documentation together, including the legacy UI. Inventory any agent-tool callers separately; preserve legitimate retry/launch authority and do not treat arbitrary Mail-session possession as team-creation authorization.

## Setup steps

Implement a flow at `/repositories/new` with five stages:

| Stage | Data and checks |
| --- | --- |
| Repository | GitHub identity, existing primary checkout, explicit polling-access check, and remaining host prerequisites |
| Team and roles | Existing/new roster, explicit Leader, worker harnesses, shared readiness; reuse an active team's assignment unless a separate eligible role change is reviewed |
| Routing | Dispatch/design labels with existence checks, area routing, expertise, and potential overlap with other scopes |
| Policies | Separate activation, merge, verification, concurrency, and finite recovery defaults |
| Review | Concrete writes, dated checks/gaps, remaining host steps, selected team/scope, preserved activation, overlap warning, and next actions |

Keep edits in a local draft until configuration is confirmed. Reuse existing validation and safe installation/launch APIs. Do not collect host GitHub or operator credentials into the setup draft.

Implement the architecture's operator-protected `POST /factory/setup-preflight` as an explicit **Check access and labels** action. It observes validated inputs without creating records or labels. Check checkout identity, polling credential presence, repository readability, selected label existence, and selected dispatch-auth configuration separately. Use bounded timeouts and safe `ready`/`blocked`/`unknown` results; successful read access does not prove write/merge access.

Report only allowlisted setting names and presence booleans from effective server settings. Explain missing host steps: configure polling/operator credentials, any selected GitHub App settings, native harness/Mail installation, required backend restart, and GitHub label creation. Never return environment values, key-file paths/contents, raw `.env` data, or credential hashes. Readiness remains incomplete until required checks pass; disabled configuration can still be saved.

Create a new team with `autonomy_enabled: false`. Create every new repository scope with an explicit `enabled: false` request, including scopes added to an already active team; the current scope API defaults to true. For reused teams, omit activation fields from configuration writes and preserve their roster/Leader, policies, and other scopes.

If an existing scope is found during selection or recovery, reconcile its ID and state and review any requested edits. Do not apply new-record defaults or reset its activation. A Leader edit that fails the paused/quiescent precondition remains blocked; offer retaining the current assignment or selecting/creating another team. Never pause the team as an automatic setup step.

Launch only selected slots through a separately reviewed current launch plan. Enabling automation is another explicit operation after the relevant checks. Activating the new scope under an active team must affect only that scope. If the team is paused, the activation review must enumerate every already-enabled scope that would resume when team automation is enabled.

Recheck access/labels and scope overlaps before guided activation. Required blocked/unknown checks disable that action with a remedy. When current enabled scopes share the repository and dispatch label, show the affected teams and **This can dispatch the same issue more than once**, then require acknowledgement of that concrete warning. Include any sibling scopes resumed by team activation. Deliberate overlap remains allowed; this wizard adds no dispatch arbitration or exclusivity guarantee.

Existing setup APIs can commit independently. Track acknowledged created IDs and completed steps. A partial failure shows what exists and resumes remaining work. A lost response with an unknown creation or launch outcome does not cause blind re-creation or respawning; reconcile through reads and visible operator selection.

Apply human merge and existing finite limits to new scopes; preserve existing policy when reusing a scope unless its change is separately reviewed. Build settings remain agent instructions. Verify polling access separately from a selected dispatch authentication mode.

## Acceptance criteria

The relevant P06 cases are V13, V17–V21, V28, V35, the M2 activation observations of V36, and V37. Supply the integrated configuration fixture for P06's V32 comparison.

- Migration preserves the effective legacy Leader, member/request references, and authority records.
- Repeated migration/startup preserves explicit assignments.
- Roster reordering has no authority effect after migration.
- Missing, invalid, cross-team, disabled, stale, active, and unauthorized changes fail visibly.
- Python and SQL authority predicates agree, including self-approval refusal.
- Tied-position/no-enabled-slot fixtures prove migration compatibility, and unsafe authority downgrades are refused.
- Copy/import flows do not retain an original team's slot ID.
- The setup draft performs no writes until configuration confirmation.
- Save, launch-plan confirmation, launch, and activation are distinct visible acts.
- Adding a scope to an active team leaves all existing activation and policy values unchanged and creates the new scope disabled.
- A blocked Leader edit never pauses other scopes; a later explicit team activation previews all affected scopes.
- Partial or unknown outcomes cannot silently create duplicate teams, scopes, or sessions.
- Creation/import/duplication rejects unauthenticated or unintended principals and uses the shared browser helper; valid existing agent retry/launch remains supported.
- Missing repository access, labels, or host settings remains actionable and cannot become a ready state or guided activation.
- Same-label overlaps are shown and acknowledged without altering existing teams or pretending to enforce dispatch exclusivity.
- Preflight and UI expose setting presence only, never values or private host paths.

## Validation

Add explicit-role migration, API, race, and setup tests. Run relevant existing suites:

```bash
cd backend
python -m pytest tests/test_sqlite_compat_migrations.py tests/agent_teams/test_agent_team_api.py tests/agent_teams/test_agent_team_service.py tests/agent_mail/test_approval_concurrency.py tests/agent_teams/test_operator_auth.py -q
```

Also run the affected dispatch, continuation, Mail authority, and recovery-gate tests, plus new role tests. Choose tests by the resolver consumers actually modified.

Frontend checks:

```bash
cd frontend
npm run test
npm run lint
npm run build
```

Exercise interrupted setup, expired plan hashes, a missing owner/approver, and role changes concurrent with active work using isolated fixtures. For V28, reuse an active team with two existing scopes, add a disabled third scope, interrupt and resume the save, and verify no unrelated policy, activation, session, or intake change. Then activate only the new scope through the explicit action. Also verify the all-affected-scopes preview when the selected team is paused.

V35 covers missing token configuration, inaccessible repository, absent labels, timeout/rate limit, wrong checkout, changed draft inputs, and safe host remedies without real GitHub writes. V36 covers overlap appearing between review and activation. V37 tests representable rollback and refusal when an explicit Leader differs from legacy order; do not test by downgrading the user's database.

## Delivery evidence

Provide the resolver/caller inventory, tied-position migration equality, invalid-change matrix, copy/import evidence, authorization matrix, preflight fixtures/redaction, overlap warnings, configuration screenshots, active-team reuse/partial-failure evidence, and tested paused rollback procedure.

## Agent start instruction

> Start P04 only after G00, accepted M1b, and the deletion prerequisite. Branch from updated `feature/software-delivery-product-reposition`. Migrate Leader authority across Python/SQL consumers, proving tied-position compatibility and paused rollback. Protect creation routes, then add guided configuration with bounded access/label checks and explicit host/overlap remedies. Keep new scopes disabled and preserve reused teams. Supply migration, authorization, redaction, concurrency, and partial-outcome evidence.
