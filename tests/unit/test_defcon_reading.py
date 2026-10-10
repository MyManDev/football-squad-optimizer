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
            "data_checked": final or w < target,
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


@pytest.mark.parametrize("corruption", ["duplicate", "season"])
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
    candidate = candidate_handoff(
        snapshot, base(snapshot), declaration_sha256=runner.DECLARATION_SHA256
    )
    component = candidate.diagnostics["defcon_component"]
    assert component["rates"]["player_appearances"]["102"] == 5
    assert component["rates"]["player_awards"]["102"] == 4
    assert component["development_schema_disagreements"][0]["reason"] == "count_award_disagreement"


def test_checker_parses_only_development_payloads_and_never_scored_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = capture(tmp_path / "snapshots")
    publication(tmp_path, snapshot, base(snapshot))
    original = Path.read_bytes
    opened = []

    def checked(path: Path) -> bytes:
        assert not re_event(path.name) or int(path.name[8:10]) <= 5
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
        snapshot_root=tmp_path / "snapshots",
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
        tmp_path / "publications",
        tmp_path / "handoffs",
        captures,
        6,
        as_of="2026-12-01T00:00:00Z",
        deadline_utc=stamp(START + timedelta(weeks=5)),
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
            deadline_utc=stamp(START + timedelta(weeks=5)),
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
        (runner.ROOT / "docs/measurements_index.md").read_text(encoding="utf-8"),
        encoding="utf-8",
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
        snapshot_root=tmp_path / "snapshots",
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


def test_no_population_after_fixture_count_drops_marks_week_missing(tmp_path: Path) -> None:
    decision = capture(tmp_path / "decision", double=True)
    outcome = capture(tmp_path / "outcome", final=True)
    with pytest.raises(DefconMissingInputs, match="population is empty"):
        runner.paired_week(decision, base(decision), outcome)


def test_finished_blank_week_keeps_paired_players_with_zero_component(tmp_path: Path) -> None:
    def blank(documents: dict[str, Any]) -> None:
        documents[FIXTURES_PAYLOAD] = [f for f in documents[FIXTURES_PAYLOAD] if f["event"] != 6]
        if live_payload(6) in documents:
            for entry in documents[live_payload(6)]["elements"]:
                entry["stats"]["minutes"] = 0
                entry["stats"]["total_points"] = 0
                entry["explain"] = []

    decision = capture(tmp_path / "decision", change=blank)
    original = replace(base(decision), appearance_probability=None)
    outcome = capture(tmp_path / "outcome", final=True, change=blank)
    candidate = candidate_handoff(decision, original, declaration_sha256=runner.DECLARATION_SHA256)
    assert candidate.expected_points == original.expected_points
    rows, dropped, _ = runner.paired_week(decision, original, outcome)
    assert len(rows) == 3
    assert dropped == []
    assert all(
        row.term_unconditional == 0 and row.term_decided == 0 and row.realized == 0 for row in rows
    )


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


@pytest.mark.parametrize("code", [102, 103, 104])
def test_direct_control_omission_stays_paired_with_zero_term(tmp_path: Path, code: int) -> None:
    decision = capture(tmp_path / "snapshots")
    original = base(decision)
    appearance = dict(original.appearance_probability or {})
    del appearance[code]
    original = replace(original, appearance_probability=appearance)
    publication(tmp_path, decision, original)
    outcome = capture(tmp_path / "outcome", final=True)
    audit: dict[str, Any] = {}
    rows, dropped, _ = runner.paired_week(decision, original, outcome, audit=audit)
    row = next(row for row in rows if row.player_code == code)
    assert row.candidate == row.comparator
    assert row.term_unconditional == row.term_decided == 0
    assert dropped == []
    assert audit["zero_term_player_codes"] == [code]
    assert audit["zero_term_player_count"] == 1
    checked = runner.check_inputs(
        runner.inventory(tmp_path / "snapshots", as_of="2026-12-01T00:00:00Z"),
        publications=tmp_path / "publications",
        handoffs=tmp_path / "handoffs",
        weeks=(6,),
        as_of="2026-12-01T00:00:00Z",
        snapshot_root=tmp_path / "snapshots",
    )
    assert checked["weeks"][0]["status"] == "identity_and_inventory_ready"
    assert checked["weeks"][0]["zero_term_player_codes"] == [code]


def test_paired_week_applies_half_availability_to_the_whole_candidate(tmp_path: Path) -> None:
    decision = capture(tmp_path / "decision")
    outcome = capture(tmp_path / "outcome", final=True)
    rows, _, _ = runner.paired_week(decision, base(decision), outcome)
    row = next(row for row in rows if row.player_code == 102)
    assert row.comparator == pytest.approx(1.5)
    assert row.candidate == pytest.approx(2.3)
    assert row.term_unconditional == pytest.approx(1.6)
    assert row.term_decided == pytest.approx(0.8)
    assert {row.player_code: row.realized for row in rows} == {102: 2, 103: 3, 104: 4}


@pytest.mark.parametrize(
    "corruption", ["modification", "award", "minutes", "fixture", "sum", "zero_award"]
)
def test_invalid_fit_fixture_is_excluded_from_both_counts(tmp_path: Path, corruption: str) -> None:
    def change(documents: dict[str, Any]) -> None:
        entry = documents[live_payload(1)]["elements"][1]
        if corruption == "modification":
            entry["explain"][0]["stats"][1]["points_modification"] = 1
        elif corruption == "award":
            entry["explain"][0]["stats"][1]["points"] = 1
        elif corruption == "minutes":
            entry["explain"][0]["stats"] = entry["explain"][0]["stats"][1:]
        elif corruption == "fixture":
            entry["explain"][0]["fixture"] = 2
        elif corruption == "sum":
            entry["stats"]["minutes"] = 80
        else:
            entry["stats"]["minutes"] = 0
            entry["explain"][0]["stats"][0]["value"] = 0

    decision = capture(tmp_path / "snapshots", change=change)
    original = base(decision)
    candidate = candidate_handoff(decision, original, declaration_sha256=runner.DECLARATION_SHA256)
    component = candidate.diagnostics["defcon_component"]
    assert component["rates"]["player_appearances"]["102"] == 4
    assert component["rates"]["player_awards"]["102"] == 4
    assert component["excluded_fit_rows"][0]["player_code"] == 102
    assert component["excluded_fit_rows"][0]["gameweek"] == 1
    publication(tmp_path, decision, original)
    checked = runner.check_inputs(
        runner.inventory(tmp_path / "snapshots", as_of="2026-12-01T00:00:00Z"),
        publications=tmp_path / "publications",
        handoffs=tmp_path / "handoffs",
        weeks=(6,),
        as_of="2026-12-01T00:00:00Z",
        snapshot_root=tmp_path / "snapshots",
    )
    assert checked["weeks"][0]["excluded_development_fit_rows"] == component["excluded_fit_rows"]


