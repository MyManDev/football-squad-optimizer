"""The league views builder: member advice from the seam, independence pinned as fact."""

from pathlib import Path
from typing import Any

import tests.unit.test_live_transfers as world_module

from squadopt.application.entries import EntryError, EntryPicks, EntryRegistration
from squadopt.application.league_views import build_league_views
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
        bank_tenths=5,
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
    # position blocks; a legal 2-5-5-3 fifteen with max three per club exists by
    # construction of the fixture data.
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
    assert (tmp_path / "league" / "advice-101.json").is_file()
    import json

    advice = json.loads((tmp_path / "league" / "advice-101.json").read_text(encoding="utf-8"))
    assert advice["contract_version"] == "provisional_league_ui_v1"
    assert advice["payload"]["mode"] == "saf_puan"
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
    first = (tmp_path / "one" / "advice-101.json").read_bytes()
    second = (tmp_path / "two" / "advice-101.json").read_bytes()
    assert first == second


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
