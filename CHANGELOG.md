# Changelog

All notable changes to Claude Deck will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **CC Bridge**: Live terminal bridge to Claude Code sessions running in tmux
  - Multi-terminal grid layout supporting up to 4 simultaneous panes (auto-layout: 1, 2-column, or 2x2 grid)
  - Per-pane read-only/interactive mode toggle, fullscreen, attach/detach, and close controls
  - Session discovery via `tmux list-panes` with auto-refresh polling
  - Spawn new Claude Code sessions (plain, worktree, or resume mode) from the UI
  - Kill sessions with optional worktree cleanup
  - WebSocket-based PTY relay with xterm.js (WebGL rendering, web links)

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

[Unreleased]: https://github.com/adrirubio/claude-deck/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/adrirubio/claude-deck/releases/tag/v1.0.0
