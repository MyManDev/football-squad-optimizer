"""The squad tail diagnostic: a fair comparison, and a classification it cannot inflate.

The study varies one already-existing evaluation parameter and nothing else, so almost
everything worth testing is about what it holds still: the same decision and the same
scenario draws behind every arm, a control that has to reproduce the recorded result, a
classification that only validation can decide, and a locked season that never reaches
a loader.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from squadopt.application.strategies.catalog import PUBLISHABLE_FIELDS
from squadopt.experiments.shadow_report import ShadowReportError, write_document_once
from squadopt.experiments.shadow_squad_calibration import SquadShadowConfig, SquadShadowError
from squadopt.experiments.tail_diagnostic import (
    CONTROL_SCALE,
    INCONCLUSIVE,
    RECORDED_BELOW_QUANTILE_RATE,
    RECORDED_MEAN_PIT,
    SCALE_LEVELS,
    SCALE_NOT_SUFFICIENT,
    SCALE_SUFFICIENT,
    SENSITIVITY_SEASON,
    STUDY_SEASONS,
    FoldFacts,
    captain_description,
    classify,
    common_shock_description,
    control_replay,
    eligible_development_folds,
    refuse_the_holdout,
    summarise_arm,
)


def _summary(*, pit: float, rate: float, folds: float = 37.0) -> dict[str, float | None]:
    return {
        "fold_count": folds,
        "mean_probability_integral_transform": pit,
        "below_lower_quantile_rate": rate,
    }


def _facts(**overrides: object) -> FoldFacts:
    values: dict[str, object] = {
        "fold_id": "2023-24-gw10",
        "season": "2023-24",
        "realized_score": 50.0,
        "scenario_mean_score": 55.0,
        "below_lower_quantile": False,
        "captain_realized_error": -3.0,
    }
    values.update(overrides)
    return FoldFacts(**values)  # type: ignore[arg-type]


# --- 1. the arms are declared, not chosen ---------------------------------------------


def test_the_scale_levels_are_the_pre_registered_four() -> None:
    """A level added after a result is a level chosen by the result."""

    assert SCALE_LEVELS == (1.00, 1.15, 1.30, 1.45)
    assert CONTROL_SCALE == 1.00
    assert CONTROL_SCALE in SCALE_LEVELS


def test_the_command_line_cannot_choose_an_arm(monkeypatch: pytest.MonkeyPatch) -> None:
    """The levels live in the pre-registration, so a shell may not name one."""

    from scripts.run_tail_diagnostic import _parse_arguments

    monkeypatch.setattr(
        "sys.argv",
        [
            "run_tail_diagnostic",
            "--residual-table",
            "t.csv",
            "--residual-manifest",
            "m.json",
            "--dispersion-scale",
            "1.30",
        ],
    )
    with pytest.raises(SystemExit):
        _parse_arguments()


# --- 2. the comparison is fair --------------------------------------------------------


def test_every_arm_reads_one_optimization_and_one_scenario_matrix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The arms cannot differ in their draws, because there is only one set of them.

    Common random numbers by construction rather than by assertion: the fold is
    optimized once, generated once, and only the evaluation is repeated.
    """

    from squadopt.experiments import tail_diagnostic as module

    calls = {"optimize": 0, "generate": 0}
    scenario_objects: list[object] = []
    scales: list[float] = []

    class _Decision:
        has_solution = True
        captain = None

    class _Scenarios:
        pass

    class _Metrics:
        mean_score = 55.0
        lower_quantile_score = 40.0

    class _Evaluated:
        scenario_scores = (40.0, 50.0, 60.0)
        metrics = _Metrics()

    def fake_optimize(players: object, config: object) -> object:
        calls["optimize"] += 1
        return _Decision()

    def fake_generate(*args: object, **kwargs: object) -> object:
        calls["generate"] += 1
        scenarios = _Scenarios()
        scenario_objects.append(scenarios)
        return scenarios

    def fake_evaluate(decision: object, scenarios: object, config: object) -> object:
        scenario_objects.append(scenarios)
        scales.append(float(config.dispersion_scale))  # type: ignore[attr-defined]
        return _Evaluated()

    monkeypatch.setattr(module, "optimize_squad", fake_optimize)
    monkeypatch.setattr(module, "generate_scenarios", fake_generate)
    monkeypatch.setattr(module, "evaluate_fixed_decision", fake_evaluate)
    monkeypatch.setattr(module, "prepare_optimizer_projection", lambda *a, **k: object())
    monkeypatch.setattr(module, "score_realized_squad_points", lambda *a, **k: 50.0)

    fold = _fold()
    readings, facts = module.read_fold_at_every_scale(
        fold, _residuals(), ("2021-22-gw02",), None, SquadShadowConfig()
    )

    assert calls == {"optimize": 1, "generate": 1}
    assert len(readings) == len(SCALE_LEVELS)
    assert scales == [float(scale) for scale in SCALE_LEVELS]
    # Every evaluation was handed the one matrix that was generated.
    assert len(set(map(id, scenario_objects))) == 1
    assert facts.fold_id == fold.fold_id


