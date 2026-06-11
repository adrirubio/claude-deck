# Changelog

All notable changes to Claude Deck are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## 1.3.1 — 2026-06-11

### Fixed

- Aligned `react` and `react-is` with the installed React DOM version to avoid production render failures from mixed React package versions.

### Changed

- Refreshed README screenshots, including the Agent Bridge mixed-provider view, dashboard, config, and MCP visuals used for the release.

## 1.3.0 — 2026-06-08

### Added

- **Codex CLI support** is now stable enough for daily use:
  - Mixed Claude Code and Codex tmux sessions in Agent Bridge
  - Codex spawn, resume, fork, attach, and kill actions
  - Provider-aware navigation so Codex users do not land on unsupported Claude-only pages
- **Codex Config**:
  - Safe TOML editing for whitelisted scalar settings and feature flags
  - Dropdowns for known Codex runtime values
  - Help tooltips for documented settings and feature flags
  - Feature inventory from `codex features list`, including goals and other enable-flag features
  - Profile diagnostics for active/default profiles, profile files, overrides, missing references, and malformed profiles
- **Codex MCP and Plugins**:
  - MCP inventory from `codex mcp list --json`
  - MCP add/remove through the Codex CLI with validation
  - Plugin inventory from `codex plugin list`
  - Plugin install/remove where the installed Codex CLI exposes safe commands
- **Codex Backup Export**:
  - Redacted export-only backups for config, profile files, rules, and provider inventory metadata
- **Projects**:
  - Easier project discovery and directory browsing when adding project paths

### Changed

- Provider status, capabilities, diagnostics, and normalized provider errors now drive more of the UI.
- The frontend toolchain now uses TypeScript 6, `@vitejs/plugin-react` 5, updated ESLint tooling, React DOM, PostCSS, Tailwind Merge, and Node types.

### Security

- Codex auth, history, model cache, SQLite state, prompt text, and raw cache payloads are still excluded from raw viewers and backups.
- Automatic Codex restore remains disabled because exports intentionally omit provider-owned local state.

## 1.2.0 — 2026-04-22

### Added

- **CC Bridge** — live terminal bridge to Claude Code sessions in tmux
  - Multi-terminal grid (up to 4 panes in auto-layout)
  - Per-pane read-only/interactive mode, fullscreen, attach/detach
  - Session discovery via `tmux list-panes` with auto-refresh
  - Spawn new sessions (plain, worktree, or resume mode)
  - Kill sessions with optional worktree cleanup
  - WebSocket PTY relay with xterm.js (WebGL rendering)

### Fixed

- **CC Bridge** — prevent orphaned `tmux attach-session` processes on server reload
- **CC Bridge** — fix terminal rendering in React StrictMode

## 1.0.0 — 2026-01-22

### Added

- Initial release of Claude Deck
- **Dashboard** — configuration status and usage overview
- **MCP Server Management** — add, edit, test, configure servers (global + project)
- **Commands** — create and manage slash commands
- **Plugins** — create, install, and manage plugins
- **Hooks** — configure event hooks for Claude Code lifecycle
- **Permissions** — manage allow/deny rules for tools
- **Backup & Restore** — full configuration backup and restore
- **Project Management** — project-specific configurations
- **Usage Tracking** — token usage and cost visualization

### Technical

- FastAPI backend with async SQLAlchemy + SQLite
- React frontend with TypeScript, Vite, and shadcn/ui
- RESTful API at `/api/v1/`

---

See the full changelog on [GitHub](https://github.com/adrirubio/claude-deck/blob/master/CHANGELOG.md).
