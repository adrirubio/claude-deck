# Codex CLI Support Across Claude Deck

**Date:** 2026-05-25  
**Status:** Initial plan for iteration  
**Scope:** Backend provider abstraction, tmux bridge, configuration surfaces, navigation/UI layout, docs, tests

## Goal

Add first-class Codex CLI support to Claude Deck so the app can manage Claude Code and Codex side by side:

- Discover, spawn, attach to, and kill tmux sessions for both CLIs.
- View and edit Codex configuration with parity to the existing Claude Code configuration experience.
- Keep Claude-specific features intact while moving shared concepts into provider-neutral surfaces.
- Rework the left sidebar so the app can grow beyond a single Claude Code toolchain without becoming a long flat menu.

This should make Claude Deck behave like a local agent operations console. Public branding can stay Claude Deck for now, but the internal architecture should become multi-agent.

## Current State

The repo is now up to date with `origin/master` as of 2026-05-25.

Relevant existing surfaces:

- Backend config service: `backend/app/services/config_service.py`
- Claude path helpers: `backend/app/utils/path_utils.py`
- Claude CLI executor: `backend/app/services/cli_executor.py`
- CC Bridge discovery/spawn/relay:
  - `backend/app/services/cc_bridge/discovery.py`
  - `backend/app/services/cc_bridge/spawn.py`
  - `backend/app/services/cc_bridge/pty_relay.py`
  - `backend/app/api/v1/cc_bridge/router.py`
- Frontend config page:
  - `frontend/src/features/config/ConfigViewerPage.tsx`
  - `frontend/src/features/config/settings/SettingsEditor.tsx`
  - `frontend/src/features/config/settings/cards/*`
- Frontend bridge page:
  - `frontend/src/features/cc-bridge/CCBridgePage.tsx`
  - `frontend/src/features/cc-bridge/*`
- Current sidebar: `frontend/src/components/layout/Sidebar.tsx`
- Routes: `frontend/src/App.tsx`
- Header/status: `backend/app/api/v1/status.py`, `frontend/src/components/layout/Header.tsx`

Local Codex CLI snapshot used for this plan:

- Installed binary: `codex-cli 0.133.0`
- Main config file: `~/.codex/config.toml`
- Relevant commands: `codex`, `codex exec`, `codex review`, `codex login/logout`, `codex mcp`, `codex plugin`, `codex doctor`, `codex resume`, `codex fork`
- Important CLI flags: `--model`, `--profile`, `--profile-v2`, `--sandbox`, `--ask-for-approval`, `--search`, `--cd`, `--add-dir`, `--no-alt-screen`, `--strict-config`, `--config key=value`
- Observed config examples: `model`, `model_reasoning_effort`, `[projects."<path>"].trust_level`, `[notice.model_migrations]`, `[tui.model_availability_nux]`

## Product Shape

The target product model:

- **Agents** are provider-backed local CLIs: Claude Code, Codex CLI, later others.
- **Sessions** are tmux panes/windows running one provider.
- **Configuration** is provider-specific, but the app presents shared patterns consistently:
  - user/global config
  - project config
  - profiles
  - permissions/sandbox/trust
  - MCP
  - plugins/skills/extensions where supported
  - diagnostics
- **Bridge** becomes provider-neutral: one terminal/tmux experience with provider filtering.

Avoid building a separate Codex-only duplicate of every Claude page. Use provider-aware building blocks and keep provider-specific cards where the config model genuinely differs.

## Mixed Provider Sessions

Claude Code and Codex sessions should be visible together in the same Agent Bridge.

The backend should run one tmux discovery pass across all panes, classify each matching pane with a provider id, and return a mixed session list. The frontend should default to an **All agents** view and offer provider filters for **Claude Code** and **Codex**.

Example mixed response:

```json
{
  "sessions": [
    { "provider": "claude-code", "tmux_target": "snazzy-1234:0.0", "cwd": "/home/joni/repos/snazzyemail" },
    { "provider": "codex-cli", "tmux_target": "deck-5678:0.0", "cwd": "/home/joni/repos/claude-deck" },
    { "provider": "claude-code", "tmux_target": "sam-9012:0.0", "cwd": "/home/joni/repos/linode-migration" },
    { "provider": "codex-cli", "tmux_target": "stocks-3456:0.0", "cwd": "/home/joni/repos/stocks-dashboard" }
  ]
}
```

