"""Read-only Codex usage/context diagnostics.

Codex history contains prompt text, and the local model cache is not a stable
usage source. This service reports only safe file-shape metadata so callers can
explain the current unsupported state without exposing raw prompts or cache
payloads.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.providers.codex_cli import get_codex_home


METRIC_KEY_MARKERS = (
    "token",
    "usage",
    "context",
)

MAX_HISTORY_ROWS = 50_000
MAX_MODELS_CACHE_BYTES = 5 * 1024 * 1024


class CodexUsageContextService:
    """Summarize Codex usage/context data sources without exposing contents."""

    def __init__(
        self,
        codex_home: Path | None = None,
        *,
        max_history_rows: int = MAX_HISTORY_ROWS,
        max_models_cache_bytes: int = MAX_MODELS_CACHE_BYTES,
    ):
        self.codex_home = (codex_home or get_codex_home()).expanduser()
        self.history_path = self.codex_home / "history.jsonl"
        self.models_cache_path = self.codex_home / "models_cache.json"
        self.max_history_rows = max_history_rows
        self.max_models_cache_bytes = max_models_cache_bytes

    def get_diagnostics(self) -> dict[str, Any]:
        """Return safe diagnostics for Codex usage/context parity."""
        history = self._summarize_history()
        models_cache = self._summarize_models_cache()
        sqlite_files = self._summarize_sqlite_files()

        metric_fields = sorted(
            set(history.get("metric_fields_present", []))
            | set(models_cache.get("metric_fields_present", []))
        )
        stable_usage_surface = False
        stable_context_surface = False

        return {
            "provider": "codex-cli",
            "decision": {
                "surface": "diagnostics_only",
                "usage_status": "unsupported",
                "context_status": "unsupported",
                "reason": (
                    "Local Codex files do not currently expose a stable usage "
                    "or context metric surface that can be read without prompt "
                    "text or raw cache payloads."
                ),
            },
            "sources": {
                "history": {
                    "path": str(self.history_path),
                    "exists": self.history_path.exists(),
                },
                "models_cache": {
                    "path": str(self.models_cache_path),
                    "exists": self.models_cache_path.exists(),
                },
                "sqlite_files": sqlite_files,
            },
            "history": history,
            "models_cache": models_cache,
            "metric_findings": {
                "metric_fields_present": metric_fields,
                "token_metrics_present": any("token" in field.lower() for field in metric_fields),
                "context_metrics_present": any("context" in field.lower() for field in metric_fields),
                "stable_usage_surface": stable_usage_surface,
                "stable_context_surface": stable_context_surface,
                "notes": [
                    "history.jsonl text values are treated as prompt content and are not returned.",
                    "models_cache.json model payloads are summarized by shape only.",
                ],
            },
        }

    def _summarize_history(self) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "exists": False,
            "size_bytes": 0,
            "rows_read": 0,
            "valid_rows": 0,
            "invalid_rows": 0,
            "truncated": False,
            "observed_keys": [],
            "standard_fields_present": [],
            "metric_fields_present": [],
            "prompt_text_omitted": True,
        }
        if not self.history_path.exists():
            return summary

        summary["exists"] = True
        summary["size_bytes"] = self._safe_size(self.history_path)
        observed_keys: set[str] = set()
        standard_fields: set[str] = set()
        metric_fields: set[str] = set()

        try:
            with self.history_path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if summary["rows_read"] >= self.max_history_rows:
                        summary["truncated"] = True
                        break
                    stripped = line.strip()
                    if not stripped:
                        continue
                    summary["rows_read"] += 1
                    try:
                        row = json.loads(stripped)
                    except json.JSONDecodeError:
                        summary["invalid_rows"] += 1
                        continue
                    if not isinstance(row, dict):
                        summary["invalid_rows"] += 1
                        continue
                    summary["valid_rows"] += 1
                    for key in row:
                        key_string = str(key)
                        observed_keys.add(key_string)
                        if key_string in {"session_id", "ts", "text"}:
                            standard_fields.add(key_string)
                        if self._looks_like_metric_key(key_string):
                            metric_fields.add(key_string)
        except OSError as exc:
            summary["read_error"] = type(exc).__name__

        summary["observed_keys"] = sorted(observed_keys)
        summary["standard_fields_present"] = sorted(standard_fields)
        summary["metric_fields_present"] = sorted(metric_fields)
        return summary

    def _summarize_models_cache(self) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "exists": False,
            "size_bytes": 0,
            "too_large": False,
            "parse_error": None,
            "root_keys": [],
            "metadata_fields_present": [],
            "metric_fields_present": [],
            "model_count": None,
            "models_shape": None,
            "etag_present": False,
            "raw_payload_omitted": True,
        }
        if not self.models_cache_path.exists():
            return summary

        summary["exists"] = True
        summary["size_bytes"] = self._safe_size(self.models_cache_path)
        if summary["size_bytes"] > self.max_models_cache_bytes:
            summary["too_large"] = True
            return summary

        try:
            payload = json.loads(self.models_cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            summary["parse_error"] = "invalid_json"
            return summary
        except OSError as exc:
            summary["parse_error"] = type(exc).__name__
            return summary

        if not isinstance(payload, dict):
            summary["parse_error"] = "root_not_object"
            return summary

        root_keys = sorted(str(key) for key in payload)
        summary["root_keys"] = root_keys
        summary["metadata_fields_present"] = [
            key for key in ("fetched_at", "etag", "client_version") if key in payload
        ]
        summary["etag_present"] = "etag" in payload
        summary["metric_fields_present"] = [
            key for key in root_keys if self._looks_like_metric_key(key)
        ]

        models = payload.get("models")
        if isinstance(models, list):
            summary["models_shape"] = "list"
            summary["model_count"] = len(models)
        elif isinstance(models, dict):
            summary["models_shape"] = "object"
            summary["model_count"] = len(models)
        elif models is not None:
            summary["models_shape"] = type(models).__name__

        return summary

    def _summarize_sqlite_files(self) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        for path in sorted(self.codex_home.glob("*.sqlite*")):
            if not path.is_file():
                continue
            files.append(
                {
                    "name": path.name,
                    "size_bytes": self._safe_size(path),
                    "contents_omitted": True,
                }
            )
        return files

    @staticmethod
    def _looks_like_metric_key(key: str) -> bool:
        lower_key = key.lower()
        return any(marker in lower_key for marker in METRIC_KEY_MARKERS)

    @staticmethod
    def _safe_size(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0
