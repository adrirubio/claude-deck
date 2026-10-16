# Director docs plan and video concept

For: issue #768 under parent issue #745. This revision uses `01-audit.md`, the revised `02-factory-story.md`, the revised `03-website-plan.md`, and both mockup pages on master.

This file plans two things. It plans the documentation for directors. It plans the product video concept. It produces neither one. Both stay later work.

Each claim names its evidence. A claim with no evidence does not enter the plan.

## Sources

- `01-audit.md` records the current docs, page by page, with limits.
- `02-factory-story.md` gives the one sentence, the three parts, the eight-step "How it works" layer with parallel tracks and several teams, the six top-level words, and the nine detail words.
- `03-website-plan.md` gives the website pages, the graphical home copy, the five animation concepts, the two big figures, and the share ways. `mockup/index.html` and `mockup/how-it-works.html` show the two pages.
- The existing docs live in `docs/guide/`, `docs/features/`, `docs/index.md`, and `docs/autonomy.md`.
- Issue #758 gives the Director's video direction and the chosen production approach. Seeded screen states from the audit serve only the closing-segment capture list. They are not live records and not human trials.

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
| 1 | What Deck is | New director page | The director learns the factory in two minutes | Opens with the story: backlog, AI team, finished work. The one sentence and the three short parts, with the five home pictures and the two big figures as still images. A link to "How it works" for the detail. |
| 2 | A first look at Overview | New director page | The director learns what needs a person | What "Needs you" means. Campaign progress in plain words. Which item waits for the director, and which waits for the team. |
| 3 | A first look at Work | New director page | The director learns who owns each item | One row explained: owner, state, waiting reason, pull request link. The four normal states and the attention exception. |
| 4 | A first look at Repositories and Teams | New director page | The director learns which backlog feeds which team | One scope explained in plain words. The roster, the named Leader, and the supervisor status. Repository count and work count. |
| 5 | A first look at Audit | New director page | The director learns what the ledger proves | Safe metrics in plain words. Coverage limits. The locked event list as an access gate, not a failure. Cost stays unknown. |
| 6 | A first look at Agent Mail | New director page | The director learns how the team coordinates | What Agent Mail holds: durable participants, structured mailboxes, context requests, and handoffs. Mail reads stay protected. This page uses words and a diagram. It holds no screen capture. |
| 7 | A first look at Harnesses | New director page | The director learns which agent tools Deck can set up | What a harness is, in one sentence. The six agent tools by name. Setup and support in plain words. Account, model, and session readiness stay unknown here. Operator setup stays on the operator path. |
| 8 | The decisions that are yours | New director page | The director learns the retained decisions | Goal and backlog order. Publication, budgets, models, security stops. The Leader approves agent plans inside those limits. Human review follows repository policy. |
| 9 | Words you need | New director page | The director learns the story words | The six top-level words first, then the nine "How it works" words, one short sentence per word. Each word links to the page that uses it. |
| 10 | Limits and trust | New director page | The director learns what Deck does not promise | Local running and operator setup. Seeded example data. Locked Audit events. Usage session estimates beside unknown factory cost. No measured time saving. |
| 11 | Share Deck from the docs | New director page | The director briefs a peer from the docs | The link, the one-page summary, and the video. Each item stands alone. |

Evidence for the screen claims: `01-audit.md` records Overview with "Needs you" and campaign progress, Work with owners and waiting reasons, Teams with the roster and the named Leader, Repositories with enablement apart from intake, and Audit with safe metrics and locked events. `02-factory-story.md` gives the retained decisions. The glossary comes from the story: six top-level words, then nine detail words.

Screen limits that the pages must print:

- The Agent Mail introduction rests on `docs/features/agent-mail.md`. That page describes durable participants, structured mailboxes, and protected Mail reads. The page holds no screen capture. The only observed screen state stayed at participant loading. Evidence: `01-audit.md` records that state as an open observation limit. It proves no Mail failure and no docs defect. Add a capture only when a supported coordination state exists to show.
- The Harnesses introduction keeps the readiness limit in its first lines. The screen shows setup and support. Account, model, and session readiness stay unknown without a separate check. Evidence: `docs/features/harnesses.md`. Tool setup itself stays on the operator path.

### The "How it works" docs page

