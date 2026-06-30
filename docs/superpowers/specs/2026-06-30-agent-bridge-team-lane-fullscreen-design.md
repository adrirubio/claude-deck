# Agent Bridge Team-Lane Fullscreen — Design Spec

**Status:** Draft for review (no implementation committed)
**Date:** 2026-06-30
**Scope:** Add a fullscreen "team lanes" layout to Agent Bridge that displays all live sessions of the currently-selected team side by side as vertical, full-height lanes (left-to-right), up to 4 lanes.
**Depends on:** #257 (Agent Bridge team filtering) — provides the selected-team concept and slot-ordering plumbing this feature builds on.

---

## 1. Problem & Motivation

Agent Bridge currently supports fullscreen for a **single** terminal panel (`fullscreenTarget` in `CCBridgePage.tsx`). When working with an Agent Team, a user wants to watch **all members at once** — e.g. a team of Architect, Lead Dev, and QA Engineer — each occupying a full-height vertical lane across the screen.

Today there is no way to see more than one agent at full size. The single-panel fullscreen forces the user to flip between members one at a time, which defeats the purpose of observing a team working in parallel.

The desired outcome: with a team selected, one click enters a fullscreen layout where each team member is shown in its own vertical lane, dividing the horizontal space evenly, supporting up to 4 lanes.

---

## 2. Current Architecture (as-is)

In `frontend/src/features/cc-bridge/CCBridgePage.tsx`:

- `activeTargets: string[]` — terminals attached in the grid (capped at `MAX_GRID_PANES = 4`).
- `fullscreenTarget: string | null` — single-panel fullscreen state.
- `gridCols` — only ever `grid-cols-1` or `grid-cols-2`.
- Fullscreen container uses `fixed inset-0 z-50 bg-background`.
- An existing `useEffect` listens for `Escape` to exit fullscreen.

Each terminal is a `TerminalView` backed by `useTerminal`, which already:

- loads `FitAddon` and calls `fitAddon.fit()` on mount and on a `ResizeObserver`,
- sends a `resize` control frame to the backend pty relay when dimensions change.

So **terminals automatically refit when their container resizes** — no manual sizing logic is needed for new layouts.

Sessions carry team metadata (from `_enrich_team_sessions` in `backend/app/api/v1/agent_bridge/router.py`), already typed on `AgentSession` in `frontend/src/features/cc-bridge/types.ts`:

- `team_preset_id: number | null`
- `team_preset_name: string | null`
- `team_slot_id`, `team_slot_name`, `team_slot_role`, `team_slot_color`

**This is a frontend-only feature.** No backend or schema changes.

---

## 3. Behavior & Trigger

