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
from squadopt.preflight.measurement import MEASUREMENT_DECLARATIONS

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


@pytest.mark.parametrize(
    ("field", "check"),
    [
        ("locked_holdout_accessed", "artifact_no_holdout_access"),
        ("automatic_promotion", "artifact_no_automatic_promotion"),
        ("recommendation_only", "artifact_recommendation_only"),
    ],
)
def test_a_required_root_declaration_cannot_be_replaced_by_a_nested_one(
    field: str, check: str
) -> None:
    document = _document()
    value = document.pop(field)
    document["nested"] = {field: value}

    assert check in _failed(document)


@pytest.mark.parametrize("value", [None, 0, "false", [], {}])
def test_invalid_declaration_types_are_not_false(value: object) -> None:
    assert "artifact_no_holdout_access" in _failed(_document(locked_holdout_accessed=value))


@pytest.mark.parametrize("value", [True, None, [], {}])
def test_nested_declarations_include_containers_and_contradictions(value: object) -> None:
    document = _document(nested=[{"automatic_promotion": value}])

    assert "artifact_no_automatic_promotion" in _failed(document)


def test_recommendation_only_false_cannot_pass() -> None:
    assert "artifact_recommendation_only" in _failed(_document(recommendation_only=False))


@pytest.mark.parametrize("kind", sorted(MEASUREMENT_KINDS))
def test_every_kind_requires_an_explicit_no_holdout_declaration(kind: str) -> None:
    document = _document()
    document.update({name: {} for name in MEASUREMENT_KINDS[kind] if name not in document})
    document.pop("locked_holdout_accessed")

    report = run_measurement_preflight(document, kind)

    assert "artifact_no_holdout_access" in {finding.check for finding in report.failures}
    assert set(MEASUREMENT_DECLARATIONS) == set(MEASUREMENT_KINDS)


@pytest.mark.parametrize("kind", ["scenario_audit", "control_uncertainty", "rotation_evidence"])
def test_descriptive_kinds_report_optional_absence_without_claiming_evidence(kind: str) -> None:
    document = _document()
    document.update({name: {} for name in MEASUREMENT_KINDS[kind] if name not in document})
    document.pop("automatic_promotion")
    document.pop("recommendation_only")

    report = run_measurement_preflight(document, kind)

    assert report.passed
    optional = [
        finding
        for finding in report.findings
        if finding.check in {"artifact_no_automatic_promotion", "artifact_recommendation_only"}
    ]
    assert len(optional) == 2
    assert all(
        "optional" in finding.detail and "undeclared" in finding.detail for finding in optional
    )


def test_an_optional_declaration_must_be_valid_when_supplied() -> None:
    document = _document(decision_level={}, player_level={}, rows=[], automatic_promotion=None)

    assert "artifact_no_automatic_promotion" in _failed(document, "scenario_audit")


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


def test_the_rotation_lane_has_a_kind_the_runner_covers() -> None:
    """An artifact outside the covered set has no gate to keep passing, so it needs one."""

    required = MEASUREMENT_KINDS["rotation_evidence"]

    # The two that make a reading checkable against its protocol: which control it was
    # measured against, and which comparator decided.
    assert "arms" in required
    assert "comparator" in required
    # Eligible and scored are separate counts because one "n" would hide which of the two
    # moved, and the protocol's coverage falsifier fires on exactly that difference.
    assert {"eligible_rows", "scored_rows"} <= set(required)


def test_the_evidence_family_name_is_not_also_a_measurement_kind() -> None:
    """Two `rotation`-ish names now exist and they name different things.

    `rotation` is an evidence *family* in the ablation; `rotation_evidence` is the artifact
    *kind* this runner covers. Passing one where the other belongs must be refused rather
    than half-checked, which is the failure a shared prefix invites.
    """

    with pytest.raises(PreflightError, match="Unknown measurement kind"):
        run_measurement_preflight(_document(), "rotation")
