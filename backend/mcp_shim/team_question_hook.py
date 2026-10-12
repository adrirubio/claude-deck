"""Refuse interactive questions in unattended Deck team sessions."""
import json
import os
import sys


def main() -> int:
    marker = os.environ.get("CLAUDE_DECK_TEAM_SLOT_ID", "")
    if not marker.isascii() or not marker.isdecimal() or int(marker) <= 0:
        return 0
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        payload = {}
    if isinstance(payload, dict) and payload.get("tool_name") not in {None, "AskUserQuestion"}:
        return 0
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            "Deck team sessions cannot use interactive question prompts. "
            "Use Agent Mail. Ask the Leader about assignments, plans, and sequencing. "
            "Ask the Supervisor about incidents, gates, harnesses, workspaces, and stalls. "
            "Use an operator action record for a retained operator decision. "
            "Continue other authorized work while you wait."
        ),
    }}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
