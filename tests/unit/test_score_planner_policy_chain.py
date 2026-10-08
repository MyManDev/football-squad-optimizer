"""The chain's scorer reads the runner's evidence and the season's outcomes by the protocol's rules.

The worlds here are synthetic: the runner decides stubbed arms into a real evidence directory,
and outcome captures are written with the payloads the scorer reads. No real capture, archive
or live store is touched.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from scripts import measure_planner_policy_chain as chain
from scripts import score_planner_policy_chain as scorer
from tests.unit.test_live_transfers import CHIPS, _game_config
from tests.unit.test_planner_policy_chain import (
    POSITIONS,
    PROTOCOL_TEXT,
    SQUAD,
    T0,
    _chain_world,
    _outcome,
    _plan,
    _plan_week,
    _state,
    _week,
)

from squadopt.data.atomic import document_bytes
from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, live_payload
from squadopt.evaluation.live_series import DetectionPolicy, detectable_effect
from squadopt.evaluation.promotion import PromotionPolicy
from squadopt.evaluation.statistics import season_aware_moving_block_interval

#: A legal eleven over the synthetic squad: one goalkeeper, four defenders, four midfielders,
#: two forwards; the bench holds the second goalkeeper, a defender, a midfielder and a forward.
STARTERS = [1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14]
BENCH = [2, 7, 12, 15]
ROSTER = (*SQUAD, 16, 17)
CAPTAINS = {"served": 8, "hold": 10, "one_week": 11}
#: Realized points: the served captain scores ten, hold's captain two, one_week's one.
POINTS = {player: 2 for player in ROSTER} | {8: 10, 10: 2, 11: 1}
#: The game's position codes in a bootstrap's elements.
ELEMENT_TYPES = {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}
#: Every outcome capture prices each player two tenths above the price the chains bought him at
#: (rule 10), so under the captured fee of 0.5 a sale keeps one tenth of the rise (rule 18).
RISE = 2
#: The frozen commit the synthetic chain was decided from, as the operator posts it (rule 24).
FROZEN = "b" * 40
#: Rule 3: what the runner records at the frozen commit, as the chain's protocol.json carries it.
IDENTITY: dict[str, object] = {
    "protocol": scorer.PROTOCOL_ID,
    "repository_commit": FROZEN,
    "protocol_sha256": "1" * 64,
    "runner_sha256": "2" * 64,
    "binding_commits": {
        "protocol": {
            "commit": "a" * 40,
            "committed_utc": "2026-10-06T12:00:00+00:00",
            "line_position": "1",
        },
        "runner": {
            "commit": FROZEN,
            "committed_utc": "2026-10-08T09:00:00+00:00",
            "line_position": "2",
        },
    },
}
#: The receipts file each world writes beside its evidence, as the operator transcribes it.
RECEIPTS = "receipts.json"
#: Rule 6's three admitted model versions, and one its reader accepts that it does not admit.
TEAM_SHARE = "football_team_share_v1"
MINUTES = "football_joint_role_minutes_v1"
RETAINED = "football_joint_role_retained_history_v1"
NOT_ADMITTED = "football_contextual_v3"
#: The line the runner prints for each week it decides, which the operator posts (rule 24).
DECIDED = re.compile(r"GW(\d{2}) decided from .+; manifest sha256 ([0-9a-f]{64})")
#: Rule 30's numbers and rule 33's rates, built here rather than read from the scorer, so that a
#: constant changed there cannot agree with itself.
STATED_POLICY = PromotionPolicy(
    min_mean_improvement=0.5,
    confidence_level=0.90,
    bootstrap_resamples=5000,
    moving_block_length=4,
    deterministic_seed=0,
)
STATED_DETECTION = DetectionPolicy(confidence_level=0.90, power=0.80)
#: What a served window pays in paid transfers, week by week. Only the first week is played
#: (rule 17), so only a scorer that charges a later week would see the two.
SERVED_PAID = (1, 2, 0, 0, 0)


def _lineup(captain: int) -> dict[str, object]:
    return {
        "starting_xi": list(STARTERS),
        "bench": list(BENCH),
        "captain": captain,
        "vice_captain": 9,
        "chip": None,
        "transfer_hit_points": 0.0,
        "scoring_complete": True,
    }


def _deadline(gameweek: int):
    return T0 + timedelta(days=7 * (gameweek - 6))


def _stamp(moment) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _bootstrap(settled_through: int) -> bytes:
    events = [
        {
            "id": gameweek,
            "deadline_time": _stamp(_deadline(gameweek)),
            "finished": gameweek <= settled_through,
            "data_checked": gameweek <= settled_through,
        }
        for gameweek in range(1, 39)
    ]
    # A whole roster, as a capture's bootstrap carries it: names, clubs, positions, prices and
    # availability, so every reader of a capture reads these as it reads a real one.
    elements = [
        {
            "id": player + 100,
            "code": player,
            "first_name": "Player",
            "second_name": str(player),
            "team": 1 + player % 5,
            "element_type": ELEMENT_TYPES[POSITIONS[player]],
            "now_cost": 50 + player + RISE,
            "status": "a",
            "chance_of_playing_next_round": None,
            "news_added": None,
        }
        for player in ROSTER
    ]
    teams = [{"id": team, "name": f"Club {team}"} for team in range(1, 6)]
    document = {
        "events": events,
        "teams": teams,
        "elements": elements,
        "game_config": _game_config(),
        "chips": CHIPS,
    }
    return json.dumps(document).encode("utf-8")


def _live(points: dict[int, int]) -> bytes:
    return json.dumps(
        {
            "elements": [
                {"id": player + 100, "stats": {"total_points": value, "minutes": 90, "starts": 1}}
                for player, value in points.items()
            ]
        }
    ).encode("utf-8")


def _outcome_capture(
    root: Path,
    gameweek: int,
    *,
    settled_through: int | None = None,
    hours_after: float = 5.0,
    live: bool = True,
    points: dict[int, int] | None = None,
) -> str:
    payloads = {
        BOOTSTRAP_PAYLOAD: _bootstrap(gameweek if settled_through is None else settled_through)
    }
    if live:
        payloads[live_payload(gameweek)] = _live(POINTS if points is None else points)
    metadata = write_snapshot(
        root,
        source="fpl-live",
        captured_at_utc=_stamp(_deadline(gameweek) + timedelta(hours=hours_after)),
        payloads=payloads,
    )
    return metadata.snapshot_id


def _arm_outcome(name: str, gameweek: int, *, paid: Sequence[int] = (0,)) -> chain.ArmOutcome:
    """One arm's stubbed decision: a plan over the arm's whole window, cut at GW38 and labelled
    truncated by the runner's own rule (rule 14), whose weeks pay ``paid`` transfers in turn and
    none after. Only the first week is played (rule 17)."""

    weeks = chain.window_weeks(name, gameweek)
    first = _plan_week(gameweek=gameweek)
    # Each later week keeps the first week's team, so it is built once.
    planned = [SimpleNamespace(**{**vars(first), "gameweek": week}) for week in weeks]
    for week, count in zip(planned, paid, strict=False):
        week.paid_transfer_count = count
    outcome = _outcome(_plan(planned[0]))
    outcome.plan.weeks = tuple(planned)
    outcome.weeks = weeks
    family = "one_week" if name == "one_week" else name.split("_")[0]
    outcome.lineup = _lineup(CAPTAINS[family])
    outcome.truncated = len(weeks) < chain._width(name)
    return outcome


def _post(receipts: Path, lines: Sequence[str]) -> None:
    """The operator's receipts (rule 24): the frozen commit, and each week's manifest sha256 as
    the runner printed it, each named by the comment that carries it."""

    manifests = {
        f"gw{week}": {"sha256": digest, "posted": f"issuecomment-{week}"}
        for line in lines
        if (match := DECIDED.fullmatch(line))
        for week, digest in [match.groups()]
    }
    document = {
        "tracking_issue": "https://github.com/MyManDev/football-squad-optimizer/issues/1",
        "frozen_commit": {"commit": FROZEN, "posted": "issuecomment-0"},
        "manifests": manifests,
    }
    receipts.write_text(json.dumps(document), encoding="utf-8")


def _rewrite(path: Path, change: Callable[[dict[str, Any]], object]) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(json.dumps(document), encoding="utf-8")


def _repost(receipts: Path, evidence: Path, gameweek: int) -> None:
    """Post a week's manifest sha256 again, as the manifest now stands on disk."""

    name = f"gw{gameweek:02d}"
    digest = hashlib.sha256((evidence / name / "manifest.json").read_bytes()).hexdigest()
    _rewrite(receipts, lambda document: document["manifests"][name].update(sha256=digest))


def _reseal(evidence: Path, gameweek: int) -> None:
    """Rewrite a week's manifest over its files as they now stand, as a runner that wrote those
    files would have: each listed record's digest and the week's evidence_digest."""

    directory = evidence / f"gw{gameweek:02d}"

    def seal(manifest: dict[str, Any]) -> None:
        manifest["records"] = {
            name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
            for name in manifest["records"]
        }
        manifest["evidence_digest"] = scorer.evidence_digest(directory)

    _rewrite(directory / "manifest.json", seal)


def _rewrite_week(
    evidence: Path, receipts: Path, gameweek: int, change: Callable[[dict[str, Any]], object]
) -> None:
    """Change every chain record of one decided week, then reseal its manifest and post its
    sha256 again, so the week reads as one the runner wrote and the operator posted that way."""

    for path in (evidence / f"gw{gameweek:02d}").glob("p*-*.json"):
        _rewrite(path, change)
    _reseal(evidence, gameweek)
    _repost(receipts, evidence, gameweek)


def _read_through(monkeypatch: pytest.MonkeyPatch, gameweek: int) -> None:
    """A gw20 reading over the chain's first weeks only, through ``gameweek``, so a test need not
    decide fifteen weeks."""

    read = scorer.read_evidence
    monkeypatch.setattr(
        scorer, "read_evidence", lambda root, through, posted: read(root, gameweek, posted)
    )


def _world(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    through: int = 20,
    missing: tuple[int, ...] = (),
    failing: tuple[tuple[str, int], ...] = (),
    receipt_fields: dict[int, dict[str, object]] | None = None,
    unproved: tuple[tuple[str, int], ...] = (),
    blocked_from: int | None = None,
    without_live: tuple[int, ...] = (),
    points: Callable[[int], dict[int, int]] | None = None,
    settled_through: int | None = None,
) -> tuple[Path, Path, Path]:
    """A decided chain from GW6 through ``through``: each served window pays one transfer in
    its played first week and two in its second (``SERVED_PAID``), and each window, failed or
    not, is cut at GW38 and truncated by the runner's own rule (rule 14).

    The runner starts the chain before GW21's deadline, as rule 40 requires, and decides any
    later week in a second run. The operator posts the frozen commit and every manifest sha256
    the runner prints, written to ``tmp_path / RECEIPTS`` (rule 24). ``receipt_fields`` adds
    fields to a week's receipt.json, by gameweek; a missing week's ``reason`` is its missing
    reason, and a decided week's ``model_version`` is also its forecast's, as the runner writes
    it into each decided record. An ``unproved`` arm's plan that week is published FEASIBLE and
    not proved. From ``blocked_from`` on the roster lacks player 15, whom every chain holds, so
    every chain is blocked. An outcome capture is written for each week through
    ``settled_through`` (``through`` when not given), with ``points`` of that gameweek as its
    realized points (``POINTS`` when not given), and without its live payload in a week of
    ``without_live``.
    """

    weeks: dict[int, object] = {}
    for gameweek in range(6, through + 1):
        fields = (receipt_fields or {}).get(gameweek, {})
        if gameweek in missing:
            reason = str(fields.get("reason", "no_artifact"))
            weeks[gameweek] = (reason, {"snapshot_id": None, "reason": reason, **fields})
        else:
            blocked = blocked_from is not None and gameweek >= blocked_from
            roster = tuple(player for player in ROSTER if not (blocked and player == 15))
            decided = _week(gameweek, roster=roster)
            forecast = decided.forecast
            if "model_version" in fields:
                horizon = SimpleNamespace(model_version=fields["model_version"])
                forecast = SimpleNamespace(**{**vars(forecast), "horizon": horizon})
            # Rule 36: a decided week's receipt carries the deadline its capture states.
            weeks[gameweek] = replace(
                decided,
                receipt={
                    **decided.receipt,
                    "deadline_utc": _stamp(_deadline(gameweek)),
                    **fields,
                },
                forecast=forecast,
            )
    evidence, _ = _chain_world(tmp_path, monkeypatch, weeks)
    monkeypatch.setattr(chain, "source_identity", lambda: dict(IDENTITY))
    states = {f"p{budget}": _state(decided=5) for budget, _, _ in chain.PROFILES}
    for state in states.values():
        object.__setattr__(state, "lineup", _lineup(CAPTAINS["hold"]))
    squads = chain.Squads(states, {}, {profile: ["OPTIMAL"] for profile in states})
    monkeypatch.setattr(chain, "initial_states", lambda forecast, week: squads)

    def arm(name: str, week: chain.WeekInputs, held: object) -> chain.ArmOutcome:
        gameweek = int(week.inputs.deadline.gameweek)
        if (name, gameweek) in failing:
            # The runner gives a failing arm its own window and rule 14's truncation too.
            failed = _outcome(None, failure="raised_ValueError")
            failed.weeks = chain.window_weeks(name, gameweek)
            failed.truncated = len(failed.weeks) < chain._width(name)
            return failed
        outcome = _arm_outcome(
            name, gameweek, paid=SERVED_PAID if name.startswith("served") else (0,)
        )
        if (name, gameweek) in unproved:
            outcome.status = {"solver_status": "FEASIBLE", "proved": False}
        return outcome

    monkeypatch.setattr(chain, "run_arm", arm)
    snapshots, artifacts = tmp_path / "snapshots", tmp_path / "football"
    (artifacts / "football").mkdir(parents=True)
    snapshots.mkdir()
    printed: list[str] = []
    for last in sorted({min(through, chain.LAPSE_GAMEWEEK - 1), through}):
        chain.decide(
            snapshots,
            artifacts,
            evidence,
            last,
            "issuecomment-1",
            now=_deadline(last) + timedelta(hours=1),
            emit=printed.append,
        )
    _post(tmp_path / RECEIPTS, printed)
    for gameweek in range(6, (through if settled_through is None else settled_through) + 1):
        _outcome_capture(
            snapshots,
            gameweek,
            live=gameweek not in without_live,
            points=None if points is None else points(gameweek),
        )
    return evidence, snapshots, tmp_path / "records"


def _identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """The scorer's identity, its checks for a reading taken already, origin's release tags and
    the frozen source, stubbed: no git runs. The final reading's interim record is refused until
    a test names one (``_on_develop``), so no test reads the repository's own develop."""

    def no_interim() -> scorer.InterimRecord:
        raise scorer.ScorerError("This test names no interim record.")

    monkeypatch.setattr(
        scorer,
        "source_identity",
        lambda: {"scorer_merge_commit": "c" * 40, "scorer_sha256": "d" * 64},
    )
    monkeypatch.setattr(scorer, "committed_reading", lambda reading: None)
    monkeypatch.setattr(scorer, "written_reading", lambda reading: None)
    monkeypatch.setattr(scorer, "release_tags", lambda: ())
    monkeypatch.setattr(scorer, "interim_reading", no_interim)
    # The frozen source is read again from git at the frozen commit; that has its own tests.
    monkeypatch.setattr(scorer, "check_frozen_source", lambda protocol, **roots: None)
    monkeypatch.setattr(
        scorer,
        "release_binding",
        lambda deadline, frozen, tags: {
            "release_tag": "site-2026-27-gw06-fix16",
            "planner_source_same": True,
            "binding_source_same": frozen == FROZEN,
        },
    )


def _on_develop(monkeypatch: pytest.MonkeyPatch, records: Path) -> scorer.InterimRecord:
    """Rule 25: the interim record as develop on origin holds it once merged, the gw20 JSON this
    world's own interim reading wrote, under stub commits."""

    raw = (records / "planner_policy_chain_gw20.json").read_bytes()
    interim = scorer.InterimRecord(
        record=json.loads(raw),
        added_commit="a" * 40,
        develop_commit="e" * 40,
        sha256=hashlib.sha256(raw).hexdigest(),
    )
    monkeypatch.setattr(scorer, "interim_reading", lambda: interim)
    return interim


def _correction(root: Path, through: int, corrected: dict[int, dict[int, int]]) -> str:
    """A capture taken a day after GW``through``'s deadline that holds every played week's live
    payload, as live captures do, with the points of the ``corrected`` weeks corrected. It is
    the latest capture with each of those weeks' live payloads, so it becomes each week's
    outcome capture (rule 25)."""

    payloads = {BOOTSTRAP_PAYLOAD: _bootstrap(through)}
    for gameweek in range(6, through + 1):
        payloads[live_payload(gameweek)] = _live(corrected.get(gameweek, POINTS))
    return write_snapshot(
        root,
        source="fpl-live",
        captured_at_utc=_stamp(_deadline(through) + timedelta(hours=30)),
        payloads=payloads,
    ).snapshot_id


def _players() -> dict[str, dict[str, object]]:
    """A record's players block over the synthetic roster, as score_recorded_advice reads it."""

    return {
        str(player): {"name": f"Player {player}", "position": position, "expected_points": 2.0}
        for player, position in zip(
            ROSTER,
            ["GK", "GK", *["DEF"] * 5, *["MID"] * 5, *["FWD"] * 3, "MID", "DEF"],
            strict=True,
        )
    }


def _outcomes() -> Any:
    """Every player of the roster scores two in ninety minutes."""

    import pandas as pd

    return pd.DataFrame(
        {
            "player_id": list(ROSTER),
            "total_points": [2] * len(ROSTER),
            "minutes": [90] * len(ROSTER),
        }
    )


def _stated_interval(series: Sequence[float], candidate: str, *, blocks: int = 4) -> list[float]:
    """Rule 30's interval on ``series``, computed here under the stated numbers."""

    return list(
        season_aware_moving_block_interval(
            [("2026-27", value) for value in series],
            policy=replace(STATED_POLICY, moving_block_length=blocks),
            candidate_id=candidate,
        )
    )


def _verdicts(node: object, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], object]]:
    """Every verdict a record holds, by its path in the record."""

    if isinstance(node, dict):
        found = [(path, node["verdict"])] if "verdict" in node else []
        for key, value in node.items():
            found += _verdicts(value, (*path, str(key)))
        return found
    if isinstance(node, list):
        return [
            item
            for index, value in enumerate(node)
            for item in _verdicts(value, (*path, str(index)))
        ]
    return []


