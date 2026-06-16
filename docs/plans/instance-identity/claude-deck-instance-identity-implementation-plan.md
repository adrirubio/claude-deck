# Claude Deck Instance Identity & Accent Implementation Plan

**Date:** 2026-06-11  
**Target project:** `adrirubio/claude-deck`  
**Suggested branch:** `feature/instance-identity`  
**Primary goal:** Make every Claude Deck browser window clearly identify the backend machine/instance it controls.

---

## 1. Executive summary

When Claude Deck is reachable from another machine on the LAN or tailnet, multiple browser windows can point at different backend hosts while looking visually identical. This is risky in Agent Bridge because actions such as attaching to a terminal, sending input, interrupting a process, spawning a new session, or killing a session affect the real `tmux` sessions on the backend host.

Implement an **Instance Identity** feature:

- Backend exposes an `instance` object in the existing `/status` response.
- Frontend displays the instance name in the top bar as a compact chip.
- Browser tab title becomes `<instance name> · Claude Deck`.
- Each instance can have a small accent color, separate from light/dark theme.
- Agent Bridge surfaces the instance name in session cards, terminal panes, confirmations, and toasts.
- Configuration starts with environment variables and automatic fallbacks; no database migration is needed for the MVP.

The guiding UX principle is:

> The user should always know which physical/logical machine they are controlling before interacting with Agent Bridge.

---

## 2. Current code touchpoints

These are the current integration points to modify. Confirm paths against the local checkout before editing, because `master` may move.

### Backend

- `backend/app/api/v1/status.py`
  - Existing `/status` endpoint currently computes Claude Code version, active Agent Bridge session count, provider statuses, and returns `SystemStatusResponse`.
  - Add `instance=get_instance_identity()` to the response.

- `backend/app/models/schemas.py`
  - Existing location for Pydantic API schemas.
  - Add an `InstanceIdentity` schema.
  - Add optional `instance` field to `SystemStatusResponse`.

- New file: `backend/app/services/instance_identity.py`
  - Resolve runtime identity from environment variables and hostname.
  - Validate accent names.
  - Generate a stable, non-sensitive ID.
  - Cache the result for process lifetime.

### Frontend

- `frontend/src/types/status.ts`
  - Existing `SystemStatusResponse` type includes `claude_code_version`, `active_sessions`, and optional `providers`.
  - Add `InstanceIdentity` and `InstanceAccent` types.

- `frontend/src/hooks/useSystemStatus.ts`
  - Existing hook polls status and maps API fields into frontend state every 30 seconds.
  - Parse and expose `instance`.

- `frontend/src/components/layout/Header.tsx`
  - Existing header renders app branding, provider badges, active sessions, and theme toggle.
  - Add the instance identity chip and top accent border.

- `frontend/src/contexts/ThemeContext.tsx`
  - Existing theme is only `light | dark` via `localStorage` and root classes.
  - Do **not** expand this into many full themes for the MVP.
  - Keep light/dark as theme; implement accent color separately from status instance data.

- New file: `frontend/src/lib/instanceAccent.ts`
  - Central class map for supported accent colors.
  - Use literal Tailwind class strings so the build includes them.

- New file: `frontend/src/hooks/useInstanceDocumentTitle.ts`
  - Sets browser title to `<instance name> · Claude Deck`.

### Agent Bridge

- `frontend/src/features/cc-bridge/types.ts`
  - Existing session objects represent sessions on the current backend only.
  - Do not add per-session host fields for the MVP unless the backend starts aggregating remote machines.

- `frontend/src/features/cc-bridge/CCBridgePage.tsx`
  - Existing page owns session list, active terminal targets, and dialogs.
  - Pull `instance` from `useSystemStatus()` and pass it into child components.

- `frontend/src/features/cc-bridge/SessionList.tsx`
  - Pass `instance` to `SessionCard`.

- `frontend/src/features/cc-bridge/SessionCard.tsx`
  - Add instance name near `tmux` target/project path.

- `frontend/src/features/cc-bridge/TerminalView.tsx`
  - Add instance name in terminal footer while attached.
  - Make interactive/read-only context unmistakable.

- `frontend/src/features/cc-bridge/KillSessionDialog.tsx`
  - Confirmation copy should say which instance the session will be killed on.

---

## 3. User-facing behavior

### 3.1 Header

Target appearance:

```text
[Claude Deck logo] Claude Deck
                  Your local agent command centre

                                  [Studio Mac] [Claude Code ready] [Codex ready] [3 active] [theme toggle]
```

The instance chip should:

- Use `instance.name` as primary label.
- Use a server/monitor icon if available from `lucide-react`.
- Show tooltip/title with:
  - display name
  - hostname
  - browser URL host, e.g. `window.location.host`
- Have an accent-tinted outline/background.
- Degrade gracefully while `/status` is loading.

Recommended tooltip text:

```text
Claude Deck instance: Studio Mac
Hostname: studio-mac.local
Opened from: studio-mac.local:5173
```

### 3.2 Browser title

- Before status loads: `Claude Deck`
- After status loads: `Studio Mac · Claude Deck`
- If instance name changes after reload due to env/config: title updates.

### 3.3 Accent color

Accent is separate from light/dark mode.

Good MVP uses:

- top border of app/header
- instance chip
- active Agent Bridge terminal border or label
- maybe active nav marker later

Do **not** replace the full color system or introduce multiple theme files in the MVP.

### 3.4 Agent Bridge session cards

Current cards already show session name, provider, project, `tmux` target, and kill action. Add the instance name in a subtle line.

Example:

```text
codex-main          [kill]
[Codex CLI]
my-project
Studio Mac · tmux: codex-main:0.1
```

### 3.5 Terminal pane footer

Example:

```text
[Read-only] [Interactive]   Connected · Studio Mac · codex-main:0.1      [Fullscreen] [Close]
```

When interactive mode is active, the footer should make the target instance obvious:

```text
Interactive on Studio Mac
```

This is where mistakes are most costly, so the instance should be visible without needing to look at the header.

### 3.6 Kill confirmations

Current/target copy should include instance identity:

```text
Kill codex-main on Studio Mac?
This will terminate tmux target codex-main:0.1 on hostname studio-mac.local.
```

The primary destructive button can remain `Kill session`.

---

## 4. API design

### 4.1 Response shape

Extend the existing status response:

```json
{
  "claude_code_version": "1.2.3",
  "active_sessions": 3,
  "providers": {
    "claude-code": {
      "id": "claude-code",
      "display_name": "Claude Code",
      "installed": true,
      "version": "1.2.3"
    }
  },
  "instance": {
    "id": "6d5b3e90f2a1",
    "name": "Studio Mac",
    "hostname": "studio-mac.local",
    "short_hostname": "studio-mac",
    "accent": "blue",
    "started_at": "2026-06-11T15:21:43.120000Z"
  }
}
```

### 4.2 Field definitions

