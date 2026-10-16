# Technical information — final page copy

For: issue #781, page 4 of 4 under parent issue #777.

This file is the complete copy for the Technical information page, in page order, ready for the Supervisor to build from on the preview branch. Text under a **Page copy** heading is the exact text for the page. Placement notes and evidence notes are guidance for the build; they do not appear on the page.

Planned route mapping for the builder (Leader-confirmed 2026-10-16; intended destinations, not yet live routes): Home `/`, How it works `/how-it-works/`, Quick tour `/quick-tour/`, Technical information `/technical-information/`.

No scene and no screenshot sit on this page. It is a text-and-links page, so there is no image, alt text, screenshot caption, or example-data label to supply.

## Page title

Page copy:

> Deck — Technical information

## Navigation (top of page)

Page copy:

> Deck
>
> Home · How it works · Quick tour · Technical information

Placement note: as on the home page. "Deck" links to `/`; the four links go to `/`, `/how-it-works/`, `/quick-tour/` and `/technical-information/`, in that order.

## 1. Heading and who this page is for

Page copy:

> # Technical information
>
> For the person who installs Deck and keeps it running.

## 2. What you need

Page copy:

> ## What you need
>
> Deck must run in the same environment as your agent tools and the sign-ins they use. Do not run Deck in Docker; Docker is not supported.
>
> You need:
>
> - Python 3.11 or newer
> - Node.js 22.12 or newer
> - At least one supported agent tool installed in that same environment
>
> The Python and Node.js versions above are general minimums. A tool you choose may need a newer version or extra preparation, so check its notes in the installation guide.

Placement note: "installation guide" in the last sentence links to `/docs/guide/installation`.

Evidence: Deck must run in the same environment as the agent tools and their sign-ins, and Docker is not supported — `docs/guide/installation.md:3`. The general Python and Node.js minimums and at least one supported local agent tool — `docs/guide/installation.md:11-13`. A chosen tool can need a newer Node.js version and extra preparation — `docs/guide/installation.md:20-24`.

## 3. Install Deck

Page copy:

> ## Install Deck
>
> At a glance:
>
> 1. Get a copy of Deck's source code.
> 2. Run the install script. It prepares what Deck needs to run.
> 3. Start Deck, then open it in your browser.
> 4. Run the checks in the guide to confirm the installation.
>
> The full guide gives the exact commands for each step.
>
> [Link] Read the installation guide

Placement note: the link goes to `/docs/guide/installation`.

Evidence: the source copy, install script, start, and installation checks, in that order — `docs/guide/installation.md:28-67`. The install script prepares the running parts and required folders — `docs/guide/installation.md:43-49`. Opening Deck in the browser after starting it — `docs/guide/quick-start.md:5-15`. The exact commands stay in the linked guide and are not repeated here.

## 4. Connect your AI harnesses and models

Page copy:

> ## Connect your AI harnesses and models
>
> A harness is the agent tool a team member runs. Deck works with six harnesses.
>
> Install a harness in the same environment as Deck first. Then choose the harness and AI model for each role on your AI teams.
>
> The harness guide explains what Deck can show and set up for each choice.
>
> [Link] Read the harness guide

Placement note: the link goes to `/docs/features/harnesses`. This page does not name the six harnesses; the linked docs page may name them.

Evidence: six harness choices — `docs/features/harnesses.md:3`. At least one supported agent tool must be installed in Deck's environment — `docs/guide/installation.md:11-13`. Each team role carries its own tool choice and options — `docs/features/agent-teams.md:39-50`. Team roles each carry a chosen harness and AI model — `docs/superpowers/specs/2026-10-16-website-build-design.md:85`.

## 5. Turn on your AI teams

Page copy:

> ## Turn on your AI teams
>
> Autonomy stays off until you turn it on for a team. To get ready:
>
> 1. Give Deck access to GitHub from the environment where it runs.
> 2. Prepare each team roster, choose its AI Leader, and launch the Leader as the guide explains.
> 3. Choose the GitHub repository Deck should watch.
> 4. Mark your features ready in GitHub when they can start.
> 5. Choose how finished work may merge, and set finite limits for automated work.
>
> When the rosters and watched repositories are ready, turn autonomy on. You can pause a watched repository separately.
>
> [Link] Read the autonomy guide
>
> [Link] Read the Teams guide

