# Website and docs plan: Synth City at albiex.org

**Status: verified against the supplied mockup files; ready for independent review.**
An earlier checkpoint of this document was written before the approved website
mockup (called "v7d") and brand package v2 reached the team, and marked everything
mockup-dependent UNVERIFIED. Those files have since been supplied as a read-only
reference outside the repositories, identified by the bound Supervisor through
the route issue #792 requires and accepted by the team Leader as the approved
source handoff. Source identity (filenames and SHA-256 checksums, Appendix A) is
recorded separately from this document's own content checks, which verify the
plan against those identified files, file by file (section 4). The `v7b`
basenames inside the packet are filenames only; they do not imply a different
approval version from the Supervisor-identified v7d packet. Two limits remain, stated where they apply: the
mockup pages were inspected as source and their captures viewed directly, but no
browser rendering check was performed by the author — that is the Director preview
step in section 9 — and the brand guide is an internal draft whose trademark
clearance is still outstanding (section 10). Do not use any older mockup in the
repositories as a substitute for v7d: the older files describe a different design
round.

**What this document does.** It plans how the approved mockup becomes the published
website at `albiex.org`, how the public documentation is renamed, which product
pictures ("captures") must be retaken, where the site is deployed, and how the old
addresses redirect to the new ones. It does not authorize building the site, moving
repositories, or publishing anything.

**The one rule that governs everything below:** the new website goes live only after
the `albiexai` GitHub organisation exists and both repositories have been transferred
to it (campaign README, `docs/plans/2026-11-06-rename-synth-city/README.md:19`).

## 1. Decisions already made

These come from the parent issue #787 and the campaign README in this folder. This
plan does not revisit them.

| Decision | Value | Where it is recorded |
|---|---|---|
| Product name | Synth City, by Albiex | campaign `README.md:13-14` |
| GitHub organisation | `albiexai` | campaign `README.md:15` |
| Product repository | transferred to `albiexai/synth-city`, never recreated at the old address | campaign `README.md:16`, `README.md:24-25` |
| Website repository | transferred to `albiexai/synth-city-website` | campaign `README.md:17` |
| Domain | `albiex.org` | campaign `README.md:18` |
| Old domain | `claudedeck.org` redirects every path to `albiex.org` with 301 redirects | campaign `README.md:30` |
| Publication order | website only after the organisation exists and both repositories are transferred | campaign `README.md:19` |
| Visibility | the rename is public from the start | campaign `README.md:20` |

(Line numbers in this table are in `docs/plans/2026-11-06-rename-synth-city/README.md`
at the pinned product commit below.)

## 2. Sources, pinned commits, and how evidence is cited

Two repositories matter. Claims about them are cited as `file:line` at these exact
commits, measured on 2026-11-06:

| Label used below | Repository | Pinned commit |
|---|---|---|
| **[product]** | `adrirubio/claude-deck` (becomes `albiexai/synth-city`) | `c4daece7b300e2d07b884a75adf6ef8f99950389` |
| **[website]** | `adrirubio/claude-deck-website` (becomes `albiexai/synth-city-website`) | `0c35f391759633c774b7cc4ace5c52b96dd53d12` |
| **[mockup]** | Supplied v7d reference files, held outside both repositories (read-only) | SHA-256 checksums in Appendix A |
| **[brand]** | Supplied `brand-package-v2/` in the same reference set | `BRAND-GUIDE.md` checksum in Appendix A |

The [mockup] and [brand] files are cited by path and line, like repository files.
They are not copied into either repository by this plan: the mockup pages are
throwaway design sources, and the brand assets enter the repositories only during
implementation, through the asset mapping in section 4.4. Whoever implements this
plan needs authorized access to the same reference files at the checksums recorded
in Appendix A; if the checksums differ, the supplied copy is not the copy this plan
was verified against.

Counts below come from whole-repository `git grep` and `git ls-files` runs at those
commits, not from sampling. Appendix A lists the commands so anyone can reproduce
every number. If either repository head moves before implementation, the counts and
line numbers must be re-measured and this document updated; do not mix commits.

Words used in this document:

- **Mockup (v7d):** the approved design for the new website: three pages, a colour
  palette, a logo, and animated scenes. The Director holds the files.
- **Capture:** a picture of the product shown on the website or in the docs (a
  screenshot, logo, or icon).
- **Deploy:** publishing files so the public website serves them.
- **Generated docs:** documentation web pages built automatically from Markdown
  source files. People edit the Markdown, never the generated pages.

## 3. Where the website and docs live today

The public site at `claudedeck.org` is assembled from two repositories. The
documentation publishing playbook describes the split: the product repository owns
the Markdown content, the VitePress configuration and the build scripts, and the
website repository owns the landing page plus the generated documentation
([product] `DOCUMENTATION_PUBLISHING.md:7-10`). VitePress is the tool that turns the
Markdown files into web pages ([product] `DOCUMENTATION_PUBLISHING.md:12`).

| Part of today's site | Source a person edits | Where it is served from |
|---|---|---|
| Landing page | [website] `index.html` (749 lines) and `styles.css` (270 lines), plus pictures in `assets/` | website repo root, deployed as-is |
| Documentation at `/docs/` | [product] Markdown under `docs/`, built by VitePress | copied into [website] `docs/` (187 tracked files at the pin), then deployed |
| Deploy itself | [website] `.github/workflows/deploy.yml:3-5` runs on every push to `master` | Cloudflare Pages, project `claude-deck-website` ([website] `deploy.yml:21`) |

The normal publish path, step by step ([product] `DOCUMENTATION_PUBLISHING.md:16-23`):

```text
edit Markdown in product repo docs/
  -> VitePress build
  -> copy generated output to website repo docs/
  -> commit and push website repo master
  -> GitHub Actions runs Wrangler (Cloudflare's deploy tool)
  -> Cloudflare Pages serves the website
```

Three facts in that path matter for the rename:

1. **A push to the website `master` branch deploys production immediately**
   ([website] `README.md:20`, `README.md:44`). There is no separate "publish" button
   to forget — and none to protect you. Any rename work in the website repository
   must therefore happen on a branch, with the merge to `master` treated as the
   publication act itself.
2. **The generated `docs/` folder in the website repo is replaced wholesale on every
   docs publish.** The copy script deletes it and copies a fresh build in
   ([product] `scripts/deploy-docs.sh:19-20`). Nobody may hand-edit files there
   ([website] `README.md:24`). Every docs rename change belongs in the product
   repository source.
3. **The copy script hard-codes the website checkout's folder name.** It derives
   the product root from its own location, so the product folder may be named
   anything, but the neighbouring website folder must be exactly
   `claude-deck-website` ([product] `scripts/deploy-docs.sh:4-7`); the playbook
   additionally prescribes both folder names for readers setting up a machine
   (`DOCUMENTATION_PUBLISHING.md:27`). After the transfer and rename, a fresh
   website clone will naturally be named `synth-city-website`, and the script
   will fail until it is updated. Section 5 covers this.

## 4. The new website: three pages from the approved mockup

### 4.1 What was supplied, verified file by file

The supplied reference set (source identity and checksums in Appendix A) contains
exactly what #792 describes. The three pages are single-file HTML mockups with
inline CSS. Home and How it works also embed an inline copy of the street scene
script; Technical information has only its small menu script
([mockup] `v7d/technical-information.html:274-279`) and no scene. They are design
sources to port, not files to publish as-is.

