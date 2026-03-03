# Introduction

Claude Deck is a self-hosted web application for visualizing and managing [Claude Code](https://docs.anthropic.com/en/docs/claude-code) configuration. It provides a unified interface for managing MCP servers, plugins, slash commands, hooks, agents, permissions, usage tracking, and other Claude Code extensions.

## Why Claude Deck?

Claude Code stores configuration across multiple JSON files and directories (`~/.claude.json`, `~/.claude/settings.json`, `.claude/settings.json`, `.mcp.json`, and more). Managing these files manually is tedious and error-prone. Claude Deck gives you a visual dashboard to:

- **See everything at a glance** — dashboard with counts, session activity, and context window usage
- **Edit configuration visually** — no more hand-editing JSON files
- **Manage MCP servers** — add, test, and configure servers with OAuth support
- **Track usage** — monitor token costs, billing blocks, and daily/monthly trends
- **Browse sessions** — view conversation transcripts with tool use details
- **Monitor live sessions** — attach to running Claude Code terminals via CC Bridge

## Features

Claude Deck covers all aspects of Claude Code configuration:

| Category | Features |
|----------|----------|
| **Core Config** | Settings editor, MCP servers, slash commands |
| **Extensions** | Plugins, hooks, permissions, agents, skills |
| **Monitoring** | Sessions, usage tracking, context window, CC Bridge |
| **Customization** | Output styles, status line, memory |
| **Management** | Projects, plans, backup & restore |

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.11+ with FastAPI |
| Frontend | React 19 + TypeScript + Vite 7 |
| UI | shadcn/ui + Tailwind CSS |
| Charts | Recharts |
| Database | SQLite (async via SQLAlchemy + aiosqlite) |

## Next Steps

- [Installation](/guide/installation) — get Claude Deck running locally
- [Quick Start](/guide/quick-start) — explore the dashboard in 5 minutes
- [Architecture](/guide/architecture) — understand how the app is built
