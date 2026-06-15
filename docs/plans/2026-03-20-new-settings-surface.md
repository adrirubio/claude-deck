# New Claude Code Settings — Surface in Claude Deck

**Date:** 2026-03-20  
**Status:** Ready for implementation  
**Scope:** `frontend/src/features/config/SettingsEditor.tsx` + backend schema validation

---

## Analysis: What's Missing

Cross-referencing the official `code.claude.com/docs/en/settings.md` against the current `SettingsEditor.tsx`, the following settings from Anthropic's docs are not yet surfaced in the UI:

### Priority 1 — High value, user-facing (implement now)

| Setting | Type | Where to add |
|---|---|---|
| `autoMemory` | boolean | New **Memory** card |
| `autoMemoryDirectory` | string (path) | New **Memory** card |
| `effortLevel` | enum: low/medium/high | **General** card |
| `includeGitInstructions` | boolean | **Advanced** card |

### Priority 2 — Power users

| Setting | Type | Where to add |
|---|---|---|
| `availableModels` | string[] | **General** card (below model) |
| `apiKeyHelper` | string (script path) | **Advanced** card |
| `companyAnnouncements` | string[] | **Advanced** card |
| `enableAllProjectMcpServers` | boolean | New **MCP Servers** card |
| `enabledMcpjsonServers` | string[] | New **MCP Servers** card |
| `disabledMcpjsonServers` | string[] | New **MCP Servers** card |
| `fileSuggestion` | string (script path) | **UI** card |

### Priority 3 — Advanced/Enterprise

| Setting | Type | Where to add |
|---|---|---|
| `allowedHttpHookUrls` | string[] | New **Hooks Security** card (or within Advanced) |
| `httpHookAllowedEnvVars` | string[] | **Hooks Security** card |
| `forceLoginMethod` | enum: claudeai/console | New **Authentication** card |
| `forceLoginOrgUUID` | string (UUID) | **Authentication** card |
| `agent` | string | **Advanced** card |
| `modelOverrides` | Record<string,string> | **General** card |

### Priority 4 — Managed/Enterprise only (lower pri, skip for now)

`allowManagedHooksOnly`, `allowManagedPermissionRulesOnly`, `allowManagedMcpServersOnly`, `channelsEnabled`, `allowedMcpServers`, `deniedMcpServers`, `strictKnownMarketplaces`, `feedbackSurveyRate`

These only apply to `managed-settings.json` deployed by IT/DevOps. Surfacing them in the user-facing editor is low value. Skip for now.

---

## Implementation Plan

### Phase 1 — Memory card (highest priority — this is the new feature users are asking about)

Add a new **Memory** card between the General and Sandbox cards:

```tsx
<Card>
  <CardHeader>
    <CardTitle>Memory</CardTitle>
    <CardDescription>Auto memory lets Claude accumulate learnings between sessions</CardDescription>
  </CardHeader>
  <CardContent className="space-y-4">
    <SwitchSetting
      label="Auto Memory"
      description="Claude automatically takes notes on your project — build commands, preferences, architectural decisions — and loads them at the start of every session"
      checked={getSetting<boolean>('autoMemory', false)}
      onCheckedChange={(v) => updateSetting('autoMemory', v)}
    />
    <TextSetting
      id="autoMemoryDirectory"
      label="Memory Directory"
      description="Custom directory for auto memory storage. Accepts ~ paths. Only available in user/local settings (not project settings)."
      value={getSetting<string>('autoMemoryDirectory', '')}
      onChange={(v) => updateSetting('autoMemoryDirectory', v)}
      placeholder="~/.claude/memory"
    />
  </CardContent>
</Card>
```

### Phase 2 — General card additions

Add to existing General card:

1. **Effort Level** (select: low / medium / high) — after the Model field
   - `effortLevel`: "low" | "medium" | "high"
   - Description: "Persist the effort level across sessions. Supported on Opus 4.6 and Sonnet 4.6."

2. **Available Models** (ListEditor) — after Effort Level
   - `availableModels`: string[]
   - Description: "Restrict which models users can select via /model. Does not affect the Default option."

3. **Model Overrides** (KeyValueEditor) — after Available Models
   - `modelOverrides`: Record<string, string>
   - Description: "Map Anthropic model IDs to provider-specific IDs (e.g., Bedrock ARNs)."

