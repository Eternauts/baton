"""Runtime configuration, read once from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_DEFAULT_CORPUS = str(Path(__file__).resolve().parent.parent / "corpus")


def _csv(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class Settings:
    project: str = field(default_factory=lambda: os.getenv("GOOGLE_CLOUD_PROJECT", ""))
    # Gemini 3.x on Vertex AI is served from the global endpoint.
    location: str = field(default_factory=lambda: os.getenv("GOOGLE_CLOUD_LOCATION", "global"))
    # Fallback chain: the first model that answers wins.
    answer_models: list[str] = field(
        default_factory=lambda: _csv("BATON_ANSWER_MODELS", "gemini-3.8-flash,gemini-2.5-flash")
    )
    thinking_level: str = field(default_factory=lambda: os.getenv("BATON_THINKING_LEVEL", "LOW"))
    use_embeddings: bool = field(default_factory=lambda: _bool("BATON_USE_EMBEDDINGS", True))
    embed_model: str = field(default_factory=lambda: os.getenv("BATON_EMBED_MODEL", "text-embedding-005"))
    embed_dim: int = field(default_factory=lambda: int(os.getenv("BATON_EMBED_DIM", "768")))
    # Embedding models are regional; Gemini answers are global.
    embed_location: str = field(default_factory=lambda: os.getenv("BATON_EMBED_LOCATION", "asia-southeast1"))
    # Local folder or gs://bucket/prefix holding .md/.txt/.json/.pdf documents and an optional rules.json.
    corpus_uri: str = field(default_factory=lambda: os.getenv("BATON_CORPUS_URI", _DEFAULT_CORPUS))
    # Where the built index is cached (local folder or gs://...). Empty: rebuild on every start.
    index_uri: str = field(default_factory=lambda: os.getenv("BATON_INDEX_URI", ""))
    # How often (seconds) an instance re-checks the corpus fingerprint and reloads if documents changed.
    refresh_s: int = field(default_factory=lambda: int(os.getenv("BATON_REFRESH_S", "300")))
    chunk_chars: int = field(default_factory=lambda: int(os.getenv("BATON_CHUNK_CHARS", "1100")))
    # Below this overall confidence an answer is reported as PARTIAL instead of ANSWER.
    answer_threshold: float = field(default_factory=lambda: float(os.getenv("BATON_ANSWER_THRESHOLD", "0.65")))
    # Below this retrieval confidence Gemini is not called at all: the corpus has nothing relevant.
    retrieval_floor: float = field(default_factory=lambda: float(os.getenv("BATON_RETRIEVAL_FLOOR", "0.2")))
    llm_timeout_s: float = field(default_factory=lambda: float(os.getenv("BATON_LLM_TIMEOUT_S", "25")))
    cache_size: int = field(default_factory=lambda: int(os.getenv("BATON_CACHE_SIZE", "512")))
    # Comma-separated keys accepted in X-API-Key. Empty disables auth (local development only).
    api_keys: list[str] = field(default_factory=lambda: _csv("BATON_API_KEYS", ""))
    admin_key: str = field(default_factory=lambda: os.getenv("BATON_ADMIN_KEY", ""))
    version: str = field(default_factory=lambda: os.getenv("BATON_VERSION", "0.1.0"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