| Field | Type | Required | Source | Notes |
|---|---:|---:|---|---|
| `id` | string | yes | env override or hostname hash | Stable-ish, non-sensitive display-neutral ID. Do not expose MAC address or raw machine ID. |
| `name` | string | yes | `CLAUDE_DECK_INSTANCE_NAME` or hostname fallback | Human-facing display name. |
| `hostname` | string | yes | `socket.gethostname()` | Useful for tooltips and confirmations. |
| `short_hostname` | string | yes | derived | First label before `.`. |
| `accent` | string literal | yes | env override or hostname hash | One of the supported accent names. |
| `started_at` | ISO datetime | yes | process start | Useful for debugging which server process the window is attached to. |

### 4.3 Environment variables

Add these optional environment variables:

```bash
CLAUDE_DECK_INSTANCE_NAME="Studio Mac"
CLAUDE_DECK_INSTANCE_ACCENT="blue"
CLAUDE_DECK_INSTANCE_ID="studio-mac"
```

Recommended launch examples:

```bash
CLAUDE_DECK_INSTANCE_NAME="Studio Mac" \
CLAUDE_DECK_INSTANCE_ACCENT="blue" \
./scripts/dev.sh --host 0.0.0.0
```

```bash
CLAUDE_DECK_INSTANCE_NAME="Linux Box" \
CLAUDE_DECK_INSTANCE_ACCENT="green" \
./scripts/dev.sh --host 0.0.0.0
```

```bash
CLAUDE_DECK_INSTANCE_NAME="Garage Mini" \
CLAUDE_DECK_INSTANCE_ACCENT="orange" \
./scripts/dev.sh --host 0.0.0.0
```

### 4.4 Supported accents

Use a small fixed set:

```ts
blue | green | purple | orange | red | pink | cyan | slate
```

Rationale:

- enough variety for multiple machines
- easy to map to Tailwind classes
- easy to document
- avoids arbitrary CSS injection from env vars

### 4.5 Backward compatibility

- Make frontend `instance` optional.
- If missing, show no instance chip or show `This Deck` fallback.
- Do not break older backend/frontend combinations during local development.

---

## 5. Backend implementation details

### 5.1 Add schema

File: `backend/app/models/schemas.py`

Add imports if needed:

```py
from datetime import datetime
from typing import Literal
```

Add near other general response schemas:

```py
InstanceAccent = Literal["blue", "green", "purple", "orange", "red", "pink", "cyan", "slate"]


class InstanceIdentity(BaseModel):
    """Runtime identity for the Claude Deck backend instance."""

    id: str
    name: str
    hostname: str
    short_hostname: str
    accent: InstanceAccent
    started_at: datetime
```

Update `SystemStatusResponse`:

```py
class SystemStatusResponse(BaseModel):
    claude_code_version: Optional[str]
    active_sessions: int
    providers: Optional[Dict[str, AgentProviderStatus]] = None
    instance: Optional[InstanceIdentity] = None
```

Adjust names/types to match the exact existing `SystemStatusResponse` definition in the local checkout.

### 5.2 Add service

File: `backend/app/services/instance_identity.py`

```py
"""Runtime Claude Deck instance identity."""

from __future__ import annotations

import hashlib
import logging
import os
import socket
from datetime import datetime, timezone
from functools import lru_cache

from app.models.schemas import InstanceIdentity

LOGGER = logging.getLogger(__name__)

ALLOWED_ACCENTS: tuple[str, ...] = (
    "blue",
    "green",
    "purple",
    "orange",
    "red",
    "pink",
    "cyan",
    "slate",
)

_STARTED_AT = datetime.now(timezone.utc)
_MAX_NAME_LENGTH = 64
_MAX_ID_LENGTH = 64


def _get_hostname() -> str:
    hostname = socket.gethostname().strip()
    return hostname or "unknown-host"


def _short_hostname(hostname: str) -> str:
    short = hostname.split(".", 1)[0].strip()
    return short or hostname or "unknown-host"


def _clean_name(raw_name: str | None, fallback: str) -> str:
    name = (raw_name or "").strip()
    if not name:
        return fallback[:_MAX_NAME_LENGTH]
    return name[:_MAX_NAME_LENGTH]


def _clean_explicit_id(raw_id: str | None) -> str | None:
    value = (raw_id or "").strip()
    if not value:
        return None
    # Keep this display-neutral and URL/log friendly.
    safe = "".join(ch for ch in value if ch.isalnum() or ch in {"-", "_"})
    return safe[:_MAX_ID_LENGTH] or None


def _stable_id(hostname: str, explicit_id: str | None) -> str:
    cleaned = _clean_explicit_id(explicit_id)
    if cleaned:
        return cleaned
    return hashlib.sha256(f"claude-deck:{hostname}".encode("utf-8")).hexdigest()[:12]


def _accent_from_hostname(hostname: str) -> str:
    digest = hashlib.sha256(hostname.encode("utf-8")).digest()
    return ALLOWED_ACCENTS[digest[0] % len(ALLOWED_ACCENTS)]


def _resolve_accent(hostname: str, raw_accent: str | None) -> str:
    accent = (raw_accent or "").strip().lower()
    if not accent:
        return _accent_from_hostname(hostname)
    if accent in ALLOWED_ACCENTS:
        return accent
    LOGGER.warning(
        "Unsupported CLAUDE_DECK_INSTANCE_ACCENT=%r; using hostname-derived accent",
        raw_accent,
    )
    return _accent_from_hostname(hostname)


@lru_cache(maxsize=1)
def get_instance_identity() -> InstanceIdentity:
    """Return process-lifetime identity for this Claude Deck backend."""

    hostname = _get_hostname()
    short_hostname = _short_hostname(hostname)
    name = _clean_name(os.getenv("CLAUDE_DECK_INSTANCE_NAME"), short_hostname)

    return InstanceIdentity(
        id=_stable_id(hostname, os.getenv("CLAUDE_DECK_INSTANCE_ID")),
        name=name,
        hostname=hostname,
        short_hostname=short_hostname,
        accent=_resolve_accent(hostname, os.getenv("CLAUDE_DECK_INSTANCE_ACCENT")),
        started_at=_STARTED_AT,
    )
```

### 5.3 Update status endpoint

File: `backend/app/api/v1/status.py`

Add import:

```py
from app.services.instance_identity import get_instance_identity
```

Update return:

```py
return SystemStatusResponse(
    claude_code_version=version,
    active_sessions=active_count,
    providers=provider_statuses,
    instance=get_instance_identity(),
)
```

Use the exact existing local variable names.

### 5.4 Backend tests

Add unit tests if backend test structure exists. Suggested file:

`backend/tests/test_instance_identity.py`

Test cases:

1. Defaults work when no env vars are set.
2. `CLAUDE_DECK_INSTANCE_NAME` overrides display name.
3. Valid accent is preserved.
4. Invalid accent falls back to deterministic hostname-derived value.
5. Explicit ID is sanitized and bounded.
6. Generated ID does not expose the raw hostname directly.

Suggested pytest skeleton:

```py
import importlib


def test_instance_identity_env_overrides(monkeypatch):
    module = importlib.import_module("app.services.instance_identity")
    module.get_instance_identity.cache_clear()

    monkeypatch.setenv("CLAUDE_DECK_INSTANCE_NAME", "Studio Mac")
    monkeypatch.setenv("CLAUDE_DECK_INSTANCE_ACCENT", "blue")
    monkeypatch.setenv("CLAUDE_DECK_INSTANCE_ID", "studio-mac")

    identity = module.get_instance_identity()

    assert identity.name == "Studio Mac"
    assert identity.accent == "blue"
    assert identity.id == "studio-mac"
    assert identity.hostname
    assert identity.short_hostname

    module.get_instance_identity.cache_clear()
```

