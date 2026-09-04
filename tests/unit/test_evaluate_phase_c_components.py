import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
import scripts.evaluate_phase_c_components as runner

from squadopt.data import DataError
from squadopt.experiments.shadow_report import write_document_once


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

    result = runner._producer_environment(path, table_sha256="a" * 64, repository_commit="b" * 40)

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
        runner._producer_environment(path, table_sha256="a" * 64, repository_commit="b" * 40)


def test_loaded_panel_must_contain_exactly_the_declared_seasons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "build_panel",
        lambda *_args, **_kwargs: pd.DataFrame({"season": [*runner.HISTORY_SEASONS, "2025-26"]}),
    )

    with pytest.raises(DataError, match="panel seasons differ"):
        runner._load_development_panel(Path("unused"))


def test_runner_timestamp_allows_an_identical_create_once_replay(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    first: dict[str, object] = {
        "contract_version": runner.REPORT_VERSION,
        "generated_at_utc": "2026-09-04T10:00:00+00:00",
        "execution": {
            "started_at_utc": "2026-09-04T09:00:00+00:00",
            "completed_at_utc": "2026-09-04T10:00:00+00:00",
            "elapsed_seconds": 3600.0,
            "warnings": [],
        },
        "promotion_decision": "not_evaluated",
    }
    replay: dict[str, object] = {
        **first,
        "generated_at_utc": "2026-09-05T10:00:00+00:00",
        "execution": {
            "started_at_utc": "2026-09-05T09:00:00+00:00",
            "completed_at_utc": "2026-09-05T10:00:00+00:00",
            "elapsed_seconds": 3600.0,
            "warnings": [],
        },
    }

    assert write_document_once(first, path) == "written"
    assert write_document_once(replay, path) == "replay"
