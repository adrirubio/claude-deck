import argparse
import importlib.util
import json
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("deck_pi_manifest", root / "backend/mcp_shim/agent_mail_server.py")
    shim = importlib.util.module_from_spec(spec)
    previous = os.environ.get("CLAUDE_DECK_PROVIDER")
    os.environ["CLAUDE_DECK_PROVIDER"] = "pi-cli"
    try:
        spec.loader.exec_module(shim)
    finally:
        if previous is None:
            os.environ.pop("CLAUDE_DECK_PROVIDER", None)
        else:
            os.environ["CLAUDE_DECK_PROVIDER"] = previous
    public = []
    private = []
    for tool in shim.mcp._tool_manager.list_tools():
        entry = {"name": tool.name, "description": tool.description, "inputSchema": tool.parameters}
        if tool.name.startswith("deck_"):
            public.append(entry)
        elif tool.name == "__deck_mail_close_generation":
            private.append(entry)
        else:
            raise SystemExit("Unexpected non-public MCP tool")
    content = "export const manifest = " + json.dumps(sorted(public, key=lambda tool: tool["name"]), indent=2) + " as const\n"
    content += "\nexport const privateTools = " + json.dumps(private, indent=2) + " as const\n"
    destination = root / "integrations/pi-agent-mail/manifest.ts"
    if args.check:
        if not destination.exists() or destination.read_text() != content:
            raise SystemExit("Pi mail manifest differs from the MCP server")
    else:
        destination.write_text(content)


if __name__ == "__main__":
    main()
