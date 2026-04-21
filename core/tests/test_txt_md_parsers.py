import zipfile
from pathlib import Path

from eoditdeora.parsers.md_parser import MdParser
from eoditdeora.parsers.odf_parser import OpenDocumentParser
from eoditdeora.parsers.rtf_parser import RtfParser
from eoditdeora.parsers.txt_parser import TxtParser


def test_txt_parser_utf8(tmp_path: Path):
    f = tmp_path / "hello.txt"
    f.write_text("첫 번째 문단\n\n두 번째 문단", encoding="utf-8")
    res = TxtParser().parse(f, doc_id="sha256:" + "b" * 64)
    assert res.doc.format == "txt"
    assert len(res.doc.blocks) == 2
    assert res.doc.metadata["encoding"] == "utf-8"


def test_txt_parser_cp949(tmp_path: Path):
    f = tmp_path / "legacy.txt"
    f.write_bytes("한글 레거시".encode("cp949"))
    res = TxtParser().parse(f, doc_id="sha256:" + "c" * 64)
    assert res.doc.metadata["encoding"] == "cp949"
    assert res.doc.blocks[0].text.startswith("한글")


def test_md_parser_headings_and_frontmatter(tmp_path: Path):
    f = tmp_path / "note.md"
    f.write_text(
        "---\n"
        "author: cheol\n"
        "---\n"
        "# 제목\n"
        "본문입니다.\n\n"
        "## 하위제목\n"
        "다음 문단.",
        encoding="utf-8",
    )
    res = MdParser().parse(f, doc_id="sha256:" + "d" * 64)
    assert res.doc.metadata == {"author": "cheol"}
    kinds = [(b.type, b.level) for b in res.doc.blocks]
    assert ("heading", 1) in kinds
    assert ("heading", 2) in kinds
    assert any(b.type == "paragraph" for b in res.doc.blocks)


def test_rtf_parser_extracts_unicode_text_and_paragraphs(tmp_path: Path):
    f = tmp_path / "memo.rtf"
    f.write_text(
        "{\\rtf1\\ansi\\ansicpg949\\deff0\\uc1 "
        "{\\fonttbl{\\f0\\fnil Gulim;}}"
        "\\viewkind4\\pard "
        "\\u-14840?\\u-16208? \\u-11128?\\u-14504?\\u-16100?\\par "
        "\\u-10612?\\u-14504?\\u-18339? 2026\\par}",
        encoding="latin-1",
    )
    res = RtfParser().parse(f, doc_id="sha256:" + "e" * 64)
    assert res.doc.format == "rtf"
    assert res.doc.parse_status == "ok"
    assert [b.text for b in res.doc.blocks] == ["예산 품의서", "회의록 2026"]


def test_rtf_parser_ignores_metadata_groups_and_decodes_hex_escapes(tmp_path: Path):
    f = tmp_path / "latin.rtf"
    f.write_text(
        "{\\rtf1\\ansi"
        "{\\info{\\title Hidden Title}}"
        "\\pard Caf\\'e9 budget\\tab draft\\par}",
        encoding="latin-1",
    )
    res = RtfParser().parse(f, doc_id="sha256:" + "f" * 64)
    assert res.doc.parse_status == "ok"
    assert [b.text for b in res.doc.blocks] == ["Café budget\tdraft"]


def test_rtf_parser_decodes_cp949_hex_escapes(tmp_path: Path):
    f = tmp_path / "legacy-korean.rtf"
    f.write_text(
        "{\\rtf1\\ansi\\ansicpg949\\deff0 "
        "\\pard "
        "\\'c7\\'d1\\'b1\\'db "
        "\\'bf\\'b9\\'bb\\'ea\\'be\\'c8\\par}",
        encoding="latin-1",
    )
    res = RtfParser().parse(f, doc_id="sha256:" + "0" * 64)
    assert res.doc.parse_status == "ok"
    assert [b.text for b in res.doc.blocks] == ["한글 예산안"]


def test_odt_parser_extracts_headings_paragraphs_and_metadata(tmp_path: Path):
    f = tmp_path / "memo.odt"
    _write_odf_zip(
        f,
        content_xml=(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<office:document-content '
            'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
            "<office:body><office:text>"
            '<text:h text:outline-level="1">회의록</text:h>'
            "<text:p>예산 품의서 초안</text:p>"
            "<text:list><text:list-item><text:p>후속 일정</text:p></text:list-item></text:list>"
            "</office:text></office:body>"
            "</office:document-content>"
        ),
        meta_xml=(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<office:document-meta '
            'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            "<office:meta>"
            "<dc:title>주간 회의록</dc:title>"
            "<dc:creator>Cheol</dc:creator>"
            "</office:meta>"
            "</office:document-meta>"
        ),
    )
    res = OpenDocumentParser().parse(f, doc_id="sha256:" + "1" * 64)
    assert res.doc.parse_status == "ok"
    assert [(b.type, b.text) for b in res.doc.blocks] == [
        ("heading", "회의록"),
        ("paragraph", "예산 품의서 초안"),
        ("list_item", "후속 일정"),
    ]
    assert res.doc.metadata["title"] == "주간 회의록"
    assert res.doc.metadata["author"] == "Cheol"


