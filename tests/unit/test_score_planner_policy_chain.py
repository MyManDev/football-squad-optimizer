"""The chain's scorer reads the runner's evidence and the season's outcomes by the protocol's rules.

The worlds here are synthetic: the runner decides stubbed arms into a real evidence directory,
and outcome captures are written with the payloads the scorer reads. No real capture, archive
or live store is touched.
"""

from __future__ import annotations

import json
import subprocess
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from scripts import measure_planner_policy_chain as chain
from scripts import score_planner_policy_chain as scorer
from tests.unit.test_planner_policy_chain import (
    SQUAD,
    T0,
    _chain_world,
    _outcome,
    _plan,
    _plan_week,
    _state,
    _week,
)

from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, live_payload

#: A legal eleven over the synthetic squad: one goalkeeper, four defenders, four midfielders,
#: two forwards; the bench holds the second goalkeeper, a defender, a midfielder and a forward.
STARTERS = [1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14]
BENCH = [2, 7, 12, 15]
ROSTER = (*SQUAD, 16, 17)
CAPTAINS = {"served": 8, "hold": 10, "one_week": 11}
#: Realized points: the served captain scores ten, hold's captain two, one_week's one.
POINTS = {player: 2 for player in ROSTER} | {8: 10, 10: 2, 11: 1}


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
    elements = [{"id": player + 100, "code": player, "now_cost": 50 + player} for player in ROSTER]
    return json.dumps({"events": events, "elements": elements}).encode("utf-8")


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


def _arm_outcome(
    name: str, gameweek: int, *, paid: int = 0, truncated: bool = False
) -> chain.ArmOutcome:
    week = _plan_week(gameweek=gameweek)
    week.paid_transfer_count = paid
    outcome = _outcome(_plan(week))
    family = "one_week" if name == "one_week" else name.split("_")[0]
    outcome.lineup = _lineup(CAPTAINS[family])
    outcome.truncated = truncated
    return outcome


def _world(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    through: int = 20,
    missing: tuple[int, ...] = (),
    truncated_in: tuple[int, ...] = (),
    failing: tuple[tuple[str, int], ...] = (),
) -> tuple[Path, Path, Path]:
    """A decided chain from GW6 through ``through``: served arms pay one transfer a week."""

    weeks: dict[int, object] = {}
    for gameweek in range(6, through + 1):
        if gameweek in missing:
            weeks[gameweek] = ("no_artifact", {"snapshot_id": None, "reason": "no_artifact"})
        else:
            weeks[gameweek] = _week(gameweek)
    evidence, _ = _chain_world(tmp_path, monkeypatch, weeks)
    states = {f"p{budget}": _state(decided=5) for budget, _, _ in chain.PROFILES}
    for state in states.values():
        object.__setattr__(state, "lineup", _lineup(CAPTAINS["hold"]))
    squads = chain.Squads(states, {}, {profile: ["OPTIMAL"] for profile in states})
    monkeypatch.setattr(chain, "initial_states", lambda forecast, week: squads)

    def arm(name: str, week: chain.WeekInputs, held: object) -> chain.ArmOutcome:
        gameweek = int(week.inputs.deadline.gameweek)
        if (name, gameweek) in failing:
            return _outcome(None, failure="raised_ValueError")
        return _arm_outcome(
            name,
            gameweek,
            paid=1 if name.startswith("served") else 0,
            truncated=gameweek in truncated_in,
        )

    monkeypatch.setattr(chain, "run_arm", arm)
    snapshots, artifacts = tmp_path / "snapshots", tmp_path / "football"
    (artifacts / "football").mkdir(parents=True)
    snapshots.mkdir()
    chain.decide(
        snapshots,
        artifacts,
        evidence,
        through,
        "issuecomment-1",
        now=_deadline(through) + timedelta(hours=1),
    )
    for gameweek in range(6, through + 1):
        _outcome_capture(snapshots, gameweek)
    return evidence, snapshots, tmp_path / "records"


