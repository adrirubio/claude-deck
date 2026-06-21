"""Install Agent Mail integration into supported local agent CLIs."""
import json
import logging
import shlex
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Backup
from app.config import settings
from app.models.schemas import (
    AgentMailInstallStatus,
    AgentMailSnippets,
    HookCreate,
    MCPServerCreate,
)
from app.services.hook_service import HookService
from app.services.mcp_service import MCPService
from app.services.providers.copilot_cli import get_copilot_home
from app.services.providers.codex_cli import get_codex_home
from app.services.providers.opencode_cli import get_opencode_home
from app.utils.path_utils import get_claude_user_config_file, get_claude_user_settings_file

logger = logging.getLogger(__name__)

hook_service = HookService()
mcp_service = MCPService()

MCP_SERVER_NAME = "claude-deck-mail"
POST_TOOL_USE_MATCHER = "Edit|Write|MultiEdit|NotebookEdit"

MAIL_HOOK_EVENTS = {
    "SessionStart": "session-start",
    "UserPromptSubmit": "user-prompt-submit",
    "SessionEnd": "session-end",
    "PostToolUse": "post-tool-use",
}
CODEX_MAIL_HOOK_EVENTS = {
    "SessionStart": "session-start",
    "UserPromptSubmit": "user-prompt-submit",
}
COPILOT_MAIL_HOOK_EVENTS = {
    "sessionStart": "session-start",
    "userPromptSubmitted": "user-prompt-submit",
    "sessionEnd": "session-end",
    "postToolUse": "post-tool-use",
    "notification": "user-prompt-submit",
}
OPENCODE_MAIL_PLUGIN_EVENTS = {
    "session.created": "session-start",
    "session.idle": "user-prompt-submit",
    "session.deleted": "session-end",
    "tool.execute.after": "post-tool-use",
    "experimental.chat.system.transform": "user-prompt-submit",
}

_HOOK_URL_MARKER = "/api/v1/agent-mail/hooks/"
_CODEX_HOOK_MARKER = "agent_mail_hook.py"
_OPENCODE_PLUGIN_MARKER = "Claude Deck Agent Mail OpenCode plugin"


def deck_base_url() -> str:
    return f"http://127.0.0.1:{settings.port}"


def shim_path() -> str:
    return str(Path(__file__).resolve().parents[2] / "mcp_shim" / "agent_mail_server.py")


def hook_shim_path() -> str:
    return str(Path(__file__).resolve().parents[2] / "mcp_shim" / "agent_mail_hook.py")


def hook_command(slug: str) -> str:
    return (
        f"curl -s -f --connect-timeout 0.25 -m 1 "
        f"-X POST {deck_base_url()}/api/v1/agent-mail/hooks/{slug} "
        "-H 'Content-Type: application/json' --data-binary @- 2>/dev/null || true"
    )


def codex_hooks_path() -> Path:
    return get_codex_home() / "hooks.json"


def copilot_hooks_path() -> Path:
    return get_copilot_home() / "hooks" / f"{MCP_SERVER_NAME}.json"


def opencode_config_path() -> Path:
    jsonc_path = get_opencode_home() / "opencode.jsonc"
    return jsonc_path if jsonc_path.exists() else get_opencode_home() / "opencode.json"


def opencode_config_paths() -> list[Path]:
    home = get_opencode_home()
    return [home / "opencode.json", home / "opencode.jsonc"]


def opencode_plugin_path() -> Path:
    return get_opencode_home() / "plugins" / "claude-deck-agent-mail.js"


def provider_hook_command(provider: str, slug: str) -> str:
    return " ".join(
        [
            shlex.quote(sys.executable),
            shlex.quote(hook_shim_path()),
            "--deck-url",
            shlex.quote(deck_base_url()),
            "--provider",
            shlex.quote(provider),
            "--event",
            shlex.quote(slug),
        ]
    )


def codex_hook_command(slug: str) -> str:
    return provider_hook_command("codex-cli", slug)


def copilot_hook_command(slug: str) -> str:
    return provider_hook_command("copilot-cli", slug)


def _installed_mail_hooks() -> list:
    return [
        hook
        for hook in hook_service.list_hooks()
        if hook.type == "command" and hook.command and _HOOK_URL_MARKER in hook.command
    ]


def _hook_is_current(hook, event: str, slug: str) -> bool:
    return (
        hook.event == event
        and hook.command == hook_command(slug)
        and hook.matcher == (POST_TOOL_USE_MATCHER if event == "PostToolUse" else None)
    )


