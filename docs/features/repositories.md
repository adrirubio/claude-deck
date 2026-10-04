# Repositories

Repositories lists watched scopes across teams. The same GitHub repository can appear in more than one scope; keep the team and scope identity when opening details or related work. Provider filtering here means a configured harness in the team's roster, while Work filtering means an assigned owner's harness.

Read configured enablement separately from effective intake. A team and scope can both be enabled while normal intake is blocked by recovery-only mode, a stopped scheduler or a missing scheduled job. Unavailable runtime evidence stays unknown. A runtime timestamp is separate from the stored last-poll time.

Fresh, stale and never-polled observations describe eligible polling. Paused or blocked intake displays suspended polling; unknown runtime is not silently classified as stale. An error while refreshing keeps the prior observation labelled rather than reporting zero configured scopes.

A same-repository/same-label overlap warning includes other enabled local scope IDs, even outside your current team filter. It warns about independent dispatch authorities; it does not deduplicate issues, merge attempts or prevent concurrent dispatch. A guided activation flow is not included in this build.

Open the scope's work with `scope_id` to browse its queue separately. Use existing Teams surfaces for configuration and existing authority checks. Navigation does not enable a scope or release a workspace. Team deletion remains server-guarded against enabled automation and in-use work, approvals, revisions and leases; it is not a way to silently stop or clear work.

Use [Teams](/features/agent-teams) for current repository settings and [Work](/features/work) for paused pagination/detail behavior. [Factory API](/api/factory) documents the safe observations. Guided setup is not included.
