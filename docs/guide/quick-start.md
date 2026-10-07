# Quick Start

Start Deck, inspect existing work, or launch a manual session before deciding whether to connect a repository.

## Start the Dev Servers

```bash
./scripts/dev.sh
```

This starts:
- **Backend** at `http://localhost:8000` (API docs at `http://localhost:8000/docs`)
- **Frontend** at `http://localhost:5173`

Open `http://localhost:5173` in your browser.

To stop or restart the dev servers for this checkout:

```bash
./scripts/dev.sh stop
./scripts/dev.sh restart
```

## Observe existing work

Overview is the home page for tracking counts and automation observations across this backend. Use team, scope and harness filters on factory pages; native harness/project preferences do not filter work. Open [Work](/features/work) for an owner, waiting reason or PR. Open [Repositories](/features/repositories) to distinguish configured enablement from effective intake. An empty workload does not require enabling autonomy, and a read failure is not an empty factory.

## Launch manually or inspect configuration

Use Live sessions for standalone work or [Teams](/features/agent-teams) for a current launch plan. Reuse only sessions belonging to intended slots. Unbound adoption is an explicit operator review; opening a Work launch link starts nothing.

Use [Harnesses](/features/harnesses) for guarded native pages. Local projects scope supported native settings independently of factory filters. Other harnesses' integration capabilities do not create native editors.

## Connect a backlog with the current flow

Open Repositories and select **Set up a repository** for [guided configuration](/features/repositories#guided-configuration). It checks access and labels without changes, then saves an inactive team or uses an existing team, with a disabled scope. Launch and activation are separate, reviewed steps. You can also add an existing primary checkout in Teams > Autonomy.

The Leader is the team's explicit `leader_slot_id`. Guided setup names it for a new team; for an existing team, use **Set Leader** in the roster while automation is off. Slot order and Role text do not select it. Configure GitHub polling access on the host and dispatch/design/area labels on GitHub, as described in [Autonomous GitHub dispatch](/autonomy). Choose merge policy and finite budgets; review the enable confirmation only when ready.

The operator credential uses the existing per-tab flow, separately from GitHub polling access and authenticated agent sessions. No cookie login is included. Team/scope pause controls intake; inspect existing attempts separately rather than assuming processes stopped.

## Identify the Backend Instance

When you run Claude Deck on more than one machine, or expose it over a LAN or tailnet, set an instance name so each browser window clearly shows the backend it controls:

```bash
CLAUDE_DECK_INSTANCE_NAME="Studio Mac" \
CLAUDE_DECK_INSTANCE_ACCENT="blue" \
CLAUDE_DECK_INSTANCE_ID="studio-mac" \
./scripts/dev.sh --host 0.0.0.0
```

Use a trusted network or tunnel when binding to all interfaces. Protected roster, autonomy and recovery controls require their documented credentials; safe reads remain observational. Local trust is not remote multi-user isolation. A Vite dev UI on another origin needs that exact origin in the JSON `CORS_ORIGINS` setting; Deck's production UI is same-origin.

The instance name appears in the header, browser tab title, Agent Bridge terminal panes, and kill-session confirmations. Supported accents are `blue`, `green`, `purple`, `orange`, `red`, `pink`, `cyan`, and `slate`.

## Key pages

| Page | Purpose |
| --- | --- |
| [Overview](/features/dashboard) | Tracking counts and automation observations |
| [Work](/features/work) | Mixed-team details and current remedies |
| [Repositories](/features/repositories) | Watched scopes, intake, polling and overlaps |
| [Harnesses](/features/harnesses) | Guarded native settings and manual entry points |
| [Teams](/features/agent-teams) | Rosters, launch plans and current repository/autonomy configuration |
| [Live sessions](/features/agent-bridge) | Standalone sessions and explicit terminal interaction |
| [Agent Mail](/features/agent-mail) | Coordination and read-only work context |

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
