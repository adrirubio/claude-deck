# Documentation publishing playbook

This playbook rebuilds the public documentation at <https://claudedeck.org/docs/> from the maintained documentation in this repository, copies the generated site into the separate website repository, and publishes it through Cloudflare Pages.

## How the two repositories fit together

| Repository | Owns |
|---|---|
| `claude-deck` | Markdown content in `docs/`, VitePress configuration and assets, and the build/copy scripts |
| `claude-deck-website` | Landing page plus the generated static documentation under its tracked `docs/` directory |

The source documents are maintained Markdown files. “Generate” means VitePress renders those files into static HTML, JavaScript, CSS, and assets; there is no source-code scraper that writes the documentation content. The public build excludes `docs/plans/**`, `docs/superpowers/**`, and `docs/deploy/**` through `docs/.vitepress/config.ts`.

The normal publish path is:

```text
edit Markdown in claude-deck/docs
  -> VitePress build
  -> copy generated output to claude-deck-website/docs
  -> commit and push claude-deck-website master
  -> GitHub Actions invokes Wrangler
  -> Cloudflare Pages serves the website
```

## One-time setup on a machine

The copy script expects the repositories to be siblings named exactly `claude-deck` and `claude-deck-website`. For example:

```text
~/repos/claude-deck/
~/repos/claude-deck-website/
```

Clone both repositories into that layout, or arrange the same relative layout under another parent directory. The script derives its location and does not depend on the shell's current directory.

For fresh checkouts, the repository remotes are:

```bash
mkdir -p ~/repos
cd ~/repos
git clone https://github.com/adrirubio/claude-deck.git
git clone https://github.com/adrirubio/claude-deck-website.git
```

Install Node.js 18 or newer, then install the docs dependencies from the lockfile:

```bash
cd ~/repos/claude-deck/docs
npm ci
```

The broader `./scripts/install.sh` also installs the backend and frontend dependencies; it is unnecessary when setting up only the documentation publisher. The normal GitHub Actions publish path needs GitHub permission to push to `claude-deck-website`; Cloudflare credentials stay in that repository's GitHub Actions secrets.

## Edit and preview documentation

Edit the Markdown source under `~/repos/claude-deck/docs/`. Update `docs/.vitepress/config.ts` when a new page needs navigation or sidebar links. Put site-wide images and static files under `docs/public/`.

Preview the docs locally:

```bash
cd ~/repos/claude-deck
./scripts/docs-dev.sh
```

Open <http://localhost:5174/docs/>. Stop the server with Ctrl+C. `./scripts/docs-dev.sh --port 5175` changes the port; `--host 0.0.0.0` makes it reachable on the local network.

## Build and copy the generated site

Before running the copy script, inspect both working trees and preserve or commit any changes you want to keep:

```bash
git -C ~/repos/claude-deck status --short
git -C ~/repos/claude-deck-website status --short
```

Then run:

```bash
cd ~/repos/claude-deck
./scripts/deploy-docs.sh
```

The script runs `npm run build` in `claude-deck/docs`, which invokes `vitepress build` and writes `docs/.vitepress/dist/`. If the build succeeds, it removes `claude-deck-website/docs/` and copies the generated `dist/` directory there. Keep hand-authored website content out of that target directory; make content changes in the source `claude-deck/docs/` tree.

Review the generated changes before publishing:

```bash
git -C ~/repos/claude-deck-website status --short
git -C ~/repos/claude-deck-website diff --stat -- docs/
git -C ~/repos/claude-deck-website diff --check -- docs/
```

The website repository should show generated files under `docs/` (for example `docs/index.html`, page HTML, and hashed assets). The base URL is `/docs/`, as configured in the source VitePress config.

Commit changes to the source Markdown in `claude-deck` through its normal branch/PR process so the canonical content is retained there. The generated copy is a separate change in `claude-deck-website`.

## Publish through the normal automated path

The website repository's `.github/workflows/deploy.yml` runs on pushes to `master`. It checks out the website repo and runs `cloudflare/wrangler-action@v3` with:

```text
pages deploy . --project-name=claude-deck-website
```

The action reads `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` from the website repository's GitHub Actions secrets. No Cloudflare token is needed on the publishing machine for this path.

The direct-push commands below require the website checkout to be on `master`. If it is on another branch, use the repository's PR flow and merge that branch into `master`; do not run the commands below from the other branch. Confirm the branch before committing:

```bash
test "$(git -C ~/repos/claude-deck-website branch --show-current)" = master || {
  echo "Switch to master or use the PR flow before publishing."
  exit 1
}
git -C ~/repos/claude-deck-website add docs/
git -C ~/repos/claude-deck-website commit -m "docs: update documentation"
git -C ~/repos/claude-deck-website push origin master
```

The production workflow is configured for `master`; merge a change to that branch before expecting the site to update. Check the GitHub Actions run in `adrirubio/claude-deck-website`, then open <https://claudedeck.org/docs/> and a changed page.

## Optional direct Wrangler deploy

The committed workflow is the normal deployment mechanism; it runs Wrangler through the Cloudflare GitHub Action. If a direct CLI deployment is specifically needed, use the same command from the root of the website repository after authenticating Wrangler to the intended Cloudflare account and reviewing the complete website checkout:

```bash
cd ~/repos/claude-deck-website
npx wrangler pages deploy . --project-name=claude-deck-website
```

Do not put an API token in this repository or in shell history. The CLI deploys the whole current website directory, including the landing page and generated `docs/` tree.

## Recovery

If the generated website commit is wrong, revert that commit in `claude-deck-website` and push the revert to `master`. The same workflow will publish the restored tracked files. Keep the source Markdown commit in `claude-deck` unless it also needs correction; reverting the generated snapshot alone does not change the source repository.

## Troubleshooting

- **`claude-deck-website not found`:** check that both repositories are sibling directories with the expected names.
- **Docs dependencies missing:** run `npm ci` from `claude-deck/docs`.
- **Generated links or assets point to the wrong location:** confirm `base: '/docs/'` in `docs/.vitepress/config.ts` and run the source build/copy script again.
- **No Cloudflare deployment starts:** confirm the website commit was pushed to `master` and inspect the repository's Actions run and configured Cloudflare secrets.
- **A local `docs/` change disappears:** the website `docs/` directory is generated output and is replaced by `scripts/deploy-docs.sh`; retain edits in the source `claude-deck/docs/` tree.
