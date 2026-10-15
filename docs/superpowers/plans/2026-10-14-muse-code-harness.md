# Muse Code Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deck launches, identifies, observes, supervises and connects Agent Mail for Meta's Muse Code CLI as the provider `muse-cli`.

**Architecture:** There are three parts.

- **A provider module,** following the existing provider pattern: launch and resume commands, plus process matching.
- **A transcript observer,** following `claude_activity_service.py`. It reads Muse's structured `session.jsonl` event log and discovers the session id from the `.session.lock` that the Muse process holds open.
- **The integrations that list harnesses** get the new id: Agent Mail install (user-wide settings), the hook route, the screen recogniser, the guard and the frontend.

**Tech Stack:** Python 3.12, FastAPI and pytest in the backend; React 19, TypeScript, Vitest and Playwright in the frontend; the Muse Code CLI 1.4.x.

**Spec:** `docs/superpowers/specs/2026-10-14-muse-code-harness-design.md`

## Global Constraints

- **Provider id** `muse-cli`, display name `Muse Code`, binary `muse`.
- **Process names:** argv0 `muse` (the launcher) or `muse-bin-<version>` (the exec'd binary).
- **Session folder:** `$MUSE_DATA_DIR` or `~/.local/share/muse`, then `sessions/YYYY/MM/DD/<uuid>/session.jsonl`, with `.session.lock` held by the live process.
- **Settings file:** `$MUSE_CONFIG_DIR` or `~/.config/muse`, then `settings.json`. It must keep `schema_version`. The install edits only `mcpServers.claude-deck-mail` and Deck's hook groups.
- **Timestamps:** `recorded_at` is epoch microseconds (UTC).
- **Reasoning tiers:** `none minimal low medium high xhigh max ultra`.
- **Muse runs only on Meta:** the Bedrock and platform options are refused.
- **Unknown grants no authority:** every unreadable or ambiguous observation returns `unknown`.

## Review Focus

1. **A resumed session reads an older transcript prefix.** A turn that started before this process started must not count as current work. The observer ignores events before the process start, as `observe_claude` does. Test: `test_events_before_process_start_are_ignored`.
2. **The settings file has other users' MCP servers and hooks.** Install and uninstall must keep them byte-for-byte as data, and a malformed file must be refused, not rewritten. Tests: `test_install_keeps_existing_servers_and_hooks`, `test_install_refuses_malformed_settings`.
3. **Two Muse sessions in one workspace** (for example the user's own and Deck's). Discovery must bind to this process's lock only, never the newest folder. Test: `test_discovery_uses_this_process_lock_only`.
4. **The last transcript line is partial,** because Muse is mid-write. Return `unknown` / `observation_incomplete`; never raise. Test: `test_partial_last_line_is_incomplete`.
5. **A question was answered and the turn continues.** The state is `working`, not waiting. Test: `test_answered_question_is_not_waiting`.

---

### Task 1: Provider module, registry, capabilities and launch contract

**Files:**
- Create: `backend/app/services/providers/muse_cli.py`
- Modify: `backend/app/services/providers/__init__.py` (the registry)
- Modify: `backend/app/services/providers/launch_contract.py` (the constants and tables)
- Modify: `backend/app/services/providers/capabilities.py` (the matrix entry)
- Test: `backend/tests/test_muse_provider.py`

**Interfaces:**
- Produces: `MuseCliProvider` (id `muse-cli`), `muse_data_dir() -> Path`, `muse_config_dir() -> Path`, `MUSE_REASONING_EFFORTS: tuple[str, ...]`, and `PROVIDER_MUSE_CLI = "muse-cli"` in `launch_contract`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_muse_provider.py
import pytest

from app.services.providers import get_provider
from app.services.providers.base import ProviderLaunchError, SpawnCommandOptions
from app.services.providers.capabilities import capability_flags
from app.services.providers.launch_contract import launch_modes_for, option_keys_for, reasoning_efforts_for

SID = "01a13be9-b3fa-79f3-941d-e49637f03184"


def build(**kwargs):
    return get_provider("muse-cli").build_spawn_command(SpawnCommandOptions(directory="/w", **kwargs))


def test_registry_and_contract():
    provider = get_provider("muse-cli")
    assert (provider.display_name, provider.binary_name) == ("Muse Code", "muse")
    assert launch_modes_for("muse-cli") == ("plain", "resume")
    assert "ultra" in reasoning_efforts_for("muse-cli")
    assert set(option_keys_for("muse-cli")) == {"model", "reasoning_effort", "skip_permissions", "prompt", "session_id"}
    flags = capability_flags("muse-cli")
    assert flags["spawn"] and flags["resume"] and flags["mcp"] and flags["hooks"]


def test_plain_launch():
    assert build(model="muse-wonder-1.0", reasoning_effort="high", skip_permissions=True, prompt="Hello") == [
        "muse", "--trust-workspace", "--model", "muse-wonder-1.0", "--reasoning-effort", "high", "--yolo", "Hello"]


def test_resume_launch():
    assert build(mode="resume", session_id=SID, model="muse-wonder-1.0") == [
        "muse", "--trust-workspace", "--model", "muse-wonder-1.0", "resume", SID]


@pytest.mark.parametrize("kwargs,code", [
    ({"mode": "resume", "session_id": "last"}, "muse_session_invalid"),
    ({"mode": "resume"}, "muse_session_invalid"),
    ({"session_id": SID}, "muse_session_invalid"),
    ({"mode": "worktree"}, "unsupported_launch_mode"),
    ({"reasoning_effort": "extreme"}, "invalid_reasoning_effort"),
    ({"model": "bad\nmodel"}, "invalid_model"),
    ({"platform": "bedrock"}, "muse_platform_unsupported"),
    ({"bedrock_model": "x"}, "muse_option_unsupported"),
    ({"no_ask_user": True}, "muse_option_unsupported"),
    ({"prompt": "-rf"}, "muse_literal_prompt_required"),
])
def test_refusals(kwargs, code):
    with pytest.raises(ProviderLaunchError) as error:
        build(**kwargs)
    assert error.value.block_code == code


@pytest.mark.parametrize("command,match", [
    ("muse --trust-workspace", True),
    ("/home/u/.local/bin/muse-bin-1.4.8-R6256.1 --trust-workspace", True),
    ("musescore", False),
    ("python3 muse.py", False),
])
def test_process_match(command, match):
    assert get_provider("muse-cli").is_process_match(command, "1") is match
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_muse_provider.py -p deck_guard -q`
Expected: FAIL with `ValueError: Unknown provider: muse-cli`.

- [ ] **Step 3: Implement the provider module**

```python
# backend/app/services/providers/muse_cli.py
"""Muse Code CLI provider (Meta)."""
from __future__ import annotations

import os
import re
from pathlib import Path

from app.services.providers.base import AgentProvider, ProviderLaunchError, SpawnCommandOptions, argv0_name
from app.services.providers.launch_contract import MUSE_REASONING_EFFORTS

_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_BINARY = re.compile(r"muse-bin-[0-9][0-9A-Za-z.\-]*")


def muse_data_dir() -> Path:
    return Path(os.environ.get("MUSE_DATA_DIR", "~/.local/share/muse")).expanduser()


def muse_config_dir() -> Path:
    return Path(os.environ.get("MUSE_CONFIG_DIR", "~/.config/muse")).expanduser()


def is_muse_command(command: str) -> bool:
    name = argv0_name(command)
    return name == "muse" or bool(_BINARY.fullmatch(name))


class MuseCliProvider(AgentProvider):
    id = "muse-cli"
    display_name = "Muse Code"
    binary_name = "muse"

    def get_config_paths(self, project_path: str | None = None) -> dict:
        return {"root": str(muse_config_dir()), "user_config": str(muse_config_dir() / "settings.json"),
                "sessions": str(muse_data_dir() / "sessions")}

    def is_process_match(self, command: str, pid: str) -> bool:
        return is_muse_command(command)

    def build_spawn_command(self, options: SpawnCommandOptions) -> list[str]:
        if options.mode not in {"plain", "resume"}:
            raise ProviderLaunchError("Muse Code supports plain and resume only", "unsupported_launch_mode")
        if options.platform.strip() not in {"", "anthropic", "meta"}:
            raise ProviderLaunchError("Muse Code runs only on Meta", "muse_platform_unsupported")
        unsupported = (
            "worktree_name", "project_folder", "profile", "profile_v2", "sandbox", "approval_policy",
            "search", "no_alt_screen", "dangerously_bypass_approvals_and_sandbox", "aws_region",
            "aws_profile", "bedrock_model", "agent", "context_tier", "plan", "remote", "allow_all",
            "no_ask_user", "use_last",
        )
        if any(getattr(options, field) not in (None, False, "") for field in unsupported):
            raise ProviderLaunchError("Unsupported Muse Code launch option", "muse_option_unsupported")
        command = ["muse", "--trust-workspace"]
        if options.model is not None:
            model = options.model.strip()
            if not model or any(character in model for character in "\n\r\x00 "):
                raise ProviderLaunchError("Invalid Muse model", "invalid_model")
            command += ["--model", model]
        if options.reasoning_effort:
            if options.reasoning_effort not in MUSE_REASONING_EFFORTS:
                raise ProviderLaunchError("Invalid Muse reasoning effort", "invalid_reasoning_effort")
            command += ["--reasoning-effort", options.reasoning_effort]
        if options.skip_permissions:
            command.append("--yolo")
        if options.mode == "resume":
            if not options.session_id or not _UUID.fullmatch(options.session_id):
                raise ProviderLaunchError("Muse resume requires an exact session UUID", "muse_session_invalid")
            if options.prompt:
                raise ProviderLaunchError("Muse resume does not take a prompt", "muse_option_unsupported")
            return command + ["resume", options.session_id]
        if options.session_id:
            raise ProviderLaunchError("A session id requires resume mode", "muse_session_invalid")
        if options.prompt:
            if options.prompt.startswith("-"):
                raise ProviderLaunchError("A Muse prompt cannot start with -", "muse_literal_prompt_required")
            command.append(options.prompt)
        return command

    def get_allowed_cli_commands(self) -> list[str]:
        return []
```

- [ ] **Step 4: Register the provider and add its contract**

In `launch_contract.py`, add `PROVIDER_MUSE_CLI = "muse-cli"` and `MUSE_REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")`, then these table entries:
- `PROVIDER_LAUNCH_MODES[PROVIDER_MUSE_CLI] = ("plain", "resume")`
- `PROVIDER_REASONING_EFFORTS[PROVIDER_MUSE_CLI] = MUSE_REASONING_EFFORTS`
- `PROVIDER_BEDROCK_SUPPORT[PROVIDER_MUSE_CLI] = False`
- `PROVIDER_OPTION_KEYS[PROVIDER_MUSE_CLI] = ("model", "reasoning_effort", "skip_permissions", "prompt", "session_id")`
- `MODEL_EXAMPLES[PROVIDER_MUSE_CLI] = ({"value": "muse-wonder-1.0", "label": "Muse Wonder", "source": "example"}, {"value": "muse-spark-1.3", "label": "Muse Spark", "source": "example"})`

In `providers/__init__.py`, import `MuseCliProvider` and add `"muse-cli": MuseCliProvider()`.

In `capabilities.py`, add a `"muse-cli"` entry. `spawn` and `resume` are `write_capable`, `sessions` is `read_only`, and `mcp` and `hooks` are `write_capable`, with reasons in the style of the Pi entry. Add `permissions` as `unsupported`, with the reason "Questions are detected and escalated; a hook cannot block them."

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && venv/bin/python -m pytest tests/test_muse_provider.py tests/test_providers.py tests/test_multi_provider_smoke.py -p deck_guard -q`
Expected: PASS. Update `test_multi_provider_smoke.py`'s provider id set to include `muse-cli` if it asserts the exact set.

- [ ] **Step 6: Commit**

`git commit -m "feat(providers): add the Muse Code provider (muse-cli)"`

### Task 2: Agent Mail install and the hook route

**Files:**
- Modify: `backend/app/services/agent_mail_install_service.py`
- Modify: `backend/app/models/schemas.py` (`AgentMailInstallStatus`)
- Modify: `backend/app/api/v1/agent_mail.py` (`_hook_provider`, `_hook_session_key`, and the install routes)
- Modify: `backend/tests/test_settings_write_guard.py` (`MAIL_INSTALL_WRITES`)
- Test: `backend/tests/agent_mail/test_muse_install.py`

**Interfaces:**
- Consumes: `muse_config_dir()` from Task 1.
- Produces: `muse_settings_path() -> Path`, `muse_mcp_installed() -> bool`, `installed_muse_hooks() -> list[str]`, `async apply_muse_install(db)`, `async uninstall_muse(db)`, and `MUSE_MAIL_HOOK_EVENTS`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/agent_mail/test_muse_install.py
import json

import pytest

from app.services import agent_mail_install_service as svc


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(svc, "muse_cli_available", lambda: True)

    async def no_backup(db, scope):
        return None

    monkeypatch.setattr(svc, "_backup_before_mutation", no_backup)
    return tmp_path / "settings.json"


@pytest.mark.asyncio
async def test_install_keeps_existing_servers_and_hooks(settings_file):
    other_hook = {"hooks": [{"type": "command", "command": "/usr/bin/true"}]}
    settings_file.write_text(json.dumps({"schema_version": 1, "tui": {"theme": "dark"},
        "mcpServers": {"mine": {"transport": "stdio", "command": "x"}},
        "hooks": {"SessionStart": [other_hook]}}))
    await svc.apply_muse_install(None)
    doc = json.loads(settings_file.read_text())
    assert doc["schema_version"] == 1 and doc["tui"] == {"theme": "dark"}
    assert doc["mcpServers"]["mine"] == {"transport": "stdio", "command": "x"}
    assert doc["mcpServers"]["claude-deck-mail"]["transport"] == "stdio"
    assert other_hook in doc["hooks"]["SessionStart"]
    assert svc.muse_mcp_installed() and sorted(svc.installed_muse_hooks()) == ["SessionStart", "UserPromptSubmit"]
    await svc.apply_muse_install(None)  # idempotent: no duplicate groups
    doc = json.loads(settings_file.read_text())
    assert len(doc["hooks"]["SessionStart"]) == 2
    await svc.uninstall_muse(None)
    doc = json.loads(settings_file.read_text())
    assert "claude-deck-mail" not in doc["mcpServers"] and doc["hooks"]["SessionStart"] == [other_hook]
    assert "UserPromptSubmit" not in doc["hooks"]


@pytest.mark.asyncio
async def test_install_creates_a_versioned_file(settings_file):
    await svc.apply_muse_install(None)
    assert json.loads(settings_file.read_text())["schema_version"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["{not json", "[]", '{"schema_version": 1, "mcpServers": []}'])
async def test_install_refuses_malformed_settings(settings_file, content):
    settings_file.write_text(content)
    with pytest.raises(ValueError):
        await svc.apply_muse_install(None)
    assert settings_file.read_text() == content


def test_hook_command_names_the_provider():
    assert "--provider muse-cli" in svc.muse_hook_command("session-start")
```

Add to `backend/tests/test_settings_write_guard.py`: `"muse"` in the harness tuple of `MAIL_INSTALL_WRITES`. Add a test for the hook route in `backend/tests/agent_mail/test_api.py`: post a `session-start` hook with `provider=muse-cli`, and assert that the session key starts with `muse:`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/agent_mail/test_muse_install.py tests/test_settings_write_guard.py -p deck_guard -q`
Expected: FAIL with `AttributeError: ... apply_muse_install`, and a 404 or 405 for the new routes in the write guard.

- [ ] **Step 3: Implement**

In `agent_mail_install_service.py`:

```python
MUSE_MAIL_HOOK_EVENTS = {"SessionStart": "session-start", "UserPromptSubmit": "user-prompt-submit"}


def muse_settings_path() -> Path:
    from app.services.providers.muse_cli import muse_config_dir
    return muse_config_dir() / "settings.json"


def muse_cli_available() -> bool:
    return shutil.which("muse") is not None


def muse_hook_command(slug: str) -> str:
    return provider_hook_command("muse-cli", slug)


def _muse_mcp_entry() -> dict:
    return {"transport": "stdio", "command": sys.executable, "args": [shim_path()],
            "env": {"CLAUDE_DECK_URL": deck_base_url(), "CLAUDE_DECK_PROVIDER": "muse-cli"}}


def _load_muse_settings() -> dict:
    path = muse_settings_path()
    if not path.exists():
        return {"schema_version": 1}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read the Muse settings file: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError("The Muse settings file must contain a JSON object")
    for key in ("mcpServers", "hooks"):
        if key in doc and not isinstance(doc[key], dict):
            raise ValueError(f"The Muse settings field '{key}' must be a JSON object")
    return doc


def _write_muse_settings(doc: dict) -> None:
    path = muse_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".deck-tmp")
    temporary.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def muse_mcp_installed() -> bool:
    try:
        entry = _load_muse_settings().get("mcpServers", {}).get(MCP_SERVER_NAME)
    except ValueError:
        return False
    return isinstance(entry, dict) and shim_path() in entry.get("args", [])


