"""Markdown parser that preserves heading hierarchy as block types."""

from __future__ import annotations

import re
from pathlib import Path

from eoditdeora.parsers.base import Block, ParsedDoc, ParseResult, ParserError
from eoditdeora.parsers.registry import register
from eoditdeora.utils.paths_util import display_path

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_CODE_FENCE = re.compile(r"^```")
_FRONTMATTER = re.compile(r"^---\s*$")


class MdParser:
    name = "md_frontmatter_aware"
    supported_extensions = ("md", "markdown", "mdx")
    fidelity = 5

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower().lstrip(".") in self.supported_extensions

    def parse(self, path: Path, *, doc_id: str) -> ParseResult:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise ParserError(f"decode_failed: {e}") from e

        blocks: list[Block] = []
        lines = text.splitlines()
        i = 0

        # Optional YAML frontmatter
        metadata: dict[str, str] = {}
        if lines and _FRONTMATTER.match(lines[0]):
            i = 1
            while i < len(lines) and not _FRONTMATTER.match(lines[i]):
                if ":" in lines[i]:
                    k, v = lines[i].split(":", 1)
                    metadata[k.strip()] = v.strip().strip('"').strip("'")
                i += 1
            i += 1  # consume closing ---

        para_buf: list[str] = []
        in_code = False
        code_buf: list[str] = []

        def flush_para() -> None:
            if para_buf:
                blocks.append(Block(type="paragraph", text="\n".join(para_buf).strip()))
                para_buf.clear()

        while i < len(lines):
            line = lines[i]
            if _CODE_FENCE.match(line):
                if in_code:
                    blocks.append(Block(type="code", text="\n".join(code_buf)))
                    code_buf.clear()
                    in_code = False
                else:
                    flush_para()
                    in_code = True
                i += 1
                continue
            if in_code:
                code_buf.append(line)
                i += 1
                continue

            m = _HEADING_RE.match(line)
            if m:
                flush_para()
                level = len(m.group(1))
                blocks.append(Block(type="heading", text=m.group(2).strip(), level=level))
            elif not line.strip():
                flush_para()
            else:
                para_buf.append(line)
            i += 1
        flush_para()
        if in_code and code_buf:
            blocks.append(Block(type="code", text="\n".join(code_buf)))

        doc = ParsedDoc(
            doc_id=doc_id,
            source_path=str(path),
            source_path_display=display_path(path),
            format="md",
            parser=self.name,
            fidelity=self.fidelity,
            blocks=blocks,
            metadata=metadata,
        )
        return ParseResult(doc=doc)


register(MdParser())
