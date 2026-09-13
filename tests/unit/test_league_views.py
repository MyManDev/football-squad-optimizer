"""The league views builder: member advice from the seam, independence pinned as fact."""

import dataclasses
import json
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest
import tests.unit.test_live_transfers as world_module

import squadopt.live.transfers as live_transfers
from squadopt.application.entries import EntryError, EntryPicks, EntryRegistration
from squadopt.application.league_views import MemberStanding, build_league_views
from squadopt.data.snapshots import read_snapshot
from squadopt.live import read_inputs, read_season_rules
from squadopt.live.recommendation import project, read_projection_handoff

SEASON = world_module.SEASON

world = world_module._world  # re-register the fixture in this module


class _Provider:
    """A test double for the #127 capture provider, member state per entry id."""

    def __init__(self, picks_by_entry: dict[int, EntryPicks]) -> None:
        self._picks = picks_by_entry

    def picks(self, entry_id: int, season: str, gameweek: int) -> EntryPicks:
        if entry_id not in self._picks:
            raise EntryError(f"No picks captured for entry {entry_id}.")
        return self._picks[entry_id]


def _member_picks(world: dict[str, Any], entry_id: int, squad_codes: list[int]) -> EntryPicks:
    return EntryPicks(
        entry_id=entry_id,
        season=SEASON,
        gameweek=1,
        squad=tuple(squad_codes),
        starting_xi=tuple(squad_codes[:11]),
        captain=squad_codes[0],
        vice_captain=squad_codes[1],
        bank_tenths=5,
        squad_sell_value_tenths=world_module.member_squad_sell_value(world, squad_codes),
        free_transfers=1,
        free_transfers_known=False,
        source_snapshot_id=world["gw2_id"],
    )


def _world_context(world: dict[str, Any]) -> tuple[Any, Any, Any]:
    snapshot = read_snapshot(world["snapshot_root"], world["gw2_id"])
    inputs = read_inputs(snapshot, season=SEASON, gameweek=2)
    handoff = read_projection_handoff(world_module._handoff(world))
    projection = project(inputs, in_season=handoff)
    rules = read_season_rules(snapshot, season=SEASON)
    return inputs, projection, rules


def _legal_squad(world: dict[str, Any]) -> list[int]:
    # The world's shape is 3 GK / 8 DEF / 8 MID / 5 FWD with codes 1001..1024 in
    # position blocks. "Legal" here means the 2-5-5-3 *shape* only: this fifteen holds
    # four from Club 1 and four from Club 2, which the game's three-per-club rule
    # forbids, and it holds the injured 1005. Both are deliberate — the member's first
    # decision is a repair, which is what ``test_a_squad_that_needs_transfers_to_be_legal_
    # falls_back_to_the_hit_plan`` (test_advise_entry.py) exists to cover. It is also why
    # this world's plan cannot respond to MEMBER_PLANNING_POLICY's caution margin: use
    # ``DISCRETIONARY_SQUAD`` below for a member whose transfers are a choice.
    codes = [1001, 1002]  # GK
    codes += [1004, 1005, 1006, 1007, 1008]  # DEF
    codes += [1012, 1013, 1014, 1015, 1016]  # MID
    codes += [1020, 1021, 1022]  # FWD
    return codes


def test_the_builder_renders_members_and_advice_and_survives_one_failure(
    world: dict[str, Any], tmp_path: Path
) -> None:
    inputs, projection, rules = _world_context(world)
    squad = _legal_squad(world)
    provider = _Provider({101: _member_picks(world, 101, squad)})
    registrations = (
        EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),
        EntryRegistration(999, "member-missing", "2026-08-23T00:00:00Z"),
    )
    report = build_league_views(
        provider,
        registrations,
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=tmp_path / "league",
    )
    assert report.rendered_count == 1
    failed = [m for m in report.members if not m.rendered]
    assert len(failed) == 1 and failed[0].entry_id == 999
    assert (tmp_path / "league" / "members.json").is_file()
    assert (tmp_path / "league" / "entries" / "101.json").is_file()
    advice_path = tmp_path / "league" / "advice" / "101" / "saf-puan" / "1.json"
    assert advice_path.is_file()
    import json

    advice = json.loads(advice_path.read_text(encoding="utf-8"))
    assert advice["contract_version"] == "provisional_league_ui_v1"
    assert advice["payload"]["mode"] == "saf-puan"
    # The unknown-flags travel: free transfers were not proven by the source.
    assert "free_transfers" in advice["payload"]["missing_fields"]


