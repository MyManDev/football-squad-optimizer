"""Readiness refuses wrong-week, late, missing and changed paired inputs, and pairs the
current arm by default 1 of ``docs/football_prospective_pairing_note.md``.

Every root here is synthetic: captures from ``write_snapshot``, artifacts and receipts
written as the shadow builder writes them, advice records written through
``record_member_advice``. No member capture is read.
"""

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
from scripts import build_football_shadow as shadow
from scripts import football_prospective_inputs as helper
from scripts.check_football_prospective_inputs import audit
from tests.unit.test_football_prospective_prereg import _artifact
from tests.unit.test_live_recommendation import SEASON, _capture

from squadopt.application.advice_record import record_directory, record_member_advice
from squadopt.data.errors import DataError
from squadopt.data.timestamps import as_instant
from squadopt.live.football_artifact import football_artifact_path
from squadopt.live.recommendation import (
    InSeasonProjection,
    RecommendationInputs,
    read_inputs,
    write_projection_handoff,
)
from squadopt.live.tick import handoff_path_for
from squadopt.prediction.component_dataset import FEATURE_CONTRACT_VERSION
from squadopt.prediction.component_models import COMPONENT_MODEL_VERSION

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"

#: The fixture's target gameweek and its deadline (``EVENTS`` in test_live_recommendation).
WEEK = 2
DEADLINE = "2026-08-28T17:30:00Z"
CAPTURED = "2026-08-22T09:00:00Z"
BEFORE_DEADLINE = "2026-08-22T10:00:00Z"
AT_DEADLINE = "2026-08-28T17:30:00Z"
AFTER_DEADLINE = "2026-08-28T18:00:00Z"


def _set_write_time(path: Path, instant: str) -> None:
    timestamp = as_instant(instant).timestamp()
    os.utime(path, (timestamp, timestamp))


def _inputs(tmp_path: Path, identifier: str) -> RecommendationInputs:
    from squadopt.data.snapshots import read_snapshot

    return read_inputs(
        read_snapshot(tmp_path / "snapshots", identifier), season=SEASON, gameweek=None
    )


def _handoff(inputs: RecommendationInputs, points: float = 3.0) -> InSeasonProjection:
    return InSeasonProjection(
        SEASON,
        inputs.deadline.gameweek,
        inputs.snapshot_id,
        "control",
        COMPONENT_MODEL_VERSION,
        FEATURE_CONTRACT_VERSION,
        {int(p): points for p in inputs.players.player_id},
    )


def retained_path(tmp_path: Path, identifier: str, name: str = "forecast.json") -> Path:
    return tmp_path / "handoffs" / "by-capture" / identifier / name


def alias_path(tmp_path: Path) -> Path:
    return handoff_path_for(tmp_path / "handoffs", SEASON, WEEK)


def write_handoff(
    path: Path, inputs: RecommendationInputs, *, points: float = 3.0, written: str = CAPTURED
) -> str:
    """Write a handoff with the given write time and return its fingerprint."""

    handoff = _handoff(inputs, points)
    write_projection_handoff(path, handoff)
    _set_write_time(path, written)
    return handoff.fingerprint


def bundle(tmp_path: Path, captured: str = CAPTURED, *, handoff: bool = True) -> str:
    """A capture, its v1 artifact and, unless told otherwise, one retained handoff."""

    snapshot = _capture(tmp_path / "snapshots", captured_at=captured)
    inputs = read_inputs(snapshot, season=SEASON, gameweek=None)
    identifier = inputs.snapshot_id
    path = football_artifact_path(tmp_path / "artifacts", identifier)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_artifact(inputs)))
    timestamp = as_instant(captured).timestamp() + 60
    os.utime(path, (timestamp, timestamp))
    if handoff:
        write_handoff(retained_path(tmp_path, identifier), inputs, written=captured)
    return identifier