The detail follows the backlog through eight steps, then explains parallel tracks and several teams. It lives on a separate "How it works" page, linked from Start here and the technical docs, placed after "What Deck is". The page carries the eight steps, the decision at each step, the nine detail words, and the retell. It is the docs twin of the website's second page in `03-website-plan.md`, and it links onward to `docs/guide/operating-model.md` and the feature pages for depth.

Evidence: the revised story marks its eight-step layer "read this on the second page". `03-website-plan.md` gives the website the same split. The docs keep that split so a director meets the same shape in both places.

### What changes in the existing docs

| Page | Change | Reason |
|---|---|---|
| `docs/index.md` (docs home) | Add a Start here block at the top, before the operator actions | The hero and first action suit an operator today. Evidence: `01-audit.md` docs home finding. |
| `docs/guide/index.md` | Add the director path as the first next step. Keep the dense definition below it | A director gets no short briefing path today. Evidence: `01-audit.md` guide finding. |
| `docs/guide/operating-model.md` | Keep the content. Add a plain summary at the top and link it from Start here | The page defines the factory and the roles. It needs revision for a director, not creation. Evidence: `01-audit.md` operating model finding. |
| `docs/guide/quick-start.md` | Move it under For operators. No director page links to it as a first step | Its first step is a shell command. Evidence: `01-audit.md` quick start finding. |
| `docs/features/dashboard.md`, `work.md`, `repositories.md`, `agent-teams.md` | Add one director line at the top of each: what the screen shows, and which decision it supports. Keep the operator depth below | The pages name counts and filters before the decision. Evidence: `01-audit.md` feature findings. |
| `docs/features/agent-mail.md` | Link it from the new Agent Mail introduction. Add no capture and no director rewrite | The introduction rests on this page text. The loading observation is a product limit, not a docs defect. Evidence: `01-audit.md` Agent Mail finding. |
| `docs/features/harnesses.md` | Link it from the new Harnesses introduction. Keep setup depth and the readiness limit on the operator path | The page supports setup claims only. Evidence: `docs/features/harnesses.md`. |
| `docs/features/usage.md` | Add one director line: Usage shows estimates for one supported agent tool's sessions. Factory delivery cost stays unknown | The split prevents a false cost claim. Evidence: `02-factory-story.md` cost line and `docs/features/usage.md`. |
| `docs/autonomy.md` | Keep on the operator path. No director page sends a reader here first | The opening suits an operator and the setup needs a host token. Evidence: `01-audit.md` autonomy finding. |
| Sidebar in `docs/.vitepress/config.ts` | Add a Start here group for directors at the top of the guide sidebar. Keep Guide and Features below it | The sidebar links the operating model today but gives no director entry. Evidence: `docs/.vitepress/config.ts` guide sidebar and `01-audit.md`. |

### Docs rules

- Each director page defines its words on first use, or links to Words you need.
- Each director page states its limit on the same page. No page hides a limit in another path.
- No director page starts with a command, a token, or a setting.
- Operator pages keep their depth. This plan moves entry points. It deletes no operator content.

## Part 2. The video concept

Producing the video is later work. This part gives the concept, the narration script, the animation storyboard, the music brief with its Suno prompt, the voice brief, the closing segment, and the production approach.

