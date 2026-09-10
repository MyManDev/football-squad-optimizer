"""Preflight checks for the repository's own measurement artifacts.

The residual-export preflight guards what we *receive*; this module guards what we
*produce*. Every committed measurement report (search traces, grids, frontiers,
audits, rehearsals) claims the same governance invariants — clean-tree provenance,
no locked-holdout access, no automatic promotion, well-formed fingerprints — and a
report that violates them cannot support the claims made on top of it. As with the
export preflight, every violation becomes a named finding and one run reports all of
them at once.
"""

import math
from collections.abc import Mapping, Sequence
from typing import Final

from squadopt.preflight.models import (
    COMMIT_PATTERN,
    SHA256_PATTERN,
    PreflightError,
    PreflightFinding,
    PreflightReport,
)
from squadopt.preflight.validator import _is_utc_timestamp

MEASUREMENT_PREFLIGHT_CONTRACT_VERSION: Final = "measurement_artifact_preflight_v1"

MEASUREMENT_KINDS: Final[Mapping[str, tuple[str, ...]]] = {
    "baseline_bayesopt": (
        "run_fingerprint",
        "recommended_candidate_id",
        "trace",
        "search_space_size",
        "development_fold_count",
    ),
    "policy_grid": (
        "contract_version",
        "cells",
        "true_best_candidate_id",
        "search_efficiency",
        "grid_size",
    ),
    "scenario_bayesopt": (
        "run_fingerprint",
        "recommended_candidate_id",
        "trace",
        "residual_input",
        "evaluated_fold_count",
    ),
    "risk_frontier": ("contract_version", "frontier", "anchor", "residual_input"),
    "scenario_audit": ("contract_version", "decision_level", "player_level", "rows"),
    "multi_gw_rehearsal": (
        "contract_version",
        "windows",
        "mean_planning_advantage_points",
        "projection_rule",
    ),
    "control_uncertainty": (
        "position_level",
        "player_adaptive",
        "calibration_seasons",
        "evaluation_season",
    ),
    # The rotation lane's readings. `arms` and `comparator` are required because the whole
    # protocol turns on which control a result was measured against -- a reading that does
    # not name it cannot be checked against `rotation_evidence_prereg.md`. `eligible_rows`
    # and `scored_rows` are separate fields for the same reason they are separate counts in
    # the artifact: one "n" hides which of the two moved, and the protocol's coverage
    # falsifier fires on exactly that difference.
    "rotation_evidence": (
        "contract_version",
        "arms",
        "comparator",
        "target",
        "eligible_rows",
        "scored_rows",
    ),
}

# Required declarations follow the existing producers, not a blanket policy retrofitted
# onto descriptive reports. Fields absent from a kind's tuple are optional; whenever
# supplied, including inside nested diagnostics, they must have the declared boolean value.
MEASUREMENT_DECLARATIONS: Final[Mapping[str, tuple[str, ...]]] = {
    "baseline_bayesopt": ("locked_holdout_accessed", "automatic_promotion", "recommendation_only"),
    "policy_grid": ("locked_holdout_accessed", "automatic_promotion", "recommendation_only"),
    "scenario_bayesopt": ("locked_holdout_accessed", "automatic_promotion", "recommendation_only"),
    "risk_frontier": ("locked_holdout_accessed", "automatic_promotion", "recommendation_only"),
    "scenario_audit": ("locked_holdout_accessed",),
    "multi_gw_rehearsal": ("locked_holdout_accessed", "recommendation_only"),
    "control_uncertainty": ("locked_holdout_accessed",),
    "rotation_evidence": ("locked_holdout_accessed",),
}

_DECLARATION_CHECKS: Final = {
    "locked_holdout_accessed": (False, "artifact_no_holdout_access"),
    "automatic_promotion": (False, "artifact_no_automatic_promotion"),
    "recommendation_only": (True, "artifact_recommendation_only"),
}


def _finding(check: str, passed: bool, detail: str) -> PreflightFinding:
    return PreflightFinding(check=check, passed=passed, detail=detail)


