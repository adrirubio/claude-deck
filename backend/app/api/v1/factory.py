"""Local observational delivery reads; legacy protected remedies stay separate."""
import asyncio
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.v1.deps import require_operator
from app.config import settings
from app.models import factory_schemas as wire
from app.models.schemas import (
    FactoryReviewAcceptanceDeclaration, SetupPreflightRequest, SetupPreflightResponse,
    SetupPreflightCheck,
)
from app.services.github_client import github_client, GithubClientResponseError
from app.services.github_app_auth_service import GithubAppAuthError, github_app_auth_service
from app.services import factory_projection_service as projections
from app.utils.repo_utils import is_primary_github_checkout


class FactoryReadRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            try:
                return await original(request)
            except RequestValidationError:
                error = projections.FactoryReadError("invalid_filter", 422)
            except projections.FactoryReadError as exc:
                error = exc
            except HTTPException:
                raise
            except Exception:
                # Neither DB exceptions nor failed observations are empty data.
                # Do not serialize private query parameters or diagnostics.
                error = projections.FactoryReadError("projection_failed", 500)
            return JSONResponse(status_code=error.status,
                                content={"detail": {"code": error.code, "message": str(error)}})

        return handle


router = APIRouter(route_class=FactoryReadRoute)


def _github_rate_limited(exc: httpx.HTTPStatusError) -> bool:
    """Recognize GitHub rate limits without treating every 403 as one."""
    response = exc.response
    if response.status_code == 429:
        return True
    if response.status_code != 403:
        return False
    if response.headers.get("x-ratelimit-remaining") == "0" or response.headers.get("retry-after"):
        return True
    try:
        body = response.json()
    except ValueError:
        return False
    message = body.get("message", "") if isinstance(body, dict) else ""
    message = message.casefold() if isinstance(message, str) else ""
    return "rate limit" in message or "secondary rate" in message


