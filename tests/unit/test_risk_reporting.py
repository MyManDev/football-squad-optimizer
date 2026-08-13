"""Tests for portable Sprint 4 artifact rendering helpers."""

import numpy as np
from scripts.run_risk_screening import _json_identifier, _markdown


def _report() -> dict[str, object]:
    return {
        "created_utc": "2026-01-01T00:00:00+00:00",
        "provenance": {
            "repository_commit": "a" * 40,
            "working_tree_dirty": True,
            "archive_repository": "owner/repo",
            "archive_commit": "b" * 40,
            "feature_generation_contract_version": "feature-v1",
            "baseline_form_window": 5,
            "configuration_fingerprint": "c" * 64,
        },
        "configuration": {},
        "diagnostics": {
            "calibration_policy": "expanding-completed-seasons",
            "seed_season": "s1",
            "evaluation_seasons": ("s2",),
            "holdout_accessed": False,
            "promotion_performed": False,
        },
        "candidates": [
            {
                "risk_aversion": 0.0,
                "metrics": {
                    "attempted_folds": 1,
                    "feasibility_rate": 0.0,
                    "mean_realized_squad_points": None,
                    "realized_squad_points_stddev": None,
                    "downside_quantile_score": None,
                    "mean_worst_fraction_score": None,
                    "mean_risk_penalty_value": None,
                },
                "comparison": {
                    "mean_difference": None,
                    "squad_changed_folds": 0,
                    "starting_xi_changed_folds": 0,
                    "captain_changed_folds": 0,
                },
            }
        ],
        "limitations": ["Synthetic limitation."],
    }


def test_markdown_is_cp1254_safe_and_handles_missing_metrics() -> None:
    markdown = _markdown(_report())

    markdown.encode("cp1254", errors="strict")
    assert "Risk aversion" in markdown
    assert "n/a" in markdown


def test_numpy_integer_identifier_is_json_safe() -> None:
    value = _json_identifier(np.int64(7))

    assert value == 7
    assert isinstance(value, int)
