"""Read Codex CLI TOML configuration."""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from app.services.providers.codex_cli import get_codex_home


class CodexConfigService:
    """Service for Codex config files.

    This first pass is read-only. Python's stdlib tomllib is used for safe TOML
    parsing; write support should use a formatting-preserving writer such as
    tomlkit when editable TOML lands.
    """

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