@pytest.fixture(scope="module")
def two_readings(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Both readings of one chain decided from GW6 through GW38, each taken once.

    At the interim GW15 is unscored: two distinct captures tie as its latest. Between the
    readings a capture is taken that holds every played week's live payload and corrects GW12,
    where player 8, the served captain, scored 4 and not 10. The final reading reads the interim
    record as develop holds it.
    """

    tmp_path = tmp_path_factory.mktemp("two_readings")
    with pytest.MonkeyPatch.context() as monkeypatch:
        evidence, snapshots, records = _world(tmp_path, monkeypatch, through=38)
        tied = _outcome_capture(snapshots, 15, points={player: 3 for player in ROSTER})
        _identity(monkeypatch)
        index = tmp_path / "index.md"
        index.write_text("# Measurements Index\n", encoding="utf-8")
        paths = {"receipts": tmp_path / RECEIPTS, "records_dir": records, "index_file": index}
        interim = scorer.score(evidence, snapshots, "gw20", **paths)
        correction = _correction(snapshots, 21, {12: POINTS | {8: 4}})
        on_develop = _on_develop(monkeypatch, records)
        final = scorer.score(evidence, snapshots, "gw38", **paths)
    return {
        **paths,
        "interim": interim,
        "final": final,
        "on_develop": on_develop,
        "tied": tied,
        "correction": correction,
    }


# Rules 25 to 30: a reading over fifteen decided weeks


def test_the_interim_reading_scores_every_week_and_pairs_the_arms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence, snapshots, records = _world(tmp_path, monkeypatch)
    _identity(monkeypatch)
    index = tmp_path / "index.md"
    index.write_text("# Measurements Index\n\n- [other](x.json): a row.\n", encoding="utf-8")
    record = scorer.score(
        evidence,
        snapshots,
        "gw20",
        receipts=tmp_path / RECEIPTS,
        records_dir=records,
        index_file=index,
    )
    assert record["final"] is False and record["outcome_read"] is True
    assert record["locked_holdout_accessed"] is False
    assert record["once_rule"] == scorer.ONCE_RULE
    assert record["release_rule"] == scorer.RELEASE_RULE and record["release_tags"] == []
    assert [week["gameweek"] for week in record["weeks"]] == list(range(6, 21))
    assert all(week["scored_chains"] == 15 for week in record["weeks"])
    assert all(week["release"]["binding_source_same"] is True for week in record["weeks"])
    # The served captain scores ten and pays one transfer at four points: 39 - 4 against
    # hold's 31 and one_week's 30, so A is +4 and B is +5 in every week and every pair.
    primary_a = record["contrasts"]["A"]["primary"]
    primary_b = record["contrasts"]["B"]["primary"]
    assert primary_a["weeks"] == 15 and primary_a["pairs"] == 15 * 6
    assert primary_a["mean"] == pytest.approx(4.0)
    assert primary_b["mean"] == pytest.approx(5.0)
    assert primary_a["interval"] == pytest.approx([4.0, 4.0])
    assert primary_a["interval_blocks_of_8"] == pytest.approx([4.0, 4.0])
    assert primary_a["standard_deviation"] == pytest.approx(0.0)
    assert primary_a["detectable_effect"] is None
    assert primary_a["exact_zero_pairs"] == 0
    assert primary_a["verdict"] is None and primary_b["verdict"] is None
    # Rule 32: the interim records no verdict, in any block.
    assert [value for _, value in _verdicts(record) if value is not None] == []
    # Rule 30's numbers, stated here, so that a constant changed in the scorer cannot echo itself.
    assert record["interval_policy"] == {
        "confidence_level": 0.90,
        "bootstrap_resamples": 5000,
        "moving_block_length": 4,
        "deterministic_seed": 0,
        "min_mean_improvement": 0.5,
        "min_weeks_for_interval": 6,
        "min_weeks_for_verdict": 15,
        "detection": {"confidence_level": 0.90, "power": 0.80},
    }
    # This world's receipts name no model version, so no version block opens.
    assert record["contrasts"]["A"]["by_model_version"] == {}
    assert record["secondary"]["hold_minus_one_week"]["mean"] == pytest.approx(1.0)
    assert record["secondary"]["A_window_3"]["weeks"] == 15
    # Rule 29: each squad, for A, B and hold minus one_week, on its own two pairs a week.
    for label, mean in (("A", 4.0), ("B", 5.0), ("hold_minus_one_week", 1.0)):
        squads = record["by_squad"][label]
        assert set(squads) == {"p1000", "p950", "p900"}
        for block in squads.values():
            assert block["weeks"] == 15 and block["pairs"] == 15 * 2
            assert block["mean"] == pytest.approx(mean) and block["verdict"] is None
    # Rule 25: each week keeps the weekly difference of each primary contrast.
    assert all(
        week["differences"]
        == {
            "A": {"difference": 4.0, "pairs": 6, "exact_zero_pairs": 0, "failed_pairs": 0},
            "B": {"difference": 5.0, "pairs": 6, "exact_zero_pairs": 0, "failed_pairs": 0},
        }
        for week in record["weeks"]
    )
    assert record["changed_since_interim"] is None
    assert record["totals"]["paired_differences"]["A"]["net_points"] == pytest.approx(
        2 * 15 * 3 * 4.0
    )
    assert "by_arm" not in record["totals"]
    assert record["choices"] == scorer.CHOICES
    written = json.loads((records / "planner_policy_chain_gw20.json").read_text(encoding="utf-8"))
    assert written == record
    twin = (records / "planner_policy_chain_gw20.md").read_text(encoding="utf-8")
    assert "+4.000" in twin and "+5.000" in twin and "none (interim)" in twin
    # The weeks table shows each week's differences of A and B beside its captures.
    assert "| Model version | Scored chains | A | B | Release tag |" in twin
    assert twin.count("| 15 | +4.000 | +5.000 | site-2026-27-gw06-fix16 | True | True |") == 15
    assert scorer.RELEASE_RULE in twin
    assert all(f"- `{name}`: {text}" in twin for name, text in scorer.CHOICES.items())
    index_text = index.read_text(encoding="utf-8")
    assert index_text.count("- [Planner policy chain, gw20 reading]") == 1
    assert index_text.startswith("# Measurements Index")


def test_a_held_or_blocked_chain_scores_nothing_even_with_a_lineup_on_record() -> None:
    """Rules 21 and 23: a missing week's hold and a blocked chain contribute no pair."""

    outcomes, players = _outcomes(), _players()
    for status in ("held", "blocked"):
        record = {"status": status, "advice": _lineup(8), "players": players, "plan": {"weeks": []}}
        assert scorer.score_chain_week(record, outcomes) is None
    decided = {
        "status": "decided",
        "advice": _lineup(8),
        "players": players,
        "plan": {"weeks": [{"paid_transfer_count": 1}]},
    }
    scored = scorer.score_chain_week(decided, outcomes)
    assert scored is not None and scored.hits == 4.0 and scored.net == scored.gross - 4.0


def test_a_week_without_its_digest_is_refused_and_each_record_is_held_to_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 36: the runner always writes a week's evidence_digest, so a manifest without one is
    refused, and each record is held to the digest its manifest lists even where the week's
    digest and the posted receipt agree with the files."""

    evidence, _, _ = _world(tmp_path, monkeypatch, through=6)
    receipts = tmp_path / RECEIPTS
    manifest_path = evidence / "gw06" / "manifest.json"
    pristine = manifest_path.read_bytes()
    _rewrite(manifest_path, lambda manifest: manifest.pop("evidence_digest"))
    _repost(receipts, evidence, 6)
    with pytest.raises(scorer.ScorerError, match="records no evidence_digest"):
        scorer.read_evidence(evidence, 6, scorer.read_receipts(receipts))
    manifest_path.write_bytes(pristine)
    _repost(receipts, evidence, 6)
    scorer.read_evidence(evidence, 6, scorer.read_receipts(receipts))
    path = evidence / "gw06" / "p1000-served_3.json"
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    digest = scorer.evidence_digest(evidence / "gw06")
    _rewrite(manifest_path, lambda manifest: manifest.update(evidence_digest=digest))
    _repost(receipts, evidence, 6)
    with pytest.raises(scorer.ScorerError, match="does not match the digest"):
        scorer.read_evidence(evidence, 6, scorer.read_receipts(receipts))

    # A week's files that cannot be read are a refusal, never a traceback.
    def unreadable(directory: Path) -> str:
        raise PermissionError(f"{directory.name} cannot be opened")

    monkeypatch.setattr(scorer, "evidence_digest", unreadable)
    with pytest.raises(scorer.ScorerError, match="GW06: the week's evidence cannot be read"):
        scorer.read_evidence(evidence, 6, scorer.read_receipts(receipts))


def test_hits_are_charged_at_four_per_paid_transfer_from_the_played_week() -> None:
    """Rule 26: the game's four points per paid transfer, never the planning cost of eight."""

    decided = {"status": "decided", "plan": {"weeks": [{"paid_transfer_count": 2}]}}
    assert scorer.paid_hits(decided) == 8.0
    assert (
        scorer.paid_hits({"status": "failed", "plan": {"weeks": [{"paid_transfer_count": 2}]}})
        == 0.0
    )
    assert scorer.paid_hits({"status": "decided", "plan": {"weeks": []}}) == 0.0


def test_only_the_played_first_week_of_a_longer_plan_is_charged() -> None:
    """Rules 17 and 26: a three-week plan paying one, two and no transfers is charged the game's
    four points for its first week's one paid transfer, never for a later week's."""

    plan = {
        "weeks": [
            {"gameweek": 6 + offset, "paid_transfer_count": paid}
            for offset, paid in enumerate((1, 2, 0))
        ]
    }
    assert scorer.paid_hits({"status": "decided", "plan": plan}) == 4.0
    decided = {"status": "decided", "advice": _lineup(8), "players": _players(), "plan": plan}
    scored = scorer.score_chain_week(decided, _outcomes())
    assert scored is not None and scored.hits == 4.0
    assert scored.net == scored.gross - 4.0


def test_a_failed_arm_is_scored_on_its_held_team_and_the_pair_is_also_reported_without_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 22: the failed week is scored and stays in the pairs; rule 29 reports it apart."""

    evidence, snapshots, records = _world(tmp_path, monkeypatch, failing=(("hold_3", 7),))
    _identity(monkeypatch)
    record = scorer.score(
        evidence,
        snapshots,
        "gw20",
        receipts=tmp_path / RECEIPTS,
        records_dir=records,
        index_file=tmp_path / "index.md",
    )
    primary = record["contrasts"]["A"]["primary"]
    without = record["contrasts"]["A"]["without_failed_weeks"]
    assert primary["pairs"] == 15 * 6 and without["pairs"] == 15 * 6 - 3
    # The held team is hold's lineup with no transfer, so the failed pair scores like hold's.
    assert primary["mean"] == pytest.approx(4.0) and without["mean"] == pytest.approx(4.0)
    week7 = next(week for week in record["weeks"] if week["gameweek"] == 7)
    assert week7["scored_chains"] == 15


def test_a_missing_week_is_listed_with_its_reason_and_enters_no_series(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 21: a missing week is not scored and is listed with its reason."""

    evidence, snapshots, records = _world(tmp_path, monkeypatch, missing=(8,))
    _identity(monkeypatch)
    record = scorer.score(
        evidence,
        snapshots,
        "gw20",
        receipts=tmp_path / RECEIPTS,
        records_dir=records,
        index_file=tmp_path / "index.md",
    )
    week8 = next(week for week in record["weeks"] if week["gameweek"] == 8)
    assert week8["missing_reason"] == "no_artifact" and week8["scored_chains"] == 0
    primary = record["contrasts"]["A"]["primary"]
    assert primary["weeks"] == 14 and 8 not in primary["weeks_listed"]
    assert all(8 not in block["weeks_listed"] for block in record["secondary"].values())
    assert all(
        8 not in block["weeks_listed"]
        for squads in record["by_squad"].values()
        for block in squads.values()
    )
    assert week8["differences"] == {"A": None, "B": None}
    assert record["truncated_weeks"]["A"]["weeks"] == 0


def test_a_truncated_pair_leaves_the_primary_and_its_week_stays_on_the_other_pairs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rules 14 and 29: at GW35 and GW36 only the five-week windows are truncated, so each
    contrast keeps those weeks on its three-week pairs and scores at most GW6 to GW36. The
    truncated block takes the truncated pairs only, and every other series takes the rest."""

    evidence, snapshots, records = _world(
        tmp_path, monkeypatch, through=38, missing=tuple(range(7, 34))
    )
    _identity(monkeypatch)
    paths = {
        "receipts": tmp_path / RECEIPTS,
        "records_dir": records,
        "index_file": tmp_path / "index.md",
    }
    # Rule 25: the final reading reads the interim record, so the interim is taken first.
    scorer.score(evidence, snapshots, "gw20", **paths)
    _on_develop(monkeypatch, records)
    record = scorer.score(evidence, snapshots, "gw38", **paths)
    truncated = {week["gameweek"]: week["truncated_arms"] for week in record["weeks"]}
    assert truncated[34] == []
    assert truncated[35] == truncated[36] == ["hold_5", "served_5"]
    assert truncated[37] == truncated[38] == ["hold_3", "hold_5", "served_3", "served_5"]
    secondary = record["secondary"]
    for label, mean in (("A", 4.0), ("B", 5.0)):
        contrast = record["contrasts"][label]
        for block in (contrast["primary"], contrast["without_failed_weeks"]):
            assert block["weeks_listed"] == [6, 34, 35, 36]
            assert block["pairs"] == 6 + 6 + 3 + 3
            assert block["mean"] == pytest.approx(mean)
        beside = record["truncated_weeks"][label]
        assert beside["weeks_listed"] == [35, 36, 37, 38]
        assert beside["pairs"] == 3 + 3 + 6 + 6
        assert beside["mean"] == pytest.approx(mean)
        assert secondary[f"{label}_window_3"]["weeks_listed"] == [6, 34, 35, 36]
        assert secondary[f"{label}_window_5"]["weeks_listed"] == [6, 34]
    hold_minus_one_week = secondary["hold_minus_one_week"]
    assert hold_minus_one_week["weeks_listed"] == [6, 34, 35, 36]
    assert hold_minus_one_week["pairs"] == 6 + 6 + 3 + 3
    for label in ("A", "B", "hold_minus_one_week"):
        assert set(record["by_squad"][label]) == {"p1000", "p950", "p900"}
        for block in record["by_squad"][label].values():
            assert block["weeks_listed"] == [6, 34, 35, 36] and block["pairs"] == 2 + 2 + 1 + 1
    # The truncated weeks keep no weekly difference of a primary contrast past GW36.
    weekly = {week["gameweek"]: week["differences"] for week in record["weeks"]}
    assert weekly[36]["A"] == {
        "difference": 4.0,
        "pairs": 3,
        "exact_zero_pairs": 0,
        "failed_pairs": 0,
    }
    assert weekly[37] == weekly[38] == {"A": None, "B": None}
    (split,) = record["contrast_a_by_served_route"].values()
    assert split["weeks_listed"] == [6, 34, 35, 36] and split["pairs"] == 6 + 6 + 3 + 3
    assert {
        "truncation",
        "served_route",
        "team_share_without_marker_or_components",
        "producer_changes",
    } <= set(record["choices"])
    assert record["choices"]["truncation"] == scorer.CHOICES["truncation"]


@pytest.mark.parametrize(
    ("arm", "gameweek", "truncated"),
    [
        ("served_5", 34, False),
        ("hold_5", 35, True),
        ("served_3", 36, False),
        ("hold_3", 37, True),
        ("served_3", 38, True),
        ("one_week", 38, False),
    ],
)
def test_rule_14_truncates_five_week_windows_from_gw35_and_three_week_ones_from_gw37(
    arm: str, gameweek: int, truncated: bool
) -> None:
    assert scorer.truncated_by_rule_14(arm, gameweek) is truncated
    assert truncated is (len(chain.window_weeks(arm, gameweek)) < chain._width(arm))


def test_a_record_whose_truncation_is_not_rule_14s_refuses_the_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 14 fixes which windows are truncated, so a record that says otherwise is refused
    rather than moved into or out of the primary contrasts."""

    original = chain._chain_record

    def mislabelled(key: tuple[str, str], *rest: Any) -> chain.ChainRecord:
        """The runner's own record, with GW7's p950 one_week window stated as truncated; the
        runner then seals and posts it as it stands."""

        record = original(key, *rest)
        if key == ("p950", "one_week") and rest[1] == 7:
            cast(dict[str, object], record.document["policy"])["truncated"] = True
        return record

    monkeypatch.setattr(chain, "_chain_record", mislabelled)
    evidence, snapshots, records = _world(tmp_path, monkeypatch, missing=tuple(range(8, 21)))
    _identity(monkeypatch)
    with pytest.raises(scorer.ScorerError, match="GW07 p950 one_week: the record's truncation"):
        scorer.score(
            evidence,
            snapshots,
            "gw20",
            receipts=tmp_path / RECEIPTS,
            records_dir=records,
            index_file=tmp_path / "index.md",
        )
    assert not records.exists()


def test_a_record_must_state_the_truncation_rule_14_gives_in_both_directions() -> None:
    """Rule 14: a five-week window decided at GW35 is truncated, so a record that says it is not
    is refused, as is a one-week record that says it is, and a decided or failed record that
    states no truncation. Held and blocked records carry no window."""

    def week(arm: str, policy: object, status: str = "decided") -> scorer.WeekEvidence:
        record = {"profile": "p1000", "arm": arm, "status": status, "policy": policy}
        return scorer.WeekEvidence(35, {}, {"missing_reason": None}, {("p1000", arm): record})

    unscored = scorer.Outcome(35, None, None, "not_settled")
    differs = "'s truncation is {}, and rule 14 says {}"
    for arm, policy, status, message in (
        ("served_5", {"truncated": False}, "decided", differs.format(False, True)),
        ("one_week", {"truncated": True}, "decided", differs.format(True, False)),
        ("one_week", {}, "decided", " states no truncation"),
        ("hold_5", None, "failed", " states no truncation"),
        ("served_3", {"truncated": 0}, "failed", " states no truncation"),
    ):
        with pytest.raises(scorer.ScorerError, match=f"GW35 p1000 {arm}: the record{message}"):
            scorer.score_week(week(arm, policy, status), unscored)
    scored = scorer.score_week(week("served_5", {"truncated": True}), unscored)
    assert scored.truncated == frozenset({("p1000", "served_5")}) and scored.scores == {}
    for status in ("held", "blocked"):
        assert scorer.score_week(week("hold_5", None, status), unscored).truncated == frozenset()
    with pytest.raises(scorer.ScorerError, match="not one of the protocol's arms"):
        scorer.truncated_by_rule_14("served_4", 10)


@pytest.mark.parametrize(
    ("hold_change", "served_paid", "zero_pairs_a", "mean_a"),
    [
        ({}, 0, 6, 0.0),
        ({}, 1, 0, -4.0),
        ({"bench": [2, 12, 7, 15]}, 0, 0, 0.0),
        ({"captain": 4}, 0, 0, 0.0),
        ({"vice_captain": 13}, 0, 0, 0.0),
    ],
    ids=["same_team", "only_hits", "only_bench_order", "only_captain", "only_vice"],
)
def test_a_pair_is_exactly_zero_only_when_the_whole_team_and_the_hits_agree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hold_change: dict[str, object],
    served_paid: int,
    zero_pairs_a: int,
    mean_a: float,
) -> None:
    """Rule 27: a pair is exactly zero only when the fifteen, the eleven, the bench order, the
    captain, the vice and the hits all agree. A pair that differs only in its bench order or its
    armband scores the same points here and is still not counted, and no other pair is set to
    zero."""

    evidence, snapshots, records = _world(tmp_path, monkeypatch, through=6)
    _identity(monkeypatch)

    def one_team(document: dict[str, Any]) -> None:
        # Players 3, 4, 9 and 13 all score two, so no armband here moves the points.
        document["advice"] = _lineup(3)
        if document["arm"].startswith("hold"):
            document["advice"].update(hold_change)
        served = document["arm"].startswith("served")
        document["plan"]["weeks"][0]["paid_transfer_count"] = served_paid if served else 0

    _rewrite_week(evidence, tmp_path / RECEIPTS, 6, one_team)
    # The reading waits for GW20 in some capture.
    _outcome_capture(snapshots, 20, settled_through=20, live=False)
    _read_through(monkeypatch, 6)
    record = scorer.score(
        evidence,
        snapshots,
        "gw20",
        receipts=tmp_path / RECEIPTS,
        records_dir=records,
        index_file=tmp_path / "index.md",
    )
    primary_a = record["contrasts"]["A"]["primary"]
    primary_b = record["contrasts"]["B"]["primary"]
    assert primary_a["pairs"] == 6 and primary_a["exact_zero_pairs"] == zero_pairs_a
    assert primary_a["mean"] == pytest.approx(mean_a)
    # served and one_week played one team; only served's own hit can set them apart.
    assert primary_b["pairs"] == 6 and primary_b["exact_zero_pairs"] == (0 if served_paid else 6)
    assert primary_b["mean"] == pytest.approx(-4.0 * served_paid)


#: Hold's captain's (player 10) and one_week's captain's (player 11) realized points from GW6 to
#: GW38, drawn once and kept: on these weeks each contrast's interval moves with its candidate id.
HOLD_CAPTAIN = [10, 15, 9, 12, 14, 8, 7, 14, 11, 15, 10, 10, 14, 15, 15, 14, 13]
HOLD_CAPTAIN += [9, 10, 9, 15, 13, 7, 8, 9, 7, 11, 7, 11, 14, 13, 13, 13]
ONE_WEEK_CAPTAIN = [5, 4, 3, 1, 2, 0, 0, 1, 3, 1, 2, 5, 3, 5, 2, 3, 4]
ONE_WEEK_CAPTAIN += [3, 4, 2, 4, 4, 3, 4, 1, 2, 5, 0, 2, 4, 5, 5, 1]


