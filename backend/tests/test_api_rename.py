"""C3 T-H1/T-H2/T-L1: paired wire names never grant new authority."""
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import get_db
from app.main import app
from app.models.database import GithubWorkItem, MailAgentSession, TeamGithubScope
from app.models.schemas import MailAgentRegisterRequest, TeamGithubScopeCreate
from app.services.agent_mail_service import agent_mail_service
from app.utils import peer_process
from tests.agent_mail.conftest import db  # noqa: F401
from tests.agent_mail.test_capability_tokens import (
    _slot_session, client, slot, team_slots,  # noqa: F401
)
from tests.upgrade.conftest import v31_install  # noqa: F401
from tests.upgrade.v31_fixture import SemanticSnapshot, copy_database_set


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['operator', 'session'])
async def test_t_h1_live_new_header_works_and_old_header_is_refused(client, db, slot, monkeypatch, kind):
    monkeypatch.setattr(settings, 'operator_token', 'synthetic-operator')
    monkeypatch.setattr(settings, 'mail_capability_tokens_required', True)
    monkeypatch.setattr(peer_process, 'pane_is_alive', lambda *_: True)
    session = await _slot_session(db, slot, 'synthetic-session')
    assert session.closed_at is None and session.mailbox_status == 'connected'
    assert session.bound_pane_pid is not None and session.bound_pane_proc_start is not None
    value = f'synthetic-{kind}'
    suffix = kind.title() + '-Token'
    # A live session reads its inbox; operator access uses a protected team read.
    endpoint = '/api/v1/agent-mail/agent/inbox' if kind == 'session' else '/api/v1/agent-mail/team?sync=false'
    good = await client.get(endpoint, headers={f'X-Synth-City-{suffix}': value})
    assert good.status_code == 200
    refused = await client.get(endpoint, headers={f'X-Deck-{suffix}': value})
    assert refused.status_code == 401


@pytest.mark.asyncio
async def test_t_h1_terminal_header_is_paired_and_has_no_old_alias(client, monkeypatch):
    monkeypatch.setattr(settings, 'operator_token', 'synthetic-operator')
    granted = await client.get('/api/v1/agent-bridge/token', params={'target': 'fixture:0.0', 'purpose': 'attachment'})
    assert granted.status_code == 200
    token = granted.json()['token']
    endpoint = '/api/v1/agent-bridge/sessions/fixture:0.0/attachments'
    good = await client.get(endpoint, headers={'X-Synth-City-Terminal-Token': token})
    assert good.status_code == 200
    another = await client.get('/api/v1/agent-bridge/token', params={'target': 'fixture:0.0', 'purpose': 'attachment'})
    fresh_token = another.json()['token']
    refused = await client.get(endpoint, headers={'X-Claude-Deck-Terminal-Token': fresh_token})
    assert refused.status_code == 401
    assert (await client.get(endpoint, headers={'X-Synth-City-Terminal-Token': fresh_token})).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize('state', ['closed', 'offline', 'stale-pane'])
async def test_t_h2_matching_hash_never_revives_an_ineligible_session(client, db, slot, monkeypatch, state):
    monkeypatch.setattr(settings, 'mail_capability_tokens_required', True)
    monkeypatch.setattr(peer_process, 'pane_is_alive', lambda *_: state != 'stale-pane')
    session = await _slot_session(db, slot, 'synthetic-old')
    if state == 'closed':
        session.closed_at = datetime.utcnow()
    elif state == 'offline':
        session.mailbox_status = 'offline'
    await db.commit()
    hashed = session.capability_token_hash
    response = await client.get('/api/v1/agent-mail/agent/inbox', headers={'X-Synth-City-Session-Token': 'synthetic-old'})
    assert response.status_code == 401
    assert response.json()['detail'] == ('session_token_closed' if state == 'closed' else 'session_token_stale')
    await db.refresh(session)
    assert session.capability_token_hash == hashed
    if state == 'closed':
        assert session.closed_at is not None