def installed_muse_hooks() -> list[str]:
    try:
        hooks = _load_muse_settings().get("hooks", {})
    except ValueError:
        return []
    return [event for event, slug in MUSE_MAIL_HOOK_EVENTS.items()
            if any(_codex_hook_group_is_current(group, event, slug) for group in hooks.get(event, []) or [])]


def _muse_hook_entry(slug: str) -> dict:
    return {"hooks": [{"type": "command", "command": muse_hook_command(slug), "timeout": 2}]}


async def apply_muse_install(db: AsyncSession) -> AgentMailInstallStatus:
    if not muse_cli_available():
        raise ValueError("Muse Code is not available on this machine")
    doc = _load_muse_settings()
    await _backup_before_mutation(db, "muse")
    doc.setdefault("schema_version", 1)
    doc.setdefault("mcpServers", {})[MCP_SERVER_NAME] = _muse_mcp_entry()
    _prune_codex_mail_hooks(doc)
    hooks = doc.setdefault("hooks", {})
    for event, slug in MUSE_MAIL_HOOK_EVENTS.items():
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise ValueError(f"Muse hooks event {event} must contain a list")
        groups.append(_muse_hook_entry(slug))
    _write_muse_settings(doc)
    return await get_install_status()


async def uninstall_muse(db: AsyncSession) -> AgentMailInstallStatus:
    if not muse_settings_path().exists():
        return await get_install_status()
    doc = _load_muse_settings()
    await _backup_before_mutation(db, "muse")
    servers = doc.get("mcpServers", {})
    changed = servers.pop(MCP_SERVER_NAME, None) is not None
    changed = _prune_codex_mail_hooks(doc) or changed
    if not doc.get("hooks"):
        doc.pop("hooks", None)
    if changed:
        _write_muse_settings(doc)
    return await get_install_status()
