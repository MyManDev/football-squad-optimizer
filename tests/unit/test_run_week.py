"""The weekly command's pure half: the plan, the decide pre-flight, the mode the decision
is stamped with, the snapshot-by-difference rule, the parser."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import scripts.run_week as run_week
from scripts.run_week import (
    CHIP_CHOICES,
    MODE_RULE,
    STEPS,
    WeekError,
    _wrote_paths,
    check_evidence_for_reused_capture,
    decision_mode_for,
    evidence_artifact,
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
    """The plan names the captures it reuses and does not claim the export is reused too.

    Whether the export is reused depends on what is on disk, which ``plan_week`` does not
    read; saying "export reused" unconditionally was false exactly when it mattered — the
    run that then re-exported and was refused at the handoff.
    """

    plan = _plan(cohort_snapshot="fpl-top100-x", elite_snapshot="fpl-elite-picks-y")
    assert "top100" in plan.steps
    assert plan.reasons["top100"] == "reusing fpl-top100-x and fpl-elite-picks-y"


# --- the other half of "the evidence must predate the decision capture" ----------------


def test_a_reused_capture_refuses_when_its_evidence_export_is_not_on_disk(
    tmp_path: Path,
) -> None:
    """``apply_elite_evidence`` checks the artifact's generation time as well as the
    evidence's capture time, and a re-export is stamped with the wall clock — which is
    always after a capture already taken. Refused up front rather than after the export."""

    with pytest.raises(WeekError, match="already on disk"):
        check_evidence_for_reused_capture(
            tmp_path,
            season="2026-27",
            gameweek=4,
            elite_snapshot="fpl-elite-picks-20260911T091000Z-bbbbbbbbbbbb",
            snapshot_id="fpl-live-20260911T100000Z-abc123def456",
        )


def test_a_reused_capture_with_its_export_already_on_disk_is_allowed(tmp_path: Path) -> None:
    table, manifest = evidence_artifact(
        tmp_path, "2026-27", 4, "fpl-elite-picks-20260911T091000Z-bbbbbbbbbbbb"
    )
    assert table.name == "player_evidence_v1_2026-27_gw04_top100_bbbbbbbbbbbb.csv"
    table.write_text("player_id\n1\n", encoding="utf-8")
    manifest.write_text("{}", encoding="utf-8")

    check_evidence_for_reused_capture(
        tmp_path,
        season="2026-27",
        gameweek=4,
        elite_snapshot="fpl-elite-picks-20260911T091000Z-bbbbbbbbbbbb",
        snapshot_id="fpl-live-20260911T100000Z-abc123def456",
    )


def test_a_half_written_export_does_not_count_as_reusable(tmp_path: Path) -> None:
    table, _manifest = evidence_artifact(
        tmp_path, "2026-27", 4, "fpl-elite-picks-20260911T091000Z-bbbbbbbbbbbb"
    )
    table.write_text("player_id\n1\n", encoding="utf-8")

    with pytest.raises(WeekError, match="already on disk"):
        check_evidence_for_reused_capture(
            tmp_path,
            season="2026-27",
            gameweek=4,
            elite_snapshot="fpl-elite-picks-20260911T091000Z-bbbbbbbbbbbb",
            snapshot_id="fpl-live-20260911T100000Z-abc123def456",
        )


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


def test_a_gameweek_the_ledger_already_holds_skips_the_decision_and_keeps_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A run that decided and then died in the league build must be able to rebuild the
    rest of the week. The recorded decision is immutable, which is exactly why the tree,
    the site and the scoreboard can safely re-run around it: the step is skipped with its
    reason, not refused with the whole run."""

    monkeypatch.setattr(
        run_week,
        "load_ledger",
        lambda root, season: (SimpleNamespace(gameweek=3), SimpleNamespace(gameweek=4)),
    )
    skip = preflight_decide(tmp_path / "ledger", "2026-27", 4)
    assert skip is not None
    assert "already holds 2026-27 GW4" in skip
    assert "immutable" in skip


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


def _held(chips_used: dict[str, tuple[int, ...]] | None = None) -> SimpleNamespace:
    return SimpleNamespace(decided_gameweek=3, chips_used=chips_used or {})


