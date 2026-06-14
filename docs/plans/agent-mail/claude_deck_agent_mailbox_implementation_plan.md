# Claude Deck Agent Mailbox — Codex CLI Implementation Plan

**Target repository:** `https://github.com/adrirubio/claude-deck`
**Feature name:** Agent Mailbox, also called Agent Mesh / Deck Bus in this plan
**Audience:** Codex CLI or another coding agent implementing the feature in the Claude Deck codebase
**Primary goal:** Let local Claude Code and Codex CLI agent instances that Claude Deck can observe gain controlled visibility of each other, send messages, coordinate work, reserve files, and leave a local audit trail.

---

## 0. Copy/paste prompt for Codex CLI

Use the following as the direct prompt to Codex CLI after placing this file at the root of the Claude Deck repository.

```text
You are implementing the “Agent Mailbox” feature in Claude Deck.

Read this entire implementation plan first. Then inspect the current repository before editing. Implement incrementally in small, reviewable commits or work chunks. Preserve Claude Deck’s local-only trust model. Reuse existing backend/frontend patterns for services, routers, SQLAlchemy models, Pydantic schemas, React routes, hooks, MCP server management, Agent Bridge, Presence, and configuration backups.

Do not silently overwrite user configuration files. Any installer that modifies ~/.claude.json, ~/.claude/settings.json, .claude/settings.json, .mcp.json, or ~/.codex/config.toml must use existing Claude Deck config-writing/backup patterns and must expose a preview/diff or explicit confirmation path in the UI/API.

Build the MVP first:
1. Backend mailbox data model and REST API.
2. Observed-agent sync from Agent Bridge.
3. Connected-agent registration/heartbeat API.
4. Agent-facing MCP stdio server exposing core mailbox tools.
5. Claude Code hook integration for SessionStart, SessionEnd, Notification, PostToolUse, and optional PreToolUse lease checks.
6. Frontend Agent Mailbox page with Agents, Threads, Coordination, and Install/Coverage views.
7. Tests and docs.

Avoid Phase 2 features until the MVP acceptance criteria in this plan pass.
```

---

## 1. Product definition

Claude Deck currently acts as a local control panel for AI coding agents: configuration, MCP servers, hooks, session transcripts, Agent Bridge, and tmux-based live sessions. The Agent Mailbox feature should make Claude Deck a **local coordination layer**.

### User-facing promise

> Any Claude Code or Codex CLI session visible in Claude Deck can become an addressable local agent. Agents can see who else is running, send messages, hand off tasks, reserve paths, report status, and leave an auditable local history.

### Core experience

A user has several local terminals/tmux panes running Claude Code and Codex CLI. Claude Deck’s Agent Bridge already sees those sessions. Agent Mailbox adds:

- An **Agent Mailbox** page in the Claude Deck UI.
- Presence states: `observed`, `connected`, `offline`.
- Agent-to-agent messages and inboxes.
- Broadcast messages per project.
- Simple task handoff messages.
- Advisory file/path leases.
- One-click installation of the mailbox MCP server and Claude Code hooks.
- Agent-facing MCP tools so agents can ask:
  - “Who else is working in this repo?”
  - “Do I have messages?”
  - “Tell the frontend agent I touched auth.”
  - “Reserve `src/auth/**` while I refactor.”
  - “Check whether anyone else has a lease on these files.”

### Important distinction

Claude Deck should **not** make agents talk directly to each other. Claude Deck should own the shared state. Agents should talk to the local Claude Deck backend via a mailbox MCP server and lifecycle hooks.

```text
Claude Code / Codex agent
        ↓ MCP tools + hooks
Claude Deck Agent Mailbox backend
        ↓ SQLite + event stream
Claude Deck UI + Agent Bridge
```

---

## 2. Design principles

1. **Local-only by default**
   Do not introduce cloud services, remote accounts, telemetry, hosted relay services, or external dependencies for coordination.

2. **Claude Deck is the source of truth**
   The mailbox state belongs to Claude Deck’s backend and SQLite database. MCP shims and hooks are clients, not durable state stores.

3. **Observed first, connected second**
   Agent Bridge can passively discover tmux sessions. Those become `observed` mailbox agents. MCP/hook registration upgrades them to `connected`.

4. **No surprise terminal injection**
   Do not type commands into live agent panes to install, reload, or activate mailbox tooling. Installation should be explicit through UI/API flows.

5. **Safe config mutations**
   Claude Deck edits real local Claude Code and Codex CLI files. Any installer must use existing backup/preview/safe-write conventions.

6. **Advisory coordination before enforcement**
   File reservations should start as advisory warnings. Blocking via PreToolUse hooks can be a user-enabled strict mode later or a guarded v1.1 setting.

7. **No raw transcript sharing to agents by default**
   Agents should communicate through messages. The human can inspect transcripts in Claude Deck, but mailbox MCP tools should not expose other agents’ transcript contents unless a later explicit setting enables it.

8. **Stale state must fail soft**
   If a hook or MCP shim cannot reach Claude Deck, Claude Code/Codex CLI should continue working. Hooks should not break normal agent work unless strict lease-blocking is explicitly enabled.

---

## 3. Current Claude Deck seams to reuse

Before implementing, inspect the current repository. The plan assumes the following architecture based on current public Claude Deck docs and repo layout:

- Backend:
  - Python/FastAPI.
  - SQLite via SQLAlchemy + aiosqlite.
  - API routes mounted under `/api/v1`.
  - Existing route modules for MCP, hooks, agents, sessions, presence, and Agent Bridge.
  - Existing services such as `mcp_service`, `hook_service`, `agent_bridge`, `presence_service`, and config utilities.
- Frontend:
  - React + TypeScript + Vite.
  - Existing pages for MCP servers, hooks, agents, sessions, and Agent Bridge.
- Agent Bridge:
  - Discovers provider-aware Claude Code and Codex CLI sessions in tmux.
  - Exposes metadata such as provider, tmux target, cwd, pane ID, pid, and status.
- MCP:
  - Claude Deck already manages MCP servers across user and project scopes.
  - It supports transports such as stdio, HTTP, and SSE.
- Hooks:
  - Claude Deck already manages Claude Code hook settings.
  - Anthropic Claude Code supports command hooks and HTTP hooks at lifecycle events including SessionStart, SessionEnd, Notification, PreToolUse, and PostToolUse.

Where names differ, prefer the actual repository patterns over names in this plan.

---

## 4. MVP scope

### Include in MVP

#### Backend

- SQLAlchemy models for mailbox agents, threads, messages, receipts, path leases, and events.
- REST API under `/api/v1/agent-mailbox`.
- Optional local capability token for agent/hook endpoints.
- Service logic to:
  - Upsert observed agents from Agent Bridge.
  - Register connected agents.
  - Heartbeat connected agents.
  - List agents by project.
  - Send/read/reply/ack messages.
  - Create/list/release path leases.
  - Detect lease conflicts.
  - Ingest hook events.

#### MCP

- A local stdio MCP server/shim named `claude-deck-mailbox`.
- Core MCP tools:
  - `deck_whoami`
  - `deck_list_agents`
  - `deck_set_status`
  - `deck_send_message`
  - `deck_read_inbox`
  - `deck_reply`
  - `deck_ack_message`
  - `deck_create_handoff`
  - `deck_reserve_paths`
  - `deck_release_paths`
  - `deck_list_path_leases`
  - `deck_check_path_conflicts`

#### Hooks

- Claude Code hooks for:
  - `SessionStart`
  - `SessionEnd`
  - `Notification`
  - `PostToolUse`
  - optional `PreToolUse` lease warnings/blocks
- A command wrapper is acceptable for v1. Use HTTP hooks only if the current Claude Deck hook service/UI already supports them or can be extended safely.

#### Frontend

- New Agent Mailbox page.
- Agents view.
- Threads/inbox view.
- Coordination/leases view.
- Install/Coverage view.
- Agent Bridge badge integration if low-risk.

#### Tests/docs

- Backend unit and API tests.
- MCP shim smoke tests or protocol-level tests where feasible.
- Hook wrapper tests.
- Frontend build/type checks.
- User docs.

### Exclude from MVP

- Cross-machine or LAN mesh.
- Cloud relay.
- Direct transcript sharing between agents.
- Autonomous typing into tmux panes.
- Hard file locking as the default behavior.
- Full Codex CLI hook parity if Codex does not support equivalent hooks yet.
- Complex task scheduler or planner.
- Rich attachments/binary blobs.
- Git-aware branch/worktree orchestration.

---

## 5. Terminology and states

### Agent instance

A running or recently observed coding-agent session. It may be a Claude Code session, a Codex CLI session, or an unknown provider discovered from tmux.

### Observed agent

Claude Deck sees a session through Agent Bridge, but that session has not connected through the mailbox MCP server or hooks.

### Connected agent

The session has registered or heartbeated through MCP/hook endpoints and can use mailbox tools.

### Offline agent

A previously known agent whose heartbeat has expired or whose session ended.

### Project

A filesystem path used to group agents, messages, threads, and leases. Prefer normalized absolute paths.

### Thread

A conversation with a subject, project scope, and messages.

### Message

A markdown body sent by an agent or the human UI to one or more agents.

### Receipt

Per-agent read/ack state for a message.

### Path lease

An advisory claim over one or more project-relative path globs for a TTL.

---

## 6. Architecture

```text
┌────────────────────────────────────────────────────────────┐
│ Claude Deck frontend                                       │
│                                                            │
│  /agent-mailbox page                                       │
│  AgentBridge cards with mailbox badges                     │
│  Threads, inbox, leases, install coverage                  │
└──────────────────────────────┬─────────────────────────────┘
                               │ REST / WS or SSE
┌──────────────────────────────▼─────────────────────────────┐
│ Claude Deck backend                                        │
│                                                            │
│  api/v1/agent_mailbox.py                                   │
│  services/agent_mailbox_service.py                         │
│  services/agent_mailbox_auth.py                            │
│  models: AgentMailbox*                                     │
│                                                            │
│  Inputs: Agent Bridge, Presence, MCP shim, hooks            │
│  Storage: SQLite                                           │
└───────────────┬──────────────────────┬─────────────────────┘
                │                      │
      MCP stdio │                      │ hook command/http
                │                      │
┌───────────────▼─────────────┐ ┌──────▼─────────────────────┐
│ Claude Code / Codex CLI     │ │ Claude Code hook events     │
│ sessions                    │ │ SessionStart/PostToolUse/etc│
│                             │ │                             │
│ MCP tools: list/send/read   │ │ lifecycle + activity events │
└─────────────────────────────┘ └────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│ Agent Bridge                                               │
│ provider-aware tmux discovery: Claude Code + Codex CLI      │
└────────────────────────────────────────────────────────────┘
```