| Supplied file | What it is (verified) |
|---|---|
| [mockup] `v7d/home-street-v7b.html` (892 lines) | Home page. Title "Albiex Synth City: Scale product velocity with self-directing AI teams" (line 4), hero headline at line 175; animated street hero plus two still scenes; Work capture; tool icons row |
| [mockup] `v7d/how-it-works.html` (955 lines) | How it works. Outer loop in four steps (lines 251–264), inner loop with animated street, stage links, and the loop diagram in wide and tall variants (line 287) |
| [mockup] `v7d/technical-information.html` (279 lines) | Technical information: requirements, install steps, harness connection, next-step docs links (headings at lines 216–261) |
| [mockup] `v7d/street-v7b.js` | The animated "signal works" hero as a reusable function, `mountStreet(svg, opts)`. Its header comment (lines 1–18) is the API contract: unique prefix per scene, still moments, caller-chosen crops, pause/play button, stage callback, and a no-animation mode |
| [mockup] `v7d/assets/brand/` | The three brand files the pages actually use: `albiex-logo-compact.svg`, `favicon.svg`, `apple-touch-icon.png` |
| [mockup] `v7d/assets/icons/` | Four third-party tool icons plus `icons-credits.json` recording source, CC0-1.0 licence, and trademark flags for each |
| [mockup] `v7d/assets/tour/` (plus one duplicate at `v7d/assets/work-active.png`) | Five seeded product captures: `overview.png`, `teams.png`, `work-active.png`, `work-merged.png`, `work-review.png` (section 6.1) |
| [brand] `brand-package-v2/` | Seven logo/icon SVGs plus `favicon.svg` (eight SVG files total), three production PNGs, `BRAND-GUIDE.md`, preview and QA files. The QA report records valid XML, globally unique ids, and only approved palette colours in every SVG (`QA-REPORT.txt:1-16`) |
| [brand] `brand-package-v2-brief.md` | The brief that produced v2, including why v1's violet/magenta look was replaced (line 9) and the Director's palette choice on 2026-11-06 (line 18) |

Verified against #792 point by point:

- **Three pages, named as in #792.** Navigation on every page is "How it works" and
  "Technical information" plus a GitHub link (for example [mockup]
  `v7d/home-street-v7b.html:166`). No fourth page exists in v7d; the earlier
  round's Quick tour is not part of this design (recorded under "Answered by the
  supplied sources" in section 10; no Quick tour decision remains open).
- **Transit enamel palette, with exact values.** The brand guide defines seven
  colours — Ink `#101A26`, Slate `#3D5A80`, Dusk `#5B7896`, Horizon `#E9B98A`,
  Signal vermilion `#E4572E`, Sodium `#F5C77A`, Paper `#F7F5F0` — each with a
  restricted job ([brand] `BRAND-GUIDE.md:13-21`), and rules that bind the port:
  vermilion is the sole accent, no violet/magenta/cyan/glow/neon, flat colours in
  artwork, and no Horizon arc in compact logos or icons
  (`BRAND-GUIDE.md:25-28`). The pages additionally use a separate website role
  system (human amber `#D97706`, AI teal `#0D9488`, steel, plus per-team colours);
  the guide explicitly reserves those for the website and forbids leaking them
  into brand artwork (`BRAND-GUIDE.md:31-38`). The port must keep the two systems
  apart: brand files stay palette-only, page components may use role colours.
- **Logo.** Pages use the compact lockup, `assets/brand/albiex-logo-compact.svg`,
  at 44 px in the header and 40 px in the footer, with alt text "Albiex Synth
  City" ([mockup] `v7d/home-street-v7b.html:165`, `:244`; same pattern on the
  other pages). That matches the guide's header sizing rule — 40 px minimum,
  height-based placement ([brand] `BRAND-GUIDE.md:46-47`, `:56`).
- **"Signal works" hero, agent diamonds, Verify.** The street scene moves three
  feature parcels, each escorted by one diamond-shaped agent, through four halls
  named Plan, Build, Review, Verify, then sends finished parcels back to GitHub by
  rail while the Director supervises by wire ([mockup] `v7d/street-v7b.js:1-7`;
  hall names at `v7d/street-v7b.js:53`). The home page mounts it three times — one animated hero with a
  pause/play button and two stills ([mockup] `v7d/home-street-v7b.html:880`,
  `:888`, `:890`) — and How it works mounts one animated scene plus two stills
  ([mockup] `v7d/how-it-works.html:941-944`). Reduced-motion readers get a still:
  the script checks `prefers-reduced-motion` and listens for changes
  ([mockup] `v7d/street-v7b.js:399`, `:605`). Every reader-visible stage label
  already says "Verify" — no visible Check-to-Verify correction is part of the
  port (steps and aria label at `v7d/home-street-v7b.html:195-196`, hall name at
  `:303`; How it works at `v7d/how-it-works.html:284-287`, `:376`). The word
  `check` survives only as an internal variable name in the script, which no
  reader sees and which does not establish visible wording.
