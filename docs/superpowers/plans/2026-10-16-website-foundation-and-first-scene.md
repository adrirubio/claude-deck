# Website foundation and the first scene: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a new Astro site on the branch `preview/website-v2` of `adrirubio/claude-deck-website`, live on an unlisted Cloudflare Pages preview URL, with the existing docs served unchanged, automatic page checks, a typed isometric scene library, and the first scene, "the factory from outside", on an unlinked gallery page, with a screen recording for the Director.

**Architecture:** Astro builds static pages into `dist/`. The existing generated docs move to `public/docs/` and pass through to `dist/docs/` byte for byte. Scenes are React islands drawn as isometric SVG from one pure projection module, animated with GSAP ScrollTrigger, with a still version under reduced motion. A workflow that exists only on the preview branch builds, checks and deploys `dist/` to a branch preview URL.

**Tech stack:** Node 24, Astro 7.4, @astrojs/react 7.1, React 19, GSAP 3.15 (ScrollTrigger, DrawSVGPlugin), Lenis 1.3, Vitest 5, Playwright, Wrangler 4 (through `cloudflare/wrangler-action@v3`), @fontsource/instrument-serif and @fontsource/instrument-sans.

**Spec:** `docs/superpowers/specs/2026-10-16-website-build-design.md` (in `adrirubio/claude-deck`). Style: `docs/plans/2026-10-15-director-website/style/` (its `source.html` holds the reference isometric code). Copy and decisions: `docs/plans/2026-10-15-director-website/README.md`, "Decisions after approval".

## Global Constraints

- Work only on the branch `preview/website-v2` of `adrirubio/claude-deck-website`. Never push to `master`. Never change `.github/workflows/deploy.yml` or `check-pages.yml`.
- The live site is untouched until the Director approves publication.
- The docs are served unchanged at the same URLs (`/docs/...`).
- Preview access is unlisted: every page carries `<meta name="robots" content="noindex, nofollow">`, and `dist/robots.txt` disallows everything. Nothing links to the preview address.
- The product is called only "Deck". No "Claude" anywhere in the new pages and scenes (the generated docs under `docs/` are excluded from this check until the docs rework).
- No "backlog" on the home page.
- No requests to any other origin: fonts are self-hosted from the build; no analytics, no CDNs.
- Colour roles: people amber `#E3962B`; AI agents verdigris `#1E8C76` with top `#5FC1A9`; systems steel `#9DAEB6` and graphite `#1C2A31`; background fog `#ECEFF1`. Feature colours with AI cap shapes: blue `#2E7DD7` cube, violet `#8E5BD8` pyramid, rose `#D0577B` cylinder.
- Type: Instrument Serif (headlines), Instrument Sans (text).
- Every scene has a still version under `prefers-reduced-motion: reduce` that shows the scene's final state.
- No private launch configuration in any file, commit or message.

## Review Focus

1. **A docs page loses its styles or scripts after the move** (absolute `/docs/assets/...` paths): every file under the old `docs/` must be in `dist/docs/` with the same bytes, and a docs page must load with no 404. Test: `tests/docs-passthrough.test.mjs` (Task 2) and the docs check in `tests/e2e/site.spec.ts` (Task 4).
2. **A preview deploy is reachable from a search engine or a link:** `noindex` on every HTML page, including the gallery, and `robots.txt` disallow. Test: `check-dist` rule `noindex` (Task 3).
3. **A scene draws over its labels or clips at narrow widths:** the scene's viewBox is fitted to its content after the fonts load, and the page has no horizontal overflow at 390 px. Test: `tests/e2e/scenes.spec.ts` "no overflow at 390 px" (Task 6).
4. **Reduced motion still animates or shows a half-built scene:** under `reduce`, no GSAP timeline is created and every element is at its final position. Test: `tests/e2e/scenes.spec.ts` "reduced motion shows the final state" (Task 6).
5. **The preview workflow deploys a build that failed the checks:** the deploy step runs only after `npm run check` passes. Test: the workflow order is asserted in `tests/workflow.test.mjs` (Task 5).

