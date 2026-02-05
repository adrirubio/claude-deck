"""Pydantic schemas for API models."""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class ConfigFile(BaseModel):
    """Represents a configuration file."""

    path: str
    scope: str  # "user" or "project"
    exists: bool
    content: Optional[Dict[str, Any]] = None


class ConfigFileListResponse(BaseModel):
    """List of configuration files."""

    files: List[ConfigFile]


class MergedConfig(BaseModel):
    """Merged configuration from all scopes."""

    settings: Dict[str, Any]
    mcp_servers: Dict[str, Any]
    hooks: Dict[str, List[Any]]
    permissions: Dict[str, List[str]]
    commands: List[str]
    agents: List[str]


class RawFileContent(BaseModel):
    """Raw file content."""

    path: str
    content: str
    exists: bool


# Project Management Schemas


class ProjectBase(BaseModel):
    """Base project schema."""

    name: str
    path: str


class ProjectCreate(ProjectBase):
    """Schema for creating a new project."""

    pass


class ProjectUpdate(BaseModel):
    """Schema for updating a project."""

    name: Optional[str] = None
    is_active: Optional[bool] = None


class ProjectResponse(ProjectBase):
    """Schema for project response."""

    id: int
    is_active: bool
    last_accessed: str
    created_at: str

    class Config:
        from_attributes = True


class ProjectListResponse(BaseModel):
    """List of projects."""

    projects: List[ProjectResponse]


class ProjectDiscoveryRequest(BaseModel):
    """Schema for project discovery request."""

    base_path: str


class ProjectDiscoveryResponse(BaseModel):
    """Schema for project discovery response."""

    discovered: List[ProjectBase]


class SetActiveProjectRequest(BaseModel):
    """Schema for setting active project."""

    project_id: int


# CLI Execution Schemas


class CLIExecuteRequest(BaseModel):
    """Schema for CLI execution request."""

    command: str
    args: List[str] = []


class CLIResult(BaseModel):
    """Schema for CLI execution result."""

    stdout: str
    stderr: str
    exit_code: int


# MCP Server Schemas


class MCPServer(BaseModel):
    """MCP Server configuration."""

    name: str
    type: str  # "stdio" or "http"
    scope: str  # "user" or "project"
    command: Optional[str] = None  # For stdio type
    args: Optional[List[str]] = None  # For stdio type
    url: Optional[str] = None  # For http type
    headers: Optional[Dict[str, str]] = None  # For http type
    env: Optional[Dict[str, str]] = None  # Environment variables
    # Cache fields
    is_connected: Optional[bool] = None
    last_tested_at: Optional[str] = None
    last_error: Optional[str] = None
    mcp_server_name: Optional[str] = None
    mcp_server_version: Optional[str] = None
    tools: Optional[List["MCPTool"]] = None
    tool_count: Optional[int] = None


class MCPServerCreate(BaseModel):
    """Schema for creating an MCP server."""

    name: str
    type: str  # "stdio" or "http"
    scope: str  # "user" or "project"
    command: Optional[str] = None
    args: Optional[List[str]] = None
    url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    env: Optional[Dict[str, str]] = None


class MCPServerUpdate(BaseModel):
    """Schema for updating an MCP server."""

    type: Optional[str] = None
    command: Optional[str] = None
    args: Optional[List[str]] = None
    url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    env: Optional[Dict[str, str]] = None


class MCPServerListResponse(BaseModel):
    """List of MCP servers."""

    servers: List[MCPServer]


class MCPTestConnectionRequest(BaseModel):
    """Schema for testing MCP server connection."""

    name: str
    scope: str


class MCPTool(BaseModel):
    """MCP tool information."""

    name: str
    description: Optional[str] = None
    inputSchema: Optional[Dict[str, Any]] = None


class MCPTestConnectionResponse(BaseModel):
    """Response from testing MCP server connection."""

    success: bool
    message: str
    server_name: Optional[str] = None
    server_version: Optional[str] = None
    tools: Optional[List[MCPTool]] = None


# Slash Command Schemas


class SlashCommand(BaseModel):
    """Slash command configuration."""

    name: str
    path: str  # File path relative to commands directory
    scope: str  # "user" or "project"
    description: Optional[str] = None
    allowed_tools: Optional[List[str]] = None
    content: str  # Markdown content (without frontmatter)


