from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

PROVIDERS = ("ollama", "openai", "agnes", "google")


def active_providers(*, local_only: bool) -> tuple[str, ...]:
    return ("ollama",) if local_only else PROVIDERS


OPENAI_MODELS = ("gpt-5.6-luna", "gpt-5.6-terra")
AGNES_MODEL = "agnes-2.5-flash"
AGNES_BASE_URL = "https://apihub.agnes-ai.com/v1"
GOOGLE_MODELS = ("gemini-3.5-flash-lite", "gemini-3.7-flash")
MAX_DEBUG_ATTEMPTS = 3
MAX_TEST_REWRITES = 2
MAX_REVIEW_ATTEMPTS = 1
MAX_GOAL_CYCLES = 2
MIN_COVERAGE = 70.0
MIN_LOOP_SCORE = 50
PERF_BUDGET_S = 2.0
LLM_TIMEOUT_S = 300
RUNS_DIR = ROOT / "runs"


def ollama_host() -> str:
    return os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value