@router.post("/setup-preflight", response_model=SetupPreflightResponse)
async def setup_preflight(
    request: SetupPreflightRequest,
    _operator: None = Depends(require_operator),
):
    """Observe setup prerequisites. This route never creates or changes records."""
    checked_at = datetime.now(timezone.utc)
    repository_info: dict | None = None

    async def checkout_check() -> SetupPreflightCheck:
        try:
            path = Path(request.repo_path).expanduser()
            if not path.is_dir():
                return SetupPreflightCheck(status="blocked", code="checkout_unavailable")
            matches = await asyncio.wait_for(
                asyncio.to_thread(
                    is_primary_github_checkout,
                    str(path), request.repo_owner, request.repo_name,
                ),
                timeout=8.0,
            )
            if not matches:
                return SetupPreflightCheck(status="blocked", code="checkout_identity_mismatch")
            return SetupPreflightCheck(status="ready", code="checkout_identity_matches")
        except (asyncio.TimeoutError, subprocess.TimeoutExpired):
            # A bounded Git subprocess timeout is a dated safe unknown, not a
            # server failure. Independent checks keep their own results.
            return SetupPreflightCheck(status="unknown", code="checkout_check_timeout")
        except (OSError, ValueError, KeyError):
            return SetupPreflightCheck(status="unknown", code="checkout_check_failed")

    async def repository_check() -> SetupPreflightCheck:
        nonlocal repository_info
        if not settings.github_token:
            return SetupPreflightCheck(status="blocked", code="polling_credential_missing")
        try:
            repository_info = await asyncio.wait_for(
                github_client.get_repository(request.repo_owner, request.repo_name), timeout=5.0
            )
            return SetupPreflightCheck(status="ready", code="repository_readable")
        except asyncio.TimeoutError:
            return SetupPreflightCheck(status="unknown", code="repository_check_timeout")
        except httpx.HTTPStatusError as exc:
            if _github_rate_limited(exc):
                return SetupPreflightCheck(status="unknown", code="github_rate_limited")
            if exc.response.status_code in (403, 404):
                return SetupPreflightCheck(status="blocked", code="repository_not_readable")
            return SetupPreflightCheck(status="unknown", code="repository_check_failed")
        except Exception:
            return SetupPreflightCheck(status="unknown", code="repository_check_failed")

    async def base_branch_check() -> SetupPreflightCheck:
        if request.base_ref == "origin/HEAD":
            default_branch = repository_info.get("default_branch") if repository_info else None
            if isinstance(default_branch, str) and default_branch.strip():
                return SetupPreflightCheck(status="ready", code="repository_default_branch_available")
            return SetupPreflightCheck(status="unknown", code="repository_default_branch_unknown")
        if not request.base_ref.startswith("origin/"):
            return SetupPreflightCheck(status="blocked", code="base_branch_invalid")
        branch = request.base_ref.removeprefix("origin/")
        try:
            valid = await asyncio.wait_for(asyncio.to_thread(
                subprocess.run,
                ["git", "check-ref-format", f"refs/remotes/{branch}"],
                capture_output=True, text=True, timeout=2, check=False,
            ), timeout=3.0)
        except asyncio.TimeoutError:
            return SetupPreflightCheck(status="unknown", code="base_branch_check_timeout")
        except (OSError, subprocess.TimeoutExpired):
            return SetupPreflightCheck(status="unknown", code="base_branch_check_failed")
        if valid.returncode != 0:
            return SetupPreflightCheck(status="blocked", code="base_branch_invalid")
        try:
            ref = await asyncio.wait_for(
                github_client.get_ref(
                    request.repo_owner, request.repo_name, branch,
                    token=settings.github_token,
                ),
                timeout=5.0,
            )
            return SetupPreflightCheck(
                status="ready" if ref is not None else "blocked",
                code="base_branch_exists" if ref is not None else "base_branch_missing",
            )
        except asyncio.TimeoutError:
            return SetupPreflightCheck(status="unknown", code="base_branch_check_timeout")
        except httpx.HTTPStatusError as exc:
            if _github_rate_limited(exc):
                return SetupPreflightCheck(status="unknown", code="github_rate_limited")
            if exc.response.status_code in (403, 404):
                return SetupPreflightCheck(status="blocked", code="base_branch_not_readable")
            return SetupPreflightCheck(status="unknown", code="base_branch_check_failed")
        except Exception:
            return SetupPreflightCheck(status="unknown", code="base_branch_check_failed")

    async def labels_check() -> tuple[SetupPreflightCheck, SetupPreflightCheck]:
        try:
            labels = await asyncio.wait_for(
                github_client.list_repo_labels(request.repo_owner, request.repo_name), timeout=5.0
            )
        except asyncio.TimeoutError:
            unknown = SetupPreflightCheck(status="unknown", code="label_check_timeout")
            return unknown, unknown
        except httpx.HTTPStatusError as exc:
            if _github_rate_limited(exc):
                unknown = SetupPreflightCheck(status="unknown", code="github_rate_limited")
                return unknown, unknown
            if exc.response.status_code in (403, 404):
                blocked = SetupPreflightCheck(status="blocked", code="labels_not_readable")
                return blocked, blocked
            unknown = SetupPreflightCheck(status="unknown", code="label_check_failed")
            return unknown, unknown
        except GithubClientResponseError:
            # Bounded or unsafe pagination is an incomplete observation, not a block.
            unknown = SetupPreflightCheck(status="unknown", code="label_check_incomplete")
            return unknown, unknown
        except Exception:
            unknown = SetupPreflightCheck(status="unknown", code="label_check_failed")
            return unknown, unknown
        return tuple(
            SetupPreflightCheck(
                status="ready" if label in labels else "blocked",
                code="selected_label_exists" if label in labels else "selected_label_missing",
            )
            for label in (request.dispatch_label, request.design_label)
        )

    if request.dispatch_auth_mode == "token":
        dispatch_auth = SetupPreflightCheck(
            status="ready" if settings.github_token else "blocked",
            code="dispatch_token_configured" if settings.github_token else "dispatch_token_missing",
        )
    else:
        try:
            github_app_auth_service.require_configuration(require_bot_login=True)
            installation_id = await asyncio.wait_for(
                github_app_auth_service.resolve_installation(request.repo_owner, request.repo_name),
                timeout=5.0,
            )
            dispatch_auth = SetupPreflightCheck(
                status="ready" if installation_id is not None else "blocked",
                code="github_app_installation_available" if installation_id is not None else "github_app_installation_missing",
            )
        except asyncio.TimeoutError:
            dispatch_auth = SetupPreflightCheck(status="unknown", code="github_app_installation_lookup_timeout")
        except GithubAppAuthError as exc:
            dispatch_auth = SetupPreflightCheck(
                status="blocked" if exc.code == "app_auth_unconfigured" else "unknown",
                code="github_app_configuration_missing" if exc.code == "app_auth_unconfigured" else "github_app_installation_lookup_failed",
            )

    repository_status = await repository_check()
    dispatch_label_status, design_label_status = await labels_check()
    if dispatch_label_status.status == "unknown" or design_label_status.status == "unknown":
        labels_status = SetupPreflightCheck(status="unknown", code="label_check_incomplete")
    elif dispatch_label_status.status == "blocked" or design_label_status.status == "blocked":
        labels_status = SetupPreflightCheck(status="blocked", code="selected_labels_missing")
    else:
        labels_status = SetupPreflightCheck(status="ready", code="selected_labels_exist")
    checks = {
        "checkout_identity": await checkout_check(),
        "polling_credential": SetupPreflightCheck(
            status="ready" if settings.github_token else "blocked",
            code="polling_credential_configured" if settings.github_token else "polling_credential_missing",
        ),
        "operator_credential": SetupPreflightCheck(
            status="ready" if settings.operator_token else "blocked",
            code="operator_token_configured" if settings.operator_token else "operator_token_missing",
        ),
        "repository_read": repository_status,
        "labels": labels_status,
        "dispatch_label": dispatch_label_status,
        "design_label": design_label_status,
        "base_branch": await base_branch_check(),
        "dispatch_auth": dispatch_auth,
    }
    if all(check.status == "ready" for check in checks.values()):
        status = "ready"
    elif any(check.status == "blocked" for check in checks.values()):
        status = "blocked"
    else:
        status = "unknown"
    remedies = {
        "checkout_unavailable": "Select an available primary checkout, then run this check again.",
        "checkout_identity_mismatch": "Select a primary checkout whose origin matches this repository.",
        "polling_credential_missing": "Configure the operator's GitHub polling credential before activation.",
        "repository_not_readable": "Grant repository read access to the configured GitHub credential.",
        "github_rate_limited": "Wait for GitHub's rate limit to reset, then run this check again.",
        "selected_label_missing": "Create the selected label on the repository, then run this check again.",
        "base_branch_invalid": "Use origin/HEAD or an existing origin/<branch> reference.",
        "base_branch_missing": "Select an existing remote branch or restore the configured branch.",
        "github_app_configuration_missing": "Configure the GitHub App and its bot login before using App authentication.",
        "github_app_installation_missing": "Install the configured GitHub App on this repository.",
        "dispatch_token_missing": "Configure the dispatch GitHub token or select a configured GitHub App.",
        "operator_token_missing": "Configure operator_token in backend/.env, then apply the documented backend restart.",
    }
    for name, check in list(checks.items()):
        if check.status == "ready":
            remedy = "No action is required for this check."
        elif check.status == "unknown":
            # Unknown checks use a specific safe remedy when one exists.
            remedy = remedies.get(check.code, "Keep setup disabled and retry this observation after the service responds.")
        else:
            remedy = remedies.get(check.code, "Review this check's safe code and complete the required host setup.")
        checks[name] = check.model_copy(update={"remedy": remedy})
    # Allowlisted key names with boolean presence only; never values or paths.
    configuration_presence = {
        "github_token": bool(settings.github_token),
        "operator_token": bool(settings.operator_token),
        "github_app_id": bool(settings.github_app_id),
        "github_app_private_key_path": bool(settings.github_app_private_key_path),
        "github_app_bot_login": bool(settings.github_app_bot_login),
    }
    host_guidance = [
        "Configure github_token and operator_token in backend/.env.",
        "Configure the existing GitHub App settings only when App authentication is selected.",
        "Install the required harness and Agent Mail integration for team activation.",
        "Apply the documented backend restart when settings change, then repeat this check.",
        "Create missing labels on GitHub, then repeat this check.",
    ]
    return SetupPreflightResponse(
        status=status,
        observed_at=checked_at,
        checked_at=checked_at,
        checks=checks,
        configuration_presence=configuration_presence,
        host_guidance=host_guidance,
    )


