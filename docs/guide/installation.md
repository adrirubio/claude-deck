# Installation

## Docker (Recommended)

The fastest way to run Claude Deck:

```bash
git clone https://github.com/adrirubio/claude-deck.git
cd claude-deck
docker compose up
```

This builds and starts Claude Deck at `http://localhost:8000`, mounting your `~/.claude` and `~/.claude.json` configuration files.

::: tip
The container mounts your home directory's Claude Code configuration. The container runs as root to access these files; adjust permissions if running as a non-root user.
:::

## Manual Installation

### Prerequisites

- **Python 3.11+**
- **Node.js 18+**

### Steps

1. Clone the repository:

```bash
git clone https://github.com/adrirubio/claude-deck.git
cd claude-deck
```

2. Run the install script:

```bash
./scripts/install.sh
```

This script:
- Creates a Python virtual environment in `backend/venv/`
- Installs Python dependencies from `backend/requirements.txt`
- Installs Node.js dependencies in `frontend/`
- Installs documentation dependencies in `docs/`
- Creates required directories

3. Verify the installation:

```bash
# Check backend
(cd backend && source venv/bin/activate && python -c "import fastapi; print('Backend OK')")

# Check frontend and docs
./scripts/build.sh
```

## Configuration

Claude Deck requires no configuration files — all settings have sensible defaults defined in `backend/app/config.py`. The SQLite database is created automatically on first run at `backend/claude_registry.db`.

## What Gets Read

Claude Deck reads these Claude Code configuration files:

| File/Directory | Scope | Description |
|----------------|-------|-------------|
| `~/.claude.json` | User | OAuth, caches, MCP servers |
| `~/.claude/settings.json` | User | User settings, permissions |
| `~/.claude/settings.local.json` | User | Local overrides |
| `~/.claude/commands/` | User | User slash commands |
| `~/.claude/agents/` | User | User agents |
| `~/.claude/skills/` | User | User skills |
| `~/.claude/projects/` | User | Session transcripts & usage |
| `.claude/settings.json` | Project | Project settings |
| `.claude/commands/` | Project | Project commands |
| `.mcp.json` | Project | Project MCP servers |
| `CLAUDE.md` | Project | Project instructions |
