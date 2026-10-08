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
#: The line the runner prints for each week it decides, which the operator posts (rule 24).
DECIDED = re.compile(r"GW(\d{2}) decided from .+; manifest sha256 ([0-9a-f]{64})")


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


def _world(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    through: int = 20,
    missing: tuple[int, ...] = (),
    failing: tuple[tuple[str, int], ...] = (),
    receipt_fields: dict[int, dict[str, object]] | None = None,
) -> tuple[Path, Path, Path]:
    """A decided chain from GW6 through ``through``: served arms pay one transfer a week, and
    each window, failed or not, is truncated by the runner's own rule (rule 14).

    The runner starts the chain before GW21's deadline, as rule 40 requires, and decides any
    later week in a second run. The operator posts the frozen commit and every manifest sha256
    the runner prints, written to ``tmp_path / RECEIPTS`` (rule 24). ``receipt_fields`` adds
    fields to a week's receipt.json, by gameweek.
    """

    weeks: dict[int, object] = {}
    for gameweek in range(6, through + 1):
        fields = (receipt_fields or {}).get(gameweek, {})
        if gameweek in missing:
            weeks[gameweek] = (
                "no_artifact",
                {"snapshot_id": None, "reason": "no_artifact", **fields},
            )
        else:
            decided = _week(gameweek)
            # Rule 36: a decided week's receipt carries the deadline its capture states.
            weeks[gameweek] = replace(
                decided,
                receipt={
                    **decided.receipt,
                    "deadline_utc": _stamp(_deadline(gameweek)),
                    **fields,
                },
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
        truncated = len(chain.window_weeks(name, gameweek)) < chain._width(name)
        if (name, gameweek) in failing:
            failed = _outcome(None, failure="raised_ValueError")
            failed.truncated = truncated
            return failed
        return _arm_outcome(
            name, gameweek, paid=1 if name.startswith("served") else 0, truncated=truncated
        )

    monkeypatch.setattr(chain, "run_arm", arm)
    snapshots, artifacts = tmp_path / "snapshots", tmp_path / "football"
    (artifacts / "football").mkdir(parents=True)
    snapshots.mkdir()
    printed: list[str] = []
    for last in sorted({min(through, 20), through}):
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
    for gameweek in range(6, through + 1):
        _outcome_capture(snapshots, gameweek)
    return evidence, snapshots, tmp_path / "records"


def _identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """The scorer's identity, its checks for a reading taken already, origin's release tags and
    the frozen source, stubbed: no git runs."""

    monkeypatch.setattr(
        scorer,
        "source_identity",
        lambda: {"scorer_merge_commit": "c" * 40, "scorer_sha256": "d" * 64},
    )
    monkeypatch.setattr(scorer, "committed_reading", lambda reading: None)
    monkeypatch.setattr(scorer, "written_reading", lambda reading: None)
    monkeypatch.setattr(scorer, "release_tags", lambda: ())
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
    assert record["choices"] == scorer.CHOICES
    written = json.loads((records / "planner_policy_chain_gw20.json").read_text(encoding="utf-8"))
    assert written == record
    twin = (records / "planner_policy_chain_gw20.md").read_text(encoding="utf-8")
    assert "+4.000" in twin and "+5.000" in twin and "none (interim)" in twin
    assert scorer.RELEASE_RULE in twin
    assert all(f"- `{name}`: {text}" in twin for name, text in scorer.CHOICES.items())
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
    assert all(8 not in block["weeks_listed"] for block in record["by_squad"].values())
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
    record = scorer.score(
        evidence,
        snapshots,
        "gw38",
        receipts=tmp_path / RECEIPTS,
        records_dir=records,
        index_file=tmp_path / "index.md",
    )
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
    assert set(record["by_squad"]) == {"p1000", "p950", "p900"}
    for block in record["by_squad"].values():
        assert block["weeks_listed"] == [6, 34, 35, 36] and block["pairs"] == 2 + 2 + 1 + 1
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
    _reseal(evidence, 6)
    _repost(tmp_path / RECEIPTS, evidence, 6)
    # The reading waits for GW20 in some capture.
    _outcome_capture(snapshots, 20, settled_through=20, live=False)
    read = scorer.read_evidence
    monkeypatch.setattr(
        scorer, "read_evidence", lambda root, through, posted: read(root, 6, posted)
    )
    record = scorer.score(
        evidence,
        snapshots,
        "gw20",
        receipts=tmp_path / RECEIPTS,
        records_dir=records,
        index_file=tmp_path / "index.md",
    )
    primary = record["contrasts"]["A"]["primary"]
    assert primary["pairs"] == 6 and primary["exact_zero_pairs"] == 6
    assert primary["mean"] == pytest.approx(0.0)


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
    paths = {"receipts": tmp_path / RECEIPTS, "index_file": tmp_path / "index.md"}
    undeclared = scorer.score(
        evidence, snapshots, "gw20", records_dir=tmp_path / "undeclared", **paths
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
        evidence, snapshots, "gw20", records_dir=records, producer_changes=declared, **paths
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
                producer_changes={"source": "issuecomment-3", "changes": [contradicted]},
                **paths,
            )
    assert not (tmp_path / "refused").exists()
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
    # Another reading's record is no bar: gw38 goes on to wait for its gameweek.
    with pytest.raises(scorer.ScorerError, match="has not settled"):
        scorer.score(tmp_path / "evidence", tmp_path / "snapshots", "gw38", **paths)
    assert read == [tmp_path / "snapshots"]
    assert _git_in(checkout, "status", "--porcelain") == ""


def test_no_capture_is_read_before_the_refusals_that_need_no_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rules 24 and 28: the reading's record in committed history, its record in another
    worktree, origin's release tags and the receipts file are checked before the first capture
    is read, in that order."""

    read: list[Path] = []
    monkeypatch.setattr(scorer, "_captures", lambda root: read.append(root) or [])
    monkeypatch.setattr(scorer, "source_identity", lambda: {})

    def tags_refused() -> tuple[scorer.ReleaseTag, ...]:
        raise scorer.ScorerError("a release tag differs from origin's")

    monkeypatch.setattr(scorer, "release_tags", tags_refused)
    paths = {
        "receipts": tmp_path / RECEIPTS,
        "records_dir": tmp_path / "records",
        "index_file": tmp_path / "index.md",
    }
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
    read = scorer.read_evidence
    monkeypatch.setattr(
        scorer, "read_evidence", lambda root, through, posted: read(root, 6, posted)
    )
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rules 24 and 26: each reading lists the receipts it held its weeks to, and values each
    arm's end state at its own gameweek's outcome capture, with that capture's sell-on fee.

    One chain through GW38 serves both readings; each reads only its own weeks."""

    evidence, snapshots, records = _world(tmp_path, monkeypatch, through=38)
    _identity(monkeypatch)
    receipts = tmp_path / RECEIPTS
    index = tmp_path / "index.md"
    interim = scorer.score(
        evidence, snapshots, "gw20", receipts=receipts, records_dir=records, index_file=index
    )
    final = scorer.score(
        evidence, snapshots, "gw38", receipts=receipts, records_dir=records, index_file=index
    )
    for record, last in ((interim, 20), (final, 38)):
        assert record["frozen_source"]["checked"] == scorer.FROZEN_SOURCE_CHECK
        assert record["outcome_captures"] == {"rule": scorer.CAPTURE_SET_RULE, "read": 33}
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
    read = scorer.read_evidence
    monkeypatch.setattr(
        scorer, "read_evidence", lambda root, through, posted: read(root, 8, posted)
    )
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
