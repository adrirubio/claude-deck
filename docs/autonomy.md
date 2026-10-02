# Autonomous GitHub dispatch

This guide is for the operator of a Deck team. Autonomy is off until you enable it for the team, and a watched repo can also be paused separately.

## Before enabling

1. Give the watcher GitHub access and configure the operator token described below before editing the roster. Add `github_token=<token>` to `backend/.env` and restart the backend. The watcher uses this host token to poll GitHub; private repos cannot be polled through GitHub App settings alone. If you use App-backed dispatch, also configure `github_app_id`, `github_app_private_key_path`, and `github_app_bot_login`. The repo card distinguishes a missing polling token from a dispatch mode not yet selected. Deck selects the dispatch mode when eligible work is dispatched, not on the first poll. A selected mode is not proof of successful access; check the last poll and Activity.
2. In Roster, put the desired Leader first among enabled slots and launch it. The Role field is descriptive only. The Leader approves plans and takes issues that no other slot matches.
3. Add a watched repo. Give its GitHub owner/name and an existing primary clone under your home directory. Deck creates a separate issue worktree beside that clone; ordinary slot sessions keep using their own repo path.
4. Create the dispatch and optional design/area labels on GitHub. Adding the dispatch label queues an issue; an area label routes it to a matching owner. Without one, Deck uses slot expertise and finally the Leader. A design label on the same issue uses the human-review design pipeline. Removing the dispatch label during an attempt escalates it.
5. Choose merge policy and finite budgets. Human policy leaves PRs for review. Auto policy merges eligible code PRs after checks pass, subject to the daily cap; design PRs always need human review. Enable autonomy when the roster and watched repos are ready.

Deck polls GitHub every 60 seconds by default. The Activity table refreshes every five seconds while open; it does not trigger another GitHub poll. Issues move through queued, dispatched, verifying, and ready for human review or merged. An escalated issue has stopped and needs attention.

## Build hints

Deck does not run the build command. The optional build settings are instructions in the owner's brief. An out-of-tree build directory may include `{issue_number}`. The command hint may include `{build_dir}` and `{parallelism}`. The parallelism value also tells the agent to cap build jobs.

## Ordinary review corrections

An initial implementation plan remains the basis for work while its normalized
approval and owner acknowledgement remain valid. Opening a PR or reaching
`ready_for_review` does not end that plan. The Leader sends review findings back
to the current owner. The owner can correct findings within that same plan on
the existing branch and PR after reconciling owner identity, dispatch nonce,
workspace lease and approval evidence. Operator pauses and safety holds stop
work. Missing or stale authority must be resolved before edits.

`continuation_disabled` describes recovery of an escalated attempt. It does not
by itself prohibit ordinary corrections under an existing initial approval.
Do not escalate, retry, release the workspace, change recovery policy or request
a continuation just to make in-scope review corrections. Do not send a second
`pr_opened` report for an already tracked PR.

Every pushed head needs independent review and hosted CI for its full SHA.
Previous review acceptance and CI readiness apply to the previous head. Preserve
the configured merge policy; human policy still requires human merge. The owner
context returned by `deck_get_work_item_context` includes `review_rework_guidance`;
that text explains the workflow and does not grant approval.

This rule applies to nonterminal, non-escalated initial implementation attempts
with `active_scope_revision=0`. Scoped and diagnostic continuations retain their
approved paths, commands and finite budgets. Completing one does not grant
authority for another head. Work outside the approved plan requires a supported
new approval.

## Recovery and operator token

An escalated issue with an open PR may be continued within a bounded scope revision. The owner proposes a plan, allowed files, and allowed commands; the Leader approves; the owner continues in the same workspace. A failed head is a pushed PR commit whose GitHub checks fail. The policy caps revisions and failed heads so recovery cannot loop indefinitely. A checkpoint hold pauses the Leader's decision or owner's acknowledgement until an operator releases it.

To create an operator token on the Deck host, run `openssl rand -hex 32`, put the result in `backend/.env` as `operator_token=<value>`, run `chmod 600 backend/.env`, and restart the backend. Do not export this token into the agent environment. The UI stores it only in the current browser tab and asks for it when you edit the roster, watched repos, autonomy settings, recovery policy, or use operator remedies. The current authenticated Leader can request an eligible retry through Agent Mail without the operator token. Ordinary issue dispatch does not need the token. This token does not isolate agents running under the backend's OS user: such processes can read `backend/.env` despite its `0600` permissions.

Planning or launching a team requires an authenticated agent session or the operator token. Agent sessions can use the configured roster but cannot override launch prompts or paths, include disabled slots, force a respawn, or bypass plan confirmation. Terminating a session through Agent Bridge requires the operator token.

Plan launch reuses only a live pane already bound to its slot. A discovered pane with no verified slot binding blocks the default plan; it is **not** silently promoted to Leader. An operator can request a new plan that explicitly marks such a pane for adoption and names its tmux target and PID. Review the pane and its startup instructions before selecting **Adopt and launch**, or choose a forced fresh spawn instead. Agent sessions cannot request adoption. Agent Bridge's raw spawn route accepts a minimal same-repository plain spawn from an authenticated agent session, but requires the operator token for prompts and other overrides; the legacy CC Bridge spawn and kill routes are operator-only. This does not isolate same-UID agent panes from the backend's operator token or direct tmux access.

If the card says the polling token is not set, check `github_token` in `backend/.env` and restart the backend. A card that says the dispatch mode is not selected can remain that way after successful polls if no issue is eligible for dispatch. If Activity reports an auth error, verify the host token's repository access or the GitHub App installation and settings before retrying.