def _codex_expected_matcher(event: str) -> str | None:
    return "startup|resume|clear|compact" if event == "SessionStart" else None


def _codex_hook_entry(event: str, slug: str) -> dict:
    entry = {
        "hooks": [
            {
                "type": "command",
                "command": codex_hook_command(slug),
                "statusMessage": "Checking Agent Mail",
                "timeout": 2,
            }
        ]
    }
    matcher = _codex_expected_matcher(event)
    if matcher is not None:
        entry["matcher"] = matcher
    return entry


def _load_codex_hooks_doc() -> dict:
    path = codex_hooks_path()
    if not path.exists():
        return {"hooks": {}}
    try:
        with path.open("r", encoding="utf-8") as file:
            doc = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read Codex hooks file: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError("Codex hooks file must contain a JSON object")
    hooks = doc.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("Codex hooks file field 'hooks' must be a JSON object")
    return doc


def _write_codex_hooks_doc(doc: dict) -> None:
    path = codex_hooks_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_copilot_hooks_doc() -> dict:
    path = copilot_hooks_path()
    if not path.exists():
        return {"hooks": {}}
    try:
        with path.open("r", encoding="utf-8") as file:
            doc = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read Copilot hooks file: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError("Copilot hooks file must contain a JSON object")
    hooks = doc.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("Copilot hooks file field 'hooks' must be a JSON object")
    return doc


def _write_copilot_hooks_doc(doc: dict) -> None:
    path = copilot_hooks_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _strip_json_comments_and_trailing_commas(text: str) -> str:
    """Parse common JSONC files without taking a runtime dependency."""
    output: list[str] = []
    in_string = False
    escaped = False
    in_line_comment = False
    in_block_comment = False
    index = 0
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if in_line_comment:
            if char in "\r\n":
                in_line_comment = False
                output.append(char)
            index += 1
            continue
        if in_block_comment:
            if char == "*" and next_char == "/":
                in_block_comment = False
                index += 2
            else:
                index += 1
            continue
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue
        if char == "/" and next_char == "/":
            in_line_comment = True
            index += 2
            continue
        if char == "/" and next_char == "*":
            in_block_comment = True
            index += 2
            continue
        output.append(char)
        index += 1

    without_comments = "".join(output)
    cleaned: list[str] = []
    in_string = False
    escaped = False
    index = 0
    while index < len(without_comments):
        char = without_comments[index]
        if in_string:
            cleaned.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            cleaned.append(char)
            index += 1
            continue
        if char == ",":
            lookahead = index + 1
            while lookahead < len(without_comments) and without_comments[lookahead].isspace():
                lookahead += 1
            if lookahead < len(without_comments) and without_comments[lookahead] in "}]":
                index += 1
                continue
        cleaned.append(char)
        index += 1
    return "".join(cleaned)


def _load_opencode_config_doc(path: Path | None = None) -> dict:
    path = path or opencode_config_path()
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        doc = json.loads(_strip_json_comments_and_trailing_commas(text))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read OpenCode config file: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError("OpenCode config file must contain a JSON object")
    mcp = doc.setdefault("mcp", {})
    if not isinstance(mcp, dict):
        raise ValueError("OpenCode config file field 'mcp' must be a JSON object")
    return doc


def _write_opencode_config_doc(doc: dict, path: Path | None = None) -> None:
    path = path or opencode_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _codex_hook_command_is_managed(hook: object) -> bool:
    if not isinstance(hook, dict) or not isinstance(hook.get("command"), str):
        return False
    command = hook["command"]
    return _CODEX_HOOK_MARKER in command or _HOOK_URL_MARKER in command


def _prune_codex_mail_hooks(doc: dict) -> bool:
    changed = False
    hooks = doc.setdefault("hooks", {})
    for event in list(hooks.keys()):
        groups = hooks.get(event)
        if not isinstance(groups, list):
            continue
        kept_groups = []
        for group in groups:
            if not isinstance(group, dict):
                kept_groups.append(group)
                continue
            group_hooks = group.get("hooks")
            if not isinstance(group_hooks, list):
                kept_groups.append(group)
                continue
            kept_hooks = [hook for hook in group_hooks if not _codex_hook_command_is_managed(hook)]
            if len(kept_hooks) != len(group_hooks):
                changed = True
            if kept_hooks:
                updated = dict(group)
                updated["hooks"] = kept_hooks
                kept_groups.append(updated)
        if kept_groups:
            hooks[event] = kept_groups
        else:
            hooks.pop(event, None)
    return changed


