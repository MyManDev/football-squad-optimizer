"""The policy chain's runner applies its protocol: the capture, the arms, the carry and the records.

Synthetic and offline throughout. The runner is held to
``docs/research/planner_policy_chain_prereg.md``; each test names the rule it pins. Where a
solver would only slow a test that is about control flow, the arm is replaced by a recorded
outcome, and the arms themselves are tested on the shared synthetic window.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from scripts import measure_planner_policy_chain as chain
from tests.unit.test_football_bundle import case as case
from tests.unit.test_football_bundle_switches import make_joint_pair
from tests.unit.test_football_prospective_prereg import _artifact
from tests.unit.test_football_publication import publication_case as publication_case
from tests.unit.test_live_horizon_planning import _inputs
from tests.unit.test_live_recommendation import _bootstrap, _capture
from tests.unit.test_live_transfers import CHIPS, _game_config

from squadopt.application.entries import EntryError
from squadopt.application.football_participation import FOOTBALL_PARTICIPATION_VERSION
from squadopt.application.lineup_publication import lineup_fields
from squadopt.application.weekly_suggestion_eval import score_recorded_advice
from squadopt.data.atomic import write_document_once
from squadopt.data.errors import ConflictingBytesError
from squadopt.live import plan_transfer_horizon
from squadopt.live import transfers as live_transfers
from squadopt.live.football_artifact import football_artifact_path, forecast_digest
from squadopt.live.recommendation import read_inputs
from squadopt.live.tick import handoff_path_for
from squadopt.optimization import OptimizationConfig, SolverStatus
from squadopt.planning import PlanningHorizon
from squadopt.planning.guarded import GUARDED_PLANNER_VERSION
from squadopt.planning.horizon import APPEARANCE_HORIZON_CONTRACT_VERSION
from squadopt.planning.optimizer import optimize_transfer_plan
from squadopt.planning.pricing import sell_price_tenths
from squadopt.platform.football_bundle import seal_football_bundle
from squadopt.prediction.football import (
    FOOTBALL_MODEL_VERSION,
    JOINT_ROLE_MODEL_VERSION,
    JOINT_ROLE_MODEL_VERSIONS,
    JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION,
)

PROTOCOL_TEXT = " ".join(chain.PROTOCOL_PATH.read_text(encoding="utf-8").split())
T0 = datetime(2026, 10, 10, 10, 0, tzinfo=UTC)
BUDGET = OptimizationConfig(solver_time_limit_seconds=300, solver_deterministic_time_limit=20)

SQUAD = tuple(range(1, 16))
POSITIONS = dict(
    zip(SQUAD, ("GK", "GK", *("DEF",) * 5, *("MID",) * 5, *("FWD",) * 3), strict=True)
) | {16: "MID", 17: "DEF"}
LINEUP: dict[str, object] = {
    "starting_xi": list(SQUAD[:11]),
    "bench": list(SQUAD[11:]),
    "captain": 3,
    "vice_captain": 4,
    "chip": None,
    "transfer_hit_points": 0.0,
    "scoring_complete": True,
}


def _entry(
    snapshot: str, hours: float, target: int, deadline_hours: float = 0.0
) -> chain.CaptureIndexEntry:
    return chain.CaptureIndexEntry(
        snapshot, T0 + timedelta(hours=hours), target, T0 + timedelta(hours=deadline_hours)
    )


def _table(players: tuple[int, ...] = (*SQUAD, 16, 17), gameweek: int = 6) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "gameweek": gameweek,
            "player_id": list(players),
            "name": [f"Player {p}" for p in players],
            "team_id": [f"Club {p % 5}" for p in players],
            "position": [POSITIONS[p] for p in players],
            "price_tenths": [50 + p for p in players],
            "expected_points": [1.0 + p / 10 for p in players],
        }
    )


def _week(gameweek: int = 6, roster: tuple[int, ...] = (*SQUAD, 16, 17)) -> chain.WeekInputs:
    """A week whose inputs the stubbed arms never solve on: only the carry reads it."""

    table = _table(roster, gameweek)
    return chain.WeekInputs(
        inputs=SimpleNamespace(  # type: ignore[arg-type]
            deadline=SimpleNamespace(gameweek=gameweek),
            players=table.loc[:, ["player_id", "price_tenths"]],
        ),
        rules=SimpleNamespace(  # type: ignore[arg-type]
            transfers=SimpleNamespace(sell_on_fee=0.5, max_free_transfers=5)
        ),
        forecast=SimpleNamespace(  # type: ignore[arg-type]
            projection=SimpleNamespace(table=table),
            fingerprint="forecast",
            horizon=SimpleNamespace(model_version=FOOTBALL_MODEL_VERSION),
            build_horizon=lambda weeks: weeks,
        ),
        artifact_bytes=b'{"fingerprint": "forecast"}',
        receipt={"snapshot_id": f"capture-gw{gameweek}", "artifact_sha256": "a" * 64},
    )


def _state(
    squad: tuple[int, ...] = SQUAD, bank: int = 20, free: int = 1, decided: int = 5
) -> chain.ChainState:
    return chain.ChainState(squad, {p: 50 + p for p in squad}, bank, free, decided, LINEUP)


def _plan_week(
    squad: tuple[int, ...] = SQUAD,
    *,
    out: tuple[int, ...] = (),
    into: tuple[int, ...] = (),
    bank_after: int = 20,
    gameweek: int = 6,
) -> SimpleNamespace:
    table = _table(squad, gameweek).drop(columns="gameweek")
    return SimpleNamespace(
        gameweek=gameweek,
        selected_squad=table,
        starting_xi=table.head(11),
        transfers_out=pd.DataFrame({"player_id": list(out)}, dtype="int64"),
        transfers_in=pd.DataFrame({"player_id": list(into)}, dtype="int64"),
        bank_after_tenths=bank_after,
        free_transfers_for_next_gameweek=1,
        paid_transfer_count=0,
        projected_score=50.0,
        chip=None,
        captain=pd.Series({"player_id": squad[2]}),
        transfer_hit_points=0.0,
    )


def _plan(
    week: SimpleNamespace | None = None,
    *,
    status: SolverStatus = SolverStatus.OPTIMAL,
    diagnostics: dict[str, object] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        solver_status=status,
        has_solution=status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE),
        weeks=() if week is None else (week,),
        diagnostics={"horizon_fingerprint": "horizon"} if diagnostics is None else diagnostics,
    )


def _outcome(
    plan: SimpleNamespace | None, *, failure: str | None = None, horizon: str = "horizon"
) -> chain.ArmOutcome:
    return chain.ArmOutcome(
        plan,  # type: ignore[arg-type]
        "served",
        None,
        60.0,
        1800.0,
        (6, 7, 8),
        False,
        "configuration",
        horizon,
        failure,
        None if failure else dict(LINEUP),
        {"solver_status": "OPTIMAL", "proved": True},
        {"deterministic_time_used": 1.0},
    )


# Rule 5: the decision capture, and a week decided only after its deadline


def test_the_decision_capture_is_the_latest_capture_whose_own_target_is_the_week() -> None:
    index = (_entry("early", 0, 6), _entry("latest-own", 5, 6), _entry("next-target", 9, 7))
    assert chain.decision_capture(index, 6) == chain.Selection("latest-own", None)


def test_two_captures_at_the_latest_instant_make_the_week_missing() -> None:
    index = (_entry("a", 3, 6), _entry("b", 3, 6), _entry("older", 1, 6))
    assert chain.decision_capture(index, 6) == chain.Selection(None, "tied_latest_captures")


def test_a_capture_that_targets_another_week_is_never_this_weeks() -> None:
    index = (_entry("last-weeks", 2, 5),)
    assert chain.decision_capture(index, 6) == chain.Selection(None, "no_own_target_capture")


def _bootstrap_deadlines(monkeypatch: pytest.MonkeyPatch, deadlines: dict[int, datetime]) -> None:
    monkeypatch.setattr(
        chain,
        "read_snapshot",
        lambda root, snapshot_id: SimpleNamespace(payloads={chain.BOOTSTRAP_PAYLOAD: b"{}"}),
    )
    monkeypatch.setattr(
        chain,
        "gameweek_deadlines",
        lambda payload: tuple(
            SimpleNamespace(gameweek=week, deadline_utc=moment.isoformat())
            for week, moment in sorted(deadlines.items())
        ),
    )


def test_a_week_waits_for_the_latest_deadline_any_capture_states_for_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = (_entry("own", 0, 6, deadline_hours=0), _entry("newest", 30, 7, deadline_hours=170))
    _bootstrap_deadlines(monkeypatch, {6: T0 + timedelta(hours=2), 7: T0 + timedelta(hours=170)})
    assert chain.deadline_of(index, Path("."), 6) == T0 + timedelta(hours=2)
    _bootstrap_deadlines(monkeypatch, {6: T0 - timedelta(hours=2)})
    assert chain.deadline_of(index, Path("."), 6) == T0


def test_the_first_bound_week_is_the_first_deadline_after_the_later_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bootstrap_deadlines(monkeypatch, {5: T0 - timedelta(days=7), 6: T0, 7: T0 + timedelta(days=7)})
    index = (_entry("newest", -1, 6),)
    commits = {
        "protocol": {"commit": "a", "committed_utc": (T0 - timedelta(days=9)).isoformat()},
        "runner": {"commit": "b", "committed_utc": (T0 - timedelta(days=2)).isoformat()},
    }
    bound = chain.binding_instant(commits)
    assert bound == T0 - timedelta(days=2)
    assert chain.frozen_commit(commits) == "b"
    assert chain.first_bound_week(index, Path("."), commits) == 6
    at_deadline = {**commits, "runner": {"commit": "b", "committed_utc": T0.isoformat()}}
    assert chain.first_bound_week(index, Path("."), at_deadline) == 7


@pytest.mark.parametrize(
    "protocol,runner,week",
    [
        ("2026-10-06T23:59:59+00:00", "2026-10-08T23:59:59+00:00", 6),
        ("2026-10-07T00:00:00+00:00", "2026-10-08T09:00:00+00:00", 7),
        ("2026-10-06T12:00:00+00:00", "2026-10-09T00:00:00+00:00", 7),
        ("2026-10-07T00:00:00+00:00", "2026-10-09T00:00:00+00:00", 7),
    ],
)
def test_gw6_needs_both_merges_by_their_dates_and_either_miss_falls_back_to_gw7(
    monkeypatch: pytest.MonkeyPatch, protocol: str, runner: str, week: int
) -> None:
    """Rule 2 and Answer 5948324329: each date on its own, not only the GW6 deadline."""

    _bootstrap_deadlines(monkeypatch, {6: T0, 7: T0 + timedelta(days=7)})
    commits = {
        "protocol": {"commit": "a", "committed_utc": protocol},
        "runner": {"commit": "b", "committed_utc": runner},
    }
    assert chain.first_bound_week((_entry("newest", -1, 6),), Path("."), commits) == week


def test_no_decision_is_computed_before_the_freeze_ends_and_nothing_is_touched_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 40: a Saturday run after GW6's deadline, or a Sunday one before 10:00Z, refuses
    before the output check, the source identity, the lock or the inventory."""

    touched: list[str] = []

    def forbidden(name: str) -> object:
        def call(*args: object, **kwargs: object) -> object:
            touched.append(name)
            raise AssertionError(f"{name} ran before the boundary")

        return call

    for name in ("refuse_output", "source_identity", "single_run", "capture_inventory"):
        monkeypatch.setattr(chain, name, forbidden(name))
    for moment in (T0 + timedelta(hours=1), chain.FIRST_COMPUTATION - timedelta(seconds=1)):
        with pytest.raises(chain.ChainError, match="end of the freeze"):
            chain.decide(*ROOTS(tmp_path), tmp_path / "out", 6, "issuecomment-1", now=moment)
    assert touched == [] and not (tmp_path / "out").exists()
    with pytest.raises(AssertionError, match="refuse_output ran"):
        chain.decide(
            *ROOTS(tmp_path), tmp_path / "out", 6, "issuecomment-1", now=chain.FIRST_COMPUTATION
        )
    assert touched == ["refuse_output"]


