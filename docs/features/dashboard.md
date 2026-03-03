# Dashboard

The dashboard provides an at-a-glance overview of your entire Claude Code configuration with 12 information cards organized in a responsive grid.

## Overview

When you open Claude Deck, the dashboard aggregates data from 12 API endpoints in parallel and displays:

- **Projects** — number of tracked project directories
- **MCP Servers** — configured server count
- **Commands** — available slash commands
- **Plugins** — installed plugins
- **Hooks** — automation hooks
- **Permissions** — total permission rules
- **Agents** — custom agents across all scopes
- **Skills** — available skills
- **Output Styles** — custom output formats
- **Sessions** — total count with today/this week breakdown and most active project
- **Plans** — execution plan count
- **Context Window** — highest context usage across active sessions with a color-coded progress bar

A **Quick Status** card at the bottom shows settings key count and allow/deny rule breakdown.

## How to Use

### Viewing Data

All cards update together. The dashboard shows project-scoped data for the currently selected project — switch projects using the sidebar selector.

### Context Window Indicator

The context window card shows the highest context usage percentage across all active Claude Code sessions:

| Color | Range | Meaning |
|-------|-------|---------|
| Green | 0–49% | Plenty of room |
| Yellow | 50–79% | Getting used |
| Orange | 80–94% | Running low |
| Red | 95–100% | Nearly full |

### Refreshing

Click the **refresh button** in the top-right corner to reload all data. The dashboard caches data between page navigations — navigating away and back shows cached data instantly without a loading flash.

A relative timestamp ("Updated 2m ago") next to the refresh button shows when data was last fetched.

### Navigation Links

Several cards include links to jump to their full page:
- "View all sessions →" on the Sessions card
- "View context →" on the Context Window card
- "View all plans →" on the Plans card

## Configuration

The dashboard has no dedicated configuration. It reads data from all other features. The active project (set via sidebar) determines the scope for MCP servers, commands, hooks, and permissions.

## Tips

- **Data is cached** — switching pages doesn't trigger a re-fetch. Click refresh for fresh data.
- **Project switching** automatically re-fetches dashboard data for the new project.
- **First visit** shows a loading skeleton while data loads. Subsequent visits show cached data.
