# Claude Deck Launch Posts

Post on a **Tuesday, Wednesday, or Thursday**.

## Launch Principle

Lead with the product. The father/son story matters, but it should support the launch, not carry it.

Claude Deck is interesting because it solves a real Claude Code problem:
**config and visibility are fragmented once your setup gets serious**.

## Recommended Launch Order (if launching today)

1. **X/Twitter thread** — easiest place to get the first reactions and shares
2. **r/ClaudeAI** — most targeted audience
3. **Hacker News (Show HN)** — highest upside, but only post when repo/README/screenshots are fully ready and you can stay around to reply

If energy is limited, do **those three today** and treat the rest as follow-on distribution over the next few days.

---

## Posting Schedule (Madrid Time)

### TIER 1 - Launch Day
| # | Channel | Madrid Time | ET | Note |
|---|---------|-------------|----|------|
| 1 | X/Twitter thread | 17:30-18:00 | 11:30 AM-12:00 PM | Start here, build momentum |
| 2 | r/ClaudeAI | 18:00-18:30 | 12:00-12:30 PM | Targeted, relevant audience |
| 3 | Hacker News (Show HN) | 18:30-19:00 | 12:30-1:00 PM | Post only when you're ready to engage |

### TIER 2 - Next Day
| # | Channel | Madrid Time | ET | Note |
|---|---------|-------------|----|------|
| 4 | r/SelfHosted | 15:00 | 9:00 AM | Strong fit for local-first / no-cloud angle |
| 5 | LinkedIn | 14:00 | 8:00 AM | Personal builder story plays well here |
| 6 | Anthropic Forum | 16:30 | 10:30 AM | Product-specific audience |
| 7 | r/OpenSource | 15:45 | 9:45 AM | Good for the build story and OSS angle |

### TIER 3 - Days 3-7 (one or two per day)
| # | Channel | Madrid Time | ET | Note |
|---|---------|-------------|----|------|
| 8 | r/webdev | 15:00 | 9:00 AM | Focus on stack + lessons learned |
| 9 | r/sideproject | 15:45 | 9:45 AM | Focus on Christmas-break / father-son build |
| 10 | r/coolgithubprojects | 15:00 | 9:00 AM | Short + link-driven |
| 11 | Bluesky | 15:00 | 9:00 AM | Mirror/adapt X thread |

---

## TIER 1 - Launch Day

---

### 1. X/Twitter Thread -- first post today

**Tweet 1:**
We built a self-hosted web dashboard for Claude Code.

Claude Deck gives you one place to manage MCP servers, slash commands, hooks, agents, usage, transcripts, and more — without digging through JSON files.

Built by me and my 13yo son Adrian.
https://github.com/adrirubio/claude-deck

[attach dashboard screenshot]

**Tweet 2:**
Once your Claude Code setup grows, config gets fragmented fast:
- `~/.claude.json`
- `~/.claude/settings.json`
- `.mcp.json`
- commands / agents / skills / project files

Claude Deck puts it behind a local web UI. No cloud, no account, no telemetry.

[attach MCP servers screenshot]

**Tweet 3:**
What it covers:
- MCP servers (test, enable/disable, OAuth, inspect tools/resources/prompts)
- slash commands, hooks, permissions, agents, skills, memory
- usage tracking with cost charts
- session transcripts and plan history
- CC Bridge for Claude Code tmux sessions
- backup & restore

**Tweet 4:**
Stack: FastAPI + React 19 + TypeScript + shadcn/ui + SQLite.

Claude Code generated a lot of the implementation. We handled product direction, architecture, review, and fixes.

**Tweet 5:**
Started as a Christmas-break project. Adrian usually builds hardware — ESP32 sensors, Raspberry Pi projects, that sort of thing.

Now it’s open source:
https://github.com/adrirubio/claude-deck

Feedback welcome. @AnthropicAI

---

### 2. r/ClaudeAI -- after X/Twitter

**Cross-posting verdict:** Yes, acceptable. This is the strongest Reddit fit. Keep it practical and product-focused.

**Title:** We built a self-hosted web dashboard for managing Claude Code

**Text:**
My son Adrian (13) and I have been building **Claude Deck**, a self-hosted web dashboard for managing Claude Code.

