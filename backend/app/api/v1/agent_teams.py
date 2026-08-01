"""Agent Team Preset endpoints."""
from __future__ import annotations

from datetime import datetime
from string import Formatter

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.database import GithubWorkItem, GithubWorkspace, TeamGithubScope
from app.models.schemas import (
    AgentTeamCreateFromBridgeRequest,
    AgentTeamCreateFromMailRequest,
    AgentTeamLaunchPlan,
    AgentTeamLaunchRequest,
    AgentTeamLaunchResult,
    AgentTeamPresetCreate,
    AgentTeamPresetListResponse,
    AgentTeamPresetResponse,
    AgentTeamPresetUpdate,
    AgentTeamSlotCreate,
    AgentTeamSlotReorderRequest,
    AgentTeamSlotUpdate,
    DispatchStatusReport,
    GithubWorkItemAbandonRequest,
    GithubWorkItemListResponse,
    GithubWorkItemRetryRequest,
    GithubWorkItemResponse,
    GithubWorkspaceCreate,
    GithubWorkspaceListResponse,
    GithubWorkspaceResponse,
    TeamGithubScopeCreate,
    TeamGithubScopeListResponse,
    TeamGithubScopeResponse,
    TeamGithubScopeUpdate,
)
from app.services.github_dispatch_scheduler import github_dispatch_scheduler
from app.services.github_dispatch_service import github_dispatch_service
from app.services.github_workspace_service import (
    GithubWorkspaceError,
    GithubWorkspaceResetError,
    github_workspace_service,
)
from app.services.github_verification_service import github_verification_service
from app.services.agent_team_service import PlanConflictError, agent_team_service
from app.services.providers.base import ProviderLaunchError

router = APIRouter()

_WORKSPACE_CONFLICT_CODES = {
    "workspace_path_registered",
    "workspace_not_a_worktree",
    "workspace_is_primary",
    "workspace_dirty",
    "workspace_occupied",
    "workspace_leased",
    "workspace_reset_failed",
    "work_item_not_abandonable",
}


def _bad_request(exc: ValueError) -> HTTPException:
    if isinstance(exc, ProviderLaunchError):
        return HTTPException(
            status_code=400,
            detail={"message": str(exc), "block_code": exc.block_code},
        )
    return HTTPException(status_code=400, detail=str(exc))


def _conflict(message: str, block_code: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"message": message, "block_code": block_code},
    )


