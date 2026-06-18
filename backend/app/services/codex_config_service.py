"""Read and update Codex CLI TOML configuration."""
from __future__ import annotations

import shutil
import tempfile
import tomllib
import re
import copy
import json
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
SENSITIVE_KEY_PATTERN = re.compile(r"(token|secret|password|credential|api[_-]?key|auth|cookie|session)", re.I)
PROFILE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
PROFILE_V2_KEYS = ("profile-v2", "profile_v2")
MAX_MODELS_CACHE_BYTES = 5 * 1024 * 1024


class CodexConfigService:
    """Service for Codex config files."""

    def __init__(self, codex_home: Path | None = None):
        self.codex_home = codex_home or get_codex_home()

    @property
    def config_file(self) -> Path:
        return self.codex_home / "config.toml"

    @property
    def models_cache_file(self) -> Path:
        return self.codex_home / "models_cache.json"

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

    def _redact_summary_value(self, value: Any, parent_key: str = "") -> Any:
        if value is None:
            return None
        if isinstance(value, dict):
            return {
                key: "[redacted]" if SENSITIVE_KEY_PATTERN.search(key) or SENSITIVE_KEY_PATTERN.search(parent_key)
                else self._redact_summary_value(child, key)
                for key, child in value.items()
            }
        if isinstance(value, list):
            return [self._redact_summary_value(item, parent_key) for item in value]
        if SENSITIVE_KEY_PATTERN.search(parent_key):
            return "[redacted]"
        return value

    def _profile_name_from_file(self, path: Path) -> str:
        suffix = ".config.toml"
        return path.name[:-len(suffix)] if path.name.endswith(suffix) else path.stem

    def _is_safe_profile_name(self, name: str) -> bool:
        return bool(PROFILE_NAME_PATTERN.fullmatch(name))

    def _get_profile_files(self) -> list[Path]:
        if not self.codex_home.exists():
            return []
        return sorted(self.codex_home.glob("*.config.toml"))

    def _get_profile_v2_reference(self, config: dict[str, Any]) -> str | None:
        for key in PROFILE_V2_KEYS:
            value = config.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    def _summarize_config(self, config: dict[str, Any]) -> dict[str, Any]:
        projects = config.get("projects", {}) if isinstance(config.get("projects"), dict) else {}
        profiles = config.get("profiles", {}) if isinstance(config.get("profiles"), dict) else {}
        features = config.get("features", {}) if isinstance(config.get("features"), dict) else {}
        summary = {
            "model": config.get("model"),
            "model_reasoning_effort": config.get("model_reasoning_effort"),
            "profile": config.get("profile"),
            "profile_v2": self._get_profile_v2_reference(config),
            "sandbox_mode": config.get("sandbox_mode"),
            "approval_policy": config.get("approval_policy"),
            "search": config.get("search"),
            "strict_config": config.get("strict_config"),
            "no_alt_screen": config.get("no_alt_screen"),
            "projects": self._redact_summary_value(projects),
            "profiles": self._redact_summary_value(profiles),
            "features": self._redact_summary_value(features),
        }
        return {key: value for key, value in summary.items() if value is not None}

    def _safe_overlay_summary(self, config: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for key in SAFE_SCALAR_FIELDS:
            if key in config:
                summary[key] = self._redact_summary_value(config[key], key)
        profile_v2 = self._get_profile_v2_reference(config)
        if profile_v2 is not None:
            summary["profile_v2"] = self._redact_summary_value(profile_v2, "profile_v2")
        features = config.get("features")
        if isinstance(features, dict):
            summary["features"] = self._redact_summary_value(features, "features")
        return summary

    def _flatten_safe_summary(self, summary: dict[str, Any]) -> dict[str, Any]:
        flattened: dict[str, Any] = {}
        for key, value in summary.items():
            if key == "features" and isinstance(value, dict):
                for feature_key, feature_value in value.items():
                    flattened[f"features.{feature_key}"] = feature_value
            elif key not in {"projects", "profiles"}:
                flattened[key] = value
        return flattened

    def _get_overrides(self, base: dict[str, Any], overlay: dict[str, Any]) -> list[dict[str, Any]]:
        base_flat = self._flatten_safe_summary(base)
        overlay_flat = self._flatten_safe_summary(overlay)
        overrides: list[dict[str, Any]] = []
        for key, value in sorted(overlay_flat.items()):
            base_value = base_flat.get(key)
            if base_value != value:
                overrides.append({
                    "key": key,
                    "base": base_value,
                    "value": value,
                })
        return overrides

    def _merge_safe_summary(self, base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
        merged = copy.deepcopy(base)
        for key, value in overlay.items():
            if key == "features" and isinstance(value, dict):
                current = merged.get("features") if isinstance(merged.get("features"), dict) else {}
                merged["features"] = {**current, **value}
            elif key not in {"projects", "profiles"}:
                merged[key] = value
        return merged

    def _build_profile_source(
        self,
        *,
        name: str,
        source: str,
        path: Path | None,
        exists: bool,
        config: dict[str, Any],
        parse_error: str | None,
        base_summary: dict[str, Any],
    ) -> dict[str, Any]:
        summary = self._safe_overlay_summary(config) if not parse_error else {}
        return {
            "name": name,
            "source": source,
            "path": str(path) if path else None,
            "exists": exists,
            "parse_error": parse_error,
            "summary": summary,
            "overrides": self._get_overrides(base_summary, summary),
        }

    def resolve_profiles(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        """Resolve Codex profile references without exposing raw TOML or secrets."""
        config = config if config is not None else self.parse_toml_file(self.config_file)[0]
        base_summary = self._safe_overlay_summary(config)
        active_profile = config.get("profile") if isinstance(config.get("profile"), str) else None
        active_profile_v2 = self._get_profile_v2_reference(config)
        inline_profiles = config.get("profiles", {}) if isinstance(config.get("profiles"), dict) else {}

        sources: list[dict[str, Any]] = []
        for name, profile_config in sorted(inline_profiles.items()):
            if not isinstance(name, str) or not isinstance(profile_config, dict):
                continue
            sources.append(self._build_profile_source(
                name=name,
                source="inline",
                path=self.config_file,
                exists=True,
                config=profile_config,
                parse_error=None,
                base_summary=base_summary,
            ))

        for profile_file in self._get_profile_files():
            profile_config, parse_error = self.parse_toml_file(profile_file)
            sources.append(self._build_profile_source(
                name=self._profile_name_from_file(profile_file),
                source="file",
                path=profile_file,
                exists=profile_file.exists(),
                config=profile_config,
                parse_error=parse_error,
                base_summary=base_summary,
            ))

        source_names = {(source["name"], source["source"]) for source in sources}
        missing: list[dict[str, Any]] = []
        for reference_type, reference in (("profile", active_profile), ("profile_v2", active_profile_v2)):
            if not reference:
                continue
            if (reference, "inline") not in source_names and (reference, "file") not in source_names:
                entry = {
                    "name": reference,
                    "reference": reference_type,
                    "expected_file": None,
                    "unsafe_reference": not self._is_safe_profile_name(reference),
                }
                if self._is_safe_profile_name(reference):
                    entry["expected_file"] = str(self.codex_home / f"{reference}.config.toml")
                missing.append(entry)

        active_sources = [
            source for source in sources
            if source["name"] in {active_profile, active_profile_v2} and not source["parse_error"]
        ]
        effective_summary = copy.deepcopy(base_summary)
        for source in active_sources:
            effective_summary = self._merge_safe_summary(effective_summary, source["summary"])

        return {
            "active_profile": active_profile,
            "active_profile_v2": active_profile_v2,
            "resolution_order": ["config.toml", "inline profile", "*.config.toml profile file"],
            "base_summary": base_summary,
            "profiles": sources,
            "active_sources": active_sources,
            "missing_references": missing,
            "malformed_profiles": [
                {
                    "name": source["name"],
                    "path": source["path"],
                    "parse_error": source["parse_error"],
                }
                for source in sources if source["parse_error"]
            ],
            "effective_summary": effective_summary,
        }

    def _read_models_cache(self) -> tuple[dict[str, Any], str | None]:
        path = self.models_cache_file
        if not path.exists():
            return {}, None

        try:
            if path.stat().st_size > MAX_MODELS_CACHE_BYTES:
                return {}, "models_cache.json exceeds read limit"
            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError as exc:
            return {}, str(exc)
        except OSError as exc:
            return {}, str(exc)

        if not isinstance(data, dict):
            return {}, "models_cache.json root is not an object"
        return data, None

    @staticmethod
    def _model_option_from_mapping(value: str, metadata: Any, source: str) -> dict[str, Any] | None:
        if not value or "\x00" in value:
            return None

        label = value
        description = None
        priority = None
        if isinstance(metadata, dict):
            display_name = metadata.get("display_name")
            if isinstance(display_name, str) and display_name.strip():
                label = display_name.strip()
            description_value = metadata.get("description")
            if isinstance(description_value, str) and description_value.strip():
                description = description_value.strip()
            priority_value = metadata.get("priority")
            if isinstance(priority_value, int):
                priority = priority_value

        option = {
            "value": value,
            "label": label,
            "source": source,
        }
        if description is not None:
            option["description"] = description
        if priority is not None:
            option["priority"] = priority
        return option

    def _get_model_options(
        self,
        config: dict[str, Any],
        effective_summary: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str | None]:
        cache, parse_error = self._read_models_cache()
        options: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add_option(option: dict[str, Any] | None) -> None:
            if not option:
                return
            value = option["value"]
            if value in seen:
                return
            seen.add(value)
            options.append(option)

        models = cache.get("models")
        if isinstance(models, list):
            for item in models:
                if isinstance(item, str):
                    add_option(self._model_option_from_mapping(item, {}, "models_cache"))
                elif isinstance(item, dict):
                    slug = item.get("slug") or item.get("id") or item.get("name") or item.get("model")
                    if isinstance(slug, str):
                        add_option(self._model_option_from_mapping(slug, item, "models_cache"))
        elif isinstance(models, dict):
            for value, metadata in sorted(models.items()):
                if isinstance(value, str):
                    slug = metadata.get("slug") if isinstance(metadata, dict) else None
                    add_option(
                        self._model_option_from_mapping(
                            slug if isinstance(slug, str) else value,
                            metadata,
                            "models_cache",
                        )
                    )

        for source, value in (
            ("effective_config", effective_summary.get("model")),
            ("config", config.get("model")),
        ):
            if isinstance(value, str) and value.strip():
                add_option({
                    "value": value.strip(),
                    "label": value.strip(),
                    "source": source,
                })

        return options, parse_error

    def _get_profile_options(
        self,
        profile_resolution: dict[str, Any] | None,
        config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        options_by_name: dict[str, dict[str, Any]] = {}

        def add_profile(
            name: Any,
            source: str,
            *,
            parse_error: str | None = None,
            active: bool = False,
        ) -> None:
            if not isinstance(name, str) or not name.strip():
                return
            clean_name = name.strip()
            option = options_by_name.setdefault(
                clean_name,
                {
                    "value": clean_name,
                    "label": clean_name,
                    "sources": [],
                    "active": False,
                    "parse_error": None,
                },
            )
            if source not in option["sources"]:
                option["sources"].append(source)
            if active:
                option["active"] = True
            if parse_error and not option["parse_error"]:
                option["parse_error"] = parse_error

        if profile_resolution:
            active_names = {
                profile_resolution.get("active_profile"),
                profile_resolution.get("active_profile_v2"),
            }
            for source in profile_resolution.get("profiles", []):
                if not isinstance(source, dict):
                    continue
                name = source.get("name")
                add_profile(
                    name,
                    str(source.get("source") or "profile"),
                    parse_error=source.get("parse_error") if isinstance(source.get("parse_error"), str) else None,
                    active=name in active_names,
                )
            for missing in profile_resolution.get("missing_references", []):
                if isinstance(missing, dict):
                    add_profile(missing.get("name"), "missing_reference", active=True)

        add_profile(config.get("profile"), "config", active=True)
        active_profile_v2 = self._get_profile_v2_reference(config)
        add_profile(active_profile_v2, "config", active=True)

        return sorted(options_by_name.values(), key=lambda option: option["value"].lower())

    def get_launch_options(self) -> dict[str, Any]:
        """Return non-secret Codex values useful when launching new sessions."""
        config, parse_error = self.parse_toml_file(self.config_file)
        profile_resolution = self.resolve_profiles(config) if not parse_error else None
        effective_summary = profile_resolution["effective_summary"] if profile_resolution else {}
        default_profile = None
        if profile_resolution:
            default_profile = (
                profile_resolution.get("active_profile")
                or profile_resolution.get("active_profile_v2")
            )
        model_options, models_parse_error = self._get_model_options(config, effective_summary)

        return {
            "provider": "codex-cli",
            "config_path": str(self.config_file),
            "models_cache_path": str(self.models_cache_file),
            "config_exists": self.config_file.exists(),
            "config_parse_error": parse_error,
            "models_cache_exists": self.models_cache_file.exists(),
            "models_cache_parse_error": models_parse_error,
            "default_model": effective_summary.get("model") or config.get("model"),
            "default_profile": default_profile,
            "model_options": model_options,
            "profile_options": self._get_profile_options(profile_resolution, config),
        }

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
            for profile in self._get_profile_files():
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

    def _is_safe_raw_file(self, path: Path) -> bool:
        root = self.codex_home.expanduser().resolve()
        if path == root / "config.toml":
            return True
        if path.parent == root and path.name.endswith(".config.toml"):
            return True
        if path.parent == root / "rules" and path.suffix == ".rules":
            return True
        return False

    def get_config(self) -> dict[str, Any]:
        config, parse_error = self.parse_toml_file(self.config_file)

        return {
            "provider": "codex-cli",
            "path": str(self.config_file),
            "exists": self.config_file.exists(),
            "parse_error": parse_error,
            "summary": self._summarize_config(config),
            "profile_resolution": self.resolve_profiles(config) if not parse_error else None,
        }

    def get_file_content(self, file_path: str) -> dict[str, Any]:
        path = Path(file_path).expanduser().resolve()
        root = self.codex_home.expanduser().resolve()
        if path != root and root not in path.parents:
            raise ValueError("Path is outside CODEX_HOME")
        if not self._is_safe_raw_file(path):
            raise ValueError("Codex raw viewer only supports config.toml, *.config.toml, and rules/*.rules")

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
