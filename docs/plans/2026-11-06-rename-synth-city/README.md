# Rename: Claude Deck → Albiex Synth City

**Status:** approved by the Director, 6 November 2026; the planning team works from it.

## Why

The "Claude" name carries the risk of legal action. The product becomes **Synth City**, made by **Albiex**. The rename happens in public and quickly. The work moves from `adrirubio` to the new GitHub organisation **`albiexai`**, without losing the project's stars, forks, issues or the users who already know Claude Deck.

## Decisions already made

| Decision | Value |
|---|---|
| Company and logo | Albiex (brand package v2, Transit enamel palette) |
| Product name in copy | Synth City |
| GitHub organisation | `albiexai` (free on 2026-11-06) |
| Product repository | `adrirubio/claude-deck` → transferred and renamed to `albiexai/synth-city` |
| Website repository | `adrirubio/claude-deck-website` → `albiexai/synth-city-website` |
| Domain | `albiex.org` (`albiex.com` is owned and held for later) |
| Publication | The new website is published only after the organisation exists and both repositories are transferred |
| Visibility | The rename is public from the start |

## Keeping stars, forks and users

- **Transfer the repositories; never create new ones.** A transfer keeps stars, watchers, forks, issues, pull requests, Discussions, the wiki and releases, and GitHub redirects the old web, git and API addresses to the new one.
- **Never create a repository at `adrirubio/claude-deck` again.** That would break the redirect.
- **Announce before the transfer:** a pinned Discussion and a README banner on the old repository, "Claude Deck is becoming Synth City", with the date and what changes.
- **Existing installs keep working for a deprecation window.** The new version reads the old names alongside the new ones:
  - environment variables, the MCP server name, the terminal header and the ready marker;
  - on first start, it moves the old database file and backups folder to their new names.
- **`claudedeck.org` redirects every path** to `albiex.org` (301 redirects).

## What changes, and what does not

- **Must change** (anything containing "claude" that identifies the product):
  - user-facing names and copy;
  - environment variables (`CLAUDE_DECK_*`);
  - the MCP server name `claude-deck-mail`;
  - the `Claude-Deck-Terminal-Token` header and the `claude-deck-ready` marker;
  - the database file `claude_registry.db` and the backups folder `~/.claude-registry`;
  - package names (`claude-code-registry-backend`);
  - repository names, the website and the docs.
- **Also renamed (the Director's decision):** the Agent Mail tool names (`deck_check_inbox`, `deck_launch_team`, …). They get a new prefix, and the old `deck_` names stay as aliases during the deprecation window, so existing agent charters and skills keep working.
- **Kept:**
  - names of the Claude Code harness, which is a real third-party product the agents run;
  - old release notes and history.
- **Size:** about 1,470 mentions in 248 tracked files (docs 113, frontend 53, backend 47, scripts 17, integrations 10).

## Phases

### Phase 0: the Director (people only, now)
1. Create the `albiexai` organisation, with Juan and Adrian as owners.
2. Point `albiex.org` at Cloudflare. Plan the `claudedeck.org` redirects.
3. Trademark search for "Albiex" and "Synth City" before launch.
4. Approve this plan, the planning team's roster and its models.

### Phase 1: the rename planning team (a Deck team, plan documents only)
Each item is one GitHub issue and one reviewed pull request under `docs/plans/2026-11-06-rename-synth-city/`:
1. **Inventory.** Every old-name occurrence, classified as user-facing, runtime identifier, docs, or history to keep.
2. **Compatibility design.** For each runtime identifier: the new name, the old-name fallback, the length of the deprecation window, and the first-start migration. Includes the installer's MCP server rename.
3. **Transfer runbook.** The checklist before the transfer, the transfer steps, and the checks afterwards: secrets and variables, rulesets, deploy keys, webhooks, GitHub App installations, Cloudflare Pages, and the release workflow's repository references.
4. **Release and announcement plan.** The release (proposed: v4.0.0, "Synth City, formerly Claude Deck"), the migration guide, the pinned Discussion, the README banner, and the redirect map.
5. **Website and docs plan.** Port the approved mockup (v7d) into the website repository, rename the docs, and list the product captures to retake. They still show "Deck".

### Phase 2: the rename implementation team (a Deck team, code)
Issues generated from Phase 1, on a release branch with CI, merged under the delivery policy.

### Phase 3: cutover day (people)
Transfer and rename both repositories, verify the runbook checks, switch DNS, publish the website at `albiex.org`, and publish the release.

### Phase 4: cleanup (a later release)
Remove the old-name fallbacks after the window, and retire `claudedeck.org`.

## Decided
- **The planning team's roster** is the website plan team's: an AI Leader on Codex, an implementer on Muse Code and a verifier on Codex.
- **The Agent Mail tools are renamed,** with `deck_` aliases during the window.

## Open question for the Director
**The release number.** The Director would like to reset to v1. But the repository already has tags v1.0.0 to v1.3.1 from Claude Deck, and a transfer keeps them, so a new v1.0.0 would collide. Version-sorting tools would also rank v3.1.0 above any new 1.x. **The recommendation is to continue: Synth City v4.0.0**, "formerly Claude Deck". The release plan (Phase 1, item 4) compares both options. The length of the deprecation window (proposed: two minor releases) is decided there too.
