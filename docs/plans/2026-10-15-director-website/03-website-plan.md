# Website plan for claudedeck.org

For: issue #757 under parent issue #745. This revision uses `01-audit.md` and the revised `02-factory-story.md` merged under issue #756.

Main action: **Understand and share it.** A director sees the graphical home page, understands the factory mostly through its animated pictures, and forwards one link, one page, or one short video. The detail lives on the second page, "How it works".

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
| 1 | Home | What is Deck, in one look? | Understand backlog, team, and finished work through the pictures. |
| 2 | How it works | How does one piece of work travel, and what do I see and decide? | Read the six steps, the screens, and the gates. |
| 3 | Share Deck | How do I brief my board or my team? | Forward the link, the one-page summary, or the video. |
| 4 | Limits and trust | What does Deck not promise? | Share with the limits stated, not hidden. |
| 5 | For operators | How does an operator set Deck up? | Hand the setup to a technical operator. |

The home page carries the whole idea in pictures and a few short lines. "How it works" carries the depth. No director page starts with install steps.

Evidence: `01-audit.md` finds install steps and developer words on the first screen today. The revised story in `02-factory-story.md` puts the three-part top level first and marks the six-step layer for a second page.

## Page structure

### Home

Purpose: a director understands and can share Deck after one graphical page.

Sections, in order: first screen (the story sentence and the backlog → team → finished work flow), the idea in pictures (four animated illustrations), six words, Share Deck, Limits and trust, For operators. Text stays at a few short lines. The pictures carry the story.

### How it works

Purpose: the second page, for readers who want the detail.

The page follows one piece of work through the six steps from the revised story. Each step gives its copy, what the director sees on the named screens with their seeded states, and the decision that stays with the Director. The page ends with the nine detail words and the limits. The home page links here, and this page links back home.

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

The mockup at `mockup/index.html` uses this copy. The copy is the top level of the revised story. It uses the story sentence and the six top-level words, and no developer words. The #756 word check runs on this copy (see "The mockup" below).

### First screen

Heading: **Your backlog. Your AI team. Finished work.**

One line: You shape the feature backlog, Deck's AI team builds and checks the work, and the key decisions stay with you.

Button: **See how it works** — it links to the second page.

Under it, one flow in three boxes: **Backlog** (the features you want, in your order) → **AI team** (a Leader, members, and reviewers) → **Finished work** (checked work, with its record).

Evidence: the line is the revised story's one sentence. The three boxes are its three parts. `02-factory-story.md` gives each claim its evidence.

### The idea in pictures

Four animated illustrations carry the story. Each one is self-contained: one idea, inline SVG and CSS, no Deck screenshots, no screen labels, no product UI. That keeps each one reusable as a video scene. Each one has a still version: under `prefers-reduced-motion`, the animation stops and the finished state of the picture stays on screen, with the same caption.

1. **Backlog — you shape the list.** The viewer sees three feature cards settling into an ordered list, first to third. Motion: each card lifts slightly and settles back, in turn. Loop: 6 seconds, calm. Idea it teaches: the backlog is yours, ordered by you. Still version: the three cards at rest in order.
2. **AI team — clear roles.** The viewer sees a Leader, members, and a reviewer, with one card of work passing from building to checking. Motion: each role lights in turn while the work card moves across. Loop: 8 seconds. Idea it teaches: the Leader organises and approves plans, members build, reviewers check work they did not build. Still version: all roles lit, work card in place.
3. **Finished work — work comes back to you.** The viewer sees checked work beside its record, with one record line drawn dashed. Motion: the check mark and the record lines appear in turn. Loop: 7 seconds. Idea it teaches: work returns for you to assess, and gaps in the record are shown, not hidden. Still version: checked work and the full record, gap line included.
4. **People in charge deciding — the key decisions stay yours.** The viewer sees a dot of work travel, pause at a gate marked "You decide", and pass only when the gate opens. Motion: travel, a clear pause, then the gate lifts. Loop: 8 seconds. Idea it teaches: goals, priorities, budget, and publication stay with the Director. Still version: the dot at rest before the upright gate — work waiting for the decision.

Evidence: each caption restates one accepted claim from the revised story's three parts and "Why it matters", with its limits kept (record gaps shown; decisions reserved). No picture shows a screen, a time saving, or a cost.

### Six words carry the story

Backlog, Team, Leader, Member, Reviewer, Director — with the one-line definitions from the revised story, unchanged.

Evidence: `02-factory-story.md` defines the six top-level words. The nine detail words sit on "How it works", not here.

### Share Deck, Limits and trust, For operators (home sections)

Share Deck: Send this page. It is the brief. When you want the detail, read "How it works".

Limits and trust: Deck does not measure the full cost of a finished feature, and no trial has measured the time it saves you. A person still sets the goals and decides what gets published. Costs and records are shown with their limits.

