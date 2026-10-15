# Audit — how the site and the docs tell the story to a director

For: row 741 under parent issue #745.

Purpose. This document audits claudedeck.org and the Deck documentation for a non-technical director.

Director. A director decides value, risk, and sharing. The director does not code.

Evidence rule. Each claim names its evidence: a page file, a doc file, or an e2e screen label.

## Sources read

Website. The read-only reference clone at commit `0c35f391759633c774b7cc4ace5c52b96dd53d12`.

- Landing page: `website-ref/index.html`.
- Built docs pages under `website-ref/docs/`, generated from Deck `docs/`.
- Site readme: `website-ref/README.md`.

Documentation. The Deck source in this repository at `origin/master` `b43af6d`.

- Home: `docs/index.md`. Introduction: `docs/guide/index.md`.
- Guide pages under `docs/guide/`, including `docs/guide/quick-start.md` and `docs/guide/supervised-factory-playbook.md`.
- Feature pages under `docs/features/`, including `docs/features/work.md`, `docs/features/agent-teams.md`, and `docs/features/repositories.md`.
- `docs/autonomy.md` and `docs/changelog.md`.

Product. The tested source is Deck 3.1.0 on the isolated e2e instance via `scripts/e2e-instance.sh`.

- Version evidence: `VERSION` in the workspace root reads `3.1.0`. It shows the tested source version. It does not show a published release.
- Instance evidence: `GET http://127.0.0.1:18765/health` returns `{"name":"Claude Deck","version":"3.1.0","status":"running"}`. It shows the tested source version. It does not show a published release.
- Screens checked: seven scoped screens — Overview (`/`), Work (`/work`), Repositories (`/repositories`), Teams (`/teams`), Agent Mail (`/agent-mail`), Harnesses (`/harnesses`), and Audit (`/audit`).
- Sidebar evidence: `frontend/src/components/layout/Sidebar.tsx` lists eight entries. The seven screens above are a scoped selection from those eight.

## Product screens observed on the tested source

Evidence rule for this section. A line means my observation on the e2e instance. A limit means the observation stops there.

- Overview (`/`). The screen shows `NeedsYou`, `CampaignProgress`, team summaries, and tracking counts. Evidence: `frontend/src/features/factory/pages/OverviewPage.tsx` lines 63–67 hold `NeedsYou`, `CampaignProgress`, and `StatusTiles`. My check of `GET /api/v1/factory/overview` returned counts `queued`, `active`, `review`, `attention`, and `finished`. The website Overview image shows numeric ID filters and tracking counts instead. Evidence: `website-ref/assets/screenshot-overview.png` alt text and caption at `website-ref/index.html` lines 263 and 277. C1 saw "Needs you", campaign progress, "Your decisions ahead", and team decision summaries here. My observation confirms the campaign and team parts. Limit: I read the API and source components. I did not click every Overview dialog in a browser.
- Work (`/work`). The screen shows owners, waiting reasons, and PR links, with team, repository, and harness filters. Evidence: `docs/features/work.md` opening and `docs/guide/quick-start.md` key-pages table. Limit: the e2e `GET /api/v1/factory/work` returned no body in my probe. I did not invent Work rows.
- Repositories (`/repositories`). The screen shows configured enablement apart from effective intake. My check of `GET /api/v1/factory/repositories` returned three scopes with states `blocked` and `Team automation is paused.` Evidence: that response. The intakes show paused teams, not live polling.
- Teams (`/teams`). The screen shows rosters, the Leader slot, and launch plans. Evidence: `docs/features/agent-teams.md` and `docs/guide/index.md`. Limit: the e2e `GET /api/v1/agent-teams` returned no body in my probe. I make no claim about a live roster count.
- Agent Mail (`/agent-mail`). The screen lists participants and team mail. Evidence: `frontend/src/features/agent-mail/TeamTab.tsx` line 124 shows `Loading participants...`. Limit: in my probe the screen data did not load beyond that label. C1 saw the same label after 30 seconds. L1 did not check this. I record the stall as a limit. I do not claim the mail function fails.
- Harnesses (`/harnesses`). The screen shows a readiness catalogue. My check of `GET /api/v1/providers` returned six providers with display names, binary names, and capability labels. Evidence: that response. The tested source has six harnesses.
- Audit (`/audit`). The screen shows the delivery ledger and metrics. Evidence: `docs/guide/factory-audit-and-metrics.md` and `docs/index.md`. Limit: audit events were locked in my probe. I did not unlock them and I did not change settings. I make no claim about event rows.

