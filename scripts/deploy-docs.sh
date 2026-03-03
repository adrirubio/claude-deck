#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
DOCS_DIR="$REPO_ROOT/docs"
WEBSITE_DIR="$REPO_ROOT/../claude-deck-website"

if [ ! -d "$WEBSITE_DIR" ]; then
  echo "Error: claude-deck-website not found at $WEBSITE_DIR"
  exit 1
fi

echo "Building docs..."
cd "$DOCS_DIR"
npm run build

echo "Copying to website repo..."
rm -rf "$WEBSITE_DIR/docs"
cp -r "$DOCS_DIR/.vitepress/dist" "$WEBSITE_DIR/docs"

echo "Done! Built docs copied to $WEBSITE_DIR/docs/"
echo "cd $WEBSITE_DIR && git add docs/ && git commit -m 'docs: update documentation' && git push"
