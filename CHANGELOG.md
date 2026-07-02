# Changelog

All notable changes to Claude Deck will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.0.1] - 2026-06-20

### Added
- **Claude Code Config**: Added coverage for current Claude Code settings such as advisor model, fallback model chains, Remote Control startup, push notifications, notification channel, theme, auto-compact, file checkpointing, and newer safety/privacy toggles.
- **Config editor helpers**: Added validated JSON editing for complex settings objects/arrays and a boolean map editor for plugin enablement.

### Changed
- **Dashboard**: Dashboard cards and navigation are now provider-aware so Codex selection does not show inaccessible Claude Code-only cards as if they were Codex pages.
- **Codex provider pages**: Codex MCP servers, plugins, feature flags, and configuration inventory now route to provider-appropriate pages instead of dead-end dashboard stats.
- **Claude Code settings**: Plugin marketplace settings, worktree symlink directories, sandbox Mach lookup settings, and managed marketplace policy values now use the JSON shapes documented by Claude Code.
- **Docs**: Refreshed release, Config, and Dashboard docs to describe the 2.0.1 stabilization fixes.

### Fixed
- **Usage costs**: Claude Code usage dashboards now calculate costs for current Claude model aliases such as Sonnet 5, Fable 5, Opus 4.6/4.7/4.8, Sonnet 4.6, and Haiku 4.5 instead of showing `$0.00` with non-zero token usage.
- **Usage cache**: Usage cache keys now include the pricing table version, avoiding stale zero-cost aggregates after pricing support changes.
- **Config defaults**: Corrected stale UI defaults/descriptions for auto-updates, sandbox auto-allow, thinking summaries, plan auto-mode, and turn duration.

## [2.0.0] - 2026-06-19

### Added
- **Agent Mail**: Durable local mailbox coordination for Claude Code and Codex CLI agents
  - Per-repository and Agent Team slot participants with role and charter metadata
  - Structured direct messages, context requests, handoffs, replies, read state, acknowledgements, and inbox load
  - Agent-facing MCP tools for team discovery, inbox checks, replies, context requests, and handoffs
  - One-click install and uninstall flows for Claude Code and Codex MCP/hooks configuration with best-effort backups
  - Best-effort tmux wake nudges for visible sessions through Agent Bridge
- **Agent Teams**: Saved rosters for launching or reusing local agent sessions
  - Manual team creation, team creation from Agent Mail participants, and team creation from visible Agent Bridge sessions
  - Team slots with provider, repository, display name, role, charter, bootstrap prompt, launch mode, provider options, and enabled state
  - Launch planning that checks provider availability, Agent Mail readiness, reusable tmux sessions, disabled slots, and launch option validity
  - Same-repository planner/reviewer and implementer workflows through distinct Agent Mail team-slot identities
- **External local orchestration**: Token-bound same-machine Agent Mail API for tools such as OpenClaw
  - External actor registration, member discovery, direct messages, broadcasts, context requests, handoffs, replies, request status, bounded waits, and acknowledgements
  - Agent Teams launch endpoints usable by local external automation after plan review
- **Agent Bridge session creation**: Searchable project picker and Codex model/profile selectors with custom-value fallback.

### Changed
- **Multi-agent workflow**: Agent Bridge, Agent Mail, and Agent Teams are now the supported surfaces for local session visibility, communication, and reusable rosters.
- **Agent Mail dashboard**: Connected, observed-only, not wakeable, and inbox-load states now describe delivery behavior more explicitly.
- **Agent Mail docs**: Setup documentation now explains required MCP/hooks configuration and the current tmux-only wake path.
- **Dependencies**: Merged low-risk package updates including React package alignment and small UI/runtime dependency updates.

### Removed
- **Presence**: Removed the Presence frontend route, backend route/service, hook integration, tests, and navigation. Existing inert SQLite tables may remain in local databases, but no active backend polling or UI surface uses them.

### Fixed
- **Agent Mail install feedback**: Install and uninstall actions now refresh status and show clearer results for Claude Code and Codex configuration.
- **Agent Mail roster accuracy**: Dashboard member counts now distinguish durable members from observed sessions and collapse bridge-observed/MCP sessions under the same member where appropriate.
- **Agent Mail hook output**: Claude Code and Codex hooks return provider-valid JSON so hook failures are not shown for normal mailbox checks.
- **Agent Bridge startup flow**: The development script now avoids transient frontend proxy noise by coordinating backend/frontend startup more carefully.

### Security
- **External Agent Mail boundary**: External actor creation is loopback-only, external endpoints require bearer tokens, and per-actor rate limits protect the local orchestration surface within Claude Deck's existing local trust model.

## [1.3.1] - 2026-06-11

### Fixed
- **Frontend runtime alignment**: Aligned `react` and `react-is` with the installed React DOM version to avoid production render failures from mixed React package versions.

### Changed
- **Documentation screenshots**: Refreshed README screenshots, including the Agent Bridge mixed-provider view, dashboard, config, and MCP visuals used for the release.

## [1.3.0] - 2026-06-08

### Added
- **Codex CLI support**: Provider-aware Codex support is now stable enough for everyday use
  - Agent Bridge discovers mixed Claude Code and Codex tmux sessions
  - Codex sessions can be spawned, resumed, forked, attached to, and killed from the UI
  - Provider switcher keeps Claude Code and Codex surfaces separate instead of showing unsupported pages
