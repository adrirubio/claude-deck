# Agent Bridge Image Paste — Design Spec & Implementation Plan

**Status:** Draft for review (no implementation committed)
**Date:** 2026-06-29
**Target version:** post-2.0.1
**Scope:** Add image paste / drag-drop support to Agent Bridge terminal sessions so a browser user can provide screenshots, mockups, diagrams, and other images to Claude Code, Codex CLI, OpenCode CLI, and future tmux-backed agents.

---

## 1. Problem & Motivation

Agent Bridge is now usable for observing and interacting with local/remote tmux-backed agent sessions, but it is still missing the main affordance users expect from native agent UIs: **paste an image into the active agent conversation**.

The current terminal bridge can relay keyboard input into a `tmux attach-session` pty, but a browser clipboard image is binary data and the underlying CLIs do not receive browser attachments through tmux. The right user-facing outcome is:

1. user focuses an Agent Bridge terminal,
2. user pastes or drops an image,
3. Claude Deck stores the image somewhere the tmux agent process can read,
4. Claude Deck injects a concise prompt containing the image file path,
5. the agent CLI handles the image path using its own multimodal/file-ingestion behavior.

This is especially important when Claude Deck is running on a remote machine. In that case, the browser clipboard image originates on the user's laptop, but the agent and tmux session run on the remote host. Uploading the image to the Deck backend solves that mismatch cleanly: the pasted path is remote-local to the agent process.

---

## 2. Current Architecture (as-is)

### 2.1 Terminal relay path

Current Agent Bridge terminal input flows through:

```
frontend/src/features/cc-bridge/useTerminal.ts
  └─ WebSocket to /api/v1/agent-bridge/sessions/{target}/terminal
       └─ backend/app/api/v1/agent_bridge/router.py
            └─ PtyRelay(target)
                 └─ backend/app/services/agent_bridge/pty_relay.py
                      ├─ pty.openpty()
                      ├─ subprocess.Popen(["tmux", "attach-session", "-t", target], stdin/out/err=slave_fd)
                      └─ websocket text/bytes frames write to pty master fd
```

Important consequences:

- The browser can send text/bytes to the pty, but the relay has no concept of browser files or attachments.
- The relay already has control messages (`resize`, `mode`) via JSON text frames.
- The public Agent Bridge namespace is `backend/app/services/agent_bridge/`; the legacy `cc_bridge` backend modules are compatibility shims and should not be the target for new code. The frontend directory is still `frontend/src/features/cc-bridge/`.
- Interactive input is disabled when a specific websocket relay is in read-only mode.
- Any pasted text is currently treated as terminal input by `xterm` / `term.onData`.

### 2.2 Agent Bridge session metadata

Agent Bridge sessions expose provider/session/team metadata via:

- `GET /api/v1/agent-bridge/sessions`
- `frontend/src/features/cc-bridge/types.ts`

The target session has enough metadata to choose a provider-aware prompt template:

- `provider`
- `provider_display_name`
- `tmux_target`
- `session_name`
- optional Agent Team role/color metadata

### 2.3 Storage assumptions

Claude Deck defaults to local SQLite (`claude_registry.db`) and does not currently have a general attachment store. Existing filesystem state lives under user-owned directories, not a formal Deck data directory.

For this feature, attachments should be stored in a Deck-managed path on the same machine/filesystem namespace as the tmux process.

---

## 3. Goals

### G1 — Browser image paste

When an Agent Bridge terminal is focused, `Ctrl/Cmd+V` with an image in the clipboard should offer to attach that image to the active tmux session.

### G2 — Drag/drop image

Dragging an image file onto a terminal pane should follow the same attachment flow as clipboard paste.

### G3 — Remote Deck compatibility

If Claude Deck runs on a remote machine, the image must be uploaded to and saved on that remote machine, then referenced by a path visible to the tmux agent.

### G4 — Explicit user control

Users should be able to choose:

- paste image reference into the terminal without submitting,
- paste image reference and submit,
- cancel.

The safe default should be **paste without auto-submit**.

### G5 — Provider-aware prompt templates

