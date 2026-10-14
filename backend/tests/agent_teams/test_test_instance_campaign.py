"""Prove the seeded campaign poll has no production or network effect."""
import asyncio
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import Settings
from app.models.database import AgentTeamPreset, TeamGithubScope
from app.services.agent_team_campaign_service import AgentTeamCampaignService


def seed_backlog(tmp_path):
    data = {"repositories": [
        {"owner": "example", "repo": "readable", "available": True,
         "milestones": [{"number": 7, "title": "Release"}],
         "issues": [{"number": 1, "labels": [{"name": "area:backend"}],
                     "milestone": {"number": 7, "title": "Release"}}]},
        {"owner": "example", "repo": "unavailable", "available": False,
         "milestones": [{"number": 8, "title": "Unavailable"}], "issues": []},
    ]}
    (tmp_path / "campaign-backlog.json").write_text(json.dumps(data))
    return data


@pytest.mark.asyncio
async def test_offline_campaign_reads_fixed_seed_without_http(tmp_path, monkeypatch):
    from app.services.github_offline import OfflineCampaignClient

    seed_backlog(tmp_path)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: pytest.fail("HTTP client opened"))
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("Socket opened"))
    client = OfflineCampaignClient.from_seed(Settings(test_instance=True, test_instance_root=str(tmp_path)))
    assert await client.list_milestones("example", "readable") == [{"number": 7, "title": "Release"}]
    assert (await client.get_issue("example", "readable", 1))["milestone"]["number"] == 7
    issues = await client.list_milestone_issues("example", "readable", 7)
    assert [issue["number"] for issue in issues] == [1]
    issues[0]["number"] = 999
    assert (await client.list_milestone_issues("example", "readable", 7))[0]["number"] == 1
    assert await client.list_milestone_issues("example", "readable", 8) == []
    with pytest.raises(LookupError):
        await client.list_milestones("example", "unavailable")
    with pytest.raises(LookupError):
        await client.list_milestones("other", "readable")


@pytest.mark.parametrize("identity", [False, True])
def test_offline_campaign_client_rejects_production(tmp_path, identity):
    from app.services.github_offline import OfflineCampaignClient

    seed_backlog(tmp_path)
    config = Settings(test_instance=False, test_instance_root=str(tmp_path) if identity else "",
                      test_instance_token="synthetic-test-token" if identity else "")
    with pytest.raises(RuntimeError, match="test instance"):
        OfflineCampaignClient.from_seed(config)


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", [False, True])
async def test_production_cannot_start_campaign_loop(tmp_path, monkeypatch, identity):
    from app.services.github_offline import OfflineCampaignClient
    from app.services.test_instance_campaign_service import TestInstanceCampaignPoller

    config = Settings(test_instance=False, test_instance_root=str(tmp_path) if identity else "",
                      test_instance_token="synthetic-test-token" if identity else "")
    monkeypatch.setattr(OfflineCampaignClient, "from_seed", lambda *a: pytest.fail("Offline client started"))
    monkeypatch.setattr(asyncio, "create_task", lambda *a, **k: pytest.fail("Campaign loop started"))
    poll = TestInstanceCampaignPoller(config=config, campaign=AsyncMock())
    await poll.start()
    await poll.shutdown()
    assert poll._task is None
    assert poll._client is None


@pytest.mark.asyncio
async def test_test_poll_alone_fills_cache_and_expires_after_60_seconds(db, tmp_path, monkeypatch):
    from app.services.test_instance_campaign_service import TestInstanceCampaignPoller

    seed_backlog(tmp_path)
    team = AgentTeamPreset(name="Readable", backlog_milestone="Release", autonomy_enabled=False)
    db.add(team)
    await db.flush()
    db.add(TeamGithubScope(preset_id=team.id, repo_owner="example", repo_name="readable",
                          repo_path=str(tmp_path), base_ref="origin/main", enabled=False))
    await db.commit()
    clock = [0.0]
    campaign = AgentTeamCampaignService(interval_seconds=5, clock=lambda: clock[0])

    @asynccontextmanager
    async def session():
        yield db

    config = Settings(test_instance=True, test_instance_root=str(tmp_path))
    poll = TestInstanceCampaignPoller(config=config, campaign=campaign, session_factory=session)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: pytest.fail("HTTP client opened"))
    assert (await campaign.summary(db, team.id)).backlog_state == "backlog unavailable"
    await poll.start()
    try:
        assert campaign.interval_seconds == 60
        assert (await campaign.summary(db, team.id)).not_started_count == 1
        clock[0] = 59.9
        assert (await campaign.summary(db, team.id)).backlog_state == "available"
        clock[0] = 60
        assert (await campaign.summary(db, team.id)).backlog_state == "backlog unavailable"
        await poll.poll_once()
        assert (await campaign.summary(db, team.id)).backlog_state == "available"
    finally:
        await poll.shutdown()
    assert poll._task is None