def _codex_hook_group_is_current(group: object, event: str, slug: str) -> bool:
    if not isinstance(group, dict):
        return False
    if group.get("matcher") != _codex_expected_matcher(event):
        return False
    hooks = group.get("hooks")
    if not isinstance(hooks, list):
        return False
    return any(_codex_hook_matches_event(hook, slug) for hook in hooks)


def _codex_hook_matches_event(hook: object, slug: str) -> bool:
    if not isinstance(hook, dict) or hook.get("type") != "command":
        return False
    command = hook.get("command")
    if not isinstance(command, str):
        return False
    if _HOOK_URL_MARKER in command:
        return f"{_HOOK_URL_MARKER}{slug}" in command
    if _CODEX_HOOK_MARKER not in command:
        return False
    try:
        parts = shlex.split(command)
    except ValueError:
        return f"--event {slug}" in command or f"--event={slug}" in command
    for index, part in enumerate(parts):
        if part == "--event" and index + 1 < len(parts) and parts[index + 1] == slug:
            return True
        if part == f"--event={slug}":
            return True
    return False


def _copilot_hook_entry(event: str, slug: str) -> dict:
    entry = {
        "type": "command",
        "command": copilot_hook_command(slug),
        "timeoutSec": 2,
    }
    if event == "notification":
        entry["matcher"] = "agent_idle"
    return entry


def _copilot_hook_entry_is_current(entry: object, event: str, slug: str) -> bool:
    if not isinstance(entry, dict):
        return False
    if entry.get("type") != "command":
        return False
    if entry.get("matcher") != ("agent_idle" if event == "notification" else None):
        return False
    return _codex_hook_matches_event(entry, slug)


def installed_copilot_hooks() -> list[str]:
    try:
        doc = _load_copilot_hooks_doc()
    except ValueError:
        return []
    hooks = doc.get("hooks", {})
    installed = []
    for event, slug in COPILOT_MAIL_HOOK_EVENTS.items():
        entries = hooks.get(event, [])
        if isinstance(entries, list) and any(
            _copilot_hook_entry_is_current(entry, event, slug) for entry in entries
        ):
            installed.append(event)
    return sorted(installed)


def installed_codex_hooks() -> list[str]:
    try:
        doc = _load_codex_hooks_doc()
    except ValueError:
        return []
    hooks = doc.get("hooks", {})
    installed = []
    for event, slug in CODEX_MAIL_HOOK_EVENTS.items():
        groups = hooks.get(event, [])
        if isinstance(groups, list) and any(
            _codex_hook_group_is_current(group, event, slug) for group in groups
        ):
            installed.append(event)
    return sorted(installed)


def _codex_executor():
    try:
        from app.services.cli_executor import ProviderCLIExecutor

        executor = ProviderCLIExecutor("codex-cli")
        return executor if executor.binary_path else None
    except Exception as exc:
        logger.debug("codex executor unavailable: %s", exc)
        return None


def _copilot_executor():
    try:
        from app.services.cli_executor import ProviderCLIExecutor

        executor = ProviderCLIExecutor("copilot-cli")
        return executor if executor.binary_path else None
    except Exception as exc:
        logger.debug("copilot executor unavailable: %s", exc)
        return None


def _opencode_executor():
    try:
        from app.services.cli_executor import ProviderCLIExecutor

        executor = ProviderCLIExecutor("opencode-cli")
        return executor if executor.binary_path else None
    except Exception as exc:
        logger.debug("opencode executor unavailable: %s", exc)
        return None


def codex_cli_available() -> bool:
    return _codex_executor() is not None


def copilot_cli_available() -> bool:
    return _copilot_executor() is not None


def opencode_cli_available() -> bool:
    return _opencode_executor() is not None


def codex_mcp_installed() -> bool:
    executor = _codex_executor()
    if executor is None:
        return False
    try:
        result = executor.execute("mcp", ["list", "--json"], timeout=30)
        return MCP_SERVER_NAME in (result.stdout or "")
    except Exception as exc:
        logger.debug("codex mcp list failed: %s", exc)
        return False


