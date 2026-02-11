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
    permissions: Dict[str, Any]
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
    type: str  # "stdio", "http", or "sse"
    scope: str  # "user", "project", "plugin", or "managed"
    source: Optional[str] = None  # Original source for display (e.g., plugin name)
    disabled: Optional[bool] = None  # Whether server is disabled
    command: Optional[str] = None  # For stdio type
    args: Optional[List[str]] = None  # For stdio type
    url: Optional[str] = None  # For http/sse type
    headers: Optional[Dict[str, str]] = None  # For http/sse type
    env: Optional[Dict[str, str]] = None  # Environment variables
    # Cache fields
    is_connected: Optional[bool] = None
    last_tested_at: Optional[str] = None
    last_error: Optional[str] = None
    mcp_server_name: Optional[str] = None
    mcp_server_version: Optional[str] = None
    tools: Optional[List["MCPTool"]] = None
    tool_count: Optional[int] = None
    resources: Optional[List["MCPResource"]] = None
    prompts: Optional[List["MCPPrompt"]] = None
    resource_count: Optional[int] = None
    prompt_count: Optional[int] = None
    capabilities: Optional[Dict[str, Any]] = None


class MCPServerCreate(BaseModel):
    """Schema for creating an MCP server."""

    name: str
    type: str  # "stdio", "http", or "sse"
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


# MCP Server Approval Settings Schemas


class MCPServerApprovalMode(BaseModel):
    """Server-level approval mode configuration."""

    server_name: str
    mode: str  # "always-allow", "always-deny", "ask-every-time"


class MCPServerApprovalSettings(BaseModel):
    """MCP server approval settings for automatic tool permissions."""

    default_mode: str = "ask-every-time"  # "always-allow", "always-deny", "ask-every-time"
    server_overrides: List[MCPServerApprovalMode] = []


class MCPServerApprovalSettingsUpdate(BaseModel):
    """Schema for updating MCP server approval settings."""

    default_mode: Optional[str] = None
    server_overrides: Optional[List[MCPServerApprovalMode]] = None


class MCPServerToggleRequest(BaseModel):
    """Schema for toggling an MCP server's disabled state."""

    disabled: bool


class MCPServerToggleResponse(BaseModel):
    """Response from toggling an MCP server."""

    success: bool
    message: str
    server_name: str
    disabled: bool


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


class MCPResource(BaseModel):
    """MCP resource information."""

    uri: str
    name: str
    description: Optional[str] = None
    mimeType: Optional[str] = None


class MCPPromptArgument(BaseModel):
    """MCP prompt argument."""

    name: str
    description: Optional[str] = None
    required: Optional[bool] = None


class MCPPrompt(BaseModel):
    """MCP prompt information."""

    name: str
    description: Optional[str] = None
    arguments: Optional[List[MCPPromptArgument]] = None


class MCPAuthStatus(BaseModel):
    """OAuth authentication status for an MCP server."""

    has_token: bool
    expired: bool
    server_url: Optional[str] = None
    has_client_registration: Optional[bool] = None


class MCPAuthStartResponse(BaseModel):
    """Response from starting an OAuth flow."""

    auth_url: str
    state: str


class MCPTestConnectionResponse(BaseModel):
    """Response from testing MCP server connection."""

    success: bool
    message: str
    server_name: Optional[str] = None
    server_version: Optional[str] = None
    tools: Optional[List[MCPTool]] = None
    resources: Optional[List[MCPResource]] = None
    prompts: Optional[List[MCPPrompt]] = None
    resource_count: Optional[int] = None
    prompt_count: Optional[int] = None
    capabilities: Optional[Dict[str, Any]] = None


class MCPTestAllResult(BaseModel):
    """Result for a single server from test-all."""

    server_name: str
    scope: str
    success: bool
    message: str
    tool_count: Optional[int] = None
    resource_count: Optional[int] = None
    prompt_count: Optional[int] = None


class MCPTestAllResponse(BaseModel):
    """Response from testing all MCP servers."""

    results: List[MCPTestAllResult]


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
    """Plugin component (command, agent, hook, mcp, lsp, or skill)."""

    type: str  # "command", "agent", "hook", "mcp", "lsp", "skill"
    name: str
    description: Optional[str] = None


