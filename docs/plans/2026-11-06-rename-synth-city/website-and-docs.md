# Website and docs plan: Synth City at albiex.org

**Status: reviewable draft checkpoint, not a finished plan.** Everything that can be
checked against the two repositories today is written and cited below. Everything that
depends on the approved website mockup (called "v7d") is marked **UNVERIFIED**, because
the mockup files are not in either repository and have not reached this team yet. The
Director holds those files (issue #792). When they arrive, the marked sections must be
checked against them before anyone treats this document as complete. Do not use any
older mockup in the repositories as a substitute: the older files describe a different
design round.

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
3. **The copy script expects the two checkouts to be sibling folders named exactly
   `claude-deck` and `claude-deck-website`** ([product] `scripts/deploy-docs.sh:7`,
   `DOCUMENTATION_PUBLISHING.md:27`). After the transfer and rename, fresh clones
   will naturally be named `synth-city` and `synth-city-website`, and the script
   will fail until it is updated. Section 5 covers this.

## 4. The new website: three pages from the approved mockup

### 4.1 What the mockup is, and what we cannot yet check

Issue #792 describes the approved mockup as three pages — **home**, **How it works**,
and **Technical information** — with the **Transit enamel palette** (the approved
colour set), the **brand package v2 logo**, an animated **"signal works" hero**
(the large opening scene at the top of the home page) containing **agent diamonds**
(diamond-shaped markers for the AI agents) and a **Verify stage**, and a How it works
story told as an **outer loop and an inner loop with a loop diagram**.

**UNVERIFIED.** None of those files are in either repository. A whole-repository
search at the pinned product commit finds the mockup only as a mention — the campaign
plan item that created this work (campaign `README.md:62`). The website repository at
its pin contains the current live landing page, not the mockup. So this section does
two different jobs, and keeps them separate:

- It maps each mockup requirement, as #792 words it, to the place it must land and to
  the evidence that will prove it landed. That mapping is usable today.
- It does **not** state any colour value, logo file, animation timing, or diagram
  content. Those can only come from the v7d files. Any future draft that contains
  such values without citing the supplied files should be rejected in review.

A note on older material: the repositories contain an earlier approved website build
design with its own style and scenes ([product]
`docs/superpowers/specs/2026-10-16-website-build-design.md:7`) and page copy for
four pages including a Quick tour ([product]
`docs/plans/2026-10-15-director-website/pages/`). That round predates the rename and
the v7d mockup. It is useful background for technology choices (section 4.4) but it
is **not** the design source for Synth City, and its four-page list does not override
the three pages named in #792. If the Director wants the Quick tour page kept, that
is an open question in section 10, not something this plan decides.

### 4.2 Requirement-by-requirement port map

"Port" means rebuilding what the mockup shows as real website pages in the website
repository, keeping its look, words, and behaviour. Each row names where the
requirement lands, what replaces today's equivalent, and how a reviewer will check it
once the files exist.

| Mockup requirement (#792) | Lands on | Replaces today | Checked when v7d arrives by |
|---|---|---|---|
| Transit enamel palette | All three pages: shared colour definitions, then page styles | Current landing colours defined inline, e.g. background and accent hex values at [website] `index.html:33-44` and rules in `styles.css` | Comparing every colour token in the built pages against the palette file in the brand package; no other hex values present |
| Brand package v2 logo | Header of all pages; social-share image; favicon set | [website] `assets/logo-dark.png` used at `index.html:65` and as share image at `index.html:19`; `favicon.ico` at `index.html:11`; `assets/apple-touch-icon.png` at `index.html:12` | File-for-file match with the supplied logo files (names, sizes, dark/light variants); alt text reads "Synth City" |
| "Signal works" hero | Home page, top section | Static headline hero, [website] `index.html:84-144` | Scene content, motion, and still (reduced-motion) version match the mockup; headline names Synth City |
| Agent diamonds | Inside the hero scene, as the agent markers | Nothing equivalent exists today | Diamonds present with the same meaning, labels, and motion as the mockup; each diamond's label is readable without motion |
| Verify stage | Inside the hero scene, as one named stage of the work flow | Nothing equivalent exists today | Stage name, position in the flow, and description match the mockup; wording agrees with the product's own stage names in the docs |
| Outer loop / inner loop story | How it works page, main narrative | No such page exists today; today's landing page explains features in cards, e.g. [website] `index.html:282-288` | Page tells the same two-loop story in the same order; no extra loop or stage invented |
| Loop diagram | How it works page, central figure | Nothing equivalent exists today | Diagram structure, labels, and captions match the mockup file; a text alternative describes the same loops for readers who cannot see the figure |
| Technical information page | Third page: architecture, requirements, links into `/docs/` | Nothing equivalent; technical readers today go straight to `/docs/` ([website] `index.html:73`) | Page content matches the mockup outline; every technical claim traces to the renamed docs, not to new unsupported claims |

### 4.3 What happens to today's landing-page content

The current landing page is one long page: hero, value points, audience, screenshots,
feature cards that link into `/docs/`, and install instructions. Renaming it in place
would mean at least the title ([website] `index.html:6`), the description and share
metadata (`index.html:7`, `index.html:15-19`), the header logo and name
(`index.html:65-66`), the hero headline (`index.html:100-101`), and product name
mentions throughout — 23 old-name lines in `index.html` and 1 in `styles.css` at the
pin (Appendix A). But the mockup is a different design, not a re-skin of this page,
so the plan is:

1. Build the three mockup pages as the new site (section 4.2). Do not stretch the
   old single-page layout to fit them.
2. Carry over only what the mockup or the Director asks for: the install entry point,
   the GitHub link, and the links into `/docs/` must survive in some form, because
   readers and search results depend on them. The old page's GitHub links point at
   the pre-transfer address (7 `adrirubio` lines across [website] `index.html` and
   `README.md`); after the transfer they must point at `albiexai/synth-city`
   directly rather than relying on GitHub's redirect forever.
3. Keep `/docs/` serving at the same path throughout. The new pages link to it; the
   docs themselves are renamed in their source repository (section 5), not as part
   of the page build.

**UNVERIFIED** until the mockup arrives: exact page URLs (for example whether
How it works lives at `/how-it-works/`), the navigation labels, and which of today's
sections, if any, the mockup already absorbs. The implementation team must take
these from the supplied files and record the final URL list in the website
repository, because the redirect map in section 8 depends on it.

### 4.4 Technology for the new pages: an open decision with evidence

Issue #792 says to port the mockup "into the website repository's Astro pages".
Astro is a static-site builder: authors write page components, and the tool outputs
plain web files. **Today no Astro source exists in the website repository**: at the
pin it contains static HTML and CSS plus the generated docs (204 tracked files; no
`package.json`, no Astro configuration; its own README lists the stack as static
HTML with Tailwind via CDN, [website] `README.md:48-52`). So "the Astro pages" do not
exist yet to port into. There are two honest readings, and the Director (or the
mockup files themselves, if they arrive as an Astro project) must settle which one
applies:

| Option | What it means | Evidence for it | Cost and risk |
|---|---|---|---|
| **A. Adopt Astro in the website repo** | Create the Astro project the earlier build design already specified: Astro with static output in `dist/`, animated scenes as components, existing `docs/` carried through unchanged | The Director-approved build design chose exactly this stack and layout ([product] `docs/superpowers/specs/2026-10-16-website-build-design.md:22`, foundation phase at line 42), and #792's wording assumes Astro pages | A new build step in the deploy workflow (today it deploys the repo as-is, [website] `deploy.yml:21`); every existing safeguard (page checks) must be re-pointed at the build output |
| **B. Stay with static HTML/CSS/JS** | Hand-build the three pages the way the current landing page is built | Zero new tooling; the current deploy path needs no change | The animated hero and loop diagram must be hand-rolled; keeping three pages consistent without components is more error-prone, and it contradicts #792's Astro wording |

This plan records option A as the assumption that best fits the written sources, and
lists the confirmation as Director open question 3 (section 10). Whichever option is
chosen, two constraints from the earlier design round still describe good practice
and cost nothing to keep: build on a preview branch with a private-enough preview
URL first, because a merge to website `master` is publication ([product]
`docs/superpowers/specs/2026-10-16-website-build-design.md:14-15`), and keep serving
the generated docs at the same URLs during the build (same file, line 16). The
preview-branch pattern also fits the campaign's own record: draft first, Director
reviews, publish after the transfer gate (section 9).

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
assets in `docs/public/`. Within those 56 files, **69 lines in 22 files** still use
an old name (`Claude Deck`, `claude-deck`, `claude_deck`, or `claudedeck.org`;
Appendix A). That is the text-rename workload for the public docs. It is deliberately
smaller than the whole-repository count that the inventory in #788 will produce:
dated plans and other history keep their original names and stay out of the public
build.

On top of the page text, the site chrome (the frame every docs page shares) carries
the old name in specific configuration lines:

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

The five operating-model diagrams in `docs/public/images/operating-model/` are text
inside SVG files, so they can be checked exactly: three of them contain the word
"Deck" as a label (`factory.svg` 1, `hierarchy.svg` 1, `modes.svg` 4 occurrences;
Appendix A). Those labels are part of the docs rename, not of the capture retakes in
section 6, because they are source files a person edits, not screenshots.

### 5.2 Order of work

1. **Wait for the vocabulary.** The exact new names for identifiers that appear in
   the docs (install commands, file paths, environment variables) are decided by the
   compatibility design in #789. Until it merges, docs-rename drafting must either
   use only the already-decided names from section 1 ("Synth City", "Albiex",
   `albiex.org`, `albiexai/synth-city`) or mark identifier examples as provisional.
   Section 9 lists this as a hard reconciliation gate.
2. **Edit the source**: the 56 public Markdown files, the configuration lines in
   the table above, the SVG labels, and the logo/favicon files once brand package
   v2 supplies replacements.
3. **Fix the sibling-folder trap before the transfer, or as part of it.** The
   publishing script hard-codes the neighbour folder name `claude-deck-website`
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
- Dated plans, old release notes, and other history keep the old name. They are
  already excluded from the public build, so leaving them costs nothing and keeps
  the record honest.

## 6. Captures to retake

A capture must be retaken when a reader can see the old product name, old logo, or
old interface wording in it. Text inside screenshots cannot be searched, so this
list is built from where each picture is used and what it shows, and every item must
be eyeballed once at retake time. Two timing facts govern the whole section:
captures of the product interface can only be retaken **after** the renamed product
exists (the implementation campaign that follows these plans), because today the
interface still titles itself "Claude Deck" ([product] `frontend/index.html:9`);
and captures must come from the isolated test instance with synthetic example data,
the same practice the current website screenshots already document
([website] `README.md:33`) — never from a live working instance.

### 6.1 Website repository captures (all retake or replace)

All eight screenshots are referenced from the landing page — two as the main
showcase ([website] `index.html:263`, `index.html:272`) and six in feature-card
previews (`index.html:426`, `index.html:451`, `index.html:478`, `index.html:506`,
`index.html:533`, `index.html:560`). In the three-page design their placements
change (**UNVERIFIED**: which captures the mockup uses, and where, comes from the
v7d files), but any of them that survives needs a retake under the new name, and
any that does not survive must be deleted rather than left orphaned.

| File ([website] `assets/`) | Shows | Action |
|---|---|---|
| `screenshot-overview.png` | Overview page, synthetic records | Retake after product rename; keep the synthetic-data caption practice from `index.html:276-278` |
| `screenshot-work.png` | Work page, synthetic issues | Retake; same caption practice |
| `screenshot-cc-bridge.png` | Agent Bridge sessions | Retake if the new design keeps the feature preview; note the old "CC" filename also goes away with the rename |
| `screenshot-config.png` | Configuration editor | Retake if kept |
| `screenshot-hooks.png` | Hooks & permissions | Retake if kept |
| `screenshot-mcp.png` | MCP servers | Retake if kept |
| `screenshot-sessions.png` | Session transcripts | Retake if kept |
| `screenshot-usage.png` | Provider status & usage | Retake if kept |
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
| `screenshots/dashboard.png`, `screenshots/cc-bridge.png`, `screenshots/config.png`, `screenshots/mcp-servers.png`, `screenshots/sessions.png`, `screenshots/skills.png`, `screenshots/usage-tracking.png` | Product README showcase pictures (7 files) | Retake all 7 from the renamed interface on the isolated test instance |
| `frontend/public/logo-dark.png`, `frontend/public/logo-light.png` | Logo inside the app itself | Replace from brand package v2 (the app ships both variants; the package must supply both, or the gap is a Director question) |
| `frontend/public/favicon-16.png`, `frontend/public/favicon-32.png`, `frontend/public/apple-touch-icon.png` | App icons | Replace from brand package v2 |
| `docs/public/logo-dark.png`, `docs/public/favicon.ico` | Docs header logo and icon (section 5.1) | Replace from brand package v2 |

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
uses that repository's own GitHub secrets for Cloudflare (`deploy.yml:19-20`); the
playbook is explicit that no Cloudflare token belongs on a publisher's machine or in
either repository ([product] `DOCUMENTATION_PUBLISHING.md:105`,
`DOCUMENTATION_PUBLISHING.md:130`). A pull-request check already validates the
landing page's HTML and local links ([website] `.github/workflows/check-pages.yml`);
whatever replaces the landing page must keep an equivalent check, pointed at the
three new pages (and at build output instead of source files, if option A in
section 4.4 is chosen).

**For Synth City,** the deploy target stays Cloudflare Pages — nothing in the
campaign decisions moves hosting — but three things around it change, and the
implementation plan must schedule them as separate, checkable steps:

1. **Domain attachment.** `albiex.org` is pointed at Cloudflare and attached to the
   Pages project only at cutover (campaign `README.md:52` plans the DNS move;
   section 9 fixes its position in the order). The `pages.dev` preview addresses
   are used for Director review before that, never linked publicly.
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
3. **Rollback stays a revert.** The existing recovery practice — revert the website
   commit on `master` and let the same workflow republish the restored files
   ([product] `DOCUMENTATION_PUBLISHING.md:134`, [website] `README.md:46`) — works
   unchanged after the rename and should be rehearsed once on the preview branch
   before cutover day.

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

For the third kind, the measured scope at the pins is small and exact: 12 lines in
6 public docs files link to `adrirubio/claude-deck`, plus the configuration links in
section 5.1, 6 lines across the product README and publishing playbook, and 7 lines
across the website landing page and README (Appendix A). Each becomes
`albiexai/synth-city` (or `-website`) during the rename edits. Metadata that names
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
deployment (section 3, fact 1). Drafts live on a preview branch with an unlisted
preview address for the Director's review.

### 9.2 Cutover order for the website and docs parts

The full cutover belongs to the transfer runbook (#790) and the release plan
(#791); only the website-and-docs steps are sequenced here, in dependency order:

1. Three pages built on a preview branch; captures retaken; Director reviews the
   preview and approves the exact build.
2. Docs renamed in the product source; publishing script and playbooks updated for
   the new repository names (section 5.2, step 3); generated docs rebuilt and the
   diff reviewed, still unmerged.
3. Organisation created; both repositories transferred and renamed; #790's
   post-transfer checks pass, including website-repo secrets and the Pages project
   (section 7).
4. `albiex.org` DNS pointed at Cloudflare; the every-path redirect from
   `claudedeck.org` prepared but not yet switched on.
5. Preview branch merged to website `master` (this deploys), generated docs commit
   included; live checks on `albiex.org`: home, How it works, Technical
   information, `/docs/` and one changed docs page.
6. `claudedeck.org` redirect switched on; old-address spot checks (`/`, a docs
   page, a screenshot asset) land on the same paths at `albiex.org`.
7. Announcement and release steps proceed under #791. If any check in steps 5–6
   fails, revert the website `master` commit (section 7, rollback) and stop; do
   not improvise fixes on the live branch.

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
| #791 release and announcement | Release number and wording anywhere the site mentions versions; announcement timing relative to step 6 above; the README banner and pinned discussion that point readers to the new site |

## 10. Open questions for the Director

This plan does not decide any of these. Each needs the Director's answer (or the
supplied mockup files, where noted) before the affected work can finish:

1. **Supply of the v7d mockup and brand package v2.** The files themselves — three
   pages, palette, logo set — are the missing evidence for every UNVERIFIED mark in
   section 4. Which channel delivers them to the team, and in what form (static
   files, or a project the website build starts from)?
2. **Page list.** #792 names three pages. The earlier approved round also had a
   Quick tour page with finished copy ([product]
   `docs/plans/2026-10-15-director-website/pages/quick-tour.md`). Is Quick tour
   dropped, folded into How it works, or kept as a fourth page?
3. **Technology confirmation.** Astro in the website repository (option A,
   section 4.4), as the earlier approved design specified and #792 assumes — or
   stay with hand-written static files (option B)? If the mockup arrives as an
   Astro project, that answers this by itself.
4. **Logo variants.** The product ships dark and light logos
   ([product] `frontend/public/logo-dark.png`, `logo-light.png`); the website and
   docs today use only dark. Does brand package v2 supply both variants and the
   full icon set listed in section 6?
5. **Release number and deprecation window** (already open in #787): only needed
   here where website or docs copy mentions versions or upgrade paths; the site
   copy must not name a version before this is decided.
6. **Go-live approval.** The Director reviews the full draft on the preview address
   and approves the exact build before step 5 of section 9.2 — confirmed practice
   from the earlier round ([product]
   `docs/superpowers/specs/2026-10-16-website-build-design.md:54-56`), restated
   here so the approval is never assumed from a merge.

## 11. Acceptance checks for the implementation team

Whoever builds this can call the work done only when all of the following hold. The
reviewer should check them on the exact preview build that will be merged:

1. Every UNVERIFIED mark in section 4 has been replaced by a comparison against the
   supplied v7d files, and the comparison notes (palette tokens, logo files, hero
   and diagram behaviour) are recorded in the website repository.
2. The three pages contain no "Claude Deck", `claude-deck`, or `claudedeck.org`
   text except where the copy deliberately explains the rename ("formerly Claude
   Deck"), and no colour, logo, or wording that is absent from the brand package.
3. The public docs build from the renamed source with zero old-name lines in the 56
   public Markdown files outside deliberate rename explanations and history, and
   the generated copy in the website repo matches a fresh build from the recorded
   source commit.
4. Every capture in sections 6.1–6.2 has been retaken or replaced, or deleted with
   its references; the website README's screenshot provenance record names the new
   source commit and checksums; no capture shows a live (non-synthetic) workspace.
5. The page-check workflow passes on the new pages, and the deploy workflow on the
   preview branch produces the site the Director approved — same files, no
   hand-edits after approval.
6. The redirect checks in section 9.2 step 6 pass on the live domains, and the
   publication gate (section 9.1) was observed: no `master` merge before transfer
   verification.

## Appendix A. How the numbers in this document were measured

All commands ran on 2026-11-06 at the pinned commits in section 2. [product]
commands run in a `claude-deck` checkout; [website] commands in a
`claude-deck-website` checkout.

```bash
# Public docs surface (section 5.1): 56 files
git ls-files docs | grep '\.md$' | grep -v -E '^docs/(plans|superpowers|deploy)/' | wc -l

# Old-name lines in those files (section 5.1): 69 lines in 22 files
git grep -I -i -c -E 'Claude Deck|claude-deck|claude_deck|claudedeck\.org' -- <those 56 files>

# "Deck" labels inside the operating-model SVGs (section 5.1)
grep -o -i 'Claude Deck\|Deck' docs/public/images/operating-model/*.svg | sort | uniq -c

# Mockup presence check (section 4.1): only the campaign README matches
git grep -I -i -l -E 'v7d|Transit enamel|signal works|agent diamonds'

# Landing-page old-name lines (section 4.3) [website]: index.html 23, styles.css 1, README.md 7
git grep -I -i -c -E 'Claude Deck|claude-deck|claudedeck\.org' -- index.html styles.css README.md

# Transfer-sensitive GitHub links (section 8)
git grep -I -i -c 'adrirubio/claude-deck' -- <public docs files>   # [product] 12 lines, 6 files
git grep -I -i -c 'adrirubio' -- README.md DOCUMENTATION_PUBLISHING.md   # [product] 6 lines
git grep -I -i -c 'adrirubio' -- index.html README.md              # [website] 7 lines

# Capture and asset lists (section 6)
git ls-files screenshots frontend/public docs/public               # [product]
git ls-files assets                                                # [website] 10 files

# Redirect configuration today (section 8): no matches in either repository
git ls-files | grep -i '_redirects\|_headers'
```

Remaining source limit, stated plainly: the v7d mockup and brand package v2 files
were not available to this team when this draft was written, and no route to them
existed in the team's authorized context at first (later supply is being arranged
outside this document — see issue #792 for the current source status). Every claim
that depends on those files is marked UNVERIFIED above rather than guessed.