Be careful with `lru_cache`: clear it between tests after changing env vars.

---

## 6. Frontend implementation details

### 6.1 Update status types

File: `frontend/src/types/status.ts`

```ts
import type { AgentProviderStatus } from './providers'

export type InstanceAccent =
  | 'blue'
  | 'green'
  | 'purple'
  | 'orange'
  | 'red'
  | 'pink'
  | 'cyan'
  | 'slate'

export interface InstanceIdentity {
  id: string
  name: string
  hostname: string
  short_hostname: string
  accent: InstanceAccent
  started_at?: string
}

export interface SystemStatusResponse {
  claude_code_version: string | null
  active_sessions: number
  providers?: Record<string, AgentProviderStatus>
  instance?: InstanceIdentity
}
```

Preserve any existing exports in the local file.

### 6.2 Update system status hook

File: `frontend/src/hooks/useSystemStatus.ts`

Ensure the returned status includes `instance`:

```ts
import type { InstanceIdentity } from '@/types/status'

interface SystemStatus {
  claudeCodeVersion: string | null
  activeSessions: number
  providers?: Record<string, AgentProviderStatus>
  instance: InstanceIdentity | null
}
```

When mapping the response:

```ts
setStatus({
  claudeCodeVersion: data.claude_code_version,
  activeSessions: data.active_sessions,
  providers: data.providers,
  instance: data.instance ?? null,
})
```

If the existing hook returns the API response directly, adapt this to the actual local implementation.

### 6.3 Add accent class map

File: `frontend/src/lib/instanceAccent.ts`

Use literal class names. Do not generate Tailwind class names dynamically.

```ts
import type { InstanceAccent } from '@/types/status'

export interface InstanceAccentClasses {
  headerBorder: string
  badge: string
  dot: string
  terminal: string
}

export const DEFAULT_INSTANCE_ACCENT: InstanceAccent = 'blue'

export const INSTANCE_ACCENT_CLASSES: Record<InstanceAccent, InstanceAccentClasses> = {
  blue: {
    headerBorder: 'border-t-blue-500',
    badge: 'border-blue-500/40 bg-blue-500/10 text-blue-700 dark:text-blue-300',
    dot: 'bg-blue-500',
    terminal: 'border-blue-500/40',
  },
  green: {
    headerBorder: 'border-t-green-500',
    badge: 'border-green-500/40 bg-green-500/10 text-green-700 dark:text-green-300',
    dot: 'bg-green-500',
    terminal: 'border-green-500/40',
  },
  purple: {
    headerBorder: 'border-t-purple-500',
    badge: 'border-purple-500/40 bg-purple-500/10 text-purple-700 dark:text-purple-300',
    dot: 'bg-purple-500',
    terminal: 'border-purple-500/40',
  },
  orange: {
    headerBorder: 'border-t-orange-500',
    badge: 'border-orange-500/40 bg-orange-500/10 text-orange-700 dark:text-orange-300',
    dot: 'bg-orange-500',
    terminal: 'border-orange-500/40',
  },
  red: {
    headerBorder: 'border-t-red-500',
    badge: 'border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300',
    dot: 'bg-red-500',
    terminal: 'border-red-500/40',
  },
  pink: {
    headerBorder: 'border-t-pink-500',
    badge: 'border-pink-500/40 bg-pink-500/10 text-pink-700 dark:text-pink-300',
    dot: 'bg-pink-500',
    terminal: 'border-pink-500/40',
  },
  cyan: {
    headerBorder: 'border-t-cyan-500',
    badge: 'border-cyan-500/40 bg-cyan-500/10 text-cyan-700 dark:text-cyan-300',
    dot: 'bg-cyan-500',
    terminal: 'border-cyan-500/40',
  },
  slate: {
    headerBorder: 'border-t-slate-500',
    badge: 'border-slate-500/40 bg-slate-500/10 text-slate-700 dark:text-slate-300',
    dot: 'bg-slate-500',
    terminal: 'border-slate-500/40',
  },
}

export function getInstanceAccentClasses(accent?: string | null): InstanceAccentClasses {
  if (!accent || !(accent in INSTANCE_ACCENT_CLASSES)) {
    return INSTANCE_ACCENT_CLASSES[DEFAULT_INSTANCE_ACCENT]
  }
  return INSTANCE_ACCENT_CLASSES[accent as InstanceAccent]
}
```

### 6.4 Add document title hook

File: `frontend/src/hooks/useInstanceDocumentTitle.ts`

```ts
import { useEffect } from 'react'

import type { InstanceIdentity } from '@/types/status'

const BASE_TITLE = 'Claude Deck'

export function useInstanceDocumentTitle(instance?: InstanceIdentity | null) {
  useEffect(() => {
    document.title = instance?.name ? `${instance.name} · ${BASE_TITLE}` : BASE_TITLE
  }, [instance?.name])
}
```

Call this in `Header` or in `MainLayout`. Since `Header` already calls `useSystemStatus`, putting it there is the smallest change. If another component later needs status, consider lifting status into context to avoid duplicate polling.

### 6.5 Update Header

File: `frontend/src/components/layout/Header.tsx`

Add imports:

```ts
import { Server } from 'lucide-react'
import { getInstanceAccentClasses } from '@/lib/instanceAccent'
import { useInstanceDocumentTitle } from '@/hooks/useInstanceDocumentTitle'
```

The existing import from `lucide-react` can become:

```ts
import { Terminal, Radio, AlertCircle, Server } from 'lucide-react'
```

Inside `Header()`:

```ts
const instance = status?.instance ?? null
const accentClasses = getInstanceAccentClasses(instance?.accent)
useInstanceDocumentTitle(instance)

const instanceTitle = instance
  ? [
      `Claude Deck instance: ${instance.name}`,
      `Hostname: ${instance.hostname}`,
      `Opened from: ${window.location.host}`,
    ].join('\n')
  : 'Claude Deck instance loading'
```

Change header class:

```tsx
<header className={cn('border-b border-t-4 bg-background', accentClasses.headerBorder)}>
```

Add chip before provider badges:

```tsx
{instance && (
  <Badge
    variant="outline"
    className={cn('gap-1 text-xs max-w-[12rem] truncate', accentClasses.badge)}
    title={instanceTitle}
  >
    <Server className="h-3 w-3 shrink-0" />
    <span className={cn('h-2 w-2 rounded-full shrink-0', accentClasses.dot)} />
    <span className="truncate">{instance.name}</span>
  </Badge>
)}
```

Notes:

- Keep `Claude Deck` as the main product title.
- Keep subtitle as-is for now.
- On narrow screens, the chip can truncate. The tooltip still contains full hostname.
- Do not show raw interface/IP information by default.

---

## 7. Agent Bridge implementation details

### 7.1 Pass instance through CCBridgePage