Director direction (issue #758): the video explains the story, not how Deck is implemented. Screens change, so a video built on screenshots would date. The audience is non-technical product people. The style is very engaging: much animation and many transitions, warm narration, high-beat music. **Screens rule: no Deck screen appears outside the short closing segment in the last few seconds.** That segment is self-contained, so it can be replaced or cut without re-editing the rest.

### Audience and message

Audience: a non-technical product person who has never seen Deck, and the peer they forward the video to. Technical readers go to the technical documentation instead.

Message: you shape the feature backlog, Deck's AI team builds and checks the work, and the key decisions stay with you.

Length: about 2 minutes 34 seconds of story (scenes below), plus an optional closing segment of at most 10 seconds and a 4-second end card. The longest version is 2:48, inside two to three minutes with or without the closing segment.

The narration claims no measured delivery, no time saving, and no delivery cost. Evidence: `02-factory-story.md` keeps those limits, and `docs/guide/factory-audit-and-metrics.md:57` and `:96-97` keep delivery cost and human time savings unmeasured.

### Narration script

Natural, warm spoken English. Read it aloud at the pace in the voice brief (about 140 words per minute). The word count of each scene fits its window with hold time to spare (timing table below). The script uses no developer words. The same banned-word check as the home copy runs on it (see "Checks" under Production approach).

**Opening, 0:00–0:18.** "You know what you want to build next. Deck gives those ideas an AI team, while you decide what matters."

**The backlog, 0:18–0:42.** "Start with the features you want to build. Give each one a clear result, then put them in priority order. That is your backlog. You decide what belongs there and what is ready for the team."

**Meet the team, 0:42–1:08.** "The Leader organises the work and approves the plans. Members build the features. Other team members review the results, so the person who builds a change is not its independent reviewer."

**Finished work, 1:08–1:32.** "The team returns work for you to assess, with a record of what happened. You can see what is finished, what still needs attention, and where that record has gaps."

**You stay in charge, 1:32–1:58.** "And through it all, the decisions that matter stay with you. The goals. The priorities. The budget. And what gets published. The team handles the routine problems inside the limits you set — and anything reserved for you waits for you."

**Honest limits, 1:58–2:22.** "Deck runs on your own computer, and someone needs to set it up. The full cost of delivering a feature is not yet measured. Neither is the time it might save you."

**Closing line, 2:22–2:34.** "Your backlog. Your AI team. Finished work — with you in charge. That is Deck."

Timing check, at about 140 words per minute. Every scene window covers its speech and leaves hold time for the picture.

| Scene | Window | Words | Speech | Hold |
|---|---|---|---|---|
| Opening | 0:00–0:18 (18s) | 20 | 8.6s | 9.4s |
| The backlog | 0:18–0:42 (24s) | 36 | 15.4s | 8.6s |
| Meet the team | 0:42–1:08 (26s) | 31 | 13.3s | 12.7s |
| Finished work | 1:08–1:32 (24s) | 30 | 12.9s | 11.1s |
| You stay in charge | 1:32–1:58 (26s) | 41 | 17.6s | 8.4s |
| Honest limits | 1:58–2:22 (24s) | 32 | 13.7s | 10.3s |
| Closing line | 2:22–2:34 (12s) | 15 | 6.4s | 5.6s |
| **Total** | **154s** | **205** | **87.9s** | **66.1s** |

Evidence for the script: the closing line and the three middle scenes restate the revised story's three parts and "Why it matters" in spoken form. "The Leader organises the work and approves the plans" keeps the accepted roles (owner proposes on the detail page; Leader approves). The limits scene restates local running and the unmeasured-cost limits from `02-factory-story.md`.

### Animation storyboard

Every scene except the closing segment is an animated concept picture. No scene shows a Deck screen, a screen label, or product UI. The scenes are the website's React scene components (see `03-website-plan.md`, Technology and build), rendered here at video size. That includes the two big home figures: the hierarchy of roles carries Scene 3, and the factory figure carries the zoomed-out Scenes 6 and 7. The story arc is: backlog, then parallel lanes, then many teams. Each scene stays self-contained: one idea.

| Scene | Time | What the viewer sees | Motion and transition | One idea it teaches |
|---|---|---|---|---|
| 1. Opening | 0:00 | A soft pile of feature cards. The Deck name settles above them. | Let the cards settle as the opening sentence ends. Hold until the next scene. | Every team has a list. Deck gives it a team. |
| 2. The backlog | 0:18 | The #757 backlog animation: three feature cards settling into order, first to third. | Cards lift and settle in turn. The top card glows gently on "ready for the team". | You shape and order the list. |
| 3. Meet the team — parallel lanes | 0:42 | The hierarchy figure builds first (Director, Leader, the two stacks), then the parallel-lanes scene: cards split into lanes; in each lane an owner drafts a plan, the Leader approves, the owner builds, a reviewer checks. Several lanes move at once. | Cards travel their lanes with small offsets, timed to the narration. | Members check their work. Someone else independently reviews it. |
| 4. Finished work | 1:08 | Finished items land on the "finished" shelf beside their record, one record line drawn dashed. | Check mark draws in. Record lines appear. The dashed gap line pulses once, calmly. | Work returns with its record, gaps shown. |
| 5. You stay in charge | 1:32 | The decision animation: work travels and stops at the closed "You decide" gate. The Director's moments (ready, publish) light up. | The work stops at the closed gate while the narrator says "waits for you". A separate approval cue then opens the gate. Approval never comes from elapsed time alone. | The key decisions stay yours. |
| 6. Honest limits | 1:58 | The view begins to pull back to the factory figure, boundary and all: this team is one of several in one Deck, each with its own backlog (the many-teams scene), drawn quieter. A small house outline marks "your own computer". A dotted line marks "not measured yet". | Motion slows. Music drops under the words. | Local running. Unmeasured cost, stated plainly. |
| 7. Closing line | 2:22 | Zoomed out: several teams side by side, each with its list, lanes, and finished shelf. End card with the Deck name. | The wide view settles. Hold for the last line. | Backlog, team, finished work — with you in charge. |
| 8. Closing segment (optional) | after 2:34, at most 10s | The only screens in the video. See its own section below. | Separate sequence. Swappable or cuttable. | A short look at the real product, labeled as examples. |

Transitions: match cuts on the moving card between Scenes 2, 3, and 4, so one piece of work seems to travel. A soft fade into Scene 6 (the quiet scene) and out to the end card. No whip pans, no text flying at the viewer: the energy comes from the music and the steady motion, not from tricks.

### The closing segment (the only screens)

Length: at most 10 seconds, after the closing line and before the end card. The end card holds 4 seconds. With the montage the total is at most 2:48 (154s story + 10s montage + 4s end card). Without it, 2:38. Both versions stay under three minutes. Optional: the video is complete without it.

What it may show: a short "see it in action" montage of real Deck screens, using seeded captures from the `03-website-plan.md` screenshot list (Overview, Work with the All filter, Teams). Every capture carries the seeded-data label: "Example data — seeded screens. Not live records." No Audit event rows (locked gate), no Agent Mail capture (loading limit), no Usage total as cost proof.

How it is cut out: Keep Scenes 1-7 and their audio fixed. Give the optional montage its own music bed and edit boundaries. The same end card follows either version. To refresh it, swap the captures in that sequence and re-render. To remove it, drop the sequence and its music bed and re-render.

Narration over it: none. Music only, so cutting it never cuts a sentence.

### Music brief

Job: carry the energy the calm pictures do not. High beat, warm, forward-moving. No lyrics anywhere: words under narration fight the narrator.

- Tempo and energy: about 118–124 BPM. Bright and confident, never frantic.
- Shape: gentle intro under the opening, builds through the backlog, energetic but spacious under the team narration, settles into a warm, lighter groove at finished work, drops low and warm under "Honest limits", then a short bright rise for the closing line and end card.
- Level: always under the narration. The mix ducks the music whenever the voice speaks. The limits scene sits lowest.
- Length: generate about 3 minutes, then trim or loop-extend to the final cut (2:34 plus closing segment and end card).

Ready-to-paste Suno prompt. The Director generates the track in Suno's app from this text. Suno settings: Instrumental ON. No lyrics field beyond the section tags below.

Style text (paste into Style):

```text
Uplifting instrumental corporate pop, 122 BPM, warm and confident, bright piano chords, clean electric guitar arpeggios, soft synth pads, steady pop drums with handclaps, light strings in the lift, optimistic forward motion, polished product-video feel. No vocals, no lyrics, no choir, no harsh distortion, no drops with heavy bass, no minor-key drama.
```

Structure text (paste into Lyrics, instrumental mode). Times match the scenes; extend or trim sections in Suno to fit the final narration timing.

```text
[Intro — soft piano and pads, gentle pulse, 0:00-0:18]
[Build — drums enter, guitar arpeggios, growing energy, 0:18-0:42]
[Drop — full band but spacious, ducked below the voice, handclaps light, 0:42-1:08]
[Groove — warm, lighter groove, settles down, 1:08-1:32]
[Build — rising again, strings enter, 1:32-1:58]
[Break — sparse piano, low and calm, space for voice, 1:58-2:22]
[Lift — bright short rise, full but clean, 2:22-2:34]
[Outro — warm resolve, end-card hold, fade]
```

Settings and fit: instrumental, target about 3 minutes. Generate two or three takes and keep the best. If a section runs long or short against the final narration timestamps, use Suno's extend/trim on that section, or let the editor loop the Groove section. Keep the Break under the limits scene: if the generated Break is busy, regenerate with "sparse, minimal" added to the style.

Two alternative style prompts, so the Director can choose:

- Calmer: "Warm acoustic instrumental, 104 BPM, gentle and trustworthy, fingerpicked acoustic guitar, soft piano, light brushed drums, subtle strings, calm product-story feel. No vocals, no lyrics, no electronic drops, no harsh sounds."
- More energetic: "Energetic instrumental indie electronic, 128 BPM, bright and driving, pulsing synths, punchy clean drums, plucked bass, sparkling arpeggios, launch-video energy. No vocals, no lyrics, no dubstep drops, no distortion, no dark mood."

Commercial use: whether the generated track may be used commercially depends on the Suno plan's terms. The Director checks the current terms for their plan before publication, and keeps the generation receipt with the project files. This plan does not state Suno's terms.

### Voice brief

The narrator is an AI voice. The video credits say so. The Director picks the voice.

- Tone: warm, friendly, and clear — a good colleague explaining over coffee. Confident on the story, gentle on the limits, never salesy. No excitement words beyond the script. Smile in the voice, not hype.
- Pace: about 140 words per minute, with a breath at each scene change. Slower on the decision list ("The goals. The priorities. The budget.") and on the limits. Word timestamps from the voice render drive the scene timing, so generate the voice first, then lock the cuts.
- Pronunciation: Deck — "deck", one syllable. Leader — "the Leader", stress on "lead". Reviewer — plain. Backlog — "BACK-log". Do not spell out abbreviations: the script holds none.
- Rules: read every limit line in full, at the same warmth as the claims. One voice for the whole video. The voice reads the approved script only — no ad-libbed benefits.

### Production approach

The Director chose this approach. This section records it with its reasons.

- **Video as code, with Remotion.** A Deck team renders the website's React scene components to MP4 with Remotion. The same components run on the Astro site and in the video — one scene library, two outputs — so the website and the video tell the story with the same pictures. Code gives exact, repeatable edits: a word, a timing, or a colour changes in one place and re-renders.
- **Narration with ElevenLabs.** The Director picks the voice. Its word timestamps drive the scene timing, so cuts land on sentences, not guesses.
- **Music with Suno.** The Director generates the track in Suno's app from the prompt above, chooses among takes and the two alternative styles, and hands the file to the render.
- **Optional texture clips only.** Short AI-generated atmosphere clips (for example Veo or Runway) may add texture where a scene needs it — a soft background drift, never a product claim, never a fake screen.
- **Swappable closing sequence.** The closing segment is its own sequence. Swap its captures or cut it, then re-render. The story scenes never change when screens change — which is the point of the screens rule.

Why not the other ways:

- We chose code so the same artwork can appear on the website and in the video, with precise edits to words, colours, and timing. That is the project's reason for Remotion over whole-film text-to-video or template tools for this film.
- A custom layout lets us reuse these animations without depending on a template library.
- We want the viewer to focus on the backlog, team, and result, so this film uses illustrated ideas rather than an on-screen presenter.

Check first, before production money is spent: the commercial-use licence terms of Remotion, ElevenLabs, and Suno, for the exact plans the Director will use. Record the answers with the project. This plan names the check; it does not state any tool's terms.

Checks for this concept (run on the draft, and again on the final storyboard):

- Screens rule: read every storyboard row. Outside the closing segment, each row must name an animation concept, never a Deck screen. In the storyboard, screen words appear only in the rule statement itself and in the closing-segment row.
- Narration words: run the home-copy banned-word check on the script text — `grep -Eio 'github|\bprs?\b|pull requests?|\bissues?\b|\bci\b|\bmerg[a-z]*|\bbranch[a-z]*|\blabel[a-z]*'` — and require no matches.
- Timing: count each scene's words, divide by the voice pace (about 140 per minute), and require speech time below the scene window. The table above records this check.

Producing the video stays later work. The first step is a 20-second prototype under a separate issue. It proves the render path, the voice timing, and the music fit before the full film is built.

## What this plan does not promise

This plan does not produce the docs pages or the video. Both stay later work, after the Director approves this plan under the parent issue.

This plan does not promise that seeded screens prove live value. Each shot and page carries its seeded-data limit.

This plan does not promise a human verdict. The Director reviewed the earlier plan and requested these revisions. Agents checked the revised artifacts. No separate human comprehension trial is recorded.

This plan keeps factory delivery cost unknown and claims no time saving. Evidence: `docs/guide/factory-audit-and-metrics.md` and `02-factory-story.md`.
