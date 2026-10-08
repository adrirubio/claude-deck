"""Static and behavioral guards for GitHub dispatch state vocabularies."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest

from app.models.database import (
    AgentTeamPreset,
    AgentTeamSlot,
    GithubWorkItem,
    GithubWorkspace,
    TeamGithubScope,
)
from app.services.github_app_auth_service import github_app_auth_service
from app.services.github_dispatch_service import (
    DISPATCH_STATUSES,
    ESCALATION_REASONS,
    PENDING_REASONS,
    github_dispatch_service,
)
from app.services.github_verification_service import github_verification_service

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
        "owner_observation_unavailable",
        "integration_update_conflict",
        "retry_count_exhausted",
        "continuation_revision_exhausted",
        "continuation_budget_exhausted",
        "continuation_invalid_state",
        "continuation_pr_identity_invalid",
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
    item_names = {"GithubWorkItem"}
    update_function_names = {"update"}
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        for imported in node.names:
            if imported.name == "GithubWorkItem":
                item_names.add(imported.asname or imported.name)
            if imported.name == "update":
                update_function_names.add(imported.asname or imported.name)

    def is_item_model(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Name) and node.id in item_names
        ) or (
            isinstance(node, ast.Attribute) and node.attr == "GithubWorkItem"
        )

    def is_update_factory(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and bool(node.args)
            and (
                isinstance(node.func, ast.Name)
                and node.func.id in update_function_names
                or isinstance(node.func, ast.Attribute) and node.func.attr == "update"
            )
            and is_item_model(node.args[0])
        )

    item_variable_names = {"item", "work_item"}
    alias_changed = True
    while alias_changed:
        alias_changed = False
        for node in [
            part
            for part in ast.walk(tree)
            if isinstance(part, (ast.Assign, ast.AnnAssign))
        ]:
            value = node.value
            if not isinstance(value, ast.Name) or value.id not in item_variable_names:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in item_variable_names:
                    item_variable_names.add(target.id)
                    alias_changed = True

    update_names: set[str] = set()
    assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
    ]
    changed = True
    while changed:
        changed = False
        for node in assignments:
            value = node.value
            if value is None:
                continue
            if not any(is_update_factory(part) for part in ast.walk(value)) and not any(
                isinstance(part, ast.Name) and part.id in update_names
                for part in ast.walk(value)
            ):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in update_names:
                    update_names.add(target.id)
                    changed = True

    def references_item(node: ast.AST) -> bool:
        return any(
            is_item_model(part)
            or isinstance(part, ast.Name) and part.id in update_names
            for part in ast.walk(node)
        )

    def is_item_target(node: ast.expr) -> bool:
        return isinstance(node, ast.Name) and node.id in item_variable_names

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
            if len(node.args) >= 2:
                resolved_field = _value(node.args[1], constants)
                field = resolved_field if isinstance(resolved_field, str) else None
                if field in _FIELDS:
                    writes.append(Write(path, node.lineno, field, None, "setattr"))
                elif resolved_field is _UNKNOWN:
                    writes.append(
                        Write(
                            path,
                            node.lineno,
                            "*",
                            None,
                            "setattr_unknown"
                            if is_item_target(node.args[0])
                            else "setattr_other_unknown",
                        )
                    )
        constructor_call = is_item_model(node.func)
        if constructor_call:
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
        values_call = (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "values"
            and references_item(node.func.value)
        )
        if values_call:
            for argument in node.args:
                if not isinstance(argument, ast.Dict):
                    writes.append(
                        Write(path, node.lineno, "*", None, "values_mapping_unknown")
                    )
                    continue
                for key, value_node in zip(argument.keys, argument.values):
                    if key is None:
                        writes.append(
                            Write(path, node.lineno, "*", None, "values_mapping_unknown")
                        )
                        continue
                    resolved_field = _value(key, constants)
                    if resolved_field in _FIELDS:
                        value = _value(value_node, constants)
                        writes.append(
                            Write(
                                path,
                                node.lineno,
                                str(resolved_field),
                                None if value is _UNKNOWN else value,
                                "values_mapping_unknown"
                                if value is _UNKNOWN
                                else "values_mapping",
                            )
                        )
                    elif resolved_field is _UNKNOWN:
                        writes.append(
                            Write(path, node.lineno, "*", None, "values_mapping_unknown")
                        )
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
        helper_target = (
            any(is_item_target(argument) for argument in node.args)
            or any(is_item_target(keyword.value) for keyword in node.keywords)
            or isinstance(node.func, ast.Attribute)
            and is_item_target(node.func.value)
        )
        if helper_target and not constructor_call and not values_call:
            if any(keyword.arg is None for keyword in node.keywords):
                writes.append(Write(path, node.lineno, "*", None, "helper_splat"))
            for keyword in node.keywords:
                if keyword.arg in _FIELDS:
                    value = _value(keyword.value, constants)
                    writes.append(
                        Write(
                            path,
                            node.lineno,
                            keyword.arg,
                            None if value is _UNKNOWN else value,
                            "helper_unknown" if value is _UNKNOWN else "helper",
                        )
                    )
    return writes


def _app_writes() -> list[Write]:
    writes: list[Write] = []
    for path in APP_ROOT.rglob("*.py"):
        writes.extend(classify_writes(path.read_text(), path.relative_to(APP_ROOT)))
    return writes


def _guarded_dispatch_write_lines(source: str | None = None) -> tuple[set[int], list[Write]]:
    """Check each payload before allowing the conditional SQL forwarding helper.

    Unknown helpers and unknown mappings remain forbidden. This exception binds
    to one helper in one module, and checks both alternatives of a launch result.
    """
    path = APP_ROOT / "services/github_dispatch_service.py"
    tree = ast.parse(path.read_text() if source is None else source)
    service = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                   and node.name == "GithubDispatchService")
    methods = [node for node in service.body if isinstance(node, ast.AsyncFunctionDef)]
    helper = next(node for node in methods if node.name == "_update_current_item")
    assert helper.args.kwarg.arg == "values"
    forwarding = [node for node in ast.walk(helper) if isinstance(node, ast.Call)
                  and any(keyword.arg is None for keyword in node.keywords)]
    assert len(forwarding) == 1
    forward = forwarding[0]
    assert isinstance(forward.func, ast.Attribute) and forward.func.attr == "values"
    assert [keyword.arg for keyword in forward.keywords] == [None, "updated_at"]
    assert isinstance(forward.keywords[0].value, ast.Name)
    assert forward.keywords[0].value.id == "values"
    allowed_lines = {forward.lineno}
    payload_writes: list[Write] = []

    def check_value(field: str, value: ast.expr) -> None:
        if field not in _FIELDS:
            return
        choices = [value.body, value.orelse] if isinstance(value, ast.IfExp) else [value]
        namespace = {
            "dispatch_status": DISPATCH_STATUSES,
            "escalation_reason": ESCALATION_REASONS | {None},
            # Existing routing refusal; PR2 queues use PENDING_REASONS.
            "pending_reason": PENDING_REASONS | {None, "leader_unavailable"},
        }[field]
        for choice in choices:
            assert isinstance(choice, ast.Constant), (field, ast.dump(choice))
            assert choice.value in namespace, (field, choice.value)
            payload_writes.append(Write(Path("services/github_dispatch_service.py"),
                                        choice.lineno, field, choice.value, "guarded_payload"))

    for method in methods:
        for node in ast.walk(method):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "self"
                    and node.func.attr == "_update_current_item"):
                continue
            for keyword in node.keywords:
                if keyword.arg is not None:
                    check_value(keyword.arg, keyword.value)
                    continue
                assert isinstance(keyword.value, ast.Name)
                name = keyword.value.id
                assignments = [part for part in ast.walk(method)
                               if isinstance(part, ast.Assign)
                               and any(isinstance(target, ast.Name) and target.id == name
                                       for target in part.targets)]
                assert len(assignments) == 1
                payload = assignments[0].value
                assert isinstance(payload, ast.Call) and isinstance(payload.func, ast.Name)
                assert payload.func.id == "dict" and not payload.args
                for entry in payload.keywords:
                    assert entry.arg is not None
                    check_value(entry.arg, entry.value)
                for part in ast.walk(method):
                    if isinstance(part, ast.Subscript) and isinstance(part.value, ast.Name) \
                            and part.value.id == name:
                        assert isinstance(part.ctx, ast.Store)
                        assert isinstance(part.slice, ast.Constant)
                        assert part.slice.value not in _FIELDS
                    if isinstance(part, ast.Attribute) and isinstance(part.value, ast.Name) \
                            and part.value.id == name:
                        assert method.name == "prepare_attempt" and part.attr == "items"
                    if isinstance(part, ast.Call):
                        assert not any(isinstance(arg, ast.Name) and arg.id == name
                                       for arg in part.args)
            allowed_lines.add(node.lineno)
    return allowed_lines, payload_writes


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
                "_escalate_current_item",
            }:
                continue
            reason_index = {
                "_apply_escalation": 1,
                "_escalate_current_item": 3,
            }.get(node.func.attr, 2)
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
FIELD = "dispatch_status"
import sqlalchemy as sa
from sqlalchemy import update as sql_update
from app.models import database as models
item.dispatch_status = CONST
item_alias = item
item.pending_reason: str = dynamic
GithubWorkItem(dispatch_status="failed")
models.GithubWorkItem(pending_reason="queued_no_workspace")
GithubWorkItem(**payload)
update(GithubWorkItem).values(escalation_reason="plan_blocked")
sa.update(models.GithubWorkItem).values(pending_reason="queued_auth_mode_unresolved")
update(GithubWorkItem).values({FIELD: "merged"})
update(GithubWorkItem).values(**payload)
statement = update(GithubWorkItem)
aliased = statement.where(True)
aliased.values(payload)
sql_statement = sql_update(models.GithubWorkItem)
sql_alias = sql_statement.where(True)
sql_alias.values(pending_reason="queued_slot_busy")
setattr(item, FIELD, "merged")
setattr(item, dynamic_field, "merged")
setattr(cache_entry, dynamic_field, "merged")
mutate(item, dispatch_status="verifying")
mutate(item, **payload)
mutate(subject=item_alias, escalation_reason="plan_blocked")
Unrelated(**payload)
"""
    )
    assert {(write.field, write.form) for write in writes} == {
        ("dispatch_status", "assignment"),
        ("pending_reason", "assignment_unknown"),
        ("dispatch_status", "constructor"),
        ("pending_reason", "constructor"),
        ("*", "item_splat"),
        ("escalation_reason", "values"),
        ("pending_reason", "values"),
        ("dispatch_status", "values_mapping"),
        ("*", "values_splat"),
        ("*", "values_mapping_unknown"),
        ("dispatch_status", "setattr"),
        ("*", "setattr_unknown"),
        ("*", "setattr_other_unknown"),
        ("dispatch_status", "helper"),
        ("escalation_reason", "helper"),
        ("*", "helper_splat"),
    }
    assert (
        "pending_reason",
        "queued_slot_busy",
        "values",
    ) in {(write.field, write.value, write.form) for write in writes}
    assert (
        "escalation_reason",
        "plan_blocked",
        "helper",
    ) in {(write.field, write.value, write.form) for write in writes}