---

## 7. Data model

Use the existing SQLAlchemy style in `backend/app/models`. If the project keeps all DB models in a single file, add these models there. If newer modules exist, add a mailbox-specific module and import it where metadata is initialized.

Prefer string constants over database enums for SQLite simplicity unless the existing project already uses enum columns.

### 7.1 `AgentMailboxAgent`

Purpose: Represents both observed and connected agents.

Recommended columns:

```python
class AgentMailboxAgent(Base):
    __tablename__ = "agent_mailbox_agents"

    id = Column(String, primary_key=True)  # uuid/ulid string

    # Identity and correlation
    provider = Column(String, nullable=False, default="unknown")  # claude-code, codex-cli, unknown
    display_name = Column(String, nullable=True)
    role = Column(String, nullable=True)
    agent_label = Column(String, nullable=True)

    # Project/session context
    project_path = Column(String, nullable=True, index=True)
    cwd = Column(String, nullable=True)
    session_id = Column(String, nullable=True, index=True)
    transcript_path = Column(String, nullable=True)

    # Agent Bridge / tmux correlation
    tmux_target = Column(String, nullable=True, index=True)
    tmux_session = Column(String, nullable=True)
    tmux_window = Column(String, nullable=True)
    pane_id = Column(String, nullable=True, index=True)
    pid = Column(Integer, nullable=True)

    # Status
    mailbox_status = Column(String, nullable=False, default="observed")  # observed, connected, offline
    current_status = Column(String, nullable=False, default="idle")      # idle, busy, waiting, blocked, error, offline
    status_note = Column(Text, nullable=True)

    supports_mcp = Column(Boolean, nullable=False, default=False)
    supports_hooks = Column(Boolean, nullable=False, default=False)

    # Stable key for deduping observed sessions when no mailbox id exists
    observed_key = Column(String, nullable=True, unique=True, index=True)

    # Client metadata
    client_name = Column(String, nullable=True)
    client_version = Column(String, nullable=True)
    hostname = Column(String, nullable=True)
    username = Column(String, nullable=True)

    last_seen_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
```

Indexes:

```text
project_path
session_id
tmux_target
pane_id
observed_key unique
last_seen_at
mailbox_status
```

Correlation rules:

1. If `session_id` matches an existing agent, update that row.
2. Else if `pane_id` + `tmux_target` match, update that row.
3. Else if `observed_key` matches, update that row.
4. Else create a new row.

Recommended `observed_key` formula:

```text
provider + ":" + normalized_cwd + ":" + tmux_target + ":" + pane_id
```

Fallback if tmux metadata is missing:

```text
provider + ":" + normalized_cwd + ":" + pid
```

### 7.2 `AgentMailboxThread`

```python
class AgentMailboxThread(Base):
    __tablename__ = "agent_mailbox_threads"

    id = Column(String, primary_key=True)
    project_path = Column(String, nullable=True, index=True)

    subject = Column(String, nullable=False)
    thread_type = Column(String, nullable=False, default="message")  # message, handoff, broadcast, system
    created_by_agent_id = Column(String, ForeignKey("agent_mailbox_agents.id"), nullable=True)

    is_archived = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
```

### 7.3 `AgentMailboxMessage`

```python
class AgentMailboxMessage(Base):
    __tablename__ = "agent_mailbox_messages"

    id = Column(String, primary_key=True)
    thread_id = Column(String, ForeignKey("agent_mailbox_threads.id"), nullable=False, index=True)

    sender_agent_id = Column(String, ForeignKey("agent_mailbox_agents.id"), nullable=True)
    sender_kind = Column(String, nullable=False, default="agent")  # agent, human, system

    recipient_agent_id = Column(String, ForeignKey("agent_mailbox_agents.id"), nullable=True, index=True)
    recipient_role = Column(String, nullable=True, index=True)
    is_broadcast = Column(Boolean, nullable=False, default=False)

    priority = Column(String, nullable=False, default="normal")  # low, normal, high, urgent
    requires_ack = Column(Boolean, nullable=False, default=False)

    body_markdown = Column(Text, nullable=False)
    metadata_json = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, index=True)
```

### 7.4 `AgentMailboxReceipt`

```python
class AgentMailboxReceipt(Base):
    __tablename__ = "agent_mailbox_receipts"

    id = Column(String, primary_key=True)
    message_id = Column(String, ForeignKey("agent_mailbox_messages.id"), nullable=False, index=True)
    agent_id = Column(String, ForeignKey("agent_mailbox_agents.id"), nullable=False, index=True)

    delivered_at = Column(DateTime(timezone=True), nullable=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    acked_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False)
```

Unique constraint:

```text
(message_id, agent_id)
```

### 7.5 `AgentMailboxPathLease`

```python
class AgentMailboxPathLease(Base):
    __tablename__ = "agent_mailbox_path_leases"

    id = Column(String, primary_key=True)

    agent_id = Column(String, ForeignKey("agent_mailbox_agents.id"), nullable=False, index=True)
    project_path = Column(String, nullable=False, index=True)

    path_glob = Column(String, nullable=False)
    normalized_path_glob = Column(String, nullable=False, index=True)

    purpose = Column(Text, nullable=True)
    lease_status = Column(String, nullable=False, default="active")  # active, released, expired
    enforcement_mode = Column(String, nullable=False, default="advisory")  # advisory, warn, block

    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    released_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
```

### 7.6 `AgentMailboxEvent`

```python
class AgentMailboxEvent(Base):
    __tablename__ = "agent_mailbox_events"

    id = Column(String, primary_key=True)
    agent_id = Column(String, ForeignKey("agent_mailbox_agents.id"), nullable=True, index=True)

    project_path = Column(String, nullable=True, index=True)
    event_type = Column(String, nullable=False, index=True)  # registered, heartbeat, message_sent, lease_created, hook_post_tool_use, etc.
    payload_json = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, index=True)
```

### 7.7 Migration/init strategy

Claude Deck may not have Alembic. If it initializes tables on startup using SQLAlchemy metadata, import the new models before `create_all`. If it has its own migration/versioning pattern, follow it.

Add a safe, idempotent startup path:

- Existing databases should start without manual migration.
- New tables should be created if missing.
- If adding columns to existing tables is necessary, use a safe schema upgrade function matching existing patterns.

Do not add destructive migrations.

---

## 8. Pydantic/API schemas

Create request/response schemas in the existing schema location. Names are suggestions.

### Core enums as literals

```python
MailboxStatus = Literal["observed", "connected", "offline"]
AgentStatus = Literal["idle", "busy", "waiting", "blocked", "error", "offline"]
MessagePriority = Literal["low", "normal", "high", "urgent"]
ThreadType = Literal["message", "handoff", "broadcast", "system"]
LeaseStatus = Literal["active", "released", "expired"]
LeaseEnforcementMode = Literal["advisory", "warn", "block"]
```

### Agent schemas

```python
class AgentRegisterRequest(BaseModel):
    provider: str | None = None
    display_name: str | None = None
    role: str | None = None
    project_path: str | None = None
    cwd: str | None = None
    session_id: str | None = None
    transcript_path: str | None = None
    tmux_target: str | None = None
    pane_id: str | None = None
    pid: int | None = None
    client_name: str | None = None
    client_version: str | None = None
    hostname: str | None = None
    username: str | None = None

class AgentHeartbeatRequest(BaseModel):
    agent_id: str
    status: AgentStatus | None = None
    status_note: str | None = None
    cwd: str | None = None
    project_path: str | None = None
    session_id: str | None = None

class AgentResponse(BaseModel):
    id: str
    provider: str
    display_name: str | None
    role: str | None
    project_path: str | None
    cwd: str | None
    session_id: str | None
    tmux_target: str | None
    pane_id: str | None
    pid: int | None
    mailbox_status: MailboxStatus
    current_status: AgentStatus
    status_note: str | None
    supports_mcp: bool
    supports_hooks: bool
    last_seen_at: datetime | None
    unread_count: int = 0
    active_lease_count: int = 0
```

### Message schemas

```python
class SendMessageRequest(BaseModel):
    sender_agent_id: str | None = None  # nullable for human/system messages
    recipient_agent_id: str | None = None
    recipient_role: str | None = None
    broadcast: bool = False
    project_path: str | None = None
    thread_id: str | None = None
    subject: str | None = None
    body_markdown: str
    priority: MessagePriority = "normal"
    requires_ack: bool = False
    thread_type: ThreadType = "message"

class MessageResponse(BaseModel):
    id: str
    thread_id: str
    sender_agent_id: str | None
    sender_kind: str
    recipient_agent_id: str | None
    recipient_role: str | None
    is_broadcast: bool
    priority: MessagePriority
    requires_ack: bool
    body_markdown: str
    created_at: datetime
    read_at: datetime | None = None
    acked_at: datetime | None = None
```

### Lease schemas

```python
class ReservePathsRequest(BaseModel):
    agent_id: str
    project_path: str
    paths: list[str]
    purpose: str | None = None
    ttl_minutes: int = 90
    enforcement_mode: LeaseEnforcementMode = "advisory"

class PathLeaseResponse(BaseModel):
    id: str
    agent_id: str
    project_path: str
    path_glob: str
    purpose: str | None
    lease_status: LeaseStatus
    enforcement_mode: LeaseEnforcementMode
    expires_at: datetime
    created_at: datetime

class PathConflictResponse(BaseModel):
    has_conflicts: bool
    conflicts: list[PathLeaseResponse]
```

### Hook schemas

```python
class HookEventRequest(BaseModel):
    hook_event_name: str
    session_id: str | None = None
    cwd: str | None = None
    project_path: str | None = None
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_response: dict[str, Any] | None = None
    notification_message: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)
```

---

## 9. Backend service

Create `backend/app/services/agent_mailbox_service.py`.

### 9.1 Public service methods

Implement roughly this surface:

```python
class AgentMailboxService:
    async def sync_observed_agents_from_agent_bridge(
        self,
        db: AsyncSession,
        project_path: str | None = None,
    ) -> list[AgentMailboxAgent]: ...

    async def list_agents(
        self,
        db: AsyncSession,
        project_path: str | None = None,
        include_observed: bool = True,
        include_offline: bool = False,
    ) -> list[AgentMailboxAgent]: ...

    async def register_agent(
        self,
        db: AsyncSession,
        request: AgentRegisterRequest,
    ) -> AgentMailboxAgent: ...

    async def heartbeat_agent(
        self,
        db: AsyncSession,
        request: AgentHeartbeatRequest,
    ) -> AgentMailboxAgent: ...

    async def set_status(
        self,
        db: AsyncSession,
        agent_id: str,
        status: str,
        note: str | None = None,
    ) -> AgentMailboxAgent: ...

    async def send_message(
        self,
        db: AsyncSession,
        request: SendMessageRequest,
        sender_kind: str = "agent",
    ) -> AgentMailboxMessage: ...

    async def list_threads(
        self,
        db: AsyncSession,
        project_path: str | None = None,
        agent_id: str | None = None,
        include_archived: bool = False,
    ) -> list[ThreadWithSummary]: ...

    async def read_inbox(
        self,
        db: AsyncSession,
        agent_id: str,
        unread_only: bool = False,
        limit: int = 50,
    ) -> list[MessageResponse]: ...

    async def mark_read(
        self,
        db: AsyncSession,
        message_id: str,
        agent_id: str,
    ) -> None: ...

    async def ack_message(
        self,
        db: AsyncSession,
        message_id: str,
        agent_id: str,
    ) -> None: ...

    async def reserve_paths(
        self,
        db: AsyncSession,
        request: ReservePathsRequest,
    ) -> ReservePathsResult: ...

    async def list_path_leases(
        self,
        db: AsyncSession,
        project_path: str,
        agent_id: str | None = None,
        active_only: bool = True,
    ) -> list[AgentMailboxPathLease]: ...

    async def release_path_leases(
        self,
        db: AsyncSession,
        agent_id: str,
        lease_ids: list[str],
    ) -> list[AgentMailboxPathLease]: ...

    async def check_path_conflicts(
        self,
        db: AsyncSession,
        project_path: str,
        paths: list[str],
        requesting_agent_id: str | None = None,
    ) -> PathConflictResponse: ...

    async def ingest_hook_event(
        self,
        db: AsyncSession,
        event: HookEventRequest,
    ) -> HookIngestResult: ...
```

### 9.2 Agent Bridge sync

This is the main “detected by Claude Deck” mechanism.

Implementation sketch:

```python
async def sync_observed_agents_from_agent_bridge(db, project_path=None):
    sessions = await existing_agent_bridge_service.list_sessions(provider=None)

    for session in sessions:
        if project_path and normalize(session.cwd) != normalize(project_path):
            # If projects can be nested, use existing project matching logic instead.
            continue

        observed_key = build_observed_key(session)
        agent = await find_by_session_or_tmux_or_observed_key(db, session, observed_key)

        if not agent:
            agent = AgentMailboxAgent(id=new_id(), observed_key=observed_key, ...)

        agent.provider = session.provider or "unknown"
        agent.cwd = session.cwd
        agent.project_path = derive_project_path(session.cwd)
        agent.tmux_target = session.tmux_target
        agent.pane_id = session.pane_id
        agent.pid = session.pid

        if agent.mailbox_status != "connected":
            agent.mailbox_status = "observed"
            agent.current_status = map_bridge_status(session.status)

        agent.last_seen_at = now()
        agent.updated_at = now()

    await db.commit()
```

Notes:

- Do not call the HTTP endpoint from the service if a Python service class exists. Import/reuse the existing service.
- If Agent Bridge service methods are synchronous, adapt accordingly.
- Ensure this does not spawn tmux commands too frequently. Cache/sync on page load and on a reasonable interval.

### 9.3 Stale status

Add TTL settings:

```python
CONNECTED_HEARTBEAT_TTL_SECONDS = 120
OBSERVED_TTL_SECONDS = 300
LEASE_SWEEP_INTERVAL_SECONDS = 60
```

When listing agents:

- If `mailbox_status == connected` and `last_seen_at < now - heartbeat_ttl`, mark as `offline`.
- If `mailbox_status == observed` and Agent Bridge no longer reports it for `observed_ttl`, mark as `offline`.
- Keep offline rows for history.

### 9.4 Message delivery rules

Message targeting options:

1. Direct to `recipient_agent_id`.
2. Role-based to `recipient_role`.
3. Broadcast to all agents in `project_path`.
4. Human/system messages with `sender_agent_id = null`.

For direct messages:

- Create one receipt for the recipient.

For role messages:

- Create receipts for currently known agents in that role/project.
- Also keep `recipient_role` on the message for later display.

For broadcast:

- Create receipts for every active agent in that project except sender.
- If no recipients exist, still store the message as project broadcast.

Subject behavior:

- If `thread_id` is provided, append to that thread.
- Else create a thread with `subject`.
- If `subject` is missing for a new thread, derive a short subject from first line of body.

### 9.5 Handoffs

A handoff is a typed message, not a separate task scheduler in MVP.

`deck_create_handoff` should create:

- `thread_type = "handoff"`
- `requires_ack = true`
- Metadata:
  - `files`
  - `summary`
  - `next_steps`
  - `from_agent_id`
  - `to_agent_id` or `to_role`

Example body:

```markdown
## Handoff

**Summary:** Refactored login/session boundary.

**Files touched:**
- `src/auth/session.ts`
- `backend/app/api/v1/auth.py`

**Next steps:**
1. Update frontend form wiring.
2. Run auth tests.
3. Review error states.
```

### 9.6 Path lease conflict logic

Use project-relative normalized POSIX paths for comparisons. Handle absolute paths by converting them under `project_path` when possible.

Basic approach:

- Normalize both lease globs and requested paths.
- Expire stale active leases before checking.
- Exclude leases owned by the requesting agent.
- A conflict exists if:
  - the requested path matches the lease glob; or
  - the lease path matches the requested glob; or
  - simple parent/child overlap can be detected.

Implement with `fnmatch.fnmatchcase` and extra helper functions. This will not be perfect. It is acceptable for MVP if tests cover common cases.

Helper examples:

```python
def normalize_project_path(project_path: str, path: str) -> str:
    # Convert to POSIX-ish relative path where possible.
    ...

def glob_overlaps(a: str, b: str) -> bool:
    # True for exact match, parent/child dirs, and fnmatch either direction.
    ...
```

Conflict examples to test:

```text
Lease: src/auth/**
Request: src/auth/session.ts        conflict
Lease: src/auth/session.ts
Request: src/auth/**                conflict
Lease: backend/**
Request: frontend/**                no conflict
Lease: README.md
Request: README.md                  conflict
Lease: **/*.py
Request: backend/app/main.py        conflict
```

---

## 10. Backend API

Create `backend/app/api/v1/agent_mailbox.py` and include it from `backend/app/api/v1/router.py` under prefix `/agent-mailbox`.

### 10.1 Human/UI endpoints

These can rely on Claude Deck’s local-only UI trust model.

```http
GET /api/v1/agent-mailbox/agents
Query:
  project_path?: string
  include_observed?: bool = true
  include_offline?: bool = false
  sync_observed?: bool = true

Response:
  { "agents": AgentResponse[] }
```

```http
GET /api/v1/agent-mailbox/threads
Query:
  project_path?: string
  agent_id?: string
  include_archived?: bool = false

Response:
  { "threads": ThreadSummary[] }
```

```http
GET /api/v1/agent-mailbox/threads/{thread_id}/messages

Response:
  { "messages": MessageResponse[] }
```

```http
POST /api/v1/agent-mailbox/messages

Body:
  SendMessageRequest

Response:
  MessageResponse
```

```http
POST /api/v1/agent-mailbox/messages/{message_id}/read
Body:
  { "agent_id": "..." }

POST /api/v1/agent-mailbox/messages/{message_id}/ack
Body:
  { "agent_id": "..." }
```

```http
GET /api/v1/agent-mailbox/leases
Query:
  project_path: string
  agent_id?: string
  active_only?: bool = true

POST /api/v1/agent-mailbox/leases
Body:
  ReservePathsRequest

DELETE /api/v1/agent-mailbox/leases/{lease_id}
Body or query:
  agent_id: string
```

```http
POST /api/v1/agent-mailbox/leases/check-conflicts
Body:
  {
    "project_path": "...",
    "paths": ["src/auth/session.ts"],
    "requesting_agent_id": "..."
  }
```

### 10.2 Agent/hook endpoints

These should require a local capability token unless the project already has a better local-auth pattern.

```http
POST /api/v1/agent-mailbox/register
Headers:
  X-Claude-Deck-Mailbox-Token: <token>
Body:
  AgentRegisterRequest
```

```http
POST /api/v1/agent-mailbox/heartbeat
Headers:
  X-Claude-Deck-Mailbox-Token: <token>
Body:
  AgentHeartbeatRequest
```

```http
POST /api/v1/agent-mailbox/status
Headers:
  X-Claude-Deck-Mailbox-Token: <token>
Body:
  {
    "agent_id": "...",
    "status": "busy",
    "note": "Working on auth refactor"
  }
```

```http
POST /api/v1/agent-mailbox/hooks/event
Headers:
  X-Claude-Deck-Mailbox-Token: <token>
Body:
  HookEventRequest
```

Convenience hook aliases:

```http
POST /api/v1/agent-mailbox/hooks/session-start
POST /api/v1/agent-mailbox/hooks/session-end
POST /api/v1/agent-mailbox/hooks/notification
POST /api/v1/agent-mailbox/hooks/pre-tool-use
POST /api/v1/agent-mailbox/hooks/post-tool-use
```

All can normalize into `hooks/event`.

### 10.3 Event stream

Use whichever real-time pattern is already present. If none exists, start with polling.

Phase 1 optional endpoint:

```http
GET /api/v1/agent-mailbox/events
Query:
  project_path?: string
  since?: iso datetime
  limit?: int = 100
```

Phase 2 optional:

```text
WS /api/v1/agent-mailbox/ws
```

### 10.4 Install/coverage endpoints

```http
GET /api/v1/agent-mailbox/install/status
Query:
  project_path?: string
  scope?: user|project

Response:
{
  "mcp": {
    "user": { "installed": true, "enabled": true, "server_name": "claude-deck-mailbox" },
    "project": { "installed": false, "enabled": false, "server_name": "claude-deck-mailbox" }
  },
  "hooks": {
    "user": { "installed_events": ["SessionStart", "SessionEnd"], "missing_events": [...] },
    "project": { ... }
  },
  "token": {
    "exists": true,
    "path": "~/.claude-deck/agent-mailbox/token"
  },
  "warnings": []
}
```

```http
POST /api/v1/agent-mailbox/install/preview
Body:
{
  "project_path": "...",
  "scope": "user" | "project",
  "install_mcp": true,
  "install_hooks": true,
  "lease_guard_mode": "off" | "warn" | "block"
}

Response:
{
  "changes": [
    { "file": "~/.claude.json", "operation": "add_mcp_server", "diff": "..." },
    { "file": "~/.claude/settings.json", "operation": "add_hooks", "diff": "..." }
  ],
  "warnings": [...]
}
```

