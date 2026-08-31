"""Adversarial pass over the squad-gate verdict contract and its publication boundary.

Three claims are attacked here, and nothing else:

* **A partial protocol cannot pass.** ``ShadowCalibrationReport`` — not a runner, not a
  docstring — must refuse ``calibrated_internal`` for any gate set that does not answer
  every family the report declares *and* every family the pre-registration fixed, and
  the family rule must be exact-or-underscore-prefix so a typo drops a gate loudly.
  This is the ``v2`` contract: it is where the declaration and the completeness rule
  live. ``v1`` keeps the meaning its two recorded artifacts were written under and may
  not carry a declaration at all, so every attack below that hands a report a
  ``declared_gates`` tuple builds a v2 report — attacking v1 with a v2 field would only
  ever measure the version freeze.
* **The boundary holds in both directions.** A squad report may not validate against the
  member-facing ``ui_view_v1`` contract, may not carry probability prose, may not be
  written under ``web/public``, and may not widen the strategy catalogue's envelope.
* **A recorded result is not overwritten.** ``write_shadow_report_once`` publishes once,
  replays an identical measurement, refuses a different one, and leaves no residue —
  including under concurrent writers.

Where an attack succeeds, the test below documents the behaviour that *actually* exists
and says so in its name and docstring; it never asserts the guarantee the code does not
provide. The attacks on the completeness rule that once found holes — a self-declared
subset, a whitespace family, a truncated family name, a bare string — are now assertions
that the contract refuses them, and each keeps the explanation of why that matters. The
two ``FINDING``-named cases that remain are the site-tree guard's casing rule and the
publishable-name meta-gate's scope, and they are still open.

Every fixture is synthetic. Nothing here reads an archive, a residual export, or any
2025-26 file, and the only production behaviour replaced is ``_read_fold`` — the
solver-and-scenario step — so that the *real* gate ids, threshold prose, diagnostic
names and verdict still come from the module under review.
"""

import itertools
import json
import re
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import pytest

