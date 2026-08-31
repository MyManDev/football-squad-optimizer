"""The shadow calibration report contract: internal-only, honest by construction."""

import json
from pathlib import Path

import pytest

from squadopt.experiments.shadow_calibration import PREREG_GATES
from squadopt.experiments.shadow_report import (
    LOCKED_HOLDOUT_SEASON,
    PREREG_GATE_FAMILIES,
    SHADOW_CALIBRATION_CONTRACT_V1,
    SHADOW_CALIBRATION_CONTRACT_V2,
    SHADOW_CALIBRATION_CONTRACT_VERSION,
    ShadowCalibrationReport,
    ShadowExecutionMetadata,
    ShadowGateResult,
    ShadowReportError,
    ShadowResidualSource,
    load_shadow_report,
    read_shadow_report,
    replay_identity_of,
    report_to_dict,
    write_shadow_report,
    write_shadow_report_once,
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
        "gate_results": (
            ShadowGateResult(
                gate="player_coverage_pooled",
                passes=True,
                observed=0.905,
                threshold="|coverage - 0.90| <= 0.03",
            ),
        ),
        "shadow_status": "calibrated_internal",
        "reasons": (),
        "provenance_fingerprints": {"repository_commit": "93fde86"},
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
    failing = ShadowGateResult(
        gate="squad_pit_location",
        passes=False,
        observed=0.31,
        threshold="mean PIT in [0.43, 0.57]",
    )
    with pytest.raises(ShadowReportError, match="every pre-registered gate"):
        _report(gate_results=(_report().gate_results[0], failing))


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


# --- the v2 contract -------------------------------------------------------------
#
# v1 above is left exactly as it was. Everything below is about the version that adds
# the completeness and status-consistency rules, and about reading a recorded document
# back without changing what it says.

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_RECORDED_V1 = _REPOSITORY_ROOT / "docs" / "shadow_calibration_in_season_corrected.json"
_PRE_EXECUTION_V1 = _REPOSITORY_ROOT / "docs" / "shadow_calibration_in_season.json"


def _passing(family: str) -> ShadowGateResult:
    return ShadowGateResult(
        gate=f"{family}_measured",
        passes=True,
        observed=0.5,
        threshold="the pre-registered band",
    )


def _v2(**overrides: object) -> ShadowCalibrationReport:
    """A complete, passing v2 report: the full protocol declared and answered."""

    values: dict[str, object] = {
        "contract_version": SHADOW_CALIBRATION_CONTRACT_V2,
        "declared_gates": PREREG_GATE_FAMILIES,
        "gate_results": tuple(_passing(family) for family in PREREG_GATE_FAMILIES),
        "point_estimate": None,
    }
    values.update(overrides)
    return _report(**values)


def test_the_default_contract_version_is_still_v1() -> None:
    """A runner that says nothing keeps writing the bytes its artifacts already hold."""

    assert SHADOW_CALIBRATION_CONTRACT_VERSION == SHADOW_CALIBRATION_CONTRACT_V1
    assert _report().contract_version == SHADOW_CALIBRATION_CONTRACT_V1


def test_the_runner_and_the_contract_name_one_gate_set() -> None:
    """Two lists of the same pre-registered families are two lists that can drift."""

    assert PREREG_GATES is PREREG_GATE_FAMILIES


def test_a_v1_report_may_not_declare_gates() -> None:
    """v1 never checked a declaration, so a v1 document may not appear to carry one."""

    with pytest.raises(ShadowReportError, match="frozen at what its artifacts"):
        _report(declared_gates=PREREG_GATE_FAMILIES)


def test_an_unknown_contract_version_is_refused() -> None:
    with pytest.raises(ShadowReportError, match="contract_version must be one of"):
        _report(contract_version="shadow_calibration_report_v3")


def test_a_v2_report_must_declare_the_gate_families_it_answers() -> None:
    with pytest.raises(ShadowReportError, match="must declare which"):
        _v2(declared_gates=())


def test_a_v2_declaration_that_omits_a_family_is_refused_whatever_the_status() -> None:
    """The completeness rule is not only a rule about passing.

    A report that declares two families of three and abstains still tells a reader it
    was asked two questions. The protocol asked three.
    """

    two_thirds = PREREG_GATE_FAMILIES[1:]
    with pytest.raises(ShadowReportError, match="omits pre-registered families"):
        _v2(
            declared_gates=two_thirds,
            gate_results=tuple(_passing(family) for family in two_thirds),
            shadow_status="abstained",
            reasons=("P1 was not evaluated.",),
        )


def test_a_measured_gate_outside_the_declared_families_is_refused() -> None:
    with pytest.raises(ShadowReportError, match="matches no declared family"):
        _v2(
            gate_results=(
                *(_passing(family) for family in PREREG_GATE_FAMILIES),
                _passing("S3_squad_upper_tail"),
            )
        )


def test_a_declared_family_with_no_entry_cannot_be_calibrated_internal() -> None:
    """Declaring the protocol is not answering it."""

    with pytest.raises(ShadowReportError, match="has no entry in gate_results"):
        _v2(gate_results=tuple(_passing(f) for f in PREREG_GATE_FAMILIES[:2]))


def test_a_declared_family_with_no_entry_may_abstain() -> None:
    """The same report, filed honestly, is a legitimate abstention."""

    report = _v2(
        gate_results=tuple(_passing(f) for f in PREREG_GATE_FAMILIES[:2]),
        shadow_status="abstained",
        reasons=("S2 was pre-registered but not evaluated.",),
    )
    assert report.shadow_status == "abstained"


def test_a_gate_that_failed_as_measured_forces_the_failed_status() -> None:
    """A measured negative may not be filed as an abstention."""

    failing = ShadowGateResult(
        gate="S1_squad_pit_location",
        passes=False,
        observed=0.31,
        threshold="mean PIT in [0.43, 0.57]",
    )
    gates = (_passing(PREREG_GATE_FAMILIES[0]), failing, _passing(PREREG_GATE_FAMILIES[2]))
    with pytest.raises(ShadowReportError, match="failed as measured"):
        _v2(gate_results=gates, shadow_status="abstained", reasons=("thin sample",))
    assert _v2(gate_results=gates, shadow_status="failed", reasons=("S1 failed.",)).gate_results


def test_failed_without_a_measured_failure_is_refused() -> None:
    """An abstention may not be dressed up as a failure it did not measure."""

    with pytest.raises(ShadowReportError, match="names at least one gate that failed"):
        _v2(shadow_status="failed", reasons=("the sample was thin",))


def test_an_unevaluable_gate_abstains_rather_than_failing() -> None:
    """No observation is missing evidence, not a negative result."""

    unevaluable = ShadowGateResult(
        gate="S2_squad_lower_tail",
        passes=False,
        observed=None,
        threshold="below-q10 rate in [0.04, 0.16]",
    )
    gates = (_passing(PREREG_GATE_FAMILIES[0]), _passing(PREREG_GATE_FAMILIES[1]), unevaluable)
    report = _v2(
        gate_results=gates,
        shadow_status="abstained",
        reasons=("S2 could not be read.",),
    )
    assert report.shadow_status == "abstained"
    with pytest.raises(ShadowReportError, match="names at least one gate that failed"):
        _v2(gate_results=gates, shadow_status="failed", reasons=("S2 could not be read.",))


def test_a_bare_string_declaration_is_refused() -> None:
    """A string is a sequence of characters, and would shatter into one family each."""

    with pytest.raises(ShadowReportError, match="not a single string"):
        _v2(declared_gates="S1_squad_pit_location")


def test_a_blank_or_repeated_declared_family_is_refused() -> None:
    with pytest.raises(ShadowReportError, match="non-empty name"):
        _v2(declared_gates=(*PREREG_GATE_FAMILIES, "   "))
    with pytest.raises(ShadowReportError, match="repeats a family"):
        _v2(declared_gates=(*PREREG_GATE_FAMILIES, PREREG_GATE_FAMILIES[0]))


def test_only_a_v2_document_carries_the_declaration_key() -> None:
    """Serialization is what keeps a recorded v1 document byte-identical."""

    assert "declared_gates" not in report_to_dict(_report())
    assert report_to_dict(_v2())["declared_gates"] == list(PREREG_GATE_FAMILIES)


def test_a_v2_report_round_trips_through_the_loader() -> None:
    report = _v2()
    assert load_shadow_report(report_to_dict(report)) == report


def test_the_loader_refuses_a_document_with_unknown_fields() -> None:
    """A newer contract's extra rules cannot be checked by an older reader."""

    document = report_to_dict(_v2())
    document["confidence_interval"] = [0.1, 0.9]
    with pytest.raises(ShadowReportError, match="unrecognised fields"):
        load_shadow_report(document)


def test_the_loader_refuses_a_document_with_a_field_missing() -> None:
    document = report_to_dict(_v2())
    del document["sample_size"]
    with pytest.raises(ShadowReportError, match="missing required field 'sample_size'"):
        load_shadow_report(document)


def test_the_loader_refuses_a_boolean_where_a_number_belongs() -> None:
    """True is an int in Python and would otherwise load as a coverage of 1.0."""

    document = report_to_dict(_v2())
    document["point_estimate"] = True
    with pytest.raises(ShadowReportError, match="must be a number or null"):
        load_shadow_report(document)


def test_the_recorded_v1_measurement_still_loads_and_reserializes_byte_for_byte() -> None:
    """The point of versioning: the committed artifact is not changed by v2 existing."""

    raw = _RECORDED_V1.read_text(encoding="utf-8")
    report, digest = read_shadow_report(_RECORDED_V1)
    assert report.contract_version == SHADOW_CALIBRATION_CONTRACT_V1
    assert report.shadow_status == "abstained"
    assert report.declared_gates == ()
    assert len(digest) == 64
    again = json.dumps(report_to_dict(report), indent=2, sort_keys=True, allow_nan=False) + "\n"
    assert again == raw


def test_the_earliest_v1_artifact_is_refused_rather_than_completed() -> None:
    """It predates the execution block; loading it would mean inventing one."""

    with pytest.raises(ShadowReportError, match="no execution block"):
        read_shadow_report(_PRE_EXECUTION_V1)


def test_create_once_writes_then_replays_then_refuses_a_different_measurement(
    tmp_path: Path,
) -> None:
    target = tmp_path / "squad.json"
    report = _v2()
    assert write_shadow_report_once(report, target) == "written"
    assert write_shadow_report_once(report, target) == "replay"

    later = _v2(generated_at_utc="2026-08-29T09:00:00+00:00")
    assert write_shadow_report_once(later, target) == "replay"

    different = _v2(sample_size=36)
    with pytest.raises(ShadowReportError, match="already holds a different measurement"):
        write_shadow_report_once(different, target)


def test_create_once_refuses_the_published_site_tree(tmp_path: Path) -> None:
    published = tmp_path / "web" / "public" / "squad.json"
    with pytest.raises(ShadowReportError, match="published site tree"):
        write_shadow_report_once(_v2(), published)


def test_replay_identity_excludes_only_the_wall_clock() -> None:
    document = report_to_dict(_v2())
    identity = replay_identity_of(document)
    assert "generated_at_utc" not in identity
    execution = identity["execution"]
    assert isinstance(execution, dict)
    assert set(execution) == {"deterministic_seed", "warnings"}
    assert identity["gate_results"] == document["gate_results"]
    assert identity["declared_gates"] == document["declared_gates"]