def test_post_deadline_publication_is_ignored_and_restore_mtime_is_not_proof(
    tmp_path: Path,
) -> None:
    early = capture(tmp_path / "snapshots")
    late = capture(tmp_path / "snapshots", instant_offset=10)
    publication(tmp_path, early, base(early))
    publication(tmp_path, late, base(late), generated_offset=7200)
    handoff_path = (
        tmp_path / "handoffs" / "by-capture" / early.metadata.snapshot_id / "default.json"
    )
    after_deadline = (START + timedelta(weeks=6)).timestamp()
    os.utime(handoff_path, (after_deadline, after_deadline))
    captures = runner.inventory(tmp_path / "snapshots", as_of="2026-12-01T00:00:00Z")
    selected, _, _ = runner.published_pair(
        tmp_path / "publications",
        tmp_path / "handoffs",
        captures,
        6,
        as_of="2026-12-01T00:00:00Z",
        deadline_utc=stamp(START + timedelta(weeks=5)),
    )
    assert selected.metadata.snapshot_id == early.metadata.snapshot_id


@pytest.mark.parametrize("deadline_offset", [-1, 0, 1])
def test_unknown_capture_publication_uses_independent_deadline_in_both_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, deadline_offset: int
) -> None:
    captures, kwargs = reading_fixture(tmp_path, monkeypatch)
    publication_root = kwargs["publications"] / "2026-27/gw08"
    earlier = next(publication_root.glob("entry-*/*/advice.json"))
    document = json.loads(earlier.read_text(encoding="utf-8"))
    expected_capture = document["capture"]["snapshot_id"]
    document["capture"]["snapshot_id"] = "not-retained"
    document["generated_at_utc"] = stamp(START + timedelta(weeks=7, seconds=deadline_offset))
    unknown = publication_root / "entry-unknown/not-retained/advice.json"
    unknown.parent.mkdir(parents=True)
    unknown.write_text(json.dumps(document), encoding="utf-8")
    checked = runner.check_inputs(
        captures,
        publications=kwargs["publications"],
        handoffs=kwargs["handoffs"],
        weeks=(8,),
        as_of=kwargs["as_of"],
        snapshot_root=kwargs["snapshot_root"],
    )
    report = runner.reading(captures, **kwargs)
    row = next(row for row in report["week_identities"] if row["gameweek"] == 8)
    if deadline_offset < 0:
        assert checked["weeks"][0]["status"] == row["status"] == "missing"
        assert "decision capture is absent" in row["detail"]
        assert report["valid_weeks"] == 6
    else:
        assert checked["weeks"][0]["status"] == "identity_and_inventory_ready"
        assert row["status"] == "scored"
        assert row["identity"]["capture"] == expected_capture
        assert report["valid_weeks"] == 7


@pytest.mark.parametrize("duplicate", ["fixture", "statistic"])
def test_duplicate_realized_explanation_excludes_diagnostics_and_keeps_week_scored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, duplicate: str
) -> None:
    def change(documents: dict[str, Any]) -> None:
        player = documents[live_payload(9)]["elements"][1]
        if duplicate == "fixture":
            player["explain"].append(player["explain"][0])
        else:
            stats = player["explain"][0]["stats"]
            stats.append(stats[0])

    captures, kwargs = reading_fixture(tmp_path, monkeypatch, change=change)
    report = runner.reading(captures, **kwargs)
    row = next(row for row in report["week_identities"] if row["gameweek"] == 9)
    assert report["valid_weeks"] == 7
    assert row["status"] == "scored"
    assert row["dropped_players"] == []
    assert row["excluded_realized_diagnostics"] == [
        {"gameweek": 9, "player_code": 102, "fixture": 9, "reason": "duplicate_explanation_key"}
    ]
    decision = capture(tmp_path / "decision", target=9)
    outcome = capture(tmp_path / "outcome", final=True, change=change)
    paired_rows, _, _ = runner.paired_week(decision, base(decision, target=9), outcome)
    retained = next(row for row in paired_rows if row.player_code == 102)
    assert retained.realized == 2
    assert retained.awarded_defcon == 0
    assert retained.defcon_diagnostic is False
    assert row["defcon_diagnostic_excluded_player_codes"] == [102]


@pytest.mark.parametrize("duplicate", ["fixture", "statistic"])
def test_duplicate_fit_explanation_still_refuses_input_validation(
    tmp_path: Path, duplicate: str
) -> None:
    def change(documents: dict[str, Any]) -> None:
        player = documents[live_payload(3)]["elements"][1]
        if duplicate == "fixture":
            player["explain"].append(player["explain"][0])
        else:
            player["explain"][0]["stats"].append(player["explain"][0]["stats"][0])

    decision = capture(tmp_path, change=change)
    with pytest.raises(DefconInputError, match="duplicated"):
        candidate_handoff(decision, base(decision), declaration_sha256=runner.DECLARATION_SHA256)


def test_fixture_count_mismatch_drops_only_the_affected_club_players(tmp_path: Path) -> None:
    def change(documents: dict[str, Any]) -> None:
        documents[BOOTSTRAP_PAYLOAD]["elements"][3]["team"] = 2
        documents[BOOTSTRAP_PAYLOAD]["teams"].append({"id": 3, "name": "Other"})
        documents[FIXTURES_PAYLOAD][5]["team_a"] = 3

    decision = capture(tmp_path / "decision", change=change)
    outcome = capture(tmp_path / "outcome", final=True)
    audit: dict[str, Any] = {}
    rows, dropped, _ = runner.paired_week(decision, base(decision), outcome, audit=audit)
    assert [row.player_code for row in rows] == [102, 103]
    assert dropped == [104]
    assert audit["fixture_count_mismatches"] == [
        {"player_code": 104, "decided_count": 0, "settled_count": 1}
    ]


def test_rank_means_use_player_count_weights_when_group_ranks_differ() -> None:
    rows = tuple(paired(6, i, "DEF", float(i), float(-i), float(i)) for i in range(1, 4))
    rows += tuple(paired(7, i, "DEF", float(i), float(i), float(-i)) for i in range(1, 6))
    ranks = summarize(rows, scored_weeks=tuple(range(6, 13)))["ranks"]["DEF"]
    assert ranks["comparator"] == pytest.approx((3 - 5) / 8)
    assert ranks["candidate"] == pytest.approx((-3 + 5) / 8)
    assert ranks["players"] == 8


@pytest.mark.parametrize("merged", ["2026-10-17T10:00:00Z", "2026-10-18T00:00:00Z"])
def test_late_declaration_requires_a_new_window(merged: str) -> None:
    with pytest.raises(DefconInputError, match="new declaration"):
        runner.window({"merged_at": merged})


def test_finished_but_unchecked_event_is_not_settled(tmp_path: Path) -> None:
    def change(documents: dict[str, Any]) -> None:
        documents[BOOTSTRAP_PAYLOAD]["events"][0]["data_checked"] = False

    decision = capture(tmp_path / "decision", change=change)
    with pytest.raises(DefconMissingInputs, match="not settled"):
        candidate_handoff(decision, base(decision), declaration_sha256=runner.DECLARATION_SHA256)

    def unchecked_outcome(documents: dict[str, Any]) -> None:
        documents[BOOTSTRAP_PAYLOAD]["events"][9]["data_checked"] = False

    capture(tmp_path / "snapshots", final=True, change=unchecked_outcome)
    captures = runner.inventory(tmp_path / "snapshots", as_of="2026-12-01T00:00:00Z")
    with pytest.raises(DefconMissingInputs, match="not yet"):
        runner.first_settled(captures, tuple(range(6, 13)))


