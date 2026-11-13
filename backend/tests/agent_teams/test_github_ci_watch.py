"""Required-check completion is durable and bound to explicit identities."""
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
import app.models.github_work_progress  # Register snapshot tables before isolated fixture create_all.
from app.models.database import (AgentTeamPreset, AgentTeamSlot, GithubWorkItem, GithubWorkspace,
    MailAgentSession, MailMessage, MailTeamMember, TeamGithubScope)
from app.models.schemas import FactoryDeliveryPolicy
from app.services.github_ci_watch_service import GithubCIWatchService

HEAD = 'a' * 40
OTHER = 'b' * 40


@pytest_asyncio.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'watch.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        session.info['maker'] = maker
        yield session
    await engine.dispose()


async def seed(db):
    team = AgentTeamPreset(name='Checks', autonomy_enabled=True)
    db.add(team); await db.flush()
    scope = TeamGithubScope(preset_id=team.id, repo_owner='example', repo_name='repo',
        repo_path='/fixture', enabled=True)
    db.add(scope); await db.flush()
    members = []
    for n, name in enumerate(('Leader', 'Owner', 'Reviewer')):
        slot = AgentTeamSlot(preset_id=team.id, position=n, display_name=name,
            provider='codex-cli', repo_id='fixture', repo_path='/fixture', repo_name='repo', enabled=True)
        db.add(slot); await db.flush()
        member = MailTeamMember(identity_key=f'fixture:{n}', repo_id='fixture', repo_path='/fixture',
            repo_name='repo', display_name=name, participant_kind='team_slot',
            team_preset_id=team.id, team_slot_id=slot.id)
        db.add(member); await db.flush(); members.append(member)
        db.add(MailAgentSession(member_id=member.id, source='mcp', provider='codex-cli',
            session_key=f'fixture-session:{n}', team_preset_id=team.id, team_slot_id=slot.id,
            capability_token_hash=f'fixture-hash:{n}', bound_pane_pid=100+member.id,
            bound_pane_proc_start='fixture-start', mailbox_status='connected', wake_enabled=True))
    team.leader_slot_id = members[0].team_slot_id
    policy = FactoryDeliveryPolicy(required_checks=[{'name':'backend', 'app_slug':'github-actions'},
        {'name':'e2e', 'app_slug':'github-actions'}])
    item = GithubWorkItem(scope_id=scope.id, issue_number=839, issue_title='Watch',
        issue_url='https://github.com/example/repo/issues/839', github_updated_at=datetime.utcnow(),
        dispatch_status='verifying', dispatch_nonce='fixture-attempt', owner_slot_id=members[1].team_slot_id,
        pr_number=874, verification_head_sha=HEAD, dispatch_head_ref='fixture/839',
        ack_received_at=datetime.utcnow(), delivery_policy=policy.model_dump(mode='json'))
    db.add(item); await db.flush()
    db.add(GithubWorkspace(scope_id=scope.id,path='/fixture/work', leased_item_id=item.id,
        lease_token='fixture-private',leased_at=datetime.utcnow()))
    await db.commit()
    return team, scope, item, members, policy


def checks(first='success', second='in_progress', *, head=HEAD):
    return [{'name':name, 'head_sha':head, 'app':{'slug':'github-actions'},
        'status':'in_progress' if result=='in_progress' else 'completed',
        'conclusion':None if result=='in_progress' else result}
        for name,result in (('backend',first),('e2e',second))]


