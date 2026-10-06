"""Bounded, read-only Git observations for an already registered workspace.

These facts describe publication. They never approve work or release a lease.
File names, Git diagnostics, configuration, and credentials stay private.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import re
import signal
from dataclasses import dataclass

_SHA = re.compile(r"[0-9a-f]{40}")
_MAX_OUTPUT = 512 * 1024
_MAX_COMMITS = 10_000
_COMMAND_SECONDS = 2


async def _gather(*operations):
    tasks = [asyncio.create_task(operation) for operation in operations]
    try:
        return await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class ProgressObservationError(RuntimeError):
    """A fixed public reason, with no command output or private paths."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class WorkspaceProgressContext:
    scope_path: str
    workspace_path: str
    kind: str


@dataclass(frozen=True)
class LocalProgressObservation:
    sha: str
    branch: str | None
    tracked_changes: int
    untracked_files: int
    # Used only to detect changes during the read. Never saved or returned.
    status_bytes: bytes


def status_counts(raw: bytes) -> tuple[int, int]:
    """Count porcelain-v1 NUL records, including the second rename path."""
    if raw and not raw.endswith(b"\0"):
        raise ProgressObservationError("invalid_git_observation")
    records = raw.split(b"\0")[:-1]
    tracked = untracked = index = 0
    while index < len(records):
        record = records[index]
        if len(record) < 4 or record[2:3] != b" ":
            raise ProgressObservationError("invalid_git_observation")
        state = record[:2]
        if any(value not in b" MADRCU?!" for value in state):
            raise ProgressObservationError("invalid_git_observation")
        if state == b"??":
            untracked += 1
        elif state == b"!!":
            raise ProgressObservationError("invalid_git_observation")
        else:
            tracked += 1
        if b"R" in state or b"C" in state:
            index += 1
            if index >= len(records) or not records[index]:
                raise ProgressObservationError("invalid_git_observation")
        index += 1
    return tracked, untracked


class WorkspaceProgressObserver:
    def __init__(self, runner=None):
        self._runner = runner or self._run_git

    @staticmethod
    def _allowed(context: WorkspaceProgressContext) -> None:
        try:
            scope = pathlib.Path(context.scope_path)
            workspace = pathlib.Path(context.workspace_path)
            # Registration stores real absolute paths. A later symlink or move
            # invalidates this observation instead of redirecting the read.
            if (not scope.is_absolute() or not workspace.is_absolute()
                    or scope.resolve(strict=True) != scope
                    or workspace.resolve(strict=True) != workspace):
                raise ProgressObservationError("workspace_identity_unavailable")
            if context.kind == "primary":
                allowed = workspace == scope
            else:
                allowed = (context.kind == "worktree" and workspace != scope
                           and workspace.parent == scope.parent)
            if not allowed or not workspace.is_dir() or not scope.is_dir():
                raise ProgressObservationError("workspace_identity_unavailable")
        except (OSError, RuntimeError) as error:
            if isinstance(error, ProgressObservationError):
                raise
            raise ProgressObservationError("workspace_identity_unavailable") from None

    @staticmethod
    async def _run_git(path: str, args: list[str]) -> tuple[int, bytes]:
        env = {key: value for key, value in os.environ.items()
               if not key.startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
        try:
            process = await asyncio.create_subprocess_exec(
                "git", "--no-optional-locks", "--no-pager", "--no-replace-objects",
                "-c", f"safe.directory={path}", "-c", "core.fsmonitor=false",
                "-c", "core.hooksPath=/dev/null", "-C", path, *args,
                env=env, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=os.name == "posix",
            )
        except OSError:
            raise ProgressObservationError("git_unavailable") from None

        async def read():
            output = bytearray()
            while chunk := await process.stdout.read(16 * 1024):
                output.extend(chunk)
                if len(output) > _MAX_OUTPUT:
                    raise ProgressObservationError("observation_limit")
            await process.wait()
            return process.returncode, bytes(output)

        completed = False
        try:
            result = await asyncio.wait_for(read(), timeout=_COMMAND_SECONDS)
            completed = True
            return result
        except asyncio.TimeoutError:
            raise ProgressObservationError("observation_timeout") from None
        finally:
            if not completed or process.returncode is None:
                try:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()

    async def _identity(self, path: str) -> tuple[str, str, str]:
        code, raw = await self._runner(path, [
            "rev-parse", "--path-format=absolute", "--git-dir",
            "--git-common-dir", "--show-toplevel",
        ])
        try:
            rows = raw.decode("utf-8", "strict").splitlines()
            if code or len(rows) != 3:
                raise ValueError
            return tuple(str(pathlib.Path(row).resolve(strict=True)) for row in rows)
        except (ValueError, OSError, UnicodeError):
            raise ProgressObservationError("workspace_identity_unavailable") from None

    async def _state(self, path: str) -> LocalProgressObservation:
        head, branch, status = await _gather(
            self._runner(path, ["rev-parse", "--verify", "HEAD^{commit}"]),
            self._runner(path, ["symbolic-ref", "--quiet", "--short", "HEAD"]),
            self._runner(path, ["status", "--porcelain=v1", "-z",
                                "--untracked-files=all", "--ignore-submodules=none"]),
        )
        try:
            sha = head[1].decode("ascii", "strict").strip()
            branch_name = branch[1].decode("utf-8", "strict").strip()
        except UnicodeError:
            raise ProgressObservationError("invalid_git_observation") from None
        if head[0] or not _SHA.fullmatch(sha) or status[0]:
            raise ProgressObservationError("invalid_git_observation")
        if branch[0] not in (0, 1) or branch[0] == 0 and not branch_name:
            raise ProgressObservationError("invalid_git_observation")
        tracked, untracked = status_counts(status[1])
        return LocalProgressObservation(
            sha, branch_name if branch[0] == 0 else None, tracked, untracked, status[1],
        )

    async def read(self, context: WorkspaceProgressContext) -> LocalProgressObservation:
        self._allowed(context)
        scope, workspace = await _gather(
            self._identity(context.scope_path), self._identity(context.workspace_path),
        )
        if (scope[1] != workspace[1] or workspace[2] != context.workspace_path
                or scope[2] != context.scope_path
                or context.kind == "worktree" and workspace[0] == workspace[1]):
            raise ProgressObservationError("workspace_identity_unavailable")
        return await self._state(context.workspace_path)

    async def confirm(
        self, context: WorkspaceProgressContext, before: LocalProgressObservation,
    ) -> bool:
        return await self.read(context) == before

    async def compare(
        self, context: WorkspaceProgressContext, local_sha: str, published_sha: str,
    ) -> tuple[str, int]:
        if not _SHA.fullmatch(local_sha) or not _SHA.fullmatch(published_sha):
            raise ProgressObservationError("invalid_git_observation")
        if local_sha == published_sha:
            return "synchronized", 0
        code, raw = await self._runner(context.workspace_path, [
            "rev-list", "--left-right", "--count", f"--max-count={_MAX_COMMITS + 1}",
            f"{published_sha}...{local_sha}", "--",
        ])
        parts = raw.split()
        if code or len(parts) != 2 or not all(value.isdigit() for value in parts):
            raise ProgressObservationError("published_object_unavailable")
        remote, local = (int(value) for value in parts)
        if remote + local > _MAX_COMMITS:
            raise ProgressObservationError("observation_limit")
        relation = ("diverged" if remote and local else "behind" if remote
                    else "ahead" if local else "synchronized")
        return relation, local


workspace_progress_observer = WorkspaceProgressObserver()
