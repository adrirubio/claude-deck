# Changelog

All notable changes to Claude Deck will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [3.1.0] - 2026-10-14

v3.1 makes the factory pages readable for a Director, and hardens the local API.

### Upgrade notes
- **Node.js 22.12 or later** is now required to build and test the frontend. Vite 8 and Vitest 5 need it. `scripts/install.sh` checks the version.
- **Agent Mail authentication is strict by default.** Agents need their Mail session credential, and external actors read and write only threads they created or are addressed in. When a Director key is configured, Agent Mail setup, member edits, actor creation and the UI's Mail reads need it. An install with no Director key keeps working as before and shows a recommendation to set one. An explicit opt-out restores the earlier unauthenticated reads; writes always need a key. See the Agent Mail guide.
- **Controller upgrades:** the maintenance upgrade now tolerates nullable columns that a startup migration adds, and accepts checkpoints from owners that work in a leased dispatch workspace. Its CLI prints the refusal reason code.

### Added
- **Overview:** answers what has happened, what is happening and what still needs to happen. It shows a campaign progress bar, a team summary card, the supervisor's status, unanswered release reminders, and items that wait for someone.
- **Teams:** a readable team page (header and members first, editing behind Edit team), a link from a team to its parent issue, and From Bridge and From Mail creation from the selected sessions only.
- **Audit:** a plain-language delivery summary, a readable activity feed, a "Needs a look" panel for refused agent requests, and Team, Repository and Window selects. Events unlock only when the Director chooses to.
- **Agent Mail:** "Waiting on someone" first, conversations grouped by team, a compact roster, the sender shown as Deck, Director or agent, and Mail setup on each harness page.
- **Live sessions:** a readable session list with Kill away from Watch, Team lanes that show every member four at a time, and the shared Director-key prompt for new sessions.
- **Harnesses:** breadcrumbs, a page per harness with grouped native pages, a compact list, and local projects folded into harness pages.
- **Factory signals:** one shared agent status across Agent Mail, Live sessions and Teams; an attention signal when required CI cannot be read; an optional supervisor check-in; unattended-launch results.
- **E2E journeys:** an isolated Playwright instance with deterministic seed data, and a required `e2e` CI job. Every lane has active journeys, including contrast, keyboard and a no-flicker check of the factory pages.

### Changed
- **Work and Repositories** are the single home of a work item and of repository setup. The Work list is compact and defaults to active work. Repository setup no longer asks for the key on entry or requires hand-typed paths.
- **Plain-language copy** on Director-facing pages: for example "Teams", "Director" and "updated" times.
- **Frontend dependencies:** Tailwind CSS 4, Vite 8 with plugin-react 6, lucide-react 1.x and Vitest 5.

### Fixed
- **Flicker:** the factory pages no longer show a "Refreshing…" line or flash "Previous" labels during each background refresh.
- **Delivery:** a pending check no longer uses up the merge retry budget; draft PRs are never promoted or auto-merged, and a configured review-hold label is honoured; a status report cannot move a merged item back to escalated.
- **Dispatch:** the Leader acknowledgement deadline starts when the plan request arrives; native owner contact renews in a leased dispatch workspace; workspace-release reminders are bounded; a merged item keeps no active continuation revision.
- **Factory pages** stop polling after a permanent 404 or 422, show local times in the right time zone, show a way back and plain errors on the Work item page, and keep the reader's place on Audit.
- **Accessibility:** WCAG AA contrast fixes in both themes (team cards, Autonomy, Agent Mail badges, Live sessions counts, Team lanes labels).

### Security
- **Local API hardening:** settings writes need the Director key when one is configured; Agent Mail authentication defaults as described in the upgrade notes; the Agent Mail install routes need the Director key.
- **Unattended team sessions:** interactive question prompts are blocked, and workspaces are pre-trusted for team sessions.


## [3.0.0] - 2026-10-09

