"""Classify / summarize / entity understanders.

We inject a FakeLlmClient that returns prescripted JSON, verifying
parsing, sanitization, and fallback paths.
"""

from __future__ import annotations

from typing import Any

from eoditdeora.parsers.base import Block, ParsedDoc
from eoditdeora.understanders.classify import classify_document
from eoditdeora.understanders.entities import extract_entities
from eoditdeora.understanders.summarize import summarize_document


class FakeLlm:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def chat(self, system: str, user: str, **kw: Any) -> str:  # noqa: ARG002
        self.calls.append({"system": system, "user": user, "kw": kw})
        return self._responses.pop(0)


def _doc(text: str = "내용") -> ParsedDoc:
    return ParsedDoc(
        doc_id="sha256:" + "a" * 64,
        source_path="/tmp/x.txt",
        source_path_display="/tmp/x.txt",
        format="txt",
        parser="txt_plain",
        fidelity=5,
        blocks=[Block(type="paragraph", text=text)],
    )


def test_classify_parses_valid_json():
    llm = FakeLlm(['{"classification": "품의서", "confidence": 0.92}'])
    result = classify_document(_doc(), llm)
    assert result == {"classification": "품의서", "confidence": 0.92}


def test_classify_falls_back_on_malformed_output():
    llm = FakeLlm(["not json at all"])
    result = classify_document(_doc(), llm)
    assert result["classification"] == "기타"
    assert result["confidence"] == 0.0


def test_summarize_normalizes_outputs():
    llm = FakeLlm(
        [
            '{"oneline": "' + "가" * 200 + '", '
            '"paragraph": "세 문장 요약", '
            '"detailed": "열 문장 요약"}'
        ]
    )
    result = summarize_document(_doc(), llm)
    # Oneline should be truncated so it fits UI chrome.
    assert len(result["oneline"]) <= 120
    assert result["paragraph"] == "세 문장 요약"


def test_summarize_returns_empty_dict_on_malformed():
    llm = FakeLlm(["not json"])
    result = summarize_document(_doc(), llm)
    assert result == {"oneline": "", "paragraph": "", "detailed": ""}


def test_extract_entities_filters_unknown_kinds():
    llm = FakeLlm(
        [
            '{"entities": ['
            '  {"kind": "person", "value": "김철수", "normalized": "김철수"},'
            '  {"kind": "unknown_kind", "value": "drop me"},'
            '  {"kind": "money", "value": "120,000,000원"},'
            '  {"kind": "date", "value": ""}'
            "]}"
        ]
    )
    result = extract_entities(_doc(), llm)
    kinds = [e["kind"] for e in result]
    assert "person" in kinds
    assert "money" in kinds
    assert "unknown_kind" not in kinds
    # Empty value dropped.
    assert all(e["value"] for e in result)


def test_extract_entities_handles_malformed_output():
    llm = FakeLlm(["not json"])
    assert extract_entities(_doc(), llm) == []


def test_classify_prompt_includes_head_text():
    llm = FakeLlm(['{"classification": "회의록", "confidence": 0.8}'])
    doc = _doc("민감한 키워드 abcxyz 회의 요약")
    classify_document(doc, llm)
    assert "abcxyz" in llm.calls[0]["user"]
