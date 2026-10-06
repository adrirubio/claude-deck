"""Safe observation cache, separate from dispatch authority and audit events."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GithubWorkProgressSnapshot(Base):
    __tablename__ = "github_work_progress_snapshots"

    work_item_id: Mapped[int] = mapped_column(
        ForeignKey("github_work_items.id", ondelete="CASCADE"), primary_key=True,
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    identity: Mapped[dict] = mapped_column(JSON, nullable=False)
    observation: Mapped[dict] = mapped_column(JSON, nullable=False)
