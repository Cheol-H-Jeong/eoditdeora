import json
import time

from eoditdeora.storage.meta import MetaStore


def _record(doc_id: str, path: str) -> dict:
    return {
        "doc_id": doc_id,
        "root": "/tmp/root",
        "source_path": path,
        "source_path_display": path,
        "format": "txt",
        "parser": "txt_plain",
        "fidelity": 5,
        "size_bytes": 123,
        "mtime_ns": time.time_ns(),
        "indexed_at": time.time_ns(),
        "classification": None,
        "summary_oneline": None,
        "summary_paragraph": None,
        "summary_detailed": None,
        "language": None,
        "warnings_json": "[]",
        "metadata_json": "{}",
    }


def test_upsert_and_count():
    s = MetaStore()
    try:
        assert s.count_documents() == 0
        s.upsert_document(_record("sha256:" + "a" * 64, "/tmp/a.txt"))
        s.upsert_document(_record("sha256:" + "b" * 64, "/tmp/b.txt"))
        assert s.count_documents() == 2
        # Re-upsert same doc_id should not duplicate.
        s.upsert_document(_record("sha256:" + "a" * 64, "/tmp/a.txt"))
        assert s.count_documents() == 2
    finally:
        s.close()


def test_chunks_replace_atomically():
    s = MetaStore()
    try:
        s.upsert_document(_record("sha256:" + "a" * 64, "/tmp/a.txt"))
        s.replace_chunks(
            "sha256:" + "a" * 64,
            [
                {
                    "chunk_id": "sha256:" + "a" * 64 + ":0",
                    "doc_id": "sha256:" + "a" * 64,
                    "ordinal": 0,
                    "block_type": "paragraph",
                    "page": None,
                    "sheet": None,
                    "text": "첫 청크",
                    "char_start": 0,
                    "char_end": 5,
                    "token_count": 3,
                }
            ],
        )
        chunks = s.get_chunks_for_doc("sha256:" + "a" * 64)
        assert len(chunks) == 1
        assert chunks[0]["text"] == "첫 청크"
    finally:
        s.close()


def test_get_documents_batches_unique_ids():
    s = MetaStore()
    try:
        doc_a = "sha256:" + "a" * 64
        doc_b = "sha256:" + "b" * 64
        s.upsert_document(_record(doc_a, "/tmp/a.txt"))
        s.upsert_document(_record(doc_b, "/tmp/b.txt"))

        got = s.get_documents([doc_a, "", doc_b, doc_a, "missing"])

        assert set(got) == {doc_a, doc_b}
        assert got[doc_a]["source_path"] == "/tmp/a.txt"
        assert got[doc_b]["source_path"] == "/tmp/b.txt"
    finally:
        s.close()


def test_job_queue_claim_complete():
    s = MetaStore()
    try:
        jid = s.enqueue_job("embed", json.dumps({"x": 1}))
        claimed = s.claim_job("embed")
        assert claimed is not None
        assert claimed["id"] == jid
        s.complete_job(jid)
        # Next claim finds nothing.
        assert s.claim_job("embed") is None
    finally:
        s.close()
