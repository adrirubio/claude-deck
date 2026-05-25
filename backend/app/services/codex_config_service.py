"""Read and update Codex CLI TOML configuration."""
from __future__ import annotations

import shutil
import tempfile
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.exceptions import TOMLKitError
from tomlkit.items import Table

from app.services.providers.codex_cli import get_codex_home


SAFE_SCALAR_FIELDS = {
    "model": str,
    "model_reasoning_effort": str,
    "profile": str,
    "sandbox_mode": str,
    "approval_policy": str,
    "search": bool,
    "strict_config": bool,
    "no_alt_screen": bool,
}


class CodexConfigService:
    """Service for Codex config files."""

    def __init__(self, codex_home: Path | None = None):
        self.codex_home = codex_home or get_codex_home()

    @property
    def config_file(self) -> Path:
        return self.codex_home / "config.toml"

    def parse_toml_file(self, path: Path) -> tuple[dict[str, Any], str | None]:
        if not path.exists():
            return {}, None
        try:
            with path.open("rb") as file:
                return tomllib.load(file), None
        except tomllib.TOMLDecodeError as exc:
            return {}, str(exc)
        except OSError as exc:
            return {}, str(exc)

    def _parse_toml_document(self, path: Path):
        if not path.exists():
            return tomlkit.document(), None
        try:
            return tomlkit.parse(path.read_text(encoding="utf-8")), None
        except (TOMLKitError, OSError) as exc:
            return None, str(exc)

    def get_all_config_files(self) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        user_config = self.config_file
        files.append({
            "path": str(user_config),
            "scope": "user",
            "exists": user_config.exists(),
            "content": None,
            "provider": "codex-cli",
        })

        if self.codex_home.exists():
            for profile in sorted(self.codex_home.glob("*.config.toml")):
                files.append({
                    "path": str(profile),
                    "scope": "profile",
                    "exists": True,
                    "content": None,
                    "provider": "codex-cli",
                })

            rules_dir = self.codex_home / "rules"
            if rules_dir.exists():
                for rule in sorted(rules_dir.glob("*.rules")):
                    files.append({
                        "path": str(rule),
                        "scope": "rules",
                        "exists": True,
                        "content": None,
                        "provider": "codex-cli",
                    })
        return files

    def get_config(self) -> dict[str, Any]:
        config, parse_error = self.parse_toml_file(self.config_file)
        projects = config.get("projects", {}) if isinstance(config.get("projects"), dict) else {}
        profiles = config.get("profiles", {}) if isinstance(config.get("profiles"), dict) else {}
        features = config.get("features", {}) if isinstance(config.get("features"), dict) else {}

        return {
            "provider": "codex-cli",
            "path": str(self.config_file),
            "exists": self.config_file.exists(),
            "parse_error": parse_error,
            "config": config,
            "summary": {
                "model": config.get("model"),
                "model_reasoning_effort": config.get("model_reasoning_effort"),
                "profile": config.get("profile"),
                "sandbox_mode": config.get("sandbox_mode"),
                "approval_policy": config.get("approval_policy"),
                "search": config.get("search"),
                "strict_config": config.get("strict_config"),
                "no_alt_screen": config.get("no_alt_screen"),
                "projects": projects,
                "profiles": profiles,
                "features": features,
            },
        }

    def get_file_content(self, file_path: str) -> dict[str, Any]:
        path = Path(file_path).expanduser().resolve()
        root = self.codex_home.expanduser().resolve()
        if path != root and root not in path.parents:
            raise ValueError("Path is outside CODEX_HOME")

        if not path.exists():
            return {"path": str(path), "content": "", "exists": False}

        try:
            content = path.read_text(encoding="utf-8")
            parse_error = None
            if path.suffix == ".toml":
                _, parse_error = self.parse_toml_file(path)
            return {
                "path": str(path),
                "content": content,
                "exists": True,
                "parse_error": parse_error,
            }
        except OSError as exc:
            return {
                "path": str(path),
                "content": f"Error reading file: {exc}",
                "exists": True,
            }

    def _validate_scalar_updates(self, settings: dict[str, Any]) -> None:
        unknown = set(settings) - set(SAFE_SCALAR_FIELDS)
        if unknown:
            raise ValueError(f"Unsupported Codex setting(s): {', '.join(sorted(unknown))}")

        for key, value in settings.items():
            expected_type = SAFE_SCALAR_FIELDS[key]
            if value is None:
                continue
            if expected_type is bool:
                if type(value) is not bool:
                    raise ValueError(f"Codex setting '{key}' must be a boolean")
            elif not isinstance(value, expected_type):
                raise ValueError(f"Codex setting '{key}' must be a string")

    def _validate_feature_updates(self, features: dict[str, Any]) -> None:
        for key, value in features.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("Feature names must be non-empty strings")
            if "." in key or "/" in key or "\\" in key or ".." in key:
                raise ValueError(f"Unsafe feature name: {key}")
            if type(value) is not bool and value is not None:
                raise ValueError(f"Feature '{key}' must be a boolean")

    def _create_backup(self, path: Path) -> Path | None:
        if not path.exists():
            return None
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = path.with_name(f"{path.name}.{timestamp}.bak")
        counter = 1
        while backup_path.exists():
            backup_path = path.with_name(f"{path.name}.{timestamp}.{counter}.bak")
            counter += 1
        shutil.copy2(path, backup_path)
        return backup_path

    def _write_config_atomically(self, path: Path, content: str) -> None:
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                temp_file.write(content)
                temp_file.flush()
                try:
                    import os

                    os.fsync(temp_file.fileno())
                except OSError:
                    pass
            temp_path.replace(path)
        except Exception:
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            raise

    def update_safe_settings(
        self,
        settings: dict[str, Any] | None = None,
        features: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update safe Codex settings while preserving TOML formatting."""
        settings = settings or {}
        features = features or {}
        self._validate_scalar_updates(settings)
        self._validate_feature_updates(features)

        config_path = self.config_file
        root = self.codex_home.expanduser().resolve()
        resolved_config = config_path.expanduser().resolve()
        if resolved_config != root / "config.toml":
            raise ValueError("Unsafe Codex config path")
        if ".." in config_path.parts:
            raise ValueError("Unsafe Codex config path")

        document, parse_error = self._parse_toml_document(config_path)
        if parse_error or document is None:
            raise ValueError(f"Cannot update config.toml while it has parse errors: {parse_error}")

        for key, value in settings.items():
            if value is None:
                document.pop(key, None)
            else:
                document[key] = value

        if features:
            if "features" not in document or not isinstance(document["features"], Table):
                document["features"] = tomlkit.table()
            feature_table = document["features"]
            for key, value in features.items():
                if value is None:
                    feature_table.pop(key, None)
                else:
                    feature_table[key] = value

        config_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path = self._create_backup(config_path)
        self._write_config_atomically(config_path, tomlkit.dumps(document))

        updated = self.get_config()
        return {
            "success": True,
            "path": str(config_path),
            "backup_path": str(backup_path) if backup_path else None,
            "config": updated,
        }
