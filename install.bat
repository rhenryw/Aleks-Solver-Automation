@echo off
echo.
echo ===================================
echo   ALEKS AutoSolver — Setup
echo ===================================
echo.

echo [1/3] Installing Python dependencies...
pip install openai playwright python-dotenv
echo.

echo [2/3] Installing browser engine (Chromium)...
playwright install chromium
echo.

echo [3/3] Checking API configuration...
if "%OPENAI_API_KEY%"=="" (
    echo.
    echo !! OPENAI_API_KEY is not set.
    echo    Option A — set env vars in CMD:
    echo.
    echo      setx OPENAI_API_KEY "your-key-here"
    echo      setx OPENAI_BASE_URL "https://your-endpoint/v1"  (optional, for custom endpoints)
    echo      setx AI_MODEL "gpt-4o"                           (optional, overrides default model)
    echo.
    echo    Option B — create a .env file in this folder:
    echo.
    echo      OPENAI_API_KEY=your-key-here
    echo      OPENAI_BASE_URL=https://your-endpoint/v1
    echo      AI_MODEL=gpt-4o
    echo.
    echo    Then restart this terminal.
) else (
    echo    API key found.
    if not "%OPENAI_BASE_URL%"=="" echo    Base URL: %OPENAI_BASE_URL%
    if not "%AI_MODEL%"=="" echo    Model: %AI_MODEL%
)

echo.
echo Setup complete! Run with:
echo    python main.py
echo.
pause
