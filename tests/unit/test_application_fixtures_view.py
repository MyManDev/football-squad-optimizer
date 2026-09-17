"""Synthetic capture-to-view checks for ``data/fixtures.json``; no upstream calls."""

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from squadopt.application.fixtures_view import fixtures_schema, fixtures_view
from squadopt.application.site import build_site
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, SnapshotMetadata, payload_checksum

CAPTURED = "2026-09-17T10:33:11Z"
TEAMS = [
    {"id": 1, "name": "Arsenal", "short_name": "ARS"},
    {"id": 2, "name": "Aston Villa", "short_name": "AVL"},
    {"id": 3, "name": "Brentford", "short_name": "BRE"},
    {"id": 4, "name": "Chelsea", "short_name": "CHE"},
]
EVENTS = [
    {"id": 1, "deadline_time": "2026-08-21T17:30:00Z", "finished": True},
    {"id": 2, "deadline_time": "2026-09-19T10:00:00Z", "finished": False},
    {"id": 3, "deadline_time": "2026-09-26T10:00:00Z", "finished": False},
]


def fixture(identifier: int, event: int | None, home: int, away: int, **fields: Any) -> dict:
    return {
        "id": identifier,
        "event": event,
        "team_h": home,
        "team_a": away,
        "kickoff_time": None,
        "finished": False,
        "team_h_score": None,
        "team_a_score": None,
        **fields,
    }


FIXTURES = [
    fixture(
        1,
        1,
        1,
        2,
        kickoff_time="2026-08-21T19:00:00Z",
        finished=True,
        team_h_score=3,
        team_a_score=0,
    ),
    fixture(
        2,
        1,
        3,
        4,
        kickoff_time="2026-08-22T14:00:00Z",
        finished=True,
        team_h_score=0,
        team_a_score=0,
    ),
    # Gameweek 2 is a double for Arsenal and a blank for Chelsea; ids arrive out of order.
    fixture(6, 2, 1, 3, kickoff_time="2026-09-20T14:00:00Z"),
    fixture(5, 2, 2, 1, kickoff_time="2026-09-19T14:00:00Z"),
    fixture(4, 2, 3, 2, kickoff_time="2026-09-19T14:00:00Z"),
    fixture(7, 2, 2, 3),
    fixture(8, 3, 4, 1, kickoff_time="2026-09-26T14:00:00Z"),
    fixture(9, None, 4, 2),
]


def capture(
    *,
    fixtures: list[dict] | None = None,
    captured_at_utc: str = CAPTURED,
    events: list[dict] | None = None,
    drop: str | None = None,
) -> CapturedSnapshot:
    payloads = {
        "bootstrap-static.json": json.dumps(
            {"events": EVENTS if events is None else events, "teams": TEAMS}
        ).encode(),
        "fixtures.json": json.dumps(FIXTURES if fixtures is None else fixtures).encode(),
    }
    if drop is not None:
        del payloads[drop]
    return CapturedSnapshot(
        SnapshotMetadata(
            "fpl-live-synthetic",
            "fpl-live",
            captured_at_utc,
            "snapshot_v1",
            {name: payload_checksum(body) for name, body in payloads.items()},
            "digest",
        ),
        payloads,
    )


def payload(snapshot: CapturedSnapshot | None = None) -> dict[str, Any]:
    view = fixtures_view(snapshot or capture())
    assert view is not None
    return view.to_dict()


def test_the_view_is_the_committed_closed_contract() -> None:
    schema = json.loads(Path("docs/contracts/fixtures_v1.schema.json").read_text("utf-8"))
    assert schema == fixtures_schema()
    document = {
        "contract_version": "fixtures_v1",
        "generated_at_utc": CAPTURED,
        "payload": payload(),
    }
    jsonschema.validate(document, schema)
    document["payload"]["gameweeks"][0]["fixtures"][0]["difficulty"] = 2
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, schema)


def test_the_current_gameweek_is_the_first_deadline_still_open_at_the_capture() -> None:
    view = payload()
    assert view["season"] == "2026-27"
    assert view["source_snapshot_id"] == "fpl-live-synthetic"
    assert view["captured_at_utc"] == CAPTURED
    assert view["current_gameweek"] == 2
    assert [week["gameweek"] for week in view["gameweeks"]] == [1, 2, 3]
    assert view["gameweeks"][1]["deadline_utc"] == "2026-09-19T10:00:00Z"
    # A capture taken at the deadline itself is a capture of the week after.
    assert payload(capture(captured_at_utc="2026-09-19T10:00:00Z"))["current_gameweek"] == 3


