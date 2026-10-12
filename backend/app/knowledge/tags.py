"""Asset-tag and language helpers shared by the chunkers."""
from __future__ import annotations

import re

# P-201B, V-102, ESDV-301, TK-501, GD-311, PSV-104 ...
_TAG = re.compile(r"\b([A-Z]{1,5}-\d{2,4}[A-Z]?)(?:/([A-Z]))?\b")
# Document references (SOP-ISO-04, BUL-2026-07) look like tags but are not equipment.
_DOC_REF = re.compile(r"\b(?:SOP|BUL|MAN)(?:-[A-Z0-9]+)+\b")
_UNIT_SPACES = re.compile(r"[^A-Z0-9]+")


def extract_asset_tags(text: str) -> list[str]:
    """Normalized, de-duplicated tags in order of first appearance. 'P-101A/B' gives P-101A and P-101B."""
    seen: dict[str, None] = {}
    for m in _TAG.finditer(_DOC_REF.sub(" ", text.upper())):
        tag, suffix = m.group(1), m.group(2)
        seen.setdefault(tag, None)
        if suffix and tag[-1].isalpha():
            seen.setdefault(tag[:-1] + suffix, None)
    return list(seen)


def normalize_tag(tag: str) -> str:
    return tag.strip().upper()


def normalize_unit(unit: str | None) -> str | None:
    """'Hydrocracker Unit 01' / 'hydrocracker-01' -> 'HYDROCRACKER-01'. The live app already sends this form.
    The word UNIT is dropped only when it sits between a name and a number, so 'UNIT-01' and 'CANARY-UNIT' keep it."""
    if not unit:
        return None
    toks = [t for t in _UNIT_SPACES.split(unit.upper()) if t]
    out = []
    for i, t in enumerate(toks):
        if t == "UNIT" and 0 < i < len(toks) - 1 and toks[i + 1].isdigit():
            continue
        out.append(t)
    return "-".join(out) or None


def detect_language(text: str) -> str:
    """Script-based guess: Tamil block -> 'ta', Chinese -> 'zh', otherwise 'en'.
    Malay and English share a script, so Malay is not distinguished here."""
    tamil = sum(1 for ch in text if "஀" <= ch <= "௿")
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    letters = sum(1 for ch in text if ch.isalpha()) or 1
    if tamil / letters > 0.3:
        return "ta"
    if cjk / letters > 0.3:
        return "zh"
    return "en"
