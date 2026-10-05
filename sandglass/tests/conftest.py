from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from app.config import Settings
from app.engine import Engine
from app.gemini import CallMeta, LLMUnavailable
from app.schemas import DraftAnswer

CORPUS = str(Path(__file__).resolve().parent.parent / "corpus")


class FakeLLM:
    """Stands in for Vertex AI. `draft` is returned by generate(); None simulates an outage."""

    def __init__(self, draft: DraftAnswer | None = None):
        self.draft = draft
        self.prompts: list[str] = []

    async def generate(self, *, system, prompt, schema):
        self.prompts.append(prompt)
        if self.draft is None:
            raise LLMUnavailable("offline")
        return self.draft, CallMeta(model="fake-gemini", latency_ms=1)

    def embed_documents(self, texts):
        return None

    async def embed_query(self, text):
        return None


@pytest.fixture
def settings(tmp_path) -> Settings:
    return replace(Settings(), corpus_uri=CORPUS, index_uri=str(tmp_path / "index"), use_embeddings=False,
                   api_keys=[], admin_key="", cache_size=64)


@pytest.fixture
def make_engine(settings):
    def make(draft: DraftAnswer | None = None) -> tuple[Engine, FakeLLM]:
        llm = FakeLLM(draft)
        engine = Engine(settings, llm)
        engine.load()
        return engine, llm

    return make
