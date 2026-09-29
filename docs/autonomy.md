# Autonomous GitHub dispatch

This guide is for the operator of a Deck team. Autonomy is off until you enable it for the team, and a watched repo can also be paused separately.

## Before enabling

1. Give the watcher GitHub access. Add `github_token=<token>` to `backend/.env` and restart the backend. The watcher uses this host token to poll GitHub; private repos cannot be polled through GitHub App settings alone. If you use App-backed dispatch, also configure `github_app_id`, `github_app_private_key_path`, and `github_app_bot_login`. The repo card distinguishes a missing polling token from a dispatch mode not yet selected. Deck selects the dispatch mode when eligible work is dispatched, not on the first poll. A selected mode is not proof of successful access; check the last poll and Activity.
2. In Roster, put the desired Leader first among enabled slots and launch it. The Role field is descriptive only. The Leader approves plans and takes issues that no other slot matches.
3. Add a watched repo. Give its GitHub owner/name and an existing primary clone under your home directory. Deck creates a separate issue worktree beside that clone; ordinary slot sessions keep using their own repo path.
4. Create the dispatch and optional design/area labels on GitHub. Adding the dispatch label queues an issue; an area label routes it to a matching owner. Without one, Deck uses slot expertise and finally the Leader. A design label on the same issue uses the human-review design pipeline. Removing the dispatch label during an attempt escalates it.
5. Choose merge policy and finite budgets. Human policy leaves PRs for review. Auto policy merges eligible code PRs after checks pass, subject to the daily cap; design PRs always need human review. Enable autonomy when the roster and watched repos are ready.

Deck polls GitHub every 60 seconds by default. The Activity table refreshes every five seconds while open; it does not trigger another GitHub poll. Issues move through queued, dispatched, verifying, and ready for human review or merged. An escalated issue has stopped and needs attention.

## Build hints

Deck does not run the build command. The optional build settings are instructions in the owner's brief. An out-of-tree build directory may include `{issue_number}`. The command hint may include `{build_dir}` and `{parallelism}`. The parallelism value also tells the agent to cap build jobs.

## Recovery and operator token

An escalated issue with an open PR may be continued within a bounded scope revision. The owner proposes a plan, allowed files, and allowed commands; the Leader approves; the owner continues in the same workspace. A failed head is a pushed PR commit whose GitHub checks fail. The policy caps revisions and failed heads so recovery cannot loop indefinitely. A checkpoint hold pauses the Leader's decision or owner's acknowledgement until an operator releases it.

To create an operator token on the Deck host, run `openssl rand -hex 32`, put the result in `backend/.env` as `operator_token=<value>`, run `chmod 600 backend/.env`, and restart the backend. Do not export this token into the agent environment. The UI stores it only in the current browser tab and uses it for protected recovery policy and operator actions. It is not needed for ordinary issue dispatch.

If the card says the polling token is not set, check `github_token` in `backend/.env` and restart the backend. A card that says the dispatch mode is not selected can remain that way after successful polls if no issue is eligible for dispatch. If Activity reports an auth error, verify the host token's repository access or the GitHub App installation and settings before retrying.