def write_receipt(tmp_path: Path, identifier: str, **overrides: Any) -> Path:
    """A receipt as the shadow builder writes one for the fixture's artifact."""

    artifact = football_artifact_path(tmp_path / "artifacts", identifier)
    document = json.loads(artifact.read_text(encoding="utf-8"))
    receipt = {
        "contract_version": shadow.RECEIPT_CONTRACT,
        "snapshot_id": identifier,
        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "fingerprint": document["fingerprint"],
        "served": False,
    }
    receipt.update(overrides)
    path = tmp_path / "artifacts" / "receipts" / (identifier + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path


def write_record(
    tmp_path: Path,
    identifier: str,
    entry_id: int,
    fingerprint: str,
    *,
    generated_at: str = BEFORE_DEADLINE,
) -> Path:
    """One member's advice record of the capture, naming the handoff it was built from."""

    record = {
        "contract_version": "synthetic",
        "season": SEASON,
        "gameweek": WEEK,
        "entry_id": entry_id,
        "capture": {"snapshot_id": identifier, "captured_at_utc": CAPTURED},
        "generated_at_utc": generated_at,
        "provenance": {"projection_handoff_fingerprint": fingerprint},
    }
    return record_member_advice(tmp_path / "records", record)


def check(
    tmp_path: Path, ids: list[str], week: int = WEEK, *, records: bool = False
) -> dict[str, Any]:
    return audit(
        tmp_path / "snapshots",
        tmp_path / "handoffs",
        tmp_path / "artifacts",
        snapshot_ids=ids,
        season=SEASON,
        gameweeks=[week],
        as_of="2026-08-29T00:00:00Z",
        advice_record_root=tmp_path / "records" if records else None,
    )


def pair(tmp_path: Path, identifier: str, *, records: bool = True) -> helper.CurrentPairing:
    return helper.pair_current(
        tmp_path / "handoffs",
        _inputs(tmp_path, identifier),
        advice_record_root=tmp_path / "records" if records else None,
    )


# The check as it was: wrong-week, late, missing and changed inputs.


def test_real_readers_pair_forecasts_without_outcomes(tmp_path: Path) -> None:
    identifier = bundle(tmp_path)
    result = check(tmp_path, [identifier])
    assert result["outcomes_read"] is False
    assert result["advice_records_read"] is False
    row = result["weeks"][0]
    assert row["status"] == "inputs_ready"
    assert row["paired_players"] == 24
    assert row["capture_selection_final"] is True
    assert row["own_target"] == 2
    assert row["pairing_branch"] == "b"
    assert row["handoff_write_utc"] == as_instant(CAPTURED).isoformat()
    assert row["backend_rule_fingerprint"] == row["current_fingerprint"]
    assert row["backend_rule_differs"] is False
    assert row["receipt_matches"] is False
    assert row["receipt_status"] == "absent"
    assert row["football_served"] is None


def test_previous_target_is_never_borrowed(tmp_path: Path) -> None:
    identifier = bundle(tmp_path, "2026-08-13T20:11:43Z")
    assert check(tmp_path, [identifier])["weeks"][0]["reason"] == "no_own_target_capture"


@pytest.mark.parametrize("failure", ["missing", "late", "corrupt", "current"])
def test_latest_unusable_capture_never_falls_back(tmp_path: Path, failure: str) -> None:
    older = bundle(tmp_path)
    latest = bundle(tmp_path, "2026-08-23T09:00:00Z")
    path = football_artifact_path(tmp_path / "artifacts", latest)
    if failure == "missing":
        path.unlink()
    elif failure == "late":
        _set_write_time(path, DEADLINE)
    elif failure == "corrupt":
        path.write_text("{}")
    else:
        retained_path(tmp_path, latest).write_text("{}")
    row = check(tmp_path, [latest, older])["weeks"][0]
    assert row["snapshot_id"] == latest
    assert row["status"] == "missing"
    if failure == "current":
        assert row["reason"] == helper.UNPAIRED_REASON
        assert row["pairing_branch"] == "c"
    else:
        assert row["reason"] == "football_missing_invalid_or_late"


def test_future_capture_and_duplicate_inventory_are_refused(tmp_path: Path) -> None:
    identifier = bundle(tmp_path)
    with pytest.raises(ValueError, match="unique"):
        check(tmp_path, [identifier, identifier])
    with pytest.raises(ValueError, match="later"):
        audit(
            tmp_path / "snapshots",
            tmp_path / "handoffs",
            tmp_path / "artifacts",
            snapshot_ids=[identifier],
            season=SEASON,
            gameweeks=[2],
            as_of="2026-08-21T00:00:00Z",
        )


def test_before_deadline_ready_is_only_provisional(tmp_path: Path) -> None:
    identifier = bundle(tmp_path)
    result = audit(
        tmp_path / "snapshots",
        tmp_path / "handoffs",
        tmp_path / "artifacts",
        snapshot_ids=[identifier],
        season=SEASON,
        gameweeks=[2],
        as_of="2026-08-24T00:00:00Z",
    )
    assert result["weeks"][0]["status"] == "inputs_ready"
    assert result["weeks"][0]["capture_selection_final"] is False


def test_naive_audit_instant_is_rejected_before_any_capture_read(tmp_path: Path) -> None:
    from squadopt.data.errors import DataSourceError

    with pytest.raises(DataSourceError, match="timezone"):
        audit(
            tmp_path,
            tmp_path,
            tmp_path,
            snapshot_ids=["unused"],
            season=SEASON,
            gameweeks=[2],
            as_of="2026-08-24T00:00:00",
        )


# Neither script reaches the backend.


@pytest.mark.parametrize(
    "script", ["check_football_prospective_inputs.py", "football_prospective_inputs.py"]
)
def test_neither_prospective_script_imports_the_platform(script: str) -> None:
    source = (SCRIPTS / script).read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import)\s+squadopt\.platform", source, re.MULTILINE)
    # The finish condition is a grep, so the name is absent from the prose as well.
    assert "squadopt.platform" not in source


