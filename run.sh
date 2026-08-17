#!/usr/bin/env bash
# run.sh — One-click setup and startup script for NIFTY Market Analyzer

set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🚀 Starting NIFTY Market Analyzer Setup & Server"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 1. Create virtual environment if missing
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment (venv)..."
    python3 -m venv venv
fi

# 2. Activate virtual environment
source venv/bin/activate

# 3. Install / update dependencies
echo "📥 Installing / verifying Python dependencies..."
pip install -q -r requirements.txt

# 4. Launch Flask App
echo "🌐 Launching Flask server on http://localhost:5000..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
python server.py