@pytest.mark.asyncio
async def test_t_h2_stop_then_fresh_registration_gets_new_row_key_and_token(client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'mail_capability_tokens_required', True)
    monkeypatch.setattr(agent_mail_service, 'auto_nudge_members', AsyncMock(return_value=[]))
    request = MailAgentRegisterRequest(source='mcp', provider='pi-cli', cwd=str(tmp_path), session_key='synthetic-before-stop')
    member, previous = await agent_mail_service.register_session(db, request)
    token = await agent_mail_service.ensure_capability_token(db, previous)
    old_id, old_hash = previous.id, previous.capability_token_hash
    stopped = await client.post('/api/v1/agent-mail/agent/close', headers={'X-Synth-City-Session-Token': token})
    assert stopped.status_code == 200 and stopped.json()['closed'] is True
    relaunched = await client.post('/api/v1/agent-mail/agent/register', json=request.model_copy(update={'session_key': 'synthetic-relaunched'}).model_dump())
    assert relaunched.status_code == 200
    new_token = relaunched.json()['capability_token']
    assert new_token != token
    current = await db.scalar(select(MailAgentSession).where(MailAgentSession.session_key == 'synthetic-relaunched'))
    assert current.id != old_id and current.member_id == member.id
    assert current.closed_at is None
    await db.refresh(previous)
    assert previous.capability_token_hash == old_hash and previous.closed_at is not None
    old = await client.get('/api/v1/agent-mail/agent/inbox', headers={'X-Synth-City-Session-Token': token})
    assert old.status_code == 401 and old.json()['detail'] == 'session_token_closed'
    assert (await client.get('/api/v1/agent-mail/agent/inbox', headers={'X-Synth-City-Session-Token': new_token})).status_code == 200


@pytest.mark.asyncio
async def test_t_l1_only_new_scopes_receive_new_orm_defaults(db):
    from app.models.database import AgentTeamPreset
    preset = AgentTeamPreset(name='Label preservation')
    db.add(preset)
    await db.flush()
    existing = TeamGithubScope(preset_id=preset.id, repo_owner='fixture', repo_name='old', repo_path='/synthetic/old',
                               dispatch_label='claude-deck-ready', design_label='claude-deck-design')
    db.add(existing)
    await db.commit()
    new = TeamGithubScope(preset_id=preset.id, repo_owner='fixture', repo_name='new', repo_path='/synthetic/new')
    db.add(new)
    await db.commit()
    await db.refresh(existing)
    assert (existing.dispatch_label, existing.design_label) == ('claude-deck-ready', 'claude-deck-design')
    assert (new.dispatch_label, new.design_label) == ('albiex-synth-city-ready', 'albiex-synth-city-design')
    from app.services.github_watcher_service import github_watcher_service
    from tests.agent_teams.test_github_watcher_service import _FakeClient, _issue
    class StoredLabelClient(_FakeClient):
        async def list_issues_with_label(self, owner, repo, label):
            assert label == 'claude-deck-ready'
            return [_issue(818, ['claude-deck-ready', 'claude-deck-design'])]
    await github_watcher_service.poll_scope(db, existing, StoredLabelClient())
    admitted = await db.scalar(select(GithubWorkItem).where(GithubWorkItem.scope_id == existing.id))
    assert admitted.issue_number == 818 and admitted.issue_type == 'design'
    assert admitted.dispatch_status == 'pending'


def test_t_h1_every_runtime_header_declaration_has_only_new_names():
    app.openapi_schema = None
    names = {p['name'].lower() for path in app.openapi()['paths'].values() for operation in path.values()
             if isinstance(operation, dict) for p in operation.get('parameters', []) if p.get('in') == 'header'}
    assert {'x-synth-city-operator-token', 'x-synth-city-session-token', 'x-synth-city-terminal-token'} <= names
    assert not {'x-deck-operator-token', 'x-deck-session-token', 'x-claude-deck-terminal-token'} & names


def test_t_h1_shim_sends_new_session_header(monkeypatch):
    spec = importlib.util.spec_from_file_location('c3_shim', Path(__file__).parents[1] / 'mcp_shim/agent_mail_server.py')
    shim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shim)
    shim._state['capability_token'] = 'synthetic-session'
    calls = []
    def request(method, url, **kwargs):
        calls.append(kwargs['headers'])
        return httpx.Response(200, json={'members': []}, request=httpx.Request(method, url))
    monkeypatch.setattr(shim.httpx, 'request', request)
    assert shim._request('GET', '/team')['ok']
    assert calls == [{'X-Synth-City-Session-Token': 'synthetic-session'}]


def test_t_l1_api_defaults_and_new_git_identity_and_emitted_markers():
    from app.services.github_workspace_service import GithubWorkspaceService
    from app.services.agent_mail_service import INBOX_CHECK_PROMPT
    model = TeamGithubScopeCreate(repo_owner='fixture', repo_name='new', repo_path='/synthetic/new')
    assert (model.dispatch_label, model.design_label) == ('albiex-synth-city-ready', 'albiex-synth-city-design')
    assert GithubWorkspaceService.slot_email('Builder', 12) == 'builder+slot12@synth-city.local'
    assert GithubWorkspaceService.slot_name('Builder') == 'Builder (Synth City agent)'
    assert INBOX_CHECK_PROMPT.startswith('Albiex Synth City Agent Mail: call `synth_city_check_inbox')


