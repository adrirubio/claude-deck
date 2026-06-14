# Agent Mail v2 Review For Plan Patching

**Reviewed plan:** `docs/plans/agent-mail/2026-06-12-agent-mail-v2-implementation-plan.md`
**Purpose:** Actionable review notes for another agent to patch the v2 implementation plan before coding starts.
**Review verdict:** Close to implementation-ready, but not suitable to execute literally until the blocking issues below are patched.

---

## Summary

The v2 plan is a strong improvement over the original. It has a clearer product shape, durable per-repo team members, structured context requests and handoffs, state-based delivery, and a practical non-chat UI.

The implementation sequence is also mostly usable: it is test-first, references current repo conventions, and decomposes backend, MCP, hooks, install, frontend, and docs in a reasonable order.

However, several details would either fail during implementation or ship behavior that does not match the stated product goals.

Patch the plan before assigning implementation.

---

## Blocking Issues

### 1. Hook install code omits required `scope`

**Severity:** Blocking implementation defect

The plan creates `HookCreate(...)` in Task 8 without `scope`. In the current repo, `HookCreate.scope` is required.

Relevant v2 plan area:

- Task 8 install service
- `apply_claude_code_install`
- `HookCreate(...)` block around the hook install loop

Current repo facts:

- `backend/app/models/schemas.py` defines `HookCreate.scope: str`
- `backend/app/services/hook_service.py` branches on `hook.scope`

Required patch:

```python
HookCreate(
    event=event,
    matcher=POST_TOOL_USE_MATCHER if event == "PostToolUse" else None,
    type="command",
    command=hook_command(slug),
    scope="user",
)
```

Also patch `test_apply_adds_missing_hooks_and_mcp` to assert every added hook has `scope == "user"`.

Why this matters:

Without this, Task 8 fails at runtime when constructing `HookCreate`.

---

### 2. Handoffs never close when acked

**Severity:** Blocking behavior defect

The plan models `handoff` as a request kind with status `pending`, but `ack_message` only moves a root request to `acknowledged` when the acked message is an `answer` and the root sender is acknowledging that answer.

That means a recipient can ack a handoff, but the handoff root remains `pending` and keeps contributing to pending counts.

Relevant v2 plan areas:

- Task 4 messaging service
- `MAIL_REQUEST_KINDS = ["context_request", "handoff"]`
- `counts_for_member`
- `ack_message`
- MCP `deck_create_handoff`
- MCP `deck_ack_message`

Required patch:

Add behavior to `ack_message`:

- If the acked message is a root `handoff`
- And `message.recipient_member_id == member_id`
- And `message.request_status == "pending"`
- Then set `message.request_status = "acknowledged"`

Suggested service logic:

```python
if (
    message is not None
    and message.kind == "handoff"
    and message.thread_root_id is None
    and message.recipient_member_id == member_id
    and message.request_status == "pending"
):
    message.request_status = "acknowledged"
```

Required tests:

1. `test_handoff_ack_closes_request`
2. Confirm `counts_for_member` pending count drops after ack.
3. Confirm unrelated members cannot close the handoff by acking.

Why this matters:

The plan presents handoffs as structured requests. If acking a handoff does not close it, the core request lifecycle is inconsistent.

---

### 3. Codex one-click install is deferred despite existing Codex MCP mutation support

**Severity:** Product-goal mismatch

The v2 goal says local Claude Code and Codex CLI sessions should coordinate with one-click install. But Task 8 says Codex only gets copy-paste `config.toml` and `AGENTS.md` snippets because `codex_config_service` has no MCP mutation seam.

The repo already exposes Codex MCP mutation through provider endpoints:

- `POST /api/v1/providers/{provider_id}/mcp`
- Backed by Codex CLI `codex mcp add`
- Provider capabilities classify Codex MCP as write-capable.

Required decision:

Choose one and update the plan clearly:

1. **Preferred:** Include Codex one-click MCP install in MVP.
2. **Acceptable but weaker:** Keep Codex manual snippets, but revise the top-level goal and acceptance criteria so "one-click install" explicitly means Claude Code only in MVP.

Recommended patch if choosing one-click Codex MCP:

- Add Codex MCP install status to `AgentMailInstallStatus`.
- Add install endpoint:

```text
POST /api/v1/agent-mail/install/codex/apply
```

- Have install service call the existing Codex provider MCP mutation path or extract shared helper logic.
- Keep `AGENTS.md` as a snippet unless there is a safe existing writer.

Required tests:

- Codex MCP install builds the same command/sys.executable and shim path.
- Codex MCP install uses `CLAUDE_DECK_PROVIDER=codex-cli`.
- Codex hook status remains unsupported/not installed.

Why this matters:

The feature promise is cross-provider agent coordination. Manual Codex setup weakens that promise and conflicts with the earlier product goal.

---

### 4. Install has no preview, confirmation, or backup path

**Severity:** Safety/product risk

Task 8 directly mutates real user config through `HookService.add_hook` and `MCPService.add_server`. That matches current service mechanics, but it is risky for an install button that edits `~/.claude/settings.json` and `~/.claude.json`.

