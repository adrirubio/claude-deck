# Installation

Claude Deck must run in the same environment where your agent CLIs and credentials are installed. Docker is not supported because containers cannot see host-installed CLIs, host tmux sessions, native agent credentials, or your real repository environment.

Older packaged releases can show the earlier configuration home page. Use the current source to evaluate the Overview and Work pages. The installation prerequisites still apply.

## Native Installation

### Prerequisites

- **Python 3.11+**
- **Node.js 18+**
- At least one supported local agent CLI installed on the same host:
  - Claude Code
  - Codex CLI
  - GitHub Copilot CLI
  - OpenCode CLI
  - Pi

Pi has additional requirements:

- Pi 0.87.1
- Node.js 22.19.0 or later
- The dependencies of the repository-local Agent Mail extension in `integrations/pi-agent-mail`, prepared before you launch Pi from Deck

Agent Mail has no Pi install action. Its **Pi Agent Mail** card on the Install tab only checks whether the extension is ready.

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

3. Start Claude Deck:

```bash
./scripts/dev.sh
```

Claude Deck starts the backend at `http://localhost:8000` and the frontend dev server at `http://localhost:5173`.

4. Verify the installation:

```bash
# Check backend
(cd backend && source venv/bin/activate && python -c "import fastapi; print('Backend OK')")

# Check frontend and docs
./scripts/build.sh
```

## Configuration

The dashboard and native pages start with the code defaults in `backend/app/config.py`. Settings can also come from environment variables or `backend/.env`. Factory polling (`github_token`) and operator-protected actions (`operator_token`) need host settings; see [Autonomous GitHub dispatch](/autonomy). The SQLite database is created automatically on first run at `backend/claude_registry.db`.

## Remote Use

For remote access, install and run Claude Deck natively on the remote host where the agents, credentials, repositories, and tmux sessions exist. Then connect from your browser over a trusted tunnel or network route.

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
