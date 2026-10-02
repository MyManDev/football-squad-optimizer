"""Official facts compare content, not editorial timestamps or retrieval order."""

import dataclasses
import json

import jsonschema
import pytest
from tests.unit import test_live_recommendation as live
from tests.unit.test_source_fpl_live import EVENTS, TEAMS, _element

from squadopt.contracts.information import official_information_schema
from squadopt.data.errors import DataError
from squadopt.data.sources.fpl_information import (
    FplInformation,
    captured_fpl_information,
    information_changes,
)
from squadopt.live.recommendation import read_inputs


def _feed(*, observed="2026-08-20T12:00:00Z", changes=None, reverse=False):
    rows = [_element(**(changes or {})), _element(code=99, id=6, team=14)]
    if reverse:
        rows.reverse()
    feed = captured_fpl_information(
        json.dumps({"elements": rows, "teams": TEAMS, "events": EVENTS}).encode(),
        season="2026-27",
        gameweek=1,
        snapshot_id="held",
        observed_at=observed,
    )
    assert isinstance(feed, FplInformation)
    return feed


def test_all_teams_and_persistent_identity_without_editorial_leakage():
    feed = _feed(changes={"news": "Private raw editorial", "news_added": "2026-08-19T12:00:00Z"})
    assert feed.declared_team_count == 2
    assert {p.team_code for p in feed.players} == {3, 14}
    public = feed.public_record([118748])
    assert len(public["players"]) == 1
    assert public["players"][0]["player_id"] == 118748
    assert "Private raw editorial" not in json.dumps(public)
    assert "news_sha256" not in json.dumps(public)


def test_unchanged_fetch_and_order_do_not_change_information_revision():
    before = _feed()
    after = _feed(observed="2026-08-20T13:00:00Z", reverse=True)
    assert before.revision == after.revision
    assert information_changes(before, after)["changed_player_count"] == 0


def test_percentage_change_without_new_date_is_detected():
    before = _feed(changes={"chance_of_playing_next_round": 75})
    after = _feed(observed="2026-08-20T13:00:00Z", changes={"chance_of_playing_next_round": 50})
    assert information_changes(before, after)["changes"] == [
        {"player_id": 118748, "fields": ["chance_percent"]}
    ]


@pytest.mark.parametrize("chance", [None, 0, 25, 50, 75, 100])
def test_zero_and_unknown_remain_distinct(chance):
    feed = _feed(changes={"chance_of_playing_next_round": chance})
    assert next(p for p in feed.players if p.player_id == 118748).chance_percent == chance


def test_cleared_flag_is_not_missing_editorial():
    unknown = _feed()
    cleared = _feed(
        observed="2026-08-20T13:00:00Z",
        changes={"news_added": "2026-08-20T11:00:00Z", "news": ""},
    )
    assert next(p for p in unknown.players if p.player_id == 118748).news_state == "not_reported"
    assert next(p for p in cleared.players if p.player_id == 118748).news_state == "cleared"


def test_changed_text_with_same_dateline_is_detected():
    before = _feed(changes={"news": "ankle", "news_added": "2026-08-19T12:00:00Z"})
    after = _feed(
        observed="2026-08-20T13:00:00Z",
        changes={"news": "illness", "news_added": "2026-08-19T12:00:00Z"},
    )
    assert information_changes(before, after)["changes"][0]["fields"] == ["news_sha256"]


def test_cross_season_and_backwards_comparisons_refused():
    feed = _feed()
    with pytest.raises(DataError, match="one season"):
        information_changes(feed, dataclasses.replace(feed, season="2027-28"))
    with pytest.raises(DataError, match="later"):
        information_changes(feed, feed)


def test_new_and_removed_players_have_explicit_reasons():
    before = _feed()
    after = dataclasses.replace(
        before, observed_at="2026-08-20T13:00:00Z", players=before.players[:1]
    )
    assert information_changes(before, after)["changes"] == [
        {"player_id": before.players[1].player_id, "fields": ["removed"]}
    ]


@pytest.mark.parametrize("chance", [-1, 101, True, 50.1])
def test_invalid_source_percentage_refused(chance):
    with pytest.raises(DataError):
        _feed(changes={"chance_of_playing_next_round": chance})


def _saka(feed):
    return next(p for p in feed.players if p.player_id == 118748)


def test_a_stamp_after_the_observation_is_not_carried_and_the_capture_still_reads():
    on_time = _feed(changes={"news": "ankle", "news_added": "2026-08-20T11:59:59Z"})
    late = _feed(changes={"news": "ankle", "news_added": "2026-08-20T12:00:01Z"})
    assert _saka(on_time).source_added_at == "2026-08-20T11:59:59Z"
    assert _saka(late).source_added_at is None
    assert _saka(late).news_state == "present"
    assert dataclasses.replace(_saka(late), source_added_at="2026-08-20T11:59:59Z") == _saka(
        on_time
    )
    other = [p for p in late.players if p.player_id != 118748]
    assert other == [p for p in on_time.players if p.player_id != 118748]
    public = late.public_record([118748])
    jsonschema.validate(public, official_information_schema())
    assert public["players"][0]["source_added_at"] is None


def test_a_stamp_at_the_observation_is_carried():
    feed = _feed(changes={"news": "ankle", "news_added": "2026-08-20T12:00:00Z"})
    assert _saka(feed).source_added_at == "2026-08-20T12:00:00Z"


def test_a_cleared_note_with_a_late_stamp_is_still_cleared_and_not_unreported():
    feed = _feed(changes={"news": "", "news_added": "2026-08-21T00:00:00Z"})
    assert _saka(feed).source_added_at is None
    assert _saka(feed).news_state == "cleared"


def test_one_late_stamp_no_longer_stops_reading_the_capture(tmp_path):
    elements = live._elements()
    late = elements[0]
    late.update(news="Knock", news_added="2026-08-13T20:11:44Z")
    snapshot = live._capture(tmp_path, live._bootstrap(elements=elements))
    inputs = read_inputs(snapshot, season=live.SEASON)
    assert inputs.official_information is not None
    (row,) = (p for p in inputs.official_information.players if p.player_id == late["code"])
    assert row.source_added_at is None
    assert row.news_state == "present"


def test_a_malformed_stamp_is_still_refused():
    with pytest.raises(DataError):
        _feed(changes={"news": "ankle", "news_added": "yesterday"})


def test_legacy_capture_has_no_invented_news():
    row = _element()
    del row["news"]
    assert (
        captured_fpl_information(
            json.dumps({"elements": [row]}).encode(),
            season="2026-27",
            gameweek=1,
            snapshot_id="legacy",
            observed_at="2026-08-20T12:00:00Z",
        )
        is None
    )
