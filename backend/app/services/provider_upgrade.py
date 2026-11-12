"""Durable provider upgrade, resumed by the ordinary application lifespan.

Private records hold the capture; public status contains only fixed stage codes.
A safety backup is not completion. Completion requires the shipped MCP protocol
and captured final files to verify, followed by a durable completion record.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import uuid
import zipfile

from sqlalchemy import select

from app.models.database import Backup
from . import provider_upgrade_artifacts as a

logger = logging.getLogger(__name__)
_STAGES = {"captured", "backed_up", "old_removed", "new_applied", "verified"}
_runtime_incomplete = False
_SUFFIXES = {
    "ack_continuation", "ack_message", "approve_work_item", "attach_image_to_bridge_session",
    "check_inbox", "create_handoff", "create_team", "decide_continuation",
    "get_backlog_coordination", "get_operator_action_contexts", "get_team_summary",
    "get_work_item_context", "launch_team", "list_bridge_attachments", "list_scope_revisions",
    "list_team", "list_teams", "list_work_items", "paste_bridge_attachment", "plan_team_launch",
    "prepare_operator_action_contexts", "prepare_work_remaining_summary", "render_github_summary",
    "reply", "report_backlog_assessment", "report_dispatch_status", "report_owner_followup",
    "request_context", "request_continuation", "request_work_item_approval", "retry_work_item",
    "send_message", "supervisor_checkin", "update_team_campaign", "update_team_parent_issue", "whoami",
}


def _checkpoint(stage, record):
    """Durability boundary used by isolated interruption tests."""


def _root():
    return Path.home() / ".albiex-synth-city"


def _sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _directory(path):
    missing = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    # Refuse symlinked configuration/storage ancestors. They cannot be bound to
    # the captured installation safely by a restart record.
    if any(parent.is_symlink() for parent in [path, *path.parents]):
        raise a.Attention("directory_identity")
    for directory in reversed(missing):
        directory.mkdir(mode=0o700)
        _sync_dir(directory.parent)
    if not path.is_dir():
        raise a.Incomplete("directory_unavailable")


def _atomic(path, data, mode=0o600):
    _directory(path.parent)
    fd, raw = tempfile.mkstemp(prefix=".provider-upgrade-", dir=path.parent)
    temporary = Path(raw)
    try:
        os.fchmod(fd, stat.S_IMODE(mode))
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync_dir(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _json_bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("ascii")


@contextmanager
def _lock():
    root = _root()
    _directory(root)
    fd = os.open(root / "provider-upgrade.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise a.Incomplete("upgrade_in_progress") from None
        yield
    finally:
        os.close(fd)


def _record_path(record):
    return _root() / "provider-upgrades" / (record["id"] + ".json")


def _capture_digest(record):
    return hashlib.sha256(_json_bytes({key: value for key, value in record.items()
        if key not in {"stage", "backup", "backup_name", "backup_digest", "capture_digest", "error", "published"}})).hexdigest()


def _persist(record):
    _atomic(_record_path(record), _json_bytes(record))


def _validate(record, path):
    if (not isinstance(record, dict) or record.get("version") != 1 or
            record.get("provider") not in a.PROVIDERS or record.get("stage") not in _STAGES or
            not re.fullmatch(r"[a-f0-9]{64}", str(record.get("id", ""))) or
            path != _record_path(record) or record.get("capture_digest") != _capture_digest(record)):
        raise a.Attention("recovery_record_invalid")
    from app.services import agent_mail_install_service as i
    allowed = set()
    for config, _, hooks in a._paths(record["provider"]):
        allowed.add(str(config.absolute()))
        if hooks:
            allowed.add(str(hooks.absolute()))
            if record["provider"] == "copilot-cli":
                allowed.add(str(hooks.with_name(a.NEW + ".json").absolute()))
    if record["provider"] == "opencode-cli":
        allowed.update(str(i.opencode_plugin_path().with_name(name).absolute()) for name in (a.OLD_PLUGIN, a.NEW_PLUGIN))
    files = record.get("files")
    if not isinstance(files, list) or not files or len(files) > 4:
        raise a.Attention("recovery_record_invalid")
    for file in files:
        if (not isinstance(file, dict) or file.get("path") not in allowed or
                "before" not in file or "after" not in file):
            raise a.Attention("recovery_record_invalid")
        for key in ("before", "after", "removed"):
            if key in file:
                a.decoded(file[key])
    if "backup" in record:
        backup = Path(record["backup"])
        if (backup.parent != _root() / "backups" or not backup.is_absolute() or
                not re.fullmatch(r"provider-upgrade-[a-f0-9]{32}\.zip", backup.name)):
            raise a.Attention("recovery_backup_invalid")


def _current(file):
    path = Path(file["path"])
    _directory(path.parent)
    if path.is_symlink():
        raise a.Attention("configuration_identity")
    if path.exists() and not path.is_file():
        raise a.Attention("configuration_identity")
    return path.read_bytes() if path.exists() else None


def _preflight(record):
    for file in record["files"]:
        actual = _current(file)
        if actual != a.decoded(file["before"]):
            raise a.Attention("capture_changed")
        if file["identity"] is not None and a._identity(Path(file["path"])) != file["identity"]:
            raise a.Attention("capture_identity_changed")


def _write(file, target):
    desired = a.decoded(target)
    actual = _current(file)
    if actual == desired:
        return
    if actual == a.decoded(file["before"]) and file["identity"] is not None:
        if a._identity(Path(file["path"])) != file["identity"]:
            raise a.Attention("capture_identity_changed")
    allowed = [a.decoded(file.get(key)) for key in ("before", "removed", "after") if key in file]
    if actual not in allowed:
        raise a.Attention("configuration_changed")
    path = Path(file["path"])
    if desired is None:
        path.unlink()
        _sync_dir(path.parent)
    else:
        mode = file["identity"][4] if file["identity"] else 0o600
        _atomic(path, desired, mode)


def _verify_backup(record):
    path = Path(record["backup"])
    if path.is_symlink() or not path.is_file():
        raise a.Incomplete("backup_unavailable")
    if hashlib.sha256(path.read_bytes()).hexdigest() != record["backup_digest"]:
        raise a.Attention("backup_changed")
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        if manifest != _backup_manifest(record):
            raise a.Attention("backup_capture_mismatch")
        for index, file in enumerate(record["files"]):
            if file["before"] is not None and archive.read(_archive_name(file, index)) != a.decoded(file["before"]):
                raise a.Attention("backup_capture_mismatch")
        if archive.testzip() is not None:
            raise a.Incomplete("backup_unreadable")


def _archive_name(file, index):
    try:
        return str(Path(file["path"]).relative_to(Path.home()))
    except ValueError:
        return "external/" + str(index) + "/" + Path(file["path"]).name


def _backup_manifest(record):
    return {"version": 1, "capture_digest": record["capture_digest"], "provider": record["provider"],
            "files": [{"source": file["path"], "archive": _archive_name(file, index)}
                      for index, file in enumerate(record["files"]) if file["before"] is not None]}


def _backup(record):
    if "backup_digest" in record:
        _verify_backup(record)
        return
    _directory(_root() / "backups")
    # Allocate durably in the record before creating the archive. A crash during
    # creation leaves only an untrusted partial file, never a mutation permit.
    if "backup" not in record:
        name = "provider-upgrade-" + uuid.uuid4().hex
        record.update(backup=str(_root() / "backups" / (name + ".zip")), backup_name=name)
        _persist(record)
    path = Path(record["backup"])
    if path.exists():
        # Never truncate a same-name file, including a partial earlier attempt.
        name = "provider-upgrade-" + uuid.uuid4().hex
        record.update(backup=str(_root() / "backups" / (name + ".zip")), backup_name=name)
        _persist(record)
        path = Path(record["backup"])
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", _json_bytes(_backup_manifest(record)))
            for index, file in enumerate(record["files"]):
                if file["before"] is not None:
                    archive.writestr(_archive_name(file, index), a.decoded(file["before"]))
        stream.flush()
        os.fsync(stream.fileno())
    _sync_dir(path.parent)
    record["backup_digest"] = hashlib.sha256(path.read_bytes()).hexdigest()
    _verify_backup(record)
    _persist(record)
    _checkpoint("backup_durable", record)


async def _index_backup(record):
    from app.database import AsyncSessionLocal
    _verify_backup(record)
    async with AsyncSessionLocal() as db:
        # FULL applies to this barrier transaction, not the application's
        # general SQLite policy. Restore the connection setting after commit.
        connection = await db.connection()
        prior = (await connection.exec_driver_sql("PRAGMA synchronous")).scalar()
        await connection.exec_driver_sql("PRAGMA synchronous=FULL")
        try:
            existing = (await db.execute(select(Backup).where(Backup.file_path == record["backup"]))).scalars().all()
            if not existing:
                db.add(Backup(name=record["backup_name"], scope="agent-mail",
                    description="Safety capture before automatic provider upgrade",
                    file_path=record["backup"], size_bytes=Path(record["backup"]).stat().st_size,
                    created_at=datetime.utcnow()))
            elif (len(existing) != 1 or existing[0].name != record["backup_name"] or
                    existing[0].size_bytes != Path(record["backup"]).stat().st_size):
                raise a.Attention("backup_index_conflict")
            await db.commit()
        except BaseException:
            await db.rollback()
            raise
        finally:
            restored = await db.connection()
            await restored.exec_driver_sql("PRAGMA synchronous=" + str(int(prior)))
    async with AsyncSessionLocal() as db:
        indexed = (await db.execute(select(Backup.file_path).where(
            Backup.name == record["backup_name"], Backup.file_path == record["backup"]))).scalars().all()
        if indexed != [record["backup"]]:
            raise a.Incomplete("backup_index_unverified")
    _checkpoint("backup_indexed", record)


def _cli_operation(record, operation):
    """Exercise the provider CLI in a private config mirror.

    CLI serializers may rewrite unrelated user bytes. Its exit and resulting
    registration are checked here; only the captured owned edits are published
    to the real file by the stage machine.
    """
    provider, cli = record["provider"], a.executor(record["provider"])
    if cli is None:
        raise a.Incomplete("cli_unavailable")
    with tempfile.TemporaryDirectory(prefix=".provider-cli-", dir=_root() / "provider-upgrades") as raw:
        home = Path(raw)
        root = home / (".codex" if provider == "codex-cli" else ".copilot")
        _directory(root)
        source = record["files"][0]
        config = root / Path(source["path"]).name
        payload = source["before"] if operation == "remove" else source["removed"]
        _atomic(config, a.decoded(payload))
        env = dict(os.environ, HOME=str(home), CODEX_HOME=str(home / ".codex"), COPILOT_HOME=str(home / ".copilot"))
        if operation == "remove":
            args = ["remove", a.OLD]
        else:
            entry = record["entry"]
            args = ["add", a.NEW, "--", entry["command"], *entry.get("args", [])]
            if provider == "copilot-cli":
                args.insert(1, "--json")
        result = cli.execute("mcp", args, timeout=20, env=env)
        if result.exit_code:
            raise a.Incomplete("cli_" + operation + "_failed")
        listed = cli.execute("mcp", ["list", "--json"], timeout=15, env=env)
        if listed.exit_code:
            raise a.Incomplete("cli_" + operation + "_unverified")
        entries = a.parse_cli_entries(provider, listed.stdout)
        if (operation == "remove" and a.OLD in entries) or (operation == "add" and a.NEW not in entries):
            raise a.Incomplete("cli_" + operation + "_unverified")


async def _protocol(entry):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from app.services import agent_mail_install_service as install
    if not a.is_owned_entry(entry, install.shim_path()):
        raise a.Attention("probe_identity_changed")
    command, args = entry["command"], entry.get("args", [])
    if isinstance(command, list):
        command, *args = command
    env = dict(os.environ)
    # No ambient team/session capability participates in an upgrade probe.
    for key in list(env):
        if key.startswith(("SYNTH_CITY_", "CLAUDE_DECK_")):
            del env[key]
    env.update(entry.get("environment", entry.get("env", {})))
    # Use the installation's fixed executable and shim after checking captured
    # launch identity; do not execute an arbitrary binary named 'python'.
    params = StdioServerParameters(command=sys.executable,
        args=[install.shim_path(), *args[1:], "--synth-city-upgrade-tools-list-probe"], env=env)
    with open(os.devnull, "w") as errors:
        async with asyncio.timeout(15):
            async with stdio_client(params, errlog=errors) as (read, write):
                async with ClientSession(read, write, client_info={"name": "albiex-synth-city-test", "version": "4.0.0"}) as session:
                    initialized = await session.initialize()
                    tools = await session.list_tools()
                    if initialized.serverInfo.name != a.NEW or {tool.name for tool in tools.tools} != {
                            "synth_city_" + suffix for suffix in _SUFFIXES} or len(tools.tools) != 36:
                        raise a.Incomplete("protocol_unverified")


async def _resume(record):
    stage = record["stage"]
    if stage == "verified" and record.get("published") is True:
        return
    if stage == "captured":
        _preflight(record)
        _backup(record)
    await _index_backup(record)
    if stage == "captured":
        _preflight(record)
        record["stage"] = "backed_up"
        _persist(record)
        stage = "backed_up"
    if stage == "backed_up":
        if record["cli"]:
            _cli_operation(record, "remove")
        for file in record["files"]:
            if "removed" in file:
                _write(file, file["removed"])
            elif record["artifact"] == "plugin" and file["after"] is None:
                _write(file, None)
        record["stage"] = "old_removed"
        _persist(record)
        _checkpoint("old_removed", record)
        stage = "old_removed"
    if stage == "old_removed":
        if record["cli"] and not record.get("both"):
            _cli_operation(record, "add")
        for file in record["files"]:
            _write(file, file["after"])
        record["stage"] = "new_applied"
        _persist(record)
        _checkpoint("new_applied", record)
    for file in record["files"]:
        if _current(file) != a.decoded(file["after"]):
            raise a.Attention("final_configuration_changed")
    if record["artifact"] == "mcp":
        if record["cli"]:
            listed = a.cli_entries(record["provider"], a.executor(record["provider"]))
            if a.OLD in listed or not a.same_launch(listed.get(a.NEW), record["entry"]):
                raise a.Incomplete("new_registration_unverified")
        await _protocol(record["entry"])
    record["stage"] = "verified"
    _persist(record)
    _checkpoint("verified", record)


def read_status():
    if _runtime_incomplete:
        return {provider: {"state": "incomplete", "stage": "status_unavailable"} for provider in a.PROVIDERS}
    try:
        path = _root() / "provider-upgrade-status.json"
        if not path.exists() and (_root() / "provider-upgrades").exists():
            if any((_root() / "provider-upgrades").glob("*.json")):
                raise ValueError
        if not path.exists():
            return {}
        if path.is_symlink():
            raise ValueError
        doc = json.loads(path.read_text())
        states = {}
        for provider, row in doc["providers"].items():
            if (provider not in a.PROVIDERS or row["state"] not in {"verified", "incomplete", "needs_attention"}
                    or not re.fullmatch(r"[a-z_]{1,60}", row["stage"])):
                raise ValueError
            states[provider] = {"state": row["state"], "stage": row["stage"]}
        return states
    except (OSError, ValueError, TypeError, KeyError):
        return {provider: {"state": "incomplete", "stage": "status_unavailable"} for provider in a.PROVIDERS}


async def upgrade_providers():
    """Called only after init_db/reference retarget, before startup services."""
    from app.config import settings
    global _runtime_incomplete
    if settings.test_instance:
        return
    _runtime_incomplete = False
    try:
        with _lock():
            directory = _root() / "provider-upgrades"
            _directory(directory)
            records, findings = {}, {provider: [] for provider in a.PROVIDERS}
            for path in sorted(directory.glob("*.json")):
                try:
                    if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) & 0o077:
                        raise a.Attention("recovery_record_invalid")
                    record = json.loads(path.read_text())
                    _validate(record, path)
                    records[record["id"]] = record
                except Exception:
                    # Unknown/corrupt recovery state must not be replaced by a
                    # fresh discovery that could forget an already removed name.
                    status = {provider: {"state": "needs_attention", "stage": "recovery_record_invalid"}
                              for provider in a.PROVIDERS}
                    _atomic(_root() / "provider-upgrade-status.json", _json_bytes({"version": 1, "providers": status}))
                    return
            for provider in a.PROVIDERS:
                active = [r for r in records.values() if r["provider"] == provider and r["stage"] != "verified"]
                if not active:
                    discovered, findings[provider] = a.discover(provider)
                    for record in discovered:
                        if record["id"] in records:
                            # A completed capture cannot authorise a later new
                            # old-name configuration with different values.
                            findings[provider].append({"state": "needs_attention", "stage": "completed_capture_changed"})
                            continue
                        record["version"] = 1
                        record["capture_digest"] = _capture_digest(record)
                        _persist(record)
                        records[record["id"]] = record
                        _checkpoint("captured", record)
            status = {}
            for provider in a.PROVIDERS:
                relevant = [r for r in records.values() if r["provider"] == provider]
                outcomes = list(findings[provider])
                for record in relevant:
                    try:
                        await _resume(record)
                        outcomes.append({"state": "verified", "stage": "verified"})
                    except a.Attention as exc:
                        outcomes.append({"state": "needs_attention", "stage": str(exc)})
                    except Exception as exc:
                        code = str(exc) if isinstance(exc, a.Incomplete) else record["stage"]
                        outcomes.append({"state": "incomplete", "stage": code})
                        logger.warning("Provider upgrade incomplete: provider=%s stage=%s", provider, record["stage"])
                if outcomes:
                    priority = {"verified": 0, "incomplete": 1, "needs_attention": 2}
                    status[provider] = max(outcomes, key=lambda row: priority[row["state"]])
                _atomic(_root() / "provider-upgrade-status.json", _json_bytes({"version": 1, "providers": status}))
                for record in relevant:
                    if record["stage"] == "verified" and not record.get("published"):
                        record["published"] = True
                        _persist(record)
                    _checkpoint("status_durable", record)
    except Exception:
        # Do not leak captured values, paths, subprocess output or raw errors.
        # A missing/stale status is treated as incomplete by the setup API.
        _runtime_incomplete = True
        logger.warning("Provider upgrade incomplete at durable storage boundary")
