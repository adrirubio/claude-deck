# Quick tour — final page copy

For: issue #780, page 3 of 4 under parent issue #777.

This file is the complete copy for the Quick tour page, in page order, ready for the Supervisor to build from on the preview branch. The home page's main button, "Take the quick tour", leads here. Text under a **Page copy** heading is the exact text for the page. Screenshot requests, placement notes and evidence notes are guidance for the build; they do not appear on the page.

Planned route mapping for the builder (Leader-confirmed 2026-10-16; intended destinations, not yet live routes): Home `/`, How it works `/how-it-works/`, Quick tour `/quick-tour/`, Technical information `/technical-information/`.

Every stop shows one seeded Deck screenshot carrying this label on the image: "Example data — seeded screens. Not live records." Crop every capture to the relevant state, and crop out harness names, old product branding, and unrelated technical chrome; keep the seeded label visible, and do not invent UI labels. The roughly two-minute read is a design target for the copy length, not a measured result; all supplied visible text, including the six on-image labels, is budgeted at 400 words at most; alt text and builder notes sit outside that count.

## Page title

Page copy:

> Deck — Quick tour

## Navigation (top of page)

Page copy:

> Deck
>
> Home · How it works · Quick tour · Technical information

Placement note: as on the home page. "Deck" links to `/`; the four links go to `/`, `/how-it-works/`, `/quick-tour/` and `/technical-information/`, in that order.

## 1. Heading and intro

Page copy:

> # Quick tour
>
> Six short stops to see what Deck looks like, and what you would do in it.
>
> You, the Director, write your features in GitHub and mark them ready. These pictures show different example items inside Deck.

Placement note: no screenshot sits in the intro. Writing features happens in GitHub, outside Deck, so no Deck screen is invented for it.

Evidence: the Director writes and orders the features and marks what is ready — `docs/guide/operating-model.md:53-57`.

## 2. The six stops

### Stop 1 — Your features connect to a team

Page copy:

> ### 1. Your features connect to a team
>
> Deck connects the features you mark ready to the team you choose.

Screenshot: Repositories. Seeded state: the three seeded connections, with new work paused on two of them. Caption:

> Repositories, with example data: three connections; new work is paused on two.

Alt text:

> The Repositories screen with example data, listing three connections and whether each is taking in new work.

Evidence: the screen lists the connections across teams, with setup shown apart from whether new work is coming in — `docs/features/repositories.md:3-5`. The seeded connections and their paused state — `docs/plans/2026-10-15-director-website/01-audit.md:39`.

### Stop 2 — Choose who is on each team

Page copy:

> ### 2. Choose who is on each team
>
> Each team has a roster you prepare: its AI Leader, agent owners and AI reviewers, each with their own tools and models.

Screenshot: Teams. Seeded state: the "Release crew" roster, with its named Leader and member slots. Caption:

> A team roster, with example data: its AI Leader and team members.

Alt text:

> The Teams screen with example data, showing one team's roster, its named AI Leader, and its members.

Evidence: the Director chooses the roster and how many builders and checkers each team has — `docs/guide/operating-model.md:30` and `:46`. Each team slot stores its own provider, launch mode and provider options — `docs/features/agent-teams.md:39-50`. The seeded roster — `docs/plans/2026-10-15-director-website/01-audit.md:40`.

### Stop 3 — See what needs you

Page copy:

> ### 3. See what needs you
>
> One overview puts what needs you first, then how every team is doing.

Screenshot: Overview. Seeded state: "Needs you" with campaign progress and team summaries, and counts with one item in each state (queued, active, review, attention, finished). Caption:

> The Overview, with example data: what needs you comes first.

Alt text:

> The Overview screen with example data, showing what needs the Director, campaign progress, and a summary for each team.

Evidence: "Needs you", campaign progress and team decision summaries were seen in a browser with seeded data — `docs/plans/2026-10-15-director-website/01-audit.md:37`; the counts are `docs/features/dashboard.md:7`. Builder note: counts alone do not prove the summaries; the browser observation at `01-audit.md:37` carries that claim.

### Stop 4 — Work in progress

Page copy:

> ### 4. Work in progress
>
> Each feature gets its own AI team, working at its own pace. Work shows who is assigned and what is waiting.

Screenshot: Work. Seeded state: work items in mixed states, including one active item and the queued item with no owner yet. Caption:

> Work, with example data: assigned features and a feature waiting for an owner.

Alt text:

> The Work screen lists example features, their states, and their assigned owners. One queued feature has no owner yet.

Evidence: mixed-team work items with their current state — `docs/features/work.md:3`; the seeded queued item with no owner — `scripts/e2e/scenarios.py:227-228`; this mixed-state capture — `docs/plans/2026-10-15-director-website/03-website-plan.md:176`.

### Stop 5 — When work waits for a person

Page copy:

> ### 5. When work waits for a person
>
> An AI reviewer checks work they did not build. Your rules may ask for your review too.

Screenshot: Work. Seeded state: the seeded item waiting for human review under that team's rules. The picture illustrates the second sentence, not the AI reviewer's own check. Caption:

> Waiting for human review, with example data: under this team's rules, this item waits for a person.

Alt text:

> The Work screen with example data, showing an item whose state says it is waiting for human review.

Evidence: the seeded waiting-for-human-review item — `scripts/e2e/scenarios.py:218-220`. Building and checking are separate roles — `docs/guide/operating-model.md:18` and `:27`. Human review stays separate from agent plan approval — `docs/features/work.md:13`; human review and merge gates — `docs/features/agent-teams.md:207-214`; merge under the repository rules — `docs/guide/supervised-factory-playbook.md:154`.

### Stop 6 — Finished work, back in GitHub

Page copy:

> ### 6. Finished work, back in GitHub
>
> After the required reviews and checks, work can merge under your project's rules. You decide when it is ready to publish.

Screenshot: Work. Seeded state: the merged item in the list, shown with the All filter. Caption:

> Work, with example data: a merged item shown with the All filter.

Alt text:

> The Work screen with example data, showing a merged item in the mixed-state All view.

Evidence: human review and merge follow repository policy — `docs/guide/index.md:13`; passing checks alone do not prove review acceptance — `docs/features/agent-teams.md:207-214`. The seeded merged item — `scripts/e2e/scenarios.py:225-226`; the All filter as the mixed-state view — `frontend/src/features/factory/filters.tsx:40-45`, with the capture instruction at `docs/plans/2026-10-15-director-website/03-website-plan.md:176`. Approving publication stays with the Director — `docs/guide/operating-model.md:91`. Work may merge into an integration branch before a later promotion, so merging does not by itself mean the work is ready to publish — `docs/guide/supervised-factory-playbook.md:150-154`.

## 3. Share the tour

Page copy:

> ## Share the tour
>
> Send this tour to a colleague:
>
> "Worth a look: Deck — your features, built and checked by AI teams."
>
> Prefer to watch? A short video of Deck in action will join this page later.

Placement note: the quoted line is the sendable link text; the builder presents it with a link to this page, `/quick-tour/`. The video line is page copy only; no video is produced or linked yet.

Evidence: the coming short video is the Director's plan for this page (issue #780, with the video itself under issue #760). No product fact beyond the tour's own story is claimed in the share line.

## 4. Next

Page copy:

> ## Next
>
> Want the full story? Read How it works. Setting up? Try Technical information.
>
> [Link] How it works
>
> [Link] Technical information

Placement note: the links go to `/how-it-works/` and `/technical-information/`.

## Footer

Page copy:

> Deck
>
> How it works · Quick tour · Technical information

Placement note: as on the home page. "Deck" links to `/`; the three links go to `/how-it-works/`, `/quick-tour/` and `/technical-information/`, in that order.

## Evidence notes (not shown on the page)

- Sources, in order of authority: the Director's decisions in `docs/superpowers/specs/2026-10-16-website-build-design.md` (`:70-86`), then the "Director decisions" and "Decisions after approval" sections of `docs/plans/2026-10-15-director-website/README.md` (`:50-74`), then `03-website-plan.md` (share-kit background and the screenshot list) and the accepted `pages/home.md` and `pages/how-it-works.md` for voice and navigation. Where older text disagreed with a decision, the decision was followed.
- The factory here is Deck and the AI teams, supervised from outside (`docs/superpowers/specs/2026-10-16-website-build-design.md:80`). `docs/guide/operating-model.md` still describes the factory the older way (`:38`, `:42-44`) until issue #775 updates it, so factory-boundary lines cite the decision; other facts cite the guide, feature docs and seed at the lines shown.
- No Harnesses screenshot is used on this page: its cards display a harness name the naming rule keeps off the site. The harnesses themselves are also never named in the copy.
- The preview address is deliberately not linked or named anywhere in this file.
