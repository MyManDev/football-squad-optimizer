"""Tests for the in-season handoff producer.

The producer's own arithmetic is tested in ``test_in_season_blend.py``. What matters here is
the wiring, and specifically the three things that would fail late rather than loudly on a
deadline day: the handoff has to describe the capture the decision will run on, it has to
land on the path the tick waits at, and it has to satisfy the consumer's reader rather than
merely look plausible.

The deadline calendar, club list and squad shape are borrowed from the live path's own tests
so the two do not drift apart. Elements and fixtures are built here because the producer
reads fields those tests do not need: the cumulative counters, and a kick-off time without
which the capture's season phase cannot be established.
"""

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from scripts import build_projection_handoff as producer
from tests.unit.test_live_transfers import EVENTS, SHAPE, TEAMS

from squadopt.data.errors import DataSourceError
from squadopt.data.snapshots import write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.live import CONTROL_MODEL_NAME, handoff_path_for, read_projection_handoff
from squadopt.prediction.component_dataset import (
    FEATURE_CONTRACT_VERSION as COMPONENT_FEATURE_CONTRACT_VERSION,
)
from squadopt.prediction.component_dataset import (
    component_feature_columns,
)
from squadopt.prediction.component_models import COMPONENT_MODEL_VERSION
from squadopt.prediction.elite_evidence import (
    ELITE_EVIDENCE_MODEL_VERSION,
    ELITE_EVIDENCE_POLICY_VERSION,
)
from squadopt.prediction.in_season import (
    IN_SEASON_FEATURE_CONTRACT_VERSION,
    IN_SEASON_MODEL_VERSION,
)

SEASON = "2026-27"
HISTORY_SEASON = "2025-26"
FIRST_KICKOFF = "2026-08-21T19:00:00Z"
# After the opening gameweek, before the second deadline: the instant a real GW2 capture
# is taken, and the only phase in which a capture carries in-season history.
GW2_CAPTURED_AT = "2026-08-28T15:30:00Z"
BEFORE_ANY_KICKOFF = "2026-08-20T17:00:00Z"

COUNTERS = (
    "minutes",
    "total_points",
    "starts",
    "goals_scored",
    "assists",
    "clean_sheets",
    "goals_conceded",
    "saves",
    "bonus",
    "bps",
    "own_goals",
)


def _elements(*, played: dict[int, tuple[int, int]] | None = None) -> list[dict[str, Any]]:
    """The roster, with cumulative counters. ``played`` maps code -> (minutes, points)."""

    minutes_and_points = played or {}
    records: list[dict[str, Any]] = []
    code = 1000
    for element_type, count in SHAPE:
        for index in range(count):
            code += 1
            minutes, points = minutes_and_points.get(code, (0, 0))
            record: dict[str, Any] = {
                "code": code,
                "id": code - 1000,
                "first_name": "Player",
                "second_name": f"{code}",
                "team": (index % 6) + 1,
                "element_type": element_type,
                "now_cost": 45 + (index % 4) * 5,
                "status": "a",
                "chance_of_playing_next_round": None,
                "news": "",
                "news_added": None,
            }
            record.update({name: 0 for name in COUNTERS})
            record["minutes"] = minutes
            record["total_points"] = points
            records.append(record)
    return records


def _bootstrap(elements: list[dict[str, Any]] | None = None) -> bytes:
    finished = [dict(EVENTS[0], finished=True), *EVENTS[1:]]
    document = {
        "events": finished,
        "teams": TEAMS,
        "elements": _elements() if elements is None else elements,
    }
    return json.dumps(document).encode("utf-8")


def _fixtures() -> bytes:
    return json.dumps(
        [
            {
                "id": 1,
                "event": 1,
                "team_h": 1,
                "team_a": 2,
                "team_h_difficulty": 3,
                "team_a_difficulty": 2,
                "kickoff_time": FIRST_KICKOFF,
                "finished": True,
                "provisional_start_time": False,
            }
        ]
    ).encode("utf-8")


