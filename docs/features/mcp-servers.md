# MCP Servers

Manage Model Context Protocol servers — the integrations that give Claude access to external tools, resources, and prompts.

## Overview

The MCP Servers page has two tabs:

- **My Servers** — view and manage all configured MCP servers
- **Registry** — browse and install servers from the [MCP Registry](https://registry.modelcontextprotocol.io)

## How to Use

### Viewing Servers

The My Servers tab shows all configured servers as cards displaying:

- Server name and connection status (connected, failed, needs-auth, not-tested)
- Transport type (stdio command or HTTP/SSE URL)
- Scope badge (user, project, plugin, or managed)
- Tool, resource, and prompt counts (from cached test results)
- Enable/disable toggle

### Adding a Server

Click **"Add Server"** to open the wizard:

1. Enter a server name
2. Choose the transport type:
   - **stdio** — command-based servers (e.g., `node`, `npx`, `python`)
   - **http** — HTTP POST JSON-RPC servers (supports OAuth tokens)
   - **sse** — Server-Sent Events servers
3. Configure connection details (command + args for stdio, URL for http/sse)
4. Optionally set environment variables and headers
5. Choose the scope (user or project)

### Testing Servers

Click the **test button** on a server card or use **"Test All"** to verify connectivity. Testing:

- Verifies the command or URL is reachable
- Communicates via the MCP JSON-RPC protocol
- Discovers available tools, resources, and prompts
- Caches results for display on the card and detail view

::: info
Tests have a 30-second timeout. npx-based servers may need extra startup time.
:::

### Server Detail View

Click a server card to see full details:

- Complete configuration (command, arguments, environment variables)
- Cached connection test results
- Lists of discovered tools, resources, and prompts (up to 200 items)
- Server version and capabilities
- Approval settings override

### Server Approval Settings

Expand the **Approval Settings** panel to configure how Claude handles tool approvals:

| Mode | Behavior |
|------|----------|
| Ask every time | Prompt before each tool use (default) |
| Always allow | Auto-approve all tool calls |
| Always deny | Block all tool calls |

Per-server overrides let you set different policies for individual servers.

### Browsing the Registry

Switch to the **Registry** tab to discover pre-built MCP servers. You can browse by category, search by name, and install servers directly into your configuration.

## Configuration

MCP servers are stored in two locations:

| File | Scope | Description |
|------|-------|-------------|
| `~/.claude.json` | User | Global MCP servers |
| `.mcp.json` | Project | Project-specific servers |

Plugin-provided and managed (enterprise) servers are read-only and shown with distinct badges.

## Tips

- Use **project-scoped** servers for tools specific to a codebase (e.g., database access).
- Use **user-scoped** servers for tools you want everywhere (e.g., web search).
- **Test servers** after adding them to verify connectivity and discover available tools.
- **Managed servers** (enterprise) appear with an amber badge and cannot be modified.
- Environment variables in server configs are masked in the UI for security.
