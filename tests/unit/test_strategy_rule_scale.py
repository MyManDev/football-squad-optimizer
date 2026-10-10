"""The #1002 instrument, exercised only on synthetic FPL-shaped payloads."""

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


def test_prefix_and_cumulative_readings_run_from_gw3_through_n() -> None:
    record = _measure(_payloads())
    assert [row["through_gameweek"] for row in record["prefixes"]] == [3, 4, 5, 6]
    assert [row["through_gameweek"] for row in record["cumulative_comparisons"]] == [3, 4, 5, 6]
    # Every pair's weekly gap is constant, so its k-week gap is k times that gap and, divided
    # by the unrounded S (sqrt(450), not the rounded 21.2), the ratio is exactly sqrt(k).
    ratios = [
        row["cumulative_rms_over_sqrt_k_times_unrounded_scale"]
        for row in record["cumulative_comparisons"]
    ]
    assert ratios == pytest.approx([math.sqrt(k) for k in (3, 4, 5, 6)], rel=1e-9)


def test_cumulative_ratio_divides_by_the_unrounded_scale_on_gw1_to_n() -> None:
    payloads = _payloads()
    history = json.loads(payloads["entry-3-history.json"])
    history["current"][5]["points"] = 60
    payloads["entry-3-history.json"] = _bytes(history)
    record = _measure(payloads)
    # GW1 to GW5 keep gaps 15, 15 and 30; GW6 has 15, 60 and 45. S on GW1 to 6 is sqrt(700),
    # which differs from S on GW1 to k (sqrt(450) for k up to 5) and from its rounding 26.5.
    assert record["scale"]["scale_unrounded"] == pytest.approx(math.sqrt(700))
    assert record["scale"]["scale_rounded"] == 26.5
    expected = [math.sqrt(k * 450 / 700) for k in (3, 4, 5)]
    expected.append(math.sqrt((90**2 + 210**2 + 120**2) / 3) / (math.sqrt(6) * math.sqrt(700)))
    rows = record["cumulative_comparisons"]
    assert [row["cumulative_rms_over_sqrt_k_times_unrounded_scale"] for row in rows] == (
        pytest.approx(expected, rel=1e-9)
    )
    for row in rows:
        assert row["cumulative_rms"] == pytest.approx(
            row["cumulative_rms_over_sqrt_k_times_unrounded_scale"]
            * math.sqrt(row["through_gameweek"])
            * record["scale"]["scale_unrounded"],
            rel=1e-9,
        )


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


def _failed_control_payloads() -> dict[str, bytes]:
    payloads = _payloads()
    history = json.loads(payloads["entry-3-history.json"])
    history["current"][0]["points"] = 99
    payloads["entry-3-history.json"] = _bytes(history)
    return payloads


# GW1 gaps are 15, 99 and 84; every other week keeps 15, 15 and 30.
_GW1_SQUARES = 15**2 + 99**2 + 84**2
_WEEK_SQUARES = 15**2 + 15**2 + 30**2


def test_failed_three_week_control_is_recorded_with_its_aggregates() -> None:
    record = _measure(_failed_control_payloads())
    assert record["control_failed"] is True
    control = record["control_gw1_to_gw3"]
    assert control["scale_rounded"] == 46.9
    assert control["scale_unrounded"] == pytest.approx(
        math.sqrt((_GW1_SQUARES + 2 * _WEEK_SQUARES) / 9)
    )
    assert control["expected_scale_rounded"] == 21.2
    assert (control["pair_weeks_counted"], control["pair_weeks_dropped"]) == (9, 0)
    # S and every companion reading are still recorded; only step 4 is held.
    assert record["scale"]["scale_unrounded"] == pytest.approx(
        math.sqrt((_GW1_SQUARES + 5 * _WEEK_SQUARES) / 18)
    )
    assert record["scale"]["scale_rounded"] == 36.4
    assert [row["gameweek"] for row in record["by_gameweek"]] == [1, 2, 3, 4, 5, 6]
    assert len(record["cumulative_comparisons"]) == 4


def test_passing_control_is_recorded_as_passed() -> None:
    record = _measure(_payloads())
    assert record["control_failed"] is False
    assert record["control_gw1_to_gw3"]["scale_rounded"] == 21.2


def test_secondary_readings_cover_every_listed_league_and_no_other() -> None:
    payloads = _payloads()
    payloads.update(
        {key: value for key, value in _payloads(league=123).items() if key.startswith("league-")}
    )
    unlisted = _measure(payloads)
    assert unlisted["secondary_leagues"] == []
    record = _measure(payloads, listed=(measurement.PRIMARY_LEAGUE, 123, 456))
    assert [row["league"] for row in record["secondary_leagues"]] == [123, 456]
    measured, absent = record["secondary_leagues"]
    assert measured["available"] is True
    assert measured["scale_rounded"] == 21.2
    assert absent == {
        "league": 456,
        "available": False,
        "reason": "The capture has no standings for this listed league.",
    }
    # Reading (e) never changes the primary reading.
    assert {**record, "secondary_leagues": []} == unlisted


