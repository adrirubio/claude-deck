# The factory story for directors

For: issue #768 under parent issue #745. This revision starts from `01-audit.md` and the revised factory story on master.

Purpose. A non-technical product person can retell this story after one short read. The top level tells the whole idea in three parts. The detail sits in a second layer, marked for a second page. Evidence notes sit under the copy, so the reading stays clean and every claim still names where it comes from.

## The story in short

### One sentence

You shape the feature backlog, Deck's AI team builds and checks the work, and the key decisions stay with you.

Evidence: `docs/guide/operating-model.md` describes the factory as a team working on the Director's ordered backlog, with the key decisions kept by the Director.

### One paragraph

Deck brings an AI team to the features you want to build. You, the Director, decide what matters and what is ready to start. The AI Leader organises the work, AI members build it, and independent AI reviewers check it. You can follow progress and see where a decision is needed. You keep control of the goals, priorities, budget, AI models, publication, and safety stops. Deck runs on your own computer.

Evidence: `docs/guide/operating-model.md` gives the backlog and the big decisions to the Director, organising and plan approval to the Team Leader, and building to the team. The audit in `01-audit.md` records the screens that show progress, waiting work, and what needs a person.

### The three parts

**1. A clear list of priorities.** Your backlog is the list of features you want built, with a clear result for each. You can see their order and progress. You choose what belongs on the list, what comes first, and what is ready for the team to start.

Evidence: `docs/guide/operating-model.md` states that the Director writes and orders the work, sets what counts as done, and marks what is ready to start.

**2. An AI team with clear roles.** The Leader, an AI agent, organises the work and approves the team's plans. AI members build the features, and AI reviewers who did not build them check the results. You can see who leads the team, who is working, and where help is needed. You choose the Leader and set the team's limits.

Evidence: the audit in `01-audit.md` records the team screen with its roster, its named Leader, and its work counts, and the work screen with an owner and a waiting reason for each item. `docs/guide/operating-model.md` gives plan approval and next-work choice to the Leader. Organising the work is not writing every plan: the owner proposes the plan and the Leader decides on it (see Steps 3 and 4 and `docs/guide/index.md:13`).

**3. Checked work and a record to review.** The team returns its work for you to assess. You can see what is finished, what still needs attention, and the available record of what happened. Deck also shows gaps in that record. You decide whether the result meets your goal and when to publish it.

Evidence: `docs/guide/factory-audit-and-metrics.md:46-49` and `:94` state that the record shows what the factory actually did and keeps its limits visible. `docs/guide/operating-model.md:65-70` and `:89-98` keep acceptance and publication with the Director.

### Why it matters

**Keep the key decisions.** You set the goals, priorities, budget, and limits. The team works within them. The team can handle routine problems within its authority. Decisions reserved for you stay yours.

**See where your attention is needed.** Deck brings progress, owners, and waiting work together so you can see what needs a decision.

**Keep checks part of the work.** The AI Leader approves plans before building starts, and AI reviewers check the results. Deck shows work that needs attention.

**Understand the cost limits.** Deck can show estimates for one supported agent tool's sessions when their data is available. It does not yet measure the full cost of delivering a feature. No trial has measured how much director time it saves.

Evidence: `docs/guide/operating-model.md:65-70` and `:89-98` list the decisions the Director keeps and the checkpoints the work passes. `docs/features/usage.md` covers session cost estimates for one supported agent tool. `docs/guide/factory-audit-and-metrics.md:57` and `:96-97` state that delivery cost and human time savings are not measured.

### The words for this level

Six words carry the whole story. Everything else can wait for the next page.

1. **Backlog** — The features you want built, in the order you want them.
2. **Team** — The AI agents working through your backlog.
3. **Leader** — The AI agent who organises the work and approves plans.
4. **Member** — An AI agent assigned to build part of the work.
5. **Reviewer** — An AI agent who checks work they did not build.
6. **Director** — you: the person who owns the goals, the list, and the final decisions.

### Retell it in half a minute

"We choose and order the features we want. Our AI team works through them: the Leader organises the work, members build it, and reviewers check it. We follow progress and see what needs us. We keep the decisions about goals, priorities, budget, and publication."

Evidence: each sentence maps to the three parts above — the list and its order, the team and its roles, and finished work with its record — with the decisions kept by the Director.

## How it works — read this on the second page