For operators: Setup and day-to-day running live in the operator guides, not on this page.

Footer retell: "We choose and order the features we want. Our AI team works through them. We follow progress, and the decisions stay with us." This is a shortened form of the revised story's retell, with the same facts.

Evidence: the limits lines restate "Why it matters" (cost) and "What the story does not promise" in the revised story. Deck can show estimates for Claude Code sessions when their data is available (`docs/features/usage.md`). Factory delivery cost and director-time savings are not measured (`docs/guide/factory-audit-and-metrics.md:57`, `:96-97`).

## The "How it works" page

The mockup at `mockup/how-it-works.html` carries this page. It follows one example from a GitHub issue to a merged PR: "Add a short help note to the welcome page." The example is not a measured delivery.

Sections, in order: the six steps (each with copy, what you see, and your decision), words for this page (the nine detail words), and what this page does not promise.

| Step | Copy in one line | Screen and seeded state it shows | Decision that stays with the Director |
|---|---|---|---|
| 1. The Director writes the issue | Write a clear result, order the backlog, mark it ready. | GitHub issue in backlog order. Deck does not replace GitHub. | Goal, order, ready mark. |
| 2. The owner proposes. The Leader approves. | Building starts only after the designated Leader approves the owner's plan. | Overview ("Needs you", progress), Work (owner, waiting reason), Teams (roster, named Leader). Seeded states: see the screenshot list. | Outcome and limits. The Leader approves plans inside them. |
| 3. A member does the work | The member builds in a separate working copy and opens a PR. | Work (owner, state, PR link), Repositories (which backlog feeds the team). | None, unless a decision only the Director can make, or a safety stop, applies. |
| 4. Reviewers check the work | An independent reviewer reads the exact version. Fixes stay on the same PR. CI runs again. | Work (waiting for review, with its PR field), Audit (delivery measures with limits). | Review follows repository policy. Passing review and CI give no merge power alone. |
| 5. The Supervisor watches and helps | Optional. It fixes routine blockers inside its delegation and explains retained decisions with evidence. | Overview Supervisor state (Healthy, Late, or Absent) when one is registered. | Grant or withdraw delegation. Publication, budgets, models, security HOLD. |
| 6. The PR merges. The record stays. | The PR merges under repository policy. The issue closes. | Work (finished; use the All filter), Audit (history with limits; event list locked). | Accept the result. Decide publication. |

Evidence: Steps 1 to 6, their screens, and their gates come from the "How it works" layer of the revised story. The seeded states come from the screenshot list below, which records the audit evidence and the seed.

## Headings and key sentences for the other pages

### How it works

Heading: **How it works: one piece of work, step by step.**

Key sentence: The owner proposes the plan, the Leader approves it, and you keep the decisions that matter.

The page then gives the six steps. Each step names what you see on the screens and the decision that stays yours. The mockup page carries this copy in full.

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

Each request names the real Deck screen and the seeded state to capture. Capture new images from the tested source. Do not reuse the old site images. The graphical home page needs no screenshot: its four animated illustrations carry the story, and they hold no screen detail. Screenshots belong to "How it works", Share Deck, Limits and trust, and For operators.

The old images freeze older versions. Evidence: `01-audit.md` records the two main images at version 3.0.0 and six feature previews with a v2.0.0 footer. The tested source reports version 3.1.0.

Seed evidence: the test seed holds five different issues, one per work state. Evidence: `scripts/e2e/scenarios.py` seeds issues #101 to #105 in the attention, review, active, finished, and queued states. No single seeded issue moves through all states. The clip below therefore narrates static states. It does not show one issue in motion.