File: `frontend/src/features/cc-bridge/CCBridgePage.tsx`

Add imports:

```ts
import { useSystemStatus } from '@/hooks/useSystemStatus'
```

Inside the page:

```ts
const status = useSystemStatus()
const instance = status?.instance ?? null
```

Pass to children:

```tsx
<SessionList
  sessions={sessions}
  activeTargets={activeTargets}
  onSessionClick={handleSessionClick}
  onKillSession={setKillSession}
  instance={instance}
/>
```

```tsx
<TerminalView
  target={target}
  fullscreen={fullscreenTarget === target}
  onToggleFullscreen={() => toggleFullscreen(target)}
  onClose={() => closeTarget(target)}
  instance={instance}
/>
```

```tsx
<KillSessionDialog
  session={killSession}
  open={Boolean(killSession)}
  onOpenChange={...}
  onConfirm={...}
  instance={instance}
/>
```

Match the exact local prop names.

### 7.2 Update SessionList props

File: `frontend/src/features/cc-bridge/SessionList.tsx`

```ts
import type { InstanceIdentity } from '@/types/status'

interface SessionListProps {
  // existing props...
  instance?: InstanceIdentity | null
}
```

Pass to card:

```tsx
<SessionCard
  session={session}
  gridPosition={gridPosition}
  onClick={() => onSessionClick(session)}
  onKill={onKillSession}
  instance={instance}
/>
```

### 7.3 Update SessionCard

File: `frontend/src/features/cc-bridge/SessionCard.tsx`

Add type import:

```ts
import type { InstanceIdentity } from '@/types/status'
```

Update props:

```ts
interface SessionCardProps {
  session: CCSession
  gridPosition: number | null
  onClick: () => void
  onKill: (session: CCSession) => void
  instance?: InstanceIdentity | null
}
```

Update signature:

```ts
export function SessionCard({ session, gridPosition, onClick, onKill, instance }: SessionCardProps) {
```

Add text near existing `tmux` target line:

```tsx
<p
  className="text-xs text-muted-foreground mt-0.5 truncate"
  title={instance ? `${instance.name} · ${session.tmux_target}` : session.tmux_target}
>
  {instance ? `${instance.name} · ` : ''}tmux: {session.tmux_target}
</p>
```

If the existing card already has a `tmux` line, replace it rather than duplicating it.

### 7.4 Update TerminalView

File: `frontend/src/features/cc-bridge/TerminalView.tsx`

Add type import:

```ts
import type { InstanceIdentity } from '@/types/status'
import { getInstanceAccentClasses } from '@/lib/instanceAccent'
```

Update props:

```ts
interface TerminalViewProps {
  target: string | null
  fullscreen?: boolean
  onToggleFullscreen?: () => void
  onClose?: () => void
  instance?: InstanceIdentity | null
}
```

Update signature:

```ts
export function TerminalView({ target, fullscreen, onToggleFullscreen, onClose, instance }: TerminalViewProps) {
```

Inside component:

```ts
const accentClasses = getInstanceAccentClasses(instance?.accent)
const modeLabel = readOnly ? 'Read-only' : 'Interactive'
```

Update footer wrapper:

```tsx
<div className={cn('flex items-center justify-between px-3 py-2 border-t bg-background', accentClasses.terminal)}>
```

Add instance context to footer left area:

```tsx
<span
  className="text-xs text-muted-foreground truncate max-w-[18rem]"
  title={instance ? `${modeLabel} on ${instance.name} (${instance.hostname}) · ${target}` : target ?? undefined}
>
  {instance ? `${modeLabel} on ${instance.name}` : modeLabel}
</span>
```

Keep the existing connection indicator. Avoid clutter by not duplicating `target` too many times.

### 7.5 Update KillSessionDialog

File: `frontend/src/features/cc-bridge/KillSessionDialog.tsx`

Add type import:

```ts
import type { InstanceIdentity } from '@/types/status'
```

Update props:

```ts
interface KillSessionDialogProps {
  // existing props...
  instance?: InstanceIdentity | null
}
```

Use copy like:

```tsx
<AlertDialogTitle>
  Kill {session?.session_name ?? 'session'}{instance ? ` on ${instance.name}` : ''}?
</AlertDialogTitle>

<AlertDialogDescription>
  This will terminate tmux target {session?.tmux_target}
  {instance ? ` on hostname ${instance.hostname}` : ''}.
</AlertDialogDescription>
```

### 7.6 Update toasts

Find kill/spawn/resume/fork toasts in `CCBridgePage.tsx` or related hooks.

Include the instance name where useful:

```ts
const instanceSuffix = instance?.name ? ` on ${instance.name}` : ''

toast.success(`Killed ${session.session_name}${instanceSuffix}`)
toast.success(`Started ${providerName}${instanceSuffix}`)
toast.error(`Failed to kill ${session.session_name}${instanceSuffix}`)
```

Keep messages short.

---

## 8. Styling guidance

### 8.1 Keep theme and accent separate

Current theme mode remains:

```ts
light | dark
```

New accent is backend-provided instance metadata:

```ts
blue | green | purple | orange | red | pink | cyan | slate
```

This avoids a large theme refactor.

### 8.2 Tailwind safelist caution

Do not use interpolated class strings like:

```ts
`border-t-${accent}-500`
```

Tailwind will not reliably include those classes unless configured. Use a static mapping object with every class name written literally.

### 8.3 Accessibility

- The instance chip should have a text label, not only color.
- Accent color must be supplemental, not the only way to identify the instance.
- Tooltip/title should include the full hostname.
- Destructive action dialogs should include text identity.

---

## 9. Documentation updates

Update README or a new docs page.

Suggested README section near Development:

```md
### Naming a Claude Deck instance

When running several Claude Deck servers on different machines, set a display name and accent color so each browser window is easy to recognize:

```bash
CLAUDE_DECK_INSTANCE_NAME="Studio Mac" \
CLAUDE_DECK_INSTANCE_ACCENT="blue" \
./scripts/dev.sh --host 0.0.0.0
```

Supported accents: `blue`, `green`, `purple`, `orange`, `red`, `pink`, `cyan`, `slate`.

The name is shown in the top bar, browser tab title, Agent Bridge session cards, terminal panes, and destructive confirmations.
```

If `.env.example` exists, add:

```bash
# Optional display identity for multi-machine Claude Deck usage
CLAUDE_DECK_INSTANCE_NAME=
CLAUDE_DECK_INSTANCE_ACCENT=blue
CLAUDE_DECK_INSTANCE_ID=
```

---

## 10. Validation plan

### 10.1 Backend manual validation

Start normally:

```bash
./scripts/dev.sh
```

Open status endpoint in API docs or curl the existing status URL. In dev this is expected to be under the backend at `localhost:8000`; confirm route prefix locally.

Expected:

```json
"instance": {
  "id": "...",
  "name": "<short hostname>",
  "hostname": "<hostname>",
  "short_hostname": "<short hostname>",
  "accent": "<deterministic accent>",
  "started_at": "..."
}
```

Start with env vars:

```bash
CLAUDE_DECK_INSTANCE_NAME="Studio Mac" \
CLAUDE_DECK_INSTANCE_ACCENT="blue" \
CLAUDE_DECK_INSTANCE_ID="studio-mac" \
./scripts/dev.sh --host 0.0.0.0
```

