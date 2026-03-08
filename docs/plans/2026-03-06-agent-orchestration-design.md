# Agent Orchestration Platform — Design Document

**Date:** 2026-03-06  
**Status:** Proposal  
**Author:** Galactus (OpenClaw AI)

---

## Overview

Claude Deck today is a monitoring dashboard for Claude Code sessions. This document proposes evolving it into a **full agent orchestration platform** — a system where OpenClaw (Galactus) can spawn, steer, and monitor fleets of Claude Code agents working in parallel on large tasks, with Claude Deck as the mission control surface.

The killer feature: **Deck becomes the nervous system connecting OpenClaw and CC instances**, enabling end-to-end execution of large tasks (PRDs, migrations, feature buildouts) that would be too large for a single agent context.

---

## Problem Statement

Large engineering tasks exceed what a single Claude Code session can do reliably:
- Context limits prevent holding the full codebase + task in one session
- Sequential execution is slow — many subtasks are parallelisable
- No visibility into what agents are doing across sessions
- No mechanism for an orchestrating agent to steer individual workers mid-task
- No way to recover gracefully when one agent gets stuck or goes wrong

---

## Architecture

### Three-layer model

```
┌─────────────────────────────────────────────────────┐
│                  CONTROL PLANE                       │
│   OpenClaw (Galactus) + ACP sessions                 │
│   Orchestrates agents, holds the plan, makes         │
│   decisions, steers workers                          │
└────────────────────┬────────────────────────────────┘
                     │ sessions_send / completion events
┌────────────────────▼────────────────────────────────┐
│                  SURFACE LAYER                       │
│   Claude Deck (backend + frontend)                   │
│   Visualises state, relays events, exposes           │
│   steer controls, shows telemetry                    │
└────────┬───────────────────────────┬────────────────┘
         │ CC HTTP hooks             │ ACP events
┌────────▼──────────┐    ┌──────────▼────────────────┐
│   DATA PLANE      │    │   CONTROL PLANE WORKERS    │
│   CC instances    │    │   ACP sub-agents           │
│   (tool calls,    │    │   (each drives one CC      │
│   file edits,     │    │   instance, reports back   │
│   completions)    │    │   to Galactus)             │
└───────────────────┘    └───────────────────────────┘
```

### Component roles

| Component | Role |
|-----------|------|
| **Galactus (OpenClaw)** | Orchestrator. Breaks down tasks, spawns ACP sub-agents, makes steering decisions, synthesises outputs |
| **ACP sub-agents** | Worker agents. Each owns one subtask, drives a CC instance, reports completion back to Galactus |
| **CC instances** | Executors. Do the actual code work — edit files, run tests, commit |
| **CC HTTP hooks** | Telemetry. Fire events on every meaningful action (tool call, file edit, session end) |
| **Deck backend** | Relay + store. Receives CC hooks, persists them, forwards to OpenClaw Gateway, manages WebSocket connections |
| **OpenClaw Gateway** | Message bus. Routes events from Deck to Galactus, routes Galactus replies to Deck |
| **Deck frontend** | Mission control. Shows agent fleet, plan tree, telemetry stream, steer controls |

---

## Workflow: Large Task Execution

### Phase 1 — Inception

1. User describes the goal to Galactus (TUI or Slack): *"Build the billing module — stripe integration, webhook handling, subscription management, usage metering"*
2. Galactus produces a **task breakdown**:
   - Phases (sequential gates)
   - Subtasks within each phase (parallelisable)
   - Dependencies between subtasks
   - Acceptance criteria per subtask
   - Estimated token budget per agent
3. Galactus writes `PLAN.md` to the repo root — the shared source of truth
4. Deck displays the plan tree in a new **Orchestration view**

### Phase 2 — Dispatch

1. Galactus calls `sessions_spawn(runtime="acp")` for each ready subtask
2. Each ACP sub-agent receives:
   - Its slice of `PLAN.md`
   - A `TASK.md` with specific instructions, scope boundaries, and acceptance criteria
   - The repo path and branch to work on