def test_the_receipt_contract_is_the_shadow_builders() -> None:
    assert helper.SHADOW_RECEIPT_CONTRACT == shadow.RECEIPT_CONTRACT
    assert helper.UNPAIRED_REASON == "cannot pair the scored capture with exactly one handoff"


# Default 1, branch a: the handoff the published plans used.


def test_branch_a_pairs_the_fingerprint_every_pre_deadline_record_names(tmp_path: Path) -> None:
    identifier = bundle(tmp_path)
    recorded = _handoff(_inputs(tmp_path, identifier)).fingerprint
    for entry in (101, 102, 103):
        write_record(tmp_path, identifier, entry, recorded)
    pairing = pair(tmp_path, identifier)
    assert pairing.branch == "a"
    assert pairing.fingerprint == recorded
    assert pairing.model_version == COMPONENT_MODEL_VERSION
    assert pairing.path == retained_path(tmp_path, identifier)
    assert pairing.write_utc == as_instant(CAPTURED).isoformat()
    assert pairing.records_counted == 3
    assert pairing.record_fingerprints == (recorded,)
    assert pairing.replay is False
    assert pairing.backend_rule_fingerprint == recorded
    assert pairing.backend_rule_differs is False
    row = check(tmp_path, [identifier], records=True)["weeks"][0]
    assert row["status"] == "inputs_ready"
    assert row["pairing_branch"] == "a"
    assert row["advice_records_counted"] == 3
    assert row["current_fingerprint"] == recorded


def test_the_364991a4f832_shape_picks_the_recorded_handoff_over_the_rewritten_alias(
    tmp_path: Path,
) -> None:
    """The alias was rebuilt after the plans were published; the records name the retained copy."""

    identifier = bundle(tmp_path)
    inputs = _inputs(tmp_path, identifier)
    recorded = _handoff(inputs).fingerprint
    rewritten = write_handoff(alias_path(tmp_path), inputs, points=4.0, written=AFTER_DEADLINE)
    assert rewritten != recorded
    for entry in (101, 102):
        write_record(tmp_path, identifier, entry, recorded)
    pairing = pair(tmp_path, identifier)
    assert pairing.branch == "a"
    assert pairing.fingerprint == recorded
    assert pairing.path == retained_path(tmp_path, identifier)
    assert pairing.replay is False
    # What the backend rule selects at reading time is the alias, and the difference is flagged.
    assert pairing.backend_rule_fingerprint == rewritten
    assert pairing.backend_rule_differs is True
    row = check(tmp_path, [identifier], records=True)["weeks"][0]
    assert row["status"] == "inputs_ready"
    assert row["current_fingerprint"] == recorded
    assert row["backend_rule_fingerprint"] == rewritten
    assert row["backend_rule_differs"] is True
    assert row["handoff_write_utc"] == as_instant(CAPTURED).isoformat()