def service(monkeypatch, wakes):
    from app.services.agent_mail_service import agent_mail_service
    from app.utils import peer_process
    from types import SimpleNamespace
    monkeypatch.setattr('app.services.github_ci_watch_service.hold_code', lambda: None)
    monkeypatch.setattr(peer_process, 'pane_is_alive', lambda *args: True)
    async def wake(db, ids, **kwargs):
        wakes.extend(sorted(ids)); return [{'member_id':i, 'method':'fixture'} for i in ids]
    async def guarded_wake(db, member_id, now, *, delivery_guard, transport_guard, **kwargs):
        from app.services.agent_mail_service import MailWakeError
        if not await delivery_guard() or not transport_guard():
            raise MailWakeError('wake_session_mismatch')
        wakes.append(member_id); return {'method':'fixture'}
    async def sync(db): pass
    async def pane(db, member_id, now):
        member=await db.get(MailTeamMember,member_id)
        return SimpleNamespace(id=1000+member_id, pane_id=f'%{member_id}', pid=100+member_id,
            tmux_target=f'fixture:{member_id}', provider='codex-cli',
            team_slot_id=member.team_slot_id, team_preset_id=member.team_preset_id)
    async def read_pull(self, scope, number):
        return {'number':874,'merged_at':None,'state':'open','head':{'sha':HEAD,'ref':'fixture/839','repo':{'full_name':'example/repo'}}}
    monkeypatch.setattr(GithubCIWatchService, '_read_pull', read_pull)
    monkeypatch.setattr(agent_mail_service, 'auto_nudge_members', wake)
    monkeypatch.setattr(agent_mail_service, '_wake_member', guarded_wake)
    monkeypatch.setattr(agent_mail_service, 'sync_observed_sessions', sync)
    monkeypatch.setattr(agent_mail_service, '_nudge_session_for_member', pane)
    return GithubCIWatchService()


async def bind(svc, db, item, members, **kwargs):
    return await svc.register(db, work_item_id=item.id, dispatch_nonce=item.dispatch_nonce,
        scope_revision=item.active_scope_revision, head_sha=HEAD, reviewer_member_id=members[2].id,
        actor_member_id=members[0].id, **kwargs)


@pytest.mark.asyncio
async def test_green_wakes_explicit_reviewer_and_leader_once_across_restart(db, monkeypatch):
    _, scope, item, members, policy = await seed(db)
    wakes=[]; svc=service(monkeypatch,wakes)
    await bind(svc,db,item,members)
    await svc.observe(db,scope,item,HEAD,checks(),policy)
    assert wakes == []
    await svc.observe(db,scope,item,HEAD,checks(second='success'),policy)
    await GithubCIWatchService().observe(db,scope,item,HEAD,checks(second='success'),policy)
    mail=(await db.execute(select(MailMessage))).scalars().all()
    assert sorted(m.recipient_member_id for m in mail)==[members[0].id,members[2].id]
    assert sorted(wakes)==[members[0].id,members[2].id]
    assert all(HEAD in m.body_markdown and 'e2e: success' in m.body_markdown for m in mail)


@pytest.mark.asyncio
async def test_failure_names_check_and_notifies_owner_leader_without_duplicate(db,monkeypatch):
    _,scope,item,members,policy=await seed(db)
    wakes=[];svc=service(monkeypatch,wakes)
    assert await svc.observe(db,scope,item,HEAD,checks(first='failure'),policy)
    assert await svc.observe(db,scope,item,HEAD,checks(first='failure'),policy)
    rows=(await db.execute(select(MailMessage))).scalars().all()
    assert sorted(m.recipient_member_id for m in rows)==[members[0].id,members[1].id]
    assert all('backend: failure' in m.body_markdown for m in rows)
    assert sorted(wakes)==[members[0].id,members[1].id]


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['wrong_head','wrong_app','missing','ambiguous'])
async def test_incomplete_or_mismatched_required_evidence_does_not_emit(db,monkeypatch,change):
    _,scope,item,members,policy=await seed(db);wakes=[];svc=service(monkeypatch,wakes)
    await bind(svc,db,item,members)
    rows=checks(second='success')
    if change=='wrong_head': rows[1]['head_sha']=OTHER
    if change=='wrong_app': rows[1]['app']['slug']='other'
    if change=='missing': rows.pop()
    if change=='ambiguous': rows.append(dict(rows[1]))
    await svc.observe(db,scope,item,HEAD,rows,policy)
    assert wakes==[] and (await db.execute(select(MailMessage))).scalars().all()==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid',['owner','nonleader','disabled','nonce','revision','head','hold'])
