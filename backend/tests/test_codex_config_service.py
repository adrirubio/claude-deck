"""Tests for Codex TOML config parsing."""


def test_codex_config_parses_config_toml(tmp_path):
    from app.services.codex_config_service import CodexConfigService

    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '\n'.join([
            'model = "gpt-5.1-codex"',
            'model_reasoning_effort = "medium"',
            '',
            '[projects."/repo/app"]',
            'trust_level = "trusted"',
            '',
            '[features]',
            'search = true',
        ]),
        encoding="utf-8",
    )

    data = CodexConfigService(codex_home=tmp_path).get_config()

    assert data["exists"] is True
    assert data["parse_error"] is None
    assert data["summary"]["model"] == "gpt-5.1-codex"
    assert data["summary"]["projects"]["/repo/app"]["trust_level"] == "trusted"
    assert data["summary"]["features"]["search"] is True


def test_codex_config_reports_parse_errors(tmp_path):
    from app.services.codex_config_service import CodexConfigService

    (tmp_path / "config.toml").write_text("invalid = [", encoding="utf-8")

    data = CodexConfigService(codex_home=tmp_path).get_config()

    assert data["exists"] is True
    assert data["parse_error"]
    assert "config" not in data


def test_codex_config_summary_omits_full_config_and_secrets(tmp_path):
    from app.services.codex_config_service import CodexConfigService

    (tmp_path / "config.toml").write_text(
        '\n'.join([
            'model = "gpt-5"',
            '',
            '[mcp_servers.linear]',
            'command = "npx"',
            'args = ["-y", "@linear/mcp"]',
            '',
            '[mcp_servers.linear.env]',
            'LINEAR_API_KEY = "secret-api-key"',
            '',
            '[auth]',
            'token = "secret-auth-token"',
            '',
            '[profiles.work]',
            'api_key = "secret-profile-key"',
        ]),
        encoding="utf-8",
    )

    data = CodexConfigService(codex_home=tmp_path).get_config()
    serialized = str(data)

    assert "config" not in data
    assert data["summary"]["model"] == "gpt-5"
    assert data["summary"]["profiles"]["work"]["api_key"] == "[redacted]"
    assert "secret-api-key" not in serialized
    assert "secret-auth-token" not in serialized
    assert "secret-profile-key" not in serialized
    assert "mcp_servers" not in serialized


def test_codex_profile_resolution_merges_active_inline_and_file_profiles(tmp_path):
    from app.services.codex_config_service import CodexConfigService

    (tmp_path / "config.toml").write_text(
        '\n'.join([
            'model = "base-model"',
            'profile = "work"',
            'profile-v2 = "work"',
            'approval_policy = "ask"',
            '',
            '[features]',
            'search = false',
            '',
            '[profiles.work]',
            'approval_policy = "on-request"',
            '',
            '[profiles.work.features]',
            'search = true',
            '',
            '[profiles.work.env]',
            'API_TOKEN = "secret-inline-token"',
        ]),
        encoding="utf-8",
    )
    (tmp_path / "work.config.toml").write_text(
        '\n'.join([
            'model = "profile-model"',
            'sandbox_mode = "workspace-write"',
            'authToken = "secret-file-token"',
            '',
            '[features]',
            'shell_tool = true',
        ]),
        encoding="utf-8",
    )

    data = CodexConfigService(codex_home=tmp_path).get_config()
    resolution = data["profile_resolution"]
    serialized = str(resolution)

    assert data["summary"]["profile"] == "work"
    assert data["summary"]["profile_v2"] == "work"
    assert resolution["active_profile"] == "work"
    assert resolution["active_profile_v2"] == "work"
    assert [source["source"] for source in resolution["active_sources"]] == ["inline", "file"]
    assert resolution["effective_summary"]["model"] == "profile-model"
    assert resolution["effective_summary"]["approval_policy"] == "on-request"
    assert resolution["effective_summary"]["sandbox_mode"] == "workspace-write"
    assert resolution["effective_summary"]["features"]["search"] is True
    assert resolution["effective_summary"]["features"]["shell_tool"] is True
    assert any(
        override["key"] == "approval_policy"
        for source in resolution["profiles"]
        if source["source"] == "inline"
        for override in source["overrides"]
    )
    assert "secret-inline-token" not in serialized
    assert "secret-file-token" not in serialized
    assert "authToken" not in serialized


