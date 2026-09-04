"""Removing the captain's second copy, and nothing else.

The ablation is only meaningful if it takes out exactly one term: the captain stays a
starter with his ordinary points, the decision is untouched, and what is subtracted from
the scenario side and the realized side is the same extra copy the scoring policy adds.
These tests pin that, the three classification branches, and the refusals.
"""

from collections.abc import Mapping

import numpy as np
import pandas as pd
import pytest

from squadopt.experiments.captain_attribution import (
    ABLATED,
    ABLATED_UNSHIFTED,
    CAPTAIN_CONCENTRATED,
    FULL,
    INCONCLUSIVE,
    SHARED_TAIL_FAILURE,
    CaptainReading,
    captain_component,
    classify,
    read_fold,
    refuse_unexpected_folds,
    summarise,
)
from squadopt.experiments.shadow_squad_calibration import (
    SquadFold,
    SquadShadowConfig,
    SquadShadowError,
)
from squadopt.experiments.tail_diagnostic import FROZEN_SHIFT_POINTS
from squadopt.scenarios.models import ScenarioValidationError

_PLAYERS = (1, 2, 3)
_CAPTAIN = 2


def _projections() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "player_id": list(_PLAYERS),
            "name": ["A", "B", "C"],
            "team_id": [10, 11, 12],
            "position": ["MID", "FWD", "DEF"],
            "price_tenths": [50, 60, 45],
            "expected_points": [4.0, 6.0, 3.0],
        }
    )


def _fold(realized: dict[int, float] | None = None) -> SquadFold:
    points = {1: 3.0, 2: 1.0, 3: 5.0} if realized is None else realized
    return SquadFold(
        fold_id="2024-25-gw10",
        season="2024-25",
        gameweek=10,
        projections=_projections(),
        realized_points=pd.DataFrame(
            {"player_id": list(points), "total_points": list(points.values())}
        ),
        prior_fold_ids=tuple(f"2023-24-gw{gw:02d}" for gw in range(2, 12)),
    )


class _Captain(dict[str, object]):
    """A captain row, read the way the canonical result exposes one."""


class _Decision:
    has_solution = True

    def __init__(self, captain: object | None = _Captain({"player_id": _CAPTAIN})) -> None:
        self.captain = captain
        self.starting_xi = pd.DataFrame({"player_id": list(_PLAYERS)})
        self.selected_squad = self.starting_xi


class _Scenarios:
    def __init__(self, matrix: dict[int, list[float]]) -> None:
        self.scenario_points = pd.DataFrame(matrix)


class _Metrics:
    def __init__(self, scores: np.ndarray, quantile: float) -> None:
        self.mean_score = float(scores.mean())
        self.lower_quantile_score = float(np.quantile(scores, quantile, method="linear"))


class _Evaluated:
    def __init__(self, scores: list[float], quantile: float) -> None:
        self.scenario_scores = tuple(scores)
        self.metrics = _Metrics(np.asarray(scores, dtype="float64"), quantile)


def _canonical_evaluate(decision: object, scenarios: object, config: object) -> _Evaluated:
    """What ``evaluate_fixed_decision`` does, including the transform it is given.

    A fake that skipped the dispersion and the shift would make the study's "unshifted"
    arm the opposite of production's, so this reproduces the evaluator's own arithmetic
    from the decision it is handed rather than from a captured constant.
    """

    if decision.captain is None:  # type: ignore[attr-defined]
        # What the canonical evaluator does, and it does it before this module's own
        # guard is ever reached.
        raise ScenarioValidationError("A feasible fixed decision must contain a captain.")
    matrix = scenarios.scenario_points  # type: ignore[attr-defined]
    starters = list(decision.starting_xi["player_id"])  # type: ignore[attr-defined]
    captain_id = decision.captain["player_id"]  # type: ignore[index, attr-defined]
    raw = matrix[starters].to_numpy(dtype="float64").sum(axis=1) + matrix[captain_id].to_numpy(
        dtype="float64"
    )
    raw_mean = float(raw.mean())
    scores = (
        raw_mean
        + config.dispersion_scale * (raw - raw_mean)  # type: ignore[attr-defined]
        + config.location_shift_points  # type: ignore[attr-defined]
    )
    return _Evaluated(list(scores), config.lower_quantile)  # type: ignore[attr-defined]