async def test_registration_rejects_wrong_identity_attempt_or_head(db,monkeypatch,invalid):
    team,scope,item,members,policy=await seed(db);svc=service(monkeypatch,[])
    args=dict(work_item_id=item.id,dispatch_nonce=item.dispatch_nonce,scope_revision=0,head_sha=HEAD,
        reviewer_member_id=members[2].id,actor_member_id=members[0].id)
    if invalid=='owner':args['reviewer_member_id']=members[1].id
    if invalid=='nonleader':args['actor_member_id']=members[1].id
    if invalid=='disabled':
        (await db.get(AgentTeamSlot,members[2].team_slot_id)).enabled=False;await db.commit()
    if invalid=='nonce':args['dispatch_nonce']='other-attempt'
    if invalid=='revision':args['scope_revision']=1
    if invalid=='head':args['head_sha']=OTHER
    if invalid=='hold':monkeypatch.setattr('app.services.github_ci_watch_service.hold_code',lambda:'hold')
    with pytest.raises((ValueError,PermissionError)):await svc.register(db,**args)
    assert (await db.execute(select(MailMessage))).scalars().all()==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['owner','nonce','head','off','reviewer','pause'])
async def test_registration_rechecks_after_remote_head_await(db,monkeypatch,change):
    from app.models.database import GithubOwnerObservationPause
    team,scope,item,members,policy=await seed(db);svc=service(monkeypatch,[])
    async def changed(scope,pr):
        if change=='owner':item.owner_slot_id=members[2].team_slot_id
        if change=='nonce':item.dispatch_nonce='other'
        if change=='head':item.verification_head_sha=OTHER
        if change=='off':team.autonomy_enabled=False
        if change=='reviewer':(await db.get(AgentTeamSlot,members[2].team_slot_id)).enabled=False
        if change=='pause':db.add(GithubOwnerObservationPause(work_item_id=item.id,wait_key='pause',
            authority_sha256='fixture',status='paused',deadline=datetime.utcnow()))
        await db.commit()
        return {'number':874,'merged_at':None,'state':'open','head':{'sha':HEAD,'ref':'fixture/839','repo':{'full_name':'example/repo'}}}
    monkeypatch.setattr(svc,'_read_pull',changed)
    with pytest.raises((ValueError,PermissionError)):await bind(svc,db,item,members)
    assert (await db.execute(select(MailMessage))).scalars().all()==[]


@pytest.mark.asyncio
async def test_late_reviewer_receives_existing_completion_once_and_clear_stops_assignment(db,monkeypatch):
    _,scope,item,members,policy=await seed(db);wakes=[];svc=service(monkeypatch,wakes)
    await svc.observe(db,scope,item,HEAD,checks(second='success'),policy)
    assert wakes==[members[0].id]
    await bind(svc,db,item,members)
    await bind(svc,db,item,members)
    assert sorted(wakes)==[members[0].id,members[2].id]
    await svc.register(db,work_item_id=item.id,dispatch_nonce=item.dispatch_nonce,scope_revision=0,
        head_sha=HEAD,reviewer_member_id=None,actor_member_id=members[0].id)
    assert len((await db.execute(select(MailMessage))).scalars().all())==2


