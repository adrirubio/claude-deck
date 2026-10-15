# The factory story for directors

For: row 742 under parent issue #745. This document starts from `01-audit.md` on master.

Purpose. A director can retell the Deck story from this page. The page uses short, plain sentences. Each claim names its evidence.

## One sentence

Deck runs a team of AI agents that take GitHub issues to reviewed work, while the people in charge keep the key decisions.

Evidence: `docs/guide/operating-model.md` defines the factory as the supervisor, the Deck controller, and the team working on the Director's backlog. `docs/guide/index.md` states the team works on GitHub issues with bounded attempts.

## One paragraph

Deck is a local workspace where a director runs AI agent teams on GitHub work. The director owns the backlog and sets the goal. The assigned owner proposes a plan and the designated Leader approves it. Members build the work, reviewers check it, and the Supervisor, when one is assigned, watches the factory and repairs routine faults under delegation. The director sees progress on Overview and Work, tracks repositories and teams, checks the audit record, and still decides publication, budgets, models, and security stops. GitHub stays the home for issues, pull requests, and review.

Evidence: `docs/guide/index.md` line 13 states agents propose plans for designated Leader decisions. `docs/guide/operating-model.md` gives the backlog to the Director and retained decisions to the Director, and keeps GitHub outside the factory as the record home. The e2e sidebar in `frontend/src/components/layout/Sidebar.tsx` lists Overview, Work, Repositories, Teams, and Audit.

## The story of one piece of work

Read this story as one example job that moves from a GitHub issue to a merged PR. The example uses one simple issue: "Add a short help note to the welcome page." This example is not a measured delivery. It shows the roles, the screens, and the gates.

Example policy. In this example, repository policy asks a human to review this PR before merge. Other repositories use other rules. Evidence: `docs/autonomy.md` states the auto policy merges eligible code PRs after checks pass, and design PRs always need human review. Repository policy sets the review rule for each PR.

### Step 1. The Director writes the issue

The Director writes the example issue with a clear result. The Director orders the backlog and marks the issue ready. Evidence: `docs/guide/operating-model.md` states the Director writes and orders issues, sets acceptance conditions, and applies the dispatch label as the ready signal.

What the Director sees: GitHub shows the issue and its place in the backlog. Deck does not replace GitHub. Evidence: `docs/guide/operating-model.md` keeps GitHub outside the factory as the record home.

Decision that stays with the Director: approve the goal, the order, and the ready mark.

### Step 2. The owner proposes a plan and the Leader approves it

The controller assigns the ready issue to one owner. The owner proposes a short plan. The designated Leader approves the plan. Then the work starts. Evidence: `docs/guide/index.md` line 13 states agents propose plans for designated Leader decisions. `backend/app/services/github_approval_service.py` `create_initial_request` records the owner proposal and the Leader decision. `docs/guide/operating-model.md` gives next-work selection to the Team Leader.

What the Director sees: Overview shows campaign progress and team summaries. Work shows the owner and the waiting reason. Teams shows the roster, the named Leader, supervisor status, repositories, and work counts. Evidence: the audit at `01-audit.md` records Overview with "Needs you", campaign progress, and team summaries, Work with owners and waiting reasons, and Teams with the selected roster, the named Leader, supervisor status, repository count, and work count.

Decision that stays with the Director: set the outcome and the limits for the campaign. The Leader approves the agent plan. The Director does not approve each agent plan.

### Step 3. A member does the work

The assigned member builds the change in a leased workspace. A leased workspace is a separate working copy that only this job may use. The member runs the scoped checks and opens a pull request (PR). A PR is one proposed change. Repository policy sets its review rule. Evidence: `docs/guide/operating-model.md` gives implementation to team members under the Leader. `docs/guide/index.md` states human PR review and merge follow repository policy.

What the Director sees: Work shows the owner, the state, and the PR link. Repositories shows which backlog feeds the team. Harnesses shows the observed setup and support for each agent tool. Account, model, and session readiness stay unknown here. Evidence: the audit at `01-audit.md` records Work with PR fields and Repositories with enablement and intake. `docs/features/harnesses.md` states readiness stays unknown without a separate check.

Decision that stays with the Director: none at this step, unless the work hits a retained decision or a safety stop.

### Step 4. Reviewers check the work

In this example, an independent reviewer reads the exact PR head. The PR head is the latest commit on the PR branch. The reviewer sends findings to the owner. The owner fixes them on the same branch and PR. Hosted checks (CI) run on the new head. Evidence: `docs/features/work.md` states human PR review stays separate from agent plan approval in this example policy. `docs/autonomy.md`, "Ordinary review corrections", gives the same-branch fix loop.

What the Director sees: Work shows whether the item waits for review. Agent Mail holds the coordination messages under its access rules. Audit shows safe delivery metrics without a secret token. Evidence: `docs/features/agent-mail.md` explains protected Mail reads under "Authentication and upgrades". The audit at `01-audit.md` records Audit from `docs/guide/factory-audit-and-metrics.md`. The audit did not see loaded Mail messages. The browser stayed at "Loading participants...". That state is an open observation limit. It is not a docs defect.

Decision that stays with the Director: in this example, review the final PR under repository policy, or leave that review to the named reviewers. Passing review and CI give no merge power alone. The merger named in the example is the Supervisor under the example repository policy.

### Step 5. The Supervisor watches and helps

The Supervisor is optional. When no supervisor is registered, the status reads None and no supervisor is required. Evidence: `docs/guide/operating-model.md` calls the supervisor an optional staff role and lists None as not an error.

