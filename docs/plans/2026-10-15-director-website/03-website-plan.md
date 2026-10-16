# Website plan for claudedeck.org

For: issue #768 under parent issue #745. This revision uses `01-audit.md`, the revised `02-factory-story.md`, and `04-docs-and-video.md` on master.

Main action: **Understand and share it.** A director sees the graphical home page, understands the factory mostly through its animated pictures, and forwards one link, one page, or one short video. The detail lives on the second page, "How it works".

This plan names evidence for each claim. A claim with no evidence does not enter the copy.

## Sources

- `01-audit.md` records the current site, the docs, and the product screens.
- `02-factory-story.md` gives the one sentence, the one paragraph, the roles, and the glossary.
- `docs/guide/operating-model.md` defines the factory, the Director, the Leader, and the retained decisions. It is the source of truth for the two big figures below. Their static originals are `docs/public/images/operating-model/hierarchy.svg` and `docs/public/images/operating-model/factory.svg`.
- Naming, per the Director: the product is called Deck. The tools team members run are called agent tools.
- The website reference is a separate repository. This plan cites it as `website-ref` at commit `0c35f391759633c774b7cc4ace5c52b96dd53d12`. This plan does not change it.
- An isolated test instance supplied fresh screen states for this plan. The states are seeded example data. They are not live records and not human trials.

## The reading order for a director

A director reads in this order. Each page answers one question.

| Order | Page | Question the page answers | Director purpose |
|---|---|---|---|
| 1 | Home | What is Deck, in one look? | Understand backlog, team, and finished work through the pictures. |
| 2 | How it works | How does the backlog travel through the team, and what do I see and decide? | Read the eight steps, the screens, and the gates. |
| 3 | Share Deck | How do I brief my board or my team? | Forward the link, the one-page summary, or the video. |
| 4 | For operators | How does an operator set Deck up? | Hand the setup to a technical operator. |

The home page carries the whole idea in pictures and a few short lines. "How it works" carries the depth. No director page starts with install steps.

Evidence: `01-audit.md` finds install steps and developer words on the first screen today. The revised story in `02-factory-story.md` puts the three-part top level first and marks the eight-step layer for a second page.

## Page structure

### Home

Purpose: a director understands and can share Deck after one graphical page.

Sections, in order: first screen (the story sentence and the main action), the idea in pictures (five animated illustrations in the opening flow), who does what (the animated hierarchy of roles), what the factory is (the animated factory figure), Share Deck, For operators. Text stays at a few short lines. The pictures carry the story. The six words, the retell, and the operator paragraph live on "How it works".

### How it works

Purpose: the second page, for readers who want the detail.

The page follows the backlog through the team in the Director's eight steps from the revised story. Each step gives its copy, what the director sees on the named screens with their seeded states, and the decision that stays with the Director. A short section then covers parallel tracks and several teams. The page ends with the glossaries and the retell. The home page links here, and this page links back home.

### Share Deck

Purpose: the share kit on one page.

The page holds the share link text, the one-page summary, and the short video. Each item stands alone. A peer needs no other page first.

### For operators

Purpose: setup and depth for a technical operator.

This page links to the docs. It holds install steps, harness setup, and autonomy setup. It keeps those topics off the director pages.

Evidence for the structure: `01-audit.md` ranks the missing director decision map and the missing share artefact in its top problems. `02-factory-story.md` supplies the story order.

## Draft copy for the home page

The mockup at `mockup/index.html` uses this copy. The copy is the top level of the revised story. It uses the story sentence and the six top-level words, and no developer words. The #756 word check runs on this copy (see "The mockup" below).

### First screen

Heading: **Your backlog. Your AI team. Finished work.**

One line: You shape the feature backlog, Deck's AI team builds and checks the work, and the key decisions stay with you.

Main button: **Understand and share it** — it links to the sharing section, as the parent issue requires. Secondary link: **How it works** — it links to the second page.

The five illustrations follow at once, in the opening flow. There is no text-only flow above them, so the first picture sits on the first screen, on mobile too.

Evidence: the line is the revised story's one sentence. `02-factory-story.md` gives each claim its evidence. The parent issue #745 names "Understand and share it" as the main action.

