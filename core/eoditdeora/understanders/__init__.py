"""LLM-backed content enrichment.

The Understanders consume `ParsedDoc` records and enrich them with:
  * classification (품의서/회의록/...)
  * 3-length summaries
  * entity extraction

Each stage is its own module so it can be tested in isolation with a
mock `LlmClient`.
"""

from eoditdeora.understanders.classify import classify_document
from eoditdeora.understanders.entities import extract_entities
from eoditdeora.understanders.summarize import summarize_document

__all__ = ["classify_document", "extract_entities", "summarize_document"]
