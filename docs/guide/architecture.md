# Architecture

Claude Deck is a full-stack application with a Python backend and React frontend.

## Overview

```
┌─────────────────────────┐     ┌─────────────────────────┐
│   Frontend (React 19)   │────▶│   Backend (FastAPI)      │
│   Port 5173 (dev)       │     │   Port 8000              │
│   Vite + TypeScript     │     │   Python 3.11+           │
│   shadcn/ui + Tailwind  │     │   SQLAlchemy + SQLite    │
└─────────────────────────┘     └──────────┬──────────────┘
                                           │
                                    ┌──────▼──────┐
                                    │ ~/.claude/   │
                                    │ $CODEX_HOME  │
                                    │ provider CLI │
                                    └─────────────┘
```

## Backend

**Stack:** FastAPI + async SQLAlchemy + aiosqlite + SQLite

```
backend/
├── app/
│   ├── main.py          # FastAPI app, CORS, lifespan
│   ├── config.py        # Settings (code defaults; environment or backend/.env)
│   ├── database.py      # Async SQLAlchemy engine, session, compatibility steps
│   ├── api/v1/          # Route modules
│   │   └── router.py    # Aggregates all routes
│   ├── models/
│   │   ├── database.py  # SQLAlchemy ORM models
│   │   └── schemas.py   # Pydantic request/response models
│   ├── services/        # Business logic services
│   └── utils/           # Path and file utilities
```

### API Design

All routes live under `/api/v1/`. The frontend's Vite dev server proxies `/api` requests to the backend at `http://localhost:8000`.

`router.py` defines `/health` and includes these route modules:

- Native and configuration modules: `config`, `codex_config`, `providers`, `projects`, `cli`, `mcp` (`/mcp`), `commands`, `plugins`, `hooks`, `permissions`, `agents`, `backup`, `output_styles`, `statusline`, `sessions`, `usage`, `memory`, `context`, `plans`, `status`
- Coordination modules: `agent_mail` (`/agent-mail`), `external_agent_mail` (`/external/agent-mail`), `agent_bridge` (`/agent-bridge`), `cc_bridge` (`/cc-bridge`)
- Team and factory modules: `agent_teams` (`/agent-teams`, which also includes the `factory_delivery` routes), `github_coordination`, `github_work_progress` and `factory_maintenance` (all under `/agent-teams`), and `factory` (`/factory`)

### Provider Boundaries

Claude Deck keeps shared terminal viewing in Agent Bridge and pushes provider-specific behavior into provider modules, config services, diagnostics, and backup policy. The UI reads provider capabilities before showing controls so Codex users do not land on Claude-only mutation pages.

Codex diagnostics are intentionally privacy-conservative. History, model cache, and SQLite files are not product data sources; diagnostics may summarize shape and parse state but must not expose prompt text, raw cache payloads, or SQLite contents.

### Database

SQLite at `backend/claude_registry.db`, auto-created on first run via `create_all()`. There is no general migration framework. At startup, Deck then runs SQLite compatibility steps that add listed missing columns and indexes in place, and records named one-time data migrations in the `deck_compat_migrations` table. Do not delete the database to upgrade; existing data stays in place. Back up the database before an upgrade. The compatibility steps do not support downgrade or rollback, and a repair step stops when it finds duplicate constrained rows.

## Frontend

**Stack:** React 19 + Vite 7 + TypeScript + TailwindCSS + shadcn/ui

```
frontend/src/
├── App.tsx              # Routes
├── features/            # Feature modules
│   └── <feature>/
│       ├── *Page.tsx    # Main page component
│       ├── components/  # Feature-specific components
│       ├── api.ts       # API calls
│       └── types.ts     # TypeScript types
├── components/
│   ├── layout/          # Sidebar, header
│   ├── shared/          # Reusable components
│   └── ui/              # shadcn/ui primitives
├── hooks/               # Custom React hooks
├── contexts/            # React contexts (Dashboard, Project, Provider, Sidebar, Theme)
├── types/               # Shared TypeScript types
└── lib/                 # API client, constants, utilities
```

### Feature Modules

Each feature is self-contained in `frontend/src/features/<name>/` with its own page component, sub-components, API functions, and types.

### State Management

- **ProjectContext** — tracks the active project, persists across navigation
- **DashboardContext** — caches dashboard stats, refreshes on demand or project change
- **ThemeContext** — dark/light mode
- **React Router** — client-side routing with sidebar navigation

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| SQLite over Postgres | Simple deployment, no external database needed |
| Code defaults for settings | The dashboard starts without a `.env` file; factory polling and operator-protected actions need host settings |
| Feature modules | Isolate each feature's code for maintainability |
| shadcn/ui | Copy-paste components, full control over styling |
| Async SQLAlchemy | Non-blocking database access in FastAPI |
