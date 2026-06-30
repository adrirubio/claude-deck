"""Claude Deck Agent Mail MCP server over stdio."""
import os
import threading
import time
import uuid
from typing import Any, Optional
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP

DECK_URL = os.environ.get("CLAUDE_DECK_URL", "http://127.0.0.1:8000").rstrip("/")
PROVIDER = os.environ.get("CLAUDE_DECK_PROVIDER", "unknown")
DECK_API = f"{DECK_URL}/api/v1"
API = f"{DECK_API}/agent-mail"
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


def _http_error_result(exc: httpx.HTTPStatusError) -> dict:
    response = exc.response
    message = response.text
    block_code = None
    try:
        body = response.json()
        detail = body.get("detail") if isinstance(body, dict) else body
        if isinstance(detail, str):
            message = detail
        elif isinstance(detail, dict):
            message = str(detail.get("message") or detail)
            block_code = detail.get("block_code")
        elif detail is not None:
            message = str(detail)
    except ValueError:
        pass
    error = {
        "code": "deck_http_error",
        "status_code": response.status_code,
        "message": message,
    }
    if block_code:
        error["block_code"] = block_code
    return {
        "ok": False,
        "error": error,
    }


def _deck_request(method: str, api_prefix: str, path: str, **kwargs) -> dict:
    now = time.monotonic()
    if now < _state.get("offline_until", 0.0):
        return _unreachable_result(_state.get("last_error") or "Claude Deck is unavailable.")
    normalized_path = path if path.startswith("/") else f"/{path}"
    url = f"{DECK_API}/{api_prefix.strip('/')}{normalized_path}"
    try:
        response = httpx.request(method, url, timeout=DECK_HTTP_TIMEOUT, **kwargs)
        response.raise_for_status()
        _state["offline_until"] = 0.0
        _state["last_error"] = None
        return {"ok": True, "data": response.json()}
    except httpx.HTTPStatusError as exc:
        _state["offline_until"] = 0.0
        _state["last_error"] = None
        return _http_error_result(exc)
    except httpx.HTTPError as exc:
        _state["offline_until"] = time.monotonic() + OFFLINE_BACKOFF_SECONDS
        _state["last_error"] = str(exc)
        return _unreachable_result(str(exc))


def _request(method: str, path: str, **kwargs) -> dict:
    return _deck_request(method, "agent-mail", path, **kwargs)


def _team_request(method: str, path: str, **kwargs) -> dict:
    return _deck_request(method, "agent-teams", path, **kwargs)


def _bridge_request(method: str, path: str, **kwargs) -> dict:
    return _deck_request(method, "agent-bridge", path, **kwargs)


def _bridge_request_with_token(method: str, path: str, **kwargs) -> dict:
    token_result = _bridge_request("GET", "/token")
    if not token_result["ok"]:
        return token_result
    token = token_result["data"].get("token")
    if not token:
        return {
            "ok": False,
            "error": {
                "code": "missing_terminal_token",
                "message": "Claude Deck did not return an Agent Bridge terminal token.",
            },
        }
    headers = dict(kwargs.pop("headers", {}) or {})
    headers["X-Claude-Deck-Terminal-Token"] = token
    return _bridge_request(method, path, headers=headers, **kwargs)


def _bridge_session_path(target: str) -> str:
    return f"/sessions/{quote(target, safe='')}"


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


@mcp.tool()
def deck_attach_image_to_bridge_session(
    target: str,
    file_path: str,
    submit: bool = False,
    prompt: str = "",
) -> dict:
    """Upload a local image file to an Agent Bridge tmux session, paste the
    generated image-path prompt, and optionally submit it. target is the
    tmux target from Agent Bridge, such as "repo-1234:0.0". file_path must
    point to an image readable by this trusted MCP server process."""
    expanded_path = os.path.abspath(os.path.expanduser(file_path))
    if not os.path.isfile(expanded_path):
        return {
            "ok": False,
            "error": {
                "code": "image_file_not_found",
                "message": f"Image file not found: {expanded_path}",
            },
        }

    data = {"created_by": "mcp"}
    if prompt:
        data["prompt"] = prompt
    with open(expanded_path, "rb") as handle:
        upload = _bridge_request_with_token(
            "POST",
            f"{_bridge_session_path(target)}/attachments",
            files={"file": (os.path.basename(expanded_path), handle)},
            data=data,
        )
    if not upload["ok"]:
        return upload

    attachment = upload["data"]
    paste = _bridge_request_with_token(
        "POST",
        f"{_bridge_session_path(target)}/attachments/{attachment['id']}/paste",
        json={"submit": submit},
    )
    if not paste["ok"]:
        return {"ok": False, "attachment": attachment, "error": paste["error"]}
    return {"ok": True, "attachment": attachment, "paste": paste["data"]}


