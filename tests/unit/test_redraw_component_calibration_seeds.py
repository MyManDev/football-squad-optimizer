"""The seed-sensitivity reading of the joint sampler's calibration record: which folds it
re-draws, how it counts S2 per seed, the seed-0 check that guards it, the location and plug-in
readings it takes from the record alone, and a re-draw that is the calibration run's own."""

from dataclasses import replace

import pytest
from scripts.redraw_component_calibration_seeds import (
    BLOCK,
    CANDIDATE,
    FoldTask,
    SeedReadingError,
    _poisson_binomial_at_most,
    boundary_fold_ids,
    location_against_block,
    lower_tail_counts_by_seed,
    plug_in_lower_tail,
    redraw_fold,
    seed_reading,
)
from scripts.run_component_squad_calibration import (
    _history_rows,
    _measure_fold,
    _selected_component_inputs,
)
from tests.unit.test_run_component_squad_calibration import _squad_positions
from tests.unit.test_run_component_squad_calibration_team_match_block import (
    _handoff_with_clubs,
)

from squadopt.scenarios import ScenarioConfig
from squadopt.scenarios.components import TeamMatchJointConfig


def _arm(pit: float, below: bool, mean: float, q10: float, sd: float = 10.0) -> dict[str, object]:
    return {
        "realized_score": 40.0,
        "probability_integral_transform": pit,
        "realized_below_q10": below,
        "q10_score": q10,
        "scenario_mean_score": mean,
        "scenario_standard_deviation": sd,
        "scenario_fingerprint": f"fp-{pit}-{q10}",
        "component_fingerprint": "components",
    }


def _folds() -> list[dict[str, object]]:
    rows = (
        # fold, candidate (pit, below, mean, q10), block (pit, below, mean, q10)
        ("2021-22-gw11", (0.10, False, 50.0, 39.9), (0.09, True, 50.2, 40.1)),
        ("2021-22-gw12", (0.30, False, 52.0, 35.0), (0.31, False, 52.1, 35.1)),
        ("2022-23-gw05", (0.02, True, 60.0, 45.0), (0.02, True, 60.1, 45.1)),
        ("2022-23-gw06", (0.50, False, 41.0, 30.0), (0.70, False, 41.2, 30.2)),
    )
    return [
        {"fold_id": fold_id, **_arm(*candidate), "block_arm": _arm(*block)}
        for fold_id, candidate, block in rows
    ]


def _redrawn(flags: dict[str, tuple[tuple[bool, bool], ...]]) -> dict[str, object]:
    """Per fold, per seed, both arms' readouts; seed 0 copies the record's own readout."""

    folds = {str(fold["fold_id"]): fold for fold in _folds()}
    redrawn: dict[str, object] = {}
    for fold_id, by_seed in flags.items():
        recorded = folds[fold_id]
        readings: dict[str, object] = {}
        for seed, (candidate, block) in enumerate(by_seed):
            if seed == 0:
                readings["0"] = {
                    CANDIDATE: {key: recorded[key] for key in _arm(0, False, 0, 0)},
                    BLOCK: dict(recorded["block_arm"]),  # type: ignore[call-overload]
                }
                continue
            readings[str(seed)] = {
                CANDIDATE: _arm(0.1, candidate, 50.0, 40.0),
                BLOCK: _arm(0.1, block, 50.0, 40.0),
            }
        redrawn[fold_id] = readings
    return redrawn


def test_the_boundary_is_read_under_either_arm() -> None:
    assert boundary_fold_ids(_folds(), 0.06, 0.14) == ("2021-22-gw11",)
    assert boundary_fold_ids(_folds(), 0.0, 0.05) == ("2022-23-gw05",)
    # gw06 lies in [0.6, 0.8] under the block only, and is still taken.
    assert boundary_fold_ids(_folds(), 0.6, 0.8) == ("2022-23-gw06",)


def test_a_seed_count_is_the_redrawn_flags_plus_every_other_folds_recorded_flag() -> None:
    redrawn = _redrawn({"2021-22-gw11": ((False, True), (True, True), (False, False))})
    candidate = lower_tail_counts_by_seed(_folds(), redrawn, (0, 1, 2), CANDIDATE)  # type: ignore[arg-type]
    block = lower_tail_counts_by_seed(_folds(), redrawn, (0, 1, 2), BLOCK)  # type: ignore[arg-type]

    # gw05 is the one recorded flag outside the re-drawn fold, under both arms.
    assert candidate["fixed_count_outside_the_redrawn_folds"] == 1
    assert candidate["counts_by_seed"] == {"0": 1, "1": 2, "2": 1}
    assert block["counts_by_seed"] == {"0": 2, "1": 2, "2": 1}
    assert candidate["mean_count"] == pytest.approx(4 / 3)
    assert (candidate["min_count"], candidate["max_count"]) == (1, 2)
    # Four folds: [0.04, 0.16] holds no count, since 1/4 is already above the band.
    assert candidate["seeds_within_s2_band"] == 0