---

### Task 1: The Astro project on the preview branch

**Files:**
- Create: `package.json`, `astro.config.mjs`, `tsconfig.json`, `src/layouts/Base.astro`, `src/styles/tokens.css`, `src/pages/index.astro`, `public/robots.txt`
- Move: `assets/` → `public/assets/`, `favicon.ico` → `public/favicon.ico`
- Keep for now: the old `index.html` and `styles.css` move to `legacy/` (reference only; not built)

**Interfaces:**
- Produces: `Base.astro` props `{ title: string; description?: string }`; CSS custom properties `--fog --graphite --steel --ai --ai-top --human --feat-blue --feat-violet --feat-rose`; font families `"Instrument Serif"` and `"Instrument Sans"`.

- [ ] **Step 1: Clone and branch**

```bash
cd /home/juan/work/repos/adrirubio
git clone https://github.com/adrirubio/claude-deck-website.git
cd claude-deck-website && git checkout -b preview/website-v2
```

- [ ] **Step 2: Create `package.json`**

```json
{
  "name": "deck-website",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "astro dev",
    "build": "astro build",
    "check": "node scripts/check-dist.mjs dist",
    "test": "vitest run",
    "e2e": "playwright test"
  }
}
```

Then install exact versions:

```bash
npm install astro@7.4.0 @astrojs/react@7.1.0 react@19 react-dom@19 gsap@3.15.0 lenis@1.3.27 @fontsource/instrument-serif @fontsource/instrument-sans
npm install -D vitest@5.0.5 @playwright/test typescript
npx playwright install chromium
```

- [ ] **Step 3: `astro.config.mjs`**

```js
import { defineConfig } from 'astro/config'
import react from '@astrojs/react'

export default defineConfig({
  output: 'static',
  integrations: [react()],
  build: { format: 'directory' },
})
```

Check the Astro 7 configuration reference before changing these keys; Astro 7 is newer than some references.

- [ ] **Step 4: Move the static files and the old page**

```bash
mkdir -p public legacy
git mv assets public/assets
git mv favicon.ico public/favicon.ico
git mv index.html legacy/index.html
git mv styles.css legacy/styles.css
printf 'User-agent: *\nDisallow: /\n' > public/robots.txt
```

- [ ] **Step 5: `src/styles/tokens.css`**

```css
@import '@fontsource/instrument-serif/400.css';
@import '@fontsource/instrument-serif/400-italic.css';
@import '@fontsource/instrument-sans/400.css';
@import '@fontsource/instrument-sans/500.css';
@import '@fontsource/instrument-sans/600.css';

:root {
  --fog: #ECEFF1; --graphite: #1C2A31; --steel: #9DAEB6; --muted: #56666E;
  --ai: #1E8C76; --ai-top: #5FC1A9; --human: #E3962B;
  --feat-blue: #2E7DD7; --feat-violet: #8E5BD8; --feat-rose: #D0577B;
}
*, *::before, *::after { box-sizing: border-box }
html, body { margin: 0 }
body { background: var(--fog); color: var(--graphite); font-family: "Instrument Sans", system-ui, sans-serif; font-size: 18px; line-height: 1.55 }
h1, h2 { font-family: "Instrument Serif", serif; font-weight: 400; letter-spacing: -.015em }
:focus-visible { outline: 2px solid var(--ai); outline-offset: 3px; border-radius: 4px }
```

- [ ] **Step 6: `src/layouts/Base.astro`**

```astro
---
import '../styles/tokens.css'
interface Props { title: string; description?: string }
const { title, description = '' } = Astro.props
---
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="robots" content="noindex, nofollow" />
    <title>{title}</title>
    {description && <meta name="description" content={description} />}
    <link rel="icon" href="/favicon.ico" />
  </head>
  <body><slot /></body>
</html>
```

- [ ] **Step 7: A placeholder home page `src/pages/index.astro`**

