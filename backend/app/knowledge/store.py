"""Writing chunks to Firestore: embed, upsert by chunk_id, prune stale chunks of a source."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Iterable

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore_v1.vector import Vector

from app.config import get_settings
from app.knowledge.embed import DOCUMENT, embed_texts
from app.knowledge.schema import COLLECTION, SCHEMA_VERSION, Chunk

logger = logging.getLogger("baton.knowledge.store")
_BATCH = 400  # Firestore allows 500 writes per batch


@lru_cache(maxsize=1)
def get_db() -> firestore.Client:
    s = get_settings()
    return firestore.Client(project=s.project, database=s.firestore_database)


def to_document(chunk: Chunk, embedding: list[float], model: str) -> dict:
    return {
        "chunk_id": chunk.chunk_id,
        "source_type": chunk.source_type,
        "source_id": chunk.source_id,
        "chunk_index": chunk.chunk_index,
        "title": chunk.title,
        "text": chunk.text,
        "language": chunk.language,
        "unit": chunk.unit,
        "asset_tags": chunk.asset_tags,
        "shift_id": chunk.shift_id,
        "author_role": chunk.author_role,
        "created_at": chunk.created_at or datetime.now(timezone.utc),
        "valid_from": chunk.valid_from,
        "embedding": Vector(embedding),
        "embedding_model": model,
        "schema_version": SCHEMA_VERSION,
        "doc_type": chunk.doc_type,
        "revision": chunk.revision,
        "supersedes": chunk.supersedes,
        "seeded": chunk.seeded,
    }


def upsert_chunks(chunks: Iterable[Chunk]) -> int:
    """Embed and write chunks. Same content gives the same chunk_id, so reruns overwrite, never duplicate."""
    chunks = list(chunks)
    if not chunks:
        return 0
    s = get_settings()
    vectors = embed_texts([c.text for c in chunks], DOCUMENT)
    db = get_db()
    for i in range(0, len(chunks), _BATCH):
        batch = db.batch()
        for c, v in zip(chunks[i:i + _BATCH], vectors[i:i + _BATCH]):
            batch.set(db.collection(COLLECTION).document(c.chunk_id), to_document(c, v, s.embedding_model))
        batch.commit()
    logger.info("upserted chunks=%d", len(chunks))
    return len(chunks)


def prune_source(source_type: str, source_id: str, keep_ids: set[str]) -> int:
    """Delete chunks of one source whose content is no longer present (e.g. after an SOP edit).
    Seeded documents are never touched."""
    db = get_db()
    q = (db.collection(COLLECTION)
         .where(filter=FieldFilter("source_type", "==", source_type))
         .where(filter=FieldFilter("source_id", "==", source_id)))
    stale = [d.reference for d in q.select(["seeded"]).stream() if d.id not in keep_ids and not d.get("seeded")]
    for i in range(0, len(stale), _BATCH):
        batch = db.batch()
        for ref in stale[i:i + _BATCH]:
            batch.delete(ref)
        batch.commit()
    return len(stale)


def delete_seeded() -> int:
    """Remove every chunk flagged seeded:true."""
    db = get_db()
    refs = [d.reference for d in db.collection(COLLECTION).where(filter=FieldFilter("seeded", "==", True)).select([]).stream()]
    for i in range(0, len(refs), _BATCH):
        batch = db.batch()
        for ref in refs[i:i + _BATCH]:
            batch.delete(ref)
        batch.commit()
    return len(refs)
