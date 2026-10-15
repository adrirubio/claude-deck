# Website plan for claudedeck.org

For: row 743 under parent issue #745. This plan uses `01-audit.md` and `02-factory-story.md` on master.

Main action: **Understand and share it.** A director reads the home page, understands the factory, and forwards one link, one page, or one short video.

This plan names evidence for each claim. A claim with no evidence does not enter the copy.

## Sources

- `01-audit.md` records the current site, the docs, and the product screens.
- `02-factory-story.md` gives the one sentence, the one paragraph, the roles, and the glossary.
- `docs/guide/operating-model.md` defines the factory, the Director, the Leader, and the retained decisions.
- The website reference is a separate repository. This plan cites it as `website-ref` at commit `0c35f391759633c774b7cc4ace5c52b96dd53d12`. This plan does not change it.
- An isolated test instance supplied fresh screen states for this plan. The states are seeded example data. They are not live records and not human trials.

## The reading order for a director

A director reads in this order. Each page answers one question.

| Order | Page | Question the page answers | Director purpose |
|---|---|---|---|
| 1 | Home | What is Deck, and why does it matter? | Understand the factory in one visit. |
| 2 | The factory story | How does one issue become merged work? | Retell the story to a peer. |
| 3 | What you see and decide | What do I watch, and what stays mine? | Learn the screens and the retained decisions. |
| 4 | Share Deck | How do I brief my board or my team? | Forward the link, the one-page summary, or the video. |
| 5 | Limits and trust | What does Deck not promise? | Share with the limits stated, not hidden. |
| 6 | For operators | How does an operator set Deck up? | Hand the setup to a technical operator. |

The home page carries the full director read. The other pages carry depth. No director page starts with install steps.

Evidence: `01-audit.md` finds install steps and developer words on the first screen today. The story gives the director order in Steps 1 to 6.

## Page structure

### Home

Purpose: a director understands and can share Deck after one page.

Sections, in order: first screen, what Deck is, one piece of work, what you see and decide, why it matters, words you need, share it, what Deck does not promise, and a footer that points operators to setup.

### The factory story

Purpose: the full story from `02-factory-story.md`, told as one page.

The page keeps the one sentence, the one paragraph, the six steps, and the retell paragraph.

### What you see and decide

Purpose: one page per screen group, in director words.

The page covers Overview, Work, Repositories, Teams, Agent Mail, Harnesses, and Audit. Each screen gets one line: what it shows, and which decision it supports.

### Share Deck

Purpose: the share kit on one page.

The page holds the share link text, the one-page summary, and the short video. Each item stands alone. A peer needs no other page first.

### Limits and trust

Purpose: the honest limits in one place.

The page states local running, operator setup, seeded example data, and locked Audit events. It also states that Usage shows Claude Code session estimates and that factory delivery cost stays unknown. It claims no measured time saving.

### For operators

Purpose: setup and depth for a technical operator.

This page links to the docs. It holds install steps, harness setup, and autonomy setup. It keeps those topics off the director pages.

Evidence for the structure: `01-audit.md` ranks the missing director decision map and the missing share artefact in its top problems. `02-factory-story.md` supplies the story order.

## Draft copy for the home page

The mockup at `mockup/index.html` uses this copy. The copy uses the story sentence, paragraph, and glossary terms.

### First screen

Heading: **Your AI team ships GitHub work. You keep the decisions.**

Deck runs a team of AI agents that take GitHub issues to reviewed work, while the people in charge keep the key decisions.

One issue goes in. Reviewed work comes out. You see who owns each item, what waits for a person, and what the audit ledger recorded.

Button: **Understand and share it.** Button: **See one piece of work.**

Evidence: the heading sentence is the story one sentence, in director words. `02-factory-story.md` gives that sentence and the roles.

### What Deck is

Deck is a local workspace where a director runs AI agent teams on GitHub work. The director owns the backlog and sets the goal. The assigned owner proposes a plan and the designated Leader approves it. Members build the work, reviewers check it, and the Supervisor, when one is assigned, watches the factory and repairs routine faults under delegation. The director sees progress on Overview and Work, tracks repositories and teams, checks the audit record, and still decides publication, budgets, models, and security stops. GitHub stays the home for issues, pull requests, and review.

Evidence: this paragraph is the story one paragraph. `02-factory-story.md` states its evidence.

### One piece of work

Follow one issue from goal to merged work.

1. You write the issue and order the backlog.
2. The owner proposes a plan. The Leader approves it.
3. A member builds the change and opens a pull request.
4. A reviewer checks the exact version. Checks run.
5. The pull request merges under repository policy.
6. The audit ledger keeps the record.

This path is an example. It is not a measured delivery.

Evidence: Steps 1 to 6 in `02-factory-story.md` tell this path with screens and gates.

### What you see and decide

Overview shows what needs you. Work shows each owner and each waiting reason. Repositories shows which backlog feeds each team. Teams shows the roster and the named Leader. Audit shows what the factory did, with its limits.

