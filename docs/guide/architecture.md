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
                                    │  ~/.claude/  │
                                    │  Claude Code │
                                    │  config files│
                                    └─────────────┘
```

## Backend

**Stack:** FastAPI + async SQLAlchemy + aiosqlite + SQLite

```
backend/
├── app/
│   ├── main.py          # FastAPI app, CORS, lifespan
│   ├── config.py        # Settings (defaults in code, no .env needed)
│   ├── database.py      # Async SQLAlchemy engine + session
│   ├── api/v1/          # 17 route modules
│   │   └── router.py    # Aggregates all routes
│   ├── models/
│   │   ├── database.py  # SQLAlchemy ORM models
│   │   └── schemas.py   # Pydantic request/response models
│   ├── services/        # 18 service files (business logic)
│   └── utils/           # Path and file utilities
```

### API Design

All routes live under `/api/v1/`. The frontend's Vite dev server proxies `/api` requests to the backend at `http://localhost:8000`.

Route modules: `health`, `config`, `projects`, `cli`, `mcp`, `commands`, `plugins`, `hooks`, `permissions`, `agents`, `backup`, `output-styles`, `statusline`, `sessions`, `cc-bridge`, `usage`, `memory`

### Database

SQLite at `backend/claude_registry.db`, auto-created on first run via `create_all()`. No migration system — schema changes require deleting the database.

## Frontend

**Stack:** React 19 + Vite 7 + TypeScript + TailwindCSS + shadcn/ui

```
frontend/src/
├── App.tsx              # Routes (17 pages)
├── features/            # Feature modules (16 directories)
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
├── contexts/            # React contexts (Project, Theme, Dashboard)
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
| No `.env` file | All defaults in code, zero-config startup |
| Feature modules | Isolate each feature's code for maintainability |
| shadcn/ui | Copy-paste components, full control over styling |
| Async SQLAlchemy | Non-blocking database access in FastAPI |
