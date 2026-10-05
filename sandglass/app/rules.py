"""Deterministic text rules shared by indexing and querying.

Both sides go through the same normalisation so lexical matching is symmetric:
equipment tags are canonicalised (p101a, P 101A -> P-101A), alias phrases map to
tags ("pump A" -> P-101A) and synonym groups widen the query at a lower weight.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

# Plant tag shape: 1-4 letters, optional hyphen, 2-4 digits, optional letter suffix (P-101A, PSV104, GD-311).
TAG_RE = re.compile(r"\b([A-Za-z]{1,4})-?(\d{2,4}[A-Za-z]?)\b")
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_STOPWORDS = frozenset(
    "a an and are as at be been but by can could do does for from had has have how i if in into is it its "
    "may me might must my no not of on or our shall should so than that the their them then there these they "
    "this those to was we were what when where which while who why will with would you your still any all "
    "currently now".split()
)


def canon_tags(text: str) -> str:
    return TAG_RE.sub(lambda m: f"{m[1].upper()}-{m[2].upper()}", text)


def _stem(token: str) -> str:
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    """Lowercased content tokens. Hyphenated words also yield their parts; tags stay whole."""
    out: list[str] = []
    for tok in _TOKEN_RE.findall(canon_tags(text).lower()):
        if "-" in tok and not TAG_RE.fullmatch(tok):
            out.extend(_stem(p) for p in tok.split("-") if p not in _STOPWORDS)
        if tok not in _STOPWORDS:
            out.append(_stem(tok))
    return out


def normalize_for_match(text: str) -> str:
    """Loose form used to verify that a quote really appears in a source."""
    return re.sub(r"[^a-z0-9]+", " ", canon_tags(text).lower()).strip()


@dataclass
class QueryPlan:
    text: str
    core_terms: list[str]  # tokens from the question itself
    weights: dict[str, float]  # core terms at 1.0, expansions lower
    tags: set[str] = field(default_factory=set)  # named in the question: count toward retrieval confidence
    context_tags: set[str] = field(default_factory=set)  # from device context: ranking boost only


class RuleSet:
    """Loaded from rules.json in the corpus. Every section is optional."""

    def __init__(self, data: dict | None = None):
        data = data or {}
        # {"P-101A": ["pump A", "feed pump A"]}
        self.aliases: dict[str, list[str]] = {canon_tags(k): v for k, v in data.get("aliases", {}).items()}
        # [["psv", "relief valve", "safety valve"], ...]
        self.synonyms: list[list[str]] = [[s.lower() for s in g] for g in data.get("synonyms", [])]
        # {"BULLETIN": 1.3, "SOP": 1.15, "NOTE": 0.85}
        self.type_boost: dict[str, float] = {k.upper(): float(v) for k, v in data.get("type_boost", {}).items()}
        self.expansion_weight: float = float(data.get("expansion_weight", 0.5))
        self._alias_res = [
            (tag, re.compile(rf"\b{re.escape(a.lower())}\b")) for tag, names in self.aliases.items() for a in names
        ]

    @classmethod
    def from_bytes(cls, raw: bytes | None) -> RuleSet:
        return cls(json.loads(raw) if raw else None)

    def tags_in(self, text: str) -> set[str]:
        canon = canon_tags(text)
        tags = {f"{m[1]}-{m[2]}" for m in TAG_RE.finditer(canon)}
        low = text.lower()
        tags.update(tag for tag, rx in self._alias_res if rx.search(low))
        return tags

    def plan(self, query: str, context_tags: list[str] | None = None) -> QueryPlan:
        core = tokenize(query)
        weights: dict[str, float] = {t: 1.0 for t in core}
        tags = self.tags_in(query)
        ctx = {canon_tags(t) for t in (context_tags or []) if TAG_RE.fullmatch(canon_tags(t))} - tags
        for tag in tags:
            weights[tag.lower()] = max(weights.get(tag.lower(), 0.0), 1.5)
        for tag in ctx:
            weights.setdefault(tag.lower(), 0.5)
        low = " " + " ".join(normalize_for_match(query).split()) + " "
        w = self.expansion_weight
        for group in self.synonyms:
            if any(f" {normalize_for_match(term)} " in low for term in group):
                for term in group:
                    for tok in tokenize(term):
                        weights.setdefault(tok, w)
        return QueryPlan(text=query, core_terms=list(dict.fromkeys(core)), weights=weights, tags=tags, context_tags=ctx)

    def boost(self, doc_type: str) -> float:
        return self.type_boost.get(doc_type.upper(), 1.0)