class PluginHook(BaseModel):
    """Plugin-defined hook."""

    event: str  # PreToolUse, PostToolUse, etc.
    type: str = "command"  # "command", "prompt", "agent"
    matcher: Optional[str] = None
    command: Optional[str] = None
    prompt: Optional[str] = None


class PluginLSPConfig(BaseModel):
    """Plugin LSP server configuration."""

    name: str
    language: str
    command: str
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None


class Plugin(BaseModel):
    """Installed plugin configuration."""

    name: str
    version: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    category: Optional[str] = None
    source: Optional[str] = None  # e.g., "anthropic-agent-skills", "claude-plugins-official", "local"
    enabled: bool = True
    scope: Optional[str] = None  # "user", "project", "local"
    components: List[PluginComponent] = []
    # Component counts for quick display
    skill_count: int = 0
    agent_count: int = 0
    hook_count: int = 0
    mcp_count: int = 0
    lsp_count: int = 0
    # Extended information for plugin details
    usage: Optional[str] = None  # Usage instructions
    examples: Optional[List[str]] = None  # Example use cases
    readme: Optional[str] = None  # README content (for local plugins)
    # Plugin-defined hooks (read-only)
    hooks: Optional[List[PluginHook]] = None
    # LSP configurations
    lsp_configs: Optional[List[PluginLSPConfig]] = None


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
    auto_update: bool = False  # Per-marketplace auto-update setting


class MarketplaceListResponse(BaseModel):
    """List of configured marketplaces."""

    marketplaces: List[MarketplaceResponse]


class PluginInstallRequest(BaseModel):
    """Schema for installing a plugin."""

    name: str
    marketplace_name: Optional[str] = None
    scope: str = "user"  # "user", "project", "local"


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


# Plugin Update Schemas


class PluginUpdateInfo(BaseModel):
    """Information about a plugin update."""

    name: str
    installed_version: Optional[str] = None
    latest_version: Optional[str] = None
    has_update: bool = False
    source: Optional[str] = None


class PluginUpdatesResponse(BaseModel):
    """Response containing plugins with available updates."""

    plugins: List[PluginUpdateInfo]
    outdated_count: int


class PluginValidationResult(BaseModel):
    """Result of validating a plugin."""

    valid: bool
    errors: List[str] = []
    warnings: List[str] = []


class AvailablePluginsResponse(BaseModel):
    """Response containing all available plugins from all marketplaces."""

    plugins: List[MarketplacePlugin]


class PluginValidateRequest(BaseModel):
    """Request to validate a plugin."""

    path: str


class PluginUpdateResponse(BaseModel):
    """Response from updating a plugin."""

    success: bool
    message: str
    stdout: Optional[str] = None
    stderr: Optional[str] = None


class PluginUpdateAllResponse(BaseModel):
    """Response from updating all plugins."""

    success: bool
    message: str
    updated_count: int
    failed_count: int
    results: List[PluginUpdateResponse] = []


# Hook Schemas

# Valid hook event types
VALID_HOOK_EVENTS = [
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "Stop",
    "SessionStart",
    "SessionEnd",
    "UserPromptSubmit",
    "PermissionRequest",
    "Notification",
    "SubagentStart",
    "SubagentStop",
    "PreCompact",
]


class Hook(BaseModel):
    """Hook configuration."""

    id: str
    event: str  # PreToolUse, PostToolUse, PostToolUseFailure, Stop, SessionStart, SessionEnd, UserPromptSubmit, PermissionRequest, Notification, SubagentStart, SubagentStop, PreCompact
    matcher: Optional[str] = None  # Tool matcher pattern (e.g., "Write(*.py)")
    type: str = "command"  # "command", "prompt", or "agent"
    command: Optional[str] = None  # Shell command to execute (for command type)
    prompt: Optional[str] = None  # Prompt to append (for prompt/agent type)
    model: Optional[str] = None  # Model to use (for agent type, e.g., "haiku")
    async_: Optional[bool] = None  # Run in background (JSON field name: "async")
    statusMessage: Optional[str] = None  # Custom spinner message
    once: Optional[bool] = None  # Run only once per session
    timeout: Optional[int] = None  # Timeout in seconds
    scope: str  # "user" or "project"

    class Config:
        # Map async_ to "async" in JSON
        populate_by_name = True


