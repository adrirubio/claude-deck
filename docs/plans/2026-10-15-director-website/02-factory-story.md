# The factory story for directors

For: issue #756 under parent issue #745. This revision starts from `01-audit.md` and the first factory story on master.

Purpose. A non-technical product person can retell this story after one short read. The top level tells the whole idea in three parts. The detail sits in a second layer, marked for a second page. Evidence notes sit under the copy, so the reading stays clean and every claim still names where it comes from.

## The story in short

### One sentence

You shape the feature backlog, Deck's AI team builds and checks the work, and the key decisions stay with you.

Evidence: `docs/guide/operating-model.md` describes the factory as a team working on the Director's ordered backlog, with the key decisions kept by the Director.

### One paragraph

Deck brings an AI team to the features you want to build. You decide what matters and what is ready to start. The Leader organises the work, members build it, and independent reviewers check it. You can follow progress and see where a decision is needed. You keep control of the goals, priorities, budget, AI models, publication, and safety stops. Deck runs on your own computer.

Evidence: `docs/guide/operating-model.md` gives the backlog and the big decisions to the Director, organising and plan approval to the Team Leader, and building to the team. The audit in `01-audit.md` records the screens that show progress, waiting work, and what needs a person.

### The three parts

**1. A clear list of priorities.** Your backlog is the list of features you want built, with a clear result for each. You can see their order and progress. You choose what belongs on the list, what comes first, and what is ready for the team to start.

Evidence: `docs/guide/operating-model.md` states that the Director writes and orders the work, sets what counts as done, and marks what is ready to start.

**2. An AI team with clear roles.** The Leader organises the work and approves the team's plans. Members build the features, and reviewers who did not build them check the results. You can see who leads the team, who is working, and where help is needed. You choose the Leader and set the team's limits.

Evidence: the audit in `01-audit.md` records the team screen with its roster, its named Leader, and its work counts, and the work screen with an owner and a waiting reason for each item. `docs/guide/operating-model.md` gives plan approval and next-work choice to the Leader. Organising the work is not writing every plan: the owner proposes the plan and the Leader decides on it (see Step 2 and `docs/guide/index.md:13`).

**3. Checked work and a record to review.** The team returns its work for you to assess. You can see what is finished, what still needs attention, and the available record of what happened. Deck also shows gaps in that record. You decide whether the result meets your goal and when to publish it.

Evidence: `docs/guide/factory-audit-and-metrics.md:46-49` and `:94` state that the record shows what the factory actually did and keeps its limits visible. `docs/guide/operating-model.md:65-70` and `:89-98` keep acceptance and publication with the Director.

### Why it matters

**Keep the key decisions.** You set the goals, priorities, budget, and limits. The team works within them. The team can handle routine problems within its authority. Decisions reserved for you stay yours.

**See where your attention is needed.** Deck brings progress, owners, and waiting work together so you can see what needs a decision.

**Keep checks part of the work.** The Leader approves plans before building starts, and reviewers check the results. Deck shows work that needs attention.

**Understand the cost limits.** Deck can show estimates for Claude Code sessions when their data is available. It does not yet measure the full cost of delivering a feature. No trial has measured how much director time it saves.

Evidence: `docs/guide/operating-model.md:65-70` and `:89-98` list the decisions the Director keeps and the checkpoints the work passes. `docs/features/usage.md` covers Claude Code session cost estimates. `docs/guide/factory-audit-and-metrics.md:57` and `:96-97` state that delivery cost and human time savings are not measured.

### The words for this level

Six words carry the whole story. Everything else can wait for the next page.

1. **Backlog** — The features you want built, in the order you want them.
2. **Team** — The AI agents working through your backlog.
3. **Leader** — The team member who organises the work and approves plans.
4. **Member** — An AI agent assigned to build part of the work.
5. **Reviewer** — Someone who checks work they did not build.
6. **Director** — you: the person who owns the goals, the list, and the final decisions.

### Retell it in half a minute

