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
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import GithubWorkItem, GithubWorkspace, TeamGithubScope
from app.services.agent_bridge.discovery import discover_agent_sessions
from app.services.agent_mail_install_service import deck_base_url
from app.services.github_app_auth_service import (
    GithubAppAuthError,
    github_app_auth_service,
)

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

    def config_lock(self, workspace_id: int) -> asyncio.Lock:
        return self._config_locks.setdefault(workspace_id, asyncio.Lock())

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
        workspace.updated_at = now
        await db.commit()

        if workspace.kind != "primary":
            try:
                await self.reset_workspace(db, scope, workspace)
            except GithubWorkspaceResetError:
                if workspace.leased_at is not None:
                    await self.force_release_acquisition(
                        db,
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
        return f"{slug}{suffix}@claude-deck.local"

    @staticmethod
    def slot_name(display_name: str) -> str:
        return f"{display_name} (Deck agent)"

    @staticmethod
    def _credential_helper_command(lease_token: str) -> str:
        helper_path = pathlib.Path(__file__).resolve().parents[2] / "mcp_shim" / "git_credential_helper.py"
        return shlex.join(
            [
                sys.executable,
                str(helper_path),
                "--deck-url",
                deck_base_url(),
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
            if (
                workspace_row.scope_id != scope_id
                or workspace_row.leased_item_id != item_id
                or workspace_row.leased_at != expected_leased_at
                or workspace_row.lease_token != lease_token
            ):
                await db.rollback()
                return False
            await db.commit()
            snapshot = (
                None
                if config_workspace.kind == "primary"
                else await self.snapshot_worktree_config(config_workspace)
            )
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
                await db.rollback()
                return False
            try:
                await self.revoke_push_token(
                    scope,
                    config_workspace,
                    owner_slot_id=(
                        owner_slot_id
                        if owner_slot_id is not None
                        else current_owner_slot_id
                    ),
                )
                if config_workspace.kind != "primary":
                    await self.remove_managed_worktree_config(config_workspace)
                await db.commit()
                return True
            except BaseException as exc:
                await db.rollback()
                if snapshot is not None:
                    try:
                        await self.restore_worktree_config(config_workspace, snapshot)
                    except GithubWorkspaceConfigError as restore_exc:
                        detail = (
                            "Worktree release failed and managed config restoration "
                            f"also failed: {restore_exc}"
                        )
                        await self._record_config_repair_note(
                            db,
                            workspace_id=workspace_id,
                            item_id=item_id,
                            detail=detail,
                        )
                        if not isinstance(exc, Exception):
                            raise exc from restore_exc
                        raise GithubWorkspaceConfigError(
                            detail,
                            restoration_failed=True,
                        ) from restore_exc
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
        self, db: AsyncSession, item_id: int, *, lease_token: str
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
            workspace_id=workspace_id,
            scope_id=scope_id,
            item_id=item_id,
            expected_leased_at=expected_leased_at,
            lease_token=lease_token,
            owner_slot_id=owner_slot_id,
        )

    async def release_blocker(
        self, scope: TeamGithubScope, workspace: GithubWorkspace
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
            return output.strip() or "unpushed commits could not be determined"
        if output.strip() != "0":
            return (
                f"{output.strip()} commit(s) not pushed to {scope.base_ref}; "
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
        path_exists = os.path.exists(path)
        empty_directory = False
        if path_exists and os.path.isdir(path):
            with os.scandir(path) as entries:
                empty_directory = next(entries, None) is None

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