- **Outer loop, inner loop, loop diagram.** The outer loop is four numbered steps
  (backlog, rosters, rules, autonomy) each ending in a "Your call" line
  ([mockup] `v7d/how-it-works.html:251-264`). The inner-loop diagram has wide
  (1200×460) and tall (400×1000) SVG variants with five stage nodes, forward
  arrows, three named send-back paths ("Changes requested", "A question about the
  plan", "More changes requested"), a dashed "next ready feature" return, and a
  "Your reserved decisions wait here" callout on Verify — all on one very long
  line ([mockup] `v7d/how-it-works.html:287`), with a full text description in
  `#loop-desc` on the same line for readers who cannot see the figure.
- **Technical claims spot-checked.** The page's minimums — Python 3.11+, Node.js
  22.12+ ([mockup] `v7d/technical-information.html:223`) — agree with the product's
  own installation guide ([product] `docs/guide/installation.md:11-12`). Its
  six-tool list (four icon tools plus Pi and Muse Code as text, line 238) matches
  the pinned product's current harness support — six harness cards
  ([product] `docs/features/harnesses.md:3`), Muse Code among them
  (`harnesses.md:7`, dedicated section at `:19-25`), and the six provider ids in
  code ([product] `frontend/src/types/agentTeams.ts:3`). Do not confuse that with
  the older public website, which still names only five tools and omits Muse
  Code ([website] `index.html:111`, `:349`). Its docs links are still
  placeholders (section 4.6).

Older material stays background only: the earlier approved build design
([product] `docs/superpowers/specs/2026-10-16-website-build-design.md:7`) and its
four page drafts predate v7d and must not be mixed into the port.

### 4.2 Astro port map

The target is Astro in the website repository: #792 names Astro, the supply note
for these files instructs planning the port into Astro pages, and the earlier
Director-approved build design specified Astro with static output, animated scenes
as components, and the generated `docs/` carried through unchanged ([product]
`docs/superpowers/specs/2026-10-16-website-build-design.md:22`, `:42`). No Astro
source exists in the website repository at its pin — its own README lists static
HTML as the stack ([website] `README.md:48-52`) and a whole-tree listing shows no
`package.json` or Astro configuration — so the first implementation step is that
design's foundation phase: create the Astro project on a preview branch, keep
serving `docs/` unchanged, and add the preview deploy — only then port the pages.

| Mockup source | Astro target | Port notes |
|---|---|---|
| Shared `<head>`, tokens, header, footer (near-identical in all three files; tokens at `home-street-v7b.html:10-13`) | One layout component + one shared stylesheet with the design tokens | Deduplicate: the three files repeat the same CSS. Tokens include the role colours and four font stacks (Newsreader, Hanken Grotesk, JetBrains Mono, Chakra Petch). Self-host the fonts: the mockup loads Google Fonts (`home-street-v7b.html:7-8`), but the approved build design requires self-hosted fonts and no external requests ([product] build design `:27`) |
| `v7d/home-street-v7b.html` | Home page (`/`) | Sections in mockup order; hero headline is the primary visual, not the logo ([brand] `BRAND-GUIDE.md:29`) |
| `v7d/how-it-works.html` | `/how-it-works/` | Keep outer-loop order, stage anchors (`#stage-plan` … `#stage-merged`, line 285), and the glossary |
| `v7d/technical-information.html` | `/technical-information/` | Wire every placeholder link to the renamed docs (section 4.6) |
| `v7d/street-v7b.js` (`mountStreet`) | One shared scene module/component used by all six mounts (home 3, How it works 3) | Planned extraction work, not existing reuse: neither animated page loads the standalone file (no script `src`); both embed their own inline copy. Extract those two copies — with the standalone file as the canonical source — into one shared module; keep each page's own menu initialization separate (Technical information's only script is that menu code). Preserve: unique prefixes, pause/play on animated mounts only, `animate:false` stills with their exact crops and still-moments, phone crop behaviour, and the reduced-motion path |
| Loop diagram (wide + tall SVG, `how-it-works.html:287`) | One diagram component rendering both variants | Extract from the single-line SVG into maintainable markup without changing geometry, labels, colours, or the `#loop-desc` text alternative |
| `v7d/assets/tour/*.png` | Website public assets, same placements as the mockup | `teams.png` and `overview.png` on How it works (lines 258, 264), `work-active.png` on home (line 205) and How it works (line 291); `work-merged.png` and `work-review.png` are supplied but unused in the mockup pages — place only if the Director's review asks, otherwise do not ship unused captures. Retakes per section 6.1 |
| `v7d/assets/icons/*.svg` + credits | Tool-icon row on home and Technical information | Keep `icons-credits.json` provenance with the assets (CC0-1.0 icon files; the logos themselves remain their owners' trademarks, as each page footer already notes) |
| `v7d/assets/brand/*` | Replaced by the full brand mapping in section 4.4 | The mockup's three files are a subset of the package |

The proposed clean Astro routes are `/`, `/how-it-works/`, and
`/technical-information/`. Be exact about their status: these are this plan's
port choice, derived from the navigation labels — they are **not** paths supplied
by the source, whose literal links are mockup filenames (`how-it-works.html`,
`technical-information.html`, and the stale `home-street-v6.html` for home;
section 4.6). The implementation team records the final route list in the website
repository; the redirect rules in section 8 assume these proposed routes plus the
unchanged `/docs/`, and must be re-checked if the Director's preview review
changes any route.

### 4.3 What happens to today's landing-page content

Nothing from today's single-page site carries over automatically. The three v7d
pages already contain their own hero, explanation, tool row, captures, and install
entry points, so the old page (title at [website] `index.html:6`, hero at
`index.html:100-101`, 23 old-name lines in `index.html` and 1 in `styles.css`) is
retired whole at cutover, not renamed in place. Three things must survive the
retirement in the new pages, and the mockup already provides anchors for each: the
GitHub entry point (nav and hero buttons, currently `href="#"` placeholders), the
install path (Technical information), and links into `/docs/` (the "Where to go
next" list, [mockup] `v7d/technical-information.html:261`, also placeholders).
Section 4.6 lists every placeholder that must be wired.

### 4.4 Brand asset mapping (brand package v2 → destinations)

The package supplies more than the mockup uses. Every supplied production asset has
a destination; test sheets (`PREVIEW.html`, `header-size-test.png`,
`favicon-size-test.png`, `BRAND-OVERVIEW.png`) are QA references and are never
shipped ([brand] `BRAND-GUIDE.md:80-82`).

| Brand asset | Destination | Notes |
|---|---|---|
| `albiex-logo-compact.svg` | Website header (44 px) and footer (40 px), as in the mockup | Light-background lockup; clear space per `BRAND-GUIDE.md:60` |
| `albiex-logo-compact-dark.svg` | Docs header | The docs theme is forced dark ([product] `docs/.vitepress/config.ts:6`), replacing `docs/public/logo-dark.png`; VitePress logo config changes from PNG to this SVG |
| `albiex-logo.svg`, `albiex-logo-dark.svg` | Social-share/large placements and any light/dark hero-adjacent use at 300 px+ | Only the full logos may carry the Horizon arc (`BRAND-GUIDE.md:18`) |
| `albiex-logo-stacked.svg` | Vertical placements (for example README or about surfaces) at 180 px+ | Light only; no dark stacked variant is supplied |
| `albiex-icon.svg`, `albiex-icon-mono.svg` | Standalone marks (app, README, partner slots) | Mono is Ink-only for single-colour contexts |
| `favicon.svg`, `favicon-32.png` | Website and docs favicons | Replaces [website] `favicon.ico` and [product] `docs/public/favicon.ico`; the SVG is optimised for 16/32 px, so no separate 16 px PNG is needed |
| `apple-touch-icon.png` (180×180) | Website and product touch icons | Replaces both current `apple-touch-icon.png` files |
| `icon-512.png` | App/README icon | New; product README can adopt it during the product rename |

Two product-side adaptations belong to the rename implementation campaign, not the
website build, and are recorded here so they are not lost: the app ships PNG logos
([product] `frontend/public/logo-dark.png`, `logo-light.png`) and PNG favicons at
16/32 px, while the brand package is SVG-first — the frontend asset references must
change to the supplied SVGs (or Director-approved rasters derived from them), and
the light-variant need maps to `albiex-logo-compact.svg`, the dark to
`albiex-logo-compact-dark.svg`.

### 4.5 Mockup defects the port must fix (do not copy blindly)

The mockup is a design source, not production code. Verified defects to fix during
the port, none of which change the design:

1. **Stale home links.** How it works and Technical information link their logos to
   `home-street-v6.html`, a file that does not exist in the supplied set (the home
   file is `home-street-v7b.html`): [mockup] `v7d/how-it-works.html:238`, `:317`,
   `v7d/technical-information.html:207`, `:268`. In Astro these become `/`.
2. **Placeholder links.** `href="#"` appears 7 times on home, 3 on How it works,
   and 16 on Technical information — including every GitHub button and every docs
   link on the Technical page (`technical-information.html:224`, `:232`, `:261`).
   Wire GitHub to the post-transfer repository and docs links to the renamed
   `/docs/` pages; the port is not done while any `href="#"` survives outside a
   deliberate same-page anchor.
3. **Duplicated code.** All three pages repeat the shared CSS. Home and How it
   works also repeat the street scene script inline (roughly 640 lines in each of
   those two pages); neither loads `street-v7b.js` by reference. Extract those
   two scene copies into one shared module and the CSS into one shared
   stylesheet (section 4.2); keep each page's menu initialization. Keeping the
   copies would guarantee drift.
4. **Duplicate capture file.** `assets/work-active.png` is byte-identical to
   `assets/tour/work-active.png` (same SHA-256, Appendix A). Ship one.
5. **External font loading.** Covered in section 4.2: self-host the four families
   instead of the Google Fonts links, per the approved build design.
6. **Confidentiality wording in brand sources is stale.** The guide and brief say
   to keep the name confidential until launch ([brand] `BRAND-GUIDE.md:3`), but
   the Director's campaign decision makes the rename public (campaign
   `README.md:20`); the current decision governs. What remains a real gate from
   the guide is separate: the assets "have not been trademark-cleared"
   (`BRAND-GUIDE.md:3`, `:68`), which joins the campaign's Phase 0 trademark
   search (campaign `README.md:53`) as a before-launch item (section 10).

### 4.6 Link map: every placeholder and draft route, with its destination

This is the complete wiring list promised in sections 4.1–4.3. Destinations in
the docs use the existing VitePress routes under the unchanged `/docs/` base
([product] `docs/.vitepress/config.ts:7`); each destination file exists at the
product pin. Do not port any source form in the middle column literally.

| Destination | Source occurrences ([mockup]) | Destination evidence ([product]) |
|---|---|---|
| `/` (proposed home route) | Home header/footer logos `href="#"` (`home-street-v7b.html:165`, `:244`); How it works and Technical logos `href="home-street-v6.html"` (absent file; `how-it-works.html:238`, `:317`, `technical-information.html:207`, `:268`) | Plan-proposed route (section 4.2) |
| `/how-it-works/` (proposed) | Nav/footer links `href="how-it-works.html"` on all three pages (for example `home-street-v7b.html:166`, `:245`) | Plan-proposed route; literal source form is the mockup filename |
| `/technical-information/` (proposed) | Nav/footer links `href="technical-information.html"` on all three pages (for example `home-street-v7b.html:166`) | Plan-proposed route; literal source form is the mockup filename |
| Product GitHub repository (post-transfer `albiexai/synth-city` address) | Nav "Open source on GitHub", GitHub pills, hero and closing buttons, footer nav — all `href="#"` (`home-street-v7b.html:166`, `:168`, `:179`, `:234`, `:245`; `how-it-works.html:239`, `:241`, `:318`; `technical-information.html:207` area nav, pill, `:268` footer) | Transfer target from section 1; until the transfer, the old repository address is the live one, and after it GitHub redirects bridge the change (section 8) — final pages link the new address directly |
| `/docs/` (docs home) | "Docs home" (`technical-information.html:261`) | `docs/index.md` |
| `/docs/guide/installation` | "installation guide" (`technical-information.html:224`), "Read the installation guide" (`:232`), "Installation guide" (`:261`) | `docs/guide/installation.md` |
| `/docs/guide/quick-start` | "Quick start" (`technical-information.html:261`) | `docs/guide/quick-start.md` |
| `/docs/features/harnesses` | "Read the harness guide" (`technical-information.html:241`), "Harness guide" (`:261`) | `docs/features/harnesses.md` |
| `/docs/features/agent-mail` | "Read the Agent Mail guide" (`technical-information.html:247`) | `docs/features/agent-mail.md` |
| `/docs/features/agent-bridge` | "Read the Agent Bridge guide" (`technical-information.html:247`) | `docs/features/agent-bridge.md` |
| `/docs/autonomy` | "Read the autonomy guide" (`technical-information.html:255`), "Autonomy guide" (`:261`) | `docs/autonomy.md`, sidebar link `/autonomy` at `docs/.vitepress/config.ts:39` |
| `/docs/features/agent-teams` | "Read the Teams guide" (`technical-information.html:255`), "Teams guide" (`:261`) | `docs/features/agent-teams.md` |

Same-page anchors in the mockup (for example hero buttons to `#street`, `#tour`,
`#start`) are deliberate in-page links, not placeholders; they port as the
equivalent section anchors on the Astro pages. The acceptance check is simple:
after the port, a search for `href="#"` and for `.html` page links in the built
output returns nothing outside deliberate same-page anchors.

## 5. The docs rename

The public documentation is renamed in its source, the product repository, and then
rebuilt and recopied through the normal path in section 3. Nobody edits the
generated copy in the website repository.

### 5.1 Scope, measured at the pin

The public build includes only part of the product `docs/` folder: the VitePress
configuration excludes `plans/**`, `superpowers/**`, and `deploy/**`
([product] `docs/.vitepress/config.ts:8-12`). What remains — the rename surface for
this section — is **56 Markdown files** (22 under `docs/api/`, 22 under
`docs/features/`, 9 under `docs/guide/`, 3 at the `docs/` root), plus the site-wide
assets in `docs/public/`. A narrow four-pattern search (`Claude Deck`,
`claude-deck`, `claude_deck`, `claudedeck.org`, case-insensitive) finds **69 lines
in 22 files**. That is a baseline, not the whole workload: the broader classified
searches below are what the docs rename must actually work through, in step with
the whole-repository inventory in #788 and the identifier decisions in #789. The
sets overlap, so they are never added together.

| Search set (public docs only) | Lines / files | How the rename treats it |
|---|---|---|
| Four-pattern baseline above | 69 / 22 | Product-name text to rename, except history and deliberate rename explanations |
| Bare `Deck` as a word (case-sensitive) | 151 / 27 | Includes every "Claude Deck" line plus the short product name used alone, for example "Start Deck…" ([product] `docs/guide/quick-start.md:3`). Classify line by line with #788's rules: product short name renames, ordinary English does not |
| `deck_` tool names | 24 / 8 | Runtime identifiers, for example the tool list at [product] `docs/features/agent-mail.md:71`. New prefix and alias period come from #789; during the window the docs must keep the old names working as documented aliases |
| `claude_registry` / `.claude-registry` paths | 10 / 5 | Runtime identifiers in install and API examples, for example [product] `docs/api/agent-bridge.md:103-104` and `docs/changelog.md:21`. Migrate per #789, keeping old-install instructions usable |
| `CLAUDE_DECK` environment names | 4 / 2 | Runtime identifiers; same #789 treatment (subset of the baseline set) |
| `Claude Code` / `claude-code` (third-party harness) | 90 / 30 | **Keep.** These name a real external product the agents run, not this product; never rename them mechanically |

On top of the page text, the shared header and footer (the frame every docs page
shares) carries the old name in specific configuration lines:

| What a reader sees | Source line to change |
|---|---|
| Browser tab and search title "Claude Deck" | [product] `docs/.vitepress/config.ts:4` |
| Site description | [product] `docs/.vitepress/config.ts:5` |
| Logo image in the docs header | [product] `docs/.vitepress/config.ts:18`, file [product] `docs/public/logo-dark.png` |
| Site title beside the logo | [product] `docs/.vitepress/config.ts:19` |
| Favicon | [product] `docs/.vitepress/config.ts:13-15`, file `docs/public/favicon.ico` |
| "Product source" nav link to the old GitHub address | [product] `docs/.vitepress/config.ts:26-27` |
| GitHub icon link and "edit this page" link pattern | [product] `docs/.vitepress/config.ts:111`, `config.ts:119` |
| Docs home hero name and source button | [product] `docs/index.md:4`, `docs/index.md:12-13` |
| Footer copyright line "Claude Deck Contributors" | [product] `docs/.vitepress/config.ts:125` |

The five operating-model diagrams in `docs/public/images/operating-model/` are text
inside SVG files, so they can be checked exactly: three of them contain visible
"Deck" labels (`factory.svg` 1, `hierarchy.svg` 1, `modes.svg` 3 visible labels at
lines 12, 23 and 48, plus a fourth source occurrence in a comment at line 20;
Appendix A). Those labels are part of the docs rename, not of the capture retakes in
section 6, because they are source files a person edits, not screenshots.

### 5.2 Order of work

1. **Wait for the vocabulary.** The exact new names for identifiers that appear in
   the docs (install commands, file paths, environment variables, `deck_` tools)
   are decided by the compatibility design in #789. Until it merges, docs-rename
   drafting must either use only the already-decided names from section 1
   ("Synth City", "Albiex", `albiex.org`, `albiexai/synth-city`) or mark identifier
   examples as provisional. Section 9 lists this as a hard reconciliation gate.
   The renamed docs must keep existing installs working through the
   Director-approved deprecation window: supported old identifier examples,
   documented compatibility aliases, old-install paths, and migration guidance
   approved by #789 stay in the docs, clearly marked as compatibility material —
   they are not rename leftovers. The campaign already requires old names and
   `deck_` aliases to keep working during the window (campaign `README.md:27-29`,
   `README.md:42`).
2. **Edit the source**: the 56 public Markdown files, the configuration lines in
   the table above, the SVG labels, and the logo/favicon files, replaced from the
   supplied brand package v2 per section 4.4.
3. **Fix the hard-coded website folder name before the transfer, or as part of
   it.** The publishing script hard-codes the neighbour folder name
   `claude-deck-website`
   ([product] `scripts/deploy-docs.sh:7`) and the playbook tells readers to clone
   `adrirubio/claude-deck` and `adrirubio/claude-deck-website` side by side
   ([product] `DOCUMENTATION_PUBLISHING.md:41-42`). The rename implementation must
   update the script, the playbook, and the website README's build instructions
   ([website] `README.md:26-29`) in the same change, or the first post-transfer
   docs publish will fail on a fresh machine.
4. **Rebuild and recopy** with the existing script, review the generated diff in
   the website repository as the playbook prescribes ([product]
   `DOCUMENTATION_PUBLISHING.md:85-93`), and record the new source commit in the
   website README, replacing the release-3.0.0 pin it carries today
   ([website] `README.md:27`).
5. **Publish only through the gate in section 9.** The regenerated website `docs/`
   commit goes to `master` only when publication is authorized, because that push
   deploys.

### 5.3 What does not change

- The `/docs/` URL prefix stays. It is configured in one place
  ([product] `docs/.vitepress/config.ts:7`) and every existing link, including the
  landing page's feature cards, assumes it. Keeping it means the redirect work in
  section 8 is a domain change, not a path redesign.
- Page URLs inside the docs stay unless a page is genuinely renamed for content
  reasons; a product rename alone is not a reason to break a bookmarked docs URL.
- History keeps the old name, in two different places. The three excluded
  directories (`docs/plans/`, `docs/superpowers/`, `docs/deploy/`) stay out of
  the public build entirely ([product] `docs/.vitepress/config.ts:8-12`). But
  `docs/changelog.md` is one of the 56 public files and is linked in the docs
  sidebar ([product] `docs/.vitepress/config.ts:46`), and the pinned website
  serves it as `docs/changelog.html`: its historical entries remain published
  under their historical names. Do not rewrite released changelog entries; only
  new entries use the new name.

## 6. Captures to retake

A capture must be retaken when a reader can see the old product name, old logo, or
old interface wording in it. Text inside screenshots cannot be searched, so this
list is built from where each picture is used and what it shows, and every item
must be visually checked once at retake time. Two timing facts govern the whole
section: captures of the product interface can only be retaken **after** the
renamed product exists (the implementation campaign that follows these plans),
because today the interface still titles itself "Claude Deck"
([product] `frontend/index.html:9`); and new captures are required to come from
the isolated test instance with synthetic example data, never from a live working
instance. That isolation is a requirement for the retakes, not a demonstrated fact
about every existing capture: the current website record documents synthetic
example records for its two showcase screenshots only ([website] `README.md:33`),
and a seeded-data banner on an image is not by itself proof of capture isolation.

### 6.1 Captures in the new design and in today's website repository

The new design does not reuse today's eight landing-page screenshots; it uses the
supplied tour captures. Used, duplicate, and unused supplied captures must be
treated differently. All five tour PNGs were visually checked for this plan; the
"Deck" wordings below are raster text baked into the images, not page captions.

| Supplied capture ([mockup] `v7d/assets/`) | Used where | Visible "Deck" text | Action |
|---|---|---|---|
| `tour/overview.png` | How it works, outer-loop step 4 (`how-it-works.html:264`) | Yes — "so Deck shows only the work it has seen" in the progress card | **Retake** from the renamed product |
| `tour/teams.png` | How it works, outer-loop step 2 (`how-it-works.html:258`) | None visible | Re-verify against the renamed interface at implementation; retake if any shown wording changed |
| `tour/work-active.png` | How it works inner loop (`how-it-works.html:291`) and, as the byte-identical duplicate `assets/work-active.png`, the home page (`home-street-v7b.html:205`) | None visible | Ship one copy only; same re-verification as above |
| `tour/work-merged.png` | Not referenced by any supplied page | None visible | Ship only if the Director's preview review adds a placement; otherwise leave unshipped |
| `tour/work-review.png` | Not referenced by any supplied page | Yes — "Deck record updated" in the detail card | **Retake before any use**; do not ship as supplied |

Today's eight website screenshots are all referenced from the current landing
page — two as the main showcase ([website] `index.html:263`, `index.html:272`) and
six in feature-card previews (`index.html:426`, `index.html:451`, `index.html:478`,
`index.html:506`, `index.html:533`, `index.html:560`). Their public paths
(`/assets/screenshot-*.png`) may be linked from outside this site, and section 8
promises every old path a same-path redirect. A redirect to a deleted file is a
broken promise, so the rule for cutover is: **retain an appropriately replaced
image at each supported old public path, or define an explicit compatibility
mapping for that path and test that the final response is a successful (200)
image.** Deleting an old capture path requires checking old external URLs, not
just current page references, and is not mandated by this plan. Renaming a capture
file (for example the `cc-bridge` name) is likewise not mandated here; filename
classification belongs to #788/#789, and any rename needs the same retained-route
treatment.

| File ([website] `assets/`) | Shows | Action |
|---|---|---|
| `screenshot-overview.png` | Overview page, synthetic records | Serve a retaken image at this same public path, or map it per the rule above; keep the synthetic-data caption practice from `index.html:276-278` |
| `screenshot-work.png` | Work page, synthetic issues | Same retained-route treatment |
| `screenshot-cc-bridge.png` | Agent Bridge sessions | Same retained-route treatment; no filename change is mandated by this plan |
| `screenshot-config.png` | Configuration editor | Same retained-route treatment |
| `screenshot-hooks.png` | Hooks & permissions | Same retained-route treatment |
| `screenshot-mcp.png` | MCP servers | Same retained-route treatment |
| `screenshot-sessions.png` | Session transcripts | Same retained-route treatment |
| `screenshot-usage.png` | Provider status & usage | Same retained-route treatment |
| `logo-dark.png`, `apple-touch-icon.png`, `favicon.ico` (repo root) | Old logo and icons | Replace from brand package v2; do not redraw by hand |

The website README currently records checksums for the two showcase screenshots
([website] `README.md:35-39`). The retake change must refresh that record (new
source commit, new checksums) so the provenance practice survives the rename.

### 6.2 Product repository captures (retake or replace when the product is renamed)

These feed the product README, the docs, and the app itself. They are listed here so
the implementation campaign budgets the retakes; the website build only consumes
the finished files.

| File ([product]) | Used for | Action |
|---|---|---|
| `screenshots/dashboard.png`, `screenshots/cc-bridge.png`, `screenshots/config.png`, `screenshots/mcp-servers.png`, `screenshots/sessions.png`, `screenshots/skills.png`, `screenshots/usage-tracking.png` | Product README showcase pictures (7 files, embedded at [product] `README.md:126`, `:131`, `:136`, `:141`) | Retake all 7 from the renamed interface on the isolated test instance |
| `frontend/public/logo-dark.png`, `frontend/public/logo-light.png` | Logo inside the app, selected by theme at [product] `frontend/src/components/layout/Header.tsx:42` | Brand package v2 supplies light/dark logos as SVG, not these PNG names (section 4.4): the implementation must either point the app at the supplied SVGs or derive approved rasters from them — conversion or asset-reference work, not a missing design decision |
| `frontend/public/favicon-16.png`, `frontend/public/favicon-32.png`, `frontend/public/apple-touch-icon.png` | App icons, linked at [product] `frontend/index.html:5-7` | Package supplies `favicon.svg`, `favicon-32.png`, `apple-touch-icon.png`, `icon-512.png` — no `favicon-16.png` or `.ico`. Update the icon links to the supplied set or derive the missing sizes from the supplied SVG |
| `docs/public/logo-dark.png`, `docs/public/favicon.ico` | Docs header logo and icon (section 5.1) | Replace per section 4.4 (`albiex-logo-compact-dark.svg`, `favicon.svg`); no `.ico` is supplied, so the docs icon link changes type |

### 6.3 What is not retaken

The roughly 120 plan and explainer images under [product] `docs/plans/` are history:
they document past design rounds, they are excluded from the public docs build
([product] `docs/.vitepress/config.ts:8-12`), and retaking them would falsify the
record. The same applies to old release screenshots kept with their releases. If
any of those images is ever reused on the new website, it becomes a new capture and
re-enters section 6.1 — reuse by copying is not allowed without a retake.

## 7. Deploy target

**Today,** the site deploys to Cloudflare Pages, project `claude-deck-website`,
whenever the website repository's `master` branch moves ([website]
`.github/workflows/deploy.yml:3-5`, deploy command at `deploy.yml:21`). The deploy
uses that repository's own GitHub secrets for Cloudflare (`deploy.yml:19-20`).
The normal workflow keeps Cloudflare credentials in GitHub Actions secrets, and no
token is needed on the publishing machine for that path ([product]
`DOCUMENTATION_PUBLISHING.md:105`). A direct Wrangler deployment from a machine is
a separate, specifically-needed option in the playbook
(`DOCUMENTATION_PUBLISHING.md:121-130`): it requires separate authorization and
authentication, and credentials must never be put in either repository or in shell
history. A pull-request check parses the current `index.html` and verifies that
its local `href`/`src` targets exist ([website]
`.github/workflows/check-pages.yml:24-44`); it does not validate rendered
behaviour, and it does not see image paths loaded by click handlers. The Astro
build must keep an equivalent check pointed at the built output of all three
pages, including handler-loaded assets.

