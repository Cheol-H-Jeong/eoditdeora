from __future__ import annotations

from pathlib import Path

from eoditdeora.storage.schema_version import (
    SchemaVersionStore,
    ensure_version,
    get_version,
    set_version,
)


def test_fresh_install_persists_version(tmp_path: Path):
    called = False

    def rebuild() -> None:
        nonlocal called
        called = True

    ensure_version(tmp_path, "meta", 1, rebuild)

    assert called is False
    assert get_version(tmp_path, "meta") == 1


def test_upgrade_triggers_rebuild_callback(tmp_path: Path):
    set_version(tmp_path, "fts", 2)
    calls = 0

    def rebuild() -> None:
        nonlocal calls
        calls += 1

    ensure_version(tmp_path, "fts", 3, rebuild)

    assert calls == 1
    assert get_version(tmp_path, "fts") == 3


def test_same_version_skips_rebuild_callback(tmp_path: Path):
    set_version(tmp_path, "vectors", 3)
    calls = 0

    def rebuild() -> None:
        nonlocal calls
        calls += 1

    ensure_version(tmp_path, "vectors", 3, rebuild)

    assert calls == 0
    assert get_version(tmp_path, "vectors") == 3


def test_schema_version_store_upserts_version(tmp_path: Path):
    store = SchemaVersionStore(tmp_path)
    try:
        store.set_version("fast_index", 1)
        store.set_version("fast_index", 4)
        assert store.get_version("fast_index") == 4
    finally:
        store.close()