def _canonical_realized(decision: object, frame: pd.DataFrame) -> float:
    """What ``score_realized_squad_points`` does: the XI, plus the captain again."""

    points = dict(zip(frame["player_id"], frame["total_points"], strict=True))
    starters = list(decision.starting_xi["player_id"])  # type: ignore[attr-defined]
    captain_id = decision.captain["player_id"]  # type: ignore[index, attr-defined]
    return float(sum(points[player] for player in starters) + points[captain_id])


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    captain_scenario: list[float],
    other_starters: list[float],
    decision: _Decision | None = None,
    realized: dict[int, float] | None = None,
) -> dict[str, object]:
    """Wire the module to a hand-built scenario matrix and a fixed decision."""

    from squadopt.experiments import captain_attribution as module

    chosen = _Decision() if decision is None else decision
    seen: dict[str, object] = {"decision": chosen}
    matrix = {
        1: [value / 2 for value in other_starters],
        _CAPTAIN: list(captain_scenario),
        3: [value / 2 for value in other_starters],
    }
    scenarios = _Scenarios(matrix)
    seen["scenarios"] = scenarios
    seen["matrix"] = matrix

    monkeypatch.setattr(module, "optimize_squad_once", lambda fold, config: chosen)
    monkeypatch.setattr(module, "prepare_optimizer_projection", lambda *a, **k: object())
    monkeypatch.setattr(module, "generate_scenarios", lambda *a, **k: scenarios)
    monkeypatch.setattr(module, "evaluate_fixed_decision", _canonical_evaluate)
    monkeypatch.setattr(module, "score_realized_squad_points", _canonical_realized)
    seen["realized"] = {1: 3.0, 2: 1.0, 3: 5.0} if realized is None else realized
    return seen


def _expected(seen: Mapping[str, object]) -> dict[str, np.ndarray | float]:
    """The two distributions and the two outcomes, computed independently of the module."""

    matrix = seen["matrix"]
    assert isinstance(matrix, dict)
    realized = seen["realized"]
    assert isinstance(realized, dict)
    captain = np.asarray(matrix[_CAPTAIN], dtype="float64")
    starters = sum(np.asarray(matrix[player], dtype="float64") for player in _PLAYERS)
    raw = starters + captain
    full = raw - raw.mean() + raw.mean() + FROZEN_SHIFT_POINTS
    return {
        "full_scores": full,
        "ablated_scores": starters + FROZEN_SHIFT_POINTS,
        "full_realized": float(sum(realized[player] for player in _PLAYERS) + realized[_CAPTAIN]),
        "ablated_realized": float(sum(realized[player] for player in _PLAYERS)),
    }


def _read(monkeypatch: pytest.MonkeyPatch, **kwargs: object) -> tuple[CaptainReading, dict]:
    seen = _install(monkeypatch, **kwargs)  # type: ignore[arg-type]
    realized = seen["realized"]
    assert isinstance(realized, dict)
    reading = read_fold(
        _fold(realized),
        pd.DataFrame({"fold_id": [], "residual": []}),
        (),
        None,
        SquadShadowConfig(),
    )
    return reading, seen


# --- the decomposition ----------------------------------------------------------------