**For Synth City,** the deploy target stays Cloudflare Pages — nothing in the
campaign decisions moves hosting — but four things around it change, and the
implementation plan must schedule them as separate, checkable steps:

1. **Domain attachment.** `albiex.org` is pointed at Cloudflare and attached to the
   Pages project only at cutover (campaign `README.md:52` plans the DNS move;
   section 9 fixes its position in the order). Director review before that uses a
   preview deployment (item 4 below), never the production address.
2. **Project and repository names.** The deploy command names the Pages project
   `claude-deck-website`, and the workflow lives in a repository that will be
   transferred and renamed. Whether the Pages project itself is renamed is a
   Cloudflare-side choice the transfer runbook (#790) must record; if it is
   renamed, `deploy.yml:21` and the playbook's copies of the command
   ([product] `DOCUMENTATION_PUBLISHING.md:102`, `DOCUMENTATION_PUBLISHING.md:127`)
   change in the same commit, and the GitHub secrets must be confirmed present in
   the transferred repository before the first post-transfer push. A push that
   deploys to the wrong project — or fails silently because secrets did not survive
   the transfer — is the main cutover risk in this section, and #790 owns the
   checklist that prevents it.
3. **Rollback is scoped, and each layer needs its own recovery.** A website
   `master` revert only recovers content when the workflow and Pages project it
   deploys through are unchanged and known-good; it cannot undo Cloudflare
   project, domain, or redirect changes. The existing practice also carries its
   own gate: because a `master` push deploys production, the revert push needs
   the same release-owner approval as a publication ([website] `README.md:46`,
   [product] `DOCUMENTATION_PUBLISHING.md:134`). The earlier build design instead
   names the previous Cloudflare deployment as the publication rollback
   ([product] `docs/superpowers/specs/2026-10-16-website-build-design.md:56`).
   This plan therefore requires #790 to specify, before cutover: the verified
   known-good deployment to return to, the infrastructure and redirect recovery
   steps, and who may authorize each one. Rehearsing a revert on a preview branch
   is useful practice; it does not prove production rollback works.
4. **A separate preview build and deploy must be created; it does not exist
   today.** The pinned production workflow triggers only on `master` and deploys
   the repository root ([website] `deploy.yml:3-5`, `:21`). The implementation
   adds a preview workflow on a named non-production branch that builds the Astro
   output (`dist/`) and deploys it to a non-production Pages target, following
   the concrete precedent in the earlier build design — a preview-branch
   workflow deploying `dist` to a branch preview address, with the workflow file
   living only on that branch so it cannot affect production ([product] build
   design `:31-33`, foundation at `:42`) — while preserving the production
   trigger untouched until the approved cutover. That precedent is a plan to
   build, not an existing capability. Access wording must stay exact: **an
   unlisted preview is public to anyone who knows its URL; use `noindex`, or
   obtain the owner's approval for access protection** (the two options and their
   costs are spelled out at build design `:35-38`; the earlier round's choice
   does not silently select the access option for this build).

