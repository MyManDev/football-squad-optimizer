"""Tests for the candidate residual export.

The export is one half of a pair a measurement run consumes without repairing anything,
so what is tested here is the ways it could hand over something wrong while looking
right: an identity that drifts, a builder with no versioned provenance, an unmatched
player quietly dropped, and a column order the receiving contract does not expect.
"""

import pandas as pd
import pytest
from tests.fixtures.synthetic_gameweeks import (
    PREVIOUS_SEASON,
    SEASON,
    make_canonical_gameweeks,
    make_two_season_gameweeks,
)

from squadopt.backtest.candidate_residuals import (
    build_candidate_residual_table,
    candidate_identity,
    candidate_residual_manifest,
)
from squadopt.backtest.folds import build_walk_forward_folds, make_baseline_projection_builder
from squadopt.backtest.splits import BacktestConfigurationError, DecisionPoint
from squadopt.features import CrossSeasonConfig
from squadopt.prediction.integration import PredictionProvenance, prepare_optimizer_projection
from squadopt.preflight import RESIDUAL_EXPORT_COLUMNS, RESIDUAL_EXPORT_CONTRACT_VERSION

SNAPSHOT_COLUMNS = ("player_id", "name", "team_id", "position", "price_tenths")
FINGERPRINT = "0" * 64

MANIFEST_ARGUMENTS = {
    "candidate_label": "calendar_aware_production",
    "training_contract_version": "expanding_window_opening_price_prior_v1",
    "repository_commit": "a" * 40,
    "dataset_snapshot_id": "vaastav-fpl@" + "b" * 40,
    "table_sha256": "c" * 64,
    "created_at_utc": "2026-08-16T09:00:00+00:00",
}


def _snapshot_builder(*, model_version: str = "test-v1", drift: bool = False):
    """Wrap the baseline projection in a versioned snapshot, as a real candidate does."""

    baseline = make_baseline_projection_builder(cross_season=CrossSeasonConfig())

    def build(visible: pd.DataFrame, decision: DecisionPoint):
        table = baseline(visible, decision)
        provenance = PredictionProvenance(
            model_name="test-candidate",
            model_version=(
                f"{model_version}-gw{decision.gameweek:02d}" if drift else model_version
            ),
            feature_contract_version="test-features-v1",
            training_cutoff=f"{decision.season}:GW{decision.gameweek:02d}",
            training_data_fingerprint=FINGERPRINT,
        )
        predictions = pd.DataFrame(
            {
                "player_id": table["player_id"].to_numpy(),
                "expected_points": table["expected_points"].to_numpy(),
            }
        )
        return prepare_optimizer_projection(
            table.loc[:, list(SNAPSHOT_COLUMNS)], predictions, provenance
        )

    return build


def _table(**kwargs) -> tuple[pd.DataFrame, dict[str, str]]:
    table, identity = build_candidate_residual_table(
        make_canonical_gameweeks(), _snapshot_builder(), seasons=(SEASON,), **kwargs
    )
    return table, dict(identity)


# --- model identity ---------------------------------------------------------


def test_identity_comes_from_the_snapshots_rather_than_the_caller() -> None:
    """Passing identity in is how the declaration and the manifest drift apart."""

    _, identity = _table()

    assert identity == {
        "model_name": "test-candidate",
        "model_version": "test-v1",
        "feature_contract_version": "test-features-v1",
    }


def test_a_builder_without_versioned_provenance_is_refused() -> None:
    """A plain frame cannot support a manifest that claims a model version."""

    with pytest.raises(BacktestConfigurationError, match="versioned PredictionSnapshot"):
        build_candidate_residual_table(
            make_canonical_gameweeks(),
            make_baseline_projection_builder(cross_season=CrossSeasonConfig()),
            seasons=(SEASON,),
        )


def test_an_identity_that_drifts_between_folds_is_refused() -> None:
    """One export describes one model; two versions under one manifest is a lie."""

    with pytest.raises(BacktestConfigurationError, match="differs across folds"):
        build_candidate_residual_table(
            make_canonical_gameweeks(),
            _snapshot_builder(drift=True),
            seasons=(SEASON,),
        )


def test_identity_of_an_empty_fold_sequence_is_refused() -> None:
    with pytest.raises(BacktestConfigurationError, match="non-empty"):
        candidate_identity(())


# --- the join discipline ----------------------------------------------------


def test_a_projected_player_with_no_realized_outcome_raises() -> None:
    """The contract forbids silent drops; build_residual_history inner-joins instead."""

    from squadopt.backtest import candidate_residuals

    folds = build_walk_forward_folds(
        make_canonical_gameweeks(), seasons=(SEASON,), projection_builder=_snapshot_builder()
    )
    fold = folds[0]
    truncated = type(fold)(
        fold_id=fold.fold_id,
        projections=fold.projections,
        realized_points=fold.realized_points.iloc[1:],
        metadata=fold.metadata,
    )

    with pytest.raises(BacktestConfigurationError, match="no realized outcome"):
        candidate_residuals._residual_rows(truncated)