### The idea in pictures

Five animated illustrations carry the story. Each one is self-contained: one idea, inline SVG and CSS, no Deck screenshots, no screen labels, no product UI. That keeps each one reusable as a video scene. Each one has a still version: under `prefers-reduced-motion`, the animation stops and the finished state of the picture stays on screen, with the same caption.

1. **Backlog — you shape the list.** The viewer sees three feature cards settling into an ordered list, first to third. Motion: each card lifts slightly and settles back, in turn. Loop: 6 seconds, calm. Idea it teaches: the backlog is yours, ordered by you. Still version: the three cards at rest in order.
2. **AI team — parallel tracks.** The viewer sees three lanes under one AI Leader, with a work card travelling down each lane toward its own AI reviewer. Motion: the three cards travel in turn, slightly offset, so several items are clearly moving at once. Loop: 7 seconds. Idea it teaches: several owners and reviewers can work parallel tracks of the backlog at the same time, coordinated by the Leader. Still version: the three cards rest part-way down their lanes. Evidence for "at the same time": `docs/guide/operating-model.md:30` (Director chooses implementer and verifier counts; concurrent-dispatch limits) and `docs/guide/supervised-factory-playbook.md:193` (one workspace per concurrent item). The concurrency-1 starting setting is stated on "How it works", not in this short home copy.
3. **Finished work — work comes back to you.** The viewer sees checked work beside its record, with one record line drawn dashed. Motion: the check mark and the record lines appear in turn. Loop: 7 seconds. Idea it teaches: work returns for you to assess, and gaps in the record are shown, not hidden. Still version: checked work and the full record, gap line included.
4. **People in charge deciding — the key decisions stay yours.** The viewer sees a dot of work travel, pause at a gate marked "You decide", and pass only when the gate opens. Motion: travel, a clear pause, then the gate lifts. Loop: 8 seconds. Idea it teaches: goals, priorities, budget, and publication stay with the Director. Still version: the dot rests beside the closed gate, with the caption "Work waits here for your decision", so the still itself teaches the decision idea.

5. **Several teams — one Deck, many projects.** The viewer sees three small team groups side by side, each with its own short backlog list and one moving work card. Motion: the cards nudge forward in turn, calmly. Loop: 6 seconds. Idea it teaches: one Deck can run several teams in parallel, each on a different project's backlog. Still version: the three teams at rest with their lists. Evidence: `docs/features/repositories.md:3` (scopes across teams), `docs/features/work.md:3` (mixed-team work), `docs/guide/supervised-factory-playbook.md:37` (one actor can supervise several teams). The test seed in `scripts/e2e/scenarios.py` holds several saved teams in one Deck; its quiet team is idle, so it shows several teams existing, not all running.

Evidence: each caption restates one accepted claim from the revised story, with its limits kept (record gaps shown; decisions reserved; concurrency setting on the second page). No picture shows a screen, a time saving, or a cost.

### Captions

One short caption per picture: "Choose what matters." / "Your AI team builds and checks it — several items at once." / "Review the result and its record." / "You decide what gets published." / "One Deck can run several teams, each on its own project." The full glossary (the six top-level words and the nine detail words) and the retell sit on "How it works", so the home text stays at a few short lines.

Evidence: `02-factory-story.md` defines both word sets and gives the retell.

### The two big figures

After the five pictures, two large animated figures carry the two ideas a director most needs: who is who, and what the factory is. They join the home page; they replace nothing, and the first screen stays as above. Each figure is animated SVG built in code, in line with "Technology and build" below, and each is also a shared React scene the video reuses (see `04-docs-and-video.md`). Each builds once, as it scrolls into view. Under reduced motion, each shows its finished still version with the same caption.