def _season_points(gameweek: int) -> dict[int, int]:
    return POINTS | {10: HOLD_CAPTAIN[gameweek - 6], 11: ONE_WEEK_CAPTAIN[gameweek - 6]}


@pytest.mark.slow
def test_the_final_reading_covers_the_season_with_verdicts_and_each_arms_totals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rules 14 and 26 to 35 over GW6 to GW38, after the interim reading: the windows are cut
    at GW38 as the runner cuts them, each contrast scores GW6 to GW36 on its own candidate id,
    and only the final reading records verdicts, on its two primary contrasts alone, and each
    arm's totals."""

    evidence, snapshots, records = _world(tmp_path, monkeypatch, through=38, points=_season_points)
    _identity(monkeypatch)
    index = tmp_path / "index.md"
    paths = {"receipts": tmp_path / RECEIPTS, "records_dir": records, "index_file": index}
    interim = scorer.score(evidence, snapshots, "gw20", **paths)
    assert interim["final"] is False and "by_arm" not in interim["totals"]
    # Rule 25: the final reading reads the interim record as develop holds it once merged.
    _on_develop(monkeypatch, records)
    record = scorer.score(evidence, snapshots, "gw38", **paths)
    assert record["final"] is True and record["reading_gameweek"] == 38
    assert [week["gameweek"] for week in record["weeks"]] == list(range(6, 39))
    assert all(week["scored_chains"] == 15 for week in record["weeks"])
    # No capture changed between the readings.
    assert record["changed_since_interim"]["changed_weeks"] == []
    assert {
        week["gameweek"]: week["truncated_arms"]
        for week in record["weeks"]
        if week["truncated_arms"]
    } == {
        35: ["hold_5", "served_5"],
        36: ["hold_5", "served_5"],
        37: ["hold_3", "hold_5", "served_3", "served_5"],
        38: ["hold_3", "hold_5", "served_3", "served_5"],
    }
    # Every arm's eleven scores 26 plus hold's and one_week's captains' points, and its own
    # captain's points again; served's captain scores ten and served pays four. So A is 6
    # minus hold's captain's points and B is 6 minus one_week's, week by week.
    expected = {
        "A": [6.0 - _season_points(gameweek)[10] for gameweek in range(6, 37)],
        "B": [6.0 - _season_points(gameweek)[11] for gameweek in range(6, 37)],
    }
    for label, other, verdict in (("A", "B", "worse"), ("B", "A", "better")):
        block = record["contrasts"][label]
        primary = block["primary"]
        assert primary["weeks_listed"] == list(range(6, 37))
        # GW35 and GW36 enter on their untruncated window-3 pairs only.
        assert primary["pairs"] == 29 * 6 + 2 * 3
        assert primary["mean"] == pytest.approx(statistics.fmean(expected[label]))
        for blocks in (4, 8):
            stated = _stated_interval(
                expected[label], f"planner_policy_chain_v1:{label}", blocks=blocks
            )
            assert stated != _stated_interval(
                expected[label], f"planner_policy_chain_v1:{other}", blocks=blocks
            )
            key = "interval" if blocks == 4 else "interval_blocks_of_8"
            assert primary[key] == stated
        assert primary["verdict"] == verdict
        cut = record["truncated_weeks"][label]
        assert cut["weeks_listed"] == [35, 36, 37, 38] and cut["pairs"] == 3 + 3 + 6 + 6
    # Rules 29 and 32: only the two primary contrasts carry a verdict; every other block is
    # descriptive.
    assert {path: value for path, value in _verdicts(record) if value is not None} == {
        ("contrasts", "A", "primary"): "worse",
        ("contrasts", "B", "primary"): "better",
    }
    # Each window alone scores until its own truncation: GW36 for three weeks, GW34 for five.
    assert record["secondary"]["A_window_3"]["weeks_listed"] == list(range(6, 37))
    assert record["secondary"]["A_window_5"]["weeks_listed"] == list(range(6, 35))
    by_arm = record["totals"]["by_arm"]
    assert set(by_arm) == set(scorer.ARMS)
    captain = {"served": 8, "hold": 10, "one": 11}
    for arm in scorer.ARMS:
        gross = sum(
            26
            + _season_points(gameweek)[10]
            + _season_points(gameweek)[11]
            + _season_points(gameweek)[captain[arm.split("_")[0]]]
            for gameweek in range(6, 39)
        )
        totals = by_arm[arm]
        # Truncated weeks are played (rule 14), so every week of every squad counts.
        assert totals["scored_chain_weeks"] == 3 * 33
        assert totals["gross_points"] == pytest.approx(3 * gross)
        assert totals["hit_points"] == pytest.approx(
            3 * 33 * 4.0 if arm.startswith("served") else 0.0
        )
        assert totals["net_points"] == pytest.approx(totals["gross_points"] - totals["hit_points"])
    # Rule 3: one statement of how the release live at a deadline is read, in each record.
    assert record["release_rule"] == interim["release_rule"] == scorer.RELEASE_RULE
    assert "strictly before the deadline" in record["release_rule"]
    twin = (records / "planner_policy_chain_gw38.md").read_text(encoding="utf-8")
    assert "Final reading" in twin
    assert "| A | 31 |" in twin and "| B | 31 |" in twin
    index_text = index.read_text(encoding="utf-8")
    assert index_text.count("- [Planner policy chain, gw20 reading]") == 1
    assert index_text.count("- [Planner policy chain, gw38 reading]") == 1
    assert "verdicts A worse, B better" in index_text


# Rule 25: a week whose outcome capture changed between the readings


def test_the_final_reading_lists_each_week_whose_outcome_capture_changed_with_both_scores(
    two_readings: dict[str, Any],
) -> None:
    """Rule 25: each reading keeps every week's weekly differences beside its outcome capture,
    and the final reading lists each interim week whose capture changed with both captures and
    both differences, the interim's as develop holds them. The later capture holds every played
    week's live payload, so every interim week's capture changed: GW12's differences moved, and
    GW15, unscored at the interim, is scored."""

    interim, final = two_readings["interim"], two_readings["final"]
    before = {week["gameweek"]: week for week in interim["weeks"]}
    assert before[12]["differences"] == {
        "A": {"difference": 4.0, "pairs": 6, "exact_zero_pairs": 0, "failed_pairs": 0},
        "B": {"difference": 5.0, "pairs": 6, "exact_zero_pairs": 0, "failed_pairs": 0},
    }
    assert before[15]["outcome_capture"] is None
    assert before[15]["unscored_reason"] == "tied_outcome_captures"
    assert before[15]["differences"] == {"A": None, "B": None}
    # Two distinct captures tie as GW15's latest, so the interim twin lists the week with its
    # reason and no difference, never as a zero (rule 25).
    interim_twin = (two_readings["records_dir"] / "planner_policy_chain_gw20.md").read_text(
        encoding="utf-8"
    )
    row = next(line for line in interim_twin.splitlines() if line.startswith("| 15 |"))
    assert row.startswith("| 15 | capture-gw15 | none |")
    assert row.endswith(
        "| 0 | none | none | site-2026-27-gw06-fix16 | True | True | tied_outcome_captures |"
    )
    changed = final["changed_since_interim"]
    assert changed["record"] == "docs/research/planner_policy_chain_gw20.json"
    assert changed["read_from"] == scorer.DEVELOP == "refs/remotes/origin/develop"
    assert (changed["added_commit"], changed["develop_commit"]) == ("a" * 40, "e" * 40)
    assert changed["sha256"] == two_readings["on_develop"].sha256
    assert changed["scorer_merge_commit"] == "c" * 40 and changed["interim_weeks"] == 15
    listed = {week["gameweek"]: week for week in changed["changed_weeks"]}
    assert list(listed) == list(range(6, 21))
    correction = two_readings["correction"]
    for gameweek, week in listed.items():
        assert week["interim"] == {
            key: before[gameweek][key]
            for key in ("outcome_capture", "unscored_reason", "differences")
        }
        assert week["final"]["outcome_capture"] == correction
        assert week["final"]["unscored_reason"] is None
        if gameweek not in (12, 15):
            assert week["final"]["differences"] == week["interim"]["differences"]
    # Player 8, the served captain, scored 4 and not 10, doubled: served nets 27 - 4 = 23
    # against hold's 25 and one_week's 24.
    assert listed[12]["final"]["differences"]["A"]["difference"] == pytest.approx(-2.0)
    assert listed[12]["final"]["differences"]["B"]["difference"] == pytest.approx(-1.0)
    assert listed[15]["final"]["differences"]["A"]["difference"] == pytest.approx(4.0)
    # Weeks after the interim are the final reading's alone.
    assert all(week["gameweek"] <= 20 for week in changed["changed_weeks"])
    twin = (two_readings["records_dir"] / "planner_policy_chain_gw38.md").read_text(
        encoding="utf-8"
    )
    assert "## Weeks whose outcome capture changed since the interim" in twin
    assert f"as commit `{'a' * 40}` added it" in twin
    old = before[12]["outcome_capture"]
    assert f"| 12 | {old} | {correction} | +4.000 | -2.000 | +5.000 | -1.000 |" in twin
    assert (
        f"| 15 | none (tied_outcome_captures) | {correction} | none | +4.000 | none | +5.000 |"
        in twin
    )


def test_the_final_reading_refuses_an_interim_record_it_cannot_compare_with(
    two_readings: dict[str, Any],
) -> None:
    """Rules 3, 24, 25, 28 and 37: the interim record must be this protocol's interim reading of
    the same chain, scored from this scorer's merge commit on the same protocol.json, over the
    same weeks and decisions, and an outcome capture that did not change must give the
    differences it gave at the interim."""

    final = two_readings["final"]
    raw = (two_readings["records_dir"] / "planner_policy_chain_gw20.json").read_bytes()
    source = {key: final["frozen_source"][key] for key in scorer.FROZEN_SOURCE_FIELDS}
    correction = two_readings["correction"]

    def compare(
        change: Callable[[dict[str, Any]], object],
        weeks: Sequence[dict[str, Any]] = final["weeks"],
    ) -> dict[str, Any]:
        record = json.loads(raw)
        change(record)
        return scorer.changed_since_interim(
            scorer.InterimRecord(record, "a" * 40, "e" * 40, "f" * 64),
            weeks,
            {"scorer_merge_commit": "c" * 40},
            source,
            final["receipts"]["manifests"],
        )

    assert compare(lambda record: None) == final["changed_since_interim"] | {"sha256": "f" * 64}

    def first_week_unchanged(record: dict[str, Any]) -> None:
        record["weeks"][0]["outcome_capture"] = correction

    # A week whose outcome capture did not change is not listed.
    assert [week["gameweek"] for week in compare(first_week_unchanged)["changed_weeks"]] == list(
        range(7, 21)
    )

    def missing_at_gw10(record: dict[str, Any]) -> None:
        record["weeks"][10 - 6]["missing_reason"] = "no_artifact"

    # A week missing in both readings is scored by neither, so it is not listed, although the
    # capture its outcome would be read from changed.
    weeks = [dict(week) for week in final["weeks"]]
    weeks[10 - 6]["missing_reason"] = "no_artifact"
    assert weeks[10 - 6]["outcome_capture"] != json.loads(raw)["weeks"][10 - 6]["outcome_capture"]
    assert [week["gameweek"] for week in compare(missing_at_gw10, weeks)["changed_weeks"]] == [
        gameweek for gameweek in range(6, 21) if gameweek != 10
    ]

    def same_capture_other_differences(record: dict[str, Any]) -> None:
        record["weeks"][12 - 6]["outcome_capture"] = correction

    for change, message in (
        (lambda record: record.update(reading="gw38"), "not this protocol's interim record"),
        (lambda record: record.update(season="2025-26"), "not this protocol's interim record"),
        (
            lambda record: record["identity"].update(scorer_merge_commit="9" * 40),
            r"scored from 9{40}, and this reading runs from c{40}: rule 37",
        ),
        (
            lambda record: record["frozen_source"].update(repository_commit="f" * 40),
            r"another frozen source \(rule 3\): its repository_commit differ",
        ),
        (
            lambda record: record["frozen_source"].update(dropped_profiles={"p900": "x"}),
            "another frozen source .*dropped_profiles",
        ),
        (
            lambda record: record["frozen_source"].update(first_chain_week=7),
            "another frozen source .*first_chain_week",
        ),
        (
            lambda record: record["frozen_source"].pop("runner_sha256"),
            "another frozen source .*runner_sha256",
        ),
        (lambda record: record.pop("weeks"), "lists no weeks"),
        (
            lambda record: record["weeks"].pop(),
            "lists other weeks than this reading's through GW20",
        ),
        (
            lambda record: record["weeks"][0].update(decision_capture="capture-elsewhere"),
            "GW06: the interim record was read from other decisions",
        ),
        (
            lambda record: record["weeks"][1].update(missing_reason="no_artifact"),
            "GW07: the interim record was read from other decisions",
        ),
        (
            lambda record: record["receipts"]["manifests"]["gw08"].update(sha256="0" * 64),
            r"GW08: the interim record was read from other decisions than this reading's \(rule",
        ),
        (
            same_capture_other_differences,
            "GW12: the interim read the same outcome capture and recorded other differences",
        ),
    ):
        with pytest.raises(scorer.ScorerError, match=message):
            compare(change)
    with pytest.raises(scorer.ScorerError, match="so it reads the interim record first"):
        scorer.reading_record(
            reading="gw38",
            protocol={},
            evidence=[],
            captures=[],
            identity={},
            binding=None,
            receipts={},
        )


# Rules 6, 13 and 29: what each reading also reports apart


def test_contrast_a_is_split_by_each_pairs_own_served_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rules 13 and 29: each squad and window pair goes under its own served chain's route and
    outcome. The chosen proposal and whether the guarded construction completed are part of the
    label, a failed served chain is labelled by its failure, and a pair whose hold chain failed
    stays under its served chain's label (rule 22)."""

    observed = "expected_lineup_observed_window_v4"
    expected = "expected_lineup_window_v2"
    guarded = "sequential_certified_window_v1"
    took: dict[tuple[str, str], tuple[str, str, dict[str, object]]] = {
        ("p1000", "served_3"): (
            "observed",
            observed,
            {"observed_window_status": "compared", "seed_completed": None},
        ),
        ("p1000", "served_5"): (
            "expected",
            expected,
            {
                "expected_window_status": "compared",
                "expected_window_chosen": "zero_bonus_proposal",
                "seed_completed": True,
            },
        ),
        ("p950", "served_3"): ("guarded", guarded, {"seed_completed": False}),
        ("p950", "served_5"): ("guarded", guarded, {"seed_completed": False}),
        ("p900", "served_3"): ("guarded", guarded, {"seed_completed": True}),
        ("p900", "served_5"): ("guarded", guarded, {"seed_completed": True}),
    }
    original = chain._chain_record

    def routed(key: tuple[str, str], *rest: Any) -> chain.ChainRecord:
        """In GW6 each served chain names its route; all but p1000's served_3 play hold's team
        without a paid transfer, so only that pair is not an exact zero. The runner then seals
        and posts each record as it stands."""

        record = original(key, *rest)
        if rest[1] == 6 and key in took:
            route, version, solver = took[key]
            document = record.document
            cast(dict[str, object], document["policy"]).update(route=route, route_version=version)
            cast(dict[str, object], document["solver"]).update(solver)
            if key != ("p1000", "served_3"):
                document["advice"] = _lineup(CAPTAINS["hold"])
                plan = cast(dict[str, list[dict[str, object]]], document["plan"])
                plan["weeks"][0]["paid_transfer_count"] = 0
        return record

    monkeypatch.setattr(chain, "_chain_record", routed)
    evidence, snapshots, records = _world(
        tmp_path,
        monkeypatch,
        missing=tuple(range(8, 21)),
        failing=(("served_5", 7), ("hold_3", 7)),
    )
    _identity(monkeypatch)
    record = scorer.score(
        evidence,
        snapshots,
        "gw20",
        receipts=tmp_path / RECEIPTS,
        records_dir=records,
        index_file=tmp_path / "index.md",
    )
    split = {
        label: (block["weeks_listed"], block["pairs"], block["mean"], block["exact_zero_pairs"])
        for label, block in record["contrast_a_by_served_route"].items()
    }
    stubbed = "route=served:version=none:seed_completed=none"
    assert split == {
        f"route=observed:version={observed}:observed=compared:seed_completed=none": (
            [6],
            1,
            pytest.approx(4.0),
            0,
        ),
        f"route=expected:version={expected}:expected=compared:chosen=zero_bonus_proposal:"
        "seed_completed=true": ([6], 1, pytest.approx(0.0), 1),
        f"route=guarded:version={guarded}:seed_completed=false": ([6], 2, pytest.approx(0.0), 2),
        f"route=guarded:version={guarded}:seed_completed=true": ([6], 2, pytest.approx(0.0), 2),
        # GW7's stubbed arms name no route of their own. Its served_3 chains are paired with
        # failed hold_3 chains, which play their held team, hold's lineup of GW6 with no hit.
        stubbed: ([7], 3, pytest.approx(4.0), 0),
        # Its failed served_5 chains play their held team, the served lineup of GW6 (the record's
        # advice was edited, the chain's state was not), with no hit.
        "failed=raised_ValueError": ([7], 3, pytest.approx(8.0), 0),
    }
    week7 = next(week for week in record["weeks"] if week["gameweek"] == 7)
    assert week7["served_routes"]["p950:served_5"] == "failed=raised_ValueError"
    assert week7["served_routes"]["p950:served_3"] == stubbed
    assert record["contrasts"]["A"]["primary"]["weeks_listed"] == [6, 7]
    twin = (records / "planner_policy_chain_gw20.md").read_text(encoding="utf-8")
    assert "| A where served is `failed=raised_ValueError` | 1 | +8.000 |" in twin


