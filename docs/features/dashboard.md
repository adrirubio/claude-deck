# Dashboard

The dashboard provides an at-a-glance overview of the selected provider and active project. Claude Code has the richest metrics; Codex focuses on configuration, provider inventory, and live-session state that can be read without exposing prompt history or provider-owned cache data.

## Overview

When Claude Code is selected, the dashboard aggregates data from the Claude Code configuration and session APIs and displays:

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

When Codex CLI is selected, the dashboard switches to Codex-specific cards such as:

- **Codex Config** — safe config entries, profiles, projects, and feature settings
- **Codex MCP Servers** — configured MCP server inventory
- **Codex Plugins** — installed plugin inventory
- **Codex Feature Flags** — available and enabled feature flags
- **Codex Live Sessions** — sessions currently visible through Agent Bridge
- **Plan Snapshots** — Codex `update_plan` snapshots

Cards link to provider-appropriate pages. Claude Code-only surfaces such as usage costs, context windows, transcript browsing, memory, hooks, and permission pages are not shown as Codex data.

## How to Use

### Viewing Data

All cards update together. The dashboard shows data for the currently selected provider and active project — switch providers and projects using the sidebar selectors.

### Context Window Indicator

For Claude Code, the context window card shows the highest context usage percentage across all active Claude Code sessions:

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

The dashboard has no dedicated configuration. It reads data from all other features. The selected provider controls which cards are shown, and the active project determines the scope for project-aware cards.

## Tips

- **Data is cached** — switching pages doesn't trigger a re-fetch. Click refresh for fresh data.
- **Provider and project switching** automatically re-fetch dashboard data for the new selection.
- **First visit** shows a loading skeleton while data loads. Subsequent visits show cached data.
