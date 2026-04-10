# Settings Gap Update — Implementation Plan

## Context

Claude-deck's settings editor (last updated 2026-03-20) is missing settings that Claude Code has added since: Auto Mode, Plugins/Marketplaces, Sandbox filesystem controls, and 14 new hook events. The SettingsEditor.tsx is also 1,090 lines (exceeds 800-line max). This plan closes the gaps and fixes the file size.

**Design spec:** `docs/superpowers/specs/2026-04-10-settings-gap-update-design.md`

---

## Phase 0: Split SettingsEditor (Pure Refactor)

Extract into `frontend/src/features/config/settings/` module:

1. Create `settings/field-components.tsx` — move SwitchSetting, NumberSetting, SelectSetting, TextSetting, AttributionField, ListEditor, KeyValueEditor (~335 lines)
2. Create `settings/constants.ts` — move MODEL_OPTIONS, PERMISSION_MODE_OPTIONS, UPDATE_CHANNEL_OPTIONS, LOGIN_METHOD_OPTIONS, EFFORT_LEVEL_OPTIONS, TEAMMATE_MODE_OPTIONS
3. Create `settings/cards/*.tsx` — extract each card (Authentication, General, Memory, Sandbox, Permissions, McpServers, Attribution, Ui, EnvVars, HooksSecurity, Advanced) into its own file
4. Create `settings/SettingsEditor.tsx` — orchestrator with state management, scope selector, save button, renders card components via standard `SettingsCardProps`
5. Create `settings/index.ts` — re-export SettingsEditor
6. Update `ConfigViewerPage.tsx` import path
7. Delete old `SettingsEditor.tsx`
8. Verify: `npm run lint && npm run build`, manual test all scopes

**Critical files:**
- `frontend/src/features/config/SettingsEditor.tsx` (source, 1090 lines)
- `frontend/src/features/config/ConfigViewerPage.tsx` (import update)

---

## Phase 1: Auto Mode Card (~80 lines)

1. Add `cards/AutoModeCard.tsx` with scope guard (`scope !== 'project'`):
   - `autoMode.environment` (ListEditor)
   - `autoMode.allow` (ListEditor)
   - `autoMode.soft_deny` (ListEditor)
   - `permissions.disableAutoMode` (SwitchSetting)
2. Add `{ value: 'auto', label: 'Auto' }` to PERMISSION_MODE_OPTIONS in constants.ts
3. Import and render AutoModeCard in SettingsEditor after PermissionsCard
4. Verify: lint, build, manual test

---

## Phase 2: Plugin Management Card (~120 lines)

1. Add `ObjectArrayEditor` component to `field-components.tsx` (~50 lines) for `{name, url}` pairs
2. Add `cards/PluginManagementCard.tsx`:
   - `enabledPlugins` (ListEditor)
   - `extraKnownMarketplaces` (ObjectArrayEditor)
   - Managed-only: `blockedMarketplaces`, `pluginTrustMessage`, `strictKnownMarketplaces`
3. Import and render in SettingsEditor after McpServersCard
4. Verify: lint, build, manual test

---

## Phase 3: Sandbox Filesystem Rules (~40 lines)

1. Add to existing `cards/SandboxCard.tsx`:
   - `sandbox.filesystem.allowRead` (ListEditor, gitignore patterns)
   - `sandbox.filesystem.denyRead` (ListEditor)
   - Managed-only: `sandbox.filesystem.allowManagedReadPathsOnly`, `sandbox.network.allowManagedDomainsOnly`
2. Verify: lint, build, manual test

---

## Phase 4: Hook Event Editor (~550 lines across 2 files)

1. Extend `frontend/src/types/hooks.ts`:
   - Add 14 new events to HookEvent union
   - Add metadata entries to HOOK_EVENTS array
   - Add `if` and `shell` fields to Hook interface
2. Add hook event constants to `settings/constants.ts` (HOOK_EVENT_GROUPS, HANDLER_TYPE_OPTIONS, SHELL_OPTIONS)
3. Add `cards/HookEntryForm.tsx` (~350 lines) — dialog form with:
   - Event selector (grouped by category)
   - Handler type selector (command/http/prompt/agent)
   - Common fields (matcher, if, timeout, statusMessage, once)
   - Conditional fields per handler type
4. Add `cards/HookEventEditorCard.tsx` (~200 lines) — card showing:
   - Grouped event list with handler counts
   - Collapsible per-event sections
   - Add/Edit/Delete actions opening HookEntryForm
5. Import and render in SettingsEditor
6. Verify: lint, build, full hook editor workflow test

---

## Verification (after all phases)

1. `cd frontend && npm run lint` — no warnings
2. `cd frontend && npm run build` — clean build
3. Start dev servers, navigate to Settings Editor
4. Test each scope (user, project, local, managed)
5. Test save round-trip for new settings
6. Test hook editor: add hook → configure → save → verify in raw JSON
7. Cross-check against official docs — all user-facing settings editable