No deploy of the new site happens under this plan. Building, transferring, and
publishing are separate authorized steps in later phases (campaign `README.md:64-68`).

## 8. Redirects

A redirect sends a visitor who asks for an old address to the new one. Three kinds
are needed, with different owners:

| Kind | Rule | Owner and evidence |
|---|---|---|
| Old domain to new domain | Every `claudedeck.org` path redirects (301, permanent) to the same path on `albiex.org`: `/` → `/`, `/docs/…` → `/docs/…`, assets likewise | Decided in campaign `README.md:30`; implemented at Cloudflare when DNS moves (`README.md:52`); retired only in a later cleanup phase (`README.md:71`) |
| Old GitHub addresses | `adrirubio/claude-deck` and `adrirubio/claude-deck-website` web, git, and API addresses redirect to the transferred repositories automatically **because the repositories are transferred, not recreated** | Campaign `README.md:24-25`; transfer mechanics and their checks belong to the runbook in #790 — this plan only depends on the result |
| Links inside our own pages | Our own pages and docs link directly to the new addresses instead of leaning on either redirect above | This plan: counts and locations below |

For the third kind, the measured scope at the pins is small and exact, counting
only actual repository paths (`adrirubio/claude-deck` or
`adrirubio/claude-deck-website`): 12 lines in 6 public docs files, plus the
configuration links in section 5.1, 5 lines across the product README and
publishing playbook, and 6 lines across the website landing page and README
(Appendix A). Each becomes `albiexai/synth-city` (or `-website`) during the rename
edits. Links to a person's GitHub profile are not repository addresses and are
preserved as author attribution — the "Built by Adrian" credits at [product]
`README.md:268` and [website] `index.html:662` keep pointing at the personal
profile; never rewrite a profile link into a repository link. Metadata that names
the old domain as the site's own address — today the landing page's share URL and
share image ([website] `index.html:18-19`) — becomes `albiex.org` in the new pages,
and the product README's website line ([product] `README.md:3`) follows.

