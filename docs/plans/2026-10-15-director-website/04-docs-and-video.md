# Director docs plan and video concept

For: row 744 under parent issue #745. This plan uses `01-audit.md`, `02-factory-story.md`, and `03-website-plan.md` on master.

This file plans two things. It plans the documentation for directors. It plans the product video concept. It produces neither one. Both stay later work.

Each claim names its evidence. A claim with no evidence does not enter the plan.

## Sources

- `01-audit.md` records the current docs, page by page, with limits.
- `02-factory-story.md` gives the one sentence, the roles, and the glossary of 15 words.
- `03-website-plan.md` gives the website pages, the home-page copy, and the share ways.
- The existing docs live in `docs/guide/`, `docs/features/`, `docs/index.md`, and `docs/autonomy.md`.
- An isolated test instance supplied fresh seeded screen states for the storyboard. The states are seeded example data. They are not live records and not human trials.

## Part 1. The docs plan

### The problem in one paragraph

A director opens the docs and meets operator words first. Evidence: `01-audit.md` finds the docs home hero abstract, the guide first line dense, and the quick start first step a shell command. The factory story exists in `docs/guide/operating-model.md`. No page gives a director a short path through it.

### The reshaped structure

Three paths. Each path serves one reader. No path borrows another path's first step.

| Path | Reader | First page | Rule |
|---|---|---|---|
| Start here | Director | What Deck is | No install step, no shell command, no undefined word. |
| For operators | Technical operator | Set up Deck on your machine | Holds install, harness setup, and autonomy setup. |
| Reference | Developer and operator | Feature and API pages | Holds depth, fields, and rules. It holds no director copy. |

Evidence: `01-audit.md` separates the missing public director pages from the existing source pages that need revision. `03-website-plan.md` gives the website the same three-way split.

### The Start here path, page by page

Read the pages in this order. Each page answers one question.

| Order | Page | New or changed | Purpose | Short outline |
|---|---|---|---|---|
| 1 | What Deck is | New director page | The director learns the factory in two minutes | The story one sentence. The story one paragraph. One picture of the path: issue, plan, build, review, merge, record. A link to the full story. |
| 2 | A first look at Overview | New director page | The director learns what needs a person | What "Needs you" means. Campaign progress in plain words. Which item waits for the director, and which waits for the team. |
| 3 | A first look at Work | New director page | The director learns who owns each item | One row explained: owner, state, waiting reason, pull request link. The four normal states and the attention exception. |
| 4 | A first look at Repositories and Teams | New director page | The director learns which backlog feeds which team | One scope explained in plain words. The roster, the named Leader, and the supervisor status. Repository count and work count. |
| 5 | A first look at Audit | New director page | The director learns what the ledger proves | Safe metrics in plain words. Coverage limits. The locked event list as an access gate, not a failure. Cost stays unknown. |
| 6 | The decisions that are yours | New director page | The director learns the retained decisions | Goal and backlog order. Publication, budgets, models, security stops. The Leader approves agent plans inside those limits. Human review follows repository policy. |
| 7 | Words you need | New director page | The director learns the 15 words | The glossary from the story, one short sentence per word. Each word links to the page that uses it. |
| 8 | Limits and trust | New director page | The director learns what Deck does not promise | Local running and operator setup. Seeded example data. Locked Audit events. Usage session estimates beside unknown factory cost. No measured time saving. |
| 9 | Share Deck from the docs | New director page | The director briefs a peer from the docs | The link, the one-page summary, and the video. Each item stands alone. |

Evidence for the screen claims: `01-audit.md` records Overview with "Needs you" and campaign progress, Work with owners and waiting reasons, Teams with the roster and the named Leader, Repositories with enablement apart from intake, and Audit with safe metrics and locked events. `02-factory-story.md` gives the retained decisions. The glossary comes from the story, at 15 words.

Screen limits that the pages must print:

- Agent Mail holds no director page in this path. The only observed state stayed at participant loading. Evidence: `01-audit.md` records that state as an open observation limit. It proves no Mail failure and no docs defect. Add a Mail page only when a supported coordination state exists to show.
- Harnesses gets one line on the operator path, not a director page. The screen shows setup and support. Account, model, and session readiness stay unknown without a separate check. Evidence: `docs/features/harnesses.md`.

### What changes in the existing docs

