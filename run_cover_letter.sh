#!/bin/bash
set -e

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$REPO_ROOT/.venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Error: No virtual environment found at .venv/"
    echo ""
    echo "To set up:"
    echo "  python3 -m venv .venv"
    echo "  .venv/bin/pip install -r backend/requirements.txt"
    exit 1
fi

source "$VENV_DIR/bin/activate"
cd "$REPO_ROOT/backend"
python generate_cover_letter.py "$@"
