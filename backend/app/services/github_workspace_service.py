"""Provision and lease isolated workspaces for GitHub dispatch."""
from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import re
import secrets
import shlex
import sys
from dataclasses import dataclass, field
from types import SimpleNamespace
import stat
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import httpx
from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import GithubWorkItem, GithubWorkspace, TeamGithubScope
from app.services.agent_bridge.discovery import discover_agent_sessions
from app.services.agent_mail_install_service import synth_city_base_url
from app.services.github_app_auth_service import (
    GithubAppAuthError,
    github_app_auth_service,
)
from app.services.github_client import GithubClientResponseError, github_client

GIT_TIMEOUT_SECONDS = 300

_GIT_ENV = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "",
    "SSH_ASKPASS": "",
    "GIT_CONFIG_NOSYSTEM": "1",
}

_RECLAIMABLE_STATUSES = ("escalated", "failed", "merged", "completed")
_RELEASABLE_STATUSES = ("merged", "completed", "escalated", "failed")

logger = logging.getLogger(__name__)

_GITHUB_CREDENTIAL_PREFIX = "credential.https://github.com"
_MANAGED_WORKTREE_KEYS = (
    "user.name",
    "user.email",
    f"{_GITHUB_CREDENTIAL_PREFIX}.useHttpPath",
    f"{_GITHUB_CREDENTIAL_PREFIX}.helper",
)
_UNSET = object()


def _push_token_subject(
    workspace_id: int,
    lease_token: str,
    owner_slot_id: int,
) -> str:
    return f"workspace:{workspace_id}:lease:{lease_token}:slot:{owner_slot_id}"


def _redact_git_diagnostic(value: str) -> str:
    return re.sub(r"(--lease(?:=|\s+))[^\s'\"]+", r"\1<redacted>", value)


# Dispatch workspaces are created only as these direct siblings of the scope checkout.
MAX_WORKSPACE_NAME_SEARCH = 64
MAX_PROVISIONED_PER_CALL = 64
# provision_error marker of a reservation row while a worker is creating its checkout.
RESERVATION_MARKER = "provisioning"
RESERVATION_STALE_SECONDS = 900


def _contained_path(path: str | None) -> str | None:
    """The resolved path when it lies strictly inside the home directory, else None.

    Checked before any filesystem or git call that takes a scope path, which comes from a
    request. Scope paths are saved under the home directory already; this re-proves it where
    the path is used.
    """
    if not path or "\x00" in path:
        return None
    resolved = os.path.realpath(path)
    home = os.path.realpath(os.path.expanduser("~"))
    if resolved.startswith(home + os.sep):
        return resolved
    return None


@dataclass(frozen=True)
class _Reservation:
    row_id: int
    scope_id: int
    path: str
    repo_path: str
    snapshot: tuple
_PROVISION_REASON_LIMIT = 300


def _provision_reason(value: str) -> str:
    """One short line for an operator: redacted, no control characters, bounded."""
    text = re.sub(r"[\x00-\x1f\x7f]", " ", value)
    return _redact_git_diagnostic(" ".join(text.split()))[:_PROVISION_REASON_LIMIT]


@dataclass(frozen=True)
class ProvisionFailure:
    path: str
    code: str
    reason: str


@dataclass
class ProvisioningReport:
    target: int
    existing: int = 0
    created: list[str] = field(default_factory=list)
    failures: list[ProvisionFailure] = field(default_factory=list)


@dataclass(frozen=True)
class WorktreeConfigSnapshot:
    values: dict[str, tuple[str, ...]]


class GithubWorkspaceError(RuntimeError):
    def __init__(self, message: str, block_code: str = "workspace_not_a_worktree"):
        super().__init__(message)
        self.block_code = block_code


class GithubWorkspaceResetError(GithubWorkspaceError):
    def __init__(self, message: str, *, transient: bool):
        super().__init__(message, "workspace_reset_failed")
        self.transient = transient


class GithubWorkspaceLeaseTokenMismatch(GithubWorkspaceError):
    def __init__(self, message: str):
        super().__init__(message, "lease_token_mismatch")


class GithubWorkspaceConfigError(GithubWorkspaceError):
    def __init__(self, message: str, *, restoration_failed: bool = False):
        super().__init__(message, "workspace_config_failed")
        self.restoration_failed = restoration_failed


class GithubWorkspaceCredentialRevokeError(GithubWorkspaceError):
    def __init__(self, message: str):
        super().__init__(message, "workspace_credential_revoke_failed")


class GithubWorkspaceRemoteError(GithubWorkspaceError):
    def __init__(self, message: str):
        super().__init__(message, "workspace_remote_invalid")


