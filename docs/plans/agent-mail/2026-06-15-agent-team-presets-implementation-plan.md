# Agent Team Presets Implementation Plan

Date: 2026-06-15
Issue: https://github.com/adrirubio/claude-deck/issues/189
Branch: `feat/agent-team-presets-189`

## Purpose

Agent Team Presets let a Claude Deck user save reusable agent rosters such as `DevOps`, `Project A`, or `Project B`, then launch the needed Claude Code and Codex sessions with one action.

This feature should be a practical orchestration layer over existing systems:

- Agent Bridge owns tmux session discovery, terminal access, and provider-specific spawning.
- Agent Mail owns local agent identity, inboxes, roles, charters, context requests, and handoffs.
- Agent Team Presets own desired rosters, launch planning, and per-team slot context.

The feature should not introduce a second messaging model. It should make it easier to create the right local team, then continue using Agent Mail for communication.

## Product Principles

1. **Launch useful teams, not gimmicks.** A preset is valuable only if it reliably brings up the right agents with the right repository and operating context.
2. **Prefer reconciliation over blind spawning.** Deck should inspect live sessions and reuse matching agents before creating new tmux sessions.
3. **Keep global repo identity stable.** Agent Mail currently models one durable member per repo. Team presets must not overwrite global member role/charter every time a preset launches.
4. **Make launch state inspectable.** The user should see which slots are already running, which will be spawned, which are pending registration, and which failed.
5. **Stay provider-aware.** Claude Code and Codex launch options differ. The preset model should store common slot intent plus provider-specific launch options.
6. **Do not hide setup prerequisites.** If Agent Mail MCP/hooks are missing for a provider, the launch plan should say so before spawning.

## Supported Use Cases

### UC1: Save A Project Team

The user creates a `Project A` team with slots:

- `Backend owner`: Codex in `/repos/project-a-api`
- `Frontend owner`: Claude Code in `/repos/project-a-web`
- `DevOps`: Codex in `/repos/project-a-infra`

The user can later launch this team from Deck and get the same structure back.

Supported in v1:

- create/edit/delete preset
- create/edit/delete/reorder slots
- store provider, repo path, role, charter, launch mode, and provider options
- launch all enabled slots

### UC2: Reuse Already-Running Agents

The user already has a Codex tmux session running in `/repos/project-a-api`. Launching `Project A` should mark the backend slot as reused instead of spawning another backend session.

Supported in v1:

- compare desired slot provider + repo path against Agent Bridge tmux discovery
- show `Reused` in launch plan/result
- avoid duplicate sessions by default

Deferred:

- fuzzy matching across moved/renamed repositories beyond normalized repo root/path
- attaching a team slot to a non-tmux session that cannot be observed

### UC3: Spawn Missing Agents

The user launches `Project A`; the frontend slot is missing. Deck starts a new tmux session using the existing Agent Bridge spawn service.

Supported in v1:

- spawn missing slots through `spawn_session`
- pass provider-specific options through the existing `SpawnCommandOptions`
- return per-slot result instead of failing the entire launch when one slot fails

### UC4: Bootstrap Agents Into The Correct Team Context

When a launched agent starts, it should understand the team and slot it belongs to.

Supported in v1:

- spawn sessions with environment variables:
  - `CLAUDE_DECK_TEAM_PRESET_ID`
  - `CLAUDE_DECK_TEAM_SLOT_ID`
- include a bootstrap prompt when possible:
  - "You are joining Claude Deck team Project A as Backend owner. Call `deck_whoami`, then wait for direction."
- have MCP/hook registration forward team env values to Agent Mail session metadata
- have Agent Mail context include slot role/charter when the active session has a slot

### UC5: Create A Preset From Current Agent Mail Roster

The user has a useful set of currently registered Agent Mail members and wants to save it as a preset.

Supported in v1:

