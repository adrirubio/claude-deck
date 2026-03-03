# Changelog

All notable changes to Claude Deck are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

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
- **Plugins** — install, configure, and manage plugins
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
