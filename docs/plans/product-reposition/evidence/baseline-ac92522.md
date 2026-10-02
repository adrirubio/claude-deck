# P06 existing-interface baseline — fork #11

Recorded 2026-10-02 by B4 Product Validation (Agent Mail member 5, preset 1,
slot 4). Source/controller pin: `ac9252242fcf436c3ea9997add5d32416cad2cd1`.
Artifact branch: `product/validation-bootstrap`; intended PR base:
`feature/software-delivery-product-reposition` on `juanrubio/claude-deck`.

This is an objective source and isolated DOM-fixture baseline before product UI
changes. It is not a human task trial, browser visual review, V31/V32 acceptance,
milestone acceptance, or a pilot/promotion decision. No feature code was changed.
The user authorized this prerequisite on 2026-10-02. B1 reconciled API status:
no dispatched work item/workspace superseded the standing validation assignment
(Mail answer 10, acknowledged). No implementation lease was claimed.

## Environment and provenance

- The validation checkout was clean at the source pin before capture.
- Test run began 2026-10-02 00:35:41 UTC (runner displayed 01:35:41 Canary time).
  Source inventory was captured during 00:33–00:37 UTC.
- Node v24.19.0; Vitest 3.2.7; jsdom 26.1.0; React 19.2.7;
  Testing Library React 16.3.3. These are actual installed versions.
- An initial `npm ci --ignore-scripts --no-audit --no-fund` failed with ENOENT
  for the unavailable default cache `/home/deckproduct/.npm`, following tarball
  warnings. It was not counted as a successful install or test.
- Tests used a local copy of the pinned controller's installed frontend
  dependencies. The operator separately confirmed providing these dependencies.
  Controller and checkout lockfiles both hash to
  `e586c653fde550fb8d52f22dfd5d59c4f5c6970d34ab449080561729c2c6cb91` (SHA-256).
  The lock declares Vitest 3.2.4 while installed Vitest reports 3.2.7; this was
  not a clean lockfile-reproduction run. No lockfile was changed.
- Existing tests mock the team/provider APIs and use synthetic fixture data and
  credentials. No live controller requests, real credentials, agent launches,
  terminal input, dispatches, approvals or workspace claims were part of the tests.
- No backend fixture server or real browser was started. Controller code was
  read-only. The shared heavy-operation lock wrapped the fixture command.

## Current task workflows

Paths and lines refer to the exact source pin, not future implementation files.
Navigation sequences below are source-derived task scripts, not counted human
clicks or measured completion times. A sequence may require choosing a team if
the first selected preset is not the intended one.

| Pilot task | Existing workflow and objective limitation | Evidence at source pin |
| --- | --- | --- |
| Return to mixed-team workload | Open **Agent Teams**, select the intended team, then **Autonomy** and **Activity**. Read status/phase/owner, filter the fetched rows by repository/status, and open details for context. Repeat team selection for another team. Homepage is the provider-oriented Dashboard; there is no instance-wide Work route. Configuration enablement, authentication/poll hints and the recovery gate are visible, but the planned complete effective-intake/scheduler projection is absent. | `frontend/src/App.tsx:40`; `components/layout/Sidebar.tsx:57`; `features/agent-teams/AgentTeamsPage.tsx:753,861,1358`; `AutonomyPanel.tsx:253,1275,1625` |
| Inspect older work and recover context | Activity requests the selected team's latest 50 items, then filters that subset locally. The API supports a limit up to 200, but the UI supplies its default 50 and has no cursor/Load more. An item outside that fetched set cannot be reached through Activity pagination. Visible-tab refresh replaces the team list every five seconds; there is no older-page browsing state to preserve. Details follow a local item ID, rather than a shareable `/work/:id` route. | `features/agent-teams/api.ts:220`; `AgentTeamsPage.tsx:861,929`; `AutonomyPanel.tsx:1275,1284`; `backend/app/api/v1/agent_teams.py:2245` |
| Recover an offline actor | Identify the intended actor from existing team/work context; return to that team's **Roster** and use the individual slot launch button. It calls `openPlan([slot.id])`; the team **Plan launch** button instead passes all slots. The browser requests the per-tab operator credential before the plan request and requires a separate launch confirmation. The planned stable offline-actor deep link is absent. Actual identity correctness and successful live launch were not observed. | `features/agent-teams/AgentTeamsPage.tsx:1174,1379,1471`; `operatorAuth.ts:1`; `tests/agent-teams-plan-token.test.tsx` |
| Continue configuration-only work | Existing Dashboard, provider selector and provider-specific sidebar entries remain the entry points, with Config at `/config`. There is no `/harnesses` route. Config explicitly branches to Codex endpoints for Codex; other selections must not be assumed to have independent native editors merely from capability flags. The planned checked-in adapter guard is future P02 work, not a passed baseline property. | `App.tsx:40`; `components/layout/Sidebar.tsx:94`; `features/dashboard/DashboardPage.tsx:25`; `features/config/ConfigViewerPage.tsx:36,75` |
| Establish repository using existing team | Select team → **Autonomy** → **Add watched repo**; enter repository, checkout/base, labels and policies; save through the shared operator-token helper. Launch planning is separately available in Roster. The existing new-scope form defaults `enabled: true`; P04's disabled-save guarantee and complete access/label/host/overlap preflight must not be attributed to this baseline. Existing scope edits send changed fields only. No real scope was saved in this capture. | `features/agent-teams/AutonomyPanel.tsx:79,95,407,428,1456`; `AgentTeamsPage.tsx:1062`; `tests/autonomy-panel.test.tsx` |
| Reach first reviewable PR | Unavailable: no actual setup-to-reviewable-PR pilot was performed. Neither a source walkthrough nor fixture runtime supplies a delivery-duration measurement. | No live observation |

