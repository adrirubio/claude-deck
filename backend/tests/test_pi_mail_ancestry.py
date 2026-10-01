import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.utils import peer_process


def test_actual_pi_shim_kernel_ancestry_and_reload_on_disposable_socket(tmp_path, monkeypatch):
    pi = shutil.which("pi")
    tmux = shutil.which("tmux")
    root = Path(__file__).resolve().parents[2]
    extension = root / "integrations/pi-agent-mail/extension.ts"
    if not pi or not tmux or not (extension.parent / "node_modules").exists():
        pytest.skip("Installed Pi, tmux and local integration dependencies are required")
    socket = f"deck-pi-fixture-{uuid.uuid4().hex}"
    registrations = []
    closures = []
    resolutions = []

    def fixture_tmux(*args):
        result = subprocess.run([tmux, "-L", socket, *args], capture_output=True, text=True, timeout=5)
        return result.stdout if result.returncode == 0 else None
    monkeypatch.setattr(peer_process, "_run_tmux", fixture_tmux)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, data):
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
            if self.path.endswith("/agent/register"):
                resolution = peer_process.resolve_peer_pane_detailed(self.client_address[0], self.client_address[1], local_port=self.server.server_port)
                resolutions.append(resolution)
                registrations.append(body)
                self.respond({"member": {"id": 1}, "capability_token": "synthetic-capability"})
            elif self.path.endswith("/agent/close"):
                closures.append(self.headers.get("X-Deck-Session-Token") == "synthetic-capability")
                self.respond({"closed": True})
            else:
                self.send_error(404)

        def do_GET(self):
            if "/team" in self.path:
                self.respond({"members": [{"id": 1, "display_name": "Fixture", "sessions": []}]})
            else:
                self.respond({"unread_count": 0, "pending_count": 0, "messages": []})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    environment = {
        "PATH": os.environ["PATH"], "HOME": str(tmp_path), "SHELL": "/bin/sh",
        "PI_CODING_AGENT_DIR": str(tmp_path / "pi-agent"),
        "XDG_RUNTIME_DIR": str(tmp_path),
        "CLAUDE_DECK_MAIL_OPT_IN": "1", "CLAUDE_DECK_PROVIDER": "pi-cli",
        "CLAUDE_DECK_MAIL_PYTHON": sys.executable,
        "CLAUDE_DECK_MAIL_SHIM": str(root / "backend/mcp_shim/agent_mail_server.py"),
        "CLAUDE_DECK_URL": f"http://127.0.0.1:{server.server_port}",
    }
    command = shlex.join([pi, "--mode", "rpc", "--no-session", "--no-extensions", "--no-skills", "--provider", "openrouter", "--model", "moonshotai/kimi-k3", "--extension", str(extension)])
    def wait_for(predicate):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.1)
        raise AssertionError("Disposable Pi fixture did not reach its expected lifecycle state")

    try:
        subprocess.run([tmux, "-L", socket, "-f", "/dev/null", "new-session", "-d", "-s", "fixture", "-c", str(tmp_path), command], env=environment, check=True, capture_output=True)
        wait_for(lambda: len(registrations) >= 1 and any(resolution.pane is not None for resolution in resolutions))
        subprocess.run([tmux, "-L", socket, "send-keys", "-t", "fixture:0.0", "-l", '{"type":"new_session"}'], check=True, capture_output=True)
        subprocess.run([tmux, "-L", socket, "send-keys", "-t", "fixture:0.0", "Enter"], check=True, capture_output=True)
        wait_for(lambda: len(closures) >= 1 and len({entry["session_key"] for entry in registrations}) >= 2)
        assert all(closures)
        assert all(entry["provider"] == "pi-cli" for entry in registrations)
        assert all(resolution.pane is not None for resolution in resolutions)
        assert max(len(resolution.walked_pids) for resolution in resolutions) <= 32
        assert len({(resolution.pane.pane_pid, resolution.pane.pane_proc_start) for resolution in resolutions}) == 1
    finally:
        subprocess.run([tmux, "-L", socket, "kill-server"], capture_output=True)
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
