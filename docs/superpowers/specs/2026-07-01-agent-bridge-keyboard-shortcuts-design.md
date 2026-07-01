# Agent Bridge Keyboard Shortcuts — Design Spec

**Status:** Draft for review (no implementation committed)
**Date:** 2026-07-01
**Scope:** Add mouse-free keyboard navigation to Agent Bridge terminals — cycle/jump between displayed panes and toggle read-only ↔ interactive — using a leader-prefix scheme that does not interfere with the agent CLIs, byobu/tmux, or browser-reserved shortcuts.
**Related:** builds on the grid + team-lanes layouts (#258 / PR #260) and the read-only/interactive relay mode.

---

## 1. Problem & Motivation

Agent Bridge shows up to 4 terminals at once (grid or team lanes). Today, switching the focused pane and toggling a pane between read-only and interactive both require the mouse. When working across a team's panes, the user wants to:

- cycle to the next / previous displayed pane,
- jump directly to displayed pane N,
- toggle the focused pane between read-only and interactive,

all from the keyboard.

The core challenge is **interference**: keystrokes in a focused, interactive terminal are forwarded to the agent CLI, and the user runs sessions under **byobu** (tmux), which claims many no-prefix key combos. Any shortcut scheme must avoid stealing keys that byobu or the agent legitimately need.

---

## 2. Current Input Architecture (as-is)

`frontend/src/features/cc-bridge/useTerminal.ts`:
- Each `TerminalView` owns its own xterm `Terminal`.
- Keystrokes flow through `term.onData` → websocket **only when** the pane is focused **and** `readOnly` is false (`useTerminal.ts:129-133`).
- `readOnly` is per-terminal state in `useTerminal`; on change it sends a `mode` control frame to the backend pty relay (`useTerminal.ts:30-35`). No backend change is needed for the toggle.

`frontend/src/features/cc-bridge/CCBridgePage.tsx`:
- Owns `activeTargets: string[]` (attached grid panes, ≤4), `focusedTarget`, `layoutMode` (`grid` / `single` / `lanes`), and `teamLanes.sessions` (the lanes' ≤4 sessions in slot order).
- Grid pane numbering is already established: `SessionList` renders a badge of `activeTargets.indexOf(target) + 1` on each active card (`SessionList.tsx:108`, `SessionCard.tsx:86`).
- Already has a document-level `Escape` handler for exiting fullscreen.

### Interference facts (verified)

- **xterm** exposes `attachCustomKeyEventHandler((e) => boolean)`; returning `false` swallows a `keydown` **before** it reaches `term.onData` / the agent. This is the only reliable pre-agent hook, and it works even in interactive mode.
- **byobu default tmux bindings** (`/usr/share/byobu/keybindings/f-keys.tmux`) claim, no-prefix:
  - `M-Left`/`M-Right` (prev/next window), `M-Up`/`M-Down` (switch client) → **Alt+arrows unusable**
  - `S-Left`/`S-Right` (select pane), `M-S-arrows` (resize) → **Shift+arrows unusable**
  - `F12` is byobu's prefix; `C-a` is byobu's screen-style new-window → both unusable
  - `C-Space` (`C-@`) is **not** bound by byobu → safe from byobu's perspective
- **Browser-reserved (cannot intercept):** `Cmd/Ctrl+1..9` (tab switch), `Cmd/Ctrl+T/W/N/Tab`, `Cmd+``. So "jump to N" must not use `Ctrl/Cmd+digit`.

---

## 3. Design Decisions (settled)

1. **Scope = global within Agent Bridge (grid + lanes + single fullscreen).** Shortcuts are active whenever a bridge terminal is focused, in any layout. They are inert when focus is outside a bridge terminal.
2. **Navigation set = the currently displayed panes, in on-screen order.**
   - Grid: `activeTargets` order (the 1..N badges already shown on cards).
   - Lanes: `teamLanes.sessions` order (slot order, left-to-right).
   - Single fullscreen: the one displayed pane, `[layoutMode.target]` (see §4.1).
   - Consequence (accepted): a given session's number may differ between grid and lanes, because each layout numbers what is visually on screen. "N = the Nth thing I see."
   - Only displayed panes can be cycled/jumped to.
3. **Scheme = leader prefix** (tmux/byobu-native muscle memory; provably collision-free because nothing single-modifier must thread byobu + both platforms' browser reservations).
4. **Prefix = `Ctrl+Space`, MVP default (not universally guaranteed).** Verified unbound in byobu and not browser-reserved, but `Ctrl+Space` is an OS/IME switcher on some Linux and macOS setups and may be intercepted before the browser/xterm sees it. Ships as the default; configurable keybindings (§8) may be promoted from future to fast-follow if testing on target machines shows OS interception. Soft-leader (see §4).
5. **Visual hint overlay** appears on prefix arm.
6. **Interception = per-terminal via xterm `attachCustomKeyEventHandler`** (approach A), actions dispatched up to `CCBridgePage` with the originating terminal target. Only mechanism that behaves correctly in both interactive and read-only panes.
7. **Out-of-range "jump to N" = silent no-op.**

---

## 4. Keybindings & Behavior

Leader prefix, then a key within a ~2s timeout:

| Sequence | Action |
|---|---|
| `Ctrl+Space` then `←` | focus previous displayed pane (wraps) |
| `Ctrl+Space` then `→` | focus next displayed pane (wraps) |
| `Ctrl+Space` then `1`–`4` | focus displayed pane N (on-screen order); out-of-range = silent no-op |
| `Ctrl+Space` then `r` | toggle focused pane read-only ↔ interactive |
| `Ctrl+Space` then `Esc` | cancel the prefix |

**Soft-leader rule.** `Ctrl+Space` is the terminal NUL character (`'\x00'`). When armed, the initial `Ctrl+Space` keydown is swallowed (handler returns `false`) so the state machine can see the next key. The prefix only "acts" when the following key is one of the shortcut keys above.

Because `attachCustomKeyEventHandler` returning `true` for a later key only lets xterm process *that* key — it does **not** replay the already-swallowed `Ctrl+Space` — the swallowed prefix must be emitted explicitly so the agent loses nothing:

- **Non-shortcut completion:** before returning `true` for the following key, call `term.input('\x00')` to emit the prefix, then let the following key through normally.
- **Timeout (~2s) with no following key:** call `term.input('\x00')` to emit the prefix, then return to idle. A lone `Ctrl+Space` is therefore delivered, not lost — this is what makes it a true soft leader.

**Read-only caveat.** `term.input('\x00')` routes through xterm's `onData`, which is intentionally gated by `readOnlyRef` (`useTerminal.ts:129-133`). In read-only mode the NUL — like any other input — is intentionally dropped and never reaches the backend. "Forward to the agent" therefore means "in interactive mode." This is correct: read-only means no input, and navigation/overlay still work regardless of mode.

**Interference guarantees:**
- We swallow only `Ctrl+Space` (when armed) and the completing shortcut key. Everything byobu owns (`M-`/`S-` arrows, `F12`, `C-a`) is never touched and passes through normally.
- macOS `Option`-produces-glyph concern does not apply (we use `Ctrl`, not `Alt`).

### 4.1 Behavior per layout

The displayed set (§3.2) depends on `layoutMode`:

| Layout (`layoutMode.kind`) | Displayed set | `←`/`→` | `1` | `2`-`4` | `r` |
|---|---|---|---|---|---|
| `grid` | `activeTargets` | cycle, wrap | pane 1 | pane 2-4 if attached, else no-op | toggle focused |
| `lanes` | `teamLanes.sessions` targets (slot order) | cycle, wrap | lane 1 | lane 2-4 if present, else no-op | toggle focused |
| `single` | `[layoutMode.target]` | wrap to same pane (no-op move) | focus it | no-op | toggle focused |

`r` (mode toggle) works in every layout because it acts on the focused pane, independent of the navigation set.

---

## 5. Architecture

### 5.1 Interception (per terminal)

`useTerminal` registers `term.attachCustomKeyEventHandler` implementing a small per-terminal state machine:

```
idle --(Ctrl+Space keydown)--> armed
armed --(shortcut key)--> fire action, return to idle, swallow
armed --(other key)--> emit '\x00' via term.input(), then allow the key, return to idle
armed --(Esc)--> cancel, return to idle, swallow Esc
armed --(2s elapsed)--> emit '\x00' via term.input(), return to idle
```

The handler processes only `keydown` events — it returns `true` (pass through) for `keyup`, composition, and any unrelated event, so it never interferes with IME composition or key-repeat bookkeeping. For `keydown` it returns `false` (swallow) for keys it consumes so they never reach `term.onData` / the agent, and `true` for anything it forwards.

**Callback freshness.** `attachCustomKeyEventHandler` is registered once against the xterm instance and closes over whatever was in scope at registration. To avoid stale callbacks/state, `useTerminal` stores the latest `onLeaderNavigate` / `onLeaderStateChange` callbacks in refs, and uses `readOnlyRef` (already present, `useTerminal.ts:28`) rather than a captured `readOnly` value. The `r` toggle uses a functional update (`setReadOnly(v => !v)`).

### 5.2 Action dispatch

`useTerminal` gains callbacks (stored in refs, supplied by `TerminalView` / `CCBridgePage`). Each carries the **originating terminal target** so `CCBridgePage` resolves navigation relative to the pane that actually received the key, not page state that may be stale:
- `onLeaderNavigate(sourceTarget: string, direction: 'prev' | 'next' | number)` — navigation resolved in `CCBridgePage`, which owns pane order + focus.
- `onLeaderStateChange(sourceTarget: string, active: boolean)` — drives the overlay, unambiguous even with multiple terminals.
- Mode toggle (`r`) is handled **locally** in `useTerminal` via `setReadOnly(v => !v)` — no round trip needed; the existing `mode` control frame carries it to the backend.

### 5.3 Navigation resolution (`CCBridgePage`)

`onLeaderNavigate(sourceTarget, direction)`:
1. Sets `focusedTarget = sourceTarget` first — this repairs any staleness (e.g. `openTeamLanes()` sets `focusedTarget` to `null` at `CCBridgePage.tsx:187`).
2. Computes the displayed set for the active layout:
   - lanes → `teamLanes.sessions.map(s => s.tmux_target)`
   - grid → `activeTargets`
   - single → `[layoutMode.target]`
3. Resolves prev/next (with wrap) relative to `sourceTarget`, or index `N-1` for a number (out-of-range → no-op), sets `focusedTarget` to the resolved pane.

### 5.4 Focusing a pane (prop-driven)

Rather than an imperative registry, focus is prop-driven:
- `TerminalView` accepts a `focused: boolean` prop.
- `useTerminal` returns a `focusTerminal()` method (calls `term.focus()`).
- `TerminalView` runs an effect: when `focused && target`, call `focusTerminal()`.
- The grid passes `focused={focusedTarget === target}`; `TeamLanesView` threads `focused={focusedTarget === session.tmux_target}` to each lane.

This routes subsequent keystrokes to the newly focused pane without `CCBridgePage` holding refs to child terminals.

### 5.5 Overlay

A transient hint rendered by `CCBridgePage`, visible while a focused terminal reports leader-armed, listing:
`Leader: ← prev · → next · 1-4 jump · r toggle mode · Esc cancel`
Auto-dismissed on completion, cancel, or timeout. Optionally flash the focused pane border so the user sees "where they are" before navigating.

---

## 6. Components / Files

Frontend only. No backend change (mode toggle reuses the existing `mode` control frame).

- `frontend/src/features/cc-bridge/useTerminal.ts` — custom key event handler + leader state machine (keydown-only); callbacks-in-refs; `setReadOnly(v => !v)` for `r`; `term.input('\x00')` soft-leader emission; return `focusTerminal()`.
- `frontend/src/features/cc-bridge/TerminalView.tsx` — thread `onLeaderNavigate(sourceTarget, dir)` / `onLeaderStateChange(sourceTarget, active)` props; accept `focused: boolean` and call `focusTerminal()` in an effect.
- `frontend/src/features/cc-bridge/CCBridgePage.tsx` — navigation resolution over the displayed set (per layout, incl. `single`), sets `focusedTarget = sourceTarget` first, overlay state + render, passes `focused` to grid panes.
- `frontend/src/features/cc-bridge/TeamLanesView.tsx` — thread `focused={focusedTarget === session.tmux_target}` to each lane.
- (optional) small `LeaderHintOverlay` component if `CCBridgePage` grows.
- Docs: `docs/features/agent-bridge.md` — document the shortcuts.

No backend change: the `r` mode toggle reuses the existing `mode` control frame, and soft-leader emission uses xterm `term.input()` → the existing `onData` path (no new backend control message).

---

## 7. Test Plan (manual; no FE test harness)

1. `Ctrl+Space` arms the overlay; it lists the keys and dismisses on timeout/cancel/completion.
2. `Ctrl+Space →` / `←` cycle displayed panes in on-screen order, wrapping; works in **grid** (badge order) and **lanes** (slot order).
3. `Ctrl+Space 1..4` jumps to displayed pane N; out-of-range N is a silent no-op.
4. `Ctrl+Space r` toggles the focused pane's read-only/interactive; the mode indicator updates and the backend relay honors it.
5. **Soft-leader:** a lone `Ctrl+Space` (timeout) and `Ctrl+Space` + non-shortcut key both emit NUL and forward the following key to the agent (nothing lost) — verified in **interactive** mode.
6. **Read-only:** navigation and overlay work when the focused pane is read-only; the NUL emission is correctly dropped by the `onData` read-only guard (no backend input).
7. **Single fullscreen:** `1` / `r` act on the fullscreen pane; `←`/`→` are no-op moves; `2-4` no-op.
8. Shortcuts are inert when no bridge terminal is focused (e.g. focus in the sidebar).
9. Sequences behave identically in grid and lanes; navigation resolves against the originating pane even right after `openTeamLanes()` cleared `focusedTarget`.
10. **byobu passthrough:** bare `Alt+Left`/`Alt+Right`/`Shift+Left`/`F12` still reach byobu unchanged (we never intercept them).
11. **Platform check:** confirm `Ctrl+Space` reaches the browser on the target OS/browser (not swallowed by an OS/IME language switcher); if it is, this validates the need for configurable keybindings.

---

## 8. Non-Goals

- Configurable / user-remappable keybindings (future enhancement — but may be promoted to fast-follow if §7.11 platform testing shows `Ctrl+Space` is intercepted by the OS/IME on target machines).
- Shortcuts active when focus is outside a bridge terminal.
- Multi-key chords beyond a single key after the prefix.
- Keyboard-driven session spawn/kill.
- Changing byobu/tmux passthrough behavior for any key we don't explicitly claim.
