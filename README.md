# Claude Deck

**Website**: [claudedeck.org](https://claudedeck.org)

A self-hosted workspace to observe and intervene in bounded coding-agent attempts on GitHub issues, with mixed harnesses, visible policies and recovery controls.

## Why This Exists

Returning to several agents should make it possible to find queued work, review requests and attempts needing attention. Claude Deck brings tracking observations across teams together with the existing session, Mail and configuration workflows. GitHub remains the source of issues and PRs. Native configuration and manual sessions are available without enabling automatic dispatch.

## Best For

Technical operators with existing repositories, local agent CLIs, native toolchains, tmux sessions and their own model credentials. Teams can mix harnesses; native coverage and operational readiness vary.

## Trust model

- Local control plane and real agent/repository files; no Deck cloud account.
- No Deck telemetry sent elsewhere. GitHub and native CLIs use their configured services and credentials.
- Protected roster, autonomy and recovery actions use the current browser tab's configured operator credential. It is separate from GitHub polling credentials and authenticated Mail-session authority; this is not cookie login or a remote multi-user isolation boundary.
- Review real-file changes and retain backups.

> [!WARNING]
> Claude Deck reads and writes your real local agent configuration files. Changes made in the UI affect the files Claude Code, Codex CLI, and installed agent integrations actually use. Review changes carefully, and create a backup before major edits.

## Daily operating flow

1. Read Overview for complete filtered tracking counts and configured versus effective intake.
2. Open Work or Repositories using explicit team, scope and harness filters.
3. Inspect an owner, waiting reason, PR and current observations; session/Mail context remains read-only.
4. Review confirmation, authorization and state before a protected remedy. Agent plan approval, operator intervention and human PR review are separate.
5. Use Teams for roster/repository policies and finite recovery, or start manually from Live sessions.

Finished is tracking state, not independently reviewed delivery, reliability, cost or time saved. An operator-requested stop can leave a process running and the attempt needing attention.

## Product integration scope

This reference describes the integrated product source candidate. Earlier packaged releases and separately pinned runtime or pilot environments can retain previous navigation and capabilities; integrating source does not upgrade those environments.

[Harnesses](docs/features/harnesses.md) includes the versioned operations/readiness catalog for all five harnesses, bounded local configuration observations and guarded native pages. See the [Providers API](docs/api/providers.md) for the catalog contract. Native adapters remain provider-specific; catalog support does not create an editor or grant authority.

Configuration checks do not verify model access. Credential readiness remains unknown, and generic provider cards do not establish a team-slot session binding. Conditional operating support still requires the current identity, workspace and approval authority.

Guided setup, explicit Leader selection and delivery audit/metrics are not included. This source candidate has not received M1b or pilot acceptance. The manual Bridge trial is unperformed; pilot participants, human benefit measurements and timing comparisons are unavailable. Promotion, publication, paid execution and deployment require separate authorization.

## Features

Native features vary by harness and registered page access. See [Harnesses](docs/features/harnesses.md) before using the native feature inventory below.

- **Overview** — complete filtered work counts and automation observations; native configuration summaries are under Harnesses.
- **Harnesses** — guarded native pages and manual entry points for the implemented providers; factory filters remain independent.
- **Config Editor** — Browse, inspect, and edit Claude Code JSON settings or Codex TOML settings, including Codex profiles, runtime options, and feature flags
- **MCP Servers** — Add, edit, test, and manage MCP server connections with OAuth support. Browse and install servers from the [MCP Registry](https://registry.modelcontextprotocol.io). View tools, resources, and prompts. Supports stdio, HTTP, and SSE transports
- **Slash Commands** — Browse, create, and edit custom commands (user and project scope)
- **Plugins** — Browse installed plugins with detail views and enable/disable toggles; Codex plugins support CLI-backed inventory, install, and remove where the installed Codex CLI exposes safe commands
- **Hooks** — Configure automation hooks by event type (PreToolUse, PostToolUse, etc.)
- **Permissions** — Visual allow/deny rule builder for tool access control
- **Agents** — Create and manage custom agent configurations
- **Skills** — Browse installed skills and discover new ones from [skills.sh](https://skills.sh)
- **Memory** — View and edit Claude Code memory files
- **Output Styles** — Configure response output formats
- **Status Line** — Customize Claude Code status line display
- **Agent Bridge** — Discover and monitor Claude Code, Codex CLI, and GitHub Copilot CLI sessions running in tmux. Attach up to 4 terminals simultaneously in a 2x2 grid with independent read-only/interactive modes, fullscreen toggle, and per-pane controls. Spawn new sessions and manage provider-specific options directly from the UI
- **Agent Mail** — Coordinate local Claude Code, Codex CLI, and GitHub Copilot CLI agents through durable per-repo identities, structured context requests, handoffs, and an inspectable team mailbox
- **Agent Teams** — Save reusable rosters of Claude Code, Codex, and Copilot agents, launch or reuse their sessions, and keep same-repo roles distinct through Agent Mail slot identities
- **Session Transcripts** — View conversation history with full message details and tool use
- **Usage Tracking** — Monitor token usage, costs, and billing blocks with daily/monthly charts
- **Plan History** — Browse and review Claude Code implementation plans
- **Backup & Restore** — Create and manage Claude Code backups with selective restore, plus redacted export-only Codex backups
- **Projects** — Discover and manage project directories

## What's New in 2.0.1

Claude Deck 2.0.1 is a stabilization release for the 2.x coordination work:

- Claude Code usage dashboards now calculate costs for current Claude model aliases instead of showing `$0.00` when token usage is present.
- Dashboard cards and links are provider-aware, including Codex configuration, MCP, plugin, feature flag, live session, and plan surfaces.
- Claude Code Config now exposes more current settings, including advisor model, fallback model chains, Remote Control, notification, checkpointing, theme, and safety/privacy controls.
- Plugin marketplace, worktree, and sandbox settings now write the JSON shapes expected by current Claude Code.

## What's New in 2.0.0

Claude Deck 2.0.0 shifts the product from single-agent management toward local agent coordination:

- Agent Mail gives Claude Code and Codex CLI sessions durable mail identities, structured context requests, handoffs, replies, inbox state, and one-click install flows for MCP and lifecycle hooks.
- Agent Teams adds saved rosters for repeatable project, DevOps, release, or same-repo planner/implementer teams, with launch planning and session reuse from Agent Bridge.
- External local tools such as OpenClaw can use token-bound Agent Mail endpoints to discover participants, send requests, create handoffs, poll for answers, and launch saved teams through the Agent Teams API.
- Agent Bridge now has a searchable project picker and Codex model/profile selectors when spawning sessions.
- Presence has been removed from the product. Agent Bridge, Agent Mail, and Agent Teams are now the supported observability and coordination surfaces.

Codex support remains explicit about provider boundaries: usage/context parity and session transcript browsing are not supported for Codex yet; history and model-cache diagnostics avoid prompt text and raw cache payloads; Codex automatic restore is refused because exports intentionally exclude auth, history, cache, and local state.

## Screenshots

These existing screenshots show retained native/session pages; they do not depict the new factory Overview or Work.

| Agent Bridge | Dashboard |
|--------------|-----------|
| ![Agent Bridge](screenshots/cc-bridge.png) | ![Dashboard](screenshots/dashboard.png) |
| Monitor and interact with Claude Code, Codex, and Copilot tmux sessions | Native configuration summary (existing screenshot) |

| Config | MCP Servers |
|--------|-------------|
| ![Config](screenshots/config.png) | ![MCP Servers](screenshots/mcp-servers.png) |
| Edit safe Codex TOML settings and inspect provider diagnostics | Manage MCP connections, status, and configuration |

| Usage Tracking | Session Transcripts |
|----------------|---------------------|
| ![Usage Tracking](screenshots/usage-tracking.png) | ![Session Transcripts](screenshots/sessions.png) |
| Cost visibility, charts, and billing blocks | Browse conversation history and tool usage details |

| Skills |
|--------|
| ![Skills](screenshots/skills.png) |
| Browse installed skills and discover new ones |

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.11+ with FastAPI |
| Frontend | React 19 + TypeScript 6 + Vite 7 |
| UI Components | shadcn/ui + Tailwind CSS |
| Charts | Recharts (via shadcn/ui) |
| Database | SQLite (async via SQLAlchemy + aiosqlite) |

## Installation

Claude Deck must run in the same environment where your agent CLIs and credentials are installed. Use the native install path below; Docker is not supported because containers cannot see host-installed CLIs, tmux sessions, native agent credentials, or your real repository environment.

**Prerequisites**:

- Python 3.11+
- Node.js 18+
- At least one supported local agent CLI installed on the same host: Claude Code, Codex CLI, GitHub Copilot CLI, OpenCode CLI, or Pi
- **Linux** for agent-team pane binding. Deck reads `/proc/net/tcp` and `/proc/<pid>/stat` to derive which tmux pane a registering agent is running in. On macOS or Windows every other feature works, but agents register unbound, and the Agent Mail capability-token enforcement described in `docs/deploy/pr0-capability-tokens-rollout.md` cannot be turned on

Pi integration requires Pi 0.87.1, Node >=22.19.0, and the repository-local Agent Mail extension dependencies. It supports OpenRouter (default model `moonshotai/kimi-k3`), plain launches and exact project-local resume. No global Pi configuration is installed, and Pi tools are not sandboxed by Deck. See [Pi rollout and team migration](docs/deploy/pi-provider-rollout.md) before deployment or replacing existing team sessions.

```bash
git clone --branch feature/software-delivery-product-reposition https://github.com/juanrubio/claude-deck.git
cd claude-deck
./scripts/install.sh
```

> [!WARNING]
> Claude Deck is not a mock viewer. It works with your real local agent files, so changes made in the UI can change your working setup.

## Development

```bash
./scripts/dev.sh
```

This starts:
- Backend at http://localhost:8000 (API docs at http://localhost:8000/docs)
- Frontend at http://localhost:5173

To stop or restart the dev servers for this checkout:

```bash
./scripts/dev.sh stop
./scripts/dev.sh restart
```

To make the dev environment reachable from another machine on your LAN or tailnet (e.g. to monitor tmux sessions via Agent Bridge from a different host), pass `--host`:

```bash
./scripts/dev.sh --host 0.0.0.0
```

Both servers will then bind to all interfaces.

Only use this option on a trusted network. Protected roster, autonomy and recovery routes require their documented credentials, while safe observations remain readable. These endpoint checks do not provide remote multi-user isolation. For remote access, prefer a trusted tunnel to the loopback listener. If you intentionally run the Vite dev UI from another origin, set `CORS_ORIGINS` to a JSON list containing that exact origin (for example, `["http://deck-host:5173"]`). Production UI served by Deck uses the same origin and needs no CORS entry.

Remote use should still be native: run Claude Deck on the remote host where the agents, credentials, repositories, and tmux sessions exist, then connect from your browser over a trusted tunnel or network route.

### Naming a Claude Deck instance

When running Claude Deck on several machines, set a display name and accent color so each browser window clearly identifies the backend it controls:

```bash
CLAUDE_DECK_INSTANCE_NAME="Studio Mac" \
CLAUDE_DECK_INSTANCE_ACCENT="blue" \
./scripts/dev.sh --host 0.0.0.0
```

Supported accents are `blue`, `green`, `purple`, `orange`, `red`, `pink`, `cyan`, and `slate`. The name appears in the header, browser tab title, Agent Bridge terminal panes, and destructive confirmations.

To preview the documentation site:

```bash
./scripts/docs-dev.sh
```

This starts VitePress at http://localhost:5174/docs/. Use `--host 0.0.0.0` if you need to reach it from another machine.

For a release check, `./scripts/build.sh` builds both the app frontend and the documentation site.

## Configuration Files

Claude Deck reads and writes these Claude Code configuration files:

| File/Directory | Scope | Description |
|---------------|-------|-------------|
| `~/.claude.json` | User | OAuth, caches, MCP servers |
| `~/.claude/settings.json` | User | User settings, permissions, disabled servers |
| `~/.claude/settings.local.json` | User | Local overrides (not committed) |
| `~/.claude/commands/` | User | User slash commands |
| `~/.claude/agents/` | User | User agents |
| `~/.claude/skills/` | User | User skills |
| `~/.claude/projects/` | User | Session transcripts & usage data |
| `.claude/settings.json` | Project | Project settings |
| `.claude/commands/` | Project | Project slash commands |
| `.mcp.json` | Project | Project MCP servers |
| `CLAUDE.md` | Project | Project instructions |

Codex CLI support uses `$CODEX_HOME`, defaulting to `~/.codex`:

| File/Directory | Scope | Description |
|---------------|-------|-------------|
| `~/.codex/config.toml` | User | Main Codex TOML configuration |
| `~/.codex/*.config.toml` | User | Codex profile v2 files |
| `~/.codex/rules/` | User | Codex rule files |
| `~/.codex/auth.json` | User | Auth status only; raw contents are never returned |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, style, and PR guidelines.

API documentation is available at http://localhost:8000/docs when running the dev server.

## Feedback

If you use Claude Code heavily, issues and feature requests are especially welcome.

## Built By

[Adrian](https://github.com/adrirubio) (13) and [Juan](https://github.com/juanrubio) during the 2025 Christmas break as a learning project — to explore open source, Claude Code, and full-stack development together.

## Acknowledgments

The session transcript viewer was inspired by and includes code adapted from [claude-code-transcripts](https://github.com/simonw/claude-code-transcripts) by [Simon Willison](https://simonwillison.net/).

The usage tracking feature ports algorithms from [ccusage](https://github.com/ryoppippi/ccusage) by [ryoppippi](https://github.com/ryoppippi), including session block identification, tiered pricing, and burn rate projections.

## Disclaimer

Claude Deck is a community project and is not affiliated with or endorsed by Anthropic.

## License

MIT License
