@echo off
echo.
echo ===================================
echo   ALEKS AutoSolver — Setup
echo ===================================
echo.

echo [1/3] Installing Python dependencies...
pip install anthropic playwright
echo.

echo [2/3] Installing browser engine (Chromium)...
playwright install chromium
echo.

echo [3/3] Setting up API key...
if "%ANTHROPIC_API_KEY%"=="" (
    echo.
    echo !! You need to set your Claude API key.
    echo    Run this in CMD:
    echo.
    echo    setx ANTHROPIC_API_KEY "your-key-here"
    echo.
    echo    Then restart this terminal.
) else (
    echo    API key found.
)

echo.
echo Setup complete! Run with:
echo    python main.py
echo.
pause
