"""The HiGHS window protocol is held to the code and the committed inputs it names.

The protocol is written before any solve, so its numbers are claims about the repository as
it stands: the production budget, the pinned solver versions, the capture and the published
statuses. A later change to any of them fails here rather than quietly moving the
measurement's ground.
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from typing import Any

from squadopt.application import advice
from squadopt.application.advice import solve_window_plan
from squadopt.live.transfers import plan_transfer_horizon
from squadopt.optimization.optimizer import configure_solver

REPOSITORY = Path(__file__).resolve().parents[2]
PROTOCOL = REPOSITORY / "docs" / "window_solver_highs_prereg.md"
LEAGUE = REPOSITORY / "web" / "public" / "data" / "league"
CAPTURE = "fpl-live-20261002T104314Z-8b70515b9b31"


def _text() -> str:
    return re.sub(r"\s+", " ", PROTOCOL.read_text(encoding="utf-8"))


def _section(heading: str) -> str:
    text = PROTOCOL.read_text(encoding="utf-8")
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert match is not None, f"The protocol has no section {heading!r}."
    return re.sub(r"\s+", " ", match.group(1))


def _payload(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    payload = document.get("payload", document)
    assert isinstance(payload, dict)
    return payload


def test_the_cp_sat_budget_is_the_production_one() -> None:
    assert advice.WINDOW_DETERMINISTIC_UNITS_PER_WEEK == 20.0
    assert advice.WINDOW_WALL_CEILING_SECONDS == 1800.0
    assert advice.WINDOW_LINEARIZATION_LEVEL == 2
    budgets = _section("Solvers and budgets")
    assert "linearization level 2" in budgets
    assert "20 deterministic units per week" in budgets
    assert "the 1,800 s wall ceiling" in budgets
    for name in (
        "WINDOW_DETERMINISTIC_UNITS_PER_WEEK",
        "WINDOW_WALL_CEILING_SECONDS",
        "WINDOW_LINEARIZATION_LEVEL",
    ):
        assert f"`{name}`" in budgets
    assert configure_solver.__name__ in budgets
    assert plan_transfer_horizon.__name__ in _section("Instances")
    assert solve_window_plan.__name__ in _section("Instances")


def test_the_solver_versions_are_the_pinned_ones() -> None:
    package = json.loads((REPOSITORY / "web" / "package.json").read_text(encoding="utf-8"))
    assert package["dependencies"]["highs"] == "1.15.3"
    pins = (REPOSITORY / "constraints.txt").read_text(encoding="utf-8")
    assert "ortools==9.15.6755" in pins
    budgets = _section("Solvers and budgets")
    assert "`ortools` as `constraints.txt` pins it (9.15.6755)" in budgets
    assert "`highspy` 1.15.3" in budgets
    assert "the `highs` 1.15.3 package `web/package.json` pins" in budgets
    assert "`mip_rel_gap` 0 and `mip_abs_gap` 0.5" in budgets


def test_the_instances_are_the_committed_gw6_inputs() -> None:
    plan = _payload(LEAGUE / "device-plan.json")
    assert plan["source_snapshot_id"] == CAPTURE
    assert plan["gameweek"] == 6
    entries = sorted((LEAGUE / "entries").glob("*.json"))
    assert len(entries) == 15
    assert all(_payload(entry).get("device_plan") for entry in entries)
    instances = _section("Instances")
    assert f"`{CAPTURE}`" in instances
    assert "the 15 members of league 352490 at GW6" in instances
    assert "30 instances" in instances
    assert "No gitignored store is read." in instances


def test_the_published_window_statuses_are_as_stated() -> None:
    counts: dict[int, dict[str, int]] = {}
    for window in (3, 5):
        for path in (LEAGUE / "advice").glob(f"*/saf-puan/{window}.json"):
            status = str(_payload(path)["solver_status"])
            counts.setdefault(window, {}).setdefault(status, 0)
            counts[window][status] += 1
    assert counts == {3: {"OPTIMAL": 15}, 5: {"OPTIMAL": 2, "FEASIBLE": 13}}
    read = _section("What has been read")
    assert "15 three-week plans, all OPTIMAL" in read
    assert "15 five-week plans, 2 OPTIMAL and 13 FEASIBLE" in read


def test_every_path_the_protocol_names_exists() -> None:
    """A wrong path would let the protocol point at inputs nobody can read."""

    later = {
        "scripts/measure_window_solver_highs.py",  # its own pull request, after this one
        "docs/research/window_solver_highs.json",  # the record the run writes
    }
    named = re.findall(r"`((?:docs|src|scripts|web|tests)/[\w/.{},*-]+)`", _text())
    assert named
    for path in named:
        if path in later or "*" in path or "{" in path:
            continue
        assert (REPOSITORY / path).exists(), path
    for module in (
        "live/horizon.py",
        "live/transfers.py",
        "planning/optimizer.py",
        "application/advice.py",
        "optimization/optimizer.py",
    ):
        assert f"`{module}`" in _text(), module
        assert (REPOSITORY / "src" / "squadopt" / module).is_file(), module


def test_the_calendar_is_flat_and_every_input_is_the_same_capture() -> None:
    fixtures = _payload(REPOSITORY / "web" / "public" / "data" / "fixtures.json")
    assert fixtures["source_snapshot_id"] == CAPTURE
    weeks = {int(week["gameweek"]): week for week in fixtures["gameweeks"]}
    for gameweek in range(6, 11):
        counts: dict[int, int] = {}
        for fixture in weeks[gameweek]["fixtures"]:
            for side in ("home", "away"):
                team = int(fixture[side]["team_id"])
                counts[team] = counts.get(team, 0) + 1
        assert len(counts) == 20 and set(counts.values()) == {1}, gameweek
    documents = [
        *(LEAGUE / "entries").glob("*.json"),
        *(LEAGUE / "advice").glob("*/saf-puan/*.json"),
    ]
    assert documents
    for path in documents:
        payload = _payload(path)
        assert payload["source_snapshot_id"] == CAPTURE, path
        assert payload["league_id"] == 352490, path
    assert "every club has one fixture in each of GW6 to GW10" in _section("Instances")


def test_the_model_is_the_path_the_published_member_windows_take() -> None:
    """The member-menu windows run `optimize_transfer_plan` with the hold protection at level
    2, because their projection is not the football candidate's; the football route is out."""

    assert "linearization_level=WINDOW_LINEARIZATION_LEVEL" in inspect.getsource(solve_window_plan)
    horizon_source = inspect.getsource(plan_transfer_horizon)
    assert "protect_hold=True" in horizon_source
    assert 'projection_horizon.model_name == "fixture_football_candidate"' in horizon_source
    for path in (LEAGUE / "advice").glob("*/saf-puan/[35].json"):
        limits = " ".join(str(limit) for limit in _payload(path)["stated_limits"])
        assert "The first week's projection is repeated over the later weeks" in limits, path
    instances = _section("Instances")
    assert "`optimize_transfer_plan`" in instances
    assert "with `protect_hold=True`, linearization level 2" in instances
    assert "The football windows' guarded, expected and observed route is not measured." in (
        instances
    )


