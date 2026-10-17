"""The listed-minutes measurement compares its control with the measured league's records."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import scripts.measure_listed_minutes as measure

from squadopt.application.advice_record import STORE_ROOT_LEAGUE_ID, league_record_root

CAPTURE = "fpl-live-20261002T104314Z-8b70515b9b31"


def _record(root: Path, entry_id: int) -> None:
    path = root / "2026-27" / "gw06" / f"entry-{entry_id}" / CAPTURE / "advice.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"advice": [{"published_path": f"advice/{entry_id}/x.json"}]}))


def test_each_league_is_compared_with_its_own_records_only(tmp_path: Path) -> None:
    store = tmp_path / "advice_records"
    _record(league_record_root(store, STORE_ROOT_LEAGUE_ID), 101)
    _record(league_record_root(store, 7), 101)
    _record(league_record_root(store, 7), 202)

    def published(league_id: int) -> int:
        root = league_record_root(store, league_id)
        return measure._published(root, CAPTURE, {})["published_entries"]

    assert published(STORE_ROOT_LEAGUE_ID) == 1
    assert published(7) == 2


def test_the_command_reads_the_record_root_of_the_league_it_measures() -> None:
    source = Path(measure.__file__).read_text(encoding="utf-8")
    assert "league_record_root(arguments.published_records, arguments.league)" in source


def test_the_command_compares_with_the_root_of_the_league_it_measures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Run end to end with the build and the solves stubbed: the comparison is handed the
    store's root for league 352490 and ``leagues/<id>/`` for any other league."""

    store = tmp_path / "advice_records"
    compared: list[Path] = []
    control = SimpleNamespace(source_snapshot_id=CAPTURE, fingerprint="control")
    candidate = SimpleNamespace(fingerprint="candidate")

    def published(root: Path, snapshot_id: str, solved: object) -> dict[str, int]:
        compared.append(root)
        return {"published_entries": 0, "reproduced_by_the_control": 0}

    monkeypatch.setattr(measure, "read_projection_handoff", lambda path: control)
    monkeypatch.setattr(measure.producer, "build", lambda *args, **kwargs: (candidate, None, {}))
    monkeypatch.setattr(measure, "write_projection_handoff", lambda path, handoff: path)
    monkeypatch.setattr(measure, "_players", lambda *args: {"changed": []})
    monkeypatch.setattr(measure, "_solve", lambda *args: {})
    monkeypatch.setattr(measure, "_compare", lambda *args: {})
    monkeypatch.setattr(measure, "repository_provenance", lambda: {})
    monkeypatch.setattr(measure, "write_json", lambda path, record: None)
    monkeypatch.setattr(measure, "_published", published)
    for league in ([], ["--league", "7"]):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "measure_listed_minutes",
                "--snapshot-id",
                CAPTURE,
                "--control-handoff",
                str(tmp_path / "control.json"),
                "--published-records",
                str(store),
                "--work-dir",
                str(tmp_path / "work"),
                "--output",
                str(tmp_path / "out.json"),
                *league,
            ],
        )
        assert measure.main() == 0
    capsys.readouterr()

    assert compared == [store, store / "leagues" / "7"]