When a Supervisor is assigned, the Supervisor is an outside AI agent that watches the factory. The Supervisor fixes routine blockers inside the recorded delegation. The Supervisor prepares exact requests when a retained decision is needed. Evidence: `docs/guide/operating-model.md` gives repair, upgrade, and rollback to the Supervisor with the maintenance script, and states the Supervisor uses Director powers only inside delegation.

What the Director sees: Overview shows whether the Supervisor is Healthy, Late, or Absent when a supervisor is registered. Evidence: `docs/guide/operating-model.md` defines those three states from the last promised check.

Decision that stays with the Director: grant or withdraw delegation, and decide publication, budgets, models, and security HOLD.

### Step 6. The PR merges and the record stays

In this example, the Supervisor merges the PR after review and CI pass under the example repository policy. Passing review and CI alone give no merge power. The issue closes. The audit ledger keeps what happened. Evidence: `docs/guide/operating-model.md` keeps GitHub as the final record. `docs/guide/factory-audit-and-metrics.md` states the audit ledger records what the factory actually did.

What the Director sees: Work shows the item as finished. Audit shows the delivery history with coverage limits. Locked Audit events are an access gate. They are not a load failure. Evidence: the audit at `01-audit.md` records finished tracking apart from reviewed delivery, and cost as unknown. `docs/guide/factory-audit-and-metrics.md` states the event list needs the operator token.

Decision that stays with the Director: accept the campaign result and decide publication.

## Why it matters to a director

Each point below names what the product shows today. No point claims a saving the product cannot prove.

Control. The Director owns the backlog and the retained decisions. Evidence: `docs/guide/operating-model.md` lists backlog ownership for the Director and names publication, budgets, models, and security HOLD as retained decisions. The Leader approves plans inside those limits. Evidence: `docs/guide/operating-model.md` gives plan approval to the Team Leader.

Visibility. The Director sees waiting work without opening each terminal. Evidence: the audit at `01-audit.md` records Overview with "Needs you" and campaign progress, and Work with owners and waiting reasons. Repositories shows enablement apart from intake. Evidence: `docs/guide/index.md` states that split.

Safety gates. Work stops at named gates. A plan needs Leader approval before build. In this example, a PR needs human review and CI before merge. Other repositories set other review rules. A security HOLD stays with the Director. Evidence: `docs/guide/index.md` keeps agent plan approval apart from human PR review. `docs/autonomy.md` states the auto policy merges eligible code PRs after checks pass, and design PRs always need human review. `docs/guide/operating-model.md` keeps security HOLD as a Director decision.

Cost. Usage shows Claude Code session estimates where Deck can read them. Evidence: `docs/features/usage.md` states the Usage page aggregates Claude Code session tokens and estimated cost. Factory delivery cost stays unknown. Evidence: `docs/guide/factory-audit-and-metrics.md` keeps unknown observations as unknown. This section claims no campaign cost and no measured saving. No trial measures those savings yet.

## Glossary

At most 15 words. Each entry gives one short sentence.

1. **Team** — A saved roster of agent sessions that work as one unit.
2. **Leader** — The one team member who approves plans and picks the next work.
3. **Member** — One agent slot on a team that owns a piece of work.
4. **Harness** — The agent tool a member runs, such as Claude Code or Codex.
5. **Scope** — The link that connects one team to one repository and its dispatch labels.
6. **Work item** — One tracked piece of work from issue to review.
7. **Approval** — A recorded yes at a gate, such as plan approval or PR review.
8. **Agent Mail** — The team mailbox where agents coordinate and hand off work.
9. **Backlog** — The ordered list of GitHub issues the Director wants done.
10. **Director** — The human who owns the outcome and the retained decisions.
11. **Supervisor** — The outside watcher that repairs routine faults under delegation.
12. **Reviewer** — The independent reader who checks the exact PR before merge.
13. **Audit** — The ledger that records what the factory did and its limits.
14. **CI** — Automatic checks that run on a PR before merge.
15. **PR** — A pull request: one proposed change. Repository policy sets its review rule.

## What the story does not promise

Deck does not promise a time saving. No trial measures director time saved. Evidence: `docs/changelog.md` keeps cost as unknown and the audit keeps finished tracking apart from reviewed delivery.

Deck does not promise that agents work alone. A person still writes the goal, sets limits, and decides publication. PR review follows repository policy. Evidence: `docs/guide/operating-model.md` keeps the goal and retained decisions with the Director. `docs/guide/index.md` states human PR review and merge follow repository policy.

Deck does not promise that every screen always loads its data. Agent Mail once stayed at "Loading participants...". That state is an open observation limit. Audit events stay behind an access gate. A locked event list is not a load failure. Evidence: the audit at `01-audit.md` records both limits on the tested source. `docs/guide/factory-audit-and-metrics.md` states the event list needs the operator token.

Deck does not promise cloud hosting. Deck runs on the director's machine and changes real local agent files. Evidence: the landing page at `website-ref/index.html` lines 185–186 and the audit verdict. An operator must set up the host first.

Deck does not replace GitHub. GitHub holds the issues, the PRs, and the final record. Evidence: `docs/guide/operating-model.md` keeps GitHub outside the factory as the record home.

## How a director retells the story

A director can say: "We write goals as GitHub issues. The owner proposes a plan and our Leader approves it. Members build it and reviewers check the exact change. We watch progress on Overview and Work and read the audit ledger after. We still decide the goal, the budget, the models, and publication."

Evidence for the retell: each sentence above maps to Steps 1–6. The Leader approves plans. The Director keeps the retained decisions. Human PR review follows repository policy.