```

Make two more changes in this service:
- `_backup_before_mutation`: add a branch `elif scope == "muse": paths = [muse_settings_path()]`.
- `get_install_status()`: add `muse_cli_available`, `muse_mcp_installed`, `muse_hooks=installed_muse_hooks()` and `muse_hooks_missing`, set to the events in `MUSE_MAIL_HOOK_EVENTS` that are not installed.

Add those four fields to `AgentMailInstallStatus` in `schemas.py`, with defaults: `False`, `False`, `[]` and `[]`.

In `agent_mail.py`:
- add `"muse-cli"` to the `_hook_provider` allowlist;
- add `"muse-cli": "muse"` to `prefix_by_provider`;
- add `POST /install/muse/apply` and `POST /install/muse/uninstall`, copying the Codex route pair with the same dependencies, including `INSTALL_WRITES`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && venv/bin/python -m pytest tests/agent_mail/test_muse_install.py tests/test_settings_write_guard.py tests/agent_mail/test_api.py -p deck_guard -q`
Expected: PASS.

- [ ] **Step 5: Commit**

`git commit -m "feat(agent-mail): install Agent Mail for Muse Code in its user settings"`

### Task 3: Native observation and session discovery

**Files:**
- Create: `backend/app/services/muse_activity_service.py`
- Modify: `backend/app/services/agent_activity_service.py`. Dispatch `muse-cli`; extend the `launch_options` query (`provider.in_([...])`) and `_save_codex_identities`, so that a discovered Muse id is saved too.
- Create fixtures: `backend/tests/fixtures/muse_sessions/{turn_completed,tool_turn_working,question_waiting,question_answered}.jsonl`, sanitised minimal event logs.
- Test: `backend/tests/agent_teams/test_muse_activity.py`

