import hashlib
import json
from pathlib import Path

import pytest
from scripts.evaluate_phase_c_components import _producer_environment


def _write_environment(path: Path, **overrides: object) -> None:
    document: dict[str, object] = {
        "table_sha256": "a" * 64,
        "repository_commit": "b" * 40,
        "python": "3.11.0",
        "numpy": "2.4.6",
        "pandas": "3.0.5",
        "scipy": "1.17.1",
        "scikit_learn": "1.9.0",
        **overrides,
    }
    path.write_text(json.dumps(document), encoding="utf-8")


def test_producer_environment_is_bound_to_the_handoff(tmp_path: Path) -> None:
    path = tmp_path / "environment.json"
    _write_environment(path)

    result = _producer_environment(path, table_sha256="a" * 64, repository_commit="b" * 40)

    assert result["file_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result["numpy"] == "2.4.6"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"table_sha256": "c" * 64}, "different OOF table"),
        ({"repository_commit": "d" * 40}, "different repository commit"),
        ({"numpy": None}, "required package version"),
    ],
)
def test_producer_environment_rejects_an_unbound_or_incomplete_file(
    tmp_path: Path, overrides: dict[str, object], message: str
) -> None:
    path = tmp_path / "environment.json"
    _write_environment(path, **overrides)

    with pytest.raises(ValueError, match=message):
        _producer_environment(path, table_sha256="a" * 64, repository_commit="b" * 40)