@pytest.mark.asyncio
async def test_wake_crash_is_unconfirmed_after_new_service_and_session(db,monkeypatch):
    from app.models.database import GithubRequiredCheckRecipient
    from app.services.agent_mail_service import agent_mail_service
    class InterruptedWake(BaseException):pass
    _,scope,item,members,policy=await seed(db);wakes=[];svc=service(monkeypatch,wakes)
    await bind(svc,db,item,members)
    item_id,scope_id=item.id,scope.id
    async def interrupted(db,member_id,now,**kwargs):
        wakes.append(member_id);raise InterruptedWake()
    monkeypatch.setattr(agent_mail_service,'_wake_member',interrupted)
    with pytest.raises(InterruptedWake):
        await svc.observe(db,scope,item,HEAD,checks(second='success'),policy)
    await db.rollback()  # A stopped process closes its in-flight post-claim transaction.
    service(monkeypatch,wakes)
    maker=db.info['maker']
    async with maker() as resumed:
        current_item=await resumed.get(GithubWorkItem,item_id)
        current_scope=await resumed.get(TeamGithubScope,scope_id)
        await GithubCIWatchService().observe(resumed,current_scope,current_item,HEAD,checks(second='success'),policy)
        view=await GithubCIWatchService().view(resumed,current_item)
        states=(await resumed.execute(select(GithubRequiredCheckRecipient.wake_state))).scalars().all()
    await db.refresh(members[0]);await db.refresh(members[2])
    assert sorted(wakes)==[members[0].id,members[2].id]
    assert sorted(states)==['claimed','confirmed']
    assert view['state']=='no_next_actor'


@pytest.mark.asyncio
async def test_concurrent_poll_sessions_share_one_recipient_claim(db,monkeypatch):
    import asyncio
    _,scope,item,members,policy=await seed(db);wakes=[];svc=service(monkeypatch,wakes)
    await bind(svc,db,item,members)
    maker=db.info['maker'];item_id,scope_id=item.id,scope.id
    async def poll():
        async with maker() as session:
            i=await session.get(GithubWorkItem,item_id);s=await session.get(TeamGithubScope,scope_id)
            await GithubCIWatchService().observe(session,s,i,HEAD,checks(second='success'),policy)
    await asyncio.gather(poll(),poll())
    await poll()
    assert sorted(wakes)==[members[0].id,members[2].id]
    assert len((await db.execute(select(MailMessage))).scalars().all())==2


@pytest.mark.asyncio
async def test_same_head_rerun_updates_view_without_new_completion_event(db,monkeypatch):
    _,scope,item,members,policy=await seed(db);wakes=[];svc=service(monkeypatch,wakes)
    await bind(svc,db,item,members)
    await svc.observe(db,scope,item,HEAD,checks(first='failure'),policy)
    await svc.observe(db,scope,item,HEAD,checks(second='success'),policy)
    view=await svc.view(db,item)
    assert view['result']=='success' and view['completed']==2
    assert sorted(wakes)==[members[0].id,members[1].id]
    assert len((await db.execute(select(MailMessage))).scalars().all())==2


@pytest.mark.asyncio
async def test_hold_during_mail_bundle_rolls_back_before_commit(db,monkeypatch):
    from app.services.agent_mail_service import agent_mail_service
    _,scope,item,members,policy=await seed(db);wakes=[];svc=service(monkeypatch,wakes)
    await bind(svc,db,item,members)
    original=agent_mail_service.send_message
    async def pause(*args,**kwargs):
        result=await original(*args,**kwargs)
        monkeypatch.setattr('app.services.github_ci_watch_service.hold_code',lambda:'hold')
        return result
    monkeypatch.setattr(agent_mail_service,'send_message',pause)
    await svc.observe(db,scope,item,HEAD,checks(second='success'),policy)
    assert (await db.execute(select(MailMessage))).scalars().all()==[]
    assert wakes==[]


@pytest.mark.asyncio
async def test_monitor_failure_accounts_retry_once_and_uses_single_owner_notice(db,monkeypatch):
    from app.services.github_verification_service import GithubVerificationService
    _,scope,item,members,policy=await seed(db);wakes=[];service(monkeypatch,wakes)
    verifier=GithubVerificationService()
    async def identity(*args,**kwargs):return True
    monkeypatch.setattr(verifier,'_validate_polled_pull_identity',identity)
    class Client:
        async def get_pull(self,*args,**kwargs):return {'number':874,'merged_at':None,'state':'open','head':{'sha':HEAD}}
        async def list_check_runs_for_ref(self,*args,**kwargs):return checks(first='failure')
    await verifier._verify_item(db,scope,item,Client())
    await verifier._verify_item(db,scope,item,Client())
    assert item.retry_count==1 and item.dispatch_status=='dispatched'
    rows=(await db.execute(select(MailMessage))).scalars().all()
    assert len(rows)==2 and sorted(r.recipient_member_id for r in rows)==[members[0].id,members[1].id]
    assert sorted(wakes)==[members[0].id,members[1].id]