def test_branch_a_reports_the_alias_when_only_the_alias_carries_the_fingerprint(
    tmp_path: Path,
) -> None:
    identifier = bundle(tmp_path, handoff=False)
    inputs = _inputs(tmp_path, identifier)
    recorded = write_handoff(alias_path(tmp_path), inputs, written=CAPTURED)
    write_record(tmp_path, identifier, 101, recorded)
    pairing = pair(tmp_path, identifier)
    assert pairing.branch == "a"
    assert pairing.path == alias_path(tmp_path)
    assert pairing.fingerprint == recorded


@pytest.mark.parametrize("generated_at", [AT_DEADLINE, AFTER_DEADLINE])
def test_a_record_published_at_or_after_the_deadline_does_not_count(
    tmp_path: Path, generated_at: str
) -> None:
    identifier = bundle(tmp_path)
    inputs = _inputs(tmp_path, identifier)
    recorded = _handoff(inputs).fingerprint
    rewritten = write_handoff(alias_path(tmp_path), inputs, points=4.0, written=CAPTURED)
    write_record(tmp_path, identifier, 101, recorded, generated_at=generated_at)
    pairing = pair(tmp_path, identifier)
    assert pairing.records_counted == 0
    assert pairing.record_fingerprints == ()
    assert pairing.branch == "b"
    assert pairing.fingerprint == rewritten


def test_records_naming_two_fingerprints_give_a_missing_week(tmp_path: Path) -> None:
    identifier = bundle(tmp_path)
    inputs = _inputs(tmp_path, identifier)
    first = _handoff(inputs).fingerprint
    second = write_handoff(
        retained_path(tmp_path, identifier, "second.json"), inputs, points=4.0, written=CAPTURED
    )
    write_record(tmp_path, identifier, 101, first)
    write_record(tmp_path, identifier, 102, second)
    pairing = pair(tmp_path, identifier)
    assert pairing.branch == "c"
    assert pairing.handoff is None
    assert pairing.reason == helper.UNPAIRED_REASON
    assert pairing.record_fingerprints == tuple(sorted((first, second)))
    assert pairing.records_counted == 2
    row = check(tmp_path, [identifier], records=True)["weeks"][0]
    assert row["status"] == "missing"
    assert row["reason"] == helper.UNPAIRED_REASON
    assert row["pairing_branch"] == "c"
    assert row["current_fingerprint"] is None


def test_a_recorded_fingerprint_without_a_file_gives_a_missing_week_not_branch_b(
    tmp_path: Path,
) -> None:
    identifier = bundle(tmp_path)
    write_record(tmp_path, identifier, 101, "0" * 64)
    pairing = pair(tmp_path, identifier)
    assert pairing.branch == "c"
    assert pairing.reason == helper.UNPAIRED_REASON
    assert "recorded fingerprint" in str(pairing.detail)
    # The backend rule would have paired the retained copy; branch a does not fall to it.
    assert pairing.backend_rule_fingerprint == _handoff(_inputs(tmp_path, identifier)).fingerprint
    assert check(tmp_path, [identifier], records=True)["weeks"][0]["status"] == "missing"


def test_a_record_of_another_capture_is_not_read_for_this_one(tmp_path: Path) -> None:
    older = bundle(tmp_path)
    latest = bundle(tmp_path, "2026-08-23T09:00:00Z")
    write_record(tmp_path, older, 101, "1" * 64)
    pairing = pair(tmp_path, latest)
    assert pairing.branch == "b"
    assert pairing.records_counted == 0


