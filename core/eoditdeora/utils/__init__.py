"""Shared utilities: logging, hashing, cross-OS path handling."""

from eoditdeora.utils.hashing import blake_file_id, sha256_file, xxhash_file
from eoditdeora.utils.logging import configure_logging, get_logger
from eoditdeora.utils.paths_util import (
    display_path,
    normalize_path,
    path_is_hidden,
    safe_relative,
)

__all__ = [
    "blake_file_id",
    "configure_logging",
    "display_path",
    "get_logger",
    "normalize_path",
    "path_is_hidden",
    "safe_relative",
    "sha256_file",
    "xxhash_file",
]
