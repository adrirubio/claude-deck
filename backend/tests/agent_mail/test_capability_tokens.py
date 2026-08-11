"""Spec §3.7 — capability token tests for PR0."""

import pytest
from sqlalchemy import text

from app.config import settings
from app.models.database import AgentPaneBinding, MailAgentSession


def test_capability_token_settings_default_to_grace_mode():
    """PR0 ships enforcement off, so an unconfigured deploy behaves exactly as before."""
    assert settings.mail_capability_tokens_required is False
    assert settings.operator_token == ""


def test_session_model_carries_the_three_binding_columns():
    columns = MailAgentSession.__table__.columns
    assert columns["capability_token_hash"].nullable is True
    assert columns["bound_pane_pid"].nullable is True
    assert columns["bound_pane_proc_start"].nullable is True


def test_pane_binding_table_is_unique_on_pid_and_proc_start():
    names = {column.name for column in AgentPaneBinding.__table__.columns}
    assert names == {
        "id",
        "pane_pid",
        "pane_proc_start",
        "slot_id",
        "preset_id",
        "tmux_target",
        "created_at",
    }
    unique = {
        tuple(sorted(column.name for column in constraint.columns))
        for constraint in AgentPaneBinding.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("pane_pid", "pane_proc_start") in unique


@pytest.mark.asyncio
async def test_pane_binding_round_trips(db):
    """create_all makes the table; a row survives a raw-SQL read-back."""
    db.add(
        AgentPaneBinding(
            pane_pid=4242,
            pane_proc_start="123456",
            slot_id=None,
            preset_id=None,
            tmux_target="deck-team:0.1",
        )
    )
    await db.commit()

    row = (
        await db.execute(
            text(
                "SELECT pane_pid, pane_proc_start, tmux_target "
                "FROM agent_pane_bindings WHERE pane_pid = 4242"
            )
        )
    ).first()
    assert row == (4242, "123456", "deck-team:0.1")
