# Delivery interface implementation handoff

**Execution baseline, 2026-10-02:** G00 passed through upstream PR #399 / `ac9252242fcf436c3ea9997add5d32416cad2cd1`. Product work starts first in the fork `juanrubio/claude-deck`, from and targeting `feature/software-delivery-product-reposition`. Follow the agent deployment plan and startup gates. Earlier release snapshots and M0 readiness tables are historical evidence; this decision supersedes their pending-G00 or master-target instructions.

Implement **P02 in M1a**: replace the configuration-oriented homepage with delivery observation, make work details shareable, and preserve native configuration through a thin Harnesses index and verified adapters.

Read the [experience specification](../experience-spec.md) and [architecture contracts](../architecture-contracts.md). Use the P01 response fixtures as the interface contract.

## Start conditions

G00 is complete. Start P02 only after exact-head packet acceptance and independently reviewed P06 baseline, including fixture-based screen development. Branch from updated `feature/software-delivery-product-reposition` and record the autonomy merge evidence and base SHA.

After G00, develop screens against P01 fixtures while its backend implementation proceeds. Integrate the real API before milestone acceptance. Own the initial Harnesses index; P03 extends it only after the pilot checkpoint. M1a must not depend on the new operations/readiness/catalog API.

The baseline branch already contains useful status explanations, recovery remedies, instance identity, Bridge team lanes, and Mail. Reuse their behavior instead of replacing their underlying models.

## Source files

- `frontend/src/App.tsx`, `components/layout/Sidebar.tsx`, and `Header.tsx`.
- `frontend/src/contexts/ProviderContext.tsx`, `ProjectContext.tsx`, and `DashboardContext.tsx`.
- `frontend/src/features/dashboard/DashboardPage.tsx`.
- `frontend/src/features/agent-teams/AgentTeamsPage.tsx` and `AutonomyPanel.tsx`.
- `frontend/src/features/agent-teams/api.ts` and `operatorAuth.ts`.
- `frontend/src/features/cc-bridge/CCBridgePage.tsx`, `types.ts`, and terminal/session components.
- `frontend/src/features/agent-mail/AgentMailPage.tsx`, `ThreadDialog.tsx`, and browser API clients.
- `frontend/src/lib/api.ts` and existing frontend tests.

## Write scope

Own new `frontend/src/features/factory/`, the initial `frontend/src/features/harnesses/`, `frontend/src/features/native-settings/surfaceRegistry.tsx`, `frontend/src/types/factory.ts`, shared frontend test utilities, factory/native-route tests, M1a route/layout changes, and Bridge/Mail/launch-plan context-link consumption.

Freeze the M1a adapter fixtures from implemented surfaces. Hand Harnesses component ownership to P03 after acceptance and the checkpoint; P03 adds operation types, readiness, and `native_surfaces` metadata in M1b. The coordinator schedules later catalog/route integration against your completed registry. Export shared context components deliberately.

## Implementation steps

1. Establish shared fetch fixtures, a router wrapper, fake timers, and visibility helpers using the existing Vitest/Testing Library pattern. Add navigation, compatibility aliases, and a thin all-provider Harnesses index backed by existing registry/status reads.
2. Make factory filters URL-backed and independent of the legacy provider/project preference.
3. Add explicit provider/surface/adapter mappings to components and read/write API actions. In M1a, gate mounting on the checked-in adapters and their access levels, with route provider context ready before any request. Keep the later catalog intersection bounded to M1b.
4. Implement Overview, Work, repository summaries/details, and all loading/error/empty states against P01 fixtures. Show configuration enablement separately from effective intake and runtime mode.
5. Wire complete-set counts and cursor pagination to the backend. Share requests and prevent stale responses from replacing newer filters. Pause list polling when Load more starts; preserve accumulated rows, cursor, focus, and scroll until explicit Refresh from start or a filter change.
6. Add `/work/:workItemId`, including phase, waiting actor, safe policy, PR, and verified associations.
7. Extract reusable recovery presentation from `AutonomyPanel.tsx` where useful. Keep protected history and operator credential handling intact.
8. Add stable links to `/teams/:teamId`, the correct repository scope, read-only Bridge context, and relevant Mail context. A verified offline owner/Leader links to a current launch plan with that slot selected; opening it never launches or approves work.
9. Keep the existing dashboard available as a guarded native configuration summary, prominently linked through Harnesses when no scopes exist. Show same-label overlap warnings on repositories.
10. Connect eligible existing remedies only after the server authorization prerequisite is satisfied.