class GithubWorkspaceService:
    def __init__(self, runner=None):
        self._runner = runner or self._run_git
        self._config_locks: dict[int, asyncio.Lock] = {}
        self._provision_locks: dict[int, asyncio.Lock] = {}

    def config_lock(self, workspace_id: int) -> asyncio.Lock:
        return self._config_locks.setdefault(workspace_id, asyncio.Lock())

    async def attest_head(self, workspace: GithubWorkspace, expected_ref: str) -> tuple[str, str]:
        """Read the leased branch's immutable commit/tree without touching held edits."""
        if not workspace.enabled or not workspace.path or not expected_ref:
            raise GithubWorkspaceError("Workspace head cannot be attested", "amendment_workspace_unverifiable")
        try:
            path = pathlib.Path(workspace.path).resolve(strict=True)
            if not path.is_dir() or not pathlib.Path(workspace.path).is_absolute():
                raise ValueError()
            branch_code, branch = await self._runner(["-C", str(path), "symbolic-ref", "--short", "HEAD"])
            head_code, head = await self._runner(["-C", str(path), "rev-parse", "--verify", "HEAD"])
            head = head.strip()
            if branch_code or head_code or branch.strip() != expected_ref or not re.fullmatch(r"[0-9a-f]{40}", head):
                raise ValueError()
            tree_code, tree = await self._runner(["-C", str(path), "rev-parse", "--verify", head + "^{tree}"])
            final_code, final = await self._runner(["-C", str(path), "rev-parse", "--verify", "HEAD"])
            branch_code, branch = await self._runner(["-C", str(path), "symbolic-ref", "--short", "HEAD"])
            if (tree_code or final_code or branch_code or final.strip() != head
                    or branch.strip() != expected_ref or not re.fullmatch(r"[0-9a-f]{40}", tree.strip())):
                raise ValueError()
        except (OSError, ValueError) as exc:
            raise GithubWorkspaceError("Workspace head cannot be attested", "amendment_workspace_unverifiable") from exc
        return head, tree.strip()

    async def _run_git(self, args: list[str]) -> tuple[int, str]:
        process = await asyncio.create_subprocess_exec(
            "git",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=_GIT_ENV,
        )
        try:
            stdout, _ = await asyncio.wait_for(
                process.communicate(), timeout=GIT_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            command = _redact_git_diagnostic(shlex.join(args))
            return 124, f"git {command} timed out after {GIT_TIMEOUT_SECONDS}s"
        return process.returncode, stdout.decode("utf-8", "replace")

    def _parse_proc_start(self, raw: str) -> str | None:
        """Return field 22 (starttime) from a /proc/<pid>/stat line."""
        try:
            return raw[raw.rindex(")") + 2:].split()[19]
        except (ValueError, IndexError):
            return None

    def _read_proc_start(self, pid: int) -> str | None:
        """Read a process start time while preserving process-gone errors."""
        return self._parse_proc_start(pathlib.Path(f"/proc/{pid}/stat").read_text())

    def _owner_process_is_alive(self, workspace: GithubWorkspace) -> bool:
        """Return whether the process briefed with this lease is still running."""
        if workspace.leased_owner_pid is None:
            return True
        try:
            current_start = self._read_proc_start(workspace.leased_owner_pid)
        except (FileNotFoundError, ProcessLookupError):
            return False
        except OSError:
            return True
        if current_start is None or workspace.leased_owner_proc_start is None:
            return True
        return current_start == workspace.leased_owner_proc_start

    async def acquire(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        item: GithubWorkItem,
        *,
        allow_primary: bool = False,
    ) -> GithubWorkspace | None:
        held = (
            await db.execute(
                select(GithubWorkspace).where(GithubWorkspace.leased_item_id == item.id)
            )
        ).scalar_one_or_none()
        if held is not None:
            if held.kind != "primary" or allow_primary:
                return held
            if held.leased_at is None:
                return None
            released = await self.force_release_acquisition(
                db,
                actor_kind="scheduler", actor_scheduler="github_dispatch_scheduler",
                workspace_id=held.id,
                scope_id=scope.id,
                item_id=item.id,
                expected_leased_at=held.leased_at,
                lease_token=held.lease_token,
            )
            if not released:
                return None

        clauses = [
            GithubWorkspace.scope_id == scope.id,
            GithubWorkspace.enabled.is_(True),
            GithubWorkspace.dispatchable.is_(True),
            GithubWorkspace.leased_item_id.is_(None),
        ]
        if not allow_primary:
            clauses.append(GithubWorkspace.kind != "primary")
        workspace = (
            await db.execute(
                select(GithubWorkspace)
                .where(*clauses)
                .order_by(GithubWorkspace.id)
            )
        ).scalars().first()
        if workspace is None:
            return None

        now = datetime.utcnow()
        workspace.leased_item_id = item.id
        workspace.leased_at = now
        workspace.released_at = None
        workspace.lease_token = secrets.token_hex(8)
        workspace.push_token_expires_at = None
        workspace.leased_owner_pid = None
        workspace.leased_owner_proc_start = None
        workspace.lease_last_owner_contact_at = None
        workspace.lease_release_reminded_at = None
        workspace.lease_release_reminder_count = 0
        workspace.lease_release_reminder_started_at = None
        workspace.updated_at = now
        await db.commit()

        if workspace.kind != "primary":
            try:
                await self.reset_workspace(db, scope, workspace)
            except GithubWorkspaceResetError:
                if workspace.leased_at is not None:
                    await self.force_release_acquisition(
                        db,
                        actor_kind="scheduler",
                        actor_scheduler="github_dispatch_scheduler",
                        workspace_id=workspace.id,
                        scope_id=scope.id,
                        item_id=item.id,
                        expected_leased_at=workspace.leased_at,
                        lease_token=workspace.lease_token,
                    )
                return None
            workspace.updated_at = datetime.utcnow()
            await db.commit()
        return workspace

    async def skipped_primary_count(
        self, db: AsyncSession, scope_id: int
    ) -> int:
        result = await db.execute(
            select(GithubWorkspace.id).where(
                GithubWorkspace.scope_id == scope_id,
                GithubWorkspace.kind == "primary",
                GithubWorkspace.enabled.is_(True),
                GithubWorkspace.dispatchable.is_(True),
            )
        )
        return len(result.scalars().all())

    @staticmethod
    def slot_email(display_name: str, slot_id: int) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-")
        if not slug:
            slug = "agent"
        suffix = f"+slot{slot_id}"
        slug = slug[: 64 - len(suffix)].rstrip("-") or "agent"
        return f"{slug}{suffix}@synth-city.local"

    @staticmethod
    def slot_name(display_name: str) -> str:
        return f"{display_name} (Synth City agent)"

    @staticmethod
    def _credential_helper_command(lease_token: str) -> str:
        helper_path = pathlib.Path(__file__).resolve().parents[2] / "mcp_shim" / "git_credential_helper.py"
        return shlex.join(
            [
                sys.executable,
                str(helper_path),
                "--synth-city-url",
                synth_city_base_url(),
                "--lease",
                lease_token,
            ]
        )

    @staticmethod
    def push_token_subject(
        workspace_id: int,
        lease_token: str,
        owner_slot_id: int,
    ) -> str:
        return _push_token_subject(workspace_id, lease_token, owner_slot_id)

    async def revoke_push_token(
        self,
        scope: TeamGithubScope,
        workspace: GithubWorkspace,
        *,
        owner_slot_id: int | None,
    ) -> bool:
        if (
            scope.github_auth_mode != "app"
            or scope.github_app_installation_id is None
            or workspace.lease_token is None
            or owner_slot_id is None
        ):
            return False
        try:
            revoked = await github_app_auth_service.revoke_cached_repository_token(
                scope.github_app_installation_id,
                scope.repo_owner,
                scope.repo_name,
                purpose="push",
                cache_subject=_push_token_subject(
                    workspace.id,
                    workspace.lease_token,
                    owner_slot_id,
                ),
            )
            if (
                not revoked
                and workspace.push_token_expires_at is not None
                and workspace.push_token_expires_at > datetime.utcnow()
            ):
                raise GithubWorkspaceCredentialRevokeError(
                    "Unable to prove the workspace push credential expired after "
                    "the backend token cache was lost"
                )
            return revoked
        except GithubAppAuthError as exc:
            raise GithubWorkspaceCredentialRevokeError(
                f"Unable to revoke the workspace push credential: {exc.code}"
            ) from exc

    async def _config_values(
        self, workspace: GithubWorkspace, key: str
    ) -> tuple[str, ...]:
        return_code, output = await self._runner(
            ["-C", workspace.path, "config", "--worktree", "--null", "--get-all", key]
        )
        if return_code == 1:
            return ()
        if return_code != 0:
            raise GithubWorkspaceConfigError(
                output.strip() or f"Unable to read worktree config {key}"
            )
        values = output.split("\0")
        if values and values[-1] == "":
            values.pop()
        return tuple(values)

    async def snapshot_worktree_config(
        self, workspace: GithubWorkspace
    ) -> WorktreeConfigSnapshot:
        values: dict[str, tuple[str, ...]] = {}
        for key in _MANAGED_WORKTREE_KEYS:
            values[key] = await self._config_values(workspace, key)
        return WorktreeConfigSnapshot(values)

    async def _worktree_config_unavailable(self, workspace: GithubWorkspace) -> bool:
        try:
            os.stat(workspace.path)
        except (FileNotFoundError, NotADirectoryError):
            return True
        return_code, output = await self._runner(
            [
                "-C", workspace.path, "config", "--local", "--bool",
                "extensions.worktreeConfig",
            ]
        )
        return (return_code == 1 and not output.strip()) or (
            return_code == 0 and output.strip() == "false"
        )

    async def _clear_config_key(self, workspace: GithubWorkspace, key: str) -> None:
        return_code, output = await self._runner(
            ["-C", workspace.path, "config", "--worktree", "--unset-all", key]
        )
        if return_code not in {0, 5}:
            raise GithubWorkspaceConfigError(
                output.strip() or f"Unable to clear worktree config {key}"
            )

    async def restore_worktree_config(
        self,
        workspace: GithubWorkspace,
        snapshot: WorktreeConfigSnapshot,
    ) -> None:
        for key in _MANAGED_WORKTREE_KEYS:
            await self._clear_config_key(workspace, key)
            for value in snapshot.values[key]:
                return_code, output = await self._runner(
                    ["-C", workspace.path, "config", "--worktree", "--add", key, value]
                )
                if return_code != 0:
                    raise GithubWorkspaceConfigError(
                        _redact_git_diagnostic(output.strip())
                        or f"Unable to restore worktree config {key}",
                        restoration_failed=True,
                    )

    async def remove_managed_worktree_config(
        self, workspace: GithubWorkspace
    ) -> None:
        if workspace.kind == "primary":
            return
        for key in _MANAGED_WORKTREE_KEYS:
            await self._clear_config_key(workspace, key)

    async def apply_slot_identity(
        self,
        workspace: GithubWorkspace,
        *,
        display_name: str,
        slot_id: int,
    ) -> None:
        """Write the managed commit identity while the caller holds config_lock."""
        commands = [
            [
                "-C",
                workspace.path,
                "config",
                "--worktree",
                "--replace-all",
                "user.name",
                self.slot_name(display_name),
            ],
            [
                "-C",
                workspace.path,
                "config",
                "--worktree",
                "--replace-all",
                "user.email",
                self.slot_email(display_name, slot_id),
            ],
        ]
        for command in commands:
            return_code, output = await self._runner(command)
            if return_code != 0:
                raise GithubWorkspaceConfigError(
                    _redact_git_diagnostic(output.strip())
                    or f"git {_redact_git_diagnostic(shlex.join(command))} failed"
                )

    async def validate_app_remote(
        self, scope: TeamGithubScope, workspace: GithubWorkspace
    ) -> None:
        return_code, output = await self._runner(
            ["-C", workspace.path, "remote", "get-url", "--push", "--all", "origin"]
        )
        urls = [line.strip() for line in output.splitlines() if line.strip()]
        if return_code != 0 or len(urls) != 1:
            raise GithubWorkspaceRemoteError(
                output.strip() or "origin must have exactly one push URL"
            )
        parsed = urlsplit(urls[0])
        try:
            port = parsed.port
        except ValueError as exc:
            raise GithubWorkspaceRemoteError("origin push URL has an invalid port") from exc
        normalized_path = parsed.path.removeprefix("/")
        if normalized_path.endswith(".git"):
            normalized_path = normalized_path[:-4]
        expected_path = f"{scope.repo_owner}/{scope.repo_name}"
        if (
            parsed.scheme != "https"
            or parsed.hostname != "github.com"
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
            or parsed.query
            or parsed.fragment
            or normalized_path != expected_path
        ):
            raise GithubWorkspaceRemoteError(
                f"origin push URL does not match https://github.com/{expected_path}.git"
            )

    async def resolve_attempt_base_ref(
        self,
        scope: TeamGithubScope,
        workspace: GithubWorkspace,
    ) -> str:
        """Freeze a symbolic default branch to the branch this worktree uses."""
        if scope.base_ref != "origin/HEAD":
            return scope.base_ref
        return_code, output = await self._runner(
            [
                "-C",
                workspace.path,
                "symbolic-ref",
                "--short",
                "refs/remotes/origin/HEAD",
            ]
        )
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        if (
            return_code != 0
            or len(lines) != 1
            or not lines[0].startswith("origin/")
            or lines[0] == "origin/HEAD"
        ):
            raise GithubWorkspaceConfigError(
                "Unable to resolve origin/HEAD to an immutable dispatch base"
            )
        return lines[0]

    async def configure_dispatch_worktree(
        self,
        workspace: GithubWorkspace,
        *,
        display_name: str,
        slot_id: int,
        app_mode: bool,
    ) -> WorktreeConfigSnapshot | None:
        if workspace.kind == "primary":
            return None
        if workspace.lease_token is None:
            raise GithubWorkspaceConfigError("Workspace lease token is missing")
        async with self.config_lock(workspace.id):
            return_code, output = await self._runner(
                ["-C", workspace.path, "config", "extensions.worktreeConfig", "true"]
            )
            if return_code != 0:
                raise GithubWorkspaceConfigError(
                    output.strip() or "Unable to enable worktree config"
                )
            snapshot = await self.snapshot_worktree_config(workspace)
            commands = []
            if app_mode:
                commands.extend(
                    [
                        [
                            "-C",
                            workspace.path,
                            "config",
                            "--worktree",
                            "--replace-all",
                            f"{_GITHUB_CREDENTIAL_PREFIX}.useHttpPath",
                            "true",
                        ],
                        [
                            "-C",
                            workspace.path,
                            "config",
                            "--worktree",
                            "--replace-all",
                            f"{_GITHUB_CREDENTIAL_PREFIX}.helper",
                            "",
                        ],
                        [
                            "-C",
                            workspace.path,
                            "config",
                            "--worktree",
                            "--add",
                            f"{_GITHUB_CREDENTIAL_PREFIX}.helper",
                            self._credential_helper_command(workspace.lease_token),
                        ],
                    ]
                )
            try:
                await self.apply_slot_identity(
                    workspace,
                    display_name=display_name,
                    slot_id=slot_id,
                )
                for command in commands:
                    return_code, output = await self._runner(command)
                    if return_code != 0:
                        raise GithubWorkspaceConfigError(
                            _redact_git_diagnostic(output.strip())
                            or f"git {_redact_git_diagnostic(shlex.join(command))} failed"
                        )
            except BaseException as exc:
                try:
                    await self.restore_worktree_config(workspace, snapshot)
                except GithubWorkspaceConfigError as restore_exc:
                    if not isinstance(exc, Exception):
                        raise exc from restore_exc
                    raise GithubWorkspaceConfigError(
                        f"{exc}; worktree config restoration failed: {restore_exc}",
                        restoration_failed=True,
                    ) from restore_exc
                raise
            return snapshot

    @staticmethod
    def _released_values(now: datetime) -> dict[str, object | None]:
        return {
            "leased_item_id": None,
            "released_at": now,
            "lease_token": None,
            "push_token_expires_at": None,
            "leased_owner_pid": None,
            "leased_owner_proc_start": None,
            "lease_last_owner_contact_at": None,
            "lease_release_reminded_at": None,
            "lease_release_reminder_count": 0,
            "lease_release_reminder_started_at": None,
            "updated_at": now,
        }

    async def _record_config_repair_note(
        self,
        db: AsyncSession,
        *,
        workspace_id: int,
        item_id: int,
        detail: str,
    ) -> None:
        try:
            workspace = await db.get(GithubWorkspace, workspace_id)
            item = await db.get(GithubWorkItem, item_id)
            if workspace is not None:
                workspace.provision_error = detail
                workspace.updated_at = datetime.utcnow()
            if item is not None:
                item.status_note = detail
                item.updated_at = datetime.utcnow()
            await db.commit()
        except Exception:
            logger.exception(
                "Unable to persist worktree config repair note for workspace %s",
                workspace_id,
            )
            await db.rollback()

    async def _release_acquisition(
        self,
        db: AsyncSession,
        *,
        workspace_id: int,
        scope_id: int,
        item_id: int,
        actor_kind: str = "operator",
        actor_member_id: int | None = None,
        actor_session_id: int | None = None,
        actor_scheduler: str | None = None,
        expected_leased_at: datetime | None,
        lease_token: str | None,
        owner_slot_id: int | None = None,
        expected_owner_pid: int | None | object = _UNSET,
        expected_owner_proc_start: str | None | object = _UNSET,
        expected_last_owner_contact_at: datetime | None | object = _UNSET,
    ) -> bool:
        async with self.config_lock(workspace_id):
            workspace_row = (
                await db.execute(
                    select(
                        GithubWorkspace.id,
                        GithubWorkspace.scope_id,
                        GithubWorkspace.path,
                        GithubWorkspace.kind,
                        GithubWorkspace.leased_item_id,
                        GithubWorkspace.leased_at,
                        GithubWorkspace.lease_token,
                        GithubWorkspace.push_token_expires_at,
                    )
                    .where(GithubWorkspace.id == workspace_id)
                )
            ).one_or_none()
            item_row = (
                await db.execute(
                    select(GithubWorkItem.id, GithubWorkItem.owner_slot_id)
                    .where(GithubWorkItem.id == item_id)
                )
            ).one_or_none()
            scope_row = (
                await db.execute(
                    select(
                        TeamGithubScope.id,
                        TeamGithubScope.repo_owner,
                        TeamGithubScope.repo_name,
                        TeamGithubScope.github_auth_mode,
                        TeamGithubScope.github_app_installation_id,
                    )
                    .where(TeamGithubScope.id == scope_id)
                )
            ).one_or_none()
            if workspace_row is None or item_row is None or scope_row is None:
                await db.rollback()
                return False
            scope = TeamGithubScope(
                id=scope_row.id,
                repo_owner=scope_row.repo_owner,
                repo_name=scope_row.repo_name,
                github_auth_mode=scope_row.github_auth_mode,
                github_app_installation_id=scope_row.github_app_installation_id,
            )
            config_workspace = GithubWorkspace(
                id=workspace_row.id,
                path=workspace_row.path,
                kind=workspace_row.kind,
                lease_token=lease_token,
                push_token_expires_at=workspace_row.push_token_expires_at,
            )
            current_owner_slot_id = item_row.owner_slot_id
            from app.services import factory_audit_service as _audit
            # C08: the actor comes from the trusted entry point. The
            # acquisition identity is the workspace and its lease time; the
            # lease token is a capability and never enters the ledger.
            release_actor = _audit.derive_actor(
                actor_kind=actor_kind,
                member_id=actor_member_id,
                session_id=actor_session_id,
                scheduler=actor_scheduler,
            )
            acquisition = (
                f"workspace:{workspace_id}:leased_at:"
                f"{expected_leased_at.isoformat() if expected_leased_at else None}"
            )
            release_fields = {
                "event_kind": "workspace_release",
                "source": "github_workspace_service._release_acquisition",
                "actor": release_actor,
                "scope_id": scope_id,
                "item_id": item_id,
                "correlation_id": f"workspace_release:{acquisition}",
            }

            async def observe_release(outcome: str, reason: str) -> None:
                # A refused or failed release is observed after its own
                # transaction ends. Observation failure never masks it.
                await _audit.record_observation(
                    db,
                    occurred_at=datetime.utcnow(),
                    action_outcome=outcome,
                    sanitized_reason=reason,
                    **release_fields,
                )

            if (
                workspace_row.scope_id != scope_id
                or workspace_row.leased_item_id != item_id
                or workspace_row.leased_at != expected_leased_at
                or workspace_row.lease_token != lease_token
            ):
                await db.rollback()
                await observe_release("rejected", "acquisition identity mismatch")
                return False
            await db.commit()
            snapshot = None
            if config_workspace.kind != "primary":
                try:
                    snapshot = await self.snapshot_worktree_config(config_workspace)
                except GithubWorkspaceConfigError:
                    if not await self._worktree_config_unavailable(config_workspace):
                        raise
            predicates = [
                GithubWorkspace.id == workspace_id,
                GithubWorkspace.scope_id == scope_id,
                GithubWorkspace.leased_item_id == item_id,
                GithubWorkspace.leased_at == expected_leased_at,
                GithubWorkspace.lease_token == lease_token,
            ]
            if expected_owner_pid is not _UNSET:
                predicates.append(
                    GithubWorkspace.leased_owner_pid == expected_owner_pid
                )
            if expected_owner_proc_start is not _UNSET:
                predicates.append(
                    GithubWorkspace.leased_owner_proc_start
                    == expected_owner_proc_start
                )
            if expected_last_owner_contact_at is not _UNSET:
                predicates.append(
                    GithubWorkspace.lease_last_owner_contact_at
                    == expected_last_owner_contact_at
                )
            if owner_slot_id is not None:
                predicates.append(
                    exists().where(
                        GithubWorkItem.id == item_id,
                        GithubWorkItem.owner_slot_id == owner_slot_id,
                        GithubWorkItem.dispatch_status.in_(_RELEASABLE_STATUSES),
                    )
                )
            result = await db.execute(
                update(GithubWorkspace)
                .where(*predicates)
                .values(**self._released_values(datetime.utcnow()))
                .execution_options(synchronize_session="fetch")
            )
            if result.rowcount != 1:
                # C09: a late CAS refusal. The acquisition, owner or lease
                # contact changed while the release awaited; nothing was
                # revoked or cleaned up.
                await db.rollback()
                await observe_release("rejected", "release guard changed before release")
                return False
            # Each external effect is recorded only as far as it is proved.
            credential_effect = "not_attempted"
            config_effect = "not_attempted"
            try:
                credential_effect = "unknown"
                await self.revoke_push_token(
                    scope,
                    config_workspace,
                    owner_slot_id=(
                        owner_slot_id
                        if owner_slot_id is not None
                        else current_owner_slot_id
                    ),
                )
                credential_effect = "revoked_or_not_held"
                if snapshot is not None:
                    config_effect = "unknown"
                    await self.remove_managed_worktree_config(config_workspace)
                    config_effect = "removed"
                # A06/A08: the release event commits in the same transaction
                # as the release itself. An audit-write failure rolls back
                # the release.
                operation_id = f"workspace_release:{acquisition}"
                await _audit.record_event(
                    db,
                    occurred_at=datetime.utcnow(),
                    action_outcome="applied",
                    sanitized_reason="workspace release applied",
                    operation_id=operation_id,
                    **release_fields,
                )
                await db.commit()
                return True
            except BaseException as exc:
                await db.rollback()
                restore_effect = "not_needed"
                restore_exc_raised: GithubWorkspaceConfigError | None = None
                if snapshot is not None:
                    try:
                        await self.restore_worktree_config(config_workspace, snapshot)
                        restore_effect = "restored"
                    except GithubWorkspaceConfigError as restore_exc:
                        restore_effect = "restore_failed"
                        restore_exc_raised = restore_exc
                if isinstance(exc, Exception):
                    # C09: the local release rolled back. A remote revocation
                    # cannot be undone by that rollback, so the observed
                    # result names each known effect. Only an effect whose
                    # result cannot be proved makes the outcome uncertain.
                    # A partial config removal is proved settled only when
                    # the snapshot restoration succeeded.
                    uncertain = (
                        credential_effect == "unknown"
                        or restore_effect == "restore_failed"
                        or (config_effect == "unknown" and restore_effect != "restored")
                    )
                    await observe_release(
                        "uncertain" if uncertain else "rejected",
                        "workspace release rolled back; "
                        f"push access {credential_effect}; "
                        f"managed config {config_effect}; restoration {restore_effect}",
                    )
                if restore_exc_raised is not None:
                    detail = (
                        "Worktree release failed and managed config restoration "
                        f"also failed: {restore_exc_raised}"
                    )
                    await self._record_config_repair_note(
                        db,
                        workspace_id=workspace_id,
                        item_id=item_id,
                        detail=detail,
                    )
                    if not isinstance(exc, Exception):
                        raise exc from restore_exc_raised
                    raise GithubWorkspaceConfigError(
                        detail,
                        restoration_failed=True,
                    ) from restore_exc_raised
                raise

    async def release(self, db: AsyncSession, item_id: int) -> bool:
        workspace = (
            await db.execute(
                select(GithubWorkspace).where(GithubWorkspace.leased_item_id == item_id)
            )
        ).scalar_one_or_none()
        if workspace is None:
            return False
        return await self._release_acquisition(
            db,
            actor_kind="scheduler", actor_scheduler="github_dispatch_scheduler",
            workspace_id=workspace.id,
            scope_id=workspace.scope_id,
            item_id=item_id,
            expected_leased_at=workspace.leased_at,
            lease_token=workspace.lease_token,
        )

    async def force_release_acquisition(
        self,
        db: AsyncSession,
        *,
        workspace_id: int,
        scope_id: int,
        item_id: int,
        actor_kind: str = "operator",
        actor_member_id: int | None = None,
        actor_session_id: int | None = None,
        actor_scheduler: str | None = None,
        expected_leased_at: datetime,
        lease_token: str | None,
    ) -> bool:
        """Clear exactly the acquisition described, or nothing at all.

        `release` selects on `leased_item_id` alone, so a caller that inspects
        a workspace, awaits, and then calls it can clear a lease on a
        different row. Here the comparison is the write: every part of what
        the caller inspected is in the WHERE clause.
        """
        return await self._release_acquisition(
            db,
            actor_kind=actor_kind,
            actor_member_id=actor_member_id,
            actor_session_id=actor_session_id,
            actor_scheduler=actor_scheduler,
            workspace_id=workspace_id,
            scope_id=scope_id,
            item_id=item_id,
            expected_leased_at=expected_leased_at,
            lease_token=lease_token,
        )

    async def get_leased_workspace(
        self, db: AsyncSession, item_id: int
    ) -> GithubWorkspace | None:
        return (
            await db.execute(
                select(GithubWorkspace).where(
                    GithubWorkspace.leased_item_id == item_id
                )
            )
        ).scalar_one_or_none()

    async def release_by_token(
        self, db: AsyncSession, item_id: int, *, lease_token: str,
        actor_kind: str = "member",
        actor_member_id: int | None = None,
        actor_session_id: int | None = None,
        actor_scheduler: str | None = None,
    ) -> bool:
        """Release only the workspace acquisition named by the token.

        Item identity alone cannot distinguish a stale report from an earlier
        dispatch attempt. Requiring the acquisition token prevents that report
        from releasing a replacement owner's live lease.
        """
        workspace = await self.get_leased_workspace(db, item_id)
        if workspace is None:
            return False
        if workspace.lease_token != lease_token:
            raise GithubWorkspaceLeaseTokenMismatch(
                f"lease_token does not match the current lease for item {item_id}"
            )
        return await self._release_acquisition(
            db,
            actor_member_id=actor_member_id,
            actor_session_id=actor_session_id,
            actor_scheduler=actor_scheduler,
            actor_kind=actor_kind,
            workspace_id=workspace.id,
            scope_id=workspace.scope_id,
            item_id=item_id,
            expected_leased_at=workspace.leased_at,
            lease_token=lease_token,
        )

    async def release_by_owner(
        self,
        db: AsyncSession,
        item_id: int,
        actor_kind: str = "member",
        actor_member_id: int | None = None,
        actor_session_id: int | None = None,
        actor_scheduler: str | None = None,
        *,
        lease_token: str,
        workspace_id: int,
        scope_id: int,
        owner_slot_id: int,
        expected_leased_at: datetime | None,
    ) -> bool:
        """Release only while acquisition and item ownership still match."""
        return await self._release_acquisition(
            db,
            actor_kind=actor_kind,
            actor_member_id=actor_member_id,
            actor_session_id=actor_session_id,
            actor_scheduler=actor_scheduler,
            workspace_id=workspace_id,
            scope_id=scope_id,
            item_id=item_id,
            expected_leased_at=expected_leased_at,
            lease_token=lease_token,
            owner_slot_id=owner_slot_id,
        )

    async def release_blocker(
        self,
        scope: TeamGithubScope,
        workspace: GithubWorkspace,
        item: GithubWorkItem | None = None,
    ) -> str | None:
        """Return why a workspace must not be released, failing closed."""
        if workspace.kind == "primary":
            return None

        return_code, output = await self._runner(
            ["-C", workspace.path, "status", "--porcelain"]
        )
        if return_code != 0:
            return output.strip() or "workspace status could not be determined"
        if output.strip():
            return f"uncommitted or untracked changes:\n{output.strip()}"

        return_code, output = await self._runner(
            ["-C", workspace.path, "rev-list", "--count", f"{scope.base_ref}..HEAD"]
        )
        if return_code != 0:
            return output.strip() or "commits outside the dispatch base could not be determined"
        count = output.strip()
        if not count.isdecimal():
            return "commits outside the dispatch base could not be determined"
        if count != "0":
            if item is not None and item.pr_number is not None and item.dispatch_head_ref:
                return_code, head_output = await self._runner(
                    ["-C", workspace.path, "rev-parse", "--verify", "HEAD"]
                )
                head_sha = head_output.strip()
                if return_code != 0 or re.fullmatch(r"[0-9a-f]{40}", head_sha) is None:
                    return "workspace HEAD could not be verified"
                try:
                    token = None
                    if scope.github_auth_mode == "app":
                        if scope.github_app_installation_id is None:
                            return "GitHub App installation is not configured"
                        token = await github_app_auth_service.mint_repository_token(
                            scope.github_app_installation_id,
                            scope.repo_owner,
                            scope.repo_name,
                            purpose="pull_request",
                            cache_subject="workspace_release",
                        )
                    pull = await github_client.get_pull(
                        scope.repo_owner,
                        scope.repo_name,
                        item.pr_number,
                        token=token,
                    )
                except (GithubAppAuthError, GithubClientResponseError, httpx.HTTPError):
                    return "pushed PR head could not be verified on GitHub"
                head = pull.get("head")
                head_repo = head.get("repo") if isinstance(head, dict) else None
                if (
                    isinstance(head, dict)
                    and isinstance(head_repo, dict)
                    and head.get("sha") == head_sha
                    and head.get("ref") == item.dispatch_head_ref
                    and str(head_repo.get("full_name", "")).casefold()
                    == f"{scope.repo_owner}/{scope.repo_name}".casefold()
                    and (pull.get("state") == "open" or pull.get("merged_at") is not None)
                ):
                    return None
                return "workspace HEAD is not the pushed head of its recorded PR"
            return (
                f"{count} commit(s) not contained in local {scope.base_ref}; "
                "the next dispatch would reset --hard them away"
            )
        return None

    async def pending_work(
        self, scope: TeamGithubScope, workspace: GithubWorkspace
    ) -> tuple[str | None, int | None]:
        """Return pending paths and commits for reporting, never as a gate.

        Unlike release_blocker, observation failures return unknown values and
        do not veto an operator-authorized force release.
        """
        if workspace.kind == "primary":
            return None, None

        return_code, output = await self._runner(
            ["-C", workspace.path, "status", "--porcelain"]
        )
        paths = output.rstrip("\r\n") or None if return_code == 0 else None

        return_code, output = await self._runner(
            ["-C", workspace.path, "rev-list", "--count", f"{scope.base_ref}..HEAD"]
        )
        try:
            commits = int(output.strip()) if return_code == 0 else None
        except ValueError:
            commits = None
        return paths, commits

    async def touch_owner_contact(
        self,
        db: AsyncSession,
        item_id: int,
        *,
        lease_token: str | None,
        owner_slot_id: int,
    ) -> None:
        """Conditionally stamp contact for the current owner and acquisition."""
        if lease_token is None:
            return
        now = datetime.utcnow()
        owner_still_current = exists().where(
            GithubWorkItem.id == item_id,
            GithubWorkItem.owner_slot_id == owner_slot_id,
        )
        result = await db.execute(
            update(GithubWorkspace)
            .where(
                GithubWorkspace.leased_item_id == item_id,
                GithubWorkspace.lease_token == lease_token,
                owner_still_current,
            )
            .values(
                lease_last_owner_contact_at=now,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount:
            await db.commit()

    async def reclaim_stale(self, db: AsyncSession, scope: TeamGithubScope) -> int:
        threshold = datetime.utcnow() - timedelta(
            seconds=settings.github_stale_lease_backstop_seconds
        )
        leased = (
            await db.execute(
                select(GithubWorkspace, GithubWorkItem)
                .join(GithubWorkItem, GithubWorkspace.leased_item_id == GithubWorkItem.id)
                .where(
                    GithubWorkspace.scope_id == scope.id,
                    GithubWorkItem.dispatch_status.in_(_RECLAIMABLE_STATUSES),
                )
                .order_by(GithubWorkspace.id)
            )
        ).all()
        released = 0
        for workspace, item in leased:
            if workspace.kind == "primary":
                continue
            if workspace.leased_at is None or workspace.leased_at > threshold:
                continue
            if self._owner_process_is_alive(workspace):
                continue
            if (
                workspace.lease_last_owner_contact_at is not None
                and workspace.lease_last_owner_contact_at > threshold
            ):
                continue
            if not await self._worktree_is_quiescent(scope, workspace):
                continue
            released_now = await self._release_acquisition(
                db,
                actor_kind="scheduler", actor_scheduler="github_dispatch_scheduler",
                workspace_id=workspace.id,
                scope_id=scope.id,
                item_id=item.id,
                expected_leased_at=workspace.leased_at,
                lease_token=workspace.lease_token,
                owner_slot_id=item.owner_slot_id,
                expected_owner_pid=workspace.leased_owner_pid,
                expected_owner_proc_start=workspace.leased_owner_proc_start,
                expected_last_owner_contact_at=workspace.lease_last_owner_contact_at,
            )
            if released_now:
                released += 1
        return released

    async def _worktree_is_quiescent(
        self, scope: TeamGithubScope, workspace: GithubWorkspace
    ) -> bool:
        return_code, output = await self._runner(
            ["-C", workspace.path, "status", "--porcelain"]
        )
        if return_code != 0 or output.strip():
            return False

        return_code, output = await self._runner(
            ["-C", workspace.path, "rev-list", "--count", f"{scope.base_ref}..HEAD"]
        )
        if return_code != 0:
            return False
        return output.strip() == "0"

    async def reset_workspace(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        workspace: GithubWorkspace,
    ) -> None:
        if workspace.kind == "primary":
            return

        commands = [
            ["-C", workspace.path, "fetch", "origin", "--prune"],
            ["-C", workspace.path, "switch", "--detach", "--force", scope.base_ref],
            ["-C", workspace.path, "reset", "--hard", scope.base_ref],
            ["-C", workspace.path, "clean", "-fd"],
        ]
        for index, command in enumerate(commands):
            return_code, output = await self._runner(command)
            if return_code == 0:
                continue
            message = output.strip() or f"git {' '.join(command)} failed"
            workspace.provision_error = message
            workspace.updated_at = datetime.utcnow()
            transient = index == 0
            if not transient:
                workspace.enabled = False
            raise GithubWorkspaceResetError(message, transient=transient)
        workspace.provision_error = None
        workspace.updated_at = datetime.utcnow()

    async def register_workspace(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        path: str,
        *,
        kind: str = "worktree",
        dispatchable: bool = True,
        enabled: bool = True,
    ) -> GithubWorkspace:
        if kind not in {"primary", "worktree"}:
            raise ValueError(f"Unsupported workspace kind: {kind}")

        path = os.path.realpath(path)
        repo_path = os.path.realpath(scope.repo_path)
        empty_directory = False
        if kind == "worktree":
            workspace_root = os.path.dirname(repo_path)
            workspace_prefix = f"{workspace_root}{os.sep}"
            if not path.startswith(workspace_prefix):
                raise GithubWorkspaceError(
                    "A worktree path must be a direct sibling of the scope checkout",
                    "workspace_path_outside_root",
                )
            workspace_name = path[len(workspace_prefix) :]
            if not workspace_name or os.sep in workspace_name:
                raise GithubWorkspaceError(
                    "A worktree path must be a direct sibling of the scope checkout",
                    "workspace_path_outside_root",
                )
            path_exists = os.path.exists(path)
            if path_exists and os.path.isdir(path):
                with os.scandir(path) as entries:
                    empty_directory = next(entries, None) is None
        else:
            path_exists = True

        if kind == "worktree" and path == repo_path:
            raise GithubWorkspaceError(
                "The scope primary checkout cannot be registered as a worktree",
                "workspace_is_primary",
            )

        adopted = path_exists and not empty_directory
        if kind == "primary" and not adopted:
            raise GithubWorkspaceError(
                "A primary workspace must be an existing repository checkout"
            )

        if adopted:
            scope_identity = await self._probe_identity(repo_path)
            candidate_identity = await self._probe_identity(path)
            if scope_identity is None or candidate_identity is None:
                raise GithubWorkspaceError(
                    f"Workspace path is not a git worktree of {scope.repo_owner}/{scope.repo_name}"
                )
            git_dir, common_dir, top_level = candidate_identity
            _, scope_common_dir, _ = scope_identity
            if common_dir != scope_common_dir or top_level != path:
                raise GithubWorkspaceError(
                    f"Workspace path is not a worktree root of {scope.repo_owner}/{scope.repo_name}"
                )
            linked = git_dir != common_dir
            if kind == "worktree" and not linked:
                raise GithubWorkspaceError(
                    "The requested worktree path resolves to a primary checkout",
                    "workspace_is_primary",
                )
            if kind == "primary" and linked:
                raise GithubWorkspaceError(
                    "The requested primary path resolves to a linked worktree"
                )
            if dispatchable:
                await self._validate_adoption_is_available(path)
        else:
            await self._provision_worktree(scope, path)

        workspace = GithubWorkspace(
            scope_id=scope.id,
            path=path,
            kind=kind,
            dispatchable=dispatchable,
            enabled=enabled,
        )
        db.add(workspace)
        await db.commit()
        await db.refresh(workspace)
        return workspace

    async def ensure_dispatch_workspaces(
        self, db: AsyncSession, scope: TeamGithubScope
    ) -> ProvisioningReport:
        """Make `max_concurrent_dispatched` dispatchable worktrees exist for the scope.

        One `dispatch-N` direct sibling of the scope checkout at a time, in three phases so
        no database lock is held during filesystem work. Each phase takes the SQLite writer
        through the scope row, as scope updates do, so it is serialized with scope changes
        and with other workers:
          1. reserve: re-read the scope and the rows, count configured capacity and in-flight
             reservations, and insert a disabled reservation row for the next free name;
          2. create: claim the directory with an exclusive `mkdir` (an existing entry of any
             kind is never adopted or written), `git worktree add` into it, and re-verify it;
          3. finalize: re-read the scope; if its checkout, base, name or target changed,
             remove only what this call created, otherwise make the row dispatchable.
        Manual adoption stays in `register_workspace`; an existing row is never changed.
        """
        report = ProvisioningReport(target=scope.max_concurrent_dispatched)
        scope_id = scope.id
        await self._report_unavailable(db, scope, report)
        first = True
        try:
            for _ in range(min(report.target, MAX_PROVISIONED_PER_CALL) + MAX_WORKSPACE_NAME_SEARCH):
                try:
                    step = await self._reserve_workspace(db, scope_id, report, first)
                except OperationalError:
                    await db.rollback()
                    report.failures.append(
                        ProvisionFailure("", "database_busy", "The database was busy; try again."))
                    break
                first = False
                if step is None:
                    break
                if step == "retry":
                    continue
                if await self._create_workspace(db, step, report) == "failed":
                    break
        finally:
            # Rollbacks above expire the caller's scope; hand it back readable.
            try:
                await db.refresh(scope)
            except Exception:
                pass
        return report

    async def _lock_scope(self, db: AsyncSession, scope_id: int) -> TeamGithubScope | None:
        """Take the SQLite writer through the scope row, then read the scope fresh."""
        result = await db.execute(
            update(TeamGithubScope)
            .where(TeamGithubScope.id == scope_id)
            .values(id=TeamGithubScope.id)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            return None
        return (await db.execute(
            select(TeamGithubScope)
            .where(TeamGithubScope.id == scope_id)
            .execution_options(populate_existing=True)
        )).scalar_one()

    async def scope_common_dir(self, repo_path: str, runner=None) -> str | None:
        code, output = await (runner or self._runner)(
            ["-C", repo_path, "rev-parse", "--path-format=absolute", "--git-common-dir"]
        )
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        if code != 0 or not lines:
            return None
        return os.path.realpath(lines[0])

    async def workspace_state(self, path: str, scope_common: str, runner=None) -> str:
        """"ok", or the reason a registered workspace is not usable capacity."""
        if not path or not os.path.lexists(path):
            return "path_missing"
        if os.path.islink(path):
            return "path_is_symlink"
        if not os.path.isdir(path):
            return "path_missing"
        code, output = await (runner or self._runner)(
            ["-C", path, "rev-parse", "--path-format=absolute", "--git-dir",
             "--git-common-dir", "--show-toplevel"]
        )
        if code != 0:
            return "git_owner_differs" if "dubious ownership" in output.lower() else "not_a_git_checkout"
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        if len(lines) != 3:
            return "not_a_git_checkout"
        git_dir, common, top = (os.path.realpath(line) for line in lines)
        if common != scope_common:
            return "different_repository"
        if top != os.path.realpath(path) or git_dir == common:
            return "not_a_worktree_root"
        return "ok"

    async def _report_unavailable(
        self, db: AsyncSession, scope: TeamGithubScope, report: ProvisioningReport
    ) -> None:
        """Name configured workspaces whose checkout is missing or foreign. Their rows stay as
        they are: they are neither recreated nor adopted, and they are not usable capacity."""
        repo_real = _contained_path(scope.repo_path)
        if repo_real is None or not os.path.isdir(repo_real):
            return
        rows = (await db.execute(
            select(GithubWorkspace).where(
                GithubWorkspace.scope_id == scope.id,
                GithubWorkspace.kind == "worktree",
                GithubWorkspace.dispatchable.is_(True),
                GithubWorkspace.enabled.is_(True),
            ).order_by(GithubWorkspace.id)
        )).scalars().all()
        if not rows:
            return
        common = await self.scope_common_dir(repo_real)
        if common is None:
            return
        for row in rows:
            state = await self.workspace_state(row.path, common)
            if state != "ok":
                report.failures.append(ProvisionFailure(
                    row.path, "workspace_unavailable",
                    f"The registered workspace is not usable ({state}); its row is unchanged.",
                ))

    async def _reserve_workspace(self, db, scope_id: int, report: ProvisioningReport, first: bool):
        """Phase 1. Returns a reservation, "retry", or None when done or stopped."""
        scope = await self._lock_scope(db, scope_id)
        if scope is None:
            await db.rollback()
            report.failures.append(ProvisionFailure("", "scope_not_found", "The scope no longer exists."))
            return None
        report.target = scope.max_concurrent_dispatched
        scope_repo_path = scope.repo_path
        repo_real = _contained_path(scope_repo_path)
        if repo_real is None:
            await db.rollback()
            code = "scope_checkout_outside_home" if scope_repo_path else "scope_checkout_missing"
            report.failures.append(ProvisionFailure(
                scope_repo_path or "", code,
                "The scope checkout is not inside the home directory, so nothing was created."
                if scope_repo_path else "The scope has no checkout path.",
            ))
            return None
        if not os.path.isdir(repo_real):
            await db.rollback()
            report.failures.append(ProvisionFailure(
                scope_repo_path, "scope_checkout_missing",
                "The scope checkout does not exist, so no dispatch workspace was created.",
            ))
            return None
        rows = (await db.execute(
            select(GithubWorkspace).where(GithubWorkspace.scope_id == scope_id)
        )).scalars().all()
        now = datetime.utcnow()
        inflight = 0
        for row in rows:
            if row.provision_error == RESERVATION_MARKER and not row.enabled:
                if (now - row.created_at).total_seconds() > RESERVATION_STALE_SECONDS:
                    # A worker that died mid-provisioning: stop counting it, keep row and files.
                    row.provision_error = "abandoned: provisioning did not finish"
                else:
                    inflight += 1
        configured = sum(
            1 for row in rows if row.kind == "worktree" and row.dispatchable and row.enabled
        )
        if first:
            report.existing = configured
        if configured + inflight >= report.target:
            await db.commit()
            return None
        taken = {row.path for row in rows}
        root = os.path.dirname(repo_real)
        for number in range(1, MAX_WORKSPACE_NAME_SEARCH + 1):
            candidate = os.path.join(root, f"dispatch-{number}")
            if candidate in taken or os.path.lexists(candidate):
                continue
            row = GithubWorkspace(
                scope_id=scope_id, path=candidate, kind="worktree", dispatchable=False,
                enabled=False, provision_error=RESERVATION_MARKER,
            )
            db.add(row)
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                return "retry"
            return _Reservation(
                row.id, scope_id, candidate, repo_real,
                (scope.repo_path, scope.base_ref, scope.repo_owner, scope.repo_name),
            )
        await db.rollback()
        report.failures.append(ProvisionFailure(
            root, "no_free_workspace_name",
            f"No free dispatch-N name among the first {MAX_WORKSPACE_NAME_SEARCH} under {root}.",
        ))
        return None

    @staticmethod
    def _claim_directory(path: str) -> tuple[int, int] | None:
        """Create the directory exclusively. None when anything already exists there."""
        try:
            os.mkdir(path)
        except FileExistsError:
            return None
        info = os.lstat(path)
        return info.st_dev, info.st_ino

    @staticmethod
    def _is_claimed(path: str, claim: tuple[int, int]) -> bool:
        try:
            info = os.lstat(path)
        except OSError:
            return False
        return stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == claim

    def _remove_claim_if_empty(self, path: str, claim: tuple[int, int]) -> None:
        try:
            if self._is_claimed(path, claim) and not os.listdir(path):
                os.rmdir(path)
        except OSError:
            pass

    async def _release_reservation(self, db: AsyncSession, row_id: int) -> None:
        try:
            await db.execute(delete(GithubWorkspace).where(
                GithubWorkspace.id == row_id,
                GithubWorkspace.provision_error == RESERVATION_MARKER,
                GithubWorkspace.enabled.is_(False),
            ))
            await db.commit()
        except OperationalError:
            await db.rollback()

    async def _disable_reservation(self, db: AsyncSession, row_id: int, reason: str) -> None:
        try:
            await db.execute(update(GithubWorkspace).where(
                GithubWorkspace.id == row_id,
                GithubWorkspace.provision_error == RESERVATION_MARKER,
            ).values(enabled=False, dispatchable=False, provision_error=reason[:200]))
            await db.commit()
        except OperationalError:
            await db.rollback()

    async def _verify_created(self, res: "_Reservation", claim: tuple[int, int]) -> str | None:
        """None when the path is still the directory this call made, a linked worktree of the scope's repository."""
        if not self._is_claimed(res.path, claim):
            return "the path is no longer the directory this call created"
        common = await self.scope_common_dir(res.repo_path)
        if common is None or await self.workspace_state(res.path, common) != "ok":
            return "the new checkout is not a worktree of the scope's repository"
        return None

    async def _discard_created(self, res: "_Reservation", claim: tuple[int, int]) -> bool:
        """Remove only a worktree this call created and can still identify. True when it is gone."""
        if not self._is_claimed(res.path, claim):
            return not os.path.lexists(res.path)
        common = await self.scope_common_dir(res.repo_path)
        if common is not None and await self.workspace_state(res.path, common) == "ok":
            await self._runner(["-C", res.repo_path, "worktree", "remove", "--force", res.path])
        self._remove_claim_if_empty(res.path, claim)
        return not os.path.lexists(res.path)

    async def _create_workspace(self, db: AsyncSession, res: "_Reservation", report: ProvisioningReport) -> str:
        """Phases 2 and 3. "created", "skipped" (the name was not ours to take) or "failed"."""
        try:
            claim = self._claim_directory(res.path)
        except OSError as exc:
            await self._release_reservation(db, res.row_id)
            report.failures.append(ProvisionFailure(
                res.path, "provision_failed", _provision_reason(str(exc)) or type(exc).__name__))
            return "failed"
        if claim is None:
            await self._release_reservation(db, res.row_id)
            return "skipped"
        try:
            await self._provision_worktree(
                SimpleNamespace(repo_path=res.repo_path, base_ref=res.snapshot[1]), res.path)
        except Exception as exc:
            self._remove_claim_if_empty(res.path, claim)
            await self._release_reservation(db, res.row_id)
            report.failures.append(ProvisionFailure(
                res.path, "provision_failed", _provision_reason(str(exc)) or type(exc).__name__))
            return "failed"
        problem = await self._verify_created(res, claim)
        if problem is not None:
            await self._disable_reservation(db, res.row_id, f"workspace_path_changed: {problem}")
            report.failures.append(ProvisionFailure(res.path, "workspace_path_changed", problem))
            return "failed"
        try:
            scope = await self._lock_scope(db, res.scope_id)
            stale = None
            if scope is None:
                stale = ("scope_changed_during_provisioning", "The scope no longer exists.")
            elif (scope.repo_path, scope.base_ref, scope.repo_owner, scope.repo_name) != res.snapshot:
                stale = ("scope_changed_during_provisioning",
                         "The scope's checkout, base or name changed while provisioning.")
            else:
                others = (await db.execute(
                    select(func.count()).select_from(GithubWorkspace).where(
                        GithubWorkspace.scope_id == res.scope_id,
                        GithubWorkspace.id != res.row_id,
                        GithubWorkspace.kind == "worktree",
                        GithubWorkspace.dispatchable.is_(True),
                        GithubWorkspace.enabled.is_(True),
                    ))).scalar_one()
                if others >= scope.max_concurrent_dispatched:
                    stale = ("target_reduced_during_provisioning",
                             "The scope's concurrency was lowered while provisioning.")
            if stale is None:
                updated = await db.execute(update(GithubWorkspace).where(
                    GithubWorkspace.id == res.row_id,
                    GithubWorkspace.provision_error == RESERVATION_MARKER,
                ).values(enabled=True, dispatchable=True, provision_error=None, updated_at=datetime.utcnow()))
                if updated.rowcount == 1:
                    await db.commit()
                    report.created.append(res.path)
                    return "created"
                stale = ("workspace_reservation_lost", "The reservation was removed while provisioning.")
            await db.rollback()
        except OperationalError:
            await db.rollback()
            stale = ("database_busy", "The database was busy while finishing; the new checkout was discarded.")
        gone = await self._discard_created(res, claim)
        if gone:
            await self._release_reservation(db, res.row_id)
        else:
            await self._disable_reservation(db, res.row_id, f"{stale[0]}: the new checkout could not be removed")
        report.failures.append(ProvisionFailure(res.path, stale[0], stale[1]))
        return "failed"

    async def no_workspace_note(self, db: AsyncSession, scope: TeamGithubScope) -> str | None:
        """Why a dispatch found no workspace, or None when the cause is not one of these."""
        rows = (await db.execute(
            select(GithubWorkspace).where(GithubWorkspace.scope_id == scope.id)
        )).scalars().all()
        if not rows:
            return (
                "No dispatchable workspace is registered for this scope. Synth City provisions dispatch "
                "workspaces when a scope is created or its concurrency rises; see "
                f"GET /api/v1/agent-teams/github-scopes/{scope.id}/workspace-readiness."
            )
        if any(row.provision_error == RESERVATION_MARKER and not row.enabled for row in rows):
            return "Dispatch workspaces are still being provisioned for this scope."
        usable = [row for row in rows if row.enabled and row.dispatchable]
        if not usable:
            return f"All {len(rows)} workspace(s) are disabled or not dispatchable."
        if all(row.leased_item_id is not None for row in usable):
            return f"All {len(usable)} dispatchable workspace(s) are leased by other items."
        return None

    async def _probe_identity(self, path: str) -> tuple[str, str, str] | None:
        return_code, output = await self._runner(
            [
                "-C",
                path,
                "rev-parse",
                "--path-format=absolute",
                "--git-dir",
                "--git-common-dir",
                "--show-toplevel",
            ]
        )
        if return_code != 0:
            return None
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        if len(lines) != 3:
            return None
        return tuple(os.path.realpath(line) for line in lines)

    async def _validate_adoption_is_available(self, path: str) -> None:
        return_code, output = await self._runner(["-C", path, "status", "--porcelain"])
        if return_code != 0:
            raise GithubWorkspaceError(
                output.strip() or "Unable to inspect workspace status"
            )
        if output.strip():
            raise GithubWorkspaceError(
                f"Workspace has uncommitted or untracked changes:\n{output.strip()}",
                "workspace_dirty",
            )
        for session in discover_agent_sessions():
            cwd = session.get("cwd")
            if cwd and os.path.realpath(cwd) == path:
                raise GithubWorkspaceError(
                    f"Workspace is occupied by live session {session.get('tmux_target', '')}".strip(),
                    "workspace_occupied",
                )

    async def _provision_worktree(self, scope: TeamGithubScope, path: str) -> None:
        command = [
            "-C",
            scope.repo_path,
            "worktree",
            "add",
            "--detach",
            path,
            scope.base_ref,
        ]
        return_code, output = await self._runner(command)
        if return_code != 0:
            raise GithubWorkspaceError(
                output.strip() or f"git {' '.join(command)} failed"
            )


github_workspace_service = GithubWorkspaceService()
