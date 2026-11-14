"""Read-only report of a scope's dispatch workspaces and slot repository identities (#564).

Nothing here writes: git is only asked `rev-parse`, no row changes, and the `safe.directory`
entries are text for an operator to run as the right user. Applying another user's git
configuration is an installation action and stays an explicit operator step.
"""
from __future__ import annotations

import hashlib
import os
import re
import shlex

from sqlalchemy import select

from app.models.database import AgentTeamSlot, GithubWorkspace, TeamGithubScope
from app.services.github_workspace_service import RESERVATION_MARKER, github_workspace_service

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

_WORKSPACE_MESSAGES = {
    "path_missing": "The registered checkout does not exist, so it is not usable capacity.",
    "path_is_symlink": "The registered path is a symbolic link, so it is not usable capacity.",
    "git_owner_differs": "git refused the checkout: the owner differs, so it is not usable capacity.",
    "not_a_git_checkout": "The registered path is not a git checkout, so it is not usable capacity.",
    "not_a_worktree_root": "The registered path is not the root of a linked worktree, so it is not usable capacity.",
    "different_repository": "The registered checkout belongs to a different repository than the scope.",
}

_MESSAGES = {
    "path_missing": "The slot's repository path does not exist.",
    "git_owner_differs": (
        "git refused the checkout: the owner differs. Add the path to safe.directory for the "
        "user that runs git (see safe_directory), then save the slot's repository path again."
    ),
    "not_a_git_checkout": "The slot's repository path is not a git checkout.",
    "different_repository": "The slot's repository path belongs to a different repository than the scope.",
    "stored_identity_stale": (
        "The slot's stored repository identity is out of date (git was refused earlier or the "
        "checkout moved); save the slot's repository path again so Synth City recomputes it."
    ),
}


async def _probe(path: str, runner) -> tuple[str, str]:
    """Return ("ok", common_dir) or (failure_code, "")."""
    if not path or not os.path.isdir(path):
        return "path_missing", ""
    code, output = await runner(
        ["-C", path, "rev-parse", "--path-format=absolute", "--git-common-dir"]
    )
    if code != 0:
        if "dubious ownership" in output.lower():
            return "git_owner_differs", ""
        return "not_a_git_checkout", ""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return "not_a_git_checkout", ""
    return "ok", os.path.realpath(lines[0])


def _identity(common_dir: str) -> str:
    # Same formula as repo_utils.derive_repo_identity, so the stored slot identity compares.
    return hashlib.sha1(common_dir.encode("utf-8")).hexdigest()[:16]


async def repo_id_for(path: str, runner) -> str | None:
    state, common = await _probe(path, runner)
    return _identity(common) if state == "ok" else None


async def check_slot_identity(db, scope: TeamGithubScope, slot: AgentTeamSlot, runner=None) -> dict:
    runner = runner or github_workspace_service._runner
    result = {
        "slot_id": slot.id, "display_name": slot.display_name,
        "status": "ok", "code": None, "message": None,
    }
    scope_state, scope_common = await _probe(scope.repo_path, runner)
    if scope_state != "ok":
        result.update(
            status="unverified", code="scope_identity_unavailable",
            message="The scope checkout's repository identity could not be read, so slots cannot be compared.",
        )
        return result
    slot_state, slot_common = await _probe(slot.repo_path, runner)
    code = None
    if slot_state != "ok":
        code = slot_state
    elif slot_common != scope_common:
        code = "different_repository"
    elif slot.repo_id != _identity(slot_common):
        code = "stored_identity_stale"
    if code is not None:
        result.update(status="mismatch", code=code, message=_MESSAGES[code])
    return result


def _entry(path: str) -> dict:
    return {"path": path, "command": f"git config --global --add safe.directory {shlex.quote(path)}"}


def _lease_state(row: GithubWorkspace) -> str:
    if row.leased_item_id is not None:
        return "leased"
    if not row.enabled:
        return "disabled"
    if not row.dispatchable:
        return "disabled_for_dispatch"
    return "available"


async def build_readiness(db, scope: TeamGithubScope, runner=None) -> dict:
    runner = runner or github_workspace_service._runner
    rows = (await db.execute(
        select(GithubWorkspace).where(GithubWorkspace.scope_id == scope.id).order_by(GithubWorkspace.id)
    )).scalars().all()
    slots = (await db.execute(
        select(AgentTeamSlot)
        .where(AgentTeamSlot.preset_id == scope.preset_id, AgentTeamSlot.enabled.is_(True))
        .order_by(AgentTeamSlot.position, AgentTeamSlot.id)
    )).scalars().all()
    scope_repo = scope.repo_path if scope.repo_path and os.path.isdir(scope.repo_path) else None
    scope_common = await github_workspace_service.scope_common_dir(scope_repo, runner) if scope_repo else None
    entries, dispatchable = [], 0
    for r in rows:
        status, code, message = "not_dispatchable", None, None
        if r.provision_error == RESERVATION_MARKER and not r.enabled:
            status, message = "provisioning", "Being provisioned by a worker; not usable yet."
        elif r.kind == "worktree" and r.dispatchable and r.enabled:
            if scope_common is None:
                status, code, message = "unavailable", "scope_identity_unavailable", "The scope checkout's identity could not be read."
            else:
                state = await github_workspace_service.workspace_state(r.path, scope_common, runner)
                if state == "ok":
                    status = "ok"
                    dispatchable += 1
                else:
                    status, code, message = "unavailable", state, _WORKSPACE_MESSAGES.get(state, state)
        entries.append({"path": r.path, "kind": r.kind, "lease_state": _lease_state(r),
                        "dispatchable": r.dispatchable, "enabled": r.enabled,
                        "status": status, "code": code, "message": message})

    slot_results, controller, native, unsafe = [], [], [], []
    seen_controller, seen_native = set(), set()

    def add(paths: list, seen: set, path: str, label: str) -> None:
        # A quoted '*' is still a wildcard to git (a trailing "/*" trusts everything below it),
        # so such a path is reported, never emitted. Only absolute paths are exact entries.
        if _CONTROL.search(path) or "*" in path or not os.path.isabs(path):
            unsafe.append({"display_name": label, "reason": "The path is not an exact absolute path (control characters, '*' or relative) and is not listed."})
        elif path and path not in seen:
            seen.add(path)
            paths.append(_entry(path))

    add(controller, seen_controller, scope.repo_path, "scope checkout")
    for slot in slots:
        check = await check_slot_identity(db, scope, slot, runner)
        check["repo_path"] = slot.repo_path
        slot_results.append(check)
        add(controller, seen_controller, slot.repo_path, slot.display_name)
    for row in rows:
        if row.kind == "worktree" and row.enabled and row.provision_error != RESERVATION_MARKER:
            add(native, seen_native, row.path, "dispatch workspace")
    return {
        "scope_id": scope.id,
        "repo_path": scope.repo_path,
        "target": scope.max_concurrent_dispatched,
        "dispatchable_workspaces": dispatchable,
        "shortfall": max(0, scope.max_concurrent_dispatched - dispatchable),
        "workspaces": entries,
        "slots": slot_results,
        "safe_directory": {"controller": controller, "native": native},
        "unsafe_paths": unsafe,
    }
