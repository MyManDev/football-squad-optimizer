"""The weekly command's pure half: the plan, the snapshot-by-difference rule, the parser."""

from pathlib import Path

import pytest
from scripts.run_week import WeekError, _wrote_paths, new_snapshot, plan_week


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
    }
    fields.update(overrides)
    return plan_week(**fields)  # type: ignore[arg-type]


def test_a_fresh_week_runs_every_producing_step_and_leaves_publishing_to_a_flag() -> None:
    plan = _plan()
    # Top-100 first: the projection refuses evidence captured after the decision capture.
    assert plan.steps == ("top100", "capture", "handoff", "league", "site")
    assert "publish" in plan.reasons
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
    assert plan.steps == ("handoff", "league", "site")


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


@pytest.mark.parametrize("gameweek", [0, 1, 39])
def test_the_opening_week_and_impossible_weeks_are_refused(gameweek: int) -> None:
    with pytest.raises(WeekError):
        _plan(gameweek=gameweek)


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
