"""Cross-platform application paths.

Uses `platformdirs` so the same code produces:
  - Linux:   ~/.local/share/eoditdeora, ~/.config/eoditdeora, ...
  - Windows: %APPDATA%\\eoditdeora, %LOCALAPPDATA%\\eoditdeora, ...
  - macOS:   ~/Library/Application Support/eoditdeora (future)

User can override the root via the EODITDEORA_HOME environment variable,
which is the recommended way to relocate the whole index (e.g. to a larger
drive) or to run multiple profiles for testing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from platformdirs import PlatformDirs

_APP_NAME = "eoditdeora"
_APP_AUTHOR = "eoditdeora"


@dataclass(frozen=True)
class AppPaths:
    """Resolved absolute paths for all Eoditdeora state."""

    root: Path
    data: Path
    config: Path
    cache: Path
    logs: Path
    index: Path
    thumbnails: Path
    models: Path
    runtime: Path

    def ensure(self) -> None:
        for p in (
            self.data,
            self.config,
            self.cache,
            self.logs,
            self.index,
            self.thumbnails,
            self.models,
            self.runtime,
        ):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_paths() -> AppPaths:
    override = os.environ.get("EODITDEORA_HOME")
    if override:
        root = Path(override).expanduser().resolve()
        paths = AppPaths(
            root=root,
            data=root / "data",
            config=root / "config",
            cache=root / "cache",
            logs=root / "logs",
            index=root / "data" / "index",
            thumbnails=root / "cache" / "thumbnails",
            models=root / "models",
            runtime=root / "runtime",
        )
    else:
        pd = PlatformDirs(_APP_NAME, _APP_AUTHOR, roaming=False)
        data = Path(pd.user_data_dir)
        config = Path(pd.user_config_dir)
        cache = Path(pd.user_cache_dir)
        logs = Path(pd.user_log_dir)
        paths = AppPaths(
            root=data,
            data=data,
            config=config,
            cache=cache,
            logs=logs,
            index=data / "index",
            thumbnails=cache / "thumbnails",
            models=data / "models",
            runtime=data / "runtime",
        )
    paths.ensure()
    return paths
