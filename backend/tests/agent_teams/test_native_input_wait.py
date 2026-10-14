"""Match captured active prompts without exposing screen contents."""
from pathlib import Path

import pytest

SCREENS = Path(__file__).resolve().parents[1] / "fixtures/native_screens"


@pytest.mark.parametrize("provider,name,expected", [
    ("claude-code", "claude-question-form.txt", "question"),
    ("claude-code", "claude-question-form.ansi", "question"),
    ("claude-code", "claude-question-form-two-questions.txt", "question"),
    ("claude-code", "claude-trust-prompt.txt", "trust"),
    ("claude-code", "claude-trust-prompt.ansi", "trust"),
    ("claude-code", "claude-trust-prompt-with-permissions.txt", "trust"),
    ("codex-cli", "codex-sign-in.txt", "sign_in"),
    ("codex-cli", "codex-sign-in.ansi", "sign_in"),
    ("claude-code", "claude-idle-after-declined-question.txt", "clear"),
    ("codex-cli", "codex-idle-prompt.txt", "clear"),
    ("muse-cli", "muse-question-form.txt", "question"),
    ("muse-cli", "muse-idle-prompt.txt", "clear"),
])
def test_captured_native_input_screens(provider, name, expected):
    from app.services.agent_activity_service import recognize_native_input_wait
    assert recognize_native_input_wait(provider, (SCREENS / name).read_text()) == expected


@pytest.mark.parametrize("provider,name", [
    ("muse-cli", "claude-question-form.txt"), ("muse-cli", "codex-idle-prompt.txt"),
    ("codex-cli", "muse-idle-prompt.txt"),
])
def test_one_harness_screen_is_not_another_harness_wait(provider, name):
    from app.services.agent_activity_service import recognize_native_input_wait
    assert recognize_native_input_wait(provider, (SCREENS / name).read_text()) is None


@pytest.mark.parametrize("provider,screen", [("pi-cli", ""), ("claude-code", ""), ("codex-cli", "Unrecognized screen.")])
def test_unknown_native_screen_has_no_wait_claim(provider, screen):
    from app.services.agent_activity_service import recognize_native_input_wait
    assert recognize_native_input_wait(provider, screen) is None


@pytest.fixture
def captured_pane(monkeypatch):
    from types import SimpleNamespace
    from app.services import agent_activity_service as activity
    calls, identity, process = [], ["41000:%8", "41000:%8"], [("S", "27"), ("S", "27")]
    screen = (SCREENS / "claude-question-form.txt").read_text()

    def run(args, **options):
        calls.append(args)
        assert options["timeout"] == .5
        return SimpleNamespace(returncode=0, stdout=screen if args[1] == "capture-pane" else identity.pop(0))

    monkeypatch.setattr(activity.subprocess, "run", run)
    monkeypatch.setattr(activity, "_process", lambda _: process.pop(0))
    binding = activity.ActivityBinding(41000, "27", "/synthetic/project", tmux_target="%8", binding_id=1)
    return activity, binding, calls, identity, process


def test_capture_reads_visible_current_pane_only(captured_pane):
    activity, binding, calls, _, _ = captured_pane
    assert activity._capture_native_input_wait("claude-code", binding) == "question"
    assert calls[1] == ["tmux", "capture-pane", "-p", "-t", "%8"]
    assert all("send-keys" not in args for args in calls)


@pytest.mark.parametrize("change", ["pid", "pane", "start", "stopped"])
def test_capture_refuses_changed_or_stopped_pane(captured_pane, change):
    activity, binding, _, identity, process = captured_pane
    if change == "pid":
        identity[0] = "41001:%8"
    elif change == "pane":
        identity[1] = "41000:%9"
    elif change == "start":
        process[1] = ("S", "28")
    else:
        process[0] = ("T", "27")
    assert activity._capture_native_input_wait("claude-code", binding) is None


