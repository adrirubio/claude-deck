# Claude Deck

Web app for managing Claude Code configurations, MCP servers, commands, plugins, hooks, and permissions.

## Completed Stages

| Stage | Name | Status |
|-------|------|--------|
| 1 | Backend Foundation | ✓ |
| 2 | Frontend Foundation | ✓ |
| 3 | Config Service | ✓ |
| 4 | Config Viewer UI | ✓ |
| 5 | Project Management | ✓ |
| 6 | CLI Executor | ✓ |
| 7 | MCP Backend | ✓ |
| 8 | MCP Frontend | ✓ |
| 9 | Commands Backend | ✓ |
| 10 | Commands Frontend | ✓ |
| 11 | Plugins Backend | ✓ |
| 12 | Plugins Frontend | ✓ |
| 13 | Hooks Backend | ✓ |
| 14 | Hooks Frontend | ✓ |
| 15 | Permissions Backend | ✓ |
| 16 | Permissions Frontend | ✓ |
| 17-21 | Remaining | Pending |

## Architecture

```
backend/                 # FastAPI + SQLAlchemy + SQLite
├── app/
│   ├── main.py         # FastAPI app with CORS
│   ├── config.py       # pydantic-settings
│   ├── database.py     # Async SQLAlchemy
│   ├── api/v1/         # API routes
│   ├── models/         # DB models
│   ├── services/       # Business logic (config, mcp, commands, plugins, hooks, permissions)
│   └── utils/          # path_utils, file_utils

frontend/               # React + Vite + TypeScript + shadcn/ui
├── src/
│   ├── components/     # UI components
│   ├── pages/          # Route pages (Dashboard, MCP, Commands, Plugins, Hooks, Permissions)
│   └── services/       # API clients
```

## Quick Start

```bash
# Backend
cd backend && source venv/bin/activate
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend && npm run dev
```

## Build Script

```bash
./scripts/build-all.sh           # Run all stages
./scripts/build-all.sh 16 16     # Run specific stage
FORCE_RERUN=1 ./scripts/build-all.sh 1 1  # Force rerun
```

Requires: tmux, claude (or clode for Bedrock)

## Key Decisions

- **Backend**: FastAPI + async SQLAlchemy + aiosqlite
- **Frontend**: React 18 + Vite + TypeScript + TailwindCSS + shadcn/ui
- **Database**: SQLite
- **API**: RESTful `/api/v1/`
- **CORS**: `localhost:5173`

---
*Last Updated: 2026-01-01*