def _fold() -> object:
    from squadopt.experiments.shadow_squad_calibration import SquadFold

    projections = pd.DataFrame(
        {
            "player_id": [1, 2],
            "name": ["A", "B"],
            "team_id": [10, 11],
            "position": ["MID", "FWD"],
            "price_tenths": [50, 60],
            "expected_points": [4.0, 5.0],
        }
    )
    realized = pd.DataFrame({"player_id": [1, 2], "total_points": [3.0, 6.0]})
    return SquadFold(
        fold_id="2021-22-gw10",
        season="2021-22",
        gameweek=10,
        projections=projections,
        realized_points=realized,
        prior_fold_ids=tuple(f"2021-22-gw{gw:02d}" for gw in range(2, 10)),
    )


def _residuals() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fold_id": ["2021-22-gw02", "2021-22-gw02"],
            "season": ["2021-22", "2021-22"],
            "gameweek": [2, 2],
            "player_id": [1, 2],
            "team_id": [10, 11],
            "residual": [-1.0, 1.0],
        }
    )


def test_the_control_arm_must_reproduce_the_recorded_measurement() -> None:
    """A comparison whose baseline has drifted is not a comparison."""

    exact = control_replay(_summary(pit=RECORDED_MEAN_PIT, rate=RECORDED_BELOW_QUANTILE_RATE))
    assert exact["reproduced"] is True

    drifted = control_replay(
        _summary(pit=RECORDED_MEAN_PIT + 1e-6, rate=RECORDED_BELOW_QUANTILE_RATE)
    )
    assert drifted["reproduced"] is False
    assert drifted["recorded_mean_probability_integral_transform"] == RECORDED_MEAN_PIT


# --- 3. the split ---------------------------------------------------------------------


def test_the_locked_season_never_reaches_a_loader() -> None:
    assert "2025-26" not in STUDY_SEASONS
    refuse_the_holdout(STUDY_SEASONS)
    with pytest.raises(SquadShadowError, match="locked confirmation holdout"):
        refuse_the_holdout(("2023-24", "2025-26"))


def test_the_sensitivity_season_is_not_an_input_to_the_classification() -> None:
    """2024-25's result was seen before this study was written.

    ``classify`` takes the validation season and nothing else, so a sensitivity season
    that passes every arm cannot turn a validation that passes none into a candidate.
    """

    nothing_passes = {scale: _summary(pit=0.49, rate=0.30) for scale in (1.00, 1.15, 1.30, 1.45)}
    classification, eligible = classify(nothing_passes)
    assert classification == SCALE_NOT_SUFFICIENT
    assert eligible == ()
    assert SENSITIVITY_SEASON == "2024-25"


def test_the_development_burn_in_is_excluded_from_the_study_too() -> None:
    """The same rule the third squad-gate amendment applies to the shift fit."""

    from squadopt.experiments.shadow_squad_calibration import SquadFold

    def fold(priors: int, gameweek: int) -> SquadFold:
        return SquadFold(
            fold_id=f"2021-22-gw{gameweek:02d}",
            season="2021-22",
            gameweek=gameweek,
            projections=pd.DataFrame({"player_id": [1], "expected_points": [1.0]}),
            realized_points=pd.DataFrame({"player_id": [1], "total_points": [1.0]}),
            prior_fold_ids=tuple(f"2021-22-gw{index:02d}" for index in range(2, 2 + priors)),
        )

    folds = (fold(7, 20), fold(8, 21), fold(30, 22))
    kept = eligible_development_folds(folds, SquadShadowConfig())
    assert [entry.fold_id for entry in kept] == ["2021-22-gw21", "2021-22-gw22"]