```astro
---
import Base from '../layouts/Base.astro'
---
<Base title="Deck">
  <main style="max-width:1240px;margin:0 auto;padding:64px 40px">
    <h1 style="font-size:72px;line-height:.95;margin:0">Your features.<br />Your AI teams.<br />Finished products.</h1>
    <p>Draft site in progress.</p>
  </main>
</Base>
```

- [ ] **Step 8: Build**

Run: `npm run build`
Expected: `dist/index.html`, `dist/robots.txt`, `dist/assets/…`, `dist/favicon.ico`; the HTML contains `noindex, nofollow` and the two font families load from `/_astro/…` (same origin).

- [ ] **Step 9: Commit**

```bash
git add -A && git commit -m "feat(site): start the Astro site on the preview branch"
```

### Task 2: The docs pass through unchanged

**Files:**
- Move: `docs/` → `public/docs/`
- Create: `tests/docs-passthrough.test.mjs`

**Interfaces:**
- Consumes: Task 1's build.
- Produces: `dist/docs/**` identical to the old `docs/**`.

- [ ] **Step 1: Write the failing test**

```js
// tests/docs-passthrough.test.mjs
import { createHash } from 'node:crypto'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { execSync } from 'node:child_process'
import { expect, test } from 'vitest'

function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    return statSync(path).isDirectory() ? files(path) : [path]
  })
}
const hash = (p) => createHash('sha256').update(readFileSync(p)).digest('hex')

test('every file of the old docs is in dist/docs with the same bytes', () => {
  // The baseline is the docs tree on master, before the move.
  const ref = execSync('git ls-tree -r --name-only origin/master docs').toString().trim().split('\n')
  expect(ref.length).toBeGreaterThan(10)
  for (const path of ref) {
    const blob = execSync(`git show origin/master:${path}`)
    const want = createHash('sha256').update(blob).digest('hex')
    expect(hash(join('dist', path)), path).toBe(want)
  }
})

test('dist/docs has no file the old docs did not have', () => {
  const ref = new Set(execSync('git ls-tree -r --name-only origin/master docs').toString().trim().split('\n'))
  for (const p of files('dist/docs')) expect(ref.has(relative('dist', p)), p).toBe(true)
})
```

- [ ] **Step 2: Run it before the move**

Run: `npm run build && npx vitest run tests/docs-passthrough.test.mjs`
Expected: FAIL (no `dist/docs`).

- [ ] **Step 3: Move the docs**

```bash
git mv docs public/docs
```

- [ ] **Step 4: Run the test again**