def reading_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, change: Any = None
) -> tuple[Any, dict[str, Any]]:
    # Use the committed index with all its tables, rather than an unrepresentative single table.
    contents = (runner.ROOT / "docs/measurements_index.md").read_text(encoding="utf-8")
    root = tmp_path / "repo"
    (root / "docs/research").mkdir(parents=True)
    (root / "docs/measurements_index.md").write_text(contents, encoding="utf-8")
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "command", lambda *args: "")
    capture(tmp_path / "snapshots", final=True, change=change)
    for week in range(6, 13):
        decision = capture(tmp_path / "snapshots", target=week)
        publication(tmp_path, decision, base(decision, target=week))
    captures = runner.inventory(tmp_path / "snapshots", as_of="2026-12-01T00:00:00Z")
    return captures, dict(
        snapshot_root=tmp_path / "snapshots",
        publications=tmp_path / "publications",
        handoffs=tmp_path / "handoffs",
        declaration={
            "merged_at": "2026-10-09T00:00:00Z",
            "sha256": runner.DECLARATION_SHA256,
            "code_commit": "a" * 40,
        },
        as_of="2026-12-01T00:00:00Z",
        claim_directory=tmp_path / "claims",
        owner_approved=True,
        weekly_run_idle=True,
    )


def test_real_index_records_beside_direct_defcon_and_preserves_every_existing_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captures, kwargs = reading_fixture(tmp_path, monkeypatch)
    index = runner.ROOT / "docs/measurements_index.md"
    before = index.read_text(encoding="utf-8")
    assert before.count("| --- | --- | --- |") > 1
    report = runner.reading(captures, **kwargs)
    after = index.read_text(encoding="utf-8")
    assert report["valid_weeks"] == 7
    lines = after.splitlines(keepends=True)
    inserted = [line for line in lines if "defcon_component_reading.md" in line]
    assert len(inserted) == 1
    at = lines.index(inserted[0])
    assert lines[at - 1].startswith("| [Direct DEFCON development]")
    assert after.split("## Deterministic policy", 1)[1].split("\n## ", 1)[0].count(inserted[0]) == 1
    assert after.replace(inserted[0], "", 1) == before


def test_bad_index_shape_refuses_before_claim_or_outcome_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captures, kwargs = reading_fixture(tmp_path, monkeypatch)
    (runner.ROOT / "docs/measurements_index.md").write_text("No table", encoding="utf-8")

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("No outcome may be opened before index validation")

    monkeypatch.setattr(runner, "partial_snapshot", forbidden)
    with pytest.raises(DefconInputError, match="index section"):
        runner.reading(captures, **kwargs)
    assert not list((tmp_path / "claims").glob("*.json"))


def test_one_duplicate_outcome_week_is_missing_with_named_validation_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def change(documents: dict[str, Any]) -> None:
        documents[live_payload(10)]["elements"].append(documents[live_payload(10)]["elements"][0])

    captures, kwargs = reading_fixture(tmp_path, monkeypatch, change=change)
    report = runner.reading(captures, **kwargs)
    assert report["valid_weeks"] == 6
    missing = [w for w in report["week_identities"] if w["status"] == "missing"]
    assert len(missing) == 1
    assert missing[0]["gameweek"] == 10
    assert missing[0]["reason"] == "input_validation"
    assert "duplicated" in missing[0]["detail"]


def test_unexpected_error_after_outcome_access_saves_completed_verdict_and_no_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captures, kwargs = reading_fixture(tmp_path, monkeypatch)

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("synthetic programming fault")

    monkeypatch.setattr(runner, "paired_week", broken)
    report = runner.reading(captures, **kwargs)
    assert report["verdict"] == "insufficient_evidence"
    assert report["stop_reason"] == {
        "reason": "RuntimeError",
        "detail": "synthetic programming fault",
    }
    assert json.loads((runner.ROOT / (runner.RECORD + ".json")).read_text()) == report
    with pytest.raises(DefconInputError, match="another gate"):
        runner.reading(captures, **kwargs)


def test_inventory_skips_unreadable_metadata_and_records_its_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = capture(tmp_path)
    bad = tmp_path / "fpl-live-20260925T163001Z-000000000000"
    bad.mkdir()
    original = Path.read_bytes

    def unreadable(path: Path) -> bytes:
        if path == bad / "metadata.json":
            raise PermissionError("synthetic unreadable metadata")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", unreadable)
    captures = runner.inventory(tmp_path, as_of="2026-12-01T00:00:00Z")
    assert list(captures) == [good.metadata.snapshot_id]
    assert captures.skipped == [
        {
            "snapshot_id": bad.name,
            "reason": "PermissionError",
            "detail": "synthetic unreadable metadata",
        }
    ]


@pytest.mark.parametrize("name", [BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD])
def test_intact_metadata_with_a_missing_payload_refuses_the_inventory(
    tmp_path: Path, name: str
) -> None:
    # The runner documents that such a capture is repaired or removed before any mode.
    capture(tmp_path)
    damaged = capture(tmp_path, instant_offset=1)
    (tmp_path / damaged.metadata.snapshot_id / "payloads" / name).unlink()
    with pytest.raises(DefconMissingInputs, match="absent in the retained capture"):
        runner.inventory(tmp_path, as_of="2026-12-01T00:00:00Z")


def test_summary_failure_saves_completed_verdict_without_retrying_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captures, kwargs = reading_fixture(tmp_path, monkeypatch)
    calls = []

    def broken(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        raise RuntimeError("synthetic summary fault")

    monkeypatch.setattr(runner, "summarize", broken)
    report = runner.reading(captures, **kwargs)
    assert calls == [1]
    assert report["verdict"] == "insufficient_evidence"
    assert report["valid_weeks"] == 7
    assert report["gate_completed"] is False
    assert report["constants"]["bootstrap_seed"] == 20261007
    assert json.loads((runner.ROOT / (runner.RECORD + ".json")).read_text()) == report


@pytest.mark.parametrize(
    "damage",
    [
        "outcome_missing",
        "history_missing",
        "provenance_missing",
        "total_points_missing",
        "total_points_string",
        "fixture_club_missing",
    ],
)
def test_one_week_input_failure_preserves_the_other_six_pairs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    def change(documents: dict[str, Any]) -> None:
        if damage in ("total_points_missing", "total_points_string"):
            stats = documents[live_payload(8)]["elements"][1]["stats"]
            if damage.endswith("missing"):
                del stats["total_points"]
            else:
                stats["total_points"] = "2"

    captures, kwargs = reading_fixture(tmp_path, monkeypatch, change=change)
    selected = runner.first_settled(captures, tuple(range(6, 13)))
    if damage == "outcome_missing":
        (
            tmp_path / "snapshots" / selected.metadata.snapshot_id / "payloads" / live_payload(8)
        ).unlink()
    elif damage == "history_missing":
        decision = next(
            s
            for s in captures.values()
            if decode(s.payloads[BOOTSTRAP_PAYLOAD])["events"][7]["finished"] is False
            and decode(s.payloads[BOOTSTRAP_PAYLOAD])["events"][6]["finished"] is True
        )
        (
            tmp_path / "snapshots" / decision.metadata.snapshot_id / "payloads" / live_payload(3)
        ).unlink()
    elif damage == "provenance_missing":
        path = next((tmp_path / "publications/2026-27/gw08").rglob("advice.json"))
        doc = decode(path.read_bytes())
        del doc["provenance"]
        path.write_text(json.dumps(doc), encoding="utf-8")
    elif damage == "fixture_club_missing":
        original = runner.fixture_counts

        def malformed(fixtures: Any, elements: Any, week: int) -> Any:
            if week == 8:
                fixtures = {k: dict(v) for k, v in fixtures.items()}
                del fixtures[8]["team_h"]
            return original(fixtures, elements, week)

        monkeypatch.setattr(runner, "fixture_counts", malformed)
    report = runner.reading(captures, **kwargs)
    assert report["valid_weeks"] == 6
    assert report["gate_completed"] is True
    assert "stop_reason" not in report
    assert [w["gameweek"] for w in report["week_identities"] if w["status"] == "missing"] == [8]
    assert report["week_identities"][-1]["gameweek"] == 12


@pytest.mark.parametrize("weeks", [(7,), tuple(range(6, 11))])
def test_later_input_checks_open_only_actual_development_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, weeks: tuple[int, ...]
) -> None:
    for week in weeks:
        snapshot = capture(tmp_path / "snapshots", target=week)
        publication(tmp_path, snapshot, base(snapshot, target=week))
    original = Path.read_bytes
    opened: set[int] = set()

    def guarded(path: Path) -> bytes:
        if re_event(path.name):
            number = int(path.name[8:10])
            assert number <= 5, "Input checks must keep scored outcomes closed"
            opened.add(number)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    report = runner.check_inputs(
        runner.inventory(tmp_path / "snapshots", as_of="2026-12-01T00:00:00Z"),
        publications=tmp_path / "publications",
        handoffs=tmp_path / "handoffs",
        weeks=weeks,
        as_of="2026-12-01T00:00:00Z",
        snapshot_root=tmp_path / "snapshots",
    )
    assert all(row["status"] == "identity_and_inventory_ready" for row in report["weeks"])
    assert opened == {1, 2, 3, 4, 5}
    assert report["development_history_weeks_read"] == sorted(opened)


