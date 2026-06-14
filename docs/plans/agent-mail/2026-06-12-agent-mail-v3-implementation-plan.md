# Agent Mail v3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let local Claude Code / Codex CLI sessions coordinate as a user-directed team — durable per-repo team identities, structured context requests and handoffs, state-based delivery into agent context — with one-click install and an operational (non-chat) UI.

**Architecture:** Claude Deck's backend owns all coordination state in SQLite (4 new tables). Agents interact through (a) a standalone MCP stdio shim (`deck_*` tools) that calls Deck's REST API, and (b) Claude Code hooks implemented as `curl` command hooks whose JSON responses inject roster/inbox context into the agent's conversation at `SessionStart` (including post-compaction) and `UserPromptSubmit`. Identity is durable: a **team member** is keyed by repo (worktree-aware `repo_id`); ephemeral sessions attach to members, so roles, charters and inboxes survive session restarts and context compaction.

**Tech Stack:** FastAPI + async SQLAlchemy + aiosqlite (existing), `mcp` Python SDK (new dep, official), httpx (existing), React 19 + TypeScript + shadcn/ui (existing).

**Changes from v2** (fixes from `2026-06-12-agent-mail-v2-review-for-patching.md`): (1) `scope="user"` on every `HookCreate` — it's a required field; (2) handoff roots close when their recipient acks them; (3) Codex gets one-click MCP install via the existing provider CLI executor; (4) install/uninstall require `{"confirmed": true}`, the UI shows a confirm dialog listing exact file mutations, and a best-effort backup is taken first; (5) the curl hook-output delivery assumption is verified by an early spike (Task 1.5) before anything is built on it; (6) Team/Requests tabs ship with status filters and repo search; (7) machine-global visibility and one-member-per-repo are documented as explicit MVP limits, with a same-repo smoke test; (8) session rows render compactly with source badges under one member; (9) `counts_for_member` uses SQL `count()`; (10) the `mcp` dependency is added to both `requirements.txt` and `pyproject.toml`.

---

## Design decisions (locked during review — do not relitigate while implementing)

1. **Machine-global visibility.** All members are mutually visible; repo is a label/filter, not a boundary. No "scopes/workspaces" concept in MVP.
2. **Durable team members, ephemeral sessions.** `MailTeamMember` keyed by `repo_id` (one member per repo in MVP); `MailAgentSession` rows (hook / mcp / observed sources) attach to members. Director-assigned name/role/charter live on the member. Messages address members, never sessions — a message to a member whose session died waits in the inbox.
3. **State-based, idempotent delivery.** Injections describe current state ("1 unanswered context request"), never events. `SessionStart` hook fires on `startup|resume|clear|compact` sources, so post-compaction recovery is automatic. `read ≠ handled`: receipts track read; request-kind messages carry their own lifecycle that re-surfaces until resolved. Lifecycle per kind: `context_request` = pending → answered (recipient replies) → acknowledged (requester acks the answer); `handoff` = pending → acknowledged when its recipient acks it (accepted) — completion reports are plain thread replies.
4. **Structured requests are the hero.** Message kinds: `message`, `broadcast`, `context_request`, `handoff`, `answer`. Generic chat is secondary.
5. **No path leases, no PreToolUse guard, no Notification hook, no events audit table, no token auth in MVP.** Leases are Phase 2. Token rationale: Deck's existing API already exposes unauthenticated config-mutating endpoints (hooks, MCP) and the Presence `/events` endpoint is unauthenticated — a mailbox-only token is false security. Hardening (bind `127.0.0.1`, optional token) is a separate, whole-app concern; note it in docs as a limitation.
6. **Hooks are `curl` command hooks** (no wrapper script): payload arrives on the hook's stdin, `--data-binary @-` posts it, the endpoint's JSON response body goes to stdout, and Claude Code parses command-hook stdout JSON (`hookSpecificOutput.additionalContext`). `|| true` makes every failure soft. Events: `SessionStart`, `UserPromptSubmit`, `SessionEnd`, `PostToolUse` (matcher `Edit|Write|MultiEdit|NotebookEdit`). All four already exist in `VALID_HOOK_EVENTS` (`backend/app/models/schemas.py:551`).
7. **MCP shim is standalone** (`backend/mcp_shim/agent_mail_server.py`): imports only `mcp` + `httpx`, never `app.*`, so it runs from any cwd via the backend venv's python. 8 tools: `deck_whoami`, `deck_list_team`, `deck_check_inbox`, `deck_send_message`, `deck_reply`, `deck_ack_message`, `deck_request_context`, `deck_create_handoff`. Every tool response piggybacks `unread_count`/`pending_count`.
8. **Provider tiers.** Claude Code: one-click install (4 hooks user-scope via `hook_service`, MCP server user-scope via `mcp_service`). Codex CLI: one-click MCP install via the existing provider CLI executor (the `POST /providers/{id}/mcp` pattern in `backend/app/api/v1/providers.py:484` shells out to `codex mcp add`); lifecycle hooks remain unsupported for Codex; `AGENTS.md` stays a copy-paste snippet. Observed-only sessions come free via `discover_agent_sessions()`.
9. **Timestamps:** naive UTC via `datetime.utcnow` (matches `Project`/`Backup` models). **IDs:** `Integer` autoincrement PKs (repo convention; not ULIDs).

## Repo conventions the implementer must follow (verified 2026-06-12)

| Concern | Fact |
|---|---|
| ORM | `Mapped[...]`/`mapped_column` style in single file `backend/app/models/database.py`; `Base` from `app.database`; tables created by `init_db()` `create_all` (no migrations — **new tables only, never alter existing**) |
| Schemas | All Pydantic models in `backend/app/models/schemas.py`, snake_case fields, no camelCase aliasing |
| Routers | `backend/app/api/v1/agent_mail.py`, registered in `backend/app/api/v1/router.py` via `router.include_router(agent_mail_router, prefix="/agent-mail", tags=["Agent Mail"])`; DB via `db: AsyncSession = Depends(get_db)` |
| Agent Bridge | `discover_agent_sessions(provider_id=None)` in `backend/app/services/agent_bridge/discovery.py` — **sync**, returns dicts with keys `provider, provider_display_name, tmux_target, session_name, window_name, pane_id, cwd, pid (str), status` |
| Hook mgmt | `HookService().add_hook(hook: HookCreate, project_path=None)`, `list_hooks(project_path=None)`, `remove_hook(...)` — sync. `HookCreate(event, matcher=None, type="command", command=...)` |
| MCP mgmt | `MCPService().add_server(server: MCPServerCreate, project_path=None)` / `remove_server` — async. Stdio config keys: `type, command, args, env` |
| Presence precedent | `/api/v1/presence/events` accepts unauthenticated hook posts; `PresenceSession` model is the style reference for session-ish tables |
| Tests | `backend/tests/`, no global conftest; sync tests use `unittest.mock.patch`; `pytest-asyncio` is installed → async tests need `@pytest.mark.asyncio` + `@pytest_asyncio.fixture`. Run: `cd backend && source venv/bin/activate && pytest tests/` |
| Frontend API | `apiClient<T>(endpoint, options?)` callable from `@/lib/api`; endpoints relative, **no leading slash** (base is `/api/v1/`) |
| Frontend types | Shared dir `frontend/src/types/*.ts`, fields stay **snake_case** mirroring backend |
| Routes/nav | Route in `frontend/src/App.tsx` inside `<Route path="/" element={<MainLayout />}>`; nav item in `frontend/src/components/layout/Sidebar.tsx` (`{ name, href, icon }`, lucide icons) |
| UI kit | shadcn in `src/components/ui/` (alert-dialog, badge, button, card, dialog, input, label, select, tabs, textarea, scroll-area available); `CLICKABLE_CARD`, `MODAL_SIZES` from `@/lib/constants`; `MarkdownRenderer` from `@/components/shared/MarkdownRenderer` |
| Codex MCP mutation | `ProviderCLIExecutor("codex-cli")` from `app.services.cli_executor`; `executor.execute("mcp", args, timeout=30)`; add-args shape (providers.py:248): `["add", "--env", "K=V", ..., name, "--", command, *args]`; every arg must match the executor's `SAFE_ARG_PATTERN` (alphanumerics plus `_./@:+,=%?#&-` — no spaces or quotes) |
| Backups | `BackupService(db).create_backup(name=..., scope=...)` — async, scope `"user"` or `"codex"`, returns `(Backup, BackupManifest)` |

## File map

**Create**
- `backend/app/utils/repo_utils.py` — repo identity derivation (worktree-aware)
- `backend/app/services/agent_mail_service.py` — registry + messaging + context builders
- `backend/app/services/agent_mail_install_service.py` — install status/apply/uninstall/snippets
- `backend/app/api/v1/agent_mail.py` — all `/agent-mail/*` endpoints
- `backend/mcp_shim/agent_mail_server.py` — standalone MCP stdio server
- `backend/tests/agent_mail/conftest.py` + `test_repo_utils.py`, `test_registry.py`, `test_messaging.py`, `test_context.py`, `test_api.py`, `test_hooks_api.py`, `test_install.py`
- `frontend/src/types/agentMail.ts`
- `frontend/src/features/agent-mail/` — `api.ts`, `AgentMailPage.tsx`, `TeamTab.tsx`, `RequestsTab.tsx`, `InstallTab.tsx`, `MemberEditDialog.tsx`, `ComposeDialog.tsx`, `ThreadDialog.tsx`
- `docs/features/agent-mail.md`

**Modify**
- `backend/app/models/database.py` — append 4 models
- `backend/app/models/schemas.py` — append Agent Mail schemas
- `backend/app/api/v1/router.py` — include router
- `backend/requirements.txt` — add `mcp>=1.2.0`
- `frontend/src/App.tsx`, `frontend/src/components/layout/Sidebar.tsx` — route + nav
- `README.md` — one feature line

---

### Task 1: Repo identity helper

Worktrees of the same repo must map to the same `repo_id`; non-git dirs fall back to the normalized path.

**Files:**
- Create: `backend/app/utils/repo_utils.py`
- Create: `backend/tests/agent_mail/__init__.py` (empty), `backend/tests/agent_mail/test_repo_utils.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/agent_mail/test_repo_utils.py
"""Tests for repo identity derivation."""
import subprocess

from app.utils.repo_utils import derive_repo_identity


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_non_git_dir_uses_normalized_path(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    ident = derive_repo_identity(str(d))
    assert ident["repo_name"] == "plain"
    assert ident["repo_root"] == str(d.resolve())
    assert len(ident["repo_id"]) == 16


def test_same_dir_is_stable(tmp_path):
    d = tmp_path / "stable"
    d.mkdir()
    assert derive_repo_identity(str(d)) == derive_repo_identity(str(d))


def test_worktrees_share_repo_id(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    _git(["init", "-b", "master"], main)
    (main / "f.txt").write_text("x")
    _git(["add", "."], main)
    _git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init"], main)
    wt = tmp_path / "wt"
    _git(["worktree", "add", "-b", "feature", str(wt)], main)

    a = derive_repo_identity(str(main))
    b = derive_repo_identity(str(wt))
    assert a["repo_id"] == b["repo_id"]
    assert a["repo_name"] == "main"


def test_missing_dir_does_not_crash(tmp_path):
    ident = derive_repo_identity(str(tmp_path / "nope"))
    assert ident["repo_id"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_mail/test_repo_utils.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.utils.repo_utils'`

- [ ] **Step 3: Implement**

```python
# backend/app/utils/repo_utils.py
"""Derive a stable repository identity from a working directory.

Worktrees of the same repository share a git common dir, so hashing that
path gives every worktree the same repo_id while plain directories fall
back to their own normalized path.
"""
import hashlib
import logging
import os
import subprocess

logger = logging.getLogger(__name__)


def derive_repo_identity(cwd: str) -> dict:
    """Return {"repo_id", "repo_root", "repo_name"} for a working directory."""
    norm = os.path.realpath(os.path.expanduser(cwd or "."))
    anchor = norm
    repo_root = norm
    try:
        result = subprocess.run(
            ["git", "-C", norm, "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            anchor = os.path.realpath(result.stdout.strip())
            repo_root = os.path.dirname(anchor) if anchor.endswith(f"{os.sep}.git") else anchor
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("git common-dir lookup failed for %s: %s", norm, exc)

    repo_id = hashlib.sha1(anchor.encode("utf-8")).hexdigest()[:16]
    return {
        "repo_id": repo_id,
        "repo_root": repo_root,
        "repo_name": os.path.basename(repo_root) or repo_root,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agent_mail/test_repo_utils.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/utils/repo_utils.py backend/tests/agent_mail/
git commit -m "feat: add worktree-aware repo identity helper for agent mail"
```

---

### Task 1.5: SPIKE — verify curl command-hook context injection (BEFORE building on it)

The entire delivery design assumes: a `command` hook printing JSON to stdout has that JSON parsed by Claude Code, and `hookSpecificOutput.additionalContext` reaches the model. Verify it now, manually, in ~15 minutes — six later tasks depend on it.

- [ ] **Step 1: Add a throwaway hook** to `~/.claude/settings.json` (copy the file aside first):

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "echo '{\"hookSpecificOutput\":{\"hookEventName\":\"SessionStart\",\"additionalContext\":\"AGENT MAIL SPIKE MARKER 12321\"}}'"
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 2: Start a fresh Claude Code session** and ask: "What did your SessionStart hook context say?"

Expected: the model can repeat `AGENT MAIL SPIKE MARKER 12321`.

- [ ] **Step 3: Repeat for UserPromptSubmit** — same echo command with `"hookEventName":"UserPromptSubmit"` under a `UserPromptSubmit` hook entry; send any prompt and confirm the marker is visible to the model.

- [ ] **Step 4: Remove the throwaway hooks** and restore the original settings file.

- [ ] **Step 5: Record the outcome** by editing this task in place (PASS/FAIL + Claude Code version). If FAIL: stop and switch the delivery strategy to a small wrapper script (`scripts/agent-mail-hook.sh`: read stdin, `curl --data-binary @-` to the endpoint, print the response body to stdout) — the backend endpoints already return the correct JSON shape, so nothing else in this plan changes.

---

### Task 2: Models, schemas, and async test fixture

**Files:**
- Modify: `backend/app/models/database.py` (append at end)
- Modify: `backend/app/models/schemas.py` (append at end)
- Create: `backend/tests/agent_mail/conftest.py`
- Create: `backend/tests/agent_mail/test_models.py`

- [ ] **Step 1: Write the async DB fixture**

```python
# backend/tests/agent_mail/conftest.py
"""Local fixtures for agent mail tests (kept out of global scope on purpose)."""
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models.database  # noqa: F401  (registers models on Base.metadata)
from app.database import Base


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()
```

- [ ] **Step 2: Write the failing model test**

```python
# backend/tests/agent_mail/test_models.py
"""Smoke test: agent mail tables exist and accept rows."""
import pytest

from app.models.database import MailAgentSession, MailMessage, MailReceipt, MailTeamMember


@pytest.mark.asyncio
async def test_tables_create_and_accept_rows(db):
    member = MailTeamMember(
        repo_id="abc123", repo_path="/tmp/r", repo_name="r", display_name="r"
    )
    db.add(member)
    await db.flush()

    db.add(MailAgentSession(member_id=member.id, source="hook", session_key="cc:s1"))
    msg = MailMessage(kind="context_request", body_markdown="hi", request_status="pending",
                      recipient_member_id=member.id)
    db.add(msg)
    await db.flush()
    db.add(MailReceipt(message_id=msg.id, member_id=member.id))
    await db.commit()

    assert member.id and msg.id
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/agent_mail/test_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'MailTeamMember'`

- [ ] **Step 4: Append models to `backend/app/models/database.py`**

