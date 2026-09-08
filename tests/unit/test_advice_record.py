"""The immutable advice record: written by the publish, complete enough to score, never
rewritten.

The published league tree carries no gameweek in its paths and is overwritten every week.
These tests pin the four things that makes the record worth having: it exists after a
publish, it does not move the published bytes, it refuses to change, and a later page can
score what it names without re-solving anything.
"""

import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import tests.unit.test_live_transfers as world_module

from squadopt.application.advice_record import (
    MEMBER_ADVICE_RECORD_CONTRACT_VERSION,
    RECORD_FILE,
    AdviceRecordConflictError,
    load_member_advice_record,
    record_directory,
)
from squadopt.application.entries import EntryError, EntryPicks, EntryRegistration
from squadopt.application.league_views import MemberStanding, build_league_views
from squadopt.data.snapshots import read_snapshot
from squadopt.live import read_inputs, read_season_rules
from squadopt.live.recommendation import project, read_projection_handoff

SEASON = world_module.SEASON
WHEN = datetime.datetime(2026, 8, 23, 12, 0, tzinfo=datetime.UTC)

world = world_module._world  # re-register the fixture in this module


class _Provider:
    """The #127 capture provider's seam, member state per entry id."""

    def __init__(self, picks_by_entry: dict[int, EntryPicks]) -> None:
        self._picks = picks_by_entry

    def picks(self, entry_id: int, season: str, gameweek: int) -> EntryPicks:
        if entry_id not in self._picks:
            raise EntryError(f"No picks captured for entry {entry_id}.")
        return self._picks[entry_id]


def _member_picks(
    world: dict[str, Any],
    entry_id: int,
    squad_codes: list[int],
    *,
    free_transfers: int = 1,
) -> EntryPicks:
    return EntryPicks(
        entry_id=entry_id,
        season=SEASON,
        gameweek=1,
        squad=tuple(squad_codes),
        starting_xi=tuple(squad_codes[:11]),
        captain=squad_codes[0],
        vice_captain=squad_codes[1],
        bank_tenths=5,
        free_transfers=free_transfers,
        free_transfers_known=free_transfers > 1,
        source_snapshot_id=world["gw2_id"],
    )


def _world_context(world: dict[str, Any]) -> tuple[Any, Any, Any]:
    snapshot = read_snapshot(world["snapshot_root"], world["gw2_id"])
    inputs = read_inputs(snapshot, season=SEASON, gameweek=2)
    handoff = read_projection_handoff(world_module._handoff(world))
    return inputs, project(inputs, in_season=handoff), read_season_rules(snapshot, season=SEASON)


def _legal_squad() -> list[int]:
    # The world is 3 GK / 8 DEF / 8 MID / 5 FWD, codes 1001..1024 in position blocks.
    return [
        *(1001, 1002),
        *(1004, 1005, 1006, 1007, 1008),
        *(1012, 1013, 1014, 1015, 1016),
        *(1020, 1021, 1022),
    ]


def _other_squad() -> list[int]:
    squad = _legal_squad()
    squad[10], squad[11] = 1017, 1018
    return squad


def _build(
    world: dict[str, Any],
    out_dir: Path,
    *,
    record_root: Path | None,
    free_transfers: int = 1,
    now: datetime.datetime = WHEN,
) -> None:
    inputs, projection, rules = _world_context(world)
    provider = _Provider(
        {
            101: _member_picks(world, 101, _legal_squad(), free_transfers=free_transfers),
            202: _member_picks(world, 202, _other_squad()),
        }
    )
    build_league_views(
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
        out_dir=out_dir,
        standings={
            101: MemberStanding(101, "A", "Manager A", 1, 40, 80),
            202: MemberStanding(202, "B", "Manager B", 2, 30, 70),
        },
        scored_gameweek=1,
        now=now,
        advice_record_root=record_root,
    )


def _digests(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*.json"))
    }


