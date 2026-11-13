#!/usr/bin/env python3
"""A local stub model provider for the isolated runtime kit (#902).

It speaks just enough of the OpenAI-compatible chat API for a provider CLI's
live check: `GET /v1/models` and `POST /v1/chat/completions` (plain or
`stream: true`). Every reply is the same scripted text. It listens on
127.0.0.1 only, inside the kit's loopback-only network namespace, and never
forwards anything.

The request log keeps the time, the path, the model name and a SHA-256 of the
request body. It never keeps prompt text.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPLY = "stub reply from the isolated runtime kit"
MAX_BODY = 4 << 20


class Handler(BaseHTTPRequestHandler):
    log_path: Path
    model = "stub-model"

    def log_message(self, *args):  # no access log on stderr
        return

    def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _record(self, body: bytes, model: str | None) -> None:
        entry = {"time": time.time(), "path": self.path, "model": model,
                 "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
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
        self._record(body, model if isinstance(model, str) else None)
        if self.path not in ("/v1/chat/completions", "/chat/completions"):
            self._send(404, b'{"error": "not found"}')
            return
        created = int(time.time())
        if isinstance(request, dict) and request.get("stream"):
            chunks = [
                {"id": "stub", "object": "chat.completion.chunk", "created": created, "model": model or self.model,
                 "choices": [{"index": 0, "delta": {"role": "assistant", "content": REPLY}, "finish_reason": None}]},
                {"id": "stub", "object": "chat.completion.chunk", "created": created, "model": model or self.model,
                 "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
            ]
            data = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
            self._send(200, data.encode(), "text/event-stream")
            return
        reply = {"id": "stub", "object": "chat.completion", "created": created, "model": model or self.model,
                 "choices": [{"index": 0, "message": {"role": "assistant", "content": REPLY}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
        self._send(200, json.dumps(reply).encode())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    Handler.log_path = args.log
    args.log.touch()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