@pytest.mark.asyncio
async def test_changed_head_binding_hides_old_success_and_old_reviewer(db,monkeypatch):
    _,scope,item,members,policy=await seed(db);wakes=[];svc=service(monkeypatch,wakes)
    await bind(svc,db,item,members)
    await svc.observe(db,scope,item,HEAD,checks(second='success'),policy)
    async def read(scope,number):return {'number':874,'merged_at':None,'state':'open','head':{'sha':OTHER,'ref':'fixture/839','repo':{'full_name':'example/repo'}}}
    monkeypatch.setattr(svc,'_read_pull',read)
    await svc.register(db,work_item_id=item.id,dispatch_nonce=item.dispatch_nonce,scope_revision=0,
        head_sha=OTHER,reviewer_member_id=None,actor_member_id=members[0].id)
    assert item.verification_head_sha==OTHER and await svc.view(db,item) is None
    await svc.observe(db,scope,item,OTHER,checks(second='success',head=OTHER),policy)
    assert wakes.count(members[0].id)==2 and wakes.count(members[2].id)==1
    assert (await svc.view(db,item))['head_sha']==OTHER


@pytest.mark.asyncio
async def test_green_monitor_promotion_does_not_repeat_reviewer_or_leader_wake(db,monkeypatch):
    from app.models.database import MailReceipt
    from app.services.github_verification_service import GithubVerificationService
    _,scope,item,members,policy=await seed(db);wakes=[];svc=service(monkeypatch,wakes)
    await bind(svc,db,item,members)
    verifier=GithubVerificationService()
    async def identity(*args,**kwargs):return True
    monkeypatch.setattr(verifier,'_validate_polled_pull_identity',identity)
    class Client:
        async def get_pull(self,*args,**kwargs):return {'number':874,'state':'open','merged_at':None,'draft':False,'head':{'sha':HEAD}}
        async def list_check_runs_for_ref(self,*args,**kwargs):return checks(second='success')
    await verifier._verify_item(db,scope,item,Client())
    assert item.dispatch_status=='ready_for_review'
    assert wakes.count(members[0].id)==1 and wakes.count(members[2].id)==1
    for member in (members[0],members[2]):
        rows=(await db.execute(select(MailReceipt).where(MailReceipt.member_id==member.id))).scalars().all()
        assert len(rows)==1


@pytest.mark.asyncio
async def test_reviewer_unbound_during_mail_preparation_rolls_back_bundle(db,monkeypatch):
    from app.services.agent_mail_service import agent_mail_service
    _,scope,item,members,policy=await seed(db);wakes=[];svc=service(monkeypatch,wakes)
    await bind(svc,db,item,members)
    reviewer=await db.get(AgentTeamSlot,members[2].team_slot_id)
    original=agent_mail_service.send_message
    async def rebind(*args,**kwargs):
        result=await original(*args,**kwargs)
        reviewer.enabled=False;await db.flush()
        return result
    monkeypatch.setattr(agent_mail_service,'send_message',rebind)
    await svc.observe(db,scope,item,HEAD,checks(second='success'),policy)
    assert (await db.execute(select(MailMessage))).scalars().all()==[]
    assert wakes==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('wake_confirmed',[True,False])
