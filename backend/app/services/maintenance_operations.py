"""Operator maintenance primitives. Profiles contain data, never executable hooks."""
from __future__ import annotations

from datetime import datetime, timezone
import asyncio
from contextlib import contextmanager
import hashlib
import json
import os
import pwd
from pathlib import Path
import re
import signal
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
           "github_attempt_scope_revisions", "github_delivery_policy_events", "github_owner_followups",
           "github_accepted_source_imports")
_GLOBAL_TABLES = ("team_github_scopes", "agent_team_presets", "agent_team_slots",
                  "github_backlog_coordination")
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
    check_apps: dict[str, str] = Field(default_factory=dict, max_length=32)

    @model_validator(mode="after")
    def applications(self):
        if (set(self.check_apps) - set(self.checks)
                or any(not re.fullmatch(_NAME, app) for app in self.check_apps.values())):
            raise ValueError("invalid_check_application")
        return self


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
    checkpoint_message: int | None = Field(default=None,gt=0)


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
        self.reservation_deadline = None

    def run(self, argv, *, user=None, timeout=30):
        if self.reservation_deadline is not None:
            remaining=self.reservation_deadline-time.monotonic()
            if remaining<=0: raise ValueError('maintenance_reservation_deadline')
            timeout=min(timeout,remaining)
        if user and os.geteuid() != 0 and pwd.getpwuid(os.geteuid()).pw_name != user:
            raise ValueError("maintenance_user_unavailable")
        prefix = ["/usr/sbin/runuser", "-u", user, "--"] if user and os.geteuid() == 0 else []
        process = subprocess.Popen(prefix + argv, cwd="/tmp", stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        try:
            output, _errors = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Git effects cannot roll back with a database transaction. Settle
            # its whole child group before returning control to a reservation.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                process.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                raise ValueError("maintenance_child_settlement_unknown") from None
            # An orphan zombie cannot write source. Refuse any remaining live
            # group member. Do not read argv, environment or native transcripts.
            deadline=time.monotonic()+1
            while True:
                unsettled=False
                entries=list(Path('/proc').iterdir())
                if len(entries)>16384: raise ValueError('maintenance_child_settlement_unknown')
                for entry in entries:
                    if not entry.name.isdigit(): continue
                    try: fields=(entry/'stat').read_text().rsplit(')',1)[1].split()
                    except FileNotFoundError: continue
                    if fields[2]==str(process.pid) and fields[0] not in {'Z','X','x'}:
                        unsettled=True;break
                if not unsettled: raise ValueError('maintenance_command_timeout_settled') from None
                if time.monotonic()>=deadline: raise ValueError('maintenance_child_settlement_unknown') from None
                time.sleep(.02)
        if process.returncode:
            # Raw process output can contain credentials or private settings.
            raise ValueError("maintenance_command_failed")
        if len(output) > 16 * 1024 * 1024:
            raise ValueError("maintenance_output_too_large")
        return output

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
        checks = self.current_checks(pull)
        # Workflow rows cover a new queued same-head run even before its jobs
        # exist. Keep actual failures and all recorded external application IDs.
        if not checks or any(row.get("status") != "completed" or row.get("conclusion") not in {"success","neutral","skipped"}
                             for row in checks):
            raise ValueError("accepted_check_not_successful")
        for name in pull.checks:
            matching = [row for row in checks if row.get("name") == name
                        and row.get("app",{}).get("slug") == pull.check_apps.get(name,"github-actions")
                        and row.get("head_sha") == pull.head]
            if not matching or any(row.get("status") != "completed" or row.get("conclusion") != "success" for row in matching):
                raise ValueError("accepted_check_not_successful")
        return actual["merge_commit_sha"]

    def current_checks(self, pull):
        import httpx
        from app.services.github_check_observation import observe_checks
        token = self.run(["gh", "auth", "token"], user=self.profile.github_user).decode().strip()
        if not token:
            raise ValueError("github_identity_unavailable")
        owner, repo = pull.repository.split("/")
        async def read():
            async with httpx.AsyncClient(base_url="https://api.github.com") as client:
                timeout=45 if self.reservation_deadline is None else min(45,self.reservation_deadline-time.monotonic())
                if timeout<=0: raise ValueError('maintenance_reservation_deadline')
                return await asyncio.wait_for(observe_checks(client, {"Authorization":"Bearer "+token,
                    "Accept":"application/vnd.github+json"}, owner, repo, pull.head),timeout=timeout)
        return asyncio.run(read())

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

    def approved_owner(self, item, workspace):
        """Use the same actual approval, ACK, lease and identity guards as recovery."""
        from sqlalchemy.engine import URL
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from app.models.database import GithubWorkItem, TeamGithubScope
        from app.services.owner_observation_pause import bound_authority
        async def inspect():
            engine=create_async_engine(URL.create('sqlite+aiosqlite',database=str(Path(self.profile.database).resolve())))
            try:
                async with AsyncSession(engine,expire_on_commit=False) as db:
                    actual=await db.get(GithubWorkItem,item['id'])
                    if actual is None or actual.dispatch_status!='dispatched':
                        raise ValueError('approved_owner_required')
                    scope=await db.get(TeamGithubScope,actual.scope_id)
                    if scope is None: raise ValueError('approved_scope_required')
                    fingerprint,current,session=await bound_authority(db,scope,actual)
                    if current.id!=workspace['id']:
                        raise ValueError('owner_workspace_changed')
                    return {'authority':fingerprint,'workspace_id':current.id,'generation':session.id}
            finally:
                await engine.dispose()
        return asyncio.run(inspect())

    def checkpoint_templates(self, request):
        """Prepare data for an owner's confirmation. This makes no hold or claim."""
        if isinstance(request,IntegrationRequest):
            items=self.rows('SELECT * FROM github_work_items WHERE id=?',(request.work_item_id,))
            operation='integration_update'
        else:
            items=self.rows("SELECT * FROM github_work_items WHERE dispatch_status IN ('dispatched','verifying') ORDER BY id")
            operation='controller_upgrade'
        payloads=[]
        for item in items:
            if item['dispatch_status']!='dispatched': raise ValueError('active_owner_required')
            workspaces=self.rows('SELECT * FROM github_workspaces WHERE leased_item_id=?',(item['id'],))
            if len(workspaces)!=1: raise ValueError('active_workspace_unavailable')
            workspace=workspaces[0];source=self.source(workspace['path'],user=self.profile.workspace_user)
            if isinstance(request,IntegrationRequest) and source['head']!=request.expected_head:
                raise ValueError('checkpoint_head_changed')
            owner=self.approved_owner(item,workspace);self.generations(item['owner_slot_id'])
            payloads.append({'kind':'factory_maintenance_checkpoint','operation':operation,
                'operation_id':request.operation_id,'work_item_id':item['id'],'source_head':source['head'],
                'owner_context_sha256':digest(owner),'no_inflight_operations':True,'hold_until_release':True})
        if isinstance(request,IntegrationRequest) and len(payloads)!=1:
            raise ValueError('active_owner_required')
        return {'status':'template_requires_owner_confirmation','payloads':payloads}

    def current_sessions(self, member_id, slot_id):
        from app.utils.peer_process import process_is_confirmed_dead
        rows=self.rows("SELECT id,pid,created_at,last_seen_at,provider,cwd,bound_pane_pid,bound_pane_proc_start "
            "FROM mail_agent_sessions WHERE member_id=? AND team_slot_id=? AND source='mcp' AND closed_at IS NULL "
            "AND mailbox_status='connected' AND capability_token_hash IS NOT NULL ORDER BY id DESC LIMIT 257",
            (member_id,slot_id))
        if not rows or len(rows)>256: raise ValueError('current_generation_unavailable')
        live=[]
        for row in rows:
            try:
                seen=datetime.fromisoformat(row['last_seen_at']).replace(tzinfo=timezone.utc)
            except (ValueError,TypeError):
                raise ValueError('current_generation_unavailable') from None
            if not 0<=(datetime.now(timezone.utc)-seen).total_seconds()<=MCP_HEARTBEAT_TTL_SECONDS:
                continue
            # Stopped, denied and malformed observations remain competitors.
            # Only a confirmed dead process can be omitted.
            if not process_is_confirmed_dead(row['pid']):
                live.append(row)
        if len(live)!=1 or live[0]['id']!=rows[0]['id']:
            raise ValueError('current_generation_ambiguous')
        try:
            fields=Path(f"/proc/{live[0]['pid']}/stat").read_text().rsplit(')',1)[1].split()
            self.process(live[0]['pid'],fields[19])
        except (OSError,ValueError,TypeError,IndexError):
            raise ValueError('current_generation_unavailable') from None
        return live

    def checkpoint(self, item, workspace, operation, message_id, head, operation_id, owner):
        messages = self.rows("SELECT sender_member_id,created_at,payload,body_markdown FROM mail_messages WHERE id=?", (message_id,))
        members = self.rows("SELECT id FROM mail_team_members WHERE team_slot_id=? ORDER BY updated_at DESC,id DESC LIMIT 1",
                            (item["owner_slot_id"],))
        sessions=self.current_sessions(members[0]['id'],item['owner_slot_id']) if members else []
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
        if payload is None:
            # The standard authenticated MCP Mail tool sends only a body.
            # Accept one complete JSON object; never extract from prose.
            body = message.get("body_markdown")
            if not isinstance(body, str) or len(body.encode("utf-8")) > 65536:
                raise ValueError("owner_checkpoint_not_confirmed")
            def unique(pairs):
                value = {}
                for key, field in pairs:
                    if key in value:
                        raise ValueError("duplicate_checkpoint_field")
                    value[key] = field
                return value
            try:
                payload = json.loads(body, object_pairs_hook=unique)
            except (ValueError, TypeError):
                raise ValueError("owner_checkpoint_not_confirmed") from None
        expected = {"kind":"factory_maintenance_checkpoint", "operation":operation,
                    "operation_id":operation_id,"work_item_id":item["id"], "source_head":head,
                    "owner_context_sha256":digest(owner), "no_inflight_operations":True,"hold_until_release":True}
        if not isinstance(payload,dict) or any(payload.get(key) != value for key,value in expected.items()):
            raise ValueError("owner_checkpoint_not_confirmed")
        self.process(workspace["leased_owner_pid"],workspace["leased_owner_proc_start"])
        return {"message":message_id,"member":members[0]["id"],"generation":session["id"]}

    def consume_checkpoint(self, operation_id, checkpoint):
        # Persist outside SQLite: a Git mutation survives SQLite rollback.
        directory=Path(self.profile.state_dir)/'maintenance/checkpoint-claims'
        directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        path=directory/(str(checkpoint['message'])+'.json')
        descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'w') as stream:
            json.dump({'operation_id':operation_id,'checkpoint':checkpoint,'consumed_at':now()},stream)
            stream.flush();os.fsync(stream.fileno())

    @contextmanager
    def reservation(self):
        """Refuse contention. Keep all authority writers out of the Git boundary."""
        identity=self.database_identity()
        db=sqlite3.connect(self.profile.database,timeout=2)
        try:
            db.execute('BEGIN IMMEDIATE')
            self.reservation_deadline=time.monotonic()+75
            if self.database_identity()!=identity: raise ValueError('database_identity_changed')
            yield db
            if time.monotonic()>self.reservation_deadline: raise ValueError('maintenance_reservation_deadline')
            if self.database_identity()!=identity: raise ValueError('database_identity_changed')
            db.commit()
        finally:
            self.reservation_deadline=None
            db.rollback();db.close()

    def process(self, pid, expected):
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")",1)[1].split()
        if fields[0] in {"T","t","Z","X","x"} or fields[19] != str(expected):
            raise ValueError("native_process_changed")

    def authority(self, item_id=None):
        result = {}
        # One read transaction prevents a mixed snapshot across related tables.
        with sqlite3.connect(Path(self.profile.database).resolve().as_uri()+'?mode=ro',uri=True) as db:
            db.row_factory=sqlite3.Row;db.execute('BEGIN')
            for table in _TABLES + (_GLOBAL_TABLES if item_id is None else ()):
                if not db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
                    if table == 'github_accepted_source_imports': result[table] = []
                    continue
                field='id' if table=='github_work_items' else ('leased_item_id' if table=='github_workspaces' else 'work_item_id')
                where=' WHERE '+field+'=?' if item_id is not None else ''
                primary=[row['name'] for row in db.execute('PRAGMA table_info("'+table+'")') if row['pk']]
                if not primary: raise ValueError('maintenance_identity_unavailable')
                order=','.join('"'+name+'"' for name in primary)
                rows=db.execute('SELECT * FROM "'+table+'"'+where+' ORDER BY '+order,() if item_id is None else (item_id,)).fetchmany(4097)
                if len(rows)>4096: raise ValueError('maintenance_read_limit')
                omitted=_VOLATILE|({'autonomy_enabled'} if table=='agent_team_presets' else set())
                if table in {'team_github_scopes','github_backlog_coordination'}:
                    omitted=omitted|{'last_polled_at','last_poll_error','auth_state'}
                result[table]=[{k:v for k,v in dict(row).items() if k not in omitted} for row in rows]
            if item_id is not None:
                row=db.execute('SELECT * FROM team_github_scopes WHERE id=(SELECT scope_id FROM github_work_items WHERE id=?)',(item_id,)).fetchone()
                omitted=_VOLATILE|{'last_polled_at','last_poll_error','auth_state'}
                result['scope']={k:v for k,v in dict(row).items() if k not in omitted} if row else None
        return digest(result)

    def database_identity(self):
        metadata=Path(self.profile.database).stat()
        return {'device':metadata.st_dev,'inode':metadata.st_ino}

    def stop_controller(self):
        self.run(['systemctl','stop',self.profile.service])
        properties=dict(line.split('=',1) for line in self.run(['systemctl','show',self.profile.service,
            '--property=ActiveState,SubState,MainPID,ControlGroup']).decode().splitlines())
        if properties.get('ActiveState')!='inactive' or properties.get('SubState')!='dead' or properties.get('MainPID')!='0':
            raise ValueError('controller_termination_unknown')
        if properties.get('ControlGroup'):
            group=Path('/sys/fs/cgroup')/properties['ControlGroup'].lstrip('/')/'cgroup.procs'
            if group.exists() and group.read_text().strip():
                raise ValueError('controller_processes_remain')

    def failed_upgrade(self, operation_id, record, presets, error):
        """Independent cleanup steps. Report certainty rather than assumed OFF."""
        cleanup=[]
        record.update(status='failed_termination_unknown',failure=type(error).__name__,finished_at=now())
        try:
            Path(self.profile.arming_file).unlink(missing_ok=True)
            cleanup.append({'step':'arming_removal','status':'confirmed'})
        except Exception as failure:
            cleanup.append({'step':'arming_removal','status':'unknown','error':type(failure).__name__})
        try:
            current=self.rows('SELECT id,autonomy_enabled FROM agent_team_presets ORDER BY id')
            presets=list({row['id']:row for row in [*presets,*current]}.values())
        except Exception as failure:
            cleanup.append({'step':'preset_inventory','status':'unknown','error':type(failure).__name__})
        for preset in presets:
            try:
                endpoint=f"/agent-teams/presets/{preset['id']}"
                self.api('PATCH',endpoint,{'autonomy_enabled':False})
                if self.api('GET',endpoint)['autonomy_enabled']:
                    raise ValueError('autonomy_remains_active')
                cleanup.append({'step':'autonomy_off','preset_id':preset['id'],'status':'confirmed'})
            except Exception as failure:
                cleanup.append({'step':'autonomy_off','preset_id':preset['id'],'status':'unknown','error':type(failure).__name__})
        if record.get('cutover_started') or any(step['status']=='unknown' for step in cleanup):
            try:
                self.stop_controller()
                record['status']='failed_stopped_needs_inspection'
                cleanup.append({'step':'controller_stop','status':'confirmed'})
            except Exception as failure:
                cleanup.append({'step':'controller_stop','status':'unknown','error':type(failure).__name__})
        else:
            record['status']='failed_paused_needs_inspection'
        record['cleanup']=cleanup
        record['version_certainty']={}
        for relative,key in self.profile.version_records.items():
            try:
                value=read_json(Path(self.profile.state_dir)/relative).get(key)
                record['version_certainty'][relative]='original' if value==record['old_head'] else 'target' if value==record['target_head'] else 'unknown'
            except Exception:
                record['version_certainty'][relative]='unknown'
        # Evidence failure must never prevent the attempts above.
        try:
            self.record(operation_id,record)
        except Exception:
            pass

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
            rows=self.current_sessions(members[0]['id'],binding['slot_id'])
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

    def record_source_import(self, db, request, item, workspace, scope, after):
        """The held Git operation records its exact accepted import before release."""
        from app.services.accepted_source_imports import import_record_values, verified_import_snapshots
        from app.services.github_client import GithubTreeEntry
        from app.services.github_approval_service import github_approval_service
        if item['active_scope_revision'] == 0:
            return {'status':'not_applicable','paths':[]}
        db.row_factory = sqlite3.Row
        revision = db.execute("SELECT * FROM github_attempt_scope_revisions WHERE work_item_id=? "
            "AND dispatch_nonce=? AND revision=? AND status='active'",
            (item['id'], item['dispatch_nonce'], item['active_scope_revision'])).fetchone()
        if revision is None: raise ValueError('source_import_context_changed')
        revision = dict(revision)
        def tree(head):
            entries = self.git(workspace['path'], 'ls-tree', '-r', '-z', head,
                               user=self.profile.workspace_user).split(b'\0')
            if len(entries) > 50001: raise ValueError('source_import_tree_limit')
            result = {}
            for entry in entries:
                if not entry: continue
                identity, raw_path = entry.split(b'\t', 1)
                mode, kind, sha = identity.decode('ascii').split(' ')
                path = raw_path.decode('utf-8', errors='strict')
                if path in result: raise ValueError('source_import_tree_inconclusive')
                result[path] = GithubTreeEntry(path, mode, kind, sha)
            return result
        baseline, current, accepted = tree(revision['baseline_head_sha']), tree(after['head']), tree(request.accepted_tip)
        allowed = json.loads(revision['allowed_paths'])
        def value(entries, path):
            row = entries.get(path)
            return None if row is None else (row.mode, row.object_type, row.sha)
        outside = sorted(path for path in baseline.keys() | current.keys()
                         if not github_approval_service.path_is_allowed(path, allowed)
                         and value(baseline, path) != value(current, path))
        if not outside: return {'status':'not_needed','paths':[]}
        if len(outside) > 64: raise ValueError('source_import_path_limit')
        snapshots = verified_import_snapshots(baseline, current, accepted, allowed, outside)
        operation_id = 'import-' + hashlib.sha256(request.operation_id.encode()).hexdigest()
        values = import_record_values(item, revision, workspace, scope, operation_id=operation_id,
            request_sha256=digest(request.model_dump()), accepted_pull_number=request.accepted_pull.number,
            accepted_source_sha=request.accepted_pull.head, accepted_merge_sha=request.accepted_tip,
            observed_head_sha=after['head'], path_snapshots=snapshots)
        old = db.execute('SELECT * FROM github_accepted_source_imports WHERE operation_id=?',
                         (operation_id,)).fetchone()
        if old:
            expected = dict(values); expected['path_snapshots'] = json.dumps(snapshots)
            if any(old[key] != value for key,value in expected.items()):
                raise ValueError('source_import_replay_conflict')
            return {'status':'already_recorded','import_id':old['id'],'paths':outside}
        if db.execute('SELECT COUNT(*) FROM github_accepted_source_imports WHERE work_item_id=? '
                      'AND scope_revision_id=? AND context_sha256=?',
                      (item['id'], revision['id'], values['context_sha256'])).fetchone()[0] >= 64:
            raise ValueError('source_import_read_limit')
        values['path_snapshots'] = json.dumps(snapshots)
        values['created_at'] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=' ')
        columns = ','.join(values)
        cursor = db.execute('INSERT INTO github_accepted_source_imports (' + columns + ') VALUES ('
                            + ','.join('?' for _ in values) + ')', tuple(values.values()))
        return {'status':'recorded','import_id':cursor.lastrowid,'paths':outside}

    def integration_update(self, request):
        self.safety()
        items = self.rows("SELECT * FROM github_work_items WHERE id=?",(request.work_item_id,))
        if len(items)!=1 or items[0]["dispatch_status"]!="dispatched": raise ValueError("active_owner_required")
        item=items[0];scope=self.rows("SELECT * FROM team_github_scopes WHERE id=?",(item["scope_id"],))[0]
        policy=json.loads(item["delivery_policy"] or "{}")
        mode=policy.get("accepted_base_update","disabled")
        if mode not in {"fast_forward","merge"}: raise ValueError("accepted_base_updates_disabled")
        required=policy.get('required_checks',[])
        if (not {check['name'] for check in required}.issubset(request.accepted_pull.checks)
                or any(request.accepted_pull.check_apps.get(check['name'],'github-actions')!=check.get('app_slug','github-actions')
                       for check in required)):
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
        owner=self.approved_owner(item,workspace)
        checkpoint=self.checkpoint(item,workspace,"integration_update",request.checkpoint_message,before["head"],request.operation_id,owner)
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
            with self.reservation() as reservation:
                # Finish slow external observations before the final owner,
                # process, source and checkpoint freshness checks.
                if self.accepted(request.accepted_pull)!=tip: raise ValueError('accepted_tip_changed')
                self.safety()
                if self.authority(item['id'])!=authority or self.approved_owner(item,workspace)!=owner:
                    raise ValueError('reserved_owner_context_changed')
                if self.source(path,user=user)!=before or self.bindings(item['owner_slot_id'])!=bindings or self.generations(item['owner_slot_id'])!=generations:
                    raise ValueError('reserved_checkpoint_changed')
                self.checkpoint(item,workspace,'integration_update',request.checkpoint_message,before['head'],request.operation_id,owner)
                self.consume_checkpoint(request.operation_id,checkpoint)
                # The durable claim can wait on storage. Recheck freshness and
                # native lifetime immediately before Git. run() also enforces
                # the reservation deadline before it starts the child.
                if self.approved_owner(item,workspace)!=owner or self.generations(item['owner_slot_id'])!=generations:
                    raise ValueError('reserved_owner_context_changed')
                self.checkpoint(item,workspace,'integration_update',request.checkpoint_message,before['head'],request.operation_id,owner)
                args=["merge","--ff-only",tip] if mode=="fast_forward" else ["merge","--no-edit","--no-verify","--no-gpg-sign","--no-stat",tip]
                self.git(path,*args,user=user)
                after=self.source(path,user=user)
                self.git(path,"merge-base","--is-ancestor",before["head"],after["head"],user=user)
                self.git(path,"merge-base","--is-ancestor",tip,after["head"],user=user)
                if self.authority(item['id'])!=authority or self.approved_owner(item,workspace)!=owner or self.bindings(item['owner_slot_id'])!=bindings or self.generations(item['owner_slot_id'])!=generations:
                    raise ValueError("post_update_context_changed")
                self.safety()
                record['source_import'] = self.record_source_import(
                    reservation, request, item, workspace, scope, after)
                record.update(status="completed",source_after=after,finished_at=now())
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
        sources={};checkpoints=[];owner_contexts=[]
        for item in self.rows("SELECT * FROM github_work_items WHERE dispatch_status IN ('dispatched','verifying') ORDER BY id"):
            if item['dispatch_status']=='verifying': raise ValueError("verification_in_progress")
            workspace=self.rows('SELECT * FROM github_workspaces WHERE leased_item_id=?',(item['id'],))
            if len(workspace)!=1: raise ValueError("active_workspace_unavailable")
            workspace=workspace[0];source=self.source(workspace['path'],user=self.profile.workspace_user)
            message=request.checkpoint_messages.get(str(item['id']))
            if not message: raise ValueError("active_owner_checkpoint_required")
            owner=self.approved_owner(item,workspace)
            checkpoints.append(self.checkpoint(item,workspace,'controller_upgrade',message,source['head'],request.operation_id,owner))
            owner_contexts.append((item,workspace,source,owner,message))
            sources[workspace['path']]=source
        bindings=self.bindings();generations=self.generations()
        baseline=self.authority();database_identity=self.database_identity()
        record={'operation':'controller_upgrade','status':'prepared','started_at':now(),'old_head':old['head'],
            'target_head':new['head'],'review_sha256':request.review_sha256,'accepted_merges':accepted,
            'checkpoints':checkpoints,'original_autonomy':presets,'sources':sources,'cutover_started':False}
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
            if authority!=baseline or self.database_identity()!=database_identity:
                raise ValueError('pause_context_changed')
            if self.bindings()!=bindings or self.generations()!=generations: raise ValueError('native_generation_changed')
            for path, source in sources.items():
                if self.source(path,user=self.profile.workspace_user)!=source: raise ValueError('owner_source_changed')
            backup=Path(self.profile.state_dir)/'maintenance'/(request.operation_id+'.sqlite3')
            descriptor=os.open(backup,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(descriptor)
            with sqlite3.connect(Path(self.profile.database).resolve().as_uri()+'?mode=ro',uri=True) as db:
                with sqlite3.connect(backup) as destination: db.backup(destination)
            if [self.accepted(pull) for pull in request.accepted_pulls]!=accepted:
                raise ValueError('accepted_tip_changed')
            with self.reservation():
                if self.authority()!=authority or self.database_identity()!=database_identity:
                    raise ValueError('reserved_upgrade_context_changed')
                for item,workspace,source,owner,message in owner_contexts:
                    if self.source(workspace['path'],user=self.profile.workspace_user)!=source or self.approved_owner(item,workspace)!=owner:
                        raise ValueError('reserved_owner_context_changed')
                    self.checkpoint(item,workspace,'controller_upgrade',message,source['head'],request.operation_id,owner)
                self.safety()
                for checkpoint in checkpoints: self.consume_checkpoint(request.operation_id,checkpoint)
                record['cutover_started']=True
                self.stop_controller()
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
            if self.authority()!=authority or self.database_identity()!=database_identity or self.bindings()!=bindings or self.generations()!=generations: raise ValueError('deployed_context_changed')
            for path, source in sources.items():
                if self.source(path,user=self.profile.workspace_user)!=source: raise ValueError('owner_source_changed')
            for name, expected in protected.items():
                if hashlib.sha256((controller/name).read_bytes()).hexdigest()!=expected: raise ValueError('protected_file_changed')
            for preset in presets:
                if self.api('GET',f"/agent-teams/presets/{preset['id']}")['autonomy_enabled']: raise ValueError('autonomy_unexpectedly_active')
            record.update(status='deployed_paused',finished_at=now(),authority_preserved=True)
            result=self.record(request.operation_id,record)
        except Exception as error:
            record.pop('authority_preserved',None)
            self.failed_upgrade(request.operation_id,record,presets,error)
            raise
        return result