If you use Claude Code heavily, you know the setup starts simple and then gradually sprawls across config files and directories: `~/.claude.json`, `~/.claude/settings.json`, `.mcp.json`, slash commands, agents, skills, project config, transcripts.

Claude Deck gives you one place to manage all of that through a local web UI.

**What it covers:**
- **MCP servers**: add, edit, test, enable/disable, OAuth, inspect tools/resources/prompts
- **Slash commands, hooks, permissions, agents, skills, memory, output styles, status line**
- **Usage tracking**: token usage, costs, billing blocks, charts
- **Session transcripts** and **plan history**
- **CC Bridge** for monitoring Claude Code tmux sessions
- **Backup & restore**

Tech stack: FastAPI + React 19 + TypeScript + shadcn/ui + SQLite.
Runs locally. No cloud, no account, no telemetry.

Claude Code generated a lot of the implementation. We handled the product direction, architecture, review, and fixes.

This started as a Christmas-break project so Adrian could learn how a real software project comes together. He normally builds hardware, and this became his biggest software project so far.

MIT licensed. Open source.

GitHub: https://github.com/adrirubio/claude-deck

Would love feedback from people actually using Claude Code. What’s missing? What would you want next?

---

### 3. Hacker News (Show HN) -- only when you're ready to stay engaged

**Preferred titles:**
- **Show HN: Claude Deck – a self-hosted dashboard for Claude Code**
- **Show HN: Claude Deck – web UI for Claude Code config, MCP servers and usage**
- **Show HN: Claude Deck – manage Claude Code from a local dashboard**

**Text:**
Hi HN — I’m Juan. My son Adrian and I built **Claude Deck**, a self-hosted web dashboard for managing Claude Code.

If you use Claude Code seriously, the configuration surface gets fragmented pretty quickly: `~/.claude.json`, `~/.claude/settings.json`, `.mcp.json`, slash commands, agents, skills, project config, usage data, transcripts.

Claude Deck puts that behind a local web UI.

What it covers:
- MCP servers: add, edit, test connections, enable/disable, OAuth, inspect tools/resources/prompts
- Slash commands, hooks, permissions, agents, skills, memory, output styles, status line
- Usage tracking with daily/monthly cost charts and billing blocks
- Session transcripts and plan history
- CC Bridge for monitoring Claude Code tmux sessions
- Backup & restore

Tech stack is FastAPI + React 19 + TypeScript + shadcn/ui + SQLite.
It runs locally, with no cloud, no account, and no telemetry.

We built it over Christmas break as a learning project. Adrian is 13 and usually builds hardware — ESP32 sensors, Raspberry Pi projects, that sort of thing. This was his biggest software project so far.

We were also pretty direct about using AI tools: Claude Code generated a lot of the implementation. We still made the product decisions, architecture calls, reviewed the code, and fixed issues, but using Claude Code is a big part of how we got from idea to working full-stack app quickly.

It’s MIT licensed and open source:
https://github.com/adrirubio/claude-deck

Would love feedback — especially from people using Claude Code heavily. What feels most useful here, and what’s still missing?

---

## TIER 2 - Day 1-2

---

### 4. r/SelfHosted -- next day

**Cross-posting verdict:** Yes, acceptable if you emphasize local-first/self-hosted properties and avoid sounding like generic SaaS promo.

**Title:** Claude Deck - self-hosted dashboard for Claude Code (local-only, SQLite, no cloud)

**Text:**
My son and I built **Claude Deck**, a self-hosted web dashboard for managing Claude Code.

If you use Claude Code, this gives you a local UI for the config files and metadata that otherwise live across your filesystem.

**Self-hosted basics:**
- local only
- no cloud
- no account
- no telemetry
- SQLite
- reads and writes existing Claude Code config files
- Docker / Docker Compose support
- FastAPI + React frontend

**What it manages:**
- MCP servers
- slash commands
- hooks
- permissions
- agents
- skills
- memory
- usage/cost tracking
- session transcripts
- backup & restore
- CC Bridge for tmux-based Claude Code sessions

It’s open source and MIT licensed:
https://github.com/adrirubio/claude-deck

Curious what the self-hosted crowd would want from something like this.

---

### 5. LinkedIn -- next day