- `Create from current roster`
- each selected Agent Mail member becomes one slot
- default provider inferred from best live session when possible
- default role/charter copied from the current member values into slot role/charter

Important behavior:

- copying member role/charter into slot role/charter is a snapshot, not a live binding
- later editing the preset does not mutate global Agent Mail member role/charter

### UC6: DevOps Or Cross-Project Team

The user defines a team whose repos are loosely related, such as `DevOps` with infrastructure, deployment, monitoring, and app repos.

Supported in v1:

- slots can point to arbitrary local repo paths
- slots do not need to share a common parent project
- Agent Mail can still route between the resulting repo members

### UC7: Edit Team Roster Without Launching

The user can maintain a preset as a durable roster without spawning anything yet.

Supported in v1:

- create/edit/delete slots without side effects
- disabled slots stay in the preset but are excluded from launch by default
- validation errors are shown inline

### UC8: Inspect Launch Outcome

After launching, the user should know what happened.

Supported in v1:

- launch result includes one item per slot
- item states:
  - `reused`
  - `spawned`
  - `pending_registration`
  - `failed`
  - `skipped_disabled`
  - `blocked_provider_unavailable`
  - `blocked_agent_mail_not_configured`
- result includes tmux target/session name when available
- result includes error message when failed

### UC9: Launch A Single Slot

The user wants only the DevOps slot, not the whole team.

Supported in v1:

- per-slot launch action uses the same launch planner and result model
- still reuses matching live sessions by default

## Explicitly Unsupported Or Deferred Use Cases

### Multiple Independently Addressable Agents In The Same Repo

Agent Mail currently uses one durable member per repo, so multiple sessions in the same repo share one inbox and identity.

V1 stance:

- allow at most one enabled slot per normalized repo path in a preset by default
- if later allowed, the UI must warn that same-repo slots share an Agent Mail inbox

Deferred:

- multi-member-per-repo Agent Mail identities
- addressing a message to a specific same-repo session/slot

### Non-Tmux Wakeability

Team presets should not solve non-tmux wakeability.

V1 stance:

- launching creates tmux sessions through Agent Bridge
- reuse only counts observable tmux sessions for wakeable launch state
- non-tmux sessions may still register through MCP, but are not reliable launch/reuse targets

### Cross-Machine Teams

V1 is local-machine only.

Deferred:

- remote hosts
- distributed Deck instances
- cloud-hosted agent teams

### Autonomous Scheduling

V1 is manually launched from Deck.

Deferred:

- scheduled team launch
- recurring maintenance runs
- automatic launch based on GitHub events

### Full Team Lifecycle Management

V1 focuses on launch and visibility.

Deferred unless cheap:

- stop all sessions for team
- restart all sessions
- cleanup worktrees
- preserve launch history indefinitely

## Current Codebase Facts

Agent Bridge already provides:

- `backend/app/services/agent_bridge/spawn.py`
  - validates directories
  - spawns tmux sessions
  - delegates command construction to provider modules
- `backend/app/api/v1/agent_bridge/router.py`
  - `POST /api/v1/agent-bridge/sessions`
  - `GET /api/v1/agent-bridge/sessions`
- provider launch options in `SpawnCommandOptions`
- provider implementations:
  - `ClaudeCodeProvider`
  - `CodexCliProvider`

Agent Mail already provides:

- durable `MailTeamMember`, keyed by repo identity
- ephemeral `MailAgentSession`
- member role/charter editing
- MCP/hook registration
- tmux wakeability for observed Codex sessions
- context injection through `build_session_start_context` and prompt submit context

Gaps:

- no saved roster model
- no launch planning or reconciliation
- no per-team/per-slot context overlay
- no UI for saved teams
- no durable launch result model

## Proposed Architecture

Add a new feature area named `agent-teams`.

Backend modules:

- `backend/app/services/agent_team_service.py`
- `backend/app/api/v1/agent_teams.py`
- schema additions in `backend/app/models/schemas.py`
- database models in `backend/app/models/database.py`