*This layer belongs on a second page. Read it when you want the detail behind the story above. It follows the backlog through the team, not one single item alone. The example uses one simple backlog item: "Add a short help note to the welcome page." This example is not a measured delivery. It shows the roles, the screens, and the gates.*

Example policy. In this example, repository policy asks a human to review this PR before merge. Other repositories use other rules. Evidence: `docs/autonomy.md` states the auto policy merges eligible code PRs after checks pass, and design PRs always need human review. Repository policy sets the review rule for each PR.

### Step 1. The Director writes the backlog and marks it ready

The Director — you, the human in charge — writes each backlog item with a clear result, orders the backlog, and marks what is ready for the team to start. Evidence: `docs/guide/operating-model.md` states the Director writes and orders issues, sets acceptance conditions, and applies the dispatch label as the ready signal.

What the Director sees: GitHub, a computer system — not a person or an agent — shows the backlog and each item's place in it. Deck does not replace GitHub. Evidence: `docs/guide/operating-model.md` keeps GitHub outside the factory as the place where the work and its final record are kept.

Decision that stays with the Director: the goals, the order, and what is ready.

### Step 2. The team works on the backlog items autonomously

Autonomously means the AI team works through ready items without the Director steering each step. It follows the Director's goals and limits, respects safety stops, and uses the plan approvals and reviews below. It does not mean the team works without limits. Evidence: `docs/guide/operating-model.md` gives normal running to the Leader and team inside the Director's retained decisions, with a safety hold available.

What the Director sees: Overview shows progress and what needs a person. Work shows each item's progress and who owns it. Evidence: the audit at `01-audit.md` records Overview with "Needs you" and Work with owners, states, and waiting reasons.

Decision that stays with the Director: hold or pause the work, and change the limits.

### Step 3. Each backlog item is assigned to an agent owner, who writes the plan

The Deck controller, a computer system, assigns one ready item to one agent owner. The agent owner writes a short plan for that item. Evidence: `docs/guide/index.md` line 13 states agents propose plans for designated Leader decisions. `backend/app/services/github_approval_service.py` `create_initial_request` records the owner proposal.

What the Director sees: Work shows the owner for each item. Teams shows the roster and the named Leader. Evidence: the audit at `01-audit.md` records both screens.

Decision that stays with the Director: none per plan. The Director sets the outcome and the limits for the campaign.

### Step 4. The Leader reviews and approves the plan

The designated Leader, an AI agent, reviews the agent owner's plan and approves it. Only then does building start. If the Leader asks for changes, the owner revises the plan first. Evidence: `decide` in `backend/app/services/github_approval_service.py` records the Leader decision. `docs/guide/operating-model.md` gives next-work selection to the Team Leader.

What the Director sees: Overview shows campaign progress and team summaries. Evidence: the audit at `01-audit.md` records Overview with "Needs you", campaign progress, and team summaries.

Decision that stays with the Director: none at this gate. The Leader approves agent plans inside the Director's limits.

### Step 5. The agent owner works on the item

The agent owner builds the change in a leased workspace. A leased workspace is a separate working copy that only this job may use. The owner checks their own work, runs the checks agreed for this work, and opens a pull request (PR). A PR is one proposed change. Repository policy sets its review rule. Evidence: `docs/guide/operating-model.md` gives implementation to team members under the Leader. `docs/guide/index.md` states human PR review and merge follow repository policy.

What the Director sees: Work shows the owner, the state, and the PR link. Repositories shows which backlog feeds the team. Evidence: the audit at `01-audit.md` records Work with PR fields and Repositories with enablement and intake.

Decision that stays with the Director: none here, unless the team needs a decision only you can make or a safety stop applies.

### Step 6. An AI reviewer checks the work

An AI reviewer who did not build the change reads the exact PR head. The PR head is the exact version proposed for review. Findings go back to the agent owner, who fixes them on the same branch and PR. Hosted checks (CI) run on the new head. Members check their own work as they build; this step is the independent check. Evidence: `docs/features/work.md` states human PR review stays separate from agent plan approval in this example policy. `docs/autonomy.md`, "Ordinary review corrections", gives the same-branch fix loop.

What the Director sees: Work shows whether the item waits for review. Agent Mail holds the coordination messages under its access rules. Evidence: `docs/features/agent-mail.md` explains protected Mail reads under "Authentication and upgrades". The audit did not see loaded Mail messages. The browser stayed at "Loading participants...". That state is an open observation limit. It is not a docs defect.