def test_the_reading_refuses_unless_seed_zero_reproduces_the_record() -> None:
    redrawn = _redrawn({"2021-22-gw11": ((False, True), (True, True))})
    reading = seed_reading(_folds(), redrawn, (0, 1))  # type: ignore[arg-type]
    folds = reading["folds"]
    assert folds["2021-22-gw11"]["flags_by_seed"] == {CANDIDATE: [0, 1], BLOCK: [1, 1]}  # type: ignore[index]
    assert folds["2021-22-gw11"]["realized_score"] == 40.0  # type: ignore[index]
    outside = reading["folds_outside_the_boundary"]
    assert outside["count"] == 3  # type: ignore[index]
    assert outside["nearest_pit_distance_from_0_10"][CANDIDATE] == pytest.approx(0.08)  # type: ignore[index]

    moved = _redrawn({"2021-22-gw11": ((False, True), (True, True))})
    moved["2021-22-gw11"]["0"][BLOCK]["q10_score"] = 40.2  # type: ignore[index]
    with pytest.raises(SeedReadingError, match="2021-22-gw11/block_arm"):
        seed_reading(_folds(), moved, (0, 1))  # type: ignore[arg-type]
    with pytest.raises(SeedReadingError, match="Seed 0"):
        seed_reading(_folds(), redrawn, (1,))  # type: ignore[arg-type]


def test_the_location_reading_separates_a_shift_from_a_fatter_tail() -> None:
    reading = location_against_block(_folds())

    # Every fold's q10 moves by exactly its mean: a pure location shift, no change of shape.
    assert reading["mean_score_difference_mean"] == pytest.approx(-0.15)
    assert reading["q10_difference_mean"] == pytest.approx(-0.15)
    assert reading["centred_q10_difference_mean"] == pytest.approx(0.0)
    assert reading["folds_with_candidate_centred_q10_lower"] == 0
    assert reading["folds_with_candidate_mean_lower"] == 4
    # gw11: the block's 40.1 moved by -0.2 is 39.9, and the realized 40 no longer falls below.
    assert reading["block_folds_leaving_the_tail_when_moved"] == ["2021-22-gw11"]
    assert reading["block_folds_entering_the_tail_when_moved"] == []
    assert reading["block_count_with_q10_moved_by_the_mean_difference"] == 1


def test_the_plug_in_count_brackets_the_flag_probability() -> None:
    assert _poisson_binomial_at_most([0.5, 0.5], 0) == pytest.approx(0.25)
    assert _poisson_binomial_at_most([0.5, 0.5], 1) == pytest.approx(0.75)
    folds = [
        {"fold_id": "a", **_arm(0.0, True, 50.0, 40.0)},
        {"fold_id": "b", **_arm(0.5, False, 50.0, 40.0)},
    ]
    reading = plug_in_lower_tail(folds, CANDIDATE)
    low = reading["at_most_99"]["expected_count"]  # type: ignore[index]
    high = reading["at_most_100"]["expected_count"]  # type: ignore[index]
    assert low == pytest.approx(1.0) and high == pytest.approx(1.0)
    at_boundary = plug_in_lower_tail([{"fold_id": "c", **_arm(0.1, False, 50.0, 40.0)}], CANDIDATE)
    assert (
        at_boundary["at_most_99"]["expected_count"]  # type: ignore[index]
        < 0.5
        < at_boundary["at_most_100"]["expected_count"]  # type: ignore[index]
    )


def test_a_redraw_at_the_recorded_seed_is_the_calibration_runs_own_draw() -> None:
    handoff, prepared, result = _handoff_with_clubs()
    settings = ScenarioConfig(scenario_count=64)
    selected = tuple(_squad_positions())
    _, record = _measure_fold(
        handoff,
        prepared,
        result,
        40.0,
        selected,
        settings,
        TeamMatchJointConfig(),  # type: ignore[arg-type]
        control_arm=True,
    )
    inputs, snapshot = _selected_component_inputs(handoff, prepared, selected)  # type: ignore[arg-type]
    rows = _history_rows(handoff, TeamMatchJointConfig())
    fold_id = str(prepared.fold_id)  # type: ignore[attr-defined]
    task = FoldTask(
        fold_id=fold_id,
        inputs=inputs,
        snapshot=snapshot,
        history=rows.loc[rows["fold_id"].astype("string") < fold_id].copy(),
        result=result,  # type: ignore[arg-type]
        realized_score=40.0,
        seeds=(0, 1),
        base=settings,
    )

    readings = redraw_fold(task)

    assert set(readings) == {"0", "1"}
    candidate = readings["0"][CANDIDATE]
    block = readings["0"][BLOCK]
    assert all(record[name] == value for name, value in candidate.items())
    assert all(record["block_arm"][name] == value for name, value in block.items())  # type: ignore[index]
    assert readings["1"][CANDIDATE]["scenario_fingerprint"] != candidate["scenario_fingerprint"]
    # A seed's draw does not depend on the seeds drawn before it.
    assert redraw_fold(replace(task, seeds=(1,)))["1"] == readings["1"]