def test_the_merge_identities_are_the_commits_on_the_line_they_were_merged_into(
    tmp_path: Path,
) -> None:
    """Rule 2 on a real history: a feature commit that added the file, a fix, a normal merge;
    then a squash merge. The identities are the merge and the squash commit."""

    def git(*arguments: str) -> str:
        return subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *arguments],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def write(path: str, text: str) -> None:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    git("init", "-q", "-b", "develop")
    write("README", "base")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    git("switch", "-q", "-c", "protocol")
    write(chain.PROTOCOL_FILE, "protocol")
    git("add", "-A")
    git("commit", "-q", "-m", "add the protocol")
    written = git("rev-parse", "HEAD")
    write(chain.PROTOCOL_FILE, "protocol, fixed")
    git("commit", "-q", "-am", "fix the protocol")
    git("switch", "-q", "develop")
    git("merge", "-q", "--no-ff", "protocol", "-m", "merge the protocol")
    merged = git("rev-parse", "HEAD")
    git("switch", "-q", "-c", "runner")
    write(chain.RUNNER_FILE, "runner")
    git("add", "-A")
    git("commit", "-q", "-m", "add the runner")
    git("switch", "-q", "develop")
    git("merge", "-q", "--squash", "runner")
    git("commit", "-q", "-m", "the runner, squashed")
    squashed = git("rev-parse", "HEAD")

    commits = chain.binding_commits(root=tmp_path)
    assert commits["protocol"]["commit"] == merged != written
    assert commits["runner"]["commit"] == squashed
    assert chain.frozen_commit(commits) == squashed == git("rev-parse", "HEAD")
    # Made within one second here, as two merges of one merge group can be: the line decides.
    assert commits["protocol"]["committed_utc"] <= commits["runner"]["committed_utc"]
    assert int(commits["runner"]["line_position"]) > int(commits["protocol"]["line_position"])


# Rules 6 to 8: the served forecast, read once and never rebuilt


def _served(tmp_path: Path, *, written_before_deadline: bool = True) -> tuple[Path, Path, str]:
    """A synthetic capture with its served v1 artifact, written at a chosen instant."""

    snapshots = tmp_path / "snapshots"
    bootstrap = json.loads(_bootstrap().decode("utf-8"))
    bootstrap["game_config"] = _game_config()
    bootstrap["chips"] = CHIPS
    capture = _capture(snapshots, bootstrap=json.dumps(bootstrap).encode("utf-8"))
    inputs = read_inputs(capture, season=chain.SEASON)
    artifacts = tmp_path / "artifacts"
    path = football_artifact_path(artifacts, capture.metadata.snapshot_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_artifact(inputs)), encoding="utf-8")
    deadline = chain._instant(inputs.deadline.deadline_utc)
    written = deadline + (timedelta(hours=-1) if written_before_deadline else timedelta(0))
    os.utime(path, (written.timestamp(), written.timestamp()))
    return snapshots, artifacts, capture.metadata.snapshot_id


