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

echo "=========================================="
echo "Step 1/3: Scraping WaterlooWorks..."
echo "=========================================="
python jobhunter_h.py

echo ""
echo "=========================================="
echo "Step 2/3: Ranking jobs with AI..."
echo "=========================================="
python ai_matcher_bulk.py

echo ""
echo "=========================================="
echo "Step 3/3: Cover Letter Generation"
echo "=========================================="
echo ""
echo "What would you like to do?"
echo "  1) Generate for all ranked jobs"
echo "  2) Generate for a specific job ID"
echo "  3) Skip"
echo ""
read -rp "Choose [1/2/3]: " choice

case "$choice" in
    1)
        python generate_cover_letter.py --all
        ;;
    2)
        read -rp "Enter job ID: " job_id
        python generate_cover_letter.py "$job_id"
        ;;
    3)
        echo "Skipping cover letter generation."
        ;;
    *)
        echo "Invalid choice. Skipping cover letter generation."
        ;;
esac

echo ""
echo "Done!"