def test_whole_tree_writers_stay_inside_declared_namespaces():
    writes = _app_writes()
    guarded_lines, payload_writes = _guarded_dispatch_write_lines()
    writes.extend(payload_writes)
    forbidden = [
        write
        for write in writes
        if write.form
        in {
            "setattr",
            "item_splat",
            "values_splat",
            "values_mapping_unknown",
            "constructor_unknown",
            "helper_splat",
            "helper_unknown",
            "helper",
        }
        and not (write.path.as_posix() == "services/github_dispatch_service.py"
                 and write.line in guarded_lines)
    ]
    assert forbidden == []

    dynamic_setattr = [write for write in writes if write.form == "setattr_unknown"]
    assert len(dynamic_setattr) == 2
    assert all(write.path.as_posix() == "services/github_dispatch_service.py"
               for write in dynamic_setattr)

    unrelated_dynamic_setattr = [
        write for write in writes if write.form == "setattr_other_unknown"
    ]
    assert sorted(write.path.as_posix() for write in unrelated_dynamic_setattr) == [
        "services/agent_team_service.py",
        "services/mcp_service.py",
    ]

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
    assert sorted(write.path.as_posix() for write in dynamic_dispatch) == [
        "services/github_verification_service.py",
        "services/github_verification_service.py",
        "services/github_verification_service.py",
        "services/github_verification_service.py",
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
    conditional_escalation_writes = [
        write
        for write in writes
        if write.field == "escalation_reason"
        and write.form == "values"
        and write.value is not None
    ]
    assert [
        (write.path.as_posix(), write.value)
        for write in conditional_escalation_writes
    ] == [
        (
            "services/github_dispatch_service.py",
            "approval_rounds_exhausted",
        ),
        (
            "services/github_dispatch_service.py",
            "continuation_revision_exhausted",
        ),
        (
            "api/v1/factory_maintenance.py",
            "integration_update_conflict",
        ),
    ]
    direct_literals = [write for write in writes if write.field == "escalation_reason"
                       and write.form == "assignment" and write.value is not None]
    assert [(write.path.as_posix(),write.value) for write in direct_literals] == [
        ("services/github_dispatch_service.py","continuation_revision_exhausted"),
        ("services/owner_observation_pause.py","owner_observation_unavailable")
    ]
    assert _escalation_call_reasons() | {write.value for write in direct_literals} | {
        write.value for write in conditional_escalation_writes
    } == ESCALATION_REASONS

    pending_literals = {
        write.value
        for write in writes
        if write.field == "pending_reason" and write.value is not None
    }
    assert PENDING_REASONS <= pending_literals


@pytest.mark.parametrize(("original", "replacement"), [
    ('dispatch_status="failed" if failed else "dispatched"',
     'dispatch_status="invented" if failed else "dispatched"'),
    ('dispatch_status="failed" if failed else "dispatched"',
     'dispatch_status=dynamic_status'),
    ('pending_reason="queued_low_memory"', 'pending_reason="invented"'),
    ('values["dispatched_at"] = datetime.utcnow()',
     'values["dispatch_status"] = dynamic_status'),
    ('values["dispatched_at"] = datetime.utcnow()',
     'values.update(dynamic_values)'),
])
def test_guarded_payload_audit_rejects_unknown_states_and_mappings(original, replacement):
    source = (APP_ROOT / "services/github_dispatch_service.py").read_text()
    changed = source.replace(original, replacement)
    assert changed != source
    with pytest.raises(AssertionError):
        _guarded_dispatch_write_lines(changed)


def test_apply_escalation_rejects_an_undeclared_reason():
    item = GithubWorkItem(dispatch_status="dispatched")

    with pytest.raises(ValueError, match="undeclared escalation reason"):
        github_dispatch_service._apply_escalation(item, "invented_reason")


async def _behavior_context(
    db,
    *,
    auth_mode: str = "ambient",
    with_workspace: bool = True,
):
    preset = AgentTeamPreset(name=f"namespace-{auth_mode}", created_by="test")
    db.add(preset)
    await db.flush()
    slot = AgentTeamSlot(
        preset_id=preset.id,
        position=0,
        display_name="Owner",
        provider="codex-cli",
        repo_id="r",
        repo_path="/tmp/r",
        repo_name="r",
    )
    db.add(slot)
    await db.flush()
    scope = TeamGithubScope(
        preset_id=preset.id,
        repo_owner="o",
        repo_name="r",
        repo_path="/tmp/r",
        base_ref="origin/master",
        github_auth_mode=auth_mode,
        github_app_installation_id=55 if auth_mode == "app" else None,
    )
    db.add(scope)
    await db.flush()
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=1,
        issue_title="Namespace behavior",
        issue_url="https://github.com/o/r/issues/1",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=slot.id,
        dispatch_nonce="nonce",
        dispatch_head_ref="deck/slot-1/issue-1/nonce",
        dispatch_base_ref="origin/master",
    )
    db.add(item)
    await db.flush()
    if with_workspace:
        db.add(
            GithubWorkspace(
                scope_id=scope.id,
                path=f"/tmp/namespace-{item.id}",
                leased_item_id=item.id,
                lease_token="lease",
            )
        )
    await db.commit()
    return scope, item


