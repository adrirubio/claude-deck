# Codex App-Server Wakeups For Agent Mail

**Issue:** [#185](https://github.com/adrirubio/claude-deck/issues/185)  
**Status:** Spike completed; automatic app-server wakeups disabled after live validation
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

Spike result: the installed Codex CLI on this machine supports `codex app-server --stdio` directly, but `codex remote-control start --json` fails because it requires the managed standalone Codex install at `~/.codex/packages/standalone/current/codex`. A custom Unix socket plus `codex app-server proxy --sock ...` timed out during `initialize`. The implementation therefore uses a Deck-managed persistent `codex app-server --stdio` child process and reports remote-control daemon status only as diagnostic information.

## Non-Goals

- Do not keep guessing tmux key sequences for non-tmux sessions.
- Do not expose app-server on a public or non-loopback network listener.
- Do not promise waking the exact visible Codex terminal session until the spike proves that behavior.
- Do not make Agent Mail depend on Codex app-server for Claude Code.
- Do not implement long-lived streaming UI for Codex turns in this issue.
- Do not add user-facing chat transcripts for app-server wake turns in Agent Mail MVP follow-up. The wake turn's job is to get the agent to call `deck_check_inbox`.

## Key Uncertainty

The main unanswered question is not whether Claude Deck can send a turn through app-server. It can, assuming the Deck-managed app-server process is running. The question is what that turn controls:

- Does `thread/resume` + `turn/start` wake the existing non-tmux CLI TUI session?
- Does it resume the same Codex thread in a separate app-server-managed runtime?
- Does it start a parallel worker for the repo when no thread is loaded?

All three can be useful, but they have different UX wording and safety implications. The spike must answer this before broad implementation.

## Spike Results

Completed on 2026-06-14:

- `codex remote-control start --json` is not usable on this install; it fails with "managed standalone Codex install not found".
- `codex app-server --stdio` works as a direct JSON-RPC transport.
- `initialize`, `thread/list`, `thread/start`, `thread/resume`, and `turn/start` work through the direct stdio process.
- `turn/start` accepts the fixed inbox prompt and returns promptly enough to treat request acceptance as wake success.
- A custom `codex app-server proxy --sock ...` path was unreliable and timed out during `initialize`.
- `turn/start` should omit optional analytics/source fields; `threadSource: {"kind": "local"}` was rejected by the local CLI.

Initial implementation decision: Claude Deck owned one local app-server child process for the backend lifetime. Start/stop were runtime controls, not durable configuration mutation.

Live validation later showed that this path does not wake the visible Codex CLI session. It can run a separate app-server-controlled Codex runtime that calls `deck_check_inbox`, which marks the visible member's mailbox read without making the visible agent act on the message. That is not acceptable for Agent Mail delivery semantics.

Corrected implementation decision: do not use app-server as an automatic Agent Mail wake path. Keep non-tmux Codex members in `delivered_waiting` unless a real visible wake path exists. App-server worker orchestration should be designed separately from Agent Mail delivery nudges.

## Proposed User Experience

### Team Cards

Replace the single `can_nudge` mental model with explicit delivery/wakeup status.

Suggested member-level fields:

```python
wake_state: Literal["wakeable", "delivered_waiting", "offline"]
wake_methods: list[Literal["tmux"]]
last_nudge_method: Optional[str]
last_nudge_error: Optional[str]
```

Suggested UI labels:

- `Connected`: this member has checked in recently through MCP/hooks.
- `Wakeable via tmux`: Deck can inject an inbox check into an observed tmux Codex pane.
- `Not wakeable`: mail is stored, but no active visible wake path is available.
- `Offline`: no recent check-in and no live observation.

Keep the UI quiet:

- Show a small wakeability badge next to the existing member status badge.
- Keep the manual button as `Queue inbox check`.
- In the button tooltip, name the method that will be used.
- If no wake path exists and the member has unread/pending mail, show a compact warning: `No wake path is available; the visible agent must check its inbox.`

### Install Tab

Add a Codex app-server section under Codex CLI:

- `Codex MCP`: installed/not installed.
- `Codex hooks`: installed/not installed.
- `Codex app-server`: diagnostic/experimental worker status only, not a visible wake path.
- `Codex remote control`: running/not running/unavailable as diagnostic status only.

Actions:

Do not expose app-server as "Start wakeups" unless Codex can target the visible CLI session.

Copy should be explicit that non-tmux Codex delivery waits for the agent to poll or reach a hook boundary.

### Daemon Lifetime And Idempotency

Treat Codex Agent Mail install and Codex app-server runtime state as separate things:

- Codex MCP/hooks install is durable user configuration and should remain a one-off install action.
- Codex app-server availability is runtime state, but it should not be treated as Agent Mail wakeability for visible Codex CLI sessions.
- Claude Deck must never ask users to reinstall Codex Agent Mail just because an app-server process is stopped.

The backend start path must be idempotent:

- If the Deck-managed app-server child process is already running, `start` returns success and refreshed status without launching a duplicate process.
- If no child process is running, `start` launches `codex app-server --stdio`, initializes JSON-RPC, and returns refreshed status.
- If the child process is half-started or does not answer `initialize`, `start` should tear it down before surfacing an error.
- `stop` should be idempotent: stopping an already-stopped app-server returns success with `codex_app_server_running=false`.

Install-tab copy should use "Start Codex wakeups" or "Enable Codex wakeups" rather than "Install" for this action, so users understand it is runtime availability, not repeated configuration mutation.

## Superseded Architecture

The architecture below records the attempted app-server implementation. It is not the current Agent Mail wakeup plan because live validation showed it drives a separate app-server worker rather than the visible Codex CLI session.

### New Backend Service

Create `backend/app/services/codex_app_server_service.py`.

Responsibilities:

- Detect Codex CLI availability.
- Detect Deck-managed app-server process status.
- Report remote-control daemon status as diagnostic information.
- Start/stop a Deck-managed `codex app-server --stdio` child process.
- Maintain a JSON-RPC connection to that process.
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
    app_server_available: bool
    app_server_running: bool
    remote_control_running: bool
    remote_control_error: str | None = None
    app_server_error: str | None = None

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
    def start(self) -> CodexAppServerStatus: ...
    def stop(self) -> CodexAppServerStatus: ...
    def wake_repo(self, repo_path: str, prompt: str) -> CodexWakeResult: ...
```

Keep this service isolated from Agent Mail business logic. Agent Mail should ask for wakeup capability; the Codex service owns all Codex protocol details.

### JSON-RPC Client Strategy

Use one persistent `codex app-server --stdio` child process owned by the backend.

Rationale:

- No custom WebSocket-over-Unix-socket transport.
- No dependency on the managed standalone remote-control install.
- Shared initialized JSON-RPC state for repeated wakeups.
- Easier to test by mocking subprocess stdin/stdout.
- Failure mode is contained to one Deck-owned child process that can be stopped/restarted.

Flow:

1. Spawn `codex app-server --stdio` when the user starts Codex wakeups.
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
9. Keep the app-server process running for future wakeups until the backend shuts down or the user stops wakeups.

Timeouts:

- App-server status command: 3 seconds.
- Initialize/list/resume/start requests: 10-20 seconds depending on operation.
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
   - UI shows `Not wakeable`.

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
- `Codex app-server wakeups are not running`
- `No Codex thread found for this repo and thread start failed`
- `Codex app-server rejected the wake request`

### Install Status API

Extend `AgentMailInstallStatus`:

```python
codex_app_server_available: bool = False
codex_app_server_running: bool = False
codex_remote_control_running: bool = False
codex_app_server_error: Optional[str] = None
codex_remote_control_error: Optional[str] = None
```

Add endpoints:

```http
POST /api/v1/agent-mail/install/codex/wakeups/start
POST /api/v1/agent-mail/install/codex/wakeups/stop
```

Implementation:

- Delegate start/stop to `CodexAppServerService`.
- Do not back up Codex config for wakeup start/stop because these endpoints do not mutate durable configuration.
- Keep remote-control status as read-only diagnostic status.

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
- For unread/pending mail with no wake method, show a small `No wake path is available` warning.

Install tab:

- Keep Codex MCP/hooks install status clear.
- Do not expose app-server start/stop actions as Agent Mail wake controls.
- Explain that non-tmux Codex delivery waits for polling or hook-boundary reminders.

Help dialog/docs:

- Explain:
  - MCP means the agent can read/send mail.
  - Hooks mean the agent is reminded at turn boundaries.
  - Tmux wakeups wake visible tmux Codex sessions.
  - App-server worker turns are not equivalent to waking the visible Codex CLI session.

## Original Spike Plan

These were the investigation steps proposed before implementation. See **Spike Results** above for the decisions that supersede the remote-control/proxy path.

### Spike A: Daemon lifecycle

Commands to test:

```bash
codex app-server daemon version
codex remote-control start --json
codex app-server daemon version
codex remote-control start --json
codex app-server daemon version
codex app-server proxy
codex remote-control stop --json
codex remote-control stop --json
```

Record:

- Exit codes.
- JSON output shape.
- Whether repeated `remote-control start` is idempotent.
- Whether repeated `remote-control stop` is idempotent.
- Whether start creates duplicate daemon processes.
- Whether start recovers from a stale socket or half-started daemon.
- Whether it persists remote-control enablement.
- Whether it leaves background processes after stop.
- Whether the daemon survives shell exit, Deck restart, user logout, or machine reboot. Reboot testing can be manual, but the plan must not assume persistence without verification.

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

## Superseded Implementation Tasks

The task list below is retained for audit context. Do not implement app-server fallback as Agent Mail wakeability unless Codex exposes a control path that reaches the visible CLI session.

### Task 1: Codex app-server client

Add `backend/app/services/codex_app_server_service.py`.

Test file: `backend/tests/agent_mail/test_codex_app_server_service.py`.

Coverage:

- Parses success and error JSON-RPC responses.
- Sends initialize before other calls.
- Handles notification interleaving.
- Times out cleanly.
- Reports app-server unavailable when the Deck-managed child process cannot start or answer.
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

- Status fields for app-server runtime and remote-control diagnostic state.
- Start/stop endpoints.
- Tests with mocked Codex executor.
- Explicit idempotency tests for start and stop.

Acceptance:

- Install tab can report app-server stopped/running/unavailable.
- Start/stop actions return refreshed install status.
- Start action is safe to call repeatedly and does not create duplicate app-server processes.
- Stop action is safe to call repeatedly and reports stopped state.
- Stopped app-server state does not mark Codex MCP/hooks install as missing.
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
- No app-server fallback unless it can target the visible Codex CLI session.
- Manual queue endpoint method-aware response.
- Per-member cooldown shared across wake methods.

Acceptance:

- Tmux path still works exactly as MVP.
- Connected non-tmux Codex sessions remain delivered-waiting instead of being marked wakeable.
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
- Queue button appears only for members with a real visible wake path.
- Delivered-but-not-wakeable pending mail is visible without looking like an error.
- Existing Agent Mail flows still render when new fields are absent or empty.

### Task 5: Install UI

Modify:

- `frontend/src/features/agent-mail/InstallTab.tsx`
- `frontend/src/features/agent-mail/api.ts`
- `frontend/src/types/agentMail.ts`

Acceptance:

- User can see Codex app-server wakeup status.
- User can start/stop Codex wakeups.
- The UI distinguishes durable Codex Agent Mail install from runtime Codex wakeup availability.
- The main action says `Start Codex wakeups` or `Enable Codex wakeups`, not `Install`, when MCP/hooks are already installed.
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
6. Send mail to non-tmux session; verify it remains delivered-waiting and unread until the visible agent checks inbox.
7. Verify no app-server worker is launched as an automatic wake for Agent Mail delivery.

## Data Model Decision

Do not add database columns in the first pass unless spike results show the need.

Reason:

- Wakeability can be derived from session data plus Agent Bridge tmux visibility.
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

- Use only local Codex app-server control paths for future explicit worker orchestration.
- Prefer local stdio app-server control over direct network listeners.
- Do not configure `ws://0.0.0.0` or any non-loopback listener.
- Do not store Codex auth tokens or app-server credentials in Claude Deck.
- Do not expose app-server start/stop as Agent Mail wakeup controls.
- Automatic wakeups should only use a control plane that reaches the visible agent session.
- Wake prompts should be fixed and minimal; do not include arbitrary sender-provided text in the wake prompt.

## Error Handling

`send_message` should never fail merely because wakeup failed. Delivery and wakeup are separate:

- Delivery failure: message was not stored.
- Wakeup failure: message is stored, but no agent was actively nudged.

Log wake failures at debug/info level with concise reason. Surface user-facing wake failures only on manual queue actions or install/status screens.

Recommended wake result reasons:

- `tmux_unavailable`
- `wake_throttled`

## Acceptance Criteria

- Agent Mail still stores messages even when wakeup fails.
- UI clearly distinguishes connected from wakeable.
- Connected non-tmux Codex members show delivered-waiting, not wakeable.
- Tmux wakeups continue to work.
- Codex install/status UI does not imply app-server wakes visible CLI sessions.
- Tests cover tmux-first routing and no-wake fallback for non-tmux Codex.
- Documentation explains setup, limitations, and the security boundary.

## Review Questions

1. Should Claude Deck automatically start Codex wakeups after Codex Agent Mail install, or should the user start them explicitly?
2. If app-server starts a separate Codex worker rather than waking the visible CLI session, is that acceptable for Agent Mail, and what should the UI call it?
3. Should active Codex turns receive `turn/steer`, or should Agent Mail wait until they are idle?
4. Should a missing Codex thread create a new app-server thread automatically, or should that require a manual "Start worker" action?
5. Should wake result history be persisted in SQLite, or is derived status plus current UI state enough for the first version?

## Superseded Implementation Sequence

The sequence below was the original plan before live validation. The corrected path is to ship explicit `wakeable` vs `delivered_waiting` state and keep app-server worker orchestration out of Agent Mail delivery nudges.

1. Run and document the four spike steps.
2. Decide exact UX language based on spike results.
3. Implement `CodexAppServerService` behind mocked subprocess tests.
4. Add install/status endpoints and UI.
5. Refactor Agent Mail wake routing.
6. Add UI wakeability badges and delivered-waiting state.
7. Update docs and run full validation.

Do not start production implementation until the spike confirms whether app-server wakeups wake the existing CLI session or a separate Codex runtime.
