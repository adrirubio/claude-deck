# Presence Feature Usability Review After Agent Mail

**Date:** 2026-06-13
**Status:** Product/UX review
**Scope:** Current Presence feature in the context of the new Agent Mail feature

## Executive Summary

Presence should not be left alone as-is. It is now weak as a top-level product surface because Agent Mail owns the user-meaningful concepts: repository member identity, session availability, inbox load, pending requests, handoffs, setup status, and coordination state.

Presence is not obsolete as infrastructure. The hook/event ingestion path still has value. But the current Presence page is obsolete or at least degraded as a standalone navigation item. It should either be redesigned into a true activity/diagnostics view connected to Agent Mail and Agent Bridge, or removed from primary navigation while retaining the backend event pipeline for future use.

Recommended direction:

1. Short term: demote Presence from primary navigation or rename it to an advanced "Activity" view.
2. Medium term: integrate the useful parts of Presence into Agent Mail member/session details.
3. Long term: either redesign it as an event timeline/debugging surface or retire the standalone UI.

## Decision Annotation

**Decision:** Demote Presence from the primary Claude Deck sidebar now and remove the Presence-derived active-session badge from the top header. Keep the `/presence` route, API, event tables, and WebSocket path intact.

**Rationale:** Agent Mail should become the center of gravity for team coordination and agent availability. Presence remains useful as telemetry infrastructure, but the current standalone card dashboard is not strong enough to sit beside Agent Mail as a primary Operations feature.

**Revisit after usage:** Re-evaluate after Agent Mail has been used in normal multi-agent work for a while. The review question should be: "Do users still need a dedicated activity/diagnostics timeline, or are Agent Mail and Agent Bridge enough?"

Possible revisit outcomes:

1. Build a proper Agent Activity timeline from Presence events.
2. Fold selected Presence fields into Agent Mail member/session views only.
3. Replace remaining Presence backend dependencies and retire the feature fully.

## Product Context

Agent Mail is now the primary coordination feature. It is built around durable team members per repository, ephemeral agent sessions, structured messages, context requests, handoffs, and inspectable communication.

Presence was originally trying to answer a different question: "What Claude Code sessions exist and what are they doing right now?"

That can still be useful, but only if the feature gives the user actionable observability. In its current form, it mostly shows hook-derived session cards. That is not enough to support a real agent observability workflow.

## Current Feature Shape

Presence is implemented as a Claude Code hook telemetry dashboard:

- `POST /api/v1/presence/events` receives Claude Code HTTP hook payloads.
- `PresenceEvent` stores raw hook events.
- `PresenceSession` stores aggregated per-session state.
- The frontend shows a page with session counts, active/error totals, and one card per session.
- The connect dialog can add HTTP hooks for Claude Code events.

Relevant files:

- `backend/app/api/v1/presence.py`
- `backend/app/services/presence_service.py`
- `backend/app/models/database.py`
- `frontend/src/features/presence/PresencePage.tsx`
- `frontend/src/features/presence/PresenceCard.tsx`
- `frontend/src/features/presence/ConnectDialog.tsx`
- `frontend/src/hooks/usePresenceWebSocket.ts`

## Main Findings

### 1. Presence Does Not Currently Deliver Strong Observability

The page describes itself as "Real-time monitoring of Claude Code sessions," but the UI mostly gives summary cards. A card can show:

- session label
- status dot
- duration
- last status text
- last user prompt
- last narrative
- recently changed files
- last command
- activity sparkline

This is helpful at a glance, but it does not answer the operational questions a Claude Deck user is likely to ask:

- What is this agent doing right now?
- Is it stuck?
- Did a command fail?
- What changed before it stopped?
- Is it waiting for me or just not emitting hooks?
- Which agent/repo/member does this session belong to?
- What should I do next?

The backend stores raw events, but the UI does not expose a drill-down event timeline. That leaves a lot of useful data invisible.

### 2. The Status Model Is Not Trustworthy Enough