### Added
- **Overview, Work and Repositories**: Show factory work counts, owners, waiting reasons, pull request context, and watched-scope intake, polling and overlap observations across teams.
- **Harnesses**: Show the versioned operations and readiness catalog for Claude Code, Codex CLI, GitHub Copilot CLI, OpenCode CLI and Pi, with guarded native pages. The catalog does not create an editor or grant authority.
- **Guided repository configuration**: `/repositories/new` keeps the draft, the saved configuration, the reviewed launch and the activation as separate steps.
- **Explicit Leader authority**: Teams sets the Leader through the team's `leader_slot_id`.
- **Audit history and metrics**: The factory audit ledger and delivery metrics record observed actions and outcomes. See `docs/guide/factory-audit-and-metrics.md`.
- **Agent Bridge**: Codex CLI sessions can launch on Amazon Bedrock with a provider-aware platform selector, a per-session `model_provider = "amazon-bedrock"` override, and optional AWS region, profile and model fields.
- **Version sync**: `scripts/bump-version.sh` also syncs `frontend/package-lock.json`, `backend/uv.lock` and the backend `app_version`.

### Changed
- **Product positioning**: Claude Deck is a self-hosted workspace to observe and intervene in bounded coding-agent attempts on GitHub issues, with mixed harnesses, visible policies and recovery controls. Native configuration and manual sessions stay available without automatic dispatch.
- **Version**: The runtime version response and the application package metadata report 3.0.0.
- **CI**: Product CI also runs for pull requests and pushes on `release/v3.0.0`.
- **Upgrade**: Existing databases upgrade in place. Back up `backend/claude_registry.db` first. Downgrade restores that backup. See `docs/guide/installation.md`.

### Fixed
- **Agent Teams**: Unsafe multi-slot Codex `resume --last` launches in the same repository are blocked. Codex hook session keys stay distinct per team slot.
- **Agent Mail**: Compose labels offline and not-wakeable recipients clearly before storing mail for later delivery.

### Evidence limits
- Finished is a tracking state. It is not independently reviewed delivery, reliability, cost or time saved.
- Cost is unknown. This release makes no performance, cost or time-saving claim.
- Native adapters stay provider-specific. Catalog support does not mean equal native capability across harnesses.
- The manual Bridge trial (V14) is not performed. Pilot participants, comparisons and human benefit measurements are not available.

## [2.0.1] - 2026-06-20

### Added
- **Claude Code Config**: Added coverage for current Claude Code settings such as advisor model, fallback model chains, Remote Control startup, push notifications, notification channel, theme, auto-compact, file checkpointing, and newer safety/privacy toggles.
- **Config editor helpers**: Added validated JSON editing for complex settings objects/arrays and a boolean map editor for plugin enablement.

### Changed
- **Dashboard**: Dashboard cards and navigation are now provider-aware so Codex selection does not show inaccessible Claude Code-only cards as if they were Codex pages.
- **Codex provider pages**: Codex MCP servers, plugins, feature flags, and configuration inventory now route to provider-appropriate pages instead of dead-end dashboard stats.
- **Claude Code settings**: Plugin marketplace settings, worktree symlink directories, sandbox Mach lookup settings, and managed marketplace policy values now use the JSON shapes documented by Claude Code.
- **Docs**: Refreshed release, Config, and Dashboard docs to describe the 2.0.1 stabilization fixes.

### Fixed
- **Usage costs**: Claude Code usage dashboards now calculate costs for current Claude model aliases such as Sonnet 5, Fable 5, Opus 4.6/4.7/4.8, Sonnet 4.6, and Haiku 4.5 instead of showing `$0.00` with non-zero token usage.
- **Usage cache**: Usage cache keys now include the pricing table version, avoiding stale zero-cost aggregates after pricing support changes.
- **Config defaults**: Corrected stale UI defaults/descriptions for auto-updates, sandbox auto-allow, thinking summaries, plan auto-mode, and turn duration.

## [2.0.0] - 2026-06-19

### Added
- **Agent Mail**: Durable local mailbox coordination for Claude Code and Codex CLI agents
  - Per-repository and Agent Team slot participants with role and charter metadata
  - Structured direct messages, context requests, handoffs, replies, read state, acknowledgements, and inbox load
  - Agent-facing MCP tools for team discovery, inbox checks, replies, context requests, and handoffs
  - One-click install and uninstall flows for Claude Code and Codex MCP/hooks configuration with best-effort backups
  - Best-effort tmux wake nudges for visible sessions through Agent Bridge