class HookCreate(BaseModel):
    """Schema for creating a hook."""

    event: str
    matcher: Optional[str] = None
    type: str = "command"  # "command", "prompt", or "agent"
    command: Optional[str] = None
    prompt: Optional[str] = None
    model: Optional[str] = None  # For agent hooks
    async_: Optional[bool] = None  # Run in background
    statusMessage: Optional[str] = None  # Custom spinner message
    once: Optional[bool] = None  # Run only once per session
    timeout: Optional[int] = None
    scope: str  # "user" or "project"


class HookUpdate(BaseModel):
    """Schema for updating a hook."""

    event: Optional[str] = None
    matcher: Optional[str] = None
    type: Optional[str] = None
    command: Optional[str] = None
    prompt: Optional[str] = None
    model: Optional[str] = None
    async_: Optional[bool] = None
    statusMessage: Optional[str] = None
    once: Optional[bool] = None
    timeout: Optional[int] = None


class HookListResponse(BaseModel):
    """List of hooks."""

    hooks: List[Hook]


# Permission Schemas

# Valid permission modes
VALID_PERMISSION_MODES = [
    "default",
    "acceptEdits",
    "dontAsk",
    "plan",
]


class PermissionRule(BaseModel):
    """Permission rule configuration."""

    id: str
    type: str  # "allow", "deny", or "ask"
    pattern: str  # Tool(pattern), Tool:subcommand, WebFetch(domain:...), MCP(server:tool), Task(*), Skill(skill-name)
    scope: str  # "user" or "project"


class PermissionRuleCreate(BaseModel):
    """Schema for creating a permission rule."""

    type: str  # "allow", "deny", or "ask"
    pattern: str  # Tool(pattern), Tool:subcommand, WebFetch(domain:...), MCP(server:tool), Task(*), Skill(skill-name)
    scope: str  # "user" or "project"


class PermissionRuleUpdate(BaseModel):
    """Schema for updating a permission rule."""

    type: Optional[str] = None
    pattern: Optional[str] = None


class PermissionSettings(BaseModel):
    """Full permission settings including mode and directories."""

    defaultMode: Optional[str] = "default"  # default/acceptEdits/dontAsk/plan
    additionalDirectories: Optional[List[str]] = None  # Additional allowed directories
    disableBypassPermissionsMode: Optional[bool] = False  # Disable bypass mode


class PermissionListResponse(BaseModel):
    """List of permission rules with settings."""

    rules: List[PermissionRule]
    settings: Optional[PermissionSettings] = None


class PermissionSettingsUpdate(BaseModel):
    """Schema for updating permission settings."""

    defaultMode: Optional[str] = None
    additionalDirectories: Optional[List[str]] = None
    disableBypassPermissionsMode: Optional[bool] = None


# Agent and Skill Schemas


class AgentHook(BaseModel):
    """Agent lifecycle hook."""

    type: str  # "command" or "prompt"
    command: Optional[str] = None
    prompt: Optional[str] = None


class Agent(BaseModel):
    """Agent configuration."""

    name: str
    scope: str  # "user" or "project"
    description: Optional[str] = None
    tools: Optional[List[str]] = None
    model: Optional[str] = None
    prompt: str  # Full prompt content
    # Subagent management fields
    disallowed_tools: Optional[List[str]] = None  # Tools to deny
    permission_mode: Optional[str] = None  # default/acceptEdits/dontAsk/bypassPermissions/plan
    skills: Optional[List[str]] = None  # Preload skills into context
    hooks: Optional[Dict[str, List[AgentHook]]] = None  # Lifecycle hooks scoped to subagent
    memory: Optional[str] = None  # Persistent memory scope (user/project/local/none)