| Page | Change | Reason |
|---|---|---|
| `docs/index.md` (docs home) | Add a Start here block at the top, before the operator actions | The hero and first action suit an operator today. Evidence: `01-audit.md` docs home finding. |
| `docs/guide/index.md` | Add the director path as the first next step. Keep the dense definition below it | A director gets no short briefing path today. Evidence: `01-audit.md` guide finding. |
| `docs/guide/operating-model.md` | Keep the content. Add a plain summary at the top and link it from Start here | The page defines the factory and the roles. It needs revision for a director, not creation. Evidence: `01-audit.md` operating model finding. |
| `docs/guide/quick-start.md` | Move it under For operators. No director page links to it as a first step | Its first step is a shell command. Evidence: `01-audit.md` quick start finding. |
| `docs/features/dashboard.md`, `work.md`, `repositories.md`, `agent-teams.md` | Add one director line at the top of each: what the screen shows, and which decision it supports. Keep the operator depth below | The pages name counts and filters before the decision. Evidence: `01-audit.md` feature findings. |
| `docs/features/agent-mail.md` | No director change in this plan | The page text stands. The loading observation is a product limit, not a docs defect. Evidence: `01-audit.md` Agent Mail finding. |
| `docs/features/harnesses.md` | Keep on the operator path. Keep the readiness limit in the first lines | The page supports setup claims only. Evidence: `docs/features/harnesses.md`. |
| `docs/features/usage.md` | Add one director line: Usage shows Claude Code session estimates. Factory delivery cost stays unknown | The split prevents a false cost claim. Evidence: `02-factory-story.md` cost line and `docs/features/usage.md`. |
| `docs/autonomy.md` | Keep on the operator path. No director page sends a reader here first | The opening suits an operator and the setup needs a host token. Evidence: `01-audit.md` autonomy finding. |
| Sidebar in `docs/.vitepress/config.ts` | Add a Start here group for directors at the top of the guide sidebar. Keep Guide and Features below it | The sidebar links the operating model today but gives no director entry. Evidence: `docs/.vitepress/config.ts` guide sidebar and `01-audit.md`. |

### Docs rules

- Each director page defines its words on first use, or links to Words you need.
- Each director page states its limit on the same page. No page hides a limit in another path.
- No director page starts with a command, a token, or a setting.
- Operator pages keep their depth. This plan moves entry points. It deletes no operator content.

## Part 2. The video concept

Producing the video is later work. This part gives the concept, the script draft, the storyboard, and the voice requirements.

### Audience and message

Audience: a director who has never seen Deck, and the peer that director forwards the video to.

Message: your AI team ships GitHub work, and you keep the decisions.

Length: two to three minutes. At the pace below, the script runs about two and a half minutes.

The video uses seeded example screens. Each shot says so in its caption where the data appears. The video claims no measured delivery and no time saving. Evidence: `03-website-plan.md` sets those limits for the clip.

### Script draft

Read the script aloud at the pace in the voice requirements. Times are guides for the editor.

**Opening, 0:00 to 0:20.** "This is Deck. Deck runs a team of AI agents that take GitHub issues to reviewed work. You write the goals. You keep the key decisions. In the next two minutes, you see one factory at work, on example data."

**The path, 0:20 to 1:00.** "You write an issue and order the backlog. The owner proposes a short plan. The Leader approves it. A member builds the change and opens a pull request. A reviewer checks the exact version, and checks run. The pull request merges under your repository policy. The audit ledger keeps the record."

**What you see, 1:00 to 1:35.** "You do not open each agent session to learn who waits. Overview shows what needs you. Work shows each owner and each waiting reason. Teams shows the roster and the named Leader. When work needs a person, it waits in attention. That is the exception, not a step on the path."

**Your decisions, 1:35 to 2:05.** "The Leader approves agent plans inside your limits. Your decisions stay yours: the goal, the backlog order, publication, budgets, models, and security stops. Deck runs on your machine, and an operator sets up the host. GitHub holds the issues, the pull requests, and the final record."

**Close, 2:05 to 2:30.** "Deck shows session cost estimates where it can read them. The cost of a whole delivery stays unknown, and no trial yet measures time saved. So Deck makes one promise it can show: your team ships GitHub work in the open, and you keep the decisions. Send this link, send the one-page summary, or start with the story."

Evidence for the script: the opening uses the story one sentence. The path follows Steps 1 to 6 in `02-factory-story.md`. The decisions match the retained decisions in `docs/guide/operating-model.md`. The close keeps the cost split from `docs/features/usage.md` and `docs/guide/factory-audit-and-metrics.md`.

### Storyboard

Each shot names the real Deck screen and the seeded state to capture. The seed holds one issue per state. Each state therefore shows a different issue. The narration states that limit where the states appear in sequence.