def test_odt_parser_does_not_duplicate_table_cells_as_paragraphs(tmp_path: Path):
    f = tmp_path / "table.odt"
    _write_odf_zip(
        f,
        content_xml=(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<office:document-content '
            'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
            'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
            "<office:body><office:text>"
            "<text:p>본문 요약</text:p>"
            "<table:table>"
            "<table:table-row>"
            "<table:table-cell><text:p>항목</text:p></table:table-cell>"
            "<table:table-cell><text:p>금액</text:p></table:table-cell>"
            "</table:table-row>"
            "<table:table-row>"
            "<table:table-cell><text:p>운영비</text:p></table:table-cell>"
            "<table:table-cell><text:p>120000</text:p></table:table-cell>"
            "</table:table-row>"
            "</table:table>"
            "</office:text></office:body>"
            "</office:document-content>"
        ),
    )
    res = OpenDocumentParser().parse(f, doc_id="sha256:" + "4" * 64)
    assert res.doc.parse_status == "ok"
    assert [(b.type, b.text) for b in res.doc.blocks] == [
        ("paragraph", "본문 요약"),
        ("table", "항목\t금액\n운영비\t120000"),
    ]


def test_ods_parser_extracts_sheet_rows(tmp_path: Path):
    f = tmp_path / "budget.ods"
    _write_odf_zip(
        f,
        content_xml=(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<office:document-content '
            'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
            'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
            "<office:body><office:spreadsheet>"
            '<table:table table:name="예산안">'
            "<table:table-row>"
            "<table:table-cell><text:p>항목</text:p></table:table-cell>"
            "<table:table-cell><text:p>금액</text:p></table:table-cell>"
            "</table:table-row>"
            "<table:table-row>"
            "<table:table-cell><text:p>운영비</text:p></table:table-cell>"
            "<table:table-cell><text:p>120000</text:p></table:table-cell>"
            "</table:table-row>"
            "</table:table>"
            "</office:spreadsheet></office:body>"
            "</office:document-content>"
        ),
    )
    res = OpenDocumentParser().parse(f, doc_id="sha256:" + "2" * 64)
    assert res.doc.parse_status == "ok"
    assert len(res.doc.blocks) == 1
    assert res.doc.blocks[0].type == "table"
    assert res.doc.blocks[0].sheet == "예산안"
    assert res.doc.blocks[0].text == "항목\t금액\n운영비\t120000"


def test_ods_parser_reads_attribute_only_cell_values(tmp_path: Path):
    f = tmp_path / "typed-values.ods"
    _write_odf_zip(
        f,
        content_xml=(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<office:document-content '
            'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
            'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
            "<office:body><office:spreadsheet>"
            '<table:table table:name="원본값">'
            "<table:table-row>"
            '<table:table-cell office:value-type="string" office:string-value="항목"/>'
            '<table:table-cell office:value-type="string" office:string-value="값"/>'
            "</table:table-row>"
            "<table:table-row>"
            '<table:table-cell office:value-type="string" office:string-value="운영비"/>'
            '<table:table-cell office:value-type="float" office:value="120000"/>'
            "</table:table-row>"
            "<table:table-row>"
            '<table:table-cell office:value-type="string" office:string-value="승인"/>'
            '<table:table-cell office:value-type="boolean" office:boolean-value="true"/>'
            "</table:table-row>"
            "</table:table>"
            "</office:spreadsheet></office:body>"
            "</office:document-content>"
        ),
    )
    res = OpenDocumentParser().parse(f, doc_id="sha256:" + "5" * 64)
    assert res.doc.parse_status == "ok"
    assert len(res.doc.blocks) == 1
    assert res.doc.blocks[0].sheet == "원본값"
    assert res.doc.blocks[0].text == "항목\t값\n운영비\t120000\n승인\ttrue"


def test_odp_parser_extracts_slide_text(tmp_path: Path):
    f = tmp_path / "deck.odp"
    _write_odf_zip(
        f,
        content_xml=(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<office:document-content '
            'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
            'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
            "<office:body><office:presentation>"
            '<draw:page draw:name="슬라이드 1">'
            "<draw:frame><draw:text-box>"
            "<text:p>분기 실적</text:p>"
            "<text:p>매출 15% 증가</text:p>"
            "</draw:text-box></draw:frame>"
            "</draw:page>"
            "</office:presentation></office:body>"
            "</office:document-content>"
        ),
    )
    res = OpenDocumentParser().parse(f, doc_id="sha256:" + "3" * 64)
    assert res.doc.parse_status == "ok"
    assert len(res.doc.blocks) == 1
    assert res.doc.blocks[0].text == "분기 실적\n매출 15% 증가"
    assert res.doc.blocks[0].meta["slide"] == "슬라이드 1"


def _write_odf_zip(path: Path, *, content_xml: str, meta_xml: str | None = None) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument")
        zf.writestr("content.xml", content_xml)
        if meta_xml is not None:
            zf.writestr("meta.xml", meta_xml)
