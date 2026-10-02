# Claude Deck product repositioning implementation plan

**Execution baseline, 2026-10-02:** G00 passed through upstream PR #399 / `ac9252242fcf436c3ea9997add5d32416cad2cd1`. Product work starts first in the fork `juanrubio/claude-deck`, from and targeting `feature/software-delivery-product-reposition`. Follow the agent deployment plan and startup gates. Earlier release snapshots and M0 readiness tables are historical evidence; this decision supersedes their pending-G00 or master-target instructions.

Follow **M0 → M1a → pilot checkpoint → M1b → M2 → M3**. With the autonomy release complete, pilot delivery observation before investing in the full harness catalog. Guided configuration and explicit authority follow; durable accountability and measured outcomes come last.

Use the [product brief](product-brief.md), [experience specification](experience-spec.md), and [architecture contracts](architecture-contracts.md) as the shared requirements. This plan assigns ownership and integration order rather than replacing those contracts.

## Autonomy merge gate

**G00 is satisfied:** upstream PR #399 merged 2026-10-01T19:20:30Z as `ac9252242fcf436c3ea9997add5d32416cad2cd1`. Product implementation uses the fork integration branch, subject to the packet, baseline, owner-bound dispatch and distinct Leader approval gates.

## M0 autonomy release

M0 completed with the actual PR #399 merge above. Historical pre-merge planning, audited candidate `301e37c1e53e822a47a9572dc592e866df77f763`, and observed master `96954a6a07d3b376ea9cd32341ce18dd6f6f9328` remain preserved in source snapshot commit `86a0f4702ef40f3f88bc5e1f53b26803ee7a0881`. Their pending owner/date/release assertions no longer schedule product work.

| Current record | Disposition |
| --- | --- |
| Autonomy release / G00 | Complete through upstream PR #399 and full merge SHA above |
| Product integration base / controller pin | `ac9252242fcf436c3ea9997add5d32416cad2cd1`; no runtime upgrade authorized |
| Packet reconciliation | B1 owns fork #4 / PR #15; exact-head B4 acceptance pending |
| Carried deletion prerequisite | B2 owns fork #5; V33 blocks M1a acceptance, with #5 before #6 in this factory |
| P06 baseline | B4 owns fork #11; accepted baseline precedes #7 UI edits |
| Intake arming | Root operator instruction pending; no readiness label or scope enablement |
| Pilot / promotion / deployment | Separate operator decisions; human merge remains policy |

Historical release/soak evidence is not a product live replay result. Product agents do not access the other lane's runtime or resources. The [reconciliation ledger](reconciliation-ledger.md) records outstanding product gates without reopening M0 or claiming unavailable evidence.

## Integration procedure

After G00 is satisfied, create implementation branches from the updated `feature/software-delivery-product-reposition` tip in isolated worktrees. Record the autonomy merge evidence and product integration base SHA in each PR. Reconcile the merged code with the audited integration snapshot `301e37c1e53e822a47a9572dc592e866df77f763`, especially the authorization matrix, browser signatures, deletion guards, and retry/launch semantics. The documentation worktree's older code is not the implementation base.

Use fixture databases, temporary repositories, mocked GitHub/provider operations, and isolated tmux sockets for tests that need processes. Do not copy the running host's `.env`, database, credentials, or live attempt state into these worktrees.

Target reposition PRs at `feature/software-delivery-product-reposition` on `juanrubio/claude-deck`. The autonomy feature branch is the analysis reference; reposition implementation follows its completed merge. A live autonomous replay continues to require its own existing runbook and authorization.

The coordinator owns integration decisions and the shared-file schedule. Implementation agents own the bounded package they receive. Assign actual agents explicitly; the suggested roles below do not assume that every role is currently connected.

## Packages and dependencies

| Package | Suggested role | Dependencies | Required result |
| --- | --- | --- | --- |
| P01 | Backend services implementer | G00; contract review; merged autonomy reconciliation | Delivery API and shared safe projections |
| P02 | Frontend implementer | G00; can start with fixtures; integrated reads depend on P01 | M1a delivery interface, thin Harnesses index, and static native adapter guards |
| P03 | Provider integration implementer | G00; M1a accepted; pilot checkpoint disposition to proceed | M1b operations contract, readiness, and full Harnesses catalog |
| P04 | Team and setup implementer | G00; M1b accepted; mutation/deletion prerequisites | M2 explicit Leader authority and guided configuration |
| P05 | Backend observability implementer | G00; P04 authority model; mutation authorization prerequisite | Audit events and measured outcomes |
| P06 | Validation and documentation implementer | G00; baseline before M1a UI changes; runs alongside each milestone | Acceptance evidence, operator-task comparisons, regression checks, and user documentation |

