# MCP Page Enhancements Design

**Date**: 2026-02-07
**Status**: Approved

## Goal

Bring the MCP Servers page to feature parity with Claude Code's `/mcp` capabilities. Three priority areas: per-server approval overrides, server health/status improvements, and tools/resources/prompts browsing via a detail dialog.

## Architecture

### Approach: Server Detail Dialog + Enhanced Cards

Click a server card to open a full `MCPServerDetailDialog` with 4 tabs. Cards become cleaner (no inline tool expansion). Per-server approval lives in the dialog. "Test All" button added to page header.

## Phase 1: Backend — Resources & Prompts Support

### New Pydantic Schemas (`backend/app/models/schemas.py`)

```python
class MCPResource(BaseModel):
    uri: str
    name: str
    description: Optional[str] = None
    mimeType: Optional[str] = None

class MCPPromptArgument(BaseModel):
    name: str
    description: Optional[str] = None
    required: Optional[bool] = None

class MCPPrompt(BaseModel):
    name: str
    description: Optional[str] = None
    arguments: Optional[List[MCPPromptArgument]] = None
```

### Database Model Extension (`backend/app/models/database.py`)

Add to `MCPServerCache`:
- `resources = Column(JSON, nullable=True)` — cached resources list
- `prompts = Column(JSON, nullable=True)` — cached prompts list
- `resource_count = Column(Integer, default=0)`
- `prompt_count = Column(Integer, default=0)`

### Service Extension (`backend/app/services/mcp_service.py`)

In `test_connection` for stdio servers, after the existing `tools/list` call:

1. Send `resources/list` (JSON-RPC id: 3) — best-effort, wrapped in try/except
2. Send `prompts/list` (JSON-RPC id: 4) — best-effort, wrapped in try/except
3. Parse responses into `MCPResource[]` and `MCPPrompt[]`
4. Include in response and cache

Extend `MCPTestConnectionResponse` schema:
- `resources: Optional[List[MCPResource]] = None`
- `prompts: Optional[List[MCPPrompt]] = None`

Extend `MCPServerResponse` schema:
- `resources: Optional[List[MCPResource]] = None`
- `prompts: Optional[List[MCPPrompt]] = None`
- `resource_count: Optional[int] = None`
- `prompt_count: Optional[int] = None`

Extend cache read/write methods to include resources and prompts.

HTTP/SSE servers: No change (just basic reachability checks).

**Note**: Delete `backend/claude_registry.db` after schema changes (no migration system).

## Phase 2: Frontend Types (`frontend/src/types/mcp.ts`)

```typescript
export interface MCPResource {
  uri: string;
  name: string;
  description?: string;
  mimeType?: string;
}

export interface MCPPromptArgument {
  name: string;
  description?: string;
  required?: boolean;
}

export interface MCPPrompt {
  name: string;
  description?: string;
  arguments?: MCPPromptArgument[];
}
```

Extend `MCPServer`:
- `resources?: MCPResource[] | null`
- `prompts?: MCPPrompt[] | null`
- `resource_count?: number`
- `prompt_count?: number`

Extend `MCPTestConnectionResponse`:
- `resources?: MCPResource[]`
- `prompts?: MCPPrompt[]`

## Phase 3: MCPServerDetailDialog (New Component)

**File**: `frontend/src/features/mcp/MCPServerDetailDialog.tsx`

**Props**:
```typescript
interface MCPServerDetailDialogProps {
  server: MCPServer | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onEdit: (server: MCPServer) => void;
  onDelete: (name: string, scope: string) => void;
  onTestComplete: () => void;
  approvalSettings: MCPServerApprovalSettings | null;
  onApprovalChange: (serverName: string, mode: string | null) => void;
  readOnly?: boolean;
}
```

**Size**: `MODAL_SIZES.MD` with `flex flex-col`

**Header**: Server name + type label + scope badge + connection status badge

### Tab 1: Overview (default)
- **Configuration section**: type, command/URL, args, environment variables (masked), HTTP headers
- **Connection info**: last tested timestamp, MCP server name/version
- **Per-server approval**: dropdown with "Use default (currently: X)", "Always allow", "Always deny", "Ask every time". Changing calls `onApprovalChange`.
- **Test Connection button**: triggers test, shows inline result alert

### Tab 2: Tools
- Tab trigger shows count badge: "Tools (N)"
- Search input (shown when >5 tools)
- List of tools: name (mono font), description (line-clamp-2)
- Click a tool to expand: full description, input schema with parameter table (name, type, required badge, description), collapsible raw JSON
- Empty state: "No tools discovered. Test connection to discover tools."

### Tab 3: Resources
- Tab trigger shows count badge: "Resources (N)"
- List: URI (mono), name, description, mimeType badge
- Empty state: "No resources exposed by this server." or "Test connection to discover resources."

### Tab 4: Prompts
- Tab trigger shows count badge: "Prompts (N)"
- List: name, description, arguments list with required badges
- Empty state: "No prompts exposed by this server." or "Test connection to discover prompts."

## Phase 4: Card & Page Updates

### MCPServerCard Changes
- Add `CLICKABLE_CARD`, `tabIndex={0}`, `onClick` → `onViewDetail`, keyboard handler
- Remove inline tool expansion (collapsible tool list, tool filter, tool detail modal)
- Keep: test result alert inline, action buttons with `stopPropagation`
- Add resource/prompt count badges next to tool count
- Replace emoji status (circles) with styled icon badges (`CheckCircle2`/`AlertCircle`/`Circle`)
- Show small badge if server has a non-default approval override

### MCPServerList Changes
- Accept and pass through `onViewDetail` prop

### MCPServersPage Changes
- Add state: `detailServer`, `showDetail`
- Add "Test All" button: iterates servers, calls test endpoint for each (sequential), refreshes after
- Wire `onViewDetail` through list to cards
- Add `MCPServerDetailDialog` with approval settings props
- Add handler for per-server approval changes: updates `server_overrides` array, calls PUT endpoint

## Files Summary

| Action | File |
|--------|------|
| Create | `frontend/src/features/mcp/MCPServerDetailDialog.tsx` |
| Modify | `backend/app/models/schemas.py` |
| Modify | `backend/app/models/database.py` |
| Modify | `backend/app/services/mcp_service.py` |
| Modify | `frontend/src/types/mcp.ts` |
| Modify | `frontend/src/features/mcp/MCPServerCard.tsx` |
| Modify | `frontend/src/features/mcp/MCPServerList.tsx` |
| Modify | `frontend/src/features/mcp/MCPServersPage.tsx` |
| Delete | `backend/claude_registry.db` (recreated on startup) |

## Implementation Order

1. Backend schemas (Pydantic + DB model)
2. Backend service (resources/prompts fetching + caching)
3. Frontend types
4. MCPServerDetailDialog
5. MCPServerCard simplification + CLICKABLE_CARD
6. MCPServerList prop threading
7. MCPServersPage wiring (detail dialog, Test All, per-server approvals)
8. Delete DB, verify with `tsc --noEmit` + `npm run lint` + manual test

## Key Pattern References

| Pattern | Reference |
|---------|-----------|
| CLICKABLE_CARD + keyboard a11y | `hooks/HookCard.tsx:62-71` |
| Detail dialog with tabs | `agents/AgentList.tsx:248-420` (inline dialog with sections) |
| Lazy fetch on dialog open | `skills/SkillDetailDialog.tsx:65-100` |
| Per-server settings | `MCPServerApprovalSettings.server_overrides` (already in type system) |
| Test connection flow | `MCPServerCard.tsx:112-145` |
| MODAL_SIZES | `lib/constants.ts:5-9` |