Two cautions for whoever implements the first kind: neither repository contains a
redirect configuration file today (no `_redirects` file exists in either repo at
the pins), so the every-path rule will be new Cloudflare configuration, not an edit
to an existing file; and the redirect must preserve paths exactly, because the docs
keep their `/docs/` prefix and page URLs (section 5.3), which is what makes a pure
domain swap safe for bookmarks and search results.

## 9. Publication gate, cutover order, and unfinished prerequisites

### 9.1 The gate

The new website is published only after the `albiexai` organisation exists and both
repositories are transferred (campaign `README.md:19`). Concretely, that means no
merge of the new pages — and no regenerated docs commit — into the website
repository's `master` before the transfer is verified, because that merge is the
deployment (section 3, fact 1). Drafts live on the non-production preview branch
and preview deployment planned in section 7 item 4. An unlisted preview is public
to anyone who knows its URL; use `noindex`, or obtain the owner's approval for
access protection — do not describe an unlisted preview as private.

### 9.2 Cutover order for the website and docs parts

The full cutover belongs to the transfer runbook (#790) and the release plan
(#791); only the website-and-docs steps are sequenced here, in dependency order:

1. Three pages built on the preview branch with the separate preview deploy
   (section 7 item 4); captures retaken; Director reviews the preview and
   approves the exact build.
2. Docs renamed in the product source; publishing script and playbooks updated for
   the new repository names (section 5.2, step 3); generated docs rebuilt and the
   diff reviewed, still unmerged.
3. **Pre-transfer announcement (already decided; owned by #791).** Before any
   transfer, a pinned Discussion and a README banner on the old repository
   announce "Claude Deck is becoming Synth City" with the date and what changes
   (campaign `README.md:26`). This is a prerequisite, not a sequencing choice
   left to #791.
4. Organisation created; both repositories transferred and renamed; #790's
   post-transfer checks pass, including website-repo secrets and the Pages project
   (section 7).
5. `albiex.org` DNS pointed at Cloudflare; the every-path redirect from
   `claudedeck.org` prepared but not yet switched on.
6. **Production workflow cutover, then merge.** Merely merging an Astro project
   under the current workflow would deploy the repository root, not the built
   pages ([website] `deploy.yml:21`). The authorized cutover therefore updates
   the production workflow on `master` to build the same approved source the
   Director reviewed, carry the generated documentation into `dist/docs/` (the
   current generated `docs/` tree at the repository root, produced by the
   section 3 copy path), and deploy `dist/` to the verified production Pages
   project — the production workflow change the approved build design already
   requires at publication ([product] build design `:56`). Only then merge the
   preview branch to website `master`. Require evidence that the production
   output matches the reviewed preview artifact (same source commit and build
   inputs; compare the deployed file list and page checksums against the preview
   build). Transfer and publication gates from steps 3–5 remain in force. Live
   checks on `albiex.org`: home, How it works, Technical information, `/docs/`
   and one changed docs page.
7. `claudedeck.org` redirect switched on; old-address spot checks (`/`, a docs
   page, a screenshot asset) land on the same paths at `albiex.org` with a
   successful final response.
8. Launch announcement and release steps proceed under #791, after the live
   checks — distinct from the pre-transfer announcement in step 3. If any check
   in steps 6–7 fails: **stop**, and execute only the recovery that is authorized
   for the layer that failed (section 7 item 3 — content revert with its
   publication approval, previous known-good deployment, or #790's
   infrastructure/redirect recovery). Do not improvise fixes on the live branch.

### 9.3 Reconciliation with the unfinished plan documents

This plan was written first by direct instruction, while #788 (inventory), #789
(compatibility design), #790 (transfer runbook), and #791 (release and
announcement) are still open. That order does not waive their outputs. Before
implementation of this plan, each line below must be re-checked against the merged
document it names, and any conflict resolved in favour of the later, more specific
document:

| Prerequisite | What it can change here |
|---|---|
| #788 inventory of every old-name occurrence | The docs-rename scope in section 5.1 was measured independently for the public docs only; the inventory's whole-repository classification is the authority for anything outside that subset, and any public-docs file it classifies differently must be reconciled |
| #789 compatibility design | New identifier names used inside docs examples and install text (section 5.2, step 1); nothing in the docs may document an identifier under a name #789 did not choose |
| #790 transfer runbook | Secrets, Pages project, DNS and redirect mechanics and their verification steps (sections 7–9); if the runbook orders DNS or redirects differently, the runbook wins |
| #791 release and announcement | Release number and wording anywhere the site mentions versions, and launch-announcement timing after the live checks. The pre-transfer banner and pinned Discussion are **not** deferred to this reconciliation: they are already decided and sit at step 3 of section 9.2 |

## 10. Open questions for the Director

This plan does not decide any of these. Questions the supplied sources already
answered are recorded first so they are not re-asked; the rest still need the
Director.

**Answered by the supplied sources (no longer open):** the mockup and brand
package arrived as static reference files (section 4.1), so the port builds the
Astro source from them; the page list is the mockup's three pages, with no Quick
tour (reviving the earlier round's Quick tour copy would be a new Director
decision, not part of this port); Astro is required by #792 and specified by the
approved build design — any proposal to deviate from Astro is a change request
needing its own authority, and the supplied files' format alone cannot authorize
one; the package supplies light/dark full and compact SVG logos, and the missing
PNG/ICO slots are conversion or asset-reference work (sections 4.4, 6.2), not an
open design decision.

**Still open for the Director:**

1. **Trademark clearance before launch.** The brand guide is a supplied internal
   draft that states the assets have not been trademark-cleared and that a
   separate name/logo similarity check and legal review remain necessary
   ([brand] `BRAND-GUIDE.md:3`, `:64-68`, attributed here as a supplied claim,
   not as clearance this plan has performed). Together with the campaign's Phase
   0 trademark search (campaign `README.md:53`), this must close before launch.
   The guide's older confidentiality wording is superseded by the campaign's
   public-rename decision (campaign `README.md:20`) and creates no approval rule.
2. **Release number and deprecation window** (already open in #787): needed here
   where website or docs copy mentions versions, upgrade paths, or how long old
   identifiers remain documented (section 5.2). Site copy must not name a version
   before this is decided.
3. **Preview access choice.** An unlisted preview is public to anyone who knows
   its URL; use `noindex`, or obtain the owner's approval for access protection
   (section 7 item 4). The earlier round's choice does not select this build's
   option.
4. **Go-live approval.** The Director reviews the full draft on the preview
   deployment and approves the exact build before step 6 of section 9.2 —
   confirmed practice from the earlier round ([product]
   `docs/superpowers/specs/2026-10-16-website-build-design.md:54-56`), restated
   here so the approval is never assumed from a merge.

## 11. Acceptance checks for the implementation team

Whoever builds this can call the work done only when all of the following hold. The
reviewer should check them on the exact preview build that will be merged:

1. The built pages have been compared element by element against the
   Supervisor-identified v7d files at the checksums in Appendix A (palette and
   role-colour tokens, logo files and sizes, hero and diagram content and
   behaviour, page copy and order), and the comparison notes are recorded in the
   website repository. Every defect in section 4.5 is fixed: no stale
   `home-street-v6.html` links, no surviving `href="#"` placeholders, no
   duplicated scene code or duplicate capture file, fonts self-hosted.
2. Page design tokens and logo usage match the approved brand guidance (Transit
   enamel for brand artwork; website role colours only in page UI, per
   [brand] `BRAND-GUIDE.md:31-38`), and page copy and scene content match the
   approved mockup plus cited product facts. This is not a literal ban on every
   other colour or word: colours inside product captures and illustrations, and
   adjustments required for accessibility (for example contrast or focus
   treatment), are permitted where they serve the mockup's content and are noted
   in the comparison record. No unexplained "Claude Deck" branding remains
   outside deliberate rename explanations.
3. The public docs build from the renamed source with **no unexplained old
   branding** in the 56 public Markdown files. Explicitly allowed and tested
   instead of removed: documented compatibility aliases, supported old
   identifier examples, old-install paths, and migration guidance approved by
   #789, kept usable through the Director-approved deprecation window; historical
   changelog entries under their historical names; and third-party Claude Code
   references. The generated copy in the website repo matches a fresh build from
   the recorded source commit.
4. Every capture in sections 6.1–6.2 has been retaken or replaced as listed; each
   supported old public screenshot path either serves its replaced image or an
   approved compatibility mapping whose final response was tested successful;
   the website README's screenshot provenance record names the new source commit
   and checksums; no capture shows a live (non-synthetic) workspace.
5. The page-check workflow passes on the built output of all three pages
   (including handler-loaded assets); the separate preview workflow (section
   7 item 4) — not the production workflow — produced the exact build the
   Director approved, with no hand-edits after approval and the production
   `master` trigger preserved until cutover; and at cutover the updated
   production workflow (section 9.2 step 6) built that same approved source,
   carried the generated docs into `dist/docs/`, deployed `dist/` to the verified
   production project, and produced output evidenced to match the reviewed
   preview artifact.
6. The redirect checks in section 9.2 step 7 pass on the live domains, the
   pre-transfer announcement (step 3) demonstrably preceded the transfer, and
   the publication gate (section 9.1) was observed: no `master` merge before
   transfer verification.

## Appendix A. How the numbers in this document were measured

All commands ran on 2026-11-06 at the pinned commits in section 2. Run them in
checkouts actually at those pinned revisions — [product]
`c4daece7b300e2d07b884a75adf6ef8f99950389`, [website]
`0c35f391759633c774b7cc4ace5c52b96dd53d12` — not in whatever checkout is at hand:
check out the pinned revision first (for example `git checkout <pinned commit>`),
or select files with `git ls-tree -r --name-only <pinned commit>` and pass the
revision to `git grep` (`git grep … <pinned commit> -- <paths>`). Counts from any
other revision are a different measurement.

Supplied-source identity (SHA-256, measured 2026-11-06; filenames as supplied, no
private absolute paths):

| Supplied file | SHA-256 |
|---|---|
| `v7d/home-street-v7b.html` | `95a29c48b7e7e03f251bee80a2fdac7efcd9109170a391651332b36b2b9bb483` |
| `v7d/how-it-works.html` | `9616013b22029082642fc94eacfcae66ad44f189a6ebdc7a1e7db217ad19b4e0` |
| `v7d/technical-information.html` | `33c1dce6c56cab615ed7e6217840919f1d861ff0834ffc2203897afc3b972fd0` |
| `v7d/street-v7b.js` | `70bcff7bf1c363679d47f7d42ddfba9b1e1961bee13a325141e361ffa5e327be` |
| `brand-package-v2/BRAND-GUIDE.md` | `0cbec51cb6434aba6d4fca62d7667274bf31b05abfe939c129646f24e4612b30` |
| `v7d/assets/tour/overview.png` | `ff1b13917c072007e23e9226f778127eb677b2d4839de4ee505de27f176706a9` |
| `v7d/assets/tour/teams.png` | `c7b08710ae32f56d67e6c808c111d3e94f072277ee4a174d7d034643d8f7372c` |
| `v7d/assets/tour/work-active.png` = `v7d/assets/work-active.png` | `e3b6b841afb59a56d6681999521ce27a3cd8c2d077f44b910ce7511581a851f7` |
| `v7d/assets/tour/work-merged.png` | `aea52d7122c32d1fae099d73ad0d92b1c244cf5cac688c82f453a9166ddc96a9` |
| `v7d/assets/tour/work-review.png` | `09fcbedadcc11cffb5b091c3d7c528f9b440796680e16d588e2485777fb3c729` |

The three files in `v7d/assets/brand/` match their `brand-package-v2/`
counterparts byte for byte (verified by checksum comparison during this plan's
inspection; re-run `sha256sum` on both copies to reproduce).

```bash
# Reproducible public-docs file selection (used by every count below).
# Verified at the pin: no selected filename contains a space.
files=$(git ls-files docs | grep '\.md$' | grep -v -E '^docs/(plans|superpowers|deploy)/')
printf '%s\n' "$files" | wc -l        # 56 files (section 5.1)

# Narrow baseline (section 5.1): 69 lines in 22 files
git grep -I -i -c -E 'Claude Deck|claude-deck|claude_deck|claudedeck\.org' -- $files

# Broader classified sets (section 5.1); overlaps expected, never summed
git grep -I -c -E '\bDeck\b' -- $files                    # 151 lines, 27 files
git grep -I -c -E '\bdeck_[a-z]' -- $files                # 24 lines, 8 files
git grep -I -c -E 'claude_registry|\.claude-registry' -- $files   # 10 lines, 5 files
git grep -I -c -E 'CLAUDE_DECK' -- $files                 # 4 lines, 2 files
git grep -I -c -E 'Claude Code|claude-code' -- $files     # 90 lines, 30 files (keep)

# "Deck" occurrences inside the operating-model SVGs (section 5.1)
grep -o -i 'Claude Deck\|Deck' docs/public/images/operating-model/*.svg | sort | uniq -c
grep -n -i 'deck' docs/public/images/operating-model/modes.svg   # labels :12 :23 :48, comment :20

# Was any approved v7d source already in the product repo at the pin? Raw matches:
#   docs/plans/2026-11-06-rename-synth-city/README.md  (the campaign mention)
#   docs/plans/2026-10-15-director-website/style/index.html  (false positive: encoded data)
#   integrations/pi-agent-mail/package-lock.json  (false positive: integrity string)
# Classified result: no approved v7d source identified in either repository.
git grep -I -i -l -E 'v7d|Transit enamel|signal works|agent diamonds'

# Landing-page old-name lines (section 4.3) [website]: index.html 23, styles.css 1, README.md 7
git grep -I -i -c -E 'Claude Deck|claude-deck|claudedeck\.org' -- index.html styles.css README.md

# Transfer-sensitive repository-path links only (section 8); profile links excluded
git grep -I -i -c 'adrirubio/claude-deck' -- $files                  # [product] 12 lines, 6 files
git grep -I -i -c 'adrirubio/claude-deck' -- README.md DOCUMENTATION_PUBLISHING.md   # [product] 5 lines
git grep -I -i -c 'adrirubio/claude-deck' -- index.html README.md    # [website] 6 lines

# Capture and asset lists (section 6)
git ls-files screenshots frontend/public docs/public               # [product]
git ls-files assets                                                # [website] 10 files

# Redirect configuration today (section 8): no matches in either repository
git ls-files | grep -i '_redirects\|_headers'

# Supplied-source checks (section 4; run in the supplied reference set)
sha256sum v7d/home-street-v7b.html v7d/how-it-works.html \
  v7d/technical-information.html v7d/street-v7b.js brand-package-v2/BRAND-GUIDE.md
grep -n 'mountStreet(document' v7d/*.html        # six mounts, section 4.1
grep -o 'href="#"' v7d/*.html | cut -d: -f1 | sort | uniq -c   # placeholders: 7 home, 3 how, 16 technical (section 4.5)
```

Remaining limits, stated plainly: the mockup pages were verified as source and
the five tour captures by direct visual inspection; no browser motion or
accessibility trial was run by the author, and no deployed behaviour was tested.
Brand licensing and trademark statements are attributed supplied claims from the
brand guide, not clearance performed for this plan (section 10).
