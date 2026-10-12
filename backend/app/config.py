"""Central, validated configuration. Every model ID and location comes from here, never from code."""
from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    project: str
    gemini_model: str
    gemini_fast_model: str
    gemini_location: str
    gemini_fast_location: str
    embedding_model: str
    embedding_dim: int
    embedding_location: str
    transcribe_engine: str
    firestore_database: str
    pubsub_topic: str
    aegis_api_key: str
    aegis_demo_key: str
    search_max_distance: float
    corpus_bucket: str
    worker_audience: str
    push_invoker_email: str


def _env(name: str, default: str | None = None) -> str:
    return (os.environ.get(name) or default or "").strip()


def get_settings() -> Settings:
    """Read settings from the environment on every call (cheap; keeps tests and rotated secrets simple)."""
    try:
        dim = int(_env("EMBEDDING_DIM", "768"))
        max_dist = float(_env("SEARCH_MAX_DISTANCE", "0.42"))
    except ValueError:
        raise ConfigError("EMBEDDING_DIM must be an integer and SEARCH_MAX_DISTANCE a number")
    return Settings(
        project=_env("GOOGLE_CLOUD_PROJECT"),
        gemini_model=_env("GEMINI_MODEL"),
        gemini_fast_model=_env("GEMINI_FAST_MODEL") or _env("GEMINI_MODEL"),
        # VERTEX_LOCATION is the legacy name, kept as a fallback so older deployments keep working.
        gemini_location=_env("GEMINI_LOCATION") or _env("VERTEX_LOCATION", "global"),
        # The fast (Flash-Lite) model is only served from `global`, so it may need its own location.
        gemini_fast_location=_env("GEMINI_FAST_LOCATION") or _env("GEMINI_LOCATION") or _env("VERTEX_LOCATION", "global"),
        embedding_model=_env("EMBEDDING_MODEL"),
        embedding_dim=dim,
        embedding_location=_env("EMBEDDING_LOCATION") or _env("GEMINI_LOCATION") or _env("VERTEX_LOCATION", "global"),
        transcribe_engine=_env("TRANSCRIBE_ENGINE", "gemini"),
        firestore_database=_env("FIRESTORE_DATABASE", "(default)"),
        pubsub_topic=_env("PUBSUB_TOPIC"),
        aegis_api_key=_env("AEGIS_API_KEY"),
        # Optional key that is safe to ship inside a public web app: it opens the app endpoints only (see main.require_app_key).
        aegis_demo_key=_env("AEGIS_DEMO_KEY"),
        # Cosine distance (0 = identical, 2 = opposite). Hits farther than this are dropped.
        search_max_distance=max_dist,
        corpus_bucket=_env("CORPUS_BUCKET", "ai-builder-cup-2026-509818-baton-corpus"),
        # Pub/Sub push auth: the worker accepts only tokens for this audience and this identity.
        worker_audience=_env("WORKER_AUDIENCE"),
        push_invoker_email=_env("PUSH_INVOKER_EMAIL"),
    )


def validate_startup(s: Settings | None = None) -> list[str]:
    """Return a list of problems. Required for the API to do useful work; the caller decides whether to fail."""
    s = s or get_settings()
    problems = []
    if not s.project:
        problems.append("GOOGLE_CLOUD_PROJECT is not set")
    if not s.gemini_model:
        problems.append("GEMINI_MODEL is not set")
    if not s.aegis_api_key:
        problems.append("AEGIS_API_KEY is not set (protected endpoints will reject every request)")
    if s.transcribe_engine not in ("gemini", "chirp3"):
        problems.append("TRANSCRIBE_ENGINE must be 'gemini' or 'chirp3'")
    return problems
