"""Claude Deck Agent Mail MCP server over stdio."""
import os
import threading
import time
import uuid
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

DECK_URL = os.environ.get("CLAUDE_DECK_URL", "http://127.0.0.1:8000").rstrip("/")
PROVIDER = os.environ.get("CLAUDE_DECK_PROVIDER", "unknown")
API = f"{DECK_URL}/api/v1/agent-mail"
DECK_HTTP_TIMEOUT = httpx.Timeout(connect=0.5, read=15.0, write=5.0, pool=0.5)
OFFLINE_BACKOFF_SECONDS = 2.0
HEARTBEAT_INTERVAL_SECONDS = 60.0
HEARTBEAT_UNAVAILABLE_INTERVAL_SECONDS = 300.0

mcp = FastMCP("claude-deck-mail")
_register_lock = threading.Lock()

_state: dict[str, Any] = {
    "member_id": None,
    "session_key": f"mcp:{uuid.uuid4().hex[:12]}",
    "offline_until": 0.0,
    "last_error": None,
}


def _env_int(name: str) -> int | None:
    value = os.environ.get(name)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _unreachable_result(message: str) -> dict:
    return {
        "ok": False,
        "error": {"code": "deck_unreachable", "message": message},
        "suggestion": "Continue without mailbox coordination, or ask the user to start Claude Deck.",
    }


def _request(method: str, path: str, **kwargs) -> dict:
    now = time.monotonic()
    if now < _state.get("offline_until", 0.0):
        return _unreachable_result(_state.get("last_error") or "Claude Deck is unavailable.")
    try:
        response = httpx.request(method, f"{API}{path}", timeout=DECK_HTTP_TIMEOUT, **kwargs)
        response.raise_for_status()
        _state["offline_until"] = 0.0
        _state["last_error"] = None
        return {"ok": True, "data": response.json()}
    except httpx.HTTPError as exc:
        _state["offline_until"] = time.monotonic() + OFFLINE_BACKOFF_SECONDS
        _state["last_error"] = str(exc)
        return _unreachable_result(str(exc))


def _ensure_registered() -> dict:
    with _register_lock:
        payload = {
            "source": "mcp",
            "provider": PROVIDER,
            "cwd": os.getcwd(),
            "session_key": _state["session_key"],
            "pid": os.getppid(),
        }
        team_preset_id = _env_int("CLAUDE_DECK_TEAM_PRESET_ID")
        team_slot_id = _env_int("CLAUDE_DECK_TEAM_SLOT_ID")
        if team_preset_id is not None:
            payload["team_preset_id"] = team_preset_id
        if team_slot_id is not None:
            payload["team_slot_id"] = team_slot_id
        result = _request(
            "POST",
            "/agent/register",
            json=payload,
        )
        if result["ok"]:
            _state["member_id"] = result["data"]["member"]["id"]
        return result


def _heartbeat_once() -> float:
    result = _ensure_registered()
    if result["ok"]:
        return HEARTBEAT_INTERVAL_SECONDS
    return HEARTBEAT_UNAVAILABLE_INTERVAL_SECONDS


def _heartbeat_loop() -> None:
    while True:
        time.sleep(_heartbeat_once())


def _start_heartbeat_thread() -> threading.Thread:
    thread = threading.Thread(
        target=_heartbeat_loop,
        name="claude-deck-agent-mail-heartbeat",
        daemon=True,
    )
    thread.start()
    return thread


def _counts() -> dict:
    if _state["member_id"] is None:
        return {}
    result = _request(
        "GET",
        f"/agent/inbox?member_id={_state['member_id']}&unread_only=true&limit=1",
    )
    if not result["ok"]:
        return {}
    return {
        "unread_count": result["data"]["unread_count"],
        "pending_count": result["data"]["pending_count"],
    }


def _guard() -> Optional[dict]:
    registered = _ensure_registered()
    return None if registered["ok"] else registered


@mcp.tool()
def deck_whoami() -> dict:
    """Register with Claude Deck Agent Mail and return your participant identity, role,
    charter, repo, live status, and unread/pending inbox counts. Call this once when
    starting coordinated work."""
    err = _guard()
    if err:
        return err
    result = _request("GET", "/team?sync=false")
    if not result["ok"]:
        return result
    me = next(
        (member for member in result["data"]["members"] if member["id"] == _state["member_id"]),
        None,
    )
    return {"ok": True, "me": me, **_counts()}


@mcp.tool()
def deck_list_team() -> dict:
    """List all local Agent Mail participants Claude Deck knows about, including member
    ids, display names, roles, repos, team slots, charters, and live statuses."""
    err = _guard()
    if err:
        return err
    result = _request("GET", "/team?sync=false")
    if not result["ok"]:
        return result
    members = [
        {
            key: member.get(key)
            for key in (
                "id",
                "display_name",
                "participant_kind",
                "role",
                "repo_name",
                "status",
                "charter",
                "team_preset_name",
                "team_slot_name",
            )
        }
        for member in result["data"]["members"]
    ]
    return {"ok": True, "members": members, **_counts()}


