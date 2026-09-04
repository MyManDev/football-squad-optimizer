"""Behaviour tests for the component sampler fidelity diagnostic.

Everything is synthetic and small enough to work out by hand. The residual pool is built so
that every historical row carries the *same* pair of residuals, which makes the sampler's
output fully determinate: with a certain appearance, every cell draws minutes ``mu + 10`` and
points ``mu + 1`` whichever fold and row it picks. That is what lets a test state the expected
metrics as exact numbers instead of asserting a tolerance around an unknown.

The tests assert behaviour. None parses source text, none pins a private helper's name, and
none re-tests ``write_document_once``'s own writer contract -- that writer has its own tests,
so only the integration is checked here.
"""

import json
from pathlib import Path

import pandas as pd
import pytest
from scripts.measure_component_fidelity import (
    FIDELITY_CONTRACT_VERSION,
    METRIC_NAMES,
    measure_fidelity,
)

from squadopt.experiments.shadow_report import ShadowReportError, write_document_once
from squadopt.scenarios import ScenarioConfig

PLAYERS = (101, 102, 103)
HISTORY_FOLDS = ("2026-27-gw01", "2026-27-gw02")
TARGET_FOLD = "2026-27-gw03"
ALL_FOLDS = (*HISTORY_FOLDS, TARGET_FOLD)

# Small enough to stay fast. min_history_folds=2 is the config's own floor, and it makes the
# two history folds ineligible while the target fold has exactly enough history.
CONFIG = ScenarioConfig(scenario_count=32, deterministic_seed=3, min_history_folds=2)

MANIFEST = {
    "model_version": "synthetic-components-v1",
    "feature_contract_version": "synthetic-features-v1",
    "target_contract_version": "synthetic-targets-v1",
    "dataset_contract_version": "synthetic-dataset-v1",
    # Real lowercase hex, because PredictionProvenance validates this as a SHA-256 digest.
    "table_sha256": "a" * 64,
    "roster_sha256": "b" * 64,
    "locked_holdout_read": False,
}


def _oof(**overrides: object) -> pd.DataFrame:
    """Every row carries minutes residual +10 and points residual +1, in every fold."""

    records: list[dict[str, object]] = []
    for fold in ALL_FOLDS:
        for player in PLAYERS:
            records.append(
                {
                    "season": "2026-27",
                    "fold_id": fold,
                    "player_id": player,
                    "fixture_count": 1,
                    "appearance_probability": 1.0,
                    "expected_minutes_if_appearance": 45.0,
                    "raw_expected_points_if_appearance": 4.0,
                    "control_expected_points": 4.0,
                    "composition_route": "component_model",
                    "evidence_status": "not_requested",
                    "appearance_target": 1,
                    "minutes_target": 55.0,  # residual +10 against the pool's own mean of 45
                    "points_target": 5.0,  # residual +1 against 4
                }
            )
    frame = pd.DataFrame(records)
    for column, value in overrides.items():
        frame[column] = value
    return frame


def _roster() -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for fold in ALL_FOLDS:
        for index, player in enumerate(PLAYERS):
            records.append(
                {
                    "fold_id": fold,
                    "player_id": player,
                    "name": f"Synthetic {player}",
                    "team_id": f"Team {index % 2}",
                    "position": ("MID", "FWD", "DEF")[index],
                    "price_tenths": 50,
                }
            )
    return pd.DataFrame(records)


def _measure(oof: pd.DataFrame | None = None) -> dict[str, object]:
    return measure_fidelity(_oof() if oof is None else oof, _roster(), MANIFEST, config=CONFIG)


def _target_fold(document: dict[str, object]) -> dict[str, object]:
    folds = [record for record in document["folds"] if record["fold_id"] == TARGET_FOLD]  # type: ignore[union-attr]
    assert len(folds) == 1, f"expected {TARGET_FOLD} to be measured, got {document['folds']!r}"
    return folds[0]


# --- determinism and shape ---------------------------------------------------