def test_the_publish_records_what_each_member_was_told(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """A publish leaves, beside the overwritable tree, one immutable record per member.

    The record is addressed by gameweek — which the published tree's paths are not — and
    every advice document in it carries the digest of the bytes that actually landed, so a
    later page can prove the record describes the files that were published rather than a
    re-rendering of them.
    """

    out = tmp_path / "site"
    records = tmp_path / "records"
    _build(world, out, record_root=records)

    directory = record_directory(records, SEASON, 2, 101)
    assert (directory / RECORD_FILE).is_file()
    assert (directory / "manifest.json").is_file()
    record = load_member_advice_record(records, SEASON, 2, 101)
    assert record["contract_version"] == MEMBER_ADVICE_RECORD_CONTRACT_VERSION
    assert record["gameweek"] == 2 and record["entry_id"] == 101
    assert record["player_id_space"] == "fpl_element_code"

    # Which document is the one the member's page points at, named rather than inferred.
    told = record["told"]
    assert isinstance(told, dict)
    assert told["published_path"] in {
        document["published_path"]
        for document in record["advice"]  # type: ignore[union-attr]
    }

    # Every recorded document is the file that was published, byte for byte.
    for document in record["advice"]:  # type: ignore[union-attr]
        published = out / document["published_path"]
        assert published.is_file()
        assert document["published_sha256"] == hashlib.sha256(published.read_bytes()).hexdigest()

    baseline = next(
        document
        for document in record["advice"]  # type: ignore[union-attr]
        if document["published_path"] == "advice/101/saf-puan/1.json"
    )
    published = (out / "advice/101/saf-puan/1.json").read_text(encoding="utf-8")
    payload = json.loads(published)["payload"]
    # The whole decision, not only the transfers: eleven, bench, armband, chip, hits.
    assert baseline["starting_xi"] == [p["player_id"] for p in payload["starting_xi"]]
    assert baseline["bench"] == [p["player_id"] for p in payload["bench"]]
    assert baseline["captain"] == payload["captain"]["player_id"]
    assert baseline["vice_captain"] == payload["vice_captain"]["player_id"]
    assert baseline["chip"] == payload["chip"]
    assert baseline["transfer_hit_points"] == payload["transfer_hit_points"]
    assert baseline["expected_own_points"] == payload["expected_own_points"]
    assert baseline["solver_status"] == payload["solver_status"]
    assert [(move["player_out"], move["player_in"]) for move in baseline["moves"]] == [
        (
            move["player_out"]["player_id"] if move["player_out"] else None,
            move["player_in"]["player_id"] if move["player_in"] else None,
        )
        for move in payload["moves"]
    ]

    # The state it was computed from, so "ignored our advice" and "could not afford it"
    # stay different answers.
    state = record["state"]
    assert isinstance(state, dict)
    assert state["picks_gameweek"] == 1
    assert state["held_squad"] == _legal_squad()
    assert state["bank_tenths"] == 5
    assert state["free_transfers"] == 1
    assert state["free_transfers_known"] is False
    assert state["purchase_prices_known"] is False
    # Unknown purchase prices are absent, not an empty map: the plan valued the squad at
    # current prices, and an empty map would read as "nothing was bought".
    assert state["purchase_prices"] is None
    assert state["chips_used"] == {}
    assert state["source_snapshot_id"] == world["gw2_id"]

    # What produced it.
    provenance = record["provenance"]
    assert isinstance(provenance, dict)
    assert provenance["model_version"] == world_module.IN_SEASON_VERSION
    assert provenance["feature_contract_version"]
    assert len(str(provenance["projection_handoff_fingerprint"])) == 64
    assert provenance["planner_policy_id"] == "member_planning_policy_v2"
    assert len(str(provenance["transfer_config_fingerprint"])) == 64
    assert record["league_view_contract_version"] == "provisional_league_ui_v1"


def test_writing_the_record_does_not_move_a_single_published_byte(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """The record is a second output, never a change to the first.

    Members read the published tree; nothing about recording what was published may alter
    what they are shown. Two builds of the same world, one recording and one not, are
    compared file by file rather than spot-checked.
    """

    without = tmp_path / "without"
    with_record = tmp_path / "with"
    _build(world, without, record_root=None)
    _build(world, with_record, record_root=tmp_path / "records")
    assert _digests(without) == _digests(with_record)
    assert _digests(without)  # the comparison is not vacuous


def test_republishing_the_identical_week_is_a_no_op(world: dict[str, Any], tmp_path: Path) -> None:
    """The same week deployed twice must not fail; there is nothing to disagree about.

    This has actually happened, so it is the ordinary case rather than a hypothetical one.
    """

    records = tmp_path / "records"
    _build(world, tmp_path / "first", record_root=records)
    landed = (record_directory(records, SEASON, 2, 101) / RECORD_FILE).read_bytes()

    _build(world, tmp_path / "second", record_root=records)
    assert (record_directory(records, SEASON, 2, 101) / RECORD_FILE).read_bytes() == landed


def test_a_republish_that_differs_is_refused_and_names_what_differed(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """Different bytes over a recorded week are refused, and the refusal is readable.

    A record that can be overwritten proves nothing about what was published, so the
    second publish loses rather than the first. The message names the fields that moved:
    a re-run at a different minute and a re-run that changed the advice are both refused,
    and an operator has to be able to tell them apart without diffing two files by hand.
    """

    records = tmp_path / "records"
    _build(world, tmp_path / "first", record_root=records)

    # Same advice, a later run: only the publication's own timestamp moved.
    later = WHEN + datetime.timedelta(hours=1)
    with pytest.raises(AdviceRecordConflictError) as clock:
        _build(world, tmp_path / "second", record_root=records, now=later)
    assert "generated_at_utc" in str(clock.value)
    assert "2026-08-23T12:00:00Z" in str(clock.value)
    assert "2026-08-23T13:00:00Z" in str(clock.value)

    # A second free transfer the source did publish: the state read changed, the week's
    # hit charge went with it, and the message names the input that moved and the
    # published document that moved with it.
    with pytest.raises(AdviceRecordConflictError) as changed:
        _build(world, tmp_path / "third", record_root=records, free_transfers=2)
    message = str(changed.value)
    assert "state.free_transfers: recorded 1, now 2" in message
    assert "state.free_transfers_known: recorded False, now True" in message
    assert "transfer_hit_points" in message
    assert "published_sha256" in message

    # Neither refusal rewrote anything.
    record = load_member_advice_record(records, SEASON, 2, 101)
    state = record["state"]
    assert isinstance(state, dict)
    assert state["free_transfers"] == 1 and state["free_transfers_known"] is False
    assert record["generated_at_utc"] == "2026-08-23T12:00:00Z"


def _multipliers(record: dict[str, Any], published_path: str) -> dict[int, int]:
    """The advised squad's multiplier per player, from the record and nothing else.

    Starters count once, the captain counts again, the bench counts nothing — unless a
    chip changes that: a bench boost counts the bench, a triple captain counts the captain
    a third time. This is the whole reason the record carries a lineup rather than only
    transfers, so it is exercised here as well as in the throwaway reconstruction script.
    """

    document = next(item for item in record["advice"] if item["published_path"] == published_path)
    chip = document["chip"]
    multipliers = {int(player): 1 for player in document["starting_xi"]}
    for player in document["bench"]:
        multipliers[int(player)] = 1 if chip == "bboost" else 0
    captain = int(document["captain"])
    multipliers[captain] += 2 if chip == "3xc" else 1
    return multipliers


def test_the_record_alone_reconstructs_the_advised_squads_multipliers(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """A later page can score what we advised without re-solving or re-reading anything.

    Every id the multipliers name resolves in the record's own player map, so the join
    onto realized points needs the record and the week's points and nothing else.
    """

    records = tmp_path / "records"
    _build(world, tmp_path / "site", record_root=records)
    record = load_member_advice_record(records, SEASON, 2, 101)
    told = record["told"]
    assert isinstance(told, dict)

    multipliers = _multipliers(dict(record), str(told["published_path"]))
    assert len(multipliers) == 15
    assert sorted(multipliers.values()) == [0, 0, 0, 0, *([1] * 10), 2]
    players = record["players"]
    assert isinstance(players, dict)
    for player in multipliers:
        assert str(player) in players
        assert players[str(player)]["position"] in {"GK", "DEF", "MID", "FWD"}
    # The bench's first player is the goalkeeper, which is the order the autosubs walk.
    document = next(
        item
        for item in record["advice"]  # type: ignore[union-attr]
        if item["published_path"] == told["published_path"]
    )
    assert players[str(document["bench"][0])]["position"] == "GK"
