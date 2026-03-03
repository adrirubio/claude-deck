# Claude Code Bridge — Design Document

> Deck ↔ Claude Code integration: observe, launch, orchestrate, and configure CC sessions from the browser.

**Date:** 2026-03-01
**Status:** Design complete, Stage 1 ready for implementation
**Supersedes:** Original `acp-direct-adapter.md` approach

---

## Vision

Three stages of integration between Deck and Claude Code:

| Stage | Name | What It Does |
|-------|------|-------------|
| 1 | **Observe** | Discover running CC sessions in tmux, view them live in-browser |
| 2 | **Launch & Orchestrate** | Spawn new CC sessions from Deck, send prompts to multiple sessions |
| 3 | **Meta-chat** | Chat with CC about your CC configuration, optimize settings via Deck |

---

## Key Design Decisions

1. **tmux as the session layer** — CC sessions run inside tmux sessions. Deck discovers them via tmux APIs and attaches via pty relay. No custom process management needed.

2. **xterm.js for terminal rendering** — Full-fidelity terminal in the browser. The user sees exactly what they'd see in their terminal, including CC's TUI, permission prompts, colors, and tool output.

3. **No custom CC protocol** — We do NOT invent a message protocol to talk to CC. Instead, we relay raw terminal I/O. This means every CC feature works out of the box with zero maintenance burden.

4. **Agent SDK for programmatic use only** — Stages 2-3 use the Python `claude-agent-sdk` for cases where structured programmatic control is needed (orchestration, meta-chat). The terminal view remains the primary interactive interface.

5. **Dropped "ACP" naming** — The original plan used "ACP" loosely. IBM's actual ACP protocol has merged into Google's A2A and is irrelevant to this feature. We call this the "CC Bridge."

## Why Not the Original Approach

The original scaffolding (`backend/app/services/acp/`) tried to:
- Spawn `claude --print` as a persistent subprocess
- Communicate via invented JSON messages over stdin/stdout
- Build a custom WebSocket protocol mirroring "ACP semantics"

This approach has fatal flaws:
- `claude --print` is one-shot (exits after one prompt), not interactive
- The stdin JSON protocol (`user_message`) was invented and doesn't match CC's actual interface
- Multi-turn via `--print` requires spawning a new process per prompt (~12s startup each time)
- Loses all CC TUI features (permission prompts, slash commands, visual output)

The tmux approach avoids all of these problems.

## Competitive Landscape

| Project | Approach | Limitation |
|---------|----------|-----------|
| claude-code-webui | CLI wrapper, streams responses | No multi-turn persistence |
| claude-code-desktop-remote | Full session mgmt, Cloudflare tunnel | Complex setup |
| claude-code-web | Nuxt 4, PWA | Separate app, not config-integrated |
| claude remote-control (official) | Polls Anthropic API, web/mobile client | Human-only, not programmatic |

Deck's advantage: integrated with project configs, MCP server management, hooks, permissions — the full CC configuration stack. Plus live terminal view of real sessions.

---

## Existing Codebase Context

### Sessions Feature (read-only, historical)

Deck already has a Sessions page that reads `.jsonl` transcript files from `~/.claude/projects/`. It shows:
- Session list with project, summary, message count, tool calls
- Detailed conversation view with pagination
- Dashboard stats (sessions today/week/total)

The CC Bridge adds **live session** capabilities on top of this existing historical view.

### Scaffolded Code (to be replaced)

| File | Disposition |
|------|-------------|
| `backend/app/services/acp/cc_process.py` | Replace — wrong approach (--print subprocess) |
| `backend/app/services/acp/ws_bridge.py` | Replace — custom protocol not needed |
| `backend/app/api/v1/acp/router.py` | Replace — endpoints change for tmux model |
| `backend/app/api/v1/router.py` | Update — change route registration |

---

## Stage 1: Observe — Detailed Design

### Architecture

```
┌──────────────┐   REST       ┌──────────────┐   libtmux    ┌───────┐
│  Deck React  │ ◄──────────► │   FastAPI     │ ◄──────────► │ tmux  │
│              │              │              │              │server │
│  Session List│   WebSocket  │  Pty Bridge   │   pty+fork   │       │
│  xterm.js    │ ◄──────────► │  (per attach) │ ◄──────────► │ panes │
└──────────────┘  binary I/O  └──────────────┘              └───────┘
```

