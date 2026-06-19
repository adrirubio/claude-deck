---
layout: home

hero:
  name: Claude Deck
  text: Documentation
  tagline: Local agent coordination, live session control, and provider-aware configuration
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
  - icon: ✉️
    title: Agent Mail
    details: Route structured context requests, handoffs, replies, and inbox state between local Claude Code and Codex agents.
  - icon: 👥
    title: Agent Teams
    details: Save project, DevOps, release, or same-repo rosters and launch or reuse the sessions that belong to them.
  - icon: 🎛️
    title: Provider-Aware Configuration
    details: Manage Claude Code JSON settings and safe Codex TOML settings, profiles, runtime options, and feature flags.
  - icon: 📊
    title: Dashboard & Usage
    details: See configuration status, context windows, session activity, project state, and Claude Code token usage in one place.
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

## Release Focus: 2.0 Team Coordination

Claude Deck 2.0.0 makes Agent Mail and Agent Teams the main coordination layer for local coding agents. Agents can keep durable per-repository or per-team-slot identities, ask each other for context, hand work across repositories, and keep an inspectable mailbox without turning Claude Deck into a general chat product.

Presence has been removed. Agent Bridge, Agent Mail, and Agent Teams are now the supported surfaces for live session visibility, communication, and reusable rosters. Codex support still keeps provider boundaries explicit: usage metrics, context charts, and transcript browsing are not shown as if they were Claude Code data, and Codex backups remain redacted exports.