def test_team_share_weeks_without_their_marker_or_components_are_reported_apart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rules 6 and 40: a team share week that bound while its receipt records its ready
    bundle's marker or its components file as absent stays pooled and is also reported apart,
    in each contrast. The twin, rendered from the JSON, claims nothing about what such a week's
    members were served (section 11)."""

    share: dict[str, object] = {
        "model_version": "football_team_share_v1",
        "ready_bundle_present": True,
        "components_present": True,
    }
    fields: dict[int, dict[str, object]] = {
        6: share,
        7: share | {"ready_bundle_present": False},
        8: share | {"components_present": False},
        9: share | {"ready_bundle_present": False, "components_present": False},
        # A missing week bound nothing, so it is not reported apart whatever its receipt says.
        10: share | {"ready_bundle_present": False},
    }
    evidence, snapshots, records = _world(
        tmp_path, monkeypatch, missing=tuple(range(10, 21)), receipt_fields=fields
    )
    _identity(monkeypatch)
    record = scorer.score(
        evidence,
        snapshots,
        "gw20",
        receipts=tmp_path / RECEIPTS,
        records_dir=records,
        index_file=tmp_path / "index.md",
    )
    listed = {week["gameweek"]: week for week in record["weeks"]}
    apart = [g for g, week in listed.items() if week["team_share_without_marker_or_components"]]
    assert apart == [7, 8, 9]
    assert (listed[7]["ready_bundle_present"], listed[7]["components_present"]) == (False, True)
    assert (listed[11]["ready_bundle_present"], listed[11]["components_present"]) == (None, None)
    for label in ("A", "B"):
        block = record["contrasts"][label]
        assert block["primary"]["weeks_listed"] == [6, 7, 8, 9]
        assert block["team_share_without_marker_or_components"]["weeks_listed"] == [7, 8, 9]
    twin = (records / "planner_policy_chain_gw20.md").read_text(encoding="utf-8")
    assert "reported apart (rule 6): GW07, GW08, GW09." in twin
    assert "claims nothing about what their members were served" in twin
    written = json.loads((records / "planner_policy_chain_gw20.json").read_text(encoding="utf-8"))
    assert scorer.render_markdown(written) == twin
    # Only a team share week is reported apart, and a field its receipt lacks is not presence.
    joint = share | {"model_version": "football_joint_role_minutes_v1", "components_present": False}
    assert not scorer.team_share_apart(joint)
    assert not scorer.team_share_apart(share)
    assert scorer.team_share_apart({"model_version": "football_team_share_v1"})


def test_a_declared_producer_change_is_reported_apart_and_a_reading_says_when_none_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 6: a producer change that keeps its version name is taken as the operator declared
    it, with its first week. Its weeks stay pooled and are also reported apart, each week under
    the latest change of its version. With none declared the record says so, and a declaration
    the evidence contradicts is refused before anything is written."""

    share: dict[str, object] = {"model_version": "football_team_share_v1"}
    present = {"ready_bundle_present": True, "components_present": True}
    evidence, snapshots, records = _world(
        tmp_path,
        monkeypatch,
        missing=tuple(range(10, 21)),
        receipt_fields=dict.fromkeys(range(6, 10), share | present),
    )
    _identity(monkeypatch)
    # Each reading here goes to a place of its own, its index included: a reading the index
    # already links is taken (rule 28).
    paths = {"receipts": tmp_path / RECEIPTS}
    undeclared = scorer.score(
        evidence,
        snapshots,
        "gw20",
        records_dir=tmp_path / "undeclared",
        index_file=tmp_path / "undeclared.md",
        **paths,
    )
    assert undeclared["producer_changes"] == {
        "source": None,
        "declared": [],
        "statement": "No producer change that keeps a version name was declared, so no week is "
        "reported apart for one.",
    }
    assert undeclared["contrasts"]["A"]["after_producer_change"] == {}
    assert all(week["producer_change"] is None for week in undeclared["weeks"])
    twin = (tmp_path / "undeclared" / "planner_policy_chain_gw20.md").read_text(encoding="utf-8")
    assert "Producer changes that keep a version name (rule 6): none declared." in twin
    first, second = share | {"first_week": 7}, share | {"first_week": 9}
    path = tmp_path / "producer_changes.json"
    declaration = {"source": "issuecomment-2", "changes": [second, first]}
    path.write_text(json.dumps(declaration), encoding="utf-8")
    declared = scorer.read_producer_changes(str(path))
    assert declared == {"source": "issuecomment-2", "changes": [first, second]}
    record = scorer.score(
        evidence,
        snapshots,
        "gw20",
        records_dir=records,
        index_file=tmp_path / "index.md",
        producer_changes=declared,
        **paths,
    )
    names = ["football_team_share_v1 from GW07", "football_team_share_v1 from GW09"]
    assert record["producer_changes"]["source"] == "issuecomment-2"
    assert record["producer_changes"]["declared"] == [first, second]
    # GW10 is missing and its receipt names no version, so no change reaches it.
    assert [week["producer_change"] for week in record["weeks"][:5]] == [
        None,
        names[0],
        names[0],
        names[1],
        None,
    ]
    for label in ("A", "B"):
        contrast = record["contrasts"][label]
        assert contrast["primary"]["weeks_listed"] == [6, 7, 8, 9]
        after = contrast["after_producer_change"]
        assert sorted(after) == names
        assert [after[name]["weeks_listed"] for name in names] == [[7, 8], [9]]
    twin = (records / "planner_policy_chain_gw20.md").read_text(encoding="utf-8")
    assert f"{names[0]}, {names[1]}, declared at issuecomment-2." in twin
    assert f"| A after the producer change of `{names[1]}` | 1 |" in twin
    for contradicted, message in (
        ({"model_version": "football_joint_role_minutes_v1", "first_week": 8}, "receipt states"),
        (share | {"first_week": 5}, "precedes the chain's first week"),
    ):
        with pytest.raises(scorer.ScorerError, match=message):
            scorer.score(
                evidence,
                snapshots,
                "gw20",
                records_dir=tmp_path / "refused",
                index_file=tmp_path / "refused.md",
                producer_changes={"source": "issuecomment-3", "changes": [contradicted]},
                **paths,
            )
    assert not (tmp_path / "refused").exists() and not (tmp_path / "refused.md").exists()
    for document in (
        [],
        {"changes": []},
        {"source": " ", "changes": []},
        {"source": "x", "changes": [], "note": "free text"},
        {"source": "x", "changes": {}},
        {"source": "x", "changes": [{"model_version": "football_contextual_v3", "first_week": 8}]},
        {"source": "x", "changes": [share | {"first_week": 39}]},
        {"source": "x", "changes": [share | {"first_week": True}]},
        {"source": "x", "changes": [share | {"first_week": "8"}]},
        {"source": "x", "changes": [share]},
        {"source": "x", "changes": [first, first]},
    ):
        with pytest.raises(scorer.ScorerError, match="producer change"):
            scorer.declared_producer_changes(document)
    assert scorer.read_producer_changes("none") == {"source": None, "changes": []}


def test_a_producer_change_declaration_that_is_not_one_object_with_single_keys_is_refused(
    tmp_path: Path,
) -> None:
    """Rule 6: a declaration file that is not one JSON object, or that gives a key twice, is
    refused with a reason and never read as fewer changes. One written with a byte order mark,
    as Windows PowerShell 5.1 writes UTF-8, is read."""

    path = tmp_path / "producer_changes.json"
    change = '{"model_version": "football_team_share_v1", "first_week": 8}'
    twice = '{"model_version": "football_team_share_v1", "first_week": 8, "first_week": 9}'
    for text in (
        "[]",
        '"none"',
        '["source", "changes"]',
        '{"source": "issuecomment-2", "changes": [' + change + '], "changes": []}',
        '{"source": "issuecomment-2", "changes": [' + twice + "]}",
    ):
        path.write_text(text, encoding="utf-8")
        with pytest.raises(scorer.ScorerError, match="producer change"):
            scorer.read_producer_changes(str(path))
    with pytest.raises(scorer.ScorerError, match="cannot be read"):
        scorer.read_producer_changes(str(tmp_path / "absent.json"))
    whole = '{"source": "issuecomment-2", "changes": [' + change + "]}"
    path.write_bytes(b"\xef\xbb\xbf" + whole.encode("utf-8"))
    assert scorer.read_producer_changes(str(path)) == {
        "source": "issuecomment-2",
        "changes": [{"model_version": "football_team_share_v1", "first_week": 8}],
    }


# Rules 20, 22, 23 and 29: what each chain did besides its points, and each model version


def test_a_blocked_chain_is_listed_from_its_week_and_a_failure_is_no_proved_plan() -> None:
    """Rules 20, 22 and 23 on hand-made evidence: a chain blocked from GW7 is listed in GW7 and
    GW8 with GW7, failed arms are listed by budget with their reasons, and only a decided record
    whose solver says proved, as a boolean, counts as proved, whatever a failed one says."""

    def week(
        gameweek: int, changes: dict[tuple[str, str], dict[str, object]]
    ) -> scorer.WeekEvidence:
        records = {
            (profile, arm): {
                "profile": profile,
                "arm": arm,
                "status": "decided",
                "solver": {"proved": True},
                **changes.get((profile, arm), {}),
            }
            for profile in scorer.PROFILES
            for arm in scorer.ARMS
        }
        return scorer.WeekEvidence(gameweek, {}, {"gameweek": gameweek}, records)

    blocked = {"status": "blocked", "reason": "held_player_absent"}
    weeks = [
        week(
            6,
            {
                ("p1000", "served_3"): {"solver": {"proved": False}},
                ("p950", "hold_5"): {"solver": {"proved": "true"}},
            },
        ),
        week(
            7,
            {
                ("p950", "served_5"): blocked,
                ("p900", "hold_3"): {"status": "failed", "reason": "no_plan"},
                ("p1000", "hold_3"): {"status": "failed", "reason": "wall_clock_stopped"},
            },
        ),
        week(
            8,
            {
                ("p950", "served_5"): blocked,
                ("p1000", "one_week"): {"status": "held", "reason": "no_artifact"},
            },
        ),
    ]
    listed = scorer.chain_statuses(weeks)
    assert listed[6] == {"blocked_chains": [], "failed_chains": []}
    assert listed[7]["failed_chains"] == [
        {"profile": "p1000", "arm": "hold_3", "reason": "wall_clock_stopped"},
        {"profile": "p900", "arm": "hold_3", "reason": "no_plan"},
    ]
    for gameweek in (7, 8):
        assert listed[gameweek]["blocked_chains"] == [
            {
                "profile": "p950",
                "arm": "served_5",
                "blocked_from": 7,
                "reason": "held_player_absent",
            }
        ]
    assert listed[8]["failed_chains"] == []
    proved = scorer.proved_plans(weeks)
    assert proved["served_3"] == {
        "decided": 9,
        "proved": 8,
        "failed": 0,
        "proved_share": pytest.approx(8 / 9),
    }
    assert proved["served_5"] == {"decided": 7, "proved": 7, "failed": 0, "proved_share": 1.0}
    assert proved["hold_3"] == {"decided": 7, "proved": 7, "failed": 2, "proved_share": 1.0}
    assert proved["hold_5"]["proved"] == 8 and proved["one_week"]["decided"] == 8
    assert scorer.proved_plans([])["served_3"] == {
        "decided": 0,
        "proved": 0,
        "failed": 0,
        "proved_share": None,
    }
    # The twin lists a blocked chain once, from the week it was blocked, and each failure.
    lines = scorer._chain_lines(
        {
            "weeks": [{"gameweek": week.gameweek, **listed[week.gameweek]} for week in weeks],
            "proved_plans": proved,
        }
    )
    assert lines.count(
        "- `p950` `served_5`: blocked from GW07 (held_player_absent); no decision and no pair "
        "from then on (rule 23)."
    ) == 1 and not any("GW08 (held" in line for line in lines)
    assert "| 7 | p1000 | hold_3 | wall_clock_stopped |" in lines
    assert "| served_3 | 9 | 8 | 0.889 | 0 |" in lines