### Backend

#### New Dependencies

```
libtmux          # Python API for tmux (session discovery)
# pty, fcntl, termios, struct — all stdlib
```

#### File Structure

```
backend/app/
├── api/v1/cc_bridge/
│   ├── __init__.py
│   └── router.py          # REST + WebSocket endpoints
└── services/cc_bridge/
    ├── __init__.py
    ├── discovery.py        # tmux session discovery
    └── pty_relay.py        # WebSocket ↔ pty bridge
```

#### Session Discovery (`discovery.py`)

Uses `libtmux` to find tmux panes running Claude Code:

```python
import libtmux

def discover_cc_sessions() -> list[dict]:
    """Find all tmux panes running Claude Code."""
    server = libtmux.Server()
    results = []
    for session in server.sessions:
        for window in session.windows:
            for pane in window.panes:
                cmd = pane.pane_current_command
                if _is_claude_code(cmd):
                    results.append({
                        "tmux_target": f"{session.name}:{window.index}.{pane.index}",
                        "session_name": session.name,
                        "window_name": window.name,
                        "pane_id": pane.pane_id,
                        "cwd": pane.pane_current_path,
                        "pid": pane.pane_pid,
                        "status": "active",
                    })
    return results
```

Detection heuristic: check `pane_current_command` for `claude` or `node` (CC runs as a Node process). Cross-reference with `/proc/<pid>/cmdline` for accuracy on Linux.

Also supports `capture-pane` snapshots for previews:

```python
def capture_pane_preview(target: str) -> str:
    """Capture current visible content of a tmux pane."""
    result = subprocess.run(
        ['tmux', 'capture-pane', '-t', target, '-p', '-e'],
        capture_output=True, text=True
    )
    return result.stdout
```

#### Pty Relay (`pty_relay.py`)

Bridges a tmux pane to a WebSocket via a pseudo-terminal:

1. `pty.openpty()` creates master/slave fd pair
2. `subprocess.Popen(['tmux', 'attach-session', '-t', target], stdin=slave, stdout=slave, stderr=slave, preexec_fn=os.setsid)`
3. `asyncio.get_event_loop().add_reader(master_fd, callback)` for event-driven, non-blocking reads
4. WebSocket binary frames relay pty output to xterm.js
5. WebSocket text frames relay user input to pty (when not read-only)
6. Resize messages handled via `ioctl(fd, TIOCSWINSZ, struct.pack(...))`

Read-only mode: accept the WebSocket, relay output, but discard any input frames.

#### API Endpoints (`router.py`)