- **Agent Teams**: Saved rosters for launching or reusing local agent sessions
  - Manual team creation, team creation from Agent Mail participants, and team creation from visible Agent Bridge sessions
  - Team slots with provider, repository, display name, role, charter, bootstrap prompt, launch mode, provider options, and enabled state
  - Launch planning that checks provider availability, Agent Mail readiness, reusable tmux sessions, disabled slots, and launch option validity
  - Same-repository planner/reviewer and implementer workflows through distinct Agent Mail team-slot identities
- **External local orchestration**: Token-bound same-machine Agent Mail API for tools such as OpenClaw
  - External actor registration, member discovery, direct messages, broadcasts, context requests, handoffs, replies, request status, bounded waits, and acknowledgements
  - Agent Teams launch endpoints usable by local external automation after plan review
- **Agent Bridge session creation**: Searchable project picker and Codex model/profile selectors with custom-value fallback.

### Changed
- **Multi-agent workflow**: Agent Bridge, Agent Mail, and Agent Teams are now the supported surfaces for local session visibility, communication, and reusable rosters.
- **Agent Mail dashboard**: Connected, observed-only, not wakeable, and inbox-load states now describe delivery behavior more explicitly.
- **Agent Mail docs**: Setup documentation now explains required MCP/hooks configuration and the current tmux-only wake path.
- **Dependencies**: Merged low-risk package updates including React package alignment and small UI/runtime dependency updates.

### Removed
- **Presence**: Removed the Presence frontend route, backend route/service, hook integration, tests, and navigation. Existing inert SQLite tables may remain in local databases, but no active backend polling or UI surface uses them.

### Fixed
- **Agent Mail install feedback**: Install and uninstall actions now refresh status and show clearer results for Claude Code and Codex configuration.
- **Agent Mail roster accuracy**: Dashboard member counts now distinguish durable members from observed sessions and collapse bridge-observed/MCP sessions under the same member where appropriate.
- **Agent Mail hook output**: Claude Code and Codex hooks return provider-valid JSON so hook failures are not shown for normal mailbox checks.
- **Agent Bridge startup flow**: The development script now avoids transient frontend proxy noise by coordinating backend/frontend startup more carefully.

### Security
- **External Agent Mail boundary**: External actor creation is loopback-only, external endpoints require bearer tokens, and per-actor rate limits protect the local orchestration surface within Claude Deck's existing local trust model.

## [1.3.1] - 2026-06-11

### Fixed
- **Frontend runtime alignment**: Aligned `react` and `react-is` with the installed React DOM version to avoid production render failures from mixed React package versions.

### Changed
- **Documentation screenshots**: Refreshed README screenshots, including the Agent Bridge mixed-provider view, dashboard, config, and MCP visuals used for the release.

## [1.3.0] - 2026-06-08

### Added
- **Codex CLI support**: Provider-aware Codex support is now stable enough for everyday use
  - Agent Bridge discovers mixed Claude Code and Codex tmux sessions
  - Codex sessions can be spawned, resumed, forked, attached to, and killed from the UI
  - Provider switcher keeps Claude Code and Codex surfaces separate instead of showing unsupported pages
- **Codex Config**: Safe TOML editor for Codex settings
  - Structured General and Runtime cards for model, profile, reasoning effort, sandbox mode, approval policy, search, strict config, and alternate screen behavior
  - Dropdowns for known Codex enum values while keeping open-ended fields editable
  - Help tooltips for documented settings and feature flags
  - Feature flag inventory from `codex features list`, including editable overrides for flags such as goals, memories, hooks, multi-agent, shell tool, and network proxy
  - Profile diagnostics for active/default profile resolution, profile files, overrides, missing references, and malformed profiles
- **Codex MCP and Plugins**: Provider inventory and safe CLI-backed mutations
  - MCP inventory from `codex mcp list --json`
  - MCP add/remove through the Codex CLI with validation
  - Plugin inventory from `codex plugin list`
  - Plugin install/remove where the installed Codex CLI exposes safe commands
- **Codex Backup Export**: Redacted export-only backups for Codex config, profile files, rules, and provider inventory metadata
- **Projects**: Project discovery is easier, with directory browsing support when adding project paths

### Changed
- **Provider model**: Provider status, capabilities, diagnostics, and normalized errors now drive the UI for Claude Code and Codex CLI.
- **Documentation**: README and VitePress docs now describe the stable Codex support surface, the remaining provider boundaries, and the release-ready dependency updates.
- **Frontend toolchain**: Updated TypeScript to 6.0.3, `@vitejs/plugin-react` to 5.1.4, ESLint tooling, React DOM, PostCSS, Tailwind Merge, and Node types.