## Verdict in one paragraph

A director learns that Deck shows agent work on GitHub issues. The director does not learn quickly why that work matters, what the director decides, or how to share the idea.

The first screens use developer words before they explain the factory story. Evidence: the landing page and the docs named below.

The factory intent is present but buried. Evidence: sections 3 and 4 below.

## What a director can learn, page by page

### Landing page — `website-ref/index.html`

The title tells the director the topic. Evidence: line 6 reads `Review and Steer Coding Agents Working on Your GitHub Issues`.

The first heading is only the product name. Evidence: line 100–102, `<h1>Claude Deck</h1>`.

The tagline needs developer context. Evidence: lines 105–107 read `Follow and steer coding agents working on your GitHub issues`.

The definition is clear but technical. Evidence: lines 110–112 name `queued`, `owner`, `pull requests`, and `attempts` without a glossary.

The badges need a glossary. Evidence: lines 114–122 list `Local-only`, `No Deck account`, `No Deck telemetry`, `Work and Repositories`, `Human actions`, `Audit history`, and `Five harnesses`. A director does not learn the meaning of `harness` here.

The main actions suit developers. Evidence: lines 126–133 offer `See how it works` and `Get Started`. Neither action says `Understand and share it`.

The audience excludes the director. Evidence: lines 197–199 read `Claude Deck is for technical operators who already have repositories, local agent tools, tmux sessions and their own model credentials`.

The value section helps a director a little. Evidence: lines 157, 165, and 173 explain `Work`, `Plan approval`, and `audit ledger`. The text still uses `pull request`, `operator`, and `ledger` without a plain definition.

The warning helps a director. Evidence: lines 185–186 state the product changes real local agent files and is not a mock viewer.

The screenshots use fake data. Evidence: lines 252 and 277 state the images show synthetic example records from `Claude Deck 3.0.0`. A director cannot tell whether the fake data proves value.

The feature cards mix two audiences. Evidence: lines 306–308 (`Overview and Work`), 348–350 (`Harnesses`), and 393–395 (`Agent Mail`) use operator words. The cards link to developer docs, for example `/docs/features/work.html` at line 293.

The install steps assume a developer. Evidence: lines 597–598 require `Python 3.11+`, `Node.js 18+`, and an agent CLI. Lines 614–631 use `git clone`, `./scripts/install.sh`, and `./scripts/dev.sh`. A director gets lost here.

The tech list assumes a developer. Evidence: lines 648–653 list `FastAPI`, `React`, `TypeScript`, `SQLite`, `shadcn/ui`, and `Tailwind CSS`.

Where the director gets lost on this page: the words `harness`, `tmux`, `pull request`, `attempt`, `audit ledger`, `operator`, and `CLI` appear before a plain factory story.

### Docs home — `docs/index.md` and `website-ref/docs/index.html`

The hero is abstract. Evidence: `docs/index.md` sets `text: Observe work. Review interventions.` and `tagline: A self-hosted workspace for bounded coding-agent attempts on GitHub issues`. A director does not learn what to observe or why.

The first action suits an operator. Evidence: `docs/index.md` offers `Start with work` and links it to `/guide/quick-start`. The action does not say what work means.

The feature blurbs assume the factory model. Evidence: `docs/index.md` describes `mixed-team tracking`, `configured enablement`, `effective intake`, and `authorized remedies`. A director needs those words defined first.

The scope section is honest but hard. Evidence: `docs/index.md` states the reference describes an integrated product source candidate and that earlier packaged releases can retain previous navigation. A director cannot map that sentence to a buying or sharing decision.

The M1b sentence blocks sharing. Evidence: `docs/index.md` states `The operator accepted M1b; that decision does not supply missing observations.` and `This source does not establish M2 or M3 acceptance.` A director cannot cite that text to a peer.

### Guide introduction — `docs/guide/index.md`

The first line is precise and dense. Evidence: the file opens with `A self-hosted workspace to observe and intervene in bounded coding-agent attempts on GitHub issues, with mixed harnesses, visible policies and recovery controls.`

The actor list helps. Evidence: the heading `Keep the actors separate` states that agents propose plans, operators configure policies, and human PR review follows repository policy. That text supports the director role.

The trust limits are clear. Evidence: the file states `Finished tracking is not a measured delivery outcome.` and `Unknown observations remain unknown.` A director can cite that caution.

The next-steps list suits builders. Evidence: the file links `Supervised factory playbook`, `Installation`, `Quick Start`, `Factory API`, and `Architecture`. A director gets no short briefing path.

