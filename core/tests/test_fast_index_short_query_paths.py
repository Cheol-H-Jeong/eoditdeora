from __future__ import annotations

from pathlib import Path

from eoditdeora.storage.fast_index import FastIndex


def test_short_query_matches_parent_directory_names(tmp_path: Path):
    idx = FastIndex(db_path=tmp_path / "fast.db")
    idx.upsert_many([
        ("/docs/회의/notes.txt", 1, 100.0),
        ("/docs/예산/report.txt", 1, 90.0),
    ])

    rows = idx.search("회의")

    assert [row.path for row in rows] == ["/docs/회의/notes.txt"]


def test_short_query_matches_full_path_when_filename_does_not(tmp_path: Path):
    idx = FastIndex(db_path=tmp_path / "fast.db")
    idx.upsert_many([
        ("/shared/tf/roadmap.txt", 1, 100.0),
        ("/shared/qa/checklist.txt", 1, 90.0),
    ])

    rows = idx.search("tf")

    assert [row.path for row in rows] == ["/shared/tf/roadmap.txt"]
