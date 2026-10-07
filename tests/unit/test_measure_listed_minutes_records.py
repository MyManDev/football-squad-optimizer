"""The listed-minutes measurement compares its control with the measured league's records."""

from __future__ import annotations

import json
from pathlib import Path

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