Your decisions stay yours: the goal, the backlog order, publication, budgets, models, and security stops. The Leader approves agent plans inside those limits.

Evidence: `01-audit.md` records Overview with "Needs you", Work with owners and waiting reasons, and Teams with the roster and the named Leader. `docs/guide/operating-model.md` lists the retained decisions.

### Why it matters

Control. You own the backlog and the retained decisions. The Leader approves plans inside your limits.

Visibility. You see waiting work on one screen. You do not open each agent session to learn who waits.

Safety gates. A plan needs Leader approval before build. A pull request follows repository policy before merge. A security stop stays with you.

Cost, stated with its limit. The Usage screen shows Claude Code session estimates where Deck can read them. Factory delivery cost stays unknown. This site claims no saving that no trial has measured.

Evidence: `02-factory-story.md` states each point with its source. `docs/features/usage.md` covers the session estimates. `docs/guide/factory-audit-and-metrics.md` keeps cost unknown.

### Words you need

The home page defines five words in place: team, Leader, member, pull request, and audit ledger. The factory story page carries the full glossary of 15 words.

Evidence: `01-audit.md` finds `harness`, `pull request`, and `ledger` in use before any definition today. The glossary in `02-factory-story.md` defines each word in one sentence.

### Share it

Send the link. The home page is the brief.

Send the one-page summary. It carries the one sentence, the six steps, and the limits.

Show the video. It walks the normal path in story order: queued, active, review, finished. It shows attention separately, as the exception that needs a person. Each state shows a different example issue. The clip ends on the Audit screen.

Evidence: `01-audit.md` finds no share artefact on the site today. This section creates the three artefacts. The video script follows Steps 1 to 6 in `02-factory-story.md`.

### What Deck does not promise

Deck does not promise a time saving. No trial measures director time saved.

Deck does not work alone for you. A person writes the goal, sets the limits, and decides publication.

Deck runs on your machine. An operator sets up the host first. Deck changes real local agent files.

Deck does not replace GitHub. GitHub holds the issues, the pull requests, and the final record.

Evidence: `02-factory-story.md` states each limit with its source. The local-running limit cites the current landing page in that story.

## Headings and key sentences for the other pages

### The factory story

Heading: **One issue in. Reviewed work out.**

Key sentence: The owner proposes the plan, the Leader approves it, and you keep the decisions that matter.

The page then gives the six steps and the retell paragraph from the story.

### What you see and decide

Heading: **Watch the work. Keep the decisions.**

Key sentence: Overview shows what needs you, Work shows who owns each item, and Audit shows what happened.

Each screen then gets one short block. Each block names the decision the screen supports.

### Share Deck

Heading: **Brief your board in one page.**

Key sentence: Send the link, send the one-page summary, or show the short video. Each one stands alone.

### Limits and trust

Heading: **What Deck does not promise.**

Key sentence: Usage shows Claude Code session estimates. Factory delivery cost stays unknown, time saved stays unmeasured, and a person keeps the final decisions.

### For operators

Heading: **Set up Deck on your machine.**

Key sentence: An operator installs Deck, connects the agent tools, and turns on team automation under policy.

This page links to the quick start and the autonomy guide. It holds no director copy.

Evidence: the headings use the story terms. The operator key sentence matches the audience line in `01-audit.md`: the product today speaks to technical operators first. This plan gives directors their own pages and keeps operator depth here.

## Screenshots and short clips each section needs

Each request names the real Deck screen and the seeded state to capture. Capture new images from the tested source. Do not reuse the old site images.

The old images freeze older versions. Evidence: `01-audit.md` records the two main images at version 3.0.0 and six feature previews with a v2.0.0 footer. The tested source reports version 3.1.0.

Seed evidence: the test seed holds five different issues, one per work state. Evidence: `scripts/e2e/scenarios.py` seeds issues #101 to #105 in the attention, review, active, finished, and queued states. No single seeded issue moves through all states. The clip below therefore narrates static states. It does not show one issue in motion.