Frontend modules:

- `frontend/src/features/agent-teams/AgentTeamsPage.tsx`
- `frontend/src/features/agent-teams/api.ts`
- `frontend/src/features/agent-teams/types.ts`
- supporting components:
  - `PresetList`
  - `PresetEditor`
  - `SlotEditor`
  - `LaunchPlanDialog`
  - `LaunchResultPanel`

Navigation:

- Add `Agent Teams` under Operations, near Agent Mail.
- Keep Agent Mail focused on communication.

## Data Model

### `agent_team_presets`

Fields:

- `id`
- `name`
- `description`
- `is_archived`
- `created_at`
- `updated_at`

Notes:

- `name` should be unique among non-archived presets.
- hard delete is acceptable for v1 if no launch history references it; otherwise use archive.

### `agent_team_slots`

Fields:

- `id`
- `preset_id`
- `position`
- `enabled`
- `display_name`
- `provider`
- `repo_path`
- `repo_id`
- `repo_name`
- `role`
- `charter`
- `launch_mode`
- `launch_options` JSON
- `bootstrap_prompt`
- `created_at`
- `updated_at`

`launch_options` should store provider-specific options already supported by Agent Bridge:

- Claude Code:
  - `mode`
  - `worktree_name`
  - `skip_permissions`
  - `platform`
  - `aws_region`
  - `aws_profile`
  - `bedrock_model`
- Codex:
  - `mode`
  - `model`
  - `profile`
  - `profile_v2`
  - `sandbox`
  - `approval_policy`
  - `search`
  - `no_alt_screen`
  - `dangerously_bypass_approvals_and_sandbox`
  - `use_last`
  - `session_id`

Validation:

- `repo_path` must be absolute and exist at save time.
- derive `repo_id`/`repo_name` using existing repo identity helper.
- provider must be known.
- launch mode must be supported by provider.
- v1 should reject duplicate enabled slots with the same `repo_id` inside one preset.

### `agent_team_launches`

Fields:

- `id`
- `preset_id`
- `status`
- `started_at`
- `finished_at`
- `summary` JSON

Launch status:

- `planning`
- `running`
- `completed`
- `partial_failure`
- `failed`

### `agent_team_launch_items`

Fields:

- `id`
- `launch_id`
- `slot_id`
- `status`
- `provider`
- `repo_path`
- `tmux_target`
- `session_name`
- `message`
- `error`
- `started_at`
- `finished_at`

This table can be optional for v1 if the implementation returns transient launch results. Prefer adding it if it is not too much overhead because it makes support and UI easier.

### `mail_agent_sessions` Extension

Add optional fields:

- `team_preset_id`
- `team_slot_id`

These fields describe the team context of a particular session. They do not change the durable repo member identity.

## Backend API

### Presets CRUD

- `GET /api/v1/agent-teams/presets`
- `POST /api/v1/agent-teams/presets`
- `GET /api/v1/agent-teams/presets/{preset_id}`
- `PATCH /api/v1/agent-teams/presets/{preset_id}`
- `DELETE /api/v1/agent-teams/presets/{preset_id}`
- `POST /api/v1/agent-teams/presets/{preset_id}/duplicate`

### Slots

Either nest slots inside preset update payloads or provide explicit endpoints:

- `POST /api/v1/agent-teams/presets/{preset_id}/slots`
- `PATCH /api/v1/agent-teams/slots/{slot_id}`
- `DELETE /api/v1/agent-teams/slots/{slot_id}`
- `POST /api/v1/agent-teams/presets/{preset_id}/slots/reorder`

For v1, nested updates are simpler only if the editor saves the whole preset at once. Explicit endpoints are better for incremental UI and validation.

### Create From Agent Mail

- `POST /api/v1/agent-teams/presets/from-agent-mail`

Request:

- `name`
- optional `member_ids`
- optional `include_offline`

