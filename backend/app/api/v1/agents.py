"""API endpoints for agent and skill management."""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import (
    Agent,
    AgentCreate,
    AgentListResponse,
    AgentUpdate,
    Skill,
    SkillListResponse,
)
from app.services.agent_service import AgentService

router = APIRouter(prefix="/agents", tags=["Agents"])


@router.get("", response_model=AgentListResponse)
async def list_agents(
    project_path: Optional[str] = Query(None, description="Project path")
):
    """
    List all agents from user and project scopes.

    Args:
        project_path: Optional project directory path

    Returns:
        List of all agents
    """
    agents = AgentService.list_agents(project_path)
    return AgentListResponse(agents=agents)


@router.get("/skills", response_model=SkillListResponse)
async def list_skills(
    project_path: Optional[str] = Query(None, description="Project path")
):
    """
    List all skills from user, project, and plugin directories.

    Args:
        project_path: Optional project directory path

    Returns:
        List of all skills
    """
    skills = AgentService.list_skills(project_path)
    return SkillListResponse(skills=skills)


@router.get("/skills/{location}/{name}", response_model=Skill)
async def get_skill(
    location: str,
    name: str,
    project_path: Optional[str] = Query(None, description="Project path")
):
    """
    Get a specific skill by location and name with full content.

    Args:
        location: Skill location ("user", "project", or "plugin:pluginname")
        name: Skill name
        project_path: Optional project directory path

    Returns:
        Skill definition with full content
    """
    skill = AgentService.get_skill(name, location, project_path)
    if not skill:
        raise HTTPException(
            status_code=404,
            detail=f"Skill '{name}' not found in location '{location}'"
        )
    return skill


@router.get("/{scope}/{name}", response_model=Agent)
async def get_agent(
    scope: str,
    name: str,
    project_path: Optional[str] = Query(None, description="Project path")
):
    """
    Get a specific agent by scope and name.

    Args:
        scope: Agent scope (user or project)
        name: Agent name (without .md extension)
        project_path: Optional project directory path (required for project scope)

    Returns:
        Agent definition
    """
    # Validate scope
    if scope not in ["user", "project"]:
        raise HTTPException(
            status_code=400,
            detail="Scope must be 'user' or 'project'"
        )

    agent = AgentService.get_agent(scope, name, project_path)
    if not agent:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{name}' not found in {scope} scope"
        )
    return agent


@router.post("", response_model=Agent, status_code=201)
async def create_agent(
    agent: AgentCreate,
    project_path: Optional[str] = Query(None, description="Project path")
):
    """
    Create a new agent.

    Args:
        agent: Agent creation data
        project_path: Optional project directory path (required for project scope)

    Returns:
        Created agent
    """
    # Validate scope
    if agent.scope not in ["user", "project"]:
        raise HTTPException(
            status_code=400,
            detail="Scope must be 'user' or 'project'"
        )

    # Validate project path for project scope
    if agent.scope == "project" and not project_path:
        raise HTTPException(
            status_code=400,
            detail="project_path is required for project-scoped agents"
        )

    try:
        created_agent = AgentService.create_agent(agent, project_path)
        return created_agent
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create agent: {str(e)}"
        )


@router.put("/{scope}/{name}", response_model=Agent)
async def update_agent(
    scope: str,
    name: str,
    agent_update: AgentUpdate,
    project_path: Optional[str] = Query(None, description="Project path")
):
    """
    Update an existing agent.

    Args:
        scope: Agent scope (user or project)
        name: Agent name (without .md extension)
        agent_update: Agent update data
        project_path: Optional project directory path (required for project scope)

    Returns:
        Updated agent
    """
    # Validate scope
    if scope not in ["user", "project"]:
        raise HTTPException(
            status_code=400,
            detail="Scope must be 'user' or 'project'"
        )

    try:
        updated_agent = AgentService.update_agent(scope, name, agent_update, project_path)

        if not updated_agent:
            raise HTTPException(
                status_code=404,
                detail=f"Agent '{name}' not found in {scope} scope"
            )

        return updated_agent
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update agent: {str(e)}"
        )


@router.delete("/{scope}/{name}", status_code=204)
async def delete_agent(
    scope: str,
    name: str,
    project_path: Optional[str] = Query(None, description="Project path")
):
    """
    Delete an agent.

    Args:
        scope: Agent scope (user or project)
        name: Agent name (without .md extension)
        project_path: Optional project directory path (required for project scope)

    Returns:
        204 No Content on success
    """
    # Validate scope
    if scope not in ["user", "project"]:
        raise HTTPException(
            status_code=400,
            detail="Scope must be 'user' or 'project'"
        )

    try:
        deleted = AgentService.delete_agent(scope, name, project_path)

        if not deleted:
            raise HTTPException(
                status_code=404,
                detail=f"Agent '{name}' not found in {scope} scope"
            )

        return None
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete agent: {str(e)}"
        )