```python
class MailTeamMember(Base):
    """Durable Agent Mail team identity, keyed by repository (worktree-aware)."""

    __tablename__ = "mail_team_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repo_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    repo_path: Mapped[str] = mapped_column(String, nullable=False)
    repo_name: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str | None] = mapped_column(String, nullable=True)
    charter: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class MailAgentSession(Base):
    """Ephemeral agent session attached to a team member."""

    __tablename__ = "mail_agent_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    member_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mail_team_members.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String, default="unknown", nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)  # hook, mcp, observed
    session_key: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    cwd: Mapped[str | None] = mapped_column(String, nullable=True)
    tmux_target: Mapped[str | None] = mapped_column(String, nullable=True)
    pane_id: Mapped[str | None] = mapped_column(String, nullable=True)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mailbox_status: Mapped[str] = mapped_column(
        String, default="connected", nullable=False
    )  # observed, connected, offline
    activity: Mapped[str | None] = mapped_column(String, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class MailMessage(Base):
    """Agent Mail message. Request-kind rows carry their own lifecycle status."""

    __tablename__ = "mail_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_root_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("mail_messages.id", ondelete="CASCADE"), index=True, nullable=True
    )
    kind: Mapped[str] = mapped_column(
        String, default="message", nullable=False, index=True
    )  # message, broadcast, context_request, handoff, answer
    sender_member_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("mail_team_members.id", ondelete="SET NULL"), nullable=True
    )  # null = human director
    recipient_member_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("mail_team_members.id", ondelete="CASCADE"), index=True, nullable=True
    )  # null = broadcast to all members
    subject: Mapped[str | None] = mapped_column(String, nullable=True)
    body_markdown: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    request_status: Mapped[str | None] = mapped_column(
        String, nullable=True, index=True
    )  # pending, answered, acknowledged (request kinds only)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )


class MailReceipt(Base):
    """Per-recipient read/ack state for a message."""

    __tablename__ = "mail_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mail_messages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    member_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mail_team_members.id", ondelete="CASCADE"), index=True, nullable=False
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("message_id", "member_id", name="uix_mail_receipt_message_member"),
    )
```

- [ ] **Step 5: Append schemas to `backend/app/models/schemas.py`**

```python
# --- Agent Mail ---

MAIL_MESSAGE_KINDS = ["message", "broadcast", "context_request", "handoff", "answer"]
MAIL_REQUEST_KINDS = ["context_request", "handoff"]


class MailSessionResponse(BaseModel):
    """One live/observed agent session attached to a member."""

    id: int
    provider: str
    source: str  # hook, mcp, observed
    session_key: str
    cwd: Optional[str] = None
    tmux_target: Optional[str] = None
    mailbox_status: str  # observed, connected, offline
    activity: Optional[str] = None
    last_seen_at: Optional[datetime] = None


class MailMemberResponse(BaseModel):
    """Durable team member with derived status and inbox counts."""

    id: int
    repo_id: str
    repo_path: str
    repo_name: str
    display_name: str
    role: Optional[str] = None
    charter: Optional[str] = None
    status: str  # connected, observed, offline (best of live sessions)
    unread_count: int = 0
    pending_count: int = 0
    sessions: List[MailSessionResponse] = []


class TeamListResponse(BaseModel):
    members: List[MailMemberResponse]


class MailMemberUpdate(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    charter: Optional[str] = None


class MailMessageCreate(BaseModel):
    kind: str = "message"
    sender_member_id: Optional[int] = None  # null = human director
    recipient_member_id: Optional[int] = None  # null = broadcast to all members
    thread_root_id: Optional[int] = None
    subject: Optional[str] = None
    body_markdown: str
    payload: Optional[Dict[str, Any]] = None  # files, next_steps, topic, why_needed


class MailMessageResponse(BaseModel):
    id: int
    thread_root_id: Optional[int] = None
    kind: str
    sender_member_id: Optional[int] = None
    sender_name: str  # "Director" when sender_member_id is null
    recipient_member_id: Optional[int] = None
    subject: Optional[str] = None
    body_markdown: str
    payload: Optional[Dict[str, Any]] = None
    request_status: Optional[str] = None
    is_stale: bool = False
    read_at: Optional[datetime] = None
    acked_at: Optional[datetime] = None
    created_at: datetime


class MailThreadResponse(BaseModel):
    root: MailMessageResponse
    replies: List[MailMessageResponse]


class MailInboxResponse(BaseModel):
    member_id: int
    unread_count: int
    pending_count: int
    messages: List[MailMessageResponse]


class MailAgentRegisterRequest(BaseModel):
    source: str  # hook, mcp
    provider: str = "unknown"
    cwd: str
    session_key: str
    pid: Optional[int] = None


class MailAgentRegisterResponse(BaseModel):
    member: MailMemberResponse
    session: MailSessionResponse


class AgentMailInstallStatus(BaseModel):
    claude_code_hooks: List[str]  # installed agent-mail hook events
    claude_code_hooks_missing: List[str]
    claude_code_mcp_installed: bool
    codex_cli_available: bool
    codex_mcp_installed: bool
    curl_available: bool
    shim_path: str
    python_path: str
    deck_url: str


class AgentMailSnippets(BaseModel):
    codex_config_toml: str
    codex_agents_md: str
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/agent_mail/test_models.py -v`
Expected: 1 passed

- [ ] **Step 7: Verify backend still boots with existing DB** (tables are additive)

Run: `cd backend && source venv/bin/activate && python -c "import asyncio; from app.database import init_db; asyncio.run(init_db()); print('ok')"`
Expected: `ok`

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/database.py backend/app/models/schemas.py backend/tests/agent_mail/
git commit -m "feat: add agent mail models and schemas"
```

---

### Task 3: Registry service (members, sessions, observed sync, staleness)

**Files:**
- Create: `backend/app/services/agent_mail_service.py`
- Create: `backend/tests/agent_mail/test_registry.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/agent_mail/test_registry.py
"""Registry behavior: durable members, ephemeral sessions, observed sync, staleness."""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.models.schemas import MailAgentRegisterRequest
from app.services.agent_mail_service import HEARTBEAT_TTL_SECONDS, AgentMailService


@pytest.fixture
def svc():
    return AgentMailService()


def _register(cwd, session_key="cc:s1", source="hook", provider="claude-code", pid=None):
    return MailAgentRegisterRequest(
        source=source, provider=provider, cwd=cwd, session_key=session_key, pid=pid
    )


@pytest.mark.asyncio
async def test_register_creates_member_named_after_repo(db, svc, tmp_path):
    member, session = await svc.register_session(db, _register(str(tmp_path / "myrepo")))
    assert member.display_name == "myrepo"
    assert session.mailbox_status == "connected"
    assert session.member_id == member.id


@pytest.mark.asyncio
async def test_second_session_same_repo_reuses_member(db, svc, tmp_path):
    cwd = str(tmp_path / "r")
    m1, _ = await svc.register_session(db, _register(cwd, session_key="cc:s1"))
    m2, s2 = await svc.register_session(db, _register(cwd, session_key="mcp:abc", source="mcp"))
    assert m1.id == m2.id
    assert s2.session_key == "mcp:abc"


@pytest.mark.asyncio
async def test_reregister_same_session_key_updates_not_duplicates(db, svc, tmp_path):
    cwd = str(tmp_path / "r")
    _, s1 = await svc.register_session(db, _register(cwd))
    _, s2 = await svc.register_session(db, _register(cwd))
    assert s1.id == s2.id


@pytest.mark.asyncio
async def test_member_identity_survives_session_end(db, svc, tmp_path):
    cwd = str(tmp_path / "r")
    member, _ = await svc.register_session(db, _register(cwd))
    member.role = "backend expert"
    await db.commit()
    await svc.mark_session_offline(db, "cc:s1")
    m2, _ = await svc.register_session(db, _register(cwd, session_key="cc:s2"))
    assert m2.id == member.id
    assert m2.role == "backend expert"


@pytest.mark.asyncio
async def test_sync_observed_creates_observed_sessions(db, svc, tmp_path):
    fake = [{
        "provider": "codex-cli", "provider_display_name": "Codex",
        "tmux_target": "w:0.1", "session_name": "w", "window_name": "main",
        "pane_id": "%7", "cwd": str(tmp_path / "obs"), "pid": "4242", "status": "active",
    }]
    with patch("app.services.agent_mail_service.discover_agent_sessions", return_value=fake):
        await svc.sync_observed_sessions(db)
    members = await svc.list_team(db)
    assert len(members) == 1
    assert members[0].status == "observed"
    assert members[0].sessions[0].session_key == "tmux:%7"


@pytest.mark.asyncio
async def test_stale_connected_session_reports_offline(db, svc, tmp_path):
    member, session = await svc.register_session(db, _register(str(tmp_path / "r")))
    session.last_seen_at = datetime.utcnow() - timedelta(seconds=HEARTBEAT_TTL_SECONDS + 60)
    await db.commit()
    members = await svc.list_team(db)
    assert members[0].status == "offline"


@pytest.mark.asyncio
async def test_heartbeat_refreshes_and_sets_activity(db, svc, tmp_path):
    member, session = await svc.register_session(db, _register(str(tmp_path / "r")))
    session.last_seen_at = datetime.utcnow() - timedelta(seconds=HEARTBEAT_TTL_SECONDS + 60)
    await db.commit()
    await svc.heartbeat_session(db, "cc:s1", activity="edited src/main.py")
    members = await svc.list_team(db)
    assert members[0].status == "connected"
    assert members[0].sessions[0].activity == "edited src/main.py"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agent_mail/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.agent_mail_service'`

- [ ] **Step 3: Implement the registry half of the service**

```python
# backend/app/services/agent_mail_service.py
"""Agent Mail: durable team members, ephemeral sessions, messages, delivery context."""
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import MailAgentSession, MailMessage, MailReceipt, MailTeamMember
from app.models.schemas import (
    MAIL_REQUEST_KINDS,
    MailAgentRegisterRequest,
    MailInboxResponse,
    MailMemberResponse,
    MailMessageCreate,
    MailMessageResponse,
    MailSessionResponse,
    MailThreadResponse,
)
from app.services.agent_bridge.discovery import discover_agent_sessions
from app.utils.repo_utils import derive_repo_identity

logger = logging.getLogger(__name__)

HEARTBEAT_TTL_SECONDS = 180   # connected session with no heartbeat for this long shows offline
OBSERVED_TTL_SECONDS = 300    # observed session not re-discovered for this long shows offline
STALE_REQUEST_MINUTES = 15    # pending request older than this is flagged stale in the UI


class AgentMailService:
    # ---------- registry ----------

    async def _get_or_create_member(self, db: AsyncSession, cwd: str) -> MailTeamMember:
        ident = derive_repo_identity(cwd)
        result = await db.execute(
            select(MailTeamMember).where(MailTeamMember.repo_id == ident["repo_id"])
        )
        member = result.scalar_one_or_none()
        if member is None:
            member = MailTeamMember(
                repo_id=ident["repo_id"],
                repo_path=ident["repo_root"],
                repo_name=ident["repo_name"],
                display_name=ident["repo_name"],
            )
            db.add(member)
            await db.flush()
        return member

    async def register_session(
        self, db: AsyncSession, request: MailAgentRegisterRequest
    ) -> tuple[MailTeamMember, MailAgentSession]:
        member = await self._get_or_create_member(db, request.cwd)
        result = await db.execute(
            select(MailAgentSession).where(MailAgentSession.session_key == request.session_key)
        )
        session = result.scalar_one_or_none()
        if session is None:
            session = MailAgentSession(
                member_id=member.id,
                source=request.source,
                session_key=request.session_key,
            )
            db.add(session)
        session.member_id = member.id
        session.provider = request.provider
        session.cwd = request.cwd
        session.pid = request.pid
        session.mailbox_status = "connected"
        session.last_seen_at = datetime.utcnow()
        await db.commit()
        await db.refresh(member)
        await db.refresh(session)
        return member, session

    async def heartbeat_session(
        self, db: AsyncSession, session_key: str, activity: Optional[str] = None
    ) -> Optional[MailAgentSession]:
        result = await db.execute(
            select(MailAgentSession).where(MailAgentSession.session_key == session_key)
        )
        session = result.scalar_one_or_none()
        if session is None:
            return None
        session.last_seen_at = datetime.utcnow()
        session.mailbox_status = "connected" if session.source != "observed" else "observed"
        if activity:
            session.activity = activity[:200]
        await db.commit()
        return session

    async def mark_session_offline(self, db: AsyncSession, session_key: str) -> None:
        result = await db.execute(
            select(MailAgentSession).where(MailAgentSession.session_key == session_key)
        )
        session = result.scalar_one_or_none()
        if session is not None:
            session.mailbox_status = "offline"
            await db.commit()

    async def sync_observed_sessions(self, db: AsyncSession) -> None:
        """Upsert Agent Bridge tmux discoveries as observed sessions."""
        try:
            discovered = discover_agent_sessions()
        except Exception as exc:  # discovery must never break the mailbox
            logger.warning("agent bridge discovery failed: %s", exc)
            return
        for info in discovered:
            pane_id = info.get("pane_id")
            cwd = info.get("cwd")
            if not pane_id or not cwd:
                continue
            member = await self._get_or_create_member(db, cwd)
            session_key = f"tmux:{pane_id}"
            result = await db.execute(
                select(MailAgentSession).where(MailAgentSession.session_key == session_key)
            )
            session = result.scalar_one_or_none()
            if session is None:
                session = MailAgentSession(
                    member_id=member.id, source="observed", session_key=session_key
                )
                db.add(session)
            session.member_id = member.id
            session.provider = info.get("provider", "unknown")
            session.cwd = cwd
            session.tmux_target = info.get("tmux_target")
            session.pane_id = pane_id
            try:
                session.pid = int(info.get("pid") or 0) or None
            except (TypeError, ValueError):
                session.pid = None
            session.mailbox_status = "observed"
            session.last_seen_at = datetime.utcnow()
        await db.commit()

    def _effective_status(self, session: MailAgentSession, now: datetime) -> str:
        if session.mailbox_status == "offline":
            return "offline"
        ttl = OBSERVED_TTL_SECONDS if session.source == "observed" else HEARTBEAT_TTL_SECONDS
        if session.last_seen_at < now - timedelta(seconds=ttl):
            return "offline"
        return session.mailbox_status

    def _session_response(self, session: MailAgentSession, now: datetime) -> MailSessionResponse:
        return MailSessionResponse(
            id=session.id,
            provider=session.provider,
            source=session.source,
            session_key=session.session_key,
            cwd=session.cwd,
            tmux_target=session.tmux_target,
            mailbox_status=self._effective_status(session, now),
            activity=session.activity,
            last_seen_at=session.last_seen_at,
        )

    async def list_team(self, db: AsyncSession) -> List[MailMemberResponse]:
        now = datetime.utcnow()
        members = (await db.execute(select(MailTeamMember))).scalars().all()
        sessions = (await db.execute(select(MailAgentSession))).scalars().all()
        by_member: dict[int, list[MailAgentSession]] = {}
        for s in sessions:
            by_member.setdefault(s.member_id, []).append(s)

        responses: List[MailMemberResponse] = []
        for member in members:
            session_responses = [
                self._session_response(s, now) for s in by_member.get(member.id, [])
            ]
            statuses = {s.mailbox_status for s in session_responses}
            if "connected" in statuses:
                status = "connected"
            elif "observed" in statuses:
                status = "observed"
            else:
                status = "offline"
            unread, pending = await self.counts_for_member(db, member.id)
            responses.append(
                MailMemberResponse(
                    id=member.id,
                    repo_id=member.repo_id,
                    repo_path=member.repo_path,
                    repo_name=member.repo_name,
                    display_name=member.display_name,
                    role=member.role,
                    charter=member.charter,
                    status=status,
                    unread_count=unread,
                    pending_count=pending,
                    sessions=session_responses,
                )
            )
        responses.sort(key=lambda m: (m.status != "connected", m.display_name.lower()))
        return responses


agent_mail_service = AgentMailService()
```