Do not infer native page support through `!isCodex` or a positive capability flag. Capability metadata can describe CLI or Agent Mail functionality without a native page. Use the checked-in adapter guard for links, legacy routes, canonical routes, and native dashboard cards. OpenCode config/plugins/usage must remain unavailable as pages unless dedicated adapters exist; they must never mount Claude editors. Read-only surfaces expose no writes.

## State and action requirements

Basic detail loading does not require an operator token. Protected history asks for the existing per-tab operator credential only when requested. Reuse the established credential helper and explicit header contract.

Verify launch/retry client signatures against the recorded autonomy baseline and current fork integration tip. Browser actions use operator credentials while the server preserves legitimate constrained agent paths. Do not introduce another token store or cookie login. Record credential prompts and interruptions in the pilot.

Agent decisions, operator remedies, and human PR review remain distinct. A pending Leader request gets a waiting state and context link; it never becomes a browser approval action.

“Pause automation” describes scheduler effects and the possibility of continuing agent processes. Do not add an unimplemented “stop factory” button.

Recovery-only mode blocks normal intake for every enabled scope. Show the safe mode and reason without requesting protected target details. A stopped or unknown scheduler must not appear as normal intake, and intentionally suspended polling must not look like an unexplained refresh failure.

The Finished category describes terminal tracking. A `completed` issue without result evidence displays delivery/human review as unconfirmed; M3 supplies the separate outcome presentation.

Use **Escalate attempt** for the existing abandon action. Explain **Operator requested stop**, attention status, possible retry, and the lack of guaranteed process termination. A successful route response must not move the item into Finished. Deletion controls need the coordinator's in-use-state guard, with actionable conflict messages.

For Bridge links, a verified single target may be opened read-only. Ambiguous bindings only filter the available team/slot sessions. No navigation sends terminal input, restarts a session, or invokes an owner tool.

## Acceptance criteria

The relevant P06 cases are V01–V04, V07–V16 at M1a scope, V26, V27, V34, and the M1a UI of V36. Coordinate deletion-conflict presentation for V33. Supply the integrated fixture UI for P06's V31 comparison before P03 starts; V05/V06 belong to M1b.

- Native provider/project preferences cannot hide mixed-harness delivery work.
- Counts, category links, filters, browser history, and list pagination agree.
- Multiple automatic refresh intervals, an older first-page response, and tab hide/show cannot reset browsing after Load more.
- Configured enablement, effective intake, runtime mode, and poll freshness retain their distinct meaning.
- Stale refresh data remains labelled and readable; a failed API is not shown as an empty factory.
- Work details and selected Teams/repositories survive reload and are shareable.
- Legacy native routes and manual session use remain accessible.
- An empty factory prominently links configuration-only users to Harnesses and the correctly guarded native summary.
- Offline-actor launch links preserve the selected team/slot and require authenticated plan review without automatic launch.
- Missing native adapters explain their page limit without Claude fallthrough, including providers with positive integration capability flags.
- All actions preserve current backend eligibility, actor, and authorization requirements.
- Keyboard and narrow-layout behavior meet the experience specification.

## Validation

Use Vitest and Testing Library with API fixtures. Start with the existing Autonomy panel test pattern and land the shared router/fetch/timer utilities in P02a; the current frontend suite is small, so this work is part of the package estimate. Test user-visible behavior, authority boundaries, routing, and stale-response handling.

```bash
cd frontend
npm run test
npm run lint
npm run build
```

Add tests for route selection before requests, positive capability flags without native adapters, read-only action denial, mixed providers, stale filter responses, failed refresh, unknown status, multiple pages, operator-token denial, offline/ambiguous session links, and the configuration-only empty state. Exercise V26 and V27 with more than 100 rows across several polling intervals, including an action/detail refresh while the list is paused. Verify that M1a never calls the absent P03 endpoint.

Perform browser checks using an isolated fixture server at 360px, 768px, and 1280px. Record the backend fixture and commit used for screenshots. Do not use the running factory to simulate clicks or interventions.

## Delivery evidence

Report routes and aliases, affected compatibility entries, API fixtures consumed, test results, keyboard/layout observations, screenshots, and any mutation controls deferred pending guard coverage.

## Agent start instruction

> Start P02 for M1a after accepted packet reconciliation and independently reviewed P06 baseline, including fixture-based development; consume the acknowledged exact P01 fixture version. Branch from updated `feature/software-delivery-product-reposition`. Build delivery views, a thin Harnesses index, and static native adapter guards without a P03 dependency. Preserve authority, nonterminal escalation, safe context links, and older-page browsing. Provide functional/browser evidence and the pilot UI before handing Harnesses ownership to P03.