async def wait_team(db, *, supervised=True):
    from app.models.database import AgentPaneBinding, AgentTeamPreset, AgentTeamSlot, MailAgentSession, MailExternalActor, MailTeamMember
    team = AgentTeamPreset(name="Wait fixture")
    actor = MailExternalActor(actor_key="wait-actor", display_name="Supervisor", kind="external_tool", token_hash="synthetic-hash")
    db.add_all([team, actor]); await db.flush()
    slot = AgentTeamSlot(preset_id=team.id, display_name="Worker", provider="claude-code",
        repo_path="/synthetic/project", repo_id="fixture", repo_name="fixture")
    leader = AgentTeamSlot(preset_id=team.id, display_name="Leader", provider="codex-cli",
        repo_path="/synthetic/project", repo_id="fixture", repo_name="fixture")
    db.add_all([slot, leader]); await db.flush()
    team.leader_slot_id = leader.id
    team.supervisor_actor_id = actor.id if supervised else None
    members = [MailTeamMember(identity_key=f"wait-{s.id}", repo_id="fixture", repo_name="fixture",
        repo_path="/synthetic/project", display_name=s.display_name, team_preset_id=team.id, team_slot_id=s.id)
        for s in (slot, leader)]
    db.add_all(members); await db.flush()
    binding = AgentPaneBinding(pane_pid=41000, pane_proc_start="27", slot_id=slot.id, preset_id=team.id, tmux_target="%8")
    session = MailAgentSession(member_id=members[0].id, provider="claude-code", source="mcp", session_key="wait-session",
        team_slot_id=slot.id, team_preset_id=team.id, bound_pane_pid=41000, bound_pane_proc_start="27",
        cwd="/synthetic/project", capability_token_hash="synthetic-hash", mailbox_status="connected")
    db.add_all([binding, session]); await db.commit()
    return team, actor, slot, binding, session, members[1]


async def record_wait(db, team, slot, binding, reason, *, now=None):
    from datetime import datetime, timezone
    from app.services import agent_activity_service as activity
    inputs = await activity._team_inputs(db, team.id)
    metadata = [{"input_wait_known": True, "input_wait_binding_id": binding.id, "input_wait_reason": reason}
                if entry[0] == slot.id else {} for entry in inputs]
    await activity._record_input_waits(db, team.id, inputs, metadata, {entry[0]: entry for entry in inputs},
                                     now=now or datetime.now(timezone.utc))
    await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("supervised", [True, False])
async def test_wait_notice_is_persistent_and_routes_to_current_supervisor_or_leader(db, supervised):
    from sqlalchemy import select
    from app.models.database import MailMessage, MailReceipt
    from app.services.agent_team_supervisor_service import supervisor_inbox, require_supervisor_thread
    team, actor, slot, binding, session, leader = await wait_team(db, supervised=supervised)
    await record_wait(db, team, slot, binding, "question")
    await record_wait(db, team, slot, binding, "trust")
    messages = (await db.scalars(select(MailMessage))).all()
    assert len(messages) == 1
    message = messages[0]
    assert message.sender_member_id is None
    assert message.payload["reason"] == "question"
    assert message.payload["slot_id"] == slot.id
    assert "synthetic/project" not in message.body_markdown
    if supervised:
        assert message.recipient_member_id is None
        assert message.payload["supervisor_actor_id"] == actor.id
        assert len(await supervisor_inbox(db, actor)) == 1
        await require_supervisor_thread(db, actor, message)
    else:
        assert message.recipient_member_id == leader.id
        assert await db.scalar(select(MailReceipt.id).where(MailReceipt.message_id == message.id, MailReceipt.member_id == leader.id))
    session.session_key = "wait-new-session"
    await db.commit()
    await record_wait(db, team, slot, binding, "question")
    assert len((await db.scalars(select(MailMessage))).all()) == 1
    await record_wait(db, team, slot, binding, None)
    await db.refresh(binding)
    assert binding.waiting_input_reason == "question"
    await record_wait(db, team, slot, binding, "clear")
    await db.refresh(binding)
    assert binding.waiting_input_reason is None
    await record_wait(db, team, slot, binding, "sign_in")
    assert len((await db.scalars(select(MailMessage))).all()) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["closed", "retired", "slot", "member", "target", "disabled"])
async def test_notice_storage_rechecks_authenticated_current_binding(db, change):
    from datetime import datetime, timezone
    from sqlalchemy import select, update
    from app.models.database import AgentPaneBinding, AgentTeamSlot, MailAgentSession, MailMessage, MailPaneLifecycle, MailTeamMember
    from app.services import agent_activity_service as activity
    team, _, slot, binding, session, _ = await wait_team(db)
    inputs = await activity._team_inputs(db, team.id)
    if change == "closed":
        await db.execute(update(MailAgentSession).where(MailAgentSession.id == session.id).values(closed_at=datetime.utcnow()))
    elif change == "retired":
        db.add(MailPaneLifecycle(pane_pid=41000, pane_proc_start="27", retired_at=datetime.utcnow()))
    elif change == "slot":
        await db.execute(update(AgentPaneBinding).where(AgentPaneBinding.id == binding.id).values(slot_id=None))
    elif change == "target":
        await db.execute(update(AgentPaneBinding).where(AgentPaneBinding.id == binding.id).values(tmux_target="%9"))
    elif change == "disabled":
        await db.execute(update(AgentTeamSlot).where(AgentTeamSlot.id == slot.id).values(enabled=False))
    else:
        db.add(MailTeamMember(identity_key="wait-replacement", repo_id="fixture", repo_name="fixture",
            repo_path="/synthetic/project", display_name="Replacement", team_preset_id=team.id, team_slot_id=slot.id))
    await db.commit()
    metadata = [{"input_wait_known": True, "input_wait_binding_id": binding.id, "input_wait_reason": "question"}
                if entry[0] == slot.id else {} for entry in inputs]
    await activity._record_input_waits(db, team.id, inputs, metadata, {entry[0]: entry for entry in inputs},
                                     now=datetime.now(timezone.utc))
    await db.commit()
    assert not (await db.scalars(select(MailMessage))).all()
    await db.refresh(binding)
    assert binding.waiting_input_reason is None


