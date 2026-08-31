from __future__ import annotations

from argparse import Namespace
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

from squadopt.experiments.attacking_hurdle import (
    INCONCLUSIVE,
    NOT_LOCALIZED,
    OCCURRENCE_CARRIER,
    POSITIVE_SEVERITY_CARRIER,
    SHARED_HURDLE_FAILURE,
    AttackingHurdleError,
    build_fold_reading,
    classify,
    decompose_player_rows,
    summarise,
)


def _players(
    *, low_positive_support: bool = False, missing_zero_fallback: bool = False
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for index in range(11):
        probability = 0.0 if index == 0 else (0.25 if low_positive_support and index == 1 else 0.5)
        history_positive = 0 if index == 0 else (3 if low_positive_support and index == 1 else 6)
        reference_positive = (
            0 if index == 0 and missing_zero_fallback else (7 if index == 0 else history_positive)
        )
        positive_mean = float("nan") if reference_positive == 0 else (4.0 if index == 0 else 2.0)
        rows.append(
            {
                "fold_id": "2023-24-gw10",
                "season": "2023-24",
                "player_id": index + 1,
                "weight": 2.0 if index == 0 else 1.0,
                "attacking_points": 6.0 if index == 0 else (2.0 if index % 2 else 0.0),
                "history_count": 12,
                "history_attacking_mean": 0.0
                if probability == 0.0
                else probability * positive_mean,
                "occurrence_probability": probability,
                "positive_mean": positive_mean,
                "history_positive_returns": history_positive,
                "severity_reference_positive_returns": reference_positive,
            }
        )
    return pd.DataFrame(rows)


def test_decomposition_is_exact_with_captain_and_zero_probability_fallback() -> None:
    parts = decompose_player_rows(_players())

    captain = parts.loc[parts["weight"].eq(2.0)].iloc[0]
    assert captain["occurrence_surprise"] == pytest.approx(8.0)
    assert captain["severity_surprise"] == pytest.approx(4.0)
    assert captain["attacking_surprise"] == pytest.approx(12.0)
    assert parts["identity_error"].abs().max() <= 1e-9
    assert parts["carrier_supported"].all()


def test_one_to_four_positive_returns_make_the_fold_ineligible_without_changing_math() -> None:
    parts = decompose_player_rows(_players(low_positive_support=True))
    reading = build_fold_reading(
        parts,
        control_realized_score=30.0,
        lower_quantile_score=35.0,
        control_below_q10=True,
    )

    assert reading["eligible"] is False
    assert reading["supported_starters"] == 10
    assert reading["occurrence_surprise"] != reading["occurrence_surprise"]


def test_zero_positive_history_without_a_fallback_is_unsupported() -> None:
    parts = decompose_player_rows(_players(missing_zero_fallback=True))
    assert parts.loc[parts["player_id"].eq(1), "carrier_supported"].item() is False


def test_positive_history_cannot_switch_to_a_different_severity_pool() -> None:
    rows = _players()
    rows.loc[1, "severity_reference_positive_returns"] = 8
    with pytest.raises(AttackingHurdleError, match="different severity reference"):
        decompose_player_rows(rows)


def test_probability_and_positive_mean_must_reproduce_phase2h_mean() -> None:
    rows = _players()
    rows.loc[1, "history_attacking_mean"] = 2.0
    with pytest.raises(AttackingHurdleError, match="do not reproduce"):
        decompose_player_rows(rows)


def test_occurrence_probability_must_match_empirical_history_counts() -> None:
    rows = _players()
    rows.loc[1, "occurrence_probability"] = 0.25
    rows.loc[1, "history_attacking_mean"] = 0.5
    with pytest.raises(AttackingHurdleError, match="positive returns divided"):
        decompose_player_rows(rows)


def test_fold_reading_uses_fixed_q10_and_strict_event() -> None:
    reading = build_fold_reading(
        decompose_player_rows(_players()),
        control_realized_score=30.0,
        lower_quantile_score=30.0,
        control_below_q10=False,
    )

    assert reading["eligible"] is True
    assert reading["control_below_q10"] is False
    assert reading["identity_error"] == pytest.approx(0.0)
    assert reading["occurrence_reduction"] in {-1, 0, 1}
    assert reading["severity_reduction"] in {-1, 0, 1}


@pytest.mark.parametrize(
    ("control_score", "part", "control_tail", "expected_reduction"),
    [(25.0, -10.0, True, 1), (35.0, 10.0, False, -1)],
)
def test_counterfactual_reduction_direction(
    control_score: float,
    part: float,
    control_tail: bool,
    expected_reduction: int,
) -> None:
    players = pd.DataFrame(
        {
            "fold_id": ["2023-24-gw10"] * 11,
            "season": ["2023-24"] * 11,
            "player_id": list(range(1, 12)),
            "supported": [1] * 11,
            "occurrence": [part, *([0.0] * 10)],
            "severity": [0.0] * 11,
            "attacking_surprise": [part, *([0.0] * 10)],
            "target_positive": [1, *([0] * 10)],
        }
    )
    reading = build_fold_reading(players, control_score, 30.0, control_tail)
    assert reading["occurrence_reduction"] == expected_reduction


def _folds(*, season: str, eligible: int = 30, reverse: bool = False) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for index in range(eligible):
        tail = index < 10
        sign = 1.0 if reverse else -1.0
        occurrence = sign * 4.0 if tail else 0.0
        severity = sign * 3.0 if tail else 0.0
        rows.append(
            {
                "fold_id": f"{season}-gw{index + 1}",
                "season": season,
                "eligible": True,
                "identity_error": 0.0,
                "positive_target_returns": 5,
                "zero_target_returns": 6,
                "control_below_q10": tail,
                "occurrence_surprise": occurrence,
                "severity_surprise": severity,
                "occurrence_reduction": 1 if tail else 0,
                "severity_reduction": 1 if tail else 0,
            }
        )
    return pd.DataFrame(rows)


def test_summary_bootstraps_folds_and_records_support() -> None:
    summary = summarise(_folds(season="2023-24"))

    support = summary["support"]
    assert support == {
        "folds": 30,
        "eligible_folds": 30,
        "tail_folds": 10,
        "non_tail_folds": 20,
        "positive_target_returns": 150,
        "zero_target_returns": 180,
    }
    occurrence = summary["parts"]["occurrence"]
    assert occurrence["tail_minus_other_surprise"]["bootstrap_high"] < 0.0
    assert occurrence["q10_failure_reduction"]["bootstrap_low"] > 0.0
    assert summary == summarise(_folds(season="2023-24"))


def test_summary_rejects_truthy_eligibility_and_non_event_reductions() -> None:
    truthy = _folds(season="2023-24")
    truthy["eligible"] = 1
    with pytest.raises(AttackingHurdleError, match="eligible must contain booleans"):
        summarise(truthy)

    reduction = _folds(season="2023-24")
    reduction["occurrence_reduction"] = reduction["occurrence_reduction"].astype("float64")
    reduction.loc[0, "occurrence_reduction"] = 0.5
    with pytest.raises(AttackingHurdleError, match="minus one, zero or one"):
        summarise(reduction)


def _classification_summary(
    *, occurrence: bool, severity: bool, supported: bool = True, reverse: bool = False
) -> dict[str, object]:
    def part(passes: bool) -> dict[str, object]:
        direction = 1.0 if reverse else -1.0
        return {
            "tail_minus_other_surprise": {
                "mean": direction if passes else 0.0,
                "bootstrap_low": -2.0 if passes else -1.0,
                "bootstrap_high": -0.1 if passes else 1.0,
            },
            "q10_failure_reduction": {
                "mean": -1.0 if reverse and passes else (0.2 if passes else 0.0),
                "bootstrap_low": 0.1 if passes else -0.1,
                "bootstrap_high": 0.3,
            },
        }

    folds = 30 if supported else 29
    return {
        "parts": {"occurrence": part(occurrence), "severity": part(severity)},
        "support": {
            "folds": folds,
            "eligible_folds": folds,
            "tail_folds": 10,
            "non_tail_folds": folds - 10,
            "positive_target_returns": 100,
            "zero_target_returns": 100,
        },
        "maximum_absolute_identity_error": 0.0,
    }


@pytest.mark.parametrize(
    ("occurrence", "severity", "expected"),
    [
        (True, False, OCCURRENCE_CARRIER),
        (False, True, POSITIVE_SEVERITY_CARRIER),
        (True, True, SHARED_HURDLE_FAILURE),
        (False, False, NOT_LOCALIZED),
    ],
)
def test_frozen_classification_tree(occurrence: bool, severity: bool, expected: str) -> None:
    validation = _classification_summary(occurrence=occurrence, severity=severity)
    sensitivity = _classification_summary(occurrence=occurrence, severity=severity)
    assert classify(validation, sensitivity) == expected


def test_classification_requires_support_and_both_groups_in_both_seasons() -> None:
    valid = _classification_summary(occurrence=True, severity=False)
    assert (
        classify(_classification_summary(occurrence=True, severity=False, supported=False), valid)
        == INCONCLUSIVE
    )

    missing_sensitivity_group = deepcopy(valid)
    missing_sensitivity_group["support"]["non_tail_folds"] = 0
    assert classify(valid, missing_sensitivity_group) == INCONCLUSIVE


def test_sensitivity_direction_can_veto_a_validation_carrier() -> None:
    validation = _classification_summary(occurrence=True, severity=False)
    sensitivity = _classification_summary(occurrence=True, severity=False, reverse=True)
    assert classify(validation, sensitivity) == NOT_LOCALIZED


def test_non_finite_gate_reading_is_inconclusive() -> None:
    validation = _classification_summary(occurrence=True, severity=False)
    sensitivity = _classification_summary(occurrence=True, severity=False)
    sensitivity["parts"]["occurrence"]["tail_minus_other_surprise"]["mean"] = float("nan")
    assert classify(validation, sensitivity) == INCONCLUSIVE


def _runner_inputs(
    *, first_target_attacking: float = 0.0
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    list[str],
]:
    positions = ["GK", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID", "FWD", "FWD", "FWD"]
    history_ids = [f"2022-23-gw{gameweek:02d}" for gameweek in range(1, 11)]
    history = pd.concat(
        [
            pd.DataFrame(
                {
                    "fold_id": [fold_id] * 11,
                    "season": ["2022-23"] * 11,
                    "player_id": list(range(1, 12)),
                    "position": positions,
                    "minutes": [90] * 11,
                    "fixture_count": [1] * 11,
                    "attacking": [
                        0.0 if player_id == 1 else float(gameweek % 2) for player_id in range(1, 12)
                    ],
                }
            )
            for gameweek, fold_id in enumerate(history_ids, start=1)
        ],
        ignore_index=True,
    )
    attacking = [first_target_attacking, *([0.0] * 10)]
    target = pd.DataFrame(
        {
            "fold_id": ["2023-24-gw10"] * 11,
            "season": ["2023-24"] * 11,
            "player_id": list(range(1, 12)),
            "position": positions,
            "minutes": [90] * 11,
            "fixture_count": [1] * 11,
            "attacking": attacking,
        }
    )
    phase2i = target.rename(columns={"attacking": "attacking_points"}).copy()
    phase2i = phase2i.drop(columns="position")
    phase2i["is_captain"] = [1, *([0] * 10)]
    return phase2i, target, history, history_ids


def test_runner_uses_one_exact_pool_and_target_independent_zero_fallback() -> None:
    from scripts.run_attacking_hurdle import _hurdle_player_rows

    source_by_target: list[str] = []
    for target_attacking in (0.0, 6.0):
        phase2i, target, history, history_ids = _runner_inputs(
            first_target_attacking=target_attacking
        )
        # Player 1's Phase 2H mean is zero; all other starters have a 0.5 mean.
        attacking_surprise = 2.0 * target_attacking - 5.0
        rows, diagnostics = _hurdle_player_rows(
            phase2i,
            target,
            history,
            history_ids,
            {"component_surprises": {"attacking": attacking_surprise}},
        )

        player = rows.loc[rows["player_id"].eq(1)].iloc[0]
        source_by_target.append(str(player["severity_source"]))
        assert player["history_positive_returns"] == 0
        assert player["severity_reference_positive_returns"] >= 5
        assert player["carrier_supported"]
        assert diagnostics["eligible"] is True
        assert rows["identity_error"].abs().max() <= 1e-9

    assert source_by_target == ["pooled_zero_positive_fallback"] * 2

    phase2i, target, history, history_ids = _runner_inputs()
    with pytest.raises(ValueError, match="target or future"):
        _hurdle_player_rows(
            phase2i,
            target,
            history,
            [*history_ids, "2023-24-gw10"],
            {"component_surprises": {"attacking": -5.0}},
        )


def test_runner_refuses_an_unregistered_phase2i_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.run_attacking_hurdle as runner

    monkeypatch.setattr(runner, "PHASE2I_ARTIFACT", Path("pyproject.toml"))
    with pytest.raises(ValueError, match="pre-registered source"):
        runner._phase2i_document()


def test_runner_refuses_a_substituted_residual_before_loading_the_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.run_attacking_hurdle as runner

    expected = "1" * 64
    monkeypatch.setattr(
        runner, "_phase2h_document", lambda: {"residual_source": {"table_sha256": expected}}
    )
    monkeypatch.setattr(runner, "_phase2i_document", lambda: {})
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda self, *, encoding: '{"table_sha256":"' + ("2" * 64) + '"}',
    )
    table_loaded = False

    def forbidden_loader(*args: object, **kwargs: object) -> object:
        nonlocal table_loaded
        table_loaded = True
        raise AssertionError("the table loader must not run")

    monkeypatch.setattr(runner, "load_residual_source_manifest", forbidden_loader)
    arguments = Namespace(
        residual_table=Path("not-read.csv"),
        residual_manifest=Path("manifest.json"),
        archive_root=Path("not-read-archive"),
    )
    with pytest.raises(ValueError, match="does not name the Phase 2H residual export"):
        runner._measure(arguments, runner.SquadShadowConfig())
    assert table_loaded is False


def test_runner_parses_only_residual_bytes_matching_the_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.run_attacking_hurdle as runner

    payload = b"fold_id,player_id\n2023-24-gw01,1\n"
    monkeypatch.setattr(Path, "read_bytes", lambda self: payload)
    with pytest.raises(ValueError, match="changed after validation"):
        runner._read_pinned_residual_table(Path("residuals.csv"), "0" * 64)
