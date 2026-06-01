# Plugins

Browse, install, enable/disable, and update Claude Code plugins.

## Overview

Plugins are packages that extend Claude Code with commands, skills, agents, MCP servers, and hooks. The Plugins page has three tabs:

- **Installed** — manage your installed plugins
- **Marketplace** — browse and install from configured marketplaces
- **All Available** — search across all marketplaces

## How to Use

### Viewing Installed Plugins

The Installed tab shows plugin cards with:

- Plugin name, version, and source badge
- Category and scope (user/project/local)
- Component summary (commands, skills, agents, etc.)
- Enable/disable toggle
- Update indicator (orange button when new version available)

Filter by status (enabled/disabled), update availability, or source.

### Installing Plugins

1. Switch to the **Marketplace** tab
2. Select a marketplace from the dropdown
3. Browse or search for plugins
4. Click a plugin card to preview its README and details
5. Click **Install** to open the wizard
6. Choose installation scope (user, project, or local)
7. Wait for installation to complete

### Updating Plugins

- Click **"Check Updates"** in the bulk actions bar to scan for new versions
- Update individual plugins with the orange update button on their card
- Use **"Update All"** to batch-update all outdated plugins

### Bulk Operations

The actions bar supports:
- **Check Updates** — scan all plugins for new versions
- **Update All** — update all outdated plugins at once
- **Enable All / Disable All** — toggle all plugins

## Configuration

| Location | Scope |
|----------|-------|
| `~/.claude/plugins/` | User plugins |
| `.claude/plugins/` | Project plugins |
| `~/.claude/settings.json` → `enabledPlugins` | Enable/disable state |

Marketplace URLs are configured in Claude Code settings.

## Codex CLI

When Codex is selected, plugin handling is provider-aware:

- Inventory comes from `codex plugin list`
- Install/remove operations use the Codex CLI when the installed CLI exposes safe commands
- Enable/disable is unsupported until Codex exposes a stable safe contract for it
- Raw plugin output is retained only after redacting secret-like values

Claude Code plugin pages remain the source of truth for Claude plugin enable/disable, marketplace browsing, updates, and settings-backed plugin state.

## Tips

- **Local plugins** can be uninstalled; marketplace plugins use enable/disable.
- Plugin cards show component counts so you can see what a plugin provides at a glance.
- Plugins can provide their own MCP servers — check the detail view for MCP badges.