Expected:

```json
"instance": {
  "id": "studio-mac",
  "name": "Studio Mac",
  "accent": "blue"
}
```

Invalid accent:

```bash
CLAUDE_DECK_INSTANCE_ACCENT="neon" ./scripts/dev.sh
```

Expected:

- no crash
- backend logs warning or silently falls back
- `/status.instance.accent` is one of supported values

### 10.2 Frontend validation

Run:

```bash
cd frontend
npm run lint
npm run build
```

Expected UI behavior:

- Header shows instance chip.
- Header has accent top border.
- Browser title updates after status load.
- Provider badges and active sessions still render.
- Theme toggle still works.
- No TypeScript errors.

### 10.3 Agent Bridge validation

With a real or test `tmux` session:

- Open Agent Bridge.
- Session cards show instance name and `tmux` target.
- Attach terminal pane; footer shows instance name.
- Switch read-only/interactive; footer remains clear.
- Kill dialog title/body include instance name and hostname.
- Kill/spawn toasts include instance name where applicable.

### 10.4 Multi-machine validation

Run on two machines:

Machine A:

```bash
CLAUDE_DECK_INSTANCE_NAME="Studio Mac" CLAUDE_DECK_INSTANCE_ACCENT="blue" ./scripts/dev.sh --host 0.0.0.0
```

Machine B:

```bash
CLAUDE_DECK_INSTANCE_NAME="Linux Box" CLAUDE_DECK_INSTANCE_ACCENT="green" ./scripts/dev.sh --host 0.0.0.0
```

From a third machine/browser:

- Open both frontends in separate windows.
- Browser switcher should show distinct titles.
- Headers should show distinct instance chips and accents.
- Agent Bridge terminal panes should identify the correct instance.

### 10.5 Release/build validation

Run repository release check if available:

```bash
./scripts/build.sh
```

Expected:

- frontend builds
- docs build still works
- no backend import errors

---

## 11. Acceptance criteria

The feature is complete when all of these are true:

- `/status` includes `instance` with `id`, `name`, `hostname`, `short_hostname`, `accent`, and `started_at`.
- With no env vars, Claude Deck still starts and uses hostname-derived defaults.
- With env vars, the configured name/accent/id appear in `/status`.
- Invalid accents do not crash the backend.
- Header displays an instance chip using `instance.name`.
- Header tooltip includes hostname and browser host.
- Browser title is `<instance name> · Claude Deck` after status loads.
- Accent color is visible but does not replace light/dark theme.
- Agent Bridge session cards show the instance name.
- Agent Bridge terminal footer shows the instance name, especially in interactive mode.
- Kill session confirmation includes instance name and hostname.
- Relevant toasts include instance name.
- `npm run lint` and `npm run build` pass in the frontend.
- Backend tests pass if tests are present.
- No raw MAC address, raw machine-id, full interface list, auth data, or secret config values are exposed.

---

## 12. Non-goals for MVP

Do not implement these in the first pass unless everything above is already merged and stable:

- Remote Deck switcher.
- Multi-instance overview dashboard.
- Central proxy to control sessions across machines.
- Server-side settings UI/database persistence.
- Favicon generation.
- Full theme marketplace or arbitrary custom colors.
- Per-session host metadata. For now, all sessions are local to the current backend instance.

---

## 13. Phase 2 ideas

After the MVP ships, consider:

1. **Deck switcher**
   - Browser-local list of known Deck URLs.
   - Lets users jump between `Studio Mac`, `Linux Box`, etc.
   - No proxying; just navigation.

2. **Read-only multi-instance overview**
   - Poll registered Deck URLs’ `/status` endpoint.
   - Show active session counts and provider readiness.
   - Link out to each Deck.

3. **Settings UI**
   - Edit display name/accent from Claude Deck.
   - Persist server-side config.
   - More complex than env vars, so not MVP.

4. **Favicon badge**
   - Generate accent-colored favicon or small badge.
   - Helps OS/browser window switching.

5. **Instance-aware exported diagnostics**
   - Include `instance.name`, `hostname`, and `started_at` in safe diagnostics bundles.
   - Do not include raw secrets or identifiers.

---

## 14. Suggested PR structure

### PR 1: Backend status identity

Files:

- `backend/app/models/schemas.py`
- `backend/app/services/instance_identity.py`
- `backend/app/api/v1/status.py`
- backend tests if present
- README env var note if desired

Acceptance:

- `/status.instance` works.
- No frontend behavior change required yet.

### PR 2: Header identity + title

Files:

- `frontend/src/types/status.ts`
- `frontend/src/hooks/useSystemStatus.ts`
- `frontend/src/hooks/useInstanceDocumentTitle.ts`
- `frontend/src/lib/instanceAccent.ts`
- `frontend/src/components/layout/Header.tsx`

Acceptance:

- Header chip visible.
- Browser title updated.
- Accent top border visible.

### PR 3: Agent Bridge instance labels

Files:

- `frontend/src/features/cc-bridge/CCBridgePage.tsx`
- `frontend/src/features/cc-bridge/SessionList.tsx`
- `frontend/src/features/cc-bridge/SessionCard.tsx`
- `frontend/src/features/cc-bridge/TerminalView.tsx`
- `frontend/src/features/cc-bridge/KillSessionDialog.tsx`
- any toast/hook files that own kill/spawn messages

Acceptance:

- Session cards and terminal panes identify instance.
- Kill confirmation includes instance.

### PR 4: Docs + QA polish

Files:

- `README.md`
- `.env.example`, if present
- docs page, if desired
- tests/story snapshots if project has them

Acceptance:

- Examples documented.
- Build/lint/test pass.

---

## 15. Handoff notes for local agents

Give agents precise boundaries:

- Backend agent owns API/schema/service only.
- Header/theme agent owns status types, document title, accent utilities, and header UI.
- Agent Bridge agent owns cards, terminal footer, dialog copy, and toasts.
- QA/docs agent owns validation, docs, and final consistency pass.

Do not let agents independently invent different names for the same concepts. Use these exact names:

- Feature name: **Instance Identity**
- Type: `InstanceIdentity`
- Hook: `useInstanceDocumentTitle`
- Accent utility: `getInstanceAccentClasses`
- Env vars:
  - `CLAUDE_DECK_INSTANCE_NAME`
  - `CLAUDE_DECK_INSTANCE_ACCENT`
  - `CLAUDE_DECK_INSTANCE_ID`

---

## 16. Final Definition of Done

A user with three machines can run:

```bash
CLAUDE_DECK_INSTANCE_NAME="Studio Mac" CLAUDE_DECK_INSTANCE_ACCENT="blue" ./scripts/dev.sh --host 0.0.0.0
CLAUDE_DECK_INSTANCE_NAME="Linux Box" CLAUDE_DECK_INSTANCE_ACCENT="green" ./scripts/dev.sh --host 0.0.0.0
CLAUDE_DECK_INSTANCE_NAME="Garage Mini" CLAUDE_DECK_INSTANCE_ACCENT="orange" ./scripts/dev.sh --host 0.0.0.0
```