def test_a_record_that_fails_its_digest_refuses_rather_than_falling_to_branch_b(
    tmp_path: Path,
) -> None:
    identifier = bundle(tmp_path)
    recorded = _handoff(_inputs(tmp_path, identifier)).fingerprint
    directory = write_record(tmp_path, identifier, 101, recorded)
    assert directory == record_directory(tmp_path / "records", SEASON, WEEK, 101, identifier)
    (directory / "advice.json").write_text("{}", encoding="utf-8")
    with pytest.raises(DataError, match="digest"):
        pair(tmp_path, identifier)


# Default 1, branch b: the backend's rule, and a late file is a replay.


def test_branch_b_pairs_the_unique_retained_copy_when_no_record_exists(tmp_path: Path) -> None:
    identifier = bundle(tmp_path)
    pairing = pair(tmp_path, identifier)
    assert pairing.branch == "b"
    assert pairing.fingerprint == _handoff(_inputs(tmp_path, identifier)).fingerprint
    assert pairing.path == retained_path(tmp_path, identifier)
    assert pairing.replay is False
    assert pairing.records_counted == 0


@pytest.mark.parametrize("written", [AT_DEADLINE, AFTER_DEADLINE])
def test_a_late_file_under_branch_b_makes_the_week_a_replay(tmp_path: Path, written: str) -> None:
    identifier = bundle(tmp_path)
    _set_write_time(retained_path(tmp_path, identifier), written)
    pairing = pair(tmp_path, identifier)
    assert pairing.branch == "b"
    assert pairing.replay is True
    assert pairing.write_utc == as_instant(written).isoformat()
    row = check(tmp_path, [identifier])["weeks"][0]
    assert row["status"] == "replay"
    assert row["reason"] == "current_handoff_written_at_or_after_deadline"
    assert row["pairing_branch"] == "b"
    assert row["handoff_write_utc"] == as_instant(written).isoformat()
    assert row["current_fingerprint"] == pairing.fingerprint


def test_a_late_file_under_branch_a_is_not_a_replay(tmp_path: Path) -> None:
    """Branch a's pre-deadline records attest the handoff; the file's own time does not decide."""

    identifier = bundle(tmp_path)
    recorded = _handoff(_inputs(tmp_path, identifier)).fingerprint
    _set_write_time(retained_path(tmp_path, identifier), AFTER_DEADLINE)
    write_record(tmp_path, identifier, 101, recorded)
    pairing = pair(tmp_path, identifier)
    assert pairing.branch == "a"
    assert pairing.replay is False
    assert check(tmp_path, [identifier], records=True)["weeks"][0]["status"] == "inputs_ready"


@pytest.mark.parametrize("shape", ["none", "two"])
def test_branch_b_with_none_or_two_matches_gives_a_missing_week(tmp_path: Path, shape: str) -> None:
    identifier = bundle(tmp_path, handoff=shape == "two")
    if shape == "two":
        write_handoff(
            retained_path(tmp_path, identifier, "second.json"),
            _inputs(tmp_path, identifier),
            points=4.0,
        )
    pairing = pair(tmp_path, identifier)
    assert pairing.branch == "c"
    assert pairing.reason == helper.UNPAIRED_REASON
    assert pairing.backend_rule_fingerprint is None
    assert check(tmp_path, [identifier])["weeks"][0]["reason"] == helper.UNPAIRED_REASON


# Branch b is the backend's rule: pinned to load_capture_identity while that helper exists.
# The backend helper skips a file that raises OSError; the helper here refuses it, so that
# case is not among these.

BACKEND_CASES = [
    "absent",
    "alias_invalid",
    "alias_mismatched",
    "alias_precedence",
    "retained_unique",
    "retained_same_fingerprint_twice",
    "retained_two_fingerprints",
    "retained_invalid_beside_one",
    "retained_mismatched_beside_one",
]