def test_input_check_reads_each_deadline_from_the_latest_retained_capture(tmp_path: Path) -> None:
    # The game moves deadlines, so an older capture can still carry GW7's earlier one.
    def provisional(documents: dict[str, Any]) -> None:
        documents[BOOTSTRAP_PAYLOAD]["events"][6]["deadline_time"] = stamp(
            START + timedelta(weeks=6, days=1)
        )

    capture(tmp_path / "snapshots", target=5, change=provisional)
    snapshot = capture(tmp_path / "snapshots", target=7)
    publication(tmp_path, snapshot, base(snapshot, target=7))
    captures = runner.inventory(tmp_path / "snapshots", as_of="2026-12-01T00:00:00Z")
    assert next(iter(captures)) != snapshot.metadata.snapshot_id
    report = runner.check_inputs(
        captures,
        publications=tmp_path / "publications",
        handoffs=tmp_path / "handoffs",
        weeks=(7,),
        as_of="2026-12-01T00:00:00Z",
        snapshot_root=tmp_path / "snapshots",
    )
    assert report["weeks"][0]["status"] == "identity_and_inventory_ready"
    assert report["weeks"][0]["identity"]["capture"] == snapshot.metadata.snapshot_id


@pytest.mark.parametrize("moved", ["earlier", "final"])
def test_only_the_selected_publication_capture_must_state_the_target_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, moved: str
) -> None:
    # An extra GW8 publish whose capture still carries a deadline the game later moved.
    def stale(documents: dict[str, Any]) -> None:
        documents[BOOTSTRAP_PAYLOAD]["events"][7]["deadline_time"] = stamp(
            START + timedelta(weeks=7, days=1)
        )

    captures, kwargs = reading_fixture(tmp_path, monkeypatch)
    week_root = kwargs["publications"] / "2026-27/gw08"
    consistent = next(week_root.glob("entry-*/*/advice.json")).parent.name
    extra = capture(
        kwargs["snapshot_root"],
        target=8,
        change=stale,
        instant_offset=-60 if moved == "earlier" else 60,
    )
    publication(tmp_path, extra, base(extra, target=8))
    captures = runner.inventory(kwargs["snapshot_root"], as_of=kwargs["as_of"])
    checked = runner.check_inputs(
        captures,
        publications=kwargs["publications"],
        handoffs=kwargs["handoffs"],
        weeks=(8,),
        as_of=kwargs["as_of"],
        snapshot_root=kwargs["snapshot_root"],
    )
    report = runner.reading(captures, **kwargs)
    row = next(row for row in report["week_identities"] if row["gameweek"] == 8)
    if moved == "earlier":
        assert checked["weeks"][0]["status"] == "identity_and_inventory_ready"
        assert row["status"] == "scored"
        assert report["valid_weeks"] == 7
        for proof in (checked["weeks"][0]["identity"], row["identity"]):
            assert proof["capture"] == consistent
            assert len(proof["publication_sha256"]) == 1
            (note,) = proof["nonfinal_deadline_notes"]
            assert note["capture"] == extra.metadata.snapshot_id
            assert note["reason"] == "deadline_disagreement"
            assert runner.as_instant(note["capture_deadline_utc"]) == START + timedelta(
                weeks=7, days=1
            )
            assert runner.as_instant(note["target_deadline_utc"]) == START + timedelta(weeks=7)
        others = [w["identity"] for w in report["week_identities"] if w["gameweek"] != 8]
        assert all(proof["nonfinal_deadline_notes"] == [] for proof in others)
    else:
        assert checked["weeks"][0]["status"] == row["status"] == "missing"
        assert checked["weeks"][0]["reason"] == row["reason"] == "input_validation"
        assert "selected decision capture disagrees" in row["detail"]
        assert report["valid_weeks"] == 6


def test_unreadable_earlier_deadline_is_a_note_and_never_makes_the_week_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An earlier GW8 publish whose capture lists no GW8 event cannot state any deadline.
    def unlisted(documents: dict[str, Any]) -> None:
        del documents[BOOTSTRAP_PAYLOAD]["events"][7]

    captures, kwargs = reading_fixture(tmp_path, monkeypatch)
    week_root = kwargs["publications"] / "2026-27/gw08"
    consistent = next(week_root.glob("entry-*/*/advice.json")).parent.name
    extra = capture(kwargs["snapshot_root"], target=8, change=unlisted, instant_offset=-60)
    publication(tmp_path, extra, base(extra, target=8))
    captures = runner.inventory(kwargs["snapshot_root"], as_of=kwargs["as_of"])
    checked = runner.check_inputs(
        captures,
        publications=kwargs["publications"],
        handoffs=kwargs["handoffs"],
        weeks=(8,),
        as_of=kwargs["as_of"],
        snapshot_root=kwargs["snapshot_root"],
    )
    report = runner.reading(captures, **kwargs)
    row = next(row for row in report["week_identities"] if row["gameweek"] == 8)
    assert checked["weeks"][0]["status"] == "identity_and_inventory_ready"
    assert row["status"] == "scored"
    assert report["valid_weeks"] == 7
    for proof in (checked["weeks"][0]["identity"], row["identity"]):
        assert proof["capture"] == consistent
        (note,) = proof["nonfinal_deadline_notes"]
        assert note["capture"] == extra.metadata.snapshot_id
        assert note["reason"] == "deadline_unreadable"
        assert note["detail"].startswith("DataSourceError: ")
        assert "publishes no gameweek 8" in note["detail"]