class AgentCreate(BaseModel):
    """Schema for creating an agent."""

    name: str
    scope: str  # "user" or "project"
    description: Optional[str] = None
    tools: Optional[List[str]] = None
    model: Optional[str] = None
    prompt: str
    # Subagent management fields
    disallowed_tools: Optional[List[str]] = None
    permission_mode: Optional[str] = None
    skills: Optional[List[str]] = None
    hooks: Optional[Dict[str, List[AgentHook]]] = None
    memory: Optional[str] = None


class AgentUpdate(BaseModel):
    """Schema for updating an agent."""

    description: Optional[str] = None
    tools: Optional[List[str]] = None
    model: Optional[str] = None
    prompt: Optional[str] = None
    # Subagent management fields
    disallowed_tools: Optional[List[str]] = None
    permission_mode: Optional[str] = None
    skills: Optional[List[str]] = None
    hooks: Optional[Dict[str, List[AgentHook]]] = None
    memory: Optional[str] = None


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


class SkillFrontmatter(BaseModel):
    """All known skill frontmatter fields."""

    # Identity
    name: Optional[str] = None
    description: Optional[str] = None
    version: Optional[str] = None
    license: Optional[str] = None

    # Execution context
    context: Optional[str] = None  # "fork" to run in a subagent
    agent: Optional[str] = None  # Subagent type: "Explore", "Plan", custom
    model: Optional[str] = None  # Override model for this skill

    # Tool control
    allowed_tools: Optional[List[str]] = None  # Tools available without permission

    # Visibility & invocability
    user_invocable: Optional[bool] = None  # Show in / menu (default true)
    disable_model_invocation: Optional[bool] = None  # Prevent auto-loading

    # UX
    argument_hint: Optional[str] = None  # Autocomplete hint e.g. "[issue-number]"

    # Hooks
    hooks: Optional[dict] = None  # Lifecycle hooks scoped to skill

    # Metadata (author, version, etc.)
    metadata: Optional[dict] = None


class Skill(BaseModel):
    """Skill definition."""

    name: str
    description: Optional[str] = None
    location: str  # "user", "project", or plugin path
    content: Optional[str] = None  # Full markdown content (optional)
    # Full frontmatter (populated on detail view)
    frontmatter: Optional[SkillFrontmatter] = None
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


# Settings Update Schemas


class SettingsUpdateRequest(BaseModel):
    """Schema for updating settings."""

    scope: str  # "user", "project", or "local"
    settings: Dict[str, Any]
    project_path: Optional[str] = None  # Required for project/local scope


class SettingsUpdateResponse(BaseModel):
    """Response from settings update."""

    success: bool
    message: str
    path: str  # File path that was updated
    migrated_patterns: Optional[List[Dict[str, str]]] = None
    removed_patterns: Optional[List[Dict[str, str]]] = None


class SettingsValidationRequest(BaseModel):
    """Schema for validating settings without saving."""

    settings: Dict[str, Any]


class PatternIssue(BaseModel):
    """A single pattern validation issue."""

    pattern: str
    category: str
    error: str
    suggestion: Optional[str] = None


class SettingsValidationResponse(BaseModel):
    """Response from settings validation."""

    valid: bool
    issues: List[PatternIssue] = []


# Backup Manifest & Dependency Schemas


class BackupSkillDependency(BaseModel):
    """Dependency detected in a skill."""

    kind: str  # "npm", "pip", "bin", "script"
    name: str
    version: Optional[str] = None


class BackupSkillInfo(BaseModel):
    """Skill information in backup manifest."""

    name: str
    path: str
    has_package_json: bool = False
    has_requirements_txt: bool = False
    has_install_script: bool = False
    dependencies: List[BackupSkillDependency] = []


class BackupPluginInfo(BaseModel):
    """Plugin information in backup manifest."""

    name: str
    version: Optional[str] = None
    source: Optional[str] = None
    install_command: Optional[str] = None
    marketplace: Optional[str] = None


class BackupMCPServerInfo(BaseModel):
    """MCP server information in backup manifest."""

    name: str
    type: str  # "stdio", "http", "sse"
    scope: str
    command: Optional[str] = None
    args: Optional[List[str]] = None
    url: Optional[str] = None
    requires_npm_install: bool = False


