"""Semantic progress, rather than polling, drives advisory team idleness."""
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.database import AgentTeamPreset, GithubWorkItem, TeamGithubScope
from app.services.github_team_idle_service import GithubTeamIdleService


@pytest_asyncio.fixture
async def db(tmp_path):
    engine=create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'idle.db'}")
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine,expire_on_commit=False)() as session: yield session
    await engine.dispose()


async def seed(db):
    team=AgentTeamPreset(name='Idle',autonomy_enabled=True);db.add(team);await db.flush()
    scope=TeamGithubScope(preset_id=team.id,repo_owner='example',repo_name='repo',repo_path='/fixture',enabled=True)
    db.add(scope);await db.flush()
    item=GithubWorkItem(scope_id=scope.id,issue_number=839,issue_title='Idle',issue_url='https://github.com/example/repo/issues/839',
        github_updated_at=datetime.utcnow(),dispatch_status='dispatched',dispatch_nonce='fixture-attempt',
        ack_received_at=datetime.utcnow())
    db.add(item);await db.commit();return team,scope,item


@pytest.mark.asyncio
async def test_idle_ignores_polling_and_clears_on_real_state_progress(db,monkeypatch):
    monkeypatch.setattr('app.services.github_team_idle_service.hold_code',lambda:None)
    team,scope,item=await seed(db);svc=GithubTeamIdleService();now=datetime.utcnow()
    assert await svc.observe(db,team.id,now=now)==[]
    item.updated_at=now+timedelta(minutes=40);item.status_note='Still polling';await db.commit()
    result=await svc.observe(db,team.id,now=now+timedelta(minutes=31))
    assert len(result)==1 and result[0]['work_item_id']==item.id
    assert result[0]['last_actor']=='Unknown'
    item.dispatch_status='verifying';await db.commit()
    assert await svc.observe(db,team.id,now=now+timedelta(minutes=32))==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('wait',['human','external','hold','off','unknown'])
async def test_waits_and_incomplete_observation_suppress_idle(db,monkeypatch,wait):
    monkeypatch.setattr('app.services.github_team_idle_service.hold_code',lambda:'hold' if wait=='hold' else None)
    team,scope,item=await seed(db);svc=GithubTeamIdleService();now=datetime.utcnow()
    await svc.observe(db,team.id,now=now)
    if wait=='human':item.dispatch_status='awaiting_human_review'
    if wait=='external':item.dispatch_status='verifying'
    if wait=='off':scope.enabled=False
    await db.commit()
    assert await svc.observe(db,team.id,now=now+timedelta(hours=1),coverage_complete=wait!='unknown')==[]


@pytest.mark.asyncio
async def test_real_mail_clears_idle_and_preserves_authenticated_last_actor(db,monkeypatch):
    from app.models.database import MailMessage,MailTeamMember
    monkeypatch.setattr('app.services.github_team_idle_service.hold_code',lambda:None)
    team,scope,item=await seed(db);svc=GithubTeamIdleService();now=datetime.utcnow()
    team_id,item_id,scope_id=team.id,item.id,scope.id
    member=MailTeamMember(identity_key='idle-actor',repo_id='fixture',repo_path='/fixture',
        repo_name='repo',display_name='Ada',team_preset_id=team_id)
    db.add(member);await db.commit()
    await svc.observe(db,team_id,now=now)
    assert await svc.observe(db,team_id,now=now+timedelta(minutes=31))
    db.add(MailMessage(kind='message',sender_member_id=member.id,recipient_member_id=member.id,
        audience_type='team_preset',audience_id=str(team_id),body_markdown='token=private-fixture',
        payload={'work_item_id':item_id},created_at=now+timedelta(minutes=32)))
    await db.commit()
    assert await svc.observe(db,team_id,now=now+timedelta(minutes=32))==[]
    result=await GithubTeamIdleService().observe(db,team_id,now=now+timedelta(minutes=63))
    assert result[0]['last_actor']=='Ada' and 'private-fixture' not in str(result)
    # Automatic notices and timestamp-only polls do not count as progress.
    db.add(MailMessage(kind='message',audience_type='team_preset',audience_id=str(team_id),
        body_markdown='Automatic observation notice',created_at=now+timedelta(minutes=64)))
    await db.commit()
    assert await svc.observe(db,team_id,now=now+timedelta(minutes=64))


