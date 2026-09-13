"""Public-output guards: everything *we write* under `data/league/` stays probability-free.

The envelope covers the text this repository generates — strategy names, notes, badges,
rule copy — and not a member's own team name, manager name or registry label. Those are
the member's words, already public in the game once the deadline passes, so publishing
them is not this site making a claim; they are published as captured, and the sweeps
below skip them by field rather than pretending they were never there.

Five guards the existing suites do not carry: (1) a sweep of every file the league
builder publishes, applying the web guard's own bilingual regex backend-side
(`FORBIDDEN_TEXT_PATTERN`), with '%' refused everywhere in this tree rather than only
under `advice/`: the earlier scope was justified by ownership percentages, and the
league builder publishes none — the real 527-file tree contains no '%' at all outside
the fields a member types; (2) the same sweep with a hostile team and manager name
driven through the real builder, because a guard that invents its own team names is
blind to the one field a member writes — the honesty half of that name is now the
member's business, the *shape* half (markup, controls, length) is still ours;
(3) a pin on the scope boundary itself, that the same chance wording is swept in a
generated field and skipped in a member-typed one; (4) the same sweep over
`scoreboard.json`, which the league builder does not write —
`scripts/build_scoreboard.py` does, into the same directory, so the first guard would
never have seen it; and (5) a pin that the ledger site path renders every probability
field of the risk block as null with no rivals — so switching the site build to a
populated risk view breaks a named test instead of silently shipping probabilities to
pages that already render them.
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

#: The producer's own rule, used as the sweep's rule: one pattern decides what a
#: published file may contain, so the two cannot drift apart.
_FORBIDDEN_TEXT = FORBIDDEN_TEXT_PATTERN

#: The published keys whose value is text a member typed rather than text we generated.
#: `team_name` and `manager_name` are the standings row's own two fields, copied into
#: `members.json` and into the `entry` block of `entries/{id}.json`; `manager_name` also
#: falls back to the registry label, which is the member's team name by another route.
#: `rival_label` is a third route to the same string: `mode_selection` labels a rival
#: with their own team name, so a competitive-mode advice file carries one. Measured
#: against the real 527-file tree: no other key in it holds a member-typed name.
#:
#: Skipped by the sweeps, not stripped by the producer — the honesty envelope is about
#: our words, and these are not ours. Their *shape* is still ours and is pinned below.
_MEMBER_TYPED_FIELDS = frozenset({"team_name", "manager_name", "rival_label"})


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
        squad_sell_value_tenths=world_module.member_squad_sell_value(world, squad_codes),
        free_transfers=1,
        free_transfers_known=False,
        source_snapshot_id=world["gw2_id"],
    )


def _legal_squad() -> list[int]:
    gk, defs = [1001, 1002], [1004, 1005, 1006, 1007, 1008]
    return gk + defs + [1012, 1013, 1014, 1015, 1016, 1020, 1021, 1022]


def _walk(node: object, path: str, offenders: list[str]) -> None:
    """Report every string we generated that reads as a chance, and every field name that
    does. A member-typed field's *value* is skipped — its key is still checked, because
    the key is ours even where the value is not."""

    if isinstance(node, dict):
        for key, value in node.items():
            if FORBIDDEN_FIELD_PATTERN.search(str(key)):
                offenders.append(f"{path}.{key} (key)")
            if key in _MEMBER_TYPED_FIELDS:
                continue
            _walk(value, f"{path}.{key}", offenders)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _walk(value, f"{path}[{index}]", offenders)
    elif isinstance(node, str) and _FORBIDDEN_TEXT.search(node):
        offenders.append(f"{path} (text: {node[:60]!r})")


def _without_member_typed_names(node: object) -> object:
    """The same document with every member-typed value blanked, so the raw-text checks
    below read only what this repository wrote. Keys survive, so a '%' in one is still
    caught; a member who calls their team `%72 sans` no longer trips the file."""

    if isinstance(node, dict):
        return {
            key: ("" if key in _MEMBER_TYPED_FIELDS else _without_member_typed_names(value))
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_without_member_typed_names(value) for value in node]
    return node


def _sweep(out_dir: Path) -> list[str]:
    """Every offender in a published league tree, by the shared bilingual rule.

    The '%' check is over the document's text, not only its string values, so a key or a
    path carrying one is caught too; nothing we write in this tree is a share of anything.
    """

    published = sorted(out_dir.rglob("*.json"))
    assert published, "the builder wrote nothing — the sweep has no subject"
    offenders: list[str] = []
    for file in published:
        document = json.loads(file.read_text(encoding="utf-8"))
        relative = file.relative_to(out_dir).as_posix()
        _walk(document, relative, offenders)
        ours = json.dumps(_without_member_typed_names(document), ensure_ascii=False)
        if "%" in ours:
            offenders.append(f"{relative} (text we wrote contains '%')")
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
#: member downloads. The last two are no longer hostile at all — a percentage and the
#: inflected Turkish form of "probability" are words a member is entitled to put in their
#: own team name, and they are kept here to pin that they now travel through untouched.
_HOSTILE_NAMES = {
    "markup": '<img src=x onerror="alert(1)">',
    "script": "<script>alert('xss')</script>",
    "long": "A" * 5000,
    "controls": "Team \x00\x1b[31m\tname\nsecond line",
    "override": "Team \u202eelbisrever\u202c name",
    "percent": "%72 sans",
    "turkish": "Kazanma olas\u0131l\u0131\u011f\u0131 y\u00fcksek",
}


def test_a_member_typed_name_cannot_carry_markup_or_controls_into_the_published_tree(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """The same sweep, with the free text the capture actually carries made hostile.

    A team name and a manager name are typed by the member; the builder copies both into
    `members.json` and into the `entry` block of `entries/{id}.json`, and the page renders
    the team name as its `<h1>`. The guard above builds its own names ("Team 101"), so it
    could never have seen this. Every value below reached both files unchanged before the
    producer normalised them.

    What the producer decides about a name is its shape, not its wording: markup
    delimiters, control and format characters, and a length bound, because a document is
    not made safe by one of its readers and one member may not set the size of a payload
    the other fourteen download. The wording is the member's own — `%72 sans` is a
    plausible FPL team name and is published as the member typed it.
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
    assert _sweep(out_dir) == [], "text we generated reached the published tree unswept"

    rows = json.loads((out_dir / "members.json").read_text(encoding="utf-8"))["payload"]["members"]
    by_id = {int(row["entry_id"]): row for row in rows}
    # Normalised, never replaced. The markup delimiters are gone and the percentage the
    # member typed is still there: the first is ours to decide, the second is theirs.
    assert by_id[101]["team_name"] == 'img src=x onerror="alert(1)" %72 sans'
    assert by_id[101]["manager_name"] == "script alert('xss') /script"
    assert len(by_id[202]["team_name"]) == PUBLISHED_NAME_LIMIT
    # Controls and the bidi override removed, the rest kept \u2014 including the Turkish
    # "olas\u0131l\u0131\u011f\u0131" that used to cost this member their name.
    assert by_id[202]["manager_name"] == (
        "Team [31m name second lineTeam elbisrever nameKazanma olas\u0131l\u0131\u011f\u0131"
    )
    for row in rows:
        for field in ("team_name", "manager_name"):
            value = row[field]
            assert isinstance(value, str)
            assert "<" not in value and ">" not in value
            assert not any(ord(char) < 0x20 for char in value)
            assert "\u202e" not in value
            assert len(value) <= PUBLISHED_NAME_LIMIT
            assert not value.startswith("entry-"), "no member here has lost their name"
    # The same name in the entry document the page reads for its heading.
    entry = json.loads((out_dir / "entries" / "101.json").read_text(encoding="utf-8"))
    assert entry["payload"]["entry"]["team_name"] == 'img src=x onerror="alert(1)" %72 sans'
    # Every alteration is stated: a name changed without a word said would be the quiet
    # half of this. The batch still renders, so the note travels on a rendered row.
    reasons = {member.entry_id: member.reason for member in report.members}
    assert "team_name: unprintable characters and markup delimiters removed" in reasons[101]
    assert f"team_name: truncated to {PUBLISHED_NAME_LIMIT} characters" in reasons[202]
    assert "manager_name: unprintable characters and markup delimiters removed" in reasons[202]
    # And nothing is said about a name we did not alter: the registry label `%72 sans`
    # travels whole, so no note may claim otherwise.
    assert "replaced with" not in reasons[101] and "replaced with" not in reasons[202]


