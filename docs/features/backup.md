# Backup & Restore

Create and manage configuration backups with selective component restore.

## Overview

The Backup page lets you create ZIP archives of your Claude Code configuration, restore from Claude Code backups, create redacted Codex exports, and manage backup history.

## How to Use

### Creating a Backup

Click **"Create Backup"** to open the wizard:

1. **Select components** — choose what to include:
   - Agents
   - Skills
   - Commands
   - Plugins
   - Hooks
   - Rules
   - MCP server configs
2. **Name & Description** — label your backup
3. Click create to generate the ZIP archive

### Restoring from Backup

Click **Restore** on any backup to open the restore wizard:

1. Review the backup contents and component list
2. Check for dependency warnings (missing plugins or MCP servers)
3. Confirm the restore

::: warning
Restoring overwrites existing configuration files for the selected components. Make a backup of your current configuration first if needed.
:::

Codex backups are export-only. The restore plan can show archive contents and explain why automatic restore is refused, but Claude Deck does not extract Codex exports back into `CODEX_HOME`.

### Managing Backups

- **Download** — save the ZIP archive to your local machine
- **Delete** — remove a backup from the system

Stat cards at the top show total backups, combined size, and count with external dependencies.

## Configuration

Backups are stored in `~/.claude-registry/backups/` as ZIP files with a JSON manifest containing metadata, component list, and dependency information.

### Codex Export Scope

Codex exports include redacted `config.toml`, redacted `*.config.toml` profile files, redacted `rules/*.rules` files, and redacted provider inventory metadata.

Codex exports exclude `auth.json`, `history.jsonl`, `models_cache.json`, SQLite state, SQLite sidecar files, raw prompt text, and raw cache payloads. Automatic restore is refused because these exports intentionally omit provider state and because Codex does not currently expose a stable provider-owned restore API.

## Tips

- **Regular backups** before major configuration changes protect against mistakes.
- The dependency checker warns you about plugins or MCP servers that need to be installed before restoring.
- Backups include platform info — restore warnings may appear when moving between operating systems.