```http
POST /api/v1/agent-mailbox/install/apply
Body:
{
  "project_path": "...",
  "scope": "user" | "project",
  "install_mcp": true,
  "install_hooks": true,
  "lease_guard_mode": "off" | "warn" | "block",
  "confirmed": true
}
```

```http
POST /api/v1/agent-mailbox/install/uninstall
Body:
{
  "project_path": "...",
  "scope": "user" | "project",
  "remove_mcp": true,
  "remove_hooks": true,
  "confirmed": true
}
```

Use existing `mcp_service` and `hook_service` if possible. Do not hand-edit JSON/TOML if reusable service methods exist.

---

## 11. Local capability token

Claude Deck’s UI/API is local-only, but mailbox endpoints are callable by arbitrary local processes. Add a minimal token for agent/hook endpoints.

### 11.1 Token storage

Recommended path:

```text
~/.claude-deck/agent-mailbox/token
```

If Claude Deck already has an app data/config directory, use that instead.

Token file rules:

- Create with mode `0600` where supported.
- Generate random 32+ bytes, URL-safe base64 or hex.
- Do not store the token inline in `.mcp.json`.
- Do not render the raw token in the UI unless under an explicit “show secret” action.
- Do not include token in logs.

### 11.2 Token injection

For MCP stdio config, prefer environment variables that are local/user-scoped:

```json
{
  "mcpServers": {
    "claude-deck-mailbox": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "claude_deck_mailbox_mcp"],
      "env": {
        "CLAUDE_DECK_URL": "http://127.0.0.1:8000",
        "CLAUDE_DECK_MAILBOX_TOKEN_FILE": "~/.claude-deck/agent-mailbox/token"
      }
    }
  }
}
```

Do not place the raw token in project-shared `.mcp.json`.

If the MCP client cannot expand `~`, write the absolute path to the token file, but still do not include the secret.

### 11.3 Auth helper

Create `backend/app/services/agent_mailbox_auth.py` or similar:

```python
def get_or_create_mailbox_token() -> str: ...
def read_mailbox_token() -> str | None: ...
def verify_mailbox_token(header_value: str | None) -> None: ...
```

FastAPI dependency:

```python
async def require_mailbox_token(
    x_token: Annotated[str | None, Header(alias="X-Claude-Deck-Mailbox-Token")] = None,
):
    verify_mailbox_token(x_token)
```

For local developer convenience, allow disabling token verification only via an explicit development env var:

```text
CLAUDE_DECK_MAILBOX_DISABLE_TOKEN_AUTH=1
```

Do not default to disabled.

---

## 12. MCP stdio server

### 12.1 Location

Prefer one of these options after inspecting the repo:

Option A — package/module inside backend:

```text
backend/app/mcp/agent_mailbox_stdio.py
```

Runnable:

```bash
python -m app.mcp.agent_mailbox_stdio
```

Option B — script wrapper:

```text
scripts/claude-deck-mailbox-mcp
```

Runnable:

```bash
/path/to/claude-deck/scripts/claude-deck-mailbox-mcp
```

Option C — dedicated package if packaging exists:

```text
backend/claude_deck_mailbox_mcp/
```

Runnable:

```bash
python -m claude_deck_mailbox_mcp
```

Pick the option that fits current packaging and import paths. The install UI must write a command that works from normal Claude Code/Codex sessions, not only inside the backend working directory.

### 12.2 Dependency strategy

Before adding dependencies, inspect:

```text
backend/requirements.txt
backend/pyproject.toml
```

If `mcp`, `fastmcp`, or an Anthropic/MCP SDK is already present, use it.

If no SDK is present, either:

1. Add the official Python MCP SDK dependency; or
2. Implement a minimal stdio JSON-RPC MCP server only for `initialize`, `tools/list`, and `tools/call`.

Prefer using an SDK if accepted by the project’s dependency style. The manual protocol route is lower-dependency but riskier.

### 12.3 Environment variables

The stdio server should read:

```text
CLAUDE_DECK_URL=http://127.0.0.1:8000
CLAUDE_DECK_MAILBOX_TOKEN_FILE=/absolute/path/to/token
CLAUDE_DECK_MAILBOX_TOKEN=<optional raw token only for user-local config>
CLAUDE_DECK_AGENT_ID=<optional remembered agent id>
CLAUDE_DECK_AGENT_DISPLAY_NAME=<optional>
CLAUDE_DECK_AGENT_ROLE=<optional>
CLAUDE_DECK_PROJECT_PATH=<optional>
CLAUDE_DECK_PROVIDER=claude-code|codex-cli|unknown
CLAUDE_DECK_SESSION_ID=<optional>
```

Detect defaults:

- `cwd = os.getcwd()`
- `project_path = env or cwd`
- `provider`:
  - If env exists, use it.
  - Else infer from known environment variables if available.
  - Else `"unknown"`.

### 12.4 Registration and heartbeat

The MCP server should register lazily on:

- process start, if safe; and
- first tool call.

Store the returned `agent_id` in memory. If the MCP process is restarted, it can re-register and be correlated by session/cwd/tmux metadata.

Heartbeat:

- Send heartbeat on each tool call.
- Optionally run a background heartbeat every 30 seconds if the SDK/event loop makes this easy.
- Do not let heartbeat failures crash tool calls unless the actual tool needs the backend.

### 12.5 MCP tool definitions

Tool names should be prefixed consistently, but not too long. Use clear descriptions because models discover tools through metadata.

#### `deck_whoami`

Description:

> Register this agent with Claude Deck Agent Mailbox if needed and return this agent’s mailbox identity, current status, project path, and unread message count. Use this at the start of coordinated work.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "display_name": { "type": "string" },
    "role": { "type": "string" },
    "status": { "type": "string", "enum": ["idle", "busy", "waiting", "blocked", "error"] },
    "status_note": { "type": "string" }
  }
}
```

Output example:

```json
{
  "agent": {
    "id": "agent_...",
    "display_name": "Frontend Claude",
    "role": "frontend",
    "provider": "claude-code",
    "project_path": "/Users/me/project",
    "mailbox_status": "connected",
    "current_status": "busy"
  },
  "unread_count": 2
}
```

#### `deck_list_agents`

Description:

> List other local agents Claude Deck can see for this project, including observed tmux sessions and connected mailbox agents. Use before coordinating work or handing off tasks.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "project_path": { "type": "string" },
    "include_observed": { "type": "boolean", "default": true },
    "include_offline": { "type": "boolean", "default": false }
  }
}
```

#### `deck_set_status`

Description:

> Set this agent’s current coordination status in Claude Deck, such as busy, idle, waiting, or blocked.

Input schema:

```json
{
  "type": "object",
  "required": ["status"],
  "properties": {
    "status": { "type": "string", "enum": ["idle", "busy", "waiting", "blocked", "error"] },
    "note": { "type": "string" }
  }
}
```

#### `deck_send_message`

Description:

> Send a direct, role-targeted, or project broadcast message to other agents through Claude Deck Agent Mailbox.

Input schema:

```json
{
  "type": "object",
  "required": ["body"],
  "properties": {
    "to_agent_id": { "type": "string" },
    "to_role": { "type": "string" },
    "broadcast": { "type": "boolean", "default": false },
    "subject": { "type": "string" },
    "thread_id": { "type": "string" },
    "body": { "type": "string" },
    "priority": { "type": "string", "enum": ["low", "normal", "high", "urgent"], "default": "normal" },
    "requires_ack": { "type": "boolean", "default": false }
  }
}
```

Validation:

- Exactly one of `to_agent_id`, `to_role`, or `broadcast=true` should be used unless replying to a thread where target is implicit.
- `subject` required if no `thread_id`.

#### `deck_read_inbox`

Description:

> Read this agent’s mailbox messages. Use this before starting work in a coordinated multi-agent project and periodically during long tasks.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "unread_only": { "type": "boolean", "default": true },
    "limit": { "type": "integer", "default": 20, "minimum": 1, "maximum": 100 },
    "mark_read": { "type": "boolean", "default": true }
  }
}
```

#### `deck_reply`

Description:

> Reply to an existing Agent Mailbox thread.

Input schema:

```json
{
  "type": "object",
  "required": ["thread_id", "body"],
  "properties": {
    "thread_id": { "type": "string" },
    "body": { "type": "string" },
    "requires_ack": { "type": "boolean", "default": false },
    "priority": { "type": "string", "enum": ["low", "normal", "high", "urgent"], "default": "normal" }
  }
}
```

#### `deck_ack_message`

Description:

> Acknowledge a message that requested acknowledgement.

Input schema:

```json
{
  "type": "object",
  "required": ["message_id"],
  "properties": {
    "message_id": { "type": "string" }
  }
}
```

#### `deck_create_handoff`

Description:

> Create a structured handoff to another agent or role, including summary, touched files, and next steps.

Input schema:

```json
{
  "type": "object",
  "required": ["summary"],
  "properties": {
    "to_agent_id": { "type": "string" },
    "to_role": { "type": "string" },
    "subject": { "type": "string" },
    "summary": { "type": "string" },
    "files": { "type": "array", "items": { "type": "string" } },
    "next_steps": { "type": "array", "items": { "type": "string" } },
    "requires_ack": { "type": "boolean", "default": true }
  }
}
```

#### `deck_reserve_paths`

Description:

> Create advisory leases for files or path globs before editing them, so other agents can avoid conflicts.

Input schema:

```json
{
  "type": "object",
  "required": ["paths"],
  "properties": {
    "paths": { "type": "array", "items": { "type": "string" } },
    "purpose": { "type": "string" },
    "ttl_minutes": { "type": "integer", "default": 90, "minimum": 5, "maximum": 1440 },
    "enforcement_mode": { "type": "string", "enum": ["advisory", "warn", "block"], "default": "advisory" }
  }
}
```

Output should include active conflicts, even if the lease is created.

#### `deck_release_paths`

Description:

> Release path leases created by this agent.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "lease_ids": { "type": "array", "items": { "type": "string" } },
    "paths": { "type": "array", "items": { "type": "string" } },
    "release_all": { "type": "boolean", "default": false }
  }
}
```

#### `deck_list_path_leases`

Description:

> List active path leases in this project.

Input schema:

```json
{
  "type": "object",
  "properties": {
    "project_path": { "type": "string" },
    "active_only": { "type": "boolean", "default": true }
  }
}
```

#### `deck_check_path_conflicts`

Description:

> Check whether files or path globs conflict with active leases held by other agents.

Input schema:

```json
{
  "type": "object",
  "required": ["paths"],
  "properties": {
    "paths": { "type": "array", "items": { "type": "string" } },
    "project_path": { "type": "string" }
  }
}
```

### 12.6 Error behavior

MCP tool outputs should be model-friendly JSON with an `ok` boolean:

```json
{
  "ok": false,
  "error": {
    "code": "deck_unreachable",
    "message": "Claude Deck backend is not reachable at http://127.0.0.1:8000."
  },
  "suggestion": "Continue without mailbox coordination, or ask the user to start Claude Deck."
}
```

Do not print stack traces to the model. Log diagnostics to stderr only.

---

## 13. Claude Code hooks

### 13.1 Hook integration strategy

Claude Code supports command hooks and HTTP hooks. Claude Deck’s current hook UI/service may only expose a subset of hook handler types. Implement the least risky v1:

1. Add a **command wrapper** that reads hook JSON from stdin and posts it to Claude Deck.
2. If current Claude Deck hook service supports HTTP hooks cleanly, also support direct HTTP hooks.
3. If current Claude Deck hook event constants omit `SessionStart` or `SessionEnd`, extend them carefully because these are necessary for lifecycle registration.

### 13.2 Hook wrapper location

Possible locations:

```text
scripts/claude-deck-mailbox-hook
backend/app/mcp/agent_mailbox_hook.py
backend/claude_deck_mailbox_hooks/__main__.py
```

The installed command must work outside the repo cwd.

Example command installed in settings:

```bash
python /absolute/path/to/claude-deck/scripts/claude-deck-mailbox-hook --event SessionStart
```

or:

```bash
python -m claude_deck_mailbox_hooks --event SessionStart
```

### 13.3 Hook wrapper behavior

Pseudo-code:

```python
def main():
    event_name = parse_args().event
    payload = json.load(sys.stdin)

    deck_url = os.getenv("CLAUDE_DECK_URL", "http://127.0.0.1:8000")
    token = read_token_from_env_or_file()

    request = {
        "hook_event_name": event_name,
        "session_id": payload.get("session_id"),
        "cwd": payload.get("cwd"),
        "project_path": payload.get("cwd"),
        "tool_name": payload.get("tool_name"),
        "tool_input": payload.get("tool_input"),
        "tool_response": payload.get("tool_response"),
        "notification_message": payload.get("message"),
        "raw_payload": payload,
    }

    response = post(deck_url + "/api/v1/agent-mailbox/hooks/event", request, token)

    if event_name == "SessionStart":
        # stdout can inject context in Claude Code SessionStart command hooks.
        print(short_context_message(response))

    if event_name == "PreToolUse":
        # Optional strict mode; see 13.8.
        return pretool_exit_code(response)

    return 0
```

Failure behavior:

- Network/backend failure:
  - Print a short diagnostic to stderr.
  - Exit 0 unless strict mode explicitly requires blocking.
- Invalid JSON:
  - Print to stderr.
  - Exit 0.
- Token missing:
  - Print to stderr.
  - Exit 0.

### 13.4 `SessionStart`

Purpose:

- Register or update agent.
- Inject a short context reminder into Claude Code.

Recommended event config:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python /ABSOLUTE/PATH/scripts/claude-deck-mailbox-hook --event SessionStart"
          }
        ]
      }
    ]
  }
}
```

Context message printed to stdout:

```markdown
Claude Deck Agent Mailbox is available for local multi-agent coordination.

Recommended workflow:
- Call `deck_whoami` once to register your agent identity.
- Call `deck_read_inbox` before starting coordinated work.
- Call `deck_list_agents` to see other local agents.
- Use `deck_reserve_paths` before editing shared areas.
- Use `deck_send_message` or `deck_create_handoff` when coordinating with other agents.
```

Keep this message short to avoid wasting context.

### 13.5 `SessionEnd`

Purpose:

- Mark agent/session offline.
- Release or mark stale any leases if configured.

Config:

```json
{
  "hooks": {
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python /ABSOLUTE/PATH/scripts/claude-deck-mailbox-hook --event SessionEnd"
          }
        ]
      }
    ]
  }
}
```

### 13.6 `Notification`

Purpose:

- Mark agent as `waiting`.
- Surface “needs input” badges in Claude Deck UI.

Config:

```json
{
  "hooks": {
    "Notification": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python /ABSOLUTE/PATH/scripts/claude-deck-mailbox-hook --event Notification"
          }
        ]
      }
    ]
  }
}
```

### 13.7 `PostToolUse`

Purpose:

- Update activity.
- Log modified files.
- Mark agent `busy`.
- Optionally refresh leases or create audit events.

Matcher:

```text
Edit|Write|MultiEdit|Bash
```

Config:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit|Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python /ABSOLUTE/PATH/scripts/claude-deck-mailbox-hook --event PostToolUse"
          }
        ]
      }
    ]
  }
}
```

For `Edit`, `Write`, and `MultiEdit`:

- Extract `file_path` from tool input.
- Add to `AgentMailboxEvent`.
- Optionally add to `modified_files` in existing `PresenceSession` if shared helper exists.

For `Bash`:

- Store command summary only; do not log large output or secrets.
- If command looks like git status/diff, do not parse raw output in MVP.

### 13.8 `PreToolUse` lease guard

Purpose:

- Warn or block if another agent holds a conflicting lease.

Start as optional. Installation setting:

```text
lease_guard_mode = off | warn | block
```

Recommended v1 behavior:

- `off`: do not install PreToolUse hook.
- `warn`: install PreToolUse hook, return JSON/exit 0 with a message if conflicts exist.
- `block`: install PreToolUse hook, deny on conflict.

Matcher:

```text
Edit|Write|MultiEdit
```

For Bash, conflict detection is hard. Do not block Bash in MVP unless command clearly references a conflicting file path and tests cover it.

Blocking behavior:

- Follow current Claude Code hook expected output/exit behavior.
- If using exit code `2` for blocking, emit a concise stderr/JSON message.
- Make sure the hook does not block on backend failure. Only block on confirmed conflicts.

Conflict message:

```text
Claude Deck Agent Mailbox: another agent has an active lease on src/auth/**.
Holder: Frontend Claude
Purpose: Refactoring login form
Expires: 2026-06-12T16:30:00+02:00
Use deck_send_message to coordinate, or ask the user to override.
```

---

## 14. Installation and configuration

### 14.1 MCP server installation

Use existing `mcp_service` to add/update a server named:

```text
claude-deck-mailbox
```

User-scope example:

```json
{
  "name": "claude-deck-mailbox",
  "type": "stdio",
  "scope": "user",
  "command": "python",
  "args": ["/ABSOLUTE/PATH/TO/claude-deck/scripts/claude-deck-mailbox-mcp"],
  "env": {
    "CLAUDE_DECK_URL": "http://127.0.0.1:8000",
    "CLAUDE_DECK_MAILBOX_TOKEN_FILE": "/ABSOLUTE/PATH/.claude-deck/agent-mailbox/token"
  },
  "disabled": false
}
```

Project-scope `.mcp.json` example:

```json
{
  "mcpServers": {
    "claude-deck-mailbox": {
      "type": "stdio",
      "command": "python",
      "args": ["/ABSOLUTE/PATH/TO/claude-deck/scripts/claude-deck-mailbox-mcp"],
      "env": {
        "CLAUDE_DECK_URL": "http://127.0.0.1:8000",
        "CLAUDE_DECK_MAILBOX_TOKEN_FILE": "/ABSOLUTE/PATH/.claude-deck/agent-mailbox/token"
      }
    }
  }
}
```

Important:

- Project config may be committed. Do not include raw token.
- Absolute local script paths in project config are machine-specific. Warn the user.
- User-scope is safer for local-only usage. Project-scope is useful for repeatable setup but less portable.

### 14.2 Hook installation

Use existing `hook_service` where possible.

User-scope file:

```text
~/.claude/settings.json
```

Project-scope file:

```text
.claude/settings.json
```

Install:

- `SessionStart`
- `SessionEnd`
- `Notification`
- `PostToolUse` matcher `Edit|Write|MultiEdit|Bash`
- `PreToolUse` matcher `Edit|Write|MultiEdit` only when lease guard mode is `warn` or `block`

If Claude Deck hook schema currently lacks `SessionStart` or `SessionEnd`, extend it. If frontend options do not show these events, add them.

### 14.3 Coverage model

The install status endpoint/UI should classify each project/session:

```text
Observed only:
  Claude Deck sees this session through Agent Bridge, but the session cannot use mailbox tools.

Mailbox installed:
  Config contains claude-deck-mailbox MCP server, but the running session may need restart/reload.

Connected:
  Agent registered or heartbeated through mailbox MCP/hooks.

Offline:
  Agent was known but stale or ended.
```

Warn the user:

```text
Existing Claude Code/Codex sessions may not load newly installed MCP servers until they are restarted or reload their MCP configuration.
```

### 14.4 Codex CLI support

Claude Deck supports Codex CLI configuration and tmux discovery. For Codex CLI:

- Ensure observed sessions from Agent Bridge show in Agent Mailbox.
- Install MCP config through existing Codex support only if Claude Deck already supports Codex MCP configuration safely.
- If Codex CLI hooks are not available or not managed by Claude Deck, do not invent unsupported hooks.
- Connected Codex agents can still use the mailbox MCP server if Codex CLI supports MCP server configuration in the user’s installed version.

Make Codex support explicit in UI:

```text
Codex CLI:
- Observed through Agent Bridge: supported.
- Mailbox MCP: supported when Codex CLI MCP config is available.
- Lifecycle hooks: not available unless Codex exposes compatible hooks.
```

---

## 15. Frontend implementation

### 15.1 Suggested file structure

Adapt to current frontend conventions.

```text
frontend/src/features/agent-mailbox/
  api.ts
  types.ts
  hooks.ts
  AgentMailboxPage.tsx
  components/
    AgentMailboxHeader.tsx
    AgentCardsGrid.tsx
    AgentStatusBadge.tsx
    AgentMailboxInstallPanel.tsx
    ThreadList.tsx
    ThreadDetail.tsx
    ComposeMessageDialog.tsx
    PathLeasesPanel.tsx
    LeaseConflictBadge.tsx
    HandoffDialog.tsx
```

If project uses `pages/`:

```text
frontend/src/pages/AgentMailboxPage.tsx
```

### 15.2 Route/nav

Add a route:

```text
/agent-mailbox
```

Add sidebar/nav item:

```text
Agent Mailbox
```

Icon suggestion:

- Mailbox
- MessagesSquare
- Network
- UsersRound

Use whatever icon library is already used.

### 15.3 API client

`api.ts`:

```ts
export async function listMailboxAgents(params: {
  projectPath?: string
  includeObserved?: boolean
  includeOffline?: boolean
  syncObserved?: boolean
}): Promise<{ agents: MailboxAgent[] }> { ... }

export async function listThreads(params: {
  projectPath?: string
  agentId?: string
}): Promise<{ threads: MailboxThreadSummary[] }> { ... }

export async function getThreadMessages(threadId: string): Promise<{ messages: MailboxMessage[] }> { ... }

export async function sendMessage(request: SendMessageRequest): Promise<MailboxMessage> { ... }

export async function listLeases(params: { projectPath: string }): Promise<{ leases: PathLease[] }> { ... }

export async function reservePaths(request: ReservePathsRequest): Promise<ReservePathsResult> { ... }

export async function getInstallStatus(projectPath?: string): Promise<InstallStatus> { ... }

export async function previewInstall(request: InstallRequest): Promise<InstallPreview> { ... }

export async function applyInstall(request: InstallRequest & { confirmed: true }): Promise<InstallResult> { ... }
```

Follow current error-handling/fetch conventions.

### 15.4 Types

`types.ts`:

```ts
export type MailboxStatus = 'observed' | 'connected' | 'offline'
export type AgentStatus = 'idle' | 'busy' | 'waiting' | 'blocked' | 'error' | 'offline'

export interface MailboxAgent {
  id: string
  provider: string
  displayName?: string | null
  role?: string | null
  projectPath?: string | null
  cwd?: string | null
  sessionId?: string | null
  tmuxTarget?: string | null
  paneId?: string | null
  pid?: number | null
  mailboxStatus: MailboxStatus
  currentStatus: AgentStatus
  statusNote?: string | null
  supportsMcp: boolean
  supportsHooks: boolean
  lastSeenAt?: string | null
  unreadCount: number
  activeLeaseCount: number
}
```

Use the project’s existing camelCase/snake_case mapping style.

### 15.5 Page layout

Recommended layout:

```text
Agent Mailbox
┌──────────────────────────────────────────────────────┐
│ Project picker / Sync observed / Install status      │
└──────────────────────────────────────────────────────┘

Tabs:
1. Agents
2. Threads
3. Coordination
4. Install / Coverage
```

#### Agents tab

Cards for each agent:

```text
Frontend Claude
Connected · busy · claude-code
/Users/me/project
tmux: deck:1.2 · pid 12345
Unread: 2 · Leases: 1
[Message] [Handoff] [Attach in Agent Bridge if available]
```

Badges:

- `Connected`: green-ish if existing styles have variants; do not invent custom color tokens unnecessarily.
- `Observed only`
- `Offline`
- `Waiting`
- `Blocked`

Actions:

- Compose direct message.
- Create handoff.
- View leases.
- Open/attach in Agent Bridge if a tmux target exists and an existing route can be linked.

#### Threads tab

Left list:

- Subject
- Last message excerpt
- Participants / target
- Unread count
- Requires ack indicator
- Priority

Right detail:

- Messages in chronological order.
- Reply composer.
- Ack button for messages requiring ack.
- Human/system sender label.

#### Coordination tab

Panels:

- Active path leases.
- Conflicts.
- Expired/released toggle.
- Reserve path form for human-created leases.
- Handoff summaries.

Human-created leases should use `sender_kind = human` or a nullable agent ID, depending on service design. For v1, human-created leases are optional; messages are more important.

#### Install/Coverage tab

Show:

- Token status: exists/missing.
- MCP install status at user/project scope.
- Hook install status at user/project scope.
- Observed sessions without mailbox tools.
- Connected sessions.
- Warnings about existing sessions needing restart.

Actions:

- Preview install.
- Apply install.
- Uninstall.
- Copy manual config snippets.

### 15.6 Agent Bridge badges

If low-risk, add mailbox state badges to existing Agent Bridge cards:

```text
Mailbox: Connected
Mailbox: Observed only
Mailbox: Installed, restart needed
Mailbox: Offline
```

Do not block MVP on this if Agent Bridge components are complex. The Agent Mailbox page is the required UI.

### 15.7 Polling vs realtime

MVP can poll:

- Agents every 5 seconds.
- Threads every 10 seconds.
- Active thread messages every 5 seconds.
- Leases every 10 seconds.

If an existing WebSocket/event helper exists, use it instead.

---

## 16. Backend integration with existing Presence

Claude Deck appears to have a presence service that records hook events and session state. Reuse it where possible, but do not entangle mailbox logic so deeply that the feature becomes fragile.

Recommended relationship:

```text
Presence = raw/derived session activity stream
Agent Mailbox = coordination and communication layer
```

Integration points:

- `PostToolUse` hook events can be written to both Presence and Agent Mailbox event log.
- Existing modified file extraction logic should be reused if available.
- Existing `PresenceSession` project derivation should be reused to normalize project paths.
- Do not break existing presence endpoints or UI.

If current presence service already handles SessionStart/SessionEnd, Agent Mailbox should subscribe/call a helper rather than duplicating logic. If no such callback mechanism exists, duplication is acceptable for v1 with tests.

---

## 17. Implementation phases

### Phase 0 — Repository reconnaissance

Codex CLI should begin with:

```bash
git status --short
find backend/app -maxdepth 3 -type f | sort
find frontend/src -maxdepth 3 -type f | sort
sed -n '1,220p' backend/app/api/v1/router.py
sed -n '1,260p' backend/app/database.py
grep -R "class .*Base" -n backend/app/models backend/app | head -80
grep -R "Presence" -n backend/app | head -80
grep -R "AgentBridge" -n backend/app frontend/src | head -80
grep -R "hook" -n backend/app/services frontend/src | head -80
grep -R "mcp" -n backend/app/services frontend/src | head -80
```

Tasks:

- Identify actual DB model location.
- Identify async session dependency.
- Identify route include pattern.
- Identify frontend route/nav pattern.
- Identify API client conventions.
- Identify build/test commands from `package.json`, `pyproject.toml`, and scripts.

Deliverable:

- No code changes except optional notes.
- A short implementation note in the Codex session: actual files to modify.

### Phase 1 — Backend models and service

Files likely changed:

```text
backend/app/models/database.py or backend/app/models/agent_mailbox.py
backend/app/models/schemas.py or backend/app/schemas/agent_mailbox.py
backend/app/services/agent_mailbox_service.py
backend/app/services/agent_mailbox_auth.py
backend/app/api/v1/agent_mailbox.py
backend/app/api/v1/router.py
backend/app/database.py if model import is needed
backend/tests/test_agent_mailbox_service.py
backend/tests/test_agent_mailbox_api.py
```

Implement:

1. Models.
2. Schemas.
3. Auth token helper.
4. Core service.
5. API router.
6. Router include.
7. Table initialization/migration.
8. Tests.

Acceptance:

- Backend starts.
- Tables created.
- `GET /api/v1/agent-mailbox/agents` works.
- `POST /register` with token works.
- `POST /messages` + inbox read works.
- `POST /leases` + conflict check works.
- Existing tests still pass.

Suggested tests:

```python
async def test_register_agent_creates_connected_agent(...): ...
async def test_heartbeat_marks_agent_seen(...): ...
async def test_send_direct_message_creates_receipt(...): ...
async def test_broadcast_message_targets_project_agents(...): ...
async def test_ack_message_sets_acked_at(...): ...
async def test_reserve_paths_detects_conflict(...): ...
async def test_expired_lease_is_not_conflict(...): ...
async def test_hook_session_start_registers_agent(...): ...
```

### Phase 2 — Agent Bridge observed sync

Files likely changed:

```text
backend/app/services/agent_mailbox_service.py
backend/app/api/v1/agent_mailbox.py
backend/tests/test_agent_mailbox_agent_bridge_sync.py
```

Implement:

1. Call existing Agent Bridge service to list sessions.
2. Upsert observed agents.
3. Add `sync_observed` query behavior on list agents.
4. Add stale observed handling.
5. Tests with mocked Agent Bridge service.

Acceptance:

- With mocked Agent Bridge sessions, mailbox list shows `observed` agents.
- If a connected registration matches an observed session, it upgrades the same row to `connected`.
- No duplicate agent rows for the same tmux pane.

### Phase 3 — MCP stdio server

Files likely changed:

```text
scripts/claude-deck-mailbox-mcp
backend/app/mcp/agent_mailbox_stdio.py
backend/tests/test_agent_mailbox_mcp.py
backend/requirements.txt or pyproject.toml if adding SDK
```

Implement:

1. Stdio server.
2. HTTP client to Claude Deck backend.
3. Registration/heartbeat.
4. Tool definitions.
5. Tool call handlers.
6. Model-friendly error outputs.
7. Smoke tests.

Acceptance:

- Running the MCP server does not crash when backend is down.
- `tools/list` includes all core tools.
- `deck_whoami` registers an agent when backend is up.
- `deck_send_message` calls backend correctly.
- Tool descriptions are clear enough for a model.

Manual protocol smoke if not using SDK:

```bash
printf '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}\n' \
  | python scripts/claude-deck-mailbox-mcp
```

Adapt to actual MCP framing required by the chosen SDK/protocol.

### Phase 4 — Hook wrapper and hook ingest

Files likely changed:

```text
scripts/claude-deck-mailbox-hook
backend/app/services/agent_mailbox_service.py
backend/app/api/v1/agent_mailbox.py
backend/tests/test_agent_mailbox_hooks.py
```

Implement:

1. Hook wrapper script.
2. Generic hook ingest endpoint.
3. SessionStart registration behavior.
4. SessionEnd offline behavior.
5. Notification waiting behavior.
6. PostToolUse activity/modified file event behavior.
7. Optional PreToolUse conflict check with warn/block output.
8. Tests.

Acceptance:

- Hook wrapper accepts stdin JSON.
- Missing backend exits 0.
- SessionStart emits short context message.
- PreToolUse block mode blocks only confirmed conflicts.
- No secrets/raw large payloads are stored unnecessarily.

### Phase 5 — Install/coverage backend

Files likely changed:

```text
backend/app/services/agent_mailbox_install_service.py
backend/app/api/v1/agent_mailbox.py
backend/tests/test_agent_mailbox_install.py
```

Implement:

1. Token ensure/status.
2. MCP install status.
3. Hook install status.
4. Preview diff.
5. Apply install using existing service methods.
6. Uninstall.
7. Warnings about restart/reload.

Acceptance:

- Preview works without modifying files.
- Apply creates backups or uses existing backup path.
- Raw token is never written to `.mcp.json`.
- Project-scope install warns about absolute local paths.
- Existing MCP/hook pages still parse the resulting config.

### Phase 6 — Frontend page

Files likely changed:

```text
frontend/src/features/agent-mailbox/*
frontend/src/pages/AgentMailboxPage.tsx
frontend/src/App.tsx or route config
frontend/src/components/sidebar/nav config
```

Implement:

1. Types and API client.
2. Route/nav.
3. Agent Mailbox page layout.
4. Agents tab.
5. Threads tab.
6. Coordination tab.
7. Install/Coverage tab.
8. Loading/error/empty states.
9. Polling.

