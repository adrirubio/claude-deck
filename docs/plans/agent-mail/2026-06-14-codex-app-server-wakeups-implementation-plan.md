# Codex App-Server Wakeups For Agent Mail

**Issue:** [#185](https://github.com/adrirubio/claude-deck/issues/185)  
**Status:** Draft implementation plan for review  
**Depends on:** Agent Mail MVP merged via [#186](https://github.com/adrirubio/claude-deck/pull/186)  
**Date:** 2026-06-14

## Goal

Make Agent Mail reliable for non-tmux Codex sessions.

The MVP can store mail for any connected Codex member, and it can actively nudge Codex only when Agent Bridge observes the session through tmux. That leaves a major reliability gap: an idle Codex CLI session outside tmux can be `connected` but not wakeable. This plan adds a native Codex app-server wakeup path so Claude Deck can ask Codex to check Agent Mail without terminal key injection.

## Product Principle

Agent Mail should behave like team coordination, not a passive inbox. If a user or another agent sends a context request to a connected teammate, Claude Deck should either:

1. actively wake an appropriate agent runtime, or
2. clearly say that the message is delivered but no wake path is available.

The UI must not imply that `connected` means "will wake up". The implementation should expose wakeability explicitly.

## Current MVP Behavior

Relevant files after PR #186:

- `backend/app/services/agent_mail_service.py`
  - Stores messages and receipts in `send_message`.
  - Calls `auto_nudge_members` after commit.
  - Can nudge only observed Codex tmux sessions through `_send_tmux_inbox_check`.
  - Exposes manual `queue_inbox_check`, also tmux-only.
  - Computes `can_nudge` as a boolean in `list_team`.
- `backend/app/services/agent_mail_install_service.py`
  - Installs Codex MCP through `codex mcp add`.
  - Installs Codex `SessionStart` and `UserPromptSubmit` hooks.
  - Does not manage Codex app-server or remote-control daemon.
- `frontend/src/features/agent-mail/TeamTab.tsx`
  - Shows `Queue inbox check` only when `member.can_nudge` is true and the member has unread/pending mail.
- `frontend/src/types/agentMail.ts`
  - Models wakeability as `can_nudge: boolean`; no distinction between tmux, app-server, or unavailable.

## Codex Capability Facts

From the current Codex manual and local CLI:

- `codex app-server` is a JSON-RPC 2.0 interface used by rich Codex clients.
- Supported methods include:
  - `initialize`
  - `thread/list`
  - `thread/loaded/list`
  - `thread/read`
  - `thread/resume`
  - `thread/start`
  - `turn/start`
  - `turn/steer`
- Threads include `id`, `cwd`, `status`, `source`, `sessionId`, `updatedAt`, and optional title/preview metadata.
- Thread statuses include `notLoaded`, `idle`, `active`, and `systemError`.
- `turn/start` starts a new user turn on a thread.
- `turn/steer` can append input to an active turn, but requires the expected active turn id.
- `codex remote-control start` starts the app-server daemon with remote control enabled.
- `codex app-server daemon start` starts the managed daemon.
- `codex app-server daemon enable-remote-control` enables remote control for future starts and the current managed daemon.
- `codex app-server daemon version` reports local/running versions, but fails when no daemon socket exists.
- `codex app-server proxy` proxies JSONL stdio bytes to the running app-server control socket.

Important implication: use `codex app-server proxy` first. It avoids custom WebSocket-over-Unix-socket code in Claude Deck while still using the local app-server control socket.

## Non-Goals

- Do not keep guessing tmux key sequences for non-tmux sessions.
- Do not expose app-server on a public or non-loopback network listener.
- Do not promise waking the exact visible Codex terminal session until the spike proves that behavior.
- Do not make Agent Mail depend on Codex app-server for Claude Code.
- Do not implement long-lived streaming UI for Codex turns in this issue.
- Do not add user-facing chat transcripts for app-server wake turns in Agent Mail MVP follow-up. The wake turn's job is to get the agent to call `deck_check_inbox`.

## Key Uncertainty

The main unanswered question is not whether Claude Deck can send a turn through app-server. It can, assuming the daemon is running and authenticated. The question is what that turn controls:

- Does `thread/resume` + `turn/start` wake the existing non-tmux CLI TUI session?
- Does it resume the same Codex thread in a separate app-server-managed runtime?
- Does it start a parallel worker for the repo when no thread is loaded?

All three can be useful, but they have different UX wording and safety implications. The spike must answer this before broad implementation.

## Proposed User Experience

### Team Cards

Replace the single `can_nudge` mental model with explicit delivery/wakeup status.

Suggested member-level fields:

```python
wake_state: Literal["wakeable", "delivered_waiting", "offline"]
wake_methods: list[Literal["tmux", "codex_app_server"]]
last_nudge_method: Optional[str]
last_nudge_error: Optional[str]
```

Suggested UI labels:

- `Connected`: this member has checked in recently through MCP/hooks.
- `Wakeable via tmux`: Deck can inject an inbox check into an observed tmux Codex pane.
- `Wakeable via Codex`: Deck can send an inbox-check turn through Codex app-server.
- `Delivered, waiting`: mail is stored, but no active wake path is available.
- `Offline`: no recent check-in and no live observation.

Keep the UI quiet:

- Show a small wakeability badge next to the existing member status badge.
- Keep the manual button as `Queue inbox check`.
- In the button tooltip, name the method that will be used.
- If no wake path exists and the member has unread/pending mail, show a compact warning: `Delivered, waiting for agent activity`.

### Install Tab

Add a Codex app-server section under Codex CLI:

- `Codex MCP`: installed/not installed.
- `Codex hooks`: installed/not installed.
- `Codex remote control`: running/not running/unavailable.
- `Wakeups`: available/unavailable.

Actions:

- `Enable remote control`
  - Prefer `codex remote-control start --json` if it proves reliable in the spike.
  - Otherwise use `codex app-server daemon start` followed by `codex app-server daemon enable-remote-control`.
- `Stop remote control`
  - Use `codex remote-control stop --json` or `codex app-server daemon stop`.

Copy should be explicit that this enables local Codex wakeups for Agent Mail and uses Codex's local app-server daemon.

## Architecture

### New Backend Service

Create `backend/app/services/codex_app_server_service.py`.

Responsibilities:

- Detect Codex CLI availability.
- Detect app-server daemon status.
- Start/stop or enable remote control through Codex CLI.
- Create a short-lived JSON-RPC connection through `codex app-server proxy`.
- Initialize JSON-RPC with `clientInfo.name = "claude_deck"` and `capabilities.experimentalApi = true`.
- List candidate threads for a repo cwd.
- Choose the best thread.
- Resume/start a thread.
- Send the Agent Mail inbox-check prompt through `turn/start` or `turn/steer`.
- Return structured wakeup results to Agent Mail.

Initial API sketch:

```python
@dataclass
class CodexAppServerStatus:
    codex_cli_available: bool
    daemon_available: bool
    remote_control_available: bool
    version: dict | None
    error: str | None = None

@dataclass
class CodexWakeResult:
    ok: bool
    method: str
    thread_id: str | None = None
    turn_id: str | None = None
    created_thread: bool = False
    resumed_thread: bool = False
    error: str | None = None

class CodexAppServerService:
    def status(self) -> CodexAppServerStatus: ...
    def enable_remote_control(self) -> CodexAppServerStatus: ...
    def stop_remote_control(self) -> CodexAppServerStatus: ...
    def wake_repo(self, repo_path: str, prompt: str) -> CodexWakeResult: ...
```

Keep this service isolated from Agent Mail business logic. Agent Mail should ask for wakeup capability; the Codex service owns all Codex protocol details.

### JSON-RPC Client Strategy

Use `codex app-server proxy` as a child process per wake operation for the first implementation.

Rationale:

- No persistent socket lifecycle in Claude Deck.
- No custom WebSocket-over-Unix-socket transport.
- Easier to test by mocking subprocess stdin/stdout.
- Failure mode is contained to one wake attempt.

Flow:

1. Spawn `codex app-server proxy`.
2. Send:

```json
{"id":1,"method":"initialize","params":{"clientInfo":{"name":"claude_deck","title":"Claude Deck","version":"<deck-version>"},"capabilities":{"experimentalApi":true}}}
```

3. Send:

```json
{"method":"initialized","params":{}}
```

4. Send `thread/list` with exact cwd filter for the member repo path.
5. Select thread.
6. Send `thread/resume` or `thread/start`.
7. Send `turn/start` with:

```json
{
  "threadId": "<thread id>",
  "input": [
    {
      "type": "text",
      "text": "Claude Deck Agent Mail: please call `deck_check_inbox(unread_only=False)` now, then answer any pending context requests or handoffs before continuing."
    }
  ],
  "cwd": "<repo path>"
}
```

8. Wait only for the `turn/start` response, not the whole turn completion.
9. Close the proxy process gracefully.

Timeouts:

- App-server status command: 3 seconds.
- Proxy initialize/list/resume/start sequence: 10 seconds total.
- Turn completion should not be awaited.

### Thread Selection

Selection must be conservative to avoid waking the wrong repo or old thread.

Algorithm:

1. `thread/list` with `cwd` equal to member `repo_path`.
2. Prefer non-archived threads.
3. Prefer threads where `status.type` is `idle`.
4. Then prefer `notLoaded`.
5. Avoid `systemError`.
6. Avoid `active` for MVP unless the spike proves `turn/steer` is safe and we can identify the active turn id.
7. Sort by `updatedAt` descending.
8. If no thread exists:
   - `thread/start` with `cwd = member.repo_path`.
   - Then `turn/start`.

If the spike proves `turn/steer` is reliable:

- Add active-thread steering as a second step.
- Require active turn id from `thread/read` or notifications.
- If active turn id cannot be established, do not steer; fall back to delivered-waiting or start a separate thread only if the user explicitly permits that behavior.

### Wake Routing

Refactor `AgentMailService` nudge logic into method-aware routing:

Current:

- `auto_nudge_members` -> `sync_observed_sessions` -> `_nudge_session_for_member` -> `_send_tmux_inbox_check`

Proposed:

```python
async def _wake_member(self, db: AsyncSession, member_id: int, reason: str) -> WakeResult | None:
    # 1. Prefer tmux when available for a visible interactive session.
    # 2. Else use Codex app-server when member has connected Codex MCP/hook session
    #    or a Codex thread exists for repo_path.
    # 3. Else return None.
```

Routing priority:

1. Tmux observed Codex session:
   - Current behavior remains first because it wakes the visible terminal session.
2. Codex app-server:
   - Use when member has any live/recent `codex-cli` session or Codex thread for the repo.
3. No wake path:
   - Mail remains delivered.
   - UI shows `Delivered, waiting`.

Keep throttling:

- Existing `AUTO_NUDGE_COOLDOWN_SECONDS` applies per member across all methods.
- Store the last method in memory for UX diagnostics.
- Consider database-backed nudge history only if the in-memory status proves insufficient.

### Manual Queue Endpoint

Keep the existing endpoint:

```http
POST /api/v1/agent-mail/members/{member_id}/queue-inbox-check
```

Change response from tmux-specific payload to method-aware payload:

```json
{
  "ok": true,
  "method": "codex_app_server",
  "target": "thread:<thread-id>",
  "prompt": "..."
}
```

Possible error details:

- `No wake path is available for this member`
- `Codex app-server remote control is not running`
- `No Codex thread found for this repo and thread start failed`
- `Codex app-server rejected the wake request`

### Install Status API

Extend `AgentMailInstallStatus`:

```python
codex_app_server_available: bool = False
codex_remote_control_running: bool = False
codex_app_server_version: Optional[dict] = None
codex_app_server_error: Optional[str] = None
```

Add endpoints:

```http
POST /api/v1/agent-mail/install/codex/remote-control/start
POST /api/v1/agent-mail/install/codex/remote-control/stop
```

Implementation:

- Reuse provider CLI executor if it supports `codex app-server ...` and `codex remote-control ...` args safely.
- If safe arg constraints block nested commands, add a narrow dedicated executor method in the install service instead of broadening generic CLI execution.
- Back up Codex config only if commands mutate durable config. Starting/stopping a daemon likely does not need a config backup; enabling remote control for future starts may.

### Schema Changes

Backend schema additions in `backend/app/models/schemas.py`:

```python
class MailWakeCapability(BaseModel):
    method: str
    label: str
    available: bool
    detail: Optional[str] = None

class MailMemberResponse(BaseModel):
    ...
    can_nudge: bool = False  # keep for compatibility during transition
    wake_methods: List[str] = Field(default_factory=list)
    wake_state: str = "delivered_waiting"
```

Frontend type additions in `frontend/src/types/agentMail.ts`:

```ts
export type MailWakeMethod = 'tmux' | 'codex_app_server'
export type MailWakeState = 'wakeable' | 'delivered_waiting' | 'offline'
```

Keep `can_nudge` for one release to avoid a large front/back compatibility break.

### UI Changes

Files:

- `frontend/src/types/agentMail.ts`
- `frontend/src/features/agent-mail/utils.ts`
- `frontend/src/features/agent-mail/TeamTab.tsx`
- `frontend/src/features/agent-mail/InstallTab.tsx`
- `frontend/src/features/agent-mail/AgentMailHelpDialog.tsx`
- `docs/features/agent-mail.md`

Team tab:

- Add `wakeStateLabel`, `wakeStateBadgeClass`, `wakeMethodLabel`.
- Show wake badge separately from connectivity badge.
- Keep `Queue inbox check` if `wake_methods.length > 0`.
- Tooltip should show the preferred method.
- For unread/pending mail with no wake method, show a small `Delivered, waiting for poll` warning.

Install tab:

- Add Codex remote-control status.
- Add start/stop actions.
- Warn that this is local Codex app-server remote control and required for non-tmux Codex wakeups.

Help dialog/docs:

- Explain:
  - MCP means the agent can read/send mail.
  - Hooks mean the agent is reminded at turn boundaries.
  - Tmux wakeups wake visible tmux Codex sessions.
  - Codex app-server wakeups wake non-tmux Codex through Codex's native local control plane.

## Spike Plan

Do this before implementation PR work.

### Spike A: Daemon lifecycle

Commands to test:

```bash
codex app-server daemon version
codex remote-control start --json
codex app-server daemon version
codex app-server proxy
codex remote-control stop --json
```

Record:

- Exit codes.
- JSON output shape.
- Whether `remote-control start` is idempotent.
- Whether it persists remote-control enablement.
- Whether it leaves background processes after stop.

### Spike B: Protocol handshake through proxy

Build a small temporary script outside production code that:

- Spawns `codex app-server proxy`.
- Sends `initialize`.
- Sends `initialized`.
- Sends `thread/list` with `cwd` for `/home/joni/repos/claude-deck`.
- Prints responses and notifications.

Record:

- Whether the proxy exits cleanly when stdin closes.
- Whether notifications interleave with responses.
- Whether response ids are stable enough for simple request/response matching.

### Spike C: Wake semantics

With one non-tmux Codex session idle in another repo:

1. Send an Agent Mail test message.
2. Use the spike script to find the repo thread.
3. Send `thread/resume` + `turn/start` with the inbox prompt.
4. Observe whether:
   - the visible CLI session wakes,
   - a separate app-server-controlled worker runs,
   - a new thread appears in Codex history,
   - the Agent Mail inbox is read.

Decision after spike:

- If visible CLI wakes: UI can say `Wakeable via Codex app-server`.
- If separate worker runs but reads the same repo mailbox: UI should say `Wakeable via Codex worker`, not imply the existing terminal woke.
- If neither is reliable: app-server should not be shipped as automatic wakeup; use it only as an explicit "start Codex worker for this repo" action.

### Spike D: Active thread behavior

With a Codex turn actively running:

- Try `thread/list`.
- Inspect status.
- Determine whether the active turn id is discoverable.
- Try `turn/steer` only in a disposable session.

Decision:

- If `turn/steer` is safe and reliable, add active-turn steering.
- Otherwise, MVP app-server wakeups should target idle/notLoaded threads only.

## Implementation Tasks

### Task 1: Codex app-server client

Add `backend/app/services/codex_app_server_service.py`.

Test file: `backend/tests/agent_mail/test_codex_app_server_service.py`.

Coverage:

- Parses success and error JSON-RPC responses.
- Sends initialize before other calls.
- Handles notification interleaving.
- Times out cleanly.
- Reports daemon unavailable when proxy cannot connect.
- Lists threads by cwd.
- Selects best thread from mixed statuses.
- Sends `thread/resume` + `turn/start`.
- Starts a new thread if allowed and no thread exists.

### Task 2: Install/status integration

Modify:

- `backend/app/services/agent_mail_install_service.py`
- `backend/app/api/v1/agent_mail.py`
- `backend/app/models/schemas.py`
- `backend/tests/agent_mail/test_install.py`

Add:

- Status fields for app-server/remote-control.
- Start/stop endpoints.
- Tests with mocked Codex executor.

Acceptance:

- Install tab can report remote-control unavailable/running.
- Start/stop actions return refreshed install status.
- Failures surface as concise UI errors.

### Task 3: Wake routing refactor

Modify:

- `backend/app/services/agent_mail_service.py`
- `backend/tests/agent_mail/test_registry.py`
- `backend/tests/agent_mail/test_messaging.py`
- `backend/tests/agent_mail/test_api.py`

Add:

- Wake result dataclass.
- Method-aware `_wake_member`.
- Tmux-first routing.
- App-server fallback.
- Manual queue endpoint method-aware response.
- Per-member cooldown shared across wake methods.

Acceptance:

- Tmux path still works exactly as MVP.
- App-server path is used when tmux is unavailable and Codex app-server is available.
- No wake path leaves mail delivered and does not fail `send_message`.
- Manual queue returns 400 when no wake path exists.

### Task 4: Response schema and UI wakeability

Modify:

- `backend/app/models/schemas.py`
- `frontend/src/types/agentMail.ts`
- `frontend/src/features/agent-mail/utils.ts`
- `frontend/src/features/agent-mail/TeamTab.tsx`
- `frontend/src/features/agent-mail/AgentMailPage.tsx` if response handling changes.

Acceptance:

- Members distinguish connected status from wakeability.
- Queue button appears for tmux or app-server wakeable members.
- Delivered-but-not-wakeable pending mail is visible without looking like an error.
- Existing Agent Mail flows still render when new fields are absent or empty.

### Task 5: Install UI

Modify:

- `frontend/src/features/agent-mail/InstallTab.tsx`
- `frontend/src/features/agent-mail/api.ts`
- `frontend/src/types/agentMail.ts`

Acceptance:

- User can see Codex remote-control status.
- User can start/stop remote control.
- Copy explains why this matters for non-tmux Codex wakeups.
- Actions show success/error toasts and refresh status.

### Task 6: Documentation

Modify:

- `docs/features/agent-mail.md`
- Possibly `docs/guide/quick-start.md`.

Document:

- `Connected` vs `Wakeable`.
- Tmux wakeups.
- Codex app-server wakeups.
- Limitations if app-server is not running.
- Security note: keep app-server local; do not expose remote transports.

### Task 7: Validation

Backend:

```bash
backend/venv/bin/python -m pytest backend/tests/agent_mail -q
```

Frontend:

```bash
cd frontend && npm test -- --run
cd frontend && npm run build
```

Manual:

1. Start Deck.
2. Open Agent Mail.
3. Confirm Codex install status shows MCP/hooks/app-server status.
4. Start one Codex session in tmux and one outside tmux.
5. Send mail to tmux session; verify tmux wake path.
6. Send mail to non-tmux session; verify app-server wake path.
7. Stop remote control; verify UI changes to delivered-waiting and no automatic wake is attempted.

## Data Model Decision

Do not add database columns in the first pass unless spike results show the need.

Reason:

- Wakeability can be derived from session data plus Codex app-server status.
- Last wake result can be kept in memory initially.
- Persisting app-server thread ids before the semantics are proven risks stale or misleading routing.

If the spike proves app-server creates a stable worker/thread per repo, then add an optional table in a later iteration:

```text
mail_codex_thread_links
- id
- member_id
- repo_path
- thread_id
- session_id
- last_wake_at
- last_status
- created_at
- updated_at
```

Do not include that table in the first implementation unless required.

## Security Considerations

- Use only local Codex app-server control paths.
- Prefer `codex app-server proxy` over direct network listeners.
- Do not configure `ws://0.0.0.0` or any non-loopback listener.
- Do not store Codex auth tokens or app-server credentials in Claude Deck.
- Start/stop actions should be explicit user actions from the Install tab.
- Automatic wakeups should only use an already available local control plane.
- Wake prompts should be fixed and minimal; do not include arbitrary sender-provided text in the wake prompt.

## Error Handling

`send_message` should never fail merely because wakeup failed. Delivery and wakeup are separate:

- Delivery failure: message was not stored.
- Wakeup failure: message is stored, but no agent was actively nudged.

Log wake failures at debug/info level with concise reason. Surface user-facing wake failures only on manual queue actions or install/status screens.

Recommended wake result reasons:

- `tmux_unavailable`
- `app_server_not_running`
- `app_server_proxy_failed`
- `no_codex_thread_for_repo`
- `thread_resume_failed`
- `turn_start_failed`
- `wake_throttled`

## Acceptance Criteria

- A non-tmux Codex member with app-server remote control available can be nudged from Agent Mail without terminal key injection.
- Agent Mail still stores messages even when wakeup fails.
- UI clearly distinguishes connected from wakeable.
- Tmux wakeups continue to work.
- Codex install/status UI explains and manages app-server remote control.
- Tests cover tmux-first routing, app-server fallback, and no-wake fallback.
- Documentation explains setup, limitations, and the security boundary.

## Review Questions

1. Should Claude Deck automatically start Codex remote-control after Codex Agent Mail install, or should the user start it explicitly?
2. If app-server starts a separate Codex worker rather than waking the visible CLI session, is that acceptable for Agent Mail, and what should the UI call it?
3. Should active Codex turns receive `turn/steer`, or should Agent Mail wait until they are idle?
4. Should a missing Codex thread create a new app-server thread automatically, or should that require a manual "Start worker" action?
5. Should wake result history be persisted in SQLite, or is derived status plus current UI state enough for the first version?

## Recommended Implementation Sequence

1. Run and document the four spike steps.
2. Decide exact UX language based on spike results.
3. Implement `CodexAppServerService` behind mocked subprocess tests.
4. Add install/status endpoints and UI.
5. Refactor Agent Mail wake routing.
6. Add UI wakeability badges and delivered-waiting state.
7. Update docs and run full validation.

Do not start production implementation until the spike confirms whether app-server wakeups wake the existing CLI session or a separate Codex runtime.
