"""Read and write a flat set of files from a local folder or a gs://bucket/prefix."""
from __future__ import annotations

import hashlib
from pathlib import Path


def _split_gs(uri: str) -> tuple[str, str]:
    bucket, _, prefix = uri[len("gs://"):].partition("/")
    return bucket, prefix.strip("/")


def _bucket(name: str):
    from google.cloud import storage

    return storage.Client().bucket(name)


def fingerprint(uri: str) -> str:
    """Cheap content fingerprint of every file under uri (GCS md5 from the listing, no download)."""
    h = hashlib.sha1()
    if uri.startswith("gs://"):
        bucket, prefix = _split_gs(uri)
        for blob in sorted(_bucket(bucket).client.list_blobs(bucket, prefix=prefix + "/" if prefix else ""),
                           key=lambda b: b.name):
            h.update(f"{blob.name}:{blob.md5_hash or blob.etag}\n".encode())
    else:
        for path in sorted(p for p in Path(uri).rglob("*") if p.is_file()):
            h.update(f"{path.relative_to(uri)}:".encode())
            h.update(hashlib.sha1(path.read_bytes()).digest())
    return h.hexdigest()


def read_all(uri: str) -> dict[str, bytes]:
    """Every file under uri, keyed by its path relative to uri."""
    if uri.startswith("gs://"):
        bucket_name, prefix = _split_gs(uri)
        bucket = _bucket(bucket_name)
        start = len(prefix) + 1 if prefix else 0
        return {
            blob.name[start:]: blob.download_as_bytes()
            for blob in bucket.client.list_blobs(bucket_name, prefix=prefix + "/" if prefix else "")
            if not blob.name.endswith("/")
        }
    root = Path(uri)
    if not root.exists():
        return {}
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def read_file(uri: str, name: str) -> bytes | None:
    if uri.startswith("gs://"):
        bucket, prefix = _split_gs(uri)
        blob = _bucket(bucket).blob(f"{prefix}/{name}" if prefix else name)
        return blob.download_as_bytes() if blob.exists() else None
    path = Path(uri) / name
    return path.read_bytes() if path.exists() else None


def write_files(uri: str, files: dict[str, bytes]) -> None:
    if uri.startswith("gs://"):
        bucket_name, prefix = _split_gs(uri)
        bucket = _bucket(bucket_name)
        for name, data in files.items():
            bucket.blob(f"{prefix}/{name}" if prefix else name).upload_from_string(data)
        return
    root = Path(uri)
    root.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (root / name).write_bytes(data)
