# Pi Agent Mail tools

The Pi tool list must match the real standalone MCP server. Keep the private close tool out of the public list.

After you change an MCP tool, run these commands from this directory. Use Python with the backend MCP dependencies installed.

```sh
python sync_manifest.py
python sync_manifest.py --check
```

The command reads tool definitions. It does not register an agent or call the Deck API.

Backend tests compare the complete list with the real server. The pinned Pi runtime tests check argument validation. Fixture transport tests keep the existing schema check, pane fence, and uncertain outcome rules.
