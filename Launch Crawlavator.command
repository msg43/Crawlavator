#!/bin/bash
# Crawlavator one-click launcher (macOS: double-click this file to start the app)

set -e
cd "$(dirname "$0")"

if [[ ! -d venv ]]; then
    echo "First-time setup: creating virtual environment..."
    python3 -m venv venv
    ./venv/bin/pip install -r requirements.txt
    echo "Installing Playwright browsers (one-time download)..."
    ./venv/bin/playwright install
    echo ""
fi

echo "Starting Crawlavator at http://localhost:5001"
echo "Press Ctrl+C to stop the server."
echo ""
exec ./venv/bin/python app.py
