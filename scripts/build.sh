#!/bin/bash
# Production build script
# Builds the frontend for production deployment

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "Building Claude Deck for production..."

# Build frontend
echo ""
echo "Building frontend..."
cd "$PROJECT_ROOT/frontend"
npm run build

# The built files will be in frontend/dist
echo ""
echo "Build complete!"
echo "Frontend assets are in: frontend/dist"
echo ""
echo "To deploy:"
echo "  1. Serve frontend/dist with a static file server"
echo "  2. Run backend with: cd backend && source venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8000"
