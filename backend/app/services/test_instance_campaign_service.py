"""Poll seeded campaign data without starting dispatch or opening sockets."""
from __future__ import annotations

import asyncio
from contextlib import suppress
import logging

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.database import TeamGithubScope
from app.services.agent_team_campaign_service import agent_team_campaign_service
from app.services.github_offline import OfflineCampaignClient

logger = logging.getLogger(__name__)


class TestInstanceCampaignPoller:
    def __init__(self, *, config=settings, campaign=agent_team_campaign_service,
                 session_factory=AsyncSessionLocal):
        self.config = config
        self.campaign = campaign
        self.session_factory = session_factory
        self._task = None
        self._client = None

    async def start(self):
        if not self.config.test_instance or (self._task is not None and not self._task.done()):
            return
        self._client = OfflineCampaignClient.from_seed(self.config)
        self.campaign.interval_seconds = 60
        # Fill the cache before the first UI request. Only this poll writes it.
        await self.poll_once()
        self._task = asyncio.create_task(self._run())

    async def poll_once(self):
        if not self.config.test_instance or self._client is None:
            return
        try:
            async with self.session_factory() as db:
                scopes = (await db.scalars(select(TeamGithubScope).order_by(TeamGithubScope.id))).all()
                for scope in scopes:
                    await self.campaign.refresh_scope(db, scope, self._client)
        except Exception:
            # Do not expose seed paths or request data in logs.
            logger.warning("Test-instance campaign poll unavailable")

    async def _run(self):
        while True:
            # Cache reads remain valid for 60 seconds. Poll more often to refill
            # expired observations without changing dispatch or any stored row.
            await asyncio.sleep(5)
            await self.poll_once()

    async def shutdown(self):
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        self._client = None


test_instance_campaign_poller = TestInstanceCampaignPoller()
