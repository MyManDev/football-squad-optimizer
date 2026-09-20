"""A capture calendar and already computed gains, with no additional chip solve."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import tests.unit.test_live_transfers as world_module
from tests.unit.test_advice_chips import ENVELOPE, _every_chip_open
from tests.unit.test_league_views import _legal_squad, _member_picks, _Provider, _world_context

from squadopt.application import advice_menu
from squadopt.application.advice_menu import MenuRequest
from squadopt.application.advice_record import load_member_advice_record
from squadopt.application.chip_forecast_publication import (
    ForecastSource,
    ForecastUnavailable,
    calendar_counts,
    member_chip_forecast,
    published_chip_gains,
)
from squadopt.application.entries import EntryRegistration
from squadopt.application.fixtures_view import (
    FixtureGameweekView,
    FixturesView,
    FixtureTeamView,
    FixtureView,
)
from squadopt.application.league_views import build_league_views
from squadopt.application.strategies import PUBLISHABLE_FIELDS

world = world_module._world


def _source(snapshot: str, clubs: dict[str, int]) -> ForecastSource:
    teams = [FixtureTeamView(number, name, name) for name, number in clubs.items()]
    games = tuple(
        FixtureView(n, None, teams[n * 2], teams[n * 2 + 1], False, None, None)
        for n in range(len(teams) // 2)
    )
    return ForecastSource(
        snapshot,
        FixturesView(
            "2026-27",
            snapshot,
            "2026-08-25T00:00:00Z",
            2,
            0,
            tuple(FixtureGameweekView(w, "2026-08-25T00:00:00Z", games) for w in range(2, 20)),
        ),
        clubs,
    )


def test_calendar_states_zero_for_absent_club_from_complete_roster() -> None:
    source = _source("capture", {"A": 1, "B": 2, "Blank": 3})
    counts = calendar_counts(source, first=2, last=3)
    assert dict(counts[0].fixture_count_by_club) == {1: 1, 2: 1, 3: 0}
    assert counts[0].clubs_blank == 1


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"unscheduled_count": 1}, "fixtures_unscheduled"),
        ({"gameweeks": ()}, "calendar_incomplete"),
    ],
)
def test_ambiguous_calendar_is_refused(change: dict[str, Any], reason: str) -> None:
    source = _source("capture", {"A": 1, "B": 2})
    assert source.calendar is not None
    source = replace(source, calendar=replace(source.calendar, **change))
    with pytest.raises(ForecastUnavailable, match=reason):
        calendar_counts(source, first=2, last=3)


def _member(world: dict[str, Any]) -> dict[str, Any]:
    inputs, projection, rules = _world_context(world)
    picks = replace(_member_picks(world, 101, _legal_squad(world)), chips_used={})
    names = sorted(set(str(name) for name in projection.table.team_id))
    return {
        "league_id": 352490,
        "picks": picks,
        "inputs": inputs,
        "projection": projection,
        "rules": _every_chip_open(rules),
        "source": _source(inputs.snapshot_id, {name: n for n, name in enumerate(names, 1)}),
    }


def test_only_supplied_gain_is_known_and_each_reading_stands_alone(world: dict[str, Any]) -> None:
    args = _member(world)
    published = member_chip_forecast(**args, gains={"bboost": 30, "3xc": 25})
    fresh = member_chip_forecast(**args, gains={"bboost": -2})
    assert published["status"] == fresh["status"] == "available"
    old_rows = {row["name"]: row for row in published["forecast"]["chips"]}
    rows = {row["name"]: row for row in fresh["forecast"]["chips"]}
    assert old_rows["3xc"]["gain_this_week"] == 25
    assert rows["3xc"]["gain_this_week"] is None
    assert rows["3xc"]["verdict"] == "unknown_this_week"
    assert rows["bboost"]["gain_this_week"] == -2
    assert fresh["bench_player_ids"] == list(args["picks"].squad[11:])
    assert fresh["source_snapshot_id"] == args["inputs"].snapshot_id


def test_mismatched_capture_or_unknown_history_refuses_only_forecast(world: dict[str, Any]) -> None:
    args = _member(world)
    args["source"] = replace(args["source"], snapshot_id="other")
    result = member_chip_forecast(**args, gains={})
    assert result["reason"] == "capture_mismatch" and result["forecast"] is None
    assert result["calendar_has_structure"] is None and result["calendar_range"] is None
    args = _member(world)
    args["picks"] = replace(args["picks"], chips_used=None)
    assert member_chip_forecast(**args, gains={})["reason"] == "chip_history_unknown"


def test_calendar_structure_does_not_depend_on_a_held_free_hit(world: dict[str, Any]) -> None:
    args = _member(world)
    args["picks"] = replace(args["picks"], chips_used={"freehit": (1,)})
    source = args["source"]
    assert source.calendar is not None
    # The real source lists matches: remove a match, not a pre-existing count.
    # The adapter then states zeros for BOTH absent clubs in its complete roster.
    weeks = source.calendar.gameweeks
    assert weeks[1].fixtures
    blank = replace(weeks[1], fixtures=weeks[1].fixtures[1:])
    args["source"] = replace(
        source, calendar=replace(source.calendar, gameweeks=(weeks[0], blank, *weeks[2:]))
    )
    result = member_chip_forecast(**args, gains={})
    assert result["status"] == "available"
    assert all(row["name"] != "freehit" for row in result["forecast"]["chips"])
    assert result["calendar_has_structure"] is True
    assert result["calendar_range"] == {"first_gameweek": 3, "last_gameweek": 19}
    completed = calendar_counts(args["source"], first=3, last=3)[0]
    assert completed.fixture_count_by_club[weeks[1].fixtures[0].home.team_id] == 0


def test_an_extra_match_accumulates_a_double_and_marks_calendar_structure(
    world: dict[str, Any],
) -> None:
    args = _member(world)
    source = args["source"]
    assert source.calendar is not None
    weeks = source.calendar.gameweeks
    match = weeks[1].fixtures[0]
    extra = replace(match, fixture_id=999, home=match.away, away=match.home)
    doubled = replace(weeks[1], fixtures=(*weeks[1].fixtures, extra))
    args["source"] = replace(
        source, calendar=replace(source.calendar, gameweeks=(weeks[0], doubled, *weeks[2:]))
    )
    counts = calendar_counts(args["source"], first=3, last=3)[0]
    assert counts.fixture_count_by_club[match.home.team_id] == 2
    assert counts.fixture_count_by_club[match.away.team_id] == 2
    assert counts.clubs_doubling == 2
    assert counts.clubs_blank == 0
    result = member_chip_forecast(**args, gains={})
    assert result["status"] == "available"
    assert result["calendar_has_structure"] is True


def test_no_held_window_has_an_explicit_empty_examined_range(world: dict[str, Any]) -> None:
    args = _member(world)
    args["picks"] = replace(
        args["picks"], chips_used={name: (1,) for name in ("wildcard", "freehit", "bboost", "3xc")}
    )
    result = member_chip_forecast(**args, gains={})
    assert result["status"] == "available"
    assert result["calendar_has_structure"] is False
    assert result["calendar_range"] is None
    assert result["forecast"]["chips"] == []


def test_gain_extraction_never_turns_missing_or_boolean_into_zero() -> None:
    assert published_chip_gains(
        [
            ("bboost", {"chip_choice": {"gain_vs_no_chip": -3}}),
            ("3xc", {}),
            ("wildcard", {"chip_choice": {"gain_vs_no_chip": False}}),
        ]
    ) == {"bboost": -3.0, "3xc": None, "wildcard": None}


def test_on_demand_computes_only_requested_chip_and_keeps_plan_on_refusal(
    world: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _member(world)
    calls = []

    def chosen(*_args: Any, chip: str, **_kwargs: Any) -> SimpleNamespace:
        calls.append(chip)
        return SimpleNamespace(payload={"chip_choice": {"gain_vs_no_chip": 3.25}, "moves": []})

    monkeypatch.setattr(advice_menu, "advise_with_chip", chosen)
    source = args.pop("source")
    picks = args.pop("picks")
    league = args.pop("league_id")
    request = MenuRequest("2026-27", 2, league, 101, chip="bboost")
    result = advice_menu.advise_menu_entry(
        request,
        provider=_Provider({101: picks}),
        chip_forecast_source=source,
        **args,
    )
    assert calls == ["bboost"]
    # Check the menu's final output, after it grafts on the optional forecast.
    assert set(result) - ENVELOPE <= PUBLISHABLE_FIELDS
    rows = {row["name"]: row for row in result["chip_forecast"]["forecast"]["chips"]}
    assert rows["bboost"]["gain_this_week"] == 3.25
    assert rows["3xc"]["gain_this_week"] is None
    assert source.calendar is not None
    source = replace(source, calendar=replace(source.calendar, unscheduled_count=1))
    refused = advice_menu.advise_menu_entry(
        request,
        provider=_Provider({101: picks}),
        chip_forecast_source=source,
        **args,
    )
    assert calls == ["bboost", "bboost"]
    assert refused["moves"] == [] and refused["chip_choice"] == result["chip_choice"]
    assert refused["chip_forecast"]["reason"] == "fixtures_unscheduled"
    assert set(refused) - ENVELOPE <= PUBLISHABLE_FIELDS


def test_published_index_and_immutable_record_keep_the_same_forecast(
    world: dict[str, Any],
    tmp_path: Path,
) -> None:
    args = _member(world)
    source = args.pop("source")
    picks = args.pop("picks")
    root = tmp_path / "records"
    out = tmp_path / "site"
    build_league_views(
        _Provider({101: picks}),
        (EntryRegistration(101, "member", "2026-08-23T00:00:00Z"),),
        league_name="Test league",
        out_dir=out,
        rival_menu=False,
        advice_record_root=root,
        chip_forecast_source=source,
        **args,
    )
    raw = (out / "advice/101/index.json").read_bytes()
    published = json.loads(raw)["payload"]["chip_forecast"]
    assert published["status"] == "available"
    record = load_member_advice_record(root, "2026-27", 2, 101, args["inputs"].snapshot_id)
    block = record["chip_forecast"]
    assert json.loads(block["document_json"]) == published
    assert block["document_json"].encode() in raw
    assert block["published_index_path"] == "advice/101/index.json"
