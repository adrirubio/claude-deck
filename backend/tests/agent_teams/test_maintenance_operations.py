"""Maintenance profiles and real disposable Git updates preserve source history."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import pwd
import sqlite3
import subprocess

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
        super().__init__(p);self.path=path;self.tip=tip;self.mode=mode;self.notices=[];self.safety_calls=0
    def safety(self): self.safety_calls+=1
    def accepted(self,_pull): return self.tip
    def rows(self,query,values=()):
        if 'github_work_items' in query: return [{'id':1,'scope_id':1,'owner_slot_id':2,'dispatch_status':'dispatched','dispatch_nonce':'fixture','active_scope_revision':4,'delivery_policy':json.dumps({'accepted_base_update':self.mode})}]
        if 'team_github_scopes' in query: return [{'repo_owner':'fixture','repo_name':'repo','base_ref':'origin/integration','preset_id':1}]
        if 'github_workspaces' in query: return [{'path':str(self.path),'enabled':True}]
        raise AssertionError(query)
    def checkpoint(self,*_args): return {'message':1,'member':2,'generation':3}
    def authority(self,*_args): return 'unchanged-private-authority'
    def bindings(self,*_args): return []
    def generations(self,*_args): return []
    def api(self,method,path,body=None): self.notices.append(body);return {'status':'recorded'}


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


@pytest.mark.parametrize('problem',['disabled','dirty','wrong_head','wrong_branch'])
def test_integration_preflight_does_not_change_source_or_record_success(tmp_path,problem):
    workspace,before,tip=repository(tmp_path)
    service=IntegrationFixture(profile(tmp_path),workspace,tip,'disabled' if problem=='disabled' else 'fast_forward')
    if problem=='dirty': (workspace/'untracked.txt').write_text('Preserve this work')
    request=IntegrationRequest(operation_id='integration-1',work_item_id=1,expected_head='c'*40 if problem=='wrong_head' else before,
        accepted_pull=AcceptedPull(repository='fixture/repo',number=1,head=tip,base='main' if problem=='wrong_branch' else 'integration',checks=['Tests']),
        accepted_tip=tip,checkpoint_message=1)
    with pytest.raises(ValueError): service.integration_update(request)
    assert git(workspace,'rev-parse','HEAD')==before and service.notices==[]
    assert not (tmp_path/'state/maintenance/integration-1.json').exists()


class UpgradeFixture(Maintenance):
    def __init__(self,p,old,new,tree,contents,stop_unknown=False):
        super().__init__(p);self.current=old;self.old=old;self.new=new;self.tree=tree;self.contents=contents
        self.enabled=True;self.commands=[];self.stop_unknown=stop_unknown
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
        if argv[1]=='show': return b'ActiveState=active\nSubState=running\nMainPID=123\nControlGroup=\n' if self.stop_unknown else b'ActiveState=inactive\nSubState=dead\nMainPID=0\nControlGroup=\n'
        return b''


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
    assert record['status']==('paused_needs_inspection' if stop_unknown else 'deployed_paused')
    assert service.enabled is False and not Path(p.arming_file).exists()
    assert (Path(p.controller)/'private.env').read_text()=='Do not replace'
    assert service.current==('a'*40 if stop_unknown else 'b'*40)
    assert read_json(Path(p.state_dir)/'readiness.json')['other']=='preserve'
    if stop_unknown: assert 'authority_preserved' not in record
    else: assert record['authority_preserved'] is True
