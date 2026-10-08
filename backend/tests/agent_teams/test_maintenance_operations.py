"""Maintenance profiles and real disposable Git updates preserve source history."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import pwd
import sqlite3
import subprocess
import sys

import pytest
from pydantic import ValidationError

from app.services.maintenance_operations import (
    AcceptedPull, InstallationProfile, IntegrationRequest, Maintenance, UpgradeRequest, digest, read_json,
)


def profile(tmp_path, **changes):
    data=dict(controller=str(tmp_path/'controller'),database=str(tmp_path/'db.sqlite'),
        operator_env=str(tmp_path/'operator.env'),api_url='http://127.0.0.1:8000/api/v1',
        service='deck.service',supervisor_unit='deck-supervisor.timer',
        supervisor_state=str(tmp_path/'supervisor.json'),state_dir=str(tmp_path/'state'),
        hold_files=[str(tmp_path/'HOLD.json')],arming_file=str(tmp_path/'armed'),
        github_user='fixture',workspace_user=pwd.getpwuid(os.geteuid()).pw_name,protected_files=['private.env'])
    return InstallationProfile(**(data|changes))


@pytest.mark.parametrize('changes',[
    {'api_url':'https://remote.example/api/v1'}, {'api_url':'http://user:secret@localhost/api/v1'},
    {'controller':'relative'}, {'protected_files':['../private']}, {'hold_files':['relative']},
    {'service':'deck;touch private'}, {'version_records':{'../record':'pin'}}, {'unknown':True},
])
def test_profile_refuses_unbound_paths_remote_api_and_executable_data(tmp_path,changes):
    with pytest.raises(ValidationError): profile(tmp_path,**changes)


def test_input_refuses_duplicate_fields_symlinks_and_public_operator_profile(tmp_path):
    path=tmp_path/'profile.json';path.write_text('{"same":1,"same":2}')
    with pytest.raises(ValueError,match='duplicate'): read_json(path)
    path.write_text('{}');path.chmod(0o644)
    with pytest.raises(ValueError,match='private_profile'): read_json(path,private=True)
    path.chmod(0o600);assert read_json(path,private=True)=={}
    alias=tmp_path/'alias';alias.symlink_to(path)
    with pytest.raises(OSError): read_json(alias)


class CheckFixture(Maintenance):
    def __init__(self,p,actual,runs): super().__init__(p);self.actual=actual;self.runs=runs
    def run(self,argv,**_kwargs):
        return json.dumps(self.runs if 'check-runs' in argv[-1] else self.actual).encode()
    def current_checks(self,_pull):
        if self.runs.get('total_count',0)>100: raise ValueError('incomplete')
        return self.runs['check_runs']


@pytest.mark.parametrize('change',['head','base','unmerged','missing','wrong_app','wrong_head','pending','skipped','too_many'])
def test_accepted_pull_requires_exact_successful_configured_jobs(tmp_path,change):
    head='a'*40;pull=AcceptedPull(repository='fixture/repo',number=1,head=head,base='integration',checks=['Tests'])
    actual={'merged':True,'head':{'sha':head},'base':{'ref':'integration'},'merge_commit_sha':'b'*40}
    row={'name':'Tests','app':{'slug':'github-actions'},'head_sha':head,'status':'completed','conclusion':'success'}
    runs={'total_count':1,'check_runs':[row]}
    if change=='head': actual['head']['sha']='c'*40
    elif change=='base': actual['base']['ref']='main'
    elif change=='unmerged': actual['merged']=False
    elif change=='missing': runs['check_runs']=[]
    elif change=='wrong_app': row['app']['slug']='other'
    elif change=='wrong_head': row['head_sha']='c'*40
    elif change=='pending': row['status']='in_progress'
    elif change=='skipped': row['conclusion']='skipped'
    else: runs['total_count']=101
    with pytest.raises(ValueError): CheckFixture(profile(tmp_path),actual,runs).accepted(pull)
    actual['merged']=True;actual['head']['sha']=head;actual['base']['ref']='integration'
    row.update(app={'slug':'github-actions'},head_sha=head,status='completed',conclusion='success')
    runs.update(total_count=1,check_runs=[row])
    assert CheckFixture(profile(tmp_path),actual,runs).accepted(pull)=='b'*40


def git(path,*args):
    return subprocess.check_output(['git','-C',str(path),*args],stderr=subprocess.DEVNULL).decode().strip()


class IntegrationFixture(Maintenance):
    def __init__(self,p,path,tip,mode):
        super().__init__(p);self.path=path;self.tip=tip;self.mode=mode;self.notices=[];self.safety_calls=0;self.required=[]
        sqlite3.connect(p.database).close()
    def safety(self): self.safety_calls+=1
    def accepted(self,_pull): return self.tip
    def rows(self,query,values=()):
        if 'github_work_items' in query: return [{'id':1,'scope_id':1,'owner_slot_id':2,'dispatch_status':'dispatched','dispatch_nonce':'fixture','active_scope_revision':4,'delivery_policy':json.dumps({'accepted_base_update':self.mode,'required_checks':self.required})}]
        if 'team_github_scopes' in query: return [{'repo_owner':'fixture','repo_name':'repo','base_ref':'origin/integration','preset_id':1}]
        if 'github_workspaces' in query: return [{'id':1,'path':str(self.path),'enabled':True}]
        raise AssertionError(query)
    def checkpoint(self,*_args): return {'message':1,'member':2,'generation':3}
    def approved_owner(self,*_args): return {'authority':'fixture','workspace_id':1,'generation':3}
    def authority(self,*_args): return 'unchanged-private-authority'
    def bindings(self,*_args): return []
    def generations(self,*_args): return []
    def api(self,method,path,body=None): self.notices.append(body);return {'status':'recorded'}
    def record_source_import(self,*_args): return {'status':'mock_adapter','paths':[]}


def repository(tmp_path,diverged=False):
    upstream=tmp_path/'upstream';upstream.mkdir();git(upstream,'init','-b','integration')
    git(upstream,'config','user.name','Fixture');git(upstream,'config','user.email','fixture@example.test')
    (upstream/'source.txt').write_text('original\n');git(upstream,'add','.');git(upstream,'commit','-m','Initial')
    workspace=tmp_path/'workspace';git(tmp_path,'clone',str(upstream),str(workspace))
    git(workspace,'config','user.name','Fixture');git(workspace,'config','user.email','fixture@example.test')
    git(workspace,'switch','-c','owner-work');before=git(workspace,'rev-parse','HEAD')
    if diverged:
        (workspace/'source.txt').write_text('owner change\n');git(workspace,'commit','-am','Owner checkpoint');before=git(workspace,'rev-parse','HEAD')
    (upstream/'source.txt').write_text('accepted integration\n');git(upstream,'commit','-am','Accepted change')
    return workspace,before,git(upstream,'rev-parse','HEAD')


class StoredIntegrationFixture(IntegrationFixture):
    """Real Git and storage; owner process and API transport remain adapters."""
    rows = Maintenance.rows
    authority = Maintenance.authority
    record_source_import = Maintenance.record_source_import

    def __init__(self, p, path, tip, baseline, mode):
        super().__init__(p, path, tip, mode)
        Path(p.state_dir).mkdir()
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from app.database import Base
        from app.models.database import (
            AgentTeamPreset, GithubAttemptScopeRevision, GithubWorkItem, GithubWorkspace, TeamGithubScope,
        )
        engine = create_engine('sqlite:///' + p.database)
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(AgentTeamPreset(id=1, name='Fixture', description='', created_by='test'))
            db.add(TeamGithubScope(id=1, preset_id=1, repo_owner='fixture', repo_name='repo',
                repo_path=str(path), base_ref='origin/integration'))
            db.add(GithubWorkItem(id=1, scope_id=1, issue_number=1, issue_title='Fixture', issue_url='u',
                github_updated_at=datetime.now(timezone.utc), owner_slot_id=2, dispatch_status='dispatched',
                dispatch_nonce='fixture', active_scope_revision=4, pr_number=99, retry_count=3,
                delivery_policy_revision=2, delivery_policy={'accepted_base_update':mode,'required_checks':[]}))
            db.add(GithubWorkspace(id=1, scope_id=1, path=str(path), enabled=True, leased_item_id=1,
                lease_token='fixture-lease', leased_owner_pid=6000, leased_owner_proc_start='fixture'))
            db.add(GithubAttemptScopeRevision(id=1, work_item_id=1, dispatch_nonce='fixture', revision=4,
                owner_slot_id=2, owner_member_id=2, phase='implementation', execution_target='workspace',
                summary='Fixture', originating_escalation_reason='retry_count_exhausted',
                allowed_paths=['owned.txt'], allowed_actions=['edit_production'],
                allowed_commands=['pytest'], prohibited_actions=[], tool_fallbacks={},
                baseline_head_sha=baseline, baseline_tree_sha=git(path,'rev-parse',baseline+'^{tree}'),
                expected_workspace_id=1, expected_lease_token_hash='f'*64, max_failed_heads=2,
                status='active', acknowledged_at=datetime.now(timezone.utc)))
            db.commit()
        engine.dispose()


@pytest.mark.parametrize('mode', ['fast_forward', 'merge'])
def test_source_import_integration_records_exact_storage_without_changing_approval(tmp_path,mode):
    from app.services.accepted_source_imports import source_import_context
    workspace, baseline, tip = repository(tmp_path)
    if mode == 'merge':
        (workspace/'owned.txt').write_text('Owner checkpoint\n')
        git(workspace,'add','owned.txt');git(workspace,'commit','-m','Owner checkpoint')
    before = git(workspace,'rev-parse','HEAD')
    service = StoredIntegrationFixture(profile(tmp_path), workspace, tip, baseline, mode)
    original_authority = service.authority(1)
    original = {table: service.rows('SELECT * FROM '+table) for table in (
        'github_work_items','github_attempt_scope_revisions','github_workspaces')}
    request = IntegrationRequest(operation_id='integration-storage',work_item_id=1,expected_head=before,
        accepted_pull=AcceptedPull(repository='fixture/repo',number=1,head=tip,base='integration',checks=['Tests']),
        accepted_tip=tip,checkpoint_message=1)
    service.integration_update(request)
    record = read_json(tmp_path/'state/maintenance/integration-storage.json')
    assert record['status']=='completed' and record['source_import']['status']=='recorded'
    imported = service.rows('SELECT * FROM github_accepted_source_imports')[0]
    expected_blob = git(workspace,'rev-parse',tip+':source.txt')
    assert json.loads(imported['path_snapshots']) == {'source.txt':['100644','blob',expected_blob]}
    assert imported['accepted_source_sha']==tip and imported['accepted_merge_sha']==tip
    assert imported['observed_head_sha']==git(workspace,'rev-parse','HEAD')
    assert imported['context_sha256']==source_import_context(
        original['github_work_items'][0],original['github_attempt_scope_revisions'][0],
        original['github_workspaces'][0],service.rows('SELECT * FROM team_github_scopes')[0])
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.models.database import GithubWorkItem, GithubAttemptScopeRevision, GithubWorkspace, TeamGithubScope
    engine = create_engine('sqlite:///' + service.profile.database)
    with Session(engine) as db:
        assert imported['context_sha256'] == source_import_context(db.get(GithubWorkItem,1),
            db.get(GithubAttemptScopeRevision,1),db.get(GithubWorkspace,1),db.get(TeamGithubScope,1))
    engine.dispose()
    assert {table:service.rows('SELECT * FROM '+table) for table in original}==original
    assert service.authority(1) != original_authority
    git(workspace,'merge-base','--is-ancestor',before,'HEAD')
    git(workspace,'merge-base','--is-ancestor',tip,'HEAD')
    assert not git(workspace,'status','--porcelain')


@pytest.mark.parametrize('directory_scope', ['docs/', 'docs'])
@pytest.mark.parametrize('import_external', [False, True])
def test_maintenance_import_respects_explicit_directory_scope(tmp_path, directory_scope, import_external):
    workspace, baseline, tip = repository(tmp_path)
    if not import_external:
        upstream = tmp_path/'upstream'
        git(upstream, 'revert', '--no-edit', tip)
        tip = git(upstream, 'rev-parse', 'HEAD')
    (workspace/'docs/guide').mkdir(parents=True)
    (workspace/'docs/index.md').write_text('Owner document\n')
    (workspace/'docs/guide/install.md').write_text('Owner nested document\n')
    git(workspace, 'add', 'docs'); git(workspace, 'commit', '-m', 'Owner documents')
    before = git(workspace, 'rev-parse', 'HEAD')
    service = StoredIntegrationFixture(profile(tmp_path), workspace, tip, baseline, 'merge')
    with sqlite3.connect(service.profile.database) as db:
        db.execute('UPDATE github_attempt_scope_revisions SET allowed_paths=?',
                   (json.dumps([directory_scope]),))
    original = service.rows('SELECT * FROM github_attempt_scope_revisions')
    request = IntegrationRequest(operation_id='directory-import', work_item_id=1, expected_head=before,
        accepted_pull=AcceptedPull(repository='fixture/repo', number=1, head=tip, base='integration', checks=['Tests']),
        accepted_tip=tip, checkpoint_message=1)
    if directory_scope == 'docs/':
        service.integration_update(request)
        record = read_json(tmp_path/'state/maintenance/directory-import.json')
        assert record['status'] == 'completed'
        imports = service.rows('SELECT * FROM github_accepted_source_imports')
        if import_external:
            assert record['source_import']['status'] == 'recorded'
            assert set(json.loads(imports[0]['path_snapshots'])) == {'source.txt'}
        else:
            assert record['source_import'] == {'status': 'not_needed', 'paths': []}
            assert imports == []
    else:
        with pytest.raises(ValueError, match='source_import_content_mismatch'):
            service.integration_update(request)
        assert service.rows('SELECT * FROM github_accepted_source_imports') == []
    assert service.rows('SELECT * FROM github_attempt_scope_revisions') == original
    git(workspace, 'merge-base', '--is-ancestor', before, 'HEAD')
    assert (workspace/'docs/guide/install.md').read_text() == 'Owner nested document\n'


def test_source_import_integration_refuses_unaccepted_outside_content_and_keeps_commits(tmp_path):
    workspace, baseline, tip = repository(tmp_path)
    (workspace/'outside.txt').write_text('Unaccepted owner change\n')
    git(workspace,'add','outside.txt');git(workspace,'commit','-m','Keep owner work')
    before = git(workspace,'rev-parse','HEAD')
    service = StoredIntegrationFixture(profile(tmp_path),workspace,tip,baseline,'merge')
    original = service.authority(1)
    request = IntegrationRequest(operation_id='integration-refusal',work_item_id=1,expected_head=before,
        accepted_pull=AcceptedPull(repository='fixture/repo',number=1,head=tip,base='integration',checks=['Tests']),
        accepted_tip=tip,checkpoint_message=1)
    with pytest.raises(ValueError,match='source_import_content_mismatch'): service.integration_update(request)
    record = read_json(tmp_path/'state/maintenance/integration-refusal.json')
    assert record['status']=='needs_coordination' and service.authority(1)==original
    assert service.rows('SELECT * FROM github_accepted_source_imports')==[]
    git(workspace,'merge-base','--is-ancestor',before,'HEAD')
    assert (workspace/'outside.txt').read_text()=='Unaccepted owner change\n'


def test_source_import_reservation_commits_and_rolls_back_real_records(tmp_path):
    workspace, baseline, tip = repository(tmp_path)
    service = StoredIntegrationFixture(profile(tmp_path),workspace,tip,baseline,'fast_forward')
    git(workspace,'fetch','origin','integration');git(workspace,'merge','--ff-only',tip)
    item=service.rows('SELECT * FROM github_work_items')[0]
    owner=service.rows('SELECT * FROM github_workspaces')[0]
    scope=service.rows('SELECT * FROM team_github_scopes')[0]
    request=IntegrationRequest(operation_id='storage-rollback',work_item_id=1,expected_head=baseline,
        accepted_pull=AcceptedPull(repository='fixture/repo',number=1,head=tip,base='integration',checks=['Tests']),
        accepted_tip=tip,checkpoint_message=1)
    with pytest.raises(ValueError,match='after_record'):
        with service.reservation() as db:
            assert service.record_source_import(db,request,item,owner,scope,service.source(workspace))['status']=='recorded'
            raise ValueError('after_record')
    assert service.rows('SELECT * FROM github_accepted_source_imports')==[]
    with service.reservation() as db:
        first=service.record_source_import(db,request,item,owner,scope,service.source(workspace))
    with service.reservation() as db:
        replay=service.record_source_import(db,request,item,owner,scope,service.source(workspace))
    assert first['status']=='recorded' and replay['status']=='already_recorded'
    assert first['import_id']==replay['import_id']
    assert len(service.rows('SELECT * FROM github_accepted_source_imports'))==1


def test_source_import_initial_attempt_integration_has_no_continuation_boundary(tmp_path):
    workspace, baseline, tip = repository(tmp_path)
    service = StoredIntegrationFixture(profile(tmp_path),workspace,tip,baseline,'fast_forward')
    with sqlite3.connect(service.profile.database) as db:
        db.execute('DELETE FROM github_attempt_scope_revisions')
        db.execute('UPDATE github_work_items SET active_scope_revision=0')
    original = service.authority(1)
    request = IntegrationRequest(operation_id='initial-integration',work_item_id=1,expected_head=baseline,
        accepted_pull=AcceptedPull(repository='fixture/repo',number=1,head=tip,base='integration',checks=['Tests']),
        accepted_tip=tip,checkpoint_message=1)
    try:
        service.integration_update(request)
    except ValueError:
        pass  # Read the durable outcome to expose the old post-Git refusal.
    record = read_json(tmp_path/'state/maintenance/initial-integration.json')
    assert record['status']=='completed' and record['source_import']['status']=='not_applicable'
    assert git(workspace,'rev-parse','HEAD')==tip and service.authority(1)==original
    assert service.rows('SELECT * FROM github_accepted_source_imports')==[]


def test_source_import_empty_table_creation_does_not_change_upgrade_authority(tmp_path):
    from sqlalchemy import create_engine
    from app.models.database import GithubAcceptedSourceImport
    service = Maintenance(profile(tmp_path));sqlite3.connect(service.profile.database).close()
    before = service.authority()
    engine = create_engine('sqlite:///' + service.profile.database)
    GithubAcceptedSourceImport.__table__.create(engine)
    engine.dispose()
    assert service.authority()==before


def test_source_import_history_survives_parent_deletion_with_foreign_keys_enabled(tmp_path):
    workspace, baseline, tip = repository(tmp_path)
    service = StoredIntegrationFixture(profile(tmp_path),workspace,tip,baseline,'fast_forward')
    request = IntegrationRequest(operation_id='history-integration',work_item_id=1,expected_head=baseline,
        accepted_pull=AcceptedPull(repository='fixture/repo',number=1,head=tip,base='integration',checks=['Tests']),
        accepted_tip=tip,checkpoint_message=1)
    service.integration_update(request)
    history = service.rows('SELECT * FROM github_accepted_source_imports')
    with sqlite3.connect(service.profile.database) as db:
        db.execute('PRAGMA foreign_keys=ON')
        assert db.execute('PRAGMA foreign_keys').fetchone()[0]==1
        db.execute('DELETE FROM github_work_items WHERE id=1')
        assert db.execute('SELECT COUNT(*) FROM github_attempt_scope_revisions').fetchone()[0]==0
    assert service.rows('SELECT * FROM github_accepted_source_imports')==history


@pytest.mark.parametrize('mode,diverged,result',[('fast_forward',False,'completed'),('fast_forward',True,'needs_coordination'),('merge',True,'needs_coordination')])
def test_real_integration_update_preserves_commits_supervision_and_conflicts(tmp_path,mode,diverged,result):
    workspace,before,tip=repository(tmp_path,diverged)
    (tmp_path/'state').mkdir()
    service=IntegrationFixture(profile(tmp_path),workspace,tip,mode)
    request=IntegrationRequest(operation_id='integration-1',work_item_id=1,expected_head=before,
        accepted_pull=AcceptedPull(repository='fixture/repo',number=1,head=tip,base='integration',checks=['Tests']),
        accepted_tip=tip,checkpoint_message=1)
    if result=='completed': service.integration_update(request)
    else:
        with pytest.raises(ValueError): service.integration_update(request)
    record=read_json(tmp_path/'state/maintenance/integration-1.json')
    assert record['status']==result and service.safety_calls>=2
    assert service.notices[-1]['outcome']==result
    git(workspace,'merge-base','--is-ancestor',before,'HEAD')
    if result=='completed': assert git(workspace,'rev-parse','HEAD')==tip
    elif mode=='fast_forward': assert git(workspace,'rev-parse','HEAD')==before and not git(workspace,'status','--porcelain')
    else:
        assert git(workspace,'rev-parse','HEAD')==before
        assert 'UU source.txt' in git(workspace,'status','--porcelain')
        assert (workspace/'source.txt').read_text().startswith('<<<<<<<')


@pytest.mark.parametrize('problem',['disabled','dirty','wrong_head','wrong_branch','configured_check'])
def test_integration_preflight_does_not_change_source_or_record_success(tmp_path,problem):
    workspace,before,tip=repository(tmp_path)
    service=IntegrationFixture(profile(tmp_path),workspace,tip,'disabled' if problem=='disabled' else 'fast_forward')
    if problem=='dirty': (workspace/'untracked.txt').write_text('Preserve this work')
    if problem=='configured_check': service.required=[{'name':'Required missing job','app_slug':'github-actions'}]
    request=IntegrationRequest(operation_id='integration-1',work_item_id=1,expected_head='c'*40 if problem=='wrong_head' else before,
        accepted_pull=AcceptedPull(repository='fixture/repo',number=1,head=tip,base='main' if problem=='wrong_branch' else 'integration',checks=['Tests']),
        accepted_tip=tip,checkpoint_message=1)
    with pytest.raises(ValueError): service.integration_update(request)
    assert git(workspace,'rev-parse','HEAD')==before and service.notices==[]
    assert not (tmp_path/'state/maintenance/integration-1.json').exists()


class UpgradeFixture(Maintenance):
    def __init__(self,p,old,new,tree,contents,stop_unknown=False):
        super().__init__(p);self.current=old;self.old=old;self.new=new;self.tree=tree;self.contents=contents
        self.enabled=True;self.commands=[];self.stop_unknown=stop_unknown;self.started=False
    def source(self,path,**_kwargs): return {'head':self.current if str(path)==self.profile.controller else self.new,'tree':self.tree,'branch':''}
    def git(self,path,*args,**_kwargs):
        if args[0]=='diff': return b'source.py\n'
        if args[0]=='show': return self.contents
        if args[0]=='checkout': self.current=args[-1]
        self.commands.append(args);return b''
    def rows(self,query,values=()):
        if 'agent_team_presets' in query: return [{'id':1,'autonomy_enabled':self.enabled}]
        if 'github_work_items' in query: return []
        raise AssertionError(query)
    def safety(self): pass
    def accepted(self,pull): return pull.head
    def authority(self): return 'unchanged'
    def bindings(self): return []
    def generations(self): return []
    def api(self,method,path,body=None):
        if body is not None: self.enabled=body['autonomy_enabled']
        if path=='/health': return {'status':'ok'}
        return {'autonomy_enabled':self.enabled}
    def run(self,argv,**_kwargs):
        self.commands.append(tuple(argv))
        if argv[1]=='start': self.started=True
        if argv[1]=='show': return b'ActiveState=active\nSubState=running\nMainPID=123\nControlGroup=\n' if self.stop_unknown else b'ActiveState=inactive\nSubState=dead\nMainPID=0\nControlGroup=\n'
        return b''


def configured_upgrade(tmp_path):
    p=profile(tmp_path,version_records={'readiness.json':'controller_pin'})
    Path(p.controller).mkdir();(Path(p.controller)/'private.env').write_text('Preserve operator settings')
    Path(p.state_dir).mkdir();(Path(p.state_dir)/'readiness.json').write_text(json.dumps({'controller_pin':'a'*40}))
    Path(p.supervisor_state).write_text(json.dumps({'autonomy_enabled':False,'last_tick':datetime.now(timezone.utc).isoformat()}))
    sqlite3.connect(p.database).close();Path(p.arming_file).write_text('armed')
    contents=b'accepted source';files={'source.py':hashlib.sha256(contents).hexdigest()}
    log=tmp_path/'proof.log';log.write_text('Focused synthetic proof')
    source={'head':'b'*40,'tree':'c'*40,'status':''}
    receipt=tmp_path/'proof.json';receipt.write_text(json.dumps({'eligible':True,'exit_code':0,'source_before':source,'source_after':source,'log':str(log),'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}))
    review=tmp_path/'review.md';review.write_text('ACCEPT\n'+'b'*40+'\n'+digest(files))
    request=UpgradeRequest(operation_id='upgrade-1',expected_head='a'*40,target_head='b'*40,candidate=str(tmp_path/'candidate'),
        accepted_pulls=[AcceptedPull(repository='fixture/repo',number=1,head='b'*40,base='main',checks=['Tests'])],
        reviewed_files=files,review_file=str(review),review_sha256=hashlib.sha256(review.read_bytes()).hexdigest(),proof_receipt=str(receipt))
    return UpgradeFixture(p,'a'*40,'b'*40,'c'*40,contents),request


@pytest.mark.parametrize('failure',['health','preservation','autonomy_on','off_timeout','marker','evidence'])
def test_upgrade_failure_always_attempts_and_proves_stop(tmp_path,monkeypatch,failure):
    service,request=configured_upgrade(tmp_path)
    api=service.api
    def changed_api(method,path,body=None):
        if service.started and failure=='off_timeout' and method=='PATCH': raise TimeoutError('fixture')
        if service.started and path=='/health' and failure in {'health','off_timeout'}:
            if failure=='off_timeout': service.enabled=True
            return {'status':'unknown'}
        if service.started and method=='GET' and path!='/health' and failure=='autonomy_on': return {'autonomy_enabled':True}
        return api(method,path,body)
    monkeypatch.setattr(service,'api',changed_api)
    if failure=='preservation': monkeypatch.setattr(service,'authority',lambda: 'changed' if service.started else 'unchanged')
    if failure=='marker': Path(service.profile.arming_file).unlink();Path(service.profile.arming_file).mkdir()
    if failure=='evidence':
        original=service.record
        def cannot_save(operation_id,record,*,first=False):
            if not first: raise OSError('fixture')
            return original(operation_id,record,first=first)
        monkeypatch.setattr(service,'record',cannot_save)
    with pytest.raises(Exception): service.upgrade(request)
    assert sum(command==('systemctl','start','deck.service') for command in service.commands)<=1
    assert ('systemctl','stop','deck.service') in service.commands
    record=read_json(Path(service.profile.state_dir)/'maintenance/upgrade-1.json')
    if failure=='evidence': assert record['status']=='prepared'
    else:
        assert record['status']=='failed_stopped_needs_inspection'
        assert 'authority_preserved' not in record
        assert {'step':'controller_stop','status':'confirmed'} in record['cleanup']
        if failure in {'marker','off_timeout'}: assert any(step['status']=='unknown' for step in record['cleanup'])


@pytest.mark.parametrize('change',['scope','slot','coordination','database','unchanged'])
def test_upgrade_preservation_reads_real_policy_roster_coordination_and_database_identity(tmp_path,monkeypatch,change):
    service,request=configured_upgrade(tmp_path)
    with sqlite3.connect(service.profile.database) as db:
        db.executescript('''
            CREATE TABLE team_github_scopes (id INTEGER PRIMARY KEY,max_scope_paths INTEGER);
            INSERT INTO team_github_scopes VALUES (1,29);
            CREATE TABLE agent_team_slots (id INTEGER PRIMARY KEY,enabled INTEGER,role TEXT);
            INSERT INTO agent_team_slots VALUES (1,1,'owner');
            CREATE TABLE agent_team_presets (id INTEGER PRIMARY KEY,autonomy_enabled INTEGER,name TEXT);
            INSERT INTO agent_team_presets VALUES (1,1,'fixture');
            CREATE TABLE github_backlog_coordination (scope_id INTEGER PRIMARY KEY,max_daily_requests INTEGER);
            INSERT INTO github_backlog_coordination VALUES (1,12);
        ''')
    monkeypatch.setattr(service,'authority',lambda: Maintenance.authority(service))
    original=service.run
    def run_changed(argv,**kwargs):
        result=original(argv,**kwargs)
        if argv[1]=='start' and change!='unchanged':
            if change=='database':
                replacement=tmp_path/'replacement.sqlite'
                with sqlite3.connect(service.profile.database) as db,sqlite3.connect(replacement) as target: db.backup(target)
                os.replace(replacement,service.profile.database)
            else:
                query={'scope':'UPDATE team_github_scopes SET max_scope_paths=30',
                       'slot':"UPDATE agent_team_slots SET enabled=0,role='other'",
                       'coordination':'UPDATE github_backlog_coordination SET max_daily_requests=99'}[change]
                with sqlite3.connect(service.profile.database) as db: db.execute(query)
        return result
    monkeypatch.setattr(service,'run',run_changed)
    if change=='unchanged': service.upgrade(request)
    else:
        with pytest.raises(ValueError,match='deployed_context_changed'): service.upgrade(request)
    record=read_json(Path(service.profile.state_dir)/'maintenance/upgrade-1.json')
    assert record['status']==('deployed_paused' if change=='unchanged' else 'failed_stopped_needs_inspection')


def test_checkpoint_is_single_use_across_operation_ids_and_transaction_rollback(tmp_path):
    service=Maintenance(profile(tmp_path));sqlite3.connect(service.profile.database).close()
    checkpoint={'message':12,'member':2,'generation':3}
    with pytest.raises(ValueError):
        with service.reservation():
            service.consume_checkpoint('first-operation',checkpoint)
            raise ValueError('Source effects do not roll back')
    with pytest.raises(FileExistsError): service.consume_checkpoint('other-operation',checkpoint)


def checkpoint_database(service,head='a'*40):
    stamp=datetime.now(timezone.utc).isoformat();pid=os.getpid()
    start=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]
    owner={'authority':'fixture-current-approval','workspace_id':1,'generation':10}
    payload={'kind':'factory_maintenance_checkpoint','operation':'controller_upgrade','operation_id':'upgrade-1',
        'work_item_id':1,'source_head':head,'owner_context_sha256':digest(owner),
        'no_inflight_operations':True,'hold_until_release':True}
    with sqlite3.connect(service.profile.database) as db:
        db.executescript('''CREATE TABLE mail_messages (id INTEGER PRIMARY KEY,sender_member_id INTEGER,created_at TEXT,payload TEXT,body_markdown TEXT);
            CREATE TABLE mail_team_members (id INTEGER PRIMARY KEY,team_slot_id INTEGER,updated_at TEXT);
            CREATE TABLE mail_agent_sessions (id INTEGER PRIMARY KEY,member_id INTEGER,team_slot_id INTEGER,pid INTEGER,
                created_at TEXT,last_seen_at TEXT,provider TEXT,cwd TEXT,bound_pane_pid INTEGER,bound_pane_proc_start TEXT,
                source TEXT,closed_at TEXT,mailbox_status TEXT,capability_token_hash TEXT);''')
        db.execute('INSERT INTO mail_messages (id,sender_member_id,created_at,payload) VALUES (12,2,?,?)',(stamp,json.dumps(payload)))
        db.execute('INSERT INTO mail_team_members VALUES (2,2,?)',(stamp,))
        db.execute('INSERT INTO mail_agent_sessions VALUES (10,2,2,?,?,?, ?,?,?,?,?,NULL,?,?)',
            (pid,stamp,stamp,'fixture',str(Path(service.profile.database).parent),pid,start,'mcp','connected','fixture-capability-hash'))
    item={'id':1,'owner_slot_id':2};workspace={'id':1,'leased_owner_pid':pid,'leased_owner_proc_start':start,'path':str(Path(service.profile.database).parent)}
    return item,workspace,owner


@pytest.mark.parametrize('change',['operation','context','expired','hold','competing','unchanged'])
def test_real_mail_checkpoint_binds_one_current_operation_and_generation(tmp_path,change):
    service=Maintenance(profile(tmp_path));item,workspace,owner=checkpoint_database(service)
    with sqlite3.connect(service.profile.database) as db:
        payload=json.loads(db.execute('SELECT payload FROM mail_messages').fetchone()[0])
        if change=='operation': payload['operation_id']='other-operation'
        elif change=='context': payload['owner_context_sha256']='0'*64
        elif change=='hold': payload['hold_until_release']=False
        elif change=='expired': db.execute('UPDATE mail_messages SET created_at=?',((datetime.now(timezone.utc)-timedelta(seconds=901)).isoformat(),))
        elif change=='competing': db.execute('INSERT INTO mail_agent_sessions SELECT 11,member_id,team_slot_id,pid,created_at,last_seen_at,provider,cwd,bound_pane_pid,bound_pane_proc_start,source,closed_at,mailbox_status,? FROM mail_agent_sessions',('second-capability-hash',))
        db.execute('UPDATE mail_messages SET payload=?',(json.dumps(payload),))
    call=lambda: service.checkpoint(item,workspace,'controller_upgrade',12,'a'*40,'upgrade-1',owner)
    if change=='unchanged': assert call()=={'message':12,'member':2,'generation':10}
    else:
        with pytest.raises(ValueError): call()


def test_upgrade_rechecks_real_checkpoint_age_after_backup_before_cutover(tmp_path,monkeypatch):
    from datetime import timedelta
    service,request=configured_upgrade(tmp_path);item,workspace,owner=checkpoint_database(service,head='b'*40)
    original=service.rows
    def rows(query,values=()):
        if 'github_work_items' in query: return [item|{'dispatch_status':'dispatched'}]
        if 'github_workspaces' in query: return [workspace]
        if 'mail_' in query: return Maintenance.rows(service,query,values)
        return original(query,values)
    monkeypatch.setattr(service,'rows',rows)
    monkeypatch.setattr(service,'approved_owner',lambda *_args: owner)
    request=request.model_copy(update={'checkpoint_messages':{'1':12}})
    calls=[]
    def checkpoint(*args):
        calls.append(True)
        return Maintenance.checkpoint(service,*args)
    accepted=service.accepted;reads=[]
    def age_after_backup(pull):
        reads.append(True)
        if len(reads)==2:
            with sqlite3.connect(service.profile.database) as db:
                db.execute('UPDATE mail_messages SET created_at=?',((datetime.now(timezone.utc)-timedelta(seconds=901)).isoformat(),))
        return accepted(pull)
    monkeypatch.setattr(service,'checkpoint',checkpoint)
    monkeypatch.setattr(service,'accepted',age_after_backup)
    with pytest.raises(ValueError,match='owner_checkpoint_changed'): service.upgrade(request)
    assert len(calls)==2 and service.current=='a'*40
    assert ('systemctl','stop','deck.service') not in service.commands
    assert ('systemctl','start','deck.service') not in service.commands
    assert read_json(Path(service.profile.state_dir)/'maintenance/upgrade-1.json')['status']=='failed_paused_needs_inspection'


def test_timeout_settles_actual_child_process_before_releasing_reservation(tmp_path):
    import sys
    service=Maintenance(profile(tmp_path));sqlite3.connect(service.profile.database).close()
    pidfile=tmp_path/'child.pid'
    code='import os,signal,time;from pathlib import Path;Path('+repr(str(pidfile))+').write_text(str(os.getpid()));signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)'
    with service.reservation():
        with pytest.raises(ValueError,match='timeout_settled'):
            service.run([sys.executable,'-c',code],timeout=.1)
        pid=int(pidfile.read_text())
        with pytest.raises(ProcessLookupError): os.kill(pid,0)


def integration_authority_db(service):
    with sqlite3.connect(service.profile.database) as db:
        db.executescript('''CREATE TABLE github_work_items (id INTEGER PRIMARY KEY,scope_id INTEGER,dispatch_status TEXT);
            INSERT INTO github_work_items VALUES (1,1,'dispatched');
            CREATE TABLE team_github_scopes (id INTEGER PRIMARY KEY,base_ref TEXT);
            INSERT INTO team_github_scopes VALUES (1,'origin/integration');''')
    service.authority=lambda item_id: Maintenance.authority(service,item_id)


@pytest.mark.parametrize('when',['before_reservation','during_merge'])
def test_real_independent_authority_writer_cannot_cross_source_boundary(tmp_path,monkeypatch,when):
    from contextlib import contextmanager
    workspace,before,tip=repository(tmp_path);(tmp_path/'state').mkdir()
    service=IntegrationFixture(profile(tmp_path),workspace,tip,'fast_forward');integration_authority_db(service)
    request=IntegrationRequest(operation_id='integration-race',work_item_id=1,expected_head=before,
        accepted_pull=AcceptedPull(repository='fixture/repo',number=1,head=tip,base='integration',checks=['Tests']),
        accepted_tip=tip,checkpoint_message=1)
    if when=='before_reservation':
        original=service.reservation
        @contextmanager
        def cancel_then_reserve():
            with sqlite3.connect(service.profile.database) as writer: writer.execute("UPDATE github_work_items SET dispatch_status='failed' WHERE id=1")
            with original(): yield
        monkeypatch.setattr(service,'reservation',cancel_then_reserve)
        with pytest.raises(ValueError,match='reserved_owner_context_changed'): service.integration_update(request)
        assert git(workspace,'rev-parse','HEAD')==before
        assert not (Path(service.profile.state_dir)/'maintenance/checkpoint-claims/1.json').exists()
    else:
        original=service.git;blocked=[]
        def try_cancel(path,*args,**kwargs):
            if args[0]=='merge':
                with sqlite3.connect(service.profile.database,timeout=.02) as writer:
                    with pytest.raises(sqlite3.OperationalError,match='locked'):
                        writer.execute("UPDATE github_work_items SET dispatch_status='failed' WHERE id=1")
                    blocked.append(True)
            return original(path,*args,**kwargs)
        monkeypatch.setattr(service,'git',try_cancel)
        service.integration_update(request)
        assert blocked==[True] and git(workspace,'rev-parse','HEAD')==tip
        with sqlite3.connect(service.profile.database) as db: assert db.execute('SELECT dispatch_status FROM github_work_items').fetchone()[0]=='dispatched'


@pytest.mark.parametrize('stop_unknown',[False,True])
def test_upgrade_records_only_confirmed_version_and_preserves_operator_files(tmp_path,stop_unknown):
    p=profile(tmp_path,version_records={'readiness.json':'controller_pin'})
    Path(p.controller).mkdir();(Path(p.controller)/'private.env').write_text('Do not replace')
    Path(p.state_dir).mkdir();(Path(p.state_dir)/'readiness.json').write_text(json.dumps({'controller_pin':'a'*40,'other':'preserve'}))
    Path(p.supervisor_state).write_text(json.dumps({'autonomy_enabled':False,'last_tick':datetime.now(timezone.utc).isoformat()}))
    sqlite3.connect(p.database).close();Path(p.arming_file).write_text('armed')
    contents=b'accepted source';files={'source.py':hashlib.sha256(contents).hexdigest()}
    log=tmp_path/'proof.log';log.write_text('Focused synthetic proof')
    source={'head':'b'*40,'tree':'c'*40,'status':''}
    receipt=tmp_path/'proof.json';receipt.write_text(json.dumps({'eligible':True,'exit_code':0,'source_before':source,'source_after':source,'log':str(log),'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}))
    review=tmp_path/'review.md';review.write_text('ACCEPT\n'+'b'*40+'\n'+digest(files))
    request=UpgradeRequest(operation_id='upgrade-1',expected_head='a'*40,target_head='b'*40,candidate=str(tmp_path/'candidate'),
        accepted_pulls=[AcceptedPull(repository='fixture/repo',number=1,head='b'*40,base='main',checks=['Tests'])],
        reviewed_files=files,review_file=str(review),review_sha256=hashlib.sha256(review.read_bytes()).hexdigest(),
        proof_receipt=str(receipt))
    service=UpgradeFixture(p,'a'*40,'b'*40,'c'*40,contents,stop_unknown)
    if stop_unknown:
        with pytest.raises(ValueError,match='termination_unknown'): service.upgrade(request)
    else: service.upgrade(request)
    record=read_json(Path(p.state_dir)/'maintenance/upgrade-1.json')
    assert record['status']==('failed_termination_unknown' if stop_unknown else 'deployed_paused')
    assert service.enabled is False and not Path(p.arming_file).exists()
    assert (Path(p.controller)/'private.env').read_text()=='Do not replace'
    assert service.current==('a'*40 if stop_unknown else 'b'*40)
    assert read_json(Path(p.state_dir)/'readiness.json')['other']=='preserve'
    if stop_unknown: assert 'authority_preserved' not in record
    else: assert record['authority_preserved'] is True


@pytest.mark.parametrize('observation',['denied','malformed','stopped','unknown_time','confirmed_dead'])
def test_current_checkpoint_retains_unresolved_competitor(tmp_path, monkeypatch, observation):
    service=Maintenance(profile(tmp_path));item,workspace,owner=checkpoint_database(service)
    child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
    try:
        stamp=datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(service.profile.database) as db:
            db.execute('INSERT INTO mail_agent_sessions SELECT 9,member_id,team_slot_id,?,created_at,?,provider,cwd,bound_pane_pid,bound_pane_proc_start,source,closed_at,mailbox_status,? FROM mail_agent_sessions WHERE id=10',
                (child.pid,None if observation=='unknown_time' else stamp,'competing-private-hash'))
        original=Path.read_text
        target=f'/proc/{child.pid}/stat'
        raw=original(Path(target))
        if observation=='confirmed_dead':child.terminate();child.wait(timeout=3)
        else:
            def read(path,*args,**kwargs):
                if str(path)==target:
                    if observation=='denied':raise PermissionError('synthetic process observation denied')
                    if observation=='malformed':return 'malformed'
                    if observation=='stopped':return raw.replace(') S ',') T ').replace(') R ',') T ')
                return original(path,*args,**kwargs)
            monkeypatch.setattr(Path,'read_text',read)
        call=lambda:service.checkpoint(item,workspace,'controller_upgrade',12,'a'*40,'upgrade-1',owner)
        if observation=='confirmed_dead':assert call()=={'message':12,'member':2,'generation':10}
        else:
            with pytest.raises(ValueError):call()
    finally:
        if child.poll() is None:child.terminate();child.wait(timeout=3)


def test_final_ci_read_cannot_expire_checkpoint_before_real_git_merge(tmp_path,monkeypatch):
    workspace,before,tip=repository(tmp_path);(tmp_path/'state').mkdir()
    service=IntegrationFixture(profile(tmp_path),workspace,tip,'fast_forward')
    item,bound,owner=checkpoint_database(service,head=before)
    with sqlite3.connect(service.profile.database) as db:
        import json
        payload=json.loads(db.execute('SELECT payload FROM mail_messages WHERE id=12').fetchone()[0])
        payload.update(operation='integration_update',operation_id='integration-expiry')
        db.execute('UPDATE mail_messages SET payload=? WHERE id=12',(json.dumps(payload),))
    original_rows=service.rows
    def rows(query,values=()):
        if 'mail_' in query:return Maintenance.rows(service,query,values)
        return original_rows(query,values)
    monkeypatch.setattr(service,'rows',rows)
    monkeypatch.setattr(service,'approved_owner',lambda *_args:owner)
    monkeypatch.setattr(service,'checkpoint',lambda _item,_workspace,*args:Maintenance.checkpoint(service,item,bound,*args))
    import app.services.maintenance_operations as operations
    actual_datetime=operations.datetime
    class Clock(actual_datetime):
        advance=0
        @classmethod
        def now(cls,tz=None):return actual_datetime.now(tz)+timedelta(seconds=cls.advance)
    monkeypatch.setattr(operations,'datetime',Clock)
    reads=[]
    def accepted(_pull):
        reads.append(True)
        if len(reads)==2:Clock.advance=901
        return tip
    monkeypatch.setattr(service,'accepted',accepted)
    request=IntegrationRequest(operation_id='integration-expiry',work_item_id=1,expected_head=before,
        accepted_pull=AcceptedPull(repository='fixture/repo',number=1,head=tip,base='integration',checks=['Tests']),
        accepted_tip=tip,checkpoint_message=12)
    with pytest.raises(ValueError,match='owner_checkpoint_changed'):service.integration_update(request)
    assert len(reads)==2 and git(workspace,'rev-parse','HEAD')==before
    assert not (Path(service.profile.state_dir)/'maintenance/checkpoint-claims/12.json').exists()
    assert read_json(Path(service.profile.state_dir)/'maintenance/integration-expiry.json')['status']=='needs_coordination'


@pytest.mark.parametrize("change", [
    "unchanged", "prose", "duplicate", "operation", "context", "sender",
    "hold", "inflight", "too_large", "scalar", "explicit_payload_conflict",
])
def test_standard_authenticated_mail_body_confirms_only_exact_checkpoint(tmp_path, change):
    service = Maintenance(profile(tmp_path))
    item, workspace, owner = checkpoint_database(service)
    with sqlite3.connect(service.profile.database) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(mail_messages)")}
        # Keep this decisive case runnable against the original clean source.
        if "body_markdown" not in columns:
            db.execute("ALTER TABLE mail_messages ADD COLUMN body_markdown TEXT")
        payload = json.loads(db.execute("SELECT payload FROM mail_messages").fetchone()[0])
        original = dict(payload)
        if change == "operation":
            payload["operation_id"] = "other-operation"
        elif change == "context":
            payload["owner_context_sha256"] = "0" * 64
        elif change == "hold":
            payload["hold_until_release"] = False
        elif change == "inflight":
            payload["no_inflight_operations"] = False
        body = json.dumps(payload)
        if change == "prose":
            body = "I confirm this checkpoint: " + body
        elif change == "duplicate":
            body = '{"operation_id":"wrong",' + body[1:]
        elif change == "too_large":
            body += " " * 65537
        elif change == "scalar":
            body = "null"
        if change == "sender":
            db.execute("UPDATE mail_messages SET sender_member_id=999")
        structured = "null"
        if change == "explicit_payload_conflict":
            original["operation_id"] = "other-operation"
            structured = json.dumps(original)
        db.execute("UPDATE mail_messages SET payload=?,body_markdown=?", (structured, body))
    call = lambda: service.checkpoint(item, workspace, "controller_upgrade", 12, "a" * 40, "upgrade-1", owner)
    if change == "unchanged":
        try:
            observed = call()
        except ValueError:
            observed = None
        assert observed == {"message": 12, "member": 2, "generation": 10}
    else:
        with pytest.raises(ValueError):
            call()