**Interfaces:**
- Consumes: `muse_data_dir()` and `is_muse_command()` from Task 1.
- Produces:
  - `observe_muse(pid: int, session_id: str, cwd: str, now: datetime, started_at: datetime, *, provenance: dict | None = None) -> tuple[str, str, datetime | None]`
  - `discover_muse_session(pid: int, cwd: str) -> str | None`
  - `muse_state_from_lines(lines: list[bytes], session_id: str, cwd: str, now: datetime, started_at: datetime) -> tuple[str, str, datetime | None, dict]`. This is the pure parser; the dict carries `build` and `model`.

The parser rules:
- **Binding:** the lines must contain `session.opened.observed` with `payload.record.session_id == session_id` and `runtime.session.metadata` with `payload.record.workspace_root` resolving to `cwd`. Otherwise return `session_mismatch`.
- **Time:** `recorded_at` is in µs; ignore events before `started_at`; an event more than 5 s after `now` is `observation_invalid`.
- **Events:**
  - `runtime.session` with `event.kind == "started"` and a `prompt` key gives working / `native_turn_started`.
  - `user_input_prompt_requested` records `prompt_id` as pending and gives `waiting_input`.
  - `user_input_prompt_settled` with the same `prompt_id` clears it and gives working / `native_progress`.
  - `terminal` with `terminal == "completed"` gives idle / `native_turn_completed`; any other value gives unknown / `native_turn_interrupted`.
  - Progress kinds (`model_completed`, `assistant_tool_calls_committed`, `tool_result_batch_committed`) while working give `native_progress`; outside a turn they give unknown / `native_progress_without_start`.