Run: `npm run build && npx vitest run tests/docs-passthrough.test.mjs`
Expected: PASS, both tests.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(site): serve the generated docs unchanged from dist/docs"
```

### Task 3: Page checks on the build

**Files:**
- Create: `scripts/check-dist.mjs`, `tests/check-dist.test.mjs`, `tests/fixtures/check-dist/{good,bad}/…`

**Interfaces:**
- Produces: `checkDist(root: string): { file: string, rule: string, detail: string }[]` (exported), and the CLI `node scripts/check-dist.mjs <root>` that prints each finding and exits 1 if there are any.
- Rules (the docs under `<root>/docs/` are skipped by every rule except `local-link`):
  - `noindex`: every HTML page has `<meta name="robots" content="noindex, nofollow">`.
  - `robots`: `<root>/robots.txt` contains `Disallow: /`.
  - `local-link`: every `href`/`src` without a scheme resolves to a file in `<root>` (a path ending in `/` resolves to `index.html`).
  - `external-request`: no `src=`, `<link rel="stylesheet|preload|icon" href=>` or CSS `url()` points to another origin (plain `<a href>` links to other sites are allowed).
  - `no-claude`: no "claude" (case-insensitive) in any HTML, CSS or JS file outside `docs/`.
  - `no-backlog-home`: no "backlog" (case-insensitive) in the visible text of `<root>/index.html`.

- [ ] **Step 1: Write the fixtures and the failing tests**

```js
// tests/check-dist.test.mjs
import { mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { beforeEach, expect, test } from 'vitest'
import { checkDist } from '../scripts/check-dist.mjs'

const root = 'tests/.tmp-dist'
const page = (body, head = '<meta name="robots" content="noindex, nofollow">') =>
  `<!doctype html><html><head>${head}</head><body>${body}</body></html>`
function write(path, text) { mkdirSync(join(root, path, '..'), { recursive: true }); writeFileSync(join(root, path), text) }
beforeEach(() => { rmSync(root, { recursive: true, force: true }); write('robots.txt', 'User-agent: *\nDisallow: /\n') })
const rules = () => checkDist(root).map((f) => f.rule).sort()

test('a clean build has no findings', () => {
  write('index.html', page('<a href="/how/">How</a><img src="/a.png">'))
  write('how/index.html', page('Hello')); write('a.png', 'x')
  expect(checkDist(root)).toEqual([])
})
test('a page without noindex is found', () => { write('index.html', page('x', '')); expect(rules()).toEqual(['noindex']) })
test('a robots.txt that allows crawling is found', () => { write('index.html', page('x')); write('robots.txt', 'User-agent: *\n'); expect(rules()).toEqual(['robots']) })
test('a broken local link is found', () => { write('index.html', page('<a href="/missing/">x</a>')); expect(rules()).toEqual(['local-link']) })
test('an external script, stylesheet or CSS url is found, an outbound link is not', () => {
  write('index.html', page('<script src="https://cdn.example/x.js"></script><a href="https://github.com/x">ok</a>',
    '<meta name="robots" content="noindex, nofollow"><link rel="stylesheet" href="https://fonts.example/a.css"><style>b{background:url(https://x.example/i.png)}</style>'))
  expect(rules()).toEqual(['external-request', 'external-request', 'external-request'])
})
test('the word Claude is found outside the docs only', () => {
  write('index.html', page('Claude Deck')); write('docs/index.html', page('Claude Deck docs'))
  expect(checkDist(root).map((f) => [f.rule, f.file])).toEqual([['no-claude', 'index.html']])
})
test('backlog on the home page is found, on other pages it is allowed', () => {
  write('index.html', page('Your backlog')); write('how/index.html', page('Your backlog'))
  expect(checkDist(root).map((f) => [f.rule, f.file])).toEqual([['no-backlog-home', 'index.html']])
})
```

- [ ] **Step 2: Run them**

Run: `npx vitest run tests/check-dist.test.mjs`
Expected: FAIL ("Cannot find module '../scripts/check-dist.mjs'").

- [ ] **Step 3: Implement `scripts/check-dist.mjs`**

```js
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, dirname, extname } from 'node:path'
import { fileURLToPath } from 'node:url'

function walk(dir) {
  return readdirSync(dir).flatMap((n) => { const p = join(dir, n); return statSync(p).isDirectory() ? walk(p) : [p] })
}
const isDocs = (rel) => rel === 'docs' || rel.startsWith('docs/')
const external = (v) => /^([a-z]+:)?\/\//i.test(v)
const visibleText = (html) => html.replace(/<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>/gi, ' ').replace(/<[^>]+>/g, ' ')