**Text:**
Over Christmas break, my son Adrian (13) and I built **Claude Deck**, a self-hosted web dashboard for managing Claude Code.

The product solves a pretty specific problem: once your Claude Code setup grows, configuration and visibility get fragmented. MCP servers, slash commands, hooks, permissions, agents, skills, transcripts, usage data — it’s all there, but spread across files and folders.

Claude Deck gives you one local interface to manage it.

A few things Adrian learned through the project:
- how a full-stack codebase fits together
- how open source projects are structured
- how to work with AI tools critically rather than blindly
- how much product thinking matters once code generation gets easier

We built it with FastAPI + React + TypeScript + SQLite, and yes, Claude Code generated a lot of the implementation. But the real work was still deciding what to build, reviewing the output, and correcting course when the model got things wrong.

Adrian usually builds hardware — ESP32 sensors, Raspberry Pi projects — so this was a big step up in software scope. Watching him direct an AI tool toward a real product was fascinating.

Open source, MIT licensed:
https://github.com/adrirubio/claude-deck

---

### 6. Anthropic Community Forum -- next day

**Title:** Claude Deck - self-hosted dashboard for Claude Code (open source)

**Text:**
Sharing an open source project: **Claude Deck**, a self-hosted web dashboard for managing Claude Code.

It provides a local web UI for:
- **MCP servers**: add/edit/test, enable/disable, OAuth, inspect tools/resources/prompts
- **Slash commands, hooks, permissions, agents, skills, memory, output styles, status line**
- **Usage tracking**: token usage, costs, billing blocks, charts
- **Session transcripts** and **plan history**
- **CC Bridge** for tmux-based Claude Code session monitoring
- **Backup & restore**

Tech stack: FastAPI + React 19 + TypeScript + shadcn/ui + SQLite.
Runs locally. No cloud, no account, no telemetry.

Built by my son Adrian and me over Christmas break. Claude Code generated much of the implementation; we handled product direction, architecture, review, and fixes.

MIT licensed:
https://github.com/adrirubio/claude-deck

Would love feedback from Claude Code users. What should a tool like this support next?

---

### 7. r/OpenSource -- next day

**Cross-posting verdict:** Yes, but lean into the open-source/build story more than the product pitch.

**Title:** We open sourced Claude Deck, a self-hosted dashboard for Claude Code that my 13-year-old son and I built together

**Text:**
My son Adrian (13) and I built **Claude Deck**, a self-hosted web dashboard for managing Claude Code.

We started it as a Christmas-break project to learn together: open source workflow, product thinking, full-stack structure, and what AI-assisted development is actually good at.

Claude Deck solves a real annoyance for Claude Code users: once your setup grows, config and visibility are scattered across JSON files, directories, transcripts, and usage logs. This puts all of that into one local interface.

It covers MCP servers, slash commands, hooks, permissions, agents, skills, memory, usage tracking, transcripts, plan history, backups, and tmux session monitoring via CC Bridge.

Tech stack: FastAPI + React 19 + TypeScript + shadcn/ui + SQLite.
MIT licensed.

GitHub: https://github.com/adrirubio/claude-deck

If anyone has feedback on the project structure, docs, or where this should go next, I’d genuinely love to hear it.

---

## TIER 3 - Days 3-7

---

### 8. r/webdev -- day 3

**Title:** We built a full-stack dashboard with FastAPI + React 19 + TypeScript + SQLite — here’s what worked

**Text:**
My son and I built **Claude Deck**, a self-hosted dashboard for managing Claude Code, and the stack ended up working well enough that it might be interesting here.

**Stack:**
- Backend: Python 3.11 + FastAPI + async SQLAlchemy + aiosqlite
- Frontend: React 19 + TypeScript + Vite 7
- UI: Tailwind + shadcn/ui
- Charts: Recharts
- Storage: SQLite

Claude Code generated a lot of the implementation, but the interesting part was where that worked well vs where it didn’t.

What worked well:
- FastAPI + React plumbing
- schema and type alignment
- CRUD-heavy surfaces
- shadcn/ui-based component generation

What needed more supervision:
- more complex state flows
- edge cases around MCP testing and config interactions
- features requiring deeper understanding of Claude Code internals