def test_unlanded_staging_record_is_not_a_publication(tmp_path: Path) -> None:
    snapshot = capture(tmp_path / "snapshots")
    path = publication(tmp_path, snapshot, base(snapshot))
    # A writer that died before its landing rename leaves this hidden sibling behind.
    document = decode(path.read_bytes())
    document["provenance"]["projection_handoff_fingerprint"] = "f" * 64
    document["generated_at_utc"] = stamp(
        datetime.fromisoformat(snapshot.metadata.captured_at_utc) + timedelta(seconds=40)
    )
    staging = path.parents[1] / f".{snapshot.metadata.snapshot_id}.staging-1-abcd" / "advice.json"
    staging.parent.mkdir()
    staging.write_text(json.dumps(document), encoding="utf-8")
    chosen, handoff, proof = runner.published_pair(
        tmp_path / "publications",
        tmp_path / "handoffs",
        runner.inventory(tmp_path / "snapshots", as_of="2026-12-01T00:00:00Z"),
        6,
        as_of="2026-12-01T00:00:00Z",
        deadline_utc=stamp(START + timedelta(weeks=5)),
    )
    assert chosen.metadata.snapshot_id == snapshot.metadata.snapshot_id
    assert handoff.fingerprint == base(snapshot).fingerprint
    assert proof["publication_sha256"] == [runner.payload_checksum(path.read_bytes())]


def test_checker_keeps_other_week_after_a_malformed_publication(tmp_path: Path) -> None:
    for week in (6, 7):
        snapshot = capture(tmp_path / "snapshots", target=week)
        path = publication(tmp_path, snapshot, base(snapshot, target=week))
        if week == 6:
            document = decode(path.read_bytes())
            del document["provenance"]
            path.write_text(json.dumps(document), encoding="utf-8")
    report = runner.check_inputs(
        runner.inventory(tmp_path / "snapshots", as_of="2026-12-01T00:00:00Z"),
        publications=tmp_path / "publications",
        handoffs=tmp_path / "handoffs",
        weeks=(6, 7),
        as_of="2026-12-01T00:00:00Z",
        snapshot_root=tmp_path / "snapshots",
    )
    assert [row["status"] for row in report["weeks"]] == ["missing", "identity_and_inventory_ready"]
    assert report["weeks"][0]["reason"] == "input_validation"


def test_nonconstant_whole_week_interval_pins_draws_seed_axis_and_endpoints() -> None:
    import math

    deltas = (-0.31, -0.17, -0.113, 0.052, 0.097, -0.041, 0.023)
    rows = tuple(
        paired(week, code + offset, position, float(code), code + math.sqrt(1 + delta), code + 1.0)
        for week, delta in zip(range(6, 13), deltas, strict=True)
        for position, offset in (("DEF", 0), ("MID", 100))
        for code in range(1, 4)
    )
    report = summarize(rows, scored_weeks=tuple(range(6, 13)))
    assert report["interval_90"]["lower"] == pytest.approx(-0.1526, abs=1e-12)
    assert report["interval_90"]["upper"] == pytest.approx(0.013285714285714285, abs=1e-12)
    assert report["verdict"] == "failed"
    assert report["constants"]["bootstrap_draws"] == 10_000
    assert report["constants"]["bootstrap_seed"] == 20261007