def _secondary_payloads(case: str) -> dict[str, bytes]:
    """League 123 with members 11 to 13, broken the way ``case`` names."""
    payloads = _payloads()
    if case == "standings-absent":
        return payloads
    standings = json.loads(_payloads(league=123)["league-123-standings.json"])
    standings["standings"]["has_next"] = case == "standings-paginated"
    for row in standings["standings"]["results"]:
        row["entry"] += 10
    payloads["league-123-standings.json"] = _bytes(standings)
    if case in ("histories-missing", "standings-paginated"):
        return payloads
    for entry in (1, 2, 3):
        history = json.loads(payloads[f"entry-{entry}-history.json"])
        if case == "week-missing" and entry == 3:
            history["current"] = [row for row in history["current"] if row["event"] != 4]
        if case == "cost-missing" and entry == 2:
            del history["current"][1]["event_transfers_cost"]
        payloads[f"entry-{entry + 10}-history.json"] = _bytes(history)
    return payloads


@pytest.mark.parametrize(
    "case,reason",
    [
        ("standings-absent", "The capture has no standings for this listed league."),
        ("histories-missing", "The capture lacks a standings or required history payload."),
        ("standings-paginated", "The capture has invalid standings or history rows."),
        ("week-missing", "A member lacks a history row for a week from GW1 to N."),
        ("cost-missing", "A history row lacks event_transfers_cost."),
    ],
)
def test_unreadable_secondary_league_is_recorded_unavailable_without_refusing_s(
    tmp_path: Path, case: str, reason: str
) -> None:
    record = _measure(_secondary_payloads(case), listed=(measurement.PRIMARY_LEAGUE, 123))
    assert record["scale"]["scale_rounded"] == 21.2
    assert record["secondary_leagues"] == [{"league": 123, "available": False, "reason": reason}]
    assert {**record, "secondary_leagues": []} == _measure(_payloads())
    measurement.write_records(_provenance(record), tmp_path)
    text = (tmp_path / "docs/strategy_rule_scale.md").read_text()
    assert f"League 123 is listed but was not measured: {reason}" in text
    assert "No additional listed league was measured." in text


def test_complete_secondary_league_is_measured() -> None:
    payloads = _secondary_payloads("complete")
    record = _measure(payloads, listed=(measurement.PRIMARY_LEAGUE, 123))
    (measured,) = record["secondary_leagues"]
    assert measured["available"] is True
    assert (measured["members"], measured["through_gameweek"]) == (3, 6)
    assert (measured["pair_weeks_counted"], measured["pair_weeks_dropped"]) == (18, 0)
    assert measured["scale_rounded"] == 21.2


def _uncosted_week_after_n(payload: bytes) -> bytes:
    """One history with an extra GW7 row, after N, carrying no event_transfers_cost."""
    history = json.loads(payload)
    history["current"].append({"event": 7, "points": 40, "total_points": 0})
    return _bytes(history)


def test_secondary_league_needs_the_transfer_cost_only_on_gw1_to_n() -> None:
    payloads = _secondary_payloads("complete")
    payloads["entry-12-history.json"] = _uncosted_week_after_n(payloads["entry-12-history.json"])
    record = _measure(payloads, listed=(measurement.PRIMARY_LEAGUE, 123))
    (measured,) = record["secondary_leagues"]
    assert measured["available"] is True
    assert (measured["pair_weeks_counted"], measured["scale_rounded"]) == (18, 21.2)
    # The primary league still refuses any history row without the cost.
    payloads = _payloads()
    payloads["entry-2-history.json"] = _uncosted_week_after_n(payloads["entry-2-history.json"])
    with pytest.raises(measurement.ScaleMeasurementError, match="event_transfers_cost"):
        _measure(payloads)


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


def _git(
    declared: bytes | None, *, remote: bytes = b"c" * 40, tracked: bytes = b"c" * 40
) -> Callable[..., subprocess.CompletedProcess[bytes]]:
    """Answer the gate's git calls; a None declaration is absent from origin/develop."""

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        outputs = {
            "ls-remote": remote + b"\trefs/heads/develop\n",
            "rev-parse": tracked + b"\n",
            "show": declared,
        }
        output = outputs[command[1]]
        if output is None:
            raise subprocess.CalledProcessError(128, command)
        return subprocess.CompletedProcess(command, 0, stdout=output)

    return run


def test_unmerged_preregistration_refuses_before_reading_any_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(measurement, "_git_revision", lambda: ("a" * 40, False))

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("No snapshot is read before the declaration merges.")

    monkeypatch.setattr(measurement.subprocess, "run", _git(None))
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
    assert "must first merge into origin/develop" in capsys.readouterr().err
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
    monkeypatch.setattr(measurement.subprocess, "run", _git(declared))
    assert measurement.preregistration_gate() == ("a" * 40, sha256(declared).hexdigest())
    (tmp_path / measurement.DECLARATION_PATH).write_text("Different method\n")
    with pytest.raises(measurement.ScaleMeasurementError, match="differs"):
        measurement.preregistration_gate()


