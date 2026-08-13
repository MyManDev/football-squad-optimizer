"""Tests for Sprint 5 benchmark provenance and portable report rendering."""

from scripts.run_player_risk_screening import (
    _markdown,
    _prediction_builder,
    _prediction_provenance,
)
from tests.fixtures.synthetic_gameweeks import SEASON, make_canonical_gameweeks

from squadopt.backtest import DecisionPoint, build_walk_forward_fold


def test_real_screening_builder_attaches_prediction_provenance() -> None:
    fold = build_walk_forward_fold(
        make_canonical_gameweeks(),
        DecisionPoint(SEASON, 6),
        projection_builder=_prediction_builder("a" * 64),
    )

    provenance = _prediction_provenance((fold,))
    rows = provenance["prediction_fingerprints"]
    assert isinstance(rows, list)
    assert provenance["all_folds_provenanced"] is True
    assert rows[0]["model_name"] == "deterministic-rate-minutes-baseline"
    assert rows[0]["training_cutoff"] == f"{SEASON}:before-GW06-outcomes"
    assert rows[0]["training_data_fingerprint"] == "a" * 64
    assert len(rows[0]["prediction_fingerprint"]) == 64


def test_markdown_is_cp1254_safe_and_explicitly_reports_no_holdout_or_promotion() -> None:
    report: dict[str, object] = {
        "created_utc": "2026-01-01T00:00:00+00:00",
        "provenance": {
            "repository_commit": "a" * 40,
            "working_tree_dirty": True,
            "archive_repository": "owner/repo",
            "archive_commit": "b" * 40,
            "feature_generation_contract_version": "features-v1",
            "configuration_fingerprint": "c" * 64,
        },
        "configuration": {
            "scale_training_fraction": 0.5,
            "min_player_observations": 5,
            "shrinkage_observations": 10.0,
            "minimum_scale": 0.25,
        },
        "diagnostics": {
            "calibration_policy": "expanding-completed-seasons",
            "calibration_split": "chronological-disjoint-folds",
            "evaluation_seasons": ("s2",),
            "holdout_accessed": False,
            "promotion_performed": False,
        },
        "candidates": [],
        "limitations": ["Synthetic limitation."],
    }

    markdown = _markdown(report)

    markdown.encode("cp1254", errors="strict")
    assert "Reused 2025-26 benchmark accessed: `false`" in markdown
    assert "Promotion performed: `false`" in markdown