class BackupManifestContents(BaseModel):
    """Contents tracked in backup manifest."""

    files: List[str] = []
    skills: List[BackupSkillInfo] = []
    plugins: List[BackupPluginInfo] = []
    mcp_servers: List[BackupMCPServerInfo] = []
    agents: List[str] = []
    commands: List[str] = []


class BackupManifest(BaseModel):
    """Full backup manifest stored in the backup zip."""

    version: str = "1.0"
    created_at: str
    claude_code_version: Optional[str] = None
    platform: str  # "linux", "darwin", "win32"
    scope: str  # "full", "user", "project"
    contents: BackupManifestContents


class RestoreOptions(BaseModel):
    """Options for restore operation."""

    selective_restore: Optional[List[str]] = None  # Specific paths to restore
    install_dependencies: bool = False  # Auto-install deps after restore
    dry_run: bool = False  # Preview only, don't actually restore
    skip_plugins: bool = False
    skip_skills: bool = False
    skip_mcp_servers: bool = False


class DependencyInstallStatus(BaseModel):
    """Status of a single dependency installation."""

    name: str
    kind: str  # "npm", "pip", "plugin", "skill"
    success: bool
    message: Optional[str] = None


class RestorePlanDependency(BaseModel):
    """A dependency that needs to be installed during restore."""

    kind: str  # "npm", "pip", "plugin", "mcp_npm"
    name: str
    version: Optional[str] = None
    source: Optional[str] = None  # Skill/plugin name requiring this
    install_command: Optional[str] = None


class RestorePlanWarning(BaseModel):
    """Warning about restore compatibility."""

    type: str  # "platform", "version", "missing_tool"
    message: str
    severity: str = "warning"  # "warning", "error"


class RestorePlan(BaseModel):
    """Plan showing what will be restored and dependencies needed."""

    backup_id: int
    backup_name: str
    created_at: str
    scope: str
    platform_current: str
    platform_backup: str
    platform_compatible: bool

    # What will be restored
    files_to_restore: List[str] = []
    skills_to_restore: List[BackupSkillInfo] = []
    plugins_to_restore: List[BackupPluginInfo] = []
    mcp_servers_to_restore: List[BackupMCPServerInfo] = []

    # Dependencies needed
    dependencies: List[RestorePlanDependency] = []
    has_dependencies: bool = False

    # Warnings
    warnings: List[RestorePlanWarning] = []

    # Manual steps
    manual_steps: List[str] = []


class RestoreResult(BaseModel):
    """Result of restore operation."""

    success: bool
    message: str
    files_restored: int = 0
    files_skipped: int = 0
    dry_run: bool = False
    dependency_results: List[DependencyInstallStatus] = []
    manual_steps: List[str] = []


class DependencyInstallRequest(BaseModel):
    """Request to install dependencies from a backup."""

    install_npm: bool = True
    install_pip: bool = True
    install_plugins: bool = True
    skill_names: Optional[List[str]] = None  # Specific skills to install deps for
    plugin_names: Optional[List[str]] = None  # Specific plugins to reinstall


class DependencyInstallResult(BaseModel):
    """Result of dependency installation."""

    success: bool
    message: str
    installed: List[DependencyInstallStatus] = []
    failed: List[DependencyInstallStatus] = []
    logs: str = ""


# Context Window Analysis Schemas


class ContextSnapshot(BaseModel):
    """One turn's context window state."""

    turn_number: int
    timestamp: str
    total_context_tokens: int
    input_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    output_tokens: int
    model: str
    context_percentage: float  # 0-100


class ContentCategory(BaseModel):
    """Content type breakdown."""

    category: str  # "user_messages", "assistant_messages", "tool_results", "tool_calls", "thinking"
    estimated_chars: int
    estimated_tokens: int
    percentage: float


class FileConsumption(BaseModel):
    """File read consumption data."""

    file_path: str
    read_count: int
    total_chars: int
    estimated_tokens: int


class CacheEfficiency(BaseModel):
    """Cache hit/miss breakdown."""

    total_cache_read: int
    total_cache_creation: int
    total_uncached: int
    hit_ratio: float  # 0-1


