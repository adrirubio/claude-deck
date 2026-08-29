"""Hosted scheduler for autonomous GitHub dispatch."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.database import AgentTeamPreset, AgentTeamSlot, GithubWorkItem, TeamGithubScope
from app.services.github_client import GithubClient, github_client
from app.services.github_dispatch_service import github_dispatch_service
from app.services.github_verification_service import github_verification_service
from app.services.github_watcher_service import github_watcher_service

logger = logging.getLogger(__name__)

_JOB_PREFIX = "github-dispatch:"


class GithubDispatchScheduler:
    def __init__(
        self,
        scheduler=None,
        *,
        interval_seconds: int | None = None,
        watcher=github_watcher_service,
        dispatch=github_dispatch_service,
        verification=github_verification_service,
    ) -> None:
        self.scheduler = scheduler
        self.interval_seconds = interval_seconds or settings.github_dispatch_interval_seconds
        self.watcher = watcher
        self.dispatch = dispatch
        self.verification = verification

    def _ensure_scheduler(self):
        if self.scheduler is None:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler

            self.scheduler = AsyncIOScheduler()
        return self.scheduler

    async def start(self) -> None:
        scheduler = self._ensure_scheduler()
        async with AsyncSessionLocal() as db:
            await self.sync_jobs(db)
        if not getattr(scheduler, "running", False):
            scheduler.start()

    async def shutdown(self) -> None:
        if self.scheduler is not None and getattr(self.scheduler, "running", False):
            self.scheduler.shutdown(wait=False)

    async def sync_jobs(self, db: AsyncSession) -> None:
        scheduler = self._ensure_scheduler()
        rows = (
            await db.execute(
                select(TeamGithubScope.repo_owner, TeamGithubScope.repo_name)
                .join(AgentTeamPreset, AgentTeamPreset.id == TeamGithubScope.preset_id)
                .where(
                    TeamGithubScope.enabled.is_(True),
                    AgentTeamPreset.autonomy_enabled.is_(True),
                )
                .distinct()
            )
        ).all()
        desired = {self._job_id(owner, repo): (owner, repo) for owner, repo in rows}
        existing = {
            job.id
            for job in scheduler.get_jobs()
            if getattr(job, "id", "").startswith(_JOB_PREFIX)
        }
        for stale_id in existing - set(desired):
            scheduler.remove_job(stale_id)
        for job_id, (owner, repo) in desired.items():
            if job_id in existing:
                continue
            scheduler.add_job(
                self.run_repo_job,
                "interval",
                seconds=self.interval_seconds,
                id=job_id,
                args=[owner, repo],
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )

    async def run_repo_job(self, owner: str, repo: str) -> None:
        try:
            async with AsyncSessionLocal() as db:
                await self.run_repo_once(db, owner, repo)
                await self.sync_jobs(db)
        except Exception:
            logger.exception("Autonomous GitHub dispatch job failed for %s/%s", owner, repo)

    async def run_repo_once(
        self,
        db: AsyncSession,
        owner: str,
        repo: str,
        *,
        client: GithubClient | None = None,
        launcher=None,
        classify=None,
    ) -> None:
        client = client or github_client
        scopes = (
            await db.execute(
                select(TeamGithubScope)
                .join(AgentTeamPreset, AgentTeamPreset.id == TeamGithubScope.preset_id)
                .where(
                    TeamGithubScope.repo_owner == owner,
                    TeamGithubScope.repo_name == repo,
                    TeamGithubScope.enabled.is_(True),
                    AgentTeamPreset.autonomy_enabled.is_(True),
                )
                .order_by(TeamGithubScope.id)
            )
        ).scalars().all()
        for scope in scopes:
            await self.watcher.poll_scope(db, scope, client)
            slots = (
                await db.execute(
                    select(AgentTeamSlot)
                    .where(AgentTeamSlot.preset_id == scope.preset_id)
                    .order_by(AgentTeamSlot.position, AgentTeamSlot.id)
                )
            ).scalars().all()
            issues_by_number = await self._pending_issues_by_number(db, scope, client)
            issue_labels_by_number = {
                number: [label["name"] for label in issue.get("labels", []) if "name" in label]
                for number, issue in issues_by_number.items()
            }
            await self.dispatch.dispatch_pending(
                db,
                scope,
                slots,
                client=client,
                classify=classify,
                launcher=launcher,
                issue_labels_by_number=issue_labels_by_number,
                issue_details_by_number=issues_by_number,
            )
            await db.commit()
            scope, slots = await self._reload_scope_context(db, scope.id)
            await self.dispatch.monitor_dispatched(db, scope, slots)
            await db.commit()
            scope, slots = await self._reload_scope_context(db, scope.id)
            await self.dispatch.monitor_continuation(db, scope, slots)
            await db.commit()
            scope, _slots = await self._reload_scope_context(db, scope.id)
            await self.verification.process_scope(db, scope, client=client)
            await db.commit()
            scope, slots = await self._reload_scope_context(db, scope.id)
            await self.dispatch.monitor_recovery(db, scope, slots)
            await db.commit()
            scope, _slots = await self._reload_scope_context(db, scope.id)
            await self.dispatch.remind_held_leases(db, scope)
            await db.commit()

    async def _reload_scope_context(
        self,
        db: AsyncSession,
        scope_id: int,
    ) -> tuple[TeamGithubScope, list[AgentTeamSlot]]:
        scope = (
            await db.execute(
                select(TeamGithubScope)
                .where(TeamGithubScope.id == scope_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        slots = (
            await db.execute(
                select(AgentTeamSlot)
                .where(AgentTeamSlot.preset_id == scope.preset_id)
                .order_by(AgentTeamSlot.position, AgentTeamSlot.id)
                .execution_options(populate_existing=True)
            )
        ).scalars().all()
        return scope, list(slots)

    async def _pending_issues_by_number(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        client: GithubClient,
    ) -> dict[int, dict]:
        pending_numbers = (
            await db.execute(
                select(GithubWorkItem.issue_number).where(
                    GithubWorkItem.scope_id == scope.id,
                    GithubWorkItem.dispatch_status == "pending",
                )
            )
        ).scalars().all()
        if not pending_numbers:
            return {}
        issues = await client.get_issues_by_number(
            scope.repo_owner,
            scope.repo_name,
            list(pending_numbers),
        )
        return issues

    def _job_id(self, owner: str, repo: str) -> str:
        return f"{_JOB_PREFIX}{owner}/{repo}"


github_dispatch_scheduler = GithubDispatchScheduler()
