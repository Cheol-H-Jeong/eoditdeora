"""Filesystem collection.

- `IgnoreMatcher`: gitignore-style exclusion.
- `Scanner`: one-shot recursive walk producing `CollectedFile` records.
- `Watcher`: long-running watchdog observer that emits the same records on change.
- `service`: RPC glue (add/remove root, status).
"""

from eoditdeora.collector.ignore import IgnoreMatcher
from eoditdeora.collector.model import CollectedFile, ChangeKind
from eoditdeora.collector.scanner import Scanner
from eoditdeora.collector.watcher import Watcher

__all__ = [
    "ChangeKind",
    "CollectedFile",
    "IgnoreMatcher",
    "Scanner",
    "Watcher",
]
