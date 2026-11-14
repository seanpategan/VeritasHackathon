"""Tiny disk cache for genuine upstream data (keyed by dataset raster ID, so entries never go stale
within a dataset version). Safe for multiple gunicorn workers on one host: writes are atomic renames.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import time
from pathlib import Path


class DiskCache:
    def __init__(self, root: str, max_age_seconds: int = 30 * 24 * 3600):
        self.root = Path(root)
        self.max_age = max_age_seconds
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str, suffix: str) -> Path:
        digest = hashlib.sha256(key.encode()).hexdigest()
        return self.root / digest[:2] / f"{digest}{suffix}"

    def get(self, key: str, suffix: str = ".bin") -> bytes | None:
        path = self._path(key, suffix)
        try:
            if time.time() - path.stat().st_mtime > self.max_age:
                return None
            return path.read_bytes()
        except (FileNotFoundError, OSError):
            return None

    def set(self, key: str, data: bytes, suffix: str = ".bin") -> None:
        path = self._path(key, suffix)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent)
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
        except OSError:
            pass  # Caching is best-effort; never fail a request because the cache is unwritable.