def copilot_mcp_installed() -> bool:
    executor = _copilot_executor()
    if executor is None:
        return False
    try:
        result = executor.execute("mcp", ["list", "--json"], timeout=30)
        if result.exit_code != 0:
            return False
        data = json.loads(result.stdout or "{}")
        servers = data.get("mcpServers") if isinstance(data, dict) else None
        return isinstance(servers, dict) and MCP_SERVER_NAME in servers
    except Exception as exc:
        logger.debug("copilot mcp list failed: %s", exc)
        return False


def _opencode_mcp_entry() -> dict:
    return {
        "type": "local",
        "command": [sys.executable, shim_path()],
        "enabled": True,
        "environment": {
            "CLAUDE_DECK_URL": deck_base_url(),
            "CLAUDE_DECK_PROVIDER": "opencode-cli",
        },
    }


def _opencode_mcp_entry_is_current(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    expected = _opencode_mcp_entry()
    command = entry.get("command")
    environment = entry.get("environment")
    return (
        entry.get("type") == "local"
        and entry.get("enabled", True) is not False
        and command == expected["command"]
        and isinstance(environment, dict)
        and environment.get("CLAUDE_DECK_URL") == expected["environment"]["CLAUDE_DECK_URL"]
        and environment.get("CLAUDE_DECK_PROVIDER") == "opencode-cli"
    )


def opencode_mcp_installed() -> bool:
    effective_entry = None
    for path in opencode_config_paths():
        try:
            doc = _load_opencode_config_doc(path)
        except ValueError:
            return False
        mcp = doc.get("mcp")
        if isinstance(mcp, dict) and MCP_SERVER_NAME in mcp:
            effective_entry = mcp[MCP_SERVER_NAME]
    return _opencode_mcp_entry_is_current(effective_entry)


def _opencode_plugin_content() -> str:
    template = r"""// Claude Deck Agent Mail OpenCode plugin.
const DECK_URL = (__DECK_URL__ || process.env.CLAUDE_DECK_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const PROVIDER = process.env.CLAUDE_DECK_PROVIDER || "opencode-cli";

function envInt(name) {
  const raw = process.env[name];
  if (!raw) return undefined;
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function timeoutSignal(ms) {
  const controller = new AbortController();
  setTimeout(() => controller.abort(), ms).unref?.();
  return controller.signal;
}

export const ClaudeDeckAgentMailPlugin = async (ctx) => {
  const cwd = () => ctx.worktree || ctx.directory || process.cwd();

  const payload = (sessionID, extra = {}) => {
    const body = {
      provider: PROVIDER,
      cwd: extra.cwd || cwd(),
      session_id: sessionID || extra.session_id || String(process.pid),
      pid: process.pid,
      ...extra,
    };
    const teamPresetID = envInt("CLAUDE_DECK_TEAM_PRESET_ID");
    const teamSlotID = envInt("CLAUDE_DECK_TEAM_SLOT_ID");
    if (teamPresetID !== undefined) body.team_preset_id = teamPresetID;
    if (teamSlotID !== undefined) body.team_slot_id = teamSlotID;
    return body;
  };

  const post = async (slug, body) => {
    try {
      const response = await fetch(`${DECK_URL}/api/v1/agent-mail/hooks/${slug}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: timeoutSignal(1000),
      });
      if (!response.ok) return {};
      return await response.json();
    } catch {
      return {};
    }
  };

  const send = (slug, sessionID, extra = {}) => post(slug, payload(sessionID, extra));

  return {
    event: async ({ event }) => {
      if (event.type === "session.created") {
        const info = event.properties?.info || {};
        await send("session-start", info.id, {
          cwd: info.directory,
          source: "opencode-session-created",
        });
      }
      if (event.type === "session.idle") {
        await send("user-prompt-submit", event.properties?.sessionID, {
          source: "opencode-session-idle",
        });
      }
      if (event.type === "session.deleted") {
        const info = event.properties?.info || {};
        await send("session-end", info.id, {
          cwd: info.directory,
          source: "opencode-session-deleted",
        });
      }
    },

    "tool.execute.after": async (input) => {
      await send("post-tool-use", input.sessionID, {
        tool_name: input.tool,
        tool_input: input.args || {},
        source: "opencode-tool-execute-after",
      });
    },

    "experimental.chat.system.transform": async (input, output) => {
      const body = await send("user-prompt-submit", input.sessionID, {
        source: "opencode-chat-system-transform",
      });
      const context = body?.hookSpecificOutput?.additionalContext;
      if (context) output.system.push(context);
    },
  };
};
"""
    return template.replace("__DECK_URL__", json.dumps(deck_base_url()))


def installed_opencode_plugin_events() -> list[str]:
    path = opencode_plugin_path()
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return []
    if _OPENCODE_PLUGIN_MARKER not in content:
        return []
    installed = []
    for event, slug in OPENCODE_MAIL_PLUGIN_EVENTS.items():
        if event in content and slug in content:
            installed.append(event)
    return sorted(installed)


async def _backup_before_mutation(db: AsyncSession, scope: str) -> None:
    try:
        backup_dir = Path.home() / ".claude-registry" / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow()
        name = f"pre-agent-mail-{scope}-{timestamp:%Y%m%d-%H%M%S}"
        archive_path = backup_dir / f"{name}.zip"
        if scope == "codex":
            paths = [
                get_codex_home() / "config.toml",
                codex_hooks_path(),
            ]
        elif scope == "copilot":
            paths = [
                get_copilot_home() / "mcp-config.json",
                copilot_hooks_path(),
            ]
        elif scope == "opencode":
            paths = [
                *opencode_config_paths(),
                opencode_plugin_path(),
            ]
        else:
            paths = [
                get_claude_user_settings_file(),
                get_claude_user_config_file(),
            ]
        existing = [path for path in paths if path.exists() and path.is_file()]
        if not existing:
            return

        home = Path.home()
        manifest = {
            "name": name,
            "scope": "agent-mail",
            "created_at": timestamp.isoformat() + "Z",
            "description": "Automatic lightweight backup before Agent Mail install/uninstall",
            "files": [],
        }
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in existing:
                try:
                    arcname = str(path.relative_to(home))
                except ValueError:
                    arcname = path.name
                manifest["files"].append(arcname)
                zf.write(path, arcname)
            zf.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))

        db.add(
            Backup(
                name=name,
                scope="agent-mail",
                description="Automatic lightweight backup before Agent Mail install/uninstall",
                file_path=str(archive_path),
                size_bytes=archive_path.stat().st_size,
            )
        )
        await db.commit()
    except Exception as exc:
        logger.warning("agent mail pre-mutation backup failed: %s", exc)


