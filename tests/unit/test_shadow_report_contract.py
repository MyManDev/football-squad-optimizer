"""The shadow calibration report contract: internal-only, honest by construction."""

import json
from pathlib import Path

import pytest

from squadopt.experiments.shadow_report import (
    LOCKED_HOLDOUT_SEASON,
    PREREG_GATE_FAMILIES,
    SHADOW_CALIBRATION_CONTRACT_VERSION,
    ShadowCalibrationReport,
    ShadowExecutionMetadata,
    ShadowGateResult,
    ShadowReportError,
    ShadowResidualSource,
    report_to_dict,
    write_shadow_report,
)

_SHA = "ab" * 32


def _source(**overrides: object) -> ShadowResidualSource:
    values: dict[str, object] = {
        "export_label": "in_season_carry_over_blend",
        "model_name": "squadopt-deterministic-baseline",
        "model_version": "in-season-carry-over-v1",
        "feature_contract_version": "in-season-carry-over-features-v1",
        "table_sha256": _SHA,
        "seasons": ("2021-22", "2022-23", "2023-24", "2024-25"),
        "cutoff_fold_id": "2023-24-gw38",
    }
    values.update(overrides)
    return ShadowResidualSource(**values)  # type: ignore[arg-type]


def _report(**overrides: object) -> ShadowCalibrationReport:
    values: dict[str, object] = {
        "generated_at_utc": "2026-08-28T12:00:00+00:00",
        "execution": ShadowExecutionMetadata(
            started_at_utc="2026-08-28T12:00:00+00:00",
            completed_at_utc="2026-08-28T12:00:01+00:00",
            elapsed_seconds=1.0,
            deterministic_seed=0,
            warnings=(),
        ),
        "horizon": 1,
        "residual_source": _source(),
        "sample_size": 37,
        "point_estimate": 0.905,
        "calibration_diagnostics": {"empirical_coverage": 0.905, "mean_pit": None},
        "interval_diagnostics": {"mean_width": 6.85},
        "gate_results": tuple(
            ShadowGateResult(
                gate=f"{family}_measured",
                passes=True,
                observed=0.905,
                threshold="the pre-registered band",
            )
            for family in PREREG_GATE_FAMILIES
        ),
        "shadow_status": "calibrated_internal",
        "reasons": (),
        "provenance_fingerprints": {"repository_commit": "93fde86"},
        # A pass must say which gates the protocol required. The fixture declares the
        # whole set, because a report that declares less can no longer claim one.
        "declared_gates": PREREG_GATE_FAMILIES,
    }
    values.update(overrides)
    return ShadowCalibrationReport(**values)  # type: ignore[arg-type]


def test_a_valid_report_round_trips_with_missing_kept_as_null(tmp_path: Path) -> None:
    report = _report()
    out = tmp_path / "shadow" / "report.json"
    write_shadow_report(report, out)
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["contract_version"] == SHADOW_CALIBRATION_CONTRACT_VERSION
    # The unmeasured diagnostic stayed null — missing is not zero.
    assert document["calibration_diagnostics"]["mean_pit"] is None
    assert document["calibration_diagnostics"]["empirical_coverage"] == 0.905
    assert document["execution"]["deterministic_seed"] == 0
    assert document["execution"]["warnings"] == []


def test_execution_metadata_refuses_invalid_provenance() -> None:
    with pytest.raises(ShadowReportError, match="cannot precede"):
        ShadowExecutionMetadata(
            started_at_utc="2026-08-28T12:00:01+00:00",
            completed_at_utc="2026-08-28T12:00:00+00:00",
            elapsed_seconds=1.0,
            deterministic_seed=0,
            warnings=(),
        )
    with pytest.raises(ShadowReportError, match="deterministic_seed"):
        ShadowExecutionMetadata(
            started_at_utc="2026-08-28T12:00:00+00:00",
            completed_at_utc="2026-08-28T12:00:01+00:00",
            elapsed_seconds=1.0,
            deterministic_seed=True,  # type: ignore[arg-type]
            warnings=(),
        )


def test_the_locked_holdout_is_refused_in_residual_provenance() -> None:
    with pytest.raises(ShadowReportError, match="locked holdout"):
        _source(seasons=("2024-25", LOCKED_HOLDOUT_SEASON))


def test_a_missing_manifest_fingerprint_is_refused() -> None:
    with pytest.raises(ShadowReportError, match="SHA-256"):
        _source(table_sha256="not-a-digest")


def test_multi_week_horizons_are_refused_until_their_own_prereg() -> None:
    with pytest.raises(ShadowReportError, match="h=1 only"):
        _report(horizon=3)


