"""The proposed #1002 instrument, exercised only on synthetic FPL-shaped payloads."""

from __future__ import annotations

import json
import math
import subprocess
from collections.abc import Callable
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from scripts import measure_strategy_rule_scale as measurement

from squadopt.data.snapshots import SnapshotMetadata, write_snapshot


def _bytes(value: Any) -> bytes:
    return json.dumps(value).encode()


def _payloads(n: int = 6, league: int = measurement.PRIMARY_LEAGUE) -> dict[str, bytes]:
    payloads = {
        "bootstrap-static.json": _bytes(
            {
                "events": [
                    {"id": week, "finished": True, "data_checked": True} for week in range(1, n + 1)
                ]
            }
        ),
        f"league-{league}-standings.json": _bytes(
            {
                "league": {"id": league},
                "standings": {
                    "has_next": False,
                    "results": [
                        {
                            "entry": entry,
                            "entry_name": "Synthetic",
                            "player_name": "Synthetic",
                            "rank": entry,
                        }
                        for entry in (1, 2, 3)
                    ],
                },
            }
        ),
    }
    for entry in (1, 2, 3):
        points = (entry - 1) * 15
        payloads[f"entry-{entry}-history.json"] = _bytes(
            {
                "current": [
                    {
                        "event": week,
                        "points": points,
                        "total_points": points * week,
                        "event_transfers_cost": 0,
                    }
                    for week in range(1, n + 1)
                ],
                "chips": [{"name": "bboost", "event": 2}],
            }
        )
    return payloads


def _measure(
    payloads: dict[str, bytes], n: int = 6, listed: tuple[int, ...] = ()
) -> dict[str, Any]:
    return measurement.measure_payloads(
        payloads, league=measurement.PRIMARY_LEAGUE, through_gameweek=n, listed_leagues=listed
    )


def test_hand_computed_rms_counts_unordered_pair_weeks() -> None:
    reading = measurement.pair_week_reading(({1: 0}, {1: 3}, {1: 6}), (1,))
    assert reading.squared_difference_sum == 9 + 36 + 9
    assert reading.counted == 3
    assert reading.scale() is not None
    assert float(reading.scale()) == pytest.approx(math.sqrt(18))
    assert reading.document()["scale_rounded"] == 4.2


def test_transfer_cost_is_subtracted_without_changing_chip_week_scores() -> None:
    payloads = _payloads()
    history = json.loads(payloads["entry-2-history.json"])
    history["current"][3].update(points=25, event_transfers_cost=10)
    payloads["entry-2-history.json"] = _bytes(history)
    record = _measure(payloads)
    assert record["scale"]["scale_rounded"] == 21.2
    assert record["scale"]["pair_weeks_counted"] == 18


def test_missing_row_drops_only_its_two_pair_weeks() -> None:
    payloads = _payloads()
    history = json.loads(payloads["entry-3-history.json"])
    history["current"] = [row for row in history["current"] if row["event"] != 4]
    payloads["entry-3-history.json"] = _bytes(history)
    record = _measure(payloads)
    assert record["scale"]["pair_weeks_counted"] == 16
    assert record["scale"]["pair_weeks_dropped"] == 2
    assert record["by_gameweek"][3]["pair_weeks_counted"] == 1
    assert record["by_gameweek"][4]["pair_weeks_counted"] == 3
    cumulative = record["cumulative_comparisons"][1]
    assert cumulative["pair_counted"] == 1
    assert cumulative["pair_dropped"] == 2
    assert cumulative["cumulative_rms"] == 60


@pytest.mark.parametrize("field", ["finished", "data_checked"])
@pytest.mark.parametrize("week", [4, 6])
def test_unfinished_or_unchecked_gameweek_refuses(field: str, week: int) -> None:
    payloads = _payloads()
    bootstrap = json.loads(payloads["bootstrap-static.json"])
    bootstrap["events"][week - 1][field] = False
    payloads["bootstrap-static.json"] = _bytes(bootstrap)
    with pytest.raises(measurement.ScaleMeasurementError, match="every prior week checked"):
        _measure(payloads)


@pytest.mark.parametrize("n,through", [(5, 5), (7, 6), (6, 7)])
def test_checkpoint_requires_six_weeks_and_highest_settled_week(n: int, through: int) -> None:
    with pytest.raises(measurement.ScaleMeasurementError, match="highest finished"):
        _measure(_payloads(n), through)


def test_missing_transfer_cost_refuses_even_an_observed_zero_score() -> None:
    payloads = _payloads()
    history = json.loads(payloads["entry-1-history.json"])
    del history["current"][4]["event_transfers_cost"]
    payloads["entry-1-history.json"] = _bytes(history)
    with pytest.raises(measurement.ScaleMeasurementError, match="event_transfers_cost"):
        _measure(payloads)


