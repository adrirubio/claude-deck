"""Provider registry API."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.services.providers import get_provider, get_providers

router = APIRouter()


@router.get("/providers")
def list_providers():
    providers = [provider.get_status() for provider in get_providers()]
    return {"providers": providers, "count": len(providers)}


@router.get("/providers/{provider_id}/status")
def get_provider_status(provider_id: str):
    try:
        return get_provider(provider_id).get_status()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

