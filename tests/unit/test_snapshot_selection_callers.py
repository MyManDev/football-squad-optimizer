"""How the remaining callers pick "the latest capture" out of a root three collectors share.

The companion to ``test_snapshot_selection_cli.py``, which covers the operator shells. These
are the callers inside the application and platform layers, plus the scripts the shells do
not reach: the same defect, found in the same sweep.

A snapshot identifier is ``{source}-{stamp}-{digest}``, so a lexical listing orders by
collector name before it orders by capture time. ``fpl-top100`` sorts *after* every
``fpl-live`` identifier however old it is, so a caller taking the last entry gets a cohort
capture; ``fpl-elite-picks`` sorts *before* every ``fpl-live`` one, so a caller taking the
first entry gets an elite-picks capture. Those are the two halves of one bug, and a fixture
pinning either has to use a source that really does sort on the side being tested.

Each capture here is written to ``tmp_path`` rather than read from ``data/snapshots/``,
which is gitignored: a test that needed a real capture would pass only on the machine that
took one.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest
import scripts.build_scoreboard as scoreboard_cli
import scripts.measure_capture_season_phase as measure_cli
import scripts.record_preseason_difficulty as record_cli
import scripts.run_week as run_week
import scripts.seed_entry_registry as seed_cli

from squadopt.application.commands import _resolve_snapshot as resolve_for_decide
from squadopt.application.horizon_plans import _resolve_snapshot as resolve_for_horizon
from squadopt.data.errors import DataError
from squadopt.data.snapshots import write_snapshot
from squadopt.data.sources.fpl_live import league_standings_payload
from squadopt.experiments import ExperimentError
from squadopt.platform.capture_context import latest_snapshot_id
from squadopt.platform.cli import _snapshot_files

LEAGUE_ID = 352490
EARLY_LIVE_AT = "2026-08-14T09:00:00Z"
LIVE_AT = "2026-08-21T15:00:00Z"
COHORT_AT = "2026-01-01T12:00:00Z"
ELITE_AT = "2026-09-07T13:11:33Z"


def _live(root: Path, captured_at: str = LIVE_AT) -> str:
    """A live capture: the game-state payloads, and the league standings page."""

    return write_snapshot(
        root,
        source="fpl-live",
        captured_at_utc=captured_at,
        payloads={
            "bootstrap-static.json": b"{}",
            "fixtures.json": b"[]",
            league_standings_payload(LEAGUE_ID): b"{}",
        },
    ).snapshot_id


def _cohort(root: Path, *, captured_at: str = COHORT_AT) -> str:
    """A Top-100 capture, which sorts *after* every live one. None of the game state."""

    return write_snapshot(
        root,
        source="fpl-top100",
        captured_at_utc=captured_at,
        payloads={"league-352490-standings-page-1.json": b"{}"},
    ).snapshot_id


def _elite(root: Path, *, captured_at: str = ELITE_AT) -> str:
    """An elite-picks capture, which sorts *before* every live one, however recent."""

    return write_snapshot(
        root,
        source="fpl-elite-picks",
        captured_at_utc=captured_at,
        payloads={"entry-1-picks.json": b"{}"},
    ).snapshot_id


# --- squadopt.application.commands ---------------------------------------------------


def test_deciding_resolves_the_latest_live_capture(tmp_path: Path) -> None:
    """A decide reads prices, availability and the deadline calendar; a cohort holds none.

    This automatic branch is not on the operator's own path: ``squadopt decide`` resolves
    the capture in ``platform.cli._snapshot_files`` first and hands ``DecideRequest`` the
    concrete identifier, so a normal run reaches this only through a programmatic caller
    that passes ``snapshot_id=None``. Read the test as covering that entry point, not the
    scheduled one — ``test_a_bare_decide_takes_the_latest_live_capture`` below is the CLI.
    """

    live = _live(tmp_path)
    _cohort(tmp_path)

    assert resolve_for_decide(tmp_path, None)[0] == live


def test_deciding_still_replays_a_capture_named_outright(tmp_path: Path) -> None:
    """Filtering the automatic pick must not narrow what an operator may name.

    The membership check and the "Held:" hint stay about everything on disk, so a cohort
    capture is still replayable and a misspelling still reports what is really there.
    """

    _live(tmp_path)
    cohort = _cohort(tmp_path)

    assert resolve_for_decide(tmp_path, cohort)[0] == cohort
    with pytest.raises(DataError, match="No snapshot"):
        resolve_for_decide(tmp_path, "fpl-live-20260101T000000Z-000000000000")


def test_deciding_from_a_cohort_only_root_asks_for_a_live_capture(tmp_path: Path) -> None:
    _cohort(tmp_path)

    with pytest.raises(DataError, match="No fpl-live snapshots"):
        resolve_for_decide(tmp_path, None)


# --- squadopt.application.horizon_plans ----------------------------------------------


def test_the_horizon_plan_resolves_the_latest_live_capture(tmp_path: Path) -> None:
    """Reached by a normal run: ``scripts.plan_transfer_horizon`` and the batch runner
    both default ``--snapshot-id`` to ``None``, so this is what a plan without one uses."""

    live = _live(tmp_path)
    _cohort(tmp_path)

    assert resolve_for_horizon(tmp_path, None)[0] == live


def test_the_horizon_plan_still_replays_a_capture_named_outright(tmp_path: Path) -> None:
    _live(tmp_path)
    cohort = _cohort(tmp_path)

    assert resolve_for_horizon(tmp_path, cohort)[0] == cohort


# --- squadopt.platform.capture_context -----------------------------------------------


def test_the_adapter_serves_advice_from_the_latest_live_capture(tmp_path: Path) -> None:
    """The HTTP adapter has no ``--snapshot-id``: this pick is the whole of what it serves.

    ``backend_runtime`` calls this per request to decide which capture it holds an identity
    for, so an unfiltered pick would serve every caller advice built on the Top-100 cohort.
    """

    live = _live(tmp_path)
    _cohort(tmp_path)

    assert latest_snapshot_id(tmp_path) == live


def test_a_cohort_only_root_reads_as_not_ready_rather_than_ready(tmp_path: Path) -> None:
    """``None`` is "no capture to serve", which the adapter reports as unready.

    Answering from a cohort capture would be worse than answering nothing: it looks ready.
    """

    _cohort(tmp_path)

    assert latest_snapshot_id(tmp_path) is None


# --- squadopt.platform.cli -----------------------------------------------------------


def test_a_bare_decide_takes_the_latest_live_capture(tmp_path: Path) -> None:
    """``squadopt decide`` with no ``--snapshot-id``: the run log's inputs and the capture
    the decision is actually made from are both this identifier."""

    live = _live(tmp_path)
    _cohort(tmp_path)

    identifier, files = _snapshot_files(tmp_path, None)

    assert identifier == live
    assert all(path.is_file() for path in files)


def test_a_named_capture_is_still_found_whatever_took_it(tmp_path: Path) -> None:
    _live(tmp_path)
    cohort = _cohort(tmp_path)

    assert _snapshot_files(tmp_path, cohort)[0] == cohort


# --- scripts.seed_entry_registry -----------------------------------------------------


def test_the_seed_reads_standings_from_the_latest_live_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a live capture carries the classic-league standings payload.

    The cohort capture holds standings *pages* under a different name, so before the fix
    this did not merely pick oddly, it failed: the chosen capture carried no
    ``league-{id}-standings.json`` at all.
    """

    live = _live(tmp_path)
    _cohort(tmp_path)
    monkeypatch.setattr(seed_cli, "SNAPSHOT_ROOT", tmp_path)

    _payload, origin = seed_cli._standings_bytes(
        league_id=LEAGUE_ID, snapshot_id=None, standings_file=None
    )

    assert origin == f"snapshot {live}"


