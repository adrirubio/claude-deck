# Claude Deck

Web app for managing Claude Code configurations, MCP servers, commands, plugins, hooks, and permissions.

## Commands

```bash
# Install
./scripts/install.sh             # Setup venv, install deps, create dirs (requires Python 3.11+, Node 18+)

# Development
./scripts/dev.sh                 # Start both backend + frontend servers
cd backend && source venv/bin/activate && uvicorn app.main:app --reload --port 8000  # Backend only
cd frontend && npm run dev       # Frontend only (port 5173)

# Build
./scripts/build.sh               # Production frontend build → frontend/dist
cd frontend && npm run build     # Same as above

# Test
cd backend && source venv/bin/activate && pytest tests/  # Python tests
bash backend/test_commands_api.sh                         # Curl-based API tests

# Lint
cd frontend && npm run lint      # ESLint

# Version
./scripts/bump-version.sh <major|minor|patch>  # Sync version across VERSION, package.json, pyproject.toml
```

## Architecture

```
backend/                  # FastAPI + async SQLAlchemy + aiosqlite
├── app/
│   ├── main.py          # FastAPI app, CORS, lifespan
│   ├── config.py        # pydantic-settings (defaults in code, no .env required)
│   ├── database.py      # Async SQLAlchemy engine + session
│   ├── api/v1/          # 17 route modules (router.py aggregates all)
│   ├── models/          # database.py (ORM), schemas.py (Pydantic)
│   ├── services/        # 18 service files (business logic)
│   └── utils/           # path_utils, file_utils

frontend/                 # React 19 + Vite + TypeScript + shadcn/ui
├── src/
│   ├── App.tsx          # Routes (17 pages)
│   ├── features/        # Feature modules (16 dirs, each with page + components + API + types)
│   ├── components/      # layout/, shared/, ui/ (19 shadcn components)
│   ├── hooks/           # useApi, useProjects, useSessionsApi, useUsageApi
│   ├── contexts/        # ProjectContext, ThemeContext
│   ├── types/           # Shared TypeScript types (15 files)
│   └── lib/             # api.ts, constants.ts, utils.ts
```

### Features

Config, MCP Servers, Commands, Plugins, Hooks, Permissions, Agents, Skills, Memory, Projects, Backup, Output Styles, Status Line, Sessions, Usage, Dashboard

### API Routes

All under `/api/v1/`: health, config, projects, cli, mcp, commands, plugins, hooks, permissions, agents, backup, output-styles, statusline, sessions, usage, memory

## Key Decisions

- **Backend**: FastAPI + async SQLAlchemy + aiosqlite + SQLite
- **Frontend**: React 19 + Vite 7 + TypeScript + TailwindCSS + shadcn/ui
- **Database**: SQLite at `backend/claude_registry.db` (auto-created via `create_all`, no migrations)
- **API**: RESTful `/api/v1/`, Vite proxies `/api` → `http://localhost:8000`
- **CORS**: `localhost:5173`

## Code Style

- **Frontend**: ESLint + TypeScript strict mode (`noUnusedLocals`, `noUnusedParameters`). Path alias `@/*` → `./src/*`
- **Backend**: Type hints throughout, async/await patterns, pydantic models for validation

## UI Conventions

- **Clickable cards**: All clickable Card components must use the `CLICKABLE_CARD` constant from `@/lib/constants`. This gives a consistent `border-2 hover:border-primary/50` green border hover effect, plus `cursor-pointer`, `transition-colors`, and `focus-visible:ring-2` for keyboard a11y. Action buttons inside clickable cards must use `e.stopPropagation()` and keyboard handlers must support Enter/Space.
- **Modal sizes**: Use `MODAL_SIZES.SM`, `MODAL_SIZES.MD`, or `MODAL_SIZES.LG` from `@/lib/constants` for dialog sizing.
- **Markdown rendering**: Use `<MarkdownRenderer>` from `@/components/shared/MarkdownRenderer` for read-only markdown display. Use `<MarkdownPreviewToggle>` from `@/components/shared/MarkdownPreviewToggle` for editable markdown with Edit/Preview tabs.

## CI/CD

Three GitHub Actions workflows in `.github/workflows/`:
- `claude.yml` — Claude Code integration (triggers on @claude mentions)
- `claude-code-review.yml` — Automated code review
- `release.yml` — Manual release (builds frontend, creates GitHub release)

## Gotchas

- No `.env` file needed — all config has defaults in `backend/app/config.py`
- Database lives at `backend/claude_registry.db`, created automatically on first run
- No database migration system — schema changes require deleting the db
- Frontend tests not yet set up
- Backups stored in `~/.claude-registry/backups/`