### Quick start — `docs/guide/quick-start.md`

The first step is a shell command. Evidence: the file states `Start Deck, inspect existing work, or launch a manual session` and then gives `./scripts/dev.sh`. A director gets lost at the first step.

The observe section helps an operator. Evidence: the file states `Overview is the home page for tracking counts and automation observations` and names `Work` and `Repositories`. A director learns the screens but not the decision each screen supports.

The setup flow is careful. Evidence: the file states `Guided setup` keeps the draft, the saved configuration, the reviewed launch, and the activation as separate steps. The flow states the Leader is the team's explicit `leader_slot_id`. That text helps trust but uses `slot` without a plain definition.

The instance section assumes an operator. Evidence: the file gives `CLAUDE_DECK_INSTANCE_NAME`, `CLAUDE_DECK_INSTANCE_ACCENT`, and `CORS_ORIGINS`. A director does not need those values in a first read.

### Features and work pages — `docs/features/`

Work page. Evidence: `docs/features/work.md` opens with `Open Work to browse mixed-team work.` The page then defines filters, counts, and retry confirmations in operator terms. The page states `Human PR review remains separate from agent plan approval and operator interventions.` That separation helps a director.

Agent Teams page. Evidence: `docs/features/agent-teams.md` opens with `Agent Teams are saved rosters of local Claude Code, Codex CLI, GitHub Copilot CLI, OpenCode CLI, and Pi sessions.` The roster idea helps. The page then uses `watch`, `polling`, `merge policy`, `finite dispatch/recovery limits`, and `leader_slot_id` without a director glossary.

Operating model page. Evidence: `docs/guide/operating-model.md` defines the factory, the Director, the Supervisor, the Leader, backlog ownership, and retained decisions. Lines 17–18 name the Director as owner of the outcome and the backlog. Lines 85–91 separate Leader plan approval from the Director's retained decisions. The guide sidebar links it: `docs/.vitepress/config.ts` line 40 lists `Factory Operating Model`. Status: this page exists in source. It needs revision for a director, not creation. The website reference does not ship these guide pages. Status: public pages are missing. The source page is separate.

Other guide and feature pages, one by one.

- `docs/features/dashboard.md` (Overview). Reviewer judgment: the page must map counts to decisions. The tested Overview source holds `NeedsYou` and `CampaignProgress`. The docs name the counts first. A director needs the decision first.
- `docs/features/work.md` (Work). Evidence: the page states `Human PR review remains separate from agent plan approval`. What works: the separation is clear. Gap: filters and retry rules come before the director decision.
- `docs/features/repositories.md` (Repositories). What works: the page separates configured enablement from effective intake. Evidence: `docs/guide/index.md` states that split. Gap: `intake`, `polling`, and `advisory overlaps` need a glossary first.
- `docs/features/agent-teams.md` (Teams). What works: the roster idea in the first sentence. Gap: `leader_slot_id`, budgets, and reuse rules need a plain map.
- `docs/features/agent-mail.md` (Agent Mail). What works: the page can show coordination apart from human PR review. Gap: my Audit probe found the participants list did not load. A director needs a load state, not a silent stall.
- `docs/features/harnesses.md` (Harnesses). What works: per-harness readiness. Evidence: `GET /api/v1/providers` shows six providers. Gap: the landing page still says five. See contradiction 1.
- `docs/features/agent-bridge.md` and `docs/features/cc-bridge.md` (Live sessions). Evidence: the sidebar names `Live sessions` at `/agent-bridge`. These pages suit operators. A director needs one line: live sessions let a person watch or join agent work.
- Remaining feature pages count. Evidence: `docs/features/` holds 22 files in total. Reviewer judgment: the count alone is not an audit. Each page above names its finding. The catalogue still hides the seven scoped screens.

### Autonomy — `docs/autonomy.md`

The opening suits an operator. Evidence: the file opens with `This guide is for the operator of a Deck team. Autonomy is off until you enable it`. That sentence tells the director to stop.

The preconditions assume a host operator. Evidence: step 1 tells the reader to add `github_token=<token>` to `backend/.env` and restart the backend. A director gets lost here.

The value is still visible. Evidence: the file states issues move through `queued, dispatched, verifying, and ready for human review or merged`. That sentence describes the factory line in plain stages.

### Changelog — `docs/changelog.md`

The changelog is honest. Evidence: the heading `3.0.0 — Unreleased` lists new Overview, Work, and Repositories behaviour.