def test_bound_wait_is_safe_without_a_conversation_id(monkeypatch):
    from datetime import datetime, timezone
    from app.services import agent_activity_service as activity
    monkeypatch.setattr(activity, "_process", lambda _: ("S", "27"))
    monkeypatch.setattr(activity, "_capture_native_input_wait", lambda *args: "trust")
    binding = activity.ActivityBinding(41000, "27", "/synthetic/project", tmux_target="%8", binding_id=1)
    metadata = {}
    observed = activity._observe(1, "claude-code", None, [binding], False, datetime.now(timezone.utc), provenance=metadata)
    assert observed.waiting_input.reason == "trust"
    assert observed.state == "idle"
    assert "synthetic/project" not in observed.model_dump_json()
    assert metadata == {"input_wait_known": True, "input_wait_reason": "trust", "input_wait_binding_id": 1}
    metadata.clear()
    observed = activity._observe(1, "claude-code", None, [binding], True, datetime.now(timezone.utc), provenance=metadata)
    assert observed.waiting_input is None and not metadata
    observed = activity._observe(1, "claude-code", None, [], False, datetime.now(timezone.utc))
    assert observed.waiting_input is None


@pytest.mark.asyncio
async def test_failed_notice_transaction_preserves_empty_latch(db, monkeypatch):
    from sqlalchemy import select
    from app.models.database import AgentPaneBinding, MailMessage
    team, _, slot, binding, _, _ = await wait_team(db)
    binding_id = binding.id
    original = db.flush

    async def refused(*args, **kwargs):
        if any(isinstance(row, MailMessage) for row in db.new):
            raise RuntimeError("fixture_store_refused")
        return await original(*args, **kwargs)

    monkeypatch.setattr(db, "flush", refused)
    with pytest.raises(RuntimeError, match="fixture_store_refused"):
        await record_wait(db, team, slot, binding, "question")
    await db.rollback()
    stored = await db.get(AgentPaneBinding, binding_id)
    assert stored.waiting_input_reason is None
    assert not (await db.scalars(select(MailMessage))).all()


@pytest.mark.asyncio
async def test_native_notice_requires_current_bound_supervisor(db):
    from sqlalchemy import select
    from app.models.database import MailExternalActor, MailMessage
    from app.services.agent_team_supervisor_service import require_supervisor_thread, supervisor_inbox
    team, actor, slot, binding, _, _ = await wait_team(db)
    await record_wait(db, team, slot, binding, "question")
    message = await db.scalar(select(MailMessage))
    foreign = MailExternalActor(actor_key="wait-foreign", display_name="Foreign", kind="external_tool", token_hash="synthetic-other")
    db.add(foreign); await db.commit()
    with pytest.raises(PermissionError, match="supervisor_actor_not_bound"):
        await require_supervisor_thread(db, foreign, message)
    team.supervisor_actor_id = foreign.id
    await db.commit()
    assert await supervisor_inbox(db, foreign) == []
    with pytest.raises(PermissionError, match="supervisor_actor_not_bound"):
        await require_supervisor_thread(db, actor, message)


@pytest.mark.asyncio
async def test_older_capture_cannot_restore_a_wait_after_a_newer_idle_screen(db):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from app.models.database import MailMessage
    team, _, slot, binding, _, _ = await wait_team(db)
    now = datetime.now(timezone.utc)
    await record_wait(db, team, slot, binding, "question", now=now)
    await record_wait(db, team, slot, binding, "clear", now=now + timedelta(seconds=2))
    await record_wait(db, team, slot, binding, "question", now=now + timedelta(seconds=1))
    assert len((await db.scalars(select(MailMessage))).all()) == 1
    await db.refresh(binding)
    assert binding.waiting_input_reason is None
