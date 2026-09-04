"""Tests for the Route A candidate declaration freeze.

A pre-registration is only worth the property that it cannot drift after review, so the tests
that carry weight here are the ones that would fail if it did:

- the declaration must not move #43's fingerprints, which is ruling 3's whole point;
- the two fingerprints must be reproducible from the typed objects, so what was reviewed is
  what executes;
- the input must be bound by digest, and the freeze must refuse to invent one;
- the stop condition must gate the pooled coefficient and nothing per-position.

The pinned literals below are the values under review. **If one of these fails, do not update
the literal** — a moved fingerprint means the declaration no longer describes the candidate,
and the freeze is void until it is re-reviewed.
"""

import json
from pathlib import Path

import pytest
from scripts import freeze_candidate_declaration as issue43
from scripts import freeze_route_a_declaration as route_a

# The frozen values. See the module docstring before changing either.
DECLARATION_FINGERPRINT = "29deea10bf176b59b5a4c9107008e8870ebcb5d685077fc3aa6e1142a6db4036"
BENCHMARK_FINGERPRINT = "01bd220fbcb23e467f9945f243528fe73cf53af7cb092cd5db049cc28bb4cbf6"


# --- ruling 3: no shared constant moves, and #43 stays valid ------------------


def test_the_declaration_does_not_move_issue_43s_fingerprints() -> None:
    """Ruling 3's whole purpose. #43's pending freeze must survive this declaration."""

    assert issue43.declaration().declaration_fingerprint != (
        route_a.declaration().declaration_fingerprint
    )
    assert issue43.benchmark_config().configuration_fingerprint != (
        route_a.benchmark_config().configuration_fingerprint
    )


def test_route_a_carries_its_own_contract_identity() -> None:
    """Not a bump of the shared constant: the signal joins as data."""

    from squadopt.backtest.learned_candidate import LEARNED_RATE_FEATURE_CONTRACT_VERSION

    declared = route_a.declaration()

    assert declared.feature_contract_version == route_a.ROUTE_A_FEATURE_CONTRACT_VERSION
    assert declared.feature_contract_version != LEARNED_RATE_FEATURE_CONTRACT_VERSION


def test_the_record_states_that_no_shared_constant_moved() -> None:
    record = route_a.document()

    assert record["shared_contract_constants_moved"] == []
    assert "shared_feature_contract_constants" in route_a.declaration().frozen_components


# --- the fingerprints are the reviewed values --------------------------------


def test_the_declaration_fingerprint_holds() -> None:
    """A moved value means the declaration describes something that is not being run."""

    assert route_a.declaration().declaration_fingerprint == DECLARATION_FINGERPRINT


def test_the_benchmark_configuration_fingerprint_holds() -> None:
    assert route_a.benchmark_config().configuration_fingerprint == BENCHMARK_FINGERPRINT


def test_the_record_reports_the_same_fingerprints_it_computes() -> None:
    """The record must not restate a transcription of the values."""

    record = route_a.document()

    assert record["declaration_fingerprint"] == route_a.declaration().declaration_fingerprint
    assert record["benchmark_configuration_fingerprint"] == (
        route_a.benchmark_config().configuration_fingerprint
    )


def test_the_freeze_reads_no_holdout_and_records_no_completed_run() -> None:
    record = route_a.document()

    assert record["locked_holdout_accessed"] is False
    assert record["formal_run_completed"] is False


# --- ruling 2: the input is bound, not described ------------------------------


def test_the_input_is_bound_to_the_committed_frame_digest() -> None:
    record = route_a.document()
    signal = record["signal_input"]

    assert isinstance(signal, dict)
    committed = json.loads(route_a.SIGNAL_RECORD.read_text(encoding="utf-8"))
    assert signal["frame_fingerprint"] == committed["frame_fingerprint"]
    assert len(str(signal["frame_fingerprint"])) == 64
    assert signal["re_derived_in_the_run"] is True


def test_a_missing_signal_record_refuses_rather_than_inventing_a_digest(
    tmp_path: Path,
) -> None:
    """Without the frame's digest there is nothing to bind, so the freeze must not proceed."""

    with pytest.raises(SystemExit, match="cannot invent one"):
        route_a.signal_frame_fingerprint(tmp_path / "absent.json")


def test_a_signal_record_without_a_usable_digest_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "opponent_signal.json"
    path.write_text(json.dumps({"frame_fingerprint": "too-short"}), encoding="utf-8")

    with pytest.raises(SystemExit, match="no usable frame_fingerprint"):
        route_a.signal_frame_fingerprint(path)


# --- ruling 1: the gate is on the pooled coefficient -------------------------


def test_the_gated_quantity_is_the_pooled_coefficient() -> None:
    record = route_a.document()

    assert record["gated_quantity"] == "pooled_coefficient"
    assert "diagnostics" in str(record["per_position_slopes_are"])
    assert "not gates" in str(record["per_position_slopes_are"])


def test_both_expected_signs_are_declared_before_the_fit() -> None:
    """A stop condition on an undeclared sign is decided after seeing the answer."""

    record = route_a.document()
    signs = record["expected_coefficient_signs"]

    assert isinstance(signs, dict)
    assert set(signs) == set(route_a.SIGNAL_INPUT_COLUMNS)
    assert set(signs.values()) == {"positive"}


def test_the_stop_condition_names_the_interval_and_the_grain() -> None:
    condition = route_a.STOP_CONDITION

    assert "pooled coefficient" in condition
    assert "90%" in condition
    assert "gate nothing" in condition


# --- the change is exactly one component -------------------------------------


def test_only_the_rate_changes_and_the_two_signals_are_what_is_added() -> None:
    record = route_a.document()
    before = record["rate_inputs_before"]
    after = record["rate_inputs_after"]

    assert route_a.declaration().changed_component == "expected_points_rate"
    assert isinstance(before, list)
    assert isinstance(after, list)
    assert after == before + list(route_a.SIGNAL_INPUT_COLUMNS)
    assert len(after) == len(before) + 2


def test_the_control_it_was_written_against_is_recorded() -> None:
    """Written after the fw10 holdout so it does not chase a moving control."""

    record = route_a.document()

    assert record["operational_control_at_declaration"] == "fw05-bw0p1"
    assert record["control_unchanged_by_the_fw10_holdout"] is True


def test_the_frozen_components_include_the_gates_and_the_fold_set() -> None:
    frozen = route_a.declaration().frozen_components

    for component in ("development_fold_set", "promotion_gates", "evaluation_objective"):
        assert component in frozen


def test_the_declaration_is_rendered_with_its_reasoning_not_only_its_verdict() -> None:
    """A reader has to be able to tell why positive was expected, or the sign is arbitrary."""

    text = route_a.markdown(route_a.document())

    assert "clean sheet" in text
    assert "conflated difficulty integer" in text
    assert DECLARATION_FINGERPRINT in text