# --- 4. the classification ------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "validation", "expected", "eligible"),
    [
        (
            "one arm inside both bands is a candidate",
            {
                1.00: _summary(pit=0.49, rate=0.2162),
                1.15: _summary(pit=0.49, rate=0.19),
                1.30: _summary(pit=0.50, rate=0.135),
                1.45: _summary(pit=0.51, rate=0.02),
            },
            SCALE_SUFFICIENT,
            (1.30,),
        ),
        (
            "no arm inside both bands is not sufficient",
            {
                1.00: _summary(pit=0.49, rate=0.2162),
                1.15: _summary(pit=0.49, rate=0.19),
                1.30: _summary(pit=0.50, rate=0.17),
                1.45: _summary(pit=0.62, rate=0.10),
            },
            SCALE_NOT_SUFFICIENT,
            (),
        ),
        (
            "several qualifying arms are a set, and this study picks no winner",
            {
                1.00: _summary(pit=0.49, rate=0.2162),
                1.15: _summary(pit=0.49, rate=0.16),
                1.30: _summary(pit=0.50, rate=0.135),
                1.45: _summary(pit=0.51, rate=0.10),
            },
            SCALE_SUFFICIENT,
            (1.15, 1.30, 1.45),
        ),
        (
            "a validation season below the fold floor decides nothing",
            {scale: _summary(pit=0.50, rate=0.10, folds=12.0) for scale in SCALE_LEVELS},
            INCONCLUSIVE,
            (),
        ),
    ],
)
def test_the_classification_is_the_eligible_set_and_never_a_winner(
    name: str,
    validation: dict[float, dict[str, float | None]],
    expected: str,
    eligible: tuple[float, ...],
) -> None:
    """Three words, decided on validation alone, with no arm promoted by default."""

    classification, measured = classify(validation)
    assert classification == expected, name
    assert measured == eligible, name


# --- 5. missing is never zero ---------------------------------------------------------


def test_a_fold_without_a_captain_is_counted_as_missing_not_averaged_as_zero() -> None:
    facts = (
        _facts(captain_realized_error=-8.0, below_lower_quantile=True),
        _facts(captain_realized_error=-2.0),
        _facts(captain_realized_error=None),
    )
    described = captain_description(facts)
    assert described["measurable"] is True
    assert described["fold_count"] == 2
    assert described["folds_without_captain"] == 1
    # The mean is over the two errors that exist; a zero for the third would give -3.33.
    assert described["mean_captain_realized_error"] == pytest.approx(-5.0)
    assert described["mean_captain_realized_error_below_lower_quantile"] == pytest.approx(-8.0)

    assert captain_description((_facts(captain_realized_error=None),))["measurable"] is False


def test_a_residual_export_without_team_ids_says_so_instead_of_joining_one() -> None:
    """No join, no fabrication: the diagnostic that cannot be measured is named."""

    described = common_shock_description(
        (_facts(),), pd.DataFrame({"fold_id": ["2023-24-gw10"], "residual": [0.5]})
    )
    assert described["measurable"] is False
    assert "team-shock diagnostic not measurable" in str(described["reason"])


# --- 6. the artifact ------------------------------------------------------------------


def test_the_artifact_is_written_exactly_once(tmp_path: Path) -> None:
    target = tmp_path / "diagnostic.json"
    document = {"contract_version": "phase2_tail_diagnostic_v1", "classification": "x"}

    assert write_document_once(document, target) == "written"
    assert write_document_once(document, target) == "replay"
    assert json.loads(target.read_text(encoding="utf-8")) == document

    with pytest.raises(ShadowReportError, match="already holds a different measurement"):
        write_document_once({**document, "classification": "y"}, target)
    assert [entry.name for entry in tmp_path.iterdir() if ".tmp-" in entry.name] == []


def test_no_field_this_study_records_can_reach_a_published_payload() -> None:
    """The study's names are internal; the published surface is a closed set."""

    recorded = {
        "classification",
        "eligible_scales",
        "scale_levels",
        "control_replay",
        "common_shock",
        "captain",
        "mean_probability_integral_transform",
        "below_lower_quantile_rate",
        "below_lower_quantile_folds",
        "mean_tail_width",
        "mean_pit_bootstrap_low",
        "pearson_correlation",
        "mean_captain_realized_error",
    }
    assert recorded.isdisjoint(PUBLISHABLE_FIELDS)


def test_an_arm_summary_reports_the_count_beside_the_rate() -> None:
    """At 37 folds a rate can only land on multiples of 1/37, so the count is the fact."""

    from squadopt.experiments.tail_diagnostic import ArmReading

    readings = tuple(
        ArmReading(
            fold_id=f"2023-24-gw{index:02d}",
            season="2023-24",
            scale=1.0,
            probability_integral_transform=0.5,
            below_lower_quantile=index < 4,
            scenario_mean_score=55.0,
            realized_score=50.0,
            tail_width=15.0,
        )
        for index in range(2, 12)
    )
    summary = summarise_arm(readings)
    assert summary["fold_count"] == 10.0
    assert summary["below_lower_quantile_folds"] == 2.0
    assert summary["below_lower_quantile_rate"] == pytest.approx(0.2)
    assert summary["mean_tail_width"] == pytest.approx(15.0)
    assert summary["mean_pit_bootstrap_low"] is not None
