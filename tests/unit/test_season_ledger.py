"""Tests for the season ledger: frozen decisions, settled outcomes, and trust.

The ledger's whole value is that a recorded decision can be proven to be the decision
that was made. So the tests attack exactly that: overwriting, tampering, settling
without a decision, settling twice, and realized points read from a capture that has
not actually finished the gameweek.
"""

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.live import (
    SEASON_LEDGER_CONTRACT_VERSION,
    LedgerError,
    Projection,
    Recommendation,
    build_recommendation,
    extract_event_points,
    ledger_summary,
    load_entry,
    load_ledger,
    project,
    read_inputs,
    record_decision,
    record_outcome,
    render,
    summary_markdown,
)

SEASON = "2026-27"
HISTORY_SEASON = "2025-26"
CAPTURED_AT = "2026-08-13T20:11:43Z"

EVENTS: list[dict[str, Any]] = [
    {"id": 1, "deadline_time": "2026-08-21T17:30:00Z", "finished": False},
    {"id": 2, "deadline_time": "2026-08-28T17:30:00Z", "finished": False},
]
TEAMS: list[dict[str, Any]] = [
    {"id": index, "code": index * 3, "name": f"Club {index}", "short_name": f"C{index}"}
    for index in range(1, 7)
]
POSITIONS: dict[int, str] = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
SHAPE: list[tuple[int, int]] = [(1, 3), (2, 8), (3, 8), (4, 5)]