3. Each sub-agent spawns or attaches to a CC instance in its working directory
4. Sub-agents register their session IDs with Deck so events can be correlated

### Phase 3 — Execution + Monitoring

CC instances work autonomously, firing HTTP hooks to Deck on every action:

```
POST /api/hooks/inbound
{
  "session_id": "abc123",
  "event": "tool_call",
  "tool": "write_file",
  "path": "src/billing/stripe.ts",
  "timestamp": "..."
}
```

Deck:
- Persists each event to its DB
- Updates the frontend via WebSocket (live feed)
- Forwards significant events to OpenClaw Gateway for Galactus awareness

Galactus monitors the fleet passively, intervening when:
- An agent signals it needs a decision (`event: "waiting_for_input"`)
- An agent has been idle too long (timeout heuristic)
- A completion event arrives (subtask done → check acceptance criteria)
- A blocking error is detected

### Phase 4 — Steering

When Galactus decides to steer an agent:

```
Galactus
  → sessions_send(subAgentSessionKey, "The schema changed, use UUID not int for IDs")
  → ACP sub-agent receives the message
  → Sub-agent injects the instruction into its CC session
  → CC continues with updated context
```

From Deck, the user can also steer directly:
- Click an agent card → open steer panel → type instruction → routes via OpenClaw Gateway → ACP sub-agent → CC

### Phase 5 — Completion + Synthesis

1. Each sub-agent fires a completion event when its CC session finishes
2. ACP push notification reaches Galactus
3. Galactus reviews the output (reads changed files, checks acceptance criteria)
4. If accepted: marks subtask done in `PLAN.md`, unlocks dependent subtasks, dispatches next phase
5. If rejected: re-steers the agent or spawns a new one with a corrected brief
6. Final phase: Galactus runs a synthesis pass — resolves any conflicts between parallel agents, writes a summary PR, updates docs

---

## New Deck Components

### 1. Orchestration View (new page)

The top-level view for multi-agent tasks.

**Plan tree panel:**
- Hierarchical view: Task → Phases → Subtasks → Agent
- Node states: `pending` / `running` / `blocked` / `done` / `failed`
- Dependency arrows between subtasks
- Click a node → focus that agent's detail view

**Fleet summary bar:**
- N agents running / M done / K blocked
- Total token burn + burn rate
- Estimated completion (based on per-agent progress)

### 2. Agent Detail Card (enhanced Presence card)

Per-agent panel showing:
- Current status and last action
- Live event stream (last N hook events)
- Files modified (linked, browsable)
- Token usage + cost
- Time elapsed
- **Steer input** — type a message, hit send, routes to that agent

### 3. Event Stream (new panel)

Live feed of all hook events across all agents, similar to a log tail:
```
[09:42:11] agent-stripe  write_file  src/billing/stripe.ts
[09:42:13] agent-webhooks run_command  npm test -- billing
[09:42:18] agent-stripe  waiting_for_input  "Should I use idempotency keys?"
[09:42:19] ← Galactus   steer       "Yes, always pass idempotency_key=..."
```

Filterable by agent, event type, or file path.

### 4. Artifacts Panel (new panel)

Files produced/modified by the fleet, browsable without leaving Deck:
- File tree of all touched paths
- Diff view per file
- "Open in editor" link

### 5. Gateway Bridge (new backend module)

The relay between Deck and OpenClaw:

```python
# On receiving a CC hook event
async def on_hook_event(event: HookEvent):
    await db.store(event)
    await websocket.broadcast(event)          # → Deck frontend
    await gateway.forward(event)              # → OpenClaw Gateway → Galactus

# On receiving a steer command from Galactus via Gateway
async def on_galactus_steer(session_id: str, message: str):
    await db.store_steer(session_id, message)
    await websocket.broadcast_steer(session_id, message)  # → Deck frontend
    # ACP sub-agent handles actual injection into CC
```

**OpenClaw Gateway endpoint (new):**
```
POST /api/inbound-event   ← Deck forwards CC hook events here
POST /api/steer           ← Galactus sends steering commands here → Deck
```

