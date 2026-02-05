"""API endpoints for memory management (CLAUDE.md, rules, etc.)."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.memory_service import MemoryService

router = APIRouter(prefix="/memory", tags=["Memory"])


# Request/Response schemas
class MemoryFileResponse(BaseModel):
    """Response for a memory file."""

    path: str
    exists: bool
    content: Optional[str] = None
    imports: List[str] = []
    frontmatter: Dict[str, Any] = {}
    error: Optional[str] = None


class MemoryHierarchyItem(BaseModel):
    """Item in the memory hierarchy."""

    path: str
    scope: str
    type: str
    exists: bool
    readonly: bool
    description: str
    name: Optional[str] = None
    relative_path: Optional[str] = None


class MemoryHierarchyResponse(BaseModel):
    """Response for memory hierarchy."""

    files: List[MemoryHierarchyItem]


class RuleInfo(BaseModel):
    """Info about a rule file."""

    name: str
    path: str
    relative_path: str
    frontmatter: Dict[str, Any] = {}
    scoped_paths: List[str] = []
    description: str = ""
    content_preview: str = ""


class RulesListResponse(BaseModel):
    """Response for rules list."""

    rules: List[RuleInfo]
    rules_dir: str


class SaveMemoryRequest(BaseModel):
    """Request to save a memory file."""

    content: str


class SaveMemoryResponse(BaseModel):
    """Response for save operation."""

    success: bool
    path: str
    error: Optional[str] = None


class CreateRuleRequest(BaseModel):
    """Request to create a new rule."""

    name: str
    content: str
    paths: Optional[List[str]] = None
    description: Optional[str] = None


class ImportTreeNode(BaseModel):
    """Node in the import tree."""

    path: str
    exists: bool
    cycle: bool = False
    imports: List["ImportTreeNode"] = []
    error: Optional[str] = None


# Make the self-reference work
ImportTreeNode.model_rebuild()


class ImportTreeResponse(BaseModel):
    """Response for import tree resolution."""

    tree: ImportTreeNode


# Endpoints


@router.get("/hierarchy", response_model=MemoryHierarchyResponse)
async def get_memory_hierarchy(
    project_path: Optional[str] = Query(None, description="Project path"),
):
    """
    Get the memory file hierarchy.

    Returns all memory files (CLAUDE.md, rules) with their locations,
    scopes, and existence status.
    """
    files = MemoryService.get_memory_hierarchy(project_path)
    return MemoryHierarchyResponse(files=files)


@router.get("/file", response_model=MemoryFileResponse)
async def get_memory_file(
    file_path: str = Query(..., description="Absolute path to the memory file"),
    include_imports: bool = Query(True, description="Extract import references"),
):
    """
    Get a specific memory file with content and metadata.
    """
    result = MemoryService.get_memory_file(file_path, include_imports)
    return MemoryFileResponse(**result)


@router.put("/file", response_model=SaveMemoryResponse)
async def save_memory_file(
    file_path: str = Query(..., description="Absolute path to the memory file"),
    request: SaveMemoryRequest = ...,
):
    """
    Save content to a memory file.

    Creates the file and parent directories if they don't exist.
    Cannot modify the managed policy file (/etc/claude-code/CLAUDE.md).
    """
    result = MemoryService.save_memory_file(file_path, request.content)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Save failed"))

    return SaveMemoryResponse(**result)


@router.delete("/file", response_model=SaveMemoryResponse)
async def delete_memory_file(
    file_path: str = Query(..., description="Absolute path to the memory file"),
):
    """
    Delete a memory file.

    Cannot delete the managed policy file.
    """
    result = MemoryService.delete_memory_file(file_path)

    if not result["success"]:
        raise HTTPException(
            status_code=400, detail=result.get("error", "Delete failed")
        )

    return SaveMemoryResponse(**result)


@router.get("/rules", response_model=RulesListResponse)
async def list_rules(
    project_path: Optional[str] = Query(None, description="Project path"),
):
    """
    List all rules in the .claude/rules/ directory.
    """
    from app.utils.path_utils import get_project_claude_dir

    rules = MemoryService.list_rules(project_path)
    rules_dir = get_project_claude_dir(project_path) / "rules"

    return RulesListResponse(rules=rules, rules_dir=str(rules_dir))


@router.post("/rules", response_model=SaveMemoryResponse)
async def create_rule(
    project_path: Optional[str] = Query(None, description="Project path"),
    request: CreateRuleRequest = ...,
):
    """
    Create a new rule file in .claude/rules/.
    """
    result = MemoryService.create_rule(
        project_path=project_path,
        name=request.name,
        content=request.content,
        paths=request.paths,
        description=request.description,
    )

    if not result["success"]:
        raise HTTPException(
            status_code=400, detail=result.get("error", "Create failed")
        )

    return SaveMemoryResponse(**result)


@router.get("/imports", response_model=ImportTreeResponse)
async def resolve_imports(
    file_path: str = Query(..., description="Path to the memory file"),
):
    """
    Resolve the import tree for a memory file.

    Returns the full tree of @import references with cycle detection.
    """
    tree = MemoryService.resolve_imports(file_path)
    return ImportTreeResponse(tree=ImportTreeNode(**tree))