def test_a_served_forecast_written_before_the_deadline_is_read_with_its_receipt(
    tmp_path: Path,
) -> None:
    snapshots, artifacts, snapshot_id = _served(tmp_path)
    week = chain.week_inputs(snapshots, artifacts, snapshot_id)
    assert isinstance(week, chain.WeekInputs)
    path = football_artifact_path(artifacts, snapshot_id)
    assert week.artifact_bytes == path.read_bytes()
    receipt = week.receipt
    assert receipt["artifact_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert receipt["forecast_fingerprint"] == week.forecast.fingerprint
    assert receipt["model_version"] == FOOTBALL_MODEL_VERSION
    assert receipt["snapshot_id"] == snapshot_id and receipt["capture_fingerprint"]
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    assert receipt["artifact_modified_utc"] == modified.isoformat()
    assert receipt["deadline_utc"] == week.inputs.deadline.deadline_utc
    assert receipt["reason"] is None


def test_a_capture_without_its_served_forecast_is_a_missing_week(tmp_path: Path) -> None:
    snapshots, artifacts, snapshot_id = _served(tmp_path)
    football_artifact_path(artifacts, snapshot_id).unlink()
    reason, receipt = chain.week_inputs(snapshots, artifacts, snapshot_id)  # type: ignore[misc]
    assert (reason, receipt["reason"], receipt["snapshot_id"]) == (
        "no_artifact",
        "no_artifact",
        snapshot_id,
    )


def test_a_forecast_written_at_the_deadline_is_a_missing_week(tmp_path: Path) -> None:
    snapshots, artifacts, snapshot_id = _served(tmp_path, written_before_deadline=False)
    reason, receipt = chain.week_inputs(snapshots, artifacts, snapshot_id)  # type: ignore[misc]
    assert reason == "artifact_written_at_or_after_deadline"
    assert len(str(receipt["artifact_sha256"])) == 64


def test_a_forecast_that_fails_its_fingerprint_is_a_missing_week(tmp_path: Path) -> None:
    snapshots, artifacts, snapshot_id = _served(tmp_path)
    path = football_artifact_path(artifacts, snapshot_id)
    stamp = path.stat().st_mtime
    document = json.loads(path.read_text(encoding="utf-8"))
    document["rows"][0]["expected_points"] = float(document["rows"][0]["expected_points"]) + 1.0
    path.write_text(json.dumps(document), encoding="utf-8")
    os.utime(path, (stamp, stamp))
    reason, _ = chain.week_inputs(snapshots, artifacts, snapshot_id)  # type: ignore[misc]
    assert reason == "artifact_unreadable_or_unbound"


def test_a_forecast_of_another_model_version_is_a_missing_week(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshots, artifacts, snapshot_id = _served(tmp_path)
    monkeypatch.setattr(chain, "ADMITTED_MODEL_VERSIONS", ("football_contextual_v3",))
    reason, receipt = chain.week_inputs(snapshots, artifacts, snapshot_id)  # type: ignore[misc]
    assert reason == "artifact_of_another_model_version"
    assert receipt["model_version"] == FOOTBALL_MODEL_VERSION


def test_the_admitted_versions_are_the_protocols_and_the_contextual_version_is_not() -> None:
    """Rule 6: three served versions by name, each one the reader accepts; research versions not."""

    assert chain.ADMITTED_MODEL_VERSIONS == (
        FOOTBALL_MODEL_VERSION,
        JOINT_ROLE_MODEL_VERSION,
        JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION,
    )
    for version in chain.ADMITTED_MODEL_VERSIONS:
        assert f"`{version}`" in PROTOCOL_TEXT
    assert "football_contextual_v3" not in chain.ADMITTED_MODEL_VERSIONS
    assert "`football_contextual_v3`, which that reader also accepts, was never" in PROTOCOL_TEXT


@pytest.mark.parametrize("version", ["football_contextual_v3", "football_nobody_v9"])
def test_the_model_version_is_read_from_the_artifact_before_any_reader_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str
) -> None:
    """Rule 6: a week of another version is missing as that, whether or not a reader knows it."""

    snapshots, artifacts, snapshot_id = _served(tmp_path)
    path = football_artifact_path(artifacts, snapshot_id)
    stamp = path.stat().st_mtime
    document = json.loads(path.read_text(encoding="utf-8"))
    document["model_version"] = version
    document["fingerprint"] = forecast_digest(document)
    path.write_text(json.dumps(document), encoding="utf-8")
    os.utime(path, (stamp, stamp))

    def never(*args: object, **kwargs: object) -> object:
        pytest.fail("a reader ran before the version was checked")

    monkeypatch.setattr(chain, "read_football_forecast", never)
    monkeypatch.setattr(chain, "load_switch_inputs", never)
    reason, receipt = chain.week_inputs(snapshots, artifacts, snapshot_id)  # type: ignore[misc]
    assert reason == receipt["reason"] == "artifact_of_another_model_version"
    assert receipt["model_version"] == version


def test_a_served_week_plans_on_the_forecast_the_service_binds(tmp_path: Path) -> None:
    """Rules 6 and 36: a v1 week without a bundle is bound as served, and the receipt says so."""

    snapshots, artifacts, snapshot_id = _served(tmp_path)
    week = chain.week_inputs(snapshots, artifacts, snapshot_id)
    assert isinstance(week, chain.WeekInputs)
    receipt = week.receipt
    assert receipt["ready_bundle_sha256"] is None and receipt["handoff_fingerprint"] is None
    assert receipt["rotation_table_sha256"] is None and receipt["components_bound"] is False
    assert receipt["participation_version"] == FOOTBALL_PARTICIPATION_VERSION
    information = receipt["decision_information"]
    assert information["version"] == "football_decision_information_v1"
    assert len(information["revision"]) == 64
    assert information["coach_news_bound"] is False
    assert information["minute_components_bound"] is False
    assert receipt["forecast_training_selection"] is None
    assert receipt["forecast_role_metadata"] is None
    evidence = week.forecast.projection.diagnostics["participation_evidence"]
    assert evidence["version"] == FOOTBALL_PARTICIPATION_VERSION
    assert evidence["base_revision"] == week.forecast.fingerprint == receipt["forecast_fingerprint"]


@pytest.fixture
def bundle_case(publication_case: dict[str, Any], request: pytest.FixtureRequest) -> dict[str, Any]:
    """The bundle tests' sealed-bundle case, with the season rules the chain reads."""

    publication_case["bootstrap_extra"] = {"game_config": _game_config(), "chips": CHIPS}
    return request.getfixturevalue("case")


@pytest.mark.parametrize("version", JOINT_ROLE_MODEL_VERSIONS)
def test_a_joint_week_is_read_by_the_real_reader_and_bound_only_under_a_ready_bundle(
    bundle_case: dict[str, Any], tmp_path: Path, version: str
) -> None:
    """Rule 6: a joint forecast is admitted under its own name, through the reader and the
    service's own binding, so it needs the ready bundle the service needs, sealed against the
    served handoff."""

    make_joint_pair(bundle_case, version=version)
    roots = (
        bundle_case["snapshot_root"],
        bundle_case["artifact_root"],
        bundle_case["snapshot_id"],
    )
    handoffs = tmp_path / "handoffs"
    handoffs.mkdir()
    shutil.copy(bundle_case["handoff_path"], handoff_path_for(handoffs, chain.SEASON, 6))
    artifact = football_artifact_path(bundle_case["artifact_root"], bundle_case["snapshot_id"])
    inputs = read_inputs(chain.read_snapshot(roots[0], roots[2]), season=chain.SEASON)
    before = (chain._instant(inputs.deadline.deadline_utc) - timedelta(hours=1)).timestamp()
    os.utime(artifact, (before, before))

    reason, receipt = chain.week_inputs(*roots, handoff_root=handoffs)  # type: ignore[misc]
    assert reason == receipt["reason"] == "served_binding_refused"
    assert receipt["model_version"] == version and receipt["ready_bundle_sha256"] is None
    assert any("requires a complete ready bundle" in note for note in receipt["binding_notes"])

    ready = seal_football_bundle(**bundle_case)
    os.utime(artifact, (before, before))
    week = chain.week_inputs(*roots, handoff_root=handoffs)
    assert isinstance(week, chain.WeekInputs)
    assert week.receipt["reason"] is None
    assert week.receipt["model_version"] == version == week.forecast.horizon.model_version
    assert week.receipt["ready_bundle_sha256"] == ready.fingerprint
    assert week.receipt["handoff_fingerprint"] == ready.handoff_fingerprint
    assert week.receipt["components_bound"] is True
    assert week.receipt["decision_information"]["minute_components_bound"] is True
    assert week.receipt["forecast_role_metadata"]["version"]
    assert week.forecast.projection.diagnostics["fixture_role_estimates"]

    reason, receipt = chain.week_inputs(*roots)  # type: ignore[misc]
    assert reason == "served_binding_refused"
    assert any("served baseline handoff" in note for note in receipt["binding_notes"])


def test_the_binding_is_asked_with_the_capture_the_handoff_and_the_configured_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rules 6 and 8: the service is asked as it was asked when serving, and its answer is kept."""

    snapshots, artifacts, snapshot_id = _served(tmp_path)
    inputs = read_inputs(chain.read_snapshot(snapshots, snapshot_id), season=chain.SEASON)
    forecast = chain.read_football_forecast(football_artifact_path(artifacts, snapshot_id), inputs)
    asked: dict[str, Any] = {}

    def service(**kwargs: Any) -> Any:
        asked.update(kwargs)
        return SimpleNamespace(
            football=forecast,
            football_bundle_sha256="b" * 64,
            rotation_table_sha256="r" * 64,
            football_components_sha256="c" * 64,
            football_components_bound=True,
            notes=("top100: none",),
            decision_information=lambda snapshot: {
                "version": "football_decision_information_v1",
                "revision": "d" * 64,
                "source_snapshot_id": snapshot,
            },
        )

    monkeypatch.setattr(chain, "load_switch_inputs", service)
    monkeypatch.setattr(
        chain,
        "handoff_fingerprint_for",
        lambda root, season, gameweek, snapshot: f"{root.name}:{season}:{gameweek}:{snapshot}",
    )
    source = tmp_path / "club-news-source.json"
    week = chain.week_inputs(
        snapshots,
        artifacts,
        snapshot_id,
        handoff_root=tmp_path / "handoffs",
        club_news_source=source,
    )
    assert isinstance(week, chain.WeekInputs)
    assert asked["artifact_root"] == artifacts and asked["snapshot_root"] == snapshots
    assert asked["club_news_source"] == source
    assert asked["inputs"].snapshot_id == snapshot_id
    fingerprint = f"handoffs:{chain.SEASON}:{inputs.deadline.gameweek}:{snapshot_id}"
    assert asked["projection"].diagnostics == {"projection_handoff_fingerprint": fingerprint}
    assert week.receipt["handoff_fingerprint"] == fingerprint
    assert week.receipt["ready_bundle_sha256"] == "b" * 64
    assert week.receipt["rotation_table_sha256"] == "r" * 64
    assert week.receipt["components_sha256"] == "c" * 64
    assert week.receipt["components_bound"] is True
    assert week.receipt["binding_notes"] == ["top100: none"]
    assert week.receipt["decision_information"]["revision"] == "d" * 64


def test_the_command_line_names_the_handoff_root(tmp_path: Path) -> None:
    """Rules 6 and 8: the served handoff's root is an input, read for its fingerprint only."""

    with pytest.raises(SystemExit) as refused:
        chain.main(["check", "--snapshot-root", str(tmp_path), "--artifact-root", str(tmp_path)])
    assert refused.value.code == 2


def test_a_forecast_that_changed_while_it_was_read_is_a_missing_week(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshots, artifacts, snapshot_id = _served(tmp_path)
    real = chain.read_football_forecast
    monkeypatch.setattr(
        chain,
        "read_football_forecast",
        lambda path, inputs: replace(real(path, inputs), fingerprint="another"),
    )
    reason, _ = chain.week_inputs(snapshots, artifacts, snapshot_id)  # type: ignore[misc]
    assert reason == "artifact_changed_while_read"


def test_the_capture_index_keeps_this_seasons_captures_and_refuses_an_unreadable_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshots, _, snapshot_id = _served(tmp_path)
    (entry,) = chain.capture_index(snapshots)
    inputs = read_inputs(chain.read_snapshot(snapshots, snapshot_id), season=chain.SEASON)
    assert entry.snapshot_id == snapshot_id
    assert entry.target == int(inputs.deadline.gameweek)
    assert entry.deadline_utc == chain._instant(inputs.deadline.deadline_utc)
    monkeypatch.setattr(chain, "infer_season", lambda snapshot: "2025-26")
    assert chain.capture_index(snapshots) == ()
    monkeypatch.setattr(chain, "infer_season", lambda snapshot: chain.SEASON)

    def unreadable(snapshot: object, *, season: str) -> object:
        raise ValueError("no deadline")

    monkeypatch.setattr(chain, "read_inputs", unreadable)
    with pytest.raises(chain.ChainError, match=snapshot_id):
        chain.capture_index(snapshots)


# Rule 9: the squads, proved, retried once and dropped alone


def test_a_squad_is_retried_at_240_units_and_dropped_alone_when_still_unproved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statuses = {
        1000: [SolverStatus.OPTIMAL],
        950: [SolverStatus.FEASIBLE, SolverStatus.OPTIMAL],
        900: [SolverStatus.FEASIBLE, SolverStatus.FEASIBLE],
    }
    calls: list[tuple[int, float, float]] = []

    def optimize(first: pd.DataFrame, config: OptimizationConfig, **_: object) -> object:
        budget = int(config.budget_tenths)
        calls.append(
            (
                budget,
                float(config.solver_deterministic_time_limit or 0),
                float(config.solver_time_limit_seconds),
            )
        )
        status = statuses[budget].pop(0)
        squad = pd.DataFrame({"player_id": list(SQUAD)})
        stopped = budget == 900 and len(statuses[budget]) == 0
        return SimpleNamespace(
            solver_status=status,
            selected_squad=squad,
            starting_xi=None,
            bench=None,
            captain=None,
            diagnostics={} if stopped else {"deterministic_time_budget_exhausted": True},
        )

    monkeypatch.setattr(chain, "optimize_squad", optimize)
    monkeypatch.setattr(chain, "_lineup_block", lambda week: dict(LINEUP))
    forecast = SimpleNamespace(horizon=SimpleNamespace(table=_table()))
    squads = chain.initial_states(forecast, 6)  # type: ignore[arg-type]
    assert calls == [
        (1000, 60.0, 120.0),
        (950, 60.0, 120.0),
        (950, 240.0, 480.0),
        (900, 60.0, 120.0),
        (900, 240.0, 480.0),
    ]
    assert squads.statuses["p900"] == ["FEASIBLE", "FEASIBLE_clock_stopped"]
    assert set(squads.states) == {"p1000", "p950"}
    assert squads.dropped == {"p900": "squad_not_proved_at_240_units"}
    assert squads.statuses["p950"] == ["FEASIBLE", "OPTIMAL"]
    cost = sum(50 + p for p in SQUAD)
    first, second = squads.states["p1000"], squads.states["p950"]
    assert (first.bank_tenths, first.free_transfers) == (1000 - cost, 1)
    assert (second.bank_tenths, second.free_transfers) == (1000 - cost, 2)
    assert dict(first.purchase_prices) == {p: 50 + p for p in SQUAD}
    assert first.decided_gameweek == 5 and first.lineup == LINEUP


# Rules 11 to 14: the arms, their budgets and their truncation


@pytest.mark.parametrize(
    ("arm", "gameweek", "weeks", "units", "truncated"),
    [
        ("served_3", 6, (6, 7, 8), 60.0, False),
        ("served_5", 6, (6, 7, 8, 9, 10), 100.0, False),
        ("served_3", 37, (37, 38), 40.0, True),
        ("served_5", 35, (35, 36, 37, 38), 80.0, True),
        ("served_5", 38, (38,), 20.0, True),
    ],
)
def test_the_served_arm_is_the_member_window_at_twenty_units_a_week(
    monkeypatch: pytest.MonkeyPatch,
    arm: str,
    gameweek: int,
    weeks: tuple[int, ...],
    units: float,
    truncated: bool,
) -> None:
    seen: dict[str, object] = {}

    def served(inputs: object, horizon: object, held: object, rules: object, **kwargs: Any) -> Any:
        seen.update(horizon=horizon, **kwargs)
        return _plan(_plan_week(gameweek=gameweek)), SimpleNamespace(configuration_fingerprint="c")

    monkeypatch.setattr(chain, "plan_transfer_horizon", served)
    monkeypatch.setattr(chain, "_lineup_block", lambda week: dict(LINEUP))
    outcome = chain.run_arm(arm, _week(gameweek), _state(decided=gameweek - 1).held())
    optimization = seen["optimization"]
    assert seen["horizon"] == weeks
    assert optimization.solver_deterministic_time_limit == units  # type: ignore[attr-defined]
    assert optimization.solver_time_limit_seconds == 1800.0  # type: ignore[attr-defined]
    assert seen["linearization_level"] == 2
    assert (outcome.weeks, outcome.deterministic_units, outcome.truncated) == (
        weeks,
        units,
        truncated,
    )
    assert outcome.failure is None and outcome.lineup == LINEUP


@pytest.mark.parametrize(
    ("arm", "gameweek", "primary"), [("hold_3", 6, 59.0), ("hold_5", 37, 39.0)]
)
def test_the_hold_arm_is_one_unit_short_so_its_probe_brings_it_level(
    monkeypatch: pytest.MonkeyPatch, arm: str, gameweek: int, primary: float
) -> None:
    seen: dict[str, Any] = {}
    prepared = chain.PreparedWindow(
        "table",  # type: ignore[arg-type]
        "state",  # type: ignore[arg-type]
        SimpleNamespace(configuration_fingerprint="c"),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(chain, "prepare_window", lambda *args, **kwargs: prepared)
    monkeypatch.setattr(chain, "PlanningHorizon", lambda table: ("horizon", table))

    def optimize(
        horizon: object, state: object, config: OptimizationConfig, policy: object, **kwargs: Any
    ) -> Any:
        seen.update(horizon=horizon, config=config, **kwargs)
        return _plan(_plan_week(gameweek=gameweek))

    monkeypatch.setattr(chain, "optimize_transfer_plan", optimize)
    monkeypatch.setattr(chain, "_lineup_block", lambda week: dict(LINEUP))
    outcome = chain.run_arm(arm, _week(gameweek), _state(decided=gameweek - 1).held())
    assert seen["config"].solver_deterministic_time_limit == primary
    assert primary + chain.HOLD_PROBE_UNITS == outcome.deterministic_units
    assert seen["protect_hold"] is True and seen["linearization_level"] == 2
    assert outcome.route == "hold"


def test_the_one_week_arm_is_the_member_week_at_its_own_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def one_week(
        inputs: object, projection: object, held: object, rules: object, **kwargs: Any
    ) -> Any:
        seen.update(projection=projection, **kwargs)
        return _plan(_plan_week()), None, SimpleNamespace(configuration_fingerprint="c")

    monkeypatch.setattr(chain, "plan_transfers", one_week)
    monkeypatch.setattr(chain, "_lineup_block", lambda week: dict(LINEUP))
    week = _week()
    outcome = chain.run_arm("one_week", week, _state().held())
    assert seen["projection"] is week.forecast.projection
    assert seen["optimization"].solver_deterministic_time_limit == 20.0
    assert seen["optimization"].solver_time_limit_seconds == 300.0
    assert (outcome.route, outcome.weeks, outcome.truncated) == ("one_week", (6,), False)


@pytest.mark.parametrize(
    ("diagnostics", "status", "reason"),
    [
        (
            {"hold_protection": {"status": "FEASIBLE", "deterministic_time": 0.4}},
            None,
            "hold_probe_clock_stopped",
        ),
        (
            {"hold_protection": {"status": "UNKNOWN", "deterministic_time": 0.0}},
            None,
            "hold_probe_clock_stopped",
        ),
        ({"hold_protection": {"status": "OPTIMAL", "deterministic_time": 0.0004}}, None, None),
        ({"hold_protection": {"status": "FEASIBLE", "deterministic_time": 1.0}}, None, None),
        ({}, SolverStatus.UNKNOWN, "no_plan"),
    ],
)
def test_an_arm_fails_where_the_protocol_says_and_only_there(
    monkeypatch: pytest.MonkeyPatch,
    diagnostics: dict[str, object],
    status: SolverStatus | None,
    reason: str | None,
) -> None:
    plan = _plan(
        None if status is not None else _plan_week(),
        status=status or SolverStatus.OPTIMAL,
        diagnostics={"deterministic_time_budget_exhausted": True, **diagnostics},
    )
    monkeypatch.setattr(
        chain,
        "plan_transfers",
        lambda *a, **k: (plan, None, SimpleNamespace(configuration_fingerprint="c")),
    )
    monkeypatch.setattr(chain, "_lineup_block", lambda week: dict(LINEUP))
    assert chain.run_arm("one_week", _week(), _state().held()).failure == reason


def test_a_plan_the_wall_clock_stopped_fails_the_week(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan(_plan_week(), status=SolverStatus.FEASIBLE, diagnostics={})
    monkeypatch.setattr(
        chain,
        "plan_transfers",
        lambda *a, **k: (plan, None, SimpleNamespace(configuration_fingerprint="c")),
    )
    outcome = chain.run_arm("one_week", _week(), _state().held())
    assert outcome.failure == "wall_clock_stopped_the_search"
    assert outcome.lineup is None


def test_a_raising_arm_fails_with_a_stable_reason_and_a_runner_refusal_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raises(*args: object, **kwargs: object) -> object:
        raise ValueError("no solution within 0.1234 units")

    monkeypatch.setattr(chain, "plan_transfers", raises)
    outcome = chain.run_arm("one_week", _week(), _state().held())
    assert (outcome.failure, outcome.plan) == ("raised_ValueError", None)
    assert outcome.work == {"error": "no solution within 0.1234 units"}

    def refuses(*args: object, **kwargs: object) -> object:
        raise chain.ChainError("refused")

    monkeypatch.setattr(chain, "plan_transfers", refuses)
    with pytest.raises(chain.ChainError):
        chain.run_arm("one_week", _week(), _state().held())


def test_an_incomplete_lineup_fails_the_arm_instead_of_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        chain,
        "plan_transfers",
        lambda *a, **k: (_plan(_plan_week()), None, SimpleNamespace(configuration_fingerprint="c")),
    )

    def incomplete(week: object) -> dict[str, object]:
        raise EntryError("The plan's bench must hold exactly one goalkeeper.")

    monkeypatch.setattr(chain, "_lineup_block", incomplete)
    assert chain.run_arm("one_week", _week(), _state().held()).failure == "incomplete_lineup"


def test_the_served_route_reads_the_observed_block_before_its_guarded_baselines() -> None:
    both = _plan(
        diagnostics={
            "observed_window": {"version": "bounded_observed_window_v1"},
            "sequential_incumbent": {"version": "sequential_certified_window_v1"},
        }
    )
    guarded = _plan(
        diagnostics={"sequential_incumbent": {"version": "sequential_certified_window_v1"}}
    )
    expected = _plan(
        diagnostics={
            "expected_lineup_window": {"version": "expected_lineup_window_v1"},
            "sequential_incumbent": {"version": "sequential_certified_window_v1"},
        }
    )
    assert chain._route(both) == ("observed", "bounded_observed_window_v1")  # type: ignore[arg-type]
    assert chain._route(expected) == ("expected", "expected_lineup_window_v1")  # type: ignore[arg-type]
    assert chain._route(guarded) == ("guarded", "sequential_certified_window_v1")  # type: ignore[arg-type]
    assert chain._route(_plan(diagnostics={})) == ("standard", None)  # type: ignore[arg-type]


def test_an_observed_comparison_is_published_feasible_and_not_counted_as_proved() -> None:
    observed = _plan(
        status=SolverStatus.OPTIMAL,
        diagnostics={
            "observed_window": {"status": "compared", "actual_total": 41.5},
            "sequential_incumbent": {"seed_completed": True, "actual_total": 20.0},
            "selection_status": "FEASIBLE_RESTRICTED_MENU",
            "solve_time_seconds": 9.0,
        },
    )
    status = chain._status(observed, "observed")  # type: ignore[arg-type]
    assert status == {
        "solver_status": "OPTIMAL",
        "published_status": "FEASIBLE",
        "proved": False,
        "selection_status": "FEASIBLE_RESTRICTED_MENU",
        "observed_window_status": "compared",
        "expected_window_status": None,
        "expected_window_chosen": None,
        "seed_completed": True,
        "seed_note": None,
    }
    nominal = _plan(diagnostics={"observed_window": {"status": "compared"}})
    assert chain._status(nominal, "observed")["seed_note"] == (  # type: ignore[arg-type]
        "observed_action_is_not_the_guarded_baseline"
    )
    assert chain._status(_plan(diagnostics={}), "hold")["seed_note"] == (  # type: ignore[arg-type]
        "no_guarded_construction"
    )
    assert chain._work(observed) == {"deterministic_time_used": 41.5, "solve_time_seconds": 9.0}  # type: ignore[arg-type]
    standard = _plan(
        diagnostics={
            "deterministic_time_used": 2.0,
            "hold_protection": {"deterministic_time": 0.5},
            "solve_time_seconds": 1.0,
        }
    )
    assert chain._status(standard, "standard")["proved"] is True  # type: ignore[arg-type]
    assert chain._work(standard)["deterministic_time_used"] == 2.5  # type: ignore[arg-type]


# Rules 11 and 18: the hold arm is the standard path, and the carry is the ledger's


@pytest.mark.parametrize("length", [3, 5])
def test_the_hold_arm_is_the_standard_path_plan_for_plan(tmp_path: Path, length: int) -> None:
    """A control-model horizon takes the standard path, so the two must agree exactly."""

    inputs, horizon, held, rules = _inputs(tmp_path, tuple(range(2, 2 + length)))
    served, served_policy = plan_transfer_horizon(
        inputs, horizon, held, rules, optimization=BUDGET, linearization_level=2
    )
    prepared = chain.prepare_window(inputs, horizon, held, rules, deterministic_units=20)
    ours = optimize_transfer_plan(
        PlanningHorizon(prepared.planning_table),
        prepared.state,
        BUDGET,
        prepared.policy,
        linearization_level=2,
        protect_hold=True,
    )
    assert prepared.policy.configuration_fingerprint == served_policy.configuration_fingerprint
    assert ours.diagnostics["horizon_fingerprint"] == served.diagnostics["horizon_fingerprint"]
    assert ours.solver_status == served.solver_status
    assert ours.objective_value == served.objective_value
    for mine, theirs in zip(ours.weeks, served.weeks, strict=True):
        assert sorted(mine.selected_squad.player_id) == sorted(theirs.selected_squad.player_id)
        assert sorted(mine.transfers_in.player_id) == sorted(theirs.transfers_in.player_id)
        assert mine.bank_after_tenths == theirs.bank_after_tenths
        assert int(mine.captain["player_id"]) == int(theirs.captain["player_id"])


def _football(horizon: Any, *, appearance: bool) -> Any:
    """The synthetic window relabelled as the football forecast the routed planner takes."""

    table = horizon.table.copy()
    if appearance:
        table["appearance_probability"] = 0.9
    return replace(
        horizon,
        table=table,
        model_name=chain.FOOTBALL_HORIZON_MODEL,
        model_version=FOOTBALL_MODEL_VERSION,
        contract_version=(
            APPEARANCE_HORIZON_CONTRACT_VERSION if appearance else horizon.contract_version
        ),
    )


@pytest.mark.parametrize("length", [3, 5])
def test_a_routed_football_window_and_the_hold_arm_share_one_policy(
    tmp_path: Path, length: int
) -> None:
    """Rule 12 on the path the chain takes: a football window the planner routes and finances.

    The synthetic tests above use a control-model horizon, which takes the standard path, so
    they could not see that a routed football window now plans under a second policy flag.
    """

    inputs, horizon, held, rules = _inputs(tmp_path, tuple(range(2, 2 + length)))
    football = _football(horizon, appearance=False)
    served, served_policy = plan_transfer_horizon(
        inputs, football, held, rules, optimization=BUDGET, linearization_level=2
    )
    prepared = chain.prepare_window(inputs, football, held, rules, deterministic_units=20)
    assert served_policy.allow_two_free_transfers is True
    assert prepared.policy == served_policy
    assert prepared.policy.configuration_fingerprint == served_policy.configuration_fingerprint
    assert chain._route(served) == ("guarded", GUARDED_PLANNER_VERSION)


def test_an_expected_lineup_window_is_named_as_its_own_route(tmp_path: Path) -> None:
    """Rule 13: its guarded proposals carry the guarded block, so the route is read first."""

    inputs, horizon, held, rules = _inputs(tmp_path, (2, 3, 4))
    served, _policy = plan_transfer_horizon(
        inputs,
        _football(horizon, appearance=True),
        held,
        rules,
        optimization=BUDGET,
        linearization_level=2,
    )
    review = served.diagnostics["expected_lineup_window"]
    assert "sequential_incumbent" in served.diagnostics
    # Rule 3: the route's version string is whatever the frozen commit carries (v1 at fix11,
    # v2 since #948); the record names it, and the test holds the route, not the digit.
    assert str(review["version"]).startswith("expected_lineup_window_v")
    assert chain._route(served) == ("expected", review["version"])
    status = chain._status(served, "expected")
    assert status["expected_window_status"] == review["status"]
    assert status["expected_window_chosen"] == review["chosen"]
    assert chain._work(served)["deterministic_time_used"] == review["actual_total"]


def test_a_control_or_truncated_window_keeps_the_one_move_policy(tmp_path: Path) -> None:
    inputs, horizon, held, rules = _inputs(tmp_path, (2, 3, 4))
    control = chain.prepare_window(inputs, horizon, held, rules, deterministic_units=60)
    assert control.policy.allow_two_free_transfers is False
    # Two weeks is neither three nor five: the planner takes the standard path, and so does
    # the hold arm's policy.
    inputs, horizon, held, rules = _inputs(tmp_path / "short", (2, 3))
    short = _football(horizon, appearance=False)
    _, served_policy = plan_transfer_horizon(
        inputs, short, held, rules, optimization=BUDGET, linearization_level=2
    )
    prepared = chain.prepare_window(inputs, short, held, rules, deterministic_units=40)
    assert served_policy.allow_two_free_transfers is False
    assert prepared.policy.configuration_fingerprint == served_policy.configuration_fingerprint


def test_the_routing_names_the_runner_copies_are_the_planners() -> None:
    source = inspect.getsource(live_transfers.plan_transfer_horizon)
    assert f'model_name == "{chain.FOOTBALL_HORIZON_MODEL}"' in source
    assert "allow_two_free_transfers=True" in source
    assert "len(projection_horizon.target_gameweeks) in (3, 5)" in source


def _lowered(tmp_path: Path) -> tuple[Any, Any, Any, Any]:
    """The synthetic window with every purchase four tenths below its current price."""

    inputs, horizon, held, rules = _inputs(tmp_path, (2, 3, 4))
    lowered = replace(held, purchase_prices={p: v - 4 for p, v in held.purchase_prices.items()})
    return inputs, horizon, lowered, rules


def test_the_hold_arm_sells_at_the_games_price_not_the_current_one(tmp_path: Path) -> None:
    inputs, horizon, held, rules = _lowered(tmp_path)
    prepared = chain.prepare_window(inputs, horizon, held, rules, deterministic_units=20)
    table = prepared.planning_table.loc[prepared.planning_table.gameweek.eq(2)]
    fee = float(rules.transfers.sell_on_fee)
    current = dict(zip(table.player_id, table.buy_price_tenths, strict=True))
    for player in held.squad_player_ids:
        row = table.loc[table.player_id.eq(player)].iloc[0]
        expected = sell_price_tenths(
            int(current[player]), held.purchase_prices[player], sell_on_fee=fee
        )
        assert int(row.sell_price_tenths) == expected != int(current[player])


def test_the_hold_arm_refuses_a_horizon_from_another_capture(tmp_path: Path) -> None:
    inputs, horizon, held, rules = _inputs(tmp_path, (2, 3, 4))
    with pytest.raises(chain.ChainError):
        chain.prepare_window(
            replace(inputs, snapshot_id="another-capture"),
            horizon,
            held,
            rules,
            deterministic_units=20,
        )


def test_the_state_after_a_week_is_the_ledgers_state_after_it(tmp_path: Path) -> None:
    inputs, horizon, held, rules = _lowered(tmp_path)
    plan, policy = plan_transfer_horizon(
        inputs, horizon, held, rules, optimization=BUDGET, linearization_level=2
    )
    assert len(plan.weeks[0].transfers_out) > 0, "the carry must exercise a sale"
    first = horizon.table.loc[horizon.table.gameweek == 2]
    current = {int(p): int(c) for p, c in zip(first.player_id, first.price_tenths, strict=True)}
    fee = float(rules.transfers.sell_on_fee)
    sells = {
        p: sell_price_tenths(current[p], held.purchase_prices[p], sell_on_fee=fee)
        for p in held.squad_player_ids
    }
    ledger = live_transfers._package_decision(plan, held, None, policy, sells, current, fee)
    state = chain.ChainState(
        held.squad_player_ids,
        dict(held.purchase_prices),
        held.bank_tenths,
        held.free_transfers,
        held.decided_gameweek,
    )
    after = chain.advance(state, plan.weeks[0], current, fee, LINEUP)
    assert dict(after.purchase_prices) == dict(ledger.purchase_prices_after)
    assert after.bank_tenths == ledger.bank_after_tenths
    assert after.free_transfers == ledger.free_transfers_after
    assert (after.decided_gameweek, after.lineup) == (2, LINEUP)


def test_a_sale_is_credited_at_the_games_price() -> None:
    state = _state(bank=10)
    current = {p: 50 + p for p in SQUAD} | {1: 57, 16: 52}
    squad = (16, *SQUAD[1:])
    sale = sell_price_tenths(57, 51, sell_on_fee=0.5)
    week = _plan_week(squad, out=(1,), into=(16,), bank_after=10 + sale - 52)
    after = chain.advance(state, week, current, 0.5, LINEUP)  # type: ignore[arg-type]
    assert sale == 54 != 57
    assert after.bank_tenths == 12
    assert dict(after.purchase_prices)[16] == 52 and 1 not in after.purchase_prices


def test_a_plan_whose_bank_does_not_follow_from_its_moves_stops_the_run() -> None:
    state = _state(bank=10)
    current = {p: 50 + p for p in SQUAD} | {16: 52}
    week = _plan_week((16, *SQUAD[1:]), out=(1,), into=(16,), bank_after=10 + 51 - 52 + 1)
    with pytest.raises(chain.ChainError, match="bank"):
        chain.advance(state, week, current, 0.5, LINEUP)  # type: ignore[arg-type]
    unlisted = _plan_week((17, *SQUAD[1:]), out=(1,), into=(16,), bank_after=9)
    with pytest.raises(chain.ChainError, match="purchase prices"):
        chain.advance(state, unlisted, current, 0.5, LINEUP)  # type: ignore[arg-type]


# Rules 21 to 23: a missing week holds, a failed arm plays its held team, a blocked chain stops


@pytest.mark.parametrize(("before", "cap", "expected"), [(1, 5, 2), (5, 5, 5), (0, 2, 1)])
def test_a_held_week_banks_one_free_transfer_up_to_the_captured_maximum(
    before: int, cap: int, expected: int
) -> None:
    state = chain.ChainState((1, 2), {1: 50, 2: 60}, 7, before, 5, LINEUP)
    held = chain.hold(state, 6, cap)
    assert (held.free_transfers, held.decided_gameweek) == (expected, 6)
    assert (held.squad, dict(held.purchase_prices), held.bank_tenths) == ((1, 2), {1: 50, 2: 60}, 7)
    assert held.lineup == LINEUP


def test_a_missing_week_holds_every_chain_that_is_not_blocked() -> None:
    missing = ("no_own_target_capture", {"snapshot_id": None})
    record = chain._chain_record(("p1000", "served_3"), _state(free=1), 6, missing, set(), "c", 5)
    assert (record.document["status"], record.document["reason"]) == (
        "held",
        "no_own_target_capture",
    )
    assert record.state_after.free_transfers == 2
    blocked = {("p1000", "served_3")}
    again = chain._chain_record(("p1000", "served_3"), _state(), 6, missing, blocked, "c", 5)
    assert again.document["status"] == "blocked" and again.blocked


def test_a_held_player_absent_from_the_roster_blocks_that_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def never(*args: object) -> object:
        raise AssertionError("a blocked chain is never solved")

    monkeypatch.setattr(chain, "run_arm", never)
    blocked: set[tuple[str, str]] = set()
    week = _week(roster=SQUAD[1:])
    record = chain._chain_record(("p1000", "hold_3"), _state(), 6, week, blocked, "c", 5)
    assert (record.document["status"], record.document["reason"]) == (
        "blocked",
        "held_player_absent",
    )
    assert blocked == {("p1000", "hold_3")}


def test_a_failed_arm_plays_its_held_team_and_stays_in_the_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chain, "run_arm", lambda *a: _outcome(None, failure="raised_ValueError"))
    record = chain._chain_record(("p1000", "served_5"), _state(free=1), 6, _week(), set(), "c", 5)
    document = record.document
    assert (document["status"], document["reason"]) == ("failed", "raised_ValueError")
    assert document["advice"] == {**LINEUP, "transfer_hit_points": 0.0}
    assert sorted(int(p) for p in document["players"]) == list(SQUAD)  # type: ignore[union-attr]
    assert record.state_after == replace(_state(free=2), decided_gameweek=6)


def test_a_decided_week_records_the_plan_the_lineup_and_the_carry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chain, "run_arm", lambda *a: _outcome(_plan(_plan_week())))
    record = chain._chain_record(("p950", "served_3"), _state(), 6, _week(), set(), "abc", 5)
    document = record.document
    assert document["status"] == "decided"
    assert document["advice"] == LINEUP
    assert document["forecast"] == {
        "sha256": "a" * 64,
        "fingerprint": "forecast",
        "model_version": FOOTBALL_MODEL_VERSION,
    }
    assert document["provenance"] == {"repository_commit": "abc"}
    assert document["outcome_read"] is False and document["locked_holdout_accessed"] is False
    assert document["policy"]["truncated"] is False  # type: ignore[index]
    assert record.state_after.decided_gameweek == 6


# Rule 12: served and hold, planning from one state, agree in their plans' fingerprints


def _twins(
    served: str, hold: str, *, same_state: bool = True
) -> dict[tuple[str, str], chain.ChainRecord]:
    def record(arm: str, fingerprint: str, state: chain.ChainState) -> chain.ChainRecord:
        policy = {"configuration_fingerprint": "c", "horizon_fingerprint": fingerprint}
        document = {"state_before": state.to_json(), "policy": policy}
        return chain.ChainRecord(f"p1000-{arm}.json", document, state)

    other = _state(bank=21) if not same_state else _state()
    return {
        ("p1000", "served_3"): record("served_3", served, _state()),
        ("p1000", "hold_3"): record("hold_3", hold, other),
    }


def test_served_and_hold_from_one_state_must_share_their_fingerprints() -> None:
    chain._refuse_unequal_twins(_twins("h", "h"))
    chain._refuse_unequal_twins(_twins("h", "other", same_state=False))
    with pytest.raises(chain.ChainError, match="horizon_fingerprint"):
        chain._refuse_unequal_twins(_twins("h", "other"))


# Rule 24: a week is computed, checked, then written once; an interrupted week resumes


def test_a_week_writes_its_receipt_forecast_records_and_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chain, "run_arm", lambda *a: _outcome(_plan(_plan_week())))
    states = {("p1000", arm): _state() for arm in chain.ARMS}
    after, max_free, digest = chain.decide_week(tmp_path, 6, _week(), states, set(), "c", 2)
    directory = tmp_path / "gw06"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert digest == hashlib.sha256((directory / "manifest.json").read_bytes()).hexdigest()
    assert (directory / "forecast.json").read_bytes() == b'{"fingerprint": "forecast"}'
    receipt = json.loads((directory / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["snapshot_id"] == "capture-gw6" and receipt["artifact_sha256"] == "a" * 64
    assert sorted(manifest["records"]) == sorted(f"p1000-{arm}.json" for arm in chain.ARMS)
    for name, sha in manifest["records"].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == sha
    assert max_free == 5 and set(after) == set(states)


def test_an_interrupted_week_carries_its_written_records_without_solving_them_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def arm(name: str, week: object, held: object) -> chain.ArmOutcome:
        calls.append(name)
        return _outcome(_plan(_plan_week()))

    monkeypatch.setattr(chain, "run_arm", arm)
    written_after = replace(_state(bank=33), decided_gameweek=6)
    existing = chain._record(
        gameweek=6,
        profile="p1000",
        arm="served_3",
        status="decided",
        state_after=written_after.to_json(),
    )
    write_document_once(existing, tmp_path / "gw06" / "p1000-served_3.json")
    states = {("p1000", "served_3"): _state(), ("p1000", "one_week"): _state()}
    after, _, _ = chain.decide_week(tmp_path, 6, _week(), states, set(), "c", 2)
    assert calls == ["one_week"]
    assert after[("p1000", "served_3")] == written_after


def test_a_resumed_season_keeps_a_blocked_chain_blocked(tmp_path: Path) -> None:
    directory = tmp_path / "gw06"
    blocked_before = _state()
    records = {
        "p1000-served_3.json": chain._record(
            gameweek=6,
            profile="p1000",
            arm="served_3",
            status="blocked",
            reason="held_player_absent",
            state_before=blocked_before.to_json(),
        ),
        "p1000-hold_3.json": chain._record(
            gameweek=6,
            profile="p1000",
            arm="hold_3",
            status="held",
            state_after=replace(_state(free=2), decided_gameweek=6).to_json(),
        ),
    }
    for name, document in records.items():
        write_document_once(document, directory / name)
    manifest = chain._record(gameweek=6, max_free_transfers=5, records=dict.fromkeys(records, ""))
    write_document_once(manifest, directory / "manifest.json")
    blocked: set[tuple[str, str]] = set()
    states, max_free = chain._load_week(directory, blocked)
    assert blocked == {("p1000", "served_3")} and max_free == 5
    assert states[("p1000", "served_3")] == replace(blocked_before, decided_gameweek=6)
    assert states[("p1000", "hold_3")].free_transfers == 2


def test_a_week_whose_twins_disagree_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        chain,
        "run_arm",
        lambda arm, *a: _outcome(
            _plan(_plan_week()), horizon="h" if arm.startswith("served") else "x"
        ),
    )
    states = {("p1000", "served_3"): _state(), ("p1000", "hold_3"): _state()}
    with pytest.raises(chain.ChainError):
        chain.decide_week(tmp_path, 6, _week(), states, set(), "c", 2)
    assert not (tmp_path / "gw06").exists()


def test_a_record_replays_despite_its_work_and_refuses_a_different_decision(tmp_path: Path) -> None:
    path = tmp_path / "p1000-served_3.json"
    first = {"status": "decided", "plan": {"captain": 7}, "work": {"deterministic_time_used": 1.0}}
    write_document_once(first, path, replay_identity=chain.replay_identity)
    again = {**first, "work": {"deterministic_time_used": 1.0000000000000002}}
    write_document_once(again, path, replay_identity=chain.replay_identity)
    assert json.loads(path.read_text(encoding="utf-8"))["work"] == first["work"]
    with pytest.raises(ConflictingBytesError):
        write_document_once(
            {**first, "plan": {"captain": 8}}, path, replay_identity=chain.replay_identity
        )


# Rules 19 and 26: the lineup is the publication rule's, and one the scorer accepts


def test_the_recorded_lineup_is_the_published_one_and_the_scorer_accepts_it(tmp_path: Path) -> None:
    inputs, horizon, held, rules = _inputs(tmp_path, (2, 3, 4))
    plan, _ = plan_transfer_horizon(
        inputs, horizon, held, rules, optimization=BUDGET, linearization_level=2
    )
    week = plan.weeks[0]
    advice = chain._lineup_block(week)
    published = lineup_fields(week)
    assert advice["captain"] == int(published["captain"]["player_id"])  # type: ignore[index]
    assert advice["vice_captain"] == int(published["vice_captain"]["player_id"])  # type: ignore[index]
    assert advice["bench"] == [int(p["player_id"]) for p in published["bench"]]  # type: ignore[attr-defined]
    squad = [int(p) for p in week.selected_squad.player_id]
    record = {"players": chain.players_block(horizon.table.loc[horizon.table.gameweek == 2], squad)}
    outcomes = pd.DataFrame({"player_id": squad, "total_points": [2] * 15, "minutes": [90] * 15})
    scored, players = score_recorded_advice(record, advice, outcomes)
    assert len(players) == 15 and scored is not None
    assert advice["transfer_hit_points"] == float(week.transfer_hit_points)


# Rules 3, 4 and 39: the frozen source, where the chain writes, when and how often it runs


def _fake_git(monkeypatch: pytest.MonkeyPatch, *, head: str = "b", dirty: str = "") -> None:
    def git(*arguments: str, cwd: Path | None = None) -> str:
        if arguments[:1] == ("status",):
            return dirty
        if arguments[:2] == ("rev-parse", "HEAD"):
            return head
        if arguments[:2] == ("rev-list", "--first-parent"):
            return "1" if arguments[-1] == "a" else "2"
        if arguments[0] == "log":
            assert "--first-parent" in arguments and "--diff-merges=first-parent" in arguments
            path = arguments[-1]
            return (
                "a 2026-10-06T12:00:00+00:00"
                if path == chain.PROTOCOL_FILE
                else "b 2026-10-08T09:00:00+00:00"
            )
        raise AssertionError(arguments)

    monkeypatch.setattr(chain, "_git", git)
    monkeypatch.setattr(chain, "_git_bytes", lambda *arguments: arguments[-1].encode("utf-8"))


def test_the_source_identity_names_the_frozen_commit_and_everything_the_solver_depends_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_git(monkeypatch)
    identity = chain.source_identity()
    assert identity["repository_commit"] == "b"
    expected = hashlib.sha256(f"HEAD:{chain.PROTOCOL_FILE}".encode()).hexdigest()
    assert identity["protocol_sha256"] == expected
    assert set(identity["versions"]) == set(chain.PINNED_PACKAGES)  # type: ignore[arg-type]
    assert identity["python"] and set(identity["platform"]) == {"system", "machine"}  # type: ignore[arg-type]
    assert identity["binding_commits"]["runner"]["commit"] == "b"  # type: ignore[index]


def test_a_run_from_another_commit_or_a_dirty_tree_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_git(monkeypatch, head="later")
    with pytest.raises(chain.ChainError, match="frozen commit b"):
        chain.source_identity()
    _fake_git(monkeypatch, dirty=" M scripts/measure_planner_policy_chain.py")
    with pytest.raises(chain.ChainError, match="not clean"):
        chain.source_identity()


def test_a_frozen_source_whose_window_constants_moved_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain.stated_constants_hold()
    monkeypatch.setattr(chain.window_advice, "WINDOW_DETERMINISTIC_UNITS_PER_WEEK", 25.0)
    with pytest.raises(chain.ChainError, match="WINDOW_DETERMINISTIC_UNITS_PER_WEEK"):
        chain.stated_constants_hold()


def test_the_source_identity_refuses_a_frozen_source_whose_constants_moved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_git(monkeypatch)
    monkeypatch.setattr(chain.window_advice, "WINDOW_LINEARIZATION_LEVEL", 3)
    with pytest.raises(chain.ChainError, match="WINDOW_LINEARIZATION_LEVEL"):
        chain.source_identity()


def test_a_later_run_with_any_other_identity_is_refused(tmp_path: Path) -> None:
    identity = {"protocol": chain.PROTOCOL_ID, "repository_commit": "b", "python": "3.13.5"}
    assert chain.bind_protocol(tmp_path, identity) is None
    write_document_once({**identity, "first_chain_week": 6}, tmp_path / "protocol.json")
    assert chain.bind_protocol(tmp_path, identity)["first_chain_week"] == 6  # type: ignore[index]
    with pytest.raises(chain.ChainError, match="python"):
        chain.bind_protocol(tmp_path, {**identity, "python": "3.13.6"})


def test_the_chain_writes_only_under_its_own_artifact_directory(tmp_path: Path) -> None:
    snapshots, artifacts = tmp_path / "snapshots", tmp_path / "artifacts"
    chain.refuse_output(chain.OUTPUT_ROOT / "2026-27", snapshots, artifacts)
    for output in (
        tmp_path / "chain",
        chain.REPOSITORY / "data" / "chain",
        chain.REPOSITORY / "artifacts" / "football",
    ):
        with pytest.raises(chain.ChainError):
            chain.refuse_output(output, snapshots, artifacts)
    with pytest.raises(chain.ChainError):
        chain.refuse_output(chain.OUTPUT_ROOT / "x", chain.OUTPUT_ROOT, artifacts)


@pytest.mark.parametrize(
    ("moment", "refused"),
    [
        ("2026-10-06T10:00:00+00:00", True),
        ("2026-10-09T10:00:00+00:00", True),
        ("2026-10-05T22:00:00+00:00", True),
        ("2026-10-05T12:00:00+00:00", False),
        ("2026-10-10T12:00:00+00:00", False),
    ],
)
def test_the_decision_step_never_runs_on_a_tuesday_or_friday_operator_time(
    moment: str, refused: bool
) -> None:
    if refused:
        with pytest.raises(chain.ChainError):
            chain.refuse_day(datetime.fromisoformat(moment))
    else:
        chain.refuse_day(datetime.fromisoformat(moment))


def test_one_decision_step_runs_at_a_time(tmp_path: Path) -> None:
    with (
        chain.single_run(tmp_path),
        pytest.raises(chain.ChainError, match="Another decision step"),
        chain.single_run(tmp_path),
    ):
        pass
    assert not (tmp_path / "run.lock").exists()


# Rules 2, 5, 9 and 40: the chain starts once, waits for deadlines and resumes in order


def ROOTS(tmp_path: Path) -> tuple[Path, Path]:
    """A capture root and a football artifact root apart from the chain's own output."""

    return tmp_path / "snapshots", tmp_path / "football"


def _chain_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, weeks: dict[int, object]
) -> tuple[Path, list[tuple[str, int]]]:
    root = tmp_path / "artifacts" / "planner_policy_chain"
    monkeypatch.setattr(chain, "OUTPUT_ROOT", root)
    # These tests decide on the GW6 deadline's own day; rule 40's boundary has its own test.
    monkeypatch.setattr(chain, "FIRST_COMPUTATION", T0 - timedelta(days=30))
    commits = {
        "protocol": {"commit": "a", "committed_utc": "2026-10-06T12:00:00+00:00"},
        "runner": {"commit": "b", "committed_utc": "2026-10-08T09:00:00+00:00"},
    }
    monkeypatch.setattr(
        chain, "source_identity", lambda: {"repository_commit": "b", "binding_commits": commits}
    )
    monkeypatch.setattr(
        chain, "capture_inventory", lambda root: chain.CaptureInventory((), ("late-capture",))
    )
    monkeypatch.setattr(chain, "first_bound_week", lambda index, root, bound: 6)
    monkeypatch.setattr(
        chain, "deadline_of", lambda index, root, week: T0 + timedelta(days=7 * (week - 6))
    )
    monkeypatch.setattr(
        chain, "_week", lambda index, snapshots, artifacts, week, **roots: weeks[week]
    )
    squads = chain.Squads(
        {f"p{budget}": _state() for budget, _, _ in chain.PROFILES},
        {},
        {f"p{budget}": ["OPTIMAL"] for budget, _, _ in chain.PROFILES},
    )
    monkeypatch.setattr(chain, "initial_states", lambda forecast, week: squads)
    solved: list[tuple[str, int]] = []

    def arm(name: str, week: chain.WeekInputs, held: object) -> chain.ArmOutcome:
        gameweek = int(week.inputs.deadline.gameweek)
        solved.append((name, gameweek))
        return _outcome(_plan(_plan_week(gameweek=gameweek)))

    monkeypatch.setattr(chain, "run_arm", arm)
    return root, solved