def _backend_case(tmp_path: Path, case: str) -> str:
    """Build the handoff root for one case and return the capture it is for."""

    identifier = bundle(tmp_path, handoff=case != "absent")
    inputs = _inputs(tmp_path, identifier)
    other = _inputs(tmp_path, bundle(tmp_path, "2026-08-13T20:11:43Z", handoff=False))
    if case == "alias_invalid":
        alias_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        alias_path(tmp_path).write_text("{}", encoding="utf-8")
    elif case == "alias_mismatched":
        write_handoff(alias_path(tmp_path), other)
    elif case == "alias_precedence":
        write_handoff(alias_path(tmp_path), inputs, points=4.0)
    elif case == "retained_same_fingerprint_twice":
        write_handoff(retained_path(tmp_path, identifier, "copy.json"), inputs)
    elif case == "retained_two_fingerprints":
        write_handoff(retained_path(tmp_path, identifier, "second.json"), inputs, points=4.0)
    elif case == "retained_invalid_beside_one":
        retained_path(tmp_path, identifier, "broken.json").write_text("[]", encoding="utf-8")
    elif case == "retained_mismatched_beside_one":
        write_handoff(retained_path(tmp_path, identifier, "other.json"), other)
    return identifier


@pytest.mark.parametrize("case", BACKEND_CASES)
def test_branch_b_equals_load_capture_identity(tmp_path: Path, case: str) -> None:
    from squadopt.platform.capture_context import load_capture_identity

    identifier = _backend_case(tmp_path, case)
    try:
        expected: str | None = load_capture_identity(
            snapshot_root=tmp_path / "snapshots",
            snapshot_id=identifier,
            handoff_root=tmp_path / "handoffs",
            advice_contract_version="test",
            repository_commit="test",
            configuration_fingerprint="test",
            season=SEASON,
        ).handoff.fingerprint
    except DataError:
        expected = None
    selected = helper.backend_rule_handoff(tmp_path / "handoffs", SEASON, WEEK, identifier)
    assert (None if selected is None else selected[1].fingerprint) == expected
    pairing = pair(tmp_path, identifier, records=False)
    assert pairing.backend_rule_fingerprint == expected
    assert pairing.branch == ("c" if expected is None else "b")
    assert pairing.fingerprint == expected
    if case == "alias_precedence":
        assert pairing.path == alias_path(tmp_path)
    elif expected is not None:
        assert (
            pairing.path is not None
            and pairing.path.parent == retained_path(tmp_path, identifier).parent
        )


def test_the_backend_case_list_covers_the_note(tmp_path: Path) -> None:
    """Absent, invalid and mismatched alias and retained files, alias precedence, uniqueness."""

    assert {"absent", "alias_invalid", "alias_mismatched", "alias_precedence"} <= set(BACKEND_CASES)
    assert {"retained_unique", "retained_two_fingerprints", "retained_invalid_beside_one"} <= set(
        BACKEND_CASES
    )


# Default 2: the shadow artifact and its receipt.


def test_a_receipt_matching_the_artifact_bytes_reports_the_week_unserved(tmp_path: Path) -> None:
    identifier = bundle(tmp_path)
    write_receipt(tmp_path, identifier)
    artifact = helper.shadow_artifact(tmp_path / "artifacts", _inputs(tmp_path, identifier))
    assert artifact.status == "usable"
    assert artifact.receipt_matches is True
    assert artifact.receipt_status == "matches"
    assert artifact.football_served is False
    assert artifact.sha256 == hashlib.sha256(artifact.path.read_bytes()).hexdigest()
    row = check(tmp_path, [identifier])["weeks"][0]
    assert row["status"] == "inputs_ready"
    assert row["receipt_matches"] is True
    assert row["football_served"] is False


