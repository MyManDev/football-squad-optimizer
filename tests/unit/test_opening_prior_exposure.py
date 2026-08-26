"""Tests for the opening price prior's exposure measurement.

The measurement itself reads the real archive and cannot live in a unit suite, so what is
tested here is everything that would make it produce a wrong number quietly:

- the population must be the in-season blend benchmark's, because this measures *that*
  record's caveat and a differently-shaped fold list would answer a different question;
- the locked holdout must be cut away before anything reads a feature window;
- the coefficient must be refit on seasons that finished before the one being projected;
- the attribution must equal the whole projection where the prior priced a row outright and
  zero where no rung reached it -- that identity is the reason the estimator is a finite
  difference rather than a second copy of the precedence rules;
- the squad-shaped proxy must fill the position quotas, since a flat top-fifteen could
  return an illegal shape and the record leans on that column.

The panel is synthetic and no optimizer runs.
"""

from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from scripts import measure_in_season_blend as benchmark

from squadopt.experiments.config import ExperimentConfigurationError, ExperimentExecutionError
from squadopt.experiments.opening_prior_exposure import (
    OpeningPriorExposureConfig,
    _fold_totals,
    _squad_shaped_index,
    _visible_panel,
    measure_opening_prior_exposure,
    walk_forward_coefficients,
)
from squadopt.prediction.config import FITTED_OPENING_PRICE_COEFFICIENT


def _panel(seasons: tuple[str, ...], gameweeks: int = 4, players: int = 24) -> pd.DataFrame:
    """A canonical panel with every position represented often enough to fill a squad."""

    rows: list[dict[str, Any]] = []
    positions = ("GK", "DEF", "MID", "FWD")
    for season in seasons:
        for gameweek in range(1, gameweeks + 1):
            for index in range(players):
                rows.append(
                    {
                        "season": season,
                        "gameweek": gameweek,
                        "player_id": 1000 + index,
                        "name": f"Player {1000 + index}",
                        "team_id": f"Club {index % 5}",
                        "position": positions[index % 4],
                        "price_tenths": 45 + index,
                        "minutes": 90,
                        "total_points": 2 + (index % 4),
                    }
                )
    return pd.DataFrame(rows)


# --- the population is the benchmark's, not a copy that may drift from it ----


def test_the_population_is_the_benchmarks_own() -> None:
    """A measurement of that record's caveat has to describe that record's folds."""

    from squadopt.experiments import opening_prior_exposure as exposure

    assert exposure.DEVELOPMENT_SEASONS == benchmark.DEVELOPMENT_SEASONS
    assert exposure.MIN_PRIOR_GAMEWEEKS_IN_SEASON == benchmark.MIN_PRIOR_GAMEWEEKS_IN_SEASON
    assert exposure.LOCKED_HOLDOUT_SEASON == benchmark.LOCKED_HOLDOUT_SEASON
    assert exposure.ROSTER_COLUMNS == benchmark.ROSTER_COLUMNS


def test_the_measured_configurations_are_labelled_as_the_benchmark_labels_them() -> None:
    """The labels are how a reader joins this record to the one it qualifies."""

    from squadopt.experiments import opening_prior_exposure as exposure

    settings = OpeningPriorExposureConfig()
    assert settings.prior_minute_equivalent == benchmark.DECLARED_MINUTE_EQUIVALENT
    assert settings.prior_gameweek_equivalent == benchmark.DECLARED_GAMEWEEK_EQUIVALENT
    assert settings.control_form_window in benchmark.CONTROL_FORM_WINDOWS
    assert (
        f"blend-m{benchmark.DECLARED_MINUTE_EQUIVALENT}"
        f"-g{benchmark.DECLARED_GAMEWEEK_EQUIVALENT}-declared"
    ) == exposure.BLEND_LABEL
    assert f"control-fw{settings.control_form_window:02d}" == exposure.CONTROL_LABEL


# --- the locked holdout ------------------------------------------------------


def test_the_holdout_season_is_cut_away_before_anything_reads_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from squadopt.experiments import opening_prior_exposure as exposure

    seasons = ("2020-21", *exposure.DEVELOPMENT_SEASONS, exposure.LOCKED_HOLDOUT_SEASON)
    monkeypatch.setattr(exposure, "build_panel", lambda root: _panel(seasons))

    visible = _visible_panel(Path("unused"), OpeningPriorExposureConfig())

    remaining = sorted({str(value) for value in visible["season"].tolist()})
    assert exposure.LOCKED_HOLDOUT_SEASON not in remaining
    assert "2020-21" in remaining, "the season before the development block carries the fit"


def test_the_holdout_cannot_be_configured_as_a_development_season() -> None:
    from squadopt.experiments import opening_prior_exposure as exposure

    with pytest.raises(ExperimentConfigurationError, match="locked holdout"):
        OpeningPriorExposureConfig(development_seasons=(exposure.LOCKED_HOLDOUT_SEASON,))


def test_a_missing_development_season_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    from squadopt.experiments import opening_prior_exposure as exposure

    monkeypatch.setattr(exposure, "build_panel", lambda root: _panel(("2021-22",)))

    with pytest.raises(ExperimentExecutionError, match="absent from the panel"):
        _visible_panel(Path("unused"), OpeningPriorExposureConfig())


# --- the probe, which is the estimator -------------------------------------


def test_the_two_probe_scales_must_differ_or_the_check_checks_nothing() -> None:
    with pytest.raises(ExperimentConfigurationError, match="must differ"):
        OpeningPriorExposureConfig(probe_scale=1e-6, verification_probe_scale=1e-6)


