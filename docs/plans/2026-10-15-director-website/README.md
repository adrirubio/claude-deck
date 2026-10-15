# Director website campaign — summary and recommended changes

For: row 744 under parent issue #745. This summary covers the four plan documents in this folder.

This README recommends changes. It grants no approval. The Director approves the campaign plan under #745. Publication stays a Director decision.

## The documents

Read them in this order.

| File | What it gives |
|---|---|
| `01-audit.md` | The audit of the current site and docs, page by page, with evidence and limits. |
| `02-factory-story.md` | The factory story: one sentence, one paragraph, six steps, and the glossary of 15 words. |
| `03-website-plan.md` | The website plan and the home-page draft copy. The mockup sits in `mockup/index.html`. |
| `04-docs-and-video.md` | The director docs plan and the video concept, with script, storyboard, and AI voice requirements. |

## Recommended changes, in order

Do the changes in this order. Each line states the source and the decision the Director must make.

1. **Rewrite the home page first screen.** Use the story sentence, the six-step path, and the decisions on the first screen. Source: `03-website-plan.md`, "First screen"; `01-audit.md`, top problem 1. Director: approve the copy. Publication stays a Director decision.
2. **Add Share Deck.** Give the director the link, the one-page summary, and later the video. Each item stands alone. Source: `03-website-plan.md`, "How a director shares Deck"; `01-audit.md`, top problem 4. Director: approve the summary text.
3. **Fix the wrong facts.** Show six harnesses, not five. Replace the v2.0.0 and v3.0.0 screenshots with new captures of the tested source. Source: `03-website-plan.md`, "What to remove or move to the docs"; `01-audit.md`, top problems 6 and 7. Director: approve public use of seeded captures, with the seeded-data label.
4. **Move operator content off the director pages.** Move install steps, shell commands, and the tech list to For operators and the docs. Source: `03-website-plan.md`, "What to remove or move to the docs"; `01-audit.md`, top problems 2 and 5. Director: approve the split between director and operator pages.
5. **Add "Words you need".** Use the glossary of at most 15 words, one short sentence per word. Source: `02-factory-story.md`, "Glossary"; `01-audit.md`, top problem 3. Director: no decision beyond copy approval.
6. **Add "What you see and decide".** Show each screen in director words, with the decision roles beside it. Source: `02-factory-story.md`, Steps 1 to 6; `03-website-plan.md`, page structure; `01-audit.md`, top problem 8. Director: confirm the retained decisions are correct.
7. **Add "Limits and trust".** State the benefit with its limits. Usage shows Claude Code session estimates. Factory delivery cost stays unknown. Source: `03-website-plan.md`, "Limits and trust"; `01-audit.md`, top problem 9. Director: approve the limit wording.
8. **Build the docs "Start here" path.** Nine short director pages, separate from the developer and operator pages. Source: `04-docs-and-video.md`, Part 1. Director: approve the docs structure.
9. **Produce the video.** A two to three minute concept with script, storyboard, and AI voice requirements. Source: `04-docs-and-video.md`, Part 2. Director: approve the budget, the AI voice choice, and publication.

## What each change needs from the Director

| Change | Director gives | Without it |
|---|---|---|
| First screen and home copy | Copy approval, then a publication decision | The site keeps the developer first screen. |
| Share Deck | Summary text approval | A director has no artefact to forward. |
| Fact fixes and new captures | Approval to publish seeded captures, with the label | The site keeps old screens at two ages. |
| Page split | Approval of the director and operator split | Install steps stay on the director read. |
| Words and decisions pages | Copy approval. Confirmation of the retained decisions | Words stay undefined and roles stay split across cards. |
| Limits and trust | Limit wording approval | A reader can over-read the benefit. |
| Docs Start here | Docs structure approval | The docs keep an operator first step. |
| Video | Budget, AI voice choice, publication approval | The share kit holds text only. |

## Open questions for the Director

The campaign leaves five questions open. Each question blocks the change named beside it.

1. Is a human director trial needed before publication? All reviews so far are agent readings. No human director has read the story, the plan, or the mockup. This question blocks a final publication claim.
2. When and how does the website change publish? The website repository deploys its whole root on a push to its main branch. A partial copy is not a safe publish. This question blocks change 1.
3. May public captures use seeded data, with the label on each image? Every fresh capture in this campaign uses seeded example states. This question blocks change 3.
4. The mobile first screen shows only two of six steps in the mockup layout. Is that acceptable, or must all six steps fit the first mobile screen? This question blocks final home-page approval.
5. Agent Mail stayed at "Loading participants..." in two agent checks. Investigate that state before any Mail capture or Mail claim. This question blocks any Mail image.

## Limits that stay in force

- Every screen state in this campaign is seeded example data. No capture shows live records.
- Factory delivery cost stays unknown. Usage shows Claude Code session estimates only.
- No trial measures director time saved. No document in this folder claims a saving.
- The mockup is a plan artifact. It is never deployed.
- Producing the docs pages and the video stays later work. This folder holds plans only.

## Approval note

This README grants no approval, retry, lease, merge, or publication authority. The Director approves the campaign plan under #745. Each change above then needs its own Director decision, as its line states.
