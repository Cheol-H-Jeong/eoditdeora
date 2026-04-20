"""File hashing helpers.

- `xxhash_file`: fast 64-bit hash for change-detection. Used as the primary
  doc_id when content bytes must be hashed, since it is ~15x faster than
  sha256 on large files.
- `sha256_file`: cryptographic hash. Used only when we need a stable
  identifier we will publish externally (e.g. in the JSON schema doc_id).
- `blake_file_id`: 128-bit BLAKE3-equivalent via hashlib fallback when
  blake3 is unavailable; reserved for future use.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import xxhash

_CHUNK = 1024 * 1024  # 1 MiB streaming window


def xxhash_file(path: Path) -> str:
    h = xxhash.xxh64()
    with path.open("rb") as fp:
        while chunk := fp.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        while chunk := fp.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def blake_file_id(path: Path) -> str:
    h = hashlib.blake2b(digest_size=16)
    with path.open("rb") as fp:
        while chunk := fp.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()
