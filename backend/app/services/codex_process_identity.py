"""Recognize only the explicit resume command forms emitted by Deck."""
from pathlib import Path
import os
import uuid


def explicit_resume(argv: list[bytes], session_id: str) -> bool:
    if not argv or Path(os.fsdecode(argv[0])).name != "codex":
        return False
    try:
        if str(uuid.UUID(session_id)) != session_id:
            return False
    except (ValueError, TypeError, AttributeError):
        return False
    values = {b"--cd", b"--config", b"--model", b"--profile", b"--profile-v2",
              b"--sandbox", b"--ask-for-approval"}
    flags = {b"--search", b"--no-alt-screen", b"--dangerously-bypass-approvals-and-sandbox"}
    index = 1
    while index < len(argv):
        argument = argv[index]
        if argument in values:
            if index + 1 >= len(argv) or not argv[index + 1] or argv[index + 1].startswith(b"--"):
                return False
            index += 2
        elif argument in flags:
            index += 1
        else:
            break
    if argv[index:index + 2] != [b"resume", session_id.encode()]:
        return False
    # Deck emits at most one prompt after its explicit selector. Option text
    # after a delimiter cannot select a conversation. Unsupported forms refuse.
    tail = argv[index + 2:]
    if tail and tail[-1] == b"":
        tail = tail[:-1]
    return len(tail) <= 1 and (not tail or (tail[0] and not tail[0].startswith(b"-")))
