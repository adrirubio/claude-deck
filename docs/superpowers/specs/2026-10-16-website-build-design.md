# Website build: a draft site on a preview URL

Date: 2026-10-16. Status: approved by the Director on 2026-10-16, with the decisions below.

## Goal

Build the new Deck website described in the approved plan (`docs/plans/2026-10-15-director-website/`, #745) in the chosen style (`style/`, option C "Floor"), as a **production-like draft on a private-enough preview URL**. The Director reviews the draft. Nothing is published to the live site until the Director approves it.

The animations must be top quality. The build therefore starts with the scenes, which the Director approves one by one, before the pages are assembled.

## Where the work happens

- **Repository:** `adrirubio/claude-deck-website`, the repository of the live site.
- **Branch:** `preview/website-v2`. Nothing is merged into `master` until the Director approves publication.
- **Live site:** unchanged during the build. Its deploy (`deploy.yml`, on push to `master`) is not touched until publication.
- **Docs:** the repository also serves the generated VitePress docs under `docs/`. The new build keeps serving them unchanged at the same URLs. Rebuilding the docs (the docs plan in `04`) is separate later work.

## Technology

As recorded in `03-website-plan.md`, "Technology and build":

- **Astro** for the site. Static output in `dist/`; only `dist/` is deployed. Animated scenes are React islands.
- **GSAP** with ScrollTrigger, DrawSVG, MorphSVG and SplitText for motion. Scroll drives each story.
- **Isometric SVG drawn in code** for the illustrations, from one small projection library (the one in the style frame, made into a typed module).
- **Lenis** for smooth scrolling; the **View Transitions API** between pages.
- **One React scene library**, used by the site now and by the Remotion video later (#760).
- **Fonts:** Instrument Serif and Instrument Sans (OFL), self-hosted from the build. No requests to font or analytics services.

## The preview URL

A new workflow on the preview branch builds the site and runs `wrangler pages deploy dist --project-name=claude-deck-website --branch=preview-website-v2`. Cloudflare Pages then serves it at a branch preview URL (`https://preview-website-v2.claude-deck-website.pages.dev`).

The workflow file lives only on the preview branch, so it cannot affect the live deploy. It uses the repository's existing Cloudflare secrets.

**A preview URL is public by default** (anyone with the address can open it). Two options, for the Director:

- **A. Unlisted (recommended for speed):** the address is not linked anywhere and pages carry `noindex`. Anyone who learns the address can see the draft.
- **B. Protected:** turn on Cloudflare Access for preview deployments, so only the Director's account can open them. This needs a one-time setting in the Cloudflare dashboard by the account owner.

## Phases

1. **Foundation.** Create the Astro project on the preview branch, carry the existing `docs/` through to `dist/docs/` unchanged, add the preview workflow and a page-check job (HTML, local links, no external requests, no "Claude", no "backlog" on the home page). Deliverable: a near-empty site live on the preview URL, the docs reachable as today.

2. **Scenes, one by one, on a gallery page** (`/scenes`, not linked from the site):
   - **The factory from outside:** the Director and an AI helper with GitHub, the Director with Deck, ready features flowing into a factory with several AI teams, finished work flowing back.
   - **Inside the factory:** parallel lanes, one feature colour and cap shape per lane.
   - **The hierarchy of roles:** people, AI agents and systems.
   - **The factory figure:** the boundary, what is inside and outside it.
   - **Several teams in one Deck.**

   For each scene: a written storyboard (what the viewer sees, motion, timing, easing, the one idea it teaches), the scroll-driven animation, the still version for reduced motion, and a **short screen recording** sent to the Director. The Director approves each scene or asks for another round. No scene enters a page before approval.

3. **Pages:** Home, How it works, Quick tour, Technical information, with the approved copy and every decision recorded on #745 and in the plan's `README.md` (plurals; "features" not "backlog" on the home page; "Quick tour"; "Technical information"; the main button "Take the quick tour"; AI and human roles clear; the product called only "Deck"; seeded screenshots labelled).

4. **Quality pass:** desktop, tablet and mobile; keyboard and screen-reader checks; reduced motion; 60 fps measured on each scene; no layout shift; Lighthouse above 95 on each page; no external requests. Findings are fixed before the Director's review.

5. **The Director's review of the full draft** on the preview URL, with as many rounds as it takes.

6. **Publication, only after the Director's approval:** update `deploy.yml` on `master` to build and deploy `dist/`, merge the preview branch, and confirm the live site and the docs. A rollback is the previous deployment in Cloudflare Pages.

## Who does the work

- **The Supervisor (an AI agent)** builds the scenes and the motion, as the Director decided (#745, question 5), and leads the quality pass.
- **The website-plan team** (Leader, researcher, critic) writes the page copy and the critic reviews each page, in the same way as the plan campaign.

## Rules that carry over

- The product is called only "Deck"; no "Claude" on the site.
- No private launch configuration in any file or message.
- No publication without the Director's approval.
- Seeded example data only, labelled on each image.

## The Director's decisions (2026-10-16)

1. **Preview access: A, unlisted.** Pages carry `noindex`, and the address is not linked anywhere.
2. **Pages: the website-plan team** writes the page copy and C1 reviews it, as in the plan campaign. The Supervisor builds the scenes, the motion and the site, and leads the quality pass.
3. **Docs stay as they are** in this build. The docs rework is later work.

## Out of scope

The video (#760, it reuses the scenes later), the docs rework, the rename of the project, and changes to the Deck product.
