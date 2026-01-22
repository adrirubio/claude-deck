#!/bin/bash
# bump-version.sh - Sync version across all project files
#
# Usage: ./scripts/bump-version.sh [version]
#   If version is provided, updates VERSION file and syncs to all files
#   If no version provided, reads from VERSION file and syncs to all files

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

VERSION_FILE="$PROJECT_ROOT/VERSION"
PACKAGE_JSON="$PROJECT_ROOT/frontend/package.json"
PYPROJECT_TOML="$PROJECT_ROOT/backend/pyproject.toml"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

validate_semver() {
    local version="$1"
    if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?(\+[a-zA-Z0-9.]+)?$ ]]; then
        log_error "Invalid semantic version: $version"
        log_error "Expected format: MAJOR.MINOR.PATCH (e.g., 1.0.0, 2.1.3-beta)"
        exit 1
    fi
}

# Get version from argument or VERSION file
if [ -n "$1" ]; then
    VERSION="$1"
    validate_semver "$VERSION"
    echo "$VERSION" > "$VERSION_FILE"
    log_info "Updated VERSION file to $VERSION"
else
    if [ ! -f "$VERSION_FILE" ]; then
        log_error "VERSION file not found at $VERSION_FILE"
        log_error "Usage: $0 <version>"
        exit 1
    fi
    VERSION=$(cat "$VERSION_FILE" | tr -d '[:space:]')
    validate_semver "$VERSION"
    log_info "Reading version from VERSION file: $VERSION"
fi

# Update frontend/package.json
if [ -f "$PACKAGE_JSON" ]; then
    # Use a temporary file for sed compatibility across platforms
    if command -v jq &> /dev/null; then
        jq --arg v "$VERSION" '.version = $v' "$PACKAGE_JSON" > "$PACKAGE_JSON.tmp" && mv "$PACKAGE_JSON.tmp" "$PACKAGE_JSON"
    else
        # Fallback to sed if jq is not available
        sed -i.bak "s/\"version\": \"[^\"]*\"/\"version\": \"$VERSION\"/" "$PACKAGE_JSON" && rm -f "$PACKAGE_JSON.bak"
    fi
    log_info "Updated $PACKAGE_JSON to version $VERSION"
else
    log_warn "File not found: $PACKAGE_JSON"
fi

# Update backend/pyproject.toml
if [ -f "$PYPROJECT_TOML" ]; then
    sed -i.bak "s/^version = \"[^\"]*\"/version = \"$VERSION\"/" "$PYPROJECT_TOML" && rm -f "$PYPROJECT_TOML.bak"
    log_info "Updated $PYPROJECT_TOML to version $VERSION"
else
    log_warn "File not found: $PYPROJECT_TOML"
fi

log_info "Version sync complete: v$VERSION"

# Display current versions for verification
echo ""
echo "Current versions:"
echo "  VERSION file:    $(cat "$VERSION_FILE" | tr -d '[:space:]')"
if [ -f "$PACKAGE_JSON" ]; then
    echo "  package.json:    $(grep '"version"' "$PACKAGE_JSON" | head -1 | sed 's/.*"version": "\([^"]*\)".*/\1/')"
fi
if [ -f "$PYPROJECT_TOML" ]; then
    echo "  pyproject.toml:  $(grep '^version' "$PYPROJECT_TOML" | sed 's/version = "\([^"]*\)"/\1/')"
fi
