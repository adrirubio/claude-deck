"""JSON timestamps name UTC without changing stored or Python values."""
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Response

from app.models.github_work_progress_schemas import GithubPublicationObservation, GithubWorkProgressResponse
from app.models.provider_operations_schemas import CredentialReadiness
from app.models.schemas import AgentTeamPresetResponse, MailMessageResponse, ProjectResponse


MOMENT = datetime(2026, 10, 9, 6, 20, 53, 83886)


def _parsed(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _progress_response(stamp):
    return GithubWorkProgressResponse(work_item_id=1, dispatch_nonce=None, owner_slot_id=None,
                                      checked_at=stamp, valid_until=stamp, phase="implementation",
                                      next_actor="owner", next_action="Continue",
                                      publication=GithubPublicationObservation(state="unavailable", observed_at=stamp))


@pytest.mark.parametrize("stamp", [
    MOMENT,
    MOMENT.replace(tzinfo=timezone.utc),
    (MOMENT + timedelta(hours=2)).replace(tzinfo=timezone(timedelta(hours=2))),
])
@pytest.mark.parametrize("make,field", [
    (lambda stamp: AgentTeamPresetResponse(id=1, name="UTC", created_at=stamp, updated_at=stamp), "updated_at"),
    (lambda stamp: MailMessageResponse(id=1, kind="message", sender_name="Fixture", body_markdown="UTC", created_at=stamp), "created_at"),
    (_progress_response, "checked_at"),
    (lambda stamp: CredentialReadiness(observed_at=stamp), "observed_at"),
])
def test_response_json_names_utc_and_preserves_python_values(make, field, stamp):
    model = make(stamp)
    before = model.model_dump(mode="python")
    serialized = model.model_dump(mode="json")
    parsed = _parsed(serialized[field])
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)
    assert parsed == MOMENT.replace(tzinfo=timezone.utc)
    assert model.model_dump(mode="python") == before
    assert getattr(model, field) == stamp


def test_progress_api_copy_names_utc_and_preserves_stored_snapshot_json():
    response = _progress_response(MOMENT)
    publication = response.publication
    stored = publication.model_dump_json()
    assert json.loads(stored)["observed_at"] == MOMENT.isoformat()
    data = response.model_dump(mode="json")
    assert _parsed(data["publication"]["observed_at"]) == MOMENT.replace(tzinfo=timezone.utc)
    assert publication.model_dump_json() == stored
    assert publication.observed_at.tzinfo is None


def test_nested_json_datetimes_name_utc_without_changing_text_or_input():
    payload = {"observed": MOMENT, "items": [MOMENT], "text": MOMENT.isoformat()}
    model = MailMessageResponse(id=1, kind="message", sender_name="Fixture",
                                body_markdown=MOMENT.isoformat(), created_at=MOMENT,
                                payload=payload)
    data = model.model_dump(mode="json")
    assert _parsed(data["payload"]["observed"]).tzinfo is not None
    assert _parsed(data["payload"]["items"][0]).tzinfo is not None
    assert data["payload"]["text"] == MOMENT.isoformat()
    assert data["body_markdown"] == MOMENT.isoformat()
    assert payload["observed"].tzinfo is None
    assert model.payload["observed"].tzinfo is None


@pytest.mark.parametrize("stamp", [MOMENT.isoformat(), MOMENT.replace(tzinfo=timezone.utc).isoformat()])
def test_legacy_string_timestamp_fields_name_utc_only_in_json(stamp):
    model = ProjectResponse(id=1, name=MOMENT.isoformat(), path="/tmp/fixture", is_active=False,
                            last_accessed=stamp, created_at=stamp)
    data = model.model_dump(mode="json")
    assert _parsed(data["created_at"]) == MOMENT.replace(tzinfo=timezone.utc)
    assert _parsed(data["last_accessed"]) == MOMENT.replace(tzinfo=timezone.utc)
    assert data["name"] == MOMENT.isoformat()
    assert model.model_dump(mode="python")["created_at"] == stamp


@pytest.mark.asyncio
async def test_observation_pause_response_names_utc_and_keeps_nullable_times(monkeypatch):
    from app.api.v1 import factory_maintenance as routes

    record = SimpleNamespace(id=1, status="paused", deadline=MOMENT, paused_at=MOMENT,
                             resume_deadline=MOMENT, resumed_at=None, notice_status="sent")
    db = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [record])))
    monkeypatch.setattr(routes, "context", AsyncMock(return_value=(SimpleNamespace(id=2, dispatch_status="dispatched"), None)))
    data = await routes.observation_pauses(1, 2, Response(), _operator=None, db=db)
    pause = data["pauses"][0]
    for field in ("wait_deadline", "paused_at", "resume_deadline"):
        assert _parsed(pause[field]) == MOMENT.replace(tzinfo=timezone.utc)
    assert pause["resumed_at"] is None
    assert record.paused_at == MOMENT
    assert record.status == "paused"


@pytest.mark.asyncio
async def test_source_import_response_names_utc_without_changing_record(monkeypatch):
    from app.api.v1 import factory_maintenance as routes

    row = SimpleNamespace(id=1, operation_id="fixture", scope_revision_id=1,
                          accepted_repository="fixture/repo", accepted_pull_number=1,
                          accepted_source_sha="a" * 40, accepted_merge_sha="b" * 40,
                          observed_head_sha="c" * 40, path_snapshots={"fixture": {}}, created_at=MOMENT)
    db = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [row])))
    monkeypatch.setattr(routes, "context", AsyncMock(return_value=(SimpleNamespace(id=2), None)))
    data = await routes.accepted_source_imports(1, 2, Response(), _operator=None, db=db)
    assert _parsed(data["imports"][0]["created_at"]) == MOMENT.replace(tzinfo=timezone.utc)
    assert row.created_at == MOMENT


@pytest.mark.asyncio
async def test_backup_api_copy_names_utc_and_preserves_archive_json(monkeypatch):
    from app.api.v1 import backup as routes
    from app.models.schemas import BackupManifest, BackupManifestContents

    manifest = BackupManifest(created_at=MOMENT.isoformat(), platform="linux", scope="user",
                              contents=BackupManifestContents(provider_inventory={"observed": MOMENT}))
    stored = manifest.model_dump_json()
    assert json.loads(stored)["created_at"] == MOMENT.isoformat()
    assert json.loads(stored)["contents"]["provider_inventory"]["observed"] == MOMENT.isoformat()
    service = SimpleNamespace(get_backup=AsyncMock(return_value=SimpleNamespace(file_path="fixture.zip")),
                              get_manifest_from_backup=lambda _: manifest)
    monkeypatch.setattr(routes, "BackupService", lambda _: service)
    response = await routes.get_backup_manifest(1, db=None)
    assert _parsed(response.created_at) == MOMENT.replace(tzinfo=timezone.utc)
    assert response is not manifest
    assert manifest.model_dump_json() == stored
    assert manifest.created_at == MOMENT.isoformat()
    assert response.contents.provider_inventory["observed"] == MOMENT.replace(tzinfo=timezone.utc)
    assert manifest.contents.provider_inventory["observed"].tzinfo is None