Behavior:

- read current Agent Mail members
- choose provider from newest connected/observed session if possible
- copy current member role/charter into slot role/charter
- set launch mode to provider default

### Launch Planning

- `POST /api/v1/agent-teams/presets/{preset_id}/plan-launch`

Request options:

- `slot_ids`
- `reuse_existing: true`
- `include_disabled: false`

Response per slot:

- desired provider/repo/role
- current state
- planned action:
  - `reuse`
  - `spawn`
  - `skip_disabled`
  - `blocked`
- reason
- matching live session, if any

The frontend should show this before launching a full preset.

### Launch

- `POST /api/v1/agent-teams/presets/{preset_id}/launch`

Request options:

- `slot_ids`
- `reuse_existing: true`
- `include_disabled: false`
- `confirm_plan_hash`

Behavior:

- recompute plan server-side
- if `confirm_plan_hash` is provided and no longer matches, return 409 with updated plan
- spawn missing slots
- return launch result

Do not make launch long-running in v1. Spawning tmux sessions should be quick. Registration can remain `pending_registration` and be refreshed by UI polling.

## Launch Planning Logic

For each enabled slot:

1. Validate provider availability.
2. Validate Agent Mail install readiness for that provider:
   - Claude Code: MCP installed, hooks installed if context injection is expected
   - Codex: MCP installed, hooks installed for prompt-boundary reminders
3. Discover tmux sessions through Agent Bridge.
4. Match live sessions by:
   - provider equality
   - normalized cwd/repo root matching slot `repo_path`/`repo_id`
5. If match exists and `reuse_existing`, plan `reuse`.
6. Otherwise plan `spawn`.

Matching should be conservative. A false positive is worse than a duplicate because it gives the user the wrong agent.

## Spawn Behavior

Add a lower-level helper so team launch can pass env vars into tmux:

- current `spawn_session(provider_id, options)` constructs env flags internally only for platform env
- add optional `extra_env: dict[str, str]` argument or extend `SpawnCommandOptions`

For each spawned slot, pass:

- `CLAUDE_DECK_TEAM_PRESET_ID`
- `CLAUDE_DECK_TEAM_SLOT_ID`
- `CLAUDE_DECK_TEAM_NAME`
- `CLAUDE_DECK_TEAM_SLOT_NAME`

Bootstrap prompt:

- If slot has explicit `bootstrap_prompt`, use it.
- Otherwise synthesize:
  - "You are joining Claude Deck team {team_name} as {slot_display_name}. Call `deck_whoami` now, review your Agent Mail context, then wait for direction."

Provider-specific placement:

- Codex: append bootstrap prompt as prompt argument for new sessions.
- Claude Code: append bootstrap prompt where current provider supports `prompt`.
- For resume/fork modes, be conservative. Include prompt only if existing provider behavior supports it safely.

## Agent Mail Context Overlay

MCP shim and hook shim should read:

- `CLAUDE_DECK_TEAM_PRESET_ID`
- `CLAUDE_DECK_TEAM_SLOT_ID`

Registration payload additions:

- `team_preset_id`
- `team_slot_id`

Agent Mail service behavior:

- store those values on `MailAgentSession`
- when building context for a session/member, if the active session has a slot:
  - include team name
  - include slot display name
  - include slot role
  - include slot charter
- do not copy slot role/charter into `MailTeamMember.role` or `MailTeamMember.charter`

Context example:

```text
[Claude Deck Agent Mail]
You are "project-a-api" - repo: project-a-api.
Team preset: Project A
Team slot: Backend owner
Slot role: Backend implementation
Slot charter: Own FastAPI, DB, migrations, and API contracts.
```

Open question for implementation:

- Current context builders operate by member id, not specific session id in all paths. The hook path has a session key and can use exact session metadata. The MCP inbox path may only know member id. Prefer preserving exact session metadata in MCP state after registration so context tools can request context for the current session where needed.

