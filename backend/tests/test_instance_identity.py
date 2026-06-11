import importlib


def _service():
    module = importlib.import_module("app.services.instance_identity")
    module.get_instance_identity.cache_clear()
    return module


def test_instance_identity_uses_env_overrides(monkeypatch):
    service = _service()
    monkeypatch.setattr(service.socket, "gethostname", lambda: "studio-mac.local")
    monkeypatch.setenv("CLAUDE_DECK_INSTANCE_NAME", "Studio Mac")
    monkeypatch.setenv("CLAUDE_DECK_INSTANCE_ACCENT", "blue")
    monkeypatch.setenv("CLAUDE_DECK_INSTANCE_ID", "studio-mac")

    identity = service.get_instance_identity()

    assert identity.name == "Studio Mac"
    assert identity.accent == "blue"
    assert identity.id == "studio-mac"
    assert identity.hostname == "studio-mac.local"
    assert identity.short_hostname == "studio-mac"


def test_instance_identity_defaults_are_stable_and_non_sensitive(monkeypatch):
    service = _service()
    monkeypatch.setattr(service.socket, "gethostname", lambda: "linux-box.local")
    monkeypatch.delenv("CLAUDE_DECK_INSTANCE_NAME", raising=False)
    monkeypatch.delenv("CLAUDE_DECK_INSTANCE_ACCENT", raising=False)
    monkeypatch.delenv("CLAUDE_DECK_INSTANCE_ID", raising=False)

    identity = service.get_instance_identity()

    assert identity.name == "linux-box"
    assert identity.hostname == "linux-box.local"
    assert identity.short_hostname == "linux-box"
    assert identity.accent in service.ALLOWED_ACCENTS
    assert identity.id
    assert "linux-box" not in identity.id
    assert identity.id == service.get_instance_identity().id


def test_instance_identity_sanitizes_display_values(monkeypatch):
    service = _service()
    monkeypatch.setattr(service.socket, "gethostname", lambda: "host\nname.local")
    monkeypatch.setenv("CLAUDE_DECK_INSTANCE_NAME", "Studio\nMac\tProd")
    monkeypatch.setenv("CLAUDE_DECK_INSTANCE_ID", "studio mac\nprod!@#")

    identity = service.get_instance_identity()

    assert identity.hostname == "hostname.local"
    assert identity.name == "StudioMacProd"
    assert identity.id == "studiomacprod"
    assert "\n" not in identity.name
    assert "\t" not in identity.name


def test_instance_identity_invalid_accent_falls_back(monkeypatch):
    service = _service()
    monkeypatch.setattr(service.socket, "gethostname", lambda: "garage-mini")
    monkeypatch.setenv("CLAUDE_DECK_INSTANCE_ACCENT", "neon")

    identity = service.get_instance_identity()

    assert identity.accent == service._accent_from_hostname("garage-mini")


def test_status_response_can_serialize_instance(monkeypatch):
    service = _service()
    monkeypatch.setattr(service.socket, "gethostname", lambda: "studio-mac.local")
    monkeypatch.setenv("CLAUDE_DECK_INSTANCE_NAME", "Studio Mac")

    from app.models.schemas import SystemStatusResponse

    response = SystemStatusResponse(
        claude_code_version=None,
        active_sessions=2,
        providers={},
        instance=service.get_instance_identity(),
    )

    dumped = response.model_dump(mode="json")
    assert dumped["instance"]["name"] == "Studio Mac"
    assert dumped["instance"]["hostname"] == "studio-mac.local"
    assert dumped["instance"]["started_at"]
