"""Turn synced capsules (one handover) into knowledge chunks, without personal names."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable

from app.knowledge.schema import MAX_CHUNK_CHARS, SOURCE_HANDOVER, Chunk
from app.knowledge.tags import detect_language, extract_asset_tags, normalize_tag, normalize_unit

# Words in an operator ID that are not names (TECH-ARUN-42 -> ARUN).
_ID_NOISE = {"TECH", "OPERATOR", "OP", "SUP", "SUPERVISOR", "OFFLINE", "EDGE", "DEVICE", "FLUTTER", "USER"}
_BY_NAME = re.compile(r"\s*,?\s*\b(?:by|from|with)\s+(?:supervisor\s+|operator\s+|mr\.?\s+|ms\.?\s+)?[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})?\b")


def _names_from_operator_id(operator_id: str | None) -> list[str]:
    toks = re.split(r"[^A-Za-z]+", operator_id or "")
    return [t for t in toks if len(t) > 2 and t.upper() not in _ID_NOISE]


def scrub_names(text: str, known_names: Iterable[str] = ()) -> str:
    """Best-effort removal of personal names: 'by <Name>' patterns and any name derived from the
    operator ID. It cannot catch every name in free text."""
    out = text
    for n in known_names:
        out = re.sub(rf"\b{re.escape(n)}\b", "the operator", out, flags=re.I)
    out = _BY_NAME.sub("", out)
    return re.sub(r"\s{2,}", " ", out).strip()


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _pretty_shift(shift_name: str | None) -> str:
    """'NIGHT-SHIFT-A' -> 'Night shift A'; 'DAY' -> 'Day shift'."""
    if not shift_name:
        return "Unknown shift"
    toks = [t for t in re.split(r"[^A-Za-z0-9]+", shift_name) if t]
    lowered = [t.lower() for t in toks]
    if "shift" in lowered:
        k = lowered.index("shift")
        before, after = toks[:k], toks[k + 1:]
    else:
        before, after = toks, []
    words = [w.capitalize() for w in before] + ["shift"] + [w.upper() if len(w) == 1 else w.capitalize() for w in after]
    return " ".join(words)


def capsule_line(cap: dict[str, Any], shift_label: str, names: list[str], role: str) -> str:
    """e.g. 'P-201B: RUNNING. Vibrating heavily, seal looks wet. (operator, 14:30, Night shift)'"""
    tag = normalize_tag(cap.get("asset_tag") or "UNTAGGED")
    state = (cap.get("asserted_state") or "UNKNOWN").upper()
    note = scrub_names(cap.get("text_transcript") or "", names).rstrip(".")
    ts = _parse_ts(cap.get("timestamp"))
    when = ts.strftime("%H:%M") if ts else "time unknown"
    body = f"{tag}: {state}." + (f" {note}." if note else "")
    return f"{body} ({role}, {when}, {shift_label})"


def chunk_handover(handover_id: str, capsules: list[dict[str, Any]], *, unit_name: str | None,
                   shift_name: str | None, operator_id: str | None = None, author_role: str = "operator",
                   source_type: str = SOURCE_HANDOVER, seeded: bool = False) -> list[Chunk]:
    """Group capsule lines into chunks under the size limit. Each chunk starts with a header line."""
    unit = normalize_unit(unit_name)
    shift_label = _pretty_shift(shift_name)
    names = _names_from_operator_id(operator_id)
    title = f"Handover, {unit or 'unknown unit'}, {shift_label}"
    header = f"{title}."
    lines = [(c, capsule_line(c, shift_label, names, author_role)) for c in capsules]
    created = max((t for t in (_parse_ts(c.get("timestamp")) for c in capsules) if t), default=None)

    groups: list[list[tuple[dict, str]]] = []
    cur: list[tuple[dict, str]] = []
    size = len(header)
    for item in lines:
        if cur and size + len(item[1]) + 1 > MAX_CHUNK_CHARS:
            groups.append(cur)
            cur, size = [], len(header)
        cur.append(item)
        size += len(item[1]) + 1
    if cur:
        groups.append(cur)

    chunks = []
    for idx, grp in enumerate(groups):
        text = header + "\n" + "\n".join(line for _, line in grp)
        tags = list(dict.fromkeys(
            [normalize_tag(c["asset_tag"]) for c, _ in grp if c.get("asset_tag") and c["asset_tag"].upper() != "UNTAGGED"]
            + extract_asset_tags(text)))
        chunks.append(Chunk(
            source_type=source_type, source_id=handover_id, chunk_index=idx, title=title, text=text,
            language=detect_language(text), unit=unit, asset_tags=tags, shift_id=shift_name,
            author_role=author_role, created_at=created, seeded=seeded))
    return chunks