async def get_install_status() -> AgentMailInstallStatus:
    installed_hooks = _installed_mail_hooks()
    installed_events = sorted(
        {
            event
            for event, slug in MAIL_HOOK_EVENTS.items()
            if any(_hook_is_current(hook, event, slug) for hook in installed_hooks)
        }
    )
    missing = [event for event in MAIL_HOOK_EVENTS if event not in installed_events]
    codex_hook_events = installed_codex_hooks()
    codex_missing = [event for event in CODEX_MAIL_HOOK_EVENTS if event not in codex_hook_events]
    copilot_hook_events = installed_copilot_hooks()
    copilot_missing = [
        event for event in COPILOT_MAIL_HOOK_EVENTS if event not in copilot_hook_events
    ]
    opencode_plugin_events = installed_opencode_plugin_events()
    opencode_missing = [
        event for event in OPENCODE_MAIL_PLUGIN_EVENTS if event not in opencode_plugin_events
    ]
    server = await mcp_service.get_server(MCP_SERVER_NAME, "user")
    return AgentMailInstallStatus(
        claude_code_hooks=installed_events,
        claude_code_hooks_missing=missing,
        claude_code_mcp_installed=server is not None,
        codex_cli_available=codex_cli_available(),
        codex_mcp_installed=codex_mcp_installed(),
        codex_hooks=codex_hook_events,
        codex_hooks_missing=codex_missing,
        copilot_cli_available=copilot_cli_available(),
        copilot_mcp_installed=copilot_mcp_installed(),
        copilot_hooks=copilot_hook_events,
        copilot_hooks_missing=copilot_missing,
        opencode_cli_available=opencode_cli_available(),
        opencode_mcp_installed=opencode_mcp_installed(),
        opencode_plugin_events=opencode_plugin_events,
        opencode_plugin_events_missing=opencode_missing,
        curl_available=shutil.which("curl") is not None,
        shim_path=shim_path(),
        python_path=sys.executable,
        deck_url=deck_base_url(),
        claude_settings_path=str(get_claude_user_settings_file()),
        claude_mcp_config_path=str(get_claude_user_config_file()),
        codex_hooks_path=str(codex_hooks_path()),
        copilot_hooks_path=str(copilot_hooks_path()),
        opencode_config_path=str(opencode_config_path()),
        opencode_plugin_path=str(opencode_plugin_path()),
    )


