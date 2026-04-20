"""Configuration primitives for Eoditdeora.

All user-facing configuration lives under the platform-specific application
data directory (see `paths.py`). The config is loaded at startup and reloaded
on file change by the API layer.
"""

from eoditdeora.config.paths import AppPaths, get_paths
from eoditdeora.config.settings import Settings, load_settings, save_settings

__all__ = ["AppPaths", "Settings", "get_paths", "load_settings", "save_settings"]