class SlashCommandCreate(BaseModel):
    """Schema for creating a slash command."""

    name: str  # Can include namespace (e.g., "tools:analyze")
    scope: str  # "user" or "project"
    description: Optional[str] = None
    allowed_tools: Optional[List[str]] = None
    content: str


class SlashCommandUpdate(BaseModel):
    """Schema for updating a slash command."""

    description: Optional[str] = None
    allowed_tools: Optional[List[str]] = None
    content: Optional[str] = None


class SlashCommandListResponse(BaseModel):
    """List of slash commands."""

    commands: List[SlashCommand]


# Plugin Schemas


class PluginComponent(BaseModel):
    """Plugin component (command, agent, hook, or MCP server)."""

    type: str  # "command", "agent", "hook", "mcp"
    name: str


class Plugin(BaseModel):
    """Installed plugin configuration."""

    name: str
    version: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    category: Optional[str] = None
    source: Optional[str] = None  # e.g., "anthropic-agent-skills", "claude-plugins-official", "local"
    enabled: bool = True
    components: List[PluginComponent] = []
    # Extended information for plugin details
    usage: Optional[str] = None  # Usage instructions
    examples: Optional[List[str]] = None  # Example use cases
    readme: Optional[str] = None  # README content (for local plugins)


class PluginListResponse(BaseModel):
    """List of installed plugins."""

    plugins: List[Plugin]


class MarketplacePlugin(BaseModel):
    """Plugin available in a marketplace."""

    name: str
    description: Optional[str] = None
    version: Optional[str] = None
    install_command: str


class MarketplacePluginListResponse(BaseModel):
    """List of plugins in a marketplace."""

    plugins: List[MarketplacePlugin]


class MarketplaceCreate(BaseModel):
    """Schema for adding a marketplace.

    Supports two input modes:
    1. Direct: Provide name and url directly
    2. Smart: Provide input field with "owner/repo" or full URL
    """

    name: Optional[str] = None  # Optional - derived from input if not provided
    url: Optional[str] = None   # Optional - derived from input if not provided
    input: Optional[str] = None  # Accepts "owner/repo" or full URL


class MarketplaceResponse(BaseModel):
    """Marketplace configuration from Claude's known_marketplaces.json."""

    name: str
    repo: str
    install_location: str
    last_updated: Optional[str] = None
    plugin_count: int = 0


class MarketplaceListResponse(BaseModel):
    """List of configured marketplaces."""

    marketplaces: List[MarketplaceResponse]


class PluginInstallRequest(BaseModel):
    """Schema for installing a plugin."""

    name: str
    marketplace_name: Optional[str] = None


class PluginInstallResponse(BaseModel):
    """Response from plugin installation."""

    success: bool
    message: str
    stdout: Optional[str] = None
    stderr: Optional[str] = None


class PluginToggleRequest(BaseModel):
    """Schema for toggling a plugin's enabled state."""

    enabled: bool
    source: Optional[str] = None


class PluginToggleResponse(BaseModel):
    """Response from toggling a plugin."""

    success: bool
    message: str
    plugin: Optional["Plugin"] = None


# Hook Schemas


class Hook(BaseModel):
    """Hook configuration."""

    id: str
    event: str  # PreToolUse, PostToolUse, PermissionRequest, Stop, SubagentStop, Notification, UserPromptSubmit, SessionStart, PreCompact
    matcher: Optional[str] = None  # Tool matcher pattern (e.g., "Write(*.py)")
    type: str  # "command" or "prompt"
    command: Optional[str] = None  # Shell command to execute
    prompt: Optional[str] = None  # Prompt to append
    timeout: Optional[int] = None  # Timeout in seconds
    scope: str  # "user" or "project"


class HookCreate(BaseModel):
    """Schema for creating a hook."""

    event: str
    matcher: Optional[str] = None
    type: str  # "command" or "prompt"
    command: Optional[str] = None
    prompt: Optional[str] = None
    timeout: Optional[int] = None
    scope: str  # "user" or "project"


class HookUpdate(BaseModel):
    """Schema for updating a hook."""

    event: Optional[str] = None
    matcher: Optional[str] = None
    type: Optional[str] = None
    command: Optional[str] = None
    prompt: Optional[str] = None
    timeout: Optional[int] = None