@pytest.mark.asyncio
async def test_background_poll_refreshes_and_shutdown_stops_it(db, tmp_path, monkeypatch):
    from app.services.test_instance_campaign_service import TestInstanceCampaignPoller

    seed_backlog(tmp_path)
    team = AgentTeamPreset(name="Readable", backlog_milestone="Release")
    db.add(team)
    await db.flush()
    db.add(TeamGithubScope(preset_id=team.id, repo_owner="example", repo_name="readable",
                          repo_path=str(tmp_path), enabled=False))
    await db.commit()
    campaign = AsyncMock()

    @asynccontextmanager
    async def session():
        yield db

    sleeping, resume = asyncio.Event(), asyncio.Event()
    original_sleep = asyncio.sleep

    async def controlled_sleep(seconds):
        assert seconds == 5
        sleeping.set()
        await resume.wait()
        resume.clear()

    monkeypatch.setattr(asyncio, "sleep", controlled_sleep)
    poll = TestInstanceCampaignPoller(config=Settings(test_instance=True, test_instance_root=str(tmp_path)),
                                      campaign=campaign, session_factory=session)
    await poll.start()
    try:
        assert campaign.refresh_scope.await_count == 1
        await sleeping.wait()
        resume.set()
        for _ in range(100):
            if campaign.refresh_scope.await_count == 2:
                break
            await original_sleep(0.01)
        assert campaign.refresh_scope.await_count == 2
    finally:
        await poll.shutdown()
    resume.set()
    await original_sleep(0)
    assert campaign.refresh_scope.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("contents", [None, "invalid json"])
async def test_missing_seed_is_unavailable_without_network(db, tmp_path, monkeypatch, contents):
    from app.services.test_instance_campaign_service import TestInstanceCampaignPoller

    if contents is not None:
        (tmp_path / "campaign-backlog.json").write_text(contents)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: pytest.fail("HTTP client opened"))
    team = AgentTeamPreset(name="Missing seed", backlog_milestone="Release")
    db.add(team)
    await db.flush()
    db.add(TeamGithubScope(preset_id=team.id, repo_owner="example", repo_name="readable",
                          repo_path=str(tmp_path), enabled=False))
    await db.commit()
    campaign = AgentTeamCampaignService()

    @asynccontextmanager
    async def session():
        yield db

    poll = TestInstanceCampaignPoller(config=Settings(test_instance=True, test_instance_root=str(tmp_path)),
                                      campaign=campaign, session_factory=session)
    await poll.start()
    await poll.shutdown()
    assert (await campaign.summary(db, team.id)).backlog_state == "backlog unavailable"
    assert all(observation.issues is None for observation in campaign._cache.values())


def test_seed_keeps_live_and_deleted_duplicate_teams_and_quiet_idle(tmp_path):
    repo = Path(__file__).resolve().parents[3]
    root = tmp_path / "instance"
    root.mkdir()
    home = root / "home"
    home.mkdir()
    database = root / "seed.db"
    result = subprocess.run(
        [sys.executable, str(repo / "scripts/e2e/seed.py"), "--database", str(database), "--root", str(root)],
        cwd=root, env={"PATH": os.defpath, "HOME": str(home), "PYTHONPATH": str(repo / "backend"),
                       "TEST_INSTANCE": "1", "E2E_NO_PANES": "1",
                       "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60,
    )
    assert result.returncode == 0, "Synthetic seed failed"
    with sqlite3.connect(database) as conn:
        live = conn.execute("SELECT id, name FROM agent_team_presets WHERE name = 'Retired crew'").fetchall()
        assert live == [(4, "Retired crew")]
        history = conn.execute("SELECT context_snapshot FROM factory_audit_events WHERE event_kind = 'team_delete'").fetchall()
        assert any(json.loads(row[0])["original_team_id"] == 3
                   and json.loads(row[0])["team_display_name"] == "Retired crew" for row in history)
        assert conn.execute("SELECT count(*) FROM github_work_items").fetchone()[0] == 5
        assert conn.execute("SELECT backlog_milestone FROM agent_team_presets WHERE id = 2").fetchone()[0] is None
        assert conn.execute("SELECT enabled FROM team_github_scopes WHERE id = 2").fetchone()[0] == 0
        assert conn.execute("SELECT backlog_milestone FROM agent_team_presets WHERE id = 4").fetchone()[0] == "Retired site 1.0"
    data = json.loads((root / "campaign-backlog.json").read_text())
    assert [(row["repo"], row["available"]) for row in data["repositories"]] == [
        ("retired-site", True), ("sample-app", False)]
