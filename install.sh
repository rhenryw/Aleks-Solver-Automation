#!/bin/bash

echo ""
echo "==================================="
echo "  ALEKS AutoSolver — Setup"
echo "==================================="
echo ""

echo "[1/3] Installing Python dependencies..."
pip install anthropic playwright
echo ""

echo "[2/3] Installing browser engine (Chromium)..."
playwright install chromium
echo ""

echo "[3/3] Setting up API key..."
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo ""
    echo "!! You need to set your Claude API key."
    echo "   Add this to your ~/.bashrc or ~/.zshrc:"
    echo ""
    echo "   export ANTHROPIC_API_KEY=\"your-key-here\""
    echo ""
    echo "   Then restart this terminal or run: source ~/.bashrc"
else
    echo "   API key found."
fi

echo ""
echo "Setup complete! Run with:"
echo "   python main.py"
echo ""
