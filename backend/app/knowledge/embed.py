"""Batched embeddings through the Gen AI SDK (Vertex AI), normalized for Firestore vector search."""
from __future__ import annotations

import logging
import math
import time

from google.genai import errors, types

from app.config import get_settings
from app.llm import get_client

logger = logging.getLogger("baton.knowledge.embed")

BATCH_SIZE = 100          # the API rejects ~250+ instances per request; 120 was verified to work
MAX_RETRIES = 3
_RETRY_BASE_S = 1.0

DOCUMENT = "RETRIEVAL_DOCUMENT"
QUERY = "RETRIEVAL_QUERY"


def _normalize(vec: list[float]) -> list[float]:
    """Reduced-dimension outputs are not unit length, so normalize them."""
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm else vec


def _embed_batch(texts: list[str], task_type: str) -> list[list[float]]:
    s = get_settings()
    cfg = types.EmbedContentConfig(task_type=task_type, output_dimensionality=s.embedding_dim)
    client = get_client(s.embedding_location)
    for attempt in range(MAX_RETRIES + 1):
        try:
            res = client.models.embed_content(model=s.embedding_model, contents=texts, config=cfg)
            return [_normalize(list(e.values)) for e in res.embeddings]
        except errors.APIError as err:
            code = getattr(err, "code", None)
            if attempt < MAX_RETRIES and (code == 429 or (isinstance(code, int) and code >= 500)):
                time.sleep(_RETRY_BASE_S * (2 ** attempt))
                continue
            if code == 404:
                logger.error("Embedding model '%s' not found at '%s'. Change EMBEDDING_MODEL or EMBEDDING_LOCATION.",
                             s.embedding_model, s.embedding_location)
            raise
    raise RuntimeError("unreachable")


def embed_texts(texts: list[str], task_type: str = DOCUMENT) -> list[list[float]]:
    """Embed many texts in batches. Returns one normalized vector per input, in order."""
    if not texts:
        return []
    start = time.time()
    out: list[list[float]] = []
    for i in range(0, len(texts), BATCH_SIZE):
        out.extend(_embed_batch(texts[i:i + BATCH_SIZE], task_type))
    logger.info("embed task=%s texts=%d dim=%d latency_ms=%d", task_type, len(texts),
                len(out[0]), int((time.time() - start) * 1000))
    return out


def embed_query(text: str) -> list[float]:
    return embed_texts([text], QUERY)[0]
