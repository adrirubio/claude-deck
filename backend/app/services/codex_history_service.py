"""Read-only diagnostics for Codex history and model cache files."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.providers.codex_cli import get_codex_home


class CodexHistoryService:
    """Summarize generated Codex files without exposing prompt text."""

    def __init__(
        self,
        codex_home: Path | None = None,
        *,
        max_history_rows: int = 50_000,
        max_model_cache_bytes: int = 5 * 1024 * 1024,
    ):
        self.codex_home = codex_home or get_codex_home()
        self.max_history_rows = max_history_rows
        self.max_model_cache_bytes = max_model_cache_bytes

    @property
    def history_file(self) -> Path:
        return self.codex_home / "history.jsonl"

    @property
    def models_cache_file(self) -> Path:
        return self.codex_home / "models_cache.json"

    def get_diagnostics(self) -> dict[str, Any]:
        return {
            "provider": "codex-cli",
            "decision": {
                "surface": "diagnostics_only",
                "reason": (
                    "Codex history currently exposes session_id, ts, and sensitive prompt text. "
                    "Claude Deck summarizes structure only until stable non-sensitive history "
                    "metadata is available."
                ),
            },
            "history": self.summarize_history(),
            "models_cache": self.summarize_models_cache(),
        }

    def summarize_history(self) -> dict[str, Any]:
        path = self.history_file
        summary: dict[str, Any] = {
            "path": str(path),
            "exists": path.exists(),
            "size_bytes": None,
            "max_rows": self.max_history_rows,
            "rows_read": 0,
            "valid_rows": 0,
            "invalid_rows": 0,
            "truncated": False,
            "observed_keys": [],
            "sensitive_fields_omitted": [],
            "session_id_rows": 0,
            "unique_session_count": 0,
            "ts_rows": 0,
            "first_ts": None,
            "last_ts": None,
            "text_rows": 0,
            "latest_session_summaries": [],
            "read_error": None,
        }
        if not path.exists():
            return summary

        try:
            summary["size_bytes"] = path.stat().st_size
            observed_keys: set[str] = set()
            session_ids: set[str] = set()
            sessions: dict[str, dict[str, Any]] = {}
            first_key: float | None = None
            last_key: float | None = None

            with path.open("r", encoding="utf-8", errors="replace") as file:
                for raw_line in file:
                    if not raw_line.strip():
                        continue
                    if summary["rows_read"] >= self.max_history_rows:
                        summary["truncated"] = True
                        break

                    summary["rows_read"] += 1
                    try:
                        row = json.loads(raw_line)
                    except json.JSONDecodeError:
                        summary["invalid_rows"] += 1
                        continue

                    if not isinstance(row, dict):
                        summary["invalid_rows"] += 1
                        continue

                    summary["valid_rows"] += 1
                    observed_keys.update(str(key) for key in row.keys())
                    if isinstance(row.get("text"), str):
                        summary["text_rows"] += 1

                    session_id = row.get("session_id")
                    if isinstance(session_id, str) and session_id:
                        summary["session_id_rows"] += 1
                        session_ids.add(session_id)

                    ts = row.get("ts")
                    ts_key = self._timestamp_key(ts)
                    if ts_key is not None:
                        summary["ts_rows"] += 1
                        if first_key is None or ts_key < first_key:
                            first_key = ts_key
                            summary["first_ts"] = ts
                        if last_key is None or ts_key > last_key:
                            last_key = ts_key
                            summary["last_ts"] = ts

                    if isinstance(session_id, str) and session_id:
                        session = sessions.setdefault(
                            session_id,
                            {
                                "session_id_hash": self._hash_session_id(session_id),
                                "message_count": 0,
                                "first_ts": None,
                                "last_ts": None,
                                "_first_key": None,
                                "_last_key": None,
                            },
                        )
                        session["message_count"] += 1
                        if ts_key is not None:
                            if session["_first_key"] is None or ts_key < session["_first_key"]:
                                session["_first_key"] = ts_key
                                session["first_ts"] = ts
                            if session["_last_key"] is None or ts_key > session["_last_key"]:
                                session["_last_key"] = ts_key
                                session["last_ts"] = ts

            summary["observed_keys"] = sorted(observed_keys)
            if "text" in observed_keys:
                summary["sensitive_fields_omitted"] = ["text"]
            summary["unique_session_count"] = len(session_ids)
            latest_sessions = sorted(
                sessions.values(),
                key=lambda item: item["_last_key"] if item["_last_key"] is not None else -1,
                reverse=True,
            )
            summary["latest_session_summaries"] = [
                {
                    "session_id_hash": session["session_id_hash"],
                    "message_count": session["message_count"],
                    "first_ts": session["first_ts"],
                    "last_ts": session["last_ts"],
                }
                for session in latest_sessions[:10]
            ]
        except OSError as exc:
            summary["read_error"] = str(exc)

        return summary

    def summarize_models_cache(self) -> dict[str, Any]:
        path = self.models_cache_file
        summary: dict[str, Any] = {
            "path": str(path),
            "exists": path.exists(),
            "size_bytes": None,
            "max_bytes": self.max_model_cache_bytes,
            "too_large": False,
            "parse_error": None,
            "root_keys": [],
            "fetched_at": None,
            "client_version": None,
            "etag_present": False,
            "models_shape": None,
            "model_count": None,
            "raw_fields_omitted": [],
        }
        if not path.exists():
            return summary

        try:
            size = path.stat().st_size
            summary["size_bytes"] = size
            if size > self.max_model_cache_bytes:
                summary["too_large"] = True
                summary["parse_error"] = "models_cache.json exceeds diagnostics read limit"
                return summary

            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError as exc:
            summary["parse_error"] = str(exc)
            return summary
        except OSError as exc:
            summary["parse_error"] = str(exc)
            return summary

        if not isinstance(data, dict):
            summary["parse_error"] = "models_cache.json root is not an object"
            return summary

        summary["root_keys"] = sorted(str(key) for key in data.keys())
        summary["fetched_at"] = data.get("fetched_at") if isinstance(data.get("fetched_at"), str) else None
        summary["client_version"] = (
            data.get("client_version") if isinstance(data.get("client_version"), str) else None
        )
        summary["etag_present"] = bool(data.get("etag"))
        models = data.get("models")
        if isinstance(models, list):
            summary["models_shape"] = "list"
            summary["model_count"] = len(models)
        elif isinstance(models, dict):
            summary["models_shape"] = "object"
            summary["model_count"] = len(models)
        elif models is not None:
            summary["models_shape"] = type(models).__name__
        omitted = [key for key in ("etag", "models") if key in data]
        summary["raw_fields_omitted"] = omitted
        return summary

    @staticmethod
    def _hash_session_id(session_id: str) -> str:
        return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _timestamp_key(value: Any) -> float | None:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                pass
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except ValueError:
                return None
        return None