async def test_work_progress_exposes_counts_and_finished_actor_confirmation(db,monkeypatch,wake_confirmed):
    from app.services.agent_mail_service import agent_mail_service
    from app.services.github_work_progress_service import GithubWorkProgressService
    from app.services.github_work_progress_observation import ProgressObservationError
    _,scope,item,members,policy=await seed(db);wakes=[];svc=service(monkeypatch,wakes)
    item_id,scope_id=item.id,scope.id
    await bind(svc,db,item,members)
    await svc.observe(db,scope,item,HEAD,checks(),policy)
    progress=GithubWorkProgressService()
    async def unavailable(*args,**kwargs):raise ProgressObservationError('git_unavailable')
    monkeypatch.setattr(progress,'_observe_progress',unavailable)
    monkeypatch.setattr('app.services.github_work_progress_service.hold_code',lambda:None)
    result=await progress.summary(db,item_id)
    assert result.phase=='ci_wait' and result.required_checks.completed==1 and result.required_checks.total==2
    assert '1 of 2 done' in result.next_action and 'fixture-private' not in result.model_dump_json()
    item=await db.get(GithubWorkItem,item_id);scope=await db.get(TeamGithubScope,scope_id)
    if not wake_confirmed:
        async def no_target(*args,**kwargs):return None
        monkeypatch.setattr(agent_mail_service,'_wake_member',no_target)
    await svc.observe(db,scope,item,HEAD,checks(second='success'),policy)
    result=await progress.summary(db,item_id)
    assert result.phase==('ci_finished' if wake_confirmed else 'ci_no_next_actor')
    assert result.required_checks.state==('finished' if wake_confirmed else 'no_next_actor')
    assert result.required_checks.completed==2 and result.required_checks.head_sha==HEAD


@pytest.mark.asyncio
@pytest.mark.parametrize('clear_at_claim', [False, True])
async def test_v1_cleared_reviewer_after_durable_claim_is_not_woken(db,monkeypatch,clear_at_claim):
    from app.models.database import GithubRequiredCheckRecipient, GithubRequiredCheckWatch
    from sqlalchemy import update
    _,scope,item,members,policy=await seed(db);wakes=[];svc=service(monkeypatch,wakes)
    await bind(svc,db,item,members)
    leader_id,reviewer_id=members[0].id,members[2].id
    original_commit=db.commit
    changed=[]
    async def commit():
        await original_commit()
        claimed=await db.scalar(select(GithubRequiredCheckRecipient.id).where(
            GithubRequiredCheckRecipient.member_id==reviewer_id,
            GithubRequiredCheckRecipient.wake_state=='claimed'))
        if clear_at_claim and claimed and not changed:
            changed.append(True)
            await db.execute(update(GithubRequiredCheckWatch).values(reviewer_member_id=None))
            await original_commit()
    monkeypatch.setattr(db,'commit',commit)
    await svc.observe(db,scope,item,HEAD,checks(second='success'),policy)
    assert wakes == ([leader_id] if clear_at_claim else [leader_id,reviewer_id]), wakes


@pytest.mark.asyncio
@pytest.mark.parametrize('hold_during_sync', [False, True])
async def test_v1_hold_during_actual_mail_wake_prevents_transport(db,monkeypatch,hold_during_sync):
    from types import SimpleNamespace
    from app.services.agent_mail_service import agent_mail_service, AgentMailService
    _,scope,item,members,policy=await seed(db);svc=service(monkeypatch,[])
    await bind(svc,db,item,members)
    monkeypatch.setattr(agent_mail_service,'_wake_member',AgentMailService._wake_member.__get__(agent_mail_service))
    held=[];sent=[]
    async def sync(db):
        if hold_during_sync:
            held.append(True)
            monkeypatch.setattr('app.services.github_ci_watch_service.hold_code',lambda:'hold')
    def run(args,**kwargs):
        if args[1]=='display-message':
            target=args[4]
            return SimpleNamespace(stdout=f'{target}|{100+int(target[1:])}')
        sent.append((args[-1]=='Enter',bool(held)))
        return SimpleNamespace(stdout='')
    monkeypatch.setattr(agent_mail_service,'sync_observed_sessions',sync)
    monkeypatch.setattr('app.services.agent_mail_service.subprocess.run',run)
    await svc.observe(db,scope,item,HEAD,checks(second='success'),policy)
    assert sent == ([] if hold_during_sync else [(False,False),(True,False)]*2), sent


