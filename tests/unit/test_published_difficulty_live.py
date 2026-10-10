"""Synthetic coefficient, pairing, date, solver and once-only checks for #1009(b)."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from scripts import measure_published_difficulty_live as runner
from tests.unit.test_season_rules import _chips, _rules, _scoring

from squadopt.data.snapshots import CapturedSnapshot, read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD, live_payload
from squadopt.experiments import opponent_projection
from squadopt.experiments import published_difficulty_live as study
from squadopt.experiments.opponent_projection import _squad
from squadopt.live.recommendation import InSeasonProjection, write_projection_handoff

START = datetime(2026, 8, 25, 18, tzinfo=UTC)


def stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def captured(
    root: Path, *, target: int = 7, final: bool = False, offset: int = 0, change: Any = None
) -> CapturedSnapshot:
    positions = [1] * 2 + [2] * 6 + [3] * 6 + [4] * 4
    events = [
        {
            "id": w,
            "deadline_time": stamp(START + timedelta(weeks=w - 1)),
            "finished": final or w < target,
            "data_checked": final or w < target,
        }
        for w in range(1, 21)
    ]
    players = [
        {
            "id": i,
            "code": 1000 + i,
            "element_type": p,
            "team": 1 + (i - 1) % 10,
            "first_name": "Synthetic",
            "second_name": str(i),
            "now_cost": 50,
            "status": "d" if i == 3 else "a",
            "chance_of_playing_next_round": 50 if i == 3 else None,
            "news_added": None,
        }
        for i, p in enumerate(positions, 1)
    ]
    bootstrap = {
        "events": events,
        "elements": players,
        "teams": [{"id": i, "name": f"Club {i}"} for i in range(1, 11)],
        "game_config": {"rules": _rules(), "scoring": _scoring()},
        "chips": _chips(),
    }
    fixtures = [
        {
            "id": w * 10 + i,
            "event": w,
            "team_h": i * 2 - 1,
            "team_a": i * 2,
            "team_h_difficulty": 2,
            "team_a_difficulty": 4,
            "kickoff_time": stamp(START + timedelta(weeks=w - 1, hours=2)),
            "finished": final or w < target,
            "finished_provisional": final or w < target,
        }
        for w in range(1, 21)
        for i in range(1, 6)
    ]
    documents = {BOOTSTRAP_PAYLOAD: bootstrap, FIXTURES_PAYLOAD: fixtures}
    if final:
        for w in range(1, 21):
            documents[live_payload(w)] = {
                "elements": [
                    {"id": i, "stats": {"total_points": i % 8, "minutes": 0 if i % 8 == 0 else 90}}
                    for i in range(1, 19)
                ]
            }
    if change:
        change(documents)
    instant = START + timedelta(
        weeks=19 if final else target - 1, hours=8 if final else -1, seconds=offset
    )
    metadata = write_snapshot(
        root,
        source="fpl-live",
        captured_at_utc=stamp(instant),
        payloads={
            key: value if isinstance(value, bytes) else json.dumps(value).encode()
            for key, value in documents.items()
        },
    )
    return read_snapshot(root, metadata.snapshot_id)


def handoff(
    root: Path,
    snapshot: CapturedSnapshot,
    *,
    target: int = 7,
    filename: str = "base.json",
    delta: float = 0,
) -> InSeasonProjection:
    base = InSeasonProjection(
        study.SEASON,
        target,
        snapshot.metadata.snapshot_id,
        "component",
        "phase_c_control_components_v1",
        "phase_c_component_form_window_v1",
        {1000 + i: float(i % 6 + 1) + delta for i in range(1, 19)},
    )
    path = root / "by-capture" / snapshot.metadata.snapshot_id / filename
    write_projection_handoff(path, base)
    instant = datetime.fromisoformat(snapshot.metadata.captured_at_utc).timestamp()
    os.utime(path, (instant, instant))
    return base


def frame() -> pd.DataFrame:
    positions = ["GK"] * 2 + ["DEF"] * 6 + ["MID"] * 6 + ["FWD"] * 4
    return pd.DataFrame(
        {
            "player_id": range(1, 19),
            "name": [f"Player {i}" for i in range(1, 19)],
            "team_id": [f"Club {i % 10}" for i in range(18)],
            "position": positions,
            "price_tenths": [50] * 18,
            "predicted_points": np.linspace(1, 8, 18),
            "realized_points": [i % 8 for i in range(18)],
            "fixture_count": [1] * 18,
            "published_signal": [-2.0] * 18,
        }
    )


def test_recorded_coefficients_are_pinned_by_hash_and_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = (runner.ROOT / "docs/opponent_projection_study.json").read_bytes()
    study.verify_coefficients(content)
    with pytest.raises(study.DifficultyInputError, match="hash"):
        study.verify_coefficients(content + b" ")
    document = json.loads(content)
    candidate = next(
        item for item in document["candidates"] if item["candidate"] == "P_published_rating"
    )
    candidate["coefficients"]["DEF"]["slope"] += 0.01
    changed = json.dumps(document).encode()
    monkeypatch.setattr(
        study, "COEFFICIENT_FILE_SHA256", runner.hashlib.sha256(changed).hexdigest()
    )
    with pytest.raises(study.DifficultyInputError, match="values"):
        study.verify_coefficients(changed)


def test_multiplier_is_hand_computed_and_blank_has_no_calendar_double_counting() -> None:
    rows = frame()
    rows.loc[0, "fixture_count"] = 0
    rows.loc[0, "published_signal"] = np.nan
    rows.loc[1, "fixture_count"] = 2
    adjusted, multiplier = study.adjusted_points(rows)
    assert multiplier[0] == 1
    assert multiplier[1] == pytest.approx(1.0823658724428682)
    assert adjusted[1] == pytest.approx(rows.loc[1, "predicted_points"] * 1.0823658724428682)
    assert adjusted[0] == rows.loc[0, "predicted_points"]


@pytest.mark.parametrize(
    "corruption", ["duplicate", "position", "nonfinite", "rating", "count", "blank"]
)
def test_invalid_adjustment_inputs_refuse(corruption: str) -> None:
    rows = frame()
    if corruption == "duplicate":
        rows.loc[0, "player_id"] = rows.loc[1, "player_id"]
    if corruption == "position":
        rows.loc[0, "position"] = "UNKNOWN"
    if corruption == "nonfinite":
        rows.loc[0, "predicted_points"] = np.inf
    if corruption == "rating":
        rows.loc[0, "published_signal"] = -9
    if corruption == "count":
        rows["fixture_count"] = rows["fixture_count"].astype(float)
        rows.loc[0, "fixture_count"] = 0.5
    if corruption == "blank":
        rows.loc[0, "fixture_count"] = 0
    with pytest.raises(study.DifficultyInputError):
        study.adjusted_points(rows)


def test_reused_squad_records_the_same_actual_solve_and_default_answer() -> None:
    rows = frame()
    trace: dict[str, object] = {}
    config = study.optimization_config(60.0)
    expected = _squad(rows, rows["predicted_points"].to_numpy(), config, linearization_level=2)
    actual = _squad(
        rows,
        rows["predicted_points"].to_numpy(),
        config,
        diagnostics=trace,
        linearization_level=2,
    )
    assert expected == actual
    assert trace["solver_status"] == "OPTIMAL"
    assert len(trace["squad"]) == 15
    assert len(trace["starting_xi"]) == 11
    assert trace["captain"] == actual[1]
    solver = trace["solver_diagnostics"]
    assert solver["linearization_level"] == 2
    assert solver["num_search_workers"] == 1
    assert solver["deterministic_seed"] == 0
    assert solver["solver_deterministic_time_limit"] == 60.0
    assert solver["solver_time_limit_seconds"] == 1800.0
    # The study's own call passes no level, which is the solver default it always used.
    assert _squad(rows, rows["predicted_points"].to_numpy(), config) == expected


def test_free_squad_is_solved_by_the_844_method(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[float | None, float, int, int | None]] = []
    original = opponent_projection.optimize_squad

    def spy(players: pd.DataFrame, config: Any, **kwargs: Any) -> Any:
        calls.append(
            (
                config.solver_deterministic_time_limit,
                config.solver_time_limit_seconds,
                config.deterministic_seed,
                kwargs.get("linearization_level"),
            )
        )
        return original(players, config, **kwargs)

    monkeypatch.setattr(opponent_projection, "optimize_squad", spy)
    measured, _ = study.measure_week(
        frame(), season=study.SEASON, gameweek=7, handoff_version="base"
    )
    # Both arms are proven at 60 units, so neither is solved again at 240.
    assert calls == [(60.0, 1800.0, 0, 2), (60.0, 1800.0, 0, 2)]
    for decision in (measured.comparator_decision, measured.candidate_decision):
        assert decision["decided"] is True
        assert decision["decided_at_units"] == 60.0
        assert decision["wall_clock_stopped"] is False
        (attempt,) = decision["attempts"]
        assert attempt["primary_status"] == "OPTIMAL"
        assert attempt["tiebreak_status"] == "OPTIMAL"
        assert attempt["wall_clock_stopped"] is False
        assert attempt["proven"] is True
        assert isinstance(attempt["primary_deterministic_time"], float)
        assert isinstance(attempt["tiebreak_deterministic_time"], float)
        assert decision["squad"] == attempt["squad"]
        assert decision["captain"] == attempt["captain"]


def _unproven(result: Any, *, clock: bool) -> Any:
    """The same answer, recorded as a tie-break the budget (or the clock) cut short."""
    diagnostics = dict(result.diagnostics)
    diagnostics.update(
        tiebreak_status="FEASIBLE",
        tiebreak_completed=False,
        deterministic_time_budget_exhausted=not clock,
    )
    return replace(result, diagnostics=diagnostics)


@pytest.mark.parametrize("unproven_at", [(60.0,), (60.0, 240.0)])
def test_an_arm_unproven_at_60_is_decided_at_240_and_unproven_there_is_missing(
    monkeypatch: pytest.MonkeyPatch, unproven_at: tuple[float, ...]
) -> None:
    calls: list[float | None] = []
    original = opponent_projection.optimize_squad

    def solve(players: pd.DataFrame, config: Any, **kwargs: Any) -> Any:
        calls.append(config.solver_deterministic_time_limit)
        result = original(players, config, **kwargs)
        if config.solver_deterministic_time_limit in unproven_at:
            return _unproven(result, clock=False)
        return result

    monkeypatch.setattr(opponent_projection, "optimize_squad", solve)
    if unproven_at == (60.0,):
        measured, _ = study.measure_week(
            frame(), season=study.SEASON, gameweek=7, handoff_version="base"
        )
        assert calls == [60.0, 240.0, 60.0, 240.0]
        decision = measured.candidate_decision
        assert decision["decided_at_units"] == 240.0
        assert [a["proven"] for a in decision["attempts"]] == [False, True]
        assert decision["attempts"][0]["tiebreak_status"] == "FEASIBLE"
        return
    with pytest.raises(study.DifficultySolveFailure) as failure:
        study.measure_week(frame(), season=study.SEASON, gameweek=7, handoff_version="base")
    # Both arms are solved and recorded even when the first is already unproven.
    assert calls == [60.0, 240.0, 60.0, 240.0]
    for arm in ("comparator", "candidate"):
        decision = failure.value.decisions[arm]
        assert decision["decided"] is False
        assert decision["decided_at_units"] == 240.0
        assert [a["deterministic_units"] for a in decision["attempts"]] == [60.0, 240.0]
        assert [a["proven"] for a in decision["attempts"]] == [False, False]


def test_a_wall_clock_stop_at_60_makes_the_week_missing_without_a_240_solve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[float | None] = []
    original = opponent_projection.optimize_squad

    def solve(players: pd.DataFrame, config: Any, **kwargs: Any) -> Any:
        calls.append(config.solver_deterministic_time_limit)
        result = original(players, config, **kwargs)
        return _unproven(result, clock=True) if len(calls) == 1 else result

    monkeypatch.setattr(opponent_projection, "optimize_squad", solve)
    with pytest.raises(study.DifficultySolveFailure) as failure:
        study.measure_week(frame(), season=study.SEASON, gameweek=7, handoff_version="base")
    comparator = failure.value.decisions["comparator"]
    assert comparator["wall_clock_stopped"] is True
    assert [a["wall_clock_stopped"] for a in comparator["attempts"]] == [True]
    assert failure.value.decisions["candidate"]["decided"] is True
    assert calls == [60.0, 60.0]


def test_week_reads_mse_mae_ordering_and_realized_starters_plus_captain() -> None:
    rows = frame()
    measured, evidence = study.measure_week(
        rows, season=study.SEASON, gameweek=7, handoff_version="base"
    )
    assert measured.comparator_mse == pytest.approx(
        np.mean((rows.predicted_points - rows.realized_points) ** 2)
    )
    assert measured.candidate_mse == pytest.approx(
        np.mean((evidence.candidate_points - rows.realized_points) ** 2)
    )
    totals = dict(zip(rows.player_id, rows.realized_points, strict=True))
    trace = measured.candidate_decision
    expected = sum(totals[p] for p in trace["starting_xi"]) + totals[trace["captain"]]
    assert measured.candidate_realized_points == expected
    assert measured.squared_error_improvement == measured.comparator_mse - measured.candidate_mse


def test_week_readings_point_toward_the_candidate_that_was_right() -> None:
    rows = frame()
    rows["published_signal"] = -3.0
    # An easy fixture for the weaker player of each close pair and a hard one for the
    # stronger swaps their order in DEF, in MID and among the two leading forwards.
    for weaker, stronger in ((2, 3), (8, 9), (16, 17)):
        rows.loc[weaker, "published_signal"] = -1.0
        rows.loc[stronger, "published_signal"] = -5.0
    adjusted, _ = study.adjusted_points(rows)
    rows["realized_points"] = adjusted
    measured, _ = study.measure_week(rows, season=study.SEASON, gameweek=7, handoff_version="base")
    # One adjacent swap among six players gives Spearman 1 - 6 * 2 / (6 * 35) = 33 / 35.
    assert measured.candidate_rank == pytest.approx(1.0)
    assert measured.comparator_rank == pytest.approx(33 / 35)
    assert measured.rank_improvement == pytest.approx(1.0 - 33 / 35)
    base, candidate = measured.comparator_decision, measured.candidate_decision
    assert set(base["starting_xi"]) == set(candidate["starting_xi"])
    assert (base["captain"], candidate["captain"]) == (18, 17)
    totals = dict(zip(rows.player_id, rows.realized_points, strict=True))
    assert measured.comparator_realized_points == pytest.approx(
        sum(totals[p] for p in base["starting_xi"]) + totals[18]
    )
    assert measured.decision_difference == pytest.approx(totals[17] - totals[18])
    assert measured.decision_difference > 0
    assert measured.candidate_mae == 0
    assert measured.absolute_error_improvement == pytest.approx(measured.comparator_mae)
    assert measured.absolute_error_improvement > 0
    assert measured.identical_decision is False


def test_gate_weights_whole_weeks_equally_and_keeps_versions() -> None:
    measured, _ = study.measure_week(
        frame(), season=study.SEASON, gameweek=7, handoff_version="old"
    )
    weeks = tuple(
        replace(
            measured,
            gameweek=7 + i,
            players=1 if i == 0 else 1000,
            handoff_version="old" if i < 4 else "new",
            squared_error_improvement=float(i + 1),
            rank_improvement=0,
            decision_difference=0,
            identical_decision=True,
        )
        for i in range(8)
    )
    report = study.summarize(weeks)
    assert report["verdict"] == "passed"
    assert report["squared_error_improvement"] == 4.5
    assert report["by_handoff_version"]["old"]["weeks"] == 4
    assert report["identical_decisions"] == 8
    assert study.summarize(weeks[:7])["verdict"] == "insufficient_evidence"
    assert (
        study.summarize(tuple(replace(w, rank_improvement=-0.001) for w in weeks))["verdict"]
        == "failed"
    )
    assert (
        study.summarize(tuple(replace(w, decision_difference=-0.001) for w in weeks))["verdict"]
        == "failed"
    )
    assert (
        study.summarize(tuple(replace(w, squared_error_improvement=0) for w in weeks))["verdict"]
        == "failed"
    )


def test_locked_season_is_refused_before_inventory_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("loader was called")

    monkeypatch.setattr(runner, "partial_snapshot", forbidden)
    with pytest.raises(study.DifficultyInputError, match="2025-26"):
        runner.inventory(tmp_path, season="2025-26", as_of="2027-01-20T00:00:00Z")
    monkeypatch.setattr(runner, "frozen_declaration", forbidden)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "--season",
            "2025-26",
            "--snapshot-root",
            str(tmp_path),
            "--handoff-root",
            str(tmp_path),
            "--as-of",
            "2027-01-20T00:00:00Z",
            "--output-directory",
            str(tmp_path),
        ],
    )
    assert runner.main() == 1


def test_unmerged_declaration_refuses_before_any_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        runner, "command", lambda *args: json.dumps({"state": "OPEN", "mergedAt": None})
    )
    with pytest.raises(study.DifficultyInputError, match="merge"):
        runner.frozen_declaration()


def test_pairing_refuses_multiple_fingerprints_and_missing_latest(tmp_path: Path) -> None:
    snapshot = captured(tmp_path / "captures")
    base = handoff(tmp_path / "handoffs", snapshot)
    paired, _ = runner.paired_handoff(tmp_path / "handoffs", snapshot, 7)
    assert paired.fingerprint == base.fingerprint
    handoff(tmp_path / "handoffs", snapshot, filename="other.json", delta=1)
    with pytest.raises(study.DifficultyMissingInputs, match="exactly one"):
        runner.paired_handoff(tmp_path / "handoffs", snapshot, 7)
    later = captured(tmp_path / "captures", offset=1)
    selected = runner.decision_capture({s.metadata.snapshot_id: s for s in (snapshot, later)}, 7)
    assert selected.metadata.snapshot_id == later.metadata.snapshot_id
    with pytest.raises(study.DifficultyMissingInputs):
        runner.paired_handoff(tmp_path / "handoffs", selected, 7)


def test_early_reading_refuses_before_any_outcome_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decision = captured(tmp_path / "captures")

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("outcome opened")

    monkeypatch.setattr(runner, "partial_snapshot", forbidden)
    with pytest.raises(study.DifficultyMissingInputs, match="GW20"):
        runner.reading(
            {decision.metadata.snapshot_id: decision},
            snapshot_root=tmp_path / "captures",
            handoff_root=tmp_path / "handoffs",
            declaration={"merged_at": "2026-10-01T00:00:00Z"},
            as_of="2026-10-07T00:00:00Z",
            output_directory=tmp_path / "artifacts/study",
            owner_approved=True,
            weekly_run_idle=True,
        )


def test_inventory_never_opens_event_payloads_and_skips_future_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured(tmp_path, final=True)
    original = Path.read_bytes

    def checked(path: Path) -> bytes:
        if path.name.startswith("event-"):
            raise AssertionError("outcome opened during inventory")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", checked)
    assert runner.inventory(tmp_path, season=study.SEASON, as_of="2026-10-01T00:00:00Z") == {}
    assert len(runner.inventory(tmp_path, season=study.SEASON, as_of="2027-01-20T00:00:00Z")) == 1


def test_join_keeps_zero_minutes_and_drops_missing_rows_with_availability_once(
    tmp_path: Path,
) -> None:
    decision = captured(tmp_path / "captures")
    base = handoff(tmp_path / "handoffs", decision)

    def change(docs: dict[str, Any]) -> None:
        docs[live_payload(7)]["elements"] = [
            e for e in docs[live_payload(7)]["elements"] if e["id"] != 2
        ]

    outcome = captured(tmp_path / "captures", final=True, change=change)
    rows, dropped = runner.joined_rows(decision, base, outcome, 7)
    assert dropped == [1002]
    assert 1008 in set(rows.player_id)
    assert rows.set_index("player_id").loc[1008, "realized_points"] == 0
    assert (
        rows.set_index("player_id").loc[1003, "predicted_points"]
        == base.expected_points[1003] * 0.5
    )


def test_binding_start_excludes_deadline_equal_to_merge_and_settlement_is_earliest(
    tmp_path: Path,
) -> None:
    first = captured(tmp_path, final=True)
    later = captured(tmp_path, final=True, offset=1)
    selected = runner.first_settled({s.metadata.snapshot_id: s for s in (later, first)})
    assert selected.metadata.snapshot_id == first.metadata.snapshot_id
    assert runner.eligible_weeks(first, stamp(START + timedelta(weeks=6))) == tuple(range(8, 21))


def test_once_only_claim_survives_across_output_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "captures"
    decision = captured(root)
    outcome = captured(root, final=True)
    handoff(tmp_path / "handoffs", decision)
    snapshots = runner.inventory(root, season=study.SEASON, as_of="2027-01-20T00:00:00Z")
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(
        runner,
        "command",
        lambda *args: str(tmp_path / "common") if "--git-common-dir" in args else "",
    )
    kwargs = dict(
        snapshot_root=root,
        handoff_root=tmp_path / "handoffs",
        declaration={"merged_at": "2026-10-01T00:00:00Z", "sha256": runner.DECLARATION_SHA256},
        as_of="2027-01-20T00:00:00Z",
        owner_approved=True,
        weekly_run_idle=True,
    )
    report = runner.reading(snapshots, output_directory=tmp_path / "artifacts/one", **kwargs)
    assert report["reading_capture"] == outcome.metadata.snapshot_id
    assert report["valid_weeks"] == 1
    assert report["verdict"] == "insufficient_evidence"
    assert (tmp_path / "artifacts/one/gw07-players.csv").is_file()

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("second outcome read")

    monkeypatch.setattr(runner, "partial_snapshot", forbidden)
    other_worktree = tmp_path / "other-worktree"
    monkeypatch.setattr(runner, "ROOT", other_worktree)
    with pytest.raises(study.DifficultyInputError, match="single reading"):
        runner.reading(snapshots, output_directory=other_worktree / "artifacts/two", **kwargs)


@pytest.mark.parametrize("unfinished", ["data_checked", "fixture", "future_kickoff"])
def test_settlement_refuses_unfinished_or_future_fixtures(tmp_path: Path, unfinished: str) -> None:
    def change(docs: dict[str, Any]) -> None:
        if unfinished == "data_checked":
            docs[BOOTSTRAP_PAYLOAD]["events"][-1]["data_checked"] = False
        else:
            fixture = docs[FIXTURES_PAYLOAD][-1]
            if unfinished == "fixture":
                fixture["finished"] = False
            else:
                fixture["kickoff_time"] = "2027-01-20T00:00:00Z"

    snapshot = captured(tmp_path, final=True, change=change)
    with pytest.raises(study.DifficultyMissingInputs, match="GW20"):
        runner.first_settled({snapshot.metadata.snapshot_id: snapshot})


def test_settled_blank_week_needs_no_nonexistent_fixture(tmp_path: Path) -> None:
    def change(docs: dict[str, Any]) -> None:
        docs[FIXTURES_PAYLOAD] = [f for f in docs[FIXTURES_PAYLOAD] if f["event"] != 20]

    snapshot = captured(tmp_path, final=True, change=change)
    assert runner.first_settled({snapshot.metadata.snapshot_id: snapshot}) == snapshot


def test_candidate_solve_failure_retains_both_traces(monkeypatch: pytest.MonkeyPatch) -> None:
    original = study._squad
    calls = 0

    def solve(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls > 1:
            kwargs["diagnostics"].update({"solver_status": "UNKNOWN", "squad": []})
            raise study.ExperimentExecutionError("synthetic solve failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(study, "_squad", solve)
    with pytest.raises(study.DifficultySolveFailure) as failure:
        study.measure_week(frame(), season=study.SEASON, gameweek=7, handoff_version="base")
    assert failure.value.decisions["comparator"]["solver_status"] == "OPTIMAL"
    assert failure.value.decisions["candidate"]["solver_status"] == "UNKNOWN"
    assert [a["error"] for a in failure.value.decisions["candidate"]["attempts"]] == [
        "ExperimentExecutionError",
        "ExperimentExecutionError",
    ]
    assert calls == 3


def test_coefficient_identity_is_identical_on_windows_and_linux() -> None:
    content = (runner.ROOT / "docs/opponent_projection_study.json").read_bytes()
    lf = content.replace(b"\r\n", b"\n")
    study.verify_coefficients(lf)
    study.verify_coefficients(lf.replace(b"\n", b"\r\n"))


def test_join_reads_own_side_and_mean_of_double_and_blank(tmp_path):
    def change(docs):
        fixtures = docs[FIXTURES_PAYLOAD]
        fixtures[:] = [f for f in fixtures if not (f["event"] == 7 and f["team_h"] == 9)]
        extra = next(f.copy() for f in fixtures if f["event"] == 7 and f["team_h"] == 1)
        extra.update(id=999, team_h_difficulty=4, team_a=4)
        fixtures.append(extra)

    decision = captured(tmp_path / "captures", change=change)
    base = handoff(tmp_path / "handoffs", decision)
    outcome = captured(tmp_path / "captures", final=True)
    rows, _ = runner.joined_rows(decision, base, outcome, 7)
    by_id = rows.set_index("player_id")
    assert by_id.loc[1001, "published_signal"] == -3
    assert by_id.loc[1002, "published_signal"] == -4
    assert by_id.loc[1003, "published_signal"] == -2
    assert by_id.loc[1004, "published_signal"] == -4
    assert by_id.loc[1001, "fixture_count"] == 2
    assert np.isnan(by_id.loc[1009, "published_signal"])
    assert by_id.loc[1009, "fixture_count"] == 0
    adjusted, multiplier = study.adjusted_points(rows)
    offset = rows.index[rows.player_id.eq(1009)][0]
    assert multiplier[offset] == 1
    assert adjusted[offset] == by_id.loc[1009, "predicted_points"]


def test_handoff_written_at_deadline_is_refused(tmp_path):
    snapshot = captured(tmp_path / "captures")
    root = tmp_path / "handoffs"
    handoff(root, snapshot)
    path = next((root / "by-capture" / snapshot.metadata.snapshot_id).glob("*.json"))
    instant = (START + timedelta(weeks=6)).timestamp()
    os.utime(path, (instant, instant))
    with pytest.raises(study.DifficultyMissingInputs, match="exactly one"):
        runner.paired_handoff(root, snapshot, 7)


def test_admitted_name_with_locked_bootstrap_refuses_before_event_read(tmp_path, monkeypatch):
    def change(docs):
        for event in docs[BOOTSTRAP_PAYLOAD]["events"]:
            event["deadline_time"] = stamp(
                datetime.fromisoformat(event["deadline_time"]) - timedelta(days=365)
            )

    snapshot = captured(tmp_path, final=True, change=change)
    original = Path.read_bytes
    opened = []

    def tracked(path):
        opened.append(path.name)
        assert not path.name.startswith("event-")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", tracked)
    with pytest.raises(study.DifficultyInputError, match="2025-26"):
        runner.partial_snapshot(tmp_path / snapshot.metadata.snapshot_id, (live_payload(7),))
    assert BOOTSTRAP_PAYLOAD in opened


def test_equal_latest_instants_make_week_missing(tmp_path):
    one = captured(tmp_path)

    def change(docs):
        docs[BOOTSTRAP_PAYLOAD]["elements"][0]["first_name"] = "Different"

    two = captured(tmp_path, change=change)
    assert one.metadata.snapshot_id != two.metadata.snapshot_id
    with pytest.raises(study.DifficultyMissingInputs, match="ambiguous"):
        runner.decision_capture({s.metadata.snapshot_id: s for s in (one, two)}, 7)


def reading_setup(tmp_path, monkeypatch, *, outcome_change=None):
    root = tmp_path / "captures"
    decision = captured(root)
    captured(root, final=True, change=outcome_change)
    handoff(tmp_path / "handoffs", decision)
    snapshots = runner.inventory(root, season=study.SEASON, as_of="2027-01-20T00:00:00Z")
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(
        runner,
        "command",
        lambda *args: str(tmp_path / "common") if "--git-common-dir" in args else "",
    )
    return snapshots, dict(
        snapshot_root=root,
        handoff_root=tmp_path / "handoffs",
        declaration={"merged_at": "2026-10-01T00:00:00Z", "sha256": runner.DECLARATION_SHA256},
        as_of="2027-01-20T00:00:00Z",
        output_directory=tmp_path / "artifacts/one",
        owner_approved=True,
        weekly_run_idle=True,
    )


@pytest.mark.parametrize("bad_root", ["absent", "unpaired", "invalid_projection"])
def test_outcome_free_preflight_does_not_spend_claim(tmp_path, monkeypatch, bad_root):
    snapshots, kwargs = reading_setup(tmp_path, monkeypatch)
    if bad_root == "absent":
        kwargs["handoff_root"] = tmp_path / "typo"
    if bad_root == "unpaired":
        kwargs["handoff_root"] = tmp_path / "empty"
        kwargs["handoff_root"].mkdir()
    if bad_root == "invalid_projection":

        def broken(*args, **kwargs):
            raise runner.DataError("synthetic bad projection")

        monkeypatch.setattr(runner, "project", broken)

    def forbidden(*args, **kwargs):
        raise AssertionError("outcome opened before preflight")

    monkeypatch.setattr(runner, "partial_snapshot", forbidden)
    with pytest.raises(study.DifficultyMissingInputs, match="no reading was claimed"):
        runner.reading(snapshots, **kwargs)
    assert not (tmp_path / "common/research-claims").exists()
    assert not kwargs["output_directory"].exists()


def test_unchecked_nonfinal_week_is_missing_in_single_reading(tmp_path, monkeypatch):
    def change(docs):
        docs[BOOTSTRAP_PAYLOAD]["events"][6]["data_checked"] = False

    snapshots, kwargs = reading_setup(tmp_path, monkeypatch, outcome_change=change)
    report = runner.reading(snapshots, **kwargs)
    seven = next(w for w in report["week_identities"] if w["gameweek"] == 7)
    assert seven["status"] == "missing"
    assert report["valid_weeks"] == 0
    assert not (kwargs["output_directory"] / "gw07-players.csv").exists()


@pytest.mark.parametrize(
    "refused", ["duplicate_live_id", "no_matched_row", "invalid_json", "duplicate_key"]
)
def test_refused_week_outcome_is_missing_rather_than_a_refused_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refused: str
) -> None:
    def change(docs: dict[str, Any]) -> None:
        held = docs[live_payload(7)]["elements"]
        if refused == "duplicate_live_id":
            held.append(dict(held[0]))
        elif refused == "no_matched_row":
            held.clear()
        elif refused == "invalid_json":
            docs[live_payload(7)] = b'{"elements": ['
        else:
            docs[live_payload(7)] = b'{"elements": [], "elements": []}'

    snapshots, kwargs = reading_setup(tmp_path, monkeypatch, outcome_change=change)
    report = runner.reading(snapshots, **kwargs)
    seven = next(w for w in report["week_identities"] if w["gameweek"] == 7)
    assert (seven["status"], seven["reason"]) == ("missing", "DifficultyMissingInputs")
    assert report["valid_weeks"] == 0
    assert not (kwargs["output_directory"] / "refused.json").exists()


def test_settled_roster_is_refused_before_the_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def change(docs: dict[str, Any]) -> None:
        players = docs[BOOTSTRAP_PAYLOAD]["elements"]
        players[1]["code"] = players[0]["code"]

    snapshots, kwargs = reading_setup(tmp_path, monkeypatch, outcome_change=change)
    with pytest.raises(study.DifficultyInputError, match="roster"):
        runner.reading(snapshots, **kwargs)
    assert not (tmp_path / "common/research-claims").exists()
    assert not kwargs["output_directory"].exists()