def test_the_same_inputs_produce_the_same_document() -> None:
    """No wall clock inside the measurement, so the document itself is fully comparable."""

    first = _measure()
    second = _measure()

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["contract_version"] == FIDELITY_CONTRACT_VERSION
    assert first["diagnostic_only"] is True
    assert first["promotes_anything"] is False
    assert first["registers_any_threshold"] is False


# --- the numbers, worked out by hand -----------------------------------------


def test_every_metric_matches_the_hand_calculated_value() -> None:
    """The pool forces one outcome, so each of the five differences is an exact number.

    Certain appearance, one distinct residual pair, and a 90-minute ceiling that 55 does not
    reach. So every cell is minutes 45+10 = 55 and points 4+1 = 5, and:

    A appearance          1.0 - 1.0                = 0.0
    B points, uncond.     5.0 - (1.0 * 4.0)        = +1.0
    C minutes, uncond.    55.0 - (1.0 * 45.0)      = +10.0
    D minutes, cond.      55.0 - 45.0              = +10.0
    E points, cond.       5.0 - 4.0                = +1.0
    """

    record = _target_fold(_measure())
    expected = {
        "appearance": (0.0, 1.0, 1.0),
        "points_unconditional": (1.0, 5.0, 4.0),
        "minutes_unconditional": (10.0, 55.0, 45.0),
        "minutes_conditional": (10.0, 55.0, 45.0),
        "points_conditional": (1.0, 5.0, 4.0),
    }
    assert set(expected) == set(METRIC_NAMES)  # all five, none quietly dropped
    for name, (difference, sampled, predicted) in expected.items():
        assert record[f"{name}_mean_difference"] == pytest.approx(difference), name
        assert record[f"{name}_sampled_mean"] == pytest.approx(sampled), name
        assert record[f"{name}_predicted_mean"] == pytest.approx(predicted), name
        assert record[f"{name}_sample_count"] == len(PLAYERS), name

    assert record["floor_engaged_cells"] == 0
    assert record["blank_fixture_cells"] == 0
    assert record["appeared_cells"] == CONFIG.scenario_count * len(PLAYERS)


def test_a_negative_point_outcome_is_measured_rather_than_clipped() -> None:
    """The sampled *level* is what shows this; a signed difference alone could not.

    With a conditional mean of -6 and a points residual of +1, the sampled outcome is -5. Both
    are negative, so a clip at zero anywhere in the chain would be visible here.
    """

    # Only the target fold's *prediction* moves. The history keeps its +1 points residual,
    # which is the point: the residual comes from the past and the mean it lands on does not.
    frame = _oof()
    target = frame["fold_id"] == TARGET_FOLD
    frame.loc[target, "raw_expected_points_if_appearance"] = -6.0
    frame.loc[target, "control_expected_points"] = 0.0  # the export's non-negative composition

    record = _target_fold(_measure(frame))

    assert record["points_conditional_sampled_mean"] == pytest.approx(-5.0)
    assert record["points_conditional_predicted_mean"] == pytest.approx(-6.0)
    assert record["points_conditional_mean_difference"] == pytest.approx(1.0)


def test_the_one_minute_floor_is_counted_when_the_pool_forces_it() -> None:
    """A conditional mean of 5 against a historical residual of -30 lands below zero.

    Without the floor these cells would read zero minutes while the appearance state says the
    player featured -- the contradiction the floor exists to prevent.
    """

    # The history supplies the residual (15 - 45 = -30); the target fold supplies the mean it
    # is added to (5). So the unclipped draw is -25 on every cell and the floor takes it to 1.
    frame = _oof()
    target = frame["fold_id"] == TARGET_FOLD
    frame.loc[~target, "minutes_target"] = 15.0
    frame.loc[target, "expected_minutes_if_appearance"] = 5.0

    document = _measure(frame)
    record = _target_fold(document)

    assert record["floor_engaged_cells"] == CONFIG.scenario_count * len(PLAYERS)
    assert record["minutes_conditional_sampled_mean"] == pytest.approx(1.0)
    assert record["minutes_conditional_mean_difference"] == pytest.approx(-4.0)
    assert document["counts"]["floor_engaged_rate"] == pytest.approx(1.0)  # type: ignore[index]
    assert document["counts"]["floor_engagement_is_upper_bound"] is True  # type: ignore[index]


