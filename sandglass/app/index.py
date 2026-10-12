"""Hybrid retrieval: BM25 (rule-normalised tokens) + dense vectors, fused with reciprocal rank fusion.

The index artifact is three files (manifest.json, chunks.jsonl, embeddings.npy).
BM25 statistics are cheap and rebuilt on load; only embeddings are worth caching.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import math
from collections import Counter, defaultdict
from dataclasses import dataclass

import numpy as np

from .corpus import Chunk
from .rules import QueryPlan, RuleSet

log = logging.getLogger("sandglass.index")

_K1, _B = 1.5, 0.75
_RRF_K = 60
_DENSE_CANDIDATES = 50
# Typical cosine range for text-embedding-005: ~0.45 unrelated, ~0.8 a close paraphrase.
_COS_LOW, _COS_HIGH = 0.45, 0.80


@dataclass
class Hit:
    chunk: Chunk
    score: float  # fused, boosted score; only meaningful relative to other hits
    bm25: float
    cosine: float | None
    pos: int  # position in HybridIndex.chunks


class HybridIndex:
    def __init__(self, chunks: list[Chunk], embeddings: np.ndarray | None, rules: RuleSet,
                 corpus_fingerprint: str = "", embed_model: str = ""):
        self.chunks = chunks
        self.rules = rules
        self.embeddings = embeddings if embeddings is not None and len(embeddings) == len(chunks) else None
        self.corpus_fingerprint = corpus_fingerprint
        self.embed_model = embed_model if self.embeddings is not None else ""
        self._postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self._lengths = np.zeros(len(chunks), dtype=np.float32)
        self.token_sets: list[set[str]] = []
        for i, chunk in enumerate(chunks):
            tokens = chunk.lexical_tokens()
            self._lengths[i] = len(tokens)
            self.token_sets.append(set(tokens))
            for term, tf in Counter(tokens).items():
                self._postings[term].append((i, tf))
        self._avgdl = float(self._lengths.mean()) if len(chunks) else 1.0
        self._boosts = np.array([rules.boost(c.doc_type) for c in chunks], dtype=np.float32)
        digest = hashlib.sha1(corpus_fingerprint.encode())
        for chunk in chunks:
            digest.update(chunk.id.encode())
            digest.update(chunk.text.encode())
        self.version = digest.hexdigest()[:10]

    @property
    def dense(self) -> bool:
        return self.embeddings is not None

    def _bm25(self, weights: dict[str, float]) -> np.ndarray:
        scores = np.zeros(len(self.chunks), dtype=np.float32)
        n = len(self.chunks)
        for term, weight in weights.items():
            postings = self._postings.get(term)
            if not postings:
                continue
            idf = math.log(1 + (n - len(postings) + 0.5) / (len(postings) + 0.5))
            for i, tf in postings:
                norm = tf + _K1 * (1 - _B + _B * self._lengths[i] / self._avgdl)
                scores[i] += weight * idf * tf * (_K1 + 1) / norm
        return scores

    def search(self, plan: QueryPlan, query_vec: np.ndarray | None, k: int) -> list[Hit]:
        if not self.chunks:
            return []
        bm = self._bm25(plan.weights)
        fused = np.zeros(len(self.chunks), dtype=np.float32)
        lexical = [i for i in np.argsort(-bm) if bm[i] > 0]
        for rank, i in enumerate(lexical):
            fused[i] += 1 / (_RRF_K + rank + 1)
        cos = None
        if self.embeddings is not None and query_vec is not None:
            cos = self.embeddings @ query_vec
            for rank, i in enumerate(np.argsort(-cos)[:_DENSE_CANDIDATES]):
                fused[i] += 1 / (_RRF_K + rank + 1)
        # Rule boosts: exact equipment-tag hits and document authority (bulletin > SOP > note).
        boost_tags = plan.tags | plan.context_tags
        for i, chunk in enumerate(self.chunks):
            if fused[i] == 0:
                continue
            tag_hits = len(boost_tags.intersection(chunk.tags))
            fused[i] *= self._boosts[i] * (1 + 0.25 * tag_hits)
        order = [i for i in np.argsort(-fused)[:k] if fused[i] > 0]
        return [Hit(self.chunks[i], float(fused[i]), float(bm[i]), None if cos is None else float(cos[i]), int(i))
                for i in order]

    def retrieval_confidence(self, plan: QueryPlan, hits: list[Hit]) -> float:
        """How likely the top hits contain the answer, from signals that need no model call."""
        if not hits:
            return 0.0
        top = hits[:3]
        signals: list[float] = []
        top_tokens = set().union(*(self.token_sets[h.pos] for h in top))
        if plan.core_terms:
            signals.append(sum(t in top_tokens for t in plan.core_terms) / len(plan.core_terms))
        if plan.tags:
            top_tags = set().union(*(h.chunk.tags for h in top))
            signals.append(len(plan.tags & top_tags) / len(plan.tags))
        if hits[0].cosine is not None:
            signals.append(min(1.0, max(0.0, (hits[0].cosine - _COS_LOW) / (_COS_HIGH - _COS_LOW))))
        return round(sum(signals) / len(signals), 3) if signals else 0.0

    # ---- persistence -------------------------------------------------------------------------

    def to_files(self) -> dict[str, bytes]:
        manifest = {"version": self.version, "corpus_fingerprint": self.corpus_fingerprint,
                    "embed_model": self.embed_model, "chunks": len(self.chunks)}
        files = {
            "manifest.json": json.dumps(manifest).encode(),
            "chunks.jsonl": "\n".join(json.dumps(c.to_json(), ensure_ascii=False) for c in self.chunks).encode(),
        }
        if self.embeddings is not None:
            buf = io.BytesIO()
            np.save(buf, self.embeddings)
            files["embeddings.npy"] = buf.getvalue()
        return files

    @classmethod
    def from_files(cls, files: dict[str, bytes], rules: RuleSet) -> HybridIndex:
        manifest = json.loads(files["manifest.json"])
        chunks = [Chunk(**json.loads(line)) for line in files["chunks.jsonl"].decode().splitlines() if line]
        emb = np.load(io.BytesIO(files["embeddings.npy"])) if "embeddings.npy" in files else None
        return cls(chunks, emb, rules, manifest.get("corpus_fingerprint", ""), manifest.get("embed_model", ""))

    def stats(self) -> dict:
        return {"version": self.version, "documents": len({c.doc_id for c in self.chunks}),
                "chunks": len(self.chunks), "dense": self.dense, "embed_model": self.embed_model}
