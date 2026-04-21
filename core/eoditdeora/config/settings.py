"""User-facing settings persisted as TOML.

Deliberately small. Everything that could be a setting lives here so the UI
has a single source of truth to bind to.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import tomli_w  # type: ignore[import-not-found]
from pydantic import BaseModel, Field

from eoditdeora.config.paths import get_paths

SETTINGS_FILENAME = "settings.toml"


class EndpointConfig(BaseModel):
    """Connection info for an already-running OpenAI-compatible server.

    Eoditdeora never spawns model weights of its own — it connects to
    an existing inference server (llama.cpp, vLLM, Ollama, LM Studio,
    etc.). Each of the three roles (llm / embed / rerank) points at
    at most one endpoint. When `base_url` is empty the role is
    considered disabled and the pipeline gracefully skips that stage.
    """

    base_url: str = ""
    """Root URL. Examples:
      http://127.0.0.1:8080         (llama-server, base has /v1/...)
      http://127.0.0.1:8000/v1      (vLLM -- explicit /v1 prefix)
      http://127.0.0.1:11434        (Ollama native)"""

    model_id: str = ""
    """Model name to send as the `model` field. Empty means 'use server
    default / the single model currently loaded'."""

    api_key: str = ""
    """Only needed if the server was started with --api-key."""

    api_kind: str = "openai"
    """openai | ollama | llama_cpp_native — controls request formatting."""


class ModelSettings(BaseModel):
    """Which already-running inference endpoints Eoditdeora should use.

    No weights are ever downloaded or loaded by this app. All compute
    happens on a pre-existing local server the user operates.
    """

    llm: EndpointConfig = Field(default_factory=EndpointConfig)
    embed: EndpointConfig = Field(default_factory=EndpointConfig)
    rerank: EndpointConfig = Field(default_factory=EndpointConfig)

    llm_context_tokens: int = 32768


_DEFAULT_INDEX_EXTENSIONS: list[str] = [
    ".hwp", ".hwpx",
    ".pdf",
    ".doc", ".docx",
    ".ppt", ".pptx",
    ".xls", ".xlsx",
    ".txt", ".md", ".markdown",
    ".rtf", ".odt", ".ods", ".odp",
]


class IndexSettings(BaseModel):
    roots: list[str] = Field(default_factory=list)
    ignore_patterns: list[str] = Field(default_factory=list)
    max_file_bytes: int = 256 * 1024 * 1024  # 256 MB hard cap
    incremental_interval_sec: int = 30
    batch_understand_hour: int = 2  # 2am local time for heavy LLM batching
    # Extension set for the fast (Everything-tier) file-name index.
    # Content parsing pipeline honors the same list for deciding which
    # files are worth the heavier extraction pass. Users can broaden
    # this in Settings; broadening triggers a rescan of every root.
    extensions: list[str] = Field(default_factory=lambda: list(_DEFAULT_INDEX_EXTENSIONS))


class SearchSettings(BaseModel):
    bm25_top_k: int = 50
    dense_top_k: int = 50
    rerank_top_k: int = 10
    strict_provenance: bool = True  # D9 locked


class PrivacySettings(BaseModel):
    pii_mask_in_ui: bool = True
    telemetry: bool = False  # always false; exposed so the UI can state it
    egress_allowed_hosts: list[str] = Field(
        default_factory=lambda: [
            "huggingface.co",
            "cdn-lfs.huggingface.co",
        ]
    )


class Settings(BaseModel):
    """Top-level settings. Serialized to settings.toml."""

    version: int = 1
    model: ModelSettings = Field(default_factory=ModelSettings)
    index: IndexSettings = Field(default_factory=IndexSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    privacy: PrivacySettings = Field(default_factory=PrivacySettings)


def _settings_path() -> Path:
    return get_paths().config / SETTINGS_FILENAME


def load_settings() -> Settings:
    path = _settings_path()
    if not path.exists():
        settings = Settings()
        save_settings(settings)
        return settings
    with path.open("rb") as fp:
        data = tomllib.load(fp)
    return Settings.model_validate(data)


def save_settings(settings: Settings) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fp:
        tomli_w.dump(settings.model_dump(mode="json"), fp)
