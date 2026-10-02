# Claude Deck delivery experience specification

**Execution baseline, 2026-10-02:** G00 passed through upstream PR #399 / `ac9252242fcf436c3ea9997add5d32416cad2cd1`. Product work starts first in the fork `juanrubio/claude-deck`, from and targeting `feature/software-delivery-product-reposition`. Follow the agent deployment plan and startup gates. Earlier release snapshots and M0 readiness tables are historical evidence; this decision supersedes their pending-G00 or master-target instructions.

The delivery interface will make work, repository policies, and intervention easy to inspect across mixed-harness teams. Native configuration moves into Harnesses. Existing session and coordination features supply context and controls for delivery.

This is the target experience for the milestones in the [product brief](product-brief.md). Routes introduced here are planned.

Begin this experience implementation only after the autonomy feature has been merged into `master`, as required by the [implementation start gate](README.md#implementation-start-gate). Develop against the autonomy implementation on the updated `master`.

## Primary navigation

| Label | Canonical route | Purpose |
| --- | --- | --- |
| Overview | `/` | Instance-wide progress, review requests, attention, and automation state |
| Work | `/work` | Filtered queue across teams and watched repository scopes |
| Repositories | `/repositories` | Watched repositories, team assignments, access, and policy |
| Teams | `/teams` | Saved rosters, authority, expertise, and launch plans |
| Live sessions | `/agent-bridge` | Existing terminals, provider filters, team lanes, and session controls |
| Harnesses | `/harnesses` | M1a registry/index and implemented native settings; M1b operational support and readiness |

Agent Mail remains directly accessible at `/agent-mail` through a secondary Coordination entry and work/team links. Native transcript history, plans, usage, backup, extensions, and application settings remain available through the appropriate Harnesses or secondary navigation.

Use **agent** for a running worker or team member and **harness** for its execution tool. Use **custom agent definitions** when referring to the legacy Claude configuration feature.

The header continues to identify the backend instance and retains the existing name, logo, theme controls, and instance accent.

## Scope and filter behavior

Overview and Work initially cover the current backend instance. Available local filters are team, watched repository scope, and assigned harness. These views never inherit the legacy global provider or active-project selection.

Filters are encoded in the URL using `team_id`, `scope_id`, `provider`, and, for Work, `category`. Invalid filters produce an understandable error and a Reset filters action. Back/forward navigation preserves the filter state. Changing filters clears the current pagination cursor.

The repository filter identifies a watched scope belonging to a team. The same GitHub repository or issue may appear in more than one scope; retain separate work-item identities and show the owning team.

The harness filter means the owner slot's current configured harness. Label historical runtime evidence separately when it exists. Unassigned work appears under All harnesses and is never silently assigned to Claude Code.

Scope changes in these read views do not write `/projects/active`, launch agents, poll GitHub, claim a lease, or acknowledge Agent Mail.

## Overview

The first screen answers four operating needs: progress, review, intervention, and the state of automation.

```text
Claude Deck                                  Backend instance
Overview                   Team   Repository   Harness filters

Queued     In progress     Needs review     Needs attention

Needs your attention
Issue and repository | Team and owner | Waiting reason | Open

Ready for human review
Issue and PR | Code or design | Verification summary | Open PR

Active work
Issue | Current stage | Owner and harness | Last observed change

Repository automation
Repository and team | Configured enabled/paused | Intake state | Poll freshness
```

Counts cover every matching work item, not only the loaded list page. Each count links to Work with the matching category and the same filters.

An attention section identifies the waiting actor and reason when the backend can establish them. A pending agent approval is labelled **Waiting for Leader**, not presented as an operator approval button. Human review and protected operator remedies receive distinct labels.

M1a uses current-state counts. A “delivered today” chart appears only after M3 has sourced delivery outcomes and trustworthy event times for that range.

Show the observed runtime mode alongside repository automation: normal, recovery-only, or unknown, plus scheduler running/stopped/unknown. **Configured enabled** describes saved toggles. **Intake eligible**, **Intake blocked**, and **Intake unknown** describe whether normal intake can be attempted. Recovery-only mode explains that new intake is blocked even for enabled scopes. Suspended polling has its own label and last observation time. Protected recovery-target details remain behind their existing operator authorization.

With no watched repositories, present **Configure a repository**, **Open live sessions**, and a prominent **Open Harnesses and configuration** entry. Repository configuration links to the existing flow in M1a and the guided flow in M2. The Harnesses entry reaches the existing guarded configuration summary, so configuration-only users can continue their daily work without setting up a factory. With filters that match nothing, show Clear filters instead of a setup instruction.

## Work

Provide a readable table as the first implementation. A board can follow if it improves real operating tasks.

| Column | Content |
| --- | --- |
| Issue | Number, title, repository, and team |
| Stage | Raw status rendered clearly, display category, code/design type, implementation/diagnostic phase |
| Owner | Name and current configured harness; distinguish observed runtime where available |
| Waiting | Pending reason, next actor, escalation, handoff, or unavailable evidence |
| PR | Canonical PR link and verification evidence available from the existing system |
| Updated | Deck record update timestamp labelled as an observation |
| Actions | Open details; eligible existing remedies when their authorization prerequisites are met |

The categories are Queued, In progress, Needs review, Needs attention, Finished, and Unknown. The [architecture contract](architecture-contracts.md) owns the raw-status mapping.

Rows use work-item IDs as keys. Preserve multiple rows for the same issue tracked by different teams. Use **Load more** when another cursor page is available.

Starting Load more pauses automatic refresh of that list. Preserve its accumulated rows, cursor, scroll position, and focus, and ignore an older first-page response already in flight. Show **Live updates paused while browsing older results**, the observation time, and **Refresh from start**. That explicit action or a filter change returns to the first page and resumes polling. Overview counts and details can refresh independently and show their own timestamps.

The Finished category means tracking ended. A raw `completed` state can come from issue closure without a delivered artifact. Details explain the known closure/result evidence and leave delivery or human review unknown when unproven. M3 presents evidenced delivery outcomes separately from this category.

An item escalated through the existing abandon endpoint remains in Needs attention, with **Operator requested stop** as its reason. Explain that an agent may still be running and that manual or issue-update retry can remain possible under existing rules. Do not visually move it to Finished to imply a permanent stop.

## Work details

Use a route at `/work/:workItemId` so an operator or implementation agent can share a precise link. An unknown ID shows a useful not-found state.

The page contains:

1. Issue, team, repository, owner, approver, and current phase.
2. Current state, waiting reason, and the next known actor.
3. PR identity and the verification evidence available for that PR head.
4. Finite policy and recovery counters, keeping implementation retries and diagnostic failed heads separate.
5. Safe workspace ID/state and session association, with read-only terminal access when the bound session is unambiguous. Absolute workspace paths and private revision text stay outside the ordinary factory projection.
6. Context links to team, repository, relevant Mail, and native harness settings.
7. Recovery history and remedies using the existing authorization contracts.

Loading a work page is an observational read. The page must not call agent tools such as `deck_get_work_item_context`, which can perform an owner continuation claim.

M1a can show known timestamps and current authority from existing projections. Describe these as known milestones. A complete chronological audit appears only when P05 supplies recorded events and coverage metadata.

Protected recovery history is fetched separately after operator authorization. Basic work details remain usable without a token prompt.

If the verified owner or Leader is offline, show **Review launch for [slot name]**. Open that team's launch planner with the slot selected, show any state/readiness blocks, and use the existing operator-authenticated plan review before launch. A pending Leader decision never becomes a browser approval action. Unknown or ambiguous actor identity opens team/session inspection instead of guessing whom to launch.

## Operator actions and their meaning

| Label or behavior | Meaning |
| --- | --- |
| Open PR | Navigate to GitHub; does not approve or merge |
| Retry issue | Use existing retry eligibility and explain that attempt markers can be reset |
| Resume prepared attempt | Preserve the prepared attempt through the existing operator route |
| Recovery information | Explain how the owner proposes a revision and the designated Leader decides |
| Release decision hold | Allow the Leader to decide; the operator does not supply the decision |
| Release acknowledgement hold | Allow the owner to acknowledge; the operator does not acknowledge as owner |
| Cancel continuation | Apply the appropriate existing request or active-revision cancellation |
| Escalate attempt | Use the existing protected abandon route with a reason; explain nonterminal state, possible retry, and that process termination is not guaranteed |
| Review launch for an offline actor | Open the current team/slot launch plan; explicit authenticated review precedes launch |
| Release workspace | Use the existing inspection and protected force-release flow when appropriate |

The browser does not act as an owner or Leader. A convenience message to an agent is a Mail action with visible recipients and content; it does not constitute an approval or continuation proposal.

Use backend-derived eligibility and block reasons. Re-fetch the item after a successful action or a conflict. Preserve actionable `401`, `403`, and `409` details. An unavailable or ambiguous result remains visible until reconciled. Refreshing an affected detail does not restart a paused paginated list; mark that list as needing refresh and preserve its browsing position.

The audited source already protects team/scope/slot policy changes. Retry and launch also preserve specific authenticated agent paths. Browser controls use the shared operator credential helper and current client signatures; the [authorization matrix](architecture-contracts.md#operator-authorization-prerequisite) owns the exact contract. Do not create a second token store for the new shell. Measure repeated prompts and multi-tab friction in the pilot; a new login model is a separate decision.

## Automation controls

The existing team and scope toggles control the scheduler's automation, including its monitoring and verification stages. Existing agents may continue running after automation is disabled.

Use **Pause automation** with an explanation of that effect. A per-repository control identifies the team and scope it changes. Do not present the existing toggle as a guarantee that active processes have stopped.

Separate dispatch activation, merge policy, and recovery policy in the interface. A human merge policy and a design task's human-review requirement remain explicit.

A configured toggle is never the sole runtime-health indicator. Show the backend's effective intake projection and safe reason when the recovery gate, a stopped scheduler, or a missing job prevents intake. Unknown runtime observations remain unknown. Intake eligibility does not promise that access, worker readiness, labels, or capacity permit a particular issue to dispatch.

A future control for pausing only new intake needs a separate backend contract. Stopping a session continues to use the existing Agent Bridge action and confirmation.

## Repositories and Teams

Repositories group watched scopes by GitHub owner/name and show each associated team, primary checkout, polling state, dispatch labels, merge policy, and finite budgets. Local project discovery remains available as a secondary **Local projects** surface; a local project and a watched GitHub scope are different records.

Warn when enabled scopes on the same repository share a dispatch label: identify their teams/scopes and explain that the same issue can dispatch independently more than once. Preserve separate rows. This warning describes a potential collision; it does not promise cross-team arbitration.

The route `/repositories/:scopeId` opens the selected team's scope. Changing a scope's identity remains subject to existing active-attempt and lease checks.

Teams retain reusable rosters and launch planning. Add stable selection through `/teams/:teamId`. Teams with watched scopes initially open their activity; manual-only teams initially open their roster. M1a shows the actual derived Leader and explains roster-order behavior. M2 replaces that convention with explicit assignment after the backend migration.

Team deletion must first pass the server's paused/in-use checks. A conflict identifies blocking work, approvals, revisions, or leases and links to their existing inspection/remedy surfaces. A confirmation dialog cannot permit deletion of active records.

M2 setup creates new teams with automation off and always creates new scopes with `enabled: false`. Reusing an active team preserves its existing operation and Leader; the review screen identifies the new scope and any separately requested edits. A blocked Leader change offers retaining the current assignment or choosing another team. Setup never pauses that team's other repositories to satisfy a role-edit precondition.

Saving, launching selected slots from a reviewed plan, and activating the new scope are separate actions. If activation requires enabling a paused team, show every existing enabled scope that would resume. Reopening a partial setup preserves acknowledged IDs and existing activation values instead of applying new-record defaults again.

M2's **Check access and labels** action reports dated repository-read access, dispatch/design label existence, checkout identity, and configured host prerequisites separately. Show missing and unknown checks with the exact remaining host steps; never show credential values. Missing labels link to GitHub instructions and are not created automatically. Saving disabled configuration remains possible, but guided activation waits for required checks. Recheck before activation and show current same-label overlap warnings for explicit acknowledgement. Call this guided configuration, and include credential setup/restarts in any observed first-PR timing.

## Harnesses and native settings

In M1a, Harnesses is a thin index for Claude Code, Codex CLI, Copilot CLI, OpenCode, and Pi. It uses existing registry/status facts and links only to verified native adapters, the guarded configuration summary, and existing team/session operations. It does not depend on P03's planned operations API or claim comprehensive credential/session readiness.

In M1b, after the pilot checkpoint, cards add operational support, launch configuration readiness, credential-check status, live session information, and native configuration coverage.

The screen must not rank harnesses by the number of Claude-specific configuration features. It must not equate an installed binary with a verified working team session.

Use `/harnesses/:providerId` for the native entry point and `/harnesses/:providerId/:surface` for implemented native settings surfaces. The provider in the route supplies the configuration context. In M1a, the checked-in provider/page/API adapter registry gates mounting, reads, and writes. In M1b, require an available matching `native_surfaces` entry as well, using the intersection of allowed access. Resolve guards before mounting or fetching; a missing/mismatched catalog or adapter renders an explanation.

Unsupported deep links explain the missing capability and offer supported operations. They never fall through to Claude settings endpoints. Native settings can retain their own project selector and saved harness preference.

Positive native capability flags can describe CLI inventory or Agent Mail integration without a corresponding page. For example, OpenCode config/plugins/usage classifications do not enable the legacy editors. Show those integration capabilities accurately while keeping unavailable page links disabled or explanatory. Apply the same rule to native dashboard cards and compatibility routes.

## Compatibility

| Existing route | Handling |
| --- | --- |
| `/agent-teams` | Alias to `/teams`, preserving query and hash |
| `/cc-bridge` | Keep the existing Agent Bridge alias |
| `/agent-mail` | Remain directly accessible |
| `/projects` | Remain accessible as Local projects |
| `/config`, `/mcp`, `/plugins`, and other native settings routes | Remain guarded compatibility entries using the saved configuration harness preference |
| `/sessions` and transcript detail routes | Preserve the history surface and its provider boundaries |
| `/plans`, `/usage`, `/context`, `/backup` | Preserve access through implemented native surface adapters and their read/write limits |

Legacy provider preference may initialize a native editor. It does not filter delivery work. The milestone's native adapter/availability and read/write guards apply even when a user bypasses navigation and opens a URL directly.

## Loading and accessibility

Use explicit initial loading, refresh-in-progress, stale-data, empty, filtered-empty, error, forbidden, unknown, and not-found states. Keep the last successful data visible after a refresh failure and label its age.

The initial refresh target for visible Overview, details, and first-page delivery lists is five seconds. Lists pause polling as soon as Load more starts and retain that state when a hidden tab becomes visible. Hidden tabs pause other polling too. Requests for the same data are shared; old responses cannot overwrite a newer filter, detail selection, or pagination generation. Browser refresh does not trigger an extra GitHub poll.

Use semantic tables, labelled filters, keyboard-operable actions, text status labels, visible focus, and focus restoration after dialogs. Status meaning must survive color removal. Preserve useful layout at 360px, 768px, and 1280px viewport widths.
