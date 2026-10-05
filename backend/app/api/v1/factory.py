"""Local observational delivery reads; legacy protected remedies stay separate."""
import asyncio
import subprocess
from datetime import datetime
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
from app.models.schemas import SetupPreflightRequest, SetupPreflightResponse, SetupPreflightCheck
from app.services.github_client import github_client
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


@router.post("/setup-preflight", response_model=SetupPreflightResponse)
async def setup_preflight(
    request: SetupPreflightRequest,
    _operator: None = Depends(require_operator),
):
    """Observe setup prerequisites. This route never creates or changes records."""
    checked_at = datetime.utcnow()
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
        except asyncio.TimeoutError:
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
            if exc.response.status_code in (403, 404):
                return SetupPreflightCheck(status="blocked", code="base_branch_not_readable")
            return SetupPreflightCheck(status="unknown", code="base_branch_check_failed")
        except Exception:
            return SetupPreflightCheck(status="unknown", code="base_branch_check_failed")

    async def labels_check() -> SetupPreflightCheck:
        try:
            labels = await asyncio.wait_for(
                github_client.list_repo_labels(request.repo_owner, request.repo_name), timeout=5.0
            )
        except asyncio.TimeoutError:
            return SetupPreflightCheck(status="unknown", code="label_check_timeout")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (403, 404):
                return SetupPreflightCheck(status="blocked", code="labels_not_readable")
            return SetupPreflightCheck(status="unknown", code="label_check_failed")
        except Exception:
            return SetupPreflightCheck(status="unknown", code="label_check_failed")
        missing = [label for label in (request.dispatch_label, request.design_label) if label not in labels]
        return SetupPreflightCheck(
            status="blocked" if missing else "ready",
            code="selected_labels_missing" if missing else "selected_labels_exist",
        )

    if request.dispatch_auth_mode == "token":
        dispatch_auth = SetupPreflightCheck(
            status="ready" if settings.github_token else "blocked",
            code="dispatch_token_configured" if settings.github_token else "dispatch_token_missing",
        )
    else:
        app_ready = bool(settings.github_app_id and settings.github_app_private_key_path
                         and settings.github_app_bot_login
                         and Path(settings.github_app_private_key_path).is_file())
        dispatch_auth = SetupPreflightCheck(
            status="ready" if app_ready else "blocked",
            code="github_app_configuration_present" if app_ready else "github_app_configuration_missing",
        )

    repository_status = await repository_check()
    checks = {
        "checkout_identity": await checkout_check(),
        "polling_credential": SetupPreflightCheck(
            status="ready" if settings.github_token else "blocked",
            code="polling_credential_configured" if settings.github_token else "polling_credential_missing",
        ),
        "repository_read": repository_status,
        "labels": await labels_check(),
        "base_branch": await base_branch_check(),
        "dispatch_auth": dispatch_auth,
    }
    if all(check.status == "ready" for check in checks.values()):
        status = "ready"
    elif any(check.status == "blocked" for check in checks.values()):
        status = "blocked"
    else:
        status = "unknown"
    return SetupPreflightResponse(status=status, checked_at=checked_at, checks=checks)


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