async def apply_claude_code_install(db: AsyncSession) -> AgentMailInstallStatus:
    await _backup_before_mutation(db, "user")
    installed_hooks = _installed_mail_hooks()
    for event, slug in MAIL_HOOK_EVENTS.items():
        event_hooks = [hook for hook in installed_hooks if hook.event == event]
        if any(_hook_is_current(hook, event, slug) for hook in event_hooks):
            continue
        for hook in event_hooks:
            hook_service.remove_hook(hook.id, hook.scope)
        hook_service.add_hook(
            HookCreate(
                event=event,
                matcher=POST_TOOL_USE_MATCHER if event == "PostToolUse" else None,
                type="command",
                command=hook_command(slug),
                scope="user",
            )
        )
    if await mcp_service.get_server(MCP_SERVER_NAME, "user") is None:
        await mcp_service.add_server(
            MCPServerCreate(
                name=MCP_SERVER_NAME,
                type="stdio",
                scope="user",
                command=sys.executable,
                args=[shim_path()],
                env={
                    "CLAUDE_DECK_URL": deck_base_url(),
                    "CLAUDE_DECK_PROVIDER": "claude-code",
                },
            )
        )
    return await get_install_status()


async def uninstall_claude_code(db: AsyncSession) -> AgentMailInstallStatus:
    await _backup_before_mutation(db, "user")
    for hook in _installed_mail_hooks():
        hook_service.remove_hook(hook.id, hook.scope)
    if await mcp_service.get_server(MCP_SERVER_NAME, "user") is not None:
        await mcp_service.remove_server(MCP_SERVER_NAME, "user")
    return await get_install_status()


async def apply_codex_install(db: AsyncSession) -> AgentMailInstallStatus:
    executor = _codex_executor()
    if executor is None:
        raise ValueError("Codex CLI is not available on this machine")
    await _backup_before_mutation(db, "codex")
    if not codex_mcp_installed():
        args = [
            "add",
            "--env",
            f"CLAUDE_DECK_URL={deck_base_url()}",
            "--env",
            "CLAUDE_DECK_PROVIDER=codex-cli",
            MCP_SERVER_NAME,
            "--",
            sys.executable,
            shim_path(),
        ]
        result = executor.execute("mcp", args, timeout=30)
        if result.exit_code != 0:
            raise ValueError(f"codex mcp add failed: {(result.stderr or '')[:300]}")
    doc = _load_codex_hooks_doc()
    _prune_codex_mail_hooks(doc)
    hooks = doc.setdefault("hooks", {})
    for event, slug in CODEX_MAIL_HOOK_EVENTS.items():
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise ValueError(f"Codex hooks event {event} must contain a list")
        groups.append(_codex_hook_entry(event, slug))
    _write_codex_hooks_doc(doc)
    return await get_install_status()


async def uninstall_codex(db: AsyncSession) -> AgentMailInstallStatus:
    executor = _codex_executor()
    should_backup = (executor is not None and codex_mcp_installed()) or bool(installed_codex_hooks())
    if should_backup:
        await _backup_before_mutation(db, "codex")
    if executor is not None and codex_mcp_installed():
        executor.execute("mcp", ["remove", MCP_SERVER_NAME], timeout=30)
    doc = _load_codex_hooks_doc()
    if _prune_codex_mail_hooks(doc):
        _write_codex_hooks_doc(doc)
    return await get_install_status()


async def apply_copilot_install(db: AsyncSession) -> AgentMailInstallStatus:
    executor = _copilot_executor()
    if executor is None:
        raise ValueError("GitHub Copilot CLI is not available on this machine")
    await _backup_before_mutation(db, "copilot")
    if not copilot_mcp_installed():
        args = [
            "add",
            "--env",
            f"CLAUDE_DECK_URL={deck_base_url()}",
            "--env",
            "CLAUDE_DECK_PROVIDER=copilot-cli",
            "--json",
            MCP_SERVER_NAME,
            "--",
            sys.executable,
            shim_path(),
        ]
        result = executor.execute("mcp", args, timeout=30)
        if result.exit_code != 0:
            raise ValueError(f"copilot mcp add failed: {(result.stderr or '')[:300]}")
    doc = {"version": 1, "hooks": {}}
    hooks = doc["hooks"]
    for event, slug in COPILOT_MAIL_HOOK_EVENTS.items():
        hooks[event] = [_copilot_hook_entry(event, slug)]
    _write_copilot_hooks_doc(doc)
    return await get_install_status()


