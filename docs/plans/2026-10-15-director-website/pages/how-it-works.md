# How it works — final page copy

For: issue #779, page 2 of 4 under parent issue #777.

This file is the complete copy for the How it works page, in page order, ready for the Supervisor to build from on the preview branch. Text under a **Page copy** heading is the exact text for the page. Placement notes, screenshot requests and evidence notes are guidance for the build; they do not appear on the page.

Planned route mapping for the builder (Leader-confirmed 2026-10-16; the three newer routes are intended destinations, not yet live routes): Home `/`, How it works `/how-it-works/`, Quick tour `/quick-tour/`, Technical information `/technical-information/`.

One example feature runs through the steps: adding a short help note to a welcome page. The screenshots show seeded example screens in the states named; each picture shows a different seeded item, so together they illustrate the states rather than showing one live feature moving. Every screenshot carries this label on the image: "Example data — seeded screens. Not live records." Crop every capture to the relevant state, and crop out harness names, old product branding, and unrelated technical chrome; keep the seeded label visible, and do not invent UI labels.

## Page title

Page copy:

> Deck — How it works

## Navigation (top of page)

Page copy:

> Deck
>
> Home · How it works · Quick tour · Technical information

Placement note: as on the home page. "Deck" links to `/`; the four links go to `/`, `/how-it-works/`, `/quick-tour/` and `/technical-information/`, in that order.

## 1. Heading and intro

Page copy:

> # How it works
>
> Follow one feature through the factory, from ready to finished. Our example: adding a short help note to a welcome page. The pictures use different example items to show each stage.

Evidence: the eight steps below are the story's "How it works" layer, updated to the Director's current decisions; the example feature is the one the story uses (`docs/plans/2026-10-15-director-website/02-factory-story.md:64-68`).

## 2. The steps

Placement note for the scene: the "inside the factory" scene sits with this section and plays as the reader scrolls. Its fixed captions and six step labels stay as they are. The scene's six steps match narrative steps 3 to 8 below (Plan, Approve, Build, Review, Check, Merged); steps 1 and 2 set the scene up.

Alt text for the inside scene:

> AI teams take features from plan to finished work at their own pace. Each feature has its own team and colour.

### Step 1 — You write the features and mark them ready

Page copy:

> ### 1. You write the features and mark them ready
>
> Start with the features you want. Give each one a clear result, put them in order, and mark the ones that are ready to build.
>
> **Your call:** the goals, the order, and what is ready.

Screenshot: none. The feature list lives in GitHub, outside Deck, so this step is a written example only; do not invent a Deck screen for it.

Evidence: the Director writes and orders the work, sets the acceptance conditions, and marks what is ready — `docs/guide/operating-model.md:53-57`; the Director owns the outcome — `:17`.

### Step 2 — The AI teams work on their own

Page copy:

> ### 2. The AI teams work on their own
>
> From there, the teams work through the ready features without you steering every step. They follow your goals and limits, and pause work that needs your decision and bring it to you.
>
> **Your call:** pause the work, or change the limits, whenever you like.

Screenshot: Overview. Seeded state: "Needs you" with campaign progress and team summaries, and counts with one item in each state (queued, active, review, attention, finished). Caption and alt text:

> The Overview, with example data: what needs you comes first.

Evidence: normal running inside the Director's retained decisions, with safety stops — `docs/guide/operating-model.md:65`. "Needs you", campaign progress and team decision summaries were seen in a browser with seeded data — `docs/plans/2026-10-15-director-website/01-audit.md:37`; the counts are `docs/features/dashboard.md:7`. Builder note: counts alone do not prove the summaries; the browser observation at `01-audit.md:37` carries that claim.

### Step 3 — The agent owner plans

Page copy:

> ### 3. The agent owner plans
>
> Each ready feature goes to one agent owner. The owner studies it and writes a short plan: what will change, and how it will be checked.
>
> **Your call:** the outcome and the limits — not each plan.

Screenshot: Teams. Seeded state: the "Release crew" roster, with its named Leader and member slots. Caption and alt text:

> A team roster, with example data: its AI Leader and team members.

Evidence: agents propose the plan and the Leader decides — `docs/guide/index.md:13` and `docs/guide/operating-model.md:89`. The seeded roster and named Leader — `docs/plans/2026-10-15-director-website/01-audit.md:40`.

### Step 4 — The AI Leader approves

Page copy:

> ### 4. The AI Leader approves
>
> The AI Leader reads the plan and says yes, or sends it back with questions. Building starts only after that yes.
>
> **Your call:** nothing at this gate — the AI Leader approves inside the limits you set.

Screenshot: Overview. Seeded state: campaign progress and team summaries. Caption and alt text:

> The Overview, with example data: campaign progress and team summaries.