def _clean_required(value: str | None, label: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    return text


def _clean_repo_part(value: str | None, label: str) -> str:
    text = _clean_required(value, label)
    if any(char.isspace() for char in text) or "/" in text:
        raise ValueError(f"{label} must not contain whitespace or slash")
    return text


def _clean_label(value: str | None, label: str) -> str:
    return _clean_required(value, label)


def _validate_template(
    value: str,
    *,
    label: str,
    allowed_fields: set[str],
    render_values: dict[str, object],
) -> str:
    try:
        for _, field_name, format_spec, conversion in Formatter().parse(value):
            if field_name is None:
                continue
            if (
                field_name not in allowed_fields
                or format_spec
                or conversion is not None
            ):
                raise ValueError
        value.format(**render_values)
    except (KeyError, IndexError, ValueError) as exc:
        allowed = ", ".join(f"{{{field}}}" for field in sorted(allowed_fields))
        raise ValueError(f"{label} may only use placeholders: {allowed}") from exc
    return value


def _scope_response(scope: TeamGithubScope) -> TeamGithubScopeResponse:
    return TeamGithubScopeResponse(
        id=scope.id,
        preset_id=scope.preset_id,
        repo_owner=scope.repo_owner,
        repo_name=scope.repo_name,
        repo_path=scope.repo_path,
        dispatch_label=scope.dispatch_label,
        design_label=scope.design_label,
        merge_policy=scope.merge_policy,
        max_approval_rounds=scope.max_approval_rounds,
        max_concurrent_dispatched=scope.max_concurrent_dispatched,
        max_verification_retries=scope.max_verification_retries,
        max_auto_merges_per_day=scope.max_auto_merges_per_day,
        base_ref=scope.base_ref,
        builds_out_of_tree=scope.builds_out_of_tree,
        build_dir_template=scope.build_dir_template,
        build_command_hint=scope.build_command_hint,
        max_build_parallelism=scope.max_build_parallelism,
        enabled=scope.enabled,
        last_polled_at=scope.last_polled_at,
        created_at=scope.created_at,
        updated_at=scope.updated_at,
    )


def _workspace_lease_state(workspace: GithubWorkspace) -> str:
    if workspace.leased_item_id is not None:
        return "leased"
    if not workspace.enabled:
        return "disabled"
    if not workspace.dispatchable:
        return "disabled_for_dispatch"
    return "available"


def _workspace_response(workspace: GithubWorkspace) -> GithubWorkspaceResponse:
    return GithubWorkspaceResponse(
        id=workspace.id,
        scope_id=workspace.scope_id,
        path=workspace.path,
        kind=workspace.kind,
        lease_state=_workspace_lease_state(workspace),
        dispatchable=workspace.dispatchable,
        leased_item_id=workspace.leased_item_id,
        leased_at=workspace.leased_at,
        released_at=workspace.released_at,
        provision_error=workspace.provision_error,
        enabled=workspace.enabled,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
    )


def _work_item_response(
    item: GithubWorkItem,
    scope: TeamGithubScope,
    workspace_path: str | None = None,
) -> GithubWorkItemResponse:
    return GithubWorkItemResponse(
        id=item.id,
        scope_id=item.scope_id,
        repo_owner=scope.repo_owner,
        repo_name=scope.repo_name,
        issue_number=item.issue_number,
        issue_title=item.issue_title,
        issue_url=item.issue_url,
        github_updated_at=item.github_updated_at,
        issue_type=item.issue_type,
        dispatch_status=item.dispatch_status,
        pending_reason=item.pending_reason,
        launch_id=item.launch_id,
        owner_slot_id=item.owner_slot_id,
        routing_method=item.routing_method,
        handoff_state=item.handoff_state,
        handoff_target_slot_id=item.handoff_target_slot_id,
        approval_round_count=item.approval_round_count,
        pr_number=item.pr_number,
        retry_count=item.retry_count,
        last_verified_sha=item.last_verified_sha,
        escalation_reason=item.escalation_reason,
        status_note=item.status_note,
        auto_merged_at=item.auto_merged_at,
        workspace_path=workspace_path,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


async def _sync_github_jobs(db: AsyncSession) -> None:
    await github_dispatch_scheduler.sync_jobs(db)


def _apply_scope_create(
    scope: TeamGithubScope,
    request: TeamGithubScopeCreate | TeamGithubScopeUpdate,
) -> None:
    if request.repo_owner is not None:
        scope.repo_owner = _clean_repo_part(request.repo_owner, "Repo owner")
    if request.repo_name is not None:
        scope.repo_name = _clean_repo_part(request.repo_name, "Repo name")
    if request.repo_path is not None:
        repo_path, _ = agent_team_service.normalize_repo_path(request.repo_path)
        scope.repo_path = repo_path
    if request.dispatch_label is not None:
        scope.dispatch_label = _clean_label(request.dispatch_label, "Dispatch label")
    if request.design_label is not None:
        scope.design_label = _clean_label(request.design_label, "Design label")
    if request.merge_policy is not None:
        scope.merge_policy = request.merge_policy
    if request.max_approval_rounds is not None:
        scope.max_approval_rounds = request.max_approval_rounds
    if request.max_concurrent_dispatched is not None:
        scope.max_concurrent_dispatched = request.max_concurrent_dispatched
    if request.max_verification_retries is not None:
        scope.max_verification_retries = request.max_verification_retries
    if request.max_auto_merges_per_day is not None:
        scope.max_auto_merges_per_day = request.max_auto_merges_per_day
    if request.base_ref is not None:
        scope.base_ref = _clean_required(request.base_ref, "Base ref")
    if request.builds_out_of_tree is not None:
        scope.builds_out_of_tree = request.builds_out_of_tree
    if request.build_dir_template is not None:
        scope.build_dir_template = _validate_template(
            request.build_dir_template,
            label="Build directory template",
            allowed_fields={"issue_number"},
            render_values={"issue_number": 1},
        )
    if request.build_command_hint is not None:
        scope.build_command_hint = _validate_template(
            request.build_command_hint,
            label="Build command hint",
            allowed_fields={"build_dir", "parallelism"},
            render_values={"build_dir": "build", "parallelism": 4},
        )
    if request.max_build_parallelism is not None:
        scope.max_build_parallelism = request.max_build_parallelism
    if request.enabled is not None:
        scope.enabled = request.enabled
    scope.updated_at = datetime.utcnow()


@router.post("/dispatch-status")
async def report_dispatch_status(
    report: DispatchStatusReport,
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(GithubWorkItem, report.work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="work item not found")
    scope = await db.get(TeamGithubScope, item.scope_id)

    if report.status == "triaging":
        if report.note is not None:
            item.status_note = report.note
            item.updated_at = datetime.utcnow()
            await db.commit()
    elif report.status == "revision_requested":
        await github_dispatch_service.record_approval_round(db, item, scope)
    elif report.status == "handoff_initiated":
        if report.reassign_to_slot_id is None:
            raise HTTPException(status_code=400, detail="reassign_to_slot_id required")
        await github_dispatch_service.initiate_handoff(db, item, report.reassign_to_slot_id)
    elif report.status == "handoff_accepted":
        if report.reporting_slot_id is None:
            raise HTTPException(status_code=400, detail="reporting_slot_id required")
        try:
            await github_dispatch_service.accept_handoff(db, item, report.reporting_slot_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    elif report.status == "blocked":
        await github_dispatch_service.escalate(db, item, "plan_blocked", report.note)
        await db.commit()
    elif report.status == "ack_received":
        await github_dispatch_service.record_ack_received(db, item)
    elif report.status == "pr_opened":
        if report.pr_number is None:
            raise HTTPException(status_code=400, detail="pr_number required")
        try:
            await github_verification_service.report_pr_opened(db, item, scope, report.pr_number)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    elif report.status == "in_progress":
        now = datetime.utcnow()
        item.last_nudge_at = None
        if report.pr_number is not None:
            item.pr_number = report.pr_number
        item.updated_at = now
        await db.commit()
    else:
        raise HTTPException(status_code=400, detail=f"unknown status {report.status}")

    await db.refresh(item)
    return {
        "work_item_id": item.id,
        "dispatch_status": item.dispatch_status,
        "escalation_reason": item.escalation_reason,
        "handoff_state": item.handoff_state,
    }


@router.get("/presets", response_model=AgentTeamPresetListResponse)
async def list_presets(db: AsyncSession = Depends(get_db)):
    return AgentTeamPresetListResponse(presets=await agent_team_service.list_presets(db))


@router.post("/presets", response_model=AgentTeamPresetResponse)
async def create_preset(
    request: AgentTeamPresetCreate,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await agent_team_service.create_preset(db, request)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/presets/from-agent-mail", response_model=AgentTeamPresetResponse)
async def create_preset_from_agent_mail(
    request: AgentTeamCreateFromMailRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await agent_team_service.create_from_agent_mail(db, request)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/presets/from-agent-bridge", response_model=AgentTeamPresetResponse)
async def create_preset_from_agent_bridge(
    request: AgentTeamCreateFromBridgeRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await agent_team_service.create_from_agent_bridge(db, request)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/presets/{preset_id}", response_model=AgentTeamPresetResponse)
async def get_preset(preset_id: int, db: AsyncSession = Depends(get_db)):
    try:
        return await agent_team_service.get_preset(db, preset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/presets/{preset_id}", response_model=AgentTeamPresetResponse)
async def update_preset(
    preset_id: int,
    request: AgentTeamPresetUpdate,
    db: AsyncSession = Depends(get_db),
):
    try:
        response = await agent_team_service.update_preset(
            db,
            preset_id,
            name=request.name,
            description=request.description,
            autonomy_enabled=request.autonomy_enabled,
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc
    if request.autonomy_enabled is not None:
        await _sync_github_jobs(db)
    return response


@router.delete("/presets/{preset_id}", status_code=204)
async def delete_preset(preset_id: int, db: AsyncSession = Depends(get_db)):
    try:
        await agent_team_service.delete_preset(db, preset_id)
        await _sync_github_jobs(db)
        return Response(status_code=204)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/presets/{preset_id}/github-scopes",
    response_model=TeamGithubScopeListResponse,
)
async def list_github_scopes(preset_id: int, db: AsyncSession = Depends(get_db)):
    try:
        await agent_team_service.require_preset_row(db, preset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    scopes = (
        await db.execute(
            select(TeamGithubScope)
            .where(TeamGithubScope.preset_id == preset_id)
            .order_by(TeamGithubScope.repo_owner, TeamGithubScope.repo_name, TeamGithubScope.id)
        )
    ).scalars().all()
    return TeamGithubScopeListResponse(scopes=[_scope_response(scope) for scope in scopes])


@router.post(
    "/presets/{preset_id}/github-scopes",
    response_model=TeamGithubScopeResponse,
)
async def create_github_scope(
    preset_id: int,
    request: TeamGithubScopeCreate,
    db: AsyncSession = Depends(get_db),
):
    try:
        await agent_team_service.require_preset_row(db, preset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        scope = TeamGithubScope(
            preset_id=preset_id,
            repo_owner="",
            repo_name="",
            repo_path="",
        )
        _apply_scope_create(scope, request)
        db.add(scope)
        await db.commit()
        await db.refresh(scope)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="GitHub scope already exists for this repo") from exc
    except ValueError as exc:
        raise _bad_request(exc) from exc
    await _sync_github_jobs(db)
    return _scope_response(scope)


@router.patch("/github-scopes/{scope_id}", response_model=TeamGithubScopeResponse)
async def update_github_scope(
    scope_id: int,
    request: TeamGithubScopeUpdate,
    db: AsyncSession = Depends(get_db),
):
    scope = await db.get(TeamGithubScope, scope_id)
    if scope is None:
        raise HTTPException(status_code=404, detail="GitHub scope not found")
    try:
        _apply_scope_create(scope, request)
        await db.commit()
        await db.refresh(scope)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="GitHub scope already exists for this repo") from exc
    except ValueError as exc:
        raise _bad_request(exc) from exc
    await _sync_github_jobs(db)
    return _scope_response(scope)


@router.delete("/github-scopes/{scope_id}", status_code=204)
async def delete_github_scope(scope_id: int, db: AsyncSession = Depends(get_db)):
    scope = await db.get(TeamGithubScope, scope_id)
    if scope is None:
        raise HTTPException(status_code=404, detail="GitHub scope not found")
    await db.delete(scope)
    await db.commit()
    await _sync_github_jobs(db)
    return Response(status_code=204)


@router.get(
    "/github-scopes/{scope_id}/workspaces",
    response_model=GithubWorkspaceListResponse,
)
async def list_github_workspaces(
    scope_id: int,
    db: AsyncSession = Depends(get_db),
):
    scope = await db.get(TeamGithubScope, scope_id)
    if scope is None:
        raise HTTPException(status_code=404, detail="GitHub scope not found")
    workspaces = (
        await db.execute(
            select(GithubWorkspace)
            .where(GithubWorkspace.scope_id == scope_id)
            .order_by(GithubWorkspace.id)
        )
    ).scalars().all()
    return GithubWorkspaceListResponse(
        workspaces=[_workspace_response(workspace) for workspace in workspaces]
    )


@router.post(
    "/github-scopes/{scope_id}/workspaces",
    response_model=GithubWorkspaceResponse,
    status_code=201,
)
async def create_github_workspace(
    scope_id: int,
    request: GithubWorkspaceCreate,
    db: AsyncSession = Depends(get_db),
):
    scope = await db.get(TeamGithubScope, scope_id)
    if scope is None:
        raise HTTPException(status_code=404, detail="GitHub scope not found")
    if request.kind not in {"primary", "worktree"}:
        raise HTTPException(status_code=400, detail="Workspace kind must be primary or worktree")
    try:
        path, _ = agent_team_service.normalize_repo_path(request.path)
    except ValueError as exc:
        raise _bad_request(exc) from exc
    existing = (
        await db.execute(select(GithubWorkspace).where(GithubWorkspace.path == path))
    ).scalar_one_or_none()
    if existing is not None:
        raise _conflict(
            "Workspace path already registered",
            block_code="workspace_path_registered",
        )
    dispatchable = (
        request.dispatchable
        if request.dispatchable is not None
        else request.kind == "worktree"
    )
    try:
        workspace = await github_workspace_service.register_workspace(
            db,
            scope,
            path,
            kind=request.kind,
            dispatchable=dispatchable,
            enabled=request.enabled,
        )
    except GithubWorkspaceError as exc:
        block_code = (
            exc.block_code
            if exc.block_code in _WORKSPACE_CONFLICT_CODES
            else "workspace_not_a_worktree"
        )
        raise _conflict(str(exc), block_code=block_code) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise _conflict(
            "Workspace path already registered",
            block_code="workspace_path_registered",
        ) from exc
    return _workspace_response(workspace)


@router.post(
    "/github-scopes/{scope_id}/workspaces/{workspace_id}/reprobe",
    response_model=GithubWorkspaceResponse,
)
async def reprobe_github_workspace(
    scope_id: int,
    workspace_id: int,
    db: AsyncSession = Depends(get_db),
):
    scope = await db.get(TeamGithubScope, scope_id)
    if scope is None:
        raise HTTPException(status_code=404, detail="GitHub scope not found")
    workspace = await db.get(GithubWorkspace, workspace_id)
    if workspace is None or workspace.scope_id != scope_id:
        raise HTTPException(status_code=404, detail="GitHub workspace not found")
    if workspace.leased_item_id is not None:
        raise _conflict(
            "Workspace is currently leased",
            block_code="workspace_leased",
        )
    if workspace.kind == "primary":
        raise _conflict(
            "Primary workspaces are never reset",
            block_code="workspace_is_primary",
        )
    was_enabled = workspace.enabled
    try:
        await github_workspace_service.reset_workspace(db, scope, workspace)
    except GithubWorkspaceResetError as exc:
        workspace.enabled = was_enabled if exc.transient else False
        workspace.provision_error = str(exc)
        workspace.updated_at = datetime.utcnow()
        await db.commit()
        raise _conflict(str(exc), block_code="workspace_reset_failed") from exc
    workspace.enabled = True
    workspace.provision_error = None
    workspace.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(workspace)
    return _workspace_response(workspace)


@router.get(
    "/presets/{preset_id}/github-work-items",
    response_model=GithubWorkItemListResponse,
)
async def list_github_work_items(
    preset_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    try:
        await agent_team_service.require_preset_row(db, preset_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    rows = (
        await db.execute(
            select(GithubWorkItem, TeamGithubScope, GithubWorkspace.path)
            .join(TeamGithubScope, TeamGithubScope.id == GithubWorkItem.scope_id)
            .outerjoin(GithubWorkspace, GithubWorkspace.leased_item_id == GithubWorkItem.id)
            .where(TeamGithubScope.preset_id == preset_id)
            .order_by(GithubWorkItem.updated_at.desc(), GithubWorkItem.id.desc())
            .limit(limit)
        )
    ).all()
    return GithubWorkItemListResponse(
        items=[
            _work_item_response(item, scope, workspace_path)
            for item, scope, workspace_path in rows
        ]
    )


@router.post(
    "/github-work-items/{work_item_id}/retry",
    response_model=GithubWorkItemResponse,
)
async def retry_github_work_item(
    work_item_id: int,
    request: GithubWorkItemRetryRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(GithubWorkItem, work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="GitHub work item not found")
    scope = await db.get(TeamGithubScope, item.scope_id)
    if scope is None:
        raise HTTPException(status_code=404, detail="GitHub scope not found")
    if item.dispatch_status != "escalated":
        raise HTTPException(status_code=409, detail="Only escalated work items can be retried")
    if item.pr_number is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Work item has PR #{item.pr_number} already open; retry would orphan "
                "it. Resolve or close the PR first."
            ),
        )
    github_dispatch_service.reset_for_retry(item)
    if request is not None and request.reason:
        item.pending_reason = f"retry requested: {request.reason}"
    await db.commit()
    await db.refresh(item)
    return _work_item_response(item, scope)


@router.post(
    "/github-work-items/{work_item_id}/abandon",
    response_model=GithubWorkItemResponse,
)
async def abandon_github_work_item(
    work_item_id: int,
    request: GithubWorkItemAbandonRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(GithubWorkItem, work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="GitHub work item not found")
    scope = await db.get(TeamGithubScope, item.scope_id)
    if scope is None:
        raise HTTPException(status_code=404, detail="GitHub scope not found")
    if item.dispatch_status not in {
        "ready_for_review",
        "awaiting_human_review",
        "dispatched",
        "verifying",
    }:
        raise _conflict(
            f"Work item in status {item.dispatch_status} cannot be abandoned",
            block_code="work_item_not_abandonable",
        )
    note = (
        request.reason
        if request is not None and request.reason
        else (
            "Abandoned by operator; workspace lease will be reclaimed once the "
            "owner session is offline."
        )
    )
    await github_dispatch_service.escalate(
        db,
        item,
        "abandoned_by_operator",
        note=note,
    )
    await db.commit()
    await db.refresh(item)
    return _work_item_response(item, scope)


@router.post("/presets/{preset_id}/duplicate", response_model=AgentTeamPresetResponse)
async def duplicate_preset(
    preset_id: int,
    request: AgentTeamPresetUpdate,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await agent_team_service.duplicate_preset(db, preset_id, name=request.name)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/presets/{preset_id}/slots", response_model=AgentTeamPresetResponse)
async def add_slot(
    preset_id: int,
    request: AgentTeamSlotCreate,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await agent_team_service.add_slot(db, preset_id, request)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.patch("/slots/{slot_id}", response_model=AgentTeamPresetResponse)
async def update_slot(
    slot_id: int,
    request: AgentTeamSlotUpdate,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await agent_team_service.update_slot(db, slot_id, request)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.delete("/slots/{slot_id}", response_model=AgentTeamPresetResponse)
async def delete_slot(slot_id: int, db: AsyncSession = Depends(get_db)):
    try:
        return await agent_team_service.delete_slot(db, slot_id)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/presets/{preset_id}/slots/reorder", response_model=AgentTeamPresetResponse)
async def reorder_slots(
    preset_id: int,
    request: AgentTeamSlotReorderRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await agent_team_service.reorder_slots(db, preset_id, request.slot_ids)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/presets/{preset_id}/plan-launch", response_model=AgentTeamLaunchPlan)
async def plan_launch(
    preset_id: int,
    request: AgentTeamLaunchRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await agent_team_service.plan_launch(db, preset_id, request)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post(
    "/presets/{preset_id}/launch/plan",
    response_model=AgentTeamLaunchPlan,
    include_in_schema=False,
)
async def plan_launch_compat(
    preset_id: int,
    request: AgentTeamLaunchRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await plan_launch(preset_id, request, db)


@router.post("/presets/{preset_id}/launch", response_model=AgentTeamLaunchResult)
async def launch_preset(
    preset_id: int,
    request: AgentTeamLaunchRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await agent_team_service.launch(db, preset_id, request)
    except PlanConflictError as exc:
        detail: dict[str, object] = {"message": str(exc)}
        if exc.plan is not None:
            detail["plan"] = jsonable_encoder(exc.plan)
        raise HTTPException(status_code=409, detail=detail) from exc
    except ValueError as exc:
        raise _bad_request(exc) from exc