## Frontend UX

### Navigation

Add `Agent Teams` under Operations.

Page layout:

- header with `New team`, `Create from Agent Mail`, and `Refresh`
- left/list area for presets
- main detail/editor area for selected preset
- launch summary/status area

### Preset List

Each preset card/row:

- name
- description
- slot count
- last launched summary if available
- buttons:
  - Launch
  - Plan
  - Edit
  - Duplicate
  - Delete/archive

### Preset Editor

Fields:

- name
- description
- slots table/list

Slot controls:

- enabled toggle
- display name
- provider select
- repo path input
- role
- charter
- launch mode
- provider-specific options
- bootstrap prompt

Use dense operational UI, not marketing-style cards. This is a workspace management tool.

### Launch Plan Dialog

Before launch, show table:

- slot
- provider
- repo
- current state
- planned action
- reason

Actions:

- `Launch`
- `Cancel`

If there are blocked slots, allow launching unblocked slots only after the UI makes that explicit.

### Launch Result

After launch:

- show per-slot result
- show tmux target/session name for spawned/reused sessions
- show failures inline
- offer `Open Agent Mail` and `Open Agent Bridge`

Do not auto-switch pages without user action.

## Frontend Types

Add types under `frontend/src/features/agent-teams/types.ts`:

- `AgentTeamPreset`
- `AgentTeamSlot`
- `AgentTeamPresetCreate`
- `AgentTeamPresetUpdate`
- `AgentTeamLaunchPlan`
- `AgentTeamLaunchPlanItem`
- `AgentTeamLaunchResult`
- `AgentTeamLaunchResultItem`

Reuse provider ids and spawn option names from existing Agent Bridge types where practical.

## Implementation Tasks

### Task 1: Backend Models And Schemas

- Add database models.
- Add Pydantic schemas.
- Add lightweight migration handling in `backend/app/database.py` consistent with current project style.
- Add tests for table creation and serialization.

### Task 2: Team Preset CRUD Service

- Implement create/list/get/update/delete/duplicate.
- Validate provider and repo path.
- Derive repo identity.
- Enforce no duplicate enabled repo slots per preset for v1.
- Test validation and CRUD.

### Task 3: Create From Agent Mail

- Add service method that snapshots selected/current members into slots.
- Infer provider from newest live session, falling back to `codex-cli` if Codex is installed or `claude-code` if Claude Code is installed. If neither is clear, require user selection later.
- Test generated slots.

### Task 4: Launch Planner

- Add plan computation using Agent Bridge discovery and Agent Mail install status.
- Match provider + repo conservatively.
- Return per-slot planned action/reason.
- Test reuse, spawn, disabled, provider unavailable, Agent Mail not configured.

### Task 5: Launch Execution

- Extend Agent Bridge spawn helper to accept extra env.
- Implement launch endpoint.
- Recompute plan before launch.
- Spawn missing slots.
- Return partial results.
- Test successful spawn, reuse, and partial failure.

### Task 6: Agent Mail Session Team Context

- Add optional team ids to register payload/session model.
- Update MCP shim and hook shim to forward env values.
- Update Agent Mail context building to include slot context.
- Test registration and context injection.

### Task 7: Frontend Agent Teams Page

- Add route and nav item.
- Implement API client.
- Implement preset list/editor.
- Implement create-from-Agent-Mail action.
- Implement launch plan dialog and launch result panel.
- Add loading/error/empty states.

### Task 8: Documentation

- Add feature doc under `docs/features/`.
- Add short help copy in Agent Teams page.
- Cross-link from Agent Mail help if useful.

### Task 9: Validation

Backend:

- targeted `pytest` for agent teams + agent mail registration changes
- existing Agent Mail tests
- Agent Bridge spawn tests

Frontend:

- targeted eslint for new feature files
- `npm run build`

Manual:

- create preset manually
- create preset from current Agent Mail roster
- plan launch with live matching session
- launch missing Codex slot
- launch missing Claude Code slot if available
- verify Agent Mail context includes team slot
- verify second launch reuses sessions

## Testing Plan

Backend test files:

- `backend/tests/agent_teams/test_models.py`
- `backend/tests/agent_teams/test_api.py`
- `backend/tests/agent_teams/test_service.py`
- extend:
  - `backend/tests/agent_mail/test_mcp_shim.py`
  - `backend/tests/agent_mail/test_hooks_api.py`
  - `backend/tests/test_agent_bridge_spawn.py`

Key cases:

- CRUD round trip.
- Duplicate enabled repo slot rejected.
- Disabled duplicate allowed or rejected explicitly; choose one and test.
- Create from current Agent Mail members.
- Launch plan reuses live tmux session.
- Launch plan chooses spawn when no match exists.
- Launch plan blocks unavailable provider.
- Launch execution spawns with team env.
- Launch execution returns partial failure when one slot fails.
- MCP shim forwards team env on registration.
- Hook shim forwards team env on registration.
- Agent Mail context includes slot role/charter.
- Global MailTeamMember role/charter are not overwritten by launch.

Frontend:

- Keep tests lightweight if there is no established frontend test harness.
- Rely on TypeScript build and targeted lint.
- Consider component smoke tests only if local patterns exist.

## Risks And Mitigations

### Risk: Confusing Team Slot With Agent Mail Member

Mitigation:

- UI labels must distinguish repo member from team slot.
- Do not display slot role as if it were global member role.

### Risk: Duplicate Sessions

Mitigation:

- launch plan defaults to reuse
- conservative matching by provider + repo root
- require explicit user action to spawn anyway later

### Risk: Same Repo Multi-Agent Expectations

Mitigation:

- reject duplicate enabled repo slots in v1
- document that Agent Mail is one member per repo

### Risk: Provider Options Become Too Complex

Mitigation:

- reuse Agent Bridge option names
- show provider-specific advanced options behind compact sections
- keep default options simple

### Risk: Registration Race

Mitigation:

- launch returns `spawned` first
- UI polls Agent Mail and updates to connected/pending registration
- do not block launch endpoint waiting for MCP check-in

### Risk: Bad Paths Or Unsafe Commands

Mitigation:

- use existing directory validation and provider command builders
- never shell-concatenate user-provided command strings in team service
- keep all spawn execution through Agent Bridge

## Rollout Strategy

1. Ship backend CRUD + launch planner first.
2. Add launch execution and env propagation.
3. Add UI.
4. Validate with Codex tmux sessions first, because current Agent Mail wakeability is strongest there.
5. Validate Claude Code if installed and configured.
6. Open PR with issue #189 linked.

## PR Scope

This is large but still a single coherent PR if kept disciplined:

- new Agent Teams backend service/API
- minimal DB model additions
- Agent Bridge spawn env support
- Agent Mail session team context support
- new Agent Teams frontend page
- docs/tests

Do not include:

- non-tmux remote control
- scheduler
- cross-machine support
- multi-member-per-repo mail identity
- large visual redesign of Agent Mail or Agent Bridge

## Open Questions Before Implementation

1. Should v1 hard-reject duplicate enabled repo slots, or allow them with a shared-inbox warning?
   - Recommendation: hard-reject for v1.
2. Should launch history be persisted?
   - Recommendation: persist lightweight launch/items if implementation stays simple.
3. Should Agent Teams live as its own nav item or inside Agent Mail?
   - Recommendation: own nav item under Operations. It is launch orchestration, not messaging.
4. Should create-from-Agent-Mail include offline members by default?
   - Recommendation: include all selected members, but default selection should favor connected/observed members.
5. Should launch immediately after plan or require a confirmation dialog?
   - Recommendation: require plan confirmation for full team launch; single-slot launch can show a compact confirm.