async def read_snapshot(db: AsyncSession = Depends(get_db)):
    # sqlite3's legacy mode does not begin on SELECT. Establish a real read
    # snapshot before counts/records/authority reads; never acquire a writer.
    if db.get_bind().dialect.name == "sqlite" and not db.in_transaction():
        await db.execute(text("BEGIN"))
    with db.no_autoflush:
        yield db


def filters(
    team_id: int | None = Query(None, ge=1, le=2**63 - 1),
    scope_id: int | None = Query(None, ge=1, le=2**63 - 1),
    provider: str | None = Query(None),
):
    return wire.FactoryFilters(team_id=team_id, scope_id=scope_id, provider=provider)


def work_filters(
    selected: wire.FactoryFilters = Depends(filters),
    category: str = Query("all", pattern="^(all|queued|active|review|attention|finished|unknown)$"),
):
    return wire.WorkFilters(**selected.model_dump(), category=category)


@router.get("/overview", response_model=wire.OverviewResponse)
async def overview(selected: wire.FactoryFilters = Depends(filters), db=Depends(read_snapshot)):
    return await projections.overview(db, selected)


@router.get("/work-items", response_model=wire.WorkListResponse)
async def work_items(
    selected: wire.WorkFilters = Depends(work_filters),
    limit: int = Query(50, ge=1, le=100), cursor: str | None = Query(None),
    db=Depends(read_snapshot),
):
    return await projections.work_list(db, selected, limit, cursor)