Then open three Claude Deck windows and immediately see:

- different browser titles
- different header chips
- different accent bars
- Agent Bridge session/terminal labels showing the correct machine
- kill confirmations that name the exact target instance

No extra setup should be required beyond optional environment variables.


---

# Agent Task Pack: Claude Deck Instance Identity

Use these as direct prompts/tasks for local coding agents. Each task has clear ownership and acceptance criteria.

---

## Task 0 — Integration conductor

**Role:** Coordinate branch, review PRs/patches, and prevent scope creep.

**Goal:** Ship backend-driven Instance Identity without turning it into a full theming/settings refactor.

**Instructions:**

1. Create branch `feature/instance-identity`.
2. Assign tasks in this file to agents.
3. Make sure every agent uses the same API shape and names.
4. Keep accent separate from light/dark theme.
5. Keep `instance` optional on the frontend.
6. Run final validation checklist.

**Definition of done:**

- All acceptance criteria in `ACCEPTANCE_CHECKLIST.md` pass.
- No agent added a remote proxy, database migration, or settings UI in MVP.

---

## Task 1 — Backend instance identity

**Owner:** Backend agent  
**Files:**

- `backend/app/models/schemas.py`
- `backend/app/services/instance_identity.py`
- `backend/app/api/v1/status.py`
- backend tests if present

**Goal:** Expose runtime backend identity in the existing status response.

**API shape:**

```json
"instance": {
  "id": "studio-mac",
  "name": "Studio Mac",
  "hostname": "studio-mac.local",
  "short_hostname": "studio-mac",
  "accent": "blue",
  "started_at": "2026-06-11T15:21:43.120000Z"
}
```

**Steps:**

1. Add `InstanceIdentity` schema.
2. Add optional `instance` to `SystemStatusResponse`.
3. Create `backend/app/services/instance_identity.py`.
4. Resolve env vars:
   - `CLAUDE_DECK_INSTANCE_NAME`
   - `CLAUDE_DECK_INSTANCE_ACCENT`
   - `CLAUDE_DECK_INSTANCE_ID`
5. Fallback to hostname-derived `name`, `id`, and `accent` when env vars are missing.
6. Validate accent against:
   - `blue`
   - `green`
   - `purple`
   - `orange`
   - `red`
   - `pink`
   - `cyan`
   - `slate`
7. Update `/status` to include `instance=get_instance_identity()`.
8. Add/adjust tests.

**Acceptance criteria:**

- `/status.instance` exists.
- Env overrides work.
- Invalid accent does not crash.
- No raw MAC address or machine-id is exposed.
- Backend tests pass if present.

---

## Task 2 — Frontend status types, document title, and accent utility

**Owner:** Frontend foundation agent  
**Files:**

- `frontend/src/types/status.ts`
- `frontend/src/hooks/useSystemStatus.ts`
- `frontend/src/hooks/useInstanceDocumentTitle.ts`
- `frontend/src/lib/instanceAccent.ts`

**Goal:** Make instance identity available to UI components.

**Steps:**

1. Add `InstanceAccent` type.
2. Add `InstanceIdentity` interface.
3. Add optional `instance?: InstanceIdentity` to `SystemStatusResponse`.
4. Update `useSystemStatus` returned shape to include `instance: InstanceIdentity | null`.
5. Add `useInstanceDocumentTitle(instance)` hook.
6. Add `getInstanceAccentClasses(accent)` utility with static Tailwind class map.

**Important:** Do not generate Tailwind class names dynamically.

**Acceptance criteria:**

- TypeScript compiles.
- Hook returns `instance` without breaking existing consumers.
- `document.title` can be updated by consumers.
- All supported accents have class mappings.

---

## Task 3 — Header instance chip

**Owner:** Frontend UI agent  
**Files:**

- `frontend/src/components/layout/Header.tsx`

**Goal:** Make the current Claude Deck instance obvious in the top bar.

**Steps:**

1. Read `instance` from existing `useSystemStatus()` call.
2. Call `useInstanceDocumentTitle(instance)`.
3. Add top border accent to header.
4. Add instance badge/chip before provider badges.
5. Badge label should be `instance.name`.
6. Badge tooltip should include:
   - display name
   - hostname
   - `window.location.host`
7. Keep the product title `Claude Deck` unchanged.
8. Keep `ThemeToggle` behavior unchanged.

**Acceptance criteria:**

- Header shows `Studio Mac` when backend returns that name.
- Browser title becomes `Studio Mac · Claude Deck`.
- Accent is visible in both light and dark modes.
- Existing provider/version/active session badges still work.

---

## Task 4 — Agent Bridge instance labels

**Owner:** Agent Bridge frontend agent  
**Files:**

- `frontend/src/features/cc-bridge/CCBridgePage.tsx`
- `frontend/src/features/cc-bridge/SessionList.tsx`
- `frontend/src/features/cc-bridge/SessionCard.tsx`
- `frontend/src/features/cc-bridge/TerminalView.tsx`
- `frontend/src/features/cc-bridge/KillSessionDialog.tsx`
- toast-related files if kill/spawn toasts are elsewhere

**Goal:** Prevent wrong-machine mistakes during terminal/session operations.

**Steps:**

1. In `CCBridgePage`, call `useSystemStatus()` and derive `instance`.
2. Pass `instance` to `SessionList`, `TerminalView`, and `KillSessionDialog`.
3. In `SessionList`, pass `instance` to `SessionCard`.
4. In `SessionCard`, display `instance.name` next to the existing `tmux` target line.
5. In `TerminalView`, show `Read-only on <name>` or `Interactive on <name>` in the footer.
6. In `KillSessionDialog`, include instance name and hostname in title/body.
7. Update success/error toasts for kill/spawn/resume/fork to include `on <instance.name>` where useful.

**Acceptance criteria:**

- Session cards identify the backend instance.
- Terminal panes identify the backend instance while attached.
- Interactive mode clearly says which instance is interactive.
- Kill confirmation names the instance and hostname.
- Existing Agent Bridge functionality remains unchanged.

---

## Task 5 — Documentation and examples

**Owner:** Docs/QA agent  
**Files:**

- `README.md`
- `.env.example` if present
- docs page if desired

**Goal:** Document how to name/color Claude Deck instances.

**Steps:**

1. Add a README section near Development or Agent Bridge usage.
2. Include examples for multiple machines.
3. Document supported accents.
4. Mention where the name appears:
   - header
   - browser title
   - Agent Bridge session cards
   - terminal pane footer
   - destructive confirmations
5. Add env vars to `.env.example` if the file exists.

**Acceptance criteria:**

- A user can configure two machines from docs alone.
- Docs mention that env vars are optional.
- Docs state that hostname is fallback.

---

## Task 6 — QA and final review

**Owner:** QA agent  
**Goal:** Verify implementation against real local usage.

**Commands:**

```bash
cd frontend
npm run lint
npm run build
```

```bash
cd backend
python -m pytest
```

If backend tests are not configured, run the project manually and test `/status` via API docs/curl.

**Manual scenarios:**

