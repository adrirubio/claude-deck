#!/usr/bin/env python3
"""A local stub model provider for the isolated runtime kit (#902).

It speaks just enough of the OpenAI-compatible chat API for a provider CLI's
live check: `GET /v1/models` and `POST /v1/chat/completions` (plain or
`stream: true`). Every reply is the same fixed text, unless `--script` names a
JSON list of turns (#912): each turn is `{"text": ...}` or
`{"tool_call": {"name": ..., "arguments": {...}}}`, served in order, one per chat
completion, and the fixed text resumes after the last one. A malformed script is
refused before the server binds. It listens on 127.0.0.1 only, inside the kit's
loopback-only network namespace, and never forwards anything.

The request log keeps the time, the path, the model name and a SHA-256 of the
request body; with a script, also the turn index and the reply kind. It never
keeps prompt or argument text.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPLY = "stub reply from the isolated runtime kit"
MAX_BODY = 4 << 20
MAX_SCRIPT_BYTES = 64 << 10
MAX_TURNS = 64


class ScriptError(ValueError):
    """A script the stub refuses before it serves anything."""


def _valid_turn(turn) -> bool:
    if not isinstance(turn, dict) or len(turn) != 1:
        return False
    if "text" in turn:
        return isinstance(turn["text"], str)
    call = turn.get("tool_call")
    return (isinstance(call, dict) and set(call) == {"name", "arguments"} and isinstance(call["name"], str)
            and call["name"] != "" and isinstance(call["arguments"], dict))


def _refuse_constant(name: str):
    raise ScriptError(f"the script holds a non-finite number ({name})")


def load_script(path: Path | str) -> list[dict]:
    """Read and check a script: 1 to 64 turns, at most 64 KiB, each exactly one known kind."""
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise ScriptError(f"the script can't be read: {exc.strerror}") from exc
    if len(raw) > MAX_SCRIPT_BYTES:
        raise ScriptError("the script is larger than 64 KiB")
    try:
        turns = json.loads(raw, parse_constant=_refuse_constant)
    except RecursionError as exc:  # the decoder's own depth limit; the limit itself is unchanged
        raise ScriptError("the script's nesting is too deep") from exc
    except ScriptError:
        raise
    except ValueError as exc:
        raise ScriptError("the script is not JSON") from exc
    if not isinstance(turns, list) or not 1 <= len(turns) <= MAX_TURNS:
        raise ScriptError(f"the script must be a list of 1 to {MAX_TURNS} turns")
    for index, turn in enumerate(turns):
        if not _valid_turn(turn):
            raise ScriptError(f'turn {index} is not {{"text": str}} or {{"tool_call": {{"name": str, "arguments": object}}}}')
    return turns


class Handler(BaseHTTPRequestHandler):
    log_path: Path
    model = "stub-model"
    script: list[dict] | None = None
    served = [0]
    lock = threading.Lock()

    def log_message(self, *args):  # no access log on stderr
        return

    def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _next_turn(self) -> tuple[int | None, dict | None]:
        with self.lock:
            index = self.served[0]
            if index < len(self.script):
                self.served[0] += 1
                return index, self.script[index]
        return None, None

    def _record(self, body: bytes, model: str | None, scripted: tuple[int | None, str] | None = None) -> None:
        entry = {"time": time.time(), "path": self.path, "model": model,
                 "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
        if scripted is not None:
            entry["turn"], entry["kind"] = scripted
        with self.log_path.open("a") as log:
            log.write(json.dumps(entry) + "\n")

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self._send(200, b'{"ok": true}')
        elif self.path == "/v1/models":
            self._send(200, json.dumps({"object": "list", "data": [{"id": self.model, "object": "model"}]}).encode())
        else:
            self._send(404, b'{"error": "not found"}')

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self._send(413, b'{"error": "too large"}')
            return
        body = self.rfile.read(length)
        try:
            request = json.loads(body or b"{}")
        except ValueError:
            request = {}
        model = request.get("model") if isinstance(request, dict) else None
        chat = self.path in ("/v1/chat/completions", "/chat/completions")
        index, turn = self._next_turn() if chat and self.script is not None else (None, None)
        scripted = None
        if chat and self.script is not None:
            scripted = (index, next(iter(turn)) if turn is not None else "fallback")
        self._record(body, model if isinstance(model, str) else None, scripted)
        if not chat:
            self._send(404, b'{"error": "not found"}')
            return
        text, call = REPLY, None
        if turn is not None:
            if "tool_call" in turn:
                call = {"id": f"call_stub_{index}", "type": "function",
                        "function": {"name": turn["tool_call"]["name"],
                                     "arguments": json.dumps(turn["tool_call"]["arguments"], allow_nan=False)}}
            else:
                text = turn.get("text", REPLY)
        finish = "tool_calls" if call else "stop"
        created = int(time.time())
        if isinstance(request, dict) and request.get("stream"):
            deltas = ([{"role": "assistant"}, {"tool_calls": [dict(call, index=0)]}] if call
                      else [{"role": "assistant", "content": text}])
            chunks = [{"id": "stub", "object": "chat.completion.chunk", "created": created, "model": model or self.model,
                       "choices": [{"index": 0, "delta": delta, "finish_reason": None}]} for delta in deltas]
            chunks.append({"id": "stub", "object": "chat.completion.chunk", "created": created,
                           "model": model or self.model, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]})
            data = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
            self._send(200, data.encode(), "text/event-stream")
            return
        message = {"role": "assistant", "content": None, "tool_calls": [call]} if call else {
            "role": "assistant", "content": text}
        reply = {"id": "stub", "object": "chat.completion", "created": created, "model": model or self.model,
                 "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                 "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
        self._send(200, json.dumps(reply).encode())


def make_server(port: int, log_path: Path, script: list[dict] | None = None) -> ThreadingHTTPServer:
    """A server on 127.0.0.1 with its own script position, so each server serves its script once."""
    handler = type("StubHandler", (Handler,), {"log_path": log_path, "script": script, "served": [0],
                                               "lock": threading.Lock()})
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--script", type=Path)
    args = parser.parse_args(argv)
    script = None
    if args.script is not None:
        try:
            script = load_script(args.script)
        except ScriptError as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
    args.log.touch()
    server = make_server(args.port, args.log, script)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
