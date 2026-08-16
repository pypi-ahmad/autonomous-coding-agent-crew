@echo off
setlocal
cd /d "%~dp0"
set UV_LINK_MODE=copy

where uv >nul 2>&1
if errorlevel 1 (
    echo uv is not on PATH. Install it from https://docs.astral.sh/uv/getting-started/installation/
    pause
    exit /b 1
)

if not exist ".env" (
    copy /y ".env.example" ".env" >nul
    echo Created .env from .env.example. Add API keys if you are not using Ollama.
)

uv sync --all-groups
if errorlevel 1 (
    echo uv sync failed.
    pause
    exit /b 1
)

uv run streamlit run streamlit_app.py --server.headless true
set EXITCODE=%ERRORLEVEL%
echo.
pause
exit /b %EXITCODE%
