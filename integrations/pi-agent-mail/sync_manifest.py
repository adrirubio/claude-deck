#!/usr/bin/env python3
"""Update the static Pi tools from the standalone MCP server. Do not register."""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path


def render_manifest() -> str:
    root = Path(__file__).resolve().parents[2]
    os.environ["CLAUDE_DECK_PROVIDER"] = "pi-cli"
    spec = importlib.util.spec_from_file_location(
        "pi_manifest_shim", root / "backend/mcp_shim/agent_mail_server.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tools = asyncio.run(module.mcp.list_tools())
    public = []
    private = []
    for tool in sorted(tools, key=lambda item: item.name):
        entry = {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool.inputSchema,
        }
        if tool.name.startswith("deck_"):
            public.append(entry)
        elif tool.name == "__deck_mail_close_generation":
            private.append(entry)
        else:
            raise ValueError(f"Unexpected MCP tool: {tool.name}")
    assert len(private) == 1, "Expected one private close tool"
    return (
        "export const manifest = " + json.dumps(public, indent=2) + " as const\n\n"
        "export const privateTools = " + json.dumps(private, indent=2) + " as const\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = Path(__file__).with_name("manifest.ts")
    expected = render_manifest()
    if args.check:
        if path.read_text() != expected:
            print("Pi tool list differs from the MCP server. Run sync_manifest.py.")
            return 1
        print("Pi tool list matches the MCP server.")
    else:
        path.write_text(expected)
        print("Updated the Pi tool list from the MCP server.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
