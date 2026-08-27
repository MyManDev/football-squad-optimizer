"""The league views builder: member advice from the seam, independence pinned as fact."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest
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
    # The unknown flags travel to the entry page too, not just to the advice.
    assert payload["free_transfers_known"] is False
    assert "free_transfers" in payload["missing_fields"]
    # No score comparison is claimed while the standings view carries no points.
    assert payload["squadopt_comparison"] is None


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


# The in-season member plan this world produces, recorded so that a change to the member
# advice path has to declare itself. Every other test in this file compares two runs of
# the same commit, which passes even if every number moved; these literals are the only
# thing here that would notice. The planner itself has the GW1 opening pin
# (test_live_recommendation.py); this is the same gate for the in-season member path,
# which that pin never exercised: a held squad, sell prices, and a transfer decision.
IN_SEASON_MEMBER_ADVICE_SHA256 = "e9482cf30166756feb0336856f37d92e22b6faeff0039a011d1ff0c0efb23b0a"
# (player_out, player_in, expected_points_delta, expected_points_cost) per move.
IN_SEASON_MEMBER_MOVES = (
    (1005, 1009, 2.5, 4.0),
    (1020, 1024, 7.0, 4.0),
)


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
                move["expected_points_cost"],
            )
            for move in payload["moves"]
        )
        == IN_SEASON_MEMBER_MOVES
    )
    assert payload["mode"] == "saf-puan"
    assert payload["window"] == 1
    assert payload["expected_points_cost"] == 0.0
    assert payload["source_snapshot_id"] == world["gw2_id"]
    assert hashlib.sha256(raw).hexdigest() == IN_SEASON_MEMBER_ADVICE_SHA256


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
