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


def test_short_query_expands_office_synonyms_for_filename_search(tmp_path: Path):
    idx = FastIndex(db_path=tmp_path / "fast.db")
    idx.upsert_many([
        ("/docs/2026_예산안_초안.hwpx", 1, 100.0),
        ("/docs/회의록.hwpx", 1, 90.0),
    ])

    rows = idx.search("예산")

    assert [row.path for row in rows] == ["/docs/2026_예산안_초안.hwpx"]


def test_long_query_expands_office_synonyms_for_filename_search(tmp_path: Path):
    idx = FastIndex(db_path=tmp_path / "fast.db")
    idx.upsert_many([
        ("/docs/연차계획서.docx", 1, 100.0),
        ("/docs/출장보고서.docx", 1, 90.0),
    ])

    rows = idx.search("휴가")

    assert [row.path for row in rows] == ["/docs/연차계획서.docx"]


def test_multi_term_query_matches_terms_in_any_order(tmp_path: Path):
    idx = FastIndex(db_path=tmp_path / "fast.db")
    idx.upsert_many([
        ("/docs/2026_예산안_회의록.hwpx", 1, 100.0),
        ("/docs/회의록_예산안.hwpx", 1, 99.0),
        ("/docs/예산안초안.hwpx", 1, 98.0),
    ])

    rows = idx.search("회의록 예산안")

    assert [row.path for row in rows] == [
        "/docs/2026_예산안_회의록.hwpx",
        "/docs/회의록_예산안.hwpx",
    ]


def test_multi_term_query_uses_synonyms_per_term(tmp_path: Path):
    idx = FastIndex(db_path=tmp_path / "fast.db")
    idx.upsert_many([
        ("/docs/연차_신청_양식.docx", 1, 100.0),
        ("/docs/휴가계.docx", 1, 90.0),
        ("/docs/출장_신청_양식.docx", 1, 80.0),
    ])

    rows = idx.search("휴가 신청")

    assert [row.path for row in rows] == ["/docs/연차_신청_양식.docx"]
