"""Tests for Codex usage/context diagnostics."""
from __future__ import annotations

import json

import pytest

from app.services.codex_usage_context_service import CodexUsageContextService


def test_diagnostics_omit_history_text_and_raw_model_cache(tmp_path):
    prompt_sentinel = "TEXT_FIELD_SENTINEL_SHOULD_NOT_RETURN"
    etag_sentinel = "OPAQUE_ETAG_SHOULD_NOT_RETURN"
    model_sentinel = "MODEL_SENTINEL_SHOULD_NOT_RETURN"
    (tmp_path / "history.jsonl").write_text(
        json.dumps(
            {
                "session_id": "session-1",
                "ts": "2026-05-26T10:00:00Z",
                "text": prompt_sentinel,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "models_cache.json").write_text(
        json.dumps(
            {
                "fetched_at": "2026-05-26T10:00:00Z",
                "etag": etag_sentinel,
                "client_version": "codex-cli 0.0.0",
                "models": [{"id": model_sentinel, "context_window": 200000}],
            }
        ),
        encoding="utf-8",
    )

    diagnostics = CodexUsageContextService(codex_home=tmp_path).get_diagnostics()
    serialized = json.dumps(diagnostics)

    assert diagnostics["decision"]["usage_status"] == "unsupported"
    assert diagnostics["decision"]["context_status"] == "unsupported"
    assert diagnostics["history"]["valid_rows"] == 1
    assert diagnostics["history"]["standard_fields_present"] == ["session_id", "text", "ts"]
    assert diagnostics["models_cache"]["model_count"] == 1
    assert diagnostics["models_cache"]["etag_present"] is True
    assert diagnostics["models_cache"]["metadata_fields_present"] == [
        "fetched_at",
        "etag",
        "client_version",
    ]
    assert prompt_sentinel not in serialized
    assert etag_sentinel not in serialized
    assert model_sentinel not in serialized


def test_diagnostics_detect_metric_like_keys_without_values(tmp_path):
    (tmp_path / "history.jsonl").write_text(
        json.dumps(
            {
                "session_id": "session-1",
                "ts": "2026-05-26T10:00:00Z",
                "text": "omitted",
                "input_tokens": 123,
                "context_window": 200000,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "models_cache.json").write_text(
        json.dumps({"models": [], "usage_hint": "not returned"}),
        encoding="utf-8",
    )

    diagnostics = CodexUsageContextService(codex_home=tmp_path).get_diagnostics()

    assert diagnostics["history"]["metric_fields_present"] == ["context_window", "input_tokens"]
    assert diagnostics["models_cache"]["metric_fields_present"] == ["usage_hint"]
    assert diagnostics["metric_findings"]["metric_fields_present"] == [
        "context_window",
        "input_tokens",
        "usage_hint",
    ]
    assert diagnostics["metric_findings"]["token_metrics_present"] is True
    assert diagnostics["metric_findings"]["context_metrics_present"] is True
    assert diagnostics["metric_findings"]["stable_usage_surface"] is False


def test_diagnostics_handle_missing_and_malformed_files(tmp_path):
    service = CodexUsageContextService(codex_home=tmp_path)
    missing = service.get_diagnostics()

    assert missing["history"]["exists"] is False
    assert missing["models_cache"]["exists"] is False

    (tmp_path / "history.jsonl").write_text("{not-json\n", encoding="utf-8")
    (tmp_path / "models_cache.json").write_text("{not-json", encoding="utf-8")

    malformed = service.get_diagnostics()

    assert malformed["history"]["rows_read"] == 1
    assert malformed["history"]["invalid_rows"] == 1
    assert malformed["models_cache"]["parse_error"] == "invalid_json"


def test_diagnostics_limit_history_and_large_cache(tmp_path):
    (tmp_path / "history.jsonl").write_text(
        "\n".join(
            json.dumps(
                {
                    "session_id": f"session-{index}",
                    "ts": "2026-05-26T10:00:00Z",
                    "text": "omitted",
                }
            )
            for index in range(3)
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "models_cache.json").write_text("123456", encoding="utf-8")

    diagnostics = CodexUsageContextService(
        codex_home=tmp_path,
        max_history_rows=2,
        max_models_cache_bytes=5,
    ).get_diagnostics()

    assert diagnostics["history"]["rows_read"] == 2
    assert diagnostics["history"]["truncated"] is True
    assert diagnostics["models_cache"]["too_large"] is True
    assert diagnostics["models_cache"]["raw_payload_omitted"] is True


def test_diagnostics_include_sqlite_metadata_only(tmp_path):
    (tmp_path / "logs.sqlite").write_text("opaque", encoding="utf-8")

    diagnostics = CodexUsageContextService(codex_home=tmp_path).get_diagnostics()

    assert diagnostics["sources"]["sqlite_files"] == [
        {"name": "logs.sqlite", "size_bytes": 6, "contents_omitted": True}
    ]


def test_provider_usage_context_endpoint_is_codex_only(monkeypatch):
    from app.api.v1 import providers as providers_api

    class FakeService:
        def get_diagnostics(self):
            return {
                "provider": "codex-cli",
                "decision": {"usage_status": "unsupported", "context_status": "unsupported"},
            }

    monkeypatch.setattr(providers_api, "CodexUsageContextService", lambda: FakeService())

    response = providers_api.get_provider_usage_context_diagnostics("codex-cli")

    assert response["provider"] == "codex-cli"
    assert response["provider_display_name"] == "Codex"
    assert response["decision"]["usage_status"] == "unsupported"

    with pytest.raises(providers_api.HTTPException) as exc_info:
        providers_api.get_provider_usage_context_diagnostics("claude-code")
    assert exc_info.value.status_code == 400
