from pathlib import Path

from eoditdeora.utils.hashing import blake_file_id, sha256_file, xxhash_file


def test_hashes_are_stable(tmp_path: Path):
    f = tmp_path / "x.txt"
    f.write_bytes(b"hello world")
    assert xxhash_file(f) == xxhash_file(f)
    assert sha256_file(f) == sha256_file(f)
    assert blake_file_id(f) == blake_file_id(f)


def test_sha256_matches_known_value(tmp_path: Path):
    import hashlib

    f = tmp_path / "x.txt"
    content = b"an example to compare"
    f.write_bytes(content)
    assert sha256_file(f) == hashlib.sha256(content).hexdigest()


def test_hashes_change_with_content(tmp_path: Path):
    f = tmp_path / "x.txt"
    f.write_bytes(b"a")
    a = xxhash_file(f)
    f.write_bytes(b"b")
    b = xxhash_file(f)
    assert a != b


def test_large_file_streaming(tmp_path: Path):
    f = tmp_path / "big.bin"
    # Write 3MB so streaming path is definitely exercised.
    f.write_bytes(b"0" * (3 * 1024 * 1024))
    # Should just return a reasonable hex digest without OOM.
    digest = sha256_file(f)
    assert len(digest) == 64
