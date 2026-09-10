"""Public-output guards: everything published under `data/league/` stays probability-free.

Four guards the existing suites do not carry: (1) a sweep of every file the league
builder publishes, applying the web guard's own bilingual regex backend-side
(`FORBIDDEN_TEXT_PATTERN`, shared with the producer that refuses a name for it), with
'%' refused everywhere in this tree rather than only under `advice/`: the earlier scope
was justified by ownership percentages, and the league builder publishes none — the
real 527-file tree contains no '%' at all, so the exemption only ever covered
`members.json` and `entries/{id}.json`, which are exactly the two files member-typed
free text lands in; (2) the same sweep with a hostile team and manager name driven
through the real builder, because a guard that invents its own team names is blind to
the one field a member writes; (3) the same sweep over `scoreboard.json`, which the
league builder does not write — `scripts/build_scoreboard.py` does, into the same
directory, so the first guard would never have seen it; and (4) a pin that the ledger
site path renders every probability field of the risk block as null with no rivals — so
switching the site build to a populated risk view breaks a named test instead of
silently shipping probabilities to pages that already render them.
"""

import json
from pathlib import Path
from typing import Any

import pytest
import tests.unit.test_live_transfers as world_module
from scripts.build_scoreboard import CohortCapture, CohortPicks, scoreboard_payload

from squadopt.application.build import _risk_from_status
from squadopt.application.entries import EntryError, EntryPicks, EntryRegistration
from squadopt.application.league_views import (
    PUBLISHED_NAME_LIMIT,
    MemberStanding,
    build_league_views,
    published_member_name,
)
from squadopt.application.strategies.catalog import (
    FORBIDDEN_FIELD_PATTERN,
    FORBIDDEN_TEXT_PATTERN,
)
from squadopt.data.snapshots import read_snapshot
from squadopt.live import LedgerEntry, read_inputs, read_season_rules
from squadopt.live.recommendation import project, read_projection_handoff

SEASON = world_module.SEASON

world = world_module._world  # re-register the fixture in this module

#: The producer's own rule, used as the sweep's rule: one pattern decides both what a
#: name may say and what a published file may contain, so the two cannot drift apart.
_FORBIDDEN_TEXT = FORBIDDEN_TEXT_PATTERN


class _Provider:
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
        free_transfers=1,
        free_transfers_known=False,
        source_snapshot_id=world["gw2_id"],
    )


def _legal_squad() -> list[int]:
    gk, defs = [1001, 1002], [1004, 1005, 1006, 1007, 1008]
    return gk + defs + [1012, 1013, 1014, 1015, 1016, 1020, 1021, 1022]


def _walk(node: object, path: str, offenders: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if FORBIDDEN_FIELD_PATTERN.search(str(key)):
                offenders.append(f"{path}.{key} (key)")
            _walk(value, f"{path}.{key}", offenders)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _walk(value, f"{path}[{index}]", offenders)
    elif isinstance(node, str) and _FORBIDDEN_TEXT.search(node):
        offenders.append(f"{path} (text: {node[:60]!r})")


def _sweep(out_dir: Path) -> list[str]:
    """Every offender in a published league tree, by the shared bilingual rule.

    The '%' check is over the file's raw text, not only its string values, so a key or a
    path carrying one is caught too; nothing in this tree is a share of anything.
    """

    published = sorted(out_dir.rglob("*.json"))
    assert published, "the builder wrote nothing — the sweep has no subject"
    offenders: list[str] = []
    for file in published:
        raw = file.read_text(encoding="utf-8")
        relative = file.relative_to(out_dir).as_posix()
        _walk(json.loads(raw), relative, offenders)
        if "%" in raw:
            offenders.append(f"{relative} (raw text contains '%')")
    return offenders


def test_every_published_league_file_is_probability_free(
    world: dict[str, Any], tmp_path: Path
) -> None:
    snapshot = read_snapshot(world["snapshot_root"], world["gw2_id"])
    inputs = read_inputs(snapshot, season=SEASON, gameweek=2)
    handoff = read_projection_handoff(world_module._handoff(world))
    projection = project(inputs, in_season=handoff)
    rules = read_season_rules(snapshot, season=SEASON)
    squad = _legal_squad()
    chaser = [*squad[:10], 1017, 1018, *squad[12:]]
    provider = _Provider(
        {101: _member_picks(world, 101, squad), 202: _member_picks(world, 202, chaser)}
    )
    out_dir = tmp_path / "league"
    # Two members with proven totals far apart, so the declared strategy rule actually
    # fires and its published band travels through this sweep rather than sitting null.
    standings = {
        entry_id: MemberStanding(
            entry_id=entry_id,
            team_name=f"Team {entry_id}",
            manager_name=f"Manager {entry_id}",
            rank=rank,
            total_points=total,
        )
        for rank, (entry_id, total) in enumerate(((101, 400), (202, 100)), start=1)
    }
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
        standings=standings,
        scored_gameweek=1,
    )
    suggested = json.loads((out_dir / "advice" / "101" / "index.json").read_text(encoding="utf-8"))[
        "payload"
    ]["suggested_strategy"]
    assert suggested is not None, "the rule's band must be in the swept tree, not null"
    offenders = _sweep(out_dir)
    assert offenders == [], f"probability-shaped content in the published tree: {offenders}"


