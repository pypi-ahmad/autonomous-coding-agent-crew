from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from crewai import LLM

from agent_crew.settings import (
    AGNES_BASE_URL,
    AGNES_MODEL,
    GOOGLE_MODELS,
    LLM_TIMEOUT_S,
    OPENAI_MODELS,
    ollama_host,
    require_env,
)


def list_ollama_models() -> list[str]:
    url = f"{ollama_host()}/api/tags"
    if not url.startswith(("http://", "https://")):
        return []
    try:
        with urllib.request.urlopen(url, timeout=3) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return []
    names: list[str] = []
    for item in payload.get("models", []):
        name = item.get("name") or item.get("model")
        if name:
            names.append(str(name))
    return names


def models_for(provider: str) -> list[str]:
    if provider == "ollama":
        return list_ollama_models()
    if provider == "openai":
        return list(OPENAI_MODELS)
    if provider == "agnes":
        return [AGNES_MODEL]
    if provider == "google":
        return list(GOOGLE_MODELS)
    return []


def validate_selection(provider: str, model: str) -> None:
    allowed = models_for(provider)
    if provider == "ollama" and not allowed:
        raise RuntimeError("No Ollama models found. Is Ollama running?")
    if model not in allowed:
        raise RuntimeError(f"Model {model!r} is not allowed for provider {provider!r}.")


def make_llm(provider: str, model: str, timeout: float = LLM_TIMEOUT_S) -> LLM:
    validate_selection(provider, model)
    if provider == "ollama":
        return LLM(model=f"ollama/{model}", api_base=ollama_host(), timeout=timeout)
    if provider == "openai":
        kwargs: dict[str, object] = {
            "model": f"openai/{model}",
            "api_key": require_env("OPENAI_API_KEY"),
            "reasoning_effort": "medium",
            "timeout": timeout,
        }
        base = os.getenv("OPENAI_BASE_URL", "").strip()
        if base:
            kwargs["api_base"] = base
            kwargs["custom_openai"] = True
        return LLM(**kwargs)
    if provider == "agnes":
        return LLM(
            model=f"openai/{AGNES_MODEL}",
            api_key=require_env("AGNES_API_KEY"),
            api_base=AGNES_BASE_URL,
            custom_openai=True,
            timeout=timeout,
        )
    if provider == "google":
        return LLM(model=f"gemini/{model}", api_key=require_env("GOOGLE_API_KEY"), timeout=timeout)
    raise RuntimeError(f"Unknown provider: {provider}")
