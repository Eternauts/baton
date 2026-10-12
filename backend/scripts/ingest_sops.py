"""Ingest SOP markdown files from the corpus bucket into knowledge_chunks.

    python -m scripts.ingest_sops            # all *.md under corpus/
    python -m scripts.ingest_sops --dry-run  # chunk only, no embedding, no writes

Safe to rerun: chunk IDs are content hashes, and chunks of a file that no longer exist are pruned.
rules.json and the old index/ files are not touched.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import PurePosixPath

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from google.cloud import storage  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.knowledge.chunking import chunk_markdown  # noqa: E402
from app.knowledge.schema import SOURCE_SOP  # noqa: E402
from app.knowledge.store import prune_source, upsert_chunks  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--prefix", default="corpus/")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    s = get_settings()
    bucket = storage.Client(project=s.project).bucket(s.corpus_bucket)

    total = 0
    for blob in bucket.list_blobs(prefix=args.prefix):
        if not blob.name.endswith(".md"):
            continue
        doc_id = PurePosixPath(blob.name).stem
        chunks = chunk_markdown(doc_id, blob.download_as_text(encoding="utf-8"))
        if args.dry_run:
            print(f"{doc_id}: {len(chunks)} chunks (dry run)")
            continue
        n = upsert_chunks(chunks)
        pruned = prune_source(SOURCE_SOP, doc_id, {c.chunk_id for c in chunks})
        print(f"{doc_id}: {n} chunks upserted, {pruned} stale removed")
        total += n
    print(f"total chunks: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