#: One value per way a member-typed name can hurt a reader of these documents. Markup and
#: the script tag: our page is React and escapes both, but the files are served to
#: whoever asks. The controls: a NUL truncates a C string, an ESC is a command to a
#: terminal, a newline forges a log line. The override: U+202E reverses everything
#: printed after it. The long one: a name deciding the size of a payload every other
#: member downloads. The last two are the honesty half — a percentage and the inflected
#: Turkish form of "probability", which the guard's earlier `olas.l.k` did not match.
_HOSTILE_NAMES = {
    "markup": '<img src=x onerror="alert(1)">',
    "script": "<script>alert('xss')</script>",
    "long": "A" * 5000,
    "controls": "Team \x00\x1b[31m\tname\nsecond line",
    "override": "Team \u202eelbisrever\u202c name",
    "percent": "%72 sans",
    "turkish": "Kazanma olas\u0131l\u0131\u011f\u0131 y\u00fcksek",
}


def test_a_member_typed_name_cannot_carry_anything_into_the_published_tree(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """The same sweep, with the free text the capture actually carries made hostile.

    A team name and a manager name are typed by the member; the builder copies both into
    `members.json` and into the `entry` block of `entries/{id}.json`, and the page renders
    the team name as its `<h1>`. The guard above builds its own names ("Team 101"), so it
    could never have seen this. Every value below reached both files unchanged before the
    producer filtered them, and `%72 sans` — eight characters, a plausible FPL team name —
    put a percent sign on a published page.
    """

    snapshot = read_snapshot(world["snapshot_root"], world["gw2_id"])
    inputs = read_inputs(snapshot, season=SEASON, gameweek=2)
    handoff = read_projection_handoff(world_module._handoff(world))
    projection = project(inputs, in_season=handoff)
    rules = read_season_rules(snapshot, season=SEASON)
    squad = _legal_squad()
    chaser = [*squad[:10], 1017, 1018, *squad[12:]]
    provider = _Provider(
        {101: _member_picks(world, 101, squad), 202: _member_picks(world, 202, chaser)}
    )
    out_dir = tmp_path / "league"
    standings = {
        101: MemberStanding(
            entry_id=101,
            team_name=_HOSTILE_NAMES["markup"] + _HOSTILE_NAMES["percent"],
            manager_name=_HOSTILE_NAMES["script"],
            rank=1,
            total_points=400,
        ),
        202: MemberStanding(
            entry_id=202,
            team_name=_HOSTILE_NAMES["long"],
            manager_name=(
                _HOSTILE_NAMES["controls"] + _HOSTILE_NAMES["override"] + _HOSTILE_NAMES["turkish"]
            ),
            rank=2,
            total_points=100,
        ),
    }
    report = build_league_views(
        provider,
        # The registry's label is the member's own team name too, so it is hostile here.
        (
            EntryRegistration(101, _HOSTILE_NAMES["percent"], "2026-08-23T00:00:00Z"),
            EntryRegistration(202, _HOSTILE_NAMES["controls"], "2026-08-23T00:00:00Z"),
        ),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=out_dir,
        standings=standings,
        scored_gameweek=1,
    )
    assert report.rendered_count == 2, "a hostile name must not cost a member their advice"
    assert _sweep(out_dir) == [], "a member-typed name reached the published tree"

    rows = json.loads((out_dir / "members.json").read_text(encoding="utf-8"))["payload"]["members"]
    by_id = {int(row["entry_id"]): row for row in rows}
    # Refused, not blanked: an absent name and a name we would not print are different
    # facts, so the refused one is published as the entry's own id.
    assert by_id[101]["team_name"] == "entry-101"
    assert by_id[202]["manager_name"] == "entry-202"
    # Normalised, not refused: nothing here reads as a chance, so the member keeps a name.
    assert by_id[101]["manager_name"] == "script alert('xss') /script"
    assert len(by_id[202]["team_name"]) == PUBLISHED_NAME_LIMIT
    for row in rows:
        for field in ("team_name", "manager_name"):
            value = row[field]
            assert isinstance(value, str)
            assert "<" not in value and ">" not in value
            assert not any(ord(char) < 0x20 for char in value)
            assert "\u202e" not in value
            assert len(value) <= PUBLISHED_NAME_LIMIT
    # The same names in the entry document the page reads for its heading.
    entry = json.loads((out_dir / "entries" / "101.json").read_text(encoding="utf-8"))
    assert entry["payload"]["entry"]["team_name"] == "entry-101"
    # Every alteration is stated: a name changed without a word said would be the quiet
    # half of this. The batch still renders, so the note travels on a rendered row.
    reasons = {member.entry_id: member.reason for member in report.members}
    assert "team_name: replaced with 'entry-101'" in reasons[101]
    assert f"team_name: truncated to {PUBLISHED_NAME_LIMIT} characters" in reasons[202]
    assert "manager_name: replaced with 'entry-202'" in reasons[202]


@pytest.mark.parametrize(
    "raw",
    [
        # An adjective and a surname that merely open with the noun "şans", and a
        # phrase that contains "yüzde" while meaning "for that reason". Each was
        # published as the entry's id while the Turkish alternatives carried a leading
        # word boundary only.
        pytest.param("Şansl\u0131", id="adjective-sansli"),
        pytest.param("Şansal", id="surname-sansal"),
        pytest.param("Bu Yüzden", id="phrase-bu-yuzden"),
    ],
)
def test_a_turkish_name_that_only_contains_a_chance_word_is_published_unchanged(raw: str) -> None:
    """Nothing here reads as a chance, so the producer hands the name on byte for byte
    and says nothing about it: a refusal note on a legitimate name is a false claim."""

    assert published_member_name(raw, entry_id=7, field="team_name") == (raw, "")


@pytest.mark.parametrize(
    "raw",
    [
        # The bare words the new boundaries delimit, and the inflections that are still
        # the forbidden word rather than a name: ``olas\u0131l\u0131\u011f\u0131`` is the
        # one an earlier, narrower stem let through.
        pytest.param("şans", id="sans"),
        pytest.param("Yüzde 72", id="yuzde-72"),
        pytest.param("yüzde", id="yuzde"),
        pytest.param("ihtimali", id="ihtimali"),
        pytest.param("ihtimalle", id="ihtimalle"),
        pytest.param("olas\u0131l\u0131\u011f\u0131", id="olasiligi"),
        pytest.param("Kazanma olas\u0131l\u0131\u011f\u0131 y\u00fcksek", id="olasiligi-sentence"),
    ],
)
def test_a_turkish_chance_word_is_still_refused_whole_or_inflected(raw: str) -> None:
    """The other half of the same rule. Narrowing the false refusals above must not open
    a true one, so each of these still publishes as the entry's id, with the reason."""

    published, note = published_member_name(raw, entry_id=7, field="team_name")
    assert published == "entry-7"
    assert "team_name: replaced with 'entry-7'" in note


_DEADLINES = {
    1: "2026-08-21T17:30:00Z",
    2: "2026-08-28T17:30:00Z",
    3: "2026-09-04T17:30:00Z",
}


def _scoreboard_document(basis: str) -> dict[str, Any]:
    """A scoreboard covering every state the card renders: our settled and unsettled rows,
    members with and without a transfer cost, a finished-but-unchecked week, and the
    Top-100 mean on the basis asked for."""

    events = [
        {
            "id": week,
            "deadline_time": _DEADLINES[week],
            "finished": week < 3,
            "data_checked": week < 2,
            "average_entry_score": 50 + week,
            "highest_score": 130 + week,
        }
        for week in (1, 2, 3)
    ]
    bootstrap = json.dumps({"events": events}).encode("utf-8")
    pages = [
        json.dumps(
            {
                "standings": {
                    "results": [
                        {
                            "entry": 900_000 + rank,
                            "rank": rank,
                            "rank_sort": rank,
                            "event_total": rank,
                            "total": 300,
                        }
                        for rank in range(1, 101)
                    ]
                }
            }
        ).encode("utf-8")
    ]
    cohort = CohortCapture(
        snapshot_id="fpl-top100-test",
        captured_at_utc="2026-08-30T13:11:12Z",
        bootstrap=bootstrap,
        pages=tuple(pages),
    )
    picks = CohortPicks(
        snapshot_id="fpl-elite-picks-test",
        gameweek=2,
        net={900_000 + rank: rank - 1 for rank in range(1, 101)},
        hits={900_000 + rank: 1 for rank in range(1, 101)},
    )
    history = json.dumps(
        {
            "chips": [],
            "current": [
                {"event": 1, "points": 64, "total_points": 64, "event_transfers_cost": 0},
                {"event": 2, "points": 78, "total_points": 138, "event_transfers_cost": 4},
            ],
        }
    ).encode("utf-8")
    decision = {
        "snapshot_id": "fpl-live-test",
        "projected_score": 56.1,
        "metadata": {"mode": "replay"},
        "transfers": {"transfer_hit_points": 4.0, "chip": "bboost"},
    }
    outcome = {"realized_net_score": 26.0, "realized_xi_score": 30.0}
    entries = (
        LedgerEntry("2026-27", 1, decision, outcome, Path(".")),
        LedgerEntry("2026-27", 2, decision, None, Path(".")),
    )
    return scoreboard_payload(
        season="2026-27",
        league_id=352490,
        bootstrap=bootstrap,
        captured_at_utc="2026-09-07T13:14:14Z",
        source_snapshot_id="fpl-live-test",
        histories={11: history},
        registered=[11, 22],
        ledger_entries=entries,
        cohort=cohort,
        cohort_picks=picks if basis == "net" else None,
        generated_at_utc="2026-09-07T13:20:00Z",
    )


@pytest.mark.parametrize("basis", ["net", "gross"])
def test_the_published_scoreboard_is_probability_free(basis: str, tmp_path: Path) -> None:
    """`scoreboard.json` lands in `data/league/` beside the builder's own files, so the
    sweep above would never have seen it: a different producer writes it. Same regex,
    same rule — and '%' is refused here too, because the scoreboard publishes points,
    never a share of anything."""

    document = _scoreboard_document(basis)
    raw = json.dumps(document, indent=2, sort_keys=True, allow_nan=False)
    target = tmp_path / "scoreboard.json"
    target.write_text(raw, encoding="utf-8")
    offenders: list[str] = []
    _walk(json.loads(raw), "scoreboard.json", offenders)
    if "%" in raw:
        offenders.append("scoreboard.json contains '%'")
    assert offenders == [], f"probability-shaped content in the scoreboard: {offenders}"
    # The sweep has a subject: the rows it swept really carry the numbers.
    payload = document["payload"]
    assert isinstance(payload, dict)
    weeks = payload["gameweeks"]
    assert isinstance(weeks, list) and len(weeks) == 3
    top100 = [week["top100"] for week in weeks if week["top100"] is not None]
    assert [week["basis"] for week in top100] == [basis]


def test_the_ledger_site_path_nulls_every_probability_field() -> None:
    for status in ("not_requested", "unavailable", "available", "unexpected"):
        risk = _risk_from_status(status)
        assert risk.lower_quantile_probability is None
        assert risk.lower_quantile_score is None
        assert risk.mean_score is None
        assert risk.mean_worst_fraction_score is None
        assert risk.worst_fraction is None
        assert risk.points_threshold is None
        assert risk.probability_below_threshold is None
        assert risk.probability_below_threshold_interval is None
        assert risk.location_shift_points is None
        assert risk.rivals == ()
        assert risk.status == status
