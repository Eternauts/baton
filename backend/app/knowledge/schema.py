"""Shape of a document in the `knowledge_chunks` collection."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

COLLECTION = "knowledge_chunks"
SCHEMA_VERSION = "1"
MAX_CHUNK_CHARS = 1500

SOURCE_SOP = "SOP"
SOURCE_HANDOVER = "HANDOVER"
SOURCE_OBSERVATION = "OBSERVATION"
SOURCE_TYPES = (SOURCE_SOP, SOURCE_HANDOVER, SOURCE_OBSERVATION)


def make_chunk_id(source_type: str, source_id: str, chunk_index: int, text: str) -> str:
    """Deterministic ID, so re-ingesting the same content upserts instead of duplicating."""
    raw = f"{source_type}|{source_id}|{chunk_index}|{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class Chunk:
    source_type: str
    source_id: str
    chunk_index: int
    title: str
    text: str
    language: str = "en"
    unit: Optional[str] = None
    asset_tags: list[str] = field(default_factory=list)
    shift_id: Optional[str] = None
    author_role: Optional[str] = None
    created_at: Optional[datetime] = None
    valid_from: Optional[datetime] = None
    # Optional extras beyond the base schema
    doc_type: Optional[str] = None      # SOP | BULLETIN | MANUAL for source_type SOP
    revision: Optional[str] = None
    supersedes: Optional[str] = None    # e.g. "SOP-GD-03#2"
    seeded: bool = False

    @property
    def chunk_id(self) -> str:
        return make_chunk_id(self.source_type, self.source_id, self.chunk_index, self.text)
