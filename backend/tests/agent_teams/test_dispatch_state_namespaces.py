"""Static and behavioral guards for GitHub dispatch state vocabularies."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.models.database import GithubWorkItem
from app.services.github_dispatch_service import (
    DISPATCH_STATUSES,
    ESCALATION_REASONS,
    PENDING_REASONS,
    github_dispatch_service,
)

APP_ROOT = Path(__file__).resolve().parents[2] / "app"
EXPECTED_DISPATCH_STATUSES = frozenset(
    {
        "pending",
        "dispatched",
        "verifying",
        "ready_for_review",
        "awaiting_human_review",
        "merged",
        "completed",
        "escalated",
        "failed",
    }
)
EXPECTED_ESCALATION_REASONS = frozenset(
    {
        "plan_blocked",
        "launch_outcome_unknown",
        "approval_rounds_exhausted",
        "leader_offline",
        "owner_offline",
        "brief_unread",
        "leader_ack_timeout",
        "owner_idle_timeout",
        "retry_count_exhausted",
        "dispatch_label_removed",
        "abandoned_by_operator",
        "prepared_owner_unavailable",
        "pr_closed_unmerged",
    }
)
EXPECTED_PR2_PENDING_REASONS = frozenset(
    {
        "queued_repo_cap",
        "queued_low_memory",
        "queued_slot_busy",
        "queued_ambiguous_sessions",
        "queued_no_workspace",
        "queued_auth_mode_unresolved",
    }
)


@dataclass(frozen=True)
class Write:
    path: Path
    line: int
    field: str
    value: str | None
    form: str


def _module_constants(tree: ast.Module) -> dict[str, str | None]:
    constants: dict[str, str | None] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, (str, type(None))):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                constants[target.id] = value.value
    return constants


def _value(node: ast.expr, constants: dict[str, str | None]) -> str | None | object:
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, type(None))):
        return node.value
    if isinstance(node, ast.Name) and node.id in constants:
        return constants[node.id]
    return _UNKNOWN


_UNKNOWN = object()
_FIELDS = {"dispatch_status", "escalation_reason", "pending_reason"}


def classify_writes(source: str, path: Path = Path("synthetic.py")) -> list[Write]:
    tree = ast.parse(source)
    constants = _module_constants(tree)
    writes: list[Write] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr in _FIELDS:
                    value = _value(node.value, constants)
                    writes.append(
                        Write(
                            path,
                            node.lineno,
                            target.attr,
                            None if value is _UNKNOWN else value,
                            "assignment_unknown" if value is _UNKNOWN else "assignment",
                        )
                    )
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "setattr":
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                field = node.args[1].value
                if field in _FIELDS:
                    writes.append(Write(path, node.lineno, field, None, "setattr"))
        if isinstance(node.func, ast.Name) and node.func.id == "GithubWorkItem":
            if any(keyword.arg is None for keyword in node.keywords):
                writes.append(Write(path, node.lineno, "*", None, "item_splat"))
            for keyword in node.keywords:
                if keyword.arg in _FIELDS:
                    value = _value(keyword.value, constants)
                    writes.append(
                        Write(
                            path,
                            node.lineno,
                            keyword.arg,
                            None if value is _UNKNOWN else value,
                            "constructor_unknown" if value is _UNKNOWN else "constructor",
                        )
                    )
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "values"
            and any(
                isinstance(part, ast.Name) and part.id == "GithubWorkItem"
                for part in ast.walk(node.func.value)
            )
        ):
            if any(keyword.arg is None for keyword in node.keywords):
                writes.append(Write(path, node.lineno, "*", None, "values_splat"))
            for keyword in node.keywords:
                if keyword.arg in _FIELDS:
                    value = _value(keyword.value, constants)
                    writes.append(
                        Write(
                            path,
                            node.lineno,
                            keyword.arg,
                            None if value is _UNKNOWN else value,
                            "values_unknown" if value is _UNKNOWN else "values",
                        )
                    )
    return writes


def _app_writes() -> list[Write]:
    writes: list[Write] = []
    for path in APP_ROOT.rglob("*.py"):
        writes.extend(classify_writes(path.read_text(), path.relative_to(APP_ROOT)))
    return writes


def _escalation_call_reasons() -> set[str]:
    reasons: set[str] = set()
    for path in APP_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {
                "escalate",
                "escalate_without_notification",
                "_apply_escalation",
            }:
                continue
            reason_index = 1 if node.func.attr == "_apply_escalation" else 2
            if len(node.args) > reason_index and isinstance(
                node.args[reason_index], ast.Constant
            ):
                reason = node.args[reason_index].value
                if isinstance(reason, str):
                    reasons.add(reason)
    return reasons


def test_declared_namespaces_are_literal_and_complete():
    assert DISPATCH_STATUSES == EXPECTED_DISPATCH_STATUSES
    assert ESCALATION_REASONS == EXPECTED_ESCALATION_REASONS
    assert EXPECTED_PR2_PENDING_REASONS <= PENDING_REASONS


def test_synthetic_classifier_distinguishes_writer_forms():
    writes = classify_writes(
        """
CONST = "pending"
item.dispatch_status = CONST
item.pending_reason: str = dynamic
GithubWorkItem(dispatch_status="failed")
GithubWorkItem(**payload)
update(GithubWorkItem).values(escalation_reason="plan_blocked")
update(GithubWorkItem).values(**payload)
setattr(item, "dispatch_status", "merged")
Unrelated(**payload)
"""
    )
    assert {(write.field, write.form) for write in writes} == {
        ("dispatch_status", "assignment"),
        ("pending_reason", "assignment_unknown"),
        ("dispatch_status", "constructor"),
        ("*", "item_splat"),
        ("escalation_reason", "values"),
        ("*", "values_splat"),
        ("dispatch_status", "setattr"),
    }


def test_whole_tree_writers_stay_inside_declared_namespaces():
    writes = _app_writes()
    forbidden = [
        write
        for write in writes
        if write.form in {"setattr", "item_splat", "values_splat", "constructor_unknown"}
    ]
    assert forbidden == []

    dispatch_literals = {
        write.value
        for write in writes
        if write.field == "dispatch_status" and write.value is not None
    }
    assert dispatch_literals == DISPATCH_STATUSES

    dynamic_dispatch = [
        write
        for write in writes
        if write.field == "dispatch_status" and write.form == "assignment_unknown"
    ]
    assert sorted(
        (write.path.as_posix(), write.line) for write in dynamic_dispatch
    ) == [
        ("services/github_verification_service.py", 970),
        ("services/github_verification_service.py", 998),
    ]

    direct_non_null_escalation_writes = [
        write
        for write in writes
        if write.field == "escalation_reason"
        and write.form == "assignment_unknown"
    ]
    assert len(direct_non_null_escalation_writes) == 1
    assert direct_non_null_escalation_writes[0].path.as_posix() == (
        "services/github_dispatch_service.py"
    )
    assert _escalation_call_reasons() == ESCALATION_REASONS

    pending_literals = {
        write.value
        for write in writes
        if write.field == "pending_reason" and write.value is not None
    }
    assert PENDING_REASONS <= pending_literals


def test_apply_escalation_rejects_an_undeclared_reason():
    item = GithubWorkItem(dispatch_status="dispatched")

    with pytest.raises(ValueError, match="undeclared escalation reason"):
        github_dispatch_service._apply_escalation(item, "invented_reason")