| Section | Screen to capture | Seeded state to show | What the director learns | Limit to print with the image |
|---|---|---|---|---|
| Home, the idea in pictures | No screenshot. Four animated illustrations (inline SVG and CSS). | No seeded state. No screen detail in any illustration. | Backlog, team, finished work, and retained decisions, mostly through the pictures | Each illustration is a concept picture, not a product screen. Its still version serves reduced motion. |
| How it works, Step 2 | Overview and Teams | Overview seeded counts with one item in each state: queued, active, review, attention, finished. Teams seeded team "Release crew" with a named Leader and its member slots. | Work waits in named states, and a team is a roster with one Leader | Seeded example data. Not live records. Seeded roster, not a live team. |
| How it works, Steps 3 and 6 | Work | Five seeded work items, one item per state, shown with the All filter. Four items name an owner. The queued item, #105 "Add keyboard shortcuts", has no owner yet. | Each state exists at once, and the queued item still waits for an owner | Seeded example data. The default Work filter hides finished work, so the capture names the All filter. The path is an example, not a measured delivery. |
| How it works, Step 2 | Overview | The "Needs you" area with campaign progress and team summaries | The screen puts the director decision first | Browser observation from the audit. Counts alone do not prove the summaries. |
| How it works, Step 3 | Repositories | Three seeded repository scopes, with paused intake on two scopes | A backlog feeds a team only when intake allows it | Seeded scopes. Paused intake shows no live polling. |
| How it works, Step 4 | Work | One seeded item that waits for review, with its pull request field | A gate stops work until a reviewer acts | Review follows repository policy. This image shows one example policy. |
| Agent tools, on For operators | Harnesses | Six seeded harness providers with setup and support labels | Deck shows the setup and support for each agent tool | This capture supports agent-tool setup only. It supports no cost claim. Account, model, and session readiness stay unknown without a separate check. |
| Limits and trust | Audit | Safe delivery metrics with the event list locked | The ledger shows metrics, and events stay behind an access gate | Locked events are an access gate, not a load failure. No event rows shown. |
| Limits and trust | Agent Mail | No public capture. The only observed state stayed at participant loading. | No director claim rests on this screen yet | Keep this state in the evidence limits. Add a public capture only when a supported coordination state exists. The limit proves no Mail failure and no docs defect. |
| Share it | Overview, Work, and Audit, as a clip | The seeded stills for the normal path in story order: queued, active, review, finished. One separate attention still. One closing Audit still with safe metrics and events locked. Each state shows a different seeded issue. | The director sees the normal path, the exception that needs a person, and the ledger screen that closes the story | Narrated example over static states. No single seeded issue moves through all states. The Audit still shows no event record for these issues. Not a measured delivery time. |

Short clips: the video itself is planned under issue #758. This plan supplies its reusable scenes: the four screen-free home illustrations, each one idea, ready to rebuild as video scenes. The seeded screen stills above stay available for a short closing segment only. Any state sequence still carries its limit: each state shows a different seeded issue, and no single seeded issue moves through all states. Evidence: `backend/app/services/factory_projection_service.py` maps attention to escalated or failed work, and the seed gives issue #101 an owner idle timeout.

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

Keep on the home page: the story sentence, the four pictures, the six words, the share line, and the limits. Screens in director words live on "How it works".

## How a director shares Deck

Three ways. Each way stands alone.

1. **A link.** The director sends the home page link. The first screen carries the one sentence, the three-part flow, and the link to the detail. The peer needs no setup and no account to read it.
2. **A one-page summary.** The director sends one page with the one sentence, the three parts, what the director decides, and the limits. The summary prints cleanly and forwards as a document.
3. **The video.** The director shows the short video planned under issue #758. It tells the same three-part story, reuses the home pictures as scenes, and keeps any screen shots to a short, replaceable closing segment.

Evidence: `01-audit.md` finds only Docs and GitHub links today, and no forwardable brief. The three items above close that gap. Each item uses only claims from `02-factory-story.md`.

Share limits: the summary and the video use seeded example data. Each one says so. Neither one claims a measured saving or a measured delivery time.

## The mockup

The mockup has two pages. `mockup/index.html` shows the graphical home page with the four animated illustrations built in. `mockup/how-it-works.html` shows the second page with the six steps. The home page links to the second page, and the second page links back.

Each page is one self-contained HTML file. Each uses inline CSS and inline SVG only. Neither makes an external request. Neither holds a script. Under `prefers-reduced-motion`, every animation stops and each illustration shows its still version.

A critic opens both pages in a browser, on desktop and mobile widths and with reduced motion on, and confirms: the home page tells backlog → team → finished work mostly through the graphics, and the detail lives on "How it works".

Both mockup pages are plan artifacts. They are never deployed. No step in this plan copies them to the website repository.

Checks, with commands. The build notes record each command and its result.

- External requests: `grep -En 'https?://|url\(|@import|<link|src=|fetch\(|XMLHttpRequest|<script|<iframe|srcset|action='` on both files. Require no matches, except two exempt forms only: the exact SVG namespace string, and `url(` followed by `#`. List every exempt match in the build notes.
- Reduced motion: `grep -n 'prefers-reduced-motion'` in both files. Each illustration must have its still state in that block.
- Link: `grep -n 'how-it-works.html'` in `mockup/index.html`, then serve the mockup folder locally and require HTTP 200 for both pages.
- Home word check: extract the home page visible copy and run `grep -Eio 'github|\bprs?\b|pull requests?|\bissues?\b|\bci\b|\bmerg[a-z]*|\bbranch[a-z]*|\blabel[a-z]*'`. It must print nothing.

## What this plan does not promise

This plan does not promise a published site. Publication stays a Director decision under the parent issue.

This plan does not promise that seeded screens prove live value. Each capture carries its seeded-data limit.

This plan does not promise a human verdict. A critic reads the mockup as a director. No human director trial has run.

This plan keeps factory delivery cost unknown and claims no time saving. Evidence: `docs/guide/factory-audit-and-metrics.md` and `02-factory-story.md`.