@pytest.mark.asyncio
async def test_check_result_progress_clears_idle_but_observation_time_does_not(db,monkeypatch):
    from app.models.database import GithubRequiredCheckWatch
    from app.models.schemas import FactoryDeliveryPolicy
    from app.services.github_ci_watch_service import _digest
    monkeypatch.setattr('app.services.github_team_idle_service.hold_code',lambda:None)
    team,scope,item=await seed(db);now=datetime.utcnow();svc=GithubTeamIdleService()
    policy=FactoryDeliveryPolicy(required_checks=[{'name':'backend'}])
    item.pr_number=1;item.verification_head_sha='a'*40;item.delivery_policy=policy.model_dump(mode='json')
    watch=GithubRequiredCheckWatch(work_item_id=item.id,dispatch_nonce=item.dispatch_nonce,scope_revision=0,
        pr_number=1,head_sha='a'*40,owner_slot_id=1,policy_digest=_digest(policy),
        checks=[{'name':'backend','app_slug':'github-actions','result':'success'}],
        observed_at=now,changed_at=now,completion_kind='success',completed_at=now)
    item.owner_slot_id=1;db.add(watch);await db.commit()
    await svc.observe(db,team.id,now=now)
    watch.observed_at=now+timedelta(minutes=31);await db.commit()
    assert await svc.observe(db,team.id,now=now+timedelta(minutes=31))
    watch.changed_at=now+timedelta(minutes=32);watch.observed_at=watch.changed_at
    watch.checks=[{'name':'backend','app_slug':'github-actions','result':'failure'}];await db.commit()
    assert await svc.observe(db,team.id,now=now+timedelta(minutes=32))==[]


@pytest.mark.asyncio
async def test_idle_is_visible_through_the_summary_http_response_and_clears(db,monkeypatch):
    from types import SimpleNamespace
    from datetime import timezone
    import httpx
    from app.main import app
    from app.database import get_db
    from app.api.v1 import agent_teams
    from app.models.github_work_progress_schemas import GithubPublicationObservation,GithubWorkProgressResponse
    from app.services.agent_team_summary_service import AgentTeamSummaryService
    from app.models.database import GithubTeamProgress
    team,scope,item=await seed(db);team_id,item_id=team.id,item.id
    class Progress:
        async def summary(self,db,item_id):
            now=datetime.now(timezone.utc)
            return GithubWorkProgressResponse(work_item_id=item_id,dispatch_nonce='fixture-attempt',owner_slot_id=None,
                checked_at=now,valid_until=now+timedelta(seconds=15),phase='implementation',
                next_actor='owner',next_action='Continue.',publication=GithubPublicationObservation(state='unavailable'))
    class Attention:
        async def dispatch_snapshot(self,db,scopes):return {'complete':True,'actions':[]}
        async def summary(self,db,preset_id):
            return {'coverage_complete':True,'actions':[], 'observation_expires_at':datetime.now(timezone.utc)+timedelta(seconds=15)}
    monkeypatch.setattr('app.services.github_team_idle_service.hold_code',lambda:None)
    monkeypatch.setattr('app.services.agent_team_summary_service.hold_code',lambda:None)
    monkeypatch.setattr(agent_teams,'agent_team_summary_service',AgentTeamSummaryService(progress=Progress(),attention=Attention()))
    async def override():yield db
    app.dependency_overrides[get_db]=override
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
            url=f'/api/v1/agent-teams/presets/{team_id}/summary'
            first=await client.get(url);assert first.status_code==200
            saved=await db.get(GithubTeamProgress,team_id)
            assert saved is not None
            saved.last_progress_at=datetime.utcnow()-timedelta(minutes=31);await db.commit()
            second=await client.get(url)
            rows=[a for a in second.json()['attention'] if a['code']=='team_idle']
            assert len(rows)==1 and rows[0]['work_item_id']==item_id and rows[0]['last_actor']=='Unknown'
            assert second.headers['cache-control']=='no-store'
            current=await db.get(GithubWorkItem,item_id);current.retry_count=1;await db.commit()
            third=await client.get(url)
            assert not [a for a in third.json()['attention'] if a['code']=='team_idle']
    finally:app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_unknown_interval_requires_a_new_trusted_baseline(db,monkeypatch):
    monkeypatch.setattr('app.services.github_team_idle_service.hold_code',lambda:None)
    team,scope,item=await seed(db);svc=GithubTeamIdleService();now=datetime.utcnow()
    await svc.observe(db,team.id,now=now)
    assert await svc.observe(db,team.id,now=now+timedelta(minutes=31))
    assert await svc.observe(db,team.id,now=now+timedelta(hours=1),coverage_complete=False)==[]
    assert await svc.observe(db,team.id,now=now+timedelta(hours=2))==[]
    assert await svc.observe(db,team.id,now=now+timedelta(hours=2,minutes=31))


