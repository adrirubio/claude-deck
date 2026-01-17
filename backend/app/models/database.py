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
    cached_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    config_hash: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint('server_name', 'server_scope', name='uix_server_name_scope'),
    )