@pytest.mark.parametrize(
    ("overrides", "status", "served"),
    [
        ({"artifact_sha256": "0" * 64}, "sha256_mismatch", False),
        ({"fingerprint": "0" * 64}, "fingerprint_mismatch", False),
        ({"snapshot_id": "fpl-live-other"}, "other_capture", False),
        ({"served": True}, "served", True),
        ({"served": "no"}, "served_not_recorded", None),
        ({"contract_version": "other"}, "not_a_receipt", None),
    ],
)
def test_a_receipt_that_does_not_match_is_listed_and_excludes_nothing(
    tmp_path: Path, overrides: dict[str, Any], status: str, served: bool | None
) -> None:
    identifier = bundle(tmp_path)
    write_receipt(tmp_path, identifier, **overrides)
    row = check(tmp_path, [identifier])["weeks"][0]
    assert row["status"] == "inputs_ready"
    assert row["receipt_matches"] is False
    assert row["receipt_status"] == status
    assert row["football_served"] is served


def test_an_unreadable_receipt_is_listed(tmp_path: Path) -> None:
    identifier = bundle(tmp_path)
    write_receipt(tmp_path, identifier).write_text("{", encoding="utf-8")
    row = check(tmp_path, [identifier])["weeks"][0]
    assert row["receipt_status"] == "unreadable"
    assert row["receipt_matches"] is False


def test_the_receipt_is_read_beside_the_artifact_root_only(tmp_path: Path) -> None:
    identifier = bundle(tmp_path)
    elsewhere = tmp_path / "elsewhere" / "receipts" / (identifier + ".json")
    elsewhere.parent.mkdir(parents=True)
    elsewhere.write_text(json.dumps({"contract_version": shadow.RECEIPT_CONTRACT, "served": False}))
    artifact = helper.shadow_artifact(tmp_path / "artifacts", _inputs(tmp_path, identifier))
    assert artifact.receipt_path == tmp_path / "artifacts" / "receipts" / (identifier + ".json")
    assert artifact.receipt_status == "absent"


@pytest.mark.parametrize("damage", ["missing", "late", "corrupt", "after_audit"])
def test_the_artifact_status_names_each_failure(tmp_path: Path, damage: str) -> None:
    identifier = bundle(tmp_path)
    inputs = _inputs(tmp_path, identifier)
    path = football_artifact_path(tmp_path / "artifacts", identifier)
    write_receipt(tmp_path, identifier)
    as_of = as_instant("2026-08-29T00:00:00Z")
    if damage == "missing":
        path.unlink()
    elif damage == "late":
        _set_write_time(path, DEADLINE)
    elif damage == "corrupt":
        path.write_text("{}")
    else:
        _set_write_time(path, "2026-08-27T00:00:00Z")
        as_of = as_instant("2026-08-26T00:00:00Z")
    artifact = helper.shadow_artifact(tmp_path / "artifacts", inputs, as_of=as_of)
    expected = {"missing": "missing", "late": "late", "corrupt": "invalid", "after_audit": "late"}
    assert artifact.status == expected[damage]
    assert artifact.receipt_matches is (damage in ("late", "after_audit"))
    if damage == "corrupt":
        assert artifact.receipt_status == "artifact_invalid"
        assert artifact.football_served is False
    assert (artifact.forecast is None) is (damage in ("missing", "corrupt"))


def test_the_shadow_builders_receipt_passes_the_helpers_check(tmp_path: Path) -> None:
    """The keys the helper compares are the ones the builder writes."""

    for key in ("snapshot_id", "artifact_sha256", "fingerprint", "served", "contract_version"):
        assert key in shadow.RECEIPT_KEYS


# The scored capture rule.


def test_scored_capture_is_the_last_own_target_capture_and_a_tie_is_ambiguous(
    tmp_path: Path,
) -> None:
    first = _inputs(tmp_path, bundle(tmp_path))
    later = _inputs(tmp_path, bundle(tmp_path, "2026-08-23T09:00:00Z"))
    earlier_week = _inputs(tmp_path, bundle(tmp_path, "2026-08-13T20:11:43Z"))
    selection = helper.scored_capture([first, earlier_week, later], WEEK)
    assert selection.inputs is later and selection.reason is None
    assert helper.scored_capture([first, later], 1).reason == "no_own_target_capture"
    assert helper.scored_capture([earlier_week], 1).inputs is earlier_week
    tied = helper.scored_capture([later, later], WEEK)
    assert tied.inputs is None and tied.reason == "ambiguous_latest_capture"
