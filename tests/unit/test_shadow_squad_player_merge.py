"""Merging P1 into the full protocol: same export, or no merge at all.

The player-level runner measures P1 and records it. The squad instrument measures S1
and S2. The pre-registration's verdict is about all three, so something has to put them
in one report — and the dangerous version of that is a merge that quietly averages two
different measurements. These tests are about the refusals that make the merge safe,
and about the difference between evidence that is missing and evidence that is
negative.
"""

import hashlib
import json
from pathlib import Path

import pytest

from squadopt.experiments.shadow_report import (
    PREREG_GATE_FAMILIES,
    SHADOW_CALIBRATION_CONTRACT_V2,
    ShadowCalibrationReport,
    ShadowExecutionMetadata,
    ShadowGateResult,
    ShadowReportError,
    ShadowResidualSource,
    report_to_dict,
    write_shadow_report,
)
from squadopt.experiments.shadow_squad_calibration import (
    PlayerEvidence,
    SquadShadowConfig,
    SquadShadowError,
    combine_full_protocol,
    load_bound_player_report,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_RECORDED = _REPOSITORY_ROOT / "docs" / "shadow_calibration_in_season_corrected.json"

#: The digest of the residual export the corrected player measurement was bound to.
#: Written out rather than read from the artifact under test: a check that reads its
#: expectation from the thing it is checking cannot fail.
_RESIDUAL_SHA = "17f88e6e75618adc01ec6357317a6849bdb053e7eeed1cd6627c8eceab15fc7a"


def _source(**overrides: object) -> ShadowResidualSource:
    values: dict[str, object] = {
        "export_label": "in_season_carry_over_blend",
        "model_name": "squadopt-deterministic-baseline",
        "model_version": "in-season-carry-over-v1",
        "feature_contract_version": "in-season-carry-over-features-v1",
        "table_sha256": _RESIDUAL_SHA,
        "seasons": ("2021-22", "2022-23", "2023-24", "2024-25"),
        "cutoff_fold_id": "2023-24-gw38",
    }
    values.update(overrides)
    return ShadowResidualSource(**values)  # type: ignore[arg-type]


def _execution() -> ShadowExecutionMetadata:
    return ShadowExecutionMetadata(
        started_at_utc="2026-08-29T09:00:00+00:00",
        completed_at_utc="2026-08-29T09:00:20+00:00",
        elapsed_seconds=20.0,
        deterministic_seed=11,
        warnings=(),
    )


def _player_report(path: Path, **overrides: object) -> Path:
    """A stand-in player-level artifact, written the way the real runner writes one."""

    values: dict[str, object] = {
        "generated_at_utc": "2026-08-28T17:24:27+00:00",
        "execution": _execution(),
        "horizon": 1,
        "residual_source": _source(),
        "sample_size": 37,
        "point_estimate": 0.906,
        "calibration_diagnostics": {"pooled_empirical_coverage": 0.906},
        "interval_diagnostics": {"pooled_mean_interval_width": 6.05},
        "gate_results": (
            ShadowGateResult(
                gate="P1_player_coverage_pooled",
                passes=True,
                observed=0.906,
                threshold="|coverage - 0.9| <= 0.03",
            ),
        ),
        "shadow_status": "abstained",
        "reasons": ("S1 and S2 belong to the squad instrument.",),
        "provenance_fingerprints": {
            "repository_commit": "82711b9",
            "working_tree_dirty": "false",
        },
    }
    values.update(overrides)
    write_shadow_report(ShadowCalibrationReport(**values), path)  # type: ignore[arg-type]
    return path


def _squad_gates(*, pit: float = 0.50, tail: float = 0.108) -> tuple[ShadowGateResult, ...]:
    return (
        ShadowGateResult(
            gate="S1_squad_pit_location",
            passes=0.43 <= pit <= 0.57,
            observed=pit,
            threshold="mean PIT in [0.43, 0.57]",
        ),
        ShadowGateResult(
            gate="S2_squad_lower_tail",
            passes=0.04 <= tail <= 0.16,
            observed=tail,
            threshold="below-q10 rate in [0.04, 0.16]",
        ),
    )


def _merge(player: PlayerEvidence, **overrides: object) -> ShadowCalibrationReport:
    values: dict[str, object] = {
        "generated_at_utc": "2026-08-29T09:00:00+00:00",
        "execution": _execution(),
        "residual_source": _source(),
        "player": player,
        "squad_gates": _squad_gates(),
        "calibration_diagnostics": {"mean_probability_integral_transform": 0.50},
        "interval_diagnostics": {"mean_pit_bootstrap_low": 0.44},
        "evaluation_folds": 37,
        "provenance_fingerprints": {"repository_commit": "6ba9990"},
    }
    values.update(overrides)
    return combine_full_protocol(**values)  # type: ignore[arg-type]


def _evidence(path: Path, **overrides: object) -> PlayerEvidence:
    """A synthetic record, so the digest pin is explicitly waived rather than met."""

    settings: dict[str, object] = {"expect_sha256": None, "expect_fingerprints": {}}
    settings.update(overrides)
    return load_bound_player_report(path, _source(), SquadShadowConfig(), **settings)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# The binding: the same export, or nothing
# --------------------------------------------------------------------------------------


def test_the_recorded_measurement_is_accepted_and_carries_its_three_p1_cells() -> None:
    """The real committed artifact, matched against what this run believes it is."""

    evidence = _evidence(_RECORDED)
    assert [gate.gate for gate in evidence.gates] == [
        "P1_player_coverage_pooled",
        "P1_player_coverage_single",
        "P1_player_coverage_double_plus",
    ]
    assert all(gate.passes for gate in evidence.gates)
    assert evidence.abstentions == ()
    assert evidence.sample_size == 37
    assert evidence.provenance["player_report_status"] == "abstained"
    assert evidence.provenance["player_report_file"] == _RECORDED.name
    assert len(evidence.provenance["player_report_sha256"]) == 64
    # Its own numbers survive the merge, under names that say whose they are.
    assert evidence.calibration_diagnostics["player_pooled_empirical_coverage"] == pytest.approx(
        0.9061703988138236
    )


@pytest.mark.parametrize(
    ("field", "other"),
    [
        ("export_label", "archive_form_window"),
        ("model_name", "squadopt-archive-baseline"),
        ("model_version", "form-window-8-v1"),
        ("feature_contract_version", "form-window-features-v1"),
        ("table_sha256", "cd" * 32),
        ("seasons", ("2021-22", "2022-23", "2023-24")),
        ("cutoff_fold_id", "2022-23-gw38"),
    ],
)
def test_a_player_report_about_a_different_export_is_refused_field_by_field(
    field: str, other: object
) -> None:
    """Every field, not only the digest.

    A different cutoff or a different season list is a different split even when the
    residual table is byte for byte the same one, and a merged report that averaged
    two splits would read as one measurement of something nobody ran.
    """

    with pytest.raises(SquadShadowError, match=f"different {field}"):
        load_bound_player_report(
            _RECORDED,
            _source(**{field: other}),
            SquadShadowConfig(),
            expect_sha256=None,
            expect_fingerprints={},
        )


def test_a_missing_player_report_file_is_an_error_not_an_empty_merge(tmp_path: Path) -> None:
    with pytest.raises(ShadowReportError, match="could not be read"):
        _evidence(tmp_path / "absent.json")


# --------------------------------------------------------------------------------------
# Missing evidence abstains; negative evidence fails
# --------------------------------------------------------------------------------------


def test_a_report_carrying_no_p1_gate_abstains_rather_than_passing(tmp_path: Path) -> None:
    path = _player_report(tmp_path / "no_p1.json", gate_results=())
    evidence = _evidence(path)
    assert evidence.gates == ()
    assert any("carries no P1_player_coverage gate" in reason for reason in evidence.abstentions)

    report = _merge(evidence)
    assert report.shadow_status == "abstained"
    assert any("P1" in reason for reason in report.reasons)


def test_a_p1_gate_with_no_observation_abstains(tmp_path: Path) -> None:
    """An unread gate is missing evidence, not a negative result."""

    unread = ShadowGateResult(
        gate="P1_player_coverage_double_plus",
        passes=False,
        observed=None,
        threshold="|coverage - 0.9| <= 0.05 over >= 200 rows",
    )
    path = _player_report(tmp_path / "unread.json", gate_results=(unread,))
    evidence = _evidence(path)
    assert any("carries no observation" in reason for reason in evidence.abstentions)
    assert _merge(evidence).shadow_status == "abstained"


def test_a_thin_player_population_abstains(tmp_path: Path) -> None:
    path = _player_report(tmp_path / "thin.json", sample_size=12)
    evidence = _evidence(path)
    assert any("below the pre-registered floor of 30" in r for r in evidence.abstentions)
    assert _merge(evidence).shadow_status == "abstained"


@pytest.mark.parametrize(
    ("fingerprints", "expected"),
    [
        ({"repository_commit": "82711b9"}, "does not say whether its working tree"),
        (
            {"repository_commit": "82711b9", "working_tree_dirty": "true"},
            "modified working tree",
        ),
        ({"working_tree_dirty": "false"}, "names no repository commit"),
    ],
)
def test_unprovable_player_provenance_abstains(
    tmp_path: Path, fingerprints: dict[str, str], expected: str
) -> None:
    """Missing provenance is an abstention, and never an assumption that it was fine."""

    path = _player_report(tmp_path / "provenance.json", provenance_fingerprints=fingerprints)
    evidence = _evidence(path)
    assert any(expected in reason for reason in evidence.abstentions)
    assert _merge(evidence).shadow_status == "abstained"


def test_a_failed_p1_gate_fails_the_whole_protocol(tmp_path: Path) -> None:
    """A recorded negative is carried through, not filed as something softer."""

    failing = ShadowGateResult(
        gate="P1_player_coverage_pooled",
        passes=False,
        observed=0.71,
        threshold="|coverage - 0.9| <= 0.03",
    )
    path = _player_report(
        tmp_path / "failed.json",
        gate_results=(failing,),
        shadow_status="failed",
        reasons=("P1 failed as measured.",),
    )
    evidence = _evidence(path)
    assert evidence.abstentions == ()

    report = _merge(evidence)
    assert report.shadow_status == "failed"
    assert any("failed as measured" in reason for reason in report.reasons)


# --------------------------------------------------------------------------------------
# The merged verdict
# --------------------------------------------------------------------------------------


def test_the_full_protocol_passes_only_when_all_three_families_pass(tmp_path: Path) -> None:
    evidence = _evidence(_player_report(tmp_path / "clean.json"))
    report = _merge(evidence)
    assert report.shadow_status == "calibrated_internal"
    assert report.contract_version == SHADOW_CALIBRATION_CONTRACT_V2
    assert report.declared_gates == PREREG_GATE_FAMILIES
    assert [gate.gate for gate in report.gate_results] == [
        "P1_player_coverage_pooled",
        "S1_squad_pit_location",
        "S2_squad_lower_tail",
    ]
    # The evidence's own provenance travels with it: a reader can find the artifact
    # this verdict merged, and check that it is still the same bytes.
    assert report.provenance_fingerprints["player_report_sha256"]
    assert report.provenance_fingerprints["repository_commit"] == "6ba9990"


def test_one_failing_squad_gate_fails_the_merged_verdict(tmp_path: Path) -> None:
    evidence = _evidence(_player_report(tmp_path / "clean.json"))
    report = _merge(evidence, squad_gates=_squad_gates(pit=0.31))
    assert report.shadow_status == "failed"


def test_the_merge_cannot_be_called_without_player_evidence() -> None:
    """The defect this signature exists to prevent.

    An earlier version took a sequence of player gates, and the runner passed an empty
    tuple: P1 was then permanently unanswered while the two squad gates looked like a
    protocol. A caller that has not loaded a bound player report can no longer call
    this function at all.
    """

    with pytest.raises(TypeError):
        combine_full_protocol(  # type: ignore[call-arg]
            generated_at_utc="2026-08-29T09:00:00+00:00",
            execution=_execution(),
            residual_source=_source(),
            squad_gates=_squad_gates(),
            calibration_diagnostics={},
            interval_diagnostics={},
            evaluation_folds=37,
            provenance_fingerprints={"repository_commit": "6ba9990"},
        )


def test_the_merged_report_serializes_as_v2_with_its_declaration(tmp_path: Path) -> None:
    evidence = _evidence(_player_report(tmp_path / "clean.json"))
    document = report_to_dict(_merge(evidence))
    assert document["contract_version"] == SHADOW_CALIBRATION_CONTRACT_V2
    assert document["declared_gates"] == list(PREREG_GATE_FAMILIES)
    # Serializable as it stands: a report that cannot be written is not a record.
    assert json.dumps(document, sort_keys=True, allow_nan=False)


# --------------------------------------------------------------------------------------
# The record is evidence, not testimony
# --------------------------------------------------------------------------------------


def test_a_player_report_at_another_digest_is_refused() -> None:
    """Which recorded measurement P1 comes from is protocol, not a path someone passes.

    Every field of the seven-field binding is a label a hand-written file can carry.
    The digest is the one thing that cannot be reproduced by writing the right strings,
    so the protocol names the bytes it merges.
    """

    load_bound_player_report(
        _RECORDED,
        _source(),
        SquadShadowConfig(),
        expect_sha256=hashlib.sha256(_RECORDED.read_bytes()).hexdigest(),
        expect_fingerprints={},
    )
    with pytest.raises(SquadShadowError, match="not the pre-registered"):
        load_bound_player_report(
            _RECORDED,
            _source(),
            SquadShadowConfig(),
            expect_sha256="0" * 64,
            expect_fingerprints={},
        )


def test_a_player_report_from_another_dataset_snapshot_is_refused() -> None:
    """The residual export is not the only thing two instruments have to share.

    The squad decision and the realized score come from the archive; P1's residuals
    came from an archive too. If those are different snapshots, the merged report is
    an average of two measurements of different data.
    """

    load_bound_player_report(
        _RECORDED,
        _source(),
        SquadShadowConfig(),
        expect_sha256=None,
        expect_fingerprints={"dataset_snapshot_id": "8c97b2adb123863c3dd581e730f1360e89815ac2"},
    )
    with pytest.raises(SquadShadowError, match="different dataset_snapshot_id"):
        load_bound_player_report(
            _RECORDED,
            _source(),
            SquadShadowConfig(),
            expect_sha256=None,
            expect_fingerprints={"dataset_snapshot_id": "some other archive entirely"},
        )


@pytest.mark.parametrize(
    ("observed", "claimed"),
    [(0.4123, True), (0.906, False)],
)
def test_a_record_that_disagrees_with_its_own_numbers_is_refused(
    tmp_path: Path, observed: float, claimed: bool
) -> None:
    """``passes`` is a claim the artifact makes about itself, not evidence.

    Both directions matter. A pass claimed over a coverage of 0.41 would carry a
    failure into the merge as though it were a pass; a failure claimed over 0.906 would
    fail the whole protocol on a gate that met its band. The band is pre-registered, so
    the verdict is recomputed and the record is refused when the two disagree.
    """

    gate = ShadowGateResult(
        gate="P1_player_coverage_pooled",
        passes=claimed,
        observed=observed,
        threshold="|coverage - 0.9| <= 0.03",
    )
    path = _player_report(
        tmp_path / "liar.json",
        gate_results=(gate,),
        shadow_status="failed" if not claimed else "abstained",
        reasons=("recorded",),
    )
    with pytest.raises(SquadShadowError, match="disagrees with its own numbers"):
        _evidence(path)


def test_a_record_without_its_pooled_cell_abstains(tmp_path: Path) -> None:
    """A thin fixture group is not P1.

    The per-group cells are gated only when a group clears its row floor, so a report
    may legitimately carry fewer of them. The pooled coverage is the one cell the
    pre-registration measures unconditionally, and a family answered by a group cell
    alone would let a 200-row corner stand in for the whole gate.
    """

    group = ShadowGateResult(
        gate="P1_player_coverage_double_plus",
        passes=True,
        observed=0.91,
        threshold="|coverage - 0.9| <= 0.05",
    )
    evidence = _evidence(_player_report(tmp_path / "no_pooled.json", gate_results=(group,)))
    assert any("no P1_player_coverage_pooled cell" in reason for reason in evidence.abstentions)
    assert _merge(evidence).shadow_status == "abstained"


def test_a_measured_failure_outside_p1_cannot_be_dropped_by_the_merge(tmp_path: Path) -> None:
    """The filter keeps the P1 cells; it may not quietly discard a recorded negative."""

    path = _player_report(
        tmp_path / "elsewhere.json",
        gate_results=(
            ShadowGateResult(
                gate="P1_player_coverage_pooled",
                passes=True,
                observed=0.906,
                threshold="|coverage - 0.9| <= 0.03",
            ),
            ShadowGateResult(
                gate="S1_squad_pit_location",
                passes=False,
                observed=0.07,
                threshold="mean PIT in [0.43, 0.57]",
            ),
        ),
        shadow_status="failed",
        reasons=("S1 failed as measured.",),
    )
    with pytest.raises(SquadShadowError, match="measured failures"):
        _evidence(path)


def test_a_failed_record_whose_p1_cells_all_pass_is_refused(tmp_path: Path) -> None:
    """Whatever failed in it is not what this merge would carry forward."""

    path = _player_report(
        tmp_path / "failed_elsewhere.json",
        shadow_status="failed",
        reasons=("something outside P1 failed.",),
    )
    with pytest.raises(SquadShadowError, match="carries no failing"):
        _evidence(path)


def test_the_records_own_provenance_travels_into_the_merged_artifact() -> None:
    """A reader of the verdict can find what produced the other half of it."""

    evidence = _evidence(_RECORDED)
    assert evidence.provenance["player_report_dataset_snapshot_id"]
    assert evidence.provenance["player_report_residual_generation_commit"]
    assert evidence.provenance["player_report_model_identity"].startswith(
        "squadopt-deterministic-baseline/"
    )