export function checkDist(root) {
  const out = []
  const add = (file, rule, detail) => out.push({ file, rule, detail })
  const robots = join(root, 'robots.txt')
  if (!existsSync(robots) || !/^Disallow:\s*\/\s*$/m.test(readFileSync(robots, 'utf8'))) add('robots.txt', 'robots', 'robots.txt must disallow /')
  for (const path of walk(root)) {
    const rel = relative(root, path).split('\\').join('/')
    const ext = extname(path)
    if (!['.html', '.css', '.js', '.mjs'].includes(ext)) continue
    const text = readFileSync(path, 'utf8')
    if (ext === '.html') {
      for (const m of text.matchAll(/\s(href|src)=["']([^"']+)["']/gi)) {
        const v = m[2]
        if (v.startsWith('#') || /^(mailto|tel|data):/i.test(v) || external(v)) continue
        const clean = v.split(/[?#]/)[0]
        let target = clean.startsWith('/') ? join(root, clean) : join(dirname(path), clean)
        if (clean.endsWith('/')) target = join(target, 'index.html')
        if (!existsSync(target)) add(rel, 'local-link', v)
      }
    }
    if (isDocs(rel)) continue
    if (ext === '.html') {
      if (!/<meta\s+name=["']robots["']\s+content=["']noindex, nofollow["']/i.test(text)) add(rel, 'noindex', 'missing robots noindex')
      for (const m of text.matchAll(/<(script|img|iframe|source|video|audio)[^>]*\ssrc=["']([^"']+)["']/gi)) if (external(m[2])) add(rel, 'external-request', m[2])
      for (const m of text.matchAll(/<link[^>]*rel=["'](?:stylesheet|preload|icon|modulepreload)["'][^>]*href=["']([^"']+)["']/gi)) if (external(m[1])) add(rel, 'external-request', m[1])
      if (rel === 'index.html' && /backlog/i.test(visibleText(text))) add(rel, 'no-backlog-home', 'the word backlog is on the home page')
    }
    for (const m of text.matchAll(/url\(\s*["']?([^"')]+)/gi)) if (external(m[1])) add(rel, 'external-request', m[1])
    if (/claude/i.test(text)) add(rel, 'no-claude', 'the word Claude')
  }
  return out
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const findings = checkDist(process.argv[2] || 'dist')
  for (const f of findings) console.log(`${f.rule}\t${f.file}\t${f.detail}`)
  process.exit(findings.length ? 1 : 0)
}
```

- [ ] **Step 4: Run the tests and the check on the real build**

Run: `npx vitest run tests/check-dist.test.mjs && npm run build && npm run check`
Expected: the tests PASS; `npm run check` prints nothing and exits 0. If it reports a finding in the real build, fix the page, not the rule.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "test(site): check every build for noindex, local links, external requests and copy rules"
```

### Task 4: The site in a browser

**Files:**
- Create: `playwright.config.ts`, `tests/e2e/site.spec.ts`

**Interfaces:**
- Consumes: the build in `dist/`.
- Produces: `npm run e2e` serving `dist/` with `astro preview` on port 4321.

- [ ] **Step 1: `playwright.config.ts`**

```ts
import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: 'tests/e2e',
  use: { baseURL: 'http://127.0.0.1:4321' },
  webServer: { command: 'npx astro preview --host 127.0.0.1 --port 4321', url: 'http://127.0.0.1:4321', reuseExistingServer: false },
})
```

- [ ] **Step 2: Write `tests/e2e/site.spec.ts`**

```ts
import { expect, test } from '@playwright/test'

test('the home page loads with no request to another origin', async ({ page }) => {
  const foreign: string[] = []
  page.on('request', (r) => { if (!r.url().startsWith('http://127.0.0.1:4321')) foreign.push(r.url()) })
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Your features.')
  expect(foreign).toEqual([])
})

test('a docs page loads its own styles and scripts', async ({ page }) => {
  const missing: string[] = []
  page.on('response', (r) => { if (r.status() >= 400) missing.push(`${r.status()} ${r.url()}`) })
  await page.goto('/docs/')
  await expect(page.locator('body')).not.toBeEmpty()
  expect(missing).toEqual([])
})
```

- [ ] **Step 3: Run**

Run: `npm run build && npm run e2e`
Expected: 2 passed. If the docs test finds 404s, fix the paths in the Astro config (`trailingSlash`, `base`), not the docs files.

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "test(site): load the home page and a docs page in a browser"
```

### Task 5: Deploy the preview

**Files:**
- Create: `.github/workflows/preview.yml`, `tests/workflow.test.mjs`

**Interfaces:**
- Consumes: `npm run build`, `npm test`, `npm run check`, the repository secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` (already used by `deploy.yml`).
- Produces: a deployment at `https://preview-website-v2.claude-deck-website.pages.dev` on every push to `preview/website-v2`.

- [ ] **Step 1: Write the failing test**

```js
// tests/workflow.test.mjs
import { readFileSync } from 'node:fs'
import { expect, test } from 'vitest'

test('the preview workflow deploys only preview branches, and only after the checks', () => {
  const y = readFileSync('.github/workflows/preview.yml', 'utf8')
  expect(y).toMatch(/branches:\s*\[\s*'preview\/\*\*'\s*\]/)
  expect(y).not.toMatch(/\bmaster\b/)
  const order = ['npm ci', 'npm run build', 'npm test', 'npm run check', 'pages deploy dist']
  const at = order.map((s) => y.indexOf(s))
  expect(at.every((i) => i >= 0)).toBe(true)
  expect([...at].sort((a, b) => a - b)).toEqual(at)
  expect(y).toMatch(/--branch=preview-website-v2/)
})
```

- [ ] **Step 2: Run it**

Run: `npx vitest run tests/workflow.test.mjs`
Expected: FAIL (no workflow file).

- [ ] **Step 3: `.github/workflows/preview.yml`**

```yaml
name: Preview deploy

on:
  push:
    branches: ['preview/**']

permissions:
  contents: read
  deployments: write

concurrency:
  group: preview-${{ github.ref }}
  cancel-in-progress: true

jobs:
  preview:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-node@v4
        with:
          node-version: '24'
          cache: npm
      - run: npm ci
      - run: npm run build
      - run: npm test
      - run: npm run check
      - name: Deploy the preview
        uses: cloudflare/wrangler-action@v3
        with:
          apiToken: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          accountId: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
          command: pages deploy dist --project-name=claude-deck-website --branch=preview-website-v2
```

`fetch-depth: 0` keeps `origin/master` available to the docs pass-through test.

- [ ] **Step 4: Run the test, then push the branch**

Run: `npx vitest run && git add -A && git commit -m "ci(site): build, check and deploy the preview branch" && git push -u origin preview/website-v2`
Expected: the tests pass; the "Preview deploy" run succeeds; `curl -sI https://preview-website-v2.claude-deck-website.pages.dev/ | head -1` returns `HTTP/2 200`, and the page shows "Your features."; `curl -s https://preview-website-v2.claude-deck-website.pages.dev/robots.txt` shows `Disallow: /`.

### Task 6: The isometric scene library

**Files:**
- Create: `src/scenes/iso/project.ts`, `src/scenes/iso/shapes.tsx`, `src/scenes/iso/fit.ts`, `tests/iso.test.ts`

**Interfaces:**
- Produces:
  - `project(o: Origin, x: number, y: number, z: number): [number, number]` with `Origin = { x: number; y: number; k: number }` (30° isometric: `[o.x + (x - y)·cos30·k, o.y + (x + y)·sin30·k − z·k]`).
  - `shade(hex: string, factor: number): string`.
  - React components, all taking `o: Origin` and world coordinates: `<Box x y z w d h color />` (three faces: left `shade(color,.78)`, right `shade(color,.9)`, top `color`), `<Person x y color? />` (amber by default), `<Agent x y feature?: 0|1|2 />` (verdigris body, cap by feature: 0 cube blue, 1 pyramid violet, 2 cylinder rose; no feature: cube `--ai-top`), `<WorkItem x y feature />`, `<Callout x y z text dx dy small? />`.
  - `fitViewBox(svg: SVGSVGElement, pad?: number): void`, which sets `viewBox` to the content's bounding box after `document.fonts.ready`.
  - Depth order: callers draw back to front (larger `x + y` later); `sortByDepth(items)` returns items ordered by `x + y`.

- [ ] **Step 1: Write the failing tests**

```ts
// tests/iso.test.ts
import { expect, test } from 'vitest'
import { project, shade, sortByDepth } from '../src/scenes/iso/project'

const o = { x: 100, y: 50, k: 1 }
test('the origin projects to itself', () => expect(project(o, 0, 0, 0)).toEqual([100, 50]))
test('x goes right and down, y goes left and down, z goes up', () => {
  const [ax, ay] = project(o, 10, 0, 0); const [bx, by] = project(o, 0, 10, 0); const [, cz] = project(o, 0, 0, 10)
  expect(ax).toBeGreaterThan(100); expect(ay).toBeGreaterThan(50)
  expect(bx).toBeLessThan(100); expect(by).toBeGreaterThan(50)
  expect(cz).toBe(40)
})
test('scale k multiplies distances', () => expect(project({ ...o, k: 2 }, 0, 0, 10)[1]).toBe(30))
test('shade darkens and clamps', () => {
  expect(shade('#808080', 0.5)).toBe('#404040')
  expect(shade('#ffffff', 2)).toBe('#ffffff')
})
test('items are drawn from back to front', () => {
  expect(sortByDepth([{ x: 5, y: 5 }, { x: 0, y: 0 }, { x: 10, y: 0 }]).map((i) => i.x + i.y)).toEqual([0, 10, 10])
})
```

- [ ] **Step 2: Run them**

Run: `npx vitest run tests/iso.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `src/scenes/iso/project.ts`**

```ts
export type Origin = { x: number; y: number; k: number }
const C = Math.cos(Math.PI / 6), S = Math.sin(Math.PI / 6)

export function project(o: Origin, x: number, y: number, z: number): [number, number] {
  return [o.x + (x - y) * C * o.k, o.y + (x + y) * S * o.k - z * o.k].map((v) => Math.round(v * 1000) / 1000) as [number, number]
}
export function shade(hex: string, f: number): string {
  const n = parseInt(hex.slice(1), 16)
  const c = (v: number) => Math.max(0, Math.min(255, Math.round(v * f)))
  return '#' + [n >> 16, (n >> 8) & 255, n & 255].map((v) => c(v).toString(16).padStart(2, '0')).join('')
}
export function sortByDepth<T extends { x: number; y: number }>(items: T[]): T[] {
  return [...items].sort((a, b) => a.x + a.y - (b.x + b.y))
}
```

- [ ] **Step 4: Implement `src/scenes/iso/shapes.tsx` and `fit.ts`**

Port `box`, `person`, `agent` (with the feature caps), the work item and `callout` from `docs/plans/2026-10-15-director-website/style/source.html` (functions of the same names) to React components that return SVG elements, using `project` and `shade`. Use the Global Constraints colours. `fitViewBox` is the style frame's `fit()` made into a function that runs once now and again on `document.fonts.ready`.

- [ ] **Step 5: Run the tests**

Run: `npx vitest run tests/iso.test.ts`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(scenes): the isometric scene library"
```

### Task 7: The first scene, "the factory from outside", on the gallery page

**Files:**
- Create: `src/scenes/outside/OutsideScene.tsx`, `src/scenes/outside/STORYBOARD.md`, `src/pages/scenes/index.astro`, `tests/e2e/scenes.spec.ts`, `scripts/record-scene.mjs`

**Interfaces:**
- Consumes: the scene library (Task 6).
- Produces: `<OutsideScene />` (a React island, `client:visible`), the unlinked page `/scenes/` (with `noindex`), and `node scripts/record-scene.mjs <url> <out.webm>`, which records the page while it scrolls through the scene.

- [ ] **Step 1: Write the storyboard** in `src/scenes/outside/STORYBOARD.md`, before any code. Six beats, each with what the viewer sees, the motion, the timing in scroll progress (0–1), the easing, and the one idea it teaches:
  1. The ground draws in; GitHub appears with its feature lists ("GitHub holds your feature lists").
  2. The AI helper prepares a list; a card lifts into the stack ("Your AI helper prepares them").
  3. You, the Director, appear between GitHub and the Deck console ("You, the Director").
  4. You set up the teams in Deck; the console lights; the factory walls rise ("Deck sets up and runs your AI teams").
  5. Ready features travel from GitHub into the factory; two AI teams, blue and rose, start working ("The factory: several AI teams at work").
  6. Finished work travels back to GitHub; the loop continues ("Finished work flows back").

  The still version is beat 6's final frame with all labels.

- [ ] **Step 2: Write the failing browser tests**

```ts
// tests/e2e/scenes.spec.ts
import { expect, test } from '@playwright/test'
const labels = ['GitHub holds your feature lists', 'Your AI helper prepares them', 'You, the Director',
  'Deck sets up and runs your AI teams', 'The factory: several AI teams at work', 'Finished work flows back']

test('the gallery shows the outside scene with every label and no foreign request', async ({ page }) => {
  const foreign: string[] = []
  page.on('request', (r) => { if (!r.url().startsWith('http://127.0.0.1:4321')) foreign.push(r.url()) })
  await page.goto('/scenes/')
  const scene = page.locator('[data-scene="outside"] svg')
  await scene.scrollIntoViewIfNeeded()
  for (const l of labels) await expect(scene.getByText(l)).toBeAttached()
  expect(foreign).toEqual([])
})

test('reduced motion shows the final state with no timeline', async ({ browser }) => {
  const page = await browser.newPage({ reducedMotion: 'reduce' })
  await page.goto('/scenes/')
  const scene = page.locator('[data-scene="outside"]')
  await expect(scene).toHaveAttribute('data-state', 'still')
  for (const l of labels) await expect(scene.getByText(l)).toBeVisible()
})

test('no overflow at 390 px', async ({ browser }) => {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } })
  await page.goto('/scenes/')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})

test('the scene is not linked from the home page', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('a[href^="/scenes"]')).toHaveCount(0)
})
```

- [ ] **Step 3: Run them**

Run: `npm run build && npx playwright test tests/e2e/scenes.spec.ts`
Expected: FAIL (no `/scenes/` page).

- [ ] **Step 4: Implement the scene and the page**

`OutsideScene.tsx` draws the scene from the library: the ground, GitHub with three feature lists, the AI helper, the Director, the Deck console, the factory with two AI teams (feature 0 blue and feature 2 rose) and the two flows with work items. Draw back to front with `sortByDepth`. Set `data-scene="outside"` on the wrapper. In a `useEffect`:
- if `matchMedia('(prefers-reduced-motion: reduce)').matches`, set `data-state="still"` and stop;
- otherwise register `ScrollTrigger` and `DrawSVGPlugin`, build one GSAP timeline with the six storyboard beats, scrubbed by scroll over the scene's section (`scrub: true`, `start: 'top 75%'`, `end: 'bottom 40%'`), and set `data-state="animated"`;
- call `fitViewBox` on the SVG.

Clean the timeline up when the component unmounts.

`src/pages/scenes/index.astro` uses `Base` and places `<OutsideScene client:visible />` in a tall section (about 220 vh) so the scroll has room. It is linked from nowhere.

- [ ] **Step 5: Run the tests and the checks**

Run: `npm run build && npm run check && npx playwright test`
Expected: all browser tests pass; `npm run check` reports nothing.

- [ ] **Step 6: The recording script `scripts/record-scene.mjs`**

```js
import { chromium } from '@playwright/test'
const [url, out] = process.argv.slice(2)
const browser = await chromium.launch()
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, recordVideo: { dir: 'recordings', size: { width: 1440, height: 900 } } })
const page = await context.newPage()
await page.goto(url)
await page.waitForTimeout(800)
for (let y = 0; y <= 2600; y += 20) { await page.mouse.wheel(0, 20); await page.waitForTimeout(30) }
await page.waitForTimeout(1200)
const video = page.video()
await context.close()
await video.saveAs(out)
await browser.close()
console.log('saved', out)
```

Run: `node scripts/record-scene.mjs https://preview-website-v2.claude-deck-website.pages.dev/scenes/ recordings/outside-v1.webm` after the push in Step 7.
Expected: a WebM file of about 10–15 seconds showing the six beats.

- [ ] **Step 7: Commit and push**

```bash
echo recordings/ >> .gitignore
git add -A && git commit -m "feat(scenes): the factory from outside, on the gallery page" && git push
```

Expected: the preview deploy succeeds and `/scenes/` shows the scene on the preview URL. Send the Director the recording and a still frame, and ask for approval or changes. The next scenes (inside the factory, the hierarchy, the factory figure, several teams) get their own plan after this review.