1. No env vars.
2. Valid env vars.
3. Invalid accent.
4. Two machines/two windows.
5. Agent Bridge attach/detach.
6. Interactive mode.
7. Kill confirmation.
8. Dark/light mode toggle.

**Acceptance criteria:**

- All checklist items pass.
- No unrelated UI regressions.
- No sensitive local identifiers exposed.


---

# Acceptance Checklist: Claude Deck Instance Identity

Use this checklist before merging.

## Backend API

- [ ] `/status` includes an `instance` object.
- [ ] `instance.id` is present.
- [ ] `instance.name` is present.
- [ ] `instance.hostname` is present.
- [ ] `instance.short_hostname` is present.
- [ ] `instance.accent` is one of: `blue`, `green`, `purple`, `orange`, `red`, `pink`, `cyan`, `slate`.
- [ ] `instance.started_at` is present and ISO-serializable.
- [ ] With no env vars, backend uses hostname-derived defaults.
- [ ] `CLAUDE_DECK_INSTANCE_NAME` overrides `instance.name`.
- [ ] `CLAUDE_DECK_INSTANCE_ACCENT` overrides `instance.accent` when valid.
- [ ] Invalid `CLAUDE_DECK_INSTANCE_ACCENT` falls back without crashing.
- [ ] `CLAUDE_DECK_INSTANCE_ID` overrides `instance.id` safely.
- [ ] No raw MAC address, raw machine-id, auth token, or secret config appears in `/status`.

## Frontend header

- [ ] Header still shows `Claude Deck` as app title.
- [ ] Header shows an instance chip when `status.instance` exists.
- [ ] Instance chip displays `instance.name`.
- [ ] Instance chip tooltip/title includes `instance.hostname`.
- [ ] Instance chip tooltip/title includes `window.location.host`.
- [ ] Header has an accent-colored top border.
- [ ] Accent is visible in light mode.
- [ ] Accent is visible in dark mode.
- [ ] Provider badges still render.
- [ ] Active session count badge still renders.
- [ ] Theme toggle still works.
- [ ] Layout does not overflow badly on normal laptop widths.

## Browser title

- [ ] Before status loads, title is `Claude Deck` or existing fallback.
- [ ] After status loads, title is `<instance name> · Claude Deck`.
- [ ] Two different Deck windows show different OS/browser switcher titles when configured differently.

## Agent Bridge

- [ ] Session cards show instance name near the `tmux` target/project metadata.
- [ ] Terminal footer shows instance name when attached.
- [ ] Terminal footer makes read-only vs interactive mode clear.
- [ ] Interactive mode text includes the instance name.
- [ ] Kill session dialog title includes instance name.
- [ ] Kill session dialog body includes hostname or target instance detail.
- [ ] Kill/spawn/resume/fork toasts include instance name where useful.
- [ ] Existing attach/detach behavior still works.
- [ ] Existing fullscreen behavior still works.
- [ ] Existing close terminal behavior still works.

## Build/test

- [ ] `cd frontend && npm run lint` passes.
- [ ] `cd frontend && npm run build` passes.
- [ ] `cd backend && python -m pytest` passes, if backend tests are configured.
- [ ] `./scripts/build.sh` passes, if used as the release check.

## Multi-machine smoke test

- [ ] Machine A with `Studio Mac / blue` displays `Studio Mac` and blue accent.
- [ ] Machine B with `Linux Box / green` displays `Linux Box` and green accent.
- [ ] Both windows can be opened from a third machine.
- [ ] Browser title, header chip, Agent Bridge cards, and terminal footer all match the correct backend.

## Scope control

- [ ] No central proxy was added.
- [ ] No database migration was added for this MVP.
- [ ] No full theme system refactor was added.
- [ ] No arbitrary user-supplied CSS/classes are rendered.
- [ ] `instance` is optional on the frontend for compatibility.


---

# Code Skeletons: Claude Deck Instance Identity

These snippets are intended to accelerate implementation. Adapt them to the exact local code style and imports.

---

## Backend schema

File: `backend/app/models/schemas.py`

```py
from datetime import datetime
from typing import Literal

InstanceAccent = Literal["blue", "green", "purple", "orange", "red", "pink", "cyan", "slate"]


class InstanceIdentity(BaseModel):
    """Runtime identity for the Claude Deck backend instance."""

    id: str
    name: str
    hostname: str
    short_hostname: str
    accent: InstanceAccent
    started_at: datetime
```

Update status response:

```py
class SystemStatusResponse(BaseModel):
    claude_code_version: Optional[str]
    active_sessions: int
    providers: Optional[Dict[str, AgentProviderStatus]] = None
    instance: Optional[InstanceIdentity] = None
```

---

## Backend service

File: `backend/app/services/instance_identity.py`

```py
"""Runtime Claude Deck instance identity."""

from __future__ import annotations

import hashlib
import logging
import os
import socket
from datetime import datetime, timezone
from functools import lru_cache

from app.models.schemas import InstanceIdentity

LOGGER = logging.getLogger(__name__)

ALLOWED_ACCENTS: tuple[str, ...] = (
    "blue",
    "green",
    "purple",
    "orange",
    "red",
    "pink",
    "cyan",
    "slate",
)

_STARTED_AT = datetime.now(timezone.utc)
_MAX_NAME_LENGTH = 64
_MAX_ID_LENGTH = 64


def _get_hostname() -> str:
    hostname = socket.gethostname().strip()
    return hostname or "unknown-host"


def _short_hostname(hostname: str) -> str:
    short = hostname.split(".", 1)[0].strip()
    return short or hostname or "unknown-host"


def _clean_name(raw_name: str | None, fallback: str) -> str:
    name = (raw_name or "").strip()
    if not name:
        return fallback[:_MAX_NAME_LENGTH]
    return name[:_MAX_NAME_LENGTH]


def _clean_explicit_id(raw_id: str | None) -> str | None:
    value = (raw_id or "").strip()
    if not value:
        return None
    safe = "".join(ch for ch in value if ch.isalnum() or ch in {"-", "_"})
    return safe[:_MAX_ID_LENGTH] or None


def _stable_id(hostname: str, explicit_id: str | None) -> str:
    cleaned = _clean_explicit_id(explicit_id)
    if cleaned:
        return cleaned
    return hashlib.sha256(f"claude-deck:{hostname}".encode("utf-8")).hexdigest()[:12]


def _accent_from_hostname(hostname: str) -> str:
    digest = hashlib.sha256(hostname.encode("utf-8")).digest()
    return ALLOWED_ACCENTS[digest[0] % len(ALLOWED_ACCENTS)]


def _resolve_accent(hostname: str, raw_accent: str | None) -> str:
    accent = (raw_accent or "").strip().lower()
    if not accent:
        return _accent_from_hostname(hostname)
    if accent in ALLOWED_ACCENTS:
        return accent
    LOGGER.warning(
        "Unsupported CLAUDE_DECK_INSTANCE_ACCENT=%r; using hostname-derived accent",
        raw_accent,
    )
    return _accent_from_hostname(hostname)


@lru_cache(maxsize=1)
def get_instance_identity() -> InstanceIdentity:
    hostname = _get_hostname()
    short_hostname = _short_hostname(hostname)
    name = _clean_name(os.getenv("CLAUDE_DECK_INSTANCE_NAME"), short_hostname)

    return InstanceIdentity(
        id=_stable_id(hostname, os.getenv("CLAUDE_DECK_INSTANCE_ID")),
        name=name,
        hostname=hostname,
        short_hostname=short_hostname,
        accent=_resolve_accent(hostname, os.getenv("CLAUDE_DECK_INSTANCE_ACCENT")),
        started_at=_STARTED_AT,
    )
```