def _behavior_pull(item, *, state="open", merged_at=None, number=7):
    return {
        "number": number,
        "state": state,
        "merged_at": merged_at,
        "draft": True,
        "head": {
            "sha": "sha",
            "ref": item.dispatch_head_ref,
            "repo": {"full_name": "o/r"},
        },
        "base": {"ref": "master", "repo": {"full_name": "o/r"}},
        "user": {"login": "deck-app[bot]"},
    }


class _BehaviorClient:
    def __init__(self, pull, *, pulls=None, created=None):
        self.pull = pull
        self.pulls = pulls
        self.created = created

    async def get_pull(self, owner, repo, pr_number):
        return dict(self.pull)

    async def get_ref(self, owner, repo, head, *, token):
        return {"ref": f"refs/heads/{head}", "object": {"sha": "sha"}}

    async def get_repository(self, owner, repo, *, token=None):
        return {"default_branch": "master"}

    async def list_pulls_for_head(
        self,
        owner,
        repo,
        *,
        head,
        base,
        state,
        token,
    ):
        return [dict(pull) for pull in (self.pulls or [])]

    async def create_pull(self, owner, repo, **kwargs):
        return dict(self.created or self.pull)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "expected_status", "expected_escalation"),
    [
        ("pr_ready_open", "verifying", None),
        ("pr_ready_merged", "merged", None),
        ("pr_ready_closed", "escalated", "pr_closed_unmerged"),
        ("pr_ready_no_match", "verifying", None),
        ("pr_ready_two_open", "dispatched", None),
        ("pr_ready_unclassifiable", "dispatched", None),
        ("pr_opened_open", "verifying", None),
        ("pr_opened_merged", "merged", None),
        ("pr_opened_closed", "escalated", "pr_closed_unmerged"),
        ("verifier_closed", "escalated", "pr_closed_unmerged"),
        ("auth_mode_refusal", "dispatched", None),
        ("no_workspace_refusal", "dispatched", None),
    ],
)
async def test_pr2_behavioral_writers_stay_in_declared_namespaces(
    db, monkeypatch, case, expected_status, expected_escalation
):
    auth_mode = "app" if case.startswith("pr_ready_") or case == "no_workspace_refusal" else "ambient"
    if case == "auth_mode_refusal":
        auth_mode = "ambient"
    scope, item = await _behavior_context(
        db,
        auth_mode=auth_mode,
        with_workspace=case != "no_workspace_refusal",
    )
    monkeypatch.setattr(
        "app.services.github_verification_service.settings.github_app_bot_login",
        "deck-app[bot]",
    )
    monkeypatch.setattr(
        github_app_auth_service,
        "require_configuration",
        lambda **_kwargs: None,
    )

    async def mint(*_args, **_kwargs):
        return "app-token"

    monkeypatch.setattr(github_app_auth_service, "mint_repository_token", mint)

    if case.startswith("pr_ready_"):
        if case == "pr_ready_no_match":
            pulls = []
        elif case == "pr_ready_two_open":
            pulls = [
                _behavior_pull(item, number=7),
                _behavior_pull(item, number=8),
            ]
        elif case == "pr_ready_unclassifiable":
            pulls = [_behavior_pull(item, state="unknown")]
        elif case == "pr_ready_merged":
            pulls = [
                _behavior_pull(
                    item,
                    state="closed",
                    merged_at="2026-08-14T12:00:00Z",
                )
            ]
        elif case == "pr_ready_closed":
            pulls = [_behavior_pull(item, state="closed")]
        else:
            pulls = [_behavior_pull(item)]
        behavior_client = _BehaviorClient(
            _behavior_pull(item, number=9),
            pulls=pulls,
            created=_behavior_pull(item, number=9),
        )
        if case == "pr_ready_two_open":
            with pytest.raises(ValueError, match="Multiple open pull requests"):
                await github_verification_service.report_pr_ready(
                    db,
                    item,
                    scope,
                    item.dispatch_head_ref,
                    "lease",
                    behavior_client,
                )
        elif case == "pr_ready_unclassifiable":
            with pytest.raises(ValueError, match="unclassifiable"):
                await github_verification_service.report_pr_ready(
                    db,
                    item,
                    scope,
                    item.dispatch_head_ref,
                    "lease",
                    behavior_client,
                )
        elif case == "pr_ready_closed":
            with pytest.raises(ValueError, match="closed without merge"):
                await github_verification_service.report_pr_ready(
                    db,
                    item,
                    scope,
                    item.dispatch_head_ref,
                    "lease",
                    behavior_client,
                )
        else:
            await github_verification_service.report_pr_ready(
                db,
                item,
                scope,
                item.dispatch_head_ref,
                "lease",
                behavior_client,
            )
    elif case.startswith("pr_opened_"):
        if case == "pr_opened_merged":
            pull = _behavior_pull(
                item,
                state="closed",
                merged_at="2026-08-14T12:00:00Z",
            )
        elif case == "pr_opened_closed":
            pull = _behavior_pull(item, state="closed")
        else:
            pull = _behavior_pull(item)
        await github_verification_service.report_pr_opened(
            db,
            item,
            scope,
            7,
            _BehaviorClient(pull),
        )
    elif case == "verifier_closed":
        item.pr_number = 7
        item.dispatch_status = "verifying"
        await db.commit()
        await github_verification_service._verify_item(
            db,
            scope,
            item,
            _BehaviorClient(_behavior_pull(item, state="closed")),
        )
    else:
        expected_error = (
            "requires GitHub App authentication"
            if case == "auth_mode_refusal"
            else "workspace_lease_changed"
        )
        with pytest.raises(ValueError, match=expected_error):
            await github_verification_service.report_pr_ready(
                db,
                item,
                scope,
                item.dispatch_head_ref,
                "lease",
                _BehaviorClient(_behavior_pull(item)),
            )

    await db.refresh(item)
    assert item.dispatch_status == expected_status
    assert item.dispatch_status in DISPATCH_STATUSES
    assert item.escalation_reason == expected_escalation
    if item.escalation_reason is not None:
        assert item.escalation_reason in ESCALATION_REASONS
    if item.pending_reason is not None and item.pending_reason.startswith("queued_"):
        assert item.pending_reason in PENDING_REASONS