"We choose and order the features we want. Our AI team works through them: the Leader organises the work, members build it, and reviewers check it. We follow progress and see what needs us. We keep the decisions about goals, priorities, budget, and publication."

Evidence: each sentence maps to the three parts above — the list and its order, the team and its roles, and finished work with its record — with the decisions kept by the Director.

## How it works — read this on the second page

*This layer belongs on a second page. Read it when you want the detail behind the story above. It follows one piece of work from a GitHub issue to a merged PR. The example uses one simple issue: "Add a short help note to the welcome page." This example is not a measured delivery. It shows the roles, the screens, and the gates.*

Example policy. In this example, repository policy asks a human to review this PR before merge. Other repositories use other rules. Evidence: `docs/autonomy.md` states the auto policy merges eligible code PRs after checks pass, and design PRs always need human review. Repository policy sets the review rule for each PR.

### Step 1. The Director writes the issue

The Director writes the example issue with a clear result. The Director orders the backlog and marks the issue ready. Evidence: `docs/guide/operating-model.md` states the Director writes and orders issues, sets acceptance conditions, and applies the dispatch label as the ready signal.

What the Director sees: GitHub shows the issue and its place in the backlog. Deck does not replace GitHub. Evidence: `docs/guide/operating-model.md` keeps GitHub outside the factory as the place where the work and its final record are kept.

Decision that stays with the Director: approve the goal, the order, and the ready mark.

### Step 2. The owner proposes a plan and the Leader approves it

The controller assigns the ready issue to one owner. The owner proposes a short plan. The designated Leader approves the plan. Then the work starts. Evidence: `docs/guide/index.md` line 13 states agents propose plans for designated Leader decisions. `backend/app/services/github_approval_service.py` `create_initial_request` records the owner proposal. `decide` in the same file records the Leader decision. `docs/guide/operating-model.md` gives next-work selection to the Team Leader.

What the Director sees: Overview shows campaign progress and team summaries. Work shows the owner and the waiting reason. Teams shows the roster, the named Leader, supervisor status, repositories, and work counts. Evidence: the audit at `01-audit.md` records Overview with "Needs you", campaign progress, and team summaries, Work with owners and waiting reasons, and Teams with the selected roster, the named Leader, supervisor status, repository count, and work count.

Decision that stays with the Director: set the outcome and the limits for the campaign. The Leader approves the agent plan. The Director does not approve each agent plan.

### Step 3. A member does the work

The assigned member builds the change in a leased workspace. A leased workspace is a separate working copy that only this job may use. The member runs the scoped checks and opens a pull request (PR). A PR is one proposed change. Repository policy sets its review rule. Evidence: `docs/guide/operating-model.md` gives implementation to team members under the Leader. `docs/guide/index.md` states human PR review and merge follow repository policy.

What the Director sees: Work shows the owner, the state, and the PR link. Repositories shows which backlog feeds the team. Harnesses shows the observed setup and support for each agent tool. Account, model, and session readiness stay unknown here. Evidence: the audit at `01-audit.md` records Work with PR fields and Repositories with enablement and intake. `docs/features/harnesses.md` states readiness stays unknown without a separate check.

Decision that stays with the Director: none at this step, unless the team needs a decision only you can make, or a safety stop applies.

### Step 4. Reviewers check the work

In this example, an independent reviewer reads the exact PR head. The PR head is the exact version proposed for review. The reviewer sends findings to the owner. The owner fixes them on the same branch and PR. Hosted checks (CI) run on the new head. Evidence: `docs/features/work.md` states human PR review stays separate from agent plan approval in this example policy. `docs/autonomy.md`, "Ordinary review corrections", gives the same-branch fix loop.

What the Director sees: Work shows whether the item waits for review. Agent Mail holds the coordination messages under its access rules. Audit shows safe delivery metrics without a secret token. Evidence: `docs/features/agent-mail.md` explains protected Mail reads under "Authentication and upgrades". The audit at `01-audit.md` records Audit from `docs/guide/factory-audit-and-metrics.md`. The audit did not see loaded Mail messages. The browser stayed at "Loading participants...". That state is an open observation limit. It is not a docs defect.

