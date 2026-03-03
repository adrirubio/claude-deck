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

The dashboard shows an overview of your Claude Code configuration:

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

## Key Pages

| Page | What You Can Do |
|------|-----------------|
| **MCP Servers** | Add servers, test connections, browse the MCP Registry |
| **Commands** | Create and edit slash commands |
| **Hooks** | Configure pre/post tool use automation |
| **Sessions** | Browse conversation transcripts |
| **Usage** | View token costs and billing blocks |
| **CC Bridge** | Attach to live Claude Code terminals |

## Production Build

To build for production:

```bash
./scripts/build.sh
```

This compiles the frontend into `frontend/dist/`. The backend serves the built frontend automatically.

## Next Steps

- [Features](/features/dashboard) — detailed guides for each feature
- [Architecture](/guide/architecture) — how the app is structured
- [API Reference](/api/) — REST API documentation