Evidence: the Leader approves plans and selects the next work — `docs/guide/operating-model.md:89`. Campaign progress and team summaries on Overview — `docs/plans/2026-10-15-director-website/01-audit.md:37`, with the same builder note as step 2.

### Step 5 — The agent owner builds

Page copy:

> ### 5. The agent owner builds
>
> The agent owner builds the feature in its own working copy, checks its own work as it goes, and runs the agreed checks before sharing the change for review.
>
> **Your call:** nothing here, unless the team needs a decision only you can make.

Screenshot: Work. Seeded state: work items with their owners and states, the active item building. Caption and alt text:

> Work in progress, with example data: each feature shows its owner and state.

Evidence: team members implement under the Leader — `docs/guide/operating-model.md:27` and `:89-90`; work rows show owner, state and waiting reason — `docs/plans/2026-10-15-director-website/01-audit.md:38` and `docs/features/work.md:5`.

### Step 6 — An AI reviewer checks

Page copy:

> ### 6. An AI reviewer checks
>
> An AI reviewer who did not build the feature gives it a fresh, independent check. Their questions and suggested changes go back to the agent owner.
>
> **Your call:** if your own rules ask you to review as well, that review is yours.

Screenshot: Work. Seeded state: the seeded item waiting for human review under that team's rules. The picture illustrates the "Your call" line, not the AI reviewer's check itself. Caption and alt text:

> Waiting for human review, with example data: under this team's rules, this item waits for a person.

Evidence: implementers build and verifiers check as separate roles — `docs/guide/operating-model.md:18`, `:27` and `:30`. The seeded waiting-for-human-review item — `scripts/e2e/scenarios.py:218-220`. Work rows show owners and waiting reasons — `docs/plans/2026-10-15-director-website/01-audit.md:38`.

### Step 7 — The AI Leader checks, with your supervision

Page copy:

> ### 7. The AI Leader checks
>
> The AI Leader checks the finished work against the approved plan. You and your AI assistants supervise from outside the factory, and anything reserved for you waits for your word.
>
> **Your call:** publication, budgets, AI models, and safety stops stay yours.

Screenshot: Overview. Seeded state: team summaries with anything that needs you. Caption and alt text:

> Team summaries, with example data: progress, and the decisions that need you.

Evidence: the Leader acts on the work while the Director keeps the retained decisions — `docs/guide/operating-model.md:65`, `:89` and `:91`. Supervision sits with you and your AI assistants, outside the factory — `docs/superpowers/specs/2026-10-16-website-build-design.md:80`.

### Step 8 — Merged, and back to GitHub

Page copy:

> ### 8. Merged, and back to GitHub
>
> Once the required reviews and checks are complete, the work can be merged under your project's rules and returned to GitHub. In our example, the merged help note becomes part of the welcome page.
>
> **Your call:** you decide whether the results meet your goals, and when to publish.

Screenshot: Work. Seeded state: the merged item in the list, shown with the All filter. Caption and alt text:

> Work, with example data: a merged item shown with the All filter.

Evidence: human review and merge follow repository policy — `docs/guide/index.md:13`; human review and merge gates link to the proposed change, and passing checks alone do not prove review acceptance — `docs/features/agent-teams.md:207-214`. Work may merge into an integration branch before a later promotion — `docs/guide/supervised-factory-playbook.md:150-154`. The seeded merged item — `scripts/e2e/scenarios.py:225-226`; finished as a tracking state — `docs/features/work.md:5`. The All-filter capture instruction comes from the screenshot list in `docs/plans/2026-10-15-director-website/03-website-plan.md:176` (the steps 2, 5 and 8 Work row). Approving publication stays with the Director — `docs/guide/operating-model.md:91` and `:97`.

### Sent back a step

Page copy:

> Work does not always travel in a straight line. A review can send work back for changes. A question about the plan can send it back to planning. The team works within the limits you set.

Evidence: work is sometimes sent back a step (review to build, approval to plan) — `docs/superpowers/specs/2026-10-16-website-build-design.md:86`; work runs under chosen merge policy and finite budgets — `docs/autonomy.md:11`.

## 3. Several AI teams at once

Page copy:

> ## Several AI teams at once
>
> One feature, one team. With several features on the go, several AI teams work side by side — on different features, or different projects — each moving at its own pace. One Deck runs them all.

Placement note: plain text only; the inside scene above already shows several teams. No extra screenshot sits in this section.

Evidence: one AI team per feature, at its own pace — `docs/superpowers/specs/2026-10-16-website-build-design.md:46` and `:86`. Several teams in one Deck, across projects — `docs/features/repositories.md:3` and `docs/features/work.md:3`.

## 4. You and your AI assistants

Page copy:

> ## You and your AI assistants
>
> You run the factory from outside it. You own the features, prepare the team rosters in Deck — who is on each team, and which agent tools and models they use — and supervise the work as it flows.
>
> Your AI assistants can help with all of it, from drafting features to keeping watch. The decisions stay yours.

Placement note: plain text only; no scene or screenshot sits in this section.

Evidence: you own the features — `docs/guide/operating-model.md:53`. You prepare the rosters: the Director chooses the roster and how many builders and checkers each team has — `:30` and `:46`; each role carries your selection of AI harnesses and AI models — `docs/superpowers/specs/2026-10-16-website-build-design.md:85`. Supervision is yours, with AI assistants, from outside — `:80` and `:83`. An optional AI agent can draft features for the Director, who decides — `docs/guide/operating-model.md:59`.

## 5. Highlights: what makes Deck different

Page copy:

> ## Highlights: what makes Deck different
>
> **Many AI harnesses, your choice of models.** Deck works with six different AI harnesses — the agent tools your team members run. Every role in a team gets its own harness and its own model, so a team can mix model families.
>
> **Adversarial reviews.** The AI reviewer is a different agent from the one who built the work — another agent whose job is to challenge it. And because each role carries its own model choice, you can give the reviewer role a different model family from the builder's, for a second perspective on the same work.
>
> **Team communication.** Your AI team members talk to each other through Deck as they work — asking questions, sharing context, and handing work over. When a decision is yours, they can reach you the same way.
>
> **The production dashboard.** One overview keeps the whole factory in view: what needs you first, and how every team's work is going.

Placement note: this section carries no screenshot of its own. For "The production dashboard", reuse the step 2 Overview capture; do not build a second dashboard image.

Evidence: six harness cards — `docs/features/harnesses.md:3`. Each team slot stores its own provider, launch mode and provider options — `docs/features/agent-teams.md:39-50`; each role carries your selection of AI harnesses and AI models — `docs/superpowers/specs/2026-10-16-website-build-design.md:85`. Review is a separate role from building — `docs/guide/operating-model.md:18` and `:27`. Team communication through structured mailboxes for context requests, handoffs and replies — `docs/features/agent-mail.md:3`; "Deck — team communication, production dashboard" — `docs/superpowers/specs/2026-10-16-website-build-design.md:84`. "Needs you" and team summaries on Overview — `docs/plans/2026-10-15-director-website/01-audit.md:37`, with the counts at `docs/features/dashboard.md:7`. Builder note: the copy states that a different model family is a choice you can make for the reviewer role; it makes no claim about how many more problems any review finds.

## 6. Words on this page

Page copy:

> ## Words on this page
>
> - **Feature** — something you want built, with a clear result.
> - **AI team** — the AI agents working on your features.
> - **Agent owner** — the AI agent who plans and builds one feature.
> - **AI Leader** — the AI agent who approves the plans and checks the finished work.
> - **AI reviewer** — an AI agent who checks work they did not build.
> - **Harness** — the agent tool a team member runs.
> - **Factory** — Deck and your AI teams, working together.
> - **Merged** — finished work joined into the project's shared version on GitHub.

Evidence: each entry restates, in one plain sentence, a word the copy above uses, with the evidence already given for that word's claim.

## 7. Next

Page copy:

> ## Next
>
> See it in action on the Quick tour, or go deeper in Technical information.
>
> [Link] Quick tour
>
> [Link] Technical information

Placement note: the links go to `/quick-tour/` and `/technical-information/`.

## Footer

Page copy:

> Deck
>
> How it works · Quick tour · Technical information

Placement note: as on the home page. "Deck" links to `/`; the three links go to `/how-it-works/`, `/quick-tour/` and `/technical-information/`, in that order.

## Evidence notes (not shown on the page)

- Sources, in order of authority: the Director's decisions in `docs/superpowers/specs/2026-10-16-website-build-design.md` (`:70-86`), then the "Director decisions" and "Decisions after approval" sections of `docs/plans/2026-10-15-director-website/README.md` (`:50-74`), then `03-website-plan.md` and the story's "How it works" layer in `02-factory-story.md`. Where older text disagreed with a decision — who stands inside the factory, who checks at step 7, who merges — the decision was followed.
- The factory here is Deck and the AI teams, supervised from outside (`docs/superpowers/specs/2026-10-16-website-build-design.md:80`). `docs/guide/operating-model.md` still describes the factory the older way (`:38`, `:42-44`) until issue #775 updates it, so factory-boundary lines cite the decision; other facts cite the guide and feature docs at the lines shown.
- The harnesses are not named anywhere in the copy, as the issue requires; the docs name them. Evidence citations point at lines that support the claim without repeating those names here.
- The preview address is deliberately not linked or named anywhere in this file.

