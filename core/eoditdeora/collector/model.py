"""Data types used by the collector."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ChangeKind(str, Enum):
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    MOVED = "moved"


@dataclass(frozen=True)
class CollectedFile:
    path: Path
    root: Path
    size: int
    mtime_ns: int
    change: ChangeKind
    # Only set for MOVED
    previous_path: Path | None = None