| Shot | Time | Screen | Seeded state to capture | Narration line it carries | Caption or limit on screen |
|---|---|---|---|---|---|
| 1 | 0:00 | Overview | Seeded counts with one item in each state | "This is Deck." | Example data. Not live records. |
| 2 | 0:20 | Work, All filter | Queued item #105, "Add keyboard shortcuts", with no owner yet | "You write an issue and order the backlog." | The queued item waits for an owner. |
| 3 | 0:35 | Teams | Seeded team "Release crew" with its named Leader and member slots | "The owner proposes a plan. The Leader approves it." | Seeded roster. Not a live team. |
| 4 | 0:50 | Work, All filter | Active item #103, "Document the import format", with its owner | "A member builds the change." | One state, one example issue. |
| 5 | 1:05 | Work, All filter | Review item #102, "Fix the settings page layout", with its pull request field | "A reviewer checks the exact version, and checks run." | Review follows repository policy. |
| 6 | 1:20 | Overview | The "Needs you" area with campaign progress | "Overview shows what needs you." | Counts alone do not prove the summaries. |
| 7 | 1:35 | Work, All filter | Attention item #101, "Add the CSV export button", stopped after its owner went idle | "When work needs a person, it waits in attention." | Attention is the exception, not a path step. |
| 8 | 1:50 | Work, All filter | Finished item #104, "Rename the sync command", in merged state | "The pull request merges under your repository policy." | Example path. Not a measured delivery. |
| 9 | 2:05 | Audit | Safe delivery metrics with the event list locked | "The audit ledger keeps the record." | Events stay locked. This shot shows no event record for these issues. |
| 10 | 2:20 | Overview | The first-screen view from shot 1 | "You keep the decisions." | Send the link or the one-page summary. |

Seed evidence: the test seed creates issues #101 to #105 in the attention, review, active, finished, and queued states, each with its own title. Evidence: `scripts/e2e/scenarios.py`. A fresh check of the test instance returned the same five states. The default Work filter hides finished work, so shots 2, 4, 5, 7, and 8 name the All filter. Evidence: `03-website-plan.md` records that filter rule from the audit review.

Excluded shots:

- No Agent Mail shot. The observed state stayed at participant loading. A loading screen shows no coordination. Evidence: `01-audit.md`.
- No Usage total as proof of cost. The old Usage image shows zero totals, and factory cost stays unknown. Evidence: `01-audit.md` and `docs/guide/factory-audit-and-metrics.md`.
- No install or terminal shot. Setup belongs to the operator path. Evidence: `01-audit.md` install finding.

### AI voice requirements

The voice is an AI voice. The video states that fact in its credits. The requirements below bind the voice choice.

Tone:

- Calm and plain. The voice sounds like a briefing officer, not an advert.
- Confident on facts. Careful on limits. The voice gives each limit the same weight as each claim.
- No excitement words. No "revolutionary", no "effortless", no "game changer".

Pace:

- About 140 words per minute. The script runs about two and a half minutes at that pace.
- One sentence, then a short pause. A breath pause at each shot change.
- Numbers and state names get a slower pace: queued, active, review, attention, finished.

Pronunciation of product words:

| Word | Say it as | Rule |
|---|---|---|
| Deck | "deck", one syllable | Never spell it out. Never say "the deck platform". |
| Claude Deck | "clawd deck" | Keep the product name together. |
| harness | "HAR-ness" | Say "agent tool" right after the first use. |
| pull request | "pull request", both words in full | Never say the short form in this video. |
| audit ledger | "AW-dit LED-jer" | Keep both words. Never shorten to "the ledger" in the script lines above. |
| Leader | "LEE-der", with stress on the first part | Always "the Leader" for the role. |
| Supervisor | "SOO-per-vy-zor" | Say "the Supervisor, when one is assigned" at first use. The role is optional. |
| GitHub | "GIT-hub" | Keep the name plain. No added claim about the service. |
| Overview, Work, Teams, Audit | Say each screen name in full, then pause | The listener must map each name to the shot on screen. |

Do and do not:

- Do read every limit line in full. Do not lower the voice or speed up on limits.
- Do keep one voice for the whole video. Do not switch voices per section.
- Do not add music under the limit lines. Keep the close quiet.
- Do not let the voice invent a benefit. The voice reads the approved script only.

## What this plan does not promise

This plan does not produce the docs pages or the video. Both stay later work, after the Director approves this plan under the parent issue.

This plan does not promise that seeded screens prove live value. Each shot and page carries its seeded-data limit.

This plan does not promise a human verdict. Reviews so far are agent readings. No human director trial has run.

This plan keeps factory delivery cost unknown and claims no time saving. Evidence: `docs/guide/factory-audit-and-metrics.md` and `02-factory-story.md`.
