"""Codex app-server client behavior for Agent Mail wakeups."""
from types import SimpleNamespace

from app.services.codex_app_server_service import CodexAppServerService, CodexAppServerStatus


def test_choose_thread_prefers_idle_then_recent_not_loaded():
    svc = CodexAppServerService()

    chosen = svc._choose_thread(
        [
            {"id": "active", "status": {"type": "active"}, "updatedAt": 30},
            {"id": "old-idle", "status": {"type": "idle"}, "updatedAt": 10},
            {"id": "new-not-loaded", "status": {"type": "notLoaded"}, "updatedAt": 40},
            {"id": "new-idle", "status": {"type": "idle"}, "updatedAt": 20},
        ]
    )

    assert chosen["id"] == "new-idle"


def test_wake_repo_resumes_existing_thread(monkeypatch):
    svc = CodexAppServerService()
    calls = []

    monkeypatch.setattr(svc, "is_running", lambda: True)

    def fake_request(method, params, timeout):
        calls.append((method, params))
        if method == "thread/list":
            return {"data": [{"id": "thr_1", "status": {"type": "notLoaded"}, "updatedAt": 1}]}
        if method == "thread/resume":
            return {"thread": {"id": "thr_1"}}
        if method == "turn/start":
            return {"turn": {"id": "turn_1"}}
        raise AssertionError(method)

    monkeypatch.setattr(svc, "_request", fake_request)

    result = svc.wake_repo("/repo", "check inbox")

    assert result.ok is True
    assert result.thread_id == "thr_1"
    assert result.turn_id == "turn_1"
    assert result.resumed_thread is True
    assert calls == [
        ("thread/list", {"cwd": "/repo", "limit": 10, "archived": False}),
        ("thread/resume", {"threadId": "thr_1", "cwd": "/repo"}),
        (
            "turn/start",
            {
                "threadId": "thr_1",
                "cwd": "/repo",
                "input": [{"type": "text", "text": "check inbox"}],
            },
        ),
    ]


def test_wake_repo_starts_thread_when_none_exists(monkeypatch):
    svc = CodexAppServerService()
    calls = []

    monkeypatch.setattr(svc, "is_running", lambda: True)

    def fake_request(method, params, timeout):
        calls.append((method, params))
        if method == "thread/list":
            return {"data": []}
        if method == "thread/start":
            return {"thread": {"id": "thr_new"}}
        if method == "turn/start":
            return {"turn": {"id": "turn_new"}}
        raise AssertionError(method)

    monkeypatch.setattr(svc, "_request", fake_request)

    result = svc.wake_repo("/repo", "check inbox")

    assert result.ok is True
    assert result.created_thread is True
    assert ("thread/start", {"cwd": "/repo"}) in calls


def test_start_is_idempotent_when_process_is_already_running(monkeypatch):
    svc = CodexAppServerService()
    svc._proc = SimpleNamespace(poll=lambda: None)

    def fail_popen(*args, **kwargs):
        raise AssertionError("start should not launch a second app-server process")

    monkeypatch.setattr("app.services.codex_app_server_service.subprocess.Popen", fail_popen)
    monkeypatch.setattr(
        svc,
        "status",
        lambda: CodexAppServerStatus(
            codex_cli_available=True,
            app_server_available=True,
            app_server_running=True,
            remote_control_running=False,
        ),
    )

    status = svc.start()

    assert status.app_server_running is True


def test_stop_is_idempotent_when_process_is_not_running(monkeypatch):
    svc = CodexAppServerService()
    monkeypatch.setattr(svc, "_codex_binary", lambda: "/usr/bin/codex")
    monkeypatch.setattr(svc, "_remote_control_status", lambda codex_binary: (False, None))

    status = svc.stop()

    assert status.app_server_running is False
    assert status.app_server_error is None


def test_status_reports_remote_control_error(monkeypatch):
    svc = CodexAppServerService()

    monkeypatch.setattr(svc, "_codex_binary", lambda: "/usr/bin/codex")
    monkeypatch.setattr(svc, "is_running", lambda: False)
    monkeypatch.setattr(
        "app.services.codex_app_server_service.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="managed standalone Codex install not found",
        ),
    )

    status = svc.status()

    assert status.codex_cli_available is True
    assert status.app_server_available is True
    assert status.app_server_running is False
    assert status.remote_control_running is False
    assert "standalone Codex" in status.remote_control_error