def test_the_chain_starts_at_the_first_week_with_a_forecast_and_lists_the_skipped_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = ("no_artifact", {"snapshot_id": "capture-gw6", "reason": "no_artifact"})
    root, solved = _chain_world(tmp_path, monkeypatch, {6: missing, 7: _week(7)})
    lines: list[str] = []
    now = T0 + timedelta(days=7, hours=1)
    chain.decide(*ROOTS(tmp_path), root, 7, "issuecomment-1", now=now, emit=lines.append)
    protocol = json.loads((root / "protocol.json").read_text(encoding="utf-8"))
    assert protocol["first_chain_week"] == 7 and protocol["bound_week"] == 6
    assert protocol["skipped_weeks"] == [{"gameweek": 6, "reason": "no_artifact"}]
    assert protocol["answer"] == "issuecomment-1" and protocol["locked_holdout_accessed"] is False
    assert not (root / "gw06").exists() and (root / "gw07" / "manifest.json").exists()
    assert {week for _, week in solved} == {7} and len(solved) == 15
    assert lines[0] == "left out 1 captures taken after every deadline"
    assert lines[-1].startswith("GW07 decided from capture-gw7; manifest sha256 ")
    (logged,) = (root / "runs.log").read_text(encoding="utf-8").splitlines()
    assert logged.startswith(f"{now.isoformat()} b ") and "GW07 decided from capture-gw7" in logged
    manifest = json.loads((root / "gw07" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["work"] == {"decided_at_utc": now.isoformat()}


def test_a_week_whose_deadline_has_not_passed_is_left_for_a_later_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, solved = _chain_world(tmp_path, monkeypatch, {6: _week(6), 7: _week(7)})
    lines: list[str] = []
    early = T0 + timedelta(hours=1)
    chain.decide(*ROOTS(tmp_path), root, 7, "issuecomment-1", now=early, emit=lines.append)
    assert (root / "gw06" / "manifest.json").exists() and not (root / "gw07").exists()
    assert lines[-1] == "GW07 pending: its deadline has not passed"
    first_run = len(solved)
    later = T0 + timedelta(days=7, hours=1)
    chain.decide(*ROOTS(tmp_path), root, 7, "issuecomment-1", now=later, emit=lines.append)
    assert len(solved) == 2 * first_run and {week for _, week in solved[first_run:]} == {7}
    after = json.loads((root / "gw07" / "p1000-served_3.json").read_text(encoding="utf-8"))
    assert after["state_before"]["decided_gameweek"] == 6


def test_before_its_first_deadline_the_chain_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, solved = _chain_world(tmp_path, monkeypatch, {6: _week(6)})
    lines: list[str] = []
    chain.decide(*ROOTS(tmp_path), root, 6, "issuecomment-1", now=T0, emit=lines.append)
    assert not (root / "protocol.json").exists() and solved == []
    assert lines[-1] == "waiting: no first chain week has both a passed deadline and a forecast"


def test_the_decision_step_needs_an_answer_and_a_permitted_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = _chain_world(tmp_path, monkeypatch, {6: _week(6)})
    later = T0 + timedelta(hours=1)
    with pytest.raises(chain.ChainError, match="Answer"):
        chain.decide(*ROOTS(tmp_path), root, 6, " ", now=later)
    tuesday = datetime(2026, 10, 13, 10, 0, tzinfo=UTC)
    with pytest.raises(chain.ChainError, match="Tuesday"):
        chain.decide(*ROOTS(tmp_path), root, 6, "issuecomment-1", now=tuesday)
    assert not root.exists()


def test_check_labels_each_week_pending_or_final_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = (_entry("capture-gw6", -20, 6), _entry("capture-gw7", 100, 7, deadline_hours=168))
    monkeypatch.setattr(chain, "capture_index", lambda root: index)
    monkeypatch.setattr(
        chain,
        "binding_commits",
        lambda: {"runner": {"commit": "b", "committed_utc": "2026-10-08T09:00:00+00:00"}},
    )
    monkeypatch.setattr(chain, "first_bound_week", lambda index, root, bound: 6)
    monkeypatch.setattr(
        chain, "deadline_of", lambda index, root, week: T0 + timedelta(days=7 * (week - 6))
    )
    monkeypatch.setattr(
        chain,
        "week_inputs",
        lambda root, artifacts, snapshot_id, **roots: (
            _week(6) if snapshot_id == "capture-gw6" else ("no_artifact", {})
        ),
    )
    lines: list[str] = []
    chain.check(tmp_path, tmp_path, now=T0 + timedelta(hours=1), emit=lines.append)
    assert lines[:3] == [
        "GW06 final capture-gw6 ready",
        "GW07 pending capture-gw7 no_artifact",
        "GW08 pending missing no_own_target_capture",
    ]
    assert list(tmp_path.iterdir()) == []


# Review 4: post-season captures, the real artifact root, the inventory, the lapse, the receipt


def test_a_capture_after_the_last_deadline_is_left_out_and_listed(tmp_path: Path) -> None:
    root = tmp_path / "snapshots"
    _capture(root, captured_at="2026-08-13T20:11:43Z")
    _capture(root, captured_at="2026-08-25T09:00:00Z")
    late = _capture(root, captured_at="2026-08-29T09:00:00Z")
    inventory = chain.capture_inventory(root)
    assert [entry.target for entry in inventory.entries] == [1, 2]
    assert inventory.closed == (late.metadata.snapshot_id,)
    assert chain.capture_index(root) == inventory.entries


def test_a_capture_named_before_the_season_is_never_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "snapshots"
    old = _capture(root, captured_at="2026-03-01T09:00:00Z")
    current = _capture(root, captured_at="2026-08-13T20:11:43Z")
    opened: list[str] = []
    real = chain.read_snapshot

    def tracked(snapshot_root: Path, snapshot_id: str) -> object:
        opened.append(snapshot_id)
        return real(snapshot_root, snapshot_id)

    monkeypatch.setattr(chain, "read_snapshot", tracked)
    entries = chain.capture_index(root)
    assert opened == [current.metadata.snapshot_id]
    assert [entry.snapshot_id for entry in entries] == [current.metadata.snapshot_id]
    assert old.metadata.snapshot_id not in opened


def test_the_chain_writes_beside_the_served_artifacts_but_never_among_them() -> None:
    artifacts = chain.REPOSITORY / "artifacts"
    snapshots = chain.REPOSITORY / "data" / "snapshots"
    chain.refuse_output(chain.OUTPUT_ROOT, snapshots, artifacts)
    with pytest.raises(chain.ChainError):
        chain.refuse_output(chain.OUTPUT_ROOT, artifacts, artifacts)
    with pytest.raises(chain.ChainError, match="football"):
        chain.refuse_output(chain.OUTPUT_ROOT / "football" / "x", snapshots, chain.OUTPUT_ROOT)


def test_each_weeks_receipt_lists_every_capture_that_targeted_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = (_entry("second", 3, 6), _entry("first", 1, 6), _entry("other", 2, 7))
    monkeypatch.setattr(
        chain, "week_inputs", lambda root, artifacts, snapshot_id, **roots: _week(6)
    )
    week = chain._week(index, Path("."), Path("."), 6)
    assert isinstance(week, chain.WeekInputs)
    assert [entry["snapshot_id"] for entry in week.receipt["own_target_captures"]] == [
        "first",
        "second",
    ]
    missing = chain._week(index, Path("."), Path("."), 8)
    assert missing[1]["own_target_captures"] == []  # type: ignore[index]


def test_no_chain_starts_after_gameweek_21s_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, solved = _chain_world(tmp_path, monkeypatch, {6: _week(6)})
    late = T0 + timedelta(days=7 * 15, hours=1)
    with pytest.raises(chain.ChainError, match="lapsed unrun"):
        chain.decide(*ROOTS(tmp_path), root, 6, "issuecomment-1", now=late)
    assert not (root / "protocol.json").exists() and solved == []
    assert "refused: No chain started" in (root / "runs.log").read_text(encoding="utf-8")


def test_a_week_whose_capture_choice_changed_is_refused_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chain, "run_arm", lambda *a: _outcome(_plan(_plan_week())))
    write_document_once({"snapshot_id": "capture-earlier"}, tmp_path / "gw06" / "receipt.json")
    states = {("p1000", "served_3"): _state()}
    with pytest.raises(chain.ChainError, match="capture-earlier"):
        chain.decide_week(tmp_path, 6, _week(), states, set(), "c", 2)


def test_the_receipt_names_the_archive_seasons_and_training_rows(tmp_path: Path) -> None:
    snapshots, artifacts, snapshot_id = _served(tmp_path)
    path = football_artifact_path(artifacts, snapshot_id)
    stamp = path.stat().st_mtime
    document = json.loads(path.read_text(encoding="utf-8"))
    document["archive_hashes"] = {"2022-23/teams.csv": "a", "2025-26/teams.csv": "b"}
    document["training_rows"] = 1234
    document["fingerprint"] = forecast_digest(document)
    path.write_text(json.dumps(document), encoding="utf-8")
    os.utime(path, (stamp, stamp))
    week = chain.week_inputs(snapshots, artifacts, snapshot_id)
    assert isinstance(week, chain.WeekInputs)
    assert week.receipt["forecast_archive_seasons"] == ["2022-23", "2025-26"]
    assert week.receipt["forecast_training_rows"] == 1234


def test_bytes_that_do_not_carry_their_own_fingerprint_are_a_missing_week(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshots, artifacts, snapshot_id = _served(tmp_path)
    path = football_artifact_path(artifacts, snapshot_id)
    forecast = chain.read_football_forecast(
        path, read_inputs(chain.read_snapshot(snapshots, snapshot_id), season=chain.SEASON)
    )
    stamp = path.stat().st_mtime
    document = json.loads(path.read_text(encoding="utf-8"))
    document["rows"][0]["expected_points"] = 99.0
    path.write_text(json.dumps(document), encoding="utf-8")
    os.utime(path, (stamp, stamp))
    monkeypatch.setattr(chain, "read_football_forecast", lambda path, inputs: forecast)
    reason, _ = chain.week_inputs(snapshots, artifacts, snapshot_id)  # type: ignore[misc]
    assert reason == "artifact_unreadable_or_unbound"


def test_an_artifact_that_cannot_be_read_now_stops_the_run_instead_of_missing_the_week(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshots, artifacts, snapshot_id = _served(tmp_path)

    def locked(path: object, inputs: object) -> object:
        raise PermissionError("The process cannot access the file.")

    monkeypatch.setattr(chain, "read_football_forecast", locked)
    with pytest.raises(chain.ChainError, match="cannot be read now"):
        chain.week_inputs(snapshots, artifacts, snapshot_id)


# Rules 8 and 38: what the runner never reads or records


def test_the_runner_reads_no_outcome_and_records_no_member() -> None:
    source = chain.RUNNER_PATH.read_text(encoding="utf-8")
    for name in ("live_event_outcomes", "score_recorded_advice", "weekly_suggestion_eval"):
        assert name not in source
    for name in ("entry_id", "league_id", "data/entries", "archive_history", "_experiment_cli"):
        assert name not in source


def test_every_record_says_it_read_no_outcome_and_no_holdout() -> None:
    assert chain._record(gameweek=6) == {
        "protocol": chain.PROTOCOL_ID,
        "season": chain.SEASON,
        "outcome_read": False,
        "locked_holdout_accessed": False,
        "gameweek": 6,
    }


# Rules 9 to 11 and 39: the runner's constants are the protocol's


def test_the_runners_constants_are_the_protocols() -> None:
    assert chain.PROFILES == ((1000, 1000, 1), (950, 1000, 2), (900, 900, 0))
    assert chain.ARMS == ("served_3", "served_5", "hold_3", "hold_5", "one_week")
    assert (chain.UNITS_PER_WEEK, chain.HOLD_PROBE_UNITS, chain.SQUAD_RETRY_UNITS) == (
        20.0,
        1.0,
        240.0,
    )
    assert chain.SQUAD_CONFIG.bench_weight == 0
    assert chain.SQUAD_CONFIG.solver_time_limit_seconds == 120
    assert chain.SQUAD_CONFIG.solver_deterministic_time_limit == 60
    assert frozenset({1, 4}) == chain.REFUSED_WEEKDAYS
    assert chain.OPERATOR_ZONE.utcoffset(None) == timedelta(hours=3)
    assert chain.OUTPUT_ROOT == chain.REPOSITORY / "artifacts" / "planner_policy_chain"
    matrix = chain.REPOSITORY / "scripts" / "measure_shortlist_matrix.py"
    assert "(1000, 1000, 1), (950, 1000, 2), (900, 900, 0)" in matrix.read_text(encoding="utf-8")
    for phrase in (
        "squad budgets of 1000, 950 and 900 tenths",
        "total funds of 1000, 1000 and 900",
        "one, two and zero free transfers",
        "59 and 99, plus the 1-unit hold probe",
        "at twenty deterministic units per forecast week",
        "A squad not proved OPTIMAL at 60 units is built once more at 240.",
        "never on a Tuesday or Friday",
        "writes only under `artifacts/planner_policy_chain/`",
    ):
        assert phrase in PROTOCOL_TEXT
