"""Contract tests for the control-regime residual export.

The export claims `oos_residual_export_v1` conformance, so the tests hold it to its
own preflight: the artifact the calibration layers will consume must pass the same
gate a prediction-side handoff would.
"""

import pandas as pd
import pytest
from tests.fixtures.synthetic_gameweeks import SEASON, make_canonical_gameweeks

from squadopt.experiments import (
    CONTROL_CANDIDATE_LABEL,
    CONTROL_MODEL_NAME,
    ExperimentExecutionError,
    PolicyObjectiveConfig,
    build_control_residual_table,
    control_model_version,
    control_residual_manifest,
)
from squadopt.preflight import (
    RESIDUAL_EXPORT_COLUMNS,
    run_residual_export_preflight,
)

CONFIG = PolicyObjectiveConfig(development_seasons=(SEASON,))


def _table() -> pd.DataFrame:
    return build_control_residual_table(make_canonical_gameweeks(), CONFIG)


def _manifest(table: pd.DataFrame) -> dict[str, object]:
    return dict(
        control_residual_manifest(
            table,
            form_window=5,
            repository_commit="a" * 40,
            dataset_snapshot_id="vaastav-fpl@test-pin",
            table_sha256="0" * 64,
            created_at_utc="2026-08-15T00:00:00Z",
        )
    )


def test_the_export_passes_its_own_preflight() -> None:
    table = _table()

    report = run_residual_export_preflight(table, _manifest(table))

    assert report.passed, [finding.detail for finding in report.failures]


def test_the_export_covers_every_projected_player_on_every_fold() -> None:
    table = _table()

    assert tuple(table.columns) == RESIDUAL_EXPORT_COLUMNS
    assert table["fold_id"].nunique() == 7
    folds = table.groupby("fold_id", sort=True).size()
    assert set(folds) == {36}
    assert (table["gameweek"] >= 2).all()


def test_residuals_are_out_of_sample_predictions_against_realized_points() -> None:
    table = _table()

    assert (table["predicted_points"] >= 0.0).all()
    drift = (table["residual"] - (table["realized_points"] - table["predicted_points"])).abs()
    assert float(drift.max()) < 1e-12


def test_the_export_is_deterministic() -> None:
    first = _table()
    second = _table()

    pd.testing.assert_frame_equal(first, second)


def test_the_manifest_names_the_control_regime() -> None:
    table = _table()
    manifest = _manifest(table)

    assert manifest["candidate_label"] == CONTROL_CANDIDATE_LABEL
    assert manifest["model_name"] == CONTROL_MODEL_NAME
    assert manifest["model_version"] == control_model_version(5)
    assert manifest["opening_gameweeks_included"] is False
    assert manifest["fold_count"] == 7
    assert manifest["row_count"] == len(table)


def test_an_unknown_season_is_refused() -> None:
    with pytest.raises(ExperimentExecutionError, match="absent from the panel"):
        build_control_residual_table(
            make_canonical_gameweeks(),
            PolicyObjectiveConfig(development_seasons=("1999-00",)),
        )


def test_the_input_panel_is_not_mutated() -> None:
    panel = make_canonical_gameweeks()
    original = panel.copy(deep=True)

    build_control_residual_table(panel, CONFIG)

    pd.testing.assert_frame_equal(panel, original)
