# Director website campaign — summary and recommended changes

For: issue #758 under parent issue #745. This summary covers the four plan documents and the two mockup pages in this folder, after the Director review round (#756 to #758).

This README recommends changes. It grants no approval. The Director approves the campaign plan under #745. Publication stays a Director decision.

## The documents

Read them in this order.

| File | What it gives |
|---|---|
| `01-audit.md` | The audit of the current site and docs, page by page, with evidence and limits. |
| `02-factory-story.md` | The factory story: backlog, AI team, finished work at the top level, with the six-step "How it works" layer and both glossaries. |
| `03-website-plan.md` | The website plan: the graphical home page, four animation concepts, and the "How it works" page. Mockups in `mockup/index.html` and `mockup/how-it-works.html`. |
| `04-docs-and-video.md` | The director docs plan and the story-only video concept, with narration, animation storyboard, Suno music prompt, voice brief, and production approach. |

## Recommended changes, in order

Do the changes in this order. Each line states the source and the decision the Director must make.

1. **Build the graphical home page.** A few short lines, the four animations with still versions, main action "Understand and share it". Source: `03-website-plan.md`, Home; `02-factory-story.md`; `01-audit.md`, top problem 1. Director: approve the copy and the animations. Publication stays a Director decision.
2. **Add the "How it works" page.** The six steps, the decision roles, the glossary, and the retell. Source: `03-website-plan.md`, "How it works"; `02-factory-story.md`, "How it works" layer; `01-audit.md`, top problem 8. Director: confirm the retained decisions are correct.
3. **Add Share Deck.** The link, the one-page summary, and later the video. Source: `03-website-plan.md`, Share Deck; `01-audit.md`, top problem 4. Director: approve the summary text.
4. **Fix the wrong facts and make new captures** for "How it works" and the video closing segment. Six harnesses, not five. Replace the old-version screenshots. Source: `03-website-plan.md`, screenshot list; `01-audit.md`, top problems 6 and 7. Director: approve public use of seeded captures, with the label.
5. **Move operator content to For operators and the docs.** Install steps, shell commands, and the tech list leave the director pages. Source: `03-website-plan.md`, "What to remove or move to the docs"; `01-audit.md`, top problems 2 and 5. Director: approve the split.
6. **Add "Limits and trust".** Claude Code session estimates only, delivery cost unknown, no time-saving claim. Source: `03-website-plan.md`, "Limits and trust"; `01-audit.md`, top problem 9. Director: approve the limit wording.
7. **Build the docs "Start here" path**, opening with the story, with its own "How it works" page linked to the technical docs. Source: `04-docs-and-video.md`, Part 1. Director: approve the docs structure.
8. **Produce the final animations**, reused on the home page and in the video. Source: `03-website-plan.md`, animation concepts; `04-docs-and-video.md`, storyboard. Director: decide who produces them.
9. **Produce the video as code.** Remotion scenes, ElevenLabs narration, Suno music. The first step is a separate 20-second prototype issue. Source: `04-docs-and-video.md`, Part 2. Director: choose the voice, generate the Suno track, check the licences, approve the budget and publication.

## What each change needs from the Director

| Change | Director gives | Without it |
|---|---|---|
| Graphical home page | Copy and animation approval, then a publication decision | The site keeps the developer first screen. |
| How it works page | Confirmation of the retained decisions | The detail has no director home. |
| Share Deck | Summary text approval | A director has no artefact to forward. |
| Fact fixes and new captures | Approval to publish seeded captures, with the label | The site keeps old screens at two ages. |
| Page split | Approval of the director and operator split | Install steps stay on the director read. |
| Limits and trust | Limit wording approval | A reader can over-read the benefit. |
| Docs Start here | Docs structure approval | The docs keep an operator first step. |
| Final animations | A producer decision (who, and at what budget) | The home page and video hold concept pictures only. |
| Video | Voice choice, the generated Suno track, licence checks, budget, publication approval | The share kit holds pages and text only. |

## Open questions for the Director

The campaign leaves six questions open. Each question blocks the change named beside it.

1. Is a human director trial needed before publication? The Director reviewed the earlier plan and requested these revisions. Agents checked the revised artifacts. No separate human comprehension trial is recorded. This question blocks a final publication claim.
2. When and how does the website change publish? The website repository deploys its whole root on a push to its main branch. A partial copy is not a safe publish. This question blocks change 1.
3. May public captures use seeded data, with the label on each image? Every fresh capture in this campaign uses seeded example states. This question blocks change 4 and the video closing segment.
4. Agent Mail stayed at "Loading participants..." in two agent checks. Investigate that state before any Mail capture or Mail claim. This question blocks any Mail image.
5. Who produces the final animations and the video, and at what budget? This campaign plans both and produces neither. This question blocks changes 8 and 9.
6. What are the commercial-use licence terms of Remotion, ElevenLabs, and Suno on the plans the Director will use? Check the commercial-use terms for the chosen plans before production spending. Keep the results with the project. Publication stays a separate Director decision. This question blocks change 9.

## Limits that stay in force

- Every isolated test capture in this campaign, and every planned new capture, uses seeded example data. No such capture shows live records. The older website screenshots keep the separate origin and age limits that `01-audit.md` records.
- Factory delivery cost stays unknown. Usage shows Claude Code session estimates only.
- No trial measures director time saved. No document in this folder claims a saving.
- The two mockup pages are plan artifacts. They are never deployed.
- Producing the docs pages and the video stays later work. This folder holds plans only.

## Approval note

This README grants no approval, retry, lease, merge, or publication authority. The Director approves the campaign plan under #745. Each change above then needs its own Director decision, as its line states.
