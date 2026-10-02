"""Local observational delivery reads; legacy protected remedies stay separate."""
from fastapi import APIRouter, Depends, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import factory_schemas as wire
from app.services import factory_projection_service as projections


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
            except Exception:
                # Neither DB exceptions nor failed observations are empty data.
                # Do not serialize private query parameters or diagnostics.
                error = projections.FactoryReadError("projection_failed", 500)
            return JSONResponse(status_code=error.status,
                                content={"detail": {"code": error.code, "message": str(error)}})

        return handle


router = APIRouter(route_class=FactoryReadRoute)


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
