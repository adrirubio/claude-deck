# CC Bridge

::: warning Legacy name
The provider-aware feature is now Agent Bridge. This page describes the original Claude Code-only bridge naming; use [Agent Bridge](/features/agent-bridge) for mixed Claude Code and Codex CLI sessions.
:::

Discover and monitor live Claude Code sessions running in tmux with a multi-terminal grid view.

## Overview

CC Bridge provides real-time visibility into Claude Code sessions running in tmux. You can observe up to 4 terminals simultaneously, spawn new sessions, and terminate existing ones.

## How to Use

### Discovering Sessions

The left sidebar automatically discovers active Claude Code tmux sessions. Sessions appear as cards with their name and status.

### Viewing Terminals

Click a session in the sidebar to add it to the terminal grid. The grid supports up to **4 simultaneous panes** in a 2x2 layout.

- Click a session again to remove it from the grid
- Click the **fullscreen** icon on a pane to focus on a single session
- Press **Escape** to exit fullscreen

### Spawning Sessions

Click **"New Session"** to spawn a new Claude Code terminal in tmux. A dialog lets you configure the session before launching.

### Terminating Sessions

Use the **"Kill Session"** button to terminate a running tmux session. A confirmation dialog prevents accidental termination.

## Architecture

CC Bridge uses a PTY relay to stream terminal output:

1. Backend discovers tmux sessions via `tmux ls`
2. Frontend requests terminal content via the API
3. Backend captures pane content with `tmux capture-pane`
4. Terminal output streams to the browser in real-time

## Configuration

CC Bridge is configuration-free. It auto-discovers any active tmux sessions on the system.

::: info
CC Bridge requires tmux to be installed and sessions to be running. If no tmux sessions exist, the sidebar will be empty.
:::

## Tips

- Use the **2x2 grid** to monitor multiple sessions at once — great for parallel development.
- **Fullscreen mode** gives you a focused view of one session.
- Sessions are discovered automatically — no setup needed beyond having tmux running.