def test_every_projected_player_appears_exactly_once_per_fold() -> None:
    table, _ = _table()

    duplicated = table.duplicated(subset=["fold_id", "player_id"])

    assert not bool(duplicated.any())


# --- the contract shape -----------------------------------------------------


def test_the_column_order_matches_the_export_contract() -> None:
    table, _ = _table()

    assert tuple(table.columns) == RESIDUAL_EXPORT_COLUMNS


def test_rows_are_sorted_by_season_gameweek_and_player() -> None:
    table, _ = _table()

    expected = table.sort_values(["season", "gameweek", "player_id"], kind="stable")

    assert table.equals(expected.reset_index(drop=True))


def test_the_residual_is_realized_minus_predicted() -> None:
    table, _ = _table()

    difference = table["realized_points"] - table["predicted_points"] - table["residual"]

    assert float(difference.abs().max()) == 0.0


def test_fold_identifiers_use_the_contract_format() -> None:
    table, _ = _table()

    expected = [
        f"{season}-gw{gameweek:02d}"
        for season, gameweek in zip(table["season"], table["gameweek"], strict=True)
    ]

    assert table["fold_id"].tolist() == expected


def test_opening_gameweeks_stay_out_of_the_export() -> None:
    table, _ = _table()

    assert not bool((table["gameweek"] == 1).any())


def test_folding_an_opening_gameweek_is_refused() -> None:
    """Opening gameweeks are a separate evidence regime, per the GW1 blocker report."""

    with pytest.raises(BacktestConfigurationError, match="separate evidence regime"):
        _table(min_prior_gameweeks_in_season=0)


# --- the visible history ----------------------------------------------------


def test_seasons_after_the_declared_range_are_cut_before_features_are_built() -> None:
    """A locked-holdout row must not reach a shifted window even as carry-over."""

    both, _ = build_candidate_residual_table(
        make_two_season_gameweeks(), _snapshot_builder(), seasons=(PREVIOUS_SEASON,)
    )
    earlier_only, _ = build_candidate_residual_table(
        make_two_season_gameweeks().loc[lambda frame: frame["season"] == PREVIOUS_SEASON],
        _snapshot_builder(),
        seasons=(PREVIOUS_SEASON,),
    )

    assert both.equals(earlier_only)


def test_a_season_absent_from_the_panel_is_refused() -> None:
    with pytest.raises(BacktestConfigurationError, match="absent from the panel"):
        build_candidate_residual_table(
            make_canonical_gameweeks(), _snapshot_builder(), seasons=("1999-00",)
        )


# --- the manifest -----------------------------------------------------------


def test_the_manifest_carries_the_identity_the_snapshots_reported() -> None:
    table, identity = _table()

    manifest = candidate_residual_manifest(table, identity, **MANIFEST_ARGUMENTS)

    assert manifest["model_name"] == identity["model_name"]
    assert manifest["model_version"] == identity["model_version"]
    assert manifest["feature_contract_version"] == identity["feature_contract_version"]
    assert manifest["contract_version"] == RESIDUAL_EXPORT_CONTRACT_VERSION


def test_the_manifest_counts_come_from_the_table_it_describes() -> None:
    table, identity = _table()

    manifest = candidate_residual_manifest(table, identity, **MANIFEST_ARGUMENTS)

    assert manifest["row_count"] == len(table)
    assert manifest["fold_count"] == table["fold_id"].nunique()
    assert manifest["development_seasons"] == [SEASON]
    assert manifest["opening_gameweeks_included"] is False


def test_the_opening_flag_is_evidence_rather_than_a_setting() -> None:
    """It must describe the table, not whatever the caller would prefer it to say."""

    table, identity = _table()
    opening = table.assign(gameweek=1, fold_id=f"{SEASON}-gw01")

    manifest = candidate_residual_manifest(opening, identity, **MANIFEST_ARGUMENTS)

    assert manifest["opening_gameweeks_included"] is True


@pytest.mark.parametrize("field", sorted(MANIFEST_ARGUMENTS))
def test_every_manifest_field_must_be_supplied(field: str) -> None:
    table, identity = _table()
    arguments = {**MANIFEST_ARGUMENTS, field: "  "}

    with pytest.raises(BacktestConfigurationError, match=field):
        candidate_residual_manifest(table, identity, **arguments)


def test_an_incomplete_identity_is_refused() -> None:
    table, identity = _table()
    identity.pop("model_version")

    with pytest.raises(BacktestConfigurationError, match="model_version"):
        candidate_residual_manifest(table, identity, **MANIFEST_ARGUMENTS)


def test_an_empty_table_cannot_carry_a_manifest() -> None:
    _, identity = _table()

    with pytest.raises(BacktestConfigurationError, match="non-empty"):
        candidate_residual_manifest(pd.DataFrame(), identity, **MANIFEST_ARGUMENTS)
