"""Block → chunk windowing.

Target window: ~512 tokens with 64-token overlap. bge-m3 handles up to
8K, but smaller chunks produce better snippet alignment and tighter
reranking scores. We approximate token count as len(text)/2 for Korean
since Kiwi morphemes average about 2 characters.
"""

from __future__ import annotations

from dataclasses import dataclass

from eoditdeora.parsers.base import Block, ParsedDoc

TARGET_CHARS = 1000      # ≈ 500 tokens for Korean
OVERLAP_CHARS = 150


@dataclass
class Chunk:
    ordinal: int
    block_type: str
    page: int | None
    sheet: str | None
    text: str
    char_start: int
    char_end: int

    @property
    def token_count(self) -> int:
        return max(1, len(self.text) // 2)


def _flatten(doc: ParsedDoc) -> tuple[str, list[tuple[int, int, Block]]]:
    """Concatenate blocks into a single string, remembering offsets.

    Returns (joined_text, [(start, end, block), ...]) so the chunker can
    preserve block provenance per window.
    """
    parts: list[str] = []
    offsets: list[tuple[int, int, Block]] = []
    cursor = 0
    for b in doc.blocks:
        text = b.text.strip()
        if not text:
            continue
        offsets.append((cursor, cursor + len(text), b))
        parts.append(text)
        cursor += len(text) + 1  # +1 for the newline separator
    return "\n".join(parts), offsets


def chunk_parsed(doc: ParsedDoc) -> list[Chunk]:
    joined, offsets = _flatten(doc)
    if not joined.strip():
        return []

    chunks: list[Chunk] = []
    ordinal = 0
    i = 0
    while i < len(joined):
        window = joined[i : i + TARGET_CHARS]
        # Prefer breaking on a newline within the last 200 chars of the window
        if len(window) == TARGET_CHARS:
            tail_break = window.rfind("\n", max(0, TARGET_CHARS - 200))
            if tail_break > 0:
                window = window[:tail_break]
        end = i + len(window)
        # Resolve the first block that overlaps this window; use its
        # structural metadata for snippet context.
        block = _block_at(offsets, i)
        chunks.append(
            Chunk(
                ordinal=ordinal,
                block_type=block.type if block else "paragraph",
                page=block.page if block else None,
                sheet=block.sheet if block else None,
                text=window.strip(),
                char_start=i,
                char_end=end,
            )
        )
        ordinal += 1
        if end >= len(joined):
            break
        i = end - OVERLAP_CHARS
        if i < 0:
            i = 0
    return chunks


def _block_at(offsets: list[tuple[int, int, Block]], pos: int) -> Block | None:
    for start, end, block in offsets:
        if start <= pos < end:
            return block
    return offsets[0][2] if offsets else None
