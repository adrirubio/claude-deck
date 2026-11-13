"""The hosted real-sudo regression for the cross-user terminal attach (#880, moved out of #877).

It uses real `sudo` against a disposable OS user, so it runs ONLY on an ephemeral GitHub-hosted Linux
runner, in the dedicated job "Hosted real-sudo attach" (ubuntu-24.04). The full backend suite does
not collect this file. There is no other way to turn it on. On a hosted runner a missing prerequisite
FAILS the test; it never skips there. Off a hosted runner it is skipped, by design.

The setup, the cleanup controls and the sudo attestation are in real_sudo_support.py, and the
fake-command controls are in test_cc_bridge_sudo_lifecycle.py.
"""
import asyncio
import logging

import pytest

from app.services.cc_bridge import pty_relay
from tests.real_sudo_support import (
    WRONG_SETUP_MARKERS,
    DisposableAgent,
    attest_sudo,
    format_sudo_facts,
    hosted_runner_only,
    require_original_sudo,
    wait_for_terminal_bytes,
)
from tests.test_cc_bridge_pty_relay import FIXED_ATTACH_ERROR, FrameWebSocket


@pytest.fixture
def disposable_agent():
    made = []

    def make() -> DisposableAgent:
        agent = DisposableAgent()
        made.append(agent)  # registered first, so a failed setup is still cleaned up
        agent.create()
        return agent

    yield make
    failures = []
    for agent in made:
        try:
            agent.remove()
        except AssertionError as error:
            failures.append(str(error))
    assert not failures, "; ".join(failures)



@hosted_runner_only
@pytest.mark.asyncio
async def test_real_sudo_under_production_capabilities_needs_use_pty_off_for_the_attach_command(
    monkeypatch, disposable_agent, caplog
):
    # The claim is production's sudo. Attest it before anything privileged is created, and stop on a mismatch.
    facts = attest_sudo()
    print(format_sudo_facts(facts))
    require_original_sudo(facts)

    agent = disposable_agent()
    monkeypatch.setattr(pty_relay, "TMUX_BINARY", agent.launcher)

    # Phase 1, the defect the real trial found (run H2): with use_pty the attach cannot start.
    agent.install_rules(use_pty=True)
    agent.attest()
    websocket = FrameWebSocket()
    relay = pty_relay.PtyRelay("test:real-sudo-use-pty", read_only=False)
    with caplog.at_level(logging.WARNING, logger=pty_relay.logger.name):
        await asyncio.wait_for(relay.run(websocket), timeout=60)
    logged = "\n".join(r.getMessage() for r in caplog.records if r.name == pty_relay.logger.name)

    # The browser frame is fixed and generic, so it proves nothing about the cause. The cause is
    # proven only by the backend log, which keeps sudo's own text out of the client payload.
    assert "unable to allocate pty" in logged, f"the attach did not fail for the intended cause. Log: {logged!r}"
    for marker in WRONG_SETUP_MARKERS:
        assert marker not in logged, f"the attach failed for the wrong reason ({marker!r}). Log: {logged!r}"
    assert b"ready" not in websocket.sent, "the attach started although use_pty is on and CAP_CHOWN is missing"
    assert websocket.frames == [{"type": "error", "message": FIXED_ATTACH_ERROR}]
    assert websocket.close_code == 4000
    assert b"sudo" not in websocket.sent and b"allocate" not in websocket.sent

    # Phase 2, the supported setup. Same user, programs, launcher, bounding set and session.
    # Only the command-scoped use_pty line of the rules changes.
    agent.install_rules(use_pty=False)
    agent.attest()
    websocket = FrameWebSocket()
    relay = pty_relay.PtyRelay("test:real-sudo-no-use-pty", read_only=False)
    task = asyncio.create_task(relay.run(websocket))
    try:
        await wait_for_terminal_bytes(websocket, b"ready")
        for rows, cols in ((45, 160), (24, 80)):  # full screen, then back
            relay.resize(rows, cols)
            # The size the attached program reports, not only the resize that was sent.
            await wait_for_terminal_bytes(websocket, f"WINCH:{rows} {cols}".encode())
        assert b"sudo" not in websocket.sent
        assert websocket.frames == []
    finally:
        websocket.finish()
        await asyncio.wait_for(task, timeout=60)

