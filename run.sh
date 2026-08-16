#!/usr/bin/env bash
# Linux/macOS equivalent of run.cmd: first-time setup, then launch.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
export UV_LINK_MODE=copy

if ! command -v uv >/dev/null 2>&1; then
    echo "uv is not on PATH. Install it from https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

if [ ! -f ".env" ]; then
    cp ".env.example" ".env"
    echo "Created .env from .env.example. Add API keys if you are not using Ollama."
fi

uv sync --all-groups

exec uv run streamlit run streamlit_app.py --server.headless true
