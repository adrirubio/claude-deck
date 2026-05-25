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
    assert data["config"] == {}