Acceptance:

- Page loads with no agents/messages.
- Observed agents appear after sync.
- Connected agents display.
- Human can send a message.
- Human can view thread messages.
- Leases list and conflict badges display.
- Install status visible.

### Phase 7 — Agent Bridge badge integration

Files likely changed:

```text
frontend/src/features/agent-bridge/*
backend/app/api/v1/agent_bridge.py or mailbox endpoint only
```

Implement only if low-risk:

- Add mailbox badge to Agent Bridge cards.
- Link to Agent Mailbox filtered to that agent/project.
- Do not change terminal attach/kill behavior.

Acceptance:

- Agent Bridge still works.
- Badge reflects observed/connected/offline.

### Phase 8 — Docs

Files likely changed:

```text
docs/features/agent-mailbox.md
docs/api/agent-mailbox.md
docs/features/mcp-servers.md maybe link
docs/features/hooks.md maybe link
README.md feature list maybe one line
```

Document:

- What Agent Mailbox does.
- Observed vs connected.
- Installation.
- MCP tools.
- Hooks.
- File leases.
- Security/token model.
- Limitations.
- Troubleshooting.

### Phase 9 — Final verification

Run available commands after inspecting scripts:

```bash
# Backend
cd backend
python -m pytest

# Frontend
cd frontend
npm install  # only if needed and lockfile policy allows
npm run build

# Full project, if available
./scripts/build.sh
```

Also run manual smoke tests in section 25.

---

## 18. Detailed API behavior

### 18.1 Register agent

Request:

```json
{
  "provider": "claude-code",
  "display_name": "Frontend Claude",
  "role": "frontend",
  "project_path": "/Users/me/project",
  "cwd": "/Users/me/project",
  "session_id": "abc123",
  "client_name": "claude-deck-mailbox-mcp",
  "client_version": "0.1.0"
}
```

Response:

```json
{
  "agent": {
    "id": "agent_01J...",
    "provider": "claude-code",
    "display_name": "Frontend Claude",
    "role": "frontend",
    "project_path": "/Users/me/project",
    "cwd": "/Users/me/project",
    "session_id": "abc123",
    "tmux_target": null,
    "pane_id": null,
    "pid": null,
    "mailbox_status": "connected",
    "current_status": "idle",
    "status_note": null,
    "supports_mcp": true,
    "supports_hooks": false,
    "last_seen_at": "2026-06-12T12:00:00+02:00",
    "unread_count": 0,
    "active_lease_count": 0
  }
}
```

Server behavior:

- Normalize paths.
- Upsert by session/tmux/observed key.
- Set `supports_mcp = true` if source is MCP.
- Set `supports_hooks = true` if source is hook.
- Add event `registered`.

### 18.2 List agents

Request:

```http
GET /api/v1/agent-mailbox/agents?project_path=/Users/me/project&include_observed=true&sync_observed=true
```

Response:

```json
{
  "agents": [
    {
      "id": "agent_01J...",
      "provider": "claude-code",
      "display_name": "Frontend Claude",
      "role": "frontend",
      "project_path": "/Users/me/project",
      "cwd": "/Users/me/project",
      "tmux_target": "deck:1.2",
      "pane_id": "%5",
      "pid": 12345,
      "mailbox_status": "connected",
      "current_status": "busy",
      "status_note": "Refactoring auth form",
      "supports_mcp": true,
      "supports_hooks": true,
      "last_seen_at": "2026-06-12T12:01:00+02:00",
      "unread_count": 1,
      "active_lease_count": 2
    },
    {
      "id": "agent_01K...",
      "provider": "codex-cli",
      "display_name": "Codex Tests",
      "role": null,
      "project_path": "/Users/me/project",
      "cwd": "/Users/me/project",
      "tmux_target": "deck:1.3",
      "pane_id": "%6",
      "pid": 12346,
      "mailbox_status": "observed",
      "current_status": "idle",
      "status_note": null,
      "supports_mcp": false,
      "supports_hooks": false,
      "last_seen_at": "2026-06-12T12:01:00+02:00",
      "unread_count": 0,
      "active_lease_count": 0
    }
  ]
}
```

### 18.3 Send message

Request:

```json
{
  "sender_agent_id": "agent_01J...",
  "recipient_agent_id": "agent_01K...",
  "subject": "Auth tests handoff",
  "body_markdown": "I refactored auth session handling. Please run and fix tests.",
  "priority": "high",
  "requires_ack": true
}
```

Response:

```json
{
  "id": "msg_01...",
  "thread_id": "thread_01...",
  "sender_agent_id": "agent_01J...",
  "sender_kind": "agent",
  "recipient_agent_id": "agent_01K...",
  "recipient_role": null,
  "is_broadcast": false,
  "priority": "high",
  "requires_ack": true,
  "body_markdown": "I refactored auth session handling. Please run and fix tests.",
  "created_at": "2026-06-12T12:02:00+02:00",
  "read_at": null,
  "acked_at": null
}
```

### 18.4 Read inbox

Request:

```http
GET /api/v1/agent-mailbox/inbox?agent_id=agent_01K&unread_only=true&limit=20&mark_read=true
```

Response:

```json
{
  "messages": [
    {
      "id": "msg_01...",
      "thread_id": "thread_01...",
      "sender_agent_id": "agent_01J...",
      "sender_kind": "agent",
      "recipient_agent_id": "agent_01K...",
      "priority": "high",
      "requires_ack": true,
      "body_markdown": "I refactored auth session handling. Please run and fix tests.",
      "created_at": "2026-06-12T12:02:00+02:00",
      "read_at": "2026-06-12T12:05:00+02:00",
      "acked_at": null
    }
  ]
}
```

### 18.5 Reserve paths

Request:

```json
{
  "agent_id": "agent_01J...",
  "project_path": "/Users/me/project",
  "paths": ["src/auth/**", "backend/app/api/v1/auth.py"],
  "purpose": "Refactoring login/session flow",
  "ttl_minutes": 90,
  "enforcement_mode": "advisory"
}
```

Response:

```json
{
  "leases": [
    {
      "id": "lease_01...",
      "agent_id": "agent_01J...",
      "project_path": "/Users/me/project",
      "path_glob": "src/auth/**",
      "purpose": "Refactoring login/session flow",
      "lease_status": "active",
      "enforcement_mode": "advisory",
      "expires_at": "2026-06-12T13:30:00+02:00",
      "created_at": "2026-06-12T12:00:00+02:00"
    }
  ],
  "conflicts": []
}
```

---

## 19. Security and privacy requirements

### Must not

- Send mailbox data outside the local machine.
- Add telemetry.
- Store raw OAuth/auth files.
- Store raw terminal transcripts in mailbox tables.
- Expose another agent’s transcript through MCP tools.
- Log the mailbox token.
- Store raw token in project `.mcp.json`.
- Auto-execute installation commands inside live terminal panes.
- Block agent tool use by default.

### Should

- Redact suspiciously secret-looking fields from hook payloads before storing.
- Store only command summaries for Bash events.
- Use token for agent/hook endpoints.
- Keep human UI local-only.
- Provide install previews.
- Provide backups before config mutation.
- Treat stale heartbeats as offline.
- Make failure modes visible but not destructive.

### Suggested redaction keys

When storing `tool_input` or hook payloads, redact values for keys matching:

```text
token
secret
password
passwd
api_key
apikey
authorization
cookie
oauth
credential
private_key
```

Do not attempt deep secret scanning in MVP. Use conservative key-based redaction.

---

## 20. Settings

Add a persistent settings record if Claude Deck has a settings table/file. Otherwise keep v1 settings implicit and add endpoints later.

Potential settings:

```json
{
  "agent_mailbox": {
    "enabled": true,
    "heartbeat_ttl_seconds": 120,
    "observed_ttl_seconds": 300,
    "default_lease_ttl_minutes": 90,
    "lease_guard_mode": "off",
    "expose_transcripts_to_agents": false,
    "allow_agent_broadcasts": true,
    "allow_role_messages": true
  }
}
```

MVP can hardcode defaults and expose lease guard install mode only.

---

## 21. IDs and timestamps

Use existing ID helpers if present. If not:

```python
import uuid
def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"
```

Recommended prefixes:

```text
agent_
thread_
msg_
receipt_
lease_
event_
```

Timestamps:

- Store timezone-aware UTC if existing app does that.
- Otherwise follow existing project convention.
- API should emit ISO 8601 strings.

---

## 22. Error handling

### API errors

Use FastAPI `HTTPException` matching current style.

Common cases:

```text
400 invalid target: must specify recipient_agent_id, recipient_role, or broadcast
400 invalid path: path outside project_path
401 invalid/missing mailbox token
404 agent not found
404 message not found
409 lease conflict only if strict/blocking API mode is requested
500 unexpected service error
```

### MCP errors

Always return model-friendly content. Example:

```json
{
  "ok": false,
  "error": {
    "code": "agent_not_registered",
    "message": "This mailbox tool could not determine the current agent identity."
  },
  "suggestion": "Call deck_whoami first."
}
```

### Hook errors

Hooks should exit 0 on non-strict failures. Do not make Claude Code unusable if Claude Deck is not running.

---

## 23. UI empty states and copy

### No agents

```text
No agents visible yet.

Open Claude Code or Codex CLI inside tmux and Agent Bridge will discover it. To let an agent message other agents, install the Claude Deck Mailbox MCP server.
```

### Observed only

```text
Observed only

Claude Deck can see this tmux session, but the session has not connected to Agent Mailbox. Install the mailbox MCP server and start a new/reloaded session to make it addressable.
```

### Connected

```text
Connected

This agent has mailbox tools and can list agents, read messages, send messages, and reserve paths.
```

### Existing session warning

```text
Already-running sessions may not load newly installed MCP servers. Start a new session or reload the agent’s MCP configuration after installation.
```

### File leases copy

```text
Path leases are advisory by default. They help agents avoid collisions but do not lock files unless you enable a PreToolUse lease guard.
```

---

## 24. Tests

### 24.1 Backend unit tests

Create tests using the existing async DB test fixture.

#### Agent registration

```python
async def test_register_agent_creates_connected_agent(db):
    req = AgentRegisterRequest(provider="claude-code", cwd="/tmp/project")
    agent = await service.register_agent(db, req)
    assert agent.mailbox_status == "connected"
    assert agent.supports_mcp is True
```

#### Observed upgrade

```python
async def test_register_agent_upgrades_observed_agent(db):
    observed = await create_observed_agent(pane_id="%1", tmux_target="deck:1.1")
    req = AgentRegisterRequest(provider="claude-code", pane_id="%1", tmux_target="deck:1.1")
    connected = await service.register_agent(db, req)
    assert connected.id == observed.id
    assert connected.mailbox_status == "connected"
```