- **Trigger:** a "Team lanes" action in the Agent Bridge header, enabled **only when a specific team is selected** in the team filter (#257). When "All teams" is selected, the action is disabled.
- **Lane contents:** derived from discovery — all live sessions whose `team_preset_id` matches the selected team, **ordered by slot role** (`team_slot` ordering), **capped at 4**.
- **No pre-attaching required:** entering lane mode attaches the team's sessions on the fly.
- **Overflow (>4 live members):** show the first 4 by slot order plus a clear "+N not shown" indicator. No paging in MVP.
- **Underflow:** lane count equals the actual live-member count (3 members → 3 lanes); lanes divide the width evenly.
- **Exit:** `Esc` (reusing the existing Escape handler) returns to the normal grid.
- **Coexistence:** mutually exclusive with single-panel fullscreen — entering one exits the other.

---

## 4. State & Layout Mechanics

### 4.1 Layout state

Replace the implicit two-flag fullscreen state with an explicit union, since the three layouts are mutually exclusive:

```ts
type LayoutMode =
  | { kind: 'grid' }
  | { kind: 'single'; target: string }
  | { kind: 'lanes' }
```

(Equivalent to today's `fullscreenTarget` plus a new lanes state. Implementation may keep `fullscreenTarget` and add a `teamLanesActive` boolean instead, as long as the mutual exclusion is enforced. The union is preferred for clarity.)

### 4.2 Derived lane targets

Lane targets are **derived, not stored**, so they react to discovery refreshes automatically:

```ts
const laneTargets = useMemo(() => {
  if (layoutMode.kind !== 'lanes' || teamFilter === 'all') return []
  return sessions
    .filter((s) => s.team_preset_id === teamFilter)
    .sort(bySlotOrder)            // stable order by slot role / slot id
    .slice(0, MAX_GRID_PANES)
    .map((s) => s.tmux_target)
}, [layoutMode, teamFilter, sessions])
```

`bySlotOrder` sorts by a stable slot ordering (slot id, or a role rank derived from `team_slot_role`) so the left-to-right arrangement is meaningful and stable across refreshes.

### 4.3 Layout rendering

- Reuse the existing fullscreen container (`fixed inset-0 z-50 bg-background`).
- Render N lanes as full-height columns. Lane count drives columns: 1→1, 2→2, 3→3, 4→4. This is a **distinct layout path** from the existing `gridCols` (which only does 1/2). Use `flex` with `flex-1` per lane, or an explicit `grid-cols-N` mapping.
- Each lane renders a `TerminalView` for one lane target.

### 4.4 Sizing

No manual terminal sizing — each lane's `TerminalView` refits via the existing `ResizeObserver` + `FitAddon` + `resize` control frame when the lanes mount/resize.

### 4.5 Attach semantics

Lane mode is **ephemeral**: it shows the team's sessions regardless of what was in `activeTargets`, and it does **not** mutate `activeTargets`. Exiting lane mode (`Esc`) restores the previous grid untouched.

---

## 5. Edge Cases & Interactions

- **Read-only / interactive:** each lane is a normal `TerminalView`; the per-terminal read-only/interactive toggle and focus highlight (`focusedTarget`) work per lane, unchanged.
- **Member dies mid-lanes:** discovery refresh drops it from `laneTargets` → its lane disappears, remaining lanes re-divide the width. If the count reaches 0 (whole team gone), **auto-exit** to the grid.
- **Team filter changes while in lanes:** **exit lane mode** back to the grid. The user re-triggers lanes deliberately for the new team. (Avoids a surprising full re-layout on a filter click.)
- **"All teams" selected:** the Team-lanes action is disabled.
- **Overflow (>4):** first 4 by slot order; "+N not shown" indicator in the lane bar.
- **Single-fullscreen button inside a lane:** hidden in MVP (promote-to-single is a deferred enhancement).
- **Spawn / kill from lane mode:** out of scope; if a session is killed elsewhere, the die-mid-lanes path covers it.

---

## 6. Components

Frontend-only:

- **`CCBridgePage.tsx`** — `LayoutMode` union state; derived `laneTargets` (filter by team → sort by slot order → slice 4); lane render path; "Team lanes" trigger button (enabled only for a specific team); Esc/exit handler reuse; auto-exit effects (team gone, filter changed); disable rules.
- **`TerminalView.tsx`** — minor: hide the per-panel maximize button when in lane mode (small prop signal, e.g. `inLanes`).
- **`TeamLanesView` (optional)** — extract the lane render path into a subcomponent if `CCBridgePage` grows too heavy; decide during implementation, otherwise inline.
- **No `types.ts` change** (team fields already present); **no backend change**.

---

## 7. Test Plan

Manual (until a frontend test harness exists):

1. 3-member team → click Team lanes → 3 full-height lanes left-to-right in slot-role order, each attached.
2. 5-member team → 4 lanes + "+1 not shown".
3. Kill one member → its lane drops, others re-divide; kill all → auto-exit to grid.
4. `Esc` exits to the prior grid with previous `activeTargets` intact (ephemeral attach didn't disturb them).
5. Switch team filter while in lanes → exits lane mode.
6. "All teams" selected → Team-lanes action disabled.
7. Per-lane read-only/interactive toggle works independently.

---

## 8. Non-Goals

- Promote-a-lane to single fullscreen (and back). Deferred enhancement.
- Horizontal (stacked) lane orientation — lanes are vertical only.
- More than 4 members with paging.
- Spawning or killing sessions from lane mode.
- Persisting lane mode across reloads.
- Team-color theming of lanes/pills.