Project if anyone wants to poke around:
https://github.com/adrirubio/claude-deck

---

### 9. r/sideproject -- day 3

**Cross-posting verdict:** Yes. This is the best place to lean a little more into the personal story.

**Title:** Christmas-break side project: a self-hosted Claude Code dashboard I built with my 13yo son

**Text:**
We built **Claude Deck**, a self-hosted dashboard for managing Claude Code.

It covers MCP servers, slash commands, hooks, permissions, usage tracking, transcripts, backups, and more.

FastAPI + React 19 + TypeScript + SQLite.
Local only, open source, MIT licensed.

Built with my son Adrian over Christmas break as a real project to learn from, not just a demo.

GitHub:
https://github.com/adrirubio/claude-deck

---

### 10. r/coolgithubprojects -- day 4

**Title:** Claude Deck - self-hosted dashboard for Claude Code

**Text:**
https://github.com/adrirubio/claude-deck

Self-hosted web dashboard for managing Claude Code config and metadata.

MCP servers, slash commands, hooks, permissions, agents, skills, usage tracking, session transcripts, CC Bridge, backup & restore.

FastAPI + React 19 + TypeScript + SQLite. MIT licensed.

---

### 11. Bluesky -- day 4-5

**Post 1:**
We built a self-hosted web dashboard for Claude Code.

Claude Deck gives you one place to manage MCP servers, usage, transcripts, slash commands, hooks, permissions, agents, skills, and more.

Built by me and my 13yo son Adrian.

github.com/adrirubio/claude-deck

[attach dashboard screenshot]

**Post 2:**
Once your Claude Code setup grows, config gets messy fast.

Claude Deck puts it behind a local UI: no cloud, no account, no telemetry.

FastAPI + React 19 + TypeScript + shadcn/ui + SQLite.

[attach usage tracking screenshot]

**Post 3:**
Claude Code generated a lot of the implementation. We handled product direction, architecture, review, and fixes.

Open source, MIT licensed:
https://github.com/adrirubio/claude-deck

---

## Comment Reply Cheat Sheet

- **“How much did Claude Code write?”**
  - “A lot of the implementation. We still made the product decisions, architecture calls, reviewed the code, and fixed what was wrong.”

- **“So is this just AI slop?”**
  - “No. AI helped us build faster, but we still had to decide what to build, review the output, and make it work as a coherent product.”

- **“Why not just edit the JSON files?”**
  - “You can. But once you have multiple MCP servers, custom commands, hooks, usage data, and transcripts, a visual overview becomes a lot more useful.”

- **“Why is it under Adrian’s account?”**
  - “Because it’s his project. I helped build it with him, but it lives under his GitHub.”

- **“What makes this different from just reading config files?”**
  - “It’s not just a viewer. It gives you management, testing, usage visibility, transcript browsing, backup/restore, and session monitoring in one place.”

- **“What should you launch first today?”**
  - “X/Twitter, then r/ClaudeAI, then HN once you’re fully ready to stay online and reply.”

---

## Screenshot Picks

Use these by channel:
- **X/Twitter:** `screenshots/dashboard.png` for tweet 1, `screenshots/mcp-servers.png` for tweet 2
- **Hacker News:** no image in post body, but make sure README screenshots are strong
- **r/ClaudeAI:** `dashboard.png` if posting with an image
- **r/SelfHosted:** `cc-bridge.png` or `dashboard.png` depending on whether you want broader appeal or power-user appeal
- **LinkedIn:** `dashboard.png`
- **Bluesky:** `dashboard.png`, then `usage-tracking.png`

Why:
- `dashboard.png` is the clearest "what is this?" image
- `mcp-servers.png` makes the utility concrete fast
- `cc-bridge.png` is the differentiator for technical users
- `usage-tracking.png` is strong as a secondary proof-of-depth image
- `skills.png` and `sessions.png` are good README support shots, but weaker as launch lead images

## Final Launch Checklist

Before posting:
- README up to date
- screenshots ready
- install flow tested
- repo public and clean enough
- CONTRIBUTING good enough
- Juan available to reply for at least 1-2 hours after HN post

If you only do three things today, do:
1. X/Twitter
2. r/ClaudeAI
3. Hacker News
