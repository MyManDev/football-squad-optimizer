"""Tests for the in-season blend benchmark.

The measurement itself takes an hour of CP-SAT and cannot live in a unit suite, so what is
tested here is everything that would make that hour produce a wrong number quietly:

- the locked holdout must be cut away before anything reads a feature window;
- every configuration must be scored on the *same* folds, because an unpaired fold is a
  smaller sample rather than an error;
- each fold must carry its season in metadata, because the interval helper skips a fold
  without one and would return an interval over fewer folds than the run claims.

The panel is synthetic and no optimizer runs: the pieces under test are the population, the
guard and the pairing, not the solver.
"""

from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from scripts import measure_in_season_blend as benchmark

from squadopt.backtest.splits import BacktestConfigurationError


def _panel(seasons: tuple[str, ...], gameweeks: int = 4, players: int = 6) -> pd.DataFrame:
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
                        "team_id": f"Club {index % 3}",
                        "position": positions[index % 4],
                        "price_tenths": 50 + index,
                        "minutes": 90,
                        "total_points": 3 + (index % 3),
                    }
                )
    return pd.DataFrame(rows)


# --- the locked holdout is cut, not filtered --------------------------------


def test_the_holdout_season_is_cut_away_before_anything_reads_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cut rather than filtered later, so it cannot reach a feature window as history."""

    seasons = (*benchmark.DEVELOPMENT_SEASONS, benchmark.LOCKED_HOLDOUT_SEASON)
    monkeypatch.setattr(benchmark, "build_panel", lambda root: _panel(seasons))

    visible = benchmark._visible_panel(Path("unused"))

    remaining = sorted({str(value) for value in visible["season"].tolist()})
    assert benchmark.LOCKED_HOLDOUT_SEASON not in remaining
    assert set(benchmark.DEVELOPMENT_SEASONS) <= set(remaining)


def test_an_earlier_season_survives_the_cut_because_carry_over_needs_it() -> None:
    """The cut removes what comes *after* the development seasons, not what precedes them."""

    assert "2020-21" not in benchmark.DEVELOPMENT_SEASONS
    assert benchmark.DEVELOPMENT_SEASONS[0] == "2021-22"


def test_a_missing_development_season_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(benchmark, "build_panel", lambda root: _panel(("2021-22",)))

    with pytest.raises(BacktestConfigurationError, match="absent from the panel"):
        benchmark._visible_panel(Path("unused"))


def test_the_holdout_is_never_a_development_season() -> None:
    assert benchmark.LOCKED_HOLDOUT_SEASON not in benchmark.DEVELOPMENT_SEASONS


# --- the pairing refuses to shrink the sample quietly -----------------------


class _Fold:
    def __init__(self, fold_id: str, points: float | None, season: str | None) -> None:
        self.fold_id = fold_id
        self.realized_squad_points = points
        self.metadata: dict[str, object] = {} if season is None else {"season": season}


class _Result:
    def __init__(self, folds: list[_Fold]) -> None:
        self.folds = folds


def _paired(candidate: list[_Fold], control: list[_Fold]) -> dict[str, object]:
    return benchmark._paired(
        _Result(candidate),  # type: ignore[arg-type]
        _Result(control),  # type: ignore[arg-type]
        candidate_id="candidate|control",
    )


def test_matching_folds_are_paired_and_summarised() -> None:
    candidate = [_Fold(f"2021-22-gw{n:02d}", 50.0 + n, "2021-22") for n in range(2, 10)]
    control = [_Fold(f"2021-22-gw{n:02d}", 48.0 + n, "2021-22") for n in range(2, 10)]

    comparison = _paired(candidate, control)

    assert comparison["folds_paired"] == 8
    assert comparison["mean_difference"] == pytest.approx(2.0)
    assert comparison["seasons"] == 1
    assert comparison["seasons_positive"] == 1


def test_a_fold_the_control_did_not_score_stops_the_run() -> None:
    """An unpaired fold is a quietly smaller sample, so it must fail rather than drop."""

    candidate = [_Fold(f"2021-22-gw{n:02d}", 50.0, "2021-22") for n in range(2, 6)]
    control = [_Fold(f"2021-22-gw{n:02d}", 48.0, "2021-22") for n in range(2, 5)]

    with pytest.raises(BacktestConfigurationError, match="could not be paired"):
        _paired(candidate, control)


def test_an_infeasible_fold_stops_the_run_rather_than_being_skipped() -> None:
    candidate = [_Fold("2021-22-gw02", None, "2021-22"), _Fold("2021-22-gw03", 50.0, "2021-22")]
    control = [_Fold("2021-22-gw02", 48.0, "2021-22"), _Fold("2021-22-gw03", 48.0, "2021-22")]

    with pytest.raises(BacktestConfigurationError, match="could not be paired"):
        _paired(candidate, control)


def test_a_fold_without_its_season_in_metadata_stops_the_run() -> None:
    """The trap this test exists for.

    ``season_aware_moving_block_interval`` reads ``metadata["season"]`` and *skips* a fold
    that lacks it. Skipping would narrow the interval over fewer folds than the run reports,
    with no error anywhere, so the pairing refuses instead.
    """

    candidate = [_Fold("2021-22-gw02", 50.0, None), _Fold("2021-22-gw03", 50.0, "2021-22")]
    control = [_Fold("2021-22-gw02", 48.0, "2021-22"), _Fold("2021-22-gw03", 48.0, "2021-22")]

    with pytest.raises(BacktestConfigurationError, match="could not be paired"):
        _paired(candidate, control)


def test_the_interval_is_season_aware_across_more_than_one_season() -> None:
    """Blocks are resampled within a season, so both seasons must reach the helper."""

    candidate = [
        _Fold(f"{season}-gw{n:02d}", 50.0 + n, season)
        for season in ("2021-22", "2022-23")
        for n in range(2, 10)
    ]
    control = [
        _Fold(f"{season}-gw{n:02d}", 48.0 + n, season)
        for season in ("2021-22", "2022-23")
        for n in range(2, 10)
    ]

    comparison = _paired(candidate, control)

    assert comparison["seasons"] == 2
    assert comparison["folds_paired"] == 16
    assert comparison["interval_lower"] <= comparison["mean_difference"]  # type: ignore[operator]
    assert comparison["mean_difference"] <= comparison["interval_upper"]  # type: ignore[operator]


# --- the configuration set is the declared one ------------------------------


def test_the_declared_configuration_is_the_module_default() -> None:
    """If these drift from prediction.in_season's defaults the run measures another model."""

    from squadopt.prediction.in_season import InSeasonBlendConfig

    declared = InSeasonBlendConfig()

    assert declared.prior_minute_equivalent == benchmark.DECLARED_MINUTE_EQUIVALENT
    assert declared.prior_gameweek_equivalent == benchmark.DECLARED_GAMEWEEK_EQUIVALENT


