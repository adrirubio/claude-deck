"""Codex configuration API."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.services.codex_config_service import CodexConfigService

router = APIRouter()


@router.get("/codex-config")
def get_codex_config():
    return CodexConfigService().get_config()


@router.get("/codex-config/files")
def list_codex_config_files():
    service = CodexConfigService()
    files = service.get_all_config_files()
    return {"files": files, "count": len(files)}


@router.get("/codex-config/file")
def get_codex_config_file(path: str):
    try:
        return CodexConfigService().get_file_content(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

