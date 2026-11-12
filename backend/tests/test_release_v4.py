"""C9 release inputs and current product copy are explicit release requirements."""
import hashlib
import json
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[2]


def test_p3_all_application_version_fields_are_4_0_0():
    assert (ROOT / "VERSION").read_text().strip() == "4.0.0"
    package = json.loads((ROOT / "frontend/package.json").read_text())
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text())
    assert package["version"] == lock["version"] == lock["packages"][""]["version"] == "4.0.0"
    project = tomllib.loads((ROOT / "backend/pyproject.toml").read_text())
    uv = tomllib.loads((ROOT / "backend/uv.lock").read_text())
    roots = [entry for entry in uv["package"] if entry.get("source") == {"editable": "."}]
    assert len(roots) == 1
    assert roots[0]["name"] == "albiex-synth-city-backend"
    assert project["project"]["version"] == roots[0]["version"] == "4.0.0"
    from app.config import Settings
    assert Settings().app_version == "4.0.0"
    assert Settings().app_name == "Albiex Synth City"


def test_release_notes_are_the_director_approved_master_prose():
    text = (ROOT / "CHANGELOG.md").read_text()
    match = re.search(r"^## \[4\.0\.0\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
    assert match, "The approved [4.0.0] release section is absent"
    body = match.group(1).strip() + "\n"
    # Pin the approved PR818 prose with its two LINK fill-ins resolved to the
    # v4.0.0 tag (PR855). No placeholder may reach the published release notes.
    assert hashlib.sha256(body.encode()).hexdigest() == "3d4e44dd61ad87f74d8018cb1041ab1eed84275ec9a95eeea6926d5380d7f277"
    assert "](LINK)" not in body
    assert "[migration guide](https://github.com/albiexai/synth-city/blob/v4.0.0/docs/guide/migration-v4.md)" in body
    assert "[compatibility design](https://github.com/albiexai/synth-city/blob/v4.0.0/docs/plans/2026-11-06-rename-synth-city/compatibility.md)" in body
    assert body.startswith("# Albiex Synth City v4.0.0 — formerly Claude Deck\n")


def test_current_system_copy_has_the_full_product_first_mention():
    # Real send/inbox paths are also exercised by test_messaging.
    text = (ROOT / "backend/app/services/agent_mail_service.py").read_text()
    assert 'return "Albiex Synth City", "system", None' in text
    assert 'return "Albiex Synth City or Director (recorded before v3.1)", "legacy", None' in text
    assert '[Albiex Synth City Agent Mail]' in text