### Security
- **Codex privacy boundary**: Codex auth, history, model cache, SQLite state, prompt text, and raw cache payloads remain excluded from raw viewers and backups.
- **Codex restore policy**: Automatic Codex restore is refused because exports intentionally omit provider-owned local state.

## [1.2.0] - 2026-04-22

### Added
- **CC Bridge**: Live terminal bridge to Claude Code sessions running in tmux
  - Multi-terminal grid layout supporting up to 4 simultaneous panes (auto-layout: 1, 2-column, or 2x2 grid)
  - Per-pane read-only/interactive mode toggle, fullscreen, attach/detach, and close controls
  - Active terminal focus indicator — green glow on the focused pane
  - Session discovery via `tmux list-panes` with auto-refresh polling
  - Spawn new Claude Code sessions (plain, worktree, or resume mode) from the UI
  - Kill sessions with optional worktree cleanup
  - WebSocket-based PTY relay with xterm.js (WebGL rendering, web links)
- **Projects**: Discover projects from `~/.claude/projects/` session history
- **Dashboard**: Cache stats in context to avoid re-fetching on navigation
- **Documentation**: VitePress documentation site with guide, features, and API reference

### Fixed
- **CC Bridge**: Prevent orphaned `tmux attach-session` processes from accumulating on server reload/crash via `PR_SET_PDEATHSIG` and startup cleanup
- **CC Bridge**: Fix terminal not rendering in React StrictMode due to race condition in async attach flow

## [1.1.0] - 2026-03-03

### Added
- **CC Bridge**: Live terminal bridge to Claude Code sessions running in tmux
  - Multi-terminal grid layout supporting up to 4 simultaneous panes (auto-layout: 1, 2-column, or 2x2 grid)
  - Per-pane read-only/interactive mode toggle, fullscreen, attach/detach, and close controls
  - Active terminal focus indicator — green glow on the focused pane
  - Session discovery via `tmux list-panes` with auto-refresh polling
  - Spawn new Claude Code sessions (plain, worktree, or resume mode) from the UI
  - Kill sessions with optional worktree cleanup
  - WebSocket-based PTY relay with xterm.js (WebGL rendering, web links)
- **Projects**: Discover projects from `~/.claude/projects/` session history
- **Dashboard**: Cache stats in context to avoid re-fetching on navigation
- **Documentation**: VitePress documentation site with guide, features, and API reference

### Fixed
- **CC Bridge**: Prevent orphaned `tmux attach-session` processes from accumulating on server reload/crash via `PR_SET_PDEATHSIG` and startup cleanup
- **CC Bridge**: Fix terminal not rendering in React StrictMode due to race condition in async attach flow

## [1.0.0] - 2026-01-22

### Added
- Initial release of Claude Deck
- **Dashboard**: Overview of Claude Code configuration status and usage statistics
- **MCP Server Management**: Add, edit, remove, and configure MCP servers (global and project-scoped)
- **Commands Management**: Create and manage custom slash commands with argument support
- **Plugins Management**: Install, configure, and manage Claude Code plugins
- **Hooks Management**: Configure pre/post hooks for various Claude Code events
- **Permissions Management**: Manage allowed and denied permissions for tools
- **Backup & Restore**: Full backup and restore functionality for all configurations
- **Project Management**: Support for project-specific configurations
- **CLI Executor**: Execute Claude CLI commands from the web interface
- **Usage Tracking**: Track and visualize API usage and costs

### Technical
- FastAPI backend with async SQLAlchemy and SQLite
- React 18 frontend with TypeScript, Vite, and shadcn/ui
- RESTful API at `/api/v1/`
- CORS configured for local development

[Unreleased]: https://github.com/adrirubio/claude-deck/compare/v2.0.1...HEAD
[2.0.1]: https://github.com/adrirubio/claude-deck/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/adrirubio/claude-deck/compare/v1.3.1...v2.0.0
[1.3.1]: https://github.com/adrirubio/claude-deck/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/adrirubio/claude-deck/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/adrirubio/claude-deck/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/adrirubio/claude-deck/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/adrirubio/claude-deck/releases/tag/v1.0.0