def test_missing_standings_member_history_is_not_an_exclusion() -> None:
    payloads = _payloads()
    del payloads["entry-3-history.json"]
    with pytest.raises(measurement.ScaleMeasurementError, match="required history payload"):
        _measure(payloads)


@pytest.mark.parametrize("value,expected", [("21.25", 21.3), ("21.15", 21.2), ("0.05", 0.1)])
def test_rounding_is_half_up_at_exact_ties(value: str, expected: float) -> None:
    assert measurement.round_half_up(Decimal(value)) == expected
    assert measurement.Reading(7225, 16, 16).document()["scale_rounded"] == 21.3


def test_three_week_control_refuses_before_emitting_a_binding_record() -> None:
    payloads = _payloads()
    history = json.loads(payloads["entry-3-history.json"])
    history["current"][0]["points"] = 99
    payloads["entry-3-history.json"] = _bytes(history)
    with pytest.raises(measurement.ScaleMeasurementError, match="Explain on #1002 before step 4"):
        _measure(payloads)


def test_secondary_is_only_an_already_listed_captured_league() -> None:
    payloads = _payloads()
    payloads.update(
        {key: value for key, value in _payloads(league=123).items() if key.startswith("league-")}
    )
    assert _measure(payloads)["secondary_leagues"] == []
    record = _measure(payloads, listed=(measurement.PRIMARY_LEAGUE, 123, 456))
    assert len(record["secondary_leagues"]) == 1
    assert record["secondary_leagues"][0]["league"] == 123
    assert record["secondary_leagues"][0]["available"] is True
    assert record["secondary_leagues"][0]["scale_rounded"] == 21.2


def _secondary_standings(*, has_next: bool) -> bytes:
    standings = json.loads(_payloads(league=123)["league-123-standings.json"])
    standings["standings"]["has_next"] = has_next
    for row in standings["standings"]["results"]:
        row["entry"] += 10
    return _bytes(standings)


@pytest.mark.parametrize(
    "has_next,reason",
    [
        (False, "The capture lacks a standings or required history payload."),
        (True, "The capture has invalid standings or history rows."),
    ],
    ids=["histories-missing", "standings-paginated"],
)
def test_unreadable_secondary_league_is_recorded_unavailable_without_refusing_s(
    tmp_path: Path, has_next: bool, reason: str
) -> None:
    payloads = _payloads()
    payloads["league-123-standings.json"] = _secondary_standings(has_next=has_next)
    record = _measure(payloads, listed=(measurement.PRIMARY_LEAGUE, 123))
    assert record["scale"]["scale_rounded"] == 21.2
    assert record["secondary_leagues"] == [{"league": 123, "available": False, "reason": reason}]
    measurement.write_records(_provenance(record), tmp_path)
    text = (tmp_path / "docs/strategy_rule_scale.md").read_text()
    assert f"League 123 is listed and captured but was not measured: {reason}" in text
    assert "No additional listed league was measured." in text


def _provenance(record: dict[str, Any]) -> dict[str, Any]:
    return {
        **record,
        "snapshot_id": "synthetic-capture",
        "snapshot_fingerprint": "1" * 64,
        "captured_at_utc": "2026-10-13T12:00:00Z",
        "repository_commit": "2" * 40,
        "preregistration_sha256": "3" * 64,
    }


def test_json_and_markdown_render_week_list_in_numeric_order_without_member_details(
    tmp_path: Path,
) -> None:
    record = _provenance(_measure(_payloads(11), 11))
    measurement.write_records(record, tmp_path)
    written = json.loads((tmp_path / "docs/strategy_rule_scale.json").read_text())
    text = (tmp_path / "docs/strategy_rule_scale.md").read_text()
    assert [row["gameweek"] for row in written["by_gameweek"]] == list(range(1, 12))
    assert text == measurement.markdown(written)
    single = text.split("## Single gameweeks")[1].split("## Prefixes")[0]
    rendered = [
        int(line.split("|")[1].strip())
        for line in single.splitlines()
        if line.startswith("| ") and line.split("|")[1].strip().isdigit()
    ]
    assert rendered == list(range(1, 12))
    serialized = json.dumps(written) + text
    assert all(
        word not in serialized
        for word in (
            "entry_id",
            "entry_name",
            "player_name",
            "Synthetic",
            "event_transfers_cost",
            "per_member",
        )
    )


