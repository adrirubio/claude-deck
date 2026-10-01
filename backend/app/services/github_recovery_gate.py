"""Identity selector for a single preserved GitHub recovery attempt."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import settings
from app.models.database import GithubWorkItem


@dataclass(frozen=True, slots=True)
class GithubRecoveryOnlyAttempt:
    scope_id: int
    work_item_id: int
    pr_number: int
    dispatch_nonce: str
    head_ref: str

    @classmethod
    def parse(cls, value: str) -> GithubRecoveryOnlyAttempt | None:
        if not value:
            return None
        parts = value.split(":", 4)
        if len(parts) != 5 or any(
            not re.fullmatch(r"[1-9][0-9]*", part) for part in parts[:3]
        ):
            raise ValueError(
                "GITHUB_RECOVERY_ONLY_ATTEMPT must identify scope:item:PR:nonce:head-ref"
            )
        scope_id, work_item_id, pr_number = (int(part) for part in parts[:3])
        nonce, head_ref = parts[3:]
        if not re.fullmatch(r"[0-9a-f]{16}", nonce) or not re.fullmatch(
            r"[A-Za-z0-9._/-]+", head_ref
        ):
            raise ValueError("GITHUB_RECOVERY_ONLY_ATTEMPT has an invalid nonce or head ref")
        return cls(scope_id, work_item_id, pr_number, nonce, head_ref)

    def item_filters(self):
        return (
            GithubWorkItem.scope_id == self.scope_id,
            GithubWorkItem.id == self.work_item_id,
            GithubWorkItem.pr_number == self.pr_number,
            GithubWorkItem.dispatch_nonce == self.dispatch_nonce,
            GithubWorkItem.dispatch_head_ref == self.head_ref,
        )

    def matches_item(self, item: GithubWorkItem) -> bool:
        return (
            item.scope_id == self.scope_id
            and item.id == self.work_item_id
            and item.pr_number == self.pr_number
            and item.dispatch_nonce == self.dispatch_nonce
            and item.dispatch_head_ref == self.head_ref
        )


def configured_recovery_only_attempt() -> GithubRecoveryOnlyAttempt | None:
    return GithubRecoveryOnlyAttempt.parse(settings.github_recovery_only_attempt)