def _walk(value: object, path: str) -> list[tuple[str, object]]:
    items: list[tuple[str, object]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            items.extend(_walk(item, f"{path}.{key}" if path else str(key)))
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        for index, item in enumerate(value):
            items.extend(_walk(item, f"{path}[{index}]"))
    else:
        items.append((path, value))
    return items


def _declarations(value: object, name: str, path: str = "") -> list[tuple[str, object]]:
    """Include container-valued declarations too: an empty mapping is not false."""

    found: list[tuple[str, object]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            location = f"{path}.{key}" if path else str(key)
            if key == name:
                found.append((location, item))
            found.extend(_declarations(item, name, location))
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        for index, item in enumerate(value):
            found.extend(_declarations(item, name, f"{path}[{index}]"))
    return found


def _check_declaration(
    document: Mapping[str, object], kind: str, name: str, expected: bool, check: str
) -> PreflightFinding:
    declarations = _declarations(document, name)
    required = name in MEASUREMENT_DECLARATIONS[kind]
    missing = required and name not in document
    violations = [path for path, value in declarations if value is not expected]
    if missing or violations:
        detail = (
            f"Missing required root declaration {name!r} for kind {kind!r}. " if missing else ""
        )
        if violations:
            detail += f"{name} must be {expected!r} at: {violations[:5]!r}."
        return _finding(check, False, detail.strip())
    if not declarations:
        return _finding(
            check,
            True,
            f"{name} is optional for kind {kind!r} and undeclared; "
            "this check asserts no evidence about the absent declaration.",
        )
    return _finding(
        check,
        True,
        f"{'Required root and all' if required else 'All supplied'} {name} "
        f"declarations are {expected!r} ({len(declarations)} checked).",
    )


def check_measurement_artifact(
    document: Mapping[str, object],
    kind: str,
) -> tuple[PreflightFinding, ...]:
    """Check one measurement artifact's governance invariants and shape."""

    if not isinstance(document, Mapping):
        raise PreflightError("document must be a mapping.")
    if kind not in MEASUREMENT_KINDS:
        raise PreflightError(
            f"Unknown measurement kind {kind!r}; known kinds: {sorted(MEASUREMENT_KINDS)!r}."
        )
    findings: list[PreflightFinding] = []

    required = MEASUREMENT_KINDS[kind]
    missing = [name for name in required if name not in document]
    findings.append(
        _finding(
            "artifact_required_fields",
            not missing,
            f"All required fields for kind {kind!r} are present."
            if not missing
            else f"Missing required fields for kind {kind!r}: {missing!r}.",
        )
    )

    provenance = document.get("provenance")
    if not isinstance(provenance, Mapping):
        findings.append(
            _finding(
                "artifact_provenance_block",
                False,
                "The artifact lacks a provenance mapping.",
            )
        )
    else:
        findings.append(
            _finding("artifact_provenance_block", True, "A provenance mapping is present.")
        )
        commit = provenance.get("repository_commit")
        commit_ok = isinstance(commit, str) and bool(COMMIT_PATTERN.match(commit))
        findings.append(
            _finding(
                "artifact_repository_commit",
                commit_ok,
                "provenance.repository_commit is a full lowercase commit hash."
                if commit_ok
                else f"provenance.repository_commit is invalid: {commit!r}.",
            )
        )
        dirty = provenance.get("working_tree_dirty")
        findings.append(
            _finding(
                "artifact_clean_tree",
                dirty is False,
                "The artifact was produced from a clean tree."
                if dirty is False
                else "The artifact records a dirty working tree; its provenance "
                "cannot be tied to one commit.",
            )
        )

    created = document.get("created_utc")
    if created is not None:
        created_ok = isinstance(created, str) and _is_utc_timestamp(created)
        findings.append(
            _finding(
                "artifact_created_utc",
                created_ok,
                "created_utc is an explicit UTC timestamp."
                if created_ok
                else f"created_utc is not an explicit UTC timestamp: {created!r}.",
            )
        )

    leaves = _walk(document, "")
    for name, (expected, check) in _DECLARATION_CHECKS.items():
        findings.append(_check_declaration(document, kind, name, expected, check))

    bad_digests: list[str] = []
    for path, value in leaves:
        leaf = path.split(".")[-1].split("[")[0]
        if leaf.endswith("fingerprint") or leaf.endswith("sha256"):
            if value is None:
                continue
            if not isinstance(value, str) or not SHA256_PATTERN.match(value):
                bad_digests.append(path)
    findings.append(
        _finding(
            "artifact_digest_formats",
            not bad_digests,
            "Every fingerprint/sha256 field is a lowercase 64-hex digest or null."
            if not bad_digests
            else f"Malformed digest fields: {bad_digests[:5]!r}.",
        )
    )

    non_finite = [
        path
        for path, value in leaves
        if isinstance(value, float) and not isinstance(value, bool) and not math.isfinite(value)
    ]
    findings.append(
        _finding(
            "artifact_finite_numbers",
            not non_finite,
            "Every numeric leaf is finite."
            if not non_finite
            else f"Non-finite numeric leaves: {non_finite[:5]!r}.",
        )
    )

    return tuple(findings)


def run_measurement_preflight(
    document: Mapping[str, object],
    kind: str,
    *,
    artifact_label: str = "measurement_artifact",
) -> PreflightReport:
    """Run every measurement-artifact check and return one complete report."""

    return PreflightReport(
        artifact_label=artifact_label,
        findings=check_measurement_artifact(document, kind),
    )