- **No events:** unknown / `no_native_event`.
- **Stale work:** working with no event for 180 s gives unknown / `native_event_stale`.
- **The returned state:**
  - a pending prompt id returns `("waiting_input", "native_question_open", t)`;
  - `("idle", ...)` and `("working", ...)` pass through;
  - the caller maps `waiting_input` to the existing `NativeInputWait(reason="question")` and reports the activity state `working`, which is how the screen path reports a question today.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/agent_teams/test_muse_activity.py
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.muse_activity_service import discover_muse_session, muse_state_from_lines

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "muse_sessions"
SID = "01a13be9-b3fa-79f3-941d-e49637f03184"
CWD = "/tmp/muse-fixture-ws"
NOW = datetime(2026, 10, 14, 17, 50, tzinfo=timezone.utc)
START = NOW - timedelta(hours=1)


def state(name, **kwargs):
    lines = (FIX / f"{name}.jsonl").read_bytes().splitlines(keepends=True)
    values = {"session_id": SID, "cwd": CWD, "now": NOW, "started_at": START, **kwargs}
    return muse_state_from_lines(lines, **values)[:2]


@pytest.mark.parametrize("name,expected", [
    ("turn_completed", ("idle", "native_turn_completed")),
    ("tool_turn_working", ("working", "native_progress")),
    ("question_waiting", ("waiting_input", "native_question_open")),
])
def test_states(name, expected):
    assert state(name) == expected


