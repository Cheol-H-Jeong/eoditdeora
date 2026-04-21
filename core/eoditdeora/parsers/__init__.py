"""Document parsers.

Every parser produces a `ParsedDoc` that conforms to
`schemas/parsed_doc.schema.json`. The orchestrator picks a parser via
`select_parser(path)` which consults the registry below.

Parser modules import their optional native dependencies (lxml, pyhwp,
pdfplumber, python-docx, openpyxl, python-pptx) at module scope. If one
of those dependencies is missing at runtime we log a warning and skip
registering that parser, rather than tearing down the whole process.
This matters for partial installs — e.g. CI running unit tests without
the full Windows/Linux parser stack.
"""

from importlib import import_module

from eoditdeora.parsers.base import ParsedDoc, Parser, ParseResult
from eoditdeora.parsers.registry import register, resolve_parser
from eoditdeora.utils.logging import get_logger

_log = get_logger(__name__)


def _try_import(modname: str) -> None:
    try:
        import_module(f"eoditdeora.parsers.{modname}")
    except ImportError as e:  # optional parser dep missing
        _log.warning("parser_module_skipped", module=modname, error=str(e))


for _m in (
    "txt_parser",
    "md_parser",
    "rtf_parser",
    "odf_parser",
    "docx_parser",
    "xlsx_parser",
    "pptx_parser",
    "pdf_parser",
    "hwpx_parser",
    "hwp_parser",
):
    _try_import(_m)


__all__ = ["ParsedDoc", "ParseResult", "Parser", "register", "resolve_parser"]