def _ledger_can_start(monkeypatch: pytest.MonkeyPatch, held: SimpleNamespace) -> list[int]:
    monkeypatch.setattr(
        run_week, "load_ledger", lambda root, season: (SimpleNamespace(gameweek=3),)
    )
    asked: list[int] = []

    def supply(root: Path, season: str, *, before_gameweek: int, budget_tenths: int) -> object:
        asked.append(before_gameweek)
        return held

    monkeypatch.setattr(run_week, "held_squad_from_ledger", supply)
    return asked


def test_a_ledger_that_can_start_the_gameweek_passes_the_pre_flight(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    asked = _ledger_can_start(monkeypatch, _held())
    assert preflight_decide(tmp_path / "ledger", "2026-27", 4) is None
    assert asked == [4]


# --- the chip, checked before the week's captures are spent ----------------------------


class _Windows:
    """The chip availability the season rules publish, as the pre-flight consumes it."""

    def __init__(self, weeks: dict[str, frozenset[int]]) -> None:
        self._weeks = weeks

    def gameweeks_for(self, chip: str) -> frozenset[int]:
        return self._weeks.get(chip, frozenset())


def test_a_chip_outside_its_window_is_refused_before_a_capture_is_spent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``build_transfer_recommendation`` asks exactly this an hour later, after the
    Top-100 captures, the live capture and the handoff are all spent."""

    _ledger_can_start(monkeypatch, _held())
    monkeypatch.setattr(run_week, "chip_availability_for", lambda rules, weeks, used: _Windows({}))
    with pytest.raises(WeekError, match="cannot be played in GW4"):
        preflight_decide(tmp_path / "ledger", "2026-27", 4, chip="bboost", rules=SimpleNamespace())


def test_a_chip_already_played_is_refused_and_the_message_says_when(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _ledger_can_start(monkeypatch, _held({"bboost": (2,)}))
    seen: list[object] = []

    def availability(rules: object, weeks: object, used: object) -> _Windows:
        seen.append(used)
        return _Windows({})

    monkeypatch.setattr(run_week, "chip_availability_for", availability)
    with pytest.raises(WeekError, match=r"bboost.*\[2\]"):
        preflight_decide(tmp_path / "ledger", "2026-27", 4, chip="bboost", rules=SimpleNamespace())
    assert seen == [{"bboost": (2,)}], "the ledger's own chips_used answers the question"


def test_a_chip_inside_an_open_window_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _ledger_can_start(monkeypatch, _held())
    monkeypatch.setattr(
        run_week,
        "chip_availability_for",
        lambda rules, weeks, used: _Windows({"bboost": frozenset({4})}),
    )
    assert (
        preflight_decide(tmp_path / "ledger", "2026-27", 4, chip="bboost", rules=SimpleNamespace())
        is None
    )


def test_a_chip_cannot_be_checked_without_rules_so_it_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _ledger_can_start(monkeypatch, _held())
    with pytest.raises(WeekError, match="cannot be checked before the capture"):
        preflight_decide(tmp_path / "ledger", "2026-27", 4, chip="bboost", rules=None)


# --- the mode the decision is stamped with ---------------------------------------------


def test_a_capture_taken_by_this_run_before_its_deadline_is_live() -> None:
    assert (
        decision_mode_for(
            reused_capture=False,
            deadline_utc="2026-09-12T12:30:00Z",
            now_utc="2026-09-12T11:00:00Z",
        )
        == "live"
    )


def test_a_reused_capture_is_a_replay_however_early_the_clock_is() -> None:
    """``commands.decide``'s own rule, which the loop used to override by asserting
    ``mode="live"`` unconditionally."""

    assert (
        decision_mode_for(
            reused_capture=True,
            deadline_utc="2026-09-12T12:30:00Z",
            now_utc="2026-09-12T11:00:00Z",
        )
        == "replay"
    )


@pytest.mark.parametrize("now", ["2026-09-12T12:30:00Z", "2026-09-12T18:00:00Z"])
def test_a_decision_recorded_at_or_after_the_deadline_is_a_replay(now: str) -> None:
    """A catch-up run from a pre-deadline capture is an honest record of what the model
    would have said; calling it live would claim it was said before the deadline."""

    assert (
        decision_mode_for(reused_capture=False, deadline_utc="2026-09-12T12:30:00Z", now_utc=now)
        == "replay"
    )


def test_the_mode_rule_is_stated_where_the_pre_flight_prints_it() -> None:
    assert "reused" in MODE_RULE and "replay" in MODE_RULE and "deadline" in MODE_RULE


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
