# Presence Dashboard: Status Accuracy Improvements

**Date:** 2026-03-08
**Status:** Implemented

## Problem

The Presence Dashboard cards don't show useful status information for most sessions. From a screenshot with 8 sessions:

- **5 of 8 cards are nearly empty** — openclaw, both nano-banana-pipelines, claude-deck, and linode-migration show only a tiny activity sparkline with no narrative, commands, or files.
- **"Active: 0" despite 8 sessions listed** — the 5-minute idle timeout aggressively marks sessions as idle even when Claude is actively thinking (just not triggering hook events).
- **No status text** — the only indicator is a colored dot (green/gray/red), which doesn't communicate what the session is actually doing.

### Root Cause

The current status model has 4 states (`active`, `idle`, `error`, `stopped`) derived from **event timing**, not from what Claude is actually doing:

- A session is `active` only while hook events are arriving frequently (< 5 min apart)
- A session becomes `idle` after 5 minutes without events — but Claude may be thinking, waiting for a large tool response, or the user is reading output
- Cards render sections conditionally (`last_narrative`, `modified_files`, `last_command`), so sessions that haven't triggered those specific events appear blank
- There's no human-readable status text — just a dot color

### Relevant Code

**Backend status logic** (`backend/app/services/presence_service.py`):
- `_mark_idle_sessions()`: marks any `active` session as `idle` if `last_event_at` is > 5 minutes ago
- `process_event()`: sets status to `active` on any non-Stop/SessionEnd event, `stopped` on Stop/SessionEnd, `error` on non-zero Bash exit code
- No concept of "waiting for input" vs "thinking" vs "running tool"

**Frontend card rendering** (`frontend/src/features/presence/PresenceCard.tsx`):
- Narrative section: only rendered if `session.last_narrative` exists
- Modified files section: only rendered if `session.modified_files` has entries
- Last command section: only rendered if `session.last_command` exists
- When none of these exist, only the header (label + duration) and sparkline are shown

**Hook events subscribed** (from ConnectDialog):
- `Notification` — narrative text updates
- `PostToolUse` — file edits, bash commands
- `Stop` — session paused
- `SessionStart` — session started
- `SessionEnd` — session ended

---

## Proposed Solutions

### Approach A: Richer Status from Existing Hooks (Recommended)

**Effort:** Medium | **Impact:** High | **Risk:** Low

Derive a human-readable `status_text` from the last event and always display it prominently on every card. No new dependencies or hook types needed.

**Backend changes:**
- Add `status_text` field to `PresenceSession` model (string, e.g., "Waiting for input", "Ran tool: Bash", "Edited 3 files", "Thinking...")
- Update `process_event()` to set `status_text` based on event type:
  - `Notification` with "waiting for input" → "Waiting for input"
  - `PostToolUse` with `tool_name=Bash` → "Ran: `<command snippet>`"
  - `PostToolUse` with `tool_name=Edit/Write` → "Edited `<filename>`"
  - `PostToolUse` with other tools → "Used tool: `<tool_name>`"
  - `SessionStart` → "Session started"
  - `Stop`/`SessionEnd` → "Stopped"
- Replace binary idle detection with graduated staleness:
  - Show `last_event_at` as relative time ("2m ago", "15m ago") on every card
  - Consider a longer idle timeout (15-20 min) or remove it entirely in favor of showing the "last seen" time

**Frontend changes:**
- Always show a status line on every card, even when no narrative/files/commands exist:
  ```
  [●] mercadona-cli                    11h 39m
  Waiting for input · last event 2m ago
  ```
- Show `status_text` prominently below the header (not conditionally)
- Show relative `last_event_at` time alongside status
- Consider showing `total_events` count as a secondary indicator of session activity

**Why recommended:** Gets 80% of the value with minimal changes. Every card will always show meaningful information. The "last event" time gives users an accurate sense of liveness without needing more hook types.

---

### Approach B: Poll Claude Code Status Directly

**Effort:** High | **Impact:** Very High | **Risk:** Medium

Add a backend polling mechanism that checks the actual state of Claude Code sessions independently of hook events.

**How it would work:**
- Backend periodically (every 10-30s) checks tmux panes for sessions known to be in tmux
- Parse the tmux pane content to detect Claude Code status bar patterns (e.g., "Thinking...", "● claude-deck", idle prompt)
- Could also check process status (is the Claude Code process still running?)
- Update session status based on polled state, not just hook events

**Pros:**
- Most accurate real-time status — doesn't depend on hooks firing
- Can detect when Claude is thinking (no hooks fire during inference)
- Can detect crashed/hung sessions

**Cons:**
- Requires tmux dependency (not all sessions may use tmux)
- Parsing terminal content is fragile
- Adds background polling complexity
- May duplicate CC Bridge functionality

---

### Approach C: Subscribe to Additional Hook Events

**Effort:** Medium | **Impact:** High | **Risk:** Low-Medium

Claude Code supports more hook events than currently subscribed. Adding more events gives finer-grained status.

**Additional events to consider:**
- `PreToolUse` — fires before a tool runs, so we know Claude is about to execute something
- `UserMessage` — fires when the user sends a message, confirming the session is interactive
- `SubagentStart`/`SubagentEnd` — track when subagents are spawned

**How it improves status:**
- `PreToolUse` → status: "Running tool: `<name>`..." (before it completes)
- `UserMessage` → status: "Processing user message..." / resets idle timer
- Gap between `PreToolUse` and `PostToolUse` → "Tool running..." with elapsed time
- Long gap after `PostToolUse` with no new events → "Thinking..." (Claude is generating)

**Pros:**
- More accurate status without polling
- Leverages existing hook infrastructure
- Can detect "thinking" state (gap between events)

**Cons:**
- Requires user to update their hook configuration (re-run connect dialog)
- More events = more webhook traffic
- Still can't detect truly idle vs. thinking if no events fire

---

## Recommendation

**Start with Approach A**, then layer in Approach C later if needed.

Approach A is the quickest path to useful cards — every card will always show what the session last did and when. The "last event X ago" pattern is well-understood from tools like `kubectl get pods` (showing age) and gives users an intuitive sense of liveness.

Approach C can be added incrementally to get finer-grained "Running tool..." / "Thinking..." states, but it requires users to update their hook config, so it's better as a follow-up.

Approach B should only be considered if the tmux-based CC Bridge is always available and the polling approach can be shared between features.
