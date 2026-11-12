"""Positive provider ownership and bounded, lossless configuration edits.

Installer detection is deliberately not evidence. This module captures complete
files and launch values, and never calls an install/uninstall routine.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sys

import tomlkit

OLD = "claude-deck-mail"
NEW = "albiex-synth-city-mail"
OLD_PLUGIN = "claude-deck-agent-mail.js"
NEW_PLUGIN = "albiex-synth-city-agent-mail.js"
OLD_MARKER = "Claude Deck Agent Mail OpenCode plugin"
NEW_MARKER = "Albiex Synth City Agent Mail OpenCode plugin"
PROVIDERS = ("claude-code", "muse-cli", "codex-cli", "copilot-cli", "opencode-cli")


class Attention(ValueError):
    """Ambiguous input; do not claim or overwrite it."""


class Incomplete(RuntimeError):
    """A transient boundary failed; ordinary startup must retry it."""


def is_owned_entry(entry, shim):
    if not isinstance(entry, dict):
        return False
    command, args = entry.get("command"), entry.get("args", [])
    if isinstance(command, list):
        if args or not command:
            return False
        command, *args = command
    if not isinstance(command, str) or not isinstance(args, list) or not args:
        return False
    if not all(isinstance(item, str) for item in args):
        return False
    executable = shutil.which(command) if not Path(command).is_absolute() else command
    # A shell/echo/custom executable with a suggestive argument is not a shim.
    if not executable or not re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", Path(executable).name):
        return False
    try:
        return (Path(executable).resolve() == Path(sys.executable).resolve()
                and Path(args[0]).expanduser().resolve() == Path(shim).resolve() and Path(shim).is_file())
    except (OSError, ValueError):
        return False


def renamed_entry(entry):
    result = copy.deepcopy(entry)
    key = "environment" if isinstance(result.get("command"), list) else "env"
    environment = result.get(key)
    if not isinstance(environment, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                    for k, v in environment.items()):
        raise Attention("environment_capture")
    for old, new in (("CLAUDE_DECK_URL", "SYNTH_CITY_URL"), ("CLAUDE_DECK_PROVIDER", "SYNTH_CITY_PROVIDER")):
        if old in environment:
            if new in environment and environment[new] != environment[old]:
                raise Attention("environment_conflict")
            environment[new] = environment.pop(old)
        elif new not in environment:
            raise Attention("environment_capture")
    return result


def parse_cli_entries(provider, raw):
    try:
        doc = json.loads(raw)
        if provider == "codex-cli" and isinstance(doc, list):
            result = {}
            for row in doc:
                if not isinstance(row, dict) or not isinstance(row.get("name"), str) or row["name"] in result:
                    raise ValueError
                entry = {k: v for k, v in row.items() if k != "name"}
                # Current Codex nests launch data under transport; older versions
                # emit command/args/env directly. Neither is substring evidence.
                transport = entry.get("transport")
                result[row["name"]] = transport if isinstance(transport, dict) else entry
            return result
        if provider == "copilot-cli" and isinstance(doc, dict) and isinstance(doc.get("mcpServers"), dict):
            return doc["mcpServers"]
    except (ValueError, TypeError):
        pass
    raise Attention("cli_list_unrecognised")


class _Node:
    def __init__(self, value, start, end, children=None):
        self.value, self.start, self.end = value, start, end
        self.children = children or {}


def _json_tree(text):
    """Parse JSON/JSONC with source spans; reject duplicate/ambiguous keys."""
    pattern = re.compile(r'\s+|//[^\n]*|/\*[\s\S]*?\*/|"(?:[^"\\]|\\.)*"|[{}\[\]:,]|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null')
    tokens, pos = [], 0
    while pos < len(text):
        match = pattern.match(text, pos)
        if not match:
            raise Attention("configuration_parse")
        token = match.group()
        if not token.isspace() and not token.startswith(("//", "/*")):
            tokens.append((token, pos, match.end()))
        pos = match.end()
    index = 0

    def parse():
        nonlocal index
        if index >= len(tokens):
            raise Attention("configuration_parse")
        token, start, end = tokens[index]
        index += 1
        if token in ("{", "["):
            object_ = token == "{"
            close = "}" if object_ else "]"
            value, children = ({} if object_ else []), {}
            while index < len(tokens) and tokens[index][0] != close:
                if object_:
                    keytoken, keystart, keyend = tokens[index]
                    if not keytoken.startswith('"'):
                        raise Attention("configuration_parse")
                    key = json.loads(keytoken)
                    if key in children:
                        raise Attention("configuration_duplicate_key")
                    index += 1
                    if index >= len(tokens) or tokens[index][0] != ":":
                        raise Attention("configuration_parse")
                    index += 1
                else:
                    key, keystart, keyend = len(value), 0, 0
                node = parse()
                children[key] = (keystart, keyend, node)
                if object_:
                    value[key] = node.value
                else:
                    value.append(node.value)
                if index >= len(tokens):
                    raise Attention("configuration_parse")
                if tokens[index][0] == ",":
                    index += 1
                elif tokens[index][0] != close:
                    raise Attention("configuration_parse")
            if index >= len(tokens) or tokens[index][0] != close:
                raise Attention("configuration_parse")
            end = tokens[index][2]
            index += 1
            return _Node(value, start, end, children)
        try:
            return _Node(json.loads(token), start, end)
        except ValueError:
            raise Attention("configuration_parse") from None

    root = parse()
    if index != len(tokens):
        raise Attention("configuration_parse")
    return root


def read_json(text):
    return _json_tree(text).value


def _trailing_comma(tail):
    """Read trailing JSONC trivia once, without nested regex backtracking."""
    position, comma = 0, False
    while position < len(tail):
        if tail[position].isspace():
            position += 1
        elif tail.startswith("//", position):
            end = tail.find("\n", position + 2)
            position = len(tail) if end < 0 else end + 1
        elif tail.startswith("/*", position):
            end = tail.find("*/", position + 2)
            if end < 0:
                raise Attention("configuration_parse")
            position = end + 2
        elif tail[position] == "," and not comma:
            comma, position = True, position + 1
        else:
            raise Attention("configuration_parse")
    return comma


def edit_json(text, path, value, *, rename=None, remove=False):
    root = _json_tree(text)
    node = root
    for key in path[:-1]:
        if key not in node.children:
            raise Attention("configuration_shape")
        node = node.children[key][2]
    key = path[-1]
    if key in node.children:
        start, keyend, child = node.children[key]
        if rename is not None:
            if rename in node.children:
                raise Attention("registration_conflict")
            return text[:start] + json.dumps(rename) + text[keyend:]
        if remove:
            keys = list(node.children)
            index = keys.index(key)
            end = child.end
            if index:
                start = node.children[keys[index - 1]][2].end
            elif len(keys) > 1:
                end = node.children[keys[1]][0]
            else:
                # A JSONC singleton may have a trailing comma.
                tail = text[end:node.end - 1]
                comma = re.match(r"\s*,", tail)
                if comma:
                    end += comma.end()
            return text[:start] + text[end:]
        return text[:child.start] + json.dumps(value, ensure_ascii=True) + text[child.end:]
    if remove:
        return text
    if not isinstance(node.value, dict):
        raise Attention("configuration_shape")
    prefix = "," if node.children and not _trailing_comma(text[list(node.children.values())[-1][2].end:node.end - 1]) else ""
    insertion = prefix + json.dumps(key) + ":" + json.dumps(value, ensure_ascii=True)
    return text[:node.end - 1] + insertion + text[node.end - 1:]


def _identity(path):
    stat = path.lstat()
    if not path.is_file() or path.is_symlink():
        raise Attention("configuration_not_regular")
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_mode]


def snapshot(path):
    path = Path(path).expanduser().absolute()
    if not path.exists() and not path.is_symlink():
        return {"path": str(path), "before": None, "identity": None}
    identity = _identity(path)
    data = path.read_bytes()
    if _identity(path) != identity:
        raise Incomplete("capture_changed")
    return {"path": str(path), "before": base64.b64encode(data).decode("ascii"), "identity": identity}


def decoded(value):
    return base64.b64decode(value, validate=True) if value is not None else None


def encoded(value):
    return base64.b64encode(value).decode("ascii") if value is not None else None


def _hooks(text, provider, shim):
    """Only exact generated command shapes corroborate a registration."""
    from app.services import agent_mail_install_service as install
    doc = read_json(text)
    expected = (install.MAIL_HOOK_EVENTS if provider == "claude-code" else
                install.COPILOT_MAIL_HOOK_EVENTS if provider == "copilot-cli" else install.CODEX_MAIL_HOOK_EVENTS)
    found, replacements = False, []
    groups = doc.get("hooks", {}) if isinstance(doc, dict) else None
    if not isinstance(groups, dict):
        raise Attention("hooks_capture")
    for event, entries in groups.items():
        if event not in expected or not isinstance(entries, list):
            continue
        slug = expected[event]
        for gi, group in enumerate(entries):
            if not isinstance(group, dict):
                continue
            nested = group.get("hooks")
            commands = nested if isinstance(nested, list) else [group]
            for ci, hook in enumerate(commands):
                if not isinstance(hook, dict) or not isinstance(hook.get("command"), str):
                    continue
                command = hook["command"]
                owned = False
                try:
                    args = shlex.split(command)
                    if provider == "claude-code":
                        if slug == "team-question":
                            owned = is_owned_entry({"command": args[0], "args": args[1:]}, Path(shim).with_name("team_question_hook.py"))
                        else:
                            generated = install.hook_command(slug)
                            # The exact curl envelope is corroborated by this
                            # installation's MCP shim, never by a URL substring.
                            url = re.search(r"-X POST (\S+)/(?:api/v1/agent-mail/hooks)/" + re.escape(slug), command)
                            if url:
                                generated = generated.replace(install.synth_city_base_url(), url.group(1))
                                owned = command == generated
                    elif len(args) == 8 and args[2] in ("--deck-url", "--synth-city-url"):
                        owned = (is_owned_entry({"command": args[0], "args": [args[1]]}, Path(shim).with_name("agent_mail_hook.py"))
                                 and args[4:] == ["--provider", provider, "--event", slug])
                except (ValueError, IndexError):
                    pass
                if owned:
                    found = True
                    if "--deck-url" in args:
                        args[args.index("--deck-url")] = "--synth-city-url"
                        location = ("hooks", event, gi, "hooks", ci, "command") if isinstance(nested, list) else ("hooks", event, gi, "command")
                        replacements.append((location, shlex.join(args)))
    for location, value in replacements:
        text = edit_json(text, location, value)
    return found, text


def _paths(provider):
    from app.services import agent_mail_install_service as i
    if provider == "claude-code":
        return [(i.get_claude_user_config_file(), "mcpServers", i.get_claude_user_settings_file())]
    if provider == "muse-cli":
        path = i.muse_settings_path()
        return [(path, "mcpServers", path)]
    if provider == "codex-cli":
        return [(i.get_codex_home() / "config.toml", "mcp_servers", i.codex_hooks_path())]
    if provider == "copilot-cli":
        return [(i.get_copilot_home() / "mcp-config.json", "mcpServers", i.get_copilot_home() / "hooks" / (OLD + ".json"))]
    return [(path, "mcp", None) for path in i.opencode_config_paths()]


def executor(provider):
    from app.services import agent_mail_install_service as i
    return i._codex_executor() if provider == "codex-cli" else i._copilot_executor() if provider == "copilot-cli" else None


def cli_entries(provider, cli):
    if cli is None:
        raise Incomplete("cli_unavailable")
    result = cli.execute("mcp", ["list", "--json"], timeout=15)
    if result.exit_code:
        raise Incomplete("cli_list_failed")
    return parse_cli_entries(provider, result.stdout)


def same_launch(listed, captured):
    return isinstance(listed, dict) and all(listed.get(key) == captured.get(key) for key in ("command", "args", "env"))


def _registration_text(text, key, entry, *, toml=False, remove=False, both=False):
    if toml:
        doc = tomlkit.parse(text)
        servers = doc[key]
        if not remove and not both:
            servers[NEW] = entry
        servers.pop(OLD, None)
        return tomlkit.dumps(doc)
    if remove or both:
        return edit_json(text, (key, OLD), None, remove=True)
    text = edit_json(text, (key, OLD), entry)
    return edit_json(text, (key, OLD), None, rename=NEW)


def discover(provider):
    """Return fully captured independent artifacts plus value-free findings."""
    from app.services import agent_mail_install_service as install
    shim, records, findings = Path(install.shim_path()), [], []
    for path, key, hookpath in _paths(provider):
        if not path.exists():
            continue
        try:
            source = snapshot(path)
            text = decoded(source["before"]).decode("utf-8")
            toml = path.suffix == ".toml"
            doc = tomlkit.parse(text).unwrap() if toml else read_json(text)
            servers = doc.get(key, {})
            if not isinstance(servers, dict):
                raise Attention("registration_capture")
            if OLD not in servers:
                continue
            old = servers[OLD]
            if not is_owned_entry(old, shim):
                raise Attention("ownership_unproven")
            new = renamed_entry(old)
            hookfiles = []
            updated_hooks = None
            if hookpath:
                hook = source if hookpath == path else snapshot(hookpath)
                if hook["before"] is None:
                    raise Attention("hooks_unproven")
                found, updated_hooks = _hooks(decoded(hook["before"]).decode("utf-8"), provider, shim)
                if not found:
                    raise Attention("hooks_unproven")
                if hookpath != path:
                    hook["after"] = encoded(updated_hooks.encode())
                    hookfiles.append(hook)
            if provider in ("codex-cli", "copilot-cli"):
                listed = cli_entries(provider, executor(provider))
                listed_old = listed.get(OLD)
                if not is_owned_entry(listed_old, shim):
                    raise Attention("cli_ownership_unproven")
                # Full source config is captured; parsed CLI launch evidence
                # must agree rather than silently selecting one of two values.
                if not same_launch(listed_old, old):
                    raise Attention("cli_capture_disagrees")
            both = NEW in servers
            if both and (not is_owned_entry(servers[NEW], shim) or servers[NEW] != new):
                raise Attention("registration_conflict")
            base = updated_hooks if hookpath == path else text
            source["removed"] = encoded(_registration_text(base, key, new, toml=toml, remove=True).encode())
            source["after"] = encoded(_registration_text(base, key, new, toml=toml, both=both).encode())
            if provider == "copilot-cli":
                destination = snapshot(hookpath.with_name(NEW + ".json"))
                if destination["before"] not in (None, hookfiles[0]["after"]):
                    raise Attention("hooks_destination_conflict")
                destination["after"] = hookfiles[0]["after"]
                hookfiles[0]["after"] = None
                hookfiles.append(destination)
            identity = hashlib.sha256((provider + ":mcp:" + str(path.absolute())).encode()).hexdigest()
            records.append({"id": identity, "provider": provider, "artifact": "mcp", "stage": "captured",
                            "files": [source, *hookfiles], "entry": new, "entry_key": key,
                            "both": both, "cli": provider in ("codex-cli", "copilot-cli")})
        except Attention as exc:
            findings.append({"state": "needs_attention", "stage": str(exc)})
        except (OSError, UnicodeError, ValueError, Incomplete) as exc:
            findings.append({"state": "incomplete", "stage": str(exc) if isinstance(exc, Incomplete) else "capture_failed"})
    if provider == "opencode-cli":
        oldpath = install.opencode_plugin_path().with_name(OLD_PLUGIN)
        if oldpath.exists():
            try:
                source = snapshot(oldpath)
                text = decoded(source["before"]).decode("utf-8")
                if not text.startswith("// " + OLD_MARKER + "."):
                    raise Attention("plugin_ownership_unproven")
                updated = text.replace("// " + OLD_MARKER + ".", "// " + NEW_MARKER + ".", 1)
                updated = re.sub(r"(?m)^export const ClaudeDeckAgentMailPlugin\b", "export const AlbiexSynthCityAgentMailPlugin", updated)
                # Rename generated environment reads, never the captured URL
                # literal (which may itself contain an old spelling).
                prefix = "const DECK_URL = ("
                start = updated.find(prefix)
                if start < 0:
                    raise Attention("plugin_url_capture")
                start += len(prefix)
                try:
                    url, size = json.JSONDecoder().raw_decode(updated[start:])
                except ValueError:
                    raise Attention("plugin_url_capture") from None
                if not isinstance(url, str):
                    raise Attention("plugin_url_capture")
                tail = updated[start + size:]
                tail = re.sub(r"^( \|\| process\.env\.)CLAUDE_DECK_URL\b", r"\1SYNTH_CITY_URL", tail, count=1)
                tail = re.sub(r"(?m)^(const PROVIDER = process\.env\.)CLAUDE_DECK_PROVIDER\b", r"\1SYNTH_CITY_PROVIDER", tail)
                tail = re.sub(r'(?m)^(    const teamPresetID = envInt\(")CLAUDE_DECK_TEAM_PRESET_ID("\);)$',
                              r'\1SYNTH_CITY_TEAM_PRESET_ID\2', tail)
                tail = re.sub(r'(?m)^(    const teamSlotID = envInt\(")CLAUDE_DECK_TEAM_SLOT_ID("\);)$',
                              r'\1SYNTH_CITY_TEAM_SLOT_ID\2', tail)
                updated = updated[:start] + updated[start:start + size] + tail
                if "export const AlbiexSynthCityAgentMailPlugin" not in updated:
                    raise Attention("plugin_capture")
                destination = snapshot(oldpath.with_name(NEW_PLUGIN))
                destination["after"] = encoded(updated.encode())
                if destination["before"] not in (None, destination["after"]):
                    raise Attention("plugin_destination_conflict")
                source["after"] = None
                identity = hashlib.sha256((provider + ":plugin:" + str(oldpath.absolute())).encode()).hexdigest()
                records.append({"id": identity, "provider": provider, "artifact": "plugin", "stage": "captured",
                                "files": [source, destination], "cli": False})
            except Attention as exc:
                findings.append({"state": "needs_attention", "stage": str(exc)})
            except (OSError, UnicodeError):
                findings.append({"state": "incomplete", "stage": "plugin_capture_failed"})
    # A same-provider both-name conflict blocks every provider artifact. An
    # independently unowned OpenCode artifact does not claim its owned sibling.
    if any(row["state"] == "incomplete" or row["stage"].endswith("conflict") for row in findings):
        records = []
    return records, findings
