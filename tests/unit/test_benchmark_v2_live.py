"""Prospective reading uses only synthetic frozen weeks and refuses repeated looks."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from tests.unit.test_benchmark_v2_measurement import _parity_snapshot, _snapshot, _top100_page

from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    league_standings_page_payload,
    live_payload,
)
from squadopt.evaluation import EvaluationValidationError
from squadopt.experiments import benchmark_v2_live as live


def week(
    gameweek=6, coverage=100, *, event_points=None, system_captain=(1008, 1009), captains=None
):
    """One synthetic frozen week.

    ``event_points`` maps an element id to its settled points, ``system_captain`` names the
    frozen system captain and vice by code, and ``captains`` maps a cohort rank to the
    element ids it captains and vice-captains, so the three arms can score differently.
    """
    base = _parity_snapshot()
    boot = json.loads(base.payloads[BOOTSTRAP_PAYLOAD])
    deadline = datetime(2026, 10, 10, 10, tzinfo=UTC) + timedelta(weeks=gameweek - 6)

    def stamp(hours):
        return (deadline + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")

    boot["events"][0].update(
        id=gameweek, deadline_time=stamp(0), finished=False, data_checked=False
    )
    boot["events"].append(
        {"id": gameweek - 1, "deadline_time": stamp(-168), "finished": True, "data_checked": True}
    )
    for element in boot["elements"]:
        element["selected_by_percent"] = str(100 - element["id"])
    decision_boot = json.dumps(boot).encode()
    decision = _snapshot("fpl-live", {BOOTSTRAP_PAYLOAD: decision_boot}, captured=stamp(-2))
    cohort = _snapshot(
        "fpl-top100",
        {
            BOOTSTRAP_PAYLOAD: decision_boot,
            league_standings_page_payload(314, 1): _top100_page(1, 1),
            league_standings_page_payload(314, 2): _top100_page(2, 51),
        },
        captured=stamp(-3),
    )
    picks_data = {
        BOOTSTRAP_PAYLOAD: decision_boot,
        "benchmark.json": json.dumps(
            {
                "season": "2026-27",
                "gameweek": gameweek,
                "cohort_snapshot_id": cohort.metadata.snapshot_id,
            }
        ).encode(),
    }
    for rank in range(1, coverage + 1):
        entry = 1000 + rank
        raw_picks = base.payloads["entry-99-picks-gw01.json"]
        if captains is not None and rank in captains:
            captain, vice = captains[rank]
            document = json.loads(raw_picks)
            for row in document["picks"]:
                row["is_captain"] = row["element"] == captain
                row["is_vice_captain"] = row["element"] == vice
                row["multiplier"] = 2 if row["element"] == captain else int(row["position"] <= 11)
            raw_picks = json.dumps(document).encode()
        picks_data[f"entry-{entry}-picks-gw{gameweek:02d}.json"] = raw_picks
        picks_data[f"entry-{entry}-history.json"] = base.payloads["entry-99-history.json"]
    picks = _snapshot("fpl-benchmark-picks", picks_data, captured=stamp(1))
    system = {
        "snapshot_id": decision.metadata.snapshot_id,
        "captured_at_utc": decision.metadata.captured_at_utc,
        "season": "2026-27",
        "gameweek": gameweek,
        "deadline_utc": stamp(0),
        "squad_player_ids": list(range(1001, 1016)),
        "starting_xi_player_ids": [
            1001,
            1003,
            1004,
            1005,
            1006,
            1008,
            1009,
            1010,
            1011,
            1013,
            1014,
        ],
        "ordered_bench_player_ids": [1002, 1007, 1012, 1015],
        "captain_player_id": system_captain[0],
        "vice_captain_player_id": system_captain[1],
        "completion_policy": "captured_entry_v1",
        "model_version": "synthetic-current",
    }
    frozen = json.dumps(system).encode()
    binding = {
        "season": "2026-27",
        "gameweek": gameweek,
        "cohort_snapshot_id": cohort.metadata.snapshot_id,
        "decision_snapshot_id": decision.metadata.snapshot_id,
        "decision_fingerprint": decision.metadata.fingerprint,
        "system_decision_sha256": hashlib.sha256(frozen).hexdigest(),
        "template_configuration": {
            "budget_tenths": 1000,
            "max_players_per_team": 3,
            "expected_points_scale": 1000,
        },
    }
    freeze = _snapshot(
        "fpl-benchmark-decision",
        {
            BOOTSTRAP_PAYLOAD: decision_boot,
            "system-decision.json": frozen,
            "benchmark.json": json.dumps(binding).encode(),
        },
        captured=stamp(-1),
    )
    boot["events"][0].update(finished=True, data_checked=True)
    if event_points is not None:
        for element in boot["elements"]:
            element["event_points"] = event_points[element["id"]]
    outcome = _snapshot(
        "fpl-live",
        {
            BOOTSTRAP_PAYLOAD: json.dumps(boot).encode(),
            live_payload(gameweek): json.dumps(
                {
                    "elements": [
                        {
                            "id": row["id"],
                            "stats": {
                                "minutes": row["minutes"],
                                "total_points": row["event_points"],
                                "yellow_cards": 0,
                                "red_cards": 0,
                                "starts": int(row["minutes"] > 0),
                            },
                        }
                        for row in boot["elements"]
                    ]
                }
            ).encode(),
        },
        captured=stamp(72),
    )
    return live.LiveBenchmarkWeek(gameweek, decision, freeze, cohort, picks, outcome)


def read(weeks, root, *, missing=(), first=None, last=None):
    listed = [candidate.gameweek for candidate in weeks] + list(missing)
    return live.read_live_benchmark_once(
        weeks,
        record_root=root,
        repository_commit="a" * 40,
        preregistration_sha256="b" * 64,
        first_gameweek=min(listed) if first is None else first,
        last_gameweek=max(listed) if last is None else last,
        missing_gameweeks=missing,
        manifest_sha256="c" * 64,
    )


def test_early_reading_refuses_before_preparing_or_scoring(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "prepare_live_week", lambda *_: pytest.fail("Early input was opened"))
    with pytest.raises(EvaluationValidationError, match="eight valid"):
        read([week()] * 7, tmp_path)
    assert not (tmp_path / live.CLAIM_FILE).exists()


# Element 3 never plays; every other element scores its own id. The system captains the
# goalkeeper (1 point), half the cohort captains element 14 and the template captains its
# most-owned starter, so the three arms score 89, 99 and 87 and the two differences differ
# in sign.
DISTINCT_POINTS = {element: 0 if element == 3 else element for element in range(1, 16)}
DISTINCT_ARMS = {
    "event_points": DISTINCT_POINTS,
    "system_captain": (1001, 1009),
    "captains": {rank: (14, 13) for rank in range(1, 101, 2)},
}


PAIRED = [7, *range(9, 16)]


def test_eight_weeks_pair_all_arms_and_second_reading_opens_nothing(tmp_path, monkeypatch):
    weeks = [week(gameweek, **DISTINCT_ARMS) for gameweek in PAIRED] + [week(16, 79)]
    result = read(list(reversed(weeks)), tmp_path, missing=[8])
    assert result["declared_gameweeks"] == {"first_gameweek": 7, "last_gameweek": 16}
    assert result["manifest_sha256"] == "c" * 64
    assert result["exclusions"] == [
        {"gameweek": 8, "reason": "missing_capture"},
        {
            "gameweek": 16,
            "reason": "insufficient_coverage",
            "cohort_valid": 79,
            "cohort_excluded": 21,
            "cohort_exclusions": {
                "chip_unresolved": 0,
                "free_hit_previous_missing": 0,
                "unreadable": 21,
                "invalid_picks": 0,
                "missing_outcome": 0,
            },
            "cohort_chip_rosters": {"wildcard": 0, "freehit": 0},
        },
    ]
    assert result["paired_gameweeks"] == 8
    assert [row["gameweek"] for row in result["rows"]] == PAIRED
    for row in result["rows"]:
        assert (row["system"]["points"], row["template"]["points"]) == (89, 87)
        assert row["cohort"]["points"] == 99
        assert row["system_minus_template"] == 2
        assert row["system_minus_cohort"] == -10
        assert row["system"]["v1_points"] == 82
    assert result["summary"] == {
        "mean_system_minus_template": 2,
        "median_system_minus_template": 2,
        "mean_system_minus_cohort": -10,
        "median_system_minus_cohort": -10,
    }
    assert (result["scoring_basis"], result["template_policy"], result["cohort_policy"]) == (
        "official_autosub_captain_v2",
        "ownership_template_v2",
        "as_of_top_100_v1",
    )
    assert json.loads((tmp_path / live.READING_FILE).read_bytes()) == result
    markdown = (tmp_path / live.READING_FILE.replace(".json", ".md")).read_text(encoding="utf-8")
    assert "- Template policy: `ownership_template_v2`" in markdown
    assert "- Cohort policy: `as_of_top_100_v1`" in markdown
    assert "| System minus template | +2.000 | +2.000 |" in markdown
    assert "| System minus cohort | -10.000 | -10.000 |" in markdown
    week_lines = [line for line in markdown.splitlines() if line.endswith("| 100 | 0 |")]
    assert week_lines == [
        f"| {gameweek} | 89.000 | 87.000 | 99.000 | +2.000 | -10.000 | 100 | 0 |"
        for gameweek in PAIRED
    ]
    assert "- Declared gameweeks: 7 to 16" in markdown
    assert "| 8 | `missing_capture` | not read | not read |" in markdown
    assert "| 16 | `insufficient_coverage` | 79 | 21 |" in markdown
    monkeypatch.setattr(
        live, "prepare_live_week", lambda *_: pytest.fail("Second input was opened")
    )
    with pytest.raises(EvaluationValidationError, match="already been claimed"):
        read(weeks, tmp_path, missing=[8])


@pytest.mark.parametrize(
    ("listed", "missing", "first", "last"),
    [
        ([7, *range(9, 16)], (), 7, 15),  # GW8 left out without a trace
        (list(range(7, 15)), (), 7, 13),  # GW14 outside the declared range
        (list(range(7, 15)), (8,), 7, 14),  # GW8 both captured and missing
        (list(range(7, 15)), (), 14, 7),  # reversed range
        (list(range(6, 14)), (), 6, 13),  # starts before the declared GW7
        (list(range(8, 16)), (), 8, 15),  # starts after the declared GW7
        (list(range(7, 15)), (), 2, 14),  # before the first prospective cohort
    ],
)
def test_every_declared_gameweek_is_listed_before_any_week_is_prepared(
    tmp_path, monkeypatch, listed, missing, first, last
):
    monkeypatch.setattr(live, "prepare_live_week", lambda *_: pytest.fail("Input was opened"))
    with pytest.raises(EvaluationValidationError, match=r"declared gameweek|unique"):
        read(
            [week(gameweek) for gameweek in listed],
            tmp_path,
            missing=missing,
            first=first,
            last=last,
        )
    assert not (tmp_path / live.CLAIM_FILE).exists()


def test_coverage_below_eighty_cannot_make_a_valid_eighth_week(tmp_path):
    weeks = [week(gameweek) for gameweek in range(7, 14)] + [week(14, 79)]
    with pytest.raises(EvaluationValidationError, match="eight valid"):
        read(weeks, tmp_path)
    assert not (tmp_path / live.CLAIM_FILE).exists()


def _restamp(snapshot, captured_at_utc):
    return replace(snapshot, metadata=replace(snapshot.metadata, captured_at_utc=captured_at_utc))


def _with_payload(snapshot, name, raw):
    return replace(snapshot, payloads={**snapshot.payloads, name: raw})


def _with_configuration(candidate, **changes):
    binding = json.loads(candidate.freeze.payloads["benchmark.json"])
    binding["template_configuration"].update(changes)
    return replace(
        candidate,
        freeze=_with_payload(candidate.freeze, "benchmark.json", json.dumps(binding).encode()),
    )


@pytest.mark.parametrize(
    ("captured_at_utc", "admitted"),
    [
        ("2026-10-09T08:00:00Z", False),  # before GW6's deadline: ranked as of GW5
        ("2026-10-17T09:59:59Z", False),  # GW7 still open: the cohort of an older week
        ("2026-10-17T10:00:00Z", True),  # GW7's deadline closes GW7, so GW8 is open
        ("2026-10-17T10:00:01Z", True),
    ],
)
def test_cohort_ranked_before_the_previous_deadline_is_stale(captured_at_utc, admitted):
    candidate = week(8)
    candidate = replace(candidate, cohort=_restamp(candidate.cohort, captured_at_utc))
    if admitted:
        assert live.prepare_live_week(candidate).gameweek == 8
        return
    with pytest.raises(live.LiveWeekRefusal, match="previous gameweek deadline") as refused:
        live.prepare_live_week(candidate)
    assert refused.value.code == "stale_cohort"


@pytest.mark.parametrize(
    ("damage", "message", "code"),
    [
        ("early_picks", "cannot precede deadline", "early_capture"),
        ("early_outcome", "cannot precede deadline", "early_capture"),
        ("changed_pool", "decision-time ownership pool", "provenance_mismatch"),
        ("team_limit", "declared FPL policy", "invalid_configuration"),
        ("ownership_scale", "declared FPL policy", "invalid_configuration"),
    ],
)
def test_capture_timing_pool_and_configuration_gates_refuse_the_week(damage, message, code):
    candidate = week()
    if damage == "early_picks":
        candidate = replace(candidate, picks=_restamp(candidate.picks, "2026-10-10T09:59:59Z"))
    elif damage == "early_outcome":
        candidate = replace(candidate, outcome=_restamp(candidate.outcome, "2026-10-10T09:59:59Z"))
    elif damage == "changed_pool":
        boot = json.loads(candidate.freeze.payloads[BOOTSTRAP_PAYLOAD])
        boot["elements"][0]["selected_by_percent"] = "0.1"
        candidate = replace(
            candidate,
            freeze=_with_payload(candidate.freeze, BOOTSTRAP_PAYLOAD, json.dumps(boot).encode()),
        )
    elif damage == "team_limit":
        candidate = _with_configuration(candidate, max_players_per_team=4)
    else:
        candidate = _with_configuration(candidate, expected_points_scale=100)
    with pytest.raises(live.LiveWeekRefusal, match=message) as refused:
        live.prepare_live_week(candidate)
    assert refused.value.code == code


@pytest.mark.parametrize(
    ("damage", "code"),
    [
        ("late_freeze", "late_capture"),
        ("wrong_cohort", "provenance_mismatch"),
        ("unchecked", "unchecked_outcome"),
        ("changed_decision", "provenance_mismatch"),
    ],
)
def test_invalid_week_is_refused_before_a_reading(damage, code):
    candidate = week()
    if damage == "late_freeze":
        candidate = replace(
            candidate,
            freeze=replace(
                candidate.freeze,
                metadata=replace(candidate.freeze.metadata, captured_at_utc="2026-10-10T10:00:00Z"),
            ),
        )
    elif damage == "wrong_cohort":
        candidate = replace(
            candidate,
            picks=replace(
                candidate.picks,
                payloads={
                    **candidate.picks.payloads,
                    "benchmark.json": json.dumps(
                        {"season": "2026-27", "gameweek": 6, "cohort_snapshot_id": "other"}
                    ).encode(),
                },
            ),
        )
    elif damage == "unchecked":
        boot = json.loads(candidate.outcome.payloads[BOOTSTRAP_PAYLOAD])
        boot["events"][0]["data_checked"] = False
        candidate = replace(
            candidate,
            outcome=replace(
                candidate.outcome,
                payloads={
                    **candidate.outcome.payloads,
                    BOOTSTRAP_PAYLOAD: json.dumps(boot).encode(),
                },
            ),
        )
    else:
        candidate = replace(
            candidate,
            freeze=replace(
                candidate.freeze,
                payloads={
                    **candidate.freeze.payloads,
                    "system-decision.json": candidate.freeze.payloads["system-decision.json"]
                    + b" ",
                },
            ),
        )
    with pytest.raises(live.LiveWeekRefusal) as refused:
        live.prepare_live_week(candidate)
    assert refused.value.code == code


def test_exactly_eighty_valid_members_pass_without_backfilling():
    prepared = live.prepare_live_week(week(coverage=80))
    assert len(prepared.managers) == 80
    assert prepared.provenance["cohort_excluded"] == 20
    assert prepared.provenance["cohort_exclusions"] == {
        "chip_unresolved": 0,
        "free_hit_previous_missing": 0,
        "unreadable": 20,
        "invalid_picks": 0,
        "missing_outcome": 0,
    }
    assert prepared.provenance["solver_configuration"] == {
        "deterministic_time_limit": 5.0,
        "wall_time_limit_seconds": 600.0,
        "binding_limit": "deterministic_time",
    }


def test_thin_week_keeps_its_coverage_counted_by_reason():
    candidate = week(coverage=82)
    payloads = dict(candidate.picks.payloads)
    for entry, chip in ((1001, "freehit"), (1002, "freehit"), (1003, "unknown")):
        name = f"entry-{entry}-picks-gw06.json"
        document = json.loads(payloads[name])
        document["active_chip"] = chip
        payloads[name] = json.dumps(document).encode()
    name = "entry-1004-picks-gw06.json"
    document = json.loads(payloads[name])
    document["automatic_subs"] = [{"entry": 1, "event": 6, "element_out": 3, "element_in": 7}]
    payloads[name] = json.dumps(document).encode()
    with pytest.raises(live.LiveWeekRefusal) as refused:
        live.prepare_live_week(
            replace(candidate, picks=replace(candidate.picks, payloads=payloads))
        )
    assert refused.value.code == "insufficient_coverage"
    assert refused.value.coverage == {
        "cohort_valid": 78,
        "cohort_excluded": 22,
        "cohort_exclusions": {
            "chip_unresolved": 1,
            "free_hit_previous_missing": 2,
            "unreadable": 18,
            "invalid_picks": 1,
            "missing_outcome": 0,
        },
        "cohort_chip_rosters": {"wildcard": 0, "freehit": 0},
    }


@pytest.mark.parametrize("chip", ["freehit", "unknown"])
def test_unresolved_roster_chips_cannot_silently_count_toward_coverage(chip):
    document = {"active_chip": chip}
    with pytest.raises(live.UnresolvedChipError, match="no captured roster"):
        live._original_picks(json.dumps(document).encode(), entry_id=1, gameweek=6)


def _play_chip(payloads, entries, gameweek, chip, captain=None):
    """Set an active chip, and optionally a new captain and vice, on captured picks."""
    for entry in entries:
        name = f"entry-{entry}-picks-gw{gameweek:02d}.json"
        document = json.loads(payloads[name])
        document["active_chip"] = chip
        if captain is not None:
            for row in document["picks"]:
                row["is_captain"] = row["element"] == captain[0]
                row["is_vice_captain"] = row["element"] == captain[1]
                row["multiplier"] = (
                    (3 if chip == "3xc" else 2)
                    if row["element"] == captain[0]
                    else int(row["position"] <= 11 or chip == "bboost")
                )
        payloads[name] = json.dumps(document).encode()


def test_wildcard_entry_scores_its_captured_roster_and_keeps_the_week():
    # 21 Wildcard entries left a week below 80 valid members when every chip was refused.
    candidate = week(event_points=DISTINCT_POINTS)
    payloads = dict(candidate.picks.payloads)
    _play_chip(payloads, range(1001, 1022), 6, "wildcard", captain=(14, 13))
    prepared = live.prepare_live_week(
        replace(candidate, picks=replace(candidate.picks, payloads=payloads))
    )
    assert prepared.provenance["cohort_valid"] == 100
    assert prepared.provenance["cohort_excluded"] == 0
    assert prepared.provenance["cohort_chip_rosters"] == {"wildcard": 21, "freehit": 0}
    wildcard, normal = prepared.managers[0], prepared.managers[21]
    assert (wildcard.captain_id, normal.captain_id) == (1014, 1008)
    # The captured Wildcard roster scores its own captain: 88 from the XI and the
    # autosub, plus 14 for the captain, against 88 plus 8 for an entry without a chip.
    assert live._score(wildcard, prepared.outcomes)["points"] == 102
    assert live._score(normal, prepared.outcomes)["points"] == 96


def test_settled_autosub_positions_restore_the_original_captain_and_bench():
    candidate = week(coverage=80)
    payloads = dict(candidate.picks.payloads)
    for entry in range(1001, 1081):
        name = f"entry-{entry}-picks-gw06.json"
        document = json.loads(payloads[name])
        rows = {row["element"]: row for row in document["picks"]}
        rows[3]["position"], rows[7]["position"] = rows[7]["position"], rows[3]["position"]
        for row in rows.values():
            row["is_captain"] = row["element"] == 3
            row["is_vice_captain"] = row["element"] == 8
            row["multiplier"] = 2 if row["element"] == 8 else int(row["position"] <= 11)
        document["automatic_subs"] = [
            {"entry": entry, "event": 6, "element_out": 3, "element_in": 7}
        ]
        payloads[name] = json.dumps(document).encode()
    prepared = live.prepare_live_week(
        replace(candidate, picks=replace(candidate.picks, payloads=payloads))
    )
    original = prepared.managers[0]
    assert original.captain_id == 1003 and original.starting_xi[1] == 1003
    assert original.bench == (1002, 1007, 1012, 1015)
    scored = live._score(original, prepared.outcomes)
    assert scored["vice_captain_recovery"] == 1 and scored["points"] == 12


def test_failed_claimed_reading_cannot_be_looked_at_again(tmp_path, monkeypatch):
    weeks = [week(gameweek) for gameweek in range(7, 15)]
    monkeypatch.setattr(
        live, "_score", lambda *a: (_ for _ in ()).throw(OSError("synthetic failure"))
    )
    with pytest.raises(OSError, match="synthetic failure"):
        read(weeks, tmp_path)
    claim = json.loads((tmp_path / live.CLAIM_FILE).read_bytes())
    assert claim["declared_gameweeks"] == {"first_gameweek": 7, "last_gameweek": 14}
    assert claim["manifest_sha256"] == "c" * 64
    monkeypatch.setattr(
        live, "prepare_live_week", lambda *_: pytest.fail("Second input was opened")
    )
    with pytest.raises(EvaluationValidationError, match="already been claimed"):
        read(weeks, tmp_path)


def _with_picks(candidate, payloads):
    return replace(candidate, picks=replace(candidate.picks, payloads=payloads))


def _set_previous_roster(payloads, entries, gameweek):
    """Captain the goalkeeper and put element 15 first among outfield substitutes.

    The first entry's settled picks also carry the autosub FPL made for that bench order.
    """
    for entry in entries:
        name = f"entry-{entry}-picks-gw{gameweek:02d}.json"
        document = json.loads(payloads[name])
        rows = {row["element"]: row for row in document["picks"]}
        rows[15]["position"], rows[7]["position"] = 13, 15
        if entry == entries[0]:
            rows[3]["position"], rows[15]["position"] = rows[15]["position"], rows[3]["position"]
            document["automatic_subs"] = [
                {"entry": entry, "event": gameweek, "element_out": 3, "element_in": 15}
            ]
        for row in rows.values():
            row["is_captain"] = row["element"] == 1
            row["is_vice_captain"] = row["element"] == 9
            row["multiplier"] = 2 if row["element"] == 1 else int(row["position"] <= 11)
        payloads[name] = json.dumps(document).encode()


def test_free_hit_entry_scores_the_roster_it_reverts_to():
    previous = week(7, event_points=DISTINCT_POINTS)
    payloads = dict(previous.picks.payloads)
    _set_previous_roster(payloads, list(range(1001, 1022)), 7)
    previous = _with_picks(previous, payloads)
    current = week(8, event_points=DISTINCT_POINTS)
    payloads = dict(current.picks.payloads)
    # The Free Hit roster itself would score 102 with element 14 as captain.
    _play_chip(payloads, range(1001, 1022), 8, "freehit", captain=(14, 13))
    prepared = live.prepare_live_week(_with_picks(current, payloads), previous)
    assert prepared.provenance["cohort_valid"] == 100
    assert prepared.provenance["cohort_chip_rosters"] == {"wildcard": 0, "freehit": 21}
    assert prepared.provenance["previous_picks"] == {
        "snapshot_id": previous.picks.metadata.snapshot_id,
        "fingerprint": previous.picks.metadata.fingerprint,
        "captured_at_utc": previous.picks.metadata.captured_at_utc,
    }
    reverted, normal = prepared.managers[0], prepared.managers[21]
    # GW7's autosub is reversed, so the XI and bench are the ones the manager set.
    assert 1003 in reverted.starting_xi and 1015 not in reverted.starting_xi
    assert reverted.bench == (1002, 1015, 1012, 1007)
    assert (reverted.captain_id, reverted.vice_captain_id) == (1001, 1009)
    # Scored against GW8 outcomes: 81 from the XI, 15 from the first legal substitute
    # for the absent element 3, and 1 for the goalkeeper captain.
    scores = [live._score(manager, prepared.outcomes)["points"] for manager in prepared.managers]
    assert scores[:21] == [97] * 21
    assert live._score(normal, prepared.outcomes)["points"] == 96


@pytest.mark.parametrize(
    "absence", ["no_previous_week", "absent_member", "other_cohort", "early", "other_week"]
)
def test_free_hit_without_previous_picks_is_counted_never_guessed(absence):
    previous = week(7, coverage=90 if absence == "absent_member" else 100)
    if absence == "other_cohort":
        binding = {"season": "2026-27", "gameweek": 7, "cohort_snapshot_id": "other"}
        previous = _with_picks(
            previous,
            {**previous.picks.payloads, "benchmark.json": json.dumps(binding).encode()},
        )
    elif absence == "early":
        previous = replace(previous, picks=_restamp(previous.picks, "2026-10-17T09:59:59Z"))
    elif absence == "other_week":
        previous = week(6)
    current = week(8)
    payloads = dict(current.picks.payloads)
    _play_chip(payloads, range(1091, 1101), 8, "freehit")
    prepared = live.prepare_live_week(
        _with_picks(current, payloads), None if absence == "no_previous_week" else previous
    )
    assert prepared.provenance["cohort_valid"] == 90
    assert prepared.provenance["cohort_exclusions"]["free_hit_previous_missing"] == 10
    assert prepared.provenance["cohort_chip_rosters"]["freehit"] == 0
    assert (prepared.provenance["previous_picks"] is not None) == (absence == "absent_member")


def test_free_hit_after_a_free_hit_has_no_roster_to_revert_to():
    previous = week(7)
    payloads = dict(previous.picks.payloads)
    _play_chip(payloads, range(1091, 1101), 7, "freehit")
    previous = _with_picks(previous, payloads)
    current = week(8)
    payloads = dict(current.picks.payloads)
    _play_chip(payloads, range(1091, 1101), 8, "freehit")
    prepared = live.prepare_live_week(_with_picks(current, payloads), previous)
    assert prepared.provenance["cohort_valid"] == 90
    assert prepared.provenance["cohort_exclusions"]["chip_unresolved"] == 10
    assert prepared.provenance["cohort_exclusions"]["free_hit_previous_missing"] == 0


def test_chip_heavy_week_stays_paired_and_a_first_week_free_hit_is_counted(tmp_path):
    weeks = {gameweek: week(gameweek) for gameweek in range(7, 16)}
    # GW7's previous week is outside the reading, so its Free Hit entries have no roster.
    payloads = dict(weeks[7].picks.payloads)
    _play_chip(payloads, range(1001, 1022), 7, "freehit")
    weeks[7] = _with_picks(weeks[7], payloads)
    # GW10 is chip heavy: 30 Free Hits revert to GW9 and 21 Wildcards keep their roster.
    payloads = dict(weeks[10].picks.payloads)
    _play_chip(payloads, range(1001, 1031), 10, "freehit")
    _play_chip(payloads, range(1031, 1052), 10, "wildcard")
    weeks[10] = _with_picks(weeks[10], payloads)
    result = read(list(weeks.values()), tmp_path)
    assert result["paired_gameweeks"] == 8
    assert [row["gameweek"] for row in result["rows"]] == list(range(8, 16))
    (excluded,) = result["exclusions"]
    assert (excluded["gameweek"], excluded["reason"]) == (7, "insufficient_coverage")
    assert excluded["cohort_exclusions"]["free_hit_previous_missing"] == 21
    chip_week = next(row for row in result["rows"] if row["gameweek"] == 10)
    assert chip_week["provenance"]["cohort_valid"] == 100
    assert chip_week["provenance"]["cohort_chip_rosters"] == {"wildcard": 21, "freehit": 30}
    assert chip_week["provenance"]["previous_picks"] is not None