### Phase 3 — Advanced card additions

Add to existing Advanced card:

1. **Include Git Instructions** (SwitchSetting)
   - `includeGitInstructions`: boolean (default: true)
   - Description: "Include built-in commit and PR workflow instructions in the system prompt. Set to false if using your own git workflow skills."

2. **API Key Helper** (TextSetting)
   - `apiKeyHelper`: string
   - Description: "Custom script (run via /bin/sh) to generate an auth value sent as X-Api-Key and Authorization: Bearer headers."
   - Placeholder: "/bin/generate_temp_api_key.sh"

3. **Company Announcements** (ListEditor)
   - `companyAnnouncements`: string[]
   - Description: "Messages displayed to users at startup, cycled through at random."

4. **Default Agent** (TextSetting)
   - `agent`: string
   - Description: "Run the main thread as a named subagent. Applies that subagent's system prompt, tool restrictions, and model."

### Phase 4 — New MCP Servers card

Add a new **MCP Servers (project.json)** card in the settings, after Permissions:

```
<Card>
  <CardHeader>
    <CardTitle>MCP Servers (.mcp.json)</CardTitle>
    <CardDescription>Control auto-approval of MCP servers defined in project .mcp.json files</CardDescription>
  </CardHeader>
  <CardContent className="space-y-4">
    <SwitchSetting
      label="Enable All Project MCP Servers"
      description="Automatically approve all MCP servers defined in project .mcp.json files"
      ...
    />
    <ListEditor label="Enabled MCP Servers" description="Specific servers to approve" ... />
    <ListEditor label="Disabled MCP Servers" description="Specific servers to reject" ... />
  </CardContent>
</Card>
```

### Phase 5 — UI card addition + Hooks Security card

**UI card:** Add `fileSuggestion` command field (TextSetting):
- Description: "Custom script for @ file autocomplete suggestions."

**New Hooks Security card** (after Hooks, before Advanced):
```
<Card>
  <CardHeader>
    <CardTitle>Hooks Security</CardTitle>
    <CardDescription>Restrict HTTP hooks to approved destinations</CardDescription>
  </CardHeader>
  <CardContent className="space-y-4">
    <ListEditor label="Allowed HTTP Hook URLs" ... placeholder="https://hooks.example.com/*" />
    <ListEditor label="Allowed Hook Environment Variables" ... placeholder="MY_TOKEN" />
  </CardContent>
</Card>
```

### Phase 6 — New Authentication card (managed scope only)

Show only when scope === 'managed'. Add a new **Authentication** card at the top:

```
<Card>
  <CardHeader>
    <CardTitle>Authentication</CardTitle>
    <CardDescription>Restrict login method and organization (managed settings only)</CardDescription>
  </CardHeader>
  <CardContent className="space-y-4">
    <SelectSetting id="forceLoginMethod" ... options={[{value:'claudeai', ...}, {value:'console', ...}]} />
    <TextSetting id="forceLoginOrgUUID" ... placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" />
  </CardContent>
</Card>
```

---

## Files to Change

- `frontend/src/features/config/SettingsEditor.tsx` — all UI changes above

No backend changes needed — the backend's config service reads/writes raw JSON, so new keys will just flow through.

---

## Order of Work

1. Memory card (Phase 1) — highest value, done in isolation
2. General card additions (Phase 2)  
3. Advanced card additions (Phase 3)
4. MCP Servers card (Phase 4)
5. UI + Hooks Security additions (Phase 5)
6. Authentication card (Phase 6)

After all phases: run `/code-review`, `/simplify`, `/verify`, then commit.

---

## Commit Message

```
feat(config): surface new Claude Code settings in SettingsEditor

- Add Memory card: autoMemory toggle + autoMemoryDirectory path
- Add effortLevel, availableModels, modelOverrides to General
- Add includeGitInstructions, apiKeyHelper, companyAnnouncements, agent to Advanced
- Add MCP Servers card for enableAllProjectMcpServers, enabled/disabledMcpjsonServers
- Add fileSuggestion to UI card
- Add Hooks Security card: allowedHttpHookUrls, httpHookAllowedEnvVars
- Add Authentication card (managed scope only): forceLoginMethod, forceLoginOrgUUID
```
