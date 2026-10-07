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


def week(gameweek=6, coverage=100):
    base = _parity_snapshot()
    boot = json.loads(base.payloads[BOOTSTRAP_PAYLOAD])
    deadline = datetime(2026, 10, 10, 10, tzinfo=UTC) + timedelta(weeks=gameweek - 6)

    def stamp(hours):
        return (deadline + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")

    boot["events"][0].update(
        id=gameweek, deadline_time=stamp(0), finished=False, data_checked=False
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
        picks_data[f"entry-{entry}-picks-gw{gameweek:02d}.json"] = base.payloads[
            "entry-99-picks-gw01.json"
        ]
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
        "captain_player_id": 1008,
        "vice_captain_player_id": 1009,
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


def read(weeks, root):
    return live.read_live_benchmark_once(
        weeks, record_root=root, repository_commit="a" * 40, preregistration_sha256="b" * 64
    )


def test_early_reading_refuses_before_preparing_or_scoring(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "prepare_live_week", lambda _: pytest.fail("Early input was opened"))
    with pytest.raises(EvaluationValidationError, match="eight valid"):
        read([week()] * 7, tmp_path)
    assert not (tmp_path / live.CLAIM_FILE).exists()


def test_eight_weeks_pair_all_arms_and_second_reading_opens_nothing(tmp_path, monkeypatch):
    weeks = [week(gameweek) for gameweek in range(6, 14)]
    result = read(list(reversed(weeks)), tmp_path)
    assert result["paired_gameweeks"] == 8
    assert [row["gameweek"] for row in result["rows"]] == list(range(6, 14))
    assert all(row["system"]["points"] == row["cohort"]["points"] == 12 for row in result["rows"])
    assert result["summary"]["mean_system_minus_cohort"] == 0
    assert json.loads((tmp_path / live.READING_FILE).read_bytes()) == result
    assert (tmp_path / live.READING_FILE.replace(".json", ".md")).exists()
    monkeypatch.setattr(live, "prepare_live_week", lambda _: pytest.fail("Second input was opened"))
    with pytest.raises(EvaluationValidationError, match="already been claimed"):
        read(weeks, tmp_path)


def test_coverage_below_eighty_cannot_make_a_valid_eighth_week(tmp_path):
    weeks = [week(gameweek) for gameweek in range(6, 13)] + [week(13, 79)]
    with pytest.raises(EvaluationValidationError, match="eight valid"):
        read(weeks, tmp_path)
    assert not (tmp_path / live.CLAIM_FILE).exists()


@pytest.mark.parametrize("damage", ["late_freeze", "wrong_cohort", "unchecked", "changed_decision"])
def test_invalid_week_is_refused_before_a_reading(damage):
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
    with pytest.raises(EvaluationValidationError):
        live.prepare_live_week(candidate)


def test_exactly_eighty_valid_members_pass_without_backfilling():
    prepared = live.prepare_live_week(week(coverage=80))
    assert len(prepared.managers) == 80
    assert prepared.provenance["cohort_excluded"] == 20
    assert prepared.provenance["solver_configuration"] == {
        "deterministic_time_limit": 5.0,
        "wall_time_limit_seconds": 600.0,
        "binding_limit": "deterministic_time",
    }


@pytest.mark.parametrize("chip", ["freehit", "wildcard", "unknown"])
def test_unresolved_roster_chips_cannot_silently_count_toward_coverage(chip):
    document = {"active_chip": chip}
    with pytest.raises(EvaluationValidationError, match="protocol decision"):
        live._original_picks(json.dumps(document).encode(), entry_id=1, gameweek=6)


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
    weeks = [week(gameweek) for gameweek in range(6, 14)]
    monkeypatch.setattr(
        live, "_score", lambda *a: (_ for _ in ()).throw(OSError("synthetic failure"))
    )
    with pytest.raises(OSError, match="synthetic failure"):
        read(weeks, tmp_path)
    assert (tmp_path / live.CLAIM_FILE).exists()
    monkeypatch.setattr(live, "prepare_live_week", lambda _: pytest.fail("Second input was opened"))
    with pytest.raises(EvaluationValidationError, match="already been claimed"):
        read(weeks, tmp_path)