def test_nan_diagnostics_are_refused_rather_than_serialized() -> None:
    with pytest.raises(ShadowReportError, match="finite float or None"):
        _report(calibration_diagnostics={"empirical_coverage": float("nan")})


def test_abstained_is_distinct_from_failed_and_both_need_reasons() -> None:
    abstained = _report(
        shadow_status="abstained",
        gate_results=(),
        reasons=("fewer than 8 settled gameweeks",),
    )
    failed = _report(
        shadow_status="failed",
        gate_results=(
            ShadowGateResult(
                gate="player_coverage_pooled",
                passes=False,
                observed=0.79,
                threshold="|coverage - 0.90| <= 0.03",
            ),
        ),
        reasons=("gate player_coverage_pooled failed",),
    )
    assert abstained.shadow_status != failed.shadow_status
    with pytest.raises(ShadowReportError, match="reasons"):
        _report(shadow_status="abstained", gate_results=(), reasons=())


def test_calibrated_internal_requires_every_gate_to_pass() -> None:
    passing = _report().gate_results
    failing = ShadowGateResult(
        gate=f"{PREREG_GATE_FAMILIES[1]}_measured",
        passes=False,
        observed=0.31,
        threshold="mean PIT in [0.43, 0.57]",
    )
    # The declaration still covers the protocol, so the only thing left to refuse is
    # the failing gate itself.
    with pytest.raises(ShadowReportError, match="every pre-registered gate"):
        _report(gate_results=(passing[0], failing, passing[2]))


def test_an_unevaluable_gate_cannot_pass() -> None:
    with pytest.raises(ShadowReportError, match="cannot pass"):
        ShadowGateResult(gate="g", passes=True, observed=None, threshold="t")


def test_the_writer_refuses_the_published_site_tree(tmp_path: Path) -> None:
    target = tmp_path / "web" / "public" / "data" / "shadow.json"
    with pytest.raises(ShadowReportError, match="web/public"):
        write_shadow_report(_report(), target)
    assert not target.exists()


def test_serialization_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    write_shadow_report(_report(), first)
    write_shadow_report(_report(), second)
    assert first.read_bytes() == second.read_bytes()
    assert b"\r" not in first.read_bytes()


def test_the_public_site_schema_rejects_a_shadow_report() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema_path = (
        Path(__file__).resolve().parents[2] / "docs" / "contracts" / "ui_view_v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(report_to_dict(_report()), schema)


def test_calibrated_internal_requires_the_declared_set_to_cover_the_protocol() -> None:
    """A report may not declare a subset of the protocol and then pass its own subset.

    The completeness rule lives here rather than in a runner precisely so that a second
    runner inherits it. If the contract only cross-checked declared_gates against
    gate_results, a report could name two of the three families, satisfy both, and read
    as a full pass.
    """

    two_thirds = PREREG_GATE_FAMILIES[1:]
    with pytest.raises(ShadowReportError, match="omits pre-registered families"):
        _report(
            declared_gates=two_thirds,
            gate_results=tuple(
                ShadowGateResult(
                    gate=f"{family}_measured",
                    passes=True,
                    observed=0.5,
                    threshold="the pre-registered band",
                )
                for family in two_thirds
            ),
        )


def test_a_declared_family_with_no_measured_entry_is_refused() -> None:
    """Declaring the protocol is not answering it."""

    with pytest.raises(ShadowReportError, match="has no entry in gate_results"):
        _report(gate_results=_report().gate_results[:2])


def test_a_bare_string_declared_gate_set_is_refused() -> None:
    """A string is a sequence of characters, and would shatter into one family each."""

    with pytest.raises(ShadowReportError, match="not a single string"):
        _report(declared_gates="S1_squad_pit_location")


def test_a_blank_declared_family_name_is_refused() -> None:
    """A whitespace name is as empty as an absent one, and is refused the same way."""

    with pytest.raises(ShadowReportError, match="non-empty name"):
        _report(declared_gates=(*PREREG_GATE_FAMILIES, "   "))


def test_a_report_declaring_nothing_serializes_without_the_key(tmp_path: Path) -> None:
    """Older artifacts must still replay: a report that declares nothing says nothing.

    The two committed shadow artifacts predate ``declared_gates`` and are ``abstained``,
    so omitting the key when it is empty is what keeps their bytes reproducible.
    """

    report = _report(shadow_status="abstained", reasons=("nothing was asked",), declared_gates=())
    document = report_to_dict(report)
    assert "declared_gates" not in document

    out = tmp_path / "older.json"
    write_shadow_report(report, out)
    assert "declared_gates" not in json.loads(out.read_text(encoding="utf-8"))