Decision that stays with the Director: if your rules call for your review, decide whether the change is ready. Passing review and checks does not authorize a merge.

### Step 7. The Leader and the Supervisor check it

The Leader checks that the finished work matches the approved plan and the campaign limits. When a Supervisor is assigned, that Supervisor also checks it. The Supervisor can be an AI agent or a person. The Supervisor is optional: without one, the Leader reports directly to the Director, and no supervisor is required. Evidence: `docs/guide/operating-model.md:28` calls the supervisor an optional staff role. The static factory figure lists the supervisor as an agent tool or the Director (`docs/public/images/operating-model/factory.svg`, Supervisor box), so the role can be an AI agent or a person. The Supervisor uses Director powers only inside the recorded delegation.

What the Director sees: Overview shows whether a registered Supervisor is Healthy, Late, or Absent. Evidence: `docs/guide/operating-model.md` defines those three states from the last promised check.

Decision that stays with the Director: grant or withdraw delegation, and decide publication, budgets, models, and security stops.

### Step 8. The work is merged

The work is merged under repository policy, after the checks above pass. In this example, the merger is the Supervisor under the example repository policy. Other repositories name other mergers. Passing review and CI alone give no merge power. The backlog item closes, and the audit record keeps what happened. Evidence: `docs/guide/operating-model.md` keeps GitHub as the final record. `docs/guide/factory-audit-and-metrics.md` states the audit ledger records what the factory actually did.

What the Director sees: Work shows the item as finished. Audit shows the delivery history with coverage limits. Locked Audit events are an access gate. They are not a load failure. Evidence: the audit at `01-audit.md` records finished tracking apart from reviewed delivery. `docs/guide/factory-audit-and-metrics.md` states the event list needs the operator token.

Decision that stays with the Director: accept the campaign result and decide publication.

### Parallel tracks: several items at once

A team does not have to work one item at a time. The Director chooses how many implementers and verifiers a team has, so a team can have several agent owners and several AI reviewers. With the right setting, those members work on parallel tracks of the backlog at the same time, each track in its own workspace, coordinated by the Leader. Evidence: `docs/guide/operating-model.md:30` gives the implementer and verifier counts to the Director and names concurrent-dispatch limits. `docs/guide/supervised-factory-playbook.md:193` registers one dispatch workspace for each concurrent item. `docs/features/repositories.md:20` and `docs/features/agent-mail.md:114` show a team has several member slots.

One limit, in plain words: a new backlog link starts at one item at a time. Parallel tracks need a higher setting and one workspace per track. That setting is the Director's choice. Evidence: `docs/features/repositories.md:22` saves a new scope at concurrency 1.

### Several teams in one Deck

One Deck can run several teams in parallel, each working on the backlog of a different project. Each team keeps its own Leader, roster, and backlog link. Evidence: `docs/features/repositories.md:3` lists watched scopes across teams. `docs/features/work.md:3` browses mixed-team work. `docs/guide/supervised-factory-playbook.md:37` states one actor can supervise several teams. The test seed in `scripts/e2e/scenarios.py` holds several saved teams in one Deck (such as "Release crew" and "Quiet team"); the seeded quiet team is idle, so the seed shows several teams existing in one Deck, not all of them running.

What the Director sees: Teams lists the teams. Work can filter by team. Overview summarises each team. Evidence: the audit at `01-audit.md` records the Teams roster screen and team summaries on Overview.

Decision that stays with the Director: how many teams to run, which project each team serves, and each team's limits.

### Words for this page

These words belong to the How it works page. Each entry gives one short sentence.

1. **Harness** — The agent tool a member runs.
2. **Scope** — The link that connects one team to one repository and its dispatch labels.
3. **Work item** — One tracked piece of work from issue to review.
4. **Approval** — A recorded yes at a gate, such as plan approval or PR review.
5. **Agent Mail** — The team mailbox where agents coordinate and hand off work.
6. **Supervisor** — The outside watcher, an AI agent or a person, that repairs routine faults under delegation.
7. **Audit** — The ledger that records what the factory did and its limits.
8. **CI** — Automatic checks that run on a PR before merge.
9. **PR** — A pull request is a proposed change reviewed under repository policy.