@pytest.mark.asyncio
async def test_t_h2_pinned_v31_stop_then_current_fresh_session_preserves_history(v31_install, tmp_path, monkeypatch):
    """C3's auth segment uses the copied C0 fixture; C4 owns physical data movement."""
    import app.database as database
    copied = copy_database_set(v31_install.database, tmp_path / 'copied')
    script = '''
import asyncio, json
import httpx
from app.main import app
from app.database import init_db
from app.services.agent_mail_service import agent_mail_service
from unittest.mock import AsyncMock
async def main():
    await init_db()
    agent_mail_service.auto_nudge_members = AsyncMock(return_value=[])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        body={'source':'mcp','provider':'pi-cli','cwd':__import__('sys').argv[1],'session_key':'c3-v31-before-stop'}
        registered=await client.post('/api/v1/agent-mail/agent/register',json=body)
        assert registered.status_code==200, registered.text
        token=registered.json()['capability_token']
        history=await client.post('/api/v1/agent-mail/messages',headers={'X-Deck-Session-Token':token},
            json={'recipient_member_id':int(__import__('sys').argv[2]),'subject':'C3 old session history','body_markdown':'Retain C3 session history.'})
        assert history.status_code==200, history.text
        closed=await client.post('/api/v1/agent-mail/agent/close',headers={'X-Deck-Session-Token':token})
        assert closed.status_code==200 and closed.json()['closed']
        print(json.dumps({'token':token,'body':body}))
asyncio.run(main())
'''
    environment = {'PATH': os.environ['PATH'], 'HOME': str(tmp_path),
                   'PYTHONPATH': str(v31_install.source / 'backend'),
                   'DATABASE_URL': f'sqlite+aiosqlite:///{copied}'}
    recipient = min(row['id'] for row in v31_install.before.records['mail_team_members'].values())
    output = subprocess.run([sys.executable, '-c', script, str(v31_install.app_dir / 'repository'), str(recipient)],
                            cwd=v31_install.app_dir, env=environment, capture_output=True, text=True, timeout=45)
    assert output.returncode == 0, output.stderr
    previous = json.loads(output.stdout)
    before = SemanticSnapshot.capture(copied)
    engine = create_async_engine(f'sqlite+aiosqlite:///{copied}')
    monkeypatch.setattr(database, 'engine', engine)
    monkeypatch.setattr(database.settings, 'database_url', f'sqlite+aiosqlite:///{copied}')
    monkeypatch.setattr(settings, 'mail_capability_tokens_required', True)
    monkeypatch.setattr(agent_mail_service, 'auto_nudge_members', AsyncMock(return_value=[]))
    try:
        await database.init_db()
        before.assert_preserved(SemanticSnapshot.capture(copied))
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            async def override():
                yield session
            app.dependency_overrides[get_db] = override
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                endpoint = '/api/v1/agent-mail/agent/inbox'
                old = await client.get(endpoint, headers={'X-Synth-City-Session-Token': previous['token']})
                assert old.status_code == 401 and old.json()['detail'] == 'session_token_closed'
                old_row = await session.scalar(select(MailAgentSession).where(MailAgentSession.session_key == 'c3-v31-before-stop'))
                old_id, old_hash = old_row.id, old_row.capability_token_hash
                fresh = await client.post('/api/v1/agent-mail/agent/register', json={**previous['body'], 'session_key': 'c3-current-relaunch'})
                assert fresh.status_code == 200
                token = fresh.json()['capability_token']
                assert token != previous['token']
                new_row = await session.scalar(select(MailAgentSession).where(MailAgentSession.session_key == 'c3-current-relaunch'))
                assert new_row.id != old_id and new_row.closed_at is None and new_row.member_id == old_row.member_id
                assert (await client.get(endpoint, headers={'X-Synth-City-Session-Token': token})).status_code == 200
                history = await client.get('/api/v1/agent-mail/messages', headers={'X-Synth-City-Session-Token': token})
                assert history.status_code == 200 and 'Retain C3 session history.' in json.dumps(history.json())
                await session.refresh(old_row)
                assert old_row.closed_at is not None and old_row.capability_token_hash == old_hash
                after = SemanticSnapshot.capture(copied)
                # Registration legitimately refreshes the member's updated_at.
                # Upgrade preservation above is checked before this new activity;
                # history and the stopped credential row must still be identical.
                for table in ('mail_messages', 'mail_receipts'):
                    assert after.records[table] == before.records[table]
                for identity, row in before.records['mail_agent_sessions'].items():
                    if row['id'] == old_id:
                        assert after.records['mail_agent_sessions'][identity] == row
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