def test_the_full_score_decomposes_into_the_rest_plus_the_extra_captain_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`full = non_captain + extra_captain_bonus`, on both sides, per scenario."""

    captain_scenario = [4.0, 6.0, 8.0, 10.0]
    reading, seen = _read(
        monkeypatch, captain_scenario=captain_scenario, other_starters=[10.0, 12.0, 14.0, 16.0]
    )
    assert reading.decomposition_holds
    expected = _expected(seen)

    # The ablated distribution is the starting XI's own columns, with the captain still
    # in it once: strictly more than the squad without him, and exactly one copy less
    # than the full score.
    ablated_scores = expected["ablated_scores"]
    captain = np.asarray(captain_scenario, dtype="float64")
    assert isinstance(ablated_scores, np.ndarray)
    assert np.allclose(np.asarray(expected["full_scores"]) - captain, ablated_scores)

    # And the module reports readings taken from exactly those two distributions.
    assert reading.pit[ABLATED] == pytest.approx(
        float((ablated_scores <= expected["ablated_realized"]).mean())
    )
    assert reading.below_lower_quantile[ABLATED] == bool(
        expected["ablated_realized"] < float(np.quantile(ablated_scores, 0.10, method="linear"))
    )
    assert reading.ablated_scenario_mean_score == pytest.approx(float(ablated_scores.mean()))
    assert reading.ablated_realized_score == pytest.approx(expected["ablated_realized"])
    assert reading.full_realized_score == pytest.approx(expected["full_realized"])
    assert reading.captain_realized_bonus == pytest.approx(1.0)
    assert reading.captain_scenario_mean_bonus == pytest.approx(float(captain.mean()))


def test_only_the_multiplier_copy_is_removed_at_a_doubling_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One copy out of two, which is what STARTING_XI_CAPTAIN_V1 adds."""

    reading, seen = _read(
        monkeypatch,
        captain_scenario=[2.0, 4.0, 6.0, 40.0],
        other_starters=[20.0, 20.0, 20.0, 20.0],
        realized={1: 3.0, 2: 1.0, 3: 5.0},
    )
    expected = _expected(seen)
    ablated = expected["ablated_scores"]
    assert isinstance(ablated, np.ndarray)

    # Removing two copies instead of one would give a different distribution and a
    # different outcome; both are pinned, so that mistake cannot pass.
    captain = np.asarray([2.0, 4.0, 6.0, 40.0], dtype="float64")
    twice_removed = np.asarray(expected["full_scores"]) - 2 * captain
    assert not np.allclose(ablated, twice_removed)
    assert reading.ablated_realized_score == pytest.approx(9.0)
    assert reading.pit[ABLATED] == pytest.approx(float((ablated <= 9.0).mean()))


def test_the_scoring_contract_supports_one_multiplier_and_the_study_invents_no_other() -> None:
    """A triple-captain policy does not exist here, so nothing pretends it does."""

    from squadopt.evaluation.scoring import ScoringPolicy

    assert [policy.name for policy in ScoringPolicy] == [
        "STARTING_XI_CAPTAIN_V1",
        "OFFICIAL_AUTOSUB_CAPTAIN_V2",
    ]


def test_the_decision_is_untouched_by_the_ablation(monkeypatch: pytest.MonkeyPatch) -> None:
    """No reoptimization: the same squad, XI and captain are read twice."""

    decision = _Decision()
    before = decision.starting_xi.copy(deep=True)
    reading, _ = _read(
        monkeypatch,
        captain_scenario=[4.0, 8.0, 2.0, 6.0],
        other_starters=[10.0, 14.0, 8.0, 12.0],
        decision=decision,
    )
    # The fakes read the decision to score, so an ablation that mutated it would show
    # here rather than being asserted against something nothing touched.
    assert reading.decomposition_holds
    assert decision.captain["player_id"] == _CAPTAIN
    pd.testing.assert_frame_equal(decision.starting_xi, before)


def test_the_full_arm_is_the_canonical_evaluation(monkeypatch: pytest.MonkeyPatch) -> None:
    """The derived numbers are checked against the evaluator's own metrics, not trusted."""

    reading, seen = _read(
        monkeypatch, captain_scenario=[1.0, 9.0, 3.0, 7.0], other_starters=[10.0, 30.0, 14.0, 26.0]
    )
    expected = _expected(seen)
    full = expected["full_scores"]
    assert isinstance(full, np.ndarray)
    assert reading.full_scenario_mean_score == pytest.approx(float(full.mean()))
    assert reading.pit[FULL] == pytest.approx(float((full <= expected["full_realized"]).mean()))
    assert reading.below_lower_quantile[FULL] == bool(
        expected["full_realized"] < float(np.quantile(full, 0.10, method="linear"))
    )
    assert reading.decomposition_holds