class HookListResponse(BaseModel):
    """List of hooks."""

    hooks: List[Hook]


# Permission Schemas


class PermissionRule(BaseModel):
    """Permission rule configuration."""

    id: str
    type: str  # "allow" or "deny"
    pattern: str  # Tool(pattern) or Tool:subcommand
    scope: str  # "user" or "project"


class PermissionRuleCreate(BaseModel):
    """Schema for creating a permission rule."""

    type: str  # "allow" or "deny"
    pattern: str  # Tool(pattern) or Tool:subcommand
    scope: str  # "user" or "project"


class PermissionRuleUpdate(BaseModel):
    """Schema for updating a permission rule."""

    type: Optional[str] = None
    pattern: Optional[str] = None


class PermissionListResponse(BaseModel):
    """List of permission rules."""

    rules: List[PermissionRule]


# Agent and Skill Schemas


class Agent(BaseModel):
    """Agent configuration."""

    name: str
    scope: str  # "user" or "project"
    description: Optional[str] = None
    tools: Optional[List[str]] = None
    model: Optional[str] = None
    prompt: str  # Full prompt content


class AgentCreate(BaseModel):
    """Schema for creating an agent."""

    name: str
    scope: str  # "user" or "project"
    description: Optional[str] = None
    tools: Optional[List[str]] = None
    model: Optional[str] = None
    prompt: str


class AgentUpdate(BaseModel):
    """Schema for updating an agent."""

    description: Optional[str] = None
    tools: Optional[List[str]] = None
    model: Optional[str] = None
    prompt: Optional[str] = None


class AgentListResponse(BaseModel):
    """List of agents."""

    agents: List[Agent]


class SkillDependency(BaseModel):
    """A single skill dependency."""

    kind: str  # "bin", "npm", "pip", "script"
    name: str  # Binary name, package name, or script path
    installed: bool = False  # Whether the dependency is currently satisfied
    version: Optional[str] = None  # Required version (if specified)
    installed_version: Optional[str] = None  # Currently installed version


class SkillDependencyStatus(BaseModel):
    """Dependency status report for a skill."""

    skill_name: str
    all_satisfied: bool
    dependencies: List[SkillDependency]
    has_install_script: bool = False
    install_script_path: Optional[str] = None


class SkillInstallResult(BaseModel):
    """Result of installing skill dependencies."""

    success: bool
    message: str
    installed: List[str] = []  # Successfully installed deps
    failed: List[str] = []  # Failed deps
    logs: str = ""  # Combined stdout/stderr


class SkillSupportingFile(BaseModel):
    """A supporting file in a skill directory."""

    name: str
    path: str
    size_bytes: int
    is_script: bool = False


class Skill(BaseModel):
    """Skill definition."""

    name: str
    description: Optional[str] = None
    location: str  # "user", "project", or plugin path
    content: Optional[str] = None  # Full markdown content (optional)
    # Dependency info (populated on detail view)
    dependency_status: Optional[SkillDependencyStatus] = None
    supporting_files: Optional[List[SkillSupportingFile]] = None


class SkillListResponse(BaseModel):
    """List of skills."""

    skills: List[Skill]


# Registry Skills (skills.sh)


class RegistrySkillResponse(BaseModel):
    """A skill from the skills.sh registry."""

    skill_id: str
    name: str
    source: str  # GitHub repo path (e.g. "vercel-labs/agent-skills")
    installs: int
    registry_id: str
    url: str  # skills.sh detail page URL
    github_url: str  # GitHub repo URL
    installed: bool = False  # Whether this skill is installed locally


class RegistrySearchResponse(BaseModel):
    """Response from registry search/browse."""

    skills: List[RegistrySkillResponse]
    total: int
    cached: bool = False


class RegistryInstallRequest(BaseModel):
    """Request to install a skill from the registry."""

    source: str  # GitHub repo path
    skill_names: Optional[List[str]] = None  # Specific skills to install (None = all)
    global_install: bool = True  # User-level vs project-level


class RegistryInstallResponse(BaseModel):
    """Response from registry install."""

    success: bool
    message: str
    logs: str
    source: str
    skill_names: Optional[List[str]] = None


