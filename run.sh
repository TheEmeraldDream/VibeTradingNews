#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/backend"

# Create venv if it doesn't exist
if [ ! -f "venv/bin/activate" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# Install / update dependencies
echo "Installing dependencies..."
pip install -r requirements.txt -q

# Run setup (creates setup.txt on first run, builds portfolio on subsequent runs)
echo ""
echo "Running setup..."
python setup_portfolio.py
echo ""

# Open browser after server starts
(sleep 2 && python3 -m webbrowser "http://localhost:8000/app") &

echo ""
echo "Starting Auction House v2.5 on http://localhost:8000/app"
echo "Press Ctrl+C to stop."
echo ""
uvicorn main:app --reload --port 8000