def _panel() -> pd.DataFrame:
    """A completed season for some of the roster, so carry-over exists for some codes."""

    rows: list[dict[str, Any]] = []
    for code in (1001, 1004, 1012):
        for gameweek in range(1, 11):
            rows.append(
                {
                    "season": HISTORY_SEASON,
                    "gameweek": gameweek,
                    "player_id": code,
                    "name": f"Player {code}",
                    "team_id": "Club 1",
                    "position": "MID",
                    "price_tenths": 50,
                    "minutes": 90,
                    "total_points": 5,
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture(name="world")
def _world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    snapshot_root = tmp_path / "snapshots"
    after = write_snapshot(
        snapshot_root,
        source="fpl-live",
        captured_at_utc=GW2_CAPTURED_AT,
        payloads={
            BOOTSTRAP_PAYLOAD: _bootstrap(
                _elements(played={1001: (90, 6), 1004: (20, 4), 1013: (75, 5)})
            ),
            FIXTURES_PAYLOAD: _fixtures(),
        },
    )
    before = write_snapshot(
        snapshot_root,
        source="fpl-live",
        captured_at_utc=BEFORE_ANY_KICKOFF,
        payloads={BOOTSTRAP_PAYLOAD: _bootstrap(), FIXTURES_PAYLOAD: _fixtures()},
    )
    monkeypatch.setattr(producer, "build_panel", lambda root: _panel())
    return {
        "snapshot_root": snapshot_root,
        "archive_root": tmp_path,
        "handoff_root": tmp_path / "handoffs",
        "after": after.snapshot_id,
        "before": before.snapshot_id,
    }


def _build(world: dict[str, Any], **kwargs: Any) -> tuple[Any, Path | None, dict[str, object]]:
    return producer.build(
        world["snapshot_root"], world["archive_root"], world["handoff_root"], **kwargs
    )


# --- the contract with the consumer -----------------------------------------


def test_the_handoff_reads_back_through_the_consumers_own_reader(
    world: dict[str, Any],
) -> None:
    """Producer and consumer agreeing is a measurement here, not an assumption.

    ``read_projection_handoff`` recomputes the fingerprint and refuses a file that does not
    match, so a successful read is the two sides agreeing on every field.
    """

    projection, written, _ = _build(world, snapshot_id=world["after"])

    assert written is not None
    reread = read_projection_handoff(written)
    assert reread.fingerprint == projection.fingerprint
    assert reread.expected_points == projection.expected_points


def test_the_handoff_lands_on_the_path_the_tick_waits_at(world: dict[str, Any]) -> None:
    """Resolved through the tick's own helper, so producer and consumer cannot drift."""

    _, written, report = _build(world, snapshot_id=world["after"])

    assert written == handoff_path_for(world["handoff_root"], SEASON, 2)
    assert written is not None
    assert written.name == "2026-27-gw02.json"
    assert report["handoff_path"] == str(written)


def test_the_handoff_names_the_capture_it_was_built_from(world: dict[str, Any]) -> None:
    """The live path refuses a projection made from a different capture."""

    projection, _, _ = _build(world, snapshot_id=world["after"])

    assert projection.source_snapshot_id == world["after"]


def test_the_target_deadline_is_read_from_the_capture(world: dict[str, Any]) -> None:
    """A hand-passed gameweek can be wrong, and the refusal would come after the work."""

    projection, _, report = _build(world, snapshot_id=world["after"])

    assert projection.gameweek == 2
    assert projection.season == SEASON
    assert report["gameweeks_played"] == 1


def test_the_identity_is_the_control_name_and_the_in_season_version(
    world: dict[str, Any],
) -> None:
    """The name is not this path's to choose; only the version distinguishes it."""

    projection, _, _ = _build(world, snapshot_id=world["after"])

    assert projection.model_name == CONTROL_MODEL_NAME
    assert projection.model_version == IN_SEASON_MODEL_VERSION
    assert projection.feature_contract_version == IN_SEASON_FEATURE_CONTRACT_VERSION


# --- coverage ---------------------------------------------------------------


def test_every_rostered_player_appears_in_the_handoff(world: dict[str, Any]) -> None:
    """A missing code is refused by the consumer, so producing one is a producer defect."""

    projection, _, report = _build(world, snapshot_id=world["after"])

    expected_players = sum(count for _, count in SHAPE)
    assert len(projection.expected_points) == expected_players
    assert report["players"] == expected_players
    assert all(value >= 0.0 for value in projection.expected_points.values())


def test_the_declared_weights_travel_with_the_handoff(world: dict[str, Any]) -> None:
    """They surface in the weekly report only if they are in the diagnostics."""

    projection, _, _ = _build(world, snapshot_id=world["after"])

    assert projection.diagnostics["gameweeks_played"] == 1
    assert projection.diagnostics["in_season_weight"] == pytest.approx(1 / 7)
    assert projection.diagnostics["carry_over_weight"] == pytest.approx(6 / 7)


def test_verified_elite_evidence_changes_identity_and_round_trips(
    world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control, _, _ = _build(world, snapshot_id=world["after"], dry_run=True)
    rows = []
    ordered_players = sorted(control.expected_points)
    for offset, player_id in enumerate(ordered_players):
        count = 100 if offset < 11 else 0
        rows.append(
            {
                "season": SEASON,
                "target_gameweek": 2,
                "captured_at_utc": "2026-08-27T08:00:00Z",
                "deadline_timestamp_utc": EVENTS[1]["deadline_time"],
                "player_id": player_id,
                "elite_cohort_size": 100,
                "elite_members_observed": 100,
                "elite_start_count_lag1": count,
                "elite_start_share_lag1": count / 100,
                "elite_evidence_observed": True,
            }
        )
    evidence = pd.DataFrame(rows)
    evidence.attrs.update(
        {
            "elite_members_missing_picks": 0,
            "unmapped_picked_elements": (),
            "table_sha256": "a" * 64,
            "generated_at_utc": "2026-08-27T09:00:00Z",
        }
    )
    monkeypatch.setattr(producer, "read_player_evidence_artifact", lambda *_: evidence)
    table_path = tmp_path / "evidence.csv"
    manifest_path = tmp_path / "evidence.json"
    table_path.write_text("unused\n", encoding="utf-8")
    manifest_path.write_text("{}\n", encoding="utf-8")

    projection, written, report = _build(
        world,
        snapshot_id=world["after"],
        evidence_table_path=table_path,
        evidence_manifest_path=manifest_path,
    )

    assert written is not None
    reread = read_projection_handoff(written)
    assert reread.fingerprint == projection.fingerprint
    assert projection.model_version == ELITE_EVIDENCE_MODEL_VERSION
    assert projection.expected_points[1001] == pytest.approx(control.expected_points[1001] * 1.05)
    last_player = ordered_players[-1]
    assert projection.expected_points[last_player] == pytest.approx(
        control.expected_points[last_player]
    )
    assert report["elite_evidence_policy_version"] == ELITE_EVIDENCE_POLICY_VERSION
    assert report["elite_evidence_manifest_sha256"]
    assert report["version_is_promoted"] is True


def test_evidence_paths_are_an_explicit_pair(world: dict[str, Any], tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="requires both"):
        _build(
            world,
            snapshot_id=world["after"],
            evidence_table_path=tmp_path / "evidence.csv",
        )


def test_the_command_uses_the_component_path_without_evidence_arguments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class Called(Exception):
        pass

    def fake_build(*_args: object, **kwargs: object) -> None:
        assert kwargs["control_only"] is False
        assert kwargs["evidence_table_path"] is None
        assert kwargs["evidence_manifest_path"] is None
        raise Called

    monkeypatch.setattr(producer, "build", fake_build)
    monkeypatch.setattr(
        "sys.argv",
        [
            "build_projection_handoff",
            "--snapshot-root",
            str(tmp_path),
            "--archive-root",
            str(tmp_path),
        ],
    )

    with pytest.raises(Called):
        producer.main()


def test_the_command_forwards_the_verified_evidence_pair(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    table_path = tmp_path / "evidence.csv"
    manifest_path = tmp_path / "evidence.json"

    class Called(Exception):
        pass

    def fake_build(*_args: object, **kwargs: object) -> None:
        assert kwargs["evidence_table_path"] == table_path
        assert kwargs["evidence_manifest_path"] == manifest_path
        raise Called

    monkeypatch.setattr(producer, "build", fake_build)
    monkeypatch.setattr(
        "sys.argv",
        [
            "build_projection_handoff",
            "--snapshot-root",
            str(tmp_path),
            "--archive-root",
            str(tmp_path),
            "--evidence-table",
            str(table_path),
            "--evidence-manifest",
            str(manifest_path),
        ],
    )

    with pytest.raises(Called):
        producer.main()


# --- refusals ---------------------------------------------------------------


def test_a_capture_taken_before_the_counters_reset_is_refused(world: dict[str, Any]) -> None:
    """Its counters are the previous season's; building from them is the silent failure."""

    with pytest.raises(DataSourceError, match="no in-season history"):
        _build(world, snapshot_id=world["before"])


def test_a_dry_run_writes_nothing(world: dict[str, Any]) -> None:
    projection, written, report = _build(world, snapshot_id=world["after"], dry_run=True)

    assert written is None
    assert not Path(str(report["handoff_path"])).exists()
    assert projection.fingerprint


def test_the_latest_capture_is_used_when_none_is_named(world: dict[str, Any]) -> None:
    """Identifiers sort by capture instant, so the newest is the last."""

    projection, _, _ = _build(world)

    assert projection.source_snapshot_id == world["after"]


def test_the_report_says_whether_the_version_is_promoted(world: dict[str, Any]) -> None:
    """A refusal at verification should be predictable from the producer's own output."""

    _, _, report = _build(world, snapshot_id=world["after"], dry_run=True)

    assert "version_is_promoted" in report
    assert isinstance(report["version_is_promoted"], bool)


def test_component_model_is_the_default_when_the_capture_has_settled_history(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = write_snapshot(
        world["snapshot_root"],
        source="fpl-live",
        captured_at_utc="2026-08-28T15:31:00Z",
        payloads={
            BOOTSTRAP_PAYLOAD: _bootstrap(
                _elements(played={1001: (90, 6), 1004: (20, 4), 1013: (75, 5)})
            ),
            FIXTURES_PAYLOAD: _fixtures(),
            "event-gw01-live.json": b"unused by the injected component builder",
        },
    )

    def fake_component(*_args: object, fallback: pd.DataFrame, **_kwargs: object) -> object:
        table = fallback.loc[:, ["player_id", "expected_points"]].copy(deep=True)
        table["expected_points"] = table["expected_points"].add(1.0)
        return table, {"component_fingerprint": "a" * 64}

    monkeypatch.setattr(producer, "_component_table", fake_component)

    projection, _, report = _build(world, snapshot_id=snapshot.snapshot_id, dry_run=True)

    assert projection.model_version == COMPONENT_MODEL_VERSION
    assert projection.feature_contract_version == COMPONENT_FEATURE_CONTRACT_VERSION
    assert report["projection_selection"] == "phase_c_component_default"
    assert report["version_is_promoted"] is True


def test_an_older_capture_records_the_legacy_fallback_reason(world: dict[str, Any]) -> None:
    projection, _, report = _build(world, snapshot_id=world["after"], dry_run=True)

    assert projection.model_version == IN_SEASON_MODEL_VERSION
    assert report["projection_selection"] == "legacy_control_fallback"
    assert report["component_fallback_reason"] == "missing_live_history_payloads"


def test_control_only_is_an_explicit_rollback_even_with_component_history(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = write_snapshot(
        world["snapshot_root"],
        source="fpl-live",
        captured_at_utc="2026-08-28T15:31:00Z",
        payloads={
            BOOTSTRAP_PAYLOAD: _bootstrap(),
            FIXTURES_PAYLOAD: _fixtures(),
            "event-gw01-live.json": b"unused",
        },
    )
    monkeypatch.setattr(
        producer,
        "_component_table",
        lambda *_args, **_kwargs: pytest.fail("component model must not run"),
    )

    projection, _, report = _build(
        world, snapshot_id=snapshot.snapshot_id, control_only=True, dry_run=True
    )

    assert projection.model_version == IN_SEASON_MODEL_VERSION
    assert report["projection_selection"] == "explicit_legacy_control"


def test_component_wiring_fits_composes_and_records_row_level_fallbacks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    feature_columns = component_feature_columns()
    training_rows = []
    for index in range(360):
        appeared = index % 3 != 0
        training_rows.append(
            {
                "season": "2024-25",
                "gameweek": index // 24 + 1,
                "player_id": index + 1,
                "appearance_target": int(appeared),
                "minutes_target": 70 if appeared else pd.NA,
                "points_target": 5 if appeared else pd.NA,
                **{column: float(index % 7 + 1) for column in feature_columns},
            }
        )
    training = pd.DataFrame(training_rows)
    scoring = pd.DataFrame(
        [
            {"player_id": 1001, **{column: 2.0 for column in feature_columns}},
            {
                "player_id": 1002,
                **{
                    column: (pd.NA if column == feature_columns[0] else 2.0)
                    for column in feature_columns
                },
            },
        ]
    )
    scoring["fixture_count"] = [1, 1]

    monkeypatch.setattr(producer, "build_panel", lambda *_args, **_kwargs: pd.DataFrame())
    monkeypatch.setattr(producer, "build_fixture_panel", lambda *_args, **_kwargs: pd.DataFrame())
    monkeypatch.setattr(producer, "load_team_codes", lambda *_args: pd.DataFrame())
    monkeypatch.setattr(
        producer,
        "build_component_modelling_frame",
        lambda *_args, **_kwargs: training,
    )
    monkeypatch.setattr(
        producer,
        "build_live_player_history",
        lambda *_args, **_kwargs: (pd.DataFrame(), (1002,)),
    )
    monkeypatch.setattr(producer, "fixture_snapshot", lambda *_args, **_kwargs: pd.DataFrame())
    monkeypatch.setattr(producer, "_team_bridge", lambda *_args: pd.DataFrame())
    monkeypatch.setattr(
        producer,
        "build_component_scoring_frame",
        lambda *_args, **_kwargs: scoring,
    )

    table, diagnostics = producer._component_table(
        tmp_path,
        bootstrap=b"{}",
        fixtures=b"[]",
        event_payloads={1: b"{}"},
        season=SEASON,
        target=2,
        source_snapshot_id="capture-v1",
        captured_at_utc=GW2_CAPTURED_AT,
        deadline_utc=EVENTS[1]["deadline_time"],
        fallback=pd.DataFrame({"player_id": [1001, 1002], "expected_points": [3.0, 4.0]}),
    )

    by_player = table.set_index("player_id")
    assert by_player.loc[1001, "expected_points"] >= 0.0
    assert by_player.loc[1002, "expected_points"] == 4.0
    assert diagnostics["route:component_model"] == 1
    assert diagnostics["route:direct_control"] == 1
    assert diagnostics["component_history_incomplete_players"] == 1