def test_the_unshifted_companion_moves_only_the_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Removing the frozen shift is a constant, so it can only move the comparison point."""

    reading, seen = _read(
        monkeypatch,
        captain_scenario=[4.0, 6.0, 8.0, 40.0],
        other_starters=[10.0, 14.0, 18.0, 22.0],
    )
    values = _expected(seen)
    full = values["full_scores"]
    assert isinstance(full, np.ndarray)
    # The shift is negative, so removing it moves the distribution up and the outcome
    # can only sit lower within it. The opposite sign would move it the other way.
    unshifted = full - FROZEN_SHIFT_POINTS
    assert reading.pit["full_unshifted"] == pytest.approx(
        float((unshifted <= values["full_realized"]).mean())
    )
    assert reading.pit["full_unshifted"] <= reading.pit[FULL]
    assert reading.pit["full_unshifted"] != pytest.approx(
        float(((full + FROZEN_SHIFT_POINTS) <= values["full_realized"]).mean())
    )


def test_the_tail_comparison_is_strict_and_the_quantile_is_interpolated() -> None:
    """Both choices decide every S2 event, so both are pinned to the evaluator's own.

    With four scenarios the tenth percentile falls between the first two, so linear
    interpolation and the "lower" method disagree by three points — enough for an
    outcome to be inside one tail and outside the other. And an outcome sitting exactly
    on the quantile is not below it: the evaluator's comparison is strict.
    """

    from squadopt.experiments.captain_attribution import _below, _pit

    scores = np.asarray([10.0, 20.0, 30.0, 40.0], dtype="float64")
    assert float(np.quantile(scores, 0.10, method="linear")) == pytest.approx(13.0)

    assert _below(scores, 11.0, 0.10) is True
    assert _below(scores, 13.0, 0.10) is False
    assert _below(scores, 14.0, 0.10) is False

    # The PIT counts a scenario equal to the outcome, as the evaluator's own reading does.
    assert _pit(scores, 20.0) == pytest.approx(0.5)
    assert _pit(scores, 19.999) == pytest.approx(0.25)


# --- refusals -------------------------------------------------------------------------


def test_a_decision_without_a_captain_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The canonical evaluator refuses first; this module's own guard is behind it."""

    with pytest.raises(ScenarioValidationError, match="must contain a captain"):
        _read(
            monkeypatch,
            captain_scenario=[4.0] * 4,
            other_starters=[10.0] * 4,
            decision=_Decision(captain=None),
        )


def test_a_fold_with_no_realized_points_for_its_captain_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing bonus is refused, never read as zero."""

    from squadopt.experiments import captain_attribution as module

    _install(monkeypatch, captain_scenario=[4.0] * 4, other_starters=[10.0] * 4)
    monkeypatch.setattr(module, "score_realized_squad_points", lambda d, frame: 10.0)
    fold = SquadFold(
        fold_id="2024-25-gw10",
        season="2024-25",
        gameweek=10,
        projections=_projections(),
        realized_points=pd.DataFrame({"player_id": [1, 3], "total_points": [3.0, 5.0]}),
        prior_fold_ids=tuple(f"2023-24-gw{gw:02d}" for gw in range(2, 12)),
    )
    with pytest.raises(SquadShadowError, match="no realized points for its captain"):
        read_fold(
            fold, pd.DataFrame({"fold_id": [], "residual": []}), (), None, SquadShadowConfig()
        )


def test_a_dispersion_other_than_the_pinned_one_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ablation is exact only where the evaluator is raw plus a constant."""

    class _Widened:
        dispersion_scale = 1.30

    with pytest.raises(SquadShadowError, match="defined only at the pre-registered dispersion"):
        read_fold(_fold(), pd.DataFrame(), (), None, _Widened())  # type: ignore[arg-type]


def _reading(fold_id: str, *, holds: bool = True, below: bool = False) -> CaptainReading:
    return CaptainReading(
        fold_id=fold_id,
        season="2024-25",
        pit=dict.fromkeys(("full", ABLATED, "full_unshifted", ABLATED_UNSHIFTED), 0.5),
        below_lower_quantile=dict.fromkeys(
            ("full", ABLATED, "full_unshifted", ABLATED_UNSHIFTED), below
        ),
        captain_scenario_mean_bonus=6.0,
        captain_realized_bonus=1.0,
        full_scenario_mean_score=60.0,
        full_realized_score=50.0,
        ablated_scenario_mean_score=54.0,
        ablated_realized_score=49.0,
        decomposition_holds=holds,
    )


def test_a_repeated_or_undecomposable_fold_is_refused() -> None:
    with pytest.raises(SquadShadowError, match="repeats a fold"):
        refuse_unexpected_folds((_reading("a"), _reading("a")))
    with pytest.raises(SquadShadowError, match="does not hold on folds"):
        refuse_unexpected_folds((_reading("a"), _reading("b", holds=False)))


