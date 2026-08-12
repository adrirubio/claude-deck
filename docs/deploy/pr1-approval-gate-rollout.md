# PR1 Approval Gate Rollout

Deploy the authenticated approval gate in this order:

1. Set `operator_token` in `backend/.env` and set the file mode to `0600`.
2. Deploy PR0.
3. Restart every agent pane so each session registers and obtains a capability token.
4. Set `mail_capability_tokens_required = True` and restart the backend.
5. Verify authenticated Agent Mail and `/dispatch-status` calls on a non-autonomous test preset.
6. Deploy PR1.
7. Keep autonomy disabled until PR2 is deployed and the end-to-end gate passes.

Do not export the operator token into the backend process environment or the tmux global environment. Agent panes must never receive it.

PR1 intentionally refuses every dispatch-status report while capability-token enforcement is disabled. This prevents an unauthenticated compatibility path from creating approval, ownership, liveness, or release evidence.
