"""Keep test imports and each test independent of installation settings."""
import copy
import atexit
import os
import tempfile
from unittest.mock import patch

import pytest
from pydantic_settings import BaseSettings


# A memory database does not suppress independent HOME-resource conversion.
# Establish isolation before config or child conftests can import application code.
_original_home = os.environ.get('HOME')
_session_home = tempfile.TemporaryDirectory(prefix='synth-city-test-home-')
os.environ['HOME'] = _session_home.name


def _restore_home():
    if _original_home is None:
        os.environ.pop('HOME', None)
    else:
        os.environ['HOME'] = _original_home
    _session_home.cleanup()


atexit.register(_restore_home)


_settings_init = BaseSettings.__init__


def _isolated_settings_init(self, **values):
    defaults = {
        name: copy.deepcopy(field.get_default(call_default_factory=True))
        for name, field in type(self).model_fields.items()
    }
    defaults["database_url"] = "sqlite+aiosqlite:///:memory:"
    # Init values take precedence over process values. Never open a local .env.
    _settings_init(self, **(defaults | values | {"_env_file": None}))


# app.config constructs its shared instance during import. Isolate that first
# construction before child conftests import the application and its database.
with patch.object(BaseSettings, "__init__", _isolated_settings_init):
    from app.config import Settings, settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    names = {name.casefold() for name in Settings.model_fields}
    for name in tuple(os.environ):
        if name.casefold() in names:
            monkeypatch.delenv(name)
    monkeypatch.setattr(Settings, "__init__", _isolated_settings_init)
    defaults = Settings()
    for name in Settings.model_fields:
        monkeypatch.setattr(settings, name, copy.deepcopy(getattr(defaults, name)))