def test_the_locked_season_is_refused_before_any_loader_sees_it() -> None:
    from squadopt.experiments.tail_diagnostic import STUDY_SEASONS, refuse_the_holdout

    assert "2025-26" not in STUDY_SEASONS
    refuse_the_holdout(STUDY_SEASONS)
    with pytest.raises(SquadShadowError, match="locked confirmation holdout"):
        refuse_the_holdout(("2024-25", "2025-26"))


# --- the classification ---------------------------------------------------------------


def _arms(*, full_rate: float, ablated_rate: float, ablated_unshifted_rate: float) -> dict:
    def gates(rate: float) -> dict[str, float | bool]:
        return {
            "fold_count": 37.0,
            "mean_probability_integral_transform": 0.49,
            "below_lower_quantile_folds": rate * 37.0,
            "below_lower_quantile_rate": rate,
            "s1_within_band": True,
            "s2_within_band": 0.04 <= rate <= 0.16,
            "s2_fails_above_band": rate > 0.16,
        }

    return {
        FULL: gates(full_rate),
        ABLATED: gates(ablated_rate),
        "full_unshifted": gates(full_rate),
        ABLATED_UNSHIFTED: gates(ablated_unshifted_rate),
    }


@pytest.mark.parametrize(
    ("name", "arms", "expected"),
    [
        (
            "the failure disappears with the extra copy, under both conventions",
            _arms(full_rate=0.2162, ablated_rate=0.081, ablated_unshifted_rate=0.108),
            CAPTAIN_CONCENTRATED,
        ),
        (
            "the failure survives the ablation",
            _arms(full_rate=0.2162, ablated_rate=0.243, ablated_unshifted_rate=0.216),
            SHARED_TAIL_FAILURE,
        ),
        (
            "the two location conventions disagree, so the study will not choose",
            _arms(full_rate=0.2162, ablated_rate=0.081, ablated_unshifted_rate=0.243),
            INCONCLUSIVE,
        ),
        (
            "there is no full-squad failure here to attribute",
            _arms(full_rate=0.108, ablated_rate=0.081, ablated_unshifted_rate=0.081),
            INCONCLUSIVE,
        ),
        (
            "the ablated arm is under the floor rather than inside the band",
            _arms(full_rate=0.2162, ablated_rate=0.0, ablated_unshifted_rate=0.0),
            INCONCLUSIVE,
        ),
    ],
)
def test_the_classification_uses_only_the_existing_band(
    name: str, arms: dict, expected: str
) -> None:
    classification, reasons = classify(arms)
    assert classification == expected, name
    assert (classification == INCONCLUSIVE) == bool(reasons), name


def test_the_summary_and_component_read_the_folds_they_are_given() -> None:
    readings = (_reading("a", below=True), _reading("b"), _reading("c"))
    arms = summarise(readings)
    assert arms[FULL]["fold_count"] == 3.0
    assert arms[FULL]["below_lower_quantile_folds"] == 1.0
    # 1/3 is above the S2 band's upper bound and the PIT of 0.5 is inside S1's, so the
    # two verdicts are read against their own bands rather than against each other's.
    assert arms[FULL]["below_lower_quantile_rate"] == pytest.approx(1 / 3)
    assert arms[FULL]["s2_within_band"] is False
    assert arms[FULL]["s2_fails_above_band"] is True
    assert arms[FULL]["s1_within_band"] is True

    # And at the band's own edges, inclusively.
    edge = summarise(tuple(_reading(str(index), below=index < 4) for index in range(25)))
    assert edge[FULL]["below_lower_quantile_rate"] == pytest.approx(0.16)
    assert edge[FULL]["s2_within_band"] is True
    assert edge[FULL]["s2_fails_above_band"] is False

    component = captain_component(readings)
    assert component["fold_count"] == 3
    assert component["negative_bonus_error_folds"] == 3
    assert component["on_full_score_tail_failures"]["fold_count"] == 1.0  # type: ignore[index]
    assert component["elsewhere"]["fold_count"] == 2.0  # type: ignore[index]
    assert component["mean_bonus_error"] == pytest.approx(-5.0)


def test_the_reading_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    first, _ = _read(monkeypatch, captain_scenario=[4.0, 6.0, 8.0], other_starters=[10.0] * 3)
    second, _ = _read(monkeypatch, captain_scenario=[4.0, 6.0, 8.0], other_starters=[10.0] * 3)
    assert first == second
