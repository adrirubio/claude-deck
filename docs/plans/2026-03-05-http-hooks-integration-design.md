# HTTP Hooks Integration for Claude Deck

## Context

Claude Code recently added HTTP Hooks (`type: "http"`) — a new hook type that sends POST requests to URLs when lifecycle events fire. Claude Deck currently supports 3 hook types (command, prompt, agent) but has no HTTP hook support. This plan integrates HTTP hooks into Claude Deck at two levels: (1) full UI support for creating/editing HTTP hooks, and (2) a built-in webhook receiver so Claude Deck itself can monitor Claude Code activity in real-time via an Activity Dashboard.

Additionally, Claude Code has added 5 new event types not yet in Claude Deck, and there's a validation bug to fix.

## Design: Full HTTP Hooks Integration

### Part 1: HTTP Hook Type Support (Schema + UI)

#### 1.1 Backend Schema Changes

**File: `backend/app/models/schemas.py`**

Add to `Hook`, `HookCreate`, `HookUpdate` models:
- `url: Optional[str]` — HTTP endpoint URL
- `headers: Optional[Dict[str, str]]` — HTTP headers with env var interpolation
- `allowedEnvVars: Optional[List[str]]` — Whitelist for env var expansion in headers

Add to `VALID_HOOK_EVENTS` (line ~549):
- `TeammateIdle`, `TaskCompleted`, `InstructionsLoaded`, `ConfigChange`, `WorktreeCreate`, `WorktreeRemove`

#### 1.2 Backend API Fix + HTTP Validation

**File: `backend/app/api/v1/hooks.py`**

- **Bug fix (line 66)**: Type validation currently only allows `"command"` or `"prompt"` — add `"agent"` and `"http"`
- Add validation for HTTP hooks: require `url`, reject `command`/`prompt` fields, validate URL format
- Ensure `headers` is a valid dict and `allowedEnvVars` is a list of strings

#### 1.3 Backend Service Changes

**File: `backend/app/services/hook_service.py`**

