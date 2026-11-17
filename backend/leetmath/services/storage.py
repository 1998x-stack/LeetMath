"""Content-addressed object store (local FS for dev; S3-compatible in production)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from ..config import settings


def put_bytes(data: bytes, prefix: str = "raw") -> tuple[str, str]:
    sha = hashlib.sha256(data).hexdigest()
    key = f"{prefix}/{sha[:2]}/{sha}"
    path = Path(settings.storage_dir) / key
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return key, sha


def get_bytes(key: str) -> bytes:
    if ".." in key:
        raise ValueError("bad key")
    return (Path(settings.storage_dir) / key).read_bytes()