@pytest.mark.asyncio
@pytest.mark.parametrize('stale_during_read', [False, True])
async def test_v1_registration_revalidates_leader_session_after_pull_read(db,monkeypatch,stale_during_read):
    from app.models.database import MailAgentSession, GithubRequiredCheckWatch
    from app.api.v1.deps import require_current_mail_session
    from app.config import settings
    from app.utils import peer_process
    team,scope,item,members,policy=await seed(db);svc=service(monkeypatch,[])
    session=MailAgentSession(member_id=members[0].id,source='mcp',provider='codex-cli',session_key='v1-current-leader',team_preset_id=team.id,team_slot_id=members[0].team_slot_id,capability_token_hash='synthetic-hash',bound_pane_pid=123,bound_pane_proc_start='start',mailbox_status='connected')
    db.add(session);await db.commit()
    alive=[True]
    monkeypatch.setattr(settings,'mail_capability_tokens_required',True)
    monkeypatch.setattr(peer_process,'pane_is_alive',lambda *args:alive[0])
    require_current_mail_session(session)
    original=svc._read_pull
    async def read(scope,number):
        result=await original(scope,number)
        if stale_during_read:
            alive[0]=False;session.mailbox_status='offline';await db.commit()
        return result
    monkeypatch.setattr(svc,'_read_pull',read)
    rejected=False
    try: await bind(svc,db,item,members,session=session)
    except (ValueError,PermissionError): rejected=True
    assert rejected is stale_during_read


@pytest.mark.asyncio
@pytest.mark.parametrize('head_changes', [False,True])
async def test_v1_monitor_rechecks_remote_head_before_completion_notice(db,monkeypatch,head_changes):
    from app.services.github_verification_service import GithubVerificationService
    _,scope,item,members,policy=await seed(db);wakes=[];svc=service(monkeypatch,wakes)
    await bind(svc,db,item,members)
    verifier=GithubVerificationService()
    async def identity(*args,**kwargs):return True
    monkeypatch.setattr(verifier,'_validate_polled_pull_identity',identity)
    current=[HEAD]
    class Client:
        async def get_pull(self,*args,**kwargs):return {'number':874,'state':'open','merged_at':None,'draft':False,'head':{'sha':current[0]}}
        async def list_check_runs_for_ref(self,*args,**kwargs):
            if head_changes:current[0]=OTHER
            return checks(second='success')
    await verifier._verify_item(db,scope,item,Client())
    review_wakes=[member_id for member_id in wakes if member_id in {members[0].id,members[2].id}]
    assert review_wakes == ([] if head_changes else [members[0].id,members[2].id]), wakes


@pytest.mark.asyncio
@pytest.mark.parametrize('path',['human_review','merge_wait'])
@pytest.mark.parametrize('head_changes',[False,True])
async def test_remote_head_fence_also_covers_review_and_merge_wait(db,monkeypatch,path,head_changes):
    from app.services.github_verification_service import GithubVerificationService
    _,scope,item,members,policy=await seed(db);wakes=[];svc=service(monkeypatch,wakes)
    await bind(svc,db,item,members)
    verifier=GithubVerificationService()
    async def identity(*args,**kwargs):return True
    monkeypatch.setattr(verifier,'_validate_polled_pull_identity',identity)
    current=[HEAD]
    class Client:
        async def get_pull(self,*args,**kwargs):
            return {'number':874,'state':'open','merged_at':None,'draft':False,'head':{'sha':current[0]}}
        async def list_check_runs_for_ref(self,*args,**kwargs):
            if head_changes:current[0]=OTHER
            return checks(second='success')
        async def get_combined_status_for_ref(self,*args,**kwargs):return {'state':'success','statuses':[]}
    if path=='human_review':
        item.issue_type='code';item.dispatch_status='ready_for_review';item.last_verified_sha=HEAD
        scope.merge_policy='human';await db.commit()
        await verifier._process_review_item(db,scope,item,Client())
    else:
        await verifier._wait_for_merge_checks(db,scope,item,Client(),HEAD)
    assert wakes==([] if head_changes else [members[0].id,members[2].id])