In the UI:

- Session cards show a provider badge.
- The bridge grid can display mixed sessions side by side.
- A user can attach to, watch, and interact with Claude Code and Codex panes at the same time.
- Provider-specific behavior is limited to discovery, spawn/resume/fork options, prompt-state handling, and configuration/diagnostics.
- Terminal rendering, WebSocket relay, fullscreen mode, multi-pane layout, and kill/preview mechanics stay shared.

## Architecture Decision

Introduce an `AgentProvider` abstraction in the backend and mirror it in the frontend.

Initial provider ids:

- `claude-code`
- `codex-cli`

Provider metadata should include:

- display name
- binary name
- version command
- config root paths
- supported capabilities
- tmux process detection rules
- spawn command builder
- resume/fork support
- allowed CLI subcommands
- config schema/editor card list

Example capability flags:

```json
{
  "sessions": true,
  "spawn": true,
  "resume": true,
  "fork": true,
  "mcp": true,
  "plugins": true,
  "commands": false,
  "agents": false,
  "skills": false,
  "hooks": false,
  "memory": false,
  "usage": false,
  "context": false,
  "doctor": true
}
```

Claude Code will expose the current richer Claude-specific feature set. Codex starts with tmux, config, MCP, plugins, doctor/status, and project trust.

## Backend Plan

### Phase 1: Provider Registry

Create a small provider layer:

- `backend/app/services/providers/__init__.py`
- `backend/app/services/providers/base.py`
- `backend/app/services/providers/claude_code.py`
- `backend/app/services/providers/codex_cli.py`
- `backend/app/api/v1/providers.py`

Provider interface:

- `id`
- `display_name`
- `binary_name`
- `get_version()`
- `get_status()`
- `get_config_paths(project_path?: str)`
- `get_capabilities()`
- `is_process_match(command: str, pid: str) -> bool`
- `build_spawn_command(request) -> list[str]`
- `get_allowed_cli_commands() -> list[str]`

Expose:

- `GET /api/v1/providers`
- `GET /api/v1/providers/{provider_id}/status`
- `GET /api/v1/status` should eventually return both Claude and Codex versions.

Migration rule: keep the existing `/cc-bridge` and `/config` routes during the transition. New routes can run in parallel until frontend migration is complete.

### Phase 2: Generalize CC Bridge Into Agent Bridge

Keep the relay implementation, but rename the surrounding service concept from `cc_bridge` to `agent_bridge`.

New backend files:

- `backend/app/services/agent_bridge/discovery.py`
- `backend/app/services/agent_bridge/spawn.py`
- `backend/app/services/agent_bridge/pty_relay.py` or re-export existing relay
- `backend/app/api/v1/agent_bridge/router.py`

New endpoints:

- `GET /api/v1/agent-bridge/sessions`
- `GET /api/v1/agent-bridge/sessions?provider=codex-cli`
- `GET /api/v1/agent-bridge/sessions/{target:path}/preview`
- `GET /api/v1/agent-bridge/token`
- `WS /api/v1/agent-bridge/sessions/{target:path}/terminal`
- `POST /api/v1/agent-bridge/sessions`
- `DELETE /api/v1/agent-bridge/sessions/{target}`

Session response should add:

```json
{
  "provider": "codex-cli",
  "provider_display_name": "Codex",
  "tmux_target": "repo-1234:0.0",
  "session_name": "repo-1234",
  "window_name": "main",
  "pane_id": "%1",
  "cwd": "/home/joni/repos/foo",
  "pid": "12345",
  "status": "active"
}
```

Codex detection:

- Match direct pane command `codex`.
- Match node wrapper descendants where argv0 basename is `codex`, mirroring the existing Claude descendant walk.
- Avoid matching `codex-exec-server` or unrelated helper processes unless a real interactive Codex TUI descendant is present.

Claude detection:

- Move the existing `claude` and node-wrapper logic into `ClaudeCodeProvider`.

Spawn behavior:

- Claude Code keeps existing modes: `plain`, `worktree`, `resume`.
- Codex should support:
  - `plain`: `codex --cd <directory>`
  - `resume`: `codex resume <session_id>` or `codex resume --last`, with `--cd <directory>` when applicable
  - `fork`: `codex fork <session_id>` or `codex fork --last`
  - prompt seed: optional initial prompt argument
  - options: `--model`, `--profile`, `--profile-v2`, `--sandbox`, `--ask-for-approval`, `--search`, `--no-alt-screen`, `--dangerously-bypass-approvals-and-sandbox`

