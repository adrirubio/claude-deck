# Director website campaign — summary and recommended changes

For: issue #768 under parent issue #745. This summary covers the four plan documents and the two mockup pages in this folder, after Director review rounds 2 to 4 (#756 to #768).

This README recommends changes. It grants no approval. The Director approves the campaign plan under #745. Publication stays a Director decision.

## The documents

Read them in this order.

| File | What it gives |
|---|---|
| `01-audit.md` | The audit of the current site and docs, page by page, with evidence and limits. |
| `02-factory-story.md` | The factory story: backlog, AI team, finished work at the top level, with the eight-step "How it works" layer, parallel tracks, several teams, and both glossaries. |
| `03-website-plan.md` | The website plan: the graphical home page, five animation concepts, the two big animated figures, the "How it works" page, technology and build, and the next-work order. Mockups in `mockup/index.html` and `mockup/how-it-works.html`. |
| `04-docs-and-video.md` | The director docs plan and the story-only video concept, with narration, animation storyboard, Suno music prompt, voice brief, and production approach. |

## Recommended changes, in order

Four stages govern the work, in order: (1) the Director approves this plan; (2) style frames are made and the Director picks a style; (3) the preview website build, including its shared React scenes; (4) the #760 video prototype using those scenes. The scoped checklist below sits inside those stages with its dependencies. It is not a second sequence. Each line states the source and the decision the Director must make.

Stage 1: Director plan approval. Stage 2: style frames and the Director's style choice. Stage 3: preview website build, including its shared React scenes. Stage 4: the #760 prototype using those scenes.

Scoped checklist, by stage:

1. **Approve this plan, then pick a visual style.** Two or three still frames (the hero and the parallel lanes) in different styles. Source: `03-website-plan.md`, "Order of the next work". Director: approve the plan and pick the style; the site and the video follow it.
2. **Build the graphical home page** in Astro, on a preview branch with its Cloudflare Pages preview URL. A few short lines, the five animations and the two big figures (who does what; what the factory is) with still versions, main action "Understand and share it". Only the built `dist/` folder deploys. Source: `03-website-plan.md`, Home and "Technology and build"; `02-factory-story.md`; `01-audit.md`, top problem 1. Director: review the draft at its preview URL and approve publication.
3. **Add the "How it works" page.** The eight steps, parallel tracks, several teams, the decision roles, the glossary, and the retell. Source: `03-website-plan.md`, "How it works"; `02-factory-story.md`, "How it works" layer; `01-audit.md`, top problem 8. Director: confirm the retained decisions are correct.
4. **Add Share Deck.** The link, the one-page summary, and later the video. Source: `03-website-plan.md`, Share Deck; `01-audit.md`, top problem 4. Director: approve the summary text.
5. **Fix the wrong facts and make new captures** for "How it works" and the video closing segment. Six harnesses, not five. Source: `03-website-plan.md`, screenshot list; `01-audit.md`, top problems 6 and 7. Director: approve public use of seeded captures, with the label.
6. **Move operator content to For operators and the docs.** Source: `03-website-plan.md`, "What to remove"; `01-audit.md`, top problems 2 and 5. Director: approve the split.
7. **Build the docs "Start here" path**, opening with the story, with its own "How it works" page. Source: `04-docs-and-video.md`, Part 1. Director: approve the docs structure.
8. **Produce the final animations** as shared React scenes, reused on the home page and in the video. The two big figures are scenes in the same library. Source: `03-website-plan.md`, animation concepts and storyboard; `04-docs-and-video.md`, storyboard. Director: the Supervisor, an AI agent, produces them (answered — see open questions). Approve the style frames first.
9. **Produce the video as code**, starting with the 20-second prototype under issue #760. Remotion renders the shared scenes, ElevenLabs narrates, Suno supplies the music. Source: `04-docs-and-video.md`, Part 2. Director: choose the voice, generate the Suno track, check the licences, approve the budget and publication.

## What each change needs from the Director

| Change | Director gives | Without it |
|---|---|---|
| Plan and style approval | Plan approval, then one picked visual style | No build starts. |
| Graphical home page | Draft review at the preview URL, then a publication decision | The site keeps the developer first screen. |
| How it works page | Confirmation of the retained decisions | The detail has no director home. |
| Share Deck | Summary text approval | A director has no artefact to forward. |
| Fact fixes and new captures | Approval to publish seeded captures, with the label | The site keeps old screens at two ages. |
| Page split | Approval of the director and operator split | Install steps stay on the director read. |
| Docs Start here | Docs structure approval | The docs keep an operator first step. |
| Final animations | Style-frame approval (producer already answered) | The home page and video hold concept pictures only. |
| Video | Voice choice, the generated Suno track, licence checks, budget, publication approval | The share kit holds pages and text only. |

## Director decisions

The Director answered the open questions on #745 (2026-10-15 and 2026-10-16).

1. **Human trial before publication:** the Director reviews a production-like draft website on a preview URL before anything is published.
2. **When to publish:** when the Director is happy with that draft.
3. **Seeded captures:** yes, public captures may use seeded example data, with the label on each image.
4. **Agent Mail "Loading participants...":** investigated. Agent Mail asks for the Director key first, and the list says "Loading participants..." while the key dialog waits. It is a misleading label, not a failure (filed as #763). Mail captures are taken with the key entered.
5. **Who produces the animations and the video:** the Supervisor, an AI agent. Budget items to check: the ElevenLabs plan, the Suno plan, the Remotion licence, agent time (measured by the #760 prototype), and optional AI texture clips.
6. **Licence terms:** the Director makes sure the Remotion, ElevenLabs and Suno subscriptions cover the commercial use.
7. **Animation rule:** smooth at 60 fps, measured on the build. DrawSVG and MorphSVG may animate SVG illustrations.
8. **"What this plan does not promise":** removed from the plan.

## Limits that stay in force

- Every isolated test capture in this campaign, and every planned new capture, uses seeded example data. No such capture shows live records. The older website screenshots keep the separate origin and age limits that `01-audit.md` records.
- Factory delivery cost stays unknown. Usage shows estimates for one supported agent tool's sessions only.
- No trial measures director time saved. No document in this folder claims a saving.
- The two mockup pages are plan artifacts. They are never deployed.
- Producing the docs pages and the video stays later work. This folder holds plans only.

## Approval note

This README grants no approval, retry, lease, merge, or publication authority. The Director approves the campaign plan under #745. Each change above then needs its own Director decision, as its line states.