class ContextCategoryItem(BaseModel):
    """Single item within a category (e.g., one MCP tool, one memory file)."""

    name: str
    estimated_tokens: int


class ContextCompositionCategory(BaseModel):
    """One category in the context composition breakdown."""

    category: str  # "System Prompt", "MCP Tools", etc.
    estimated_tokens: int
    percentage: float
    color: str  # Hex color for chart
    items: Optional[List[ContextCategoryItem]] = None


class ContextComposition(BaseModel):
    """Full context composition matching /context CLI output."""

    categories: List[ContextCompositionCategory]
    total_tokens: int
    context_limit: int
    model: str


class ContextAnalysis(BaseModel):
    """Full context analysis for a session."""

    session_id: str
    project_folder: str
    project_name: str
    model: str
    current_context_tokens: int
    max_context_tokens: int
    context_percentage: float
    snapshots: List[ContextSnapshot]
    content_categories: List[ContentCategory]
    file_consumptions: List[FileConsumption]
    cache_efficiency: CacheEfficiency
    avg_tokens_per_turn: int
    estimated_turns_remaining: int
    context_zone: str  # "green", "yellow", "orange", "red"
    total_turns: int
    composition: Optional[ContextComposition] = None


class ContextAnalysisResponse(BaseModel):
    """Response wrapper for context analysis."""

    analysis: ContextAnalysis


class ActiveSessionContext(BaseModel):
    """Lightweight context info for an active/recent session."""

    session_id: str
    project_folder: str
    project_name: str
    model: str
    context_percentage: float
    current_context_tokens: int
    max_context_tokens: int
    is_active: bool
    last_activity: str


class ActiveSessionsResponse(BaseModel):
    """List of active sessions with context info."""

    sessions: List[ActiveSessionContext]


# Plan History Browser Schemas


class PlanSummary(BaseModel):
    """Summary of a plan file for list view."""

    filename: str
    slug: str
    title: str
    excerpt: str
    modified_at: str
    size_bytes: int


class PlanLinkedSession(BaseModel):
    """Session linked to a plan via slug."""

    session_id: str
    project_folder: str
    project_name: str
    git_branch: Optional[str] = None
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None


class PlanDetail(BaseModel):
    """Full plan detail including content and linked sessions."""

    filename: str
    slug: str
    title: str
    content: str
    modified_at: str
    size_bytes: int
    headings: List[str]
    code_block_count: int
    table_count: int
    linked_sessions: List[PlanLinkedSession]


class PlanSearchResult(BaseModel):
    """Plan matching a search query."""

    filename: str
    slug: str
    title: str
    matches: List[str]
    modified_at: str


class PlanListResponse(BaseModel):
    """List of plan summaries."""

    plans: List[PlanSummary]
    total: int


class PlanDetailResponse(BaseModel):
    """Single plan detail response."""

    plan: PlanDetail


class PlanSearchResponse(BaseModel):
    """Plan search results."""

    results: List[PlanSearchResult]
    query: str
    total: int


class PlanStatsResponse(BaseModel):
    """Plan statistics for dashboard."""

    total_plans: int
    oldest_date: Optional[str] = None
    newest_date: Optional[str] = None
    total_size_bytes: int


# MCP Registry Schemas


class MCPRegistryInstallRequest(BaseModel):
    """Request to install an MCP server from the registry."""

    server_name: str  # User-chosen config name (e.g., "github")
    scope: str  # "user" or "project"
    # Package install fields (mutually exclusive with remote_*)
    package_registry_type: Optional[str] = None  # "npm", "pypi", "oci"
    package_identifier: Optional[str] = None
    package_version: Optional[str] = None
    package_runtime_hint: Optional[str] = None
    package_arguments: Optional[Dict[str, str]] = None
    # Remote install fields
    remote_type: Optional[str] = None  # "streamable-http", "sse"
    remote_url: Optional[str] = None
    remote_headers: Optional[Dict[str, str]] = None
    # Shared
    env_values: Optional[Dict[str, str]] = None


class MCPRegistryInstallResponse(BaseModel):
    """Response from MCP registry install."""

    success: bool
    server_name: str
    config: Dict[str, Any]
    scope: str