@pytest.mark.parametrize(
    "raw",
    [
        # An adjective and a surname that merely open with the noun "\u015fans", and a
        # phrase that contains "y\u00fczde" while meaning "for that reason". These three
        # cost their members a name until the word boundaries were added.
        pytest.param("\u015eansl\u0131", id="adjective-sansli"),
        pytest.param("\u015eansal", id="surname-sansal"),
        pytest.param("Bu Y\u00fczden", id="phrase-bu-yuzden"),
        # And these, which the boundaries left refused: the bare nouns and the
        # inflections. A member is entitled to call their team "\u015fans" — it is their
        # word in their own language, and the site is not the one saying it. No boundary
        # can tell these two groups apart, which is why the check does not belong on a
        # member's name at all.
        pytest.param("\u015fans", id="sans"),
        pytest.param("y\u00fczde", id="yuzde"),
        pytest.param("olas\u0131l\u0131\u011f\u0131", id="olasiligi"),
        pytest.param("Y\u00fczde 72", id="yuzde-72"),
        pytest.param("ihtimali", id="ihtimali"),
        pytest.param("ihtimalle", id="ihtimalle"),
        pytest.param("Kazanma olas\u0131l\u0131\u011f\u0131 y\u00fcksek", id="olasiligi-sentence"),
        # A percent sign, and the entry stand-in's own shape. Neither is refused: the
        # first is the member's word, and the second never was refused — the stand-in is
        # what a member with *no* readable name is published under, and nothing reads a
        # name back as an id, so a name shaped like one impersonates nothing.
        pytest.param("%72 sans", id="percent"),
        pytest.param("entry-7", id="stand-in-shaped"),
    ],
)
def test_a_member_typed_name_is_published_as_captured(raw: str) -> None:
    """A member's name is the member's own words. It is already public in the game once
    the deadline passes, and repeating it is not this site making a claim — so the
    honesty envelope does not reach it, and the producer hands it on byte for byte with
    nothing said about it. A note on a name we did not alter would be a false claim."""

    assert published_member_name(raw, entry_id=7, field="team_name") == (raw, "")


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("\u015fans", id="sans"),
        pytest.param("y\u00fczde", id="yuzde"),
        pytest.param("olas\u0131l\u0131\u011f\u0131", id="olasiligi"),
        pytest.param("Kazanma olas\u0131l\u0131\u011f\u0131 y\u00fcksek", id="olasiligi-sentence"),
        pytest.param("ihtimali", id="ihtimali"),
        pytest.param("%72", id="percent"),
        pytest.param("a 60% chance of catching up", id="english-chance"),
        pytest.param("the likelihood of a green arrow", id="english-likelihood"),
    ],
)
def test_our_own_copy_is_still_refused_when_it_reads_as_a_chance(text: str) -> None:
    """The half that does not move. Taking member-typed names out of the envelope must
    not take anything out of it that this repository wrote, so the rule itself is
    unchanged and the sweep still reports every one of these in a generated field."""

    assert _FORBIDDEN_TEXT.search(text) is not None
    offenders: list[str] = []
    _walk({"payload": {"note": text}}, "advice/7/index.json", offenders)
    assert offenders == [f"advice/7/index.json.payload.note (text: {text[:60]!r})"]


@pytest.mark.parametrize("field", sorted(_MEMBER_TYPED_FIELDS))
def test_the_sweep_skips_a_member_typed_field_and_only_that(field: str) -> None:
    """The scope boundary, pinned from both sides with one string. Under a key the member
    fills in, `Kazanma olas\u0131l\u0131\u011f\u0131 %72` is their wording and passes;
    under a key we fill in, the identical string is an offender. Move a field between the
    two sets and this test says so."""

    text = "Kazanma olas\u0131l\u0131\u011f\u0131 %72"
    theirs: list[str] = []
    _walk({"payload": {field: text}}, "members.json", theirs)
    assert theirs == []
    assert "%" not in json.dumps(
        _without_member_typed_names({"payload": {field: text}}), ensure_ascii=False
    )
    ours: list[str] = []
    _walk({"payload": {"suggested_strategy": text}}, "members.json", ours)
    assert ours == [f"members.json.payload.suggested_strategy (text: {text!r})"]


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