#### Message direct

```python
async def test_send_direct_message_creates_receipt(db):
    sender = await create_agent()
    recipient = await create_agent()
    msg = await service.send_message(db, SendMessageRequest(
        sender_agent_id=sender.id,
        recipient_agent_id=recipient.id,
        subject="Hello",
        body_markdown="Ping",
    ))
    inbox = await service.read_inbox(db, recipient.id)
    assert inbox[0].id == msg.id
```

#### Broadcast

```python
async def test_broadcast_targets_project_agents_except_sender(db):
    ...
```

#### Ack

```python
async def test_ack_message_sets_receipt_acked_at(db):
    ...
```

#### Leases

```python
async def test_path_lease_conflict_exact(db): ...
async def test_path_lease_conflict_glob(db): ...
async def test_path_lease_no_conflict_different_dir(db): ...
async def test_expired_lease_is_ignored(db): ...
async def test_agent_does_not_conflict_with_own_lease(db): ...
```

#### Hooks

```python
async def test_session_start_hook_registers_agent(db): ...
async def test_session_end_hook_marks_offline(db): ...
async def test_notification_hook_marks_waiting(db): ...
async def test_post_tool_use_records_modified_file_event(db): ...
async def test_pre_tool_use_warn_mode_does_not_block(db): ...
async def test_pre_tool_use_block_mode_blocks_confirmed_conflict(db): ...
```

### 24.2 API tests

Use existing FastAPI test client.

Test:

- Token missing -> 401 for `/register`.
- Valid token -> register works.
- UI list agents works without token if app policy allows.
- Send/read/ack messages.
- Install preview does not write files.
- Install apply writes expected config via temp home/project.

### 24.3 MCP tests

If using SDK, use SDK test helpers where available.

Minimum tests:

- `tools/list` contains expected tools.
- Tool schema has descriptions and input schemas.
- Backend unreachable returns `ok=false`, not crash.
- Mock backend receives correct HTTP request for `deck_send_message`.
- `deck_whoami` caches agent ID.

### 24.4 Hook wrapper tests

Use subprocess with stdin JSON and env variables:

```bash
echo '{"session_id":"s1","cwd":"/tmp/project"}' \
  | CLAUDE_DECK_URL=http://127.0.0.1:9999 \
    python scripts/claude-deck-mailbox-hook --event SessionStart
```

Expected:

- Exit 0 if backend unavailable.
- stderr diagnostic.
- no traceback.

Mock server test:

- Start local test HTTP server.
- Assert payload posted.
- Assert token header present.

### 24.5 Frontend checks

After implementation:

```bash
cd frontend
npm run build
```

If tests/lint exist:

```bash
npm run lint
npm run test
npm run typecheck
```

Run only available scripts.

---

## 25. Manual smoke test

Perform this manually after automated tests.

### Setup

```bash
git status --short
./scripts/dev.sh
```

Open Claude Deck in browser.

### Smoke 1 — empty mailbox

1. Navigate to `/agent-mailbox`.
2. Confirm page loads.
3. Confirm empty state is useful.
4. Confirm no console errors.

### Smoke 2 — observed session

1. Start a tmux session.
2. Launch Claude Code or Codex CLI in it.
3. Open Agent Bridge and confirm session appears.
4. Open Agent Mailbox.
5. Click “Sync observed” if needed.
6. Confirm session appears as `observed`.

### Smoke 3 — install mailbox

1. Open Agent Mailbox Install/Coverage tab.
2. Preview user-scope MCP + hooks install.
3. Confirm diff shows `claude-deck-mailbox` and hook changes.
4. Apply install.
5. Confirm backups or existing backup flow.
6. Confirm MCP Servers page can still parse config.
7. Confirm Hooks page can still parse config.

### Smoke 4 — connected session

1. Start a new Claude Code session after install.
2. Ask it to call `deck_whoami`.
3. Confirm Agent Mailbox shows it as `connected`.
4. Ask it to call `deck_list_agents`.
5. Confirm it sees observed/connected agents.

### Smoke 5 — messaging

1. Start two connected sessions.
2. In Agent A, call `deck_send_message` to Agent B.
3. In Agent B, call `deck_read_inbox`.
4. Confirm message appears.
5. Ack message if required.
6. Confirm UI receipt updates.

### Smoke 6 — path leases

1. Agent A reserves `src/auth/**`.
2. Agent B checks conflict for `src/auth/session.ts`.
3. Confirm conflict appears.
4. Agent A releases lease.
5. Confirm conflict disappears.

### Smoke 7 — hooks

1. Trigger an edit with Claude Code.
2. Confirm PostToolUse event updates activity.
3. End session.
4. Confirm agent eventually shows offline.

### Smoke 8 — failure mode

1. Stop Claude Deck.
2. Start Claude Code with installed hooks.
3. Confirm Claude Code still works and hooks do not crash the session.
4. Restart Claude Deck.

---

## 26. Documentation content

Add a docs page:

```text
docs/features/agent-mailbox.md
```

Suggested outline:

```markdown
# Agent Mailbox

Agent Mailbox lets local agents visible in Claude Deck coordinate with each other.

## Observed vs connected

## Install mailbox MCP server

## Install Claude Code hooks

## MCP tools available to agents

## Messages and handoffs

## Path leases

## Security and privacy

## Limitations

## Troubleshooting
```

Add API docs:

```text
docs/api/agent-mailbox.md
```

Suggested outline:

```markdown
# Agent Mailbox API

## Agents
## Messages
## Threads
## Leases
## Hooks
## Install/Coverage
## Auth token for agent endpoints
```

Update README feature list:

```markdown
- Agent Mailbox — local agent-to-agent visibility, messaging, handoffs, and advisory path leases for Agent Bridge sessions.
```

---

## 27. Release notes draft

```markdown
## Agent Mailbox

Claude Deck now includes Agent Mailbox, a local coordination layer for multi-agent work. Agent Bridge sessions can appear as observed agents, and mailbox-enabled Claude Code/Codex sessions can list other agents, read and send messages, create handoffs, and reserve paths before editing. The feature includes a new Agent Mailbox page, local MCP server integration, Claude Code lifecycle hooks, and advisory file leases.

Agent Mailbox is local-only and stores its state in Claude Deck’s SQLite database. Existing sessions may need to be restarted or have MCP configuration reloaded before mailbox tools appear.
```

---

## 28. Future phases after MVP

### Phase 2A — Hosted HTTP MCP endpoint

If the backend can host MCP over HTTP cleanly:

```text
POST/GET http://127.0.0.1:8000/mcp/agent-mailbox
```

Benefits:

- No stdio wrapper process per agent.
- Easier versioning.
- Better connection visibility.

Keep stdio shim as compatibility path.

### Phase 2B — WebSocket/SSE realtime UI

Replace polling with event stream.

### Phase 2C — Rich attachments

Add small text artifacts or links to local files. Do not add binary blobs in v1.

### Phase 2D — Stronger lease enforcement

Strict PreToolUse guards:

- Project-level policies.
- Human override.
- Temporary override token.
- Better Bash path extraction.

### Phase 2E — Worktree awareness

Show branch/worktree per agent and warn on shared working tree edits.

### Phase 2F — Agent roles and team templates

Allow user-defined roles:

```text
frontend
backend
tests
reviewer
docs
```

Add template messages and default lease scopes.

### Phase 2G — Summaries

Generate optional thread/handoff summaries from stored messages. Keep local and explicit.

---

## 29. Common pitfalls

### Pitfall: Creating a separate mailbox daemon

Do not. Claude Deck already has the backend, UI, SQLite, MCP management, hooks, and Agent Bridge. The mailbox should be part of Claude Deck.

### Pitfall: Depending only on MCP for discovery

Do not. MCP only tells you about sessions that loaded the server. Agent Bridge should populate observed sessions first.

### Pitfall: Treating observed sessions as reachable

Observed sessions may be visible but cannot receive MCP messages. The UI and tools should distinguish this from connected sessions.

### Pitfall: Blocking file edits by default

Do not. Advisory leases are safer. Blocking should be opt-in and tested.

### Pitfall: Storing secrets in project config

Do not write raw tokens into `.mcp.json`.

### Pitfall: Assuming running sessions reload MCP config

Warn that existing sessions may need restart/reload.

### Pitfall: Sharing transcripts through MCP tools

Do not expose raw transcript data to agents. Use messages/handoffs.

### Pitfall: Logging huge hook payloads

Store small summaries, redacted payloads, and essential metadata only.

---

## 30. Final MVP acceptance criteria

The feature is MVP-complete when all of the following are true:

1. Claude Deck starts normally with an existing database.
2. New mailbox tables are created without destructive migration.
3. `/api/v1/agent-mailbox/agents` returns an empty list on a fresh install.
4. Agent Bridge sessions appear as `observed` agents.
5. Mailbox MCP/hook registration upgrades an observed agent to `connected`.
6. Connected agents can call MCP tools to:
   - identify themselves,
   - list other agents,
   - set status,
   - send messages,
   - read inbox,
   - ack messages,
   - reserve paths,
   - check path conflicts,
   - release leases.
7. The UI shows agents, threads, messages, leases, and install coverage.
8. Config installation uses preview/confirmation and does not expose raw token in project config.
9. Hook failures do not break Claude Code when Claude Deck is unavailable.
10. Existing MCP, Hooks, Agent Bridge, Presence, Sessions, and Config pages still work.
11. Backend tests pass.
12. Frontend build passes.
13. Documentation explains setup, behavior, security, and limitations.

---

## 31. Reference facts used while preparing this plan

These references are for the human maintainer and for implementation context. Codex should still inspect the current repository because code may have changed.

- Claude Deck repository: `https://github.com/adrirubio/claude-deck`
- Claude Deck docs: `https://claudedeck.org/docs/`
- Claude Deck API overview: `https://claudedeck.org/docs/api/`
- Claude Deck MCP Servers docs: `https://claudedeck.org/docs/features/mcp-servers`
- Claude Deck Agent Bridge docs: `https://claudedeck.org/docs/features/agent-bridge`
- Claude Deck Hooks docs: `https://claudedeck.org/docs/features/hooks`
- Anthropic Claude Code MCP docs: `https://docs.anthropic.com/en/docs/claude-code/mcp`
- Anthropic Claude Code Hooks docs: `https://docs.anthropic.com/en/docs/claude-code/hooks`
- MCP overview: `https://modelcontextprotocol.io/docs/getting-started/intro`
- MCP tools specification: `https://modelcontextprotocol.io/specification/2025-03-26/server/tools`
