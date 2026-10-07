"""Operator maintenance primitives. Profiles contain data, never executable hooks."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import pwd
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
import urllib.request

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.services.agent_mail_service import MCP_HEARTBEAT_TTL_SECONDS

_SHA = r"^[0-9a-f]{40}$"
_NAME = r"^[A-Za-z0-9_.-]{1,100}$"
_TABLES = ("github_work_items", "github_approval_requests", "github_workspaces",
           "github_attempt_scope_revisions", "github_delivery_policy_events", "github_owner_followups")
_VOLATILE = {"updated_at", "github_updated_at", "issue_title", "issue_url"}


class InstallationProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    controller: str
    database: str
    operator_env: str
    api_url: str
    service: str = Field(pattern=_NAME)
    supervisor_unit: str = Field(pattern=_NAME)
    supervisor_state: str
    state_dir: str
    hold_files: list[str] = Field(min_length=1, max_length=8)
    arming_file: str
    github_user: str = Field(pattern=r"^[a-z_][a-z0-9_-]{0,31}$")
    workspace_user: str = Field(pattern=r"^[a-z_][a-z0-9_-]{0,31}$")
    protected_files: list[str] = Field(min_length=1, max_length=16)
    version_records: dict[str, str] = Field(default_factory=dict, max_length=8)

    @field_validator("controller", "database", "operator_env", "supervisor_state", "state_dir", "arming_file")
    @classmethod
    def absolute(cls, value):
        if not Path(value).is_absolute():
            raise ValueError("absolute_path_required")
        return value

    @model_validator(mode="after")
    def installation(self):
        url = urlsplit(self.api_url)
        if (url.scheme != "http" or url.hostname not in {"127.0.0.1", "::1", "localhost"}
                or url.username or url.password or url.query or url.fragment or url.path.rstrip("/") != "/api/v1"):
            raise ValueError("loopback_api_required")
        for relative in [*self.protected_files, *self.version_records]:
            if Path(relative).is_absolute() or ".." in Path(relative).parts:
                raise ValueError("relative_profile_path_required")
        if any(not Path(path).is_absolute() for path in self.hold_files):
            raise ValueError("absolute_hold_path_required")
        if any(not re.fullmatch(_NAME, key) for key in self.version_records.values()):
            raise ValueError("invalid_version_field")
        return self


class AcceptedPull(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    number: int = Field(gt=0)
    head: str = Field(pattern=_SHA)
    base: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9_./-]*$")
    checks: list[str] = Field(min_length=1, max_length=32)


class UpgradeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation_id: str = Field(pattern=_NAME)
    expected_head: str = Field(pattern=_SHA)
    target_head: str = Field(pattern=_SHA)
    candidate: str
    accepted_pulls: list[AcceptedPull] = Field(min_length=1, max_length=8)
    reviewed_files: dict[str, str] = Field(min_length=1, max_length=128)
    review_file: str
    review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    proof_receipt: str
    checkpoint_messages: dict[str, int] = Field(default_factory=dict, max_length=64)


class IntegrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation_id: str = Field(pattern=_NAME)
    work_item_id: int = Field(gt=0)
    expected_head: str = Field(pattern=_SHA)
    accepted_pull: AcceptedPull
    accepted_tip: str = Field(pattern=_SHA)
    checkpoint_message: int = Field(gt=0)


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def read_json(path, limit=65536, *, private=False):
    path = Path(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
            raise ValueError("invalid_input_file")
        if private and (metadata.st_uid not in {0, os.geteuid()} or metadata.st_mode & 0o077):
            raise ValueError("private_profile_required")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("input_too_large")
    def unique(pairs):
        value = {}
        for key, field in pairs:
            if key in value:
                raise ValueError("duplicate_field")
            value[key] = field
        return value
    return json.loads(raw, object_pairs_hook=unique)


class Maintenance:
    def __init__(self, profile):
        self.profile = profile

    def run(self, argv, *, user=None, timeout=30):
        if user and os.geteuid() != 0 and pwd.getpwuid(os.geteuid()).pw_name != user:
            raise ValueError("maintenance_user_unavailable")
        prefix = ["/usr/sbin/runuser", "-u", user, "--"] if user and os.geteuid() == 0 else []
        result = subprocess.run(prefix + argv, cwd="/tmp", capture_output=True, timeout=timeout)
        if result.returncode:
            # Raw process output can contain credentials or private settings.
            raise ValueError("maintenance_command_failed")
        if len(result.stdout) > 16 * 1024 * 1024:
            raise ValueError("maintenance_output_too_large")
        return result.stdout

    def git(self, path, *args, user=None):
        return self.run(["git", "-c", "safe.directory=" + str(path), "-c", "core.hooksPath=/dev/null",
                         "-C", str(path), *args], user=user, timeout=60)

    def rows(self, query, values=()):
        with sqlite3.connect(Path(self.profile.database).resolve().as_uri() + "?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(query, values).fetchmany(4097)
            if len(rows) > 4096:
                raise ValueError("maintenance_read_limit")
            return [dict(row) for row in rows]

    def api(self, method, path, body=None):
        # Read the secret at use time. Never retain it in operation evidence.
        config = dict(line.split("=", 1) for line in Path(self.profile.operator_env).read_text().splitlines()
                      if "=" in line and not line.startswith("#"))
        token = config.get("OPERATOR_TOKEN", "").strip().strip('"').strip("'")
        if not token:
            raise ValueError("operator_token_unconfigured")
        request = urllib.request.Request(self.profile.api_url.rstrip("/") + path,
            data=None if body is None else json.dumps(body).encode(), method=method,
            headers={"Content-Type":"application/json", "X-Deck-Operator-Token":token})
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read(2 * 1024 * 1024))

    def safety(self):
        if any(Path(path).exists() or Path(path).is_symlink() for path in self.profile.hold_files):
            raise ValueError("safety_hold_exists")
        if self.run(["systemctl", "is-active", self.profile.supervisor_unit]).strip() != b"active":
            raise ValueError("supervisor_not_active")
        value = read_json(self.profile.supervisor_state)
        tick = datetime.fromisoformat(value["last_tick"])
        if tick.tzinfo is None or not 0 <= (datetime.now(timezone.utc)-tick).total_seconds() <= 30:
            raise ValueError("supervisor_observation_unknown")

    def accepted(self, pull):
        def gh(endpoint):
            return json.loads(self.run(["gh", "api", endpoint], user=self.profile.github_user))
        actual = gh(f"repos/{pull.repository}/pulls/{pull.number}")
        if (not actual.get("merged") or actual["head"]["sha"] != pull.head
                or actual["base"]["ref"] != pull.base):
            raise ValueError("accepted_pull_changed")
        checks = gh(f"repos/{pull.repository}/commits/{pull.head}/check-runs?per_page=100")
        if checks.get("total_count", 101) > 100:
            raise ValueError("accepted_checks_incomplete")
        for name in pull.checks:
            matching = [row for row in checks["check_runs"] if row.get("name") == name
                        and row.get("app",{}).get("slug") == "github-actions" and row.get("head_sha") == pull.head]
            if not matching or any(row.get("status") != "completed" or row.get("conclusion") != "success" for row in matching):
                raise ValueError("accepted_check_not_successful")
        return actual["merge_commit_sha"]

    def source(self, path, *, user=None):
        if self.git(path, "status", "--porcelain", "--untracked-files=all", user=user):
            raise ValueError("clean_checkpoint_required")
        if self.git(path, "ls-files", "-u", user=user):
            raise ValueError("unmerged_source")
        for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
            if self.git(path, "rev-parse", "--git-path", name, user=user).strip():
                candidate = Path(self.git(path, "rev-parse", "--git-path", name, user=user).decode().strip())
                if (candidate if candidate.is_absolute() else Path(path)/candidate).exists():
                    raise ValueError("source_operation_in_progress")
        return {"head":self.git(path,"rev-parse","HEAD",user=user).decode().strip(),
                "tree":self.git(path,"rev-parse","HEAD^{tree}",user=user).decode().strip(),
                "branch":self.git(path,"branch","--show-current",user=user).decode().strip()}

    def checkpoint(self, item, workspace, operation, message_id, head):
        messages = self.rows("SELECT sender_member_id,created_at,payload FROM mail_messages WHERE id=?", (message_id,))
        members = self.rows("SELECT id FROM mail_team_members WHERE team_slot_id=? ORDER BY updated_at DESC,id DESC LIMIT 1",
                            (item["owner_slot_id"],))
        sessions = self.rows("SELECT id,created_at,last_seen_at,bound_pane_pid,bound_pane_proc_start FROM mail_agent_sessions "
            "WHERE member_id=? AND team_slot_id=? AND source='mcp' AND closed_at IS NULL AND mailbox_status='connected' "
            "AND capability_token_hash IS NOT NULL ORDER BY id DESC LIMIT 1", (members[0]["id"], item["owner_slot_id"])) if members else []
        if len(messages) != 1 or not sessions or messages[0]["sender_member_id"] != members[0]["id"]:
            raise ValueError("owner_checkpoint_unavailable")
        message, session = messages[0], sessions[0]
        stamp = lambda value: datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc)-stamp(message["created_at"])).total_seconds()
        if (not 0 <= age <= 900 or stamp(message["created_at"]) < stamp(session["created_at"])
                or not 0 <= (datetime.now(timezone.utc)-stamp(session["last_seen_at"])).total_seconds() <= MCP_HEARTBEAT_TTL_SECONDS
                or session["bound_pane_pid"] != workspace["leased_owner_pid"]
                or session["bound_pane_proc_start"] != workspace["leased_owner_proc_start"]):
            raise ValueError("owner_checkpoint_changed")
        payload = json.loads(message["payload"]) if isinstance(message["payload"], str) else message["payload"]
        expected = {"kind":"factory_maintenance_checkpoint", "operation":operation,
                    "work_item_id":item["id"], "source_head":head, "no_inflight_operations":True}
        if not isinstance(payload,dict) or any(payload.get(key) != value for key,value in expected.items()):
            raise ValueError("owner_checkpoint_not_confirmed")
        self.process(workspace["leased_owner_pid"],workspace["leased_owner_proc_start"])
        return {"message":message_id,"member":members[0]["id"],"generation":session["id"]}

    def process(self, pid, expected):
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")",1)[1].split()
        if fields[0] in {"T","t","Z","X","x"} or fields[19] != str(expected):
            raise ValueError("native_process_changed")

    def authority(self, item_id=None):
        result = {}
        # One read transaction prevents a mixed snapshot across related tables.
        with sqlite3.connect(Path(self.profile.database).resolve().as_uri()+'?mode=ro',uri=True) as db:
            db.row_factory=sqlite3.Row;db.execute('BEGIN')
            for table in _TABLES:
                if not db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone(): continue
                field='id' if table=='github_work_items' else ('leased_item_id' if table=='github_workspaces' else 'work_item_id')
                where=' WHERE '+field+'=?' if item_id is not None else ''
                rows=db.execute('SELECT * FROM "'+table+'"'+where+' ORDER BY id',() if item_id is None else (item_id,)).fetchmany(4097)
                if len(rows)>4096: raise ValueError('maintenance_read_limit')
                result[table]=[{k:v for k,v in dict(row).items() if k not in _VOLATILE} for row in rows]
            if item_id is not None:
                row=db.execute('SELECT * FROM team_github_scopes WHERE id=(SELECT scope_id FROM github_work_items WHERE id=?)',(item_id,)).fetchone()
                omitted=_VOLATILE|{'last_polled_at','last_poll_error','auth_state'}
                result['scope']={k:v for k,v in dict(row).items() if k not in omitted} if row else None
        return digest(result)

    def bindings(self, slot_id=None):
        where=' WHERE slot_id=?' if slot_id is not None else ''
        values = self.rows("SELECT preset_id,slot_id,pane_pid,pane_proc_start,tmux_target FROM agent_pane_bindings"+where+" ORDER BY slot_id",
                           () if slot_id is None else (slot_id,))
        for row in values:
            self.process(row["pane_pid"],row["pane_proc_start"])
        return values

    def generations(self, slot_id=None):
        """Retain authenticated generations without retaining private launch data."""
        result=[]
        for binding in self.bindings(slot_id):
            members=self.rows("SELECT id,team_preset_id FROM mail_team_members WHERE team_slot_id=? ORDER BY updated_at DESC,id DESC LIMIT 1",(binding["slot_id"],))
            if not members: raise ValueError("current_member_unavailable")
            rows=self.rows("SELECT id,pid,created_at,last_seen_at,provider,cwd,bound_pane_pid,bound_pane_proc_start FROM mail_agent_sessions "
                "WHERE member_id=? AND source='mcp' AND closed_at IS NULL AND mailbox_status='connected' "
                "AND capability_token_hash IS NOT NULL ORDER BY id DESC LIMIT 1",(members[0]["id"],))
            if not rows: raise ValueError("current_generation_unavailable")
            row=rows[0]
            fields=Path(f"/proc/{row['pid']}/stat").read_text().rsplit(")",1)[1].split()
            self.process(row["pid"],fields[19])
            boot=next(int(line.split()[1]) for line in Path('/proc/stat').read_text().splitlines() if line.startswith('btime '))
            born=datetime.fromtimestamp(boot+int(fields[19])/os.sysconf('SC_CLK_TCK'),timezone.utc)
            registered=datetime.fromisoformat(row["created_at"]).replace(tzinfo=timezone.utc)
            seen=datetime.fromisoformat(row["last_seen_at"]).replace(tzinfo=timezone.utc)
            if (born>registered or not 0<=(datetime.now(timezone.utc)-seen).total_seconds()<=MCP_HEARTBEAT_TTL_SECONDS
                    or row['bound_pane_pid']!=binding['pane_pid'] or row['bound_pane_proc_start']!=binding['pane_proc_start']):
                raise ValueError("current_generation_changed")
            from types import SimpleNamespace
            from app.services.owner_observation_pause import _process_identity
            slots=self.rows('SELECT provider,launch_options,preset_id FROM agent_team_slots WHERE id=?',(binding['slot_id'],))
            if (len(slots)!=1 or row['provider']!=slots[0]['provider']
                    or members[0]['team_preset_id']!=binding['preset_id'] or slots[0]['preset_id']!=binding['preset_id']):
                raise ValueError('current_slot_changed')
            options=json.loads(slots[0]['launch_options'] or '{}')
            _process_identity(SimpleNamespace(provider=slots[0]['provider'],launch_options=options),
                SimpleNamespace(pid=row['pid'],created_at=registered.replace(tzinfo=None),cwd=row['cwd']),
                SimpleNamespace(leased_owner_pid=binding['pane_pid'],leased_owner_proc_start=binding['pane_proc_start']))
            result.append({"slot":binding['slot_id'],"member":members[0]['id'],"session":row['id'],
                           "pid":row['pid'],"process_start":fields[19],"created_at":row['created_at'],
                           "slot_identity":digest(slots[0])})
        return result

    def record(self, operation_id, value, *, first=False):
        directory = Path(self.profile.state_dir)/"maintenance"
        directory.mkdir(mode=0o700,exist_ok=True)
        path = directory/(operation_id+".json")
        if first:
            descriptor = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(descriptor,"w") as stream: json.dump(value,stream,indent=2)
        else:
            descriptor, temporary = tempfile.mkstemp(dir=directory)
            try:
                with os.fdopen(descriptor,"w") as stream:
                    json.dump(value,stream,indent=2);stream.flush();os.fsync(stream.fileno())
                os.replace(temporary,path)
            finally: Path(temporary).unlink(missing_ok=True)
        return str(path)

    def integration_update(self, request):
        self.safety()
        items = self.rows("SELECT * FROM github_work_items WHERE id=?",(request.work_item_id,))
        if len(items)!=1 or items[0]["dispatch_status"]!="dispatched": raise ValueError("active_owner_required")
        item=items[0];scope=self.rows("SELECT * FROM team_github_scopes WHERE id=?",(item["scope_id"],))[0]
        policy=json.loads(item["delivery_policy"] or "{}")
        mode=policy.get("accepted_base_update","disabled")
        if mode not in {"fast_forward","merge"}: raise ValueError("accepted_base_updates_disabled")
        required=policy.get('required_checks',[])
        if (any(check.get('app_slug','github-actions')!='github-actions' for check in required)
                or not {check['name'] for check in required}.issubset(request.accepted_pull.checks)):
            raise ValueError('configured_integration_checks_missing')
        if request.accepted_pull.repository != scope["repo_owner"]+"/"+scope["repo_name"]: raise ValueError("integration_repository_changed")
        if scope["base_ref"] != "origin/"+request.accepted_pull.base: raise ValueError("integration_branch_changed")
        tip=self.accepted(request.accepted_pull)
        if tip!=request.accepted_tip: raise ValueError("accepted_tip_changed")
        workspace=self.rows("SELECT * FROM github_workspaces WHERE leased_item_id=?",(item["id"],))
        if len(workspace)!=1 or not workspace[0]["enabled"]: raise ValueError("workspace_binding_changed")
        workspace=workspace[0];path=workspace["path"];user=self.profile.workspace_user
        before=self.source(path,user=user)
        if before["head"]!=request.expected_head: raise ValueError("checkpoint_head_changed")
        checkpoint=self.checkpoint(item,workspace,"integration_update",request.checkpoint_message,before["head"])
        authority=self.authority(item['id']);bindings=self.bindings(item['owner_slot_id'])
        generations=self.generations(item['owner_slot_id'])
        self.git(path,"fetch","origin",request.accepted_pull.base,user=user)
        observed=self.git(path,"rev-parse","refs/remotes/origin/"+request.accepted_pull.base,user=user).decode().strip()
        if observed!=tip: raise ValueError("integration_tip_not_current")
        if self.source(path,user=user)!=before or self.authority(item['id'])!=authority or self.bindings(item['owner_slot_id'])!=bindings or self.generations(item['owner_slot_id'])!=generations: raise ValueError("checkpoint_context_changed")
        self.safety()
        record={"operation":"integration_update","status":"prepared","started_at":now(),"source_before":before,"checkpoint":checkpoint,"accepted_tip":tip}
        self.record(request.operation_id,record,first=True)
        try:
            args=["merge","--ff-only",tip] if mode=="fast_forward" else ["merge","--no-edit","--no-verify","--no-gpg-sign","--no-stat",tip]
            self.git(path,*args,user=user)
            after=self.source(path,user=user)
            self.git(path,"merge-base","--is-ancestor",before["head"],after["head"],user=user)
            self.git(path,"merge-base","--is-ancestor",tip,after["head"],user=user)
            if self.authority(item['id'])!=authority or self.bindings(item['owner_slot_id'])!=bindings or self.generations(item['owner_slot_id'])!=generations: raise ValueError("post_update_context_changed")
            self.safety();record.update(status="completed",source_after=after,finished_at=now())
        except Exception as error:
            # Keep commits and any merge conflicts. Never reset, abort or force-push.
            record.update(status="needs_coordination",failure=type(error).__name__,finished_at=now())
            self.record(request.operation_id,record)
            try:
                self.api('POST',f"/agent-teams/presets/{scope['preset_id']}/work-items/{item['id']}/integration-outcome",
                    {'operation_id':request.operation_id,'expected_dispatch_nonce':item['dispatch_nonce'],
                     'expected_scope_revision':item['active_scope_revision'],'expected_owner_slot':item['owner_slot_id'],
                     'outcome':'needs_coordination'})
                record['controller_notice']='recorded'
            except Exception: record['controller_notice']='uncertain'
            self.record(request.operation_id,record);raise
        self.record(request.operation_id,record)
        try:
            self.api('POST',f"/agent-teams/presets/{scope['preset_id']}/work-items/{item['id']}/integration-outcome",
                {'operation_id':request.operation_id,'expected_dispatch_nonce':item['dispatch_nonce'],
                 'expected_scope_revision':item['active_scope_revision'],'expected_owner_slot':item['owner_slot_id'],
                 'outcome':'completed'})
            record['controller_notice']='recorded'
        except Exception:
            record['controller_notice']='uncertain'
        return self.record(request.operation_id,record)

    def upgrade(self, request):
        """Upgrade only the controller. Leave autonomy paused for explicit activation."""
        self.safety()
        controller=Path(self.profile.controller);candidate=Path(request.candidate)
        if not candidate.is_absolute(): raise ValueError("absolute_candidate_required")
        old=self.source(controller);new=self.source(candidate)
        if old['head']!=request.expected_head or new['head']!=request.target_head:
            raise ValueError("controller_version_changed")
        review=Path(request.review_file).read_bytes()
        if (hashlib.sha256(review).hexdigest()!=request.review_sha256 or not review.startswith(b'ACCEPT\n')
                or request.target_head.encode() not in review or digest(request.reviewed_files).encode() not in review):
            raise ValueError("runtime_review_binding_invalid")
        proof=read_json(request.proof_receipt)
        if (not proof.get('eligible') or proof.get('exit_code')!=0
                or proof['source_before']!=proof['source_after']
                or proof['source_before']['head']!=request.target_head or proof['source_before']['status']
                or proof['source_before']['tree']!=new['tree']
                or hashlib.sha256(Path(proof['log']).read_bytes()).hexdigest()!=proof['log_sha256']):
            raise ValueError("runtime_proof_invalid")
        accepted=[self.accepted(pull) for pull in request.accepted_pulls]
        self.git(controller,'fetch',str(candidate),request.target_head)
        files=self.git(candidate,'diff','--name-only',request.expected_head,request.target_head).decode().splitlines()
        if set(files)!=set(request.reviewed_files): raise ValueError("runtime_change_scope_changed")
        for relative, expected in request.reviewed_files.items():
            if Path(relative).is_absolute() or '..' in Path(relative).parts or relative in self.profile.protected_files:
                raise ValueError("runtime_change_path_invalid")
            actual=hashlib.sha256(self.git(candidate,'show',request.target_head+':'+relative)).hexdigest()
            if actual!=expected: raise ValueError("reviewed_runtime_file_changed")
        protected={name:hashlib.sha256((controller/name).read_bytes()).hexdigest() for name in self.profile.protected_files}
        presets=self.rows('SELECT id,autonomy_enabled FROM agent_team_presets ORDER BY id')
        sources={};checkpoints=[]
        for item in self.rows("SELECT * FROM github_work_items WHERE dispatch_status IN ('dispatched','verifying') ORDER BY id"):
            if item['dispatch_status']=='verifying': raise ValueError("verification_in_progress")
            workspace=self.rows('SELECT * FROM github_workspaces WHERE leased_item_id=?',(item['id'],))
            if len(workspace)!=1: raise ValueError("active_workspace_unavailable")
            workspace=workspace[0];source=self.source(workspace['path'],user=self.profile.workspace_user)
            message=request.checkpoint_messages.get(str(item['id']))
            if not message: raise ValueError("active_owner_checkpoint_required")
            checkpoints.append(self.checkpoint(item,workspace,'controller_upgrade',message,source['head']))
            sources[workspace['path']]=source
        bindings=self.bindings();generations=self.generations()
        record={'operation':'controller_upgrade','status':'prepared','started_at':now(),'old_head':old['head'],
            'target_head':new['head'],'review_sha256':request.review_sha256,'accepted_merges':accepted,
            'checkpoints':checkpoints,'original_autonomy':presets,'sources':sources}
        self.record(request.operation_id,record,first=True)
        try:
            Path(self.profile.arming_file).unlink(missing_ok=True)
            for preset in presets:
                self.api('PATCH',f"/agent-teams/presets/{preset['id']}",{'autonomy_enabled':False})
            # Polling must see the pause before stopping the controller. Supervision stays active.
            deadline=time.monotonic()+45
            while True:
                self.safety()
                state=read_json(self.profile.supervisor_state)
                if state.get('autonomy_enabled') is False: break
                if time.monotonic()>=deadline: raise ValueError('supervisor_pause_unconfirmed')
                time.sleep(.5)
            for preset in presets:
                if self.api('GET',f"/agent-teams/presets/{preset['id']}")['autonomy_enabled']:
                    raise ValueError('autonomy_pause_unconfirmed')
            authority=self.authority()
            if self.bindings()!=bindings or self.generations()!=generations: raise ValueError('native_generation_changed')
            for path, source in sources.items():
                if self.source(path,user=self.profile.workspace_user)!=source: raise ValueError('owner_source_changed')
            backup=Path(self.profile.state_dir)/'maintenance'/(request.operation_id+'.sqlite3')
            descriptor=os.open(backup,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(descriptor)
            with sqlite3.connect(Path(self.profile.database).resolve().as_uri()+'?mode=ro',uri=True) as db:
                with sqlite3.connect(backup) as destination: db.backup(destination)
            self.run(['systemctl','stop',self.profile.service])
            properties=dict(line.split('=',1) for line in self.run(['systemctl','show',self.profile.service,
                '--property=ActiveState,SubState,MainPID,ControlGroup']).decode().splitlines())
            if properties.get('ActiveState')!='inactive' or properties.get('SubState')!='dead' or properties.get('MainPID')!='0':
                raise ValueError('controller_termination_unknown')
            if properties.get('ControlGroup'):
                group=Path('/sys/fs/cgroup')/properties['ControlGroup'].lstrip('/')/'cgroup.procs'
                if group.exists() and group.read_text().strip(): raise ValueError('controller_processes_remain')
            self.safety()
            if self.authority()!=authority or self.bindings()!=bindings or self.generations()!=generations: raise ValueError('stopped_context_changed')
            self.git(controller,'checkout','--detach',request.target_head)
            if self.source(controller)['head']!=request.target_head: raise ValueError('controller_checkout_unconfirmed')
            for relative, key in self.profile.version_records.items():
                path=Path(self.profile.state_dir)/relative;value=read_json(path)
                if value.get(key)!=request.expected_head: raise ValueError('version_record_changed')
                value[key]=request.target_head
                descriptor, temporary=tempfile.mkstemp(dir=path.parent)
                try:
                    with os.fdopen(descriptor,'w') as stream:
                        json.dump(value,stream,indent=2);stream.flush();os.fsync(stream.fileno())
                    os.replace(temporary,path)
                finally: Path(temporary).unlink(missing_ok=True)
            self.run(['systemctl','start',self.profile.service])
            deadline=time.monotonic()+30
            while True:
                try:
                    health=self.api('GET','/health')
                    if health.get('status')!='ok': raise ValueError('controller_health_unknown')
                    break
                except OSError:
                    if time.monotonic()>=deadline: raise ValueError('controller_health_unknown')
                    time.sleep(.5)
            self.safety()
            if self.authority()!=authority or self.bindings()!=bindings or self.generations()!=generations: raise ValueError('deployed_context_changed')
            for path, source in sources.items():
                if self.source(path,user=self.profile.workspace_user)!=source: raise ValueError('owner_source_changed')
            for name, expected in protected.items():
                if hashlib.sha256((controller/name).read_bytes()).hexdigest()!=expected: raise ValueError('protected_file_changed')
            for preset in presets:
                if self.api('GET',f"/agent-teams/presets/{preset['id']}")['autonomy_enabled']: raise ValueError('autonomy_unexpectedly_active')
            record.update(status='deployed_paused',finished_at=now(),authority_preserved=True)
        except Exception as error:
            record.update(status='paused_needs_inspection',failure=type(error).__name__,finished_at=now())
            Path(self.profile.arming_file).unlink(missing_ok=True)
            for preset in presets:
                try: self.api('PATCH',f"/agent-teams/presets/{preset['id']}",{'autonomy_enabled':False})
                except Exception: pass
            self.record(request.operation_id,record);raise
        return self.record(request.operation_id,record)
