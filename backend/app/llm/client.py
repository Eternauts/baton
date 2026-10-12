"""The single Gemini entry point. Uses the Gen AI SDK against Vertex AI.

Every Gemini call in the backend goes through `generate()`, so retries, timeouts and
per-call logging behave the same everywhere. Model IDs and locations come from app.config.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import errors, types

from app.config import get_settings

logger = logging.getLogger("baton.llm")

MAX_RETRIES = 2
_RETRY_BASE_S = 0.5
_clients: dict[tuple[str, str], genai.Client] = {}
_lock = threading.Lock()


@dataclass
class GenerateResult:
    text: str
    model: str
    location: str
    latency_ms: int


def get_client(location: str | None = None) -> genai.Client:
    """Shared client per (project, location)."""
    s = get_settings()
    loc = location or s.gemini_location
    key = (s.project, loc)
    with _lock:
        if key not in _clients:
            _clients[key] = genai.Client(vertexai=True, project=s.project, location=loc)
        return _clients[key]


def _input_size(contents: Any) -> int:
    """Rough input size (characters of text plus bytes of inline data). Never logs content."""
    if isinstance(contents, str):
        return len(contents)
    total = 0
    for part in contents if isinstance(contents, (list, tuple)) else [contents]:
        if isinstance(part, str):
            total += len(part)
        else:
            inline = getattr(part, "inline_data", None)
            if inline is not None and getattr(inline, "data", None):
                total += len(inline.data)
            else:
                total += len(getattr(part, "text", "") or "")
    return total


def _retryable(err: Exception) -> bool:
    code = getattr(err, "code", None)
    return isinstance(err, errors.APIError) and (code == 429 or (isinstance(code, int) and code >= 500))


def generate(
    purpose: str,
    contents: Any,
    *,
    fast: bool = False,
    max_output_tokens: int = 1024,
    thinking_level: str | None = "MINIMAL",
    timeout_s: float = 30.0,
    system_instruction: str | None = None,
    response_mime_type: str | None = None,
    response_schema: Any = None,
) -> GenerateResult:
    """Call Gemini with retries on 429/5xx (at most MAX_RETRIES), a timeout and one log line."""
    s = get_settings()
    model = s.gemini_fast_model if fast else s.gemini_model
    location = s.gemini_fast_location if fast else s.gemini_location
    env_name = "GEMINI_FAST_MODEL" if fast else "GEMINI_MODEL"
    cfg = types.GenerateContentConfig(
        max_output_tokens=max_output_tokens,
        system_instruction=system_instruction,
        response_mime_type=response_mime_type,
        response_schema=response_schema,
        thinking_config=types.ThinkingConfig(thinking_level=thinking_level) if thinking_level else None,
        http_options=types.HttpOptions(
            timeout=int(timeout_s * 1000),
            retry_options=types.HttpRetryOptions(attempts=1),  # retries are handled here, once
        ),
    )
    in_size = _input_size(contents)
    start = time.time()
    status = "ok"
    out_size = 0
    try:
        for attempt in range(MAX_RETRIES + 1):
            try:
                res = get_client(location).models.generate_content(model=model, contents=contents, config=cfg)
                text = (res.text or "").strip()
                out_size = len(text)
                status = "ok" if attempt == 0 else f"ok_after_{attempt}_retries"
                return GenerateResult(text=text, model=model, location=location,
                                      latency_ms=int((time.time() - start) * 1000))
            except Exception as err:  # noqa: BLE001
                if attempt < MAX_RETRIES and _retryable(err):
                    status = f"retry_{getattr(err, 'code', 'err')}"
                    time.sleep(_RETRY_BASE_S * (2 ** attempt))
                    continue
                code = getattr(err, "code", None)
                status = f"error_{code or type(err).__name__}"
                if code == 404:
                    logger.error(
                        "Model '%s' not found at location '%s' (retired or not served there). "
                        "Change the %s environment variable (or the matching *_LOCATION).",
                        model, location, env_name,
                    )
                raise
    finally:
        logger.info(
            "gemini_call purpose=%s model=%s location=%s in=%d out=%d latency_ms=%d status=%s",
            purpose, model, location, in_size, out_size, int((time.time() - start) * 1000), status,
        )