# Backup Schemas


class BackupBase(BaseModel):
    """Base backup schema."""

    name: str
    description: Optional[str] = None
    scope: str  # "full", "user", "project"


class BackupCreate(BackupBase):
    """Schema for creating a backup."""

    project_path: Optional[str] = None  # Required for project/full scope
    project_id: Optional[int] = None


class BackupResponse(BackupBase):
    """Schema for backup response."""

    id: int
    file_path: str
    project_id: Optional[int] = None
    created_at: str
    size_bytes: int

    class Config:
        from_attributes = True


class BackupListResponse(BaseModel):
    """List of backups."""

    backups: List[BackupResponse]


class BackupContentsResponse(BaseModel):
    """Backup contents response."""

    files: List[str]


class RestoreRequest(BaseModel):
    """Schema for restore request."""

    project_path: Optional[str] = None


class ExportRequest(BaseModel):
    """Schema for export request."""

    paths: List[str]
    name: Optional[str] = "export"


class ExportResponse(BaseModel):
    """Schema for export response."""

    file_path: str
    size_bytes: int


# Output Style Schemas


class OutputStyle(BaseModel):
    """Output style configuration."""

    name: str
    scope: str  # "user" or "project"
    description: Optional[str] = None
    keep_coding_instructions: bool = False
    content: str  # Markdown instructions


class OutputStyleCreate(BaseModel):
    """Schema for creating an output style."""

    name: str
    scope: str  # "user" or "project"
    description: Optional[str] = None
    keep_coding_instructions: bool = False
    content: str


class OutputStyleUpdate(BaseModel):
    """Schema for updating an output style."""

    description: Optional[str] = None
    keep_coding_instructions: Optional[bool] = None
    content: Optional[str] = None


class OutputStyleListResponse(BaseModel):
    """List of output styles."""

    output_styles: List[OutputStyle]


# Status Line Schemas


class StatusLineConfig(BaseModel):
    """Status line configuration."""

    type: str = "command"  # Currently only "command" is supported
    command: Optional[str] = None  # Path to script
    padding: Optional[int] = None  # Optional padding (0 = edge)
    enabled: bool = True
    script_content: Optional[str] = None  # Current script file content


class StatusLineUpdate(BaseModel):
    """Schema for updating status line config."""

    type: Optional[str] = None
    command: Optional[str] = None
    padding: Optional[int] = None
    enabled: Optional[bool] = None


class StatusLinePreset(BaseModel):
    """Preset status line script."""

    id: str
    name: str
    description: str
    script: str


class StatusLinePresetsResponse(BaseModel):
    """List of available presets."""

    presets: List[StatusLinePreset]


class StatusLineApplyPresetRequest(BaseModel):
    """Request to apply a preset."""

    preset_id: str


class PowerlinePreset(BaseModel):
    """Powerline theme preset (uses npx command)."""

    id: str
    name: str
    description: str
    theme: str
    style: str
    command: str


class PowerlinePresetsResponse(BaseModel):
    """List of available powerline presets."""

    presets: List[PowerlinePreset]


class NodejsCheckResponse(BaseModel):
    """Response from Node.js availability check."""

    available: bool
    version: Optional[str] = None


# Session Transcript Schemas


class ContentBlock(BaseModel):
    """A content block within a message."""

    type: str  # "text", "thinking", "tool_use", "tool_result", "image"
    text: Optional[str] = None
    thinking: Optional[str] = None
    name: Optional[str] = None  # tool name for tool_use
    id: Optional[str] = None
    input: Optional[Dict[str, Any]] = None
    content: Optional[Any] = None  # tool_result content
    is_error: Optional[bool] = None
    source: Optional[Dict[str, str]] = None  # for images


class SessionMessage(BaseModel):
    """A message in a conversation (user or assistant)."""

    type: str  # "user" or "assistant"
    timestamp: str
    content: List[ContentBlock]
    model: Optional[str] = None  # Model used for this message
    usage: Optional[Dict[str, Any]] = None  # Token usage (can have nested structures)


class SessionConversation(BaseModel):
    """A conversation (user prompt + assistant responses)."""

    user_text: str  # Preview text from user prompt
    timestamp: str
    messages: List[SessionMessage]
    is_continuation: bool = False
    token_count: Optional[int] = None


