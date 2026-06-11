# Changelog

All notable changes to Claude Deck will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/adrirubio/claude-deck/compare/v1.3.1...HEAD
[1.3.1]: https://github.com/adrirubio/claude-deck/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/adrirubio/claude-deck/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/adrirubio/claude-deck/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/adrirubio/claude-deck/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/adrirubio/claude-deck/releases/tag/v1.0.0