@pytest.mark.parametrize("damage", ["modified_award", "minutes_mismatch"])
def test_invalid_realized_diagnostic_does_not_remove_a_valid_scored_week(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    def change(documents: dict[str, Any]) -> None:
        row = documents[live_payload(9)]["elements"][1]
        if damage == "modified_award":
            row["explain"][0]["stats"][1]["points_modification"] = 1
        else:
            row["stats"]["minutes"] = 89

    captures, kwargs = reading_fixture(tmp_path, monkeypatch, change=change)
    report = runner.reading(captures, **kwargs)
    assert report["valid_weeks"] == 7
    row = next(w for w in report["week_identities"] if w["gameweek"] == 9)
    assert row["status"] == "scored" and row["dropped_players"] == []
    assert row["excluded_realized_diagnostics"][0]["player_code"] == 102
    assert row["excluded_realized_diagnostics"][0]["fixture"] == 9
    assert row["excluded_realized_diagnostics"][0]["reason"]
    # Player 102 leaves both diagnostic sides in GW9 only; GW9 still scores every player.
    assert row["defcon_diagnostic_excluded_player_codes"] == [102]
    assert next(w for w in report["weekly"] if w["gameweek"] == 9)["players"] == 3
    defenders = report["defcon_by_position"]["DEF"]
    assert defenders["players"] == 6
    assert defenders["excluded_players"] == 1
    assert defenders["awarded_defcon"] == 12
    selected = runner.first_settled(captures, tuple(range(6, 13)))
    decision, original, _ = runner.published_pair(
        kwargs["publications"],
        kwargs["handoffs"],
        captures,
        9,
        as_of=kwargs["as_of"],
        deadline_utc=stamp(START + timedelta(weeks=8)),
    )
    full = runner.partial_snapshot(
        kwargs["snapshot_root"] / decision.metadata.snapshot_id,
        (BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD, *(live_payload(w) for w in range(1, 9))),
    )
    outcome = runner.partial_snapshot(
        kwargs["snapshot_root"] / selected.metadata.snapshot_id,
        (BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD, live_payload(9)),
    )
    pairs, _, _ = runner.paired_week(full, original, outcome)
    assert next(p for p in pairs if p.player_code == 102).realized == 2
    assert {p.player_code: p.defcon_diagnostic for p in pairs} == {102: False, 103: True, 104: True}


def test_failed_realized_award_leaves_both_sides_of_the_defcon_diagnostic() -> None:
    rows = (
        replace(paired(6, 1, "DEF", 2.0, 3.0, 1.0), awarded_defcon=2),
        replace(paired(6, 2, "DEF", 0.0, 4.0, 1.0), awarded_defcon=0, defcon_diagnostic=False),
        replace(paired(6, 3, "MID", 0.0, 1.5, 1.0), awarded_defcon=0),
    )
    report = summarize(rows, scored_weeks=tuple(range(6, 13)))
    assert report["weekly"][0]["players"] == 3
    assert report["defcon_by_position"]["DEF"] == {
        "players": 1,
        "excluded_players": 1,
        "term_unconditional": 2.0,
        "term_decided": 2.0,
        "awarded_defcon": 2,
    }
    assert report["defcon_by_position"]["MID"]["term_unconditional"] == 0.5
    assert report["defcon_by_position"]["MID"]["excluded_players"] == 0


@pytest.mark.parametrize("count", [None, "15"])
def test_absent_development_count_retains_captured_award(tmp_path: Path, count: Any) -> None:
    def change(documents: dict[str, Any]) -> None:
        stats = documents[live_payload(1)]["elements"][1]["stats"]
        if count is None:
            del stats["defensive_contribution"]
        else:
            stats["defensive_contribution"] = count

    snapshot = capture(tmp_path, change=change)
    candidate = candidate_handoff(
        snapshot, base(snapshot), declaration_sha256=runner.DECLARATION_SHA256
    )
    component = candidate.diagnostics["defcon_component"]
    assert component["rates"]["player_appearances"]["102"] == 5
    assert component["rates"]["player_awards"]["102"] == 5
    assert component["development_schema_disagreements"][0]["reason"] == "count_absent"


def test_missing_one_double_fixture_preserves_the_identified_fit_fixture(tmp_path: Path) -> None:
    def change(documents: dict[str, Any]) -> None:
        documents[live_payload(1)]["elements"][1]["explain"].pop()

    snapshot = capture(tmp_path, double=True, change=change)
    candidate = candidate_handoff(
        snapshot, base(snapshot), declaration_sha256=runner.DECLARATION_SHA256
    )
    component = candidate.diagnostics["defcon_component"]
    assert component["rates"]["player_appearances"]["102"] == 5
    assert component["rates"]["player_awards"]["102"] == 5
    assert component["excluded_fit_rows"][0]["fixture"] == 98
    assert component["excluded_fit_rows"][0]["reason"] == "missing_fixture_explanation"
    assert not any(
        r["reason"] == "count_award_disagreement"
        for r in component["development_schema_disagreements"]
    )


def test_duplicate_copies_of_one_handoff_keep_the_pair_and_record_every_hash(
    tmp_path: Path,
) -> None:
    snapshot = capture(tmp_path / "snapshots")
    publication(tmp_path, snapshot, base(snapshot))
    directory = tmp_path / "handoffs/by-capture" / snapshot.metadata.snapshot_id
    document = decode((directory / "default.json").read_bytes())
    (directory / "same-model.json").write_text(json.dumps(document, indent=2), encoding="utf-8")
    captures = runner.inventory(tmp_path / "snapshots", as_of="2026-12-01T00:00:00Z")
    _, handoff, proof = runner.published_pair(
        tmp_path / "publications",
        tmp_path / "handoffs",
        captures,
        6,
        as_of="2026-12-01T00:00:00Z",
        deadline_utc=stamp(START + timedelta(weeks=5)),
    )
    assert handoff.fingerprint == base(snapshot).fingerprint
    assert proof["matching_handoff_sha256"] == sorted(
        runner.payload_checksum(path.read_bytes()) for path in directory.glob("*.json")
    )


def test_unmapped_history_is_present_in_input_and_reading_audits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captures, kwargs = reading_fixture(tmp_path, monkeypatch)
    target = next(
        s
        for s in captures.values()
        if decode(s.payloads[BOOTSTRAP_PAYLOAD])["events"][5]["finished"] is False
    )

    def add_unknown(documents: dict[str, Any]) -> None:
        documents[live_payload(1)]["elements"].append({"id": 999})

    replacement = capture(tmp_path / "snapshots", target=6, change=add_unknown, instant_offset=1)
    publication(tmp_path, replacement, base(replacement))
    del captures[target.metadata.snapshot_id]
    captures[replacement.metadata.snapshot_id] = runner.partial_snapshot(
        tmp_path / "snapshots" / replacement.metadata.snapshot_id
    )
    report = runner.check_inputs(
        captures,
        publications=kwargs["publications"],
        handoffs=kwargs["handoffs"],
        weeks=(6,),
        as_of=kwargs["as_of"],
        snapshot_root=kwargs["snapshot_root"],
    )
    assert report["weeks"][0]["unmapped_history"]["1"] == [999]
    assert report["weeks"][0]["unmapped_history_count"] == 1
    reading = runner.reading(captures, **kwargs)
    assert reading["week_identities"][0]["unmapped_history"]["1"] == [999]
    assert reading["week_identities"][0]["unmapped_history_count"] == 1


@pytest.mark.parametrize("where", ["publication", "handoff", "earlier_metadata"])
def test_forbidden_season_or_unreadable_earlier_capture_refuses_before_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    captures, kwargs = reading_fixture(tmp_path, monkeypatch)
    if where == "earlier_metadata":
        bad = tmp_path / "snapshots/fpl-live-20260925T163001Z-000000000000"
        bad.mkdir()
        (bad / "metadata.json").write_text("not JSON", encoding="utf-8")
        captures = runner.inventory(kwargs["snapshot_root"], as_of=kwargs["as_of"])
    else:
        root = kwargs["publications"] if where == "publication" else kwargs["handoffs"]
        path = next(root.rglob("advice.json" if where == "publication" else "default.json"))
        document = decode(path.read_bytes())
        document["season"] = "2025-26"
        path.write_text(json.dumps(document), encoding="utf-8")
    original = Path.read_bytes

    def guarded(path: Path) -> bytes:
        assert not re_event(path.name), "Preflight must not open any event outcomes"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    with pytest.raises(DefconInputError):
        runner.reading(captures, **kwargs)
    assert not list(kwargs["claim_directory"].glob("*.json"))
    assert not (runner.ROOT / (runner.RECORD + ".json")).exists()


def test_gate_floor_small_groups_and_average_rank_spearman_are_fixed() -> None:
    from squadopt.experiments import defcon_component_reading as gate
    from squadopt.prediction.defcon_component import DEFCON_PRIOR_APPEARANCES

    assert gate.MINIMUM_WEEKS == 5
    assert gate.RANK_BOUNDARY == -0.005
    assert gate.reading_constants()["prior_fixture_appearances"] == DEFCON_PRIOR_APPEARANCES
    rows = tuple(
        paired(w, i + offset, pos, float(i // 2), float((i // 2) ** 3), float(i // 2 + 10))
        for w in range(6, 10)
        for pos, offset in (("DEF", 0), ("MID", 100))
        for i in range(1, 6)
    )
    report = summarize(rows, scored_weeks=tuple(range(6, 13)))
    assert report["verdict"] == "insufficient_evidence"
    assert report["ranks"]["DEF"]["candidate"] == pytest.approx(1)
    assert report["ranks"]["DEF"]["comparator"] == pytest.approx(1)
    small = tuple(
        paired(w, i, "DEF", float(i), float(i), float(i + 1)) for w in range(6, 11) for i in (1, 2)
    )
    result = summarize(small, scored_weeks=tuple(range(6, 13)))
    assert result["ranks"]["DEF"]["groups"] == 0
    assert len(result["excluded_rank_groups"]) == 5


def test_realized_only_tie_uses_average_ranks_not_first_occurrence() -> None:
    import math

    rows = tuple(
        paired(6, code, "DEF", realized, forecast + 1.0, forecast)
        for code, realized, forecast in ((1, 10.0, 1.0), (2, 10.0, 2.0), (3, 11.0, 3.0))
    )
    report = summarize(rows, scored_weeks=tuple(range(6, 13)))
    (group,) = report["rank_groups"]
    # Average ranks (1.5, 1.5, 3) against (1, 2, 3); first occurrence would give exactly 1.0.
    assert group["comparator"] == pytest.approx(math.sqrt(3) / 2, abs=1e-12)
    assert group["candidate"] == pytest.approx(math.sqrt(3) / 2, abs=1e-12)
    assert report["ranks"]["DEF"]["comparator"] == pytest.approx(0.8660254, abs=1e-7)
    assert report["ranks"]["DEF"]["candidate"] == pytest.approx(0.8660254, abs=1e-7)


def test_rank_boundary_accepts_equality_and_rejects_a_lower_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from squadopt.experiments import defcon_component_reading as gate

    rows = tuple(
        paired(w, i + offset, pos, float(i), float(4 - i if w == 6 else i), float(i + 10))
        for w in range(6, 11)
        for pos, offset in (("DEF", 0), ("MID", 100))
        for i in range(1, 4)
    )
    delta = summarize(rows, scored_weeks=tuple(range(6, 13)))["ranks"]["DEF"]["delta"]
    assert delta < -0.005
    monkeypatch.setattr(gate, "RANK_BOUNDARY", delta)
    assert summarize(rows, scored_weeks=tuple(range(6, 13)))["verdict"] == "passed"
    monkeypatch.setattr(gate, "RANK_BOUNDARY", delta + 1e-9)
    assert summarize(rows, scored_weeks=tuple(range(6, 13)))["verdict"] == "failed"


@pytest.mark.parametrize("damage", ["capture_instant", "ambiguous", "inconsistent"])
def test_publication_identity_guards_are_reached(tmp_path: Path, damage: str) -> None:
    first = capture(tmp_path / "snapshots")
    path = publication(tmp_path, first, base(first), generated_offset=30)
    if damage == "capture_instant":
        document = decode(path.read_bytes())
        document["capture"]["captured_at_utc"] = stamp(
            datetime.fromisoformat(first.metadata.captured_at_utc) - timedelta(seconds=1)
        )
        path.write_text(json.dumps(document), encoding="utf-8")
        reason = "instant disagree"
    elif damage == "ambiguous":
        second = capture(tmp_path / "snapshots", instant_offset=10)
        publication(tmp_path, second, base(second), generated_offset=20)
        reason = "ambiguous default identity"
    else:
        second = replace(base(first), expected_points={101: 2.0, 102: 4.0, 103: 4.0, 104: 5.0})
        document = decode(path.read_bytes())
        document["provenance"]["projection_handoff_fingerprint"] = second.fingerprint
        document["generated_at_utc"] = stamp(
            datetime.fromisoformat(first.metadata.captured_at_utc) + timedelta(seconds=40)
        )
        other = path.parent.parent.parent / "entry-2" / first.metadata.snapshot_id / "advice.json"
        other.parent.mkdir(parents=True)
        other.write_text(json.dumps(document), encoding="utf-8")
        write_projection_handoff(
            tmp_path / "handoffs/by-capture" / first.metadata.snapshot_id / "second.json", second
        )
        reason = "inconsistent default identities"
    with pytest.raises(DefconMissingInputs, match=reason):
        runner.published_pair(
            tmp_path / "publications",
            tmp_path / "handoffs",
            runner.inventory(tmp_path / "snapshots", as_of="2026-12-01T00:00:00Z"),
            6,
            as_of="2026-12-01T00:00:00Z",
            deadline_utc=stamp(START + timedelta(weeks=5)),
        )


@pytest.mark.parametrize("target, missing, unchecked", [(7, 6, False), (7, 6, True), (6, 3, False)])
def test_checker_refuses_absent_or_unsettled_prior_inventory(
    tmp_path: Path, target: int, missing: int, unchecked: bool
) -> None:
    def change(documents: dict[str, Any]) -> None:
        if unchecked:
            documents[BOOTSTRAP_PAYLOAD]["events"][missing - 1]["data_checked"] = False
        else:
            del documents[live_payload(missing)]

    snapshot = capture(tmp_path / "snapshots", target=target, change=change)
    publication(tmp_path, snapshot, base(snapshot, target=target))
    report = runner.check_inputs(
        runner.inventory(tmp_path / "snapshots", as_of="2026-12-01T00:00:00Z"),
        publications=tmp_path / "publications",
        handoffs=tmp_path / "handoffs",
        weeks=(target,),
        as_of="2026-12-01T00:00:00Z",
        snapshot_root=tmp_path / "snapshots",
    )
    assert report["weeks"][0]["status"] == "missing"
    assert report["weeks"][0]["reason"] == "prior_history_inventory_missing_or_unsettled"
    assert report["weeks"][0]["absent_weeks"] == [missing]


@pytest.mark.parametrize("flag", ["owner_approved", "weekly_run_idle"])
def test_reading_authorization_flags_refuse_before_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    captures, kwargs = reading_fixture(tmp_path, monkeypatch)
    kwargs[flag] = False
    with pytest.raises(DefconInputError, match="authorize"):
        runner.reading(captures, **kwargs)
    assert not kwargs["claim_directory"].exists()


@pytest.mark.parametrize("prefix", ["C:/sqr", "C:/sqrweb", "C:/sqr/child", "C:/sqrweb/child"])
def test_rehearsal_prefix_validation_without_accessing_the_directory(
    monkeypatch: pytest.MonkeyPatch, prefix: str
) -> None:
    monkeypatch.setattr(Path, "resolve", lambda self: self)
    with pytest.raises(DefconInputError, match="Rehearsal"):
        runner.safe_path(Path(prefix))


@pytest.mark.parametrize("damage", ["digest", "merge_base", "dirty"])
def test_merged_declaration_identity_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    import subprocess
    from types import SimpleNamespace

    blob = b"synthetic frozen declaration\n"
    (tmp_path / "docs").mkdir()
    (tmp_path / runner.DECLARATION).write_bytes(blob)
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "DECLARATION_SHA256", runner.normalized_digest(blob))

    def command(*args: str) -> str:
        if args[0] == "gh":
            return json.dumps(
                {
                    "state": "MERGED",
                    "mergedAt": "2026-10-09T00:00:00Z",
                    "mergeCommit": {"oid": "a" * 40},
                }
            )
        if args[1] == "merge-base" and damage == "merge_base":
            raise subprocess.CalledProcessError(1, args)
        if args[1] == "status" and damage == "dirty":
            return " M changed.py"
        return ""

    monkeypatch.setattr(runner, "command", command)
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout=b"different\n" if damage == "digest" else blob),
    )
    with pytest.raises((DefconInputError, subprocess.CalledProcessError)):
        runner.frozen_declaration()


