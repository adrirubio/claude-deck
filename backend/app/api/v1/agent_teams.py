"""Agent Team Preset endpoints."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.database import GithubWorkItem, TeamGithubScope
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
)
from app.services.github_dispatch_service import github_dispatch_service
from app.services.github_verification_service import github_verification_service
from app.services.agent_team_service import PlanConflictError, agent_team_service
from app.services.providers.base import ProviderLaunchError

router = APIRouter()


def _bad_request(exc: ValueError) -> HTTPException:
    if isinstance(exc, ProviderLaunchError):
        return HTTPException(
            status_code=400,
            detail={"message": str(exc), "block_code": exc.block_code},
        )
    return HTTPException(status_code=400, detail=str(exc))


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
    elif report.status == "pr_opened":
        if report.pr_number is None:
            raise HTTPException(status_code=400, detail="pr_number required")
        await github_verification_service.report_pr_opened(db, item, scope, report.pr_number)
    elif report.status == "in_progress":
        if report.pr_number is not None:
            item.pr_number = report.pr_number
            item.updated_at = datetime.utcnow()
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
        return await agent_team_service.update_preset(
            db,
            preset_id,
            name=request.name,
            description=request.description,
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.delete("/presets/{preset_id}", status_code=204)
async def delete_preset(preset_id: int, db: AsyncSession = Depends(get_db)):
    try:
        await agent_team_service.delete_preset(db, preset_id)
        return Response(status_code=204)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
