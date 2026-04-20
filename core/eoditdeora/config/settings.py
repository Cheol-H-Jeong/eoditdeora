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


class ModelSettings(BaseModel):
    """Which GGUF weights to load. Keep identifiers stable across versions
    so users can swap models without code changes."""

    llm_model_id: str = "gemma-4-26b-a4b-it"
    llm_quant: str = "Q8_0"
    llm_context_tokens: int = 32768

    embedding_model_id: str = "bge-m3"
    embedding_quant: str = "Q8_0"

    reranker_model_id: str = "bge-reranker-v2-m3"
    reranker_quant: str = "Q8_0"

    llama_cpp_host: str = "127.0.0.1"
    llama_cpp_llm_port: int = 17651
    llama_cpp_embed_port: int = 17652
    llama_cpp_rerank_port: int = 17653


class IndexSettings(BaseModel):
    roots: list[str] = Field(default_factory=list)
    ignore_patterns: list[str] = Field(default_factory=list)
    max_file_bytes: int = 256 * 1024 * 1024  # 256 MB hard cap
    incremental_interval_sec: int = 30
    batch_understand_hour: int = 2  # 2am local time for heavy LLM batching


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