from squadopt.application.strategies import (
    PUBLISHABLE_FIELDS,
    CandidateConstraints,
    EvidenceStatus,
    RankingCriterion,
    Strategy,
    StrategyConfigurationError,
)
from squadopt.application.strategies.catalog import FORBIDDEN_FIELD_PATTERN
from squadopt.experiments import shadow_squad_calibration as squad
from squadopt.experiments.shadow_calibration import PREREG_GATES
from squadopt.experiments.shadow_report import (
    PREREG_GATE_FAMILIES,
    SHADOW_CALIBRATION_CONTRACT_V1,
    SHADOW_CALIBRATION_CONTRACT_V2,
    SHADOW_CALIBRATION_CONTRACT_VERSION,
    ShadowCalibrationReport,
    ShadowExecutionMetadata,
    ShadowGateResult,
    ShadowReportError,
    ShadowResidualSource,
    replay_identity_of,
    report_to_dict,
    write_shadow_report_once,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
COMMITTED_ARTIFACTS = (
    REPOSITORY_ROOT / "docs" / "shadow_calibration_in_season.json",
    REPOSITORY_ROOT / "docs" / "shadow_calibration_in_season_corrected.json",
)
_SHA = "ab" * 32

#: The published envelope as it stands before any squad verdict exists. Written out
#: rather than imported so that a widening shows up here as a diff, not as a pass.
_PUBLISHED_ENVELOPE = frozenset(
    {
        "moves",
        "expected_own_points",
        "expected_gap_vs_rival",
        "expected_points_cost",
        "overlap_count",
        "captain_agreement",
        "difference_makers",
        "solver_status",
        "optimality_gap",
    }
)

#: The site guard's own words (``tests/unit/test_public_probability_guards.py``) plus the
#: percent sign: an internal squad artifact may not read as member-facing probability
#: prose even by accident. The Turkish word is spelled with dots for the dotless i.
_MEMBER_FACING_PROSE = re.compile(r"olas.l.k|\bP\(|%", re.IGNORECASE)


# --- builders -------------------------------------------------------------------------


def _execution(**overrides: object) -> ShadowExecutionMetadata:
    values: dict[str, object] = {
        "started_at_utc": "2026-08-28T12:00:00+00:00",
        "completed_at_utc": "2026-08-28T12:00:01+00:00",
        "elapsed_seconds": 1.0,
        "deterministic_seed": 11,
        "warnings": (),
    }
    values.update(overrides)
    return ShadowExecutionMetadata(**values)  # type: ignore[arg-type]


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


def _gate(
    name: str, *, passes: bool = True, observed: float = 0.5, threshold: str = "bound"
) -> ShadowGateResult:
    return ShadowGateResult(gate=name, passes=passes, observed=observed, threshold=threshold)


def _p1_sub_gates() -> tuple[ShadowGateResult, ...]:
    """P1 as the committed artifacts actually measure it: pooled and per fixture group."""

    return (
        _gate("P1_player_coverage_pooled", observed=0.906),
        _gate("P1_player_coverage_single", observed=0.903),
        _gate("P1_player_coverage_double_plus", observed=0.874),
    )


def _squad_gate_pair() -> tuple[ShadowGateResult, ...]:
    return (_gate(squad.S1_GATE, observed=0.50), _gate(squad.S2_GATE, observed=0.108))


def _report(**overrides: object) -> ShadowCalibrationReport:
    """An abstained v1 report by default: the shape every attack below starts from."""

    values: dict[str, object] = {
        "generated_at_utc": "2026-08-28T12:00:00+00:00",
        "execution": _execution(),
        "horizon": 1,
        "residual_source": _source(),
        "sample_size": 37,
        "point_estimate": None,
        "calibration_diagnostics": {"mean_probability_integral_transform": 0.5},
        "interval_diagnostics": {},
        "gate_results": (),
        "shadow_status": "abstained",
        "reasons": ("the squad instrument was not run",),
        "provenance_fingerprints": {"repository_commit": "f12aeb0"},
    }
    values.update(overrides)
    return ShadowCalibrationReport(**values)  # type: ignore[arg-type]


def _claims_a_pass(**overrides: object) -> ShadowCalibrationReport:
    values: dict[str, object] = {"shadow_status": "calibrated_internal", "reasons": ()}
    values.update(overrides)
    return _report(**values)


def _v2_report(**overrides: object) -> ShadowCalibrationReport:
    """The same abstained report under the full-protocol contract.

    v2 is where a declaration exists at all, and it is mandatory at every status, so
    the complete pre-registered set is the baseline here rather than an override. The
    attacks below vary it; omitting it is itself one of them.
    """

    values: dict[str, object] = {
        "declared_gates": PREREG_GATE_FAMILIES,
        "contract_version": SHADOW_CALIBRATION_CONTRACT_V2,
    }
    values.update(overrides)
    return _report(**values)


def _v2_claims_a_pass(**overrides: object) -> ShadowCalibrationReport:
    values: dict[str, object] = {"shadow_status": "calibrated_internal", "reasons": ()}
    values.update(overrides)
    return _v2_report(**values)


def _rebuild(document: Mapping[str, object]) -> ShadowCalibrationReport:
    """Reconstruct a report from a serialized document, exactly as committed."""

    execution = document["execution"]
    source = document["residual_source"]
    assert isinstance(execution, Mapping)
    assert isinstance(source, Mapping)
    gates = document["gate_results"]
    assert isinstance(gates, list)
    return ShadowCalibrationReport(
        generated_at_utc=str(document["generated_at_utc"]),
        execution=ShadowExecutionMetadata(
            started_at_utc=str(execution["started_at_utc"]),
            completed_at_utc=str(execution["completed_at_utc"]),
            elapsed_seconds=float(execution["elapsed_seconds"]),  # type: ignore[arg-type]
            deterministic_seed=int(execution["deterministic_seed"]),  # type: ignore[arg-type]
            warnings=tuple(execution["warnings"]),  # type: ignore[call-overload]
        ),
        horizon=int(document["horizon"]),  # type: ignore[arg-type]
        residual_source=ShadowResidualSource(
            export_label=str(source["export_label"]),
            model_name=str(source["model_name"]),
            model_version=str(source["model_version"]),
            feature_contract_version=str(source["feature_contract_version"]),
            table_sha256=str(source["table_sha256"]),
            seasons=tuple(source["seasons"]),  # type: ignore[call-overload]
            cutoff_fold_id=str(source["cutoff_fold_id"]),
        ),
        sample_size=int(document["sample_size"]),  # type: ignore[arg-type]
        point_estimate=document["point_estimate"],  # type: ignore[arg-type]
        calibration_diagnostics=document["calibration_diagnostics"],  # type: ignore[arg-type]
        interval_diagnostics=document["interval_diagnostics"],  # type: ignore[arg-type]
        gate_results=tuple(
            ShadowGateResult(
                gate=str(entry["gate"]),
                passes=bool(entry["passes"]),
                observed=entry["observed"],
                threshold=str(entry["threshold"]),
            )
            for entry in gates
        ),
        shadow_status=str(document["shadow_status"]),
        reasons=tuple(document["reasons"]),  # type: ignore[call-overload]
        provenance_fingerprints=document["provenance_fingerprints"],  # type: ignore[arg-type]
    )


def _synthetic_squad_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[tuple[ShadowGateResult, ...], dict[str, float | None]]:
    """The real S1/S2 gate objects and diagnostics, from synthetic per-fold readings.

    Only ``_read_fold`` is replaced — the step that would need the solver, the scenario
    generator and a residual export. The gate ids, the threshold prose, the bounds, the
    diagnostic names and the verdict are still produced by the module under review, and
    those are exactly what the publication boundary is judged on.
    """

    frame = pd.DataFrame({"player_id": [1], "expected_points": [5.0]})
    folds = tuple(
        squad.SquadFold(
            fold_id=f"2024-25-gw{gameweek:02d}",
            season="2024-25",
            gameweek=gameweek,
            projections=frame,
            realized_points=frame,
            prior_fold_ids=(),
        )
        for gameweek in range(2, 39)
    )
    residuals = pd.DataFrame(
        {
            "season": ["2021-22", "2022-23", "2023-24"],
            "fold_id": ["2021-22-gw10", "2022-23-gw20", "2023-24-gw38"],
        }
    )
    counter = itertools.count()

    def read(
        fold: squad.SquadFold,
        _residuals: pd.DataFrame,
        _history: object,
        _provenance: object,
        _config: squad.SquadShadowConfig,
        *,
        shift_points: float,
        fixture_counts: object,
    ) -> tuple[squad.SquadFoldReading, float]:
        index = next(counter)
        reading = squad.SquadFoldReading(
            fold_id=fold.fold_id,
            realized_score=50.0,
            scenario_mean_score=51.0,
            lower_quantile_score=40.0,
            probability_integral_transform=0.5,
            below_lower_quantile=index % 10 == 0,
        )
        return reading, 1.0

    monkeypatch.setattr(squad, "_read_fold", read)
    shift = squad.FrozenShift(
        shift_points=-1.25,
        fold_count=111,
        first_fold_id="2021-22-gw02",
        last_fold_id="2023-24-gw38",
        seasons=tuple(squad.FIT_SEASONS),
    )
    # The second amendment froze every control, so the configuration takes no arguments
    # at all: a test that named one would be choosing a control nobody pre-registered.
    config = squad.SquadShadowConfig()
    gates, _readings, diagnostics = squad.evaluate_squad_gates(
        folds, residuals, None, config, shift
    )
    return gates, diagnostics


def _combine(
    player_gates: tuple[ShadowGateResult, ...],
    squad_gates: tuple[ShadowGateResult, ...],
    **overrides: object,
) -> ShadowCalibrationReport:
    values: dict[str, object] = {
        "generated_at_utc": "2026-08-28T12:00:00+00:00",
        "execution": _execution(),
        "residual_source": _source(),
        "calibration_diagnostics": {},
        "interval_diagnostics": {},
        "evaluation_folds": 37,
        "provenance_fingerprints": {"repository_commit": "f12aeb0"},
    }
    values.update(overrides)
    return squad.combine_full_protocol(
        # The merge takes bound evidence rather than a bare gate sequence: a caller
        # with no recorded player report can no longer call it at all.
        player=squad.PlayerEvidence(
            gates=player_gates,
            calibration_diagnostics={},
            interval_diagnostics={},
            provenance={"player_report_sha256": "e" * 64},
            abstentions=(),
            sample_size=37,
        ),
        squad_gates=squad_gates,
        **values,  # type: ignore[arg-type]
    )


def _residue(directory: Path) -> list[str]:
    return sorted(entry.name for entry in directory.iterdir() if ".tmp-" in entry.name)


# --- 1. a partial protocol cannot pass ------------------------------------------------


def test_an_empty_declared_gate_set_is_refused_outright_not_only_on_a_pass() -> None:
    """No completeness claim at all is the weakest possible one, and v2 refuses it.

    The refusal no longer waits for a claimed pass: a v2 report that declares nothing
    cannot be constructed at any status, because a report that never says what the
    protocol required cannot be read as having answered it. The companion assertion is
    the other half of the version boundary — v1 was recorded without the field, so a v1
    report may not declare gates at all rather than declaring an empty set.
    """

    with pytest.raises(ShadowReportError, match="must declare which"):
        _v2_claims_a_pass(gate_results=_p1_sub_gates(), declared_gates=())
    with pytest.raises(ShadowReportError, match="must declare which"):
        _v2_report(declared_gates=())
    with pytest.raises(
        ShadowReportError, match=f"declared_gates is a {SHADOW_CALIBRATION_CONTRACT_V2} field"
    ):
        _report(declared_gates=PREREG_GATES)


def test_only_the_squad_gates_cannot_claim_the_full_protocol() -> None:
    with pytest.raises(ShadowReportError, match="has no entry in gate_results"):
        _v2_claims_a_pass(gate_results=_squad_gate_pair(), declared_gates=PREREG_GATES)


def test_only_p1_cannot_claim_the_full_protocol() -> None:
    with pytest.raises(ShadowReportError, match="has no entry in gate_results"):
        _v2_claims_a_pass(gate_results=_p1_sub_gates(), declared_gates=PREREG_GATES)


def test_p1_and_s1_without_s2_cannot_claim_the_full_protocol() -> None:
    with pytest.raises(ShadowReportError, match="has no entry in gate_results"):
        _v2_claims_a_pass(
            gate_results=(*_p1_sub_gates(), _gate(squad.S1_GATE)),
            declared_gates=PREREG_GATES,
        )


def test_a_declared_family_with_no_matching_entry_is_refused() -> None:
    """The protocol is declared in full and one of its families is left unanswered."""

    with pytest.raises(ShadowReportError, match="has no entry in gate_results"):
        _v2_claims_a_pass(gate_results=(*_p1_sub_gates(), _gate(squad.S1_GATE)))


def test_a_declaration_naming_a_family_the_protocol_never_fixed_is_refused() -> None:
    """Widening the declaration would let an off-protocol gate ride in as a member.

    Declaring an extra family makes the "every gate matches a declared family" rule
    admit exactly the gate that does not belong, so the declaration has to be the
    pre-registered set itself rather than a superset of it.
    """

    with pytest.raises(ShadowReportError, match="does not pre-register"):
        _v2_claims_a_pass(
            gate_results=(*_p1_sub_gates(), *_squad_gate_pair()),
            declared_gates=(*PREREG_GATES, "S3_squad_upper_tail"),
        )


def test_a_gate_entry_matching_no_declared_family_is_refused() -> None:
    """A measured gate outside the pre-registered set cannot count toward it."""

    with pytest.raises(ShadowReportError, match="matches no declared family"):
        _v2_claims_a_pass(
            gate_results=(*_p1_sub_gates(), *_squad_gate_pair(), _gate("X_convenient_extra")),
            declared_gates=PREREG_GATES,
        )


def test_the_three_p1_sub_gates_satisfy_their_family() -> None:
    report = _v2_claims_a_pass(
        gate_results=(*_p1_sub_gates(), *_squad_gate_pair()),
        declared_gates=PREREG_GATES,
    )
    assert report.shadow_status == "calibrated_internal"
    assert report.declared_gates == PREREG_GATES


def test_a_family_is_also_satisfied_by_one_entry_of_its_own_name() -> None:
    report = _v2_claims_a_pass(
        gate_results=(_gate("P1_player_coverage"), *_squad_gate_pair()),
        declared_gates=PREREG_GATES,
    )
    assert report.shadow_status == "calibrated_internal"


def test_a_typo_in_a_sub_gate_id_does_not_satisfy_its_family() -> None:
    """``P1_playercoverage_pooled`` is not ``P1_player_coverage``; it must drop loudly.

    Under v2 it drops one step earlier than it used to. The mistyped entries belong to
    no declared family, so the report is refused for carrying a gate outside the
    pre-registered set before the completeness rule is ever reached — and either way
    the three typos cannot answer the family they were meant to answer.
    """

    with pytest.raises(ShadowReportError, match="matches no declared family"):
        _v2_claims_a_pass(
            gate_results=(
                _gate("P1_playercoverage_pooled"),
                _gate("P1_playercoverage_single"),
                _gate("P1_playercoverage_double_plus"),
                *_squad_gate_pair(),
            ),
            declared_gates=PREREG_GATES,
        )


def test_a_family_prefix_without_the_separator_does_not_match() -> None:
    """``P1_player_coverage_pooled`` starts with ``P1_player_cov`` and must not count.

    A truncated family name cannot be declared at all now — the declaration must be
    the pre-registered tuple — so the rule is exercised from the other side: a gate id
    that shares a family's prefix without the separator answers no declared family, and
    a family whose only candidate entry is that gate has no entry at all.
    """

    with pytest.raises(ShadowReportError, match="matches no declared family"):
        _v2_claims_a_pass(
            gate_results=(_gate("P1_player_coverageX"), *_squad_gate_pair()),
        )
    with pytest.raises(ShadowReportError, match="does not pre-register"):
        _v2_claims_a_pass(
            gate_results=(*_p1_sub_gates(), *_squad_gate_pair()),
            declared_gates=(*PREREG_GATES, "P1_player_cov"),
        )


def test_declared_gates_may_not_repeat_a_family() -> None:
    with pytest.raises(ShadowReportError, match="repeats a family"):
        _v2_report(declared_gates=(*PREREG_GATES, PREREG_GATES[0]))


def test_a_declared_family_may_not_be_an_empty_name() -> None:
    with pytest.raises(ShadowReportError, match="non-empty name"):
        _v2_report(declared_gates=("",))


def test_a_failing_gate_still_cannot_pass_even_with_a_complete_declaration() -> None:
    """A measured negative outranks a complete declaration, under both versions.

    v2 refuses first and for a stronger reason: a gate that failed as measured *is* the
    verdict, so ``calibrated_internal`` is not merely unearned but a misfiling of a
    recorded negative. The v1 rule it was built on has not gone anywhere, and the second
    half asserts it still refuses on its own terms.
    """

    failing = (
        *_p1_sub_gates(),
        _gate(squad.S1_GATE, passes=False, observed=0.31),
        _gate(squad.S2_GATE),
    )
    with pytest.raises(ShadowReportError, match="failed as measured, so this report"):
        _v2_claims_a_pass(gate_results=failing, declared_gates=PREREG_GATES)
    with pytest.raises(ShadowReportError, match="every pre-registered gate"):
        _claims_a_pass(gate_results=failing)


# --- 1b. the declaration is measured against the pre-registration, not against itself --


def test_a_self_declared_two_thirds_protocol_is_refused_by_the_contract() -> None:
    """The declaration is checked against the pre-registration, not only against itself.

    A report that declares only the two squad families, and measures exactly those two,
    would otherwise be a ``calibrated_internal`` verdict on two thirds of the protocol
    with P1 never asked. Completeness may not rest on the caller remembering to pass
    ``PREREG_GATES``: the contract holds ``PREREG_GATE_FAMILIES`` itself, so a second
    runner that declares its own subset inherits the protection rather than having to
    reproduce it.
    """

    with pytest.raises(ShadowReportError, match="omits pre-registered families"):
        _v2_claims_a_pass(
            gate_results=_squad_gate_pair(),
            declared_gates=(squad.S1_GATE, squad.S2_GATE),
        )
    # The families named in the refusal are the contract's own, and they are the prereg.
    assert PREREG_GATE_FAMILIES == PREREG_GATES


def test_a_meaningless_declared_family_is_refused_by_the_contract() -> None:
    """A whitespace family name declares nothing, and the contract refuses to read it.

    A single space is non-empty to ``bool``, and a gate of the same name would satisfy
    it, so a report could otherwise pass with a declaration that names no protocol at
    all. The check is on ``family.strip()``, so blank-but-present is refused exactly
    like absent.
    """

    with pytest.raises(ShadowReportError, match="non-empty name"):
        _v2_claims_a_pass(gate_results=(_gate(" "),), declared_gates=(" ",))


def test_a_truncated_family_name_cannot_stand_in_for_the_pre_registered_id() -> None:
    """Declaring ``P1`` no longer satisfies the completeness rule for the P1 sub-gates.

    The prefix rule is what lets three sub-gates answer one family; it must not also let
    a shortened declaration stand in for the pre-registered id. Membership in
    ``PREREG_GATE_FAMILIES`` is exact, so the declaration reads as a quotation of the
    pre-registration and a truncation is refused by name.
    """

    with pytest.raises(ShadowReportError, match="omits pre-registered families"):
        _v2_claims_a_pass(
            gate_results=(*_p1_sub_gates(), *_squad_gate_pair()),
            declared_gates=("P1", "S1", "S2"),
        )


def test_a_bare_string_declared_gate_set_is_refused() -> None:
    """``declared_gates`` is a sequence of names, and a single string is not one.

    A caller passing the family name as a string would otherwise get one declared family
    per character, serialized as such — and silently, whenever the characters happen to
    be distinct enough to clear the duplicate check. The type is now enforced instead of
    merely annotated, at every status rather than only at a claimed pass.
    """

    with pytest.raises(ShadowReportError, match="not a single string"):
        _v2_report(declared_gates="S1_pit")


# --- 2. the three terminal states -----------------------------------------------------


def test_a_complete_passing_protocol_is_calibrated_internal() -> None:
    report = _combine(_p1_sub_gates(), _squad_gate_pair())
    assert report.shadow_status == "calibrated_internal"
    # The full-protocol combiner records under v2, which is the version whose rules the
    # verdict was actually checked against; a v1 pass would be a weaker claim.
    assert report.contract_version == SHADOW_CALIBRATION_CONTRACT_V2
    assert report.declared_gates == PREREG_GATES
    assert report.point_estimate is None
    assert "unlocks the internal status and nothing else" in report.reasons[0]


def test_one_failing_gate_fails_the_whole_protocol() -> None:
    failing = _gate(squad.S1_GATE, passes=False, observed=0.31)
    report = _combine(_p1_sub_gates(), (failing, _gate(squad.S2_GATE)))
    assert report.shadow_status == "failed"
    assert report.reasons[0] == f"{squad.S1_GATE} failed as measured."
    assert "no retry, re-tune or reinterpretation" in report.reasons[-1]


def test_a_failure_outranks_an_unasked_family_without_hiding_it() -> None:
    """A negative is the verdict even when the protocol is incomplete — and both are said.

    The status is ``failed``: a measured negative is a result, not an abstention. But
    the incompleteness does not stop being true because something else also went wrong,
    and a reader of this report would otherwise be told S1 failed and never told that
    P1 was never asked. The verdict leads; the missing family is still named.
    """

    report = _combine((), (_gate(squad.S1_GATE, passes=False, observed=0.31),))
    assert report.shadow_status == "failed"
    assert "failed as measured" in report.reasons[0]
    assert any("partial protocol" in reason for reason in report.reasons)
    assert any("P1_player_coverage" in reason for reason in report.reasons)


def test_failed_may_not_be_claimed_without_a_gate_that_failed_as_measured() -> None:
    """The status-consistency rule runs in both directions, so neither can be dressed up.

    A gate that failed as measured forces ``failed``; the converse matters just as much.
    A report that calls itself failed while every gate it carries passed is an abstention
    wearing a stronger word — and a stronger word is what a later reader would count.
    """

    with pytest.raises(ShadowReportError, match="names at least one gate that failed"):
        _v2_report(
            gate_results=(*_p1_sub_gates(), *_squad_gate_pair()),
            shadow_status="failed",
            reasons=("the run preferred to record a negative",),
        )


def test_an_unasked_family_with_everything_else_passing_abstains_and_names_it() -> None:
    report = _combine((), _squad_gate_pair())
    assert report.shadow_status == "abstained"
    assert "P1_player_coverage" in report.reasons[-1]
    assert "calibrated_internal is not claimable" in report.reasons[-1]


def test_no_gates_at_all_abstains_naming_every_family() -> None:
    report = _combine((), ())
    assert report.shadow_status == "abstained"
    assert all(family in report.reasons[-1] for family in PREREG_GATES)


def test_a_thin_sample_abstains_even_when_every_measured_gate_passed() -> None:
    report = _combine(
        _p1_sub_gates(),
        _squad_gate_pair(),
        abstention_reasons=("29 evaluation folds are fewer than the minimum of 30.",),
    )
    assert report.shadow_status == "abstained"
    assert report.reasons[0].startswith("29 evaluation folds")


def test_a_passing_gate_outside_every_family_cannot_be_combined_into_a_pass() -> None:
    """The contract, not the combiner, is what refuses — and it refuses loudly."""

    with pytest.raises(ShadowReportError, match="matches no declared family"):
        _combine(_p1_sub_gates(), (*_squad_gate_pair(), _gate("S9_bonus_gate")))


def test_an_unevaluable_gate_is_reported_as_abstained_rather_than_failed() -> None:
    """Missing evidence is not a negative result, and the combiner keeps the two apart.

    The pre-registration separates them — a failing gate is ``failed``, a missing gate
    or sample is ``abstained``. A gate entry with no observed value cannot pass by
    contract, so the naive reading drags the verdict to ``failed`` with the "failed as
    measured" wording though nothing was measured. The squad instrument never emits such
    an entry (a thin sample returns no gates at all, which does abstain), so this is
    reachable only through the shared combiner's other callers — which is exactly why
    the classification belongs in the combiner rather than in one runner's care.
    """

    unevaluable = ShadowGateResult(
        gate=squad.S2_GATE, passes=False, observed=None, threshold="not evaluable"
    )
    report = _combine(_p1_sub_gates(), (_gate(squad.S1_GATE), unevaluable))
    assert report.shadow_status == "abstained"
    named = f"{squad.S2_GATE} was not evaluable and carries no observation."
    assert report.reasons[-1] == named
    assert not any("failed as measured" in reason for reason in report.reasons)


# --- 3. backward compatibility --------------------------------------------------------


def test_a_report_declaring_nothing_serializes_without_the_key() -> None:
    document = report_to_dict(_report())
    assert "declared_gates" not in document
    # The default is still v1, so a runner that adopts nothing keeps writing v1 bytes;
    # v2 is asked for by name, by the one runner that answers the whole protocol.
    assert SHADOW_CALIBRATION_CONTRACT_VERSION == SHADOW_CALIBRATION_CONTRACT_V1
    assert document["contract_version"] == SHADOW_CALIBRATION_CONTRACT_V1


@pytest.mark.parametrize("path", COMMITTED_ARTIFACTS, ids=lambda path: path.stem)
def test_the_committed_artifacts_carry_no_declared_gates(path: Path) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    assert "declared_gates" not in document
    # Pinned to v1 by name rather than to the default: these bytes are frozen at the
    # version they were recorded under, whatever a later runner defaults to.
    assert document["contract_version"] == SHADOW_CALIBRATION_CONTRACT_V1
    assert document["shadow_status"] == "abstained"


@pytest.mark.parametrize("path", COMMITTED_ARTIFACTS, ids=lambda path: path.stem)
def test_the_committed_artifacts_have_a_stable_replay_identity(path: Path) -> None:
    raw = path.read_text(encoding="utf-8")
    document = json.loads(raw)
    identity = replay_identity_of(document)
    assert identity == replay_identity_of(json.loads(raw))
    assert set(document) - set(identity) == {"generated_at_utc"}
    assert "declared_gates" not in identity


def test_the_corrected_artifact_still_replays_byte_for_byte(tmp_path: Path) -> None:
    """The strongest compatibility statement available: the same bytes, and a replay."""

    raw = COMMITTED_ARTIFACTS[1].read_text(encoding="utf-8")
    document = json.loads(raw)
    rebuilt = _rebuild(document)
    assert report_to_dict(rebuilt) == document
    payload = json.dumps(report_to_dict(rebuilt), indent=2, sort_keys=True, allow_nan=False)
    assert payload + "\n" == raw

    occupied = tmp_path / "shadow_calibration_in_season_corrected.json"
    occupied.write_text(raw, encoding="utf-8", newline="\n")
    assert write_shadow_report_once(rebuilt, occupied) == "replay"
    assert _residue(tmp_path) == []


def test_the_pre_execution_artifact_is_readable_but_carries_no_execution_block() -> None:
    """The older artifact predates ``execution``; it replays as itself and nothing more.

    It cannot be reconstructed through the current dataclass (``execution`` is required),
    which is why the squad runner writes to its own path instead of sharing this one.
    """

    document = json.loads(COMMITTED_ARTIFACTS[0].read_text(encoding="utf-8"))
    assert "execution" not in document
    identity = replay_identity_of(document)
    assert "execution" not in identity
    assert identity == replay_identity_of(document)


def test_a_v1_shaped_report_without_declared_gates_still_constructs_and_serializes() -> None:
    report = _report(
        gate_results=_p1_sub_gates(),
        shadow_status="abstained",
        reasons=("only P1 was evaluated",),
    )
    document = report_to_dict(report)
    assert set(document) == {
        "calibration_diagnostics",
        "contract_version",
        "execution",
        "gate_results",
        "generated_at_utc",
        "horizon",
        "interval_diagnostics",
        "point_estimate",
        "provenance_fingerprints",
        "reasons",
        "residual_source",
        "sample_size",
        "shadow_status",
    }


def test_the_new_field_precedes_contract_version_so_v1_positional_calls_are_refused() -> None:
    """``declared_gates`` was inserted before ``contract_version``, and the break is loud.

    A caller that passed ``contract_version`` positionally — the thirteenth argument
    under v1 — now assigns that string to ``declared_gates``. It is refused rather than
    silently mis-assigned, and the refusal names the field it landed in and the shape it
    should have had, so the caller is told what to fix rather than left with a report
    declaring one family per character.
    """

    with pytest.raises(ShadowReportError, match="not a single string"):
        ShadowCalibrationReport(
            "2026-08-28T12:00:00+00:00",
            _execution(),
            1,
            _source(),
            37,
            None,
            {},
            {},
            (),
            "abstained",
            ("a reason",),
            {"repository_commit": "f12aeb0"},
            SHADOW_CALIBRATION_CONTRACT_VERSION,  # type: ignore[arg-type]
        )


# --- 4. the atomic writer -------------------------------------------------------------


def test_the_writer_writes_once_then_replays_identical_content(tmp_path: Path) -> None:
    path = tmp_path / "squad.json"
    assert write_shadow_report_once(_report(), path) == "written"
    assert write_shadow_report_once(_report(), path) == "replay"
    assert _residue(tmp_path) == []


def test_only_the_wall_clock_may_differ_in_a_replay(tmp_path: Path) -> None:
    path = tmp_path / "squad.json"
    assert write_shadow_report_once(_report(), path) == "written"
    later = _report(
        generated_at_utc="2030-01-01T00:00:00+00:00",
        execution=_execution(
            started_at_utc="2030-01-01T00:00:00+00:00",
            completed_at_utc="2030-01-01T00:03:00+00:00",
            elapsed_seconds=180.0,
        ),
    )
    assert write_shadow_report_once(later, path) == "replay"
    # The recorded bytes are the first run's, untouched.
    assert json.loads(path.read_text(encoding="utf-8"))["generated_at_utc"].startswith("2026")


def test_conflicting_content_at_an_occupied_path_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "squad.json"
    assert write_shadow_report_once(_report(), path) == "written"
    before = path.read_bytes()
    with pytest.raises(ShadowReportError, match="already holds a different measurement"):
        write_shadow_report_once(_report(sample_size=38), path)
    assert path.read_bytes() == before
    assert _residue(tmp_path) == []


def test_an_occupied_path_that_is_not_the_contract_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "squad.json"
    path.write_bytes(b"\xff\xfe not json at all")
    with pytest.raises(ShadowReportError, match="not a readable shadow report"):
        write_shadow_report_once(_report(), path)
    assert _residue(tmp_path) == []


def test_valid_json_that_is_not_this_measurement_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "squad.json"
    path.write_text('{"contract_version": "something_else"}\n', encoding="utf-8")
    with pytest.raises(ShadowReportError, match=r"unrecognised fields|no execution block"):
        write_shadow_report_once(_report(), path)
    assert _residue(tmp_path) == []


def test_concurrent_identical_writers_produce_one_write_and_all_replays(
    tmp_path: Path,
) -> None:
    path = tmp_path / "squad.json"

    def attempt(_index: int) -> str:
        return write_shadow_report_once(_report(), path)

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = sorted(pool.map(attempt, range(8)))
    assert outcomes.count("written") == 1
    assert outcomes.count("replay") == 7
    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["squad.json"]


def test_concurrent_conflicting_writers_leave_exactly_one_recorded_result(
    tmp_path: Path,
) -> None:
    path = tmp_path / "squad.json"

    def attempt(index: int) -> str:
        try:
            return write_shadow_report_once(_report(sample_size=30 + index), path)
        except ShadowReportError:
            return "refused"

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = sorted(pool.map(attempt, range(8)))
    assert outcomes.count("written") == 1
    assert outcomes.count("refused") == 7
    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["squad.json"]
    recorded = json.loads(path.read_text(encoding="utf-8"))["sample_size"]
    assert recorded in range(30, 38)


def test_the_writer_refuses_the_published_site_tree_and_creates_nothing(
    tmp_path: Path,
) -> None:
    target = tmp_path / "web" / "public" / "data" / "shadow_squad.json"
    with pytest.raises(ShadowReportError, match="published site tree"):
        write_shadow_report_once(_report(), target)
    assert not target.exists()
    assert not target.parent.exists()
    assert not (tmp_path / "web").exists()


def test_the_repository_site_tree_is_refused_in_every_casing() -> None:
    """The real ``web/public`` resolves to its on-disk name, so case variants are caught."""

    for candidate in ("web/public/data/x.json", "web/Public/data/x.json", "WEB/PUBLIC/x.json"):
        path = REPOSITORY_ROOT / candidate
        if "web/public" not in path.resolve().as_posix():
            pytest.skip("case-sensitive filesystem: the variants are different directories")
        with pytest.raises(ShadowReportError, match="published site tree"):
            write_shadow_report_once(_report(), path)
        assert not path.exists()


def test_a_site_tree_that_does_not_exist_yet_escapes_the_guard_by_case(
    tmp_path: Path,
) -> None:
    """FINDING: the guard is a case-sensitive substring on a case-insensitive filesystem.

    ``web/Public`` is refused only when a lowercase ``web/public`` already exists to
    canonicalize against — which is true of the repository, and false of any tree the
    run creates itself. On Windows the file below is then reachable through the very
    path the guard exists to forbid.
    """

    probe = tmp_path / "Probe"
    probe.mkdir()
    case_insensitive = (tmp_path / "probe").exists()

    target = tmp_path / "web" / "Public" / "shadow_squad.json"
    assert write_shadow_report_once(_report(), target) == "written"
    assert (tmp_path / "web" / "public" / "shadow_squad.json").exists() is case_insensitive


def test_the_guard_is_a_substring_rule_and_over_refuses(tmp_path: Path) -> None:
    """Documented: an unrelated directory whose name merely starts with ``public``."""

    target = tmp_path / "web" / "publications" / "notes.json"
    with pytest.raises(ShadowReportError, match="published site tree"):
        write_shadow_report_once(_report(), target)


# --- 5. replay identity ---------------------------------------------------------------


def test_replay_identity_excludes_only_the_four_wall_clock_fields() -> None:
    document = report_to_dict(_report())
    identity = replay_identity_of(document)
    assert set(document) - set(identity) == {"generated_at_utc"}
    execution = document["execution"]
    kept = identity["execution"]
    assert isinstance(execution, Mapping)
    assert isinstance(kept, Mapping)
    assert set(execution) - set(kept) == {
        "started_at_utc",
        "completed_at_utc",
        "elapsed_seconds",
    }
    assert set(kept) == {"deterministic_seed", "warnings"}


@pytest.mark.parametrize(
    ("label", "overrides"),
    [
        ("seed", {"execution": _execution(deterministic_seed=12)}),
        ("warning", {"execution": _execution(warnings=("a solver fell back",))}),
        ("diagnostic", {"calibration_diagnostics": {"mean_probability_integral_transform": 0.51}}),
        ("provenance", {"provenance_fingerprints": {"repository_commit": "deadbee"}}),
        ("reason", {"reasons": ("a different reason",)}),
        ("sample_size", {"sample_size": 36}),
    ],
)
def test_a_differing_run_is_a_conflict_not_a_replay(
    tmp_path: Path, label: str, overrides: dict[str, object]
) -> None:
    path = tmp_path / f"{label}.json"
    assert write_shadow_report_once(_report(), path) == "written"
    with pytest.raises(ShadowReportError, match="already holds a different measurement"):
        write_shadow_report_once(_report(**overrides), path)
    assert _residue(tmp_path) == []


def test_a_differing_declaration_is_a_conflict_not_a_replay(tmp_path: Path) -> None:
    """What a report claims to have answered is part of the measurement, not metadata.

    This case is separated from the table above because it is only expressible under
    v2 now closes it from the other end: the declaration must be the pre-registered
    tuple in its pre-registered order, so neither a widened nor a re-ordered declaration
    can be written at all. Order matters because the declaration is serialized — two
    runs of one measurement that listed the same three families differently would write
    different bytes and read as a conflict rather than as a replay.
    """

    path = tmp_path / "declared_gates.json"
    assert write_shadow_report_once(_v2_report(), path) == "written"
    with pytest.raises(ShadowReportError, match="does not pre-register"):
        _v2_report(declared_gates=(*PREREG_GATE_FAMILIES, "S3_squad_upper_tail"))
    with pytest.raises(ShadowReportError, match="in another order"):
        _v2_report(declared_gates=tuple(reversed(PREREG_GATE_FAMILIES)))
    assert _residue(tmp_path) == []


# --- 6. public isolation --------------------------------------------------------------


def test_the_public_site_schema_rejects_a_squad_report(monkeypatch: pytest.MonkeyPatch) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema_path = REPOSITORY_ROOT / "docs" / "contracts" / "ui_view_v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    gates, diagnostics = _synthetic_squad_gates(monkeypatch)
    report = _combine(_p1_sub_gates(), gates, calibration_diagnostics=diagnostics)
    assert report.shadow_status == "calibrated_internal"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(report_to_dict(report), schema)


def test_a_squad_report_carries_no_member_facing_probability_prose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gates, diagnostics = _synthetic_squad_gates(monkeypatch)
    report = _combine(_p1_sub_gates(), gates, calibration_diagnostics=diagnostics)
    text = json.dumps(report_to_dict(report), indent=2, sort_keys=True)
    assert _MEMBER_FACING_PROSE.findall(text) == []
    # The gates are still fully named internally — silence is not the mechanism.
    assert squad.S1_GATE in text
    assert "mean PIT in [0.43, 0.57] inclusive" in text
    assert "realized-below-q10 rate in [0.04, 0.16] inclusive" in text


def test_the_abstained_squad_report_the_cli_writes_carries_no_prose_either(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shipped shape: the squad CLI passes no player gates, so P1 is always unasked."""

    gates, diagnostics = _synthetic_squad_gates(monkeypatch)
    report = _combine((), gates, calibration_diagnostics=diagnostics)
    assert report.shadow_status == "abstained"
    text = json.dumps(report_to_dict(report), indent=2, sort_keys=True)
    assert _MEMBER_FACING_PROSE.findall(text) == []


def test_the_two_replay_identity_helpers_have_not_drifted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two runners must not disagree about what a replay may differ by.

    ``shadow_calibration.replay_identity`` (the player CLI's own create-once) and
    ``shadow_report.replay_identity_of`` (the new atomic writer) are duplicate
    definitions of the same rule. This pins them together on the committed artifacts and
    on a squad document so a change to one shows up as a failure rather than as two
    runners quietly disagreeing.
    """

    from squadopt.experiments.shadow_calibration import replay_identity

    gates, diagnostics = _synthetic_squad_gates(monkeypatch)
    squad_document = report_to_dict(
        _combine(_p1_sub_gates(), gates, calibration_diagnostics=diagnostics)
    )
    documents = [squad_document, report_to_dict(_report())]
    documents.extend(json.loads(path.read_text(encoding="utf-8")) for path in COMMITTED_ARTIFACTS)
    for document in documents:
        assert replay_identity(document) == replay_identity_of(document)


def test_a_squad_report_may_not_be_written_under_the_published_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gates, diagnostics = _synthetic_squad_gates(monkeypatch)
    report = _combine(_p1_sub_gates(), gates, calibration_diagnostics=diagnostics)
    target = tmp_path / "web" / "public" / "data" / "shadow_squad.json"
    with pytest.raises(ShadowReportError, match="published site tree"):
        write_shadow_report_once(report, target)
    assert not (tmp_path / "web").exists()


# --- 7. the strategy catalogue is untouched by a squad verdict ------------------------


def test_a_calibrated_internal_squad_verdict_widens_nothing_publishable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before_fields = frozenset(PUBLISHABLE_FIELDS)
    before_pattern = FORBIDDEN_FIELD_PATTERN.pattern
    gates, diagnostics = _synthetic_squad_gates(monkeypatch)
    report = _combine(_p1_sub_gates(), gates, calibration_diagnostics=diagnostics)

    assert report.shadow_status == "calibrated_internal"
    assert frozenset(PUBLISHABLE_FIELDS) == before_fields == _PUBLISHED_ENVELOPE
    assert FORBIDDEN_FIELD_PATTERN.pattern == before_pattern
    for name in diagnostics:
        assert name not in PUBLISHABLE_FIELDS


def test_no_squad_diagnostic_can_be_declared_publishable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The closed envelope — not the name pattern — is what stops every one of them."""

    _gates, diagnostics = _synthetic_squad_gates(monkeypatch)
    assert set(diagnostics) >= {
        "mean_probability_integral_transform",
        "realized_below_lower_quantile_rate",
    }
    for name in diagnostics:
        with pytest.raises(StrategyConfigurationError, match="unpublishable"):
            Strategy(
                slug="kacak",
                constraints=CandidateConstraints(),
                ranks_by=RankingCriterion.EXPECTED_OWN_POINTS,
                publishes=frozenset({name}),
                evidence=EvidenceStatus.DIAGNOSTIC_ONLY,
            )


def test_the_meta_gate_alone_would_stop_only_the_probability_named_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FINDING (scope): the name meta-gate is narrower than the envelope it backs up.

    If ``PUBLISHABLE_FIELDS`` were ever widened by hand, the existing meta-gate would
    catch the three probability- and quantile-named squad diagnostics and let the three
    bookkeeping ones through. They are not probabilities, so this is a limit of the
    pattern rather than a hole in the boundary — but the pattern is not the second line
    of defence it reads as. The tail *count* the second amendment added beside the rate
    is caught only because it inherited the word ``quantile`` from its neighbour's name,
    which is the accident that makes the point: the pattern reads names, not meanings.
    """

    _gates, diagnostics = _synthetic_squad_gates(monkeypatch)
    blocked = {name for name in diagnostics if FORBIDDEN_FIELD_PATTERN.search(name)}
    assert blocked == {
        "mean_probability_integral_transform",
        "realized_below_lower_quantile_rate",
        "realized_below_lower_quantile_folds",
    }
    assert set(diagnostics) - blocked == {
        "evaluation_folds",
        "frozen_shift_points",
        "shift_fit_folds",
    }
