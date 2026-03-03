# Usage Tracking

Monitor token usage, costs, and billing blocks with daily and monthly charts.

## Overview

The Usage page aggregates token usage data from Claude Code sessions and displays costs, trends, and billing block analysis.

## How to Use

### Overview Tab

Summary cards show total tokens, total cost, and key metrics. A daily chart plots usage over time.

### Daily Tab

Detailed daily usage and cost graphs broken down by token type:

- **Input tokens** — prompt tokens sent to Claude
- **Output tokens** — response tokens from Claude
- **Cache creation** — tokens written to cache
- **Cache read** — tokens read from cache

### Sessions Tab

A sortable table listing individual sessions with columns for date, model, input/output tokens, and estimated cost.

### Monthly Tab

Month-over-month trend charts showing usage and cost patterns.

### Blocks Tab

View billing blocks — 5-hour usage windows that Anthropic uses for billing:

- Current active block with time remaining
- Recent completed blocks with token totals and costs

### Filtering

Use the **project filter** dropdown to view usage for a specific project or across all projects.

## Configuration

Usage data is read-only. Claude Code stores usage records in:

```
~/.claude/projects/{project-folder}/usage/*.jsonl
```

Claude Deck caches parsed usage data in localStorage with a 5-minute TTL for instant page loads on return visits.

## Tips

- **Cache tokens** (creation + read) can significantly impact costs — monitor the breakdown.
- **Billing blocks** show 5-hour windows — useful for understanding burst usage patterns.
- Costs are calculated using per-model, per-token-type pricing.
- The page caches data client-side — click refresh for the latest numbers.