The generated prompt should be provider-aware, while falling back to a generic file-path instruction:

```
Please inspect this image: /path/to/image.png
```

Provider-specific templates can evolve independently.

### G6 — API-accessible attachment flow

The feature should be usable through REST, not only the React UI.

### G7 — Agentic interface support

Agentic callers should be able to attach an existing server-side file or uploaded image to a Bridge session through MCP/deck tools once the backend API exists.

### G8 — Quotas, validation, and cleanup

The backend must enforce file type, size, storage, and retention controls.

---

## 4. Non-Goals

- Rendering images inside the terminal using Kitty graphics, Sixel, iTerm inline images, or OSC escape sequences.
- Sending raw base64 image data into the terminal input stream.
- Building a general-purpose file manager.
- Guaranteeing every provider CLI can consume every image format. Deck's responsibility is to store the file and inject a usable reference.
- Supporting remote agent processes that cannot see the Deck attachment directory unless an explicit mount/path mapping is configured.
- Adding chat-style rich message UI to Agent Bridge.

---

## 5. Proposed UX

### 5.1 Clipboard paste flow

1. User focuses an interactive Agent Bridge terminal.
2. User presses `Ctrl+V` / `Cmd+V`.
3. Frontend detects image clipboard item(s).
4. Frontend uploads the selected image to:

   ```
   POST /api/v1/agent-bridge/sessions/{target}/attachments
   ```

5. Frontend shows a compact confirmation dialog/toast:

   - thumbnail preview,
   - file name,
   - size,
   - target session label,
   - generated prompt text,
   - actions:
     - `Paste reference`
     - `Paste and submit`
     - `Cancel`

6. On confirmation, frontend calls the REST paste endpoint to inject the generated text into the active session.

### 5.2 Drag/drop flow

1. User drags one image onto a terminal pane.
2. Terminal pane highlights as a drop target.
3. Drop follows the same upload + confirmation flow.

For MVP, support one image per action. Multiple image support can be added after the storage/API semantics are stable.

### 5.3 Read-only mode behavior

If the terminal is read-only:

- pasting/dropping can still upload the image and show the generated prompt,
- the final `Paste reference` / `Paste and submit` action should be disabled until the user switches to interactive mode, or offer a one-click "Switch to interactive and paste" action.

Important implementation detail: read-only is currently per-websocket relay state (`PtyRelay.read_only`), not a persisted server-side session policy. The REST paste endpoint cannot infer which browser tab's read-only toggle should govern a target, and it should remain usable even when no browser is attached. Therefore:

- read-only is a UI/client affordance, not an API authorization boundary,
- the frontend must not call the paste endpoint from a read-only terminal unless the user explicitly switches to interactive mode,
- the backend paste endpoint is protected by the terminal token/same-origin write contract in §6.6, not by read-only relay state.

---

## 6. Backend Design

### 6.1 Attachment storage

Add a configured attachment root:

```
Settings.bridge_attachment_dir
env: CLAUDE_DECK_BRIDGE_ATTACHMENT_DIR
default: ~/.claude-registry/bridge-attachments
```

Add this as a `Settings` field in `backend/app/config.py` using the existing `pydantic-settings` mechanism. Do not add free-floating `os.getenv()` reads. The codebase already uses `~/.claude-registry` for user-owned app data such as backups, so attachments should live there rather than introducing a new `~/.claude-deck` directory.

Store files under a session-scoped directory:

```
{attachment_root}/{safe_session_name_or_target_hash}/{yyyy-mm-dd}/{timestamp}-{short_sha256}.{ext}
```

Example:

```
/home/juan/.claude-registry/bridge-attachments/snazzyemail-85b9/2026-06-29/185422-a1b2c3d4.png
```

The saved path returned to the frontend must be the path visible to the agent process. By default, this is the absolute host path.

### 6.2 Docker / namespace path mapping

Add optional config for deployments where the backend and tmux agent do not share the same filesystem namespace:

```
Settings.bridge_attachment_agent_root
env: CLAUDE_DECK_BRIDGE_ATTACHMENT_AGENT_ROOT
default: same as Settings.bridge_attachment_dir
```

