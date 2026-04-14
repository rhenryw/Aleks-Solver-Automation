#!/bin/bash

echo ""
echo "==================================="
echo "  ALEKS AutoSolver — Setup"
echo "==================================="
echo ""

echo "[1/4] Installing Python dependencies..."
pip install requests playwright
echo ""

echo "[2/4] Installing browser engine (Chromium)..."
playwright install chromium
echo ""

echo "[3/4] Checking Ollama installation..."
if command -v ollama &> /dev/null; then
    echo "   ✓ Ollama is installed: $(ollama --version)"
else
    echo ""
    echo "   !! Ollama is NOT installed."
    echo "   Install it with:"
    echo ""
    echo "   curl -fsSL https://ollama.com/install.sh | sh"
    echo ""
    echo "   Then restart this script."
    echo ""
fi

echo "[4/4] Pulling AI model..."
if command -v ollama &> /dev/null; then
    echo "   Pulling qwen2.5:7b (good at math, ~4.7GB)..."
    echo "   This may take a few minutes on first run."
    ollama pull qwen2.5:7b
    echo ""
    echo "   ✓ Model ready"
else
    echo "   ⏭ Skipped (Ollama not installed yet)"
fi

echo ""
echo "==================================="
echo "  Setup complete!"
echo "==================================="
echo ""
echo "  To run:"
echo "    1. Start Ollama:  ollama serve"
echo "    2. Run solver:    python main.py"
echo ""
echo "  Optional: try other models:"
echo "    ollama pull llama3.1:8b"
echo "    ollama pull deepseek-r1:7b"
echo "    ollama pull mistral:7b"
echo "  Then change OLLAMA_MODEL in config.py"
echo ""