async def uninstall_copilot(db: AsyncSession) -> AgentMailInstallStatus:
    executor = _copilot_executor()
    should_backup = (
        (executor is not None and copilot_mcp_installed())
        or copilot_hooks_path().exists()
        or bool(installed_copilot_hooks())
    )
    if should_backup:
        await _backup_before_mutation(db, "copilot")
    if executor is not None and copilot_mcp_installed():
        executor.execute("mcp", ["remove", MCP_SERVER_NAME], timeout=30)
    try:
        copilot_hooks_path().unlink()
    except FileNotFoundError:
        pass
    return await get_install_status()


async def apply_opencode_install(db: AsyncSession) -> AgentMailInstallStatus:
    if not opencode_cli_available():
        raise ValueError("OpenCode CLI is not available on this machine")
    await _backup_before_mutation(db, "opencode")
    config_path = opencode_config_path()
    doc = _load_opencode_config_doc(config_path)
    mcp = doc.setdefault("mcp", {})
    if not isinstance(mcp, dict):
        raise ValueError("OpenCode config file field 'mcp' must be a JSON object")
    mcp[MCP_SERVER_NAME] = _opencode_mcp_entry()
    _write_opencode_config_doc(doc, config_path)
    path = opencode_plugin_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_opencode_plugin_content(), encoding="utf-8")
    return await get_install_status()


async def uninstall_opencode(db: AsyncSession) -> AgentMailInstallStatus:
    should_backup = opencode_mcp_installed() or bool(installed_opencode_plugin_events())
    if should_backup:
        await _backup_before_mutation(db, "opencode")
    for config_path in opencode_config_paths():
        try:
            doc = _load_opencode_config_doc(config_path)
        except ValueError:
            continue
        mcp = doc.get("mcp")
        if isinstance(mcp, dict) and MCP_SERVER_NAME in mcp:
            mcp.pop(MCP_SERVER_NAME, None)
            _write_opencode_config_doc(doc, config_path)
    path = opencode_plugin_path()
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        content = ""
    if _OPENCODE_PLUGIN_MARKER in content:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    return await get_install_status()


def get_snippets() -> AgentMailSnippets:
    toml = (
        f"[mcp_servers.{MCP_SERVER_NAME}]\n"
        f'command = "{sys.executable}"\n'
        f'args = ["{shim_path()}"]\n'
        f'env = {{ CLAUDE_DECK_URL = "{deck_base_url()}", CLAUDE_DECK_PROVIDER = "codex-cli" }}\n'
    )
    agents_md = (
        "## Claude Deck Agent Mail\n"
        "You are part of a local agent team coordinated through Claude Deck.\n"
        "- Call `deck_whoami` once when you start working to register and learn your role.\n"
        "- Call `deck_check_inbox` before starting major tasks and after finishing one.\n"
        "- Use `deck_request_context` to ask another repo's agent a question, and\n"
        "  `deck_create_handoff` to hand work over.\n"
    )
    copilot_command = (
        " ".join(
            [
                "copilot",
                "mcp",
                "add",
                "--env",
                shlex.quote(f"CLAUDE_DECK_URL={deck_base_url()}"),
                "--env",
                "CLAUDE_DECK_PROVIDER=copilot-cli",
                MCP_SERVER_NAME,
                "--",
                shlex.quote(sys.executable),
                shlex.quote(shim_path()),
            ]
        )
    )
    copilot_hooks_json = json.dumps(
        {
            "version": 1,
            "hooks": {
                event: [_copilot_hook_entry(event, slug)]
                for event, slug in COPILOT_MAIL_HOOK_EVENTS.items()
            },
        },
        indent=2,
        sort_keys=True,
    )
    opencode_config_json = json.dumps(
        {"mcp": {MCP_SERVER_NAME: _opencode_mcp_entry()}},
        indent=2,
        sort_keys=True,
    )
    return AgentMailSnippets(
        codex_config_toml=toml,
        codex_agents_md=agents_md,
        copilot_mcp_command=copilot_command,
        copilot_hooks_json=copilot_hooks_json,
        opencode_config_json=opencode_config_json,
        opencode_plugin_js=_opencode_plugin_content(),
    )