@pytest.mark.parametrize("position,count", [(2, 9), (2, 10), (3, 11), (3, 12), (4, 11), (4, 12)])
@pytest.mark.parametrize("award", [0, 2])
def test_development_thresholds_on_both_sides_are_diagnostics_only(
    tmp_path: Path, position: int, count: int, award: int
) -> None:
    def change(documents: dict[str, Any]) -> None:
        row = documents[live_payload(5)]["elements"][position - 1]
        row["stats"]["defensive_contribution"] = count
        row["explain"][0]["stats"][1].update(value=count, points=award)

    snapshot = capture(tmp_path, change=change)
    component = candidate_handoff(
        snapshot, base(snapshot), declaration_sha256=runner.DECLARATION_SHA256
    ).diagnostics["defcon_component"]
    assert component["development_schema_crosschecks"] == 30
    disagree = (count >= (10 if position == 2 else 12)) != (award > 0)
    reasons = {r["reason"] for r in component["development_schema_disagreements"]}
    assert reasons == (
        {"award_value_threshold_disagreement", "count_award_disagreement"} if disagree else set()
    )


def test_scored_fit_history_has_no_development_threshold_crosscheck(tmp_path: Path) -> None:
    def change(documents: dict[str, Any]) -> None:
        row = documents[live_payload(6)]["elements"][1]
        row["stats"]["defensive_contribution"] = 0
        row["explain"][0]["stats"][1]["value"] = 0

    snapshot = capture(tmp_path, target=7, change=change)
    component = candidate_handoff(
        snapshot, base(snapshot, target=7), declaration_sha256=runner.DECLARATION_SHA256
    ).diagnostics["defcon_component"]
    assert component["development_schema_crosschecks"] == 30
    assert component["development_schema_disagreements"] == []