class SessionSummary(BaseModel):
    """Session metadata for list view."""

    id: str
    project_folder: str
    project_name: str
    summary: str
    modified_at: str
    size_bytes: int
    total_messages: int
    total_tool_calls: int


class SessionDetail(BaseModel):
    """Full session data with conversations."""

    id: str
    project_folder: str
    project_name: str
    conversations: List[SessionConversation]
    total_messages: int
    total_tool_calls: int
    total_tokens: Optional[int] = None
    models_used: List[str] = []


class SessionProject(BaseModel):
    """Project grouping with session count."""

    folder: str
    name: str
    session_count: int
    most_recent: str


class SessionListResponse(BaseModel):
    """List of session summaries."""

    sessions: List[SessionSummary]
    total: int


class SessionProjectListResponse(BaseModel):
    """List of projects with session counts."""

    projects: List[SessionProject]
    total_sessions: int


class SessionDetailResponse(BaseModel):
    """Full session detail with pagination."""

    session: SessionDetail
    current_page: int
    total_pages: int
    prompts_per_page: int = 5


class SessionStatsResponse(BaseModel):
    """Dashboard session statistics."""

    total_sessions: int
    sessions_today: int
    sessions_this_week: int
    most_active_project: Optional[str] = None
    total_messages: int


# Usage Tracking Schemas


class TokenCounts(BaseModel):
    """Token counts by type."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0


class ModelBreakdown(BaseModel):
    """Model-specific usage breakdown."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost: float = 0.0


class DailyUsage(BaseModel):
    """Daily usage aggregation."""

    date: str  # YYYY-MM-DD
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    total_cost: float
    models_used: List[str]
    model_breakdowns: List[ModelBreakdown]
    project: Optional[str] = None


class SessionUsage(BaseModel):
    """Session-based usage aggregation."""

    session_id: str
    project_path: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    total_cost: float
    last_activity: str  # YYYY-MM-DD
    versions: List[str]
    models_used: List[str]
    model_breakdowns: List[ModelBreakdown]


class MonthlyUsage(BaseModel):
    """Monthly usage aggregation."""

    month: str  # YYYY-MM
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    total_cost: float
    models_used: List[str]
    model_breakdowns: List[ModelBreakdown]
    project: Optional[str] = None


class SessionBlock(BaseModel):
    """5-hour billing block usage."""

    id: str  # ISO timestamp of block start
    start_time: str  # ISO timestamp
    end_time: str  # ISO timestamp (start + 5 hours)
    actual_end_time: Optional[str] = None  # Last activity in block
    is_active: bool
    is_gap: bool = False
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    cost_usd: float
    models: List[str]
    # Projections for active blocks
    burn_rate_tokens_per_minute: Optional[float] = None
    burn_rate_cost_per_hour: Optional[float] = None
    projected_total_tokens: Optional[int] = None
    projected_total_cost: Optional[float] = None
    remaining_minutes: Optional[int] = None


class UsageSummary(BaseModel):
    """Overall usage statistics."""

    total_cost: float
    total_input_tokens: int
    total_output_tokens: int
    total_cache_creation_tokens: int
    total_cache_read_tokens: int
    total_tokens: int
    project_count: int
    session_count: int
    models_used: List[str]
    date_range_start: Optional[str] = None
    date_range_end: Optional[str] = None


class DailyUsageListResponse(BaseModel):
    """List of daily usage data."""

    data: List[DailyUsage]
    totals: TokenCounts
    total_cost: float


class SessionUsageListResponse(BaseModel):
    """List of session usage data."""

    data: List[SessionUsage]
    totals: TokenCounts
    total_cost: float
    total: int


class MonthlyUsageListResponse(BaseModel):
    """List of monthly usage data."""

    data: List[MonthlyUsage]
    totals: TokenCounts
    total_cost: float


class BlockUsageListResponse(BaseModel):
    """List of billing block usage data."""

    data: List[SessionBlock]
    active_block: Optional[SessionBlock] = None
    totals: TokenCounts
    total_cost: float


class UsageSummaryResponse(BaseModel):
    """Usage summary response."""

    summary: UsageSummary