Note: `counts_for_member` is implemented in Task 4 — for this task add a temporary stub at the end of the class so registry tests pass:

```python
    async def counts_for_member(self, db: AsyncSession, member_id: int) -> tuple[int, int]:
        return 0, 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agent_mail/test_registry.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent_mail_service.py backend/tests/agent_mail/test_registry.py
git commit -m "feat: add agent mail registry service (members, sessions, observed sync)"
```

---

### Task 4: Messaging service (send, inbox, receipts, request lifecycle)

**Files:**
- Modify: `backend/app/services/agent_mail_service.py` (replace the `counts_for_member` stub, add messaging section)
- Create: `backend/tests/agent_mail/test_messaging.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/agent_mail/test_messaging.py
"""Messaging: receipts, broadcast, request lifecycle, stale flag, counts."""
from datetime import datetime, timedelta

import pytest

from app.models.database import MailTeamMember
from app.models.schemas import MailMessageCreate
from app.services.agent_mail_service import AgentMailService


@pytest.fixture
def svc():
    return AgentMailService()


async def _member(db, repo_id, name):
    m = MailTeamMember(repo_id=repo_id, repo_path=f"/tmp/{name}", repo_name=name, display_name=name)
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


@pytest.mark.asyncio
async def test_direct_message_lands_in_recipient_inbox_only(db, svc):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    msg = await svc.send_message(db, MailMessageCreate(
        sender_member_id=a.id, recipient_member_id=b.id,
        subject="hi", body_markdown="ping"))
    inbox_b = await svc.get_inbox(db, b.id)
    inbox_a = await svc.get_inbox(db, a.id)
    assert [m.id for m in inbox_b.messages] == [msg.id]
    assert inbox_a.messages == []


@pytest.mark.asyncio
async def test_broadcast_targets_everyone_except_sender(db, svc):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    c = await _member(db, "rc", "gamma")
    await svc.send_message(db, MailMessageCreate(
        kind="broadcast", sender_member_id=a.id, body_markdown="all hands"))
    assert (await svc.get_inbox(db, b.id)).unread_count == 1
    assert (await svc.get_inbox(db, c.id)).unread_count == 1
    assert (await svc.get_inbox(db, a.id)).unread_count == 0


@pytest.mark.asyncio
async def test_human_director_message_has_director_sender_name(db, svc):
    b = await _member(db, "rb", "beta")
    await svc.send_message(db, MailMessageCreate(
        recipient_member_id=b.id, body_markdown="please review"))
    inbox = await svc.get_inbox(db, b.id)
    assert inbox.messages[0].sender_name == "Director"


@pytest.mark.asyncio
async def test_mark_read_clears_unread_count(db, svc):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    msg = await svc.send_message(db, MailMessageCreate(
        sender_member_id=a.id, recipient_member_id=b.id, body_markdown="x"))
    await svc.mark_read(db, msg.id, b.id)
    assert (await svc.get_inbox(db, b.id)).unread_count == 0


@pytest.mark.asyncio
async def test_context_request_lifecycle_pending_answered_acknowledged(db, svc):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    req = await svc.send_message(db, MailMessageCreate(
        kind="context_request", sender_member_id=a.id, recipient_member_id=b.id,
        subject="How does auth refresh work?", body_markdown="Need it for retry wiring.",
        payload={"files_or_symbols": ["app/auth/session.py"]}))
    assert req.request_status == "pending"

    answer = await svc.send_message(db, MailMessageCreate(
        kind="answer", sender_member_id=b.id, thread_root_id=req.id,
        body_markdown="Refresh happens in session middleware."))
    thread = await svc.get_thread(db, req.id)
    assert thread.root.request_status == "answered"

    # requester acknowledges the answer -> root closes
    await svc.ack_message(db, answer.id, a.id)
    thread = await svc.get_thread(db, req.id)
    assert thread.root.request_status == "acknowledged"


@pytest.mark.asyncio
async def test_handoff_ack_by_recipient_closes_it(db, svc):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    handoff = await svc.send_message(db, MailMessageCreate(
        kind="handoff", sender_member_id=a.id, recipient_member_id=b.id,
        subject="take over auth", body_markdown="## Handoff"))
    assert handoff.request_status == "pending"

    await svc.ack_message(db, handoff.id, b.id)
    thread = await svc.get_thread(db, handoff.id)
    assert thread.root.request_status == "acknowledged"
    unread, pending = await svc.counts_for_member(db, b.id)
    assert pending == 0


@pytest.mark.asyncio
async def test_handoff_ack_by_unrelated_member_does_not_close_it(db, svc):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    c = await _member(db, "rc", "gamma")
    handoff = await svc.send_message(db, MailMessageCreate(
        kind="handoff", sender_member_id=a.id, recipient_member_id=b.id,
        subject="take over auth", body_markdown="## Handoff"))
    await svc.ack_message(db, handoff.id, c.id)  # c has no receipt -> no-op
    thread = await svc.get_thread(db, handoff.id)
    assert thread.root.request_status == "pending"


@pytest.mark.asyncio
async def test_answer_is_delivered_back_to_requester(db, svc):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    req = await svc.send_message(db, MailMessageCreate(
        kind="context_request", sender_member_id=a.id, recipient_member_id=b.id,
        subject="q", body_markdown="?"))
    await svc.send_message(db, MailMessageCreate(
        kind="answer", sender_member_id=b.id, thread_root_id=req.id, body_markdown="!"))
    inbox_a = await svc.get_inbox(db, a.id)
    assert inbox_a.unread_count == 1
    assert inbox_a.messages[0].kind == "answer"


@pytest.mark.asyncio
async def test_old_pending_request_is_stale(db, svc):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    req = await svc.send_message(db, MailMessageCreate(
        kind="context_request", sender_member_id=a.id, recipient_member_id=b.id,
        subject="q", body_markdown="?"))
    from app.models.database import MailMessage
    row = await db.get(MailMessage, req.id)
    row.created_at = datetime.utcnow() - timedelta(minutes=30)
    await db.commit()
    inbox = await svc.get_inbox(db, b.id)
    assert inbox.messages[0].is_stale is True


@pytest.mark.asyncio
async def test_counts_for_member_pending_requests(db, svc):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    await svc.send_message(db, MailMessageCreate(
        kind="context_request", sender_member_id=a.id, recipient_member_id=b.id,
        subject="q", body_markdown="?"))
    unread, pending = await svc.counts_for_member(db, b.id)
    assert unread == 1
    assert pending == 1


@pytest.mark.asyncio
async def test_invalid_kind_rejected(db, svc):
    b = await _member(db, "rb", "beta")
    with pytest.raises(ValueError):
        await svc.send_message(db, MailMessageCreate(
            kind="telepathy", recipient_member_id=b.id, body_markdown="x"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agent_mail/test_messaging.py -v`
Expected: FAIL — `AttributeError: 'AgentMailService' object has no attribute 'send_message'`

- [ ] **Step 3: Implement messaging.** Delete the `counts_for_member` stub from Task 3 and add this section to `AgentMailService`:

```python
    # ---------- messaging ----------

    async def send_message(
        self, db: AsyncSession, request: MailMessageCreate
    ) -> MailMessageResponse:
        from app.models.schemas import MAIL_MESSAGE_KINDS  # local import avoids cycle on reload

        if request.kind not in MAIL_MESSAGE_KINDS:
            raise ValueError(f"Invalid message kind: {request.kind}")
        if request.kind == "answer" and request.thread_root_id is None:
            raise ValueError("answer messages require thread_root_id")
        if request.kind in MAIL_REQUEST_KINDS and request.recipient_member_id is None:
            raise ValueError(f"{request.kind} requires recipient_member_id")

        message = MailMessage(
            thread_root_id=request.thread_root_id,
            kind=request.kind,
            sender_member_id=request.sender_member_id,
            recipient_member_id=request.recipient_member_id,
            subject=request.subject,
            body_markdown=request.body_markdown,
            payload=request.payload,
            request_status="pending" if request.kind in MAIL_REQUEST_KINDS else None,
        )
        db.add(message)
        await db.flush()

        recipients: set[int] = set()
        if request.recipient_member_id is not None:
            recipients.add(request.recipient_member_id)
        elif request.thread_root_id is not None:
            root = await db.get(MailMessage, request.thread_root_id)
            if root is not None:
                for mid in (root.sender_member_id, root.recipient_member_id):
                    if mid is not None and mid != request.sender_member_id:
                        recipients.add(mid)
        else:  # broadcast
            members = (await db.execute(select(MailTeamMember))).scalars().all()
            recipients = {m.id for m in members if m.id != request.sender_member_id}

        for mid in recipients:
            db.add(MailReceipt(message_id=message.id, member_id=mid))

        if request.kind == "answer":
            root = await db.get(MailMessage, request.thread_root_id)
            if root is not None and root.request_status == "pending":
                root.request_status = "answered"

        await db.commit()
        await db.refresh(message)
        return await self._message_response(db, message, for_member_id=None)

    async def _sender_name(self, db: AsyncSession, sender_member_id: Optional[int]) -> str:
        if sender_member_id is None:
            return "Director"
        member = await db.get(MailTeamMember, sender_member_id)
        return member.display_name if member else "unknown"

    async def _message_response(
        self, db: AsyncSession, message: MailMessage, for_member_id: Optional[int]
    ) -> MailMessageResponse:
        read_at = acked_at = None
        if for_member_id is not None:
            result = await db.execute(
                select(MailReceipt).where(
                    MailReceipt.message_id == message.id,
                    MailReceipt.member_id == for_member_id,
                )
            )
            receipt = result.scalar_one_or_none()
            if receipt is not None:
                read_at, acked_at = receipt.read_at, receipt.acked_at
        is_stale = (
            message.kind in MAIL_REQUEST_KINDS
            and message.request_status == "pending"
            and message.created_at < datetime.utcnow() - timedelta(minutes=STALE_REQUEST_MINUTES)
        )
        return MailMessageResponse(
            id=message.id,
            thread_root_id=message.thread_root_id,
            kind=message.kind,
            sender_member_id=message.sender_member_id,
            sender_name=await self._sender_name(db, message.sender_member_id),
            recipient_member_id=message.recipient_member_id,
            subject=message.subject,
            body_markdown=message.body_markdown,
            payload=message.payload,
            request_status=message.request_status,
            is_stale=is_stale,
            read_at=read_at,
            acked_at=acked_at,
            created_at=message.created_at,
        )

    async def counts_for_member(self, db: AsyncSession, member_id: int) -> tuple[int, int]:
        unread = (
            await db.execute(
                select(func.count())
                .select_from(MailReceipt)
                .where(MailReceipt.member_id == member_id, MailReceipt.read_at.is_(None))
            )
        ).scalar_one()
        pending = (
            await db.execute(
                select(func.count())
                .select_from(MailMessage)
                .where(
                    MailMessage.recipient_member_id == member_id,
                    MailMessage.kind.in_(MAIL_REQUEST_KINDS),
                    MailMessage.request_status == "pending",
                )
            )
        ).scalar_one()
        return unread, pending

    async def get_inbox(
        self,
        db: AsyncSession,
        member_id: int,
        unread_only: bool = False,
        mark_read: bool = False,
        limit: int = 50,
    ) -> MailInboxResponse:
        query = (
            select(MailMessage, MailReceipt)
            .join(MailReceipt, MailReceipt.message_id == MailMessage.id)
            .where(MailReceipt.member_id == member_id)
            .order_by(MailMessage.created_at.desc())
            .limit(limit)
        )
        if unread_only:
            query = query.where(MailReceipt.read_at.is_(None))
        rows = (await db.execute(query)).all()
        messages = []
        for message, receipt in rows:
            if mark_read and receipt.read_at is None:
                receipt.read_at = datetime.utcnow()
            messages.append(await self._message_response(db, message, for_member_id=member_id))
        if mark_read:
            await db.commit()
        unread, pending = await self.counts_for_member(db, member_id)
        return MailInboxResponse(
            member_id=member_id, unread_count=unread, pending_count=pending, messages=messages
        )

    async def mark_read(self, db: AsyncSession, message_id: int, member_id: int) -> None:
        result = await db.execute(
            select(MailReceipt).where(
                MailReceipt.message_id == message_id, MailReceipt.member_id == member_id
            )
        )
        receipt = result.scalar_one_or_none()
        if receipt is not None and receipt.read_at is None:
            receipt.read_at = datetime.utcnow()
            await db.commit()

    async def ack_message(self, db: AsyncSession, message_id: int, member_id: int) -> None:
        """Ack a message.

        Acking an answer (as the original requester) closes the request;
        acking a root handoff (as its recipient) accepts and closes it.
        """
        result = await db.execute(
            select(MailReceipt).where(
                MailReceipt.message_id == message_id, MailReceipt.member_id == member_id
            )
        )
        receipt = result.scalar_one_or_none()
        if receipt is None:
            return
        now = datetime.utcnow()
        receipt.read_at = receipt.read_at or now
        receipt.acked_at = receipt.acked_at or now

        message = await db.get(MailMessage, message_id)
        if (
            message is not None
            and message.kind == "handoff"
            and message.thread_root_id is None
            and message.recipient_member_id == member_id
            and message.request_status == "pending"
        ):
            message.request_status = "acknowledged"
        if message is not None and message.kind == "answer" and message.thread_root_id:
            root = await db.get(MailMessage, message.thread_root_id)
            if (
                root is not None
                and root.sender_member_id == member_id
                and root.request_status == "answered"
            ):
                root.request_status = "acknowledged"
        await db.commit()

    async def get_thread(
        self, db: AsyncSession, root_id: int, for_member_id: Optional[int] = None
    ) -> MailThreadResponse:
        root = await db.get(MailMessage, root_id)
        if root is None:
            raise ValueError(f"Message {root_id} not found")
        replies = (
            (
                await db.execute(
                    select(MailMessage)
                    .where(MailMessage.thread_root_id == root_id)
                    .order_by(MailMessage.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        return MailThreadResponse(
            root=await self._message_response(db, root, for_member_id),
            replies=[await self._message_response(db, r, for_member_id) for r in replies],
        )

    async def list_root_messages(self, db: AsyncSession, limit: int = 100) -> List[MailMessageResponse]:
        """Thread roots, newest first — feeds the UI Requests tab."""
        roots = (
            (
                await db.execute(
                    select(MailMessage)
                    .where(MailMessage.thread_root_id.is_(None))
                    .order_by(MailMessage.created_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return [await self._message_response(db, r, for_member_id=None) for r in roots]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agent_mail/test_messaging.py tests/agent_mail/test_registry.py -v`
Expected: all passed (registry tests still green — the stub is gone, real counts now)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent_mail_service.py backend/tests/agent_mail/test_messaging.py
git commit -m "feat: add agent mail messaging with receipts and request lifecycle"
```

---

### Task 5: Delivery context builders (the injection strings)

These strings ARE the delivery mechanism. They must be state-based and idempotent: safe to inject at startup, after `/clear`, after compaction, and on every user prompt.

**Files:**
- Modify: `backend/app/services/agent_mail_service.py` (append to class)
- Create: `backend/tests/agent_mail/test_context.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/agent_mail/test_context.py
"""Injection context builders: state-based, idempotent, short."""
import pytest

from app.models.database import MailTeamMember
from app.models.schemas import MailMessageCreate
from app.services.agent_mail_service import AgentMailService


@pytest.fixture
def svc():
    return AgentMailService()


async def _member(db, repo_id, name, role=None, charter=None):
    m = MailTeamMember(repo_id=repo_id, repo_path=f"/tmp/{name}", repo_name=name,
                       display_name=name, role=role, charter=charter)
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


