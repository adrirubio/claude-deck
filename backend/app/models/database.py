"""SQLAlchemy database models."""
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Project(Base):
    """Project model for tracking Claude Code project directories."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    path: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_accessed: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )


class Backup(Base):
    """Backup model for storing configuration backup metadata."""

    __tablename__ = "backups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=True)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    scope: Mapped[str] = mapped_column(String, nullable=False)  # "full", "user", "project"
    project_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)


class Marketplace(Base):
    """Marketplace model for plugin marketplace configurations."""

    __tablename__ = "marketplaces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    last_synced: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )


class SessionCache(Base):
    """Cache for session metadata to avoid re-parsing JSONL files."""

    __tablename__ = "session_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    project_folder: Mapped[str] = mapped_column(String, index=True, nullable=False)
    project_name: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(String, nullable=False)
    modified_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    total_messages: Mapped[int] = mapped_column(Integer, nullable=False)
    total_tool_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    cached_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    file_hash: Mapped[str] = mapped_column(String, nullable=False)


class UsageCache(Base):
    """Cache for usage aggregation data to avoid re-parsing JSONL files."""

    __tablename__ = "usage_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cache_key: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    cache_type: Mapped[str] = mapped_column(String, index=True, nullable=False)  # daily, session, monthly, block, summary
    project_path: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)  # Aggregated usage data
    cached_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    file_hash: Mapped[str | None] = mapped_column(String, nullable=True)  # For cache invalidation


class MCPServerCache(Base):
    """Cache for MCP server connection status and tools."""

    __tablename__ = "mcp_server_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_name: Mapped[str] = mapped_column(String, index=True, nullable=False)
    server_scope: Mapped[str] = mapped_column(String, index=True, nullable=False)
    is_connected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    mcp_server_name: Mapped[str | None] = mapped_column(String, nullable=True)
    mcp_server_version: Mapped[str | None] = mapped_column(String, nullable=True)
    tools: Mapped[list | None] = mapped_column(JSON, nullable=True)
    tool_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    resources: Mapped[list | None] = mapped_column(JSON, nullable=True)
    prompts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    resource_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    prompt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    capabilities: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cached_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    config_hash: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint('server_name', 'server_scope', name='uix_server_name_scope'),
    )


class AgentTeamPreset(Base):
    """Saved roster of local agent slots that can be launched together."""

    __tablename__ = "agent_team_presets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    autonomy_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class AgentTeamSlot(Base):
    """One desired agent slot within a saved team preset."""

    __tablename__ = "agent_team_slots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    preset_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agent_team_presets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    repo_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    repo_path: Mapped[str] = mapped_column(String, nullable=False)
    repo_name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str | None] = mapped_column(String, nullable=True)
    charter: Mapped[str | None] = mapped_column(String, nullable=True)
    ui_color: Mapped[str | None] = mapped_column(String, nullable=True)
    bootstrap_prompt: Mapped[str | None] = mapped_column(String, nullable=True)
    launch_mode: Mapped[str] = mapped_column(String, default="plain", nullable=False)
    launch_options: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    area_labels: Mapped[list | None] = mapped_column(JSON, nullable=True)
    expertise: Mapped[str | None] = mapped_column(String, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AgentTeamLaunch(Base):
    """Audit record for an Agent Team launch request."""

    __tablename__ = "agent_team_launches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    preset_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agent_team_presets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    requested_by: Mapped[str | None] = mapped_column(String, nullable=True)
    plan_hash: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="running", nullable=False)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AgentTeamLaunchItem(Base):
    """Per-slot launch outcome for an Agent Team launch."""

    __tablename__ = "agent_team_launch_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    launch_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agent_team_launches.id", ondelete="CASCADE"), index=True, nullable=False
    )
    slot_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agent_team_slots.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    repo_path: Mapped[str | None] = mapped_column(String, nullable=True)
    session_name: Mapped[str | None] = mapped_column(String, nullable=True)
    tmux_target: Mapped[str | None] = mapped_column(String, nullable=True)
    message: Mapped[str | None] = mapped_column(String, nullable=True)
    block_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class TeamGithubScope(Base):
    """A GitHub repo an Agent Team watches for labeled issues."""

    __tablename__ = "team_github_scopes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    preset_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agent_team_presets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    repo_owner: Mapped[str] = mapped_column(String, nullable=False)
    repo_name: Mapped[str] = mapped_column(String, nullable=False)
    repo_path: Mapped[str] = mapped_column(String, nullable=False)
    dispatch_label: Mapped[str] = mapped_column(String, default="claude-deck-ready", nullable=False)
    design_label: Mapped[str] = mapped_column(String, default="claude-deck-design", nullable=False)
    merge_policy: Mapped[str] = mapped_column(String, default="human", nullable=False)
    max_approval_rounds: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    max_concurrent_dispatched: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    max_verification_retries: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    max_auto_merges_per_day: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    base_ref: Mapped[str] = mapped_column(String, default="origin/HEAD", nullable=False)
    builds_out_of_tree: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    build_dir_template: Mapped[str | None] = mapped_column(String, default="build", nullable=True)
    build_command_hint: Mapped[str | None] = mapped_column(String, nullable=True)
    max_build_parallelism: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("preset_id", "repo_owner", "repo_name", name="uix_preset_repo_scope"),
    )


class GithubWorkItem(Base):
    """A labeled GitHub issue the dispatch pipeline is tracking."""

    __tablename__ = "github_work_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("team_github_scopes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    issue_number: Mapped[int] = mapped_column(Integer, nullable=False)
    issue_title: Mapped[str] = mapped_column(String, nullable=False)
    issue_url: Mapped[str] = mapped_column(String, nullable=False)
    github_updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    issue_type: Mapped[str] = mapped_column(String, default="code", nullable=False)
    dispatch_status: Mapped[str] = mapped_column(String, default="pending", nullable=False)
    pending_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    launch_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agent_team_launches.id", ondelete="SET NULL"), nullable=True
    )
    owner_slot_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agent_team_slots.id", ondelete="SET NULL"), nullable=True
    )
    routing_method: Mapped[str | None] = mapped_column(String, nullable=True)
    handoff_state: Mapped[str | None] = mapped_column(String, nullable=True)
    handoff_target_slot_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agent_team_slots.id", ondelete="SET NULL"), nullable=True
    )
    approval_round_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_verified_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ack_received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_nudge_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    retry_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    brief_delivery_nudge_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    brief_delivery_nudge_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    brief_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ack_approver_member_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ack_evidence_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dispatch_nonce: Mapped[str | None] = mapped_column(String, nullable=True)
    ack_enforcement_epoch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ack_approval_round: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dispatch_head_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    escalation_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    status_note: Mapped[str | None] = mapped_column(String, nullable=True)
    auto_merged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("scope_id", "issue_number", name="uix_scope_issue"),
    )


class GithubWorkspace(Base):
    """A checkout a dispatched work item may exclusively occupy."""

    __tablename__ = "github_workspaces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("team_github_scopes.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    path: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, default="worktree", nullable=False)
    dispatchable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    leased_item_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("github_work_items.id", ondelete="SET NULL"), nullable=True
    )
    leased_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String, nullable=True)
    leased_owner_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    leased_owner_proc_start: Mapped[str | None] = mapped_column(String, nullable=True)
    lease_last_owner_contact_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lease_release_reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    provision_error: Mapped[str | None] = mapped_column(String, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("path", name="uix_workspace_path"),
        UniqueConstraint("leased_item_id", name="uix_workspace_leased_item"),
    )


class AgentPaneBinding(Base):
    """Which tmux pane a launched slot physically occupies.

    Written by the launcher at launch time and committed on its own, ahead of
    the slot loop's single commit, because the pane it describes can register
    with Agent Mail before that loop finishes. A binding that is not visible
    yet is indistinguishable from a pane that was never launched.
    """

    __tablename__ = "agent_pane_bindings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pane_pid: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    pane_proc_start: Mapped[str] = mapped_column(String, nullable=False)
    slot_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agent_team_slots.id", ondelete="SET NULL"), nullable=True
    )
    preset_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agent_team_presets.id", ondelete="SET NULL"), nullable=True
    )
    tmux_target: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("pane_pid", "pane_proc_start", name="uix_pane_binding"),
    )


class BridgeSessionAttachment(Base):
    """Image attachment uploaded for an Agent Bridge tmux session."""

    __tablename__ = "bridge_session_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target: Mapped[str] = mapped_column(String, index=True, nullable=False)
    session_name: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String, index=True, nullable=False)
    storage_path: Mapped[str] = mapped_column(String, nullable=False)
    agent_path: Mapped[str] = mapped_column(String, nullable=False)
    prompt_text: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MailTeamMember(Base):
    """Durable Agent Mail routable participant, grouped by repository."""

    __tablename__ = "mail_team_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    identity_key: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    repo_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    repo_path: Mapped[str] = mapped_column(String, nullable=False)
    repo_name: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    participant_kind: Mapped[str] = mapped_column(String, default="repo", nullable=False)
    team_preset_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agent_team_presets.id", ondelete="SET NULL"), nullable=True
    )
    team_slot_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agent_team_slots.id", ondelete="SET NULL"), nullable=True
    )
    role: Mapped[str | None] = mapped_column(String, nullable=True)
    charter: Mapped[str | None] = mapped_column(String, nullable=True)
    last_inbox_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class MailAgentSession(Base):
    """Ephemeral agent session attached to a durable team member."""

    __tablename__ = "mail_agent_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    member_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mail_team_members.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String, default="unknown", nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    session_key: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    cwd: Mapped[str | None] = mapped_column(String, nullable=True)
    tmux_target: Mapped[str | None] = mapped_column(String, nullable=True)
    pane_id: Mapped[str | None] = mapped_column(String, nullable=True)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    team_preset_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agent_team_presets.id", ondelete="SET NULL"), nullable=True
    )
    team_slot_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agent_team_slots.id", ondelete="SET NULL"), nullable=True
    )
    capability_token_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    bound_pane_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bound_pane_proc_start: Mapped[str | None] = mapped_column(String, nullable=True)
    mailbox_status: Mapped[str] = mapped_column(String, default="connected", nullable=False)
    activity: Mapped[str | None] = mapped_column(String, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class MailExternalActor(Base):
    """Durable identity for a local external Agent Mail orchestrator."""

    __tablename__ = "mail_external_actors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_key: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, default="external_tool", nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    token_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MailMessage(Base):
    """Agent Mail message with request lifecycle state where applicable."""

    __tablename__ = "mail_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_root_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("mail_messages.id", ondelete="CASCADE"), index=True, nullable=True
    )
    kind: Mapped[str] = mapped_column(String, default="message", nullable=False, index=True)
    sender_member_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("mail_team_members.id", ondelete="SET NULL"), nullable=True
    )
    sender_actor_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("mail_external_actors.id", ondelete="SET NULL"), nullable=True
    )
    approval_round: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decision: Mapped[str | None] = mapped_column(String, nullable=True)
    recipient_member_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("mail_team_members.id", ondelete="CASCADE"), index=True, nullable=True
    )
    subject: Mapped[str | None] = mapped_column(String, nullable=True)
    body_markdown: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    request_status: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )


class MailReceipt(Base):
    """Per-recipient read/ack state for a message."""

    __tablename__ = "mail_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mail_messages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    member_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mail_team_members.id", ondelete="CASCADE"), index=True, nullable=False
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("message_id", "member_id", name="uix_mail_receipt_message_member"),
    )
