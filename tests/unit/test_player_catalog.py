"""The browsable roster must never inherit optimizer eligibility filters."""

import json

import pytest
from jsonschema import ValidationError

from squadopt.application.player_catalog import player_catalog, validate_catalog
from squadopt.data.snapshots import read_snapshot, write_snapshot


def capture(tmp_path):
    document = {
        "events": [{"id": 1, "deadline_time": "2026-08-21T10:00:00Z", "finished": True}],
        "teams": [{"id": 10, "name": "Arsenal"}],
        "elements": [
            {
                "id": i,
                "code": 1000 + i,
                "first_name": "Player",
                "second_name": str(i),
                "team": 10,
                "element_type": i,
                "minutes": 0,
                "status": "i",
                "now_cost": 0,
            }
            for i in range(1, 5)
        ],
    }
    meta = write_snapshot(
        tmp_path,
        source="fpl-live",
        captured_at_utc="2026-09-22T12:00:00Z",
        payloads={"bootstrap-static.json": json.dumps(document).encode()},
    )
    return read_snapshot(tmp_path, meta.snapshot_id)


def test_all_positions_including_injured_zero_minute_players_keep_persistent_codes(tmp_path):
    catalog = player_catalog(capture(tmp_path))
    assert catalog["season"] == "2026-27"
    assert catalog["captured_at_utc"] == "2026-09-22T12:00:00Z"
    assert {p["id"] for p in catalog["players"]} == {1001, 1002, 1003, 1004}
    assert {p["position"] for p in catalog["players"]} == {"GK", "DEF", "MID", "FWD"}
    assert all(p["team_id"] == 10 for p in catalog["players"])


@pytest.mark.parametrize(
    "fault", ["duplicate_player", "duplicate_team", "unknown_team", "position", "timestamp"]
)
def test_invalid_catalog_fails_closed(tmp_path, fault):
    catalog = player_catalog(capture(tmp_path))
    if fault == "duplicate_player":
        catalog["players"].append(catalog["players"][0])
    elif fault == "duplicate_team":
        catalog["teams"].append(catalog["teams"][0])
    elif fault == "unknown_team":
        catalog["players"][0]["team_id"] = 999
    elif fault == "position":
        catalog["players"][0]["position"] = "SUB"
    else:
        catalog["captured_at_utc"] = "unknown"
    with pytest.raises((ValueError, ValidationError)):
        validate_catalog(catalog)