@router.get("/work-items/{item_id}", response_model=wire.WorkDetailResponse)
async def work_item(item_id: int, db=Depends(read_snapshot)):
    if not 0 < item_id < 2**63:
        raise projections.FactoryReadError("invalid_filter", 422)
    return await projections.work_detail(db, item_id)


@router.get("/repositories", response_model=wire.RepositoryListResponse)
async def repositories(
    selected: wire.FactoryFilters = Depends(filters),
    limit: int = Query(50, ge=1, le=100), cursor: str | None = Query(None),
    db=Depends(read_snapshot),
):
    return await projections.repositories(db, selected, limit, cursor)


@router.get("/repositories/{scope_id}", response_model=wire.RepositoryDetailResponse)
async def repository(scope_id: int, db=Depends(read_snapshot)):
    if not 0 < scope_id < 2**63:
        raise projections.FactoryReadError("invalid_filter", 422)
    return await projections.repository_detail(db, scope_id)


# ---------------------------------------------------------------------------
# P05: observation ledger reads and safe delivery metrics
# ---------------------------------------------------------------------------

@router.get("/audit-events")
async def list_factory_audit_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    event_kind: str | None = None,
    team_context_key: str | None = None,
    scope_context_key: str | None = None,
    item_context_key: str | None = None,
    team_id: int | None = None,
    scope_id: int | None = None,
    item_id: int | None = None,
    _operator: None = Depends(require_operator),
    db=Depends(get_db),
):
    """A15/A16/A21/A38: operator-protected paginated audit reads.

    Historical context keys address retained history after deletion; current
    ID filters resolve the current resource context key. Agent tokens do not
    authorize audit reads. Deleted live links are labelled unavailable while
    snapshot labels remain readable.
    """
    from sqlalchemy import func, select

    from app.models.database import FactoryAuditEvent
    from app.models.schemas import FactoryAuditEventPage, FactoryAuditEventRead
    from app.services.factory_audit_service import current_context_key as _current_key

    # C05/R01: current-ID filters resolve the active key of the current
    # resource lifetime. The read never allocates a key and performs no write.
    # A current ID with no recorded lifetime key selects no events.
    unresolved = False
    for numeric, kind, supplied in (
        (team_id, "team", team_context_key),
        (scope_id, "scope", scope_context_key),
        (item_id, "item", item_context_key),
    ):
        if numeric is None or supplied is not None:
            continue
        resolved = await _current_key(db, kind, numeric)
        if resolved is None:
            unresolved = True
        elif kind == "team":
            team_context_key = resolved
        elif kind == "scope":
            scope_context_key = resolved
        else:
            item_context_key = resolved
    if unresolved:
        return FactoryAuditEventPage(
            items=[], total=0, page=page, page_size=page_size,
            team_context_key=team_context_key, scope_context_key=scope_context_key,
            event_kind=event_kind, snapshot_labels=[])

    stmt = select(FactoryAuditEvent)
    count_stmt = select(func.count()).select_from(FactoryAuditEvent)
    if event_kind:
        stmt = stmt.where(FactoryAuditEvent.event_kind == event_kind)
        count_stmt = count_stmt.where(FactoryAuditEvent.event_kind == event_kind)
    if team_context_key:
        stmt = stmt.where(FactoryAuditEvent.team_context_key == team_context_key)
        count_stmt = count_stmt.where(FactoryAuditEvent.team_context_key == team_context_key)
    if scope_context_key:
        stmt = stmt.where(FactoryAuditEvent.scope_context_key == scope_context_key)
        count_stmt = count_stmt.where(FactoryAuditEvent.scope_context_key == scope_context_key)
    if item_context_key:
        stmt = stmt.where(FactoryAuditEvent.item_context_key == item_context_key)
        count_stmt = count_stmt.where(FactoryAuditEvent.item_context_key == item_context_key)
    total = int((await db.execute(count_stmt)).scalar_one_or_none() or 0)
    rows = (await db.execute(
        stmt.order_by(FactoryAuditEvent.occurred_at.desc(), FactoryAuditEvent.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    items = []
    labels: set[str] = set()
    for row in rows:
        if row.context_snapshot:
            labels.update(str(key) for key in row.context_snapshot.keys())
        items.append(FactoryAuditEventRead(
            id=row.id, occurred_at=row.occurred_at, recorded_at=row.recorded_at,
            event_kind=row.event_kind, source=row.source, record_kind=row.record_kind,
            fact_source=row.fact_source, fact_time=row.fact_time,
            actor_kind=row.actor_kind, actor_reference=row.actor_reference,
            team_preset_id=row.team_preset_id, team_slot_id=row.team_slot_id,
            scope_id=row.scope_id, item_id=row.item_id, revision_id=row.revision_id,
            request_id=row.request_id,
            team_context_key=row.team_context_key, scope_context_key=row.scope_context_key,
            item_context_key=row.item_context_key, context_snapshot=row.context_snapshot,
            correlation_id=row.correlation_id, sanitized_reason=row.sanitized_reason,
            before_values=row.before_values, after_values=row.after_values,
            action_outcome=row.action_outcome, delivery_outcome=row.delivery_outcome,
            completion_kind=row.completion_kind, human_review_evidence=row.human_review_evidence,
            live_links_available=any(value is not None for value in (
                row.team_preset_id, row.scope_id, row.item_id, row.revision_id)),
        ))
    return FactoryAuditEventPage(
        items=items, total=total, page=page, page_size=page_size,
        team_context_key=team_context_key, scope_context_key=scope_context_key,
        event_kind=event_kind, snapshot_labels=sorted(labels))


@router.post("/review-acceptances", status_code=201)
async def declare_review_acceptance(
    declaration: FactoryReviewAcceptanceDeclaration,
    _operator: None = Depends(require_operator),
    db=Depends(get_db),
):
    """A32: record one trusted review acceptance declaration.

    Operator-protected and observational. The operator credential
    authenticates the recording action only; the declared reviewer stays a
    separate field. The route never changes work state, approvals, merges,
    retries, leases or counters. A binding refusal or replay conflict is
    recorded as one rejected observation and returns 409.
    """
    from app.models.schemas import FactoryReviewAcceptanceRead
    from app.services import factory_audit_service as audit

    operation_id = f"review_acceptance:{declaration.declaration_id}"
    recording_actor = audit.derive_actor(actor_kind="operator")
    replay = (await db.execute(text(
        "SELECT id FROM factory_audit_events WHERE operation_id = :op"
        " AND event_kind = 'review_acceptance_declared' LIMIT 1"),
        {"op": operation_id})).first()
    try:
        event, counted, delivered = await audit.record_review_acceptance(
            db, declaration, recording_actor=recording_actor)
        await db.commit()
    except (audit.ReviewDeclarationRefused, audit.ReplayConflictError) as exc:
        refusal = exc.code if isinstance(exc, audit.ReviewDeclarationRefused) else "replay_conflict"
        await db.rollback()
        await audit.record_observation(
            db, event_kind="review_acceptance_declared", source="operator_declaration",
            occurred_at=datetime.utcnow(), actor=recording_actor,
            action_outcome="rejected",
            item_id=None if refusal == "work_item_not_found" else declaration.work_item_id,
            correlation_id=operation_id, sanitized_reason=f"declaration refused: {refusal}")
        return JSONResponse(status_code=409, content=FactoryReviewAcceptanceRead(
            operation_id=operation_id, refusal=refusal).model_dump())
    body = FactoryReviewAcceptanceRead(
        event_id=event.id, operation_id=operation_id, counted=counted,
        delivery_established=delivered)
    if replay is not None:
        return JSONResponse(status_code=200, content=body.model_dump())
    return body


@router.get("/metrics")
async def get_factory_metrics(
    window_start: datetime,
    window_end: datetime,
    filter_scope: str = "all",
    team_context_key: str | None = None,
    scope_context_key: str | None = None,
    db=Depends(get_db),
):
    """A23-A38: safe aggregates with window, scope, unit, samples and
    coverage. Ordinary factory read: no protected details, no fresh GitHub
    fetches and no writes.
    """
    from app.services import factory_metrics_service as _metrics
    return await _metrics.build_metrics_window(
        db,
        window_start=window_start,
        window_end=window_end,
        filter_scope=filter_scope,
        team_context_key=team_context_key,
        scope_context_key=scope_context_key,
    )