Decision that stays with the Director: in this example, review the final PR under repository policy, or leave that review to the named reviewers. Passing review and CI give no merge power alone. The merger named in the example is the Supervisor under the example repository policy.

### Step 5. The Supervisor watches and helps

The Supervisor is optional. When no supervisor is registered, the status reads None and no supervisor is required. Evidence: `docs/guide/operating-model.md` calls the supervisor an optional staff role and lists None as not an error.

When a Supervisor is assigned, the Supervisor is an outside AI agent that watches the factory. The Supervisor fixes routine blockers inside the recorded delegation. When only you can decide, the Supervisor explains what you need to decide and gives you the evidence. Evidence: `docs/guide/operating-model.md` gives repair, upgrade, and rollback to the Supervisor with the maintenance script, and states the Supervisor uses Director powers only inside delegation.

What the Director sees: Overview shows whether the Supervisor is Healthy, Late, or Absent when a supervisor is registered. Evidence: `docs/guide/operating-model.md` defines those three states from the last promised check.

Decision that stays with the Director: grant or withdraw delegation, and decide publication, budgets, models, and security HOLD.

### Step 6. The PR merges and the record stays

In this example, the Supervisor merges the PR after review and CI pass under the example repository policy. Passing review and CI alone give no merge power. The issue closes. The audit ledger keeps what happened. Evidence: `docs/guide/operating-model.md` keeps GitHub as the final record. `docs/guide/factory-audit-and-metrics.md` states the audit ledger records what the factory actually did.

What the Director sees: Work shows the item as finished. Audit shows the delivery history with coverage limits. Locked Audit events are an access gate. They are not a load failure. Evidence: the audit at `01-audit.md` records finished tracking apart from reviewed delivery, and cost as unknown. `docs/guide/factory-audit-and-metrics.md` states the event list needs the operator token.

Decision that stays with the Director: accept the campaign result and decide publication.

### Words for this page

These words belong to the How it works page. Each entry gives one short sentence.

1. **Harness** — The agent tool a member runs, such as Claude Code or Codex.
2. **Scope** — The link that connects one team to one repository and its dispatch labels.
3. **Work item** — One tracked piece of work from issue to review.
4. **Approval** — A recorded yes at a gate, such as plan approval or PR review.
5. **Agent Mail** — The team mailbox where agents coordinate and hand off work.
6. **Supervisor** — The outside watcher that repairs routine faults under delegation.
7. **Audit** — The ledger that records what the factory did and its limits.
8. **CI** — Automatic checks that run on a PR before merge.
9. **PR** — A pull request is a proposed change reviewed under repository policy.

## What the story does not promise

Deck does not promise a time saving. No trial measures director time saved. Evidence: `docs/changelog.md` keeps cost as unknown and the audit keeps finished tracking apart from reviewed delivery.

Deck does not promise that agents work alone. A person still writes the goal, sets limits, and decides publication. PR review follows repository policy. Evidence: `docs/guide/operating-model.md` keeps the goal and retained decisions with the Director. `docs/guide/index.md` states human PR review and merge follow repository policy.

Deck does not promise that every screen always loads its data. Agent Mail once stayed at "Loading participants...". That state is an open observation limit. Audit events stay behind an access gate. A locked event list is not a load failure. Evidence: the audit at `01-audit.md` records both limits on the tested source. `docs/guide/factory-audit-and-metrics.md` states the event list needs the operator token.

Deck does not promise cloud hosting. Deck runs on the director's machine and changes real local agent files. Evidence: the landing page at `website-ref/index.html` lines 185–186 and the audit verdict. An operator must set up the host first.

Deck does not replace GitHub. GitHub holds the issues, the PRs, and the final record. Evidence: `docs/guide/operating-model.md` keeps GitHub outside the factory as the place where the work and its final record are kept.