@pytest.mark.parametrize("scale", [0.0, 1.0, -1e-6, 2.0])
def test_a_probe_scale_outside_the_unit_interval_is_refused(scale: float) -> None:
    with pytest.raises(ExperimentConfigurationError, match="strictly between 0 and 1"):
        OpeningPriorExposureConfig(probe_scale=scale)


def _table(points: list[float], positions: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"position": positions, "expected_points": points})


def test_attribution_is_the_whole_projection_where_the_prior_priced_the_row() -> None:
    """A purely prior-priced row is linear in the coefficient, so c * dP/dc is P itself."""

    scale = 1e-6
    base = pd.Series([2.0, 5.0], dtype="float64")
    # The first row is priced from the prior and scales with the coefficient; the second
    # comes from a rung that never reads it.
    probed = pd.Series([2.0 * (1.0 + scale), 5.0], dtype="float64")
    table = _table([2.0, 5.0], ["GK", "MID"])

    totals = _fold_totals(table, base, probed, scale)

    assert totals.attributable == pytest.approx(2.0, rel=1e-6)
    assert totals.touching == 1


def test_attribution_is_zero_where_no_rung_reached_the_prior() -> None:
    base = pd.Series([3.0, 4.0], dtype="float64")
    table = _table([3.0, 4.0], ["DEF", "FWD"])

    totals = _fold_totals(table, base, base.copy(), 1e-6)

    assert totals.attributable == pytest.approx(0.0)
    assert totals.touching == 0


def test_attribution_is_the_carried_portion_of_a_partly_shrunk_rung() -> None:
    """A rung that is half the prior contributes half its projection, not all of it."""

    scale = 1e-6
    base = pd.Series([4.0], dtype="float64")
    # Half of the four points move with the coefficient.
    probed = pd.Series([4.0 + 2.0 * scale], dtype="float64")

    totals = _fold_totals(_table([4.0], ["MID"]), base, probed, scale)

    assert totals.attributable == pytest.approx(2.0, rel=1e-6)


# --- the squad-shaped proxy -------------------------------------------------


def test_the_squad_shaped_selection_fills_the_position_quotas() -> None:
    from squadopt.experiments import opening_prior_exposure as exposure

    positions = ["GK"] * 4 + ["DEF"] * 8 + ["MID"] * 8 + ["FWD"] * 6
    points = [float(len(positions) - index) for index in range(len(positions))]
    table = _table(points, positions)

    index = _squad_shaped_index(table, table["expected_points"])
    chosen = table.loc[index, "position"].value_counts().to_dict()

    assert chosen == dict(exposure._SQUAD_SHAPE)
    assert len(index) == sum(exposure._SQUAD_SHAPE.values()) == 15


def test_the_squad_shaped_selection_takes_the_best_at_each_position() -> None:
    positions = ["GK", "GK", "GK", "DEF", "MID", "FWD"]
    points = [1.0, 9.0, 5.0, 2.0, 2.0, 2.0]
    table = _table(points, positions)

    index = _squad_shaped_index(table, table["expected_points"])

    keepers = sorted(table.loc[index].loc[lambda f: f["position"] == "GK", "expected_points"])
    assert keepers == [5.0, 9.0], "the two best keepers, not the first two rows"


# --- the refit is walk-forward ----------------------------------------------


def test_the_coefficient_is_fitted_only_on_seasons_that_finished_first() -> None:
    panel = _panel(("2020-21", "2021-22", "2022-23", "2023-24", "2024-25"))
    config = OpeningPriorExposureConfig()

    fitted = walk_forward_coefficients(panel, config)

    assert tuple(entry.season for entry in fitted) == config.development_seasons
    for entry in fitted:
        assert entry.fitted_on, "every development season has at least one season before it"
        assert all(season < entry.season for season in entry.fitted_on)
        assert entry.season not in entry.fitted_on


def test_the_refit_reports_its_distance_from_the_shipped_constant() -> None:
    panel = _panel(("2020-21", "2021-22", "2022-23", "2023-24", "2024-25"))

    fitted = walk_forward_coefficients(panel, OpeningPriorExposureConfig())

    for entry in fitted:
        assert entry.difference_from_frozen == pytest.approx(
            entry.coefficient - FITTED_OPENING_PRICE_COEFFICIENT
        )


def test_a_season_with_nothing_before_it_is_refused_rather_than_frozen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Silently falling back to the frozen constant would hide the one fold it applies to."""

    panel = _panel(("2021-22", "2022-23"))
    config = OpeningPriorExposureConfig(development_seasons=("2021-22", "2022-23"))

    with pytest.raises(ExperimentExecutionError, match="No season precedes"):
        walk_forward_coefficients(panel, config)


# --- end to end on a synthetic panel ----------------------------------------


def test_the_measurement_runs_end_to_end_and_declares_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from squadopt.experiments import opening_prior_exposure as exposure

    seasons = ("2020-21", *exposure.DEVELOPMENT_SEASONS, exposure.LOCKED_HOLDOUT_SEASON)
    monkeypatch.setattr(exposure, "build_panel", lambda root: _panel(seasons))

    result = measure_opening_prior_exposure(Path("unused"), fold_limit=2)

    assert result.contract_version == exposure.OPENING_PRIOR_EXPOSURE_CONTRACT_VERSION
    assert result.folds == 2
    assert {entry.label for entry in result.configurations} == {
        exposure.CONTROL_LABEL,
        exposure.BLEND_LABEL,
        exposure.FLOOR_LABEL,
    }
    assert result.diagnostics["measurement_only"] is True
    assert result.diagnostics["gate_evidence"] is False
    assert result.diagnostics["locked_holdout_read"] is False
    assert result.diagnostics["decision_level_rescore"] is False
    for entry in result.configurations:
        assert entry.rows > 0
        assert 0.0 <= entry.row_share <= 1.0
        assert entry.finite_difference_disagreement < 1e-3
