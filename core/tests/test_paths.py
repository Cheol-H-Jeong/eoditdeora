from pathlib import Path

from eoditdeora.config.paths import get_paths


def test_paths_respect_env_override(tmp_path: Path):
    paths = get_paths()
    assert paths.root == tmp_path.resolve()
    assert paths.data.exists()
    assert paths.index.exists()
    assert paths.models.exists()
    assert paths.logs.exists()
