"""The gate must refuse gains bought by error or decision regressions."""

from dataclasses import replace

import pytest

from squadopt.evaluation.prediction_gate import PredictionGatePolicy, evaluate_prediction_gate

SEASONS = ("2023-24", "2024-25")
POSITIONS = ("GK", "DEF")


def read_gate(**changes):
    evidence = {
        "seasons": SEASONS,
        "positions": POSITIONS,
        "ranks": {(s, p): (0.2, 0.23) for s in (*SEASONS, "pooled") for p in POSITIONS},
        "errors": {s: (1.0, 1.04) for s in (*SEASONS, "pooled")},
        "decision_mean": 0.8,
        "decision_interval": (0.1, 1.5),
        "decision_by_season": {s: 0.8 for s in SEASONS},
    }
    evidence.update(changes)
    return evaluate_prediction_gate(**evidence)


def test_rank_gain_can_pass_with_a_small_error_increase():
    assert read_gate().verdict == "passes"


def test_exact_inclusive_rank_boundary_is_not_lost_to_binary_roundoff():
    ranks = {(s, p): (0.1, 0.11) for s in (*SEASONS, "pooled") for p in POSITIONS}
    assert read_gate(ranks=ranks).ranking == "passes"
    below = {(s, p): (0.1, 0.10999999) for s in (*SEASONS, "pooled") for p in POSITIONS}
    assert read_gate(ranks=below).ranking == "fails"


def test_roundoff_allowance_never_turns_zero_error_or_zero_interval_into_a_pass():
    assert read_gate(errors={"pooled": (0.0, 1e-13)}).error == "fails"
    assert read_gate(decision_interval=(0.0, 1.0)).decision == "fails"


@pytest.mark.parametrize(
    "change,clause",
    [
        ({"errors": {"pooled": (1.0, 1.051)}}, "error"),
        (
            {"ranks": {(s, p): (0.2, 0.2) for s in (*SEASONS, "pooled") for p in POSITIONS}},
            "ranking",
        ),
        ({"decision_mean": 0.49}, "decision"),
        ({"decision_interval": (0.0, 1.5)}, "decision"),
        ({"decision_by_season": {s: -0.01 for s in SEASONS}}, "decision"),
    ],
)
def test_no_other_gain_can_compensate_for_a_failed_clause(change, clause):
    result = read_gate(**change)
    assert getattr(result, clause) == "fails"
    assert result.verdict == "fails"


def test_macro_rank_gain_cannot_hide_one_regressing_position_season():
    ranks = {(s, p): (0.2, 0.4) for s in (*SEASONS, "pooled") for p in POSITIONS}
    ranks[SEASONS[0], "GK"] = (0.2, 0.18)
    assert read_gate(ranks=ranks).ranking == "fails"


@pytest.mark.parametrize(
    "change",
    [
        {"ranks": {}},
        {"errors": {}},
        {"decision_mean": None},
        {"decision_interval": None},
        {"decision_by_season": {}},
    ],
)
def test_missing_evidence_never_passes(change):
    assert read_gate(**change).verdict == "insufficient"


def test_zero_control_error_has_no_relative_allowance():
    assert read_gate(errors={"pooled": (0.0, 0.001)}).error == "fails"


def test_one_season_cannot_establish_the_gate():
    result = read_gate(
        seasons=SEASONS[:1],
        ranks={(s, p): (0.2, 0.3) for s in (*SEASONS[:1], "pooled") for p in POSITIONS},
        errors={s: (1.0, 1.0) for s in (*SEASONS[:1], "pooled")},
        decision_by_season={SEASONS[0]: 0.8},
    )
    assert result.verdict == "insufficient"


@pytest.mark.parametrize(
    "change",
    [
        {"ranks": {("pooled", "GK"): (0.2, float("nan"))}},
        {"errors": {"pooled": (1.0, float("inf"))}},
        {"errors": {"pooled": (-1.0, 1.0)}},
        {"decision_mean": float("nan")},
        {"decision_interval": (2.0, 1.0)},
        {"decision_by_season": {"2025-26": 5.0}},
        {"ranks": {("unknown", "GK"): (0.0, 0.3)}},
        {"positions": ("GK", "GK")},
    ],
)
def test_malformed_or_undeclared_evidence_refuses(change):
    with pytest.raises(ValueError):
        read_gate(**change)


def test_policy_identity_changes_when_any_threshold_moves():
    policy = PredictionGatePolicy()
    assert policy.fingerprint == PredictionGatePolicy().fingerprint
    for name, value in [
        ("minimum_rank_gain", 0.02),
        ("maximum_cell_rank_loss", 0.02),
        ("maximum_relative_mae_increase", 0.1),
        ("minimum_decision_gain", 1.0),
        ("maximum_losing_seasons", 0),
        ("minimum_seasons", 3),
    ]:
        assert replace(policy, **{name: value}).fingerprint != policy.fingerprint


@pytest.mark.parametrize(
    "change",
    [
        {"minimum_rank_gain": float("nan")},
        {"minimum_decision_gain": -1.0},
        {"minimum_seasons": 1},
        {"maximum_losing_seasons": 2},
    ],
)
def test_invalid_policy_refuses(change):
    with pytest.raises(ValueError):
        PredictionGatePolicy(**change)
