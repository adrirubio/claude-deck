# PR2 GitHub App rollout

PR2 adds per-agent commit identity, repository-scoped push credentials, and Deck-owned pull-request creation. Roll it out one repository at a time.

## GitHub App

Create or select a GitHub App and install it only on repositories that use App mode. Grant these repository permissions:

- **Contents: Read and write** for branch pushes.
- **Pull requests: Read and write** for PR discovery and creation.
- **Metadata: Read-only**, which GitHub grants automatically.
- Add checks/status read permissions if the repository restricts those endpoints.

Do not grant Administration, Workflows, or any branch-protection/ruleset bypass to
the App. Deck mints separate installation tokens: panes receive only Contents
write, while the backend receives Contents read plus Pull requests write. Keep
protected-branch rules as the final guard against a direct push to the base branch.

Branch protection, App installation, and repository provisioning remain manual operator actions.

## Backend configuration

Put these values in `backend/.env`, not in the exported backend environment or tmux global environment:

```dotenv
GITHUB_APP_ID=<numeric-app-id>
GITHUB_APP_PRIVATE_KEY_PATH=/absolute/path/to/private-key.pem
GITHUB_APP_BOT_LOGIN=<app-slug>[bot]
```

Set mode `0600` on both `.env` and the private key. Restart the backend after a setting or key change. App JWTs and installation tokens must never appear in prompts, status notes, logs, URLs, or tmux configuration.

Run one backend worker for App-mode dispatch. The installation-token cache and
revocation locks are process-local. Before a planned backend restart, disable
autonomy and drain every App-mode workspace lease. After an unplanned restart
with an active App lease, Deck retains the token's persisted expiry quarantine
and refuses release or reassignment until that time passes, unless an operator
revokes the GitHub App installation first. Keep autonomy disabled while such a
lease is quarantined. A restarted process cannot revoke plaintext tokens that
intentionally were never persisted.

## Scope reset gate

Before resetting authentication state for any scope:

1. Disable autonomy for every affected preset.
2. Verify every affected `github_workspaces.leased_item_id` is `NULL`.
3. In one transaction, set `github_auth_mode = 'unknown'` and `github_app_installation_id = NULL`.
4. Read both columns back before re-enabling autonomy.

Never reset a live scope. A leased worktree credential helper intentionally reads the persisted installation id.

## Staged rollout

1. Deploy PR2 while existing scopes remain in ambient mode.
2. Select one sandbox repository with an installed App.
3. Reset that idle scope with the gate above.
4. Enable one dispatch and verify the worktree commit identity, authenticated push, Deck-created PR, and managed-config cleanup after release.
5. Expand to additional repositories only after the sandbox completes the full lifecycle.

Expected diagnostics:

- `app_not_installed`: the persisted installation cannot mint for this repository.
- `app_auth_unconfigured`: App id or private key configuration is incomplete.
- `app_mode_bot_login_unset`: App-mode adoption cannot verify the expected bot author.
- `queued_auth_mode_unresolved`: Deck could not determine ambient versus App mode before launch.
- `pane_unresolved`: kernel-derived pane ownership could not be established for a credential request.
- HTTP `501` from the credential helper: the deployed backend does not support the PR2 credential route; treat this as a stale mixed-version deployment.

## Rollback

1. Disable autonomy for affected presets.
2. Wait for or manually resolve all leases.
3. Remove the URL-scoped helper and managed worktree identity from unleased test worktrees.
4. Clear App settings and restart the backend.
5. Reset each idle scope to `(unknown, NULL)` using the safety gate.
6. Run one ambient dispatch and verify push, verified `pr_opened`, and release cleanup.

Do not automate GitHub App installation, branch-protection changes, private-key provisioning, or the final production enablement in this rollout.