---

## What CC Bridge Becomes

CC Bridge (PTY relay) remains useful but scoped to **manually-run CC sessions** — when you open CC yourself in tmux and want a web terminal view. It is **not** part of the ACP orchestration path.

In the orchestration flow, ACP sub-agents communicate with CC via message passing, not PTY relay. Deck's visibility into those sessions comes from CC HTTP hooks, not CC Bridge.

The two coexist as separate Deck features:
- **CC Bridge tab** — manual sessions, PTY view, existing workflow
- **Orchestration tab** — Galactus-managed fleet, plan tree, hook telemetry

---

## Implementation Phases

### Phase 1 — Gateway Bridge (foundation)
*Prerequisite for everything else*

- Add `POST /api/hooks/forward` to Deck backend — forwards hook events to OpenClaw Gateway
- Add `/api/inbound-event` endpoint to OpenClaw Gateway
- Add `/api/steer` endpoint to Deck backend — accepts commands from Galactus, routes to correct agent
- Wire Gateway → Galactus session delivery (treat as inbound message to main session)

**Deliverable:** Galactus receives CC hook events in real time. Galactus can send steer messages that appear in Deck.

### Phase 2 — Orchestration View skeleton
*Deck frontend*

- New `/orchestration` page
- Plan tree component (static JSON for now, no live updates yet)
- Agent cards with hook event feed
- Event stream panel

**Deliverable:** You can see a task plan and live hook events from CC agents in Deck.

### Phase 3 — ACP sub-agent integration
*OpenClaw side*

- Galactus can spawn ACP sub-agents with a task brief
- Sub-agents register their session with Deck on startup (`POST /api/agents/register`)
- Sub-agents drive CC instances and relay CC hook events
- Completion events propagate back to Galactus via ACP push

**Deliverable:** Galactus can dispatch a multi-agent task and track completion without manual intervention.

### Phase 4 — Steer controls
*Full loop*

- Steer input in Agent Detail Card
- Galactus auto-steer on `waiting_for_input` hook events
- User steer via Deck UI routes to Galactus → ACP sub-agent → CC
- Conflict detection when parallel agents touch the same file

**Deliverable:** Full control loop — spawn, monitor, steer, complete.

### Phase 5 — Synthesis + PR generation
*End-to-end*

- Galactus synthesis pass on fleet completion
- Auto-generated PR with summary of all agent outputs
- `PLAN.md` final state written to repo
- Deck shows completed task summary with cost breakdown

**Deliverable:** Drop a goal in, get a merged PR out.

---

## Open Questions

1. **Branch strategy** — Do parallel agents work on the same branch (conflict-prone) or feature branches per agent (merge complexity)? Recommendation: per-agent branches, Galactus does the merge.

2. **Context budget** — How much shared context does each sub-agent get? Full codebase is too large. Recommendation: agent gets only the files relevant to its subtask (derived from plan + file ownership map).

3. **Hook reliability** — CC hooks are fire-and-forget HTTP. If Deck is down, events are lost. Recommendation: agents should also commit progress checkpoints to git so Galactus can reconcile from state even with missed events.

4. **Cost controls** — Multi-agent runs can burn tokens fast. Recommendation: per-agent token budget enforced by Galactus; auto-pause if budget exceeded, surface alert in Deck.

5. **OpenClaw Gateway API** — Does Gateway expose an HTTP API for inbound events today, or does this need to be added? Needs investigation.

---

## Summary

Claude Deck evolves from a monitoring dashboard into a **multi-agent orchestration platform** by wiring together three existing pieces:

- **ACP** (control plane): Galactus spawns and steers sub-agents
- **CC HTTP hooks** (data plane): telemetry from CC instances flows to Deck
- **Deck** (surface): visualises the fleet, relays events, exposes steer controls

The result is a system where you can hand Galactus a large engineering goal and watch it execute — with full visibility, the ability to intervene at any level, and a clean output at the end.