@mcp.tool()
def deck_check_inbox(unread_only: bool = True, limit: int = 20) -> dict:
    """Read your Agent Mail inbox, including messages, context requests, handoffs, and
    answers. Returned messages are marked read. Check before major work and after
    finishing a task."""
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
    """Send a plain message to another team member. For answerable questions use
    deck_request_context; for handing work over use deck_create_handoff."""
    err = _guard()
    if err:
        return err
    result = _request(
        "POST",
        "/messages",
        json={
            "kind": "message",
            "sender_member_id": _state["member_id"],
            "recipient_member_id": to_member_id,
            "subject": subject or None,
            "body_markdown": body,
        },
    )
    if not result["ok"]:
        return result
    return {"ok": True, "message_id": result["data"]["id"], **_counts()}


@mcp.tool()
def deck_reply(thread_root_id: int, body: str) -> dict:
    """Reply in an existing thread. If the root is a pending context request addressed
    to you, your reply is recorded as the answer and resolves it."""
    err = _guard()
    if err:
        return err
    thread = _request("GET", f"/messages/{thread_root_id}/thread")
    if not thread["ok"]:
        return thread
    root = thread["data"]["root"]
    is_answer = (
        root["kind"] == "context_request"
        and root.get("request_status") == "pending"
        and root.get("recipient_member_id") == _state["member_id"]
    )
    result = _request(
        "POST",
        "/messages",
        json={
            "kind": "answer" if is_answer else "message",
            "sender_member_id": _state["member_id"],
            "thread_root_id": thread_root_id,
            "body_markdown": body,
        },
    )
    if not result["ok"]:
        return result
    return {
        "ok": True,
        "message_id": result["data"]["id"],
        "resolved_request": is_answer,
        **_counts(),
    }


@mcp.tool()
def deck_ack_message(message_id: int) -> dict:
    """Acknowledge a message. Acking an answer to your context request closes it; acking
    a handoff addressed to you accepts and closes the handoff."""
    err = _guard()
    if err:
        return err
    result = _request(
        "POST",
        f"/messages/{message_id}/ack",
        json={"member_id": _state["member_id"]},
    )
    if not result["ok"]:
        return result
    return {"ok": True, **_counts()}


@mcp.tool()
def deck_request_context(
    to_member_id: int,
    topic: str,
    why_needed: str = "",
    files_or_symbols: Optional[list[str]] = None,
) -> dict:
    """Ask another Agent Mail participant a structured question about something they know.
    Creates a pending context request they will be nudged to answer."""
    err = _guard()
    if err:
        return err
    files_or_symbols = files_or_symbols or []
    body = topic
    if why_needed:
        body += f"\n\n**Why needed:** {why_needed}"
    result = _request(
        "POST",
        "/messages",
        json={
            "kind": "context_request",
            "sender_member_id": _state["member_id"],
            "recipient_member_id": to_member_id,
            "subject": topic[:120],
            "body_markdown": body,
            "payload": {"why_needed": why_needed, "files_or_symbols": files_or_symbols},
        },
    )
    if not result["ok"]:
        return result
    return {"ok": True, "request_id": result["data"]["id"], **_counts()}


@mcp.tool()
def deck_create_handoff(
    to_member_id: int,
    summary: str,
    files: Optional[list[str]] = None,
    next_steps: Optional[list[str]] = None,
) -> dict:
    """Hand work over to another Agent Mail participant with a summary, touched files, and next
    steps. The recipient acknowledges it to accept the handoff."""
    err = _guard()
    if err:
        return err
    files = files or []
    next_steps = next_steps or []
    body_lines = ["## Handoff", "", f"**Summary:** {summary}"]
    if files:
        body_lines += ["", "**Files touched:**"] + [f"- `{file}`" for file in files]
    if next_steps:
        body_lines += ["", "**Next steps:**"] + [
            f"{index + 1}. {step}" for index, step in enumerate(next_steps)
        ]
    result = _request(
        "POST",
        "/messages",
        json={
            "kind": "handoff",
            "sender_member_id": _state["member_id"],
            "recipient_member_id": to_member_id,
            "subject": f"Handoff: {summary[:100]}",
            "body_markdown": "\n".join(body_lines),
            "payload": {"files": files, "next_steps": next_steps},
        },
    )
    if not result["ok"]:
        return result
    return {"ok": True, "handoff_id": result["data"]["id"], **_counts()}


if __name__ == "__main__":
    _start_heartbeat_thread()
    mcp.run()