def test_invalid_second_double_fixture_keeps_first_and_gk_is_not_zero_term(tmp_path: Path) -> None:
    def change(documents: dict[str, Any]) -> None:
        documents[live_payload(1)]["elements"][1]["explain"][1]["stats"][1][
            "points_modification"
        ] = 1

    snapshot = capture(tmp_path, double=True, change=change)
    original = base(snapshot)
    original = replace(
        original,
        appearance_probability={
            k: v for k, v in original.appearance_probability.items() if k != 101
        },
    )
    component = candidate_handoff(
        snapshot, original, declaration_sha256=runner.DECLARATION_SHA256
    ).diagnostics["defcon_component"]
    assert component["rates"]["player_appearances"]["102"] == 5
    assert [r["fixture"] for r in component["excluded_fit_rows"]] == [98]
    assert 101 not in component["zero_term_player_codes"]


def test_distinct_captured_position_awards_supply_both_candidate_and_paired_diagnostic(
    tmp_path: Path,
) -> None:
    def change(documents: dict[str, Any]) -> None:
        scoring = documents[BOOTSTRAP_PAYLOAD]["game_config"]["scoring"]
        for position, amount in (("DEF", 2), ("MID", 3), ("FWD", 4)):
            scoring["defensive_contribution"][position] = amount
        for name, document in documents.items():
            if re_event(name):
                for row in document["elements"][1:]:
                    for explanation in row["explain"]:
                        explanation["stats"][1]["points"] = row["id"]

    decision = capture(tmp_path / "decision", change=change)
    outcome = capture(tmp_path / "outcome", final=True, change=change)
    original = base(decision)
    component = candidate_handoff(
        decision, original, declaration_sha256=runner.DECLARATION_SHA256
    ).diagnostics["defcon_component"]
    assert component["terms"] == {"101": 0, "102": 1.6, "103": pytest.approx(2.7), "104": 2.8}
    rows, _, _ = runner.paired_week(decision, original, outcome)
    assert {r.player_code: r.awarded_defcon for r in rows} == {102: 2, 103: 3, 104: 4}


def test_absent_legacy_mapping_marks_only_its_week_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captures, kwargs = reading_fixture(tmp_path, monkeypatch)
    snapshot = capture(tmp_path / "snapshots", target=8, instant_offset=1)
    publication(tmp_path, snapshot, replace(base(snapshot, target=8), appearance_probability=None))
    captures[snapshot.metadata.snapshot_id] = runner.partial_snapshot(
        tmp_path / "snapshots" / snapshot.metadata.snapshot_id
    )
    report = runner.reading(captures, **kwargs)
    assert report["valid_weeks"] == 6
    row = next(w for w in report["week_identities"] if w["gameweek"] == 8)
    assert row["status"] == "missing"
    assert "published appearance mapping" in row["detail"]


@pytest.mark.parametrize(
    "appearance, fingerprint",
    [
        (None, "32b72a32e13e38d57cef83fe3b9ec5c129dc1f36c80ec8858f6b5c6c137fd2ae"),
        (
            {101: 1.0, 102: 0.8, 103: 0.9, 104: 0.7},
            "fbba01311d69ad6686fbbcfb1cede0718c0b45f1634e71bbf3eda640cdf54c22",
        ),
    ],
)
def test_literal_develop_fingerprints_without_augmentation(
    appearance: Any, fingerprint: str
) -> None:
    handoff = InSeasonProjection(
        "2026-27",
        6,
        "fpl-live-20260925T163000Z-000000000000",
        "component",
        "phase_c_control_components_v1",
        "phase_c_component_form_window_v1",
        {101: 2.0, 102: 3.0, 103: 4.0, 104: 5.0},
        appearance_probability=appearance,
    )
    assert handoff.fingerprint == fingerprint


@pytest.mark.parametrize("bad", ["a" * 63, "A" * 64, 123])
def test_malformed_augmentation_binding_is_refused(tmp_path: Path, bad: Any) -> None:
    snapshot = capture(tmp_path / "snapshots")
    path = tmp_path / "handoff.json"
    write_projection_handoff(path, base(snapshot))
    document = decode(path.read_bytes())
    document["augmentation_fingerprint"] = bad
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(DataSourceError):
        read_projection_handoff(path)


def test_index_heading_without_its_table_refuses_before_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captures, kwargs = reading_fixture(tmp_path, monkeypatch)
    (runner.ROOT / "docs/measurements_index.md").write_text(
        "## Deterministic policy\n\nNo table\n", encoding="utf-8"
    )
    with pytest.raises(DefconInputError, match="table"):
        runner.reading(captures, **kwargs)
    assert not list(kwargs["claim_directory"].glob("*.json"))


@pytest.mark.parametrize("anchor_count", [0, 2])
def test_index_defcon_anchor_must_be_unique_before_claim_or_outcome_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, anchor_count: int
) -> None:
    captures, kwargs = reading_fixture(tmp_path, monkeypatch)
    path = runner.ROOT / "docs/measurements_index.md"
    contents = path.read_text(encoding="utf-8")
    anchor = next(
        line
        for line in contents.splitlines(keepends=True)
        if line.startswith("| [Direct DEFCON development]")
    )
    path.write_text(contents.replace(anchor, anchor * anchor_count), encoding="utf-8")
    original = runner.partial_snapshot

    def guard(directory: Path, names: Any = None) -> Any:
        if names is not None and any(re_event(name) for name in names):
            pytest.fail("No outcome may open before index anchor validation")
        return original(directory, names)

    monkeypatch.setattr(runner, "partial_snapshot", guard)
    with pytest.raises(DefconInputError, match="direct DEFCON index row"):
        runner.reading(captures, **kwargs)
    assert not list(kwargs["claim_directory"].glob("*.json"))


@pytest.mark.parametrize("count", [None, "absent"])
def test_missing_development_count_stays_ready_and_scored_in_every_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, count: Any
) -> None:
    captures, kwargs = reading_fixture(tmp_path, monkeypatch)

    def change(documents: dict[str, Any]) -> None:
        stats = documents[live_payload(2)]["elements"][1]["stats"]
        if count == "absent":
            del stats["defensive_contribution"]
        else:
            stats["defensive_contribution"] = count

    for week in range(6, 13):
        snapshot = capture(tmp_path / "snapshots", target=week, change=change, instant_offset=1)
        publication(tmp_path, snapshot, base(snapshot, target=week))
        captures[snapshot.metadata.snapshot_id] = runner.partial_snapshot(
            tmp_path / "snapshots" / snapshot.metadata.snapshot_id
        )
    checked = runner.check_inputs(
        captures,
        publications=kwargs["publications"],
        handoffs=kwargs["handoffs"],
        weeks=(6, 7),
        as_of=kwargs["as_of"],
        snapshot_root=kwargs["snapshot_root"],
    )
    assert all(row["status"] == "identity_and_inventory_ready" for row in checked["weeks"])
    assert all(
        row["development_schema_disagreements"][0]["reason"] == "count_absent"
        for row in checked["weeks"]
    )
    report = runner.reading(captures, **kwargs)
    assert report["valid_weeks"] == 7
    assert all(
        row["development_schema_disagreements"][0]["reason"] == "count_absent"
        for row in report["week_identities"]
    )
