#!/bin/bash

echo ""
echo "==================================="
echo "  ALEKS AutoSolver — Setup"
echo "==================================="
echo ""

echo "[1/3] Installing Python dependencies..."
pip install openai playwright python-dotenv
echo ""

echo "[2/3] Installing browser engine (Chromium)..."
playwright install chromium
echo ""

echo "[3/3] Checking API configuration..."
if [ -z "$OPENAI_API_KEY" ]; then
    echo ""
    echo "!! OPENAI_API_KEY is not set."
    echo "   Option A — add to ~/.bashrc or ~/.zshrc:"
    echo ""
    echo "     export OPENAI_API_KEY=\"your-key-here\""
    echo "     export OPENAI_BASE_URL=\"https://your-endpoint/v1\"  # optional, for custom endpoints"
    echo "     export AI_MODEL=\"gpt-4o\"                           # optional, overrides default model"
    echo ""
    echo "   Option B — create a .env file in this folder:"
    echo ""
    echo "     OPENAI_API_KEY=your-key-here"
    echo "     OPENAI_BASE_URL=https://your-endpoint/v1"
    echo "     AI_MODEL=gpt-4o"
    echo ""
    echo "   Then restart your terminal or run: source ~/.bashrc"
else
    echo "   API key found."
    [ -n "$OPENAI_BASE_URL" ] && echo "   Base URL: $OPENAI_BASE_URL"
    [ -n "$AI_MODEL" ] && echo "   Model: $AI_MODEL"
fi

echo ""
echo "Setup complete! Run with:"
echo "   python main.py"
echo ""