Important tmux input rule:

- Preserve and formalize the defensive Enter behavior learned from Claude Code and Codex:
  - paste/send prompt
  - send explicit Enter
  - capture pane
  - if the prompt is still visibly sitting at the prompt, send Enter again
- This belongs in the shared bridge layer, not inside one provider.

### Phase 3: Provider-Aware CLI Executor

Replace `CLIExecutor` with a provider-aware executor:

- `backend/app/services/cli_executor.py` can become `ProviderCLIExecutor`.
- Existing `/cli/execute` can gain a `provider` field or be superseded by `POST /providers/{provider_id}/cli`.

Codex whitelist:

- `doctor`
- `mcp`
- `plugin`
- `features`
- `completion` only if needed later

Do not expose:

- `logout`
- `update`
- `apply`
- `sandbox`
- `exec`
- `review`
- `cloud`

Those can change user state, run commands, or perform broad external actions and should only be added with explicit UX and safety review.

### Phase 4: Codex Configuration Service

Codex uses TOML, not Claude's JSON settings model. Add a separate service rather than forcing it through `ConfigService`.

New files:

- `backend/app/services/codex_config_service.py`
- `backend/app/utils/codex_path_utils.py`
- `backend/app/api/v1/codex_config.py` or provider-scoped config routes

Paths:

- User config: `$CODEX_HOME/config.toml`, defaulting to `~/.codex/config.toml`
- Auth file: `$CODEX_HOME/auth.json`, display status only, never raw content
- History: `$CODEX_HOME/history.jsonl`, future read-only surface
- Models cache: `$CODEX_HOME/models_cache.json`, future read-only surface
- Rules: `$CODEX_HOME/rules/*.rules`
- Profiles v2: `$CODEX_HOME/<name>.config.toml`

Use a TOML parser/writer, not regex editing. Python 3.11+ has `tomllib` for reading only, so add a write-capable TOML dependency if the backend does not already have one. Candidates:

- `tomlkit` preferred because it preserves comments/formatting.
- `tomli-w` acceptable if formatting preservation is not required.

Initial editable Codex config cards:

- General:
  - `model`
  - `model_reasoning_effort`
  - `profile`
  - `profile-v2` references, if present
- Runtime:
  - `sandbox_mode` or equivalent persisted key if present
  - `approval_policy` or equivalent persisted key if present
  - `search`
  - `strict_config`
  - `no_alt_screen`
- Projects:
  - `[projects."<path>"].trust_level`
  - add/remove trusted project paths
  - show invalid/missing paths
- Profiles:
  - `[profiles.<name>]` entries in `config.toml`
  - v2 profile files under `$CODEX_HOME/*.config.toml`
- MCP:
  - read via TOML config and/or `codex mcp list`
  - add/remove via `codex mcp` where safer than direct TOML writes
- Plugins:
  - read installed/marketplace state via `codex plugin list` and local config where possible
  - add/remove through explicit command workflows later
- Features:
  - `[features]` booleans
  - `codex features` read-only diagnostics if useful

Read-only Codex status cards:

- `codex doctor --json`
- installed version
- auth present/missing
- config parse errors
- unknown fields when `--strict-config` would fail

### Phase 5: Backup Support

Extend backup/export to include provider-specific files.

Current backup service is Claude-specific. Add provider options:

- `claude-code` files:
  - current behavior
- `codex-cli` files:
  - `~/.codex/config.toml`
  - `~/.codex/*.config.toml`
  - `~/.codex/rules/*.rules`
  - exclude `auth.json` by default
  - exclude SQLite/log/history files by default unless a later explicit export mode is added

UI backup wizard should allow:

- provider selection
- include/exclude auth-sensitive files
- clear warning when exporting Codex auth is not included

## Frontend Plan

### Phase 1: Provider Context

Add a provider selector independent of project selection:

- `frontend/src/contexts/ProviderContext.tsx`
- `frontend/src/types/providers.ts`
- `frontend/src/hooks/useProviders.ts`

Provider state:

- selected provider
- provider capabilities
- installed/missing status
- versions

Default behavior:

- If both are installed, keep last selected provider.
- If only one is installed, select it automatically.
- If Codex is missing, show install/status guidance but keep Claude pages usable.

### Phase 2: Sidebar Rework

Replace the flat sidebar array with grouped navigation and provider-aware filtering.

Recommended left sidebar structure:

- Top area:
  - Project switcher
  - Agent provider switcher: Claude Code / Codex
- Primary:
  - Dashboard
  - Agent Bridge
  - Sessions
- Configuration:
  - Overview
  - Settings
  - MCP
  - Plugins
  - Permissions / Trust
  - Hooks
  - Commands
  - Agents
  - Skills
  - Memory
  - Output Styles
  - Status Line
- Operations:
  - Presence
  - Plans
  - Context
  - Usage
  - Backup
  - Diagnostics

Hide items unsupported by the selected provider by default, with a small "Claude-only" or "Unsupported for Codex" affordance in search/overflow if needed. Do not show a dead Codex page for Claude-only concepts like Claude agents unless we intentionally build a Codex equivalent.

Implementation approach:

- Convert `navigation` in `Sidebar.tsx` into a grouped `NavGroup[]`.
- Add collapsible groups using the existing `Collapsible` UI primitive.
- Keep collapsed-icon mode working.
- Add route metadata with `providerSupport`.
- Rename visible "CC Bridge" to "Agent Bridge".

### Phase 3: Agent Bridge UI

Move frontend bridge feature:

- from `frontend/src/features/cc-bridge/*`
- to `frontend/src/features/agent-bridge/*`

Page changes:

- Provider filter tabs or segmented control: All / Claude Code / Codex
- Session cards show provider badge.
- New session dialog starts with provider choice and then shows provider-specific fields.
- Codex spawn options:
  - directory
  - mode: new / resume / fork
  - resume/fork id or `--last`
  - model
  - profile
  - profile v2
  - sandbox mode
  - approval policy
  - search toggle
  - no-alt-screen toggle
  - optional initial prompt
  - dangerous bypass toggle with explicit warning
- Claude spawn options keep current fields.

Keep the current terminal grid behavior, fullscreen behavior, and tokenized WebSocket flow.

### Phase 4: Configuration UI

Current `ConfigViewerPage` assumes Claude Code. Evolve it into provider-aware configuration.

Recommended route shape:

- `/config` stays as provider-selected config overview.
- Optional explicit routes:
  - `/config/claude-code`
  - `/config/codex-cli`

UI layout:

- Provider header with version/status.
- Tabs:
  - Settings Editor
  - Scope/Profile Resolver
  - Raw Viewer
  - Diagnostics

Claude path:

- Reuse existing `SettingsEditor`, `ScopeResolver`, `ConfigFileList`, and `ConfigFileViewer`.

Codex path:

- New `CodexSettingsEditor`.
- New `CodexProfileResolver`.
- New `CodexConfigFileList`.
- New `CodexDiagnosticsPanel`.

Codex config cards:

- `CodexGeneralCard`
- `CodexRuntimeCard`
- `CodexProjectsCard`
- `CodexProfilesCard`
- `CodexMcpCard`
- `CodexPluginsCard`
- `CodexFeaturesCard`
- `CodexRulesCard`
- `CodexDiagnosticsCard`

Raw viewer:

- TOML syntax display/edit for `config.toml`.
- Warn before saving raw TOML.
- Validate by parsing TOML before write.
- Offer `codex doctor --json` after save.

### Phase 5: Header and Dashboard

Header currently shows only Claude Code version. Update status payload and UI:

- show selected provider version
- show both provider install statuses in a compact popover later
- active sessions should be provider-count aware

Dashboard:

- add provider status summary
- split active sessions by provider
- keep Claude-only metrics clearly labeled where Codex has no equivalent yet

### Phase 6: Docs

Docs to add/update:

- `docs/features/agent-bridge.md`
- `docs/features/config.md`
- `docs/api/providers.md`
- `docs/api/agent-bridge.md`
- `docs/api/config.md`
- `docs/guide/architecture.md`
- README feature list

Keep old `cc-bridge` docs as compatibility notes until routes/components are fully migrated.

## Route/API Migration

Compatibility period:

- Keep `/cc-bridge` frontend route as a redirect or alias to `/agent-bridge?provider=claude-code`.
- Keep backend `/api/v1/cc-bridge/*` until the UI no longer calls it.
- New code should call `/api/v1/agent-bridge/*`.