@pytest.mark.asyncio
async def test_session_start_context_includes_identity_team_and_inbox(db, svc):
    me = await _member(db, "ra", "backend-agent", role="backend expert", charter="Owns the API")
    other = await _member(db, "rb", "frontend-agent", role="frontend")
    await svc.send_message(db, MailMessageCreate(
        kind="context_request", sender_member_id=other.id, recipient_member_id=me.id,
        subject="auth?", body_markdown="?"))

    ctx = await svc.build_session_start_context(db, me.id)
    assert 'You are "backend-agent"' in ctx
    assert "backend expert" in ctx
    assert "Owns the API" in ctx
    assert "frontend-agent" in ctx
    assert "1 pending request" in ctx
    assert "deck_check_inbox" in ctx


@pytest.mark.asyncio
async def test_prompt_submit_context_none_when_inbox_clear(db, svc):
    me = await _member(db, "ra", "solo")
    assert await svc.build_prompt_submit_context(db, me.id) is None


@pytest.mark.asyncio
async def test_prompt_submit_context_mentions_pending(db, svc):
    me = await _member(db, "ra", "backend-agent")
    other = await _member(db, "rb", "frontend-agent")
    await svc.send_message(db, MailMessageCreate(
        kind="context_request", sender_member_id=other.id, recipient_member_id=me.id,
        subject="auth refresh", body_markdown="?"))
    ctx = await svc.build_prompt_submit_context(db, me.id)
    assert ctx is not None
    assert "1 pending request" in ctx
    assert "deck_check_inbox" in ctx
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agent_mail/test_context.py -v`
Expected: FAIL — no attribute `build_session_start_context`

- [ ] **Step 3: Implement.** Append to `AgentMailService`:

```python
    # ---------- delivery context (hook injection) ----------

    async def build_session_start_context(self, db: AsyncSession, member_id: int) -> str:
        member = await db.get(MailTeamMember, member_id)
        if member is None:
            return ""
        team = await self.list_team(db)
        me = next((m for m in team if m.id == member_id), None)
        others = [m for m in team if m.id != member_id]

        lines = ["[Claude Deck Agent Mail]"]
        role = f" ({member.role})" if member.role else ""
        lines.append(f'You are "{member.display_name}"{role} — repo: {member.repo_name}.')
        if member.charter:
            lines.append(f"Charter: {member.charter}")
        if others:
            roster = " · ".join(
                f"{m.display_name} ({m.role or m.repo_name}, {m.status})" for m in others[:8]
            )
            lines.append(f"Team: {roster}")
        if me is not None and (me.unread_count or me.pending_count):
            lines.append(
                f"Inbox: {me.unread_count} unread, "
                f"{me.pending_count} pending request(s) awaiting your answer."
            )
        lines.append(
            "Coordinate via MCP tools: deck_check_inbox, deck_request_context, "
            "deck_send_message, deck_create_handoff."
        )
        return "\n".join(lines)

    async def build_prompt_submit_context(
        self, db: AsyncSession, member_id: int
    ) -> Optional[str]:
        unread, pending = await self.counts_for_member(db, member_id)
        if not unread and not pending:
            return None
        parts = []
        if unread:
            parts.append(f"{unread} unread message(s)")
        if pending:
            parts.append(f"{pending} pending request(s)")
        return (
            f"[Agent Mail] You have {' and '.join(parts)}. "
            "Call deck_check_inbox when convenient."
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agent_mail/test_context.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent_mail_service.py backend/tests/agent_mail/test_context.py
git commit -m "feat: add agent mail injection context builders"
```

---

### Task 6: API router — team and message endpoints

**Files:**
- Create: `backend/app/api/v1/agent_mail.py`
- Modify: `backend/app/api/v1/router.py`
- Create: `backend/tests/agent_mail/test_api.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/agent_mail/test_api.py
"""HTTP surface for team + messages."""
import httpx
import pytest
import pytest_asyncio

from app.database import get_db
from app.main import app
from app.models.database import MailTeamMember


@pytest_asyncio.fixture
async def client(db):
    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _member(db, repo_id, name):
    m = MailTeamMember(repo_id=repo_id, repo_path=f"/tmp/{name}", repo_name=name, display_name=name)
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


@pytest.mark.asyncio
async def test_team_empty(client):
    resp = await client.get("/api/v1/agent-mail/team?sync=false")
    assert resp.status_code == 200
    assert resp.json() == {"members": []}


@pytest.mark.asyncio
async def test_patch_member_sets_role_and_charter(client, db):
    m = await _member(db, "ra", "alpha")
    resp = await client.patch(
        f"/api/v1/agent-mail/members/{m.id}",
        json={"display_name": "Backend", "role": "backend expert", "charter": "Owns API"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["display_name"] == "Backend"
    assert body["role"] == "backend expert"


@pytest.mark.asyncio
async def test_patch_unknown_member_404(client):
    resp = await client.patch("/api/v1/agent-mail/members/999", json={"role": "x"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_send_and_thread_roundtrip(client, db):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    resp = await client.post("/api/v1/agent-mail/messages", json={
        "kind": "context_request", "sender_member_id": a.id,
        "recipient_member_id": b.id, "subject": "q", "body_markdown": "?"})
    assert resp.status_code == 200
    root_id = resp.json()["id"]

    resp = await client.post("/api/v1/agent-mail/messages", json={
        "kind": "answer", "sender_member_id": b.id,
        "thread_root_id": root_id, "body_markdown": "!"})
    assert resp.status_code == 200

    resp = await client.get(f"/api/v1/agent-mail/messages/{root_id}/thread")
    assert resp.status_code == 200
    assert resp.json()["root"]["request_status"] == "answered"
    assert len(resp.json()["replies"]) == 1


@pytest.mark.asyncio
async def test_invalid_kind_is_400(client, db):
    b = await _member(db, "rb", "beta")
    resp = await client.post("/api/v1/agent-mail/messages", json={
        "kind": "bogus", "recipient_member_id": b.id, "body_markdown": "x"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_inbox_read_ack_endpoints(client, db):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    resp = await client.post("/api/v1/agent-mail/messages", json={
        "sender_member_id": a.id, "recipient_member_id": b.id, "body_markdown": "hi"})
    msg_id = resp.json()["id"]

    resp = await client.get(f"/api/v1/agent-mail/agent/inbox?member_id={b.id}")
    assert resp.json()["unread_count"] == 1

    await client.post(f"/api/v1/agent-mail/messages/{msg_id}/read", json={"member_id": b.id})
    resp = await client.get(f"/api/v1/agent-mail/agent/inbox?member_id={b.id}")
    assert resp.json()["unread_count"] == 0

    resp = await client.post(f"/api/v1/agent-mail/messages/{msg_id}/ack", json={"member_id": b.id})
    assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agent_mail/test_api.py -v`
Expected: FAIL — 404s (router not registered)

- [ ] **Step 3: Create the router**

```python
# backend/app/api/v1/agent_mail.py
"""Agent Mail endpoints: team roster, messages, agent registration, hook ingest."""
import logging
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.database import MailTeamMember
from app.models.schemas import (
    MailAgentRegisterRequest,
    MailAgentRegisterResponse,
    MailInboxResponse,
    MailMemberResponse,
    MailMemberUpdate,
    MailMessageCreate,
    MailMessageResponse,
    MailThreadResponse,
    TeamListResponse,
)
from app.services.agent_mail_service import agent_mail_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------- UI: team ----------

@router.get("/team", response_model=TeamListResponse)
async def get_team(sync: bool = True, db: AsyncSession = Depends(get_db)):
    """Team roster with sessions and inbox counts. sync=true refreshes observed sessions."""
    if sync:
        await agent_mail_service.sync_observed_sessions(db)
    members = await agent_mail_service.list_team(db)
    return TeamListResponse(members=members)


@router.patch("/members/{member_id}", response_model=MailMemberResponse)
async def update_member(
    member_id: int, update: MailMemberUpdate, db: AsyncSession = Depends(get_db)
):
    member = await db.get(MailTeamMember, member_id)
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    if update.display_name is not None:
        member.display_name = update.display_name.strip() or member.display_name
    if update.role is not None:
        member.role = update.role.strip() or None
    if update.charter is not None:
        member.charter = update.charter.strip() or None
    from datetime import datetime
    member.updated_at = datetime.utcnow()
    await db.commit()
    members = await agent_mail_service.list_team(db)
    found = next((m for m in members if m.id == member_id), None)
    if found is None:
        raise HTTPException(status_code=404, detail="Member not found")
    return found


# ---------- messages (UI + agents share these) ----------

@router.post("/messages", response_model=MailMessageResponse)
async def send_message(request: MailMessageCreate, db: AsyncSession = Depends(get_db)):
    try:
        return await agent_mail_service.send_message(db, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/messages", response_model=list[MailMessageResponse])
async def list_messages(db: AsyncSession = Depends(get_db)):
    """Thread roots, newest first (UI Requests tab)."""
    return await agent_mail_service.list_root_messages(db)


@router.get("/messages/{message_id}/thread", response_model=MailThreadResponse)
async def get_thread(
    message_id: int, member_id: Optional[int] = None, db: AsyncSession = Depends(get_db)
):
    try:
        return await agent_mail_service.get_thread(db, message_id, for_member_id=member_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/messages/{message_id}/read")
async def mark_read(
    message_id: int,
    body: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
):
    await agent_mail_service.mark_read(db, message_id, int(body["member_id"]))
    return {"ok": True}


@router.post("/messages/{message_id}/ack")
async def ack_message(
    message_id: int,
    body: dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
):
    await agent_mail_service.ack_message(db, message_id, int(body["member_id"]))
    return {"ok": True}


# ---------- agents (MCP shim) ----------

@router.post("/agent/register", response_model=MailAgentRegisterResponse)
async def register_agent(
    request: MailAgentRegisterRequest, db: AsyncSession = Depends(get_db)
):
    member, session = await agent_mail_service.register_session(db, request)
    members = await agent_mail_service.list_team(db)
    member_resp = next(m for m in members if m.id == member.id)
    session_resp = next(s for s in member_resp.sessions if s.session_key == session.session_key)
    return MailAgentRegisterResponse(member=member_resp, session=session_resp)


@router.get("/agent/inbox", response_model=MailInboxResponse)
async def agent_inbox(
    member_id: int,
    unread_only: bool = False,
    mark_read: bool = False,
    db: AsyncSession = Depends(get_db),
):
    return await agent_mail_service.get_inbox(
        db, member_id, unread_only=unread_only, mark_read=mark_read
    )
```

- [ ] **Step 4: Register the router.** In `backend/app/api/v1/router.py` add the import next to the others and the include next to the presence one:

```python
from .agent_mail import router as agent_mail_router
```

```python
router.include_router(agent_mail_router, prefix="/agent-mail", tags=["Agent Mail"])
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/agent_mail/test_api.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/agent_mail.py backend/app/api/v1/router.py backend/tests/agent_mail/test_api.py
git commit -m "feat: add agent mail team and message endpoints"
```

---

### Task 7: Hook ingest endpoints (registration + context injection)

The four endpoints receive raw Claude Code hook payloads (posted by the installed `curl` command hooks; the hook's stdin payload is forwarded verbatim). Their JSON response becomes the command hook's stdout, which Claude Code parses — `hookSpecificOutput.additionalContext` is injected into the conversation for `SessionStart` and `UserPromptSubmit`.

**Files:**
- Modify: `backend/app/api/v1/agent_mail.py` (append)
- Create: `backend/tests/agent_mail/test_hooks_api.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/agent_mail/test_hooks_api.py
"""Hook ingest endpoints: register, inject, heartbeat, fail soft."""
import httpx
import pytest
import pytest_asyncio

from app.database import get_db
from app.main import app
from app.models.database import MailTeamMember
from app.models.schemas import MailMessageCreate
from app.services.agent_mail_service import agent_mail_service


@pytest_asyncio.fixture
async def client(db):
    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_session_start_registers_and_injects(client, db, tmp_path):
    resp = await client.post("/api/v1/agent-mail/hooks/session-start", json={
        "session_id": "s1", "cwd": str(tmp_path / "myrepo"), "source": "startup"})
    assert resp.status_code == 200
    out = resp.json()["hookSpecificOutput"]
    assert out["hookEventName"] == "SessionStart"
    assert 'You are "myrepo"' in out["additionalContext"]

    team = await agent_mail_service.list_team(db)
    assert team[0].status == "connected"


@pytest.mark.asyncio
async def test_session_start_without_session_id_fails_soft(client):
    resp = await client.post("/api/v1/agent-mail/hooks/session-start", json={"cwd": "/tmp"})
    assert resp.status_code == 200
    assert resp.json() == {}


@pytest.mark.asyncio
async def test_user_prompt_submit_injects_only_when_inbox_nonempty(client, db, tmp_path):
    cwd = str(tmp_path / "myrepo")
    await client.post("/api/v1/agent-mail/hooks/session-start",
                      json={"session_id": "s1", "cwd": cwd})
    resp = await client.post("/api/v1/agent-mail/hooks/user-prompt-submit",
                             json={"session_id": "s1", "cwd": cwd, "prompt": "hi"})
    assert resp.json() == {}

    team = await agent_mail_service.list_team(db)
    me = team[0]
    other = MailTeamMember(repo_id="other", repo_path="/tmp/o", repo_name="o", display_name="o")
    db.add(other)
    await db.commit()
    await db.refresh(other)
    await agent_mail_service.send_message(db, MailMessageCreate(
        sender_member_id=other.id, recipient_member_id=me.id, body_markdown="ping"))

    resp = await client.post("/api/v1/agent-mail/hooks/user-prompt-submit",
                             json={"session_id": "s1", "cwd": cwd, "prompt": "hi"})
    out = resp.json()["hookSpecificOutput"]
    assert out["hookEventName"] == "UserPromptSubmit"
    assert "1 unread" in out["additionalContext"]


@pytest.mark.asyncio
async def test_session_end_marks_offline(client, db, tmp_path):
    cwd = str(tmp_path / "myrepo")
    await client.post("/api/v1/agent-mail/hooks/session-start",
                      json={"session_id": "s1", "cwd": cwd})
    resp = await client.post("/api/v1/agent-mail/hooks/session-end",
                             json={"session_id": "s1", "cwd": cwd})
    assert resp.status_code == 200
    team = await agent_mail_service.list_team(db)
    assert team[0].status == "offline"


@pytest.mark.asyncio
async def test_post_tool_use_updates_activity(client, db, tmp_path):
    cwd = str(tmp_path / "myrepo")
    await client.post("/api/v1/agent-mail/hooks/session-start",
                      json={"session_id": "s1", "cwd": cwd})
    resp = await client.post("/api/v1/agent-mail/hooks/post-tool-use", json={
        "session_id": "s1", "cwd": cwd, "tool_name": "Edit",
        "tool_input": {"file_path": f"{cwd}/src/main.py"}})
    assert resp.status_code == 200
    team = await agent_mail_service.list_team(db)
    assert "main.py" in team[0].sessions[0].activity
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agent_mail/test_hooks_api.py -v`
Expected: FAIL — 404 (endpoints missing)

- [ ] **Step 3: Append hook endpoints to `backend/app/api/v1/agent_mail.py`**

```python
# ---------- Claude Code hook ingest ----------
# Installed as `curl ... --data-binary @- || true` command hooks: the JSON we
# return here becomes the hook's stdout, which Claude Code parses for
# hookSpecificOutput.additionalContext. Every handler must fail soft (200 + {}).


def _hook_session_key(payload: dict) -> Optional[str]:
    session_id = payload.get("session_id")
    return f"cc:{session_id}" if session_id else None


async def _register_from_hook(db: AsyncSession, payload: dict):
    session_key = _hook_session_key(payload)
    cwd = payload.get("cwd")
    if not session_key or not cwd:
        return None, None
    return await agent_mail_service.register_session(
        db,
        MailAgentRegisterRequest(
            source="hook", provider="claude-code", cwd=cwd, session_key=session_key
        ),
    )


@router.post("/hooks/session-start")
async def hook_session_start(
    payload: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)
):
    try:
        member, _ = await _register_from_hook(db, payload)
        if member is None:
            return {}
        context = await agent_mail_service.build_session_start_context(db, member.id)
        if not context:
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }
    except Exception as exc:  # hooks must never break the agent session
        logger.warning("session-start hook failed: %s", exc)
        return {}


@router.post("/hooks/user-prompt-submit")
async def hook_user_prompt_submit(
    payload: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)
):
    try:
        session_key = _hook_session_key(payload)
        if session_key is None:
            return {}
        session = await agent_mail_service.heartbeat_session(db, session_key)
        if session is None:
            member, session = await _register_from_hook(db, payload)
            if session is None:
                return {}
        context = await agent_mail_service.build_prompt_submit_context(db, session.member_id)
        if context is None:
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": context,
            }
        }
    except Exception as exc:
        logger.warning("user-prompt-submit hook failed: %s", exc)
        return {}


@router.post("/hooks/session-end")
async def hook_session_end(
    payload: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)
):
    try:
        session_key = _hook_session_key(payload)
        if session_key is not None:
            await agent_mail_service.mark_session_offline(db, session_key)
    except Exception as exc:
        logger.warning("session-end hook failed: %s", exc)
    return {}


@router.post("/hooks/post-tool-use")
async def hook_post_tool_use(
    payload: dict[str, Any] = Body(...), db: AsyncSession = Depends(get_db)
):
    try:
        session_key = _hook_session_key(payload)
        if session_key is None:
            return {}
        activity = None
        tool_input = payload.get("tool_input") or {}
        file_path = tool_input.get("file_path")
        if file_path:
            import os
            activity = f"edited {os.path.basename(str(file_path))}"
        session = await agent_mail_service.heartbeat_session(db, session_key, activity=activity)
        if session is None:
            await _register_from_hook(db, payload)
            if activity:
                await agent_mail_service.heartbeat_session(db, session_key, activity=activity)
    except Exception as exc:
        logger.warning("post-tool-use hook failed: %s", exc)
    return {}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agent_mail/test_hooks_api.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/agent_mail.py backend/tests/agent_mail/test_hooks_api.py
git commit -m "feat: add agent mail hook ingest with context injection"
```

---

### Task 8: Install service + endpoints (one-click Claude Code + Codex, confirmed + backed up)

**Files:**
- Create: `backend/app/services/agent_mail_install_service.py`
- Modify: `backend/app/api/v1/agent_mail.py` (append install endpoints)
- Create: `backend/tests/agent_mail/test_install.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/agent_mail/test_install.py
"""Install service: hook commands, status detection, confirmed apply/uninstall, codex."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import agent_mail_install_service as install


def test_hook_command_shape():
    cmd = install.hook_command("session-start")
    assert cmd.startswith("curl -s -m 3 -X POST http://127.0.0.1:")
    assert "/api/v1/agent-mail/hooks/session-start" in cmd
    assert "--data-binary @-" in cmd
    assert cmd.endswith("|| true")


def test_shim_path_points_at_real_file():
    # The shim is created in Task 9; until then this asserts the expected location.
    assert install.shim_path().endswith("backend/mcp_shim/agent_mail_server.py")


@pytest.mark.asyncio
async def test_status_reports_missing_then_installed():
    fake_hook = MagicMock()
    fake_hook.type = "command"
    fake_hook.command = install.hook_command("session-start")
    fake_hook.event = "SessionStart"

    with patch.object(install.hook_service, "list_hooks", return_value=[fake_hook]), \
         patch.object(install.mcp_service, "get_server", new=AsyncMock(return_value=None)), \
         patch.object(install, "_codex_executor", return_value=None):
        status = await install.get_install_status()
    assert status.claude_code_hooks == ["SessionStart"]
    assert "UserPromptSubmit" in status.claude_code_hooks_missing
    assert status.claude_code_mcp_installed is False
    assert status.codex_cli_available is False
    assert status.codex_mcp_installed is False


@pytest.mark.asyncio
async def test_apply_adds_missing_hooks_and_mcp_with_user_scope_and_backup():
    db = MagicMock()
    with patch.object(install.hook_service, "list_hooks", return_value=[]), \
         patch.object(install.hook_service, "add_hook") as add_hook, \
         patch.object(install.mcp_service, "get_server", new=AsyncMock(return_value=None)), \
         patch.object(install.mcp_service, "add_server", new=AsyncMock()) as add_server, \
         patch.object(install, "_codex_executor", return_value=None), \
         patch.object(install, "_backup_before_mutation", new=AsyncMock()) as backup:
        await install.apply_claude_code_install(db)
    added = [call.args[0] for call in add_hook.call_args_list]
    assert {h.event for h in added} == {"SessionStart", "UserPromptSubmit", "SessionEnd", "PostToolUse"}
    assert all(h.scope == "user" for h in added)
    post_tool = next(h for h in added if h.event == "PostToolUse")
    assert post_tool.matcher == "Edit|Write|MultiEdit|NotebookEdit"
    assert add_server.await_count == 1
    server = add_server.await_args.args[0]
    assert server.name == "claude-deck-mail"
    assert server.scope == "user"
    assert server.args == [install.shim_path()]
    backup.assert_awaited_once_with(db, "user")


@pytest.mark.asyncio
async def test_uninstall_removes_only_agent_mail_hooks():
    ours = MagicMock(); ours.type = "command"; ours.id = "h1"; ours.scope = "user"
    ours.command = install.hook_command("session-end")
    theirs = MagicMock(); theirs.type = "command"; theirs.id = "h2"; theirs.scope = "user"
    theirs.command = "echo hello"

    db = MagicMock()
    with patch.object(install.hook_service, "list_hooks", return_value=[ours, theirs]), \
         patch.object(install.hook_service, "remove_hook") as remove_hook, \
         patch.object(install.mcp_service, "get_server", new=AsyncMock(return_value=MagicMock())), \
         patch.object(install.mcp_service, "remove_server", new=AsyncMock()) as remove_server, \
         patch.object(install, "_codex_executor", return_value=None), \
         patch.object(install, "_backup_before_mutation", new=AsyncMock()):
        await install.uninstall_claude_code(db)
    remove_hook.assert_called_once_with("h1", "user")
    remove_server.assert_awaited_once_with("claude-deck-mail", "user")


@pytest.mark.asyncio
async def test_apply_codex_runs_codex_mcp_add():
    executor = MagicMock()
    executor.execute.return_value = MagicMock(exit_code=0, stdout="", stderr="")
    db = MagicMock()
    with patch.object(install, "_codex_executor", return_value=executor), \
         patch.object(install, "codex_mcp_installed", side_effect=[False, True]), \
         patch.object(install.hook_service, "list_hooks", return_value=[]), \
         patch.object(install.mcp_service, "get_server", new=AsyncMock(return_value=None)), \
         patch.object(install, "_backup_before_mutation", new=AsyncMock()) as backup:
        await install.apply_codex_install(db)
    backup.assert_awaited_once_with(db, "codex")
    args = executor.execute.call_args.args
    assert args[0] == "mcp"
    mcp_args = args[1]
    assert mcp_args[0] == "add"
    assert "CLAUDE_DECK_PROVIDER=codex-cli" in mcp_args
    assert "claude-deck-mail" in mcp_args
    assert "--" in mcp_args
    assert mcp_args[-1] == install.shim_path()


def test_codex_snippets_mention_shim_and_provider():
    snippets = install.get_snippets()
    assert "[mcp_servers.claude-deck-mail]" in snippets.codex_config_toml
    assert "CLAUDE_DECK_PROVIDER" in snippets.codex_config_toml
    assert "deck_whoami" in snippets.codex_agents_md
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agent_mail/test_install.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement the install service**

```python
# backend/app/services/agent_mail_install_service.py
"""Install Agent Mail integration into Claude Code and Codex (one-click each).

Reuses the existing HookService and MCPService writers so settings.json and
~/.claude.json round-trip exactly like the Hooks and MCP Servers pages, and
the provider CLI executor (`codex mcp add`) for Codex. A best-effort config
backup is taken before the first mutation of every apply/uninstall.
"""
import logging
import shutil
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.schemas import (
    AgentMailInstallStatus,
    AgentMailSnippets,
    HookCreate,
    MCPServerCreate,
)
from app.services.hook_service import HookService
from app.services.mcp_service import MCPService

logger = logging.getLogger(__name__)

hook_service = HookService()
mcp_service = MCPService()

MCP_SERVER_NAME = "claude-deck-mail"
POST_TOOL_USE_MATCHER = "Edit|Write|MultiEdit|NotebookEdit"

# event name -> endpoint slug
MAIL_HOOK_EVENTS = {
    "SessionStart": "session-start",
    "UserPromptSubmit": "user-prompt-submit",
    "SessionEnd": "session-end",
    "PostToolUse": "post-tool-use",
}

_HOOK_URL_MARKER = "/api/v1/agent-mail/hooks/"


def deck_base_url() -> str:
    return f"http://127.0.0.1:{settings.port}"


def shim_path() -> str:
    # services/ -> app/ -> backend/
    return str(Path(__file__).resolve().parents[2] / "mcp_shim" / "agent_mail_server.py")


def hook_command(slug: str) -> str:
    return (
        f"curl -s -m 3 -X POST {deck_base_url()}/api/v1/agent-mail/hooks/{slug} "
        "-H 'Content-Type: application/json' --data-binary @- 2>/dev/null || true"
    )


def _installed_mail_hooks() -> list:
    return [
        h
        for h in hook_service.list_hooks()
        if h.type == "command" and h.command and _HOOK_URL_MARKER in h.command
    ]


def _codex_executor():
    """Codex provider CLI executor, or None when codex isn't installed."""
    try:
        from app.services.cli_executor import ProviderCLIExecutor

        executor = ProviderCLIExecutor("codex-cli")
        return executor if executor.binary_path else None
    except Exception as exc:
        logger.debug("codex executor unavailable: %s", exc)
        return None


def codex_cli_available() -> bool:
    return _codex_executor() is not None


def codex_mcp_installed() -> bool:
    executor = _codex_executor()
    if executor is None:
        return False
    try:
        result = executor.execute("mcp", ["list", "--json"], timeout=30)
        return MCP_SERVER_NAME in (result.stdout or "")
    except Exception as exc:
        logger.debug("codex mcp list failed: %s", exc)
        return False


async def _backup_before_mutation(db: AsyncSession, scope: str) -> None:
    """Best-effort config backup; never blocks the install."""
    try:
        from app.services.backup_service import BackupService

        await BackupService(db).create_backup(
            name=f"pre-agent-mail-{scope}",
            scope=scope,
            description="Automatic backup before Agent Mail install/uninstall",
        )
    except Exception as exc:
        logger.warning("agent mail pre-mutation backup failed: %s", exc)


async def get_install_status() -> AgentMailInstallStatus:
    installed_events = sorted({h.event for h in _installed_mail_hooks()})
    missing = [e for e in MAIL_HOOK_EVENTS if e not in installed_events]
    server = await mcp_service.get_server(MCP_SERVER_NAME, "user")
    return AgentMailInstallStatus(
        claude_code_hooks=installed_events,
        claude_code_hooks_missing=missing,
        claude_code_mcp_installed=server is not None,
        codex_cli_available=codex_cli_available(),
        codex_mcp_installed=codex_mcp_installed(),
        curl_available=shutil.which("curl") is not None,
        shim_path=shim_path(),
        python_path=sys.executable,
        deck_url=deck_base_url(),
    )


async def apply_claude_code_install(db: AsyncSession) -> AgentMailInstallStatus:
    await _backup_before_mutation(db, "user")
    installed_events = {h.event for h in _installed_mail_hooks()}
    for event, slug in MAIL_HOOK_EVENTS.items():
        if event in installed_events:
            continue
        hook_service.add_hook(
            HookCreate(
                event=event,
                matcher=POST_TOOL_USE_MATCHER if event == "PostToolUse" else None,
                type="command",
                command=hook_command(slug),
                scope="user",
            )
        )
    if await mcp_service.get_server(MCP_SERVER_NAME, "user") is None:
        await mcp_service.add_server(
            MCPServerCreate(
                name=MCP_SERVER_NAME,
                type="stdio",
                scope="user",
                command=sys.executable,
                args=[shim_path()],
                env={
                    "CLAUDE_DECK_URL": deck_base_url(),
                    "CLAUDE_DECK_PROVIDER": "claude-code",
                },
            )
        )
    return await get_install_status()


async def uninstall_claude_code(db: AsyncSession) -> AgentMailInstallStatus:
    await _backup_before_mutation(db, "user")
    for hook in _installed_mail_hooks():
        hook_service.remove_hook(hook.id, hook.scope)
    if await mcp_service.get_server(MCP_SERVER_NAME, "user") is not None:
        await mcp_service.remove_server(MCP_SERVER_NAME, "user")
    return await get_install_status()


async def apply_codex_install(db: AsyncSession) -> AgentMailInstallStatus:
    executor = _codex_executor()
    if executor is None:
        raise ValueError("Codex CLI is not available on this machine")
    await _backup_before_mutation(db, "codex")
    if not codex_mcp_installed():
        # Arg shape mirrors providers.py _build_codex_mcp_add_args. The
        # executor's SAFE_ARG_PATTERN forbids spaces, so a repo path containing
        # spaces fails cleanly and surfaces as an error in the UI.
        args = [
            "add",
            "--env", f"CLAUDE_DECK_URL={deck_base_url()}",
            "--env", "CLAUDE_DECK_PROVIDER=codex-cli",
            MCP_SERVER_NAME,
            "--", sys.executable, shim_path(),
        ]
        result = executor.execute("mcp", args, timeout=30)
        if result.exit_code != 0:
            raise ValueError(f"codex mcp add failed: {(result.stderr or '')[:300]}")
    return await get_install_status()


async def uninstall_codex(db: AsyncSession) -> AgentMailInstallStatus:
    executor = _codex_executor()
    if executor is not None and codex_mcp_installed():
        await _backup_before_mutation(db, "codex")
        executor.execute("mcp", ["remove", MCP_SERVER_NAME], timeout=30)
    return await get_install_status()


def get_snippets() -> AgentMailSnippets:
    toml = (
        f"[mcp_servers.{MCP_SERVER_NAME}]\n"
        f'command = "{sys.executable}"\n'
        f'args = ["{shim_path()}"]\n'
        f'env = {{ CLAUDE_DECK_URL = "{deck_base_url()}", CLAUDE_DECK_PROVIDER = "codex-cli" }}\n'
    )
    agents_md = (
        "## Claude Deck Agent Mail\n"
        "You are part of a local agent team coordinated through Claude Deck.\n"
        "- Call `deck_whoami` once when you start working to register and learn your role.\n"
        "- Call `deck_check_inbox` before starting major tasks and after finishing one.\n"
        "- Use `deck_request_context` to ask another repo's agent a question, and\n"
        "  `deck_create_handoff` to hand work over.\n"
    )
    return AgentMailSnippets(codex_config_toml=toml, codex_agents_md=agents_md)
```

- [ ] **Step 4: Append install endpoints to `backend/app/api/v1/agent_mail.py`**

```python
# ---------- install ----------

from app.models.schemas import AgentMailInstallStatus, AgentMailSnippets
from app.services import agent_mail_install_service


def _require_confirmed(body: dict[str, Any]) -> None:
    if not body.get("confirmed"):
        raise HTTPException(status_code=400, detail='Pass {"confirmed": true} to mutate config')


@router.get("/install/status", response_model=AgentMailInstallStatus)
async def install_status():
    return await agent_mail_install_service.get_install_status()


@router.post("/install/claude-code/apply", response_model=AgentMailInstallStatus)
async def install_claude_code(
    body: dict[str, Any] = Body(default={}), db: AsyncSession = Depends(get_db)
):
    _require_confirmed(body)
    return await agent_mail_install_service.apply_claude_code_install(db)


@router.post("/install/claude-code/uninstall", response_model=AgentMailInstallStatus)
async def uninstall_claude_code(
    body: dict[str, Any] = Body(default={}), db: AsyncSession = Depends(get_db)
):
    _require_confirmed(body)
    return await agent_mail_install_service.uninstall_claude_code(db)


@router.post("/install/codex/apply", response_model=AgentMailInstallStatus)
async def install_codex(
    body: dict[str, Any] = Body(default={}), db: AsyncSession = Depends(get_db)
):
    _require_confirmed(body)
    try:
        return await agent_mail_install_service.apply_codex_install(db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/install/codex/uninstall", response_model=AgentMailInstallStatus)
async def uninstall_codex(
    body: dict[str, Any] = Body(default={}), db: AsyncSession = Depends(get_db)
):
    _require_confirmed(body)
    return await agent_mail_install_service.uninstall_codex(db)


@router.get("/install/snippets", response_model=AgentMailSnippets)
async def install_snippets():
    return agent_mail_install_service.get_snippets()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/agent_mail/test_install.py -v`
Expected: 7 passed (the `shim_path` test asserts the path string only; the file itself arrives in Task 9)

- [ ] **Step 6: Run the whole backend suite to confirm nothing broke**

Run: `pytest tests/ -v`
Expected: all existing + new tests pass

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/agent_mail_install_service.py backend/app/api/v1/agent_mail.py backend/tests/agent_mail/test_install.py
git commit -m "feat: add agent mail one-click install service"
```

---

### Task 9: MCP stdio shim (`deck_*` tools)

**Files:**
- Modify: `backend/requirements.txt` (add `mcp>=1.2.0`)
- Create: `backend/mcp_shim/__init__.py` (empty), `backend/mcp_shim/agent_mail_server.py`
- Create: `backend/tests/agent_mail/test_mcp_shim.py`

- [ ] **Step 1: Add the dependency and install it**

Append to `backend/requirements.txt`:

```text
mcp>=1.2.0
```

Also add `"mcp>=1.2.0",` to the `dependencies` list in `backend/pyproject.toml` — the repo maintains both manifests (`requirements.txt` drives `scripts/install.sh`; pyproject mirrors it). An untracked `backend/uv.lock` exists; if you use uv locally, refresh it with `cd backend && uv lock`, otherwise ignore it.

Run: `cd backend && source venv/bin/activate && pip install -r requirements.txt`
Expected: `mcp` installs cleanly

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/agent_mail/test_mcp_shim.py
"""Shim smoke tests: tool registration and fail-soft backend errors."""
import pytest

from mcp_shim import agent_mail_server


EXPECTED_TOOLS = {
    "deck_whoami",
    "deck_list_team",
    "deck_check_inbox",
    "deck_send_message",
    "deck_reply",
    "deck_ack_message",
    "deck_request_context",
    "deck_create_handoff",
}


@pytest.mark.asyncio
async def test_all_tools_registered():
    tools = await agent_mail_server.mcp.list_tools()
    assert {t.name for t in tools} == EXPECTED_TOOLS


@pytest.mark.asyncio
async def test_every_tool_has_description():
    tools = await agent_mail_server.mcp.list_tools()
    for tool in tools:
        assert tool.description and len(tool.description) > 20, tool.name


def test_request_fails_soft_when_deck_down(monkeypatch):
    monkeypatch.setattr(agent_mail_server, "API", "http://127.0.0.1:1/api/v1/agent-mail")
    result = agent_mail_server._request("GET", "/team")
    assert result["ok"] is False
    assert result["error"]["code"] == "deck_unreachable"
    assert "suggestion" in result
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/agent_mail/test_mcp_shim.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcp_shim'`

- [ ] **Step 4: Implement the shim**

```python
# backend/mcp_shim/agent_mail_server.py
"""Claude Deck Agent Mail MCP server (stdio).

Standalone by design: imports only `mcp` and `httpx`, never `app.*`, so the
backend venv's python can run it from any working directory. All state lives
in the Claude Deck backend; this process is a thin authenticated-by-locality
HTTP client.
"""
import os
import uuid
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

DECK_URL = os.environ.get("CLAUDE_DECK_URL", "http://127.0.0.1:8000").rstrip("/")
PROVIDER = os.environ.get("CLAUDE_DECK_PROVIDER", "unknown")
API = f"{DECK_URL}/api/v1/agent-mail"

mcp = FastMCP("claude-deck-mail")

_state: dict[str, Any] = {
    "member_id": None,
    "session_key": f"mcp:{uuid.uuid4().hex[:12]}",
}


def _request(method: str, path: str, **kwargs) -> dict:
    try:
        resp = httpx.request(method, f"{API}{path}", timeout=5.0, **kwargs)
        resp.raise_for_status()
        return {"ok": True, "data": resp.json()}
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "error": {"code": "deck_unreachable", "message": str(exc)},
            "suggestion": (
                "Continue without mailbox coordination, or ask the user to "
                "start Claude Deck."
            ),
        }


def _ensure_registered() -> dict:
    """Lazy registration on first tool call; re-registers after restarts."""
    if _state["member_id"] is not None:
        return {"ok": True}
    result = _request(
        "POST",
        "/agent/register",
        json={
            "source": "mcp",
            "provider": PROVIDER,
            "cwd": os.getcwd(),
            "session_key": _state["session_key"],
            "pid": os.getppid(),
        },
    )
    if result["ok"]:
        _state["member_id"] = result["data"]["member"]["id"]
    return result


def _counts() -> dict:
    """Piggyback inbox counts onto every tool response (delivery mechanism)."""
    if _state["member_id"] is None:
        return {}
    result = _request("GET", f"/agent/inbox?member_id={_state['member_id']}&unread_only=true&limit=1")
    if not result["ok"]:
        return {}
    return {
        "unread_count": result["data"]["unread_count"],
        "pending_count": result["data"]["pending_count"],
    }


def _guard() -> Optional[dict]:
    """Return an error payload if registration failed, else None."""
    reg = _ensure_registered()
    return None if reg["ok"] else reg


@mcp.tool()
def deck_whoami() -> dict:
    """Register with Claude Deck Agent Mail (if needed) and return your team identity:
    display name, role, charter (instructions from the user), repo, plus current
    unread/pending inbox counts. Call this once when starting coordinated work."""
    err = _guard()
    if err:
        return err
    result = _request("GET", "/team?sync=false")
    if not result["ok"]:
        return result
    me = next((m for m in result["data"]["members"] if m["id"] == _state["member_id"]), None)
    return {"ok": True, "me": me, **_counts()}


@mcp.tool()
def deck_list_team() -> dict:
    """List all team members Claude Deck knows about (every local agent, across repos):
    their member_id, name, role, repo, and live status. Use member_id values from here
    as the to_member_id for messages, context requests, and handoffs."""
    err = _guard()
    if err:
        return err
    result = _request("GET", "/team?sync=true")
    if not result["ok"]:
        return result
    members = [
        {k: m[k] for k in ("id", "display_name", "role", "repo_name", "status", "charter")}
        for m in result["data"]["members"]
    ]
    return {"ok": True, "members": members, **_counts()}


@mcp.tool()
def deck_check_inbox(unread_only: bool = True, limit: int = 20) -> dict:
    """Read your Agent Mail inbox (messages, context requests, handoffs, answers from
    other agents or the user). Marks returned messages as read. Check this before
    starting major work and after finishing a task."""
    err = _guard()
    if err:
        return err
    result = _request(
        "GET",
        f"/agent/inbox?member_id={_state['member_id']}"
        f"&unread_only={'true' if unread_only else 'false'}&mark_read=true&limit={limit}",
    )
    if not result["ok"]:
        return result
    return {"ok": True, **result["data"]}


@mcp.tool()
def deck_send_message(to_member_id: int, body: str, subject: str = "") -> dict:
    """Send a plain message to another team member (get member ids from deck_list_team).
    For questions that need an answer use deck_request_context instead; for handing
    work over use deck_create_handoff."""
    err = _guard()
    if err:
        return err
    result = _request("POST", "/messages", json={
        "kind": "message",
        "sender_member_id": _state["member_id"],
        "recipient_member_id": to_member_id,
        "subject": subject or None,
        "body_markdown": body,
    })
    if not result["ok"]:
        return result
    return {"ok": True, "message_id": result["data"]["id"], **_counts()}


@mcp.tool()
def deck_reply(thread_root_id: int, body: str) -> dict:
    """Reply in an existing thread. If the thread root is a pending context request or
    handoff addressed to you, your reply is recorded as the answer and resolves it."""
    err = _guard()
    if err:
        return err
    thread = _request("GET", f"/messages/{thread_root_id}/thread")
    if not thread["ok"]:
        return thread
    root = thread["data"]["root"]
    is_answer = (
        root["kind"] in ("context_request", "handoff")
        and root.get("request_status") == "pending"
        and root.get("recipient_member_id") == _state["member_id"]
    )
    result = _request("POST", "/messages", json={
        "kind": "answer" if is_answer else "message",
        "sender_member_id": _state["member_id"],
        "thread_root_id": thread_root_id,
        "body_markdown": body,
    })
    if not result["ok"]:
        return result
    return {"ok": True, "message_id": result["data"]["id"],
            "resolved_request": is_answer, **_counts()}


@mcp.tool()
def deck_ack_message(message_id: int) -> dict:
    """Acknowledge a message. Acking an answer to your own context request closes the
    request; acking a handoff accepts it and closes it (report completion later with
    deck_reply in the same thread)."""
    err = _guard()
    if err:
        return err
    result = _request("POST", f"/messages/{message_id}/ack",
                      json={"member_id": _state["member_id"]})
    if not result["ok"]:
        return result
    return {"ok": True, **_counts()}


@mcp.tool()
def deck_request_context(
    to_member_id: int, topic: str, why_needed: str = "", files_or_symbols: list[str] = []
) -> dict:
    """Ask another repo's agent a structured question they are the expert on (e.g. how
    something in their repo works). Creates a pending request they will be nudged to
    answer; check deck_check_inbox later for the answer."""
    err = _guard()
    if err:
        return err
    body = topic
    if why_needed:
        body += f"\n\n**Why needed:** {why_needed}"
    result = _request("POST", "/messages", json={
        "kind": "context_request",
        "sender_member_id": _state["member_id"],
        "recipient_member_id": to_member_id,
        "subject": topic[:120],
        "body_markdown": body,
        "payload": {"why_needed": why_needed, "files_or_symbols": files_or_symbols},
    })
    if not result["ok"]:
        return result
    return {"ok": True, "request_id": result["data"]["id"], **_counts()}


@mcp.tool()
def deck_create_handoff(
    to_member_id: int, summary: str, files: list[str] = [], next_steps: list[str] = []
) -> dict:
    """Hand work over to another team member with a structured summary, the files you
    touched, and concrete next steps. The recipient acks it to accept and replies in
    the thread when done."""
    err = _guard()
    if err:
        return err
    body_lines = ["## Handoff", "", f"**Summary:** {summary}"]
    if files:
        body_lines += ["", "**Files touched:**"] + [f"- `{f}`" for f in files]
    if next_steps:
        body_lines += ["", "**Next steps:**"] + [f"{i+1}. {s}" for i, s in enumerate(next_steps)]
    result = _request("POST", "/messages", json={
        "kind": "handoff",
        "sender_member_id": _state["member_id"],
        "recipient_member_id": to_member_id,
        "subject": f"Handoff: {summary[:100]}",
        "body_markdown": "\n".join(body_lines),
        "payload": {"files": files, "next_steps": next_steps},
    })
    if not result["ok"]:
        return result
    return {"ok": True, "handoff_id": result["data"]["id"], **_counts()}


if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/agent_mail/test_mcp_shim.py -v`
Expected: 3 passed

- [ ] **Step 6: Manual stdio smoke (backend running not required for tools/list)**

Run: `cd backend && source venv/bin/activate && printf '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}\n' | timeout 5 python mcp_shim/agent_mail_server.py 2>/dev/null | head -1`
Expected: a JSON-RPC initialize result naming `claude-deck-mail`

- [ ] **Step 7: Commit**

```bash
git add backend/requirements.txt backend/mcp_shim/ backend/tests/agent_mail/test_mcp_shim.py
git commit -m "feat: add agent mail MCP stdio shim with deck_* tools"
```

---

### Task 10: Frontend types and API client

**Files:**
- Create: `frontend/src/types/agentMail.ts`
- Create: `frontend/src/features/agent-mail/api.ts`

- [ ] **Step 1: Create the types** (snake_case mirrors backend — repo convention)

```typescript
// frontend/src/types/agentMail.ts
export type MailMemberStatus = 'connected' | 'observed' | 'offline'
export type MailMessageKind = 'message' | 'broadcast' | 'context_request' | 'handoff' | 'answer'
export type MailRequestStatus = 'pending' | 'answered' | 'acknowledged'

export interface MailSession {
  id: number
  provider: string
  source: 'hook' | 'mcp' | 'observed'
  session_key: string
  cwd?: string | null
  tmux_target?: string | null
  mailbox_status: MailMemberStatus
  activity?: string | null
  last_seen_at?: string | null
}

export interface MailMember {
  id: number
  repo_id: string
  repo_path: string
  repo_name: string
  display_name: string
  role?: string | null
  charter?: string | null
  status: MailMemberStatus
  unread_count: number
  pending_count: number
  sessions: MailSession[]
}

export interface TeamListResponse {
  members: MailMember[]
}

export interface MailMessage {
  id: number
  thread_root_id?: number | null
  kind: MailMessageKind
  sender_member_id?: number | null
  sender_name: string
  recipient_member_id?: number | null
  subject?: string | null
  body_markdown: string
  payload?: Record<string, unknown> | null
  request_status?: MailRequestStatus | null
  is_stale: boolean
  read_at?: string | null
  acked_at?: string | null
  created_at: string
}

export interface MailThread {
  root: MailMessage
  replies: MailMessage[]
}

export interface MailMessageCreate {
  kind?: MailMessageKind
  sender_member_id?: number | null
  recipient_member_id?: number | null
  thread_root_id?: number | null
  subject?: string | null
  body_markdown: string
  payload?: Record<string, unknown> | null
}

export interface AgentMailInstallStatus {
  claude_code_hooks: string[]
  claude_code_hooks_missing: string[]
  claude_code_mcp_installed: boolean
  codex_cli_available: boolean
  codex_mcp_installed: boolean
  curl_available: boolean
  shim_path: string
  python_path: string
  deck_url: string
}

export interface AgentMailSnippets {
  codex_config_toml: string
  codex_agents_md: string
}
```

- [ ] **Step 2: Create the API client** (matches the presence feature's `apiClient` callable style; endpoints have no leading slash)

```typescript
// frontend/src/features/agent-mail/api.ts
import { apiClient } from '@/lib/api'
import type {
  AgentMailInstallStatus,
  AgentMailSnippets,
  MailMember,
  MailMessage,
  MailMessageCreate,
  MailThread,
  TeamListResponse,
} from '@/types/agentMail'

const BASE = 'agent-mail'

export async function fetchTeam(sync = true): Promise<TeamListResponse> {
  return apiClient<TeamListResponse>(`${BASE}/team?sync=${sync}`)
}

export async function updateMember(
  memberId: number,
  update: { display_name?: string; role?: string; charter?: string }
): Promise<MailMember> {
  return apiClient<MailMember>(`${BASE}/members/${memberId}`, {
    method: 'PATCH',
    body: JSON.stringify(update),
  })
}

export async function fetchMessages(): Promise<MailMessage[]> {
  return apiClient<MailMessage[]>(`${BASE}/messages`)
}

export async function fetchThread(rootId: number): Promise<MailThread> {
  return apiClient<MailThread>(`${BASE}/messages/${rootId}/thread`)
}

export async function sendMessage(request: MailMessageCreate): Promise<MailMessage> {
  return apiClient<MailMessage>(`${BASE}/messages`, {
    method: 'POST',
    body: JSON.stringify(request),
  })
}

export async function fetchInstallStatus(): Promise<AgentMailInstallStatus> {
  return apiClient<AgentMailInstallStatus>(`${BASE}/install/status`)
}

const CONFIRMED = { method: 'POST', body: JSON.stringify({ confirmed: true }) }

export async function applyClaudeCodeInstall(): Promise<AgentMailInstallStatus> {
  return apiClient<AgentMailInstallStatus>(`${BASE}/install/claude-code/apply`, CONFIRMED)
}

export async function uninstallClaudeCode(): Promise<AgentMailInstallStatus> {
  return apiClient<AgentMailInstallStatus>(`${BASE}/install/claude-code/uninstall`, CONFIRMED)
}

export async function applyCodexInstall(): Promise<AgentMailInstallStatus> {
  return apiClient<AgentMailInstallStatus>(`${BASE}/install/codex/apply`, CONFIRMED)
}

export async function uninstallCodex(): Promise<AgentMailInstallStatus> {
  return apiClient<AgentMailInstallStatus>(`${BASE}/install/codex/uninstall`, CONFIRMED)
}

export async function fetchSnippets(): Promise<AgentMailSnippets> {
  return apiClient<AgentMailSnippets>(`${BASE}/install/snippets`)
}
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/agentMail.ts frontend/src/features/agent-mail/api.ts
git commit -m "feat: add agent mail frontend types and api client"
```

---

### Task 11: Frontend page — Team, Requests, Install tabs + dialogs

**Files:**
- Create: `frontend/src/features/agent-mail/AgentMailPage.tsx`, `TeamTab.tsx`, `RequestsTab.tsx`, `InstallTab.tsx`, `MemberEditDialog.tsx`, `ComposeDialog.tsx`, `ThreadDialog.tsx`

- [ ] **Step 1: Shared status badge helper + Team tab**

```tsx
// frontend/src/features/agent-mail/TeamTab.tsx
// One card per member (per repo). Multiple sessions render as compact source
// badges under the member — never as separate teammates.
import { useMemo, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import type { MailMember, MailMemberStatus } from '@/types/agentMail'

export const STATUS_CLASSES: Record<string, string> = {
  connected: 'bg-green-500/15 text-green-600 dark:text-green-400',
  observed: 'bg-amber-500/15 text-amber-600 dark:text-amber-400',
  offline: 'bg-muted text-muted-foreground',
}

const STATUS_FILTERS: Array<MailMemberStatus | 'all'> = ['all', 'connected', 'observed', 'offline']

interface TeamTabProps {
  members: MailMember[]
  onEdit: (member: MailMember) => void
  onMessage: (member: MailMember) => void
}

export function TeamTab({ members, onEdit, onMessage }: TeamTabProps) {
  const [statusFilter, setStatusFilter] = useState<MailMemberStatus | 'all'>('all')
  const [search, setSearch] = useState('')

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase()
    return members.filter((m) => {
      if (statusFilter !== 'all' && m.status !== statusFilter) return false
      if (!q) return true
      return (
        m.display_name.toLowerCase().includes(q) ||
        m.repo_name.toLowerCase().includes(q) ||
        (m.role ?? '').toLowerCase().includes(q)
      )
    })
  }, [members, statusFilter, search])

  if (members.length === 0) {
    return (
      <div className="text-center text-muted-foreground py-12">
        <p className="font-medium">No team members yet.</p>
        <p className="text-sm mt-2">
          Start Claude Code or Codex in tmux to appear as observed, or open the Install tab
          to make agents fully addressable.
        </p>
      </div>
    )
  }
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {STATUS_FILTERS.map((s) => (
          <Button
            key={s}
            size="sm"
            variant={statusFilter === s ? 'default' : 'outline'}
            onClick={() => setStatusFilter(s)}
          >
            {s}
          </Button>
        ))}
        <Input
          className="max-w-xs ml-auto"
          placeholder="Search name, repo, role…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {visible.map((member) => (
          <Card key={member.id}>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between gap-2">
                <CardTitle className="text-base truncate">{member.display_name}</CardTitle>
                <Badge className={STATUS_CLASSES[member.status]}>{member.status}</Badge>
              </div>
              <p className="text-xs text-muted-foreground truncate">
                {member.role ? `${member.role} · ` : ''}{member.repo_name}
              </p>
            </CardHeader>
            <CardContent className="space-y-2">
              {member.charter && (
                <p className="text-xs text-muted-foreground line-clamp-2">{member.charter}</p>
              )}
              {member.sessions[0]?.activity && (
                <p className="text-xs truncate">⚡ {member.sessions[0].activity}</p>
              )}
              {member.sessions.length > 0 && (
                <div className="flex flex-wrap items-center gap-1">
                  {member.sessions.map((s) => (
                    <Badge key={s.id} variant="outline" className="text-[10px]">
                      {s.provider} · {s.source}
                    </Badge>
                  ))}
                </div>
              )}
              <div className="flex items-center gap-2 text-xs">
                {member.unread_count > 0 && (
                  <Badge variant="secondary">{member.unread_count} unread</Badge>
                )}
                {member.pending_count > 0 && (
                  <Badge variant="destructive">{member.pending_count} pending</Badge>
                )}
              </div>
              <div className="flex gap-2 pt-1">
                <Button size="sm" variant="outline" onClick={() => onEdit(member)}>
                  Edit
                </Button>
                <Button size="sm" variant="outline" onClick={() => onMessage(member)}>
                  Message
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Member edit dialog** (the director's casting tool — name, role, charter)

```tsx
// frontend/src/features/agent-mail/MemberEditDialog.tsx
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { MODAL_SIZES } from '@/lib/constants'
import type { MailMember } from '@/types/agentMail'
import { updateMember } from './api'

interface MemberEditDialogProps {
  member: MailMember | null
  onClose: () => void
  onSaved: () => void
}

export function MemberEditDialog({ member, onClose, onSaved }: MemberEditDialogProps) {
  const [displayName, setDisplayName] = useState('')
  const [role, setRole] = useState('')
  const [charter, setCharter] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (member) {
      setDisplayName(member.display_name)
      setRole(member.role ?? '')
      setCharter(member.charter ?? '')
      setError(null)
    }
  }, [member])

  const handleSave = async () => {
    if (!member) return
    setSaving(true)
    setError(null)
    try {
      await updateMember(member.id, { display_name: displayName, role, charter })
      onSaved()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={member !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className={MODAL_SIZES.SM}>
        <DialogHeader>
          <DialogTitle>Edit team member</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1">
            <Label htmlFor="am-name">Name</Label>
            <Input id="am-name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="am-role">Role</Label>
            <Input
              id="am-role" value={role} placeholder="e.g. backend expert"
              onChange={(e) => setRole(e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="am-charter">Charter</Label>
            <Textarea
              id="am-charter" value={charter} rows={4}
              placeholder="Standing instructions injected into this agent's sessions, e.g. 'Owns the FastAPI backend; other agents should ask you about auth and the DB.'"
              onChange={(e) => setCharter(e.target.value)}
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={handleSave} disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 3: Compose dialog** (director sends direct/broadcast/request/handoff)

```tsx
// frontend/src/features/agent-mail/ComposeDialog.tsx
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { MODAL_SIZES } from '@/lib/constants'
import type { MailMember, MailMessageKind } from '@/types/agentMail'
import { sendMessage } from './api'

const COMPOSE_KINDS: { value: MailMessageKind; label: string }[] = [
  { value: 'message', label: 'Message' },
  { value: 'broadcast', label: 'Broadcast (all members)' },
  { value: 'context_request', label: 'Context request' },
  { value: 'handoff', label: 'Handoff' },
]

interface ComposeDialogProps {
  open: boolean
  members: MailMember[]
  initialRecipient?: MailMember | null
  onClose: () => void
  onSent: () => void
}

export function ComposeDialog({ open, members, initialRecipient, onClose, onSent }: ComposeDialogProps) {
  const [kind, setKind] = useState<MailMessageKind>('message')
  const [recipientId, setRecipientId] = useState<string>('')
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setKind('message')
      setRecipientId(initialRecipient ? String(initialRecipient.id) : '')
      setSubject('')
      setBody('')
      setError(null)
    }
  }, [open, initialRecipient])

  const needsRecipient = kind !== 'broadcast'

  const handleSend = async () => {
    if (!body.trim() || (needsRecipient && !recipientId)) return
    setSending(true)
    setError(null)
    try {
      await sendMessage({
        kind,
        sender_member_id: null, // human director
        recipient_member_id: needsRecipient ? Number(recipientId) : null,
        subject: subject.trim() || null,
        body_markdown: body,
      })
      onSent()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to send')
    } finally {
      setSending(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className={MODAL_SIZES.SM}>
        <DialogHeader>
          <DialogTitle>New message (as Director)</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label>Type</Label>
              <Select value={kind} onValueChange={(v) => setKind(v as MailMessageKind)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {COMPOSE_KINDS.map((k) => (
                    <SelectItem key={k.value} value={k.value}>{k.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {needsRecipient && (
              <div className="space-y-1">
                <Label>To</Label>
                <Select value={recipientId} onValueChange={setRecipientId}>
                  <SelectTrigger><SelectValue placeholder="Select member" /></SelectTrigger>
                  <SelectContent>
                    {members.map((m) => (
                      <SelectItem key={m.id} value={String(m.id)}>
                        {m.display_name} ({m.repo_name})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>
          <div className="space-y-1">
            <Label htmlFor="am-subject">Subject</Label>
            <Input id="am-subject" value={subject} onChange={(e) => setSubject(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="am-body">Body (markdown)</Label>
            <Textarea id="am-body" value={body} rows={6} onChange={(e) => setBody(e.target.value)} />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={handleSend} disabled={sending || !body.trim() || (needsRecipient && !recipientId)}>
            {sending ? 'Sending…' : 'Send'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 4: Requests tab + thread dialog**

```tsx
// frontend/src/features/agent-mail/RequestsTab.tsx
import { useMemo, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { CLICKABLE_CARD } from '@/lib/constants'
import type { MailMember, MailMessage } from '@/types/agentMail'

const KIND_LABELS: Record<string, string> = {
  message: 'Message',
  broadcast: 'Broadcast',
  context_request: 'Context request',
  handoff: 'Handoff',
  answer: 'Answer',
}

const STATUS_BADGES: Record<string, string> = {
  pending: 'bg-amber-500/15 text-amber-600 dark:text-amber-400',
  answered: 'bg-blue-500/15 text-blue-600 dark:text-blue-400',
  acknowledged: 'bg-green-500/15 text-green-600 dark:text-green-400',
}

const REQUEST_FILTERS = ['all', 'pending', 'answered', 'acknowledged', 'stale'] as const
type RequestFilter = (typeof REQUEST_FILTERS)[number]

interface RequestsTabProps {
  messages: MailMessage[]
  members: MailMember[]
  onOpen: (message: MailMessage) => void
}

export function RequestsTab({ messages, members, onOpen }: RequestsTabProps) {
  const [filter, setFilter] = useState<RequestFilter>('all')

  const memberName = (id?: number | null) =>
    id == null ? 'Director' : members.find((m) => m.id === id)?.display_name ?? `#${id}`

  const visible = useMemo(
    () =>
      messages.filter((m) => {
        if (filter === 'all') return true
        if (filter === 'stale') return m.is_stale
        return m.request_status === filter
      }),
    [messages, filter]
  )

  if (messages.length === 0) {
    return (
      <div className="text-center text-muted-foreground py-12">
        <p className="font-medium">No messages yet.</p>
        <p className="text-sm mt-2">
          Agents create requests with deck_request_context / deck_create_handoff, or compose
          one yourself with New message.
        </p>
      </div>
    )
  }
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {REQUEST_FILTERS.map((f) => (
          <Button
            key={f}
            size="sm"
            variant={filter === f ? 'default' : 'outline'}
            onClick={() => setFilter(f)}
          >
            {f}
          </Button>
        ))}
      </div>
      <div className="space-y-2">
        {visible.map((msg) => (
          <Card
            key={msg.id}
            className={CLICKABLE_CARD}
            role="button"
            tabIndex={0}
            onClick={() => onOpen(msg)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                onOpen(msg)
              }
            }}
          >
            <CardContent className="py-3 flex items-center gap-3">
              <Badge variant="outline">{KIND_LABELS[msg.kind] ?? msg.kind}</Badge>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium truncate">{msg.subject || msg.body_markdown}</p>
                <p className="text-xs text-muted-foreground">
                  {msg.sender_name} → {memberName(msg.recipient_member_id)} ·{' '}
                  {new Date(msg.created_at + 'Z').toLocaleString()}
                </p>
              </div>
              {msg.is_stale && <Badge variant="destructive">stale</Badge>}
              {msg.request_status && (
                <Badge className={STATUS_BADGES[msg.request_status]}>{msg.request_status}</Badge>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
```

```tsx
// frontend/src/features/agent-mail/ThreadDialog.tsx
import { useCallback, useEffect, useState } from 'react'
import { MarkdownRenderer } from '@/components/shared/MarkdownRenderer'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Textarea } from '@/components/ui/textarea'
import { MODAL_SIZES } from '@/lib/constants'
import type { MailThread } from '@/types/agentMail'
import { fetchThread, sendMessage } from './api'

interface ThreadDialogProps {
  rootId: number | null
  onClose: () => void
  onChanged: () => void
}

export function ThreadDialog({ rootId, onClose, onChanged }: ThreadDialogProps) {
  const [thread, setThread] = useState<MailThread | null>(null)
  const [reply, setReply] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (rootId === null) return
    try {
      setThread(await fetchThread(rootId))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load thread')
    }
  }, [rootId])

  useEffect(() => {
    setThread(null)
    setReply('')
    setError(null)
    void load()
  }, [load])

  const handleReply = async () => {
    if (rootId === null || !reply.trim()) return
    setSending(true)
    try {
      await sendMessage({
        sender_member_id: null, // director
        thread_root_id: rootId,
        body_markdown: reply,
      })
      setReply('')
      await load()
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to reply')
    } finally {
      setSending(false)
    }
  }

  const all = thread ? [thread.root, ...thread.replies] : []

  return (
    <Dialog open={rootId !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className={MODAL_SIZES.MD}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {thread?.root.subject || 'Thread'}
            {thread?.root.request_status && (
              <Badge variant="outline">{thread.root.request_status}</Badge>
            )}
          </DialogTitle>
        </DialogHeader>
        <ScrollArea className="max-h-[50vh]">
          <div className="space-y-4 pr-3">
            {all.map((msg) => (
              <div key={msg.id} className="rounded-md border p-3">
                <p className="text-xs text-muted-foreground mb-1">
                  {msg.sender_name} · {msg.kind} ·{' '}
                  {new Date(msg.created_at + 'Z').toLocaleString()}
                </p>
                <MarkdownRenderer content={msg.body_markdown} />
              </div>
            ))}
          </div>
        </ScrollArea>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <div className="space-y-2">
          <Textarea
            value={reply} rows={3} placeholder="Reply as Director…"
            onChange={(e) => setReply(e.target.value)}
          />
          <div className="flex justify-end">
            <Button onClick={handleReply} disabled={sending || !reply.trim()}>
              {sending ? 'Sending…' : 'Reply'}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
```

Note: check `MarkdownRenderer`'s actual prop name (`content` vs `children`) in `frontend/src/components/shared/MarkdownRenderer.tsx` before using, and adjust.

- [ ] **Step 5: Install tab**

```tsx
// frontend/src/features/agent-mail/InstallTab.tsx
// Every mutation goes through a confirm dialog listing the exact files touched;
// the backend takes a best-effort config backup before writing.
import { useCallback, useEffect, useState } from 'react'
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { AgentMailInstallStatus, AgentMailSnippets } from '@/types/agentMail'
import {
  applyClaudeCodeInstall, applyCodexInstall, fetchInstallStatus, fetchSnippets,
  uninstallClaudeCode, uninstallCodex,
} from './api'

interface PendingAction {
  title: string
  mutations: string[]
  run: () => Promise<AgentMailInstallStatus>
}

export function InstallTab() {
  const [status, setStatus] = useState<AgentMailInstallStatus | null>(null)
  const [snippets, setSnippets] = useState<AgentMailSnippets | null>(null)
  const [pending, setPending] = useState<PendingAction | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [s, sn] = await Promise.all([fetchInstallStatus(), fetchSnippets()])
      setStatus(s)
      setSnippets(sn)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load install status')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const confirmAndRun = async () => {
    if (!pending) return
    setBusy(true)
    setError(null)
    try {
      setStatus(await pending.run())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Operation failed')
    } finally {
      setBusy(false)
      setPending(null)
    }
  }

  const ccInstalled =
    status !== null &&
    status.claude_code_hooks_missing.length === 0 &&
    status.claude_code_mcp_installed

  return (
    <div className="space-y-4 max-w-3xl">
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            Claude Code
            {status && (
              <Badge variant={ccInstalled ? 'default' : 'secondary'}>
                {ccInstalled ? 'installed' : 'not installed'}
              </Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p className="text-muted-foreground">
            Installs 4 hooks (SessionStart, UserPromptSubmit, SessionEnd, PostToolUse) in
            ~/.claude/settings.json and the claude-deck-mail MCP server at user scope.
            Hooks fail soft when Claude Deck is not running. Already-running sessions need
            a restart to pick this up.
          </p>
          {status && (
            <ul className="text-xs space-y-1">
              <li>Hooks installed: {status.claude_code_hooks.join(', ') || 'none'}</li>
              <li>Hooks missing: {status.claude_code_hooks_missing.join(', ') || 'none'}</li>
              <li>MCP server: {status.claude_code_mcp_installed ? 'installed' : 'missing'}</li>
              {!status.curl_available && (
                <li className="text-destructive">curl not found on PATH — hooks will not work</li>
              )}
            </ul>
          )}
          <div className="flex gap-2">
            <Button
              size="sm"
              disabled={busy || ccInstalled}
              onClick={() =>
                setPending({
                  title: 'Install Agent Mail for Claude Code?',
                  mutations: [
                    '~/.claude/settings.json — add 4 Agent Mail hooks (user scope)',
                    '~/.claude.json — add the claude-deck-mail MCP server (user scope)',
                    'A config backup is created first (visible on the Backup page)',
                  ],
                  run: applyClaudeCodeInstall,
                })
              }
            >
              Install
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() =>
                setPending({
                  title: 'Uninstall Agent Mail from Claude Code?',
                  mutations: [
                    '~/.claude/settings.json — remove Agent Mail hooks only',
                    '~/.claude.json — remove the claude-deck-mail MCP server',
                    'A config backup is created first (visible on the Backup page)',
                  ],
                  run: uninstallClaudeCode,
                })
              }
            >
              Uninstall
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            Codex CLI
            {status && (
              <Badge variant={status.codex_mcp_installed ? 'default' : 'secondary'}>
                {status.codex_mcp_installed
                  ? 'installed'
                  : status.codex_cli_available
                    ? 'not installed'
                    : 'codex not detected'}
              </Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p className="text-muted-foreground">
            Codex has no lifecycle hooks; it participates via MCP (one-click below, runs
            `codex mcp add`) plus an AGENTS.md standing instruction (manual copy).
          </p>
          <div className="flex gap-2">
            <Button
              size="sm"
              disabled={busy || !status?.codex_cli_available || status?.codex_mcp_installed}
              onClick={() =>
                setPending({
                  title: 'Install Agent Mail for Codex CLI?',
                  mutations: [
                    '~/.codex/config.toml — add claude-deck-mail via `codex mcp add`',
                    'A Codex config backup is created first (visible on the Backup page)',
                  ],
                  run: applyCodexInstall,
                })
              }
            >
              Install
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={busy || !status?.codex_mcp_installed}
              onClick={() =>
                setPending({
                  title: 'Uninstall Agent Mail from Codex CLI?',
                  mutations: [
                    '~/.codex/config.toml — remove claude-deck-mail via `codex mcp remove`',
                    'A Codex config backup is created first (visible on the Backup page)',
                  ],
                  run: uninstallCodex,
                })
              }
            >
              Uninstall
            </Button>
          </div>
          <p className="text-muted-foreground">Add this to ~/.codex/AGENTS.md (manual):</p>
          <pre className="text-xs bg-muted rounded-md p-3 overflow-x-auto whitespace-pre-wrap">
            {snippets?.codex_agents_md}
          </pre>
          <Button
            size="sm" variant="outline"
            onClick={() => snippets && navigator.clipboard.writeText(snippets.codex_agents_md)}
          >
            Copy AGENTS.md snippet
          </Button>
          <p className="text-muted-foreground">
            Prefer manual MCP setup? Equivalent config.toml snippet:
          </p>
          <pre className="text-xs bg-muted rounded-md p-3 overflow-x-auto">
            {snippets?.codex_config_toml}
          </pre>
          <Button
            size="sm" variant="outline"
            onClick={() => snippets && navigator.clipboard.writeText(snippets.codex_config_toml)}
          >
            Copy TOML
          </Button>
        </CardContent>
      </Card>
      {error && <p className="text-sm text-destructive">{error}</p>}

      <AlertDialog open={pending !== null} onOpenChange={(open) => !open && setPending(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{pending?.title}</AlertDialogTitle>
            <AlertDialogDescription asChild>
              <ul className="list-disc pl-5 space-y-1 text-sm">
                {pending?.mutations.map((m) => (
                  <li key={m}>{m}</li>
                ))}
              </ul>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
            <AlertDialogAction disabled={busy} onClick={confirmAndRun}>
              {busy ? 'Working…' : 'Confirm'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
```

- [ ] **Step 6: The page (polling + tab wiring)**

```tsx
// frontend/src/features/agent-mail/AgentMailPage.tsx
import { useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { MailMember, MailMessage } from '@/types/agentMail'
import { fetchMessages, fetchTeam } from './api'
import { ComposeDialog } from './ComposeDialog'
import { InstallTab } from './InstallTab'
import { MemberEditDialog } from './MemberEditDialog'
import { RequestsTab } from './RequestsTab'
import { TeamTab } from './TeamTab'
import { ThreadDialog } from './ThreadDialog'

const POLL_MS = 5000

export function AgentMailPage() {
  const [members, setMembers] = useState<MailMember[]>([])
  const [messages, setMessages] = useState<MailMessage[]>([])
  const [editing, setEditing] = useState<MailMember | null>(null)
  const [composeOpen, setComposeOpen] = useState(false)
  const [composeRecipient, setComposeRecipient] = useState<MailMember | null>(null)
  const [openThreadId, setOpenThreadId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async (sync = false) => {
    try {
      const [team, msgs] = await Promise.all([fetchTeam(sync), fetchMessages()])
      setMembers(team.members)
      setMessages(msgs)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    }
  }, [])

  useEffect(() => {
    void refresh(true)
    const interval = setInterval(() => void refresh(false), POLL_MS)
    return () => clearInterval(interval)
  }, [refresh])

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Agent Mail</h1>
          <p className="text-sm text-muted-foreground">
            Your local agent team: identities, requests, handoffs.
          </p>
        </div>
        <Button onClick={() => { setComposeRecipient(null); setComposeOpen(true) }}>
          New message
        </Button>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}

      <Tabs defaultValue="team">
        <TabsList>
          <TabsTrigger value="team">Team</TabsTrigger>
          <TabsTrigger value="requests">Requests</TabsTrigger>
          <TabsTrigger value="install">Install</TabsTrigger>
        </TabsList>
        <TabsContent value="team" className="mt-4">
          <TeamTab
            members={members}
            onEdit={setEditing}
            onMessage={(m) => { setComposeRecipient(m); setComposeOpen(true) }}
          />
        </TabsContent>
        <TabsContent value="requests" className="mt-4">
          <RequestsTab
            messages={messages}
            members={members}
            onOpen={(msg) => setOpenThreadId(msg.id)}
          />
        </TabsContent>
        <TabsContent value="install" className="mt-4">
          <InstallTab />
        </TabsContent>
      </Tabs>

      <MemberEditDialog member={editing} onClose={() => setEditing(null)} onSaved={() => void refresh()} />
      <ComposeDialog
        open={composeOpen}
        members={members}
        initialRecipient={composeRecipient}
        onClose={() => setComposeOpen(false)}
        onSent={() => void refresh()}
      />
      <ThreadDialog
        rootId={openThreadId}
        onClose={() => setOpenThreadId(null)}
        onChanged={() => void refresh()}
      />
    </div>
  )
}
```

- [ ] **Step 7: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors (fix any shadcn import mismatches — e.g. confirm `select.tsx` exports match usage, `MarkdownRenderer` prop name)

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/agent-mail/
git commit -m "feat: add agent mail page with team, requests, and install tabs"
```

---

### Task 12: Route + sidebar nav

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/layout/Sidebar.tsx`

- [ ] **Step 1: Add the route.** In `frontend/src/App.tsx`, import and add next to the presence route (around line 57):

```tsx
import { AgentMailPage } from '@/features/agent-mail/AgentMailPage'
```

```tsx
<Route path="agent-mail" element={<AgentMailPage />} />
```

- [ ] **Step 2: Add the nav item.** In `frontend/src/components/layout/Sidebar.tsx`, add `Mailbox` to the lucide-react import and add next to the Presence item (line ~64):

```tsx
{ name: 'Agent Mail', href: '/agent-mail', icon: Mailbox },
```

- [ ] **Step 3: Build + lint**

Run: `cd frontend && npm run build && npm run lint`
Expected: build succeeds, no new lint errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/layout/Sidebar.tsx
git commit -m "feat: add agent mail route and nav entry"
```

---

### Task 13: Docs

**Files:**
- Create: `docs/features/agent-mail.md`
- Modify: `README.md` (one line in the features list)

- [ ] **Step 1: Write the feature doc.** Sections (write real content, not stubs — source it from this plan's Design decisions):

```markdown
# Agent Mail

What it is: a local coordination layer — durable per-repo team members, director-assigned
roles/charters, structured context requests and handoffs between agents.

## Concepts          (member vs session; observed/connected/offline; message kinds;
                      request lifecycle pending → answered → acknowledged; stale)
## How delivery works (SessionStart + UserPromptSubmit injection; compaction recovery via
                      the SessionStart compact source; tool-response piggyback counts)
## Install            (Claude Code one-click; Codex one-click MCP via `codex mcp add` +
                      manual AGENTS.md snippet; confirm dialog + automatic backup; restart note)
## MCP tools          (table of the 8 deck_* tools)
## Security & limits  (local trust model — no auth token, same posture as the rest of the
                      Deck API; recommend binding the backend to 127.0.0.1; no transcript
                      sharing; MVP limits stated plainly: machine-global visibility — every
                      repo's agents see each other, filters not walls — and one member per
                      repo — two sessions in the same repo share one identity and inbox;
                      leases/PreToolUse guard are future work)
## Troubleshooting    (hooks need curl; sessions must restart after install; Deck down =
                      hooks no-op; check /api/v1/agent-mail/install/status)
```

- [ ] **Step 2: Add README feature line**

```markdown
- **Agent Mail** — local agent team coordination: durable per-repo identities, director-assigned roles, structured context requests and handoffs, with inbox state injected into Claude Code sessions via hooks.
```

- [ ] **Step 3: Commit**

```bash
git add docs/features/agent-mail.md README.md
git commit -m "docs: document agent mail feature"
```

---

### Task 14: Final verification + manual smoke

- [ ] **Step 1: Full automated verification**

```bash
cd backend && source venv/bin/activate && pytest tests/ -v
cd ../frontend && npm run build && npm run lint
```
Expected: all backend tests pass (existing + ~40 new), frontend build + lint clean.

- [ ] **Step 2: Manual smoke** (requires `./scripts/dev.sh` running; use the browser)

1. **Empty state** — open `/agent-mail`; Team/Requests show useful empty states, no console errors.
2. **Observed** — start Claude Code in a tmux pane; within one poll the member appears as `observed`, named after the repo.
3. **Install** — Install tab → Install; confirm Hooks page and MCP Servers page still parse their configs and show the 4 hooks + `claude-deck-mail` server.
4. **Connected + injection** — start a NEW Claude Code session in a repo; verify (a) the member flips to `connected`, (b) the session's context contains the `[Claude Deck Agent Mail]` identity block (ask the agent "what team context were you given?").
5. **Director casting** — edit the member: set name/role/charter; start another session in that repo; the injected block shows the new identity. **This verifies the durable-member design.**
6. **Request roundtrip** — two sessions in different repos: agent A `deck_request_context` → B's next user prompt shows the `[Agent Mail]` nudge → B `deck_check_inbox` → `deck_reply` → A sees the answer; Requests tab shows pending → answered; A `deck_ack_message` → acknowledged.
7. **Compaction recovery** — in a session with unread mail run `/compact`; confirm the SessionStart hook re-injects the mailbox block (requires Claude Code version where SessionStart fires with source `compact`; if not, the UserPromptSubmit nudge still covers it — note which path worked).
8. **Fail soft** — stop Claude Deck; start a Claude Code session; it must work normally (hooks silently no-op); restart Deck; next prompt re-heartbeats.
9. **Same-repo sharing** — start TWO Claude Code sessions in the SAME repo; confirm they attach to ONE member (Team tab shows one card with two session badges, not two teammates), and a message to that member is visible to both sessions' inbox checks.
10. **Codex one-click** — Install tab → Codex Install → confirm; verify `codex mcp list` shows `claude-deck-mail`; start a Codex session and confirm `deck_whoami` registers it as connected with provider `codex-cli`.

- [ ] **Step 3: Commit any smoke-test fixes, then run the project's pre-merge flow** (`/code-review`, `/simplify`, `/verify` per CLAUDE.md)

---

## Known risks (watch during implementation)

1. **HTTP-response-as-hook-output**: verified up front by the Task 1.5 spike — do not proceed past Task 1.5 without recording its PASS/FAIL outcome. If it failed, the wrapper-script fallback documented there applies and the backend is unchanged.
1b. **Codex executor arg constraints**: `SAFE_ARG_PATTERN` forbids spaces and quotes; if the claude-deck checkout path or venv python path contains spaces, `codex mcp add` will be rejected by the executor — `apply_codex_install` surfaces this as a 400 with the reason, and the manual TOML snippet is the workaround.
2. **MCP-session-to-member correlation**: the shim correlates by cwd→repo_id only. Two members never collide (repo-keyed), but a member's session list may show one `hook` and one `mcp` session for the same real agent. Cosmetic; acceptable for MVP.
3. **`mcp` SDK API drift**: `FastMCP` import path (`mcp.server.fastmcp`) is correct for `mcp>=1.2`; pin higher if `list_tools` signature differs.
4. **`datetime.utcnow` deprecation warnings** on Python 3.12+: harmless, matches existing codebase style; do not mix in aware datetimes.

## Deferred (Phase 2 — do not build now)

Path leases + PreToolUse guard (for shared-working-tree multi-agent), automatic `AGENTS.md` writing for Codex, WebSocket realtime UI (reuse presence WS pattern), multi-member-per-repo seats, scopes/workspaces if the flat roster gets noisy, optional API token hardening.
