# Agent Bridge Keyboard Shortcuts Discoverability — Design Spec

**Status:** Draft for review (no implementation committed)
**Date:** 2026-07-01
**Scope:** Make the Agent Bridge keyboard shortcuts (#261 / PR #262) discoverable through an always-visible in-app affordance plus a full shortcuts dialog, instead of only appearing transiently after pressing `Ctrl+Space`.
**Depends on:** #261 / PR #262 (leader shortcuts + `LeaderHintOverlay`), merged to master.

---

## 1. Problem & Motivation

The `Ctrl+Space` leader shortcuts (prev/next pane, jump 1-4, toggle mode) are only surfaced by `LeaderHintOverlay`, which appears **after** the user already presses `Ctrl+Space`. Nothing in the UI tells a user the shortcuts exist, so the feature is effectively hidden — a user who doesn't already know the prefix will never discover it.

Additional constraint: the Agent Bridge **header is hidden in fullscreen and team-lanes layouts** (`{!isFullscreen && ...}` in `CCBridgePage.tsx`) — which are exactly the modes where the shortcuts are most useful. So a header-only affordance would be invisible when it matters most.

---

## 2. Current State (as-is)

- `frontend/src/features/cc-bridge/LeaderHintOverlay.tsx` — a transient top-right chip listing the follow-up keys as a **hardcoded string**; rendered by `CCBridgePage` only while a terminal reports leader-armed.
- `frontend/src/features/cc-bridge/TerminalView.tsx` — each pane has a **bottom bar** already showing the Read-only/Interactive toggle, connection status, and session label. This bar is part of every pane, so it is present in **all** layouts (grid, single fullscreen, lanes).
- UI primitives available: shadcn `dialog` and `alert-dialog` exist. **No `popover` or `tooltip`** primitive is present.

---

## 3. Design

### 3.1 Shared shortcut definitions (single source of truth)

Extract the shortcut list into one module, e.g. `frontend/src/features/cc-bridge/leaderShortcuts.ts`:

```ts
export interface LeaderShortcut {
  keys: string        // e.g. '←/→', '1-4', 'r', 'Esc'
  label: string       // e.g. 'Previous / next pane'
}

export const LEADER_PREFIX_LABEL = 'Ctrl+Space'

export const LEADER_SHORTCUTS: LeaderShortcut[] = [
  { keys: '←/→', label: 'Previous / next displayed pane' },
  { keys: '1-4', label: 'Jump to displayed pane' },
  { keys: 'r',   label: 'Toggle read-only / interactive' },
  { keys: 'Esc', label: 'Cancel the leader' },
]
```

Both `LeaderHintOverlay` and the new dialog render from this array so they cannot drift.

### 3.2 Terminal-bar hint (always-visible affordance)

Add a small, low-emphasis `<button>` to the `TerminalView` bottom bar (near the mode toggle / status), labeled with an icon + prefix, e.g. `⌨ Ctrl+Space`.

- Present in every layout because the bar is part of each pane.
- **Responsive:** icon-first chip; on narrow panes (4-up grid / lanes) it may collapse to just the icon, with the full text available via `title` and the dialog.
- `onClick` calls `e.stopPropagation()` so it does not steal/alter pane focus; opens the dialog.
- A real `<button>` — keyboard reachable, focusable.

### 3.3 Shortcuts dialog

Clicking the hint opens a shadcn `Dialog` titled "Keyboard shortcuts":

- Renders `LEADER_PREFIX_LABEL` as the leader prefix, then each `LEADER_SHORTCUTS` entry as `keys` + `label`.
- Renders above fullscreen / lanes (dialog portal), so it works in every layout.
- `Esc` / backdrop / close button dismisses it.
- Open state is **local to `TerminalView`** (each pane owns its own dialog) — no new global state in `CCBridgePage`.

### 3.4 Refactor `LeaderHintOverlay`

Replace its hardcoded string with a render over `LEADER_SHORTCUTS` + `LEADER_PREFIX_LABEL`, keeping the transient overlay and the dialog in sync.

---

## 4. Components / Files

Frontend only. No backend change.

- `frontend/src/features/cc-bridge/leaderShortcuts.ts` — **new**; shared definitions.
- `frontend/src/features/cc-bridge/TerminalView.tsx` — bottom-bar hint button + local dialog state + `Dialog` render.
- `frontend/src/features/cc-bridge/LeaderHintOverlay.tsx` — consume the shared list.
- `docs/features/agent-bridge.md` — note the in-app affordance (bar hint + dialog).

---

## 5. Test Plan (manual; no FE test harness)

1. The `⌨ Ctrl+Space` hint is visible in the terminal bar in grid, single fullscreen, and team-lanes layouts.
2. Clicking the hint opens the shortcuts dialog listing prefix + all follow-up keys with descriptions.
3. Clicking the hint does not change which pane is focused (`stopPropagation`).
4. `Esc` / backdrop / close button dismisses the dialog.
5. Dialog opens correctly above fullscreen and lanes layouts.
6. On a narrow pane (4-up grid), the hint collapses gracefully (icon-only) and the dialog still lists everything.
7. The transient `LeaderHintOverlay` (after pressing `Ctrl+Space`) and the dialog show the same shortcut set (shared source).
8. Hint button is keyboard-reachable and activates on Enter/Space.

---

## 6. Non-Goals

- Configurable / remappable keybindings (still a future enhancement).
- A global, app-wide shortcuts reference beyond Agent Bridge.
- Showing the hint outside Agent Bridge terminals.
- Adding a new `popover`/`tooltip` primitive (dialog reuse only).