def test_codex_profile_resolution_reports_missing_and_malformed_profiles(tmp_path):
    from app.services.codex_config_service import CodexConfigService

    (tmp_path / "config.toml").write_text(
        '\n'.join([
            'model = "base-model"',
            'profile = "missing"',
            'profile_v2 = "broken"',
        ]),
        encoding="utf-8",
    )
    (tmp_path / "broken.config.toml").write_text("model = [", encoding="utf-8")

    data = CodexConfigService(codex_home=tmp_path).get_config()
    resolution = data["profile_resolution"]

    assert resolution["active_profile"] == "missing"
    assert resolution["active_profile_v2"] == "broken"
    assert resolution["missing_references"] == [
        {
            "name": "missing",
            "reference": "profile",
            "expected_file": str(tmp_path / "missing.config.toml"),
            "unsafe_reference": False,
        }
    ]
    assert resolution["malformed_profiles"][0]["name"] == "broken"
    assert resolution["malformed_profiles"][0]["parse_error"]
    assert resolution["effective_summary"]["model"] == "base-model"


def test_codex_profile_resolution_handles_default_config_without_profile(tmp_path):
    from app.services.codex_config_service import CodexConfigService

    (tmp_path / "config.toml").write_text(
        '\n'.join([
            'model = "base-model"',
            '',
            '[features]',
            'search = true',
        ]),
        encoding="utf-8",
    )

    resolution = CodexConfigService(codex_home=tmp_path).get_config()["profile_resolution"]

    assert resolution["active_profile"] is None
    assert resolution["active_profile_v2"] is None
    assert resolution["profiles"] == []
    assert resolution["missing_references"] == []
    assert resolution["effective_summary"]["model"] == "base-model"
    assert resolution["effective_summary"]["features"]["search"] is True


def test_codex_profile_resolution_does_not_build_paths_for_unsafe_references(tmp_path):
    from app.services.codex_config_service import CodexConfigService

    (tmp_path / "config.toml").write_text(
        '\n'.join([
            'profile = "../outside"',
            'profile_v2 = "safe-profile"',
        ]),
        encoding="utf-8",
    )

    missing = CodexConfigService(codex_home=tmp_path).get_config()["profile_resolution"]["missing_references"]

    assert missing[0] == {
        "name": "../outside",
        "reference": "profile",
        "expected_file": None,
        "unsafe_reference": True,
    }
    assert missing[1] == {
        "name": "safe-profile",
        "reference": "profile_v2",
        "expected_file": str(tmp_path / "safe-profile.config.toml"),
        "unsafe_reference": False,
    }


def test_codex_raw_view_rejects_auth_and_allows_safe_files(tmp_path):
    from app.services.codex_config_service import CodexConfigService

    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (tmp_path / "config.toml").write_text('model = "gpt-5"\n', encoding="utf-8")
    (tmp_path / "work.config.toml").write_text('profile = "work"\n', encoding="utf-8")
    (rules_dir / "team.rules").write_text("be careful\n", encoding="utf-8")
    (tmp_path / "auth.json").write_text('{"token":"secret"}', encoding="utf-8")

    service = CodexConfigService(codex_home=tmp_path)

    assert service.get_file_content(str(tmp_path / "config.toml"))["exists"] is True
    assert service.get_file_content(str(tmp_path / "work.config.toml"))["exists"] is True
    assert service.get_file_content(str(rules_dir / "team.rules"))["exists"] is True

    try:
        service.get_file_content(str(tmp_path / "auth.json"))
    except ValueError as exc:
        assert "raw viewer only supports" in str(exc)
    else:
        raise AssertionError("Expected auth.json raw access to be rejected")