All under `/api/v1/cc-bridge`:

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/sessions` | List discovered CC sessions in tmux |
| `GET` | `/sessions/{target}/preview` | Capture-pane text snapshot |
| `GET` | `/token` | Generate one-time WebSocket auth token |
| `WS` | `/sessions/{target}/terminal` | Attach to session via pty relay |

The `{target}` parameter is the tmux target string (e.g., `mysession:0.0`), URL-encoded.

#### WebSocket Protocol

Minimal — mostly raw bytes:

| Direction | Type | Content |
|-----------|------|---------|
| Server → Client | Binary | Raw pty output bytes |
| Client → Server | Text | User keystrokes (forwarded to pty) |
| Client → Server | Text (JSON) | `{"type": "resize", "cols": N, "rows": N}` |
| Server → Client | Text (JSON) | `{"type": "error", "message": "..."}` |

Text frames that parse as JSON with a `type` field are control messages. All other text frames are terminal input.

#### Security

- **Origin validation** — reject WebSocket connections from origins other than Deck's frontend (`localhost:5173`)
- **One-time token** — frontend fetches via `GET /cc-bridge/token`, passes as `?token=` query param. Expires after 30 seconds, single-use.
- **Localhost only** — Deck already binds to `127.0.0.1`
- **Read-only default** — attach in read-only mode unless user explicitly toggles interactive

#### Lifecycle

Wire into FastAPI's `lifespan` context manager:
- Track active pty relay connections
- On shutdown, close all WebSocket connections and terminate `tmux attach` subprocesses
- When the tmux pane exits, detect EOF on the master fd and close the WebSocket gracefully

### Frontend

#### New Dependencies

```
@xterm/xterm           # Terminal emulator (v6.x)
@xterm/addon-fit       # Auto-resize to container
@xterm/addon-webgl     # GPU-accelerated rendering
@xterm/addon-web-links # Clickable URLs
```

#### File Structure

```
frontend/src/features/cc-bridge/
├── CCBridgePage.tsx       # Main page — session list + terminal panel
├── SessionList.tsx        # Discovered CC sessions as cards
├── SessionCard.tsx        # Single session card
├── TerminalView.tsx       # xterm.js terminal component
├── useTerminal.ts         # Hook: WebSocket lifecycle, xterm instance, resize
├── useCCSessions.ts       # Hook: polls GET /cc-bridge/sessions
├── api.ts                 # API client functions
└── types.ts               # TypeScript types
```

#### Page Layout

```
┌─────────────────────────────────────────────────┐
│  CC Sessions (3 active)                    [⟳]  │
├──────────┬──────────────────────────────────────┤
│          │                                      │
│ session1 │                                      │
│ ~/proj-a │     xterm.js terminal view           │
│ ● active │     (attached to selected session)   │
│          │                                      │
│ session2 │                                      │
│ ~/proj-b │                                      │
│ ● idle   │                                      │
│          │                                      │
│ session3 │                                      │
│ ~/proj-c │                                      │
│ ○ busy   │                                      │
│          │                                      │
├──────────┴──────────────────────────────────────┤
│ Read-only ◉  Interactive ○       [Detach]       │
└─────────────────────────────────────────────────┘
```

- Left sidebar: clickable session cards, auto-refreshed via polling (5s interval)
- Main area: xterm.js terminal, connects when a session is clicked
- Bottom bar: read-only/interactive toggle, detach button
- Session cards show: tmux session name, working directory, status indicator

#### Terminal Hook (`useTerminal.ts`)

Manages:
- xterm.js `Terminal` instance creation and addon loading (fit, webgl, web-links)
- WebSocket connection with token auth
- Binary frame handling (pty output → `term.write()`)
- User input forwarding (`term.onData()` → WebSocket text frame)
- Resize events via `ResizeObserver` → `fitAddon.fit()` → send resize control message
- Read-only mode (suppress `term.onData` forwarding)
- Cleanup on unmount (close WebSocket, dispose terminal)
- Reconnection on disconnect (with backoff)

#### Navigation

Add "CC Bridge" to Deck's sidebar, alongside the existing "Sessions" (transcripts) page. Consider grouping under a "Claude Code" section.

### What Stage 1 Does NOT Include (deferred)

- Spawning new CC sessions from Deck
- Sending programmatic prompts
- Multi-session orchestration
- Agent SDK integration
- Meta-chat about configuration
- Session naming/labeling in Deck's database
- Dashboard integration (session count widget)

---

## Stage 2: Launch & Orchestrate (future)

**Launch:** `tmux new-session -d -s deck-<name> 'claude --resume <id>'` from Deck UI. User picks a project directory, Deck creates the tmux session and shows it in the terminal view.

**Orchestrate:** Two modes:
- Interactive: user types into a session via the terminal view
- Programmatic: Agent SDK `query()` with `resume` for structured multi-session operations (e.g., "run this across all 3 projects and collect results")

The ~12s startup per Agent SDK call is acceptable for orchestration since these are background/batch operations, not interactive.

## Stage 3: Meta-chat (future)

A dedicated CC instance with:
- System prompt aware of Deck's config structure
- MCP servers exposing Deck's API (configs, hooks, permissions, MCP servers)
- Chat UI in Deck for asking questions like "optimise my hooks" or "set up a new project with my standard config"

Could use either the terminal view (spawn `claude` with custom args in tmux) or a richer chat interface built with the Agent SDK.

---

## Implementation Order (Stage 1)

1. Backend: `discovery.py` — tmux session discovery via libtmux
2. Backend: `pty_relay.py` — pty bridge with asyncio event-driven reads
3. Backend: `router.py` — REST endpoints + WebSocket endpoint
4. Frontend: `useCCSessions.ts` + `SessionList.tsx` + `SessionCard.tsx`
5. Frontend: `useTerminal.ts` + `TerminalView.tsx` (xterm.js + WebSocket)
6. Frontend: `CCBridgePage.tsx` — compose the page layout
7. Integration: sidebar navigation, route registration
8. Security: origin validation, one-time token auth
9. Polish: error states, reconnection, loading indicators, read-only toggle
