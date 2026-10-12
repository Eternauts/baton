"""Vertex AI access through the Google Gen AI SDK: structured Gemini answers and text embeddings.

Clients are created on first use, so missing credentials degrade the service
(lexical-only retrieval, extractive answers) instead of breaking startup.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol, Sequence, TypeVar

import numpy as np
from pydantic import BaseModel, ValidationError

from .config import Settings

log = logging.getLogger("sandglass.gemini")
T = TypeVar("T", bound=BaseModel)
_EMBED_BATCH = 50


class LLMUnavailable(RuntimeError):
    """Every model in the fallback chain failed or credentials are missing."""


@dataclass
class CallMeta:
    model: str
    latency_ms: int
    tokens_in: int = 0
    tokens_out: int = 0


class LLM(Protocol):
    async def generate(self, *, system: str, prompt: str, schema: type[T]) -> tuple[T, CallMeta]: ...

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray | None: ...

    async def embed_query(self, text: str) -> np.ndarray | None: ...


def inline_schema(schema: dict) -> dict:
    """Resolve Pydantic $ref/$defs so the response schema is self-contained."""
    defs = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                target = resolve(defs[node["$ref"].split("/")[-1]])
                return {**target, **{k: resolve(v) for k, v in node.items() if k != "$ref"}}
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text.strip()


def _unit(rows: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(rows, axis=-1, keepdims=True)
    return rows / np.where(norms == 0, 1, norms)


class VertexGemini:
    def __init__(self, settings: Settings):
        from google.genai import types

        self._types = types
        self._s = settings
        self._clients: dict[str, Any] = {}
        self._auth_failed_at: float | None = None

    def _client(self, location: str) -> Any:
        if location not in self._clients:
            from google import genai

            try:
                self._clients[location] = genai.Client(enterprise=True, project=self._s.project or None,
                                                       location=location)
            except TypeError:  # google-genai 1.x naming
                self._clients[location] = genai.Client(vertexai=True, project=self._s.project or None,
                                                       location=location)
        return self._clients[location]

    def _config(self, model: str, system: str, schema: type[BaseModel]) -> Any:
        kwargs: dict[str, Any] = {
            "system_instruction": system,
            "temperature": 0.1,
            "response_mime_type": "application/json",
            "response_json_schema": inline_schema(schema.model_json_schema()),
            "automatic_function_calling": self._types.AutomaticFunctionCallingConfig(disable=True),
        }
        if self._s.thinking_level and model.startswith("gemini-3"):
            try:
                kwargs["thinking_config"] = self._types.ThinkingConfig(thinking_level=self._s.thinking_level)
            except Exception:  # SDK without thinking_level: keep the model default
                pass
        return self._types.GenerateContentConfig(**kwargs)

    async def generate(self, *, system: str, prompt: str, schema: type[T]) -> tuple[T, CallMeta]:
        if self._auth_failed_at is not None and time.monotonic() - self._auth_failed_at < 60:
            raise LLMUnavailable("credentials unavailable (recent failure)")
        try:
            client = self._client(self._s.location)
        except Exception as exc:
            self._auth_failed_at = time.monotonic()
            raise LLMUnavailable(f"client unavailable: {type(exc).__name__}") from exc
        deadline = time.monotonic() + self._s.llm_timeout_s
        last: Exception | None = None
        for model in self._s.answer_models:
            remaining = deadline - time.monotonic()
            if remaining < 2:
                break
            started = time.perf_counter()
            try:
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(model=model, contents=prompt,
                                                       config=self._config(model, system, schema)),
                    timeout=remaining,
                )
                parsed = schema.model_validate_json(_strip_fences(response.text or ""))
                usage = getattr(response, "usage_metadata", None)
                return parsed, CallMeta(
                    model=model,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    tokens_in=int(getattr(usage, "prompt_token_count", 0) or 0),
                    tokens_out=int(getattr(usage, "candidates_token_count", 0) or 0),
                )
            except (ValidationError, asyncio.TimeoutError) as exc:
                last = exc
                log.warning("model %s failed: %s", model, type(exc).__name__)
            except Exception as exc:  # google.genai.errors.*, auth and transport errors
                last = exc
                if "credential" in str(exc).lower() or type(exc).__name__ == "DefaultCredentialsError":
                    self._auth_failed_at = time.monotonic()
                    raise LLMUnavailable(f"credentials unavailable: {type(exc).__name__}") from exc
                log.warning("model %s failed: %s %s", model, type(exc).__name__, getattr(exc, "code", ""))
        raise LLMUnavailable(f"all models failed: {type(last).__name__ if last else 'time budget'}")

    def _embed_config(self, task: str) -> Any:
        return self._types.EmbedContentConfig(task_type=task, output_dimensionality=self._s.embed_dim)

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray | None:
        if not self._s.use_embeddings or not texts:
            return None
        try:
            client = self._client(self._s.embed_location)
            rows: list[list[float]] = []
            for i in range(0, len(texts), _EMBED_BATCH):
                resp = client.models.embed_content(model=self._s.embed_model, contents=list(texts[i:i + _EMBED_BATCH]),
                                                   config=self._embed_config("RETRIEVAL_DOCUMENT"))
                rows.extend(e.values for e in resp.embeddings)
            return _unit(np.asarray(rows, dtype=np.float32))
        except Exception as exc:
            log.warning("document embeddings unavailable, lexical retrieval only: %s", exc)
            return None

    async def embed_query(self, text: str) -> np.ndarray | None:
        if not self._s.use_embeddings:
            return None
        try:
            client = self._client(self._s.embed_location)
            resp = await asyncio.wait_for(
                client.aio.models.embed_content(model=self._s.embed_model, contents=[text],
                                                config=self._embed_config("RETRIEVAL_QUERY")),
                timeout=5,
            )
            return _unit(np.asarray(resp.embeddings[0].values, dtype=np.float32))
        except Exception as exc:
            log.warning("query embedding failed, lexical retrieval only: %s", type(exc).__name__)
            return None