def _identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        scorer,
        "source_identity",
        lambda: {"scorer_merge_commit": "c" * 40, "scorer_sha256": "d" * 64},
    )
    monkeypatch.setattr(
        scorer,
        "release_binding",
        lambda deadline, frozen: {
            "release_tag": "site-2026-27-gw06-fix16",
            "planner_source_same": True,
            "binding_source_same": frozen == "b",
        },
    )


# Rules 25 to 30: a reading over fifteen decided weeks


def test_the_interim_reading_scores_every_week_and_pairs_the_arms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence, snapshots, records = _world(tmp_path, monkeypatch)
    _identity(monkeypatch)
    index = tmp_path / "index.md"
    index.write_text("# Measurements Index\n\n- [other](x.json): a row.\n", encoding="utf-8")
    record = scorer.score(evidence, snapshots, "gw20", records_dir=records, index_file=index)
    assert record["final"] is False and record["outcome_read"] is True
    assert record["locked_holdout_accessed"] is False
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
    assert record["contrasts"]["A"]["by_model_version"] == {} or all(
        block["weeks"] > 0 for block in record["contrasts"]["A"]["by_model_version"].values()
    )
    assert record["secondary"]["hold_minus_one_week"]["mean"] == pytest.approx(1.0)
    assert record["secondary"]["A_window_3"]["weeks"] == 15
    assert set(record["by_squad"]) == {"p1000", "p950", "p900"}
    assert record["totals"]["paired_differences"]["A"]["net_points"] == pytest.approx(
        2 * 15 * 3 * 4.0
    )
    assert "by_arm" not in record["totals"]
    written = json.loads((records / "planner_policy_chain_gw20.json").read_text(encoding="utf-8"))
    assert written == record
    twin = (records / "planner_policy_chain_gw20.md").read_text(encoding="utf-8")
    assert "+4.000" in twin and "+5.000" in twin and "none (interim)" in twin
    index_text = index.read_text(encoding="utf-8")
    assert index_text.count("- [Planner policy chain, gw20 reading]") == 1
    assert index_text.startswith("# Measurements Index")


def test_a_held_or_blocked_chain_scores_nothing_even_with_a_lineup_on_record() -> None:
    """Rules 21 and 23: a missing week's hold and a blocked chain contribute no pair."""

    import pandas as pd

    outcomes = pd.DataFrame(
        {
            "player_id": list(ROSTER),
            "total_points": [2] * len(ROSTER),
            "minutes": [90] * len(ROSTER),
        }
    )
    players = {
        str(player): {"name": f"Player {player}", "position": position, "expected_points": 2.0}
        for player, position in zip(
            ROSTER,
            ["GK", "GK", *["DEF"] * 5, *["MID"] * 5, *["FWD"] * 3, "MID", "DEF"],
            strict=True,
        )
    }
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


def test_a_record_that_changed_under_its_own_digest_is_refused_without_a_week_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 36: each record is held to the digest its manifest lists, with or without the
    week digest the runner adds."""

    evidence, _, _ = _world(tmp_path, monkeypatch, through=6)
    manifest_path = evidence / "gw06" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("evidence_digest", None)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    scorer.read_evidence(evidence, 6)
    path = next((evidence / "gw06").glob("p1000-*.json"))
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(scorer.ScorerError, match="does not match the digest"):
        scorer.read_evidence(evidence, 6)


def test_hits_are_charged_at_four_per_paid_transfer_from_the_played_week() -> None:
    """Rule 26: the game's four points per paid transfer, never the planning cost of eight."""

    decided = {"status": "decided", "plan": {"weeks": [{"paid_transfer_count": 2}]}}
    assert scorer.paid_hits(decided) == 8.0
    assert (
        scorer.paid_hits({"status": "failed", "plan": {"weeks": [{"paid_transfer_count": 2}]}})
        == 0.0
    )
    assert scorer.paid_hits({"status": "decided", "plan": {"weeks": []}}) == 0.0


