# Backup & Restore

Create and manage configuration backups with selective component restore.

## Overview

The Backup page lets you create ZIP archives of your Claude Code configuration, restore from backups, and manage backup history.

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

### Managing Backups

- **Download** — save the ZIP archive to your local machine
- **Delete** — remove a backup from the system

Stat cards at the top show total backups, combined size, and count with external dependencies.

## Configuration

Backups are stored in `~/.claude-registry/backups/` as ZIP files with a JSON manifest containing metadata, component list, and dependency information.

## Tips

- **Regular backups** before major configuration changes protect against mistakes.
- The dependency checker warns you about plugins or MCP servers that need to be installed before restoring.
- Backups include platform info — restore warnings may appear when moving between operating systems.
