# Introduction

A self-hosted workspace to observe and intervene in bounded coding-agent attempts on GitHub issues, with mixed harnesses, visible policies and recovery controls.

## Find work needing attention

Use [Overview](/features/dashboard) for complete filtered counts and automation observations. Open [Work](/features/work) for owners, waiting reasons and PR context; inspect [Repositories](/features/repositories) for intake, polling and overlaps. Factory views include mixed harnesses by default and have their own URL filters.

Finished tracking is not a measured delivery outcome. Escalation or an operator stop does not prove process termination. Unknown observations remain unknown.

## Keep the actors separate

Agents propose plans for designated Leader decisions. Operators configure policies and perform protected interventions. Human PR review and merge follow repository policy. An eligible action is an observation, not authorization; the server checks the current principal and state again.

## Manual work and native configuration

[Harnesses](/features/harnesses) lists implemented native pages and manual entry points. [Teams](/features/agent-teams), [Live sessions](/features/agent-bridge) and [Agent Mail](/features/agent-mail) can be used without watching a repository or enabling autonomy. Native/project preferences do not select factory work. Coverage differs; see [Multi-Provider and Codex CLI](/guide/multi-provider-codex-v2).

## Current scope

This reference covers the product integration build; earlier packaged releases can retain the previous navigation. The operations/readiness catalog, guided setup and delivery audit charts are not included. Pilot participants, human benefit measurements and timing comparisons are unavailable; no pilot outcome is announced.

Repository setup uses current Teams and host/label procedures. Role text does not redesign Leader selection; the first enabled slot remains Leader.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.11+ with FastAPI |
| Frontend | React 19 + TypeScript 6 + Vite 7 |
| UI | shadcn/ui + Tailwind CSS |
| Charts | Recharts |
| Database | SQLite (async via SQLAlchemy + aiosqlite) |

## Next steps

- [Installation](/guide/installation)
- [Quick Start](/guide/quick-start)
- [Factory API](/api/factory)
- [Architecture](/guide/architecture)
