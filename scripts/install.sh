#!/bin/bash
# Initial setup script
# Creates virtual environment, installs dependencies, initializes database

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "Setting up Claude Deck..."

# Check Python version
PYTHON_CMD="python3"
if ! command -v $PYTHON_CMD &> /dev/null; then
    echo "Error: Python 3 not found. Please install Python 3.11+."
    exit 1
fi

PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}' | cut -d. -f1,2)
echo "Found Python $PYTHON_VERSION"

# Check Node.js
if ! command -v node &> /dev/null; then
    echo "Error: Node.js not found. Please install Node.js 18+."
    exit 1
fi

NODE_VERSION=$(node --version)
echo "Found Node.js $NODE_VERSION"

# Setup backend
echo ""
echo "Setting up backend..."
cd "$PROJECT_ROOT/backend"

if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment..."
    $PYTHON_CMD -m venv venv
fi

echo "Activating virtual environment..."
source venv/bin/activate

echo "Installing Python dependencies..."
pip install -r requirements.txt

# Initialize database (handled on first run by FastAPI lifespan)
echo "Backend setup complete!"

# Setup frontend
echo ""
echo "Setting up frontend..."
cd "$PROJECT_ROOT/frontend"

echo "Installing Node.js dependencies..."
npm install

echo "Frontend setup complete!"

# Create required directories
echo ""
echo "Creating required directories..."
mkdir -p ~/.claude-registry/backups

echo ""
echo "Setup complete!"
echo ""
echo "To start development servers, run:"
echo "  ./scripts/dev.sh"
