"""Claude Deck Agent Mail lifecycle hook shim."""
import argparse
import json
import os
import sys
from typing import Any

import httpx

HTTP_TIMEOUT = httpx.Timeout(connect=0.25, read=1.0, write=1.0, pool=0.25)


def _read_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _session_id(payload: dict[str, Any]) -> str:
    for key in ("session_id", "sessionId", "thread_id", "threadId", "conversation_id", "conversationId"):
        value = payload.get(key)
        if value:
            return str(value)
    return str(os.getppid())


def _write_hook_output(body: dict[str, Any]) -> None:
    if not body:
        return
    print(json.dumps(body, separators=(",", ":")))


def _provider_hook_output(provider: str, body: dict[str, Any]) -> dict[str, Any]:
    if provider != "copilot-cli":
        return body
    hook_output = body.get("hookSpecificOutput")
    if not isinstance(hook_output, dict):
        return body
    context = hook_output.get("additionalContext")
    if not context:
        return {}
    return {"additionalContext": context}


def _env_int(name: str) -> int | None:
    value = os.environ.get(name)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deck-url", default=os.environ.get("CLAUDE_DECK_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--event", required=True)
    parser.add_argument("--provider", default=os.environ.get("CLAUDE_DECK_PROVIDER", "codex-cli"))
    args = parser.parse_args()

    payload = _read_payload()
    payload.setdefault("cwd", os.getcwd())
    payload["provider"] = args.provider
    payload["session_id"] = _session_id(payload)
    payload["pid"] = os.getppid()
    team_preset_id = _env_int("CLAUDE_DECK_TEAM_PRESET_ID")
    team_slot_id = _env_int("CLAUDE_DECK_TEAM_SLOT_ID")
    if team_preset_id is not None:
        payload["team_preset_id"] = team_preset_id
    if team_slot_id is not None:
        payload["team_slot_id"] = team_slot_id

    try:
        response = httpx.post(
            f"{args.deck_url.rstrip('/')}/api/v1/agent-mail/hooks/{args.event}",
            json=payload,
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        body = response.json()
    except Exception:
        return 0

    _write_hook_output(_provider_hook_output(args.provider, body))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
