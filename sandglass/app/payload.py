"""Compact wire format for the on-device model, trimmed deterministically to a byte budget.

Compact answer keys:
  v corpus version   d decision A|P|N|C   c confidence 0-1   a answer
  f facts  [[text, confidence, [source indexes]], ...]
  s sources [[chunk id, section, relevance], ...]
  x next action   w warning / conflict note   g generator g(emini)|e(xtractive)|n(one)   t server ms

Trim order when over budget (least useful to the device first): extra facts, section labels,
long action/warning text, the last fact, answer beyond 160 chars, extra sources, action/warning/
sources, then the answer itself. v, d, c and g always survive.
"""
from __future__ import annotations

import copy
import json

from .schemas import AskResult


def encode(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()


def compact(result: AskResult) -> dict:
    p: dict = {"v": result.corpus_version, "d": result.decision, "c": round(result.confidence, 2),
               "a": result.answer, "g": result.generator[0], "t": result.latency_ms}
    # A fact already spelled out in the answer only costs bytes; keep its source through `s`.
    facts = [[c.text, round(c.confidence, 2), c.sources] for c in result.claims if c.text not in result.answer]
    if facts:
        p["f"] = facts
    if result.sources:
        p["s"] = [[s.id, s.section, round(s.relevance, 2)] for s in result.sources]
    if result.action:
        p["x"] = result.action
    if result.note:
        p["w"] = result.note
    return p


def _trim(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 1:
        return ""
    cut = text.rfind(" ", 0, limit - 1)
    return text[: cut if cut > limit // 2 else limit - 1].rstrip(" ,;:") + "…"


def _prune_sources(p: dict) -> None:
    """Keep only sources a remaining fact cites, renumbering the references."""
    if "f" not in p or "s" not in p:
        return
    used = sorted({i for fact in p["f"] for i in fact[2] if i < len(p["s"])})
    if not used:
        return
    remap = {old: new for new, old in enumerate(used)}
    p["s"] = [p["s"][i] for i in used]
    for fact in p["f"]:
        fact[2] = [remap[i] for i in fact[2] if i in remap]


def fit(payload: dict, budget: int) -> bytes:
    p = copy.deepcopy(payload)

    def over() -> bool:
        return len(encode(p)) > budget

    while over() and len(p.get("f", [])) > 1:
        p["f"].sort(key=lambda f: -f[1])
        p["f"].pop()
        _prune_sources(p)
    if over() and "s" in p:
        for src in p["s"]:
            src[1] = ""
    for key in ("x", "w"):
        if over() and key in p:
            p[key] = _trim(p[key], 80)
    if over():
        p.pop("f", None)
    if over():
        p["a"] = _trim(p["a"], 160)
    if over() and len(p.get("s", [])) > 1:
        p["s"] = p["s"][:1]
    for key in ("x", "w", "s"):
        if over():
            p.pop(key, None)
    while over() and p["a"]:
        excess = len(encode(p)) - budget
        p["a"] = _trim(p["a"], max(0, len(p["a"]) - max(excess, 4)))
    return encode(p)


def fit_search(payload: dict, budget: int) -> bytes:
    """Search payload: {"v", "rc", "r": [[id, section, relevance, snippet], ...]}. Trim snippets, then hits."""
    p = copy.deepcopy(payload)
    hits = p.get("r", [])
    limit = max((len(h[3]) for h in hits), default=0)
    while len(encode(p)) > budget and limit > 40:
        limit = int(limit * 0.8)
        for h in hits:
            h[3] = _trim(h[3], limit)
    while len(encode(p)) > budget and len(hits) > 1:
        hits.pop()
    if len(encode(p)) > budget and hits:
        hits[0][3] = ""
    return encode(p)
