"""T-O1: historical hash bytes and migration markers preserve no extra authority."""
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.models.database import GithubAttemptScopeRevision
from app.services.agent_mail_service import agent_mail_service
from app.services.external_agent_mail_service import external_agent_mail_service
from app.services.github_approval_service import github_approval_service
from app.services import instance_identity
from tests.agent_mail.conftest import db  # noqa: F401
from tests.agent_mail.test_api import (
    _continuation_approval_fixture, _continuation_request_body, _stub_continuation_github,
    client, live_slot_session_bindings,  # noqa: F401
)
from .v31_fixture import SemanticSnapshot, copy_database_set


HOSTNAME = "golden-fixture.local"
LEASE_TOKEN = "golden-synthetic-lease"
CAPABILITY_TOKEN = "golden-synthetic-capability"
# Independent literal vectors for the v3.1 constructions, also executed below
# from the source-pinned C0 archive instead of deriving expected values today.
GOLDEN = {
    "instance": "96b146144af4",
    "lease": "1dea58a3697126cd4cf8af5c7219596a4a2f1fc4a15d0b303e15f1aca9e29aa8",
    "capability": "b30ce610621862c71060794a2fa5c5fa638d3d98a6569e845735b7b1d2690a37",
    "external": "b30ce610621862c71060794a2fa5c5fa638d3d98a6569e845735b7b1d2690a37",
}


def test_t_o1_golden_hashes_match_both_pinned_v31_and_current_code(v31_install):
    script = '''
import json
from app.services import instance_identity
from app.services.github_approval_service import github_approval_service
from app.services.agent_mail_service import agent_mail_service
from app.services.external_agent_mail_service import external_agent_mail_service
print(json.dumps({
 "instance": instance_identity._stable_id("golden-fixture.local", None),
 "lease": github_approval_service.lease_token_hash("golden-synthetic-lease"),
 "capability": agent_mail_service.hash_capability_token("golden-synthetic-capability"),
 "external": external_agent_mail_service._hash_token("golden-synthetic-capability"),
}))
'''
    environment = {**os.environ, "PYTHONPATH": str(v31_install.source / "backend"),
                   "DATABASE_URL": "sqlite+aiosqlite:///:memory:"}
    result = subprocess.run([sys.executable, "-c", script], cwd=v31_install.app_dir,
                            env=environment, capture_output=True, text=True, check=True, timeout=30)
    assert json.loads(result.stdout) == GOLDEN
    assert {
        "instance": instance_identity._stable_id(HOSTNAME, None),
        "lease": github_approval_service.lease_token_hash(LEASE_TOKEN),
        "capability": agent_mail_service.hash_capability_token(CAPABILITY_TOKEN),
        "external": external_agent_mail_service._hash_token(CAPABILITY_TOKEN),
    } == GOLDEN
    assert github_approval_service.lease_token_matches(LEASE_TOKEN, GOLDEN["lease"])
    assert not github_approval_service.lease_token_matches(LEASE_TOKEN + "wrong", GOLDEN["lease"])


@pytest.mark.asyncio
async def test_t_o1_existing_compat_marker_prevents_destructive_replay(v31_install, tmp_path, monkeypatch):
    import app.database as database
    copied = copy_database_set(v31_install.database, tmp_path / "copied")
    with sqlite3.connect(copied) as connection:
        assert connection.execute("SELECT 1 FROM deck_compat_migrations WHERE name = ?",
                                  ("p04_explicit_leader_assignment",)).fetchone()
        preset = connection.execute("SELECT preset_id FROM agent_team_slots ORDER BY id LIMIT 1").fetchone()[0]
        # A legitimate post-migration edit: resetting the leader to NULL must
        # survive startup. Replaying the old migration would assign it again.
        connection.execute("UPDATE agent_team_presets SET leader_slot_id = NULL WHERE id = ?", (preset,))
    before = SemanticSnapshot.capture(copied)
    engine = create_async_engine(f"sqlite+aiosqlite:///{copied}")
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database.settings, "database_url", f"sqlite+aiosqlite:///{copied}")
    try:
        for _ in range(2):
            await database.init_db()
            after = SemanticSnapshot.capture(copied)
            before.assert_preserved(after)
            assert after.records["deck_compat_migrations"] == before.records["deck_compat_migrations"]
            assert "synth_city_compat_migrations" not in after.records
            with sqlite3.connect(copied) as connection:
                assert connection.execute("SELECT leader_slot_id FROM agent_team_presets WHERE id = ?", (preset,)).fetchone() == (None,)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("gate", ["valid", "reacquired", "expired", "hold", "unapproved"])
async def test_t_o1_same_hash_never_bypasses_lease_expiry_hold_or_approval(client, db, monkeypatch, gate):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    monkeypatch.setattr(agent_mail_service, "auto_nudge_members", AsyncMock(return_value=[]))
    item, scope, _members, tokens, workspace = await _continuation_approval_fixture(db)
    workspace.lease_token = LEASE_TOKEN
    original_acquisition = workspace.leased_at
    await db.commit()
    _stub_continuation_github(monkeypatch)
    if gate == "hold":
        monkeypatch.setattr(settings, "github_recovery_only_attempt",
                            f"{scope.id}:{item.id}:{item.pr_number}:{item.dispatch_nonce}:{item.dispatch_head_ref}")
    body = _continuation_request_body(item)
    body["lease_token"] = LEASE_TOKEN
    proposed = await client.post(f"/api/v1/agent-teams/github-work-items/{item.id}/continuation-requests",
                                 headers={"X-Synth-City-Session-Token": tokens[1]}, json=body)
    assert proposed.status_code == 200, proposed.text
    revision = await db.get(GithubAttemptScopeRevision, proposed.json()["revision"]["id"])
    assert revision.expected_lease_token_hash == GOLDEN["lease"]
    decision = {"approval_request_id": proposed.json()["approval"]["id"], "work_item_id": item.id,
                "dispatch_nonce": item.dispatch_nonce, "decision": "approved", "reason": "Golden-byte gate fixture"}
    if gate == "hold":
        refused = await client.post("/api/v1/agent-mail/continuation-decisions",
                                    headers={"X-Synth-City-Session-Token": tokens[0]}, json=decision)
        assert refused.status_code == 409
        await db.refresh(revision)
        assert revision.recovery_checkpoint_stage == "decision_hold"
        assert revision.status == "proposed"
        return
    if gate != "unapproved":
        accepted = await client.post("/api/v1/agent-mail/continuation-decisions",
                                     headers={"X-Synth-City-Session-Token": tokens[0]}, json=decision)
        assert accepted.status_code == 200, accepted.text
    if gate == "expired":
        revision.expires_at = datetime.utcnow() - timedelta(seconds=1)
        await db.commit()
    elif gate == "reacquired":
        workspace.lease_token = "new-acquisition-token"
        await db.commit()
    result = await client.post(f"/api/v1/agent-teams/github-work-items/{item.id}/scope-revisions/{revision.revision}/ack",
                               headers={"X-Synth-City-Session-Token": tokens[1]},
                               json={"dispatch_nonce": item.dispatch_nonce, "lease_token": LEASE_TOKEN})
    await db.refresh(revision)
    await db.refresh(workspace)
    assert revision.expected_lease_token_hash == GOLDEN["lease"]
    if gate == "valid":
        assert result.status_code == 200, result.text
        assert revision.status == "active"
        assert workspace.lease_token == LEASE_TOKEN
        assert workspace.leased_at == original_acquisition
    else:
        assert result.status_code in {403, 409}, result.text
        assert revision.status != "active"