Three kinds of thing must read at a glance, each in its own visual language, with a small key above the first figure: a person (amber, a person icon), an AI team member (violet, an agent icon; optional helpers dashed and marked optional), and a computer system (slate, a gear icon). The figures keep the role names — Director, Supervisor, grooming helper, Leader, Implementers, Verifiers, Deck controller — each with one short plain description. The kind of each role is clear at first sight: the Director is you, the human; the Leader, Implementers, Verifiers and grooming helper are AI agents; the Supervisor box states that the role can be an AI agent or a person; the Deck controller and where the work lives are computer systems, not people or agents. On the home page, the system that holds the backlog, the work and the record carries a plain label, "Where your work lives"; that system is GitHub (`docs/guide/operating-model.md:19`, `:31`, `:47`). No field name or internal term from the static originals enters the copy: each is translated into plain words (for example, the campaign link, the next promised check, checking the exact finished version).

6. **Who does what — the hierarchy of roles.** What the viewer sees: the Director at the top; the grooming helper and the Supervisor beside the Director, dashed and marked as optional help; the Leader below on the line of command; Implementers ×N and Verifiers ×N under the Leader; and, below a divider marked "Not ranks — computer systems", the Deck controller and where the work lives. Motion: the Director appears first, the optional helpers fade in, the line of command draws down to the Leader, then splits to the two stacks, which fan out to show several members; the systems settle last, below the divider. Timing: about 4 seconds, once, on scroll into view; no loop. One idea it teaches: one person in charge, a clear chain below that person, and systems that follow rules — they are not bosses. Still version: the complete chart, stacks fanned. Meaning and evidence: the line of command and the optional staff roles are `docs/guide/operating-model.md:27-28`; the Supervisor acts only within the Director's recorded limits and does not take the Leader's plan authority (`:29`); the Director chooses how many implementers and verifiers there are (`:30`); the controller and the work-keeping system are not ranks (`:31`); the grooming helper drafts backlog items and the Director decides (`:59`).

7. **What the factory is — the factory figure.** What the viewer sees: a boundary labelled "The factory". Inside it: the Supervisor, the Deck controller, and the team (Leader, Implementers ×N, Verifiers ×N). Outside it: the Director and the grooming helper above, and where the work lives below. Motion: the boundary draws in; the inside parts appear; work dots travel through the team; a dot flows up as ready work in and down as finished work back; the Supervisor's check-in dot pulses gently. Timing: about 5 seconds to build on scroll into view, then only the flowing dots and the gentle pulse continue. One idea it teaches: the factory is the Supervisor, the Deck controller and the team working your backlog together, while you and your list stay outside it. Still version: the closed boundary with all parts in place and one dot on each flow. Meaning and evidence: the factory is the supervisor, the controller and the team working on the Director's backlog (`docs/guide/operating-model.md:38`); who sits inside and outside, and why, is the table at `:42-49`; the team works the backlog and returns finished work, the controller keeps the team inside its rules, and the Supervisor checks in (`:65`, `:88-90`, `:98-99`).

Prototype note: drawing the lines and the boundary in the mockup animates stroke properties. The mockup is a prototype; it may show that effect, but it does not resolve the open animation constraint in `README.md` (question 7), and this plan grants no exception.

### Share Deck and For operators (home sections)

Share Deck: Send this page to someone you want to build with. When you want the detail, read "How it works".


For operators: Setup lives in the operator guides. Start from "How it works".

Evidence: cost uncertainty is no longer a home section, but no home claim needs it: no home line states a cost or a saving. The cost limit itself stays true and stated where cost appears — the story's "Why it matters" (`02-factory-story.md`) and the video plan (`04-docs-and-video.md`).

## The "How it works" page

The mockup at `mockup/how-it-works.html` carries this page. Its intro reads: "Follow your backlog through the team, in eight steps." One example item runs through it: "Add a short help note to the welcome page", from a GitHub issue to a merged PR. The page also carries parallel tracks and several teams, the six top-level words, the retell, and a short For operators note.

Sections, in order: the eight steps (each with copy, what you see, and your decision), parallel tracks and several teams, the six top-level words with the retell, the For operators note, and words for this page (the nine detail words).