@pytest.mark.parametrize(
    "identifier", ["latest", "../capture", "fpl-live-20250901T120000Z-" + "a" * 12]
)
def test_invalid_or_holdout_identifier_refuses_before_prereg_or_capture_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, identifier: str
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("An inadmissible identifier must not open inputs.")

    monkeypatch.setattr(measurement, "preregistration_gate", forbidden)
    monkeypatch.setattr(measurement, "read_snapshot", forbidden)
    assert (
        measurement.main(
            [
                "--snapshot-root",
                str(tmp_path),
                "--snapshot-id",
                identifier,
                "--league",
                "352490",
                "--through-gameweek",
                "6",
            ]
        )
        == 1
    )


def test_unmerged_preregistration_refuses_before_reading_any_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(measurement, "_git_revision", lambda: ("a" * 40, False))

    def unmerged(*args: Any, **kwargs: Any) -> Any:
        raise subprocess.CalledProcessError(128, "git show")

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("No snapshot is read before the declaration merges.")

    monkeypatch.setattr(measurement.subprocess, "run", unmerged)
    monkeypatch.setattr(measurement, "read_snapshot", forbidden)
    assert (
        measurement.main(
            [
                "--snapshot-root",
                str(tmp_path),
                "--snapshot-id",
                "fpl-live-20261013T120000Z-" + "a" * 12,
                "--league",
                "352490",
                "--through-gameweek",
                "6",
            ]
        )
        == 1
    )
    assert not (tmp_path / "docs").exists()


def test_declaration_pin_detects_method_amendments_before_measurement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(measurement, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(measurement, "_git_revision", lambda: ("a" * 40, False))
    (tmp_path / "docs").mkdir()
    declared = b"Synthetic reviewed declaration\n"
    (tmp_path / measurement.DECLARATION_PATH).write_bytes(declared)
    monkeypatch.setattr(measurement, "DECLARATION_SHA256", sha256(declared).hexdigest())
    monkeypatch.setattr(
        measurement.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, stdout=declared),
    )
    assert measurement.preregistration_gate() == ("a" * 40, sha256(declared).hexdigest())
    (tmp_path / measurement.DECLARATION_PATH).write_text("Different method\n")
    with pytest.raises(measurement.ScaleMeasurementError, match="differs"):
        measurement.preregistration_gate()


def _stored_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, payloads: dict[str, bytes]
) -> SnapshotMetadata:
    metadata = write_snapshot(
        tmp_path / "captures",
        source="fpl-live",
        captured_at_utc="2026-10-13T12:00:00Z",
        payloads=payloads,
    )
    monkeypatch.setattr(measurement, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(measurement, "preregistration_gate", lambda: ("a" * 40, "b" * 64))
    (tmp_path / "config").mkdir()
    (tmp_path / measurement.LEAGUE_LIST_FILE).write_text(
        json.dumps(
            {
                "contract_version": "league_list_v1",
                "leagues": [{"league_id": measurement.PRIMARY_LEAGUE}],
            }
        )
    )
    return metadata


def test_complete_synthetic_capture_runs_through_store_and_writes_aggregate_twins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    metadata = _stored_capture(monkeypatch, tmp_path, _payloads())
    record = measurement.run_measurement(
        snapshot_root=tmp_path / "captures",
        snapshot_id=metadata.snapshot_id,
        league=measurement.PRIMARY_LEAGUE,
        through_gameweek=6,
    )
    assert record["snapshot_fingerprint"] == metadata.fingerprint
    assert record["scale"]["pair_weeks_counted"] == 18
    assert record["scale"]["scale_rounded"] == 21.2
    assert record["preregistration_sha256"] == "b" * 64
    assert (tmp_path / "docs/strategy_rule_scale.md").is_file()


@pytest.mark.parametrize(
    "row_change",
    [
        pytest.param(lambda rows: rows.append(dict(rows[0])), id="duplicated-week"),
        pytest.param(lambda rows: rows[1].update(event_transfers_cost=None), id="null-cost"),
    ],
)
def test_invalid_history_value_ends_in_the_one_line_refusal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    row_change: Callable[[list[dict[str, Any]]], None],
) -> None:
    payloads = _payloads()
    history = json.loads(payloads["entry-2-history.json"])
    row_change(history["current"])
    payloads["entry-2-history.json"] = _bytes(history)
    metadata = _stored_capture(monkeypatch, tmp_path, payloads)
    arguments = ["--snapshot-root", str(tmp_path / "captures"), "--snapshot-id"]
    arguments += [metadata.snapshot_id, "--league", "352490", "--through-gameweek", "6"]
    assert measurement.main(arguments) == 1
    error = capsys.readouterr().err
    assert error == "Measurement refused: The capture has invalid standings or history rows.\n"
    assert not (tmp_path / "docs").exists()
