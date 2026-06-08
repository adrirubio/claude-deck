# Quick Start

Get Claude Deck running and explore the dashboard in under 5 minutes.

## Start the Dev Servers

```bash
./scripts/dev.sh
```

This starts:
- **Backend** at `http://localhost:8000` (API docs at `http://localhost:8000/docs`)
- **Frontend** at `http://localhost:5173`

Open `http://localhost:5173` in your browser.

## Explore the Dashboard

The dashboard shows an overview of your selected provider and local project state. Claude Code still has the richest metrics; Codex surfaces focus on provider status, sessions, configuration, diagnostics, and inventory.

- **Projects** — tracked project directories
- **MCP Servers** — configured server count
- **Commands** — available slash commands
- **Plugins** — installed plugins
- **Hooks** — automation hooks
- **Permissions** — allow/deny rules
- **Sessions** — conversation history with today/this week counts
- **Context Window** — highest context usage across active sessions

Data is cached between page navigations and updates when you click the refresh button or switch projects.

## Select a Project

Use the project selector in the sidebar to switch between projects. Many features show project-scoped data — MCP servers, commands, hooks, and permissions can differ between projects.

Use **Discover Projects** when you want Claude Deck to find projects from local agent state, or add a path manually with the directory browser.

## Switch Providers

Use the provider switcher in the sidebar to move between Claude Code and Codex CLI.

With Codex selected, start with:

- **Agent Bridge** — find or start Codex tmux sessions
- **Config** — edit safe TOML settings, inspect profiles, and manage feature flags
- **Backup** — create a redacted Codex export

## Key Pages

| Page | What You Can Do |
|------|-----------------|
| **MCP Servers** | Add servers, test connections, browse the MCP Registry |
| **Commands** | Create and edit slash commands |
| **Hooks** | Configure pre/post tool use automation |
| **Sessions** | Browse conversation transcripts |
| **Usage** | View token costs and billing blocks |
| **Agent Bridge** | Attach to live Claude Code and Codex terminals |

## Production Build

To build for production:

```bash
./scripts/build.sh
```

This compiles the app frontend into `frontend/dist/` and the documentation site into `docs/.vitepress/dist/`. The backend serves the built app frontend automatically.

To preview the documentation site while editing:

```bash
./scripts/docs-dev.sh
```

Open `http://localhost:5174/docs/`.

## Next Steps

- [Features](/features/dashboard) — detailed guides for each feature
- [Architecture](/guide/architecture) — how the app is structured
- [API Reference](/api/) — REST API documentation