@pytest.mark.asyncio
@pytest.mark.parametrize('stage',['after_lookup','after_literal'])
@pytest.mark.parametrize('change',['none','hold','reviewer','nonce','lease','policy','session'])
async def test_actual_transport_rechecks_authority_before_text_and_enter(db,monkeypatch,stage,change):
    from types import SimpleNamespace
    from sqlalchemy import update
    from app.models.database import GithubRequiredCheckRecipient,GithubRequiredCheckWatch
    from app.services.agent_mail_service import agent_mail_service,AgentMailService
    _,scope,item,members,policy=await seed(db);svc=service(monkeypatch,[])
    await bind(svc,db,item,members)
    item_id,leader_id,reviewer_id=item.id,members[0].id,members[2].id
    session_id=await db.scalar(select(MailAgentSession.id).where(MailAgentSession.member_id==reviewer_id))
    monkeypatch.setattr(agent_mail_service,'_wake_member',AgentMailService._wake_member.__get__(agent_mail_service))
    original=agent_mail_service._send_guarded_tmux_inbox_check
    sends=[];changed=[]
    def run(args,**kwargs):
        if args[1]=='display-message':
            target=args[4]
            return SimpleNamespace(stdout=f'{target}|{100+int(target[1:])}')
        sends.append((args[3],args[-1]=='Enter'))
        return SimpleNamespace(stdout='')
    monkeypatch.setattr('app.services.agent_mail_service.subprocess.run',run)
    async def transport(pane,prompt,start,delivery_guard,transport_guard):
        calls=0
        async def guarded():
            nonlocal calls
            calls+=1
            boundary=1 if stage=='after_lookup' else 2
            if pane.pane_id==f'%{reviewer_id}' and calls==boundary and change!='none':
                changed.append(change)
                if change=='hold':monkeypatch.setattr('app.services.github_ci_watch_service.hold_code',lambda:'hold')
                elif change=='reviewer':await db.execute(update(GithubRequiredCheckWatch).values(reviewer_member_id=None))
                elif change=='nonce':await db.execute(update(GithubWorkItem).where(GithubWorkItem.id==item_id).values(dispatch_nonce='changed'))
                elif change=='lease':await db.execute(update(GithubWorkspace).where(GithubWorkspace.leased_item_id==item_id).values(lease_token='changed'))
                elif change=='policy':await db.execute(update(GithubWorkItem).where(GithubWorkItem.id==item_id).values(delivery_policy_revision=2))
                elif change=='session':await db.execute(update(MailAgentSession).where(MailAgentSession.id==session_id).values(mailbox_status='offline'))
                await db.commit()
            return await delivery_guard()
        return await original(pane,prompt,start,guarded,transport_guard)
    monkeypatch.setattr(agent_mail_service,'_send_guarded_tmux_inbox_check',transport)
    await svc.observe(db,scope,item,HEAD,checks(second='success'),policy)
    expected=[(f'%{leader_id}',False),(f'%{leader_id}',True)]
    if change=='none':expected += [(f'%{reviewer_id}',False),(f'%{reviewer_id}',True)]
    elif stage=='after_literal':expected += [(f'%{reviewer_id}',False)]
    assert sends==expected
    assert changed==([] if change=='none' else [change])
    states=(await db.execute(select(GithubRequiredCheckRecipient.member_id,GithubRequiredCheckRecipient.wake_state))).all()
    assert dict(states)=={leader_id:'confirmed',reviewer_id:'confirmed' if change=='none' else 'unknown'}