def _elements(event_points: dict[int, int] | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    code = 1000
    for element_type, count in SHAPE:
        for index in range(count):
            code += 1
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
            if event_points is not None:
                record["event_points"] = event_points.get(code, 2)
            records.append(record)
    return records


def _bootstrap(**overrides: Any) -> bytes:
    document: dict[str, Any] = {
        "events": EVENTS,
        "teams": TEAMS,
        "elements": _elements(),
    }
    document.update(overrides)
    return json.dumps(document).encode("utf-8")


def _capture(tmp_path: Path, bootstrap: bytes | None = None, captured_at: str = CAPTURED_AT) -> Any:
    metadata = write_snapshot(
        tmp_path,
        source="fpl-live",
        captured_at_utc=captured_at,
        payloads={
            BOOTSTRAP_PAYLOAD: _bootstrap() if bootstrap is None else bootstrap,
            FIXTURES_PAYLOAD: b"[]",
        },
    )
    return read_snapshot(tmp_path, metadata.snapshot_id)


def _panel(*, players: tuple[int, ...] = ()) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for code in players:
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
    if not rows:
        rows.append(
            {
                "season": HISTORY_SEASON,
                "gameweek": 1,
                "player_id": 999_999,
                "name": "Nobody",
                "team_id": "Club 1",
                "position": "MID",
                "price_tenths": 50,
                "minutes": 0,
                "total_points": 0,
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture(name="decision_world")
def _decision_world(tmp_path: Path) -> tuple[Recommendation, Projection, Path]:
    snapshot = _capture(tmp_path / "snapshots")
    inputs = read_inputs(snapshot, season=SEASON)
    projection = project(inputs, _panel(players=(1001, 1004, 1012)))
    recommendation = build_recommendation(inputs, projection)
    return recommendation, projection, tmp_path / "ledger"


def _flat_points(recommendation: Recommendation, value: float = 2.0) -> dict[int, float]:
    return {int(player): value for player in recommendation.squad["player_id"]}


# --- recording decisions ----------------------------------------------------


def test_a_recorded_decision_round_trips_with_full_provenance(
    decision_world: tuple[Recommendation, Projection, Path],
) -> None:
    recommendation, projection, root = decision_world

    directory = record_decision(
        root, recommendation, projection, report_text=render(recommendation)
    )

    assert directory == root / SEASON / "gw01"
    entry = load_entry(root, SEASON, 1)
    assert entry.decision["contract_version"] == SEASON_LEDGER_CONTRACT_VERSION
    assert entry.decision["snapshot_id"] == recommendation.snapshot_id
    assert entry.decision["prediction_fingerprint"] == recommendation.prediction_fingerprint
    assert entry.decision["captain_player_id"] == int(recommendation.captain["player_id"])
    assert len(list(entry.decision["squad_player_ids"])) == 15  # type: ignore[arg-type]
    assert entry.outcome is None
    stored = pd.read_csv(directory / "projections.csv")
    assert len(stored) == len(projection.table)


def test_an_existing_entry_is_never_overwritten(
    decision_world: tuple[Recommendation, Projection, Path],
) -> None:
    recommendation, projection, root = decision_world
    record_decision(root, recommendation, projection, report_text="report")

    with pytest.raises(LedgerError, match="immutable"):
        record_decision(root, recommendation, projection, report_text="report")


def test_a_tampered_file_fails_its_checksum_on_load(
    decision_world: tuple[Recommendation, Projection, Path],
) -> None:
    recommendation, projection, root = decision_world
    directory = record_decision(root, recommendation, projection, report_text="report")

    projections = directory / "projections.csv"
    projections.write_text(projections.read_text(encoding="utf-8") + "tampered\n", "utf-8")

    with pytest.raises(LedgerError, match="does not match its recorded digest"):
        load_entry(root, SEASON, 1)


def test_a_missing_recorded_file_is_refused(
    decision_world: tuple[Recommendation, Projection, Path],
) -> None:
    recommendation, projection, root = decision_world
    directory = record_decision(root, recommendation, projection, report_text="report")
    (directory / "report.txt").unlink()

    with pytest.raises(LedgerError, match="missing recorded file"):
        load_entry(root, SEASON, 1)


# --- crash safety and the writer lock -----------------------------------------


def test_a_crash_before_the_manifest_leaves_no_entry_and_the_retry_succeeds(
    decision_world: tuple[Recommendation, Projection, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from squadopt.live import ledger as ledger_module

    recommendation, projection, root = decision_world

    def explode(directory: Path) -> None:
        raise RuntimeError("power cut")

    monkeypatch.setattr(ledger_module, "_write_manifest", explode)
    with pytest.raises(RuntimeError, match="power cut"):
        record_decision(root, recommendation, projection, report_text="report")
    monkeypatch.undo()

    # Nothing landed: no gameweek directory, no staging leftovers, no lock; the
    # season reads as empty and the retry records normally.
    assert not (root / SEASON / "gw01").exists()
    assert [p.name for p in (root / SEASON).iterdir()] == []
    assert load_ledger(root, SEASON) == ()
    directory = record_decision(root, recommendation, projection, report_text="report")
    assert directory.is_dir()
    assert load_entry(root, SEASON, 1).decision["gameweek"] == 1


def test_a_stale_staging_directory_is_ignored_by_readers_and_pruned_by_the_writer(
    decision_world: tuple[Recommendation, Projection, Path],
) -> None:
    import os
    import time

    from squadopt.live.ledger import prune_stale_staging

    recommendation, projection, root = decision_world
    stale = root / SEASON / ".gw01.staging-999-deadbeef"
    stale.mkdir(parents=True)
    (stale / "decision.json").write_text("{}", encoding="utf-8")
    old = time.time() - 2 * 3600
    os.utime(stale, (old, old))
    fresh = root / SEASON / ".gw01.staging-1000-cafef00d"
    fresh.mkdir()

    assert load_ledger(root, SEASON) == ()
    with pytest.raises(LedgerError, match="No ledger entry"):
        load_entry(root, SEASON, 1)
    directory = record_decision(root, recommendation, projection, report_text="report")
    assert directory.is_dir()
    assert not stale.exists()  # pruned before writing
    assert fresh.exists()  # a young staging directory may belong to a live writer
    assert prune_stale_staging(root, SEASON, older_than_seconds=0.0) == 1
    assert not fresh.exists()
    assert [entry.gameweek for entry in load_ledger(root, SEASON)] == [1]


def test_a_second_writer_is_refused_while_the_lock_is_held_and_a_stale_lock_is_broken(
    decision_world: tuple[Recommendation, Projection, Path],
) -> None:
    import os
    import time

    recommendation, projection, root = decision_world
    lock = root / SEASON / ".gw01.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("1234 held", encoding="utf-8")

    with pytest.raises(LedgerError, match="holds the ledger lock"):
        record_decision(root, recommendation, projection, report_text="report")
    assert not (root / SEASON / "gw01").exists()

    old = time.time() - 3600
    os.utime(lock, (old, old))
    directory = record_decision(root, recommendation, projection, report_text="report")
    assert directory.is_dir()
    assert not lock.exists()  # released after the write


def test_an_outcome_whose_manifest_rewrite_was_lost_is_completed_not_refused(
    decision_world: tuple[Recommendation, Projection, Path],
) -> None:
    recommendation, projection, root = decision_world
    directory = record_decision(root, recommendation, projection, report_text="report")
    points = _flat_points(recommendation, value=2.0)
    outcome_path = record_outcome(
        root, SEASON, 1, points, source_snapshot_id=recommendation.snapshot_id
    )
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert "outcome.json" in manifest["files"]

    # Simulate the crash window: outcome landed, manifest still the decision-time one.
    del manifest["files"]["outcome.json"]
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    again = record_outcome(root, SEASON, 1, points, source_snapshot_id=recommendation.snapshot_id)
    assert again == outcome_path
    repaired = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert "outcome.json" in repaired["files"]
    # And a genuinely recorded outcome is still immutable.
    with pytest.raises(LedgerError, match="immutable"):
        record_outcome(root, SEASON, 1, points, source_snapshot_id=recommendation.snapshot_id)


# --- settling outcomes ------------------------------------------------------


def test_settling_scores_the_frozen_xi_with_the_captain_doubled(
    decision_world: tuple[Recommendation, Projection, Path],
) -> None:
    recommendation, projection, root = decision_world
    record_decision(root, recommendation, projection, report_text="report")
    points = _flat_points(recommendation, value=2.0)
    captain = int(recommendation.captain["player_id"])
    points[captain] = 10.0

    record_outcome(root, SEASON, 1, points, source_snapshot_id="later-capture")

    entry = load_entry(root, SEASON, 1)
    assert entry.outcome is not None
    # Ten non-captain starters at 2.0 plus the captain's 10.0 counted twice.
    assert entry.outcome["realized_xi_score"] == pytest.approx(10 * 2.0 + 2 * 10.0)
    expected_error = (10 * 2.0 + 2 * 10.0) - recommendation.projected_score
    assert entry.outcome["projection_error"] == pytest.approx(expected_error)


def test_an_outcome_without_a_frozen_decision_is_refused(tmp_path: Path) -> None:
    with pytest.raises(LedgerError, match="No recorded decision"):
        record_outcome(tmp_path / "ledger", SEASON, 1, {1001: 2.0}, source_snapshot_id="x")


def test_an_outcome_is_recorded_exactly_once(
    decision_world: tuple[Recommendation, Projection, Path],
) -> None:
    recommendation, projection, root = decision_world
    record_decision(root, recommendation, projection, report_text="report")
    points = _flat_points(recommendation)
    record_outcome(root, SEASON, 1, points, source_snapshot_id="later-capture")

    with pytest.raises(LedgerError, match="already recorded"):
        record_outcome(root, SEASON, 1, points, source_snapshot_id="later-capture")


def test_realized_points_must_cover_every_selected_player(
    decision_world: tuple[Recommendation, Projection, Path],
) -> None:
    recommendation, projection, root = decision_world
    record_decision(root, recommendation, projection, report_text="report")
    points = _flat_points(recommendation)
    points.pop(int(recommendation.captain["player_id"]))

    with pytest.raises(LedgerError, match="do not cover every selected player"):
        record_outcome(root, SEASON, 1, points, source_snapshot_id="later-capture")


# --- realized points from a raw capture -------------------------------------


def test_event_points_are_read_by_persistent_code_from_a_finished_gameweek(
    tmp_path: Path,
) -> None:
    finished = [dict(EVENTS[0], finished=True), EVENTS[1]]
    snapshot = _capture(
        tmp_path,
        bootstrap=_bootstrap(events=finished, elements=_elements(event_points={1001: 7})),
        captured_at="2026-08-24T09:00:00Z",
    )

    points = extract_event_points(snapshot, gameweek=1)

    assert points[1001] == 7.0
    assert points[1002] == 2.0
    assert set(points) == {element["code"] for element in _elements()}


def test_an_unfinished_gameweek_cannot_be_settled(tmp_path: Path) -> None:
    snapshot = _capture(tmp_path, bootstrap=_bootstrap(elements=_elements(event_points={})))

    with pytest.raises(LedgerError, match="not finished"):
        extract_event_points(snapshot, gameweek=1)


def test_a_capture_without_event_points_cannot_settle(tmp_path: Path) -> None:
    finished = [dict(EVENTS[0], finished=True), EVENTS[1]]
    snapshot = _capture(tmp_path, bootstrap=_bootstrap(events=finished))

    with pytest.raises(LedgerError, match="no event_points"):
        extract_event_points(snapshot, gameweek=1)


def test_an_unpublished_gameweek_cannot_be_settled(tmp_path: Path) -> None:
    snapshot = _capture(tmp_path)

    with pytest.raises(LedgerError, match="publishes no gameweek 38"):
        extract_event_points(snapshot, gameweek=38)


# --- the season view --------------------------------------------------------


def test_the_summary_shows_settled_and_pending_gameweeks(
    decision_world: tuple[Recommendation, Projection, Path],
) -> None:
    recommendation, projection, root = decision_world
    record_decision(root, recommendation, projection, report_text="report")
    record_outcome(
        root, SEASON, 1, _flat_points(recommendation), source_snapshot_id="later-capture"
    )

    table = ledger_summary(root, SEASON)

    assert table["gameweek"].tolist() == [1]
    assert bool(table.loc[0, "settled"]) is True
    assert table.loc[0, "realized_score"] == pytest.approx(12 * 2.0)
    markdown = summary_markdown(root, SEASON)
    assert SEASON_LEDGER_CONTRACT_VERSION in markdown
    assert "Settled gameweeks: 1" in markdown


def test_an_empty_season_loads_as_empty(tmp_path: Path) -> None:
    assert load_ledger(tmp_path / "ledger", SEASON) == ()
    assert ledger_summary(tmp_path / "ledger", SEASON).empty
