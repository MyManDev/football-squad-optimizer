"""The immutable advice record: written by the publish, complete enough to score, never
rewritten.

The published league tree carries no gameweek in its paths and is overwritten every week.
These tests pin the things that make the record worth having: it exists after a publish, it
does not move the published bytes, it refuses to change *within one capture*, a second
publish of the week from a fresher capture records its own, the reader can name the record
a member actually saw before the deadline, and a later page can score what it names without
re-solving anything.
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
    AdviceRecordError,
    entry_directory,
    load_member_advice_record,
    load_member_advice_record_for_deadline,
    record_directory,
    record_member_advice,
    recorded_captures,
)
from squadopt.application.entries import EntryError, EntryPicks, EntryRegistration
from squadopt.application.league_views import MemberStanding, build_league_views
from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.live import read_inputs, read_season_rules
from squadopt.live.recommendation import project, read_projection_handoff

SEASON = world_module.SEASON
WHEN = datetime.datetime(2026, 8, 23, 12, 0, tzinfo=datetime.UTC)
#: The world's GW2 deadline, as its bootstrap publishes it. Asserted against the capture's
#: own reading in the reader test, so the constant cannot drift away from the fixture.
GW2_DEADLINE = "2026-08-28T17:30:00Z"
#: A second capture of the same week, taken later and still before that deadline: the
#: publish that a member's last look at the site would have been reading.
LATER_CAPTURED_AT = "2026-08-28T09:00:00Z"

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
    capture: str | None = None,
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
        source_snapshot_id=capture or world["gw2_id"],
    )


def _world_context(world: dict[str, Any], capture: str | None = None) -> tuple[Any, Any, Any]:
    snapshot = read_snapshot(world["snapshot_root"], capture or world["gw2_id"])
    inputs = read_inputs(snapshot, season=SEASON, gameweek=2)
    handoff = read_projection_handoff(world_module._handoff(world, snapshot_id=capture))
    return inputs, project(inputs, in_season=handoff), read_season_rules(snapshot, season=SEASON)


def _later_capture(world: dict[str, Any]) -> str:
    """A second live capture of the same week, taken later and still before the deadline.

    This is the ordinary shape of a published week: something goes up mid-week so members
    see an answer, and a fresher capture is published shortly before the deadline. The
    payloads are copied rather than varied — what is under test is the key, and a capture is
    a different capture because it was taken at a different instant, not because a price
    moved.
    """

    snapshot = read_snapshot(world["snapshot_root"], world["gw2_id"])
    written = write_snapshot(
        world["snapshot_root"],
        source="fpl-live",
        captured_at_utc=LATER_CAPTURED_AT,
        payloads=dict(snapshot.payloads),
    )
    return str(written.snapshot_id)


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
    capture: str | None = None,
    totals: dict[int, int] | None = None,
) -> None:
    """Publish the two-member league, optionally with league totals the rule reads.

    The default totals sit ten points apart, which is inside the rule's band at this
    gameweek, so the rule names pure points. ``totals`` moves them far enough apart for
    the rule to name a *rival* strategy, which is the case the record has to describe
    without claiming the member's page followed it.
    """

    league_totals = totals or {101: 80, 202: 70}
    inputs, projection, rules = _world_context(world, capture)
    provider = _Provider(
        {
            101: _member_picks(
                world, 101, _legal_squad(), free_transfers=free_transfers, capture=capture
            ),
            202: _member_picks(world, 202, _other_squad(), capture=capture),
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
            101: MemberStanding(101, "A", "Manager A", 1, 40, league_totals[101]),
            202: MemberStanding(202, "B", "Manager B", 2, 30, league_totals[202]),
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

    directory = record_directory(records, SEASON, 2, 101, world["gw2_id"])
    assert (directory / RECORD_FILE).is_file()
    assert (directory / "manifest.json").is_file()
    record = load_member_advice_record(records, SEASON, 2, 101, world["gw2_id"])
    assert record["contract_version"] == MEMBER_ADVICE_RECORD_CONTRACT_VERSION
    assert record["gameweek"] == 2 and record["entry_id"] == 101
    assert record["player_id_space"] == "fpl_element_code"
    # The capture is in the document as well as in the path, so a record that has been
    # moved still says which publish it is.
    assert record["capture"] == {
        "snapshot_id": world["gw2_id"],
        "captured_at_utc": world_module.GW2_CAPTURED_AT,
    }

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


def test_the_record_names_the_document_the_page_shows_not_the_one_the_rule_picked(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """``told`` describes the page, so it may only say what the page actually does.

    The member's page selects its strategy from the URL and falls back to pure points;
    the link from the members table carries no query string, so a member arriving from the
    league table sees the ``saf-puan`` card whatever the rule named. The rule's pick is a
    badge on an option the member may ignore — the web pins that deliberately — so a record
    that pointed ``told`` at the rule's file would name a squad nobody was shown, forever
    and un-rewritably. The two facts are recorded as two facts instead.
    """

    records = tmp_path / "records"
    out = tmp_path / "site"
    # Three hundred points apart: outside the rule's band, so it names a rival strategy
    # for both members rather than pure points.
    _build(world, out, record_root=records, totals={101: 400, 202: 100})

    # The leader's rule pick solved against their neighbour; the chaser's did not, which
    # this world reports rather than hides. Both members are shown the same baseline.
    for entry_id, slug in ((101, "ortak-koru"), (202, "fark-yarat")):
        record = load_member_advice_record(records, SEASON, 2, entry_id, world["gw2_id"])
        told = record["told"]
        assert isinstance(told, dict)
        # What the page shows a member who followed the members-table link: the baseline.
        assert told["published_path"] == f"advice/{entry_id}/saf-puan/1.json"
        assert told["strategy"] == "saf-puan"
        assert told["window"] == 1
        assert told["rival_entry_id"] is None
        assert told["source"] == "default_view"
        assert told["published_path"] in {
            document["published_path"]
            for document in record["advice"]  # type: ignore[union-attr]
        }
        # The record and the index the page reads agree about which strategy the rule named.
        index = json.loads(
            (out / "advice" / str(entry_id) / "index.json").read_text(encoding="utf-8")
        )["payload"]
        assert index["suggested_strategy"]["strategy"] == slug

    # The rule's pick beside it, named as a suggestion rather than as what was shown.
    leader = load_member_advice_record(records, SEASON, 2, 101, world["gw2_id"])
    leader_told = leader["told"]
    assert isinstance(leader_told, dict)
    suggested = leader_told["suggested"]
    assert isinstance(suggested, dict)
    assert suggested["strategy"] == "ortak-koru"
    assert suggested["rival_entry_id"] == 202
    assert suggested["published_path"] == "advice/101/ortak-koru/1.json"
    assert suggested["published_path"] != leader_told["published_path"]
    assert suggested["published_path"] in {
        document["published_path"]
        for document in leader["advice"]  # type: ignore[union-attr]
    }

    # The chaser's rule pick had no provable plan against their neighbour, so no file was
    # written for it: the record names no suggestion rather than an address nobody wrote.
    chaser = load_member_advice_record(records, SEASON, 2, 202, world["gw2_id"])
    chaser_told = chaser["told"]
    assert isinstance(chaser_told, dict)
    assert chaser_told["suggested"] is None
    assert not (out / "advice" / "202" / "fark-yarat" / "1.json").exists()


def test_a_multi_week_record_keeps_the_whole_plan_it_advised(world: dict[str, Any]) -> None:
    """A window document's advice is the plan, so the record keeps every week of it.

    The published tree is overwritten next week and the later weeks of a plan exist
    nowhere else, so a record that kept only the decided week would lose them for good —
    and the players named only in a later week would be in neither the record's player map
    nor its list of ids it could not resolve. A document that carries no plan for the
    weeks it covers is not scoring-complete and no longer says it is.
    """

    from squadopt.application.advice_record import PublishedAdvice, RecordCapture
    from squadopt.application.advice_record import build_member_advice_record as build_record

    _inputs, projection, _rules = _world_context(world)
    picks = _member_picks(world, 101, _legal_squad())
    one_week = {
        "season": SEASON,
        "gameweek": 2,
        "entry_id": 101,
        "mode": "saf-puan",
        "window": 1,
        "starting_xi": [{"player_id": player} for player in _legal_squad()[:11]],
        "bench": [{"player_id": player} for player in _legal_squad()[11:]],
        "captain": {"player_id": 1012},
        "vice_captain": {"player_id": 1013},
        "chip": None,
        "moves": [],
        "transfer_hit_points": 0.0,
        "expected_own_points": 50.0,
        "solver_status": "OPTIMAL",
        "optimality_gap": None,
    }
    # Week three swaps in a defender the squad never held and a player the projection has
    # no row for; week four swaps a midfielder. None of the three is named anywhere else.
    later_weeks = [
        {
            "gameweek": 2,
            "transfers_in": [],
            "transfers_out": [],
            "transfer_hit_points": 0.0,
            "chip": None,
            "free_transfers_before": 1,
            "free_transfers_after": 1,
            "expected_points": 50.0,
        },
        {
            "gameweek": 3,
            "transfers_in": [{"player_id": 1009, "name": "Nine"}],
            "transfers_out": [{"player_id": 1008, "name": "Eight"}],
            "transfer_hit_points": 4.0,
            "chip": None,
            "free_transfers_before": 1,
            "free_transfers_after": 0,
            "expected_points": 48.0,
        },
        {
            "gameweek": 4,
            "transfers_in": [{"player_id": 1017, "name": "Seventeen"}],
            "transfers_out": [{"player_id": 9999, "name": "Stranger"}],
            "transfer_hit_points": 0.0,
            "chip": None,
            "free_transfers_before": 1,
            "free_transfers_after": 1,
            "expected_points": 47.0,
        },
    ]
    limits = ["Prices are held at the captured values; no price change is modelled."]
    window_payload: dict[str, Any] = {
        **one_week,
        "window": 3,
        "plan_weeks": later_weeks,
        "stated_limits": limits,
    }

    def _published(payload: dict[str, Any], window: int) -> PublishedAdvice:
        relative = f"advice/101/saf-puan/{window}.json"
        raw = json.dumps(payload, sort_keys=True).encode("utf-8")
        return PublishedAdvice("saf-puan", window, None, relative, payload, raw)

    record = build_record(
        picks,
        projection,
        [_published(one_week, 1), _published(window_payload, 3)],
        capture=RecordCapture(world["gw2_id"], world_module.GW2_CAPTURED_AT),
        league_id=352490,
        generated_at_utc="2026-08-23T12:00:00Z",
        league_view_contract_version="provisional_league_ui_v1",
    )
    documents = {int(item["window"]): item for item in record["advice"]}  # type: ignore[index,union-attr]

    # A one-week document has no plan beyond its own week, and says so by absence.
    assert "plan_weeks" not in documents[1]
    assert documents[1]["scoring_complete"] is True

    # The window document keeps every week it advised, reduced to ids the way moves are.
    assert documents[3]["plan_weeks"] == [
        {
            "gameweek": week["gameweek"],
            "transfers_in": [player["player_id"] for player in week["transfers_in"]],
            "transfers_out": [player["player_id"] for player in week["transfers_out"]],
            "transfer_hit_points": week["transfer_hit_points"],
            "chip": week["chip"],
            "free_transfers_before": week["free_transfers_before"],
            "free_transfers_after": week["free_transfers_after"],
            "expected_points": week["expected_points"],
        }
        for week in later_weeks
    ]
    assert documents[3]["stated_limits"] == limits
    assert documents[3]["scoring_complete"] is True

    # Players named only in a later week are joinable, and the one the projection has no
    # row for is listed as unresolved rather than silently dropped from both.
    players = record["players"]
    assert isinstance(players, dict)
    assert {"1009", "1017"} <= set(players)
    assert 9999 in record["unresolved_player_ids"]  # type: ignore[operator]

    # A window document with no plan is not scoring-complete, whatever its eleven says.
    without_plan = build_record(
        picks,
        projection,
        [_published({**one_week, "window": 3}, 3)],
        capture=RecordCapture(world["gw2_id"], world_module.GW2_CAPTURED_AT),
        league_id=352490,
        generated_at_utc="2026-08-23T12:00:00Z",
        league_view_contract_version="provisional_league_ui_v1",
    )
    assert without_plan["advice"][0]["scoring_complete"] is False  # type: ignore[index]


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


def test_rebuilding_the_identical_capture_is_a_no_op(world: dict[str, Any], tmp_path: Path) -> None:
    """The same capture built twice must not fail; there is nothing to disagree about.

    This has actually happened, so it is the ordinary case rather than a hypothetical one.
    A no-op is also not a second record: the capture directory is written once and the
    rebuild leaves the week holding exactly one.
    """

    records = tmp_path / "records"
    _build(world, tmp_path / "first", record_root=records)
    directory = record_directory(records, SEASON, 2, 101, world["gw2_id"])
    landed = (directory / RECORD_FILE).read_bytes()

    _build(world, tmp_path / "second", record_root=records)
    assert (directory / RECORD_FILE).read_bytes() == landed
    week = entry_directory(records, SEASON, 2, 101)
    assert [child.name for child in sorted(week.iterdir()) if child.is_dir()] == [world["gw2_id"]]


def test_two_publishes_of_one_week_from_two_captures_each_keep_their_record(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """A week is published more than once, and the second publish must not be refused.

    Mid-week so members see something, then again with fresh availability shortly before
    the deadline: under a key of season, gameweek and entry alone the first publish won and
    the second was refused as a rewrite, so the advice that actually stood at the deadline —
    the advice a member acted on — never reached the record. Each capture writes its own.
    """

    records = tmp_path / "records"
    _build(world, tmp_path / "midweek", record_root=records)
    later = _later_capture(world)
    _build(world, tmp_path / "deadline", record_root=records, capture=later)

    week = entry_directory(records, SEASON, 2, 101)
    assert sorted(child.name for child in week.iterdir() if child.is_dir()) == sorted(
        [world["gw2_id"], later]
    )
    for capture in (world["gw2_id"], later):
        record = load_member_advice_record(records, SEASON, 2, 101, capture)
        assert record["capture"] == {  # type: ignore[comparison-overlap]
            "snapshot_id": capture,
            "captured_at_utc": (
                world_module.GW2_CAPTURED_AT if capture == world["gw2_id"] else LATER_CAPTURED_AT
            ),
        }
        assert record["state"]["source_snapshot_id"] == capture  # type: ignore[index]


def test_the_record_for_a_deadline_is_the_last_capture_that_preceded_it(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """The review page's question, answered from the records and a deadline alone.

    Its whole claim is "this is what we told you", so the record that counts is the last one
    a member could still have acted on. When none qualifies the reader says so rather than
    handing back the nearest later record, and it keeps "no record at all" apart from
    "records, but all of them built after the deadline".
    """

    records = tmp_path / "records"
    _build(world, tmp_path / "midweek", record_root=records)
    later = _later_capture(world)
    _build(world, tmp_path / "deadline", record_root=records, capture=later)

    inputs, _, _ = _world_context(world)
    assert inputs.deadline.deadline_utc == GW2_DEADLINE

    # Oldest capture first, ordered by the capture instant rather than by the filesystem.
    assert [capture.snapshot_id for capture in recorded_captures(records, SEASON, 2, 101)] == [
        world["gw2_id"],
        later,
    ]
    record = load_member_advice_record_for_deadline(
        records, SEASON, 2, 101, deadline_utc=GW2_DEADLINE
    )
    assert record["capture"]["snapshot_id"] == later  # type: ignore[index]

    # Asked for an earlier deadline, both records follow it: the nearest one is not offered
    # in its place, and the refusal says how many there are and how early the earliest is.
    with pytest.raises(AdviceRecordError) as after:
        load_member_advice_record_for_deadline(
            records, SEASON, 2, 101, deadline_utc="2026-08-21T17:30:00Z"
        )
    assert "2 advice record(s)" in str(after.value)
    assert "at or after the deadline 2026-08-21T17:30:00Z" in str(after.value)
    assert world_module.GW2_CAPTURED_AT in str(after.value)

    # A week nothing was ever recorded for is a different answer, in different words.
    assert recorded_captures(records, SEASON, 3, 101) == ()
    with pytest.raises(AdviceRecordError) as nothing:
        load_member_advice_record_for_deadline(records, SEASON, 3, 101, deadline_utc=GW2_DEADLINE)
    assert "No advice record for 2026-27 gameweek 3, entry 101" in str(nothing.value)


def test_two_records_sharing_a_capture_instant_are_refused_rather_than_guessed(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """Which of two same-instant records a member saw is not recorded, so it is not guessed.

    Write order is not evidence and neither are file timestamps — a restored backup carries
    today's — so the reader names both and stops.
    """

    records = tmp_path / "records"
    _build(world, tmp_path / "site", record_root=records)
    record = load_member_advice_record(records, SEASON, 2, 101, world["gw2_id"])
    capture = record["capture"]
    assert isinstance(capture, dict)
    twin = dict(record)
    twin["capture"] = {
        "snapshot_id": f"fpl-live-20260827T090000Z-{'0' * 12}",
        "captured_at_utc": capture["captured_at_utc"],
    }
    record_member_advice(records, twin)

    with pytest.raises(AdviceRecordError) as tie:
        load_member_advice_record_for_deadline(records, SEASON, 2, 101, deadline_utc=GW2_DEADLINE)
    assert "sharing the last capture instant" in str(tie.value)
    assert world["gw2_id"] in str(tie.value)
    assert "0" * 12 in str(tie.value)


def test_a_record_in_the_pre_capture_layout_is_refused_rather_than_ignored(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """No migration is written, but neither shape is silently read as the other.

    No record under the old key existed anywhere when the key changed, so there is nothing
    to migrate. What would be unforgivable is reading past one: a reader listing capture
    directories would not see a v1 file sitting beside them and would answer "we told them
    nothing" with the evidence unread in that very directory. Reader and writer both stop.
    """

    records = tmp_path / "records"
    _build(world, tmp_path / "site", record_root=records)
    week = entry_directory(records, SEASON, 2, 101)
    # Exactly what v1 wrote: the record file directly in the member's week directory.
    (week / RECORD_FILE).write_bytes(b"{}\n")

    with pytest.raises(AdviceRecordError) as reading:
        recorded_captures(records, SEASON, 2, 101)
    assert "member_advice_record_v1" in str(reading.value)
    assert str(week / RECORD_FILE) in str(reading.value)

    with pytest.raises(AdviceRecordError) as writing:
        _build(world, tmp_path / "again", record_root=records)
    assert "member_advice_record_v1" in str(writing.value)


def test_a_rebuild_of_one_capture_that_differs_is_refused_and_names_what_differed(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """Different bytes over a recorded capture are refused, and the refusal is readable.

    This is the property the capture key must not lose. The capture is the whole input, so
    the same capture producing different bytes is a non-determinism in our own code — which
    is how a real one in the multi-week solves was found. A record that can be overwritten
    proves nothing about what was published, so the second build loses rather than the
    first. The message names the fields that moved: a re-run at a different minute and a
    re-run that changed the advice are both refused, and an operator has to be able to tell
    them apart without diffing two files by hand.
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
    # The refusal names the capture directory, so an operator can see it is one capture
    # disagreeing with itself rather than two publishes colliding.
    assert str(record_directory(records, SEASON, 2, 101, world["gw2_id"])) in str(clock.value)

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

    # Neither refusal rewrote anything, and neither left a second record behind.
    week = entry_directory(records, SEASON, 2, 101)
    assert [child.name for child in sorted(week.iterdir()) if child.is_dir()] == [world["gw2_id"]]
    record = load_member_advice_record(records, SEASON, 2, 101, world["gw2_id"])
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
    record = load_member_advice_record(records, SEASON, 2, 101, world["gw2_id"])
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
