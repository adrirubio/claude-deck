---
layout: home

hero:
  name: Claude Deck
  text: Documentation
  tagline: Visual configuration, live session control, and safe Codex CLI management
  actions:
    - theme: brand
      text: Get Started
      link: /guide/
    - theme: alt
      text: View on GitHub
      link: https://github.com/adrirubio/claude-deck

features:
  - icon: 🌉
    title: Agent Bridge
    details: Monitor, spawn, resume, fork, and attach to live Claude Code and Codex CLI tmux sessions from the browser.
  - icon: 🎛️
    title: Provider-Aware Configuration
    details: Manage Claude Code JSON settings and safe Codex TOML settings, profiles, runtime options, and feature flags.
  - icon: 📊
    title: Dashboard & Usage
    details: See configuration status, context windows, session activity, project state, and Claude Code token usage in one place.
  - icon: 💬
    title: Sessions & Transcripts
    details: Browse conversation history with full message details, tool use, and token tracking.
  - icon: 🤖
    title: Agents & Skills
    details: Create custom agent configurations and discover skills from the community.
  - icon: 💾
    title: Backup & Export
    details: Protect Claude Code setups with backup and restore, and create redacted export-only Codex backups.
  - icon: 🧭
    title: Project Discovery
    details: Discover project directories from local agent state or add them with the directory browser.
---

## Release Focus: Codex Support

The next release makes Codex CLI a stable provider in Claude Deck. Codex sessions can live next to Claude Code sessions in Agent Bridge, and the Config page now includes a Codex-specific editor for safe TOML settings, profile diagnostics, MCP/plugin inventory, and feature flags from `codex features list`.

Claude Deck still keeps provider boundaries explicit. Codex usage metrics, context charts, and transcript browsing are not shown as if they were Claude Code data. Codex backups are redacted exports and automatic restore is refused until Codex exposes a safe restore contract.
