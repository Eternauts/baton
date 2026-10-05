"""Turn raw corpus files into section-aware chunks.

Supported: Markdown/text (optional `key: value` front matter between --- lines),
JSON (any shape; string leaves are flattened) and PDF (one section per page).
"""
from __future__ import annotations

import io
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath

from .rules import RuleSet, tokenize

log = logging.getLogger("sandglass.corpus")

RULES_FILE = "rules.json"
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass
class Chunk:
    id: str  # "<doc_id>#<n>", stable for a given corpus version
    doc_id: str
    title: str
    section: str
    text: str
    doc_type: str = "DOC"
    revision: str = ""
    tags: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return asdict(self)

    @property
    def embed_text(self) -> str:
        return f"{self.title} | {self.section}\n{self.text}"

    def lexical_tokens(self) -> list[str]:
        # Title and section words count too, and tags reached through aliases are indexed explicitly.
        return tokenize(f"{self.title} {self.section} {self.text}") + [t.lower() for t in self.tags]


def _front_matter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    head, sep, body = text[4:].partition("\n---\n")
    if not sep:
        return {}, text
    meta = {}
    for line in head.splitlines():
        key, colon, value = line.partition(":")
        if colon:
            meta[key.strip().lower()] = value.strip()
    return meta, body


def _sections_markdown(body: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    trail: list[str] = []
    current: list[str] = []

    def flush() -> None:
        text = "\n".join(current).strip()
        if text:
            sections.append((" > ".join(t for t in trail[1:] if t) or (trail[0] if trail else ""), text))
        current.clear()

    for line in body.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            flush()
            level = len(m[1])
            trail[:] = trail[: level - 1] + [""] * max(0, level - 1 - len(trail)) + [m[2].strip()]
        else:
            current.append(line)
    flush()
    return sections


def _flatten_json(node, path: str = "") -> list[str]:
    if isinstance(node, str):
        return [f"{path}: {node}" if path else node]
    if isinstance(node, dict):
        return [line for k, v in node.items() for line in _flatten_json(v, f"{path}.{k}" if path else k)]
    if isinstance(node, list):
        return [line for i, v in enumerate(node) for line in _flatten_json(v, f"{path}[{i}]")]
    return [f"{path}: {node}"] if path else [str(node)]


def _pack(text: str, limit: int) -> list[str]:
    """Pack paragraphs into pieces of at most ~limit chars, overlapping by one paragraph."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pieces: list[str] = []
    buf: list[str] = []
    for para in paras:
        while len(para) > limit:  # a single oversized paragraph: split on sentence boundaries
            cut = para.rfind(". ", 0, limit)
            cut = cut + 1 if cut > limit // 3 else limit
            paras_head, para = para[:cut].strip(), para[cut:].strip()
            if buf:
                pieces.append("\n\n".join(buf))
                buf = []
            pieces.append(paras_head)
        if buf and len("\n\n".join(buf + [para])) > limit:
            pieces.append("\n\n".join(buf))
            buf = buf[-1:] if len(buf[-1]) < limit // 3 else []
        buf.append(para)
    if buf:
        pieces.append("\n\n".join(buf))
    return pieces


def parse_file(name: str, raw: bytes, rules: RuleSet, chunk_chars: int) -> list[Chunk]:
    path = PurePosixPath(name)
    doc_id = path.stem
    suffix = path.suffix.lower()
    meta: dict[str, str] = {}
    if suffix in {".md", ".markdown", ".txt"}:
        meta, body = _front_matter(raw.decode("utf-8", errors="replace"))
        sections = _sections_markdown(body)
    elif suffix == ".json":
        data = json.loads(raw)
        if isinstance(data, dict):
            meta = {k: str(data[k]) for k in ("title", "type", "revision") if isinstance(data.get(k), (str, int))}
        sections = [("", "\n".join(_flatten_json(data)))]
    elif suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        sections = [(f"page {i + 1}", page.extract_text() or "") for i, page in enumerate(reader.pages)]
    else:
        return []

    doc_id = meta.get("id", doc_id)
    title = meta.get("title") or next((s for s, _ in sections if s), doc_id)
    if suffix in {".md", ".markdown", ".txt"}:
        first = _HEADING_RE.match(next((l for l in body.splitlines() if l.strip()), ""))
        if first and "title" not in meta:
            title = first[2].strip()
    chunks: list[Chunk] = []
    for section, text in sections:
        for piece in _pack(text, chunk_chars):
            chunks.append(
                Chunk(
                    id=f"{doc_id}#{len(chunks) + 1}",
                    doc_id=doc_id,
                    title=title,
                    section=section,
                    text=piece,
                    doc_type=meta.get("type", "DOC").upper(),
                    revision=meta.get("revision", ""),
                    tags=sorted(rules.tags_in(f"{section}\n{piece}")),
                )
            )
    return chunks


def build_chunks(files: dict[str, bytes], rules: RuleSet, chunk_chars: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    for name in sorted(files):
        if PurePosixPath(name).name == RULES_FILE:
            continue
        try:
            chunks.extend(parse_file(name, files[name], rules, chunk_chars))
        except Exception as exc:  # one bad file must not take the corpus down
            log.warning("skipping unreadable file %s: %s", name, exc)
    return chunks
