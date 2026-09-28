"""Typed configuration via pydantic-settings.

Every knob is env-overridable with the ``SWARM_`` prefix; offline mode is
the default so the whole system runs deterministically with no network.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class SwarmSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SWARM_", env_file=".env", extra="ignore")

    # Master switch: True = bundled corpus + extractive heuristics, zero network.
    offline: bool = True

    # LLM (OpenAI-compatible). Only used when offline is False and a key is set.
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    request_timeout_s: float = 60.0

    # Optional web search endpoint; empty string keeps the bundled corpus backend.
    web_search_endpoint: str = ""

    # Orchestration budgets.
    max_concurrency: int = 4
    max_docs_per_task: int = 4
    claims_per_doc: int = 5
    token_budget: int = 6000
    coverage_threshold: float = 0.8

    # Optional override for the bundled corpus location (tests / custom corpora).
    corpus_dir: Path | None = None

    # --- Serving / auth ---
    # Comma-separated RAW API keys (env SWARM_API_KEYS). Only SHA-256 hashes are
    # stored at rest (serve/auth.py). Unset/empty = auth disabled with warning.
    api_keys: str | None = None