---

## Backend status endpoint patch

File: `backend/app/api/v1/status.py`

```py
from app.services.instance_identity import get_instance_identity
```

```py
return SystemStatusResponse(
    claude_code_version=version,
    active_sessions=active_count,
    providers=provider_statuses,
    instance=get_instance_identity(),
)
```

---

## Frontend status types

File: `frontend/src/types/status.ts`

```ts
import type { AgentProviderStatus } from './providers'

export type InstanceAccent =
  | 'blue'
  | 'green'
  | 'purple'
  | 'orange'
  | 'red'
  | 'pink'
  | 'cyan'
  | 'slate'

export interface InstanceIdentity {
  id: string
  name: string
  hostname: string
  short_hostname: string
  accent: InstanceAccent
  started_at?: string
}

export interface SystemStatusResponse {
  claude_code_version: string | null
  active_sessions: number
  providers?: Record<string, AgentProviderStatus>
  instance?: InstanceIdentity
}
```

---

## Frontend accent utility

File: `frontend/src/lib/instanceAccent.ts`

```ts
import type { InstanceAccent } from '@/types/status'

export interface InstanceAccentClasses {
  headerBorder: string
  badge: string
  dot: string
  terminal: string
}

export const DEFAULT_INSTANCE_ACCENT: InstanceAccent = 'blue'

export const INSTANCE_ACCENT_CLASSES: Record<InstanceAccent, InstanceAccentClasses> = {
  blue: {
    headerBorder: 'border-t-blue-500',
    badge: 'border-blue-500/40 bg-blue-500/10 text-blue-700 dark:text-blue-300',
    dot: 'bg-blue-500',
    terminal: 'border-blue-500/40',
  },
  green: {
    headerBorder: 'border-t-green-500',
    badge: 'border-green-500/40 bg-green-500/10 text-green-700 dark:text-green-300',
    dot: 'bg-green-500',
    terminal: 'border-green-500/40',
  },
  purple: {
    headerBorder: 'border-t-purple-500',
    badge: 'border-purple-500/40 bg-purple-500/10 text-purple-700 dark:text-purple-300',
    dot: 'bg-purple-500',
    terminal: 'border-purple-500/40',
  },
  orange: {
    headerBorder: 'border-t-orange-500',
    badge: 'border-orange-500/40 bg-orange-500/10 text-orange-700 dark:text-orange-300',
    dot: 'bg-orange-500',
    terminal: 'border-orange-500/40',
  },
  red: {
    headerBorder: 'border-t-red-500',
    badge: 'border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300',
    dot: 'bg-red-500',
    terminal: 'border-red-500/40',
  },
  pink: {
    headerBorder: 'border-t-pink-500',
    badge: 'border-pink-500/40 bg-pink-500/10 text-pink-700 dark:text-pink-300',
    dot: 'bg-pink-500',
    terminal: 'border-pink-500/40',
  },
  cyan: {
    headerBorder: 'border-t-cyan-500',
    badge: 'border-cyan-500/40 bg-cyan-500/10 text-cyan-700 dark:text-cyan-300',
    dot: 'bg-cyan-500',
    terminal: 'border-cyan-500/40',
  },
  slate: {
    headerBorder: 'border-t-slate-500',
    badge: 'border-slate-500/40 bg-slate-500/10 text-slate-700 dark:text-slate-300',
    dot: 'bg-slate-500',
    terminal: 'border-slate-500/40',
  },
}

export function getInstanceAccentClasses(accent?: string | null): InstanceAccentClasses {
  if (!accent || !(accent in INSTANCE_ACCENT_CLASSES)) {
    return INSTANCE_ACCENT_CLASSES[DEFAULT_INSTANCE_ACCENT]
  }
  return INSTANCE_ACCENT_CLASSES[accent as InstanceAccent]
}
```

---

## Frontend document title hook

File: `frontend/src/hooks/useInstanceDocumentTitle.ts`

```ts
import { useEffect } from 'react'

import type { InstanceIdentity } from '@/types/status'

const BASE_TITLE = 'Claude Deck'

export function useInstanceDocumentTitle(instance?: InstanceIdentity | null) {
  useEffect(() => {
    document.title = instance?.name ? `${instance.name} · ${BASE_TITLE}` : BASE_TITLE
  }, [instance?.name])
}
```

---

## Header chip snippet

File: `frontend/src/components/layout/Header.tsx`

```tsx
const instance = status?.instance ?? null
const accentClasses = getInstanceAccentClasses(instance?.accent)
useInstanceDocumentTitle(instance)

const instanceTitle = instance
  ? [
      `Claude Deck instance: ${instance.name}`,
      `Hostname: ${instance.hostname}`,
      `Opened from: ${window.location.host}`,
    ].join('\n')
  : 'Claude Deck instance loading'
```

```tsx
<header className={cn('border-b border-t-4 bg-background', accentClasses.headerBorder)}>
```

```tsx
{instance && (
  <Badge
    variant="outline"
    className={cn('gap-1 text-xs max-w-[12rem] truncate', accentClasses.badge)}
    title={instanceTitle}
  >
    <Server className="h-3 w-3 shrink-0" />
    <span className={cn('h-2 w-2 rounded-full shrink-0', accentClasses.dot)} />
    <span className="truncate">{instance.name}</span>
  </Badge>
)}
```

---

## Agent Bridge session card snippet

File: `frontend/src/features/cc-bridge/SessionCard.tsx`

```tsx
<p
  className="text-xs text-muted-foreground mt-0.5 truncate"
  title={instance ? `${instance.name} · ${session.tmux_target}` : session.tmux_target}
>
  {instance ? `${instance.name} · ` : ''}tmux: {session.tmux_target}
</p>
```

---

## Terminal footer snippet

File: `frontend/src/features/cc-bridge/TerminalView.tsx`

```tsx
<span
  className="text-xs text-muted-foreground truncate max-w-[18rem]"
  title={instance ? `${readOnly ? 'Read-only' : 'Interactive'} on ${instance.name} (${instance.hostname}) · ${target}` : target ?? undefined}
>
  {instance ? `${readOnly ? 'Read-only' : 'Interactive'} on ${instance.name}` : readOnly ? 'Read-only' : 'Interactive'}
</span>
```

---

## Kill dialog copy snippet

File: `frontend/src/features/cc-bridge/KillSessionDialog.tsx`

```tsx
<AlertDialogTitle>
  Kill {session?.session_name ?? 'session'}{instance ? ` on ${instance.name}` : ''}?
</AlertDialogTitle>

<AlertDialogDescription>
  This will terminate tmux target {session?.tmux_target}
  {instance ? ` on hostname ${instance.hostname}` : ''}.
</AlertDialogDescription>
```
