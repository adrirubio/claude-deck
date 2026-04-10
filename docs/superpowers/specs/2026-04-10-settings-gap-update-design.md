# Settings Gap Update — Design Spec

**Date:** 2026-04-10
**Status:** Approved for implementation
**Context:** Claude-deck's settings editor was last updated on 2026-03-20 (commit 565de27). Since then, Claude Code has added Auto Mode, Plugins/Marketplaces, expanded Sandbox filesystem controls, and 14 new hook events. This spec closes those gaps.

---

## Problem

The SettingsEditor currently covers ~35 settings across 10 cards. The official Claude Code settings docs at `code.claude.com/docs/en/settings` now document settings that are not surfaced:

1. **Auto Mode** — A new permission mode with its own sub-configuration (`autoMode.environment`, `.allow`, `.soft_deny`)
2. **Plugin Management** — `enabledPlugins`, `extraKnownMarketplaces`, managed plugin controls
3. **Sandbox Filesystem** — `sandbox.filesystem.allowRead`/`denyRead` gitignore-pattern controls
4. **Hook Events** — 14 new hook events (26 total), plus the `if` permission-rule filter field and `shell` option

Additionally, `SettingsEditor.tsx` is 1,090 lines — exceeding the project's 800-line max.

---

## Solution

### Phase 0: Split SettingsEditor (Refactor)

Extract the monolithic `SettingsEditor.tsx` into a module:

```
frontend/src/features/config/settings/
├── index.ts                      # re-export SettingsEditor
├── SettingsEditor.tsx            # orchestrator (~250 lines)
├── constants.ts                  # all option arrays
├── field-components.tsx          # SwitchSetting, ListEditor, KeyValueEditor, etc.
└── cards/
    ├── AuthenticationCard.tsx    # existing (managed-only)
    ├── GeneralCard.tsx          # existing
    ├── MemoryCard.tsx           # existing
    ├── SandboxCard.tsx          # existing + Phase 3 additions
    ├── PermissionsCard.tsx      # existing
    ├── McpServersCard.tsx       # existing
    ├── AttributionCard.tsx      # existing
    ├── UiCard.tsx               # existing
    ├── EnvVarsCard.tsx          # existing
    ├── HooksSecurityCard.tsx    # existing
    ├── AdvancedCard.tsx         # existing
    ├── AutoModeCard.tsx         # NEW (Phase 1)
    ├── PluginManagementCard.tsx # NEW (Phase 2)
    └── HookEventEditorCard.tsx  # NEW (Phase 4)
```

**Card component interface:**

```typescript
interface SettingsCardProps {
  getSetting: <T extends ConfigValue>(path: string, defaultValue: T) => T
  getSettingRaw: (path: string) => ConfigValue | undefined
  updateSetting: (path: string, value: ConfigValue) => void
  scope: SettingsScope
}
```

The parent `SettingsEditor.tsx` owns state and passes these props to all cards.

**Import migration:** `settings/index.ts` re-exports `SettingsEditor` so existing imports only need a path update from `'./SettingsEditor'` to `'./settings'`.

---

### Phase 1: Auto Mode Card

**File:** `cards/AutoModeCard.tsx` (~80 lines)

**Scope restriction:** Renders only when `scope !== 'project'` (auto mode config lives in user/local/managed only).

**Settings:**

| Setting | Component | Placeholder/Description |
|---|---|---|
| `autoMode.environment` | ListEditor | "e.g., This repo is deployed to a sandboxed staging environment" |
| `autoMode.allow` | ListEditor | "e.g., Bash(git *)" |
| `autoMode.soft_deny` | ListEditor | "e.g., Bash(rm -rf *)" |
| `permissions.disableAutoMode` | SwitchSetting | "Prevent auto mode from being used" |

**Constants update:** Add `{ value: 'auto', label: 'Auto' }` to `PERMISSION_MODE_OPTIONS` in `constants.ts`.

**Card position:** After the Permissions card, before MCP Servers.

---

### Phase 2: Plugin Management Card

**File:** `cards/PluginManagementCard.tsx` (~120 lines)