@mcp.tool()
def deck_list_bridge_attachments(target: str) -> dict:
    """List recent image attachments for an Agent Bridge tmux target."""
    result = _bridge_request_with_token("GET", f"{_bridge_session_path(target)}/attachments")
    if not result["ok"]:
        return result
    return {"ok": True, **result["data"]}


@mcp.tool()
def deck_paste_bridge_attachment(
    target: str,
    attachment_id: int,
    submit: bool = False,
) -> dict:
    """Paste an existing Agent Bridge attachment prompt into a tmux session,
    optionally submitting it with Enter."""
    result = _bridge_request_with_token(
        "POST",
        f"{_bridge_session_path(target)}/attachments/{attachment_id}/paste",
        json={"submit": submit},
    )
    if not result["ok"]:
        return result
    return {"ok": True, "paste": result["data"]}


@mcp.tool()
def deck_list_teams() -> dict:
    """List saved Claude Deck Agent Team presets. Returns preset ids, names,
    descriptions, and slots with launch options and validation warnings."""
    result = _team_request("GET", "/presets")
    if not result["ok"]:
        return result
    return {"ok": True, **result["data"]}


@mcp.tool()
def deck_create_team(
    name: str,
    description: str = "",
    slots: Optional[list[dict[str, Any]]] = None,
) -> dict:
    """Create an Agent Team preset.

    Valid providers: claude-code, codex-cli, copilot-cli, opencode-cli.
    Common slot fields: display_name, provider, repo_path, role, charter,
    ui_color, launch_mode, launch_options. ui_color values: blue, purple,
    green, amber, red, cyan, slate. Provider launch modes/options:
    - claude-code: modes plain/worktree/resume; launch_options
      skip_permissions, platform, aws_region, aws_profile, bedrock_model,
      prompt, session_id, project_folder, worktree_name.
    - codex-cli: modes plain/resume/fork; launch_options model, profile,
      profile_v2, sandbox, approval_policy, search, no_alt_screen,
      dangerously_bypass_approvals_and_sandbox, use_last, session_id,
      platform, aws_region, aws_profile, bedrock_model, reasoning_effort,
      prompt. reasoning_effort: low/medium/high/xhigh.
    - copilot-cli: modes plain/resume; launch_options model, agent,
      context_tier, reasoning_effort, plan, remote, allow_all, no_ask_user,
      skip_permissions, dangerously_bypass_approvals_and_sandbox, use_last,
      session_id, prompt. reasoning_effort: none/low/medium/high/xhigh/max;
      context_tier: default/long_context. Bedrock launch options are not
      supported for copilot-cli.
    - opencode-cli: modes plain/resume; launch_options model, agent,
      use_last, session_id, platform, aws_region, aws_profile, prompt.
      OpenCode TUI launch does not support reasoning_effort.
    Use deck_plan_team_launch before launch.
    """
    payload = {
        "name": name,
        "description": description or None,
        "created_by": "mcp",
        "slots": slots or [],
    }
    result = _team_request("POST", "/presets", json=payload)
    if not result["ok"]:
        return result
    return {"ok": True, "preset": result["data"]}


@mcp.tool()
def deck_plan_team_launch(
    preset_id: int,
    reuse_existing: bool = True,
    slot_ids: Optional[list[int]] = None,
    include_disabled: bool = False,
) -> dict:
    """Plan an Agent Team launch and return the plan_hash required by
    deck_launch_team. Review blocked items and warnings before launching."""
    payload = {
        "reuse_existing": reuse_existing,
        "slot_ids": slot_ids,
        "include_disabled": include_disabled,
    }
    result = _team_request("POST", f"/presets/{preset_id}/plan-launch", json=payload)
    if not result["ok"]:
        return result
    return {"ok": True, "plan": result["data"]}


@mcp.tool()
def deck_launch_team(
    preset_id: int,
    confirm_plan_hash: str = "",
    reuse_existing: bool = True,
    slot_ids: Optional[list[int]] = None,
    force_without_plan: bool = False,
) -> dict:
    """Launch an Agent Team preset.

    Call deck_plan_team_launch first and pass its plan_hash as
    confirm_plan_hash. force_without_plan bypasses that safety check only when
    explicitly set true. Launch behavior uses the per-provider launch_options
    accepted by deck_create_team; validation errors include machine-readable
    block_code values when available.
    """
    if not confirm_plan_hash and not force_without_plan:
        return {
            "ok": False,
            "error": {
                "code": "plan_hash_required",
                "message": "Call deck_plan_team_launch first and pass confirm_plan_hash.",
            },
        }
    payload = {
        "requested_by": "mcp",
        "reuse_existing": reuse_existing,
        "slot_ids": slot_ids,
        "confirm_plan_hash": confirm_plan_hash or None,
        "skip_plan_confirmation": force_without_plan,
    }
    result = _team_request("POST", f"/presets/{preset_id}/launch", json=payload)
    if not result["ok"]:
        return result
    return {"ok": True, "launch": result["data"]}


if __name__ == "__main__":
    _start_heartbeat_thread()
    mcp.run()