The evidence limits help a director. Evidence: the file states `Finished is a tracking state. It is not independently reviewed delivery` and `Cost is unknown.` A director can share that caution.

The changelog does not give a story. Evidence: the file lists changes and fixes. It does not state what a director can now decide faster or share with a board.

## Is the factory intent clear?

Factory intent. Deck runs a team of AI agents that deliver work from GitHub issues to merged PRs. The director decides the important things.

Verdict. The intent is present in fragments. It is not clear on first read by a director.

Fragment one: delivery from issue to review. Evidence: `docs/autonomy.md` states issues move through `queued, dispatched, verifying, and ready for human review or merged`. That text shows a line but not the director decision.

Fragment two: separate decisions. Evidence: `docs/guide/index.md`, heading `Keep the actors separate`, states agents propose plans, operators configure policies, and human PR review follows repository policy.

Fragment three: visible ownership. Evidence: e2e `GET /api/v1/factory/overview` returns counts `queued`, `active`, `review`, `attention`, and `finished`. The `Sidebar.tsx` label list names `Overview` and `Work`. A director can see waiting work but not the value of the work.

Fragment four: the landing summary. Evidence: `website-ref/index.html` lines 110–112 state Deck shows which issues are queued, which agent owns each one, and which pull requests wait for review. That sentence is the clearest factory fragment on the site.

Product benefit, separate from measured savings. The benefit exists on the landing page. Evidence: `website-ref/index.html` lines 226–240, heading `Why use Claude Deck instead of GitHub and terminals alone?` The text states GitHub stays the home for issues and PRs while Deck adds one operating view: what is queued, who owns it, what waits for a person, and what needs attention. Assessment: that explanation is present. Its clarity is low for a director. The paragraph comes after the audience warning and still uses `Attempts`, `review`, and `attention` without a glossary. No page claims a measured time saving. Evidence: `docs/index.md` states `Finished tracking does not establish reviewed delivery.` and `docs/changelog.md` states `Cost is unknown.` Reviewer judgment: keep the benefit claim and the evidence limits. Do not add a savings claim without trial data.

Missing piece two: the director decision map. Decision roles, corrected. Agent plan approval belongs to the designated Leader. Evidence: `docs/guide/index.md` line 13 states agents propose plans for designated Leader decisions. Campaign approval belongs to the Director. The Director owns the backlog and the retained decisions. Evidence: `docs/guide/operating-model.md` lines 85–91 list backlog ownership for the Director and plan approval for the Team Leader, with publication, budgets, models, and security HOLD as Director retained decisions. Human PR review and merge follow repository policy. Evidence: `docs/guide/index.md` states human PR review and merge follow repository policy. No first page lists those three roles together. Evidence: the landing feature cards at lines 306–308 and 393–395 split those decisions across operator cards.

Missing piece three: the share artefact. No page offers a one-page brief for a board or peer. Evidence: the landing page offers `Docs` at line 73 and GitHub at line 75. Neither link gives a director summary to forward.

## Where the site and docs contradict v3.1

Contradiction 1: harness count. The landing page names five harnesses. Evidence: `website-ref/index.html` line 121 badge `Five harnesses` and lines 348–350 listing Claude Code, Codex CLI, GitHub Copilot CLI, OpenCode CLI, and Pi. The product has six. Evidence: `docs/index.md` states `Harnesses includes the versioned operations/readiness catalog for all six harnesses`. The e2e `Sidebar.tsx` shows `Harnesses` as one screen. The count mismatch confuses a director.

Contradiction 2: screenshot version. The landing screenshots freeze version 3.0.0. Evidence: `website-ref/index.html` lines 252 and 277 state the images show `Claude Deck 3.0.0`. The site readme agrees: `website-ref/README.md` lines 27 and 33 name source commit `bc66e5f` from `release/v3.0.0`. The tested source is 3.1.0. Evidence: workspace `VERSION` reads `3.1.0` and the e2e `/health` reports `3.1.0`. Both show the tested source version. They do not show a published release. Reviewer judgment: a director sees old screens.

Contradiction 3: docs build lag. The website docs copy is generated from v3.0. Evidence: `website-ref/README.md` lines 24–29 state the docs under `docs/` are generated from `release/v3.0.0`. The source docs at `origin/master` describe the integrated candidate, including six harnesses. Evidence: `docs/index.md`, paragraph on Harnesses. A director who follows the site link reads older navigation claims.