def test_answered_question_is_not_waiting():
    assert state("question_answered")[0] == "idle"


def test_wrong_session_or_workspace_is_a_mismatch():
    assert state("turn_completed", session_id="01a13be9-0000-7000-8000-000000000000")[1] == "session_mismatch"
    assert state("turn_completed", cwd="/elsewhere")[1] == "session_mismatch"


def test_events_before_process_start_are_ignored():
    assert state("turn_completed", started_at=NOW - timedelta(seconds=1))[0] == "unknown"


def test_partial_last_line_is_incomplete():
    lines = (FIX / "turn_completed.jsonl").read_bytes().splitlines(keepends=True)
    lines[-1] = lines[-1].rstrip(b"\n")[:-5]
    assert muse_state_from_lines(lines, SID, CWD, NOW, START)[:2] == ("unknown", "observation_incomplete")


def test_discovery_uses_this_process_lock_only(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions" / "2026" / "10" / "14"
    for sid in (SID, "01a13be9-ffff-7fff-bfff-ffffffffffff"):
        folder = sessions / sid
        folder.mkdir(parents=True)
        (folder / ".session.lock").write_text("")
        text = (FIX / "turn_completed.jsonl").read_text()
        (folder / "session.jsonl").write_text(text.replace(SID, sid))
    monkeypatch.setenv("MUSE_DATA_DIR", str(tmp_path))
    fds = tmp_path / "fd"
    fds.mkdir()
    (fds / "7").symlink_to(sessions / SID / ".session.lock")
    import app.services.muse_activity_service as m
    monkeypatch.setattr(m, "_process_fd_dir", lambda pid: fds)
    assert discover_muse_session(123, CWD) == SID
```

The fixtures are built from the spike logs: keep only the records named in the parser rules, set `workspace_root` to `/tmp/muse-fixture-ws` and the session id to `SID`, drop prompt text and model reasoning, and keep `recorded_at` values within the hour before `NOW`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/agent_teams/test_muse_activity.py -p deck_guard -q`
Expected: FAIL with `ModuleNotFoundError: app.services.muse_activity_service`.

- [ ] **Step 3: Implement `muse_activity_service.py`**

The module has:
- `_process_fd_dir(pid)`, which returns `Path(f"/proc/{pid}/fd")` and is patchable in tests;
- `discover_muse_session(pid, cwd)`, which looks for exactly one fd target named `.session.lock` under `muse_data_dir()/"sessions"` whose parent name is a UUID, then validates the binding with `muse_state_from_lines` reading that folder's `session.jsonl`;
- `muse_state_from_lines(...)`, which implements the parser rules above;
- `observe_muse(...)`:
  - check that `/proc/pid/cmdline` argv0 passes `is_muse_command` and that argv is `... resume <session_id>`, or that `discover_muse_session(pid, cwd) == session_id`; otherwise return `session_mismatch`;
  - open `session.jsonl` with `O_NOFOLLOW | O_NONBLOCK`, require a regular file owned by the process uid that is not world-writable, and read a 1 MiB tail through one descriptor with the same before/after `fstat` binding as `claude_activity_service._state`;
  - if the tail starts mid-file, drop its first line, then call `muse_state_from_lines`;
  - put `session_id`, `build`, `model` and `event_id` into `provenance`.

- [ ] **Step 4: Wire the dispatcher**

In `agent_activity_service.py`, after the `pi-cli` branch, add a `muse-cli` branch. With no `session_id`, call `discover_muse_session`; if it finds an id, set `provenance["discovered_session_id"]` and return `("unknown", "restart_needed_for_observation")`, as Codex does. Otherwise call `observe_muse`. Then:
- re-check the process start, as the other branches do;
- map `waiting_input` to `NativeInputWait(reason="question", observed_at=now)`, with the activity state `working`;
- put `provenance["muse_build"]` in the result details.

Add `"muse-cli"` to the `launch_options` provider list and to `_save_codex_identities`'s provider filter, so that a discovered id is saved into the slot's `launch_options.session_id`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && venv/bin/python -m pytest tests/agent_teams/test_muse_activity.py tests/agent_teams -k "activity or native" -p deck_guard -q`
Expected: PASS.

- [ ] **Step 6: Commit**

`git commit -m "feat(teams): observe Muse Code sessions from their event log"`

### Task 4: The screen recogniser

**Files:**
- Modify: `backend/app/services/agent_activity_service.py` (`recognize_native_input_wait`)
- Create: `backend/tests/fixtures/native_screens/muse-question-form.txt` and `muse-idle-prompt.txt`, from the spike captures with the paths sanitised.
- Test: `backend/tests/agent_teams/test_native_input_wait.py`

- [ ] **Step 1: Add tests** that `recognize_native_input_wait("muse-cli", <question form>) == "question"`, that the idle prompt gives `"clear"`, and that the Claude fixtures give `None` for `muse-cli`.

- [ ] **Step 2: Implement** a `muse-cli` branch:
  - `question`: the footer matches `Enter to select\s*·\s*↑/↓ to move\s*·\s*Tab for an optional note\s*·\s*Esc to interrupt$`, and the active area has `(?m)^\s*⟩\s*\d+\.`.
  - `clear`: one of the last 4 lines matches `❯\s*`, and the status line matches `muse-[a-z0-9.\-]+ · `.

  Allow `muse-cli` in the provider check.

- [ ] **Step 3: Run** `pytest tests/agent_teams/test_native_input_wait.py -q`. Expected: PASS.

- [ ] **Step 4: Commit** `git commit -m "feat(teams): recognise Muse Code question and idle screens"`

### Task 5: The guard

**Files:**
- Modify: `scripts/product-factory/team-supervisor` (`transcript()` and `notice()`)
- Test: `backend/tests/test_team_supervisor.py`

- [ ] **Step 1: Add tests:**
  - a Muse transcript is found at `muse_sessions_root/*/*/*/<uuid>/session.jsonl`;
  - missing and ambiguous matches raise `FileNotFoundError` (`native_transcript_missing` and `native_transcript_ambiguous`);
  - an `output` event whose `final_result` text contains the cybersecurity notice gives `cybersecurity_notice`;
  - the same text in a `tool_result_batch_committed` result gives `None`.

- [ ] **Step 2: Implement:**
  - a `muse_sessions_root` config key, defaulting to `~/.local/share/muse/sessions`, and a `muse-cli` branch in `transcript()` mirroring the Codex glob branch;
  - in `notice()`, a record with `payload_type == "runtime.session"` and `payload.event.kind in {"output", "reasoning_committed"}` has its `text`, `chunk.text` and `final_result.text` checked with `_match`;
  - a `runtime.session` event of kind `error` or `failed` has its `message` checked with `_error_code`;
  - every other record returns `None`.

- [ ] **Step 3: Run** `pytest tests/test_team_supervisor.py -q`. Expected: PASS.

- [ ] **Step 4: Commit** `git commit -m "feat(guard): scan Muse Code transcripts"`

### Task 6: Frontend

**Files:**
- Modify:
  - `frontend/src/types/providers.ts` (the `AgentProviderId` union)
  - `frontend/src/features/factory/filterHelpers.ts` (the harness label)
  - `frontend/src/features/native-settings/surfaceRegistry.tsx` (`"muse-cli": {}`)
  - `frontend/src/features/agent-teams/AgentTeamsPage.tsx` (the slot provider select)
  - `frontend/src/features/factory/RepositorySetupPage.tsx` (the provider list)
  - `frontend/src/features/providers/ProviderLaunchOptionsFields.tsx` (`isMuse`: a model field with the placeholder `muse-wonder-1.0`, a reasoning effort select from the contract, no platform field)
  - `frontend/e2e/lane-f/harness-list.spec.ts` and the provider-operations fixture catalogs, if their tests assert the exact provider set
- Test: `frontend/tests/provider-launch-options.test.tsx` (create it if missing, following the existing launch-options tests)

- [ ] **Step 1: Add a test** that renders the launch-options fields for `muse-cli` and finds a model input and a reasoning-effort select, with no platform select.
- [ ] **Step 2: Implement** the additions above.
- [ ] **Step 3: Run** `cd frontend && npx tsc -b --noEmit && npx vitest run`. Expected: PASS, except the known locale-dependent `activity-feed` test.
- [ ] **Step 4: Commit** `git commit -m "feat(ui): offer Muse Code as a team harness"`

### Task 7: Docs and a live check

**Files:**
- Modify: `docs/features/harnesses.md` (a Muse Code section: subscription, launch, Agent Mail install, the question limit, auto-updates)

- [ ] **Step 1: Write the docs section.**
- [ ] **Step 2: Run the full backend suite** (`pytest tests/ -p deck_guard -q`) **and the frontend suite.**
- [ ] **Step 3: Live check** on an isolated Deck instance (port 8765, with `cleanup_orphaned_relays` patched out). Install Agent Mail for Muse, create a team with one `muse-cli` slot on `muse-wonder-1.0` in a temporary workspace, and launch it. Then confirm:
  1. the member registers in Agent Mail;
  2. the slot's `session_id` is saved and the slot relaunches in resume mode;
  3. activity shows `working` during a prompt and `idle` after it;
  4. asking a question shows waiting for input;
  5. the guard's transcript lookup finds the session.

  Stop the instance and remove the temporary team.
- [ ] **Step 4: Commit the docs, then push and open the PR** into `master` with the four required checks.