def test_the_seed_still_reads_a_capture_named_outright(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An older live capture is a legitimate thing to seed from, so naming one works even
    though it is not the automatic pick."""

    older = _live(tmp_path, EARLY_LIVE_AT)
    _live(tmp_path)
    monkeypatch.setattr(seed_cli, "SNAPSHOT_ROOT", tmp_path)

    _payload, origin = seed_cli._standings_bytes(
        league_id=LEAGUE_ID, snapshot_id=older, standings_file=None
    )

    assert origin == f"snapshot {older}"


def test_the_seed_reports_a_root_holding_no_live_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cohort(tmp_path)
    monkeypatch.setattr(seed_cli, "SNAPSHOT_ROOT", tmp_path)

    with pytest.raises(DataError, match="No fpl-live snapshots"):
        seed_cli._standings_bytes(league_id=LEAGUE_ID, snapshot_id=None, standings_file=None)


# --- scripts.record_preseason_difficulty ---------------------------------------------


def _record_argv(root: Path, output: Path) -> list[str]:
    return [
        "record_preseason_difficulty",
        "--snapshot-root",
        str(root),
        "--json-output",
        str(output / "difficulty.json"),
        "--markdown-output",
        str(output / "difficulty.md"),
    ]


def test_the_preseason_record_takes_the_earliest_live_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mirror image of the "last entry" bug: this one takes the *first* entry.

    ``fpl-elite-picks`` sorts before ``fpl-live``, so the unfiltered first entry was the
    elite-picks capture no matter how recently it was taken — the opposite of the earliest
    capture this wants, and one holding no fixtures to rate. Wanting the earliest is why
    it takes ``[0]`` rather than ``[-1]``; it still has to say which source it means.
    """

    early = _live(tmp_path, EARLY_LIVE_AT)
    _live(tmp_path)
    _elite(tmp_path)

    read: list[str] = []

    def _record(root: Path, identifier: str, *, season: str) -> None:
        read.append(identifier)
        raise ExperimentError("read no further; this test is about the selection")

    monkeypatch.setattr(record_cli, "build_preseason_record", _record)
    monkeypatch.setattr(sys, "argv", _record_argv(tmp_path, tmp_path))

    assert record_cli.main() == 1
    assert read == [early], read


def test_the_preseason_record_still_reads_a_capture_named_outright(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    elite = _elite(tmp_path)
    _live(tmp_path)

    read: list[str] = []

    def _record(root: Path, identifier: str, *, season: str) -> None:
        read.append(identifier)
        raise ExperimentError("read no further; this test is about the selection")

    monkeypatch.setattr(record_cli, "build_preseason_record", _record)
    monkeypatch.setattr(sys, "argv", [*_record_argv(tmp_path, tmp_path), "--snapshot-id", elite])

    assert record_cli.main() == 1
    assert read == [elite], read


def test_the_preseason_record_reports_a_root_holding_no_live_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _elite(tmp_path)
    monkeypatch.setattr(sys, "argv", _record_argv(tmp_path, tmp_path))

    assert record_cli.main() == 1


# --- scripts.run_week ----------------------------------------------------------------


def test_the_weekly_loop_finds_the_latest_live_capture(tmp_path: Path) -> None:
    """This one was already correct, and this test passes before the change as well as after.

    ``run_week`` hand-filtered with a fourth copy of the ``fpl-live-`` prefix; the change
    is a dedupe onto ``FPL_LIVE_SOURCE`` and ``list_snapshot_ids(source=...)``, so there is
    no behaviour here that was ever wrong. The test exists to hold the dedupe to the
    behaviour it replaced: drop the ``source=`` argument and it fails.
    """

    live = _live(tmp_path)
    _cohort(tmp_path)
    _elite(tmp_path)

    assert run_week.latest_live_snapshot(tmp_path) == live


def test_the_weekly_loop_reports_no_live_capture_as_none(tmp_path: Path) -> None:
    _cohort(tmp_path)

    assert run_week.latest_live_snapshot(tmp_path) is None


# --- scripts.build_scoreboard ---------------------------------------------------------


def test_the_scoreboard_resolves_the_latest_live_capture(tmp_path: Path) -> None:
    """Like ``run_week``'s, this one was already right and passes before the change too.

    ``build_scoreboard`` was merged between the two passes of the sweep and kept its own
    copy of the ``fpl-live-`` prefix, hand-filtering an unfiltered listing. The change is a
    dedupe onto ``FPL_LIVE_SOURCE`` and ``list_snapshot_ids(source=...)``; this holds it to
    the behaviour it replaced, so dropping the ``source=`` argument fails it.
    """

    live = _live(tmp_path)
    _cohort(tmp_path)
    _elite(tmp_path)

    assert scoreboard_cli.resolve_live_snapshot_id(tmp_path, None) == live


def test_the_scoreboard_still_reads_a_capture_named_outright(tmp_path: Path) -> None:
    _live(tmp_path)
    cohort = _cohort(tmp_path)

    assert scoreboard_cli.resolve_live_snapshot_id(tmp_path, cohort) == cohort
    with pytest.raises(DataError, match="No snapshot"):
        scoreboard_cli.resolve_live_snapshot_id(tmp_path, "fpl-live-20260101T000000Z-000000000000")


def test_the_scoreboard_reports_a_root_holding_no_live_capture(tmp_path: Path) -> None:
    _cohort(tmp_path)

    with pytest.raises(DataError, match="No fpl-live-\\* snapshots"):
        scoreboard_cli.resolve_live_snapshot_id(tmp_path, None)


# --- scripts.measure_capture_season_phase ---------------------------------------------


def test_the_phase_measurement_reads_live_captures_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The last ``iterdir`` reader of a snapshot root, and the one the sweep missed.

    It indexes ``bootstrap-static.json`` and ``fixtures.json`` on every directory it finds,
    and only a live capture carries both: an elite-picks capture holds picks documents and
    no bootstrap, a cohort capture a bootstrap and no fixtures. Since the weekly loop began
    writing both into this root, the documented invocation died on a bare ``KeyError``
    before a single capture was measured.
    """

    live = _live(tmp_path)
    _cohort(tmp_path)
    _elite(tmp_path)
    read: list[str] = []

    def _phase(bootstrap: bytes, fixtures: bytes, *, captured_at_utc: str) -> object:
        raise ExperimentError("read no further; this test is about the selection")

    def _snapshot(root: Path, identifier: str) -> object:
        read.append(identifier)
        return original(root, identifier)

    original = measure_cli.read_snapshot
    monkeypatch.setattr(measure_cli, "read_snapshot", _snapshot)
    monkeypatch.setattr(measure_cli, "capture_season_phase", _phase)
    monkeypatch.setattr(
        measure_cli,
        "_archive_season_totals",
        lambda *_arguments, **_keywords: pd.DataFrame(
            {"player_id": [], "archive_total_points": [], "archive_minutes": []}
        ),
    )

    with pytest.raises(ExperimentError):
        measure_cli.measure(tmp_path, tmp_path / "archive")

    assert read == [live], read
