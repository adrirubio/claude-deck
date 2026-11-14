# Installation

Albiex Synth City must run in the same environment where your agent CLIs and credentials are installed. Docker is not supported because containers cannot see host-installed CLIs, host tmux sessions, native agent credentials, or your real repository environment.

Synth City includes the Overview, Work, Repositories and Harnesses pages (added in 3.0.0). Older packaged releases can show the earlier configuration home page. The installation prerequisites still apply.

## Native Installation

### Prerequisites

- **Python 3.11+**
- **Node.js 22.12+**
- At least one supported local agent CLI installed on the same host:
  - Claude Code
  - Codex CLI
  - GitHub Copilot CLI
  - OpenCode CLI 2 or later
  - Pi

Synth City requires OpenCode 2 or later. It reads the version from `opencode --version` (for example `opencode v2.0.29` or `2.0.29`). With OpenCode 1, or a version it cannot read, the OpenCode harness shows a blocked configuration with the reason "OpenCode 2 or later is required", and OpenCode team members cannot launch.

Pi has additional requirements:

- Pi 0.87.1
- Node.js 22.19.0 or later
- The dependencies of the repository-local Agent Mail extension in `integrations/pi-agent-mail`, prepared before you launch Pi from Synth City

Agent Mail has no Pi install action. Its **Pi Agent Mail** card on the Install tab only checks whether the extension is ready.

### Steps

1. Clone the repository:

```bash
git clone https://github.com/albiexai/synth-city.git
cd synth-city
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

3. Start Synth City:

```bash
./scripts/dev.sh
```

Synth City starts the backend at `http://localhost:8000` and the frontend dev server at `http://localhost:5173`.

4. Verify the installation:

```bash
# Check backend
(cd backend && source venv/bin/activate && python -c "import fastapi; print('Backend OK')")

# Check frontend and docs
./scripts/build.sh
```

## Upgrade and Rollback

Synth City runs from a clone of the repository. An upgrade changes the source. It keeps your database, your operator and GitHub settings in `backend/.env`, and your agent configuration files.

### Upgrading from v3.1 to v4.0.0

Version 4.0.0 is the rename release, and its upgrade renames data and settings as well as the product. Follow [Moving to Albiex Synth City v4.0.0](/guide/migration-v4) for that upgrade, including its complete backup and restore contract. Do not use the historical procedure below for a v4 upgrade: its filenames predate the rename.

### Historical procedure (v3.0.0 and earlier)

The steps below are the upgrade and rollback procedure as written for v3.0.0 and earlier versions, kept for those versions. They use the database filename from before the rename, `backend/claude_registry.db`. Do not pair them with a v4 checkout.

#### Upgrade (historical)

1. Stop the application.
2. Copy the database while it is stopped. The database uses SQLite WAL mode, so committed data can be in the `-wal` file. Use the SQLite backup command and keep the copy outside the repository:

```bash
sqlite3 backend/claude_registry.db ".backup '$HOME/claude_registry.db.before-3.0.0'"
```

Without `sqlite3`, copy `claude_registry.db`, `claude_registry.db-wal` and `claude_registry.db-shm` together. If `DATABASE_URL` in `backend/.env` sets another database path, back up that database.

3. Copy `backend/.env` if you have one. Also create a Backup in the Backup page if you plan to edit agent configuration.
4. Update the source and install the dependencies:

```bash
git fetch --tags
git checkout v3.0.0
./scripts/install.sh
```

5. Start the application with `./scripts/dev.sh`.

Do not delete the database. At startup, the application adds the listed missing columns and indexes in place and records one-time data migrations. The first start after an upgrade also installs one audit coverage marker. See [Factory audit and metrics](/guide/factory-audit-and-metrics).

#### Rollback (historical)

The startup steps do not support downgrade. To roll back, restore the copy you made before the upgrade:

1. Stop the application.
2. Check out the earlier version. For example, `git checkout v2.0.1`, then run `./scripts/install.sh`.
3. Remove `backend/claude_registry.db-wal` and `backend/claude_registry.db-shm`. A stale file from 3.0.0 can damage the restored database. Then replace `backend/claude_registry.db` with your copy, for example `~/claude_registry.db.before-3.0.0`.
4. Keep `backend/.env` unchanged. Start the application.

Records written after the upgrade are not in the copy. They are lost when you restore it. Rollback does not change your agent configuration files. Use the Backup page to restore those files.

## Configuration

The dashboard and native pages start with the code defaults in `backend/app/config.py`. Settings can also come from environment variables or `backend/.env`. Factory polling (`github_token`) and operator-protected actions (`operator_token`) need host settings; see [Autonomous GitHub dispatch](/autonomy). The SQLite database is created automatically on first run at `backend/synth_city.db`.

## Remote Use

For remote access, install and run Synth City natively on the remote host where the agents, credentials, repositories, and tmux sessions exist. Then connect from your browser over a trusted tunnel or network route.

## Separate controller and agent users

If the controller and the agents run as different operating-system users, the operator must set up one `sudoers` rule for the cross-user terminal attach: turn `use_pty` off for the agent `tmux` command only. Synth City does not change `sudoers`. See [What you must set up: a command-scoped `!use_pty`](/features/agent-bridge#what-you-must-set-up-a-command-scoped-use_pty) and, for the rest of this layout, [Deployment with separate controller and agent users](/features/agent-teams#deployment-with-separate-controller-and-agent-users).

## What Gets Read

Synth City reads these Claude Code configuration files:

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