Final cleanup later:

- Remove old CC Bridge route names after one release cycle.
- Update screenshots and docs.

## Data Model Notes

No database migration is required for the initial plan unless we decide to persist provider preferences server-side.

If persisted preferences are needed:

- selected provider
- last bridge filters
- default spawn options per provider

Prefer local browser storage first for UI preferences. Use backend persistence only for shared machine-level preferences.

## Testing Plan

Backend tests:

- Provider registry returns Claude and Codex providers.
- Missing Codex binary reports installed=false without failing.
- Codex version parsing handles `codex-cli 0.133.0`.
- Codex tmux discovery matches direct `codex`.
- Codex tmux discovery matches node wrapper descendant.
- Codex tmux discovery rejects helper processes.
- Codex spawn command builder validates directory and modes.
- Codex config service reads TOML.
- Codex config service writes TOML without dropping unrelated keys.
- Codex config service masks secrets and never returns `auth.json`.
- Provider-aware CLI executor enforces per-provider whitelist.

Frontend tests:

- Sidebar groups render and collapse.
- Provider switcher hides unsupported nav items.
- Agent Bridge lists mixed provider sessions.
- New session dialog renders Codex fields when Codex is selected.
- Config page renders Claude editor for Claude provider.
- Config page renders Codex editor for Codex provider.
- Raw TOML validation blocks invalid saves.

Manual verification:

- Start existing Claude Code tmux session and confirm discovery.
- Start existing Codex tmux session and confirm discovery.
- Spawn Codex from a repo and attach terminal.
- Send prompt through interactive bridge and verify Enter handling.
- Edit a harmless Codex setting in a temp `$CODEX_HOME`.
- Run `codex doctor --json` from diagnostics with redacted output.

## Implementation Order

1. Add backend provider registry and status endpoint.
2. Add Codex provider with version/status/config path detection.
3. Generalize bridge backend into `agent_bridge` while keeping `/cc-bridge`.
4. Add Codex discovery and spawn command building.
5. Add frontend provider context and provider selector.
6. Rework sidebar into grouped provider-aware navigation.
7. Rename/migrate CC Bridge frontend to Agent Bridge with provider filtering.
8. Add Codex new-session dialog fields.
9. Add Codex TOML config service and read-only config files endpoint.
10. Add Codex settings editor cards for general/runtime/projects/profiles.
11. Add Codex MCP/plugins/diagnostics surfaces.
12. Extend backup/export for Codex config.
13. Update docs and screenshots.
14. Remove or alias old naming after compatibility is verified.

## Open Questions

- Should the public product name remain Claude Deck, or should the UI start using a broader label like "Agent Deck" while the repo remains `claude-deck`?
- Should provider selection be global, per page, or per project?
- Should Codex project trust be edited directly in TOML, only via CLI if Codex adds commands for it, or both?
- Should Codex `auth.json` ever be included in backups behind an explicit advanced option?
- Do we want OpenAI account/model usage metrics in Claude Deck, or keep Codex usage out of scope until the CLI exposes stable local usage data?
- Should non-interactive `codex exec` and `codex review` be exposed as task actions later, or should v1 stay strictly interactive/tmux plus config?

## Risks

- Codex CLI config shape may evolve quickly. Use permissive TOML read/write and avoid hardcoding too much schema.
- Raw TOML writing can damage comments/formatting unless we use `tomlkit`.
- Naming migration from CC Bridge to Agent Bridge touches docs, routes, screenshots, and mental model.
- Sidebar grouping can become a UX project by itself. Keep the first version functional and restrained.
- Provider-specific config can drift. Tests should use temp homes and fixture configs for both providers.

## Definition of Done for v1

- Claude Code behavior is unchanged.
- Codex sessions are discoverable in tmux.
- Claude and Codex sessions can be viewed in the same Agent Bridge grid.
- Codex sessions can be spawned from the UI with core runtime options.
- Codex `~/.codex/config.toml` can be viewed and safely edited through structured cards.
- Codex project trust and profiles are visible and manageable.
- Codex doctor output is available as a redacted diagnostics panel.
- Sidebar is grouped and provider-aware.
- Tests cover provider detection, bridge discovery/spawn, TOML config editing, and core UI routing.
