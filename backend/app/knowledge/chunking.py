"""Split SOP-style markdown into chunks: one per `##` section, with front matter and asset tags."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.knowledge.schema import MAX_CHUNK_CHARS, SOURCE_SOP, Chunk
from app.knowledge.tags import detect_language, extract_asset_tags

_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_SUPERSEDES = re.compile(r"supersedes\s+(SOP-[A-Z]+-\d+)\s+section\s+(\d+)", re.I)


@dataclass
class ParsedDoc:
    doc_id: str
    title: str
    doc_type: str
    revision: str
    body: str


def parse_front_matter(doc_id: str, raw: str) -> ParsedDoc:
    meta: dict[str, str] = {}
    body = raw
    m = _FRONT.match(raw)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = raw[m.end():]
    return ParsedDoc(
        doc_id=doc_id,
        title=meta.get("title", doc_id),
        doc_type=meta.get("type", "SOP").upper(),
        revision=meta.get("revision", ""),
        body=body.strip(),
    )


def _split_long(text: str, limit: int) -> list[str]:
    """Split on paragraph breaks so no piece exceeds `limit` characters."""
    if len(text) <= limit:
        return [text]
    pieces, cur = [], ""
    for para in re.split(r"\n\s*\n", text):
        if cur and len(cur) + len(para) + 2 > limit:
            pieces.append(cur)
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        pieces.append(cur)
    # a single paragraph can still be too long: hard split
    final = []
    for p in pieces:
        final.extend(p[i:i + limit] for i in range(0, len(p), limit))
    return final


def chunk_markdown(doc_id: str, raw: str) -> list[Chunk]:
    """Turn one SOP/bulletin/manual file into chunks. Text is prefixed with the document ID and
    section heading, which helps retrieval and lets the model cite the section."""
    doc = parse_front_matter(doc_id, raw)
    sections: list[tuple[str, str]] = []
    heading, buf = "Overview", []
    for line in doc.body.splitlines():
        if line.startswith("## "):
            if "".join(buf).strip():
                sections.append((heading, "\n".join(buf).strip()))
            heading, buf = line[3:].strip(), []
        elif line.startswith("# ") and not sections and not "".join(buf).strip():
            continue  # document title line
        else:
            buf.append(line)
    if "".join(buf).strip():
        sections.append((heading, "\n".join(buf).strip()))

    sup = _SUPERSEDES.search(doc.body)
    chunks: list[Chunk] = []
    idx = 0
    for heading, text in sections:
        for piece in _split_long(text, MAX_CHUNK_CHARS - 120):
            full = f"{doc.doc_id} - {doc.title} - {heading}\n{piece}"
            chunks.append(Chunk(
                source_type=SOURCE_SOP,
                source_id=doc.doc_id,
                chunk_index=idx,
                title=f"{doc.doc_id} {heading}",
                text=full,
                language=detect_language(piece),
                asset_tags=extract_asset_tags(full),
                doc_type=doc.doc_type,
                revision=doc.revision,
                # A bulletin that overrides a specific SOP section says so in its body.
                supersedes=f"{sup.group(1)}#{sup.group(2)}" if sup and doc.doc_type == "BULLETIN" else None,
            ))
            idx += 1
    return chunks