**Settings (all scopes):**

| Setting | Component | Placeholder/Description |
|---|---|---|
| `enabledPlugins` | ListEditor | "e.g., plugin-name@marketplace or /path/to/plugin" |
| `extraKnownMarketplaces` | ObjectArrayEditor (new) | Two inputs: Name + URL, renders as list of {name, url} pairs |

**Managed-only settings** (conditional on `scope === 'managed'`):

| Setting | Component |
|---|---|
| `blockedMarketplaces` | ListEditor |
| `pluginTrustMessage` | TextSetting |
| `strictKnownMarketplaces` | SwitchSetting |

**ObjectArrayEditor:** New sub-component (~50 lines) modeled after `KeyValueEditor`. Two text inputs (Name, URL) with an Add button. Each entry renders as a row with values and a remove button. Lives in `field-components.tsx`.

**Card position:** After MCP Servers card.

---

### Phase 3: Sandbox Filesystem Rules

**File:** Extends existing `cards/SandboxCard.tsx` (~40 additional lines)

Add a visual separator and new section:

| Setting | Component | Placeholder/Description |
|---|---|---|
| `sandbox.filesystem.allowRead` | ListEditor | "e.g., /tmp/**, *.log" — gitignore-style patterns |
| `sandbox.filesystem.denyRead` | ListEditor | "e.g., /etc/shadow, ~/.ssh/**" |

**Managed-only** (conditional on `scope === 'managed'`):

| Setting | Component |
|---|---|
| `sandbox.filesystem.allowManagedReadPathsOnly` | SwitchSetting |
| `sandbox.network.allowManagedDomainsOnly` | SwitchSetting |

---

### Phase 4: Hook Event Editor

**Distinction from existing `/hooks` feature:** The `/hooks` page manages hooks via a CRUD API with database persistence (hooks have `id` and `scope`). The Hook Event Editor in settings writes directly to the `hooks` key in `settings.json` — it's the same JSON structure Claude Code reads, but managed as part of the settings config rather than through a separate registry.

#### Files

**`cards/HookEventEditorCard.tsx`** (~200 lines):
- Card with title "Hook Events"
- Summary view: lists configured hook events grouped by category
- Categories: **Lifecycle** (SessionStart, SessionEnd, Stop, StopFailure, UserPromptSubmit, PreCompact, PostCompact, Notification), **Tool** (PreToolUse, PostToolUse, PostToolUseFailure, PermissionRequest, PermissionDenied), **Agent & Team** (SubagentStart, SubagentStop, TeammateIdle, TaskCreated, TaskCompleted), **Config & Infrastructure** (InstructionsLoaded, ConfigChange, CwdChanged, FileChanged, WorktreeCreate, WorktreeRemove, Elicitation, ElicitationResult)
- Each event shows handler count badge
- Collapsible per-event sections showing handler summaries
- Add/Edit/Delete actions per handler, opening `HookEntryForm`

**`cards/HookEntryForm.tsx`** (~350 lines):
- Dialog-based form for creating/editing a single hook handler
- Event selector (grouped by category via `<SelectGroup>`)
- Handler type selector: command | http | prompt | agent
- Common fields:

| Field | Component | Description |
|---|---|---|
| `matcher` | TextSetting | Regex or exact match filter |
| `if` | TextSetting | Permission rule filter (e.g., "Bash(git *)") |
| `timeout` | NumberSetting | Seconds |
| `statusMessage` | TextSetting | Custom spinner text |
| `once` | SwitchSetting | Fire only once per session |

- Conditional fields by handler type:

**command:**
| Field | Component |
|---|---|
| `command` | TextSetting (monospace) |
| `async` | SwitchSetting |
| `shell` | SelectSetting (bash / powershell) |

**http:**
| Field | Component |
|---|---|
| `url` | TextSetting |
| `headers` | KeyValueEditor |
| `allowedEnvVars` | ListEditor |

**prompt / agent:**
| Field | Component |
|---|---|
| `prompt` | Textarea or MarkdownPreviewToggle |
| `model` | SelectSetting (haiku / sonnet / opus / fast-model) |

