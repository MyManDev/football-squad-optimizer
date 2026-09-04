"""Tests for the measurement-artifact preflight.

Two populations are checked: synthetic documents that violate one governance rule at
a time, and the repository's own committed measurement artifacts — which must keep
passing their own gate whenever they are regenerated.
"""

import json
from pathlib import Path

import pytest

from squadopt.preflight import (
    MEASUREMENT_KINDS,
    PreflightError,
    run_measurement_preflight,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _document(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "contract_version": "risk_frontier_v1",
        "frontier": [{"risk_aversion": 0.0}],
        "anchor": {"form_window": 6, "bench_weight": 0.0},
        "residual_input": {"table_sha256": "a" * 64},
        "created_utc": "2026-08-15T00:00:00Z",
        "recommendation_only": True,
        "locked_holdout_accessed": False,
        "automatic_promotion": False,
        "objective_configuration_fingerprint": "b" * 64,
        "provenance": {
            "repository_commit": "c" * 40,
            "working_tree_dirty": False,
        },
    }
    base.update(overrides)
    return base


def _failed(document: dict[str, object], kind: str = "risk_frontier") -> tuple[str, ...]:
    report = run_measurement_preflight(document, kind)
    return tuple(finding.check for finding in report.failures)


def test_a_conforming_artifact_passes() -> None:
    report = run_measurement_preflight(_document(), "risk_frontier")

    assert report.passed, [finding.detail for finding in report.failures]


def test_a_missing_required_field_is_named() -> None:
    document = _document()
    del document["anchor"]

    assert "artifact_required_fields" in _failed(document)


def test_a_dirty_tree_fails_provenance() -> None:
    document = _document(provenance={"repository_commit": "c" * 40, "working_tree_dirty": True})

    assert "artifact_clean_tree" in _failed(document)


def test_a_holdout_access_flag_anywhere_fails() -> None:
    document = _document(nested={"inner": {"locked_holdout_accessed": True}})

    assert "artifact_no_holdout_access" in _failed(document)


def test_a_malformed_fingerprint_fails() -> None:
    document = _document(objective_configuration_fingerprint="not-a-digest")

    assert "artifact_digest_formats" in _failed(document)


def test_a_non_finite_number_fails() -> None:
    document = _document(frontier=[{"risk_aversion": float("nan")}])

    assert "artifact_finite_numbers" in _failed(document)


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(PreflightError, match="Unknown measurement kind"):
        run_measurement_preflight(_document(), "unknown_kind")


@pytest.mark.parametrize(
    ("kind", "relative_path"),
    [
        ("policy_grid", "docs/baseline_policy_grid.json"),
        ("risk_frontier", "docs/risk_frontier.json"),
        ("scenario_bayesopt", "docs/scenario_bayesopt_deterministic.json"),
        ("multi_gw_rehearsal", "docs/multi_gw_rehearsal.json"),
        ("baseline_bayesopt", "docs/baseline_bayesopt.json"),
    ],
)
def test_the_committed_artifacts_pass_their_own_gate(kind: str, relative_path: str) -> None:
    """Regenerated artifacts must stay conformant; this pins the committed ones."""

    path = REPOSITORY_ROOT / relative_path
    document = json.loads(path.read_text(encoding="utf-8"))

    report = run_measurement_preflight(document, kind, artifact_label=path.name)

    assert report.passed, [finding.detail for finding in report.failures]


def test_every_registered_kind_names_at_least_three_required_fields() -> None:
    for kind, required in MEASUREMENT_KINDS.items():
        assert len(required) >= 3, kind