def test_the_verdicts_and_their_checks_are_fixed_before_any_solve() -> None:
    verdicts = _section("Verdicts")
    for clause in (
        "The thresholds are fixed here and not changed after the data.",
        "No solution, an error or a crash counts as not proved.",
        "proves all 15 three-week instances and at least 14 of the 15 five-week instances, "
        "each proof within 15 s of wall time on this machine",
        "in the wall-matched run, proves every instance CP-SAT proves, at CP-SAT's value",
        "proves at least half of the five-week instances CP-SAT's rerun leaves FEASIBLE "
        "(with none, this condition fails)",
        "on no instance ends with a primary value below CP-SAT's",
        "No run substitutes for another.",
    ):
        assert clause in verdicts, clause
    check = _section("The exporter and its checks")
    assert "the exporter is wrong and the run stops with no verdict" in check
    assert "fixed in the CP-SAT model, is feasible there" in check
    assert "differ by at most 1,000 units (0.001 points)" in check
    assert 'makes the verdict "the models disagree", which replaces both verdicts' in check
    budgets = _section("Solvers and budgets")
    assert "each solver computes the hold model's optimum itself" in budgets
    assert "A CP-SAT run stopped by the wall ceiling counts as not proved" in budgets
    assert "must equal the published `saf-puan/1.json` for all 15 members" in _text()
    assert "No solve runs on 9 or 10 October (UTC)." in _text()
    assert "`planning/**` is Astra's lane" in _section("What a result licenses")