def test_a_members_advice_is_invariant_to_every_other_members_state(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """The fairness rule as fact: member 101's advice is byte-identical whether the
    league contains only them, or other members with entirely different squads —
    the builder reads nothing global, so nobody's advice can be bent by anyone's rank."""

    inputs, projection, rules = _world_context(world)
    squad = _legal_squad(world)
    other = list(squad)
    other[10], other[11] = 1017, 1018  # different midfielders for the other member

    alone = _Provider({101: _member_picks(world, 101, squad)})
    crowded = _Provider(
        {
            101: _member_picks(world, 101, squad),
            202: _member_picks(world, 202, other),
        }
    )
    when = __import__("datetime").datetime(2026, 8, 23, 12, 0, tzinfo=__import__("datetime").UTC)
    build_league_views(
        alone,
        (EntryRegistration(101, "a", "2026-08-23T00:00:00Z"),),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="L",
        out_dir=tmp_path / "one",
        now=when,
    )
    build_league_views(
        crowded,
        (
            EntryRegistration(202, "b", "2026-08-23T00:00:00Z"),
            EntryRegistration(101, "a", "2026-08-23T00:00:00Z"),
        ),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="L",
        out_dir=tmp_path / "two",
        now=when,
    )
    first = (tmp_path / "one" / "advice" / "101" / "saf-puan" / "1.json").read_bytes()
    second = (tmp_path / "two" / "advice" / "101" / "saf-puan" / "1.json").read_bytes()
    assert first == second


def test_an_unproven_plan_is_published_with_its_status_not_discarded(
    world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A member whose plan the solver found but could not prove keeps their page.

    Before this, the OPTIMAL-only gate on the member path threw the found plan away and
    the member vanished from their own league — and under a wall-clock budget, which
    members vanished depended on the machine (#247). The plan the solver found is real;
    what was missing is the proof, and the payload now states exactly that: the status
    and the measured bound gap, no more.
    """

    import dataclasses

    from squadopt.live import transfers as live_transfers
    from squadopt.optimization import SolverStatus

    inputs, projection, rules = _world_context(world)
    squad = _legal_squad(world)

    real_plan_transfers = live_transfers.plan_transfers

    def feasible_plan_transfers(*args: Any, **kwargs: Any) -> Any:
        plan, decision, config = real_plan_transfers(*args, **kwargs)
        # The solve is real; only the proof is withheld, as a budget-bound solve would.
        relabelled = dataclasses.replace(
            plan,
            solver_status=SolverStatus.FEASIBLE,
            diagnostics={**dict(plan.diagnostics), "absolute_optimality_gap": 0.25},
        )
        return relabelled, decision, config

    monkeypatch.setattr("squadopt.application.advice.plan_transfers", feasible_plan_transfers)
    report = build_league_views(
        _Provider({101: _member_picks(world, 101, squad)}),
        (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=tmp_path / "unproven",
    )

    assert [member.rendered for member in report.members] == [True]
    raw = (tmp_path / "unproven" / "advice" / "101" / "saf-puan" / "1.json").read_bytes()
    payload = json.loads(raw)["payload"]
    assert payload["solver_status"] == "FEASIBLE"
    assert payload["optimality_gap"] == 0.25
    assert payload["moves"]  # the found plan itself is published, not just the caveat


def test_a_proven_plan_publishes_its_proof(world: dict[str, Any], tmp_path: Path) -> None:
    """The baseline advice carries OPTIMAL and a zero gap when the proof exists."""

    inputs, projection, rules = _world_context(world)
    squad = _legal_squad(world)
    build_league_views(
        _Provider({101: _member_picks(world, 101, squad)}),
        (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=tmp_path / "proven",
    )
    raw = (tmp_path / "proven" / "advice" / "101" / "saf-puan" / "1.json").read_bytes()
    payload = json.loads(raw)["payload"]
    assert payload["solver_status"] == "OPTIMAL"
    assert payload["optimality_gap"] == 0.0


def test_the_members_page_carries_the_league_standing_and_its_order(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """Where a member sits comes from the standings, not from registry order.

    Without it the page shipped rank 0 and a null team for everyone, which reads as a
    league nobody has looked up rather than as one that has not started.
    """

    import json

    from squadopt.application.league_views import MemberStanding

    inputs, projection, rules = _world_context(world)
    squad = _legal_squad(world)
    provider = _Provider(
        {101: _member_picks(world, 101, squad), 202: _member_picks(world, 202, squad)}
    )
    registrations = (
        EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),
        EntryRegistration(202, "member-b", "2026-08-23T00:00:00Z"),
    )
    standings = {
        202: MemberStanding(entry_id=202, team_name="Bea FC", manager_name="Bea B", rank=1),
        101: MemberStanding(entry_id=101, team_name="Ada FC", manager_name="Ada A", rank=2),
    }
    report = build_league_views(
        provider,
        registrations,
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=tmp_path / "league",
        standings=standings,
    )
    assert report.rendered_count == 2
    rows = json.loads((tmp_path / "league" / "members.json").read_text(encoding="utf-8"))[
        "payload"
    ]["members"]
    assert [row["entry_id"] for row in rows] == [202, 101], "standings order, not registry order"
    assert [row["rank"] for row in rows] == [1, 2]
    assert [row["team_name"] for row in rows] == ["Bea FC", "Ada FC"]
    assert [row["manager_name"] for row in rows] == ["Bea B", "Ada A"]
    # Points stay null: the standings parser does not carry them, and a zero would be a
    # number nobody measured.
    assert all(row["gameweek_points"] is None and row["total_points"] is None for row in rows)


def test_without_standings_the_page_still_renders_from_the_registry(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """The producer must not require a standings capture to publish anything."""

    import json

    inputs, projection, rules = _world_context(world)
    squad = _legal_squad(world)
    report = build_league_views(
        _Provider({101: _member_picks(world, 101, squad)}),
        (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=tmp_path / "league",
    )
    assert report.rendered_count == 1
    row = json.loads((tmp_path / "league" / "members.json").read_text(encoding="utf-8"))["payload"][
        "members"
    ][0]
    assert row["manager_name"] == "member-a" and row["team_name"] is None and row["rank"] == 0


def test_the_entry_page_gets_the_members_own_squad_not_our_advice(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """entries/{id}.json describes what the member holds, before any suggestion."""

    import json

    inputs, projection, rules = _world_context(world)
    squad = _legal_squad(world)
    picks = _member_picks(world, 101, squad)
    build_league_views(
        _Provider({101: picks}),
        (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=tmp_path / "league",
    )
    payload = json.loads(
        (tmp_path / "league" / "entries" / "101.json").read_text(encoding="utf-8")
    )["payload"]
    assert payload["league_id"] == 352490
    assert [p["player_id"] for p in payload["starting_xi"]] == list(picks.starting_xi)
    assert len(payload["bench"]) == len(picks.squad) - len(picks.starting_xi)
    assert [p["bench_order"] for p in payload["bench"]] == [1, 2, 3, 4]
    assert sum(1 for p in payload["starting_xi"] if p["is_captain"]) == 1
    assert payload["bank_tenths"] == picks.bank_tenths
    # What the member may spend, stated rather than left for a page to work out by adding
    # up current prices: the game keeps half of every rise since a player was bought, so
    # that total is not a budget. Here the squad's selling value is its priced total
    # because this world's member bought at today's prices.
    assert payload["squad_sell_value_tenths"] == picks.squad_sell_value_tenths
    assert payload["spendable_budget_tenths"] == picks.squad_sell_value_tenths + picks.bank_tenths
    # The unknown flags travel to the entry page too, not just to the advice.
    assert payload["free_transfers_known"] is False
    assert "free_transfers" in payload["missing_fields"]
    # No score comparison is claimed while the standings view carries no points.
    assert payload["squadopt_comparison"] is None
    # What the member can still play, by half, read from this world's rules (one window
    # per chip: the 3xc window opens at gameweek 20) before gameweek 2's deadline.
    chips = payload["chips"]
    assert chips["known"] is True and chips["gameweek"] == 2
    assert {name: halves["first_half"]["state"] for name, halves in chips["states"].items()} == {
        "wildcard": "available",
        "freehit": "available",
        "bboost": "available",
        "3xc": "not_yet",
    }
    assert all(halves["second_half"] is None for halves in chips["states"].values())
    assert payload["chips_used"] == {}
    # The page says which squad it shows: this member's is the captured week's own, with
    # no chip active in it.
    assert payload["squad_basis"] == "captured"
    assert payload["active_chip"] is None


def test_the_entry_page_states_which_squad_it_shows_after_a_free_hit(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """A pre-Free-Hit fifteen must not read as the played week's picks."""

    inputs, projection, rules = _world_context(world)
    picks = dataclasses.replace(
        _member_picks(world, 101, _legal_squad(world)),
        active_chip="freehit",
        chips_used={"freehit": (1,)},
        squad_basis="pre_free_hit_gw01",
    )
    build_league_views(
        _Provider({101: picks}),
        (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=tmp_path / "league",
    )
    payload = json.loads(
        (tmp_path / "league" / "entries" / "101.json").read_text(encoding="utf-8")
    )["payload"]
    assert payload["squad_basis"] == "pre_free_hit_gw01"
    assert payload["active_chip"] == "freehit"
    assert payload["chips_used"] == {"freehit": [1]}
    assert payload["chips"]["known"] is True
    assert payload["chips"]["states"]["freehit"]["first_half"] == {
        "state": "used",
        "gameweek": 1,
        "start_event": 1,
        "stop_event": 19,
    }


def test_the_entry_page_says_when_the_chip_history_was_not_captured(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """``chips.known`` is read from the data: a provider without the history publishes
    the same shape with the flag down, every window ``unknown``, and no raw history at
    all, since an empty map would read as "no chip played".

    The planner behind the advice needs the history, so this path cannot run the whole
    build; the entries document is rendered directly from such a picks object."""

    from squadopt.application.league_views import _entry_squad_payload

    inputs, projection, rules = _world_context(world)
    picks = dataclasses.replace(_member_picks(world, 101, _legal_squad(world)), chips_used=None)
    payload = _entry_squad_payload(
        picks,
        inputs,
        projection,
        rules,
        league_id=352490,
        member_row={"member_kind": "human", "entry_id": 101},
        missing=[],
        scored_gameweek=None,
    )
    chips = payload["chips"]
    assert chips["known"] is False and chips["gameweek"] == 2
    assert {
        name: halves["first_half"]["state"] for name, halves in chips["states"].items()
    } == dict.fromkeys(("wildcard", "freehit", "bboost", "3xc"), "unknown")
    assert payload["chips_used"] is None


def _squad_payload(world: dict[str, Any], picks: EntryPicks) -> dict[str, Any]:
    from squadopt.application.league_views import _entry_squad_payload

    inputs, projection, rules = _world_context(world)
    return _entry_squad_payload(
        picks,
        inputs,
        projection,
        rules,
        league_id=352490,
        member_row={"member_kind": "human", "entry_id": picks.entry_id},
        missing=[],
        scored_gameweek=None,
    )


def test_the_held_vice_captain_reaches_the_entry_page(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """The capture names the vice beside the captain; the page could not say so.

    The member's own armbands are what the entry page is for, and the vice decides where
    the multiplier lands in exactly the weeks the captain blanks. It was read, kept on
    ``EntryPicks`` and then dropped at the document, so the page fell back to saying the
    published squad names nobody.
    """

    import json

    inputs, projection, rules = _world_context(world)
    squad = _legal_squad(world)
    picks = _member_picks(world, 101, squad)
    build_league_views(
        _Provider({101: picks}),
        (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=tmp_path / "league",
    )
    payload = json.loads(
        (tmp_path / "league" / "entries" / "101.json").read_text(encoding="utf-8")
    )["payload"]
    players = [*payload["starting_xi"], *payload["bench"]]
    wearing = [player["player_id"] for player in players if player["is_vice_captain"]]
    assert wearing == [picks.vice_captain]
    # Every other record says so explicitly, and nobody wears both armbands.
    assert all("is_vice_captain" in player for player in players)
    assert not any(player["is_captain"] and player["is_vice_captain"] for player in players)


def test_a_vice_captain_the_member_left_on_the_bench_is_published_with_the_bench(
    world: dict[str, Any],
) -> None:
    """The armband is held in the squad, not in the eleven.

    The capture adapter deliberately accepts a benched vice (``EntryPicksRecord``'s
    docstring says so), and the September capture contains one: entry 3832237 names its
    vice at squad position thirteen. A flag published on the starting eleven alone would
    lose that member's vice entirely.
    """

    squad = _legal_squad(world)
    picks = dataclasses.replace(_member_picks(world, 101, squad), vice_captain=squad[12])
    payload = _squad_payload(world, picks)
    assert not any(player["is_vice_captain"] for player in payload["starting_xi"])
    wearing = [player["player_id"] for player in payload["bench"] if player["is_vice_captain"]]
    assert wearing == [squad[12]]


@pytest.mark.parametrize(
    "case", ["the_captain_himself", "a_player_not_in_the_squad", "unprojected"]
)
def test_a_vice_captain_that_is_not_held_publishes_no_armband_at_all(
    world: dict[str, Any], case: str
) -> None:
    """Absent is not false: a vice that cannot be established is published as nothing.

    ``EntryPicks`` requires a vice rather than defaulting one, but the application type
    proves nothing about the value, so a provider can hand over a stand-in: the captain
    himself, or a player the member does not hold. The third case is the document's own
    doing, not the provider's: a squad member the projection has no row for is dropped from
    the published fifteen, and if that is the vice then flagging the survivors ``false``
    would read as "nobody holds it" rather than "the holder is not on this page".

    In all three the field leaves the document entirely, because ``false`` on all fifteen
    states that the member named nobody, which is a claim the source never made, and the
    page's "not stated" path is the one that must stay live.
    """

    squad = _legal_squad(world)
    unprojected = max(squad) + 500
    if case == "unprojected":
        squad = [*squad[:14], unprojected]
    stand_in = {
        "the_captain_himself": squad[0],
        "a_player_not_in_the_squad": unprojected,
        "unprojected": unprojected,
    }[case]
    picks = dataclasses.replace(_member_picks(world, 101, squad), vice_captain=stand_in)
    payload = _squad_payload(world, picks)
    players = [*payload["starting_xi"], *payload["bench"]]
    assert len(players) == (14 if case == "unprojected" else 15)
    assert not any("is_vice_captain" in player for player in players)


def test_only_the_computed_mode_and_window_are_published(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """A file for an uncomputed mode would show an answer nobody measured."""

    inputs, projection, rules = _world_context(world)
    squad = _legal_squad(world)
    build_league_views(
        _Provider({101: _member_picks(world, 101, squad)}),
        (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=tmp_path / "league",
        rival_menu=False,
    )
    published = sorted(
        path.relative_to(tmp_path / "league").as_posix()
        for path in (tmp_path / "league" / "advice").rglob("*.json")
    )
    assert published == ["advice/101/saf-puan/1.json"]


def test_member_points_travel_with_the_week_they_were_scored_in(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """A score and its gameweek are one fact, because the view is labelled with another.

    ``members.json`` carries the *upcoming* gameweek, so a score published without naming
    its own week would be read under the wrong heading.
    """

    import json

    from squadopt.application.league_views import MemberStanding

    inputs, projection, rules = _world_context(world)
    squad = _legal_squad(world)
    report = build_league_views(
        _Provider({101: _member_picks(world, 101, squad)}),
        (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=tmp_path / "league",
        standings={
            101: MemberStanding(
                entry_id=101,
                team_name="Ada FC",
                manager_name="Ada A",
                rank=1,
                gameweek_points=73,
                total_points=73,
            )
        },
        scored_gameweek=1,
    )
    assert report.rendered_count == 1
    members = json.loads((tmp_path / "league" / "members.json").read_text(encoding="utf-8"))
    assert members["payload"]["scored_gameweek"] == 1
    row = members["payload"]["members"][0]
    assert row["gameweek_points"] == 73 and row["total_points"] == 73
    entry = json.loads((tmp_path / "league" / "entries" / "101.json").read_text(encoding="utf-8"))
    assert entry["payload"]["scored_gameweek"] == 1


def test_the_week_s_transfer_cost_travels_beside_the_week_s_score(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """The published week is gross; without the hit beside it no reader can net it.

    The page puts our net week and every member's week in one column, so the cost has to
    reach the page or the two numbers are on different bases. An absent cost stays absent:
    a member whose hit the capture does not carry is not a member who took no hit, and a
    published zero would say exactly that.
    """

    import json

    from squadopt.application.league_views import MemberStanding

    inputs, projection, rules = _world_context(world)
    squad = _legal_squad(world)
    build_league_views(
        _Provider({101: _member_picks(world, 101, squad)}),
        (
            EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),
            EntryRegistration(202, "member-b", "2026-08-23T00:00:00Z"),
        ),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=tmp_path / "league",
        standings={
            101: MemberStanding(
                entry_id=101,
                team_name="Ada FC",
                manager_name="Ada A",
                rank=1,
                gameweek_points=78,
                total_points=190,
                transfer_cost=4,
            ),
            202: MemberStanding(
                entry_id=202,
                team_name="Bea FC",
                manager_name="Bea B",
                rank=2,
                gameweek_points=51,
                total_points=211,
            ),
        },
        scored_gameweek=3,
    )
    rows = {
        int(row["entry_id"]): row
        for row in json.loads((tmp_path / "league" / "members.json").read_text(encoding="utf-8"))[
            "payload"
        ]["members"]
    }
    assert rows[101]["gameweek_points"] == 78, "the published week stays the source's gross"
    assert rows[101]["transfer_cost"] == 4
    assert rows[202]["transfer_cost"] is None, "an unproven hit is absent, never a zero"


def test_points_without_their_gameweek_are_refused(world: dict[str, Any], tmp_path: Path) -> None:
    from squadopt.application.league_views import MemberStanding

    inputs, projection, rules = _world_context(world)
    squad = _legal_squad(world)
    with pytest.raises(ValueError, match="ship together"):
        build_league_views(
            _Provider({101: _member_picks(world, 101, squad)}),
            (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),),
            inputs,
            projection,
            rules,
            league_id=352490,
            league_name="Test League",
            out_dir=tmp_path / "league",
            standings={
                101: MemberStanding(
                    entry_id=101,
                    team_name="Ada FC",
                    manager_name="Ada A",
                    rank=1,
                    gameweek_points=73,
                    total_points=73,
                )
            },
        )


def test_a_member_whose_picks_fail_still_carries_the_score_the_league_published(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """Points come from the standings side, so an unreadable squad does not erase them."""

    import json

    from squadopt.application.league_views import MemberStanding

    inputs, projection, rules = _world_context(world)
    report = build_league_views(
        _Provider({}),
        (EntryRegistration(999, "member-missing", "2026-08-23T00:00:00Z"),),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=tmp_path / "league",
        standings={
            999: MemberStanding(
                entry_id=999,
                team_name="Ghost FC",
                manager_name="G Manager",
                rank=9,
                gameweek_points=41,
                total_points=41,
            )
        },
        scored_gameweek=1,
    )
    assert report.rendered_count == 0
    row = json.loads((tmp_path / "league" / "members.json").read_text(encoding="utf-8"))["payload"][
        "members"
    ][0]
    assert row["data_quality"] == "empty"
    assert row["gameweek_points"] == 41, "a failed squad must not blank a published score"


class _WorldPaths:
    """One-week fake scenario paths over the world's whole pool, for the mode selector."""

    def __init__(
        self, projection: Any, gameweek: int, *, scenarios: int = 64, seed: int = 3
    ) -> None:
        codes = [int(str(row["player_id"])) for _, row in projection.table.iterrows()]
        generator = np.random.default_rng(seed)
        self._frame = pd.DataFrame(
            generator.uniform(0.0, 8.0, size=(scenarios, len(codes))), columns=codes
        )
        self.target = SimpleNamespace(gameweeks=(gameweek,), horizon=1, window_id=f"gw{gameweek}")
        self.config = SimpleNamespace(scenario_count=scenarios)

    def drop_player(self, code: int) -> None:
        self._frame = self._frame.drop(columns=[code])

    def week(self, gameweek: int) -> pd.DataFrame:
        return self._frame


def _two_member_standings() -> dict[int, Any]:
    from squadopt.application.league_views import MemberStanding

    return {
        101: MemberStanding(entry_id=101, team_name="Ada FC", manager_name="Ada A", rank=1),
        202: MemberStanding(entry_id=202, team_name="Bora FC", manager_name="Bora B", rank=2),
    }


def test_with_paths_every_mode_is_published_and_none_carries_a_probability(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """Four files per member, real league rivals, price tags only — no probability ships."""

    import json

    inputs, projection, rules = _world_context(world)
    squad = _legal_squad(world)
    other = list(squad)
    other[10], other[11] = 1017, 1018
    provider = _Provider(
        {101: _member_picks(world, 101, squad), 202: _member_picks(world, 202, other)}
    )
    report = build_league_views(
        provider,
        (
            EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),
            EntryRegistration(202, "member-b", "2026-08-23T00:00:00Z"),
        ),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=tmp_path / "league",
        standings=_two_member_standings(),
        scored_gameweek=1,
        mode_paths=_WorldPaths(projection, 2),  # type: ignore[arg-type]
        rival_menu=False,
    )
    assert report.rendered_count == 2
    published = sorted(
        path.relative_to(tmp_path / "league").as_posix()
        for path in (tmp_path / "league" / "advice").rglob("*.json")
    )
    modes = ("agresif", "asiri-agresif", "garantici", "saf-puan")
    assert published == [f"advice/{entry}/{mode}/1.json" for entry in (101, 202) for mode in modes]
    for entry_id, rival_name in ((101, "Bora FC"), (202, "Ada FC")):
        for mode in modes:
            raw = (tmp_path / "league" / "advice" / str(entry_id) / mode / "1.json").read_text(
                encoding="utf-8"
            )
            assert "probability" not in raw.lower(), "no probability may ever be published"
            payload = json.loads(raw)["payload"]
            assert payload["mode"] == mode
            assert payload["window"] == 1
            if mode == "saf-puan":
                assert payload["expected_points_cost"] == 0.0
                assert payload["rival_label"] is None
            else:
                assert payload["expected_points_cost"] >= 0.0
                assert payload["rival_label"] == rival_name


def test_the_baseline_advice_is_byte_identical_with_and_without_paths(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """The saf-puan file is the deterministic planner's answer, never a scenario re-pick."""

    import datetime

    inputs, projection, rules = _world_context(world)
    squad = _legal_squad(world)
    when = datetime.datetime(2026, 8, 23, 12, 0, tzinfo=datetime.UTC)
    registrations = (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),)
    for out_name, paths in (("plain", None), ("modes", _WorldPaths(projection, 2))):
        build_league_views(
            _Provider({101: _member_picks(world, 101, squad)}),
            registrations,
            inputs,
            projection,
            rules,
            league_id=352490,
            league_name="Test League",
            out_dir=tmp_path / out_name,
            now=when,
            mode_paths=paths,  # type: ignore[arg-type]
        )
    first = (tmp_path / "plain" / "advice" / "101" / "saf-puan" / "1.json").read_bytes()
    second = (tmp_path / "modes" / "advice" / "101" / "saf-puan" / "1.json").read_bytes()
    assert first == second


# A member whose plan is a *choice*, unlike the shared ``_legal_squad`` fifteen: club-legal
# (at most three per club), holding the world's one high scorer so the captain is settled
# either way, and holding nobody the projection has ruled out. Every transfer it makes is
# therefore discretionary, which is what makes the caution margin able to decide anything.
DISCRETIONARY_SQUAD = (
    1001, 1002,                    # GK   Club 1, Club 2
    1004, 1006, 1007, 1008, 1009,  # DEF  Club 1, 3, 4, 5, 6
    1012, 1013, 1014, 1015, 1016,  # MID  Club 1, 2, 3, 4, 5
    1022, 1023, 1024,              # FWD  Club 3, 4, 5
)  # fmt: skip
# Two upgrades priced onto this world so one straddles the caution margin: 1017 at 8.0
# replaces the held 1014 (2.0) for a gain of 6.0, and 1019 at 7.0 replaces the held 1015
# (2.5) for 4.5. Both stay under 1024's 9.0, so 1024 is captain in every plan and each gain
# is the plain points difference rather than a captaincy swing. The member has one free
# transfer, so the first upgrade is free and the second is the one the margin prices.
DISCRETIONARY_UPGRADES = ((1017, 8.0), (1019, 7.0))


def _discretionary_projection(projection: Any) -> Any:
    """The world's projection with ``DISCRETIONARY_UPGRADES`` applied."""

    table = projection.table.copy(deep=True)
    for player_id, points in DISCRETIONARY_UPGRADES:
        table.loc[table["player_id"] == player_id, "expected_points"] = points
    return dataclasses.replace(projection, table=table)


def _publish_member_advice(
    world: dict[str, Any],
    tmp_path: Path,
    *,
    name: str,
    squad: Sequence[int],
    projection: Any,
    inputs: Any,
    rules: Any,
) -> bytes:
    """Publish one member's ``saf-puan`` advice and return the file's bytes."""

    import datetime

    build_league_views(
        _Provider({101: _member_picks(world, 101, list(squad))}),
        (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=tmp_path / name,
        now=datetime.datetime(2026, 8, 23, 12, 0, tzinfo=datetime.UTC),
    )
    return (tmp_path / name / "advice" / "101" / "saf-puan" / "1.json").read_bytes()


def test_the_member_planning_hit_cost_reaches_the_published_bytes(
    world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Moving ``MEMBER_PLANNING_POLICY``'s caution margin changes what the member is told.

    This is the gate on the policy value, and it is stated as a difference rather than as
    a recorded literal so that it cannot quietly stop discriminating. The pair of values
    is the owner's 2026-09-07 decision itself, 4.0 -> 8.0: at 4.0 the planner buys the
    second upgrade and pays the game's four points for it, at 8.0 it declines and takes
    only the free one. The byte pin below cannot do this — its world forces both of its
    transfers — so without this test the policy could move, or be reverted by accident,
    with every published byte unchanged.
    """

    import hashlib

    inputs, projection, rules = _world_context(world)
    tuned = _discretionary_projection(projection)
    published: dict[float, bytes] = {}
    for margin in (4.0, 8.0):
        values = dict(live_transfers._MEMBER_PLANNING_POLICY_VALUES)
        values["transfer_hit_cost_points"] = margin
        monkeypatch.setattr(live_transfers, "_MEMBER_PLANNING_POLICY_VALUES", values)
        published[margin] = _publish_member_advice(
            world,
            tmp_path,
            name=f"margin-{margin}",
            squad=DISCRETIONARY_SQUAD,
            projection=tuned,
            inputs=inputs,
            rules=rules,
        )

    assert published[4.0] != published[8.0], (
        "the published advice must respond to MEMBER_PLANNING_POLICY's caution margin; "
        f"both margins published {hashlib.sha256(published[4.0]).hexdigest()}"
    )
    at_four = json.loads(published[4.0])["payload"]
    at_eight = json.loads(published[8.0])["payload"]
    # 4.0 is below the second upgrade's 4.5 gain, so the planner buys it and is charged.
    assert [
        (move["player_out"]["player_id"], move["player_in"]["player_id"])
        for move in at_four["moves"]
    ] == [(1014, 1017), (1015, 1019)]
    assert at_four["transfer_hit_points"] == 4.0
    # 8.0 is above it, so only the free transfer is made and nothing is charged.
    assert [
        (move["player_out"]["player_id"], move["player_in"]["player_id"])
        for move in at_eight["moves"]
    ] == [(1014, 1017)]
    assert at_eight["transfer_hit_points"] == 0.0
    # The captain is the same in both, so the difference is the margin and nothing else.
    assert at_four["captain"]["player_id"] == at_eight["captain"]["player_id"] == 1024


# The in-season member plan this world produces, recorded so that a change to the member
# advice path has to declare itself. Every other test in this file compares two runs of
# the same commit, which passes even if every number moved; these literals are the only
# thing here that would notice. The planner itself has the GW1 opening pin
# (test_live_recommendation.py); this is the same gate for the in-season member path,
# which that pin never exercised: a held squad, sell prices, and a transfer decision.
#
# What these bytes do *not* gate is MEMBER_PLANNING_POLICY. This world's held fifteen is
# illegal under the game's three-per-club rule (four from Club 1 and four from Club 2), so
# the planner is repairing squad legality rather than weighing a transfer, and both moves
# are forced: the caution margin was measured to move the solve's objective from 42.85 at
# 4.0 to -353.15 at 400.0 while the published bytes never changed. The gate on the policy
# value is ``test_the_member_planning_hit_cost_reaches_the_published_bytes`` above, which
# holds a discretionary member; the value itself is pinned in
# ``tests/unit/test_live_transfers.py``.
IN_SEASON_MEMBER_ADVICE_SHA256 = "5f197ac047d670817571365b37405eac1002099aab516a288dd68a845c466dad"
# (player_out, player_in, expected_points_delta) per move, each pair one position. The
# week's hit charge is not here because it is not a property of a move: this plan makes
# two transfers and pays for one, and the payload states that once as
# ``transfer_hit_points``. It is the game's 4, although the plan was solved under
# MEMBER_PLANNING_POLICY's caution margin of 8: the margin decides what to do, the
# charge is what the member is told, and only the second reaches these bytes.
IN_SEASON_MEMBER_MOVES = (
    (1005, 1009, 2.5),
    (1020, 1024, 7.0),
)
IN_SEASON_MEMBER_TRANSFER_HIT_POINTS = 4.0


def test_the_recorded_in_season_member_plan_holds(world: dict[str, Any], tmp_path: Path) -> None:
    """Rebuilding member 101's advice reproduces the plan recorded here, byte for byte.

    This is the member path's replay gate. A pull request changing what this world's
    member is told — the planner, the projection reading, the advice payload, its JSON
    rendering — fails here and must say so in the pull request, updating these literals
    in the same commit. The refactor that moves this path behind a service boundary must
    keep the hash identical, which is the point of pinning bytes rather than fields.

    If these literals do not reproduce on another machine at the same commit, that is a
    determinism defect worth reporting rather than a test to loosen.
    """

    import hashlib

    inputs, projection, rules = _world_context(world)
    squad = _legal_squad(world)
    when = __import__("datetime").datetime(2026, 8, 23, 12, 0, tzinfo=__import__("datetime").UTC)
    build_league_views(
        _Provider({101: _member_picks(world, 101, squad)}),
        (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=tmp_path / "pin",
        now=when,
    )
    raw = (tmp_path / "pin" / "advice" / "101" / "saf-puan" / "1.json").read_bytes()
    payload = json.loads(raw)["payload"]
    # The readable literals first, so a failure names the move that changed rather than
    # only reporting a hash mismatch.
    assert (
        tuple(
            (
                move["player_out"]["player_id"],
                move["player_in"]["player_id"],
                move["expected_points_delta"],
            )
            for move in payload["moves"]
        )
        == IN_SEASON_MEMBER_MOVES
    )
    # Every published row is a swap the game would accept, and the week's charge is
    # stated once rather than repeated onto each of the two rows.
    for move in payload["moves"]:
        assert move["player_out"]["position"] == move["player_in"]["position"]
    assert payload["transfer_hit_points"] == IN_SEASON_MEMBER_TRANSFER_HIT_POINTS
    assert payload["mode"] == "saf-puan"
    assert payload["window"] == 1
    assert payload["expected_points_cost"] == 0.0
    assert payload["source_snapshot_id"] == world["gw2_id"]
    assert hashlib.sha256(raw).hexdigest() == IN_SEASON_MEMBER_ADVICE_SHA256


def test_a_window_the_calendar_cannot_reach_is_recorded_not_dropped(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """This world publishes three gameweeks, so no three- or five-week window exists
    from its GW2 deadline: the index says which windows solved (one), records each
    missing window with the horizon builder's own reason, and the one-week bytes are
    the same as without any builder — the replay pin above still holds."""

    import datetime

    from squadopt.application.advice import member_horizon_builder

    inputs, projection, rules = _world_context(world)
    snapshot = read_snapshot(world["snapshot_root"], world["gw2_id"])
    handoff = read_projection_handoff(world_module._handoff(world))
    builder = member_horizon_builder(snapshot, season=SEASON, in_season=handoff)
    squad = _legal_squad(world)
    when = datetime.datetime(2026, 8, 23, 12, 0, tzinfo=datetime.UTC)
    for name, horizon_builder in (("plain", None), ("windows", builder)):
        build_league_views(
            _Provider({101: _member_picks(world, 101, squad)}),
            (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),),
            inputs,
            projection,
            rules,
            league_id=352490,
            league_name="Test League",
            out_dir=tmp_path / name,
            now=when,
            horizon_builder=horizon_builder,
        )
    baseline = Path("advice") / "101" / "saf-puan" / "1.json"
    assert (tmp_path / "plain" / baseline).read_bytes() == (
        tmp_path / "windows" / baseline
    ).read_bytes()
    assert not (tmp_path / "windows" / "advice" / "101" / "saf-puan" / "3.json").exists()
    index = json.loads(
        (tmp_path / "windows" / "advice" / "101" / "index.json").read_text(encoding="utf-8")
    )["payload"]
    assert index["windows"] == {"saf-puan": [1], "ortak-koru": [1], "fark-yarat": [1]}
    missing = [entry for entry in index["unavailable"] if entry.get("window") is not None]
    assert [(entry["strategy"], entry["rival_entry_id"], entry["window"]) for entry in missing] == [
        ("saf-puan", None, 3),
        ("saf-puan", None, 5),
    ]
    for entry in missing:
        assert "absent from the captured season" in entry["reason"]


def test_without_a_rival_only_the_baseline_is_published(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """A lone member has no league neighbour, so competitive modes are absent, not faked."""

    inputs, projection, rules = _world_context(world)
    squad = _legal_squad(world)
    build_league_views(
        _Provider({101: _member_picks(world, 101, squad)}),
        (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=tmp_path / "league",
        mode_paths=_WorldPaths(projection, 2),  # type: ignore[arg-type]
        rival_menu=False,
    )
    published = sorted(
        path.relative_to(tmp_path / "league").as_posix()
        for path in (tmp_path / "league" / "advice").rglob("*.json")
    )
    assert published == ["advice/101/saf-puan/1.json"]


def test_a_member_whose_mode_scoring_fails_keeps_the_baseline(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """Paths missing a player the member holds break their modes, not their advice."""

    inputs, projection, rules = _world_context(world)
    squad = _legal_squad(world)
    other = list(squad)
    other[10], other[11] = 1017, 1018
    paths = _WorldPaths(projection, 2)
    paths.drop_player(squad[0])  # member 101's captain is not priced by the paths
    report = build_league_views(
        _Provider({101: _member_picks(world, 101, squad), 202: _member_picks(world, 202, other)}),
        (
            EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),
            EntryRegistration(202, "member-b", "2026-08-23T00:00:00Z"),
        ),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=tmp_path / "league",
        standings=_two_member_standings(),
        scored_gameweek=1,
        mode_paths=paths,  # type: ignore[arg-type]
    )
    assert report.rendered_count == 2
    failed = next(member for member in report.members if member.entry_id == 101)
    assert failed.rendered and "competitive modes unavailable" in failed.reason
    assert (tmp_path / "league" / "advice" / "101" / "saf-puan" / "1.json").is_file()
    assert not (tmp_path / "league" / "advice" / "101" / "garantici").exists()


def test_paths_for_the_wrong_gameweek_are_refused(world: dict[str, Any], tmp_path: Path) -> None:
    inputs, projection, rules = _world_context(world)
    squad = _legal_squad(world)
    with pytest.raises(ValueError, match="these views decide"):
        build_league_views(
            _Provider({101: _member_picks(world, 101, squad)}),
            (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),),
            inputs,
            projection,
            rules,
            league_id=352490,
            league_name="Test League",
            out_dir=tmp_path / "league",
            mode_paths=_WorldPaths(projection, 3),  # type: ignore[arg-type]
        )


# --- the rival menu --------------------------------------------------------------------


def _squad_b(world: dict[str, Any]) -> list[int]:
    # A second legal fifteen sharing few players with `_legal_squad`, so the overlap
    # bands bind rather than being satisfied for free.
    return [
        1001,
        1003,
        1004,
        1005,
        1006,
        1009,
        1010,
        1012,
        1013,
        1017,
        1018,
        1019,
        1020,
        1023,
        1024,
    ]


def _squad_c(world: dict[str, Any]) -> list[int]:
    return [
        1002,
        1003,
        1005,
        1007,
        1008,
        1010,
        1011,
        1013,
        1014,
        1016,
        1017,
        1019,
        1021,
        1022,
        1023,
    ]


def _three_member_league(world: dict[str, Any]) -> tuple[_Provider, tuple[EntryRegistration, ...]]:
    provider = _Provider(
        {
            101: _member_picks(world, 101, _legal_squad(world)),
            202: _member_picks(world, 202, _squad_b(world)),
            303: _member_picks(world, 303, _squad_c(world)),
        }
    )
    registrations = tuple(
        EntryRegistration(entry_id, f"member-{entry_id}", "2026-08-23T00:00:00Z")
        for entry_id in (101, 202, 303)
    )
    return provider, registrations


def _standings(*ranked: int) -> dict[int, MemberStanding]:
    return {
        entry_id: MemberStanding(
            entry_id=entry_id,
            team_name=f"Team {entry_id}",
            manager_name=f"Manager {entry_id}",
            rank=rank,
        )
        for rank, entry_id in enumerate(ranked, start=1)
    }


def test_the_rival_menu_is_published_per_strategy_and_rival(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """Every member gets every computable rival strategy against every other member,
    the standings neighbour's copy at the plain path, and an index that says so."""

    import datetime

    from squadopt.application.league_views import computable_rival_strategies

    inputs, projection, rules = _world_context(world)
    provider, registrations = _three_member_league(world)
    when = datetime.datetime(2026, 8, 23, 12, 0, tzinfo=datetime.UTC)
    report = build_league_views(
        provider,
        registrations,
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=tmp_path / "menu",
        standings=_standings(101, 202, 303),
        now=when,
    )
    strategies = computable_rival_strategies()
    assert strategies == ("ortak-koru", "fark-yarat")
    assert report.rendered_count == 3
    files = set(report.files)
    expected_defaults = {101: 202, 202: 101, 303: 202}  # leader defends; others chase
    unavailable_seen: list[tuple[int, str, int]] = []
    for entry_id in (101, 202, 303):
        others = [other for other in (101, 202, 303) if other != entry_id]
        assert f"advice/{entry_id}/saf-puan/1.json" in files
        assert f"advice/{entry_id}/index.json" in files
        index = json.loads(
            (tmp_path / "menu" / "advice" / str(entry_id) / "index.json").read_text(
                encoding="utf-8"
            )
        )["payload"]
        assert index["strategies"] == ["saf-puan", *strategies]
        assert index["rival_entry_ids"] == others
        assert index["default_rival_entry_id"] == expected_defaults[entry_id]
        assert index["window"] == 1
        computed = {(c["strategy"], c["rival_entry_id"]) for c in index["computed"]}
        unavailable = {(u["strategy"], u["rival_entry_id"]) for u in index["unavailable"]}
        # Every (strategy, rival) pair is accounted for exactly once: a file, or a reason.
        assert computed | unavailable == {(s, r) for s in strategies for r in others}
        assert not (computed & unavailable)
        for strategy, rival in computed:
            assert f"advice/{entry_id}/{strategy}/1/vs-{rival}.json" in files
        for entry in index["unavailable"]:
            assert entry["reason"]
            unavailable_seen.append((entry_id, entry["strategy"], entry["rival_entry_id"]))
            assert (
                f"advice/{entry_id}/{entry['strategy']}/1/vs-{entry['rival_entry_id']}.json"
                not in files
            )
        default = expected_defaults[entry_id]
        for strategy in strategies:
            plain_path = tmp_path / "menu" / "advice" / str(entry_id) / strategy / "1.json"
            chosen_path = (
                tmp_path / "menu" / "advice" / str(entry_id) / strategy / "1" / f"vs-{default}.json"
            )
            if (strategy, default) in computed:
                # The standings neighbour's copy at the plain path, byte for byte.
                assert plain_path.read_bytes() == chosen_path.read_bytes()
                payload = json.loads(chosen_path.read_bytes())["payload"]
                assert payload["rival_entry_id"] == default
                assert payload["mode"] == strategy
                assert payload["control_solver_status"] in {"OPTIMAL", "FEASIBLE"}
                assert isinstance(payload["captain"], dict)
            else:
                assert not plain_path.exists()
    # This world holds one pair no plan can satisfy — squad B cannot drop to five of
    # member 101's eleven within its budget — and it is a recorded reason, not a crash.
    assert unavailable_seen == [(202, "fark-yarat", 101)]


def test_the_menu_does_not_move_the_baseline_bytes(world: dict[str, Any], tmp_path: Path) -> None:
    import datetime

    inputs, projection, rules = _world_context(world)
    provider, registrations = _three_member_league(world)
    when = datetime.datetime(2026, 8, 23, 12, 0, tzinfo=datetime.UTC)
    for name, menu in (("plain", False), ("menu", True)):
        build_league_views(
            provider,
            registrations,
            inputs,
            projection,
            rules,
            league_id=352490,
            league_name="Test League",
            out_dir=tmp_path / name,
            standings=_standings(101, 202, 303),
            now=when,
            rival_menu=menu,
        )
    for entry_id in (101, 202, 303):
        first = (tmp_path / "plain" / "advice" / str(entry_id) / "saf-puan" / "1.json").read_bytes()
        second = (tmp_path / "menu" / "advice" / str(entry_id) / "saf-puan" / "1.json").read_bytes()
        assert first == second
    assert not (tmp_path / "plain" / "advice" / "101" / "index.json").exists()


def _standings_with_totals(totals: dict[int, int]) -> dict[int, MemberStanding]:
    return {
        entry_id: MemberStanding(
            entry_id=entry_id,
            team_name=f"Team {entry_id}",
            manager_name=f"Manager {entry_id}",
            rank=rank,
            total_points=total,
        )
        for rank, (entry_id, total) in enumerate(totals.items(), start=1)
    }


def test_the_index_carries_the_declared_rules_pick_with_the_inputs_it_read(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """The rule is a band on the gap, published with the gap and the weeks it read.

    Three members, three bands: the leader is far enough clear to be told to mirror, the
    chaser far enough behind to be told to differentiate, and the member level with their
    neighbour is left on pure points. Nothing is asserted about the rule being right —
    only that the index states which rule ran, on which two numbers.
    """

    import datetime

    from squadopt.application.strategies.rule import STRATEGY_RULE_ID, suggest_strategy

    inputs, projection, rules = _world_context(world)
    provider, registrations = _three_member_league(world)
    when = datetime.datetime(2026, 8, 23, 12, 0, tzinfo=datetime.UTC)
    build_league_views(
        provider,
        registrations,
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=tmp_path / "rule",
        standings=_standings_with_totals({101: 400, 202: 100, 303: 90}),
        scored_gameweek=1,
        now=when,
    )
    expected_rivals = {101: 202, 202: 101, 303: 202}
    expected_slugs = {101: "ortak-koru", 202: "fark-yarat", 303: "saf-puan"}
    totals = {101: 400, 202: 100, 303: 90}
    for entry_id, rival_id in expected_rivals.items():
        index = json.loads(
            (tmp_path / "rule" / "advice" / str(entry_id) / "index.json").read_text(
                encoding="utf-8"
            )
        )["payload"]
        suggested = index["suggested_strategy"]
        assert (
            suggested
            == suggest_strategy(
                rival_entry_id=rival_id,
                points_ahead_of_rival=totals[entry_id] - totals[rival_id],
                gameweek=2,
                scored_gameweek=1,
            ).to_dict()
        )
        assert suggested["strategy"] == expected_slugs[entry_id]
        assert suggested["rule_id"] == STRATEGY_RULE_ID
        assert suggested["strategy"] in index["strategies"]
        # The two inputs a reader needs to re-apply the rule, and the edge they met.
        assert suggested["points_ahead_of_rival"] == totals[entry_id] - totals[rival_id]
        assert suggested["gameweeks_remaining"] == 37
        assert suggested["band_edge_points"] > 0


def test_the_rules_pick_is_absent_when_the_totals_are_not_proven(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """No standings totals, no gap, no suggestion — an absent field, never a guessed one."""

    import datetime

    inputs, projection, rules = _world_context(world)
    provider, registrations = _three_member_league(world)
    when = datetime.datetime(2026, 8, 23, 12, 0, tzinfo=datetime.UTC)
    build_league_views(
        provider,
        registrations,
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=tmp_path / "silent",
        standings=_standings(101, 202, 303),
        now=when,
    )
    for entry_id in (101, 202, 303):
        index = json.loads(
            (tmp_path / "silent" / "advice" / str(entry_id) / "index.json").read_text(
                encoding="utf-8"
            )
        )["payload"]
        assert index["suggested_strategy"] is None


def test_the_rules_pick_does_not_move_a_single_advice_file(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """The rule points at one of the member's files; it never enters one.

    Every advice document is still computed from that member's own squad, so the whole
    advice tree is byte-identical whether or not the standings prove a gap to read.
    """

    import datetime

    inputs, projection, rules = _world_context(world)
    provider, registrations = _three_member_league(world)
    when = datetime.datetime(2026, 8, 23, 12, 0, tzinfo=datetime.UTC)
    for name, kwargs in (
        ("without", {"standings": _standings(101, 202, 303)}),
        (
            "with",
            {
                "standings": _standings_with_totals({101: 400, 202: 100, 303: 90}),
                "scored_gameweek": 1,
            },
        ),
    ):
        build_league_views(
            provider,
            registrations,
            inputs,
            projection,
            rules,
            league_id=352490,
            league_name="Test League",
            out_dir=tmp_path / name,
            now=when,
            **kwargs,  # type: ignore[arg-type]
        )
    advice_files = sorted(
        path.relative_to(tmp_path / "without")
        for path in (tmp_path / "without" / "advice").rglob("*.json")
        if path.name != "index.json"
    )
    assert advice_files
    for relative in advice_files:
        assert (tmp_path / "without" / relative).read_bytes() == (
            tmp_path / "with" / relative
        ).read_bytes()


def test_a_rival_that_cannot_be_priced_is_recorded_not_fatal(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """A rival whose players the projection lacks is unavailable with its reason; the
    member's baseline and the rest of the menu render, and the batch does not sink."""

    import dataclasses
    import datetime

    inputs, projection, rules = _world_context(world)
    provider, registrations = _three_member_league(world)
    # 1003 is in squads B and C but not in member 101's fifteen.
    incomplete = dataclasses.replace(
        projection,
        table=projection.table.loc[projection.table["player_id"] != 1003].reset_index(drop=True),
    )
    when = datetime.datetime(2026, 8, 23, 12, 0, tzinfo=datetime.UTC)
    report = build_league_views(
        provider,
        registrations,
        inputs,
        incomplete,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=tmp_path / "gap",
        standings=_standings(101, 202, 303),
        now=when,
    )
    by_id = {member.entry_id: member for member in report.members}
    assert by_id[101].rendered
    assert not by_id[202].rendered and not by_id[303].rendered
    index = json.loads(
        (tmp_path / "gap" / "advice" / "101" / "index.json").read_text(encoding="utf-8")
    )["payload"]
    assert index["computed"] == []
    assert len(index["unavailable"]) == 4
    assert all("missing" in entry["reason"] for entry in index["unavailable"])
    assert {entry["rival_entry_id"] for entry in index["unavailable"]} == {202, 303}
    assert not (tmp_path / "gap" / "advice" / "101" / "fark-yarat").exists()


def test_the_mapper_is_only_a_scheduler(world: dict[str, Any], tmp_path: Path) -> None:
    """A pool's map and the built-in map produce the same tree, byte for byte."""

    import datetime
    from concurrent.futures import ThreadPoolExecutor

    inputs, projection, rules = _world_context(world)
    provider, registrations = _three_member_league(world)
    when = datetime.datetime(2026, 8, 23, 12, 0, tzinfo=datetime.UTC)
    seen: list[int] = []

    def counting_map(function: Any, tasks: Any) -> Any:
        items = list(tasks)
        seen.extend(task.entry_id for task in items)
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(function, items))

    reports = []
    for name, mapper in (("serial", map), ("pool", counting_map)):
        reports.append(
            build_league_views(
                provider,
                registrations,
                inputs,
                projection,
                rules,
                league_id=352490,
                league_name="Test League",
                out_dir=tmp_path / name,
                standings=_standings(101, 202, 303),
                now=when,
                mapper=mapper,
            )
        )
    assert seen == [101, 202, 303]
    assert reports[0].files == reports[1].files
    for relative in reports[0].files:
        assert (tmp_path / "serial" / relative).read_bytes() == (
            tmp_path / "pool" / relative
        ).read_bytes()


def test_an_unknown_rival_strategy_is_refused(world: dict[str, Any], tmp_path: Path) -> None:
    inputs, projection, rules = _world_context(world)
    provider, registrations = _three_member_league(world)
    with pytest.raises(ValueError, match="not computable"):
        build_league_views(
            provider,
            registrations,
            inputs,
            projection,
            rules,
            league_id=352490,
            league_name="Test League",
            out_dir=tmp_path / "bad",
            rival_strategies=("kaptan-ayris",),
        )


# --- a publish is this week's whole picture, not an overlay on last week's --------------


def test_a_member_who_fails_to_render_does_not_keep_last_weeks_documents(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """The live surface defect: last week's advice served as this week's.

    ``publish_gameweek_site`` builds into a worktree checked out of ``origin/develop``, which
    carries the previous publish's tree, and commits ``git add web/public/data`` — the union.
    Nothing here removed anything, so a member whose picks could not be read kept last
    week's ``entries/{id}.json`` and ``advice/{id}/**`` while ``members.json`` was rewritten
    to this gameweek. Their row still linked, and the page rendered a finished gameweek's
    transfer recommendation under the current week's league.

    The publish is not refused over it: one member's data gap must not withhold the other
    members' advice, which is this module's stated rule. The absence is made honest instead —
    the row already says ``data_quality`` "empty", and now the document is genuinely not
    there rather than stale.
    """

    inputs, projection, rules = _world_context(world)
    squad = _legal_squad(world)
    out = tmp_path / "league"
    registrations = (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),)
    build_league_views(
        _Provider({101: _member_picks(world, 101, squad)}),
        registrations,
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=out,
    )
    assert (out / "entries" / "101.json").is_file()
    assert (out / "advice" / "101" / "saf-puan" / "1.json").is_file()

    # The next week's publish, into the tree the last one left, with this member's picks
    # no longer readable from the capture.
    report = build_league_views(
        _Provider({}),
        registrations,
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=out,
    )

    assert report.rendered_count == 0
    assert not (out / "entries" / "101.json").exists(), "last week's squad is still served"
    assert not (out / "advice" / "101" / "saf-puan").exists(), "last week's advice is still served"
    # What remains is the index that names why there is no advice, and nothing beside it.
    assert sorted(path.name for path in (out / "advice" / "101").iterdir()) == ["index.json"]
    assert report.removed == ("entries/101.json", "advice/101/saf-puan/")
    # The members list is still published, and still names the member as empty rather than
    # dropping them: absent advice is not an absent member.
    members = json.loads((out / "members.json").read_text(encoding="utf-8"))["payload"]["members"]
    assert [row["entry_id"] for row in members] == [101]
    assert members[0]["data_quality"] == "empty"


def test_a_rendered_member_keeps_every_document_the_run_wrote(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """The pruning may only reach documents this run did not produce."""

    inputs, projection, rules = _world_context(world)
    out = tmp_path / "league"
    picks = _Provider({101: _member_picks(world, 101, _legal_squad(world))})
    registrations = (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),)
    for _ in range(2):
        report = build_league_views(
            picks,
            registrations,
            inputs,
            projection,
            rules,
            league_id=352490,
            league_name="Test League",
            out_dir=out,
        )

    assert report.removed == ()
    assert (out / "entries" / "101.json").is_file()
    assert (out / "advice" / "101" / "saf-puan" / "1.json").is_file()


def test_files_the_rule_does_not_understand_are_left_alone(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """``scoreboard.json`` is written into this same directory by a different script, after
    this one runs. A rule that deletes what it did not anticipate is a worse failure than
    the one it fixes, so only entry-shaped names are touched."""

    inputs, projection, rules = _world_context(world)
    out = tmp_path / "league"
    (out / "entries").mkdir(parents=True)
    (out / "scoreboard.json").write_text("{}", encoding="utf-8")
    (out / "entries" / "README.json").write_text("{}", encoding="utf-8")

    build_league_views(
        _Provider({101: _member_picks(world, 101, _legal_squad(world))}),
        (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=out,
    )

    assert (out / "scoreboard.json").is_file()
    assert (out / "entries" / "README.json").is_file()
