"""Semantic search over knowledge_chunks (Firestore vector search, cosine distance)."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from google.cloud.firestore_v1.vector import Vector

from app.config import get_settings
from app.knowledge.embed import embed_query
from app.knowledge.schema import COLLECTION
from app.knowledge.store import get_db
from app.knowledge.tags import normalize_tag, normalize_unit

logger = logging.getLogger("baton.knowledge.search")

DISTANCE_FIELD = "distance"
# With a field mask, the distance result field must be listed too, or Firestore omits it.
_FIELDS = ["source_type", "source_id", "title", "text", "asset_tags", "created_at",
           "unit", "doc_type", "supersedes", "chunk_index", DISTANCE_FIELD]
_MAX_FETCH = 200


@dataclass
class Hit:
    chunk_id: str
    source_type: str
    source_id: str
    title: str
    text: str
    asset_tags: list[str]
    created_at: Optional[datetime]
    distance: float
    unit: Optional[str] = None
    doc_type: Optional[str] = None
    supersedes: Optional[str] = None


def search(query: str, k: int = 6, source_types: list[str] | None = None, unit: str | None = None,
           asset_tag: str | None = None, since: datetime | None = None) -> list[Hit]:
    s = get_settings()
    start = time.time()
    vector = embed_query(query)
    embed_ms = int((time.time() - start) * 1000)

    q = get_db().collection(COLLECTION)
    if source_types:
        q = q.where(filter=FieldFilter("source_type", "==" if len(source_types) == 1 else "in",
                                       source_types[0] if len(source_types) == 1 else list(source_types)))
    if unit:
        q = q.where(filter=FieldFilter("unit", "==", normalize_unit(unit)))
    if asset_tag:
        q = q.where(filter=FieldFilter("asset_tags", "array_contains", normalize_tag(asset_tag)))

    # A time-range prefilter would need its own vector index per combination, so `since` is applied
    # after the search; fetch extra results to leave enough after filtering.
    limit = min(_MAX_FETCH, k * 4 if since else k)
    vq = q.select(_FIELDS).find_nearest(
        vector_field="embedding", query_vector=Vector(vector), limit=limit,
        distance_measure=DistanceMeasure.COSINE, distance_result_field=DISTANCE_FIELD,
        distance_threshold=s.search_max_distance)

    hits: list[Hit] = []
    for d in vq.stream():
        f = d.to_dict()
        created = f.get("created_at")
        if since and created and created < since:
            continue
        hits.append(Hit(chunk_id=d.id, source_type=f["source_type"], source_id=f["source_id"],
                        title=f.get("title", ""), text=f.get("text", ""), asset_tags=f.get("asset_tags") or [],
                        created_at=created, distance=float(f[DISTANCE_FIELD]), unit=f.get("unit"),
                        doc_type=f.get("doc_type"), supersedes=f.get("supersedes")))
    hits.sort(key=lambda h: h.distance)
    hits = hits[:k]
    logger.info("search qlen=%d k=%d types=%s unit=%s tag=%s since=%s hits=%d embed_ms=%d latency_ms=%d",
                len(query), k, source_types, bool(unit), bool(asset_tag), bool(since), len(hits),
                embed_ms, int((time.time() - start) * 1000))
    return hits