@pytest.mark.asyncio
async def test_supervisor_checkin_exposes_idle_without_clearing_it(db,monkeypatch):
    from datetime import timezone
    from app.models.database import GithubTeamProgress,MailExternalActor
    from app.services.agent_team_supervisor_service import supervisor_checkin
    from app.services.github_operator_attention_service import github_operator_attention_service
    monkeypatch.setattr('app.services.github_team_idle_service.hold_code',lambda:None)
    team,scope,item=await seed(db);team_id,item_id=team.id,item.id
    actor=MailExternalActor(actor_key='idle-supervisor',display_name='Supervisor',kind='external_tool',token_hash='fixture-private')
    db.add(actor);await db.flush();team.supervisor_actor_id=actor.id;await db.commit()
    now=datetime.now(timezone.utc)
    async def human(*args,**kwargs):
        return {'coverage_complete':True,'actions':[], 'observation_expires_at':now+timedelta(seconds=15)}
    monkeypatch.setattr(github_operator_attention_service,'summary',human)
    svc=GithubTeamIdleService();await svc.observe(db,team_id,now=now)
    saved=await db.get(GithubTeamProgress,team_id)
    saved.last_progress_at=(now-timedelta(minutes=31)).replace(tzinfo=None);await db.commit()
    result=await supervisor_checkin(db,actor,team_id,now+timedelta(minutes=10),now=now)
    assert len(result['team_idle'])==1 and result['team_idle'][0]['work_item_id']==item_id
    assert 'fixture-private' not in str(result)
    again=await supervisor_checkin(db,actor,team_id,now+timedelta(minutes=11),now=now+timedelta(minutes=1))
    assert len(again['team_idle'])==1


@pytest.mark.asyncio
async def test_v1_last_actor_is_retained_per_item_after_other_item_mail(db,monkeypatch):
    from app.models.database import MailMessage, MailTeamMember
    monkeypatch.setattr('app.services.github_team_idle_service.hold_code',lambda:None)
    team,scope,item=await seed(db);svc=GithubTeamIdleService();now=datetime.utcnow()
    other=GithubWorkItem(scope_id=scope.id,issue_number=840,issue_title='Other',issue_url='https://github.com/example/repo/issues/840',github_updated_at=now,dispatch_status='dispatched',dispatch_nonce='other-attempt',ack_received_at=now)
    member=MailTeamMember(identity_key='v1-idle-actor',repo_id='fixture',repo_path='/fixture',repo_name='repo',display_name='Ada',team_preset_id=team.id)
    db.add_all([other,member]);await db.commit()
    db.add(MailMessage(kind='message',sender_member_id=member.id,audience_type='team_preset',audience_id=str(team.id),body_markdown='First item progress',payload={'work_item_id':item.id},created_at=now))
    await db.commit()
    await svc.observe(db,team.id,now=now)
    first=await svc.observe(db,team.id,now=now+timedelta(minutes=31))
    assert next(x for x in first if x['work_item_id']==item.id)['last_actor']=='Ada'
    db.add(MailMessage(kind='message',sender_member_id=member.id,audience_type='team_preset',audience_id=str(team.id),body_markdown='Second item progress',payload={'work_item_id':other.id},created_at=now+timedelta(minutes=32)))
    await db.commit()
    await svc.observe(db,team.id,now=now+timedelta(minutes=32))
    later=await svc.observe(db,team.id,now=now+timedelta(minutes=63))
    assert next(x for x in later if x['work_item_id']==item.id)['last_actor']=='Ada'