def test_a_failed_arm_is_scored_on_its_held_team_and_the_pair_is_also_reported_without_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 22: the failed week is scored and stays in the pairs; rule 29 reports it apart."""

    evidence, snapshots, records = _world(tmp_path, monkeypatch, failing=(("hold_3", 7),))
    _identity(monkeypatch)
    record = scorer.score(
        evidence, snapshots, "gw20", records_dir=records, index_file=tmp_path / "index.md"
    )
    primary = record["contrasts"]["A"]["primary"]
    without = record["contrasts"]["A"]["without_failed_weeks"]
    assert primary["pairs"] == 15 * 6 and without["pairs"] == 15 * 6 - 3
    # The held team is hold's lineup with no transfer, so the failed pair scores like hold's.
    assert primary["mean"] == pytest.approx(4.0) and without["mean"] == pytest.approx(4.0)
    week7 = next(week for week in record["weeks"] if week["gameweek"] == 7)
    assert week7["scored_chains"] == 15


def test_a_missing_week_is_not_scored_and_a_truncated_week_enters_no_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rules 14 and 21: missing weeks are listed with their reason; truncated weeks are played,
    scored and reported apart."""

    evidence, snapshots, records = _world(tmp_path, monkeypatch, missing=(8,), truncated_in=(9,))
    _identity(monkeypatch)
    record = scorer.score(
        evidence, snapshots, "gw20", records_dir=records, index_file=tmp_path / "index.md"
    )
    week8 = next(week for week in record["weeks"] if week["gameweek"] == 8)
    assert week8["missing_reason"] == "no_artifact" and week8["scored_chains"] == 0
    primary = record["contrasts"]["A"]["primary"]
    assert primary["weeks"] == 13 and 8 not in primary["weeks_listed"]
    assert 9 not in primary["weeks_listed"]
    truncated = record["truncated_weeks"]["A"]
    assert truncated["weeks_listed"] == [9] and truncated["mean"] == pytest.approx(4.0)


