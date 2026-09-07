"""The weekly command's pure half: the plan, the decide pre-flight, the snapshot-by-difference
rule, the parser."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import scripts.run_week as run_week
from scripts.run_week import (
    CHIP_CHOICES,
    STEPS,
    WeekError,
    _wrote_paths,
    new_snapshot,
    plan_week,
    preflight_decide,
)

from squadopt.live import LedgerError


def _plan(**overrides: object):  # type: ignore[no-untyped-def]
    fields: dict[str, object] = {
        "season": "2026-27",
        "gameweek": 4,
        "league_id": 352490,
        "snapshot_id": None,
        "cohort_snapshot": None,
        "elite_snapshot": None,
        "skip_top100": False,
        "publish": False,
        "decide": False,
        "chip": None,
    }
    fields.update(overrides)
    return plan_week(**fields)  # type: ignore[arg-type]


def test_a_fresh_week_runs_every_producing_step_and_leaves_publishing_to_a_flag() -> None:
    plan = _plan()
    # Top-100 first: the projection refuses evidence captured after the decision capture.
    # The scoreboard last: it reads the ledger and the tree the earlier steps wrote.
    assert plan.steps == ("top100", "capture", "handoff", "league", "site", "scoreboard")
    assert "publish" in plan.reasons
    assert "decide" in plan.reasons
    assert "publish" in plan.describe()


def test_a_named_capture_skips_capturing_and_says_which_one_it_reuses() -> None:
    plan = _plan(
        snapshot_id="fpl-live-20260911T100000Z-abc123def456",
        cohort_snapshot="fpl-top100-x",
        elite_snapshot="fpl-elite-picks-y",
    )
    assert "capture" not in plan.steps
    assert "fpl-live-20260911T100000Z-abc123def456" in plan.reasons["capture"]


def test_a_reused_capture_refuses_fresh_top100_captures() -> None:
    """Evidence captured after the decision capture is refused at the handoff, so the
    plan refuses the combination up front rather than an hour in."""

    with pytest.raises(WeekError, match="taken before it"):
        _plan(snapshot_id="fpl-live-20260911T100000Z-abc123def456")
    plan = _plan(snapshot_id="fpl-live-20260911T100000Z-abc123def456", skip_top100=True)
    assert plan.steps == ("handoff", "league", "site", "scoreboard")


def test_skipping_top100_removes_the_whole_step() -> None:
    plan = _plan(skip_top100=True)
    assert "top100" not in plan.steps
    assert plan.reasons["top100"] == "--skip-top100"


def test_reused_top100_captures_still_run_the_export() -> None:
    plan = _plan(cohort_snapshot="fpl-top100-x", elite_snapshot="fpl-elite-picks-y")
    assert "top100" in plan.steps
    assert "export reused" in plan.reasons["top100"]


def test_publish_is_the_last_step_when_asked() -> None:
    assert _plan(publish=True).steps[-1] == "publish"


def test_deciding_our_squad_sits_between_the_handoff_and_the_league_tree() -> None:
    """The decision needs the handoff; the site views read the ledger the decision
    writes; so it runs after the one and before the other — and only when asked."""

    plan = _plan(decide=True)
    steps = list(plan.steps)
    assert steps.index("handoff") < steps.index("decide") < steps.index("league")
    assert steps.index("site") < steps.index("scoreboard")
    assert "decide" not in plan.reasons
    assert plan.steps == tuple(step for step in STEPS if step != "publish")


def test_a_chip_needs_the_decision_it_would_be_played_in() -> None:
    with pytest.raises(WeekError, match="needs --decide"):
        _plan(chip="bboost")
    assert _plan(decide=True, chip="bboost").steps.count("decide") == 1
    with pytest.raises(WeekError, match="must be one of"):
        _plan(decide=True, chip="manager")


def test_the_chip_choices_are_the_ones_the_decide_command_offers() -> None:
    assert set(CHIP_CHOICES) == {"bboost", "3xc", "wildcard", "freehit"}
    assert list(CHIP_CHOICES) == sorted(CHIP_CHOICES)


@pytest.mark.parametrize("gameweek", [0, 1, 39])
def test_the_opening_week_and_impossible_weeks_are_refused(gameweek: int) -> None:
    with pytest.raises(WeekError):
        _plan(gameweek=gameweek)


# --- the decide pre-flight, before any capture is spent --------------------------------


def test_an_empty_ledger_cannot_start_a_mid_season_gameweek(tmp_path: Path) -> None:
    with pytest.raises(WeekError, match="cannot supply the squad GW4 starts from"):
        preflight_decide(tmp_path / "ledger", "2026-27", 4)


def test_a_gameweek_the_ledger_already_holds_is_refused_before_capturing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        run_week,
        "load_ledger",
        lambda root, season: (SimpleNamespace(gameweek=3), SimpleNamespace(gameweek=4)),
    )
    with pytest.raises(WeekError, match="already holds 2026-27 GW4"):
        preflight_decide(tmp_path / "ledger", "2026-27", 4)


def test_a_ledger_missing_the_previous_gameweek_is_refused_with_the_ledgers_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        run_week, "load_ledger", lambda root, season: (SimpleNamespace(gameweek=1),)
    )

    def refuse(root: Path, season: str, *, before_gameweek: int, budget_tenths: int) -> None:
        raise LedgerError("No decision recorded for 2026-27 GW3; the ledger holds [1].")

    monkeypatch.setattr(run_week, "held_squad_from_ledger", refuse)
    with pytest.raises(WeekError, match="GW3; the ledger holds"):
        preflight_decide(tmp_path / "ledger", "2026-27", 4)


def test_a_ledger_that_can_start_the_gameweek_passes_the_pre_flight(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        run_week, "load_ledger", lambda root, season: (SimpleNamespace(gameweek=3),)
    )
    asked: list[int] = []

    def supply(root: Path, season: str, *, before_gameweek: int, budget_tenths: int) -> object:
        asked.append(before_gameweek)
        return object()

    monkeypatch.setattr(run_week, "held_squad_from_ledger", supply)
    preflight_decide(tmp_path / "ledger", "2026-27", 4)
    assert asked == [4]


# --- the snapshot-by-difference rule and the producers' own lines ----------------------


def test_the_new_snapshot_is_found_by_difference_and_prefix() -> None:
    before = ["fpl-live-a", "fpl-top100-a"]
    after = [*before, "fpl-top100-b"]
    assert new_snapshot(before, after, "fpl-top100-") == "fpl-top100-b"
    with pytest.raises(WeekError, match="exactly one"):
        new_snapshot(before, before, "fpl-top100-")
    with pytest.raises(WeekError, match="exactly one"):
        new_snapshot(before, [*after, "fpl-top100-c"], "fpl-top100-")
    # A live capture appearing meanwhile is not the cohort capture.
    with pytest.raises(WeekError, match="exactly one"):
        new_snapshot(before, [*before, "fpl-live-b"], "fpl-top100-")


def test_the_evidence_paths_are_read_from_the_producers_own_lines() -> None:
    output = (
        "Wrote artifacts/phase_b/player_evidence_v1_2026-27_gw04_top100.csv\n"
        "      artifacts/phase_b/player_evidence_v1_2026-27_gw04_top100.manifest.json\n"
        "  contract          player_evidence_v1 / player_evidence_export_v1\n"
    )
    assert _wrote_paths(output) == [
        Path("artifacts/phase_b/player_evidence_v1_2026-27_gw04_top100.csv"),
        Path("artifacts/phase_b/player_evidence_v1_2026-27_gw04_top100.manifest.json"),
    ]
    assert _wrote_paths("  contract   x.json\n") == []
