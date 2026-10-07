"""Synthetic identity, cutoff, label, whole-week and once-only DEFCON checks."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from scripts import measure_defcon_component as runner
from tests.unit.test_season_rules import _chips, _rules, _scoring

from squadopt.application.defcon_component import (
    DefconInputError,
    DefconMissingInputs,
    candidate_handoff,
    decode,
)
from squadopt.data.errors import DataSourceError
from squadopt.data.snapshots import CapturedSnapshot, read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD, live_payload
from squadopt.experiments.defcon_component_reading import PairedDefconRow, summarize
from squadopt.live.recommendation import (
    IN_SEASON_CONTROL_MODEL_VERSIONS,
    InSeasonProjection,
    project,
    read_inputs,
    read_projection_handoff,
    write_projection_handoff,
)

START = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)


def stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def capture(
    tmp_path: Path,
    *,
    target: int = 6,
    final: bool = False,
    double: bool = False,
    change: Any = None,
    instant_offset: int = 0,
) -> CapturedSnapshot:
    events = [
        {
            "id": w,
            "deadline_time": stamp(START + timedelta(weeks=w - 1)),
            "finished": final or w < target,
        }
        for w in range(1, 14)
    ]
    elements = [
        {
            "id": i,
            "code": 100 + i,
            "element_type": i,
            "team": 1,
            "first_name": "Synthetic",
            "second_name": str(i),
            "now_cost": 50,
            "status": "d" if i == 2 else "a",
            "chance_of_playing_next_round": 50 if i == 2 else None,
            "news_added": None,
        }
        for i in range(1, 5)
    ]
    bootstrap = {
        "events": events,
        "elements": elements,
        "teams": [{"id": 1, "name": "Home"}, {"id": 2, "name": "Away"}],
        "game_config": {"rules": _rules(), "scoring": _scoring()},
        "chips": _chips(),
    }
    fixtures = [
        {
            "id": w,
            "event": w,
            "team_h": 1,
            "team_a": 2,
            "kickoff_time": stamp(START + timedelta(weeks=w - 1, hours=2)),
            "finished": final or w < target,
            "finished_provisional": final or w < target,
        }
        for w in range(1, 14)
    ]
    if double:
        fixtures.append({**fixtures[target - 1], "id": 99})
        fixtures.append({**fixtures[0], "id": 98})
    documents: dict[str, Any] = {BOOTSTRAP_PAYLOAD: bootstrap, FIXTURES_PAYLOAD: fixtures}
    for week in range(1, 14 if final else target):
        week_fixtures = [f for f in fixtures if f["event"] == week]
        live_elements = []
        for i in range(1, 5):
            explanations = []
            for fixture in week_fixtures:
                stats = [
                    {"identifier": "minutes", "value": 90, "points": 2, "points_modification": 0}
                ]
                if i > 1:
                    stats.append(
                        {
                            "identifier": "defensive_contribution",
                            "value": 15,
                            "points": 2,
                            "points_modification": 0,
                        }
                    )
                explanations.append({"fixture": fixture["id"], "stats": stats})
            live_elements.append(
                {
                    "id": i,
                    "stats": {
                        "minutes": 90 * len(week_fixtures),
                        "total_points": i,
                        "defensive_contribution": 15 * len(week_fixtures),
                    },
                    "explain": explanations,
                }
            )
        documents[live_payload(week)] = {"elements": live_elements}
    if change:
        change(documents)
    instant = START + timedelta(
        weeks=(12 if final else target - 1), hours=(-1 if not final else 8), seconds=instant_offset
    )
    metadata = write_snapshot(
        tmp_path,
        source="fpl-live",
        captured_at_utc=stamp(instant),
        payloads={name: json.dumps(doc).encode() for name, doc in documents.items()},
    )
    return read_snapshot(tmp_path, metadata.snapshot_id)


def base(snapshot: CapturedSnapshot, *, target: int = 6) -> InSeasonProjection:
    return InSeasonProjection(
        "2026-27",
        target,
        snapshot.metadata.snapshot_id,
        "component",
        "phase_c_control_components_v1",
        "phase_c_component_form_window_v1",
        {101: 2.0, 102: 3.0, 103: 4.0, 104: 5.0},
        appearance_probability={101: 1.0, 102: 0.8, 103: 0.9, 104: 0.7},
    )


def publication(
    tmp_path: Path,
    snapshot: CapturedSnapshot,
    handoff: InSeasonProjection,
    *,
    generated_offset: int = 20,
) -> Path:
    path = (
        tmp_path
        / "publications"
        / "2026-27"
        / f"gw{handoff.gameweek:02d}"
        / "entry-1"
        / snapshot.metadata.snapshot_id
        / "advice.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "contract_version": "member_advice_record_v2",
                "player_id_space": "fpl_element_code",
                "season": "2026-27",
                "gameweek": handoff.gameweek,
                "generated_at_utc": stamp(
                    datetime.fromisoformat(snapshot.metadata.captured_at_utc)
                    + timedelta(seconds=generated_offset)
                ),
                "capture": {
                    "snapshot_id": snapshot.metadata.snapshot_id,
                    "captured_at_utc": snapshot.metadata.captured_at_utc,
                },
                "provenance": {"projection_handoff_fingerprint": handoff.fingerprint},
            }
        )
    )
    handoff_path = (
        tmp_path / "handoffs" / "by-capture" / snapshot.metadata.snapshot_id / "default.json"
    )
    write_projection_handoff(handoff_path, handoff)
    seconds = datetime.fromisoformat(snapshot.metadata.captured_at_utc).timestamp()
    os.utime(handoff_path, (seconds, seconds))
    return path


def test_pure_augmentation_preserves_base_and_applies_availability_once(tmp_path: Path) -> None:
    snapshot = capture(tmp_path, double=True)
    original = base(snapshot)
    candidate = candidate_handoff(snapshot, original, declaration_sha256=runner.DECLARATION_SHA256)
    assert original.expected_points[102] == 3.0
    assert candidate.expected_points[101] == original.expected_points[101]
    assert candidate.expected_points[102] == pytest.approx(3 + 2 * 0.8 * 2)
    assert candidate.appearance_probability == original.appearance_probability
    assert candidate.evidence_fingerprint == original.evidence_fingerprint
    assert candidate.model_version not in IN_SEASON_CONTROL_MODEL_VERSIONS
    inputs = read_inputs(snapshot, season="2026-27", gameweek=6)
    table = project(inputs, in_season=candidate).table.set_index("player_id")
    assert table.loc[102, "expected_points"] == pytest.approx((3 + 3.2) * 0.5)
    rates = candidate.diagnostics["defcon_component"]["rates"]
    assert rates["player_appearances"]["102"] == 6
    assert rates["position_appearances"]["DEF"] == 6
    path = write_projection_handoff(tmp_path / "candidate.json", candidate)
    assert read_projection_handoff(path).fingerprint == candidate.fingerprint
    assert (
        candidate_handoff(snapshot, original, declaration_sha256="b" * 64).fingerprint
        != candidate.fingerprint
    )
    altered = json.loads(path.read_text())
    altered["augmentation_fingerprint"] = "a" * 64
    path.write_text(json.dumps(altered))
    with pytest.raises(DataSourceError, match="fingerprint"):
        read_projection_handoff(path)


@pytest.mark.parametrize(
    "corruption", ["modification", "minutes", "fixture", "duplicate", "late", "season"]
)
def test_bad_fit_inputs_are_refused(tmp_path: Path, corruption: str) -> None:
    def change(documents: dict[str, Any]) -> None:
        entry = documents[live_payload(1)]["elements"][1]
        if corruption == "modification":
            entry["explain"][0]["stats"][1]["points_modification"] = 1
        elif corruption == "minutes":
            entry["explain"][0]["stats"] = entry["explain"][0]["stats"][1:]
        elif corruption == "fixture":
            entry["explain"][0]["fixture"] = 2
        elif corruption == "duplicate":
            entry["explain"].append(entry["explain"][0])
        elif corruption == "late":
            documents[FIXTURES_PAYLOAD][0]["kickoff_time"] = stamp(START + timedelta(weeks=5))
        else:
            documents[BOOTSTRAP_PAYLOAD]["events"][0]["deadline_time"] = "2025-08-21T17:30:00Z"

    snapshot = capture(tmp_path, change=change)
    with pytest.raises((DefconInputError, DefconMissingInputs)):
        candidate_handoff(snapshot, base(snapshot), declaration_sha256=runner.DECLARATION_SHA256)


def test_forbidden_handoff_is_refused_before_payload_access(tmp_path: Path) -> None:
    snapshot = capture(tmp_path)
    with pytest.raises(DefconInputError, match="2025-26"):
        candidate_handoff(
            CapturedSnapshot(snapshot.metadata, {}),
            replace(base(snapshot), season="2025-26"),
            declaration_sha256=runner.DECLARATION_SHA256,
        )


def test_missing_award_means_zero_and_unmapped_history_is_excluded(tmp_path: Path) -> None:
    def change(documents: dict[str, Any]) -> None:
        for w in range(1, 6):
            entry = documents[live_payload(w)]["elements"][1]
            entry["explain"][0]["stats"] = entry["explain"][0]["stats"][:1]
            entry["stats"]["defensive_contribution"] = 0
            documents[live_payload(w)]["elements"].append(
                {"id": 999, "stats": {"minutes": 90}, "explain": []}
            )

    snapshot = capture(tmp_path, change=change)
    candidate = candidate_handoff(
        snapshot, base(snapshot), declaration_sha256=runner.DECLARATION_SHA256
    )
    assert candidate.expected_points[102] == 3
    assert candidate.diagnostics["defcon_component"]["unmapped_history"]["1"] == [999]


def test_development_threshold_crosschecks_zero_award_without_creating_a_label(
    tmp_path: Path,
) -> None:
    def change(documents: dict[str, Any]) -> None:
        entry = documents[live_payload(1)]["elements"][1]
        entry["explain"][0]["stats"] = entry["explain"][0]["stats"][:1]

    snapshot = capture(tmp_path, change=change)
    with pytest.raises(DefconMissingInputs, match="count and awarded"):
        candidate_handoff(snapshot, base(snapshot), declaration_sha256=runner.DECLARATION_SHA256)


def test_outcome_free_checker_never_opens_any_event_live_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = capture(tmp_path / "snapshots")
    publication(tmp_path, snapshot, base(snapshot))
    original = Path.read_bytes
    opened = []

    def checked(path: Path) -> bytes:
        assert not re_event(path.name)
        opened.append(path.name)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", checked)
    captures = runner.inventory(tmp_path / "snapshots", as_of="2026-12-01T00:00:00Z")
    report = runner.check_inputs(
        captures,
        publications=tmp_path / "publications",
        handoffs=tmp_path / "handoffs",
        weeks=(6,),
        as_of="2026-12-01T00:00:00Z",
    )
    assert report["outcomes_read"] is False
    assert report["weeks"][0]["status"] == "identity_and_inventory_ready"
    assert "metadata.json" in opened


def re_event(name: str) -> bool:
    return name.startswith("event-gw") and name.endswith("-live.json")


def test_first_settled_selection_and_early_refusal(tmp_path: Path) -> None:
    first = capture(tmp_path, final=True)
    later = capture(tmp_path, final=True, instant_offset=1)
    inventory = runner.inventory(tmp_path, as_of="2026-12-01T00:00:00Z")
    assert (
        runner.first_settled(inventory, tuple(range(6, 13))).metadata.snapshot_id
        == first.metadata.snapshot_id
    )
    assert later.metadata.snapshot_id != first.metadata.snapshot_id
    with pytest.raises(DefconMissingInputs, match="not yet"):
        runner.first_settled({}, tuple(range(6, 13)))
    assert runner.window({"merged_at": "2026-10-12T18:59:59Z"}) == tuple(range(6, 13))
    assert runner.window({"merged_at": "2026-10-12T19:00:00Z"}) == tuple(range(7, 14))


def test_last_publication_is_used_and_missing_last_capture_is_not_repaired(tmp_path: Path) -> None:
    early = capture(tmp_path / "snapshots", instant_offset=-10)
    latest = capture(tmp_path / "snapshots")
    publication(tmp_path, early, base(early))
    publication(tmp_path, latest, base(latest))
    captures = runner.inventory(tmp_path / "snapshots", as_of="2026-12-01T00:00:00Z")
    chosen, _, _ = runner.published_pair(
        tmp_path / "publications", tmp_path / "handoffs", captures, 6, as_of="2026-12-01T00:00:00Z"
    )
    assert chosen.metadata.snapshot_id == latest.metadata.snapshot_id
    del captures[latest.metadata.snapshot_id]
    with pytest.raises(DefconMissingInputs, match="absent"):
        runner.published_pair(
            tmp_path / "publications",
            tmp_path / "handoffs",
            captures,
            6,
            as_of="2026-12-01T00:00:00Z",
        )


def test_realized_zero_minutes_stays_in_population_and_absent_player_is_dropped(
    tmp_path: Path,
) -> None:
    decision = capture(tmp_path / "decision")

    def change(documents: dict[str, Any]) -> None:
        rows = documents[live_payload(6)]["elements"]
        rows[1]["stats"]["minutes"] = 0
        rows[1]["stats"]["total_points"] = 0
        rows[1]["explain"] = []
        del rows[3]

    outcome = capture(tmp_path / "outcome", final=True, change=change)
    rows, dropped, _ = runner.paired_week(decision, base(decision), outcome)
    assert [r.player_code for r in rows] == [102, 103]
    assert rows[0].realized == 0
    assert dropped == [104]


def paired(
    week: int, code: int, position: str, realized: float, candidate: float, control: float
) -> PairedDefconRow:
    return PairedDefconRow(
        week,
        code,
        position,
        control,
        candidate,
        realized,
        candidate - control,
        candidate - control,
        2,
        60,
    )


def test_gate_uses_equal_week_weights_and_common_average_tied_ranks() -> None:
    rows = []
    for week in range(6, 11):
        for position, offset in (("DEF", 0), ("MID", 100)):
            for i in range(3 if week != 10 else 30):
                actual = float(i // 2)
                rows.append(paired(week, offset + i + 1, position, actual, actual, actual + 1))
    report = summarize(tuple(rows), scored_weeks=tuple(range(6, 13)))
    assert report["verdict"] == "passed"
    assert report["delta"] == -1
    assert report["interval_90"] == {"lower": -1.0, "upper": -1.0}
    assert report["ranks"]["DEF"]["comparator"] == pytest.approx(1)
    assert report["ranks"]["DEF"]["candidate"] == pytest.approx(1)
    # A zero upper endpoint fails the strict boundary, even when ranks are unchanged.
    equal = tuple(replace(row, comparator=row.candidate) for row in rows)
    assert summarize(equal, scored_weeks=tuple(range(6, 13)))["verdict"] == "failed"
    assert (
        summarize(tuple(rows[:12]), scored_weeks=tuple(range(6, 13)))["verdict"]
        == "insufficient_evidence"
    )


def test_rank_group_constant_in_either_arm_is_excluded_for_both() -> None:
    rows = tuple(
        paired(w, i, "DEF", float(i), 2.0, float(i)) for w in range(6, 11) for i in range(1, 4)
    )
    report = summarize(rows, scored_weeks=tuple(range(6, 13)))
    assert report["verdict"] == "failed"
    assert report["ranks"]["DEF"]["groups"] == 0
    assert len(report["excluded_rank_groups"]) == 5


def test_single_reading_writes_hashes_twins_and_refuses_repetition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    (root / "docs" / "research").mkdir(parents=True)
    (root / "docs" / "measurements_index.md").write_text(
        "| Artifact | Finding | PR |\n| --- | --- | --- |\n"
    )
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "command", lambda *args: "")
    capture(tmp_path / "snapshots", final=True)
    for week in range(6, 13):
        snapshot = capture(tmp_path / "snapshots", target=week)
        publication(tmp_path, snapshot, base(snapshot, target=week))
    captures = runner.inventory(tmp_path / "snapshots", as_of="2026-12-01T00:00:00Z")
    kwargs = {
        "snapshot_root": tmp_path / "snapshots",
        "publications": tmp_path / "publications",
        "handoffs": tmp_path / "handoffs",
        "declaration": {
            "merged_at": "2026-10-09T00:00:00Z",
            "sha256": runner.DECLARATION_SHA256,
            "code_commit": "a" * 40,
        },
        "as_of": "2026-12-01T00:00:00Z",
        "claim_directory": tmp_path / "claims",
        "owner_approved": True,
        "weekly_run_idle": True,
    }
    report = runner.reading(captures, **kwargs)
    assert report["valid_weeks"] == 7
    assert report["promotion"] is False
    assert len(report["reading_capture_fingerprint"]) == 64
    assert json.loads((root / (runner.RECORD + ".json")).read_text()) == report
    assert report["verdict"] in (root / (runner.RECORD + ".md")).read_text()
    assert "defcon_component_reading.md" in (root / "docs/measurements_index.md").read_text()
    with pytest.raises(DefconInputError, match="another gate"):
        runner.reading(captures, **kwargs)


def test_crashed_claim_and_early_reading_prevent_outcome_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = capture(tmp_path / "snapshots", final=True)
    captures = runner.inventory(tmp_path / "snapshots", as_of="2026-12-01T00:00:00Z")
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "command", lambda *args: "")
    claims = tmp_path / "claims"
    claims.mkdir()
    (claims / (runner.DECLARATION_SHA256 + ".json")).write_text("{}")
    kwargs = {
        "snapshot_root": tmp_path / "snapshots",
        "publications": tmp_path / "publications",
        "handoffs": tmp_path / "handoffs",
        "declaration": {"merged_at": "2026-10-09T00:00:00Z"},
        "as_of": "2026-12-01T00:00:00Z",
        "claim_directory": claims,
        "owner_approved": True,
        "weekly_run_idle": True,
    }
    with pytest.raises(DefconInputError, match="already claimed"):
        runner.reading(captures, **kwargs)
    kwargs["as_of"] = "2026-10-01T00:00:00Z"
    with pytest.raises(DefconMissingInputs, match="precedes"):
        runner.reading(captures, **kwargs)
    assert snapshot.metadata.snapshot_id in captures


def test_duplicate_json_keys_fail_input_validation() -> None:
    with pytest.raises(DefconInputError, match="duplicated"):
        decode(b'{"id":1,"id":2}')


def test_unmerged_preregistration_refuses_before_any_input_is_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "command", lambda *args: '{"state":"OPEN","mergedAt":null}')

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("No input may be read before the declaration is merged.")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    with pytest.raises(DefconInputError, match="must be merged"):
        runner.frozen_declaration()


def test_week_weighting_cannot_be_replaced_with_player_pooling() -> None:
    rows = (
        paired(6, 1, "DEF", 0.0, 1.0, 0.0),
        *(paired(7, i, "MID", 0.0, 1.0, 2.0) for i in range(1, 101)),
    )
    report = summarize(rows, scored_weeks=tuple(range(6, 13)))
    assert [week["delta"] for week in report["weekly"]] == [1.0, -3.0]
    assert report["delta"] == -1.0
    assert summarize(tuple(reversed(rows)), scored_weeks=tuple(range(6, 13))) == report


def test_elite_base_keeps_its_evidence_identity(tmp_path: Path) -> None:
    from squadopt.live.recommendation import COMPONENT_ELITE_FEATURE_CONTRACT_VERSION

    snapshot = capture(tmp_path)
    original = replace(
        base(snapshot),
        model_version="phase-c-component-elite-top100-v1",
        feature_contract_version=COMPONENT_ELITE_FEATURE_CONTRACT_VERSION,
        evidence_fingerprint="e" * 64,
    )
    candidate = candidate_handoff(snapshot, original, declaration_sha256=runner.DECLARATION_SHA256)
    assert candidate.model_version == "phase-c-component-elite-top100-defcon-2026-v1"
    assert candidate.evidence_fingerprint == original.evidence_fingerprint
    assert candidate.feature_contract_version == original.feature_contract_version
    assert candidate.model_version not in IN_SEASON_CONTROL_MODEL_VERSIONS


def test_checker_reports_missing_appearance_without_reading_outcomes(tmp_path: Path) -> None:
    snapshot = capture(tmp_path / "snapshots")
    publication(tmp_path, snapshot, replace(base(snapshot), appearance_probability=None))
    captures = runner.inventory(tmp_path / "snapshots", as_of="2026-12-01T00:00:00Z")
    result = runner.check_inputs(
        captures,
        publications=tmp_path / "publications",
        handoffs=tmp_path / "handoffs",
        weeks=(6,),
        as_of="2026-12-01T00:00:00Z",
    )
    assert result["weeks"][0]["status"] == "missing"
    assert result["weeks"][0]["absent_player_codes"] == [102, 103, 104]


def test_capture_at_deadline_is_not_an_admissible_fit_input(tmp_path: Path) -> None:
    snapshot = capture(tmp_path, instant_offset=3600)
    with pytest.raises(DefconMissingInputs, match="before its own"):
        candidate_handoff(snapshot, base(snapshot), declaration_sha256=runner.DECLARATION_SHA256)


def test_existing_handoff_optional_binding_is_absent_and_bytes_stable(tmp_path: Path) -> None:
    snapshot = capture(tmp_path)
    original = base(snapshot)
    path = write_projection_handoff(tmp_path / "old.json", original)
    content = path.read_bytes()
    assert "augmentation_fingerprint" not in json.loads(content)
    assert (
        write_projection_handoff(
            path, replace(original, augmentation_fingerprint=None)
        ).read_bytes()
        == content
    )
    assert read_projection_handoff(path).fingerprint == original.fingerprint


def test_settled_capture_time_tie_uses_snapshot_identifier(tmp_path: Path) -> None:
    first = capture(tmp_path, final=True)
    other = capture(
        tmp_path, final=True, change=lambda docs: docs[BOOTSTRAP_PAYLOAD].update(marker="tie")
    )
    captures = runner.inventory(tmp_path, as_of="2026-12-01T00:00:00Z")
    assert runner.first_settled(captures, tuple(range(6, 13))).metadata.snapshot_id == min(
        first.metadata.snapshot_id, other.metadata.snapshot_id
    )


def test_invalid_roster_and_payload_tampering_are_refused(tmp_path: Path) -> None:
    snapshot = capture(
        tmp_path / "roster",
        change=lambda docs: docs[BOOTSTRAP_PAYLOAD]["elements"].append(
            docs[BOOTSTRAP_PAYLOAD]["elements"][0]
        ),
    )
    with pytest.raises(DefconInputError, match="duplicate"):
        candidate_handoff(snapshot, base(snapshot), declaration_sha256=runner.DECLARATION_SHA256)
    good = capture(tmp_path / "clean")
    path = tmp_path / "clean" / good.metadata.snapshot_id / "payloads" / BOOTSTRAP_PAYLOAD
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(DefconMissingInputs, match="checksum"):
        runner.partial_snapshot(path.parents[1])


def test_pure_component_refuses_forged_capture_time_before_reading_payloads(tmp_path: Path) -> None:
    snapshot = capture(tmp_path)
    forged = replace(snapshot.metadata, captured_at_utc="2026-09-25T15:00:00Z")
    with pytest.raises(DefconInputError, match="identity binding"):
        candidate_handoff(
            CapturedSnapshot(forged, {}),
            base(snapshot),
            declaration_sha256=runner.DECLARATION_SHA256,
        )


def test_missing_settled_fixture_count_marks_whole_week_missing(tmp_path: Path) -> None:
    decision = capture(tmp_path / "decision", double=True)
    outcome = capture(tmp_path / "outcome", final=True)
    with pytest.raises(DefconMissingInputs, match="counts disagree"):
        runner.paired_week(decision, base(decision), outcome)


def test_crashed_claim_refuses_before_any_outcome_file_is_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture(tmp_path / "snapshots", final=True)
    captures = runner.inventory(tmp_path / "snapshots", as_of="2026-12-01T00:00:00Z")
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "command", lambda *args: "")
    claims = tmp_path / "claims"
    claims.mkdir()
    (claims / (runner.DECLARATION_SHA256 + ".json")).write_text("{}")

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("An outcome read must not happen after an existing claim.")

    monkeypatch.setattr(runner, "partial_snapshot", forbidden)
    with pytest.raises(DefconInputError, match="already claimed"):
        runner.reading(
            captures,
            snapshot_root=tmp_path / "snapshots",
            publications=tmp_path,
            handoffs=tmp_path,
            declaration={"merged_at": "2026-10-09T00:00:00Z"},
            as_of="2026-12-01T00:00:00Z",
            claim_directory=claims,
            owner_approved=True,
            weekly_run_idle=True,
        )