| Section | Screen to capture | Seeded state to show | What the director learns | Limit to print with the image |
|---|---|---|---|---|
| First screen | Overview | Seeded counts with one item in each state: queued, active, review, attention, finished | Work waits in named states, and one state needs a person | Seeded example data. Not live records. |
| What Deck is | Teams | Seeded team "Release crew" with a named Leader and its member slots | A team is a roster with one Leader | Seeded roster. Not a live team. |
| One piece of work | Work | Five seeded work items, one item per state, shown with the All filter. Four items name an owner. The queued item, #105 "Add keyboard shortcuts", has no owner yet. | Each state exists at once, and the queued item still waits for an owner | Seeded example data. The default Work filter hides finished work, so the capture names the All filter. The path is an example, not a measured delivery. |
| What you see and decide | Overview | The "Needs you" area with campaign progress and team summaries | The screen puts the director decision first | Browser observation from the audit. Counts alone do not prove the summaries. |
| What you see and decide | Repositories | Three seeded repository scopes, with paused intake on two scopes | A backlog feeds a team only when intake allows it | Seeded scopes. Paused intake shows no live polling. |
| Why it matters, safety | Work | One seeded item that waits for review, with its pull request field | A gate stops work until a reviewer acts | Review follows repository policy. This image shows one example policy. |
| Agent tools, on For operators | Harnesses | Six seeded harness providers with setup and support labels | Deck shows the setup and support for each agent tool | This capture supports agent-tool setup only. It supports no cost claim. Account, model, and session readiness stay unknown without a separate check. |
| Limits and trust | Audit | Safe delivery metrics with the event list locked | The ledger shows metrics, and events stay behind an access gate | Locked events are an access gate, not a load failure. No event rows shown. |
| Limits and trust | Agent Mail | No public capture. The only observed state stayed at participant loading. | No director claim rests on this screen yet | Keep this state in the evidence limits. Add a public capture only when a supported coordination state exists. The limit proves no Mail failure and no docs defect. |
| Share it | Overview, Work, and Audit, as a clip | The seeded stills for the normal path in story order: queued, active, review, finished. One separate attention still. One closing Audit still with safe metrics and events locked. Each state shows a different seeded issue. | The director sees the normal path, the exception that needs a person, and the ledger screen that closes the story | Narrated example over static states. No single seeded issue moves through all states. The Audit still shows no event record for these issues. Not a measured delivery time. |

Short clips: one clip only. The clip narrates the normal path: queued, active, review, finished. It then shows attention separately, as the exception that needs a person. Evidence: `backend/app/services/factory_projection_service.py` maps attention to escalated or failed work, and the seed gives issue #101 an owner idle timeout. The clip closes on the Audit still above. Its narration states that each state shows a different example issue. It adds no new claim.

Still open: Usage cost. No image in this plan shows a cost total as proof. Evidence: `01-audit.md` records the old Usage image with zero totals, and `docs/guide/factory-audit-and-metrics.md` keeps factory cost unknown. The cost copy above states the limit in words instead.

## What to remove or move to the docs

Remove from the home page:

- The install steps and the shell commands. Move them to For operators and the quick start. Evidence: `01-audit.md` finds `git clone` and script commands on the landing page.
- The tech list. Move it to the architecture docs. Evidence: `01-audit.md` lists the stack names on the landing page.
- The old screenshots at two older versions. Replace them with the captures above. Evidence: `01-audit.md` contradiction 2.
- The five-harness claim. The product has six harnesses. Evidence: `01-audit.md` contradiction 1, from the providers response and `docs/index.md`.
- Feature cards in operator words. Rewrite each card as one director sentence, or move the card to the feature docs. Evidence: `01-audit.md` finds operator words in the cards.

Move to the docs, and link from Limits and trust:

- Autonomy host setup and token steps. Evidence: `01-audit.md` finds host setup in `docs/autonomy.md`.
- Harness readiness detail and per-tool setup. The home page keeps one line: Deck shows the setup and support for each agent tool.
- Audit event access detail. The home page keeps the locked-gate line.

Keep on the home page: the story, the screens in director words, the retained decisions, the share kit, and the limits.

## How a director shares Deck

Three ways. Each way stands alone.

1. **A link.** The director sends the home page link. The first screen carries the one sentence, the path, and the decisions. The peer needs no setup and no account to read it.
2. **A one-page summary.** The director sends one page with the one sentence, the six steps, what the director decides, and the limits. The summary prints cleanly and forwards as a document.
3. **The video.** The director shows a clip under three minutes. The clip walks the normal path in story order: queued, active, review, finished. It shows attention separately, as the exception that needs a person. Each state shows a different example issue. The clip ends on the Audit screen, with safe metrics and events locked. That ending shows no event record for these issues.

Evidence: `01-audit.md` finds only Docs and GitHub links today, and no forwardable brief. The three items above close that gap. Each item uses only claims from `02-factory-story.md`.

Share limits: the summary and the video use seeded example data. Each one says so. Neither one claims a measured saving or a measured delivery time.

## The mockup

The mockup at `mockup/index.html` shows the new home page with the draft copy above.

It is one self-contained HTML file. It uses inline CSS only. It makes no external requests. It holds no script that fetches data.

The first screen shows the factory intent at once: the one sentence, the issue-to-merged-work path, and what the director sees and decides. A critic reads the mockup as a director and confirms that intent on the first screen.

The mockup is a plan artifact. It is never deployed. No step in this plan copies it to the website repository.

Check: search the mockup file for external references and require no matches. The build notes record the exact command and its result.

## What this plan does not promise

This plan does not promise a published site. Publication stays a Director decision under the parent issue.

This plan does not promise that seeded screens prove live value. Each capture carries its seeded-data limit.

This plan does not promise a human verdict. A critic reads the mockup as a director. No human director trial has run.

This plan keeps factory delivery cost unknown and claims no time saving. Evidence: `docs/guide/factory-audit-and-metrics.md` and `02-factory-story.md`.