- **Codex Config**: Safe TOML editor for Codex settings
  - Structured General and Runtime cards for model, profile, reasoning effort, sandbox mode, approval policy, search, strict config, and alternate screen behavior
  - Dropdowns for known Codex enum values while keeping open-ended fields editable
  - Help tooltips for documented settings and feature flags
  - Feature flag inventory from `codex features list`, including editable overrides for flags such as goals, memories, hooks, multi-agent, shell tool, and network proxy
  - Profile diagnostics for active/default profile resolution, profile files, overrides, missing references, and malformed profiles
- **Codex MCP and Plugins**: Provider inventory and safe CLI-backed mutations
  - MCP inventory from `codex mcp list --json`
  - MCP add/remove through the Codex CLI with validation
  - Plugin inventory from `codex plugin list`
  - Plugin install/remove where the installed Codex CLI exposes safe commands
- **Codex Backup Export**: Redacted export-only backups for Codex config, profile files, rules, and provider inventory metadata
- **Projects**: Project discovery is easier, with directory browsing support when adding project paths

### Changed
- **Provider model**: Provider status, capabilities, diagnostics, and normalized errors now drive the UI for Claude Code and Codex CLI.
- **Documentation**: README and VitePress docs now describe the stable Codex support surface, the remaining provider boundaries, and the release-ready dependency updates.
- **Frontend toolchain**: Updated TypeScript to 6.0.3, `@vitejs/plugin-react` to 5.1.4, ESLint tooling, React DOM, PostCSS, Tailwind Merge, and Node types.

### Security
- **Codex privacy boundary**: Codex auth, history, model cache, SQLite state, prompt text, and raw cache payloads remain excluded from raw viewers and backups.
- **Codex restore policy**: Automatic Codex restore is refused because exports intentionally omit provider-owned local state.

## [1.2.0] - 2026-04-22

### Added
- **CC Bridge**: Live terminal bridge to Claude Code sessions running in tmux
  - Multi-terminal grid layout supporting up to 4 simultaneous panes (auto-layout: 1, 2-column, or 2x2 grid)
  - Per-pane read-only/interactive mode toggle, fullscreen, attach/detach, and close controls
  - Active terminal focus indicator — green glow on the focused pane
  - Session discovery via `tmux list-panes` with auto-refresh polling
  - Spawn new Claude Code sessions (plain, worktree, or resume mode) from the UI
  - Kill sessions with optional worktree cleanup
  - WebSocket-based PTY relay with xterm.js (WebGL rendering, web links)
- **Projects**: Discover projects from `~/.claude/projects/` session history
- **Dashboard**: Cache stats in context to avoid re-fetching on navigation
- **Documentation**: VitePress documentation site with guide, features, and API reference

### Fixed
- **CC Bridge**: Prevent orphaned `tmux attach-session` processes from accumulating on server reload/crash via `PR_SET_PDEATHSIG` and startup cleanup
- **CC Bridge**: Fix terminal not rendering in React StrictMode due to race condition in async attach flow

## [1.1.0] - 2026-03-03

### Added
- **CC Bridge**: Live terminal bridge to Claude Code sessions running in tmux
  - Multi-terminal grid layout supporting up to 4 simultaneous panes (auto-layout: 1, 2-column, or 2x2 grid)
  - Per-pane read-only/interactive mode toggle, fullscreen, attach/detach, and close controls
  - Active terminal focus indicator — green glow on the focused pane
  - Session discovery via `tmux list-panes` with auto-refresh polling
  - Spawn new Claude Code sessions (plain, worktree, or resume mode) from the UI
  - Kill sessions with optional worktree cleanup
  - WebSocket-based PTY relay with xterm.js (WebGL rendering, web links)
- **Projects**: Discover projects from `~/.claude/projects/` session history
- **Dashboard**: Cache stats in context to avoid re-fetching on navigation
- **Documentation**: VitePress documentation site with guide, features, and API reference

### Fixed
- **CC Bridge**: Prevent orphaned `tmux attach-session` processes from accumulating on server reload/crash via `PR_SET_PDEATHSIG` and startup cleanup
- **CC Bridge**: Fix terminal not rendering in React StrictMode due to race condition in async attach flow

## [1.0.0] - 2026-01-22

### Added
- Initial release of Claude Deck
- **Dashboard**: Overview of Claude Code configuration status and usage statistics
- **MCP Server Management**: Add, edit, remove, and configure MCP servers (global and project-scoped)
- **Commands Management**: Create and manage custom slash commands with argument support
- **Plugins Management**: Install, configure, and manage Claude Code plugins
- **Hooks Management**: Configure pre/post hooks for various Claude Code events
- **Permissions Management**: Manage allowed and denied permissions for tools
- **Backup & Restore**: Full backup and restore functionality for all configurations
- **Project Management**: Support for project-specific configurations
- **CLI Executor**: Execute Claude CLI commands from the web interface
- **Usage Tracking**: Track and visualize API usage and costs

### Technical
- FastAPI backend with async SQLAlchemy and SQLite
- React 18 frontend with TypeScript, Vite, and shadcn/ui
- RESTful API at `/api/v1/`
- CORS configured for local development

[Unreleased]: https://github.com/adrirubio/claude-deck/compare/v2.0.1...HEAD
[2.0.1]: https://github.com/adrirubio/claude-deck/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/adrirubio/claude-deck/compare/v1.3.1...v2.0.0
[1.3.1]: https://github.com/adrirubio/claude-deck/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/adrirubio/claude-deck/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/adrirubio/claude-deck/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/adrirubio/claude-deck/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/adrirubio/claude-deck/releases/tag/v1.0.0