@pytest.fixture(scope="module")
def eventful_interim(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One interim reading of a chain whose arms did more than score. hold_3 fails in GW7 for
    every squad, and in GW8 both hold arms fail for every squad; served_3's GW8 plans are
    FEASIBLE and not proved; GW9 is missing as an artifact of a version rule 6 does not admit.
    The team share version serves through GW12 and the retained history version from GW13,
    whose live payload no capture holds. GW19 is decided under the minutes version, and no
    capture holds its live payload either. Every chain is blocked in GW20."""

    tmp_path = tmp_path_factory.mktemp("eventful_interim")
    share: dict[str, object] = {
        "model_version": TEAM_SHARE,
        "ready_bundle_present": True,
        "components_present": True,
    }
    fields: dict[int, dict[str, object]] = {
        gameweek: share if gameweek < 13 else {"model_version": RETAINED}
        for gameweek in range(6, 21)
    }
    fields[9] = {"model_version": NOT_ADMITTED, "reason": "artifact_of_another_model_version"}
    fields[19] = {"model_version": MINUTES}
    with pytest.MonkeyPatch.context() as monkeypatch:
        evidence, snapshots, records = _world(
            tmp_path,
            monkeypatch,
            missing=(9,),
            failing=(("hold_3", 7), ("hold_3", 8), ("hold_5", 8)),
            receipt_fields=fields,
            unproved=(("served_3", 8),),
            blocked_from=20,
            without_live=(13, 19),
        )
        _identity(monkeypatch)
        record = scorer.score(
            evidence,
            snapshots,
            "gw20",
            receipts=tmp_path / RECEIPTS,
            records_dir=records,
            index_file=tmp_path / "index.md",
        )
    twin = (records / "planner_policy_chain_gw20.md").read_text(encoding="utf-8")
    return {"record": record, "twin": twin}


def test_failed_arms_and_blocked_chains_are_listed_by_week_and_in_the_twin(
    eventful_interim: dict[str, Any],
) -> None:
    """Rule 22 records each failure and rule 23 lists a blocked chain: each week lists the arms
    that failed in it with their reasons, and every chain blocked by then with the week it was
    blocked from, by budget and then in the order of the arms."""

    record, twin = eventful_interim["record"], eventful_interim["twin"]
    weeks = {week["gameweek"]: week for week in record["weeks"]}
    failure = "raised_ValueError"
    assert weeks[7]["failed_chains"] == [
        {"profile": profile, "arm": "hold_3", "reason": failure} for profile in scorer.PROFILES
    ]
    assert weeks[8]["failed_chains"] == [
        {"profile": profile, "arm": arm, "reason": failure}
        for profile in scorer.PROFILES
        for arm in ("hold_3", "hold_5")
    ]
    assert all(weeks[g]["failed_chains"] == [] for g in weeks if g not in (7, 8))
    assert all(weeks[g]["blocked_chains"] == [] for g in range(6, 20))
    assert weeks[20]["blocked_chains"] == [
        {"profile": profile, "arm": arm, "blocked_from": 20, "reason": "held_player_absent"}
        for profile in scorer.PROFILES
        for arm in scorer.ARMS
    ]
    assert weeks[20]["scored_chains"] == 0 and weeks[20]["differences"] == {"A": None, "B": None}
    assert "## Blocked chains and failed arms" in twin
    assert "| 7 | p950 | hold_3 | raised_ValueError |" in twin
    assert "| 8 | p900 | hold_5 | raised_ValueError |" in twin
    assert (
        "- `p900` `one_week`: blocked from GW20 (held_player_absent); no decision and no pair "
        "from then on (rule 23)." in twin
    )
    assert twin.count("blocked from GW20") == 15


def test_each_arm_reports_the_share_of_its_decided_plans_proved_optimal(
    eventful_interim: dict[str, Any],
) -> None:
    """Rule 20: each arm's decided plans its own search proved OPTIMAL, over its decided plans.
    A failed week is no plan the arm played, so it is counted beside the share, although the
    stubbed failure's solver block says proved."""

    proved = eventful_interim["record"]["proved_plans"]
    assert list(proved) == sorted(scorer.ARMS)
    # GW6 to GW19 less the missing GW9: thirteen decided weeks for each of three squads, since
    # every chain is blocked in GW20.
    assert proved["served_3"] == {
        "decided": 39,
        "proved": 36,
        "failed": 0,
        "proved_share": pytest.approx(36 / 39),
    }
    assert proved["hold_3"] == {"decided": 33, "proved": 33, "failed": 6, "proved_share": 1.0}
    assert proved["hold_5"] == {"decided": 36, "proved": 36, "failed": 3, "proved_share": 1.0}
    for arm in ("served_5", "one_week"):
        assert proved[arm] == {"decided": 39, "proved": 39, "failed": 0, "proved_share": 1.0}
    twin = eventful_interim["twin"]
    assert "| Arm | Decided plans | Proved | Share | Failed weeks |" in twin
    assert "| served_3 | 39 | 36 | 0.923 | 0 |" in twin
    assert "| hold_3 | 33 | 33 | 1.000 | 6 |" in twin


def test_each_block_counts_the_pairs_in_which_an_arm_failed(
    eventful_interim: dict[str, Any],
) -> None:
    """Rule 22: a failed arm's pairs stay in the pairs, so each block counts them, and the
    series without failed weeks counts the ones it left out, a gameweek whose every pair failed
    included: GW8 leaves that series, and its failed pairs are still counted."""

    record, twin = eventful_interim["record"], eventful_interim["twin"]
    a, b = record["contrasts"]["A"], record["contrasts"]["B"]
    # hold_3 failed in GW7 for each squad, three pairs of A; both hold arms in GW8, six more.
    assert a["primary"]["failed_pairs"] == 3 + 6 and b["primary"]["failed_pairs"] == 0
    assert 8 in a["primary"]["weeks_listed"]
    without = a["without_failed_weeks"]
    assert without["failed_pairs"] == 9 and without["pairs"] == a["primary"]["pairs"] - 9
    assert 7 in without["weeks_listed"] and 8 not in without["weeks_listed"]
    assert b["without_failed_weeks"]["failed_pairs"] == 0
    assert record["secondary"]["A_window_3"]["failed_pairs"] == 6
    assert record["secondary"]["A_window_5"]["failed_pairs"] == 3
    assert record["secondary"]["hold_minus_one_week"]["failed_pairs"] == 9
    assert record["by_squad"]["A"]["p950"]["failed_pairs"] == 3
    assert record["by_squad"]["B"]["p950"]["failed_pairs"] == 0
    weeks = {week["gameweek"]: week for week in record["weeks"]}
    assert weeks[7]["differences"]["A"] == {
        "difference": 4.0,
        "pairs": 6,
        "exact_zero_pairs": 0,
        "failed_pairs": 3,
    }
    assert "| Detectable effect | Zero pairs | Failed pairs | Verdict |" in twin
    assert "| 0 | 9 | none (interim) |" in twin and "| 0 | 0 | none (interim) |" in twin


def test_each_model_version_is_reported_from_its_scored_weeks_with_its_first_week(
    eventful_interim: dict[str, Any],
) -> None:
    """Rules 6 and 29, as the record states them: versions are built from scored weeks only, and
    each contrast is reported for each of them on its scored weeks, from the first week served
    under it, scored or not. A version served only in unscored weeks opens no block, and a
    missing week opens none, though its receipt names a version rule 6 does not admit; each
    week still states its own version in the record and in the twin."""

    record, twin = eventful_interim["record"], eventful_interim["twin"]
    weeks = {week["gameweek"]: week for week in record["weeks"]}
    assert weeks[9]["model_version"] == NOT_ADMITTED
    assert weeks[9]["missing_reason"] == "artifact_of_another_model_version"
    assert weeks[13]["model_version"] == RETAINED
    assert weeks[13]["unscored_reason"] == "missing_outcomes"
    assert weeks[19]["model_version"] == MINUTES
    assert weeks[19]["unscored_reason"] == "missing_outcomes"
    for label in scorer.CONTRASTS:
        blocks = record["contrasts"][label]["by_model_version"]
        assert set(blocks) == {TEAM_SHARE, RETAINED}
        assert blocks[TEAM_SHARE]["weeks_listed"] == [6, 7, 8, 10, 11, 12]
        assert blocks[TEAM_SHARE]["first_week"] == 6
        # GW13 was served under the retained version and is its first week, though unscored;
        # GW20 was decided under it too, but every chain was blocked in it.
        assert blocks[RETAINED]["weeks_listed"] == list(range(14, 19))
        assert blocks[RETAINED]["first_week"] == 13
        assert all(block["verdict"] is None for block in blocks.values())
    assert f"| A on `{TEAM_SHARE}` weeks, from GW06 | 6 | +4.000 |" in twin
    assert f"| B on `{RETAINED}` weeks, from GW13 | 5 | +5.000 |" in twin
    assert f"`{MINUTES}` weeks" not in twin
    assert f"`{NOT_ADMITTED}` weeks" not in twin
    # GW19 is listed with its reason and no difference, never as a zero (rule 25).
    row = next(line for line in twin.splitlines() if line.startswith("| 19 |"))
    assert f"| {MINUTES} | 0 | none | none |" in row and row.endswith("| missing_outcomes |")
    assert record["choices"]["model_versions"] == scorer.CHOICES["model_versions"]


def test_each_record_states_the_choices_the_protocol_leaves_open(
    eventful_interim: dict[str, Any],
) -> None:
    """Rules 20, 22, 23, 25 and 29 leave the scorer choices, and the record states each one it
    took, in the twin too, beside the coverage and below-zero rates of rule 31."""

    record, twin = eventful_interim["record"], eventful_interim["twin"]
    assert record["choices"] == scorer.CHOICES
    assert {
        "without_failed_weeks",
        "by_squad",
        "proved_share",
        "blocked_chains",
        "model_versions",
        "changed_outcome_captures",
    } <= set(scorer.CHOICES)
    assert "keeps that gameweek's other pairs" in scorer.CHOICES["without_failed_weeks"]
    assert "contrast A, contrast B and hold minus one_week" in scorer.CHOICES["by_squad"]
    # Each is listed in the twin, in the order of its name.
    stated = {name: twin.index(f"- `{name}`: {text}") for name, text in scorer.CHOICES.items()}
    assert sorted(stated, key=stated.__getitem__) == sorted(stated)
    assert scorer.COVERAGE_NOTE in twin


def test_each_interval_carries_the_protocols_coverage_and_below_zero_rates() -> None:
    """Rule 31: beside its intervals each record states how often the check's interval covered
    zero and how often its upper bound fell below zero, the rate that bears on `worse`, with and
    without autocorrelation, in the protocol's own numbers."""

    note = scorer.summarize([1.0, 2.0], "planner_policy_chain_v1:A")["coverage_note"]
    assert note == scorer.COVERAGE_NOTE
    for stated in (
        "covered zero in 58, 76 and 82 per cent of replicates at 7, 15 and 31 weeks",
        "fell below zero in 20, 12 and 12 per cent",
        "lag-one autocorrelation of 0.2",
        "covered zero in 54, 74 and 78 per cent",
        "fell below zero in 26, 15 and 10 per cent",
    ):
        assert stated in note and stated in PROTOCOL_TEXT


# Rules 28, 32 and 37: what the scorer refuses, and the verdict clauses


def test_the_reading_refuses_what_the_protocol_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence, snapshots, records = _world(tmp_path, monkeypatch, through=10)
    _identity(monkeypatch)
    paths = {
        "receipts": tmp_path / RECEIPTS,
        "records_dir": records,
        "index_file": tmp_path / "index.md",
    }
    with pytest.raises(scorer.ScorerError, match="names no reading"):
        scorer.score(evidence, snapshots, "gw19", **paths)
    # GW20 has not settled: the captures reach GW10 only.
    with pytest.raises(scorer.ScorerError, match="has not settled"):
        scorer.score(evidence, snapshots, "gw20", **paths)
    _outcome_capture(snapshots, 20, settled_through=20, live=False)
    # GW11 is not decided yet.
    with pytest.raises(scorer.ScorerError, match="GW11 is not decided"):
        scorer.score(evidence, snapshots, "gw20", **paths)
    assert not records.exists() and not paths["index_file"].exists()
    # A reading taken already is refused by name.
    records.mkdir()
    (records / "planner_policy_chain_gw20.json").write_text("{}", encoding="utf-8")
    with pytest.raises(scorer.ScorerError, match="taken already"):
        scorer.score(evidence, snapshots, "gw20", **paths)
    (records / "planner_policy_chain_gw20.json").unlink()
    # Evidence that changed under its manifest is refused.
    path = next((evidence / "gw07").glob("p1000-*.json"))
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(scorer.ScorerError, match=r"no longer match|does not match"):
        scorer.read_evidence(evidence, 10, scorer.read_receipts(paths["receipts"]))


def test_a_reading_waits_until_its_own_gameweek_has_settled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 28: with GW20 decided and every week through GW19 settled, the gw20 reading still
    waits, and a capture in which GW20 is finished but its data not yet checked does not settle
    it."""

    evidence, snapshots, records = _world(tmp_path, monkeypatch, settled_through=19)
    _identity(monkeypatch)
    assert (evidence / "gw20" / "manifest.json").is_file()
    bootstrap = json.loads(_bootstrap(20))
    next(event for event in bootstrap["events"] if event["id"] == 20)["data_checked"] = False
    write_snapshot(
        snapshots,
        source="fpl-live",
        captured_at_utc=_stamp(_deadline(20) + timedelta(hours=5)),
        payloads={
            BOOTSTRAP_PAYLOAD: json.dumps(bootstrap).encode("utf-8"),
            live_payload(20): _live(POINTS),
        },
    )
    index = tmp_path / "index.md"
    with pytest.raises(scorer.ScorerError, match="GW20 has not settled in any capture"):
        scorer.score(
            evidence,
            snapshots,
            "gw20",
            receipts=tmp_path / RECEIPTS,
            records_dir=records,
            index_file=index,
        )
    assert not records.exists() and not index.exists()


def test_a_decided_record_the_scorer_cannot_score_refuses_the_reading_by_its_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rules 22 and 26: a decided chain's advice is scored or the reading stops, naming the
    chain; it is never passed over as a week that chain did not play, nor scored as zero."""

    evidence, snapshots, records = _world(tmp_path, monkeypatch, through=6)
    _identity(monkeypatch)

    def bench_vice(document: dict[str, Any]) -> None:
        if (document["profile"], document["arm"]) == ("p950", "hold_5"):
            document["advice"]["vice_captain"] = 2

    _rewrite_week(evidence, tmp_path / RECEIPTS, 6, bench_vice)
    _outcome_capture(snapshots, 20, settled_through=20, live=False)
    _read_through(monkeypatch, 6)
    index = tmp_path / "index.md"
    with pytest.raises(
        scorer.ScorerError, match=r"^p950 hold_5: Recorded vice-captain must start\.$"
    ):
        scorer.score(
            evidence,
            snapshots,
            "gw20",
            receipts=tmp_path / RECEIPTS,
            records_dir=records,
            index_file=index,
        )
    assert not records.exists() and not index.exists()


def test_the_scorer_runs_only_from_its_own_merge_commit_on_a_clean_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rules 2 and 37: a clean tree, then a fetch of origin, then the add commit looked for on
    origin's develop line; HEAD must equal it and be an ancestor of develop."""

    asked: list[tuple[str, ...]] = []

    def git(*arguments: str, cwd: Path | None = None) -> str:
        asked.append(arguments)
        if arguments[:1] in (("status",), ("fetch",)):
            return ""
        if arguments[:2] == ("rev-parse", "--is-shallow-repository"):
            return "false"
        if arguments[:2] == ("rev-parse", "--verify"):
            return "tip"
        if arguments[:2] == ("rev-parse", "HEAD"):
            return "head"
        if arguments[:1] == ("log",):
            return "merge 2026-10-20T13:00:00+03:00"
        raise AssertionError(arguments)

    monkeypatch.setattr(scorer, "_git", git)
    monkeypatch.setattr(scorer, "_git_code", lambda *arguments: 0)
    with pytest.raises(scorer.ScorerError, match="merge commit merge; HEAD is head"):
        scorer.source_identity()
    commands = [arguments[0] for arguments in asked]
    assert commands.index("fetch") < commands.index("log")
    log = asked[commands.index("log")]
    assert log[log.index("--") - 1] == scorer.DEVELOP == "refs/remotes/origin/develop"
    # Rule 2: the committer instant, recorded in UTC whatever offset the commit carries.
    assert scorer.scorer_merge()["committed_utc"] == "2026-10-20T10:00:00+00:00"

    def at_merge(*arguments: str, cwd: Path | None = None) -> str:
        if arguments[:1] == ("log",):
            return "merge 2026-10-20T10:00:00Z"
        if arguments[:2] == ("rev-parse", "--is-shallow-repository"):
            return "false"
        return "merge" if arguments[:1] == ("rev-parse",) else ""

    monkeypatch.setattr(scorer, "_git", at_merge)
    monkeypatch.setattr(scorer, "_git_code", lambda *arguments: 1)
    with pytest.raises(scorer.ScorerError, match="not an ancestor of refs/remotes/origin/develop"):
        scorer.source_identity()
    monkeypatch.setattr(
        scorer, "_git", lambda *a, **k: "true" if "--is-shallow-repository" in a else ""
    )
    with pytest.raises(scorer.ScorerError, match="shallow clone"):
        scorer.source_identity()
    monkeypatch.setattr(scorer, "_git", lambda *a, **k: "dirty" if a[:1] == ("status",) else "x")
    with pytest.raises(scorer.ScorerError, match="not clean"):
        scorer.source_identity()
    monkeypatch.setattr(scorer, "_git", lambda *a, **k: "")
    with pytest.raises(scorer.ScorerError, match="has not merged"):
        scorer.scorer_merge()


# Rules 2, 28 and 37 on a real history: origin, a kept feature branch and develop's squash


def _git_in(root: Path, *arguments: str, when: str | None = None) -> str:
    """Git in a temporary repository, with a fixed identity, and with ``when`` as the author's,
    the committer's and the tagger's instant."""

    environment = dict(os.environ)
    if when is not None:
        environment |= {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    ).stdout.strip()


def _commit(work: Path, files: dict[str, str], message: str, when: str) -> str:
    for path, text in files.items():
        target = work / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    _git_in(work, "add", "-A")
    _git_in(work, "commit", "-q", "-m", message, when=when)
    return _git_in(work, "rev-parse", "HEAD")


def _repository(tmp_path: Path) -> Path:
    """Origin holds develop with the protocol, and a kept branch whose feature commit added the
    scorer, which develop has not taken yet. Returns the clone the history is written from."""

    origin, work = tmp_path / "origin.git", tmp_path / "work"
    _git_in(tmp_path, "init", "-q", "--bare", "-b", "develop", str(origin))
    _git_in(tmp_path, "init", "-q", "-b", "develop", str(work))
    _git_in(work, "remote", "add", "origin", str(origin))
    _commit(
        work,
        {scorer.PROTOCOL_FILE: "protocol\n", "docs/measurements_index.md": "# Index\n"},
        "the protocol",
        "2026-10-01T09:00:00+03:00",
    )
    _git_in(work, "push", "-q", "origin", "develop")
    _git_in(work, "switch", "-q", "-c", "scorer")
    _commit(work, {scorer.SCORER_FILE: "scorer\n"}, "add the scorer", "2026-10-07T20:00:00+03:00")
    _git_in(work, "push", "-q", "origin", "scorer")
    _git_in(work, "switch", "-q", "develop")
    return work


def _squash(work: Path) -> str:
    """Develop takes the kept branch as one squash commit, made at 21:30 in UTC+3."""

    _git_in(work, "merge", "-q", "--squash", "scorer")
    _git_in(work, "commit", "-q", "-m", "the scorer, squashed", when="2026-10-08T21:30:00+03:00")
    _git_in(work, "push", "-q", "origin", "develop")
    return _git_in(work, "rev-parse", "HEAD")


def _checkout(tmp_path: Path, commit: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fresh clone of origin, clean at ``commit``, that the scorer runs from."""

    checkout = tmp_path / "checkout"
    _git_in(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(checkout))
    _git_in(checkout, "switch", "-q", "--detach", commit)
    monkeypatch.setattr(scorer, "REPOSITORY", checkout)
    package = checkout / "src" / "squadopt" / "__init__.py"
    monkeypatch.setattr(scorer, "squadopt", SimpleNamespace(__file__=str(package)))
    return checkout


def test_the_merge_commit_is_develop_s_squash_commit_never_the_feature_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rules 2 and 37 on a real history: the scorer's merge is the commit on origin's develop
    first-parent line that added it. A clean checkout of the kept branch's feature commit is
    refused before develop takes it and after; the squash commit runs, found by the scorer's own
    fetch, and its instant is recorded in UTC."""

    work = _repository(tmp_path)
    feature = _git_in(work, "rev-parse", "scorer")
    checkout = _checkout(tmp_path, feature, monkeypatch)
    with pytest.raises(scorer.ScorerError, match="has not merged"):
        scorer.source_identity()
    squash = _squash(work)
    with pytest.raises(scorer.ScorerError, match=f"merge commit {squash}; HEAD is {feature}"):
        scorer.source_identity()
    _git_in(checkout, "switch", "-q", "--detach", squash)
    identity = scorer.source_identity()
    assert identity["scorer_merge_commit"] == squash != feature
    assert identity["scorer_merged_utc"] == "2026-10-08T18:30:00+00:00"
    assert identity["develop_commit"] == squash
    assert _git_in(checkout, "status", "--porcelain") == ""
    # Origin out of reach refuses the reading: develop is never read stale.
    _git_in(checkout, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    with pytest.raises(scorer.ScorerError, match="git fetch failed"):
        scorer.source_identity()
    # A shallow clone of a later develop is refused: its one commit seems to add every file.
    _commit(work, {"later.txt": "later\n"}, "a later change", "2026-10-09T09:00:00+03:00")
    _git_in(work, "push", "-q", "origin", "develop")
    shallow = tmp_path / "shallow"
    origin = (tmp_path / "origin.git").as_uri()
    _git_in(tmp_path, "clone", "-q", "--depth", "1", origin, str(shallow))
    monkeypatch.setattr(scorer, "REPOSITORY", shallow)
    package = shallow / "src" / "squadopt" / "__init__.py"
    monkeypatch.setattr(scorer, "squadopt", SimpleNamespace(__file__=str(package)))
    with pytest.raises(scorer.ScorerError, match="shallow clone"):
        scorer.source_identity()


def test_a_reading_committed_after_the_merge_is_refused_as_taken_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rules 28, 31 and 37: a clean checkout of the merge commit cannot hold a reading committed
    after it. The scorer fetches origin and refuses a record found in committed history on any
    branch, or in a reflog, before it reads any capture."""

    work = _repository(tmp_path)
    squash = _squash(work)
    checkout = _checkout(tmp_path, squash, monkeypatch)
    read: list[Path] = []
    monkeypatch.setattr(scorer, "_captures", lambda root: read.append(root) or [])
    monkeypatch.setattr(scorer, "read_receipts", lambda path: {})
    records, index = checkout / "docs" / "research", checkout / "docs" / "measurements_index.md"

    def take(reading: str) -> None:
        scorer.score(
            tmp_path / "evidence",
            tmp_path / "snapshots",
            reading,
            receipts=tmp_path / RECEIPTS,
            records_dir=records,
            index_file=index,
        )

    # Nothing is taken yet: the check passes, and the reading waits for its gameweek.
    with pytest.raises(scorer.ScorerError, match="has not settled"):
        take("gw20")
    # gw20 is taken in another checkout and committed on develop after the scorer's merge.
    taken = _commit(
        work,
        {
            "docs/research/planner_policy_chain_gw20.json": "{}\n",
            "docs/research/planner_policy_chain_gw20.md": "# gw20\n",
        },
        "the gw20 reading",
        "2027-01-02T12:00:00+03:00",
    )
    _git_in(work, "push", "-q", "origin", "develop")
    # gw38's twin alone is committed on a branch develop has not taken.
    _git_in(work, "switch", "-q", "-c", "reading-gw38")
    side = _commit(
        work,
        {"docs/research/planner_policy_chain_gw38.md": "# gw38\n"},
        "the gw38 reading",
        "2027-05-30T12:00:00+03:00",
    )
    _git_in(work, "push", "-q", "origin", "reading-gw38")
    read.clear()
    assert not (records / "planner_policy_chain_gw20.json").exists()
    with pytest.raises(scorer.ScorerError, match=rf"gw20 reading was taken already: .* at {taken}"):
        take("gw20")
    with pytest.raises(scorer.ScorerError, match=rf"gw38 reading was taken already: .* at {side}"):
        take("gw38")
    # A reading commit that a later push drops from its branch is still found, once this
    # repository has fetched it: the remote-tracking ref's reflog holds it.
    _git_in(work, "push", "-q", "--force", "origin", f"{squash}:refs/heads/reading-gw38")
    with pytest.raises(scorer.ScorerError, match=rf"gw38 reading was taken already: .* at {side}"):
        take("gw38")
    # With every reflog expired, as gc expires old entries between the two readings, a reading
    # on a branch is still found from the branch itself.
    _git_in(checkout, "reflog", "expire", "--expire=all", "--all")
    with pytest.raises(scorer.ScorerError, match=rf"gw20 reading was taken already: .* at {taken}"):
        take("gw20")
    assert read == []
    assert _git_in(checkout, "rev-parse", "HEAD") == squash
    assert _git_in(checkout, "status", "--porcelain") == ""


def test_a_reading_written_in_another_worktree_is_refused_as_taken_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rules 28 and 37: a reading written in one worktree of the repository and not committed
    is found from another clean worktree of the merge commit, before any capture is read."""

    work = _repository(tmp_path)
    squash = _squash(work)
    checkout = _checkout(tmp_path, squash, monkeypatch)
    read: list[Path] = []
    monkeypatch.setattr(scorer, "_captures", lambda root: read.append(root) or [])
    monkeypatch.setattr(scorer, "read_receipts", lambda path: {})
    other = tmp_path / "other"
    _git_in(checkout, "worktree", "add", "--detach", str(other), squash)
    twin = other / "docs" / "research" / "planner_policy_chain_gw20.md"
    twin.write_text("# gw20\n", encoding="utf-8")
    paths = {
        "receipts": tmp_path / RECEIPTS,
        "records_dir": checkout / "docs" / "research",
        "index_file": checkout / "docs" / "measurements_index.md",
    }
    with pytest.raises(scorer.ScorerError, match=r"gw20 reading was taken already: .*other"):
        scorer.score(tmp_path / "evidence", tmp_path / "snapshots", "gw20", **paths)
    assert read == []
    # Another reading's record is no bar: gw38 goes on until it reads the interim record from
    # develop, which holds none, since the twin in the other worktree was never merged (rule 25).
    with pytest.raises(scorer.ScorerError, match="develop on origin holds no"):
        scorer.score(tmp_path / "evidence", tmp_path / "snapshots", "gw38", **paths)
    assert read == []
    assert _git_in(checkout, "status", "--porcelain") == ""


def test_the_interim_record_is_read_from_develop_as_the_merge_that_first_added_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rules 24 and 25 on a real history: the final reading runs from the scorer's merge commit,
    which the interim record postdates, so it reads the record from origin's develop after its
    own fetch. It never reads it from the checkout or from a branch develop has not taken, and
    reads it as the commit on develop's first-parent line that first added it holds it, whatever
    was written over it later. A clone that tracks another branch only, and holds a branch named
    origin/develop, reads the same."""

    work = _repository(tmp_path)
    squash = _squash(work)
    checkout = _checkout(tmp_path, squash, monkeypatch)
    path, _ = scorer.record_paths("gw20")
    scorer.fetch_origin()
    with pytest.raises(scorer.ScorerError, match=f"develop on origin holds no {path}"):
        scorer.interim_reading()

    def commit_record(document: dict[str, Any], message: str, when: str) -> str:
        target = work / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(document_bytes(document))
        _git_in(work, "add", "-A")
        _git_in(work, "commit", "-q", "-m", message, when=when)
        return _git_in(work, "rev-parse", "HEAD")

    # The interim reading, committed on a branch of its own, is not develop's until merged.
    first = {"protocol": scorer.PROTOCOL_ID, "reading": "gw20", "weeks": []}
    _git_in(work, "switch", "-q", "-c", "reading-gw20")
    feature = commit_record(first, "the gw20 reading", "2027-01-02T12:00:00+03:00")
    _git_in(work, "push", "-q", "origin", "reading-gw20")
    scorer.fetch_origin()
    with pytest.raises(scorer.ScorerError, match="develop on origin holds no"):
        scorer.interim_reading()
    # Develop takes it in a merge commit. Later the file is written over on develop, then
    # removed and added again, a second commit that adds it on develop's line.
    _git_in(work, "switch", "-q", "develop")
    _git_in(
        work,
        "merge",
        "-q",
        "--no-ff",
        "-m",
        "the gw20 reading, merged",
        "reading-gw20",
        when="2027-01-03T12:00:00+03:00",
    )
    merged = _git_in(work, "rev-parse", "HEAD")
    commit_record(
        {**first, "weeks": [{"gameweek": 6}]},
        "the interim record, written over",
        "2027-01-04T12:00:00+03:00",
    )
    _git_in(work, "rm", "-q", path)
    _git_in(work, "commit", "-q", "-m", "the interim record, removed", when="2027-01-05T12:00:00Z")
    again = commit_record(
        {**first, "weeks": [{"gameweek": 7}]},
        "the interim record, added again",
        "2027-01-06T12:00:00+03:00",
    )
    _git_in(work, "push", "-q", "origin", "develop")
    scorer.fetch_origin()
    read = scorer.interim_reading()
    assert read.record == first
    assert read.added_commit == merged != feature
    assert read.develop_commit == again
    assert read.sha256 == hashlib.sha256(document_bytes(first)).hexdigest()
    assert not (checkout / path).exists()
    assert _git_in(checkout, "rev-parse", "HEAD") == squash
    assert _git_in(checkout, "status", "--porcelain") == ""
    narrow = tmp_path / "narrow"
    origin = str(tmp_path / "origin.git")
    _git_in(tmp_path, "clone", "-q", "--single-branch", "--branch", "scorer", origin, str(narrow))
    _git_in(narrow, "branch", "origin/develop")
    monkeypatch.setattr(scorer, "REPOSITORY", narrow)
    scorer.fetch_origin()
    assert scorer.interim_reading() == read


def test_an_interim_record_that_is_not_one_json_object_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rule 25: what develop holds as the interim record is read as one JSON object, or the
    final reading is refused, in the scorer's words and never as a traceback."""

    shown: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        scorer,
        "_git",
        lambda *arguments, cwd=None: "e" * 40 if "rev-parse" in arguments else "a" * 40,
    )
    for raw, message in (
        (b'{"protocol": ', "as a{40} added it is not JSON"),
        (b"\xff\xfe", "as a{40} added it is not JSON"),
        (b"[]\n", "as a{40} added it is not a record"),
    ):
        monkeypatch.setattr(
            scorer, "_git_bytes", lambda *arguments, cwd=None, r=raw: shown.append(arguments) or r
        )
        with pytest.raises(scorer.ScorerError, match=message):
            scorer.interim_reading()
    path, _ = scorer.record_paths("gw20")
    assert shown[0] == ("show", f"{'a' * 40}:{path}", "--")


def test_no_capture_is_read_before_the_refusals_that_need_no_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rules 24, 25 and 28: the reading's record, twin and index row in the checkout, before
    anything else; then its record in committed history, its record in another worktree,
    origin's release tags, the receipts file and, for the final reading, the interim record on
    develop are checked before the first capture is read, in that order."""

    read: list[Path] = []
    monkeypatch.setattr(scorer, "_captures", lambda root: read.append(root) or [])
    identified: list[str] = []
    monkeypatch.setattr(scorer, "source_identity", lambda: identified.append("identity") or {})

    def tags_refused() -> tuple[scorer.ReleaseTag, ...]:
        raise scorer.ScorerError("a release tag differs from origin's")

    monkeypatch.setattr(scorer, "release_tags", tags_refused)
    paths = {
        "receipts": tmp_path / RECEIPTS,
        "records_dir": tmp_path / "records",
        "index_file": tmp_path / "index.md",
    }
    # A row in the checkout's index that links the reading's record refuses it first.
    paths["index_file"].write_text(
        "- [Planner policy chain, gw20 reading](research/planner_policy_chain_gw20.json)\n",
        encoding="utf-8",
    )
    with pytest.raises(scorer.ScorerError, match=r"taken already: .*index\.md links its record"):
        scorer.score(tmp_path, tmp_path, "gw20", **paths)
    assert identified == []
    paths["index_file"].unlink()
    monkeypatch.setattr(scorer, "committed_reading", lambda reading: "a" * 40)
    monkeypatch.setattr(scorer, "written_reading", lambda reading: "elsewhere.md")
    with pytest.raises(scorer.ScorerError, match=r"committed history at a{40}"):
        scorer.score(tmp_path, tmp_path, "gw20", **paths)
    monkeypatch.setattr(scorer, "committed_reading", lambda reading: None)
    with pytest.raises(scorer.ScorerError, match=r"taken already: elsewhere.md exists"):
        scorer.score(tmp_path, tmp_path, "gw20", **paths)
    monkeypatch.setattr(scorer, "written_reading", lambda reading: None)
    with pytest.raises(scorer.ScorerError, match="differs from origin's"):
        scorer.score(tmp_path, tmp_path, "gw20", **paths)
    # Rule 24: no receipts file has been transcribed, so the reading stops before any capture.
    monkeypatch.setattr(scorer, "release_tags", lambda: ())
    with pytest.raises(scorer.ScorerError, match=r"receipts file .* cannot be read"):
        scorer.score(tmp_path, tmp_path, "gw20", **paths)
    assert read == [] and not (tmp_path / "records").exists()
    # Rule 25: the final reading stops at the interim record develop does not hold yet.
    monkeypatch.setattr(scorer, "read_receipts", lambda path: {})

    def no_interim() -> scorer.InterimRecord:
        raise scorer.ScorerError("develop on origin holds no planner_policy_chain_gw20.json")

    monkeypatch.setattr(scorer, "interim_reading", no_interim)
    with pytest.raises(scorer.ScorerError, match="develop on origin holds no"):
        scorer.score(tmp_path, tmp_path, "gw38", **paths)
    assert read == []
    # The interim reading reads no interim record, and goes on to wait for its gameweek.
    with pytest.raises(scorer.ScorerError, match="GW20 has not settled"):
        scorer.score(tmp_path, tmp_path, "gw20", **paths)
    assert read == [tmp_path] and not (tmp_path / "records").exists()


def test_the_refusals_that_need_no_outcome_come_before_the_first_outcome_is_scored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rules 6, 14, 25, 28 and 37: a receipt deadline that is not an instant, a record whose
    truncation is not rule 14's, a declared producer change the evidence contradicts and an
    interim record of other decisions or another scorer each refuse the reading before any
    week's outcome capture is chosen. A reading they refuse has scored no outcome, so the run
    after the correction is the first to read one. Each case falls on GW07, which the scorer
    would otherwise reach only after scoring GW06."""

    evidence, snapshots, records = _world(tmp_path, monkeypatch, through=7)
    _identity(monkeypatch)
    _outcome_capture(snapshots, 38, settled_through=38, live=False)
    _read_through(monkeypatch, 7)
    chosen: list[int] = []
    choose = scorer.outcome_capture

    def spied(captures: Any, gameweek: int, deadline: str | None = None) -> scorer.Outcome:
        chosen.append(gameweek)
        return choose(captures, gameweek, deadline)

    monkeypatch.setattr(scorer, "outcome_capture", spied)
    receipts = tmp_path / RECEIPTS
    paths = {"receipts": receipts, "records_dir": records, "index_file": tmp_path / "index.md"}
    week = evidence / "gw07"
    kept = {path: path.read_bytes() for path in [*week.rglob("*"), receipts] if path.is_file()}

    def unreadable_deadline() -> None:
        _rewrite(week / "receipt.json", lambda receipt: receipt.update(deadline_utc="Friday"))
        _reseal(evidence, 7)
        _repost(receipts, evidence, 7)

    def truncated() -> None:
        _rewrite_week(evidence, receipts, 7, lambda record: record["policy"].update(truncated=True))

    contradicted = {
        "source": "issuecomment-3",
        "changes": [{"model_version": MINUTES, "first_week": 7}],
    }
    for change, producer_changes, message in (
        (unreadable_deadline, scorer.NO_PRODUCER_CHANGES, "GW07's receipt: "),
        (truncated, scorer.NO_PRODUCER_CHANGES, "GW07 p1000 hold_3: the record's truncation"),
        (lambda: None, contradicted, f"from GW07 names {MINUTES}, and that week's receipt"),
    ):
        change()
        with pytest.raises(scorer.ScorerError, match=message):
            scorer.score(evidence, snapshots, "gw20", producer_changes=producer_changes, **paths)
        assert chosen == [] and not records.exists()
        for path, raw in kept.items():
            path.write_bytes(raw)
    scorer.score(evidence, snapshots, "gw20", **paths)
    assert chosen == [6, 7]
    chosen.clear()
    interim = _on_develop(monkeypatch, records)

    def other_scorer(record: dict[str, Any]) -> None:
        record["identity"]["scorer_merge_commit"] = "9" * 40

    def other_decision(record: dict[str, Any]) -> None:
        record["weeks"][1]["decision_capture"] = "capture-elsewhere"

    for change, message in (
        (other_scorer, "rule 37 runs both from one merge commit"),
        (other_decision, "GW07: the interim record was read from other decisions"),
    ):
        record = json.loads(json.dumps(interim.record))
        change(record)
        monkeypatch.setattr(scorer, "interim_reading", lambda r=record: replace(interim, record=r))
        with pytest.raises(scorer.ScorerError, match=message):
            scorer.score(evidence, snapshots, "gw38", **paths)
        assert chosen == [] and not (records / "planner_policy_chain_gw38.json").exists()
    monkeypatch.setattr(scorer, "interim_reading", lambda: interim)
    scorer.score(evidence, snapshots, "gw38", **paths)
    assert chosen == [6, 7]


@pytest.mark.parametrize(
    ("weeks", "interval", "mean", "final", "expected"),
    [
        (14, [1.0, 2.0], 1.5, True, "insufficient_evidence"),
        (15, None, 1.5, True, "insufficient_evidence"),
        (15, [-3.0, -1.0], -2.0, True, "worse"),
        (15, [0.2, 2.0], 1.0, True, "better"),
        (15, [0.1, 0.6], 0.3, True, "not_separated"),
        (31, [-1.0, 1.0], 0.0, True, "not_separated"),
        (31, [0.2, 2.0], 1.0, False, None),
        # Rule 32's boundaries: a mean of exactly 0.5 is "at least 0.5"; a bound of exactly 0
        # is neither above nor below 0.
        (15, [0.1, 0.9], 0.5, True, "better"),
        (15, [0.1, 0.9], 0.49, True, "not_separated"),
        (15, [0.0, 2.0], 1.0, True, "not_separated"),
        (15, [-2.0, 0.0], -1.0, True, "not_separated"),
    ],
)
def test_the_verdict_is_the_first_clause_that_holds(
    weeks: int, interval: list[float] | None, mean: float, final: bool, expected: str | None
) -> None:
    summary = {"weeks": weeks, "interval": interval, "mean": mean}
    assert scorer.verdict(summary, final=final) == expected


def test_summaries_carry_the_interval_only_from_six_weeks_and_the_detectable_effect() -> None:
    few = scorer.summarize([1.0, 2.0, 3.0, 4.0, 5.0], "planner_policy_chain_v1:A")
    assert few["weeks"] == 5 and few["interval"] is None and few["interval_blocks_of_8"] is None
    assert few["detectable_effect"] == pytest.approx(
        scorer.detectable_effect(few["standard_deviation"], 5, policy=scorer.DETECTION)
    )
    enough = scorer.summarize([1.0, -2.0, 3.0, 4.0, -5.0, 6.0, 2.0], "planner_policy_chain_v1:A")
    low, high = enough["interval"]
    assert low <= enough["mean"] <= high
    assert enough["autocorrelation"]["1"] is not None and enough["autocorrelation"]["4"] is not None
    assert scorer.summarize([], "planner_policy_chain_v1:B")["mean"] is None


def test_six_scored_weeks_give_an_interval_on_blocks_of_four() -> None:
    """Rules 30 and 33: exactly six scored weeks print an interval, on blocks of 4, and the
    detectable effect at 0.90 and 0.80, each computed here. At six weeks on blocks of 4 the
    resampled means take only nine values, and both bounds fall on the lowest and the highest
    of them, so a level of 0.95, 1000 resamples or seed 1 gives the same interval; the
    fifteen-week test below holds those."""

    series, candidate = [3.0, -1.0, 4.0, 1.0, -5.0, 9.0], "planner_policy_chain_v1:A"
    stated = _stated_interval(series, candidate)
    for blocks in (3, 8):
        assert _stated_interval(series, candidate, blocks=blocks) != stated
    summary = scorer.summarize(series, candidate)
    assert summary["weeks"] == 6 and summary["mean"] == pytest.approx(statistics.fmean(series))
    assert summary["interval"] == stated
    assert summary["interval_blocks_of_8"] == _stated_interval(series, candidate, blocks=8)
    assert summary["detectable_effect"] == detectable_effect(
        statistics.stdev(series), 6, policy=STATED_DETECTION
    )


def test_both_intervals_are_the_ones_the_protocol_states_on_fifteen_weeks() -> None:
    """Rule 30: blocks of 4 and, beside them, blocks of 8, each at a level of 0.90 with 5000
    resamples and seed 0. On these fifteen weeks every one of those numbers moves its interval,
    so a changed constant in the scorer cannot pass."""

    series = [3.4, -1.7, 4.9, 0.8, -5.3, 9.1, 2.6, -6.2, 5.5, 3.3, -2.8, 7.4, 0.1, -4.6, 8.2]
    candidate = "planner_policy_chain_v1:B"
    paired = [("2026-27", value) for value in series]
    for blocks, others in ((4, (3, 8)), (8, (4, 7, 9))):
        stated = _stated_interval(series, candidate, blocks=blocks)
        policy = replace(STATED_POLICY, moving_block_length=blocks)
        for changed in (
            *(replace(policy, moving_block_length=other) for other in others),
            replace(policy, confidence_level=0.95),
            replace(policy, bootstrap_resamples=1000),
            replace(policy, deterministic_seed=1),
        ):
            moved = season_aware_moving_block_interval(
                paired, policy=changed, candidate_id=candidate
            )
            assert list(moved) != stated
    summary = scorer.summarize(series, candidate)
    assert summary["interval"] == _stated_interval(series, candidate)
    assert summary["interval_blocks_of_8"] == _stated_interval(series, candidate, blocks=8)


# Rule 25: the outcome capture


def test_the_outcome_capture_is_the_latest_settled_one_with_the_live_payload(
    tmp_path: Path,
) -> None:
    root = tmp_path / "snapshots"
    root.mkdir()
    unsettled = _outcome_capture(root, 6, settled_through=5, hours_after=2)
    first = _outcome_capture(root, 6, hours_after=5)
    later = _outcome_capture(root, 6, hours_after=9)
    captures = [read_snapshot(root, s) for s in (unsettled, first, later)]
    outcome = scorer.outcome_capture(captures, 6)
    assert outcome.snapshot_id == later and outcome.reason is None
    assert outcome.deadline_utc == _stamp(_deadline(6))
    assert scorer.outcome_capture(captures[:1], 6).reason == "not_settled"
    without_live = read_snapshot(root, _outcome_capture(root, 7, live=True, hours_after=1))
    bare = read_snapshot(root, _outcome_capture(root, 8, live=False))
    assert scorer.outcome_capture([bare], 8).reason == "missing_outcomes"
    assert scorer.outcome_capture([without_live], 7).reason is None
    # A second capture at the latest instant with other points: two captures, not one twice.
    rival = read_snapshot(root, _outcome_capture(root, 6, hours_after=9, points=POINTS | {8: 0}))
    assert rival.metadata.snapshot_id != later
    assert rival.metadata.captured_at_utc == captures[2].metadata.captured_at_utc
    tied = scorer.outcome_capture([*captures, rival], 6)
    assert tied.reason == "tied_outcome_captures" and tied.snapshot_id is None
    assert scorer.settled(captures, 6) and not scorer.settled(captures, 7)


def test_a_capture_at_the_deadline_instant_is_read_and_one_before_it_never_is(
    tmp_path: Path,
) -> None:
    """Rule 25: the outcome capture is chosen from the captures at or after the deadline, so
    one taken at the instant itself is read, and one taken before it is not, whatever it
    says."""

    root = tmp_path / "snapshots"
    root.mkdir()
    at = read_snapshot(root, _outcome_capture(root, 6, hours_after=0))
    before = read_snapshot(root, _outcome_capture(root, 6, hours_after=-0.5))
    outcome = scorer.outcome_capture([before, at], 6)
    assert outcome.deadline_utc == _stamp(_deadline(6))
    assert outcome.snapshot_id == at.metadata.snapshot_id and outcome.reason is None
    assert scorer.outcome_capture([before], 6).reason == "not_settled"


# Rule 3: the release tag live at the deadline, and the fixed diff test


def test_the_release_binding_reads_the_tag_live_strictly_before_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rule 3: the latest release tag created strictly before the deadline, named with its
    object id, on which the fixed diff test runs. None before it, a tie, or a latest tag origin
    does not list, is unknown."""

    def tag(name: str, digit: str, created: str) -> scorer.ReleaseTag:
        return scorer.ReleaseTag(name, digit * 40, "c" * 40, scorer._instant(created))

    tags = (
        tag("site-2026-27-gw06-fix15", "1", "2026-10-04T23:18:44+03:00"),
        tag("site-2026-27-gw06-fix16", "2", "2026-10-05T03:51:09+03:00"),
        tag("site-2026-27-gw07-fix1", "3", "2026-10-10T13:00:00+03:00"),
    )
    asked: list[tuple[str, str, tuple[str, ...]]] = []

    def diff(left: str, right: str, paths) -> bool | None:
        asked.append((left, right, tuple(paths)))
        return paths == scorer.PLANNER_SOURCE

    monkeypatch.setattr(scorer, "_diff_quiet", diff)
    deadline = scorer._instant("2026-10-10T10:00:00Z")
    # gw07-fix1 was made at the deadline instant itself, so it was not live at it.
    assert scorer.release_binding(deadline, "frozen", tags) == {
        "release_tag": "site-2026-27-gw06-fix16",
        "release_tag_object": "2" * 40,
        "planner_source_same": True,
        "binding_source_same": False,
    }
    assert asked == [
        ("2" * 40, "frozen", scorer.PLANNER_SOURCE),
        ("2" * 40, "frozen", scorer.BINDING_SOURCE),
    ]
    later = scorer.release_binding(deadline + timedelta(seconds=1), "frozen", tags)
    assert later["release_tag"] == "site-2026-27-gw07-fix1"
    early = scorer.release_binding(scorer._instant("2026-09-01T10:00:00Z"), "frozen", tags)
    assert early == dict(scorer.RELEASE_UNKNOWN) and len(asked) == 4
    tied = (*tags[:2], tag("site-2026-27-gw06-fix17", "4", "2026-10-05T00:51:09Z"))
    assert scorer.release_at(deadline, tied) is None
    # A tag origin no longer lists, as a deployed tag origin lost would be, decides no week.
    gone = scorer.ReleaseTag(
        "site-2026-27-gw07-fix2",
        "5" * 40,
        "c" * 40,
        scorer._instant("2026-10-10T11:00:00Z"),
        on_origin=False,
    )
    assert gone.to_json()["on_origin"] is False
    assert scorer.release_at(deadline + timedelta(hours=2), (*tags, gone)) is None
    assert scorer.release_at(deadline + timedelta(seconds=1), (*tags, gone)) == tags[2]
    with pytest.raises(scorer.ScorerError, match="names no time zone"):
        scorer._instant("2026-10-10T10:00:00")
    with pytest.raises(scorer.ScorerError, match="cannot be read"):
        scorer._instant("")


def test_the_release_tags_are_origin_s_each_with_its_object_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 3: the release tags are origin's, each with its object id. A lightweight tag, or a
    name the Pages workflow does not deploy, is left out; a tag no branch holds is fetched; one
    only this checkout holds is kept as not on origin; one held here under another object is
    refused, and the fetch does not overwrite it."""

    work = _repository(tmp_path)
    squash = _squash(work)
    for name, when in (
        ("site-2026-27-gw06-fix15", "2026-10-09T10:00:00+03:00"),
        ("site-2026-27-gw06-fix16", "2026-10-10T10:00:00+00:00"),
        ("site-2026-27-gw04-settled-2", "2026-10-09T11:00:00+00:00"),
    ):
        _git_in(work, "tag", "-a", name, "-m", name, squash, when=when)
    _git_in(work, "tag", "site-2026-27-gw06-fix14", squash)
    _git_in(work, "push", "-q", "origin", "--tags")
    checkout = _checkout(tmp_path, squash, monkeypatch)
    listed = _git_in(checkout, "ls-remote", "--tags", "origin").splitlines()
    origin = dict(reversed(line.split("\t")) for line in listed)
    tags = scorer.release_tags()
    assert [tag.name for tag in tags] == ["site-2026-27-gw06-fix15", "site-2026-27-gw06-fix16"]
    assert [tag.object_id for tag in tags] == [origin[f"refs/tags/{tag.name}"] for tag in tags]
    assert {tag.commit for tag in tags} == {squash}
    assert tags[0].to_json()["created_utc"] == "2026-10-09T07:00:00+00:00"
    # GW6's deadline is fix16's own instant, so fix15 is the release live at it.
    assert scorer.release_at(scorer._instant("2026-10-10T10:00:00Z"), tags) == tags[0]
    # A release tag on a commit no branch holds reaches this checkout only by the fetch.
    _git_in(work, "switch", "-q", "--orphan", "hotfix")
    lonely = _commit(work, {"hotfix": "hotfix\n"}, "a hotfix", "2026-10-09T12:00:00+00:00")
    fix17 = "site-2026-27-gw06-fix17"
    _git_in(work, "tag", "-a", fix17, "-m", fix17, lonely, when="2026-10-09T12:00:00+00:00")
    _git_in(work, "push", "-q", "origin", f"refs/tags/{fix17}")
    with pytest.raises(scorer.ScorerError, match=r"gw06-fix17 is \w+ on origin and absent"):
        scorer.release_tags()
    scorer.fetch_origin()
    assert [tag.name for tag in scorer.release_tags()] == [
        "site-2026-27-gw06-fix15",
        "site-2026-27-gw06-fix17",
        "site-2026-27-gw06-fix16",
    ]
    # A tag only this checkout holds, as a deployed tag origin lost would be, is kept by the
    # fetch whatever the checkout's settings, read as not on origin, and decides no week.
    _git_in(checkout, "config", "fetch.prune", "true")
    _git_in(checkout, "config", "fetch.pruneTags", "true")
    gw07 = "site-2026-27-gw07-fix1"
    _git_in(checkout, "tag", "-a", gw07, "-m", "local", squash, when="2026-10-11T09:00:00+00:00")
    # A lightweight tag only this checkout holds deployed nothing, and is left out.
    _git_in(checkout, "tag", "site-2026-27-gw07-fix2", squash)
    scorer.fetch_origin()
    assert _git_in(checkout, "tag", "--list", "site-2026-27-gw07-*").split() == [
        gw07,
        "site-2026-27-gw07-fix2",
    ]
    tags = scorer.release_tags()
    assert [tag.name for tag in tags if not tag.on_origin] == [gw07]
    assert [(tag.name, tag.on_origin) for tag in tags[-2:]] == [
        ("site-2026-27-gw06-fix16", True),
        (gw07, False),
    ]
    assert scorer.release_at(scorer._instant("2026-10-11T08:00:00Z"), tags) == tags[-2]
    assert scorer.release_at(scorer._instant("2026-10-11T10:00:00Z"), tags) is None
    # A tag held here under another object is refused, and the fetch does not overwrite it.
    fix15 = "site-2026-27-gw06-fix15"
    moved = "2026-10-09T13:00:00+00:00"
    _git_in(checkout, "tag", "-f", "-a", fix15, "-m", "moved", squash, when=moved)
    with pytest.raises(scorer.ScorerError, match=r"fix15 is \w+ on origin and \w+ here"):
        scorer.release_tags()
    with pytest.raises(scorer.ScorerError, match="would clobber existing tag"):
        scorer.fetch_origin()


def test_the_diff_test_reads_git_exit_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    codes = iter([0, 1, 128])

    def run(*args: Any, **kwargs: Any) -> Any:
        return type("Completed", (), {"returncode": next(codes)})()

    monkeypatch.setattr(subprocess, "run", run)
    assert scorer._diff_quiet("a", "b", ("x",)) is True
    assert scorer._diff_quiet("a", "b", ("x",)) is False
    assert scorer._diff_quiet("a", "b", ("x",)) is None


def test_the_command_line_refuses_with_a_reason_and_names_only_the_two_readings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _identity(monkeypatch)
    # Rule 24: no reading is taken without the receipts posted on the tracking issue.
    with pytest.raises(SystemExit) as unreceipted:
        scorer.main(
            ["--evidence", str(tmp_path), "--snapshot-root", str(tmp_path), "--reading", "gw20"]
        )
    assert unreceipted.value.code == 2
    assert "required: --receipts" in capsys.readouterr().err
    roots = [
        "--evidence",
        str(tmp_path),
        "--snapshot-root",
        str(tmp_path),
        "--receipts",
        str(tmp_path / RECEIPTS),
    ]
    # Rule 6: the producer changes are stated, if only as none, or nothing is read.
    with pytest.raises(SystemExit) as unstated:
        scorer.main([*roots, "--reading", "gw20"])
    assert unstated.value.code == 2
    assert "required: --producer-changes" in capsys.readouterr().err
    declaration = tmp_path / "producer_changes.json"
    for text in ('{"source": "issuecomment-2"}', "[]"):
        declaration.write_text(text, encoding="utf-8")
        code = scorer.main([*roots, "--producer-changes", str(declaration), "--reading", "gw20"])
        assert code == 2 and "refused: A producer change declaration" in capsys.readouterr().err
    arguments = [*roots, "--producer-changes", "none", "--reading"]
    with pytest.raises(SystemExit) as refused:
        scorer.main([*arguments, "gw19"])
    assert refused.value.code == 2
    # Rules 36 and 37: the command line writes only where the protocol names, so no reading
    # can be taken again into another place.
    for option in ("--records-dir", "--index-file"):
        capsys.readouterr()
        with pytest.raises(SystemExit) as elsewhere:
            scorer.main([*arguments, "gw20", option, str(tmp_path / "elsewhere")])
        assert elsewhere.value.code == 2
        assert f"unrecognized arguments: {option}" in capsys.readouterr().err
    code = scorer.main([*arguments, "gw20"])
    assert code == 2 and "refused:" in capsys.readouterr().err
    assert not (tmp_path / "elsewhere").exists()


# Rule 36: what a reading writes, and the twin rendered from the JSON


def test_each_twin_and_its_index_row_are_rendered_from_the_json_as_written(
    two_readings: dict[str, Any],
) -> None:
    """Rule 36: each twin is rendered from the JSON, so rendering the committed JSON again gives
    the twin byte for byte, with LF line ends on every machine, and the index holds each
    reading's row once. Arms, contrasts, pairings and squads come in the protocol's order, never
    in the sorted order of the JSON's keys."""

    records = two_readings["records_dir"]
    index_text = two_readings["index_file"].read_text(encoding="utf-8")
    for reading, returned in (("gw20", "interim"), ("gw38", "final")):
        written = json.loads((records / f"planner_policy_chain_{reading}.json").read_bytes())
        assert written == two_readings[returned]
        twin = (records / f"planner_policy_chain_{reading}.md").read_bytes()
        assert twin == scorer.render_markdown(written).encode("utf-8")
        assert b"\r" not in twin
        assert index_text.count(scorer.index_row(written)) == 1
    final = (records / "planner_policy_chain_gw38.md").read_text(encoding="utf-8")
    by_arm = final[final.index("| Arm | Gross |") :]
    arms = [by_arm.index(f"\n| {arm} | ") for arm in scorer.ARMS]
    assert arms == sorted(arms)
    by_pair = final[final.index("| Pair | Gross |") :]
    pairs = [by_pair.index(f"\n| {label} | ") for label in scorer.REPORTED_PAIRS]
    assert pairs == sorted(pairs)
    for label in scorer.REPORTED_PAIRS:
        squads = [final.index(f"| {label}, squad {profile} |") for profile in scorer.PROFILES]
        assert squads == sorted(squads)


def test_a_reading_writes_nothing_until_its_twin_and_index_row_are_rendered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Everything a reading writes is rendered before the first write, so a failure to render
    the twin or the index row leaves no record behind and the reading can still be taken. The
    index row is appended last, so a failure between the writes leaves no row, and a retry is
    refused naming what was written. Once taken, a reading's row in the index alone refuses it
    again (rule 28), and each output that exists is named."""

    evidence, snapshots, records = _world(tmp_path, monkeypatch, through=6)
    _identity(monkeypatch)
    _outcome_capture(snapshots, 20, settled_through=20, live=False)
    _read_through(monkeypatch, 6)
    index = tmp_path / "index.md"
    index.write_text("# Measurements Index\n", encoding="utf-8")
    paths = {"receipts": tmp_path / RECEIPTS, "records_dir": records, "index_file": index}

    def broken(record: Any) -> str:
        raise RuntimeError("this cannot be rendered")

    for name in ("render_markdown", "index_row"):
        with pytest.MonkeyPatch.context() as patched:
            patched.setattr(scorer, name, broken)
            with pytest.raises(RuntimeError, match="cannot be rendered"):
                scorer.score(evidence, snapshots, "gw20", **paths)
        assert not records.exists()
        assert index.read_text(encoding="utf-8") == "# Measurements Index\n"

    def interrupted(payload: bytes, destination: Path) -> str:
        raise OSError("the disk is full")

    target = records / "planner_policy_chain_gw20.json"
    twin = target.with_suffix(".md")
    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(scorer, "write_bytes_once", interrupted)
        with pytest.raises(OSError, match="the disk is full"):
            scorer.score(evidence, snapshots, "gw20", **paths)
    assert target.exists() and not twin.exists()
    assert index.read_text(encoding="utf-8") == "# Measurements Index\n"
    with pytest.raises(scorer.ScorerError, match=r"taken already: [^;]*gw20\.json exists\.$"):
        scorer.score(evidence, snapshots, "gw20", **paths)
    target.unlink()
    seen: dict[str, Any] = {}

    def spy(name: str, render: Callable[[Any], str]) -> Callable[[Any], str]:
        def spied(record: Any) -> str:
            seen[name] = record
            return render(record)

        return spied

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(scorer, "render_markdown", spy("twin", scorer.render_markdown))
        patched.setattr(scorer, "index_row", spy("row", scorer.index_row))
        record = scorer.score(evidence, snapshots, "gw20", **paths)
    # Rule 36: the twin and the row are rendered from the record as written, whose keys
    # document_bytes sorts, and never from the record as reading_record built it.
    written = json.loads(target.read_bytes())
    for name in ("twin", "row"):
        assert seen[name] == written and list(seen[name]) == sorted(seen[name]), name
    assert twin.read_bytes() == scorer.render_markdown(record).encode("utf-8")
    assert index.read_text(encoding="utf-8") == (
        "# Measurements Index\n" + scorer.index_row(record) + "\n"
    )
    # A row in the index is a reading taken, even with its files gone.
    target.unlink()
    twin.unlink()
    with pytest.raises(scorer.ScorerError, match=r"taken already: [^;]*index\.md links its record"):
        scorer.score(evidence, snapshots, "gw20", **paths)
    assert not target.exists()
    twin.write_text("# gw20\n", encoding="utf-8")
    with pytest.raises(
        scorer.ScorerError, match=r"taken already: [^;]*gw20\.md exists; [^;]*index\.md links its"
    ):
        scorer.score(evidence, snapshots, "gw20", **paths)


# Rule 24: the receipts posted on the tracking issue, and rules 2 and 3: the frozen source


def test_the_scorer_names_what_it_reads_as_the_runner_wrote_it() -> None:
    """The scorer restates the runner's names for its files, squads, arms and capture set, and
    reads nothing under any other name."""

    assert (scorer.PROTOCOL_FILE, scorer.RUNNER_FILE) == (chain.PROTOCOL_FILE, chain.RUNNER_FILE)
    assert (scorer.PROTOCOL_ID, scorer.SEASON) == (chain.PROTOCOL_ID, chain.SEASON)
    runner_profiles = tuple(f"p{budget}" for budget, _, _ in chain.PROFILES)
    assert runner_profiles == scorer.PROFILES
    assert scorer.ARMS == chain.ARMS
    # Rules 6 and 14: the windows the runner truncates and the versions it admits.
    assert {arm: chain._width(arm) for arm in chain.ARMS} == scorer.WINDOW_WEEKS
    assert scorer.LAST_GAMEWEEK == chain.LAST_GAMEWEEK
    for arm in chain.ARMS:
        for gameweek in range(1, chain.LAST_GAMEWEEK + 1):
            runner = len(chain.window_weeks(arm, gameweek)) < chain._width(arm)
            assert scorer.truncated_by_rule_14(arm, gameweek) is runner
    assert scorer.ADMITTED_MODEL_VERSIONS == chain.ADMITTED_MODEL_VERSIONS
    assert scorer.TEAM_SHARE_VERSION == chain.FOOTBALL_MODEL_VERSION
    assert scorer.SEASON_OPENS == chain.SEASON_OPENS
    assert scorer.CAPTURE_INSTANT.pattern == chain.CAPTURE_INSTANT.pattern


def test_the_receipts_file_is_refused_unless_every_value_is_whole_and_names_its_comment(
    tmp_path: Path,
) -> None:
    """Rule 24: the receipts are the operator's transcription of what the tracking issue
    carries, so each value must be whole, given once and tied to the comment that posted it."""

    receipts = tmp_path / RECEIPTS
    with pytest.raises(scorer.ScorerError, match="cannot be read"):
        scorer.read_receipts(receipts)
    whole = {
        "tracking_issue": "https://github.com/MyManDev/football-squad-optimizer/issues/1",
        "frozen_commit": {"commit": FROZEN, "posted": "issuecomment-0"},
        "manifests": {"gw06": {"sha256": "e" * 64, "posted": "issuecomment-6"}},
    }
    receipts.write_text(json.dumps(whole), encoding="utf-8")
    assert scorer.read_receipts(receipts) == {
        **whole,
        "file_sha256": hashlib.sha256(receipts.read_bytes()).hexdigest(),
    }
    # As Windows PowerShell 5.1 writes UTF-8: a byte order mark first, hashed with the rest.
    marked = b"\xef\xbb\xbf" + json.dumps(whole).encode("utf-8")
    receipts.write_bytes(marked)
    assert scorer.read_receipts(receipts) == {
        **whole,
        "file_sha256": hashlib.sha256(marked).hexdigest(),
    }
    again = '"manifests": {"gw06": {"sha256": "' + "f" * 64 + '", "posted": "q"}, '
    receipts.write_text(json.dumps(whole).replace('"manifests": {', again, 1), encoding="utf-8")
    with pytest.raises(scorer.ScorerError, match="more than once"):
        scorer.read_receipts(receipts)
    for broken, message in (
        ({**whole, "frozen_commit": {"commit": FROZEN[:12], "posted": "p"}}, "no full commit"),
        ({**whole, "manifests": {"gw06": {"sha256": "e" * 63, "posted": "p"}}}, "no full sha256"),
        ({**whole, "manifests": {"gw06": {"sha256": "e" * 64, "posted": " "}}}, "comment"),
        ({**whole, "manifests": {"gw6": {"sha256": "e" * 64, "posted": "p"}}}, "no gameweek"),
        ({**whole, "manifests": {"gw39": {"sha256": "e" * 64, "posted": "p"}}}, "no gameweek"),
        ({**whole, "manifests": {"gw06": {"sha256": "e" * 64}}}, "exactly 'sha256'"),
        (
            {**whole, "manifests": {"gw06": {"sha256": "e" * 64, "posted": "p", "note": "n"}}},
            "exactly 'sha256'",
        ),
        ({**whole, "frozen_commit": {"commit": FROZEN}}, "exactly 'commit'"),
        ({**whole, "manifests": []}, "must map each gwNN"),
        ({key: value for key, value in whole.items() if key != "tracking_issue"}, "exactly"),
        ({**whole, "tracking_issue": " "}, "does not name the chain's tracking issue"),
    ):
        receipts.write_text(json.dumps(broken), encoding="utf-8")
        with pytest.raises(scorer.ScorerError, match=message):
            scorer.read_receipts(receipts)


def _protocol(change: Callable[[dict[str, Any]], object]) -> Callable[[Path, Path], None]:
    def tamper(evidence: Path, receipts: Path) -> None:
        _rewrite(evidence / "protocol.json", change)

    return tamper


def _start_at_gw07(evidence: Path, receipts: Path) -> None:
    _rewrite(evidence / "protocol.json", lambda p: p.update(bound_week=7, first_chain_week=7))


def _start_at_gw07_without_gw06(evidence: Path, receipts: Path) -> None:
    _start_at_gw07(evidence, receipts)
    shutil.rmtree(evidence / "gw06")


def _start_at_gw07_unposted(evidence: Path, receipts: Path) -> None:
    # Every trace of GW06 removed, its receipt too: GW07's arms still hold diverged states.
    _start_at_gw07_without_gw06(evidence, receipts)
    _rewrite(receipts, lambda document: document["manifests"].pop("gw06"))


def _record_rewritten_with_its_manifest(evidence: Path, receipts: Path) -> None:
    _rewrite(evidence / "gw07" / "p1000-served_3.json", lambda r: r["advice"].update(captain=11))
    _reseal(evidence, 7)


def _receipt_not_posted(evidence: Path, receipts: Path) -> None:
    _rewrite(receipts, lambda document: document["manifests"].pop("gw07"))


def _chain_unlisted(evidence: Path, receipts: Path) -> None:
    manifest = evidence / "gw07" / "manifest.json"
    _rewrite(manifest, lambda document: document["records"].pop("p900-one_week.json"))
    _repost(receipts, evidence, 7)


def _record_deleted(evidence: Path, receipts: Path) -> None:
    (evidence / "gw07" / "p900-one_week.json").unlink()
    digest = scorer.evidence_digest(evidence / "gw07")
    _rewrite(evidence / "gw07" / "manifest.json", lambda m: m.update(evidence_digest=digest))
    _repost(receipts, evidence, 7)


def _record_added(evidence: Path, receipts: Path) -> None:
    week = evidence / "gw07"
    shutil.copyfile(week / "p900-one_week.json", week / "p900-hold_4.json")
    digest = scorer.evidence_digest(week)
    _rewrite(week / "manifest.json", lambda m: m.update(evidence_digest=digest))
    _repost(receipts, evidence, 7)


def _records_swapped(evidence: Path, receipts: Path) -> None:
    served, hold = (evidence / "gw07" / f"p1000-{arm}.json" for arm in ("served_3", "hold_3"))
    first, second = served.read_bytes(), hold.read_bytes()
    served.write_bytes(second)
    hold.write_bytes(first)
    _reseal(evidence, 7)
    _repost(receipts, evidence, 7)


def _decided_elsewhere(evidence: Path, receipts: Path) -> None:
    _rewrite(
        evidence / "gw07" / "p950-hold_5.json",
        lambda record: record["provenance"].update(repository_commit="c" * 40),
    )
    _reseal(evidence, 7)
    _repost(receipts, evidence, 7)


def _receipt_rewritten(evidence: Path, receipts: Path) -> None:
    # No record digest covers the receipt; only the week's evidence_digest does.
    _rewrite(evidence / "gw07" / "receipt.json", lambda receipt: receipt.update(model_version="x"))


def _receipt_of_another_week(evidence: Path, receipts: Path) -> None:
    _rewrite(evidence / "gw07" / "receipt.json", lambda receipt: receipt.update(gameweek=8))
    _reseal(evidence, 7)
    _repost(receipts, evidence, 7)


def _manifest_of_another_season(evidence: Path, receipts: Path) -> None:
    _rewrite(evidence / "gw07" / "manifest.json", lambda manifest: manifest.update(season="x"))
    _repost(receipts, evidence, 7)


def _record_of_another_protocol(evidence: Path, receipts: Path) -> None:
    _rewrite(evidence / "gw07" / "p1000-hold_3.json", lambda record: record.update(protocol="x"))
    _reseal(evidence, 7)
    _repost(receipts, evidence, 7)


def _record_of_another_week(evidence: Path, receipts: Path) -> None:
    # GW06's record of the same chain, sealed and posted under GW07.
    name = "p1000-served_3.json"
    shutil.copyfile(evidence / "gw06" / name, evidence / "gw07" / name)
    _reseal(evidence, 7)
    _repost(receipts, evidence, 7)


def _record_unreadable(evidence: Path, receipts: Path) -> None:
    # A record that is no JSON object, sealed and posted as it stands, is refused by name.
    (evidence / "gw07" / "p950-served_5.json").write_text("[]", encoding="utf-8")
    _reseal(evidence, 7)
    _repost(receipts, evidence, 7)


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        (_protocol(lambda protocol: protocol.pop("protocol")), "not this protocol's"),
        (
            _protocol(lambda protocol: protocol.update(repository_commit="c" * 40)),
            "names the frozen commit",
        ),
        (_protocol(lambda protocol: protocol.update(first_chain_week=7)), "does not follow"),
        (_protocol(lambda protocol: protocol.update(bound_week=7)), "does not follow"),
        (_protocol(lambda protocol: protocol.pop("first_chain_week")), "cannot state"),
        (_start_at_gw07, r"\['gw06'\] lie before the first chain week"),
        (_start_at_gw07_without_gw06, r"Receipts were posted for \['gw06'\]"),
        (_start_at_gw07_unposted, "GW07 is not where squad p1000's chains start"),
        (
            _protocol(lambda protocol: protocol.update(dropped_profiles={"p900": "not proved"})),
            "manifest's records are not the kept chains",
        ),
        (_protocol(lambda protocol: protocol.update(dropped_profiles={"p800": "x"})), "drops"),
        (_record_rewritten_with_its_manifest, "not the one posted in issuecomment-07"),
        (_receipt_not_posted, "GW07: no manifest sha256 was posted"),
        (_chain_unlisted, r"manifest's records are not the kept chains: missing \['p900-one"),
        (_record_deleted, r"records beside the manifest are not the kept chains: missing"),
        (_record_added, r"records beside the manifest are not the kept chains: missing \[\], not"),
        (_records_swapped, "not the chain and week its path names"),
        (_record_of_another_week, r"records \('p1000', 'served_3', 6\), not the chain and week"),
        (_decided_elsewhere, "not decided from the frozen commit"),
        (_receipt_rewritten, "GW07: the week's files no longer match their manifest"),
        (_receipt_of_another_week, r"receipt\.json names another gameweek"),
        (_manifest_of_another_season, "names another gameweek, protocol or season"),
        (_record_of_another_protocol, "p1000-hold_3.json is not this protocol's"),
        (_record_unreadable, "p950-served_5.json is not a JSON object"),
    ],
)
def test_evidence_that_its_receipts_or_its_protocol_record_do_not_vouch_for_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: Callable[[Path, Path], None],
    message: str,
) -> None:
    """Rules 3, 9, 10, 24 and 36: protocol.json names this protocol, the posted frozen commit
    and a first chain week that follows its skipped weeks, where every arm of a squad starts
    alike; each week's manifest is the one posted for it; and its records are exactly the kept
    chains, each the chain and week its path names, each decided from the frozen commit. A
    refusal is said as such, never as a traceback."""

    evidence, _, _ = _world(tmp_path, monkeypatch, through=7)
    receipts = tmp_path / RECEIPTS
    scorer.read_evidence(evidence, 7, scorer.read_receipts(receipts))
    tamper(evidence, receipts)
    with pytest.raises(scorer.ScorerError, match=message):
        scorer.read_evidence(evidence, 7, scorer.read_receipts(receipts))


def test_the_frozen_source_is_read_again_from_git_at_the_frozen_commit(tmp_path: Path) -> None:
    """Rule 3: protocol.json's sha256 of the protocol and of the runner, and the merges that
    bound the chain, are what git holds at the frozen commit, read with the runner's own rule;
    a later commit on the line is no frozen source."""

    work = tmp_path / "work"
    _git_in(tmp_path, "init", "-q", "-b", "develop", str(work))
    # Committed at +03:00: the binding commits' instants are read in UTC, as the runner reads them.
    _commit(work, {scorer.PROTOCOL_FILE: "protocol"}, "the protocol", "2026-10-06T15:00:00+03:00")
    frozen = _commit(
        work, {scorer.RUNNER_FILE: "runner"}, "the runner", "2026-10-08T12:00:00+03:00"
    )
    commits = chain.binding_commits(root=work)
    assert chain.frozen_commit(commits) == frozen
    assert commits["runner"]["committed_utc"] == "2026-10-08T09:00:00+00:00"
    later = _commit(
        work, {scorer.RUNNER_FILE: "runner, changed later"}, "later", "2026-10-09T12:00:00+03:00"
    )
    protocol = {
        "repository_commit": frozen,
        "protocol_sha256": hashlib.sha256(b"protocol").hexdigest(),
        "runner_sha256": hashlib.sha256(b"runner").hexdigest(),
        "binding_commits": commits,
    }
    scorer.check_frozen_source(protocol, root=work)
    changed_runner = hashlib.sha256(b"runner, changed later").hexdigest()
    moved = {**commits, "protocol": {**commits["protocol"], "commit": frozen}}
    for changed, message in (
        ({"protocol_sha256": "0" * 64}, "protocol_sha256 is not"),
        ({"runner_sha256": changed_runner}, "runner_sha256 is not"),
        ({"binding_commits": moved}, "binding_commits are not"),
        ({"repository_commit": "f" * 40}, "git cannot read the frozen commit f{40}"),
        ({"repository_commit": frozen[:12]}, "no full frozen commit"),
        ({"repository_commit": later, "runner_sha256": changed_runner}, "not the later"),
    ):
        with pytest.raises(scorer.ScorerError, match=message):
            scorer.check_frozen_source({**protocol, **changed}, root=work)


def test_a_chain_decided_from_the_runners_feature_commit_is_refused(tmp_path: Path) -> None:
    """Rules 2 and 3: the frozen source is the runner's merge on develop's first-parent line.
    The runner run from the feature commit that wrote it names that commit its own merge, and
    git holds the same bytes there; the scorer, run from develop, still refuses it."""

    work = tmp_path / "work"
    _git_in(tmp_path, "init", "-q", "-b", "develop", str(work))
    _commit(work, {scorer.PROTOCOL_FILE: "protocol"}, "the protocol", "2026-10-06T15:00:00+03:00")
    _git_in(work, "switch", "-q", "-c", "runner")
    feature = _commit(
        work, {scorer.RUNNER_FILE: "runner"}, "the runner", "2026-10-06T16:00:00+03:00"
    )
    _git_in(work, "switch", "-q", "--detach", feature)
    from_feature = chain.binding_commits(root=work)
    _git_in(work, "switch", "-q", "develop")
    _git_in(
        work, "merge", "-q", "--no-ff", "-m", "merge", "runner", when="2026-10-06T16:41:00+03:00"
    )
    merged = _git_in(work, "rev-parse", "HEAD")
    from_develop = chain.binding_commits(root=work)
    assert chain.frozen_commit(from_feature) == feature != merged
    assert chain.frozen_commit(from_develop) == merged
    shared = {
        "protocol_sha256": hashlib.sha256(b"protocol").hexdigest(),
        "runner_sha256": hashlib.sha256(b"runner").hexdigest(),
    }
    scorer.check_frozen_source(
        {**shared, "repository_commit": merged, "binding_commits": from_develop}, root=work
    )
    with pytest.raises(scorer.ScorerError, match="a feature commit is never the frozen source"):
        scorer.check_frozen_source(
            {**shared, "repository_commit": feature, "binding_commits": from_feature}, root=work
        )


def test_a_reading_refuses_a_frozen_source_git_does_not_hold_before_it_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 3: the reading reads the frozen source again before anything is written."""

    evidence, snapshots, records = _world(tmp_path, monkeypatch, through=6)
    _identity(monkeypatch)
    _outcome_capture(snapshots, 20, settled_through=20, live=False)
    _read_through(monkeypatch, 6)
    checked: list[object] = []

    def differs(protocol: dict[str, Any], **roots: Any) -> None:
        checked.append(protocol["repository_commit"])
        raise scorer.ScorerError("protocol.json's runner_sha256 is not the sha256 of the runner")

    monkeypatch.setattr(scorer, "check_frozen_source", differs)
    index = tmp_path / "index.md"
    with pytest.raises(scorer.ScorerError, match="runner_sha256"):
        scorer.score(
            evidence,
            snapshots,
            "gw20",
            receipts=tmp_path / RECEIPTS,
            records_dir=records,
            index_file=index,
        )
    assert checked == [FROZEN] and not records.exists() and not index.exists()


# Rule 26: the end state's sale value, and the capture set and deadline rule 25 reads


def test_each_reading_names_its_receipts_and_prices_its_end_state_at_its_own_outcome_capture(
    two_readings: dict[str, Any],
) -> None:
    """Rules 24 and 26: each reading lists the receipts it held its weeks to, and values each
    arm's end state at its own gameweek's outcome capture, with that capture's sell-on fee.

    One chain through GW38 serves both readings; each reads only its own weeks."""

    interim, final = two_readings["interim"], two_readings["final"]
    receipts, records = two_readings["receipts"], two_readings["records_dir"]
    # Each week's own outcome capture, GW15's tie and, by the final reading, the correction.
    for record, last, read in ((interim, 20, 34), (final, 38, 35)):
        assert record["frozen_source"]["checked"] == scorer.FROZEN_SOURCE_CHECK
        assert record["outcome_captures"] == {"rule": scorer.CAPTURE_SET_RULE, "read": read}
        posted = record["receipts"]
        assert posted["rule"] == scorer.RECEIPTS_RULE
        assert posted["file_sha256"] == hashlib.sha256(receipts.read_bytes()).hexdigest()
        assert posted["tracking_issue"].endswith("/issues/1")
        assert posted["frozen_commit"] == {"commit": FROZEN, "posted": "issuecomment-0"}
        assert sorted(posted["manifests"]) == [f"gw{week:02d}" for week in range(6, last + 1)]
        assert posted["manifests"]["gw06"]["posted"] == "issuecomment-06"
        assert all(week["deadline_source"] == "receipt" for week in record["weeks"])
        assert record["weeks"][-1]["gameweek"] == last
        end = record["totals"]["end_state_prices"]
        assert end == {
            "rule": scorer.END_PRICES_RULE,
            "gameweek": last,
            "outcome_capture": record["weeks"][-1]["outcome_capture"],
            "sell_on_fee": 0.5,
            "reason": None,
            "unpriced_chains": [],
        }
        assert end["outcome_capture"] is not None
        # Every arm holds the same squads, so each pair's sale difference is a number: zero.
        for pair in record["totals"]["paired_differences"].values():
            assert pair["sale_value_tenths_at_end"] == 0.0
        twin = (records / f"planner_policy_chain_gw{last}.md").read_text(encoding="utf-8")
        assert f"Sale values are at the prices in `{end['outcome_capture']}`" in twin
        assert posted["file_sha256"] in twin and scorer.CAPTURE_SET_RULE in twin
    # Each held player was bought at 50 + id and is priced at 52 + id, and a sale keeps half
    # the rise, 51 + id: a squad of players 1 to 15 sells for 885 tenths, three squads an arm.
    assert {
        arm: totals["sale_value_tenths_at_end"] for arm, totals in final["totals"]["by_arm"].items()
    } == dict.fromkeys(scorer.ARMS, 3 * 885.0)


def test_without_its_own_outcome_capture_a_reading_states_no_sale_value_and_says_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rules 25 and 26: two distinct captures tie as GW20's latest, so GW20 is unscored and
    listed with that reason, and no earlier week's capture prices the end state in its place."""

    evidence, snapshots, records = _world(tmp_path, monkeypatch)
    _identity(monkeypatch)
    _outcome_capture(snapshots, 20, points={player: 3 for player in ROSTER})
    record = scorer.score(
        evidence,
        snapshots,
        "gw20",
        receipts=tmp_path / RECEIPTS,
        records_dir=records,
        index_file=tmp_path / "index.md",
    )
    week20 = record["weeks"][-1]
    assert week20["gameweek"] == 20 and week20["outcome_capture"] is None
    assert week20["unscored_reason"] == "tied_outcome_captures"
    assert record["weeks"][-2]["outcome_capture"] is not None
    assert record["totals"]["end_state_prices"] == {
        "rule": scorer.END_PRICES_RULE,
        "gameweek": 20,
        "outcome_capture": None,
        "sell_on_fee": None,
        "reason": "reading_week_unscored:tied_outcome_captures",
        "unpriced_chains": [],
    }
    for pair in record["totals"]["paired_differences"].values():
        assert pair["sale_value_tenths_at_end"] is None
    twin = (records / "planner_policy_chain_gw20.md").read_text(encoding="utf-8")
    assert "No sale value is stated: GW20's outcome capture gives no prices" in twin


def test_a_held_player_the_pricing_capture_does_not_price_gets_no_sale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rules 23 and 26: no sale is invented. A chain whose end state holds a player its reading
    gameweek's outcome capture does not price is listed, and its arm states no sale value."""

    evidence, snapshots, _ = _world(tmp_path, monkeypatch, through=6)
    receipts = tmp_path / RECEIPTS

    def stranger(record: dict[str, Any]) -> None:
        state = record["state_after"]
        state["squad"][0] = 99
        state["purchase_prices"]["99"] = state["purchase_prices"].pop("1")

    _rewrite(evidence / "gw06" / "p950-hold_3.json", stranger)
    _reseal(evidence, 6)
    _repost(receipts, evidence, 6)
    _, weeks = scorer.read_evidence(evidence, 6, scorer.read_receipts(receipts))
    captures = scorer._captures(snapshots)
    scored = [scorer.score_week(week, scorer.outcome_capture(captures, 6)) for week in weeks]
    end = scorer.end_prices(scored, 6)
    assert (end.capture, end.fee, end.reason) == (scored[0].outcome.snapshot_id, 0.5, None)
    assert scorer.unpriced_chains(weeks, end) == ["p950:hold_3"]
    totals = scorer.arm_totals(scored, weeks, end.prices, end.fee)
    assert totals["hold_3"]["sale_value_tenths_at_end"] is None
    assert totals["hold_5"]["sale_value_tenths_at_end"] == 3 * 885.0
    priced = {
        "gameweek": 6,
        "outcome_capture": end.capture,
        "sell_on_fee": end.fee,
        "reason": end.reason,
        "unpriced_chains": scorer.unpriced_chains(weeks, end),
    }
    assert scorer._priced_note(priced).endswith(
        "No sale is invented for p950:hold_3: each holds an unpriced player."
    )


def test_the_end_state_is_priced_at_its_own_capture_s_fee_and_never_at_a_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rules 7 and 26: the sell-on fee is the pricing capture's own, read with its prices; a
    capture whose roster cannot be read prices nothing, and the reason is recorded."""

    evidence, snapshots, _ = _world(tmp_path, monkeypatch, through=6)
    _, weeks = scorer.read_evidence(evidence, 6, scorer.read_receipts(tmp_path / RECEIPTS))
    week = scorer.score_week(weeks[0], scorer.outcome_capture(scorer._captures(snapshots), 6))

    def priced_by(change: Callable[[dict[str, Any]], object]) -> scorer.EndPrices:
        bootstrap = json.loads(_bootstrap(6))
        change(bootstrap)
        written = write_snapshot(
            tmp_path / "pricing",
            source="fpl-live",
            captured_at_utc=_stamp(_deadline(6) + timedelta(hours=9)),
            payloads={
                BOOTSTRAP_PAYLOAD: json.dumps(bootstrap).encode("utf-8"),
                live_payload(6): _live(POINTS),
            },
        )
        capture = read_snapshot(tmp_path / "pricing", written.snapshot_id)
        end = scorer.end_prices([replace(week, outcome=scorer.Outcome(6, None, capture, None))], 6)
        assert end.capture == written.snapshot_id
        return end

    # Under rules that keep none of a rise, each held player sells at his price, 52 + id, and a
    # squad of players 1 to 15 for 900 tenths.
    feeless = priced_by(
        lambda bootstrap: bootstrap["game_config"]["rules"].update(transfers_sell_on_fee=0.0)
    )
    assert (feeless.fee, feeless.reason) == (0.0, None)
    totals = scorer.arm_totals([week], weeks, feeless.prices, feeless.fee)
    assert totals["hold_5"]["sale_value_tenths_at_end"] == 3 * 900.0
    unread = priced_by(lambda bootstrap: bootstrap.pop("teams"))
    assert (unread.prices, unread.fee) == (None, None)
    assert unread.reason is not None and unread.reason.startswith("prices_unreadable:")
    totals = scorer.arm_totals([week], weeks, unread.prices, unread.fee)
    assert all(arm["sale_value_tenths_at_end"] is None for arm in totals.values())


def test_the_sale_value_at_the_end_follows_the_games_rule_from_each_purchase_price() -> None:
    """Rules 10, 18 and 26: a player who fell is sold at his current price and one who rose
    keeps half the rise, rounded down; current and purchase prices never trade places."""

    state = {
        "squad": [1, 2],
        "purchase_prices": {"1": 50, "2": 60},
        "free_transfers": 1,
        "bank_tenths": 7,
    }
    records = {("p1000", arm): {"state_after": state} for arm in scorer.ARMS}
    totals = scorer.arm_totals([], [scorer.WeekEvidence(6, {}, {}, records)], {1: 61, 2: 55}, 0.5)
    for arm in scorer.ARMS:
        # Player 1 rose from 50 to 61 and sells at 55; player 2 fell from 60 to 55 and sells at 55.
        assert totals[arm]["sale_value_tenths_at_end"] == 110
        assert totals[arm]["bank_tenths_at_end"] == 7
        assert totals[arm]["free_transfers_at_end"] == 1


def test_the_capture_set_is_this_seasons_as_the_runner_reads_it(tmp_path: Path) -> None:
    """Rules 25 and 28 read only this season's captures: one named before the season opens is
    never opened, one whose bootstrap names another season is left out, so neither can settle
    a week; any other capture that cannot be read refuses the reading, as in the runner."""

    root = tmp_path / "snapshots"
    root.mkdir()
    # In June the game still serves last season, every week of it settled.
    last_season = json.loads(_bootstrap(38))
    for event in last_season["events"]:
        event["deadline_time"] = _stamp(_deadline(event["id"]) - timedelta(days=364))
    write_snapshot(
        root,
        source="fpl-live",
        captured_at_utc="2026-06-15T10:00:00Z",
        payloads={BOOTSTRAP_PAYLOAD: json.dumps(last_season).encode("utf-8")},
    )
    named_earlier = write_snapshot(
        root,
        source="fpl-live",
        captured_at_utc="2026-05-01T10:00:00Z",
        payloads={BOOTSTRAP_PAYLOAD: _bootstrap(38)},
    ).snapshot_id
    (root / named_earlier / "payloads" / BOOTSTRAP_PAYLOAD).write_bytes(b"damaged")
    assert scorer._captures(root) == []
    ours = _outcome_capture(root, 20)
    captures = scorer._captures(root)
    assert [capture.metadata.snapshot_id for capture in captures] == [ours]
    assert scorer.settled(captures, 20) and not scorer.settled(captures, 21)
    damaged = _outcome_capture(root, 21)
    (root / damaged / "payloads" / BOOTSTRAP_PAYLOAD).write_bytes(b"damaged")
    with pytest.raises(scorer.ScorerError, match=f"Capture {damaged} cannot be read"):
        scorer._captures(root)


def test_a_weeks_deadline_is_the_one_its_receipt_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rules 5 and 25: a decided week's deadline is the one its decision capture stated, as its
    receipt records it, even where a later capture states another; a week whose receipt states
    none takes the newest capture's."""

    evidence, snapshots, records = _world(tmp_path, monkeypatch, through=8, missing=(8,))
    _identity(monkeypatch)
    # The capture GW20 settles in states GW7's deadline six hours later than GW7's own did.
    moved = json.loads(_bootstrap(20))
    moved["events"][6]["deadline_time"] = _stamp(_deadline(7) + timedelta(hours=6))
    write_snapshot(
        snapshots,
        source="fpl-live",
        captured_at_utc=_stamp(_deadline(20) + timedelta(hours=5)),
        payloads={BOOTSTRAP_PAYLOAD: json.dumps(moved).encode("utf-8")},
    )
    _read_through(monkeypatch, 8)
    record = scorer.score(
        evidence,
        snapshots,
        "gw20",
        receipts=tmp_path / RECEIPTS,
        records_dir=records,
        index_file=tmp_path / "index.md",
    )
    week7, week8 = record["weeks"][1], record["weeks"][2]
    assert (week7["deadline_utc"], week7["deadline_source"]) == (_stamp(_deadline(7)), "receipt")
    # Read from the receipt, GW7's own outcome capture, five hours after it, counts.
    assert week7["outcome_capture"] is not None and week7["unscored_reason"] is None
    assert week7["scored_chains"] == 15
    assert (week8["deadline_utc"], week8["deadline_source"]) == (
        _stamp(_deadline(8)),
        "newest_capture",
    )
    # A receipt deadline that is no instant refuses the reading; none at all, with no capture
    # that states one, leaves the week without a deadline.
    for stated, message in (("2026-10-17T10:00:00", "names no time zone"), (7, "no readable")):
        week = scorer.WeekEvidence(7, {"deadline_utc": stated}, {}, {})
        with pytest.raises(scorer.ScorerError, match=f"GW07's receipt.*{message}"):
            scorer.week_deadline([], week)
    assert scorer.week_deadline([], scorer.WeekEvidence(7, {}, {}, {})) == (None, None)
