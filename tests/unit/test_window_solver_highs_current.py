"""The runner measures a later tree when told which one, and the #1083 defaults stay.

#1090 re-measures native HiGHS on the current window model. The runner keeps every default
of the #1083 record (the GW6 capture, the old ``league/`` tree, both builds, the stem
``window_solver_highs``) and takes the GW7 tree, its capture, a record stem and
``--builds native`` as arguments. These tests read a tiny synthetic tree in the committed
layout and replace every solver, as the runner's other tests do.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from scripts import measure_window_solver_highs as runner
from tests.unit.test_window_solver_highs import GOOD_DAY, _measure, _side

CAPTURE = "fpl-live-20261016T060154Z-b1702d00c8cd"
NATIVE_VERSIONS: dict[str, Any] = {"native_core": "1.15.1", "wasm": None}


def _document(payload: dict[str, Any]) -> str:
    return json.dumps({"contract_version": "x", "payload": payload})


def _tree(tmp_path: Path, *, flat: bool = True) -> tuple[Path, Path]:
    """A league tree in the committed layout: one member, two clubs, five weeks."""

    league = tmp_path / "leagues" / "352490"
    (league / "entries").mkdir(parents=True)
    (league / "advice" / "42" / "saf-puan").mkdir(parents=True)
    table = {"source_snapshot_id": CAPTURE, "gameweek": 7, "league_id": 352490, "players": []}
    (league / "device-plan.json").write_text(_document(table), encoding="utf-8")
    block = {"held": [], "bank_tenths": 0, "free_transfers": 1, "sell_tenths": {}}
    entry = {"source_snapshot_id": CAPTURE, "gameweek": 7, "device_plan": block}
    (league / "entries" / "42.json").write_text(_document(entry), encoding="utf-8")
    advice = {"source_snapshot_id": CAPTURE, "gameweek": 7, "entry_id": 42, "window": 1}
    (league / "advice" / "42" / "saf-puan" / "1.json").write_text(
        _document(advice), encoding="utf-8"
    )
    weeks = []
    for week in range(7, 12):
        fixtures = [{"home": {"name": "Arsenal"}, "away": {"name": "Chelsea"}}]
        if not flat and week == 9:
            fixtures.append({"home": {"name": "Chelsea"}, "away": {"name": "Arsenal"}})
        weeks.append({"gameweek": week, "fixtures": fixtures})
    fixtures_path = tmp_path / "fixtures.json"
    fixtures_path.write_text(
        _document({"source_snapshot_id": CAPTURE, "gameweeks": weeks}), encoding="utf-8"
    )
    return league, fixtures_path


def test_the_loader_reads_the_committed_layout_under_the_named_capture(tmp_path: Path) -> None:
    league, fixtures = _tree(tmp_path)
    inputs = runner.load_inputs(league, fixtures, CAPTURE)
    assert sorted(inputs.members) == [42]
    assert inputs.gameweek == 7
    assert inputs.capture == CAPTURE
    assert inputs.fixture_counts[11] == {"Arsenal": 1, "Chelsea": 1}
    assert runner.published_advice(inputs, 42, 1)["entry_id"] == 42
    calendar = runner.calendar_record(inputs)
    assert calendar["first_gameweek"] == 7 and calendar["last_gameweek"] == 11
    assert calendar["flat"] is True
    assert calendar["weeks"]["9"] == {"clubs": 2, "fixtures_per_club": [1]}


def test_a_double_in_a_window_week_is_read_as_not_flat(tmp_path: Path) -> None:
    league, fixtures = _tree(tmp_path, flat=False)
    calendar = runner.calendar_record(runner.load_inputs(league, fixtures, CAPTURE))
    assert calendar["flat"] is False
    assert calendar["weeks"]["9"] == {"clubs": 2, "fixtures_per_club": [2]}


def test_the_default_capture_refuses_the_later_tree_by_name(tmp_path: Path) -> None:
    league, fixtures = _tree(tmp_path)
    with pytest.raises(runner.ProtocolRefusal, match=runner.CAPTURE):
        runner.load_inputs(league, fixtures)
    inputs = runner.load_inputs(league, fixtures, CAPTURE)
    restamped = runner.PublishedInputs(
        inputs.table, inputs.members, inputs.fixture_counts, inputs.league_dir, "another"
    )
    with pytest.raises(runner.ProtocolRefusal, match="another"):
        runner.published_advice(restamped, 42, 1)


def test_the_default_target_is_the_1083_record_s() -> None:
    target = runner.Target()
    assert target.capture == runner.CAPTURE
    assert target.league_dir == runner.LEAGUE_DIR
    assert target.builds == ("native", "wasm")
    assert target.record_json == runner.RECORD_JSON
    assert target.artifact_dir == runner.ARTIFACT_DIR
    assert (target.protocol, target.issue) == (runner.PROTOCOL, runner.ISSUE)


def test_the_current_stem_names_its_own_record_protocol_and_issue() -> None:
    arguments = runner._parse(
        [
            "check",
            "--league-dir",
            "web/public/data/leagues/352490",
            "--capture",
            CAPTURE,
            "--record-stem",
            "window_solver_highs_current",
            "--builds",
            "native",
        ]
    )
    target = runner.target_from(arguments)
    assert target.league_dir == runner.REPOSITORY_ROOT / "web/public/data/leagues/352490"
    assert target.capture == CAPTURE
    assert target.builds == ("native",)
    assert target.protocol == "docs/research/window_solver_highs_current_prereg.md"
    assert target.issue == 1090
    research = runner.REPOSITORY_ROOT / "docs" / "research"
    assert target.record_json == research / "window_solver_highs_current.json"
    assert target.record_markdown == research / "window_solver_highs_current.md"
    assert target.artifact_dir == runner.REPOSITORY_ROOT / "artifacts/window_solver_highs_current"
    assert (runner.REPOSITORY_ROOT / target.protocol).is_file()


def test_a_stem_without_a_protocol_must_name_one() -> None:
    arguments = runner._parse(["check", "--record-stem", "window_solver_highs_gw9"])
    with pytest.raises(runner.ProtocolRefusal, match="names no protocol"):
        runner.target_from(arguments)
    named = runner._parse(
        ["check", "--record-stem", "window_solver_highs_gw9", "--protocol", "p.md", "--issue", "7"]
    )
    assert (runner.target_from(named).protocol, runner.target_from(named).issue) == ("p.md", 7)


def _never_wasm() -> dict[str, Any]:
    raise AssertionError("the wasm build was read on a native-only run")


def test_builds_native_skips_the_wasm_guard() -> None:
    versions = runner.measure_guards(
        have_slot=True,
        now=GOOD_DAY,
        native_version=lambda: "1.15.1",
        wasm_version=_never_wasm,
        builds=("native",),
    )
    assert versions == NATIVE_VERSIONS


def test_builds_native_skips_the_wasm_preflight_and_carries_the_device_verdict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def side(entry: int, window: int, run: int) -> dict[str, Any]:
        # CP-SAT leaves one five-week window FEASIBLE; the native stand-in proves it.
        return _side(stopped=(entry, window) == (2, 5))

    seen = _measure(monkeypatch, side=side)
    target = runner.Target(builds=("native",), record_stem="window_solver_highs_current")
    record = runner.run_measure("node", NATIVE_VERSIONS, tmp_path, target)
    assert seen.preflights == ["native"]
    assert {build for _, _, build, _ in seen.budgets} == {"native"}
    assert record["builds"] == ["native"]
    assert record["protocol"] == "docs/research/window_solver_highs_current_prereg.md"
    assert record["issue"] == 1090
    assert record["device_verdict_source"] == runner.DEVICE_VERDICT_CARRIED
    assert record["verdicts"]["device"] == runner.DEVICE_VERDICT_CARRIED
    assert record["verdicts"]["device_counts"] is None
    assert record["verdicts"]["server"] == "A switch is supported"
    assert set(record["instances"][0]["highs"]) == {"native"}
    counts = record["counts"]
    assert counts["members"] == 2 and counts["instances"] == 4
    assert counts["week_3"]["native_ceiling_proved"] == 2
    assert counts["week_5"] == {
        "instances": 2,
        "cp_sat_proved": 1,
        "cp_sat_feasible": 1,
        "native_wall_matched_proved": 2,
        "native_ceiling_proved": 2,
    }
    assert "wasm_ceiling_proved" not in counts["week_5"]
    twin = runner.markdown(record)
    assert "Wasm" not in twin
    assert "| Native matched | Native 1,800 s |" in twin
    assert "carried from docs/research/window_solver_highs.md" in twin
    assert "## Decision" in twin and "highspy==1.15.1" in twin
    assert "The CP-SAT solver stays in the decision core" in twin
    assert runner.decision(record).startswith("Switch the server's")
    assert "`constraints.txt`" in runner.decision(record)


def test_a_failed_condition_keeps_cp_sat_and_is_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Every CP-SAT run proves its window, so the second condition has nothing to prove.
    _measure(monkeypatch)
    record = runner.run_measure(
        "node", NATIVE_VERSIONS, tmp_path, runner.Target(builds=("native",))
    )
    assert record["verdicts"]["server"] == "the server stays on CP-SAT"
    text = runner.decision(record)
    assert text.startswith("Keep CP-SAT")
    assert "half of the five-week instances" in text
    assert "stays out of `constraints.txt`" in text


def test_the_measure_command_with_native_builds_never_loads_node(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def broken(node: str) -> dict[str, Any]:
        raise AssertionError("Node was asked for its wasm report")

    captured: dict[str, Any] = {}

    def run_measure(node: str, versions: Any, out_dir: Path, target: Any) -> dict[str, Any]:
        captured["versions"], captured["target"], captured["out_dir"] = versions, target, out_dir
        raise runner.ProtocolRefusal("stopped here on purpose")

    monkeypatch.setattr(runner, "native_core_version", lambda: "1.15.1")
    monkeypatch.setattr(runner, "wasm_report", broken)
    monkeypatch.setattr(runner, "run_measure", run_measure)
    monkeypatch.setattr(runner, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(runner, "datetime", runner.datetime)
    assert (
        runner.main(
            [
                "measure",
                "--i-have-the-slot",
                "--builds",
                "native",
                "--record-stem",
                "window_solver_highs_current",
            ]
        )
        == 2
    )
    assert captured["versions"] == NATIVE_VERSIONS
    assert captured["target"].builds == ("native",)
    assert captured["out_dir"] == tmp_path / "artifacts" / "window_solver_highs_current"
    stopped = json.loads((captured["out_dir"] / "stopped.json").read_text(encoding="utf-8"))
    assert stopped["reason"] == "stopped here on purpose"