def test_stale_origin_develop_refuses_before_reading_the_declaration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A clone fetched before an amendment holds the old declaration and pin, all agreeing."""
    monkeypatch.setattr(measurement, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(measurement, "_git_revision", lambda: ("a" * 40, False))
    (tmp_path / "docs").mkdir()
    declared = b"Superseded declaration\n"
    (tmp_path / measurement.DECLARATION_PATH).write_bytes(declared)
    monkeypatch.setattr(measurement, "DECLARATION_SHA256", sha256(declared).hexdigest())
    monkeypatch.setattr(measurement.subprocess, "run", _git(declared, remote=b"d" * 40))
    with pytest.raises(measurement.ScaleMeasurementError, match="Fetch origin/develop"):
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


DECLARATION = Path(__file__).resolve().parents[2] / measurement.DECLARATION_PATH


@pytest.mark.skipif(not DECLARATION.is_file(), reason="the #1002 declaration has not merged yet")
def test_pin_matches_the_declaration_in_this_tree() -> None:
    """Whichever of the declaration and this runner merges second fails here on a stale pin."""
    declared = DECLARATION.read_bytes().replace(b"\r\n", b"\n")
    assert sha256(declared).hexdigest() == measurement.DECLARATION_SHA256


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


def _main_arguments(tmp_path: Path, snapshot_id: str) -> list[str]:
    return [
        "--snapshot-root",
        str(tmp_path / "captures"),
        "--snapshot-id",
        snapshot_id,
        "--league",
        "352490",
        "--through-gameweek",
        "6",
    ]


def test_unreadable_league_list_refuses_before_any_capture_opens(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("No capture opens before the league list is read.")

    monkeypatch.setattr(measurement, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(measurement, "preregistration_gate", lambda: ("a" * 40, "b" * 64))
    monkeypatch.setattr(measurement, "read_snapshot", forbidden)
    (tmp_path / "config").mkdir()
    (tmp_path / measurement.LEAGUE_LIST_FILE).write_text("{}")
    snapshot_id = "fpl-live-20261013T120000Z-" + "a" * 12
    assert measurement.main(_main_arguments(tmp_path, snapshot_id)) == 1
    assert (
        capsys.readouterr().err == "Measurement refused: Capture or provenance validation failed.\n"
    )
    assert not (tmp_path / "docs").exists()


def test_passing_control_exits_zero_and_holds_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    metadata = _stored_capture(monkeypatch, tmp_path, _payloads())
    assert measurement.main(_main_arguments(tmp_path, metadata.snapshot_id)) == 0
    assert capsys.readouterr().err == ""
    written = json.loads((tmp_path / "docs/strategy_rule_scale.json").read_text())
    assert written["control_failed"] is False
    text = (tmp_path / "docs/strategy_rule_scale.md").read_text()
    assert "Control: passed" in text
    assert "step 4 is held" not in text
    assert (
        "Ratio is the cumulative RMS divided by sqrt(k) times the unrounded S on GW1 to N."
    ) in text


def test_failed_control_writes_the_record_and_holds_step_4(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    metadata = _stored_capture(monkeypatch, tmp_path, _failed_control_payloads())
    exit_code = measurement.main(_main_arguments(tmp_path, metadata.snapshot_id))
    assert exit_code == measurement.CONTROL_FAILED_EXIT == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "Recorded GW1 to GW6 scale 36.4 with a failed GW1 to GW3 control (46.9, expected 21.2). "
        "Step 4 is held until the difference is explained on #1002.\n"
    )
    written = json.loads((tmp_path / "docs/strategy_rule_scale.json").read_text())
    assert written["control_failed"] is True
    assert written["control_gw1_to_gw3"]["scale_rounded"] == 46.9
    text = (tmp_path / "docs/strategy_rule_scale.md").read_text()
    assert text == measurement.markdown(written)
    assert "Control: failed" in text
    assert (
        "The control failed, so step 4 is held. This record updates no constant "
        "until the difference is explained on #1002."
    ) in text


def test_usage_error_exit_differs_from_a_failed_control(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # argparse exits 2 before anything is written, so a written failed control cannot share it.
    with pytest.raises(SystemExit) as usage:
        measurement.main([])
    assert usage.value.code == 2
    assert measurement.CONTROL_FAILED_EXIT not in (0, 1, 2)
    assert "required" in capsys.readouterr().err


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
    assert measurement.main(_main_arguments(tmp_path, metadata.snapshot_id)) == 1
    error = capsys.readouterr().err
    assert error == "Measurement refused: The capture has invalid standings or history rows.\n"
    assert not (tmp_path / "docs").exists()