def test_exact_zero_pairs_are_counted_when_both_arms_played_the_same_team(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 27: a pair is exactly zero only when fifteen, eleven, bench, captain, vice and hits
    agree; no other pair is set to zero."""

    evidence, snapshots, records = _world(tmp_path, monkeypatch, through=6)
    _identity(monkeypatch)
    for path in (evidence / "gw06").glob("p*-*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        document["advice"] = _lineup(CAPTAINS["served"])
        document["plan"]["weeks"][0]["paid_transfer_count"] = 0
        path.write_text(json.dumps(document), encoding="utf-8")
    manifest_path = evidence / "gw06" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["records"] = {
        name: scorer.hashlib.sha256((evidence / "gw06" / name).read_bytes()).hexdigest()
        for name in manifest["records"]
    }
    manifest["evidence_digest"] = scorer.evidence_digest(evidence / "gw06")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    # The reading waits for GW20 in some capture.
    _outcome_capture(snapshots, 20, settled_through=20, live=False)
    read = scorer.read_evidence
    monkeypatch.setattr(scorer, "read_evidence", lambda root, through: read(root, 6))
    record = scorer.score(
        evidence, snapshots, "gw20", records_dir=records, index_file=tmp_path / "index.md"
    )
    primary = record["contrasts"]["A"]["primary"]
    assert primary["pairs"] == 6 and primary["exact_zero_pairs"] == 6
    assert primary["mean"] == pytest.approx(0.0)


# Rules 28, 32 and 37: what the scorer refuses, and the verdict clauses


def test_the_reading_refuses_what_the_protocol_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence, snapshots, records = _world(tmp_path, monkeypatch, through=10)
    _identity(monkeypatch)
    index = tmp_path / "index.md"
    with pytest.raises(scorer.ScorerError, match="names no reading"):
        scorer.score(evidence, snapshots, "gw19", records_dir=records, index_file=index)
    # GW20 has not settled: the captures reach GW10 only.
    with pytest.raises(scorer.ScorerError, match="has not settled"):
        scorer.score(evidence, snapshots, "gw20", records_dir=records, index_file=index)
    _outcome_capture(snapshots, 20, settled_through=20, live=False)
    # GW11 is not decided yet.
    with pytest.raises(scorer.ScorerError, match="GW11 is not decided"):
        scorer.score(evidence, snapshots, "gw20", records_dir=records, index_file=index)
    assert not records.exists() and not index.exists()
    # A reading taken already is refused by name.
    records.mkdir()
    (records / "planner_policy_chain_gw20.json").write_text("{}", encoding="utf-8")
    with pytest.raises(scorer.ScorerError, match="taken already"):
        scorer.score(evidence, snapshots, "gw20", records_dir=records, index_file=index)
    (records / "planner_policy_chain_gw20.json").unlink()
    # Evidence that changed under its manifest is refused.
    path = next((evidence / "gw07").glob("p1000-*.json"))
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(scorer.ScorerError, match=r"no longer match|does not match"):
        scorer.read_evidence(evidence, 10)


def test_the_scorer_runs_only_from_its_own_merge_commit_on_a_clean_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def git(*arguments: str, cwd: Path | None = None) -> str:
        if arguments[:1] == ("status",):
            return ""
        if arguments[:2] == ("rev-parse", "HEAD"):
            return "head"
        if arguments[:1] == ("log",):
            return "merge 2026-10-20T10:00:00+00:00"
        raise AssertionError(arguments)

    monkeypatch.setattr(scorer, "_git", git)
    with pytest.raises(scorer.ScorerError, match="merge commit merge; HEAD is head"):
        scorer.source_identity()
    monkeypatch.setattr(scorer, "_git", lambda *a, **k: "dirty" if a[:1] == ("status",) else "x")
    with pytest.raises(scorer.ScorerError, match="not clean"):
        scorer.source_identity()
    monkeypatch.setattr(scorer, "_git", lambda *a, **k: "")
    with pytest.raises(scorer.ScorerError, match="has not merged"):
        scorer.scorer_merge()


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
    tied = read_snapshot(root, _outcome_capture(tmp_path / "other", 6, hours_after=9))
    assert (
        scorer.outcome_capture([later_capture := captures[2], tied], 6).reason
        == "tied_outcome_captures"
    )
    assert later_capture is captures[2]
    assert scorer.settled(captures, 6) and not scorer.settled(captures, 7)


# Rule 3: the release tag live at the deadline, and the fixed diff test


def test_the_release_binding_reads_the_tag_live_at_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listing = (
        "site-2026-27-gw06-fix15 2026-10-04T23:18:44+03:00\n"
        "site-2026-27-gw06-fix16 2026-10-05T03:51:09+03:00\n"
        "site-2026-27-gw07-fix1 2026-10-16T10:00:00+03:00\n"
    )
    monkeypatch.setattr(scorer, "_git", lambda *a, **k: listing)
    asked: list[tuple[str, str, tuple[str, ...]]] = []

    def diff(left: str, right: str, paths) -> bool | None:
        asked.append((left, right, tuple(paths)))
        return paths == scorer.PLANNER_SOURCE

    monkeypatch.setattr(scorer, "_diff_quiet", diff)
    deadline = scorer._instant("2026-10-10T10:00:00Z")
    binding = scorer.release_binding(deadline, "frozen")
    assert binding == {
        "release_tag": "site-2026-27-gw06-fix16",
        "planner_source_same": True,
        "binding_source_same": False,
    }
    assert asked == [
        ("site-2026-27-gw06-fix16", "frozen", scorer.PLANNER_SOURCE),
        ("site-2026-27-gw06-fix16", "frozen", scorer.BINDING_SOURCE),
    ]
    early = scorer.release_binding(scorer._instant("2026-09-01T10:00:00Z"), "frozen")
    assert early["release_tag"] is None and early["planner_source_same"] is None


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
    with pytest.raises(SystemExit) as refused:
        scorer.main(
            ["--evidence", str(tmp_path), "--snapshot-root", str(tmp_path), "--reading", "gw19"]
        )
    assert refused.value.code == 2
    monkeypatch.setattr(scorer, "source_identity", lambda: {})
    code = scorer.main(
        [
            "--evidence",
            str(tmp_path),
            "--snapshot-root",
            str(tmp_path),
            "--reading",
            "gw20",
            "--records-dir",
            str(tmp_path / "records"),
            "--index-file",
            str(tmp_path / "index.md"),
        ]
    )
    assert code == 2 and "refused:" in capsys.readouterr().err
