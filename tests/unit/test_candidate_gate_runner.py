"""Tests for the formal-run entry point of the Issue #43 gate.

The run itself is not exercised here. It reads four seasons of the archive and takes minutes
per candidate, and `docs/candidate_gate_spec.md:68-69` is explicit that synthetic runs are not
gate evidence anyway. What is tested is everything that decides *whether* the run may happen
and what it records afterwards, because those are the parts that would otherwise be discovered
during the one attempt the issue permits.

The benchmark result is borrowed from the judging tests rather than rebuilt, for the same
reason the candidate tests borrow the production panel: two copies of a fixture drift.
"""

import json
from pathlib import Path

import pytest
from scripts.freeze_candidate_declaration import benchmark_config
from scripts.run_candidate_gate import (
    FREEZE_REQUIREMENT,
    GateRunRefused,
    main,
    read_frozen_record,
    run_record,
    run_record_markdown,
    verify_frozen_fingerprints,
)
from tests.unit.test_production_benchmark import _gates, _result

FROZEN_DECLARATION = "f72962a182e4d857448d860641c7ebc211a4f7101f3ed713362636fa2b3bce09"
FROZEN_CONFIGURATION = "b64a3ab9f06f1c1a207d66c8f1d59b0c3072f7fe8400cb598e378fca37e6f575"


def _frozen(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "candidate_id": "learned_rate_calendar_candidate_v1",
        "declaration": {"candidate_id": "learned_rate_calendar_candidate_v1"},
        "declaration_fingerprint": FROZEN_DECLARATION,
        "benchmark_configuration_fingerprint": FROZEN_CONFIGURATION,
    }
    record.update(overrides)
    return record


def _metadata() -> dict[str, object]:
    return {
        "provenance": {
            "repository_commit": "a" * 40,
            "working_tree_dirty": False,
            "archive_repository": "vaastav/Fantasy-Premier-League",
            "archive_commit": "b" * 40,
        },
        "environment": {"python": "3.13.0", "pandas": "3.0.5", "ortools": "9.15.6755"},
    }


# --- the committed record is what authorises a run --------------------------


def test_the_committed_freeze_record_matches_the_code_today() -> None:
    """If this fails, docs/issue43_candidate_declaration.json and the code have diverged."""

    verify_frozen_fingerprints(read_frozen_record(), config=benchmark_config())


def test_a_moved_declaration_fingerprint_refuses_the_run() -> None:
    with pytest.raises(GateRunRefused, match="would not be the formal run"):
        verify_frozen_fingerprints(
            _frozen(declaration_fingerprint="0" * 64), config=benchmark_config()
        )


def test_a_moved_configuration_fingerprint_refuses_the_run() -> None:
    with pytest.raises(GateRunRefused, match="would not be the formal run"):
        verify_frozen_fingerprints(
            _frozen(benchmark_configuration_fingerprint="0" * 64), config=benchmark_config()
        )


def test_the_refusal_names_both_the_frozen_and_the_current_digest() -> None:
    """A mismatch is only actionable if the reader can see which value moved, and to what."""

    with pytest.raises(GateRunRefused) as raised:
        verify_frozen_fingerprints(
            _frozen(declaration_fingerprint="0" * 64), config=benchmark_config()
        )

    message = str(raised.value)
    assert "0" * 64 in message
    assert FROZEN_DECLARATION in message
    assert "The freeze is void" in message


def test_a_record_without_fingerprints_cannot_authorise_a_run() -> None:
    with pytest.raises(GateRunRefused, match="carries no fingerprints"):
        verify_frozen_fingerprints({}, config=benchmark_config())


def test_a_missing_freeze_record_refuses_rather_than_defaults(tmp_path: Path) -> None:
    with pytest.raises(GateRunRefused, match="Cannot read the freeze record"):
        read_frozen_record(tmp_path / "absent.json")


def test_a_freeze_record_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "record.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    with pytest.raises(GateRunRefused, match="not an object"):
        read_frozen_record(path)


# --- the freeze itself is a human fact, so it is asserted, not read ---------


def test_without_the_confirmation_flag_nothing_runs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The archive is never touched: the refusal happens before any loading."""

    monkeypatch.setattr("sys.argv", ["run_candidate_gate"])

    assert main() == 1

    printed = capsys.readouterr().out
    assert "--confirm-frozen was not given" in printed
    assert "All three owners" in printed


def test_the_refusal_states_the_requirement_rather_than_the_flag_name() -> None:
    """A flag name tells an operator what to type, not what they would be asserting."""

    assert "candidate_declaration_review.md:27" in FREEZE_REQUIREMENT
    assert "is not the formal run" in FREEZE_REQUIREMENT


# --- what a completed run records -------------------------------------------


def test_the_record_carries_everything_the_review_procedure_asks_for() -> None:
    record = run_record(
        _result(_gates()),
        frozen=_frozen(),
        metadata=_metadata(),
        machine_label="a-named-machine",
    )

    assert record["declaration_fingerprint"] == FROZEN_DECLARATION
    assert record["benchmark_configuration_fingerprint"] == FROZEN_CONFIGURATION
    assert record["executed_on"] == "a-named-machine"
    assert record["formal_run"] is True
    assert record["locked_holdout_accessed"] is False
    assert "judgement" in record
    assert "provenance" in record
    assert "environment" in record


def test_the_record_states_the_verdict_as_produced() -> None:
    """Recorded even when — especially when — the candidate fails."""

    result = _result(_gates())
    record = run_record(result, frozen=_frozen(), metadata=_metadata(), machine_label="host")

    assert record["verdict"] == result.verdict
    assert record["verdict"] == "no_promotion_control_retained"


def test_the_summary_names_the_machine_the_commit_and_the_failing_gates() -> None:
    record = run_record(
        _result(_gates()), frozen=_frozen(), metadata=_metadata(), machine_label="host-7"
    )

    text = run_record_markdown(record)

    assert "host-7" in text
    assert "a" * 40 in text
    assert FROZEN_DECLARATION in text
    assert "**FAIL**" in text
    assert "not an operational promotion" in text


def test_a_dirty_working_tree_is_named_in_the_summary() -> None:
    """A run from an uncommitted tree cannot be reproduced from the commit it claims."""

    metadata = _metadata()
    provenance = metadata["provenance"]
    assert isinstance(provenance, dict)
    provenance["working_tree_dirty"] = True

    text = run_record_markdown(
        run_record(_result(_gates()), frozen=_frozen(), metadata=metadata, machine_label="host")
    )

    assert "working tree dirty" in text