```text
M0 autonomy release ── G00: actual master merge
                            │
                            ▼
P01 delivery reads ──────────┐
P02 delivery UI + thin      ─┼── M1a acceptance
    Harnesses/static guards │         │
Deletion/route prerequisites ┘         ▼
                                Pilot checkpoint
                                      │ proceed / narrow / defer
                                      ▼
                            P03 harness operations ── M1b
                                      │
                            P04 roles/configuration ── M2
                                      │
                            P05 audit and metrics ──── M3

P06 starts after G00, captures the pre-M1a baseline, and validates each milestone.
```

## Mutation authorization prerequisite

Use the [audited route matrix](architecture-contracts.md#operator-authorization-prerequisite). Team/scope/slot policy mutations are already operator protected at the pinned snapshot. Retry permits an intended current-Leader session path, and launch permits constrained authenticated MCP requests. Team creation/import/duplication remains a specific P04 prerequisite.

After G00, read-only P01 and P02 work can merge before remaining guards. Before wiring each mutation, verify its current browser credential helper/signature and the server's intended principal and state checks. Test operator-only denials separately from valid agent retry/launch paths; do not remove legitimate agent authority through a blanket test expectation.

If a required guard is absent, keep that factory entry point observational and integrate the existing hardening work or a focused prerequisite PR. Do not add an unprotected factory proxy or claim that a confirmation dialog supplies authorization.

The coordinator owns the [team deletion prerequisite](architecture-contracts.md#team-deletion-prerequisite) until its named implementer supplies V33 evidence. Authentication alone does not prevent destructive cascades. This guard must pass before M1a acceptance even though P01's read work can proceed independently.

## M1a delivery workspace

### P01 delivery reads

Suggested PRs:

1. **P01a:** Extract shared work-item authority/projection helpers without changing legacy responses. Freeze the safe-field allowlist and explicit nonterminal-abandon behavior.
2. **P01b:** Add Overview and paginated Work reads with category/filter/count contracts, plus safe scheduler/gate observations and effective intake state.
3. **P01c:** Add safe work details and repository reads with verified session associations and same-repository/dispatch-label overlap warnings.

P01 freezes the response contracts with checked-in fixture examples, including recovery-only, stopped, and unknown runtime states. P02 uses those fixtures while the endpoint implementation proceeds.

### P02 delivery interface

Suggested PRs:

1. **P02a:** Establish shared frontend fetch/router/timer fixtures, then add navigation, a thin Harnesses index, the checked-in native surface/API adapter registry, route guards, aliases, and local delivery filters.
2. **P02b:** Implement Overview, Work, and repository views against P01 contracts, including effective automation and browsing that survives background refresh.
3. **P02c:** Add work details and stable context links to Teams, Bridge, and Mail, including a reviewed slot-specific launch-plan entry for an offline owner or Leader.

Retain the existing native dashboard as a guarded configuration summary accessible from Harnesses. An empty factory gives configuration-only users a prominent Harnesses entry alongside existing setup and sessions. Replace the homepage after the working delivery views are integrated. M1a reads the existing provider registry/status and does not depend on new operations/readiness/catalog endpoints.

P06 records the existing-interface task baseline after G00 and before M1a UI changes. The functional exit below is followed by the separate pilot checkpoint.

### M1a exit criteria

- Overview counts and Work rows agree for the full matching set, including more than one page.
- No factory view inherits the native configuration provider/project preference.
- All five harnesses have an entry in the thin index, with existing status facts and links limited to implemented native adapters.
- Native page access requires a matching provider/page/API adapter even when integration capability flags are positive.
- Configuration enablement and effective intake state are distinct, including recovery-only mode and stopped/unknown scheduler states.
- Browsing beyond the first page retains rows, cursor, focus, and scroll through multiple polling intervals.
- A stopped item explains its actual state and the next known actor.
- Work details provide stable context without a lease claim, Mail acknowledgement, or terminal input.
- Existing native routes and manual single-agent workflows remain accessible.
- Configuration-only users can reach their guarded configuration summary from an empty factory.
- Offline actor links open a reviewed authenticated launch plan; navigation never launches a session.
- Operator escalation remains in attention with truthful retry/stop semantics, and overlapping active scopes show duplicate-dispatch warnings.
- Mutation entry points meet the authorization prerequisite or remain explicitly observational.
- The team-deletion state/race guard is integrated.
- P06 cases V01–V04, V07–V16 at M1a scope, V26, V27, V33, V34, and the M1a observations of V36 pass.
- User documentation describes the shipped M1a pilot and keeps broader claims within observed evidence.

## Pilot checkpoint

Run V31 against M1a before starting P03 implementation. P06 reports baseline/after task results, participants and implementer involvement, correctness, navigation/time, credential prompts, defects, and unavailable observations. Record needs that actually justify M1b, M2, and M3.

The coordinator records the operator's explicit disposition: proceed with the proposed scope, proceed with named reductions, or defer remaining work while fixing identified problems. A missing comparison is recorded as unavailable and cannot support a user-benefit claim; any decision to continue for known internal needs must state that basis explicitly.

Seek at least two independent operators for broader usability claims. If only the maintainer or implementers participate, label the result internal usability evidence. Do not infer external demand or general onboarding success from it. Lack of external participants does not automatically block the user's factory improvements or required audit safeguards. Reorder/narrow optional presentation and metrics only through a documented dependency update.

## M1b harness operations

P03 starts after M1a acceptance and a recorded checkpoint disposition to proceed:

1. **P03a:** Add the ten operational-key classifications, `native_surfaces` metadata, and shared bounded readiness checks.
2. **P03b:** Extend P02's thin Harnesses index with full cards and provider-specific support/readiness explanations.
3. **P03c:** Validate all five providers, align launch readiness, and integrate catalog/adapter agreement checks.

P03 takes ownership of Harnesses components at this boundary. Keep P02's checked-in adapters; the new catalog further restricts their availability and write access. Freeze these additional fixtures before enabling M1b catalog gating, without reopening M1a's dependency on P03.

### M1b exit criteria

- All five providers have sourced operational classifications independent of native feature counts.
- Configuration readiness, credential checks, and slot binding remain distinct and agree with launch planning.
- Available catalog entries match implemented client adapters; missing, unknown, mismatched, and read-only entries cannot broaden API access.
- P06 cases V05 and V06 pass; repeat V11, V13, V14, V15, and V16 for the new components and catalog failure states.
- M1a delivery tasks remain usable, and documentation distinguishes the new readiness evidence from earlier registry facts.

## M2 explicit roles and repository setup

Suggested PRs:

1. **P04a:** Add the explicit Leader model, compatibility migration, shared resolver, SQL authority guards, and protected update route together.
2. **P04b:** Update team reads and the role editor; validate copy/import, reorder, disable, and deletion behavior.
3. **P04c:** Protect creation/import/duplication routes and their clients, then add guided repository configuration, explicit access/label preflight, host-step remedies, overlap acknowledgement, disabled new scopes, and reviewed launch planning.

Authority changes must land as a complete change across dispatch, Mail, approval SQL, monitoring, and projections. Keep UI selection tied to server authority.

Use tied-position and pending-authority fixtures to prove compatibility, without assuming a current production resolver bug. Validate the paused rollback procedure; refuse downgrade when explicit assignments cannot be represented by legacy authority. Continue using the shared per-tab operator helper. A new login/session model needs a separate decision.

### M2 exit criteria

- Upgraded presets retain the same designated Leader and existing authority identities.
- Roster reordering no longer transfers Leader authority.
- Invalid, stale, active, or unauthorized Leader changes are refused.
- New setup clearly separates saving configuration, launching a reviewed plan, and enabling automation.
- New scopes explicitly save with `enabled: false`; reusing an active team preserves its existing activation, Leader, and other scopes. A blocked role edit never causes an automatic team pause.
- Partial setup remains visible and resumable without duplicate teams, scopes, or sessions.
- Repository access, dispatch/design labels, and relevant host configuration have separate dated checks and actionable missing/unknown states. Saving a disabled configuration does not claim readiness.
- Potential duplicate dispatch is visible before activation, with explicit acknowledgement of the current overlaps.
- Manual teams can remain valid with a single slot and no automation.
- P06 cases V17–V21, V28, V35, V37, and the M2 observations of V36 pass; V13 also covers preflight/settings redaction. V32 records the M2 comparison, first-PR evidence or its absence, and the resulting limits on onboarding claims.

## M3 audit and measured outcomes

Suggested PRs:

1. **P05a:** Add the event model, immutable historical context, deletion-safe live references, and transactional policy/Leader change records.
2. **P05b:** Add truthful recovery-action records, forward lifecycle events, and separately evidenced delivery outcomes.
3. **P05c:** Add protected historical audit reads, safe aggregate metrics, and outcome/coverage-aware UI.

Start observation at a recorded instrumentation time. Historic snapshots retain their limitations. Extend existing mutation services; the event ledger is an observation system and does not trigger retries, approvals, or budget changes.

Prioritize durable policy/authority records required for the operator's own accountability. The pilot may narrow optional charts or cost presentation; external recruitment is not a blanket gate on this audit need. Record any scope change and its acceptance impact before assignment.

### M3 exit criteria

- Policy and Leader changes cannot commit without their required audit records.
- Actors reflect authenticated roles without fabricated personal identity.
- Recovery records distinguish applied, rejected, and uncertain outcomes.
- Throughput and duration use recorded lifecycle events and expose their coverage.
- Terminal tracking, delivered work, explicit non-delivery, and unknown outcomes remain distinct; human-reviewed design requires independent review evidence.
- Existing operator abandonment/escalation cannot manufacture a terminal non-delivery result, including when the item later retries.
- Valid team/scope deletion preserves events and historical filtering; renames and provider changes do not rewrite past attribution.
- Unsupported or unattributed cost remains unknown.
- P06 cases V22–V25, V29, and V30 pass; V13 covers the new events and exports.

## File ownership

Proposed new files are implementation destinations, not existing capabilities.

| Area | Owner | Typical files |
| --- | --- | --- |
| Delivery backend | P01 | New `backend/app/api/v1/factory.py`, `backend/app/models/factory_schemas.py`, `backend/app/services/factory_projection_service.py`, shared `github_work_item_projection.py`, `backend/tests/factory/` |
| Delivery frontend | P02 | New `frontend/src/features/factory/`, `frontend/src/features/native-settings/surfaceRegistry.tsx`, `frontend/src/types/factory.ts`, initial `features/harnesses/`, shared frontend test utilities |
| Provider operations | P03 after checkpoint | New `provider_operations_service.py`, provider operation API/types, extensions to `frontend/src/features/harnesses/`, provider tests |
| Team deletion prerequisite | Named M0 or post-G00 implementer, coordinated separately | Existing team delete API/service and state/concurrency tests |
| Setup and roles | P04 | New `team_authority_service.py`, `frontend/src/features/repository-setup/`, explicit-role tests |
| Audit and metrics | P05 | New `factory_audit_service.py`, `factory_metrics_service.py`, event schema/tests, audit/metric frontend components |
| Release docs and validation | P06 | `README.md`, current user guides/features/API docs, documentation navigation, acceptance and operator-pilot evidence |

Shared files need sequential integration:

- Land any carried deletion prerequisite with coordinated ownership before overlapping edits; then P01 owns the projection extraction from `backend/app/api/v1/agent_teams.py`.
- P03 owns the first readiness extraction from `agent_team_service.py`.
- P04 modifies these services after rebasing on those changes.
- P04 owns the first changes to `backend/app/database.py` and `models/database.py`; P05 follows.
- P02 owns `frontend/src/App.tsx`, the layout, configuration route boundaries, and the thin Harnesses components during M1a.
- After the checkpoint, P03 owns provider types, native surface metadata, and Harnesses components. The coordinator assigns any adapter/route integration edits sequentially against P02's completed registry. P04 owns team authority types in M2.
- P05 adds its factory routes and screen integrations after the earlier packages.
- The coordinator registers new backend routers and final frontend route integrations when another package's exported module is required.

Do not run agents with concurrent write ownership of these files. After G00, P01/P02 source preparation and fixture-based UI work can proceed in parallel. P03 remains after the checkpoint.

## Required validation

Use `product-heavy` for every full suite, browser fixture or production build; exit 75 means wait for the shared lock. Each agent runs focused tests for its behavior and the affected existing regressions. Backend examples assume the project's test interpreter is active:

```bash
cd backend
python -m pytest tests/factory -q
```

Frontend implementation checks use the scripts present on the reference branch:

```bash
cd frontend
npm run test
npm run lint
npm run build
```

P03 changes to the Pi extension also require that integration's typecheck, tests, and generated-manifest check. Do not edit the extension merely to add metadata.

The coordinator runs the affected combined suites once per merged milestone. Repeat checks when an integration change or failure warrants it. Broad runtime tests against the running factory are outside the isolated implementation checks.

P06 separately runs the operator-task protocol in its handoff. Functional acceptance, internal usability observations, independent operator evidence, and an observed first-reviewable-PR time are different evidence. Record participants and implementer involvement, task/environment identity, measurements, coverage, and the operator's checkpoint disposition recorded by the coordinator. Do not infer general user benefit from green tests or a maintainer's self-measurement.

## Review and handoff format

Each PR describes the concrete user behavior, the API or authority contract it affects, preserved compatibility, and relevant validation. Include the autonomy merge evidence, product integration base SHA, changed paths, acceptance case IDs, commands and results, and remaining limitations.

Screenshots and browser observations identify their fixture or deployed environment. Do not describe fixture behavior as a live production result.

The completing agent hands back:

```text
Package:
Autonomy merge evidence:
Product integration base and PR or commit:
Delivered behavior:
Changed paths:
Acceptance cases and checks:
Compatibility or migration evidence:
Known limitations:
Next dependent package:
```

## Decisions deferred from implementation

The core milestones do not depend on a brand rename, broader organizational audience, board layout, conversational assistant, new backlog integration, provider replacement automation, financial budgets, cookie login, cross-scope dispatch arbitration, or a terminal-abandon state. No timestamp listener or slot-position uniqueness migration is required without evidence of a problem. Keep these options out of the first package's scope.
