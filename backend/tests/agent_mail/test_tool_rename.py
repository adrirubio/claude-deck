"""T-T1: the exact section-4.3 surface, without aliases or invented tools."""
import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError


# Independent golden list transcribed from compatibility.md section 4.3.
PUBLIC_SUFFIXES = {
    "ack_continuation", "ack_message", "approve_work_item", "attach_image_to_bridge_session",
    "check_inbox", "create_handoff", "create_team", "decide_continuation",
    "get_backlog_coordination", "get_operator_action_contexts", "get_team_summary",
    "get_work_item_context", "launch_team", "list_bridge_attachments", "list_scope_revisions",
    "list_team", "list_teams", "list_work_items", "paste_bridge_attachment", "plan_team_launch",
    "prepare_operator_action_contexts", "prepare_work_remaining_summary", "render_github_summary",
    "reply", "report_backlog_assessment", "report_dispatch_status", "report_owner_followup",
    "request_context", "request_continuation", "request_work_item_approval", "retry_work_item",
    "send_message", "supervisor_checkin", "update_team_campaign", "update_team_parent_issue", "whoami",
}
PUBLIC_NAMES = {"synth_city_" + suffix for suffix in PUBLIC_SUFFIXES}
PRIVATE_NAME = "__synth_city_mail_close_generation"
# Section 4.4 rows 10–18, 32, 36, 42 and 46 are never callable tools.
NON_TOOL_SUFFIXES = {
    "read_inbox", "list_agents", "reserve_paths", "set_status", "check_path_conflicts",
    "http_error", "list_path_leases", "mailbox_mcp", "release_paths", "join_scope",
    "list_scopes", "reply_context", "update_expertise",
}


def load_shim(monkeypatch, provider):
    monkeypatch.setenv("SYNTH_CITY_PROVIDER", provider)
    location = Path(__file__).resolve().parents[2] / "mcp_shim/agent_mail_server.py"
    spec = importlib.util.spec_from_file_location("rename_contract_" + provider, location)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def no_http(*_args, **_kwargs):
        raise AssertionError("Tool-schema inspection and unknown names must not make HTTP requests")

    monkeypatch.setattr(module.httpx, "request", no_http)
    return module


@pytest.mark.parametrize("provider", ["codex-cli", "pi-cli"])
def test_t_t1_exact_public_and_pi_private_surface(monkeypatch, provider):
    shim = load_shim(monkeypatch, provider)
    tools = asyncio.run(shim.mcp.list_tools())
    expected = PUBLIC_NAMES | ({PRIVATE_NAME} if provider == "pi-cli" else set())
    assert len(PUBLIC_NAMES) == 36
    assert {tool.name for tool in tools} == expected
    assert len(tools) == len(expected)
    for tool in tools:
        assert not any("deck_" + suffix in tool.description for suffix in PUBLIC_SUFFIXES)


@pytest.mark.parametrize("provider", ["codex-cli", "pi-cli"])
def test_t_t1_old_names_and_historical_non_tools_are_unknown(monkeypatch, provider):
    shim = load_shim(monkeypatch, provider)
    refused = {"deck_" + suffix for suffix in PUBLIC_SUFFIXES}
    refused.add("__deck_mail_close_generation")
    refused |= {prefix + suffix for prefix in ("deck_", "synth_city_") for suffix in NON_TOOL_SUFFIXES}
    if provider != "pi-cli":
        refused.add(PRIVATE_NAME)

    async def check():
        for name in sorted(refused):
            with pytest.raises(ToolError, match="Unknown tool"):
                await shim.mcp.call_tool(name, {})

    asyncio.run(check())


def test_t_t1_new_name_dispatches_through_real_mcp_server(monkeypatch):
    shim = load_shim(monkeypatch, "codex-cli")
    monkeypatch.setattr(shim, "_guard", lambda: None)
    shim._state["member_id"] = 7
    monkeypatch.setattr(shim, "_counts", lambda: {})
    calls = []

    def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"ok": True, "data": {"acked": True}}

    monkeypatch.setattr(shim, "_request", request)
    result = asyncio.run(shim.mcp.call_tool("synth_city_ack_message", {"message_id": 19}))
    content = result[0] if isinstance(result, tuple) else result
    assert json.loads(content[0].text) == {"ok": True}
    assert calls == [("POST", "/messages/19/ack", {"json": {"member_id": 7}})]


def test_transport_error_codes_use_new_names(monkeypatch):
    shim = load_shim(monkeypatch, "codex-cli")
    assert shim._unreachable_result("synthetic offline")["error"]["code"] == "synth_city_unreachable"
    request = httpx.Request("GET", "http://fixture.invalid/")
    response = httpx.Response(502, text="synthetic unstructured failure", request=request)
    error = httpx.HTTPStatusError("synthetic failure", request=request, response=response)
    assert shim._http_error_result(error)["error"]["code"] == "synth_city_http_error"


def test_url_helper_and_status_field_are_paired():
    from app.models.schemas import AgentMailInstallStatus
    from app.services import agent_mail_install_service as install
    from app.services.pi_mail_readiness import pi_mail_environment

    assert "synth_city_url" in AgentMailInstallStatus.model_fields
    assert "deck_url" not in AgentMailInstallStatus.model_fields
    assert pi_mail_environment()["SYNTH_CITY_URL"] == install.synth_city_base_url()


@pytest.mark.parametrize("old_flag", [False, True])
def test_hook_url_flag_has_no_legacy_alias(monkeypatch, old_flag):
    from mcp_shim import agent_mail_hook as hook

    flag = "--deck-url" if old_flag else "--synth-city-url"
    monkeypatch.setattr(hook.sys, "argv", ["hook", flag, "http://fixture.invalid", "--event", "session-start"])
    monkeypatch.setattr(hook, "_read_payload", lambda: {})
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {})

    monkeypatch.setattr(hook.httpx, "post", post)
    if old_flag:
        with pytest.raises(SystemExit) as error:
            hook.main()
        assert error.value.code == 2 and calls == []
    else:
        assert hook.main() == 0
        assert calls == ["http://fixture.invalid/api/v1/agent-mail/hooks/session-start"]


@pytest.mark.parametrize("old_flag", [False, True])
def test_credential_url_flag_has_no_legacy_alias(monkeypatch, old_flag):
    from mcp_shim import git_credential_helper as helper

    monkeypatch.setattr(helper, "_read_credential_input", lambda: {})
    flag = "--deck-url" if old_flag else "--synth-city-url"
    args = [flag, "http://fixture.invalid", "--lease", "synthetic-lease", "store"]
    if old_flag:
        with pytest.raises(SystemExit) as error:
            helper.main(args)
        assert error.value.code == 2
    else:
        assert helper.main(args) == 0