def test_a_blank_fixture_yields_no_appearance_and_no_conditional_observation() -> None:
    """Synthetic, because no development component row actually carries a blank fixture.

    Certainty of appearing cannot override having no fixture, so the player never features and
    contributes nothing to the conditional metrics rather than contributing a zero.
    """

    frame = _oof()
    frame["fixture_count"] = 0
    frame["expected_minutes_if_appearance"] = 0.0

    document = _measure(frame)
    record = _target_fold(document)

    assert record["appearance_sampled_mean"] == pytest.approx(0.0)
    assert record["appearance_mean_difference"] == pytest.approx(-1.0)
    assert record["appeared_cells"] == 0
    assert record["blank_fixture_cells"] == CONFIG.scenario_count * len(PLAYERS)
    assert record["players_never_appearing"] == len(PLAYERS)
    assert record["minutes_conditional_sample_count"] == 0
    assert document["warnings"]  # the missing conditional observations are named, not hidden


# --- population rules --------------------------------------------------------


def test_the_locked_holdout_is_refused() -> None:
    frame = _oof()
    frame.loc[0, "season"] = "2025-26"

    with pytest.raises(SystemExit, match="locked holdout"):
        _measure(frame)


def test_direct_control_rows_are_excluded_from_the_measurement_and_counted() -> None:
    """They carry no component prediction, so they are counted rather than filled.

    Excluding them at input construction is also what keeps the sampler's fail-closed refusal
    from firing: after the filter no control row reaches it.
    """

    frame = _oof()
    control = frame["player_id"] == PLAYERS[0]
    frame.loc[control, "composition_route"] = "direct_control"
    for column in (
        "appearance_probability",
        "expected_minutes_if_appearance",
        "raw_expected_points_if_appearance",
    ):
        frame[column] = frame[column].astype("float64")
        frame.loc[control, column] = float("nan")

    document = _measure(frame)
    record = _target_fold(document)

    assert record["direct_control_rows"] == 1
    assert record["players"] == len(PLAYERS) - 1
    assert record["appearance_sample_count"] == len(PLAYERS) - 1
    assert document["counts"]["direct_control_excluded_rows"] == len(ALL_FOLDS)  # type: ignore[index]
    # The measurement still ran on what remained, rather than refusing the whole fold.
    assert record["appearance_mean_difference"] == pytest.approx(0.0)


def test_a_fold_that_cannot_be_measured_is_recorded_with_its_reason() -> None:
    """The residual pool's own sufficiency rule decides eligibility, and says why."""

    document = _measure()
    excluded = {str(entry["fold_id"]): str(entry["reason"]) for entry in document["excluded_folds"]}  # type: ignore[union-attr]

    assert set(excluded) == set(HISTORY_FOLDS)
    assert all(reason for reason in excluded.values())
    assert document["population"]["fold_count_measured"] == 1  # type: ignore[index]
    assert document["population"]["measured_fold_ids"] == [TARGET_FOLD]  # type: ignore[index]


def test_the_callers_frames_are_not_mutated() -> None:
    oof, roster = _oof(), _roster()
    before = (oof.copy(deep=True), roster.copy(deep=True))

    measure_fidelity(oof, roster, MANIFEST, config=CONFIG)

    pd.testing.assert_frame_equal(oof, before[0])
    pd.testing.assert_frame_equal(roster, before[1])


# --- create-once integration, not the writer's own contract ------------------


def test_an_identical_rerun_replays_and_a_different_document_conflicts(
    tmp_path: Path,
) -> None:
    """Only the integration: the writer's atomicity has its own tests elsewhere."""

    document = _measure()
    destination = tmp_path / "phase_d_component_fidelity.json"

    assert write_document_once(document, destination) == "written"
    assert write_document_once(_measure(), destination) == "replay"

    with pytest.raises(ShadowReportError):
        write_document_once({**document, "diagnostic_only": False}, destination)
