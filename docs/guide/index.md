# Introduction

Claude Deck is a self-hosted web application for visualizing and managing local AI coding agents. It started with [Claude Code](https://docs.anthropic.com/en/docs/claude-code) configuration and now includes stable Codex CLI support plus GitHub Copilot CLI support for live sessions, Agent Mail, and Agent Teams.

## Why Claude Deck?

Claude Code stores configuration across multiple JSON files and directories (`~/.claude.json`, `~/.claude/settings.json`, `.claude/settings.json`, `.mcp.json`, and more). Managing these files manually is tedious and error-prone. Claude Deck gives you a visual dashboard to:

- **See everything at a glance** — dashboard with counts, session activity, and context window usage
- **Edit configuration visually** — no more hand-editing JSON files
- **Manage MCP servers** — add, test, and configure servers with OAuth support
- **Track usage** — monitor token costs, billing blocks, and daily/monthly trends
- **Browse sessions** — view conversation transcripts with tool use details
- **Monitor live sessions** — attach to running Claude Code, Codex, and Copilot terminals via Agent Bridge
- **Switch providers intentionally** — use shared surfaces for Claude Code, Codex CLI, and GitHub Copilot CLI while unsupported provider-specific pages stay hidden or disabled
- **Manage Codex safely** — edit whitelisted TOML settings, inspect feature flags, and run CLI-backed inventory/mutation flows without exposing auth or prompt history

## Features

Claude Deck covers Claude Code configuration and the shared local-agent operations layer:

| Category | Features |
|----------|----------|
| **Core Config** | Claude Code settings editor, Codex TOML settings editor, Codex feature flags, MCP servers, slash commands |
| **Extensions** | Plugins, hooks, permissions, agents, skills |
| **Monitoring** | Sessions, usage tracking, context window, Agent Bridge |
| **Customization** | Output styles, status line, memory |
| **Management** | Projects, plans, backup & restore |

## Provider Support

Claude Deck exposes provider capabilities and status through the Providers API. Claude Code remains the full-featured provider for usage, context, transcripts, plugins, hooks, agents, skills, memory, backup, and restore. Codex CLI support focuses on mixed tmux sessions, safe TOML configuration, feature flags, diagnostics, MCP/plugin inventory and safe CLI-backed mutations, and redacted export-only backups. GitHub Copilot CLI support currently focuses on Agent Bridge sessions, Agent Mail MCP/hooks, and Agent Team launch/reuse workflows.

See [Multi-Provider and Codex CLI](/guide/multi-provider-codex-v2) for the supported, diagnostics-only, and unsupported Codex surfaces.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.11+ with FastAPI |
| Frontend | React 19 + TypeScript 6 + Vite 7 |
| UI | shadcn/ui + Tailwind CSS |
| Charts | Recharts |
| Database | SQLite (async via SQLAlchemy + aiosqlite) |

## Next Steps

- [Installation](/guide/installation) — get Claude Deck running locally
- [Quick Start](/guide/quick-start) — explore the dashboard in 5 minutes
- [Architecture](/guide/architecture) — understand how the app is built