- `_parse_hook_from_data`: Read `url`, `headers`, `allowedEnvVars` fields from settings JSON
- `add_hook` / `update_hook`: Write these fields when type is "http"
- Handle the `async` field correctly (currently only for command hooks; HTTP hooks don't support it)

#### 1.4 Frontend Type Updates

**File: `frontend/src/types/hooks.ts`**

- Add `"http"` to the type union
- Add `url?: string`, `headers?: Record<string, string>`, `allowedEnvVars?: string[]` to Hook interfaces
- Add 5 new events to `HOOK_EVENTS` array with labels, descriptions, icons
- Add HTTP hook templates to `HOOK_TEMPLATES` (e.g., "Slack Webhook Notification", "Custom API Endpoint", "Claude Deck Activity Logger")
- Add `HTTP_HEADER_EXAMPLES` constant with common patterns (Authorization Bearer, Content-Type, custom headers)

#### 1.5 Frontend Component Changes

**HookWizard.tsx** (Step 3 — type selection):
- Add fourth type button: HTTP with `Globe` icon
- HTTP-specific form fields:
  - URL input with validation
  - Key-value editor for headers (reusable component)
  - Tag-style input for allowedEnvVars
- Template selection includes HTTP templates

**HookEditor.tsx**:
- Add HTTP type toggle button
- Conditionally render: URL input, headers key-value editor, allowedEnvVars when type="http"
- Hide command/prompt/model fields when type="http"

**HookCard.tsx**:
- Add `Globe` icon for HTTP type
- Display URL (truncated) instead of command/prompt preview
- Badge showing header count if > 0

**HookDetailDialog.tsx**:
- HTTP section showing: full URL, headers table (values partially masked), allowedEnvVars list

#### 1.6 New Shared Component: KeyValueEditor

**File: `frontend/src/components/shared/KeyValueEditor.tsx`**

Reusable key-value pair editor for HTTP headers:
- Add/remove rows
- Key input + value input per row
- Env var hint (show `$VAR_NAME` syntax help)
- Used by HookWizard and HookEditor

---

### Part 2: Claude Deck Webhook Receiver + Activity Dashboard

#### 2.1 Database Model

**File: `backend/app/models/database.py`**

New table `hook_events`:
```
id: Integer, primary key, autoincrement
event_type: String, not null (e.g., "PreToolUse", "PostToolUse")
session_id: String, nullable
tool_name: String, nullable
matcher: String, nullable
payload: JSON (full hook input payload)
received_at: DateTime, default=now
```

#### 2.2 Webhook Receiver API

**New file: `backend/app/api/v1/webhook_receiver.py`**

Endpoints:
- `POST /api/v1/webhook-receiver` — Receives hook payloads from Claude Code. Stores in DB. Returns 200 with empty JSON (no decision, pure logging)
- `GET /api/v1/webhook-receiver/events` — Query stored events with filters (event_type, session_id, time range, limit/offset)
- `GET /api/v1/webhook-receiver/stats` — Aggregated stats: events by type, events per hour/day, most common tools
- `DELETE /api/v1/webhook-receiver/events` — Clear events older than N days (with query param)

Register in `backend/app/api/v1/router.py`.

#### 2.3 Webhook Receiver Service

**New file: `backend/app/services/webhook_receiver_service.py`**

- `store_event(payload: dict)` — Parse and store incoming hook event
- `get_events(filters)` — Query with pagination and filtering
- `get_stats(time_range)` — Aggregate statistics
- `cleanup_events(older_than_days)` — Delete old events

#### 2.4 Frontend: Activity Tab

**New file: `frontend/src/features/hooks/HookActivityTab.tsx`**

Added as a tab within HooksPage.tsx (alongside event-type tabs):
- **Stats row**: Cards showing "Events Today", "Events This Week", "Most Active Event", "Unique Sessions"
- **Events timeline**: Table/list of recent events with columns: Time, Event Type, Tool, Session ID, expandable payload
- **Filters**: Event type dropdown, time range picker, session ID search
- **Auto-refresh**: Toggle for polling every 5 seconds
- **Clear button**: Delete old events

#### 2.5 Frontend: Connect to Deck Dialog

**New file: `frontend/src/features/hooks/ConnectToDeckDialog.tsx`**

Accessible from a "Connect to Deck" button on the Hooks page header:
- Checkbox list of all event types to monitor
- Scope selector (user/project)
- Shows the generated webhook URL (e.g., `http://localhost:8000/api/v1/webhook-receiver`)
- "Connect" button creates HTTP hooks for all selected events via the existing hooks API
- Success confirmation with link to Activity tab

#### 2.6 Frontend API Hook

**File: `frontend/src/features/hooks/api.ts`** (or new file)

- `fetchHookEvents(filters)` — GET /api/v1/webhook-receiver/events
- `fetchHookStats(timeRange)` — GET /api/v1/webhook-receiver/stats
- `clearHookEvents(olderThanDays)` — DELETE /api/v1/webhook-receiver/events

---

## Implementation Phases

### Phase 1: Schema & Types (backend + frontend)
- Add HTTP fields to Pydantic schemas and TypeScript types
- Add 5 new event types to both backend and frontend
- Fix type validation bug in hooks API route

### Phase 2: Backend Service Updates
- Hook service reads/writes HTTP hook fields (url, headers, allowedEnvVars)
- API route validation for HTTP hooks

### Phase 3: Frontend HTTP Hook UI
- KeyValueEditor shared component
- HookWizard Step 3 HTTP type + form
- HookEditor HTTP fields
- HookCard and HookDetailDialog HTTP display
- HTTP hook templates

### Phase 4: Webhook Receiver Backend
- HookEvent database model
- Webhook receiver API endpoints
- Webhook receiver service

### Phase 5: Activity Dashboard + Connect to Deck
- HookActivityTab component with stats, timeline, filters
- Integrate as tab in HooksPage
- ConnectToDeckDialog for one-click setup
- API hooks for webhook receiver endpoints

---

## Key Files to Modify

| File | Changes |
|------|---------|
| `backend/app/models/schemas.py` | Add url, headers, allowedEnvVars to Hook models; add 5 new events |
| `backend/app/models/database.py` | Add HookEvent ORM model |
| `backend/app/api/v1/hooks.py` | Fix type validation bug; add HTTP validation |
| `backend/app/api/v1/router.py` | Register webhook_receiver routes |
| `backend/app/services/hook_service.py` | Read/write HTTP hook fields |
| `frontend/src/types/hooks.ts` | Add "http" type, HTTP fields, new events, templates |
| `frontend/src/features/hooks/HooksPage.tsx` | Add Activity tab, Connect to Deck button |
| `frontend/src/features/hooks/HookWizard.tsx` | HTTP type selection + form |
| `frontend/src/features/hooks/HookEditor.tsx` | HTTP type fields |
| `frontend/src/features/hooks/HookCard.tsx` | HTTP type display |
| `frontend/src/features/hooks/HookDetailDialog.tsx` | HTTP detail section |

## New Files to Create

| File | Purpose |
|------|---------|
| `frontend/src/components/shared/KeyValueEditor.tsx` | Reusable key-value pair editor |
| `backend/app/api/v1/webhook_receiver.py` | Webhook receiver API routes |
| `backend/app/services/webhook_receiver_service.py` | Webhook receiver business logic |
| `frontend/src/features/hooks/HookActivityTab.tsx` | Activity dashboard tab |
| `frontend/src/features/hooks/ConnectToDeckDialog.tsx` | One-click setup dialog |

## Existing Patterns to Reuse

- `CLICKABLE_CARD` constant from `@/lib/constants` for any new card components
- `MODAL_SIZES` from `@/lib/constants` for dialog sizing
- `MarkdownRenderer` / `MarkdownPreviewToggle` from `@/components/shared/` for any markdown content
- Recharts (already a dependency) for activity charts
- Badge, Card, Dialog, Tabs from shadcn/ui (already installed)
- `useApi` hook pattern from `frontend/src/hooks/` for new API calls

## Verification

1. **Unit test**: Run `cd backend && pytest tests/` after schema and service changes
2. **Manual test — HTTP hook CRUD**: Create, edit, view, delete an HTTP hook via the UI. Verify settings.json contains correct `type: "http"`, `url`, `headers`, `allowedEnvVars`
3. **Manual test — webhook receiver**: Use curl to POST a sample hook payload to `/api/v1/webhook-receiver` and verify it appears in the Activity tab
4. **Manual test — Connect to Deck**: Use the dialog to create monitoring hooks, then verify they appear in settings.json and the Activity tab receives events
5. **Manual test — existing hooks**: Verify command, prompt, and agent hooks still work correctly after changes
6. **Lint**: Run `cd frontend && npm run lint` to ensure no TypeScript errors
