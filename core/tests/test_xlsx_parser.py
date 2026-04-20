from pathlib import Path

from eoditdeora.parsers.xlsx_parser import XlsxParser

from .fixtures import make_xlsx


def test_xlsx_single_sheet(tmp_path: Path):
    path = make_xlsx(
        tmp_path / "budget.xlsx",
        {
            "2025년": [
                ["항목", "1분기", "2분기"],
                ["인건비", 12_000_000, 13_000_000],
                ["운영비", 4_500_000, 4_700_000],
            ]
        },
    )
    res = XlsxParser().parse(path, doc_id="sha256:" + "4" * 64)
    assert res.doc.format == "xlsx"
    tables = [b for b in res.doc.blocks if b.type == "table"]
    assert len(tables) == 1
    assert tables[0].sheet == "2025년"
    assert "인건비" in tables[0].text
    assert "12000000" in tables[0].text  # openpyxl renders numbers as-is
    assert tables[0].meta["rows"] == 3
    assert tables[0].meta["cols"] == 3


def test_xlsx_multiple_sheets(tmp_path: Path):
    path = make_xlsx(
        tmp_path / "multi.xlsx",
        {
            "요약": [["항목", "값"], ["합계", 100]],
            "상세": [["날짜", "금액"], ["2025-01", 40], ["2025-02", 60]],
        },
    )
    res = XlsxParser().parse(path, doc_id="sha256:" + "5" * 64)
    sheet_names = {b.sheet for b in res.doc.blocks if b.type == "table"}
    assert sheet_names == {"요약", "상세"}


def test_xlsx_chunks_large_sheets(tmp_path: Path):
    # Force the 500-row chunk boundary.
    rows = [["idx", "value"]]
    for i in range(1200):
        rows.append([i, f"데이터-{i}"])
    path = make_xlsx(tmp_path / "big.xlsx", {"Sheet1": rows})
    res = XlsxParser().parse(path, doc_id="sha256:" + "6" * 64)
    tables = [b for b in res.doc.blocks if b.type == "table"]
    # 1201 rows / 500 per chunk → 3 chunks
    assert len(tables) == 3


def test_xlsx_empty_rows_dropped(tmp_path: Path):
    path = make_xlsx(
        tmp_path / "sparse.xlsx",
        {"Sheet1": [["A"], [None], [None], ["B"]]},
    )
    res = XlsxParser().parse(path, doc_id="sha256:" + "7" * 64)
    table = [b for b in res.doc.blocks if b.type == "table"][0]
    assert "A" in table.text
    assert "B" in table.text
    assert table.meta["rows"] == 2