Presence derives status from hook events and elapsed time. The service marks active sessions idle after `IDLE_TIMEOUT_MINUTES`, currently 15 minutes, without new hook events.

That is not the same as agent state. A session with no recent hook events could be:

- thinking
- waiting for input
- processing a long command
- blocked on a tool
- idle
- abandoned
- still active but not producing hook events

The UI presents these as simple states: `active`, `idle`, `error`, `stopped`. That is too coarse for observability and can be misleading.

The previous status accuracy plan already identified this category of problem. Some improvements were added, such as `status_text`, but the underlying limitation remains: hook-derived recency is not true agent state.

### 3. Agent Mail Now Owns the More Useful "Who Is Available?" Model

Agent Mail has a better product model for agent coordination:

- durable team member per repository
- connected/observed/offline member status
- sessions under each member
- unread and pending counts
- roles and charters
- actions: message, request context, handoff

This is closer to how the user thinks about working with agents: "the repo expert for this project," not "session id 832fa12."

Presence still labels sessions by cwd basename and session id. That is less meaningful after Agent Mail introduces durable member identity.

### 4. Presence and Agent Mail Compete in Navigation

Both Presence and Agent Mail currently live under Operations in the sidebar.

This creates conceptual overlap:

- Agent Mail shows who is connected or observed.
- Presence shows session cards and hook activity.
- Agent Bridge shows running/attachable sessions.

The product now has three surfaces that can all look like "agent status":

1. Agent Bridge: sessions you can attach to or spawn.
2. Agent Mail: team members, inboxes, coordination, connected/observed/offline state.
3. Presence: hook-derived activity cards.

That is too much unless each surface has a sharply different job.

Current separation is not sharp enough. Presence feels like a less actionable status view rather than a distinct observability tool.

### 5. Setup UX Is Too Low-Level

The Presence connect dialog asks users to think about hook event types:

- Notification
- PreToolUse
- PostToolUse
- UserPromptSubmit
- Stop
- SessionStart
- SessionEnd
- SubagentStart
- SubagentStop

This exposes implementation plumbing. It may be useful in an advanced configuration page, but it is not a good primary setup experience for an observability feature.

The dialog can say hooks are "Connected," but that only means HTTP hooks are configured. It does not mean:

- a session has restarted since the hook install
- events are flowing
- the active project is covered by the hook scope
- the feature is useful for this provider
- the user has actionable diagnostics

Agent Mail now has a clearer setup model with an Install tab, MCP status, hook status, and user-facing setup notes. Presence should not duplicate a weaker setup pattern.

### 6. The Backend Is Still Worth Keeping

Presence should not be ripped out blindly. The backend has useful building blocks:

- raw event storage in `PresenceEvent`
- session aggregation in `PresenceSession`
- edited file tracking
- command exit tracking
- narrative capture
- WebSocket broadcast pattern
- header/system active session count dependency

For example, `backend/app/api/v1/status.py` currently uses `PresenceService` to derive active session count. Removing the backend would require replacing that dependency.

The better move is to separate "remove the weak page" from "remove the useful telemetry pipeline."

## Evaluation of Options

### Option A: Leave Presence Alone

Recommendation: do not choose this.

Pros:

- No engineering work.
- Existing users who use it keep the page.
- Backend dependencies are untouched.

Cons:

- Keeps a confusing top-level feature.
- Reinforces overlap with Agent Mail and Agent Bridge.
- Continues presenting weak hook-recency state as observability.
- Misses the chance to make Agent Mail the central team coordination surface.

Leaving it alone is the worst product choice because it preserves confusion without adding much value.

### Option B: Remove Presence Entirely

Recommendation: not immediately.

Pros:

- Simplifies the app.
- Removes a confusing page.
- Reduces conceptual overlap.

Cons:

- Loses useful hook/event infrastructure.
- Breaks or requires replacing active-session count behavior.
- Throws away telemetry that could power a better activity timeline.
- Removes a potentially valuable debugging surface before the replacement exists.