Placement note: the links go to `/docs/autonomy` and `/docs/features/agent-teams`, in that order.

Evidence: autonomy is off until it is turned on for a team, and a watched repository can be paused separately — `docs/autonomy.md:3`. GitHub access from Deck's environment, a chosen and launched AI Leader, a watched repository, and ready features starting work — `docs/autonomy.md:7-10`, with the launch prerequisite at `docs/autonomy.md:8`. The merge choice and finite limits come before autonomy is turned on, once rosters and watched repositories are ready — `docs/autonomy.md:11`. Human review and merge stay visible and separate from automatic checks — `docs/features/agent-teams.md:207-214`.

## 6. Where to go next

Page copy:

> ## Where to go next
>
> Start at the docs home for the full guides. For the source code, choose “View product source” there.
>
> [Link] Docs home
>
> [Link] Installation guide
>
> [Link] Quick start
>
> [Link] Harness guide
>
> [Link] Teams guide
>
> [Link] Autonomy guide

Placement note: the links go to `/docs/`, `/docs/guide/installation`, `/docs/guide/quick-start`, `/docs/features/harnesses`, `/docs/features/agent-teams` and `/docs/autonomy`, in that order. The docs-home link is not a direct source-code link; the copy sends readers to the docs home first, as written.

Evidence: the docs home carries a "View product source" action that leads to the product source — `docs/index.md:12-13`. Each linked guide exists as a source file in this repository: `docs/index.md`, `docs/guide/installation.md`, `docs/guide/quick-start.md`, `docs/features/harnesses.md`, `docs/features/agent-teams.md`, and `docs/autonomy.md`.

## Footer

Page copy:

> Deck
>
> How it works · Quick tour · Technical information

Placement note: as on the home page. "Deck" links to `/`; the three links go to `/how-it-works/`, `/quick-tour/` and `/technical-information/`, in that order.

## Link checks (not shown on the page)

Shared navigation and the footer use the planned site routes above. Every in-page technical link goes under `/docs/`:

| Page link | Destination | Source file in this repository | Declared route evidence |
|---|---|---|---|
| Installation guide | `/docs/guide/installation` | `docs/guide/installation.md` | `docs/.vitepress/config.ts:37`, with the docs base at `:7` |
| Quick start | `/docs/guide/quick-start` | `docs/guide/quick-start.md` | `docs/.vitepress/config.ts:38`, with the docs base at `:7` |
| Harness guide | `/docs/features/harnesses` | `docs/features/harnesses.md` | `docs/.vitepress/config.ts:57`, with the docs base at `:7` |
| Teams guide | `/docs/features/agent-teams` | `docs/features/agent-teams.md` | `docs/.vitepress/config.ts:71`, with the docs base at `:7` |
| Autonomy guide | `/docs/autonomy` | `docs/autonomy.md` | `docs/.vitepress/config.ts:39`, with the docs base at `:7` |
| Docs home | `/docs/` | `docs/index.md` | the docs base at `docs/.vitepress/config.ts:7` |

These are source-file and declared-route checks. They do not prove that a live page loads. Read-only requests to the preview routes returned HTTP 403 from the writing environment, which proves neither that the routes work nor that they are missing. The builder must test every served `/docs/` route on the built site before publication.

## Evidence notes (not shown on the page)

- Sources, in order of authority: the Director's decisions in `docs/superpowers/specs/2026-10-16-website-build-design.md` (`:63-86`), then the "Director decisions" and "Decisions after approval" sections of `docs/plans/2026-10-15-director-website/README.md` (`:50-74`), then `03-website-plan.md` and the accepted `pages/home.md`, `pages/how-it-works.md` and `pages/quick-tour.md` for voice, navigation and format. Where older text disagreed with a decision, the decision was followed.
- The Docker line stays Docker-specific. The source does not support a claim about every container system — `docs/guide/installation.md:3`.
- The general version minimums never stand alone: the copy points readers to the chosen tool's own notes, because a tool can need more — `docs/guide/installation.md:20-24`.
- Setup stays at a glance. Exact commands, sign-in setup and other private running details stay in the linked docs and out of this page.
- The preview address is deliberately not linked or named anywhere in this file.
