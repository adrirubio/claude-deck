# Agent Bridge Terminal Contrast & Focus Fixes — Design Spec

**Status:** Implemented
**Date:** 2026-07-02
**Scope:** Fix two visual regressions introduced by team-color terminal theming — (1) low-contrast text/controls in the terminal bottom bar, and (2) a weak focused-pane indicator — across the Agent Bridge grid and team-lanes layouts.

---

## 1. Problem & Motivation

Team-color theming (`frontend/src/lib/agentTeamColors.ts`) added tinted backgrounds to the terminal bar and pane wrapper per team-slot color. Two regressions followed, sharing one root cause (colored fills sitting behind low-contrast chrome):

1. **Bar readability.** The terminal bottom bar (Read-only/Interactive toggle, connection status, `⌨` shortcuts chip, session label) renders `text-muted-foreground` and faint inactive-button states over `terminalBar: bg-{color}-950/40`. Over seven different tints the text no longer has comfortable contrast.
2. **Focus cue.** The focused pane is signalled only by `focusedTarget === target ? 'bg-primary/60' : 'bg-border/30'` — a faint wash behind a 2px inset gap. Against tinted panes it is hard to tell which pane holds focus.

---

## 2. Current State (as-is)

- `frontend/src/lib/agentTeamColors.ts` — `COLOR_CLASSES[color]` provides `terminalBar` (e.g. `border-blue-500/30 bg-blue-950/40`) and `terminalWrapper` (e.g. `bg-blue-950/20`), plus per-color `TERMINAL_THEMES` for the xterm body (already contrast-tuned fg/bg).
- `frontend/src/features/cc-bridge/TerminalView.tsx` — bottom bar applies `colorClasses.terminalBar`; labels/inactive buttons use `text-muted-foreground`; the connection text and session label are `text-xs text-muted-foreground`.
- `frontend/src/features/cc-bridge/CCBridgePage.tsx:433` — grid pane wrapper: `focusedTarget === target ? 'bg-primary/60' : 'bg-border/30'`, with the terminal inset by 2px (`inset-[2px]`).
- `frontend/src/features/cc-bridge/TeamLanesView.tsx` — each lane uses the same `bg-primary/60` / `bg-border/30` focus pattern.

The app runs in a dark theme.

---

## 3. Design

### 3.1 Fix 1 — Bar readability (decouple from theming)

The bar is chrome; its job is legibility, not color expression. Keep the color *identity* in the bar's accent border and the xterm body (already contrast-tuned), and make the bar surface + text neutral and guaranteed-readable.

- **Bar background:** stop relying on the tinted `bg-{color}-950/40` as the text surface. The bar uses a neutral surface (`bg-background` / `bg-card`); the team color contributes only the **accent border** (`border-{color}-500/…`).
  - Implemented by changing what `terminalBar` carries in `agentTeamColors.ts` — border/accent only, drop the low-contrast fill — so all seven colors are fixed uniformly with no per-color tuning.
- **Bar text/controls:** raise from `text-muted-foreground` to `text-foreground` for the session label and inactive control text; give the inactive Read-only/Interactive buttons and the `⌨` chip higher-contrast neutral states (active state via `bg-primary text-primary-foreground` is unchanged and already fine).

### 3.2 Fix 2 — Focus cue (crisp ring)

Replace the faint background wash with a solid, high-contrast **ring** framing the focused pane.

- **Focused pane:** `ring-2 ring-primary` (or `ring-ring`) on the pane wrapper; a ring reads clearly over any tint because it is a crisp edge, not a color-on-color fill, and it does not touch terminal output (important for watching multiple agents in lanes).
- **Unfocused panes:** no ring, or a neutral hairline border — no colored wash.
- **Ring color:** a single consistent `ring-primary` for all panes (focus is a global UI state; a uniform ring is unambiguous, whereas a per-team ring could be mistaken for more team-coloring).
- Applied in **both** layouts: grid pane wrapper (`CCBridgePage.tsx`) and each lane (`TeamLanesView.tsx`).

---

## 4. Components / Files

Frontend only. No backend change.

- `frontend/src/lib/agentTeamColors.ts` — `terminalBar` becomes accent/border-oriented; drop the low-contrast tinted fill.
- `frontend/src/features/cc-bridge/TerminalView.tsx` — bar text/button contrast tokens (`text-foreground`, higher-contrast inactive states).
- `frontend/src/features/cc-bridge/CCBridgePage.tsx` — replace grid focus wash with `ring-2 ring-primary`.
- `frontend/src/features/cc-bridge/TeamLanesView.tsx` — replace lane focus wash with `ring-2 ring-primary`.

---

## 5. Test Plan (manual; no FE test harness)

1. For each of the 7 team colors, the bar text (labels, connection status, session label, `⌨` chip) is comfortably readable.
2. Inactive Read-only / Interactive buttons are legible; the active one still reads via the primary fill.
3. The team color is still visibly present (accent border on the bar + themed terminal body).
4. Focused pane shows a clear `ring-primary` frame in the **grid**; only one pane is ringed at a time.
5. Same clear focus ring in **team-lanes** layout; still legible over each pane's tint.
6. Unfocused panes have no colored wash and remain easy to read.
7. Focus ring is visible on both themed (team) and un-themed (standalone) panes.
8. Keyboard navigation (`Ctrl+Space` + arrows / 1-4) moves the ring to the correct pane.

---

## 6. Non-Goals

- Redesigning the color palette or adding new team-slot colors.
- Changing the xterm body `TERMINAL_THEMES` (already contrast-tuned).
- Formal WCAG auditing — target is comfortable readability across the existing 7 colors in the dark theme.
- Light-theme work beyond ensuring the neutral bar reads.
- Per-team focus-ring coloring (explicitly rejected in favor of consistent `ring-primary`).
