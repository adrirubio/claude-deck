# Overview

Overview is the default home page for work across this backend. Team, scope and harness filters are independent of the saved native harness and local project.

## Read the observations

Counts describe the complete filtered dataset: queued, active, review, attention, finished and unknown tracking. Follow [Work](/features/work) to inspect records. Finished is not independently reviewed delivery, reliability or time saved. Read failures remain visible rather than becoming zero counts.

Automation separates configured scopes/enablement from effective intake. Runtime normal/recovery-only/unknown mode, scheduler state and runtime time are independent observations. Recovery-only blocks normal intake; missing evidence stays unknown. Stale/never-polled counts cover eligible polling, not paused or blocked scopes. See [Repositories](/features/repositories).

## Refresh and next steps

Visible observations refresh periodically. Response/runtime timestamps differ from the last repository poll; loading a page does not trigger GitHub polling or enable automation. Empty configuration retains manual Teams, Live sessions and Harnesses entry points.

## Native summaries moved to Harnesses

The former provider/project dashboard is available as Configuration summary under [Harnesses](/features/harnesses) for implemented providers. Claude Code retains its native configuration/context summary; Codex uses supported configuration, inventory, live sessions and Plans. Codex usage/context/transcript parity is unavailable. Native summaries and project settings do not filter factory work.