`frontend/src/` prefixes omitted within repeated frontend path cells above.
Source hashes and structured result availability are recorded in
`baseline-ac92522.json`.

## Fixture result

From `frontend/`:

```sh
product-heavy npm run test -- tests/autonomy-panel.test.tsx tests/agent-teams-plan-token.test.tsx tests/agent-teams-help-dialog.test.tsx --maxWorkers=1 --no-file-parallelism --reporter=verbose
```

Result: exit 0, **20 tests passed in 3 files**, runner duration 5.61 seconds.
That duration is test execution time, not operator task time.

- AutonomyPanel: 17 passing cases cover authentication/poll distinctions,
  recovery-gate visibility/error/change handling, keyboard-accessible status
  explanations, escalated revision wording, setup/build hints, protected history
  prompts/rejection/refresh, pending authentication failures, changed-field-only
  scope edits, token Enter submission, removal confirmation and queued retry wording.
- AgentTeams launch authorization: 2 passing cases cover requesting the token
  before planning and hiding the plan while re-prompting after rejection.
- Team help dialog: 1 passing case checks its autonomy-guide link.
- Existing Radix warnings report missing dialog Description/aria-describedby in
  the launch and help cases. These were not fixed or treated as accessibility passes.

These are existing regression observations, not a full mixed-provider fixture,
server-authorization test, end-to-end scenario, or proof of all pilot tasks.
No full suite, production build, or repeated test run was needed for these
documentation-only artifacts.

## Unavailable observations and comparison protocol

Human participants: **0 observed**. Human operator experience and implementation
involvement: unavailable because no human task run was supplied. B4 is the agent
capturing source/fixture evidence; the operator's dependency provisioning is not
participation in a UI trial. Independent operators: unavailable, none observed.

Per-task human completion/correctness, elapsed time, navigation count, errors,
credential prompt count and intervention count: **unavailable**. Provider mix in
an observed operator run: unavailable. The launch fixture uses a synthetic Codex
slot; it does not establish a complete mixed-harness run. Browser screenshots,
360/768/1280 viewport behavior, light/dark rendering and real browser focus/scroll
observations: unavailable in this capture. Live first-PR time, benefit, delivery
reliability, external demand and adoption: unavailable.

Before collecting after-results, retain the six task scripts above and identify
the exact baseline/after SHA, synthetic fixture or authorized environment,
participant provenance and starting state. Compare correctness, reachable
information, navigation and prompt observations first; record actual per-run
timings/counts only when observed. For older-work comparison, use more than 100
items and an identified target beyond row 50, and record the current UI's lack
of pagination rather than fabricating baseline completion. Verify exact actor
and slot, no launch on navigation, provider-safe configuration access, and scope
preservation/disabled saving at their respective milestones. Do not set numerical
benefit targets from fixture duration or infer improvement from missing samples.

V31 and V32 remain unavailable/pending; the operator owns pilot disposition and
promotion. B1 must obtain independent review of these B4-authored artifacts and
record the baseline prerequisite disposition. B4 does not approve its own baseline.
