import json
from dataclasses import replace

import pytest

from squadopt.data.snapshots import CapturedSnapshot, SnapshotMetadata
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, live_payload
from squadopt.experiments.availability_calibration import (
    availability_observations,
    calibration_report,
)
from squadopt.live import season_from_bootstrap


def snapshot(
    name="pre",
    *,
    at="2026-08-20T12:00:00Z",
    checked=False,
    stated=75,
    status="d",
    minutes=90,
    element=10,
):
    bootstrap = {
        "events": [
            {
                "id": 1,
                "deadline_time": "2026-08-21T17:30:00Z",
                "finished": checked,
                "data_checked": checked,
                "is_next": True,
            }
        ],
        "elements": [
            {"id": element, "code": 100, "status": status, "chance_of_playing_next_round": stated}
        ],
    }
    payloads = {BOOTSTRAP_PAYLOAD: json.dumps(bootstrap).encode()}
    if checked:
        payloads[live_payload(1)] = json.dumps(
            {
                "elements": [
                    {"id": element, "stats": {"minutes": minutes, "total_points": 2, "starts": 1}}
                ]
            }
        ).encode()
    return CapturedSnapshot(SnapshotMetadata(name, "fpl-live", at, "v1", {}, "test"), payloads)


def measure(*snapshots):
    rows, exclusions = availability_observations(snapshots, season_of=season_from_bootstrap)
    return rows, calibration_report(rows, exclusions)


def test_unsettled_is_absent_and_stated_missing_is_not_zero() -> None:
    rows, report = measure(snapshot(stated=None, status="a"))
    assert rows[0]["played"] is None
    assert report["bins"][0]["stated_value"] is None
    assert report["bins"][0]["realized_rate"] is None
    assert report["bins"][0]["played"] is None


def test_latest_forecast_is_counted_once_and_codes_join_across_element_ids() -> None:
    rows, report = measure(
        snapshot(),
        snapshot("later", at="2026-08-21T12:00:00Z", stated=100),
        snapshot("post", at="2026-08-25T12:00:00Z", checked=True, element=999),
    )
    assert len(rows) == 2
    assert report["unique_player_weeks"] == 1
    assert report["observed_player_weeks"] == 1
    assert report["bins"][0]["stated_value"] == 100
    assert report["bins"][0]["realized_rate"] == 1
    assert len(report["per_capture"]) == 2


def test_checked_zero_minutes_is_a_measured_nonappearance() -> None:
    _, report = measure(
        snapshot(), snapshot("post", at="2026-08-25T12:00:00Z", checked=True, minutes=0)
    )
    assert report["bins"][0]["realized_rate"] == 0
    assert report["bins"][0]["played"] == 0


def test_unchecked_or_other_season_outcome_cannot_fill_a_gap() -> None:
    post = snapshot("post", at="2026-08-25T12:00:00Z", checked=True)
    bootstrap = json.loads(post.payloads[BOOTSTRAP_PAYLOAD])
    bootstrap["events"][0]["data_checked"] = False
    unchecked = replace(
        post, payloads={**post.payloads, BOOTSTRAP_PAYLOAD: json.dumps(bootstrap).encode()}
    )
    _, report = measure(snapshot(), unchecked)
    assert report["observed_player_weeks"] == 0
    bootstrap["events"][0].update(deadline_time="2025-08-21T17:30:00Z", data_checked=True)
    other = replace(
        post, payloads={**post.payloads, BOOTSTRAP_PAYLOAD: json.dumps(bootstrap).encode()}
    )
    _, report = measure(snapshot(), other)
    assert report["observed_player_weeks"] == 0


@pytest.mark.parametrize("stated", [True, -1, 101, 50.5, "75"])
def test_invalid_feed_value_refuses_measurement(stated) -> None:
    with pytest.raises(ValueError):
        measure(snapshot(stated=stated))