If set, API responses use `agent_path` computed by replacing the storage root prefix with the agent root prefix:

```
storage_path: /app/data/bridge-attachments/session/img.png
agent_path:   /home/user/.claude-registry/bridge-attachments/session/img.png
```

This supports Docker bind mounts:

```
host:      ~/.claude-registry/bridge-attachments
container: /app/data/bridge-attachments
```

If no shared path exists, the API should return a clear configuration error instead of generating a path the agent cannot read.

### 6.3 File validation

Allow only image MIME types:

- `image/png`
- `image/jpeg`
- `image/webp`
- `image/gif` (optional for MVP; static/animated ambiguity)

Recommended defaults:

- max file size: `10 MB`
- max decoded dimensions: `12000 x 12000`
- max attachments per session per day: `100`
- max total attachment storage: configurable, default `1 GB`
- filename length limit: generated names only; ignore user-supplied path components

Validation should inspect file signatures, not only `Content-Type`.

### 6.4 Metadata persistence

Add a lightweight SQLAlchemy ORM model in `backend/app/models/database.py`. This is a brand-new table, so `Base.metadata.create_all()` can create it safely for existing SQLite users; no destructive rebuild of existing tables is required.

```python
class BridgeSessionAttachment(Base):
    __tablename__ = "bridge_session_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target: Mapped[str] = mapped_column(String, index=True, nullable=False)
    session_name: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String, index=True, nullable=False)
    storage_path: Mapped[str] = mapped_column(String, nullable=False)
    agent_path: Mapped[str] = mapped_column(String, nullable=False)
    prompt_text: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

Rationale:

- enables listing recent attachments,
- enables cleanup,
- gives auditability for agentic calls,
- allows API response reconstruction.

### 6.5 REST endpoints

#### Upload image

```http
POST /api/v1/agent-bridge/sessions/{target}/attachments
Content-Type: multipart/form-data
X-Claude-Deck-Terminal-Token: <token from GET /api/v1/agent-bridge/token>
```

Fields:

- `file`: required image file
- `template`: optional template id, default provider-specific default
- `prompt`: optional explicit prompt override containing `{path}` placeholder
- `created_by`: optional source label (`deck-ui`, `mcp`, etc.)

Response:

```json
{
  "id": 123,
  "target": "snazzyemail-85b9:0.0",
  "provider": "claude-code",
  "mime_type": "image/png",
  "size_bytes": 482103,
  "sha256": "...",
  "agent_path": "/home/juan/.claude-registry/bridge-attachments/snazzyemail-85b9/2026-06-29/185422-a1b2c3d4.png",
  "prompt_text": "Please inspect this image: /home/juan/.claude-registry/bridge-attachments/snazzyemail-85b9/2026-06-29/185422-a1b2c3d4.png",
  "created_at": "2026-06-29T18:54:22Z"
}
```

#### Paste attachment prompt into tmux

```http
POST /api/v1/agent-bridge/sessions/{target}/attachments/{attachment_id}/paste
X-Claude-Deck-Terminal-Token: <fresh token from GET /api/v1/agent-bridge/token>
```

Body:

```json
{
  "submit": false,
  "prefix": "",
  "suffix": ""
}
```

Behavior:

- validate target matches attachment,
- validate target currently exists,
- inject `prompt_text` into the tmux session,
- if `submit=true`, send Enter after the prompt.

Response:

```json
{
  "pasted": true,
  "submitted": false,
  "target": "snazzyemail-85b9:0.0"
}
```

#### List recent attachments

```http
GET /api/v1/agent-bridge/sessions/{target}/attachments
X-Claude-Deck-Terminal-Token: <fresh token from GET /api/v1/agent-bridge/token>
```

Useful for recovery and future UI.

#### Delete attachment

```http
DELETE /api/v1/agent-bridge/sessions/{target}/attachments/{attachment_id}
X-Claude-Deck-Terminal-Token: <fresh token from GET /api/v1/agent-bridge/token>
```

Delete DB row and file if the file is still under the configured attachment root.

### 6.6 Write authorization

All attachment endpoints should require the same short-lived, single-use token mechanism used by the terminal websocket. Upload, paste, and delete are write surfaces; list is read-only but exposes sensitive local file paths.

1. frontend calls `GET /api/v1/agent-bridge/token`,
2. frontend sends the returned token in `X-Claude-Deck-Terminal-Token`,
3. backend validates and consumes the token with the same TTL semantics as websocket attach.

The paste endpoint is especially sensitive because it can inject keystrokes and optionally press Enter. It must not be less protected than the terminal websocket.

REST endpoints should also perform an Origin/Host same-origin check when the request has an `Origin` header. Implement this as a request-aware helper equivalent to the websocket `_is_same_origin` logic.

### 6.7 Injection mechanism

Use `tmux send-keys -l` for REST paste endpoint, following the existing precedent in `agent_mail_service._send_tmux_inbox_check`:

```bash
tmux send-keys -t "$target" -l "$prompt_text"
sleep "$TMUX_ENTER_DELAY_SECONDS"
tmux send-keys -t "$target" Enter   # only if submit=true
```

Keep the delay between literal text injection and Enter. Agent TUIs can miss or partially process pasted text if Enter is sent immediately.

Reuse the same error semantics as `_send_tmux_inbox_check`:

- `FileNotFoundError` → `ValueError("tmux is not installed or not available")`
- `subprocess.CalledProcessError` → include the first part of stderr
- `subprocess.TimeoutExpired` → `ValueError("tmux send-keys timed out")`

Do not write the prompt through an arbitrary active websocket relay. REST injection should work even if the user is not currently attached in the browser.

The websocket relay can still support a frontend-only path later, but the REST endpoint is the more useful primitive.

### 6.8 Provider-aware prompt templates

Initial templates:

| Provider | Template |
|---|---|
| `claude-code` | `Please inspect this image: {path}` |
| `codex-cli` | `Please inspect this image: {path}` |
| `opencode-cli` | `Please inspect this image: {path}` |
| `copilot-cli` | `Please inspect this image: {path}` |
| unknown | `Please inspect this image: {path}` |

Future templates can be customized if a provider has a better file-attachment syntax.

Prompt override rules:

- reject overrides missing `{path}`,
- cap final prompt length,
- strip NUL characters,
- strip all newlines from the final `prompt_text`; embedded `\n` sent through `tmux send-keys -l` can submit text even when `submit=false`,
- do not shell-expand paths.

---

## 7. Frontend Design

### 7.1 Files to touch

Likely frontend touch points:

- `frontend/src/features/cc-bridge/TerminalView.tsx`
- `frontend/src/features/cc-bridge/useTerminal.ts`
- `frontend/src/features/cc-bridge/api.ts`
- `frontend/src/features/cc-bridge/types.ts`
- new component: `frontend/src/features/cc-bridge/ImageAttachmentDialog.tsx`

### 7.2 Clipboard detection

Add a paste handler to the terminal wrapper:

- ignore if no active `target`,
- inspect `event.clipboardData.items`,
- find image items,
- call `preventDefault()` only when handling an image,
- preserve existing text paste behavior for non-image clipboard contents.

The handler should live at the terminal pane level, not globally, so normal app text inputs keep their existing paste behavior.

### 7.3 Drag/drop detection

Add `dragover`, `dragleave`, and `drop` behavior on the terminal wrapper:

- show visual drop overlay only for image files,
- reject non-image files with a clear toast,
- support one image for MVP.

### 7.4 Confirmation dialog

Dialog state should contain:

```ts
{
  file: File
  previewUrl: string
  target: string
  session?: CCSession | null
  uploadState: 'idle' | 'uploading' | 'uploaded' | 'error'
  uploadedAttachment?: BridgeAttachment
}
```

The dialog should:

- show thumbnail preview,
- show target/session label,
- show generated prompt text after upload,
- offer `Paste reference`, `Paste and submit`, and `Cancel`.

### 7.5 Read-only mode

`TerminalView` already knows `readOnly` from `useTerminal`. Use it to disable paste actions that inject text, or to show a controlled "Switch to interactive" affordance.

### 7.6 Accessibility

- Dialog buttons must be keyboard reachable.
- Drop overlay must not trap focus.
- Error messages must be visible as text, not only toast.

---

## 8. Agentic / MCP Interface

Once REST endpoints exist, add MCP tools through a shared Deck MCP surface rather than continuing to grow a file named only for mail. Short-term implementation may still touch `backend/mcp_shim/agent_mail_server.py` because that is the installed Deck MCP shim today, but the implementation should introduce prefix-aware request helpers and keep the tool names Bridge-specific.

### 8.1 Attach existing server-side file

```python
deck_attach_image_to_bridge_session(
    target: str,
    file_path: str,
    submit: bool = False,
    prompt: str | None = None,
) -> dict
```

This is useful when an agent has already created an image file on the Deck host.

Security constraints:

- file must be under an allowed root,
- image MIME/signature validation still applies,
- copy file into the Deck attachment store instead of referencing arbitrary paths directly.

### 8.2 List attachments

```python
deck_list_bridge_attachments(target: str) -> dict
```

### 8.3 Paste existing attachment

```python
deck_paste_bridge_attachment(
    target: str,
    attachment_id: int,
    submit: bool = False,
) -> dict
```

MCP should surface backend validation errors verbatim, including file size/type and path-visibility errors.

---

## 9. Security & Privacy Considerations

### 9.1 Upload surface

Image upload is a new write surface. It must inherit existing same-origin/token assumptions and should not be exposed without the same trust boundary as Agent Bridge interactive input.

Controls:

- same-origin checks for websocket remain unchanged,
- all attachment REST endpoints require a fresh single-use terminal token,
- REST attachment endpoints reject cross-origin browser requests when `Origin` does not match `Host` or localhost,
- reject non-images,
- reject over-limit images before storing,
- generate server-side filenames,
- never write outside the configured attachment root,
- do not follow symlinks during delete/cleanup,
- do not expose raw storage paths for files outside the attachment root.

### 9.2 Prompt injection through filenames

Do not include user-supplied filenames in pasted prompts. Only include server-generated `agent_path`.

### 9.3 Sensitive images

The UI should communicate that pasted images are saved on the Deck host until cleanup/expiry.

Possible copy:

> Image will be uploaded to this Claude Deck host and saved as a temporary attachment visible to the selected tmux session.

### 9.4 Cleanup

Add a scheduled or startup cleanup task:

- delete expired DB rows and files,
- default retention: `7 days`,
- configurable via `Settings.bridge_attachment_retention_days` / `CLAUDE_DECK_BRIDGE_ATTACHMENT_RETENTION_DAYS`,
- allow manual delete from API.

---

## 10. Remote Deployment Matrix

| Deck backend | Browser | tmux/agent | Expected behavior |
|---|---|---|---|
| local host | same local browser | same host | Upload saves locally; pasted path works. |
| remote host | local browser over HTTPS/tunnel | same remote host | Upload saves remotely; pasted remote path works. |
| Docker container | browser anywhere | tmux inside same container | Container path works. |
| Docker container | browser anywhere | tmux on host | Requires bind mount + `CLAUDE_DECK_BRIDGE_ATTACHMENT_AGENT_ROOT`; otherwise block with config error. |
| host backend | browser anywhere | agent inside separate container | Requires bind mount path visible inside container; otherwise block/warn. |
| remote SSH-only tmux not on Deck host | browser anywhere | different machine | Out of scope unless Deck gains a remote file transfer backend. |

Key rule:

> The `agent_path` in the pasted prompt must be readable by the tmux agent process.

---

## 11. Implementation Plan

### Phase 1 — Backend storage and REST paste

1. Add config values in `backend/app/config.py`:
   - `bridge_attachment_dir`,
   - `bridge_attachment_agent_root`,
   - `bridge_attachment_max_bytes`,
   - `bridge_attachment_retention_days`.
2. Add `BridgeSessionAttachment` SQLAlchemy model.
3. Add Pydantic schemas:
   - `BridgeAttachmentResponse`
   - `BridgeAttachmentPasteRequest`
   - `BridgeAttachmentPasteResponse`
4. Add attachment service:
   - validate target exists via `discover_agent_sessions`,
   - validate image,
   - compute sha256,
   - save file atomically,
   - create DB row,
   - generate prompt text.
5. Add REST endpoints under `backend/app/api/v1/agent_bridge/router.py`.
6. Add terminal-token validation and request same-origin checking for REST attachment endpoints.
7. Add `tmux send-keys` injection helper with the existing Enter delay/error handling pattern.
8. Add backend tests.

### Phase 2 — Frontend paste/drop UX

1. Add API client methods in `frontend/src/features/cc-bridge/api.ts`.
2. Add `BridgeAttachment` types.
3. Add paste/drop handling in `TerminalView`.
4. Add `ImageAttachmentDialog`.
5. Respect read-only mode.
6. Add error/toast states.
7. Run targeted lint and build.

### Phase 3 — Agentic interface

1. Add MCP tool(s) for server-side file attachment and paste.
2. Add docs to the MCP tool docstrings.
3. Add shim tests.

### Phase 4 — Cleanup and polish

1. Add retention cleanup task.
2. Add list/delete UI if needed.
3. Add provider-template customization if real-world CLI testing shows better prompts.

---

## 12. Test Plan

### Backend unit/integration tests

- Upload valid PNG returns `agent_path` and persisted metadata.
- Upload rejects unsupported MIME type.
- Upload rejects oversized file.
- Upload sanitizes original filename.
- Upload rejects unknown/dead tmux target.
- Upload/list/paste/delete reject missing, expired, reused, or invalid terminal tokens.
- Paste endpoint uses `tmux send-keys -l`.
- Paste strips newlines from final prompt text.
- `submit=true` waits `TMUX_ENTER_DELAY_SECONDS` and then sends Enter.
- Docker path mapping produces correct `agent_path`.
- Delete refuses paths outside attachment root.
- Cleanup removes expired rows/files.

### Frontend tests / validation

- Pasting text still behaves as normal terminal paste.
- Pasting image opens attachment dialog.
- Dropping image opens attachment dialog.
- Dropping non-image shows error.
- Read-only terminal does not call the paste endpoint unless the user explicitly switches to interactive mode.
- `Paste reference` injects prompt without Enter.
- `Paste and submit` injects prompt with Enter.

### Manual E2E

1. Launch a Claude Code session through Agent Bridge.
2. Attach interactively.
3. Paste a PNG screenshot.
4. Confirm `Paste reference`.
5. Verify prompt appears in terminal and image path exists.
6. Press Enter manually and confirm Claude can inspect the image.
7. Repeat with `Paste and submit`.
8. Repeat against remote Deck accessed through browser.
9. Repeat with an Agent Team session to ensure session card theme changes do not affect paste behavior.

---

## 13. Open Questions for Reviewer

Resolved decisions:

- Upload before confirmation. This is the only way to preview the exact `agent_path` and `prompt_text`; abandoned uploads are handled by retention cleanup.
- Default attachment root is `~/.claude-registry/bridge-attachments`.

Remaining questions:

1. Should `submit=true` be hidden behind a setting?
2. Should attachment retention default to `24 hours` instead of `7 days`?
3. Should MVP include multiple images in one prompt?
4. Should we expose a per-provider editable prompt template in config?
5. Should Agent Bridge have a visible attachment history panel, or is API/list enough for now?

---

## 14. Recommended MVP Decision

Implement **single-image paste/drop → upload to Deck host → preview dialog → paste generated file-path prompt**.

Do not implement terminal image rendering or base64 terminal injection. Those paths are more fragile and less aligned with what the agent CLIs need.

The critical backend invariant is:

> If Deck returns an `agent_path`, the tmux agent process should be able to read it.

If that invariant cannot be satisfied for a deployment, the API should fail loudly with configuration guidance rather than pasting a broken path.