def test_codex_update_preserves_comments_and_creates_backup(tmp_path):
    from app.services.codex_config_service import CodexConfigService

    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '\n'.join([
            "# keep this comment",
            'model = "old-model"',
            "",
            "[features]",
            "# feature comment",
            "shell_tool = false",
            "",
        ]),
        encoding="utf-8",
    )

    result = CodexConfigService(codex_home=tmp_path).update_safe_settings(
        settings={"model": "new-model"},
        features={"shell_tool": True},
    )

    updated = config_path.read_text(encoding="utf-8")
    assert "# keep this comment" in updated
    assert "# feature comment" in updated
    assert 'model = "new-model"' in updated
    assert "shell_tool = true" in updated
    assert result["backup_path"] is not None
    backup_path = tmp_path / result["backup_path"].split("/")[-1]
    assert backup_path.exists()
    assert 'model = "old-model"' in backup_path.read_text(encoding="utf-8")


def test_codex_update_creates_missing_config(tmp_path):
    from app.services.codex_config_service import CodexConfigService

    result = CodexConfigService(codex_home=tmp_path).update_safe_settings(
        settings={"model": "gpt-5.1-codex", "strict_config": True},
        features={"search": True},
    )

    config_path = tmp_path / "config.toml"
    assert config_path.exists()
    assert result["backup_path"] is None
    data = CodexConfigService(codex_home=tmp_path).get_config()
    assert data["summary"]["model"] == "gpt-5.1-codex"
    assert data["summary"]["strict_config"] is True
    assert data["summary"]["features"]["search"] is True


def test_codex_update_cleans_up_temp_file_on_atomic_write_failure(tmp_path, monkeypatch):
    from app.services.codex_config_service import CodexConfigService

    config_path = tmp_path / "config.toml"
    config_path.write_text('model = "old-model"\n', encoding="utf-8")
    original_replace = type(config_path).replace

    def fail_replace(self, target):
        if self.name.startswith(".config.toml.") and self.name.endswith(".tmp"):
            raise OSError("replace failed")
        return original_replace(self, target)

    monkeypatch.setattr(type(config_path), "replace", fail_replace)

    try:
        CodexConfigService(codex_home=tmp_path).update_safe_settings(
            settings={"model": "new-model"},
        )
    except OSError as exc:
        assert "replace failed" in str(exc)
    else:
        raise AssertionError("Expected atomic replace failure")

    assert config_path.read_text(encoding="utf-8") == 'model = "old-model"\n'
    assert list(tmp_path.glob(".config.toml.*.tmp")) == []
    assert list(tmp_path.glob("config.toml.*.bak"))


def test_codex_update_rejects_unsafe_fields(tmp_path):
    from app.services.codex_config_service import CodexConfigService

    service = CodexConfigService(codex_home=tmp_path)

    try:
        service.update_safe_settings(settings={"auth": "secret"})
    except ValueError as exc:
        assert "Unsupported Codex setting" in str(exc)
    else:
        raise AssertionError("Expected unsafe setting to be rejected")

    try:
        service.update_safe_settings(features={"../bad": True})
    except ValueError as exc:
        assert "Unsafe feature name" in str(exc)
    else:
        raise AssertionError("Expected unsafe feature name to be rejected")


def test_codex_update_rejects_traversal_config_home(tmp_path):
    from app.services.codex_config_service import CodexConfigService

    service = CodexConfigService(codex_home=tmp_path / "nested" / "..")

    try:
        service.update_safe_settings(settings={"model": "new-model"})
    except ValueError as exc:
        assert "Unsafe Codex config path" in str(exc)
    else:
        raise AssertionError("Expected traversal config path to be rejected")


def test_codex_update_rejects_parse_error_without_overwriting(tmp_path):
    from app.services.codex_config_service import CodexConfigService

    config_path = tmp_path / "config.toml"
    original = "invalid = ["
    config_path.write_text(original, encoding="utf-8")

    try:
        CodexConfigService(codex_home=tmp_path).update_safe_settings(
            settings={"model": "new-model"},
        )
    except ValueError as exc:
        assert "parse errors" in str(exc)
    else:
        raise AssertionError("Expected parse-error config to be rejected")

    assert config_path.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob("*.bak")) == []