| Step | Copy in one line | Screen and seeded state it shows | Decision that stays with the Director |
|---|---|---|---|
| 1. The Director writes the backlog and marks it ready | Choose the result, set its priority, decide when it is ready. | Written example only. No GitHub capture: GitHub is not a Deck screen. | Goals, order, ready decision. |
| 2. The team works autonomously | The team works through ready items without you steering each step. It follows your goals and limits, respects safety stops, and uses the plan approvals and reviews below. | Overview ("Needs you", progress), Work (each item's progress and owner). | Hold or pause. Change the limits. |
| 3. Agent owner writes the plan | Each item is assigned to an agent owner, who writes a short plan. | Work (owner per item), Teams (roster, named Leader). | Outcome and limits, not each plan. |
| 4. Leader reviews and approves | Building starts only after the AI Leader approves the agent owner's plan. | Overview (campaign progress, team summaries). | None at this gate. |
| 5. Agent owner works | Builds in a separate working copy, checks own work, runs agreed checks, opens a PR. | Work (owner, state, PR link), Repositories (which backlog feeds the team). | None, unless a Director-only decision or safety stop applies. |
| 6. Reviewer checks | An AI reviewer who did not build it reviews the exact version. Fixes stay on the same PR. CI runs again. | Work (waiting for review, PR field), Audit (measures with limits; event list locked). | If your rules call for your review, decide readiness. Passing checks authorize no merge. |
| 7. Leader and Supervisor check | Leader checks against the approved plan. Supervisor also checks, when one is assigned (optional role; an AI agent or a person). | Overview Supervisor state (seeded Healthy, from `01-audit.md` roster record), only when registered. | Choose what the Supervisor may do. Publication, budgets, models, safety stops. |
| 8. The work is merged | Merges under repository policy. In this example the Supervisor merges. The item closes. | Work (finished; All filter), Audit (history with limits; events locked). | Accept the result. Decide publication. |

After the steps: **Parallel tracks** — several owners and reviewers can work at the same time, coordinated by the Leader, each track in its own workspace. Plain limit: a new backlog link starts at one item at a time; parallel tracks need a higher setting, and that setting is the Director's choice. **Several teams** — one Deck can run several teams in parallel, each on a different project's backlog.

Evidence: Steps 1 to 8, parallel tracks, several teams, their screens, and their gates come from the "How it works" layer of the revised story, with the concurrency evidence cited there (`docs/guide/operating-model.md:30`, `docs/guide/supervised-factory-playbook.md:193`, `docs/features/repositories.md:22`). The seeded states come from the screenshot list below, which records the audit evidence and the seed.

## Headings and key sentences for the other pages

### How it works

Heading: **How it works: your backlog, through the team.**

Key sentence: Each item gets an agent owner who writes the plan, the Leader approves it, and you keep the decisions that matter.

The page then gives the eight steps, parallel tracks, and several teams. Each step names what you see on the screens and the decision that stays yours. The mockup page carries this copy in full.

### Share Deck

Heading: **Brief your board in one page.**

Key sentence: Send the link, send the one-page summary, or show the short video. Each one stands alone.

### For operators

Heading: **Set up Deck on your machine.**

Key sentence: An operator installs Deck, connects the agent tools, and turns on team automation under policy.

This page links to the quick start and the autonomy guide. It holds no director copy.

Evidence: the headings use the story terms. The operator key sentence matches the audience line in `01-audit.md`: the product today speaks to technical operators first. This plan gives directors their own pages and keeps operator depth here.

## Screenshots and short clips each section needs

Each request names the real Deck screen and the seeded state to capture. Capture new images from the tested source. Do not reuse the old site images. The graphical home page needs no screenshot: its five animated illustrations and two big figures carry the story, and they hold no screen detail. Screenshots belong to "How it works", Share Deck, and For operators.

The old images freeze older versions. Evidence: `01-audit.md` records the two main images at version 3.0.0 and six feature previews with a v2.0.0 footer. The tested source reports version 3.1.0.

Seed evidence: the test seed holds five different issues, one per work state. Evidence: `scripts/e2e/scenarios.py` seeds issues #101 to #105 in the attention, review, active, finished, and queued states. No single seeded issue moves through all states. The clip below therefore narrates static states. It does not show one issue in motion.

| Section | Screen to capture | Seeded state to show | What the director learns | Limit to print with the image |
|---|---|---|---|---|
| Home, the idea in pictures, who does what, and what the factory is | No screenshot. Five animated illustrations and two big animated figures (inline SVG and CSS). | No seeded state. No screen detail in any illustration. | Backlog, team, finished work, and retained decisions, mostly through the pictures | Each illustration is a concept picture, not a product screen. Its still version serves reduced motion. |
| How it works, Steps 2 and 3 | Overview and Teams | Overview seeded counts with one item in each state: queued, active, review, attention, finished. Teams seeded team "Release crew" with a named Leader and its member slots. | Work waits in named states, and a team is a roster with one Leader | Seeded example data. Not live records. Seeded roster, not a live team. |
| How it works, Steps 2, 5 and 8 | Work | Five seeded work items, one item per state, shown with the All filter. Four items name an owner. The queued item, #105 "Add keyboard shortcuts", has no owner yet. | Each state exists at once, and the queued item still waits for an owner | Seeded example data. The default Work filter hides finished work, so the capture names the All filter. The path is an example, not a measured delivery. |
| How it works, Step 2 | Overview | The "Needs you" area with campaign progress and team summaries | The screen puts the director decision first | Browser observation from the audit. Counts alone do not prove the summaries. |
| How it works, Step 5 | Repositories | Three seeded repository scopes, with paused intake on two scopes | A backlog feeds a team only when intake allows it | Seeded scopes. Paused intake shows no live polling. |
| How it works, Step 6 | Work | One seeded item that waits for review, with its pull request field | A gate stops work until a reviewer acts | Review follows repository policy. This image shows one example policy. |
| Agent tools, on For operators | Harnesses | Six seeded harness providers with setup and support labels | Deck shows the setup and support for each agent tool | This capture supports agent-tool setup only. It supports no cost claim. Account, model, and session readiness stay unknown without a separate check. |
| How it works, Steps 6 and 8 | Audit | Safe delivery metrics with the event list locked | The ledger shows metrics, and events stay behind an access gate | Locked events are an access gate, not a load failure. No event rows shown. |
| How it works, Step 6 | Agent Mail | No public capture. The only observed state stayed at participant loading. | No director claim rests on this screen yet | Keep this state in the evidence limits. Add a public capture only when a supported coordination state exists. The limit proves no Mail failure and no docs defect. |
| Share it | Overview, Work, and Audit, as a clip | The seeded stills for the normal path in story order: queued, active, review, finished. One separate attention still. One closing Audit still with safe metrics and events locked. Each state shows a different seeded issue. | The director sees the normal path, the exception that needs a person, and the ledger screen that closes the story | Narrated example over static states. No single seeded issue moves through all states. The Audit still shows no event record for these issues. Not a measured delivery time. |

Short clips: the video itself is planned under issue #758. This plan supplies its reusable scenes: the five screen-free home illustrations and the two big figures, each one idea, ready to rebuild as video scenes. The seeded screen stills above stay available for a short closing segment only. Any state sequence still carries its limit: each state shows a different seeded issue, and no single seeded issue moves through all states. Evidence: `backend/app/services/factory_projection_service.py` maps attention to escalated or failed work, and the seed gives issue #101 an owner idle timeout.

Still open: Usage cost. No image in this plan shows a cost total as proof. Evidence: `01-audit.md` records the old Usage image with zero totals, and `docs/guide/factory-audit-and-metrics.md` keeps factory cost unknown. The cost copy above states the limit in words instead.

## What to remove or move to the docs

Remove from the home page:

- The install steps and the shell commands. Move them to For operators and the quick start. Evidence: `01-audit.md` finds `git clone` and script commands on the landing page.
- The tech list. Move it to the architecture docs. Evidence: `01-audit.md` lists the stack names on the landing page.
- The old screenshots at two older versions. Replace them with the captures above. Evidence: `01-audit.md` contradiction 2.
- The five-harness claim. The product has six harnesses. Evidence: `01-audit.md` contradiction 1, from the providers response and `docs/index.md`.
- Feature cards in operator words. Rewrite each card as one director sentence, or move the card to the feature docs. Evidence: `01-audit.md` finds operator words in the cards.

Move to the docs, and link from "How it works" and For operators:

- Autonomy host setup and token steps. Evidence: `01-audit.md` finds host setup in `docs/autonomy.md`.
- Harness readiness detail and per-tool setup. Explain agent-tool setup on For operators.
- Audit event access detail. Explain access to Audit events on How it works, with a link to the operator guide.

Keep on the home page: the story sentence, five pictures with short captions, the two big figures, the share line, and the For operators link. The glossary, the retell, the operator paragraph, and screens in director words live on "How it works".

## How a director shares Deck

Three ways. Each way stands alone.

1. **A link.** The director sends the home page link. The first screen carries the one sentence, the three-part flow, and the link to the detail. The peer needs no setup and no account to read it.
2. **A one-page summary.** The director sends one page with the one sentence, the three parts, what the director decides, and the limits. The summary prints cleanly and forwards as a document.
3. **The video.** The director shows the short video planned under issue #758. It tells the same three-part story, reuses the home pictures and the two big figures as scenes, and keeps any screen shots to a short, replaceable closing segment.

Evidence: `01-audit.md` finds only Docs and GitHub links today, and no forwardable brief. The three items above close that gap. Each item uses only claims from `02-factory-story.md`.

Share limits: the summary and the video use seeded example data. Each one says so. Neither one claims a measured saving or a measured delivery time.

## Technology and build

Planning only: nothing is built under this plan. Every tool below is the Director's choice, made on 2026-10-15 and recorded in issue #765. This section records the choices. It makes no claim about any tool's licence terms, price, or performance; licence checks stay named Director checks before production spending.

- **Framework: Astro.** The Director chose Astro for static pages with zero JavaScript by default. Only the animated sections load code, as islands. Astro builds to `dist/`, and only `dist/` is deployed.
- **Deploy change.** The `dist/` deploy replaces today's whole-root deploy. Evidence for today: the website reference (`website-ref` at commit `0c35f391759633c774b7cc4ace5c52b96dd53d12`) runs `pages deploy .` in `.github/workflows/deploy.yml:21`, which publishes the whole repository root.
- **Draft website: Cloudflare Pages previews.** Each branch gets a Cloudflare Pages preview URL. The Director reviews a production-like draft there before production publication. Publication stays a Director decision.
- **Motion: GSAP.** ScrollTrigger drives scroll-driven storytelling, so the reader's scroll drives the story. DrawSVG, MorphSVG, and SplitText handle line drawing, shape change, and text motion.
- **Graphics: animated SVG built in code.** The Director chose code-built SVG over editor-made Rive or Lottie files, so the team can write and change the graphics exactly.
- **Supporting tools.** Lenis for smooth scrolling. The View Transitions API for page-to-page transitions. An optional, light WebGL backdrop (Three.js) in the hero only — kept only if it stays fast against the targets below; it is not promised.
- **One component library.** Each scene is a React component. Astro shows the same component on the site, and Remotion renders the same component in the video (see `04-docs-and-video.md`, Production approach). One scene, two outputs.
- **Standards, stated as targets.** A still version of every scene for reduced motion. A target of 60 fps, using transform and opacity only. No layout shift as a build rule. A Lighthouse target above 95. Animations start when their section is visible. These are targets for the build, not measured results.

Unresolved constraint, for the Director to decide before the build uses those effects: The Director selected DrawSVG and MorphSVG and also specified transform-and-opacity-only animation. Drawing and morphing change other SVG properties. The implementation plan must reconcile these requirements before using those effects; this plan grants no exception. Evidence for what the plugins animate: [DrawSVGPlugin](https://gsap.com/docs/v3/Plugins/DrawSVGPlugin/) and [MorphSVGPlugin](https://gsap.com/docs/v3/Plugins/MorphSVGPlugin/).

### Animation storyboard (website)

The scroll story, matched to the story's eight steps, the five home pictures, and the two big figures. Each part names its still version for reduced motion.

1. **Hero, "your backlog".** Feature cards drop into a priority stack. A "ready" mark lands, and the cards flow toward the team. Steps 1–2; the backlog picture. Still: the ordered stack with the ready mark.
2. **The team at work (scroll).** Cards split into parallel lanes. In each lane: an owner drafts a plan, the Leader approves it, the owner builds, a reviewer checks, the Leader and the Supervisor (when assigned) check, and the item lands on a "finished" shelf. Several lanes move at once. Steps 3–8; the parallel-lanes and finished-work pictures. Still: cards part-way down their lanes, one item on the finished shelf.
3. **Zoom out, many teams.** The view pulls back. This team becomes one of several teams in one Deck, each with its own project backlog. The several-teams picture. Still: the three team groups at rest.
4. **You decide.** The Director's moments — marking work ready, and publishing — light up along the way. The decision picture. Still: work resting beside the closed decision gate.
5. **Who does what.** The hierarchy figure builds from the Director down the line of command, the stacks fan out, and the systems settle below their divider (full storyboard under "The two big figures" above). Still: the complete chart.
6. **What the factory is.** The boundary draws in around the Supervisor, the Deck controller and the team; work flows in ready and back finished; the check-in dot pulses (full storyboard above). Still: the closed boundary with a dot on each flow.

### Order of the next work

1. The Director approves this plan.
2. **Style options:** two or three still frames (the hero and the parallel lanes) in different visual styles. The Director picks one; the site and the video follow it.
3. **Website build** on a preview branch, reviewed as the draft site at its preview URL.
4. **Video prototype** under issue #760, reusing the same React scene components.

## The mockup

The mockup shows the draft copy and concept pictures for review. It does not test the Astro build or human understanding. The mockup has two pages. `mockup/index.html` shows the graphical home page with the five animated illustrations and the two big figures built in. `mockup/how-it-works.html` shows the second page with the eight steps. The home page links to the second page, and the second page links back.

Each page is one self-contained HTML file. Each uses inline CSS and inline SVG. Neither makes an external request. The home page holds one small inline script, with no external source: it starts each big figure's build when the figure scrolls into view, and without scripting each figure simply shows its finished state. The second page holds no script. Under `prefers-reduced-motion`, every animation stops and each illustration and figure shows its still version.

A critic opens both pages in a browser, on desktop and mobile widths and with reduced motion on, and confirms: "How it works" follows the eight steps, parallel tracks and several teams are clear to a non-technical product person, both big figures read clearly with people, AI team members and computer systems told apart at a glance and their meaning matching `docs/guide/operating-model.md`, both removed sections are gone, and the copy reads naturally.

Both mockup pages are plan artifacts. They are never deployed. No step in this plan copies them to the website repository.

Checks, with commands. The build notes record each command and its result.

- External requests: `grep -En 'https?://|url\(|@import|<link|src=|fetch\(|XMLHttpRequest|<iframe|srcset|action='` on both files. Require no matches, except two exempt forms only: the exact SVG namespace string, and `url(` followed by `#`. List every exempt match in the build notes. An inline script with no `src` is allowed on the home page; a script source is not.
- Reduced motion: `grep -n 'prefers-reduced-motion'` in both files. Each illustration must have its still state in that block.
- Link: `grep -n 'how-it-works.html'` in `mockup/index.html`, then serve the mockup folder locally and require HTTP 200 for both pages.
- Home word check: extract the home page visible copy and run `grep -Eio 'github|\bprs?\b|pull requests?|\bissues?\b|\bci\b|\bmerg[a-z]*|\bbranch[a-z]*|\blabel[a-z]*'`. It must print nothing.
- Naming check: run a case-insensitive count grep for the product's old first name on the six changed files. Report every remaining match and why it remains. The product is called Deck, and member tools are agent tools.
- Internal terms: grep the copy for the static figures' field names and internal terms. It must hold none; each one is translated into plain words.

## What this plan does not promise

This plan does not promise a published site. Publication stays a Director decision under the parent issue.

This plan does not promise that seeded screens prove live value. Each capture carries its seeded-data limit.

This plan does not promise a human verdict. A critic reads the mockup as a director. No human director trial has run.

This plan keeps factory delivery cost unknown and claims no time saving. Evidence: `docs/guide/factory-audit-and-metrics.md` and `02-factory-story.md`.