Full removal is premature. It may be the right end state if no activity/debugging view is planned, but it should not be the first move.

### Option C: Demote the Page, Keep the Backend

Recommendation: best short-term move.

Pros:

- Reduces product confusion quickly.
- Keeps telemetry available for future work.
- Avoids risky backend removal.
- Makes Agent Mail the obvious coordination center.

Possible implementation:

- Remove Presence from the primary Operations nav.
- Keep `/presence` route accessible directly or under an advanced/devtools section.
- Rename the page to "Activity" or "Claude Code Activity" if kept visible.
- Add a short scope note: "Claude Code hook telemetry only."

This is the most pragmatic near-term step.

### Option D: Redesign Presence Into Agent Activity

Recommendation: best medium-term direction if the feature is worth investing in.

The redesigned feature should not be a card grid. It should be an activity/diagnostics surface attached to Agent Mail member identity and Agent Bridge sessions.

It should answer:

- What happened recently in this repo/session?
- What tool is running or last ran?
- What files changed?
- What command failed?
- What was the last user prompt?
- When did the agent last check inbox?
- Is this session connected, observed, offline, or only hook-visible?

Suggested shape:

- Agent Mail member card shows latest activity summary.
- Clicking a session opens a timeline.
- Timeline groups events by prompt/tool/command.
- Failed commands and tool errors are visually prominent.
- Raw hook payloads are hidden by default but available in an advanced disclosure.
- Presence setup is absorbed into Agent Mail install/setup where possible.

This would convert Presence from a standalone "dashboard" into useful agent observability.

## Recommended Product Direction

Do not leave Presence as-is.

Do not immediately delete all Presence infrastructure.

Instead:

1. Treat Agent Mail as the primary coordination surface.
2. Treat Agent Bridge as the live session/terminal surface.
3. Treat Presence as telemetry infrastructure.
4. Demote or hide the current Presence page.
5. Reintroduce it only if redesigned as an Agent Activity timeline.

## Proposed Short-Term Changes

These are intentionally modest:

1. Move Presence out of the primary Operations nav.
2. If still visible, rename it to "Activity" or "Claude Code Activity."
3. Add a top-of-page note explaining its scope:
   - "This view uses Claude Code HTTP hooks."
   - "It does not coordinate agents."
   - "Use Agent Mail for messages, requests, handoffs, and team state."
4. Replace "Connected" wording with clearer wording:
   - "Hooks installed"
   - "Waiting for new/restarted Claude Code sessions"
   - "Events received X minutes ago"
5. Do not ask normal users to choose individual hook events.
6. Link from Agent Mail member/session rows to Presence activity only when telemetry exists.

## Proposed Medium-Term Redesign

If Presence is improved instead of retired, redesign around a session/repo timeline.

Minimum useful timeline fields:

- timestamp
- session/member/repo
- event type
- tool name
- command and exit code
- edited files
- user prompt summary
- narrative/status text
- error state

Useful filters:

- repo/member
- session
- failed commands only
- file edits only
- last hour/day

Useful actions:

- open related Agent Mail member
- open related Agent Bridge session
- request context from this member
- create handoff from recent activity

This would make Presence valuable because it would support a real workflow: diagnose what an agent did and decide the next action.

## Naming Recommendation

"Presence" is part of the confusion. It sounds like availability, but Agent Mail now owns the availability model.

Better names if retained:

- Agent Activity
- Session Activity
- Claude Code Activity
- Activity Timeline

Avoid names that imply coordination or messaging. That belongs to Agent Mail.

## Final Recommendation

Presence is not obsolete as telemetry infrastructure, but it is obsolete as a standalone top-level feature in its current form.

The next product move should be:

1. Demote/hide the current Presence page.
2. Keep backend event ingestion for now.
3. Fold useful activity signals into Agent Mail member/session views.
4. Decide later whether to build a proper Activity Timeline or retire the remaining UI.

This avoids a gimmicky extra dashboard while preserving the parts that can create real value.