def test_no_open_deadline_is_a_null_current_gameweek_not_the_last_one() -> None:
    view = payload(capture(captured_at_utc="2027-06-01T00:00:00Z"))
    assert view["current_gameweek"] is None
    assert len(view["gameweeks"]) == 3


def test_fixtures_are_ordered_by_kickoff_then_id_with_no_kickoff_last() -> None:
    week = payload()["gameweeks"][1]
    assert [row["fixture_id"] for row in week["fixtures"]] == [4, 5, 6, 7]
    assert week["fixtures"][3]["kickoff_utc"] is None


def test_an_unplayed_fixture_has_null_scores_and_a_finished_one_keeps_a_nil_nil() -> None:
    view = payload()
    goalless = view["gameweeks"][0]["fixtures"][1]
    assert goalless["finished"] is True
    assert (goalless["home_score"], goalless["away_score"]) == (0, 0)
    assert view["gameweeks"][0]["fixtures"][0]["home"] == {
        "team_id": 1,
        "name": "Arsenal",
        "short_name": "ARS",
    }
    for row in view["gameweeks"][1]["fixtures"]:
        assert row["finished"] is False
        assert row["home_score"] is None and row["away_score"] is None


def test_half_a_score_is_no_score() -> None:
    rows = [fixture(1, 1, 1, 2, team_h_score=1)]
    row = payload(capture(fixtures=rows))["gameweeks"][0]["fixtures"][0]
    assert row["home_score"] is None and row["away_score"] is None


def test_a_double_gameweek_lists_the_team_twice_and_a_blank_one_not_at_all() -> None:
    week = payload()["gameweeks"][1]
    sides = [side for row in week["fixtures"] for side in (row["home"], row["away"])]
    assert sum(1 for side in sides if side["short_name"] == "ARS") == 2
    assert all(side["short_name"] != "CHE" for side in sides)


def test_a_fixture_with_no_gameweek_is_counted_and_not_listed() -> None:
    view = payload()
    assert view["unscheduled_count"] == 1
    listed = [row["fixture_id"] for week in view["gameweeks"] for row in week["fixtures"]]
    assert 9 not in listed and len(listed) == 7


def test_a_gameweek_with_no_fixture_is_still_published_empty() -> None:
    view = payload(capture(fixtures=FIXTURES[:2]))
    assert [len(week["fixtures"]) for week in view["gameweeks"]] == [2, 0, 0]


def test_a_capture_without_either_payload_publishes_nothing() -> None:
    assert fixtures_view(capture(drop="fixtures.json")) is None
    assert fixtures_view(capture(drop="bootstrap-static.json")) is None


@pytest.mark.parametrize(
    "rows",
    [
        [fixture(1, 9, 1, 2)],
        [fixture(1, 1, 1, 99)],
        [fixture(1, 1, 1, 2, team_h_score=-1, team_a_score=0)],
        [fixture(1, 1, 1, 2, finished="yes")],
        [fixture(1, 1, 1, 2, kickoff_time="2026-08-21 19:00")],
    ],
)
def test_a_changed_payload_is_refused_not_rendered_as_blanks(rows: list[dict]) -> None:
    with pytest.raises(DataError):
        fixtures_view(capture(fixtures=rows))


def test_the_site_publishes_it_beside_the_index_and_lists_it(tmp_path: Path) -> None:
    report = build_site(
        ledger_root=tmp_path / "ledger", season="2026-27", out_dir=tmp_path, snapshot=capture()
    )
    assert report.fixtures_written is True
    assert {"fixtures.json", "schema/fixtures_v1.schema.json"} <= set(report.files)
    body = (tmp_path / "data" / "fixtures.json").read_bytes()
    assert b"\r\n" not in body
    document = json.loads(body)
    jsonschema.validate(document, fixtures_schema())
    assert document["payload"]["current_gameweek"] == 2
    index = json.loads((tmp_path / "data" / "index.json").read_text("utf-8"))["payload"]
    assert "fixtures.json" in index["files"]


def test_the_site_publishes_no_fixture_list_it_cannot_vouch_for(tmp_path: Path) -> None:
    other_season = [
        {**event, "deadline_time": f"2025{event['deadline_time'][4:]}"} for event in EVENTS
    ]
    for name, snapshot in {
        "unreadable": capture(fixtures=[fixture(1, 9, 1, 2)]),
        "other-season": capture(events=other_season, captured_at_utc="2025-09-17T10:00:00Z"),
    }.items():
        report = build_site(
            ledger_root=tmp_path / "ledger",
            season="2026-27",
            out_dir=tmp_path / name,
            snapshot=snapshot,
        )
        assert report.fixtures_written is False
        assert "fixtures.json" not in report.files
        assert not (tmp_path / name / "data" / "fixtures.json").exists()
