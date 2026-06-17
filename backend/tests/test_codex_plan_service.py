"""Tests for Codex update_plan snapshot extraction."""

import json
import sqlite3
from pathlib import Path

import pytest


def _write_state_db(codex_home: Path, *, thread_id: str, rollout_path: Path, cwd: Path) -> None:
    codex_home.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(codex_home / "state_5.sqlite")
    try:
        conn.execute(
            """
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                rollout_path TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                cwd TEXT NOT NULL,
                git_branch TEXT,
                git_sha TEXT,
                title TEXT NOT NULL,
                first_user_message TEXT NOT NULL,
                preview TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO threads (
                id, rollout_path, created_at, updated_at, cwd, git_branch, git_sha,
                title, first_user_message, preview
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                thread_id,
                str(rollout_path),
                1_779_000_000,
                1_779_000_100,
                str(cwd),
                "main",
                "abc123",
                "TITLE_PROMPT_SENTINEL",
                "FIRST_USER_PROMPT_SENTINEL",
                "PREVIEW_PROMPT_SENTINEL",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _write_rollout(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_codex_plan_snapshots_omit_prompt_like_fields(tmp_path):
    from app.services.codex_plan_service import CodexPlanService

    codex_home = tmp_path / ".codex"
    project = tmp_path / "repo"
    project.mkdir()
    rollout = codex_home / "sessions" / "2026" / "06" / "16" / "rollout-test.jsonl"
    _write_state_db(codex_home, thread_id="thread-a", rollout_path=rollout, cwd=project)
    _write_rollout(
        rollout,
        [
            {
                "type": "session_meta",
                "timestamp": "2026-06-16T10:00:00Z",
                "payload": {
                    "id": "thread-a",
                    "cwd": str(project),
                    "base_instructions": "BASE_INSTRUCTIONS_SENTINEL",
                },
            },
            {
                "type": "response_item",
                "timestamp": "2026-06-16T10:01:00Z",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "RAW_PROMPT_SENTINEL"}],
                },
            },
            {
                "type": "response_item",
                "timestamp": "2026-06-16T10:02:00Z",
                "payload": {
                    "type": "function_call",
                    "name": "update_plan",
                    "arguments": json.dumps(
                        {
                            "explanation": "Tracking the implementation safely",
                            "plan": [
                                {"step": "Inspect plan API", "status": "completed"},
                                {"step": "Parse Codex snapshots", "status": "in_progress"},
                                {"step": "Verify privacy boundary", "status": "pending"},
                            ],
                        }
                    ),
                    "call_id": "call-1",
                },
            },
        ],
    )

    service = CodexPlanService(codex_home=codex_home)
    plans = service.list_plans(str(project))

    assert len(plans) == 1
    assert plans[0]["source"] == "codex-cli"
    assert plans[0]["step_count"] == 3
    assert plans[0]["completed_count"] == 1
    assert plans[0]["in_progress_count"] == 1
    assert plans[0]["pending_count"] == 1
    assert "Parse Codex snapshots" in plans[0]["excerpt"]

    detail = service.get_plan(plans[0]["filename"], str(project))
    serialized = json.dumps({"plans": plans, "detail": detail})
    assert detail is not None
    assert "Inspect plan API" in detail["content"]
    assert "RAW_PROMPT_SENTINEL" not in serialized
    assert "BASE_INSTRUCTIONS_SENTINEL" not in serialized
    assert "TITLE_PROMPT_SENTINEL" not in serialized
    assert "FIRST_USER_PROMPT_SENTINEL" not in serialized
    assert "PREVIEW_PROMPT_SENTINEL" not in serialized


def test_codex_plan_uses_latest_snapshot_and_project_filter(tmp_path):
    from app.services.codex_plan_service import CodexPlanService

    codex_home = tmp_path / ".codex"
    project = tmp_path / "repo"
    other_project = tmp_path / "other"
    project.mkdir()
    other_project.mkdir()
    rollout = codex_home / "sessions" / "2026" / "06" / "16" / "rollout-test.jsonl"
    _write_state_db(codex_home, thread_id="thread-a", rollout_path=rollout, cwd=project)
    _write_rollout(
        rollout,
        [
            {
                "type": "response_item",
                "timestamp": "2026-06-16T10:00:00Z",
                "payload": {
                    "type": "function_call",
                    "name": "update_plan",
                    "arguments": json.dumps(
                        {"plan": [{"step": "Old active step", "status": "in_progress"}]}
                    ),
                },
            },
            {
                "type": "response_item",
                "timestamp": "2026-06-16T10:05:00Z",
                "payload": {
                    "type": "function_call",
                    "name": "update_plan",
                    "arguments": json.dumps(
                        {
                            "plan": [
                                {"step": "Old active step", "status": "completed"},
                                {"step": "New active step", "status": "in_progress"},
                            ]
                        }
                    ),
                },
            },
        ],
    )

    service = CodexPlanService(codex_home=codex_home)

    assert service.list_plans(str(other_project)) == []
    plans = service.list_plans(str(project))
    assert len(plans) == 1
    assert plans[0]["modified_at"] == "2026-06-16T10:05:00Z"
    assert plans[0]["title"] == "repo - New active step"


def test_codex_plan_search_finds_non_active_plan_steps(tmp_path):
    from app.services.codex_plan_service import CodexPlanService

    codex_home = tmp_path / ".codex"
    project = tmp_path / "repo"
    project.mkdir()
    rollout = codex_home / "sessions" / "2026" / "06" / "16" / "rollout-test.jsonl"
    _write_state_db(codex_home, thread_id="thread-a", rollout_path=rollout, cwd=project)
    _write_rollout(
        rollout,
        [
            {
                "type": "response_item",
                "timestamp": "2026-06-16T10:00:00Z",
                "payload": {
                    "type": "function_call",
                    "name": "update_plan",
                    "arguments": json.dumps(
                        {
                            "plan": [
                                {"step": "Active visible step", "status": "in_progress"},
                                {"step": "Hidden pending searchable step", "status": "pending"},
                            ]
                        }
                    ),
                },
            }
        ],
    )

    results = CodexPlanService(codex_home=codex_home).search_plans("searchable", str(project))

    assert len(results) == 1
    assert "Hidden pending searchable step" in results[0]["matches"][0]


@pytest.mark.asyncio
async def test_plan_api_dispatches_codex_provider(monkeypatch, tmp_path):
    from app.api.v1 import plans as plans_api
    from app.services.codex_plan_service import CodexPlanService

    codex_home = tmp_path / ".codex"
    project = tmp_path / "repo"
    project.mkdir()
    rollout = codex_home / "sessions" / "2026" / "06" / "16" / "rollout-test.jsonl"
    _write_state_db(codex_home, thread_id="thread-a", rollout_path=rollout, cwd=project)
    _write_rollout(
        rollout,
        [
            {
                "type": "response_item",
                "timestamp": "2026-06-16T10:00:00Z",
                "payload": {
                    "type": "function_call",
                    "name": "update_plan",
                    "arguments": json.dumps(
                        {"plan": [{"step": "Expose Codex plans", "status": "in_progress"}]}
                    ),
                },
            }
        ],
    )
    monkeypatch.setattr(
        plans_api,
        "CodexPlanService",
        lambda: CodexPlanService(codex_home=codex_home),
    )

    response = await plans_api.list_plans(project_path=str(project), provider="codex-cli")

    assert response["total"] == 1
    assert response["plans"][0]["source"] == "codex-cli"


@pytest.mark.asyncio
async def test_plan_api_rejects_unknown_provider():
    from app.api.v1 import plans as plans_api

    with pytest.raises(plans_api.HTTPException) as exc_info:
        await plans_api.list_plans(project_path=None, provider="missing-provider")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "unsupported_provider_operation"


def test_claude_plan_empty_state_still_works(tmp_path):
    from app.services.plan_service import PlanService

    assert PlanService.list_plans(tmp_path) == []
    assert PlanService.get_plan_stats(tmp_path)["total_plans"] == 0