**State management:** The hooks data is `Record<string, HookHandler[]>`. The card reads `getSetting('hooks', {})` and writes the entire hooks object back via `updateSetting('hooks', updatedHooksObj)`. Individual handler operations (add, edit, delete) produce a new immutable copy of the hooks object.

#### Type updates

**`frontend/src/types/hooks.ts`** — extend `HookEvent` union with 14 new events:

```typescript
| "StopFailure" | "PostCompact" | "PermissionDenied"
| "TeammateIdle" | "TaskCreated" | "TaskCompleted"
| "InstructionsLoaded" | "ConfigChange" | "CwdChanged"
| "FileChanged" | "WorktreeCreate" | "WorktreeRemove"
| "Elicitation" | "ElicitationResult"
```

Add corresponding entries to `HOOK_EVENTS` metadata array with labels, descriptions, and icons.

Add `if` and `shell` fields to the `Hook` interface:
```typescript
if?: string       // Permission rule filter
shell?: 'bash' | 'powershell'
```

---

## Files to Create/Modify

### New files
- `frontend/src/features/config/settings/index.ts`
- `frontend/src/features/config/settings/SettingsEditor.tsx`
- `frontend/src/features/config/settings/constants.ts`
- `frontend/src/features/config/settings/field-components.tsx`
- `frontend/src/features/config/settings/cards/AuthenticationCard.tsx`
- `frontend/src/features/config/settings/cards/GeneralCard.tsx`
- `frontend/src/features/config/settings/cards/MemoryCard.tsx`
- `frontend/src/features/config/settings/cards/SandboxCard.tsx`
- `frontend/src/features/config/settings/cards/PermissionsCard.tsx`
- `frontend/src/features/config/settings/cards/McpServersCard.tsx`
- `frontend/src/features/config/settings/cards/AttributionCard.tsx`
- `frontend/src/features/config/settings/cards/UiCard.tsx`
- `frontend/src/features/config/settings/cards/EnvVarsCard.tsx`
- `frontend/src/features/config/settings/cards/HooksSecurityCard.tsx`
- `frontend/src/features/config/settings/cards/AdvancedCard.tsx`
- `frontend/src/features/config/settings/cards/AutoModeCard.tsx`
- `frontend/src/features/config/settings/cards/PluginManagementCard.tsx`
- `frontend/src/features/config/settings/cards/HookEventEditorCard.tsx`
- `frontend/src/features/config/settings/cards/HookEntryForm.tsx`

### Modified files
- `frontend/src/types/hooks.ts` — extend HookEvent union, add `if`/`shell` fields
- `frontend/src/features/config/ConfigViewerPage.tsx` — update import path

### Deleted files
- `frontend/src/features/config/SettingsEditor.tsx` — replaced by `settings/SettingsEditor.tsx`

---

## Implementation Order

1. **Phase 0** — Split SettingsEditor (pure refactor, verify identical behavior)
2. **Phase 1** — Auto Mode Card + 'auto' permission mode option
3. **Phase 2** — Plugin Management Card + ObjectArrayEditor
4. **Phase 3** — Sandbox Filesystem rules (extends SandboxCard)
5. **Phase 4** — Hook Event Editor + type updates

Each phase is independently committable.

---

## Verification

After each phase:
1. Start dev servers (`./scripts/dev.sh`)
2. Navigate to Settings Editor
3. Verify each scope (user, project, local, managed) renders correctly
4. Test save round-trip: change a new setting → save → reload → value persists
5. Test scope guards: auto mode hidden in project scope, managed-only fields hidden otherwise
6. Run `cd frontend && npm run lint` — no new warnings
7. Run `cd frontend && npm run build` — builds cleanly

After all phases:
1. Test the full hook editor workflow: add a hook → select event → configure handler → save → verify in raw JSON viewer
2. Test plugin management: add a plugin → save → verify in settings file
3. Cross-check against official docs at `code.claude.com/docs/en/settings` — all documented user-facing settings should be editable