Relevant v2 plan areas:

- Task 8 install service
- Install tab "Install" button
- Docs security section

Required decision:

Either:

1. Add preview/confirmation/backup to MVP, or
2. Explicitly accept current app semantics and document that Agent Mail install follows existing Hooks/MCP writer behavior without backup.

Recommended patch:

- Add `GET /agent-mail/install/status`
- Add `POST /agent-mail/install/preview`
- Add `POST /agent-mail/install/claude-code/apply` with `{ confirmed: true }`
- Return planned files and operations:

```json
{
  "changes": [
    {"file": "~/.claude/settings.json", "operation": "add_hooks"},
    {"file": "~/.claude.json", "operation": "add_mcp_server"}
  ],
  "warnings": []
}
```

If backup helpers exist, use them. If not, at least write a timestamped `.bak` before mutation or document why not.

Required tests:

- Preview does not mutate files/services.
- Apply requires confirmation.
- Apply only adds missing Agent Mail hooks/server.
- Uninstall only removes hooks whose command contains `/api/v1/agent-mail/hooks/`.

Why this matters:

Claude Deck edits real local agent configuration. Install UX should be trustworthy.

---

### 5. Hook-output delivery assumption is verified too late

**Severity:** Architectural risk

The plan depends on `curl` command hook stdout being parsed by Claude Code as JSON containing `hookSpecificOutput.additionalContext`.

The plan lists this as a known risk at the end, but by then most of the feature has already been built.

Required patch:

Move this to an early spike before full backend/UI implementation.

Add a new early task after Task 1 or before Task 7:

```text
Task X: Verify curl command-hook additionalContext delivery
```

Minimum acceptance:

1. Install a temporary command hook manually or through a small test snippet.
2. The command emits JSON on stdout:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "Agent Mail smoke test context"
  }
}
```

3. Start Claude Code and confirm the context is visible to the model.
4. If it fails, switch the plan to a tiny wrapper script before continuing.

Why this matters:

This is the core delivery mechanism. If it is wrong, the rest of the plan still builds but the most important behavior does not work.

---

## Non-Blocking But Important Issues

### 6. Global visibility may become noisy

The plan explicitly removes scopes/workspaces in MVP and makes all members mutually visible. This is acceptable for a first release if documented, but the UI should include filters from the start.

Recommended patch:

- Team tab should support filters: all, connected, observed, offline, repo name search.
- Requests tab should support filters: pending, answered, acknowledged, stale.
- Docs should say machine-global visibility is the MVP behavior.

### 7. One member per repo is clear but limiting

The plan keys durable members by `repo_id`, which means two agents in the same repo share a single member identity. The plan calls this out as MVP behavior.

Recommended patch:

- Make this limitation visible in docs and UI copy.
- In smoke tests, include two sessions in the same repo and verify they attach to one member.

### 8. MCP and hook sessions may duplicate the same real agent in the UI

The plan already calls this cosmetic. That is acceptable, but the Team tab should render sessions compactly under one member and avoid making duplicates look like separate teammates.

Recommended patch:

- Session list shows `source` badges: hook, mcp, observed.
- Member status derives from best session status.

### 9. Tests use raw `len(result.scalars().all())`

This is fine for MVP scale, but counting receipts/messages in service code can be more efficient with SQL count queries.

Recommended patch:

- Optional. Do not block implementation.

### 10. Dependency addition should update both dependency manifests if needed

The plan adds `mcp>=1.2.0` to `backend/requirements.txt`. The repo also has `backend/pyproject.toml` and `backend/uv.lock`.

Recommended patch:

- Add `mcp` to `backend/pyproject.toml` too, or explicitly state that `requirements.txt` is the only install source for this project.
- If the project expects lockfile maintenance, run the relevant lock command.

---

## Suggested Patch Checklist

Ask the patching agent to update the v2 plan as follows:

1. Add `scope="user"` to every `HookCreate` in Task 8.
2. Add tests asserting hook scope.
3. Add handoff ack lifecycle logic and tests.
4. Decide Codex one-click MCP install vs explicit deferral.
5. If including Codex one-click, add install service/API/UI/tests for it.
6. Add install preview/confirmation and backup or explicitly document why MVP follows existing direct-write behavior.
7. Move curl hook-output verification into an early spike task.
8. Add UI filters for team/request noise control.
9. Document one-member-per-repo and machine-global visibility as MVP limitations.
10. Clarify dependency update procedure for `mcp`.

---

## Implementation Readiness After Patching

After the blocking issues are patched, the plan should be suitable for implementation.

The strongest parts to preserve:

- Durable member vs ephemeral session split.
- State-based delivery instead of event delivery.
- Context request and handoff as first-class message kinds.
- MCP tool responses piggybacking unread/pending counts.
- Non-chat UI centered on Team, Requests, and Install.

Do not revert to the original Agent Mail v1 architecture unless the hook delivery spike fails and the project chooses to simplify delivery.
