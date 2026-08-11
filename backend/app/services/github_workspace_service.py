"""Provision and lease isolated workspaces for GitHub dispatch."""
from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import GithubWorkItem, GithubWorkspace, TeamGithubScope
from app.services.agent_bridge.discovery import discover_agent_sessions

GIT_TIMEOUT_SECONDS = 300

_GIT_ENV = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "",
    "SSH_ASKPASS": "",
    "GIT_CONFIG_NOSYSTEM": "1",
}

_RECLAIMABLE_STATUSES = ("escalated", "failed", "merged", "completed")

logger = logging.getLogger(__name__)


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


class GithubWorkspaceService:
    def __init__(self, runner=None):
        self._runner = runner or self._run_git

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
            return 124, f"git {' '.join(args)} timed out after {GIT_TIMEOUT_SECONDS}s"
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
    ) -> GithubWorkspace | None:
        held = (
            await db.execute(
                select(GithubWorkspace).where(GithubWorkspace.leased_item_id == item.id)
            )
        ).scalar_one_or_none()
        if held is not None:
            return held

        workspace = (
            await db.execute(
                select(GithubWorkspace)
                .where(
                    GithubWorkspace.scope_id == scope.id,
                    GithubWorkspace.enabled.is_(True),
                    GithubWorkspace.dispatchable.is_(True),
                    GithubWorkspace.leased_item_id.is_(None),
                )
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
                await self.release(db, item.id)
                return None
            workspace.updated_at = datetime.utcnow()
            await db.commit()
        return workspace

    async def release(self, db: AsyncSession, item_id: int) -> None:
        workspace = (
            await db.execute(
                select(GithubWorkspace).where(GithubWorkspace.leased_item_id == item_id)
            )
        ).scalar_one_or_none()
        if workspace is None:
            return
        now = datetime.utcnow()
        workspace.leased_item_id = None
        workspace.released_at = now
        workspace.lease_token = None
        workspace.leased_owner_pid = None
        workspace.leased_owner_proc_start = None
        workspace.lease_last_owner_contact_at = None
        workspace.lease_release_reminded_at = None
        workspace.updated_at = now
        await db.commit()

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
        now = datetime.utcnow()
        result = await db.execute(
            update(GithubWorkspace)
            .where(
                GithubWorkspace.id == workspace_id,
                GithubWorkspace.scope_id == scope_id,
                GithubWorkspace.leased_item_id == item_id,
                GithubWorkspace.leased_at == expected_leased_at,
                GithubWorkspace.lease_token == lease_token,
            )
            .values(
                leased_item_id=None,
                released_at=now,
                lease_token=None,
                leased_owner_pid=None,
                leased_owner_proc_start=None,
                lease_last_owner_contact_at=None,
                lease_release_reminded_at=None,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            return False
        await db.commit()
        return True

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
    ) -> None:
        """Release only the workspace acquisition named by the token.

        Item identity alone cannot distinguish a stale report from an earlier
        dispatch attempt. Requiring the acquisition token prevents that report
        from releasing a replacement owner's live lease.
        """
        workspace = await self.get_leased_workspace(db, item_id)
        if workspace is None:
            return
        if workspace.lease_token != lease_token:
            raise GithubWorkspaceLeaseTokenMismatch(
                f"lease_token does not match the current lease for item {item_id}"
            )
        await self.release(db, item_id)

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
        lease_token: str | None = None,
    ) -> None:
        """Stamp contact evidence only on the matching workspace acquisition.

        A stale token is a deliberate no-op because contact recording is only a
        side effect of a status report whose primary state change already
        succeeded.
        """
        workspace = await self.get_leased_workspace(db, item_id)
        if workspace is None:
            return
        if workspace.lease_token is not None and lease_token != workspace.lease_token:
            logger.info(
                "ignoring owner contact for item %s: token mismatch (lease is on "
                "a different attempt)",
                item_id,
            )
            return
        workspace.lease_last_owner_contact_at = datetime.utcnow()
        workspace.updated_at = workspace.lease_last_owner_contact_at
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
            await self.release(db, workspace.leased_item_id)
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
