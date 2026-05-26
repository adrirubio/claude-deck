"""Tests for read-only Codex history and model cache diagnostics."""

import json


def test_codex_history_diagnostics_omit_history_text_and_summarize_sessions(tmp_path):
    from app.services.codex_history_service import CodexHistoryService

    text_sentinel = "TEXT_FIELD_SENTINEL_SHOULD_NOT_RETURN"
    rows = [
        {"session_id": "session-a", "ts": 100, "text": text_sentinel},
        {"session_id": "session-a", "ts": 110, "text": "TEXT_FIELD_SENTINEL_TWO"},
        {"session_id": "session-b", "ts": 120, "text": "TEXT_FIELD_SENTINEL_THREE"},
    ]
    (tmp_path / "history.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "models_cache.json").write_text(
        json.dumps({
            "fetched_at": "2026-05-26T12:00:00Z",
            "etag": "opaque-cache-validator",
            "client_version": "0.133.0",
            "models": [{"id": "gpt-5"}],
        }),
        encoding="utf-8",
    )

    diagnostics = CodexHistoryService(codex_home=tmp_path).get_diagnostics()
    serialized = json.dumps(diagnostics)

    assert diagnostics["decision"]["surface"] == "diagnostics_only"
    assert diagnostics["history"]["valid_rows"] == 3
    assert diagnostics["history"]["unique_session_count"] == 2
    assert diagnostics["history"]["first_ts"] == 100
    assert diagnostics["history"]["last_ts"] == 120
    assert diagnostics["history"]["sensitive_fields_omitted"] == ["text"]
    assert diagnostics["history"]["latest_session_summaries"][0]["session_id_hash"]
    assert "session-a" not in serialized
    assert text_sentinel not in serialized
    assert "TEXT_FIELD_SENTINEL_TWO" not in serialized
    assert diagnostics["models_cache"]["model_count"] == 1
    assert diagnostics["models_cache"]["etag_present"] is True
    assert "opaque-cache-validator" not in serialized
    assert "gpt-5" not in serialized


def test_codex_history_diagnostics_handle_missing_files(tmp_path):
    from app.services.codex_history_service import CodexHistoryService

    diagnostics = CodexHistoryService(codex_home=tmp_path).get_diagnostics()

    assert diagnostics["history"]["exists"] is False
    assert diagnostics["history"]["valid_rows"] == 0
    assert diagnostics["models_cache"]["exists"] is False
    assert diagnostics["models_cache"]["model_count"] is None


def test_codex_history_diagnostics_handle_malformed_files(tmp_path):
    from app.services.codex_history_service import CodexHistoryService

    (tmp_path / "history.jsonl").write_text(
        '{"session_id":"ok","ts":1,"text":"TEXT_FIELD_SENTINEL"}\n'
        "{not-json}\n"
        '["not", "object"]\n',
        encoding="utf-8",
    )
    (tmp_path / "models_cache.json").write_text("{not-json}", encoding="utf-8")

    diagnostics = CodexHistoryService(codex_home=tmp_path).get_diagnostics()

    assert diagnostics["history"]["valid_rows"] == 1
    assert diagnostics["history"]["invalid_rows"] == 2
    assert diagnostics["models_cache"]["parse_error"]


def test_codex_history_diagnostics_truncate_large_history_and_cache(tmp_path):
    from app.services.codex_history_service import CodexHistoryService

    rows = [
        {"session_id": f"session-{index}", "ts": index, "text": f"TEXT_FIELD_SENTINEL_{index}"}
        for index in range(5)
    ]
    (tmp_path / "history.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "models_cache.json").write_text(
        json.dumps({"models": [{"id": "model-a"}]}),
        encoding="utf-8",
    )

    diagnostics = CodexHistoryService(
        codex_home=tmp_path,
        max_history_rows=3,
        max_model_cache_bytes=5,
    ).get_diagnostics()
    serialized = json.dumps(diagnostics)

    assert diagnostics["history"]["rows_read"] == 3
    assert diagnostics["history"]["truncated"] is True
    assert diagnostics["models_cache"]["too_large"] is True
    assert diagnostics["models_cache"]["parse_error"] == "models_cache.json exceeds diagnostics read limit"
    assert "TEXT_FIELD_SENTINEL_4" not in serialized
    assert "model-a" not in serialized


def test_provider_history_diagnostics_endpoint_is_codex_only(monkeypatch, tmp_path):
    from app.api.v1 import providers as providers_api
    from app.services.codex_history_service import CodexHistoryService

    (tmp_path / "history.jsonl").write_text(
        json.dumps({"session_id": "session-a", "ts": 1, "text": "TEXT_FIELD_SENTINEL"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        providers_api,
        "CodexHistoryService",
        lambda: CodexHistoryService(codex_home=tmp_path),
    )

    response = providers_api.get_provider_history_diagnostics("codex-cli")

    assert response["provider"] == "codex-cli"
    assert response["provider_display_name"] == "Codex"
    assert response["history"]["valid_rows"] == 1

    try:
        providers_api.get_provider_history_diagnostics("claude-code")
    except providers_api.HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("Expected Claude Code history diagnostics to be rejected")