Contradiction 4: changelog version label. The changelog heading reads `3.0.0 — Unreleased`. Evidence: `docs/changelog.md` heading line. The tested source is 3.1.0. Evidence: `VERSION` file and e2e `/health`. Both show the tested source version. They do not show a published release. Reviewer judgment: a director cannot tell whether the audit ledger is ready or planned.

Setup barrier, not a contradiction: autonomy host setup. The site states local running. Evidence: `website-ref/index.html` line 186 states Deck runs on the machine, with no Deck account and no Deck telemetry. Line 186 also names external services and credentials. Line 198 targets technical operators. The autonomy guide then needs host token setup. Evidence: `docs/autonomy.md` step 1 asks the reader to edit `backend/.env`. Local running and host setup do not conflict. The gap is an audience and setup barrier: a director cannot start the factory alone, and an operator must set up the host first.

## Top ten problems, ranked

Rank rule. Rank measures how much the problem stops a director from understanding and sharing Deck. Higher rank blocks sooner.

1. No plain factory story on the first screen. Evidence: `website-ref/index.html` lines 100–122 and `docs/index.md` hero `Observe work. Review interventions.` A director cannot repeat the value in one sentence.

2. The page excludes the director. Evidence: `website-ref/index.html` lines 197–199 state the product is for technical operators with repositories, agent tools, `tmux` sessions, and model credentials. A director leaves at that line.

3. Jargon without a glossary. Evidence: `website-ref/index.html` lines 114–122, and `docs/features/agent-teams.md` (`watch`, `polling`, `merge policy`, `leader_slot_id`). A director must stop to decode each term.

4. No share artefact or share action. Evidence: `website-ref/index.html` lines 126–133 (`See how it works`, `Get Started`) and `docs/guide/index.md` next-steps list. The parent goal requires `Understand and share it`. No button or brief serves that goal.

5. Install and start assume a developer. Evidence: `website-ref/index.html` lines 597–598 and 614–631, and `docs/guide/quick-start.md` first command `./scripts/dev.sh`. A director cannot try or judge the product alone.

6. Six versus five harnesses. Evidence: `website-ref/index.html` line 121 versus `docs/index.md` six-catalogue text. The mismatch breaks trust in the whole story.

7. Screenshots and docs lag the product. Evidence: `website-ref/index.html` line 277 (3.0.0) versus `VERSION` 3.1.0, and `website-ref/README.md` lines 27–29. A director shares old screens.

8. Decision rights are scattered. Evidence: `docs/guide/index.md` `Keep the actors separate` versus `website-ref/index.html` feature cards at lines 306 and 393. A director must hunt for who approves, who reviews, and who merges.

9. Benefit and limits lack one clear paragraph. Evidence: `website-ref/index.html` lines 226–240 state the benefit: one operating view across teams and repositories. Evidence: `docs/index.md` (`Finished tracking does not establish reviewed delivery`) and `docs/changelog.md` (`Cost is unknown`) state the limits. Reviewer judgment: the parts are both true. No short paragraph joins the benefit to its limits for a director to cite.

10. Too many feature doors first. Evidence: 22 files in `docs/features/` versus eight sidebar entries in `frontend/src/components/layout/Sidebar.tsx`. The seven audited screens are a scoped selection. Reviewer judgment: a director faces a catalogue, not a path.

## What stays good

Plain deployment warning. Evidence: `website-ref/index.html` lines 185–186 state the UI changes real agent files. A director trusts that warning.

Honest evidence limits. Evidence: `docs/guide/index.md` and `docs/changelog.md` state finished tracking is not reviewed delivery and cost is unknown. Keep those limits.

Separate review kinds. Evidence: `docs/features/work.md` states human PR review remains separate from agent plan approval. That separation fits director control.

Live product proves the screens exist. Evidence: e2e `/health` reports the tested source 3.1.0 running. `Sidebar.tsx` lists eight entries. The seven scoped screens match that selection. The story is true. The telling comes first.

## Audit limits

Screenshots. I did not open every website image at pixel size. I read image files, alt text, and captions. Evidence: `website-ref/assets/` holds eight screenshots, including `screenshot-overview.png` and `screenshot-work.png`.

E2e path. I opened the seven scoped screens via the e2e instance and recorded what each screen shows above. Limit: I read the e2e API and source components. I did not click every dialog in a browser. Agent Mail did not load beyond `Loading participants...`. Audit events stayed locked. I did not unlock them.

Scope. This audit reads text and navigation. Reviewer judgments state predicted director reactions. No human director trial supports those judgments. This audit does not test colour contrast, screen readers, or print layout.