def test_both_declared_values_are_on_their_own_axis() -> None:
    """A cross through the declared point; an axis that omits it measures nothing about it."""

    assert benchmark.DECLARED_MINUTE_EQUIVALENT in benchmark.MINUTE_AXIS
    assert benchmark.DECLARED_GAMEWEEK_EQUIVALENT in benchmark.GAMEWEEK_AXIS


def test_the_control_windows_cover_both_sides_of_tonights_holdout() -> None:
    """fw05 is the operational control and fw10 the challenger, so either outcome is covered."""

    assert benchmark.CONTROL_FORM_WINDOWS == (5, 10)


def test_the_record_declares_itself_measurement_only() -> None:
    """A benchmark readable as gate evidence would invite promotion from it.

    Asserted against the constant the record is actually built from, so this cannot pass
    while the written artifact says something else.
    """

    provenance = benchmark.RECORD_PROVENANCE

    assert provenance["measurement_only"] is True
    assert provenance["gate_evidence"] is False
    assert provenance["locked_holdout_accessed"] is False
    assert provenance["optimizer_held_fixed"] is True
    assert provenance["comparable_to_screening_levels"] is False


def test_the_written_record_carries_every_provenance_flag() -> None:
    """The flags reach the artifact rather than only existing as a constant."""

    source = Path(benchmark.__file__).read_text(encoding="utf-8")

    assert "**dict(RECORD_PROVENANCE)" in source
    for key in benchmark.RECORD_PROVENANCE:
        assert f'"{key}"' in source
